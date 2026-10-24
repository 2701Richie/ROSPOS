# check: tags=slow,browser
"""Automatically discovered check for 42 responsive CSS/theme scenarios."""
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
        [sys.executable, os.path.join(here, "css_snapshot.py"), "--verify"],
        cwd=os.path.dirname(here),
        capture_output=True, text=True, timeout=150,
    )
    if result.returncode:
        print("FAIL 42 responsive CSS/theme scenarios: " + ((result.stdout + result.stderr).strip()[-2000:]))
        sys.exit(1)
    print("ok   42 responsive CSS/theme scenarios passes in isolated Chromium")
