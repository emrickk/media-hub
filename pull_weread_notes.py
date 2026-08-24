#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.32"]
# ///
"""Pull WeRead highlights and notes into media.db annotations.

The shelf merge (books_merged.json) only carried note COUNTS; this fetches
the actual text. Per ARCHITECTURE.md adapter contract: raw responses land
untouched under sources/raw/weread/<date>/ before any transform, the fetch
loop is resume-safe (a book already fetched today is read from disk), and
loading is idempotent (annotations UNIQUE(source, uid) via bookmarkId /
reviewId — INSERT OR IGNORE).

Endpoints (verified live 2026-07-28; cookie from AI Space/.mcp.json):
  POST /web/login/renewal               MUST run first: mints a fresh wr_skey
                                        from the long-lived cookie. Without it
                                        bookmarklist returns literally {} and
                                        review/list errors -2012 登录超时 even
                                        though /api/user/notebook still works.
  /api/user/notebook                    books that have any notes (noteCount =
                                        underlines; bookmarkCount = bookmarks)
  /web/book/bookmarklist?bookId=        highlights; needs Referer
                                        /web/reader/<bookId>
  /web/review/list?bookId=&listType=11&mine=1
                                        thoughts; type 1 = on a passage
                                        (abstract=quote, content=my thought),
                                        type 4 = book-level short review

Mapping: highlight -> annotations(kind='highlight', quote=markText)
         type-1 review -> annotations(kind='note', quote=abstract, comment=content)
         type-4 review -> annotations(kind='note', no quote) AND fills the
                          weread record's empty review field.

Books are matched via external_ids namespace 'weread'. A notebook book whose
weread id is not in media.db yet (notes survive shelf removal, so the shelf
merge can miss them) is CREATED from the notebook's own metadata — weread is
the authoritative source for those, and the work is anchored by its weread
id, never a bare title row. Same-book-different-edition duplicates surface
in match_queue for human review, per the standing rules.
"""

from __future__ import annotations

import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mediahub import (  # noqa: E402
    find_work_by_external,
    log_run,
    now,
    open_db,
    upsert_work,
)

HERE = Path(__file__).resolve().parent
SPACE = HERE.parent
RAW = HERE / "sources" / "raw" / "weread" / datetime.now().strftime("%Y-%m-%d")

BASE = "https://weread.qq.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def make_session() -> requests.Session:
    cfg = json.loads((SPACE / ".mcp.json").read_text(encoding="utf-8"))
    raw = cfg["mcpServers"]["weread"]["env"]["WEREAD_COOKIE"]
    if not raw:
        sys.exit("WEREAD_COOKIE empty in AI Space/.mcp.json")
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Origin": BASE, "Referer": f"{BASE}/",
    })
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            s.cookies.set(k, v, domain=".weread.qq.com")
    # Renew wr_skey: the stored cookie's session key is usually stale, and
    # without renewal bookmarklist answers {} instead of an error.
    r = s.post(f"{BASE}/web/login/renewal",
               json={"rq": "%2Fweb%2Fbook%2Fbookmarklist"}, timeout=30)
    if r.status_code != 200 or r.json().get("succ") != 1:
        sys.exit("wr_skey renewal failed — the long-lived cookie itself has "
                 "expired; re-login at weread.qq.com and update WEREAD_COOKIE "
                 "in AI Space/.mcp.json")
    return s


def get_json(session: requests.Session, path: str,
             params: dict | None = None, referer: str = "") -> dict:
    time.sleep(random.uniform(0.8, 1.8))
    headers = {"Referer": referer} if referer else {}
    resp = session.get(f"{BASE}{path}", params=params or {}, headers=headers, timeout=30)
    resp.raise_for_status()
    d = resp.json()
    err = d.get("errcode") or d.get("errCode")
    if err:
        # -2012 = login timeout: the cookie has expired, nothing else will work
        sys.exit(f"weread API error {err} ({d.get('errmsg') or d.get('errMsg')}); "
                 "refresh WEREAD_COOKIE in AI Space/.mcp.json and re-run (resume-safe)")
    return d


def ts(epoch) -> str:
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def fetch_book(session, book_id: str) -> dict:
    """Fetch (or reload today's raw snapshot of) one book's annotations."""
    raw_path = RAW / f"{book_id}.json"
    if raw_path.exists():
        return json.loads(raw_path.read_text(encoding="utf-8"))
    data = {
        "bookmarks": get_json(session, "/web/book/bookmarklist", {"bookId": book_id},
                              referer=f"{BASE}/web/reader/{book_id}"),
        "reviews": get_json(
            session, "/web/review/list",
            {"bookId": book_id, "listType": 11, "mine": 1, "synckey": 0},
            referer=f"{BASE}/web/reader/{book_id}",
        ),
    }
    raw_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def load_book(conn, wid: int, data: dict) -> tuple[int, int]:
    chapters = {
        c.get("chapterUid"): c.get("title") or ""
        for c in data["bookmarks"].get("chapters") or []
    }
    n_hl = n_note = 0
    for bm in data["bookmarks"].get("updated") or []:
        if not bm.get("markText"):
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO annotations
               (work_id, source, kind, uid, chapter, location, quote, comment, created_at, raw)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (wid, "weread", "highlight", bm.get("bookmarkId") or "",
             chapters.get(bm.get("chapterUid"), ""), bm.get("range") or "",
             bm["markText"], "", ts(bm.get("createTime")),
             json.dumps(bm, ensure_ascii=False)),
        )
        n_hl += cur.rowcount
    for wrap in data["reviews"].get("reviews") or []:
        rv = wrap.get("review") or {}
        content = rv.get("content") or ""
        if not content:
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO annotations
               (work_id, source, kind, uid, chapter, location, quote, comment, created_at, raw)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (wid, "weread", "note", rv.get("reviewId") or "",
             rv.get("chapterTitle") or chapters.get(rv.get("chapterUid"), ""),
             str(rv.get("range") or ""), rv.get("abstract") or "", content,
             ts(rv.get("createTime")), json.dumps(rv, ensure_ascii=False)),
        )
        n_note += cur.rowcount
        if rv.get("type") == 4:  # book-level review: also fill the record slot
            conn.execute(
                """UPDATE records SET review=?, updated_at=?
                   WHERE work_id=? AND source='weread' AND (review IS NULL OR review='')""",
                (content, now(), wid),
            )
    return n_hl, n_note


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    session = make_session()
    conn = open_db()

    nb_path = RAW / "notebooks.json"
    if nb_path.exists():
        notebooks = json.loads(nb_path.read_text(encoding="utf-8"))
    else:
        notebooks = get_json(session, "/api/user/notebook")
        nb_path.write_text(json.dumps(notebooks, ensure_ascii=False), encoding="utf-8")
    books = notebooks.get("books") or []
    print(f"{len(books)} books have notes on weread")

    total_hl = total_note = matched = created = failures = 0
    for i, b in enumerate(books, 1):
        book_id = str(b.get("bookId") or "")
        title = ((b.get("book") or {}).get("title") or "?")[:28]
        wid = find_work_by_external(conn, "weread", book_id)
        if wid is None:
            # In the notebook but not on the merged shelf (notes survive shelf
            # removal). WeRead is the source of truth here: create the work,
            # anchored by its weread id, from the notebook's own metadata.
            book = b.get("book") or {}
            wid = upsert_work(
                conn, kind="book",
                title=book.get("title") or f"weread:{book_id}",
                year=None, externals={"weread": book_id},
            )
            conn.execute(
                "UPDATE works SET creators=?, updated_at=? WHERE id=? AND creators=''",
                (book.get("author") or "", now(), wid),
            )
            created += 1
            print(f"  + {title}: not on merged shelf, created work #{wid} (weread:{book_id})")
        try:
            data = fetch_book(session, book_id)
        except requests.RequestException as exc:
            failures += 1
            print(f"  ! {title}: {exc}")
            if failures >= 5:
                print("  ! 5 fetch failures; stopping (re-run to resume from raw snapshots)")
                break
            continue
        failures = 0
        n_hl, n_note = load_book(conn, wid, data)
        total_hl += n_hl
        total_note += n_note
        matched += 1
        conn.commit()
        if i % 10 == 0 or n_hl + n_note > 0:
            print(f"  [{i}/{len(books)}] {title:30} +{n_hl} highlights +{n_note} notes")

    log_run(conn, "weread-notes", total_hl + total_note,
            f"{matched} books, {created} created off-shelf")
    print(f"\ndone: {total_hl} highlights + {total_note} notes across {matched} books"
          f" ({created} off-shelf works created)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
