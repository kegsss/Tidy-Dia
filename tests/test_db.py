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
