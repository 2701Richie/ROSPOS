// JS logic tests: runs js/*.js in a sandbox with a fake page (no browser needed).
// Usage: node tests/js_logic_test.js [source-folder]     Output: 'ok   ...' / 'FAIL ...' lines
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[2]||path.join(__dirname,'..');
let bad=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)bad++};
function load(file,extra){
 const els={};const el=id=>els[id]||(els[id]={value:'',textContent:'',innerHTML:'',hidden:false,style:{},title:''});
 const ctx=Object.assign({$:s=>el(s),document:{querySelector:s=>el(s)},window:{},localStorage:{getItem:()=>null,setItem(){}},
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

// ---- Sell: bulk quantity per tap ----
{
 const h=load('sell.js',{S:{p:[{id:1,n:'Alpha',p:2,s:12,e:'',m:0},{id:2,n:'Old',p:2,s:5,e:'2020-01-01',m:0}],s:[],g:[]}});
 const q=v=>{h.el('#bq').value=v;return run(h,'bq()')};
 ok(q('abc')===1&&q('0')===1&&q('-3')===1&&q('')===1,'sell: blank, zero, negative or text quantity means 1');
 ok(q('7')===7&&q('5abc')===5&&q('999999999')===100000,'sell: typed quantity is used and capped at 100000');
 run(h,'add(1,5)');ok(h.ctx.cart[0].q===5,'sell: bulk add puts 5 in the cart in one tap');
 run(h,'add(1,5)');ok(h.ctx.cart.length===1&&h.ctx.cart[0].q===10,'sell: adding again increases the same cart line (10)');
 const r=run(h,'add(1,5)');ok(r===false&&h.ctx.cart[0].q===10&&/Not enough stock/.test(h.ctx.said)&&/12/.test(h.ctx.said),'sell: over the stock is refused, cart unchanged, message shows stock');
 run(h,'add(1)');ok(h.ctx.cart[0].q===11,'sell: add with no quantity still adds 1');
 ok(run(h,'add(2,1)')===false&&/Expired/.test(h.ctx.said)&&h.ctx.cart.length===1,'sell: expired product cannot be sold in bulk either');
 h.el('#bq').value='5';h.el('#grid').onclick({target:{closest:()=>({dataset:{id:'1'}})}});
 ok(h.ctx.cart[0].q===11&&h.el('#bq').value==='5','sell: refused tap keeps the typed quantity so it can be corrected');
 h.ctx.cart.length=0;h.el('#bq').value='5';h.el('#grid').onclick({target:{closest:()=>({dataset:{id:'1'}})}});
 ok(h.ctx.cart[0].q===5&&h.el('#bq').value===1,'sell: tapping a product adds the typed quantity, then resets to 1');
 h.ctx.cart.length=0;h.el('#bq').value='10';h.el('#q').onkeydown({key:'Enter',target:{value:'Alpha'}});
 ok(h.ctx.cart[0]&&h.ctx.cart[0].q===10,'sell: Enter in search adds the typed quantity');
 h.el('.bq').onclick({target:{closest:()=>({dataset:{bq:'10'}})}});ok(h.el('#bq').value==='10','sell: quick button 10 sets the quantity');
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

Promise.all(pending).then(()=>process.exit(bad?1:0),e=>{console.log('FAIL test crashed: '+e);process.exit(1)});
