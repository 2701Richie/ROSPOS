"""Accounts operations. Server owns the request lock and supplies live state via ctx.

Importing this module performs no I/O and never opens the POS database.
"""

import hmac
import re


def r_login(ctx, b, ip):
    un = str(b.get("username", "")).strip().lower()
    u = ctx.find_user(un)
    if not ctx.check_pw(u, str(b.get("password", "")), "login|%s|%s" % (ip, un)):
        ctx.record_event("activity", "Login failed", actor=un, entity_type="account", entity_name=un,
                     details={"remote": ip}, status="failed")
        raise ctx.Err(403, "Wrong username or password.")
    ctx.record_event("activity", "Login successful", actor=u["name"], entity_type="account",
                 entity_id=u["id"], entity_name=u["username"], details={"role": u["role"]})
    return {"me": ctx.acct(u), "_session": ctx.new_session(u)}


def r_setup(ctx, b, ip):
    if ctx.U:
        raise ctx.Err(403, "Setup is already done.")
    ctx.throttle("setup|" + ip)
    if not hmac.compare_digest(str(b.get("code", "")).strip().upper(), ctx.SETUP_CODE):
        ctx.miss("setup|" + ip)
        raise ctx.Err(403, "Wrong setup code. It is printed in the server log.")
    un, name = str(b.get("username", "")).strip().lower(), " ".join(str(b.get("name", "")).split())
    if not re.fullmatch(r"[a-z0-9._-]{3,30}", un) or not name:
        raise ctx.Err(400, "Enter your name and a username of 3 to 30 letters or numbers.")
    u = {"id": 1, "username": un, "name": name, "role": "owner", "active": True}
    ctx.set_pw(u, ctx.valid_pw(b.get("password")))
    ctx.U.append(u)
    ctx.save_users()
    ctx.record_event("activity", "Owner account created", actor=name, entity_type="account",
                 entity_id=u["id"], entity_name=un, details={"role": "owner"})
    return {"me": ctx.acct(u), "_session": ctx.new_session(u)}


def r_users(ctx, b, ip):
    ctx.allow("owner")
    return {"users": [ctx.acct(u) for u in ctx.U]}


def r_user(ctx, b, ip):
    ctx.allow("owner")
    i, un = b.get("id"), str(b.get("username", "")).strip().lower()
    name, role, pw = " ".join(str(b.get("name", "")).split()), b.get("role"), str(b.get("password") or "")
    active = bool(b.get("active", True))
    if role not in ctx.ROLES:
        raise ctx.Err(400, "Pick a role.")
    if not name:
        raise ctx.Err(400, "Enter a name.")
    creating = not bool(i)
    if i:
        u = ctx.user_by_id(i)
        if not u:
            raise ctx.Err(404, "Account not found.")
        before_user = ctx.acct(u)
    else:
        if not re.fullmatch(r"[a-z0-9._-]{3,30}", un):
            raise ctx.Err(400, "Username must be 3 to 30 letters, numbers, dots, dashes or underscores.")
        if ctx.find_user(un):
            raise ctx.Err(409, "That username is taken.")
        ctx.valid_pw(pw)
        u = {"id": max([x["id"] for x in ctx.U] + [0]) + 1, "username": un}
    others = [x for x in ctx.U if x is not u and x["role"] == "owner" and x.get("active", True)]
    if u.get("role") == "owner" and (role != "owner" or not active) and not others:
        raise ctx.Err(409, "There must always be one active owner.")
    if pw:
        ctx.valid_pw(pw)
    u.update(name=name, role=role, active=active)
    if pw:
        ctx.set_pw(u, pw)
    if u not in ctx.U:
        ctx.U.append(u)
    if not active or (pw and u["id"] != ctx.ACTOR["id"]):
        for t in [t for t, s in ctx.SESSIONS.items() if s["id"] == u["id"]]:
            del ctx.SESSIONS[t]
    ctx.save_users()
    ctx.record_event("activity", "Account created" if creating else "Account updated", entity_type="account",
                 entity_id=u["id"], entity_name=u.get("username", un),
                 old_value=None if creating else before_user,
                 new_value={"name": u["name"], "role": u["role"], "active": u["active"]},
                 details={"password_reset": bool(pw)})
    return {"users": [ctx.acct(x) for x in ctx.U]}


def r_mypw(ctx, b, ip):
    if not ctx.check_pw(ctx.ACTOR, str(b.get("old", "")), "pw|%s|%s" % (ip, ctx.ACTOR["id"])):
        raise ctx.Err(403, "Wrong current password.")
    ctx.set_pw(ctx.ACTOR, ctx.valid_pw(b.get("new")))
    for t in [t for t, v in ctx.SESSIONS.items() if v["id"] == ctx.ACTOR["id"] and t != ctx.TOKEN]:
        del ctx.SESSIONS[t]  # other tablets signed in as this user must sign in again with the new password
    ctx.save_users()
    ctx.record_event("activity", "Password changed", entity_type="account", entity_id=ctx.ACTOR["id"],
                 entity_name=ctx.ACTOR.get("username", ""), details={"self_service": True})
    return {}
