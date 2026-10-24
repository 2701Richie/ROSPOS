#!/usr/bin/env python3
"""Phase 5 CSS cascade snapshot, across devices/themes/sidebar modes.

Usage: python3 tests/css_snapshot.py --write /tmp/rospos-phase5-before.json
       python3 tests/css_snapshot.py --compare /tmp/rospos-phase5-before.json
Loads only local HTML and CSS; no live POS server or database.
"""
import argparse, json, os, subprocess, time, threading, socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import requests

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parser=argparse.ArgumentParser()
group=parser.add_mutually_exclusive_group(required=True)
group.add_argument('--write')
group.add_argument('--compare')
group.add_argument('--verify',action='store_true',help='Check expected responsive layout invariants')
parser.add_argument('--css',help='Override stylesheet for regression baseline')
options=parser.parse_args()
class StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=ROOT,**kwargs)
    def log_message(self,*args): pass
    def do_GET(self):
        if options.css and self.path.split('?')[0]=='/style.css':
            with open(options.css,'rb') as f:data=f.read()
            self.send_response(200)
            self.send_header('Content-Type','text/css')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else: super().do_GET()
server=ThreadingHTTPServer(('127.0.0.1',0),StaticHandler)
threading.Thread(target=server.serve_forever,daemon=True).start()
sock=socket.socket()
sock.bind(('127.0.0.1',0))
port=sock.getsockname()[1]
sock.close()
driver=subprocess.Popen(['chromedriver','--port='+str(port),'--allowed-origins=*'],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
uri='http://127.0.0.1:'+str(port)
session=None
def wd(method,path,body=None):
    response=requests.request(method,uri+path,json=body,timeout=18)
    response.raise_for_status()
    result=response.json()
    if result.get('value') and isinstance(result['value'],dict) and 'error' in result['value']:
        raise RuntimeError(str(result['value']))
    return result.get('value')
def evaluate(code):
    return wd('POST','/session/'+session+'/execute/sync',{'script':code,'args':[]})
try:
    for _ in range(50):
        try:
            if requests.get(uri+'/status',timeout=.3).ok: break
        except requests.RequestException: pass
        time.sleep(.1)
    info=wd('POST','/session',{'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{
        'args':['--headless=new','--no-sandbox','--disable-dev-shm-usage','--allow-file-access-from-files']}}}})
    session=info['sessionId']
    wd('POST','/session/'+session+'/url',{'url':'http://127.0.0.1:'+str(server.server_port)+'/index.html'})
    # Snapshot final layout, not the first frame of the sidebar width transition.
    evaluate('document.head.insertAdjacentHTML("beforeend", "<style id=css-test-freeze>*,*::before,*::after{transition:none!important;animation:none!important}</style>");return true')
    result={}
    selectors=['header','main','nav.pos-sidebar','.pos-sidebar .sidebar-head',
      '.pos-sidebar .sidebar-links','.pos-sidebar .sidebar-links button',
      '.pos-sidebar .sidebar-toggle','.pos-sidebar .sidebar-hide','.sidebar-restore',
      '.card','.stats','#grid','#v-sell','.sell-workspace','.sell-checkout',
      '.report-drawers','.report-drawer','.daily-sales-summary','.daily-sales-filter',
      '.receipt-kpis','.receipt-filters','.receipt-actions','.log-filters',
      '.log-cabinet-grid','.log-drawer','#rc','#md','.rcp']
    properties=['display','position','width','height','maxWidth','minWidth','padding',
      'margin','gridTemplateColumns','gridTemplateRows','gap','overflow','overflowX',
      'overflowY','flexDirection','flexWrap','justifyContent','alignItems','fontSize',
      'fontWeight','lineHeight','color','backgroundColor','borderRadius','borderColor',
      'boxShadow','visibility','top','left','bottom','right','transform','transitionDuration',
      'animationDuration','minHeight','maxHeight']
    for width,height in [(375,812),(600,900),(700,950),(701,950),(768,1024),(1024,768),(1440,900)]:
      wd('POST','/session/'+session+'/window/rect',{'width':width,'height':height})
      for theme in ['light','dark']:
       for mode in ['compact','expanded','hidden']:
        result[f'{width}/{theme}/{mode}']=evaluate(
          'document.documentElement.setAttribute("data-theme",'+json.dumps(theme)+');'
          'document.body.classList.add("pos-ready");'
          'document.querySelector("#auth").hidden=true;'
          'document.body.classList.remove("sidebar-expanded","sidebar-hidden");'
          'if('+json.dumps(mode)+'==="expanded")document.body.classList.add("sidebar-expanded");'
          'if('+json.dumps(mode)+'==="hidden")document.body.classList.add("sidebar-hidden");'
          'const sels='+json.dumps(selectors)+';const props='+json.dumps(properties)+';'
          'return Object.fromEntries(sels.map(s=>{const e=document.querySelector(s);'
          'if(!e)return [s,null];const c=getComputedStyle(e);'
          'return [s,Object.fromEntries(props.map(p=>[p,c[p]]))]}));')
    dest=options.write or options.compare
    if options.verify:
        assert evaluate('return [...document.styleSheets].some(s=>s.href && s.href.includes("/style.css") && s.cssRules.length>100)'), 'Stylesheet was not loaded'
        for (width,height) in [(375,812),(600,900),(700,950),(701,950),(768,1024),(1024,768),(1440,900)]:
            for theme in ('light','dark'):
                for mode in ('compact','expanded','hidden'):
                    styles=result[f'{width}/{theme}/{mode}']
                    sidebar=styles['nav.pos-sidebar']
                    if width<=700:
                        assert sidebar['position']=='sticky' or (mode=='hidden' and sidebar['display']=='none'), (width,theme,mode,sidebar)
                        if mode=='hidden':assert sidebar['display']=='none', (width,mode)
                    else:
                        assert sidebar['position']=='fixed', (width,mode,sidebar)
                        assert sidebar['width']==('214px' if mode=='expanded' else '64px'), (width,mode,sidebar['width'])
                        assert styles['.pos-sidebar .sidebar-head']['position']=='fixed'
        assert result['768/light/expanded']['.card']['backgroundColor']!=result['768/dark/expanded']['.card']['backgroundColor'], 'Themes must remain distinct'
        print('PASS CSS layout/theme invariants across '+str(len(result))+' scenarios')
    elif options.write:
        with open(dest,'w') as f: json.dump(result,f,sort_keys=True,indent=1)
        print('BASELINE '+dest+' scenarios='+str(len(result)))
    else:
        with open(dest) as f: original=json.load(f)
        problems=[]
        for key,entries in result.items():
            for selector,values in entries.items():
                if values!=original[key][selector]:
                    differing=[] if values is None or original[key][selector] is None else [
                        p for p,v in values.items() if v!=original[key][selector].get(p)]
                    problems.append(f'{key} {selector}: '+','.join(differing))
        print('CSS SNAPSHOT '+('PASS' if not problems else 'FAIL')+
              ' '+str(len(result))+' scenarios, '+str(len(problems))+' changed selector styles')
        for item in problems[:35]:print(item)
        if problems: raise SystemExit(1)
finally:
    if session:
        try:wd('DELETE','/session/'+session)
        except Exception:pass
    driver.terminate()
    try:driver.wait(timeout=3)
    except subprocess.TimeoutExpired:driver.kill()
    server.shutdown()
    server.server_close()
