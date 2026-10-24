# ROSPOS code maintenance guide

## Priorities

1. Preserve pharmacy transaction behavior and existing permissions.
2. Keep code understandable: descriptive names, small functions, and clear separation of UI rendering, event handling, and server requests.
3. Do not compress production JavaScript or CSS into single-line blocks. Aim for 100-120 characters per line; longer template strings are acceptable where splitting would harm clarity.
4. Keep database changes separate from UI refactors. Never commit databases, archives, or runtime backups.
5. Change one feature at a time. Run the regression suite before and after each change.

## File organization

- `js/core.js`: shared state, permissions, API requests, and navigation.
- `js/sell.js`: product search, cart, and checkout.
- `js/products.js`, `js/purchases.js`, `js/reorder.js`: inventory workflows.
- `js/reports.js`, `js/logs.js`, `js/receipts.js`: read-only history and reporting UI.
- `style.css`: shared tokens first, component styles next, responsive overrides last.
- `server.py`: HTTP endpoints, authorization decisions, locking, transaction mutations, and database persistence.
- `poscore/storage.py`: WAL database initialization, key/value access, and atomic state, audit and payment-key commits.
- `poscore/values.py`: numeric and date validation, pure helpers.
- `poscore/auth_sessions.py`: password hashing and session cookie lifecycle.
- `poscore/state_views.py`: role-filtered full, Sell, and Live Sales response models.
- `poscore/archive_store.py`, `poscore/history.py`: archive file I/O, receipt retrieval, and historical sales reports.
- `poscore/audit_events.py`, `poscore/audit_queries.py`: legacy audit formatting and read-only audit queries.
- New service modules must not import `server` or open a production DB at import time.
  Keep server wrappers for compatibility with existing tests and authorization checks.

## Validation

```bash
python tests/check.py --fast --table
python tests/check.py --deep --table
python tests/check.py --selftest
node --check js/core.js
git diff --check
```

Before changing checkout, purchase costing, inventory updates, or backups, add targeted tests. Run UI checks for staff and owner, light and dark themes, and narrow and wide screens. Avoid blanket formatting of the entire repository in a feature commit: it makes review and collaboration difficult.
