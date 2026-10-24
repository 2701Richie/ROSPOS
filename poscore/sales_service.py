"""Sales operations. Server owns the request lock and supplies live state via ctx.

Importing this module performs no I/O and never opens the POS database.
"""

from poscore.values import MAX_NUM, R, good_num


def r_sale(ctx, b, ip):
    rid = b.get("rid")
    if rid is not None:
        if not isinstance(rid, str) or not 8 <= len(rid) <= 64:
            raise ctx.Err(400, "Bad request.")
        prior = ctx.db.execute("select sale_no from sale_requests where user_id=? and request_id=?", (ctx.ACTOR["id"], rid)).fetchone()
        if prior is not None:
            done = next((x for x in ctx.S["s"] if x.get("no") == prior[0]), None)
            if done:
                return ctx.sale_out(done)
            raise ctx.Err(409, "This payment was already recorded. Check Receipts before trying again.")
    agg = {}
    for l in b.get("lines") or []:
        q = l.get("q")
        if not good_num(q, MAX_NUM, whole=True) or q < 1 or not ctx.prod(l.get("id")):
            raise ctx.Err(400, "Invalid item in the sale.")
        agg[l["id"]] = agg.get(l["id"], 0) + q
    if not agg:
        raise ctx.Err(400, "Add a product first.")
    today, t = ctx.now()
    lines, tot = [], 0
    for i, q in agg.items():
        p = ctx.prod(i)
        if p["e"] and p["e"] < today:
            raise ctx.Err(409, "%s is expired and cannot be sold." % p["n"])
        if q > p["s"]:
            raise ctx.Err(409, "Not enough stock for %s (only %d left)." % (p["n"], p["s"]))
        line = {"id": i, "n": p["n"], "q": q, "p": p["p"]}
        if p.get("c") is not None:
            line["c"] = p["c"]  # cost at the time of sale, kept for profit reports
        lines.append(line)
        tot += q * p["p"]
    tot = R(tot)
    cash = b.get("cash")
    cash = tot if cash is None else cash
    if not good_num(cash) or cash < tot:
        raise ctx.Err(400, "Cash received is less than the total.")
    sale_no = ctx.next_sale_no()
    for l in lines:
        p = ctx.prod(l["id"])
        old_stock = p["s"]
        p["s"] -= l["q"]
        ctx.log(p["n"], "Sale #%d" % sale_no, old_stock, p["s"], p["id"], "Checkout", operation_id="sale-%s" % sale_no)
    sale = {"no": sale_no, "d": today, "t": t, "l": lines, "tot": tot, "cash": cash,
            "by": ctx.ACTOR["name"], "uid": ctx.ACTOR["id"]}
    ctx.S["s"].append(sale)
    ctx.queue_event("sales", "Sale completed", entity_type="sale", entity_id=sale_no,
                entity_name="Receipt #%s" % sale_no, operation_id="sale-%s" % sale_no,
                new_value=tot, details={"sale": sale}, source_key=ctx._sale_source_key(sale))
    if rid is not None:
        ctx.PENDING_SALE_REQUEST = (ctx.ACTOR["id"], rid, sale_no)
    try:
        ctx.save()
    except Exception:
        ctx.PENDING_SALE_REQUEST = None
        raise
    return ctx.sale_out(sale)


def r_void(ctx, b, ip):
    ctx.reauth(ip, b)
    s, why = ctx.find_sale(b.get("no")), str(b.get("why", "")).strip()
    if s.get("v"):
        raise ctx.Err(409, "This sale is already void.")
    if not why:
        raise ctx.Err(400, "Enter a reason.")
    gone = [l["n"] for l in s["l"] if not ctx.put_back(l, l["q"], "Void sale #%d" % s["no"], why, operation_id="sale-%s" % s["no"])]
    d, t = ctx.now()
    s["v"] = {"d": d, "t": t, "w": why, "u": ctx.ACTOR["name"]}
    ctx.queue_event("sales", "Sale voided", entity_type="sale", entity_id=s["no"],
                entity_name="Receipt #%s" % s["no"], operation_id="sale-%s" % s["no"],
                old_value=s.get("tot"), new_value=0,
                details={"reason": why, "void": s["v"]}, source_key="sale-void-%s" % s["no"])
    if gone:
        ctx.warn_not_restored(s, gone, "void")
    ctx.save()
    if gone:
        return {"msg": "Sale voided. Stock was not restored for deleted products: %s." % ", ".join(gone)}
    return {}


def r_change(ctx, b, ip):
    ctx.reauth(ip, b)
    s, why, q = ctx.find_sale(b.get("no")), str(b.get("why", "")).strip(), b.get("q")
    if s.get("v"):
        raise ctx.Err(409, "This sale is void.")
    if not isinstance(q, list) or len(q) != len(s["l"]) or any(not good_num(x, MAX_NUM, whole=True) for x in q):
        raise ctx.Err(400, "Quantities must be whole numbers.")
    if not any(q):
        raise ctx.Err(400, "Use Void to cancel the whole sale.")
    if not why:
        raise ctx.Err(400, "Enter a reason.")
    sub = R(sum(n * l["p"] for n, l in zip(q, s["l"])))
    dc = R(sub * 0.2) if s.get("dc") else 0  # sales made with the old discount keep it
    tot, cash = R(sub - dc), b.get("cash")
    if not good_num(cash) or cash < tot:
        raise ctx.Err(400, "Cash received must cover the new total (\u20b1%.2f)." % tot)
    for n, l in zip(q, s["l"]):
        if n > l["q"]:
            p = ctx.find_prod(l)
            if not p or n - l["q"] > p["s"]:
                raise ctx.Err(409, "Not enough stock for %s." % l["n"])
    old, d, t = s["tot"], *ctx.now()
    gone = []
    for n, l in zip(q, s["l"]):
        if n != l["q"] and not ctx.put_back(l, l["q"] - n, "Changed sale #%d" % s["no"], why, operation_id="sale-%s" % s["no"]):
            gone.append(l["n"])
    s["l"] = [dict(l, q=n) for n, l in zip(q, s["l"]) if n > 0]
    s.update(tot=tot, cash=cash)
    if s.get("dc"):
        s.update(sub=sub, dc=dc)
    change_record = {"d": d, "t": t, "w": why, "a": old, "z": tot, "u": ctx.ACTOR["name"]}
    s.setdefault("h", []).append(change_record)
    ctx.queue_event("sales", "Sale amended", entity_type="sale", entity_id=s["no"],
                entity_name="Receipt #%s" % s["no"], operation_id="sale-%s" % s["no"],
                old_value=old, new_value=tot, details={"reason": why, "change": change_record},
                source_key="sale-change-%s-%s" % (s["no"], len(s["h"])))
    if gone:
        ctx.warn_not_restored(s, gone, "change")
    ctx.save()
    return {"msg": "Sale changed. Stock was not adjusted for deleted products: %s." % ", ".join(gone)} if gone else {}
