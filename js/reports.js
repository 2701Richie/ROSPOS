// reports.js: Reports, lightweight sales forecasting, alerts, backup and restore
let forecastDays = 30;
// Reports are organized into focused views; returning to the tab always starts at the hub.
if(document.addEventListener)document.addEventListener('click',e=>{
 const drawer=e.target.closest('[data-report-drawer]');
 if(drawer){const key=drawer.dataset.reportDrawer;const page=document.querySelector('[data-report-page="'+key+'"]');if(!page)return;$('#reportCabinet').hidden=true;document.querySelectorAll('#v-rep [data-report-page]').forEach(x=>x.hidden=x!==page);if(key==='daily')drawDailySales();return}
 const dayButton=e.target.closest('[data-report-sales-day]');if(dayButton){$('#reportSalesDate').value=dayButton.dataset.reportSalesDay;drawDailySales();return}
 if(e.target.closest('[data-report-home]')){document.querySelectorAll('#v-rep [data-report-page]').forEach(x=>x.hidden=true);$('#reportCabinet').hidden=false}
});
function localDay(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function shiftDay(day,offset){const d=new Date(day+'T12:00:00');d.setDate(d.getDate()+offset);return localDay(d)}
function dayMap(){const map=new Map();for(const s of S.s){if(s.v||!/^\d{4}-\d{2}-\d{2}$/.test(s.d||''))continue;const row=map.get(s.d)||{revenue:0,transactions:0};row.revenue+=Number(s.tot)||0;row.transactions++;map.set(s.d,row)}return map}
function makeForecast(days){
 const sales=dayMap(),dates=[...sales.keys()].sort();if(!dates.length)return null;
 const earliest=dates[0],start=shiftDay(T,-83)<earliest?earliest:shiftDay(T,-83),history=[];
 for(let d=start;d<=T;d=shiftDay(d,1)){const row=sales.get(d)||{revenue:0,transactions:0};history.push({d,dow:new Date(d+'T12:00:00').getDay(),revenue:row.revenue,transactions:row.transactions})}
 const recent=history.slice(-14),prior=history.slice(-28,-14);
 const ratio=key=>{const a=recent.reduce((n,x)=>n+x[key],0),b=prior.reduce((n,x)=>n+x[key],0);if(prior.length<7||b<=0)return 1;return Math.max(.8,Math.min(1.2,a/b))};
 const trends={revenue:ratio('revenue'),transactions:ratio('transactions')},future=[];
 for(let i=1;i<=days;i++){const d=shiftDay(T,i),dow=new Date(d+'T12:00:00').getDay(),same=history.filter(x=>x.dow===dow).slice(-8),fallback=history.slice(-28);const avg=key=>{const sample=same.length?same:fallback;return sample.length?sample.reduce((n,x)=>n+x[key],0)/sample.length:0};future.push({d,revenue:Math.max(0,avg('revenue')*trends.revenue),transactions:Math.max(0,avg('transactions')*trends.transactions)})}
 const revenue=future.reduce((n,x)=>n+x.revenue,0),transactions=future.reduce((n,x)=>n+x.transactions,0),actual30=[],chartStart=shiftDay(T,-29)<earliest?earliest:shiftDay(T,-29);
 for(let d=chartStart;d<=T;d=shiftDay(d,1)){const row=sales.get(d)||{revenue:0,transactions:0};actual30.push({d,...row})}
 const hd=history.length,conf=hd<28?'low':hd<56?'medium':'good',band=({low:.4,medium:.25,good:.15}[conf])+(days>=90?.1:0);
 return{future,actual30,revenue,transactions:Math.round(transactions),avg:revenue/days,historyDays:hd,conf,band}
}
function forecastChart(model){
 const hist=model.actual30,future=model.future,all=hist.map(x=>x.revenue).concat(future.map(x=>x.revenue)),max=Math.max(1,...all)*1.12,W=900,H=270,left=48,right=18,top=18,bottom=34,iw=W-left-right,ih=H-top-bottom,count=Math.max(2,hist.length+future.length);
 const x=i=>left+i/(count-1)*iw,y=v=>top+ih-v/max*ih;
 const path=arr=>arr.map((v,i)=>(i?'L':'M')+x(v.i).toFixed(1)+','+y(v.value).toFixed(1)).join(' ');
 const actual=hist.map((v,i)=>({i,value:v.revenue})),futurePath=[{i:Math.max(0,hist.length-1),value:hist.length?hist[hist.length-1].revenue:0}].concat(future.map((v,i)=>({i:hist.length+i,value:v.revenue})));
 const grid=[0,.25,.5,.75,1].map(p=>'<g><line x1="'+left+'" y1="'+(top+ih*(1-p)).toFixed(1)+'" x2="'+(W-right)+'" y2="'+(top+ih*(1-p)).toFixed(1)+'" class="chart-grid"/><text x="'+(left-8)+'" y="'+(top+ih*(1-p)+4).toFixed(1)+'" text-anchor="end" class="chart-label">'+Math.round(max*p).toLocaleString('en-PH')+'</text></g>').join('');
 const labelIdx=[0,Math.floor((hist.length-1)/2),hist.length-1,hist.length+Math.floor((future.length-1)/2),count-1].filter((v,i,a)=>v>=0&&v<count&&a.indexOf(v)===i);
 const labels=labelIdx.map(i=>{const d=i<hist.length?hist[i].d:future[i-hist.length].d;return '<text x="'+x(i).toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle" class="chart-label">'+d.slice(5)+'</text>'}).join('');
 const cut=hist.length>1?x(hist.length-1):left;
 return '<svg class="forecast-svg" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Historical daily revenue and forecast revenue line chart">'+grid+'<line x1="'+cut+'" y1="'+top+'" x2="'+cut+'" y2="'+(top+ih)+'" class="chart-cut"/><path d="'+path(actual)+'" class="chart-actual"/><path d="'+path(futurePath)+'" class="chart-forecast"/><text x="'+left+'" y="12" class="chart-label">₱ revenue</text><text x="'+Math.min(cut+8,W-110)+'" y="12" class="chart-label">FORECAST →</text>'+labels+'</svg>'
}
function drawForecast(){
 const model=makeForecast(forecastDays);document.querySelectorAll('[data-fdays]').forEach(b=>b.classList.toggle('on',Number(b.dataset.fdays)===forecastDays));const area=$('#forecastContent');
 if(!model){area.innerHTML='<div class="forecast-empty"><span class="forecast-empty-icon">↗</span><h3>Forecast appears after your first sale</h3><p class="mu">Once ROSPOS has completed sales recorded, this dashboard will estimate revenue and transaction volume from the store’s history.</p></div>';return}
 const notice=model.conf==='good'?'':'<div class="forecast-warn"><b>'+(model.conf==='low'?'Low confidence':'Medium confidence')+'</b> · only '+model.historyDays+' days of sales so far. '+(model.conf==='low'?'Treat these numbers as a rough guess; they firm up after about 4 weeks of real sales.':'Getting better; most reliable after about 8 weeks.')+'</div>';
 area.innerHTML=notice+'<div class="forecast-kpis"><div class="forecast-kpi"><span class="mu">Projected revenue</span><strong>'+M(R(model.revenue))+'</strong><small>Next '+forecastDays+' days · likely '+M(R(model.revenue*(1-model.band)))+' to '+M(R(model.revenue*(1+model.band)))+'</small></div><div class="forecast-kpi"><span class="mu">Projected transactions</span><strong>'+model.transactions.toLocaleString('en-PH')+'</strong><small>Expected completed sales</small></div><div class="forecast-kpi"><span class="mu">Average per day</span><strong>'+M(model.avg)+'</strong><small>Estimated daily revenue</small></div></div><div class="forecast-legend"><span><i class="legend-dot actual-dot"></i>Historical sales</span><span><i class="legend-dot forecast-dot"></i>Forecast</span><span class="mu">Daily revenue · PHP</span></div><div class="forecast-chart">'+forecastChart(model)+'</div><div class="forecast-foot"><span>Model: recent trend + weekday averages</span><span>Based on '+model.historyDays+' days of available history</span></div>'
}
document.querySelectorAll('[data-fdays]').forEach(b=>b.addEventListener('click',()=>{forecastDays=Number(b.dataset.fdays)||30;drawForecast()}));
function costStats(){
 const costed=S.p.filter(p=>p.c!=null),sum=(a,f)=>R(a.reduce((t,p)=>t+f(p),0)),now=lists().now,rc=now.filter(x=>x.p.c!=null);
 const prof=from=>{let profit=0,rev=0,lines=0,missing=0;for(const s of S.s){if(s.v||!s.d||s.d<from||s.d>T)continue;for(const l of s.l){if(l.c==null){missing++;continue}lines++;profit+=(l.p-l.c)*l.q;rev+=l.p*l.q}}return{profit:R(profit),revenue:R(rev),lines,missing}};
 return{atCost:sum(costed,p=>p.s*p.c),atPrice:sum(costed,p=>p.s*p.p),unknown:S.p.length-costed.length,total:S.p.length,reorderCount:now.length,reorderCost:R(rc.reduce((t,x)=>t+sug(x.p)*x.p.c,0)),reorderUnknown:now.length-rc.length,today:prof(T),d30:prof(shiftDay(T,-29))}
}
function drawCost(){
 const c=costStats(),card=(l,v,n)=>'<div class="card"><span class="mu">'+l+'</span><b>'+v+'</b><small class="mu">'+n+'</small></div>';
 const pn=x=>(x.lines+x.missing===0?'No sales yet':x.missing?x.missing+' item line'+(x.missing>1?'s':'')+' without a cost not counted':'Every item line has a cost')+(x.revenue?' \u00b7 margin '+Math.round(x.profit/x.revenue*100)+'%':'');
 $('#cs').innerHTML=card('Stock value at cost',M(c.atCost),c.unknown?c.unknown+' of '+c.total+' products have no cost yet':'All '+c.total+' products have a cost')
 +card('Stock value at selling price',M(c.atPrice),'Products with a cost only')
 +card('Estimated cost to reorder',M(c.reorderCost),c.reorderCount+' product'+(c.reorderCount===1?'':'s')+' to reorder'+(c.reorderUnknown?', '+c.reorderUnknown+' without a cost':''))
 +card('Gross profit today',M(c.today.profit),pn(c.today))
 +card('Gross profit, last 30 days',M(c.d30.profit),pn(c.d30))
}
function drawDailySales(){
 const picker=$('#reportSalesDate');if(!picker)return;
 if(!picker.value)picker.value=T;
 const selected=picker.value,all=S.s.filter(s=>s.d===selected),valid=all.filter(s=>!s.v),voided=all.filter(s=>s.v),total=R(valid.reduce((n,s)=>n+(Number(s.tot)||0),0));
 $('#reportSalesDayHeading').textContent='Transactions for '+selected;
 $('#reportSalesSummary').innerHTML='<div class="daily-sales-kpi"><span class="mu">Sales total</span><b>'+M(total)+'</b></div><div class="daily-sales-kpi"><span class="mu">Completed sales</span><b>'+valid.length+'</b></div><div class="daily-sales-kpi"><span class="mu">Voided transactions</span><b>'+voided.length+'</b></div>';
 const rows=all.slice().sort((a,b)=>String(b.t||'').localeCompare(String(a.t||''))||Number(b.no||0)-Number(a.no||0));
 $('#reportSalesDayRows').innerHTML=rows.map(s=>'<tr><td>#'+esc(s.no||'—')+'</td><td>'+esc(s.t||'—')+'</td><td>'+esc((s.l||[]).reduce((n,l)=>n+(Number(l.q)||0),0))+'</td><td>'+M(Number(s.tot)||0)+'</td><td><span class="daily-sale-status '+(s.v?'is-void':'is-complete')+'">'+(s.v?'Voided':'Completed')+'</span></td></tr>').join('')||'<tr><td colspan="5" class="mu">No transactions recorded for this date.</td></tr>';
 const byDate=new Map();for(const sale of S.s){if(!/^\d{4}-\d{2}-\d{2}$/.test(sale.d||''))continue;const row=byDate.get(sale.d)||{count:0,voided:0,total:0};if(sale.v)row.voided++;else{row.count++;row.total+=Number(sale.tot)||0}byDate.set(sale.d,row)}
 const dates=[...byDate.keys()].sort((a,b)=>b.localeCompare(a)).slice(0,90);
 $('#reportDailyHistoryRows').innerHTML=dates.map(d=>{const x=byDate.get(d);return '<tr class="daily-sales-history-row'+(d===selected?' is-selected':'')+'"><td><button type="button" class="daily-sales-day-link" data-report-sales-day="'+d+'">'+d+'</button></td><td>'+x.count+(x.voided?' <small class="mu">('+x.voided+' voided)</small>':'')+'</td><td>'+M(R(x.total))+'</td></tr>'}).join('')||'<tr><td colspan="3" class="mu">No sales history recorded yet.</td></tr>';
}
const reportDatePicker=document.querySelector('#reportSalesDate');if(reportDatePicker&&reportDatePicker.addEventListener)reportDatePicker.addEventListener('change',drawDailySales);
const reportTodayButton=document.querySelector('#reportSalesToday');if(reportTodayButton&&reportTodayButton.addEventListener)reportTodayButton.addEventListener('click',()=>{$('#reportSalesDate').value=T;drawDailySales()});
function drawRep(){
 const td=S.s.filter(s=>s.d===T&&!s.v),sum=k=>R(td.reduce((a,s)=>a+s[k],0));drawForecast();drawCost();
 $('#st').innerHTML='<div class="card"><span class="mu">Sales today</span><b>'+td.length+'</b></div><div class="card"><span class="mu">Total today</span><b>'+M(sum('tot'))+'</b></div>';
 const L=(f,g)=>{const a=S.p.filter(f);return a.length?a.map(g).join(''):'<li class="mu">None</li>'};
 $('#al').innerHTML='<div class="card"><h3>Expired</h3><ul>'+L(p=>p.e&&p.e<T,p=>'<li>'+esc(p.n)+' ('+esc(p.e)+'), '+p.s+' left</li>')+'</ul></div><div class="card"><h3>Expiring within 90 days</h3><ul>'+L(p=>p.e&&p.e>=T&&p.e<=ds(90),p=>'<li>'+esc(p.n)+' ('+esc(p.e)+'), '+p.s+' left</li>')+'</ul></div><div class="card"><h3>Low stock</h3><ul>'+L(p=>p.m>0&&p.s<=p.m,p=>'<li>'+esc(p.n)+': '+p.s+' left</li>')+'</ul></div>';
 $('#rs').innerHTML=S.s.slice(-10).reverse().map(s=>'<tr><td>#'+s.no+(s.v?' (void)':'')+'</td><td>'+s.d+' '+s.t+'</td><td>'+s.l.reduce((a,l)=>a+l.q,0)+'</td><td>'+M(s.tot)+'</td></tr>').join('')||'<tr><td colspan="4" class="mu">No sales yet.</td></tr>'
}
$('#bd').onclick=async()=>{
 $('#bm').textContent='Preparing backup file…';
 try{
  const r=await fetch('/api/backup',{credentials:'same-origin',cache:'no-store'});
  if(!r.ok){let e={};try{e=await r.json()}catch(_){}throw new Error(e.error||'Could not download backup. Please sign in as the owner.')}
  const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download='rospos-backup-'+localDay(new Date())+'.json';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
  $('#bm').textContent='Backup file downloaded. Copy it to a USB drive or another safe location.';
 }catch(e){$('#bm').textContent=e.message||'Backup download failed.'}
};
async function restoreBackupData(d){
 const r=await api('/api/restore',{password:$('#bpn').value,data:d});
 if(r.error){$('#bm').textContent=r.error;return}
 cart=[];$('#bpn').value='';$('#bfile').value='';drawGrid();drawLines();drawProd();drawRep();$('#bm').textContent='Backup restored. A pre-restore safety snapshot was saved on the server.';
}
$('#br').onclick=async()=>{
 const f=$('#bfile').files[0];if(!f){$('#bm').textContent='Choose a backup .json file first.';return}
 if(!$('#bpn').value){$('#bm').textContent='Enter the owner password to restore a backup.';return}
 if(!confirm('Restore this backup? Current products, sales and activity history will be replaced. A safety snapshot will be saved first.'))return;
 try{const d=JSON.parse(await f.text());if(d.format&&d.format!=='ROSPOS-backup')throw new Error('This is not a ROSPOS backup file.');const data=d.data||d;if(!Array.isArray(data.p)||!Array.isArray(data.s))throw new Error('The selected file is not a valid ROSPOS backup.');await restoreBackupData(data)}catch(e){$('#bm').textContent=e.message||'Could not read this backup file.'}
};
$('#brlegacy').onclick=async()=>{let d;try{d=JSON.parse($('#bk').value)}catch(e){}if(!d||!Array.isArray(d.p)||!Array.isArray(d.s)){$('#bm').textContent='That text is not a valid backup.';return}if(!$('#bpn').value){$('#bm').textContent='Enter the owner password to restore a backup.';return}if(!confirm('Restore this legacy backup? Current products, sales and activity history will be replaced. A safety snapshot will be saved first.'))return;await restoreBackupData(d)};
