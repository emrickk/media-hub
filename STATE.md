# STATE — media system living status

> Update this file at the end of any session that changes system state.
> Cold-start agents: read this first, then ARCHITECTURE.md, then
> douban-export/RUNBOOK.md. Machine-local agent memory does NOT sync across
> computers — this file is the cross-machine handoff.

**Last updated:** 2026-08-23 (session: Douban harvest completed — the
`harvest_douban.py` checkpoint went from 69/298 to 298/298 anchors, all
`status: fetched`, no blocks or circuit-breaker trips across 5 sequential
`fetch` invocations; the whole raw corpus was then re-transformed under
the new genre-tag extraction and upserted, taking the pool's `douban_rec`
channel from 984 to 3,160 rows (3,150 of them, 99.7%, now carry tags); see
"Recommend system — Douban harvest completed" below. Prior same day:
pitch page + id-fabrication fix — `recommend/render.py` added, the system's user-facing surface: it turns logged `recommendations` rows into one self-contained HTML card page (cover, synopsis, the scout's case as the reason, predicted stars + percentile, verdict buttons that copy the `reclog.py verdict` command). Read-only view, safe to run against a busy DB. Wired into SKILL.md as step 5b. Building it surfaced a real defect — see "Recommend system — fabricated tmdb ids" below. Prior same day: recommend log — a completed
recommendation run logged, 6 new candidates, 4 pitched/selected, 1
survived-not-selected, 1 killed; see "Recommend system — run logged
(下饭剧 + 高密度电影 ask)" below. Prior same day: shells season/parent
bug fix — a live run had pitched Only Murders in the Building, Brooklyn
Nine-Nine and Poker Face as "unwatched discoveries" though all three are fully watched;
root cause: TV is stored one row per season plus a `kind='show'` parent
row that never carries its own record, so `history.py`'s `shells` and
`pool.py`'s `suppress-sync` both missed the parent/season relationship.
Fixed in both places (id-match on the season's `meta.show_*_id` vs the
parent's own `external_ids`, base-title fallback gated by a real season
family + year so unrelated same-titled works never collapse). Real DB:
shells 222 → 157 (65 excluded, all verified genuine — 3 more than the 62
first spotted by eye, the extra 3 being Plex English-titled `show` rows
id-matched to their Chinese Douban season family). `suppress-sync`
newly suppressed 10 pool rows (all reason `watched`) — write ritual
followed: `lsof` clean, WAL checkpointed, backup
`backups/media-recommend-20260823-190157.db`. Pre/post works/records/
external_ids unchanged at 4,359/5,539/11,272. Tests: 108 → 115 (7 new,
all passing), all pre-existing tests still passing. Full report:
`/private/tmp/claude-501/-Users-anping-Documents-Stuff-AI-Space-media-hub/009324b1-0160-40fe-ab60-bff5f78ff9bb/scratchpad/sdd/v2-pool/shells-fix-report.md`.
Prior same day: v2 pool bootstrap — the recommend
system's `candidate_pool` got its first real harvest from live TMDB and
Douban data, 0 → 4,297 candidates; see "Recommend system v2 — pool
bootstrap" below. Prior same day: recommend-system recalibration —
the critic's judgment layer moved from an absolute ≥4★ floor to a
percentile-against-own-history gate; the 16 calibration-session-#1 rows
were re-judged in place and a floor-rule re-sweep added 8 more, see
"Recommend system — recalibration (percentile gate)" below. Prior same
day: calibration session #1 — two real asks run through the recommend
system and logged, 16 rows / 0 kills, see "Recommend system —
calibration session #1" below. Prior same day: the recommend system
built end-to-end — engine docs, python helpers, `/recommend` skill, new
`recommendations` table — followed by a whole-system review and one
consolidated fix wave. Prior: 2026-08-06 19:22 PT Spotify Account Data
export, snapshotted raw-first, NOT loaded; no media.db writes. Before
that: 2026-08-01 monthly scheduled pipeline — Douban refresh #3, Plex
sync, enrich, resolve, Ryot delta; clean run)


## Recommend system — Douban harvest completed (2026-08-23, latest)

Finished the Douban side of the v2 candidate-pool harvest — the checkpoint
had been sitting at 69/298 anchors (all `film`-kind remaining). Read-first
per the brief: `harvest_douban.py` (+ `--help`), `pool.py --help`,
`recommend/README.md`'s write ritual.

**Task A — harvest.** `anchors --db media.db` -> 298 total (162 tv, 136
film). `fetch` run resumed from the existing checkpoint across **5
sequential invocations** (`uv run recommend/harvest_douban.py fetch
--anchors <scratchpad anchors.json> --raw-dir recommend/raw/douban/2026-08-23/
--checkpoint recommend/raw/douban/checkpoint.json --budget 45`, last one
`--budget 49` to finish the tail), each kept under the harness's shell
timeout by the 45-anchor budget (~45 × up-to-10s jittered delay stays
under 600s). Final checkpoint: **298/298, every entry `status: "fetched"`
— no 403/302 block, no 8-consecutive circuit-breaker trip.** Politeness
(5–10s jittered delay, no rate increase, no retry-into-block) held
throughout.

**Task B — genre tags, whole corpus.** Re-`transform`ed all 298 dated raw
files in `recommend/raw/douban/2026-08-23/` (the pre-existing 69 plus the
229 just fetched) under the just-landed `card_subtitle` genre extraction:
`{"raw_pages": 298, "blocked": 0, "skipped": 0, "entries": 5960}`, 5,933
of those 5,960 batch entries (99.5%) carrying a non-empty `tags` list.
`pool.py upsert`: **2,176 inserted, 3,784 merged** (2,176 matches the
pool's total delta exactly, confirming no double-counting).

**Write ritual:** `lsof media.db*` clean (no other writer) — STATE.md
lane check clean (Douban harvest is exactly this session's own lane, no
conflict) — `PRAGMA wal_checkpoint(TRUNCATE)` — backup
`backups/media-recommend-20260823-201619.db`. Only `candidate_pool`
touched: works/records/external_ids confirmed **unchanged at
4,359/5,539/11,272**, both before and after.

**Pool stats before:** `{"total": 4297, "by_kind": {"film": 3112, "tv":
1185}, "evidence_cached": 7, "suppressed": 411, "by_channel":
{"tmdb_discover_recent": 50, "tmdb_rec": 3265, "douban_rec": 984}}`.
**After `upsert` + `suppress-sync`** (608 newly suppressed, all reason
`watched`, 0 `rejected`): `{"total": 6473, "by_kind": {"film": 4788, "tv":
1685}, "evidence_cached": 7, "suppressed": 1019, "by_channel":
{"tmdb_discover_recent": 50, "tmdb_rec": 3265, "douban_rec": 3160}}`. Of
the pool's 3,160 `douban_rec` rows, **3,150 (99.7%) now carry at least one
tag** (up from 0 tag-carrying `douban_rec` rows before this session — the
extraction is new). Douban's half of the pool is now tag-filterable via
`pool.py query --tag`/`--channel douban_rec` for both the pre-existing
and newly-harvested anchors alike.

Full report:
`/private/tmp/claude-501/-Users-anping-Documents-Stuff-AI-Space-media-hub/009324b1-0160-40fe-ab60-bff5f78ff9bb/scratchpad/sdd/v2-pool/douban-complete-report.md`.


## Recommend system — pitch page + fabricated tmdb ids (2026-08-23)

**New:** `recommend/render.py` — the only user-facing surface. `python3
recommend/render.py --db media.db --ids <ids> --open` renders the logged
slate as one self-contained HTML page (posters + synopses fetched from
TMDB, Douban subject page as fallback, cached under `recommend/covers/`
and inlined as data: URIs so the file works from file:// with no server).
Picks lead the page in `pitch_rank` order; survivors the critic left
`pitch_selected: false` sit below under "也通过了，这次没选上"; `--include-killed`
adds the kills. Read-only connection — it never writes media.db, so it is
safe to run while a harvest or a log pass holds it. SKILL.md step 5b.

**Defect it found, now fixed:** the renderer checks each logged
`external_ids` entry against what the source says that id actually is,
and **2 of the 15 rows carrying a tmdb id were wrong** — both from the
2026-08-23 下饭剧 run, both Douban-origin pool candidates:

| row | work | logged id | that id really is | corrected to |
|---|---|---|---|---|
| 25 | 地球脉动 / Planet Earth (2006) | `tmdb_tv 1861` | Ain't Misbehavin' (1994) | `tmdb_tv 1044` |
| 26 | 人类星球 / Human Planet (2011) | `tmdb_tv 2795` | GMA Network News | `tmdb_tv 32062` |

Both pool rows carried **only** a douban id (`candidate_pool` 3368 for
人类星球 has `{"douban": "5950117"}` and nothing else), so the harvesters
are clean — the tmdb ids were introduced during the run, from memory,
which is exactly what the house rule forbids. Corrected in place after
verifying each against TMDB search + a detail read (TMDB's own zh name
for 32062 is 人类星球, 8 episodes). Write ritual followed: `lsof` clean,
WAL checkpointed, backup `backups/media-recommend-idfix-20260823-195459.db`.
Only rows 25/26's `external_ids`, `dossier.scout.external_ids` and a new
`dossier.id_audit` key changed; `recommendations` still 30, works/records/
external_ids unchanged at 4,359/5,539/11,272.

**Standing implication:** a scout dossier can carry an id no harvester
ever produced, and until now nothing downstream checked. `render.py`'s
`id_warnings` output is the check — SKILL.md step 5b requires reading it
after every run. Tests: 130 → 146 (16 new in
`recommend/tests/test_render.py`, 8 of them on the id guard).

## Recommend system — run logged (下饭剧 + 高密度电影 ask) (2026-08-23, latest)

A completed scout/critic run (an interactive ask, not a digest) was logged
into `recommendations`. Ask verbatim: `下饭剧优先：低认知负荷、分集式、可打断，
可以边吃饭/边玩游戏放的剧；外加一部值得专门找时间看的高密度电影。范围：新近上映/
开播或口碑新起的，以及经典中明显契合口味而从未看过的。总量小而准：剧 2–3 部、
电影 1–2 部。` All 6 candidates originated from `candidate_pool` (the
external-only policy holds — the library was not a candidate source):
地球脉动/Planet Earth, 人类星球/Human Planet, The IT Crowd, Seinfeld, 怪物/
Monster, Rear Window.

**Outcome split:** 4 survived and were selected for the pitch (怪物 rank 1,
Rear Window rank 4, 地球脉动 rank 3, Seinfeld rank 5); 1
survived but was **not** selected (人类星球/Human Planet — redundant against
地球脉动, same BBC observational-doc shape and era; recorded `critic_killed=0`
per this run's disambiguation, with `pitch_selected: false` and its
`selection_reason` preserved verbatim inside the row's `dossier.critic`);
1 killed (The IT Crowd — predicted 3.0★, 13.8th percentile of its cell,
well below the 70th-percentile target).

**Note on SKILL.md's mapping:** step 5's `outcome`→`critic_killed` table
does not explicitly address a `"survive"` candidate the critic left
`pitch_selected: false` for cap/redundancy reasons (as opposed to the
pitch-cap case it does cover). Per this run's brief, that case was treated
as `critic_killed=0` (it cleared the gate) with the selection detail kept
recoverable inside `dossier.critic` — consistent with the general rule
that `pitch_selected`, `pitch_rank`, and `selection_reason` "ride along
verbatim" rather than get their own columns. Worth folding into SKILL.md's
table explicitly if this case recurs.

Write ritual followed: `lsof media.db*` clean, WAL checkpointed, backup
`backups/media-recommend-20260823-192547.db`. `recommendations` 24 → 30
(ids 25–30, all `work_id: null` — verified against `external_ids` directly,
no match for any of the 6 candidates' tmdb/douban ids anywhere in `works`).
Pre/post `works`/`records`/`external_ids` unchanged at 4,359/5,539/11,272 —
only `recommendations` touched. `pending` now lists 18 rows (13 prior +
5 new non-killed); `stats` reports `pitched=18, hits=0` (no verdicts yet,
expected). Full report:
`/private/tmp/claude-501/-Users-anping-Documents-Stuff-AI-Space-media-hub/009324b1-0160-40fe-ab60-bff5f78ff9bb/scratchpad/sdd/v2-pool/test2-logging-report.md`.

## Recommend system — shells season/parent fix (2026-08-23)

Confirmed correctness bug, found by a live test: a live run pitched Only
Murders in the Building, Brooklyn Nine-Nine and Poker Face as unwatched
discoveries — all three are watched to completion (Brooklyn Nine-Nine
through all 8 seasons). Root cause: media.db stores TV one row per
Douban/NeoDB season (`kind='tv'`) plus a series-level `kind='show'` row
that never carries its own record — so `history.py`'s `shells` (a work
with no watched/watching/wishlist record) and `pool.py`'s
`suppress-sync` both missed the parent/season relationship, listing a
fully-watched series' parent row as an unwatched "shell"/live candidate.

**Fix** (both `recommend/history.py`'s `shells` and `recommend/pool.py`'s
`suppress-sync`, same shape in both): exclude/suppress a candidate that
shares "show identity" with a watched/watching/wishlisted season, id
match first (a season's show-level tmdb/imdb id lives only in
`meta.show_tmdb_id`/`show_imdb_id`, never in its own `external_ids` —
the season-tt gotcha — but matches the show-level parent row's own
`external_ids` directly), base-title (`第N季` suffix stripped) fallback
second, gated by a real season family + matching year so two unrelated
works that merely share a title (a remake, a different production) can
never collapse into each other.

**Real DB, verified read-only then live:** shells 222 → 157 (65
excluded — 3 more than the 62 first spotted by eye; the extra 3 are
Plex English-titled `show` rows, e.g. Gravity Falls/怪诞小镇, matched to
their Chinese Douban season family only via id overlap, which the
base-title path alone could never reach). All 65 manually verified to
have a real watched sibling season — zero suspected over-exclusion.
Confirmed 神探夏洛克, 白莲花度假村, 黑袍纠察队, 真相捕捉, 扑克脸 (and
Only Murders/大楼里只有谋杀, Brooklyn Nine-Nine/神烦警探) no longer
appear as shells. `suppress-sync` (a real media.db write) newly
suppressed 10 pool rows, all reason `watched` — write ritual followed:
`lsof media.db*` clean, `PRAGMA wal_checkpoint(TRUNCATE)`, backup
`backups/media-recommend-20260823-190157.db`. Pre/post
works/records/external_ids unchanged at 4,359/5,539/11,272;
`candidate_pool` total unchanged at 4,297 (401 → 411 suppressed).

**Tests:** 108 → 115 (7 new: 5 in `test_history.py`, 2 in
`test_pool.py` — parent-row-with-watched-season, season-with-watched-
sibling, genuinely-unwatched-still-a-shell, same-title-different-years-
not-collapsed [both modules], suppress-sync-via-sibling-season). All
115 passing, no existing test weakened. Both modules' test DB fixtures
gained `season_number`/`meta` columns on `works` to match the real
schema. Full report:
`/private/tmp/claude-501/-Users-anping-Documents-Stuff-AI-Space-media-hub/009324b1-0160-40fe-ab60-bff5f78ff9bb/scratchpad/sdd/v2-pool/shells-fix-report.md`.

## Recommend system — calibration lifecycle change (2026-08-23, later same day)

A TASTE.md recalibration pass (population-scale mining, 6 hypotheses) was
REJECTED by Anping and the rejection adopted as design: hypothesis-ratification
interviews are discontinued; TASTE.md is his voice, edited only at his
initiative. Calibration = the rec-log verdict loop (verdicts + post-watch
ratings vs sealed predictions); mispredictions update engine priors, never the
profile. The mined numbers survive as prediction priors
(`analysis/taste-recalibration-hypotheses-2026-08-23.md`, retagged). Spec Part B
amended; SKILL.md step 7 repointed. No TASTE.md or media.db changes this pass.

## Recommend system v2 — pool bootstrap (2026-08-23)

Task 5 of the v2 plan (`docs/superpowers/plans/2026-08-23-media-recommend-v2-pool.md`):
the first real harvest, run against live TMDB and Douban data (previously
only exercised against mocks/fixtures). Write ritual followed: `lsof`
clean, WAL checkpointed, backup `backups/media-recommend-20260823-180057.db`.
Pre/post `works`/`records`/`external_ids` unchanged at 4,359 / 5,539 /
11,272 — `candidate_pool` is the only table touched, as designed.

**TMDB tranche (`harvest_tmdb.py`), complete.** 147 anchors (138 film + 2
show + 7 tv — 1 of the 7 carries a `tmdb_movie` id rather than
`tmdb_tv`, passed through as-is). `fetch --pages 2 --recency-months 18`:
292 fetched, 8 failed (4 anchors × 2 pages, all HTTP 404 — stale/retired
tmdb ids on works 663, 978, 1710, 3310; not investigated further, matches
the harvester's documented partial-harvest-is-normal contract).
`transform`: 5,400 candidate rows, 400 dropped below the vote-count floor
(50). `pool.py upsert`: 3,313 inserted, 2,087 merged.

**Douban tranche (`harvest_douban.py`), first tranche — deliberately
partial.** 298 anchors carry a douban id (162 tv, 136 film; the 2 show
anchors carry none). Anchors were tv-first ordered before fetch so the
budget spends on the TV lane's only CF surface. `fetch --budget 40
--delay-min 5 --delay-max 10`: needed 3 invocations because this
session's shell tooling killed the first two on its own 2-minute
default timeout (not a Douban block) — the checkpoint's crash-safe,
resume-skips-done design absorbed this cleanly, so the cumulative
session total ran to **69/298 anchors fetched**, all `kind=tv`, all
HTTP 200, zero blocks, zero circuit-breaker trips, delays honored
throughout (never shortened, never retried into a failure). Checkpoint
lives at `recommend/raw/douban/checkpoint.json` (new — no prior
convention existed) and is resumable across sessions; remaining
229/298 anchors (all film, since tv is now exhausted) ride subsequent
sessions/digests. This is designed behavior per the plan, not a
shortfall. `transform`: 69 raw pages → 1,380 candidate rows, 0 blocked,
0 skipped. `pool.py upsert`: 984 inserted, 396 merged.

**Pool state after `suppress-sync`:** `{"total": 4297, "by_kind":
{"film": 3112, "tv": 1185}, "evidence_cached": 0, "suppressed": 401,
"by_channel": {"tmdb_discover_recent": 50, "tmdb_rec": 3265,
"douban_rec": 984}}`. `suppress-sync` newly suppressed 401 rows, all
reason `watched` (0 `rejected` — no prior `recommendations.verdict='no'`
rows overlap the pool yet). Sanity checks from the plan: total 4,297 ≥
800 ✓; tv candidates from `douban_rec` > 0 (984, all tv) ✓; default
`query` (suppressed rows excluded) returns 3,896 = 4,297 − 401, i.e.
**zero** suppressed rows visible without `--include-suppressed` ✓.

Test suite still green: `python3 -m pytest recommend/tests/ -q` → **108
passed**. `TMDB_API_KEY` never printed; raw files under
`recommend/raw/tmdb/2026-08-23/` and `recommend/raw/douban/2026-08-23/`
grepped clean of the key. ARCHITECTURE.md gained one entry each for
`candidate_pool` and the two harvesters. **Next (Task 6, user-gated):**
Anping's approval needed before adding harvest/refresh to the monthly
scheduled pipeline, then one real interactive pool-first ask to
retest against the ≤5 min target.

## Recommend system — BUILT (2026-08-23)

A scout/critic film/TV recommendation pipeline now exists. It predicts
what Anping would rate a title and pitches only what clears his ≥4★
threshold. Spec:
`docs/superpowers/specs/2026-08-23-media-recommend-design.md`.
Architecture entry: ARCHITECTURE.md §3a (whole system) and §3
(`recommendations` table).

**What exists.** `recommend/SCOUT.md` (retrieval + funnel contract) and
`recommend/CRITIC.md` (adversarial gate) are the engine — and they are
**prose read by an LLM at runtime**, so an ambiguity in them is a runtime
bug; treat them as code. Both are strictly user-agnostic:
`recommend/README.md` is the only file allowed to name TASTE.md,
media.db, the threshold, or any other instance fact. `recommend/
DIGEST-INTENT.md` holds the scheduled-digest default ask.
`recommend/history.py` is the read side (`snapshot`, plus `index` and
`lookup` for querying it), `recommend/reclog.py` the write side,
`recommend/precedence.py` the resolver they share.
`.claude/skills/recommend/SKILL.md` is the `/recommend` orchestration.
Funnel logs land in `recommend/logs/`.

**Not yet run against a real ask** — Task 7 is user-gated and needs Anping
to supply one. The first sessions are calibration sessions: he grades the
reasoning, not just the picks (spec A8).

**Fix wave after the final whole-system review (same day).** One
Critical and eleven Important findings, all applied. The Critical: the
critic was being handed `snap.json` (~900KB / ~40,000 lines) to read, and
a model Read caps at 2,000 lines — it would have reasoned about "this
user's history" from an arbitrary 5% recency slice while believing it had
all 1,702 rated works, silently. Fixed by giving the critic **query
access** rather than a curated extract (a scout-chosen subset would let
the searching party pick which history the judge sees, destroying the
blindness the design rests on): `history.py index` emits one compact line
per rated work — 1,717 lines / 94KB, readable in one pass, ending in an
`END OF INDEX` marker so a truncated read is detectable — and
`history.py lookup` pulls full detail incl. review text by
`--work-id` / `--title` / `--creator`, from the snapshot file alone.
Also in the wave: thin evidence now widens the confidence band instead of
lowering the predicted rating (it was being killed at the predicted-stars
check before the evidence-tier amendment could protect it, which fell
hardest on Chinese-language titles — genuine Chinese-language TMDB review
coverage measures ~0%); `shells` wired into SCOUT.md as a real retrieval
channel; the critic↔dossier join moved off title strings onto a
`dossier_index`; one log row per candidate carrying its final outcome;
`predicted_stars` range-guarded; the Chinese-first "absence is a
documented negative" rule restated inside CRITIC.md, which never sees
SCOUT.md.

## `recommendations` table added (2026-08-23)

New additive-only table `recommendations` (`CREATE TABLE IF NOT EXISTS`,
spec `docs/superpowers/specs/2026-08-23-media-recommend-design.md` §A5):
logs every pitched/killed candidate from the recommend system with sealed
`predicted_stars`, verdicts, and dossier JSON. Written only by the new
`recommend/reclog.py` (insert/update, never destructive — no delete command
exists). `recommend/history.py` added alongside it as the one-transaction
read snapshot (rated/wishlist/shells/rec_log) the scout/critic pipeline
reads before any network I/O. No other tables touched; `lsof` was clean
before the write. Backup taken immediately pre-init:
`backups/media-recommend-init-20260823-142104.db`. The **recommend lane now
exists** — see ARCHITECTURE.md §3 for the schema entry.

**Two post-review fix rounds landed the same day**, both against real-DB
evidence, not speculative:

- **Fix round 1 — `history.py` multi-source dedup.** `rated` now emits
  exactly one entry per `work_id` instead of one per source record: `stars`
  and `review` are each independently resolved from the highest-precedence
  source that actually has that field (`manual > douban > letterboxd >
  plex`, shared as `recommend/precedence.py`), `sources` lists every source
  with a watched/watching record for the work, and `rating_variants`
  (`{source: stars}`) appears only when sources genuinely disagree on the
  rating — never silently resolved away. `shells` was rewritten to drop its
  `JOIN records` (a true library-only shell has **zero** records rows, so
  the join could only ever return nothing) and now selects from `works`
  alone. Real-DB snapshot after the fix: **rated=1702, wishlist=91,
  shells=222, rec_log=0** (pre-fix `rated` had wrongly reported 2936 by
  counting per-source rows, and `shells` wrongly reported 0).
- **Fix round 2 — `reclog.py` carried the same class of bug plus an input
  hardening gap.** `cmd_stats`'s `sealed_vs_actual` had the identical
  per-source duplication defect (a plain `JOIN records`); now resolves one
  entry per recommendation row via the same shared `precedence.pick_best`.
  `cmd_check --title` without `--year` now fails loudly instead of silently
  no-op'ing (title-only matching across years is the remake/same-name
  identity error this project's hard rules guard against — `--ext
  namespace:value` is the correct id-based path). `cmd_log`'s batch insert
  now validates the WHOLE batch (`intention`, `kind`, `title` required) up
  front and reports every bad row (index + missing field + title if
  present) in one message, all-or-nothing — previously a malformed
  LLM-assembled batch row crashed with a bare `KeyError` mid-insert.

**Fix wave 3 (final review) added a third dedup correction and two
guards.** A same-source precedence tie IS reachable — `records` is
`UNIQUE(source, work_id, status)`, so one source can hold both a
`watched` and a `watching` row for one work and `_rated_entries` gathers
both; it used to resolve by cursor order. `precedence.pick_best` now
orders source → status (`watched` > `watching`) → most recent
`marked_at`, and `rating_variants` resolves each source's rating the same
way instead of taking whichever row the cursor yielded first. Separately,
`reclog.py log` now rejects an out-of-range `predicted_stars` (stars are
0.5–5.0; `records.rating` is 0–10 — mixing them silently corrupted the
`stats` accuracy metric), a non-object batch row, and a non-numeric
`critic_killed`; the DDL gained a matching `CHECK` for new databases
only, since the live table is deliberately never rebuilt. Both helpers
now set `PRAGMA busy_timeout=15000` so a concurrent agent session waits
for the lock instead of erroring immediately.

Test coverage: `recommend/tests/` is **51/51 passing** (`test_reclog.py`
20, `test_history.py` 19, `test_precedence.py` 12 — the resolver had no
direct tests before this wave). Real-DB verification after the wave:
**rated=1702, wishlist=91, shells=222, rec_log=0**; index = 1,702 entries
/ 1,717 lines / 94KB, of which 558 works carry review text and 93 are
watched-but-unrated.

## Recommend system — calibration session #1 run + logged (2026-08-23)

Anping supplied the first two real asks. **Run A** (ask verbatim: `我最近
看了 the office 我觉得好好看，你有没有什么别的推荐？`): funnel ~95
gathered → 26 → 8 dossiers, all 8 survived the critic (The Paper, Parks
and Recreation, What We Do in the Shadows, Abbott Elementary, Jury Duty,
Superstore, 30 Rock, Nathan for You). **Run B** (ask verbatim: `有什么最
近的好看的电影推荐？`): funnel 44 → 27 → 8 dossiers, all 8 survived
(南京照相馆, 浪浪山小妖怪, 罗小黑战记2, 捕风追影, Project Hail Mary,
Wake Up Dead Man: A Knives Out Mystery, Black Bag, F1). Funnel logs:
`recommend/logs/2026-08-23-office-followups.md`,
`recommend/logs/2026-08-23-recent-films.md`.

Logged via `reclog.py log` (write ritual followed: `lsof` clean, backup
`backups/media-recommend-20260823-154344.db`): **16 rows, ids 1–16, 0
critic kills** — every candidate that reached a critic survived, so this
run has no kill-rule exercise yet. All 16 rows carry `work_id: null`; a
full external-id sweep against the same-session `snapshot` found zero
matches against `works` (rated/shells/wishlist), confirming none of the
16 candidates were already in the library rather than assuming it.
Post-write sanity: `works=4359`, `records=5539` (both unchanged from
pre-write), `recommendations=16` (was 0). `pending` lists exactly these
16 rows; `stats` reports `pitched=16, hits=0` (no verdicts yet — this is
expected, not a defect). Verdicts are Anping's next step, via
`reclog.py verdict --id N`.

## Recommend system — recalibration (percentile gate) (2026-08-23)

Calibration session #1's critic predicted 4.0/4.5★ for all 16 candidates
and killed nothing — on this user's history that bar is close to
meaningless (4★ is his modal rating, 60.5% of everything he's ever rated
clears it). The judgment layer was rebuilt: the gate is now **the 70th
percentile of the candidate's own cell (kind × era), mid-rank
convention** rather than an absolute star floor, so an identical 4★
prediction is judged against TV's warm 74%-≥4★ history and a recent
film's cold 44%-≥4★ history separately instead of by one shared number.
Full rationale + the measured ladders live in `recommend/README.md`
("Why a percentile, not a star floor"); no engine file (`SCOUT.md`/
`CRITIC.md`) changed — the number lives in the instance layer per
design.

The same 16 candidates were re-judged by the calibrated critic, and a
floor-rule re-sweep (run A alone dropped to 1/8, below the survive-≥2
floor) added 8 never-before-seen candidates:

- **Run A** (office-adjacent sitcoms, ask `我最近看了 the office 我觉得
  好好看，你有没有什么别的推荐？`): **8/8 → 1/8** survived recalibration
  — only Abbott Elementary (4.5★, 77.8th pct) cleared 70 in the `tv/show
  2020-2026` cell (n=142); the other 7 (The Paper, Parks and Rec, What We
  Do in the Shadows, Jury Duty, Superstore, 30 Rock, Nathan for You) sat
  at the cell's ordinary 4★/4.5★ outcome (55–68th pct), not its top
  slice. The floor rule fired on this result (1 < 2 survivors) and
  triggered one re-sweep pass.
- **Run B** (recent films, ask `有什么最近的好看的电影推荐？`): **8/8 →
  7/8** survived — only Black Bag (3.5★, 55.2nd pct) missed; the
  `film 2020-2026` cell is far more permissive (a bare 4★ already clears
  70 there, 74.8th pct), so most of the original slate held.
- **Re-sweep** (same ask as run A, new angle: food/industry documentaries
  + adjacent creative-team titles per TASTE.md's named high-hit-rate
  categories): **5/8 survived** — The King of Kong: A Fistful of
  Quarters, 人生一串 第一季, Jiro Dreams of Sushi, Light & Magic, and
  Abstract: The Art of Design cleared 70; 舌尖上的中国 第二季, Chef's
  Table, and Tuca & Bertie did not.

Logged via direct `sqlite3`/Python (not `reclog.py log` — it has no
update-dossier command; same discipline: parameterised statements, one
transaction, no DELETE/DROP/schema change, `recommendations` the only
table touched). Write ritual: `lsof` clean, backup
`backups/media-recommend-20260823-172151.db`. **16 rows (ids 1–16)
updated in place** — `predicted_stars`/`predicted_confidence`/
`critic_killed`/`kill_reason` set to the calibrated outcome, and inside
each row's `dossier` JSON the original (uncalibrated) critic object was
preserved under a new `critic_uncalibrated` key while the calibrated
critic object took over the `critic` key, so both systems can be scored
against the same eventual rating. **8 new rows inserted (ids 17–24)**
for the re-sweep candidates — same `intention` as run A, dossier shape
`{"scout", "critic"}` (no `critic_uncalibrated`, never logged before).
One re-sweep candidate, The King of Kong: A Fistful of Quarters, matched
an existing library shell (`work_id=4319`, confirmed zero `records` rows
via external_ids join) and got that `work_id` set; the other 7 got
`work_id: null` as usual for a candidate not yet in the library.

Post-write: `recommendations` row count 16 → 24. `pending` lists 13 rows
(the total survivor count across all three runs); `stats` reports
`pitched=13, hits=0` (no verdicts yet, expected) with a clean
`sealed_vs_actual` (empty — none of the 13 have a matching rated
`records` row). Verdicts remain Anping's next step.

## Spotify "Account Data" export — snapshotted, NOT loaded (2026-08-06)

Anping produced a second Spotify ZIP (generated 2026-08-01). It is a
**different product** from the Extended Streaming History export loaded on
07-29, but ships under the **same filename** `my_spotify_data.zip` — sha1s
differ (account `63d6d96c…` ~957KB vs extended `46ba0158…` ~7.6MB). Check the
hash, not the name.

Snapshotted to **`sources/raw/spotify-account/2026-08-06/`** — its own source
root, deliberately NOT a new dated dir under `sources/raw/spotify/`, because
`pull_spotify.py load-plays` defaults to `latest_snapshot_dir()` and would
pick an account export as "latest", then match no `Streaming_History_[AV]*`
and fail confusingly for the music lane. (`cmd_hydrate` is unaffected — it
globs `20*/tracks_hydrated.jsonl` across all dated dirs.) Also note
`pull_spotify.py ingest` recognises `StreamingHistory*` and would have
snapshotted only the 3 history files, silently dropping the other 24 — this
was snapshotted by hand. Full file-by-file assessment:
`sources/raw/spotify-account/README.md`.

**No media.db writes this session.** Why nothing was loaded:
liked (1,285) and playlist items (852) **exactly match** existing event
counts; the 10,074 history rows overlap the loaded plays except **17**
(≈1.1 h, past the extended export's 07-27 cutoff) and that format has no
track URI and only minute-resolution timestamps, so the
`ts|track_id|ms_played` play-uid (ARCHITECTURE §3) can't be built — a
double-count risk not worth 17 plays; searches (131) have no table and no §5
consumer. PII files stay inside the ZIP, never extracted, never in the DB.

**Correction to an in-session claim:** `Follow.json`'s `userIsFollowing` (90)
are followed **user profiles** (numeric ids), NOT artists. The 07-28 OAuth
`library_following.jsonl` (2 followed *artists*) was correct and complete for
what it pulls — an earlier statement in that session that it was "clearly
incomplete" was wrong.

**The one item with real value: `YourLibrary.albums` — 72 saved albums**,
never pulled before (the 07-28 OAuth pass never called `/me/albums`).
Deliberate album saves outrank liked tracks as a taste signal. Left for the
**music lane** (threads 2–3) and the open §8 "when to clean music" decision,
since album names must go through the NeoDB/UPC path, never name matching
(§3: name similarity never auto-links). `TasteProfile.json` is worth a read
whenever a music taste model gets built — TASTE.md is film/TV only today.
Export is already stale (history ends 07-31); request a fresh one if/when the
music lane wants the albums.

## Monthly pipeline run (2026-08-01, scheduled task) — clean

Ran `monthly-douban-backup`. Previous snapshot archived to
`Emrick/_archive-20260801/`; fresh full walk **2,830 items**, `ok: true`,
0 failures. Shortfalls all match the documented stable set (movie 21 /
music 6 / game 1 / movie_wish 1 / book 2) — **no flaky-API drop this walk**
(book_collect served the full 278 again), so `union_refresh.py` restored 0
rows.

**Diff vs archive: 2 added, 7 comment edits, 0 removals, 0 status moves.**
Nothing needed Anping's confirmation.

- **New:** 辐射 第一季 / Fallout S1 (douban 35128081) → work **#5959**, and
  辐射 第二季 / S2 (douban 36846801) → work **#5958**. Both ★4, marked
  2026-07-31, NeoDB-verified (`5FyXt7D9AV5ieWNoDj7OPV` /
  `2F752sEcZtNMMgLzN8J83K`), covers fetched. NeoDB returns the **show-level**
  tt12637874 / tmdb 106379 for both seasons; load_clean.py's season-tt
  rule put them in `meta` as `show_*`, NOT as external_ids, so the two seasons
  did not collide. `resolve` confirms: 0 merges, 0 queued.
- **Plex sync** added 3 works: **#5960 Tenet**, **#5961 Dark Matter (2024)**,
  **#5962 Industry** — library presence only, no watch records yet.
- **enrich-douban** ran to exhaustion: 19 enriched over 3 passes; **3 stall
  permanently** — 极限挑战 S1, 极限挑战 S3, 奇葩说 S1, Chinese-only variety
  shows with no original title (documented first-class negative, not a
  failure).
- Verified after load: works 4,359 (+5, exactly the new items), records 5,539,
  **0 records deleted**, match_queue pending 0, every work still ≥1 external
  id, `integrity_check` ok, WAL checkpointed. Dumps + library.html rebuilt
  (movies 1,785→**1,787**, books 574, games 1,114). Backup:
  `backups/media-monthly-pipeline-20260801-100237.db`. sync_runs 54–56.

**⚠ Two findings the scheduled task file is now stale on** (it was written
before the 2026-07-29 folder cleanup):

1. **`douban_export.py` alone can never see new items.** The task's step 1 is
   a plain re-run, which resumes old checkpoints and returns `+0` on every
   list (it did exactly that on the first attempt this session: 2,828 items,
   all `↻ resuming`). Only after archiving the snapshot did the fresh walk
   find the 2 new seasons. **The task file should be amended to archive
   first** — see RUNBOOK "Resume ≠ refresh".
2. **6 of the scripts it names no longer exist at root** — `enrich_lb_tmdb.py`,
   `enrich_tmdb_search.py`, `enrich_neodb.py`, `fix_custom_lots.py`
   (→ `attic/oneoff-migration-202607/`), `custom_upgrade.py`,
   `ryot_sync_records.py`, `export_ryot_custom.py` (→ `attic/ryot/`). They
   were deliberately retired; `attic/README.md` says they will not run in
   place. **Not resurrected.** Their live replacement for NeoDB identity is
   the douban-export clean chain (`clean_movies.py` → `deep_pass.py` →
   `merge_library.py` → `load_clean.py`), which is what was run instead and
   which resolved both new seasons (2 lookups, 1,737 cached, 0 unresolved).

**Ryot: 0 pushed this run** (`export_ryot.py` delta: 0 new titles, 0 watches,
0 reviews; 1,761 already there). Correct, not a bug — the 3 Plex works have
no records to export, and the 2 new seasons hold their TMDB id in `meta`, so
they land in the "318 film/tv without a TMDB id" bucket. **Systemic gap worth
a decision:** under the season-tt rule, *no* TV season can ever reach Ryot via
`export_ryot.py`; the custom-entry lane that used to cover them
(`export_ryot_custom.py`) is retired. Ryot's Plex-yank integration still pulls
Plex/Infuse watches on its own.

**Letterboxd sync skipped:** `letterboxd.com/emrickw` returns **404** — the
account is deleted, as ARCHITECTURE/attic already record. The 1,131 letterboxd
records in media.db remain the frozen sole-source copy and were untouched.

## Douban refresh (2026-07-30) — loaded, decision resolved

Fresh full walk (2,815 items) after archiving the previous snapshot to
`Emrick/_archive-20260730/`. Diff vs archive: **1 new work, 16 comment/rating
edits, 0 removals, 0 status moves.**

- **New:** 绝望写手 第四季 / Hacks S4 (douban 36910966) → work **#5957**,
  kind tv/S4, NeoDB-verified (`2CiroZBnssSVZh3KTZgOpp`), ★4, cover fetched.
  Show-level tt11815682 / tmdb 124101 in `meta`, not as external_ids.
- **Edited:** 15 films/seasons gained a 短评 he wrote since 07-28, and
  早间新闻 第二季 dropped ★3→★2 (douban record 6.0→4.0).
- Books: the flaky-API drop hit again (book_collect served 265/280, book_wish
  served 64 vs the archive's 43). `union_refresh.py` (new, see RUNBOOK)
  restored 13 book rows from the archive; final book_collect 278 = archive
  parity. Evidence they are flaky drops rather than unmarks: all 13 subject
  pages return 200 (the RUNBOOK's documented check), and book_wish moved the
  OTHER way this walk (43→64), i.e. the lists are unreliable in both
  directions. Not re-verified mark-by-mark on his profile.
- Load: `mediahub.py ingest-douban` (2,828 records) + `load_clean.py`.
  douban records 2,825→2,826; every other source byte-identical; **0 records
  deleted**; match_queue pending 0; every work still ≥1 external id.
  Cover gaps unchanged (663, of which 654 = the uncleaned music set).
  Backup: `backups/media-pre-douban-refresh-20260730-153651.db`.
  Dumps + library.html rebuilt (movies 1,785 / books 574 / games 1,114).

**Manual-shadowing conflict — RESOLVED by Anping 2026-07-30.** The 07-28
dictated `manual` records outrank `douban`, so for 14 of the 16 edits his
NEWER Douban 短评 was not what displayed. **His call: newer Douban text wins,
and ratings follow the same rule** so each work's rating and comment come from
one source. Applied to works 447, 448, 449, 453, 457, 4369, 4370, 4372, 4374,
4377, 5947, 5949, 5954, 5955 by blanking review+rating on the `manual` row
only — **rows kept**, status/marked_at untouched, and the dictated wording
preserved in `raw.retired_review` / `raw.retired_rating` / `retired_on`, so
any of it can be restored without a backup. resolved.py precedence itself is
UNCHANGED (manual still outranks douban); this was a data edit, not a rule
change. Verified: all 14 now resolve to the Douban text and rating; manual
records still total 106. sync_runs id 51. Backup:
`backups/media-pre-manual-retire-20260730-160030.db`.

Two consequences worth knowing:
- **守护解放西 S4 flipped ★2→★4** (8.0), reversing an explicit 07-28 form
  confirmation. He saw this exact pair in the question and chose Douban, so
  it is intended — but the family is now mixed: **S3 stays manual ★2**
  (douban says ★3/6.0) while S4 follows douban. Worth asking whether S3
  should be revisited for consistency.
- The other **13 works whose manual rating still diverges from douban** were
  deliberately left alone (no new Douban 短评, so his 07-28 confirmations
  stand): 疯狂派对1/2, 海洋之歌, 白宫杀人事件, 走走停停, 守护解放西3,
  真相捕捉 S2, 杀死伊芙 S2, 老友记 S6, 亿万 S1/S2/S4, 守护解放西6.

## Loader regression caught + fixed (2026-07-30)

`load_clean.py` silently reverted work **#663 茶杯头大冒险 第三季** from
tv/S3 back to `film` — Anping had reclassified it on 07-28, but NeoDB types
that record as `Movie` (verified live: NeoDB's own title is "The Cuphead
Show! **Season 3**", so the typing is an upstream error), so `all_clean.json`
says media_type=movie and every loader re-run undid the human decision.
Sibling seasons #4432/#4433 are tv/S1/S2, corroborating. Fixed durably with a
`KIND_OVERRIDES` map at the top of load_clean.py (same intent as
suppressed_ids: proven wrong once, stays corrected). Override rows keep their
adjudicated identity — that row's upstream imdb (tt23141532) is already in
`suppressed_ids` for #663, so the override deliberately skips the
imdb/tmdb/meta rewrite instead of writing a rejected id into `meta`.
**Open follow-up (pre-existing, not from this refresh):** #663 still carries
`imdb:tt10611608` + `tmdb_movie:103786` as external_ids while its sibling
seasons carry none — a tv season holding a tmdb_**movie** id contradicts the
season-tt rule. Needs verification against the source before any rewrite;
don't touch it from memory.

## Spotify streaming history — landed & loaded (2026-07-29 late)

Export `my_spotify_data.zip` arrived → raw snapshot
`sources/raw/spotify/2026-07-29/` (audio 2018–2026 + video files, ~79MB).
**Plays schema decided with Anping (closes the §8 open item): reuse
`track_events` kind='play'** — full spec in ARCHITECTURE §3 "music event
layer" (uid=`ts|track_id|ms_played` + partial unique index → idempotent
re-loads; slim raw {rs,re,sh,sk,cc}; IP never enters the DB).
Loaded via new `pull_spotify.py load-plays`: **98,754 play events**
(2018-10-09 → 2026-07-27, 5,014 h; includes 41 music-video streams from the
Video files — they carry real track URIs), 699 exact-dupe rows collapsed,
243 podcast/audiobook rows raw-only, **6,723 stub tracks** created (tracks
1,741 → 8,464). Idempotency verified by a second run (0 re-inserts).
Backup: `media-pre-spotify-plays-20260729-222212.db`. media.db 13→47MB.
**Hydration (ISRC fill) partial — rate-limited, resumes tomorrow.** New
`pull_spotify.py hydrate`: single `/tracks/{id}` calls (batch `?ids=` 403s
in dev mode — both tokens, ledger'd in ARCHITECTURE §9). Single-id GETs
initially returned 200 despite the search-endpoint ban, but 429s caught up
after ~594 ids: **2,333/8,464 tracks now carry ISRC, 6,130 to go**, all
progress checkpointed (`2026-07-29/tracks_hydrated.jsonl`). Hydrate now
(a) holds the SAME quota lockfile as spotify_music.py
(`douban-export/.spotify_music.lock`) so passes can't race, and
(b) replays its checkpoint into the DB before any API call
(`--replay-only` = offline mode; recovered 44 kill-orphaned rows).
One-time scheduled task **`spotify-plays-hydrate-resume`** fires
2026-07-30 21:00 PT (after ban lift + clear of any music-lane pass);
it self-reschedules if rate-limited again. Dumps rebuilt post-load:
track_events.jsonl 100,891 rows (98,754 play + 1,285 liked + 852
playlist_add). Track→album work matching stays with the music lane
(threads 2/3).
**⚠ Flag for the music lane / Anping:** thread #1 says a
`spotify-music-continuation` task fires 2026-07-30 17:00 PT, but the
scheduler has NO such task (checked 23:05 PT) — the plan was written to
STATE but the task was never created. That lane needs to create it or run
the continuation manually.
**⚠ Re-verified 2026-07-30 15:09 PT (orientation session): BOTH one-time
tasks are missing.** The machine scheduler (`~/.claude/scheduled-tasks/`)
holds only `monthly-douban-backup`; `spotify-plays-hydrate-resume` (21:00 PT)
does not exist either, despite the paragraph above claiming it was created.
Nothing fires automatically today: the ISRC hydrate resume (6,131 tracks
left) and the music continuation both need manual runs or freshly created
tasks (one at a time; the shared-quota ban lifts ~16:01 PT). Same-time DB
cross-check: all canonical counts in this file verified against media.db
(works 4,353; plays 98,754; tracks 8,464 with 2,333 ISRC; match_queue
pending 0); media.db was lsof-clean.

## 守护解放西 S1/S2 短评 update (2026-07-29)

Anping dictated a replacement comment for S1 (#743) and S2 (#741):
「没有什么比现实更加超现实，也没有什么比现实更加抽象」. Applied to the two
existing manual rows (records 5974/5975) via upsert_record in one
transaction — ratings (★5) and original marked dates (2022-01-14/18)
preserved, comment only. sync_runs logged (manual, 2). Backup:
`backups/media-pre-jfx-comment-20260729-010240.db`. Dumps + library.html
rebuilt (note: library.html renders comments for books only — TV 短评 live
in the DB/dumps/blog export). Fresh blog handoff written to
`exports/library-resolved-20260729.json` (same schema as the 20260728 file,
only these 2 comments + generated date changed; 20260728 original kept).

(Concurrency note: backup files visibly disappeared mid-session — that was
the parallel cleanup session's Anping-approved 17→5 backup prune, see the
"Backups pruned" note below. No conflict: media.db was lsof-clean at write
time and the prune touched backup files only.)

## Folder cleanup (2026-07-29, files only, media.db untouched)

media-hub/ root reduced to docs + DB + the 12 live scripts + outputs.
Everything retired was MOVED (not deleted) into `attic/` — see
`attic/README.md`: `attic/ryot/` (Ryot import lane: 4 stale ryot-*.json
payloads, not-in-ryot.csv, 4 retired scripts; `export_ryot.py` stays live at
root as the optional consumer), `attic/oneoff-migration-202607/` (18
completed enrich/fix/review one-offs incl. merge_tv_seasons.py and the 3.3MB
lb-additions-review.html), `attic/taste-calibration-20260728/` (calibration
scripts + pages). Relocations: lb-additions verdict ledger →
`analysis/lb-additions-decisions-20260728.json` (ARCHITECTURE.md reference
updated); orphaned wikidata TSVs → `sources/raw/wikidata/2026-07-27/`
(nothing reads them; deep_pass.py verdicts are hard-coded).
`attic/_trash-safe-to-delete/` holds the zero-value leftovers (stale
__pycache__, empty fix-report.txt, the rating-refresh review page, backup
WAL/SHM strays) — Anping can empty it anytime.
`attic/rating-refresh-input-20260728.html` is kept as the reusable template
for the rating-refresh workflow (memory `media-rating-refresh-workflow`).
Verified: no live script imports archived code; all 12 root scripts
py_compile clean; `mediahub.py stats` matches canonical counts.
ARCHITECTURE.md gained a "Directory layout" section (the structure is now
documented authority). Stale pointers in 4 machine-local memory files fixed.

**Backups pruned (2026-07-29, Anping-approved):** 17 → 5 checkpoints,
144MB → 65MB. Kept: `media-20260728-120817.db` (day-start, fullest
pre-purge letterboxd state — deepest rollback for the sole-source rows),
`media-pre-lb-additions-20260728-155717.db` (pre mislog-purge verdicts),
`media-pre-douban-refresh-20260728-192823.db`,
`media-pre-manual-refresh-20260728-202715.db`,
`media-pre-manual-write-20260728-225653.db`. Deleted: the 12 intermediate
per-step backups from the completed 07-28 passes, each strictly dominated by
a kept neighbor. Also present (untouched, NOT part of this session):
`media-pre-jfx-comment-20260729-010240.db`, taken 2026-07-29 01:02 by
another session for a "jfx-comment" pass.

## Canonical counts (media.db)

works 4,353 — film 1,411 / tv 513 / show 83 / book 577 / game 1,114 /
music 654 / drama 1. match_queue pending 0. Every work ≥1 external id.
7 dual-id works = deliberate reviewed merges (douban/weread edition twins,
e.g. Titanic theatrical+3D), unchanged since the dedupe pass.
library.html: 影视 1,784 / 图书 574 / 游戏 1,114 (annotated books 80).

## Manual rating/comment refresh (2026-07-28 late evening)

Anping dictated fresh ratings + blog-ready short comments for ~100 works
(TV seasons, films, games) in conversation; finalized via an interactive
input form (`rating-refresh-input-20260728.html`, star+comment prefilled,
JSON paste-back — workflow he wants reused; see machine-local memory
`media-rating-refresh-workflow`). Result: **101 manual-source records**
upserted (source `manual` outranks douban in resolved view; douban rows
untouched), work **#5956 守护解放西5** created (douban:37018209,
NeoDB-verified), stale show-level manual row on #4357 Slow Horses deleted
(superseded by per-season records), **#663 茶杯头大冒险 第三季**
reclassified film→tv/S3. Notable rating regressions all explicitly
confirmed by Anping in the form (守护解放西 S3/S4→★2, Capture S2→★4,
Killing Eve S2→★4, Friends S6→★4, Party Hard→★4.5, 白宫杀人事件→★4.5).
Logged in sync_runs (source manual). Backups:
`media-pre-manual-refresh-20260728-202715.db` (session start),
`media-pre-manual-write-20260728-225653.db` (immediately pre-write).
The two `rating-refresh-*.html` files were session scaffolding (parked in
`attic/_trash-safe-to-delete/` 2026-07-29). Dumps + library.html rebuilt.
Blog follow-up: `exports/library-resolved-20260728.json` (2,451 rows,
101 manual) generated for the blog's /library page (repo now at
`~/Blog/W-Log`, snapshot builder `scripts/library/build-snapshot.mjs`
reads stale Emrick-clean — see douban-export/BLOG-HANDOFF.md addendum);
blog-side session spawned to consume it.

## Last refresh (2026-07-28 evening)

Fresh Douban walk +9 new TV marks (Clarkson's Farm S1–S5, Slow Horses
S1–S2, 守护解放西 4+6; all watched, rated, most commented — Anping
confirmed expected). No removals/status/rating changes elsewhere.
Ingested via `mediahub.py ingest-douban` + `load_clean.py`; dumps +
library.html rebuilt. Pre-refresh backup:
`backups/media-pre-douban-refresh-20260728-192823.db`.

**Incident:** Douban's anonymous mobile API randomly dropped rows from the
BOOK lists (212/280, then 256/280 on re-walk; movies/music/games stable).
Fixed by unioning fresh walks with `Emrick/_archive-20260727/`. Full gotcha
+ procedure now in RUNBOOK.md §Refresh gotchas. NOTE: `Emrick/*.csv` are
from the fresh walk only (books short); the unioned `*.jsonl` are the
authoritative snapshot.

## Taste report (2026-07-28 late, read-only session)

`analysis/taste_report_2026-07-28.md` — first applied product of TASTE.md:
him-vs-crowd deltas, pre-filter hit rates, hidden white/anti-whitelists,
8 verified-absent blind-spot recs. New raw snapshot:
`sources/raw/tmdb/tmdb_ratings_2026-07-28.jsonl` (TMDB vote_average for the
rated film/TV set, 1,263 ok / 1 stale-id 404). No media.db writes.

## Open threads (owner in brackets)

1. **[AUTOMATED — no human action] spotify_music.py rerun — STILL OPEN,
   partially repaired.** Background: the 2026-07-28 `clean_music.py` rebuild
   reset the spotify anchors to the 59 NeoDB-linked ones (any-anchor
   579→551), because `spotify_album` lives only in the derived
   music_clean.json.
   **2026-07-29 ~16:02–16:17 PT: two scheduled tasks raced and collided.**
   `spotify-music-name-search-retry` (16:00) and `spotify-anchor-repair`
   (16:15) both ran spotify_music.py concurrently. The app quota is shared,
   so the doubled request rate earned a **new, much longer ban:
   Retry-After 85465s ≈ 23h44m, i.e. lifts ~2026-07-30 16:01 PT.** The
   retry run reached row 350 and matched 128 ids (22 upc + 106 name,
   with_spotify 187 / any-anchor 577); the repair run reached row ~31 with
   13 name hits and — writing one second later — **overwrote all 128.**
   Neither JSON nor CSV retained them; the script only writes at the end, so
   the repair task's "stop if with_spotify ≥ 100" guard saw the stale 59.
   **Current state: with_spotify 72, any-anchor 551.** library.html rebuilt
   against it.
   **Hardening applied to `spotify_music.py` (2026-07-29, tested):** a
   pid-checked lockfile (`.spotify_music.lock`) makes a second concurrent
   pass exit immediately instead of competing; the decision log is now
   **cumulative** (prior entries merge, so partial progress accumulates
   across runs); `--from-log` replays logged ids with **zero API calls**
   (the durable fix for the clean_music.py wipe — no re-matching needed);
   `--skip-tried` skips rows already attempted; `--pace` defaults to 1.6s
   (1.0s got the app banned twice).
   **Next:** one-time task `spotify-music-continuation` fires 2026-07-30
   17:00 PT — probe, then `--skip-tried` resume, then the cover upgrade
   (`spotify_music_covers.py`, new), then build_library.py. 564 rows never
   attempted; 18 attempted-and-missed. Do NOT create a second task for this
   — the lock will now block the loser, but a race still wastes quota.
2. **[music-lane session fe262fbc] music → media.db load** reserved:
   fetch_tracks.py track lists + review of the ~33 name+artist matches at
   music_clean load time. Do not preempt from other sessions.
3. **[music-lane session] load_spotify.py** remaining ~389 album
   hydrations (idempotent rerun). Blocked until the ban above lifts
   (~2026-07-30 16:01 PT) — same shared client-creds quota, so do not run it
   alongside a spotify_music.py pass.
4. **[Anping] Letterboxd fresh-account import**: seed CSVs ready in
   `letterboxd-import/` (watched 1,184 / reviews variant / watchlist 76).
   Waiting for him to create the account; agent then drives the upload via
   browser. 30 verdict-kept rows stay undated unless his pre-deletion
   export ZIP surfaces.
5. ~~**[Anping → agent] Spotify Extended Streaming History**~~ RESOLVED
   2026-07-29: export landed, ingested, schema decided, 98,754 plays loaded
   (see section above). Remaining tail: ISRC hydration (running) + dumps
   rebuild.
6. **[ops] PSN npsso** expires ~2026-09 (set 2026-07-27).

## Concurrency rules (multiple sessions run in parallel on this Mac)

- Before any media.db write: `lsof media-hub/media.db*` must be empty of
  other writers; take a dated backup for multi-step passes.
- Builders (build_library_db, build_db_review, review pages): take ALL DB
  reads in one BEGIN…COMMIT snapshot BEFORE network I/O.
- Douban walk, NeoDB cleaning, cover ladders: safe to re-run any time
  (checkpointed, skip-existing).
- **Shared external quotas are a writer lane too.** The Spotify
  client-credentials app is one bucket for `spotify_music.py`,
  `spotify_music_covers.py` and `load_spotify.py`: two concurrent passes
  don't just clobber each other's output file, they get the whole app banned
  for ~24h (happened 2026-07-28 and again 2026-07-29). Run one at a time —
  spotify_music.py now enforces this with a lockfile. Same caution for any
  new Spotify consumer.
- Derived files are not durable storage. `music_clean.json` is regenerated
  by clean_music.py, which silently drops every enrichment written into it
  (spotify_album, 2026-07-28). Enrichment passes must keep a cumulative log
  they can replay offline (`spotify_music.py --from-log`).
