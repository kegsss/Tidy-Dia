import time
from unittest.mock import patch
from click.testing import CliRunner
from dia_organizer import cli, db, archive


def test_scan_command_invokes_run_scan(tmp_data_dir):
    runner = CliRunner()
    with patch("dia_organizer.cli.scanner.run_scan",
               return_value={"status": "ok", "dry_run": False, "closed": 2,
                              "triaged": 1, "would_close_count": 2,
                              "rate_limited": 0}) as p:
        res = runner.invoke(cli.main, ["scan"])
    assert res.exit_code == 0
    assert p.called
    assert "closed=2" in res.output


def test_search_uses_archive(tmp_data_dir):
    runner = CliRunner()
    conn = db.open_db()
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "Tailwind dark mode", "url": "https://x/y",
        "pinned": False, "focused": False, "now": 1,
    })
    archive.mark_closed(conn, rec.archive_id, "manual", now=2)
    conn.close()
    res = runner.invoke(cli.main, ["search", "tailwind"])
    assert res.exit_code == 0
    assert "Tailwind dark mode" in res.output


def test_undo_reopens_recent(tmp_data_dir):
    runner = CliRunner()
    conn = db.open_db()
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://x/y", "pinned": False,
        "focused": False, "now": 1,
    })
    archive.mark_closed(conn, rec.archive_id, "auto:idle", now=int(time.time()))
    conn.close()
    with patch("dia_organizer.applescript.make_tab", return_value="newid") as p:
        res = runner.invoke(cli.main, ["undo"])
    assert res.exit_code == 0
    assert p.called
