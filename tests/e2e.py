import subprocess, time, json, os, sys, shutil, re, glob, tempfile, urllib.request, urllib.error, http.cookiejar

# Usage: python3 e2e.py [source-folder]   (default: the project folder this file lives in)
SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = tempfile.mkdtemp(prefix="rospos-e2e-")
BASE = "http://127.0.0.1:8998"
shutil.copytree(SRC, W + "/clone", ignore=shutil.ignore_patterns("data", "backups", "archives", ".git", "__pycache__", "source-backups", "tests"))
env = dict(os.environ, POS_DB=W + "/data/pos.db", POS_BACKUP_DIR=W + "/backups", POS_PORT="8998", POS_ARCHIVE_DIR=W + "/archives", PYTHONDONTWRITEBYTECODE="1")
bad = 0


def ok(c, m):
    global bad
    print(("ok   " if c else "FAIL ") + m)
    bad += 0 if c else 1


def start():
    p = subprocess.Popen([sys.executable, "server.py"], cwd=W + "/clone", env=env,
                         stdout=open(W + "/server.log", "a"), stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/", timeout=1)
            return p
        except Exception:
            time.sleep(0.2)
    raise SystemExit("server did not start: " + open(W + "/server.log").read())


class C:
    def __init__(s):
        s.o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def req(s, path, body=None):
        r = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json", "X-Requested-With": "pos"})
        try:
            with s.o.open(r, timeout=10) as x:
                return x.status, x.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def j(s, path, body=None):
        c, b = s.req(path, body)
        try:
            return c, json.loads(b)
        except Exception:
            return c, b

    def state(s):
        r = s.j("/api/state")[1]
        return r.get("state", r)


srv = start()
a = C()
c, html = a.req("/")
html = html.decode()
ok(c == 200 and "<title>" in html, "index served")
files = re.findall(r'(?:src|href)="(/[^"]+)"', html)
bad_files = [f for f in files if a.req(f)[0] != 200]
ok(files and not bad_files, "all %d linked files served %s" % (len(files), bad_files))
ok(a.j("/api/state")[0] == 401, "state needs sign-in")
ok(not os.path.exists(W + "/clone/data"), "clone has no data folder (no database in the repo)")
code = re.search(r"SETUP CODE: (\w+)", open(W + "/server.log").read()).group(1)
ok(a.j("/api/setup", {"code": "WRONG1", "username": "owner", "name": "Owner", "password": "ownerpass1"})[0] == 403, "wrong setup code refused")
c, r = a.j("/api/setup", {"code": code, "username": "owner", "name": "Owner", "password": "ownerpass1"})
ok(c == 200 and r["me"]["role"] == "owner", "setup creates the owner and signs in")
ok(a.j("/api/setup", {"code": code, "username": "x1x", "name": "X", "password": "password12"})[0] == 403, "setup cannot run twice")
for n, p, e, m, s in [("Biogesic", 6, "", 40, 120), ("Amoxicillin", 14, "", 40, 10), ("Old stock", 5, "2020-01-01", 5, 50)]:
    ok(a.j("/api/product", {"n": n, "p": p, "e": e, "m": m, "s": s})[0] == 200, "add product " + n)
prods = {x["n"]: x for x in a.state()["p"]}
ok(len(prods) == 3 and prods["Biogesic"]["s"] == 120, "3 products with starting stock")
bid, aid, oid = prods["Biogesic"]["id"], prods["Amoxicillin"]["id"], prods["Old stock"]["id"]
ok(a.j("/api/sale", {"lines": [{"id": bid, "q": 2}, {"id": aid, "q": 1}], "cash": 100})[0] == 200, "sale accepted")
st = a.state()
ok({x["n"]: x["s"] for x in st["p"]}["Biogesic"] == 118 and len(st["s"]) == 1 and st["s"][0]["tot"] == 26, "stock reduced, sale total is 26")
ok(a.j("/api/sale", {"lines": [{"id": aid, "q": 999}]})[0] in (400, 409), "selling more than stock refused")
ok(a.j("/api/sale", {"lines": [{"id": oid, "q": 1}]})[0] == 409, "expired product refused")
ok(a.j("/api/sale", {"lines": []})[0] == 400, "empty sale refused")
good = {"store": "Test Store", "session_hours": 8, "backup_days": 14}
ok(a.j("/api/settings", dict(good, password="nope"))[0] == 403, "settings: wrong password refused")
ok(a.j("/api/settings", dict(good, password="ownerpass1"))[0] == 200, "settings saved")
st = a.state()
ok(st["cfg"]["store"] == "Test Store" and st["cfg"]["backup_days"] == 14 and any(g["n"] == "Settings" for g in st["g"]), "settings visible to clients and logged")
ok(a.j("/api/settings", dict(good, session_hours=500, password="ownerpass1"))[0] == 400, "settings: bad hours refused")
ok(a.j("/api/user", {"username": "staff1", "name": "Staff One", "role": "staff", "password": "staffpass1", "active": True})[0] == 200, "owner creates a staff account")
s = C()
c, r = s.j("/api/login", {"username": "staff1", "password": "staffpass1"})
ok(c == 200 and r["me"]["role"] == "staff", "staff signs in")
ok(s.j("/api/settings", dict(good, store="Hack", password="staffpass1"))[0] == 403, "staff cannot change settings")
ok(s.j("/api/users", {})[0] == 403, "staff cannot list accounts")
ok(s.j("/api/logs?category=inventory")[0] == 403, "staff cannot access the Log Center API")
ok(s.j("/api/product", {"n": "Nope", "p": 1})[0] == 403, "staff cannot add products")
ok(s.j("/api/sale", {"lines": [{"id": bid, "q": 1}]})[0] == 200, "staff can sell")
ok(s.req("/api/backup")[0] == 403, "staff cannot download a backup")
ok(a.j("/api/void", {"no": 1, "password": "ownerpass1", "why": "test"})[0] == 200, "owner voids a sale")
st = a.state()
ok({x["n"]: x["s"] for x in st["p"]}["Biogesic"] == 119 and st["s"][0].get("v"), "void restores stock (117 + 2 = 119) and marks the sale")
c, bk = a.req("/api/backup")
bk = json.loads(bk)
ok(c == 200 and bk["format"] == "ROSPOS-backup" and len(bk["data"]["s"]) == 2, "owner downloads backup")
ok(isinstance(bk["data"].get("logs"), list) and any(x.get("category")=="sales" for x in bk["data"]["logs"]), "portable backup includes retained audit logs")
a.j("/api/sale", {"lines": [{"id": bid, "q": 5}]})
ok(a.j("/api/restore", {"data": bk["data"], "password": "ownerpass1"})[0] == 200, "restore accepted")
st = a.state()
ok(len(st["s"]) == 2 and st["cfg"]["store"] == "Test Store", "restore returns to the backup and keeps settings")
c, retained = a.j("/api/logs?category=sales")
ok(c == 200 and retained["total"] >= 3 and any(x.get("entity_name") == "Receipt #3" for x in retained["items"]), "restore keeps both backed-up and newer sales audit events")
ok(glob.glob(W + "/backups/pre-restore-*.db"), "safety snapshot made before restore")
time.sleep(1)
ok(glob.glob(W + "/backups/pos-*.db"), "hourly backup file exists")
srv.terminate()
srv.wait()
srv = start()
b = C()
ok(b.j("/api/login", {"username": "owner", "password": "ownerpass1"})[0] == 200, "owner signs in after restart")
st = b.state()
ok(len(st["p"]) == 3 and len(st["s"]) == 2 and st["cfg"]["store"] == "Test Store", "data and settings survive a restart")
ok(b.j("/api/login", {"username": "owner", "password": "wrongwrong"})[0] == 403, "wrong password refused")
srv.terminate()
srv.wait()
ok("Traceback" not in open(W + "/server.log").read(), "no errors in the server log")
shutil.rmtree(W, ignore_errors=True)
print("FAILED %d" % bad if bad else "ALL PASSED")
sys.exit(1 if bad else 0)
