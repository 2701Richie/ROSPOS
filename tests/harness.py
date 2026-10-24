"""Shared helpers for the in-process backend checks (permissions, fuzz, simulation, performance).

A test file starts with:  from harness import *   then  srv, SRC, TMP = boot("name-")
Everything runs against a throw-away database in a temp folder; the real data/ is never opened.
Requests go through the real HTTP handler code (cookies, CSRF header, size limits, error mapping)
but without opening a socket, so thousands of requests take seconds.
"""
import copy, hashlib, io, json, math, os, random, secrets, shutil, sys, tempfile, time

ROLE_RANK = {None: 0, "staff": 1, "manager": 2, "owner": 3}
PW = "password123"


# ---- engine knobs (set by tests/check.py) ------------------------------------------------------
def level():
    return os.environ.get("CHECK_LEVEL", "normal")  # fast | normal | deep


def scale(fast, normal, deep):
    return {"fast": fast, "normal": normal, "deep": deep}.get(level(), normal)


def seed_value():
    return int(os.environ.get("CHECK_SEED", "1"))


class Report:
    """Prints 'ok   ...' / 'FAIL ...' lines (what the engine reads) and METRIC lines."""

    def __init__(self):
        self.bad = 0

    def ok(self, cond, msg):
        print(("ok   " if cond else "FAIL ") + msg, flush=True)
        self.bad += 0 if cond else 1
        return cond

    def metric(self, name, value, unit=""):
        print("METRIC %s %s %s" % (name, value, unit), flush=True)

    def done(self):
        print("FAILED %d" % self.bad if self.bad else "ALL PASSED")
        sys.exit(1 if self.bad else 0)


def boot(prefix, fast_hash=True):
    """Import server.py against a temp database. Returns (srv, source folder, temp folder)."""
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    src = os.path.abspath(args[0]) if args else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp = tempfile.mkdtemp(prefix=prefix)
    os.environ.update(POS_DB=tmp + "/pos.db", POS_BACKUP_DIR=tmp + "/backups", POS_ARCHIVE_DIR=tmp + "/archives",
                      POS_PORT="0", PYTHONDONTWRITEBYTECODE="1")
    sys.dont_write_bytecode = True
    sys.path.insert(0, src)
    import server as srv
    srv.db.execute("pragma synchronous=off")  # speed only: the database is thrown away anyway
    srv.real_hash_pw = srv.hash_pw  # kept so performance checks can time the genuine password hash
    if fast_hash:  # the real PBKDF2 takes ~100 ms per check; logic is what these tests exercise
        srv.hash_pw = lambda pw, salt: hashlib.sha256((salt + str(pw)).encode()).hexdigest()
    srv.traceback.print_exc = lambda *a, **k: None  # expected 500s must not flood the output
    return srv, src, tmp


class Resp:
    def __init__(self, code, data, ctype="application/json", cookie=None):
        self.code, self.data, self.ctype, self.cookie = code, data, ctype, cookie

    @property
    def obj(self):
        try:
            return json.loads(self.data)
        except Exception:
            return None


class _Headers:
    def __init__(self, d):
        self.d = d

    def get(self, k, default=None):
        return self.d.get(k, default)


class Store:
    """A signed-in-or-not client of the POS, talking to the real handler classes."""

    def __init__(self, srv):
        self.srv = srv
        self.tokens, self.problems = {}, []

        class Fake(srv.H):
            def __init__(s, path, headers, body):
                s.path, s.headers, s.client_address = path, _Headers(headers), ("127.0.0.1", 50000)
                s.rfile, s.resp = io.BytesIO(body), None

            def send(s, code, obj=None, body=None, ctype="application/json", cookie=None, disposition=None):
                s.resp = Resp(code, body if body is not None else json.dumps(obj).encode(), ctype, cookie)

        self.Fake = Fake

    def add_user(self, role, pw=PW, name=None):
        srv = self.srv
        uid = max([u["id"] for u in srv.U] + [0]) + 1
        u = {"id": uid, "username": "%s%d" % (role, uid), "name": name or "%s%d" % (role.title(), uid), "role": role, "active": True}
        srv.set_pw(u, pw)
        srv.U.append(u)
        tok = "tok-%s-%d-%s" % (role, uid, secrets.token_hex(4))
        srv.SESSIONS[tok] = {"id": uid, "exp": time.time() + 86400}
        self.tokens[role] = tok
        return u

    def call(self, path, body=None, role=None, raw=None, method=None, csrf=True, token=None, headers=None):
        method = method or ("POST" if (body is not None or raw is not None) else "GET")
        h = dict(headers or {})
        if csrf and method == "POST":
            h.setdefault("X-Requested-With", "pos")
        tok = token or (self.tokens.get(role) if role else None)
        if tok:
            h["Cookie"] = "pos_session=" + tok
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        if method == "POST":
            h.setdefault("Content-Length", str(len(data)))
        f = self.Fake(path, h, data)
        try:
            (f.do_POST if method == "POST" else f.do_GET)()
            r = f.resp or Resp(599, b'{"error":"handler sent no response"}')
        except Exception as e:  # BaseHTTPRequestHandler would drop the connection; treat as a failure
            r = Resp(599, json.dumps({"error": "EXCEPTION %s: %s" % (type(e).__name__, str(e)[:200])}).encode())
        if b'"salt"' in r.data or b'"hash"' in r.data:
            self.problems.append("password data appears in the response of " + path)
        return r


def seed(store):
    """Standard small store: owner, manager, staff, 2 suppliers, 4 products, 1 sale, 1 purchase."""
    srv = store.srv
    for role in ("owner", "manager", "staff"):
        store.add_user(role)
    sup = [store.call("/api/supplier", {"name": n}, "manager").obj["supplier"]["id"] for n in ("Acme Pharma", "Zeta Supply")]
    for n, p, s, m, c, e in (("Alpha 500mg", 10, 50, 5, 4, ""), ("Beta Syrup", 5.5, 30, 3, 2, "2027-06-01"),
                             ("Gamma Cream", 99.99, 8, 2, None, ""), ("Delta Drops", 1.25, 0, 10, None, "")):
        body = {"n": n, "p": p, "s": s, "m": m, "e": e}
        if c is not None:
            body["c"] = c
        r = store.call("/api/product", body, "manager")
        assert r.code == 200, r.data
    ids = [x["id"] for x in srv.S["p"]]
    sale = store.call("/api/sale", {"lines": [{"id": ids[0], "q": 2}], "cash": 100}, "staff").obj["sale"]["no"]
    r = store.call("/api/purchase", {"product_id": ids[1], "supplier_id": sup[0], "quantity": 5, "unit_cost": 2.5,
                                     "date": "2026-10-01", "expiry_date": "2027-10-01"}, "manager")
    assert r.code == 200, r.data
    return {"P": ids, "SALE": sale, "SUP": sup, "PUR": srv.S["purchases"][0]["id"], "PW": PW}


def templates(ids, srv):
    """One valid request body per operation (several for create/edit variants): (endpoint, role, body)."""
    P, SUP, S_ = ids["P"], ids["SUP"], ids["SALE"]
    users = {u["role"]: u for u in srv.U}
    data = {k: copy.deepcopy(srv.S.get(k, [])) for k in ("p", "s", "g", "suppliers", "purchases")}
    return [
        ("/api/sale", "staff", {"lines": [{"id": P[0], "q": 1}], "cash": 100, "rid": "template-rid-0001"}),
        ("/api/product", "manager", {"id": P[0], "n": "Alpha 500mg", "p": 10, "c": 4, "e": "2027-01-01", "m": 5}),
        ("/api/product", "manager", {"n": "New Item", "p": 5, "s": 3, "m": 1, "e": "", "c": 2}),
        ("/api/delete", "manager", {"id": P[2], "why": "check"}),
        ("/api/delete-many", "manager", {"ids": [P[2], P[3]], "why": "check"}),
        ("/api/stock", "manager", {"id": P[0], "mode": "set", "v": "5", "why": "check"}),
        ("/api/stock", "manager", {"id": P[0], "mode": "add", "v": "5"}),
        ("/api/void", "manager", {"no": S_, "password": PW, "why": "check"}),
        ("/api/change", "manager", {"no": S_, "password": PW, "why": "check", "q": [1], "cash": 100}),
        ("/api/restore", "owner", {"password": PW, "data": data}),
        ("/api/import", "manager", {"mode": "products", "apply": True, "why": "check", "rows": [{"name": "Imp", "price": "3", "quantity": "2", "reorder": "1", "cost": "1"}]}),
        ("/api/import", "manager", {"mode": "add", "apply": True, "why": "check", "rows": [{"name": "Alpha 500mg", "quantity": "3"}]}),
        ("/api/users", "owner", {}),
        ("/api/user", "owner", {"id": users["staff"]["id"], "name": "Staff Edit", "role": "staff", "active": True, "password": ""}),
        ("/api/user", "owner", {"username": "newuser", "name": "New User", "role": "staff", "password": PW}),
        ("/api/mypassword", "staff", {"old": PW, "new": "password456"}),
        ("/api/purchase", "manager", {"product_id": P[1], "supplier_id": SUP[0], "quantity": 2, "unit_cost": 3, "date": "2026-10-01", "expiry_date": "2027-10-01"}),
        ("/api/purchase", "manager", {"action": "edit", "id": ids["PUR"], "product_id": P[1], "supplier_id": SUP[0], "quantity": 5, "unit_cost": 3, "date": "2026-10-01", "expiry_date": "2027-10-01"}),
        ("/api/purchase", "manager", {"action": "delete", "id": ids["PUR"]}),
        ("/api/supplier", "manager", {"name": "Brand New Supplier"}),
        ("/api/settings", "owner", {"store": "3B", "session_hours": 12, "backup_days": 30, "rc_addr": "", "rc_phone": "", "rc_tag": "", "rc_foot": "", "password": PW}),
        ("/api/login", None, {"username": users["owner"]["username"], "password": PW}),
        ("/api/setup", None, {"code": "ZZZZZZ", "username": "setupuser", "name": "Setup", "password": PW}),
        ("/api/logout", "staff", {}),
    ]


# ---- state snapshots (so each request starts from the same store) -----------------------------
def snap(srv):
    """Fingerprint of everything a failed request must not change."""
    return json.dumps({"S": srv.S, "U": srv.U, "cfg": srv.get("settings"), "pending": len(srv.PENDING_AUDIT_EVENTS)},
                      sort_keys=True, default=str)


def save_state(srv):
    return (json.dumps(srv.S), json.dumps(srv.U), srv.get("settings"), dict(srv.SESSIONS), srv.get("sale_seq") or 0)


def load_state(srv, st):
    srv.S = json.loads(st[0])
    srv.U[:] = json.loads(st[1])
    if st[2] is None:
        srv.db.execute("delete from kv where k='settings'")
        srv.db.commit()
    else:
        srv.put("settings", st[2])
    srv.SESSIONS.clear()
    srv.SESSIONS.update(st[3])
    srv.PENDING_AUDIT_EVENTS.clear()
    srv._ID_FLOOR = None  # the replaced products may use other ids
    srv.FAILS.clear()
    if hasattr(srv, "RECENT_SALES"):  # older versions kept retry keys in memory
        srv.RECENT_SALES.clear()
    try:  # current versions keep them in a table so a retry survives a restart
        srv.db.execute("delete from sale_requests")
        srv.db.commit()
    except Exception:
        pass
    if hasattr(srv, "PENDING_SALE_REQUEST"):
        srv.PENDING_SALE_REQUEST = None
    srv.put("sale_seq", st[4])


def audit_count(srv):
    return srv.db.execute("select count(*) from audit_events").fetchone()[0] + len(srv.PENDING_AUDIT_EVENTS)


# ---- rules every state of the store must satisfy ----------------------------------------------
def invariants(srv):
    """Returns a list of violated rules (empty = healthy)."""
    bad, S, good = [], srv.S, srv.good_num
    ids = set()
    for p in S.get("p", []):
        pid = p.get("id") if isinstance(p, dict) else None
        if not isinstance(p, dict) or not isinstance(pid, int) or isinstance(pid, bool) or pid in ids:
            bad.append("product has a bad or repeated id: %r" % (pid,))
            continue
        ids.add(pid)
        if not isinstance(p.get("n"), str) or not p["n"].strip():
            bad.append("product %s has no name" % pid)
        if not good(p.get("p")):
            bad.append("product %s price invalid: %r" % (pid, p.get("p")))
        if p.get("c") is not None and not good(p["c"]):
            bad.append("product %s cost invalid: %r" % (pid, p["c"]))
        for f in ("s", "m"):
            if not good(p.get(f), srv.MAX_NUM, whole=True):
                bad.append("product %s %s invalid: %r" % (pid, f, p.get(f)))
        if not (isinstance(p.get("e"), str) and srv.valid_expiry(p["e"])):
            bad.append("product %s expiry invalid: %r" % (pid, p.get("e")))
    nos = set()
    for s in S.get("s", []):
        no = s.get("no")
        if not isinstance(no, int) or isinstance(no, bool) or no < 1 or no in nos:
            bad.append("sale has a bad or repeated number: %r" % (no,))
            continue
        nos.add(no)
        lines = s.get("l")
        if not isinstance(lines, list) or not lines:
            bad.append("sale #%s has no lines" % no)
            continue
        for l in lines:
            if not good(l.get("q"), srv.MAX_NUM, whole=True) or l["q"] < 1 or not good(l.get("p")):
                bad.append("sale #%s has an invalid line %r" % (no, l))
        if not s.get("v") and not s.get("dc"):
            want = srv.R(sum(l["q"] * l["p"] for l in lines if isinstance(l.get("q"), int) and good(l.get("p"))))
            if abs(want - s.get("tot", -1)) > 0.005:
                bad.append("sale #%s total %r does not match its lines (%r)" % (no, s.get("tot"), want))
            if not good(s.get("cash")) or s["cash"] < s["tot"] - 0.005:
                bad.append("sale #%s cash %r is below the total %r" % (no, s.get("cash"), s.get("tot")))
    if (srv.get("sale_seq") or 0) < srv.max_sale_no(S.get("s", [])):
        bad.append("sale_seq is behind the highest sale number (numbers could repeat)")
    sup = {x.get("id") for x in S.get("suppliers", [])}
    if len(sup) != len(S.get("suppliers", [])):
        bad.append("repeated supplier id")
    seen = set()
    for x in S.get("purchases", []):
        if x.get("id") in seen or not isinstance(x.get("quantity"), int) or x["quantity"] < 1:
            bad.append("bad purchase record %r" % (x.get("id"),))
        seen.add(x.get("id"))
        if abs(srv.R(x.get("quantity", 0) * x.get("unit_cost", 0)) - x.get("total", -1)) > 0.005:
            bad.append("purchase %s total does not match quantity x unit cost" % x.get("id"))
    names = [u.get("username") for u in srv.U]
    if len(set(names)) != len(names):
        bad.append("repeated username")
    if srv.U and not any(u.get("role") == "owner" and u.get("active", True) for u in srv.U):
        bad.append("no active owner account")
    if any(u.get("role") not in srv.ROLES for u in srv.U):
        bad.append("account with an unknown role")
    cfg = srv.settings()
    if not 1 <= cfg["session_hours"] <= 72 or not 7 <= cfg["backup_days"] <= 365 or len(cfg["store"]) > 60:
        bad.append("settings out of range: %r" % cfg)
    for k, mx in srv.RC_LIMITS.items():
        if len(str(cfg.get(k, ""))) > mx:
            bad.append("receipt setting %s too long" % k)
    return bad


def cost_leaks(state):
    """Anything in an API state payload that staff must never see."""
    out = []
    if any("c" in p for p in state.get("p", [])):
        out.append("product cost")
    if any("c" in l for s in state.get("s", []) for l in s.get("l", [])):
        out.append("sale line cost")
    if "purchases" in state or "suppliers" in state:
        out.append("purchases/suppliers")
    if any("cost" in str(g.get("k", "")).lower() for g in state.get("g", [])):
        out.append("cost-change log row")
    return out
