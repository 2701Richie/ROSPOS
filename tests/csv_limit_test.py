#!/usr/bin/env python3
"""The 5,000-row CSV import limit fails cleanly without partial changes."""
from harness import boot, Store, Report, seed

srv, SRC, TMP = boot("rospos-import-limit-")
report = Report()
store = Store(srv)
seed(store)
before = srv.get("state")
rows = [{"name": "Extra %05d" % n, "price": "10", "quantity": "1"} for n in range(5001)]
too_big = store.call("/api/import", {"mode": "products", "rows": rows, "apply": True,
                                    "why": "Import limit verification"}, role="manager")
report.ok(too_big.code == 400 and "5000" in str(too_big.obj),
          "CSV limit: server reports 400 with a clear 5000-row maximum")
report.ok(srv.get("state") == before and srv.S == before,
          "CSV limit: excessive import does not partially write inventory")
report.ok(not any(p["n"].startswith("Extra ") for p in srv.S["p"]),
          "CSV limit: no extra product was imported")
report.done()
