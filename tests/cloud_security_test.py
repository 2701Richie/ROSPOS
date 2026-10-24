"""Check cloud endpoint access controls with a throwaway POS database."""
import os
import shutil
from harness import *
srv, SRC, TMP = boot("rospos-cloud-security-")
from poscore import cloud_backup
R = Report()
store = Store(srv)
for role in ("owner", "manager", "staff"):
    store.add_user(role)
os.environ["POS_CLOUD_CONFIG"] = os.path.join(TMP, "cloud.json")

for role, wanted in ((None, 401), ("staff", 403), ("manager", 403), ("owner", 200)):
    result = store.call("/api/cloud-backup", role=role)
    R.ok(result.code == wanted, "GET cloud status role=%s" % role)
for role, wanted in ((None, 401), ("staff", 403), ("manager", 403), ("owner", 200)):
    result = store.call("/api/cloud-backup", {"action": "disconnect", "password": PW}, role=role)
    R.ok(result.code == wanted, "POST cloud disconnect role=%s" % role)
R.ok(store.call("/api/cloud-backup", {"action": "disconnect", "password": PW},
                "owner", csrf=False).code == 403, "cloud request CSRF protection")
R.ok(store.call("/api/cloud-backup", {"action": "disconnect", "password": "bad"},
                "owner").code == 403, "cloud request requires owner reauthentication")

R.ok(store.call("/api/cloud-backup", {"action":"configure", "remote":"secure",
                                        "enabled":True, "password":PW}, "owner").code == 400,
     "removed manual cloud configure endpoint cannot be used")
original = cloud_backup._managed_remote_valid
cloud_backup._managed_remote_valid = lambda remote: remote == "rospos_crypt_0123456789ab"
try:
    cloud_backup.activate_google("rospos_crypt_0123456789ab")
    R.ok(store.call("/api/cloud-backup", {"action": "backup", "password": "wrong"},
                    "owner").code == 403, "backup now demands current owner password")
    R.ok(store.call("/api/cloud-backup", {"action": "backup", "password": PW},
                    "staff").code == 403, "staff cannot start a cloud backup")
    previous = cloud_backup.launch
    cloud_backup.launch = lambda *args, **kw: True
    try:
        R.ok(store.call("/api/cloud-backup", {"action": "backup", "password": PW},
                        "owner").code == 200, "owner may start manual backup")
    finally:
        cloud_backup.launch = previous
    R.ok(store.call("/api/cloud-backup", {"action": "disconnect", "password": PW},
                    "owner").code == 200 and not cloud_backup.status()["enabled"],
         "owner may disconnect and disable cloud backups")
finally:
    cloud_backup._managed_remote_valid = original
R.ok(srv.db.execute("select count(*) from audit_events where entity_type='cloud_backup'").fetchone()[0] >= 3,
     "cloud management actions are audited")
R.ok(not store.problems, "no account hash or salt in responses")
shutil.rmtree(TMP, ignore_errors=True)
R.done()
