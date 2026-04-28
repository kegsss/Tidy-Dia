from unittest.mock import patch
from dia_organizer import db, scanner, archive
from dia_organizer.config import Config, ProfileConfig


def _windows():
    return [{
        "window_id": "WIN1", "name": "Win",
        "tabs": [
            {"dia_tab_id": "t1", "title": "GitHub repo",
             "url": "https://github.com/a/b", "pinned": False, "focused": True},
            {"dia_tab_id": "t2", "title": "Old YT",
             "url": "https://youtube.com/watch?v=x", "pinned": False, "focused": False},
        ],
    }]


def _cfg():
    c = Config()
    c.profiles["Keagan"] = ProfileConfig(
        name="Keagan", junk_domains=["youtube.com"],
        allowlist_domains=["github.com"], auto_close_idle_days=14,
    )
    return c


def test_scan_dry_run_does_not_close(tmp_data_dir):
    conn = db.open_db()
    cfg = _cfg()
    import datetime as dt
    cfg.dry_run_until = dt.date.today() + dt.timedelta(days=1)
    closes = []
    with patch("dia_organizer.applescript.dia_running", return_value=True), \
         patch("dia_organizer.applescript.list_tabs", return_value=_windows()), \
         patch("dia_organizer.applescript.execute_js", return_value=""), \
         patch("dia_organizer.applescript.close_tab", side_effect=lambda *a: closes.append(a)), \
         patch("dia_organizer.profiles.resolve_live", return_value={"WIN1": "Keagan"}):
        result = scanner.run_scan(conn, cfg, now=10**9)
    assert closes == []
    assert result["dry_run"] is True
    assert result["would_close_count"] >= 0


def test_scan_inserts_live_tabs(tmp_data_dir):
    conn = db.open_db()
    cfg = _cfg()
    with patch("dia_organizer.applescript.dia_running", return_value=True), \
         patch("dia_organizer.applescript.list_tabs", return_value=_windows()), \
         patch("dia_organizer.applescript.execute_js", return_value=""), \
         patch("dia_organizer.applescript.close_tab"), \
         patch("dia_organizer.profiles.resolve_live", return_value={"WIN1": "Keagan"}):
        scanner.run_scan(conn, cfg, now=10**9)
    live = archive.live_tabs(conn, "Keagan")
    assert {r["dia_tab_id"] for r in live} >= {"t1"}  # t2 may have been closed if not dry-run


def test_scan_aborts_when_dia_not_running(tmp_data_dir):
    conn = db.open_db()
    cfg = _cfg()
    with patch("dia_organizer.applescript.dia_running", return_value=False):
        result = scanner.run_scan(conn, cfg, now=10**9)
    assert result["status"] == "dia-not-running"


def test_scan_respects_max_auto_closes(tmp_data_dir):
    conn = db.open_db()
    cfg = _cfg()
    cfg.max_auto_closes_per_run = 1
    big = [{
        "window_id": "WIN1", "name": "Win",
        "tabs": [
            {"dia_tab_id": f"t{i}", "title": f"yt {i}",
             "url": f"https://youtube.com/watch?v={i}",
             "pinned": False, "focused": False}
            for i in range(3)
        ],
    }]
    closes = []
    with patch("dia_organizer.applescript.dia_running", return_value=True), \
         patch("dia_organizer.applescript.list_tabs", return_value=big), \
         patch("dia_organizer.applescript.execute_js", return_value=""), \
         patch("dia_organizer.applescript.close_tab", side_effect=lambda *a: closes.append(a)), \
         patch("dia_organizer.profiles.resolve_live", return_value={"WIN1": "Keagan"}):
        scanner.run_scan(conn, cfg, now=0)
        result = scanner.run_scan(conn, cfg, now=30 * 86_400)
    assert len(closes) <= 1
    assert result["rate_limited"] >= 2
