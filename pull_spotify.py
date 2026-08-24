#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.32",
# ]
# ///
"""
pull_spotify.py: Spotify adapter for media-hub.

Commands:

  uv run pull_spotify.py test
      Smoke-test SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET (from
      douban-export/sources/sources.env) via the client-credentials flow.
      Proves track metadata + ISRC access. No user consent involved.

  uv run pull_spotify.py auth
      One-time user consent (needed for Liked Songs / playlists — those are
      user-scoped). Opens the Spotify consent page in the default browser,
      catches the redirect on http://127.0.0.1:8899/callback, exchanges the
      code, and stores the refresh token in
      douban-export/sources/spotify_token.json (chmod 600).
      Prerequisite: that exact redirect URI must be registered in the app's
      settings on developer.spotify.com. Read-only scopes only.

  uv run pull_spotify.py library
      Pull the user library raw-first into sources/raw/spotify/<YYYY-MM-DD>/:
      Liked Songs, all playlists + their tracks, top artists/tracks
      (3 time ranges), followed artists, last-50 recently played.
      Prints a summary. Does NOT write to media.db (loader comes later,
      with the plays-schema decision).

  uv run pull_spotify.py ingest [path]
      Snapshot an Extended Streaming History export (ZIP or folder) into
      sources/raw/spotify/<YYYY-MM-DD>/ and print a summary. With no path,
      scans sources/raw/spotify/incoming/. Raw-first, idempotent, never
      overwrites (identical files skipped, differing get a -2 suffix).

  uv run pull_spotify.py load-plays [snapshot-dir]
      Load the snapshotted Streaming_History_{Audio,Video}_*.json plays into
      media.db track_events (kind='play'; schema decided 2026-07-29, see
      ARCHITECTURE §3). One row per stream; uid = "ts|track_id|ms_played"
      makes re-runs idempotent (partial unique index enforces it). context
      = platform; raw = slim JSON {rs,re,sh,sk,cc} — reason start/end,
      shuffle, skipped, country; NEVER the IP (that stays only in the raw
      snapshot). Unknown tracks get stub rows in `tracks` (ON CONFLICT DO
      NOTHING — never clobbers library/hydrated rows). Podcast/audiobook
      rows stay raw-only. Defaults to the newest snapshot dir.
      BACKUP media.db FIRST (this writes).

  uv run pull_spotify.py hydrate
      Batch-resolve tracks with empty ISRC via /v1/tracks (50 per call,
      client credentials). Tracks-only on purpose — album-UPC pulls and
      work matching belong to the music lane (load_spotify.py). Responses
      append to sources/raw/spotify/<today>/tracks_hydrated.jsonl
      (resume-safe checkpoint); on a hard 429 it saves progress and exits
      cleanly — just rerun later.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import http.server
import json
import os
import secrets as pysecrets
import subprocess
import sys
import time
import urllib.parse
import zipfile
from collections import Counter
from pathlib import Path

import requests

BASE = Path(__file__).parent
ENV_FILE = BASE.parent / "douban-export" / "sources" / "sources.env"
TOKEN_FILE = BASE.parent / "douban-export" / "sources" / "spotify_token.json"
RAW_DIR = BASE / "sources" / "raw" / "spotify"
INCOMING = RAW_DIR / "incoming"

TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTH_URL = "https://accounts.spotify.com/authorize"
API = "https://api.spotify.com/v1"


class RateLimited(Exception):
    """Raised when api_get exhausts its 429 retries; callers may cool down and resume."""
REDIRECT_URI = "http://127.0.0.1:8899/callback"
SCOPES = ("user-library-read playlist-read-private playlist-read-collaborative "
          "user-top-read user-follow-read user-read-recently-played")
# Spotify's own docs example track ("Cut To The Feeling" — Carly Rae Jepsen)
TEST_TRACK_ID = "11dFghVXANMlKmJXsNCbNl"


def load_env() -> dict[str, str]:
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def client_creds() -> tuple[str, str]:
    env = load_env()
    cid, secret = env.get("SPOTIFY_CLIENT_ID", ""), env.get("SPOTIFY_CLIENT_SECRET", "")
    if not cid or not secret or "PASTE_" in cid or "PASTE_" in secret:
        sys.exit("fill in SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in "
                 "douban-export/sources/sources.env first")
    return cid, secret


def basic_auth_header(cid: str, secret: str) -> dict[str, str]:
    return {"Authorization": "Basic "
            + base64.b64encode(f"{cid}:{secret}".encode()).decode()}


def get_token() -> str:
    """App-only token (client-credentials): metadata lookups, no user data."""
    cid, secret = client_creds()
    r = requests.post(TOKEN_URL, headers=basic_auth_header(cid, secret),
                      data={"grant_type": "client_credentials"}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"token request failed ({r.status_code}): {r.text[:200]}\n"
                 "-> check client ID/secret in sources.env")
    return r.json()["access_token"]


def user_token() -> str:
    """User token from the stored refresh token; auto-refreshes and re-saves."""
    if not TOKEN_FILE.exists():
        sys.exit("no user token yet — run `uv run pull_spotify.py auth` first")
    tok = json.loads(TOKEN_FILE.read_text())
    if tok.get("expires_at", 0) - 60 > time.time():
        return tok["access_token"]
    cid, secret = client_creds()
    r = requests.post(TOKEN_URL, headers=basic_auth_header(cid, secret),
                      data={"grant_type": "refresh_token",
                            "refresh_token": tok["refresh_token"]}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"token refresh failed ({r.status_code}): {r.text[:200]}\n"
                 "-> re-run `auth` (consent may have been revoked)")
    fresh = r.json()
    tok["access_token"] = fresh["access_token"]
    tok["expires_at"] = time.time() + fresh.get("expires_in", 3600)
    if fresh.get("refresh_token"):  # Spotify may rotate it
        tok["refresh_token"] = fresh["refresh_token"]
    save_token(tok)
    return tok["access_token"]


def save_token(tok: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(tok, indent=2))
    os.chmod(TOKEN_FILE, 0o600)


def api_get(token: str, path: str, params: dict | None = None,
            retries: int = 4, ok_codes: tuple = ()) -> dict | None:
    """GET api.spotify.com/v1<path>. Honors Retry-After on 429."""
    for attempt in range(retries):
        try:
            r = requests.get(f"{API}{path}", params=params,
                             headers={"Authorization": f"Bearer {token}"}, timeout=30)
        except requests.RequestException:
            # network blip (DNS drop, Wi-Fi sleep) — back off and retry
            time.sleep(min(15 * (attempt + 1), 120))
            continue
        if r.status_code == 429:
            # Retry-After when present; otherwise grow the wait per attempt
            wait = int(r.headers.get("Retry-After", str(10 * (attempt + 1))))
            time.sleep(min(wait + 1, 180))
            continue
        if r.status_code in ok_codes:
            return None
        r.raise_for_status()
        return r.json()
    raise RateLimited(f"retries exhausted ({retries}) on {path}")


def follow_pages(token: str, path: str, params: dict, key: str | None = None):
    """Yield items across Spotify's offset paging (follows body['next'])."""
    body = api_get(token, path, params)
    while True:
        node = body.get(key) if key else body
        yield from node.get("items", [])
        nxt = node.get("next")
        if not nxt:
            return
        time.sleep(0.15)
        body = api_get(token, nxt.removeprefix(API))


# ---------------------------------------------------------------- test

def cmd_test() -> int:
    token = get_token()
    print("token: OK (client-credentials flow)")
    t = api_get(token, f"/tracks/{TEST_TRACK_ID}")
    isrc = t.get("external_ids", {}).get("isrc", "?")
    print(f"track lookup: OK — {t['artists'][0]['name']} – {t['name']} "
          f"({t['album']['name']}, {t['album']['release_date'][:4]})")
    print(f"ISRC: {isrc}  <- this is the canonical-ID field hydrate will use")
    return 0


# ---------------------------------------------------------------- auth

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    captured: dict = {}

    def do_GET(self):  # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.captured = {k: v[0] for k, v in q.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<h2>Spotify consent received — you can close this tab. "
                         "Claude takes it from here.</h2>".encode())

    def log_message(self, *_):  # silence request logging
        pass


def cmd_auth() -> int:
    cid, secret = client_creds()
    state = pysecrets.token_urlsafe(16)
    params = urllib.parse.urlencode({
        "client_id": cid, "response_type": "code",
        "redirect_uri": REDIRECT_URI, "scope": SCOPES, "state": state,
    })
    url = f"{AUTH_URL}?{params}"
    srv = http.server.HTTPServer(("127.0.0.1", 8899), _CallbackHandler)
    srv.timeout = 5
    subprocess.run(["open", url], check=False)
    print("browser opened -> approve access on the Spotify page")
    print(f"(if no browser appeared, open this URL manually:\n{url})")
    deadline = time.time() + 300
    while time.time() < deadline and "code" not in _CallbackHandler.captured \
            and "error" not in _CallbackHandler.captured:
        srv.handle_request()
    srv.server_close()
    cap = _CallbackHandler.captured
    if cap.get("error"):
        sys.exit(f"consent denied/failed: {cap['error']}")
    if "code" not in cap:
        sys.exit("timed out waiting for consent (5 min) — run auth again")
    if cap.get("state") != state:
        sys.exit("state mismatch on callback — aborting (possible CSRF); run auth again")

    r = requests.post(TOKEN_URL, headers=basic_auth_header(cid, secret),
                      data={"grant_type": "authorization_code",
                            "code": cap["code"], "redirect_uri": REDIRECT_URI},
                      timeout=30)
    if r.status_code != 200:
        sys.exit(f"code exchange failed ({r.status_code}): {r.text[:300]}")
    tok = r.json()
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600)
    save_token(tok)
    me = api_get(tok["access_token"], "/me")
    print(f"authorized as: {me.get('display_name') or me.get('id')} "
          f"(scopes: {tok.get('scope', '')})")
    print(f"refresh token stored in {TOKEN_FILE} (0600)")
    return 0


# ---------------------------------------------------------------- library

def cmd_library() -> int:
    token = user_token()
    me = api_get(token, "/me")
    my_id = me.get("id", "")
    day_dir = RAW_DIR / datetime.date.today().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    print(f"pulling library for {me.get('display_name') or my_id} -> {day_dir}")

    def dump(name: str, rows: list[dict]) -> None:
        with (day_dir / name).open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Liked Songs ("hearted")
    liked = list(follow_pages(token, "/me/tracks", {"limit": 50}))
    dump("library_liked.jsonl", liked)
    added = sorted(x.get("added_at", "") for x in liked if x.get("added_at"))

    # Playlists + their tracks
    playlists = list(follow_pages(token, "/me/playlists", {"limit": 50}))
    dump("library_playlists.jsonl", playlists)
    pl_tracks: list[dict] = []
    pl_skipped: list[str] = []
    for pl in playlists:
        time.sleep(0.15)
        # Newer app generations get the renamed contract: playlist contents
        # live at /playlists/{id}/items and the legacy /tracks path 403s.
        # Try new first, legacy as fallback; skip-and-report if both refuse
        # (Spotify-owned editorial lists stay closed to dev-mode apps).
        rows: list[dict] = []
        got = False
        last_err = "?"
        for ep in ("items", "tracks"):
            rows.clear()
            try:
                for it in follow_pages(token, f"/playlists/{pl['id']}/{ep}",
                                       {"limit": 100}):
                    rows.append({"playlist_id": pl["id"],
                                 "playlist_name": pl.get("name", ""), "item": it})
                got = True
                break
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                last_err = f"HTTP {code}"
                if code not in (403, 404):
                    raise
        if got:
            pl_tracks.extend(rows)
        else:
            owner = (pl.get("owner") or {}).get("id", "?")
            pl_skipped.append(f"{pl.get('name', pl['id'])} (owner {owner}, {last_err})")
    dump("library_playlist_tracks.jsonl", pl_tracks)
    owned = [p for p in playlists if (p.get("owner") or {}).get("id") == my_id]

    # Top artists/tracks, all three time ranges (computed affinity — not history)
    top_rows: list[dict] = []
    for typ in ("artists", "tracks"):
        for rng in ("short_term", "medium_term", "long_term"):
            body = api_get(token, f"/me/top/{typ}",
                           {"time_range": rng, "limit": 50})
            for rank, item in enumerate(body.get("items", []), 1):
                top_rows.append({"type": typ, "range": rng, "rank": rank,
                                 "item": item})
            time.sleep(0.15)
    dump("library_top.jsonl", top_rows)

    # Followed artists (cursor paging)
    follows: list[dict] = []
    after = None
    while True:
        params = {"type": "artist", "limit": 50}
        if after:
            params["after"] = after
        body = api_get(token, "/me/following", params)
        node = body.get("artists", {})
        follows.extend(node.get("items", []))
        after = (node.get("cursors") or {}).get("after")
        if not after:
            break
        time.sleep(0.15)
    dump("library_following.jsonl", follows)

    # Recently played (API max: last 50 — the export is the real history)
    recent = api_get(token, "/me/player/recently-played", {"limit": 50})
    dump("library_recent.jsonl", recent.get("items", []))

    # Summary
    print(f"\nliked songs: {len(liked):,}"
          + (f"   (hearted {added[0][:10]} -> {added[-1][:10]})" if added else ""))
    print(f"playlists: {len(playlists)} ({len(owned)} owned by you, "
          f"{len(playlists) - len(owned)} followed) — {len(pl_tracks):,} tracks total")
    if pl_skipped:
        print(f"playlist contents unavailable via API ({len(pl_skipped)} skipped):")
        for s in pl_skipped:
            print(f"  - {s}")
    print(f"followed artists: {len(follows)}   recently played: "
          f"{len(recent.get('items', []))}")
    long_top = [r["item"]["name"] for r in top_rows
                if r["type"] == "artists" and r["range"] == "long_term"][:5]
    if long_top:
        print("top artists (long term): " + ", ".join(long_top))
    print(f"\nraw snapshot: {day_dir}")
    return 0


# ---------------------------------------------------------------- ingest

def find_history_files(path: Path) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Return ([(filename, content_bytes)], [notes]) from a ZIP, folder, or file."""
    found: list[tuple[str, bytes]] = []
    notes: list[str] = []

    def is_history(name: str) -> bool:
        base = Path(name).name
        return base.endswith(".json") and (
            base.startswith("Streaming_History_")   # extended export (audio + video)
            or base.startswith("StreamingHistory")  # basic account-data package
        )

    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if is_history(name):
                    found.append((Path(name).name, z.read(name)))
        if not found:
            notes.append(f"{path.name}: ZIP contains no streaming-history JSONs "
                         "(is this the right export?)")
    elif path.is_file() and is_history(path.name):
        found.append((path.name, path.read_bytes()))
    elif path.is_dir():
        for p in sorted(path.rglob("*.json")):
            if is_history(p.name):
                found.append((p.name, p.read_bytes()))
        for p in sorted(path.glob("*.zip")):
            sub, subnotes = find_history_files(p)
            found.extend(sub)
            notes.extend(subnotes)
    return found, notes


def snapshot(files: list[tuple[str, bytes]]) -> Path:
    """Copy verbatim into a dated immutable folder; skip identical, never overwrite."""
    day_dir = RAW_DIR / datetime.date.today().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    for name, blob in files:
        dest = day_dir / name
        if dest.exists():
            if hashlib.sha1(dest.read_bytes()).hexdigest() == hashlib.sha1(blob).hexdigest():
                print(f"  = {name} (already snapshotted, identical)")
                continue
            dest = day_dir / f"{dest.stem}-2{dest.suffix}"
        dest.write_bytes(blob)
        print(f"  + {dest.relative_to(RAW_DIR)} ({len(blob):,} bytes)")
    return day_dir


def summarize(files: list[tuple[str, bytes]]) -> None:
    plays = 0
    ms_total = 0
    podcast_plays = 0
    basic_rows = 0
    tracks: Counter[str] = Counter()
    artists_ms: Counter[str] = Counter()
    uris: set[str] = set()
    ts_min = ts_max = None

    for name, blob in files:
        try:
            rows = json.loads(blob)
        except json.JSONDecodeError:
            print(f"  ! {name}: not valid JSON, skipped")
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            ts = row.get("ts") or row.get("endTime")
            if ts:
                ts_min = ts if ts_min is None else min(ts_min, ts)
                ts_max = ts if ts_max is None else max(ts_max, ts)
            ms = row.get("ms_played", row.get("msPlayed", 0)) or 0
            if "ts" in row:  # extended format
                track = row.get("master_metadata_track_name")
                artist = row.get("master_metadata_album_artist_name")
                if track is None and row.get("episode_name"):
                    podcast_plays += 1
                    continue
                uri = row.get("spotify_track_uri")
                if uri:
                    uris.add(uri)
            else:  # basic format
                basic_rows += 1
                track = row.get("trackName")
                artist = row.get("artistName")
            plays += 1
            ms_total += ms
            if track and artist:
                tracks[f"{artist} – {track}"] += ms
                artists_ms[artist] += ms

    hours = ms_total / 3_600_000
    print(f"\nmusic plays: {plays:,}   podcast plays: {podcast_plays:,}"
          + (f"   (basic-format rows: {basic_rows:,} — no track URIs)" if basic_rows else ""))
    if ts_min:
        print(f"range: {ts_min[:10]} -> {ts_max[:10]}")
    print(f"listening time: {hours:,.0f} h   unique track URIs: {len(uris):,}   "
          f"unique artists: {len(artists_ms):,}")
    if artists_ms:
        print("\ntop 10 artists by time:")
        for artist, ms in artists_ms.most_common(10):
            print(f"  {ms/3_600_000:7.1f} h  {artist}")
    if tracks:
        print("\ntop 10 tracks by time:")
        for track, ms in tracks.most_common(10):
            print(f"  {ms/3_600_000:7.1f} h  {track}")


def cmd_ingest(arg: str | None) -> int:
    target = Path(arg).expanduser() if arg else INCOMING
    if not target.exists():
        sys.exit(f"nothing at {target} — drop the export ZIP into "
                 f"{INCOMING} or pass its path")
    files, notes = find_history_files(target)
    for n in notes:
        print(f"  ! {n}")
    if not files:
        sys.exit("no streaming-history JSONs found (expected "
                 "Streaming_History_Audio_*.json inside the export)")
    print(f"found {len(files)} history file(s); snapshotting:")
    day_dir = snapshot(files)
    summarize(files)
    print(f"\nraw snapshot: {day_dir}")
    print("next step (with Claude): decide the plays-table schema in "
          "ARCHITECTURE.md, then load + hydrate ISRCs.")
    return 0


# ------------------------------------------------- load-plays / hydrate

def latest_snapshot_dir() -> Path:
    days = sorted(d for d in RAW_DIR.iterdir()
                  if d.is_dir() and d.name.startswith("20"))
    if not days:
        sys.exit(f"no dated snapshots under {RAW_DIR} — run ingest first")
    return days[-1]


def cmd_load_plays(arg: str | None) -> int:
    sys.path.insert(0, str(BASE))
    import mediahub

    day_dir = Path(arg).expanduser() if arg else latest_snapshot_dir()
    # Video files too: music-video streams carry real spotify_track_uri rows
    files = sorted(day_dir.glob("Streaming_History_[AV]*.json"))
    if not files:
        sys.exit(f"no Streaming_History_*.json in {day_dir}")

    events: dict[str, tuple] = {}   # uid -> row; dict collapses exact repeats
    stubs: dict[str, tuple] = {}    # spotify_id -> (name, artists, album)
    n_podcast = n_nouri = n_dupe = 0
    for f in files:
        for r in json.loads(f.read_text()):
            uri = r.get("spotify_track_uri")
            if not uri:
                if r.get("spotify_episode_uri") or r.get("audiobook_uri"):
                    n_podcast += 1
                else:
                    n_nouri += 1
                continue
            sid = uri.rsplit(":", 1)[-1]
            ms = r.get("ms_played") or 0
            uid = f"{r['ts']}|{sid}|{ms}"
            if uid in events:
                n_dupe += 1
                continue
            slim = json.dumps(
                {"rs": r.get("reason_start"), "re": r.get("reason_end"),
                 "sh": r.get("shuffle"), "sk": r.get("skipped"),
                 "cc": r.get("conn_country")},
                ensure_ascii=False, separators=(",", ":"))
            events[uid] = (sid, r["ts"], ms, r.get("platform") or "", slim)
            if sid not in stubs:
                stubs[sid] = (r.get("master_metadata_track_name") or "",
                              r.get("master_metadata_album_artist_name") or "",
                              r.get("master_metadata_album_album_name") or "")

    conn = mediahub.open_db()
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_track_events_play_uid "
                 "ON track_events(uid) WHERE kind='play'")
    known = {row[0] for row in conn.execute(
        "SELECT spotify_id FROM tracks WHERE spotify_id IS NOT NULL")}
    new_stubs = [(sid, n, a, alb, mediahub.now())
                 for sid, (n, a, alb) in stubs.items() if sid not in known]
    conn.executemany(
        "INSERT INTO tracks(spotify_id, name, artists, album_name, updated_at)"
        " VALUES(?,?,?,?,?) ON CONFLICT(spotify_id) DO NOTHING", new_stubs)
    tid_of = {row[0]: row[1] for row in
              conn.execute("SELECT spotify_id, id FROM tracks")}
    have = {row[0] for row in conn.execute(
        "SELECT uid FROM track_events WHERE kind='play'")}
    rows = [(tid_of[sid], "spotify", "play", ts, ms, ctx, uid, slim)
            for uid, (sid, ts, ms, ctx, slim) in events.items()
            if uid not in have]
    conn.executemany(
        "INSERT INTO track_events(track_id, source, kind, ts, ms_played,"
        " context, uid, raw) VALUES(?,?,?,?,?,?,?,?)", rows)
    mediahub.log_run(conn, "spotify", len(rows),
                     f"streaming-history plays load ({day_dir.name}): "
                     f"{len(rows)} plays, {len(new_stubs)} stub tracks")
    print(f"plays loaded: {len(rows):,}   already present: "
          f"{len(events) - len(rows):,}   exact-dupe rows collapsed: {n_dupe:,}")
    print(f"stub tracks created: {len(new_stubs):,}")
    print(f"podcast/audiobook rows kept raw-only: {n_podcast:,}; "
          f"no-URI rows skipped: {n_nouri:,}")
    print("next: uv run pull_spotify.py hydrate  (fills ISRCs)")
    return 0


HYDRATE_UPDATE = ("UPDATE tracks SET name=?, artists=?, album_spotify_id=?,"
                  " album_name=?, isrc=?, duration_ms=?, updated_at=?"
                  " WHERE spotify_id=?")


def _hydrate_row(t: dict) -> tuple:
    alb = t.get("album") or {}
    return (t.get("name", ""),
            " / ".join(a.get("name", "") for a in t.get("artists") or []),
            alb.get("id", ""), alb.get("name", ""),
            (t.get("external_ids") or {}).get("isrc", ""),
            t.get("duration_ms"), None, t["id"])  # updated_at filled by caller


# Shared-quota mutex: the SAME lockfile spotify_music.py uses — every
# consumer of the client-creds app must hold it (two concurrent passes got
# the app banned for ~24h twice; see STATE.md concurrency rules).
QUOTA_LOCK = BASE.parent / "douban-export" / ".spotify_music.lock"


def acquire_quota_lock() -> None:
    if QUOTA_LOCK.exists():
        try:
            holder = json.loads(QUOTA_LOCK.read_text())
        except (OSError, ValueError):
            holder = {}
        pid = holder.get("pid")
        alive = False
        if isinstance(pid, int):
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        if alive:
            sys.exit(f"another spotify pass is running (pid {pid}, started "
                     f"{holder.get('started')}) — refusing to compete for "
                     "the shared quota.")
        print(f"clearing stale quota lock from dead pid {pid}")
        QUOTA_LOCK.unlink(missing_ok=True)
    QUOTA_LOCK.write_text(json.dumps(
        {"pid": os.getpid(), "started": time.strftime("%F %T"),
         "job": "pull_spotify hydrate"}))


def cmd_hydrate(replay_only: bool = False) -> int:
    sys.path.insert(0, str(BASE))
    import mediahub

    conn = mediahub.open_db()
    todo = [r[0] for r in conn.execute(
        "SELECT spotify_id FROM tracks"
        " WHERE isrc='' AND spotify_id IS NOT NULL ORDER BY id")]
    day_dir = RAW_DIR / datetime.date.today().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    outs = sorted(RAW_DIR.glob("20*/tracks_hydrated.jsonl"))
    out = day_dir / "tracks_hydrated.jsonl"
    if out not in outs:
        outs.append(out)
    # replay every checkpointed result whose DB update was lost (jsonl
    # flushes per line, commits every 50 — a killed run leaves a gap);
    # zero API calls, same durable-log idea as spotify_music.py --from-log
    empty = set(todo)
    done: set[str] = set()
    replay = 0
    for path in outs:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            try:
                t = json.loads(line)
                tid = t["id"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            done.add(tid)
            if tid in empty and not t.get("gone"):
                row = list(_hydrate_row(t))
                row[6] = mediahub.now()
                conn.execute(HYDRATE_UPDATE, row)
                replay += 1
    if replay:
        conn.commit()
        print(f"replayed {replay} checkpointed result(s) into tracks "
              "(no API calls)")
    todo = [t for t in todo if t not in done]
    if not todo:
        print("nothing to hydrate — every track has an ISRC or a checkpoint")
        return 0
    if replay_only:
        print(f"replay-only: {len(todo):,} ids still need API calls "
              "(rerun without --replay-only after the quota ban lifts)")
        return 0
    acquire_quota_lock()
    # single /tracks/{id} calls: the batch ?ids= endpoint returns 403 for
    # dev-mode apps (both app and user tokens; discovered 2026-07-29)
    print(f"hydrating {len(todo):,} track ids (single calls, checkpoint: {out.name})")
    token = get_token()
    n_ok = n_gone = 0
    try:
        with out.open("a", encoding="utf-8") as fh:
            for i, tid in enumerate(todo, 1):
                t = api_get(token, f"/tracks/{tid}", ok_codes=(400, 404))
                if not t or not t.get("id"):
                    n_gone += 1
                    fh.write(json.dumps({"id": tid, "gone": True}) + "\n")
                else:
                    fh.write(json.dumps(t, ensure_ascii=False) + "\n")
                    row = list(_hydrate_row(t))
                    row[6] = mediahub.now()
                    conn.execute(HYDRATE_UPDATE, row)
                    n_ok += 1
                if i % 50 == 0:
                    fh.flush()
                    conn.commit()
                if i % 500 == 0:
                    print(f"  {i:,}/{len(todo):,}", flush=True)
                # 1.6s: the shared client-creds app got banned twice at 1.0s
                # pacing (2026-07-28/29) — see STATE.md concurrency rules
                time.sleep(1.6)
    except RateLimited as exc:
        conn.commit()
        print(f"! rate-limited ({exc}); progress saved — rerun hydrate later")
    finally:
        QUOTA_LOCK.unlink(missing_ok=True)
    mediahub.log_run(conn, "spotify", n_ok,
                     f"track ISRC hydrate: {n_ok} resolved, {n_gone} gone/404")
    print(f"hydrated: {n_ok:,}   gone/unresolvable: {n_gone:,}   "
          f"remaining: {len(todo) - n_ok - n_gone:,}")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "test":
        return cmd_test()
    if cmd == "auth":
        return cmd_auth()
    if cmd == "library":
        return cmd_library()
    if cmd == "ingest":
        return cmd_ingest(sys.argv[2] if len(sys.argv) > 2 else None)
    if cmd == "load-plays":
        return cmd_load_plays(sys.argv[2] if len(sys.argv) > 2 else None)
    if cmd == "hydrate":
        return cmd_hydrate(replay_only="--replay-only" in sys.argv[2:])
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
