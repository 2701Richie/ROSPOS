#!/usr/bin/env python3
"""ROSPOS server. Python standard library only, nothing to install.
Run:  python3 server.py   then open http://<laptop-ip>:8000 on any tablet or PC."""
import getpass, hashlib, hmac, json, math, os, re, secrets, sqlite3, sys, threading, time, traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("POS_DB", os.path.join(HERE, "data", "pos.db"))
BACKUP_DIR = os.environ.get("POS_BACKUP_DIR", os.path.join(HERE, "backups"))
PORT = int(os.environ.get("POS_PORT", "8000"))
LOCK = threading.RLock()


class Err(Exception):
    def __init__(self, code, msg, locked=False):
        self.code, self.msg, self.locked = code, msg, locked


os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("pragma journal_mode=wal")
db.execute("create table if not exists kv(k text primary key, v text not null)")
db.commit()


def get(k, default=None):
    r = db.execute("select v from kv where k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else default


def put(k, v):
    db.execute("insert or replace into kv values(?,?)", (k, json.dumps(v)))
    db.commit()


S = get("state") or {"p": [], "s": [], "g": []}


def save():
    put("state", S)


def R(n):
    return math.floor(n * 100 + 0.5) / 100


def now():
    d = datetime.now()
    return d.strftime("%Y-%m-%d"), d.strftime("%I:%M %p")


SETTING_DEFAULTS = {"store": "", "session_hours": None, "backup_days": 30}


def settings():
    """Owner-editable options (Settings tab). Kept apart from sales data, so a restore never changes them."""
    with LOCK:
        cfg = dict(SETTING_DEFAULTS, **(get("settings") or {}))
    if cfg["session_hours"] is None:
        cfg["session_hours"] = SESSION_HOURS
    return cfg


def pub():
    return {"p": S["p"], "s": S["s"], "g": S["g"], "today": now()[0], "cfg": settings()}


def log(n, k, a, z, pid=None, why=""):
    d, t = now()
    if pid is None:
        match = next((p for p in S["p"] if p["n"] == n), None)
        pid = match["id"] if match else None
    S["g"].append({"d": d, "t": t, "n": n, "k": k, "a": a, "z": z,
                   "u": ACTOR["name"] if ACTOR else "", "i": pid, "w": why})


def prod(i):
    return next((p for p in S["p"] if p["id"] == i), None)


def find_prod(l):
    return prod(l.get("id")) or next((p for p in S["p"] if p["n"] == l["n"]), None)


def nint(v):
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


# ---- accounts, sessions, throttling ------------------------------------------
ROLES = {"staff": 1, "manager": 2, "owner": 3}
SESSION_HOURS = float(os.environ.get("POS_SESSION_HOURS", "12"))
SESSIONS, FAILS = {}, {}
ACTOR = None
U = get("users") or []
SETUP_CODE = secrets.token_hex(3).upper() if not U else None


def save_users():
    put("users", U)


def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", str(pw).encode(), bytes.fromhex(salt), 200_000).hex()


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
    n = FAILS.get(key, (0, 0))[0] + 1
    FAILS[key] = (0, time.time() + 60) if n >= 5 else (n, 0)


def check_pw(u, pw, key):
    throttle(key)
    if u and u.get("active", True) and hmac.compare_digest(hash_pw(pw, u["salt"]), u["hash"]):
        FAILS.pop(key, None)
        return True
    miss(key)
    return False


def find_user(username):
    un = str(username or "").strip().lower()
    return next((u for u in U if u["username"] == un), None)


def user_by_id(i):
    return next((u for u in U if u["id"] == i), None)


def acct(u):
    return {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"],
            "active": u.get("active", True)}


def allow(role):
    if ROLES[ACTOR["role"]] < ROLES[role]:
        raise Err(403, "Your account is not allowed to do this.")


def reauth(ip, b, role="manager"):
    allow(role)
    if not check_pw(ACTOR, str(b.get("password", "")), "re|%s|%s" % (ip, ACTOR["id"])):
        raise Err(403, "Wrong password.")


def new_session(u):
    t = secrets.token_hex(24)
    SESSIONS[t] = {"id": u["id"], "exp": time.time() + settings()["session_hours"] * 3600}
    return t


def session_user(handler):
    t = None
    for part in (handler.headers.get("Cookie") or "").split(";"):
        if part.strip().startswith("pos_session="):
            t = part.strip().split("=", 1)[1]
    s = SESSIONS.get(t)
    u = user_by_id(s["id"]) if s and s["exp"] > time.time() else None
    if not u or not u.get("active", True):
        SESSIONS.pop(t, None)
        return None, t
    return u, t


# ---- operations (each one runs under LOCK and changes nothing if it fails) ---
def r_sale(b, ip):
    agg = {}
    for l in b.get("lines") or []:
        q = l.get("q")
        if not isinstance(q, int) or q < 1 or not prod(l.get("id")):
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
        lines.append({"id": i, "n": p["n"], "q": q, "p": p["p"]})
        tot += q * p["p"]
    tot = R(tot)
    cash = b.get("cash")
    cash = tot if cash is None else cash
    if not isinstance(cash, (int, float)) or cash < tot:
        raise Err(400, "Cash received is less than the total.")
    sale_no = len(S["s"]) + 1
    for l in lines:
        p = prod(l["id"])
        old_stock = p["s"]
        p["s"] -= l["q"]
        log(p["n"], "Sale #%d" % sale_no, old_stock, p["s"], p["id"], "Checkout")
    sale = {"no": sale_no, "d": today, "t": t, "l": lines, "tot": tot, "cash": cash,
            "by": ACTOR["name"], "uid": ACTOR["id"]}
    S["s"].append(sale)
    save()
    return {"sale": sale}


def r_login(b, ip):
    un = str(b.get("username", "")).strip().lower()
    u = find_user(un)
    if not check_pw(u, str(b.get("password", "")), "login|%s|%s" % (ip, un)):
        raise Err(403, "Wrong username or password.")
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
    if i:
        u = user_by_id(i)
        if not u:
            raise Err(404, "Account not found.")
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
    return {"users": [acct(x) for x in U]}


def r_mypw(b, ip):
    if not check_pw(ACTOR, str(b.get("old", "")), "pw|%s|%s" % (ip, ACTOR["id"])):
        raise Err(403, "Wrong current password.")
    set_pw(ACTOR, valid_pw(b.get("new")))
    save_users()
    return {}


def r_product(b, ip):
    allow("manager")
    n, p = str(b.get("n", "")).strip(), b.get("p")
    if not n or not isinstance(p, (int, float)) or p < 0:
        raise Err(400, "Enter a product name and a valid price.")
    e, m, i = str(b.get("e") or ""), nint(b.get("m")), b.get("id")
    if i:
        x = prod(i)
        if not x:
            raise Err(404, "Product not found.")
        if R(p) != x["p"]:
            log(x["n"], "Price changed", x["p"], R(p))
        x.update(n=n, p=R(p), e=e, m=m)
    else:
        s, i = nint(b.get("s")), int(time.time() * 1000)
        while prod(i):
            i += 1
        S["p"].append({"id": i, "n": n, "p": R(p), "s": s, "e": e, "m": m})
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
    log(x["n"], "Deleted", x["s"], 0, x["id"], why)
    S["p"].remove(x)
    save()
    return {}


def r_stock(b, ip):
    allow("manager")
    p, v, mode = prod(b.get("id")), str(b.get("v", "")).strip(), b.get("mode")
    if not p:
        raise Err(404, "Product not found.")
    if not v.isdigit() or (mode == "add" and int(v) < 1):
        raise Err(400, "Type a whole number first" + (" (1 or more)." if mode == "add" else "."))
    o = p["s"]
    z = o + int(v) if mode == "add" else int(v)
    if z == o:
        raise Err(400, "The count did not change.")
    why = str(b.get("why", "")).strip() or ("Stock received" if mode == "add" else "Stock count correction")
    p["s"] = z
    log(p["n"], "Received +%s" % v if mode == "add" else "Count set", o, z, p["id"], why)
    save()
    return {"msg": "%s: %d \u2192 %d" % (p["n"], o, z)}


def find_sale(no):
    s = next((s for s in S["s"] if s["no"] == no), None)
    if not s:
        raise Err(404, "Sale not found.")
    return s


def put_back(l, d, action, reason=""):
    p = find_prod(l)
    if p:
        o = p["s"]
        p["s"] = max(0, o + d)
        log(p["n"], action, o, p["s"], p["id"], reason)


def r_void(b, ip):
    reauth(ip, b)
    s, why = find_sale(b.get("no")), str(b.get("why", "")).strip()
    if s.get("v"):
        raise Err(409, "This sale is already void.")
    if not why:
        raise Err(400, "Enter a reason.")
    for l in s["l"]:
        put_back(l, l["q"], "Void sale #%d" % s["no"], why)
    d, t = now()
    s["v"] = {"d": d, "t": t, "w": why, "u": ACTOR["name"]}
    save()
    return {}


def r_change(b, ip):
    reauth(ip, b)
    s, why, q = find_sale(b.get("no")), str(b.get("why", "")).strip(), b.get("q")
    if s.get("v"):
        raise Err(409, "This sale is void.")
    if not isinstance(q, list) or len(q) != len(s["l"]) or any(not isinstance(x, int) or x < 0 for x in q):
        raise Err(400, "Quantities must be whole numbers.")
    if not any(q):
        raise Err(400, "Use Void to cancel the whole sale.")
    if not why:
        raise Err(400, "Enter a reason.")
    sub = R(sum(n * l["p"] for n, l in zip(q, s["l"])))
    dc = R(sub * 0.2) if s.get("dc") else 0  # sales made with the old discount keep it
    tot, cash = R(sub - dc), b.get("cash")
    if not isinstance(cash, (int, float)) or cash < tot:
        raise Err(400, "Cash received must cover the new total (\u20b1%.2f)." % tot)
    for n, l in zip(q, s["l"]):
        if n > l["q"]:
            p = find_prod(l)
            if not p or n - l["q"] > p["s"]:
                raise Err(409, "Not enough stock for %s." % l["n"])
    old, d, t = s["tot"], *now()
    for n, l in zip(q, s["l"]):
        if n != l["q"]:
            put_back(l, l["q"] - n, "Changed sale #%d" % s["no"], why)
    s["l"] = [dict(l, q=n) for n, l in zip(q, s["l"]) if n > 0]
    s.update(tot=tot, cash=cash)
    if s.get("dc"):
        s.update(sub=sub, dc=dc)
    s.setdefault("h", []).append({"d": d, "t": t, "w": why, "a": old, "z": tot, "u": ACTOR["name"]})
    save()
    return {}


def r_restore(b, ip):
    global S
    reauth(ip, b, "owner")
    d = b.get("data") or b
    if not isinstance(d, dict) or not all(isinstance(d.get(k), list) for k in ("p", "s")):
        raise Err(400, "That is not a valid ROSPOS backup.")
    if not isinstance(d.get("g", []), list) or len(d["p"]) > 100000 or len(d["s"]) > 1000000 or len(d.get("g", [])) > 2000000:
        raise Err(400, "This backup has invalid or excessive data.")
    if any(not isinstance(x, dict) or not all(k in x for k in ("id", "n", "p", "s"))
           or not isinstance(x.get("n"), str) or not isinstance(x.get("p"), (int, float))
           or not isinstance(x.get("s"), int) or x["s"] < 0 for x in d["p"]):
        raise Err(400, "The backup contains an invalid product record.")
    if any(not isinstance(x, dict) or not all(k in x for k in ("no", "d", "l", "tot"))
           or not isinstance(x.get("l"), list) or not isinstance(x.get("tot"), (int, float))
           or any(not isinstance(line, dict) or not all(k in line for k in ("id", "n", "q", "p"))
                  or not isinstance(line.get("q"), int) or line["q"] < 0
                  or not isinstance(line.get("p"), (int, float)) for line in x.get("l", [])) for x in d["s"]):
        raise Err(400, "The backup contains an invalid sale record.")
    if any(not isinstance(x, dict) for x in d.get("g", [])):
        raise Err(400, "The backup contains an invalid activity record.")
    # Keep an immediate database-level recovery point before replacing live data.
    snapshot("pre-restore")
    S = {"p": d["p"], "s": d["s"], "g": d.get("g", [])}
    save()
    return {"msg": "Backup restored successfully."}


def snapshot(tag):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    f = os.path.join(BACKUP_DIR, "%s-%s.db" % (tag, datetime.now().strftime("%Y%m%d-%H%M%S")))
    dst = sqlite3.connect(f)
    db.backup(dst)
    dst.close()
    for old in sorted(x for x in os.listdir(BACKUP_DIR) if x.startswith(tag + "-"))[:-20]:
        os.remove(os.path.join(BACKUP_DIR, old))


def new_id():
    i = int(time.time() * 1000)
    while prod(i):
        i += 1
    return i


def key(n):
    return re.sub(r"[\W_]+", "", n.lower())


def num(v):
    s = str(v or "").replace("\u20b1", "").replace(",", "").strip()
    if not s:
        return None
    x = float(s)
    if x < 0 or x != x or x == float("inf"):
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
        found = idx.get(k, []) if k else []
        if len(found) > 1:
            errs.append("Matches more than one existing product.")
        p = found[0] if len(found) == 1 else None
        price, reorder, qty = vals["price"], vals["reorder"], vals["quantity"]
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
        ops.append((p, name, price, reorder, qty))
    new = upd = same = 0
    changes = []
    for p, name, price, reorder, qty in ops:
        if mode == "products":
            if p is None:
                new += 1
                changes.append({"n": name, "w": "New: price %.2f, stock %d" % (price, int(qty or 0))})
                continue
            ch = []
            if price is not None and R(price) != p["p"]:
                ch.append("price %.2f \u2192 %.2f" % (p["p"], R(price)))
            if reorder is not None and int(reorder) != p["m"]:
                ch.append("reorder %d \u2192 %d" % (p["m"], int(reorder)))
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
        return {"plan": plan}
    snapshot("pre-import")
    for p, name, price, reorder, qty in ops:
        if mode == "products":
            if p is None:
                s = int(qty or 0)
                S["p"].append({"id": new_id(), "n": name, "p": R(price), "s": s, "e": "", "m": int(reorder or 0)})
                if s:
                    log(name, "New product +%d" % s, 0, s, S["p"][-1]["id"], why)
            else:
                if price is not None and R(price) != p["p"]:
                    log(p["n"], "Price changed", p["p"], R(price), p["id"], why)
                    p["p"] = R(price)
                if reorder is not None:
                    p["m"] = int(reorder)
        else:
            o = p["s"]
            z = o + int(qty) if mode == "add" else int(qty)
            if z != o:
                p["s"] = z
                log(p["n"], "Import: received +%d" % int(qty) if mode == "add" else "Import: count set", o, z, p["id"], why)
    save()
    plan["applied"] = True
    return {"plan": plan}


SETTING_LABELS = {"store": "Store name", "session_hours": "Stay signed in (hours)", "backup_days": "Backup days kept"}


def shown(v):
    return "(not set)" if v == "" else v if isinstance(v, str) else "%g" % v


def r_settings(b, ip):
    reauth(ip, b, "owner")
    cur = settings()
    store = " ".join(str(b.get("store", "")).split())
    if len(store) > 60:
        raise Err(400, "Store name must be 60 characters or fewer.")
    try:
        hrs, days = float(b.get("session_hours")), int(str(b.get("backup_days")).strip())
    except (TypeError, ValueError):
        raise Err(400, "Enter whole numbers for backup days and a number for the sign-in hours.")
    if not 1 <= hrs <= 72:
        raise Err(400, "Stay signed in must be between 1 and 72 hours.")
    if not 7 <= days <= 365:
        raise Err(400, "Keep between 7 and 365 days of backups.")
    new = {"store": store, "session_hours": hrs, "backup_days": days}
    changed = [k for k in new if new[k] != cur[k]]
    if changed:
        put("settings", new)
        for k in changed:
            log("Settings", "Changed: " + SETTING_LABELS[k], shown(cur[k]), shown(new[k]), 0)
        save()
    return {"msg": "Settings saved." if changed else "No changes."}


ROUTES = {"/api/settings": r_settings, "/api/sale": r_sale, "/api/product": r_product, "/api/delete": r_delete, "/api/stock": r_stock,
          "/api/void": r_void, "/api/change": r_change, "/api/restore": r_restore, "/api/import": r_import,
          "/api/users": r_users, "/api/user": r_user, "/api/mypassword": r_mypw}
PUBLIC = {"/api/login": r_login, "/api/setup": r_setup}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def cookie(self, token, clear=False):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return "pos_session=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d%s" % (
            "" if clear else token, 0 if clear else int(settings()["session_hours"] * 3600), secure)

    def send(self, code, obj=None, body=None, ctype="application/json", cookie=None, disposition=None):
        data = body if body is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
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
        page = self.path.split("?")[0]
        if page == "/api/backup":
            with LOCK:
                u, _ = session_user(self)
                if not u:
                    return self.send(401, {"error": "Please sign in."})
                if u.get("role") != "owner":
                    return self.send(403, {"error": "Only the owner can download a full backup."})
                payload = {"format": "ROSPOS-backup", "version": 1,
                           "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
                           "data": {"p": S["p"], "s": S["s"], "g": S["g"]}}
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
        if page in ("/api/me", "/api/state"):
            with LOCK:
                u, _ = session_user(self)
                if page == "/api/me":
                    return self.send(200, {"setup": not U, "me": acct(u) if u else None})
                if not u:
                    return self.send(401, {"error": "Please sign in."})
                return self.send(200, {"state": pub(), "me": acct(u)})
        self.send(404, {"error": "Not found."})

    def do_POST(self):
        global ACTOR
        try:
            if self.headers.get("X-Requested-With") != "pos":
                raise Err(403, "Bad request origin.")
            n = int(self.headers.get("Content-Length") or 0)
            if n > 20_000_000:
                raise Err(413, "Request too large.")
            b = json.loads(self.rfile.read(n) or b"{}")
            ip = self.client_address[0]
            with LOCK:
                try:
                    if self.path in PUBLIC:
                        ACTOR = None
                        out = PUBLIC[self.path](b, ip)
                        out["state"] = pub()
                    elif self.path == "/api/logout":
                        SESSIONS.pop(session_user(self)[1], None)
                        out = {"_clear": True}
                    else:
                        fn = ROUTES.get(self.path)
                        if not fn:
                            raise Err(404, "Not found.")
                        ACTOR, _ = session_user(self)
                        if not ACTOR:
                            raise Err(401, "Please sign in again.")
                        out = fn(b, ip)
                        out["state"] = pub()
                finally:
                    ACTOR = None
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
        except Exception:
            traceback.print_exc()
            self.send(500, {"error": "Server error. See the server log."})


def backup_loop():
    """Rewrites today's backup file every hour; keeps the last N days (Settings tab, 30 by default)."""
    while True:
        try:
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
        except Exception:
            traceback.print_exc()
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
    threading.Thread(target=backup_loop, daemon=True).start()
    if not U:
        print("FIRST-TIME SETUP CODE: %s  (open the POS in a browser and create the owner account)" % SETUP_CODE, flush=True)
    print("ROSPOS running on port %d. Open http://<this-laptop-ip>:%d on a tablet or PC." % (PORT, PORT), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
