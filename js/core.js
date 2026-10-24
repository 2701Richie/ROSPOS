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
let catalogRevision = 0, salesRevision = 0;
let fullLoadPending = null;
// Older running servers may not have purpose-specific polling endpoints yet.
// Fall back once to the authorized full-state API until the page reloads.
let legacySellSync = false, legacyLiveSync = false;
let sessionRevision = 0;
function resetSyncSession() {
  sessionRevision++;
  stateETag = '';
  sellETag = '';
  liveETag = '';
  fullLoadPending = null;
  legacySellSync = false;
  legacyLiveSync = false;
}
async function fetchFullState() {
  const requestedCatalogRevision = catalogRevision;
  const requestedSalesRevision = salesRevision;
  const requestedSession = sessionRevision;
  const headers = {'X-Requested-With': 'pos'};
  if (stateETag) headers['If-None-Match'] = stateETag;
  try {
    const response = await fetch('/api/state', {headers});
    if (requestedSession !== sessionRevision) return {stale: true};
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
    if (requestedSession !== sessionRevision) return {stale: true};
    stateETag = response.headers.get('ETag') || '';
    if (result.me) ME = result.me;
    if (result.state) {
      // A slower full response must not undo a newer lightweight poll.
      if (catalogRevision !== requestedCatalogRevision) result.state.p = S.p;
      if (salesRevision !== requestedSalesRevision) result.state.s = S.s;
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
// Coalesce simultaneous full refreshes from rapid navigation into one request.
function load() {
  if (fullLoadPending) return fullLoadPending;
  const pending = fetchFullState();
  fullLoadPending = pending;
  pending.finally(() => { if (fullLoadPending === pending) fullLoadPending = null; });
  return pending;
}
// Sell polling updates the catalog only. Preserve receipts/reports and history
// already loaded for other tabs; a full load is still used when entering them.
let sellETag = '';
async function loadSellState() {
  if (legacySellSync) return load();
  const requestedSession = sessionRevision;
  const headers = {'X-Requested-With': 'pos'};
  if (sellETag) headers['If-None-Match'] = sellETag;
  try {
    const response = await fetch('/api/sell-state', {headers});
    if (requestedSession !== sessionRevision) return {stale: true};
    if (response.status === 404) {
      // Deployment compatibility: old server process, newer frontend assets.
      legacySellSync = true;
      sellETag = '';
      return load();
    }
    if (response.status === 304) return {notModified: true};
    if (!response.ok) {
      sellETag = '';
      if (response.status === 401 && ME) {
        ME = null;
        showAuth(false);
      }
      const result = await response.json();
      return {error: result.error || 'Cannot refresh products.'};
    }
    const result = await response.json();
    if (requestedSession !== sessionRevision) return {stale: true};
    sellETag = response.headers.get('ETag') || '';
    if (result.me) ME = result.me;
    if (result.state) {
      S.p = result.state.p;
      catalogRevision++;
      T = result.state.today;
      S.today = T;
      if (typeof badge === 'function') badge();
    }
    return result;
  } catch (error) {
    return {error: 'Cannot refresh products. Check the connection.'};
  }
}

// Today's live feed is independent of the catalog and retained receipt history.
let liveETag = '';
async function loadLiveState() {
  if (legacyLiveSync) return load();
  const requestedSession = sessionRevision;
  const headers = {'X-Requested-With': 'pos'};
  if (liveETag) headers['If-None-Match'] = liveETag;
  try {
    const response = await fetch('/api/live-state', {headers});
    if (requestedSession !== sessionRevision) return {stale: true};
    if (response.status === 404) {
      // Keep Live Sales operational while the backend runs an older release.
      legacyLiveSync = true;
      liveETag = '';
      return load();
    }
    if (response.status === 304) return {notModified: true};
    if (!response.ok) {
      liveETag = '';
      if (response.status === 401 && ME) { ME = null; showAuth(false); }
      const result = await response.json();
      return {error: result.error || 'Cannot refresh live sales.'};
    }
    const result = await response.json();
    if (requestedSession !== sessionRevision) return {stale: true};
    liveETag = response.headers.get('ETag') || '';
    if (result.me) ME = result.me;
    if (result.state) {
      const day = result.state.today;
      // Merge only today's transactions; other screens may still need earlier days.
      S.s = (S.s || []).filter(s => s.d !== day).concat(result.state.s);
      salesRevision++;
      S.today = T = day;
    }
    return result;
  } catch (error) {
    return {error: 'Cannot refresh live sales. Check the connection.'};
  }
}

function say(t){$('#msg').textContent=t}
function tags(p){let t='';if(p.e&&p.e<T)t+='<span class="tag b">Expired</span> ';else if(p.e&&p.e<=ds(90))t+='<span class="tag w">Exp. '+esc(p.e)+'</span> ';if(p.s<=p.m)t+='<span class="tag b">Low stock: '+p.s+'</span>';return t}
// Keep navigation and per-tab rendering separate so new pages are easy to add.
const TAB_IDS = ['sell', 'live', 'rcp', 'prod', 'pur', 'rdr', 'rep', 'logs', 'acc', 'set'];
const PRIVATE_TABS = ['set', 'acc', 'logs'];

function show(t, renderNow = true) {
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
    rcp: () => $('#receiptDate').value ? refreshReceiptDate() : drawRcp(),
    rdr: () => drawRdr(),
    acc: () => { if (can('owner')) drawAcc(); },
    set: () => { if (can('owner')) drawSet(); },
    live: () => refreshLive(),
  };
  if (renderNow && render[t]) render[t]();
}

// Don't display a stale cached screen while the authorized full snapshot loads.
// A navigation generation prevents an earlier click from revealing a later tab.
let navigationGeneration = 0;
document.querySelector('nav').onclick = async event => {
  const button = event.target.closest('button[data-t]');
  if (!button || !event.currentTarget.contains(button)) return;
  const requested = button.dataset.t;
  const generation = ++navigationGeneration;
  if (!can(PERM[requested] || 'staff') || requested === 'sell' || requested === 'live') {
    show(requested);
    return;
  }
  show(requested, false);
  const view = $('#v-' + requested);
  view.hidden = true;
  const response = await load();
  if (generation !== navigationGeneration || tab !== requested || !ME || response.stale) return;
  view.hidden = false;
  show(requested);
  if (response.error) say(response.error);
};
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
$('#ago').onclick=async()=>{const m=$('#am');m.textContent='';const r=await api(setupMode?'/api/setup':'/api/login',{code:$('#ac').value,name:$('#an').value,username:$('#au').value,password:$('#apw').value});if(r.error){m.textContent=r.error;$('#apw').value='';return}resetSyncSession();await enter()};
$('#apw').onkeydown=e=>{if(e.key==='Enter')$('#ago').click()};
$('#so').onclick=async()=>{resetSyncSession();ME=null;cart=[];S={p:[],s:[],g:[]};showAuth(false);await api('/api/logout',{});drawGrid();drawLines();};
$('#pwb').onclick=()=>{openPm('<h2>Change my password</h2><label>Current password<input id="po" type="password" autocomplete="current-password"></label><label style="margin-top:8px">New password (8 or more characters)<input id="pn" type="password" autocomplete="new-password"></label><div class="acts"><button class="pri" id="pok">Change password</button><button id="vno">Cancel</button></div><div id="vm" class="err" role="status"></div>');$('#pok').onclick=async()=>{const r=await api('/api/mypassword',{old:$('#po').value,new:$('#pn').value});if(r.error){$('#vm').textContent=r.error;return}$('#pm').hidden=true}};
