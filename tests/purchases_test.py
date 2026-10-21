"""Purchases and supplier tests run against a disposable SQLite database."""
import os, sys, json, shutil, tempfile
SRC=os.path.abspath(sys.argv[1]) if len(sys.argv)>1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP=tempfile.mkdtemp(prefix='rospos-purchases-')
os.environ.update(POS_DB=TMP+'/pos.db',POS_BACKUP_DIR=TMP+'/backups',POS_ARCHIVE_DIR=TMP+'/archives',POS_PORT='8995',PYTHONDONTWRITEBYTECODE='1')
sys.dont_write_bytecode=True;sys.path.insert(0,SRC)
import server as srv
bad=0
def ok(c,m):
 global bad
 print(('ok   ' if c else 'FAIL ')+m);bad+=0 if c else 1
def actor(role='owner'):
 return {'id':1,'name':'Tester','username':'tester','role':role,'active':True,'salt':'ab'*8,'hash':srv.hash_pw('pw12345678','ab'*8)}
def fresh():
 srv.S={'p':[],'s':[],'g':[],'purchases':[],'suppliers':[]};srv.ACTOR=actor();srv.PENDING_AUDIT_EVENTS.clear()
def add_product(name='Paracetamol',stock=2,reorder=5):
 srv.r_product({'n':name,'p':10,'s':stock,'m':reorder,'c':4},'test')
 return srv.S['p'][0]
def add_supplier(name='Supplier A'):
 return srv.r_supplier({'name':name},'test')['supplier']
def future_expiry():
 from datetime import date, timedelta
 return (date.today()+timedelta(days=365)).isoformat()
def purchase(p,s,q=8,c=3.25,date=None,expiry=None):
 return srv.r_purchase({'action':'create','product_id':p['id'],'supplier_id':s['id'],'quantity':q,'unit_cost':c,'date':date or srv.now()[0],'expiry_date':expiry or future_expiry(),'notes':'invoice 123'},'test')
fresh();p=add_product();sup=add_supplier()
ok(len(srv.S['suppliers'])==1 and sup['name']=='Supplier A','supplier is stored with a stable ID and name')
before=json.dumps(srv.S,sort_keys=True)
try: srv.r_supplier({'name':' supplier a '},'test'); duplicate=False
except srv.Err as e: duplicate=e.code==409
ok(duplicate and len(srv.S['suppliers'])==1,'supplier names are unique case-insensitively')
r=purchase(p,sup)
ok(p['s']==10 and len(srv.S['purchases'])==1,'purchase creation increases product stock and records history')
row=srv.S['purchases'][0]
ok(row['product_id']==p['id'] and row['supplier_id']==sup['id'] and row['total']==26 and row['unit_cost']==3.25,'purchase keeps product/supplier IDs and calculated total')
ok(p['c']==4,'cheaper purchase preserves the higher existing product cost')
ok(row.get('expiry_date')==future_expiry(),'purchase records batch expiration date')
ok(r['reorder_removed'] is True and p['s']>p['m'],'suggested reorder quantity purchase removes product from stock-derived Reorder list')
old=json.dumps(srv.S,sort_keys=True)
try: srv.r_purchase({'action':'create','product_id':p['id'],'supplier_id':sup['id'],'quantity':0,'unit_cost':1,'date':srv.now()[0],'expiry_date':future_expiry()},'test'); bad_qty=False
except srv.Err as e: bad_qty=e.code==400
ok(bad_qty and json.dumps(srv.S,sort_keys=True)==old,'invalid purchase quantity is rejected without changing state')
sup2=add_supplier('Supplier B')
srv.r_purchase({'action':'edit','id':row['id'],'supplier_id':sup2['id'],'quantity':6,'unit_cost':4,'date':srv.now()[0],'expiry_date':future_expiry(),'notes':'edited'},'test')
ok(p['s']==8 and row['quantity']==6 and row['supplier_id']==sup2['id'] and row['total']==24,'editing purchase adjusts stock by quantity delta and updates supplier/cost')
ok(p['c']==4,'editing purchase to a cheaper cost does not reduce protected product cost')
# A higher purchase cost raises product cost; subsequent cheaper edits/deletions never lower it.
p3=add_product('Inflation test',stock=0,reorder=2); p3['c']=10
purchase(p3,sup,2,12)
ok(p3['c']==12,'more expensive purchase raises protected product cost')
row3=srv.S['purchases'][-1]
srv.r_purchase({'action':'edit','id':row3['id'],'supplier_id':sup['id'],'quantity':2,'unit_cost':11,'date':srv.now()[0],'expiry_date':future_expiry(),'notes':''},'test')
ok(p3['c']==12,'editing a purchase to a lower cost does not reduce protected product cost')
srv.r_purchase({'action':'delete','id':row3['id']},'test')
ok(p3['c']==12,'deleting a purchase does not lower protected product cost')
srv.r_purchase({'action':'delete','id':row['id']},'test')
ok(p['s']==2 and len([x for x in srv.S['purchases'] if x['product_id']==p['id']])==0,'deleting purchase reverses received stock when available')
purchase(p,sup,8,3)
p['s']=0
snapshot=json.dumps(srv.S,sort_keys=True)
try: srv.r_purchase({'action':'delete','id':srv.S['purchases'][0]['id']},'test'); unsafe=False
except srv.Err as e: unsafe=e.code==409
ok(unsafe and json.dumps(srv.S,sort_keys=True)==snapshot,'purchase deletion refuses to reverse stock that has already been consumed')
# Historical purchase records can legitimately have expired batches today; expiry
# must be after the purchase date, not necessarily after the current date.
from datetime import date, timedelta
p2=add_product('Historical batch',stock=0,reorder=2)
historical_date=(date.today()-timedelta(days=90)).isoformat()
historical_expiry=(date.today()-timedelta(days=10)).isoformat()
old_purchase=purchase(p2,sup,1,2.5,date=historical_date,expiry=historical_expiry)
ok(old_purchase and srv.S['purchases'][-1]['expiry_date']==historical_expiry,'historical purchase accepts an expiry date that was valid after its purchase date')
snapshot=json.dumps(srv.S,sort_keys=True)
try: purchase(p2,sup,1,2.5,date=historical_date,expiry=(date.today()-timedelta(days=100)).isoformat()); bad_expiry=False
except srv.Err as e: bad_expiry=e.code==400
ok(bad_expiry and json.dumps(srv.S,sort_keys=True)==snapshot,'expiry on or before the purchase date is rejected without changing state')
srv.ACTOR=actor('staff')
try: srv.r_purchase({'action':'create'},'test'); denied=False
except srv.Err as e: denied=e.code==403
ok(denied,'staff cannot create purchase records')
print('SUMMARY PASS=%d FAIL=%d'%(18-bad,bad))
srv.db.close();shutil.rmtree(TMP,ignore_errors=True);sys.exit(1 if bad else 0)
