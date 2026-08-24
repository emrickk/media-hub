#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=10", "requests>=2.32"]
# ///
"""Load the douban-export/Emrick-clean merged JSONs into media.db.

This is the bridge between the cleaning pipeline (douban-export/) and the
canonical store (media.db), per ARCHITECTURE.md. Idempotent: re-running
upserts the same facts. Never deletes user data; the only deletions are
empty husk works left over by the TV season split (no records, no ids).

What it does, in order:

1. movies/tv (all_clean.json, 1727 rows)
   - TV goes back to SEASON-LEVEL canon. merge_tv_seasons.py had collapsed
     seasons into series works for Ryot's one-entity-per-series model; that
     is an export concern, not canonical truth. Works holding several douban
     ids are split: each douban id gets its own season work, douban records
     are re-homed to their season via records.raw subject_id, and the shell
     keeps its letterboxd/plex identity (a show-level entity) if it has any.
   - identity/metadata upgrade per row: title_en, authoritative year,
     season_number, neodb uuid, directors, genres. Films attach imdb/tmdb
     external ids; TV seasons carry the show-level imdb tt and the series
     tmdb id in works.meta instead (attaching them as external ids would
     cross-link every season of a show — the season-tt gotcha).
   - douban records upserted from the row (status/rating/comment/marked_at),
     which also restores the per-season records the old merge dropped.

2. books (books_merged.json, 587 rows): douban + weread identity (douban id,
   isbn, weread book id), authors/translators/publisher, weread record with
   progress/hours/note-count in raw.

3. games (games_merged.json, 1114 rows): douban + steam appid + psn title id,
   steam/psn records with hours/trophies/last-played in raw.

4. covers: registers Emrick-clean/covers*/<entry id>.jpg into the covers
   table with dimensions/sha1/grade. iCloud " 2.jpg" conflict copies are
   ignored because lookup is by exact name.

Status vocabulary is the universal code set (records.status):
  watched   = done (看过/读过/玩过)
  watching  = in progress (在看/在读/在玩)
  wishlist  = wants to (想看/想读/想玩)
  owned     = in the library untouched (未读/库存)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mediahub import (  # noqa: E402
    _attach_externals,
    add_alias,
    find_work_by_external,
    log_run,
    now,
    open_db,
    upsert_record,
    upsert_work,
)

HERE = Path(__file__).resolve().parent
SPACE = HERE.parent
CLEAN = SPACE / "douban-export" / "Emrick-clean"

DOUBAN_STATUS = {"collect": "watched", "wish": "wishlist", "do": "watching"}
BOOK_STATUS = {"读过": "watched", "在读": "watching", "想读": "wishlist", "未读": "owned"}
GAME_STATUS = {"玩过": "watched", "在玩": "watching", "想玩": "wishlist", "库存": "owned"}

# douban_id -> (kind, season_number). Adjudicated corrections that upstream
# keeps getting wrong: NeoDB types these as Movie, so all_clean.json says
# media_type=movie and a plain re-run silently reverts the human decision
# (caught 2026-07-30, when the refresh flipped #663 back to film). Same intent
# as suppressed_ids: proven wrong once, stays corrected across loader re-runs.
KIND_OVERRIDES = {
    "36161391": ("tv", 3),   # 茶杯头大冒险 第三季 / The Cuphead Show! S3 — reclassified by Anping 2026-07-28
}

C = {  # run counters, printed at the end
    "works_created": 0, "works_updated": 0, "seasons_split": 0,
    "records_upserted": 0, "records_rehomed": 0, "husks_deleted": 0,
    "covers_registered": 0, "covers_missing": 0, "warnings": 0,
}


def warn(msg: str) -> None:
    C["warnings"] += 1
    print(f"  ! {msg}")


def rating10(v) -> float | None:
    """Douban 1-5 stars -> normalized 0-10."""
    try:
        return float(v) * 2 if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def set_work_fields(conn, wid: int, **fields) -> None:
    """Overwrite the given works columns (clean data is authoritative), but
    never blank an existing value with an empty one."""
    sets, vals = [], []
    for col, val in fields.items():
        if val in ("", None):
            continue
        sets.append(f"{col}=?")
        vals.append(val)
    if not sets:
        return
    vals += [now(), wid]
    conn.execute(f"UPDATE works SET {', '.join(sets)}, updated_at=? WHERE id=?", vals)
    C["works_updated"] += 1


# --------------------------------------------------------------------------
# movies / tv
# --------------------------------------------------------------------------


def douban_ids_of(conn, wid: int) -> list[str]:
    return [
        r["value"]
        for r in conn.execute(
            "SELECT value FROM external_ids WHERE work_id=? AND namespace='douban'", (wid,)
        )
    ]


def split_season(conn, shell_id: int, douban_id: str, row: dict) -> int:
    """Detach one season's douban id from a merged series work into a fresh
    season-level work. Records are re-homed in a later pass."""
    cur = conn.execute(
        "INSERT INTO works(kind, title, original_title, year, created_at, updated_at)"
        " VALUES('tv',?,?,?,?,?)",
        (row.get("title_zh") or row.get("orig_title") or "", row.get("orig_title") or "",
         row.get("year") or None, now(), now()),
    )
    wid = cur.lastrowid
    conn.execute(
        "UPDATE external_ids SET work_id=? WHERE namespace='douban' AND value=?",
        (wid, douban_id),
    )
    C["seasons_split"] += 1
    C["works_created"] += 1
    return wid


def load_movies(conn) -> int:
    rows = json.loads((CLEAN / "all_clean.json").read_text(encoding="utf-8"))
    # Works holding several douban ids are merged series shells. Detect them
    # BEFORE the loop: every season splits out — including the last one, so
    # the shell never masquerades as a season while keeping series-level ids
    # and letterboxd/plex records.
    shells = {
        r["work_id"]
        for r in conn.execute(
            "SELECT work_id FROM external_ids WHERE namespace='douban'"
            " GROUP BY work_id HAVING COUNT(*) > 1"
        )
    }
    for i, row in enumerate(rows):
        douban_id = str(row["douban_id"])
        kind = "tv" if row.get("media_type") == "tv" else "film"
        season_override = None
        if douban_id in KIND_OVERRIDES:
            kind, season_override = KIND_OVERRIDES[douban_id]
        neodb_uuid = (row.get("neodb_url") or "").rstrip("/").rsplit("/", 1)[-1] or ""

        wid = find_work_by_external(conn, "douban", douban_id)
        if wid is None:
            wid = upsert_work(
                conn, kind=kind, title=row.get("title_zh") or row.get("orig_title") or "",
                year=row.get("year") or None, externals={"douban": douban_id},
                original_title=row.get("orig_title") or "",
            )
            C["works_created"] += 1
        elif kind == "tv" and wid in shells:
            wid = split_season(conn, wid, douban_id, row)

        meta = {}
        externals = {"neodb": neodb_uuid}
        if douban_id in KIND_OVERRIDES:
            # Upstream has this row's TYPE wrong, so its imdb/tmdb fields are
            # untrustworthy too (#663's all_clean imdb is in suppressed_ids —
            # an arbitration already rejected it). Correct kind/season only;
            # leave identity to what previous adjudication settled.
            pass
        elif kind == "film":
            externals["imdb"] = row.get("imdb_id") or ""
            if row.get("tmdb_type") == "movie":
                # movie and tv ids share one number space — namespaces are typed
                externals["tmdb_movie"] = str(row.get("tmdb_id") or "")
        else:
            # show-level ids live in meta, never as external ids (season-tt gotcha)
            for k in ("imdb_id", "tmdb_type", "tmdb_id", "tmdb_url",
                      "show_title_zh", "show_title_en"):
                if row.get(k):
                    meta[f"show_{k}" if k.startswith(("imdb", "tmdb")) else k] = row[k]
        for k in ("genres", "origin_country"):
            if row.get(k):
                meta[k] = row[k]

        _attach_externals(conn, wid, externals)
        set_work_fields(
            conn, wid,
            kind=kind,
            title=row.get("title_zh") or "",
            original_title=row.get("orig_title") or "",
            title_en=row.get("title_en") or "",
            year=row.get("year") or None,
            season_number=season_override or row.get("season_number") or None,
            neodb_uuid=neodb_uuid,
            creators=row.get("directors") or "",
            meta=json.dumps(meta, ensure_ascii=False) if meta else "",
        )
        if row.get("title_en"):
            add_alias(conn, wid, row["title_en"])

        upsert_record(
            conn, wid, source="douban",
            status=DOUBAN_STATUS.get(row.get("status", "collect"), "watched"),
            rating=rating10(row.get("my_rating")),
            marked_at=row.get("marked_at") or "",
            review=row.get("my_comment") or "",
            raw={k: row[k] for k in ("douban_id", "status", "my_rating", "my_tags",
                                     "my_rating_date") if row.get(k)},
        )
        C["records_upserted"] += 1
        register_cover(conn, wid, CLEAN / "covers" / f"{douban_id}.jpg")
        if i % 200 == 0:
            conn.commit()
    conn.commit()
    return len(rows)


def rehome_douban_records(conn) -> None:
    """After the season split, douban records may sit on the old series shell.
    records.raw kept the original douban payload with subject_id: move each
    record to the work that now holds that douban id."""
    for rec in conn.execute(
        "SELECT id, work_id, source, status, raw FROM records WHERE source='douban'"
    ).fetchall():
        try:
            subject_id = str(json.loads(rec["raw"]).get("subject_id")
                             or json.loads(rec["raw"]).get("douban_id") or "")
        except (json.JSONDecodeError, AttributeError):
            continue
        if not subject_id:
            continue
        target = find_work_by_external(conn, "douban", subject_id)
        if target is None or target == rec["work_id"]:
            continue
        clash = conn.execute(
            "SELECT 1 FROM records WHERE work_id=? AND source=? AND status=?",
            (target, rec["source"], rec["status"]),
        ).fetchone()
        if clash:
            conn.execute("DELETE FROM records WHERE id=?", (rec["id"],))
        else:
            conn.execute("UPDATE records SET work_id=? WHERE id=?", (target, rec["id"]))
        C["records_rehomed"] += 1
    conn.commit()


def delete_husks(conn) -> None:
    """Works left with no identity and no facts after the split are shells of
    the old series model. Only these are ever deleted."""
    husks = conn.execute(
        """SELECT id, title FROM works w
           WHERE NOT EXISTS (SELECT 1 FROM external_ids e WHERE e.work_id=w.id)
             AND NOT EXISTS (SELECT 1 FROM records r WHERE r.work_id=w.id)
             AND NOT EXISTS (SELECT 1 FROM annotations a WHERE a.work_id=w.id)
             AND NOT EXISTS (SELECT 1 FROM covers c WHERE c.work_id=w.id)"""
    ).fetchall()
    for h in husks:
        conn.execute("DELETE FROM work_aliases WHERE work_id=?", (h["id"],))
        conn.execute("DELETE FROM ryot_exported WHERE work_id=?", (h["id"],))
        conn.execute(
            "UPDATE match_queue SET state='merged' WHERE state='pending'"
            " AND (work_a=? OR work_b=?)", (h["id"], h["id"]),
        )
        conn.execute("DELETE FROM works WHERE id=?", (h["id"],))
        C["husks_deleted"] += 1
    if husks:
        print(f"  removed {len(husks)} empty husk works (post-split shells)")
    conn.commit()


# --------------------------------------------------------------------------
# books
# --------------------------------------------------------------------------


def load_books(conn) -> int:
    rows = json.loads((CLEAN / "books_merged.json").read_text(encoding="utf-8"))
    for i, row in enumerate(rows):
        sources = row.get("sources") or []
        externals = {
            "douban": str(row["id"]) if "douban" in sources else "",
            "isbn": str(row.get("isbn") or ""),
            "weread": str(row.get("weread_book_id") or ""),
        }
        neodb_uuid = (row.get("neodb_url") or "").rstrip("/").rsplit("/", 1)[-1] or ""
        externals["neodb"] = neodb_uuid
        wid = upsert_work(
            conn, kind="book",
            title=row.get("title_zh") or row.get("orig_title") or "",
            year=row.get("pub_year") or None,
            externals=externals,
            original_title=row.get("orig_title") or "",
        )
        meta = {k: row[k] for k in ("translators", "pub_house") if row.get(k)}
        set_work_fields(
            conn, wid,
            title_en=row.get("title_en") or "",
            neodb_uuid=neodb_uuid,
            creators=row.get("authors") or "",
            meta=json.dumps(meta, ensure_ascii=False) if meta else "",
        )
        if "weread" in sources:
            upsert_record(
                conn, wid, source="weread",
                status=BOOK_STATUS.get(row.get("status", ""), "owned"),
                rating=None, marked_at="" if "douban" in sources else (row.get("marked_at") or ""),
                review="",
                raw={k: row[k] for k in ("weread_book_id", "weread_progress",
                                         "weread_reading_hours", "weread_notes")
                     if row.get(k) not in ("", None)},
            )
            C["records_upserted"] += 1
        register_cover(conn, wid, CLEAN / "covers-books" / f"{row['id']}.jpg")
        if i % 200 == 0:
            conn.commit()
    conn.commit()
    return len(rows)


# --------------------------------------------------------------------------
# games
# --------------------------------------------------------------------------


def load_games(conn) -> int:
    rows = json.loads((CLEAN / "games_merged.json").read_text(encoding="utf-8"))
    for i, row in enumerate(rows):
        sources = row.get("sources") or []
        year = row.get("year")
        year = int(year) if str(year or "").isdigit() else None
        # PSN identity: playhistory rows carry a title id; trophy-only rows
        # (psn_title_id empty) carry an NPWR trophy-set id in the merged id
        # ("pt" prefix) — also unique, also an anchor.
        rid = str(row["id"])
        psn_id = str(row.get("psn_title_id") or "")
        externals = {
            "douban": rid if "douban" in sources else "",
            "steam": str(row.get("steam_appid") or ""),
            "psn": psn_id,
            "psn_npwr": rid[2:] if not psn_id and rid.startswith("pt") else "",
        }
        wid = upsert_work(
            conn, kind="game",
            title=row.get("name_zh") or row.get("name_en") or "",
            year=year,
            externals=externals,
            original_title=row.get("name_en") or "",
        )
        meta = {k: row[k] for k in ("platforms", "igdb_slug") if row.get(k)}
        set_work_fields(
            conn, wid,
            title_en=row.get("name_en") or "",
            creators=row.get("developers") or "",
            meta=json.dumps(meta, ensure_ascii=False) if meta else "",
        )
        merged_status = GAME_STATUS.get(row.get("status", ""), "owned")
        if "steam" in sources:
            hours = float(row.get("steam_hours") or 0)
            upsert_record(
                conn, wid, source="steam",
                status="watched" if hours > 0 else ("wishlist" if merged_status == "wishlist" else "owned"),
                rating=None, marked_at="", review="",
                raw={k: row[k] for k in ("steam_appid", "steam_hours", "last_played")
                     if row.get(k) not in ("", None)},
            )
            C["records_upserted"] += 1
        if "psn" in sources:
            played = float(row.get("psn_hours") or 0) > 0 or int(row.get("psn_trophies") or 0) > 0
            upsert_record(
                conn, wid, source="psn",
                status="watched" if played else "owned",
                rating=None, marked_at="", review="",
                raw={k: row[k] for k in ("psn_title_id", "psn_hours", "psn_trophies",
                                         "last_played", "platforms") if row.get(k) not in ("", None)},
            )
            C["records_upserted"] += 1
        register_cover(conn, wid, CLEAN / "covers-games" / f"{row['id']}.jpg")
        if i % 200 == 0:
            conn.commit()
    conn.commit()
    return len(rows)


# --------------------------------------------------------------------------
# covers
# --------------------------------------------------------------------------


def register_cover(conn, wid: int, path: Path) -> None:
    if not path.exists():
        C["covers_missing"] += 1
        return
    from PIL import Image

    data = path.read_bytes()
    try:
        with Image.open(path) as im:
            width, height = im.size
    except Exception:
        warn(f"unreadable image {path.name}")
        return
    grade = "good" if height >= 600 else "low"
    conn.execute(
        """INSERT INTO covers(work_id, file, source, width, height, bytes, sha1, grade, preferred)
           VALUES(?,?,?,?,?,?,?,?,1)
           ON CONFLICT(work_id, file) DO UPDATE SET
             width=excluded.width, height=excluded.height, bytes=excluded.bytes,
             sha1=excluded.sha1, grade=excluded.grade""",
        (wid, str(path.relative_to(SPACE)), "import-v1", width, height,
         len(data), hashlib.sha1(data).hexdigest(), grade),
    )
    C["covers_registered"] += 1


# --------------------------------------------------------------------------


def main() -> int:
    for f in ("all_clean.json", "books_merged.json", "games_merged.json"):
        if not (CLEAN / f).exists():
            print(f"missing {CLEAN / f}", file=sys.stderr)
            return 1
    conn = open_db()
    n_movies = load_movies(conn)
    rehome_douban_records(conn)
    delete_husks(conn)
    n_books = load_books(conn)
    n_games = load_games(conn)
    total = n_movies + n_books + n_games
    log_run(conn, "load-clean", total,
            f"split {C['seasons_split']} seasons, {C['covers_registered']} covers")
    print(f"\nloaded {n_movies} movie/tv + {n_books} book + {n_games} game rows")
    for k, v in C.items():
        print(f"  {k:18} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
