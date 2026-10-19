// JS logic tests: runs js/*.js in a sandbox with a fake page (no browser needed).
// Usage: node tests/js_logic_test.js [source-folder]     Output: 'ok   ...' / 'FAIL ...' lines
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[2]||path.join(__dirname,'..');
let bad=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)bad++};
function load(file,extra){
 const els={};const el=id=>els[id]||(els[id]={value:'',textContent:'',innerHTML:'',hidden:false,style:{},title:''});
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
 run(h,'badge()');ok(h.el('#rdrb').textContent==='Reorder (2)','reorder: tab badge counts zero-stock items');
 ok(names(run(h,'picked()'))==='Alpha,Gamma','reorder: zero-stock items are ticked by default in the order list');
 ok((run(h,'picked()').find(x=>x.n==='Alpha')||{}).q===1,'reorder: default order quantity for a zero-level product is 1');
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
 ok(h.el('#fsb').style.display!=='none'&&h.el('#fsb').textContent==='Full screen','fullscreen: button shown with label Full screen');
 h.el('#fsb').onclick();ok(calls.join()==='req','fullscreen: tap asks the browser for full screen; a refused request does not throw');
 doc.fullscreenElement={};ls.fullscreenchange();ok(h.el('#fsb').textContent==='Exit full screen','fullscreen: label changes to Exit full screen');
 h.el('#fsb').onclick();ok(calls.join()==='req,exit','fullscreen: tap while full screen exits it');
 doc.fullscreenElement=null;ls.fullscreenchange();ok(h.el('#fsb').textContent==='Full screen','fullscreen: label returns to Full screen');
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
 const r2=run(h,"toRows('name,price\\nA,10')");ok(!r2.error&&r2.rows[0].cost==='','cost csv: a file with no cost column still reads');
 h.el('#ie').onclick();const ex=lines(blobs[0]);
 ok(ex[0]==='name,price,reorder,quantity,cost'&&ex[1]==='A,9,0,4,'&&ex[2]==='B,5,2,1,3','cost csv: export has a cost column (blank when unknown)');
 h.el('#it').onclick();ok(lines(blobs[1])[0]==='name,price,reorder,quantity,cost','cost csv: template has a cost column');
}

Promise.all(pending).then(()=>process.exit(bad?1:0),e=>{console.log('FAIL test crashed: '+e);process.exit(1)});
