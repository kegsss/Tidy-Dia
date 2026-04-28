from unittest.mock import patch
from dia_organizer import notifications


def test_notify_runs_osascript():
    with patch("subprocess.run") as p:
        p.return_value.returncode = 0
        notifications.notify("hello", "world")
        cmd = p.call_args[0][0]
        assert cmd[0] == "osascript"
        assert "display notification" in cmd[2]
