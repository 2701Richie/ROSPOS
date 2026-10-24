// receipts.js: Receipts tab (list, view, password-protected void and change)
function openPm(h){$('#pb').innerHTML=h;$('#pm').hidden=false;$('#vno').onclick=()=>{$('#pm').hidden=true}}
const AUTH='<label>Reason<input id="vr"></label><label style="margin-top:8px">Your password<input id="vp" type="password" autocomplete="current-password"></label>';
let receiptLoadedDate='',receiptDaySales=[],receiptDayLoading=false,receiptDayError='',receiptDayRequest=0;
async function refreshReceiptDate(){
 const date=$('#receiptDate').value,request=++receiptDayRequest;
 const session=typeof sessionRevision==='undefined'?null:sessionRevision;
 receiptLoadedDate='';
 receiptDaySales=[];
 receiptDayLoading=!!date;
 receiptDayError='';
 drawRcp();
 if(!date)return;
 const response=await api('/api/receipt-date?date='+encodeURIComponent(date));
 if(request!==receiptDayRequest||date!==$('#receiptDate').value||!ME||
    (session!==null&&session!==sessionRevision))return;
 receiptDayLoading=false;
 receiptDayError=response.error||'';
 if(!receiptDayError){
   receiptLoadedDate=date;
   receiptDaySales=response.sales||[];
   if(response.unavailable)receiptDayError='Archived receipts for this date could not be read. Results may be incomplete.';
 }
 drawRcp();
}
function drawRcp(){
 const selectedDate=$('#receiptDate').value;
 const all=selectedDate?(receiptLoadedDate===selectedDate?[...receiptDaySales]:[]):[...(S.s||[])];
 const today=(S&&S.today)||T;
 const todaySales=(S.s||[]).filter(s=>s.d===today),todayDone=todaySales.filter(s=>!s.v);
 $('#receiptTodayCount').textContent=todaySales.length.toLocaleString('en-PH');
 $('#receiptTodayTotal').textContent=M(todayDone.reduce((a,s)=>a+(Number(s.tot)||0),0));
 $('#receiptVoidCount').textContent=todaySales.filter(s=>s.v).length.toLocaleString('en-PH');
 const q=$('#rq').value.trim().toLowerCase().replace(/^#/,''),date=$('#receiptDate').value,status=$('#receiptStatus').value;
 const l=all.reverse().filter(s=>{
  const st=s.v?'void':s.h&&s.h.length?'changed':'ok';
  const match=!q||String(s.no).toLowerCase().includes(q)||String(s.d||'').toLowerCase().includes(q)||String(s.t||'').toLowerCase().includes(q)||String(s.by||'').toLowerCase().includes(q)||(s.l||[]).some(x=>String(x.n||'').toLowerCase().includes(q));
  return match&&(!date||s.d===date)&&(status==='all'||st===status);
 });
 const shown=l.slice(0,300);
 $('#receiptResultCount').textContent=receiptDayLoading?'Loading receipts for '+selectedDate+'…':
   receiptDayError?receiptDayError:
   shown.length.toLocaleString('en-PH')+' of '+l.length.toLocaleString('en-PH')+' matching receipts'+(l.length>300?' · narrow your filters to find older matches':'')+
   (!selectedDate?' · select a date to search older archived receipts':'');
 $('#receiptEmpty').hidden=!!shown.length;
 $('#rb').innerHTML=shown.map(s=>{
  const st=s.v?`<span class="receipt-status is-void">Voided</span>`:s.h&&s.h.length?`<span class="receipt-status is-changed">Changed</span>`:`<span class="receipt-status is-complete">Completed</span>`;
  const reason=s.v?`<small class="receipt-status-note">${esc(s.v.w||'')}${s.v.u?' · '+esc(s.v.u):''}</small>`:s.h&&s.h.length?`<small class="receipt-status-note">${esc(s.h[s.h.length-1].w||'')}${s.h[s.h.length-1].u?' · '+esc(s.h[s.h.length-1].u):''}</small>`:'';
  return `<tr><td><strong class="receipt-no">#${esc(s.no)}</strong></td><td><span class="receipt-date">${esc(s.d||'')}</span><small class="receipt-time">${esc(s.t||'')}</small></td><td>${(s.l||[]).reduce((a,x)=>a+(Number(x.q)||0),0).toLocaleString('en-PH')}</td><td class="receipt-total">${M(Number(s.tot)||0)}</td><td>${esc(s.by||'—')}</td><td>${st}${reason}</td><td><div class="receipt-actions"><button type="button" data-v="${esc(s.no)}">View</button> ${can('manager')&&(S.s||[]).some(recent=>recent.no===s.no)?`<button type="button" data-c="${esc(s.no)}"${s.v?' disabled':''}>Change</button> <button type="button" class="receipt-void-btn" data-x="${esc(s.no)}"${s.v?' disabled':''}>Void</button>`:''}</div></td></tr>`
 }).join('')||'';
}
function openVoid(s){openPm(`<h2>Void sale #${s.no}</h2><p class="mu" style="margin-top:0">${s.d} ${s.t}, ${M(s.tot)}. The items go back into stock.</p>${AUTH}<div class="acts"><button class="pri" id="vok">Void sale</button><button id="vno">Cancel</button></div><div id="vm" class="err" role="status"></div>`);
$('#vok').onclick=async()=>{const w=$('#vr').value.trim();if(!w){$('#vm').textContent='Enter a reason.';return}const r=await api('/api/void',{no:s.no,password:$('#vp').value,why:w});if(r.error){$('#vm').textContent=r.error;$('#vp').value='';return}$('#pm').hidden=true;clampCart();if($('#receiptDate').value)await refreshReceiptDate();else drawRcp();drawGrid();drawLines()}}
function openChg(s){openPm(`<h2>Change sale #${s.no}</h2><div class="wrap"><table><tbody>${s.l.map(l=>`<tr><td>${esc(l.n)}<br><small>${M(l.p)} each</small></td><td><input class="cq" inputmode="numeric" value="${l.q}" style="width:72px" aria-label="Quantity for ${esc(l.n)}"></td></tr>`).join('')}</tbody></table></div><p class="mu">Set a quantity to 0 to remove an item.</p><div class="form"><label>Cash received<input id="cc" inputmode="decimal" value="${s.cash}"></label></div>${AUTH}<div class="acts"><button class="pri" id="vok">Save changes</button><button id="vno">Cancel</button></div><div id="vm" class="err" role="status"></div>`);
$('#vok').onclick=async()=>{const m=$('#vm'),qs=[...document.querySelectorAll('.cq')].map(x=>x.value.trim());if(qs.some(x=>!/^\d+$/.test(x))){m.textContent='Quantities must be whole numbers.';return}const r=await api('/api/change',{no:s.no,password:$('#vp').value,why:$('#vr').value.trim(),q:qs.map(Number),cash:parseFloat($('#cc').value)});if(r.error){m.textContent=r.error;$('#vp').value='';return}$('#pm').hidden=true;clampCart();if($('#receiptDate').value)await refreshReceiptDate();else drawRcp();drawGrid();drawLines()}}
$('#rq').oninput=drawRcp;
$('#receiptDate').onchange=refreshReceiptDate;
$('#receiptStatus').onchange=drawRcp;
$('#receiptClear').onclick=()=>{$('#rq').value='';$('#receiptDate').value='';$('#receiptStatus').value='all';refreshReceiptDate()};
$('#rb').onclick=e=>{const b=e.target.closest('button');if(!b)return;const n=+(b.dataset.v||b.dataset.c||b.dataset.x),s=S.s.find(x=>x.no===n)||receiptDaySales.find(x=>x.no===n);if(!s)return;if(b.dataset.v)receipt(s);else if(b.dataset.c)openChg(s);else openVoid(s)};
