#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.32",
# ]
# ///
"""
load_spotify.py: load the Spotify library pull (raw JSONLs from
pull_spotify.py library) into media.db.

What it writes (all idempotent, never destructive):
  * playlists      — the 12 playlist entities
  * tracks         — one row per unique song (spotify track id key, ISRC kept)
  * track_events   — kind='liked' (hearted-at) and kind='playlist_add'
                     (added-at, playlist name in context). kind='play' is
                     reserved for the streaming-history export.
  * external_ids   — namespace 'spotify_album' attached to matched album
                     works, ONLY where corroborated by a barcode/UPC join
                     (Douban album barcode from music_clean.json == Spotify
                     album UPC). Name similarity never auto-links.
  * tracks.work_id — set for tracks whose album matched a music work.

Album UPCs come from a client-credentials hydration of every unique album id
seen in the pull (/albums, 20 per call), cached raw-first + resume-safe in
sources/raw/spotify/<day>/albums_hydrated.jsonl.

Usage:
  uv run load_spotify.py [--day YYYY-MM-DD] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

import mediahub
from pull_spotify import RAW_DIR, RateLimited, api_get, get_token

MUSIC_CLEAN = Path(__file__).parent.parent / "douban-export" / "Emrick-clean" / "music_clean.json"


def norm_barcode(v: str) -> str:
    """Digits only, leading zeros stripped (EAN-13 vs UPC-12 differ by a 0)."""
    d = "".join(c for c in str(v) if c.isdigit())
    return d.lstrip("0")


def latest_day_dir() -> Path:
    days = sorted(p for p in RAW_DIR.iterdir()
                  if p.is_dir() and p.name[:2] == "20")
    if not days:
        sys.exit(f"no dated pull under {RAW_DIR} — run pull_spotify.py library first")
    return days[-1]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def track_of(row: dict) -> dict | None:
    """Extract the track object from a liked row or playlist-item row."""
    node = row.get("item", row)
    t = node.get("item") or node.get("track")   # new contract: 'item'; legacy: 'track'
    if not isinstance(t, dict) or t.get("type") != "track" or not t.get("id"):
        return None                              # episodes, local files, removed tracks
    return t


def hydrate_albums(day_dir: Path, album_ids: list[str]) -> dict[str, dict]:
    """Fetch /albums for every id (20 per call), raw-first cached, resume-safe."""
    cache_path = day_dir / "albums_hydrated.jsonl"
    cache = {a["id"]: a for a in read_jsonl(cache_path)}
    todo = [a for a in album_ids if a not in cache]
    if todo:
        token = get_token()
        # batch /albums?ids= is 403-blocked for this app generation;
        # single /albums/{id} works — loop it, checkpointed per album.
        print(f"hydrating {len(todo)} albums one-by-one ({len(cache)} cached)")
        penalties = 0
        with cache_path.open("a", encoding="utf-8") as fh:
            for n, aid in enumerate(todo, 1):
                while True:
                    try:
                        alb = api_get(token, f"/albums/{aid}", retries=6,
                                      ok_codes=(403, 404))
                        break
                    except RateLimited:
                        # penalty box / network outage: cool down hard, resume
                        penalties += 1
                        if penalties > 12:
                            raise
                        print(f"  penalty #{penalties}: cooling down 600s "
                              f"(at {n}/{len(todo)})", flush=True)
                        time.sleep(600)
                        try:
                            token = get_token()  # may have expired meanwhile
                        except requests.RequestException:
                            pass  # network still down; next api_get retries cover it
                if isinstance(alb, dict) and alb.get("id"):
                    fh.write(json.dumps(alb, ensure_ascii=False) + "\n")
                    fh.flush()
                    cache[alb["id"]] = alb
                time.sleep(1.2)  # crawl: stay far under the rolling window
                if n % 100 == 0:
                    print(f"  {n}/{len(todo)}", flush=True)
    return cache


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-hydrate", action="store_true",
                    help="use only already-cached album hydrations (no network)")
    args = ap.parse_args()

    day_dir = RAW_DIR / args.day if args.day else latest_day_dir()
    if not day_dir.exists():
        sys.exit(f"no raw dir {day_dir}")
    print(f"loading from {day_dir}")

    liked = read_jsonl(day_dir / "library_liked.jsonl")
    pl_meta = read_jsonl(day_dir / "library_playlists.jsonl")
    pl_rows = read_jsonl(day_dir / "library_playlist_tracks.jsonl")

    conn = mediahub.open_db()

    # -- douban music works: barcode -> work_id ---------------------------
    barcode_to_work: dict[str, int] = {}
    douban_to_work: dict[str, int] = {}
    for r in conn.execute(
            "SELECT e.value douban_id, e.work_id FROM external_ids e "
            "JOIN works w ON w.id=e.work_id WHERE e.namespace='douban' AND w.kind='music'"):
        douban_to_work[r["douban_id"]] = r["work_id"]
    clean = json.loads(MUSIC_CLEAN.read_text()) if MUSIC_CLEAN.exists() else []
    for row in clean:
        bc = norm_barcode(row.get("barcode") or "")
        wid = douban_to_work.get(str(row.get("douban_id")))
        if bc and wid:
            barcode_to_work[bc] = wid
    print(f"douban music works: {len(douban_to_work)}; with barcode: {len(barcode_to_work)}")

    # -- collect unique tracks --------------------------------------------
    tracks: dict[str, dict] = {}
    skipped_items = 0
    for row in liked + pl_rows:
        t = track_of(row)
        if t is None:
            skipped_items += 1
            continue
        tracks.setdefault(t["id"], t)
    album_ids = sorted({t["album"]["id"] for t in tracks.values()
                        if (t.get("album") or {}).get("id")})
    print(f"unique tracks: {len(tracks)}   unique albums: {len(album_ids)}   "
          f"non-track items skipped: {skipped_items}")

    # -- hydrate albums for UPCs (client credentials; cached) --------------
    if args.no_hydrate:
        albums = {a["id"]: a for a in read_jsonl(day_dir / "albums_hydrated.jsonl")}
        missing = len([a for a in album_ids if a not in albums])
        print(f"--no-hydrate: cache only ({len(albums)} albums, {missing} not yet hydrated)")
    else:
        albums = hydrate_albums(day_dir, album_ids)
    album_work: dict[str, int] = {}          # album spotify id -> work_id
    for aid, alb in albums.items():
        upc = norm_barcode((alb.get("external_ids") or {}).get("upc") or "")
        if upc and upc in barcode_to_work:
            album_work[aid] = barcode_to_work[upc]
    print(f"albums hydrated: {len(albums)}; UPC-matched to douban works: {len(album_work)}")

    if args.dry_run:
        print("dry-run: no DB writes")
        return 0

    # -- playlists ----------------------------------------------------------
    # is_own: the account's own id = the most common owner among its lists
    # (he owns 10/12; a tie would only happen on a degenerate pull)
    owners = [(p.get("owner") or {}).get("id", "") for p in pl_meta]
    my_owner_id = max(set(owners), key=owners.count) if owners else ""
    for p in pl_meta:
        conn.execute(
            """INSERT INTO playlists(spotify_id, name, owner, is_own, description,
                                     snapshot_id, raw, updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(spotify_id) DO UPDATE SET name=excluded.name,
                 owner=excluded.owner, is_own=excluded.is_own,
                 description=excluded.description, snapshot_id=excluded.snapshot_id,
                 raw=excluded.raw, updated_at=excluded.updated_at""",
            (p["id"], p.get("name", ""), (p.get("owner") or {}).get("id", ""),
             1 if (p.get("owner") or {}).get("id", "") == my_owner_id else 0,
             p.get("description", "") or "", p.get("snapshot_id", ""),
             json.dumps(p, ensure_ascii=False), mediahub.now()))

    # -- tracks --------------------------------------------------------------
    for sid, t in tracks.items():
        alb = t.get("album") or {}
        conn.execute(
            """INSERT INTO tracks(spotify_id, name, artists, album_spotify_id,
                                  album_name, work_id, isrc, duration_ms, raw, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(spotify_id) DO UPDATE SET name=excluded.name,
                 artists=excluded.artists, album_spotify_id=excluded.album_spotify_id,
                 album_name=excluded.album_name,
                 work_id=COALESCE(excluded.work_id, tracks.work_id),
                 isrc=excluded.isrc, duration_ms=excluded.duration_ms,
                 raw=excluded.raw, updated_at=excluded.updated_at""",
            (sid, t.get("name", ""),
             " / ".join(a.get("name", "") for a in t.get("artists") or []),
             alb.get("id", ""), alb.get("name", ""),
             album_work.get(alb.get("id", "")),
             (t.get("external_ids") or {}).get("isrc", ""),
             t.get("duration_ms"), json.dumps(t, ensure_ascii=False), mediahub.now()))

    tid_of = {r["spotify_id"]: r["id"]
              for r in conn.execute("SELECT id, spotify_id FROM tracks")}

    # -- events: liked + playlist adds ---------------------------------------
    ev_liked = ev_pl = 0
    for row in liked:
        t = track_of(row)
        if t is None:
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO track_events(track_id, source, kind, ts, context, uid)
               VALUES(?,?,?,?,?,?)""",
            (tid_of[t["id"]], "spotify", "liked", row.get("added_at", ""), "", t["id"]))
        ev_liked += cur.rowcount
    for row in pl_rows:
        t = track_of(row)
        if t is None:
            continue
        node = row.get("item", {})
        uid = f'{row.get("playlist_id","")}:{t["id"]}:{node.get("added_at","")}'
        cur = conn.execute(
            """INSERT OR IGNORE INTO track_events(track_id, source, kind, ts, context, uid)
               VALUES(?,?,?,?,?,?)""",
            (tid_of[t["id"]], "spotify", "playlist_add", node.get("added_at", ""),
             row.get("playlist_name", ""), uid))
        ev_pl += cur.rowcount

    # -- attach spotify_album ids to matched works (barcode-corroborated) ----
    attached = 0
    for aid, wid in album_work.items():
        before = conn.execute("SELECT COUNT(*) c FROM external_ids WHERE namespace='spotify_album' AND value=?",
                              (aid,)).fetchone()["c"]
        mediahub._attach_externals(conn, wid, {"spotify_album": aid})
        after = conn.execute("SELECT COUNT(*) c FROM external_ids WHERE namespace='spotify_album' AND value=?",
                             (aid,)).fetchone()["c"]
        attached += after - before

    linked_tracks = conn.execute(
        "SELECT COUNT(*) c FROM tracks WHERE work_id IS NOT NULL").fetchone()["c"]
    mediahub.log_run(conn, "spotify",
                     items=len(tracks),
                     note=f"library load: {len(tracks)} tracks, {ev_liked} liked + "
                          f"{ev_pl} playlist events, {len(pl_meta)} playlists, "
                          f"{len(album_work)} albums UPC-linked, {attached} spotify_album ids attached")
    conn.commit()

    print(f"\ntracks upserted: {len(tracks):,} ({linked_tracks} linked to douban album works)")
    print(f"events inserted: {ev_liked} liked, {ev_pl} playlist adds (re-runs add 0)")
    print(f"playlists: {len(pl_meta)}   spotify_album ids attached: {attached}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
