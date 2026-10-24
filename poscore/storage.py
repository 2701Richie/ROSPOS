"""SQLite initialization, key/value access and atomic POS state commits."""

import json
import os
import sqlite3


def open_database(db_path):
    """Open the WAL database and create additive, compatible tables/indexes."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = sqlite3.connect(db_path, check_same_thread=False)
    db.execute("pragma journal_mode=wal")
    db.execute("create table if not exists kv(k text primary key, v text not null)")
    db.execute("""create table if not exists audit_events(
        id integer primary key autoincrement,
        ts text not null,
        category text not null,
        action text not null,
        actor text not null default '',
        entity_type text not null default '',
        entity_id text not null default '',
        entity_name text not null default '',
        operation_id text not null default '',
        old_value text,
        new_value text,
        details text not null default '{}',
        status text not null default 'success',
        source_key text unique
    )""")
    db.execute("create index if not exists audit_events_ts on audit_events(ts desc, id desc)")
    db.execute("create index if not exists audit_events_category_ts on audit_events(category, ts desc, id desc)")
    db.execute("create index if not exists audit_events_operation on audit_events(operation_id)")
    db.execute("create table if not exists sale_requests (user_id integer not null, request_id text not null, sale_no integer not null, primary key(user_id, request_id))")
    db.commit()
    return db


def read_key(db, k, default=None):
    r = db.execute("select v from kv where k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else default


def write_key(db, k, v):
    db.execute("insert or replace into kv values(?,?)", (k, json.dumps(v)))
    db.commit()


def persist_state(db, state, pending_events, pending_sale_request):
    """Persist current POS state, queued audit events, and a payment request key atomically."""
    pending = pending_events[:]
    try:
        db.execute("begin immediate")
        db.execute("insert or replace into kv(k,v) values(?,?)", ("state", json.dumps(state)))
        if pending_sale_request is not None:
            db.execute("insert into sale_requests(user_id,request_id,sale_no) values(?,?,?)", pending_sale_request)
        if pending:
            db.executemany("""insert or ignore into audit_events
                (ts,category,action,actor,entity_type,entity_id,entity_name,operation_id,old_value,new_value,details,status,source_key)
                values(?,?,?,?,?,?,?,?,?,?,?,?,?)""", pending)
        db.commit()
        del pending_events[:len(pending)]
    except Exception:
        db.rollback()
        raise


