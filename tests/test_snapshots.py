from dia_organizer import db, snapshots
from dia_organizer.config import Config


def _windows():
    return [{
        "window_id": "w1", "name": "WinA",
        "tabs": [
            {"dia_tab_id": "t1", "title": "Tab1", "url": "https://a", "pinned": False, "focused": False},
            {"dia_tab_id": "t2", "title": "Tab2", "url": "https://b", "pinned": True,  "focused": False},
        ],
    }]


def test_take_snapshot_records_tabs(tmp_data_dir):
    conn = db.open_db()
    sid = snapshots.take(conn, _windows(), {"w1": "Keagan"},
                         label="manual", trigger="manual",
                         retention="manual", now=100)
    rows = list(conn.execute("SELECT * FROM snapshot_tabs WHERE snapshot_id=?", (sid,)))
    assert len(rows) == 2
    s = conn.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (sid,)).fetchone()
    assert s["tab_count"] == 2
    assert s["profile_count"] == 1


def test_retention_caps_hourly(tmp_data_dir):
    conn = db.open_db()
    cfg = Config()
    cfg.hourly_keep = 2
    for i in range(5):
        snapshots.take(conn, _windows(), {"w1": "Keagan"},
                       label="auto-hourly", trigger="hourly",
                       retention="hourly", now=100 + i)
    snapshots.apply_retention(conn, cfg)
    cnt = conn.execute(
        "SELECT COUNT(*) FROM snapshots WHERE retention='hourly'"
    ).fetchone()[0]
    assert cnt == 2


def test_retention_keeps_manual(tmp_data_dir):
    conn = db.open_db()
    cfg = Config()
    cfg.hourly_keep = 1
    for i in range(3):
        snapshots.take(conn, _windows(), {"w1": "Keagan"},
                       label=f"m{i}", trigger="manual",
                       retention="manual", now=100 + i)
    snapshots.apply_retention(conn, cfg)
    cnt = conn.execute(
        "SELECT COUNT(*) FROM snapshots WHERE retention='manual'"
    ).fetchone()[0]
    assert cnt == 3


def test_diff_against_current(tmp_data_dir):
    conn = db.open_db()
    sid = snapshots.take(conn, _windows(), {"w1": "Keagan"},
                         label="x", trigger="manual",
                         retention="manual", now=100)
    current = [{
        "window_id": "w1", "name": "WinA",
        "tabs": [
            {"dia_tab_id": "t1", "title": "Tab1", "url": "https://a", "pinned": False, "focused": False},
            {"dia_tab_id": "t9", "title": "New",  "url": "https://c", "pinned": False, "focused": False},
        ],
    }]
    diff = snapshots.diff(conn, sid, current, {"w1": "Keagan"})
    assert {x["dia_tab_id"] for x in diff["missing_from_current"]} == {"t2"}
    assert {x["dia_tab_id"] for x in diff["new_since_snapshot"]} == {"t9"}
