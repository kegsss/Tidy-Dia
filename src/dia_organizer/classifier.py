from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Iterable

from dia_organizer.config import Config

DAY = 86_400
HOUR = 3_600

WHITELIST_RE = re.compile(
    r"^(https?://(localhost|127\.|10\.|192\.168\.|172\.)|chrome://(?!newtab)|about:(?!blank)|file://|dia://(?!newtab))"
)
SEARCH_RE = re.compile(r"^https?://(www\.)?(google|bing|duckduckgo)\.[^/]+/search")
TXN_RE = re.compile(
    r"(amazon\.[^/]+/gp/buy/.*thankyou|stripe\.com/.*success|checkout/success)",
    re.IGNORECASE,
)
BLANK_URLS = {"", "about:blank", "dia://newtab", "chrome://newtab/"}


@dataclass
class Decision:
    action: str       # PROTECT | AUTO_CLOSE | TRIAGE | KEEP
    reason: str = ""  # close_reason for archive when AUTO_CLOSE / TRIAGE


def _idle_seconds(tab: dict, now: int) -> int:
    last = tab["last_focused"] or tab["last_seen"]
    return max(0, now - last)


def _age_seconds(tab: dict, now: int) -> int:
    return max(0, now - tab["first_seen"])


def classify(tab: dict, all_tabs: Iterable[dict], cfg: Config, now: int) -> Decision:
    profile = cfg.profile(tab["profile"])
    url = tab["url"] or ""
    domain = tab.get("domain") or ""

    # Hard whitelist — never close.
    if WHITELIST_RE.match(url):
        return Decision("PROTECT")

    # Pin always protects.
    if tab.get("pinned"):
        return Decision("PROTECT")

    # Allowlist domain protects.
    if any(domain == d or domain.endswith("." + d) for d in profile.allowlist_domains):
        return Decision("PROTECT")

    # Dedup-close exception — fires even in protect window.
    duplicates = [
        o for o in all_tabs
        if o["url"] == url and o["profile"] == tab["profile"]
        and o["archive_id"] != tab["archive_id"]
    ]
    if duplicates:
        newest = max([tab] + duplicates, key=lambda x: x["first_seen"])
        if tab["archive_id"] != newest["archive_id"]:
            return Decision("AUTO_CLOSE", "auto:dup")

    # Profile may forbid auto-close beyond dedup; route remaining to TRIAGE.
    auto_close_allowed = not profile.auto_close_disabled

    # Blank tabs auto-close regardless of recency (no value to preserve).
    if auto_close_allowed and url in BLANK_URLS:
        return Decision("AUTO_CLOSE", "auto:blank")

    # PROTECT — recent or selected.
    if _age_seconds(tab, now) < cfg.protect_recent_days * DAY:
        return Decision("PROTECT")
    if tab.get("selection"):
        return Decision("PROTECT")

    # AUTO_CLOSE rules.
    if auto_close_allowed:
        if TXN_RE.search(url):
            return Decision("AUTO_CLOSE", "auto:txn-done")
        if SEARCH_RE.match(url) and _idle_seconds(tab, now) > HOUR:
            return Decision("AUTO_CLOSE", "auto:search-stale")
        if any(domain == d or domain.endswith("." + d) for d in profile.junk_domains):
            if _idle_seconds(tab, now) > 2 * HOUR:
                return Decision("AUTO_CLOSE", "auto:junk")
        if _idle_seconds(tab, now) > profile.auto_close_idle_days * DAY:
            return Decision("AUTO_CLOSE", "auto:idle")

    # TRIAGE rules.
    if _idle_seconds(tab, now) > cfg.triage_threshold_days * DAY:
        return Decision("TRIAGE", "triage:idle")

    return Decision("KEEP")
