#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.32"]
# ///
"""harvest_douban.py: harvester for Douban's own "喜欢这部电影/剧集的人也喜欢"
(people-who-liked-this-also-liked) collaborative-filtering block.

Why this exists (context, not decoration): TMDB's own CF surface is nearly
useless for this user's TV taste — only 7 of his 162 top-rated TV titles
carry a TMDB id at all, while all 162 carry a Douban id. Douban's CF is
computed over an audience whose taste resembles his far more than TMDB's
does. For the TV lane this block is the ONLY collaborative-filtering
surface available in this project.

REVISION HISTORY — read this before touching the fetch logic
--------------------------------------------------------------
**First pass (2026-08-23, superseded):** the original brief for this task
described the desktop subject page (`movie.douban.com/subject/<id>/`,
scraped as HTML via a supposed "curl-cffi" pattern) as the source. A live
probe of that page, on the first try, was redirected to
`sec.douban.com/c` and served a JavaScript proof-of-work anti-bot
challenge shell — see `recommend/tests/fixtures/
douban_subject_sample.html.gz`, the actual captured response, kept as
the fixture for the block-detector's negative test. Two things about
that brief turned out to be wrong: this codebase does not use curl_cffi
anywhere (grepped; not installed, not imported), and `douban_export.py`
never actually fetches individual subject pages at all — only the user's
own profile LIST pages — so there was never a proven precedent for
subject-page HTML fetching here.

**Second pass (2026-08-23, current):** the coordinator identified the
correct, ALREADY-WORKING precedent: `mediahub.py`'s `cmd_enrich_douban`
already fetches Douban's mobile rexxar JSON API successfully
(`m.douban.com/rexxar/api/v2/movie/<id>?for_mobile=1`, `MOBILE_UA`,
`polite_get`'s jittered-delay + HTTP-error machinery, an 8-consecutive-
failure circuit breaker). The SAME host answers a `/recommendations`
sub-path with exactly the CF block this task wants, as JSON — verified
live by the coordinator against two real subjects, and re-verified here
against two more (one film anchor, one TV anchor; see "Live verification"
below). This module was rewritten around that endpoint. No HTML parsing
happens anywhere in this file any more — the fragile-selector problem
the first pass worried about is deleted, not solved.

Live verification (this pass, 2026-08-23)
------------------------------------------
```
GET https://m.douban.com/rexxar/api/v2/movie/{douban_id}/recommendations?for_mobile=1
Headers: User-Agent: <MOBILE_UA below>, Accept: application/json, text/plain, */*
         Referer: https://m.douban.com/movie/subject/{douban_id}/
```
Probed against two REAL anchors from this user's history (via `anchors`):
  * film 458 海洋之歌 (douban 11584019) -> HTTP 200, JSON list, 20 items,
    all `type: "movie"`.
  * tv 455 守望者 (douban 26635374) -> HTTP 200, JSON list, 20 items,
    all `type: "tv"`.
Both saved as fixtures: `recommend/tests/fixtures/
douban_rec_{film,tv}_sample.json` (wrapped with the same `_meta` envelope
`fetch` writes, so they double as end-to-end `transform` fixtures).

Each item's keys, confirmed on all 40 real items: `alg_json`,
`card_subtitle`, `id`, `interest`, `pic`, `rating`, `sharing_url`,
`title`, `type`, `uri`, `url`. Concretely (肖申克的救赎's own neighbor
list, per the coordinator, and confirmed in shape by this probe's own
samples): `id` is the douban subject id (numeric, as a string), `title`
the title, `type` is `"movie"` or `"tv"` (both observed; nothing else
seen — `_map_kind` still degrades safely, with a stderr warning, if a
third value ever appears), and `rating.value` is Douban's own aggregate
score (e.g. 9.5).

`year` IS NOT a top-level field, but `card_subtitle` reliably starts with
one: verified on all 40 real items across both fixtures (100%, 0
exceptions) — the format is
`"{year} / {country(ies)} / {genre(s)} / {director(s)} / {cast}"`, e.g.
`"2014 / 法国 / 动画 / 亚历山大·西伯恩 伯努瓦·菲利 / 奥玛·希 伊莎雅·海格林"`.
`parse_recommendations` extracts the leading 4-digit year with a plain
regex anchored at the string's start and leaves `year` null (never
guesses) if that pattern does not match — this is a real, verified
extraction, not the "leave it null" fallback the first pass had to use
for the whole field.

Everything else built in the first pass survives unchanged: `anchors`
(pure DB read), the checkpoint/resumability contract, the per-session
`--budget`, randomized `--delay-min`/`--delay-max`, raw-first snapshots
(now one JSON file per anchor instead of gzipped HTML — see `_write_raw`),
and a blocked-response detector, since this JSON endpoint can still
rate-limit or wall a session; `is_blocked` (body/final-url level, for
when a block manifests as Douban's familiar HTML interstitial instead of
JSON) is kept verbatim from the first pass and still tested against the
real captured HTML fixture. A wall is a recorded finding, not a crash,
exactly as before.

Subcommands
-----------
`anchors --db PATH [--min-rating 9] [--kinds tv,show,film]`
    Distinct works of the given kinds with any watched/watching record
    whose `records.rating >= min-rating` (media.db's RAW 0-10 scale, so
    the default 9 means >=4.5 stars — same convention as history.py/
    reclog.py: never mix this with the 0.5-5.0 star scale) AND that carry
    a `douban` external id. One read transaction, no network. Prints a
    JSON list of `{"work_id", "kind", "title", "douban_id"}`.

`fetch --anchors FILE --raw-dir DIR --checkpoint FILE [--budget 40]
       [--delay-min 5] [--delay-max 10]`
    For each anchor not already in the checkpoint: sleep random(delay_min,
    delay_max) between requests (not before the run's very first
    request), GET the rexxar recommendations endpoint above, and write
    ONE raw JSON file per anchor to `<raw-dir>/<douban_id>.json`:
    `{"_meta": {...}, "results": [...]}` on success, `{"_meta": {...}}`
    (plus `_raw_body` when the response wasn't a JSON list at all) on a
    block/error — see `_write_raw`. `_meta` carries channel/anchor_work_id
    /anchor_kind/anchor_title/douban_id/fetched (date)/fetched_at
    (timestamp)/status/http_status, so `transform` never needs
    `--checkpoint` and stays fully self-contained/offline.

    Checkpoint is written after EVERY single request (crash-safe) and
    anchors already present in it (any status) are skipped on resume.
    Two independent stop conditions, mirroring `mediahub.py`'s
    `cmd_enrich_douban`: (1) HTTP 403/302, or a non-JSON-list response
    whose body is Douban's known challenge shell -> immediate stop,
    `blocked=true`, this run's `blocked_anchor` names which one; (2) 8
    CONSECUTIVE non-block failures (network errors, unparseable/
    unexpected-shape bodies) -> stop, `circuit_breaker_tripped=true` —
    "grinding on would be abuse" per the reference implementation's own
    comment. `--budget` newly-attempted anchors in one run is the third,
    ordinary stop condition (`budget_hit=true`). All three exit 0 with a
    report — a block is a finding, not a crash.

`transform --raw-dir DIR --out FILE`
    No network. Reads every `<raw-dir>/*.json`, skipping (counting, not
    crashing on) any file with no `_meta` key (defensive — mirrors
    harvest_tmdb.py's "raw file with no `_meta` is skipped with a
    warning" convention) and counting (not crashing on) any file whose
    `_meta.status != "fetched"` as `blocked`. For every surviving file,
    `parse_recommendations(payload["results"])` yields the CF entries.
    Each entry becomes one pool-upsert batch row matching
    `recommend/pool.py`'s real upsert contract (verified against
    `pool.py` itself, not the plan text — see "pool.py contract check"
    below):
        kind            comes from the ITEM's own `type` field
                         (`movie`->`film`, `tv`->`tv`), NOT inherited
                         from the anchor — Douban's CF panel mixes kinds
                         freely (a TV anchor can legitimately recommend a
                         film spin-off), and the data says so directly
                         now, so the anchor-inheritance heuristic from
                         the first pass is gone.
        title           the recommendation's own title text.
        year            the leading 4-digit token of `card_subtitle` when
                         present (see "Live verification" above for why
                         this is a verified extraction, not a guess);
                         null when the pattern doesn't match.
        external_ids    {"douban": "<id>"} — real, from the item's own
                         `id` field.
        tags            genre words extracted from `card_subtitle`'s
                         3rd `" / "`-separated field (see "Genre
                         extraction" below) — `[]` when that field isn't
                         confidently genre, never a guess.
        aggregates      {"douban_rating": <rating.value>} when the item
                         carries a numeric rating (it reliably does, per
                         the live samples) — the first pass omitted
                         aggregates because the OLD (HTML) source was
                         unreliable for it; the JSON source is not, so
                         this pass populates it.
        sources         [{"channel": "douban_rec",
                          "anchor_work_id": <anchor's work_id>,
                          "fetched": <meta's fetched date>}]
    Prints a report `{"raw_pages": n, "blocked": b, "skipped": s,
    "entries": len(rows)}` and writes the batch JSON to `--out`.

Genre extraction (added 2026-08-23)
------------------------------------
Every `candidate_pool` row from this channel carried `tags: []` — useless
for `pool.py query --tag` on exactly the Chinese-language half of the
pool. `card_subtitle` packs `"{year} / {country(ies)} / {genre(s)} /
{director(s)} / {cast}"` into one string (see "Live verification"
above), and the genre segment is verifiably the 3rd `" / "`-split field
— BUT only when a genre segment actually exists: measured against the
real 69-file/1,380-item raw corpus in `recommend/raw/douban/2026-08-23/`,
1,166 items split into exactly 5 fields and in EVERY one of those the
3rd field's space-separated tokens are drawn from a closed 29-word
vocabulary (`GENRE_VOCAB` below, built from that same real data, not
guessed) — 剧情/喜剧/动作/爱情/科幻/动画/悬疑/惊悚/恐怖/犯罪/同性/音乐/
歌舞/传记/历史/战争/西部/奇幻/冒险/灾难/武侠/纪录片/短片/真人秀/脱口秀/
家庭/儿童/运动/古装. 176 more items split into 4 fields and 38 into 3 —
same rule holds for all of them EXCEPT a documented negative: when
Douban omits the genre segment entirely (a handful of talk-show/
personality-driven titles with no genre tag on their subject page, e.g.
`"2018 / 美国 / 约翰·奥利弗"`), the field list SHRINKS rather than
leaving a blank slot, so the director's name slides into the genre
position instead. Position alone cannot tell these two cases apart —
only content can. `extract_genres` therefore does NOT trust position
blindly: it takes the 3rd field only when EVERY one of its
space-separated tokens is a member of `GENRE_VOCAB`, and returns `[]`
(never a guessed/partial list) otherwise. Verified against the full real
corpus: 1,374 of 1,380 items (99.6%) get a clean genre list this way;
the 6 rejected are exactly the genre-omitted director/cast-in-position-3
cases above (spot-checked by hand, zero false positives or negatives
found). A re-`transform` of the existing raw corpus would newly populate
`tags` for candidates behind all but 6 of the pool's 984 `douban_rec`
rows on the next real harvest run (see `test_transform_...genre...`
tests and STATE.md for the exact re-transform count — this task does
NOT write that to media.db).

pool.py contract check (this pass)
-----------------------------------
Read `recommend/pool.py` directly (not the plan text) before finalizing
this shape: `UPSERT_REQUIRED_FIELDS = ("kind", "title")` plus a non-empty
`sources` list (checked separately in `_validate_upsert_rows`) are the
only hard requirements; `year`/`external_ids`/`tags`/`aggregates`/
`shape`/`original_title` are all optional and independently defaulted.
The batch rows this module emits satisfy that exactly, including the
omit-year-when-unknown and now-include-aggregates-when-known cases.
"""
from __future__ import annotations
import argparse, json, random, re, sqlite3, sys, time
from datetime import datetime, timezone
from pathlib import Path

BUSY_TIMEOUT_MS = 15000
DEFAULT_KINDS = ("tv", "show", "film")
DEFAULT_MIN_RATING = 9.0
DEFAULT_BUDGET = 40
CIRCUIT_BREAKER_STREAK = 8

REC_URL = "https://m.douban.com/rexxar/api/v2/movie/{id}/recommendations?for_mobile=1"

# Copied verbatim from mediahub.py's `cmd_enrich_douban` — the ONE proven
# pattern this project has for the rexxar mobile API.
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)
REC_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": "application/json, text/plain, */*",
}

# Same block-marker list douban_export.py's Fetcher uses, verbatim — words
# that appear in Douban's real interstitial/captcha pages. Kept short-
# body-gated (see `is_blocked`) so they don't false-positive on a long,
# legitimate page.
BLOCK_MARKERS = ("异常请求", "sec.douban.com", "有异常操作", "captcha", "验证码")
# The proof-of-work challenge shell specifically — what a live probe of
# the (now-abandoned) desktop subject-page path actually captured; see
# `recommend/tests/fixtures/douban_subject_sample.html.gz`.
CHALLENGE_MARKERS = ('id="sec"', "载入中")

KIND_MAP = {"movie": "film", "tv": "tv"}
YEAR_RE = re.compile(r"^(\d{4})\b")

# Genre vocabulary for `extract_genres` — see the module docstring's
# "Genre extraction" section. Built ENTIRELY from tokens actually observed
# in the 3rd `" / "`-split field of `card_subtitle` across the real
# 69-file/1,380-item raw corpus (`recommend/raw/douban/2026-08-23/`),
# specifically the 1,166 items with exactly 5 fields — the unambiguous
# case where that field cannot be anything but genre. Not copied from
# memory or Douban's full published tag list (which is longer than this);
# deliberately kept to only what this data has actually shown, since an
# unverified extra word here would silently start misclassifying a
# director/cast field as genre the moment it happened to collide.
GENRE_VOCAB = frozenset("""
    剧情 喜剧 动作 爱情 科幻 动画 悬疑 惊悚 恐怖 犯罪 同性 音乐 歌舞
    传记 历史 战争 西部 奇幻 冒险 灾难 武侠 纪录片 短片 真人秀 脱口秀
    家庭 儿童 运动 古装
""".split())


def now_date() -> str:
    return datetime.now(timezone.utc).astimezone().date().isoformat()


def now_ts() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- anchors

def load_anchors(con: sqlite3.Connection, kinds: tuple[str, ...],
                  min_rating: float) -> list[dict]:
    """Distinct works of `kinds` with a watched/watching record whose
    `records.rating >= min_rating` (RAW 0-10 scale) that also carry a
    `douban` external id. One read transaction, no network — mirrors
    history.py's snapshot discipline of doing all DB reads before any
    network I/O."""
    con.row_factory = sqlite3.Row
    ph = ",".join("?" for _ in kinds)
    con.execute("BEGIN")
    rows = con.execute(f"""
        SELECT DISTINCT w.id AS work_id, w.kind, w.title, e.value AS douban_id
        FROM works w
        JOIN records r ON r.work_id = w.id
        JOIN external_ids e ON e.work_id = w.id AND e.namespace = 'douban'
        WHERE w.kind IN ({ph})
          AND r.status IN ('watched', 'watching')
          AND r.rating >= ?
        ORDER BY w.id
    """, (*kinds, min_rating)).fetchall()
    con.execute("COMMIT")
    return [dict(work_id=r["work_id"], kind=r["kind"], title=r["title"],
                 douban_id=r["douban_id"]) for r in rows]


def cmd_anchors(args) -> None:
    con = sqlite3.connect(args.db)
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    try:
        kinds = tuple(k.strip() for k in args.kinds.split(",") if k.strip())
        anchors = load_anchors(con, kinds, args.min_rating)
    finally:
        con.close()
    print(json.dumps(anchors, ensure_ascii=False))


# ------------------------------------------------------------ block/parse

def is_blocked(html: str, final_url: str = "") -> bool:
    """True if `html`/`final_url` is Douban's anti-bot interstitial rather
    than real content. Used in `fetch` as the fallback check when a
    response to the rexxar JSON endpoint isn't valid JSON — a block can
    still manifest as this familiar HTML challenge shell. Verified against
    the real captured response in `recommend/tests/fixtures/
    douban_subject_sample.html.gz` (captured during the first pass's
    desktop-subject-page probe — the shell itself is host-agnostic, it's
    served by sec.douban.com regardless of which douban.com endpoint
    redirected there)."""
    if "sec.douban.com" in (final_url or ""):
        return True
    if len(html) < 20000 and all(m in html for m in CHALLENGE_MARKERS):
        return True
    if len(html) < 20000:
        return any(m in html for m in BLOCK_MARKERS)
    return False


def _map_kind(douban_type: str) -> str:
    kind = KIND_MAP.get(douban_type)
    if kind is None:
        print(f"warning: unrecognized douban recommendation type "
              f"{douban_type!r}, kept as-is (expected 'movie' or 'tv')",
              file=sys.stderr)
        return douban_type
    return kind


def extract_genres(card_subtitle: str | None) -> list[str]:
    """Genre words from `card_subtitle`'s 3rd `" / "`-split field, or `[]`
    if that field isn't confidently genre — see the module docstring's
    "Genre extraction" for the full rationale and the real-data numbers
    behind `GENRE_VOCAB`. Deliberately does NOT trust field position
    alone: Douban omits the genre segment entirely for a handful of
    titles (director/cast slide into its slot instead, e.g.
    `"2018 / 美国 / 约翰·奥利弗"`), so the 3rd field is only accepted
    when EVERY one of its space-separated tokens is a member of
    `GENRE_VOCAB` — a real, verified match, never a guess/partial list."""
    parts = (card_subtitle or "").split(" / ")
    if len(parts) < 3:
        return []
    tokens = parts[2].split()
    if tokens and all(t in GENRE_VOCAB for t in tokens):
        return tokens
    return []


def parse_recommendations(results: list) -> list[dict]:
    """Map the rexxar recommendations endpoint's raw JSON `results` list
    (list of dicts, keys `alg_json`/`card_subtitle`/`id`/`interest`/`pic`/
    `rating`/`sharing_url`/`title`/`type`/`uri`/`url` — confirmed on 40
    real items across two real anchors, see the module docstring's "Live
    verification") into `[{"douban_id": int, "title": str, "kind": str,
    "year": int|None, "rating": float|None, "genres": list[str]}, ...]`.

    `kind` = `_map_kind(item["type"])` (`movie`->`film`, `tv`->`tv`, any
    other value passed through with a stderr warning rather than
    crashing). `year` = the leading 4-digit token of `card_subtitle` via
    `YEAR_RE`, or `None` if that pattern doesn't match — a verified
    extraction (100% hit rate on the 40 real items seen), not a guess.
    `rating` = `item["rating"]["value"]` when present and numeric, else
    omitted from the entry (so callers can `.get("rating")`). `genres` =
    `extract_genres(item["card_subtitle"])` — `[]`, never a guess, when
    that field isn't confidently genre (see `extract_genres`).

    Items missing an `id` or `title`, or whose `id` isn't int-able, are
    skipped rather than raising — a single malformed item must not sink
    the whole page's batch."""
    out = []
    for item in results:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        title = (item.get("title") or "").strip()
        if not raw_id or not title:
            continue
        try:
            douban_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        kind = _map_kind(item.get("type") or "")
        card_subtitle = item.get("card_subtitle") or ""
        m = YEAR_RE.match(card_subtitle)
        year = int(m.group(1)) if m else None
        entry = {"douban_id": douban_id, "title": title, "kind": kind, "year": year,
                  "genres": extract_genres(card_subtitle)}
        rating = (item.get("rating") or {}).get("value")
        if isinstance(rating, (int, float)):
            entry["rating"] = float(rating)
        out.append(entry)
    return out


# ------------------------------------------------------------------ fetch

def _load_checkpoint(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_checkpoint(path: Path, checkpoint: dict) -> None:
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=1),
                     encoding="utf-8")


def _write_raw(raw_dir: Path, douban_id: str, meta: dict,
               results: list | None = None, raw_body: str | None = None) -> Path:
    payload = {"_meta": meta}
    if results is not None:
        payload["results"] = results
    if raw_body is not None:
        payload["_raw_body"] = raw_body
    path = raw_dir / f"{douban_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def cmd_fetch(args) -> None:
    try:
        import requests
    except ImportError:
        sys.exit(
            "fetch needs the `requests` package, which is not installed "
            "in this interpreter. Run this subcommand via "
            "`uv run recommend/harvest_douban.py fetch ...` (this file "
            "carries a PEP 723 dependency block), or `pip install "
            "requests` first. `anchors` and `transform` need no network "
            "dependency and run fine under a plain interpreter."
        )

    anchors = json.loads(Path(args.anchors).read_text(encoding="utf-8"))
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = Path(args.checkpoint)
    checkpoint = _load_checkpoint(checkpoint_path)

    session = requests.Session()
    session.headers.update(REC_HEADERS)

    attempted = fetched = skipped_resumed = streak = 0
    budget_hit = False
    blocked_anchor = None
    circuit_breaker_tripped = False
    made_request = False

    for anchor in anchors:
        douban_id = str(anchor["douban_id"])
        if douban_id in checkpoint:
            skipped_resumed += 1
            continue
        if attempted >= args.budget:
            budget_hit = True
            break

        if made_request:
            time.sleep(random.uniform(args.delay_min, args.delay_max))
        made_request = True
        attempted += 1

        url = REC_URL.format(id=douban_id)
        meta_base = dict(channel="douban_rec", anchor_work_id=anchor.get("work_id"),
                          anchor_kind=anchor.get("kind"), anchor_title=anchor.get("title"),
                          douban_id=douban_id, fetched=now_date(), fetched_at=now_ts())

        try:
            resp = session.get(
                url, headers={"Referer": f"https://m.douban.com/movie/subject/{douban_id}/"},
                timeout=30, allow_redirects=True)
        except requests.RequestException as exc:
            streak += 1
            meta = dict(meta_base, status="error", error=str(exc))
            _write_raw(raw_dir, douban_id, meta)
            checkpoint[douban_id] = meta
            _save_checkpoint(checkpoint_path, checkpoint)
            if streak >= CIRCUIT_BREAKER_STREAK:
                circuit_breaker_tripped = True
                break
            continue

        status = resp.status_code
        final_url = resp.url or ""

        if status in (403, 302):
            meta = dict(meta_base, status="blocked", http_status=status, final_url=final_url)
            _write_raw(raw_dir, douban_id, meta, raw_body=resp.text)
            checkpoint[douban_id] = meta
            _save_checkpoint(checkpoint_path, checkpoint)
            blocked_anchor = dict(anchor, http_status=status, final_url=final_url)
            break

        try:
            data = resp.json()
            if not isinstance(data, list):
                raise ValueError(f"expected a JSON list, got {type(data).__name__}")
        except ValueError:
            if is_blocked(resp.text, final_url):
                meta = dict(meta_base, status="blocked", http_status=status, final_url=final_url)
                _write_raw(raw_dir, douban_id, meta, raw_body=resp.text)
                checkpoint[douban_id] = meta
                _save_checkpoint(checkpoint_path, checkpoint)
                blocked_anchor = dict(anchor, http_status=status, final_url=final_url)
                break
            streak += 1
            meta = dict(meta_base, status="error", http_status=status,
                        error="response was not a JSON list")
            _write_raw(raw_dir, douban_id, meta, raw_body=resp.text)
            checkpoint[douban_id] = meta
            _save_checkpoint(checkpoint_path, checkpoint)
            if streak >= CIRCUIT_BREAKER_STREAK:
                circuit_breaker_tripped = True
                break
            continue

        streak = 0
        meta = dict(meta_base, status="fetched", http_status=status)
        _write_raw(raw_dir, douban_id, meta, results=data)
        checkpoint[douban_id] = meta
        _save_checkpoint(checkpoint_path, checkpoint)
        fetched += 1

    report = {
        "attempted": attempted, "fetched": fetched,
        "skipped_resumed": skipped_resumed,
        "blocked": blocked_anchor is not None, "blocked_anchor": blocked_anchor,
        "circuit_breaker_tripped": circuit_breaker_tripped,
        "budget": args.budget, "budget_hit": budget_hit,
        "raw_dir": str(raw_dir), "checkpoint": str(checkpoint_path),
    }
    print(json.dumps(report, ensure_ascii=False))


# --------------------------------------------------------------- transform

def cmd_transform(args) -> None:
    raw_dir = Path(args.raw_dir)
    rows: list[dict] = []
    raw_pages = blocked = skipped = 0

    for path in sorted(raw_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            skipped += 1
            print(f"warning: unreadable raw file {path}, skipped", file=sys.stderr)
            continue

        meta = payload.get("_meta") if isinstance(payload, dict) else None
        if not meta:
            skipped += 1
            print(f"warning: {path} has no _meta, skipped", file=sys.stderr)
            continue

        raw_pages += 1
        if meta.get("status") != "fetched":
            blocked += 1
            continue

        anchor_work_id = meta.get("anchor_work_id")
        fetched_date = meta.get("fetched") or now_date()
        results = payload.get("results") or []

        for rec in parse_recommendations(results):
            row = {
                "kind": rec["kind"],
                "title": rec["title"],
                "year": rec["year"],
                "external_ids": {"douban": str(rec["douban_id"])},
                "sources": [{"channel": "douban_rec",
                             "anchor_work_id": anchor_work_id,
                             "fetched": fetched_date}],
            }
            if "rating" in rec:
                row["aggregates"] = {"douban_rating": rec["rating"]}
            if rec["genres"]:
                row["tags"] = rec["genres"]
            rows.append(row)

    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"raw_pages": raw_pages, "blocked": blocked,
                      "skipped": skipped, "entries": len(rows)}))


# ------------------------------------------------------------------- cli

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("anchors", help="DB read: rated works with a douban id")
    s.add_argument("--db", required=True)
    s.add_argument("--min-rating", type=float, default=DEFAULT_MIN_RATING)
    s.add_argument("--kinds", default=",".join(DEFAULT_KINDS))

    s = sub.add_parser("fetch", help="polite, resumable rexxar CF fetch")
    s.add_argument("--anchors", required=True)
    s.add_argument("--raw-dir", required=True)
    s.add_argument("--checkpoint", required=True)
    s.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    s.add_argument("--delay-min", type=float, default=5)
    s.add_argument("--delay-max", type=float, default=10)

    s = sub.add_parser("transform", help="raw JSON -> pool-upsert batch JSON")
    s.add_argument("--raw-dir", required=True)
    s.add_argument("--out", required=True)

    args = p.parse_args()
    {"anchors": cmd_anchors, "fetch": cmd_fetch,
     "transform": cmd_transform}[args.cmd](args)


if __name__ == "__main__":
    main()
