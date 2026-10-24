#!/usr/bin/env python3
"""Phase 6 contract tests for the extracted, side-effect-free backend services.

Run against an explicit source folder or the current project. Uses only in-memory
SQLite and temporary archive files, never the production POS database.
"""
import json
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from poscore import archive_store, audit_events, audit_queries, auth_sessions, history, state_views, values

failures = 0


def ok(condition, name):
    global failures
    print(("ok   " if condition else "FAIL ") + name)
    failures += not condition


ok(not any(name == "server" for name in sys.modules), "M1 services import without starting POS server")
ok(values.good_num(12.5) and not values.good_num(True) and not values.good_num(float("inf")),
   "M2 numeric validation retains strict finite, non-boolean semantics")
ok(values.valid_expiry("") and values.valid_expiry("2027-11-28")
   and not values.valid_expiry("2027-02-30"),
   "M3 expiry validation still rejects invalid calendar dates")
ok(values.max_sale_no([{"no": 10}, {"no": True}, {"no": 4}]) == 10,
   "M4 sale sequence ignores booleans and invalid numbers")

raw_hash = auth_sessions.hash_password("secure-password", "ab" * 16)
ok(len(raw_hash) == 64, "M5 PBKDF2 hashing returns a SHA-256 digest")
users = {7: {"id": 7, "role": "staff", "active": True}}
sessions = {}
token = auth_sessions.create_session(users[7], sessions, 1)


class Handler:
    def __init__(self, cookie):
        self.headers = {"Cookie": cookie}


account, returned_token = auth_sessions.resolve_session(
    Handler("another=value; pos_session=" + token), sessions, users.get
)
ok(account is users[7] and returned_token == token, "M6 session cookie resolves active account")
users[7]["active"] = False
disabled, _ = auth_sessions.resolve_session(Handler("pos_session=" + token), sessions, users.get)
ok(disabled is None and token not in sessions, "M7 disabled account invalidates its session")

sample_sale = {
    "no": 42, "d": "2026-10-24", "tot": 40,
    "l": [{"n": "Tablet", "q": 2, "p": 20, "c": 10}],
}
state = {
    "p": [{"id": 1, "n": "Tablet", "p": 20, "c": 10}],
    "s": [sample_sale],
    "g": [{"k": "Cost changed"}, {"k": "Stock changed"}],
    "purchases": [{"id": "private"}], "suppliers": [{"id": "private"}],
}
staff_state = state_views.public_state(state, False, "2026-10-24", {})
manager_state = state_views.public_state(state, True, "2026-10-24", {})
ok("c" not in staff_state["p"][0] and "c" not in staff_state["s"][0]["l"][0]
   and len(staff_state["g"]) == 1 and "purchases" not in staff_state,
   "M8 staff cannot see product costs, sale costs or restricted histories")
ok(manager_state["p"][0]["c"] == 10 and "purchases" in manager_state,
   "M9 manager retains authorized cost and purchase access")
ok("c" not in state_views.current_sales_state(state["s"], False, "2026-10-24")["s"][0]["l"][0]
   and "c" not in state_views.cashier_state(state["p"], False, "2026-10-24")["p"][0],
   "M10 lightweight endpoints preserve staff cost filtering")

with tempfile.TemporaryDirectory(prefix="rospos-module-") as temp:
    archived = dict(sample_sale)
    archived["tot"] = 50
    archive_store.merge_day_archive(temp, "2026-10-24", [archived], [])
    receipts, unavailable = history.read_receipt_day("2026-10-24", temp, [sample_sale])
    ok(not unavailable and len(receipts) == 1 and receipts[0]["tot"] == 40
       and "c" not in receipts[0]["l"][0],
       "M11 live receipt takes precedence and archived cost is hidden")
    report = history.build_report_sales_history("2026-10-24", temp, [sample_sale], "2026-10-24")
    ok(report["days"][0]["total"] == 40 and report["days"][0]["profit"] == 20,
       "M12 historical report retains amounts and captured unit-cost profit")

conn = sqlite3.connect(":memory:")
conn.execute("""create table audit_events(
    id integer primary key, ts text, category text, action text,
    actor text, entity_type text, entity_id text, entity_name text,
    operation_id text, old_value text, new_value text, details text, status text)""")
conn.execute("""insert into audit_events
    values(1,'2026-10-24T11:00:00','inventory','Stock adjusted',
    'Owner','product','1','Tablet','bulk-1',null,null,'{}','success')""")
conn.execute("""insert into audit_events
    values(2,'2026-10-24T12:00:00','inventory','Cost changed',
    'Owner','product','1','Tablet','bulk-1',null,null,'{}','success')""")
grouped = audit_queries.query_audit_events(conn, {"category": ["inventory"]})
details = audit_queries.query_audit_events(
    conn, {"category": ["inventory"], "operation_id": ["bulk-1"]}
)
ok(grouped["total"] == 1 and grouped["items"][0]["event_count"] == 2,
   "M13 grouped inventory logs preserve operation counts")
ok(details["total"] == 2 and len(details["items"]) == 2,
   "M14 operation details remain paginated and linked")

try:
    audit_queries.query_audit_events(conn, {"category": ["products"]})
    invalid = False
except audit_queries.AuditQueryError:
    invalid = True
ok(invalid, "M15 audit query rejects unauthorized category names")
events = []
audit_events.prepare_sale_events(
    dict(sample_sale, v={"u": "Owner", "d": "2026-10-24", "t": "12:00 PM"},
         h=[{"u": "Owner", "d": "2026-10-24", "t": "11:30 AM"}]),
    events, lambda category, action, **kw: (category, action, kw),
)
ok([row[1] for row in events] == ["Sale completed", "Sale voided", "Sale amended"],
   "M16 legacy sale creates completed, voided and amended audit events")


with tempfile.TemporaryDirectory(prefix="rospos-storage-contract-") as folder:
    from poscore import storage

    database = storage.open_database(os.path.join(folder, "data", "pos.db"))
    storage.write_key(database, "settings", {"store": "Unit"})
    ok(storage.read_key(database, "settings") == {"store": "Unit"},
       "M17 SQLite key/value helpers retain JSON settings")
    committed = [("2026-10-24T10:00:00", "inventory", "Stock adjusted",
                  "Owner", "product", "1", "Tablet", "bulk-1", None, None,
                  "{}", "success", "module-event-1")]
    storage.persist_state(database, {"p": [{"id": 1}]}, committed, (7, "request-1", 123))
    ok(not committed and storage.read_key(database, "state")["p"][0]["id"] == 1
       and database.execute("select sale_no from sale_requests").fetchone()[0] == 123
       and database.execute("select count(*) from audit_events").fetchone()[0] == 1,
       "M18 state, audit events and payment idempotency key commit atomically")
    pending_failure = [("2026-10-24T10:01:00", "inventory", "Stock adjusted",
                        "Owner", "product", "1", "Tablet", "bulk-1", None, None,
                        "{}", "success", "module-event-2")]
    try:
        storage.persist_state(database, {"p": []}, pending_failure, (7, "request-1", 124))
        failed = False
    except sqlite3.IntegrityError:
        failed = True
    ok(failed and len(pending_failure) == 1
       and storage.read_key(database, "state")["p"][0]["id"] == 1
       and database.execute("select count(*) from audit_events").fetchone()[0] == 1,
       "M19 failed payment-key insertion rolls back state and retains queued events")
    database.close()

print("ALL PASSED" if not failures else "FAILED " + str(failures))
sys.exit(1 if failures else 0)
