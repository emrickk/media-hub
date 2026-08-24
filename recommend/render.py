#!/usr/bin/env python3
"""render.py: turn logged `recommendations` rows into one self-contained
HTML card page — the recommend system's only user-facing surface.

Why this exists: every prediction the system makes is already sealed into
media.db by `reclog.py`, but a sqlite row is not something you can read
over dinner. This renders the pitch the way it is meant to be consumed —
cover, title, one-paragraph synopsis, and *why it was picked for you* —
and nothing else. It is a VIEW: it never writes to media.db, so it can
run while anything else holds the DB.

Poster + synopsis are fetched from TMDB (falling back to the Douban
subject page) and cached under `recommend/covers/`, so a re-render of the
same slate costs zero network calls. Images are inlined as data: URIs so
the output file works from file:// with no server and no broken images.

Usage
-----
    # the newest logged slate (default)
    python3 recommend/render.py --db media.db --open

    # a specific set of logged rows
    python3 recommend/render.py --db media.db --ids 25,28,29,30

    # include what the critic killed, in a footer section
    python3 recommend/render.py --db media.db --include-killed

Options
-------
    --db PATH          media.db (read-only; required)
    --ids A,B,C        explicit recommendations.id list; default = the
                       rows of the most recent session_date
    --include-killed   also render critic_killed=1 rows, dimmed, in a
                       "didn't make the cut" section
    --out PATH         output html (default recommend/out/rec-<ts>.html)
    --no-network       never fetch; use only what is already cached
    --open             open the result in the default browser when done
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
COVER_DIR = HERE / "covers"
META_PATH = COVER_DIR / "meta.json"
OUT_DIR = HERE / "out"

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"
UA = "media-hub-recommend/1.0 (+render.py)"


# --------------------------------------------------------------------------
# db read
# --------------------------------------------------------------------------

def connect(path: str) -> sqlite3.Connection:
    """Read-only connection. The renderer must never be a writer — it is
    routinely run while a harvest or a log pass holds media.db."""
    uri = f"file:{urllib.parse.quote(str(Path(path).resolve()))}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def fetch_rows(con: sqlite3.Connection, ids: list[int] | None,
               include_killed: bool, pending: bool = False) -> list[sqlite3.Row]:
    if pending:
        # Every prediction still awaiting a reaction, across all asks.
        # This is the view that makes the verdict loop possible: a slate
        # rendered per-session shows you 4 of 18 and the other 14 are
        # invisible, so they never get scored and hit_rate stays at 0.
        return con.execute(
            "select * from recommendations where critic_killed = 0 "
            "and verdict is null order by session_date, id").fetchall()

    if ids:
        marks = ",".join("?" * len(ids))
        sql = f"select * from recommendations where id in ({marks})"
        rows = con.execute(sql, ids).fetchall()
        # preserve the order the caller asked for
        by_id = {r["id"]: r for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    latest = con.execute(
        "select session_date from recommendations "
        "order by session_date desc, id desc limit 1").fetchone()
    if not latest:
        return []
    sql = "select * from recommendations where session_date = ?"
    if not include_killed:
        sql += " and critic_killed = 0"
    return con.execute(sql + " order by id", (latest["session_date"],)).fetchall()


def jload(text: str | None, default):
    try:
        return json.loads(text) if text else default
    except (json.JSONDecodeError, TypeError):
        return default


def card_of(row: sqlite3.Row) -> dict:
    """Flatten one stored row into what the template needs. Everything
    here already lives in the row — the reason text is the scout's case
    plus the critic's selection reason, verbatim; the renderer invents
    no prose of its own."""
    dossier = jload(row["dossier"], {})
    scout = dossier.get("scout", {}) or {}
    critic = dossier.get("critic", {}) or {}
    ids = jload(row["external_ids"], {})

    return {
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "original_title": (scout.get("original_title") or "").strip(),
        "year": row["year"],
        "external_ids": ids,
        "stars": row["predicted_stars"],
        "confidence": row["predicted_confidence"] or "",
        "percentile": critic.get("predicted_percentile"),
        "cell_label": critic.get("cell_label", ""),
        "killed": bool(row["critic_killed"]),
        "kill_reason": row["kill_reason"] or "",
        "rank": critic.get("pitch_rank"),
        "selected": critic.get("pitch_selected"),
        "case": (scout.get("case") or "").strip(),
        "ask_fit": (scout.get("ask_fit") or "").strip(),
        "selection_reason": (critic.get("selection_reason") or "").strip(),
        "evidence_chain": critic.get("evidence_chain") or [],
        "risks": critic.get("residual_risks") or [],
        "shape": scout.get("shape", {}) or {},
        "verdict": row["verdict"],
        "intention": row["intention"],
        "session_date": row["session_date"],
    }


# --------------------------------------------------------------------------
# poster + synopsis, cached
# --------------------------------------------------------------------------

def load_meta() -> dict:
    return jload(META_PATH.read_text("utf-8"), {}) if META_PATH.exists() else {}


def save_meta(meta: dict) -> None:
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")


def tmdb_key() -> str:
    import os
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if key:
        return key
    env = HERE.parent.parent / "douban-export" / "sources" / "sources.env"
    if env.exists():
        for line in env.read_text("utf-8").splitlines():
            if line.startswith("TMDB_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def get_json(url: str, headers: dict | None = None, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_bytes(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def cache_key(ids: dict, title: str, year) -> str:
    for k in ("tmdb_movie", "tmdb_tv", "tmdb", "imdb", "douban"):
        if ids.get(k):
            return f"{k}_{ids[k]}"
    slug = re.sub(r"[^0-9A-Za-z一-鿿]+", "-", f"{title}-{year}").strip("-")
    return f"title_{slug}"[:80]


def _norm(s: str) -> str:
    """Loose title key: case-folded, punctuation and spacing removed, so
    "Rear Window" == "rear window" and "Spider-Man" == "spiderman"."""
    return re.sub(r"[^0-9a-z一-鿿]+", "", (s or "").lower())


def resolve_via_imdb(imdb_id: str, key: str) -> tuple[str, str] | None:
    """An imdb tt id -> the TMDB detail path for the same work. TMDB's
    /find is authoritative here, which is the whole point: it is a lookup
    at the source, not a guess."""
    q = urllib.parse.urlencode({"api_key": key, "external_source": "imdb_id"})
    try:
        data = get_json(f"{TMDB_BASE}/find/{imdb_id}?{q}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None
    if data.get("movie_results"):
        return f"/movie/{data['movie_results'][0]['id']}", "movie"
    if data.get("tv_results"):
        return f"/tv/{data['tv_results'][0]['id']}", "tv"
    return None


def tmdb_detail(ids: dict, key: str, kind: str = "") -> dict:
    """Poster path + zh-CN overview (English fallback) for one candidate,
    with the id checked against what TMDB says that id actually is.

    The check is not paranoia: a live run wrote `tmdb_tv: 2795` onto
    人类星球/Human Planet, and 2795 is a Philippine newscast — a
    remembered id, which the house rules forbid precisely because it is
    invisible once stored. Rendering is where it becomes visible, so the
    renderer refuses to dress a card in another title's poster and
    synopsis. Flagged only when the titles disagree AND the years do too,
    so a Chinese-titled work TMDB has no translation for is not accused."""
    if ids.get("tmdb_movie"):
        path, media = f"/movie/{ids['tmdb_movie']}", "movie"
    elif ids.get("tmdb_tv"):
        path, media = f"/tv/{ids['tmdb_tv']}", "tv"
    elif ids.get("tmdb"):
        # v1 rows stored a bare `tmdb` key whose endpoint is implied by
        # the work's kind rather than by the key name.
        media = "tv" if kind in ("tv", "show", "drama") else "movie"
        path = f"/{media}/{ids['tmdb']}"
    elif ids.get("imdb"):
        # No tmdb id at all — TMDB can resolve an imdb tt id to its own.
        resolved = resolve_via_imdb(str(ids["imdb"]), key)
        if not resolved:
            return {}
        path, media = resolved
    else:
        return {}

    out: dict = {"media": media, "names": set()}
    for lang in ("zh-CN", "en-US"):
        q = urllib.parse.urlencode({"api_key": key, "language": lang})
        try:
            data = get_json(f"{TMDB_BASE}{path}?{q}")
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
            continue
        for field in ("title", "name", "original_title", "original_name"):
            if data.get(field):
                out["names"].add(data[field])
        if not out.get("poster_path"):
            out["poster_path"] = data.get("poster_path") or ""
        if not out.get("overview"):
            out["overview"] = (data.get("overview") or "").strip()
        if not out.get("year"):
            released = data.get("release_date") or data.get("first_air_date") or ""
            out["year"] = int(released[:4]) if released[:4].isdigit() else None
        # The external aggregate. Engine prior `external-rating-signal`:
        # this user selects on visible quality signal and was previously
        # inferring it from cover art because the page never showed it.
        if not out.get("vote") and data.get("vote_average"):
            out["vote"] = round(float(data["vote_average"]), 1)
            out["votes"] = int(data.get("vote_count") or 0)
        if out.get("overview") and out.get("poster_path"):
            break
    return out


def id_matches(detail: dict, title: str, original_title: str, year) -> bool:
    """True when TMDB's own record for this id plausibly IS this work."""
    if not detail.get("names"):
        return False
    ours = {_norm(t) for t in (title, original_title) if t}
    theirs = {_norm(n) for n in detail["names"] if n}
    if ours & theirs:
        return True
    if year and detail.get("year") and abs(int(year) - detail["year"]) <= 1:
        return True
    return False


DOUBAN_OG = re.compile(r'<meta property="og:image" content="([^"]+)"')
DOUBAN_DESC = re.compile(
    r'<span property="v:summary"[^>]*>(.*?)</span>', re.S)


def douban_detail(douban_id: str) -> dict:
    """Cover + 简介 off the desktop subject page. Douban blocks freely;
    a block is a missing cover, never an error that stops the render."""
    url = f"https://movie.douban.com/subject/{douban_id}/"
    try:
        raw = get_bytes(url, headers={
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://movie.douban.com/",
        })
    except (urllib.error.URLError, OSError, TimeoutError):
        return {}
    page = raw.decode("utf-8", "replace")
    if "有异常请求从你的 IP 发出" in page or "sec.douban.com" in page:
        return {}
    out = {}
    m = DOUBAN_OG.search(page)
    if m:
        out["cover_url"] = m.group(1)
    m = DOUBAN_DESC.search(page)
    if m:
        text = re.sub(r"<[^>]+>", "", m.group(1))
        out["overview"] = html.unescape(text).strip()
    return out


def ensure_assets(card: dict, meta: dict, key: str, no_network: bool) -> None:
    """Fill card['poster_file'] and card['overview'], fetching only what
    the cache is missing. Mutates `meta` so the caller can persist it."""
    ck = cache_key(card["external_ids"], card["title"], card["year"])
    entry = meta.setdefault(ck, {})
    card["overview"] = entry.get("overview", "")
    card["id_warning"] = entry.get("id_warning", "")
    card["vote"] = entry.get("vote")
    card["votes"] = entry.get("votes", 0)

    cached = sorted(COVER_DIR.glob(f"{ck}.*")) if COVER_DIR.exists() else []
    if cached:
        card["poster_file"] = cached[0]

    if no_network or (card.get("poster_file") and card["overview"]):
        return

    ids = card["external_ids"]
    img_url, img_headers = "", {}

    if key and any(ids.get(k) for k in
                   ("tmdb_movie", "tmdb_tv", "tmdb", "imdb")):
        d = tmdb_detail(ids, key, card["kind"])
        if d and not id_matches(d, card["title"], card["original_title"],
                                card["year"]):
            bad = (ids.get("tmdb_movie") or ids.get("tmdb_tv")
                   or ids.get("tmdb") or ids.get("imdb"))
            got = " / ".join(sorted(d.get("names") or [])) or "(no title)"
            card["id_warning"] = entry["id_warning"] = (
                f"TMDB id {bad} 指向的是《{got}》"
                f"（{d.get('year') or '年份未知'}），不是这一部 —— "
                f"记录里的 id 有误，封面与简介已跳过")
            d = {}
        if d.get("overview") and not card["overview"]:
            card["overview"] = entry["overview"] = d["overview"]
        if d.get("vote"):
            card["vote"] = entry["vote"] = d["vote"]
            card["votes"] = entry["votes"] = d.get("votes", 0)
        if d.get("poster_path") and not card.get("poster_file"):
            img_url = TMDB_IMG + d["poster_path"]

    if ids.get("douban") and (not img_url and not card.get("poster_file")
                              or not card["overview"]):
        d = douban_detail(str(ids["douban"]))
        if d.get("overview") and not card["overview"]:
            card["overview"] = entry["overview"] = d["overview"]
        if d.get("cover_url") and not img_url and not card.get("poster_file"):
            img_url = d["cover_url"]
            img_headers = {"Referer": "https://movie.douban.com/"}

    if img_url and not card.get("poster_file"):
        try:
            blob = get_bytes(img_url, headers=img_headers)
        except (urllib.error.URLError, OSError, TimeoutError):
            return
        ext = Path(urllib.parse.urlparse(img_url).path).suffix or ".jpg"
        COVER_DIR.mkdir(parents=True, exist_ok=True)
        dest = COVER_DIR / f"{ck}{ext}"
        dest.write_bytes(blob)
        card["poster_file"] = dest


def data_uri(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


# --------------------------------------------------------------------------
# html
# --------------------------------------------------------------------------

KIND_LABEL = {"film": "电影", "tv": "剧集", "show": "剧集", "drama": "剧集"}


def stars_html(stars) -> str:
    if stars is None:
        return ""
    full = int(stars)
    half = (stars - full) >= 0.5
    glyphs = "★" * full + ("½" if half else "")
    return (f'<span class="stars" title="predicted {stars}">{glyphs}'
            f'<span class="starnum">{stars:g}</span></span>')


def shape_line(card: dict) -> str:
    s = card.get("shape") or {}
    bits = []
    if s.get("seasons"):
        bits.append(f"{s['seasons']} 季")
    if s.get("episodes"):
        bits.append(f"{s['episodes']} 集")
    if s.get("ep_runtime_min"):
        bits.append(f"每集 {s['ep_runtime_min']} 分钟")
    elif s.get("runtime_min"):
        bits.append(f"{s['runtime_min']} 分钟")
    return " · ".join(bits)


def esc(t) -> str:
    return html.escape(str(t or ""))


def pretty(stamp: str) -> str:
    try:
        return datetime.fromisoformat(stamp).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return stamp or ""


def render_card(card: dict, dimmed: bool = False) -> str:
    poster = data_uri(card.get("poster_file"))
    poster_html = (f'<img class="poster" src="{poster}" alt="">' if poster
                   else '<div class="poster poster--empty">无封面</div>')

    meta_bits = [KIND_LABEL.get(card["kind"], card["kind"])]
    if card["year"]:
        meta_bits.append(str(card["year"]))
    sl = shape_line(card)
    if sl:
        meta_bits.append(sl)

    pct = card.get("percentile")
    pct_html = ""
    if pct is not None:
        cell = esc(card.get("cell_label") or "同类作品")
        pct_html = (f'<span class="chip" title="在「{cell}」里的位置">'
                    f'{pct:g} 分位</span>')
    conf = (f'<span class="chip chip--{esc(card["confidence"])}">'
            f'把握 {esc(card["confidence"])}</span>' if card["confidence"] else "")

    # External aggregate, shown rather than left to be guessed from the art.
    vote = card.get("vote")
    vote_html = ""
    if vote:
        votes = card.get("votes") or 0
        tier = "hi" if vote >= 7.5 else ("mid" if vote >= 6.5 else "lo")
        count = f"（{votes:,} 人）" if votes else ""
        vote_html = (f'<span class="vote vote--{tier}" '
                     f'title="TMDB 平均分{count}">TMDB {vote:g}</span>')

    # The case is the persuasive argument for watching it; the critic's
    # selection_reason is bookkeeping about the slate. Lead with the case.
    why = card["case"] or card["ask_fit"] or card["selection_reason"]
    why_html = f'<p class="why">{esc(why)}</p>' if why else ""

    detail_items = []
    if card["selection_reason"] and card["selection_reason"] != why:
        detail_items.append(("为什么排在这个位置", [card["selection_reason"]]))
    if card["evidence_chain"]:
        detail_items.append(("依据", list(card["evidence_chain"])[:4]))
    if card["risks"]:
        detail_items.append(("需要注意", list(card["risks"])[:3]))
    blocks = "".join(
        f'<p class="dt">{esc(head)}</p><ul>'
        + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"
        for head, items in detail_items)
    risks_html = (f'<details class="risks"><summary>评审细节</summary>{blocks}'
                  f'</details>' if blocks else "")

    kill_html = (f'<p class="kill">未通过：{esc(card["kill_reason"])}</p>'
                 if card["killed"] and card["kill_reason"] else "")

    warn_html = (f'<p class="warn">⚠ {esc(card.get("id_warning"))}</p>'
                 if card.get("id_warning") else "")

    orig = card["original_title"]
    orig_html = (f'<span class="orig">{esc(orig)}</span>'
                 if orig and orig != card["title"] else "")

    overview = card.get("overview") or ""
    overview_html = f'<p class="overview">{esc(overview)}</p>' if overview else ""

    rank = f'<span class="rank">{card["rank"]}</span>' if card.get("rank") else ""
    verdict_cmd = (f'python3 recommend/reclog.py --db media.db verdict '
                   f'--id {card["id"]} --verdict interested')
    verdict_html = (
        f'<div class="verdict">'
        f'<button class="v" data-v="interested" data-id="{card["id"]}">感兴趣</button>'
        f'<button class="v" data-v="meh" data-id="{card["id"]}">一般</button>'
        f'<button class="v" data-v="no" data-id="{card["id"]}">不看</button>'
        f'<button class="v" data-v="watched" data-id="{card["id"]}">看过了</button>'
        f'<span class="recid" title="{esc(verdict_cmd)}">#{card["id"]}</span>'
        f'</div>')

    return f'''<article class="card{' card--dim' if dimmed else ''}">
  {poster_html}
  <div class="body">
    <h2>{rank}{esc(card["title"])}{orig_html}</h2>
    <p class="meta">{esc(" · ".join(meta_bits))}</p>
    <p class="pred">{stars_html(card["stars"])}{vote_html}{pct_html}{conf}</p>
    {overview_html}
    {why_html}
    {kill_html}
    {warn_html}
    {risks_html}
    {verdict_html}
  </div>
</article>'''


CSS = """
:root{--bg:#faf9f7;--fg:#1b1a18;--dim:#6b6660;--line:#e4e0da;--card:#fff;
 --accent:#8a5a2b;--shadow:0 1px 3px rgba(0,0,0,.07),0 8px 24px rgba(0,0,0,.05)}
@media (prefers-color-scheme:dark){:root{--bg:#141312;--fg:#eceae6;--dim:#9a938a;
 --line:#2c2a27;--card:#1d1c1a;--accent:#d9a86c;
 --shadow:0 1px 3px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3)}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font:16px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif;
 padding:40px 20px 80px}
.wrap{max-width:860px;margin:0 auto}
header{margin-bottom:36px;border-bottom:1px solid var(--line);padding-bottom:22px}
header h1{font-size:19px;margin:0 0 10px;letter-spacing:.02em}
header .ask{color:var(--dim);font-size:14px;white-space:pre-wrap;margin:0}
header .when{color:var(--dim);font-size:12px;margin-top:10px}
.card{display:flex;gap:22px;background:var(--card);border:1px solid var(--line);
 border-radius:14px;padding:22px;margin-bottom:22px;box-shadow:var(--shadow)}
.card--dim{opacity:.55}
.poster{width:132px;min-width:132px;height:198px;object-fit:cover;border-radius:8px;
 background:var(--line)}
.poster--empty{display:flex;align-items:center;justify-content:center;
 color:var(--dim);font-size:12px}
.body{flex:1;min-width:0}
h2{font-size:20px;margin:0 0 4px;line-height:1.35}
.rank{display:inline-block;width:22px;height:22px;line-height:22px;text-align:center;
 border-radius:50%;background:var(--accent);color:#fff;font-size:12px;
 margin-right:9px;vertical-align:2px}
.orig{color:var(--dim);font-weight:400;font-size:14px;margin-left:9px}
.meta{color:var(--dim);font-size:13px;margin:0 0 10px}
.pred{margin:0 0 14px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.stars{color:var(--accent);font-size:15px;letter-spacing:1px}
.starnum{color:var(--dim);font-size:12px;margin-left:6px;letter-spacing:0}
.vote{font-size:11.5px;border-radius:99px;padding:2px 9px;font-weight:600;
 letter-spacing:.02em}
.vote--hi{background:rgba(46,125,50,.13);color:#2e7d32}
.vote--mid{background:rgba(150,120,20,.13);color:#8a6d1f}
.vote--lo{background:rgba(150,60,40,.13);color:#a04a2c}
@media (prefers-color-scheme:dark){.vote--hi{color:#7fc98a}
 .vote--mid{color:#d9bd6c}.vote--lo{color:#e0917a}}
.chip{font-size:11px;color:var(--dim);border:1px solid var(--line);
 border-radius:99px;padding:2px 9px}
.overview{margin:0 0 12px;font-size:14px;color:var(--dim)}
.why{margin:0 0 12px;font-size:14.5px;border-left:2px solid var(--accent);
 padding-left:14px}
.kill{margin:0 0 10px;font-size:13px;color:var(--dim)}
.warn{margin:0 0 10px;font-size:12.5px;color:#b4451f;background:rgba(180,69,31,.08);
 border-radius:7px;padding:8px 11px}
@media (prefers-color-scheme:dark){.warn{color:#f0906a;background:rgba(240,144,106,.1)}}
.risks{font-size:13px;color:var(--dim)}
.risks summary{cursor:pointer;user-select:none}
.risks ul{margin:6px 0 12px;padding-left:18px}
.risks li{margin-bottom:5px}
.dt{margin:12px 0 0;font-weight:600;color:var(--fg);opacity:.75;font-size:12.5px}
.verdict{margin-top:16px;display:flex;gap:7px;align-items:center;flex-wrap:wrap}
.v{font:inherit;font-size:12.5px;padding:4px 12px;border-radius:99px;cursor:pointer;
 border:1px solid var(--line);background:transparent;color:var(--dim)}
.v:hover{border-color:var(--accent);color:var(--accent)}
.v.on{background:var(--accent);border-color:var(--accent);color:#fff}
.recid{margin-left:auto;color:var(--dim);font-size:11px;font-variant-numeric:tabular-nums}
.section{margin:38px 0 16px;font-size:13px;color:var(--dim);
 text-transform:uppercase;letter-spacing:.08em}
.ask-group{margin:34px 0 16px;padding:14px 18px;border-radius:10px;
 background:var(--card);border:1px solid var(--line)}
.ask-head{margin:0 0 6px;font-size:11px;color:var(--dim);letter-spacing:.08em;
 text-transform:uppercase}
.ask-text{margin:0;font-size:13.5px;color:var(--dim);white-space:pre-wrap}
#bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);
 border-top:1px solid var(--line);padding:12px 20px;display:none;
 align-items:center;gap:14px;justify-content:center;font-size:13px}
#bar code{font-size:12px;color:var(--dim);overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap;max-width:52vw}
#bar button{font:inherit;font-size:12.5px;padding:5px 14px;border-radius:99px;
 border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}
@media (max-width:620px){.card{flex-direction:column}
 .poster{width:100%;min-width:0;height:auto;aspect-ratio:2/3;max-width:200px}}
"""

JS = """
const picks = new Map();
document.querySelectorAll('.v').forEach(b => b.onclick = () => {
  const id = b.dataset.id;
  b.parentElement.querySelectorAll('.v').forEach(o => o.classList.remove('on'));
  if (picks.get(id) === b.dataset.v) { picks.delete(id); }
  else { picks.set(id, b.dataset.v); b.classList.add('on'); }
  draw();
});
function cmd() {
  return [...picks].map(([id, v]) =>
    `python3 recommend/reclog.py --db media.db verdict --id ${id} --verdict ${v}`
  ).join(' && ');
}
function draw() {
  const bar = document.getElementById('bar');
  if (!picks.size) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  document.getElementById('cmd').textContent = cmd();
}
document.getElementById('copy').onclick = async (e) => {
  try { await navigator.clipboard.writeText(cmd());
        e.target.textContent = '已复制';
        setTimeout(() => e.target.textContent = '复制记录命令', 1600); }
  catch { const r = document.createRange();
          r.selectNode(document.getElementById('cmd'));
          getSelection().removeAllRanges(); getSelection().addRange(r); }
};
"""


def render_page(cards: list[dict], alsoran: list[dict], killed: list[dict],
                intention: str, when: str) -> str:
    body = "".join(render_card(c) for c in cards)
    if alsoran:
        body += ('<p class="section">也通过了，这次没选上</p>'
                 + "".join(render_card(c, dimmed=True) for c in alsoran))
    if killed:
        body += ('<p class="section">没通过评审</p>'
                 + "".join(render_card(c, dimmed=True) for c in killed))
    n = len(cards)
    return page_shell(f"推荐 · {when[:10]}", f'''<header>
  <h1>给你的 {n} 个推荐</h1>
  <p class="ask">{esc(intention)}</p>
  <p class="when">{esc(when)}</p>
</header>
{body}''')


def render_pending_page(groups: list[tuple[str, str, list[dict]]],
                        total: int) -> str:
    """Every un-verdicted prediction, grouped by the ask that produced it.

    Each group keeps its own ask visible, because a verdict only means
    something against the question that was asked — "Rear Window, 4.5★"
    is a different claim under 下饭剧 than under 最近的好看的电影."""
    body = ""
    for intention, when, cards in groups:
        body += (f'<div class="ask-group"><p class="ask-head">{esc(when)}</p>'
                 f'<p class="ask-text">{esc(intention)}</p></div>'
                 + "".join(render_card(c) for c in cards))
    return page_shell("待反馈的推荐", f'''<header>
  <h1>{total} 个待反馈的推荐</h1>
  <p class="ask">这些预测都已封存，等你的反应才能被打分。选一个反应，
底部会拼好命令。没看过也没兴趣的，选「不看」同样是有效信号。</p>
</header>
{body}''')


def page_shell(title: str, inner: str) -> str:
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
{inner}
</div>
<div id="bar"><code id="cmd"></code><button id="copy">复制记录命令</button></div>
<script>{JS}</script>
</body></html>'''


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--ids", default="")
    ap.add_argument("--pending", action="store_true",
                    help="render every prediction still awaiting a verdict, "
                         "across all asks — the view the verdict loop needs")
    ap.add_argument("--include-killed", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--open", dest="do_open", action="store_true")
    args = ap.parse_args()

    ids = [int(x) for x in args.ids.replace(" ", "").split(",") if x] or None
    con = connect(args.db)
    rows = fetch_rows(con, ids, args.include_killed, pending=args.pending)
    con.close()
    if not rows:
        sys.exit("no recommendations rows matched — nothing to render")

    cards = [card_of(r) for r in rows]
    meta = load_meta()
    key = tmdb_key()
    for c in cards:
        ensure_assets(c, meta, key, args.no_network)
    save_meta(meta)

    def by_rank(cs):
        return sorted(cs, key=lambda c: (c["rank"] is None, c["rank"] or 0, c["id"]))

    # `pitch_selected: false` on a survivor means the critic ranked it but
    # the pitch cap (or redundancy) kept it off the slate — it is not a
    # kill, so it stays on the page, below the fold rather than beside
    # the picks.
    live = by_rank([c for c in cards
                    if not c["killed"] and c["selected"] is not False])
    alsoran = by_rank([c for c in cards
                       if not c["killed"] and c["selected"] is False])
    dead = [c for c in cards if c["killed"]]

    intention = cards[0]["intention"]
    when = pretty(cards[0]["session_date"])

    out = Path(args.out) if args.out else (
        OUT_DIR / f"rec-{datetime.now():%Y%m%d-%H%M%S}.html")
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.pending:
        groups: list[tuple[str, str, list[dict]]] = []
        for c in cards:
            stamp = pretty(c["session_date"])
            if groups and groups[-1][0] == c["intention"]:
                groups[-1][2].append(c)
            else:
                groups.append((c["intention"], stamp, [c]))
        for _, _, gc in groups:
            gc.sort(key=lambda c: (c["rank"] is None, c["rank"] or 0, c["id"]))
        html_out = render_pending_page(groups, len(cards))
    else:
        html_out = render_page(live, alsoran, dead, intention, when)
    out.write_text(html_out, "utf-8")

    covered = sum(1 for c in cards if c.get("poster_file"))
    print(json.dumps({
        "out": str(out),
        "mode": "pending" if args.pending else "slate",
        "cards": len(cards) if args.pending else len(live),
        "asks": len(groups) if args.pending else 1,
        "also_survived": 0 if args.pending else len(alsoran),
        "killed_shown": 0 if args.pending else len(dead),
        "id_warnings": [f'#{c["id"]} {c["title"]}' for c in cards
                        if c.get("id_warning")],
        "covers": f"{covered}/{len(cards)}",
        "synopses": f"{sum(1 for c in cards if c.get('overview'))}/{len(cards)}",
    }, ensure_ascii=False))

    if args.do_open:
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
