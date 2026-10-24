"""The legacy runner delegates to the new auto-discovering check engine."""
import os
import subprocess
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
old = subprocess.run([sys.executable, os.path.join(root, "tests/run.py"), "--list"],
                     cwd=root, capture_output=True, text=True, timeout=20)
new = subprocess.run([sys.executable, os.path.join(root, "tests/check.py"), "--list"],
                     cwd=root, capture_output=True, text=True, timeout=20)
if old.returncode == new.returncode == 0 and old.stdout == new.stdout:
    print("ok   legacy test runner delegates and discovers the same checks")
else:
    print("FAIL legacy runner disagrees with check.py")
    sys.exit(1)
