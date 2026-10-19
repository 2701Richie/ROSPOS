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

process.exit(bad?1:0);
