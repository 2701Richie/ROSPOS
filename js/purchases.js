// purchases.js: supplier purchase ledger, product history, and supplier price comparison.
let purchaseSort={key:'date',dir:-1},purchaseEditing=null,purchaseToastTimer=null;
function purchaseRows(){return Array.isArray(S.purchases)?S.purchases:[]}
function supplierRows(){return Array.isArray(S.suppliers)?S.suppliers:[]}
function purchaseDateToday(){return (S&&S.today)||T||ds(0)}
function purchaseToast(message,error=false){const el=$('#purchaseToast');if(!el)return;el.textContent=message;el.classList.toggle('is-error',error);el.hidden=false;clearTimeout(purchaseToastTimer);purchaseToastTimer=setTimeout(()=>{el.hidden=true},3800)}
function setPurchaseView(view){['list','recent','compare'].forEach(v=>{const panel=$('#purchaseView'+v[0].toUpperCase()+v.slice(1));if(panel)panel.hidden=v!==view;const b=document.querySelector('[data-purchase-view="'+v+'"]');if(b){b.classList.toggle('on',v===view);b.setAttribute('aria-selected',v===view?'true':'false')}});if(view==='recent')drawRecentPurchases();if(view==='compare')drawSupplierComparison()}
document.querySelectorAll('[data-purchase-view]').forEach(b=>b.addEventListener('click',()=>setPurchaseView(b.dataset.purchaseView)));
// Keep purchase filtering and sorting independent from HTML generation.
function filteredPurchases() {
  const query = $('#purchaseQ').value.trim().toLocaleLowerCase();
  const from = $('#purchaseFrom').value;
  const to = $('#purchaseTo').value;
  const numeric = ['quantity', 'unit_cost', 'total'];

  return purchaseRows()
    .filter(row =>
      (!query ||
        String(row.product_name || '').toLocaleLowerCase().includes(query) ||
        String(row.supplier_name || '').toLocaleLowerCase().includes(query)) &&
      (!from || row.date >= from) &&
      (!to || row.date <= to)
    )
    .sort((a, b) => {
      const key = purchaseSort.key;
      if (numeric.includes(key)) {
        return ((Number(a[key]) || 0) - (Number(b[key]) || 0)) * purchaseSort.dir;
      }
      return String(a[key] || '').localeCompare(String(b[key] || ''), 'en', {
        numeric: true,
        sensitivity: 'base',
      }) * purchaseSort.dir;
    });
}

function purchaseRowHTML(row) {
  return `<tr>
    <td data-label="Date">${esc(row.date || '—')}</td>
    <td data-label="Product"><strong>${esc(row.product_name || productName(row.product_id))}</strong></td>
    <td data-label="Supplier">${esc(row.supplier_name || '—')}</td>
    <td data-label="Quantity">${Number(row.quantity) || 0}</td>
    <td data-label="Unit cost">${M(Number(row.unit_cost) || 0)}</td>
    <td data-label="Total"><strong>${M(Number(row.total) || 0)}</strong></td>
    <td data-label="Expiry date">${esc(row.expiry_date || 'Not recorded')}</td>
    <td data-label="Actions"><div class="purchase-row-actions">
      <button type="button" data-purchase-edit="${esc(row.id)}">Edit</button>
      <button type="button" class="purchase-delete" data-purchase-delete="${esc(row.id)}">Delete</button>
    </div></td>
  </tr>`;
}

function drawPurchases() {
  if (!$('#purchaseRows')) return;

  const rows = filteredPurchases();
  $('#purchaseCount').textContent =
    rows.length.toLocaleString('en-PH') + ' purchase' + (rows.length === 1 ? '' : 's');
  $('#purchaseEmpty').hidden = rows.length > 0 || purchaseRows().length > 0;
  $('#purchaseRows').innerHTML = rows.map(purchaseRowHTML).join('');
}
function productName(id){const p=(S.p||[]).find(x=>String(x.id)===String(id));return p?p.n:'Deleted product'}
['purchaseQ','purchaseFrom','purchaseTo'].forEach(id=>{const el=$('#'+id);if(el)el.addEventListener(id==='purchaseQ'?'input':'change',drawPurchases)});
$('#purchaseClear').onclick=()=>{$('#purchaseQ').value=$('#purchaseFrom').value=$('#purchaseTo').value='';drawPurchases()};
document.querySelectorAll('[data-purchase-sort]').forEach(b=>b.addEventListener('click',()=>{const key=b.dataset.purchaseSort;if(purchaseSort.key===key)purchaseSort.dir*=-1;else purchaseSort={key,dir:key==='date'?-1:1};drawPurchases()}));
$('#purchaseEmptyAdd').onclick=()=>openPurchaseDialog();$('#purchaseAdd').onclick=()=>openPurchaseDialog();
function productMatches(q){q=String(q||'').trim().toLocaleLowerCase();return (S.p||[]).filter(p=>!q||String(p.n||'').toLocaleLowerCase().includes(q)||String(p.id).toLocaleLowerCase().includes(q)).slice(0,30)}
function productOptionHTML(p){return `<button type="button" class="purchase-option" data-product-option="${esc(p.id)}"><span class="purchase-option-name">${esc(p.n)}</span><small>SKU / ID ${esc(p.id)} · Stock ${Number(p.s)||0}</small></button>`}
function bindProductPicker(inputId,optionsId,onSelect,selectedId=null){const input=$('#'+inputId),box=$('#'+optionsId);if(!input||!box)return;const draw=()=>{const found=productMatches(input.value);box.innerHTML=found.map(productOptionHTML).join('')||(input.value.trim()?'<div class="purchase-option-empty">No products found</div>':'<div class="purchase-option-empty">Type to search products</div>');box.hidden=false};input.oninput=draw;input.onfocus=draw;input.onkeydown=e=>{if(e.key==='Escape'){box.hidden=true;return}if(e.key==='ArrowDown'){const first=box.querySelector('[data-product-option]');if(first){e.preventDefault();first.focus()}}};box.onclick=e=>{const b=e.target.closest('[data-product-option]');if(!b)return;const p=(S.p||[]).find(x=>String(x.id)===b.dataset.productOption);if(!p)return;input.value=p.n;box.hidden=true;onSelect(p)};box.onkeydown=e=>{const b=e.target.closest('[data-product-option]');if(!b)return;const opts=[...box.querySelectorAll('[data-product-option]')],i=opts.indexOf(b);if(e.key==='ArrowDown'){e.preventDefault();opts[Math.min(i+1,opts.length-1)]?.focus()}else if(e.key==='ArrowUp'){e.preventDefault();(opts[i-1]||input).focus()}else if(e.key==='Enter'){e.preventDefault();b.click()}else if(e.key==='Escape'){box.hidden=true;input.focus()}};document.addEventListener('click',e=>{if(!input.contains(e.target)&&!box.contains(e.target))box.hidden=true})}
function showSelectedProduct(containerId,p,onClear){const el=$('#'+containerId);if(!el)return;el.innerHTML=`<span>${esc(p.n)}</span><button type="button" aria-label="Clear selected product">×</button>`;el.hidden=false;el.querySelector('button').onclick=()=>{el.hidden=true;onClear()}}
let purchaseSelectedProduct=null;
bindProductPicker('purchaseProductQ','purchaseProductOptions',p=>{purchaseSelectedProduct=p;showSelectedProduct('purchaseProductSelected',p,()=>{purchaseSelectedProduct=null;$('#purchaseProductQ').hidden=false;$('#purchaseProductQ').value='';$('#purchaseProductQ').focus()});$('#purchaseProductQ').hidden=true;$('#purchaseProductError').textContent='';if(p.c!=null&&purchaseEditing===null&&$('#purchaseUnitCost').value==='')$('#purchaseUnitCost').value=p.c;updatePurchaseTotal()});
function fillSupplierSelect(selected=''){const s=$('#purchaseSupplier');s.innerHTML='<option value="">Select supplier…</option>'+supplierRows().slice().sort((a,b)=>a.name.localeCompare(b.name)).map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');s.value=selected||''}
function updatePurchaseTotal(){const q=Number($('#purchaseQty').value),c=Number($('#purchaseUnitCost').value);$('#purchaseTotal').textContent=M(Number.isFinite(q)&&q>0&&Number.isFinite(c)&&c>=0?q*c:0)}
$('#purchaseDate').onchange=()=>{$('#purchaseExpiryDate').min=$('#purchaseDate').value||purchaseDateToday()};$('#purchaseQty').oninput=updatePurchaseTotal;$('#purchaseUnitCost').oninput=updatePurchaseTotal;$('#purchaseQtyDown').onclick=()=>{$('#purchaseQty').value=Math.max(1,(parseInt($('#purchaseQty').value,10)||1)-1);updatePurchaseTotal()};$('#purchaseQtyUp').onclick=()=>{$('#purchaseQty').value=Math.min(100000000,(parseInt($('#purchaseQty').value,10)||1)+1);updatePurchaseTotal()};
$('#purchaseNewSupplierToggle').onclick=()=>{$('#purchaseNewSupplierBox').hidden=!$('#purchaseNewSupplierBox').hidden;if(!$('#purchaseNewSupplierBox').hidden)$('#purchaseNewSupplierName').focus()};
$('#purchaseNewSupplierSave').onclick=async()=>{const name=$('#purchaseNewSupplierName').value.trim(),m=$('#purchaseNewSupplierError');m.textContent='';if(!name){m.textContent='Enter a supplier name.';return}const btn=$('#purchaseNewSupplierSave');btn.disabled=true;const r=await api('/api/supplier',{name});btn.disabled=false;if(r.error){m.textContent=r.error;return}fillSupplierSelect(r.supplier.id);$('#purchaseNewSupplierName').value='';$('#purchaseNewSupplierBox').hidden=true;purchaseToast(r.msg||'Supplier added.')};
$('#purchaseNoteToggle').onclick=()=>{const wrap=$('#purchaseNoteWrap'),open=wrap.hidden;wrap.hidden=!open;$('#purchaseNoteToggle').textContent=open?'− Hide note':'＋ Add note (optional)';if(open)$('#purchaseNotes').focus()};
function openPurchaseDialog(row = null) {
  purchaseEditing = row;
  purchaseSelectedProduct = row
    ? (S.p || []).find(product => String(product.id) === String(row.product_id)) || null
    : null;

  $('#purchaseDialogTitle').textContent = row ? 'Edit Purchase' : 'Add Purchase';
  $('#purchaseFormError').textContent = '';
  for (const id of ['purchaseProductError', 'purchaseSupplierError', 'purchaseQtyError',
                    'purchaseCostError', 'purchaseExpiryError']) {
    $('#' + id).textContent = '';
  }

  $('#purchaseForm').reset();
  $('#purchaseDate').value = row?.date || purchaseDateToday();
  $('#purchaseExpiryDate').value = row?.expiry_date || '';
  $('#purchaseExpiryDate').min = $('#purchaseDate').value || purchaseDateToday();
  $('#purchaseQty').value = row?.quantity || 1;
  $('#purchaseUnitCost').value = row ? row.unit_cost : '';
  $('#purchaseNotes').value = row?.notes || '';
  $('#purchaseNoteWrap').hidden = !row?.notes;
  $('#purchaseNoteToggle').textContent = row?.notes ? '− Hide note' : '＋ Add note (optional)';
  fillSupplierSelect(row?.supplier_id || '');

  const productInput = $('#purchaseProductQ');
  productInput.hidden = false;
  productInput.value = '';
  productInput.disabled = !!row;
  $('#purchaseProductSelected').hidden = true;
  $('#purchaseProductOptions').hidden = true;
  $('#purchaseProductHelp').textContent = (S.p || []).length
    ? 'Search by product name or ID. Stock will update when saved.'
    : 'No products yet. Add a product in Products before recording a purchase.';

  // An existing purchase with a deleted product cannot be safely edited.
  const canSave = row ? !!purchaseSelectedProduct : !!(S.p || []).length;
  $('#purchaseSave').disabled = !canSave;
  $('#purchaseSave').textContent = row ? 'Save changes' : 'Save Purchase';
  if (row && purchaseSelectedProduct) {
    productInput.value = purchaseSelectedProduct.n;
    showSelectedProduct('purchaseProductSelected', purchaseSelectedProduct, () => {});
    $('#purchaseProductSelected button').hidden = true;
    productInput.hidden = true;
  } else if (row) {
    $('#purchaseProductError').textContent =
      'This product no longer exists. The purchase cannot be edited.';
  }

  $('#purchaseNewSupplierError').textContent = '';
  $('#purchaseNewSupplierBox').hidden = true;
  updatePurchaseTotal();
  const dialog = $('#purchaseDialog');
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else openPm(dialog.innerHTML);
  if (!row) productInput.focus();
}
function closePurchaseDialog(){const d=$('#purchaseDialog');if(d.open)d.close();else $('#pm').hidden=true}
$('#purchaseDialogClose').onclick=closePurchaseDialog;$('#purchaseCancel').onclick=closePurchaseDialog;
function validatePurchaseForm() {
  const quantityText = $('#purchaseQty').value.trim();
  const costText = $('#purchaseUnitCost').value.trim();
  const quantity = Number(quantityText);
  const unitCost = Number(costText);
  const supplierId = $('#purchaseSupplier').value;
  const date = $('#purchaseDate').value;
  const expiryDate = $('#purchaseExpiryDate').value;

  const errors = {
    purchaseProductError: purchaseSelectedProduct ? '' : 'Choose a product.',
    purchaseSupplierError: supplierId ? '' : 'Choose a supplier.',
    purchaseQtyError: /^\d+$/.test(quantityText) &&
      Number.isSafeInteger(quantity) && quantity >= 1 && quantity <= 100000000
      ? '' : 'Enter a positive whole number.',
    purchaseCostError: costText !== '' && Number.isFinite(unitCost) &&
      unitCost >= 0 && unitCost <= 100000000
      ? '' : 'Enter a valid unit cost.',
    purchaseExpiryError: expiryDate && expiryDate > date
      ? '' : 'Expiration date must be after the purchase date.',
    purchaseFormError: date ? '' : 'Choose a purchase date.',
  };
  for (const [id, message] of Object.entries(errors)) $('#' + id).textContent = message;
  if (Object.values(errors).some(Boolean)) return null;

  return {
    action: purchaseEditing ? 'edit' : 'create',
    id: purchaseEditing?.id,
    product_id: purchaseSelectedProduct.id,
    supplier_id: supplierId,
    quantity,
    unit_cost: unitCost,
    date,
    expiry_date: expiryDate,
    notes: $('#purchaseNotes').value.trim(),
  };
}

function refreshPurchaseViews() {
  drawPurchases();
  drawRdr();
  drawGrid();
  if (typeof drawRep === 'function') drawRep();
  drawRecentPurchases();
  drawSupplierComparison();
}

$('#purchaseForm').onsubmit = async event => {
  event.preventDefault();
  const payload = validatePurchaseForm();
  if (!payload) return;

  const button = $('#purchaseSave');
  button.disabled = true;
  button.textContent = 'Saving…';
  let result;
  try {
    result = await api('/api/purchase', payload);
  } catch (error) {
    result = { error: 'Cannot save purchase. Please try again.' };
  } finally {
    button.disabled = false;
    button.textContent = purchaseEditing ? 'Save changes' : 'Save Purchase';
  }
  if (result.error) {
    $('#purchaseFormError').textContent = result.error;
    return;
  }

  const edited = !!purchaseEditing;
  closePurchaseDialog();
  purchaseEditing = null;
  refreshPurchaseViews();
  purchaseToast(result.reorder_removed && !edited
    ? 'Purchase added · product quantity met the suggested reorder quantity. Reorder list updated.'
    : result.msg || (edited ? 'Purchase updated.' : 'Purchase added.'));
};
$('#purchaseRows').onclick=async e=>{const edit=e.target.closest('[data-purchase-edit]'),del=e.target.closest('[data-purchase-delete]');if(edit){const row=purchaseRows().find(x=>x.id===edit.dataset.purchaseEdit);if(row)openPurchaseDialog(row);return}if(del){const row=purchaseRows().find(x=>x.id===del.dataset.purchaseDelete);if(!row)return;if(!confirm(`Delete purchase for ${row.product_name} (${row.quantity} units)? This will reverse the received stock only if that quantity is still available.`))return;const r=await api('/api/purchase',{action:'delete',id:row.id});if(r.error){purchaseToast(r.error,true);return}drawPurchases();drawRdr();drawGrid();purchaseToast(r.msg||'Purchase deleted.');drawRecentPurchases();drawSupplierComparison()}};
function bindHistoryPicker(inputId, optionsId, selectedId, contentId, onPick, onClear) {
  bindProductPicker(inputId, optionsId, product => {
    showSelectedProduct(selectedId, product, () => {
      onClear();
      $('#' + inputId).value = '';
      $('#' + contentId).innerHTML =
        '<p class="mu">Select a product to load its records.</p>';
      $('#' + inputId).hidden = false;
    });
    $('#' + inputId).hidden = true;
    onPick(product);
  });
}
let recentProduct=null,compareProduct=null;
bindHistoryPicker('recentProductQ','recentProductOptions','recentProductSelected','recentPurchasesContent',p=>{recentProduct=p;drawRecentPurchases()},()=>{recentProduct=null});
bindHistoryPicker('compareProductQ','compareProductOptions','compareProductSelected','supplierComparisonContent',p=>{compareProduct=p;drawSupplierComparison()},()=>{compareProduct=null});
function drawRecentPurchases(){const el=$('#recentPurchasesContent');if(!el)return;if(!recentProduct){el.innerHTML='<p class="mu">Select a product to load its purchase history.</p>';return}const rows=purchaseRows().filter(x=>String(x.product_id)===String(recentProduct.id)).sort((a,b)=>String(b.date).localeCompare(String(a.date))||String(b.created_at||'').localeCompare(String(a.created_at||''))).slice(0,20);el.innerHTML=rows.length?`<div class="purchase-history-title"><strong>${esc(recentProduct.n)}</strong><span class="mu">Latest ${rows.length} records</span></div><div class="wrap purchase-table-wrap"><table class="purchase-table"><thead><tr><th>Date</th><th>Supplier</th><th>Quantity</th><th>Unit cost</th><th>Total</th><th>Expiry date</th></tr></thead><tbody>${rows.map(x=>`<tr><td data-label="Date">${esc(x.date)}</td><td data-label="Supplier">${esc(x.supplier_name)}</td><td data-label="Quantity">${x.quantity}</td><td data-label="Unit cost">${M(x.unit_cost)}</td><td data-label="Total"><strong>${M(x.total)}</strong></td><td data-label="Expiry date">${esc(x.expiry_date||'Not recorded')}</td></tr>`).join('')}</tbody></table></div>`:'<div class="purchase-empty"><h3>No purchases recorded for this product yet</h3><button type="button" class="pri" id="recentAddPurchase">＋ Add Purchase</button></div>';const b=$('#recentAddPurchase');if(b)b.onclick=()=>openPurchaseDialog()}
function drawSupplierComparison(){const el=$('#supplierComparisonContent');if(!el)return;if(!compareProduct){el.innerHTML='<p class="mu">Select a product to compare supplier prices.</p>';return}const all=purchaseRows().filter(x=>String(x.product_id)===String(compareProduct.id));if(!all.length){el.innerHTML=`<div class="purchase-empty"><h3>No purchases for ${esc(compareProduct.n)}</h3><p class="mu">Record a purchase to start comparing suppliers.</p><button type="button" class="pri" id="compareAddPurchase">＋ Add Purchase</button></div>`;const b=$('#compareAddPurchase');if(b)b.onclick=()=>openPurchaseDialog();return}const map=new Map();all.forEach(x=>{const k=x.supplier_id;if(!map.has(k))map.set(k,{id:k,name:x.supplier_name||'Unknown supplier',rows:[]});map.get(k).rows.push(x)});const ranked=[...map.values()].map(g=>{g.rows.sort((a,b)=>String(b.date).localeCompare(String(a.date))||String(b.created_at||'').localeCompare(String(a.created_at||'')));const latest=g.rows[0];return{name:g.name,id:g.id,latest:Number(latest.unit_cost)||0,date:latest.date,count:g.rows.length,avg:g.rows.reduce((sum,x)=>sum+(Number(x.unit_cost)||0),0)/g.rows.length}}).sort((a,b)=>a.latest-b.latest||a.name.localeCompare(b.name));const best=ranked[0];el.innerHTML=`<div class="purchase-cheapest"><span class="purchase-cheapest-icon">✓</span><div><small>Cheapest by latest unit cost</small><strong>${esc(best.name)}</strong><span>${M(best.latest)} per unit</span></div></div>${ranked.length===1?'<p class="mu purchase-one-supplier">Only one supplier on record.</p>':''}<div class="wrap purchase-table-wrap"><table class="purchase-table"><thead><tr><th>Rank</th><th>Supplier</th><th>Latest unit cost</th><th>Avg. unit cost</th><th>Last purchase</th><th>Purchases</th></tr></thead><tbody>${ranked.map((x,i)=>`<tr class="${i===0?'purchase-cheapest-row':''}"><td data-label="Rank">${i+1}</td><td data-label="Supplier"><strong>${esc(x.name)}</strong>${i===0?' <span class="purchase-cheapest-badge">Cheapest</span>':''}</td><td data-label="Latest unit cost">${M(x.latest)}</td><td data-label="Avg. unit cost">${M(x.avg)}</td><td data-label="Last purchase">${esc(x.date)}</td><td data-label="Purchases">${x.count}</td></tr>`).join('')}</tbody></table></div>`}
// Refresh derived views whenever the authenticated state is loaded.
