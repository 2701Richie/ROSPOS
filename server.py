#!/usr/bin/env python3
"""ROSPOS server. Python standard library only, nothing to install.
Run:  python3 server.py   then open http://<laptop-ip>:8000 on any tablet or PC."""
import getpass, gzip, hashlib, hmac, json, math, os, re, secrets, sqlite3, sys, threading, time, traceback
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from poscore.values import (MAX_NUM, R, now, day_shift, valid_day, valid_expiry, max_sale_no,
                            good_num, _no_constant, _finite_float)
from poscore.archive_store import merge_day_archive
from poscore.history import (no_cost, read_receipt_day, build_report_sales_history,
                             sold_quantities_last_30_days)
from poscore.audit_queries import AuditQueryError, query_audit_events
from poscore.audit_events import (json_value as _json_value,
                                  legacy_event_key as _legacy_event_key,
                                  legacy_timestamp as _legacy_timestamp,
                                  new_operation_id, prepare_sale_events,
                                  sale_source_key as _sale_source_key)
from poscore.auth_sessions import (hash_password as hash_pw, public_account as acct,
                                   create_session, resolve_session)
from poscore.state_views import public_state, cashier_state, current_sales_state
from poscore.storage import open_database, read_key, write_key, persist_state
from poscore import settings_service
from poscore import restore_service
from poscore import purchases_service
from poscore import inventory_service
from poscore import sales_service
from poscore import accounts_service

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("POS_DB", os.path.join(HERE, "data", "pos.db"))
BACKUP_DIR = os.environ.get("POS_BACKUP_DIR", os.path.join(HERE, "backups"))
ARCHIVE_DIR = os.environ.get("POS_ARCHIVE_DIR", os.path.join(HERE, "archives"))
try:
    HOT_DAYS = max(1, int(os.environ.get("POS_HOT_DAYS", "7")))  # sales/audit older than this leave live state
except ValueError:
    HOT_DAYS = 7
PORT = int(os.environ.get("POS_PORT", "8000"))
LOCK = threading.RLock()


class Err(Exception):
    def __init__(self, code, msg, locked=False):
        self.code, self.msg, self.locked = code, msg, locked


db = open_database(DB_PATH)
PENDING_AUDIT_EVENTS = []


def get(k, default=None):
    """Compatibility wrapper for the configured SQLite key/value store."""
    return read_key(db, k, default)


def put(k, v):
    """Compatibility wrapper for a durable key/value update."""
    return write_key(db, k, v)


S = get("state") or {"p": [], "s": [], "g": []}
# Additive migration: purchases and suppliers live in the existing versioned state blob.
# Existing product/sale IDs and stock are preserved; no separate database migration is needed.
S.setdefault("purchases", [])
S.setdefault("suppliers", [])


PENDING_SALE_REQUEST = None  # (user id, request id, sale number), persisted atomically with the sale


def save():
    """Commit state atomically and restore the last durable snapshot if saving fails.

    A failed SQLite transaction must not leave unsaved stock/sales in memory.
    This recovery is only invoked on errors; normal saves have no extra read.
    """
    global S, PENDING_SALE_REQUEST
    try:
        persist_state(db, S, PENDING_AUDIT_EVENTS, PENDING_SALE_REQUEST)
    except Exception:
        # persist_state rolls back the SQLite transaction. Discard only
        # uncommitted state and its queued events, never invent a successful sale.
        # If the disk is unreadable too, retain the original exception.
        try:
            restored = get("state") or {"p": [], "s": [], "g": []}
            restored.setdefault("purchases", [])
            restored.setdefault("suppliers", [])
            S = restored
            PENDING_AUDIT_EVENTS.clear()
        finally:
            PENDING_SALE_REQUEST = None
        raise
    PENDING_SALE_REQUEST = None


def next_sale_no():
    """Monotonic sale numbers that survive archiving (never reuse a number after old sales leave live state)."""
    n = max(get("sale_seq") or 0, max_sale_no(S["s"])) + 1
    put("sale_seq", n)
    return n


def _merge_day_archive(day, sales, logs):
    """Compatibility wrapper: merge a daily archive at the configured path."""
    return merge_day_archive(ARCHIVE_DIR, day, sales, logs)


def safe_archive():
    """archive_old that never raises: a full disk or bad folder must not stop the POS or its backups. Call under LOCK."""
    try:
        n = archive_old()
        if n:
            print("Archived %d old sale(s) to %s" % (n, ARCHIVE_DIR), flush=True)
        return n
    except Exception as exc:
        traceback.print_exc()
        try:
            record_event("system", "Archive operation failed", entity_type="archive", entity_name="Daily archive",
                         details={"error_type": type(exc).__name__, "message": str(exc)[:500]}, status="failed")
        except Exception:
            pass
        return 0


def archive_old():
    """Move sales and audit rows older than HOT_DAYS into one JSON file per day. Call under LOCK."""
    today = now()[0]
    keep_from = day_shift(today, -HOT_DAYS)  # keep keep_from..today; archive strictly older
    old_sales = [s for s in S["s"] if valid_day(s.get("d")) and s["d"] < keep_from]
    old_logs = [g for g in S["g"] if valid_day(g.get("d")) and g["d"] < keep_from]
    if not old_sales and not old_logs:
        return 0
    # Remember the highest sale number before rows leave live state, so numbers are never reused.
    put("sale_seq", max(get("sale_seq") or 0, max_sale_no(S["s"])))
    by_day_s, by_day_g = {}, {}
    for s in old_sales:
        by_day_s.setdefault(s["d"], []).append(s)
    for g in old_logs:
        by_day_g.setdefault(g["d"], []).append(g)
    for day in sorted(set(by_day_s) | set(by_day_g)):
        _merge_day_archive(day, by_day_s.get(day, []), by_day_g.get(day, []))
    keep_s = {id(s) for s in old_sales}
    keep_g = {id(g) for g in old_logs}
    S["s"] = [s for s in S["s"] if id(s) not in keep_s]
    S["g"] = [g for g in S["g"] if id(g) not in keep_g]
    save()
    return len(old_sales)


SETTING_DEFAULTS = {"store": "", "session_hours": None, "backup_days": 30,
                    "rc_addr": "", "rc_phone": "", "rc_tag": "", "rc_foot": ""}  # rc_*: lines printed on the 58 mm receipt
RC_LIMITS = {"rc_addr": 64, "rc_phone": 32, "rc_tag": 40, "rc_foot": 64}  # max characters per receipt field


def settings():
    """Owner-editable options (Settings tab). Kept apart from sales data, so a restore never changes them."""
    with LOCK:
        cfg = dict(SETTING_DEFAULTS, **(get("settings") or {}))
    if cfg["session_hours"] is None:
        cfg["session_hours"] = SESSION_HOURS
    return cfg


def can_see_cost(actor=None):
    """Product costs are for managers and owners only: staff never receive them from the server.

    Pass the authenticated user explicitly for GET responses; ACTOR is only set
    during POST handlers and is reset afterwards.
    """
    actor = ACTOR if actor is None else actor
    return bool(actor) and ROLES.get(actor.get("role", "staff"), 0) >= ROLES["manager"]


def pub(actor=None):
    """Build the authorized full-state view, including cost restrictions."""
    return public_state(S, can_see_cost(actor), now()[0], settings())


def sell_state(actor):
    """Read model for lightweight catalog and stock polling."""
    return cashier_state(S["p"], can_see_cost(actor), now()[0])


def live_state(actor):
    """Read model for current-day sales polling."""
    return current_sales_state(S["s"], can_see_cost(actor), now()[0])


def cost_of(v):
    """Cost per unit: None (unknown) for blank, else a valid money amount. Anything else is refused."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if not good_num(v):
        raise Err(400, "Enter a valid cost, or leave it blank.")
    return R(v)


def set_cost(x, c):
    if c is None:
        x.pop("c", None)
    else:
        x["c"] = c


def _event_tuple(category, action, actor=None, entity_type="", entity_id="", entity_name="",
                 operation_id="", old_value=None, new_value=None, details=None, status="success",
                 ts=None, source_key=None):
    who = actor if actor is not None else (ACTOR.get("name", "") if ACTOR else "")
    stamp = ts or datetime.now().astimezone().isoformat(timespec="seconds")
    if source_key is None:
        source_key = "event-" + secrets.token_hex(12)
    return (stamp, category, str(action)[:160], str(who)[:120], str(entity_type)[:60],
            "" if entity_id is None else str(entity_id)[:120], str(entity_name or "")[:240],
            str(operation_id or "")[:120], _json_value(old_value), _json_value(new_value),
            json.dumps(details or {}, ensure_ascii=False, separators=(",", ":"), default=str),
            status if status in ("success", "failed", "warning", "info") else "info", source_key)


def record_event(category, action, **kwargs):
    """Persist a non-state event immediately (e.g. login and unexpected server errors)."""
    row = _event_tuple(category, action, **kwargs)
    with LOCK:
        db.execute("""insert or ignore into audit_events
            (ts,category,action,actor,entity_type,entity_id,entity_name,operation_id,old_value,new_value,details,status,source_key)
            values(?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
        db.commit()


def queue_event(category, action, **kwargs):
    PENDING_AUDIT_EVENTS.append(_event_tuple(category, action, **kwargs))


def migrate_legacy_logs():
    """Import pre-Log-Center history once; source keys make startup reruns idempotent."""
    batches = []
    def add_log(g):
        if not isinstance(g, dict):
            return
        d, t = g.get("d"), g.get("t")
        stamp = _legacy_timestamp(d, t)
        action = str(g.get("k", "Legacy inventory event"))
        category = "activity" if g.get("n") == "Settings" else "inventory"
        batches.append(_event_tuple(category, action, actor=g.get("u", ""),
            entity_type="settings" if category == "activity" else "product",
            entity_id=g.get("i", ""), entity_name=g.get("n", ""),
            old_value=g.get("a"), new_value=g.get("z"),
            details={"reason": g.get("w", ""), "migrated": True}, ts=stamp,
            source_key=_legacy_event_key(g)))
    for g in S.get("g", []):
        add_log(g)
    # Existing daily archives are also part of the permanent searchable history.
    if os.path.isdir(ARCHIVE_DIR):
        for name in sorted(os.listdir(ARCHIVE_DIR)):
            if not re.fullmatch(r"sales-\d{4}-\d{2}-\d{2}\.json", name):
                continue
            try:
                with open(os.path.join(ARCHIVE_DIR, name), "r", encoding="utf-8") as fh:
                    archive = json.load(fh)
            except (OSError, ValueError, TypeError):
                continue
            for g in archive.get("g", []) if isinstance(archive, dict) else []:
                add_log(g)
    if batches:
        db.executemany("""insert or ignore into audit_events
            (ts,category,action,actor,entity_type,entity_id,entity_name,operation_id,old_value,new_value,details,status,source_key)
            values(?,?,?,?,?,?,?,?,?,?,?,?,?)""", batches)
        db.commit()


def log(n, k, a, z, pid=None, why="", operation_id="", details=None, audit_values=None):
    d, t = now()
    if pid is None:
        match = next((p for p in S["p"] if p["n"] == n), None)
        pid = match["id"] if match else None
    row = {"d": d, "t": t, "n": n, "k": k, "a": a, "z": z,
           "u": ACTOR["name"] if ACTOR else "", "i": pid, "w": why, "eid": secrets.token_hex(8)}
    S["g"].append(row)
    category = "activity" if n == "Settings" else "inventory"
    audit_old, audit_new = audit_values if audit_values is not None else (a, z)
    queue_event(category, k, actor=row["u"], entity_type="settings" if category == "activity" else "product",
        entity_id=pid, entity_name=n, operation_id=operation_id, old_value=audit_old, new_value=audit_new,
        details=dict({"reason": why} if why else {}, **(details or {})), ts=_legacy_timestamp(d, t), source_key=_legacy_event_key(row))


def _migrate_sale(s, batches):
    """Produce legacy sale audit rows with the server event factory."""
    return prepare_sale_events(s, batches, _event_tuple)


def _insert_event_batch(batches):
    if batches:
        db.executemany("""insert or ignore into audit_events
            (ts,category,action,actor,entity_type,entity_id,entity_name,operation_id,old_value,new_value,details,status,source_key)
            values(?,?,?,?,?,?,?,?,?,?,?,?,?)""", batches)
        db.commit()



migrate_legacy_logs()
_legacy_sale_events = []
for _sale in S.get("s", []):
    _migrate_sale(_sale, _legacy_sale_events)
if os.path.isdir(ARCHIVE_DIR):
    for _name in sorted(os.listdir(ARCHIVE_DIR)):
        if not re.fullmatch(r"sales-\d{4}-\d{2}-\d{2}\.json", _name):
            continue
        try:
            with open(os.path.join(ARCHIVE_DIR, _name), "r", encoding="utf-8") as _fh:
                _archive = json.load(_fh)
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(_archive, dict):
            for _sale in _archive.get("s", []):
                _migrate_sale(_sale, _legacy_sale_events)
_insert_event_batch(_legacy_sale_events)


def prod(i):
    return next((p for p in S["p"] if p["id"] == i), None)


def find_prod(l):
    return prod(l.get("id")) or next((p for p in S["p"] if p["n"] == l["n"]), None)


def nint(v):
    """Whole number from a form field. Blank or unreadable becomes 0; NaN, Infinity and booleans are refused."""
    if isinstance(v, bool) or (isinstance(v, float) and not math.isfinite(v)):
        raise Err(400, "Stock and reorder level must be whole numbers.")
    try:
        return min(MAX_NUM, max(0, int(v)))
    except (TypeError, ValueError):
        return 0


# ---- accounts, sessions, throttling ------------------------------------------
ROLES = {"staff": 1, "manager": 2, "owner": 3}
SESSION_HOURS = float(os.environ.get("POS_SESSION_HOURS", "12"))
SESSIONS, FAILS = {}, {}
ACTOR = None
TOKEN = None  # session token of the request being handled (like ACTOR, only set during POST handlers)
U = get("users") or []
SETUP_CODE = secrets.token_hex(3).upper() if not U else None


def save_users():
    put("users", U)


def set_pw(u, pw):
    u["salt"] = secrets.token_hex(16)
    u["hash"] = hash_pw(pw, u["salt"])


def valid_pw(pw):
    pw = str(pw or "")
    if len(pw) < 8:
        raise Err(400, "Use at least 8 characters for the password.")
    return pw


def throttle(key):
    if FAILS.get(key, (0, 0))[1] > time.time():
        raise Err(429, "Too many wrong attempts. Wait a minute and try again.")


def miss(key):
    if len(FAILS) > 5000:  # attackers can invent endless keys; keep memory bounded
        FAILS.clear()
    n = FAILS.get(key, (0, 0))[0] + 1
    FAILS[key] = (0, time.time() + 60) if n >= 5 else (n, 0)


def check_pw(u, pw, key):
    throttle(key)
    if u and u.get("active", True) and hmac.compare_digest(hash_pw(pw, u["salt"]), u["hash"]):
        FAILS.pop(key, None)
        return True
    if not u:
        hash_pw(pw, "00" * 16)  # same work as a real check, so response time does not reveal which usernames exist
    miss(key)
    return False


def find_user(username):
    un = str(username or "").strip().lower()
    return next((u for u in U if u["username"] == un), None)


def user_by_id(i):
    return next((u for u in U if u["id"] == i), None)


def allow(role):
    if ROLES[ACTOR["role"]] < ROLES[role]:
        raise Err(403, "Your account is not allowed to do this.")


def reauth(ip, b, role="manager"):
    allow(role)
    if not check_pw(ACTOR, str(b.get("password", "")), "re|%s|%s" % (ip, ACTOR["id"])):
        raise Err(403, "Wrong password.")


def new_session(u):
    """Create a token using the current session-lifetime setting."""
    return create_session(u, SESSIONS, settings()["session_hours"])


def session_user(handler):
    """Resolve the signed-in user and invalidate expired/disabled sessions."""
    return resolve_session(handler, SESSIONS, user_by_id)


# ---- operations (each one runs under LOCK and changes nothing if it fails) ---
def sale_out(sale):
    return {"sale": sale if can_see_cost() else dict(sale, l=[no_cost(l) for l in sale["l"]])}


def r_sale(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return sales_service.r_sale(sys.modules[__name__], b, ip)


def r_login(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return accounts_service.r_login(sys.modules[__name__], b, ip)


def r_setup(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return accounts_service.r_setup(sys.modules[__name__], b, ip)


def r_users(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return accounts_service.r_users(sys.modules[__name__], b, ip)


def r_user(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return accounts_service.r_user(sys.modules[__name__], b, ip)


def r_mypw(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return accounts_service.r_mypw(sys.modules[__name__], b, ip)


def r_product(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return inventory_service.r_product(sys.modules[__name__], b, ip)


def r_delete(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return inventory_service.r_delete(sys.modules[__name__], b, ip)


def r_delete_many(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return inventory_service.r_delete_many(sys.modules[__name__], b, ip)


def r_stock(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return inventory_service.r_stock(sys.modules[__name__], b, ip)


def find_sale(no):
    s = None if isinstance(no, bool) else next((s for s in S["s"] if s["no"] == no), None)
    if not s:
        raise Err(404, "Sale not found.")
    return s


def put_back(l, d, action, reason="", operation_id=""):
    p = find_prod(l)
    if p:
        o = p["s"]
        p["s"] = max(0, o + d)
        log(p["n"], action, o, p["s"], p["id"], reason, operation_id=operation_id)
    return bool(p)


def warn_not_restored(s, names, what):
    """The product was deleted after the sale, so its stock cannot be put back. Say so in the log instead of staying silent."""
    queue_event("sales", "Stock not restored (%s)" % what, entity_type="sale", entity_id=s["no"],
                entity_name="Receipt #%s" % s["no"], operation_id="sale-%s" % s["no"],
                details={"products": names, "reason": "Product no longer exists"}, status="warning")


def r_void(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return sales_service.r_void(sys.modules[__name__], b, ip)


def r_change(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return sales_service.r_change(sys.modules[__name__], b, ip)


def r_restore(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return restore_service.r_restore(sys.modules[__name__], b, ip)


def snapshot(tag):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    f = os.path.join(BACKUP_DIR, "%s-%s.db" % (tag, datetime.now().strftime("%Y%m%d-%H%M%S")))
    dst = sqlite3.connect(f)
    db.backup(dst)
    dst.close()
    for old in sorted(x for x in os.listdir(BACKUP_DIR) if x.startswith(tag + "-"))[:-20]:
        os.remove(os.path.join(BACKUP_DIR, old))


_ID_FLOOR = None  # highest product id handed out or seen; None = work it out again from the products


def new_id():
    """Next product id: the clock in milliseconds, but always above every id already used (no list scan per product,
    which made a 5,000-row import take seconds)."""
    global _ID_FLOOR
    if _ID_FLOOR is None:
        _ID_FLOOR = max([p["id"] for p in S["p"] if isinstance(p.get("id"), int)] + [0])
    _ID_FLOOR = max(int(time.time() * 1000), _ID_FLOOR + 1)
    return _ID_FLOOR


def key(n):
    return re.sub(r"[\W_]+", "", n.lower())


def num(v):
    s = str(v or "").replace("\u20b1", "").replace(",", "").strip()
    if not s:
        return None
    x = float(s)
    if not math.isfinite(x) or x < 0 or x > MAX_NUM:
        raise ValueError
    return x


def r_import(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return inventory_service.r_import(sys.modules[__name__], b, ip)


SETTING_LABELS = {"store": "Store name", "session_hours": "Stay signed in (hours)", "backup_days": "Backup days kept",
                  "rc_addr": "Receipt address", "rc_phone": "Receipt phone", "rc_tag": "Receipt tagline", "rc_foot": "Receipt footer message"}


def shown(v):
    return "(not set)" if v == "" else v if isinstance(v, str) else "%g" % v


def r_settings(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return settings_service.r_settings(sys.modules[__name__], b, ip)


def supplier_by_id(i):
    return next((x for x in S.get("suppliers", []) if x.get("id") == i), None)


def r_supplier(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return purchases_service.r_supplier(sys.modules[__name__], b, ip)


def r_purchase(b, ip):
    """Compatibility entry point; the HTTP handler holds LOCK."""
    return purchases_service.r_purchase(sys.modules[__name__], b, ip)


ROUTES = {"/api/settings": r_settings, "/api/sale": r_sale, "/api/product": r_product, "/api/delete": r_delete, "/api/delete-many": r_delete_many, "/api/stock": r_stock,
          "/api/void": r_void, "/api/change": r_change, "/api/restore": r_restore, "/api/import": r_import,
          "/api/users": r_users, "/api/user": r_user, "/api/mypassword": r_mypw,
          "/api/purchase": r_purchase, "/api/supplier": r_supplier}
PUBLIC = {"/api/login": r_login, "/api/setup": r_setup}


def receipt_day_sales(day, include_cost=False, hot_sales=None):
    """Read a date using the configured archive and current sales snapshot."""
    return read_receipt_day(day, ARCHIVE_DIR, S["s"],
                            include_cost=include_cost, hot_sales=hot_sales)


def report_sales_history(selected):
    """Build manager-only reports from daily archives and current sales."""
    return build_report_sales_history(selected, ARCHIVE_DIR, S["s"], now()[0])


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def cookie(self, token, clear=False):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return "pos_session=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d%s" % (
            "" if clear else token, 0 if clear else int(settings()["session_hours"] * 3600), secure)

    def send(self, code, obj=None, body=None, ctype="application/json", cookie=None, disposition=None):
        data = body if body is not None else json.dumps(obj).encode()
        # Browsers automatically decompress gzip; only compress sizeable JSON responses.
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "").lower()
        compressed = code == 200 and disposition is None and "json" in ctype and (
            len(data) >= 1024 and accepts_gzip
        )
        if compressed:
            data = gzip.compress(data, compresslevel=5)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if compressed:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        if getattr(self, "_state_etag", None):
            self.send_header("ETag", self._state_etag)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlsplit(self.path)
        page = parsed.path
        if page == "/api/reorder-sales":
            with LOCK:
                user, _ = session_user(self)
                if not user:
                    return self.send(401, {"error": "Please sign in."})
                # Reorder is accessible to staff; never expose cost or sale details.
                return self.send(200, sold_quantities_last_30_days(ARCHIVE_DIR, S["s"], now()[0]))
        if page in ("/api/report-sales", "/api/receipt-date"):
            with LOCK:
                u, _ = session_user(self)
                if not u:
                    return self.send(401, {"error": "Please sign in."})
                if (page == "/api/report-sales"
                        and ROLES.get(u.get("role", "staff"), 0) < ROLES["manager"]):
                    return self.send(403, {"error": "Sales reports require manager access."})
                requested = parse_qs(parsed.query).get("date", [now()[0]])[0]
                try:
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested):
                        raise ValueError("Invalid date")
                    datetime.strptime(requested, "%Y-%m-%d")
                except (ValueError, TypeError):
                    return self.send(400, {"error": "Choose a valid sales date."})
                if page == "/api/receipt-date":
                    sales, unavailable = receipt_day_sales(requested)
                    return self.send(200, {"date": requested, "sales": sales, "unavailable": unavailable})
                return self.send(200, report_sales_history(requested))
        if page == "/api/logs":
            with LOCK:
                u, _ = session_user(self)
                if not u:
                    return self.send(401, {"error": "Please sign in."})
                if ROLES.get(u.get("role", "staff"), 0) < ROLES["manager"]:
                    return self.send(403, {"error": "Logs are available to authorized managers and owners only."})
                try:
                    result = query_audit_events(db, parse_qs(parsed.query))
                except AuditQueryError as exc:
                    return self.send(400, {"error": str(exc)})
                return self.send(200, result)
        if page == "/api/backup":
            with LOCK:
                u, _ = session_user(self)
                if not u:
                    return self.send(401, {"error": "Please sign in."})
                if u.get("role") != "owner":
                    return self.send(403, {"error": "Only the owner can download a full backup."})
                audit_rows = db.execute("select id,ts,category,action,actor,entity_type,entity_id,entity_name,operation_id,old_value,new_value,details,status,source_key from audit_events order by id").fetchall()
                audit_logs = []
                for row in audit_rows:
                    keys = ("id", "ts", "category", "action", "actor", "entity_type", "entity_id", "entity_name", "operation_id", "old_value", "new_value", "details", "status", "source_key")
                    item = dict(zip(keys, row))
                    for key in ("old_value", "new_value", "details"):
                        try:
                            item[key] = json.loads(item[key]) if item[key] is not None else None
                        except (ValueError, TypeError):
                            pass
                    if not item["source_key"]:
                        fingerprint = json.dumps({k: item.get(k) for k in ("ts", "category", "action", "actor", "entity_type", "entity_id", "entity_name", "operation_id", "old_value", "new_value", "details", "status")}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
                        item["source_key"] = "backup-export-" + hashlib.sha256((str(item["id"]) + fingerprint).encode("utf-8")).hexdigest()
                    audit_logs.append(item)
                payload = {"format": "ROSPOS-backup", "version": 2,
                           "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
                           "data": {"p": S["p"], "s": S["s"], "g": S["g"], "suppliers": S.get("suppliers", []), "purchases": S.get("purchases", []), "logs": audit_logs}}
                filename = "rospos-backup-%s.json" % datetime.now().strftime("%Y-%m-%d-%H%M%S")
                body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                return self.send(200, body=body, ctype="application/json; charset=utf-8",
                                 disposition='attachment; filename="%s"' % filename)
        if page in ("/", "/index.html", "/style.css", "/logo.svg") or re.fullmatch(r"/js/[a-z]+\.js", page):
            name = "index.html" if page == "/" else page.lstrip("/")
            f = os.path.join(HERE, name)
            if os.path.isfile(f):
                ctype = {"html": "text/html", "css": "text/css", "js": "text/javascript", "svg": "image/svg+xml"}[name.rsplit(".", 1)[1]]
                with open(f, "rb") as fh:
                    return self.send(200, body=fh.read(), ctype=ctype + "; charset=utf-8")
        if page in ("/api/me", "/api/state", "/api/sell-state", "/api/live-state"):
            with LOCK:
                u, _ = session_user(self)
                if page == "/api/me":
                    return self.send(200, {"setup": not U, "me": acct(u) if u else None})
                if not u:
                    return self.send(401, {"error": "Please sign in."})
                # Hash the permission-filtered representation, not the raw database.
                # A conditional request saves the entire response when nothing changed.
                payload = ({"state": sell_state(u), "me": acct(u)}
                           if page == "/api/sell-state" else
                           {"state": live_state(u), "me": acct(u)}
                           if page == "/api/live-state" else
                           {"state": pub(u), "me": acct(u)})
                raw = json.dumps(payload).encode()
                self._state_etag = '"' + hashlib.sha256(raw).hexdigest() + '"'
                if self.headers.get("If-None-Match", "") == self._state_etag:
                    return self.send(304, body=b"")
                return self.send(200, body=raw)
        self.send(404, {"error": "Not found."})

    def do_POST(self):
        global ACTOR, TOKEN
        try:
            if self.headers.get("X-Requested-With") != "pos":
                raise Err(403, "Bad request origin.")
            n = int(self.headers.get("Content-Length") or 0)
            if n < 0:
                raise Err(400, "Bad request.")
            max_body = 100_000_000 if urlsplit(self.path).path == "/api/restore" else 20_000_000
            if n > max_body:
                raise Err(413, "Request too large.")
            b = json.loads(self.rfile.read(n) or b"{}", parse_constant=_no_constant, parse_float=_finite_float)
            ip = self.client_address[0]
            with LOCK:
                try:
                    if self.path in PUBLIC:
                        ACTOR = None
                        out = PUBLIC[self.path](b, ip)
                        out["state"] = pub(out.get("me"))
                    elif self.path == "/api/logout":
                        logout_user, token = session_user(self)
                        SESSIONS.pop(token, None)
                        if logout_user:
                            record_event("activity", "Logout", actor=logout_user["name"], entity_type="account",
                                         entity_id=logout_user["id"], entity_name=logout_user["username"])
                        out = {"_clear": True}
                    else:
                        fn = ROUTES.get(self.path)
                        if not fn:
                            raise Err(404, "Not found.")
                        ACTOR, TOKEN = session_user(self)
                        if not ACTOR:
                            raise Err(401, "Please sign in again.")
                        out = fn(b, ip)
                        out["state"] = pub()
                finally:
                    ACTOR = TOKEN = None
            cookie = None
            if "_session" in out:
                cookie = self.cookie(out.pop("_session"))
            if out.pop("_clear", False):
                cookie = self.cookie("", True)
            self.send(200, out, cookie=cookie)
        except Err as e:
            self.send(e.code, {"error": e.msg})
        except (ValueError, KeyError, TypeError, AttributeError):
            self.send(400, {"error": "Bad request."})
        except Exception as exc:
            trace = traceback.format_exc()
            traceback.print_exc()
            try:
                record_event("system", "Unhandled server exception", entity_type="http", entity_name=urlsplit(self.path).path,
                    details={"path": urlsplit(self.path).path, "error_type": type(exc).__name__,
                             "message": str(exc)[:500], "traceback": trace[-4000:]}, status="failed")
            except Exception:
                pass
            self.send(500, {"error": "Server error. See the server log."})


def backup_loop():
    """Archives old sales, rewrites today's backup hourly, keeps the last N daily DB copies (Settings)."""
    while True:
        try:
            with LOCK:
                safe_archive()
            os.makedirs(BACKUP_DIR, exist_ok=True)
            f = os.path.join(BACKUP_DIR, "pos-%s.db" % now()[0])
            with LOCK:
                dst = sqlite3.connect(f + ".tmp")
                db.backup(dst)
                dst.close()
            os.replace(f + ".tmp", f)
            keep = settings()["backup_days"]
            for old in sorted(x for x in os.listdir(BACKUP_DIR) if x.startswith("pos-") and x.endswith(".db"))[:-keep]:
                os.remove(os.path.join(BACKUP_DIR, old))
        except Exception as exc:
            traceback.print_exc()
            try:
                record_event("system", "Automatic backup failed", entity_type="backup", entity_name="Hourly backup",
                             details={"error_type": type(exc).__name__, "message": str(exc)[:500]}, status="failed")
            except Exception:
                pass
        time.sleep(3600)


if __name__ == "__main__":
    if "--reset-password" in sys.argv:
        k = sys.argv.index("--reset-password")
        un = sys.argv[k + 1] if len(sys.argv) > k + 1 else input("Username: ")
        u = find_user(un)
        if not u:
            sys.exit("No account with that username.")
        pw = getpass.getpass("New password (8 or more characters): ")
        try:
            valid_pw(pw)
        except Err as e:
            sys.exit(e.msg)
        set_pw(u, pw)
        u["active"] = True
        save_users()
        print("Password changed. Restart the server now: sudo systemctl restart pos")
        sys.exit(0)
    with LOCK:
        safe_archive()
    threading.Thread(target=backup_loop, daemon=True).start()
    if not U:
        print("FIRST-TIME SETUP CODE: %s  (open the POS in a browser and create the owner account)" % SETUP_CODE, flush=True)
    print("ROSPOS running on port %d. Open http://<this-laptop-ip>:%d on a tablet or PC." % (PORT, PORT), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
