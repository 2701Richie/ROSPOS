# check: tags=logic
"""Verify delegated entry points still pass the live runtime into isolated services."""
import shutil
from harness import *
srv, SRC, TMP = boot("rospos-service-purchases-")
from poscore import purchases_service
R = Report()
for name in ('r_supplier', 'r_purchase'):
    original = getattr(purchases_service, name)
    marker = object()
    seen = []
    def spy(ctx, body, ip):
        seen.append((ctx, body, ip))
        return marker
    setattr(purchases_service, name, spy)
    body = {"probe": name}
    try:
        returned = getattr(srv, name)(body, "probe-ip")
    finally:
        setattr(purchases_service, name, original)
    R.ok(returned is marker and seen == [(srv, body, "probe-ip")],
         name + " delegates to the isolated service with live context")
shutil.rmtree(TMP, ignore_errors=True)
R.done()
