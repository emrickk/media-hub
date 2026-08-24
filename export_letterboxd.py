#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Export media.db films to Letterboxd import CSVs (ARCHITECTURE §5 output).

The 2026-07-28 reimport: Anping deleted the polluted Letterboxd account;
a fresh account gets seeded from the canonical DB. What goes out:

  * kind='film' works, one row each, facts from resolved.resolve_all
    (manual > douban > weread > letterboxd > plex precedence)
  * resolved watched  -> watched.csv (ratings+dates only, the §5 safe
    default) and watched-with-reviews.csv (adds the Douban 短评 as public
    Letterboxd reviews — Anping picks which file to upload)
  * resolved wishlist -> watchlist.csv (for the separate watchlist importer)
  * watched rows with neither tmdb_movie nor imdb id -> watched-noid.csv —
    Letterboxd's catalog is TMDB, so these documented negatives are
    title-match longshots; kept separate so the main file matches 1:1

Letterboxd-only works were originally HELD BACK pending the
lb-additions-review.html verdicts. Those verdicts were applied 2026-07-28
(sync_run #28: 32 watched kept, 141 mislogs deleted), so the survivors are
Anping-confirmed watches and export normally (counted in the report). The
letterboxd adapter is dead with the old account, so no unreviewed
letterboxd-only work can ever reappear.

Letterboxd matches by tmdbID first, then imdbID, then Title/Year.
WatchedDate empty = "mark watched, no diary date" (correct for films whose
only date is a douban 想看 — resolved.py already refuses that timestamp).
Read-only: never mutates the DB.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mediahub import open_db  # noqa: E402
from resolved import resolve_all  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "letterboxd-import"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fetch_films(conn):
    works = {
        r["id"]: dict(r)
        for r in conn.execute(
            "SELECT id, title, original_title, title_en, year FROM works WHERE kind='film'"
        )
    }
    ids: dict[int, dict[str, str]] = {}
    for r in conn.execute(
        "SELECT work_id, namespace, value FROM external_ids"
        " WHERE namespace IN ('tmdb_movie','imdb')"
    ):
        ids.setdefault(r["work_id"], {})[r["namespace"]] = r["value"]
    sources: dict[int, set[str]] = {}
    for r in conn.execute("SELECT DISTINCT work_id, source FROM records"):
        sources.setdefault(r["work_id"], set()).add(r["source"])
    return works, ids, sources


def row_for(w: dict, eids: dict, res: dict, with_review: bool) -> dict:
    title = w["original_title"] or w["title_en"] or w["title"]
    date = (res["marked_at"] or "")[:10]
    if date and not DATE_RE.match(date):
        print(f"  !! unparseable date {res['marked_at']!r} on #{w['id']} {title} — dropped date")
        date = ""
    rating = res["rating"]
    row = {
        "Title": title,
        "Year": w["year"] or "",
        "imdbID": eids.get("imdb", ""),
        "tmdbID": eids.get("tmdb_movie", ""),
        "WatchedDate": date,
        "Rating10": f"{rating:g}" if rating is not None else "",
    }
    if with_review:
        row["Review"] = res["review"] or ""
    return row


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    print(f"  wrote {path.name}: {len(rows)} rows")


def main() -> int:
    conn = open_db()
    resolved = resolve_all(conn)
    works, ids, sources = fetch_films(conn)

    watched, watched_noid, wishlist = [], [], []
    odd_status, no_record = [], []
    lb_only = 0
    for wid, w in sorted(works.items()):
        src = sources.get(wid)
        if not src:
            no_record.append(wid)
            continue
        if src == {"letterboxd"}:
            lb_only += 1
        res = resolved[wid]
        eids = ids.get(wid, {})
        row = row_for(w, eids, res, with_review=True)
        if res["status"] == "watched":
            (watched if row["imdbID"] or row["tmdbID"] else watched_noid).append(row)
        elif res["status"] == "wishlist":
            wishlist.append(row)
        else:
            odd_status.append((wid, res["status"]))

    # sanity gates (§4): unique ids, ratings in range, dates sane
    for ns in ("tmdbID", "imdbID"):
        seen: dict[str, str] = {}
        for r in watched + wishlist:
            v = r[ns]
            if v and v in seen:
                print(f"  !! duplicate {ns} {v}: {seen[v]!r} / {r['Title']!r}")
            seen[v] = r["Title"]
    for r in watched + watched_noid + wishlist:
        if r["Rating10"] and not 0 <= float(r["Rating10"]) <= 10:
            raise SystemExit(f"rating out of range: {r}")
        if r["WatchedDate"] and not "2000-01-01" <= r["WatchedDate"] <= "2026-12-31":
            print(f"  !! suspicious WatchedDate {r['WatchedDate']} on {r['Title']!r}")

    OUT.mkdir(exist_ok=True)
    base = ["Title", "Year", "imdbID", "tmdbID", "WatchedDate", "Rating10"]
    write_csv(OUT / "watched.csv", watched, base)
    write_csv(OUT / "watched-with-reviews.csv", watched, base + ["Review"])
    write_csv(OUT / "watched-noid.csv", watched_noid, base + ["Review"])
    write_csv(OUT / "watchlist.csv", wishlist, ["Title", "Year", "imdbID", "tmdbID"])

    dated = sum(1 for r in watched if r["WatchedDate"])
    rated = sum(1 for r in watched if r["Rating10"])
    reviewed = sum(1 for r in watched if r["Review"])
    print(
        f"\nwatched {len(watched)} (dated {dated}, rated {rated}, reviews {reviewed})"
        f" + noid {len(watched_noid)} | watchlist {len(wishlist)}"
        f" | lb-only verdict-confirmed included {lb_only}"
        f" | odd status {odd_status or 'none'} | recordless works {len(no_record)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
