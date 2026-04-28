from __future__ import annotations
import subprocess
from dataclasses import dataclass


class AppleScriptError(RuntimeError):
    pass


def run_script(script: str, timeout: float = 30.0) -> str:
    res = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if res.returncode != 0:
        raise AppleScriptError(res.stderr.strip() or f"osascript exit {res.returncode}")
    return res.stdout.strip("\n")


def dia_running() -> bool:
    out = run_script(
        'tell application "System Events" to '
        '(name of processes) contains "Dia"'
    )
    return out.strip().lower() == "true"


# Output format:
#   WIN|<window_id>|<name>|<tab_count>\n
#   TAB|<tab_id>|<title>|<url>|<pinned 0/1>|<focused 0/1>\n
# Titles/names are sanitized of newlines and pipes by AppleScript.
LIST_TABS_SCRIPT = r'''
on sanitize(s)
    set s to s as text
    set AppleScript's text item delimiters to "|"
    set parts to text items of s
    set AppleScript's text item delimiters to "/"
    set s to parts as text
    set AppleScript's text item delimiters to (ASCII character 10)
    set parts to text items of s
    set AppleScript's text item delimiters to " "
    set s to parts as text
    set AppleScript's text item delimiters to ""
    return s
end sanitize

set out to ""
tell application "Dia"
    repeat with w in windows
        set wid to id of w
        set wname to my sanitize(name of w)
        set tcount to count of tabs of w
        set out to out & "WIN|" & wid & "|" & wname & "|" & tcount & linefeed
        repeat with t in tabs of w
            set tid to id of t
            set ttitle to my sanitize(title of t)
            set turl to URL of t
            set tpin to "0"
            if isPinned of t then set tpin to "1"
            set tfoc to "0"
            if isFocused of t then set tfoc to "1"
            set out to out & "TAB|" & tid & "|" & ttitle & "|" & turl & "|" & tpin & "|" & tfoc & linefeed
        end repeat
    end repeat
end tell
return out
'''


@dataclass
class _ParsedWindow:
    window_id: str
    name: str
    tabs: list[dict]


def list_tabs() -> list[dict]:
    raw = run_script(LIST_TABS_SCRIPT, timeout=60.0)
    windows: list[dict] = []
    current: dict | None = None
    for line in raw.splitlines():
        if not line:
            continue
        parts = line.split("|")
        if parts[0] == "WIN":
            _, wid, name, _count = parts[:4]
            current = {"window_id": wid, "name": name, "tabs": []}
            windows.append(current)
        elif parts[0] == "TAB" and current is not None:
            _, tid, title, url, pin, foc = parts[:6]
            current["tabs"].append({
                "dia_tab_id": tid, "title": title, "url": url,
                "pinned": pin == "1", "focused": foc == "1",
            })
    return windows


def close_tab(window_id: str, tab_id: str) -> None:
    script = f'''
tell application "Dia"
    tell window id "{window_id}"
        close (first tab whose id is "{tab_id}")
    end tell
end tell
'''
    run_script(script)


def focus_tab(window_id: str, tab_id: str) -> None:
    script = f'''
tell application "Dia"
    tell window id "{window_id}"
        focus (first tab whose id is "{tab_id}")
    end tell
end tell
'''
    run_script(script)


def execute_js(window_id: str, tab_id: str, js: str) -> str:
    # JS payload is heredoc-quoted to survive embedding.
    safe = js.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "Dia"
    tell window id "{window_id}"
        execute (first tab whose id is "{tab_id}") javascript "{safe}"
    end tell
end tell
'''
    return run_script(script, timeout=15.0)


def make_tab(window_id: str, url: str) -> str:
    safe_url = url.replace('"', '\\"')
    script = f'''
tell application "Dia"
    tell window id "{window_id}"
        set newTab to make new tab with properties {{URL:"{safe_url}"}}
        return id of newTab
    end tell
end tell
'''
    return run_script(script).strip()
