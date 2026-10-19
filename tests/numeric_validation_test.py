"""Numeric-validation regression tests for server.py (read-only audit helper).

Runs the server's request functions IN-PROCESS against a throw-away database in a temp folder.
It never starts the HTTP server and never opens the real POS database; it also stats the real
data files before and after to prove they were not touched.

Status meanings
  PASS  correct behaviour (invalid input rejected cleanly with no state change, or valid input accepted)
  WARN  invalid input was rejected, but only by an uncaught exception (HTTP 400 "Bad request" or HTTP 500)
  FAIL  invalid input was accepted, or in-memory state was changed by a request that errored
  INFO  advisory: very large but finite values (no upper bound today; a policy decision, not counted)
Exit code is 1 if any FAIL.
"""
import os, sys, json, tempfile, glob

SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = SRC
TMP = tempfile.mkdtemp(prefix="rospos-numtest-")
os.environ.update(POS_DB=TMP + "/pos.db", POS_BACKUP_DIR=TMP + "/backups", POS_PORT="8997", POS_ARCHIVE_DIR=TMP + "/archives")
sys.path.insert(0, SRC)
import server as srv


def stat_real():
    return {f: (os.stat(f).st_mtime_ns, os.stat(f).st_size) for f in sorted(glob.glob(REAL + "/data/*"))}


REAL_BEFORE = stat_real()
PW = "pw12345678"
SALT = "ab" * 8
OWNER = {"id": 1, "name": "Tester", "username": "tester", "role": "owner", "active": True,
         "salt": SALT, "hash": srv.hash_pw(PW, SALT)}
rows = []
counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "INFO": 0}


def fresh():
    today = srv.now()[0]
    srv.S = {"p": [{"id": 1, "n": "Alpha", "p": 5.0, "s": 10, "e": "", "m": 2},
                   {"id": 2, "n": "Half", "p": 0.5, "s": 10, "e": "", "m": 0}],
             "s": [{"no": 1, "d": today, "t": "09:00 AM", "by": "T", "uid": 1, "tot": 10.0, "cash": 10.0,
                    "l": [{"id": 1, "n": "Alpha", "q": 2, "p": 5.0}]}],
             "g": []}
    srv.ACTOR = OWNER


def snap():
    return json.dumps(srv.S, sort_keys=True)


def strict_ok():
    try:
        json.dumps(srv.pub(), allow_nan=False)
        return True
    except ValueError:
        return False


def attempt(fn):
    fresh()
    before = snap()
    try:
        fn()
        kind, detail = "accepted", ""
    except srv.Err as e:
        kind, detail = "Err%d" % e.code, e.msg
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        kind, detail = "generic-400", type(e).__name__
    except Exception as e:
        kind, detail = "http-500", type(e).__name__
    return kind, detail, snap() != before, strict_ok()


def run(cid, desc, fn, expect):
    kind, detail, mutated, strict = attempt(fn)
    if expect == "info":
        status = "INFO"
    elif expect == "accept":
        status = "PASS" if kind == "accepted" else "FAIL"
    else:  # must be rejected
        if kind == "accepted" or mutated:
            status = "FAIL"
        elif kind.startswith("Err"):
            status = "PASS"
        else:
            status = "WARN"
    counts[status] += 1
    note = kind + (" (%s)" % detail if detail and kind != "accepted" else "")
    if mutated and kind != "accepted":
        note += " + STATE CHANGED after error"
    if kind == "accepted" and not strict:
        note += " + state now contains NaN/Infinity (invalid JSON for browsers)"
    rows.append("[%s] %-4s %-62s -> %s" % (status, cid, desc, note))


J = json.loads  # same parser the server uses on request bodies (accepts NaN / Infinity / 1e999)


def sale(cash_json, q="1", lid="1"):
    return lambda: srv.r_sale(J('{"lines":[{"id":%s,"q":%s}],"cash":%s}' % (lid, q, cash_json)), "t")


# ---- sale -------------------------------------------------------------------------------------------
run("S1", "sale cash = NaN", sale("NaN"), "reject")
run("S2", "sale cash = Infinity", sale("Infinity"), "reject")
run("S3", "sale cash = -Infinity", sale("-Infinity"), "reject")
run("S4", "sale cash = 1e999 (standard JSON syntax, parses to inf)", sale("1e999"), "reject")
run("S5", "sale cash = true (total 0.50, true == 1)", sale("true", lid="2"), "reject")
run("S6", "sale cash = \"100\" (string)", sale('"100"'), "reject")
run("S7", "sale quantity = true", sale("5", q="true"), "reject")
run("S8", "sale quantity = NaN", sale("5", q="NaN"), "reject")
run("S9", "sale quantity = 1.5", sale("5", q="1.5"), "reject")
run("S10", "valid: cash exactly the total", sale("5"), "accept")
run("S11", "valid: cash omitted (defaults to total)", lambda: srv.r_sale(J('{"lines":[{"id":1,"q":1}]}'), "t"), "accept")
run("S12", "valid: cash 100.5 for a 5.00 sale", sale("100.5"), "accept")
run("S13", "boundary: cash 4.99 for a 5.00 sale", sale("4.99"), "reject")
run("S14", "advisory: cash = 1e308 (finite)", sale("1e308"), "info")

# ---- product create / edit -------------------------------------------------------------------------
def prod_new(price, extra=""):
    return lambda: srv.r_product(J('{"n":"New","p":%s%s}' % (price, extra)), "t")


def prod_edit(price):
    return lambda: srv.r_product(J('{"id":1,"n":"Alpha","p":%s}' % price), "t")


for cid, lbl, v in [("P1", "NaN", "NaN"), ("P2", "Infinity", "Infinity"), ("P3", "-Infinity", "-Infinity"),
                    ("P4", "1e999", "1e999"), ("P5", "true", "true"), ("P6", "-0.01", "-0.01"),
                    ("P7", "1e307 (finite, overflows rounding)", "1e307"), ("P8", "\"12\" string", '"12"')]:
    run(cid, "new product price = " + lbl, prod_new(v), "reject")
run("P9", "edit product price = NaN", prod_edit("NaN"), "reject")
run("P10", "edit product price = Infinity", prod_edit("Infinity"), "reject")
run("P11", "valid: new product price 12.5", prod_new("12.5"), "accept")
run("P12", "valid: new product price 0 (free item)", prod_new("0"), "accept")
run("P13", "reorder level = Infinity", prod_new("5", ',"m":Infinity'), "reject")
run("P14", "starting stock = Infinity", prod_new("5", ',"s":Infinity'), "reject")
run("P15", "reorder level = NaN (silently becomes 0)", prod_new("5", ',"m":NaN'), "reject")
run("P16", "advisory: price 1e15 / stock 1e18 accepted", prod_new("1e15", ',"s":1000000000000000000'), "info")

# ---- stock adjust ----------------------------------------------------------------------------------
for cid, lbl, v in [("T1", "\"NaN\"", '"NaN"'), ("T2", "\"Infinity\"", '"Infinity"'), ("T3", "5.0 (number)", "5.0"),
                    ("T4", "true", "true"), ("T5", "\"-3\"", '"-3"'), ("T6", "\"\\u00b2\" (superscript two)", '"\\u00b2"')]:
    run(cid, "stock set, value = " + lbl, lambda v=v: srv.r_stock(J('{"id":1,"mode":"set","v":%s}' % v), "t"), "reject")
run("T7", "valid: stock set to \"7\"", lambda: srv.r_stock(J('{"id":1,"mode":"set","v":"7"}'), "t"), "accept")
run("T8", "advisory: stock add of 30-digit number", lambda: srv.r_stock(J('{"id":1,"mode":"add","v":"%s"}' % ("9" * 30)), "t"), "info")

# ---- change / void ---------------------------------------------------------------------------------
def change(cash, q="[1]", no="1"):
    return lambda: srv.r_change(J('{"no":%s,"q":%s,"cash":%s,"why":"t","password":"%s"}' % (no, q, cash, PW)), "t")


run("C1", "change sale, cash = NaN", change("NaN"), "reject")
run("C2", "change sale, cash = Infinity", change("Infinity"), "reject")
run("C3", "change sale, cash = true", change("true"), "reject")
run("C4", "change sale, quantity = true", change("5", q="[true]"), "reject")
run("C5", "change sale, quantity = NaN", change("5", q="[NaN]"), "reject")
run("C6", "valid: change sale to 1 unit, cash 5", change("5"), "accept")
run("C7", "boundary: cash 4.99 for new total 5.00", change("4.99"), "reject")
run("V1", "void sale no = true (matches sale #1)", lambda: srv.r_void(J('{"no":true,"why":"t","password":"%s"}' % PW), "t"), "reject")
run("V2", "valid: void sale no = 1", lambda: srv.r_void(J('{"no":1,"why":"t","password":"%s"}' % PW), "t"), "accept")

# ---- settings --------------------------------------------------------------------------------------
def settings(hrs, days="30"):
    return lambda: srv.r_settings(J('{"store":"S","session_hours":%s,"backup_days":%s,"password":"%s"}' % (hrs, days, PW)), "t")


for cid, lbl, v in [("G1", "NaN", "NaN"), ("G2", "Infinity", "Infinity"), ("G3", "-Infinity", "-Infinity"),
                    ("G4", "true (becomes 1.0)", "true"), ("G5", "0.99", "0.99"), ("G6", "72.01", "72.01")]:
    run(cid, "settings sign-in hours = " + lbl, settings(v), "reject")
run("G7", "settings backup days = true", settings("8", "true"), "reject")
run("G8", "valid: 8 hours, 30 days", settings("8", "30"), "accept")
run("G9", "boundary: 1 hour / 7 days", settings("1", "7"), "accept")
run("G10", "boundary: 72 hours / 365 days", settings("72", "365"), "accept")

# ---- restore ---------------------------------------------------------------------------------------
def backup(prod_p="5.0", prod_s="3", tot="10.0", line_p="5.0", line_q="2"):
    return ('{"p":[{"id":1,"n":"A","p":%s,"s":%s,"m":1,"e":""}],'
            '"s":[{"no":1,"d":"2026-01-01","t":"09:00 AM","tot":%s,"cash":%s,"l":[{"id":1,"n":"A","q":%s,"p":%s}]}],"g":[]}'
            % (prod_p, prod_s, tot, tot, line_q, line_p))


def restore(text):
    return lambda: srv.r_restore(J('{"password":"%s","data":%s}' % (PW, text)), "t")


for cid, lbl, kw in [("R1", "product price NaN", dict(prod_p="NaN")), ("R2", "product price Infinity", dict(prod_p="Infinity")),
                     ("R3", "product price true", dict(prod_p="true")), ("R4", "product stock true", dict(prod_s="true")),
                     ("R5", "sale total NaN", dict(tot="NaN")), ("R6", "sale total -Infinity", dict(tot="-Infinity")),
                     ("R7", "sale line price NaN", dict(line_p="NaN")), ("R8", "sale line price 1e999", dict(line_p="1e999")),
                     ("R9", "sale line quantity true", dict(line_q="true")), ("R10", "product price negative", dict(prod_p="-1"))]:
    run(cid, "restore backup with " + lbl, restore(backup(**kw)), "reject")
run("R11", "valid: restore a well-formed backup", restore(backup()), "accept")
run("R12", "restore with non-string expiry / string reorder level",
    restore('{"p":[{"id":1,"n":"A","p":5,"s":3,"e":123,"m":"x"}],"s":[],"g":[]}'), "reject")
run("R13", "restore with string sale number",
    restore(backup().replace('"no":1', '"no":"1"')), "reject")
run("R14", "restore with boolean sale number",
    restore(backup().replace('"no":1', '"no":true')), "reject")
run("R15", "restore with non-string sale date",
    restore(backup().replace('"d":"2026-01-01"', '"d":20260101')), "reject")

# ---- import ----------------------------------------------------------------------------------------
def imp(rows_json, mode="products", apply_="true"):
    def go():
        out = srv.r_import(J('{"mode":"%s","apply":%s,"why":"t","rows":%s}' % (mode, apply_, rows_json)), "t")
        plan = out["plan"]
        if plan["errorCount"]:  # the import reports row errors in the plan instead of raising
            raise srv.Err(400, "; ".join(e["msg"] for e in plan["errors"][:2]))
        return out
    return go


for cid, lbl, v in [("I1", "price \"NaN\"", '"NaN"'), ("I2", "price \"Infinity\"", '"Infinity"'), ("I3", "price \"-inf\"", '"-inf"'),
                    ("I4", "price \"1e999\"", '"1e999"'), ("I5", "price NaN (JSON constant)", "NaN"),
                    ("I6", "price true", "true"), ("I7", "price \"-1\"", '"-1"')]:
    run(cid, "import new product, " + lbl, imp('[{"name":"Imp","price":' + v + ',"quantity":"1"}]'), "reject")
run("I8", "valid: import new product price \"5.50\", qty 3", imp('[{"name":"Imp","price":"5.50","quantity":"3"}]'), "accept")
run("I9", "import quantity \"NaN\" (mode set)", imp('[{"name":"Alpha","quantity":"NaN"}]', "set"), "reject")
run("I10", "import quantity \"2.5\" (mode add)", imp('[{"name":"Alpha","quantity":"2.5"}]', "add"), "reject")
run("I11", "import: row 1 valid, row 2 new product price \"1e307\" (all-or-nothing?)",
    imp('[{"name":"Good","price":"5","quantity":"1"},{"name":"Huge","price":"1e307","quantity":"1"}]'), "reject")
run("I12", "import existing product price \"1e307\" (preview only)",
    imp('[{"name":"Alpha","price":"1e307"}]', "products", "false"), "reject")
run("I13", "advisory: import quantity \"1e18\"", imp('[{"name":"Alpha","quantity":"1e18"}]', "set"), "info")

# ---- parser / output boundary ----------------------------------------------------------------------
parse_nan = J('{"x":NaN,"y":Infinity,"z":-Infinity,"w":1e999}')
fresh()
srv.S["s"][0]["cash"] = float("nan")
out_text = json.dumps({"state": srv.pub()})
rows.append("[INFO] B1   json.loads accepts NaN/Infinity/-Infinity/1e999 -> %s" % {k: v for k, v in parse_nan.items()})
rows.append("[INFO] B2   json.dumps (used by send()/backup) writes NaN as bare token -> 'NaN' in output: %s" % ("NaN" in out_text))
import subprocess
node = subprocess.run(["node", "-e", "try{JSON.parse(require('fs').readFileSync(0,'utf8'));console.log('parsed fine')}catch(e){console.log('JSON.parse ERROR: '+e.message)}"],
                      input=out_text, capture_output=True, text=True)
rows.append("[INFO] B3   browser-style JSON.parse of a response whose state holds a NaN cash -> %s" % node.stdout.strip())
fresh()
try:
    imp('[{"name":"Good","price":"5","quantity":"1"},{"name":"Huge","price":"1e307","quantity":"1"}]')()
except Exception as e:
    err_name = type(e).__name__
mem = [p["n"] for p in srv.S["p"]]
srv.save()  # what the next successful request of any kind does
disk = [p["n"] for p in srv.get("state")["p"]]
rows.append("[INFO] D1   failed import (%s): products in memory %s; after the next save() on disk %s" % (err_name, mem, disk))

print("\n".join(rows))
print("\nSUMMARY  PASS=%(PASS)d  WARN=%(WARN)d  FAIL=%(FAIL)d  INFO=%(INFO)d" % counts)
after = stat_real()
print("Real database files untouched:", REAL_BEFORE == after, "| temp dir used:", TMP)
sys.exit(1 if counts["FAIL"] else 0)
