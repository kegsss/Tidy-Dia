import datetime as dt
from pathlib import Path
from dia_organizer import config


def test_defaults(tmp_data_dir):
    cfg = config.load()
    assert cfg.scan_interval_minutes == 30
    assert cfg.protect_recent_days == 3
    assert cfg.triage_threshold_days == 5
    assert cfg.auto_close_idle_days == 14
    assert cfg.max_auto_closes_per_run == 20
    assert cfg.ui_port == 7321


def test_dry_run_active_when_date_in_future(tmp_data_dir):
    cfg = config.load()
    cfg.dry_run_until = dt.date.today() + dt.timedelta(days=2)
    assert cfg.dry_run_active() is True


def test_dry_run_inactive_when_date_past(tmp_data_dir):
    cfg = config.load()
    cfg.dry_run_until = dt.date.today() - dt.timedelta(days=1)
    assert cfg.dry_run_active() is False


def test_user_overrides(tmp_data_dir):
    (tmp_data_dir / "config.toml").write_text(
        '[general]\nscan_interval_minutes = 15\n'
        '[profiles."Keagan"]\njunk_domains = ["x.com"]\n'
    )
    cfg = config.load()
    assert cfg.scan_interval_minutes == 15
    assert cfg.profile("Keagan").junk_domains == ["x.com"]


def test_profile_defaults_when_unspecified(tmp_data_dir):
    cfg = config.load()
    p = cfg.profile("Anything")
    assert p.auto_close_disabled is False
    assert p.auto_close_idle_days == 14
    assert p.allowlist_domains == []
