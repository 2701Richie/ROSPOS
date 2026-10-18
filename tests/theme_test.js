const fs=require('fs'),vm=require('vm'),path=require('path');
const src=fs.readFileSync(path.join(process.argv[2]||path.join(__dirname,'..'),'js/settings.js'),'utf8');
let bad=0;const ok=(c,m)=>{console.log((c?'ok   ':'FAIL ')+m);if(!c)bad++};
function make(store,throwing){
 const els={};const el=id=>els[id]||(els[id]={value:'',textContent:'',title:'',attrs:{},className:'',setAttribute(k,v){this.attrs[k]=v}});
 const ls=throwing?{getItem(){throw new Error('blocked')},setItem(){throw new Error('blocked')},removeItem(){throw new Error('blocked')}}:{getItem:k=>(k in store?store[k]:null),setItem:(k,v)=>{store[k]=v},removeItem:k=>{delete store[k]}};
 const ctx={S:{},$:s=>el(s),api:async()=>({}),document:{documentElement:{dataset:{}},querySelector:()=>null,title:''},localStorage:ls};
 vm.createContext(ctx);vm.runInContext(src,ctx);return{ctx,el,root:ctx.document.documentElement};
}
let st={},a=make(st);
ok(a.root.dataset.theme===undefined&&a.el('#tb').textContent==='◐','starts on Automatic');
a.el('#tb').onclick();ok(st['pos-theme']==='light'&&a.root.dataset.theme==='light'&&a.el('#tb').textContent==='☀','tap 1: Light is forced and saved');
a.el('#tb').onclick();ok(st['pos-theme']==='dark'&&a.root.dataset.theme==='dark'&&a.el('#tb').textContent==='☾','tap 2: Dark is forced and saved');
ok(/Dark/.test(a.el('#tb').attrs['aria-label']),'accessible label names the current theme');
a.el('#tb').onclick();ok(!('pos-theme' in st)&&a.root.dataset.theme===undefined,'tap 3: back to Automatic, saved choice cleared');
let b=make({'pos-theme':'dark'});ok(b.root.dataset.theme==='dark'&&b.el('#tb').textContent==='☾','saved Dark is applied on load');
let c=make({'pos-theme':'garbage'});ok(c.root.dataset.theme===undefined,'unknown saved value is ignored');
let d=make({},true);d.el('#tb').onclick();ok(d.root.dataset.theme==='light','still works when browser storage is blocked');
process.exit(bad?1:0);
