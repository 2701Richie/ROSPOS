"""Session cookie verification and password hashing; no database access."""

import hashlib
import secrets
import time


def hash_password(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", str(pw).encode(), bytes.fromhex(salt), 200_000).hex()


def public_account(u):
    return {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"],
            "active": u.get("active", True)}


def create_session(u, sessions, session_hours):
    t = secrets.token_hex(24)
    for old in [k for k, v in sessions.items() if v["exp"] <= time.time()]:
        del sessions[old]
    sessions[t] = {"id": u["id"], "exp": time.time() + session_hours * 3600}
    return t


def resolve_session(handler, sessions, lookup_user):
    t = None
    for part in (handler.headers.get("Cookie") or "").split(";"):
        if part.strip().startswith("pos_session="):
            t = part.strip().split("=", 1)[1]
    s = sessions.get(t)
    u = lookup_user(s["id"]) if s and s["exp"] > time.time() else None
    if not u or not u.get("active", True):
        sessions.pop(t, None)
        return None, t
    return u, t


