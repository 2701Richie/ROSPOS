# Encrypted Google Drive backups

ROSPOS is local-first: sales work offline. The Owner can connect a Google account
from **Settings → Encrypted Google Drive backups**. No terminal-based rclone
configuration is needed for the new sign-in flow.

## Connect Google Drive

1. Install ROSPOS with the Arch or Lubuntu installer, which installs rclone.
   Do not rerun an installer merely to authorize an account.
2. **One-time Google prerequisite:** Follow the
   [Google Drive client instructions](https://rclone.org/drive/#making-your-own-client-id)
   to create an OAuth client of type **Desktop app** in Google Cloud Console.
   Enable the Google Drive API and configure the OAuth consent screen. Copy
   the Desktop client's ID and secret. Google's shared rclone client is
   retiring during 2026; this requirement cannot safely be skipped. For a
   Google app in testing mode, Google's refresh-token expiry restrictions may
   prevent long-running backups; configure an appropriate published app.
3. **On the ROSPOS server computer itself**, open the browser at
   `http://127.0.0.1` (or `http://127.0.0.1:8000` if running the server on
   port 8000). Sign into ROSPOS as Owner and open **Settings**.
4. Paste the Google Desktop client ID and secret, enter your current ROSPOS
   Owner password, and choose **Connect Google Drive**.
5. **Important:** Copy the displayed backup password, backup salt, and
   destination folder to a secure place **outside the POS computer**.
   You need all three plus access to the same Google account to restore after
   a device failure. A lost password or salt means cloud data cannot be decrypted.
   Tick the confirmation checkbox before continuing.
6. Choose **Continue to Google sign-in**, select your Google account, and grant
   Google Drive file access. The browser returns to a local ROSPOS confirmation.
   The connection is automatically enabled, and the first encrypted backup is
   queued immediately. Backups continue daily in the background.
7. Return to ROSPOS Settings and press **Refresh accounts** to see the connected
   destination and check the last-success or error status.

**Browser restriction:** Google Desktop OAuth redirects to 127.0.0.1 on the
device running the browser. Connect from a browser *on the POS server computer*,
not from a phone or another LAN computer. After connection, the ordinary ROSPOS
Settings interface can be viewed from the store LAN by an Owner.

**Security:** Owner password is required to begin sign-in, change cloud
settings, back up manually or disconnect. Authorization uses short-lived,
single-use state and PKCE. Google authorization codes are exchanged on the POS
computer; access/refresh tokens never enter the browser. Only the recovery
password/salt are deliberately displayed once to the Owner, to allow recovery
after loss of the server. These keys must not be shared or stored in Git.

The managed Google credentials and rclone crypt configuration are stored with
private permissions at `~/.config/rospos/managed-rclone.conf` by default.
Selected remote and backup status are stored at
`~/.config/rospos/cloud-backup.json`. `POS_CLOUD_CONFIG` changes the base
location of both files. Each sign-in creates a separate encrypted Google Drive
folder to avoid mixing installations' backup data. Cloning ROSPOS does not
inherit credentials, pharmacy data, or encryption keys.

## Existing rclone setup (advanced, optional)

Existing configured rclone Google Drive + crypt remotes are still supported:
select a remote in the dropdown, enable backups, enter the Owner password, and
save. It must use standard filename encryption and enabled directory encryption
on top of a Google Drive remote. This compatibility mode does not require the
new browser sign-in. Never point a cloud backup at an unencrypted Drive remote.

## Backup behavior and recovery

- Local hourly/daily backups remain available when offline.
- Enabling cloud backup uploads a consistent temporary SQLite snapshot,
  historical sales, and audit archives in an encrypted ZIP package. The
  rclone **crypt** backend encrypts file contents and filenames.
- Network uploads do not block sales. Failures are recorded and retry on
  subsequent scheduling checks.
- Retention keeps between 7 and 365 recognized ROSPOS bundles and never
  prunes unrelated files.
- Disconnecting stops future uploads but does **not** delete remote files,
  revoke Google's grant, or delete the private rclone credential file.
- To recover on a replacement computer, connect to the **same Google
  account**, recreate a crypt remote pointing to the **recorded folder** using
  the original password **and salt**, then download a bundle into a separate
  temporary recovery installation and verify its SQLite snapshot and archives.
  Do not restore over the live POS database. The existing JSON restore screen
  cannot restore cloud ZIP/database snapshots.

Current status: Automated tests cover OAuth permissions, redirects, state
validation, token non-disclosure, private config, and simulated rclone
integration. **Real Google authorization, upload, and recovery have not
been validated** and are required before relying on cloud backups in production.

ROSPOS currently serves plain HTTP on a trusted store LAN. Do not expose its
service port to the public internet. Access across untrusted networks must use
properly configured HTTPS/VPN protection.
