#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.32", "beautifulsoup4>=4.12", "lxml>=5.2", "curl-cffi>=0.7", "pillow>=10"]
# ///
"""Cover pass: fill missing covers and upgrade low-grade ones (< 600px).

Targets (from the covers table + resolved display rule):
  * displayed works (any records) with NO cover row
  * works whose preferred cover is graded 'low'

Source ladder, cache-first (zero network when a cached asset suffices):
  film  : sources/raw/tmdb-posters/<tmdb_movie>.jpg (another session's cache)
          -> letterboxd film page og:image (pages cached at
             sources/raw/letterboxd-films/) -> themoviedb.org/movie page og:image
  show  : tmdb poster cache -> themoviedb.org/tv/<tmdb_tv> og:image -> lb page
  tv    : meta.show_tmdb_url (the season-specific TMDB page) og:image
  book  : weread /web/book/info cover (bookinfo-*.json cached for many), with
          the s_ -> t9_ upsize trick; needs the renewal session for uncached
  game  : steam library_600x900 portrait (cdn.cloudflare.steamstatic.com)

Acceptance: a new image replaces the old preferred cover only when it is
good (height >= 600) or meaningfully larger (> 1.3x the old height). New art
lands in media-hub/covers/<work_id>.jpg; the covers table row is upserted
preferred=1 and the old preferred demoted (kept as history). Resume-safe:
a work whose preferred cover is already 'good' is never touched.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import time
import random
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mediahub import DESKTOP_UA, lb_get, lb_session, log_run, open_db  # noqa: E402

HERE = Path(__file__).resolve().parent
SPACE = HERE.parent
COVDIR = HERE / "covers"
TMDB_POSTERS = HERE / "sources" / "raw" / "tmdb-posters"
LB_PAGES = HERE / "sources" / "raw" / "letterboxd-films"
TMDB_PAGES = HERE / "sources" / "raw" / "tmdb-pages" / datetime.now().strftime("%Y-%m-%d")
WEREAD_RAW = HERE / "sources" / "raw" / "weread"

OG_IMAGE_RE = re.compile(r'<meta property="og:image"\s+content="([^"]+)"')

C = {"filled": 0, "upgraded": 0, "skipped_no_source": 0, "rejected_small": 0, "errors": 0}


def http() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": DESKTOP_UA})
    return s


def polite():
    time.sleep(random.uniform(0.7, 1.5))


def cached_or_fetch_page(state, session, url: str, cache: Path) -> str:
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    polite()
    try:
        if "letterboxd.com" in url:
            resp = lb_get(state, url)
        else:
            resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            return ""
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(resp.text, encoding="utf-8")
        return resp.text
    except Exception:  # noqa: BLE001
        C["errors"] += 1
        return ""


def og_image(html: str) -> str:
    m = OG_IMAGE_RE.search(html or "")
    return m.group(1) if m else ""


def download(session, url: str) -> bytes | None:
    if not url:
        return None
    polite()
    try:
        resp = session.get(url, timeout=45)
        if resp.status_code == 200 and len(resp.content) > 4000:
            return resp.content
    except Exception:  # noqa: BLE001
        C["errors"] += 1
    return None


def dims(data: bytes) -> tuple[int, int]:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return (0, 0)


def lb_page_cached(slug: str) -> Path:
    # any dated cache dir may hold the page; prefer existing, else today's
    for d in sorted(LB_PAGES.glob("*/"), reverse=True):
        p = d / f"{slug}.html"
        if p.exists():
            return p
    return LB_PAGES / datetime.now().strftime("%Y-%m-%d") / f"{slug}.html"


def candidates_for(work, ids: dict, meta: dict, state, web, wr_session) -> list[tuple[str, object]]:
    """(source_label, bytes | url | callable) candidates, best first."""
    out: list[tuple[str, object]] = []
    kind = work["kind"]
    if kind in ("film", "show"):
        tmdb_id = ids.get("tmdb_movie") or ids.get("tmdb_tv") or ""
        if tmdb_id and (TMDB_POSTERS / f"{tmdb_id}.jpg").exists():
            out.append(("tmdb", (TMDB_POSTERS / f"{tmdb_id}.jpg").read_bytes()))
        slug = ids.get("letterboxd", "")
        if slug:
            html = cached_or_fetch_page(state, web, f"https://letterboxd.com/film/{slug}/",
                                        lb_page_cached(slug))
            url = og_image(html)
            if url and "empty-poster" not in url:
                out.append(("letterboxd", url))
        if tmdb_id:
            path = "movie" if ids.get("tmdb_movie") else "tv"
            html = cached_or_fetch_page(state, web,
                                        f"https://www.themoviedb.org/{path}/{tmdb_id}",
                                        TMDB_PAGES / f"{path}-{tmdb_id}.html")
            url = og_image(html)
            if url:
                out.append(("tmdb", url))
    elif kind == "tv":
        url_page = meta.get("show_tmdb_url", "")
        if url_page:
            key = url_page.rstrip("/").replace("https://www.themoviedb.org/", "").replace("/", "-")
            html = cached_or_fetch_page(state, web, url_page, TMDB_PAGES / f"{key}.html")
            url = og_image(html)
            if url:
                out.append(("tmdb", url))
    elif kind == "book":
        wid = ids.get("weread", "")
        if wid:
            info = None
            for d in sorted(WEREAD_RAW.glob("*/"), reverse=True):
                p = d / f"bookinfo-{wid}.json"
                if p.exists():
                    info = json.loads(p.read_text(encoding="utf-8"))
                    break
            if info is None and wr_session is not None:
                try:
                    from pull_weread_notes import get_json
                    info = get_json(wr_session, "/web/book/info", {"bookId": wid})
                    p = WEREAD_RAW / datetime.now().strftime("%Y-%m-%d") / f"bookinfo-{wid}.json"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
                except SystemExit:
                    raise
                except Exception:  # noqa: BLE001
                    C["errors"] += 1
            cover = (info or {}).get("cover") or ""
            if cover:
                # weread serves size variants by prefix; t9_ is the large one
                for variant in (cover.replace("/s_", "/t9_"), cover.replace("/s_", "/t7_"), cover):
                    if variant not in [u for _, u in out]:
                        out.append(("weread", variant))
    elif kind == "game":
        appid = ids.get("steam", "")
        if appid:
            out.append(("steam",
                        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg"))
            out.append(("steam",
                        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"))
    return out


def main() -> int:
    conn = open_db()
    COVDIR.mkdir(exist_ok=True)
    state = {"session": lb_session()}
    web = http()
    wr_session = None  # lazily created only if an uncached weread cover is needed

    targets = conn.execute(
        """SELECT w.*, c.height AS old_h, c.file AS old_file FROM works w
           LEFT JOIN covers c ON c.work_id=w.id AND c.preferred=1
           WHERE w.kind IN ('film','tv','show','book','game')
             AND EXISTS (SELECT 1 FROM records r WHERE r.work_id=w.id)
             AND (c.work_id IS NULL OR c.grade='low'
                  OR c.width > c.height)  -- landscape og:image cards, not posters
           ORDER BY w.kind, w.id"""
    ).fetchall()
    print(f"{len(targets)} cover targets")

    ids_map: dict[int, dict] = {}
    for r in conn.execute("SELECT work_id, namespace, value FROM external_ids"):
        ids_map.setdefault(r["work_id"], {}).setdefault(r["namespace"], r["value"])

    need_wr = any(t["kind"] == "book" for t in targets)
    if need_wr:
        from pull_weread_notes import make_session
        try:
            wr_session = make_session()
        except SystemExit as exc:
            print(f"  ! weread session unavailable ({exc}); cached bookinfo only")
            wr_session = None

    for i, w in enumerate(targets, 1):
        wid = w["id"]
        ids = ids_map.get(wid, {})
        meta = json.loads(w["meta"]) if w["meta"] else {}
        old_h = w["old_h"] or 0

        best = None  # (source, data, wpx, hpx)
        for source, thing in candidates_for(w, ids, meta, state, web, wr_session):
            data = thing if isinstance(thing, bytes) else download(web, thing)
            if not data:
                continue
            wpx, hpx = dims(data)
            # posters are portrait; a landscape image is a social/backdrop
            # card (letterboxd og:image is 1200x675) and never acceptable
            if hpx <= 0 or wpx >= hpx:
                continue
            if best is None or hpx > best[3]:
                best = (source, data, wpx, hpx)
            if hpx >= 600:
                break  # good enough, stop the ladder

        if best is None:
            C["skipped_no_source"] += 1
            continue
        source, data, wpx, hpx = best
        if not (hpx >= 600 or (old_h and hpx > old_h * 1.3) or (not old_h and hpx >= 300)):
            C["rejected_small"] += 1
            continue

        path = COVDIR / f"{wid}.jpg"
        path.write_bytes(data)
        rel = str(path.relative_to(SPACE))
        grade = "good" if hpx >= 600 else "low"
        conn.execute("UPDATE covers SET preferred=0 WHERE work_id=?", (wid,))
        conn.execute(
            """INSERT INTO covers(work_id, file, source, width, height, bytes, sha1, grade, preferred)
               VALUES(?,?,?,?,?,?,?,?,1)
               ON CONFLICT(work_id, file) DO UPDATE SET source=excluded.source,
                 width=excluded.width, height=excluded.height, bytes=excluded.bytes,
                 sha1=excluded.sha1, grade=excluded.grade, preferred=1""",
            (wid, rel, source, wpx, hpx, len(data), hashlib.sha1(data).hexdigest(), grade),
        )
        conn.commit()
        C["upgraded" if old_h else "filled"] += 1
        if i % 20 == 0 or not old_h:
            print(f"  [{i}/{len(targets)}] #{wid} {w['title'][:24]:26} {source} {wpx}x{hpx} "
                  f"({'fill' if not old_h else f'was {old_h}px'})")

    log_run(conn, "cover-pass", C["filled"] + C["upgraded"],
            f"{C['filled']} filled, {C['upgraded']} upgraded, "
            f"{C['skipped_no_source']} no source, {C['rejected_small']} too small")
    print(f"\n{json.dumps(C)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
