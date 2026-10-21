#!/usr/bin/env python3
"""One command for every POS check. Prints ONE summary line, then only the failures.

  python3 tests/run.py                   test the working tree (this folder, uncommitted edits included)
  python3 tests/run.py --clone           clone GitHub (origin) into a temp folder and test that
  python3 tests/run.py --clone URL|PATH  clone something else and test it
  python3 tests/run.py --src DIR         test another folder
  python3 tests/run.py -v                also print the full output of every check

Everything runs against throw-away databases in temp folders. The real data/, backups/ and
archives/ are checked before and after to prove they were not touched. No POS server is started
except a temporary one on port 8998 (e2e); the real POS is never stopped or restarted.
Exit code 0 = all passed, 1 = something failed.
"""
import argparse, glob, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_TERMINAL_PROMPT="0")  # git must fail fast, never wait for a password


def sh(cmd, cwd=None, timeout=180):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT after %ds: %s" % (timeout, " ".join(cmd))


def snapshot(src):
    out = {}
    for d in ("data", "backups", "archives"):
        for f in glob.glob(os.path.join(src, d, "**", "*"), recursive=True):
            if os.path.isfile(f):
                st = os.stat(f)
                out[f] = (st.st_size, st.st_mtime_ns)
    return out


def ok_fail(rc, text):
    """Parse 'ok   ...' / 'FAIL ...' output. Returns (passed, total, failure lines)."""
    lines = text.splitlines()
    p = sum(1 for l in lines if l.startswith("ok   "))
    f = [l for l in lines if l.startswith("FAIL ")]
    if rc != 0 and not f:
        f = ["(exit code %d) %s" % (rc, " | ".join(l for l in lines if l.strip())[-300:])]
    return p, p + len([l for l in lines if l.startswith("FAIL ")]), f


def check_numeric(tests, src):
    rc, text = sh([sys.executable, os.path.join(tests, "numeric_validation_test.py"), src])
    s = [l for l in text.splitlines() if l.startswith("SUMMARY")]
    if not s:
        return 0, 0, ["(exit code %d) no SUMMARY line: %s" % (rc, text.strip()[-300:])], text
    n = {k: int(v) for k, v in (x.split("=") for x in s[0].split()[1:])}
    bad = [l for l in text.splitlines() if l.startswith(("[FAIL]", "[WARN]"))]
    return n["PASS"], n["PASS"] + n["WARN"] + n["FAIL"], bad, text


def check_script(tests, src, name):
    path = os.path.join(tests, name)
    if not os.path.isfile(path):
        return None
    rc, text = sh([sys.executable, path, src])
    if text.startswith("SKIP"):
        return None
    p, t, f = ok_fail(rc, text)
    return p, t, f, text


def check_js(tests, src):
    p = t = 0
    fails, texts = [], []
    for f in sorted(glob.glob(os.path.join(src, "js", "*.js"))):
        rc, text = sh(["node", "--check", f], timeout=30)
        t += 1
        p += rc == 0
        if rc:
            fails.append("FAIL syntax %s: %s" % (os.path.basename(f), text.strip().splitlines()[0] if text.strip() else rc))
    for name in ("theme_test.js", "js_logic_test.js"):
        script = os.path.join(tests, name)
        if os.path.isfile(script):
            rc, text = sh(["node", script, src], timeout=30)
            texts.append(text)
            a, b, f = ok_fail(rc, text)
            p, t, fails = p + a, t + b, fails + f
    return p, t, fails, "\n".join(texts)


def describe(src, label):
    rc, h = sh(["git", "-C", src, "rev-parse", "--short", "HEAD"], timeout=15)
    h = h.strip() if rc == 0 else "no-git"
    dirty = ""
    if rc == 0:
        _, st = sh(["git", "-C", src, "status", "--porcelain"], timeout=15)
        dirty = "+uncommitted" if st.strip() else ""
    return "%s @%s%s" % (label, h, dirty)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src")
    ap.add_argument("--clone", nargs="?", const="origin")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    tmp = None
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
        src = tmp + "/clone"
        label = "clone"
    else:
        src = os.path.abspath(a.src or ROOT)
        label = "working tree" if not a.src else "folder"
    tests = os.path.join(src, "tests") if os.path.isfile(os.path.join(src, "tests", "numeric_validation_test.py")) else HERE
    before = snapshot(src) if not a.clone else {}
    results = [("numeric", check_numeric(tests, src))]
    for name, fn in (("e2e", "e2e.py"), ("archive", "archive_test.py"), ("bulk", "bulk_delete_test.py"), ("cost", "cost_test.py"), ("purchases", "purchases_test.py"), ("receipt", "receipt_settings_test.py"), ("logs", "logs_test.py")):
        r = check_script(tests, src, fn)
        if r:
            results.append((name, r))
    results.append(("js", check_js(tests, src)))
    after = snapshot(src) if not a.clone else {}
    untouched = before == after
    desc = describe(src, label)
    allfails = [(n, f) for n, r in results for f in r[2]]
    if not untouched:
        allfails.append(("data", "FAIL real data/backups/archives changed during the run"))
    parts = " | ".join("%s %d/%d" % (n, r[0], r[1]) for n, r in results)
    status = "FAIL" if allfails else "PASS"
    print("%s  %s | data %s | %s | %ds" % (status, parts, "untouched" if untouched else "CHANGED", desc, time.time() - t0))
    for n, f in allfails[:40]:
        print("  [%s] %s" % (n, f[:220]))
    if len(allfails) > 40:
        print("  ... %d more failures (use -v)" % (len(allfails) - 40))
    if a.verbose:
        for n, r in results:
            print("\n===== %s =====\n%s" % (n, r[3]))
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(1 if allfails else 0)


if __name__ == "__main__":
    main()
