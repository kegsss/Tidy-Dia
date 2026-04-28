# Dia Organizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS Python utility that scans tabs across all Dia browser profiles, auto-closes obvious junk, queues ambiguous tabs for review in a clickable local web UI, archives every closed tab with rich page context for later search, and supports full snapshot/rollback of live tab state.

**Architecture:** A Python package (`dia_organizer`) with a Click CLI entrypoint and a Flask localhost UI. The scanner uses `osascript` to drive Dia via its AppleScript dictionary (read tabs, run JS in tab to extract context, close tabs, reopen tabs). Profile names resolve from Dia's on-disk JSON (`Local State` + `StorableProfileContainers.json`). All state lives in a single SQLite DB with FTS5 for archive search. A `launchd` agent runs `dia-organizer scan` every 30 minutes. Safety is enforced with dry-run defaults, hard caps, archive-before-close transactions, an undo window, and pre-destructive snapshots.

**Tech Stack:** Python 3.12+, Click (CLI), Flask (UI), SQLite + FTS5, `osascript` (AppleScript bridge via subprocess), `tomllib` (config), `pytest` (tests), `launchd` (scheduling). No external services.

**Spec:** `docs/superpowers/specs/2026-04-28-dia-organizer-design.md`

---

## File Structure

```
Dia_Organizer/
├── pyproject.toml
├── README.md
├── src/
│   └── dia_organizer/
│       ├── __init__.py
│       ├── cli.py                # Click entrypoint, command dispatch
│       ├── config.py             # TOML config loader + defaults
│       ├── paths.py              # Resolves ~/.dia-organizer, Dia user data, etc.
│       ├── db.py                 # SQLite connection, schema migrations
│       ├── locking.py            # Exclusive file lock for scan
│       ├── logging_setup.py      # Logging config
│       ├── applescript.py        # osascript subprocess primitives
│       ├── profiles.py           # Resolve window_id → profile name
│       ├── context_js.py         # JS payload + extraction
│       ├── scanner.py            # Tab enumeration + scan orchestration
│       ├── classifier.py         # PROTECT/AUTO-CLOSE/TRIAGE rules
│       ├── clusters.py           # Cluster grouping for triage
│       ├── archive.py            # tabs / tabs_fts / triage_queue ops
│       ├── snapshots.py          # snapshot create/retain/rollback
│       ├── notifications.py      # macOS user notifications
│       ├── scheduling.py         # launchd plist generator
│       ├── server.py             # Flask app factory + routes
│       ├── templates/
│       │   ├── base.html
│       │   ├── triage.html
│       │   ├── archive.html
│       │   └── history.html
│       └── static/
│           ├── style.css
│           └── app.js
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_db.py
    ├── test_locking.py
    ├── test_applescript.py
    ├── test_profiles.py
    ├── test_context_js.py
    ├── test_scanner.py
    ├── test_classifier.py
    ├── test_clusters.py
    ├── test_archive.py
    ├── test_snapshots.py
    ├── test_scheduling.py
    ├── test_server.py
    └── fixtures/
        ├── local_state.json
        └── storable_profile_containers.json
```

Boundaries: each module owns one concern; tests sit in parallel files. Tests use a temporary SQLite DB and mock `osascript` calls — no real Dia interaction in unit tests.

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/dia_organizer/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "dia-organizer"
version = "0.1.0"
description = "Tame Dia browser tab sprawl across profiles"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1",
    "flask>=3.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=5.0"]

[project.scripts]
dia-organizer = "dia_organizer.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra -q"
```

- [ ] **Step 2: Write `src/dia_organizer/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Write `tests/__init__.py` (empty) and `tests/conftest.py`**

```python
# tests/conftest.py
import os
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def tmp_data_dir(monkeypatch, tmp_path):
    """Redirect ~/.dia-organizer to a temp dir for the duration of a test."""
    monkeypatch.setenv("DIA_ORGANIZER_HOME", str(tmp_path))
    return tmp_path
```

- [ ] **Step 4: Write `.gitignore`**

```
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
.coverage
htmlcov/
dist/
build/
~/.dia-organizer/
```

- [ ] **Step 5: Create venv, install dev deps, verify import**

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -c "import dia_organizer; print(dia_organizer.__version__)"
.venv/bin/pytest --collect-only
```

Expected: prints `0.1.0`; pytest reports 0 tests collected with no errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/dia_organizer/__init__.py tests/__init__.py tests/conftest.py .gitignore
git commit -m "chore: scaffold dia-organizer package"
```

---

## Task 2: Paths Module

**Files:**
- Create: `src/dia_organizer/paths.py`
- Create: `tests/test_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_paths.py
from pathlib import Path
from dia_organizer import paths


def test_data_home_uses_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("DIA_ORGANIZER_HOME", str(tmp_path))
    assert paths.data_home() == tmp_path


def test_data_home_default(monkeypatch):
    monkeypatch.delenv("DIA_ORGANIZER_HOME", raising=False)
    assert paths.data_home() == Path.home() / ".dia-organizer"


def test_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("DIA_ORGANIZER_HOME", str(tmp_path))
    assert paths.db_path() == tmp_path / "db.sqlite"


def test_config_path(monkeypatch, tmp_path):
    monkeypatch.setenv("DIA_ORGANIZER_HOME", str(tmp_path))
    assert paths.config_path() == tmp_path / "config.toml"


def test_dia_user_data_default():
    expected = Path.home() / "Library" / "Application Support" / "Dia"
    assert paths.dia_app_support() == expected
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_paths.py -v`
Expected: FAIL — module `dia_organizer.paths` does not exist.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/paths.py
import os
from pathlib import Path


def data_home() -> Path:
    env = os.environ.get("DIA_ORGANIZER_HOME")
    return Path(env) if env else Path.home() / ".dia-organizer"


def db_path() -> Path:
    return data_home() / "db.sqlite"


def config_path() -> Path:
    return data_home() / "config.toml"


def lock_path() -> Path:
    return data_home() / "scan.lock"


def log_path() -> Path:
    return data_home() / "scan.log"


def err_path() -> Path:
    return data_home() / "scan.err"


def dia_app_support() -> Path:
    return Path.home() / "Library" / "Application Support" / "Dia"


def dia_local_state() -> Path:
    return dia_app_support() / "User Data" / "Local State"


def dia_storable_profiles() -> Path:
    return dia_app_support() / "StorableProfileContainers.json"


def ensure_data_home() -> Path:
    home = data_home()
    home.mkdir(parents=True, exist_ok=True)
    return home
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_paths.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/paths.py tests/test_paths.py
git commit -m "feat(paths): central path resolution"
```

---

## Task 3: Config Loader

**Files:**
- Create: `src/dia_organizer/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
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
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/config.py
from __future__ import annotations
import datetime as dt
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dia_organizer import paths


@dataclass
class ProfileConfig:
    name: str
    auto_close_disabled: bool = False
    junk_domains: list[str] = field(default_factory=list)
    allowlist_domains: list[str] = field(default_factory=list)
    auto_close_idle_days: int = 14


@dataclass
class Config:
    scan_interval_minutes: int = 30
    soft_tab_limit_per_profile: int = 60
    triage_threshold_days: int = 5
    auto_close_idle_days: int = 14
    protect_recent_days: int = 3
    max_auto_closes_per_run: int = 20
    max_closes_per_day_per_profile: int = 50
    dry_run_until: Optional[dt.date] = None
    undo_window_minutes: int = 60
    ui_port: int = 7321
    notify_on_triage_queue_growth: bool = True
    hourly_keep: int = 24
    daily_keep: int = 14
    weekly_keep: int = 12
    nightly_keep_days: int = 90
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)

    def dry_run_active(self) -> bool:
        return self.dry_run_until is not None and self.dry_run_until > dt.date.today()

    def profile(self, name: str) -> ProfileConfig:
        if name in self.profiles:
            return self.profiles[name]
        return ProfileConfig(name=name, auto_close_idle_days=self.auto_close_idle_days)


def load(path: Optional[Path] = None) -> Config:
    cfg = Config()
    p = path or paths.config_path()
    if not p.exists():
        return cfg
    data = tomllib.loads(p.read_text())
    g = data.get("general", {})
    for key, val in g.items():
        if hasattr(cfg, key):
            setattr(cfg, key, val)
    s = data.get("safety", {})
    if "dry_run_until" in s:
        v = s["dry_run_until"]
        cfg.dry_run_until = v if isinstance(v, dt.date) else dt.date.fromisoformat(v)
    if "undo_window_minutes" in s:
        cfg.undo_window_minutes = s["undo_window_minutes"]
    ui = data.get("ui", {})
    cfg.ui_port = ui.get("port", cfg.ui_port)
    cfg.notify_on_triage_queue_growth = ui.get(
        "notify_on_triage_queue_growth", cfg.notify_on_triage_queue_growth
    )
    snap = data.get("snapshots", {})
    for key in ("hourly_keep", "daily_keep", "weekly_keep", "nightly_keep_days"):
        if key in snap:
            setattr(cfg, key, snap[key])
    for name, pdata in data.get("profiles", {}).items():
        cfg.profiles[name] = ProfileConfig(
            name=name,
            auto_close_disabled=pdata.get("auto_close_disabled", False),
            junk_domains=list(pdata.get("junk_domains", [])),
            allowlist_domains=list(pdata.get("allowlist_domains", [])),
            auto_close_idle_days=pdata.get("auto_close_idle_days", cfg.auto_close_idle_days),
        )
    return cfg
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/config.py tests/test_config.py
git commit -m "feat(config): TOML config loader with profile overrides"
```

---

## Task 4: Database & Schema

**Files:**
- Create: `src/dia_organizer/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
import sqlite3
from dia_organizer import db, paths


def test_open_creates_schema(tmp_data_dir):
    conn = db.open_db()
    cur = conn.cursor()
    tables = {row[0] for row in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert {"tabs", "clusters", "triage_queue", "snapshots",
            "snapshot_tabs", "config_window_profiles"} <= tables


def test_fts_table_exists(tmp_data_dir):
    conn = db.open_db()
    rows = list(conn.execute(
        "SELECT name FROM sqlite_master WHERE name='tabs_fts'"
    ))
    assert rows


def test_fts_indexes_inserted_rows(tmp_data_dir):
    conn = db.open_db()
    conn.execute(
        "INSERT INTO tabs (dia_tab_id, profile, title, url, meta_desc, "
        "first_seen, last_seen, is_live) VALUES "
        "('t1','Keagan','Tailwind dark mode','https://x/y','dark mode css',1,1,0)"
    )
    conn.commit()
    rows = list(conn.execute(
        "SELECT title FROM tabs_fts WHERE tabs_fts MATCH 'tailwind'"
    ))
    assert rows and rows[0][0] == "Tailwind dark mode"


def test_double_open_idempotent(tmp_data_dir):
    db.open_db().close()
    db.open_db().close()  # must not raise
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/db.py
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional

from dia_organizer import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS tabs (
  archive_id     INTEGER PRIMARY KEY,
  dia_tab_id     TEXT,
  profile        TEXT,
  window_id      TEXT,
  title          TEXT,
  url            TEXT,
  domain         TEXT,
  first_seen     INTEGER,
  last_seen      INTEGER,
  last_focused   INTEGER,
  closed_at      INTEGER,
  close_reason   TEXT,
  cluster_id     INTEGER,
  meta_desc      TEXT,
  og_title       TEXT,
  og_desc        TEXT,
  h1             TEXT,
  selection      TEXT,
  scroll_pct     INTEGER,
  text_sample    TEXT,
  referrer       TEXT,
  notes          TEXT,
  is_live        INTEGER NOT NULL DEFAULT 1,
  pinned         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tabs_live ON tabs(is_live);
CREATE INDEX IF NOT EXISTS idx_tabs_profile ON tabs(profile);
CREATE INDEX IF NOT EXISTS idx_tabs_dia_id ON tabs(dia_tab_id);

CREATE TABLE IF NOT EXISTS clusters (
  cluster_id     INTEGER PRIMARY KEY,
  label          TEXT,
  profile        TEXT,
  created_at     INTEGER,
  reason         TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS tabs_fts USING fts5(
  title, url, meta_desc, og_title, og_desc, h1, selection, text_sample, notes,
  content='tabs', content_rowid='archive_id'
);

CREATE TRIGGER IF NOT EXISTS tabs_ai AFTER INSERT ON tabs BEGIN
  INSERT INTO tabs_fts(rowid, title, url, meta_desc, og_title, og_desc, h1, selection, text_sample, notes)
  VALUES (new.archive_id, new.title, new.url, new.meta_desc, new.og_title, new.og_desc, new.h1, new.selection, new.text_sample, new.notes);
END;
CREATE TRIGGER IF NOT EXISTS tabs_ad AFTER DELETE ON tabs BEGIN
  INSERT INTO tabs_fts(tabs_fts, rowid, title, url, meta_desc, og_title, og_desc, h1, selection, text_sample, notes)
  VALUES ('delete', old.archive_id, old.title, old.url, old.meta_desc, old.og_title, old.og_desc, old.h1, old.selection, old.text_sample, old.notes);
END;
CREATE TRIGGER IF NOT EXISTS tabs_au AFTER UPDATE ON tabs BEGIN
  INSERT INTO tabs_fts(tabs_fts, rowid, title, url, meta_desc, og_title, og_desc, h1, selection, text_sample, notes)
  VALUES ('delete', old.archive_id, old.title, old.url, old.meta_desc, old.og_title, old.og_desc, old.h1, old.selection, old.text_sample, old.notes);
  INSERT INTO tabs_fts(rowid, title, url, meta_desc, og_title, og_desc, h1, selection, text_sample, notes)
  VALUES (new.archive_id, new.title, new.url, new.meta_desc, new.og_title, new.og_desc, new.h1, new.selection, new.text_sample, new.notes);
END;

CREATE TABLE IF NOT EXISTS triage_queue (
  archive_id     INTEGER PRIMARY KEY REFERENCES tabs(archive_id),
  queued_at      INTEGER,
  resolution     TEXT,
  snooze_until   INTEGER
);

CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_id    INTEGER PRIMARY KEY,
  taken_at       INTEGER,
  label          TEXT,
  trigger        TEXT,
  profile_count  INTEGER,
  tab_count      INTEGER,
  retention      TEXT
);

CREATE TABLE IF NOT EXISTS snapshot_tabs (
  snapshot_id    INTEGER REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
  profile        TEXT,
  window_id      TEXT,
  dia_tab_id     TEXT,
  position       INTEGER,
  pinned         INTEGER,
  title          TEXT,
  url            TEXT,
  PRIMARY KEY (snapshot_id, profile, dia_tab_id)
);
CREATE INDEX IF NOT EXISTS idx_snap_tabs_profile ON snapshot_tabs(snapshot_id, profile);

CREATE TABLE IF NOT EXISTS config_window_profiles (
  window_id      TEXT PRIMARY KEY,
  profile        TEXT,
  bound_at       INTEGER
);
"""


def open_db(path: Optional[Path] = None) -> sqlite3.Connection:
    p = path or paths.db_path()
    paths.ensure_data_home()
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/db.py tests/test_db.py
git commit -m "feat(db): SQLite schema with FTS5 and snapshots"
```

---

## Task 5: File Locking

**Files:**
- Create: `src/dia_organizer/locking.py`
- Create: `tests/test_locking.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_locking.py
import pytest
from dia_organizer import locking


def test_acquire_then_release(tmp_data_dir):
    with locking.scan_lock() as got:
        assert got is True


def test_second_acquire_blocks(tmp_data_dir):
    with locking.scan_lock():
        with pytest.raises(locking.LockHeld):
            with locking.scan_lock():
                pass
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_locking.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/locking.py
from __future__ import annotations
import contextlib
import fcntl
from dia_organizer import paths


class LockHeld(RuntimeError):
    pass


@contextlib.contextmanager
def scan_lock():
    paths.ensure_data_home()
    p = paths.lock_path()
    f = open(p, "w")
    try:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise LockHeld(f"scan lock held at {p}") from e
        yield True
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_locking.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/locking.py tests/test_locking.py
git commit -m "feat(locking): exclusive scan lock"
```

---

## Task 6: AppleScript Bridge Primitives

**Files:**
- Create: `src/dia_organizer/applescript.py`
- Create: `tests/test_applescript.py`

This module shells out to `osascript`. Tests mock `subprocess.run`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_applescript.py
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
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_applescript.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/applescript.py
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_applescript.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/applescript.py tests/test_applescript.py
git commit -m "feat(applescript): osascript bridge for Dia"
```

---

## Task 7: Profile Resolver

**Files:**
- Create: `tests/fixtures/local_state.json`
- Create: `tests/fixtures/storable_profile_containers.json`
- Create: `src/dia_organizer/profiles.py`
- Create: `tests/test_profiles.py`

- [ ] **Step 1: Write fixture files**

```json
// tests/fixtures/local_state.json
{
  "profile": {
    "info_cache": {
      "Default":   {"name": "Keagan"},
      "Profile 1": {"name": "Together User"},
      "Profile 7": {"name": "Demo Together User"},
      "Profile 10":{"name": "test"}
    }
  }
}
```

```json
// tests/fixtures/storable_profile_containers.json
{
  "version": 3,
  "containers": [
    {"id": {"profileID": "Default",
             "container": {"window": {"_0": "AAAA-WIN-DEFAULT"}}}, "tabs": []},
    {"id": {"profileID": "Profile 1",
             "container": {"window": {"_0": "BBBB-WIN-TOGETHER"}}}, "tabs": []},
    {"id": {"profileID": "Profile 7",
             "container": {"favorites": {}}}, "tabs": []}
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_profiles.py
from pathlib import Path
from dia_organizer import profiles

FIXT = Path(__file__).parent / "fixtures"


def test_resolve_window_to_profile():
    mapping = profiles.resolve_from_files(
        local_state=FIXT / "local_state.json",
        storable=FIXT / "storable_profile_containers.json",
    )
    assert mapping["AAAA-WIN-DEFAULT"] == "Keagan"
    assert mapping["BBBB-WIN-TOGETHER"] == "Together User"
    # Profile 7 has no open window — not in map.
    assert "Demo Together User" not in mapping.values()


def test_unknown_profile_falls_back_to_id():
    mapping = profiles.resolve_from_files(
        local_state=FIXT / "local_state.json",
        storable=FIXT / "storable_profile_containers.json",
    )
    assert "AAAA-WIN-DEFAULT" in mapping


def test_missing_files_returns_empty(tmp_path):
    mapping = profiles.resolve_from_files(
        local_state=tmp_path / "missing1.json",
        storable=tmp_path / "missing2.json",
    )
    assert mapping == {}
```

- [ ] **Step 3: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_profiles.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement**

```python
# src/dia_organizer/profiles.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from dia_organizer import paths


def _load_json(p: Path) -> Optional[dict]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def resolve_from_files(local_state: Path, storable: Path) -> dict[str, str]:
    """Return mapping window_id -> profile display name."""
    ls = _load_json(local_state) or {}
    sp = _load_json(storable) or {}
    info = ((ls.get("profile") or {}).get("info_cache")) or {}
    id_to_name = {pid: meta.get("name", pid) for pid, meta in info.items()}
    out: dict[str, str] = {}
    for c in sp.get("containers", []):
        cid = c.get("id") or {}
        pid = cid.get("profileID")
        win = ((cid.get("container") or {}).get("window") or {}).get("_0")
        if pid and win:
            out[win] = id_to_name.get(pid, pid)
    return out


def resolve_live() -> dict[str, str]:
    return resolve_from_files(paths.dia_local_state(), paths.dia_storable_profiles())
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_profiles.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/dia_organizer/profiles.py tests/test_profiles.py tests/fixtures/
git commit -m "feat(profiles): resolve window_id to profile name from Dia files"
```

---

## Task 8: Page Context JS

**Files:**
- Create: `src/dia_organizer/context_js.py`
- Create: `tests/test_context_js.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_context_js.py
import json
from dia_organizer import context_js


def test_payload_is_one_line():
    js = context_js.PAYLOAD
    assert "\n" not in js


def test_parse_valid_payload():
    raw = json.dumps({
        "metaDesc": "x", "ogTitle": "y", "ogDesc": "z",
        "h1": "head", "selection": "sel", "scrollPct": 42,
        "textSample": "body", "referrer": "ref",
    })
    parsed = context_js.parse(raw)
    assert parsed.meta_desc == "x"
    assert parsed.scroll_pct == 42
    assert parsed.referrer == "ref"


def test_parse_handles_empty():
    parsed = context_js.parse("")
    assert parsed.meta_desc is None
    assert parsed.scroll_pct == 0


def test_parse_handles_garbage():
    parsed = context_js.parse("not json")
    assert parsed.meta_desc is None
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_context_js.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/context_js.py
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Optional


PAYLOAD = (
    "JSON.stringify({"
    "metaDesc:document.querySelector('meta[name=description]')?.content||null,"
    "ogTitle:document.querySelector('meta[property=\\\"og:title\\\"]')?.content||null,"
    "ogDesc:document.querySelector('meta[property=\\\"og:description\\\"]')?.content||null,"
    "h1:document.querySelector('h1')?.innerText?.slice(0,200)||null,"
    "selection:getSelection().toString().slice(0,500)||null,"
    "scrollPct:Math.round(scrollY/Math.max(1,(document.body.scrollHeight-innerHeight))*100)||0,"
    "textSample:(document.body&&document.body.innerText||'').slice(0,800),"
    "referrer:document.referrer||null"
    "})"
)


@dataclass
class PageContext:
    meta_desc: Optional[str] = None
    og_title: Optional[str] = None
    og_desc: Optional[str] = None
    h1: Optional[str] = None
    selection: Optional[str] = None
    scroll_pct: int = 0
    text_sample: Optional[str] = None
    referrer: Optional[str] = None


def parse(raw: str) -> PageContext:
    if not raw:
        return PageContext()
    try:
        data = json.loads(raw)
    except Exception:
        return PageContext()
    return PageContext(
        meta_desc=data.get("metaDesc"),
        og_title=data.get("ogTitle"),
        og_desc=data.get("ogDesc"),
        h1=data.get("h1"),
        selection=data.get("selection"),
        scroll_pct=int(data.get("scrollPct") or 0),
        text_sample=data.get("textSample"),
        referrer=data.get("referrer"),
    )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_context_js.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/context_js.py tests/test_context_js.py
git commit -m "feat(context): page context JS payload + parser"
```

---

## Task 9: Archive Module

**Files:**
- Create: `src/dia_organizer/archive.py`
- Create: `tests/test_archive.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_archive.py
import time
from dia_organizer import db, archive


def test_upsert_live_inserts_new(tmp_data_dir):
    conn = db.open_db()
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example/x", "pinned": False,
        "focused": False, "now": 100,
    })
    assert rec.archive_id is not None
    assert rec.first_seen == 100
    assert rec.last_seen == 100


def test_upsert_live_updates_existing(tmp_data_dir):
    conn = db.open_db()
    archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example/x", "pinned": False,
        "focused": False, "now": 100,
    })
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example/x", "pinned": False,
        "focused": True, "now": 200,
    })
    assert rec.first_seen == 100
    assert rec.last_seen == 200
    assert rec.last_focused == 200


def test_close_tab_marks_archive(tmp_data_dir):
    conn = db.open_db()
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example/x", "pinned": False,
        "focused": False, "now": 100,
    })
    archive.mark_closed(conn, rec.archive_id, reason="auto:idle", now=300)
    row = conn.execute(
        "SELECT is_live, closed_at, close_reason FROM tabs WHERE archive_id=?",
        (rec.archive_id,),
    ).fetchone()
    assert row["is_live"] == 0
    assert row["closed_at"] == 300
    assert row["close_reason"] == "auto:idle"


def test_search_fts(tmp_data_dir):
    conn = db.open_db()
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "Tailwind dark mode tutorial",
        "url": "https://example.com/tw",
        "pinned": False, "focused": False, "now": 100,
        "meta_desc": "css framework", "h1": "Dark mode",
    })
    archive.mark_closed(conn, rec.archive_id, reason="auto:idle", now=200)
    hits = archive.search(conn, "tailwind")
    assert len(hits) == 1
    assert hits[0]["title"].startswith("Tailwind")


def test_recent_closes_within_undo_window(tmp_data_dir):
    conn = db.open_db()
    now = int(time.time())
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example", "pinned": False,
        "focused": False, "now": now - 10,
    })
    archive.mark_closed(conn, rec.archive_id, reason="auto:idle", now=now - 5)
    recent = archive.closed_within(conn, seconds=60, now=now)
    assert len(recent) == 1
    none = archive.closed_within(conn, seconds=1, now=now)
    assert none == []


def test_mark_external_close(tmp_data_dir):
    conn = db.open_db()
    archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://a.example", "pinned": False,
        "focused": False, "now": 100,
    })
    archive.mark_external_closes(conn, profile="Keagan",
                                  seen_dia_ids=set(), now=300)
    row = conn.execute(
        "SELECT is_live, close_reason FROM tabs WHERE dia_tab_id='t1'"
    ).fetchone()
    assert row["is_live"] == 0
    assert row["close_reason"] == "external"
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_archive.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/archive.py
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass
class TabRecord:
    archive_id: int
    dia_tab_id: str
    profile: str
    window_id: str
    title: str
    url: str
    first_seen: int
    last_seen: int
    last_focused: Optional[int]
    is_live: bool


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def upsert_live(conn: sqlite3.Connection, t: dict) -> TabRecord:
    """t keys: dia_tab_id, profile, window_id, title, url, pinned, focused, now,
    + optional context fields (meta_desc, og_title, og_desc, h1, selection,
      scroll_pct, text_sample, referrer)."""
    now = t["now"]
    row = conn.execute(
        "SELECT * FROM tabs WHERE dia_tab_id=? AND profile=? AND is_live=1",
        (t["dia_tab_id"], t["profile"]),
    ).fetchone()
    last_focused = now if t.get("focused") else (row["last_focused"] if row else None)
    domain = _domain(t["url"])
    if row is None:
        cur = conn.execute(
            """INSERT INTO tabs(
                dia_tab_id, profile, window_id, title, url, domain,
                first_seen, last_seen, last_focused, pinned,
                meta_desc, og_title, og_desc, h1, selection, scroll_pct, text_sample, referrer,
                is_live
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (
                t["dia_tab_id"], t["profile"], t["window_id"], t["title"], t["url"], domain,
                now, now, last_focused, 1 if t.get("pinned") else 0,
                t.get("meta_desc"), t.get("og_title"), t.get("og_desc"),
                t.get("h1"), t.get("selection"), t.get("scroll_pct"),
                t.get("text_sample"), t.get("referrer"),
            ),
        )
        archive_id = cur.lastrowid
        first_seen = now
    else:
        archive_id = row["archive_id"]
        first_seen = row["first_seen"]
        conn.execute(
            """UPDATE tabs SET
                window_id=?, title=?, url=?, domain=?, last_seen=?, last_focused=?,
                pinned=?, meta_desc=COALESCE(?, meta_desc),
                og_title=COALESCE(?, og_title), og_desc=COALESCE(?, og_desc),
                h1=COALESCE(?, h1), selection=COALESCE(?, selection),
                scroll_pct=COALESCE(?, scroll_pct),
                text_sample=COALESCE(?, text_sample), referrer=COALESCE(?, referrer)
               WHERE archive_id=?""",
            (
                t["window_id"], t["title"], t["url"], domain, now, last_focused,
                1 if t.get("pinned") else 0,
                t.get("meta_desc"), t.get("og_title"), t.get("og_desc"),
                t.get("h1"), t.get("selection"), t.get("scroll_pct"),
                t.get("text_sample"), t.get("referrer"),
                archive_id,
            ),
        )
    conn.commit()
    return TabRecord(
        archive_id=archive_id, dia_tab_id=t["dia_tab_id"], profile=t["profile"],
        window_id=t["window_id"], title=t["title"], url=t["url"],
        first_seen=first_seen, last_seen=now, last_focused=last_focused, is_live=True,
    )


def mark_closed(conn: sqlite3.Connection, archive_id: int, reason: str, now: int) -> None:
    conn.execute(
        "UPDATE tabs SET is_live=0, closed_at=?, close_reason=? WHERE archive_id=?",
        (now, reason, archive_id),
    )
    conn.commit()


def mark_external_closes(conn: sqlite3.Connection, profile: str,
                          seen_dia_ids: set[str], now: int) -> int:
    cur = conn.execute(
        "SELECT archive_id, dia_tab_id FROM tabs WHERE profile=? AND is_live=1",
        (profile,),
    )
    closed = 0
    for row in cur.fetchall():
        if row["dia_tab_id"] not in seen_dia_ids:
            mark_closed(conn, row["archive_id"], "external", now)
            closed += 1
    return closed


def live_tabs(conn: sqlite3.Connection, profile: Optional[str] = None) -> list[sqlite3.Row]:
    if profile:
        return list(conn.execute(
            "SELECT * FROM tabs WHERE is_live=1 AND profile=?", (profile,)
        ))
    return list(conn.execute("SELECT * FROM tabs WHERE is_live=1"))


def search(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    return list(conn.execute(
        """SELECT t.* FROM tabs t
           JOIN tabs_fts f ON f.rowid = t.archive_id
           WHERE tabs_fts MATCH ?
           ORDER BY t.last_seen DESC
           LIMIT ?""",
        (query, limit),
    ))


def closed_within(conn: sqlite3.Connection, seconds: int, now: int) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM tabs WHERE is_live=0 AND closed_at >= ? ORDER BY closed_at DESC",
        (now - seconds,),
    ))


def reopen_record(conn: sqlite3.Connection, archive_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tabs WHERE archive_id=?", (archive_id,)
    ).fetchone()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_archive.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/archive.py tests/test_archive.py
git commit -m "feat(archive): tabs upsert/close/search with FTS"
```

---

## Task 10: Classifier

**Files:**
- Create: `src/dia_organizer/classifier.py`
- Create: `tests/test_classifier.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_classifier.py
from dia_organizer import classifier
from dia_organizer.config import Config, ProfileConfig

DAY = 86_400


def _cfg():
    c = Config()
    c.profiles["Keagan"] = ProfileConfig(
        name="Keagan", junk_domains=["youtube.com"], allowlist_domains=["github.com"],
        auto_close_idle_days=14,
    )
    c.profiles["Together User"] = ProfileConfig(
        name="Together User", auto_close_disabled=True,
        allowlist_domains=["togetherplatform.com"],
    )
    return c


def _tab(**kw):
    base = {
        "archive_id": 1, "dia_tab_id": "t1", "profile": "Keagan", "window_id": "w1",
        "title": "T", "url": "https://example.com/x", "domain": "example.com",
        "first_seen": 0, "last_seen": 0, "last_focused": None,
        "pinned": False, "selection": None,
    }
    base.update(kw)
    return base


def test_pinned_protected():
    decision = classifier.classify(_tab(pinned=True), [_tab(pinned=True)],
                                    cfg=_cfg(), now=10*DAY)
    assert decision.action == "PROTECT"


def test_allowlist_protected():
    t = _tab(domain="github.com", url="https://github.com/x")
    assert classifier.classify(t, [t], cfg=_cfg(), now=100*DAY).action == "PROTECT"


def test_recent_protected():
    now = 10 * DAY
    t = _tab(first_seen=now - 2 * DAY)
    assert classifier.classify(t, [t], cfg=_cfg(), now=now).action == "PROTECT"


def test_selection_protects():
    t = _tab(first_seen=0, selection="something")
    assert classifier.classify(t, [t], cfg=_cfg(), now=100*DAY).action == "PROTECT"


def test_dedup_closes_older_even_in_protect_window():
    now = 10 * DAY
    older = _tab(archive_id=1, first_seen=now - 1*DAY, last_seen=now - 1*DAY,
                 url="https://a.example/x")
    newer = _tab(archive_id=2, dia_tab_id="t2",
                 first_seen=now - 60, last_seen=now - 60,
                 url="https://a.example/x")
    d_old = classifier.classify(older, [older, newer], cfg=_cfg(), now=now)
    d_new = classifier.classify(newer, [older, newer], cfg=_cfg(), now=now)
    assert d_old.action == "AUTO_CLOSE" and d_old.reason == "auto:dup"
    assert d_new.action == "PROTECT"


def test_blank_tab_auto_close():
    t = _tab(first_seen=20*DAY, last_seen=20*DAY, url="about:blank", domain="")
    assert classifier.classify(t, [t], cfg=_cfg(), now=20*DAY+1).action == "AUTO_CLOSE"


def test_junk_domain_idle():
    now = 30*DAY
    t = _tab(first_seen=now - 10*DAY, last_seen=now - 3*60*60,
             url="https://youtube.com/watch?v=x", domain="youtube.com")
    d = classifier.classify(t, [t], cfg=_cfg(), now=now)
    assert d.action == "AUTO_CLOSE" and d.reason == "auto:junk"


def test_idle_too_long():
    now = 30*DAY
    t = _tab(first_seen=now - 30*DAY, last_seen=now - 20*DAY,
             url="https://example.com/x", domain="example.com")
    d = classifier.classify(t, [t], cfg=_cfg(), now=now)
    assert d.action == "AUTO_CLOSE" and d.reason == "auto:idle"


def test_triage_at_threshold():
    now = 30*DAY
    t = _tab(first_seen=now - 30*DAY, last_seen=now - 6*DAY,
             url="https://example.com/x", domain="example.com")
    d = classifier.classify(t, [t], cfg=_cfg(), now=now)
    assert d.action == "TRIAGE"


def test_keep_otherwise():
    now = 30*DAY
    t = _tab(first_seen=now - 10*DAY, last_seen=now - 60,
             url="https://example.com/x", domain="example.com")
    assert classifier.classify(t, [t], cfg=_cfg(), now=now).action == "KEEP"


def test_together_profile_no_auto_close():
    cfg = _cfg()
    now = 100*DAY
    t = _tab(profile="Together User", first_seen=now-50*DAY, last_seen=now-30*DAY,
             url="https://example.com/x", domain="example.com")
    d = classifier.classify(t, [t], cfg=cfg, now=now)
    assert d.action == "TRIAGE"
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_classifier.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/classifier.py
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Iterable

from dia_organizer.config import Config

DAY = 86_400
HOUR = 3_600

WHITELIST_RE = re.compile(
    r"^(https?://(localhost|127\.|10\.|192\.168\.|172\.)|chrome://|about:|file://|dia://)"
)
SEARCH_RE = re.compile(r"^https?://(www\.)?(google|bing|duckduckgo)\.[^/]+/search")
TXN_RE = re.compile(
    r"(amazon\.[^/]+/gp/buy/.*thankyou|stripe\.com/.*success|checkout/success)",
    re.IGNORECASE,
)
BLANK_URLS = {"", "about:blank", "dia://newtab", "chrome://newtab/"}


@dataclass
class Decision:
    action: str       # PROTECT | AUTO_CLOSE | TRIAGE | KEEP
    reason: str = ""  # close_reason for archive when AUTO_CLOSE / TRIAGE


def _idle_seconds(tab: dict, now: int) -> int:
    last = tab["last_focused"] or tab["last_seen"]
    return max(0, now - last)


def _age_seconds(tab: dict, now: int) -> int:
    return max(0, now - tab["first_seen"])


def classify(tab: dict, all_tabs: Iterable[dict], cfg: Config, now: int) -> Decision:
    profile = cfg.profile(tab["profile"])
    url = tab["url"] or ""
    domain = tab.get("domain") or ""

    # Hard whitelist — never close.
    if WHITELIST_RE.match(url):
        return Decision("PROTECT")

    # Pin always protects.
    if tab.get("pinned"):
        return Decision("PROTECT")

    # Allowlist domain protects.
    if any(domain == d or domain.endswith("." + d) for d in profile.allowlist_domains):
        return Decision("PROTECT")

    # Dedup-close exception — fires even in protect window.
    duplicates = [
        o for o in all_tabs
        if o["url"] == url and o["profile"] == tab["profile"]
        and o["archive_id"] != tab["archive_id"]
    ]
    if duplicates:
        newest = max([tab] + duplicates, key=lambda x: x["first_seen"])
        if tab["archive_id"] != newest["archive_id"]:
            return Decision("AUTO_CLOSE", "auto:dup")

    # PROTECT — recent or selected.
    if _age_seconds(tab, now) < cfg.protect_recent_days * DAY:
        return Decision("PROTECT")
    if tab.get("selection"):
        return Decision("PROTECT")

    # Profile may forbid auto-close beyond dedup; route remaining to TRIAGE.
    auto_close_allowed = not profile.auto_close_disabled

    # AUTO_CLOSE rules.
    if auto_close_allowed:
        if url in BLANK_URLS:
            return Decision("AUTO_CLOSE", "auto:blank")
        if TXN_RE.search(url):
            return Decision("AUTO_CLOSE", "auto:txn-done")
        if SEARCH_RE.match(url) and _idle_seconds(tab, now) > HOUR:
            return Decision("AUTO_CLOSE", "auto:search-stale")
        if any(domain == d or domain.endswith("." + d) for d in profile.junk_domains):
            if _idle_seconds(tab, now) > 2 * HOUR:
                return Decision("AUTO_CLOSE", "auto:junk")
        if _idle_seconds(tab, now) > profile.auto_close_idle_days * DAY:
            return Decision("AUTO_CLOSE", "auto:idle")

    # TRIAGE rules.
    if _idle_seconds(tab, now) > cfg.triage_threshold_days * DAY:
        return Decision("TRIAGE", "triage:idle")

    return Decision("KEEP")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_classifier.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/classifier.py tests/test_classifier.py
git commit -m "feat(classifier): PROTECT/AUTO_CLOSE/TRIAGE rule pipeline"
```

---

## Task 11: Cluster Grouping

**Files:**
- Create: `src/dia_organizer/clusters.py`
- Create: `tests/test_clusters.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clusters.py
from dia_organizer import clusters

DAY = 86_400


def _t(archive_id, domain, first_seen, title, profile="Keagan"):
    return {
        "archive_id": archive_id, "profile": profile, "domain": domain,
        "first_seen": first_seen, "title": title, "referrer": None,
    }


def test_groups_same_domain_in_2h_window():
    tabs = [
        _t(1, "tailwindcss.com", 0, "Tailwind A"),
        _t(2, "tailwindcss.com", 1800, "Tailwind B"),
        _t(3, "tailwindcss.com", 3600, "Tailwind C"),
        _t(4, "github.com", 5*DAY, "Repo"),  # different domain, different time
    ]
    groups = clusters.group(tabs)
    sizes = sorted(len(g["tabs"]) for g in groups)
    assert sizes == [1, 3]


def test_singletons_remain_singletons():
    tabs = [_t(1, "a.com", 0, "X"), _t(2, "b.com", 5*DAY, "Y")]
    groups = clusters.group(tabs)
    assert all(len(g["tabs"]) == 1 for g in groups)


def test_label_uses_domain_and_date():
    tabs = [_t(1, "tailwindcss.com", 0, "A"), _t(2, "tailwindcss.com", 600, "B")]
    groups = clusters.group(tabs)
    g = next(g for g in groups if len(g["tabs"]) > 1)
    assert "tailwindcss.com" in g["label"]
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_clusters.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/clusters.py
from __future__ import annotations
import datetime as dt
from collections import defaultdict

WINDOW_SECONDS = 2 * 60 * 60


def group(tabs: list[dict]) -> list[dict]:
    """Cluster tabs by (profile, domain) within a 2h sliding window of first_seen.
    Returns list of groups: {label, profile, reason, tabs:[...]}.
    Singletons returned as one-tab groups too."""
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for t in sorted(tabs, key=lambda x: (x["profile"], x["domain"], x["first_seen"])):
        if not t["domain"]:
            by_key[(t["profile"], "_blank_", t["first_seen"])] = [t]
            continue
        slot = t["first_seen"] // WINDOW_SECONDS
        # try to attach to existing window if the prior bucket is within 2h
        prev_key = (t["profile"], t["domain"], slot - 1)
        if prev_key in by_key and (t["first_seen"] - by_key[prev_key][-1]["first_seen"]) <= WINDOW_SECONDS:
            by_key[prev_key].append(t)
        else:
            by_key[(t["profile"], t["domain"], slot)].append(t)

    groups: list[dict] = []
    for (profile, domain, _slot), members in by_key.items():
        first = min(m["first_seen"] for m in members)
        date_str = dt.datetime.fromtimestamp(first).strftime("%b %d")
        if len(members) == 1 or domain == "_blank_":
            for m in members:
                groups.append({
                    "label": m["title"][:60] or m.get("url", ""),
                    "profile": profile, "reason": "singleton", "tabs": [m],
                })
        else:
            groups.append({
                "label": f"{domain} research, {date_str} ({len(members)} tabs)",
                "profile": profile, "reason": "domain", "tabs": members,
            })
    return groups
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_clusters.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/clusters.py tests/test_clusters.py
git commit -m "feat(clusters): group triage tabs by domain + 2h window"
```

---

## Task 12: Snapshots — Create + Retention

**Files:**
- Create: `src/dia_organizer/snapshots.py`
- Create: `tests/test_snapshots.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_snapshots.py
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
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_snapshots.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/snapshots.py
from __future__ import annotations
import sqlite3
from typing import Iterable

from dia_organizer.config import Config


def take(conn: sqlite3.Connection, windows: list[dict],
          window_to_profile: dict[str, str],
          label: str, trigger: str, retention: str, now: int) -> int:
    profiles = set()
    tab_count = 0
    cur = conn.execute(
        "INSERT INTO snapshots(taken_at,label,trigger,profile_count,tab_count,retention) "
        "VALUES (?,?,?,?,?,?)",
        (now, label, trigger, 0, 0, retention),
    )
    sid = cur.lastrowid
    for w in windows:
        profile = window_to_profile.get(w["window_id"], "<unknown>")
        profiles.add(profile)
        for pos, t in enumerate(w["tabs"]):
            conn.execute(
                "INSERT OR REPLACE INTO snapshot_tabs("
                "snapshot_id,profile,window_id,dia_tab_id,position,pinned,title,url"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (sid, profile, w["window_id"], t["dia_tab_id"], pos,
                 1 if t.get("pinned") else 0, t["title"], t["url"]),
            )
            tab_count += 1
    conn.execute(
        "UPDATE snapshots SET profile_count=?, tab_count=? WHERE snapshot_id=?",
        (len(profiles), tab_count, sid),
    )
    conn.commit()
    return sid


def _trim(conn: sqlite3.Connection, retention: str, keep: int) -> None:
    rows = list(conn.execute(
        "SELECT snapshot_id FROM snapshots WHERE retention=? "
        "ORDER BY taken_at DESC", (retention,),
    ))
    for r in rows[keep:]:
        conn.execute("DELETE FROM snapshot_tabs WHERE snapshot_id=?", (r["snapshot_id"],))
        conn.execute("DELETE FROM snapshots WHERE snapshot_id=?", (r["snapshot_id"],))


def apply_retention(conn: sqlite3.Connection, cfg: Config) -> None:
    _trim(conn, "hourly", cfg.hourly_keep)
    _trim(conn, "daily",  cfg.daily_keep)
    _trim(conn, "weekly", cfg.weekly_keep)
    # manual: keep all
    # nightly: prune by age
    cutoff_rows = list(conn.execute(
        "SELECT snapshot_id FROM snapshots "
        "WHERE retention='nightly' AND taken_at < (strftime('%s','now') - ? * 86400)",
        (cfg.nightly_keep_days,),
    ))
    for r in cutoff_rows:
        conn.execute("DELETE FROM snapshot_tabs WHERE snapshot_id=?", (r["snapshot_id"],))
        conn.execute("DELETE FROM snapshots WHERE snapshot_id=?", (r["snapshot_id"],))
    conn.commit()


def list_all(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM snapshots ORDER BY taken_at DESC"))


def get_tabs(conn: sqlite3.Connection, snapshot_id: int) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM snapshot_tabs WHERE snapshot_id=? ORDER BY profile, position",
        (snapshot_id,),
    ))


def diff(conn: sqlite3.Connection, snapshot_id: int,
         current_windows: list[dict], window_to_profile: dict[str, str]) -> dict:
    snap_rows = get_tabs(conn, snapshot_id)
    snap_set = {(r["profile"], r["dia_tab_id"]): dict(r) for r in snap_rows}
    cur_set: dict[tuple, dict] = {}
    for w in current_windows:
        profile = window_to_profile.get(w["window_id"], "<unknown>")
        for t in w["tabs"]:
            cur_set[(profile, t["dia_tab_id"])] = {
                "profile": profile, "window_id": w["window_id"],
                "dia_tab_id": t["dia_tab_id"], "title": t["title"], "url": t["url"],
            }
    missing = [v for k, v in snap_set.items() if k not in cur_set]
    added   = [v for k, v in cur_set.items()  if k not in snap_set]
    return {"missing_from_current": missing, "new_since_snapshot": added}


def delete(conn: sqlite3.Connection, snapshot_id: int) -> None:
    conn.execute("DELETE FROM snapshot_tabs WHERE snapshot_id=?", (snapshot_id,))
    conn.execute("DELETE FROM snapshots WHERE snapshot_id=?", (snapshot_id,))
    conn.commit()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_snapshots.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/snapshots.py tests/test_snapshots.py
git commit -m "feat(snapshots): take, retention, list, diff, delete"
```

---

## Task 13: Snapshot Rollback

**Files:**
- Modify: `src/dia_organizer/snapshots.py` (add `rollback`)
- Modify: `tests/test_snapshots.py` (add tests)

- [ ] **Step 1: Append failing tests to `tests/test_snapshots.py`**

```python
def test_rollback_additive_dry_run(tmp_data_dir):
    conn = db.open_db()
    sid = snapshots.take(conn, _windows(), {"w1": "Keagan"},
                         label="x", trigger="manual",
                         retention="manual", now=100)
    current = [{
        "window_id": "w1", "name": "WinA",
        "tabs": [
            {"dia_tab_id": "t1", "title": "Tab1", "url": "https://a", "pinned": False, "focused": False},
        ],
    }]
    plan = snapshots.plan_rollback(conn, sid, current, {"w1": "Keagan"}, replace=False)
    assert [t["dia_tab_id"] for t in plan["to_open"]] == ["t2"]
    assert plan["to_close"] == []


def test_rollback_replace_includes_closes(tmp_data_dir):
    conn = db.open_db()
    sid = snapshots.take(conn, _windows(), {"w1": "Keagan"},
                         label="x", trigger="manual",
                         retention="manual", now=100)
    current = [{
        "window_id": "w1", "name": "WinA",
        "tabs": [
            {"dia_tab_id": "t1", "title": "Tab1", "url": "https://a", "pinned": False, "focused": False},
            {"dia_tab_id": "tNew", "title": "N", "url": "https://n", "pinned": False, "focused": False},
        ],
    }]
    plan = snapshots.plan_rollback(conn, sid, current, {"w1": "Keagan"}, replace=True)
    assert {t["dia_tab_id"] for t in plan["to_close"]} == {"tNew"}
    assert {t["dia_tab_id"] for t in plan["to_open"]}  == {"t2"}
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_snapshots.py -v`
Expected: 2 new failures (plan_rollback missing).

- [ ] **Step 3: Append to `src/dia_organizer/snapshots.py`**

```python
def plan_rollback(conn: sqlite3.Connection, snapshot_id: int,
                   current_windows: list[dict],
                   window_to_profile: dict[str, str],
                   replace: bool,
                   profile_filter: str | None = None) -> dict:
    d = diff(conn, snapshot_id, current_windows, window_to_profile)
    to_open = d["missing_from_current"]
    to_close = d["new_since_snapshot"] if replace else []
    if profile_filter:
        to_open = [t for t in to_open if t["profile"] == profile_filter]
        to_close = [t for t in to_close if t["profile"] == profile_filter]
    return {"to_open": to_open, "to_close": to_close}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_snapshots.py -v`
Expected: all snapshots tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/snapshots.py tests/test_snapshots.py
git commit -m "feat(snapshots): plan_rollback (additive + replace)"
```

---

## Task 14: Triage Queue Operations

**Files:**
- Create: `src/dia_organizer/triage.py`
- Create: `tests/test_triage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_triage.py
from dia_organizer import db, archive, triage


def _seed_tab(conn, profile="Keagan", url="https://a"):
    rec = archive.upsert_live(conn, {
        "dia_tab_id": "t1", "profile": profile, "window_id": "w1",
        "title": "T", "url": url, "pinned": False, "focused": False, "now": 100,
    })
    return rec.archive_id


def test_enqueue_idempotent(tmp_data_dir):
    conn = db.open_db()
    aid = _seed_tab(conn)
    triage.enqueue(conn, aid, now=100)
    triage.enqueue(conn, aid, now=200)  # second call must not duplicate
    rows = list(conn.execute("SELECT * FROM triage_queue WHERE archive_id=?", (aid,)))
    assert len(rows) == 1


def test_pending_excludes_resolved(tmp_data_dir):
    conn = db.open_db()
    aid = _seed_tab(conn)
    triage.enqueue(conn, aid, now=100)
    assert len(triage.pending(conn)) == 1
    triage.resolve(conn, aid, "keep", now=200)
    assert triage.pending(conn) == []


def test_snooze_hides_until_time(tmp_data_dir):
    conn = db.open_db()
    aid = _seed_tab(conn)
    triage.enqueue(conn, aid, now=100)
    triage.snooze(conn, aid, until=500, now=200)
    assert triage.pending(conn, now=400) == []
    assert len(triage.pending(conn, now=600)) == 1
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_triage.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/triage.py
from __future__ import annotations
import sqlite3
import time


def enqueue(conn: sqlite3.Connection, archive_id: int, now: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO triage_queue(archive_id, queued_at) VALUES (?,?)",
        (archive_id, now),
    )
    conn.commit()


def resolve(conn: sqlite3.Connection, archive_id: int, resolution: str, now: int) -> None:
    conn.execute(
        "UPDATE triage_queue SET resolution=?, snooze_until=NULL WHERE archive_id=?",
        (resolution, archive_id),
    )
    conn.commit()


def snooze(conn: sqlite3.Connection, archive_id: int, until: int, now: int) -> None:
    conn.execute(
        "UPDATE triage_queue SET resolution='snooze', snooze_until=? WHERE archive_id=?",
        (until, archive_id),
    )
    conn.commit()


def pending(conn: sqlite3.Connection, now: int | None = None) -> list[sqlite3.Row]:
    n = now if now is not None else int(time.time())
    return list(conn.execute(
        """SELECT t.*, q.queued_at, q.snooze_until
           FROM triage_queue q
           JOIN tabs t ON t.archive_id = q.archive_id
           WHERE (q.resolution IS NULL)
              OR (q.resolution='snooze' AND q.snooze_until <= ?)
           ORDER BY q.queued_at""",
        (n,),
    ))
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_triage.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/triage.py tests/test_triage.py
git commit -m "feat(triage): enqueue/resolve/snooze/pending"
```

---

## Task 15: Scanner Orchestration

**Files:**
- Create: `src/dia_organizer/scanner.py`
- Create: `tests/test_scanner.py`

This task wires AppleScript bridge + classifier + archive + snapshots + triage into a single `run_scan` function. AppleScript and JS extraction are mocked in tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scanner.py
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
    # Build 3 stale junk tabs that would otherwise all auto-close.
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
        # First seed all tabs so they have age >protect window
        scanner.run_scan(conn, cfg, now=0)
        result = scanner.run_scan(conn, cfg, now=30 * 86_400)
    assert len(closes) <= 1
    assert result["rate_limited"] >= 2
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_scanner.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/scanner.py
from __future__ import annotations
import sqlite3
import time

from dia_organizer import applescript, archive, classifier, clusters, context_js, profiles, triage, snapshots
from dia_organizer.config import Config


def _maybe_extract_context(window_id: str, dia_tab_id: str) -> dict:
    try:
        raw = applescript.execute_js(window_id, dia_tab_id, context_js.PAYLOAD)
    except applescript.AppleScriptError:
        return {}
    pc = context_js.parse(raw)
    return {
        "meta_desc": pc.meta_desc, "og_title": pc.og_title, "og_desc": pc.og_desc,
        "h1": pc.h1, "selection": pc.selection, "scroll_pct": pc.scroll_pct,
        "text_sample": pc.text_sample, "referrer": pc.referrer,
    }


def run_scan(conn: sqlite3.Connection, cfg: Config, now: int | None = None) -> dict:
    n = now if now is not None else int(time.time())
    if not applescript.dia_running():
        return {"status": "dia-not-running"}

    win_to_profile = profiles.resolve_live()
    windows = applescript.list_tabs()

    # 1. Upsert all live tabs (and capture context for new/changed URLs)
    seen_per_profile: dict[str, set[str]] = {}
    all_records: list[dict] = []
    for w in windows:
        profile = win_to_profile.get(w["window_id"], "<unknown>")
        seen_per_profile.setdefault(profile, set())
        for t in w["tabs"]:
            existing = conn.execute(
                "SELECT archive_id, url FROM tabs WHERE dia_tab_id=? AND profile=? AND is_live=1",
                (t["dia_tab_id"], profile),
            ).fetchone()
            extra = {}
            if existing is None or existing["url"] != t["url"]:
                extra = _maybe_extract_context(w["window_id"], t["dia_tab_id"])
            rec = archive.upsert_live(conn, {
                **t, "profile": profile, "window_id": w["window_id"], "now": n, **extra,
            })
            seen_per_profile[profile].add(t["dia_tab_id"])
            row = conn.execute("SELECT * FROM tabs WHERE archive_id=?", (rec.archive_id,)).fetchone()
            all_records.append(dict(row))

    # 2. Mark externally-closed tabs (not seen this scan) per profile
    for profile, ids in seen_per_profile.items():
        archive.mark_external_closes(conn, profile, ids, n)

    # 3. Classify all live records
    decisions = []
    for r in all_records:
        d = classifier.classify(r, all_records, cfg, n)
        decisions.append((r, d))

    will_auto_close = [(r, d) for r, d in decisions if d.action == "AUTO_CLOSE"]
    triage_targets  = [(r, d) for r, d in decisions if d.action == "TRIAGE"]

    dry = cfg.dry_run_active()

    # 4. Pre-scan snapshot if any closes will happen (and not dry-run).
    if will_auto_close and not dry:
        snapshots.take(conn, windows, win_to_profile,
                        label="pre-scan", trigger="pre-scan",
                        retention="manual", now=n)

    # 5. Apply auto-closes with caps.
    closed = []
    rate_limited = 0
    daily_counts: dict[str, int] = {}
    for r, d in will_auto_close:
        if dry:
            continue
        if len(closed) >= cfg.max_auto_closes_per_run:
            rate_limited += 1
            triage.enqueue(conn, r["archive_id"], n)
            continue
        # daily per-profile cap
        today_count = conn.execute(
            "SELECT COUNT(*) FROM tabs WHERE profile=? AND closed_at >= ?",
            (r["profile"], n - 86_400),
        ).fetchone()[0]
        if today_count + daily_counts.get(r["profile"], 0) >= cfg.max_closes_per_day_per_profile:
            rate_limited += 1
            triage.enqueue(conn, r["archive_id"], n)
            continue
        try:
            archive.mark_closed(conn, r["archive_id"], d.reason, n)
            applescript.close_tab(r["window_id"], r["dia_tab_id"])
            daily_counts[r["profile"]] = daily_counts.get(r["profile"], 0) + 1
            closed.append(r["archive_id"])
        except Exception:
            # AppleScript failed; archive is already marked closed. Leave it; next
            # scan will see tab still live, dedup or external-close handles it.
            pass

    # 6. Queue triage targets.
    for r, _d in triage_targets:
        triage.enqueue(conn, r["archive_id"], n)

    # 7. Snapshot retention housekeeping.
    snapshots.apply_retention(conn, cfg)

    return {
        "status": "ok",
        "dry_run": dry,
        "would_close_count": len(will_auto_close),
        "closed": len(closed),
        "triaged": len(triage_targets),
        "rate_limited": rate_limited,
    }
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_scanner.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/scanner.py tests/test_scanner.py
git commit -m "feat(scanner): scan orchestration with caps + dry-run"
```

---

## Task 16: CLI — Core Commands

**Files:**
- Create: `src/dia_organizer/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
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
    archive.mark_closed(conn, rec.archive_id, "auto:idle", now=2)
    conn.close()
    with patch("dia_organizer.applescript.make_tab", return_value="newid") as p:
        res = runner.invoke(cli.main, ["undo"])
    assert res.exit_code == 0
    assert p.called
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/cli.py
from __future__ import annotations
import time
import click

from dia_organizer import applescript, archive, config as cfgmod, db, scanner, snapshots, triage as triage_mod


@click.group()
def main():
    """dia-organizer — tame Dia tab sprawl."""


@main.command()
@click.option("--dry-run", is_flag=True, help="Force dry-run regardless of config")
def scan(dry_run: bool):
    cfg = cfgmod.load()
    if dry_run:
        import datetime as dt
        cfg.dry_run_until = dt.date.today() + dt.timedelta(days=1)
    conn = db.open_db()
    res = scanner.run_scan(conn, cfg)
    click.echo(
        f"status={res.get('status')} dry_run={res.get('dry_run')} "
        f"closed={res.get('closed', 0)} triaged={res.get('triaged', 0)} "
        f"rate_limited={res.get('rate_limited', 0)}"
    )


@main.command()
@click.argument("query")
def search(query: str):
    conn = db.open_db()
    rows = archive.search(conn, query)
    if not rows:
        click.echo("(no results)")
        return
    for r in rows:
        click.echo(f"[{r['profile']}] {r['title']}")
        click.echo(f"   {r['url']}")
        if r["meta_desc"]:
            click.echo(f"   {r['meta_desc'][:120]}")
        click.echo("")


@main.command()
@click.argument("archive_id", type=int)
def reopen(archive_id: int):
    conn = db.open_db()
    row = archive.reopen_record(conn, archive_id)
    if not row:
        raise click.ClickException(f"archive_id {archive_id} not found")
    new_id = applescript.make_tab(row["window_id"], row["url"])
    click.echo(f"reopened tab {new_id} in window {row['window_id']}")


@main.command()
def undo():
    cfg = cfgmod.load()
    conn = db.open_db()
    rows = archive.closed_within(conn, cfg.undo_window_minutes * 60, int(time.time()))
    if not rows:
        click.echo("nothing to undo")
        return
    for r in rows:
        try:
            applescript.make_tab(r["window_id"], r["url"])
            click.echo(f"reopened: {r['title']}")
        except applescript.AppleScriptError as e:
            click.echo(f"failed: {r['title']} ({e})")


@main.command()
def stats():
    conn = db.open_db()
    rows = list(conn.execute(
        "SELECT profile, COUNT(*) AS n FROM tabs WHERE is_live=1 GROUP BY profile"
    ))
    for r in rows:
        click.echo(f"{r['profile']}: {r['n']} live tabs")


@main.command()
def triage():
    cfg = cfgmod.load()
    import webbrowser
    url = f"http://127.0.0.1:{cfg.ui_port}/"
    click.echo(f"opening {url}")
    webbrowser.open(url)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/cli.py tests/test_cli.py
git commit -m "feat(cli): scan, search, reopen, undo, stats, triage"
```

---

## Task 17: CLI — Snapshot Commands

**Files:**
- Modify: `src/dia_organizer/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Append failing tests**

```python
# tests/test_cli.py — append
from dia_organizer import snapshots


def test_snapshot_create_and_list(tmp_data_dir):
    runner = CliRunner()
    with patch("dia_organizer.applescript.list_tabs",
               return_value=[{"window_id": "w1", "name": "n",
                              "tabs": [{"dia_tab_id": "t1", "title": "T",
                                         "url": "https://a", "pinned": False,
                                         "focused": False}]}]), \
         patch("dia_organizer.profiles.resolve_live", return_value={"w1": "Keagan"}):
        runner.invoke(cli.main, ["snapshot", "--label", "first"])
        res = runner.invoke(cli.main, ["snapshots"])
    assert res.exit_code == 0
    assert "first" in res.output


def test_rollback_dry_run(tmp_data_dir):
    runner = CliRunner()
    with patch("dia_organizer.applescript.list_tabs",
               return_value=[{"window_id": "w1", "name": "n",
                              "tabs": [{"dia_tab_id": "t1", "title": "T",
                                         "url": "https://a", "pinned": False,
                                         "focused": False}]}]), \
         patch("dia_organizer.profiles.resolve_live", return_value={"w1": "Keagan"}):
        runner.invoke(cli.main, ["snapshot", "--label", "first"])
        # mutate "live" state to be empty
    with patch("dia_organizer.applescript.list_tabs",
               return_value=[{"window_id": "w1", "name": "n", "tabs": []}]), \
         patch("dia_organizer.profiles.resolve_live", return_value={"w1": "Keagan"}):
        res = runner.invoke(cli.main, ["rollback", "1", "--dry-run"])
    assert res.exit_code == 0
    assert "would reopen" in res.output.lower()
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: 2 new failures.

- [ ] **Step 3: Append commands to `src/dia_organizer/cli.py`**

```python
# append to cli.py

@main.command(name="snapshot")
@click.option("--label", default="manual")
def snapshot_cmd(label: str):
    conn = db.open_db()
    windows = applescript.list_tabs()
    win_map = profiles_module().resolve_live()
    sid = snapshots.take(conn, windows, win_map,
                          label=label, trigger="manual",
                          retention="manual", now=int(time.time()))
    click.echo(f"snapshot {sid} ({len(windows)} windows)")


@main.command(name="snapshots")
def snapshots_cmd():
    conn = db.open_db()
    rows = snapshots.list_all(conn)
    for r in rows:
        click.echo(f"{r['snapshot_id']:>4}  {r['taken_at']}  {r['retention']:<8} "
                   f"tabs={r['tab_count']:<4} {r['label']}")


@main.command()
@click.argument("snapshot_id", type=int)
@click.option("--profile", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--replace", is_flag=True)
def rollback(snapshot_id: int, profile: str | None, dry_run: bool, replace: bool):
    conn = db.open_db()
    windows = applescript.list_tabs()
    win_map = profiles_module().resolve_live()
    plan = snapshots.plan_rollback(conn, snapshot_id, windows, win_map,
                                    replace=replace, profile_filter=profile)
    if dry_run:
        click.echo(f"would reopen {len(plan['to_open'])} tabs, "
                   f"would close {len(plan['to_close'])} tabs")
        return
    if replace:
        snapshots.take(conn, windows, win_map,
                        label=f"pre-rollback-of-{snapshot_id}",
                        trigger="pre-rollback", retention="manual",
                        now=int(time.time()))
    for t in plan["to_open"]:
        try:
            applescript.make_tab(t["window_id"], t["url"])
        except applescript.AppleScriptError:
            pass
    for t in plan["to_close"]:
        try:
            applescript.close_tab(t["window_id"], t["dia_tab_id"])
        except applescript.AppleScriptError:
            pass
    click.echo(f"reopened {len(plan['to_open'])}, closed {len(plan['to_close'])}")


def profiles_module():
    from dia_organizer import profiles as _p
    return _p
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/cli.py tests/test_cli.py
git commit -m "feat(cli): snapshot, snapshots, rollback commands"
```

---

## Task 18: Flask Server — Triage Panel

**Files:**
- Create: `src/dia_organizer/server.py`
- Create: `src/dia_organizer/templates/base.html`
- Create: `src/dia_organizer/templates/triage.html`
- Create: `src/dia_organizer/static/style.css`
- Create: `src/dia_organizer/static/app.js`
- Create: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py
from dia_organizer import db, archive, triage, server


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
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_server.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement minimal templates**

```html
<!-- src/dia_organizer/templates/base.html -->
<!doctype html>
<html><head>
  <meta charset="utf-8">
  <title>Dia Organizer</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head><body>
  <nav>
    <a href="{{ url_for('triage_page') }}">Triage</a> |
    <a href="{{ url_for('archive_page') }}">Archive</a> |
    <a href="{{ url_for('history_page') }}">History</a>
  </nav>
  <main>{% block content %}{% endblock %}</main>
  <script src="{{ url_for('static', filename='app.js') }}"></script>
</body></html>
```

```html
<!-- src/dia_organizer/templates/triage.html -->
{% extends "base.html" %}
{% block content %}
<h1>Triage ({{ items|length }})</h1>
{% if not items %}
  <p>Nothing to triage.</p>
{% endif %}
<ul class="triage-list">
{% for it in items %}
  <li class="triage-row" data-id="{{ it['archive_id'] }}">
    <div class="title">{{ it['title'] }}</div>
    <div class="meta">
      <span class="profile">{{ it['profile'] }}</span>
      <span class="domain">{{ it['domain'] }}</span>
    </div>
    {% if it['meta_desc'] %}<div class="desc">{{ it['meta_desc'] }}</div>{% endif %}
    <form method="post" action="/triage/{{ it['archive_id'] }}/keep" class="inline">
      <button type="submit">Keep</button>
    </form>
    <form method="post" action="/triage/{{ it['archive_id'] }}/close" class="inline">
      <button type="submit">Close</button>
    </form>
    <form method="post" action="/triage/{{ it['archive_id'] }}/snooze" class="inline">
      <select name="days">
        <option value="1">1d</option>
        <option value="3">3d</option>
        <option value="7" selected>7d</option>
        <option value="14">14d</option>
      </select>
      <button type="submit">Snooze</button>
    </form>
  </li>
{% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 4: Implement minimal CSS / JS**

```css
/* src/dia_organizer/static/style.css */
body { font-family: -apple-system, sans-serif; max-width: 960px; margin: 1rem auto; }
nav { margin-bottom: 1rem; }
.triage-row { border: 1px solid #ddd; padding: .75rem; margin: .5rem 0; border-radius: 6px; }
.triage-row .title { font-weight: 600; }
.triage-row .meta { color: #666; font-size: .85em; }
.inline { display: inline; }
button { cursor: pointer; }
```

```javascript
// src/dia_organizer/static/app.js — keyboard accelerators (placeholder)
document.addEventListener("keydown", (e) => {
  if (e.key === "/") {
    const search = document.querySelector('input[type=search]');
    if (search) { e.preventDefault(); search.focus(); }
  }
});
```

- [ ] **Step 5: Implement server**

```python
# src/dia_organizer/server.py
from __future__ import annotations
import time
from flask import Flask, render_template, redirect, request, url_for

from dia_organizer import applescript, archive, db, snapshots, triage


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    @app.route("/")
    def index():
        return redirect(url_for("triage_page"))

    @app.route("/triage")
    def triage_page():
        conn = db.open_db()
        items = [dict(r) for r in triage.pending(conn)]
        return render_template("triage.html", items=items)

    @app.post("/triage/<int:archive_id>/keep")
    def triage_keep(archive_id: int):
        conn = db.open_db()
        triage.resolve(conn, archive_id, "keep", int(time.time()))
        return redirect(url_for("triage_page"))

    @app.post("/triage/<int:archive_id>/close")
    def triage_close(archive_id: int):
        conn = db.open_db()
        row = conn.execute("SELECT * FROM tabs WHERE archive_id=?", (archive_id,)).fetchone()
        if row is None:
            return ("not found", 404)
        archive.mark_closed(conn, archive_id, "triage:close", int(time.time()))
        try:
            applescript.close_tab(row["window_id"], row["dia_tab_id"])
        except applescript.AppleScriptError:
            pass
        triage.resolve(conn, archive_id, "close", int(time.time()))
        return redirect(url_for("triage_page"))

    @app.post("/triage/<int:archive_id>/snooze")
    def triage_snooze(archive_id: int):
        days = int(request.form.get("days", 7))
        until = int(time.time()) + days * 86_400
        conn = db.open_db()
        triage.snooze(conn, archive_id, until=until, now=int(time.time()))
        return redirect(url_for("triage_page"))

    @app.route("/archive")
    def archive_page():
        return "archive (todo)"

    @app.route("/history")
    def history_page():
        return "history (todo)"

    return app
```

- [ ] **Step 6: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_server.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add src/dia_organizer/server.py src/dia_organizer/templates/ src/dia_organizer/static/ tests/test_server.py
git commit -m "feat(server): triage panel with keep/close/snooze"
```

---

## Task 19: Flask Server — Archive Search Panel

**Files:**
- Modify: `src/dia_organizer/server.py`
- Create: `src/dia_organizer/templates/archive.html`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing test**

```python
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
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_server.py -v`
Expected: 2 new failures.

- [ ] **Step 3: Implement template**

```html
<!-- src/dia_organizer/templates/archive.html -->
{% extends "base.html" %}
{% block content %}
<h1>Archive</h1>
<form method="get" action="/archive">
  <input type="search" name="q" value="{{ q }}" placeholder="search archive…">
  <button type="submit">Search</button>
</form>
{% if results %}
<ul class="results">
{% for r in results %}
  <li>
    <div class="title">{{ r['title'] }}</div>
    <div class="url"><a href="{{ r['url'] }}">{{ r['url'] }}</a></div>
    <div class="meta">{{ r['profile'] }} • {{ r['close_reason'] }}</div>
    {% if r['meta_desc'] %}<div class="desc">{{ r['meta_desc'] }}</div>{% endif %}
    <form method="post" action="/archive/{{ r['archive_id'] }}/reopen" class="inline">
      <button type="submit">Reopen</button>
    </form>
  </li>
{% endfor %}
</ul>
{% elif q %}
  <p>No matches for "{{ q }}".</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Replace `archive_page` and add reopen route in `server.py`**

```python
# replace the archive_page stub and add new route:

    @app.route("/archive")
    def archive_page():
        q = (request.args.get("q") or "").strip()
        results = []
        if q:
            conn = db.open_db()
            results = [dict(r) for r in archive.search(conn, q)]
        return render_template("archive.html", q=q, results=results)

    @app.post("/archive/<int:archive_id>/reopen")
    def archive_reopen(archive_id: int):
        conn = db.open_db()
        row = archive.reopen_record(conn, archive_id)
        if row is None:
            return ("not found", 404)
        try:
            applescript.make_tab(row["window_id"], row["url"])
        except applescript.AppleScriptError:
            pass
        return redirect(url_for("archive_page", q=request.args.get("q", "")))
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_server.py -v`
Expected: all server tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/dia_organizer/server.py src/dia_organizer/templates/archive.html tests/test_server.py
git commit -m "feat(server): archive search panel with reopen"
```

---

## Task 20: Flask Server — History Panel

**Files:**
- Modify: `src/dia_organizer/server.py`
- Create: `src/dia_organizer/templates/history.html`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Append failing test**

```python
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
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_server.py -v`
Expected: 2 new failures.

- [ ] **Step 3: Implement template**

```html
<!-- src/dia_organizer/templates/history.html -->
{% extends "base.html" %}
{% block content %}
<h1>History</h1>
{% if not snapshots %}<p>No snapshots yet.</p>{% endif %}
<ul class="snapshots">
{% for s in snapshots %}
  <li>
    <a href="/history/{{ s['snapshot_id'] }}">
      #{{ s['snapshot_id'] }} {{ s['label'] }} — {{ s['retention'] }}
      ({{ s['tab_count'] }} tabs)
    </a>
  </li>
{% endfor %}
</ul>
{% if detail %}
<h2>Snapshot {{ detail['snapshot_id'] }}</h2>
<p>Would reopen {{ detail['to_open']|length }} tabs. Would close {{ detail['to_close']|length }} tabs (only if --replace).</p>
<form method="post" action="/history/{{ detail['snapshot_id'] }}/rollback">
  <label><input type="checkbox" name="replace"> Replace (close tabs not in snapshot)</label>
  <button type="submit">Restore</button>
</form>
<h3>Tabs to reopen</h3>
<ul>
{% for t in detail['to_open'] %}<li>{{ t['title'] }} — {{ t['url'] }}</li>{% endfor %}
</ul>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Replace `history_page` and add detail/rollback routes**

```python
    @app.route("/history")
    def history_page():
        conn = db.open_db()
        rows = [dict(r) for r in snapshots.list_all(conn)]
        return render_template("history.html", snapshots=rows, detail=None)

    @app.route("/history/<int:snapshot_id>")
    def history_detail(snapshot_id: int):
        from dia_organizer import profiles as _p
        conn = db.open_db()
        windows = applescript.list_tabs()
        win_map = _p.resolve_live()
        plan = snapshots.plan_rollback(conn, snapshot_id, windows, win_map, replace=False)
        plan["snapshot_id"] = snapshot_id
        rows = [dict(r) for r in snapshots.list_all(conn)]
        return render_template("history.html", snapshots=rows, detail=plan)

    @app.post("/history/<int:snapshot_id>/rollback")
    def history_rollback(snapshot_id: int):
        from dia_organizer import profiles as _p
        replace = "replace" in request.form
        conn = db.open_db()
        windows = applescript.list_tabs()
        win_map = _p.resolve_live()
        if replace:
            snapshots.take(conn, windows, win_map,
                            label=f"pre-rollback-of-{snapshot_id}",
                            trigger="pre-rollback", retention="manual",
                            now=int(time.time()))
        plan = snapshots.plan_rollback(conn, snapshot_id, windows, win_map, replace=replace)
        for t in plan["to_open"]:
            try:
                applescript.make_tab(t["window_id"], t["url"])
            except applescript.AppleScriptError:
                pass
        for t in plan["to_close"]:
            try:
                applescript.close_tab(t["window_id"], t["dia_tab_id"])
            except applescript.AppleScriptError:
                pass
        return redirect(url_for("history_page"))
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_server.py -v`
Expected: all server tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/dia_organizer/server.py src/dia_organizer/templates/history.html tests/test_server.py
git commit -m "feat(server): history panel + rollback action"
```

---

## Task 21: Server Entrypoint Command

**Files:**
- Modify: `src/dia_organizer/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Append failing test**

```python
def test_serve_command_has_port(tmp_data_dir):
    runner = CliRunner()
    res = runner.invoke(cli.main, ["serve", "--help"])
    assert res.exit_code == 0
    assert "--port" in res.output
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_cli.py::test_serve_command_has_port -v`
Expected: FAIL — `serve` command missing.

- [ ] **Step 3: Append `serve` command to cli.py**

```python
@main.command()
@click.option("--port", type=int, default=None)
@click.option("--host", default="127.0.0.1")
def serve(port: int | None, host: str):
    cfg = cfgmod.load()
    p = port or cfg.ui_port
    from dia_organizer.server import create_app
    app = create_app()
    click.echo(f"serving on http://{host}:{p}")
    app.run(host=host, port=p, debug=False)
```

- [ ] **Step 4: Run test, verify pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: all cli tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/cli.py tests/test_cli.py
git commit -m "feat(cli): serve command (Flask UI)"
```

---

## Task 22: launchd Scheduling

**Files:**
- Create: `src/dia_organizer/scheduling.py`
- Create: `tests/test_scheduling.py`
- Modify: `src/dia_organizer/cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduling.py
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
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_scheduling.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# src/dia_organizer/scheduling.py
from __future__ import annotations
from pathlib import Path

LABEL = "com.keagan.dia-organizer"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def render_plist(binary: str, interval_seconds: int,
                 log_path: str, err_path: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{binary}</string>
    <string>scan</string>
  </array>
  <key>StartInterval</key><integer>{interval_seconds}</integer>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>{log_path}</string>
  <key>StandardErrorPath</key><string>{err_path}</string>
</dict></plist>
'''
```

- [ ] **Step 4: Append CLI commands**

```python
# in cli.py
import shutil, subprocess, sys
from dia_organizer import paths as paths_mod, scheduling

@main.command(name="install-schedule")
def install_schedule():
    cfg = cfgmod.load()
    paths_mod.ensure_data_home()
    binary = shutil.which("dia-organizer") or sys.executable + " -m dia_organizer.cli"
    plist = scheduling.render_plist(
        binary=binary,
        interval_seconds=cfg.scan_interval_minutes * 60,
        log_path=str(paths_mod.log_path()),
        err_path=str(paths_mod.err_path()),
    )
    p = scheduling.plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(plist)
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
    subprocess.run(["launchctl", "load", str(p)], check=True)
    click.echo(f"installed: {p}")


@main.command(name="uninstall-schedule")
def uninstall_schedule():
    p = scheduling.plist_path()
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
    if p.exists():
        p.unlink()
    click.echo("uninstalled")
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_scheduling.py tests/test_cli.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/dia_organizer/scheduling.py tests/test_scheduling.py src/dia_organizer/cli.py
git commit -m "feat(scheduling): launchd plist install/uninstall"
```

---

## Task 23: Notifications + Lock Wiring in Scanner

**Files:**
- Create: `src/dia_organizer/notifications.py`
- Modify: `src/dia_organizer/scanner.py`
- Create: `tests/test_notifications.py`
- Modify: `tests/test_scanner.py`

- [ ] **Step 1: Write the failing test for notifications**

```python
# tests/test_notifications.py
from unittest.mock import patch
from dia_organizer import notifications


def test_notify_runs_osascript():
    with patch("subprocess.run") as p:
        p.return_value.returncode = 0
        notifications.notify("hello", "world")
        cmd = p.call_args[0][0]
        assert cmd[0] == "osascript"
        assert "display notification" in cmd[2]
```

- [ ] **Step 2: Implement notifications.py**

```python
# src/dia_organizer/notifications.py
import subprocess


def notify(title: str, body: str) -> None:
    script = (
        f'display notification "{body.replace(chr(34), chr(39))}" '
        f'with title "{title.replace(chr(34), chr(39))}"'
    )
    subprocess.run(["osascript", "-e", script], capture_output=True)
```

- [ ] **Step 3: Append failing test for lock wiring**

```python
# tests/test_scanner.py — append
from dia_organizer import locking


def test_scan_uses_lock(tmp_data_dir):
    conn = db.open_db()
    cfg = _cfg()
    with patch("dia_organizer.applescript.dia_running", return_value=True), \
         patch("dia_organizer.applescript.list_tabs", return_value=_windows()), \
         patch("dia_organizer.applescript.execute_js", return_value=""), \
         patch("dia_organizer.profiles.resolve_live", return_value={"WIN1": "Keagan"}):
        with locking.scan_lock():
            res = scanner.run_scan_cli_safe(conn, cfg, now=10**9)
    assert res["status"] == "lock-held"
```

- [ ] **Step 4: Add `run_scan_cli_safe` wrapper to scanner.py**

```python
# at bottom of scanner.py
from dia_organizer import locking


def run_scan_cli_safe(conn, cfg, now=None):
    try:
        with locking.scan_lock():
            return run_scan(conn, cfg, now=now)
    except locking.LockHeld:
        return {"status": "lock-held"}
```

- [ ] **Step 5: Wire `cli.scan` to use `run_scan_cli_safe` and emit notification on triage growth**

In `cli.py` `scan` command, replace the `scanner.run_scan(...)` call with:

```python
    res = scanner.run_scan_cli_safe(conn, cfg)
    if cfg.notify_on_triage_queue_growth and res.get("triaged", 0) > 0:
        from dia_organizer import notifications
        notifications.notify("Dia Organizer", f"{res['triaged']} tabs queued for triage")
```

- [ ] **Step 6: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_notifications.py tests/test_scanner.py tests/test_cli.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/dia_organizer/notifications.py src/dia_organizer/scanner.py src/dia_organizer/cli.py tests/test_notifications.py tests/test_scanner.py
git commit -m "feat(notifications,locking): notify on triage growth, lock around scan"
```

---

## Task 24: Hourly + Nightly Snapshot Triggers

**Files:**
- Modify: `src/dia_organizer/scanner.py`
- Modify: `tests/test_scanner.py`

- [ ] **Step 1: Append failing test**

```python
def test_hourly_snapshot_taken_when_due(tmp_data_dir):
    conn = db.open_db()
    cfg = _cfg()
    with patch("dia_organizer.applescript.dia_running", return_value=True), \
         patch("dia_organizer.applescript.list_tabs", return_value=_windows()), \
         patch("dia_organizer.applescript.execute_js", return_value=""), \
         patch("dia_organizer.applescript.close_tab"), \
         patch("dia_organizer.profiles.resolve_live", return_value={"WIN1": "Keagan"}):
        scanner.run_scan(conn, cfg, now=10**9)
    cnt_before = conn.execute(
        "SELECT COUNT(*) FROM snapshots WHERE retention='hourly'"
    ).fetchone()[0]
    assert cnt_before >= 1


def test_hourly_snapshot_skipped_within_same_hour(tmp_data_dir):
    conn = db.open_db()
    cfg = _cfg()
    with patch("dia_organizer.applescript.dia_running", return_value=True), \
         patch("dia_organizer.applescript.list_tabs", return_value=_windows()), \
         patch("dia_organizer.applescript.execute_js", return_value=""), \
         patch("dia_organizer.applescript.close_tab"), \
         patch("dia_organizer.profiles.resolve_live", return_value={"WIN1": "Keagan"}):
        scanner.run_scan(conn, cfg, now=10**9)
        scanner.run_scan(conn, cfg, now=10**9 + 60)  # one minute later
    cnt = conn.execute(
        "SELECT COUNT(*) FROM snapshots WHERE retention='hourly'"
    ).fetchone()[0]
    assert cnt == 1
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_scanner.py -v`
Expected: 2 new failures.

- [ ] **Step 3: Add hourly trigger logic to `run_scan` (after upsert step, before classification)**

In `scanner.py`, after step 2 (`mark_external_closes`) add:

```python
    # 2b. Hourly snapshot — only if no hourly snapshot in current hour bucket.
    hour_bucket = n // 3600
    last_hourly = conn.execute(
        "SELECT taken_at FROM snapshots WHERE retention='hourly' ORDER BY taken_at DESC LIMIT 1"
    ).fetchone()
    if last_hourly is None or (last_hourly["taken_at"] // 3600) < hour_bucket:
        snapshots.take(conn, windows, win_to_profile,
                        label="auto-hourly", trigger="hourly",
                        retention="hourly", now=n)

    # 2c. Nightly snapshot — once per UTC day at/after 02:00 local proxy: bucket by 86400.
    day_bucket = n // 86_400
    last_nightly = conn.execute(
        "SELECT taken_at FROM snapshots WHERE retention='nightly' ORDER BY taken_at DESC LIMIT 1"
    ).fetchone()
    if last_nightly is None or (last_nightly["taken_at"] // 86_400) < day_bucket:
        snapshots.take(conn, windows, win_to_profile,
                        label="auto-nightly", trigger="nightly",
                        retention="nightly", now=n)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_scanner.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/dia_organizer/scanner.py tests/test_scanner.py
git commit -m "feat(snapshots): hourly + nightly auto-snapshots inside scan"
```

---

## Task 25: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

```markdown
# Dia Organizer

Tame Dia browser tab sprawl across multiple profiles on macOS.

## Install

```bash
git clone https://github.com/kegsss/Tidy-Dia.git
cd Tidy-Dia
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Quick start

```bash
# First scan in dry-run (default for 7 days after install)
.venv/bin/dia-organizer scan

# Open the triage UI
.venv/bin/dia-organizer serve            # http://127.0.0.1:7321

# Search the archive
.venv/bin/dia-organizer search "tailwind"

# Take a manual snapshot
.venv/bin/dia-organizer snapshot --label "before research"

# Roll back (additive)
.venv/bin/dia-organizer rollback 5 --dry-run

# Install background schedule (every 30 min)
.venv/bin/dia-organizer install-schedule
```

## Configuration

`~/.dia-organizer/config.toml` — see `docs/superpowers/specs/2026-04-28-dia-organizer-design.md` for the full schema.

## Safety

- Dry-run default for 7 days after install.
- Every closed tab archived with full page context before close.
- 60-minute undo window on auto-closes.
- Hard caps: 20 auto-closes/scan, 50 closes/day/profile.
- Per-profile rules (work profile defaults to no auto-close).
- Snapshots before destructive rollback.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with quickstart"
```

---

## Task 26: End-to-End Smoke Test

**Files:**
- Create: `tests/test_smoke.py`

This test wires the major components together with mocks at the AppleScript boundary, then walks through scan → triage → search → snapshot → rollback.

- [ ] **Step 1: Write smoke test**

```python
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
```

- [ ] **Step 2: Run test, verify pass**

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: pass.

- [ ] **Step 3: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: end-to-end smoke covering scan/search/snapshot/rollback"
```

---

## Self-Review Notes

- **Spec coverage:** every section of the spec maps to a task — Architecture (Tasks 1, 4, 15, 18-21), Profile resolution (Task 7), Scanner + JS context (Tasks 6, 8, 15), Classifier rules incl. dedup-in-protect-window (Task 10), Cluster grouping (Task 11), Archive + FTS (Tasks 4, 9), Snapshots + rollback + retention (Tasks 12, 13, 24), Triage queue (Task 14), Triage UI clickable + Archive search + History (Tasks 18-20), CLI surface (Tasks 16, 17, 21), launchd scheduling (Task 22), Safety (dry-run in Task 3, archive-before-close in Task 9, locking in Task 5, undo in Task 16, caps in Task 15, whitelist in Task 10, pre-scan snapshot in Task 15), Notifications (Task 23).
- **No placeholders:** all code blocks contain runnable code; templates are complete; no "TBD" or "implement later".
- **Type/name consistency:** `archive.upsert_live` / `mark_closed` / `mark_external_closes` / `closed_within` / `reopen_record` / `live_tabs` / `search` reused exactly in scanner, server, CLI. `snapshots.take` / `apply_retention` / `list_all` / `get_tabs` / `diff` / `plan_rollback` / `delete` reused exactly. `classifier.classify` returns `Decision(action, reason)` consistently across tests and callers. Profile config field names (`auto_close_disabled`, `junk_domains`, `allowlist_domains`, `auto_close_idle_days`) are used identically in `config.py`, `classifier.py`, and tests.
- **Scope:** single project, single deliverable (a working CLI + UI). No decomposition needed.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-28-dia-organizer.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
