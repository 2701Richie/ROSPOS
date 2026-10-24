"""Inventory operations. Server owns the request lock and supplies live state via ctx.

Importing this module performs no I/O and never opens the POS database.
"""

import time
from poscore.values import MAX_NUM, R, good_num, valid_expiry


def r_product(ctx, b, ip):
    ctx.allow("manager")
    n, p = str(b.get("n", "")).strip(), b.get("p")
    if not n or not good_num(p):
        raise ctx.Err(400, "Enter a product name and a valid price.")
    e, m, i = str(b.get("e") or "").strip(), ctx.nint(b.get("m")), b.get("id")
    if not valid_expiry(e):
        raise ctx.Err(400, "Enter a valid expiry date, or leave it blank.")
    if len(n) > 200:
        raise ctx.Err(400, "Product name must be 200 characters or fewer.")
    k, own = ctx.key(n), (ctx.prod(i) if i else None)
    if k and not (i and not own):
        clash = next((p for p in ctx.S["p"] if p is not own and ctx.key(p["n"]) == k), None)
        if clash and (own is None or ctx.key(own["n"]) != k):  # an old duplicate may still be edited without renaming it
            raise ctx.Err(409, "A product named '%s' already exists." % clash["n"])
    has_c = "c" in b
    c = ctx.cost_of(b.get("c")) if has_c else None  # checked before anything changes
    if i:
        x = ctx.prod(i)
        if not x:
            raise ctx.Err(404, "Product not found.")
        before_fields = {k: x.get(k) for k in ("n", "p", "c", "e", "m")}
        if R(p) != x["p"]:
            ctx.log(x["n"], "Price changed", x["p"], R(p))
        if has_c and c != x.get("c"):
            ctx.log(x["n"], "Cost changed", x.get("c") or 0, c or 0, x["id"],
                audit_values=(x.get("c"), c))
            ctx.set_cost(x, c)
        x.update(n=n, p=R(p), e=e, m=m)
        field_names = {"n": "Product name", "e": "Expiry date", "m": "Reorder level"}
        for field, label in field_names.items():
            if before_fields.get(field) != x.get(field):
                ctx.queue_event("inventory", label + " changed", entity_type="product", entity_id=x["id"],
                    entity_name=x["n"], old_value=before_fields.get(field), new_value=x.get(field),
                    details={"field": field})
    else:
        s, i = ctx.nint(b.get("s")), int(time.time() * 1000)
        while ctx.prod(i):
            i += 1
        newp = {"id": i, "n": n, "p": R(p), "s": s, "e": e, "m": m}
        ctx.set_cost(newp, c)
        ctx.S["p"].append(newp)
        ctx.queue_event("inventory", "Product created", entity_type="product", entity_id=i, entity_name=n,
                    new_value={"name": n, "price": R(p), "cost": c, "stock": s, "reorder": m, "expiry": e})
        if s:
            ctx.log(n, "New product +%d" % s, 0, s, i, "Initial stock")
    ctx.save()
    return {}


def r_delete(ctx, b, ip):
    ctx.allow("manager")
    x = ctx.prod(b.get("id"))
    if not x:
        raise ctx.Err(404, "Product not found.")
    why = str(b.get("why", "")).strip()
    if not why:
        raise ctx.Err(400, "Enter a reason for deleting this product.")
    ctx.log(x["n"], "Deleted", x["s"], 0, x["id"], why,
        details={"product_snapshot": {k: x.get(k) for k in ("id", "n", "p", "c", "s", "e", "m")}})
    ctx.S["p"].remove(x)
    ctx.save()
    return {}


def r_delete_many(ctx, b, ip):
    """Delete several products at once (manager and owner). All or nothing; one audit row per product; sales history is kept."""
    ctx.allow("manager")
    ids = b.get("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100000:
        raise ctx.Err(400, "Select between 1 and 100000 products to delete.")
    if any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
        raise ctx.Err(400, "The selection is not valid.")
    why = str(b.get("why", "")).strip()
    if not why:
        raise ctx.Err(400, "Enter a reason for deleting these products.")
    # Validate the complete selection before changing anything, then replace the
    # product list in one operation. This makes the persisted set explicit.
    selected = list(dict.fromkeys(ids))
    by_id = {p.get("id"): p for p in ctx.S["p"]}
    if any(i not in by_id for i in selected):
        raise ctx.Err(404, "A selected product no longer exists. Nothing was deleted.")
    items = [by_id[i] for i in selected]
    ctx.snapshot("pre-bulk-delete")
    operation_id = ctx.new_operation_id("bulk-delete")
    ctx.queue_event("inventory", "Bulk deletion started", entity_type="operation", entity_id=operation_id,
                entity_name="Delete %d products" % len(items), operation_id=operation_id,
                details={"selected": len(items), "reason": why})
    for x in items:
        ctx.log(x["n"], "Deleted", x["s"], 0, x["id"], why, operation_id=operation_id,
            details={"product_snapshot": {k: x.get(k) for k in ("id", "n", "p", "c", "s", "e", "m")}})
    selected_set = set(selected)
    ctx.S["p"] = [p for p in ctx.S["p"] if p.get("id") not in selected_set]
    ctx.save()
    # Guard against a persistence regression: success only if the saved state
    # no longer contains any selected product IDs.
    saved = ctx.get("state") or {}
    if any(p.get("id") in selected_set for p in saved.get("p", [])):
        ctx.record_event("system", "Bulk deletion persistence verification failed", entity_type="operation",
                     entity_id=operation_id, entity_name="Delete products", operation_id=operation_id,
                     details={"selected": len(items)}, status="failed")
        raise ctx.Err(500, "Bulk delete could not be saved. Please retry or contact the owner.")
    ctx.record_event("inventory", "Bulk deletion completed", entity_type="operation", entity_id=operation_id,
                 entity_name="Delete %d products" % len(items), operation_id=operation_id,
                 details={"deleted": len(items), "reason": why})
    return {"msg": "Deleted %d product%s." % (len(items), "" if len(items) == 1 else "s")}


def r_stock(ctx, b, ip):
    ctx.allow("manager")
    p, v, mode = ctx.prod(b.get("id")), str(b.get("v", "")).strip(), b.get("mode")
    if not p:
        raise ctx.Err(404, "Product not found.")
    if not (v.isascii() and v.isdigit()) or int(v) > MAX_NUM or (mode == "add" and int(v) < 1):
        raise ctx.Err(400, "Type a whole number first" + (" (1 or more)." if mode == "add" else "."))
    o = p["s"]
    z = o + int(v) if mode == "add" else int(v)
    if z > MAX_NUM:
        raise ctx.Err(400, "That count is too large.")
    if z == o:
        raise ctx.Err(400, "The count did not change.")
    why = str(b.get("why", "")).strip() or ("Stock received" if mode == "add" else "Stock count correction")
    p["s"] = z
    ctx.log(p["n"], "Received +%s" % v if mode == "add" else "Count set", o, z, p["id"], why)
    ctx.save()
    return {"msg": "%s: %d \u2192 %d" % (p["n"], o, z)}


def r_import(ctx, b, ip):
    ctx.allow("manager")
    mode, rows = b.get("mode"), b.get("rows")
    why = str(b.get("why", "")).strip()
    if b.get("apply") and not why:
        raise ctx.Err(400, "Enter a reason for this import.")
    if mode not in ("products", "add", "set") or not isinstance(rows, list):
        raise ctx.Err(400, "Bad import request.")
    if len(rows) > 5000:
        raise ctx.Err(400, "Too many rows. Split the file (5000 rows at most).")
    idx = {}
    for p in ctx.S["p"]:
        idx.setdefault(ctx.key(p["n"]), []).append(p)
    seen, ops, errors, notes = set(), [], [], []
    for i, r in enumerate(rows, start=2):  # row 1 is the heading row
        errs, vals = [], {}
        name = " ".join(str(r.get("name") or "").split())
        k = ctx.key(name)
        if not k:
            errs.append("Name is missing.")
        elif k in seen:
            errs.append("This name appears more than once in the file.")
        seen.add(k)
        for f, label in (("price", "Price"), ("reorder", "Reorder"), ("quantity", "Quantity")):
            try:
                vals[f] = ctx.num(r.get(f))
            except ValueError:
                vals[f] = None
                errs.append(label + " is not a valid number.")
            if f != "price" and vals[f] is not None and vals[f] != int(vals[f]):
                errs.append(label + " must be a whole number.")
        try:
            vals["cost"] = ctx.num(r.get("cost"))
        except ValueError:
            vals["cost"] = None
            errs.append("Cost is not a valid number.")
        found = idx.get(k, []) if k else []
        if len(found) > 1:
            errs.append("Matches more than one existing product.")
        p = found[0] if len(found) == 1 else None
        price, reorder, qty, cost = vals["price"], vals["reorder"], vals["quantity"], vals["cost"]
        if mode == "products":
            if not p and price is None:
                errs.append("Price is required for a new product.")
        else:
            if not p:
                errs.append("Product not found. Add it first with 'Add or update products'.")
            if mode == "add" and (qty is None or qty < 1):
                errs.append("Quantity must be 1 or more.")
            if mode == "set" and qty is None:
                errs.append("Count is missing.")
        if errs:
            errors += [{"row": i, "msg": m} for m in errs]
            continue
        if p and " ".join(p["n"].split()) != name:
            notes.append("'%s' in the file matched '%s'." % (name, p["n"]))
        ops.append((p, name, price, reorder, qty, cost))
    new = upd = same = 0
    changes = []
    for p, name, price, reorder, qty, cost in ops:
        if mode == "products":
            if p is None:
                new += 1
                changes.append({"n": name, "w": "New: price %.2f, stock %d%s" % (price, int(qty or 0), ", cost %.2f" % cost if cost is not None else "")})
                continue
            ch = []
            if price is not None and R(price) != p["p"]:
                ch.append("price %.2f \u2192 %.2f" % (p["p"], R(price)))
            if reorder is not None and int(reorder) != p["m"]:
                ch.append("reorder %d \u2192 %d" % (p["m"], int(reorder)))
            if cost is not None and R(cost) != p.get("c"):
                ch.append("cost %s \u2192 %.2f" % ("%.2f" % p["c"] if p.get("c") is not None else "unknown", R(cost)))
        else:
            z = p["s"] + int(qty) if mode == "add" else int(qty)
            ch = ["stock %d \u2192 %d" % (p["s"], z)] if z != p["s"] else []
        if ch:
            upd += 1
            changes.append({"n": p["n"], "w": ", ".join(ch)})
        else:
            same += 1
    plan = {"mode": mode, "new": new, "updated": upd, "unchanged": same, "errors": errors[:50],
            "errorCount": len(errors), "changes": changes[:200], "more": max(0, len(changes) - 200),
            "notes": notes[:50], "applied": False}
    if errors or not b.get("apply"):
        if errors and b.get("apply"):
            opid = ctx.new_operation_id("csv-import")
            by_row = {}
            for issue in errors:
                by_row.setdefault(issue["row"], []).append(issue["msg"])
            ctx.record_event("inventory", "CSV import validation failed", entity_type="import", entity_id=opid,
                entity_name="CSV import (%s)" % mode, operation_id=opid,
                details={"mode": mode, "rows": len(rows), "error_count": len(errors),
                         "failed_rows": len(by_row), "errors": [{"row": row, "messages": msgs} for row, msgs in sorted(by_row.items())],
                         "apply_requested": bool(b.get("apply")), "reason": why}, status="failed")
        return {"plan": plan}
    operation_id = ctx.new_operation_id("csv-import")
    ctx.snapshot("pre-import")
    for p, name, price, reorder, qty, cost in ops:
        if mode == "products":
            if p is None:
                s = int(qty or 0)
                newp = {"id": ctx.new_id(), "n": name, "p": R(price), "s": s, "e": "", "m": int(reorder or 0)}
                ctx.set_cost(newp, None if cost is None else R(cost))
                ctx.S["p"].append(newp)
                ctx.queue_event("inventory", "Product created", entity_type="product", entity_id=newp["id"],
                    entity_name=name, operation_id=operation_id,
                    new_value={"id": newp["id"], "n": name, "p": newp["p"], "c": newp.get("c"), "s": s, "m": newp["m"], "e": newp["e"]},
                    details={"reason": why})
                if s:
                    ctx.log(name, "New product +%d" % s, 0, s, ctx.S["p"][-1]["id"], why, operation_id=operation_id)
            else:
                if price is not None and R(price) != p["p"]:
                    ctx.log(p["n"], "Price changed", p["p"], R(price), p["id"], why, operation_id=operation_id)
                    p["p"] = R(price)
                if reorder is not None and int(reorder) != p["m"]:
                    ctx.queue_event("inventory", "Reorder level changed", entity_type="product", entity_id=p["id"],
                        entity_name=p["n"], operation_id=operation_id, old_value=p["m"], new_value=int(reorder),
                        details={"field": "m", "reason": why})
                    p["m"] = int(reorder)
                if cost is not None and R(cost) != p.get("c"):
                    ctx.log(p["n"], "Cost changed", p.get("c") or 0, R(cost), p["id"], why,
                        operation_id=operation_id, audit_values=(p.get("c"), R(cost)))
                    p["c"] = R(cost)
        else:
            o = p["s"]
            z = o + int(qty) if mode == "add" else int(qty)
            if z != o:
                p["s"] = z
                ctx.log(p["n"], "Import: received +%d" % int(qty) if mode == "add" else "Import: count set", o, z, p["id"], why, operation_id=operation_id)
    ctx.queue_event("inventory", "CSV import completed", entity_type="import", entity_id=operation_id,
        entity_name="CSV import (%s)" % mode, operation_id=operation_id,
        details={"mode": mode, "rows": len(rows), "added": new, "updated": upd,
                 "unchanged": same, "failed": 0, "reason": why})
    ctx.save()
    plan["applied"] = True
    return {"plan": plan}
