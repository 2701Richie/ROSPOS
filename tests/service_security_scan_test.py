# check: tags=security
"""Verify static security scanning follows handlers moved out of server.py."""
import os
import shutil
import subprocess
import sys
import tempfile
from harness import Report

ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(__file__))
R = Report()

with tempfile.TemporaryDirectory(prefix="rospos-service-scan-") as folder:
    copied = os.path.join(folder, "source")
    shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns(
        ".git", "data", "backups", "archives", "source-backups", "__pycache__"))

    def scan():
        return subprocess.run([sys.executable, os.path.join(copied, "tests", "source_scan_test.py"), copied],
                              capture_output=True, text=True, timeout=45)

    baseline = scan()
    R.ok(baseline.returncode == 0, "unmodified service modules pass the security source scan")

    stock = os.path.join(copied, "poscore", "inventory_service.py")
    original = open(stock, encoding="utf-8").read()
    altered = original.replace('    ctx.allow("manager")', '    pass', 1)
    R.ok(altered != original, "test can inject a missing inventory role check")
    with open(stock, "w", encoding="utf-8") as fh:
        fh.write(altered)
    missing_role = scan()
    R.ok(missing_role.returncode != 0 and "no permission check" in missing_role.stdout,
         "security scan catches a missing role check inside the inventory service")
    with open(stock, "w", encoding="utf-8") as fh:
        fh.write(original)

    sales = os.path.join(copied, "poscore", "sales_service.py")
    original = open(sales, encoding="utf-8").read()
    query = 'ctx.db.execute("select sale_no from sale_requests where user_id=? and request_id=?", (ctx.ACTOR["id"], rid))'
    altered = original.replace(query, 'ctx.db.execute(f"select sale_no from sale_requests where request_id={rid}")', 1)
    R.ok(altered != original, "test can inject unsafe SQL into the sales service")
    with open(sales, "w", encoding="utf-8") as fh:
        fh.write(altered)
    unsafe_sql = scan()
    R.ok(unsafe_sql.returncode != 0 and "no SQL statement" in unsafe_sql.stdout,
         "security scan catches interpolated SQL inside the sales service")

R.done()
