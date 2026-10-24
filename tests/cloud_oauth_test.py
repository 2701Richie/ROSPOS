# check: tags=security,logic
"""Google OAuth is owner-only; encrypted config is private and never touches live data."""
import base64
import configparser
import json
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import parse_qs, urlsplit
from harness import *

srv, SRC, TMP = boot("rospos-cloud-oauth-")
from poscore import cloud_backup as cloud, google_oauth as oauth
R = Report()
store = Store(srv)
for role in ("owner", "manager", "staff"):
    store.add_user(role)
srv.PORT = 8123
os.environ["POS_CLOUD_CONFIG"] = str(Path(TMP) / "secure" / "cloud.json")

# Fake rclone never uses the host's config or accesses the internet.
bin_dir = Path(TMP) / "bin"
bin_dir.mkdir()
rclone = bin_dir / "rclone"
rclone.write_text("""#!/usr/bin/env python3
import configparser, json, os, sys
args=sys.argv[1:]
if args == ['obscure','-']:
    print('obscured-' + sys.stdin.readline().strip())
elif len(args) >= 4 and args[0]=='--config' and args[2:] == ['config','dump']:
    cfg=configparser.RawConfigParser(interpolation=None)
    cfg.read(args[1])
    print(json.dumps({sec:dict(cfg.items(sec)) for sec in cfg.sections()}))
elif args == ['config','dump']:
    print('{}')
else:
    sys.exit(1)
""", encoding="utf-8")
rclone.chmod(0o700)
os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
CID = "1234567-test.apps.googleusercontent.com"
SECRET = "GOCSPX-just-a-test-value"

for role, expected in ((None,401), ("staff",403), ("manager",403)):
    r = store.call("/api/cloud-backup", {"action":"connect", "client_id":CID,
                     "client_secret":SECRET, "password":PW}, role)
    R.ok(r.code == expected, "cloud OAuth start restricted: " + str(role))
R.ok(store.call("/api/cloud-backup", {"action":"connect", "client_id":CID,
                 "client_secret":SECRET, "password":"wrong"}, "owner").code == 403,
     "owner must reauthenticate before starting Google sign-in")
R.ok(store.call("/api/cloud-backup", {"action":"connect", "client_id":CID,
                 "client_secret":SECRET, "password":PW}, "owner", csrf=False).code == 403,
     "Google sign-in start requires CSRF header")
for cid in ("", "evil%0a", "a.example.com", "../../../drive"):
    r = store.call("/api/cloud-backup", {"action":"connect", "client_id":cid,
                   "client_secret":SECRET, "password":PW}, "owner")
    R.ok(r.code == 400, "reject invalid Google client ID " + cid)

result=store.call("/api/cloud-backup", {"action":"connect", "client_id":CID,
                  "client_secret":SECRET, "password":PW}, "owner")
R.ok(result.code==200 and result.obj["cloud"]["authorization_url"].startswith(
     "https://accounts.google.com/"), "owner can initiate Google OAuth without terminal")
auth=result.obj["cloud"]["authorization_url"]
params=parse_qs(urlsplit(auth).query)
R.ok(params["redirect_uri"]==["http://127.0.0.1:8123/api/cloud-oauth/callback"]
     and params["code_challenge_method"]==["S256"], "OAuth uses loopback PKCE redirect")
R.ok(params["scope"]==["https://www.googleapis.com/auth/drive.file"]
     and params["access_type"]==["offline"], "Drive access scope limited to app files and refresh enabled")
kit=result.obj["cloud"]["recovery"]
R.ok(len(kit["password"])>=40 and len(kit["salt"])>=40 and kit["password"] != kit["salt"],
     "independent high entropy password and salt generated for recovery")
R.ok(SECRET not in json.dumps(result.obj) and "refresh_token" not in json.dumps(result.obj),
     "client secret and Google tokens not included in connect response")
R.ok(store.call("/api/cloud-oauth/callback?state=incorrect&code=fake", method="GET").code==400,
     "unknown OAuth state rejected without consuming valid one")
# LAN clients must not start or complete a loopback Desktop OAuth flow.
local_init=store.Fake.__init__
def remote_init(handler, path, headers, body):
    local_init(handler, path, headers, body)
    handler.client_address=("192.0.2.77", 50000)
store.Fake.__init__=remote_init
try:
    R.ok(store.call("/api/cloud-backup", {"action":"connect", "client_id":CID,
             "client_secret":SECRET, "password":PW}, "owner").code == 400,
         "LAN clients cannot begin localhost Google sign-in")
    R.ok(store.call("/api/cloud-oauth/callback?state="+params["state"][0]+
             "&code=test", method="GET").code == 403,
         "LAN clients cannot complete localhost Google callback")
finally:
    store.Fake.__init__=local_init
R.ok(not cloud.status()["enabled"], "OAuth start does not enable backups before consent")
R.ok(not cloud.encrypted_drive_remotes(), "no encrypted cloud remote before consent")

class Response:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, n): return json.dumps({"access_token":"ACCESS_TEST", "refresh_token":"REFRESH_TEST",
                                         "expires_in":3600, "token_type":"Bearer"}).encode()

old_urlopen=oauth.urlopen
oauth.urlopen=lambda request, timeout: Response()
old_launch=cloud.launch
cloud.launch=lambda *args, **kwargs: True
try:
    link="/api/cloud-oauth/callback?state=" + params["state"][0] + "&code=authorization-code"
    r=store.call(link, method="GET")
    R.ok(r.code==200 and b"Automatic encrypted backups are enabled" in r.data,
         "Google callback completes connection and enables backups")
    R.ok(b"ACCESS_TEST" not in r.data and b"REFRESH_TEST" not in r.data,
         "OAuth callback never reflects access or refresh token")
    R.ok(store.call(link, method="GET").code==400, "OAuth callback is single-use")
finally:
    oauth.urlopen=old_urlopen
    cloud.launch=old_launch

cfg=cloud.status(with_remotes=True)
R.ok(cfg["enabled"] and cfg["remote"] in cfg["remotes"] and cfg["managed"],
     "Google sign-in auto-selects managed encrypted remote")
path=oauth.managed_path(cloud)
R.ok(path.exists() and path.stat().st_mode & 0o077 == 0,
     "managed rclone token and encryption configuration is private")
parser=configparser.RawConfigParser()
parser.read(path)
R.ok(any(d.get("token") for name in parser.sections() if name.startswith("rospos_drive_")
         for d in [dict(parser.items(name))]), "refresh token stored only on disk")
R.ok(any(dict(parser.items(name)).get("password","").startswith("obscured-")
         for name in parser.sections() if name.startswith("rospos_crypt_")),
     "rclone encryption password passed via stdin and stored obscured")
R.ok("ACCESS_TEST" not in json.dumps(cfg) and "REFRESH_TEST" not in json.dumps(cfg),
     "status never leaks OAuth credentials")
R.ok(cloud._rclone_for(cfg["remote"], "config", "dump").startswith("{"),
     "managed rclone remote commands use the private config")
cloud.disconnect()
# Expired OAuth grants are rejected before a token exchange.
new=cloud.begin_google_signin(CID, SECRET, srv.PORT)
newstate=parse_qs(urlsplit(new["authorization_url"]).query)["state"][0]
oauth.PENDING["created"]-=601
R.ok(store.call("/api/cloud-oauth/callback?state="+newstate+"&code=code",
       method="GET").code==400, "expired Google OAuth state rejected")
R.ok(not cloud.status()["enabled"], "expired authorization does not enable backups")
R.ok(not cloud.status()["enabled"] and path.exists(),
     "disconnect disables automatic backups without deleting recovery credentials")
R.ok(all("/api/cloud-backup" in issue for issue in store.problems),
     "only deliberate one-time Owner recovery kit triggers password leak sentinel")
shutil.rmtree(TMP, ignore_errors=True)
R.done()
