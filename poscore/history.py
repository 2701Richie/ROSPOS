"""Archived receipt readers and daily reports, independent of active sessions/DB."""

import json
import math
import os

from .values import R, day_shift


def no_cost(d):
    return {k: v for k, v in d.items() if k != "c"}


def read_receipt_day(day, archive_dir, live_sales, include_cost=False, hot_sales=None):
    """Read a single day's receipts from archive and hot state, without mutating either."""
    sales = {}
    unavailable = False
    path = os.path.join(archive_dir, "sales-%s.json" % day)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                archived = json.load(fh)
            if (not isinstance(archived, dict) or archived.get("format") != "ROSPOS-day-archive"
                    or archived.get("date") != day or not isinstance(archived.get("s"), list)):
                raise ValueError("Invalid daily archive")
            for sale in archived["s"]:
                if (isinstance(sale, dict) and sale.get("d") == day
                        and isinstance(sale.get("no"), int)):
                    sales[sale["no"]] = sale
        except (OSError, ValueError, TypeError):
            unavailable = True
    # In-memory versions win when archived copies have become outdated.
    for sale in (live_sales if hot_sales is None else hot_sales):
        if (isinstance(sale, dict) and sale.get("d") == day
                and isinstance(sale.get("no"), int)):
            sales[sale["no"]] = sale
    result = sorted(sales.values(), key=lambda s: s["no"])
    if include_cost:
        return result, unavailable
    return [dict(s, l=[no_cost(line) for line in s.get("l", [])
                           if isinstance(line, dict)]) for s in result], unavailable


def build_report_sales_history(selected, archive_dir, live_sales, today):
    """Read the 90-day report and a selected day without loading archives into live state."""
    start = day_shift(today, -89)
    requested_days = {day_shift(today, -i) for i in range(90)}
    requested_days.add(selected)
    grouped = {}
    unavailable = []
    hot_by_day = {day: [] for day in requested_days}
    for sale in live_sales:
        if isinstance(sale, dict) and sale.get("d") in hot_by_day:
            hot_by_day[sale["d"]].append(sale)
    for day in requested_days:
        grouped[day], unreadable = read_receipt_day(
            day, archive_dir, live_sales, include_cost=True, hot_sales=hot_by_day[day])
        if unreadable:
            unavailable.append(day)

    summaries = []
    for day in sorted(requested_days, reverse=True):
        if not start <= day <= today:
            continue
        sales = grouped[day]
        if not sales:
            continue
        active = [s for s in sales if not s.get("v")]
        profit = revenue_costed = 0.0
        lines = missing = 0
        for sale in active:
            for line in sale.get("l", []):
                if not isinstance(line, dict):
                    continue
                cost = line.get("c")
                if cost is None:
                    missing += 1
                    continue
                try:
                    qty, price, unit_cost = float(line["q"]), float(line["p"]), float(cost)
                    if not all(map(math.isfinite, (qty, price, unit_cost))):
                        raise ValueError("Non-finite sale line")
                except (KeyError, ValueError, TypeError, OverflowError):
                    missing += 1
                    continue
                profit += (price - unit_cost) * qty
                revenue_costed += price * qty
                lines += 1
        summaries.append({"date": day, "count": len(active),
                          "voided": len(sales) - len(active),
                          "total": R(sum(float(s.get("tot") or 0) for s in active)),
                          "profit": R(profit), "revenue_costed": R(revenue_costed),
                          "lines": lines, "missing": missing})
    selected_sales = [dict(s, l=[no_cost(line) for line in s.get("l", [])
                                     if isinstance(line, dict)]) for s in grouped[selected]]
    return {"date": selected, "today": today, "sales": selected_sales,
            "days": summaries, "unavailable": sorted(unavailable)}


