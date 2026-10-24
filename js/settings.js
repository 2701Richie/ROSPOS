// settings.js: Settings tab (owner only): store name, sign-in length, backup days kept
function cfg(){return S.cfg||{store:'',session_hours:12,backup_days:30,rc_addr:'',rc_phone:'',rc_tag:'',rc_foot:''}}
function storeName(){return String(cfg().store||'').trim()}
function applyBrand(){const n=storeName(),sm=document.querySelector('.brand small');if(sm)sm.textContent=n||'PHARMACY POS';document.title=n?n+' — ROSPOS':'ROSPOS — Pharmacy POS'}
function drawSet(){const c=cfg(),m=$('#sm');$('#sn').value=c.store||'';$('#rcad').value=c.rc_addr||'';$('#rcph').value=c.rc_phone||'';$('#rctg').value=c.rc_tag||'';$('#rcft').value=c.rc_foot||'';$('#sh').value=c.session_hours;$('#sd').value=c.backup_days;$('#sp').value='';m.textContent='';m.className='err';$('#cloudRecovery').hidden=true;$('#cloudRecoveryText').textContent='';drawRcpv();void refreshCloud()}
function rcForm(){return{store:$('#sn').value,rc_addr:$('#rcad').value,rc_phone:$('#rcph').value,rc_tag:$('#rctg').value,rc_foot:$('#rcft').value}}
function drawRcpv(){$('#rcpv').innerHTML=rcptHtml(rcptBlocks({no:1042,d:T,t:'10:42 AM',by:'Maria',l:[{n:'Paracetamol 500mg',q:2,p:5.5},{n:'Vitamin C 500mg',q:1,p:8},{n:'Alcohol 70% 500ml',q:1,p:85}],tot:104,cash:200},rcForm()))}
['sn','rcad','rcph','rctg','rcft'].forEach(i=>$('#'+i).oninput=drawRcpv);
$('#rctest').onclick=()=>rcptPopup(rcptTestBlocks(rcForm()));
$('#sr').onclick=drawSet;
$('#ss').onclick=async()=>{const m=$('#sm');m.className='err settings-message';m.textContent='';const hours=Number($('#sh').value),days=Number($('#sd').value);if(!Number.isFinite(hours)||hours<1||hours>72){m.textContent='Sign-in duration must be between 1 and 72 hours.';$('#sh').focus();return}if(!Number.isInteger(days)||days<7||days>365){m.textContent='Backup retention must be a whole number from 7 to 365 days.';$('#sd').focus();return}if(!$('#sp').value){m.textContent='Enter your current password to confirm these changes.';$('#sp').focus();return}const r=await api('/api/settings',{store:$('#sn').value,rc_addr:$('#rcad').value,rc_phone:$('#rcph').value,rc_tag:$('#rctg').value,rc_foot:$('#rcft').value,session_hours:$('#sh').value,backup_days:$('#sd').value,password:$('#sp').value});$('#sp').value='';if(r.error){m.textContent=r.error;return}applyBrand();drawSet();m.className='mu settings-message';m.textContent=r.msg||'Settings saved.'};
$('#sp').onkeydown=e=>{if(e.key==='Enter')$('#ss').click()};
// Device-local appearance choice; staff and managers can access Appearance without store settings.
const THEMES=['auto','light','dark'];
function themeGet(){try{const t=localStorage.getItem('pos-theme');return t==='light'||t==='dark'?t:'auto'}catch(e){return 'auto'}}
function themeApply(t){const r=document.documentElement;if(t==='auto')delete r.dataset.theme;else r.dataset.theme=t;$('#themeChoice').value=t}
$('#themeChoice').onchange=()=>{const t=$('#themeChoice').value;try{if(t==='auto')localStorage.removeItem('pos-theme');else localStorage.setItem('pos-theme',t)}catch(e){}themeApply(t)};
themeApply(themeGet());

// OAuth tokens remain on the POS computer. Only the one-time recovery keys are
// shown to the owner, who must save both before continuing to Google.
async function refreshCloud(){
  const info=await api('/api/cloud-backup');
  const message=$('#cloudMessage');
  if(info.error){message.textContent=info.error;return}
  const connected=Boolean(info.connected);
  if(connected){
    // Erase the one-time recovery kit from the page after authorization.
    $('#cloudRecoveryText').textContent='';
    $('#cloudRecovery').hidden=true;
    $('#cloudGoogleAuthorize').removeAttribute('href');
    $('#cloudRecoverySaved').checked=false;
  }
  $('#cloudConnectBox').hidden=connected;
  $('#cloudControls').hidden=!connected;
  $('#cloudConnect').disabled=!info.rclone_installed;
  $('#cloudNow').disabled=!connected||Boolean(info.running);
  $('#cloudDisconnect').disabled=!connected;
  const last=info.last_success?' Last successful backup: '+new Date(info.last_success).toLocaleString()+'.':' No successful cloud backup yet.';
  const state=info.running?'Backup in progress.':connected?'Automatic daily encrypted backups enabled.':'Google Drive is not connected.';
  const reconnect=info.reconnect_required?' An earlier configuration is no longer supported; reconnect using Google sign-in. Existing cloud files were not deleted.':'';
  $('#cloudStatus').textContent=state+(connected?last:'')+reconnect+(info.last_error?' '+info.last_error:'');
  if(!info.rclone_installed)message.textContent='rclone is required but is not installed on the POS computer.';
}
async function cloudAction(action){
  const password=$('#cloudPassword').value;
  const msg=$('#cloudMessage');
  if(!password){msg.textContent='Enter your Owner password for this action.';$('#cloudPassword').focus();return}
  if(action==='connect'){$('#cloudRecovery').hidden=true;$('#cloudRecoveryText').textContent='';$('#cloudGoogleAuthorize').removeAttribute('href');$('#cloudRecoverySaved').checked=false;$('#cloudGoogleAuthorize').hidden=true}
  const body={action,password};
  if(action==='connect'){body.client_id=$('#cloudClientId').value.trim();body.client_secret=$('#cloudClientSecret').value.trim()}
  $('#cloudPassword').value='';
  msg.textContent='Working…';
  for(const id of ['cloudNow','cloudDisconnect','cloudConnect'])$('#'+id).disabled=true;
  const result=await api('/api/cloud-backup',body);
  msg.textContent=result.error||result.msg||'Cloud backup settings updated.';
  if(action==='connect'&&!result.error&&result.cloud?.authorization_url){
    // This is the only time recovery keys are displayed; don't store in localStorage.
    const kit=result.cloud.recovery;
    $('#cloudRecoveryText').textContent='Backup password: '+kit.password+'\nBackup salt: '+kit.salt+'\nGoogle Drive folder: '+kit.folder;
    $('#cloudRecovery').hidden=false;
    $('#cloudGoogleAuthorize').href=result.cloud.authorization_url;
    $('#cloudGoogleAuthorize').hidden=true;
    $('#cloudClientSecret').value='';
    msg.textContent='Save both recovery secrets, then continue to Google sign-in.';
  }
  await refreshCloud();
}
$('#cloudCheck').onclick=refreshCloud;
$('#cloudNow').onclick=()=>cloudAction('backup');
$('#cloudDisconnect').onclick=()=>cloudAction('disconnect');

$('#cloudConnect').onclick=()=>cloudAction('connect');
$('#cloudCopyRecovery').onclick=async()=>{
  const kit=$('#cloudRecoveryText').textContent;
  try{await navigator.clipboard.writeText(kit);$('#cloudMessage').textContent='Recovery credentials copied. Save them somewhere secure, outside the POS computer.'}
  catch(e){$('#cloudMessage').textContent='Copy unavailable: select the recovery text and copy it manually.'}
};

$('#cloudRecoverySaved').onchange=()=>{$('#cloudGoogleAuthorize').hidden=!$('#cloudRecoverySaved').checked};
