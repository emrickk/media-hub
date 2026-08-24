#!/usr/bin/env python3
"""pool.py: the `candidate_pool` table in media.db (v2 plan Task 1).

Why this table exists. v1 re-derives its whole candidate set on every ask
— harvesting the same platform-recommendation results and re-fetching the
same review evidence, at a cost of 13-16 minutes per run. `candidate_pool`
caches what platform recommendation engines (TMDB `/recommendations`,
Douban CF, ...) hand back, so rows ACCUMULATE across harvester runs instead
of being rebuilt, and review `evidence` is fetched once and never re-fetched
(`evidence_fetched_at` records when). Rejected/watched candidates are
SUPPRESSED, never deleted, so the provenance of who found what, from which
anchor, on which channel, survives — this project's non-destructive rule
(`ARCHITECTURE.md`, `CLAUDE.md`) applies here exactly as it does to
`records`/`recommendations`.

Subcommands
-----------
`init`            create the table (idempotent, `CREATE TABLE IF NOT EXISTS`).
`upsert`          batch-insert-or-merge candidates from a JSON file (a list
                  of candidate rows — see "Upsert contract" below).
`query`           filtered read (kind/year range/tags/channel/evidence
                  presence), suppressed rows excluded unless
                  `--include-suppressed`.
`attach-evidence` cache one candidate's fetched review evidence permanently
                  (`evidence` + `evidence_fetched_at`).
`suppress-sync`   mark pool rows suppressed when the candidate has since
                  been watched/is-watching (including a recommendation
                  reaction recorded as `watched`), or was previously rejected
                  (`recommendations.verdict='no'`). UPDATE only, idempotent.
`stats`           pool-wide counts: total, by kind, evidence-cached,
                  suppressed, per-channel provenance.

Upsert contract
----------------
Each row is a JSON object. Required, non-empty: `kind`, `title`, `sources`
(a non-empty list — a candidate with no provenance is not a valid harvest
result). Optional, each defaulted if absent: `year` (null),
`original_title` (''), `external_ids` ({}), `tags` ([]), `aggregates` ({}),
`shape` ({}). The WHOLE batch is validated up front, same discipline as
`reclog.py`'s `_validate_log_rows` — a bad batch inserts nothing, and every
bad row is reported at once (row index + missing field(s), plus the title
when one is present), not one traceback at a time.

**Matching** (does this row already exist in the pool?), in order:
  1. any SHARED `external_ids` (namespace, value) pair with an existing
     row — checked via a correlated `json_each` over `external_ids`, so a
     row that carries five ids only needs ONE of them to already be known;
  2. else exact `(kind, lower(title), year)`.
No match -> INSERT a new row. A match -> MERGE into the existing row:
  - `tags`: UNION (existing set | incoming set).
  - `sources`: APPEND (every harvest is provenance; two harvesters hitting
    the same candidate from different anchors/channels must both survive
    in the list, not overwrite each other).
  - `external_ids` / `aggregates` / `shape`: gap-fill merge — an incoming
    key with a non-empty value fills the slot ONLY if the existing value
    for that key is missing/empty. **An existing non-empty value is NEVER
    overwritten, empty or not** — this is the subtle, load-bearing rule:
    two harvesters will legitimately hit the same candidate from different
    anchors with different id namespaces, and letting a later, thinner
    payload clobber an earlier, richer one would destroy exactly the
    provenance this table exists to accumulate.
  - `original_title`: gap-fill (same rule, scalar case).
  - `kind`/`title`/`year` (the identity used for matching) are left as
    first-written; a merge never touches them.
  - `updated_at` bumps to the merge's timestamp; `created_at` never changes.
All rows of one `upsert` call run in a SINGLE transaction — validation
failure or a mid-batch exception both leave the table completely
unchanged (see `cmd_upsert`).

`query`'s WHERE clause is built entirely from parameterized SQL (never
string-interpolated values). `--tag` (repeatable) and `--channel`
(repeatable — ruled on explicitly, not a typo: matches `--tag`'s shape so
the CLI stays internally consistent, and comparing what one harvester
channel contributed against another is a real pool-health query) both OR
across repeats and use the same
`EXISTS (SELECT 1 FROM json_each(...) WHERE ...)` shape over their
respective JSON array columns (`tags`, and `sources[].channel`). This
needs SQLite's JSON1 extension, which ships enabled by default in
Python's stdlib `sqlite3` from 3.10 onward; if it is somehow unavailable
here, the query subcommand fails loudly rather than silently falling back
to a different (slower, non-equivalent) matching strategy.

Example usage (both flags repeatable, OR'd across repeats):
```
python3 pool.py --db media.db query --tag comedy --tag workplace
python3 pool.py --db media.db query --channel tmdb_rec --channel douban_rec
python3 pool.py --db media.db query --kind tv --year-from 2020 --tag comedy \
    --channel tmdb_rec --needs-evidence --limit 20
```

`suppress-sync` never deletes or un-suppresses a row — it is a pure,
idempotent UPDATE pass with two independent reasons, `watched` checked
before `rejected` so a row that qualifies for both is counted once,
against the reason that fired: (a) the row's `external_ids` overlaps an
`external_ids` row for a work carrying a `watched`/`watching` record, OR
the row shares "show identity" with a watched/watching/wishlisted TV
SEASON (see "Season/parent asymmetry" below) — both count as
`suppressed_reason='watched'`; (b) the row id-overlaps (else exact
title+year+kind) a `recommendations` row with `verdict='no'`
(`suppressed_reason='rejected'`). The printed `suppressed` count is rows
newly suppressed THIS run, not the pool-wide total.

**Season/parent asymmetry** (fix, 2026-08-23, same bug as `history.py`'s
`shells` — see that module's docstring for the full rationale). media.db
stores TV one row per season (`kind='tv'`) plus a separate series-level
`kind='show'` row that never carries its own record; a platform harvest
(TMDB's own `/recommendations`) represents the show as ONE unit, so a
harvested candidate's `external_ids` line up with the show-level ids —
exactly the ids a season row keeps in `meta.show_tmdb_id`/
`show_imdb_id`, NEVER in the season's own `external_ids` (the season-tt
gotcha) — so the plain external_ids-to-external_ids join in (a) could
never see a show the user watched season-by-season. Fixed by also
checking id-overlap against those `meta` ids, and — when a candidate
carries no id at all — a base-title (`第N季` suffix stripped) fallback
gated by a real season family + year, identically to `history.py`'s
`shells`, so this can never collapse two unrelated candidates that
merely share a title.

`busy_timeout` 15000ms, same convention as `reclog.py`/`history.py` —
several agent sessions run against this DB concurrently; a competing
writer's lock is waited out, not treated as an error.
"""
from __future__ import annotations
import argparse, json, re, sqlite3, sys
from datetime import datetime, timezone

DDL = """
CREATE TABLE IF NOT EXISTS candidate_pool (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL, title TEXT NOT NULL, original_title TEXT DEFAULT '',
    year INTEGER,
    external_ids TEXT NOT NULL DEFAULT '{}',
    tags TEXT NOT NULL DEFAULT '[]',
    aggregates TEXT NOT NULL DEFAULT '{}',
    shape TEXT NOT NULL DEFAULT '{}',
    sources TEXT NOT NULL DEFAULT '[]',
    evidence TEXT, evidence_fetched_at TEXT,
    suppressed INTEGER NOT NULL DEFAULT 0,
    suppressed_reason TEXT DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pool_kind_year ON candidate_pool(kind, year);
"""

UPSERT_REQUIRED_FIELDS = ("kind", "title")
JSON_DICT_FIELDS = ("external_ids", "aggregates", "shape")
BUSY_TIMEOUT_MS = 15000
EMPTY_VALUES = (None, "", [], {})

# --------------------------------------------------- season/parent identity
#
# Same fix, same shapes, as history.py's `shells` — see this module's
# docstring's "Season/parent asymmetry" and history.py's module docstring
# for the full rationale.

SEASON_SUFFIX_RE = re.compile(r"^(.*?)\s*第[0-9一二三四五六七八九十百]+季$")

def _strip_season_suffix(title: str | None) -> str | None:
    if not title:
        return None
    m = SEASON_SUFFIX_RE.match(title.strip())
    if not m:
        return None
    base = m.group(1).strip()
    return base or None

def _show_ids_from_meta(meta_json: str | None) -> set[tuple[str, str]]:
    if not meta_json:
        return set()
    try:
        meta = json.loads(meta_json)
    except (TypeError, ValueError):
        return set()
    if not isinstance(meta, dict):
        return set()
    ids = set()
    if meta.get("show_tmdb_id"):
        ids.add(("tmdb_tv", str(meta["show_tmdb_id"])))
    if meta.get("show_imdb_id"):
        ids.add(("imdb", str(meta["show_imdb_id"])))
    return ids

def _watched_season_identity(con):
    """(watched_show_titles, watched_show_ids, sibling_years) built from
    the real works/records tables — the same season/parent asymmetry fix
    as history.py's `shells`, applied here so a pool candidate
    representing a whole show (a platform's own unit, never a season)
    can be suppressed even though its own `external_ids` can't reach a
    watched SEASON row's ids directly."""
    watched_rows = con.execute("""
        SELECT DISTINCT w.title, w.meta FROM works w
        JOIN records rec ON rec.work_id = w.id
        WHERE rec.status IN ('watched','watching','wishlist')
          AND w.season_number IS NOT NULL""").fetchall()
    watched_titles, watched_ids = set(), set()
    for r in watched_rows:
        base = _strip_season_suffix(r["title"])
        if base:
            watched_titles.add(base)
        watched_ids |= _show_ids_from_meta(r["meta"])

    sibling_years: dict[str, set] = {}
    for r in con.execute(
            "SELECT title, year FROM works WHERE season_number IS NOT NULL"):
        base = _strip_season_suffix(r["title"])
        if base:
            sibling_years.setdefault(base, set()).add(r["year"])

    return watched_titles, watched_ids, sibling_years

def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    # Several agent sessions run against this DB concurrently; wait for a
    # competing writer's lock instead of erroring out immediately.
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return con

def cmd_init(con, args):
    con.executescript(DDL)
    con.commit()
    print("ok")

# ------------------------------------------------------------- upsert

def _validate_upsert_rows(rows) -> list[str]:
    """Check the WHOLE batch and return one human-readable problem string
    per bad row (empty list if the batch is clean) — same discipline as
    `reclog.py`'s `_validate_log_rows`: report every bad row at once, name
    the row index and the missing field(s), and tag the row with its title
    when one is present."""
    problems = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            problems.append(f"row {i}: expected a JSON object, got "
                            f"{type(r).__name__}")
            continue
        title = r.get("title")
        label = f'row {i} ("{title}")' if title else f"row {i}"
        missing = [f for f in UPSERT_REQUIRED_FIELDS if not r.get(f)]
        sources = r.get("sources")
        if not isinstance(sources, list) or len(sources) == 0:
            missing.append("sources")
        if missing:
            problems.append(f"{label}: missing required field(s): {', '.join(missing)}")
    return problems

def _fill_gaps(existing: dict, incoming: dict) -> dict:
    """Gap-fill merge: an incoming key with a non-empty value fills the
    slot only if the existing value for that key is missing/empty. An
    existing non-empty value is never overwritten — see the module
    docstring's "Upsert contract" for why this direction matters."""
    merged = dict(existing)
    for k, v in incoming.items():
        if v in EMPTY_VALUES:
            continue
        if merged.get(k) in EMPTY_VALUES:
            merged[k] = v
    return merged

def _find_match(con, kind, title, year, external_ids: dict) -> int | None:
    """Matching order: any shared `external_ids` (namespace, value) pair
    with an existing row, else exact `(kind, lower(title), year)`."""
    for ns, val in (external_ids or {}).items():
        if val in EMPTY_VALUES:
            continue
        row = con.execute(
            "SELECT cp.id FROM candidate_pool cp, json_each(cp.external_ids) je "
            "WHERE je.key = ? AND je.value = ? LIMIT 1", (ns, val)).fetchone()
        if row:
            return row["id"]
    if year is None:
        row = con.execute(
            "SELECT id FROM candidate_pool WHERE kind=? AND lower(title)=lower(?) "
            "AND year IS NULL", (kind, title)).fetchone()
    else:
        row = con.execute(
            "SELECT id FROM candidate_pool WHERE kind=? AND lower(title)=lower(?) "
            "AND year=?", (kind, title, year)).fetchone()
    return row["id"] if row else None

def _insert_row(con, row: dict, ts: str) -> None:
    con.execute(
        """INSERT INTO candidate_pool
           (kind, title, original_title, year, external_ids, tags,
            aggregates, shape, sources, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (row["kind"], row["title"], row.get("original_title") or "",
         row.get("year"),
         json.dumps(row.get("external_ids") or {}, ensure_ascii=False),
         json.dumps(row.get("tags") or [], ensure_ascii=False),
         json.dumps(row.get("aggregates") or {}, ensure_ascii=False),
         json.dumps(row.get("shape") or {}, ensure_ascii=False),
         json.dumps(row.get("sources") or [], ensure_ascii=False),
         ts, ts))

def _merge_row(con, match_id: int, row: dict, ts: str) -> None:
    existing = con.execute("SELECT * FROM candidate_pool WHERE id=?",
                           (match_id,)).fetchone()
    existing_tags = json.loads(existing["tags"] or "[]")
    existing_sources = json.loads(existing["sources"] or "[]")
    existing_dicts = {f: json.loads(existing[f] or "{}") for f in JSON_DICT_FIELDS}

    incoming_tags = row.get("tags") or []
    incoming_sources = row.get("sources") or []
    incoming_dicts = {f: (row.get(f) or {}) for f in JSON_DICT_FIELDS}

    merged_tags = sorted(set(existing_tags) | set(incoming_tags))
    merged_sources = existing_sources + incoming_sources
    merged_dicts = {f: _fill_gaps(existing_dicts[f], incoming_dicts[f])
                    for f in JSON_DICT_FIELDS}
    merged_original_title = existing["original_title"] or (row.get("original_title") or "")

    con.execute(
        """UPDATE candidate_pool
           SET tags=?, sources=?, external_ids=?, aggregates=?, shape=?,
               original_title=?, updated_at=?
           WHERE id=?""",
        (json.dumps(merged_tags, ensure_ascii=False),
         json.dumps(merged_sources, ensure_ascii=False),
         json.dumps(merged_dicts["external_ids"], ensure_ascii=False),
         json.dumps(merged_dicts["aggregates"], ensure_ascii=False),
         json.dumps(merged_dicts["shape"], ensure_ascii=False),
         merged_original_title, ts, match_id))

def cmd_upsert(con, args):
    rows = json.loads(open(args.json, encoding="utf-8").read())
    if not isinstance(rows, list):
        sys.exit("upsert --json expects a JSON list of candidate rows")
    problems = _validate_upsert_rows(rows)
    if problems:
        sys.exit("upsert --json batch failed validation, nothing inserted:\n"
                  + "\n".join(f"  - {p}" for p in problems))
    ts = now()
    inserted = merged = 0
    try:
        for row in rows:
            match_id = _find_match(con, row["kind"], row["title"],
                                   row.get("year"), row.get("external_ids") or {})
            if match_id is None:
                _insert_row(con, row, ts)
                inserted += 1
            else:
                _merge_row(con, match_id, row, ts)
                merged += 1
    except Exception:
        con.rollback()
        raise
    con.commit()
    print(json.dumps({"inserted": inserted, "merged": merged}))

# -------------------------------------------------------------- query

JSON_COLUMNS = ("external_ids", "tags", "aggregates", "shape", "sources")

def _row_out(row) -> dict:
    d = dict(row)
    for k in JSON_COLUMNS:
        try: d[k] = json.loads(d[k])
        except (TypeError, ValueError): pass
    if d.get("evidence"):
        try: d["evidence"] = json.loads(d["evidence"])
        except (TypeError, ValueError): pass
    return d

def cmd_query(con, args):
    where, params = [], []
    if not args.include_suppressed:
        where.append("suppressed = 0")
    if args.kind:
        where.append("kind = ?"); params.append(args.kind)
    if args.year_from is not None:
        where.append("year >= ?"); params.append(args.year_from)
    if args.year_to is not None:
        where.append("year <= ?"); params.append(args.year_to)
    if args.tag:
        clauses = []
        for t in args.tag:
            clauses.append("EXISTS (SELECT 1 FROM json_each(tags) WHERE value = ?)")
            params.append(t)
        where.append("(" + " OR ".join(clauses) + ")")
    if args.channel:
        clauses = []
        for c in args.channel:
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(sources) "
                "WHERE json_extract(value, '$.channel') = ?)")
            params.append(c)
        where.append("(" + " OR ".join(clauses) + ")")
    if args.needs_evidence:
        where.append("evidence IS NULL")
    if args.has_evidence:
        where.append("evidence IS NOT NULL")
    sql = "SELECT * FROM candidate_pool"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id"
    if args.limit is not None:
        sql += " LIMIT ?"; params.append(args.limit)
    try:
        rows = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        if "json_each" in str(e) or "no such function" in str(e):
            sys.exit("query needs SQLite's JSON1 extension for --tag/--channel "
                     f"filtering, which is unavailable in this Python build: {e}")
        raise
    print(json.dumps([_row_out(r) for r in rows], ensure_ascii=False))

# --------------------------------------------------------- attach-evidence

def cmd_attach_evidence(con, args):
    data = json.loads(open(args.json, encoding="utf-8").read())
    evidence = data.get("evidence") if isinstance(data, dict) else data
    ts = now()
    cur = con.execute(
        "UPDATE candidate_pool SET evidence=?, evidence_fetched_at=?, updated_at=? "
        "WHERE id=?",
        (json.dumps(evidence, ensure_ascii=False), ts, ts, args.id))
    con.commit()
    if cur.rowcount != 1:
        sys.exit(f"no candidate_pool row with id {args.id}")
    print("ok")

# ----------------------------------------------------------- suppress-sync

def cmd_suppress_sync(con, args):
    ts = now()

    # (a) watched/watching: pool rows whose external_ids overlap a work's
    # external_ids, where that work has a watched/watching record — OR
    # the row shares "show identity" with a watched/watching/wishlisted
    # TV season (see module docstring's "Season/parent asymmetry"): id
    # overlap against the season's meta.show_*_id first (stronger
    # evidence), base-title fallback (guarded by a real season family +
    # year) when the row carries no usable id.
    watched_pairs = {(r["namespace"], r["value"]) for r in con.execute("""
        SELECT DISTINCT e.namespace, e.value FROM external_ids e
        JOIN records rec ON rec.work_id = e.work_id
        WHERE rec.status IN ('watched','watching')""")}
    watched_show_titles, watched_show_ids, sibling_years = \
        _watched_season_identity(con)
    watched_pairs |= watched_show_ids

    watched_rec_pairs, watched_rec_tyk = set(), set()
    for rr in con.execute(
            "SELECT title, year, kind, external_ids FROM recommendations "
            "WHERE verdict='watched'"):
        watched_rec_pairs.update(json.loads(rr["external_ids"] or "{}").items())
        watched_rec_tyk.add((rr["kind"], (rr["title"] or "").lower(), rr["year"]))
    watched_pairs |= watched_rec_pairs

    open_rows = con.execute(
        "SELECT id, kind, title, year, external_ids FROM candidate_pool "
        "WHERE suppressed=0").fetchall()
    watched_ids = []
    for r in open_rows:
        own_ids = set(json.loads(r["external_ids"] or "{}").items())
        id_match = bool(own_ids & watched_pairs)
        title_match = False
        if not id_match:
            base = _strip_season_suffix(r["title"]) or r["title"]
            if base in watched_show_titles:
                family_years = sibling_years.get(base)
                title_match = bool(family_years) and \
                    (r["year"] is None or r["year"] in family_years)
        rec_match = (r["kind"], (r["title"] or "").lower(), r["year"]) \
            in watched_rec_tyk
        if id_match or title_match or rec_match:
            watched_ids.append(r["id"])
    if watched_ids:
        con.executemany(
            "UPDATE candidate_pool SET suppressed=1, suppressed_reason='watched', "
            "updated_at=? WHERE id=?", [(ts, i) for i in watched_ids])

    # (b) rejected: pool rows (still unsuppressed) matching a rejected
    # recommendations row, id-overlap else exact title+year+kind. Checked
    # after (a) commits its rows to `suppressed`, so a row qualifying for
    # both reasons is counted once, against 'watched'.
    rejected_pairs, rejected_tyk = set(), set()
    for rr in con.execute(
            "SELECT title, year, kind, external_ids FROM recommendations "
            "WHERE verdict='no'"):
        for ns, val in json.loads(rr["external_ids"] or "{}").items():
            rejected_pairs.add((ns, val))
        rejected_tyk.add((rr["kind"], (rr["title"] or "").lower(), rr["year"]))
    remaining_rows = con.execute(
        "SELECT id, kind, title, year, external_ids FROM candidate_pool "
        "WHERE suppressed=0").fetchall()
    rejected_ids = []
    for r in remaining_rows:
        ext = json.loads(r["external_ids"] or "{}")
        id_overlap = any((ns, val) in rejected_pairs for ns, val in ext.items())
        tyk_match = (r["kind"], (r["title"] or "").lower(), r["year"]) in rejected_tyk
        if id_overlap or tyk_match:
            rejected_ids.append(r["id"])
    if rejected_ids:
        con.executemany(
            "UPDATE candidate_pool SET suppressed=1, suppressed_reason='rejected', "
            "updated_at=? WHERE id=?", [(ts, i) for i in rejected_ids])

    con.commit()
    watched, rejected = len(watched_ids), len(rejected_ids)
    print(json.dumps({"suppressed": watched + rejected,
                      "watched": watched, "rejected": rejected}))

# -------------------------------------------------------------- stats

def cmd_stats(con, args):
    rows = con.execute(
        "SELECT kind, sources, suppressed, evidence FROM candidate_pool").fetchall()
    by_kind: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    evidence_cached = suppressed_count = 0
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        if r["suppressed"]:
            suppressed_count += 1
        if r["evidence"] is not None:
            evidence_cached += 1
        channels = {s.get("channel") for s in json.loads(r["sources"] or "[]")
                   if isinstance(s, dict) and s.get("channel")}
        for ch in channels:
            by_channel[ch] = by_channel.get(ch, 0) + 1
    print(json.dumps({
        "total": len(rows), "by_kind": by_kind,
        "evidence_cached": evidence_cached, "suppressed": suppressed_count,
        "by_channel": by_channel,
    }, ensure_ascii=False))

# ---------------------------------------------------------------- cli

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    s = sub.add_parser("upsert")
    s.add_argument("--json", required=True)

    s = sub.add_parser("query")
    s.add_argument("--kind")
    s.add_argument("--year-from", type=int, dest="year_from")
    s.add_argument("--year-to", type=int, dest="year_to")
    s.add_argument("--tag", action="append", help="repeatable, OR'd")
    s.add_argument("--channel", action="append", help="repeatable, OR'd")
    ev = s.add_mutually_exclusive_group()
    ev.add_argument("--needs-evidence", action="store_true")
    ev.add_argument("--has-evidence", action="store_true")
    s.add_argument("--limit", type=int)
    s.add_argument("--include-suppressed", action="store_true")

    s = sub.add_parser("attach-evidence")
    s.add_argument("--id", type=int, required=True)
    s.add_argument("--json", required=True)

    sub.add_parser("suppress-sync")
    sub.add_parser("stats")

    args = p.parse_args()
    con = connect(args.db)
    try:
        {"init": cmd_init, "upsert": cmd_upsert, "query": cmd_query,
         "attach-evidence": cmd_attach_evidence,
         "suppress-sync": cmd_suppress_sync, "stats": cmd_stats}[args.cmd](con, args)
    finally:
        con.close()

if __name__ == "__main__":
    main()
