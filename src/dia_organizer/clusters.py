# src/dia_organizer/clusters.py
from __future__ import annotations
import datetime as dt
from collections import defaultdict

WINDOW_SECONDS = 2 * 60 * 60


def group(tabs: list[dict]) -> list[dict]:
    """Cluster tabs by (profile, domain) within a 2h sliding window of first_seen.
    Returns list of groups: {label, profile, reason, tabs:[...]}.
    Singletons returned as one-tab groups too."""
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for t in sorted(tabs, key=lambda x: (x["profile"], x["domain"], x["first_seen"])):
        if not t["domain"]:
            by_key[(t["profile"], "_blank_", t["first_seen"])] = [t]
            continue
        slot = t["first_seen"] // WINDOW_SECONDS
        # try to attach to existing window if the prior bucket is within 2h
        prev_key = (t["profile"], t["domain"], slot - 1)
        cur_key = (t["profile"], t["domain"], slot)
        if prev_key in by_key and (t["first_seen"] - by_key[prev_key][-1]["first_seen"]) <= WINDOW_SECONDS:
            by_key[prev_key].append(t)
        else:
            by_key[cur_key].append(t)

    groups: list[dict] = []
    for (profile, domain, _slot), members in by_key.items():
        first = min(m["first_seen"] for m in members)
        date_str = dt.datetime.fromtimestamp(first).strftime("%b %d")
        if len(members) == 1 or domain == "_blank_":
            for m in members:
                groups.append({
                    "label": m["title"][:60] or m.get("url", ""),
                    "profile": profile, "reason": "singleton", "tabs": [m],
                })
        else:
            groups.append({
                "label": f"{domain} research, {date_str} ({len(members)} tabs)",
                "profile": profile, "reason": "domain", "tabs": members,
            })
    return groups
