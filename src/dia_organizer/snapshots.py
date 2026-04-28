from __future__ import annotations
import sqlite3
from typing import Iterable

from dia_organizer.config import Config


def take(conn: sqlite3.Connection, windows: list[dict],
          window_to_profile: dict[str, str],
          label: str, trigger: str, retention: str, now: int) -> int:
    profiles = set()
    tab_count = 0
    cur = conn.execute(
        "INSERT INTO snapshots(taken_at,label,trigger,profile_count,tab_count,retention) "
        "VALUES (?,?,?,?,?,?)",
        (now, label, trigger, 0, 0, retention),
    )
    sid = cur.lastrowid
    for w in windows:
        profile = window_to_profile.get(w["window_id"], "<unknown>")
        profiles.add(profile)
        for pos, t in enumerate(w["tabs"]):
            conn.execute(
                "INSERT OR REPLACE INTO snapshot_tabs("
                "snapshot_id,profile,window_id,dia_tab_id,position,pinned,title,url"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (sid, profile, w["window_id"], t["dia_tab_id"], pos,
                 1 if t.get("pinned") else 0, t["title"], t["url"]),
            )
            tab_count += 1
    conn.execute(
        "UPDATE snapshots SET profile_count=?, tab_count=? WHERE snapshot_id=?",
        (len(profiles), tab_count, sid),
    )
    conn.commit()
    return sid


def _trim(conn: sqlite3.Connection, retention: str, keep: int) -> None:
    rows = list(conn.execute(
        "SELECT snapshot_id FROM snapshots WHERE retention=? "
        "ORDER BY taken_at DESC", (retention,),
    ))
    for r in rows[keep:]:
        conn.execute("DELETE FROM snapshot_tabs WHERE snapshot_id=?", (r["snapshot_id"],))
        conn.execute("DELETE FROM snapshots WHERE snapshot_id=?", (r["snapshot_id"],))


def apply_retention(conn: sqlite3.Connection, cfg: Config) -> None:
    _trim(conn, "hourly", cfg.hourly_keep)
    _trim(conn, "daily",  cfg.daily_keep)
    _trim(conn, "weekly", cfg.weekly_keep)
    # manual: keep all
    # nightly: prune by age
    cutoff_rows = list(conn.execute(
        "SELECT snapshot_id FROM snapshots "
        "WHERE retention='nightly' AND taken_at < (strftime('%s','now') - ? * 86400)",
        (cfg.nightly_keep_days,),
    ))
    for r in cutoff_rows:
        conn.execute("DELETE FROM snapshot_tabs WHERE snapshot_id=?", (r["snapshot_id"],))
        conn.execute("DELETE FROM snapshots WHERE snapshot_id=?", (r["snapshot_id"],))
    conn.commit()


def list_all(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM snapshots ORDER BY taken_at DESC"))


def get_tabs(conn: sqlite3.Connection, snapshot_id: int) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM snapshot_tabs WHERE snapshot_id=? ORDER BY profile, position",
        (snapshot_id,),
    ))


def diff(conn: sqlite3.Connection, snapshot_id: int,
         current_windows: list[dict], window_to_profile: dict[str, str]) -> dict:
    snap_rows = get_tabs(conn, snapshot_id)
    snap_set = {(r["profile"], r["dia_tab_id"]): dict(r) for r in snap_rows}
    cur_set: dict[tuple, dict] = {}
    for w in current_windows:
        profile = window_to_profile.get(w["window_id"], "<unknown>")
        for t in w["tabs"]:
            cur_set[(profile, t["dia_tab_id"])] = {
                "profile": profile, "window_id": w["window_id"],
                "dia_tab_id": t["dia_tab_id"], "title": t["title"], "url": t["url"],
            }
    missing = [v for k, v in snap_set.items() if k not in cur_set]
    added   = [v for k, v in cur_set.items()  if k not in snap_set]
    return {"missing_from_current": missing, "new_since_snapshot": added}


def delete(conn: sqlite3.Connection, snapshot_id: int) -> None:
    conn.execute("DELETE FROM snapshot_tabs WHERE snapshot_id=?", (snapshot_id,))
    conn.execute("DELETE FROM snapshots WHERE snapshot_id=?", (snapshot_id,))
    conn.commit()
