"""Fresh-clone readiness for optional encrypted Google Drive backups.

Never executes the system installers or touches the actual POS database.
"""
import os
import re
import subprocess
import sys
from pathlib import Path
from harness import Report

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
R = Report()

installers = {
    "install-arch.sh": "pacman -S --needed --noconfirm python avahi nss-mdns rclone",
    "install-lubuntu.sh": "apt-get install -y python3 avahi-daemon libnss-mdns rclone",
}
for name, package_command in installers.items():
    script = ROOT / name
    content = script.read_text(encoding="utf-8")
    syntax = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    R.ok(syntax.returncode == 0, name + " has valid Bash syntax")
    R.ok(package_command in content, name + " installs rclone with POS dependencies")
    R.ok('command -v rclone' in content and 'rclone version' in content,
         name + " verifies that rclone can execute")
    R.ok('User=$U' in content and 'UMask=0077' in content,
         name + " maintains unprivileged service and private file permissions")
    R.ok("rclone config" in content and "CLOUD_BACKUPS.md" in content,
         name + " gives the owner instructions for optional account authorization")
    R.ok(not re.search(r"^\s*(?:sudo\s+)?rclone\s+config\b", content, re.M),
         name + " never automatically configures a Google account")

guide = (ROOT / "CLOUD_BACKUPS.md").read_text(encoding="utf-8")
R.ok(all(x in guide for x in ("Connect Google Drive", "Desktop app", "127.0.0.1", "password", "salt", "Cloning")) and "rclone" in guide.lower(),
     "setup guide covers browser sign-in, recovery credentials and legacy rclone")
R.ok((ROOT / "poscore" / "cloud_backup.py").exists(),
     "cloud backup code is packaged in fresh clones")
R.done()
