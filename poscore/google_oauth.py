"""Owner-initiated Google Desktop OAuth with PKCE; no browser receives Google tokens."""
import base64
import configparser
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PENDING = {}
AUTH_LOCK = threading.Lock()
CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$")


def managed_path(cloud):
    return cloud.config_path().with_name("managed-rclone.conf")


def _safe_path(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (path.parent.is_symlink() or path.parent.stat().st_mode & 0o077
            or path.is_symlink() or (path.exists() and path.stat().st_mode & 0o077)):
        raise ValueError("Cloud credentials have unsafe filesystem permissions.")


def managed_remotes(cloud):
    path = managed_path(cloud)
    if not path.exists():
        return {}
    _safe_path(path)
    try:
        return json.loads(cloud._rclone("--config", str(path), "config", "dump"))
    except (RuntimeError, subprocess.TimeoutExpired, ValueError):
        return {}


def begin(client_id, client_secret, port, cloud):
    if not shutil.which("rclone"):
        raise ValueError("rclone must be installed on the POS computer first.")
    if not isinstance(client_id, str) or len(client_id) > 256 or not CLIENT_ID.fullmatch(client_id):
        raise ValueError("Enter a valid Google Desktop application client ID.")
    if (not isinstance(client_secret, str) or not 1 <= len(client_secret) <= 512
            or any(ord(c) < 33 or ord(c) > 126 for c in client_secret)):
        raise ValueError("Enter the matching Google Desktop client secret.")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Invalid local Google sign-in port.")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    password, salt = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    folder = "ROSPOS-Encrypted/" + secrets.token_hex(8)
    redirect = "http://127.0.0.1:%d/api/cloud-oauth/callback" % port
    with AUTH_LOCK:
        PENDING.clear()
        PENDING.update(state=state, verifier=verifier, created=time.monotonic(),
                       client_id=client_id, client_secret=client_secret,
                       password=password, salt=salt, folder=folder, redirect=redirect)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    args = dict(response_type="code", client_id=client_id, redirect_uri=redirect,
                scope="https://www.googleapis.com/auth/drive.file",
                access_type="offline", prompt="consent", state=state,
                code_challenge=challenge, code_challenge_method="S256")
    return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(args),
            "recovery": {"password": password, "salt": salt, "folder": folder}}


def _obscure(value):
    # Secrets must not appear in argv or shell history.
    result = subprocess.run(["rclone", "obscure", "-"], input=value + "\n",
                            text=True, capture_output=True, timeout=15)
    if result.returncode or not result.stdout.strip():
        raise ValueError("Cannot prepare cloud encryption.")
    return result.stdout.strip()


def _create_remote(cloud, pending, token):
    path = managed_path(cloud)
    _safe_path(path)
    config = configparser.RawConfigParser(interpolation=None)
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            config.read_file(fh)
    suffix = secrets.token_hex(6)
    drive, crypt = "rospos_drive_" + suffix, "rospos_crypt_" + suffix
    config.add_section(drive)
    for k, v in {"type": "drive", "client_id": pending["client_id"],
                 "client_secret": pending["client_secret"],
                 "scope": "drive.file", "token": json.dumps(token, separators=(",", ":"))}.items():
        config.set(drive, k, v)
    config.add_section(crypt)
    for k, v in {"type": "crypt", "remote": drive + ":" + pending["folder"],
                 "filename_encryption": "standard", "directory_name_encryption": "true",
                 "password": _obscure(pending["password"]),
                 "password2": _obscure(pending["salt"])}.items():
        config.set(crypt, k, v)
    fd, temp = tempfile.mkstemp(prefix=".managed-rclone-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            config.write(fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return crypt


def complete(state, code, cloud):
    # State is single-use; failed grants cannot be replayed.
    with AUTH_LOCK:
        if (not isinstance(state, str) or not PENDING
                or not hmac.compare_digest(state, PENDING["state"])
                or time.monotonic() - PENDING["created"] > 600):
            raise ValueError("Google authorization expired. Start again in Settings.")
        pending = dict(PENDING)
        PENDING.clear()
    if not isinstance(code, str) or not 1 <= len(code) <= 4096:
        raise ValueError("Google did not return a valid authorization code.")
    payload = dict(code=code, client_id=pending["client_id"],
                   client_secret=pending["client_secret"],
                   redirect_uri=pending["redirect"], code_verifier=pending["verifier"],
                   grant_type="authorization_code")
    try:
        req = Request("https://oauth2.googleapis.com/token", data=urlencode(payload).encode(), method="POST")
        with urlopen(req, timeout=20) as response:
            obj = json.loads(response.read(16384))
    except (OSError, ValueError):
        raise ValueError("Google sign-in could not be completed. Try connecting again.") from None
    if not isinstance(obj, dict) or not obj.get("access_token") or not obj.get("refresh_token"):
        raise ValueError("Google did not grant offline backup access. Try connecting again.")
    try:
        expiry = datetime.now(timezone.utc) + timedelta(seconds=max(0, int(obj.get("expires_in", 3600))))
        token = {"access_token": obj["access_token"], "refresh_token": obj["refresh_token"],
                 "token_type": obj.get("token_type", "Bearer"),
                 "expiry": expiry.isoformat().replace("+00:00", "Z")}
        crypt = _create_remote(cloud, pending, token)
        return cloud.activate_google(crypt)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        raise ValueError("Encrypted Google Drive connection could not be saved.") from None
