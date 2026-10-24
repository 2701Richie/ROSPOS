# check: tags=logic
"""Verify delegated entry points still pass the live runtime into isolated services."""
import shutil
from harness import *
srv, SRC, TMP = boot("rospos-service-accounts-")
from poscore import accounts_service
R = Report()
for name in ('r_login', 'r_setup', 'r_users', 'r_user', 'r_mypw'):
    original = getattr(accounts_service, name)
    marker = object()
    seen = []
    def spy(ctx, body, ip):
        seen.append((ctx, body, ip))
        return marker
    setattr(accounts_service, name, spy)
    body = {"probe": name}
    try:
        returned = getattr(srv, name)(body, "probe-ip")
    finally:
        setattr(accounts_service, name, original)
    R.ok(returned is marker and seen == [(srv, body, "probe-ip")],
         name + " delegates to the isolated service with live context")
shutil.rmtree(TMP, ignore_errors=True)
R.done()
