# NOTES: ROSPOS

Internal stock and sales counting tool. Python server on the store laptop, screens in the browser. For setup see README.md.

## Start here (agents: read only this section, then just the files your task needs)

**Before touching anything:** `git status -sb` and `git log --oneline -5` (other agents edit this repo too; never reset, stash or discard edits you did not make). Repo-local git identity stays as configured. No personal data in code or notes. Commit small, push only when the owner says.

**Safety:** never touch `data/` or `backups/` (real database), never start, stop or restart the POS server without asking. Tests use temp folders and a temp server on port 8998.

**Which file for which task** (details in the Files table below):

| Task | Read |
|---|---|
| Rule, data or endpoint change | `server.py`: find the `r_<operation>` function with `grep -n "^def r_" server.py`, read only that slice |
| Screen or behaviour of one tab | `js/<tab>.js` (sell, products, receipts, reorder, reports, livesales, import, accounts, settings) |
| Shared state, `api()`, sign-in, roles | `js/core.js` |
| Layout, popups, tab order | `index.html` (structure only) |
| Look, dark mode, phones | `style.css`: search `grep -n "^/\*" style.css` for the section, phone rules are near the end |
| Install or setup | `install-lubuntu.sh`, `install-arch.sh`, `README.md` |
| Decided rules, data shapes | sections below: Data shapes, Endpoints, Rules already decided |

**Run the tests (one command, prints one line, then only failures):**
- `python3 tests/run.py` tests the working tree including uncommitted edits.
- `python3 tests/run.py --clone` clones GitHub and tests that (run it after every push).
- `python3 tests/run.py -v` adds the full output of each check. Each check also runs alone: `tests/e2e.py`, `tests/numeric_validation_test.py`, `tests/archive_test.py`, `tests/theme_test.js` (each takes an optional source folder).
- Add a test for every new rule: put `ok   ...` / `FAIL ...` lines in a new `tests/*_test.py` and add its name to `run.py`.

**Screenshots (only for visual work):** the harness lives outside the repo, in `pos-tests/demo` next to the project folder. `bash pos-tests/demo/shoot.sh` copies the front-end, injects fake data (`demo.js`), serves it on port 8077 and saves PNGs in `/tmp/shots` with headless chromium. URL knobs: `?tab=sell|live|rep|set|receipt&taps=0|1|2` (taps = theme button presses). Look at one image, not all.

**Token habits:** grep and read line ranges, not whole files (`server.py` ~870 lines, `style.css` ~310, `js/reports.js` is the largest script). Use `git diff` instead of re-reading. Edit in place and send only changed files. Run `tests/run.py` once at the end, not after every edit.

**In progress:** daily sales archive (older than 7 days, `archives/`) is committed locally, not pushed. Archive is hardened: sale numbers survive upgrades of older databases, an unreadable archive file is kept aside (`.corrupt-*`) instead of overwritten, archive errors never stop the server or backups, restore rejects odd sale numbers, dates and expiry values. Queued, not started: in-app updater (owner only, safety backup first); see "Roadmap" below.

## Files

| File | What it holds |
|---|---|
| `install-lubuntu.sh` | One-time setup for the store laptop (Lubuntu/Ubuntu/Debian): boot service, `pos.local` name, port 80, firewall, desktop icon. `--uninstall` undoes it |
| `install-arch.sh` | Same setup for Arch, used for testing |
| `server.py` | All data and rules. SQLite in `data/pos.db`, hourly backups, daily sales archives, password re-checks, one function per operation (`r_sale`, `r_void`, ...) |
| `archives/` | One readable JSON file per day (`sales-YYYY-MM-DD.json`) for sales and audit rows older than 7 days. Not in git. Local only, like `data/` |
| `index.html` | Page structure only: header tabs, the four sections, popups |
| `style.css` | All styling, light and dark |
| `js/core.js` | Shared state `S`, helpers (`R`, `M`, `esc`, `tags`), `api()`, `load()`, `show(tab)`, sign-in screen and role checks (`can()`) |
| `js/sell.js` | Sell tab: `drawGrid`, cart (`drawLines`, `add`), checkout (`#pay`), `receipt()` popup, `clampCart` |
| `js/products.js` | Products tab (managers and owners): add/edit form, quantity Add/Set, stock log with who made each change |
| `js/accounts.js` | Accounts tab (owner): add accounts, roles, reset password, disable |
| `js/settings.js` | Settings tab (owner): store name, stay-signed-in hours, backup days kept. Also `storeName()` and `applyBrand()` used for the header, order list and receipt, and the theme button in the header (every role, this device only: Automatic, Light, Dark; saved in the browser as `pos-theme`, applied early by a script in `index.html`) |
| `js/import.js` | CSV import (preview, apply), export products, download template. Parsing happens in the browser, rules in `r_import` |
| `js/reports.js` | Reports tab: today's totals, alerts, recent sales, backup show/restore |
| `js/reorder.js` | Reorder tab: reorder-now and getting-low lists, editable order quantities, print/PDF and CSV order list. Client only, no server change |
| `js/receipts.js` | Receipts tab: sale list, view, password-protected void and change popups |
| `js/livesales.js` | Live Sales tab: today's sales as a newest-first feed (tap a row for items; filters by status and cashier; new sales highlight briefly) plus a "sold today by product" tally with search. Refreshed every 5 seconds from `/api/state`. Client only |
| `js/fullscreen.js` | Full-screen button in the header (hidden where the browser cannot) |
| `js/main.js` | Startup and the 15-second refresh on the Sell tab |

Scripts are plain (not modules) and share one global scope. Load order is in `index.html`.

## Data shapes (all in `S` on the client, one JSON blob on the server)

- Product: `{id, n:name, p:price, s:stock, e:"YYYY-MM-DD" or "", m:reorder level}`
- Sale: `{no, d:date, t:time, l:[{id,n,q,p}], tot, cash, by:name, uid, v?:{d,t,w,u}, h?:[{d,t,w,a,z,u}]}`. `v` means void, `h` is change history, `w` is the reason, `u` is who. Sales from older versions may also carry `sub`, `dc`, `dl` (a discount).
- Stock/audit log: `{d, t, n:product, k:what happened, a:count before, z:count after, u:who, i:product ID, w:reason}`. Older entries may lack `i` and `w`; normal sales now create a stock-decrease entry.
- Accounts (kept in the database, never sent with the state): `{id, username, name, role: staff|manager|owner, active, salt, hash}`. `S.today` is the laptop's date.

## Endpoints (POST JSON; header `X-Requested-With: pos` required; every reply includes fresh `state`)

Sessions use an HttpOnly cookie (`pos_session`, SameSite=Strict, 12 hours, `POS_SESSION_HOURS` to change). 401 means sign in again.

| Path | Who | Does |
|---|---|---|
| GET `/api/me` | anyone | `{setup, me}`; `setup` is true until the owner account exists |
| `/api/setup` | anyone, needs the setup code from the server log | Creates the first owner account |
| `/api/login`, `/api/logout` | anyone / signed in | Sign in and out. 5 wrong tries lock that device and username for a minute |
| GET `/api/state` | signed in | Current state and `me` |
| `/api/sale` | staff and up | Server checks stock and expiry, prices from its own list, reduces stock |
| `/api/product`, `/api/delete`, `/api/stock`, `/api/import` | manager and up | Product and stock edits. Import: mode `products`, `add` or `set`; `apply:false` previews, `apply:true` saves after a copy in `backups/pre-import-*.db`; all or nothing |
| `/api/void`, `/api/change` | manager and up, plus `password` of the signed-in user in the request | Void or amend a sale |
| `/api/restore` | owner, plus `password` | Restore a backup |
| `/api/users`, `/api/user` | owner | List, add, edit, disable accounts (always one active owner) |
| `/api/settings` | owner (re-enter password) | Save store name, stay-signed-in hours (1 to 72), backup days kept (7 to 365). Stored in the `kv` table under `settings`, outside the sales data so a restore never changes them. Each change is written to the activity log as product "Settings". Sent to every client as `S.cfg` |
| `/api/mypassword` | signed in | Change own password (`old`, `new`) |

Errors come back as `{error}`.

## Rules already decided

- Roles: staff sell, view and reprint receipts, and see the Reorder list. Managers also change products and stock, import CSV, see Reports and Live Sales, and void or change sales (re-entering their own password). Owners also manage accounts, settings and restore backups. The server enforces this; hiding tabs is only for tidiness.
- Every sale, stock change, price change, void and change records the signed-in person's name. Checkout stock reductions are recorded in the inventory accountability log. Product deletion and CSV imports require a reason; routine stock changes are logged with an automatic description.
- No discounts and no VAT: the price is the price. Old sales from earlier versions may still show a discount.
- Expired products can't be sold. Selling past stock is refused. Expiry date is optional per product; blank means never flagged or blocked.
- Sales are never deleted. Void returns stock and keeps the sale marked void. Change edits quantities and cash.
- Live state keeps about 7 days of sales and audit rows (`POS_HOT_DAYS`, default 7). Older rows are moved automatically (on startup and hourly) into `archives/sales-YYYY-MM-DD.json` (format `ROSPOS-day-archive`). Receipts, voids, changes, Live Sales and Reports only see the live week; open the archive file to read an older day. Sale numbers keep increasing via `sale_seq` so archiving never reuses a number.
- Reorder tab: "now" is stock at or below the reorder level, "getting low" is up to 25% above it (margin kept in the browser). Suggested order quantity brings stock to double the reorder level. Products with no reorder level are ignored. Order list layout: #, Product Name, Quantity, Price (blank), A to Z.
- Counting is manual: staff report counts to the owner or manager, who check the system.
- 90 days is the "expiring soon" window.

## How to add a feature

1. Find the screen: edit its one `js/*.js` file (and `index.html` / `style.css` if needed).
2. If it changes data, add or edit one `r_*` function and a line in `ROUTES` in `server.py`. Validate everything on the server.
3. Update this file's data shapes, endpoints, or rules if they changed.

## Roadmap (planned, none of this is built; order = suggested build order, owner picks)

Each feature gets: its own small commit, a test in `tests/`, and a line in NOTES. CSV bulk add/edit already exists (`js/import.js`); the items below are new.

| # | Feature | Size | Touches | Notes and risks |
|---|---|---|---|---|
| 1 | Zero-quantity items always in the Reorder list | tiny | `js/reorder.js` | Show stock 0 items first, even without a reorder level. |
| 2 | Full-screen button | tiny | `index.html`, `js/core.js`, `style.css` | Browser Fullscreen API; hide where unsupported (some phones). |
| 3 | Bulk quantity on Sell (add 5 or 10 at once) | small | `js/sell.js` | Typed quantity or +5/+10 buttons; must respect stock limit and `MAX_NUM`. |
| 4 | Bulk delete in Products (manager and owner only) | small | `js/products.js`, `server.py` (new `r_delete_many`) | Owner PIN, one audit row per item, snapshot first, all-or-nothing. Sold items keep their sale lines. |
| 5 | Cost field on products | medium | `server.py` (`r_product`, import, restore validation), `js/products.js`, `js/import.js` | New field `c` (cost per unit, optional, 0 = unknown). CSV column optional so old files still import. Needed by 6. |
| 6 | Reports: total inventory cost and estimated replenishment cost | medium | `js/reports.js` | Needs 5. Replenishment = (reorder level - stock) x cost for low items; show "cost unknown" count. |
| 7 | In-app updater (owner only) | large | `server.py`, `js/settings.js`, `install-*.sh` | Safety backup first, run `tests/run.py` on the new code before switching, keep previous version for one-click rollback. Decide method first: git pull or uploaded zip. Never restart without owner confirming. |
| 8 | Remote access to the store laptop | infra | outside the repo | For updates and fixes. Prefer a private tunnel (no open router ports) plus the existing login. Decide tool before building. |
| 9 | Sections, printable count sheets, manager "check counts" screen, differences report | large | new `js/counts.js`, `server.py`, `index.html`, `style.css` | Counting stays manual; staff assigned to sections. Build in this order: sections on products, count sheets, check-counts screen, differences report. |
| 10 | Later | n/a | n/a | Write-offs, daily comparison with the official POS, batch numbers, HTTPS and a sturdier web server. |

Dependencies: 6 needs 5. 7 needs the test runner (done). 9 is easier after the `server.py` split is decided.

## Not built yet

Sections on products with responsible staff, printable count sheets, a manager "check counts" screen and a differences report (planned next). Later: write-offs, daily comparison with the official POS, batch numbers, HTTPS and a sturdier web server if it moves to the cloud.

- Sales forecast in Reports: client-side 7/30/90-day store-wide revenue and transaction estimates from non-voided sales, using weekday averages and a capped recent trend factor. Forecasts are estimates, not guarantees. Confidence is shown from days of history: under 28 days is "low" (about ±40% range), under 56 is "medium" (±25%), more is normal (±15%); the 90-day view adds 10 points. The likely range appears under the projected revenue. Reports "Low stock" only lists products with a reorder level above 0, same as the Reorder tab. No extra libraries or server endpoint are required.
- UI polish: subtle hover/focus states, responsive forecast cards/chart, quick SVG line animation, and reduced-motion support. Forecast data is calculated in the browser from the loaded sales state.
