from dia_organizer import db, archive, triage


def _seed_tab(conn, profile="Keagan", url="https://a"):
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": profile, "window_id": "w1",
        "title": "T", "url": url, "pinned": False, "focused": False, "now": 100,
    })
    return rec.archive_id


def test_enqueue_idempotent(tmp_data_dir):
    conn = db.open_db()
    aid = _seed_tab(conn)
    triage.enqueue(conn, aid, now=100)
    triage.enqueue(conn, aid, now=200)  # second call must not duplicate
    rows = list(conn.execute("SELECT * FROM triage_queue WHERE archive_id=?", (aid,)))
    assert len(rows) == 1


def test_pending_excludes_resolved(tmp_data_dir):
    conn = db.open_db()
    aid = _seed_tab(conn)
    triage.enqueue(conn, aid, now=100)
    assert len(triage.pending(conn)) == 1
    triage.resolve(conn, aid, "keep", now=200)
    assert triage.pending(conn) == []


def test_snooze_hides_until_time(tmp_data_dir):
    conn = db.open_db()
    aid = _seed_tab(conn)
    triage.enqueue(conn, aid, now=100)
    triage.snooze(conn, aid, until=500, now=200)
    assert triage.pending(conn, now=400) == []
    assert len(triage.pending(conn, now=600)) == 1
