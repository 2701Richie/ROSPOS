"""Log Center tests against a throw-away SQLite database; never touches live POS data."""
import os, sys, json, shutil, tempfile, time, io
SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="rospos-logtest-")
os.environ.update(POS_DB=TMP+"/pos.db", POS_BACKUP_DIR=TMP+"/backups", POS_ARCHIVE_DIR=TMP+"/archives", POS_PORT="8995", PYTHONDONTWRITEBYTECODE="1")
sys.dont_write_bytecode = True
sys.path.insert(0, SRC)
import server as srv
bad = 0
def ok(condition, message):
    global bad
    print(("ok   " if condition else "FAIL ")+message)
    bad += 0 if condition else 1

def actor(role="manager", uid=2):
    return {"id":uid,"name":"Test Manager" if role=="manager" else "Test Staff","username":"testuser","role":role,"active":True}

srv.S={"p":[],"s":[],"g":[]}
srv.PENDING_AUDIT_EVENTS.clear()
srv.ACTOR=actor()
srv.r_product({"n":"Log Product","p":12.5,"c":4.25,"s":10,"m":3,"e":""},"test")
p=srv.S["p"][0]
ok(any(x[1]=="inventory" and x[2]=="Product created" for x in srv.db.execute("select id,category,action from audit_events")),"L1 product creation writes a structured inventory event")
old=p["c"]
srv.r_product({"id":p["id"],"n":"Renamed Product","p":13,"c":5.25,"s":10,"m":5,"e":"2027-01-01"},"test")
events=srv.db.execute("select action,old_value,new_value from audit_events where category='inventory'").fetchall()
ok(any(x[0]=="Cost changed" and json.loads(x[1])==old and json.loads(x[2])==5.25 for x in events),"L2 cost changes retain exact old and new values")
ok(any(x[0]=="Product name changed" for x in events) and any(x[0]=="Reorder level changed" for x in events) and any(x[0]=="Expiry date changed" for x in events),"L3 product field edits are audited, not only prices")
# Cost-change details must not leak to staff via the legacy state payload.
srv.S["g"].append({"d":"2026-10-21","t":"09:00 AM","n":"Log Product","k":"Cost changed","a":old,"z":5.25,"u":"Test Manager","i":p["id"],"w":"test"})
ok(all("cost" not in x.get("k","").lower() for x in srv.pub(actor("staff",3))["g"]),"L4 staff state payload hides cost-change audit rows")
# CSV operation is grouped, and a failed preview keeps row-level diagnostics.
plan=srv.r_import({"mode":"products","apply":True,"why":"test import","rows":[{"name":"Imported Item","price":"7","quantity":"2","reorder":"1","cost":"2"}]},"test")["plan"]
op=srv.db.execute("select operation_id from audit_events where action='CSV import completed' order by id desc limit 1").fetchone()
ok(plan["applied"] and op and srv.db.execute("select count(*) from audit_events where operation_id=?",op).fetchone()[0]>=2,"L5 CSV summary groups individual product changes under one operation ID")
srv.r_import({"mode":"products","apply":True,"why":"test failed import","rows":[{"name":"Bad Item","price":"not-a-price","quantity":"1"}]},"test")
failed=srv.db.execute("select details,status from audit_events where action='CSV import validation failed' order by id desc limit 1").fetchone()
ok(failed and failed[1]=="failed" and json.loads(failed[0]).get("errors"),"L6 failed CSV validation stores row-level error details")
# A sale and its stock movement share an operation reference.
p=srv.S["p"][0]
sale=srv.r_sale({"lines":[{"id":p["id"],"q":1}]},"test")["sale"]
opid="sale-%s"%sale["no"]
ok(srv.db.execute("select count(*) from audit_events where operation_id=? and category='inventory'",(opid,)).fetchone()[0]==1 and srv.db.execute("select count(*) from audit_events where operation_id=? and category='sales'",(opid,)).fetchone()[0]==1,"L7 sale and its inventory deduction share a linkable operation ID")
# Fake HTTP handler verifies the actual API gate and grouping/pagination without starting a server.
class Headers:
    def get(self,k,default=None): return {"Cookie":"pos_session=logtest"}.get(k,default)
class FakeHandler(srv.H):
    def __init__(self,path): self.path=path;self.headers=Headers();self.client_address=("127.0.0.1",1);self.response=None
    def send(self,code,obj=None,**kwargs): self.response=(code,obj);return self.response
srv.U=[actor("manager",2),actor("staff",3)]
srv.SESSIONS["logtest"]={"id":2,"exp":time.time()+3600}
h=FakeHandler("/api/logs?category=inventory&limit=10");h.do_GET()
ok(h.response[0]==200 and h.response[1]["total"]>=1,"L8 authorized manager can query paginated inventory logs")
items=h.response[1]["items"]
ok(any(x.get("group_id") for x in items),"L9 bulk/import operations are returned as expandable groups")
h=FakeHandler("/api/logs?category=inventory&q=Renamed");h.do_GET()
ok(h.response[0]==200 and h.response[1]["total"]>=1,"L10 text search filters inventory history safely")
srv.SESSIONS["logtest"]={"id":3,"exp":time.time()+3600}
h=FakeHandler("/api/logs?category=inventory");h.do_GET()
ok(h.response[0]==403,"L11 staff cannot access the log API")
# Historical retention: no age-based delete path is added; events remain in SQLite after live state changes.
count=srv.db.execute("select count(*) from audit_events").fetchone()[0]
srv.S["g"]=[];srv.save()
ok(srv.db.execute("select count(*) from audit_events").fetchone()[0]==count,"L12 clearing hot legacy history does not delete retained audit events")
legacy={"d":"2026-10-20","t":"09:30 AM","n":"Old Product","k":"Received +4","a":1,"z":5,"u":"Old User","i":77,"w":"legacy test","eid":"migration-test-id"}
srv.S["g"].append(legacy)
srv.migrate_legacy_logs();once=srv.db.execute("select count(*) from audit_events where source_key='legacy-g-id-migration-test-id'").fetchone()[0]
srv.migrate_legacy_logs();twice=srv.db.execute("select count(*) from audit_events where source_key='legacy-g-id-migration-test-id'").fetchone()[0]
ok(once==1 and twice==1,"L13 legacy audit migration is idempotent")
shutil.rmtree(TMP,ignore_errors=True)
print("FAILED %d"%bad if bad else "ALL PASSED")
sys.exit(1 if bad else 0)
