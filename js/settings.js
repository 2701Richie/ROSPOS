// settings.js: Settings tab (owner only): store name, sign-in length, backup days kept
function cfg(){return S.cfg||{store:'',session_hours:12,backup_days:30,rc_addr:'',rc_phone:'',rc_tag:'',rc_foot:''}}
function storeName(){return String(cfg().store||'').trim()}
function applyBrand(){const n=storeName(),sm=document.querySelector('.brand small');if(sm)sm.textContent=n||'PHARMACY POS';document.title=n?n+' — ROSPOS':'ROSPOS — Pharmacy POS'}
function drawSet(){const c=cfg(),m=$('#sm');$('#sn').value=c.store||'';$('#rcad').value=c.rc_addr||'';$('#rcph').value=c.rc_phone||'';$('#rctg').value=c.rc_tag||'';$('#rcft').value=c.rc_foot||'';$('#sh').value=c.session_hours;$('#sd').value=c.backup_days;$('#sp').value='';m.textContent='';m.className='err';drawRcpv()}
function rcForm(){return{store:$('#sn').value,rc_addr:$('#rcad').value,rc_phone:$('#rcph').value,rc_tag:$('#rctg').value,rc_foot:$('#rcft').value}}
function drawRcpv(){$('#rcpv').innerHTML=rcptHtml(rcptBlocks({no:1042,d:T,t:'10:42 AM',by:'Maria',l:[{n:'Paracetamol 500mg',q:2,p:5.5},{n:'Vitamin C 500mg',q:1,p:8},{n:'Alcohol 70% 500ml',q:1,p:85}],tot:104,cash:200},rcForm()))}
['sn','rcad','rcph','rctg','rcft'].forEach(i=>$('#'+i).oninput=drawRcpv);
$('#rctest').onclick=()=>rcptPopup(rcptTestBlocks(rcForm()));
$('#sr').onclick=drawSet;
$('#ss').onclick=async()=>{const m=$('#sm');m.className='err settings-message';m.textContent='';const hours=Number($('#sh').value),days=Number($('#sd').value);if(!Number.isFinite(hours)||hours<1||hours>72){m.textContent='Sign-in duration must be between 1 and 72 hours.';$('#sh').focus();return}if(!Number.isInteger(days)||days<7||days>365){m.textContent='Backup retention must be a whole number from 7 to 365 days.';$('#sd').focus();return}if(!$('#sp').value){m.textContent='Enter your current password to confirm these changes.';$('#sp').focus();return}const r=await api('/api/settings',{store:$('#sn').value,rc_addr:$('#rcad').value,rc_phone:$('#rcph').value,rc_tag:$('#rctg').value,rc_foot:$('#rcft').value,session_hours:$('#sh').value,backup_days:$('#sd').value,password:$('#sp').value});$('#sp').value='';if(r.error){m.textContent=r.error;return}applyBrand();drawSet();m.className='mu settings-message';m.textContent=r.msg||'Settings saved.'};
$('#sp').onkeydown=e=>{if(e.key==='Enter')$('#ss').click()};
// Theme button (every role, this device only): Automatic -> Light -> Dark. Saved in the browser, applied early by a script in index.html.
const THEMES=['auto','light','dark'],TH_ICON={auto:'◐',light:'☀',dark:'☾'},TH_NAME={auto:'Automatic',light:'Light',dark:'Dark'};
function themeGet(){try{const t=localStorage.getItem('pos-theme');return t==='light'||t==='dark'?t:'auto'}catch(e){return 'auto'}}
function themeApply(t){const r=document.documentElement,b=$('#tb');if(t==='auto')delete r.dataset.theme;else r.dataset.theme=t;b.textContent=TH_ICON[t];b.title='Theme: '+TH_NAME[t]+' (tap to change)';b.setAttribute('aria-label','Theme: '+TH_NAME[t]+'. Tap to change.')}
$('#tb').onclick=()=>{const n=THEMES[(THEMES.indexOf(themeGet())+1)%THEMES.length];try{if(n==='auto')localStorage.removeItem('pos-theme');else localStorage.setItem('pos-theme',n)}catch(e){}themeApply(n)};
themeApply(themeGet());
