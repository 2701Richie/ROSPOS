const REORDER_ROWS_PER_PAGE=80;
let reorderPage=0;
let reorderSalesSummary=null, reorderSalesSession=0;

async function refreshReorderHistory() {
  const request=++reorderSalesSession;
  const session=typeof sessionRevision==='undefined'?null:sessionRevision;
  $('#reorderHistoryStatus').textContent='Checking archived sales…';
  const result=await api('/api/reorder-sales');
  if(request!==reorderSalesSession || tab!=='rdr' || !ME ||
      (session!==null && session!==sessionRevision)) return;
  if(result.error) {
    reorderSalesSummary=null;
    $('#reorderHistoryStatus').textContent='30-day sales history unavailable; recent sales only.';
  } else {
    reorderSalesSummary=result;
    $('#reorderHistoryStatus').textContent=result.unavailable.length
      ? 'Some archived days could not be read; 30-day quantities may be incomplete.'
      : 'Sold quantities include the last 30 calendar days, including archived transactions.';
  }
  drawRdr();
}

// reorder.js: Reorder list with supplier price comparison and supplier-specific order sheets.
let rQ={},rX={};
function margin(){try{const v=parseFloat(localStorage.getItem('pos-margin'));return isNaN(v)?25:v}catch(e){return 25}}
function sug(p){return Math.max(1,2*p.m-p.s)}
function sold30(){
  if(reorderSalesSummary && reorderSalesSummary.today===T)
    return reorderSalesSummary.quantities;
  const d=new Date(T+'T00:00:00');
  d.setDate(d.getDate()-29);
  const from=d.toLocaleDateString('en-CA'),m={};
  for(const s of S.s||[]){
    if(s.v || s.d<from || s.d>T)continue;
    for(const l of s.l||[]){
      const k=l.id??l.n;
      m[k]=(m[k]||0)+Number(l.q||0);
    }
  }
  return m;
}
// Retain the latest recorded unit cost for each product/supplier pair.
function supplierPriceMap() {
  const latest = new Map();
  const suppliers = S.suppliers || [];

  for (const purchase of S.purchases || []) {
    if (purchase.supplier_id == null || purchase.product_id == null) continue;
    if (!Number.isFinite(Number(purchase.unit_cost))) continue;

    const key = String(purchase.product_id) + '|' + String(purchase.supplier_id);
    const previous = latest.get(key);
    const newerDate = !previous || String(purchase.date || '') > String(previous.date || '');
    const newerTime = previous &&
      purchase.date === previous.date &&
      String(purchase.created_at || '') > String(previous.created_at || '');
    if (!newerDate && !newerTime) continue;

    const supplier = suppliers.find(row => String(row.id) === String(purchase.supplier_id));
    latest.set(key, {
      supplier_id: String(purchase.supplier_id),
      supplier_name: purchase.supplier_name || supplier?.name || 'Unknown supplier',
      cost: Number(purchase.unit_cost),
      date: purchase.date || '',
    });
  }
  return latest;
}
function bestPrice(p,map){return [...map.entries()].filter(([k])=>k.startsWith(String(p.id)+'|')).map(([,v])=>v).sort((a,b)=>a.cost-b.cost||a.supplier_name.localeCompare(b.supplier_name))[0]||null}
function fillReorderSuppliers(){const el=$('#rSupplier');if(!el)return;const current=el.value;el.innerHTML='<option value="">All suppliers · all products</option>'+(S.suppliers||[]).slice().sort((a,b)=>a.name.localeCompare(b.name)).map(s=>'<option value="'+esc(s.id)+'">'+esc(s.name)+'</option>').join('');if((S.suppliers||[]).some(s=>String(s.id)===current))el.value=current}
// Classify only products eligible for reorder; use the same categories in every view.
function lists() {
  const threshold = 1 + margin() / 100;
  const sales = sold30();
  const candidates = (S.p || [])
    .filter(product => product.m > 0 || product.s === 0)
    .map(product => ({
      p: product,
      r: product.m > 0 ? product.s / product.m : -1,
      sold: (sales[product.id] || 0) + (sales[product.n] || 0),
    }));
  const byUrgency = (a, b) => a.r - b.r || a.p.n.localeCompare(b.p.n);

  return {
    now: candidates.filter(row => row.p.s <= row.p.m).sort(byUrgency),
    low: candidates
      .filter(row => row.p.s > row.p.m && row.p.s <= row.p.m * threshold)
      .sort(byUrgency),
    none: (S.p || []).filter(product => !(product.m > 0) && product.s > 0).length,
  };
}
function badge(){const b=$('#rdrb');if(!b)return;const n=lists().now.length;b.title=n?'Reorder ('+n+' need attention)':'Reorder';b.setAttribute?.('aria-label',b.title);const label=b.querySelector?.('.sidebar-label');if(label)label.textContent=n?'Reorder ('+n+')':'Reorder';else b.textContent=n?'Reorder ('+n+')':'Reorder'}
function defaultReorderIncluded(p){const mg=margin()/100;return p.s<=p.m||(p.m>0&&p.s>p.m&&p.s<=p.m*(1+mg))}
function reorderRows(){const l=lists(),sid=$('#rSupplier')?.value||'',prices=supplierPriceMap(),supplier=(S.suppliers||[]).find(s=>String(s.id)===sid);const rows=[...l.now,...l.low].map(x=>({...x,price:sid?(prices.get(String(x.p.id)+'|'+sid)||null):bestPrice(x.p,prices)}));return{...l,rows,sid,supplierName:supplier?.name||''}}
function visibleReorderRows(rows){const q=String($('#rSearch')?.value||'').trim().toLocaleLowerCase();if(!q)return rows;const l=reorderRows();if(!l.sid)return rows.filter(x=>String(x.p.n||'').toLocaleLowerCase().includes(q));const sold=sold30(),prices=supplierPriceMap(),sid=l.sid;return(S.p||[]).filter(p=>String(p.n||'').toLocaleLowerCase().includes(q)).map(p=>({p,r:p.m>0?p.s/p.m:-1,sold:(sold[p.id]||0)+(sold[p.n]||0),price:prices.get(String(p.id)+'|'+sid)||null,searchResult:true})).sort((a,b)=>a.p.n.localeCompare(b.p.n))}
function rrow(x){const p=x.p,isNow=p.s<=p.m,isLow=p.m>0&&p.s>p.m&&p.s<=p.m*(1+margin()/100),q=rQ[p.id]??sug(p),sid=$('#rSupplier')?.value||'',inc=sid?!!rX[p.id]:(rX[p.id]===undefined?defaultReorderIncluded(p):!!rX[p.id]),price=x.price,supplierName=sid?((S.suppliers||[]).find(s=>String(s.id)===sid)||{name:'Selected supplier'}).name:(price?price.supplier_name:'No price on record'),selector=sid?(x.searchResult?'<button type="button" class="radd" data-id="'+esc(p.id)+'">'+(inc?'Remove':'Add to order')+'</button>':'<input type="checkbox" class="ri" data-id="'+esc(p.id)+'"'+(inc?' checked':'')+' aria-label="Include '+esc(p.n)+' in the order">'):'<input type="checkbox" class="ri" data-id="'+esc(p.id)+'"'+(inc?' checked':'')+' aria-label="Include '+esc(p.n)+' in the order">'; return'<tr><td class="reorder-check-col">'+selector+'</td><td class="reorder-product-name">'+esc(p.n)+'</td><td>'+(p.s<=0?'<span class="tag b">Out of stock</span>':isNow?'<span class="tag b">Reorder now</span>':isLow?'<span class="tag w">Getting low</span>':'<span class="tag">Stock okay</span>')+'</td><td class="reorder-num">'+p.s+'</td><td class="reorder-num">'+p.m+'</td><td class="reorder-num">'+x.sold+'</td><td><input class="rn" data-id="'+esc(p.id)+'" inputmode="numeric" value="'+q+'" aria-label="Order quantity for '+esc(p.n)+'"></td><td>'+esc(supplierName)+'</td><td class="reorder-num">'+(price?M(price.cost):'—')+'</td></tr>'}
function reorderDisplayRows(list, matches) {
  const prices = supplierPriceMap();
  const sales = sold30();
  const byId = new Map(matches.map(row => [String(row.p.id), row]));
  const products = list.sid
    ? (S.p || []).filter(product => !!rX[product.id])
    : matches.map(row => row.p);

  return products.map(product => {
    const row = byId.get(String(product.id)) || {
      p: product,
      r: product.m > 0 ? product.s / product.m : -1,
      sold: (sales[product.id] || 0) + (sales[product.n] || 0),
    };
    return {
      ...row,
      price: list.sid
        ? prices.get(String(product.id) + '|' + list.sid) || null
        : bestPrice(product, prices),
    };
  }).sort((a, b) => a.p.n.localeCompare(b.p.n));
}

function renderReorderSearchResults(matches, query, supplierId) {
  const panel = $('#rsearchResults');
  if (!panel) return;
  panel.hidden = !query || !supplierId;
  if (!query || !supplierId) {
    panel.innerHTML = '';
    return;
  }
  panel.innerHTML = matches.length
    ? '<div class="reorder-search-results-head">Matching products — press Add to order</div>' +
      matches.slice(0,REORDER_ROWS_PER_PAGE).map(row => `<div class="reorder-search-result">
        <span><strong>${esc(row.p.n)}</strong>
          <small>Stock: ${row.p.s} · Min: ${row.p.m}</small></span>
        <button type="button" class="radd" data-id="${esc(row.p.id)}">
          ${rX[row.p.id] ? 'Remove from order' : 'Add to order'}
        </button></div>`).join('')
      +(matches.length>REORDER_ROWS_PER_PAGE?'<p class="mu">Showing first '+REORDER_ROWS_PER_PAGE+' of '+matches.length+' matches. Refine your search for more.</p>':'')
    : '<p class="mu">No matching products.</p>';
}

function drawRdr() {
  fillReorderSuppliers();
  const list = reorderRows();
  const matches = visibleReorderRows(list.rows);
  const query = String($('#rSearch')?.value || '').trim();
  const rows = reorderDisplayRows(list, matches);

  renderReorderSearchResults(matches, query, list.sid);
  reorderPage=Math.min(reorderPage,Math.max(0,Math.ceil(rows.length/REORDER_ROWS_PER_PAGE)-1));
  const offset=reorderPage*REORDER_ROWS_PER_PAGE;
  $('#reorderPrev').disabled=reorderPage===0;
  $('#reorderNext').disabled=offset+REORDER_ROWS_PER_PAGE>=rows.length;
  $('#reorderPageInfo').textContent='Page '+(reorderPage+1)+' of '+Math.max(1,Math.ceil(rows.length/REORDER_ROWS_PER_PAGE));
  $('#reorderRows').innerHTML = rows.length
    ? rows.slice(offset,offset+REORDER_ROWS_PER_PAGE).map(rrow).join('')
    : `<tr><td colspan="9" class="mu reorder-empty">${
        list.sid ? 'No items added yet. Search above and press Add to order.'
        : query ? 'No matching restock items.' : 'No items currently need restocking.'
      }</td></tr>`;

  $('#rmg').value = margin();
  const threshold = 1 + margin() / 100;
  const urgent = rows.filter(row => row.p.s <= row.p.m).length;
  const low = rows.filter(row =>
    row.p.m > 0 && row.p.s > row.p.m && row.p.s <= row.p.m * threshold
  ).length;
  $('#rstats').innerHTML = `<div class="reorder-stat urgent">
    <span>Reorder now</span><strong>${urgent}</strong></div>
    <div class="reorder-stat"><span>Getting low</span><strong>${low}</strong></div>
    <div class="reorder-stat"><span>Selected items</span>
      <strong id="rselectedCount">${picked().length}</strong></div>`;
  $('#rrowcount').textContent = rows.length +
    (list.sid ? ' selected item' : ' restock item') +
    (rows.length === 1 ? '' : 's');
  updateReorderSelection();
  $('#rnone').textContent = list.none
    ? list.none + (list.none > 1 ? ' products have' : ' product has') +
      ' no reorder level set and are excluded. Set a minimum on the Products tab.'
    : '';
}
// Generate the printable/exportable order from explicit selections and quantities.
function picked() {
  const { sid, supplierName } = reorderRows();
  const prices = supplierPriceMap();
  const selected = [];

  for (const product of S.p || []) {
    const quantity = parseInt(rQ[product.id] ?? sug(product));
    const included = sid
      ? !!rX[product.id]
      : rX[product.id] === undefined
        ? defaultReorderIncluded(product)
        : !!rX[product.id];
    if (!included || quantity <= 0) continue;

    const price = sid
      ? prices.get(String(product.id) + '|' + sid)
      : bestPrice(product, prices);

    selected.push({
      n: product.n,
      q: quantity,
      supplier: sid ? supplierName || 'Selected supplier' : price?.supplier_name || '',
      cost: price?.cost ?? '',
      supplier_id: sid || price?.supplier_id || '',
    });
  }

  return selected.sort((a, b) => a.n.localeCompare(b.n));
}
$('#rSupplier').onchange=()=>{reorderPage=0;drawRdr()};
$('#rSearch').oninput=()=>{reorderPage=0;drawRdr()};
$('#reorderPrev').onclick=()=>{if(reorderPage>0){reorderPage--;drawRdr()}};
$('#reorderNext').onclick=()=>{reorderPage++;drawRdr()};
$('#v-rdr').onclick=e=>{const b=e.target.closest('.radd');if(!b)return;const id=b.dataset.id;rX[id]=!rX[id];drawRdr()};
$('#v-rdr').onchange=e=>{const t=e.target;if(t.id==='rmg'){const v=parseFloat(t.value);try{localStorage.setItem('pos-margin',isNaN(v)||v<0?25:v)}catch(x){}drawRdr();badge()}else if(t.classList.contains('ri')){rX[t.dataset.id]=t.checked;drawRdr()}else if(t.classList.contains('rn')){const v=t.value.trim();if(/^\d+$/.test(v))rQ[t.dataset.id]=+v;else t.value=rQ[t.dataset.id]??sug((S.p||[]).find(p=>String(p.id)===t.dataset.id));updateReorderSelection()}};
function updateReorderSelection(){const n=picked().length,e=$('#rselected');if(e){const s=$('#rSupplier')?.selectedOptions?.[0]?.textContent||'';e.textContent=n+' item'+(n===1?'':'s')+' selected · '+(($('#rSupplier')?.value)?'order assigned to '+s:'restock items selected by default')+' · sorted A–Z'}const c=$('#rselectedCount');if(c)c.textContent=n}
function orderTitle(){const s=$('#rSupplier'),chosen=s?.value?s.selectedOptions[0]?.textContent:'';return chosen||'Supplier order list'}
$('#rpr').onclick=()=>{const r=picked(),m=$('#rmsg');if(!r.length){m.textContent='Add at least one product to the order first.';return}m.textContent='';const c=typeof cfg==='function'?cfg():{},known=r.filter(x=>x.cost!==''&&Number.isFinite(Number(x.cost))),total=known.reduce((sum,x)=>sum+Number(x.cost)*x.q,0),allCostsKnown=known.length===r.length,fmt=v=>'₱'+Number(v).toLocaleString('en-PH',{minimumFractionDigits:2,maximumFractionDigits:2}),date=String(T||new Date().toISOString().slice(0,10)),orderNo='RO-'+date.replace(/-/g,'')+'-'+String(Date.now()).slice(-4),supplierLabel='',rows=r.map((x,i)=>'<tr><td class="po-no">'+(i+1)+'</td><td>'+esc(x.n)+'</td><td class="po-qty">'+x.q+'</td><td class="po-write-cost">&nbsp;</td><td class="po-write-cost">&nbsp;</td></tr>').join('');$('#op').innerHTML='<article class="po-document"><header class="po-brand"><img src="/logo.svg" alt="ROSPOS"><div class="po-brand-name">'+esc(storeName()||'ROSPOS')+'<small>ORDER LIST</small></div><div class="po-date"><span>Order reference</span><strong>'+esc(orderNo)+'</strong><span>Date</span><strong>'+esc(date)+'</strong></div></header><table class="po-items"><thead><tr><th>#</th><th>Product</th><th class="po-qty">Qty</th><th class="po-money">Unit cost</th><th class="po-money">Total</th></tr></thead><tbody>'+rows+'</tbody></table><div class="po-total"><span>'+r.length+' products</span><strong>Supplier to complete pricing</strong></div>'+'<footer class="po-footer">'+(c.rc_addr?esc(c.rc_addr)+' · ':'')+(c.rc_phone?esc(c.rc_phone):'')+'</footer></article>';document.body.classList.add('po');window.addEventListener('afterprint',()=>document.body.classList.remove('po'),{once:true});window.print()};
$('#rcsv').onclick=()=>{const r=picked(),m=$('#rmsg');if(!r.length){m.textContent='Tick at least one product with a quantity.';return}m.textContent='';saveCsv('order-list.csv',[['#','Product Name','Quantity','Supplier','Latest unit cost'],...r.map((x,i)=>[i+1,x.n,x.q,x.supplier,x.cost])])};
