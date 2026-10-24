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
import configparser, json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ['FAKE_CLOUD'])
if len(args) < 3 or args[0] != '--config':
    sys.exit(1)  # Managed backups must never read the default rclone config.
cfg = configparser.RawConfigParser(interpolation=None)
cfg.read(args[1])
op = args[2:]
if op == ['config', 'dump']:
    print(json.dumps({section: dict(cfg.items(section)) for section in cfg.sections()}))
elif op[0] == 'copyto':
    shutil.copyfile(op[1], root / op[2].split(':', 1)[1])
elif op[0] == 'lsf':
    print('\\n'.join(x.name for x in root.iterdir() if x.is_file()))
elif op[0] == 'deletefile':
    (root / op[1].split(':', 1)[1]).unlink()
else:
    sys.exit(1)
""", encoding="utf-8")
    fake.chmod(0o700)
    os.environ["FAKE_CLOUD"] = tmp
    os.environ["POS_CLOUD_CONFIG"] = str(root / "config" / "cloud.json")
    os.environ["PATH"] = str(tool) + os.pathsep + os.environ["PATH"]
    private = root / "config"
    private.mkdir(mode=0o700)
    remote = "rospos_crypt_0123456789ab"
    drive = "rospos_drive_0123456789ab"
    cfgpath = private / "managed-rclone.conf"
    cfgpath.write_text("""[%s]
type = drive
scope = drive.file
token = {"refresh_token":"fake"}

[%s]
type = crypt
remote = %s:ROSPOS-Encrypted/0123456789abcdef
password = fake-secret
password2 = fake-salt
filename_encryption = standard
directory_name_encryption = true
""" % (drive, remote, drive), encoding="utf-8")
    cfgpath.chmod(0o600)
    R.ok(cb._managed_remote_valid(remote), "managed Google Drive crypt destination validated")
    trusted = cfgpath.read_text(encoding="utf-8")
    for unsafe, reason in (
        (trusted.replace("filename_encryption = standard", "filename_encryption = off"),
         "plaintext filenames prohibited"),
        (trusted.replace("directory_name_encryption = true", "directory_name_encryption = false"),
         "unencrypted directories prohibited"),
        (trusted.replace("password2 = fake-salt", "password2 = "),
         "missing secondary encryption secret prohibited"),
        (trusted.replace("type = drive", "type = local"),
         "non-Google backend prohibited"),
        (trusted.replace("ROSPOS-Encrypted/0123456789abcdef", "unmanaged-folder"),
         "non-ROSPOS backup destination prohibited"),
    ):
        cfgpath.write_text(unsafe, encoding="utf-8")
        R.ok(not cb._managed_remote_valid(remote), reason)
    cfgpath.write_text(trusted, encoding="utf-8")
    R.ok(cb._managed_remote_valid(remote), "secure remote remains usable after rejecting unsafe settings")
    for invalid in ("secure", "plain", "driveA", "../oops", "secure;rm", ""):
        try:
            cb.activate_google(invalid)
        except ValueError:
            R.ok(True, "unmanaged destination rejected: " + invalid)
        else:
            R.ok(False, "unmanaged destination accepted: " + invalid)
    cb.activate_google(remote)
    R.ok(cb.status()["enabled"] and cb.status()["remote"] == remote, "Google consent enables managed encrypted backup")
    R.ok(os.stat(cb.config_path()).st_mode & 0o077 == 0, "cloud settings have private file permissions")
    R.ok("password" not in json.dumps(cb.status()), "credential never returned in status")

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
