# NOTES: ROSPOS

Internal stock and sales counting tool. Python server on the main PC or store machine, screens in the browser. For setup see README.md.

## Start here (agents: read only this section, then just the files your task needs)

**Before touching anything:** `git status -sb` and `git log --oneline -5` (other agents edit this repo too; never reset, stash or discard edits you did not make). Repo-local git identity stays as configured. No personal data in code or notes. Commit small, push only when the owner says.

**Safety:** never touch `data/` or `backups/` (real database), never start, stop or restart the POS server without asking. Tests use temp folders and a temp server on port 8998.

**Pushing:** `origin` uses SSH (`git@github.com:2701Richie/ROSPOS.git`), so `git push origin master` needs no password. Always run it as `GIT_TERMINAL_PROMPT=0 timeout 60 git push origin master` and write the output to a file: if it ever stalls it is waiting for a password, so stop it instead of waiting (a stalled HTTPS push is how this was found). Never put a token in the remote URL or in a file. After every push run `python3 tests/run.py --clone` to prove a fresh copy from GitHub passes.

**Which file for which task** (details in the Files table below):

| Task | Read |
|---|---|
| Rule, data or endpoint change | `server.py`: find the `r_<operation>` function with `grep -n "^def r_" server.py`, read only that slice |
| Screen or behaviour of one tab | `js/<tab>.js` (sell, products, receipts, reorder, reports, livesales, import, logs, accounts, settings) |
| Shared state, `api()`, sign-in, roles | `js/core.js` |
| Layout, popups, tab order | `index.html` (structure only) |
| Look, dark mode, phones | `style.css`: search `grep -n "^/\*" style.css` for the section, the consolidated Navigation section owns desktop and mobile sidebar layout; avoid reviving obsolete `header nav` overrides |
| Install or setup | `install-lubuntu.sh`, `install-arch.sh`, `README.md` |
| Decided rules, data shapes | sections below: Data shapes, Endpoints, Rules already decided |

**Check engine (use this first): `python3 tests/check.py`** finds every `tests/*_test.py|js` and `e2e.py` by itself, runs them in parallel, and prints one line then only failures (details of the last run: `/tmp/rospos-check-last.json`).
- `--fast` (~1 s, skips slow checks) for every edit; plain run (~15 s, adds real-browser + speed checks) before a commit; `--deep` (5x more random requests/steps) before a release; `--clone` after every push.
- A failure line ends with the exact command and seed to repeat it: `CHECK_SEED=7 python3 tests/fuzz_test.py`. `--only fuzz,sim`, `--skip browser`, `--table` (timings and speed metrics), `--seed random`.
- What it covers: `permissions` (every endpoint x every role), `fuzz` (thousands of hostile requests, seeded), `simulation` (random sales/voids/purchases/imports/backups/day changes against an independent stock model, plus a many-tablet race), `source_scan` (syntax, doubled-backslash regex, ids, routes, permission calls, unescaped text), `browser` (headless Chromium: tabs per role, script-injection payloads, sale flow, big-catalogue draw time), `perf` (4k-5k products server side) and the older numeric/e2e/etc. checks.
- **New check:** `python3 tests/check.py --new NAME` writes `tests/NAME_test.py` from a template (helpers in `tests/harness.py`: `boot`, `Store.call(path, body, role)`, `seed`, `invariants`). Nothing to register; it is picked up automatically. Print `ok   ...`/`FAIL ...` (or `PASS ...`) lines, `METRIC name value unit`, `SKIP reason`.
- **Prove the checks work:** `python3 tests/check.py --selftest` re-introduces 8 known old bugs into a temp copy and fails if any check misses one. When you fix a new class of bug, add it to `MUTATIONS` in `tests/check.py`.
- Checks only write to temp folders; the engine fails if real `data/`, `backups/`, `archives/` change or a check creates a new file in the repo. Edits by someone else during a run only print a note.

**Older single runner (still works):**
- `python3 tests/run.py` tests the working tree including uncommitted edits.
- `python3 tests/run.py --clone` clones GitHub and tests that (run it after every push).
- `python3 tests/run.py -v` adds the full output of each check. Each check also runs alone: `tests/e2e.py`, `tests/numeric_validation_test.py`, `tests/archive_test.py`, `tests/bulk_delete_test.py`, `tests/cost_test.py`, `tests/receipt_settings_test.py`, `tests/logs_test.py`, `tests/theme_test.js`, `tests/js_logic_test.js` (each takes an optional source folder).
- Add a test for every new rule with `python3 tests/check.py --new NAME` (no registration needed; `run.py` lists its checks by hand).

**Phase 5 CSS regression:** `PYTHONDONTWRITEBYTECODE=1 python3 tests/css_snapshot.py --verify` checks the responsive sidebar and light/dark themes in isolated headless Chromium (42 combinations; no POS database). For a controlled CSS-only refactor, capture an original snapshot using `--write /tmp/rospos-css-before.json`, make changes, then compare using `--compare /tmp/rospos-css-before.json`. The tool serves the actual stylesheet over an isolated local static server and disables transitions while sampling layout. ChromeDriver is optional and this test is not part of the standard quick suite.

**Screenshots (only for visual work):** the harness lives outside the repo, in `pos-tests/demo` next to the project folder. `bash pos-tests/demo/shoot.sh` copies the front-end, injects fake data (`demo.js`), serves it on port 8077 and saves PNGs in `/tmp/shots` with headless chromium. URL knobs: `?tab=sell|live|rep|set|receipt&taps=0|1|2` (taps = theme button presses). Look at one image, not all.

**Token habits:** grep and read line ranges, not whole files (`server.py` ~870 lines, `style.css` ~310, `js/reports.js` is the largest script). Use `git diff` instead of re-reading. Edit in place and send only changed files. Run `tests/run.py` once at the end, not after every edit.

**In progress:** daily sales archive (older than 7 days, `archives/`) is committed locally, not pushed. Archive is hardened: sale numbers survive upgrades of older databases, an unreadable archive file is kept aside (`.corrupt-*`) instead of overwritten, archive errors never stop the server or backups, restore rejects odd sale numbers, dates and expiry values. Built and committed locally (not pushed): zero-stock items in Reorder, Full screen button, typed quantity on Sell cart lines, bulk delete in Products, cost field with cost reports (cost visible to managers and owners only), redesigned 58 mm receipt with direct RawBT printing (printer not yet tested on the real device; RawBT showed a "WRC error" before). Queued, not started: in-app updater (owner only, safety backup first); see "Roadmap" below.

## Files

| File | What it holds |
|---|---|
| `install-lubuntu.sh` | One-time setup for the store laptop (Lubuntu/Ubuntu/Debian): boot service, `pos.local` name, port 80, firewall, desktop icon. `--uninstall` undoes it |
| `install-arch.sh` | Same setup for Arch, used for testing |
| `server.py` | HTTP entrypoint, transaction handlers, SQLite persistence, authorization decisions and scheduled jobs. |
| `poscore/` | Import-safe backend helpers for validation, sessions, atomic SQLite persistence, scoped state responses, archive reads/writes and audit queries/events. |
| `archives/` | One readable JSON file per day (`sales-YYYY-MM-DD.json`) for sales and audit rows older than 7 days. Not in git. Local only, like `data/` |
| `index.html` | Page structure only: header tabs, the four sections, popups |
| `style.css` | All styling, light and dark |
| `js/core.js` | Shared state `S`, helpers (`R`, `M`, `esc`, `tags`), `api()`, `load()`, `show(tab)`, sign-in screen and role checks (`can()`) |
| `js/sell.js` | Sell tab: `drawGrid`, cart (`drawLines`, `add`, `setQty` typed quantity on a cart line), checkout (`#pay`), `clampCart` |
| `js/products.js` | Products tab (managers and owners): add/edit form, quantity Add/Set, Cost box and Cost column, tick boxes with grouped bulk delete (`sel`); detailed history is in Inventory Logs |
| `js/logs.js` | Separate Inventory Logs, Sales Logs, User Activity, and System Logs pages; shared search/date/user/status filters, grouped operations, expandable details, and paginated history |
| `js/accounts.js` | Accounts tab (owner): add accounts, roles, reset password, disable |
| `js/settings.js` | Settings tab (owner): store name, receipt address/phone/tagline/footer with a live receipt preview and Test slip, stay-signed-in hours, backup days kept. Also `storeName()` and `applyBrand()` used for the header, order list and receipt, and the theme button in the header (every role, this device only: Automatic, Light, Dark; saved in the browser as `pos-theme`, applied early by a script in `index.html`) |
| `js/import.js` | CSV import (preview, apply; optional `cost` column), export products, download template. Parsing happens in the browser, rules in `r_import` |
| `js/reports.js` | Reports tab: today's totals, cost cards (`costStats`, `drawCost`), alerts, recent sales, backup show/restore |
| `js/reorder.js` | Reorder tab: reorder-now and getting-low lists, editable order quantities, print/PDF and CSV order list. Products with zero stock always appear. Client only, no server change |
| `js/receipt.js` | 58 mm receipt: `rcptBlocks` (one model), `rcptText`, `rcptBytes` (ESC/POS), `rcptUrl` (RawBT link), `rcptHtml` (on-screen slip), `rcptSend`, `rcptPopup`, `receipt()`, `rcptTestBlocks` |
| `js/receipts.js` | Receipts tab: sale list, view, password-protected void and change popups |
| `js/livesales.js` | Live Sales tab: today's sales as a newest-first feed (tap a row for items; filters by status and cashier; new sales highlight briefly) plus a "sold today by product" tally with search. Refreshed every 5 seconds from `/api/state`. Client only |
| `js/fullscreen.js` | Full-screen button in the header (hidden where the browser cannot) |
| `js/main.js` | Startup and the 15-second refresh on the Sell tab |

Scripts are plain (not modules) and share one global scope. Load order is in `index.html`.

## Data shapes (operational state in `S`; long-term audit history in SQLite `audit_events`)

- Product: `{id, n:name, p:price, s:stock, e:"YYYY-MM-DD" or "", m:reorder level, c?:cost per unit}`. `c` is optional: missing means cost unknown, 0 is a real zero. Managers and owners only: the server removes `c` from every reply sent to staff.
- Sale: `{no, d:date, t:time, l:[{id,n,q,p,c?}], tot, cash, by:name, uid, v?:{d,t,w,u}, h?:[{d,t,w,a,z,u}]}`. `v` means void, `h` is change history, `w` is the reason, `u` is who. Line `c` is the product's cost at the time of sale (only when it was known), so later cost changes never alter old sales or profit. Sales from older versions may also carry `sub`, `dc`, `dl` (a discount).
- Stock/audit log: `{d, t, n:product, k:what happened, a:count before, z:count after, u:who, i:product ID, w:reason}`. Older entries may lack `i` and `w`; normal sales now create a stock-decrease entry.
- Accounts (kept in the database, never sent with the state): `{id, username, name, role: staff|manager|owner, active, salt, hash}`. `S.today` is the laptop's date.

## Endpoints (POST mutations require JSON and `X-Requested-With: pos`; read-only GET routes return only their documented data)

Sessions use an HttpOnly cookie (`pos_session`, SameSite=Strict, 12 hours, `POS_SESSION_HOURS` to change). 401 means sign in again.

| Path | Who | Does |
|---|---|---|
| GET `/api/me` | anyone | `{setup, me}`; `setup` is true until the owner account exists |
| `/api/setup` | anyone, needs the setup code from the server log | Creates the first owner account |
| `/api/login`, `/api/logout` | anyone / signed in | Sign in and out. 5 wrong tries lock that device and username for a minute |
| GET `/api/state` | signed in | Current state and `me`; cost-change rows are omitted from staff state responses |
| GET `/api/sell-state` | signed in | Lightweight product catalog and stock with role-filtered costs and ETag/304 support |
| GET `/api/live-state` | signed in | Lightweight current-day sales and ETag/304 support; cost hidden from staff |
| GET `/api/receipt-date?date=YYYY-MM-DD` | signed in | Read-only receipt lookup from one day of hot data or daily archives; historical unit costs omitted; archived receipts are view/reprint only |
| GET `/api/report-sales?date=YYYY-MM-DD` | manager and owner | Selected day's transactions (including archived) plus last 90 calendar days' daily totals, void counts and historical gross profit; flags unreadable archives |
| GET `/api/logs?category=inventory\|sales\|activity\|system` | manager and owner | Searchable, paginated structured logs; operation details can be loaded by `operation_id`. Staff are denied server-side |
| `/api/sale` | staff and up | Server checks stock and expiry, prices from its own list, reduces stock |
| `/api/product`, `/api/delete`, `/api/delete-many`, `/api/stock`, `/api/import` | manager and up | Product and stock edits. `product` takes optional `c` (blank = unknown; a request without `c` keeps the cost); `import` takes an optional `cost` column (blank cell keeps the cost). `delete-many`: `ids` list (1 to 100000) plus `why`; all or nothing; one audit row per product; copy in `backups/pre-bulk-delete-*.db`. Import: mode `products`, `add` or `set`; `apply:false` previews, `apply:true` saves after a copy in `backups/pre-import-*.db`; all or nothing |
| `/api/void`, `/api/change` | manager and up, plus `password` of the signed-in user in the request | Void or amend a sale |
| `/api/restore` | owner, plus `password` | Restore a backup |
| `/api/users`, `/api/user` | owner | List, add, edit, disable accounts (always one active owner) |
| `/api/settings` | owner (re-enter password) | Save store name, receipt fields `rc_addr` (64), `rc_phone` (32), `rc_tag` (40), `rc_foot` (64 characters max; a request without them keeps the saved values), stay-signed-in hours (1 to 72), backup days kept (7 to 365). Stored in the `kv` table under `settings`, outside the sales data so a restore never changes them. Each change is written to the activity log as product "Settings". Sent to every client as `S.cfg` |
| `/api/mypassword` | signed in | Change own password (`old`, `new`) |

Errors come back as `{error}`.

## Rules already decided

- Roles: staff sell, view and reprint receipts, and see the Reorder list. Managers also change products and stock, import CSV, see Reports and Live Sales, use all four Log Center pages, and void or change sales (re-entering their own password). Owners also manage accounts, settings and restore backups. The server enforces log permissions; hiding tabs is only for tidiness. Staff activity is recorded without giving staff log-page access. Product cost history is restricted to manager/owner roles.
- Log Center pages are separate: Inventory Logs (product field changes, stock movements, CSV imports, deletions), Sales Logs (sales/voids/amendments), User Activity (logins, account/role/settings changes, backup restores), and System Logs (unhandled server errors, failed archive/backup jobs, persistence verification failures). Bulk actions share an operation ID and expand to paginated item-level details; sale-related inventory movements share the sale operation ID. CSV validation failures retain grouped row-level errors.
- Audit events are retained long-term with no age-based auto-deletion. Existing hot-state and daily-archive audit/sales history is imported idempotently on startup. Database/hourly backups include `audit_events`; manual JSON backups export log history too, and restoring a JSON backup merges retained log records instead of deleting current history. Cleanup, if ever added, must be explicitly authorized and itself logged.
- Every sale, stock change, price change, void and change records the signed-in person's name. Checkout stock reductions are recorded in the inventory accountability log. Product deletion and CSV imports require a reason; routine stock changes are logged with an automatic description.
- No discounts and no VAT: the price is the price. Old sales from earlier versions may still show a discount.
- Expired products can't be sold. Selling past stock is refused. Expiry date is optional per product; blank means never flagged or blocked.
- Cost (managers and owners only; staff never receive it): optional per product, blank = unknown. Each sale records the cost of every line at the time of sale. Reports show stock value at cost and at selling price (costed products only), estimated cost of the Reorder list, and gross profit today and over 30 days from lines with a recorded cost, plus how many products or lines have no cost. Cost changes are logged as "Cost changed".
- Sell tab cart: the number on each line is a box. Type a quantity and leave the box (or press Enter): more than the stock sets the maximum, 0 or blank removes the line, text or a negative number keeps the old quantity. The 15-second refresh skips while a quantity box is focused.
- Reorder tab: products with zero stock always appear in "Reorder now", even with no reorder level (default order quantity 1).
- Full screen button in the header toggles browser full screen; it hides itself where the browser cannot do it.
- Receipt (58 mm roll, 32 columns): plain ASCII only (peso sign prints as PHP, accents dropped) because cheap 58 mm printers cannot print them. Tablets (Android) send ESC/POS text straight to RawBT with an `intent:base64,...;scheme=rawbt;package=ru.a402d.rawbtprinter` link; computers and the Print (browser) button use the browser print dialog with `@page 58mm`. The sale is saved before printing, so a failed print never loses a sale; Reprint is in Receipts. No QR, barcode or logo is printed (printer support varies, and pictures are heavy over BLE). Settings > Test slip prints a 32-column ruler to check a printer. RawBT's virtual printer can show the slip without a real printer. Footer always ends with "Not an official receipt".
- Bulk delete (Products tab): tick products, give one reason, confirm. Search changes clear the selection, so hidden products can never be deleted unseen. Old receipts keep their items.
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
| 1 | In-app updater (owner only) | large | `server.py`, `js/settings.js`, `install-*.sh` | Safety backup first, run `tests/run.py` on the new code before switching, keep previous version for one-click rollback. Decide method first: git pull or uploaded zip. Never restart without owner confirming. |
| 2 | Remote access to the store laptop | infra | outside the repo | For updates and fixes. Prefer a private tunnel (no open router ports) plus the existing login. Decide tool before building. |
| 3 | Sections, printable count sheets, manager "check counts" screen, differences report | large | new `js/counts.js`, `server.py`, `index.html`, `style.css` | Counting stays manual; staff assigned to sections. Build in this order: sections on products, count sheets, check-counts screen, differences report. |
| 4 | Later | n/a | n/a | Write-offs, daily comparison with the official POS, batch numbers, HTTPS and a sturdier web server. |

Dependencies: 1 needs the test runner (done). 3 is easier after the `server.py` split is decided. Built already: zero-stock items in Reorder, Full screen button, typed quantity on Sell cart lines, bulk delete in Products, cost field and cost reports.

## Not built yet

Sections on products with responsible staff, printable count sheets, a manager "check counts" screen and a differences report (planned next). Later: write-offs, daily comparison with the official POS, batch numbers, HTTPS and a sturdier web server if it moves to the cloud.

- Sales forecast in Reports: client-side 7/30/90-day store-wide revenue and transaction estimates from non-voided sales, using weekday averages and a capped recent trend factor. Forecasts are estimates, not guarantees. Confidence is shown from days of history: under 28 days is "low" (about ±40% range), under 56 is "medium" (±25%), more is normal (±15%); the 90-day view adds 10 points. The likely range appears under the projected revenue. Reports "Low stock" only lists products with a reorder level above 0, same as the Reorder tab. No extra libraries or server endpoint are required.
- UI polish: subtle hover/focus states, responsive forecast cards/chart, quick SVG line animation, and reduced-motion support. Forecast data is calculated in the browser from the loaded sales state.
