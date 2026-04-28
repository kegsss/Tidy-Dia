from __future__ import annotations
import sqlite3
import time

from dia_organizer import applescript, archive, classifier, context_js, profiles, triage, snapshots
from dia_organizer.config import Config


def _maybe_extract_context(window_id: str, dia_tab_id: str) -> dict:
    try:
        raw = applescript.execute_js(window_id, dia_tab_id, context_js.PAYLOAD)
    except applescript.AppleScriptError:
        return {}
    pc = context_js.parse(raw)
    return {
        "meta_desc": pc.meta_desc, "og_title": pc.og_title, "og_desc": pc.og_desc,
        "h1": pc.h1, "selection": pc.selection, "scroll_pct": pc.scroll_pct,
        "text_sample": pc.text_sample, "referrer": pc.referrer,
    }


def run_scan(conn: sqlite3.Connection, cfg: Config, now: int | None = None) -> dict:
    n = now if now is not None else int(time.time())
    if not applescript.dia_running():
        return {"status": "dia-not-running"}

    win_to_profile = profiles.apply_overrides(profiles.resolve_live(), conn)
    windows = applescript.list_tabs()

    # 1. Upsert all live tabs (and capture context for new/changed URLs)
    seen_per_profile: dict[str, set[str]] = {}
    all_records: list[dict] = []
    for w in windows:
        profile = win_to_profile.get(w["window_id"], "<unknown>")
        seen_per_profile.setdefault(profile, set())
        for t in w["tabs"]:
            existing = conn.execute(
                "SELECT * FROM tabs WHERE dia_tab_id=? AND profile=? AND is_live=1",
                (t["dia_tab_id"], profile),
            ).fetchone()
            extra = {}
            if existing is None or existing["url"] != t["url"]:
                extra = _maybe_extract_context(w["window_id"], t["dia_tab_id"])
            rec = archive.upsert_live(conn, {
                **t, "profile": profile, "window_id": w["window_id"], "now": n, **extra,
            })
            seen_per_profile[profile].add(t["dia_tab_id"])
            row = conn.execute("SELECT * FROM tabs WHERE archive_id=?", (rec.archive_id,)).fetchone()
            row_dict = dict(row)
            # Preserve pre-scan last_seen so classifier idle math reflects user
            # activity (not the scanner heartbeat).
            if existing is not None:
                row_dict["last_seen"] = existing["last_seen"]
            all_records.append(row_dict)

    # 2. Mark externally-closed tabs (not seen this scan) per profile
    for profile, ids in seen_per_profile.items():
        archive.mark_external_closes(conn, profile, ids, n)

    # 2b. Hourly snapshot — only if no hourly snapshot in current hour bucket.
    hour_bucket = n // 3600
    last_hourly = conn.execute(
        "SELECT taken_at FROM snapshots WHERE retention='hourly' ORDER BY taken_at DESC LIMIT 1"
    ).fetchone()
    if last_hourly is None or (last_hourly["taken_at"] // 3600) < hour_bucket:
        snapshots.take(conn, windows, win_to_profile,
                        label="auto-hourly", trigger="hourly",
                        retention="hourly", now=n)

    # 2c. Nightly snapshot — once per UTC day at/after 02:00 local proxy: bucket by 86400.
    day_bucket = n // 86_400
    last_nightly = conn.execute(
        "SELECT taken_at FROM snapshots WHERE retention='nightly' ORDER BY taken_at DESC LIMIT 1"
    ).fetchone()
    if last_nightly is None or (last_nightly["taken_at"] // 86_400) < day_bucket:
        snapshots.take(conn, windows, win_to_profile,
                        label="auto-nightly", trigger="nightly",
                        retention="nightly", now=n)

    # 3. Classify all live records together
    decisions = []
    for r in all_records:
        d = classifier.classify(r, all_records, cfg, n)
        decisions.append((r, d))

    will_auto_close = [(r, d) for r, d in decisions if d.action == "AUTO_CLOSE"]
    triage_targets = [(r, d) for r, d in decisions if d.action == "TRIAGE"]

    dry = cfg.dry_run_active()

    # 4. Pre-scan snapshot if any closes will happen (and not dry-run).
    if will_auto_close and not dry:
        snapshots.take(conn, windows, win_to_profile,
                       label="pre-scan", trigger="pre-scan",
                       retention="manual", now=n)

    # 5. Apply auto-closes with caps.
    closed = []
    rate_limited = 0
    daily_counts: dict[str, int] = {}
    for r, d in will_auto_close:
        if dry:
            continue
        if len(closed) >= cfg.max_auto_closes_per_run:
            rate_limited += 1
            triage.enqueue(conn, r["archive_id"], n)
            continue
        today_count = conn.execute(
            "SELECT COUNT(*) FROM tabs WHERE profile=? AND closed_at >= ?",
            (r["profile"], n - 86_400),
        ).fetchone()[0]
        if today_count + daily_counts.get(r["profile"], 0) >= cfg.max_closes_per_day_per_profile:
            rate_limited += 1
            triage.enqueue(conn, r["archive_id"], n)
            continue
        try:
            archive.mark_closed(conn, r["archive_id"], d.reason, n)
            applescript.close_tab(r["window_id"], r["dia_tab_id"])
            daily_counts[r["profile"]] = daily_counts.get(r["profile"], 0) + 1
            closed.append(r["archive_id"])
        except Exception:
            pass

    # 6. Queue triage targets.
    for r, _d in triage_targets:
        triage.enqueue(conn, r["archive_id"], n)

    # 7. Snapshot retention housekeeping.
    snapshots.apply_retention(conn, cfg)

    return {
        "status": "ok",
        "dry_run": dry,
        "would_close_count": len(will_auto_close),
        "closed": len(closed),
        "triaged": len(triage_targets),
        "rate_limited": rate_limited,
    }


from dia_organizer import locking


def run_scan_cli_safe(conn, cfg, now=None):
    try:
        with locking.scan_lock():
            return run_scan(conn, cfg, now=now)
    except locking.LockHeld:
        return {"status": "lock-held"}
