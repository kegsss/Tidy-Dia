import time
from dia_organizer import db, archive


def test_upsert_live_inserts_new(tmp_data_dir):
    conn = db.open_db()
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example/x", "pinned": False,
        "focused": False, "now": 100,
    })
    assert rec.archive_id is not None
    assert rec.first_seen == 100
    assert rec.last_seen == 100


def test_upsert_live_updates_existing(tmp_data_dir):
    conn = db.open_db()
    archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example/x", "pinned": False,
        "focused": False, "now": 100,
    })
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example/x", "pinned": False,
        "focused": True, "now": 200,
    })
    assert rec.first_seen == 100
    assert rec.last_seen == 200
    assert rec.last_focused == 200


def test_close_tab_marks_archive(tmp_data_dir):
    conn = db.open_db()
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example/x", "pinned": False,
        "focused": False, "now": 100,
    })
    archive.mark_closed(conn, rec.archive_id, reason="auto:idle", now=300)
    row = conn.execute(
        "SELECT is_live, closed_at, close_reason FROM tabs WHERE archive_id=?",
        (rec.archive_id,),
    ).fetchone()
    assert row["is_live"] == 0
    assert row["closed_at"] == 300
    assert row["close_reason"] == "auto:idle"


def test_search_fts(tmp_data_dir):
    conn = db.open_db()
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "Tailwind dark mode tutorial",
        "url": "https://example.com/tw",
        "pinned": False, "focused": False, "now": 100,
        "meta_desc": "css framework", "h1": "Dark mode",
    })
    archive.mark_closed(conn, rec.archive_id, reason="auto:idle", now=200)
    hits = archive.search(conn, "tailwind")
    assert len(hits) == 1
    assert hits[0]["title"].startswith("Tailwind")


def test_recent_closes_within_undo_window(tmp_data_dir):
    conn = db.open_db()
    now = int(time.time())
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example", "pinned": False,
        "focused": False, "now": now - 10,
    })
    archive.mark_closed(conn, rec.archive_id, reason="auto:idle", now=now - 5)
    recent = archive.closed_within(conn, seconds=60, now=now)
    assert len(recent) == 1
    none = archive.closed_within(conn, seconds=1, now=now)
    assert none == []


def test_mark_external_close(tmp_data_dir):
    conn = db.open_db()
    archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example", "pinned": False,
        "focused": False, "now": 100,
    })
    archive.mark_external_closes(conn, profile="Keagan",
                                  seen_dia_ids=set(), now=300)
    row = conn.execute(
        "SELECT is_live, close_reason FROM tabs WHERE dia_tab_id='t1'"
    ).fetchone()
    assert row["is_live"] == 0
    assert row["close_reason"] == "external"
