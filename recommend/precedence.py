"""precedence.py: shared source-precedence resolution for the recommend system.

Multiple sources can carry a watched/rated record for the same work
(douban, letterboxd, plex, manual entry). Wherever a single fact must be
picked from several source-tagged rows — `history.py`'s `rated` snapshot,
`reclog.py`'s `stats` sealed-vs-actual join — resolve with the SAME
precedence so the two never silently disagree: manual (deliberate hand
entry, incl. taste-test corrections) > douban (the only bulk source with
review text) > letterboxd (frozen sole-source copy) > plex (a handful of
ratings). Sources outside this tuple rank last.

A SAME-SOURCE tie is reachable and must resolve deterministically.
`records` is `UNIQUE(source, work_id, status)`, so one source can legally
hold BOTH a `watched` and a `watching` row for one work, and
`history.py`'s `_rated_entries` gathers both statuses. Without a
tie-break the winner would depend on cursor order. Order within one
source: `watched` > `watching` (a finished view is the settled opinion;
an in-progress rating is provisional), then the more recent `marked_at`.
Rows that carry no `status`/`marked_at` key at all (e.g. `reclog.py`'s
`stats` query, which selects only source+rating) all tie at the same
rank, so those call sites behave exactly as before.
"""
from __future__ import annotations

SOURCE_PRECEDENCE = ("manual", "douban", "letterboxd", "plex")
STATUS_PRECEDENCE = ("watched", "watching")

def source_rank(source) -> int:
    try:
        return SOURCE_PRECEDENCE.index(source)
    except ValueError:
        return len(SOURCE_PRECEDENCE)

def status_rank(status) -> int:
    try:
        return STATUS_PRECEDENCE.index(status)
    except ValueError:
        return len(STATUS_PRECEDENCE)

def _field(row, key, default=""):
    """Read `key` from a sqlite3.Row or dict, tolerating its absence.
    sqlite3.Row raises IndexError for an unselected column; dict raises
    KeyError. A present-but-NULL value is treated as absent."""
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value

def pick_best(rows):
    """Return the row (sqlite3.Row/dict with a 'source' key) whose source
    ranks highest in SOURCE_PRECEDENCE. Ties within one source resolve by
    status (`watched` > `watching` > anything else) and then by the more
    recent `marked_at`; ties across two equally-unknown sources break
    alphabetically by source name. Fully deterministic — never dependent
    on cursor order. `rows` must already be filtered to only the rows
    that actually carry the fact being resolved (e.g. rating IS NOT NULL)
    — this function only knows about ranking, not field presence.
    Returns None if `rows` is empty."""
    rows = list(rows)
    if not rows:
        return None
    # Most-recent-first, so that `min` (which returns the FIRST row
    # holding the minimal key) resolves any remaining tie toward recency.
    rows.sort(key=lambda r: str(_field(r, "marked_at", "")), reverse=True)
    return min(rows, key=lambda r: (source_rank(r["source"]), str(r["source"]),
                                    status_rank(_field(r, "status", None))))
