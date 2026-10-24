# check: tags=slow,browser
"""Automatically discovered check for real-browser smoke and archived receipts."""
import importlib.util
import os
import shutil
import subprocess
import sys

if not shutil.which("chromedriver") or not shutil.which("chromium"):
    print("SKIP ChromeDriver or Chromium is not installed")
elif importlib.util.find_spec("requests") is None:
    print("SKIP the optional Python requests package is not installed")
else:
    here = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        [sys.executable, os.path.join(here, "browser_smoke.py")],
        cwd=os.path.dirname(here),
        capture_output=True, text=True, timeout=150,
    )
    if result.returncode:
        print("FAIL real-browser smoke and archived receipts: " + ((result.stdout + result.stderr).strip()[-2000:]))
        sys.exit(1)
    print("ok   real-browser smoke and archived receipts passes in isolated Chromium")
