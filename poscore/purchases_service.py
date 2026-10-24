"""Purchases operations. Server owns the request lock and supplies live state via ctx.

Importing this module performs no I/O and never opens the POS database.
"""

import secrets
from datetime import datetime
from poscore.values import MAX_NUM, R, good_num, valid_day


def r_supplier(ctx, b, ip):
    ctx.allow("manager")
    name = str(b.get("name", "")).strip()
    if not name or len(name) > 120:
        raise ctx.Err(400, "Enter a supplier name (up to 120 characters).")
    existing = next((x for x in ctx.S["suppliers"] if x.get("name", "").casefold() == name.casefold()), None)
    if existing:
        if b.get("select_existing"):
            return {"supplier": existing, "msg": "Supplier already exists; selected the existing record."}
        raise ctx.Err(409, "A supplier with that name already exists.")
    x = {"id": "sup_" + secrets.token_hex(8), "name": name}
    ctx.S["suppliers"].append(x)
    ctx.save()
    ctx.record_event("inventory", "Supplier created", entity_type="supplier", entity_id=x["id"], entity_name=name)
    return {"supplier": x, "msg": "Supplier added."}


def r_purchase(ctx, b, ip):
    ctx.allow("manager")
    action = str(b.get("action", "create"))
    if action not in ("create", "edit", "delete"):
        raise ctx.Err(400, "Choose a valid purchase action.")
    rows = ctx.S.setdefault("purchases", [])
    if action in ("edit", "delete"):
        row = next((x for x in rows if x.get("id") == b.get("id")), None)
        if not row:
            raise ctx.Err(404, "Purchase record not found.")
        p = ctx.prod(row.get("product_id"))
        if not p:
            raise ctx.Err(409, "The linked product no longer exists; purchase history cannot be changed safely.")
        if action == "delete":
            if p["s"] < row["quantity"]:
                raise ctx.Err(409, "Cannot delete this purchase safely because some received stock is no longer available. Keep the record for audit history.")
            p["s"] -= row["quantity"]
            ctx.log(p["n"], "Purchase reversed -%d" % row["quantity"], p["s"] + row["quantity"], p["s"], p["id"], "Purchase record deleted")
            rows.remove(row)
            ctx.save()
            ctx.record_event("inventory", "Purchase deleted", entity_type="purchase", entity_id=row["id"], entity_name=p["n"], details={"quantity": row["quantity"]})
            return {"msg": "Purchase deleted."}
        old_q = row["quantity"]
        qty = b.get("quantity")
        cost = b.get("unit_cost")
        supplier = ctx.supplier_by_id(b.get("supplier_id"))
        date = b.get("date")
        expiry_date = b.get("expiry_date")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1 or qty > MAX_NUM:
            raise ctx.Err(400, "Quantity must be a positive whole number.")
        if not good_num(cost) or cost < 0:
            raise ctx.Err(400, "Enter a valid unit cost.")
        if not supplier:
            raise ctx.Err(400, "Choose a valid supplier.")
        if not valid_day(date):
            raise ctx.Err(400, "Choose a valid purchase date.")
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise ctx.Err(400, "Choose a valid purchase date.")
        if not valid_day(expiry_date) or expiry_date <= date:
            raise ctx.Err(400, "Expiration date must be after the purchase date.")
        try:
            datetime.strptime(expiry_date, "%Y-%m-%d")
        except ValueError:
            raise ctx.Err(400, "Enter a valid expiration date.")
        delta = qty - old_q
        if delta < 0 and p["s"] < -delta:
            raise ctx.Err(409, "Cannot reduce the purchase quantity because the received stock has already been used.")
        if p["s"] + delta > MAX_NUM:
            raise ctx.Err(400, "That stock quantity is too large.")
        before = p["s"]
        p["s"] += delta
        row.update(supplier_id=supplier["id"], supplier_name=supplier["name"], quantity=qty,
                   unit_cost=R(cost), total=R(qty * cost), date=date, expiry_date=expiry_date, notes=str(b.get("notes", ""))[:1000])
        # Protected cost: never reduce the product cost on cheaper purchases or edits.
        if p.get("c") is None or R(cost) > p["c"]:
            ctx.log(p["n"], "Cost changed", p.get("c") or 0, R(cost), p["id"], "Purchase edited",
                audit_values=(p.get("c"), R(cost)))
            p["c"] = R(cost)
        if delta:
            ctx.log(p["n"], "Purchase adjusted %+d" % delta, before, p["s"], p["id"], "Purchase record edited")
        ctx.save()
        ctx.record_event("inventory", "Purchase updated", entity_type="purchase", entity_id=row["id"], entity_name=p["n"])
        return {"msg": "Purchase updated."}

    product = ctx.prod(b.get("product_id"))
    supplier = ctx.supplier_by_id(b.get("supplier_id"))
    qty, cost, date = b.get("quantity"), b.get("unit_cost"), b.get("date")
    expiry_date = b.get("expiry_date")
    if not product:
        raise ctx.Err(400, "Choose a valid product.")
    if not supplier:
        raise ctx.Err(400, "Choose a valid supplier.")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1 or qty > MAX_NUM:
        raise ctx.Err(400, "Quantity must be a positive whole number.")
    if not good_num(cost) or cost < 0:
        raise ctx.Err(400, "Enter a valid unit cost.")
    if not valid_day(date):
        raise ctx.Err(400, "Choose a valid purchase date.")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ctx.Err(400, "Choose a valid purchase date.")
    if not valid_day(expiry_date) or expiry_date <= date:
        raise ctx.Err(400, "Expiration date must be after the purchase date.")
    try:
        datetime.strptime(expiry_date, "%Y-%m-%d")
    except ValueError:
        raise ctx.Err(400, "Enter a valid expiration date.")
    if product["s"] + qty > MAX_NUM:
        raise ctx.Err(400, "That stock quantity is too large.")
    before = product["s"]
    # Match the Reorder tab's suggested quantity (2 x reorder level minus current stock).
    suggested = max(1, 2 * product["m"] - before)
    was_on_reorder = before <= product["m"]
    product["s"] += qty
    row = {"id": "pur_" + secrets.token_hex(8), "product_id": product["id"], "product_name": product["n"],
           "supplier_id": supplier["id"], "supplier_name": supplier["name"], "quantity": qty,
           "unit_cost": R(cost), "total": R(qty * cost), "date": date, "expiry_date": expiry_date, "notes": str(b.get("notes", ""))[:1000],
           "created_at": datetime.now().isoformat(timespec="seconds")}
    rows.append(row)
    # Protected cost: keep the current cost if this purchase is cheaper; raise it if costlier.
    if product.get("c") is None or R(cost) > product["c"]:
        ctx.log(product["n"], "Cost changed", product.get("c") or 0, R(cost), product["id"], "Purchase received",
            audit_values=(product.get("c"), R(cost)))
        product["c"] = R(cost)
    ctx.log(product["n"], "Purchase received +%d" % qty, before, product["s"], product["id"], "Purchase received from " + supplier["name"])
    ctx.save()
    ctx.record_event("inventory", "Purchase recorded", entity_type="purchase", entity_id=row["id"], entity_name=product["n"],
                 details={"supplier": supplier["name"], "quantity": qty, "unit_cost": R(cost), "total": R(qty * cost), "expiry_date": expiry_date})
    return {"msg": "Purchase added.", "reorder_removed": was_on_reorder and qty >= suggested, "product_id": product["id"]}
