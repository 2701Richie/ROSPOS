// core.js: helpers, shared state, server calls (api/load), tab switching, nav
const $=s=>document.querySelector(s),K='pos3b-v1';
const R=n=>Math.round(n*100)/100,M=n=>'₱'+R(n).toLocaleString('en-PH',{minimumFractionDigits:2,maximumFractionDigits:2});
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function ds(n){return new Date(Date.now()+n*864e5).toLocaleDateString('en-CA')}
let T=ds(0);
let S={p:[],s:[],g:[]},cart=[],edit=null;
let ME=null,tab='sell';
async function api(path,body){try{const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Requested-With':'pos'},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok){if(r.status===401&&ME){ME=null;showAuth(false)}return{error:j.error||'Something went wrong.'}}if(j.me)ME=j.me;if(j.state){S=j.state;T=S.today;if(typeof badge==='function')badge();if(typeof applyBrand==='function')applyBrand()}return j}catch(e){return{error:'Cannot reach the POS server. Check the Wi-Fi and the laptop.'}}}
async function load(){const r=await api('/api/state');if(r.error)say(r.error);return r}
function say(t){$('#msg').textContent=t}
function tags(p){let t='';if(p.e&&p.e<T)t+='<span class="tag b">Expired</span> ';else if(p.e&&p.e<=ds(90))t+='<span class="tag w">Exp. '+p.e+'</span> ';if(p.s<=p.m)t+='<span class="tag b">Low stock: '+p.s+'</span>';return t}
function show(t){if(!can(PERM[t]||'staff'))t='sell';tab=t;try{localStorage.setItem('pos-tab',t==='set'||t==='acc'?'sell':t)}catch(e){}['sell','live','rcp','prod','rdr','rep','acc','set'].forEach(k=>{$('#v-'+k).hidden=k!==t;document.querySelector('nav [data-t="'+k+'"]').classList.toggle('on',k===t)});if(t==='rep')drawRep();if(t==='prod')drawProd();if(t==='rcp')drawRcp();if(t==='rdr')drawRdr();if(t==='acc')drawAcc();if(t==='set')drawSet();if(t==='live')refreshLive()}
document.querySelector('nav').onclick=e=>{const b=e.target.closest('button');if(b)show(b.dataset.t)};
const LV={staff:1,manager:2,owner:3},PERM={sell:'staff',live:'manager',rcp:'staff',rdr:'staff',prod:'manager',rep:'manager',acc:'owner',set:'owner'};
let setupMode=false;
function can(r){return !!ME&&LV[ME.role]>=LV[r]}
function fail(r,el){el.textContent=r.error}
function showAuth(setup){setupMode=setup;$('#auth').hidden=false;$('#at').textContent=setup?'Set up the owner account':'Sign in';$('#afs').hidden=!setup;$('#ago').textContent=setup?'Create account':'Sign in';$('#apw').autocomplete=setup?'new-password':'current-password';['ac','an','au','apw'].forEach(i=>$('#'+i).value='');$('#am').textContent='';$('#'+(setup?'ac':'au')).focus()}
function applyRole(){$('#who').textContent=ME.name+' ('+ME.role+')';document.querySelectorAll('nav button').forEach(b=>b.hidden=!can(PERM[b.dataset.t]));$('#br').hidden=$('#bpl').hidden=!can('owner')}
function tabSaved(){try{const t=localStorage.getItem('pos-tab');return['sell','live','rcp','prod','rdr','rep'].includes(t)?t:'sell'}catch(e){return'sell'}}
async function enter(restore){$('#auth').hidden=true;await load();applyRole();drawGrid();drawLines();show(restore?tabSaved():'sell')}
async function boot(){try{const j=await(await fetch('/api/me')).json();if(j.setup)return showAuth(true);if(!j.me)return showAuth(false);ME=j.me;await enter(true)}catch(e){$('#am').textContent='Cannot reach the POS server.'}}
$('#ago').onclick=async()=>{const m=$('#am');m.textContent='';const r=await api(setupMode?'/api/setup':'/api/login',{code:$('#ac').value,name:$('#an').value,username:$('#au').value,password:$('#apw').value});if(r.error){m.textContent=r.error;$('#apw').value='';return}await enter()};
$('#apw').onkeydown=e=>{if(e.key==='Enter')$('#ago').click()};
$('#so').onclick=async()=>{await api('/api/logout',{});ME=null;cart=[];S={p:[],s:[],g:[]};drawGrid();drawLines();showAuth(false)};
$('#pwb').onclick=()=>{openPm('<h2>Change my password</h2><label>Current password<input id="po" type="password" autocomplete="current-password"></label><label style="margin-top:8px">New password (8 or more characters)<input id="pn" type="password" autocomplete="new-password"></label><div class="acts"><button class="pri" id="pok">Change password</button><button id="vno">Cancel</button></div><div id="vm" class="err" role="status"></div>');$('#pok').onclick=async()=>{const r=await api('/api/mypassword',{old:$('#po').value,new:$('#pn').value});if(r.error){$('#vm').textContent=r.error;return}$('#pm').hidden=true}};
