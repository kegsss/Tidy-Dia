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
