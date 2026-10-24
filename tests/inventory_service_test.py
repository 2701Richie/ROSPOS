# check: tags=logic
"""Verify delegated entry points still pass the live runtime into isolated services."""
import shutil
from harness import *
srv, SRC, TMP = boot("rospos-service-inventory-")
from poscore import inventory_service
R = Report()
for name in ('r_product', 'r_delete', 'r_delete_many', 'r_stock', 'r_import'):
    original = getattr(inventory_service, name)
    marker = object()
    seen = []
    def spy(ctx, body, ip):
        seen.append((ctx, body, ip))
        return marker
    setattr(inventory_service, name, spy)
    body = {"probe": name}
    try:
        returned = getattr(srv, name)(body, "probe-ip")
    finally:
        setattr(inventory_service, name, original)
    R.ok(returned is marker and seen == [(srv, body, "probe-ip")],
         name + " delegates to the isolated service with live context")
shutil.rmtree(TMP, ignore_errors=True)
R.done()
