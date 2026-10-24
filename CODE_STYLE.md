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
- `server.py`: API, validation, persistence, and auditing. Extract modules only with regression coverage.

## Validation

```bash
python tests/check.py --fast --table
python tests/check.py --deep --table
python tests/check.py --selftest
node --check js/core.js
git diff --check
```

Before changing checkout, purchase costing, inventory updates, or backups, add targeted tests. Run UI checks for staff and owner, light and dark themes, and narrow and wide screens. Avoid blanket formatting of the entire repository in a feature commit: it makes review and collaboration difficult.
