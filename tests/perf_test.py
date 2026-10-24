# check: tags=slow
"""Speed of the server with a big store (thousands of products, a busy week of sales, a long log).
Limits are generous (they assume an old laptop, ~5x slower than a modern PC); set CHECK_SLOWNESS=2 to loosen them
further on a very slow machine. Every measurement is also printed as a METRIC line for tracking over time."""
import copy, json, os, random, subprocess, sys, time
from harness import *

srv, SRC, TMP = boot("rospos-perf-")
R = Report()
store = Store(srv)
ids = seed(store)
rng = random.Random(seed_value())
SLOW = float(os.environ.get("CHECK_SLOWNESS", "1"))
N_PROD, N_SALES, N_LOG = scale(1500, 5000, 8000), scale(600, 3000, 6000), scale(3000, 15000, 40000)

# ---- build the big store directly in memory (fast), then save once ----
today = srv.now()[0]
tpl_sale = copy.deepcopy(srv.S["s"][0])
srv.S["p"] = [{"id": 10_000 + i, "n": "Product %05d %s" % (i, rng.choice(["Tablet", "Syrup", "Cream", "Drops", "Capsule"])), "p": round(rng.uniform(1, 500), 2),
               "c": round(rng.uniform(.5, 300), 2), "s": rng.randint(0, 300), "m": rng.randint(0, 20), "e": rng.choice(["", "", "2027-12-31"])} for i in range(N_PROD)]
srv.S["s"] = []
for i in range(N_SALES):
    s = copy.deepcopy(tpl_sale)
    picks = rng.sample(srv.S["p"], 3)
    s.update(no=i + 1, d=srv.day_shift(today, -rng.randint(0, 5) if i > N_SALES // 4 else -rng.randint(10, 40)))
    s["l"] = [{"id": p["id"], "n": p["n"], "q": 1 + i % 3, "p": p["p"], "c": p["c"]} for p in picks]
    s["tot"] = srv.R(sum(l["q"] * l["p"] for l in s["l"]))
    s["cash"] = s["tot"]
    srv.S["s"].append(s)
srv.S["g"] = [{"d": srv.day_shift(today, -rng.randint(0, 5)), "t": "10:00 AM", "n": "Product %05d" % (i % N_PROD), "k": "Count set", "a": 1, "z": 2, "u": "Manager2", "i": 10_000 + i % N_PROD, "w": "x"} for i in range(N_LOG // 3)]
for i in range(N_LOG):
    srv.queue_event("sales" if i % 2 else "inventory", "Sale completed" if i % 2 else "Count set", entity_type="sale", entity_id=str(i),
                    entity_name="Receipt #%d" % i, operation_id="perf-%d" % (i // 3), details={"n": i}, source_key="perf-%d" % i)
srv.put("sale_seq", N_SALES + 1)
t = time.perf_counter()
srv.save()
t_save = (time.perf_counter() - t) * 1000

results = []


def check(name, ms, limit_ms, unit="ms", extra=""):
    limit = limit_ms * SLOW
    R.metric(name, round(ms, 1), unit)
    R.ok(ms <= limit, "%s: %.0f %s (limit %d)%s" % (name, ms, unit, limit, extra))


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return (time.perf_counter() - t) * 1000, out


check("save_everything", t_save, 2500, extra=" with %d products, %d sales, %d log rows" % (N_PROD, N_SALES, N_LOG))
ms, r = timed(lambda: store.call("/api/state", role="manager"))
check("state_fetch_manager", ms, 2000, extra=", %.1f MB" % (len(r.data) / 1e6))
R.metric("state_size_manager", round(len(r.data) / 1e6, 2), "MB")
ms, r = timed(lambda: store.call("/api/state", role="staff"))
check("state_fetch_staff", ms, 2000, extra=", %.1f MB" % (len(r.data) / 1e6))
pid = srv.S["p"][5]["id"]
ms, r = timed(lambda: store.call("/api/sale", {"lines": [{"id": pid, "q": 1}], "cash": 1000}, "staff"))
check("sale", ms, 1500, extra=" (this is the click-Pay wait on every tablet)" if r.code == 200 else " FAILED %s" % r.data[:80])
ms, r = timed(lambda: store.call("/api/stock", {"id": pid, "mode": "set", "v": "77", "why": "perf"}, "manager"))
check("stock_edit", ms, 1500)
ms, r = timed(lambda: store.call("/api/logs?category=sales&limit=50", role="manager"))
check("log_page", ms, 2000, extra=", code %s" % r.code)
ms, r = timed(lambda: store.call("/api/logs?category=inventory&q=Product+0042&limit=50", role="manager"))
check("log_search", ms, 3000, extra=", code %s" % r.code)
ms, r = timed(lambda: store.call("/api/backup", role="owner"))
check("backup_download", ms, 6000, extra=", %.1f MB" % (len(r.data) / 1e6))
backup = r.obj["data"]
ms, n = timed(lambda: srv.archive_old())
check("archive_old_sales", ms, 8000, extra=" (%d sales moved out of the live week)" % n)
ms, r = timed(lambda: store.call("/api/restore", {"password": PW, "data": backup}, "owner"))
check("restore", ms, 20000, extra=", code %s" % r.code)
rows = [{"name": "Bulk %05d" % i, "price": "%d.50" % (i % 90 + 1), "quantity": "5", "reorder": "2"} for i in range(5000)]
ms, r = timed(lambda: store.call("/api/import", {"mode": "products", "apply": True, "why": "perf", "rows": rows}, "manager"))
check("import_5000_rows", ms, 6000, extra=", code %s" % r.code)
ms, _ = timed(lambda: srv.real_hash_pw("password123", "00" * 16))
check("password_check", ms, 1500, extra=" (the whole POS waits while one person signs in)")

# ---- start-up time of the server on this much data ----
snapdb = TMP + "/startup.db"
import sqlite3
dst = sqlite3.connect(snapdb)
srv.db.backup(dst)
dst.close()
env = dict(os.environ, POS_DB=snapdb, POS_BACKUP_DIR=TMP + "/b2", POS_ARCHIVE_DIR=TMP + "/a2", PYTHONDONTWRITEBYTECODE="1")
t = time.perf_counter()
p = subprocess.run([sys.executable, "-c", "import server"], cwd=SRC, env=env, capture_output=True, text=True, timeout=300)
check("server_startup", (time.perf_counter() - t) * 1000, 25000, extra="" if p.returncode == 0 else " FAILED: " + p.stderr.strip()[-120:])
shutil.rmtree(TMP, ignore_errors=True)
R.done()
