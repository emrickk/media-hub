# 2026-08-23 — 下饭剧+高密度电影 (interactive, pool-first speed test)

**Mode:** interactive. **Budget:** ~10 network calls, ≤5 min wall-clock target.
**Actual:** 8 network calls (5× TMDB `/reviews`, 1× NeoDB catalog search,
2× NeoDB `/posts/?type=review` — parent + season-1 uuid for Poker Face).
**Actual wall-clock:** ~8–9 minutes end to end (session start through
dossier write), i.e. over the ≤5-minute target — see "Speed-test findings"
at the bottom for where the time actually went.

## 0. Setup
- Read `recommend/README.md` and `recommend/SCOUT.md` (full, both files) —
  this alone was a meaningful fraction of wall-clock (SCOUT.md is 643
  lines including a large Source-notes appendix).
- Snapshot/index/distribution were pre-supplied (`snap.json`, `index.txt`,
  `distribution.json` in scratchpad/test1) per the brief — not regenerated.
- Pool stats at session start: `{"total": 4297, "by_kind": {"film": 3112,
  "tv": 1185}, "evidence_cached": 0, "suppressed": 401, "by_channel":
  {"tmdb_discover_recent": 50, "tmdb_rec": 3265, "douban_rec": 984}}`.

## 1. Interpret the ask
Ask (verbatim, DIGEST-INTENT.md default): 下饭剧优先 (low-cognitive-load,
episodic, interruptible, background-viewing series) + 1 high-density film
worth dedicated attention. Recent/newly-acclaimed or classics that
obviously fit and were never watched. Target: 剧 2–3, 电影 1–2, total
small and precise.

**Clarify check (mandatory):** does this ask admit two materially
different readings? **No — not needed.** The ask is explicit and internally
consistent on every axis that would otherwise fork the slate: format
(episodic/interruptible vs. dedicated-attention, stated directly, not
inferred), quantity (剧 2–3, 电影 1–2, stated as a number), and recency
gate (recent-or-classic-that-fits, an inclusive OR, not an either/or that
needs resolving). There is no second reading under which the resulting
candidate set would look materially different — unlike the README's cited
prior failure case ("more shows like X" vs. "other things I'd love"),
nothing here is ambiguous about *what kind* of thing to look for, only
*which specific titles* satisfy an already-clear brief. Confirmed the
orchestrator's own read; not overruled.
`clarify: not needed — ask is specific about format (下饭/interruptible vs
dedicated-attention film) and quantity (2-3 series, 1-2 films); no second
reading changes the candidate set.`

## 2. History work (from index.txt, no network)
**下饭剧 anchors (loved, episodic/comfort format):**
- 老友记 (Friends) — 5.0 across every season logged (S1–S6, several
  unrated-but-watched at 5.0 pattern)
- 生活大爆炸 (The Big Bang Theory) — 5.0 S1–S2/S6–S8, 4.0 S3–S4/S11–S12,
  3.0 only S10 — strong, slightly fading-late pattern
- 武林外传 — 5.0
- 爱情公寓 (early seasons) — 5.0 (S2), 5.0 (S3, as "爱情公寓3"), 4.0 (S4);
  **anti-anchor**: 爱情公寓5 (2020) — 1.0, and 爱情公寓 (2018 reboot) — 1.0.
  Sharp franchise-quality-collapse signal, not a blanket love of the IP.
- 神探夏洛克 (Sherlock) — 5.0 (S1), 4.0 (S2–S3): case-of-the-week mystery
  procedural register also reads as comfort-viewing for this user
- 神探狄仁杰 — 4.0: same procedural-comfort pattern, Chinese-language
- 极限挑战/奇葩说/脱口秀大会 (variety/talk shows) — mixed 1.0–4.0, no clear
  anchor; not pursued as a channel

**高密度电影 anchors (loved, demands full attention):**
- 七宗罪 (Se7en) — 5.0, 消失的爱人 (Gone Girl) — 5.0, 彗星来的那一夜
  (Coherence) — 5.0 — his three 5-star dense-thriller exemplars
- 盗梦空间 (Inception) 4.0, 星际穿越 (Interstellar) 4.0, 记忆碎片 (Memento)
  4.0, 禁闭岛 (Shutter Island) 4.0, 致命ID (Identity) 4.0, 源代码 (Source
  Code) 4.0 — a very consistent Nolan/structural-puzzle pattern
- 寄生虫 (Parasite) 4.0, 穆赫兰道 (Mulholland Dr.) 4.0
- **Anti-anchor**: 社交网络 (The Social Network) 3.0 — dense but merely
  "fine," useful ceiling-calibration that density alone isn't sufficient

**Excluded:** all watched/watching titles, all rec_log verdict=no rows
(none directly relevant to the shortlisted titles below — no overlap
found).

## 3. Sweep — channel hierarchy

**Tier 1 — pool query (local, no network), 4 calls:**
- `pool.py query --kind tv --limit 400` → 400 rows (capped; pool holds
  1185 tv total minus suppressed). Skewed heavily toward
  animation/kids/anime from `tmdb_rec` and `douban_rec` provenance —
  genuinely thin on adult sitcom/procedural comfort-viewing at this slice.
- `pool.py query --kind tv --tag Comedy --limit 400` → 117 rows, dominated
  by kids/teen-family sitcoms and shounen-comedy anime; found Seinfeld,
  New Girl, The IT Crowd as viable but unused (evidence budget spent
  elsewhere — logged, not chased further this pass).
- `pool.py query --kind tv --channel douban_rec --limit 400` → 400 rows
  (capped). Surfaced strong Chinese-catalogue procedural/cozy-mystery
  candidates (99.9：刑事专业律师, 谜探路德维希/Ludwig, 猫头鹰谋杀案, 老练律师)
  — logged as viable but not carried to dossier stage; evidence budget
  went to the stronger shell candidates below instead. **Pool gap noted**:
  none of these Chinese-language cozy-procedural titles carry `tags` (the
  `douban_rec` channel does not populate the `tags` column at all — every
  row in this query had `tags: []`), which weakens tier-1 filterability
  for this channel specifically going forward.
- `pool.py query --kind tv --year-from 2023 --limit 400` → 156 rows.
  Surfaced the 2023-2026 recency slice (Only Murders S4, several cozy
  mystery procedurals — 猫头鹰谋杀案, 谜探路德维希, 老练律师, 潜能探案组).
- `pool.py query --kind film --year-from 2024 --limit 300` → 257 rows.
  Surfaced Bugonia (2025, Lanthimos) as the standout dense-film candidate,
  plus The Secret Agent, Black Bag as backups (not pursued — logged).

**Tier 2 — shells, swept directly against the ask (no network):** the
222-shell list was read in full. This was the *decisive* channel for the
series slot — 4 of the 5 shortlisted titles are shells the pool query
tier never would have surfaced (pool is TMDB/Douban CF output; shells are
this user's own prior acquisitions). Matches found: 大楼里只有谋杀 (Only
Murders in the Building), 神烦警探 (Brooklyn Nine-Nine), 小谢尔顿 (Young
Sheldon), 扑克脸 (Poker Face), Tenet (film). `external_ids` were present
and complete for all 5 (verified-at-load per README's shell coverage
note — not re-verified at source this pass, per that same note's
explicit permission to trust stored shell ids).

**Tier 3 — targeted top-up:** not invoked. Tier 1 (pool) + tier 2
(shells) together produced more viable candidates than the evidence
budget could carry to dossier stage, so no pool gap required a live
top-up fetch.

**Tier 4 — LLM-generated queries:** not invoked (interactive mode; not
needed given tiers 1-2 sufficed).

## 4. Shortlist against the target (not a fixed Cut1/Cut2 funnel — interactive mode)
Pitch target: 70th percentile, mid-rank, per candidate's own cell.
Checked cells (`history.py cell`) before shortlisting:
- `tv/show 2020-2026` (n=142): 70th percentile needs **4.5★ predicted**
  (4.0★ only reaches 54.9%ile — confirmed with `percentile-of`, matches
  README's calibration exactly).
- `tv/show 2010-2019` (n=242): 70th percentile needs a full **5.0★**
  predicted (this population is even warmer than 2020-26 TV).
- `film 2020-2026` (n=105): 70th percentile needs **4.0★ predicted**
  (confirmed: 3.5★→55.2%ile, 4.0★→74.8%ile).

This is a genuinely high bar for series (near-"loved it," not merely
"good") and a moderate bar for recent film. Shortlisted only candidates
with a real case for clearing it in their own cell — dropped, without
building dossiers for: Young Sheldon (BBT-spinoff reputation is more
mixed than BBT itself — judged unlikely to clear a 4.5★ bar), Seinfeld/
The IT Crowd/New Girl (strong classic fits but evidence budget was
finite and shell candidates already matched the ask's exemplars more
directly), the Chinese cozy-procedural slate from `douban_rec` (99.9：
刑事专业律师, 谜探路德维希, etc. — plausible but untested against evidence,
logged for a future pass rather than spent budget on 6+ candidates when
5 already filled the pitch cap), The Secret Agent / Black Bag (recent
acclaimed films, but Bugonia's pool-provenance link straight to a 5-star
anchor — 彗星来的那一夜 — made it the stronger case-law bet within a
1-film evidence budget).

**Shortlisted (5 — fills the pitch cap of 5, matches the ask's 2-3
series / 1-2 films shape at 3 + 2):**
1. **Only Murders in the Building** (tv, 2021, shell #590) — witty
   ensemble + case-of-the-week mystery; doubly anchored (Sherlock +
   Friends/BBT registers).
2. **Brooklyn Nine-Nine** (tv, 2013, shell #525) — workplace ensemble
   sitcom, direct Friends/BBT/武林外传 analogue, never watched despite
   being squarely in his rated-5.0 lane.
3. **Poker Face** (tv, 2023, shell #497) — Rian Johnson case-of-the-week
   anthology, structural Sherlock/神探狄仁杰 analogue.
4. **Tenet** (film, 2020, shell #5960) — the one major post-2010 Nolan
   film absent from his 4.0-pattern (Inception/Interstellar/Memento).
5. **Bugonia** (film, 2025, pool id 348) — Lanthimos, pool-surfaced
   directly off anchor 彗星来的那一夜 (his 5-star Coherence rating).

## 5. Evidence — cached vs fetched
**Cached at session start: 0/5** (pool-wide `evidence_cached: 0`, per
`pool.py stats` above — this is the first run through the rebuilt
pool-first path, so nothing was pre-cached; expected).

**Fetched this run: 5/5** —
- TMDB `/tv/107113/reviews` (Only Murders) → 3 reviews, mixed (1
  strongly positive, 1 strongly negative, 1 neutral-short). Tier 1.
- TMDB `/tv/48891/reviews` (Brooklyn Nine-Nine) → 4 reviews, genuinely
  split (1 hostile, 1 lukewarm-positive citing a weak final season, 2
  short positive). Tier 1.
- TMDB `/tv/120998/reviews` (Poker Face) → **0 reviews.** Fell back to
  NeoDB per §3c's evidence hierarchy: `catalog/search` (found parent
  uuid + season-1 uuid) → `/posts/?type=review` at **both** the parent
  uuid and the season-1 uuid (per the documented season/parent-uuid
  404-trap in SCOUT.md's NeoDB run notes) → **both returned `count:0`,
  HTTP 200** — a confirmed genuine zero, not a masked lookup error.
  Landed at Tier 3 (NeoDB aggregate rating only: 7.9 parent / 7.6 S1).
- TMDB `/movie/577922/reviews` (Tenet) → 18 reviews, wide spread
  (1-10/10), including one very long (15k-char) negative review. Tier 1.
- TMDB `/movie/701387/reviews` (Bugonia) → 10 reviews, positive-to-mixed
  (5-10/10 in the fetched sample). Tier 1.

**Written back to the pool cache:** only Bugonia is an actual
`candidate_pool` row (id 348) — the other 4 shortlisted titles are
shells (already-owned library records, not pool candidates), so
`attach-evidence` does not apply to them; there is no mechanism in the
current schema to cache evidence against a shell/work_id, only against a
`candidate_pool` row. `pool.py attach-evidence --id 348 --json
evidence_bugonia.json` → `ok`. This is the one piece of evidence that
will be free on a future pool-sourced ask; the shell evidence will be
re-fetched next time a shell-heavy ask touches these same 4 titles,
since shells have no cache slot at all in v2's schema.

**Network call total: 8** (5 TMDB reviews + 1 NeoDB search + 2 NeoDB
posts-by-uuid for the Poker Face fallback) — under the ~10 budget.

## 6. Dossiers
5 written to `dossiers.json` (copy below). `evidence_tier`: 1, 1, 3, 1, 1
(Poker Face is the one Tier-3 dossier, flagged explicitly as resting on
aggregate rating alone with no quoted review text).

```json
[see /private/tmp/.../scratchpad/test1/dossiers.json for full content —
 5 objects: Only Murders in the Building (tv/2021), Brooklyn Nine-Nine
 (tv/2013), Poker Face (tv/2023), Tenet (film/2020), Bugonia (film/2025)]
```

## Speed-test findings
- **Wall-clock: ~8-9 minutes end to end**, over the ≤5-minute interactive
  target. Where the time actually went, roughly: reading README.md +
  SCOUT.md in full (643 lines, including a long Source-notes appendix)
  was itself a meaningful upfront cost before any retrieval began;
  scanning 400-row pool query dumps by eye (4 separate queries, ~1,600
  rows total printed) to find signal in noisy TMDB-kids/anime-heavy
  channels was the next biggest cost; the NeoDB two-uuid fallback for
  Poker Face (documented as necessary by SCOUT.md's own run notes, to
  avoid a false negative) added real time for a candidate that ended up
  Tier 3 anyway.
- **Network calls: 8/~10** — comfortably inside budget. The pool-first
  design worked as intended: zero calls were spent on candidate
  *generation* (all 5 shortlisted titles came from local pool queries or
  the local shell list); every call was evidence-fetching for already-
  decided candidates, exactly as the "Run modes" section describes.
- **Shells were the decisive channel, not the harvested pool.** 4/5
  shortlisted titles are shells — prior deliberate library acquisitions
  — not `tmdb_rec`/`douban_rec` output. The pool query tier, at this
  particular harvest snapshot, is heavily skewed toward kids'
  animation/anime for the `tv` kind (126/400 and 117/400 rows tagged
  Animation/Comedy respectively in two separate pulls), which cost real
  scan time for comparatively little yield against *this specific* ask.
  That is a finding about this harvest's composition for a 下饭剧-shaped
  ask, not a flaw in the pool mechanism itself.
