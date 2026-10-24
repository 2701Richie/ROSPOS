#!/usr/bin/env python3
"""Headless Chromium smoke test; temporary database and isolated server."""
import os, sys, tempfile, subprocess, time, re, json, shutil, socket, requests
from datetime import date, timedelta
root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
temp=tempfile.mkdtemp(prefix='rospos-browser-')
def port():
 s=socket.socket(); s.bind(('127.0.0.1',0)); n=s.getsockname()[1]; s.close(); return n
port1,port2=port(),port()
env=dict(os.environ,POS_DB=temp+'/data/pos.db',POS_BACKUP_DIR=temp+'/backups',POS_ARCHIVE_DIR=temp+'/archives',POS_PORT=str(port1),PYTHONDONTWRITEBYTECODE='1')
log=open(temp+'/server.log','w+')
srv=subprocess.Popen([sys.executable,root+'/server.py'],env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT)
driver=subprocess.Popen(['chromedriver','--port='+str(port2),'--allowed-origins=*'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
base='http://127.0.0.1:'+str(port1)
wd='http://127.0.0.1:'+str(port2)
s=requests.Session()
def wait(test,timeout=12):
 for _ in range(timeout*10):
  try:
   v=test()
   if v:return v
  except Exception:pass
  time.sleep(.1)
 raise RuntimeError('timed out')
def w(method,path,data=None):
 r=requests.request(method,wd+path,json=data,timeout=15);r.raise_for_status();return r.json().get('value')
try:
 wait(lambda:s.get(base+'/',timeout=1).status_code==200)
 log.flush()
 setup=re.search(r'SETUP CODE: (\w+)',open(temp+'/server.log').read()).group(1)
 def post(path,obj):
  r=s.post(base+path,json=obj,headers={'X-Requested-With':'pos'},timeout=15)
  assert r.status_code==200,(path,r.status_code,r.text[:200])
  return r.json()
 post('/api/setup',{'code':setup,'username':'owner','name':'Owner','password':'password123'})
 post('/api/product',{'n':'Browser Test Tablet','p':10,'s':12,'m':2})
 archived_day=(date.today()-timedelta(days=20)).isoformat()
 os.makedirs(temp+'/archives',exist_ok=True)
 with open(temp+'/archives/sales-'+archived_day+'.json','w') as f:
  json.dump({'format':'ROSPOS-day-archive','version':1,'date':archived_day,'g':[],
             's':[{'no':500,'d':archived_day,'t':'01:30 PM','by':'Tester','tot':125,
                    'l':[{'id':1,'n':'Archived Tablet','q':1,'p':125,'c':50}]}]},f)
 opts={'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{'args':['--headless=new','--no-sandbox','--disable-dev-shm-usage','--window-size=1400,900']}}}}
 wait(lambda: requests.get(wd+'/status',timeout=1).status_code==200)
 created=w('POST','/session',opts); sid=created['sessionId'] if 'sessionId' in created else None
 if not sid: raise RuntimeError('No webdriver session: '+str(created))
 p='/session/'+sid
 def js(expr):return w('POST',p+'/execute/sync',{'script':'return '+expr,'args':[]})
 w('POST',p+'/url',{'url':base+'/'})
 wait(lambda:js('document.readyState')=='complete')
 wait(lambda:js('document.querySelector("#auth") !== null'))
 # Authenticate within the browser, not by injecting a fake JS state.
 js('(document.querySelector("#au").value="owner", document.querySelector("#apw").value="password123", document.querySelector("#ago").click(), true)')
 wait(lambda:js('document.querySelector("#auth").hidden === true'))
 print('PASS browser owner login and initial rendering')
 wait(lambda:js('document.body.innerText.includes("Browser Test Tablet")'))
 print('PASS browser sell catalog visible')
 wait(lambda:js('performance.getEntriesByType("resource").some(x=>x.name.includes("/api/sell-state"))'),timeout=9)
 print('PASS real Chromium periodic Sell poll uses /api/sell-state')
 js('(document.querySelector("nav [data-t=live]").click(),true)')
 wait(lambda:js('typeof tab !== "undefined" && tab === "live"'))
 wait(lambda:js('document.querySelector("#liveStatus").textContent.includes("Live")'))
 wait(lambda:js('performance.getEntriesByType("resource").some(x=>x.name.includes("/api/live-state"))'))
 print('PASS browser Live Sales uses /api/live-state')
 products=s.get(base+'/api/state').json()['state']['p']
 post('/api/sale',{'lines':[{'id':products[0]['id'],'q':2}],'cash':100})
 wait(lambda:js('document.querySelector("#liveCount").textContent.trim() === "1"'),timeout=10)
 print('PASS new sale appears in Live Sales through lightweight polling')
 js('(document.querySelector("nav [data-t=rcp]").click(),true)')
 wait(lambda:js('typeof tab !== "undefined" && tab === "rcp"'))
 wait(lambda:js('document.querySelector("#v-rcp").hidden === false'))
 wait(lambda:js('S.s.some(s=>s.l.some(l=>l.n==="Browser Test Tablet"))'))
 print('PASS browser Receipts keeps newly created sale')
 js('(document.querySelector("#receiptDate").value="'+archived_day+'",document.querySelector("#receiptDate").dispatchEvent(new Event("change",{bubbles:true})),true)')
 wait(lambda:js('document.querySelector("#rb").textContent.includes("#500") && document.querySelectorAll("#rb button[data-v]").length===1'),timeout=12)
 assert js('document.querySelectorAll("#rb button[data-c],#rb button[data-x]").length===0')
 print('PASS browser archived receipt is visible and reprintable but cannot be changed or voided')
 js('(document.querySelector("#rb button[data-v]").click(),true)')
 wait(lambda:js('!document.querySelector("#md").hidden && document.querySelector("#rc").textContent.includes("Archived Tablet")'))
 assert js('document.querySelector("#rc").textContent.includes("125") && !!document.querySelector("#pr")')
 print('PASS archived receipt opens a complete printable 58 mm slip in Chromium')
 js('(document.querySelector("#nw").click(),true)')
 # Test responsive layouts at common phone/tablet viewport widths.
 for width,height in [(375,812),(768,1024),(1024,768)]:
  w('POST',p+'/window/rect',{'width':width,'height':height})
  wait(lambda:js('window.innerWidth')==width)
  js('(document.querySelector("nav [data-t=rcp]").click(),true)')
  wait(lambda:js('tab==="rcp" && !document.querySelector("#v-rcp").hidden'))
  assert js('!!document.querySelector("#receiptDate") && !!document.querySelector("#rb")')
  js('(document.querySelector("nav [data-t=rep]").click(),true)')
  wait(lambda:js('tab==="rep" && !document.querySelector("#v-rep").hidden'))
  assert js('!!document.querySelector("[data-report-drawer=daily]")')
  js('(document.querySelector("nav [data-t=logs]").click(),true)')
  wait(lambda:js('tab==="logs" && !document.querySelector("#v-logs").hidden'))
  assert js('!!document.querySelector("[data-log-drawer=ilog]")')
  print('PASS responsive Reports, Receipts and Logs at '+str(width)+'px')
 js('(document.querySelector("#receiptClear").click(),true)')
 wait(lambda:js('document.querySelector("#receiptDate").value===""'))
 js('(document.querySelector("nav [data-t=rep]").click(),true)')
 wait(lambda:js('tab === "rep" && !document.querySelector("#v-rep").hidden'))
 js('(document.querySelector("[data-report-drawer=daily]").click(),true)')
 wait(lambda:js('!document.querySelector("[data-report-page=daily]").hidden'))
 wait(lambda:js('document.querySelector("#reportSalesSummary").textContent.includes("Sales total")'))
 js('(document.querySelector("#reportSalesDate").value="'+archived_day+'",document.querySelector("#reportSalesDate").dispatchEvent(new Event("change",{bubbles:true})),true)')
 wait(lambda:js('document.querySelector("#reportSalesDayRows").textContent.includes("#500")'))
 wait(lambda:js('document.querySelector("#reportDailyHistoryRows").textContent.includes("'+archived_day+'")'))
 print('PASS archived receipt and daily summary load in Chromium without modifying live data')
 js('(document.querySelector("nav [data-t=logs]").click(),true)')
 wait(lambda:js('tab === "logs" && !document.querySelector("#v-logs").hidden'))
 js('(document.querySelector("[data-log-drawer=ilog]").click(),true)')
 wait(lambda:js('!document.querySelector("#v-ilog").hidden'))
 wait(lambda:js('document.querySelector("#il-count").textContent.includes("inventory")'))
 print('PASS browser Inventory Logs drawer loads')
 js('(document.querySelector("nav [data-t=sell]").click(),true)')
 wait(lambda:js('typeof tab !== "undefined" && tab === "sell"'))
 js('document.querySelector("#sidebarToggle") != null')
 print('PASS browser Sell re-entry')
 # Model an older server that returns 404 for the newer optimized poll routes.
 # The real /api/state remains available and requires the authenticated cookie.
 js('(window.__posNativeFetch=window.fetch.bind(window),window.__compatRoutes=[],'
    'window.fetch=(url,options)=>{const path=typeof url==="string"?url:url.url;'
    'window.__compatRoutes.push(path);'
    'return path==="/api/sell-state"||path==="/api/live-state"?'
    'Promise.resolve(new Response(JSON.stringify({error:"Not found."}),'
    '{status:404,headers:{"Content-Type":"application/json"}})):'
    'window.__posNativeFetch(url,options)},resetSyncSession(),true)')
 js('(window.__compatSellPromise=refreshSell(),true)')
 wait(lambda:js('legacySellSync && window.__compatRoutes.includes("/api/state")'))
 assert js('S.p.some(p=>p.n==="Browser Test Tablet")')
 print('PASS browser Sell refresh falls back from legacy 404 to authorized full state')
 js('(document.querySelector("nav [data-t=live]").click(),true)')
 wait(lambda:js('legacyLiveSync && document.querySelector("#liveStatus").textContent.includes("Live")'))
 assert js('!document.querySelector(".live-dot").classList.contains("offline")')
 print('PASS browser Live Sales remains connected with older backend lacking /api/live-state')
 post('/api/sale',{'lines':[{'id':products[0]['id'],'q':1}],'cash':100})
 wait(lambda:js('document.querySelector("#liveCount").textContent.trim()==="2"'),timeout=12)
 assert js('window.__compatRoutes.filter(x=>x==="/api/live-state").length===1')
 print('PASS browser legacy Live Sales receives new sales and stops repeated 404 probes')
 print('NETWORK',js('JSON.stringify(performance.getEntriesByType("resource").filter(x=>x.name.includes("/api/")).map(x=>x.name.split("/").pop()))'))
finally:
 try:
  if 'sid' in locals() and sid:w('DELETE','/session/'+sid)
 except Exception:pass
 driver.terminate();srv.terminate()
 try:driver.wait(timeout=3)
 except Exception:driver.kill()
 try:srv.wait(timeout=3)
 except Exception:srv.kill()
 log.close()
 shutil.rmtree(temp,ignore_errors=True)
