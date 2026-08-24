#!/usr/bin/env python3
"""build_library_db.py: generate media-hub/library.html from media.db.

The DB-driven successor to douban-export/build_library.py — same midnight
archive design (tabs, pills, search, sort, poster grid, cover flagging),
but every fact comes from the canonical store via the resolved view, plus
what the JSON page couldn't do: book cards open an annotation drawer with
the actual WeRead highlights and Anping's per-passage thoughts.

Covers are referenced by their on-disk paths (covers table, relative to the
AI Space root) — open the page locally or over the repo-root http server.
stdlib only. Re-run after any sync.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from resolved import resolve_all

HERE = Path(__file__).resolve().parent
DB = HERE / "media.db"
OUT = HERE / "library.html"

STATUS_ZH = {
    "film": {"watched": "看过", "watching": "在看", "wishlist": "想看", "owned": "收藏"},
    "book": {"watched": "读过", "watching": "在读", "wishlist": "想读", "owned": "未读"},
    "game": {"watched": "玩过", "watching": "在玩", "wishlist": "想玩", "owned": "库存"},
}


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def load_maps(conn):
    ids: dict[int, dict[str, str]] = {}
    for r in conn.execute("SELECT work_id, namespace, value FROM external_ids"):
        ids.setdefault(r["work_id"], {}).setdefault(r["namespace"], r["value"])
    covers: dict[int, str] = {}
    for r in conn.execute(
        "SELECT work_id, file FROM covers WHERE preferred=1"
    ):
        covers.setdefault(r["work_id"], "../" + r["file"])
    ann_count: dict[int, int] = {}
    for r in conn.execute("SELECT work_id, COUNT(*) n FROM annotations GROUP BY work_id"):
        ann_count[r["work_id"]] = r["n"]
    return ids, covers, ann_count


def neodb_url(kind: str, uuid: str) -> str:
    if not uuid:
        return ""
    path = {"film": "movie", "tv": "tv/season", "book": "book", "game": "game"}.get(kind, "movie")
    return f"https://neodb.social/{path}/{uuid}"


def meta_of(w) -> dict:
    try:
        return json.loads(w["meta"]) if w["meta"] else {}
    except json.JSONDecodeError:
        return {}


def movies_payload(conn, R, ids, covers):
    out = []
    # season works represent their shows; a show entity only displays when no
    # season carries its identity (i.e. watched on plex/letterboxd only)
    season_show_ids = set()
    for w in conn.execute("SELECT meta FROM works WHERE kind='tv' AND meta!=''"):
        m = meta_of(w)
        season_show_ids.add(m.get("show_imdb_id", ""))
        season_show_ids.add(str(m.get("show_tmdb_id", "")))
    season_show_ids.discard("")

    for w in conn.execute(
        "SELECT * FROM works WHERE kind IN ('film','tv','show') ORDER BY id"
    ):
        wid = w["id"]
        i = ids.get(wid, {})
        if w["kind"] == "show" and (
            i.get("imdb", "") in season_show_ids or i.get("tmdb_tv", "") in season_show_ids
        ):
            continue  # its seasons are on the shelf already
        r = R.get(wid)
        if not r:
            continue  # no records = not part of the library (identity-only rows)
        m = meta_of(w)
        imdb = i.get("imdb") or m.get("show_imdb_id") or ""
        tmdb_url = (f"https://www.themoviedb.org/movie/{i['tmdb_movie']}" if i.get("tmdb_movie")
                    else m.get("show_tmdb_url") or
                    (f"https://www.themoviedb.org/tv/{i['tmdb_tv']}" if i.get("tmdb_tv") else ""))
        en = w["title_en"] or w["original_title"] or ""
        out.append({
            "id": wid, "zh": w["title"], "en": en if en != w["title"] else "",
            "y": w["year"], "t": "tv" if w["kind"] in ("tv", "show") else "movie",
            "s": w["season_number"], "st": r["status"],
            "r": round(r["rating"] / 2, 1) if r["rating"] else "",
            "m": (r["marked_at"] or "")[:10],
            "imdb": imdb, "tu": tmdb_url,
            "du": f"https://movie.douban.com/subject/{i['douban']}/" if i.get("douban") else "",
            "nu": neodb_url("tv" if w["kind"] == "tv" else "film", w["neodb_uuid"] or ""),
            "src": "+".join(r["sources"]),
            "g": "none" if not (imdb or i.get("tmdb_movie") or i.get("tmdb_tv")) else "ok",
            "cv": covers.get(wid, ""),
        })
    return out


def books_payload(conn, R, ids, covers, ann_count):
    out = []
    for w in conn.execute("SELECT * FROM works WHERE kind='book' ORDER BY id"):
        wid = w["id"]
        r = R.get(wid)
        if not r:
            continue
        i = ids.get(wid, {})
        m = meta_of(w)
        wr = r["weread"]
        out.append({
            "id": wid, "zh": w["title"],
            "en": w["original_title"] or w["title_en"] or "",
            "au": w["creators"] or "", "y": str(w["year"] or ""),
            "isbn": i.get("isbn", ""), "st": r["status"],
            "src": "+".join(s for s in r["sources"] if s in ("douban", "weread")) or "+".join(r["sources"]),
            "r": round(r["rating"] / 2, 1) if r["rating"] else "",
            "m": (r["marked_at"] or "")[:10],
            "pg": wr.get("progress") if wr.get("progress") not in (None, "") else "",
            "hr": wr.get("hours") or "",
            "nt": ann_count.get(wid, 0),
            "cm": r["review"],
            "du": f"https://book.douban.com/subject/{i['douban']}/" if i.get("douban") else "",
            "nu": neodb_url("book", w["neodb_uuid"] or ""),
            "cv": covers.get(wid, ""),
        })
    return out


def games_payload(conn, R, ids, covers):
    out = []
    for w in conn.execute("SELECT * FROM works WHERE kind='game' ORDER BY id"):
        wid = w["id"]
        r = R.get(wid)
        if not r:
            continue
        i = ids.get(wid, {})
        m = meta_of(w)
        plats = (m.get("platforms") or "").replace("windows", "win")
        out.append({
            "id": wid, "en": w["title_en"] or w["original_title"] or w["title"],
            "zh": w["title"], "y": str(w["year"] or ""), "pl": plats,
            "st": r["status"], "src": "+".join(r["sources"]),
            "r": round(r["rating"] / 2, 1) if r["rating"] else "",
            "h": r["hours"] or "", "lp": r["last_played"],
            "tr": r["trophies"] or "",
            "du": f"https://www.douban.com/game/{i['douban']}/" if i.get("douban") else "",
            "su": f"https://store.steampowered.com/app/{i['steam']}/" if i.get("steam") else "",
            "cv": covers.get(wid, ""),
        })
    return out


def annotations_payload(conn):
    ann: dict[str, list] = {}
    for r in conn.execute(
        """SELECT work_id, kind, chapter, quote, comment, created_at
           FROM annotations ORDER BY work_id, id"""
    ):
        ann.setdefault(str(r["work_id"]), []).append({
            "k": r["kind"], "c": r["chapter"], "q": r["quote"],
            "n": r["comment"], "d": (r["created_at"] or "")[:10],
        })
    return ann


HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Emrick · 媒体库</title>
<style>
  :root {
    --bg: #131110; --bg2: #1b1815; --card: #201c18;
    --ink: #ece5d8; --ink2: #a39a8d; --ink3: #6e675d;
    --line: #2e2924; --amber: #e0a43e; --amber2: #8a6524;
    --red: #cf6a55; --green: #7fa06a; --blue: #7d9db8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background:
      radial-gradient(1200px 500px at 50% -200px, #241f19 0%, transparent 70%),
      var(--bg);
    color: var(--ink);
    font-family: "Iowan Old Style", "Palatino", "Songti SC", "Noto Serif CJK SC", serif;
  }
  header { padding: 38px 32px 0; }
  header h1 { font-size: 28px; font-weight: 600; letter-spacing: .04em; }
  header h1 em { color: var(--amber); font-style: normal; }
  .tabs { display: flex; gap: 26px; margin-top: 18px;
    border-bottom: 1px solid var(--line); }
  .tab { padding: 8px 2px 12px; cursor: pointer; color: var(--ink2);
    font-size: 15px; letter-spacing: .06em; border-bottom: 2px solid transparent; }
  .tab b { font-family: "SF Mono", Menlo, monospace; font-size: 11px;
    color: var(--ink3); font-weight: 500; margin-left: 4px; }
  .tab.on { color: var(--ink); border-bottom-color: var(--amber); }
  .tab.on b { color: var(--amber); }

  .bar {
    position: sticky; top: 0; z-index: 50;
    display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
    padding: 12px 32px; border-bottom: 1px solid var(--line);
    background: color-mix(in srgb, var(--bg) 88%, transparent);
    backdrop-filter: blur(10px);
  }
  .bar input[type=search] {
    background: var(--bg2); border: 1px solid var(--line); border-radius: 3px;
    color: var(--ink); padding: 7px 12px; width: 220px; font-size: 13px;
    font-family: "SF Mono", Menlo, "PingFang SC", monospace; outline: none;
  }
  .bar input[type=search]:focus { border-color: var(--amber2); }
  .pillset { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
  .pillset .lab { color: var(--ink3); font-size: 10px; letter-spacing: .14em;
    margin: 0 4px 0 10px; font-family: "SF Mono", Menlo, "PingFang SC", monospace; }
  button.pill {
    background: transparent; border: 1px solid var(--line); border-radius: 999px;
    color: var(--ink2); font-size: 11.5px; padding: 4px 11px; cursor: pointer;
    font-family: "SF Mono", Menlo, "PingFang SC", monospace;
  }
  button.pill:hover { border-color: var(--amber2); color: var(--ink); }
  button.pill.on { background: var(--amber); border-color: var(--amber);
    color: #17130c; font-weight: 600; }
  select {
    background: var(--bg2); border: 1px solid var(--line); border-radius: 3px;
    color: var(--ink2); padding: 6px 8px; font-size: 11.5px;
    font-family: "SF Mono", Menlo, "PingFang SC", monospace;
  }
  .count { margin-left: auto; color: var(--ink3); font-size: 11.5px;
    font-family: "SF Mono", Menlo, monospace; }
  .count b { color: var(--amber); }

  main { padding: 26px 32px 80px; }
  .grid { display: grid; gap: 22px 14px;
    grid-template-columns: repeat(auto-fill, minmax(142px, 1fr)); }
  .card { position: relative; }
  .poster {
    position: relative; aspect-ratio: 2/3; border-radius: 4px; overflow: hidden;
    background: var(--card); box-shadow: 0 2px 10px rgba(0,0,0,.45);
    transition: transform .18s ease, box-shadow .18s ease; cursor: pointer;
  }
  .card:hover .poster { transform: translateY(-4px);
    box-shadow: 0 10px 26px rgba(0,0,0,.6); }
  .poster img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .spine { display: flex; flex-direction: column; justify-content: center;
    height: 100%; padding: 14px; gap: 8px; border: 1px solid var(--line);
    border-radius: 4px; background: linear-gradient(160deg, #26211c, #1b1815); }
  .spine .t { font-size: 14px; line-height: 1.45; }
  .spine .a { color: var(--ink3); font-size: 11px; font-style: italic; }
  .ribbon { position: absolute; top: 8px; left: -1px; padding: 2px 8px 2px 7px;
    font-size: 9.5px; letter-spacing: .12em; font-weight: 700;
    font-family: "SF Mono", Menlo, monospace; border-radius: 0 3px 3px 0;
    background: var(--red); color: #1d0f0a; }
  .st { position: absolute; top: 8px; right: 8px; padding: 2px 6px;
    border-radius: 3px; font-size: 9.5px; letter-spacing: .1em;
    font-family: "SF Mono", Menlo, "PingFang SC", monospace;
    background: rgba(10,8,6,.72); }
  .st.c-wish { color: var(--blue); } .st.c-do { color: var(--green); }
  .st.c-backlog { color: var(--ink3); }
  .links { position: absolute; inset: auto 0 0 0; display: flex; gap: 1px;
    opacity: 0; transition: opacity .15s ease; }
  .card:hover .links { opacity: 1; }
  .links a { flex: 1; text-align: center; padding: 6px 0; font-size: 9.5px;
    font-family: "SF Mono", Menlo, "PingFang SC", monospace;
    background: rgba(12,10,8,.86); color: var(--ink2); text-decoration: none; }
  .links a:hover { color: var(--amber); background: rgba(12,10,8,.95); }
  .tt { margin-top: 9px; }
  .tt .zh { font-size: 13.5px; line-height: 1.3; }
  .tt .en { margin-top: 2px; color: var(--ink2); font-size: 11px;
    line-height: 1.35; font-style: italic; }
  .meta { margin-top: 4px; color: var(--ink3); font-size: 10px;
    font-family: "SF Mono", Menlo, "PingFang SC", monospace; }
  .meta .stars { color: var(--amber); }
  .meta .hrs { color: var(--green); }
  .meta .pgc { color: var(--blue); }
  .meta .notes { color: var(--amber); cursor: pointer; text-decoration: underline dotted; }
  .empty { text-align: center; color: var(--ink3); padding: 90px 0;
    font-family: "SF Mono", Menlo, "PingFang SC", monospace; font-size: 13px; }
  .flag { position: absolute; top: 50%; left: 50%; z-index: 2;
    transform: translate(-50%, -50%); pointer-events: none;
    background: rgba(10,8,6,.8); border-radius: 50%;
    color: var(--amber); font-size: 26px; width: 54px; height: 54px;
    display: flex; align-items: center; justify-content: center;
    opacity: 0; transition: opacity .15s ease; }
  .poster:hover .flag { opacity: .45; }
  .poster.flagged { outline: 3px solid var(--amber); outline-offset: -3px; }
  .poster.flagged .flag { opacity: 1; }
  .flag.on { opacity: 1; background: var(--amber); color: #17130c; }
  #flagbar { position: fixed; right: 18px; bottom: 18px; z-index: 100;
    display: none; gap: 8px; align-items: center; padding: 9px 14px;
    background: var(--bg2); border: 1px solid var(--amber2); border-radius: 6px;
    font-family: "SF Mono", Menlo, "PingFang SC", monospace; font-size: 12px;
    box-shadow: 0 6px 24px rgba(0,0,0,.5); }
  #flagbar.show { display: flex; }
  #flagbar b { color: var(--amber); }
  #flagbar button { background: transparent; border: 1px solid var(--line);
    border-radius: 3px; color: var(--ink2); font-size: 11px; padding: 3px 9px;
    cursor: pointer; font-family: inherit; }
  #flagbar button:hover { border-color: var(--amber2); color: var(--ink); }

  /* annotation drawer */
  #drawer { position: fixed; inset: 0; z-index: 200; display: none; }
  #drawer.show { display: block; }
  #drawer .shade { position: absolute; inset: 0; background: rgba(0,0,0,.55); }
  #drawer .panel { position: absolute; top: 0; right: 0; bottom: 0;
    width: min(560px, 92vw); background: var(--bg2);
    border-left: 1px solid var(--amber2); box-shadow: -12px 0 40px rgba(0,0,0,.5);
    display: flex; flex-direction: column; }
  #drawer h2 { padding: 22px 26px 6px; font-size: 18px; font-weight: 600; }
  #drawer .sub { padding: 0 26px 14px; color: var(--ink3); font-size: 11.5px;
    font-family: "SF Mono", Menlo, "PingFang SC", monospace;
    border-bottom: 1px solid var(--line); }
  #drawer .list { overflow-y: auto; padding: 12px 26px 40px; flex: 1; }
  .annot { margin: 16px 0; }
  .annot .ch { color: var(--ink3); font-size: 10.5px; letter-spacing: .08em;
    font-family: "SF Mono", Menlo, "PingFang SC", monospace; margin-bottom: 5px; }
  .annot .q { border-left: 2px solid var(--amber2); padding: 2px 0 2px 14px;
    color: var(--ink2); font-size: 13.5px; line-height: 1.75; }
  .annot .n { margin-top: 7px; padding-left: 16px; color: var(--amber);
    font-size: 13px; line-height: 1.7; }
  .annot .n::before { content: "— "; color: var(--amber2); }
  #drawer .close { position: absolute; top: 18px; right: 20px;
    background: none; border: 1px solid var(--line); color: var(--ink2);
    border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 12px; }
  #drawer .close:hover { border-color: var(--amber2); color: var(--ink); }
  footer { text-align: center; color: var(--ink3); font-size: 11px;
    padding: 0 0 46px; font-family: "SF Mono", Menlo, "PingFang SC", monospace; }
</style>
</head>
<body>
<header>
  <h1>Emrick <em>/ 媒体库</em></h1>
  <div class="tabs" id="tabs"></div>
</header>
<div class="bar" id="bar"></div>
<main><div class="grid" id="grid"></div><div class="empty" id="empty" hidden>无匹配条目</div></main>
<div id="flagbar">封面已标记 <b id="flagcount">0</b>
  <button id="flagcopy">复制清单</button><button id="flagclear">清空</button></div>
<div id="drawer"><div class="shade"></div>
  <div class="panel"><button class="close">关闭 esc</button>
    <h2 id="dr-title"></h2><div class="sub" id="dr-sub"></div>
    <div class="list" id="dr-list"></div></div></div>
<footer>media.db · generated __TODAY__ · 悬停卡片点 ⚑ 标记需要更换的封面 · 书卡的「n 注」打开笔记</footer>
<script>
const DATA = __DATA__;
const ANN = __ANN__;
const TABS = [
  {key:"movies", label:"影视"},
  {key:"books", label:"图书"},
  {key:"games", label:"游戏"},
];
const FILTERS = {
  movies: [
    {key:"type", lab:"类型", opts:[["all","全部"],["movie","电影"],["tv","剧集"]],
     fn:(d,v)=>d.t===v},
    {key:"status", lab:"状态", opts:[["all","全部"],["watched","看过"],["wishlist","想看"],["watching","在看"]],
     fn:(d,v)=>d.st===v},
    {key:"src", lab:"来源", opts:[["all","全部"],["douban","含豆瓣"],["letterboxd","含LB"],["plex","含Plex"],["multi","多源"]],
     fn:(d,v)=> v==="multi" ? d.src.includes("+") : d.src.includes(v)},
  ],
  books: [
    {key:"status", lab:"状态", opts:[["all","全部"],["watched","读过"],["watching","在读"],["wishlist","想读"],["owned","未读"]],
     fn:(d,v)=>d.st===v},
    {key:"src", lab:"来源", opts:[["all","全部"],["douban","仅豆瓣"],["weread","仅微读"],["douban+weread","双源"]],
     fn:(d,v)=> v==="douban+weread" ? d.src==="douban+weread" : d.src===v},
    {key:"notes", lab:"笔记", opts:[["all","全部"],["yes","有笔记"]],
     fn:(d,v)=> d.nt>0},
  ],
  games: [
    {key:"status", lab:"状态", opts:[["all","全部"],["watched","玩过"],["wishlist","想玩"],["owned","库存"]],
     fn:(d,v)=>d.st===v},
    {key:"src", lab:"来源", opts:[["all","全部"],["douban","含豆瓣"],["steam","含Steam"],["psn","含PSN"],["multi","多源"]],
     fn:(d,v)=> v==="multi" ? d.src.includes("+") : d.src.includes(v)},
  ],
};
const SORTS = {
  movies: [["m-desc","标记时间 ↓"],["y-desc","年份 ↓"],["r-desc","评分 ↓"],["zh","名称"]],
  books:  [["m-desc","时间 ↓"],["nt-desc","笔记 ↓"],["r-desc","评分 ↓"],["zh","名称"]],
  games:  [["h-desc","时长 ↓"],["lp-desc","最近玩 ↓"],["r-desc","评分 ↓"],["y-desc","年份 ↓"],["en","名称"]],
};

let tab = "movies";
const state = {};
TABS.forEach(t => { state[t.key] = {q:"", sort:SORTS[t.key][0][0]};
  FILTERS[t.key].forEach(f => state[t.key][f.key] = "all"); });

function esc(s){ return String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;"); }
function stars(r){ const n = Math.round(+r); return r ? "★".repeat(n)+"☆".repeat(Math.max(0,5-n)) : ""; }

function renderTabs(){
  const el = document.getElementById("tabs");
  el.innerHTML = TABS.map(t =>
    `<div class="tab${t.key===tab?" on":""}" data-k="${t.key}">${t.label}<b>${DATA[t.key].length}</b></div>`).join("");
  el.querySelectorAll(".tab").forEach(d => d.onclick = () => { tab = d.dataset.k; renderBar(); render(); renderTabs(); });
}

function renderBar(){
  const s = state[tab];
  const bar = document.getElementById("bar");
  bar.innerHTML = `<input type="search" id="q" placeholder="搜索…( / )" value="${esc(s.q)}">` +
    FILTERS[tab].map(f =>
      `<span class="pillset" data-f="${f.key}"><span class="lab">${f.lab}</span>` +
      f.opts.map(([v,l]) => `<button class="pill${s[f.key]===v?" on":""}" data-v="${v}">${l}</button>`).join("") +
      `</span>`).join("") +
    `<select id="sort">` + SORTS[tab].map(([v,l]) =>
      `<option value="${v}"${s.sort===v?" selected":""}>${l}</option>`).join("") + `</select>` +
    `<span class="count" id="count"></span>`;
  bar.querySelector("#q").addEventListener("input", e => { s.q = e.target.value.trim().toLowerCase(); render(); });
  bar.querySelectorAll(".pillset").forEach(ps => {
    const fk = ps.dataset.f;
    ps.querySelectorAll(".pill").forEach(b => b.onclick = () => {
      s[fk] = b.dataset.v;
      ps.querySelectorAll(".pill").forEach(p => p.classList.toggle("on", p===b));
      render();
    });
  });
  bar.querySelector("#sort").addEventListener("change", e => { s.sort = e.target.value; render(); });
}
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeDrawer();
  const q = document.getElementById("q");
  if (e.key === "/" && q && document.activeElement !== q) { e.preventDefault(); q.focus(); }
});

function hay(d){
  return [d.zh, d.en, d.au, d.imdb, d.isbn, d.id, d.pl, d.cm].filter(Boolean).join(" ").toLowerCase();
}

function filtered(){
  const s = state[tab];
  let rs = DATA[tab].filter(d =>
    FILTERS[tab].every(f => s[f.key]==="all" || f.fn(d, s[f.key])) &&
    (!s.q || hay(d).includes(s.q)));
  const [k, dir] = s.sort.split("-");
  rs.sort((a,b) => {
    if (k==="zh"||k==="en") return String(a[k]||a.zh||"").localeCompare(String(b[k]||b.zh||""), "zh");
    const av = a[k]===""||a[k]==null ? -1 : +a[k] || String(a[k]);
    const bv = b[k]===""||b[k]==null ? -1 : +b[k] || String(b[k]);
    const cmp = (typeof av==="number" && typeof bv==="number")
      ? av-bv : String(a[k]||"").localeCompare(String(b[k]||""));
    return (dir==="asc"?1:-1) * cmp;
  });
  return rs;
}

function statusTag(d){
  const zh = {movies:{wishlist:"想看",watching:"在看",owned:"收藏"},
              books:{wishlist:"想读",watching:"在读",owned:"未读"},
              games:{wishlist:"想玩",watching:"在玩",owned:"库存"}}[tab][d.st];
  if (!zh) return "";
  const cls = d.st==="wishlist" ? "c-wish" : d.st==="watching" ? "c-do" : "c-backlog";
  return `<span class="st ${cls}">${zh}</span>`;
}

function metaLine(d){
  if (tab==="movies")
    return [d.y||"—", d.t==="tv"?("剧"+(d.s?` S${d.s}`:"")):"影", d.imdb].filter(Boolean).join(" · ")
      + (d.r?` <span class="stars">${stars(d.r)}</span>`:"");
  if (tab==="books") {
    const bits = [d.y||"—"];
    if (d.pg!=="" && d.pg>0 && d.pg<100) bits.push(`<span class="pgc">${d.pg}%</span>`);
    if (d.nt) bits.push(`<span class="notes" data-ann="${d.id}" data-t="${esc(d.zh)}">${d.nt}注</span>`);
    if (d.hr) bits.push(`${d.hr}h`);
    return bits.join(" · ") + (d.r?` <span class="stars">${stars(d.r)}</span>`:"");
  }
  const bits = [d.y||"—"];
  if (d.h) bits.push(`<span class="hrs">${d.h}h</span>`);
  if (d.tr) bits.push(`🏆${d.tr}`);
  if (d.pl) bits.push(esc(d.pl.split(" / ").slice(0,3).join("·")));
  return bits.join(" · ") + (d.r?` <span class="stars">${stars(d.r)}</span>`:"");
}

function linksBar(d){
  const L = [];
  if (d.du) L.push(`<a href="${d.du}" target="_blank" rel="noreferrer">豆瓣</a>`);
  if (d.imdb) L.push(`<a href="https://www.imdb.com/title/${d.imdb}/" target="_blank" rel="noreferrer">IMDb</a>`);
  if (d.tu) L.push(`<a href="${d.tu}" target="_blank" rel="noreferrer">TMDB</a>`);
  if (d.su) L.push(`<a href="${d.su}" target="_blank" rel="noreferrer">Steam</a>`);
  if (d.nu) L.push(`<a href="${d.nu}" target="_blank" rel="noreferrer">NeoDB</a>`);
  return L.join("");
}

function card(d){
  const title1 = d.zh || d.en, title2 = (d.zh && d.en && d.en!==d.zh) ? d.en : "";
  const sub = tab==="books" ? (d.au||"") : title2;
  const spine = `<div class=spine><div class=t>${esc(title1)}</div><div class=a>${esc(sub||title2)}</div></div>`;
  const ribbon = (tab==="movies" && d.g==="none")
    ? `<span class="ribbon">无外部ID</span>` : "";
  const imgs = d.cv
    ? `<img src="${esc(d.cv)}" loading="lazy"
           onerror="this.outerHTML=${esc(JSON.stringify(spine))}">`
    : spine;
  const fkey = tab + ":" + d.id;
  return `<div class="card">
    <div class="poster${FLAGS[fkey]?" flagged":""}" data-fk="${fkey}"
         data-title="${esc(title1)}" title="点击封面标记需要更换">
      ${imgs}
      ${ribbon}${statusTag(d)}
      <span class="flag">⚑</span>
      <div class="links">${linksBar(d)}</div>
    </div>
    <div class="tt"><div class="zh">${esc(title1)}</div>
      ${sub?`<div class="en">${esc(sub)}</div>`:""}</div>
    <div class="meta">${metaLine(d)}</div>
  </div>`;
}

function render(){
  const rs = filtered();
  document.getElementById("grid").innerHTML = rs.map(card).join("");
  document.getElementById("empty").hidden = rs.length > 0;
  const c = document.getElementById("count");
  if (c) c.innerHTML = `<b>${rs.length}</b> / ${DATA[tab].length}`;
}

// --- annotation drawer -----------------------------------------------------
function openDrawer(wid, title){
  const rows = ANN[wid] || [];
  document.getElementById("dr-title").textContent = title;
  document.getElementById("dr-sub").textContent =
    `${rows.length} 条划线与想法 · 微信读书`;
  document.getElementById("dr-list").innerHTML = rows.map(a => `
    <div class="annot">
      ${a.c?`<div class="ch">${esc(a.c)}${a.d?` · ${a.d}`:""}</div>`:""}
      ${a.q?`<div class="q">${esc(a.q)}</div>`:""}
      ${a.n?`<div class="n">${esc(a.n)}</div>`:""}
    </div>`).join("") || `<div class="annot"><div class="q">（无内容）</div></div>`;
  document.getElementById("drawer").classList.add("show");
}
function closeDrawer(){ document.getElementById("drawer").classList.remove("show"); }
document.querySelector("#drawer .shade").onclick = closeDrawer;
document.querySelector("#drawer .close").onclick = closeDrawer;

// --- cover flagging ----------------------------------------------------------
const FLAGS = JSON.parse(localStorage.getItem("coverFlags") || "{}");
function syncFlagbar() {
  const n = Object.keys(FLAGS).length;
  document.getElementById("flagcount").textContent = n;
  document.getElementById("flagbar").classList.toggle("show", n > 0);
}
document.getElementById("grid").addEventListener("click", e => {
  const note = e.target.closest(".notes");
  if (note) { openDrawer(note.dataset.ann, note.dataset.t); return; }
  if (e.target.closest("a")) return;
  const p = e.target.closest(".poster");
  if (!p) return;
  const k = p.dataset.fk;
  if (FLAGS[k]) { delete FLAGS[k]; p.classList.remove("flagged"); }
  else { FLAGS[k] = p.dataset.title; p.classList.add("flagged"); }
  localStorage.setItem("coverFlags", JSON.stringify(FLAGS));
  syncFlagbar();
});
document.getElementById("flagcopy").onclick = () => {
  const text = Object.entries(FLAGS)
    .map(([k, t]) => `${k}  ${t}`).join("\\n");
  const done = () => { const b = document.getElementById("flagcopy");
    b.textContent = "已复制 ✓"; setTimeout(() => b.textContent = "复制清单", 1500); };
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(done);
  else { const ta = document.createElement("textarea"); ta.value = text;
    document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove(); done(); }
};
document.getElementById("flagclear").onclick = () => {
  for (const k in FLAGS) delete FLAGS[k];
  localStorage.setItem("coverFlags", "{}");
  syncFlagbar(); render();
};

renderTabs(); renderBar(); render(); syncFlagbar();
</script>
</body>
</html>
"""


def main() -> None:
    conn = open_db()
    R = resolve_all(conn)
    ids, covers, ann_count = load_maps(conn)
    payload = {
        "movies": movies_payload(conn, R, ids, covers),
        "books": books_payload(conn, R, ids, covers, ann_count),
        "games": games_payload(conn, R, ids, covers),
    }
    ann = annotations_payload(conn)
    html = (HTML
            .replace("__TODAY__", date.today().isoformat())
            .replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            .replace("__ANN__", json.dumps(ann, ensure_ascii=False, separators=(",", ":"))))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB; "
          f"movies {len(payload['movies'])}, books {len(payload['books'])}, "
          f"games {len(payload['games'])}, annotated books {len(ann)})")


if __name__ == "__main__":
    main()
