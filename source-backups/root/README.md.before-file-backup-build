# ROSPOS: Point of Sale System

Two files run it: `server.py` (holds the data) and `index.html` (the screens). Keep them in the same folder. Needs Python 3.8 or newer. Nothing else to install.

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
- Every hour the server writes today's copy to `backups/pos-YYYY-MM-DD.db` and keeps the last 30 days. To store them on a USB drive, start the server with `POS_BACKUP_DIR=/media/you/USB/pos-backups`. Add it as an `Environment=` line in the service file.
- To restore: stop the server, copy a backup file over `data/pos.db`, and start it again.
- Copy the USB drive somewhere else regularly. A backup on the same laptop does not protect you if the laptop dies.
- To move your test data from the browser version: Reports, Show backup, copy the text. Paste it into Restore on this version.

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
