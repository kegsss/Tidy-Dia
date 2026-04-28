from unittest.mock import patch, MagicMock
from dia_organizer import applescript


def _run(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_run_script_returns_stdout():
    with patch("subprocess.run", return_value=_run(stdout="hello\n")) as p:
        out = applescript.run_script('tell app "Dia" to return name')
        assert out == "hello"
        args, kwargs = p.call_args
        assert args[0][0] == "osascript"


def test_run_script_raises_on_failure():
    with patch("subprocess.run", return_value=_run(returncode=1, stderr="boom")):
        try:
            applescript.run_script("garbage")
        except applescript.AppleScriptError as e:
            assert "boom" in str(e)
        else:
            assert False, "expected AppleScriptError"


def test_dia_running_true():
    with patch("subprocess.run", return_value=_run(stdout="true\n")):
        assert applescript.dia_running() is True


def test_dia_running_false():
    with patch("subprocess.run", return_value=_run(stdout="false\n")):
        assert applescript.dia_running() is False


def test_list_tabs_parses_payload():
    payload = (
        "WIN|3C6D14AB|Some Title|2\n"
        "TAB|t1|Tab One|https://a.example|0|1\n"
        "TAB|t2|Tab Two|https://b.example|1|0\n"
    )
    with patch("subprocess.run", return_value=_run(stdout=payload)):
        result = applescript.list_tabs()
    assert len(result) == 1
    win = result[0]
    assert win["window_id"] == "3C6D14AB"
    assert win["name"] == "Some Title"
    assert len(win["tabs"]) == 2
    assert win["tabs"][0] == {
        "dia_tab_id": "t1", "title": "Tab One",
        "url": "https://a.example", "pinned": False, "focused": True,
    }
    assert win["tabs"][1]["pinned"] is True


def test_close_tab_invokes_osascript():
    with patch("subprocess.run", return_value=_run()) as p:
        applescript.close_tab("3C6D14AB", "t1")
        script = p.call_args[0][0][2]
        assert "3C6D14AB" in script and "t1" in script
        assert "close" in script


def test_execute_js_returns_stdout():
    with patch("subprocess.run", return_value=_run(stdout='{"ok":1}\n')):
        out = applescript.execute_js("3C", "t1", "1+1")
        assert out == '{"ok":1}'


def test_focus_tab_invokes_osascript():
    with patch("subprocess.run", return_value=_run()) as p:
        applescript.focus_tab("3C", "t1")
        assert "focus" in p.call_args[0][0][2]


def test_make_tab_uses_url():
    with patch("subprocess.run", return_value=_run(stdout="newid\n")):
        new_id = applescript.make_tab("3C", "https://example.com")
        assert new_id == "newid"
