#!/usr/bin/env python3
"""Phase 4: archived sales report lookup, permissions and accuracy; temporary data only."""
import json
import os
import sys
from harness import boot, Store, Report, seed

srv, SRC, TMP = boot("rospos-report-history-")
R = Report()
store = Store(srv)
seed(store)
today = srv.now()[0]
day = srv.day_shift(today, -20)
old = srv.day_shift(today, -120)

def sale(no, when, total, void=False):
    out = {"no": no, "d": when, "t": "09:20 AM", "by": "Tester",
           "tot": total, "l": [{"id": 1, "n": "Archived Tablet", "q": 1, "p": total, "c": 2.5}]}
    if void:
        out["v"] = {"w": "Duplicate", "u": "Tester"}
    return out

srv._merge_day_archive(day, [sale(500, day, 125), sale(501, day, 55, True)], [])
srv._merge_day_archive(old, [sale(100, old, 75)], [])
R.ok(store.call("/api/report-sales").code == 401, "report history: requires sign-in")
R.ok(store.call("/api/receipt-date").code == 401,
     "receipt history: requires sign-in")
R.ok(store.call("/api/receipt-date?date=2026-02-30", role="staff").code == 400,
     "receipt history: invalid date is rejected")
R.ok(store.call("/api/report-sales", role="staff").code == 403, "report history: staff cannot view manager reports")
R.ok(store.call("/api/report-sales?date=2026-02-30", role="manager").code == 400,
     "report history: rejects impossible calendar dates")
R.ok(store.call("/api/report-sales?date=../etc/passwd", role="manager").code == 400,
     "report history: rejects unsafe date paths")
response = store.call("/api/report-sales?date=" + day, role="manager")
out = response.obj or {}
row = next((x for x in out.get("days", []) if x["date"] == day), None)
R.ok(response.code == 200 and [s["no"] for s in out.get("sales", [])] == [500, 501],
     "report history: manager retrieves completed and voided archived receipts")
R.ok(row is not None and row["count"] == 1 and row["voided"] == 1 and row["total"] == 125,
     "report history: 90-day totals exclude voided receipts")
R.ok(row["profit"] == 122.5 and row["revenue_costed"] == 125 and
     row["lines"] == 1 and row["missing"] == 0,
     "report history: archived unit costs contribute correctly to 30-day profit")
R.ok(all("c" not in l for s in out.get("sales", []) for l in s["l"]),
     "report history: historic line costs are excluded from reports")
staff_receipts = store.call("/api/receipt-date?date=" + day, role="staff")
R.ok(staff_receipts.code == 200 and [s["no"] for s in staff_receipts.obj["sales"]] == [500, 501]
     and all("c" not in l for s in staff_receipts.obj["sales"] for l in s["l"]),
     "receipt history: staff can reprint archived receipts without exposing cost")
older = store.call("/api/report-sales?date=" + old, role="owner").obj
R.ok(len(older["sales"]) == 1 and older["sales"][0]["no"] == 100 and
     all(x["date"] != old for x in older["days"]),
     "report history: older dates can be retrieved without changing the 90-day summary window")
# Hot state wins if it has a newer version of an archived receipt.
srv.S["s"].append(sale(500, day, 140))
updated = store.call("/api/report-sales?date=" + day, role="manager").obj
R.ok(updated["sales"][0]["tot"] == 140 and
     next(x for x in updated["days"] if x["date"] == day)["total"] == 140,
     "report history: live copy of a receipt takes priority without duplication")
# Corrupt archives produce an explicit incompleteness flag rather than fake zero results.
bad_day = srv.day_shift(today, -25)
with open(os.path.join(srv.ARCHIVE_DIR, "sales-" + bad_day + ".json"), "w") as f:
    f.write("{bad json")
unreadable = store.call("/api/report-sales?date=" + bad_day, role="manager").obj
R.ok(bad_day in unreadable["unavailable"],
     "report history: unreadable archives are explicitly reported")
R.ok(not store.problems, "report history: no password secrets leaked")
R.done()
