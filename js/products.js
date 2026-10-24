// products.js: Products tab (managers and owners): add/edit form, quantity Add/Set, bulk actions
const PRODUCT_ROWS_PER_PAGE=80;
let productPage=0;
let sel=new Set();
function drawProd(){const present=new Set(S.p.map(p=>p.id));sel=new Set([...sel].filter(id=>present.has(id)));const q=$('#ps').value.trim().toLowerCase(),all=[...S.p].sort((a,b)=>a.n.localeCompare(b.n)),l=all.filter(p=>!q||p.n.toLowerCase().includes(q));
productPage=Math.min(productPage,Math.max(0,Math.ceil(l.length/PRODUCT_ROWS_PER_PAGE)-1));
const from=productPage*PRODUCT_ROWS_PER_PAGE,visible=l.slice(from,from+PRODUCT_ROWS_PER_PAGE);
$('#pc').textContent=(l.length?(from+1)+'–'+(from+visible.length):'0')+' of '+l.length+' matching products'+(q?' (catalog: '+all.length+')':'');
$('#productPageInfo').textContent='Page '+(productPage+1)+' of '+Math.max(1,Math.ceil(l.length/PRODUCT_ROWS_PER_PAGE));
$('#productPrev').disabled=productPage===0;$('#productNext').disabled=from+visible.length>=l.length;
$('#pt').innerHTML=visible.map(p=>`<tr><td><input type="checkbox" class="pk" data-id="${p.id}" aria-label="Select ${esc(p.n)}"${sel.has(p.id)?' checked':''}></td><td>${esc(p.n)}</td><td>${M(p.p)}</td><td>${p.c==null?'<span class="mu">—</span>':M(p.c)}</td><td><b>${p.s}</b></td><td>${esc(p.e||'')||'—'}</td><td>${tags(p)}</td><td class="products-stock-correction"><input class="qv" inputmode="numeric" style="width:84px" placeholder="New qty" aria-label="Correct stock for ${esc(p.n)}"> <button data-a="set" data-id="${p.id}">Set</button></td><td class="products-row-actions"><button data-e="${p.id}">Edit</button> <button data-x="${p.id}" class="danger-action">Delete</button><span class="delbox" hidden><input class="dwhy" placeholder="Reason required" aria-label="Reason for deleting ${esc(p.n)}" style="width:130px"><button data-confirm-delete="${p.id}">Confirm</button><button data-cancel-delete>Cancel</button></span></td></tr>`).join('')||'<tr><td colspan="9" class="mu">No products found.</td></tr>';
drawBulk()}
function shown(){const q=$('#ps').value.trim().toLowerCase();return S.p.filter(p=>!q||p.n.toLowerCase().includes(q)).sort((a,b)=>a.n.localeCompare(b.n)).slice(productPage*PRODUCT_ROWS_PER_PAGE,(productPage+1)*PRODUCT_ROWS_PER_PAGE)}
function drawBulk(){const n=sel.size,l=shown(),a=$('#pall');$('#bulk').hidden=!n;$('#bn').textContent=n+' selected';a.checked=l.length>0&&l.every(p=>sel.has(p.id));a.indeterminate=!a.checked&&l.some(p=>sel.has(p.id))}
function clearForm(){edit=null;['fn','fp','fc','fe','fm','fs'].forEach(i=>$('#'+i).value='');$('#fsl').hidden=false;$('#sv').textContent='Save product';$('#fmsg').textContent='';$('#productFormTitle').textContent='Add a product';if($('#productFormDialog').open)$('#productFormDialog').close()}
$('#productAdd').onclick=()=>{clearForm();$('#productFormDialog').showModal();$('#fn').focus()};
$('#productFormClose').onclick=clearForm;
$('#productFormDialog').onclick=e=>{if(e.target===$('#productFormDialog'))clearForm()};
$('#productFormDialog').onclose=()=>{edit=null};
$('#sv').onclick=async()=>{const n=$('#fn').value.trim(),p=parseFloat($('#fp').value),cv=$('#fc').value.trim(),c=cv===''?null:Number(cv),m=$('#fmsg'),s=parseInt($('#fs').value)||0;if(!n||isNaN(p)||p<0){m.textContent='Enter a product name and a valid price.';return}if(cv!==''&&(!isFinite(c)||c<0)){m.textContent='Enter a valid cost, or leave it blank.';return}const r=await api('/api/product',{id:edit,n,p,c,e:$('#fe').value,m:parseInt($('#fm').value)||0,s});if(r.error)return fail(r,m);clearForm();drawProd();drawGrid();drawLines()};
$('#cf').onclick=clearForm;
$('#ps').oninput=()=>{sel.clear();productPage=0;drawProd()};
$('#productPrev').onclick=()=>{if(productPage>0){productPage--;drawProd()}};
$('#productNext').onclick=()=>{productPage++;drawProd()};
$('#pall').onchange=e=>{const l=shown();if(e.target.checked)l.forEach(p=>sel.add(p.id));else l.forEach(p=>sel.delete(p.id));drawProd()};
$('#pt').onchange=e=>{const c=e.target.closest('.pk');if(!c)return;const id=+c.dataset.id;if(c.checked)sel.add(id);else sel.delete(id);drawBulk()};
$('#bclr').onclick=()=>{sel.clear();drawProd()};
$('#bdel').onclick=async()=>{const m=$('#rm'),why=$('#bwhy').value.trim(),ids=[...sel];m.textContent='';if(!ids.length)return;if(!why){m.textContent='Enter a reason before deleting.';return}if(!confirm('Delete '+ids.length+' product'+(ids.length>1?'s':'')+'? Old receipts keep their items.'))return;const r=await api('/api/delete-many',{ids,why});if(r.error)return fail(r,m);sel.clear();$('#bwhy').value='';clampCart();drawProd();drawGrid();drawLines();m.textContent=r.msg};
$('#pt').onclick=async e=>{const b=e.target.closest('button');if(!b)return;const m=$('#rm');m.textContent='';
if(b.dataset.e){const p=S.p.find(x=>x.id==b.dataset.e);edit=p.id;$('#fn').value=p.n;$('#fp').value=p.p;$('#fc').value=p.c==null?'':p.c;$('#fe').value=p.e;$('#fm').value=p.m;$('#fsl').hidden=true;$('#sv').textContent='Update product';$('#productFormTitle').textContent='Edit product: '+p.n;$('#productFormDialog').showModal();$('#fn').focus()}
else if(b.dataset.x){const box=b.closest('tr').querySelector('.delbox');b.hidden=true;box.hidden=false;box.querySelector('.dwhy').focus()}
else if(b.dataset.confirmDelete){const row=b.closest('tr'),why=row.querySelector('.dwhy').value.trim();if(!why){m.textContent='Enter a reason before deleting this product.';return}const r=await api('/api/delete',{id:+b.dataset.confirmDelete,why});if(r.error)return fail(r,m);clampCart();drawProd();drawGrid();drawLines()}
else if(b.hasAttribute('data-cancel-delete')){const row=b.closest('tr');row.querySelector('[data-x]').hidden=false;row.querySelector('.delbox').hidden=true}
else if(b.dataset.a){const v=b.closest('tr').querySelector('.qv').value.trim();if(!v){m.textContent='Type a quantity first.';return}const r=await api('/api/stock',{id:+b.dataset.id,mode:b.dataset.a,v});if(r.error)return fail(r,m);clampCart();drawProd();drawGrid();drawLines();m.textContent=r.msg}};
