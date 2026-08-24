#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=10", "requests>=2.32"]
# ///
"""Build review.html: an identity & duplicates review of media.db.

Three sections, all generated from the canonical store:
  1. identity coverage — kind x namespace matrix, anchor quality summary
  2. needs attention — douban-only items, documented negatives
  3. duplicate candidates — match_queue pending pairs + a cross-name
     heuristic (works of the same kind sharing any name key, where at most
     one side has a douban id; two douban ids = two Douban subjects =
     editions/remakes, excluded by design)

Every pair has a stable id (Q<n> for queue, H<n> for heuristic) and
merge / keep-both / unsure buttons; "export decisions" copies a JSON
verdict list to paste back into a Claude session, which then applies it
via the match_queue / _merge_works machinery. The page itself never
touches the database.

Thumbnails are embedded as data URIs (the page is fully self-contained).
"""

from __future__ import annotations

import base64
import html
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import re

from mediahub import norm_title, open_db  # noqa: E402

# Season markers survive as aliases from the old series-merge era; as name
# keys they pair every show with every other show. Never keys.
_JUNK_KEY = re.compile(
    r"^(\d*a?(season|saison|temporada|staffel|stagione|sezon|saeson|sæson|"
    r"seizoen|kausi|sasong|сезон)\d*|シーズン\d*|시즌\d*|"
    r"第[一二三四五六七八九十百零\d]+季|specials?|限定剧|迷你剧|\d{1,4})$"
)

HERE = Path(__file__).resolve().parent
SPACE = HERE.parent
OUT = HERE / "review.html"

ANCHOR_ORDER = ["douban", "imdb", "tmdb_movie", "tmdb_tv", "isbn", "weread",
                "steam", "psn", "psn_npwr", "neodb", "letterboxd", "plex_guid"]


def thumb(conn, wid: int, cache: dict) -> str:
    if wid in cache:
        return cache[wid]
    row = conn.execute(
        "SELECT file FROM covers WHERE work_id=? AND preferred=1 LIMIT 1", (wid,)
    ).fetchone()
    uri = ""
    if row:
        from PIL import Image

        p = SPACE / row["file"]
        if p.exists():
            try:
                with Image.open(p) as im:
                    im = im.convert("RGB")
                    im.thumbnail((90, 120))
                    buf = io.BytesIO()
                    im.save(buf, "JPEG", quality=68)
                    uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            except Exception:
                uri = ""
    cache[wid] = uri
    return uri


def ids_of(conn, wid: int) -> list[tuple[str, str]]:
    return [
        (r["namespace"], r["value"])
        for r in conn.execute(
            "SELECT namespace, value FROM external_ids WHERE work_id=? ORDER BY namespace",
            (wid,),
        )
    ]


def work_card(conn, wid: int, cache: dict) -> str:
    w = conn.execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone()
    if w is None:
        return f"<div class='work'><div class='w-info'>#{wid} (deleted)</div></div>"
    img = thumb(conn, wid, cache)
    img_html = (f"<img src='{img}' alt=''>" if img
                else "<div class='noimg'></div>")
    idchips = "".join(
        f"<span class='chip'>{html.escape(ns)}:{html.escape(v[:22])}</span>"
        for ns, v in ids_of(conn, wid)
    ) or "<span class='chip none'>no external ids</span>"
    season = f" · S{w['season_number']}" if w["season_number"] else ""
    year = f" · {w['year']}" if w["year"] else ""
    en = (f"<div class='sub'>{html.escape(w['title_en'] or w['original_title'] or '')}</div>"
          if (w["title_en"] or w["original_title"]) else "")
    recs = conn.execute(
        "SELECT source, status FROM records WHERE work_id=? ORDER BY source", (wid,)
    ).fetchall()
    src = ", ".join(f"{r['source']}/{r['status']}" for r in recs) or "no records"
    return (f"<div class='work'>{img_html}<div class='w-info'>"
            f"<div class='w-title'>#{w['id']} {html.escape(w['title'])}"
            f"<span class='dim'>{season}{year} · {w['kind']}</span></div>{en}"
            f"<div class='chips'>{idchips}</div>"
            f"<div class='sub dim'>{html.escape(src)}</div></div></div>")


def coverage(conn) -> str:
    kinds = [r["kind"] for r in conn.execute(
        "SELECT kind, COUNT(*) n FROM works GROUP BY kind ORDER BY n DESC")]
    totals = {r["kind"]: r["n"] for r in conn.execute(
        "SELECT kind, COUNT(*) n FROM works GROUP BY kind")}
    cov = defaultdict(dict)
    for r in conn.execute(
        """SELECT w.kind, e.namespace, COUNT(DISTINCT w.id) n
           FROM works w JOIN external_ids e ON e.work_id=w.id
           GROUP BY w.kind, e.namespace"""):
        cov[r["kind"]][r["namespace"]] = r["n"]
    multi = {r["kind"]: r["n"] for r in conn.execute(
        """SELECT kind, COUNT(*) n FROM works w
           WHERE (SELECT COUNT(DISTINCT namespace) FROM external_ids e
                  WHERE e.work_id=w.id) >= 2 GROUP BY kind""")}
    none = {r["kind"]: r["n"] for r in conn.execute(
        """SELECT kind, COUNT(*) n FROM works w
           WHERE NOT EXISTS (SELECT 1 FROM external_ids e WHERE e.work_id=w.id)
           GROUP BY kind""")}
    head = "".join(f"<th>{ns}</th>" for ns in ANCHOR_ORDER)
    rows = []
    for k in kinds:
        cells = "".join(
            f"<td>{cov[k].get(ns, '') or '·'}</td>" for ns in ANCHOR_ORDER)
        pct = round(100 * multi.get(k, 0) / totals[k])
        rows.append(
            f"<tr><td class='k'>{k}</td><td>{totals[k]}</td>{cells}"
            f"<td>{multi.get(k, 0)} ({pct}%)</td>"
            f"<td class='{'bad' if none.get(k) else ''}'>{none.get(k, 0)}</td></tr>")
    return (f"<table><tr><th>kind</th><th>works</th>{head}"
            f"<th>2+ namespaces</th><th>zero ids</th></tr>{''.join(rows)}</table>")


def name_keys(conn, w) -> set[str]:
    keys = {norm_title(w["title"]), norm_title(w["original_title"] or ""),
            norm_title(w["title_en"] or "")}
    for a in conn.execute("SELECT alias FROM work_aliases WHERE work_id=?", (w["id"],)):
        keys.add(norm_title(a["alias"]))
    keys.discard("")
    return keys


def heuristic_pairs(conn) -> list[tuple[int, int, str]]:
    """Same kind + shared name key + at most one douban id. Excludes music
    (uncleaned) and anything already in match_queue in any state."""
    queued = {tuple(sorted((r["work_a"], r["work_b"])))
              for r in conn.execute("SELECT work_a, work_b FROM match_queue")}
    has_douban = {r["work_id"] for r in conn.execute(
        "SELECT work_id FROM external_ids WHERE namespace='douban'")}
    by_key: dict[tuple[str, str], list] = defaultdict(list)
    for w in conn.execute(
        "SELECT id, kind, title, original_title, title_en FROM works"
        " WHERE kind IN ('film','tv','show','book','game')"):
        for key in name_keys(conn, w):
            if len(key) >= 4 and not _JUNK_KEY.match(key):
                by_key[(w["kind"], key)].append(w["id"])
    pairs = {}
    for (kind, key), wids in by_key.items():
        wids = sorted(set(wids))
        if len(wids) < 2:
            continue
        for i, a in enumerate(wids):
            for b in wids[i + 1:]:
                if (a, b) in queued or (a, b) in pairs:
                    continue
                if a in has_douban and b in has_douban:
                    continue  # two douban subjects = editions/remakes, by design
                pairs[(a, b)] = f"share name key “{key[:40]}” ({kind})"
    return [(a, b, why) for (a, b), why in sorted(pairs.items())]


def pair_card(conn, pid: str, a: int, b: int, why: str, cache: dict) -> str:
    return (f"<div class='pair' data-pid='{pid}'>"
            f"<div class='pair-head'><b>{pid}</b> <span class='dim'>{html.escape(why)}</span>"
            f"<span class='verdict'>"
            f"<button onclick=\"decide('{pid}','merge',this)\">merge</button>"
            f"<button onclick=\"decide('{pid}','keep',this)\">keep both</button>"
            f"<button onclick=\"decide('{pid}','unsure',this)\">unsure</button>"
            f"</span></div>"
            f"<div class='pair-body'>{work_card(conn, a, cache)}{work_card(conn, b, cache)}</div>"
            f"</div>")


def main() -> int:
    conn = open_db()
    cache: dict = {}

    stats = {r["kind"]: r["n"] for r in conn.execute(
        "SELECT kind, COUNT(*) n FROM works GROUP BY kind")}
    n_ann = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
    n_rec = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    n_cov = conn.execute("SELECT COUNT(*) FROM covers").fetchone()[0]

    # needs attention
    douban_only = conn.execute(
        """SELECT w.id, w.kind, w.title, w.year FROM works w
           WHERE w.kind != 'music'
             AND (SELECT COUNT(DISTINCT namespace) FROM external_ids e
                  WHERE e.work_id=w.id) = 1
             AND EXISTS (SELECT 1 FROM external_ids e
                         WHERE e.work_id=w.id AND e.namespace='douban')
           ORDER BY w.kind, w.title"""
    ).fetchall()
    isbn_absent = conn.execute(
        "SELECT id, title FROM works WHERE kind='book' AND meta LIKE '%isbn_absent%'"
    ).fetchall()

    queue = [
        q for q in conn.execute(
            """SELECT q.id, q.work_a, q.work_b, q.reason FROM match_queue q
               WHERE q.state='pending' ORDER BY q.id"""
        ).fetchall()
        # stale rows (self-pairs after a merge, or a deleted side) are noise
        if q["work_a"] != q["work_b"]
        and conn.execute("SELECT COUNT(*) FROM works WHERE id IN (?,?)",
                         (q["work_a"], q["work_b"])).fetchone()[0] == 2
    ]
    # suspected Letterboxd mislogs are their own decision class (section 5)
    mislogs = conn.execute("SELECT * FROM lb_cleanup ORDER BY slug").fetchall()
    mislog_slugs = {m["slug"] for m in mislogs}

    def lb_slug(wid: int) -> str:
        r = conn.execute(
            "SELECT value FROM external_ids WHERE work_id=? AND namespace='letterboxd'",
            (wid,)).fetchone()
        return r["value"] if r else ""

    queue = [q for q in queue
             if lb_slug(q["work_a"]) not in mislog_slugs
             and lb_slug(q["work_b"]) not in mislog_slugs]
    heur = [(a, b, why) for a, b, why in heuristic_pairs(conn)
            if lb_slug(a) not in mislog_slugs and lb_slug(b) not in mislog_slugs]

    q_cards = "".join(
        pair_card(conn, f"Q{q['id']}", q["work_a"], q["work_b"], q["reason"], cache)
        for q in queue)
    h_cards = "".join(
        pair_card(conn, f"H{i+1}", a, b, why, cache)
        for i, (a, b, why) in enumerate(heur))

    do_rows = "".join(
        f"<tr><td>#{r['id']}</td><td>{r['kind']}</td>"
        f"<td>{html.escape(r['title'])}</td><td>{r['year'] or ''}</td></tr>"
        for r in douban_only)
    ia_rows = "".join(
        f"<tr><td>#{r['id']}</td><td>{html.escape(r['title'])}</td></tr>"
        for r in isbn_absent)

    kinds_line = " · ".join(f"{k} {n}" for k, n in sorted(stats.items(), key=lambda x: -x[1]))

    page = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>media.db — identity &amp; duplicates review</title>
<style>
:root {{ --bg:#101418; --card:#1a2026; --ink:#e8e6e1; --dim:#8a94a0;
        --line:#2a323b; --acc:#d4a24e; --bad:#e06c5a; --ok:#7fb069; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:28px 4vw 120px; background:var(--bg); color:var(--ink);
       font:15px/1.55 -apple-system,'PingFang SC','Helvetica Neue',sans-serif; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:17px; margin:36px 0 10px; color:var(--acc); }}
.dim {{ color:var(--dim); font-weight:normal; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }}
th,td {{ border:1px solid var(--line); padding:5px 9px; text-align:left; }}
th {{ background:var(--card); }} td.k {{ font-weight:600; }} td.bad {{ color:var(--bad); font-weight:700; }}
.pair {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
        padding:12px 14px; margin:10px 0; }}
.pair-head {{ display:flex; gap:10px; align-items:center; margin-bottom:8px; }}
.pair-head .verdict {{ margin-left:auto; display:flex; gap:6px; }}
.pair-head button {{ background:none; border:1px solid var(--line); color:var(--ink);
        border-radius:6px; padding:3px 10px; cursor:pointer; font-size:12px; }}
.pair-head button.on {{ border-color:var(--acc); color:var(--acc); font-weight:700; }}
.pair-body {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
@media (max-width:760px) {{ .pair-body {{ grid-template-columns:1fr; }} }}
.work {{ display:flex; gap:10px; min-width:0; }}
.work img, .noimg {{ width:60px; height:84px; object-fit:cover; border-radius:5px;
        background:#0a0d10; flex:none; }}
.w-title {{ font-weight:600; }} .sub {{ font-size:12.5px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:4px; margin:4px 0; }}
.chip {{ font-size:11px; background:#232b33; border-radius:4px; padding:1px 6px;
        color:var(--dim); }}
.chip.none {{ color:var(--bad); }}
details {{ margin:8px 0; }} summary {{ cursor:pointer; color:var(--acc); }}
#bar {{ position:fixed; bottom:0; left:0; right:0; background:var(--card);
       border-top:1px solid var(--line); padding:10px 4vw; display:flex; gap:14px;
       align-items:center; font-size:13px; }}
#bar button {{ background:var(--acc); color:#101418; border:none; border-radius:7px;
       padding:7px 16px; font-weight:700; cursor:pointer; }}
</style></head><body>
<h1>media.db — identity &amp; duplicates review <span class="dim">2026-07-28</span></h1>
<div class="dim">{kinds_line} · {n_rec} records · {n_ann} annotations · {n_cov} covers</div>

<h2>1 · Identity coverage <span class="dim">(works per kind carrying each namespace)</span></h2>
{coverage(conn)}
<p class="dim">music (654) is douban-only by design until its NeoDB cleanup runs.
TV seasons are anchored by douban + neodb; show-level imdb/tmdb ride in
works.meta (season-tt rule). kind=show carries the series-level ids.</p>

<h2>2 · Needs attention</h2>
<details><summary>douban-only works outside music ({len(douban_only)})</summary>
<table><tr><th>work</th><th>kind</th><th>title</th><th>year</th></tr>{do_rows}</table>
</details>
<details><summary>books with no ISBN in print (documented e-only, {len(isbn_absent)})</summary>
<table><tr><th>work</th><th>title</th></tr>{ia_rows}</table></details>

<h2>3 · Duplicate candidates — match queue ({len(queue)})</h2>
<p class="dim">Pairs the resolver refused to merge automatically. merge = same
work, keep both = genuinely different (remake/edition), unsure = look later.</p>
{q_cards or "<p class='dim'>queue is empty 🎉</p>"}

<h2>4 · Duplicate candidates — name heuristic ({len(heur)})</h2>
<p class="dim">Same kind, sharing a normalized name key, at most one side
douban-anchored. Two douban ids never pair (editions/remakes by design).</p>
{h_cards or "<p class='dim'>none found 🎉</p>"}

<h2>5 · Suspected Letterboxd mislogs ({len(mislogs)})</h2>
<p class="dim">Your Letterboxd diary logged the film on the left, but the
evidence (slug's true TMDB/IMDb identity vs your Douban record) says you
probably meant the film on the right. <b>delete</b> = it was a mislog, remove
the wrong watch record (and later fix Letterboxd itself); <b>watched it</b> =
you really did watch that one too, keep it.</p>
{"".join(f'''<div class="pair" data-pid="L-{html.escape(m["slug"])}">
<div class="pair-head"><b>lb:{html.escape(m["slug"])}</b>
<span class="verdict">
<button onclick="decide('L-{html.escape(m["slug"])}','delete',this)">delete mislog</button>
<button onclick="decide('L-{html.escape(m["slug"])}','watched',this)">watched it</button>
<button onclick="decide('L-{html.escape(m["slug"])}','unsure',this)">unsure</button>
</span></div>
<div class="sub">diary says: <b>{html.escape(m["wrong_film"] or "")}</b>
&nbsp;·&nbsp; probably meant: <b>{html.escape(m["your_film"] or "")}</b>
<span class="dim"> — {html.escape(m["note"] or "")}</span></div>
</div>''' for m in mislogs)}

<div id="bar"><span id="count">0 decisions</span>
<button onclick="exportDecisions()">export decisions (copy JSON)</button>
<span class="dim">paste the JSON back to Claude to apply merges</span></div>
<script>
const D = {{}};
function decide(pid, v, btn) {{
  D[pid] = v;
  btn.parentElement.querySelectorAll('button').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  document.getElementById('count').textContent = Object.keys(D).length + ' decisions';
}}
function exportDecisions() {{
  const txt = JSON.stringify(D, null, 1);
  navigator.clipboard.writeText(txt).then(() => alert('copied ' + Object.keys(D).length + ' decisions'));
}}
</script>
</body></html>"""
    OUT.write_text(page, encoding="utf-8")
    size = OUT.stat().st_size // 1024
    print(f"review.html: {size} KB · queue pairs {len(queue)} · heuristic pairs {len(heur)}"
          f" · douban-only {len(douban_only)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
