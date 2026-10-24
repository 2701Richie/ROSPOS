# check: tags=logic
"""Sales services must use the live server clock, including an injected test clock."""
import shutil
from harness import *

srv, SRC, TMP = boot("rospos-sales-clock-")
R = Report()
store = Store(srv)
ids = seed(store)

virtual = ("2034-02-03", "08:42 AM")
srv.now = lambda: virtual
sale_resp = store.call("/api/sale", {"lines": [{"id": ids["P"][0], "q": 2}], "cash": 100}, "staff")
sale = sale_resp.obj.get("sale", {}) if sale_resp.obj else {}
R.ok(sale_resp.code == 200 and (sale.get("d"), sale.get("t")) == virtual,
     "checkout uses the current server clock after service delegation")

if sale_resp.code == 200:
    number = sale["no"]
    changed = store.call("/api/change", {"no": number, "q": [1], "cash": 100,
                                          "why": "clock regression", "password": PW}, "manager")
    history = srv.find_sale(number).get("h", [])
    R.ok(changed.code == 200 and history and (history[-1]["d"], history[-1]["t"]) == virtual,
         "receipt amendments use the current server clock")
    voided = store.call("/api/void", {"no": number, "why": "clock regression",
                                      "password": PW}, "manager")
    metadata = srv.find_sale(number).get("v") or {}
    R.ok(voided.code == 200 and (metadata.get("d"), metadata.get("t")) == virtual,
         "receipt voids use the current server clock")

shutil.rmtree(TMP, ignore_errors=True)
R.done()
