# check: tags=security,logic
"""Retired manual cloud setup is unreachable and can never upload a pharmacy backup.

Uses only a disposable POS database and cloud config in the test directory.
"""
import json
import os
from pathlib import Path
import shutil
from harness import *

srv, SRC, TMP = boot("rospos-legacy-cloud-removal-")
from poscore import cloud_backup
R = Report()
store = Store(srv)
store.add_user("owner")
os.environ["POS_CLOUD_CONFIG"] = os.path.join(TMP, "cloud.json")

html = Path(SRC, "index.html").read_text(encoding="utf-8")
js = Path(SRC, "js/settings.js").read_text(encoding="utf-8")
source = Path(SRC, "poscore/cloud_backup.py").read_text(encoding="utf-8")
routes = Path(SRC, "server.py").read_text(encoding="utf-8")

for legacy_id in ("cloudRemote", "cloudSave", "cloudEnabled", "cloudRefresh"):
    R.ok(legacy_id not in html and legacy_id not in js,
         "legacy cloud UI completely removed: " + legacy_id)
for required in ("cloudConnect", "cloudControls", "cloudNow", "cloudDisconnect", "cloudCheck"):
    R.ok('id="' + required + '"' in html, "current cloud UI retained: " + required)
R.ok('def configure(' not in source and 'encrypted_drive_remotes' not in source,
     "legacy remote-selection backend functions deleted")
R.ok('action == "configure"' not in routes and "status(with_remotes" not in routes,
     "legacy configuration endpoint and response removed")
R.ok("rclone config" not in html and "rclone config" not in js,
     "no manual rclone instructions in browser")

legacy = {"remote": "pharmacycrypt", "enabled": True, "last_success": "2020-01-01"}
cloud_backup._write(legacy)
original_rclone = cloud_backup._rclone
def forbidden(*args, **kwargs):
    raise AssertionError("Legacy cloud configuration invoked rclone")
cloud_backup._rclone = forbidden
try:
    status = cloud_backup.status()
    R.ok(not status["connected"] and not status["enabled"] and status["reconnect_required"],
         "old selected remote is not an active connected account")
    R.ok(not cloud_backup.due(), "legacy configuration is never scheduled for cloud upload")
    R.ok(not cloud_backup.backup_once(srv.db, os.path.join(TMP, "archives"), srv.LOCK),
         "legacy configuration cannot upload even when explicitly invoked")
    result = store.call("/api/cloud-backup",
                        {"action": "configure", "remote": "pharmacycrypt", "enabled": True, "password": PW},
                        role="owner")
    R.ok(result.code == 400, "removed manual cloud configuration API rejects owner request")
    R.ok(cloud_backup._read() == legacy,
         "rejected legacy requests leave old private configuration unchanged")
    R.ok(not cloud_backup._managed_remote_valid("rospos_crypt_0123456789ab"),
         "manufactured managed name without Google OAuth config is rejected")
finally:
    cloud_backup._rclone = original_rclone
# A disabled saved selection must also expose the new connection flow.
old_valid = cloud_backup._managed_remote_valid
cloud_backup._managed_remote_valid = lambda remote: remote == "rospos_crypt_0123456789ab"
try:
    cloud_backup._write({"enabled": False, "remote": "rospos_crypt_0123456789ab"})
    result = cloud_backup.status()
    R.ok(not result["connected"] and result["reconnect_required"],
         "disabled historical selection cannot hide the new Google sign-in")
finally:
    cloud_backup._managed_remote_valid = old_valid
R.ok(not store.problems, "no user account secrets leaked")
shutil.rmtree(TMP, ignore_errors=True)
R.done()
