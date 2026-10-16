// livesales.js: calm, rotating live transaction slideshow
const LIVE_WINDOW=120000,LIVE_SLIDE_MS=8000;
let liveBusy=false,liveQueue=[],liveActive='',liveFirstDraw=true,liveTimer=null,liveSeen=new Set();
function liveStatus(text,ok=true){$('#liveStatus').textContent=text;$('.live-dot').classList.toggle('offline',!ok)}
function liveKey(s){return String(s.no)+'|'+String(s.d||'')+'|'+String(s.t||'')}
function liveCard(s){
 const status=s.v?'<span class="tag b">VOID</span>':s.h?'<span class="tag w">AMENDED</span>':'<span class="tag live-complete">COMPLETED</span>';
 const lines=(s.l||[]).map(l=>'<li><span class="live-item-name">'+esc(l.n)+'</span><span class="live-item-qty">× '+esc(l.q)+'</span><span class="live-item-price">'+M((Number(l.p)||0)*(Number(l.q)||0))+'</span></li>').join('');
 return '<article class="live-sale card live-slide-card"><div class="live-sale-top"><div><span class="live-sale-no">Sale #'+esc(s.no)+'</span><span class="mu live-time">'+esc((s.d||'')+' '+(s.t||''))+'</span></div>'+status+'</div><div class="live-items"><div class="live-items-label">ITEMS SOLD · '+(s.l||[]).reduce((a,l)=>a+(Number(l.q)||0),0)+' unit(s)</div><ul>'+lines+'</ul></div><div class="live-sale-bottom"><span class="mu">Cashier: <b>'+esc(s.by||'—')+'</b></span><strong>'+M(Number(s.tot)||0)+'</strong></div>'+(s.v?'<p class="live-note">Void reason: '+esc(s.v.w||'')+(s.v.u?' · '+esc(s.v.u):'')+'</p>':'')+(s.h&&s.h.length?'<p class="live-note">Sale amended · latest change '+esc(s.h[s.h.length-1].w||'')+'</p>':'');
}
function showLiveSlide(){
 const feed=$('#liveFeed'),now=Date.now();
 liveQueue=liveQueue.filter(x=>now-x.added<LIVE_WINDOW);
 if(!liveQueue.length){liveActive='';feed.innerHTML='<div class="card live-empty"><h3>Waiting for sales</h3><p class="mu">New transactions appear here and rotate like a slideshow. Each stays on screen for up to 2 minutes.</p></div>';return}
 if(!liveQueue.some(x=>x.key===liveActive))liveActive=liveQueue[0].key;
 const item=liveQueue.find(x=>x.key===liveActive)||liveQueue[0];
 feed.innerHTML='<div class="live-slideshow"><div class="live-slide-meta"><span class="eyebrow">RECENT TRANSACTION</span><span class="mu">'+(liveQueue.indexOf(item)+1)+' / '+liveQueue.length+'</span></div>'+liveCard(item.sale)+'<div class="live-slide-controls"><button id="livePrev" type="button" aria-label="Previous sale">← Previous</button><div class="live-slide-dots">'+liveQueue.map((x,i)=>'<button type="button" class="live-slide-dot'+(x.key===item.key?' on':'')+'" data-live-key="'+esc(x.key)+'" aria-label="Show sale '+(i+1)+'"></button>').join('')+'</div><button id="liveNext" type="button">Next →</button></div></div>';
 $('#livePrev').onclick=()=>stepLive(-1);$('#liveNext').onclick=()=>stepLive(1);
 feed.querySelectorAll('[data-live-key]').forEach(b=>b.onclick=()=>{liveActive=b.dataset.liveKey;showLiveSlide()});
}
function stepLive(delta){if(!liveQueue.length)return;const i=liveQueue.findIndex(x=>x.key===liveActive);liveActive=liveQueue[(i+delta+liveQueue.length)%liveQueue.length].key;showLiveSlide()}
function drawLive(){
 const sales=[...(S.s||[])].slice(-100).reverse(),today=(S.s||[]).filter(s=>s.d===T&&!s.v);
 $('#liveCount').textContent=today.length.toLocaleString('en-PH');
 $('#liveRevenue').textContent=M(today.reduce((a,s)=>a+(Number(s.tot)||0),0));
 $('#liveLatest').textContent=sales.length?(sales[0].t||sales[0].d):'No sales yet';
 const now=Date.now();
 // Track observed transactions separately so expired sales cannot re-enter the slideshow on the next poll.
 sales.slice().reverse().forEach(s=>{const key=liveKey(s);if(!liveSeen.has(key)){liveQueue.push({key,sale:s,added:now});liveSeen.add(key)}});
 liveQueue=liveQueue.filter(x=>now-x.added<LIVE_WINDOW).slice(-100);
 if(liveFirstDraw){liveFirstDraw=false;if(liveQueue.length)liveActive=liveQueue[liveQueue.length-1].key;showLiveSlide()}
 else if(!liveQueue.some(x=>x.key===liveActive))showLiveSlide();
}
async function refreshLive(){
 if(liveBusy||!ME)return;liveBusy=true;
 try{const r=await load();if(r.error){liveStatus('Connection issue',false);return}drawLive();liveStatus('Live · updated '+new Date().toLocaleTimeString('en-PH',{hour:'2-digit',minute:'2-digit',second:'2-digit'}),true)}
 catch(e){liveStatus('Connection issue',false)}finally{liveBusy=false}
}
$('#liveRefresh').onclick=refreshLive;
if(liveTimer)clearInterval(liveTimer);
liveTimer=setInterval(()=>{if(tab==='live')stepLive(1)},LIVE_SLIDE_MS);
