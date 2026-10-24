# check: tags=static
"""Static checks on the source (no server needed): syntax, known bug patterns, page/server wiring, permission calls."""
import ast, glob, os, re, shutil, subprocess, sys, warnings
from harness import Report

SRC = os.path.abspath([a for a in sys.argv[1:] if not a.startswith("-")][0]) if [a for a in sys.argv[1:] if not a.startswith("-")] else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = Report()
def read(p):
    with open(os.path.join(SRC, p), encoding="utf-8") as fh:
        return fh.read()
JS = sorted(glob.glob(os.path.join(SRC, "js", "*.js")))
rel = lambda p: os.path.relpath(p, SRC)

# 1. syntax: python (warnings count as errors, e.g. a bad \d escape) and javascript
py_bad = []
for p in ["server.py"] + sorted(os.path.relpath(x, SRC) for x in glob.glob(os.path.join(SRC, "tests", "*.py"))):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compile(read(p), p, "exec")
    except (SyntaxError, SyntaxWarning, DeprecationWarning) as e:
        py_bad.append("%s: %s" % (p, e))
R.ok(not py_bad, "python files compile cleanly, with no invalid escape sequences" + ("" if not py_bad else " -> " + py_bad[0]))
if shutil.which("node"):
    js_bad = [rel(f) + ": " + subprocess.run(["node", "--check", f], capture_output=True, text=True).stderr.strip().splitlines()[0]
              for f in JS + [x for x in glob.glob(os.path.join(SRC, "tests", "*.js"))]
              if subprocess.run(["node", "--check", f], capture_output=True, text=True).returncode]
    R.ok(not js_bad, "all %d javascript files pass a syntax check" % len(JS) + ("" if not js_bad else " -> " + js_bad[0]))
else:
    print("SKIP node not installed: javascript syntax not checked")

# 2. a regex written with a doubled backslash (/^\\d+$/) matches a literal backslash, never digits
RX = r"/((?:[^/\\\n]|\\.)+)/[gimsuy]*"
dbl = []
for f in JS:
    for n, line in enumerate(read(rel(f)).splitlines(), 1):
        for m in re.finditer(RX + r"\.(?:test|exec)\(|\.(?:match|matchAll|replace|replaceAll|split|search)\(\s*" + RX, line):
            body = m.group(1) or m.group(2)
            if body and re.search(r"(?<!\\)\\\\[dDwWsSbB.]", body):
                dbl.append("%s:%d /%s/" % (rel(f), n, body))
R.ok(not dbl, "no regex literal has a doubled backslash that can never match" + ("" if not dbl else " -> " + "; ".join(dbl[:3])))

# 3. every element id the scripts look up exists in index.html or is created by the scripts themselves
html, alljs = read("index.html"), "\n".join(read(rel(f)) for f in JS)
defined = set(re.findall(r'\bid=\\?"([^"\\]+)\\?"', html + alljs)) | set(re.findall(r"\bid=\\?'([^'\\]+)\\?'", alljs)) | set(re.findall(r"\.id\s*=\s*'([^']+)'", alljs))
used = set(re.findall(r"""\$\(\s*['"]#([A-Za-z][\w-]*)['"]\s*\)""", alljs)) | set(re.findall(r"""getElementById\(\s*['"]([\w-]+)['"]""", alljs)) | set(re.findall(r"""querySelector\(\s*['"]#([\w-]+)['"]""", alljs))
missing = sorted(used - defined)
R.ok(not missing, "every element id the scripts use exists on the page (%d ids)" % len(used) + ("" if not missing else " -> missing: " + ", ".join(missing[:8])))
ids_html = re.findall(r'\bid="([^"]+)"', html)
dups = sorted({i for i in ids_html if ids_html.count(i) > 1})
R.ok(not dups, "no element id appears twice in index.html" + ("" if not dups else " -> " + ", ".join(dups)))
scripts = re.findall(r'<script[^>]*src="/js/([^"]+)"', html)
unused = sorted({os.path.basename(f) for f in JS} - set(scripts))
R.ok(not unused and not [s for s in scripts if not os.path.isfile(os.path.join(SRC, "js", s))], "index.html loads every script file and every script it names exists" + ("" if not unused else " -> not loaded: " + ", ".join(unused)))

# 4. every /api/ address the page calls exists on the server
server_src = read("server.py")
server_routes = set(re.findall(r'"(/api/[a-z-]+)"', server_src))
called = {}
for f in JS:
    for m in re.finditer(r"""['"`](/api/[a-z-]+)""", read(rel(f))):
        called.setdefault(m.group(1), rel(f))
ghost = sorted(r for r in called if r not in server_routes)
R.ok(not ghost, "every /api/ address the page calls exists on the server (%d addresses)" % len(called) + ("" if not ghost else " -> unknown: " + ", ".join("%s (%s)" % (g, called[g]) for g in ghost)))

# 5. every write endpoint checks who is asking
tree = ast.parse(server_src)
funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
routes = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "ROUTES" for t in node.targets) and isinstance(node.value, ast.Dict):
        routes = {k.value: v.id for k, v in zip(node.value.keys, node.value.values)}
STAFF_OK = {"r_sale", "r_mypw"}  # any signed-in user (do_POST already requires a session for everything but login/setup)
unchecked = []
for path, fn in routes.items():
    calls = {c.func.id for c in ast.walk(funcs[fn]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    if fn not in STAFF_OK and not calls & {"allow", "reauth"}:
        unchecked.append("%s (%s)" % (path, fn))
R.ok(routes and not unchecked, "every endpoint function calls allow() or reauth() (%d endpoints)" % len(routes) + ("" if not unchecked else " -> no permission check: " + ", ".join(unchecked)))

# 6. SQL must use ? placeholders, never text pasted together from variables
risky = []
for n in ast.walk(tree):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("execute", "executemany") and n.args:
        a = n.args[0]
        if isinstance(a, ast.JoinedStr) or (isinstance(a, ast.BinOp) and isinstance(a.op, ast.Mod)) or \
           (isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute) and a.func.attr == "format"):
            risky.append("server.py:%d" % n.lineno)
R.ok(not risky, "no SQL statement is built by formatting text into it" + ("" if not risky else " -> " + ", ".join(risky[:5])))
dangerous = [w for w in ("eval(", "exec(", "os.system(", "shell=True", "pickle.", "__import__(") if w in server_src]
R.ok(not dangerous, "server.py uses no eval/exec/shell/pickle" + ("" if not dangerous else " -> " + ", ".join(dangerous)))
js_danger = [rel(f) + ": " + w for f in JS for w in ("eval(", "new Function(", "document.write(") if w in read(rel(f))]
R.ok(not js_danger, "scripts use no eval, new Function or document.write" + ("" if not js_danger else " -> " + ", ".join(js_danger[:3])))

# 7. text typed by people must go through esc() before it is placed in the page
FREE = r"(?:n|name|e|w|by|u|notes|note|supplier_name|product_name|store|username|reason|rc_addr|rc_phone|rc_tag|rc_foot)"
CHAIN = r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|\[[^\]]+\])*\." + FREE
bare = []
for f in JS:
    for n, line in enumerate(read(rel(f)).splitlines(), 1):
        for m in re.finditer(r"""['"]\s*\+\s*(%s)\s*\+\s*['"]|\$\{\s*(%s)(?:\s*\|\|\s*[^}]*)?\}""" % (CHAIN, CHAIN), line):
            seg = line[max(0, m.start() - 160):m.start()].split(";")[-1]
            if re.search(r"(?:say|confirm|alert)\(|textContent\s*=|\.value\s*=|\.title\s*=", seg):
                continue  # plain-text sinks: the browser does not read markup there
            bare.append("%s:%d %s" % (rel(f), n, m.group(1) or m.group(2)))
R.ok(not bare, "text fields are never placed into page markup without esc()" + ("" if not bare else " -> " + "; ".join(bare[:12])))

# 8. no live store data is committed
if os.path.isdir(os.path.join(SRC, ".git")) and shutil.which("git"):
    tracked = subprocess.run(["git", "-C", SRC, "ls-files"], capture_output=True, text=True).stdout.split()
    live = [t for t in tracked if re.match(r"(data|backups|archives|source-backups)/|.*\.(db|sqlite3?)(-wal|-shm)?$", t)]
    R.ok(not live, "no database, backup or archive file is tracked by git" + ("" if not live else " -> " + ", ".join(live[:3])))
R.done()
