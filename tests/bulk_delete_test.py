"""Bulk delete tests (r_delete_many): all-or-nothing, audit rows, permissions, input checks.

In-process against a throw-away database in a temp dir. Never starts the HTTP server or touches real data.
Usage: python3 tests/bulk_delete_test.py [source-folder]     Output: 'ok   ...' / 'FAIL ...' lines
"""
import os, sys, json, glob, shutil, tempfile

SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="rospos-bulktest-")
os.environ.update(POS_DB=TMP + "/pos.db", POS_BACKUP_DIR=TMP + "/backups", POS_ARCHIVE_DIR=TMP + "/archives",
                  POS_PORT="8995", PYTHONDONTWRITEBYTECODE="1")
sys.dont_write_bytecode = True
sys.path.insert(0, SRC)
import server as srv

if not hasattr(srv, "r_delete_many"):
    print("SKIP this source has no bulk delete")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0)

bad = 0


def ok(c, m):
    global bad
    print(("ok   " if c else "FAIL ") + m)
    bad += 0 if c else 1


def actor(role):
    return {"id": 1, "name": "T", "username": "t", "role": role, "active": True, "salt": "ab", "hash": "x"}


def fresh(role="manager"):
    today = srv.now()[0]
    srv.S = {"p": [{"id": i, "n": "P%d" % i, "p": 1.0, "s": i, "e": "", "m": 0} for i in range(1, 6)],
             "s": [{"no": 1, "d": today, "t": "09:00 AM", "by": "T", "uid": 1, "tot": 1.0, "cash": 1.0,
                    "l": [{"id": 1, "n": "P1", "q": 1, "p": 1.0}]}], "g": []}
    srv.ACTOR = actor(role)


def snap():
    return json.dumps(srv.S, sort_keys=True)


def call(ids, why="expired batch", **kw):
    return srv.r_delete_many(dict({"ids": ids, "why": why}, **kw), "t")


def rejects(ids, why="expired batch", code=None):
    before = snap()
    try:
        call(ids, why)
        return False
    except srv.Err as e:
        return (code is None or e.code == code) and snap() == before


ids = lambda: [p["id"] for p in srv.S["p"]]

fresh()
r = call([1, 2, 3])
ok(ids() == [4, 5] and r.get("msg") == "Deleted 3 products.", "B1 deletes the selected products and reports how many")
g = [x for x in srv.S["g"] if x.get("k") == "Deleted"]
ok(len(g) == 3 and all(x.get("w") == "expired batch" for x in g), "B1 one audit row per product, each with the reason")
ok(len(srv.S["s"]) == 1 and srv.S["s"][0]["l"][0]["n"] == "P1", "B1 old sales keep their items after the product is deleted")
ok(len(glob.glob(TMP + "/backups/pre-bulk-delete-*.db")) == 1, "B1 safety snapshot taken before deleting")
# Regression: verify deletion survives a database-backed state reload.
saved = srv.get("state")
ok([p["id"] for p in saved["p"]] == [4, 5], "B1 deleted products stay deleted after reloading persisted state")

fresh()
call([1, 1, 2, 2])
ok(ids() == [3, 4, 5] and len([x for x in srv.S["g"] if x.get("k") == "Deleted"]) == 2, "B2 duplicate ids are deleted once")

fresh()
ok(rejects([1, 99], code=404) and not srv.S["g"], "B3 one unknown id: refused, nothing deleted, no audit rows")
fresh()
ok(rejects([1], "", code=400) and rejects([1], "   ", code=400), "B4 blank reason refused")
fresh()
ok(all(rejects(v, code=400) for v in ("1,2", None, 5, {"a": 1}, [], list(range(1, 1002)))), "B5 not a list, empty list or over 1000 ids refused")
ok(all(rejects(v, code=400) for v in ([True], ["1"], [1.5], [None], [[1]], [1, "x"])), "B6 booleans, text, decimals and nulls refused")
ok(rejects([-1]) and rejects([0]), "B6 negative and zero ids refused")

fresh("staff")
ok(rejects([1], code=403), "B7 staff cannot bulk delete")
fresh("manager")
call([5])
ok(ids() == [1, 2, 3, 4], "B7 manager can bulk delete")
fresh("owner")
r = call([1])
ok(ids() == [2, 3, 4, 5] and r.get("msg") == "Deleted 1 product.", "B7 owner can; message uses singular for one")

fresh()
call([1, 2, 3, 4, 5])
ok(ids() == [], "B8 every product can be deleted at once")
ok(call.__name__ == "call" and "/api/delete-many" in srv.ROUTES and srv.ROUTES["/api/delete-many"] is srv.r_delete_many, "B9 route /api/delete-many is registered")

shutil.rmtree(TMP, ignore_errors=True)
print("FAILED %d" % bad if bad else "ALL PASSED")
sys.exit(1 if bad else 0)
