"""Daily archive I/O, independent of database and runtime state."""

import json
import os
from datetime import datetime


def merge_day_archive(archive_dir, day, sales, logs):
    """Write or merge one day's sales/audit into archives/sales-YYYY-MM-DD.json (readable JSON)."""
    os.makedirs(archive_dir, exist_ok=True)
    path = os.path.join(archive_dir, "sales-%s.json" % day)
    data = {"format": "ROSPOS-day-archive", "version": 1, "date": day, "s": [], "g": []}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                prev = json.load(fh)
            if not isinstance(prev, dict):
                raise ValueError("not an archive file")
            data["s"] = list(prev.get("s") or [])
            data["g"] = list(prev.get("g") or [])
        except (OSError, ValueError, TypeError):
            # never overwrite an unreadable archive: keep it aside, then start a fresh file
            os.replace(path, path + ".corrupt-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    by_no = {s["no"]: s for s in data["s"] if isinstance(s, dict) and "no" in s}
    for s in sales:
        by_no[s["no"]] = s
    data["s"] = sorted(by_no.values(), key=lambda x: x["no"])
    seen = {(g.get("d"), g.get("t"), g.get("n"), g.get("k"), g.get("a"), g.get("z"), g.get("u"), g.get("i"), g.get("w"))
            for g in data["g"] if isinstance(g, dict)}
    for g in logs:
        key = (g.get("d"), g.get("t"), g.get("n"), g.get("k"), g.get("a"), g.get("z"), g.get("u"), g.get("i"), g.get("w"))
        if key not in seen:
            data["g"].append(g)
            seen.add(key)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


