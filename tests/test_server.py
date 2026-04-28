from dia_organizer import db, archive, snapshots, triage, server


def _seed(conn):
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "Stale article", "url": "https://example.com/article",
        "pinned": False, "focused": False, "now": 1,
        "meta_desc": "an article", "h1": "Heading",
    })
    triage.enqueue(conn, rec.archive_id, now=1)
    return rec.archive_id


def test_index_redirects_to_triage(tmp_data_dir):
    db.open_db().close()
    app = server.create_app()
    client = app.test_client()
    res = client.get("/")
    assert res.status_code in (302, 308)
    assert "/triage" in res.headers["Location"]


def test_triage_page_lists_pending(tmp_data_dir):
    conn = db.open_db()
    _seed(conn)
    conn.close()
    app = server.create_app()
    client = app.test_client()
    res = client.get("/triage")
    assert res.status_code == 200
    assert b"Stale article" in res.data
    assert b"Keep" in res.data and b"Close" in res.data


def test_triage_keep_action(tmp_data_dir):
    conn = db.open_db()
    aid = _seed(conn)
    conn.close()
    app = server.create_app()
    client = app.test_client()
    res = client.post(f"/triage/{aid}/keep")
    assert res.status_code in (200, 302)
    conn = db.open_db()
    row = conn.execute("SELECT resolution FROM triage_queue WHERE archive_id=?", (aid,)).fetchone()
    assert row["resolution"] == "keep"


def test_triage_close_action_archives_and_calls_applescript(tmp_data_dir, monkeypatch):
    conn = db.open_db()
    aid = _seed(conn)
    conn.close()
    calls = []
    monkeypatch.setattr("dia_organizer.applescript.close_tab",
                         lambda w, t: calls.append((w, t)))
    app = server.create_app()
    client = app.test_client()
    res = client.post(f"/triage/{aid}/close")
    assert res.status_code in (200, 302)
    assert calls == [("w1", "t1")]
    conn = db.open_db()
    row = conn.execute(
        "SELECT is_live, close_reason FROM tabs WHERE archive_id=?", (aid,)
    ).fetchone()
    assert row["is_live"] == 0
    assert row["close_reason"] == "triage:close"


def test_archive_search_returns_matches(tmp_data_dir):
    conn = db.open_db()
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "Tailwind dark mode", "url": "https://x/y",
        "pinned": False, "focused": False, "now": 1,
        "meta_desc": "css", "h1": "Dark",
    })
    archive.mark_closed(conn, rec.archive_id, "manual", 2)
    conn.close()
    app = server.create_app()
    client = app.test_client()
    res = client.get("/archive?q=tailwind")
    assert res.status_code == 200
    assert b"Tailwind dark mode" in res.data


def test_archive_reopen_calls_applescript(tmp_data_dir, monkeypatch):
    conn = db.open_db()
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "X", "url": "https://x/y", "pinned": False,
        "focused": False, "now": 1,
    })
    archive.mark_closed(conn, rec.archive_id, "manual", 2)
    conn.close()
    seen = []
    monkeypatch.setattr("dia_organizer.applescript.make_tab",
                         lambda w, u: seen.append((w, u)) or "newid")
    app = server.create_app()
    client = app.test_client()
    res = client.post(f"/archive/{rec.archive_id}/reopen")
    assert res.status_code in (200, 302)
    assert seen == [("w1", "https://x/y")]


def test_history_lists_snapshots(tmp_data_dir):
    conn = db.open_db()
    snapshots.take(conn, [{"window_id": "w1", "name": "n",
                            "tabs": [{"dia_tab_id": "t1", "title": "T",
                                       "url": "https://a", "pinned": False,
                                       "focused": False}]}],
                    {"w1": "Keagan"}, label="lab", trigger="manual",
                    retention="manual", now=10)
    conn.close()
    app = server.create_app()
    client = app.test_client()
    res = client.get("/history")
    assert res.status_code == 200
    assert b"lab" in res.data


def test_history_rollback_dry_run(tmp_data_dir, monkeypatch):
    conn = db.open_db()
    sid = snapshots.take(conn, [{"window_id": "w1", "name": "n",
                                   "tabs": [{"dia_tab_id": "t1", "title": "T",
                                              "url": "https://a", "pinned": False,
                                              "focused": False}]}],
                          {"w1": "Keagan"}, label="lab", trigger="manual",
                          retention="manual", now=10)
    conn.close()
    monkeypatch.setattr("dia_organizer.applescript.list_tabs",
                         lambda: [{"window_id": "w1", "name": "n", "tabs": []}])
    monkeypatch.setattr("dia_organizer.profiles.resolve_live",
                         lambda: {"w1": "Keagan"})
    app = server.create_app()
    client = app.test_client()
    res = client.get(f"/history/{sid}")
    assert res.status_code == 200
    assert b"would reopen" in res.data.lower() or b"to_open" in res.data.lower()
