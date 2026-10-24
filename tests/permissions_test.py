# check: tags=security
"""Who may do what: every endpoint x every role, sessions, CSRF, static-file safety, setup and login rules."""
import json
from harness import *

srv, SRC, TMP = boot("rospos-perm-")
R = Report()
store = Store(srv)

# ---- first-run setup (runs while there are no accounts) ----
code = srv.SETUP_CODE
r = store.call("/api/setup", {"code": "WRONG1", "username": "boss", "name": "Boss", "password": PW})
R.ok(r.code == 403, "setup: a wrong setup code is refused")
r = store.call("/api/setup", {"code": code, "username": "x", "name": "Boss", "password": PW})
R.ok(r.code == 400 and not srv.U, "setup: an invalid username is refused and creates nothing")
r = store.call("/api/setup", {"code": code, "username": "boss", "name": "Boss", "password": PW})
R.ok(r.code == 200 and r.cookie and "HttpOnly" in r.cookie and "SameSite=Strict" in r.cookie, "setup: the right code creates the owner and a hardened session cookie")
r = store.call("/api/setup", {"code": code, "username": "boss2", "name": "Boss", "password": PW})
R.ok(r.code == 403 and len(srv.U) == 1, "setup: it cannot be used again once an account exists")
srv.U.clear()
srv.SESSIONS.clear()

ids = seed(store)
MIN = {"/api/sale": "staff", "/api/mypassword": "staff", "/api/product": "manager", "/api/delete": "manager",
       "/api/delete-many": "manager", "/api/stock": "manager", "/api/void": "manager", "/api/change": "manager",
       "/api/import": "manager", "/api/purchase": "manager", "/api/supplier": "manager", "/api/users": "owner",
       "/api/user": "owner", "/api/restore": "owner", "/api/settings": "owner"}
R.ok(set(MIN) == set(srv.ROUTES), "every endpoint is listed in the permission table (new endpoint? add it to MIN in tests/permissions_test.py)"
     + ("" if set(MIN) == set(srv.ROUTES) else " missing=%s extra=%s" % (sorted(set(srv.ROUTES) - set(MIN)), sorted(set(MIN) - set(srv.ROUTES)))))

base = save_state(srv)
tpl = [t for t in templates(ids, srv) if t[0] in MIN]
problems = {}
for ep, _, body in tpl:
    for role in (None, "staff", "manager", "owner"):
        load_state(srv, base)
        before = snap(srv)
        resp = store.call(ep, body, role)
        allowed = ROLE_RANK[role] >= ROLE_RANK[MIN[ep]]
        if allowed and resp.code in (401, 403):
            problems.setdefault(ep, []).append("%s should be allowed but got %s %s" % (role or "signed-out", resp.code, resp.data[:80]))
        if not allowed:
            want = 401 if role is None else 403
            if resp.code != want:
                problems.setdefault(ep, []).append("%s should get %s but got %s" % (role or "signed-out", want, resp.code))
            if snap(srv) != before:
                problems.setdefault(ep, []).append("%s was refused but the data still changed" % (role or "signed-out"))
for ep in MIN:
    R.ok(ep not in problems, "permissions %s (needs %s): all 4 roles behave" % (ep, MIN[ep]) + ("" if ep not in problems else " -> " + "; ".join(problems[ep][:3])))
load_state(srv, base)

# ---- GET endpoints ----
for path, need in (("/api/state", "staff"), ("/api/logs?category=activity", "manager"), ("/api/backup", "owner")):
    got = {role: store.call(path, role=role).code for role in (None, "staff", "manager", "owner")}
    want = {role: (200 if ROLE_RANK[role] >= ROLE_RANK[need] else (401 if role is None else 403)) for role in got}
    R.ok(got == want, "GET %s needs %s: %s" % (path, need, got))
R.ok(store.call("/api/me").code == 200, "GET /api/me answers when signed out (the page needs it to decide what to show)")

# ---- sessions ----
tok = store.tokens["staff"]
uid = srv.SESSIONS[tok]["id"]
srv.user_by_id(uid)["active"] = False
R.ok(store.call("/api/state", role="staff").code == 401, "a disabled account is signed out immediately")
load_state(srv, base)
srv.SESSIONS[tok]["exp"] = time.time() - 1
R.ok(store.call("/api/state", role="staff").code == 401, "an expired session is refused")
load_state(srv, base)
store.call("/api/logout", {}, "manager")
R.ok(store.call("/api/state", role="manager").code == 401, "logging out ends the session")
load_state(srv, base)
mgr = next(u for u in srv.U if u["role"] == "manager")
store.call("/api/user", {"id": mgr["id"], "name": mgr["name"], "role": "staff", "active": True, "password": ""}, "owner")
R.ok(store.call("/api/product", {"n": "Z", "p": 1, "s": 1}, "manager").code == 403, "demoting an account takes effect on its very next request")
load_state(srv, base)
owner = next(u for u in srv.U if u["role"] == "owner")
R.ok(store.call("/api/user", {"id": owner["id"], "name": owner["name"], "role": "staff", "active": True, "password": ""}, "owner").code in (400, 409),
     "the last owner cannot be demoted")
R.ok(store.call("/api/user", {"id": owner["id"], "name": owner["name"], "role": "owner", "active": False, "password": ""}, "owner").code in (400, 409),
     "the last owner cannot be disabled")
load_state(srv, base)

# ---- request-level protections ----
no_csrf = [ep for ep in MIN if store.call(ep, {}, "owner", csrf=False).code != 403]
R.ok(not no_csrf, "every POST endpoint refuses requests without the X-Requested-With header (CSRF)" + ("" if not no_csrf else " -> " + ", ".join(no_csrf)))
R.ok(store.call("/api/sale", {}, "staff", headers={"Content-Length": "30000000"}).code == 413, "an oversized request body is refused with 413")
R.ok(store.call("/api/sale", {}, "staff", headers={"Content-Length": "-1"}).code == 400, "a negative Content-Length is refused")
R.ok(store.call("/api/sale", {}, "staff", headers={"Content-Length": "abc"}).code == 400, "a non-numeric Content-Length is refused")
R.ok(store.call("/api/nothing", {}, "owner").code == 404, "an unknown endpoint is a clean 404")

# ---- static files: only the app itself is served ----
for path in ("/", "/index.html", "/style.css", "/logo.svg", "/js/core.js"):
    R.ok(store.call(path).code == 200, "static: %s is served" % path)
secret = [p for p in ("/server.py", "/data/pos.db", "/js/../server.py", "/js/%2e%2e/server.py", "/../server.py", "/.git/config", "/tests/run.py",
                      "/NOTES.md", "/install-lubuntu.sh", "/js/", "/js/x.js", "//etc/passwd", "/backups/", "/archives/") if store.call(p).code == 200]
R.ok(not secret, "static: source, data, git and backup files are NOT served" + ("" if not secret else " -> LEAKS: " + ", ".join(secret)))

# ---- login rules ----
load_state(srv, base)
owner_name = owner["username"]
r = store.call("/api/login", {"username": owner_name, "password": PW})
R.ok(r.code == 200 and r.cookie and "HttpOnly" in r.cookie and "SameSite=Strict" in r.cookie, "login: success sets an HttpOnly, SameSite=Strict cookie")
R.ok(store.call("/api/login", {"username": "nobody", "password": "x"}).obj["error"] == store.call("/api/login", {"username": owner_name, "password": "x"}).obj["error"],
     "login: wrong username and wrong password give the same message")
srv.FAILS.clear()
codes = [store.call("/api/login", {"username": owner_name, "password": "bad%d" % i}).code for i in range(7)]
R.ok(429 in codes, "login: repeated wrong passwords get locked out (codes %s)" % codes)
R.ok(store.call("/api/login", {"username": owner_name, "password": PW}).code == 429, "login: even the right password is refused during the lockout")
srv.FAILS.clear()
live = srv.user_by_id(mgr["id"])  # load_state() replaced the account objects, so look it up again
live["active"] = False
R.ok(store.call("/api/login", {"username": live["username"], "password": PW}).code in (400, 401, 403), "login: a disabled account cannot sign in")
live["active"] = True
R.ok(store.call("/api/login", {"username": live["username"], "password": PW}).code == 200, "login: the same account works again once re-enabled")

# ---- secrets never leave the server ----
R.ok(not store.problems, "no response ever contained a password hash or salt" + ("" if not store.problems else " -> " + store.problems[0]))
shutil.rmtree(TMP, ignore_errors=True)
R.done()
