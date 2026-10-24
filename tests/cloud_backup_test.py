"""Cloud backup and encryption-gate regression tests. Everything runs in temporary folders."""
import json
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import threading
import zipfile
from harness import Report

SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, SRC)
from poscore import cloud_backup as cb
R = Report()

with tempfile.TemporaryDirectory(prefix="rospos-cloud-check-") as tmp:
    root = pathlib.Path(tmp)
    tool = root / "bin"
    tool.mkdir()
    fake = tool / "rclone"
    fake.write_text("""#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
d = Path(os.environ['FAKE_CLOUD'])
if args == ['config', 'dump']:
    print(json.dumps({'driveA': {'type': 'drive'},
        'secure': {'type':'crypt', 'remote':'driveA:ROSPOS', 'password':'obscured',
                   'filename_encryption':'standard', 'directory_name_encryption':'true'},
        'plain': {'type':'crypt', 'remote':'driveA:ROSPOS-weak', 'password':'obscured',
                  'filename_encryption':'off'},
        'notcloud': {'type':'crypt', 'remote':'local:folder', 'password':'obscured'}}))
elif args[0] == 'copyto':
    shutil.copyfile(args[1], d / args[2].split(':', 1)[1])
elif args[0] == 'lsf':
    print('\\n'.join(x.name for x in d.iterdir() if x.is_file()))
elif args[0] == 'deletefile':
    (d / args[1].split(':', 1)[1]).unlink()
else:
    sys.exit(1)
""", encoding="utf-8")
    fake.chmod(0o700)
    os.environ["FAKE_CLOUD"] = tmp
    os.environ["POS_CLOUD_CONFIG"] = str(root / "config" / "cloud.json")
    os.environ["PATH"] = str(tool) + os.pathsep + os.environ["PATH"]
    R.ok(cb.encrypted_drive_remotes() == ["secure"], "only encrypted Google Drive crypt remotes are offered")
    for invalid in ("driveA", "plain", "notcloud", "../oops", "secure;rm", ""):
        try:
            cb.configure(invalid, True)
        except ValueError:
            pass
        else:
            R.ok(False, "unsafe remote rejected: " + invalid)
            continue
        R.ok(not cb.status()["enabled"], "unsafe remote cannot enable upload: " + invalid)
    cb.configure("secure", True)
    R.ok(cb.status()["enabled"] and cb.status()["remote"] == "secure", "owner may select an encrypted remote")
    R.ok(os.stat(cb.config_path()).st_mode & 0o077 == 0, "cloud settings have private file permissions")
    R.ok("password" not in json.dumps(cb.status(with_remotes=True)), "credential never returned in status")

    db = sqlite3.connect(str(root / "test.db"))
    db.execute("create table demo(name text)")
    db.execute("insert into demo values ('safe')")
    db.commit()
    archives = root / "archive"
    archives.mkdir()
    (archives / "2026-10-01.json").write_text('{"sales":[123]}', encoding="utf-8")
    R.ok(cb.due(), "fresh enabled remote is due for backup")
    R.ok(cb.backup_once(db, archives, threading.RLock()), "temporary database backs up successfully")
    files = list(root.glob("rospos-*.zip"))
    R.ok(len(files) == 1, "exactly one test upload was made")
    with zipfile.ZipFile(files[0]) as z:
        R.ok({"pos.db", "archives/2026-10-01.json", "manifest.json"} <= set(z.namelist()),
             "bundle contains SQLite and historical archive")
        R.ok(z.read("archives/2026-10-01.json") == b'{"sales":[123]}', "archive is unmodified")
    R.ok(not cb.due() and bool(cb.status()["last_success"]), "successful cloud backup recorded")
    with cb.JOB_LOCK:
        R.ok(not cb.backup_once(db, archives, threading.RLock()), "parallel backup cannot race another upload")
    for n in range(9):
        (root / ("rospos-202601%02dT000000-%08x.zip" % (n + 1, n))).write_text("old", encoding="utf-8")
    unrelated = root / "unrelated-file.txt"
    unrelated.write_text("must survive")
    R.ok(cb.backup_once(db, archives, threading.RLock(), retention=7),
         "a second backup can apply cloud retention")
    R.ok(len(list(root.glob("rospos-*.zip"))) == 7 and unrelated.exists(),
         "retention prunes only recognized ROSPOS backups, never unrelated files")
    cb.disconnect()
    R.ok(not cb.status()["enabled"] and not cb.status()["remote"], "disconnect stops cloud uploads")
    R.ok(not cb.backup_once(db, archives, threading.RLock()), "disconnected cloud never uploads")
    db.close()
R.done()
