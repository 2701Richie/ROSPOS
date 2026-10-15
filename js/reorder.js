// reorder.js: Reorder tab (what to order, order list as print/PDF and CSV)
let rQ={},rX={};
function margin(){try{const v=parseFloat(localStorage.getItem('pos-margin'));return isNaN(v)?25:v}catch(e){return 25}}
function sug(p){return Math.max(1,2*p.m-p.s)}
function sold30(){const d=new Date(T+'T00:00:00');d.setDate(d.getDate()-30);const from=d.toLocaleDateString('en-CA'),m={};S.s.forEach(s=>{if(s.v||s.d<from)return;s.l.forEach(l=>{const k=l.id||l.n;m[k]=(m[k]||0)+l.q})});return m}
function lists(){const mg=margin()/100,sold=sold30(),by=(a,b)=>a.r-b.r||a.p.n.localeCompare(b.p.n),all=S.p.filter(p=>p.m>0).map(p=>({p,r:p.s/p.m,sold:(sold[p.id]||0)+(sold[p.n]||0)}));
return{now:all.filter(x=>x.p.s<=x.p.m).sort(by),low:all.filter(x=>x.p.s>x.p.m&&x.p.s<=x.p.m*(1+mg)).sort(by),none:S.p.filter(p=>!(p.m>0)).length}}
function badge(){const b=$('#rdrb');if(!b)return;const n=lists().now.length;b.textContent=n?'Reorder ('+n+')':'Reorder'}
function rrow(x,isNow){const p=x.p,q=rQ[p.id]??sug(p),inc=rX[p.id]??isNow;return`<tr><td><input type="checkbox" class="ri" data-id="${p.id}"${inc?' checked':''} aria-label="Include ${esc(p.n)} in the order"></td><td>${esc(p.n)}${p.s<=0?' <span class="tag b">Out of stock</span>':''}</td><td>${p.s}</td><td>${p.m}</td><td>${x.sold}</td><td><input class="rn" data-id="${p.id}" inputmode="numeric" value="${q}" style="width:84px" aria-label="Order quantity for ${esc(p.n)}"></td></tr>`}
function drawRdr(){const l=lists(),t=(rows,n)=>rows.length?rows.map(x=>rrow(x,n)).join(''):'<tr><td colspan="6" class="mu">Nothing here.</td></tr>';
$('#rn1').innerHTML=t(l.now,true);$('#rn2').innerHTML=t(l.low,false);$('#rmg').value=margin();
$('#rnone').textContent=l.none?l.none+(l.none>1?' products have':' product has')+' no reorder level set, so they never appear here. Set one on the Products tab or import it with a CSV file.':''}
function picked(){const l=lists(),rows=[];[...l.now,...l.low].forEach(x=>{const p=x.p,q=parseInt(rQ[p.id]??sug(p)),inc=rX[p.id]??(p.s<=p.m);if(inc&&q>0)rows.push({n:p.n,q})});return rows.sort((a,b)=>a.n.localeCompare(b.n))}
$('#v-rdr').onchange=e=>{const t=e.target;if(t.id==='rmg'){const v=parseFloat(t.value);try{localStorage.setItem('pos-margin',isNaN(v)||v<0?25:v)}catch(x){}drawRdr();badge()}else if(t.classList.contains('ri'))rX[t.dataset.id]=t.checked;else if(t.classList.contains('rn')){const v=t.value.trim();if(/^\d+$/.test(v))rQ[t.dataset.id]=+v;else t.value=rQ[t.dataset.id]??sug(S.p.find(p=>p.id==t.dataset.id))}};
$('#rpr').onclick=()=>{const r=picked(),m=$('#rmsg'),c='border:1px solid #000;padding:6px;text-align:left';if(!r.length){m.textContent='Tick at least one product with a quantity.';return}m.textContent='';
$('#op').innerHTML=`<h2 style="margin:0 0 4px">ROSPOS: Order List</h2><p style="margin:0 0 12px">${T}</p><table style="width:100%;border-collapse:collapse"><thead><tr><th style="${c};width:40px">#</th><th style="${c}">Product Name</th><th style="${c};width:90px">Quantity</th><th style="${c};width:110px">Price</th></tr></thead><tbody>${r.map((x,i)=>`<tr><td style="${c}">${i+1}</td><td style="${c}">${esc(x.n)}</td><td style="${c}">${x.q}</td><td style="${c}"></td></tr>`).join('')}</tbody></table>`;
document.body.classList.add('po');window.addEventListener('afterprint',()=>document.body.classList.remove('po'),{once:true});window.print()};
$('#rcsv').onclick=()=>{const r=picked(),m=$('#rmsg');if(!r.length){m.textContent='Tick at least one product with a quantity.';return}m.textContent='';saveCsv('order-list.csv',[['#','Product Name','Quantity','Price'],...r.map((x,i)=>[i+1,x.n,x.q,''])])};
