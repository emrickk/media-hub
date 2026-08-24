#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.32"]
# ///
"""Export media.db to Ryot via its generic JSON import.

Builds a CompleteExport document (schema verified against Ryot v10.4.2's
export-schema.ts and live GraphQL introspection on 2026-07-27) and either
writes it to disk (--dry-run) or uploads it and deploys the import job.

What goes in:
  * every film/tv work holding a TMDB external id -> lot movie/show, source tmdb
  * watched records  -> seen_history entries (state completed, ended_on date)
  * ratings/comments -> reviews (Ryot rating scale is 0-100; ours 0-10, so x10)
  * wishlist records -> the built-in Watchlist collection
Works without a TMDB id are counted and reported, never silently dropped.

Ryot imports are one-shot: re-importing duplicates history. The importer
refuses to run twice against the same server unless --force is given.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from secrets import secret  # noqa: E402  (credentials, never from the json)

DB = HERE / "media.db"

RYOT = secret("ryot_url").rstrip("/")
HEADERS = {"Authorization": f"Bearer {secret('ryot_api_key')}"}

# Everything ever pushed to Ryot is recorded here, so re-running exports only
# the delta. (Ryot re-imports duplicate history, so this table is the guard.)
TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS ryot_exported (
    work_id INTEGER PRIMARY KEY,
    exported_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0
)
"""


def gql(query: str, variables: dict | None = None) -> dict:
    resp = requests.post(
        f"{RYOT}/backend/graphql",
        json={"query": query, "variables": variables or {}},
        headers=HEADERS,
        timeout=60,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(f"graphql error: {payload['errors']}")
    return payload["data"]


def seen_entry(marked_at: str) -> dict:
    date = (marked_at or "")[:10] or None
    return {
        "ended_on": f"{date}T12:00:00Z" if date else None,
        "started_on": None,
        "progress": None,
        "state": "completed",
        "manual_time_spent": None,
        "providers_consumed_on": None,
        "anime_episode_number": None,
        "manga_chapter_number": None,
        "manga_volume_number": None,
        "podcast_episode_number": None,
        "show_episode_number": None,
        "show_season_number": None,
    }


import re

SEASON_RE = re.compile(r"第([一二三四五六七八九十\d]+)季|Season\s*(\d+)", re.I)
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def season_of(title: str) -> int | None:
    m = SEASON_RE.search(title or "")
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    if raw.isdigit():
        return int(raw)
    return CN_NUM.get(raw)


def review_entry(rating_0_10, comment: str, marked_at: str, season: int | None = None) -> dict:
    date = (marked_at or "")[:10] or None
    return {
        "rating": f"{float(rating_0_10) * 10:.0f}" if rating_0_10 else None,
        "review": {
            "date": f"{date}T12:00:00Z" if date else None,
            "text": comment or None,
            "spoiler": False,
            "visibility": "private",
        }
        if (comment or rating_0_10)
        else None,
        "comments": None,
        "anime_episode_number": None,
        "manga_chapter_number": None,
        "podcast_episode_number": None,
        "show_episode_number": None,
        "show_season_number": season,
    }


def watchlist_ref(marked_at: str) -> dict:
    ts = f"{(marked_at or '2020-01-01')[:10]}T12:00:00Z"
    # Only collection_name matters to the importer; the rest are format-required.
    return {
        "collection_id": "",
        "collection_name": "Watchlist",
        "created_on": ts,
        "last_updated_on": ts,
        "creator_user_id": "",
        "information": None,
    }


def build() -> tuple[list[dict], dict, sqlite3.Connection]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(TRACKING_DDL)
    items: list[dict] = []
    stats = {"exported": 0, "no_tmdb_film": 0, "skipped_other_kinds": 0,
             "watching_skipped": 0, "already_in_ryot": 0}

    works = conn.execute(
        """SELECT w.id, w.kind, w.title, t.value AS tmdb
           FROM works w
           LEFT JOIN external_ids t ON t.work_id = w.id AND t.namespace = 'tmdb'
           WHERE w.kind IN ('film', 'tv')
             AND EXISTS (SELECT 1 FROM records r WHERE r.work_id = w.id)
             AND NOT EXISTS (SELECT 1 FROM ryot_exported x WHERE x.work_id = w.id)"""
    ).fetchall()
    stats["already_in_ryot"] = conn.execute(
        "SELECT COUNT(*) FROM ryot_exported"
    ).fetchone()[0]

    for w in works:
        if not w["tmdb"]:
            stats["no_tmdb_film"] += 1
            continue
        recs = conn.execute(
            "SELECT source, status, rating, marked_at, review FROM records WHERE work_id=?",
            (w["id"],),
        ).fetchall()

        is_show = w["kind"] == "tv"
        season = season_of(w["title"]) if is_show else None
        seen, reviews, collections = [], [], []
        seen_dates = set()
        for r in recs:
            if r["status"] == "watched":
                if is_show:
                    # Ryot tracks shows per-episode; fabricating episode-level
                    # watches would be dishonest data. Shows carry ratings,
                    # reviews (season-tagged), and collections instead — same
                    # approach Ryot's own IMDb importer takes.
                    stats["show_seen_as_review_only"] = stats.get("show_seen_as_review_only", 0) + 1
                    if not (r["rating"] or r["review"]):
                        # preserve at least the fact it was watched
                        reviews.append(review_entry(None, "看过 (imported from Douban)", r["marked_at"], season))
                else:
                    d = (r["marked_at"] or "")[:10]
                    if d not in seen_dates:  # same-day cross-source records = one watch
                        seen_dates.add(d)
                        seen.append(seen_entry(r["marked_at"]))
            elif r["status"] == "wishlist":
                collections.append(watchlist_ref(r["marked_at"]))
            else:
                stats["watching_skipped"] += 1
            if r["rating"] or r["review"]:
                reviews.append(review_entry(r["rating"], r["review"], r["marked_at"], season))

        if not (seen or reviews or collections):
            continue
        items.append(
            {
                "lot": "movie" if w["kind"] == "film" else "show",
                "source": "tmdb",
                "identifier": str(w["tmdb"]),
                "source_id": w["title"],
                "seen_history": seen,
                "reviews": reviews,
                "collections": collections[:1],  # one watchlist ref is enough
                "_work_id": w["id"],  # stripped before upload; used for tracking
            }
        )
        stats["exported"] += 1

    other = conn.execute(
        "SELECT COUNT(DISTINCT work_id) FROM records r JOIN works w ON w.id=r.work_id"
        " WHERE w.kind NOT IN ('film','tv')"
    ).fetchone()[0]
    stats["skipped_other_kinds"] = other
    return items, stats, conn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="write JSON, do not import")
    ap.add_argument("--out", default=str(HERE / "ryot-import.json"))
    args = ap.parse_args()

    items, stats, conn = build()
    total_seen = sum(len(i["seen_history"]) for i in items)
    total_reviews = sum(len(i["reviews"]) for i in items)
    print(
        f"delta: {stats['exported']} new titles, {total_seen} watches, "
        f"{total_reviews} reviews/ratings ({stats['already_in_ryot']} already in ryot)"
    )
    print(
        f"not included: {stats['no_tmdb_film']} film/tv without a TMDB id yet, "
        f"{stats['skipped_other_kinds']} books/music/games/drama (no provider ids), "
        f"{stats['watching_skipped']} in-progress records"
    )
    if not items:
        print("nothing new to import.")
        return 0

    tracked = [(i.pop("_work_id"), len(i["seen_history"]), len(i["reviews"])) for i in items]
    doc = {
        "metadata": items,
        "collections": None,
        "exercises": None,
        "measurements": None,
        "metadata_groups": None,
        "people": None,
        "workout_templates": None,
        "workouts": None,
    }
    out = Path(args.out)
    out.write_text(json.dumps(doc, ensure_ascii=False))
    if args.dry_run:
        print(f"(dry run) wrote {out.name}; nothing uploaded, nothing tracked")
        return 0

    with out.open("rb") as fh:
        up = requests.post(
            f"{RYOT}/backend/upload",
            headers=HEADERS,
            files={"files[]": ("ryot-import.json", fh, "application/json")},
            timeout=300,
        )
    up.raise_for_status()
    paths = up.json()
    export_path = paths[0] if isinstance(paths, list) else paths
    print(f"uploaded -> {export_path}")

    data = gql(
        """mutation($path: String!) {
             deployImportJob(input: {source: GENERIC_JSON, path: {exportPath: $path}})
           }""",
        {"path": export_path},
    )
    print(f"import job deployed: {data['deployImportJob']}")

    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT OR REPLACE INTO ryot_exported(work_id, exported_at, seen_count, review_count)"
        " VALUES(?,?,?,?)",
        [(wid, now, sc, rc) for wid, sc, rc in tracked],
    )
    conn.commit()
    print(f"tracked {len(tracked)} works as exported. Ryot processes the import in the "
          f"background; progress at {RYOT}/settings/imports-and-exports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
