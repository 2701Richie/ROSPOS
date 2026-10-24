# ROSPOS: Point of Sale System

The HTTP server and transaction handlers are in `server.py`, with shared backend services in `poscore/`. The screens are `index.html`, `style.css` and the `js` folder. Keep all of these together in one folder. Needs Python 3.8 or newer. Nothing else to install.

## Getting it onto a new laptop

```
sudo apt install -y git gh
gh auth login
gh repo clone 2701Richie/ROSPOS
cd ROSPOS
sudo bash install-lubuntu.sh
```

The repository is private, so GitHub asks you to sign in first (`gh auth login`: choose GitHub.com, HTTPS, and sign in through the browser). If `gh` is not available on that laptop, create a personal access token on GitHub (Settings, Developer settings, Personal access tokens, read access to this repository) and use `git clone https://github.com/2701Richie/ROSPOS.git`, entering the token as the password.

Your sales data and accounts are **not** stored on GitHub, so a new laptop starts empty. Open `http://pos.local`, enter the setup code (shown with `journalctl -u pos -n 20`) and create the owner account. To bring old data over, download a backup from Reports on the old laptop and restore it here (owner only).

## Easy setup (Lubuntu store laptop, recommended)

In this folder run once:

```
sudo bash install-lubuntu.sh
```

It installs what is needed, starts the POS at every boot (and restarts it if it stops), gives it the name `http://pos.local` on port 80 (no `:8000`), opens the firewall if one is running, and adds an **Open ROSPOS** icon for the person using the laptop. Undo with `sudo bash install-lubuntu.sh --uninstall`; data is kept.

- **Permanent address:** `pos.local` never changes. Most iPads, Windows, Mac, Linux and recent Android devices can open it. If one can't, use the laptop's IP address, which the script prints. To keep that number from changing, reserve it for the laptop in the router (look for DHCP reservation or address reservation).
- Keep the folder path free of spaces.
- If nothing else uses port 80, the service needs no changes. To change the port, edit `POS_PORT` in `/etc/systemd/system/pos.service`.
- Logs: `journalctl -u pos -e`. Restart: `sudo systemctl restart pos`.

On Arch (for testing) use `sudo bash install-arch.sh` instead. It does the same thing using pacman.

The manual steps below still work if you prefer them.

## Cloud server / development clone

The repository is code-only: `data/`, `backups/`, and `archives/` are intentionally excluded from Git. A fresh clone starts with an empty database and first-time owner setup. Do not copy the store database into Git to migrate data; use the owner backup/restore flow described below.

For a development VM, install Git, Python 3, and Node.js (Node is only needed for the JavaScript checks), clone the private repository, then run `python3 tests/check.py`. This runs against temporary test databases and checks that the real data folders are unchanged. To validate the published clone from an existing checkout, use `python3 tests/check.py --clone`.

**Do not expose the POS server directly to the public internet.** ROSPOS currently serves plain HTTP and is intended for a trusted local network. For remote/cloud access, keep port 8000 blocked from public access and use a properly configured HTTPS reverse proxy plus firewall/VPN before using real data. The laptop installer scripts are intended for supported desktop/laptop setups, not generic cloud provisioning.

## Run it

```
python3 server.py
```

On the laptop, find its address with `hostname -I`, for example `192.168.1.50`. On a tablet or PC on the same Wi-Fi or network, open `http://192.168.1.50:8000`.

Open the POS in a browser. The first screen asks for the **setup code**, which is printed in the server log when no account exists yet (`journalctl -u pos -n 20`, or the terminal where you ran `python3 server.py`). Use it to create the owner account, then add staff and managers on the **Accounts** tab. Forgot the owner password? Stop nothing, just run `python3 server.py --reset-password USERNAME` on the laptop, then `sudo systemctl restart pos`.

## Make it reliable

1. **Fixed address.** In the router, reserve the same IP for the laptop (DHCP reservation), so tablets can always find it.
2. **Firewall.** If the laptop uses ufw: `sudo ufw allow 8000/tcp`.
3. **Start on boot.** Create `/etc/systemd/system/pos.service`, replacing `YOURUSER` and the path:

```
[Unit]
Description=ROSPOS
After=network.target

[Service]
User=YOURUSER
WorkingDirectory=/home/YOURUSER/pos
ExecStart=/usr/bin/python3 /home/YOURUSER/pos/server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Then run `sudo systemctl enable --now pos`. View errors with `journalctl -u pos -e`.

4. **Laptop settings.** Plug it in, turn off sleep and suspend on lid close, and keep it where cashiers can't reach it.

## Data and backups

- All data is in `data/pos.db` (SQLite). The server needs write access to that folder.
- The server refreshes `backups/pos-YYYY-MM-DD.db` hourly and keeps the latest 30 daily copies. Restore actions and imports also create timestamped safety snapshots.
- In Reports, the owner can download a portable `rospos-backup-YYYY-MM-DD.json` file. Store a copy on a USB drive or another computer; the file contains product, sales and activity history.
- To restore, select the JSON file in Reports, enter the owner password and confirm. ROSPOS validates the contents and creates a pre-restore database snapshot before replacing current product, sales and activity data. User accounts are not replaced.
- To keep automatic database backups on a USB drive, start the server with `POS_BACKUP_DIR=/media/you/USB/pos-backups`. Add it as an `Environment=` line in the service file. Ensure the drive is mounted before ROSPOS starts.
- Keep at least one backup somewhere other than the store laptop. A backup stored only on the same laptop does not protect you if the laptop dies.
- Older browser-version text backups can still be restored from the “Legacy text backup” section in Reports.

## Settings (environment variables)

`POS_PORT` (default 8000), `POS_DB`, `POS_BACKUP_DIR`.

## What it enforces

- Sales are created by the server, which checks stock and expiry and uses its own prices and clock. Devices can't edit stock or old sales.
- Everyone signs in. Staff can sell and look things up. Managers can also change products and stock and void sales (re-entering their own password). Owners also manage accounts. Sessions last 12 hours.
- Five wrong passwords from a device lock that device out for a minute.
- Every stock change, price change, void, and change is logged with the laptop's time.

## Limits

- Plain HTTP on your own network. Anyone on that Wi-Fi could in theory watch the traffic, so use a password-protected Wi-Fi network.
- Someone with access to the laptop itself can read or change `data/pos.db`.
- If the laptop is off, nobody can ring sales. Keep a paper fallback.
