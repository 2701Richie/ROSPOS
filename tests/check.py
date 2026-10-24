#!/usr/bin/env python3
"""ROSPOS check engine: one command runs every check, prints ONE summary line, then only what failed.

  python3 tests/check.py                 everything, on the working tree (uncommitted edits included)
  python3 tests/check.py --fast          quick pass (~10 s): smaller random runs, skips tests tagged slow
  python3 tests/check.py --deep          thorough pass: 5x more fuzz requests and simulation steps
  python3 tests/check.py --clone         clone GitHub (origin) into a temp folder and check that (run after every push)
  python3 tests/check.py --only fuzz,sim --skip browser     pick checks by name (substring match)
  python3 tests/check.py --seed N        repeat a random run exactly (printed in the summary; --seed random for a new one)
  python3 tests/check.py --table | -v | --json FILE | --list
  python3 tests/check.py --new NAME      create tests/NAME_test.py from the template (picked up automatically)
  python3 tests/check.py --selftest      inject known old bugs into a temp copy and prove the checks catch them

A check is any tests/*_test.py, tests/*_test.js or tests/e2e.py. It prints 'ok   <what>' / 'FAIL <what>' lines, optional
'METRIC name value unit' lines, 'SKIP <reason>' if it cannot run here, and exits 1 on failure. Optional tag on line 1-5:
'# check: tags=slow,security'. The runner gives it: argv[1]=source folder, env CHECK_LEVEL (fast|normal|deep),
CHECK_SEED, CHECK_SLOWNESS. Full results of the last run (every failure, metrics, timings, the command to repeat a
single check) are written to <temp>/rospos-check-last.json.

Everything runs on throw-away data in temp folders. The real data/, backups/, archives/ and every file of the repo are
compared before and after to prove nothing was touched. The real POS server is never started, stopped or restarted.
Exit code 0 = all passed, 1 = something failed.
"""
import argparse, concurrent.futures as cf, glob, json, os, random, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_TERMINAL_PROMPT="0")  # git must fail fast, never wait for a password
NOT_CHECKS = {"harness.py", "check.py", "run.py"}
LAST = os.path.join(tempfile.gettempdir(), "rospos-check-last.json")


def sh(cmd, cwd=None, timeout=180):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT after %ds: %s" % (timeout, " ".join(cmd))


def discover(tests):
    out = []
    for path in sorted(glob.glob(os.path.join(tests, "*"))):
        base = os.path.basename(path)
        if base in NOT_CHECKS or not (base.endswith(("_test.py", "_test.js")) or base == "e2e.py"):
            continue
        head = open(path, encoding="utf-8", errors="replace").read(600).splitlines()[:5]
        m = next((re.search(r"check:\s*tags=([\w,-]+)", l) for l in head if "check:" in l), None)
        name = re.sub(r"(_test)?\.(py|js)$", "", base)
        out.append({"name": name, "file": base, "path": path, "kind": "py" if base.endswith(".py") else "js", "tags": m.group(1).split(",") if m else []})
    return out


def snapshot(src):
    """Size + mtime of live data folders and every file git knows or would add: nothing may change during a run."""
    out = {}
    for d in ("data", "backups", "archives"):
        for f in glob.glob(os.path.join(src, d, "**", "*"), recursive=True):
            if os.path.isfile(f):
                st = os.stat(f)
                out["live:" + f] = (st.st_size, st.st_mtime_ns)
    rc, names = sh(["git", "-C", src, "ls-files", "-z", "-c", "-o", "--exclude-standard"], timeout=30)
    if rc == 0:
        for n in names.split("\0"):
            f = os.path.join(src, n)
            if n and os.path.isfile(f):
                st = os.stat(f)
                out["repo:" + n] = (st.st_size, st.st_mtime_ns)
    return out


def parse(text, rc):
    lines = text.splitlines()
    res = {"passed": 0, "failed": [], "skip": None, "metrics": {}}
    summary = next((l for l in lines if l.startswith("SUMMARY ")), None)
    if summary:  # the older numeric test reports PASS= WARN= FAIL= counts
        n = {k: int(v) for k, v in (x.split("=") for x in summary.split()[1:] if "=" in x)}
        res["passed"] = n.get("PASS", 0)
        res["failed"] = [l for l in lines if l.startswith(("[FAIL]", "[WARN]"))]
        res["total"] = n.get("PASS", 0) + n.get("WARN", 0) + n.get("FAIL", 0)
    else:
        res["passed"] = sum(1 for l in lines if l.startswith("ok   "))
        res["failed"] = [l[5:] for l in lines if l.startswith("FAIL ")]
        res["total"] = res["passed"] + len(res["failed"])
    for l in lines:
        m = re.match(r"METRIC (\S+) (\S+) ?(.*)", l)
        if m:
            res["metrics"][m.group(1)] = {"value": float(m.group(2)) if re.fullmatch(r"-?[\d.]+", m.group(2)) else m.group(2), "unit": m.group(3)}
    skip = next((l for l in lines if l.startswith("SKIP")), None)
    if skip and res["passed"] == 0 and not res["failed"]:
        res["skip"] = skip[4:].strip(" :")
    elif rc != 0 and not res["failed"]:
        res["failed"] = ["(exit code %d, no FAIL line) %s" % (rc, " | ".join(l for l in lines if l.strip())[-300:])]
    elif rc == 0 and res["total"] == 0:
        res["failed"] = ["reported no checks at all (a test that prints nothing proves nothing)"]
    return res


def run_check(c, src, env, timeout):
    t0 = time.time()
    cmd = [sys.executable if c["kind"] == "py" else "node", c["path"], src]
    try:
        p = subprocess.run(cmd, cwd=src, env=env, capture_output=True, text=True, timeout=timeout)
        rc, text = p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        rc, text = 124, "FAIL timed out after %ds" % timeout
    except FileNotFoundError:
        rc, text = 0, "SKIP %s is not installed" % cmd[0]
    r = parse(text, rc)
    r.update(name=c["name"], file=c["file"], tags=c["tags"], seconds=round(time.time() - t0, 1), output=text[-30000:],
             rerun="python3 tests/%s" % c["file"])
    return r


def new_test(tests, name):
    path = os.path.join(tests, "%s_test.py" % name)
    if os.path.exists(path):
        sys.exit("already exists: " + path)
    open(path, "w", encoding="utf-8").write('''# check: tags=logic
"""What this check proves, in one or two sentences."""
from harness import *

srv, SRC, TMP = boot("rospos-%s-")   # throw-away database; the real data/ is never opened
R = Report()
store = Store(srv)
ids = seed(store)                    # owner/manager/staff, suppliers, 4 products, 1 sale, 1 purchase

# store.call(path, body, role)  -> Resp(.code, .obj, .data); role is "staff" | "manager" | "owner" | None (signed out)
r = store.call("/api/stock", {"id": ids["P"][0], "mode": "set", "v": "7", "why": "demo"}, "manager")
R.ok(r.code == 200 and srv.prod(ids["P"][0])["s"] == 7, "a manager can set stock")
R.ok(store.call("/api/stock", {"id": ids["P"][0], "mode": "set", "v": "8"}, "staff").code == 403, "staff cannot set stock")
R.ok(not invariants(srv), "the store still obeys every rule")   # invariants() lists any broken rule

shutil.rmtree(TMP, ignore_errors=True)
R.done()
''' % name)
    print("created", path, "- run it alone with: python3 tests/%s_test.py   (check.py finds it automatically)" % name)


# Each known old bug: (name, file, text to find, text to put instead, checks that must notice)
MUTATIONS = [
    ("expiry not validated", "server.py", '    if not valid_expiry(e):\n        raise Err(400, "Enter a valid expiry date, or leave it blank.")\n', "", "fuzz,backend_fixes,simulation"),
    ("duplicate product names allowed", "server.py", 'if clash and (own is None or key(own["n"]) != k):', "if False:", "backend_fixes,simulation"),
    ("restore accepts mismatched sale totals", "server.py", '    if any(not x.get("dc") and abs(R(sum(l["q"] * l["p"] for l in x["l"])) - x["tot"]) > 0.01 for x in d["s"]):\n        raise Err(400, "The backup contains a sale whose total does not match its items.")  # would corrupt every report\n', "", "fuzz"),
    ("void does not put stock back", "server.py", '    p = find_prod(l)\n    if p:\n        o = p["s"]', '    p = find_prod(l)\n    if p and False:\n        o = p["s"]', "simulation,backend_fixes"),
    ("stock endpoint open to staff", "server.py", 'def r_stock(b, ip):\n    allow("manager")', "def r_stock(b, ip):\n    pass", "permissions,source_scan"),
    ("reorder quantity regex doubled backslash", "js/reorder.js", "/^\\d+$/.test(v)", "/^\\\\d+$/.test(v)", "js_logic,source_scan"),
    ("expiry printed into page unescaped", "js/core.js", "'+esc(p.e)+'", "'+p.e+'", "source_scan"),
]


def selftest(src, jobs):
    base = tempfile.mkdtemp(prefix="rospos-selftest-")
    me = os.path.abspath(__file__)

    def one(m):
        name, rel, old, new, expect = m
        work = os.path.join(base, re.sub(r"\W+", "-", name))
        shutil.copytree(src, work, ignore=shutil.ignore_patterns("data", "backups", "archives", ".git", "__pycache__", "source-backups"))
        p = os.path.join(work, rel)
        text = open(p, encoding="utf-8").read()
        if text.count(old) != 1:
            return name, None, "the code this mutation edits has changed (%d matches in %s) - update MUTATIONS in tests/check.py" % (text.count(old), rel)
        open(p, "w", encoding="utf-8").write(text.replace(old, new))
        rc, out = sh([sys.executable, me, "--src", work, "--only", expect, "--fast", "--json", os.path.join(work, "r.json")], timeout=300)
        caught = rc != 0 and "FAIL" in out
        who = ", ".join(sorted({l.split("]")[0].strip(" [") for l in out.splitlines() if l.startswith("  [")}))
        return name, caught, who

    with cf.ThreadPoolExecutor(jobs) as ex:
        results = list(ex.map(one, MUTATIONS))
    shutil.rmtree(base, ignore_errors=True)
    bad = 0
    for name, caught, who in results:
        if caught is None:
            print("  ?? %-45s %s" % (name, who))
            bad += 1
        else:
            print("  %s %-45s %s" % ("caught" if caught else "MISSED", name, ("by " + who) if caught else "no check noticed this bug"))
            bad += 0 if caught else 1
    print("%s  selftest: %d of %d injected bugs were caught" % ("FAIL" if bad else "PASS", len(results) - bad, len(results)))
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src")
    ap.add_argument("--clone", nargs="?", const="origin")
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--seed", default="1")
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 2))
    ap.add_argument("--json")
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--new")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    if a.new:
        return new_test(HERE, re.sub(r"\W+", "_", a.new.lower()))
    t0, tmp = time.time(), None
    if a.clone:
        url = a.clone
        if url == "origin":
            rc, out = sh(["git", "-C", ROOT, "remote", "get-url", "origin"], timeout=15)
            url = out.strip() if rc == 0 else ""
            if not url:
                sys.exit("FAIL no 'origin' remote to clone")
        tmp = tempfile.mkdtemp(prefix="rospos-run-")
        rc, out = sh(["git", "clone", "-q", url, tmp + "/clone"], timeout=120)
        if rc:
            shutil.rmtree(tmp, ignore_errors=True)
            sys.exit("FAIL clone: " + out.strip()[-300:])
        src, label = tmp + "/clone", "clone"
    else:
        src = os.path.abspath(a.src or ROOT)
        label = "working tree" if not a.src else "folder"
    tests = os.path.join(src, "tests") if os.path.isdir(os.path.join(src, "tests")) else HERE
    if a.selftest:
        selftest(src, a.jobs)
    checks = discover(tests)
    only, skip = [x for x in a.only.split(",") if x], [x for x in a.skip.split(",") if x]
    if only:
        checks = [c for c in checks if any(o in c["name"] for o in only)]
    checks = [c for c in checks if not any(s in c["name"] for s in skip)]
    if a.list:
        for c in checks:
            print("%-22s %-28s %s" % (c["name"], c["file"], ",".join(c["tags"])))
        return
    level = "fast" if a.fast else "deep" if a.deep else "normal"
    seed = str(random.randint(1, 99999)) if a.seed == "random" else a.seed
    skipped_slow = [c for c in checks if a.fast and "slow" in c["tags"]]
    checks = [c for c in checks if c not in skipped_slow]
    env = dict(ENV, CHECK_LEVEL=level, CHECK_SEED=seed)
    before = snapshot(src) if not a.clone else {}
    with cf.ThreadPoolExecutor(max(1, a.jobs)) as ex:
        results = list(ex.map(lambda c: run_check(c, src, env, 300 if "slow" in c["tags"] else 150), checks))
    after = snapshot(src) if not a.clone else {}
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    live_changed = [k for k in changed if k.startswith("live:")]
    repo_changed = [k[5:] for k in changed if k.startswith("repo:")]
    rc, h = sh(["git", "-C", src, "rev-parse", "--short", "HEAD"], timeout=15)
    desc = "%s @%s%s" % (label, h.strip() if rc == 0 else "no-git", "+uncommitted" if rc == 0 and sh(["git", "-C", src, "status", "--porcelain"], timeout=15)[1].strip() else "")
    failed = [r for r in results if r["failed"]]
    skipped = [r for r in results if r["skip"]]
    total_ok, total_n = sum(r["passed"] for r in results), sum(r["total"] for r in results)
    bad = bool(failed or live_changed or repo_changed)
    print("%s  %d checks, %d assertions, %d failed, %d skipped | data %s | repo %s | %s | %s seed %s | %ds" % (
        "FAIL" if bad else "PASS", len(results), total_n, sum(len(r["failed"]) for r in results), len(skipped) + len(skipped_slow),
        "CHANGED" if live_changed else "untouched", "CHANGED" if repo_changed else "untouched", desc, level, seed, time.time() - t0))
    for r in failed:
        print("  [%s] %d failed   repeat: CHECK_SEED=%s %s" % (r["name"], len(r["failed"]), seed, r["rerun"]))
        for line in r["failed"][:6]:
            print("      " + line[:240])
        if len(r["failed"]) > 6:
            print("      ... %d more (see %s)" % (len(r["failed"]) - 6, LAST))
    if live_changed:
        print("  [data] the real data/backups/archives changed during the run: " + ", ".join(live_changed[:3]))
    if repo_changed:
        print("  [repo] files changed during the run (a check wrote into the repo, or another editor was working): " + ", ".join(repo_changed[:5]))
    for r in skipped:
        print("  skipped %s: %s" % (r["name"], r["skip"]))
    if skipped_slow:
        print("  skipped (slow, --fast): " + ", ".join(c["name"] for c in skipped_slow))
    if a.table:
        for r in results:
            print("  %-22s %4d/%-4d %6.1fs %s" % (r["name"], r["passed"], r["total"], r["seconds"], "SKIP" if r["skip"] else ""))
    metrics = {f"{r['name']}.{k}": v for r in results for k, v in r["metrics"].items()}
    if a.table and metrics:
        print("  metrics: " + ", ".join("%s=%s%s" % (k, v["value"], v["unit"]) for k, v in metrics.items() if not k.startswith("fuzz")))
    if a.verbose:
        for r in results:
            print("\n===== %s =====\n%s" % (r["name"], r["output"]))
    report = {"status": "FAIL" if bad else "PASS", "level": level, "seed": seed, "source": src, "description": desc, "seconds": round(time.time() - t0, 1),
              "data_changed": live_changed, "repo_changed": repo_changed, "checks": [{k: r[k] for k in ("name", "file", "passed", "total", "failed", "skip", "seconds", "metrics", "rerun")} for r in results]}
    for path in (LAST, a.json):
        if path:
            json.dump(report, open(path, "w"), indent=1)
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
