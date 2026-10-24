"""Pure audit event metadata, legacy keys and migration event formatting."""

import hashlib
import json
import secrets
from datetime import datetime


def json_value(v):
    return None if v is None else json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


def new_operation_id(prefix):
    return "%s-%s-%s" % (prefix, datetime.now().strftime("%Y%m%d%H%M%S"), secrets.token_hex(3))


def legacy_event_key(g):
    if g.get("eid"):
        return "legacy-g-id-" + str(g["eid"])
    raw = json.dumps(g, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "legacy-g-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def legacy_timestamp(day, clock):
    try:
        return datetime.strptime("%s %s" % (day, clock), "%Y-%m-%d %I:%M %p").astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        return datetime.now().astimezone().isoformat(timespec="seconds")


def sale_source_key(s):
    return "sale-created-%s" % s.get("no")


def prepare_sale_events(s, batches, event_factory):
    """Prepare legacy sale events for one batched insert during startup."""
    if not isinstance(s, dict) or not isinstance(s.get("no"), int) or isinstance(s.get("no"), bool):
        return
    no = s["no"]
    ts = legacy_timestamp(s.get("d"), s.get("t"))
    batches.append(event_factory("sales", "Sale completed", actor=s.get("by", ""), entity_type="sale",
        entity_id=no, entity_name="Receipt #%s" % no, new_value=s.get("tot"),
        operation_id="sale-%s" % no, details={"sale": s, "migrated": True}, ts=ts,
        source_key=sale_source_key(s)))
    if s.get("v"):
        v = s["v"]
        batches.append(event_factory("sales", "Sale voided", actor=v.get("u", ""), entity_type="sale",
            entity_id=no, entity_name="Receipt #%s" % no, old_value=s.get("tot"), new_value=0,
            operation_id="sale-%s" % no, details={"reason": v.get("w", ""), "void": v},
            ts=legacy_timestamp(v.get("d", s.get("d")), v.get("t", s.get("t"))),
            source_key="sale-void-%s" % no))
    for i, h in enumerate(s.get("h", []), 1):
        batches.append(event_factory("sales", "Sale amended", actor=h.get("u", ""), entity_type="sale",
            entity_id=no, entity_name="Receipt #%s" % no, old_value=h.get("a"), new_value=h.get("z"),
            operation_id="sale-%s" % no, details={"reason": h.get("w", ""), "change": h},
            ts=legacy_timestamp(h.get("d", s.get("d")), h.get("t", s.get("t"))),
            source_key="sale-change-%s-%s" % (no, i)))


