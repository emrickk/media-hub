#!/usr/bin/env python3
"""Create the empty local store needed by a chat-history-only user.

The repository deliberately does not ship anyone's `media.db`. This command
creates the user-owned database with the core media identity tables plus the
recommendation, critic-feedback, candidate-pool, and calibration tables. It is
idempotent and never removes or replaces existing rows.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import calibrate
import pool
import reclog


CORE_DDL = """
CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    original_title TEXT DEFAULT '',
    year INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    neodb_uuid TEXT,
    cover_url TEXT,
    season_number INTEGER,
    title_en TEXT DEFAULT '',
    creators TEXT DEFAULT '',
    meta TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS external_ids (
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    value TEXT NOT NULL,
    UNIQUE(namespace, value)
);
CREATE INDEX IF NOT EXISTS idx_ext_work ON external_ids(work_id);
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    rating REAL,
    marked_at TEXT DEFAULT '',
    review TEXT DEFAULT '',
    raw TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(source, work_id, status)
);
CREATE INDEX IF NOT EXISTS idx_rec_work ON records(work_id);
CREATE TABLE IF NOT EXISTS work_aliases (
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    UNIQUE(work_id, alias)
);
CREATE TABLE IF NOT EXISTS suppressed_ids (
    namespace TEXT NOT NULL,
    value TEXT NOT NULL,
    note TEXT DEFAULT '',
    PRIMARY KEY(namespace, value)
);
"""


def bootstrap(path: Path) -> dict:
    created = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute("pragma foreign_keys=on")
        con.execute("pragma busy_timeout=15000")
        con.executescript(CORE_DDL)
        con.executescript(reclog.DDL + reclog.FEEDBACK_DDL)
        con.executescript(pool.DDL)
        con.executescript(calibrate.SCHEMA)
        con.commit()
        tables = [row[0] for row in con.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' "
            "order by name")]
    finally:
        con.close()
    return {"ok": True, "created": created, "db": str(path.resolve()),
            "tables": tables}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="media.db")
    args = parser.parse_args()
    print(json.dumps(bootstrap(Path(args.db)), ensure_ascii=False))


if __name__ == "__main__":
    main()
