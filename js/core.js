// core.js: helpers, shared state, server calls (api/load), tab switching, nav
const $=s=>document.querySelector(s),K='pos3b-v1';
const R=n=>Math.round(n*100)/100,M=n=>'₱'+R(n).toLocaleString('en-PH',{minimumFractionDigits:2,maximumFractionDigits:2});
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function ds(n){return new Date(Date.now()+n*864e5).toLocaleDateString('en-CA')}
let T=ds(0);
let S={p:[],s:[],g:[]},cart=[],edit=null;
let ME=null,tab='sell';
async function api(path,body){try{const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Requested-With':'pos'},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok){if(r.status===401&&ME){ME=null;showAuth(false)}return{error:j.error||'Something went wrong.'}}if(j.me)ME=j.me;if(j.state){S=j.state;T=S.today;if(typeof badge==='function')badge();if(typeof applyBrand==='function')applyBrand()}return j}catch(e){return{error:'Cannot reach the POS server. Check the Wi-Fi and the laptop.'}}}
// Conditional polling avoids downloading unchanged state; responses remain role-scoped.
let stateETag = '';
async function load() {
  const headers = {'X-Requested-With': 'pos'};
  if (stateETag) headers['If-None-Match'] = stateETag;
  try {
    const response = await fetch('/api/state', {headers});
    if (response.status === 304) return {notModified: true};
    if (!response.ok) {
      stateETag = '';
      if (response.status === 401 && ME) {
        ME = null;
        showAuth(false);
      }
      const result = await response.json();
      const error = result.error || 'Something went wrong.';
      say(error);
      return {error};
    }
    const result = await response.json();
    stateETag = response.headers.get('ETag') || '';
    if (result.me) ME = result.me;
    if (result.state) {
      S = result.state;
      T = S.today;
      if (typeof badge === 'function') badge();
      if (typeof applyBrand === 'function') applyBrand();
    }
    return result;
  } catch (error) {
    const message = 'Cannot reach the POS server. Check the Wi-Fi and the laptop.';
    say(message);
    return {error: message};
  }
}
function say(t){$('#msg').textContent=t}
function tags(p){let t='';if(p.e&&p.e<T)t+='<span class="tag b">Expired</span> ';else if(p.e&&p.e<=ds(90))t+='<span class="tag w">Exp. '+esc(p.e)+'</span> ';if(p.s<=p.m)t+='<span class="tag b">Low stock: '+p.s+'</span>';return t}
// Keep navigation and per-tab rendering separate so new pages are easy to add.
const TAB_IDS = ['sell', 'live', 'rcp', 'prod', 'pur', 'rdr', 'rep', 'logs', 'acc', 'set'];
const PRIVATE_TABS = ['set', 'acc', 'logs'];

function show(t) {
  if (!can(PERM[t] || 'staff')) t = 'sell';
  tab = t;

  try {
    localStorage.setItem('pos-tab', PRIVATE_TABS.includes(t) ? 'sell' : t);
  } catch (e) {
    // Storage may be disabled in private browsing.
  }

  for (const key of TAB_IDS) {
    $('#v-' + key).hidden = key !== t;
    const button = document.querySelector('nav [data-t="' + key + '"]');
    if (button) button.classList.toggle('on', key === t);
  }

  if (t === 'logs') {
    document.querySelectorAll('#v-logs > .log-page').forEach(page => {
      page.hidden = true;
    });
    $('#log-cabinet-home').hidden = false;
  }

  if (t === 'rep') {
    document.querySelectorAll('#v-rep [data-report-page]').forEach(page => {
      page.hidden = true;
    });
    $('#reportCabinet').hidden = false;
  }

  const render = {
    rep: () => drawRep(),
    prod: () => drawProd(),
    pur: () => drawPurchases(),
    rcp: () => drawRcp(),
    rdr: () => drawRdr(),
    acc: () => { if (can('owner')) drawAcc(); },
    set: () => { if (can('owner')) drawSet(); },
    live: () => refreshLive(),
  };
  if (render[t]) render[t]();
}

document.querySelector('nav').onclick=e=>{const b=e.target.closest('button[data-t]');if(b&&e.currentTarget.contains(b))show(b.dataset.t)};
// Three navigation modes: hidden, compact, expanded. Remember this device's choice.
const sidebarToggle=document.querySelector('#sidebarToggle');
const sidebarHide=document.querySelector('#sidebarHide');
const sidebarRestore=document.querySelector('#sidebarRestore');
function setSidebarMode(mode){
 if(!['hidden','compact','expanded'].includes(mode))mode='compact';
 document.body.classList.toggle('sidebar-expanded',mode==='expanded');
 document.body.classList.toggle('sidebar-hidden',mode==='hidden');
 sidebarToggle.setAttribute('aria-expanded',String(mode==='expanded'));
 sidebarToggle.setAttribute('aria-label',mode==='expanded'?'Compact navigation':'Expand navigation');
 sidebarToggle.title=mode==='expanded'?'Compact navigation':'Expand navigation';
 sidebarToggle.textContent=mode==='expanded'?'‹':'☰';
 sidebarRestore.hidden=mode!=='hidden';
 try{localStorage.setItem('pos-sidebar-mode',mode)}catch(e){}
}
let savedSidebar='compact';
try{savedSidebar=localStorage.getItem('pos-sidebar-mode')||'compact'}catch(e){}
setSidebarMode(savedSidebar);
sidebarToggle.onclick=()=>setSidebarMode(document.body.classList.contains('sidebar-expanded')?'compact':'expanded');
sidebarHide.onclick=()=>setSidebarMode('hidden');
sidebarRestore.onclick=()=>setSidebarMode('compact');

const LV={staff:1,manager:2,owner:3},PERM={sell:'staff',live:'manager',rcp:'staff',pur:'manager',rdr:'staff',prod:'manager',rep:'manager',logs:'manager',acc:'staff',set:'staff'};
let setupMode=false;
function can(r){return !!ME&&LV[ME.role]>=LV[r]}
function fail(r,el){el.textContent=r.error}
function showAuth(setup){document.body.classList.remove('pos-ready');setupMode=setup;$('#auth').hidden=false;$('#at').textContent=setup?'Set up the owner account':'Sign in';$('#afs').hidden=!setup;$('#ago').textContent=setup?'Create account':'Sign in';$('#apw').autocomplete=setup?'new-password':'current-password';['ac','an','au','apw'].forEach(i=>$('#'+i).value='');$('#am').textContent='';$('#'+(setup?'ac':'au')).focus()}
function applyRole(){$('#who').textContent=ME.name+' ('+ME.role+')';document.querySelectorAll('.pos-sidebar [data-t]').forEach(b=>b.hidden=!can(PERM[b.dataset.t]));$('#br').hidden=$('#bpl').hidden=!can('owner');$('#account-admin').hidden=!can('owner');$('#settings-admin').hidden=!can('owner');document.querySelectorAll('.pos-sidebar .sidebar-divider').forEach(d=>{
 const visible=x=>x.matches('[data-t]')&&!x.hidden;
 let prev=d.previousElementSibling,next=d.nextElementSibling;
 let before=false,after=false;
 while(prev&&!prev.classList.contains('sidebar-divider')){if(visible(prev))before=true;prev=prev.previousElementSibling}
 while(next&&!next.classList.contains('sidebar-divider')){if(visible(next))after=true;next=next.nextElementSibling}
 d.hidden=!(before&&after);
});document.body.classList.add('pos-ready')}
function tabSaved(){try{const t=localStorage.getItem('pos-tab');return['sell','live','rcp','prod','pur','rdr','rep'].includes(t)?t:'sell'}catch(e){return'sell'}}
async function enter(restore){await load();applyRole();drawGrid();drawLines();show(restore?tabSaved():'sell');$('#auth').hidden=true}
async function boot(){try{const j=await(await fetch('/api/me')).json();if(j.setup)return showAuth(true);if(!j.me)return showAuth(false);ME=j.me;await enter(true)}catch(e){showAuth(false);$('#am').textContent='Cannot reach the POS server.'}}
$('#ago').onclick=async()=>{const m=$('#am');m.textContent='';const r=await api(setupMode?'/api/setup':'/api/login',{code:$('#ac').value,name:$('#an').value,username:$('#au').value,password:$('#apw').value});if(r.error){m.textContent=r.error;$('#apw').value='';return}stateETag='';await enter()};
$('#apw').onkeydown=e=>{if(e.key==='Enter')$('#ago').click()};
$('#so').onclick=async()=>{await api('/api/logout',{});stateETag='';ME=null;cart=[];S={p:[],s:[],g:[]};drawGrid();drawLines();showAuth(false)};
$('#pwb').onclick=()=>{openPm('<h2>Change my password</h2><label>Current password<input id="po" type="password" autocomplete="current-password"></label><label style="margin-top:8px">New password (8 or more characters)<input id="pn" type="password" autocomplete="new-password"></label><div class="acts"><button class="pri" id="pok">Change password</button><button id="vno">Cancel</button></div><div id="vm" class="err" role="status"></div>');$('#pok').onclick=async()=>{const r=await api('/api/mypassword',{old:$('#po').value,new:$('#pn').value});if(r.error){$('#vm').textContent=r.error;return}$('#pm').hidden=true}};
