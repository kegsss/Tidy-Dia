from __future__ import annotations
import sqlite3
import time


def enqueue(conn: sqlite3.Connection, archive_id: int, now: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO triage_queue(archive_id, queued_at) VALUES (?,?)",
        (archive_id, now),
    )
    conn.commit()


def resolve(conn: sqlite3.Connection, archive_id: int, resolution: str, now: int) -> None:
    conn.execute(
        "UPDATE triage_queue SET resolution=?, snooze_until=NULL WHERE archive_id=?",
        (resolution, archive_id),
    )
    conn.commit()


def snooze(conn: sqlite3.Connection, archive_id: int, until: int, now: int) -> None:
    conn.execute(
        "UPDATE triage_queue SET resolution='snooze', snooze_until=? WHERE archive_id=?",
        (until, archive_id),
    )
    conn.commit()


def pending(conn: sqlite3.Connection, now: int | None = None) -> list[sqlite3.Row]:
    n = now if now is not None else int(time.time())
    return list(conn.execute(
        """SELECT t.*, q.queued_at, q.snooze_until
           FROM triage_queue q
           JOIN tabs t ON t.archive_id = q.archive_id
           WHERE (q.resolution IS NULL)
              OR (q.resolution='snooze' AND q.snooze_until <= ?)
           ORDER BY q.queued_at""",
        (n,),
    ))
