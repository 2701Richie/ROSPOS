// import.js: CSV import and export on the Products tab
let imRows=null;
function parseCsv(t){t=t.replace(/^\uFEFF/,'');const rows=[];let r=[],c='',q=false;for(let i=0;i<t.length;i++){const ch=t[i];if(q){if(ch==='"'){if(t[i+1]==='"'){c+='"';i++}else q=false}else c+=ch}else if(ch==='"')q=true;else if(ch===','){r.push(c);c=''}else if(ch==='\n'||ch==='\r'){if(ch==='\r'&&t[i+1]==='\n')i++;r.push(c);c='';rows.push(r);r=[]}else c+=ch}if(c!==''||r.length){r.push(c);rows.push(r)}return rows.filter(x=>x.some(v=>v.trim()!==''))}
const HM={name:['name','product','product name','item','description'],price:['price','unit price','selling price','srp'],reorder:['reorder','reorder level','minimum','min'],quantity:['quantity','qty','count','stock','received'],cost:['cost','unit cost','cost price','purchase price','buying price']};
function toRows(csv){const t=parseCsv(csv);if(t.length<2)return{error:'The file has no data rows.'};const h=t[0].map(x=>x.trim().toLowerCase().replace(/\s+/g,' ')),col={};for(const k in HM)col[k]=h.findIndex(x=>HM[k].includes(x));if(col.name<0)return{error:'No "name" column found in the first row.'};return{col,rows:t.slice(1).map(r=>{const o={};for(const k in col)o[k]=col[k]>=0?(r[col[k]]||'').trim():'';return o})}}
function showPlan(p){const o=$('#io'),ia=$('#ia');ia.hidden=true;$('#imwhywrap').hidden=true;
let h=`<p><b>${p.new}</b> new, <b>${p.updated}</b> changed, <b>${p.unchanged}</b> unchanged.</p>`;
if(p.errorCount){h+=`<p class="err"><b>${p.errorCount} problem${p.errorCount>1?'s':''}. Nothing was saved.</b> Fix the file and preview again.</p><ul>${p.errors.map(e=>`<li>Row ${e.row}: ${esc(e.msg)}</li>`).join('')}</ul>`+(p.errorCount>p.errors.length?`<p class="mu">Showing the first ${p.errors.length}.</p>`:'')}
else if(p.applied){h+='<p><b>Import applied.</b></p>';imRows=null;$('#imf').value='';drawProd();drawGrid();drawLines()}
else{ia.hidden=false;$('#imwhywrap').hidden=false;h+='<p class="mu">Nothing is saved yet. Check the list, enter a reason, then press Apply import.</p>'}
if(p.notes.length)h+=`<p class="mu">Matched despite different spelling:</p><ul>${p.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`;
if(p.changes.length)h+=`<div class="wrap"><table><thead><tr><th>Product</th><th>Change</th></tr></thead><tbody>${p.changes.map(c=>`<tr><td>${esc(c.n)}</td><td>${esc(c.w)}</td></tr>`).join('')}</tbody></table></div>`+(p.more?`<p class="mu">and ${p.more} more.</p>`:'');
o.innerHTML=h}
async function sendImport(apply){const o=$('#io'),why=$('#imwhy').value.trim();if(apply&&!why){o.textContent='Enter a reason for this import. Nothing was saved.';$('#imwhy').focus();return}const r=await api('/api/import',{mode:$('#im').value,rows:imRows,apply,why});if(r.error)return fail(r,o);showPlan(r.plan);if(r.plan.applied)$('#imwhy').value=''}
$('#ip').onclick=async()=>{const f=$('#imf').files[0],o=$('#io');if(!f){o.innerHTML='<p class="err">Choose a CSV file first.</p>';return}const x=toRows(await f.text());if(x.error){o.innerHTML=`<p class="err">${esc(x.error)}</p>`;return}if($('#im').value!=='products'&&x.col.quantity<0){o.innerHTML='<p class="err">This import needs a "quantity" column.</p>';return}imRows=x.rows;await sendImport(false)};
$('#ia').onclick=async()=>{if(imRows)await sendImport(true)};
$('#im').onchange=$('#imf').onchange=()=>{$('#ia').hidden=true;$('#imwhywrap').hidden=true;$('#imwhy').value='';$('#io').innerHTML='';imRows=null};
function csvCell(v){v=String(v??'');return /[",\n\r]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v}
function saveCsv(name,rows){const b=new Blob(['\uFEFF'+rows.map(r=>r.map(csvCell).join(',')).join('\r\n')+'\r\n'],{type:'text/csv'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
$('#ie').onclick=()=>{saveCsv('products.csv',[['name','price','reorder','quantity','cost'],...[...S.p].sort((a,b)=>a.n.localeCompare(b.n)).map(p=>[p.n,p.p,p.m,p.s,p.c==null?'':p.c])])};
$('#it').onclick=()=>saveCsv('template.csv',[['name','price','reorder','quantity','cost']]);
