# check: tags=security
"""Hostile-input check: every endpoint gets thousands of mutated requests (wrong types, huge numbers, nulls, markup,
missing fields, nested junk). Rules: never a crash (500), a failed request changes nothing, and a request that
succeeds still leaves the store healthy (see harness.invariants). Reproduce with CHECK_SEED=<n>."""
import copy, json, random, time
from harness import *

srv, SRC, TMP = boot("rospos-fuzz-")
R = Report()
store = Store(srv)
ids = seed(store)
rng = random.Random(seed_value())
CLEAN = {200, 400, 401, 403, 404, 409, 413, 429}

CORE = [None, True, -1, 0, 1.5, 10 ** 20, float("nan"), "", " ", "abc", '<img src=x onerror="window.__xss=1">',
        "9" * 400, "\u0000", [], {}, [None]]
FULL = CORE + [False, 1, 2, 0.5, -0.5, 1e308, float("inf"), 2 ** 63, "0", "-1", "1.5", "1e3", "'; drop table kv;--", "\u202e",
               "x" * 5000, [[]], {"a": 1}, [1, 2, 3], {"id": 1}, "2026-02-31", "2026-13-01", "../../etc/passwd"]
POOL = scale(CORE[:10], CORE, FULL)
MAX_PATHS = scale(25, 60, 200)
RANDOM_ROUNDS = scale(40, 150, 800)
BUDGET = scale(8, 30, 120)  # seconds per endpoint family cap, a runaway guard

JUNK_BODIES = [b"", b"null", b"[]", b"5", b'"text"', b"{", b'{"a":', b"[1,2,3]", b"true", b"\xff\xfe", b"{'a':1}",
               b"[" * 5000 + b"]" * 5000, b'{"a":' * 3000 + b"1" + b"}" * 3000, b'{"lines":[[[[[[[]]]]]]]}']


def paths(obj, prefix=(), depth=0):
    yield prefix
    if depth >= 4:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from paths(v, prefix + (k,), depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:2]):
            yield from paths(v, prefix + (i,), depth + 1)


def mutate(obj, path, val, delete=False):
    if not path:
        return val
    o = copy.deepcopy(obj)
    cur = o
    for k in path[:-1]:
        cur = cur[k]
    if delete:
        cur.pop(path[-1]) if isinstance(cur, list) else cur.pop(path[-1], None)
    else:
        cur[path[-1]] = val
    return o


base = save_state(srv)
problems, calls = {}, {}


def attempt(ep, role, body, label, raw=None):
    """Send one request from a fresh copy of the store and judge the outcome."""
    load_state(srv, base)
    before = snap(srv)
    n_audit = audit_count(srv)
    resp = store.call(ep, body, role, raw=raw)
    calls[ep] = calls.get(ep, 0) + 1
    why = None
    if resp.code not in CLEAN:
        why = "crashed or answered %s: %s" % (resp.code, resp.data[:100].decode("utf-8", "replace"))
    elif resp.code != 200 and snap(srv) != before:
        why = "was refused (%s) but the data still changed" % resp.code
    elif resp.code == 200:
        bad = invariants(srv)
        if bad:
            why = "succeeded but left the store invalid: " + bad[0]
        elif role == "staff" and resp.obj and isinstance(resp.obj.get("state"), dict) and cost_leaks(resp.obj["state"]):
            why = "leaked to staff: " + ", ".join(cost_leaks(resp.obj["state"]))
    if why:
        key = (ep, why.split(":")[0][:60])
        problems.setdefault(key, []).append("%s -> %s" % (label, why))


for ep, role, body in templates(ids, srv):
    t0 = time.time()
    attempt(ep, role, body, "valid template")
    pts = list(paths(body))
    if len(pts) > MAX_PATHS:
        pts = rng.sample(pts, MAX_PATHS)
    for path in pts:
        if time.time() - t0 > BUDGET:
            break
        for val in POOL:
            attempt(ep, role, mutate(body, path, val), "%s = %r" % ("/".join(map(str, path)) or "<body>", str(val)[:40]))
        if path:
            attempt(ep, role, mutate(body, path, None, delete=True), "%s removed" % "/".join(map(str, path)))
    for _ in range(RANDOM_ROUNDS):  # several mutations at once
        if time.time() - t0 > BUDGET:
            break
        b2, label = body, []
        for _ in range(rng.randint(2, 4)):
            path = rng.choice(pts)
            if path and not isinstance(b2, (dict, list)):
                break
            try:
                v = rng.choice(POOL)
                b2 = mutate(b2, path, v)
                label.append("%s=%r" % ("/".join(map(str, path)), str(v)[:20]))
            except (KeyError, IndexError, TypeError):
                break
        attempt(ep, role, b2, "combo " + ", ".join(label))
    for raw in JUNK_BODIES:
        attempt(ep, role, None, "raw %r" % raw[:30], raw=raw)

# Targeted financial-integrity mutation: syntactically valid backup with a forged sale total.
# Generic random fuzzing rarely lands on this specific valid-but-inconsistent combination.
load_state(srv, base)
restore_template = next(copy.deepcopy(body) for ep, role, body in templates(ids, srv) if ep == "/api/restore")
assert restore_template["data"]["s"], "The seeded backup must include a sale"
restore_template["data"]["s"][0]["tot"] += 7
before_restore = snap(srv)
response = store.call("/api/restore", restore_template, "owner")
R.ok(response.code == 400 and snap(srv) == before_restore,
     "fuzz restore: forged sale total is rejected without changing data")

# GET endpoints with hostile query strings
GET_PATHS = ["/api/state", "/api/me", "/api/logs", "/api/backup", "/index.html", "/js/core.js", "/"]
QS = ["limit", "offset", "category", "from", "to", "q", "user", "status", "op"]
for _ in range(scale(60, 250, 1000)):
    path = rng.choice(GET_PATHS)
    if path == "/api/logs":
        path += "?" + "&".join("%s=%s" % (rng.choice(QS), str(rng.choice(FULL)).replace("&", "").replace("#", "")[:60]) for _ in range(rng.randint(1, 4)))
    load_state(srv, base)
    before = snap(srv)
    resp = store.call(path, role=rng.choice(["owner", "manager", "staff", None]))
    calls["GET"] = calls.get("GET", 0) + 1
    if resp.code not in CLEAN or snap(srv) != before:
        problems.setdefault(("GET", "bad"), []).append("%s -> %s %s" % (path[:80], resp.code, resp.data[:80]))

# a request signed in with garbage session cookies
for tok in ("", "x", "a" * 5000, "../..", "tok;tok", "\u0000"):
    r = store.call("/api/state", token=tok)
    if r.code not in (401, 403):
        problems.setdefault(("cookie", "garbage"), []).append("cookie %r -> %s" % (tok[:20], r.code))

eps = [t[0] for t in templates(ids, srv)]
for ep in dict.fromkeys(eps):
    bad = [v for k, v in problems.items() if k[0] == ep]
    detail = "" if not bad else " -> %s (%d similar) e.g. %s" % (bad[0][0].split(" -> ")[1][:90], sum(len(v) for v in bad), bad[0][0].split(" -> ")[0])
    R.ok(not bad, "fuzz %s: %d hostile requests handled cleanly%s" % (ep, calls.get(ep, 0), detail))
for k in (("GET", "bad"), ("cookie", "garbage")):
    R.ok(k not in problems, "fuzz %s: %d hostile requests handled cleanly%s" % (k[0], calls.get(k[0], 6), "" if k not in problems else " -> " + problems[k][0]))
R.ok(not store.problems, "fuzz: no response contained a password hash or salt")
R.metric("fuzz_requests", sum(calls.values()), "requests")
shutil.rmtree(TMP, ignore_errors=True)
R.done()
