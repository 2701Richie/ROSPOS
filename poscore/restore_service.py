"""Restore operations. Server owns the request lock and supplies live state via ctx.

Importing this module performs no I/O and never opens the POS database.
"""

import hashlib
import json
from poscore.values import MAX_NUM, R, good_num, max_sale_no, valid_day, valid_expiry


def r_restore(ctx, b, ip):
    ctx.reauth(ip, b, "owner")
    d = b.get("data") or b
    if not isinstance(d, dict) or not all(isinstance(d.get(k), list) for k in ("p", "s")):
        raise ctx.Err(400, "That is not a valid ROSPOS backup.")
    if not isinstance(d.get("g", []), list) or len(d["p"]) > 100000 or len(d["s"]) > 1000000 or len(d.get("g", [])) > 2000000:
        raise ctx.Err(400, "This backup has invalid or excessive data.")
    if any(not isinstance(x, dict) or not all(k in x for k in ("id", "n", "p", "s"))
           or not isinstance(x.get("n"), str) or not good_num(x.get("p"))
           or not good_num(x.get("s"), MAX_NUM, whole=True)
           or not (x.get("e") is None or isinstance(x.get("e"), str))
           or not (x.get("m") is None or good_num(x.get("m"), MAX_NUM, whole=True))
           or not (x.get("c") is None or good_num(x.get("c"))) for x in d["p"]):
        raise ctx.Err(400, "The backup contains an invalid product record.")
    if any(not isinstance(x, dict) or not all(k in x for k in ("no", "d", "l", "tot"))
           or not good_num(x.get("no"), MAX_NUM, whole=True) or not isinstance(x.get("d"), str)
           or not isinstance(x.get("l"), list) or not good_num(x.get("tot"))
           or any(not isinstance(line, dict) or not all(k in line for k in ("id", "n", "q", "p"))
                  or not good_num(line.get("q"), MAX_NUM, whole=True)
                  or not good_num(line.get("p"))
                  or not (line.get("c") is None or good_num(line.get("c"))) for line in x.get("l", [])) for x in d["s"]):
        raise ctx.Err(400, "The backup contains an invalid sale record.")
    if any(not x.get("dc") and abs(R(sum(l["q"] * l["p"] for l in x["l"])) - x["tot"]) > 0.01 for x in d["s"]):
        raise ctx.Err(400, "The backup contains a sale whose total does not match its items.")  # would corrupt every report
    if (any(not isinstance(x["id"], int) or isinstance(x["id"], bool) or not x["n"].strip() for x in d["p"])
            or len({x["id"] for x in d["p"]}) != len(d["p"])):
        raise ctx.Err(400, "The backup contains a repeated or invalid product id or an empty product name.")
    if len({x["no"] for x in d["s"]}) != len(d["s"]) or any(x["no"] < 1 for x in d["s"]):
        raise ctx.Err(400, "The backup contains a repeated or invalid sale number.")
    if any(not isinstance(x, dict) for x in d.get("g", [])):
        raise ctx.Err(400, "The backup contains an invalid activity record.")
    audit = d.get("logs", [])
    if not isinstance(audit, list) or len(audit) > 1_000_000:
        raise ctx.Err(400, "This backup has invalid or excessive log history.")
    imported_events = []
    for item in audit:
        if (not isinstance(item, dict) or item.get("category") not in ("inventory", "sales", "activity", "system")
                or not isinstance(item.get("ts"), str) or len(item["ts"]) > 64
                or not isinstance(item.get("action"), str) or len(item["action"]) > 160
                or not isinstance(item.get("actor", ""), str)
                or not isinstance(item.get("details", {}), dict)
                or item.get("status", "success") not in ("success", "failed", "warning", "info")):
            raise ctx.Err(400, "The backup contains an invalid log record.")
        fingerprint = json.dumps({k: item.get(k) for k in ("ts", "category", "action", "actor", "entity_type", "entity_id", "entity_name", "operation_id", "old_value", "new_value", "details", "status")}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        source_key = item.get("source_key") or ("restored-" + hashlib.sha256((str(item.get("id", "")) + fingerprint).encode("utf-8")).hexdigest())
        imported_events.append(ctx._event_tuple(item["category"], item["action"], actor=item.get("actor", ""),
            entity_type=item.get("entity_type", ""), entity_id=item.get("entity_id", ""),
            entity_name=item.get("entity_name", ""), operation_id=item.get("operation_id", ""),
            old_value=item.get("old_value"), new_value=item.get("new_value"), details=item.get("details", {}),
            status=item.get("status", "success"), ts=item["ts"], source_key=source_key))
    suppliers = d.get("suppliers", [])
    purchases = d.get("purchases", [])
    if (not isinstance(suppliers, list) or not isinstance(purchases, list)
            or len(suppliers) > 100000 or len(purchases) > 1000000):
        raise ctx.Err(400, "The backup contains invalid or excessive purchase data.")
    if any(not isinstance(x, dict) or not isinstance(x.get("id"), str) or not isinstance(x.get("name"), str)
           or not x["name"].strip() for x in suppliers):
        raise ctx.Err(400, "The backup contains an invalid supplier record.")
    if any(not isinstance(x, dict) or not all(k in x for k in ("id", "product_id", "supplier_id", "quantity", "unit_cost", "total", "date"))
           or not isinstance(x.get("id"), str) or not isinstance(x.get("supplier_id"), str)
           or not isinstance(x.get("quantity"), int) or isinstance(x.get("quantity"), bool) or not 1 <= x["quantity"] <= MAX_NUM
           or not good_num(x.get("unit_cost")) or not good_num(x.get("total")) or not valid_day(x.get("date"))
           for x in purchases):
        raise ctx.Err(400, "The backup contains an invalid purchase record.")
    if any(abs(R(x["quantity"] * x["unit_cost"]) - x["total"]) > 0.01 for x in purchases):
        raise ctx.Err(400, "The backup contains a purchase whose total does not match its quantity and cost.")
    for x in d["s"]:  # the cash field is display-only; repair a missing or too-small value instead of refusing the whole backup
        if not good_num(x.get("cash")) or x["cash"] < x["tot"]:
            x["cash"] = x["tot"]
    # Keep an immediate database-level recovery point before replacing live data.
    for x in d["p"]:  # older or hand-edited backups may lack these; the app expects them on every product
        if not (isinstance(x.get("e"), str) and valid_expiry(x["e"])):
            x["e"] = ""
        if x.get("m") is None:
            x["m"] = 0
    ctx.snapshot("pre-restore")
    old_S, old_pending = ctx.S, ctx.PENDING_AUDIT_EVENTS[:]
    try:
        ctx.PENDING_AUDIT_EVENTS.extend(imported_events)
        ctx.S = {"p": d["p"], "s": d["s"], "g": d.get("g", []),
             "suppliers": suppliers, "purchases": purchases}
        ctx._ID_FLOOR = None  # the restored products may use higher ids than any handed out so far
        ctx.put("sale_seq", max(ctx.get("sale_seq") or 0, max_sale_no(ctx.S["s"])))
        ctx.safe_archive()
        ctx.queue_event("activity", "Backup restored", entity_type="backup", entity_name="Backup restore",
                    details={"products": len(ctx.S["p"]), "sales": len(ctx.S["s"]), "reason": "Owner-confirmed restore"})
        ctx.save()
    except Exception:
        ctx.S = old_S  # a failed restore must leave the running POS exactly as it was
        ctx.PENDING_AUDIT_EVENTS[:] = old_pending
        raise
    return {"msg": "Backup restored successfully."}
