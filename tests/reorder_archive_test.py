#!/usr/bin/env python3
"""Reorder sold-in-30-days totals include archived sales without exposing costs."""
from harness import boot, Store, Report, seed

srv, SRC, TMP = boot("rospos-reorder-history-")
report = Report()
store = Store(srv)
ids = seed(store)
today = srv.now()[0]
archived_day = srv.day_shift(today, -20)
last_included = srv.day_shift(today, -29)
outside_window = srv.day_shift(today, -30)
product_id = ids["P"][0]


def sale(no, day, quantity, void=False):
    record = {"no": no, "d": day, "t": "10:00 AM", "tot": quantity * 5,
              "l": [{"id": product_id, "n": "Tablet", "q": quantity, "p": 5, "c": 2}]}
    if void:
        record["v"] = {"w": "Duplicate sale"}
    return record


# An archived copy of a receipt can overlap with a newer hot copy.
srv._merge_day_archive(archived_day,
    [sale(8801, archived_day, 4), sale(8802, archived_day, 7, void=True)], [])
srv._merge_day_archive(last_included, [sale(8803, last_included, 2)], [])
srv._merge_day_archive(outside_window, [sale(8804, outside_window, 99)], [])
srv.S["s"].append(sale(8801, archived_day, 6))
report.ok(store.call("/api/reorder-sales").code == 401,
          "reorder: unauthenticated clients cannot read stock demand")
response = store.call("/api/reorder-sales", role="staff")
result = response.obj or {}
report.ok(response.code == 200 and result.get("quantities", {}).get(str(product_id)) >= 8,
          "reorder: staff can retrieve archived thirty-day demand")
hot_sales = [s for s in srv.S["s"] if isinstance(s, dict)
             and s.get("d", "") >= srv.day_shift(today, -29) and not s.get("v")]
hot_total = sum(line.get("q", 0) for s in hot_sales
                for line in s.get("l", []) if line.get("id") == product_id)
report.ok(result.get("quantities", {}).get(str(product_id)) == hot_total + 2,
          "reorder: archived last day included, voids skipped, hot duplicates supersede archive")
report.ok(result.get("unavailable") == [] and "c" not in str(result),
          "reorder: no cost information or missing-data warning on intact archives")
report.ok(store.call("/api/reorder-sales", role="manager").code == 200,
          "reorder: manager retains read access")

report.done()
