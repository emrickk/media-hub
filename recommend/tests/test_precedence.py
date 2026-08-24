"""Direct unit tests for precedence.py — the shared resolver both
history.py and reclog.py depend on. It had no tests of its own; every
assertion here was previously only exercised (if at all) through a
subprocess round-trip via one of its two callers."""
import sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from precedence import SOURCE_PRECEDENCE, pick_best, source_rank, status_rank


def test_source_rank_orders_known_sources():
    assert [source_rank(s) for s in SOURCE_PRECEDENCE] == [0, 1, 2, 3]

def test_unknown_source_ranks_last():
    assert source_rank("ryot") == len(SOURCE_PRECEDENCE)
    assert source_rank(None) == len(SOURCE_PRECEDENCE)
    assert source_rank("steam") > source_rank("plex")

def test_unknown_source_still_loses_to_every_known_one():
    rows = [{"source": "steam", "rating": 10.0}, {"source": "plex", "rating": 2.0}]
    assert pick_best(rows)["source"] == "plex"

def test_empty_input_returns_none():
    assert pick_best([]) is None
    assert pick_best(iter([])) is None

def test_two_unknown_sources_break_ties_alphabetically():
    rows = [{"source": "zeta"}, {"source": "alpha"}]
    assert pick_best(rows)["source"] == "alpha"      # deterministic, not cursor order
    assert pick_best(list(reversed(rows)))["source"] == "alpha"

def test_rows_without_status_or_marked_at_still_resolve():
    """reclog.py's `stats` selects only (source, rating) — the resolver
    must tolerate the absent columns rather than raising."""
    rows = [{"source": "letterboxd", "rating": 6.0},
            {"source": "douban", "rating": 8.0}]
    assert pick_best(rows)["rating"] == 8.0

def test_sqlite_row_with_unselected_columns_is_tolerated():
    """sqlite3.Row raises IndexError (not KeyError) for a column that was
    never selected — the code path _field() exists to absorb."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    rows = list(con.execute("SELECT 'douban' AS source, 8.0 AS rating"))
    assert pick_best(rows)["source"] == "douban"

def test_status_rank_prefers_watched_over_watching():
    assert status_rank("watched") < status_rank("watching") < status_rank("wishlist")
    assert status_rank(None) == status_rank("anything-else")

def test_same_source_tie_resolves_watched_over_watching():
    """UNIQUE(source, work_id, status) permits one source to hold both a
    watched and a watching row for the same work. Both insertion orders
    must give the same answer."""
    watching = {"source": "douban", "status": "watching", "rating": 6.0,
                "marked_at": "2026-02-01"}
    watched  = {"source": "douban", "status": "watched",  "rating": 9.0,
                "marked_at": "2026-01-01"}
    assert pick_best([watching, watched])["rating"] == 9.0
    assert pick_best([watched, watching])["rating"] == 9.0

def test_same_source_same_status_tie_resolves_to_most_recent():
    a = {"source": "douban", "status": "watched", "rating": 6.0,
         "marked_at": "2026-01-01"}
    b = {"source": "douban", "status": "watched", "rating": 9.0,
         "marked_at": "2026-05-05"}
    assert pick_best([a, b])["rating"] == 9.0
    assert pick_best([b, a])["rating"] == 9.0

def test_missing_marked_at_loses_to_a_dated_row_of_equal_rank():
    dated = {"source": "douban", "status": "watched", "rating": 9.0,
             "marked_at": "2026-01-01"}
    undated = {"source": "douban", "status": "watched", "rating": 6.0,
               "marked_at": None}
    assert pick_best([undated, dated])["rating"] == 9.0

def test_source_still_outranks_status():
    """A higher-precedence source wins even from a weaker status —
    precedence order is source first, then status, then recency."""
    rows = [{"source": "letterboxd", "status": "watched",  "rating": 2.0,
             "marked_at": "2026-09-09"},
            {"source": "douban",     "status": "watching", "rating": 8.0,
             "marked_at": "2020-01-01"}]
    assert pick_best(rows)["source"] == "douban"
