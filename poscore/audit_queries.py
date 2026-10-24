"""Read-only audit search, grouped paging, and operation details.

HTTP authentication/authorization stays in server.py. This module receives an
already-authorized SQLite connection and only constructs parameterized queries.
"""
import json
import re

CATEGORIES = {"inventory", "sales", "activity", "system"}
STATUSES = {"success", "failed", "warning", "info"}
COLUMNS = (
    "id,ts,category,action,actor,entity_type,entity_id,entity_name,"
    "operation_id,old_value,new_value,details,status"
)
COLUMN_NAMES = (
    "id", "ts", "category", "action", "actor", "entity_type", "entity_id",
    "entity_name", "operation_id", "old_value", "new_value", "details", "status",
)
GROUP_KEY = "case when operation_id<>'' then operation_id else 'event-'||id end"
SEARCH_COLUMNS = (
    "action", "actor", "entity_name", "entity_id",
    "operation_id", "details", "old_value", "new_value",
)


class AuditQueryError(ValueError):
    """Invalid audit log category or pagination parameters."""


def decode_rows(rows):
    """Decode the three JSON-valued columns without changing legacy bad values."""
    items = []
    for row in rows:
        item = dict(zip(COLUMN_NAMES, row))
        for key in ("old_value", "new_value", "details"):
            try:
                item[key] = json.loads(item[key]) if item[key] is not None else None
            except (ValueError, TypeError):
                pass
        items.append(item)
    return items


def query_audit_events(db, q):
    """Return grouped audit rows or a detail page for one operation.

    Category and pagination values are validated before SQL execution; user
    filters are always bound as parameters rather than interpolated into SQL.
    """
    category = (q.get("category", [""])[0] or "").strip()
    if category not in CATEGORIES:
        raise AuditQueryError("Choose a valid log category.")

    search = (q.get("q", [""])[0] or "").strip()[:160]
    actor = (q.get("user", [""])[0] or "").strip()[:120]
    status = (q.get("status", [""])[0] or "").strip()
    start = (q.get("from", [""])[0] or "").strip()
    end = (q.get("to", [""])[0] or "").strip()
    operation_id = (q.get("operation_id", [""])[0] or "").strip()[:120]

    try:
        limit = max(1, min(100, int(q.get("limit", ["50"])[0])))
        offset = max(0, min(10_000_000, int(q.get("offset", ["0"])[0])))
    except (ValueError, TypeError) as exc:
        raise AuditQueryError("Invalid pagination.") from exc

    if operation_id:
        where = "category=? and operation_id=?"
        args = [category, operation_id]
        total = db.execute(
            "select count(*) from audit_events where " + where, args
        ).fetchone()[0]
        rows = db.execute(
            f"select {COLUMNS} from audit_events where {where}"
            " order by ts desc,id desc limit ? offset ?",
            args + [limit, offset],
        ).fetchall()
        return {
            "items": decode_rows(rows), "total": total,
            "limit": limit, "offset": offset, "operation_id": operation_id,
        }

    clauses = ["category=?"]
    args = [category]
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append(
            "(" + " or ".join(f"{column} like ? escape '\\'" for column in SEARCH_COLUMNS) + ")"
        )
        args.extend([like] * len(SEARCH_COLUMNS))
    if actor:
        clauses.append("actor like ?")
        args.append("%" + actor + "%")
    if status in STATUSES:
        clauses.append("status=?")
        args.append(status)
    if start and re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
        clauses.append("substr(ts,1,10)>=?")
        args.append(start)
    if end and re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
        clauses.append("substr(ts,1,10)<=?")
        args.append(end)

    where = " and ".join(clauses)
    total = db.execute(
        f"select count(*) from (select {GROUP_KEY} as gkey "
        f"from audit_events where {where} group by gkey)",
        args,
    ).fetchone()[0]
    groups = db.execute(
        f"select {GROUP_KEY} as gkey,max(ts) as last_ts,"
        f"max(id) as last_id,count(*) as event_count from audit_events"
        f" where {where} group by gkey"
        " order by last_ts desc,last_id desc limit ? offset ?",
        args + [limit, offset],
    ).fetchall()

    items = []
    for group_key, _, _, _ in groups:
        singleton = str(group_key).startswith("event-")
        if singleton:
            rows = db.execute(
                f"select {COLUMNS} from audit_events where id=?",
                (int(str(group_key)[6:]),),
            ).fetchall()
        else:
            rows = db.execute(
                f"select {COLUMNS} from audit_events"
                " where category=? and operation_id=?"
                " order by case when entity_type='import' then 0 else 1 end,"
                " id desc limit 1",
                (category, group_key),
            ).fetchall()
        decoded = decode_rows(rows)
        if not decoded:
            continue
        item = decoded[0]
        item["event_count"] = (
            1 if singleton else db.execute(
                "select count(*) from audit_events where category=? and operation_id=?",
                (category, group_key),
            ).fetchone()[0]
        )
        item["group_id"] = "" if singleton else str(group_key)
        items.append(item)

    return {"items": items, "total": total, "limit": limit, "offset": offset}
