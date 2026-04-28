# tests/test_smoke.py
from unittest.mock import patch
from click.testing import CliRunner

from dia_organizer import archive, cli, db, snapshots, triage


def _windows_v1():
    return [{
        "window_id": "WIN1", "name": "n",
        "tabs": [
            {"dia_tab_id": "t1", "title": "GH", "url": "https://github.com/x/y",
             "pinned": False, "focused": True},
            {"dia_tab_id": "t2", "title": "OldArticle", "url": "https://example.com/a",
             "pinned": False, "focused": False},
        ],
    }]


def test_full_flow(tmp_data_dir, monkeypatch):
    runner = CliRunner()

    # Mock all AppleScript boundary calls.
    monkeypatch.setattr("dia_organizer.applescript.dia_running", lambda: True)
    monkeypatch.setattr("dia_organizer.applescript.list_tabs", _windows_v1)
    monkeypatch.setattr("dia_organizer.applescript.execute_js", lambda *a, **k: "")
    monkeypatch.setattr("dia_organizer.applescript.close_tab", lambda *a, **k: None)
    monkeypatch.setattr("dia_organizer.applescript.make_tab", lambda *a, **k: "newid")
    monkeypatch.setattr("dia_organizer.profiles.resolve_live",
                         lambda: {"WIN1": "Keagan"})

    # 1. First scan: dry-run by default.
    res = runner.invoke(cli.main, ["scan", "--dry-run"])
    assert res.exit_code == 0

    # 2. Search archive (should be empty for a fresh URL).
    res = runner.invoke(cli.main, ["search", "github"])
    assert res.exit_code == 0

    # 3. Take a manual snapshot.
    res = runner.invoke(cli.main, ["snapshot", "--label", "smoke"])
    assert res.exit_code == 0

    # 4. List snapshots — at least one with label smoke.
    res = runner.invoke(cli.main, ["snapshots"])
    assert res.exit_code == 0
    assert "smoke" in res.output

    # 5. Rollback dry-run for snapshot 1.
    res = runner.invoke(cli.main, ["rollback", "1", "--dry-run"])
    assert res.exit_code == 0
