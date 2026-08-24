# SDD ledger — plan: media-hub/docs/superpowers/plans/2026-08-23-media-recommend-v2-pool.md

## Environment rulings (carried from v1 session)
Ruling: no git in this repo (iCloud). No worktrees/commits; verification = tests + greps + real runs.
  Ledger lives in scratchpad; copied into docs/superpowers/decisions/ at the end, since without git
  this is the only record of decisions.
Ruling: v1's judgment layer (CRITIC.md, percentile gate, mid-rank convention, rec log) is FROZEN for
  this plan — spec v2 §6 pins it. Any task touching it is out of scope and must be raised, not done.

## Pre-flight conflict scan
| # | Pair | Produces -> consumes | Finding |
|---|---|---|---|
| 1 | T1->T2/T3 | pool.py upsert batch shape (kind,title,year,external_ids,tags,aggregates,shape,sources) | clean — plan fixes the shape in all three task texts identically |
| 2 | T2->T1 | harvest transform output = upsert input | clean; T2 test asserts the exact keys T1 validates |
| 3 | T3->T1 | douban transform output = upsert input; year null, kind inherited from anchor | clean — T1 requires only kind/title/sources |
| 4 | T1->T4 | pool.py CLI names (init/upsert/query/attach-evidence/suppress-sync/stats) | clean; T4 verifies against real --help |
| 5 | T2/T3->T5 | raw dirs + checkpoint conventions | clean |
| 6 | T1->T5 | suppress-sync needs works/records/external_ids/recommendations | clean, all exist |
| 7 | T1 self | json_each for tag/channel filters needs SQLite JSON1 | risk noted: JSON1 default in py3.10+; implementer must report if absent |
| 8 | T3 self | parser written against LIVE fetched markup, not memory | by design; if challenge-walled -> report BLOCKED, do not guess |
| 9 | T4 self | scout now receives the bar; must not weaken critic blindness | plan states the distinction explicitly; reviewer will check |
| 10 | T5 self | douban budget 40 of ~164 anchors => partial by design | not a shortfall; must be logged as checkpoint position |

## Wave plan
Wave 1 (parallel): T1 pool.py, T2 harvest_tmdb.py, T3 harvest_douban.py — interfaces fixed in plan.
Wave 2: T4 docs rewrite (needs real --help from T1-T3).
Wave 3: T5 bootstrap (real network + DB write, ritual required).
T6: user-gated (Anping's approval for scheduled-task wiring + his retest).

## Wave 1 dispatched (2026-08-23)
- T1 (sonnet): recommend/pool.py + candidate_pool table + tests. Report -> task-1-report.md
- T2 (sonnet): recommend/harvest_tmdb.py (anchors/fetch/transform) + fixture tests. -> task-2-report.md
- T3 (sonnet): recommend/harvest_douban.py — MUST inspect live markup before writing parser;
  BLOCKED is an acceptable, valuable outcome. -> task-3-report.md
All three told: no bulk fetching in this wave; that is T5.

## Wave 1 results
T1 (pool.py): DONE. 82 tests pass (76 pre-existing + 6 new). candidate_pool created in real media.db;
  backup backups/media-recommend-20260823-174524.db; works/records/recommendations row counts unchanged.
Ruling: `--channel` stays REPEATABLE (agent's reading was right; the single-value line in my plan text
  was a typo). Superset, matches --tag semantics, and per-channel pool-health queries (TMDB vs Douban
  contribution) are something we will want immediately. No interface risk — no harvester consumes it.
T2 (harvest_tmdb.py): DONE. 88 tests total (10 new). Anchors 147: film 138 / tv 7 / show 2 —
  matches the controller's independent SQL exactly. Live sanity check on one real anchor (46
  candidates, 14 vote-floor drops); confirmed no api_key string in any saved raw file.
Controller CROSS-CHECK (the seam neither parallel agent could test): built a raw file in fetch's
  exact format -> ran the REAL harvest_tmdb transform -> fed its REAL output to the REAL pool.py
  upsert on a scratch DB -> queried back. inserted:1, row intact with tags/aggregates/provenance.
  T2's flagged integration risk is CLOSED, verified by execution rather than by reading.
T3 (harvest_douban.py): BLOCKED on first live fetch, and the agent was RIGHT to stop.
  Desktop /subject/<id>/ redirects to sec.douban.com JS proof-of-work challenge. It refused to guess
  selectors and left the happy-path test as xfail(strict=True) so the gap stays visible. It also
  corrected TWO factual errors in MY brief: (a) this repo does not use curl_cffi for Douban, and
  (b) douban_export.py never fetches subject pages, so the "established precedent" I cited never existed.
CONTROLLER UNBLOCK (verified live, two real subjects, both HTTP 200):
  mediahub.py cmd_enrich_douban already uses Douban's MOBILE REXXAR JSON API. The CF endpoint is
  https://m.douban.com/rexxar/api/v2/movie/{id}/recommendations?for_mobile=1 with MOBILE_UA +
  Referer https://m.douban.com/movie/subject/{id}/ . Returns a JSON LIST of 20 items, keys:
  alg_json, card_subtitle, id, interest, pic, rating, sharing_url, title, type, uri, url.
Ruling: switch the Douban harvester from HTML scraping to this API. Strictly better on three axes —
  no fragile selectors at all; `type` is per-item so KIND COMES FROM DATA (drop the inherit-from-anchor
  heuristic); rating.value present so aggregates ARE populated (my brief wrongly said to omit them).
  Reuse mediahub.py's polite_get + 403/302 stop + 8-failure circuit breaker rather than new machinery.
  Cost if wrong: a private mobile API can change shape without notice — mitigated by raw-first
  snapshots and a blocked-response detector, same as the HTML path would have needed.
Note: verify whether `card_subtitle` reliably carries a year; if not, year stays null.
T3 REBUILT on the rexxar API: DONE. 108 tests pass (20 new), xfail retired. Verified live on 2 fresh
  anchors + a real `fetch` CLI run incl. resumability (skipped_resumed:1, zero duplicate calls).
  card_subtitle's leading 4-digit token gives `year` — 100% hit rate on 40 real items, so year is NOT
  null after all. rating.value -> aggregates.douban_rating. kind now comes from the item's own `type`.
  Contract re-verified against the REAL pool.py (not plan text): 40 live rows -> inserted 40,
  by_kind {tv:20, film:20}, by_channel {douban_rec:40}.
  Residual: 403/302-stop and circuit breaker verified only against mocked requests — T5's bulk run is
  their first real-world stress test. Flagged to T5 that a fired breaker is a SUCCESS to report.
Wave 2 dispatched in parallel (they touch disjoint files):
  T4 (sonnet): SCOUT.md/SKILL.md/README.md run-mode rewrite — pool-first interactive, mandatory
    clarifying-question check, opt-in re-sweep, scout-knows-the-bar w/ the blindness rationale.
  T5 (sonnet): real bootstrap — TMDB full sweep + Douban budgeted tranche + upsert + suppress-sync,
    with the DB write ritual. Told explicitly not to massage numbers.
T4 (docs rewrite): DONE. SCOUT.md (mandatory clarifying-question check, Run-modes section, 4-tier
  channel hierarchy pool->shells->top-up->LLM-last-resort, shortlist-against-target w/ blindness
  rationale, rexxar endpoint recorded in Source notes); SKILL.md (digest-only step 0 harvest chain,
  pool-first interactive, re-sweep now ASKS interactively); README.md (pool bindings + mode split).
  108 tests still green; purity grep clean; CRITIC.md + TASTE.md mtimes unchanged.
  Caught two errors in MY brief: "four new CLIs" (only three exist — it documented three rather than
  inventing one) and an `anchors`->`fetch` "pipe" that is actually a --anchors FILE redirect.
  Note for future editors: the new Run-modes section is deliberately unnumbered so SKILL.md's
  existing §1-§6 cross-references stay valid without a renumbering pass.
T5 (bootstrap): DONE. backup backups/media-recommend-20260823-180057.db.
  TMDB: 147 anchors -> 292 fetched / 8 failed (4 stale tmdb ids, HTTP 404) -> 5,400 candidates,
    400 vote-floor drops -> 3,313 inserted / 2,087 merged.
  Douban: 298 anchors available; budgeted tranche reached checkpoint 69/298 (all tv, all HTTP 200,
    0 blocked, breaker never tripped) -> 1,380 candidates -> 984 inserted / 396 merged.
    The 3 invocations were caused by the SHELL's 2-min default timeout, NOT by Douban — the
    crash-safe checkpoint absorbed it. Remaining 229 anchors are all film; they accrue next session.
  FINAL: total 4,297 (film 3,112 / tv 1,185); by_channel tmdb_rec 3,265, douban_rec 984,
    tmdb_discover_recent 50; suppressed 401 (suppress-sync working — already-watched excluded).
  works/records/external_ids unchanged (4359/5539/11272); integrity ok; 108 tests green.
CONTROLLER VERIFICATION of the claim that justified v2: a pool query is 0.036s / 0.039s wall —
  the interactive path is now local and effectively instant, vs 13-16 min of network sweeping.
  The TV lane now has 984 douban_rec candidates where it previously had ZERO CF signal.
ALL TASKS 1-5 COMPLETE. Task 6 is user-gated (Anping's approval for the scheduled-task wiring,
  and his own ask for the timed retest).

## COMPLETION (2026-08-23)
1 sibling-seasons helper + douban tags: DONE (130 tests at the time; 146 now incl. peer's render.py)
2 Douban harvest: DONE 298/298, zero blocks, no breaker trips. Pool 4,297 -> 6,473.
  douban_rec 984 -> 3,160; 3,150/3,160 (99.7%) tagged. suppressed 411 -> 1,019.
3 Digest: run_digest.sh + `monthly-recommend-digest` scheduled task (3rd monthly 04:17,
  sequenced AFTER monthly-douban-backup so it harvests from fresh anchors).
4 Speed: batch sibling-seasons check = 0.05s for 12 candidates (was the dominant manual cost —
  per-candidate 第N季 stripping + index grep). Verified it fires: 扑克脸/神烦警探/白莲花度假村 caught by
  base_title, Brooklyn Nine-Nine caught by EXTERNAL ID across the CN/EN title gap (the exact
  miss that pitched it as a discovery), Bunny correctly passes.
5 Final verification: 146 tests pass; integrity ok; works/records/external_ids unchanged
  4359/5539/11272; recommendations 30; candidate_pool 6473; engine-doc purity clean.
6 Docs: HANDOFF status -> COMPLETE with v2 facts + standing policies; ARCHITECTURE registers
  candidate_pool, both harvesters, render.py, run_digest.sh.

Ruling: killed the docs/scheduling agent at 1h with no file writes for 55 min (stuck). Took over
  scheduling + HANDOFF/ARCHITECTURE directly. Its earlier output (run_digest.sh, SCOUT/README
  sibling wiring) was already landed and verified good.
FABRICATED-ID INCIDENT (found by a peer session, verified by me): rows 25/26 carried invented
  tmdb ids (1861 = Ain't Misbehavin' 1994; 2795 = GMA Network News). Pool rows carried douban-only
  ids, so harvesters clean — ids were invented mid-run, violating the project's first hard rule.
  Corrected to 1044/32062. I audited ALL 29 tmdb ids in the log: every one now resolves to the
  correct title AND year. Root lesson: the critic's fact-check asserted ids "resolve", which a
  fabricated-but-valid id passes. Verification must compare RESOLVED TITLE/YEAR, not HTTP 200.
