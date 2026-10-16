// livesales.js: live feed of today's sales (newest first, tap a row for items) and a sold-today-by-product tally
let liveBusy=false,liveSeen=null,liveOpen=new Set();
function liveStatus(text,ok=true){$('#liveStatus').textContent=text;$('.live-dot').classList.toggle('offline',!ok)}
function liveKey(s){return String(s.no)+'|'+String(s.d||'')+'|'+String(s.t||'')}
function liveState(s){return s.v?'void':(s.h&&s.h.length)?'amended':'ok'}
function liveTag(s){const k=liveState(s);return k==='void'?'<span class="tag b">VOID</span>':k==='amended'?'<span class="tag w">AMENDED</span>':''}
function liveSummary(s){const l=s.l||[],a=l.slice(0,2).map(x=>esc(x.n)+' ×'+esc(x.q)).join(', ');return (a+(l.length>2?', +'+(l.length-2)+' more':''))||'—'}
function liveLine(l){return '<li><span class="live-item-name">'+esc(l.n)+'</span><span class="live-item-qty">× '+esc(l.q)+'</span><span class="live-item-price">'+M((Number(l.p)||0)*(Number(l.q)||0))+'</span></li>'}
function liveRow(s,fresh){
 const key=liveKey(s),open=liveOpen.has(key),st=liveState(s);
 const detail=open?'<div class="live-items"><ul>'+(s.l||[]).map(liveLine).join('')+'</ul>'+(s.v?'<p class="live-note">Void reason: '+esc(s.v.w||'')+(s.v.u?' · '+esc(s.v.u):'')+'</p>':'')+(st==='amended'?'<p class="live-note">Latest change: '+esc(s.h[s.h.length-1].w||'')+'</p>':'')+'</div>':'';
 return '<div class="live-row'+(fresh?' live-new':'')+(st!=='ok'?' '+st:'')+'"><button type="button" class="live-row-main" data-key="'+esc(key)+'" aria-expanded="'+open+'"><span class="live-row-time">'+esc(s.t||'')+'</span><span class="live-row-no">#'+esc(s.no)+'</span><span class="live-row-sum">'+liveSummary(s)+'</span><span class="live-row-by mu">'+esc(s.by||'—')+'</span><span class="live-row-tot">'+M(Number(s.tot)||0)+'</span><span class="live-row-tag">'+liveTag(s)+'</span></button>'+detail+'</div>';
}
function drawTally(sales){
 const map=new Map();
 for(const s of sales){if(s.v)continue;for(const l of s.l||[]){const k=l.id!=null?'i'+l.id:'n'+l.n,r=map.get(k)||{n:String(l.n),q:0,amt:0};r.q+=Number(l.q)||0;r.amt+=(Number(l.p)||0)*(Number(l.q)||0);map.set(k,r)}}
 const q=($('#liveQ').value||'').trim().toLowerCase(),all=[...map.values()],units=all.reduce((a,r)=>a+r.q,0);
 const rows=all.filter(r=>!q||r.n.toLowerCase().includes(q)).sort((a,b)=>b.q-a.q||a.n.localeCompare(b.n));
 $('#liveTallyTotal').textContent=all.length?all.length+' product(s) · '+units.toLocaleString('en-PH')+' unit(s)':'';
 $('#liveTally').innerHTML=rows.length?'<table class="live-tally-table"><thead><tr><th>Product</th><th>Units</th><th>Amount</th></tr></thead><tbody>'+rows.map(r=>'<tr><td>'+esc(r.n)+'</td><td>'+r.q.toLocaleString('en-PH')+'</td><td>'+M(r.amt)+'</td></tr>').join('')+'</tbody></table>':'<p class="mu">'+(all.length?'No product matches your search.':'Nothing sold yet today.')+'</p>';
}
function drawLive(){
 const day=(S&&S.today)||T,all=S.s||[],today=all.filter(s=>s.d===day),ok=today.filter(s=>!s.v),last=all[all.length-1];
 $('#liveCount').textContent=ok.length.toLocaleString('en-PH');
 $('#liveRevenue').textContent=M(ok.reduce((a,s)=>a+(Number(s.tot)||0),0));
 $('#liveLatest').textContent=last?(last.d===day?(last.t||last.d):(last.d+' '+(last.t||''))):'No sales yet';
 const sel=$('#liveBy'),cur=sel.value,names=[...new Set(today.map(s=>s.by).filter(Boolean))].sort(),sig=names.join('|');
 if(sel.dataset.sig!==sig){sel.innerHTML='<option value="">All cashiers</option>'+names.map(n=>'<option>'+esc(n)+'</option>').join('');sel.dataset.sig=sig;sel.value=names.includes(cur)?cur:''}
 const st=$('#liveStatusF').value,by=sel.value;
 const rows=today.slice().reverse().filter(s=>(!st||st==='all'||liveState(s)===st)&&(!by||s.by===by));
 const fresh=new Set();
 if(liveSeen===null)liveSeen=new Set(today.map(liveKey));
 else today.forEach(s=>{const k=liveKey(s);if(!liveSeen.has(k)){liveSeen.add(k);fresh.add(k)}});
 const shown=rows.slice(0,200);
 $('#liveFeed').innerHTML=shown.length?shown.map(s=>liveRow(s,fresh.has(liveKey(s)))).join('')+(rows.length>shown.length?'<p class="mu live-more">Showing the newest 200 of '+rows.length+'. Use the Receipts tab for older sales.</p>':''):'<div class="card live-empty"><h3>'+(today.length?'No sales match these filters':'No sales yet today')+'</h3><p class="mu">'+(today.length?'Change the filters above to see more.':'New sales appear here the moment they are rung up.')+'</p></div>';
 drawTally(today);
}
async function refreshLive(){
 if(liveBusy||!ME)return;liveBusy=true;
 try{const r=await load();if(r.error){liveStatus('Connection issue',false);return}drawLive();liveStatus('Live · updated '+new Date().toLocaleTimeString('en-PH',{hour:'2-digit',minute:'2-digit',second:'2-digit'}),true)}
 catch(e){liveStatus('Connection issue',false)}finally{liveBusy=false}
}
$('#liveRefresh').onclick=refreshLive;
$('#liveFeed').onclick=e=>{const b=e.target.closest('[data-key]');if(!b)return;const k=b.dataset.key;if(liveOpen.has(k))liveOpen.delete(k);else liveOpen.add(k);drawLive()};
['#liveStatusF','#liveBy'].forEach(id=>$(id).onchange=drawLive);
$('#liveQ').oninput=()=>drawTally((S.s||[]).filter(s=>s.d===((S&&S.today)||T)));
