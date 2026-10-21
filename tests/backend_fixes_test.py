"""Backend hardening tests (expiry, duplicate names, retried sales, purchase cost audit, deleted-product voids,
password-change sessions, restore safety, import log noise). Throw-away database only; never touches live POS data."""
import os, sys, json, shutil, tempfile, time, io
SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="rospos-backendtest-")
os.environ.update(POS_DB=TMP+"/pos.db", POS_BACKUP_DIR=TMP+"/backups", POS_ARCHIVE_DIR=TMP+"/archives", POS_PORT="8994", PYTHONDONTWRITEBYTECODE="1")
sys.dont_write_bytecode = True
sys.path.insert(0, SRC)
import server as srv
bad = 0
def ok(cond, msg):
    global bad
    print(("ok   " if cond else "FAIL ") + msg)
    bad += 0 if cond else 1

def err_code(fn, *a):
    try:
        fn(*a)
        return None
    except srv.Err as e:
        return e.code

def user(role, uid, pw="password123"):
    u = {"id": uid, "name": role.title() + str(uid), "username": role + str(uid), "role": role, "active": True}
    srv.set_pw(u, pw)
    return u

srv.S = {"p": [], "s": [], "g": [], "purchases": [], "suppliers": []}
srv.PENDING_AUDIT_EVENTS.clear()
mgr, owner, staff = user("manager", 2), user("owner", 1), user("staff", 3)
srv.U[:] = [owner, mgr, staff]
srv.ACTOR = mgr

# --- expiry validation
base = {"n": "Alpha", "p": 10, "s": 20, "m": 2, "e": ""}
ok(err_code(srv.r_product, dict(base, e="<img src=x onerror=alert(1)>"), "t") == 400, "B1 HTML in the expiry field is refused")
ok(err_code(srv.r_product, dict(base, e="01/05/2026"), "t") == 400, "B2 wrongly formatted expiry date is refused")
ok(err_code(srv.r_product, dict(base, e="2026-02-31"), "t") == 400, "B3 impossible calendar date is refused")
ok(err_code(srv.r_product, dict(base, e=["2026-01-01"]), "t") == 400, "B4 non-text expiry is refused")
ok(len(srv.S["p"]) == 0, "B5 refused products are not saved")
srv.r_product(dict(base, e="2027-03-01"), "t")
ok(srv.S["p"][0]["e"] == "2027-03-01", "B6 a valid expiry date is stored")
srv.r_product({"n": "Beta", "p": 5, "s": 5, "m": 1, "e": ""}, "t")
ok(srv.S["p"][1]["e"] == "", "B7 blank expiry (none) is still allowed")

# --- duplicate names and length
ok(err_code(srv.r_product, {"n": "  alpha ", "p": 1, "s": 1}, "t") == 409, "B8 a second product with the same name is refused (case and spacing ignored)")
ok(err_code(srv.r_product, {"n": "A-L-P-H-A", "p": 1, "s": 1}, "t") == 409, "B9 punctuation-only differences count as the same name")
a, b = srv.S["p"][0], srv.S["p"][1]
ok(err_code(srv.r_product, {"id": b["id"], "n": "Alpha", "p": 5, "s": 5}, "t") == 409, "B10 renaming a product onto another name is refused")
srv.r_product({"id": a["id"], "n": "Alpha", "p": 11, "e": "2027-03-01", "m": 2}, "t")
ok(a["p"] == 11, "B11 editing a product under its own name still works")
srv.S["p"].append({"id": 999, "n": "Alpha", "p": 3, "s": 1, "e": "", "m": 0})  # an old duplicate that already exists
srv.r_product({"id": 999, "n": "Alpha", "p": 4, "e": "", "m": 0}, "t")
ok(srv.prod(999)["p"] == 4, "B12 an existing duplicate can still be edited without renaming it")
srv.S["p"].remove(srv.prod(999))
ok(err_code(srv.r_product, {"n": "x" * 201, "p": 1, "s": 1}, "t") == 400, "B13 an over-long product name is refused")

# --- retried sale (same request id) records one sale
srv.ACTOR = staff
stock0 = a["s"]
s1 = srv.r_sale({"lines": [{"id": a["id"], "q": 2}], "rid": "retry-token-0001"}, "t")["sale"]
s2 = srv.r_sale({"lines": [{"id": a["id"], "q": 2}], "rid": "retry-token-0001"}, "t")["sale"]
ok(s1["no"] == s2["no"] and a["s"] == stock0 - 2 and len(srv.S["s"]) == 1, "B14 a retried sale request returns the same sale and takes stock once")
s3 = srv.r_sale({"lines": [{"id": a["id"], "q": 1}], "rid": "retry-token-0002"}, "t")["sale"]
ok(s3["no"] != s1["no"] and a["s"] == stock0 - 3, "B15 a new request id makes a new sale")
ok(err_code(srv.r_sale, {"lines": [{"id": a["id"], "q": 1}], "rid": 5}, "t") == 400, "B16 a malformed request id is refused")
srv.r_sale({"lines": [{"id": a["id"], "q": 1}]}, "t")
ok(len(srv.S["s"]) == 3, "B17 sales without a request id still work")

# --- purchase cost changes are audited
srv.ACTOR = mgr
sup = srv.r_supplier({"name": "Acme"}, "t")["supplier"]
b0 = len(srv.db.execute("select id from audit_events where action='Cost changed'").fetchall())
srv.r_purchase({"product_id": b["id"], "supplier_id": sup["id"], "quantity": 3, "unit_cost": 4.5, "date": "2026-10-01", "expiry_date": "2027-10-01"}, "t")
srv.save()
rows = srv.db.execute("select action from audit_events where action='Cost changed'").fetchall()
ok(len(rows) == b0 + 1 and b["c"] == 4.5, "B18 a purchase that sets or raises the cost writes a 'Cost changed' log")

# --- voiding or changing a sale whose product was deleted
srv.r_product({"n": "Gamma", "p": 8, "s": 10, "m": 1, "e": ""}, "t")
c = srv.S["p"][-1]
srv.ACTOR = staff
sale = srv.r_sale({"lines": [{"id": c["id"], "q": 3}]}, "t")["sale"]
srv.ACTOR = mgr
srv.S["p"].remove(c)
out = srv.r_void({"no": sale["no"], "password": "password123", "why": "test"}, "t")
ok("not restored" in out.get("msg", "") and srv.find_sale(sale["no"]).get("v"), "B19 voiding a sale of a deleted product succeeds and says stock was not restored")
srv.save()
ok(srv.db.execute("select count(*) from audit_events where action like 'Stock not restored%' and status='warning'").fetchone()[0] == 1, "B20 the missing restock is written to the log as a warning")
d = {"id": 555, "n": "Delta", "p": 6, "s": 9, "e": "", "m": 0}
srv.S["p"].append(d)
srv.ACTOR = staff
sale2 = srv.r_sale({"lines": [{"id": 555, "q": 4}]}, "t")["sale"]
srv.ACTOR = mgr
srv.S["p"].remove(d)
out = srv.r_change({"no": sale2["no"], "password": "password123", "why": "t", "q": [2], "cash": 100}, "t")
ok("not adjusted" in out.get("msg", ""), "B21 changing a sale of a deleted product reports that stock was not adjusted")

# --- password change signs out the user's other sessions only
srv.SESSIONS.clear()
srv.SESSIONS.update({"keep": {"id": 2, "exp": time.time() + 3600}, "other": {"id": 2, "exp": time.time() + 3600},
                     "someone-else": {"id": 3, "exp": time.time() + 3600}})
srv.ACTOR, srv.TOKEN = mgr, "keep"
srv.r_mypw({"old": "password123", "new": "newpassword456"}, "t")
srv.ACTOR = srv.TOKEN = None
ok("keep" in srv.SESSIONS and "other" not in srv.SESSIONS and "someone-else" in srv.SESSIONS, "B22 changing your password ends your other sessions but not this one or anyone else's")
srv.set_pw(mgr, "password123")

# --- expired sessions are dropped when a new one starts
srv.SESSIONS["stale"] = {"id": 3, "exp": time.time() - 5}
srv.new_session(staff)
ok("stale" not in srv.SESSIONS, "B23 expired sessions are cleaned up")

# --- negative Content-Length is refused instead of hanging
class Hd:
    def __init__(self, d): self.d = d
    def get(self, k, default=None): return self.d.get(k, default)
class Fake(srv.H):
    def __init__(self, path, headers):
        self.path, self.headers, self.client_address, self.rfile, self.response = path, Hd(headers), ("127.0.0.1", 1), io.BytesIO(b""), None
    def send(self, code, obj=None, **kw): self.response = (code, obj); return self.response
h = Fake("/api/sale", {"X-Requested-With": "pos", "Content-Length": "-5"})
h.do_POST()
ok(h.response and h.response[0] == 400, "B24 a negative Content-Length gets 400 (does not hang)")

# --- import preview with errors stays out of the log; applying with errors is logged
srv.ACTOR = mgr
n0 = srv.db.execute("select count(*) from audit_events where action='CSV import validation failed'").fetchone()[0]
srv.r_import({"mode": "products", "apply": False, "rows": [{"name": "Bad", "price": "abc"}]}, "t")
n1 = srv.db.execute("select count(*) from audit_events where action='CSV import validation failed'").fetchone()[0]
srv.r_import({"mode": "products", "apply": True, "why": "x", "rows": [{"name": "Bad", "price": "abc"}]}, "t")
n2 = srv.db.execute("select count(*) from audit_events where action='CSV import validation failed'").fetchone()[0]
ok(n1 == n0 and n2 == n0 + 1, "B25 a preview with errors is not logged; an Apply attempt with errors is")

# --- restore: odd products are normalised, and a failed restore leaves the running data alone
srv.ACTOR = owner
srv.r_restore({"password": "password123", "data": {"p": [{"id": 1, "n": "Old", "p": 2, "s": 5, "e": "garbage"}], "s": []}}, "t")
op = srv.S["p"][0]
ok(op["e"] == "" and op["m"] == 0, "B26 restored products always get a valid expiry and a reorder level")
srv.ACTOR = staff
ok(srv.r_sale({"lines": [{"id": 1, "q": 1}]}, "t")["sale"]["tot"] == 2, "B27 a restored product can be sold")
srv.ACTOR = owner
before = json.dumps(srv.S, sort_keys=True)
real_save = srv.save
def boom():
    raise RuntimeError("disk full")
srv.save = boom
try:
    srv.r_restore({"password": "password123", "data": {"p": [{"id": 9, "n": "New", "p": 1, "s": 1}], "s": []}}, "t")
except RuntimeError:
    pass
srv.save = real_save
ok(json.dumps(srv.S, sort_keys=True) == before, "B28 a restore that fails to save leaves the running data unchanged")

shutil.rmtree(TMP, ignore_errors=True)
print("FAILED %d" % bad if bad else "ALL PASSED")
sys.exit(1 if bad else 0)
