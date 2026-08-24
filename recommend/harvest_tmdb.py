#!/usr/bin/env python3
"""harvest_tmdb.py: TMDB collaborative-filtering + recency harvest for the
candidate pool (v2 plan Task 2).

Why this exists: v1 hand-picked ~7 anchor titles per ask and invented
keyword queries — a probe showed keyword search is the weakest retrieval
surface while TMDB `/recommendations` (real collaborative filtering off
titles the user rated highly) is the strongest, 0% junk on a Breaking Bad
anchor. This harvester sweeps ALL anchors once, cheaply, raw-first, so the
result can be cached forever and re-used by every future ask instead of
re-derived per ask. Anchors are watched/watching works rated >=9 on the
0-10 scale (i.e. >=4.5 stars).

Three subcommands, run in this order:

`anchors --db PATH [--min-rating 9]`
    Read-only, single transaction, NO network. Returns one JSON row per
    (anchor work, tmdb namespace present) pair:
      {"work_id":.., "kind":.., "tmdb_id":.., "media":"movie"|"tv", "title":..}
    `media` comes from which external_ids namespace the work carries:
    tmdb_movie -> "movie", tmdb_tv -> "tv". A work with neither namespace
    is silently excluded (nothing to fetch) — this is why the TV lane
    yields far fewer rows than the film lane in the real DB (most TV
    anchors only carry a `douban` id; Douban CF is a separate harvester's
    job, not this one's). `kind` is passed through verbatim from
    `works.kind` (film/tv/show — NOT collapsed to two values, despite the
    interface doc's illustrative "film|tv").

`fetch --anchors FILE --raw-dir DIR [--pages 2] [--recency-months 18]`
    RAW-FIRST: every response is written to DIR verbatim (plus an injected
    `_meta` block — see below) before any transformation happens anywhere.
    `transform` depends entirely on these files and does no network I/O
    itself; that separation is what makes a harvest run reproducible and
    a transform re-runnable without re-fetching.

    For each anchor row, fetches `/{media}/{tmdb_id}/recommendations`
    for `--pages` pages -> `rec_<media>_<work_id>_p<page>.json`.
    Also fetches, once per run (not per anchor):
      - `/discover/movie` and `/discover/tv`, sorted by popularity, gated
        to titles released/aired in the last `--recency-months` months
        -> `discover_<media>_p<page>.json` (this is the "recency" half of
        the harvest — CF alone under-serves brand-new titles the user
        hasn't had a chance to rate anything similar to yet).
      - `/genre/movie/list` and `/genre/tv/list` -> `genres_movie.json` /
        `genres_tv.json` (genre id -> name maps; `transform` needs these
        because TMDB result rows only carry numeric `genre_ids`).

    Every non-genre file gets an injected `_meta` block —
    `{"channel": "tmdb_rec"|"tmdb_discover_recent", "anchor_work_id": W
    or null, "media": .., "fetched": "YYYY-MM-DD", "page": P}` — written
    into the saved JSON at fetch time. This is the ONLY place `transform`
    can learn which anchor (if any) produced a file; without it transform
    would have to guess from the filename, which is not a contract.

    TMDB_API_KEY is read from the `TMDB_API_KEY` env var first, else
    parsed out of `../douban-export/sources/sources.env` (resolved
    relative to this file, not the caller's cwd). The key is NEVER
    printed, logged, or embedded in a saved file or an error message —
    every URL that appears in `failed` entries or stdout has had its
    query string stripped.

    HTTP failures (timeout, non-200, bad JSON) are appended to the
    `failed` list and the run continues to the next target — a partial
    harvest is the expected, normal outcome of a large sweep, not a
    crash. Prints `{"fetched": n, "failed": [...]}` when done.

`transform --raw-dir DIR --out FILE`
    NO network. Reads every `*.json` file in DIR except the two genre
    files, requires a `_meta` block in each (a file with none is skipped
    with a stderr warning, not a crash — e.g. a raw file dropped there by
    hand, or a future channel this version doesn't understand), and turns
    every surviving TMDB result row into one pool-upsert batch row:
      kind (movie->film, tv->tv), title, original_title, year,
      external_ids ({"tmdb_movie": id} or {"tmdb_tv": id}, id as STRING —
      matches how `history.py`/`pool.py` store every other external id),
      tags (genre names, via the genre-list file for that media type),
      aggregates ({"tmdb_vote": vote_average, "tmdb_votes": vote_count}),
      sources ([{"channel":.., "anchor_work_id":.., "fetched":..}]).
    Candidates with vote_count < VOTE_FLOOR (50) are dropped — TMDB's
    catalog includes near-zero-vote titles whose vote_average is
    statistically meaningless (a single 9.9 from 3 voters), and the junk
    floor keeps them out of the pool entirely rather than letting a later
    stage try to filter them. The dropped count is reported on stdout
    alongside the candidate count. Output batch rows are NOT deduplicated
    against each other here — the same title recommended by two different
    anchors legitimately produces two rows in this file; `pool.py upsert`
    (a parallel task) is the merge point that unions their `sources` and
    `tags` by shared `external_ids`, in the same transaction, across the
    whole batch. Renaming or inventing fields here would silently break
    that contract, so don't.

This task does NOT do the real bulk harvest — that is a later plan task.
Only enough live calls to sanity-check the fetch path belong here.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

BUSY_TIMEOUT_MS = 15000
VOTE_FLOOR = 50
TMDB_BASE = "https://api.themoviedb.org/3"
ANCHOR_KINDS = ("film", "tv", "show")
ANCHOR_STATUSES = ("watched", "watching")
MEDIA_NAMESPACE = {"movie": "tmdb_movie", "tv": "tmdb_tv"}
GENRE_FILENAMES = {"movie": "genres_movie.json", "tv": "genres_tv.json"}

# --------------------------------------------------------------- anchors

def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    # Several agent sessions run against media.db concurrently; wait for a
    # competing writer's lock instead of erroring out immediately (same
    # convention as history.py/reclog.py). `anchors` never writes, but the
    # busy timeout still matters for the read lock.
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return con

def anchors(con: sqlite3.Connection, min_rating: float = 9.0) -> list[dict]:
    """One read transaction, no network. Every distinct work with a
    watched/watching record rated >= `min_rating` (0-10 scale), that ALSO
    carries a `tmdb_movie` or `tmdb_tv` external id — a work with neither
    is excluded, since there is nothing this harvester could fetch for
    it. A work carrying both namespaces (not expected in practice) yields
    two rows, one per media."""
    ph_kinds = ",".join("?" for _ in ANCHOR_KINDS)
    ph_status = ",".join("?" for _ in ANCHOR_STATUSES)
    con.execute("BEGIN")
    rated = con.execute(
        f"""SELECT DISTINCT w.id AS work_id, w.kind, w.title
            FROM works w JOIN records r ON r.work_id = w.id
            WHERE w.kind IN ({ph_kinds})
              AND r.status IN ({ph_status})
              AND r.rating >= ?
            ORDER BY w.id""",
        (*ANCHOR_KINDS, *ANCHOR_STATUSES, min_rating)).fetchall()
    work_ids = [r["work_id"] for r in rated]
    ext: dict[int, dict[str, str]] = {}
    if work_ids:
        ph_ids = ",".join("?" for _ in work_ids)
        for e in con.execute(
                f"""SELECT work_id, namespace, value FROM external_ids
                    WHERE namespace IN ('tmdb_movie','tmdb_tv')
                      AND work_id IN ({ph_ids})""", work_ids):
            ext.setdefault(e["work_id"], {})[e["namespace"]] = e["value"]
    con.execute("COMMIT")

    out = []
    for r in rated:
        ids = ext.get(r["work_id"], {})
        for namespace, media in (("tmdb_movie", "movie"), ("tmdb_tv", "tv")):
            if namespace in ids:
                out.append({"work_id": r["work_id"], "kind": r["kind"],
                            "tmdb_id": int(ids[namespace]), "media": media,
                            "title": r["title"]})
    return out

# ----------------------------------------------------------------- fetch

def _load_tmdb_key() -> str:
    """TMDB_API_KEY from the env, else parsed out of sources.env. Never
    logs the value — callers must not print whatever this returns."""
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if key:
        return key
    env_path = (Path(__file__).resolve().parent.parent.parent
                / "douban-export" / "sources" / "sources.env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("TMDB_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""

def _tmdb_get(path: str, key: str, params: dict, timeout: int = 20) -> dict:
    """GET one TMDB endpoint, api key in the query string per TMDB's v3
    auth. Raises on any failure (timeout, non-200, bad JSON) — the caller
    is responsible for catching, recording a SCRUBBED description (no
    query string — it carries the key) in `failed`, and continuing."""
    query = urllib.parse.urlencode({"api_key": key, **params})
    url = f"{TMDB_BASE}{path}?{query}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "media-hub-recommend/1.0 (+harvest_tmdb.py)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _months_ago(months: int, today: date | None = None) -> str:
    """ISO date `months` calendar months before `today` (default: today),
    clamping the day-of-month into the target month's real length (e.g.
    Aug 31 minus 6 months -> Feb 28/29, never Feb 31)."""
    today = today or date.today()
    total = today.year * 12 + (today.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()

def cmd_fetch(args) -> None:
    key = _load_tmdb_key()
    if not key:
        sys.exit("TMDB_API_KEY not found in env or "
                 "../douban-export/sources/sources.env")
    anchor_rows = json.loads(Path(args.anchors).read_text(encoding="utf-8"))
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    fetched_date = datetime.now().date().isoformat()
    fetched = 0
    failed: list[dict] = []

    def _save(name: str, data: dict) -> None:
        (raw_dir / name).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # Genre id -> name maps (transform needs these; TMDB result rows only
    # carry numeric genre_ids). No _meta needed — transform loads these
    # two files by fixed name, not by scanning for _meta.
    for media, fname in GENRE_FILENAMES.items():
        target = f"genre list media={media}"
        try:
            data = _tmdb_get(f"/genre/{media}/list", key, {})
        except Exception as e:
            failed.append({"target": target, "error": str(e)})
            continue
        _save(fname, data)
        fetched += 1

    # Per-anchor recommendations (the CF signal this harvester exists for).
    for a in anchor_rows:
        media, tmdb_id, work_id = a["media"], a["tmdb_id"], a["work_id"]
        for page in range(1, args.pages + 1):
            target = f"rec media={media} tmdb_id={tmdb_id} anchor={work_id} page={page}"
            try:
                data = _tmdb_get(f"/{media}/{tmdb_id}/recommendations", key,
                                 {"page": page})
            except Exception as e:
                failed.append({"target": target, "error": str(e)})
                continue
            data["_meta"] = {"channel": "tmdb_rec", "anchor_work_id": work_id,
                             "media": media, "fetched": fetched_date,
                             "page": page}
            _save(f"rec_{media}_{work_id}_p{page}.json", data)
            fetched += 1

    # Recency: recently released titles have too little watch history
    # anywhere to be CF-recommended yet, so they need a separate surface.
    date_field = {"movie": "primary_release_date", "tv": "first_air_date"}
    cutoff = _months_ago(args.recency_months)
    for media in ("movie", "tv"):
        for page in range(1, args.pages + 1):
            target = f"discover media={media} page={page}"
            params = {"sort_by": "popularity.desc", "page": page,
                      f"{date_field[media]}.gte": cutoff}
            try:
                data = _tmdb_get(f"/discover/{media}", key, params)
            except Exception as e:
                failed.append({"target": target, "error": str(e)})
                continue
            data["_meta"] = {"channel": "tmdb_discover_recent",
                             "anchor_work_id": None, "media": media,
                             "fetched": fetched_date, "page": page}
            _save(f"discover_{media}_p{page}.json", data)
            fetched += 1

    print(json.dumps({"fetched": fetched, "failed": failed}, ensure_ascii=False))

# ------------------------------------------------------------- transform

def _load_genre_maps(raw_dir: Path) -> dict[str, dict[int, str]]:
    maps: dict[str, dict[int, str]] = {}
    for media, fname in GENRE_FILENAMES.items():
        path = raw_dir / fname
        if not path.exists():
            maps[media] = {}
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        maps[media] = {g["id"]: g["name"] for g in data.get("genres", [])}
    return maps

def _year_of(date_str: str | None) -> int | None:
    if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        return int(date_str[:4])
    return None

def _candidate_from_result(res: dict, media: str, genre_map: dict,
                           source_entry: dict) -> dict:
    if media == "movie":
        title = res.get("title") or res.get("original_title") or ""
        original_title = res.get("original_title") or title
        year = _year_of(res.get("release_date"))
        kind = "film"
    else:
        title = res.get("name") or res.get("original_name") or ""
        original_title = res.get("original_name") or title
        year = _year_of(res.get("first_air_date"))
        kind = "tv"
    tags = [genre_map[gid] for gid in res.get("genre_ids", []) if gid in genre_map]
    return {
        "kind": kind,
        "title": title,
        "original_title": original_title,
        "year": year,
        "external_ids": {MEDIA_NAMESPACE[media]: str(res["id"])},
        "tags": tags,
        "aggregates": {"tmdb_vote": res.get("vote_average"),
                      "tmdb_votes": res.get("vote_count")},
        "sources": [source_entry],
    }

def transform(raw_dir: Path, vote_floor: int = VOTE_FLOOR):
    """Returns (candidates, dropped_vote_floor, skipped_filenames). See the
    module docstring for the full per-file contract."""
    genre_maps = _load_genre_maps(raw_dir)
    candidates: list[dict] = []
    dropped = 0
    skipped: list[str] = []

    for path in sorted(raw_dir.glob("*.json")):
        if path.name in GENRE_FILENAMES.values():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"warning: {path.name}: invalid JSON, skipped", file=sys.stderr)
            skipped.append(path.name)
            continue
        meta = data.get("_meta")
        if not meta:
            print(f"warning: {path.name}: no _meta block (transform has no "
                 f"other way to know which anchor/channel produced this "
                 f"file) — skipped", file=sys.stderr)
            skipped.append(path.name)
            continue
        media = meta.get("media")
        if media not in MEDIA_NAMESPACE:
            print(f"warning: {path.name}: _meta.media {media!r} is not "
                 f"'movie' or 'tv' — skipped", file=sys.stderr)
            skipped.append(path.name)
            continue

        genre_map = genre_maps.get(media, {})
        source_entry = {"channel": meta.get("channel"),
                        "anchor_work_id": meta.get("anchor_work_id"),
                        "fetched": meta.get("fetched")}
        for res in data.get("results", []):
            vote_count = res.get("vote_count") or 0
            if vote_count < vote_floor:
                dropped += 1
                continue
            candidates.append(_candidate_from_result(res, media, genre_map,
                                                      source_entry))

    return candidates, dropped, skipped

def cmd_transform(args) -> None:
    raw_dir = Path(args.raw_dir)
    candidates, dropped, skipped = transform(raw_dir)
    Path(args.out).write_text(
        json.dumps(candidates, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"candidates": len(candidates),
                      "dropped_vote_floor": dropped,
                      "skipped_files": skipped}, ensure_ascii=False))

# ------------------------------------------------------------------- cli

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("anchors", help="candidate anchor works, no network")
    s.add_argument("--db", required=True)
    s.add_argument("--min-rating", type=float, default=9.0)

    s = sub.add_parser("fetch", help="raw-first fetch of TMDB recs/discover/genres")
    s.add_argument("--anchors", required=True, help="JSON file from `anchors`")
    s.add_argument("--raw-dir", required=True)
    s.add_argument("--pages", type=int, default=2)
    s.add_argument("--recency-months", type=int, default=18)

    s = sub.add_parser("transform", help="raw files -> pool-upsert batch, no network")
    s.add_argument("--raw-dir", required=True)
    s.add_argument("--out", required=True)

    args = p.parse_args()

    if args.cmd == "anchors":
        con = _connect(args.db)
        try:
            rows = anchors(con, args.min_rating)
        finally:
            con.close()
        print(json.dumps(rows, ensure_ascii=False))
        return

    if args.cmd == "fetch":
        cmd_fetch(args)
        return

    if args.cmd == "transform":
        cmd_transform(args)
        return

if __name__ == "__main__":
    main()
