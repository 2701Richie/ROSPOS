"""Encrypted cloud backups using only ROSPOS-managed Google OAuth destinations.

Google tokens stay in the POS computer private config, never in client responses.
This module performs no IO at import.
"""
import json
import sys
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from poscore import google_oauth

JOB_LOCK = threading.Lock()
MANAGED = re.compile(r"^rospos_crypt_[0-9a-f]{12}$")
BUNDLE = re.compile(r"^rospos-\d{8}T\d{6}-[0-9a-f]{8}\.zip$")


def config_path():
    return Path(os.environ.get("POS_CLOUD_CONFIG", str(Path.home() / ".config/rospos/cloud-backup.json")))


def _read():
    path = config_path()
    if not path.exists():
        return {}
    if (path.is_symlink() or path.stat().st_mode & 0o077
            or path.parent.is_symlink() or path.parent.stat().st_mode & 0o077):
        raise ValueError("Cloud configuration permissions are unsafe.")
    return json.loads(path.read_text(encoding="utf-8"))


def _write(data):
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (path.parent.is_symlink() or path.parent.stat().st_mode & 0o077
            or path.is_symlink() or (path.exists() and path.stat().st_mode & 0o077)):
        raise ValueError("Cloud configuration permissions are unsafe.")
    fd, tmp = tempfile.mkstemp(prefix=".cloud-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _rclone(*args, timeout=25):
    if not shutil.which("rclone"):
        raise RuntimeError("rclone is not installed on this computer.")
    result = subprocess.run(["rclone", *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Google Drive operation failed. Check the Google connection and internet access.")
    return result.stdout


def _managed_remotes():
    return google_oauth.managed_remotes(sys.modules[__name__])


def _managed_rclone(*args, timeout=25):
    # Never fall back to the user's global rclone.conf.
    return _rclone("--config", str(google_oauth.managed_path(sys.modules[__name__])),
                   *args, timeout=timeout)


def _managed_remote_valid(remote):
    """Only a paired Google Drive + encrypted remote made by ROSPOS can upload."""
    if not isinstance(remote, str) or not MANAGED.fullmatch(remote):
        return False
    suffix = remote[len("rospos_crypt_"):]
    drive = "rospos_drive_" + suffix
    try:
        remotes = _managed_remotes()
    except (OSError, ValueError):
        return False
    crypt = remotes.get(remote, {})
    backend = remotes.get(drive, {})
    folder = drive + ":ROSPOS-Encrypted/"
    destination = str(crypt.get("remote", ""))
    return (crypt.get("type") == "crypt"
            and destination.startswith(folder)
            and re.fullmatch(r"[0-9a-f]{16}", destination[len(folder):]) is not None
            and bool(crypt.get("password")) and bool(crypt.get("password2"))
            and crypt.get("filename_encryption", "standard") == "standard"
            and str(crypt.get("directory_name_encryption", "true")).lower() == "true"
            and backend.get("type") == "drive"
            and backend.get("scope") == "drive.file"
            and bool(backend.get("token")))


def begin_google_signin(client_id, client_secret, port):
    return google_oauth.begin(client_id, client_secret, port, sys.modules[__name__])


def complete_google_signin(state, code):
    return google_oauth.complete(state, code, sys.modules[__name__])


def status():
    try:
        data, error = _read(), ""
    except (OSError, ValueError) as exc:
        data, error = {}, str(exc)
    remote = data.get("remote", "")
    # An older saved disabled selection is not an active Google connection.
    connected = bool(data.get("enabled") and _managed_remote_valid(remote))
    return {"enabled": connected,
            "connected": connected, "remote": remote if connected else "",
            "reconnect_required": bool(remote and not connected),
            "last_success": data.get("last_success", "") if connected else "",
            "last_error": (data.get("last_error", "") or error) if connected else error,
            "running": JOB_LOCK.locked(), "rclone_installed": bool(shutil.which("rclone"))}


def activate_google(remote):
    """Called only after successful Desktop OAuth and creation of a crypt remote."""
    if not _managed_remote_valid(remote):
        raise ValueError("Google Drive encryption could not be verified.")
    _write({"remote": remote, "enabled": True})
    return status()


def disconnect():
    # Local disconnection never deletes Google files or revokes Google grants.
    _write({})
    return status()


def due():
    cfg = _read()
    return bool(cfg.get("enabled") and _managed_remote_valid(cfg.get("remote"))
                and cfg.get("last_success", "")[:10] != datetime.now().astimezone().date().isoformat())


def _bundle(path, database, archive_dir, lock):
    """Online SQLite snapshot plus immutable archived sales/logs in one compressed bundle."""
    with tempfile.TemporaryDirectory(prefix="rospos-snapshot-") as folder:
        snapshot = os.path.join(folder, "pos.db")
        with lock:
            with sqlite3.connect(snapshot) as target:
                database.backup(target)
            # Archived day files are safe to copy under the transaction lock.
            archive_files = []
            root = Path(archive_dir)
            if root.is_dir():
                for entry in sorted(root.iterdir()):
                    if entry.is_file() and not entry.is_symlink() and entry.suffix == ".json":
                        dest = os.path.join(folder, entry.name)
                        shutil.copyfile(entry, dest)
                        archive_files.append((dest, entry.name))
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(snapshot, "pos.db")
            for source, name in archive_files:
                z.write(source, "archives/" + name)
            z.writestr("manifest.json", json.dumps({"format": "ROSPOS-cloud-backup", "version": 1}))


def backup_once(database, archive_dir, lock, retention=30, reserved=False):
    """Background-only job. No network work occurs under the POS transaction lock."""
    if not reserved and not JOB_LOCK.acquire(blocking=False):
        return False
    try:
        cfg = _read()
        remote = cfg.get("remote", "")
        if not cfg.get("enabled") or not _managed_remote_valid(remote):
            return False
        name = "rospos-" + datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4) + ".zip"
        with tempfile.TemporaryDirectory(prefix="rospos-cloud-") as folder:
            path = os.path.join(folder, name)
            _bundle(path, database, archive_dir, lock)
            # rclone crypt encrypts file contents and filenames before uploading.
            _managed_rclone("copyto", path, remote + ":" + name, timeout=300)
        try:
            old = sorted(x for x in _managed_rclone("lsf", remote + ":", "--files-only", timeout=45).splitlines()
                         if BUNDLE.fullmatch(x))
            for stale in old[:-max(7, min(365, int(retention)))]:
                _managed_rclone("deletefile", remote + ":" + stale, timeout=45)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired):
            pass
        saved = _read()
        if saved.get("enabled") and saved.get("remote") == remote:
            saved["last_success"] = datetime.now().astimezone().isoformat(timespec="seconds")
            saved["last_error"] = ""
            _write(saved)
        return True
    except Exception:
        try:
            saved = _read()
            saved["last_error"] = "Cloud backup failed. Check Google Drive connection and local logs."
            _write(saved)
        except (OSError, ValueError):
            pass
        return False
    finally:
        JOB_LOCK.release()


def launch(database, archive_dir, lock, retention=30):
    """Reserve a single job slot immediately; return quickly to the cashier web server."""
    if not JOB_LOCK.acquire(blocking=False):
        return False
    worker = threading.Thread(target=backup_once,
                              args=(database, archive_dir, lock, retention),
                              kwargs={"reserved": True}, daemon=True, name="rospos-cloud-backup")
    try:
        worker.start()
    except Exception:
        JOB_LOCK.release()
        raise
    return True
