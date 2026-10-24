// sell.js: Sell tab (product grid, cart, checkout, receipt popup)
// Keep the initial grid small. Additional products are available via search or Show more.
const PRODUCT_PAGE_SIZE = 80;
let productGridLimit = PRODUCT_PAGE_SIZE;

function productMatchesSearch(query) {
  return S.p.filter(product =>
    !query || product.n.toLowerCase().includes(query)
  );
}

function productTileHTML(product) {
  const stock = tags(product) || '<small>Stock ' + product.s + '</small>';
  return `<button class="tile" data-id="${product.id}" aria-label="Add ${esc(product.n)} to sale">
    <span><b>${esc(product.n)}</b></span>
    <span><b>${M(product.p)}</b> ${stock}</span>
  </button>`;
}

function drawGrid() {
  const query = $('#q').value.trim().toLowerCase();
  const matches = productMatchesSearch(query);
  const count = $('#sellProductCount');

  if (count) {
    count.textContent = query
      ? matches.length + ' match' + (matches.length === 1 ? '' : 'es')
      : S.p.length + ' products';
  }

  const visible = matches.slice(0, productGridLimit);
  const grid = $('#grid');
  grid.innerHTML = visible.map(productTileHTML).join('') ||
    '<p class="mu sell-no-products">No matching products. Try another search.</p>';

  const remaining = matches.length - visible.length;
  if (remaining > 0) {
    const more = document.createElement('div');
    more.className = 'sell-grid-more';
    more.innerHTML = `<span>Showing ${visible.length} of ${matches.length}</span>
      <button type="button" class="sell-show-more">Show ${Math.min(remaining, PRODUCT_PAGE_SIZE)} more</button>`;
    grid.appendChild(more);
  }
}

function resetProductGrid() {
  productGridLimit = PRODUCT_PAGE_SIZE;
  drawGrid();
}

function calc(){const t=R(cart.reduce((a,l)=>a+l.q*S.p.find(p=>p.id===l.id).p,0));return{sub:t,d:0,t}}
function drawChg(){const c=parseFloat($('#cash').value),x=calc();$('#chg').textContent=isNaN(c)?'':(c>=x.t?'Change: '+M(c-x.t):'Short by '+M(x.t-c))}
function drawLines(){$('#lines').innerHTML=cart.map(l=>{const p=S.p.find(x=>x.id===l.id);return`<div class="row sell-cart-line"><div class="g"><b>${esc(p.n)}</b><div class="mu">${M(p.p)} each</div></div><div class="sell-qty-controls"><button class="q" data-a="-" data-id="${l.id}" aria-label="Decrease quantity of ${esc(p.n)}">−</button><input class="qn" data-id="${l.id}" inputmode="numeric" value="${l.q}" aria-label="Quantity of ${esc(p.n)}"><button class="q" data-a="+" data-id="${l.id}" aria-label="Increase quantity of ${esc(p.n)}">+</button></div><b class="sell-line-total">${M(l.q*p.p)}</b></div>`}).join('')||'<div class="sell-empty-cart"><span class="sell-empty-icon">＋</span><b>Your cart is empty</b><p class="mu">Choose a product to start this sale.</p></div>';const count=cart.reduce((n,l)=>n+l.q,0),cc=$('#cartCount');if(cc)cc.textContent=count+' item'+(count===1?'':'s');const x=calc();$('#tot').innerHTML=`<div class="tr t"><span>Total due</span><span>${M(x.t)}</span></div>`;drawChg()}
function add(id,k=1){const p=S.p.find(x=>x.id===id);if(!p)return false;if(p.e&&p.e<T){say('Expired. Cannot sell '+p.n);return false}const l=cart.find(x=>x.id===id),n=(l?l.q:0)+k;if(n>p.s){say('Not enough stock for '+p.n+' (only '+p.s+' in stock)');return false}say('');if(l)l.q=n;else cart.push({id,q:k});drawLines();return true}
$('#q').oninput=resetProductGrid;
$('#q').onkeydown=e=>{if(e.key!=='Enter')return;const v=e.target.value.trim();if(!v)return;const m=S.p.filter(p=>p.n.toLowerCase().includes(v.toLowerCase()));if(m.length===1){add(m[0].id);e.target.value='';drawGrid()}else say(m.length?'Several matches. Tap the product.':'No product found.')};
$('#grid').onclick=e=>{
  const more = e.target.closest('.sell-show-more');
  if (more) {
    productGridLimit += PRODUCT_PAGE_SIZE;
    drawGrid();
    return;
  }
  const tile = e.target.closest('.tile');
  if (tile) add(+tile.dataset.id);
};
$('#lines').onclick=e=>{const b=e.target.closest('button');if(!b)return;const id=+b.dataset.id,l=cart.find(x=>x.id===id),p=S.p.find(x=>x.id===id);if(b.dataset.a==='+'){if(l.q+1>p.s)return say('Not enough stock.');l.q++}else{l.q--;if(!l.q)cart=cart.filter(x=>x!==l)}say('');drawLines()};
function setQty(id,raw){const l=cart.find(x=>x.id===id),p=S.p.find(x=>x.id===id);if(!l||!p)return;const t=String(raw).trim(),v=parseInt(t);
if(t===''||v===0){cart=cart.filter(x=>x!==l);say('')}else if(isNaN(v)||v<0)say('Type a whole number for the quantity.');else if(v>p.s){l.q=p.s;say('Only '+p.s+' in stock for '+p.n+'.')}else{l.q=v;say('')}drawLines()}
$('#lines').onchange=e=>{const t=e.target;if(t.classList&&t.classList.contains('qn'))setQty(+t.dataset.id,t.value)};
$('#lines').onfocusin=e=>{const t=e.target;if(t.classList&&t.classList.contains('qn')&&t.select)t.select()};
$('#cash').oninput=drawChg;
$('#clr').onclick=()=>{cart=[];$('#cash').value='';say('');drawLines()};
let payRid=null,paySig='';
function rid(){return(window.crypto&&crypto.randomUUID)?crypto.randomUUID():Date.now().toString(36)+Math.random().toString(36).slice(2)+Math.random().toString(36).slice(2)}
$('#pay').onclick=async()=>{const b=$('#pay');if(b.disabled)return;if(!cart.length)return say('Add a product first.');const c=parseFloat($('#cash').value),x=calc();if(!isNaN(c)&&c<x.t)return say('Cash received is less than the total.');
const sig=JSON.stringify([cart.map(l=>[l.id,l.q]),isNaN(c)?null:c]);if(!payRid||sig!==paySig){payRid=rid();paySig=sig}
b.disabled=true;const r=await api('/api/sale',{lines:cart.map(l=>({id:l.id,q:l.q})),cash:isNaN(c)?null:c,rid:payRid});b.disabled=false;
if(r.error){if(!/^Cannot reach/.test(r.error))payRid=null;await load();clampCart();drawGrid();drawLines();return say(r.error)}
payRid=null;receipt(r.sale);cart=[];$('#cash').value='';say('');drawLines();drawGrid()};
function clampCart(){cart.forEach(l=>{const c=S.p.find(x=>x.id===l.id);if(c&&l.q>c.s)l.q=c.s});cart=cart.filter(l=>S.p.some(p=>p.id===l.id)&&l.q>0)}
