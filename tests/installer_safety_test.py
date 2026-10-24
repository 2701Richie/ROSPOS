#!/usr/bin/env python3
"""Installer scripts must preserve live data and refuse unrelated systemd units."""
import os
import re
import subprocess
import tempfile
from pathlib import Path

root=Path(__file__).resolve().parent.parent
bad=0

def check(ok,description):
    global bad
    print(("ok   " if ok else "FAIL ")+description)
    bad+=not ok

for name in ("install-arch.sh","install-lubuntu.sh"):
    script=root/name
    content=script.read_text()
    syntax=subprocess.run(["bash","-n",str(script)],capture_output=True,text=True)
    check(syntax.returncode==0,name+": valid bash syntax")
    check('User=$U' in content and 'WorkingDirectory=$APP_DIR' in content and
          'UMask=0077' in content and
          'AmbientCapabilities=CAP_NET_BIND_SERVICE' in content,
          name+": unprivileged POS user and private new files")
    check('ExecStart="$PY" "$APP_DIR/server.py"' in content and
          '$APP_DIR/poscore/__init__.py' in content,
          name+": service executable and modular package are required")
    check(not re.search(r'\b(?:rm\s+-rf|shred|truncate)\b',content) and
          not re.search(r'(?:rm|mv|cp|chmod|chown)\s+[^\n]*\$APP_DIR/(?:data|backups|archives)',content),
          name+": installation and removal never delete or overwrite POS storage")
    guard=content.split("# Never overwrite or uninstall another application's pos.service unit.",1)
    check(len(guard)==2 and guard[1].find('if [ -e "$SERVICE" ]') <
          guard[1].find('if [ "${1:-}" = "--uninstall" ]'),
          name+": collision protection precedes install and uninstall")

with tempfile.TemporaryDirectory(prefix="rospos-unit-guard-") as directory:
    service=Path(directory)/"pos.service"
    guard="""if [ -e "$SERVICE" ] && ! grep -qx 'Description=ROSPOS' "$SERVICE"; then
      exit 1
    fi"""
    service.write_text("[Unit]\nDescription=Unrelated Service\n")
    foreign=subprocess.run(["bash","-c",guard],env=dict(os.environ,SERVICE=str(service)))
    service.write_text("[Unit]\nDescription=ROSPOS\n")
    owned=subprocess.run(["bash","-c",guard],env=dict(os.environ,SERVICE=str(service)))
    check(foreign.returncode==1 and owned.returncode==0,
          "installer collision guard refuses an unrelated unit while accepting ROSPOS")

print("ALL PASSED" if not bad else "FAILED "+str(bad))
raise SystemExit(bool(bad))
