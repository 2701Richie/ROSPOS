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
    """Atomically commit state, audit events and payment idempotency keys."""
    global PENDING_SALE_REQUEST
    persist_state(db, S, PENDING_AUDIT_EVENTS, PENDING_SALE_REQUEST)
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
    rid = b.get("rid")
    if rid is not None:
        if not isinstance(rid, str) or not 8 <= len(rid) <= 64:
            raise Err(400, "Bad request.")
        prior = db.execute("select sale_no from sale_requests where user_id=? and request_id=?", (ACTOR["id"], rid)).fetchone()
        if prior is not None:
            done = next((x for x in S["s"] if x.get("no") == prior[0]), None)
            if done:
                return sale_out(done)
            raise Err(409, "This payment was already recorded. Check Receipts before trying again.")
    agg = {}
    for l in b.get("lines") or []:
        q = l.get("q")
        if not good_num(q, MAX_NUM, whole=True) or q < 1 or not prod(l.get("id")):
            raise Err(400, "Invalid item in the sale.")
        agg[l["id"]] = agg.get(l["id"], 0) + q
    if not agg:
        raise Err(400, "Add a product first.")
    today, t = now()
    lines, tot = [], 0
    for i, q in agg.items():
        p = prod(i)
        if p["e"] and p["e"] < today:
            raise Err(409, "%s is expired and cannot be sold." % p["n"])
        if q > p["s"]:
            raise Err(409, "Not enough stock for %s (only %d left)." % (p["n"], p["s"]))
        line = {"id": i, "n": p["n"], "q": q, "p": p["p"]}
        if p.get("c") is not None:
            line["c"] = p["c"]  # cost at the time of sale, kept for profit reports
        lines.append(line)
        tot += q * p["p"]
    tot = R(tot)
    cash = b.get("cash")
    cash = tot if cash is None else cash
    if not good_num(cash) or cash < tot:
        raise Err(400, "Cash received is less than the total.")
    sale_no = next_sale_no()
    for l in lines:
        p = prod(l["id"])
        old_stock = p["s"]
        p["s"] -= l["q"]
        log(p["n"], "Sale #%d" % sale_no, old_stock, p["s"], p["id"], "Checkout", operation_id="sale-%s" % sale_no)
    sale = {"no": sale_no, "d": today, "t": t, "l": lines, "tot": tot, "cash": cash,
            "by": ACTOR["name"], "uid": ACTOR["id"]}
    S["s"].append(sale)
    queue_event("sales", "Sale completed", entity_type="sale", entity_id=sale_no,
                entity_name="Receipt #%s" % sale_no, operation_id="sale-%s" % sale_no,
                new_value=tot, details={"sale": sale}, source_key=_sale_source_key(sale))
    global PENDING_SALE_REQUEST
    if rid is not None:
        PENDING_SALE_REQUEST = (ACTOR["id"], rid, sale_no)
    try:
        save()
    except Exception:
        PENDING_SALE_REQUEST = None
        raise
    return sale_out(sale)


def r_login(b, ip):
    un = str(b.get("username", "")).strip().lower()
    u = find_user(un)
    if not check_pw(u, str(b.get("password", "")), "login|%s|%s" % (ip, un)):
        record_event("activity", "Login failed", actor=un, entity_type="account", entity_name=un,
                     details={"remote": ip}, status="failed")
        raise Err(403, "Wrong username or password.")
    record_event("activity", "Login successful", actor=u["name"], entity_type="account",
                 entity_id=u["id"], entity_name=u["username"], details={"role": u["role"]})
    return {"me": acct(u), "_session": new_session(u)}


def r_setup(b, ip):
    if U:
        raise Err(403, "Setup is already done.")
    throttle("setup|" + ip)
    if not hmac.compare_digest(str(b.get("code", "")).strip().upper(), SETUP_CODE):
        miss("setup|" + ip)
        raise Err(403, "Wrong setup code. It is printed in the server log.")
    un, name = str(b.get("username", "")).strip().lower(), " ".join(str(b.get("name", "")).split())
    if not re.fullmatch(r"[a-z0-9._-]{3,30}", un) or not name:
        raise Err(400, "Enter your name and a username of 3 to 30 letters or numbers.")
    u = {"id": 1, "username": un, "name": name, "role": "owner", "active": True}
    set_pw(u, valid_pw(b.get("password")))
    U.append(u)
    save_users()
    record_event("activity", "Owner account created", actor=name, entity_type="account",
                 entity_id=u["id"], entity_name=un, details={"role": "owner"})
    return {"me": acct(u), "_session": new_session(u)}


def r_users(b, ip):
    allow("owner")
    return {"users": [acct(u) for u in U]}


def r_user(b, ip):
    allow("owner")
    i, un = b.get("id"), str(b.get("username", "")).strip().lower()
    name, role, pw = " ".join(str(b.get("name", "")).split()), b.get("role"), str(b.get("password") or "")
    active = bool(b.get("active", True))
    if role not in ROLES:
        raise Err(400, "Pick a role.")
    if not name:
        raise Err(400, "Enter a name.")
    creating = not bool(i)
    if i:
        u = user_by_id(i)
        if not u:
            raise Err(404, "Account not found.")
        before_user = acct(u)
    else:
        if not re.fullmatch(r"[a-z0-9._-]{3,30}", un):
            raise Err(400, "Username must be 3 to 30 letters, numbers, dots, dashes or underscores.")
        if find_user(un):
            raise Err(409, "That username is taken.")
        valid_pw(pw)
        u = {"id": max([x["id"] for x in U] + [0]) + 1, "username": un}
    others = [x for x in U if x is not u and x["role"] == "owner" and x.get("active", True)]
    if u.get("role") == "owner" and (role != "owner" or not active) and not others:
        raise Err(409, "There must always be one active owner.")
    if pw:
        valid_pw(pw)
    u.update(name=name, role=role, active=active)
    if pw:
        set_pw(u, pw)
    if u not in U:
        U.append(u)
    if not active or (pw and u["id"] != ACTOR["id"]):
        for t in [t for t, s in SESSIONS.items() if s["id"] == u["id"]]:
            del SESSIONS[t]
    save_users()
    record_event("activity", "Account created" if creating else "Account updated", entity_type="account",
                 entity_id=u["id"], entity_name=u.get("username", un),
                 old_value=None if creating else before_user,
                 new_value={"name": u["name"], "role": u["role"], "active": u["active"]},
                 details={"password_reset": bool(pw)})
    return {"users": [acct(x) for x in U]}


def r_mypw(b, ip):
    if not check_pw(ACTOR, str(b.get("old", "")), "pw|%s|%s" % (ip, ACTOR["id"])):
        raise Err(403, "Wrong current password.")
    set_pw(ACTOR, valid_pw(b.get("new")))
    for t in [t for t, v in SESSIONS.items() if v["id"] == ACTOR["id"] and t != TOKEN]:
        del SESSIONS[t]  # other tablets signed in as this user must sign in again with the new password
    save_users()
    record_event("activity", "Password changed", entity_type="account", entity_id=ACTOR["id"],
                 entity_name=ACTOR.get("username", ""), details={"self_service": True})
    return {}


def r_product(b, ip):
    allow("manager")
    n, p = str(b.get("n", "")).strip(), b.get("p")
    if not n or not good_num(p):
        raise Err(400, "Enter a product name and a valid price.")
    e, m, i = str(b.get("e") or "").strip(), nint(b.get("m")), b.get("id")
    if not valid_expiry(e):
        raise Err(400, "Enter a valid expiry date, or leave it blank.")
    if len(n) > 200:
        raise Err(400, "Product name must be 200 characters or fewer.")
    k, own = key(n), (prod(i) if i else None)
    if k and not (i and not own):
        clash = next((p for p in S["p"] if p is not own and key(p["n"]) == k), None)
        if clash and (own is None or key(own["n"]) != k):  # an old duplicate may still be edited without renaming it
            raise Err(409, "A product named '%s' already exists." % clash["n"])
    has_c = "c" in b
    c = cost_of(b.get("c")) if has_c else None  # checked before anything changes
    if i:
        x = prod(i)
        if not x:
            raise Err(404, "Product not found.")
        before_fields = {k: x.get(k) for k in ("n", "p", "c", "e", "m")}
        if R(p) != x["p"]:
            log(x["n"], "Price changed", x["p"], R(p))
        if has_c and c != x.get("c"):
            log(x["n"], "Cost changed", x.get("c") or 0, c or 0, x["id"],
                audit_values=(x.get("c"), c))
            set_cost(x, c)
        x.update(n=n, p=R(p), e=e, m=m)
        field_names = {"n": "Product name", "e": "Expiry date", "m": "Reorder level"}
        for field, label in field_names.items():
            if before_fields.get(field) != x.get(field):
                queue_event("inventory", label + " changed", entity_type="product", entity_id=x["id"],
                    entity_name=x["n"], old_value=before_fields.get(field), new_value=x.get(field),
                    details={"field": field})
    else:
        s, i = nint(b.get("s")), int(time.time() * 1000)
        while prod(i):
            i += 1
        newp = {"id": i, "n": n, "p": R(p), "s": s, "e": e, "m": m}
        set_cost(newp, c)
        S["p"].append(newp)
        queue_event("inventory", "Product created", entity_type="product", entity_id=i, entity_name=n,
                    new_value={"name": n, "price": R(p), "cost": c, "stock": s, "reorder": m, "expiry": e})
        if s:
            log(n, "New product +%d" % s, 0, s, i, "Initial stock")
    save()
    return {}


def r_delete(b, ip):
    allow("manager")
    x = prod(b.get("id"))
    if not x:
        raise Err(404, "Product not found.")
    why = str(b.get("why", "")).strip()
    if not why:
        raise Err(400, "Enter a reason for deleting this product.")
    log(x["n"], "Deleted", x["s"], 0, x["id"], why,
        details={"product_snapshot": {k: x.get(k) for k in ("id", "n", "p", "c", "s", "e", "m")}})
    S["p"].remove(x)
    save()
    return {}


def r_delete_many(b, ip):
    """Delete several products at once (manager and owner). All or nothing; one audit row per product; sales history is kept."""
    allow("manager")
    ids = b.get("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100000:
        raise Err(400, "Select between 1 and 100000 products to delete.")
    if any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
        raise Err(400, "The selection is not valid.")
    why = str(b.get("why", "")).strip()
    if not why:
        raise Err(400, "Enter a reason for deleting these products.")
    # Validate the complete selection before changing anything, then replace the
    # product list in one operation. This makes the persisted set explicit.
    selected = list(dict.fromkeys(ids))
    by_id = {p.get("id"): p for p in S["p"]}
    if any(i not in by_id for i in selected):
        raise Err(404, "A selected product no longer exists. Nothing was deleted.")
    items = [by_id[i] for i in selected]
    snapshot("pre-bulk-delete")
    operation_id = new_operation_id("bulk-delete")
    queue_event("inventory", "Bulk deletion started", entity_type="operation", entity_id=operation_id,
                entity_name="Delete %d products" % len(items), operation_id=operation_id,
                details={"selected": len(items), "reason": why})
    for x in items:
        log(x["n"], "Deleted", x["s"], 0, x["id"], why, operation_id=operation_id,
            details={"product_snapshot": {k: x.get(k) for k in ("id", "n", "p", "c", "s", "e", "m")}})
    selected_set = set(selected)
    S["p"] = [p for p in S["p"] if p.get("id") not in selected_set]
    save()
    # Guard against a persistence regression: success only if the saved state
    # no longer contains any selected product IDs.
    saved = get("state") or {}
    if any(p.get("id") in selected_set for p in saved.get("p", [])):
        record_event("system", "Bulk deletion persistence verification failed", entity_type="operation",
                     entity_id=operation_id, entity_name="Delete products", operation_id=operation_id,
                     details={"selected": len(items)}, status="failed")
        raise Err(500, "Bulk delete could not be saved. Please retry or contact the owner.")
    record_event("inventory", "Bulk deletion completed", entity_type="operation", entity_id=operation_id,
                 entity_name="Delete %d products" % len(items), operation_id=operation_id,
                 details={"deleted": len(items), "reason": why})
    return {"msg": "Deleted %d product%s." % (len(items), "" if len(items) == 1 else "s")}


def r_stock(b, ip):
    allow("manager")
    p, v, mode = prod(b.get("id")), str(b.get("v", "")).strip(), b.get("mode")
    if not p:
        raise Err(404, "Product not found.")
    if not (v.isascii() and v.isdigit()) or int(v) > MAX_NUM or (mode == "add" and int(v) < 1):
        raise Err(400, "Type a whole number first" + (" (1 or more)." if mode == "add" else "."))
    o = p["s"]
    z = o + int(v) if mode == "add" else int(v)
    if z > MAX_NUM:
        raise Err(400, "That count is too large.")
    if z == o:
        raise Err(400, "The count did not change.")
    why = str(b.get("why", "")).strip() or ("Stock received" if mode == "add" else "Stock count correction")
    p["s"] = z
    log(p["n"], "Received +%s" % v if mode == "add" else "Count set", o, z, p["id"], why)
    save()
    return {"msg": "%s: %d \u2192 %d" % (p["n"], o, z)}


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
    reauth(ip, b)
    s, why = find_sale(b.get("no")), str(b.get("why", "")).strip()
    if s.get("v"):
        raise Err(409, "This sale is already void.")
    if not why:
        raise Err(400, "Enter a reason.")
    gone = [l["n"] for l in s["l"] if not put_back(l, l["q"], "Void sale #%d" % s["no"], why, operation_id="sale-%s" % s["no"])]
    d, t = now()
    s["v"] = {"d": d, "t": t, "w": why, "u": ACTOR["name"]}
    queue_event("sales", "Sale voided", entity_type="sale", entity_id=s["no"],
                entity_name="Receipt #%s" % s["no"], operation_id="sale-%s" % s["no"],
                old_value=s.get("tot"), new_value=0,
                details={"reason": why, "void": s["v"]}, source_key="sale-void-%s" % s["no"])
    if gone:
        warn_not_restored(s, gone, "void")
    save()
    if gone:
        return {"msg": "Sale voided. Stock was not restored for deleted products: %s." % ", ".join(gone)}
    return {}


def r_change(b, ip):
    reauth(ip, b)
    s, why, q = find_sale(b.get("no")), str(b.get("why", "")).strip(), b.get("q")
    if s.get("v"):
        raise Err(409, "This sale is void.")
    if not isinstance(q, list) or len(q) != len(s["l"]) or any(not good_num(x, MAX_NUM, whole=True) for x in q):
        raise Err(400, "Quantities must be whole numbers.")
    if not any(q):
        raise Err(400, "Use Void to cancel the whole sale.")
    if not why:
        raise Err(400, "Enter a reason.")
    sub = R(sum(n * l["p"] for n, l in zip(q, s["l"])))
    dc = R(sub * 0.2) if s.get("dc") else 0  # sales made with the old discount keep it
    tot, cash = R(sub - dc), b.get("cash")
    if not good_num(cash) or cash < tot:
        raise Err(400, "Cash received must cover the new total (\u20b1%.2f)." % tot)
    for n, l in zip(q, s["l"]):
        if n > l["q"]:
            p = find_prod(l)
            if not p or n - l["q"] > p["s"]:
                raise Err(409, "Not enough stock for %s." % l["n"])
    old, d, t = s["tot"], *now()
    gone = []
    for n, l in zip(q, s["l"]):
        if n != l["q"] and not put_back(l, l["q"] - n, "Changed sale #%d" % s["no"], why, operation_id="sale-%s" % s["no"]):
            gone.append(l["n"])
    s["l"] = [dict(l, q=n) for n, l in zip(q, s["l"]) if n > 0]
    s.update(tot=tot, cash=cash)
    if s.get("dc"):
        s.update(sub=sub, dc=dc)
    change_record = {"d": d, "t": t, "w": why, "a": old, "z": tot, "u": ACTOR["name"]}
    s.setdefault("h", []).append(change_record)
    queue_event("sales", "Sale amended", entity_type="sale", entity_id=s["no"],
                entity_name="Receipt #%s" % s["no"], operation_id="sale-%s" % s["no"],
                old_value=old, new_value=tot, details={"reason": why, "change": change_record},
                source_key="sale-change-%s-%s" % (s["no"], len(s["h"])))
    if gone:
        warn_not_restored(s, gone, "change")
    save()
    return {"msg": "Sale changed. Stock was not adjusted for deleted products: %s." % ", ".join(gone)} if gone else {}


def r_restore(b, ip):
    global S, _ID_FLOOR
    reauth(ip, b, "owner")
    d = b.get("data") or b
    if not isinstance(d, dict) or not all(isinstance(d.get(k), list) for k in ("p", "s")):
        raise Err(400, "That is not a valid ROSPOS backup.")
    if not isinstance(d.get("g", []), list) or len(d["p"]) > 100000 or len(d["s"]) > 1000000 or len(d.get("g", [])) > 2000000:
        raise Err(400, "This backup has invalid or excessive data.")
    if any(not isinstance(x, dict) or not all(k in x for k in ("id", "n", "p", "s"))
           or not isinstance(x.get("n"), str) or not good_num(x.get("p"))
           or not good_num(x.get("s"), MAX_NUM, whole=True)
           or not (x.get("e") is None or isinstance(x.get("e"), str))
           or not (x.get("m") is None or good_num(x.get("m"), MAX_NUM, whole=True))
           or not (x.get("c") is None or good_num(x.get("c"))) for x in d["p"]):
        raise Err(400, "The backup contains an invalid product record.")
    if any(not isinstance(x, dict) or not all(k in x for k in ("no", "d", "l", "tot"))
           or not good_num(x.get("no"), MAX_NUM, whole=True) or not isinstance(x.get("d"), str)
           or not isinstance(x.get("l"), list) or not good_num(x.get("tot"))
           or any(not isinstance(line, dict) or not all(k in line for k in ("id", "n", "q", "p"))
                  or not good_num(line.get("q"), MAX_NUM, whole=True)
                  or not good_num(line.get("p"))
                  or not (line.get("c") is None or good_num(line.get("c"))) for line in x.get("l", [])) for x in d["s"]):
        raise Err(400, "The backup contains an invalid sale record.")
    if any(not x.get("dc") and abs(R(sum(l["q"] * l["p"] for l in x["l"])) - x["tot"]) > 0.01 for x in d["s"]):
        raise Err(400, "The backup contains a sale whose total does not match its items.")  # would corrupt every report
    if (any(not isinstance(x["id"], int) or isinstance(x["id"], bool) or not x["n"].strip() for x in d["p"])
            or len({x["id"] for x in d["p"]}) != len(d["p"])):
        raise Err(400, "The backup contains a repeated or invalid product id or an empty product name.")
    if len({x["no"] for x in d["s"]}) != len(d["s"]) or any(x["no"] < 1 for x in d["s"]):
        raise Err(400, "The backup contains a repeated or invalid sale number.")
    if any(not isinstance(x, dict) for x in d.get("g", [])):
        raise Err(400, "The backup contains an invalid activity record.")
    audit = d.get("logs", [])
    if not isinstance(audit, list) or len(audit) > 1_000_000:
        raise Err(400, "This backup has invalid or excessive log history.")
    imported_events = []
    for item in audit:
        if (not isinstance(item, dict) or item.get("category") not in ("inventory", "sales", "activity", "system")
                or not isinstance(item.get("ts"), str) or len(item["ts"]) > 64
                or not isinstance(item.get("action"), str) or len(item["action"]) > 160
                or not isinstance(item.get("actor", ""), str)
                or not isinstance(item.get("details", {}), dict)
                or item.get("status", "success") not in ("success", "failed", "warning", "info")):
            raise Err(400, "The backup contains an invalid log record.")
        fingerprint = json.dumps({k: item.get(k) for k in ("ts", "category", "action", "actor", "entity_type", "entity_id", "entity_name", "operation_id", "old_value", "new_value", "details", "status")}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        source_key = item.get("source_key") or ("restored-" + hashlib.sha256((str(item.get("id", "")) + fingerprint).encode("utf-8")).hexdigest())
        imported_events.append(_event_tuple(item["category"], item["action"], actor=item.get("actor", ""),
            entity_type=item.get("entity_type", ""), entity_id=item.get("entity_id", ""),
            entity_name=item.get("entity_name", ""), operation_id=item.get("operation_id", ""),
            old_value=item.get("old_value"), new_value=item.get("new_value"), details=item.get("details", {}),
            status=item.get("status", "success"), ts=item["ts"], source_key=source_key))
    suppliers = d.get("suppliers", [])
    purchases = d.get("purchases", [])
    if (not isinstance(suppliers, list) or not isinstance(purchases, list)
            or len(suppliers) > 100000 or len(purchases) > 1000000):
        raise Err(400, "The backup contains invalid or excessive purchase data.")
    if any(not isinstance(x, dict) or not isinstance(x.get("id"), str) or not isinstance(x.get("name"), str)
           or not x["name"].strip() for x in suppliers):
        raise Err(400, "The backup contains an invalid supplier record.")
    if any(not isinstance(x, dict) or not all(k in x for k in ("id", "product_id", "supplier_id", "quantity", "unit_cost", "total", "date"))
           or not isinstance(x.get("id"), str) or not isinstance(x.get("supplier_id"), str)
           or not isinstance(x.get("quantity"), int) or isinstance(x.get("quantity"), bool) or not 1 <= x["quantity"] <= MAX_NUM
           or not good_num(x.get("unit_cost")) or not good_num(x.get("total")) or not valid_day(x.get("date"))
           for x in purchases):
        raise Err(400, "The backup contains an invalid purchase record.")
    if any(abs(R(x["quantity"] * x["unit_cost"]) - x["total"]) > 0.01 for x in purchases):
        raise Err(400, "The backup contains a purchase whose total does not match its quantity and cost.")
    for x in d["s"]:  # the cash field is display-only; repair a missing or too-small value instead of refusing the whole backup
        if not good_num(x.get("cash")) or x["cash"] < x["tot"]:
            x["cash"] = x["tot"]
    # Keep an immediate database-level recovery point before replacing live data.
    for x in d["p"]:  # older or hand-edited backups may lack these; the app expects them on every product
        if not (isinstance(x.get("e"), str) and valid_expiry(x["e"])):
            x["e"] = ""
        if x.get("m") is None:
            x["m"] = 0
    snapshot("pre-restore")
    old_S, old_pending = S, PENDING_AUDIT_EVENTS[:]
    try:
        PENDING_AUDIT_EVENTS.extend(imported_events)
        S = {"p": d["p"], "s": d["s"], "g": d.get("g", []),
             "suppliers": suppliers, "purchases": purchases}
        _ID_FLOOR = None  # the restored products may use higher ids than any handed out so far
        put("sale_seq", max(get("sale_seq") or 0, max_sale_no(S["s"])))
        safe_archive()
        queue_event("activity", "Backup restored", entity_type="backup", entity_name="Backup restore",
                    details={"products": len(S["p"]), "sales": len(S["s"]), "reason": "Owner-confirmed restore"})
        save()
    except Exception:
        S = old_S  # a failed restore must leave the running POS exactly as it was
        PENDING_AUDIT_EVENTS[:] = old_pending
        raise
    return {"msg": "Backup restored successfully."}


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
    allow("manager")
    mode, rows = b.get("mode"), b.get("rows")
    why = str(b.get("why", "")).strip()
    if b.get("apply") and not why:
        raise Err(400, "Enter a reason for this import.")
    if mode not in ("products", "add", "set") or not isinstance(rows, list):
        raise Err(400, "Bad import request.")
    if len(rows) > 5000:
        raise Err(400, "Too many rows. Split the file (5000 rows at most).")
    idx = {}
    for p in S["p"]:
        idx.setdefault(key(p["n"]), []).append(p)
    seen, ops, errors, notes = set(), [], [], []
    for i, r in enumerate(rows, start=2):  # row 1 is the heading row
        errs, vals = [], {}
        name = " ".join(str(r.get("name") or "").split())
        k = key(name)
        if not k:
            errs.append("Name is missing.")
        elif k in seen:
            errs.append("This name appears more than once in the file.")
        seen.add(k)
        for f, label in (("price", "Price"), ("reorder", "Reorder"), ("quantity", "Quantity")):
            try:
                vals[f] = num(r.get(f))
            except ValueError:
                vals[f] = None
                errs.append(label + " is not a valid number.")
            if f != "price" and vals[f] is not None and vals[f] != int(vals[f]):
                errs.append(label + " must be a whole number.")
        try:
            vals["cost"] = num(r.get("cost"))
        except ValueError:
            vals["cost"] = None
            errs.append("Cost is not a valid number.")
        found = idx.get(k, []) if k else []
        if len(found) > 1:
            errs.append("Matches more than one existing product.")
        p = found[0] if len(found) == 1 else None
        price, reorder, qty, cost = vals["price"], vals["reorder"], vals["quantity"], vals["cost"]
        if mode == "products":
            if not p and price is None:
                errs.append("Price is required for a new product.")
        else:
            if not p:
                errs.append("Product not found. Add it first with 'Add or update products'.")
            if mode == "add" and (qty is None or qty < 1):
                errs.append("Quantity must be 1 or more.")
            if mode == "set" and qty is None:
                errs.append("Count is missing.")
        if errs:
            errors += [{"row": i, "msg": m} for m in errs]
            continue
        if p and " ".join(p["n"].split()) != name:
            notes.append("'%s' in the file matched '%s'." % (name, p["n"]))
        ops.append((p, name, price, reorder, qty, cost))
    new = upd = same = 0
    changes = []
    for p, name, price, reorder, qty, cost in ops:
        if mode == "products":
            if p is None:
                new += 1
                changes.append({"n": name, "w": "New: price %.2f, stock %d%s" % (price, int(qty or 0), ", cost %.2f" % cost if cost is not None else "")})
                continue
            ch = []
            if price is not None and R(price) != p["p"]:
                ch.append("price %.2f \u2192 %.2f" % (p["p"], R(price)))
            if reorder is not None and int(reorder) != p["m"]:
                ch.append("reorder %d \u2192 %d" % (p["m"], int(reorder)))
            if cost is not None and R(cost) != p.get("c"):
                ch.append("cost %s \u2192 %.2f" % ("%.2f" % p["c"] if p.get("c") is not None else "unknown", R(cost)))
        else:
            z = p["s"] + int(qty) if mode == "add" else int(qty)
            ch = ["stock %d \u2192 %d" % (p["s"], z)] if z != p["s"] else []
        if ch:
            upd += 1
            changes.append({"n": p["n"], "w": ", ".join(ch)})
        else:
            same += 1
    plan = {"mode": mode, "new": new, "updated": upd, "unchanged": same, "errors": errors[:50],
            "errorCount": len(errors), "changes": changes[:200], "more": max(0, len(changes) - 200),
            "notes": notes[:50], "applied": False}
    if errors or not b.get("apply"):
        if errors and b.get("apply"):
            opid = new_operation_id("csv-import")
            by_row = {}
            for issue in errors:
                by_row.setdefault(issue["row"], []).append(issue["msg"])
            record_event("inventory", "CSV import validation failed", entity_type="import", entity_id=opid,
                entity_name="CSV import (%s)" % mode, operation_id=opid,
                details={"mode": mode, "rows": len(rows), "error_count": len(errors),
                         "failed_rows": len(by_row), "errors": [{"row": row, "messages": msgs} for row, msgs in sorted(by_row.items())],
                         "apply_requested": bool(b.get("apply")), "reason": why}, status="failed")
        return {"plan": plan}
    operation_id = new_operation_id("csv-import")
    snapshot("pre-import")
    for p, name, price, reorder, qty, cost in ops:
        if mode == "products":
            if p is None:
                s = int(qty or 0)
                newp = {"id": new_id(), "n": name, "p": R(price), "s": s, "e": "", "m": int(reorder or 0)}
                set_cost(newp, None if cost is None else R(cost))
                S["p"].append(newp)
                queue_event("inventory", "Product created", entity_type="product", entity_id=newp["id"],
                    entity_name=name, operation_id=operation_id,
                    new_value={"id": newp["id"], "n": name, "p": newp["p"], "c": newp.get("c"), "s": s, "m": newp["m"], "e": newp["e"]},
                    details={"reason": why})
                if s:
                    log(name, "New product +%d" % s, 0, s, S["p"][-1]["id"], why, operation_id=operation_id)
            else:
                if price is not None and R(price) != p["p"]:
                    log(p["n"], "Price changed", p["p"], R(price), p["id"], why, operation_id=operation_id)
                    p["p"] = R(price)
                if reorder is not None and int(reorder) != p["m"]:
                    queue_event("inventory", "Reorder level changed", entity_type="product", entity_id=p["id"],
                        entity_name=p["n"], operation_id=operation_id, old_value=p["m"], new_value=int(reorder),
                        details={"field": "m", "reason": why})
                    p["m"] = int(reorder)
                if cost is not None and R(cost) != p.get("c"):
                    log(p["n"], "Cost changed", p.get("c") or 0, R(cost), p["id"], why,
                        operation_id=operation_id, audit_values=(p.get("c"), R(cost)))
                    p["c"] = R(cost)
        else:
            o = p["s"]
            z = o + int(qty) if mode == "add" else int(qty)
            if z != o:
                p["s"] = z
                log(p["n"], "Import: received +%d" % int(qty) if mode == "add" else "Import: count set", o, z, p["id"], why, operation_id=operation_id)
    queue_event("inventory", "CSV import completed", entity_type="import", entity_id=operation_id,
        entity_name="CSV import (%s)" % mode, operation_id=operation_id,
        details={"mode": mode, "rows": len(rows), "added": new, "updated": upd,
                 "unchanged": same, "failed": 0, "reason": why})
    save()
    plan["applied"] = True
    return {"plan": plan}


SETTING_LABELS = {"store": "Store name", "session_hours": "Stay signed in (hours)", "backup_days": "Backup days kept",
                  "rc_addr": "Receipt address", "rc_phone": "Receipt phone", "rc_tag": "Receipt tagline", "rc_foot": "Receipt footer message"}


def shown(v):
    return "(not set)" if v == "" else v if isinstance(v, str) else "%g" % v


def r_settings(b, ip):
    reauth(ip, b, "owner")
    cur = settings()
    store = " ".join(str(b.get("store", "")).split())
    if len(store) > 60:
        raise Err(400, "Store name must be 60 characters or fewer.")
    hrs_in, days_in = b.get("session_hours"), b.get("backup_days")
    if isinstance(hrs_in, bool) or isinstance(days_in, bool):
        raise Err(400, "Enter whole numbers for backup days and a number for the sign-in hours.")
    try:
        hrs, days = float(hrs_in), int(str(days_in).strip())
    except (TypeError, ValueError):
        raise Err(400, "Enter whole numbers for backup days and a number for the sign-in hours.")
    if not math.isfinite(hrs) or not 1 <= hrs <= 72:
        raise Err(400, "Stay signed in must be between 1 and 72 hours.")
    if not 7 <= days <= 365:
        raise Err(400, "Keep between 7 and 365 days of backups.")
    rc = {}
    for k, mx in RC_LIMITS.items():
        if k in b and not isinstance(b[k], str):
            raise Err(400, "%s must be text." % SETTING_LABELS[k])
        rc[k] = " ".join(b[k].split()) if k in b else cur[k]  # a request without the field keeps the saved value
        if len(rc[k]) > mx:
            raise Err(400, "%s must be %d characters or fewer." % (SETTING_LABELS[k], mx))
    new = dict({"store": store, "session_hours": hrs, "backup_days": days}, **rc)
    changed = [k for k in new if new[k] != cur[k]]
    if changed:
        put("settings", new)
        for k in changed:
            log("Settings", "Changed: " + SETTING_LABELS[k], shown(cur[k]), shown(new[k]), 0)
        save()
    return {"msg": "Settings saved." if changed else "No changes."}


def supplier_by_id(i):
    return next((x for x in S.get("suppliers", []) if x.get("id") == i), None)


def r_supplier(b, ip):
    allow("manager")
    name = str(b.get("name", "")).strip()
    if not name or len(name) > 120:
        raise Err(400, "Enter a supplier name (up to 120 characters).")
    existing = next((x for x in S["suppliers"] if x.get("name", "").casefold() == name.casefold()), None)
    if existing:
        if b.get("select_existing"):
            return {"supplier": existing, "msg": "Supplier already exists; selected the existing record."}
        raise Err(409, "A supplier with that name already exists.")
    x = {"id": "sup_" + secrets.token_hex(8), "name": name}
    S["suppliers"].append(x)
    save()
    record_event("inventory", "Supplier created", entity_type="supplier", entity_id=x["id"], entity_name=name)
    return {"supplier": x, "msg": "Supplier added."}


def r_purchase(b, ip):
    allow("manager")
    action = str(b.get("action", "create"))
    if action not in ("create", "edit", "delete"):
        raise Err(400, "Choose a valid purchase action.")
    rows = S.setdefault("purchases", [])
    if action in ("edit", "delete"):
        row = next((x for x in rows if x.get("id") == b.get("id")), None)
        if not row:
            raise Err(404, "Purchase record not found.")
        p = prod(row.get("product_id"))
        if not p:
            raise Err(409, "The linked product no longer exists; purchase history cannot be changed safely.")
        if action == "delete":
            if p["s"] < row["quantity"]:
                raise Err(409, "Cannot delete this purchase safely because some received stock is no longer available. Keep the record for audit history.")
            p["s"] -= row["quantity"]
            log(p["n"], "Purchase reversed -%d" % row["quantity"], p["s"] + row["quantity"], p["s"], p["id"], "Purchase record deleted")
            rows.remove(row)
            save()
            record_event("inventory", "Purchase deleted", entity_type="purchase", entity_id=row["id"], entity_name=p["n"], details={"quantity": row["quantity"]})
            return {"msg": "Purchase deleted."}
        old_q = row["quantity"]
        qty = b.get("quantity")
        cost = b.get("unit_cost")
        supplier = supplier_by_id(b.get("supplier_id"))
        date = b.get("date")
        expiry_date = b.get("expiry_date")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1 or qty > MAX_NUM:
            raise Err(400, "Quantity must be a positive whole number.")
        if not good_num(cost) or cost < 0:
            raise Err(400, "Enter a valid unit cost.")
        if not supplier:
            raise Err(400, "Choose a valid supplier.")
        if not valid_day(date):
            raise Err(400, "Choose a valid purchase date.")
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise Err(400, "Choose a valid purchase date.")
        if not valid_day(expiry_date) or expiry_date <= date:
            raise Err(400, "Expiration date must be after the purchase date.")
        try:
            datetime.strptime(expiry_date, "%Y-%m-%d")
        except ValueError:
            raise Err(400, "Enter a valid expiration date.")
        delta = qty - old_q
        if delta < 0 and p["s"] < -delta:
            raise Err(409, "Cannot reduce the purchase quantity because the received stock has already been used.")
        if p["s"] + delta > MAX_NUM:
            raise Err(400, "That stock quantity is too large.")
        before = p["s"]
        p["s"] += delta
        row.update(supplier_id=supplier["id"], supplier_name=supplier["name"], quantity=qty,
                   unit_cost=R(cost), total=R(qty * cost), date=date, expiry_date=expiry_date, notes=str(b.get("notes", ""))[:1000])
        # Protected cost: never reduce the product cost on cheaper purchases or edits.
        if p.get("c") is None or R(cost) > p["c"]:
            log(p["n"], "Cost changed", p.get("c") or 0, R(cost), p["id"], "Purchase edited",
                audit_values=(p.get("c"), R(cost)))
            p["c"] = R(cost)
        if delta:
            log(p["n"], "Purchase adjusted %+d" % delta, before, p["s"], p["id"], "Purchase record edited")
        save()
        record_event("inventory", "Purchase updated", entity_type="purchase", entity_id=row["id"], entity_name=p["n"])
        return {"msg": "Purchase updated."}

    product = prod(b.get("product_id"))
    supplier = supplier_by_id(b.get("supplier_id"))
    qty, cost, date = b.get("quantity"), b.get("unit_cost"), b.get("date")
    expiry_date = b.get("expiry_date")
    if not product:
        raise Err(400, "Choose a valid product.")
    if not supplier:
        raise Err(400, "Choose a valid supplier.")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1 or qty > MAX_NUM:
        raise Err(400, "Quantity must be a positive whole number.")
    if not good_num(cost) or cost < 0:
        raise Err(400, "Enter a valid unit cost.")
    if not valid_day(date):
        raise Err(400, "Choose a valid purchase date.")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise Err(400, "Choose a valid purchase date.")
    if not valid_day(expiry_date) or expiry_date <= date:
        raise Err(400, "Expiration date must be after the purchase date.")
    try:
        datetime.strptime(expiry_date, "%Y-%m-%d")
    except ValueError:
        raise Err(400, "Enter a valid expiration date.")
    if product["s"] + qty > MAX_NUM:
        raise Err(400, "That stock quantity is too large.")
    before = product["s"]
    # Match the Reorder tab's suggested quantity (2 x reorder level minus current stock).
    suggested = max(1, 2 * product["m"] - before)
    was_on_reorder = before <= product["m"]
    product["s"] += qty
    row = {"id": "pur_" + secrets.token_hex(8), "product_id": product["id"], "product_name": product["n"],
           "supplier_id": supplier["id"], "supplier_name": supplier["name"], "quantity": qty,
           "unit_cost": R(cost), "total": R(qty * cost), "date": date, "expiry_date": expiry_date, "notes": str(b.get("notes", ""))[:1000],
           "created_at": datetime.now().isoformat(timespec="seconds")}
    rows.append(row)
    # Protected cost: keep the current cost if this purchase is cheaper; raise it if costlier.
    if product.get("c") is None or R(cost) > product["c"]:
        log(product["n"], "Cost changed", product.get("c") or 0, R(cost), product["id"], "Purchase received",
            audit_values=(product.get("c"), R(cost)))
        product["c"] = R(cost)
    log(product["n"], "Purchase received +%d" % qty, before, product["s"], product["id"], "Purchase received from " + supplier["name"])
    save()
    record_event("inventory", "Purchase recorded", entity_type="purchase", entity_id=row["id"], entity_name=product["n"],
                 details={"supplier": supplier["name"], "quantity": qty, "unit_cost": R(cost), "total": R(qty * cost), "expiry_date": expiry_date})
    return {"msg": "Purchase added.", "reorder_removed": was_on_reorder and qty >= suggested, "product_id": product["id"]}


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
