# NOTES: ROSPOS

Internal stock and sales counting tool. Python server on the store laptop, screens in the browser. For setup see README.md.

## Files

| File | What it holds |
|---|---|
| `install-lubuntu.sh` | One-time setup for the store laptop (Lubuntu/Ubuntu/Debian): boot service, `pos.local` name, port 80, firewall, desktop icon. `--uninstall` undoes it |
| `install-arch.sh` | Same setup for Arch, used for testing |
| `server.py` | All data and rules. SQLite in `data/pos.db`, hourly backups, PIN checks, one function per operation (`r_sale`, `r_void`, ...) |
| `index.html` | Page structure only: header tabs, the four sections, popups |
| `style.css` | All styling, light and dark |
| `js/core.js` | Shared state `S`, helpers (`R`, `M`, `esc`, `tags`), `api()`, `load()`, `show(tab)`, sign-in screen and role checks (`can()`) |
| `js/sell.js` | Sell tab: `drawGrid`, cart (`drawLines`, `add`), checkout (`#pay`), `receipt()` popup, `clampCart` |
| `js/products.js` | Products tab (managers and owners): add/edit form, quantity Add/Set, stock log with who made each change |
| `js/accounts.js` | Accounts tab (owner): add accounts, roles, reset password, disable |
| `js/import.js` | CSV import (preview, apply), export products, download template. Parsing happens in the browser, rules in `r_import` |
| `js/reports.js` | Reports tab: today's totals, alerts, recent sales, backup show/restore |
| `js/reorder.js` | Reorder tab: reorder-now and getting-low lists, editable order quantities, print/PDF and CSV order list. Client only, no server change |
| `js/receipts.js` | Receipts tab: sale list, view, PIN-protected void and change popups |
| `js/main.js` | Startup and the 15-second refresh on the Sell tab |

Scripts are plain (not modules) and share one global scope. Load order is in `index.html`.

## Data shapes (all in `S` on the client, one JSON blob on the server)

- Product: `{id, n:name, p:price, s:stock, e:"YYYY-MM-DD" or "", m:reorder level}`
- Sale: `{no, d:date, t:time, l:[{id,n,q,p}], tot, cash, by:name, uid, v?:{d,t,w,u}, h?:[{d,t,w,a,z,u}]}`. `v` means void, `h` is change history, `w` is the reason, `u` is who. Sales from older versions may also carry `sub`, `dc`, `dl` (a discount).
- Stock log: `{d, t, n:product, k:what happened, a:count before, z:count after, u:who}`
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
| `/api/mypassword` | signed in | Change own password (`old`, `new`) |

Errors come back as `{error}`.

## Rules already decided

- Roles: staff sell, view and reprint receipts, and see the Reorder list. Managers also change products and stock, import CSV, see Reports, and void or change sales (re-entering their own password). Owners also manage accounts and restore backups. The server enforces this; hiding tabs is only for tidiness.
- Every sale, stock change, price change, void and change records the signed-in person's name.
- No discounts and no VAT: the price is the price. Old sales from earlier versions may still show a discount.
- Expired products can't be sold. Selling past stock is refused. Expiry date is optional per product; blank means never flagged or blocked.
- Sales are never deleted. Void returns stock and keeps the sale marked void. Change edits quantities and cash.
- Reorder tab: "now" is stock at or below the reorder level, "getting low" is up to 25% above it (margin kept in the browser). Suggested order quantity brings stock to double the reorder level. Products with no reorder level are ignored. Order list layout: #, Product Name, Quantity, Price (blank), A to Z.
- Counting is manual: staff report counts to the owner or manager, who check the system.
- 90 days is the "expiring soon" window.

## How to add a feature

1. Find the screen: edit its one `js/*.js` file (and `index.html` / `style.css` if needed).
2. If it changes data, add or edit one `r_*` function and a line in `ROUTES` in `server.py`. Validate everything on the server.
3. Update this file's data shapes, endpoints, or rules if they changed.

## Not built yet

Sections on products with responsible staff, printable count sheets, a manager "check counts" screen and a differences report (planned next). Later: write-offs, daily comparison with the official POS, batch numbers, HTTPS and a sturdier web server if it moves to the cloud.
