# Funnel log — 2026-08-23 — digest-test2 (interactive, all-external policy test)

Mode: interactive (live ask, pool-first). Wall-clock: ~8.7 min (start
marker 1787537096, end 1787537619 → 523s). Over the ≤5min interactive
target — logged honestly, see "Timing" note at bottom for why.
Network calls: 10 (budget ~10). See "Network call log" below for the
itemized list.

## 0. Session setup
- Snapshot/index/distribution were pre-built and supplied (not
  regenerated): `snap.json`, `index.txt` (1,702-work rating index),
  `distribution.json`, in the scratchpad's `test2/` dir.
- Read `recommend/README.md` and `recommend/SCOUT.md` in full before any
  work, including the 2026-08-23 "all recommendations are external"
  policy amendment.

## 1. Interpret the ask
Ask (verbatim, from DIGEST-INTENT.md, matches the brief):
> 下饭剧优先：低认知负荷、分集式、可打断，可以边吃饭/边玩游戏放的剧；
> 外加一部值得专门找时间看的高密度电影。范围：新近上映/开播或口碑新起的，
> 以及经典中明显契合口味而从未看过的。总量小而准：剧 2–3 部、电影 1–2 部。

**clarify: not needed** — the ask already specifies both axes explicitly
(series count 2-3 + film count 1-2, background-viewing vs
dedicated-attention register for each, and the eligible pool: recent/
newly-acclaimed OR taste-fit classics never seen). There is no fork
whose resolution would change most of the resulting slate — every
reading converges on "find background-friendly series + one dense
film, from either recency or classic-fit". Proceeding on the working
interpretation as stated.

## 2. Work the history
- Distribution loaded from the supplied `distribution.json` — confirmed
  matches README.md's cited figures (film 2020-2026: n=105, pct_ge4
  43.8, pct_5 3.8; tv/show all years: n=498, pct_ge4 74.3, pct_5 31.1).
- Neighborhood/anchors built ad hoc per candidate during shortlisting
  (below) rather than as one upfront pass, given the pool-first
  interactive flow — documented inline per candidate.
- **Shells**: not swept, not used as a candidate source at any point —
  confirmed compliance with the new external-only policy. `index.txt`
  (the rated-history map) was the only local file used for the unseen
  check; it does not carry shells data by design, so there is no risk
  of shells leaking into the retrieval side of this run.

## 3. Sweep — channel hierarchy
**Tier 1 (pool query, local, no network) — the only generation channel
used this run. No tier-2/3 top-up was needed; the pool was not thin for
this ask.**

- `pool.py query --kind tv --limit 400` → 400 rows (of 1185 tv rows
  total in the pool, per `pool.py stats`: total 4,297, tv 1,185, film
  3,112, 411 pre-suppressed).
- `pool.py query --kind tv --year-from 2019 --limit 400` → 400 rows
  (recency slice, to bias toward "新近开播").
- `pool.py query --kind tv --limit 1200` → 1,031 rows (full unsuppressed
  tv pool, used to find alternate-season entry points for shows whose
  only pool row was a late season).
- `pool.py query --kind tv --tag Comedy --limit 200` → 110 rows (targeted
  genre slice for the 下饭-sitcom angle).
- `pool.py query --kind film --limit 400` → 400 rows.
- `pool.py query --kind film --year-from 2020 --limit 400` → 400 rows
  (recency slice for "新近上映").
- `pool.py stats` → total 4,297 (film 3,112 / tv 1,185), evidence_cached
  1 (pre-existing before this run), suppressed 411, by_channel
  {tmdb_discover_recent: 50, tmdb_rec: 3,265, douban_rec: 984}.

No pool gap was logged — tier 1 alone produced a strong-enough
candidate set for both the series and the film slot; tiers 2-3 and the
editorial pass were correctly skipped per interactive-mode rules.

## Eliminations — the sibling-season trap (the brief's specific warning, confirmed live)
The brief's warning ("check for sibling seasons before shortlisting any
series") fired repeatedly. Sorting the recent-tv pool slice by rating
surfaced many high-scoring candidates that were, on inspection, a LATER
season of a show whose earlier season(s) this user has already rated —
i.e. not "从未看过" at the show level at all:

- OUT 继承之战 第四季 (Succession S4, 2023): S1-S3 all rated (3.0/4.0/4.0) — mid-watch, not a discovery.
- OUT 怪奇物语 第五季 (Stranger Things S5, 2025): S1 rated 4.0.
- OUT 瑞克和莫蒂 第九季 (Rick and Morty S9, 2026) / 第七季: multiple seasons already rated (3.0-5.0 range).
- OUT 万物生灵 第六季 (All Creatures Great and Small S6, 2025): S1 rated 4.0.
- OUT 了不起的麦瑟尔夫人 第五季 (Mrs. Maisel S5, 2023): S1 rated 3.0 — also a soft anti-signal (low first-season rating), doubly disqualifying.
- OUT 9号秘事 第九季 (Inside No. 9 S9, 2024): S1 rated 5.0 — he loved it and never continued past S1; recommending S9 is "catch up on your own backlog," not a discovery, even though S9 itself is technically unwatched.
- OUT 去他*的世界 第二季 (The End of the F***ing World S2, 2019): S1 rated 4.0.
- OUT 灵能百分百 Ⅲ (Mob Psycho 100 S3, 2022): franchise never watched at all, but S3 is a bad entry point — held for a possible tier-2 top-up on S1 if the shortlist came in thin (it didn't, so not pursued).
- OUT JOJO的奇妙冒险 石之海 (JoJo Stone Ocean, 2021-22, Parts 1-3): same franchise-entry-point problem as Mob Psycho — franchise entirely unwatched but this is Part 6, a bad first exposure; not pursued given a thin-slate need never arose.
- OUT 纸钞屋 第五季 (Money Heist S5, 2021): only season in the pool is S5; no S1 pool row exists to substitute, so this show was dropped rather than top-upped (no thin-slate justification for a tier-2 fetch).
- OUT 姿态 第二季 (Pose S2, 2019): same problem, no S1 pool row.
- OUT 极品老妈 (Mom): pool carries only S4 (2016) and S8/final (2020), no S1 — held as a weaker alternate (US multi-cam sitcoms are unusually self-contained per-episode even mid-run) but not shortlisted once the IT Crowd/Seinfeld picks (both true S1 entries) covered the same "comfort sitcom" niche.
- OUT 办公室 (The Office US) 第三季 (2006): only S3 in pool, no S1/S2 — same reasoning as Mom, not pursued once other sitcom picks were secured.
- OUT 亚特兰大 第四季 (Atlanta S4, 2022): S1 not initially in this recent-year slice — re-queried the full pool and found 亚特兰大 第一季 (2016) IS present and unwatched; considered as a candidate (see below) but ultimately not shortlisted — its tone (surreal, symbolically dense, sometimes demanding) is a weaker match for "低认知负荷" than the final picks, despite being a legitimate S1 entry point. Logged as a genuine near-miss, not a data problem.

## Cut / shortlist reasoning (interactive mode: shortlist-against-target, no Cut 1/Cut 2 funnel)
Per SCOUT.md §4 interactive-mode instructions, candidates were judged
qualitatively against the pitch target (70th percentile, mid-rank, of
the candidate's own cell) rather than scored by the scout — `history.py
cell`/`percentile-of` were used only to calibrate my own sense of "how
hard is this bar" for the relevant cells, never as a stand-in for the
critic's judgment:

- `cell --kind tv --year 2006` → tv/show 2000-2009, n=69, pct_ge4 78.3,
  pct_5 33.3. `percentile-of --stars 4.5` → 66.7 (a 4.5-star prediction
  in this cell does NOT clear 70 on its own — a 5.0 prediction would be
  needed, or the case has to argue past a bare star number).
- `cell --kind tv --year 2011` → tv/show 2010-2019, n=242, pct_ge4 73.1,
  pct_5 31.0. `percentile-of --stars 5.0` → 84.5 (clears comfortably at
  5.0); `--stars 4.5` for 2016 (亚特兰大) → 68.4 (again just short of
  70).
- These numbers informed my confidence-only, not a kill: the nature-doc
  picks (地球脉动/人类星球) are pitched on the strength of a
  three-times-repeated 5.0 anchor (风味人间, all three seasons) — a
  rare, undiluted taste signal that gives real grounds to argue a 5.0
  prediction, which does clear 70 in both relevant cells.
- 亚特兰大 (2016 entry) was measured as marginal (68.4 at 4.5) with NO
  taste anchor to argue past that number, so it was shortlisted-out
  rather than dossiered — the honest call given the brief's own
  guidance to "drop what you don't believe clears the bar."
- The IT Crowd and Seinfeld carry no taste anchor at all (checked and
  confirmed absent, not just unchecked) — shortlisted anyway despite
  low case-confidence because they are the cleanest structural matches
  found for "下饭" specifically (short, standalone-episode sitcoms,
  true S1 entry points, unlike every other sitcom-shaped candidate the
  pool offered) and because §4 explicitly allows dossiering a
  low-confidence-but-structurally-strong candidate for the critic to
  judge, rather than the scout pre-killing everything without an
  anchor.
- 怪物/Monster (2023, Kore-eda) was the clear film pick: same director
  as two of this user's three highest-conviction film ratings (小偷家族
  5.0, 步履不停 5.0, 海街日记 4.0) — the single strongest anchor pattern
  found in the whole run.
- Rear Window (1954, Hitchcock) was shortlisted as a second film option
  despite zero taste anchor (checked eight specific Hitchcock/
  classic-noir titles against the rated history — Vertigo, Psycho,
  North by Northwest, Notorious, Shadow of a Doubt, The Conversation,
  Touch of Evil, Dog Day Afternoon — none rated) because it directly
  answers the ask's "经典...从未看过的" clause and is a canonical
  mystery/thriller; flagged honestly as the weaker of the two film
  picks in its dossier.

**Final shortlist dossiered: 6** (4 series, 2 films) — weighted toward
series per the ask, cap of 5 left for the critic to apply when ranking
survivors:
1. 地球脉动 / Planet Earth (tv, 2006)
2. 人类星球 / Human Planet (tv, 2011)
3. The IT Crowd (tv, 2006)
4. Seinfeld (tv, 1989)
5. 怪物 / Monster (film, 2023)
6. Rear Window (film, 1954)

## Evidence — cached vs fetched
Pool-wide `evidence_cached` was 1 before this run (unrelated prior row);
none of the 6 shortlisted candidates carried cached evidence, so ALL 6
required a fresh fetch (0 cached / 6 fetched, cached-first check
performed and confirmed empty for each via the pool row's `evidence:
null` field before fetching).

- The IT Crowd (tv/2490): TMDB `/tv/2490/reviews` → 1 review, Tier 1.
- Seinfeld (tv/1400): TMDB `/tv/1400/reviews` → 1 review, Tier 1.
- Rear Window (movie/567): TMDB `/movie/567/reviews` → 5 reviews, used
  2, Tier 1.
- 怪物/Monster (movie/1050035): TMDB `/movie/1050035/reviews` → 5
  reviews, used 2, Tier 1.
- 地球脉动/Planet Earth: NeoDB `/api/catalog/search` (resolved uuid,
  matched douban 1871906 exactly) → `/api/item/{uuid}/posts/?type=review`
  → 1 post found, review_uuid extracted from its content HTML →
  `/api/review/{uuid}` → **HTTP 403 "Permission denied"** (the posting
  account is `locked: true` — a private/protected NeoDB account, not the
  documented urllib-vs-curl UA gate from the source notes; retried with
  a browser UA per that gotcha, still 403). Fell back to the post's own
  visible content (review title + star-equivalent rating, no body) as
  Tier 3.
- 人类星球/Human Planet: NeoDB search → uuid resolved →
  `/api/item/{uuid}/posts/?type=review` → HTTP 200, `count: 0` — a
  **confirmed genuine zero** (not a masked 404; both season and item-
  level paths were the ones the gotcha describes as correct for a
  non-season TV item, so no retry-at-typed-path was needed here). Tier
  3 (douban_rating + confirmed absence, documented not silent).

All 6 evidence write-backs succeeded via `pool.py attach-evidence`
(ids 3266, 3270, 57, 359, 3369, 3368) — confirmed by "ok" from each
call.

## Network call log (10 total, budget ~10)
1. TMDB `/tv/2490/reviews` (The IT Crowd)
2. TMDB `/tv/1400/reviews` (Seinfeld)
3. TMDB `/movie/567/reviews` (Rear Window)
4. TMDB `/movie/1050035/reviews` (Monster)
5. NeoDB `/api/catalog/search` (地球脉动)
6. NeoDB `/api/item/{uuid}/posts/?type=review` (地球脉动)
7. NeoDB `/api/review/{uuid}` (地球脉动) — 403, failed
8. NeoDB `/api/review/{uuid}` retry w/ browser UA (地球脉动) — 403, failed (per source-notes gotcha, retried before accepting the negative)
9. NeoDB `/api/catalog/search` (人类星球)
10. NeoDB `/api/item/{uuid}/posts/?type=review` (人类星球)

All `pool.py query`/`stats`/`attach-evidence`/`history.py cell`/
`percentile-of` calls are local SQLite reads/writes, not counted as
network calls, per the budget's own framing (interactive-mode network
budget is specifically about evidence-fetching, not local pool queries).

## Timing note
Wall-clock came in at ~8.7 minutes against the ≤5 minute interactive
target — over budget. The overrun is attributable to the sibling-season
elimination pass (13 candidates individually checked against
`index.txt`/pool for parent-show identity before any could be
shortlisted or dropped) plus two full NeoDB search→posts→review chains
for the nature-doc picks, one of which dead-ended at a locked account
and required a retry per the source-notes gotcha before falling back.
Neither step has an obvious shortcut without weakening the unseen-check
rigor the brief explicitly asked for this run.

## SCOUT.md issues found
- No outright errors found in SCOUT.md's instructions this run, but the
  README's "Season/parent asymmetry" note in `pool.py --help` (about
  suppress-sync also matching against a season's `meta.show_*_id`) does
  NOT fully substitute for a scout-side sibling-season check when the
  candidate itself has no external_ids at all (most Douban-sourced rows
  in this pool carry only a bare `douban` id, no `meta` linkage back to
  other seasons of the same show) — the base-title-strip fallback the
  docstring describes is a `pool.py`-internal (suppress-sync) matching
  strategy, not something `query` exposes to the scout, so the scout
  still has to manually strip "第N季" and grep the index by hand, per
  candidate, exactly as the brief predicted. Worth a small helper (e.g.
  a `history.py sibling-seasons --title <base-title>` command) if this
  becomes a recurring pain point — noted, not acted on, out of scope
  for this run.
