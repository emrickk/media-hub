#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.32",
#   "beautifulsoup4>=4.12",
#   "lxml>=5.2",
#   "curl-cffi>=0.7",
# ]
# ///
"""
mediahub.py: one local database for a personal media library across services.

SQLite is the canonical store (media.db). Each service is an ingest source:

  ingest-douban      read a douban-export output directory (JSONL checkpoints)
  sync-letterboxd    scrape a public Letterboxd profile anonymously
  sync-plex          read a Plex server's libraries and watch state (read-only)
  enrich-douban      backfill IMDb ids for Douban films from subject pages
  resolve            cross-source entity resolution; report merges + conflicts
  stats              what's in the database
  report             films watched on one service but not another
  dump               export all tables to dumps/*.jsonl (backup / recovery)
  add                manual entry: rating/comment/status/quote for one work

Sibling scripts: load_clean.py (fold douban-export/Emrick-clean into the DB),
pull_weread_notes.py (WeRead highlights/notes -> annotations). See
ARCHITECTURE.md for the full system design.

Identity model: a `works` row is one canonical film/book/album/game/play.
Sources attach `external_ids` (douban/imdb/tmdb/letterboxd/plex) and
`records` (watched/wishlist/watching + rating + review, per source).
Nothing is ever auto-merged on a fuzzy match: exact external-id and exact
(normalized title, year) matches merge; near-misses land in `match_queue`
for review.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "media.db"

DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,             -- film|tv (one season)|show (series-level)|book|music|game|drama
    title TEXT NOT NULL,
    original_title TEXT DEFAULT '',
    year INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS external_ids (
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,        -- douban|imdb|tmdb|letterboxd|plex_guid
    value TEXT NOT NULL,
    UNIQUE(namespace, value)
);
CREATE INDEX IF NOT EXISTS idx_ext_work ON external_ids(work_id);
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    source TEXT NOT NULL,           -- douban|letterboxd|plex
    status TEXT NOT NULL,           -- watched|wishlist|watching
    rating REAL,                    -- normalized 0-10
    marked_at TEXT DEFAULT '',
    review TEXT DEFAULT '',
    raw TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(source, work_id, status)
);
CREATE INDEX IF NOT EXISTS idx_rec_work ON records(work_id);
CREATE TABLE IF NOT EXISTS work_aliases (
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    UNIQUE(work_id, alias)
);
CREATE TABLE IF NOT EXISTS match_queue (
    id INTEGER PRIMARY KEY,
    work_a INTEGER NOT NULL,
    work_b INTEGER NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',   -- pending|merged|rejected
    created_at TEXT NOT NULL,
    UNIQUE(work_a, work_b)
);
CREATE TABLE IF NOT EXISTS ryot_exported (
    work_id INTEGER PRIMARY KEY,
    exported_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    items INTEGER DEFAULT 0,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    source TEXT NOT NULL,           -- weread|manual|douban
    kind TEXT NOT NULL,             -- highlight|note|quote
    uid TEXT DEFAULT '',            -- source-native id (bookmarkId/reviewId) for idempotent re-pulls
    chapter TEXT DEFAULT '',
    location TEXT DEFAULT '',       -- source-native range/position string
    quote TEXT DEFAULT '',          -- the underlined/cited passage
    comment TEXT DEFAULT '',        -- Anping's thought on that passage
    created_at TEXT DEFAULT '',
    raw TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ann_work ON annotations(work_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ann_uid ON annotations(source, uid) WHERE uid != '';
CREATE TABLE IF NOT EXISTS suppressed_ids (
    namespace TEXT NOT NULL,        -- an id proven WRONG for this library:
    value TEXT NOT NULL,            -- _attach_externals refuses it forever,
    note TEXT DEFAULT '',           -- so loader re-runs can't resurrect it
    PRIMARY KEY(namespace, value)
);
CREATE TABLE IF NOT EXISTS covers (
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    file TEXT NOT NULL,             -- path relative to the AI Space root
    source TEXT NOT NULL,           -- douban|neodb|tmdb|steam|sgdb|weread|manual
    width INTEGER, height INTEGER, bytes INTEGER, sha1 TEXT,
    grade TEXT NOT NULL DEFAULT 'unverified',  -- good|low|placeholder|unverified
    preferred INTEGER NOT NULL DEFAULT 0,
    UNIQUE(work_id, file)
);
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    spotify_id TEXT UNIQUE,         -- spotify track id; the song-level entity key
    name TEXT NOT NULL,
    artists TEXT DEFAULT '',        -- display string, " / " joined
    album_spotify_id TEXT DEFAULT '',
    album_name TEXT DEFAULT '',
    work_id INTEGER REFERENCES works(id) ON DELETE SET NULL,  -- album work when identity-matched
    isrc TEXT DEFAULT '',           -- the recording-level canonical id
    duration_ms INTEGER,
    raw TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_work ON tracks(work_id);
CREATE INDEX IF NOT EXISTS idx_tracks_isrc ON tracks(isrc);
CREATE TABLE IF NOT EXISTS track_events (
    id INTEGER PRIMARY KEY,
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    source TEXT NOT NULL,           -- spotify|manual
    kind TEXT NOT NULL,             -- liked|playlist_add|play
    ts TEXT NOT NULL,               -- hearted/added/played at (UTC ISO)
    ms_played INTEGER,              -- play events only
    context TEXT DEFAULT '',        -- playlist name, platform, …
    uid TEXT DEFAULT '',            -- source-native idempotency key
    raw TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tev_uid ON track_events(source, kind, uid) WHERE uid != '';
CREATE INDEX IF NOT EXISTS idx_tev_track ON track_events(track_id);
CREATE TABLE IF NOT EXISTS playlists (
    spotify_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner TEXT DEFAULT '',
    is_own INTEGER NOT NULL DEFAULT 0,
    description TEXT DEFAULT '',
    snapshot_id TEXT DEFAULT '',
    raw TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
"""

# Columns added after the original schema shipped. open_db() applies these so
# any entry point (including older scripts importing this module) sees the
# full v2 shape without a separate migration step.
WORKS_COLUMNS = {
    "neodb_uuid": "TEXT",
    "cover_url": "TEXT",
    "season_number": "INTEGER",
    "title_en": "TEXT DEFAULT ''",   # english display title
    "creators": "TEXT DEFAULT ''",   # authors/directors/artists, display string
    "meta": "TEXT DEFAULT ''",       # kind-specific extras, JSON
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")  # enrichers commit concurrently
    conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    conn.executescript(SCHEMA)
    have = {r["name"] for r in conn.execute("PRAGMA table_info(works)")}
    for col, decl in WORKS_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE works ADD COLUMN {col} {decl}")
    conn.commit()
    return conn


# --------------------------------------------------------------------------
# Identity helpers
# --------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def norm_title(title: str) -> str:
    """Normalization key: NFKC, casefold, strip everything non-alphanumeric.
    CJK characters survive, so Chinese titles compare fine."""
    t = unicodedata.normalize("NFKC", title or "").casefold()
    return _PUNCT_RE.sub("", t)


def find_work_by_external(conn, namespace: str, value: str) -> int | None:
    row = conn.execute(
        "SELECT work_id FROM external_ids WHERE namespace=? AND value=?",
        (namespace, str(value)),
    ).fetchone()
    return row["work_id"] if row else None


def find_work_by_title_year(
    conn, kind: str, title: str, year: int | None, exclude_ns: dict[str, str] | None = None
) -> int | None:
    """Exact match on normalized title within kind; year must agree within 1
    when both sides have one (releases straddle year boundaries by region).

    exclude_ns: the incoming item's own external ids. A candidate work that
    already carries a DIFFERENT id in one of those same namespaces is a
    different item on the same platform (two same-titled albums, two editions
    of a book) and must never be merged with it.
    """
    key = norm_title(title)
    if not key:
        return None
    for row in conn.execute("SELECT id, title, original_title, year FROM works WHERE kind=?", (kind,)):
        if norm_title(row["title"]) == key or (
            row["original_title"] and norm_title(row["original_title"]) == key
        ):
            if year and row["year"] and abs(year - row["year"]) > 1:
                continue
            if exclude_ns and _has_conflicting_id(conn, row["id"], exclude_ns):
                continue
            return row["id"]
    return None


def _has_conflicting_id(conn, work_id: int, externals: dict[str, str]) -> bool:
    for ns, val in externals.items():
        if not val:
            continue
        row = conn.execute(
            "SELECT value FROM external_ids WHERE work_id=? AND namespace=?",
            (work_id, ns),
        ).fetchone()
        if row and row["value"] != str(val):
            return True
    return False


def upsert_work(
    conn,
    kind: str,
    title: str,
    year: int | None,
    externals: dict[str, str],
    original_title: str = "",
) -> int:
    """Find-or-create a work. External ids win; title+year is the fallback."""
    for ns, val in externals.items():
        if val:
            wid = find_work_by_external(conn, ns, val)
            if wid:
                _attach_externals(conn, wid, externals)
                _fill_gaps(conn, wid, year, original_title)
                return wid

    wid = find_work_by_title_year(conn, kind, title, year, exclude_ns=externals)
    if wid is None and original_title:
        wid = find_work_by_title_year(conn, kind, original_title, year, exclude_ns=externals)
    if wid:
        _attach_externals(conn, wid, externals)
        _fill_gaps(conn, wid, year, original_title)
        return wid

    cur = conn.execute(
        "INSERT INTO works(kind, title, original_title, year, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?)",
        (kind, title, original_title, year, now(), now()),
    )
    wid = cur.lastrowid
    _attach_externals(conn, wid, externals)
    return wid


def _attach_externals(conn, work_id: int, externals: dict[str, str]) -> None:
    for ns, val in externals.items():
        if not val:
            continue
        if conn.execute(
            "SELECT 1 FROM suppressed_ids WHERE namespace=? AND value=?", (ns, str(val))
        ).fetchone():
            continue  # proven wrong once; stays wrong across loader re-runs
        existing = find_work_by_external(conn, ns, val)
        if existing is None:
            conn.execute(
                "INSERT OR IGNORE INTO external_ids(work_id, namespace, value) VALUES(?,?,?)",
                (work_id, ns, str(val)),
            )
        elif existing != work_id:
            # Two works claim one identity: flag it, never guess.
            a, b = sorted((existing, work_id))
            conn.execute(
                "INSERT OR IGNORE INTO match_queue(work_a, work_b, reason, created_at)"
                " VALUES(?,?,?,?)",
                (a, b, f"external id conflict {ns}:{val}", now()),
            )


def _fill_gaps(conn, work_id: int, year: int | None, original_title: str) -> None:
    row = conn.execute("SELECT year, original_title FROM works WHERE id=?", (work_id,)).fetchone()
    if row is None:
        return
    if year and not row["year"]:
        conn.execute("UPDATE works SET year=?, updated_at=? WHERE id=?", (year, now(), work_id))
    if original_title and not row["original_title"]:
        conn.execute(
            "UPDATE works SET original_title=?, updated_at=? WHERE id=?",
            (original_title, now(), work_id),
        )


def upsert_record(
    conn,
    work_id: int,
    source: str,
    status: str,
    rating: float | None,
    marked_at: str,
    review: str,
    raw: dict | None = None,
) -> None:
    conn.execute(
        """INSERT INTO records(work_id, source, status, rating, marked_at, review, raw, updated_at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(source, work_id, status) DO UPDATE SET
             rating=excluded.rating, marked_at=excluded.marked_at,
             review=excluded.review, raw=excluded.raw, updated_at=excluded.updated_at""",
        (
            work_id,
            source,
            status,
            rating,
            marked_at or "",
            review or "",
            json.dumps(raw, ensure_ascii=False) if raw else "",
            now(),
        ),
    )


def log_run(conn, source: str, items: int, note: str = "") -> None:
    conn.execute(
        "INSERT INTO sync_runs(source, started_at, finished_at, items, note) VALUES(?,?,?,?,?)",
        (source, now(), now(), items, note),
    )
    conn.commit()


# --------------------------------------------------------------------------
# Douban ingest (from douban-export JSONL checkpoints)
# --------------------------------------------------------------------------

DOUBAN_STATUS = {"collect": "watched", "wish": "wishlist", "do": "watching"}


def year_of(rec: dict) -> int | None:
    for field in ("release_date", "intro"):
        m = re.search(r"(19|20)\d{2}", rec.get(field) or "")
        if m:
            return int(m.group(0))
    return None


def cmd_ingest_douban(args) -> int:
    src = Path(args.dir).expanduser().resolve()
    files = sorted(src.glob("*.jsonl"))
    if not files:
        print(f"no .jsonl files in {src}", file=sys.stderr)
        return 1
    conn = open_db()
    count = 0
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not rec.get("subject_id"):
                continue
            kind = rec.get("category") or "film"
            if kind == "movie":
                kind = "film"
            wid = upsert_work(
                conn,
                kind=kind,
                title=rec.get("title") or "",
                year=year_of(rec),
                externals={"douban": rec["subject_id"]},
                original_title=rec.get("subtitle") or "",
            )
            rating = float(rec["rating"]) * 2 if rec.get("rating") else None
            upsert_record(
                conn,
                wid,
                source="douban",
                status=DOUBAN_STATUS.get(rec.get("status", "collect"), "watched"),
                rating=rating,
                marked_at=rec.get("marked_at") or rec.get("rating_date") or "",
                review=rec.get("comment") or "",
                raw=rec,
            )
            count += 1
    conn.commit()
    log_run(conn, "douban", count, str(src))
    print(f"ingested {count} douban records from {len(files)} files")
    _print_stats(conn)
    return 0


# --------------------------------------------------------------------------
# Letterboxd (anonymous, public profiles)
# --------------------------------------------------------------------------


def polite_get(
    session,
    url: str,
    delay: tuple[float, float] = (1.0, 2.5),
    referer: str = "",
    tolerate: tuple[int, ...] = (),
):
    """Jittered GET that raises on HTTP errors except listed `tolerate` codes.
    Works with both requests and curl_cffi sessions."""
    time.sleep(random.uniform(*delay))
    headers = {"Referer": referer} if referer else {}
    resp = session.get(url, headers=headers, timeout=30)
    if resp.status_code not in tolerate:
        resp.raise_for_status()
    return resp


def lb_parse_grid(html: str) -> list[dict]:
    """Parse a Letterboxd poster grid page.

    Markup verified live 2026-07-27: each film is li.griditem holding a
    div.react-component with data-item-slug and data-item-name="Title (YYYY)".
    The user's rating is a span.rating with a rated-N class, N already 0-10.
    Returns [{slug, title, year|None, rating(0-10)|None}].
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    out = []
    for li in soup.select("li.griditem, li.poster-container"):
        poster = li.select_one("div[data-item-slug], div[data-film-slug]")
        if not poster:
            continue
        slug = poster.get("data-item-slug") or poster.get("data-film-slug") or ""
        if not slug:
            continue
        name = poster.get("data-item-name") or poster.get("data-item-full-display-name") or ""
        title, year = name, None
        m = re.match(r"^(.*)\s+\((\d{4})\)$", name)
        if m:
            title, year = m.group(1), int(m.group(2))
        rating = None
        rated = li.select_one('span.rating[class*="rated-"]')
        if rated:
            rm = re.search(r"rated-(\d+)", " ".join(rated.get("class") or []))
            if rm:
                rating = float(rm.group(1))
        out.append({"slug": slug, "title": title or slug.replace("-", " "), "year": year, "rating": rating})
    return out


def lb_next_page(html: str) -> bool:
    """True when the pagination block has a live (non-disabled) next link."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    return soup.select_one("div.pagination a.next[href]") is not None


def lb_session():
    """Letterboxd sits behind a Cloudflare TLS-fingerprint check: page 1 of a
    grid answers plain requests, but /page/2/ and the diary 403 them (verified
    2026-07-27). curl_cffi's Chrome impersonation passes it."""
    from curl_cffi import requests as cf

    return cf.Session(impersonate="chrome")


def lb_get(state: dict, url: str):
    """GET with Cloudflare-aware retries: a 403 occasionally shows up on a
    session's first contact; a fresh impersonated session clears it."""
    from curl_cffi.requests.exceptions import HTTPError as CfHTTPError

    for attempt in range(3):
        try:
            return polite_get(state["session"], url, tolerate=(404,))
        except CfHTTPError:
            if attempt == 2:
                raise
            wait = 5 * (attempt + 1)
            print(f"    ! challenge/{'error'} on {url}; new session, retry in {wait}s")
            time.sleep(wait)
            state["session"] = lb_session()


def cmd_sync_letterboxd(args) -> int:
    user = args.user
    state = {"session": lb_session()}
    conn = open_db()
    total = 0

    lists = [("films", "watched"), ("watchlist", "wishlist")]
    for path, status in lists:
        page = 1
        while True:
            # page 1 lives at the bare list URL; /page/N/ is the paginated form
            url = (
                f"https://letterboxd.com/{user}/{path}/"
                if page == 1
                else f"https://letterboxd.com/{user}/{path}/page/{page}/"
            )
            resp = lb_get(state, url)
            if resp.status_code == 404:
                if page == 1:
                    print(f"  ! {url} -> 404. Check the username (public profile required).")
                    return 1
                break
            entries = lb_parse_grid(resp.text)
            if not entries:
                break
            for e in entries:
                wid = upsert_work(
                    conn,
                    kind="film",
                    title=e["title"],
                    year=e["year"],
                    externals={"letterboxd": e["slug"]},
                )
                upsert_record(
                    conn, wid, source="letterboxd", status=status,
                    rating=e["rating"], marked_at="", review="", raw=e,
                )
                total += 1
            print(f"  {path} page {page}: {len(entries)} films")
            if not lb_next_page(resp.text):
                break
            page += 1
            if page > args.max_pages:
                print(f"  ! hit --max-pages={args.max_pages}")
                break

    # RSS: the latest ~50 watches carry watched dates, ratings, and TMDB ids —
    # data the grids don't have. Filter to guid prefix letterboxd-watch-.
    rss = lb_get(state, f"https://letterboxd.com/{user}/rss/")
    if rss.status_code == 200:
        total += _ingest_lb_rss(conn, rss.text)

    conn.commit()
    log_run(conn, "letterboxd", total, user)
    print(f"synced {total} letterboxd entries for {user}")
    _print_stats(conn)
    return 0


def _ingest_lb_rss(conn, xml_text: str) -> int:
    import xml.etree.ElementTree as ET

    NS = {"letterboxd": "https://letterboxd.com", "tmdb": "https://themoviedb.org"}
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        print("  ! RSS did not parse; skipping incremental layer")
        return 0
    n = 0
    for item in root.iter("item"):
        guid = (item.findtext("guid") or "")
        if not guid.startswith("letterboxd-watch-"):
            continue
        link = item.findtext("link") or ""
        m = re.search(r"/film/([^/]+)/", link)
        if not m:
            continue
        slug = m.group(1)
        title = item.findtext("letterboxd:filmTitle", default="", namespaces=NS) or slug
        year_s = item.findtext("letterboxd:filmYear", default="", namespaces=NS)
        watched = item.findtext("letterboxd:watchedDate", default="", namespaces=NS)
        rating_s = item.findtext("letterboxd:memberRating", default="", namespaces=NS)
        tmdb_id = item.findtext("tmdb:movieId", default="", namespaces=NS)
        wid = upsert_work(
            conn, kind="film", title=title,
            year=int(year_s) if year_s.isdigit() else None,
            externals={"letterboxd": slug, "tmdb_movie": tmdb_id},
        )
        upsert_record(
            conn, wid, source="letterboxd", status="watched",
            rating=float(rating_s) * 2 if rating_s else None,
            marked_at=watched, review="", raw={"guid": guid},
        )
        n += 1
    print(f"  rss: {n} recent watches (dates + tmdb ids)")
    return n


# --------------------------------------------------------------------------
# Plex (read-only)
# --------------------------------------------------------------------------


def plex_discover(token: str) -> str:
    """Find the user's server URL from the token alone via plex.tv resources."""
    import xml.etree.ElementTree as ET

    resp = requests.get(
        "https://plex.tv/api/resources",
        params={"includeHttps": 1, "includeRelay": 1, "X-Plex-Token": token},
        headers={"X-Plex-Client-Identifier": "media-hub", "X-Plex-Product": "media-hub"},
        timeout=30,
    )
    resp.raise_for_status()
    for device in ET.fromstring(resp.content).iter("Device"):
        if "server" not in (device.get("provides") or ""):
            continue
        conns = device.findall("Connection")
        # Prefer a local address; fall back to any (incl. relay) if none answers.
        for prefer_local in (True, False):
            for c in conns:
                if prefer_local and c.get("local") != "1":
                    continue
                uri = c.get("uri") or ""
                if not uri:
                    continue
                try:
                    ping = requests.get(
                        f"{uri}/identity", timeout=5,
                        headers={"X-Plex-Token": token}, verify=False,
                    )
                    if ping.status_code == 200:
                        return uri
                except requests.RequestException:
                    continue
    return ""


def _plex_guids(video, tmdb_ns: str = "tmdb_movie") -> dict[str, str]:
    """tmdb_ns: 'tmdb_movie' for movie sections, 'tmdb_tv' for shows — TMDB
    movie and tv ids share one number space, so the namespace carries type."""
    externals: dict[str, str] = {"plex_guid": video.get("guid") or ""}
    # New-agent libraries: <Guid id="imdb://tt..."/> children (needs includeGuids=1).
    for guid in video.iter("Guid"):
        gid = guid.get("id") or ""
        if gid.startswith("imdb://"):
            externals["imdb"] = gid[len("imdb://"):]
        elif gid.startswith("tmdb://"):
            externals[tmdb_ns] = gid[len("tmdb://"):]
    # Legacy agents encode the id in the guid attribute itself.
    legacy = re.match(r"com\.plexapp\.agents\.(imdb|themoviedb)://([^?]+)", externals["plex_guid"])
    if legacy:
        ns = "imdb" if legacy.group(1) == "imdb" else tmdb_ns
        externals.setdefault(ns, legacy.group(2))
    return externals


def cmd_sync_plex(args) -> int:
    import urllib3
    import xml.etree.ElementTree as ET

    urllib3.disable_warnings()  # local plex uses a self-signed *.plex.direct cert
    token = args.token
    base = (args.url or "").rstrip("/")
    if not base:
        print("no --url given; discovering server via plex.tv ...")
        base = plex_discover(token)
        if not base:
            print("  ! could not reach any of your servers; pass --url explicitly")
            return 1
        print(f"  using {base}")
    conn = open_db()
    session = requests.Session()
    session.headers["X-Plex-Token"] = token
    session.verify = False
    total = 0

    resp = session.get(f"{base}/library/sections", timeout=30)
    resp.raise_for_status()
    sections = ET.fromstring(resp.content)
    for directory in sections.iter("Directory"):
        sec_type = directory.get("type")
        if sec_type not in ("movie", "show"):
            continue
        key = directory.get("key")
        # Shows are show-level entities (kind 'show'), never per-season 'tv'
        # works: Douban seasons carry the 'tv' kind, and name-resolution must
        # not mix the two models.
        kind = "film" if sec_type == "movie" else "show"
        r = session.get(
            f"{base}/library/sections/{key}/all",
            params={"type": 1 if sec_type == "movie" else 2, "includeGuids": 1},
            timeout=120,
        )
        r.raise_for_status()
        for video in ET.fromstring(r.content).iter("Video" if sec_type == "movie" else "Directory"):
            title = video.get("title") or ""
            year = int(video.get("year")) if video.get("year") else None
            view_count = int(video.get("viewCount") or 0)
            wid = upsert_work(
                conn, kind=kind, title=title, year=year,
                externals=_plex_guids(video, "tmdb_movie" if kind == "film" else "tmdb_tv"),
            )
            rating = float(video.get("userRating")) if video.get("userRating") else None
            if view_count > 0 or rating is not None:
                last = video.get("lastViewedAt")
                marked = (
                    datetime.fromtimestamp(int(last), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    if last
                    else ""
                )
                upsert_record(
                    conn, wid, source="plex", status="watched",
                    rating=rating, marked_at=marked, review="",
                    raw={"ratingKey": video.get("ratingKey"), "viewCount": view_count},
                )
                total += 1
    conn.commit()
    log_run(conn, "plex", total, base)
    print(f"synced {total} watched/rated items from plex")
    _print_stats(conn)
    return 0


# --------------------------------------------------------------------------
# Douban enrichment via the mobile subject API
#
# The desktop subject page 302s to sec.douban.com for anonymous clients, but
# m.douban.com/rexxar/api/v2/movie/<id> answers anonymously (verified
# 2026-07-27) and carries original_title, authoritative year, is_tv, and an
# `aka` alias list. That is what lets a Chinese-titled Douban entry merge with
# its English-titled Letterboxd/Plex counterpart. (`imdb` exists in the payload
# but is null anonymously.)
# --------------------------------------------------------------------------

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)

_UNENRICHED_COUNT = """
SELECT COUNT(*) FROM works w
JOIN external_ids e ON e.work_id = w.id AND e.namespace='douban'
WHERE w.kind IN ('film','tv') AND w.original_title = ''
"""


def add_alias(conn, work_id: int, alias: str) -> None:
    alias = (alias or "").strip()
    if alias:
        conn.execute(
            "INSERT OR IGNORE INTO work_aliases(work_id, alias) VALUES(?,?)",
            (work_id, alias),
        )


def cmd_enrich_douban(args) -> int:
    conn = open_db()
    rows = conn.execute(
        """SELECT w.id, e.value AS douban_id, w.title FROM works w
           JOIN external_ids e ON e.work_id = w.id AND e.namespace='douban'
           WHERE w.kind IN ('film','tv') AND w.original_title = ''
           ORDER BY w.id LIMIT ?""",
        (args.limit,),
    ).fetchall()
    if not rows:
        print("nothing to enrich: every film/tv work already has an original_title")
        return 0

    session = requests.Session()
    session.headers.update({
        "User-Agent": MOBILE_UA,
        "Accept": "application/json, text/plain, */*",
    })
    hit = fail = streak = 0
    for row in rows:
        url = f"https://m.douban.com/rexxar/api/v2/movie/{row['douban_id']}?for_mobile=1"
        try:
            resp = polite_get(
                session, url, delay=(args.delay_min, args.delay_max),
                referer=f"https://m.douban.com/movie/subject/{row['douban_id']}/",
            )
            d = resp.json()
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            if code in (403, 302):
                print(f"  ! HTTP {code}: rate-limited; stopping (re-run later to resume)")
                break
            fail += 1
            streak += 1
            if streak >= 8:
                # Circuit breaker: 8 consecutive failures means Douban is
                # refusing us in some new way. Grinding on would be abuse.
                print(f"  ! {streak} consecutive failures (last: HTTP {code}); stopping")
                break
            continue
        except (requests.RequestException, ValueError):
            fail += 1
            streak += 1
            if streak >= 8:
                print(f"  ! {streak} consecutive failures; stopping")
                break
            continue
        streak = 0

        orig = (d.get("original_title") or "").strip()
        year = int(d["year"]) if str(d.get("year") or "").isdigit() else None
        conn.execute(
            "UPDATE works SET original_title=?, year=COALESCE(?, year), kind=?, updated_at=?"
            " WHERE id=?",
            (
                orig or row["title"],  # mark enriched even if douban has no orig title
                year,
                "tv" if d.get("is_tv") else "film",
                now(),
                row["id"],
            ),
        )
        for aka in d.get("aka") or []:
            add_alias(conn, row["id"], aka)
        if d.get("imdb"):  # null anonymously today, but take it if it appears
            _attach_externals(conn, row["id"], {"imdb": d["imdb"]})
        conn.commit()
        hit += 1
        if args.verbose or hit <= 10:
            print(f"  {row['title'][:22]:24} -> {orig[:34] or '(no orig)'} "
                  f"[{'tv' if d.get('is_tv') else 'film'} {year or '?'}]")
        elif hit % 50 == 0:
            print(f"  ... {hit}/{len(rows)}")
    conn.commit()
    remaining = conn.execute(_UNENRICHED_COUNT).fetchone()[0]
    log_run(conn, "enrich-douban", hit, f"{fail} failures, {remaining} remaining")
    print(f"enriched {hit}, failed {fail}, remaining: {remaining}")
    return 0


# --------------------------------------------------------------------------
# Resolution + reporting
# --------------------------------------------------------------------------


def _name_keys(conn, row) -> set[str]:
    """Every normalized name a work answers to: title, original title, aliases."""
    keys = {norm_title(row["title"]), norm_title(row["original_title"] or "")}
    for a in conn.execute("SELECT alias FROM work_aliases WHERE work_id=?", (row["id"],)):
        keys.add(norm_title(a["alias"]))
    keys.discard("")
    return keys


def cmd_resolve(args) -> int:
    """Cross-source entity resolution.

    Merges two works when they share a normalized name (title, original title,
    or alias), their years agree within 1 (or one side has no year), and they
    hold no conflicting ids in the same namespace. Same-name works whose years
    disagree by 2+ go to match_queue for review instead: that pattern is
    exactly what remakes look like, and remakes must never auto-merge.
    """
    conn = open_db()
    merged = queued = 0

    # Pre-pass: conflict-queue entries where two works claimed the same tmdb
    # id. For FILMS a shared tmdb id is proof of identity (the claim was
    # exact-title-verified against TMDB), and the year gap that queued them is
    # usually a China re-release date. TV stays queued: per-season Douban
    # entries legitimately share one TMDB series id and must not collapse.
    for q in conn.execute(
        """SELECT q.id, q.work_a, q.work_b FROM match_queue q
           JOIN works a ON a.id = q.work_a JOIN works b ON b.id = q.work_b
           WHERE q.state='pending' AND q.reason LIKE 'external id conflict tmdb:%'
             AND a.kind='film' AND b.kind='film'"""
    ).fetchall():
        # earlier merges in this same pass may have consumed either side
        alive = conn.execute(
            "SELECT COUNT(*) FROM works WHERE id IN (?,?)", (q["work_a"], q["work_b"])
        ).fetchone()[0]
        if alive != 2:
            conn.execute("UPDATE match_queue SET state='merged' WHERE id=?", (q["id"],))
            continue
        b_ids = {
            r["namespace"]: r["value"]
            for r in conn.execute(
                "SELECT namespace, value FROM external_ids WHERE work_id=?", (q["work_b"],)
            )
        }
        b_ids.pop("tmdb", None)  # the shared id is the merge reason, not a conflict
        if _has_conflicting_id(conn, q["work_a"], b_ids):
            continue
        keep, drop = sorted((q["work_a"], q["work_b"]))
        _merge_works(conn, keep, drop)
        conn.execute("UPDATE match_queue SET state='merged' WHERE id=?", (q["id"],))
        merged += 1
    conn.commit()

    changed = True
    while changed:  # merging can create new adjacencies; iterate to fixpoint
        changed = False
        rows = conn.execute(
            "SELECT id, kind, title, original_title, year FROM works"
            " WHERE kind IN ('film','tv') ORDER BY id"
        ).fetchall()
        by_name: dict[tuple[str, str], list] = {}
        for row in rows:
            for key in _name_keys(conn, row):
                by_name.setdefault((row["kind"], key), []).append(row)
        done: set[int] = set()
        for (_, _), group in by_name.items():
            if len(group) < 2:
                continue
            base = group[0]
            for other in group[1:]:
                if base["id"] in done or other["id"] in done or base["id"] == other["id"]:
                    continue
                ya, yb = base["year"], other["year"]
                other_ids = {
                    r["namespace"]: r["value"]
                    for r in conn.execute(
                        "SELECT namespace, value FROM external_ids WHERE work_id=?",
                        (other["id"],),
                    )
                }
                if _has_conflicting_id(conn, base["id"], other_ids):
                    continue
                if ya and yb and abs(ya - yb) > 1:
                    a, b = sorted((base["id"], other["id"]))
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO match_queue(work_a, work_b, reason, created_at)"
                        " VALUES(?,?,?,?)",
                        (a, b, f"same name, years {ya} vs {yb} (remake?)", now()),
                    )
                    queued += cur.rowcount
                    continue
                keep, drop = sorted((base["id"], other["id"]))
                _merge_works(conn, keep, drop)
                done.add(drop)
                merged += 1
                changed = True
        conn.commit()

    # Second pass: consume machine-resolvable queue entries. An "external id
    # conflict" pair whose two works hold no contradicting same-namespace ids
    # and whose years agree is the same title reached from two services (e.g.
    # a Chinese-titled Douban work and its English-titled Letterboxd twin
    # sharing one TMDB id): merge. Anything else stays for human review.
    for q in conn.execute(
        """SELECT q.id, q.work_a, q.work_b, a.year AS ya, b.year AS yb,
                  a.kind AS ka, b.kind AS kb
           FROM match_queue q
           JOIN works a ON a.id = q.work_a JOIN works b ON b.id = q.work_b
           WHERE q.state='pending' AND q.reason LIKE 'external id conflict%'"""
    ).fetchall():
        if q["ka"] != q["kb"]:
            continue
        # No year gate here: a shared provider id IS identity (both sides were
        # year-gated when the id was attached). Douban years are often the
        # China release, trailing the TMDB festival year by several years.
        b_ids = {
            r["namespace"]: r["value"]
            for r in conn.execute(
                "SELECT namespace, value FROM external_ids WHERE work_id=?", (q["work_b"],)
            )
        }
        if _has_conflicting_id(conn, q["work_a"], b_ids):
            continue
        keep, drop = sorted((q["work_a"], q["work_b"]))
        _merge_works(conn, keep, drop)
        conn.execute("UPDATE match_queue SET state='merged' WHERE id=?", (q["id"],))
        merged += 1
    conn.commit()

    pending = conn.execute("SELECT COUNT(*) FROM match_queue WHERE state='pending'").fetchone()[0]
    print(f"merged {merged} works; queued {queued} new; {pending} pending review in match_queue")
    if pending:
        for q in conn.execute(
            """SELECT q.id, q.reason, a.title AS ta, b.title AS tb
               FROM match_queue q JOIN works a ON a.id=q.work_a JOIN works b ON b.id=q.work_b
               WHERE q.state='pending' LIMIT 10"""
        ):
            print(f"  #{q['id']}: {q['ta'][:30]!r} vs {q['tb'][:30]!r} ({q['reason'][:44]})")
    _print_stats(conn)
    return 0


def _merge_works(conn, keep: int, drop: int) -> None:
    conn.execute("UPDATE OR IGNORE external_ids SET work_id=? WHERE work_id=?", (keep, drop))
    conn.execute("DELETE FROM external_ids WHERE work_id=?", (drop,))
    conn.execute("UPDATE OR IGNORE work_aliases SET work_id=? WHERE work_id=?", (keep, drop))
    conn.execute("DELETE FROM work_aliases WHERE work_id=?", (drop,))
    # Annotations and covers must FOLLOW the merge — the works row deletion
    # below cascades, and quotes/notes are the least replaceable data here.
    conn.execute("UPDATE OR IGNORE annotations SET work_id=? WHERE work_id=?", (keep, drop))
    conn.execute("DELETE FROM annotations WHERE work_id=?", (drop,))
    conn.execute("UPDATE OR IGNORE covers SET work_id=? WHERE work_id=?", (keep, drop))
    conn.execute("DELETE FROM covers WHERE work_id=?", (drop,))
    # Ryot export tracking must follow the merge, or the surviving work would
    # look never-exported and get re-imported (which duplicates history).
    conn.execute("UPDATE OR IGNORE ryot_exported SET work_id=? WHERE work_id=?", (keep, drop))
    conn.execute("DELETE FROM ryot_exported WHERE work_id=?", (drop,))
    # Queue rows referencing the dropped work are now moot.
    conn.execute(
        "UPDATE match_queue SET state='merged' WHERE state='pending' AND (work_a=? OR work_b=?)",
        (drop, drop),
    )
    # The dropped work's display title is still a name the merged work answers
    # to; keep it as an alias so later resolves can still find it.
    row = conn.execute("SELECT title FROM works WHERE id=?", (drop,)).fetchone()
    if row:
        add_alias(conn, keep, row["title"])
    # Records: move unless the same (source,status) already exists on keep.
    for rec in conn.execute("SELECT id, source, status FROM records WHERE work_id=?", (drop,)):
        clash = conn.execute(
            "SELECT 1 FROM records WHERE work_id=? AND source=? AND status=?",
            (keep, rec["source"], rec["status"]),
        ).fetchone()
        if clash:
            conn.execute("DELETE FROM records WHERE id=?", (rec["id"],))
        else:
            conn.execute("UPDATE records SET work_id=? WHERE id=?", (keep, rec["id"]))
    row = conn.execute("SELECT year, original_title FROM works WHERE id=?", (drop,)).fetchone()
    if row:
        _fill_gaps(conn, keep, row["year"], row["original_title"])
    conn.execute("DELETE FROM works WHERE id=?", (drop,))


def _print_stats(conn) -> None:
    print("\ndb state:")
    for row in conn.execute(
        "SELECT kind, COUNT(*) AS n FROM works GROUP BY kind ORDER BY n DESC"
    ):
        print(f"  works/{row['kind']:6} {row['n']:6}")
    for row in conn.execute(
        "SELECT source, status, COUNT(*) AS n FROM records GROUP BY source, status ORDER BY source, status"
    ):
        print(f"  {row['source']:10} {row['status']:9} {row['n']:6}")
    linked = conn.execute(
        """SELECT COUNT(DISTINCT work_id) FROM external_ids e
           WHERE EXISTS (SELECT 1 FROM external_ids o
                         WHERE o.work_id=e.work_id AND o.namespace != e.namespace)"""
    ).fetchone()[0]
    print(f"  works linked across 2+ id namespaces: {linked}")


def cmd_stats(args) -> int:
    conn = open_db()
    _print_stats(conn)
    print("\nrecent syncs:")
    for row in conn.execute(
        "SELECT source, started_at, items, note FROM sync_runs ORDER BY id DESC LIMIT 8"
    ):
        print(f"  {row['started_at']}  {row['source']:14} {row['items']:6}  {row['note'][:40]}")
    return 0


def _describe_work(conn, wid: int) -> str:
    w = conn.execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone()
    ids = ", ".join(
        f"{r['namespace']}:{r['value']}"
        for r in conn.execute(
            "SELECT namespace, value FROM external_ids WHERE work_id=? ORDER BY namespace", (wid,)
        )
    )
    year = f" ({w['year']})" if w["year"] else ""
    season = f" S{w['season_number']}" if w["season_number"] else ""
    return f"#{wid} [{w['kind']}] {w['title']}{season}{year}  <{ids or 'no external ids'}>"


# An id-shaped reference: 'imdb:tt0111161', 'douban:1292052', 'isbn:978...'.
# _resolve_work_ref and the add --create path must parse these identically.
_NS_REF_RE = re.compile(r"^([a-z_]+):(.+)$")


def _resolve_work_ref(conn, ref: str, kind: str = "") -> list[int]:
    """Resolve a human reference to work ids. Accepts '#123', 'namespace:value'
    (douban:123, imdb:tt0111161, steam:12250, weread:40726710, isbn:978...),
    or a title matched exactly (normalized) against title/original_title/
    title_en/aliases, optionally narrowed by kind."""
    ref = ref.strip()
    if ref.startswith("#") and ref[1:].isdigit():
        row = conn.execute("SELECT id FROM works WHERE id=?", (int(ref[1:]),)).fetchone()
        return [row["id"]] if row else []
    m = _NS_REF_RE.match(ref)
    if m:
        wid = find_work_by_external(conn, m.group(1), m.group(2))
        return [wid] if wid else []
    key = norm_title(ref)
    if not key:
        return []
    hits = []
    q = "SELECT id, title, original_title, title_en FROM works"
    params: tuple = ()
    if kind:
        q += " WHERE kind=?"
        params = (kind,)
    for row in conn.execute(q, params):
        names = {norm_title(row["title"]), norm_title(row["original_title"] or ""),
                 norm_title(row["title_en"] or "")}
        if key in names:
            hits.append(row["id"])
            continue
        if any(norm_title(a["alias"]) == key
               for a in conn.execute(
                   "SELECT alias FROM work_aliases WHERE work_id=?", (row["id"],))):
            hits.append(row["id"])
    return hits


def cmd_add(args) -> int:
    """Manual/conversational entry: Anping dictates a rating, comment, or a
    book quote with his thought; a Claude session (or he himself) records it
    here. Resolution is echoed before anything is written; ambiguity aborts.
    source='manual' outranks every scraped source in the resolved view."""
    conn = open_db()
    hits = _resolve_work_ref(conn, args.work, args.kind)
    wrote = []
    if not hits and args.create:
        if not args.kind:
            print("--create needs --kind (film|tv|show|book|music|game)")
            return 1
        # An id-shaped positional (namespace:value) is an identity, never a
        # display title: the id must land in external_ids and the title must
        # come from --title. Storing the raw id as a title made works
        # #5943-#5946 (fixed by hand 2026-07-28).
        externals: dict[str, str] = {}
        m = _NS_REF_RE.match(args.work.strip())
        if m:
            ns, val = m.group(1), m.group(2)
            if not args.title:
                print(f"--create with an id positional needs --title "
                      f"(refusing to store {args.work.strip()!r} as a title)")
                return 1
            if conn.execute(
                "SELECT 1 FROM suppressed_ids WHERE namespace=? AND value=?",
                (ns, val),
            ).fetchone():
                print(f"{ns}:{val} is in suppressed_ids (proven wrong for this"
                      " library); not creating")
                return 1
            if not conn.execute(
                "SELECT 1 FROM external_ids WHERE namespace=? LIMIT 1", (ns,)
            ).fetchone():
                print(f"  ! namespace {ns!r} never seen in external_ids — typo?")
            externals = {ns: val}
        pre_max = conn.execute("SELECT COALESCE(MAX(id), 0) FROM works").fetchone()[0]
        wid = upsert_work(conn, kind=args.kind, title=args.title or args.work,
                          year=args.year, externals=externals)
        # upsert_work may instead have matched an existing work by (title,
        # year) and attached the id to it; the echo must say which happened.
        is_new = wid > pre_max
        print(f"{'created new work' if is_new else 'attached id to existing work'}:"
              f" {_describe_work(conn, wid)}")
        wrote.append("new work" if is_new else "id attach")
        hits = [wid]
    if not hits:
        print(f"no work matches {args.work!r}"
              + (f" (kind={args.kind})" if args.kind else "")
              + " — refine the reference (try '#id' or 'douban:123'), or pass --create --kind")
        return 1
    if len(hits) > 1:
        print(f"ambiguous — {len(hits)} works match {args.work!r}:")
        for wid in hits[:10]:
            print(f"  {_describe_work(conn, wid)}")
        print("re-run with '#<id>'")
        return 1
    wid = hits[0]
    print(f"resolved: {_describe_work(conn, wid)}")

    if args.status or args.rating is not None or args.comment:
        status = args.status or "watched"
        upsert_record(
            conn, wid, source="manual", status=status,
            rating=args.rating,
            marked_at=args.marked or now()[:10],
            review=args.comment or "",
            raw=None,
        )
        wrote.append(
            f"record manual/{status}"
            + (f" rating={args.rating}/10" if args.rating is not None else "")
            + (" +comment" if args.comment else "")
        )
    if args.quote or args.note:
        conn.execute(
            """INSERT INTO annotations(work_id, source, kind, chapter, location,
                                       quote, comment, created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (wid, "manual", "quote" if args.quote else "note",
             args.chapter or "", args.location or "",
             args.quote or "", args.note or "", args.marked or now()),
        )
        wrote.append("annotation " + ("quote+note" if args.quote and args.note
                                      else "quote" if args.quote else "note"))
    if not wrote:
        print("nothing to write (dry resolution only — pass --status/--rating/"
              "--comment or --quote/--note)")
        return 0
    if args.dry_run:
        conn.rollback()
        print(f"dry-run: would write {', '.join(wrote)}")
        return 0
    conn.commit()
    log_run(conn, "manual", len(wrote), f"#{wid} " + "; ".join(wrote))
    print(f"wrote: {', '.join(wrote)}")
    return 0


def cmd_dump(args) -> int:
    """Export every table to dumps/<table>.jsonl — the recovery source of
    truth. media.db sits in iCloud-synced Documents where SQLite files can be
    corrupted by the sync daemon; the dumps diff cleanly and rebuild the DB."""
    conn = open_db()
    out = HERE / "dumps"
    out.mkdir(exist_ok=True)
    tables = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in sorted(tables):
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        path = out / f"{table}.jsonl"
        text = "\n".join(json.dumps(dict(r), ensure_ascii=False) for r in rows)
        text = text + "\n" if text else ""
        # write-only-if-changed: mass rewrites race the iCloud sync daemon
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
        print(f"  {table:16} {len(rows):6} rows -> {path.name}")
    return 0


def cmd_report(args) -> int:
    """Films watched on source A with no watched record on source B."""
    conn = open_db()
    a, b = args.only_on, args.missing_from
    rows = conn.execute(
        """SELECT w.title, w.year, r.rating, r.marked_at FROM works w
           JOIN records r ON r.work_id=w.id AND r.source=? AND r.status='watched'
           WHERE w.kind IN ('film','tv')
             AND NOT EXISTS (SELECT 1 FROM records o
                             WHERE o.work_id=w.id AND o.source=? AND o.status='watched')
           ORDER BY r.marked_at DESC""",
        (a, b),
    ).fetchall()
    print(f"watched on {a}, not on {b}: {len(rows)}")
    for row in rows[: args.limit]:
        y = f" ({row['year']})" if row["year"] else ""
        r = f"  [{row['rating']:.0f}/10]" if row["rating"] else ""
        print(f"  {row['marked_at'][:10]}  {row['title'][:40]}{y}{r}")
    if len(rows) > args.limit:
        print(f"  ... and {len(rows) - args.limit} more")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest-douban", help="ingest a douban-export output dir")
    s.add_argument("--dir", default=str(HERE.parent / "douban-export" / "Emrick"))
    s.set_defaults(fn=cmd_ingest_douban)

    s = sub.add_parser("sync-letterboxd", help="scrape a public letterboxd profile")
    s.add_argument("--user", required=True)
    s.add_argument("--max-pages", type=int, default=200)
    s.set_defaults(fn=cmd_sync_letterboxd)

    s = sub.add_parser("sync-plex", help="read watch state from a plex server")
    s.add_argument("--url", default="", help="e.g. http://192.168.1.10:32400 (omit to auto-discover via plex.tv)")
    s.add_argument("--token", required=True, help="X-Plex-Token")
    s.set_defaults(fn=cmd_sync_plex)

    s = sub.add_parser(
        "enrich-douban",
        help="backfill original titles/years/aliases from the douban mobile subject API",
    )
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--delay-min", type=float, default=2.0)
    s.add_argument("--delay-max", type=float, default=4.5)
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(fn=cmd_enrich_douban)

    s = sub.add_parser("resolve", help="merge duplicates, queue fuzzy matches")
    s.set_defaults(fn=cmd_resolve)

    s = sub.add_parser("stats", help="database summary")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("dump", help="export all tables to dumps/*.jsonl (backup)")
    s.set_defaults(fn=cmd_dump)

    s = sub.add_parser(
        "add",
        help="manual entry: rating/comment/status or a quote+thought on one work",
    )
    s.add_argument("work", help="'#id', 'namespace:value' (douban:.., imdb:tt.., steam:..), or exact title")
    s.add_argument("--kind", default="", choices=["", "film", "tv", "show", "book", "music", "game"])
    s.add_argument("--status", default="", choices=["", "watched", "watching", "wishlist", "owned"])
    s.add_argument("--rating", type=float, default=None, help="0-10 (5-star x2)")
    s.add_argument("--comment", default="", help="item-level review text")
    s.add_argument("--marked", default="", help="when it happened, YYYY-MM-DD (default today)")
    s.add_argument("--quote", default="", help="cited passage (books, or anything)")
    s.add_argument("--note", default="", help="thought attached to the quote, or standalone note")
    s.add_argument("--chapter", default="")
    s.add_argument("--location", default="")
    s.add_argument("--year", type=int, default=None, help="only used with --create")
    s.add_argument("--title", default="",
                   help="display title for --create; required when the positional is a namespace:value id")
    s.add_argument("--create", action="store_true",
                   help="create the work if not found (needs --kind; an id positional also needs --title)")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("report", help="watched on A but missing from B")
    s.add_argument("--only-on", required=True, choices=["douban", "letterboxd", "plex"])
    s.add_argument("--missing-from", required=True, choices=["douban", "letterboxd", "plex"])
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
