"""Receipt settings tests: address, phone, tagline and footer saved by the owner, validated, visible to every role.

In-process against a throw-away database in a temp dir. Never starts the HTTP server or touches real data.
Usage: python3 tests/receipt_settings_test.py [source-folder]     Output: 'ok   ...' / 'FAIL ...' lines
"""
import os, sys, json, shutil, tempfile

SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="rospos-rcsettings-")
os.environ.update(POS_DB=TMP + "/pos.db", POS_BACKUP_DIR=TMP + "/backups", POS_ARCHIVE_DIR=TMP + "/archives",
                  POS_PORT="8993", PYTHONDONTWRITEBYTECODE="1")
sys.dont_write_bytecode = True
sys.path.insert(0, SRC)
import server as srv

if not hasattr(srv, "RC_LIMITS"):
    print("SKIP this source has no receipt settings")
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


srv.S = {"p": [], "s": [], "g": []}
srv.ACTOR = actor("owner")
BASE = {"store": "3B Pharmacy", "session_hours": 12, "backup_days": 30, "password": PW}


def save(**kw):
    return srv.r_settings(dict(BASE, **kw), "t")


def refused(fn, code=400):
    before = json.dumps(srv.settings(), sort_keys=True)
    try:
        fn()
        return False
    except srv.Err as e:
        return e.code == code and json.dumps(srv.settings(), sort_keys=True) == before


ok(all(srv.settings()[k] == "" for k in srv.RC_LIMITS), "S1 receipt fields start empty")
save(rc_addr="12 Main St, Davao", rc_phone="0912 345 6789", rc_tag="Your health partner", rc_foot="Thank you!")
c = srv.settings()
ok((c["rc_addr"], c["rc_phone"], c["rc_tag"], c["rc_foot"]) == ("12 Main St, Davao", "0912 345 6789", "Your health partner", "Thank you!"), "S1 owner can save all four receipt fields")
names = [g["k"] for g in srv.S["g"]]
ok(all("Changed: " + srv.SETTING_LABELS[k] in names for k in srv.RC_LIMITS), "S1 every change is written to the activity log")

save()
c = srv.settings()
ok(c["rc_addr"] == "12 Main St, Davao" and c["rc_foot"] == "Thank you!", "S2 a request without receipt fields (older screen) keeps the saved values")

save(rc_addr="  12   Main\tSt  ")
ok(srv.settings()["rc_addr"] == "12 Main St", "S3 extra spaces and tabs are collapsed")

for k, mx in srv.RC_LIMITS.items():
    ok(save(**{k: "x" * mx}) is not None and srv.settings()[k] == "x" * mx, "S4 %s accepts exactly %d characters" % (k, mx))
    ok(refused(lambda k=k, mx=mx: save(**{k: "x" * (mx + 1)})), "S4 %s refuses %d characters, nothing saved" % (k, mx + 1))
for label, v in (("number", 123), ("list", ["a"]), ("null", None), ("object", {"a": 1})):
    ok(refused(lambda v=v: save(rc_tag=v)), "S5 a %s is refused for a receipt field" % label)

save(rc_tag="")
ok(srv.settings()["rc_tag"] == "" and sum(1 for g in srv.S["g"] if g["k"] == "Changed: Receipt tagline") >= 2, "S6 blank clears a field and the change is logged")

srv.ACTOR = actor("manager")
ok(refused(lambda: save(rc_foot="hacked"), 403), "S7 a manager cannot change receipt settings")
srv.ACTOR = actor("staff")
srv.ACTOR = actor("owner")
save(rc_addr="12 Main St")
srv.ACTOR = actor("staff")
ok(srv.pub()["cfg"]["rc_addr"] == "12 Main St" and srv.pub()["cfg"]["rc_phone"] == "x" * 32, "S8 staff receive the receipt fields (they print receipts)")
srv.ACTOR = actor("owner")
ok(refused(lambda: srv.r_settings(dict(BASE, password="wrong"), "t"), 403), "S9 wrong password refused")

shutil.rmtree(TMP, ignore_errors=True)
print("FAILED %d" % bad if bad else "ALL PASSED")
sys.exit(1 if bad else 0)
