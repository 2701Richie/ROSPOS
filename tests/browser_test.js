// check: tags=slow,browser
// Real-browser check (headless Chromium over the DevTools protocol; needs only node >= 22 and a chromium binary).
// Signs in as staff, manager and owner against a throw-away server and checks, for every role:
//   - the right tabs are visible and every tab opens with no console error or exception
//   - no tab shows "undefined", "NaN" or "[object Object]"
//   - script planted in product, supplier, user and store names never runs (stored-XSS check, dynamic)
//   - a sale can be completed, and typing an order quantity in Reorder sticks
//   - staff never receive product costs
// Then loads a big catalogue and times how long a tablet takes to draw the Sell grid, refresh and open Products.
// Set CHROMIUM=/path/to/chromium if it is not on the PATH. CHECK_SLOWNESS=2 doubles the time limits.
const fs = require('fs'), os = require('os'), path = require('path'), net = require('net'), cp = require('child_process');
const SRC = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const SLOW = parseFloat(process.env.CHECK_SLOWNESS || '1');
const LEVEL = process.env.CHECK_LEVEL || 'normal';
let bad = 0;
const ok = (c, m) => { console.log((c ? 'ok   ' : 'FAIL ') + m); if (!c) bad++; return c; };
const metric = (n, v, u) => console.log(`METRIC ${n} ${Math.round(v * 10) / 10} ${u || ''}`);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const PW = 'password123';
const XSS = ['<img src=x onerror=window.__xss=1>', '"><svg onload=window.__xss=1>', "'><b id=xss-marker>x</b>"];

function which(cmds) {
  for (const c of cmds) { if (!c) continue; if (c.startsWith('/') && fs.existsSync(c)) return c; try { return cp.execSync('command -v ' + c, { encoding: 'utf8' }).trim() || null; } catch (e) {} }
  return null;
}
const freePort = () => new Promise(res => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });

async function main() {
  const chromium = which([process.env.CHROMIUM, 'chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable']);
  if (!chromium) { console.log('SKIP no chromium found (install it or set CHROMIUM=/path)'); return; }
  if (typeof WebSocket === 'undefined') { console.log('SKIP node has no WebSocket (need node 22+)'); return; }
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rospos-browser-'));
  const app = path.join(tmp, 'app');
  fs.cpSync(SRC, app, { recursive: true, filter: p => !/\/(data|backups|archives|\.git|tests|source-backups|__pycache__)(\/|$)/.test(p.slice(SRC.length)) });
  const port = await freePort();
  let serverLog = '';
  const server = cp.spawn('python3', ['server.py'], { cwd: app, env: { ...process.env, POS_DB: tmp + '/data/pos.db', POS_BACKUP_DIR: tmp + '/backups', POS_ARCHIVE_DIR: tmp + '/archives', POS_PORT: String(port), PYTHONDONTWRITEBYTECODE: '1' } });
  server.stdout.on('data', d => serverLog += d); server.stderr.on('data', d => serverLog += d);
  let chrome = null;
  const cleanup = () => { try { chrome && chrome.kill('SIGKILL'); } catch (e) {} try { server.kill('SIGKILL'); } catch (e) {} setTimeout(() => fs.rmSync(tmp, { recursive: true, force: true }), 200); };
  const killer = setTimeout(() => { console.log('FAIL browser check timed out after 170 s'); cleanup(); process.exit(1); }, 170000);
  try {
    const base = 'http://127.0.0.1:' + port;
    for (let i = 0; i < 100; i++) { try { if ((await fetch(base + '/')).ok) break; } catch (e) {} await sleep(150); }
    const jar = () => ({ c: '' });
    async function api(j, p, body) {
      const r = await fetch(base + p, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'pos', ...(j.c ? { Cookie: j.c } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) });
      for (const c of (r.headers.getSetCookie ? r.headers.getSetCookie() : [])) if (c.startsWith('pos_session=')) j.c = c.split(';')[0];
      return { code: r.status, json: await r.json().catch(() => null) };
    }
    // ---- seed through the real API ----
    const code = (serverLog.match(/SETUP CODE:\s*(\w+)/) || [])[1];
    const owner = jar(), manager = jar(), staff = jar();
    let r = await api(owner, '/api/setup', { code, username: 'owner1', name: 'Owner', password: PW });
    if (!ok(r.code === 200, 'browser: first-run setup works on a fresh server')) throw new Error('setup failed ' + JSON.stringify(r.json));
    await api(owner, '/api/user', { username: 'manager1', name: 'Manager ' + XSS[0], role: 'manager', password: PW });
    await api(owner, '/api/user', { username: 'staff1', name: 'Staff ' + XSS[1], role: 'staff', password: PW });
    await api(owner, '/api/settings', { store: XSS[0], session_hours: 12, backup_days: 30, rc_addr: XSS[1], rc_phone: '', rc_tag: XSS[2], rc_foot: '', password: PW });
    await api(manager, '/api/login', { username: 'manager1', password: PW });
    await api(staff, '/api/login', { username: 'staff1', password: PW });
    const sup = (await api(manager, '/api/supplier', { name: 'Supplier ' + XSS[0] })).json;
    const prods = [['Paracetamol 500mg ' + XSS[0], 5.5, 40, 5, 2.1], ['Amoxicillin ' + XSS[1], 12, 25, 4, 6], ['Cetirizine ' + XSS[2], 8, 2, 6, 3], ['Vitamin C', 3.25, 0, 10, 1], ['Betadine', 90, 12, 3, 55]];
    for (const [n, p, s, m, c] of prods) await api(manager, '/api/product', { n, p, s, m, c, e: '' });
    const state = (await api(manager, '/api/state')).json.state;
    const pid = state.p[0].id;
    const sale = (await api(staff, '/api/sale', { lines: [{ id: pid, q: 2 }], cash: 50 })).json;
    if (sale && sale.sale) await api(manager, '/api/void', { no: sale.sale.no, password: PW, why: XSS[0] });
    if (sup && sup.supplier) await api(manager, '/api/purchase', { product_id: state.p[1].id, supplier_id: sup.supplier.id, quantity: 3, unit_cost: 5, date: '2026-10-01', expiry_date: '2027-10-01', notes: XSS[1] });
    await api(manager, '/api/stock', { id: state.p[2].id, mode: 'set', v: '1', why: XSS[2] });

    // ---- browser ----
    const dbg = await freePort();
    chrome = cp.spawn(chromium, ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--remote-debugging-port=' + dbg, '--user-data-dir=' + tmp + '/chrome', '--window-size=1280,900', 'about:blank'], { stdio: 'ignore' });
    let target = null;
    for (let i = 0; i < 100 && !target; i++) { try { target = (await (await fetch(`http://127.0.0.1:${dbg}/json/list`)).json()).find(t => t.type === 'page'); } catch (e) {} if (!target) await sleep(150); }
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise(res => ws.onopen = res);
    let id = 0; const pending = new Map(); const errors = [];
    ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); return; }
      if (m.method === 'Runtime.exceptionThrown') errors.push('exception: ' + ((m.params.exceptionDetails.exception || {}).description || m.params.exceptionDetails.text).split('\n')[0]);
      if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push('console.error: ' + m.params.args.map(a => a.value || a.description || '').join(' ').slice(0, 160));
      if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error' && !/favicon/.test(m.params.entry.url || m.params.entry.text)) errors.push('log: ' + m.params.entry.text + ' ' + (m.params.entry.url || ''));
    };
    const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
    const js = async expr => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error('page error: ' + ((r.exceptionDetails.exception || {}).description || r.exceptionDetails.text)); return r.result.value; };
    const until = async (expr, ms = 8000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (await js(expr)) return true; } catch (e) {} await sleep(100); } return false; };
    for (const d of ['Runtime', 'Log', 'Page', 'Network']) await send(d + '.enable');
    const frame = () => js('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
    async function login(user) {
      await send('Network.clearBrowserCookies');
      await send('Page.navigate', { url: base + '/' });
      await until("document.querySelector('#au')&&!document.querySelector('#auth').hidden");
      await js(`document.querySelector('#au').value='${user}';document.querySelector('#apw').value='${PW}';document.querySelector('#ago').click()`);
      return until("document.querySelector('#auth').hidden===true&&typeof S!=='undefined'&&S.p&&S.p.length>0");
    }
    const visibleTabs = () => js("[...document.querySelectorAll('.pos-sidebar [data-t]')].filter(b=>!b.hidden).map(b=>b.dataset.t).sort()");
    const want = { staff: 'acc,rcp,rdr,sell,set', manager: 'acc,live,logs,prod,pur,rcp,rdr,rep,sell,set', owner: 'acc,live,logs,prod,pur,rcp,rdr,rep,sell,set' };
    const BADTXT = "(()=>{const t=document.body.innerText;const m=t.match(/.{0,25}(\\bundefined\\b|\\bNaN\\b|\\[object Object\\]).{0,25}/);return m?m[0].replace(/\\s+/g,' '):''})()";
    for (const [role, user] of [['staff', 'staff1'], ['manager', 'manager1'], ['owner', 'owner1']]) {
      const before = errors.length;
      if (!ok(await login(user), `browser ${role}: signs in and loads the catalogue`)) continue;
      const tabs = (await visibleTabs()).join(',');
      ok(tabs === want[role], `browser ${role}: sees exactly these tabs: ${tabs}`);
      const problems = [];
      for (const t of tabs.split(',')) {
        await js(`document.querySelector('.pos-sidebar [data-t="${t}"]').click()`);
        await sleep(350);
        const txt = await js(BADTXT);
        if (txt) problems.push(`${t}: "${txt}"`);
        if (!(await js(`!document.querySelector('#v-${t}')||!document.querySelector('#v-${t}').hidden`))) problems.push(`${t}: the tab did not open`);
      }
      ok(!problems.length, `browser ${role}: every tab opens and shows no undefined/NaN/[object Object]` + (problems.length ? ' -> ' + problems.join('; ') : ''));
      const xss = await js("JSON.stringify({ran:window.__xss||0,marker:!!document.querySelector('#xss-marker')})");
      ok(xss === '{"ran":0,"marker":false}', `browser ${role}: script planted in names, notes and reasons never runs (${xss})`);
      if (role === 'staff') ok(await js("!S.p.some(p=>'c' in p)&&S.purchases===undefined&&!S.s.some(s=>s.l.some(l=>'c' in l))"), 'browser staff: the page data contains no product costs');
      // sell something
      await js("document.querySelector('.pos-sidebar [data-t=\"sell\"]').click()");
      await sleep(200);
      const n0 = await js('S.s.length');
      await js("document.querySelector('#grid .tile:not([disabled])').click()");
      await sleep(150);
      await js("document.querySelector('#pay').click()");
      const sold = await until(`S.s.length>${n0}||!document.querySelector('#md').hidden`, 6000);
      ok(sold, `browser ${role}: tapping a product and Pay completes a sale`);
      // reorder quantity
      await js("document.querySelector('.pos-sidebar [data-t=\"rdr\"]').click()");
      await sleep(300);
      const typed = await js("(()=>{const i=document.querySelector('#v-rdr .rn');if(!i)return 'none';i.value='7';i.dispatchEvent(new Event('change',{bubbles:true}));return document.querySelector('#v-rdr .rn').value})()");
      if (typed !== 'none') ok(typed === '7', `browser ${role}: a typed order quantity in Reorder sticks (shows ${typed})`);
      const fresh = errors.slice(before);
      ok(!fresh.length, `browser ${role}: no console error or exception while using the app` + (fresh.length ? ' -> ' + fresh.slice(0, 3).join(' | ') : ''));
    }
    // ---- a big catalogue on this browser (a tablet is slower: see CHECK_SLOWNESS) ----
    const N = LEVEL === 'fast' ? 1500 : 4000;
    for (let s = 0; s < N; s += 2000) {
      const rows = []; for (let i = s; i < Math.min(N, s + 2000); i++) rows.push({ name: 'Perf Item ' + String(i).padStart(5, '0') + ' Tablet', price: String(1 + i % 90) + '.50', quantity: String(5 + i % 40), reorder: '3' });
      await api(owner, '/api/import', { mode: 'products', apply: true, why: 'perf', rows });
    }
    if (await login('manager1')) {
      await js("document.querySelector('.pos-sidebar [data-t=\"sell\"]').click()"); await sleep(300);
      const timed = async body => js(`(async()=>{const t=performance.now();await (async()=>{${body}})();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return performance.now()-t})()`);
      const cnt = await js('S.p.length');
      const grid = await timed("if(typeof drawGrid==='function')drawGrid()");
      const refresh = await timed("if(typeof load==='function')await load();if(typeof clampCart==='function')clampCart();if(typeof drawGrid==='function')drawGrid();if(typeof drawLines==='function')drawLines()");
      const prod = await timed("document.querySelector('.pos-sidebar [data-t=\"prod\"]').click()");
      const nodes = await js('document.querySelectorAll("*").length');
      metric('browser_catalogue_products', cnt, 'products'); metric('browser_sell_grid_draw', grid, 'ms'); metric('browser_refresh_cycle', refresh, 'ms'); metric('browser_open_products', prod, 'ms'); metric('browser_dom_nodes', nodes, 'nodes');
      ok(grid <= 1500 * SLOW, `browser perf: drawing the Sell grid for ${cnt} products took ${Math.round(grid)} ms (limit ${1500 * SLOW})`);
      ok(refresh <= 2500 * SLOW, `browser perf: the 5-second refresh cycle took ${Math.round(refresh)} ms (limit ${2500 * SLOW})`);
      ok(prod <= 3000 * SLOW, `browser perf: opening Products took ${Math.round(prod)} ms (limit ${3000 * SLOW})`);
    } else ok(false, 'browser perf: could not sign in to the big catalogue');
    ok(!/Traceback|Exception/.test(serverLog), 'browser: the server log shows no crash during the whole run' + (/Traceback/.test(serverLog) ? ' -> ' + serverLog.slice(serverLog.indexOf('Traceback'), serverLog.indexOf('Traceback') + 200) : ''));
  } catch (e) {
    ok(false, 'browser check crashed: ' + (e.stack || e).toString().split('\n').slice(0, 3).join(' | '));
  } finally {
    clearTimeout(killer);
    cleanup();
  }
}
main().then(() => { console.log(bad ? 'FAILED ' + bad : 'ALL PASSED'); process.exit(bad ? 1 : 0); });
