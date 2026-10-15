// accounts.js: Accounts tab (owner only): add accounts, change roles, reset passwords, disable
let USERS=[],xEdit=null;
function xRender(){$('#xt').innerHTML=USERS.map(u=>`<tr><td>${esc(u.name)}</td><td>${esc(u.username)}</td><td>${u.role}</td><td>${u.active?'Active':'<span class="tag b">Disabled</span>'}</td><td style="white-space:nowrap"><button data-e="${u.id}">Edit</button> <button data-t="${u.id}">${u.active?'Disable':'Enable'}</button></td></tr>`).join('')}
async function drawAcc(){const r=await api('/api/users',{});if(r.error){$('#xm').textContent=r.error;return}USERS=r.users;xRender()}
function xClear(){xEdit=null;['xn','xu','xp'].forEach(i=>$('#'+i).value='');$('#xu').disabled=false;$('#xr').value='staff';$('#xs').textContent='Save account';$('#xm').textContent=''}
async function xSave(o){const r=await api('/api/user',o);if(r.error){$('#xm').textContent=r.error;return false}USERS=r.users;xRender();return true}
$('#xs').onclick=async()=>{const cur=USERS.find(u=>u.id===xEdit);if(await xSave({id:xEdit,name:$('#xn').value,username:$('#xu').value,role:$('#xr').value,password:$('#xp').value,active:cur?cur.active:true}))xClear()};
$('#xc').onclick=xClear;
$('#xt').onclick=async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.e){const u=USERS.find(x=>x.id==b.dataset.e);xEdit=u.id;$('#xn').value=u.name;$('#xu').value=u.username;$('#xu').disabled=true;$('#xr').value=u.role;$('#xp').value='';$('#xs').textContent='Update account';window.scrollTo(0,0)}else if(b.dataset.t){const u=USERS.find(x=>x.id==b.dataset.t);$('#xm').textContent='';await xSave({id:u.id,name:u.name,username:u.username,role:u.role,active:!u.active,password:''})}};
