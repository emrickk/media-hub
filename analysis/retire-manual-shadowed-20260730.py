#!/usr/bin/env python3
"""Retire the 14 manual review/rating values that shadow newer Douban text.

Anping's call (2026-07-30): the Douban 短评 he wrote after the 07-28 dictation
pass is canonical, and ratings follow the same rule so each work's rating and
comment come from one source.

Non-destructive: the manual row stays (status, marked_at, provenance intact);
its review/rating move into raw as retired_review / retired_rating so the
dictated wording is recoverable. Blanking them makes resolved.py fall through
to the douban record for both fields.
"""

import json
import sqlite3
import sys
from datetime import datetime

WORK_IDS = [447, 448, 449, 453, 457, 4369, 4370, 4372, 4374, 4377, 5947, 5949, 5954, 5955]

conn = sqlite3.connect("media.db")
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT work_id, rating, review, raw FROM records WHERE source='manual' AND work_id IN "
    f"({','.join('?' * len(WORK_IDS))})", WORK_IDS
).fetchall()

if len(rows) != len(WORK_IDS):
    print(f"ABORT: expected {len(WORK_IDS)} manual rows, found {len(rows)}", file=sys.stderr)
    raise SystemExit(1)

# every target must have a douban row carrying the replacement text
for r in rows:
    d = conn.execute(
        "SELECT review, rating FROM records WHERE source='douban' AND work_id=?", (r["work_id"],)
    ).fetchone()
    if not d or not (d["review"] or "").strip():
        print(f"ABORT: work {r['work_id']} has no douban review to fall through to", file=sys.stderr)
        raise SystemExit(1)

stamp = datetime.now().strftime("%Y-%m-%d")
for r in rows:
    try:
        raw = json.loads(r["raw"]) if r["raw"] else {}
    except json.JSONDecodeError:
        raw = {}
    raw["retired_review"] = r["review"] or ""
    raw["retired_rating"] = r["rating"]
    raw["retired_on"] = stamp
    raw["retired_reason"] = "superseded by newer douban 短评; Anping's call 2026-07-30"
    conn.execute(
        "UPDATE records SET review='', rating=NULL, raw=? WHERE source='manual' AND work_id=?",
        (json.dumps(raw, ensure_ascii=False), r["work_id"]),
    )

conn.execute(
    "INSERT INTO sync_runs(source, started_at, finished_at, items, note) VALUES(?,?,?,?,?)",
    ("manual", datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
     datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(rows),
     "retired 14 manual review/rating values superseded by newer douban 短评 (Anping's call)"),
)
conn.commit()
print(f"retired {len(rows)} manual review/rating values (text preserved in raw.retired_review)")
conn.close()
