from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass
class TabRecord:
    archive_id: int
    dia_tab_id: str
    profile: str
    window_id: str
    title: str
    url: str
    first_seen: int
    last_seen: int
    last_focused: Optional[int]
    is_live: bool


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def upsert_live(conn: sqlite3.Connection, t: dict) -> TabRecord:
    """t keys: dia_tab_id, profile, window_id, title, url, pinned, focused, now,
    + optional context fields (meta_desc, og_title, og_desc, h1, selection,
      scroll_pct, text_sample, referrer)."""
    now = t["now"]
    row = conn.execute(
        "SELECT * FROM tabs WHERE dia_tab_id=? AND profile=? AND is_live=1",
        (t["dia_tab_id"], t["profile"]),
    ).fetchone()
    last_focused = now if t.get("focused") else (row["last_focused"] if row else None)
    domain = _domain(t["url"])
    if row is None:
        cur = conn.execute(
            """INSERT INTO tabs(
                dia_tab_id, profile, window_id, title, url, domain,
                first_seen, last_seen, last_focused, pinned,
                meta_desc, og_title, og_desc, h1, selection, scroll_pct, text_sample, referrer,
                is_live
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (
                t["dia_tab_id"], t["profile"], t["window_id"], t["title"], t["url"], domain,
                now, now, last_focused, 1 if t.get("pinned") else 0,
                t.get("meta_desc"), t.get("og_title"), t.get("og_desc"),
                t.get("h1"), t.get("selection"), t.get("scroll_pct"),
                t.get("text_sample"), t.get("referrer"),
            ),
        )
        archive_id = cur.lastrowid
        first_seen = now
    else:
        archive_id = row["archive_id"]
        first_seen = row["first_seen"]
        conn.execute(
            """UPDATE tabs SET
                window_id=?, title=?, url=?, domain=?, last_seen=?, last_focused=?,
                pinned=?, meta_desc=COALESCE(?, meta_desc),
                og_title=COALESCE(?, og_title), og_desc=COALESCE(?, og_desc),
                h1=COALESCE(?, h1), selection=COALESCE(?, selection),
                scroll_pct=COALESCE(?, scroll_pct),
                text_sample=COALESCE(?, text_sample), referrer=COALESCE(?, referrer)
               WHERE archive_id=?""",
            (
                t["window_id"], t["title"], t["url"], domain, now, last_focused,
                1 if t.get("pinned") else 0,
                t.get("meta_desc"), t.get("og_title"), t.get("og_desc"),
                t.get("h1"), t.get("selection"), t.get("scroll_pct"),
                t.get("text_sample"), t.get("referrer"),
                archive_id,
            ),
        )
    conn.commit()
    return TabRecord(
        archive_id=archive_id, dia_tab_id=t["dia_tab_id"], profile=t["profile"],
        window_id=t["window_id"], title=t["title"], url=t["url"],
        first_seen=first_seen, last_seen=now, last_focused=last_focused, is_live=True,
    )


def mark_closed(conn: sqlite3.Connection, archive_id: int, reason: str, now: int) -> None:
    conn.execute(
        "UPDATE tabs SET is_live=0, closed_at=?, close_reason=? WHERE archive_id=?",
        (now, reason, archive_id),
    )
    conn.commit()


def mark_external_closes(conn: sqlite3.Connection, profile: str,
                          seen_dia_ids: set[str], now: int) -> int:
    cur = conn.execute(
        "SELECT archive_id, dia_tab_id FROM tabs WHERE profile=? AND is_live=1",
        (profile,),
    )
    closed = 0
    for row in cur.fetchall():
        if row["dia_tab_id"] not in seen_dia_ids:
            mark_closed(conn, row["archive_id"], "external", now)
            closed += 1
    return closed


def live_tabs(conn: sqlite3.Connection, profile: Optional[str] = None) -> list[sqlite3.Row]:
    if profile:
        return list(conn.execute(
            "SELECT * FROM tabs WHERE is_live=1 AND profile=?", (profile,)
        ))
    return list(conn.execute("SELECT * FROM tabs WHERE is_live=1"))


def search(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    return list(conn.execute(
        """SELECT t.* FROM tabs t
           JOIN tabs_fts f ON f.rowid = t.archive_id
           WHERE tabs_fts MATCH ?
           ORDER BY t.last_seen DESC
           LIMIT ?""",
        (query, limit),
    ))


def closed_within(conn: sqlite3.Connection, seconds: int, now: int) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM tabs WHERE is_live=0 AND closed_at >= ? ORDER BY closed_at DESC",
        (now - seconds,),
    ))


def reopen_record(conn: sqlite3.Connection, archive_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tabs WHERE archive_id=?", (archive_id,)
    ).fetchone()
