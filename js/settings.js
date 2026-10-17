// settings.js: Settings tab (owner only): store name, sign-in length, backup days kept
function cfg(){return S.cfg||{store:'',session_hours:12,backup_days:30}}
function storeName(){return String(cfg().store||'').trim()}
function applyBrand(){const n=storeName(),sm=document.querySelector('.brand small');if(sm)sm.textContent=n||'PHARMACY POS';document.title=n?n+' — ROSPOS':'ROSPOS — Pharmacy POS'}
function drawSet(){const c=cfg(),m=$('#sm');$('#sn').value=c.store||'';$('#sh').value=c.session_hours;$('#sd').value=c.backup_days;$('#sp').value='';m.textContent='';m.className='err'}
$('#sr').onclick=drawSet;
$('#ss').onclick=async()=>{const m=$('#sm');m.className='err';m.textContent='';const r=await api('/api/settings',{store:$('#sn').value,session_hours:$('#sh').value,backup_days:$('#sd').value,password:$('#sp').value});$('#sp').value='';if(r.error){m.textContent=r.error;return}applyBrand();drawSet();m.className='mu';m.textContent=r.msg||'Saved.'};
$('#sp').onkeydown=e=>{if(e.key==='Enter')$('#ss').click()};
// Theme button (every role, this device only): Automatic -> Light -> Dark. Saved in the browser, applied early by a script in index.html.
const THEMES=['auto','light','dark'],TH_ICON={auto:'◐',light:'☀',dark:'☾'},TH_NAME={auto:'Automatic',light:'Light',dark:'Dark'};
function themeGet(){try{const t=localStorage.getItem('pos-theme');return t==='light'||t==='dark'?t:'auto'}catch(e){return 'auto'}}
function themeApply(t){const r=document.documentElement,b=$('#tb');if(t==='auto')delete r.dataset.theme;else r.dataset.theme=t;b.textContent=TH_ICON[t];b.title='Theme: '+TH_NAME[t]+' (tap to change)';b.setAttribute('aria-label','Theme: '+TH_NAME[t]+'. Tap to change.')}
$('#tb').onclick=()=>{const n=THEMES[(THEMES.indexOf(themeGet())+1)%THEMES.length];try{if(n==='auto')localStorage.removeItem('pos-theme');else localStorage.setItem('pos-theme',n)}catch(e){}themeApply(n)};
themeApply(themeGet());
