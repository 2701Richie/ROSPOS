# check: tags=logic
"""Random store simulation checked against an independent model.

A seeded random walk of sales, voids, amendments, stock counts, product edits/deletes, purchases, CSV imports,
backup round-trips and day changes (with archiving). After every step: the stock of every product must equal what the
rules say, a refused request must change nothing, every rule in harness.invariants must hold, successful changes must be
logged, sale numbers must never repeat (even across archived days) and staff must never receive costs.
Finishes with a many-thread race on the last units of one product. Reproduce a failure with CHECK_SEED=<n>."""
import datetime, glob, json, random, threading
from harness import *

srv, SRC, TMP = boot("rospos-sim-")
R = Report()
store = Store(srv)
rng = random.Random(seed_value())
STEPS = scale(120, 400, 2500)
vday = [datetime.date(2026, 10, 24)]
srv.now = lambda: (vday[0].isoformat(), "10:00 AM")  # a controllable clock, so days can pass and archiving can run
ids = seed(store)
NAMES = ["Aspirin", "Ibuprofen", "Cetirizine", "Loperamide", "Omeprazole", "Vitamin C", "Zinc", "Salbutamol", "Metformin", "Paracetamol",
         "Amoxicillin", "Betadine", "Alcohol 70%", "Gauze Pad", "Thermometer"]
for n in NAMES[:8]:
    store.call("/api/product", {"n": n, "p": round(rng.uniform(1, 200), 2), "s": rng.randint(0, 80), "m": rng.randint(0, 10),
                                "e": rng.choice(["", "", "2027-12-31", "2020-01-01"]), **({"c": round(rng.uniform(0.5, 90), 2)} if rng.random() < .7 else {})}, "manager")
made, counts, fails = set(), {}, []


class Diverged(Exception):
    pass


def stocks():
    return {p["id"]: p["s"] for p in srv.S["p"]}


def today():
    return vday[0].isoformat()


def judge(step, name, label, resp, before, expected, snap0, audit0, must=None, audit=True):
    """expected: stock map if the request succeeds. must: True/False when the rules say it has to succeed/fail."""
    counts[name] = counts.get(name, 0) + 1
    where = "step %d %s (%s)" % (step, name, label)
    if resp.code not in (200, 400, 404, 409):
        raise Diverged("%s answered %s: %s" % (where, resp.code, resp.data[:100]))
    done = resp.code == 200 and not (resp.obj or {}).get("plan", {}).get("applied") is False
    if must is not None and must != done:
        raise Diverged("%s should have %s but answered %s %s" % (where, "succeeded" if must else "been refused", resp.code, resp.data[:100]))
    if not done:
        if snap(srv) != snap0 or stocks() != before:
            raise Diverged("%s was refused but the data changed" % where)
        return
    if stocks() != expected:
        diff = {k: (before.get(k), expected.get(k), stocks().get(k)) for k in set(expected) | set(stocks()) if expected.get(k) != stocks().get(k)}
        raise Diverged("%s stock is wrong (id: before, rules say, actual) %s" % (where, dict(list(diff.items())[:3])))
    bad = invariants(srv)
    if bad:
        raise Diverged("%s broke a rule: %s" % (where, bad[0]))
    if audit and audit_count(srv) <= audit0:
        raise Diverged("%s succeeded but wrote nothing to the log" % where)


def pick(seq):
    return rng.choice(seq) if seq else None


def step_sale(step):
    ps = srv.S["p"]
    chosen = rng.sample(ps, min(rng.randint(1, 3), len(ps)))
    lines = [{"id": p["id"], "q": rng.choice([1, 1, 2, 3, 5, rng.randint(1, 60)])} for p in chosen]
    if rng.random() < .1:
        lines.append(dict(lines[0]))
    agg = {}
    for l in lines:
        agg[l["id"]] = agg.get(l["id"], 0) + l["q"]
    must = all(srv.prod(i)["s"] >= q and not (srv.prod(i)["e"] and srv.prod(i)["e"] < today()) for i, q in agg.items())
    tot = srv.R(sum(l["q"] * srv.prod(l["id"])["p"] for l in lines))
    body = {"lines": lines, "cash": tot + rng.choice([0, 5, 100]), "rid": "sim-rid-%08d" % step}
    before, snap0, a0 = stocks(), snap(srv), audit_count(srv)
    role = rng.choice(["staff", "manager"])
    resp = store.call("/api/sale", body, role)
    judge(step, "sale", str(lines), resp, before, {k: v - agg.get(k, 0) for k, v in before.items()}, snap0, a0, must)
    if resp.code == 200:
        no = resp.obj["sale"]["no"]
        if no in made:
            raise Diverged("step %d sale number %d was issued twice" % (step, no))
        made.add(no)
        if rng.random() < .15:  # the tablet never got the answer and presses Pay again
            again = store.call("/api/sale", body, role)  # the same signed-in user retries, as a tablet would
            if again.code != 200 or again.obj["sale"]["no"] != no or stocks() != {k: v - agg.get(k, 0) for k, v in before.items()}:
                raise Diverged("step %d a retried sale was not recognised (second sale or different answer)" % step)
            counts["sale-retry"] = counts.get("sale-retry", 0) + 1


def step_void(step):
    s = pick(srv.S["s"])
    no = s["no"] if s and rng.random() < .93 else rng.randint(900000, 999999)
    must = bool(s) and no == s["no"] and not s.get("v")
    exp = stocks()
    if must:
        for l in s["l"]:
            p = srv.find_prod(l)
            if p:
                exp[p["id"]] = exp[p["id"]] + l["q"]
    before, snap0, a0 = stocks(), snap(srv), audit_count(srv)
    resp = store.call("/api/void", {"no": no, "password": PW, "why": "sim"}, "manager")
    judge(step, "void", "#%s" % no, resp, before, exp, snap0, a0, must)


def step_change(step):
    live = [s for s in srv.S["s"] if not s.get("v")]
    s = pick(live)
    if not s:
        return
    q = [rng.randint(0, l["q"] + 2) for l in s["l"]]
    exp, too_many = stocks(), False
    for n, l in zip(q, s["l"]):
        p = srv.find_prod(l)
        if n > l["q"] and (not p or n - l["q"] > p["s"]):
            too_many = True
        if p and n != l["q"]:
            exp[p["id"]] = max(0, exp[p["id"]] + l["q"] - n)
    must = False if (all(n == 0 for n in q) or too_many) else None
    before, snap0, a0 = stocks(), snap(srv), audit_count(srv)
    resp = store.call("/api/change", {"no": s["no"], "password": PW, "why": "sim", "q": q, "cash": 1e6}, "manager")
    judge(step, "change", "#%s %s" % (s["no"], q), resp, before, exp, snap0, a0, must)


def step_stock(step):
    p = pick(srv.S["p"])
    mode, v = rng.choice(["set", "add"]), rng.randint(0, 40)
    z = p["s"] + v if mode == "add" else v
    must = None if (mode == "add" and v < 1) else (z != p["s"])
    if mode == "add" and v < 1:
        must = False
    exp = {**stocks(), p["id"]: z}
    before, snap0, a0 = stocks(), snap(srv), audit_count(srv)
    resp = store.call("/api/stock", {"id": p["id"], "mode": mode, "v": str(v), "why": "sim"}, "manager")
    judge(step, "stock", "%s %s" % (mode, v), resp, before, exp, snap0, a0, must)


def step_product_create(step):
    name = rng.choice(NAMES) + (" " + str(rng.randint(1, 999)) if rng.random() < .6 else "")
    e = rng.choice(["", "2027-12-31", "2020-01-01", "31/12/2027", "<b>x</b>"])
    s = rng.randint(0, 50)
    dup = any(srv.key(p["n"]) == srv.key(name) for p in srv.S["p"])
    must = False if (dup or e in ("31/12/2027", "<b>x</b>")) else True
    before, snap0, a0 = stocks(), snap(srv), audit_count(srv)
    resp = store.call("/api/product", {"n": name, "p": round(rng.uniform(1, 90), 2), "s": s, "m": 2, "e": e}, "manager")
    new = next((p["id"] for p in srv.S["p"] if p["id"] not in before), None)
    judge(step, "product-create", name, resp, before, {**before, **({new: s} if new else {})}, snap0, a0, must)


def step_product_edit(step):
    p = pick(srv.S["p"])
    name = p["n"] if rng.random() < .6 else rng.choice(NAMES) + " v" + str(rng.randint(1, 99))
    e = rng.choice(["", "2027-12-31", "2020-01-01", "bad-date"])
    clash = any(q is not p and srv.key(q["n"]) == srv.key(name) for q in srv.S["p"]) and srv.key(name) != srv.key(p["n"])
    must = False if (e == "bad-date" or clash) else None
    before, snap0, a0 = stocks(), snap(srv), audit_count(srv)
    resp = store.call("/api/product", {"id": p["id"], "n": name, "p": round(rng.uniform(1, 90), 2), "m": rng.randint(0, 9), "e": e, "c": p.get("c")}, "manager")
    judge(step, "product-edit", name, resp, before, before, snap0, a0, must, audit=False)


def step_delete(step):
    if len(srv.S["p"]) <= 6:
        return
    picks = rng.sample(srv.S["p"], rng.choice([1, 1, 2]))
    exp = {k: v for k, v in stocks().items() if k not in {p["id"] for p in picks}}
    before, snap0, a0 = stocks(), snap(srv), audit_count(srv)
    if len(picks) == 1:
        resp = store.call("/api/delete", {"id": picks[0]["id"], "why": "sim"}, "manager")
    else:
        resp = store.call("/api/delete-many", {"ids": [p["id"] for p in picks], "why": "sim"}, "manager")
    judge(step, "delete", str([p["id"] for p in picks]), resp, before, exp, snap0, a0, True)


def step_purchase(step):
    kind = rng.choice(["create", "create", "delete", "edit"])
    rows = srv.S.get("purchases", [])
    before, snap0, a0 = stocks(), snap(srv), audit_count(srv)
    if kind == "create":
        p, sup = pick(srv.S["p"]), pick(srv.S["suppliers"])
        q = rng.randint(1, 20)
        body = {"product_id": p["id"], "supplier_id": sup["id"], "quantity": q, "unit_cost": round(rng.uniform(.5, 80), 2), "date": today(),
                "expiry_date": (vday[0] + datetime.timedelta(days=400)).isoformat()}
        exp = {**before, p["id"]: p["s"] + q}  # worked out before the call, which changes p["s"]
        resp = store.call("/api/purchase", body, "manager")
        judge(step, "purchase-create", "%s x%d" % (p["n"], q), resp, before, exp, snap0, a0, True)
        return
    row = pick(rows)
    if not row:
        return
    p = srv.prod(row["product_id"])
    if kind == "delete":
        must = bool(p) and p["s"] >= row["quantity"]
        exp = {**before, **({p["id"]: p["s"] - row["quantity"]} if p else {})}
        resp = store.call("/api/purchase", {"action": "delete", "id": row["id"]}, "manager")
        judge(step, "purchase-delete", row["id"], resp, before, exp, snap0, a0, must)
    else:
        q = rng.randint(1, 20)
        exp = {**before, **({p["id"]: p["s"] + q - row["quantity"]} if p else {})}
        body = {"action": "edit", "id": row["id"], "product_id": row["product_id"], "supplier_id": row["supplier_id"], "quantity": q,
                "unit_cost": row["unit_cost"], "date": row["date"], "expiry_date": row.get("expiry_date") or "2030-01-01"}
        resp = store.call("/api/purchase", body, "manager")
        judge(step, "purchase-edit", "%s -> %d" % (row["id"], q), resp, before, exp, snap0, a0, None if p else False, audit=False)


def step_import(step):
    mode = rng.choice(["add", "set"])
    chosen = rng.sample(srv.S["p"], min(rng.randint(1, 4), len(srv.S["p"])))
    rows, exp = [], stocks()
    for p in chosen:
        q = rng.randint(1, 30)
        rows.append({"name": p["n"], "quantity": str(q)})
        exp[p["id"]] = p["s"] + q if mode == "add" else q
    bad = rng.random() < .2
    if bad:
        rows.append({"name": "No Such Product", "quantity": "5"})
    before, snap0, a0 = stocks(), snap(srv), audit_count(srv)
    resp = store.call("/api/import", {"mode": mode, "apply": True, "why": "sim", "rows": rows}, "manager")
    judge(step, "import-" + mode, "%d rows%s" % (len(rows), " + 1 bad row" if bad else ""), resp, before, exp, snap0, a0, None, audit=False)
    if bad and stocks() != before:
        raise Diverged("step %d an import with a bad row changed stock (it must be all-or-nothing)" % step)


def step_backup(step):
    canon = lambda: json.dumps({k: srv.S.get(k, []) for k in ("p", "s", "g", "suppliers", "purchases")}, sort_keys=True)
    before_state = canon()
    data = store.call("/api/backup", role="owner").obj["data"]  # the page sends the inner data of the downloaded file
    resp = store.call("/api/restore", {"password": PW, "data": data}, "owner")
    counts["backup-roundtrip"] = counts.get("backup-roundtrip", 0) + 1
    if resp.code != 200:
        raise Diverged("step %d restoring our own backup was refused: %s" % (step, resp.data[:120]))
    if canon() != before_state:
        raise Diverged("step %d backup -> restore did not give back identical data" % step)
    bad = invariants(srv)
    if bad:
        raise Diverged("step %d restore left the store invalid: %s" % (step, bad[0]))


def step_next_day(step):
    vday[0] += datetime.timedelta(days=rng.randint(1, 3))
    with srv.LOCK:
        srv.archive_old()
    archived = set()
    for f in glob.glob(srv.ARCHIVE_DIR + "/sales-*.json"):
        for s in json.load(open(f)).get("s", []):
            if s["no"] in archived:
                raise Diverged("step %d sale #%s is in two archive files" % (step, s["no"]))
            archived.add(s["no"])
    live = {s["no"] for s in srv.S["s"]}
    if archived & live:
        raise Diverged("step %d sales both live and archived: %s" % (step, sorted(archived & live)[:3]))
    lost = made - live - archived
    if lost:
        raise Diverged("step %d sales vanished after archiving: %s" % (step, sorted(lost)[:5]))
    if (srv.get("sale_seq") or 0) < max(made | {0}):
        raise Diverged("step %d sale_seq fell behind after archiving" % step)
    counts["next-day"] = counts.get("next-day", 0) + 1


OPS = [(step_sale, 30), (step_void, 7), (step_change, 8), (step_stock, 6), (step_product_create, 5), (step_product_edit, 6),
       (step_delete, 3), (step_purchase, 9), (step_import, 6), (step_backup, 1), (step_next_day, 2)]
try:
    for step in range(1, STEPS + 1):
        fn = rng.choices([o[0] for o in OPS], [o[1] for o in OPS])[0]
        fn(step)
        if step % 15 == 0:
            r = store.call("/api/state", role="staff")
            leaks = cost_leaks(r.obj) if r.code == 200 else ["state request failed %s" % r.code]
            if leaks:
                raise Diverged("step %d staff received: %s" % (step, ", ".join(leaks)))
except Diverged as e:
    fails.append(str(e))
except Exception as e:  # a crash inside the test itself or the server: also a finding
    import traceback
    fails.append("step crashed: %s: %s | %s" % (type(e).__name__, e, traceback.format_exc().strip().splitlines()[-3:]))

summary = ", ".join("%s %d" % kv for kv in sorted(counts.items()))
R.ok(not fails, ("simulation: %d random steps kept every rule (%s)" % (STEPS, summary)) if not fails else
     "simulation diverged (seed %d): %s" % (seed_value(), fails[0]))
R.ok(not store.problems, "simulation: no response contained a password hash or salt")

# ---- many tablets at once: exactly the stock can be sold, never more ----
if not fails:
    store.call("/api/product", {"n": "Race Product", "p": 2, "s": 100, "m": 0, "e": ""}, "manager")  # the random walk may have deleted the seeded ones
    rid = next(p["id"] for p in srv.S["p"] if p["n"] == "Race Product")
    seen_codes, errs = [], []

    def tablet():
        for _ in range(25):
            try:
                seen_codes.append(store.call("/api/sale", {"lines": [{"id": rid, "q": 1}], "cash": 50}, "staff").code)
            except Exception as e:
                errs.append(repr(e))

    threads = [threading.Thread(target=tablet) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    pstock = srv.prod(rid)["s"]
    nos = [s["no"] for s in srv.S["s"]]
    R.ok(not errs and seen_codes.count(200) == 100 and pstock == 0 and not invariants(srv) and len(nos) == len(set(nos)),
         "race: 8 tablets x 25 sales on 100 units sold exactly 100, stock ended at %d, no repeated receipt numbers%s" % (pstock, "" if not errs else " " + errs[0]))
shutil.rmtree(TMP, ignore_errors=True)
R.done()
