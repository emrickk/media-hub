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

import tmdb as tmdb_client

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
        "enrichment": scout.get("enrichment", {}) or {},
        "evidence_density": scout.get("evidence_density", ""),
        "appetite": critic.get("predicted_appetite", ""),
        "appetite_case": (critic.get("appetite_case") or "").strip(),
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


def tmdb_credential() -> tmdb_client.Credential | None:
    return tmdb_client.load_credential(repo_root=HERE.parent)


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


def resolve_via_imdb(imdb_id: str, credential: tmdb_client.Credential) -> tuple[str, str] | None:
    """An imdb tt id -> the TMDB detail path for the same work. TMDB's
    /find is authoritative here, which is the whole point: it is a lookup
    at the source, not a guess."""
    try:
        data = tmdb_client.get_json(
            f"/find/{imdb_id}", credential, {"external_source": "imdb_id"})
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError,
            tmdb_client.CredentialError):
        return None
    if data.get("movie_results"):
        return f"/movie/{data['movie_results'][0]['id']}", "movie"
    if data.get("tv_results"):
        return f"/tv/{data['tv_results'][0]['id']}", "tv"
    return None


def tmdb_detail(ids: dict, credential: tmdb_client.Credential,
                kind: str = "") -> dict:
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
        resolved = resolve_via_imdb(str(ids["imdb"]), credential)
        if not resolved:
            return {}
        path, media = resolved
    else:
        return {}

    out: dict = {"media": media, "names": set()}
    for lang in ("zh-CN", "en-US"):
        try:
            data = tmdb_client.get_json(path, credential, {"language": lang})
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError,
                tmdb_client.CredentialError):
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


def ensure_assets(card: dict, meta: dict,
                  credential: tmdb_client.Credential | None,
                  no_network: bool) -> None:
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

    if credential and any(ids.get(k) for k in
                          ("tmdb_movie", "tmdb_tv", "tmdb", "imdb")):
        d = tmdb_detail(ids, credential, card["kind"])
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


def asset_problems(cards: list[dict], *, require_covers: bool = True) -> list[str]:
    """Return user-visible reasons a slate is not safe to publish."""
    problems = []
    for card in cards:
        if card.get("killed"):
            continue
        label = f'#{card.get("id")} {card.get("title")}'
        ids = card.get("external_ids") or {}
        if not any(str(ids.get(key) or "").strip()
                   for key in ("tmdb_movie", "tmdb_tv", "tmdb")):
            problems.append(f"{label}: missing verified TMDB identity")
        if card.get("id_warning"):
            problems.append(f"{label}: {card['id_warning']}")
        if require_covers and not card.get("poster_file"):
            problems.append(f"{label}: cover could not be fetched or found in cache")
    return problems


# --------------------------------------------------------------------------
# html
# --------------------------------------------------------------------------

KIND_LABEL = {"film": "Film", "tv": "TV", "show": "TV", "drama": "TV"}


def stars_html(stars) -> str:
    if stars is None:
        return ""
    full = int(stars)
    half = (stars - full) >= 0.5
    glyphs = "★" * full + ("½" if half else "")
    return f'<span class="stars" title="Predicted {stars:g} stars">{glyphs}</span>'


def shape_line(card: dict) -> str:
    s = card.get("shape") or {}
    bits = []
    if s.get("seasons"):
        count = s["seasons"]
        bits.append(f"{count} season{'s' if count != 1 else ''}")
    if s.get("episodes"):
        bits.append(f"{s['episodes']} episodes")
    if s.get("ep_runtime_min"):
        bits.append(f"{s['ep_runtime_min']}-min episodes")
    elif s.get("runtime_min"):
        bits.append(f"{s['runtime_min']} min")
    return " · ".join(bits)


def esc(t) -> str:
    return html.escape(str(t or ""))


def pretty(stamp: str) -> str:
    try:
        return datetime.fromisoformat(stamp).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return stamp or ""


def compact_number(value) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}m".replace(".0m", "m")
    if number >= 1_000:
        return f"{number / 1_000:.1f}k".replace(".0k", "k")
    return f"{number:,}"


def initials(title: str) -> str:
    words = re.findall(r"[0-9A-Za-z]+", title or "")
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return (words[0][:2] if words else "?").upper()


def tmdb_href(card: dict) -> str:
    ids = card.get("external_ids") or {}
    if ids.get("tmdb_movie"):
        return f"https://www.themoviedb.org/movie/{esc(ids['tmdb_movie'])}"
    if ids.get("tmdb_tv"):
        return f"https://www.themoviedb.org/tv/{esc(ids['tmdb_tv'])}"
    if ids.get("tmdb"):
        media_type = "movie" if card.get("kind") == "film" else "tv"
        return f"https://www.themoviedb.org/{media_type}/{esc(ids['tmdb'])}"
    return ""


def poster_html(card: dict, compact: bool = False) -> str:
    poster = data_uri(card.get("poster_file"))
    rank = (f'<span class="poster-rank">{esc(card["rank"])}</span>'
            if card.get("rank") and not compact else "")
    if poster:
        art = (f'<img class="poster" src="{poster}" '
               f'alt="Poster for {esc(card["title"])}">')
    else:
        art = (f'<div class="poster poster--empty" role="img" '
               f'aria-label="No poster available for {esc(card["title"])}">'
               f'<strong>{esc(initials(card["title"]))}</strong>'
               f'<span>Cover unavailable</span></div>')
    return f'<div class="poster-shell">{art}{rank}</div>'


def source_rating_html(card: dict) -> str:
    vote = card.get("vote")
    href = tmdb_href(card)
    if vote is None and not href:
        return ""
    label = "TMDB"
    if vote is not None:
        label += f" {vote:g}"
        count = compact_number(card.get("votes"))
        if count:
            label += f" · {count}"
    if href:
        return (f'<a class="source-rating" href="{href}" target="_blank" '
                f'rel="noreferrer">{esc(label)}</a>')
    return f'<span class="source-rating">{esc(label)}</span>'


def prediction_html(card: dict) -> str:
    details = []
    if card.get("stars") is not None:
        details.append(f'{card["stars"]:g} predicted')
    if card.get("confidence"):
        details.append(f'{card["confidence"]} confidence')
    if card.get("percentile") is not None:
        cell = card.get("cell_label") or "comparable works you rate"
        details.append(f'{card["percentile"]:g}th percentile of {cell}')
    if card.get("appetite"):
        details.append(f'{card["appetite"]} start appetite')
    if not details and card.get("stars") is None:
        details.append("Provisional cold-start judgment")
    return (f'<div class="prediction">{stars_html(card.get("stars"))}'
            f'<span>{esc(" · ".join(details))}</span></div>')


def render_enrichment(card: dict) -> str:
    enrichment = card.get("enrichment") or {}
    if not enrichment:
        return ""

    parts = []
    summary = enrichment.get("summary")
    if summary:
        parts.append('<section class="about" aria-label="What it is">'
                     '<h3 class="plain-label">What it is</h3>'
                     f'<p>{esc(summary)}</p></section>')

    reason_columns = []
    for label, key, css in (("What makes it special", "special", "special"),
                            ("Why I picked it for you", "personal_hook", "fit")):
        if enrichment.get(key):
            reason_columns.append(
                f'<section class="recommendation-point recommendation-point--{css}">'
                f'<h3 class="plain-label">{label}</h3>'
                f'<p>{esc(enrichment[key])}</p></section>')
    if reason_columns:
        parts.append('<div class="compact-copy">' + "".join(reason_columns) + '</div>')

    if enrichment.get("good_to_know"):
        parts.append('<p class="entry-line"><span>Good to know</span>'
                     f'{esc(enrichment["good_to_know"])}</p>')

    entry = enrichment.get("entry") or {}
    if entry.get("applicable") and any(entry.get(key) for key in
                                        ("start_at", "why", "exit_test")):
        line = []
        if entry.get("start_at"):
            line.append(f'<strong>{esc(entry["start_at"])}</strong>')
        if entry.get("why"):
            line.append(esc(entry["why"]))
        if entry.get("exit_test"):
            line.append(f'Exit test: {esc(entry["exit_test"])}')
        parts.append('<p class="entry-line"><span title="Where to start">Start</span>'
                     + " — ".join(line) + "</p>")

    inside = enrichment.get("inside") or {}
    moments = [moment for moment in inside.get("moments", []) if moment]
    quotes = [quote for quote in inside.get("quotes", []) if isinstance(quote, dict)
              and quote.get("text")]
    if moments or quotes:
        items = "".join(f"<li>{esc(moment)}</li>" for moment in moments)
        quote_html = "".join(
            f'<blockquote>“{esc(quote["text"])}”'
            + (f'<cite>— {esc(quote.get("speaker"))}</cite>' if quote.get("speaker") else "")
            + "</blockquote>" for quote in quotes)
        parts.append('<details class="inside"><summary>Inside it</summary>'
                     + (f"<ul>{items}</ul>" if items else "") + quote_html + "</details>")

    reception = enrichment.get("reception")
    if reception:
        parts.append(f'<p class="reception">{esc(reception)}</p>')
    ratings = enrichment.get("ratings") or []
    valid_ratings = [rating for rating in ratings if isinstance(rating, dict)
                     and rating.get("source") and rating.get("value")]
    if valid_ratings:
        parts.append('<p class="external-ratings">' + "".join(
            f'<span>{esc(rating["source"])} {esc(rating["value"])}</span>'
            for rating in valid_ratings) + "</p>")
    if enrichment.get("knowledge") == "thin":
        parts.append('<p class="knowledge">Knowledge is thin — specifics are intentionally limited.</p>')
    return "".join(parts)


def critic_notes_html(card: dict) -> str:
    items = []
    if card.get("selection_reason"):
        items.append(card["selection_reason"])
    items.extend(list(card.get("evidence_chain") or [])[:3])
    items.extend(f"Risk: {risk}" for risk in list(card.get("risks") or [])[:2])
    if card.get("id_warning"):
        items.append(f'Identity warning: {card["id_warning"]}')
    if not items:
        return ""
    return ('<details class="critic-notes"><summary>Critic notes</summary><ul>'
            + "".join(f'<li>{esc(item)}</li>' for item in items) + '</ul></details>')


def feedback_html(card: dict, compact: bool = False) -> str:
    labels = [("start", "▶ Start now"), ("bookmark", "＋ Bookmark"),
              ("wrong_title", "× Wrong title")]
    if not compact:
        labels.append(("weak_pitch", "≈ Weak pitch"))
    labels.append(("seen", "✓ Already seen"))
    buttons = "".join(
        f'<button class="reaction" data-reaction="{reaction}" data-id="{card["id"]}" '
        f'title="{esc(label.lstrip("▶＋×≈✓ "))}">{label}</button>'
        for reaction, label in labels)
    note = "" if compact else (
        f'<textarea class="feedback-note" data-note data-id="{card["id"]}" '
        f'placeholder="What specifically attracted or lost you? (optional)"></textarea>')
    return (f'<div class="feedback" data-card-id="{card["id"]}">{buttons}'
            f'<span class="reaction-status" data-status>No reaction</span>{note}</div>')


def render_card(card: dict, dimmed: bool = False) -> str:
    compact = dimmed
    meta_bits = []
    if card["year"]:
        meta_bits.append(str(card["year"]))
    meta_bits.append(KIND_LABEL.get(card["kind"], card["kind"]))
    sl = shape_line(card)
    if sl:
        meta_bits.append(sl)
    orig = card["original_title"]
    orig_html = (f'<span class="orig">{esc(orig)}</span>'
                 if orig and orig != card["title"] else "")
    enrichment = card.get("enrichment") or {}
    overview = card.get("overview") or ""
    fallback = overview or card.get("case") or card.get("ask_fit") or ""

    if compact:
        summary = enrichment.get("summary") or fallback
        held_back = card.get("selection_reason") or card.get("appetite_case") or "Passed review; held outside this slate's pitch cap."
        return f'''<article class="slate-card slate-card--secondary" data-card="{card["id"]}" data-title="{esc(card["title"])}">
  {poster_html(card, compact=True)}
  <div class="card-body">
    <div class="title-row"><div><h2>{esc(card["title"])}{orig_html}</h2>
      <p class="meta">{esc(" · ".join(meta_bits))}{f' · {card["stars"]:g} predicted' if card.get("stars") is not None else ''}</p></div>
      {source_rating_html(card)}</div>
    {f'<p class="secondary-copy">{esc(summary)}</p>' if summary else ''}
    <p class="held-back">{esc(held_back)}</p>
    {feedback_html(card, compact=True)}
  </div>
</article>'''

    legacy = ""
    if not enrichment:
        if fallback:
            legacy += ('<section class="about" aria-label="What it is">'
                       '<h3 class="plain-label">What it is</h3>'
                       f'<p>{esc(fallback)}</p></section>')
        legacy_hook = card.get("case") or card.get("ask_fit") or ""
        if legacy_hook and legacy_hook != fallback:
            legacy += ('<div class="compact-copy compact-copy--single">'
                       '<section class="recommendation-point recommendation-point--personal">'
                       '<h3 class="plain-label">Why I picked it for you</h3>'
                       f'<p>{esc(legacy_hook)}</p></section></div>')
    return f'''<article class="slate-card slate-card--primary" data-card="{card["id"]}" data-title="{esc(card["title"])}">
  {poster_html(card)}
  <div class="card-body">
    <div class="title-row"><div><h2>{esc(card["title"])}{orig_html}</h2>
      <p class="meta">{esc(" · ".join(meta_bits))}</p></div>
      {source_rating_html(card)}</div>
    {prediction_html(card)}
    {legacy}{render_enrichment(card)}
    {critic_notes_html(card)}
    {feedback_html(card)}
  </div>
</article>'''


def render_killed_card(card: dict) -> str:
    meta = " · ".join(str(x) for x in (card.get("year"), KIND_LABEL.get(card.get("kind"), card.get("kind"))) if x)
    reason = card.get("kill_reason") or card.get("selection_reason") or "The critic found insufficient support."
    return f'''<article class="rejected-row">
  <div class="rejected-head"><h2>{esc(card["title"])}</h2><span>{esc(meta)}</span></div>
  <span class="killed">Killed</span>
  <p>{esc(reason)}</p>
</article>'''


CSS = """
:root{--paper:#f2ecdf;--paper-deep:#e7dcc8;--ink:#151411;--red:#d54b30;
 --yellow:#e3b54a;--blue:#315d78;--quiet:#736d61;--line:rgba(21,20,17,.17);
 --line-strong:rgba(21,20,17,.32);--serif:'Iowan Old Style','Baskerville','Palatino Linotype',Palatino,serif;
 --sans:'Avenir Next','Archivo','Gill Sans',sans-serif;--mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth;background:var(--paper)}
body{margin:0;color:var(--ink);background:radial-gradient(circle at 12% 8%,rgba(213,75,48,.08),transparent 24rem),
 radial-gradient(circle at 91% 22%,rgba(49,93,120,.09),transparent 28rem),var(--paper);
 font-family:var(--sans);font-size:16px;line-height:1.5;-webkit-font-smoothing:antialiased;padding-bottom:76px}
body::before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.2;z-index:30;
 background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.1'/%3E%3C/svg%3E");mix-blend-mode:multiply}
button,input,textarea{font:inherit}button{touch-action:manipulation}a{color:inherit}
.wrap{max-width:1280px;margin:0 auto;padding:32px clamp(22px,5vw,72px) 0}.slate-header{animation:rise .5s ease both}
.mast{display:flex;justify-content:space-between;align-items:baseline;gap:24px}.brand{display:flex;align-items:center;
 gap:9px;font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}.brand-dot{width:9px;height:9px;background:var(--red)}
.sealed{font:10px var(--mono);letter-spacing:.1em;color:var(--quiet);text-transform:uppercase;font-variant-numeric:tabular-nums}
.slate-header h1{max-width:920px;margin:42px 0 15px;font-family:var(--serif);font-size:clamp(48px,7vw,90px);
 font-weight:400;line-height:.92;letter-spacing:-.055em;text-wrap:balance}.ask{max-width:780px;margin:0 0 34px;color:var(--quiet);
 font-size:14px;white-space:pre-wrap;text-wrap:pretty}.header-rule{height:2px;background:var(--ink)}
.slate-card{border-bottom:1px solid var(--line);animation:rise .55s ease both}.slate-card--primary{display:grid;
 grid-template-columns:minmax(190px,270px) minmax(0,1fr);gap:clamp(32px,5vw,68px);padding:clamp(52px,7vw,88px) 0}
.slate-card--secondary{display:grid;grid-template-columns:76px minmax(0,1fr);gap:22px;padding:24px 0;opacity:.76}
.poster-shell{position:relative;width:100%;height:auto;aspect-ratio:2/3;align-self:start}.poster-shell::before{content:"";
 position:absolute;inset:13px -13px -13px 13px;border:1px solid var(--ink);z-index:-1}.poster{display:block;width:100%;height:100%;
 object-fit:cover;background:var(--paper-deep);filter:saturate(.9) contrast(1.03);transition:transform .24s ease,filter .24s ease}
.poster-shell:hover .poster{transform:translate(-3px,-3px);filter:saturate(1) contrast(1.04)}.poster--empty{display:flex;
 flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--quiet)}.poster--empty strong{font:44px var(--serif);
 color:rgba(21,20,17,.24)}.poster--empty span{font:9px/1.5 var(--mono);letter-spacing:.08em;text-transform:uppercase}
.poster-rank{display:flex;align-items:center;justify-content:center;position:absolute;top:-12px;left:-12px;min-width:44px;height:44px;
 padding:0 10px;background:var(--red);color:#fff;font:700 11px var(--mono)}.slate-card--secondary .poster-shell{width:76px}
.slate-card--secondary .poster-shell::before{inset:6px -6px -6px 6px}.slate-card--secondary .poster-rank{display:none}
.slate-card--secondary .poster--empty strong{font-size:20px}.slate-card--secondary .poster--empty span{display:none}.card-body{min-width:0}
.title-row{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;flex-wrap:wrap}h2{margin:0;font-family:var(--serif);
 font-size:clamp(40px,5.2vw,68px);font-weight:400;line-height:.96;letter-spacing:-.045em;text-wrap:balance}
.slate-card--secondary h2,.rejected-row h2{font-family:var(--serif);font-size:21px;letter-spacing:-.015em}.orig{display:block;
 margin:7px 0 0;color:var(--quiet);font-family:var(--sans);font-size:13px;font-weight:400;letter-spacing:0}.meta{margin:8px 0 0;
 color:var(--quiet);font-size:12px;letter-spacing:.06em;text-transform:uppercase}.source-rating{flex:none;display:grid;padding:9px 12px 8px;
 border:1px solid var(--ink);color:var(--ink);font:11px/1.35 var(--mono);text-decoration:none;white-space:nowrap;transition:background .18s ease,
 color .18s ease,transform .18s ease}.source-rating:hover{background:var(--ink);color:var(--paper);transform:translateY(-2px)}
.prediction{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-top:13px}.prediction>span:last-child{color:var(--quiet);
 font-size:11.5px}.stars{color:var(--red);font-size:15px;letter-spacing:2px}.about{max-width:930px;margin:28px 0 30px;
 padding-left:clamp(18px,3vw,30px);border-left:5px solid var(--red)}.about .plain-label{margin-bottom:7px}.about p{margin:0;
 font-family:var(--serif);font-size:clamp(23px,2.5vw,32px);line-height:1.18;text-wrap:pretty}.plain-label{display:block;margin:0 0 7px;
 color:var(--blue);font-family:var(--sans);font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
.compact-copy{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(240px,.85fr);gap:18px;max-width:980px}
.compact-copy--single{grid-template-columns:minmax(0,720px)}.recommendation-point{margin:0;padding:19px 20px;border-top:1px solid var(--line);
 background:rgba(255,255,255,.2)}.recommendation-point--fit,.recommendation-point--personal{background:rgba(49,93,120,.1)}
.recommendation-point p{margin:0;font-size:14px;line-height:1.6;text-wrap:pretty}.entry-line{max-width:820px;margin:14px 0 0;
 color:var(--quiet);font-size:12.5px}.entry-line>span{margin-right:9px;color:var(--blue);font-size:10px;font-weight:700;
 letter-spacing:.11em;text-transform:uppercase}.entry-line strong{color:var(--ink)}.inside,.critic-notes{max-width:820px;margin-top:13px;
 color:var(--quiet);font-size:12.5px}.inside summary,.critic-notes summary{color:var(--blue);font-size:10px;font-weight:700;
 letter-spacing:.11em;text-transform:uppercase;cursor:pointer;user-select:none}.inside ul,.critic-notes ul{display:flex;flex-direction:column;
 gap:4px;margin:8px 0 0;padding-left:18px}.inside blockquote{margin:9px 0 0;padding-left:13px;border-left:2px solid var(--red);
 font-family:var(--serif);font-size:17px}.inside cite{display:block;color:var(--quiet);font:10px var(--mono)}.reception,.knowledge{
 max-width:820px;margin:10px 0 0;color:var(--quiet);font-size:11.5px}.external-ratings{display:flex;gap:8px;flex-wrap:wrap;
 margin:11px 0 0}.external-ratings span{padding:3px 7px;border:1px solid var(--line);color:var(--quiet);font:10px var(--mono)}
.feedback{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:22px;padding-top:18px;border-top:1px solid var(--line)}
.reaction{padding:8px 13px;border:1px solid var(--line-strong);background:transparent;color:var(--ink);font-size:12px;font-weight:600;
 cursor:pointer;transition:border-color .2s ease,color .2s ease,background .2s ease,transform .15s ease}.reaction:hover{border-color:var(--ink);
 transform:translateY(-1px)}.reaction:active{transform:scale(.98)}.reaction:focus-visible,.source-rating:focus-visible,input:focus-visible,
textarea:focus-visible{outline:2px solid var(--blue);outline-offset:2px}.reaction.on{border-color:var(--ink);background:var(--ink);color:var(--paper)}
.reaction.on[data-reaction=start],.reaction.on[data-reaction=bookmark]{border-color:var(--red);background:var(--red);color:#fff}
.reaction-status{margin-left:auto;color:var(--quiet);font:9.5px/1.4 var(--mono);letter-spacing:.1em;text-transform:uppercase}
.feedback-note{width:100%;min-height:48px;margin-top:2px;padding:10px 12px;border:1px solid var(--line);background:rgba(255,255,255,.22);
 color:var(--ink);font-size:12.5px;resize:vertical}.secondary-copy{max-width:720px;margin:7px 0 0;color:var(--ink);font-size:13px}
.held-back{max-width:720px;margin:5px 0 0;color:var(--quiet);font-size:11.5px;font-style:italic;display:-webkit-box;
 -webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden}.slate-card--secondary .meta{font-size:10.5px}.slate-card--secondary .source-rating{
 padding:0;border:0}.slate-card--secondary .feedback{margin-top:11px;padding-top:0;border:0}.slate-card--secondary .reaction{padding:5px 9px;
 font-size:11px}.slate-card--secondary .reaction-status{font-size:9px}.section-title{margin:44px 0 0;padding-bottom:11px;
 border-bottom:2px solid var(--ink);color:var(--quiet);font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
.rejected-row{position:relative;padding:22px 0;border-bottom:1px solid var(--line);opacity:.65}.rejected-head{display:flex;align-items:baseline;
 gap:9px}.rejected-head span{color:var(--quiet);font-size:12px}.killed{position:absolute;top:24px;right:0;color:var(--red);
 font:9.5px var(--mono);letter-spacing:.1em;text-transform:uppercase}.rejected-row p{max-width:760px;margin:7px 0 0;color:var(--quiet);
 font-size:12.5px;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:4;overflow:hidden}.ask-group{margin:42px 0 0;
 padding-bottom:12px;border-bottom:2px solid var(--ink)}.ask-head{margin:0;color:var(--red);font:10px var(--mono);letter-spacing:.1em;
 text-transform:uppercase}.ask-text{max-width:760px;margin:6px 0 0;color:var(--quiet);font-size:13px;white-space:pre-wrap}
.slate-footer{display:flex;justify-content:space-between;gap:30px;padding:30px 0 110px;color:var(--quiet);font-size:11.5px}
.feedback-dock{position:fixed;z-index:20;left:0;right:0;bottom:0;border-top:1px solid var(--line-strong);background:rgba(242,236,223,.94);
 backdrop-filter:blur(12px)}.dock-inner{display:flex;align-items:center;gap:14px;max-width:1280px;margin:0 auto;padding:11px clamp(22px,5vw,72px)}
#count{color:var(--quiet);font:10px var(--mono);letter-spacing:.08em;white-space:nowrap;text-transform:uppercase}#overall{flex:1;
 min-width:0;padding:9px 12px;border:1px solid var(--line-strong);background:rgba(255,255,255,.28);color:var(--ink);font-size:12.5px}
#copy{padding:9px 16px;border:1px solid var(--ink);background:var(--ink);color:var(--paper);font-size:12.5px;font-weight:700;
 cursor:pointer;white-space:nowrap;transition:background .2s ease,color .2s ease,transform .15s ease}#copy:hover{background:var(--red);
 border-color:var(--red);color:#fff}#copy:active{transform:scale(.98)}::placeholder{color:#8d877d}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){
 *,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important;scroll-behavior:auto!important}}
@media(max-width:820px){.slate-card--primary{grid-template-columns:160px minmax(0,1fr);gap:28px}.compact-copy{grid-template-columns:1fr}
 .sealed{display:none}.about p{font-size:23px}}@media(max-width:580px){body{padding-bottom:132px}.wrap{padding:24px 20px 0}
 .slate-header h1{margin-top:34px;font-size:48px}.slate-card--primary{grid-template-columns:1fr;padding:46px 0}.poster-shell{width:min(220px,64vw)}
 .title-row{display:block}.source-rating{display:inline-block;margin-top:12px}h2{font-size:44px}.about{margin-top:24px}.compact-copy{gap:12px}
 .feedback{gap:6px}.reaction-status{width:100%;margin:2px 0 0}.dock-inner{flex-wrap:wrap;gap:8px;padding:10px 20px}#count{width:100%}
 #overall{min-width:160px}.slate-footer{display:block}.slate-footer span{display:block;margin-bottom:8px}}
"""

JS = """
const storageKey = `media-hub-feedback:${document.title}`;
let saved;
try { saved = JSON.parse(localStorage.getItem(storageKey) || '{"cards":{},"overall":""}'); }
catch (_) { saved = {cards: {}, overall: ''}; }
const cards = saved.cards || {};
function persist() { saved.cards = cards; saved.overall = document.getElementById('overall').value;
  localStorage.setItem(storageKey, JSON.stringify(saved)); draw(); }
const labels = {start:'Start now', bookmark:'Bookmark', wrong_title:'Wrong title',
  weak_pitch:'Weak pitch', seen:'Already seen'};
document.querySelectorAll('.reaction').forEach(b => {
  const id = b.dataset.id;
  if (cards[id]?.reaction === b.dataset.reaction) b.classList.add('on');
  b.onclick = () => {
    const current = cards[id] || {};
    current.reaction = current.reaction === b.dataset.reaction ? '' : b.dataset.reaction;
    cards[id] = current;
    b.parentElement.querySelectorAll('.reaction').forEach(o =>
      o.classList.toggle('on', o.dataset.reaction === current.reaction));
    const status = b.parentElement.querySelector('[data-status]');
    if (status) status.textContent = current.reaction ? labels[current.reaction] : 'No reaction';
    persist();
  };
});
document.querySelectorAll('.feedback-note').forEach(note => {
  const id = note.dataset.id; note.value = cards[id]?.note || '';
  note.oninput = () => { const current = cards[id] || {}; current.note = note.value;
    cards[id] = current; persist(); };
});
function packet() {
  return {schema: 'media-hub-feedback-v1', overall: document.getElementById('overall').value,
    feedback: Object.entries(cards).filter(([,v]) => v.reaction || (v.note || '').trim()).map(([id,v]) =>
      ({id: Number(id), reaction: v.reaction || 'note', note: v.note || ''}))};
}
function copyText() {
  return `Media Hub feedback\n\n${JSON.stringify(packet(), null, 2)}\n\n` +
    `Record this packet with: python3 recommend/reclog.py --db media.db feedback --json <packet.json>`;
}
function draw() {
  const count = Object.values(cards).filter(v => v.reaction || (v.note || '').trim()).length;
  document.getElementById('count').textContent = `${count} reaction${count === 1 ? '' : 's'}`.toUpperCase();
}
document.getElementById('overall').value = saved.overall || '';
document.getElementById('overall').oninput = persist;
document.querySelectorAll('[data-card]').forEach(card => {
  const state = cards[card.dataset.card] || {};
  const status = card.querySelector('[data-status]');
  if (status) status.textContent = state.reaction ? labels[state.reaction] : 'No reaction';
});
document.getElementById('copy').onclick = async (e) => {
  try { await navigator.clipboard.writeText(copyText());
        e.target.textContent = 'Copied';
        setTimeout(() => e.target.textContent = 'Copy feedback for Codex / Claude', 1600); }
  catch { const helper = document.createElement('textarea'); helper.value = copyText();
    document.body.appendChild(helper); helper.select(); document.execCommand('copy'); helper.remove(); }
};
draw();
"""


def render_page(cards: list[dict], alsoran: list[dict], killed: list[dict],
                intention: str, when: str) -> str:
    body = "".join(render_card(c) for c in cards)
    if alsoran:
        body += ('<p class="section-title">Also passed review — not selected this time</p>'
                 + "".join(render_card(c, dimmed=True) for c in alsoran))
    if killed:
        body += ('<p class="section-title">Rejected by the critic</p>'
                 + "".join(render_killed_card(c) for c in killed))
    n = len(cards)
    slate = cards[0]["id"] if cards else "—"
    noun = "pick" if n == 1 else "picks"
    return page_shell(f"Recommendation slate · {when[:10]}", f'''<header class="slate-header">
  <div class="mast"><div class="brand"><span class="brand-dot"></span>Media Hub</div>
    <span class="sealed">SLATE {slate} · SEALED {esc(when)}</span></div>
  <h1>{n} {noun} for tonight</h1>
  <p class="ask">Your ask: “{esc(intention)}” Every pick survived a blind critic — react below and the next slate gets sharper.</p>
  <div class="header-rule"></div>
</header>
{body}
<footer class="slate-footer"><span>Generated locally from your permitted history. Profiles, ratings, and covers never leave this machine.</span>
<span>External scores may drift after this slate was sealed.</span></footer>''')


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
    return page_shell("Recommendations awaiting feedback", f'''<header class="slate-header">
  <div class="mast"><div class="brand"><span class="brand-dot"></span>Media Hub</div>
    <span class="sealed">Pending feedback</span></div>
  <h1>{total} recommendation{'s' if total != 1 else ''} awaiting feedback</h1>
  <p class="ask">These predictions are sealed. Your reactions are what make the next slate more accurate.</p>
  <div class="header-rule"></div>
</header>
{body}''')


def page_shell(title: str, inner: str) -> str:
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="A private, locally generated recommendation slate.">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&amp;family=JetBrains+Mono:wght@400;700&amp;display=swap" rel="stylesheet">
<style>{CSS}</style></head>
<body><div class="wrap">
{inner}
<p class="tmdb-attribution"><a href="https://www.themoviedb.org" target="_blank" rel="noreferrer">TMDB</a> · This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
</div>
<div class="feedback-dock"><div class="dock-inner"><span id="count">0 reactions</span>
 <input id="overall" type="text" aria-label="Overall slate feedback"
 placeholder="Anything true across several recommendations?">
 <button id="copy">Copy feedback for Codex / Claude</button></div></div>
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
    ap.add_argument("--allow-missing-covers", action="store_true",
                    help="explicit exception for a title known to have no poster; "
                         "identity mismatches still fail")
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
    credential = tmdb_credential()
    for c in cards:
        ensure_assets(c, meta, credential, args.no_network)
    save_meta(meta)

    problems = asset_problems(cards, require_covers=not args.allow_missing_covers)
    if problems:
        setup = ""
        if not credential and any("cover" in problem.lower() for problem in problems):
            setup = ("\nTMDB credential is missing. Create a free API Read Access Token at "
                     f"{tmdb_client.SETTINGS_URL}, then save it in "
                     "profile/tmdb.env as TMDB_READ_ACCESS_TOKEN=...")
        sys.exit("recommendation page is incomplete; no HTML was written:\n  - "
                 + "\n  - ".join(problems) + setup)

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
