"""Pure numeric and date helpers shared by POS operations and historical reports."""

import math
import re
from datetime import datetime, timedelta


def R(n):
    return math.floor(n * 100 + 0.5) / 100


def now():
    d = datetime.now()
    return d.strftime("%Y-%m-%d"), d.strftime("%I:%M %p")


def day_shift(day, n):
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def valid_day(d):
    return isinstance(d, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d))


def valid_expiry(e):
    """Blank (no expiry) or a real YYYY-MM-DD date. Anything else is refused so it can never block sales or reach the page as HTML."""
    if e == "":
        return True
    if not valid_day(e):
        return False
    try:
        datetime.strptime(e, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def max_sale_no(rows):
    """Highest whole-number sale no in rows; ignores rows with a missing or odd no."""
    return max((x["no"] for x in rows if isinstance(x, dict) and isinstance(x.get("no"), int)
                and not isinstance(x.get("no"), bool)), default=0)


MAX_NUM = 100_000_000  # largest price, cash amount, quantity or stock level the server accepts


def good_num(v, hi=MAX_NUM, whole=False):
    """True only for a real number from 0 to hi: not a bool, not NaN or Infinity (those fail the range test).
    whole=True also demands an int. Use this for every number a client sends."""
    if isinstance(v, bool) or not isinstance(v, int if whole else (int, float)):
        return False
    return 0 <= v <= hi and math.isfinite(v)


def _no_constant(name):  # json.loads hook: refuse NaN, Infinity and -Infinity
    raise ValueError("Not a valid number: " + name)


def _finite_float(s):  # json.loads hook: refuse numbers that overflow to Infinity, such as 1e999
    x = float(s)
    if not math.isfinite(x):
        raise ValueError("Number out of range")
    return x
