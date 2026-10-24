#!/usr/bin/env python3
"""SQLite commit failures restore the durable in-memory POS state and retry safely."""
import copy
import json
from harness import boot, Store, Report, seed

srv, SRC, TMP = boot("rospos-save-failure-")
report = Report()
store = Store(srv)
ids = seed(store)
baseline = copy.deepcopy(srv.S)
first_id = ids["P"][0]
rid = "sqlite-failure-retry-10001"
body = {"rid": rid, "lines": [{"id": first_id, "q": 1}], "cash": 10000}

# Force a real SQLite insert failure without modifying the configured live DB.
srv.db.execute("""
    create temp trigger deny_state BEFORE INSERT ON kv
    WHEN NEW.k='state'
    BEGIN SELECT RAISE(FAIL,'injected save failure'); END
""")
srv.db.commit()
failed = store.call("/api/sale", body, role="staff")
report.ok(failed.code == 500, "save failure: checkout is not reported as successful")
report.ok(srv.S == baseline and srv.get("state") == baseline,
          "save failure: stock, sales and purchases match the durable database")
report.ok(srv.PENDING_SALE_REQUEST is None and not srv.PENDING_AUDIT_EVENTS,
          "save failure: no phantom payment key or sale audit event remains queued")
report.ok(not srv.db.execute(
    "select sale_no from sale_requests where request_id=?", (rid,)
).fetchone(), "save failure: payment retry key was not persisted")

srv.db.execute("drop trigger deny_state")
srv.db.commit()
success = store.call("/api/sale", body, role="staff")
retry = store.call("/api/sale", body, role="staff")
report.ok(success.code == 200 and retry.code == 200 and
          success.obj["sale"]["no"] == retry.obj["sale"]["no"],
          "save failure: same request id can be retried exactly once after recovery")
report.ok(len(srv.S["s"]) == len(baseline["s"]) + 1 and
          srv.get("state") == srv.S,
          "save failure: successful retry persists exactly one new sale")

report.done()
