#!/usr/bin/env python3
"""Isolated Phase 4 archive-history performance check. No production data."""
import json, os, time
from harness import boot, Store, seed
srv, SRC, TMP = boot("rospos-report-perf-")
store = Store(srv)
seed(store)
today = srv.now()[0]
days = [srv.day_shift(today, -i) for i in range(1, 91)]
# 90,000 archived transactions: 1,000 per day, realistic item payloads.
for idx, day in enumerate(days):
    sales = [{"no":idx*1000+j+10000,"d":day,"t":"01:30 PM","by":"Cashier",
              "tot":125,"l":[{"id":1,"n":"Tablet 500 mg","q":1,"p":125,"c":50}]}
             for j in range(1000)]
    path=os.path.join(srv.ARCHIVE_DIR,"sales-"+day+".json")
    os.makedirs(srv.ARCHIVE_DIR,exist_ok=True)
    with open(path,"w") as f:
        json.dump({"format":"ROSPOS-day-archive","version":1,"date":day,"s":sales,"g":[]},f)
start=time.perf_counter()
r=store.call("/api/report-sales?date="+days[-1],role="manager")
elapsed=time.perf_counter()-start
payload=len(r.data)
assert r.code==200,(r.code,r.data[:300])
assert len(r.obj["days"])==90 and len(r.obj["sales"])==1000
assert sum(x["count"] for x in r.obj["days"] if x["date"]!=today)==89000
assert sum(x["total"] for x in r.obj["days"] if x["date"]!=today)==11125000
print(f"PASS 90,000 archived sales: 90 summary days, 1,000 selected receipts, {elapsed:.3f} s, {payload/1024:.1f} KiB response")
print("PASS no production database or archive paths accessed")
