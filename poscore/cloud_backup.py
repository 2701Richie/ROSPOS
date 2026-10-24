"""Optional encrypted cloud backups using the user's local rclone Google Drive crypt remote.

OAuth credentials are maintained by rclone outside Git and never reach POS clients.
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
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
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
        raise RuntimeError("Google Drive operation failed. Check rclone configuration and internet access.")
    return result.stdout


def _managed_remotes():
    return google_oauth.managed_remotes(sys.modules[__name__])


def _rclone_for(remote, *args, timeout=25):
    if remote in _managed_remotes():
        return _rclone("--config", str(google_oauth.managed_path(sys.modules[__name__])),
                       *args, timeout=timeout)
    return _rclone(*args, timeout=timeout)


def begin_google_signin(client_id, client_secret, port):
    return google_oauth.begin(client_id, client_secret, port, sys.modules[__name__])


def complete_google_signin(state, code):
    return google_oauth.complete(state, code, sys.modules[__name__])


def encrypted_drive_remotes():
    """Reject unencrypted remotes, including crypt remotes backed by non-Google providers."""
    if not shutil.which("rclone"):
        return []
    try:
        cfg = json.loads(_rclone("config", "dump"))
    except (ValueError, RuntimeError, subprocess.TimeoutExpired):
        cfg = {}
    try:
        cfg.update({k: v for k, v in _managed_remotes().items() if k not in cfg})
    except (OSError, ValueError):
        return []
    found = []
    for name, info in cfg.items():
        if not NAME.fullmatch(name) or info.get("type") != "crypt":
            continue
        target = str(info.get("remote", ""))
        base = target.split(":", 1)[0] if ":" in target else ""
        if (base != name and cfg.get(base, {}).get("type") == "drive"
                and info.get("password")
                and info.get("filename_encryption", "standard") == "standard"
                and str(info.get("directory_name_encryption", "true")).lower() != "false"):
            found.append(name)
    return sorted(found)


def status(with_remotes=False):
    try:
        data, error = _read(), ""
    except (OSError, ValueError) as exc:
        data, error = {}, str(exc)
    result = {"enabled": bool(data.get("enabled")), "remote": data.get("remote", ""),
              "last_success": data.get("last_success", ""),
              "last_error": data.get("last_error", "") or error,
              "running": JOB_LOCK.locked(), "rclone_installed": bool(shutil.which("rclone")),
              "managed": str(data.get("remote", "")).startswith("rospos_crypt_")}
    if with_remotes:
        result["remotes"] = encrypted_drive_remotes()
    return result


def configure(remote, enabled):
    if not isinstance(remote, str) or not NAME.fullmatch(remote) or type(enabled) is not bool:
        raise ValueError("Invalid cloud backup settings.")
    if remote not in encrypted_drive_remotes():
        raise ValueError("Choose a configured encrypted Google Drive remote.")
    saved = _read()
    if saved.get("remote") != remote:
        saved.pop("last_success", None)
        saved.pop("last_error", None)
    saved.update(remote=remote, enabled=enabled)
    _write(saved)
    return status(with_remotes=True)


def disconnect():
    # Local disconnection never deletes Google files or revokes Google grants.
    _write({})
    return status(with_remotes=True)


def due():
    cfg = _read()
    return bool(cfg.get("enabled") and cfg.get("remote")
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
        if not cfg.get("enabled") or remote not in encrypted_drive_remotes():
            return False
        name = "rospos-" + datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4) + ".zip"
        with tempfile.TemporaryDirectory(prefix="rospos-cloud-") as folder:
            path = os.path.join(folder, name)
            _bundle(path, database, archive_dir, lock)
            # rclone crypt encrypts file contents and filenames before uploading.
            _rclone_for(remote, "copyto", path, remote + ":" + name, timeout=300)
        try:
            old = sorted(x for x in _rclone_for(remote, "lsf", remote + ":", "--files-only", timeout=45).splitlines()
                         if BUNDLE.fullmatch(x))
            for stale in old[:-max(7, min(365, int(retention)))]:
                _rclone_for(remote, "deletefile", remote + ":" + stale, timeout=45)
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
