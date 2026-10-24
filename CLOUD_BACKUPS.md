# Encrypted Google Drive backups (optional)

ROSPOS remains local-first. Each installation connects to a Google account chosen by its owner. Nothing is uploaded before the owner enables this feature.

## Set up on the computer running ROSPOS

1. Run the normal ROSPOS installation script for your system: **install-arch.sh** or **install-lubuntu.sh** now installs `rclone` from the distribution package manager and checks that it runs. If your distribution package is outdated or the `rclone` package is unavailable, see https://rclone.org/install/ for the official supported installation methods. Do not run the entire ROSPOS installer as a way to connect a Google account.
2. Open a terminal as the same Linux user that runs the ROSPOS server (not as root) and enter `rclone config`.
3. Create a Google Drive remote named, for example, `pharmacydrive`. Choose your Google account in the authorization browser window. Google's shared rclone OAuth client is being retired in 2026; follow https://rclone.org/drive/#making-your-own-client-id to create a Google OAuth Desktop app client in Google Cloud Console and enable the Google Drive API.
4. In `rclone config`, create a second remote named, for example, `pharmacycrypt`, of type **crypt**. Set its destination to `pharmacydrive:ROSPOS-Encrypted`; choose **standard** filename encryption and enabled directory-name encryption; generate a strong crypt password. Keep the crypt password and optional salt in a separate safe place: without them you cannot restore your backups after device loss.
5. Sign into ROSPOS as Owner; visit **Settings → Encrypted Google Drive backups**. Click Refresh accounts, select `pharmacycrypt`, enable daily backups, enter the ROSPOS Owner password and save. Use Back up now for the first upload. Reopen Settings to check last-success status.
6. To switch Google accounts, create a new Drive+crypt remote pair in rclone with new names and select the new encrypted remote in Settings. Old cloud files remain in the old account.

The application stores only the remote selection, enabled flag, and backup status in a local file, by default `~/.config/rospos/cloud-backup.json`, restricted to the server user. The optional `POS_CLOUD_CONFIG` environment setting can change that path. rclone stores its own authorization credentials and encryption configuration in that Linux user's private rclone configuration. **Never add either config file, token, or crypt password to Git.**

## Behavior and recovery

- Existing hourly local backups are unchanged and remain available offline.
- When enabled, a daily cloud backup makes a consistent temporary SQLite snapshot and includes the archived sales/history JSON files. It compresses them into a ZIP; the rclone **crypt** remote encrypts the ZIP and filename before Google Drive receives them.
- Automatic uploads operate outside sales/checkout processing, and an outage does not stop selling. Failed backups can retry hourly. The owner can run a manual backup.
- ROTATION: old backups are removed according to configured retention (7–365); only filenames matching the ROSPOS backup convention are eligible for cleanup.
- Disconnecting prevents future uploads but **does not** revoke Google's OAuth grant or delete existing backups. Revoke access in your Google account or remove the relevant rclone remote separately.
- To recover after machine failure, configure rclone with the original Drive account and crypt credentials on a **separate recovery computer** and copy files from `pharmacycrypt:` to a private local folder. The decrypted ZIP contains `pos.db`, `archives/`, and a manifest. Verify it in a temporary test installation first. **Never overwrite a live, running database.**
- The existing JSON import/Restore interface does **not** yet restore cloud ZIP/database snapshots. Recovery is a separate manual procedure pending a dedicated tested restoration wizard.

Security: ROSPOS currently uses HTTP on the trusted store LAN. Do not expose its port publicly; use an HTTPS proxy/VPN for access across untrusted networks. Google OAuth itself is completed through rclone's browser authorization, not through the ROSPOS login screen.
