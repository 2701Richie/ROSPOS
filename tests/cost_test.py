"""Cost tests: optional product cost, cost recorded on sale lines, hidden from staff, restore and CSV import checks.

In-process against a throw-away database in a temp dir. Never starts the HTTP server or touches real data.
Usage: python3 tests/cost_test.py [source-folder]     Output: 'ok   ...' / 'FAIL ...' lines
"""
import os, sys, json, shutil, tempfile

SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="rospos-costtest-")
os.environ.update(POS_DB=TMP + "/pos.db", POS_BACKUP_DIR=TMP + "/backups", POS_ARCHIVE_DIR=TMP + "/archives",
                  POS_PORT="8994", PYTHONDONTWRITEBYTECODE="1")
sys.dont_write_bytecode = True
sys.path.insert(0, SRC)
import server as srv

if not hasattr(srv, "cost_of"):
    print("SKIP this source has no cost feature")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0)

PW, SALT = "pw12345678", "ab" * 8
bad = 0


def ok(c, m):
    global bad
    print(("ok   " if c else "FAIL ") + m)
    bad += 0 if c else 1


def actor(role):
    return {"id": 1, "name": "T", "username": "t", "role": role, "active": True, "salt": SALT, "hash": srv.hash_pw(PW, SALT)}


def fresh(role="owner"):
    srv.S = {"p": [], "s": [], "g": []}
    srv.ACTOR = actor(role)


def snap():
    return json.dumps(srv.S, sort_keys=True)


def prod(name):
    return next((p for p in srv.S["p"] if p["n"] == name), None)


def add(name="A", price=10, stock=5, **kw):
    srv.r_product(dict({"n": name, "p": price, "s": stock}, **kw), "t")
    return prod(name)


def refused(fn, code=400):
    before = snap()
    try:
        fn()
        return False
    except srv.Err as e:
        return e.code == code and snap() == before


costlogs = lambda: [g for g in srv.S["g"] if g.get("k") == "Cost changed"]

# C1 new products
fresh()
ok(add("A", c=6.5).get("c") == 6.5, "C1 new product keeps its cost")
ok("c" not in add("B", c="") and "c" not in add("C", c=None) and "c" not in add("D"), "C1 blank, null or missing cost means unknown (no cost stored)")
ok(add("E", c=0).get("c") == 0, "C1 a cost of 0 is allowed and kept")
ok(add("F", c=1.239).get("c") == 1.24, "C1 cost is rounded to centavos")

# C2 invalid costs are refused before anything changes
fresh()
a = add("A", c=5)
for label, v in (("text", "abc"), ("number as text", "5"), ("negative", -1), ("true", True), ("too large", 10 ** 12), ("list", [1]), ("object", {})):
    ok(refused(lambda v=v: srv.r_product({"id": a["id"], "n": "A", "p": 10, "c": v}, "t")), "C2 edit with %s cost refused, nothing changed" % label)
ok(refused(lambda: srv.r_product({"n": "Z", "p": 10, "s": 1, "c": "abc"}, "t")), "C2 new product with a bad cost refused")

# C3 editing
fresh()
a = add("A", c=6.5)
srv.r_product({"id": a["id"], "n": "A", "p": 12, "e": "", "m": 0}, "t")
ok(a.get("c") == 6.5 and not costlogs(), "C3 edit from a client that sends no cost keeps the cost")
srv.r_product({"id": a["id"], "n": "A", "p": 12, "c": 8}, "t")
ok(a.get("c") == 8 and len(costlogs()) == 1 and costlogs()[0]["a"] == 6.5 and costlogs()[0]["z"] == 8, "C3 changing the cost logs 'Cost changed' with old and new value")
srv.r_product({"id": a["id"], "n": "A", "p": 12, "c": 8}, "t")
ok(len(costlogs()) == 1, "C3 saving the same cost logs nothing")
srv.r_product({"id": a["id"], "n": "A", "p": 12, "c": ""}, "t")
ok("c" not in a and len(costlogs()) == 2, "C3 blank cost clears it and is logged")

# C4 cost recorded on sales
fresh()
a, b = add("A", c=6.5), add("B")
sa = srv.r_sale({"lines": [{"id": a["id"], "q": 2}, {"id": b["id"], "q": 1}]}, "t")["sale"]
ok(sa["l"][0].get("c") == 6.5 and "c" not in sa["l"][1], "C4 sale line records the cost at sale time; unknown cost stays unknown")
srv.r_product({"id": a["id"], "n": "A", "p": 10, "c": 9}, "t")
sb = srv.r_sale({"lines": [{"id": a["id"], "q": 1}]}, "t")["sale"]
ok(srv.S["s"][0]["l"][0]["c"] == 6.5 and sb["l"][0]["c"] == 9, "C4 later cost changes never alter old sales")
srv.r_change({"no": sb["no"], "q": [3], "cash": 100, "why": "t", "password": PW}, "t")
ok(srv.S["s"][1]["l"][0]["c"] == 9 and srv.S["s"][1]["l"][0]["q"] == 3, "C4 changing a sale keeps the recorded cost")

# C5 staff never receive costs; managers and owners do
for role, expect in (("staff", False), ("manager", True), ("owner", True)):
    fresh(role)
    srv.ACTOR = actor("owner")
    a = add("A", c=6.5)
    srv.ACTOR = actor(role)
    sale = srv.r_sale({"lines": [{"id": a["id"], "q": 1}]}, "t")["sale"]
    has = lambda o: '"c":' in json.dumps(o, separators=(",", ":"))
    st = srv.pub()
    ok(has(st["p"]) == expect and has(st["s"]) == expect, "C5 %s: state %s costs on products and sale lines" % (role, "includes" if expect else "has no"))
    ok(has(sale) == expect, "C5 %s: sale reply %s costs" % (role, "includes" if expect else "has no"))
    ok(srv.S["p"][0].get("c") == 6.5 and srv.S["s"][0]["l"][0].get("c") == 6.5, "C5 %s: stored data keeps the costs untouched" % role)

# C6 restore validation
fresh()
today = srv.now()[0]


def backup(pc=None, lc=None, drop=False):
    p = {"id": 1, "n": "A", "p": 5, "s": 3, "e": "", "m": 0}
    line = {"id": 1, "n": "A", "q": 1, "p": 5}
    if not drop:
        p["c"], line["c"] = pc, lc
    return {"p": [p], "s": [{"no": 1, "d": today, "t": "09:00 AM", "by": "T", "uid": 1, "tot": 5, "cash": 5, "l": [line]}], "g": []}


def restore(d):
    return lambda: srv.r_restore({"password": PW, "data": d}, "t")


srv.ACTOR = actor("owner")
ok(restore(backup(drop=True))() is not None, "C6 restore of an old backup without costs works")
ok(restore(backup(6.5, 6.5))() is not None and srv.S["p"][0]["c"] == 6.5, "C6 restore keeps valid costs")
ok(restore(backup(None, None))() is not None, "C6 restore accepts null costs")
for label, v in (("text", "x"), ("negative", -1), ("true", True), ("huge", 10 ** 12)):
    ok(refused(restore(backup(pc=v))), "C6 restore refuses a %s product cost" % label)
    ok(refused(restore(backup(lc=v))), "C6 restore refuses a %s sale line cost" % label)

# C7 CSV import
fresh("manager")


def imp(mode, rows, apply=True):
    return srv.r_import({"mode": mode, "rows": rows, "apply": apply, "why": "t"}, "t")["plan"]


imp("products", [{"name": "N1", "price": "10", "quantity": "5", "cost": "6.5"}])
ok(prod("N1") and prod("N1").get("c") == 6.5, "C7 import creates a product with its cost")
plan = imp("products", [{"name": "N1", "price": "10", "cost": "7"}], apply=False)
ok(prod("N1")["c"] == 6.5 and any("cost 6.50" in c["w"] for c in plan["changes"]), "C7 preview shows the cost change and saves nothing")
imp("products", [{"name": "N1", "price": "10", "cost": "7"}])
ok(prod("N1")["c"] == 7 and len(costlogs()) == 1, "C7 import updates the cost and logs it")
imp("products", [{"name": "N1", "price": "10", "cost": ""}])
ok(prod("N1")["c"] == 7, "C7 blank cost cell leaves the cost unchanged")
imp("products", [{"name": "N1", "price": "11"}])
ok(prod("N1")["c"] == 7 and prod("N1")["p"] == 11, "C7 file with no cost column still imports and keeps the cost")
for v in ("abc", "-1"):
    before = snap()
    plan = imp("products", [{"name": "N1", "price": "10", "cost": v}])
    ok(plan["errorCount"] >= 1 and snap() == before and not plan["applied"], "C7 invalid cost '%s' is reported and nothing is saved" % v)
imp("add", [{"name": "N1", "quantity": "2", "cost": "99"}])
ok(prod("N1")["c"] == 7 and prod("N1")["s"] == 7, "C7 'add stock' mode ignores the cost column")

shutil.rmtree(TMP, ignore_errors=True)
print("FAILED %d" % bad if bad else "ALL PASSED")
sys.exit(1 if bad else 0)
