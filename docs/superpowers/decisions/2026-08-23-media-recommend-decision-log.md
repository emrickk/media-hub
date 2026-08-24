# SDD ledger — plan: media-hub/docs/superpowers/plans/2026-08-23-media-recommend.md

## Environment rulings (pre-flight)
Ruling: No git in `AI Space` (iCloud store; plan Global Constraints says so explicitly).
  Adaptation: no worktree, no commits, no git-diff review packages. Implementers verify
  via tests + file listings; reviewers get explicit file paths to read. Ledger lives in
  the session scratchpad workspace, not `.superpowers/` in the repo.
  Cost if wrong: no rollback-by-commit; mitigated by media.db backups + additive-only edits.
Ruling: Task 6 (probe) and Task 3 both touch SCOUT.md. Probe agent writes findings to a
  scratchpad file ONLY; the controller appends them to SCOUT.md after Task 3 lands.
  Cost if wrong: none material — one extra append step.
Ruling: Critic output has kill_rule + kill_evidence; reclog DDL has one kill_reason column.
  Mapping: kill_reason = "<kill_rule>: <kill_evidence first sentence>", full critic JSON
  preserved in the dossier column. Recorded so Task 5's implementer does not invent a schema.
  Cost if wrong: analytics on kill rules need a string prefix parse rather than a column.

## Pre-flight conflict scan
| # | Pair / task | Produces → consumes | Finding |
|---|---|---|---|
| 1 | T1→T2 | reclog `init` + recommendations DDL → history.py rec_log query (id,title,year,kind,external_ids,critic_killed,verdict) | clean — all columns in DDL |
| 2 | T1→T5 | reclog CLI (log/verdict/check/pending/stats) → SKILL.md steps 5-6 | clean — signatures match |
| 3 | T2→T5 | history.py `snapshot --out` → SKILL.md step 1 | clean |
| 4 | T3→T4 | dossier schema (history_analogues, ask_fit, evidence, confidence, flags) → CRITIC.md reads | clean — all present in SCOUT §5 |
| 5 | T4→T1 | critic predicted_stars/predicted_confidence → DDL columns | clean; kill_rule/kill_evidence → kill_reason needs mapping (ruled above) |
| 6 | T3↔T6 | both write SCOUT.md (create vs append Source notes) | CONFLICT — ruled above (probe writes to scratchpad, controller appends) |
| 7 | T5→T3/T4 | README/SKILL relative paths → files created by T3/T4 | clean — verified in T5 step 3 |
| 8 | T1 self | test fixture tables (works/records) vs DDL FK works(id); argparse choices reject bad verdict | clean |
| 9 | T2 self | fixture kinds/statuses vs rated/wishlist/shells queries; original_title selected and present | clean |
| 10 | T1 self | `check` uses json_extract → requires SQLite JSON1 | risk noted, not a conflict: JSON1 is default in Python 3.10+ sqlite3; implementer must report if unavailable |

## Execution waves (fan-out)
Wave 1 (parallel): A = Tasks 1+2 (python helpers, dependent chain, one agent);
                   B = Tasks 3+4 (engine docs); C = Task 6 (probe, findings to scratchpad).
Wave 2: Task 5 (skill + README) + controller appends probe findings to SCOUT.md.
Task 7: user-gated, controller runs with Anping.

## Wave 1 dispatched (2026-08-23)
- Agent A (sonnet/implementer): Tasks 1+2 — reclog.py, history.py, media.db init, ARCHITECTURE/STATE edits. Report → task-A-report.md
- Agent B (sonnet/implementer): Tasks 3+4 — SCOUT.md, CRITIC.md, DIGEST-INTENT.md, logs/. Report → task-B-report.md
- Agent C (sonnet/implementer): Task 6 — source-surface probe; findings → source-notes.md (NOT SCOUT.md, per ruling). Report → task-C-report.md

## Wave 1 results
- Agent B (Tasks 3+4): DONE_WITH_CONCERNS. Created SCOUT.md (98L), CRITIC.md (83L), DIGEST-INTENT.md (5L), logs/.gitkeep.
  Purity greps: zero matches on both engine docs. Concern raised = the kill_rule vs kill_reason mismatch,
  which is already covered by the pre-flight Ruling (bridge in Task 5 SKILL.md, engine doc stays verbatim).
  Task review dispatched (sonnet) with that item explicitly marked pre-ruled.
- Agent A (Tasks 1+2): DONE_WITH_CONCERNS. reclog.py + history.py + tests (9/9 pass);
  media.db recommendations table created; backup backups/media-recommend-init-20260823-142104.db.
  Two concerns investigated by controller against real data — both real plan defects:

Ruling: history.py `rated` must dedupe to one row per work_id. Evidence: 2,936 rows → 1,702 distinct
  works (1,087 works have 2 rows, 69 have 3, 3 have 4) and 31 works carry CONFLICTING ratings across
  sources. The critic reasons by analogy citing "the user gave X n★"; duplicate/contradictory rows
  corrupt that reasoning and waste its context. Precedence for stars: manual > douban > letterboxd >
  plex (manual = deliberate hand entry incl. taste-test corrections; douban = only bulk source with
  review text, 1,559 ratings/520 reviews; letterboxd 1,068 ratings no reviews; plex only 9 ratings).
  Review text: highest-precedence non-empty. Keep `sources` list + `rating_variants` when sources
  disagree, so disagreement is visible rather than silently resolved.
  Cost if wrong: a per-work rating could favour a stale source over a newer one; visible in
  rating_variants and fixable by flipping precedence in one function.

Ruling: history.py `shells` query is structurally broken as specified — it JOINs records, but true
  shells have ZERO records rows, so it can only ever return 0 (confirmed: returns 0; 222 in-scope
  works have no records at all — 神探夏洛克, 白莲花度假村, 杀死伊芙 …). Fix: drop the JOIN, select
  works with no record in (watched, watching, wishlist). This preserves the plan's stated intent
  and also covers owned-only works (0 today, but steam/plex can create them).
  Cost if wrong: none identified; the plan's WHERE clause is unchanged, only the JOIN removed.
  Value: shells are library-present-but-unwatched titles — available right now and already
  deliberately acquired; TASTE.md notes current viewing runs through Plex, so this is a live signal.

Note (no action): pytest needed --break-system-packages (Homebrew PEP 668) — setup only, not code.

## Task 3+4 review: spec OK, quality approved
Byte-identical fidelity to brief; purity greps clean; dossier schema ↔ critic reads coherent.
Two findings, both defects in MY plan text (not implementer error):
Ruling: `wishlist-note` appears in prose where a kill_rule value is expected, but it is an `outcome`
  value; enum divergence in a runtime contract = run-to-run divergence. Decided: wishlist match ⇒
  outcome="wishlist-note", kill_rule=null, stated in BOTH the checklist and the schema section.
  Cost if wrong: none material; it only narrows an ambiguity that had no intended second reading.
Ruling: prose `SEND-BACK`/`KILL` must name the literal enum values (`sendback`/`kill`) it expects the
  model to emit, rather than leaving the casing transform to inference.
  Cost if wrong: none; emphasis retained, literals made explicit.
- Fix round 1/5 dispatched to Agent B (CRITIC.md precision) and Agent A (rated dedup + shells), in parallel.

## Task 6 (probe) complete — findings are substantive
Worked: TMDB /recommendations (0% junk on anchor), TMDB /discover via GENRE COMBINATION,
  NeoDB search (literal, identity-only), Douban new_search_subjects (1 call then rate-limited),
  Letterboxd reviews (needs full header set).
Failed/weak: TMDB /similar (60-70% junk), single free-text TMDB keyword (silently returns 0 —
  "mind-bending" keyword is unpopulated), Douban /tag/<term> (404 — URL structure RETIRED, not a
  block), Douban /subject/<id>/comments (JS challenge wall via urllib), RT (not probed).

Ruling: accept the probe's channel-mix recommendation into SCOUT.md Source notes (merged by Task 5
  agent). Effect on spec principle 5: review mining stays a first-class EVALUATION channel but is
  demoted from a default DISCOVERY channel (0 neighbor-title mentions found in a 13-review sample).
  Cost if wrong: we under-use a discovery channel; recoverable — the funnel logs will show if
  candidate pools are thin, and the channel can be re-promoted.
Ruling: the probe tested RAW HTTP only, but at runtime the scout is a Claude session with
  WebFetch/WebSearch, and this project already defeats Douban's wall with curl-cffi (RUNBOOK).
  Concluding "Douban reviews unobtainable" on urllib evidence alone would wrongly strip Chinese
  titles of review evidence — which the critic requires and the Chinese-first hard rule protects.
  Dispatched a focused addendum probe (curl-cffi + WebFetch + RT baseline + WebSearch fallback).
  Cost if wrong: one extra probe agent; the alternative was a silent capability loss for
  Chinese-language titles.
- Task 5 (SKILL.md + README.md + merge of source notes into SCOUT.md) dispatched to a fresh agent.

Task 3+4: fix round 1/5 (2 addressed, 0 open — wishlist-note/kill_rule pairing; prose enum literals;
  implementer extended fix uniformly to KILL in items 1-5). Re-review: both ADDRESSED, enum
  cross-check clean (no crossing), fences balanced, JSON fields intact, purity grep clean.
Task 3+4: complete (SCOUT.md, CRITIC.md 92L, DIGEST-INTENT.md, logs/ — review clean)
Task 1+2: fix round 1/5 (2 addressed, 0 open — rated dedup + shells). 14/14 tests pass.
  Smoke run rated=1702 wishlist=91 shells=222 rec_log=0; 31 works carry rating_variants and
  1,159 have multiple sources — both match the controller's independently-derived numbers exactly.
  Full task review dispatched (covers original + fix as one unit).
Task 5: implemented (SKILL.md 34L, README.md 22L, SCOUT.md 98→137L with probe notes merged).
  All 11 README relative paths resolve; SCOUT diff = single hunk at the placeholder line.
  Task review dispatched (focus: CLI-match against real argparse, kill_rule→kill_reason bridge,
  blindness-contract agreement with CRITIC.md, cwd coherence).
In flight: Task 1+2 review, Task 5 review, review-evidence addendum probe.

## Task 1+2 review: spec OK (as amended), quality approved. 14/14 tests verified by reviewer.
Findings → fix round 2/5 dispatched:
Ruling: cmd_stats double-counts sealed_vs_actual (same defect Ruling 1 fixed in history.py, left in
  reclog.py) — it feeds the prediction-accuracy metric the design judges itself by, so a silent skew
  there is worse than a wrong pick. Fix with the SAME precedence helper, shared not duplicated.
  Cost if wrong: accuracy stats mis-weight multi-source works; detectable by re-running stats.
Ruling: STATE.md must be refreshed at end of round (project rule; next agent reads it cold).
Ruling: `check --title` without --year silently no-ops. Requiring year is DELIBERATE (cross-year title
  matching is the identity error the hard rules guard against) but must fail loudly, not silently.
  Cost if wrong: none; strictly more informative than the silent path.
Ruling (confirm, no change): stars and review are chosen INDEPENDENTLY by precedence — the top rated
  source often has no review text, and dropping a real review to keep one source pure would discard
  the richest evidence in the history.
Parked: same-source duplicate-row ordering in _rated_entries — unreachable under current schema.

## Task 5 review: spec OK-with-gaps, quality approved (defects are in MY plan text, not the work)
Ruling: SKILL.md step 5 never defined the batch-row contract; `intention` is REQUIRED by reclog but
  sourced nowhere in the critic output or dossier → guaranteed KeyError crash at the only write step.
  Step 5 now specifies the full per-row contract incl. carrying the verbatim ask forward.
  Cost if wrong: a field name drifts from the DDL; caught immediately by the first real run.
Ruling: critic `outcome` was never mapped to `critic_killed` (defaults 0) → every kill would log as
  pitched, corrupting `pending` AND the hit-rate/accuracy math. Defined `critic_killed = 1 means the
  candidate did not reach the user as a pitch`; kill→1, sendback→1 (prefixed), wishlist-note→1
  (prefixed, since a note is not a pitch and must not sit in the pitched denominator), survive→0.
  Cost if wrong: wishlist-notes are excluded from hit-rate; defensible either way, prefix keeps them
  recoverable by query.
Ruling: `sendback` had no defined handling — one dossier rebuild, else log with a `sendback:` prefix.
  Cap of one rebuild mirrors the existing one-resweep cap.
Ruling: SKILL.md (cwd=media-hub root) and README.md (cwd=recommend/) disagreed, so the write ritual's
  `../media.db` would resolve outside the repo and fail. Single convention = media-hub root.
  Cost if wrong: paths must be rewritten once more if a different cwd is later preferred.
Ruling: reclog cmd_log must validate the whole batch and fail with row index + field names,
  all-or-nothing, instead of a bare KeyError mid-write. Folded into Agent A's fix round 2.

## Review-evidence probe addendum: BAD NEWS, escalated
curl-cffi (project's own sanctioned pattern) → Douban still JS-challenged. WebFetch → Douban 302 to
challenge, Letterboxd 403, RT 200-but-empty JS shell, IMDb/RogerEbert 403. Wikipedia fine, so it is a
review-site block, not a WebFetch outage. WebSearch: partial English quotes, Chinese thematic only.
This threatens spec principle 5 (reviews as first-class evidence) AND the critic's evidence
requirement — with no evidence channel the critic kills everything.
Ruling: do not accept that conclusion before probing the API surfaces nobody tested (TMDB
  /reviews endpoint, NeoDB per-item reviews/comments). Probe dispatched. If APIs also fail, the
  evidence contract in SCOUT.md/CRITIC.md must be amended to a graded hierarchy where "no verbatim
  quote obtainable" is a documented condition, not an automatic kill — mirroring the project's
  existing Chinese-first "absence is a documented negative" rule.

## API evidence probe: the block is SOLVED — evidence mechanism survives
TMDB /reviews: 100% coverage on English titles (real substantive text); ~0% genuine Chinese-language
  criticism (the 2/5 non-empty Chinese titles carried English reviews by Western viewers).
NeoDB /api/item/{uuid}/posts/?type=review -> /api/review/{uuid}: anonymous, full-length genuine
  Chinese review essays (274–5,794 chars), 80% coverage on Chinese titles. THIS is the Chinese channel.
WebSearch snippets: attributable characterization, no fetch, not blocked — Tier 2 fallback.
Metadata (vote_average/keywords/tags): present 6/6, but a confidence floor, never evidence.

Ruling: encode a graded EVIDENCE HIERARCHY rather than a binary quote requirement.
  Tier 1 verbatim (TMDB reviews EN / NeoDB review chain ZH) > Tier 2 attributable characterization
  (WebSearch) > Tier 3 metadata floor. Dossiers declare `evidence_tier`; the critic KILLS an
  evidence-free case as before, but a case resting honestly on Tier 2/3 and LABELLED as such is not
  killed — it caps predicted_confidence (Tier2→medium, Tier3→low) and names the thinness in
  residual_risks. Principle stated in the doc: unobtainable evidence is a documented condition, not a
  defect of the candidate — mirroring the project's existing "absence from a foreign DB is a
  documented negative" rule. Without this the critic would systematically punish titles whose reviews
  merely happen to be unreachable, which falls hardest on Chinese-language titles — a direct conflict
  with the Chinese-first hard rule.
  Cost if wrong: some low-confidence candidates reach the pitch that a stricter gate would have cut;
  visible to the user because confidence and residual risks are shown per candidate.
  Dispatched to Agent B as fix round 2 (also appends both probe findings files into SCOUT.md).

Task 5: fix round 1/5 (4 addressed — batch-row contract incl. intention, outcome->critic_killed,
  sendback handling, cwd convention). SKILL.md 34->75L, README.md 22->27L; 11/11 paths resolve.
Ruling: dossier column uses explicit `{"scout": {...}, "critic": {...}}` nesting (agent-raised
  collision on title/year). This column IS the audit trail the user intends to review, so provenance
  inside the record is the point; a flat merge would silently overwrite. Dispatched as fix round 2.
Task 5: fix round 2/5 applied (dossier nested as {"scout","critic"}; row-column bullets tightened).
  SKILL.md 84L. Re-review DEFERRED deliberately: it must cross-check reclog.py (Agent A round 2 in
  flight) and CRITIC.md (Agent B round 2 in flight). Reviewing against mid-edit files would produce
  findings about states that no longer exist. Will run one consolidated re-review once both land.
Task 1+2: fix round 2/5 (4 addressed, 0 open — stats double-count via new shared precedence.py,
  STATE.md refreshed, check --title fails loudly, cmd_log whole-batch validation w/ rollback).
  18/18 tests. Agent empirically ran the OLD buggy stats query against the new fixture (2 rows vs 1)
  to prove the regression guard actually guards — verification by evidence, not assertion.
  New file: recommend/precedence.py shared by history.py + reclog.py.
Task 3+4: fix round 2/5 (4 edits addressed — probe notes appended, tiered evidence guidance,
  evidence_tier in dossier schema, graded critic rule). SCOUT.md 137->298L, CRITIC.md 91->115L.
  Purity greps clean incl. new content; fences balanced; all enum literals unchanged.
ALL IMPLEMENTATION COMPLETE (Tasks 1-6). Task 7 is user-gated (needs a real ask from Anping).
Dispatching ONE consolidated final whole-branch review (opus) that also serves as the deferred
  re-review for Task 5 rounds 1-2, Task 1+2 round 2, Task 3+4 round 2 — reviewing the integrated
  system at rest rather than three mid-flight slices.

## FINAL REVIEW (opus): approve with 1 Critical + 11 Important. Rulings below; ONE fix wave dispatched.
Ruling C1 (snap.json unreadable — 793KB/37,930 lines; Read caps at 2,000 = 5% recency slice, silently):
  Fix by giving the critic QUERY ACCESS rather than a scout-curated subset. A scout-selected subset
  would let the searching party choose which history the judge sees — that quietly destroys the
  blindness the whole design rests on. Instead: `history.py index` (one compact line per work, ~1,702
  lines, fits one Read, full coverage, no silent truncation) + `history.py lookup` (full detail incl.
  review text, by work-id/title/creator). Critic drives its own retrieval; blindness preserved.
  Cost if wrong: two more subcommands to maintain.
Ruling I2 (thin evidence still dies at check 3 before the amendment protects it at check 5): thin
  evidence must WIDEN THE CONFIDENCE BAND, never lower the central estimate. Without this the
  evidence-hierarchy amendment is defeated by the check that fires first, and it lands hardest on
  Chinese-language titles (TMDB genuine ZH review coverage ~0%) — the exact discrimination the
  amendment exists to prevent, and a conflict with the Chinese-first hard rule.
Ruling I1: shells (222 works) computed then used by nobody. Wire into SCOUT §2 as a first-class
  retrieval channel — already-owned, already-chosen, unwatched; TASTE.md says current viewing runs
  through Plex, so it is the freshest signal in the system.
Ruling I3: evidence_tier "highest rank" is ambiguous (tier 1 = best = numerically lowest) and it
  drives the confidence cap → say "best (numerically lowest) tier any entry reached".
Ruling I4: appended probe notes contradict SCOUT's own normative §3c and would self-downgrade every
  English title to Tier 2. Mark superseded; keep measurements, drop stale recommendations.
Ruling I5: critic↔dossier join on a title STRING breaks on any rendering/translation difference
  (漫长的季节 vs The Long Season) → add dossier_index to the critic's per-candidate object.
Ruling I6: re-sweep/sendback can log a candidate twice, inflating the pitched denominator and
  corrupting the accuracy metric → exactly one row per candidate, carrying its FINAL outcome.
Ruling I7: no guard where the two star scales meet → validate predicted_stars in 0.5–5.0 + DDL CHECK.
Ruling I8: critic never receives SCOUT.md, so the Chinese-first "absence is a documented negative"
  rule is invisible to it → restate inside CRITIC.md check 1. Without it a douban-only title is one
  plausible reading from a `fact` kill.
Ruling I9: `confidence` and `flags` are produced for the critic and never read → wire into checks 1/6.
Ruling I10: TASTE.md carries no per-entry confidence grades, so the low-confidence→stated-risk path
  can never fire → README states the profile is prose today and tells the critic how to grade.
Ruling I11: STATE.md/ARCHITECTURE.md record only Tasks 1-2 → a cold-start agent would not learn the
  engine exists. Refresh both to the whole build.
Ruling (correcting my own earlier park): same-source precedence tie IS reachable — UNIQUE(source,
  work_id,status) permits one source to hold both watched and watching for one work, and
  _rated_entries gathers both. My earlier parking reasoning was wrong. Fix deterministically.

## Final fix wave complete: C1 + I1-I11 + 8 minors + reversed park. 51/51 tests (was 18/18).
Index = 1,717 lines / 94KB vs snapshot 39,945 lines / 898KB — one-pass readable, full coverage.
Purity grep zero matches; enums unchanged; commands match argparse; one BEGIN/COMMIT preserved.
Rulings on the agent's four raised concerns:
Ruling: TAKE the shells external_ids fix — we already hold 216 imdb / 160 plex_guid; forcing a
  network re-resolve for ids in the DB is waste AND puts an identity-matching step in the path of
  the channel we just promoted. Stored verified ids != recalled ids, so the hard rule is satisfied.
Ruling: ACCEPT snapshot +13% for `creators` — nothing reads it linearly post-C1; it enables
  lookup --creator, one of the scout's named channels.
Ruling: ACCEPT the END OF INDEX sentinel (agent went beyond brief). It converts a future overrun
  into a loud failure — silent truncation was the actual C1 danger, not size. Revisit ~1,900 works.
Ruling: ACCEPT CRITIC.md naming blocked review sources. Engine purity governs USER-specific facts;
  "Douban is JS-challenged" is infrastructure truth for every user, and the critic needs it because
  it never sees SCOUT.md.
Ruling: ACCEPT `下饭` in SKILL.md frontmatter — purity binds SCOUT/CRITIC; SKILL.md is instance
  layer alongside README.md, and the term does real work in skill triggering.

## Scoped re-review of fix wave: ALL findings ADDRESSED, no new breakage. 53/53 tests.
Controller independently verified the C1 guarantee: index = 1,702 entry lines for 1,702 rated works
(14 header + 1702 + 1 sentinel = 1717). Complete coverage, no silent truncation. Header instructs the
critic to treat a missing END-OF-INDEX marker as proof its read was truncated.
Tasks 1-6 COMPLETE. Task 7 (calibration run) is user-gated — needs a real ask from Anping.
Workspace retained (not deleted) because Task 7 remains.

## TASK 7 — calibration session #1 STARTED (real asks supplied by Anping 2026-08-23)
Ask A: 我最近看了 the office 我觉得好好看，你有没有什么别的推荐？
Ask B: 有什么最近的好看的电影推荐？
NEW TASTE DATA surfaced by ask A: TASTE.md's round-2 blind test recorded 办公室美版 as "想看"
  (not yet watched). He has now WATCHED it and loved it — a real verdict confirming the 尴尬幽默
  case-law entry (designed awkwardness = selling point). media.db has no record of this watch;
  surface to Anping, do NOT invent a star rating.
Architecture note: controller orchestrates so the critic gets REAL blindness (separate fresh agent
  that never sees the scout's transcript), rather than one agent grading its own search.
Scouts A+B dispatched in parallel (read-only; each writes its own funnel log to recommend/logs/).
Critics to be dispatched fresh after dossiers land. DB write (rec log) consolidated into ONE pass
  by the controller afterwards, with the lsof/backup ritual — several peer sessions are live.

## Smoke test (isolated scratch DB): ran end-to-end, real media.db untouched. Defects found:
1. SCOUT.md §2 bans string-matching for the neighborhood pass, but grep-over-index is what's actually
   available — works at small scale, would silently miss non-obvious titles at full scale. NEEDS A
   RULING (the contract asks for semantic relevance; the tooling offers substring).
2. sourcing sources.env errors on the Spotify line (harmless noise).
3. NeoDB /api/item/{uuid} 404s for TV seasons — correct path is category-typed (/api/tv/season/{uuid}).
   UNDOCUMENTED and dangerous: a 404 reads as "no reviews", i.e. a false documented-negative on
   exactly the Chinese-language titles NeoDB exists to serve.
4. NeoDB JSON carries raw control chars — needs json.load(strict=False).
5. NeoDB review endpoint 403s to urllib but 200s to curl (UA gate).
6. lookup --title substring matching yields false positives on short titles — risks wrong dedup.
7. Blindness in the smoke run was simulated (no-subagent constraint), NOT real.
Relayed 3-6 to both live scouts mid-flight.
Cost data: 3-dossier run = ~9.5min / ~45-50 tool calls. Full spec extrapolates to ~35-60min and
150-300 tool calls for scout+critic per ask.
Notable: the smoke critic's reasoning was genuinely case-law-by-analogy — it killed 隐秘的角落 because
its reviews describe an unforeshadowed, coincidence-driven reversal, the same failure that cost
Ozark S2 and Killing Eve S4 two full stars in his own history. That is the mechanism working.

## Calibration run A (The Office follow-ups): scout 95->26->8; critic 8/8 SURVIVED, 0 kills.
FINDING (gate softness): a 100% survival rate on the first real run is either excellent pre-filtering
  by the scout (95->8 with logged reasons) or a soft gate. Flag to Anping as a calibration
  observation — this is exactly what calibration sessions exist to surface. Watch the kill rate
  across runs; if the critic never kills, the blind-gate value is theatre.
FINDING (real contract gap): the enthusiasm threshold (>=4 stars) is recorded in README.md, which the
  critic NEVER receives — its inputs are CRITIC.md + TASTE.md + index + dossiers. The critic inferred
  ~4.0 from TASTE.md's star semantics and said so. It got the right number by reasoning, but the
  number that decides every survive/kill call must not depend on inference.
  Ruling: the threshold must reach the critic explicitly — either stated in the profile document or
  passed in the critic dispatch by SKILL.md. Fix after the calibration run completes.
  Cost if wrong: a future critic infers a different floor and the whole gate shifts silently.

## Calibration run B (recent films): scout 44->27->8; critic 8/8 SURVIVED, 0 kills.
Combined: 16/16 survived across both asks. Kill rate 0% — see gate-softness finding above.
Critic reasoning quality was high and genuinely case-law-based: it cited his own review words
(Tinker Tailor 3★「过誉」as the risk on Black Bag; Top Gun Maverick「飞行场景3星，情怀加1星」to strip the
nostalgia point from F1; 罗小黑战记「加上是国产，满分！」as the sequel anchor). It also refused to let
thin Chinese-title evidence deflate stars, per the I2 amendment — the mechanism worked as designed.
LOGGED: 16 rows to media.db (ids 1-16), backup backups/media-recommend-20260823-154344.db.
  works 4359->4359, records 5539->5539 unchanged; recommendations 0->16. work_id null for all 16
  (clean negative — full external-id sweep found no existing matches). STATE.md updated.
Post-calibration fixes dispatched: (1) threshold must be PASSED to the critic by SKILL.md rather
  than inferred — fixed in the orchestration layer, NOT by editing TASTE.md (profile edits require
  Anping's review first, per spec C1); (2) NeoDB access gotchas written into SCOUT.md Source notes,
  incl. the 404-reads-as-no-reviews trap that would fall hardest on Chinese-language titles;
  (3) §4 stage sizes explicitly scale with pool size.
OPEN for Anping: (a) his The Office rating (media.db has it as wishlist only; will not invent stars);
  (b) verdicts on the 16 pitched rows via `reclog.py verdict --id N --verdict ...`;
  (c) whether the 0% kill rate reflects good scouting or a soft gate — decide after run #2.
Post-calibration fixes DONE (threshold passed not inferred + recorded as structured output fields;
  NeoDB gotchas; §4 pool-proportional stages). 53/53 pass. TASTE.md mtime unchanged (Jul 28).
Ruling: ACCEPT the agent's judgment call to make threshold-inference a STRUCTURED output field
  (pitch_threshold_used/inferred/note) rather than prose — it puts the fact of an inference into the
  audit record, which is exactly what the calibration run showed we could not otherwise see.
ALL TASKS 1-7 COMPLETE.
Ruling: this repo has no git, so this ledger is the ONLY record of the rulings made on Anping's
  behalf. Copying it into docs/ before cleanup — deleting it (as the skill's finish step assumes)
  would destroy the record that git history normally preserves.
