from dia_organizer import scheduling


def test_plist_contains_required_keys(tmp_path):
    plist = scheduling.render_plist(
        binary="/usr/local/bin/dia-organizer",
        interval_seconds=1800,
        log_path=str(tmp_path / "out.log"),
        err_path=str(tmp_path / "err.log"),
    )
    assert "<key>Label</key>" in plist
    assert "<string>com.keagan.dia-organizer</string>" in plist
    assert "<integer>1800</integer>" in plist
    assert "/usr/local/bin/dia-organizer" in plist


def test_plist_path_default():
    p = scheduling.plist_path()
    assert str(p).endswith("LaunchAgents/com.keagan.dia-organizer.plist")
