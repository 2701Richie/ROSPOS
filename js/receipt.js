// receipt.js: 58 mm receipt (32 columns). One model (rcptBlocks) feeds the on-screen slip, the ESC/POS bytes sent to RawBT, and browser print.
// Printed text is plain ASCII on purpose: cheap 58 mm printers cannot print the peso sign or accented letters.
const RC_W=32;
function rcPlain(v){return String(v==null?'':v).normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/\u20b1/g,'PHP ').replace(/[\u2018\u2019]/g,"'").replace(/[\u201c\u201d]/g,'"').replace(/[\u2013\u2014\u2212]/g,'-').replace(/\s+/g,' ').replace(/[^\x20-\x7e]/g,'?').trim()}
function rcMoney(n){const v=Math.round(Number(n)*100)/100,p=Math.abs(v).toFixed(2).split('.');return(v<0?'-':'')+p[0].replace(/\B(?=(\d{3})+(?!\d))/g,',')+'.'+p[1]}
function rcWrap(t,w){const out=[];let cur='';for(let word of rcPlain(t).split(' ')){if(!word)continue;while(word.length>w){if(cur){out.push(cur);cur=''}out.push(word.slice(0,w));word=word.slice(w)}if(!cur)cur=word;else if((cur+' '+word).length<=w)cur+=' '+word;else{out.push(cur);cur=word}}if(cur)out.push(cur);return out}
function rcRow(l,r,w){w=w||RC_W;l=(String(l).match(/^ */)[0])+rcPlain(l);r=rcPlain(r).slice(-w);if(l.length+1+r.length<=w)return[l+' '.repeat(w-l.length-r.length)+r];const rows=rcWrap(l,w)||[''],last=rows[rows.length-1]||'';if(rows.length&&last.length+1+r.length<=w)rows[rows.length-1]=last+' '.repeat(w-last.length-r.length)+r;else rows.push(' '.repeat(w-r.length)+r);return rows}
// Blocks are printed lines: {t:text, a:'l'|'c', b:bold, s:0 normal | 1 double height | 2 double width and height (16 columns)}
function rcptBlocks(s,c){c=Object.assign({},typeof cfg==='function'?cfg():{},c||{});const out=[],W=RC_W;
 const add=(t,o)=>{o=o||{};for(const x of rcWrap(t,o.s===2?W/2:W))out.push({t:x,a:o.a||'l',b:!!o.b,s:o.s||0})};
 const row=(l,r,o)=>{o=o||{};for(const x of rcRow(l,r))out.push({t:x,a:'l',b:!!o.b,s:o.s||0})};
 const sep=ch=>out.push({t:ch.repeat(W),a:'l',b:false,s:0});
 const name=rcPlain(c.store)||'ROSPOS';add(name,{a:'c',b:true,s:name.length<=W/2?2:name.length<=W?1:0});
 if(rcPlain(c.rc_addr))add(c.rc_addr,{a:'c'});if(rcPlain(c.rc_phone))add(c.rc_phone,{a:'c'});if(rcPlain(c.rc_tag))add(c.rc_tag,{a:'c'});
 sep('=');
 if(s.v)add('*** VOID ***',{a:'c',b:true,s:1});else if(s.h)add('(AMENDED)',{a:'c',b:true});
 row('Sale No.','#'+s.no);row('Date',s.d+' '+s.t);if(s.by)row('Cashier',s.by);
 sep('-');
 for(const l of s.l){add(l.n);row('  '+l.q+' x '+rcMoney(l.p),rcMoney(l.q*l.p))}
 sep('-');
 row('Items',String(s.l.reduce((a,l)=>a+l.q,0)));
 if(s.dc){row('Subtotal',rcMoney(s.sub));row(s.dl||'Discount','-'+rcMoney(s.dc))}
 row('TOTAL','PHP '+rcMoney(s.tot),{b:true,s:1});
 row('Cash',rcMoney(s.cash));row('Change',rcMoney(Math.round((s.cash-s.tot)*100)/100));
 sep('=');
 add(rcPlain(c.rc_foot)||'Thank you for your purchase!',{a:'c',b:true});add('Not an official receipt',{a:'c'});
 return out}
function rcptTestBlocks(c){c=Object.assign({},typeof cfg==='function'?cfg():{},c||{});const o=[],A=(t,x)=>o.push(Object.assign({t,a:'l',b:false,s:0},x||{}));
 A('TEST PRINT',{a:'c',b:true,s:1});A(rcPlain(c.store)||'ROSPOS',{a:'c'});A('='.repeat(RC_W));
 A('12345678901234567890123456789012');A('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef');A('Bold line',{b:true});A('Size 2',{s:2,b:true});
 for(const x of rcRow('Left','Right'))A(x);for(const x of rcRow('TOTAL','PHP 1,234.56'))A(x,{b:true,s:1});
 A('='.repeat(RC_W));A('Every line above should be',{a:'c'});A('complete and not cut off.',{a:'c'});return o}
function rcLine(b){const w=b.s===2?RC_W/2:RC_W;return b.a==='c'?' '.repeat(Math.max(0,Math.floor((w-b.t.length)/2)))+b.t:b.t}
function rcptText(bl){return bl.map(rcLine)}
function rcptBytes(bl){const o=[0x1b,0x40];let a=-1,bo=0,sz=0;for(const b of bl){const av=b.a==='c'?1:0;if(av!==a){a=av;o.push(0x1b,0x61,av)}const bv=b.b?1:0;if(bv!==bo){bo=bv;o.push(0x1b,0x45,bv)}const z=b.s===2?0x11:b.s===1?0x01:0;if(z!==sz){sz=z;o.push(0x1d,0x21,z)}for(const ch of b.t)o.push(ch.charCodeAt(0));o.push(0x0a)}
 o.push(0x1b,0x45,0,0x1d,0x21,0,0x1b,0x61,0,0x1b,0x64,4);return Uint8Array.from(o)}
function rcptUrl(bytes){let bin='';for(const x of bytes)bin+=String.fromCharCode(x);return'intent:base64,'+btoa(bin)+'#Intent;scheme=rawbt;package=ru.a402d.rawbtprinter;end;'}
function rcptHtml(bl){return'<div class="rcp">'+bl.map(b=>'<div class="rl'+(b.a==='c'?' rl-c':'')+(b.b?' rl-b':'')+(b.s?' rl-s'+b.s:'')+'">'+esc(b.a==='c'?b.t:rcLine(b))+'</div>').join('')+'</div>'}
function rcptMode(){try{return/Android/i.test(navigator.userAgent)?'raw':'browser'}catch(e){return'browser'}}
function rcptBrowser(){const st=document.createElement('style');st.textContent='@page{size:58mm auto;margin:2mm}';document.head.appendChild(st);window.addEventListener('afterprint',()=>st.remove(),{once:true});window.print()}
function rcptSend(bl,mode){const m=$('#rcm');if(mode==='raw'){try{window.location.href=rcptUrl(rcptBytes(bl));if(m)m.textContent='Sent to RawBT. If nothing prints, press Print (browser).';return}catch(e){if(m)m.textContent='Could not reach RawBT. Using browser print instead.'}}rcptBrowser()}
function rcptPopup(bl){const raw=rcptMode()==='raw';$('#rc').innerHTML=rcptHtml(bl)+'<p class="mu np" id="rcm" role="status"></p><div class="acts np"><button class="pri" id="pr">Print</button>'+(raw?'<button id="prb">Print (browser)</button>':'')+'<button id="nw">Close</button></div>';$('#md').hidden=false;$('#pr').onclick=()=>rcptSend(bl,rcptMode());if(raw)$('#prb').onclick=()=>rcptSend(bl,'browser');$('#nw').onclick=()=>{$('#md').hidden=true;const q=$('#q');if(q&&q.focus)q.focus()}}
function receipt(s){rcptPopup(rcptBlocks(s))}
