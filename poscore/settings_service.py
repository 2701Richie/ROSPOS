"""Settings operations. Server owns the request lock and supplies live state via ctx.

Importing this module performs no I/O and never opens the POS database.
"""

import math
from poscore.values import R


def r_settings(ctx, b, ip):
    ctx.reauth(ip, b, "owner")
    cur = ctx.settings()
    store = " ".join(str(b.get("store", "")).split())
    if len(store) > 60:
        raise ctx.Err(400, "Store name must be 60 characters or fewer.")
    hrs_in, days_in = b.get("session_hours"), b.get("backup_days")
    if isinstance(hrs_in, bool) or isinstance(days_in, bool):
        raise ctx.Err(400, "Enter whole numbers for backup days and a number for the sign-in hours.")
    try:
        hrs, days = float(hrs_in), int(str(days_in).strip())
    except (TypeError, ValueError):
        raise ctx.Err(400, "Enter whole numbers for backup days and a number for the sign-in hours.")
    if not math.isfinite(hrs) or not 1 <= hrs <= 72:
        raise ctx.Err(400, "Stay signed in must be between 1 and 72 hours.")
    if not 7 <= days <= 365:
        raise ctx.Err(400, "Keep between 7 and 365 days of backups.")
    rc = {}
    for k, mx in ctx.RC_LIMITS.items():
        if k in b and not isinstance(b[k], str):
            raise ctx.Err(400, "%s must be text." % ctx.SETTING_LABELS[k])
        rc[k] = " ".join(b[k].split()) if k in b else cur[k]  # a request without the field keeps the saved value
        if len(rc[k]) > mx:
            raise ctx.Err(400, "%s must be %d characters or fewer." % (ctx.SETTING_LABELS[k], mx))
    new = dict({"store": store, "session_hours": hrs, "backup_days": days}, **rc)
    changed = [k for k in new if new[k] != cur[k]]
    if changed:
        ctx.put("settings", new)
        for k in changed:
            ctx.log("Settings", "Changed: " + ctx.SETTING_LABELS[k], ctx.shown(cur[k]), ctx.shown(new[k]), 0)
        ctx.save()
    return {"msg": "Settings saved." if changed else "No changes."}
