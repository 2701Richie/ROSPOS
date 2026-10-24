// JS logic tests: runs js/*.js in a sandbox with a fake page (no browser needed).
// Usage: node tests/js_logic_test.js [source-folder]     Output: 'ok   ...' / 'FAIL ...' lines
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[2]||path.join(__dirname,'..');
let bad=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)bad++};
function load(file,extra){
 const els={};const el=id=>els[id]||(els[id]={value:'',textContent:'',innerHTML:'',hidden:false,style:{},title:'',attrs:{},setAttribute(k,v){this.attrs[k]=v},addEventListener(){},querySelector(){return this.label||(this.label={textContent:''})}});
 const ctx=Object.assign({$:s=>el(s),document:{querySelector:s=>el(s),querySelectorAll:()=>[]},window:{},localStorage:{getItem:()=>null,setItem(){}},
  S:{p:[],s:[],g:[]},T:'2026-10-19',cart:[],said:'',say(m){ctx.said=m},M:n=>n,R:n=>Math.round(n*100)/100,esc:s=>s,tags:()=>''},extra||{});
 vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'js',file),'utf8'),ctx);return{ctx,el};
}
const run=(h,code)=>vm.runInContext(code,h.ctx);
const pending=[];
const names=a=>Array.from(a).map(x=>x.p?x.p.n:x.n).join(',');

// ---- Reorder: zero-stock products always appear ----
{
 const h=load('reorder.js',{S:{p:[{id:1,n:'Alpha',p:5,s:0,m:0},{id:2,n:'Beta',p:5,s:3,m:0},{id:3,n:'Gamma',p:5,s:0,m:4},{id:4,n:'Delta',p:5,s:9,m:4}],s:[],g:[]}});
 const L=run(h,'lists()');
 ok(names(L.now)==='Alpha,Gamma','reorder: zero stock appears in Reorder now, with or without a reorder level (%s)'.replace('%s',names(L.now)));
 ok(names(L.low)==='','reorder: well-stocked product is not listed');
 ok(L.none===1,'reorder: only products with stock and no reorder level are reported as never appearing (%s)'.replace('%s',L.none));
 run(h,'badge()');ok(h.el('#rdrb').label.textContent==='Reorder (2)','reorder: tab badge counts zero-stock items');
 ok(names(run(h,'picked()'))==='Alpha,Gamma','reorder: All suppliers selects only products at or below minimum stock by default');
 ok(run(h,'picked()').every(x=>['Alpha','Gamma'].includes(x.n)),'reorder: adequately stocked products are excluded from the default order');
 ok(!/checked/.test(run(h,'rrow({p:S.p[1],sold:0,price:null})')),'reorder: adequately stocked product checkbox starts unchecked');
 run(h,'drawRdr()');
 ok(/Alpha/.test(h.el('#reorderRows').innerHTML)&&/Gamma/.test(h.el('#reorderRows').innerHTML)&&!/Beta|Delta/.test(h.el('#reorderRows').innerHTML),'reorder: All suppliers table displays only items that need restocking');
 h.el('#rSearch').value='delta';run(h,'drawRdr()');
 ok(!/Delta/.test(h.el('#reorderRows').innerHTML),'reorder: All suppliers search cannot add adequately stocked products to the reorder list');
 ok(run(h,'sug(S.p[0])')===1,'reorder: default order quantity for a zero-level product is 1');
}

// ---- Reorder: search all products and assign selected items to a chosen supplier ----
{
 const products=[{id:1,n:'Urgent Item',p:10,s:0,m:3},{id:2,n:'Zinc Tablets',p:12,s:50,m:5}];
 const h=load('reorder.js',{S:{p:products,s:[],g:[],suppliers:[{id:7,name:'Backup Supplier'}],purchases:[{product_id:1,supplier_id:8,supplier_name:'Cheapest Supplier',unit_cost:2,date:'2026-10-20'}]}});
 h.el('#rSupplier').value='7';h.el('#rSearch').value='zinc';
 const visible=run(h,'visibleReorderRows(reorderRows().rows)');
 ok(visible.length===1&&visible[0].p.n==='Zinc Tablets','reorder: search finds a product even when it is not currently low on stock');
 run(h,'drawRdr()');
 ok(/Add to order/.test(h.el('#rsearchResults').innerHTML)&&!(/checked/.test(h.el('#rsearchResults').innerHTML)),'reorder: search results offer Add to order without auto-selecting');
 ok(/No items added yet/.test(h.el('#reorderRows').innerHTML),'reorder: main order table contains only selected products');
 run(h,'rX[2]=true;drawRdr()');
 ok(/Zinc Tablets/.test(h.el('#reorderRows').innerHTML)&&!/Urgent Item/.test(h.el('#reorderRows').innerHTML),'reorder: main order table shows selected products only');
 h.el('#rSupplier').value='7';run(h,'rX[1]=false;rX[2]=true');
 const chosen=run(h,'picked()');
 ok(chosen.length===1&&chosen[0].n==='Zinc Tablets'&&chosen[0].supplier==='Backup Supplier'&&chosen[0].cost==='','reorder: manually selected item is assigned to chosen supplier even without recorded price history');
 ok(/Backup Supplier/.test(run(h,'rrow({p:S.p[1],sold:0,price:null})')),'reorder: selected supplier is shown even when its price is unknown');
 h.el('#rSearch').value='';
 ok(run(h,'picked()').some(x=>x.n==='Zinc Tablets'),'reorder: ticking an item persists when search is cleared');
}

// ---- Reorder: professional printable order sheet ----
{
 const h=load('reorder.js',{S:{p:[{id:1,n:'Paracetamol 500mg',p:8,s:0,m:5}],s:[],g:[],purchases:[{product_id:1,supplier_id:2,supplier_name:'Trusted Supplier',unit_cost:12.5,date:'2026-10-20'}]},storeName:()=> 'ROSPOS Pharmacy',cfg:()=>({rc_addr:'Banate, Iloilo',rc_phone:'09123456789',rc_tag:'Health and inventory made simple',rc_foot:'Thank you'})});
 h.ctx.document.body={classList:{add(){},remove(){}}};h.ctx.window.addEventListener=()=>{};h.ctx.window.print=()=>{};
 run(h,'rX[1]=true;rQ[1]=4');h.el('#rpr').onclick();
 ok(/\/logo\.svg/.test(h.el('#op').innerHTML),'reorder print: includes ROSPOS logo');
 ok(/ORDER LIST/.test(h.el('#op').innerHTML)&&/Order reference/.test(h.el('#op').innerHTML)&&/Date/.test(h.el('#op').innerHTML),'reorder print: includes the order-list heading, reference and date');
 ok(!/Trusted Supplier/.test(h.el('#op').innerHTML)&&/Banate, Iloilo/.test(h.el('#op').innerHTML)&&/09123456789/.test(h.el('#op').innerHTML),'reorder print: omits supplier name and keeps configured store contact details');
 ok(/Unit cost/.test(h.el('#op').innerHTML)&&/Supplier to complete pricing/.test(h.el('#op').innerHTML)&&!(/₱50\.00/.test(h.el('#op').innerHTML)),'reorder print: leaves cost fields blank for supplier to fill in');
}

// ---- Sell: progressive rendering prevents huge product-grid updates ----
{
 const products=Array.from({length:205},(_,i)=>({
   id:i+1,n:'Item '+String(i+1).padStart(3,'0'),p:10,s:5,m:1,e:''
 }));
 const h=load('sell.js',{S:{p:products,s:[],g:[]}});
 h.ctx.document.createElement=()=>({className:'',innerHTML:''});
 h.el('#grid').appendChild=child=>{h.el('#grid').more=child};
 run(h,'drawGrid()');
 ok((h.el('#grid').innerHTML.match(/class="tile"/g)||[]).length===80,
   'sell grid: initial render creates only 80 product tiles');
 ok(/Showing 80 of 205/.test(h.el('#grid').more.innerHTML),
   'sell grid: remaining products are available via Show more');
 run(h,'productGridLimit += PRODUCT_PAGE_SIZE;drawGrid()');
 ok((h.el('#grid').innerHTML.match(/class="tile"/g)||[]).length===160,
   'sell grid: next page shows 160 products');
 h.el('#q').value='Item 205';
 run(h,'resetProductGrid()');
 ok((h.el('#grid').innerHTML.match(/class="tile"/g)||[]).length===1 &&
   /Item 205/.test(h.el('#grid').innerHTML),
   'sell grid: search still finds products beyond the initial page');
 ok(run(h,'productGridLimit')===80,
   'sell grid: changing search resets pagination');
}

// ---- Sell: type the quantity on a cart line ----
{
 const h=load('sell.js',{S:{p:[{id:1,n:'Alpha',p:2,s:12,e:'',m:0},{id:2,n:'Old',p:2,s:5,e:'2020-01-01',m:0}],s:[],g:[]}});
 const q=()=>h.ctx.cart.length?h.ctx.cart[0].q:null;
 run(h,'add(1)');run(h,'add(1)');ok(q()===2,'sell: tapping a product twice gives quantity 2');
 run(h,'setQty(1,"5")');ok(q()===5,'sell: typing 5 sets the line to 5');
 run(h,'setQty(1,"25")');ok(q()===12&&/Only 12/.test(h.ctx.said),'sell: typing more than the stock sets the maximum and shows the stock');
 run(h,'setQty(1,"5")');run(h,'setQty(1,"abc")');ok(q()===5&&/whole number/.test(h.ctx.said),'sell: text keeps the old quantity and asks for a whole number');
 run(h,'setQty(1,"-2")');ok(q()===5,'sell: a negative number keeps the old quantity');
 run(h,'setQty(1," 7.9 ")');ok(q()===7,'sell: spaces and decimals are tolerated (7.9 becomes 7)');
 run(h,'setQty(1,"0")');ok(h.ctx.cart.length===0,'sell: typing 0 removes the line');
 run(h,'add(1)');run(h,'setQty(1,"")');ok(h.ctx.cart.length===0,'sell: clearing the box removes the line');
 run(h,'add(1)');h.el('#lines').onchange({target:{classList:{contains:c=>c==='qn'},dataset:{id:'1'},value:'3'}});ok(q()===3,'sell: the change event on a quantity box updates the line');
 run(h,'drawLines()');const html=h.el('#lines').innerHTML;ok(/class="qn"/.test(html)&&/value="3"/.test(html),'sell: the cart line shows an editable quantity box with the current value');
 run(h,'setQty(1,"12")');run(h,'add(1)');ok(q()===12&&/Not enough stock/.test(h.ctx.said),'sell: tapping a product at full stock is still refused');
 ok(run(h,'add(2)')===false&&/Expired/.test(h.ctx.said),'sell: expired products still cannot be added');
 run(h,'setQty(99,"4")');ok(q()===12,'sell: typing for a line that is not in the cart does nothing');
}

// ---- Products: large catalogs render a bounded page, with safe page selection ----
{
 const products=Array.from({length:210},(_,i)=>({id:i+1,n:'Item '+String(i+1).padStart(3,'0'),p:10,s:5,e:'',m:1}));
 const h=load('products.js',{S:{p:products,s:[],g:[]}});
 run(h,'drawProd()');
 ok((h.el('#pt').innerHTML.match(/data-e=/g)||[]).length===80&&
    h.el('#productPageInfo').textContent==='Page 1 of 3',
    'products: initial large catalog renders at most 80 editable rows');
 h.el('#pall').onchange({target:{checked:true}});
 ok(run(h,'sel.size')===80,'products: Select page never silently selects all 210 products');
 h.el('#productNext').onclick();
 ok((h.el('#pt').innerHTML.match(/data-e=/g)||[]).length===80&&
    h.el('#productPageInfo').textContent==='Page 2 of 3'&&run(h,'sel.size')===80,
    'products: page two renders another 80 rows without losing intentional selections');
 h.el('#productNext').onclick();
 ok((h.el('#pt').innerHTML.match(/data-e=/g)||[]).length===50&&
    h.el('#productNext').disabled,
    'products: last page contains only the remaining 50 products');
 h.el('#ps').value='Item 210';h.el('#ps').oninput();
 ok((h.el('#pt').innerHTML.match(/data-e=/g)||[]).length===1&&
    /Item 210/.test(h.el('#pt').innerHTML)&&run(h,'productPage')===0&&
    run(h,'sel.size')===0,
    'products: searching finds off-page items and clears stale bulk selections');
}

// ---- Products: bulk delete selection ----
pending.push((async()=>{
 const calls=[];let reply={msg:'Deleted 2 products.'},yes=true;
 const prods=[{id:1,n:'Alpha',p:1,s:1,e:'',m:0},{id:2,n:'Beta',p:1,s:1,e:'',m:0},{id:3,n:'Gamma',p:1,s:1,e:'',m:0}];
 const h=load('products.js',{S:{p:prods.slice(),s:[],g:[]},api:async(p,b)=>{calls.push([p,b]);return reply},fail:(r,e)=>{e.textContent=r.error},
  clampCart(){},drawGrid(){},drawLines(){},confirm:()=>yes});
 const tick=()=>new Promise(r=>setTimeout(r,0));
 const box=(id,checked)=>({target:{closest:()=>({dataset:{id:String(id)},checked})}});
 run(h,'drawProd()');ok(h.el('#bulk').hidden===true,'products: bulk bar hidden while nothing is selected');
 h.el('#pt').onchange(box(1,true));h.el('#pt').onchange(box(3,true));
 ok(h.el('#bulk').hidden===false&&h.el('#bn').textContent==='2 selected','products: ticking products shows the bar with the count');
 h.el('#pall').onchange({target:{checked:true}});ok(h.el('#bn').textContent==='3 selected'&&h.el('#pall').checked===true,'products: select all ticks every shown product');
 h.el('#pall').onchange({target:{checked:false}});ok(h.el('#bulk').hidden===true,'products: untick select all clears the shown selection');
 h.el('#ps').value='alp';h.el('#pall').onchange({target:{checked:true}});
 ok(h.el('#bn').textContent==='1 selected','products: select all only ticks the products matching the search');
 h.el('#ps').oninput();ok(h.el('#bulk').hidden===true,'products: changing the search clears the selection (hidden rows can never be deleted unseen)');
 h.el('#ps').value='';h.el('#pt').onchange(box(1,true));h.el('#pt').onchange(box(2,true));
 h.el('#bwhy').value='';h.el('#bdel').onclick();await tick();
 ok(calls.length===0&&/reason/i.test(h.el('#rm').textContent),'products: delete needs a reason, nothing is sent without one');
 h.el('#bwhy').value='old stock';yes=false;h.el('#bdel').onclick();await tick();
 ok(calls.length===0,'products: declining the confirmation sends nothing');
 yes=true;reply={error:'Your account is not allowed to do this.'};h.el('#bdel').onclick();await tick();
 ok(calls.length===1&&calls[0][0]==='/api/delete-many'&&JSON.stringify(calls[0][1])===JSON.stringify({ids:[1,2],why:'old stock'}),'products: confirmed delete sends the selected ids and the reason to /api/delete-many');
 ok(h.el('#rm').textContent===reply.error&&run(h,'sel.size')===2,'products: a refused request shows the error and keeps the selection');
 reply={msg:'Deleted 2 products.'};h.el('#bdel').onclick();await tick();
 ok(h.el('#rm').textContent==='Deleted 2 products.'&&run(h,'sel.size')===0&&h.el('#bwhy').value==='','products: after success the message shows and the selection and reason are cleared');
})());

// ---- Full screen button ----
{
 const noFs=load('fullscreen.js',{document:{documentElement:{},addEventListener(){}}});
 ok(noFs.el('#fsb').style.display==='none','fullscreen: button hidden when the browser cannot do it');
 const calls=[],ls={};
 const doc={documentElement:{requestFullscreen(){calls.push('req');return Promise.reject(new Error('denied'))}},fullscreenElement:null,
  exitFullscreen(){calls.push('exit');return Promise.resolve()},addEventListener(n,f){ls[n]=f}};
 const h=load('fullscreen.js',{document:doc});
 ok(h.el('#fsb').style.display!=='none'&&h.el('#fsb').label.textContent==='Full screen','fullscreen: button shown with label Full screen');
 h.el('#fsb').onclick();ok(calls.join()==='req','fullscreen: tap asks the browser for full screen; a refused request does not throw');
 doc.fullscreenElement={};ls.fullscreenchange();ok(h.el('#fsb').label.textContent==='Exit full screen','fullscreen: label changes to Exit full screen');
 h.el('#fsb').onclick();ok(calls.join()==='req,exit','fullscreen: tap while full screen exits it');
 doc.fullscreenElement=null;ls.fullscreenchange();ok(h.el('#fsb').label.textContent==='Full screen','fullscreen: label returns to Full screen');
}

// ---- Cost: report numbers ----
{
 const S0={p:[{id:1,n:'A',p:10,s:10,m:4,c:6},{id:2,n:'B',p:20,s:2,m:5,c:8},{id:3,n:'C',p:5,s:5,m:0},{id:4,n:'D',p:3,s:0,m:0,c:1}],
  s:[{no:1,d:'2026-10-19',l:[{id:1,q:2,p:10,c:6},{id:3,q:1,p:5}]},{no:2,d:'2026-10-19',v:true,l:[{id:1,q:9,p:10,c:6}]},
     {no:3,d:'2026-10-01',l:[{id:2,q:1,p:20,c:8}]},{no:4,d:'2026-08-01',l:[{id:2,q:5,p:20,c:8}]}],g:[]};
 const h=load('reports.js',{S:S0});run(h,'1');vm.runInContext(fs.readFileSync(path.join(root,'js','reorder.js'),'utf8'),h.ctx);
 const c=run(h,'costStats()');
 ok(c.atCost===76&&c.atPrice===140,'cost: stock value at cost 76 and at selling price 140 (products with a cost only)');
 ok(c.unknown===1&&c.total===4,'cost: one of four products has no cost');
 ok(c.reorderCount===2&&c.reorderCost===65&&c.reorderUnknown===0,'cost: reorder estimate uses the Reorder list quantities (8 x 8 + 1 x 1 = 65)');
 ok(c.today.profit===8&&c.today.revenue===20&&c.today.lines===1&&c.today.missing===1,'cost: profit today counts only lines with a cost, skips void sales, counts the line without cost');
 ok(c.d30.profit===20&&c.d30.lines===2&&c.d30.missing===1,'cost: 30-day profit includes day 18 and excludes sales older than 30 days');
 run(h,'drawCost()');const html=h.el('#cs').innerHTML;
 ok(/Stock value at cost/.test(html)&&/1 of 4 products have no cost yet/.test(html)&&/2 products to reorder/.test(html),'cost: report cards show value, unknown count and reorder count');
 ok(/1 item line without a cost not counted/.test(html)&&/margin 40%/.test(html)&&/margin 50%/.test(html),'cost: profit cards show the uncounted lines and the margin');
 const none=load('reports.js',{S:{p:[{id:1,n:'A',p:10,s:3,m:0},{id:2,n:'B',p:5,s:0,m:0}],s:[{no:1,d:'2026-10-19',l:[{id:1,q:1,p:10}]}],g:[]}});
 vm.runInContext(fs.readFileSync(path.join(root,'js','reorder.js'),'utf8'),none.ctx);
 const z=run(none,'costStats()');
 ok(z.atCost===0&&z.unknown===2&&z.reorderCost===0&&z.reorderUnknown===1&&z.today.profit===0,'cost: with no costs anywhere (staff view) every figure is zero and nothing breaks');
}

// ---- Cost: product form, table and CSV ----
pending.push((async()=>{
 const calls=[];
 const prods=[{id:1,n:'Alpha',p:10,s:5,e:'',m:0,c:6.5},{id:2,n:'Beta',p:5,s:5,e:'',m:0}];
 const h=load('products.js',{S:{p:prods.slice(),s:[],g:[]},edit:null,window:{scrollTo(){}},api:async(p,b)=>{calls.push([p,b]);return {}},fail(){},clampCart(){},drawGrid(){},drawLines(){}});
 const tick=()=>new Promise(r=>setTimeout(r,0));
 const save=async(cost)=>{h.el('#fn').value='X';h.el('#fp').value='10';h.el('#fc').value=cost;h.el('#fmsg').textContent='';h.el('#sv').onclick();await tick()};
 await save('');ok(calls.length===1&&calls[0][1].c===null,'cost form: blank cost is sent as null (unknown)');
 await save('6.5');ok(calls.length===2&&calls[0][0]==='/api/product'&&calls[1][1].c===6.5,'cost form: a typed cost is sent as a number');
 for(const bad of ['-1','abc','₱5']){const n=calls.length;await save(bad);ok(calls.length===n&&/valid cost/.test(h.el('#fmsg').textContent),'cost form: "'+bad+'" is refused with a message and nothing is sent')}
 h.el('#pt').onclick({target:{closest:()=>({dataset:{e:'1'}})}});ok(h.el('#fc').value===6.5,'cost form: Edit fills in the existing cost');
 h.el('#pt').onclick({target:{closest:()=>({dataset:{e:'2'}})}});ok(h.el('#fc').value==='','cost form: Edit of a product with no cost leaves the box empty');
 run(h,'drawProd()');const t=h.el('#pt').innerHTML;ok(/6\.5/.test(t)&&/—/.test(t),'cost table: Cost column shows the cost, or a dash when unknown');
 run(h,'clearForm()');ok(h.el('#fc').value==='','cost form: Cancel clears the cost box');
})());
{
 const blobs=[],doc={querySelector:()=>({}),querySelectorAll:()=>[],createElement:()=>({click(){},remove(){}}),body:{appendChild(){}}};
 const h=load('import.js',{S:{p:[{id:1,n:'B',p:5,s:1,m:2,c:3},{id:2,n:'A',p:9,s:4,m:0}],s:[],g:[]},document:doc,Blob:class{constructor(p){blobs.push(p[0])}},setTimeout:()=>0,URL:{createObjectURL:()=>'x',revokeObjectURL(){}}});
 const lines=b=>b.replace(/^\uFEFF/,'').trim().split('\r\n');
 const r1=run(h,"toRows('name,price,Unit Cost\\nA,10,6.5\\nB,5,')");
 ok(!r1.error&&r1.rows[0].cost==='6.5'&&r1.rows[1].cost==='','cost csv: a "Unit Cost" column is recognised, blank cells stay blank');
 const rCurrency=run(h,"toRows('Product Name,Price (₱),Unit Cost (₱),Reorder Level,Quantity\\nA,12.50,7.25,4,9')");
 ok(!rCurrency.error&&rCurrency.rows[0].name==='A'&&rCurrency.rows[0].price==='12.50'&&rCurrency.rows[0].cost==='7.25'&&rCurrency.rows[0].reorder==='4'&&rCurrency.rows[0].quantity==='9','cost csv: currency labels and parenthetical header notes are normalized');
 const r2=run(h,"toRows('name,price\\nA,10')");ok(!r2.error&&r2.rows[0].cost==='','cost csv: a file with no cost column still reads');
 h.el('#ie').onclick();const ex=lines(blobs[0]);
 ok(ex[0]==='name,price,reorder,quantity,cost'&&ex[1]==='A,9,0,4,'&&ex[2]==='B,5,2,1,3','cost csv: export has a cost column (blank when unknown)');
 h.el('#it').onclick();ok(lines(blobs[1])[0]==='name,price,reorder,quantity,cost','cost csv: template has a cost column');
}

// ---- Receipt: 58 mm layout, plain characters, RawBT bytes ----
{
 const esc=t=>String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
 const full={store:'3B Pharmacy',rc_addr:'12 Main St, Davao City',rc_phone:'0912 345 6789',rc_tag:'Your health partner',rc_foot:'Thank you!'};
 let prints=0,cur=full;
 const h=load('receipt.js',{cfg:()=>cur,esc,btoa:t=>Buffer.from(t,'binary').toString('base64'),navigator:{userAgent:'Mozilla/5.0 (Linux; Android 13)'}});
 h.ctx.document={createElement:()=>({}),head:{appendChild(){}},querySelector:s=>h.el(s)};
 h.ctx.window={location:{href:''},print(){prints++},addEventListener(){}};
 const base={no:7,d:'2026-10-19',t:'10:42 AM',by:'Maria',l:[{n:'Paracetamol 500mg',q:2,p:5.5}],tot:11,cash:20};
 const longName='Extra Strength Paracetamol 500mg Tablets Box of 100 Pieces Special Pack';
 const sales={
  base,
  long:Object.assign({},base,{l:[{n:longName,q:3,p:1234.5},{n:'Supercalifragilisticexpialidocious_Antidisestablishmentarianism_X',q:1,p:10},{n:'Ni\u00f1o \u20b1\u00f1land\u00fa \u00c1cido \u201cquoted\u201d \u2013 dash',q:12,p:0.5}],tot:3719.5,cash:4000}),
  many:Object.assign({},base,{l:Array.from({length:100},(_,i)=>({n:'Item '+(i+1),q:1,p:1.25})),tot:125,cash:125}),
  big:Object.assign({},base,{l:[{n:'Big',q:1,p:1234567.89}],tot:1234567.89,cash:2000000}),
  noby:Object.assign({},base,{by:''}),
  discount:Object.assign({},base,{sub:12,dc:2.4,dl:'Senior 20%',tot:9.6,cash:10}),
  voided:Object.assign({},base,{v:{d:'2026-10-19'}}),amended:Object.assign({},base,{h:[{d:'2026-10-19'}]})};
 const cfgs={full,empty:{},long:{store:'S'.repeat(40),rc_addr:'123 Very Long Street Name Avenue, Barangay Somewhere, Davao City 8000',rc_phone:'0912 345 6789 / 0917 111 2222 / 082 555 1234',rc_tag:'The best prices and the friendliest service in town',rc_foot:'Thank you very much for shopping with us, please come again soon'},name20:{store:'Rosario Family Pharmacy'}};
 const blocks=(s,c)=>{cur=c;return Array.from(run(h,'rcptBlocks('+JSON.stringify(s)+')'))};
 const ascii=t=>/^[\x20-\x7e]*$/.test(t);
 const fits=bl=>bl.every(b=>ascii(b.t)&&b.t.length<=(b.s===2?16:32)&&run(h,'rcLine('+JSON.stringify(b)+')').length<=(b.s===2?16:32));
 const valid=by=>{const a=Array.from(by);let i=0;if(a[0]!==0x1b||a[1]!==0x40)return false;while(i<a.length){const c=a[i];if(c===0x1b){if(![0x40,0x61,0x45,0x64].includes(a[i+1]))return false;i+=a[i+1]===0x40?2:3}else if(c===0x1d){if(a[i+1]!==0x21)return false;i+=3}else if(c===0x0a||(c>=0x20&&c<=0x7e))i++;else return false}return true};
 let allFit=true,allValid=true,count=0;for(const sk in sales)for(const ck in cfgs){const bl=blocks(sales[sk],cfgs[ck]);count++;if(!fits(bl))allFit=false;if(!valid(run(h,'rcptBytes('+JSON.stringify(bl)+')')))allValid=false}
 ok(allFit,'receipt: every line fits 32 columns (16 for double-size) and uses plain characters, in '+count+' sale and settings combinations');
 ok(allValid,'receipt: bytes are only plain text plus the five printer commands we use (init, align, bold, size, feed)');
 for(const n of [longName,'Supercalifragilisticexpialidocious_Antidisestablishmentarianism_X','Ni\u00f1o \u20b1\u00f1land\u00fa','a b  c']){
  const w=Array.from(run(h,'rcWrap('+JSON.stringify(n)+',32)')),p=run(h,'rcPlain('+JSON.stringify(n)+')');
  ok(w.join('').replace(/ /g,'')===p.replace(/ /g,'')&&w.every(x=>x.length<=32),'receipt: wrapping loses no characters ('+p.slice(0,24)+'...)')}
 ok(run(h,'rcPlain("\\u20b1 \\u00c1\\u00f1o \\u201cx\\u201d \\u4e2d")')==='PHP Ano "x" ?','receipt: peso sign, accents and quotes become plain characters, unknown symbols become ?');
 const amt=t=>parseFloat(t.trim().split(/\s+/).pop().replace(/,/g,''));
 for(const k of ['base','long','many','big']){const bl=blocks(sales[k],full),tot=bl.find(b=>b.t.startsWith('TOTAL')),items=bl.filter(b=>/^ +\d+ x [\d,.]+ +[\d,.]+$/.test(b.t));
  ok(tot&&amt(tot.t)===sales[k].tot&&Math.abs(items.reduce((a,b)=>a+amt(b.t),0)-sales[k].tot)<0.006&&items.length===sales[k].l.length,'receipt: '+k+' sale: TOTAL equals the sum of the printed item amounts ('+items.length+' items)')}
 const dbl=blocks(sales.base,full);ok(dbl.find(b=>b.t.startsWith('TOTAL')).s===1&&dbl.find(b=>b.t.startsWith('TOTAL')).b===true,'receipt: TOTAL is bold and double height');
 ok(blocks(sales.base,{store:'3B Pharmacy'})[0].s===2&&blocks(sales.base,{store:'Rosario Family Pharmacy'})[0].s===1&&blocks(sales.base,{store:'S'.repeat(40)})[0].s===0,'receipt: store name is double size when short, double height when medium, normal bold when long');
 const txt=bl=>Array.from(bl).map(b=>b.t).join('\n');
 ok(/12 Main St/.test(txt(blocks(sales.base,full)))&&/0912 345 6789/.test(txt(blocks(sales.base,full)))&&/Your health partner/.test(txt(blocks(sales.base,full)))&&/Thank you!/.test(txt(blocks(sales.base,full))),'receipt: address, phone, tagline and footer are printed when set');
 const e=blocks(sales.base,{});ok(e[0].t==='ROSPOS'&&!e.some(b=>b.t==='')&&/Thank you for your purchase!/.test(txt(e))&&/Not an official receipt/.test(txt(e)),'receipt: with nothing set there are no blank lines, a default footer, and the not-official line');
 ok(/\*\*\* VOID \*\*\*/.test(txt(blocks(sales.voided,full)))&&/\(AMENDED\)/.test(txt(blocks(sales.amended,full)))&&!/VOID|AMENDED/.test(txt(blocks(sales.base,full))),'receipt: VOID and AMENDED banners only where they apply');
 ok(/Senior 20%/.test(txt(blocks(sales.discount,full)))&&/Subtotal/.test(txt(blocks(sales.discount,full)))&&!/Cashier/.test(txt(blocks(sales.noby,full))),'receipt: older discount sales keep their discount lines; no cashier line when unknown');
 const bytes=run(h,'rcptBytes('+JSON.stringify(blocks(sales.many,full))+')');ok(bytes.length<12000,'receipt: a 100-item slip is '+bytes.length+' bytes (small enough for BLE)');
 const url=run(h,'rcptUrl(rcptBytes('+JSON.stringify(blocks(sales.base,full))+'))'),b64=url.slice('intent:base64,'.length,url.indexOf('#Intent'));
 ok(url.startsWith('intent:base64,')&&url.endsWith('#Intent;scheme=rawbt;package=ru.a402d.rawbtprinter;end;')&&Buffer.from(b64,'base64').equals(Buffer.from(run(h,'rcptBytes('+JSON.stringify(blocks(sales.base,full))+')'))),'receipt: RawBT link is well formed and decodes back to the same bytes');
 const ts=Array.from(run(h,'rcptTestBlocks({})')).map(b=>b.t);ok(ts.includes('12345678901234567890123456789012')&&ts.every(ascii),'receipt: test slip has a 32-column ruler and plain characters');
 ok(run(h,'rcptHtml(rcptBlocks({no:1,d:"d",t:"t",l:[{n:"<b>x</b>&\\"",q:1,p:1}],tot:1,cash:1}))').includes('&lt;b&gt;x&lt;/b&gt;&amp;&quot;')&&!run(h,'rcptHtml(rcptBlocks({no:1,d:"d",t:"t",l:[{n:"<b>x</b>",q:1,p:1}],tot:1,cash:1}))').includes('<b>x'),'receipt: on-screen slip escapes product names (no HTML injection)');
 ok(run(h,'rcptMode()')==='raw','receipt: Android tablets print directly through RawBT');
 h.ctx.navigator={userAgent:'Mozilla/5.0 (X11; Linux x86_64)'};ok(run(h,'rcptMode()')==='browser','receipt: computers use browser print');
 h.ctx.navigator={userAgent:'Android'};
 const bl=run(h,'rcptBlocks('+JSON.stringify(sales.base)+')');cur=full;
 run(h,'rcptSend(rcptBlocks('+JSON.stringify(sales.base)+'),"raw")');ok(h.ctx.window.location.href.startsWith('intent:base64,')&&prints===0&&/Sent to RawBT/.test(h.el('#rcm').textContent),'receipt: Print sends the slip to RawBT and tells the user what to do if nothing prints');
 h.ctx.window.location={set href(v){throw new Error('no handler')}};run(h,'rcptSend(rcptBlocks('+JSON.stringify(sales.base)+'),"raw")');ok(prints===1&&/browser print/.test(h.el('#rcm').textContent),'receipt: if RawBT cannot be reached it falls back to browser print');
 h.ctx.window.location={href:''};run(h,'receipt('+JSON.stringify(sales.base)+')');ok(/id="prb"/.test(h.el('#rc').innerHTML)&&h.el('#md').hidden===false,'receipt: the popup on a tablet offers Print and Print (browser)');
 h.el('#pr').onclick();ok(h.ctx.window.location.href.startsWith('intent:base64,'),'receipt: the Print button in the popup sends to RawBT');
 h.ctx.navigator={userAgent:'X11'};run(h,'receipt('+JSON.stringify(sales.base)+')');ok(!/id="prb"/.test(h.el('#rc').innerHTML),'receipt: the popup on a computer has a single Print button');
}

{ // Reorder: typing an order quantity must stick (a doubled backslash in the digit regex once reset every entry)
 const h=load('reorder.js',{});h.ctx.S={p:[{id:7,n:'Zed',p:1,s:0,m:5,e:''}],s:[],g:[],suppliers:[],purchases:[]};
 const fire=v=>h.el('#v-rdr').onchange({target:{id:'',classList:{contains:c=>c==='rn'},value:v,dataset:{id:'7'}}});
 fire('12');ok(run(h,'rQ[7]')===12,'reorder: a typed order quantity is kept');
 const t={id:'',classList:{contains:c=>c==='rn'},value:'abc',dataset:{id:'7'}};h.el('#v-rdr').onchange({target:t});
 ok(run(h,'rQ[7]')===12&&t.value==12,'reorder: a non-numeric entry goes back to the last good quantity');
}

// ---- Phase 3: background poll skips unchanged catalog/cart and guards overlap ----
pending.push((async () => {
 const source=fs.readFileSync(path.join(root,'js','main.js'),'utf8');
 const p1={id:1,n:'Tablet',p:10,s:8,m:2};
 const state={S:{p:[{...p1}]},cart:[],ME:{role:'owner'},tab:'sell'};
 const els={'#pm':{hidden:true},'#md':{hidden:true}};
 let poll,grids=0,carts=0,loads=0,live=0;
 let resolveLoad;
 const context={...state, document:{hidden:false,activeElement:null},
   $:id=>els[id],boot(){},setInterval(fn){poll=fn},
   drawGrid(){grids++},drawLines(){carts++},clampCart(){},
   refreshLive:async()=>{live++},
   loadSellState:async()=>{loads++;return {state:true}}};
 vm.createContext(context);vm.runInContext(source,context);
 await poll();
 ok(grids===1&&carts===1,'poll: first refresh synchronizes catalog and cart');
 await poll();
 ok(grids===1&&carts===1,'poll: unchanged state does not rebuild tiles or cart');
 const previousLoad=context.loadSellState;
 context.loadSellState=async()=>({notModified:true});
 await poll();
 ok(grids===1&&carts===1,'poll: HTTP 304 skips unnecessary redraws');
 context.loadSellState=previousLoad;
 context.S={p:[{...p1,s:7}]};
 await poll();
 ok(grids===2&&carts===2,'poll: stock changes refresh product availability');
 context.document.hidden=true;
 await poll();
 ok(loads===3,'poll: hidden browser tabs pause state requests');
 context.document.hidden=false;
 context.document.activeElement={classList:{contains:name=>name==='qn'}};
 await poll();
 ok(loads===3,'poll: quantity input is not interrupted by background refresh');
 context.document.activeElement=null;
 context.loadSellState=()=>new Promise(resolve=>{resolveLoad=resolve});
 const first=poll(),second=poll();
 ok(loads===3,'poll: overlapping refresh requests do not start a second fetch');
 resolveLoad({state:true});
 await Promise.all([first,second]);
 context.tab='live';
 await poll();
 ok(live===1,'poll: live-sales tab retains its own refresh');
})());

// ---- Concurrent state requests: coalesce and retain newer lightweight slices ----
pending.push((async () => {
 const source=fs.readFileSync(path.join(root,'js','core.js'),'utf8').split('function say(t)')[0];
 const calls=[];
 const reply=(state,etag)=>({ok:true,status:200,headers:{get:()=>etag},json:async()=>({state,me:{role:'manager'}})});
 const ctx={document:{querySelector:()=>({textContent:''})},fetch:(url)=>{
   let resolve;const promise=new Promise(r=>resolve=r);calls.push({url,resolve});return promise;
 }};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const full1=vm.runInContext('load()',ctx),full2=vm.runInContext('load()',ctx);
 ok(calls.length===1,'sync: simultaneous full loads share one HTTP request');
 const sell=vm.runInContext('loadSellState()',ctx);
 const live=vm.runInContext('loadLiveState()',ctx);
 calls[1].resolve(reply({p:[{id:1,s:9}],today:'2026-10-24'},'"sell"'));
 calls[2].resolve(reply({s:[{no:2,d:'2026-10-24'}],today:'2026-10-24'},'"live"'));
 await Promise.all([sell,live]);
 calls[0].resolve(reply({p:[{id:1,s:3}],s:[{no:1,d:'2026-10-24'}],g:[{n:'audit'}],today:'2026-10-24'},'"full"'));
 await Promise.all([full1,full2]);
 const result=vm.runInContext('({p:S.p,s:S.s,g:S.g})',ctx);
 ok(result.p[0].s===9 && result.s[0].no===2 && result.g.length===1,
   'sync: delayed full load retains newer catalog and sales while updating audit data');
})());

// ---- Session boundary: old responses must not repopulate the signed-out state ----
pending.push((async () => {
 const source=fs.readFileSync(path.join(root,'js','core.js'),'utf8').split('function say(t)')[0];
 const calls=[];
 const ctx={document:{querySelector:()=>({textContent:''})},fetch:url=>new Promise(resolve=>calls.push({url,resolve}))};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const first=vm.runInContext('load()',ctx);
 const sell=vm.runInContext('loadSellState()',ctx);
 const live=vm.runInContext('loadLiveState()',ctx);
 vm.runInContext('resetSyncSession()',ctx);
 for(const c of calls)c.resolve({ok:true,status:200,headers:{get:()=>'"stale"'},json:async()=>({me:{role:'owner'},state:{p:[{id:1}],s:[{no:1,d:'2026-10-24'}],today:'2026-10-24'}})});
 const results=await Promise.all([first,sell,live]);
 ok(results.every(r=>r.stale) && vm.runInContext('S.p.length===0 && S.s.length===0 && ME===null && !stateETag && !sellETag && !liveETag',ctx),
    'session: delayed full, sell and live responses cannot restore signed-out data');
})());

// ---- Logs: a slow old search cannot replace newer filter results ----
pending.push((async () => {
 const deferred=[];
 const els={};
 const el=key=>els[key]||(els[key]={value:'',textContent:'',innerHTML:'',disabled:false,
   addEventListener(){},setAttribute(){}});
 const ctx={
   $:el,esc:String,URLSearchParams,document:{addEventListener(){},querySelectorAll(){return []}},
   api:url=>new Promise(resolve=>deferred.push({url,resolve}))
 };
 vm.createContext(ctx);
 vm.runInContext(fs.readFileSync(path.join(root,'js','logs.js'),'utf8'),ctx);
 const first=vm.runInContext("drawLogs('inventory')",ctx);
 el('#il-q').value='updated';
 const second=vm.runInContext("drawLogs('inventory')",ctx);
 deferred[1].resolve({items:[{id:2,ts:'2026-10-24',action:'New result',status:'success'}],total:1});
 await second;
 deferred[0].resolve({items:[{id:1,ts:'2026-10-22',action:'Old result',status:'success'}],total:1});
 await first;
 ok(el('#il-list').innerHTML.includes('New result')&&!el('#il-list').innerHTML.includes('Old result'),
   'logs: older search results never replace a newer filter');
 ok(deferred[1].url.includes('q=updated'), 'logs: latest search request includes the current filter');
})());

// ---- Phase 4: archived-day requests cannot redraw the wrong date ----
pending.push((async () => {
 const pendingResponses=[];
 const h=load('reports.js',{ME:{role:'manager'},T:'2026-10-24',
   api:url=>new Promise(resolve=>pendingResponses.push({url,resolve}))});
 h.el('#reportSalesDate').value='2026-10-04';
 const older=run(h,'drawDailySales()');
 h.el('#reportSalesDate').value='2026-10-05';
 const latest=run(h,'drawDailySales()');
 const makeResult=(day,no)=>({date:day,sales:[{no,d:day,t:'01:30 PM',tot:30,l:[{n:'A',q:1}]}],
   days:[{date:day,count:1,voided:0,total:30}],unavailable:[]});
 pendingResponses[1].resolve(makeResult('2026-10-05',888));
 await latest;
 pendingResponses[0].resolve(makeResult('2026-10-04',777));
 await older;
 ok(h.el('#reportSalesDayRows').innerHTML.includes('#888')&&!h.el('#reportSalesDayRows').innerHTML.includes('#777'),
   'reports: slow earlier date response cannot overwrite newer daily transactions');
 ok(h.el('#reportDailyHistoryRows').innerHTML.includes('2026-10-05'),
   'reports: daily totals follow the currently selected date');
 ok(run(h,"saleClockMinutes('01:30 PM')")>run(h,"saleClockMinutes('11:30 AM')")&&
    run(h,"saleClockMinutes('12:00 AM')")<run(h,"saleClockMinutes('12:00 PM')"),
   'reports: noon/midnight and 12-hour sale timestamps sort chronologically');
})());

// ---- Phase 4: grouped-log details ignore out-of-order pagination responses ----
pending.push((async () => {
 const delayed=[];
 const h=load('logs.js',{URLSearchParams,api:url=>new Promise(resolve=>delayed.push({url,resolve})),
   document:{addEventListener(){},querySelectorAll(){return []}}});
 const detailRow={isConnected:true,firstElementChild:{innerHTML:''}};
 h.ctx.detailRow=detailRow;
 const old=run(h,"loadLogOperation('inventory','bulk-1',0,detailRow)");
 const current=run(h,"loadLogOperation('inventory','bulk-1',100,detailRow)");
 delayed[1].resolve({items:[{id:2,action:'New page',status:'success',details:{}}],total:101});
 await current;
 delayed[0].resolve({items:[{id:1,action:'Old page',status:'success',details:{}}],total:101});
 await old;
 ok(detailRow.firstElementChild.innerHTML.includes('New page')&&!detailRow.firstElementChild.innerHTML.includes('Old page'),
   'logs: late detail-page responses cannot replace the current page');
})());

// ---- Phase 4: forecasts and financial totals include archived daily summaries ----
{
 const h=load('reports.js',{T:'2026-10-24',S:{p:[],s:[],g:[]}});
 vm.runInContext(fs.readFileSync(path.join(root,'js','reorder.js'),'utf8'),h.ctx);
 run(h,'reportDays=[{date:"2026-10-10",total:100,count:2,profit:60,revenue_costed:90,lines:2,missing:1}]');
 const cost=run(h,'costStats()'),forecast=run(h,'makeForecast(7)');
 ok(cost.d30.profit===60&&cost.d30.revenue===90&&cost.d30.missing===1,
   'reports: archived sales contribute to 30-day gross profit and missing-cost counts');
 ok(forecast&&forecast.historyDays===15&&forecast.revenue>0,
   'reports: forecast uses historical daily summaries rather than only hot receipts');
}

// ---- Legacy server compatibility: 404 purpose-specific APIs use full state ----
pending.push((async () => {
 const source=fs.readFileSync(path.join(root,'js','core.js'),'utf8').split('function say(t)')[0];
 const routes=[];
 const archived={p:[{id:7,n:'Legacy product',s:4}],s:[{no:42,d:'2026-10-24',tot:100}],
                 g:[],today:'2026-10-24'};
 const ctx={document:{querySelector:()=>({textContent:''})},
   fetch:async url=>{
     routes.push(url);
     if(url==='/api/sell-state'||url==='/api/live-state')
       return {ok:false,status:404,headers:{get:()=>null},json:async()=>({error:'Not found.'})};
     if(url==='/api/state')
       return {ok:true,status:200,headers:{get:()=>''},
               json:async()=>({state:{...archived},me:{role:'manager'}})};
     throw Error('Unexpected endpoint: '+url);
   }};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const sell=await vm.runInContext('loadSellState()',ctx);
 const live=await vm.runInContext('loadLiveState()',ctx);
 ok(!sell.error&&!live.error&&vm.runInContext('S.p[0].id===7&&S.s[0].no===42',ctx),
   'legacy sync: sell and live both recover their state through /api/state');
 const previous=routes.slice();
 await vm.runInContext('loadSellState()',ctx);
 await vm.runInContext('loadLiveState()',ctx);
 ok(routes.filter(u=>u==='/api/sell-state').length===1&&
    routes.filter(u=>u==='/api/live-state').length===1&&
    routes.filter(u=>u==='/api/state').length===4,
   'legacy sync: probes unsupported endpoints once and avoids repeated 404s');
 vm.runInContext('resetSyncSession()',ctx);
 await vm.runInContext('loadLiveState()',ctx);
 ok(routes.filter(u=>u==='/api/live-state').length===2,
   'legacy sync: new login session rechecks whether the optimized endpoint is available');
})());

pending.push((async () => {
 const source=fs.readFileSync(path.join(root,'js','core.js'),'utf8').split('function say(t)')[0];
 const routes=[];
 const ctx={document:{querySelector:()=>({textContent:''})},
   fetch:async url=>{
     routes.push(url);
     return {ok:false,status:503,headers:{get:()=>null},
       json:async()=>({error:'Temporarily unavailable'})};
   }};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const result=await vm.runInContext('loadLiveState()',ctx);
 ok(result.error==='Temporarily unavailable'&&routes.length===1&&
    !vm.runInContext('legacyLiveSync',ctx),
   'legacy sync: genuine server failures are not disguised as unsupported-endpoint fallback');
})());

Promise.all(pending).then(()=>process.exit(bad?1:0),e=>{console.log('FAIL test crashed: '+e);process.exit(1)});
