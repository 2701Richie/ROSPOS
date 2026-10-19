"""Archive tests: old sales/audit rows move to daily JSON files, sale numbers are never reused.

In-process against a throw-away database and archive folder in a temp dir. Never starts the HTTP
server, never touches the real database, backups or archives.
Usage: python3 tests/archive_test.py [source-folder]     Output: 'ok   ...' / 'FAIL ...' lines
"""
import os, sys, json, shutil, tempfile

SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="rospos-archtest-")
os.environ.update(POS_DB=TMP + "/pos.db", POS_BACKUP_DIR=TMP + "/backups", POS_ARCHIVE_DIR=TMP + "/archives",
                  POS_PORT="8996", PYTHONDONTWRITEBYTECODE="1")
sys.dont_write_bytecode = True
sys.path.insert(0, SRC)
import server as srv

if not hasattr(srv, "archive_old"):
    print("SKIP this source has no archive feature")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0)

bad = 0


def ok(c, m):
    global bad
    print(("ok   " if c else "FAIL ") + m)
    bad += 0 if c else 1


today = srv.now()[0]
day = lambda n: srv.day_shift(today, -n)
sale = lambda no, d: {"no": no, "d": d, "t": "09:00 AM", "by": "T", "uid": 1, "tot": 10.0, "cash": 10.0, "l": []}
log = lambda d, n: {"d": d, "t": "09:00 AM", "n": n, "k": "sale", "a": 10.0}
arch = lambda d: os.path.join(srv.ARCHIVE_DIR, "sales-%s.json" % d)
hot = srv.HOT_DAYS

# A1 legacy upgrade: old sales exist, the database has never stored sale_seq (first start after update)
srv.S = {"p": [], "s": [sale(1, day(30)), sale(2, day(20)), sale(3, day(hot + 1))], "g": []}
ok(srv.get("sale_seq") is None, "A1 setup: no sale_seq stored yet (legacy database)")
srv.archive_old()
nxt = srv.next_sale_no()
ok(nxt == 4, "A1 first sale after archiving every old sale gets number 4, not %s (numbers never reused)" % nxt)

# A2 what moves and what stays
srv.S = {"p": [], "s": [sale(10, day(hot + 3)), sale(11, day(hot)), sale(12, day(2)), sale(13, today)],
         "g": [log(day(hot + 3), 1), log(day(hot), 2), log(today, 3)]}
moved = srv.archive_old()
ok(moved == 1, "A2 only the sale older than %d days moved (moved %s)" % (hot, moved))
ok([s["no"] for s in srv.S["s"]] == [11, 12, 13], "A2 sale exactly %d days old and newer stay live" % hot)
ok([g["n"] for g in srv.S["g"]] == [2, 3], "A2 audit rows follow the same cutoff")
f = arch(day(hot + 3))
ok(os.path.isfile(f), "A2 archive file written: sales-<day>.json")
data = json.load(open(f)) if os.path.isfile(f) else {}
ok(data.get("format") == "ROSPOS-day-archive" and data.get("date") == day(hot + 3), "A2 archive has format and date")
ok([s["no"] for s in data.get("s", [])] == [10] and [g["n"] for g in data.get("g", [])] == [1], "A2 archive holds that day's sale and audit rows")

# A3 running again is a no-op
mtime = os.stat(f).st_mtime_ns if os.path.isfile(f) else 0
ok(srv.archive_old() == 0 and os.stat(f).st_mtime_ns == mtime, "A3 second run changes nothing")

# A4 merging the same day twice never duplicates
srv._merge_day_archive(day(hot + 3), [sale(10, day(hot + 3)), sale(14, day(hot + 3))], [log(day(hot + 3), 1)])
data = json.load(open(f))
ok([s["no"] for s in data["s"]] == [10, 14] and len(data["g"]) == 1, "A4 merge adds new sale, skips duplicates")

# A5 rows with a bad or missing date are never archived or dropped
srv.S = {"p": [], "s": [sale(20, None), sale(21, "garbage")], "g": [log(None, 9)]}
srv.archive_old()
ok(len(srv.S["s"]) == 2 and len(srv.S["g"]) == 1, "A5 rows with a bad date stay in live state")

# A6 normal numbering keeps counting up, including after live rows are archived
srv.S = {"p": [], "s": [sale(30, today)], "g": []}
a, b = srv.next_sale_no(), srv.next_sale_no()
ok(b == a + 1 and a > 30, "A6 next numbers keep increasing (%s, %s)" % (a, b))

# A7 archive survives a restart of the process state: the file is plain readable JSON
ok(all(isinstance(json.load(open(os.path.join(srv.ARCHIVE_DIR, x))), dict) for x in os.listdir(srv.ARCHIVE_DIR)), "A7 every archive file is valid JSON")

# A8 an unreadable archive file is kept aside, never overwritten
bad_day = day(hot + 9)
os.makedirs(srv.ARCHIVE_DIR, exist_ok=True)
open(arch(bad_day), "w").write("{ this is not json")
srv._merge_day_archive(bad_day, [sale(40, bad_day)], [])
kept = [x for x in os.listdir(srv.ARCHIVE_DIR) if x.startswith("sales-%s.json.corrupt-" % bad_day)]
ok(len(kept) == 1 and open(os.path.join(srv.ARCHIVE_DIR, kept[0])).read() == "{ this is not json", "A8 unreadable archive kept aside as .corrupt-*")
ok([s["no"] for s in json.load(open(arch(bad_day)))["s"]] == [40], "A8 fresh archive written next to it")

# A9 archive failure (bad folder) never raises and never loses live rows
good_dir = srv.ARCHIVE_DIR
open(TMP + "/blocker", "w").write("x")
srv.ARCHIVE_DIR = TMP + "/blocker/sub"
srv.S = {"p": [], "s": [sale(50, day(hot + 5))], "g": []}
try:
    r = srv.safe_archive()
    ok(r == 0 and len(srv.S["s"]) == 1, "A9 failed archive returns 0 and keeps the sale live")
except Exception as e:
    ok(False, "A9 safe_archive raised %r" % e)
srv.ARCHIVE_DIR = good_dir

# A10 odd sale numbers in live data do not break numbering
srv.S = {"p": [], "s": [{"no": "x", "d": today}, {"no": True, "d": today}, sale(60, today)], "g": []}
try:
    ok(srv.next_sale_no() > 60, "A10 next_sale_no ignores rows with odd sale numbers")
except Exception as e:
    ok(False, "A10 next_sale_no raised %r" % e)

shutil.rmtree(TMP, ignore_errors=True)
print("FAILED %d" % bad if bad else "ALL PASSED")
sys.exit(1 if bad else 0)
