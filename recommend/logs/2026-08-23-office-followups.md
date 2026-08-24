# Funnel log — 2026-08-23 — "看了 The Office，有别的推荐吗"

Ask (verbatim): `我最近看了 the office 我觉得好好看，你有没有什么别的推荐？`
Run: scout pass only (critic run separately by the controller). Scratchpad:
`/private/tmp/claude-501/-Users-anping-Documents-Stuff-AI-Space-media-hub/009324b1-0160-40fe-ab60-bff5f78ff9bb/scratchpad/runA/`

## 0. Session setup

- Read `recommend/README.md` (instance bindings), `recommend/SCOUT.md` (contract,
  incl. the 2026-08-23 probe notes at the bottom), `TASTE.md` (profile), and
  `STATE.md` for status.
- Snapshot taken BEFORE any network I/O:
  `python3 recommend/history.py --db media.db snapshot --out snapA.json`
  → `{"rated": 1702, "wishlist": 91, "shells": 222, "rec_log": 0}`
- Index built: `python3 recommend/history.py index --snapshot snapA.json --out indexA.txt`
  → 1717 lines, ends in `# END OF INDEX — 1702 entries listed above.` (read
  complete, not truncated).

## 1. Interpret the ask

Single reading, no split needed: user watched The Office (US) and loved it,
wants similar recommendations. The controller supplied critical framing not
present in the DB itself: the profile's watch/wishlist record for The Office
predates this viewing (it shows as `wishlist`, work_id 5944, not `watched`) —
media.db has not caught up to the fact that he has now watched and loved it.
Treated per the brief as fresh, authoritative signal, and per TASTE.md's own
"第二轮" calibration note, which already contains his exact quote on why:
> 谈美版办公室:「看到过抖音切片，有兴趣。但是不是你给的理由。就是很奇怪很尴尬的
> 笑点」— i.e. the draw is specifically designed, camera-caught awkward
> comedy, not any other stated reason. This is TASTE.md's explicit worked
> example distinguishing the hard red line ("做作、矫揉造作、执行层面的尴尬" —
> awkwardness that is a production/performance FAILURE) from the sanctioned
> exception ("设计出来的尴尬型幽默...他反而主动感兴趣" — designed awkward humor
> as a selling point). That distinction is the organizing question for this
> whole sweep, not "comedy" or "sitcom" generically.

## 2. Work the history

**Excluded from the pool immediately** (watched/watching, `no` verdict, or
wishlist per §2 — rec_log is empty so no `no` verdicts exist yet):
- The Office US itself (work_id 5944, wishlist row — this is the seed, not a
  candidate).
- Everything already in `rated` that came up during the sweep: Friends
  (老友记), Modern Family (摩登家庭), Brooklyn Nine-Nine (神烦警探), Silicon
  Valley (硅谷), The Marvelous Mrs. Maisel (了不起的麦瑟尔夫人), The Simpsons
  (辛普森一家), Futurama (飞出个未来), Better Call Saul (风骚律师) — all used
  as anchors/anti-anchors below instead.
- Wishlist items surfaced mid-sweep, logged as "already on your list," not
  pitched: Arrested Development S1 (work_id 2126, 发展受阻), Monty Python's
  Flying Circus S1 (work_id 2137, 巨蟒剧团之飞翔的马戏团), 日常工作 S1
  (work_id 2138, wishlist, unidentified beyond title), and — from the second-
  round taste-calibration batch — 切尔诺贝利/南方公园/黑道家族 (work_ids
  5943/5945/5946, all "想看" from a blind test, irrelevant genre-wise but
  confirmed excluded per rule anyway).

**Neighborhood swept from the index** (grep across the 1702-line index for
office/sitcom/mockumentary-adjacent titles):

| work_id(s) | title | stars (by season) | note |
|---|---|---|---|
| 4438–4442, 4437 | 老友记 Friends S1–6 | 5,5,5,5,5,4.0(S6) | S6 review: "情怀" (nostalgia) — near-ceiling ensemble hangout comedy, the strongest single anchor for "long-running American ensemble comedy he'll commit years to" |
| 4622,4621,4615–4617,4509–4514 | 摩登家庭 Modern Family S1–11 | 5,5,3,4,4,4,4,3,3,3,3 | **Key anti-anchor.** Mockumentary-format sibling of The Office. Declines from 5→3 over the run. S10 review text: **"梗已经逐渐尴尬和做作"** (the gags gradually turned awkward AND contrived/forced) — this is the profile's hard-red-line language (做作/尴尬-as-failure) showing up as an in-history verdict, giving the designed-vs-failing distinction a real, dated data point rather than just the taste-calibration quote. |
| 4594,4593,4592,4591,4577,4546,4547,4391 | 神烦警探 Brooklyn 99 S1–8 | 5,5,5,3,4,3,4,2 | S8 review: "第八季直接烂尾，只能两分" (S8 flat-out botched its ending, only 2 stars) — separately-scored finale penalty (per TASTE.md's "结尾单独计分，烂尾明确扣星"), a distinct risk category from the awkwardness axis, logged because it recurs below (HIMYM). |
| 4602,4601,4610,4603,4585,4563 | 硅谷 Silicon Valley S1–6 | 5,3,4,4,4,5 | Workplace-incompetence ensemble comedy, non-mockumentary but same "designed awkward failure at work, played straight" engine; S6 note: "最后一集太棒了加一星" (final episode was great enough to add a star) — the mirror image of the B99 finale penalty, i.e. this profile scores endings hard in both directions. |
| 816 | 了不起的麦瑟尔夫人 S1 | 3.0 | Lower interest; only S1 rated, no further seasons — logged, not used as an anchor. |

**Anchors** (≥4★, the profile's enthusiasm threshold): Friends (near-universal
5★), Modern Family S1–2 (5★, before the decline), Brooklyn 99 S1–3 & S5 & S7
(5,5,5,4,4), Silicon Valley S1 & S6 (5,5).

**Anti-anchors**: Modern Family S8–11 (3★, explicit "尴尬和做作" complaint —
designed-awkwardness-gone-wrong is the exact failure mode to screen candidates
against), Brooklyn 99 S8 (2★, botched finale).

**Shells swept** (222 no-watch/no-wish works) for office/workplace-comedy/
mockumentary terms — English and Chinese, keyword list included office,
parks and rec, arrested development, community, veep, curb your, peep show,
IT crowd, extras, 30 rock, scrubs, seinfeld, shadows, nathan for you, i think
you should leave, superstore, abbott, ghosts, schitt, derek, ted lasso, and
Chinese equivalents. **Zero shell-channel matches.** The only tv/show-kind
shells that came close in genre neighborhood were 巴瑞 (Barry), 硅谷
(Silicon Valley — parent record, already rated via seasons), 柯明斯基理论
(The Kominsky Method), 生活大爆炸 (The Big Bang Toy), 老友记 (Friends parent
record), 一年一度喜剧大赛 (a Chinese sketch show) — none of these are
mockumentary/workplace-Office-adjacent enough to pitch over the sweep's
actual finds, and none were pursued further given stronger candidates
elsewhere.

## 3. Sweep — channels and yields

**a. Anchor expansion (TMDB `/tv/{id}/recommendations`)** — per SCOUT.md's
own probe notes, `/recommendations` >> `/similar`; only `/recommendations`
used.
- Seed `/tv/2316/recommendations` (The Office US, TMDB id verified via
  `/find/tt0386676`): 20 results — yielded The Office UK, Superstore, W1A,
  Better Off Ted, **The Paper (2025)**, Reno 911!, Outsourced, and a run of
  classic-era multicam sitcoms (WKRP, Sanford and Son, Barney Miller, etc.)
- `/tv/1421/recommendations` (Modern Family): 15 results — mostly classic
  family multicam (Step by Step, Leave It to Beaver, Fresh Prince) plus
  Malcolm in the Middle (high signal, 8.467/4935 votes) and Happy Endings.
- `/tv/48891/recommendations` (Brooklyn 99): 15 results — Seinfeld, Night
  Court (both versions), Superstore (dup), Will & Grace, Key & Peele.
- `/tv/60573/recommendations` (Silicon Valley): 15 results — Larry Sanders
  Show, Portlandia, **Curb Your Enthusiasm**, Colin from Accounts, several
  sketch shows (Tim and Eric, In Living Color, Chappelle's Show).
- `/tv/8592/recommendations` (Parks and Rec, pulled once it surfaced as a
  candidate itself, to expand further): 15 results — **St. Denis Medical**,
  **Veep**, **The Thick of It**, **Documentary Now!**, Great News, Workaholics,
  Welcome to Flatch, Platonic.
- `/tv/18347/recommendations` (Community, pulled as a genre-adjacent probe):
  15 results — How I Met Your Mother (high signal), Arrested Development
  (already wishlist), Seinfeld (dup), Schmigadoon!, A Bit of Fry & Laurie.
- `/tv/125935/recommendations` (Abbott Elementary, once it surfaced): 15
  results — The Simpsons (already rated), The IT Crowd, 30 Rock, Saved by
  the Bell (both versions), Girl Meets World.

**b. Generated queries — TMDB `discover/tv` with the mockumentary keyword.**
`search/keyword?query=mockumentary` → keyword id 11800. `discover/tv?
with_genres=35&with_keywords=11800&vote_count.gte=100` → **22 total results,
20 read**: The Office (seed), Arrested Development (wishlist), **Parks and
Recreation**, **Abbott Elementary**, **What We Do in the Shadows**, Reno
911!, Trailer Park Boys, High School Musical: TMTS, Dream Productions,
American Vandal, **Jury Duty**, The Office UK, The Muppets, Wellington
Paranormal, **The Rehearsal**, **Nathan for You**, Derek, Death Valley,
Cunk on..., Stromberg. This is the single highest-precision channel in the
sweep — directly on-target genre+format filter, ~0% junk.

**c. Review mining — tiered per §3c.** All 8 finalists are English-language,
so TMDB `/reviews` was tried first (Tier 1) for every survivor reaching Cut 2:
- Hits (real, if thin, verbatim text): What We Do in the Shadows (1 review),
  Superstore (1 review), Abbott Elementary (1 review).
- Misses (empty `results`): Parks and Recreation, 30 Rock, How I Met Your
  Mother, Jury Duty, Nathan for You, The Paper — for these, fell back to
  NeoDB `/api/item/{uuid}/posts/?type=review` (checked for all five; **zero
  results on every one** — NeoDB's Chinese-skewing review base doesn't cover
  these particular English-language sitcoms either) and then WebSearch per
  the evidence-hierarchy fallback (Tier 2, attributable characterization).
  WebSearch queries run: "Parks and Recreation critical reception", "Jury
  Duty 2023 show review critics reaction", "Nathan for You review cringe
  comedy critics", "30 Rock review critics reaction workplace comedy", "How I
  Met Your Mother critical reception review", "'The Paper' 2025 Greg Daniels
  Office spinoff review reception" — all six returned real, attributable
  critic quotes/characterizations, logged in dossiers.json at Tier 2.
- NeoDB catalog `rating`/`rating_count` (Tier 3 floor) pulled for all 8
  finalists as a numeric cross-check regardless of review-text success.

**d. Editorial** — folded into the WebSearch queries above rather than run
as a separate pass; no dedicated "best shows like The Office" listicle
search was run separately (time budget; the discover+recommendations
channels already converged on the same core set editorial lists would
likely surface).

**e. Recency** — The Paper (2025, Peacock) surfaced organically from channel
(a) as an Office recommendation and turned out to be the most recency-
relevant possible find: a 2025 in-universe continuation by the same creator.
No separate "notable releases since last run" pass was run beyond this,
since there is no prior run to diff against (STATE.md confirms this is the
system's first real ask).

**Gathered pool total: ~95 distinct titles** across channels (a)–(c) before
dedup against §2's excluded set. (Exact count not mechanically deduped
against a master list — channels (a)/(b) overlapped heavily on Superstore,
Seinfeld, Reno 911!, Curb Your Enthusiasm, Portlandia, which were counted
once each below.)

## 4. Narrow

### Cut 1 (metadata only) — eliminated by category, ~95 → ~26 survivors

**Pre-sweep exclusions** (not technically "Cut 1" eliminations since they
never entered the pool as candidates, logged here for completeness): The
Office US (seed, work_id 5944), Modern Family / Brooklyn 99 / Silicon Valley
/ Friends / Marvelous Mrs. Maisel / Simpsons / Futurama / Better Call Saul
(all `rated`), Arrested Development S1 / Monty Python's Flying Circus S1
(both `wishlist`).

**Category B — British-sourced awkward/cringe comedy.** TASTE.md's H17 is a
准 (confirmed) calibrated entry with named exemplars on both sides: English
crime drama (夏洛克/9号秘事/真相捕捉) is a loved zone, but "英式尬喜欢明确欣
赏不来" (British awkward comedy explicitly not appreciated) is stated flatly
as the opposite pole. Every British-sourced mockumentary/cringe-comedy
candidate this sweep found gets cut on this basis, even though several are
critically excellent in the abstract:
- OUT The Office UK (2001): British-sourced awkward comedy — H17 calibrated anti-signal, distinct from the US Office love this ask is chasing.
- OUT W1A (2014): same.
- OUT The Thick of It (2005): same; also created by Armando Iannucci, same creative hand as Veep (see Category F note on Veep below).
- OUT The IT Crowd (2006): same.
- OUT Derek (2013): same (Ricky Gervais, UK).
- OUT Cunk on... (2018): same.
- OUT A Bit of Fry & Laurie (1989): same.
- OUT Mind Your Language (1977): same.
- OUT Coupling (2000): same (British hangout sitcom).
- OUT Drop the Dead Donkey (1990): same.
- OUT Hi-de-Hi! (1980): same.

**Category C — sketch/variety format mismatch** (not narrative mockumentary
or sitcom; different comedic mode from what a post-Office ask is chasing):
- OUT Key & Peele (2012), Chappelle's Show (2003), In Living Color (1990),
  The Whitest Kids U' Know (2007), Tim and Eric Awesome Show Great Job!
  (2007), Nick Cannon Presents: Wild 'N Out (2005), A Black Lady Sketch Show
  (2019), Jackass (2000), All That (1994): all sketch/variety/stunt format,
  no continuing narrative ensemble — the mechanism the profile responded to
  (a documentary crew catching an ensemble's ongoing awkwardness) doesn't
  exist in this format.

**Category D — classic-era/family/teen multicam sitcom, tonal/format
distance from the target** (the profile's loved neighborhood is entirely
2000s+ single-camera or hybrid-format American comedy — Friends, Modern
Family, Brooklyn 99, Silicon Valley — none of these are multicam
laugh-track shows):
- OUT High School Musical: TMTS (2019), Saved by the Bell 1989 (1989) &
  2020 reboot, Lizzie McGuire (2001), Girl Meets World (2014), Clarissa
  Explains It All (1991), Drake & Josh (2004), Are We There Yet? (2010),
  Life with Derek (2005), Stuck in the Middle (2016), Son of a Critch
  (2022), Head of the Class (1986), Amen (1986), What's Happening!! (1976),
  A Different World (1987), Moesha (1996), Leave It to Beaver (1957), The
  Honeymooners (1955), Sanford and Son (1972), The Jeffersons (1975),
  Barney Miller (1975), Archie Bunker's Place (1979), Major Dad (1989),
  WKRP in Cincinnati (1978), Night Court 1984 & 2023 reboot, 2 Broke Girls
  (2011), Will & Grace (1998), The Conners (2018), Tyler Perry's House of
  Payne (2007), Less than Perfect (2002): teen/family/classic-era multicam,
  no anchor in the loved neighborhood, all cut on tonal-distance grounds.

**Category E — thin metadata (low TMDB vote_count, insufficient signal to
carry a dossier)**:
- OUT Betas (2013, votes=40), On Cinema (2012, votes=27), Unhappily Ever
  After (1995, votes=45), Bad Judge (2014, votes=52), Ground Floor (2013,
  votes=39), Trophy Wife (2013, votes=64), Friends with Better Lives (2014,
  votes=54), Another Period (2015, votes=71), Shifting Gears (2025,
  votes=77), Mr. Mayor (2021, votes=91), Schmigadoon! (2021, votes=157 —
  kept borderline but ultimately not advanced given stronger competition),
  Death Valley (2011, votes=114), Wellington Paranormal (2018, votes=118 —
  also a horror-mockumentary spinoff of the Shadows film universe, redundant
  with the Shadows TV pick itself), Stromberg (2004, votes=135, German-
  language remake — foreign-language-original risk plus dated).

**Category F — genre/format near-misses, cut for redundancy or weaker fit
given only 8 dossier slots** (these are real, defensible candidates —
logged with why they lost out, not dismissed as junk):
- OUT Curb Your Enthusiasm (2000): genuinely strong "designed cringe" fit
  (votes=963, avg=8.043) but Larry David's improvised-real-world cringe is
  closer to Nathan for You's register than to mockumentary-sitcom, and
  Nathan for You was judged the sharper, more extreme version of that same
  bet for one of the 8 slots.
- OUT Veep (2947, 2012): excellent reviews (avg=7.5, votes=541) but created
  by Armando Iannucci (same hand as The Thick of It, cut under Category B) —
  American cast and setting soften but don't erase the British-creator
  awkward-comedy lineage; judged a real but second-tier risk against the
  H17 signal, cut in favor of cleaner-provenance picks.
- OUT Documentary Now! (2015): mockumentary format but an anthology of
  one-off documentary-style parodies, not a continuing character ensemble —
  format mismatch with what made the profile love The Office/Modern Family
  (following the same people over years).
- OUT Portlandia (2011): sketch/vignette hybrid rather than character
  ensemble, similar format objection to Documentary Now!.
- OUT Welcome to Flatch (2022): US remake, but of British "This Country" —
  inherits some of the Category B risk at one remove.
- OUT Trailer Park Boys (2001): genuine mockumentary format but blue-collar
  crime-comedy register, tonally distant from workplace/institutional
  awkwardness.
- OUT American Vandal (2017): strong mockumentary-parody format (teen
  true-crime documentary spoof) but redundant with Jury Duty for the
  "designed-prank-on-an-institution" niche within an 8-slot budget.
- OUT St. Denis Medical (2024): same creative lineage as Superstore
  (Justin Spitzer/Superstore writers' room), genuinely on-target mockumentary
  medical-workplace format, but thin votes (52) and redundant with Superstore
  and Abbott Elementary already covering "contemporary US workplace
  mockumentary" — cut for redundancy, not weakness.
- OUT Great News (2017, votes=88): Tina Fey-produced workplace mockumentary-
  adjacent comedy, thin metadata and redundant with 30 Rock already covering
  the Tina Fey angle.
- OUT Malcolm in the Middle (2000): very strong signal (avg=8.467,
  votes=4935) but pure family-multicam-hybrid, not workplace/ensemble —
  cut for thematic distance from the office/workplace core of the ask
  despite the numbers.
- OUT Happy Endings (2011): ensemble hangout comedy, close cousin to Friends
  but redundant with How I Met Your Mother for the "Friends-style hangout"
  slot.
- OUT Colin from Accounts (2022): hangout rom-com format, not workplace/
  mockumentary, weaker fit than the finalists.
- OUT The Muppets (2015): mockumentary format but puppet-variety tonal
  mismatch with a live-action ask.
- OUT Reno 911! (2003): genuine mockumentary-cop-parody format, decent
  candidate, but the profile already has 5 rated seasons of Brooklyn 99 —
  judged redundant with an already-watched, already-loved cop-workplace
  comedy rather than a genuinely new direction.
- OUT Better Off Ted (2009): solid absurdist-workplace-comedy candidate
  (votes=243) but short-lived/lower profile than the finalists chosen;
  cut for budget, not for a specific flaw.
- OUT Workaholics (2011): workplace-adjacent stoner comedy (votes=315) —
  different comic register (laddish, drug-humor-forward) than the
  observational-awkwardness core of the ask; judged a tonal risk.
- OUT The Mindy Project (2012): hospital rom-com sitcom, weaker
  mockumentary/awkwardness tie than the finalists.
- OUT Outsourced (2010), The Drew Carey Show (1995), The Crazy Ones (2013):
  lower-profile workplace sitcoms, cut for weaker signal vs. the finalists.

### Cut 2 (light evidence pull, all survivors) — ~26 → 8 dossiered

Light evidence (TMDB reviews check + NeoDB rating + a skim of vote counts)
was pulled for every Cut-1 survivor. The following did NOT make the final 8
after that pass, with the specific reason:

- OUT How I Met Your Mother (2005): strong numbers (avg=8.124, votes=5890)
  and genuine "Friends-style ensemble hangout" fit — but WebSearch reception
  surfaces its finale as one of the most litigated bad endings in sitcom
  history ("frequently cited among worst TV show endings"). Given the
  profile's own demonstrated pattern of separately penalizing bad endings
  (Brooklyn 99 S8: "第八季直接烂尾，只能两分") this is a real, concrete risk
  rather than a hypothetical one, and the show's core appeal (ensemble
  hangout) is already well covered by the profile's existing 5★ Friends
  history rather than being a novel pitch. Judged a weaker use of a dossier
  slot than the mockumentary-specific picks, which more directly answer the
  stated "why The Office worked" reason. Not discarded outright — worth
  surfacing to the user informally if the critic has room, but not one of
  the 8 argued dossiers.
- OUT Seinfeld (1989): massive numbers (avg=8.255, votes=2425) but an
  observational, plotless "show about nothing" register quite different from
  workplace/mockumentary awkwardness; also a much-referenced cultural
  monument the user has very likely already encountered/formed an opinion on
  outside the DB, making it a weak "new pitch."

**8 titles advanced to full dossiers** (see `dossiers.json`): The Paper
(2025), Parks and Recreation (2009), What We Do in the Shadows (2019),
Abbott Elementary (2021), Jury Duty (2023), Superstore (2015), 30 Rock
(2006), Nathan for You (2013).

## 5. Dossiers

Written to
`/private/tmp/claude-501/-Users-anping-Documents-Stuff-AI-Space-media-hub/009324b1-0160-40fe-ab60-bff5f78ff9bb/scratchpad/runA/dossiers.json`
(8 objects). `evidence_tier` distribution: 3 at Tier 1 (Shadows, Abbott,
Superstore — real TMDB user-review quotes), 5 at Tier 2 (The Paper, Parks
and Rec, Jury Duty, 30 Rock, Nathan for You — WebSearch-sourced attributable
critic characterization, TMDB `/reviews` came back empty for all five).
Every `external_ids.tmdb_tv` was resolved by direct API call this session
(`/find` for the seed, `/search/tv` + manual disambiguation for the rest,
`external_ids` appended to each `/tv/{id}` detail call for the IMDb id) —
none written from memory.

## 6. Handoff

Per SCOUT.md §6: the critic is spawned separately by the controller with
the profile, `index.txt` contents + `snapA.json` path, `dossiers.json`, and
CRITIC.md only. This funnel log and channel-yield detail are NOT passed to
it.

## Notes on SCOUT.md — anything ambiguous or hard to follow

- **The "shells first-class channel" instruction was easy to follow
  mechanically but yielded nothing this run** — worth recording plainly
  rather than papering over: none of the 222 shells matched this ask's
  genre. That's a real, reportable null result for this specific ask, not a
  process failure — the instruction says to sweep them "exactly as an
  external catalogue," which I did (a full keyword sweep across both English
  and Chinese titles), and it just didn't hit.
- **No genuine ambiguity in SCOUT.md itself this run.** The one place I had
  to exercise judgment rather than follow a mechanical rule was Category B
  (British-sourced awkward comedy) and the Veep/Curb Your Enthusiasm calls
  in Category F — SCOUT.md doesn't tell the scout how to weigh a calibrated
  taste-profile anti-signal (H17) against strong critical numbers for a
  candidate; I treated README.md's grading rubric ("An entry the profile
  states as confirmed/calibrated... may carry a kill") as license to cut on
  it outright for the clean British-format cases, and to weigh it as a
  second-order risk factor (not an outright kill) for the mixed-provenance
  cases like Veep. This is a judgment call, not a bug in SCOUT.md, but it's
  worth the critic (and the user) knowing it happened, since it removed some
  well-reviewed titles (Office UK, IT Crowd, W1A, Thick of It, Veep, Curb
  Your Enthusiasm) from dossier contention on taste-fit grounds rather than
  quality grounds.
- **history.py's `lookup` by `--work-id` doesn't take a list flag documented
  in `--help`, but does accept repeated ints as demonstrated** — worked fine
  once I passed multiple ids as trailing args; no actual blocker, just
  flagging that the CLI's `--help` text under-documents this compared to
  `--title`/`--creator`.

## Re-sweep

Second scout pass on the same ask, run after a blind critic judged the first
eight candidates and invoked the floor rule (only one survivor, asked for a
genuinely different angle rather than a lowered bar). Brief: do not re-tread
the Office/Schur/Daniels mockumentary lineage the first sweep drew from
exclusively; instead sweep zones TASTE.md names as genuine high-hit-rate
territory that the first sweep never touched — animated comedy/adult
animation and documentary (food/gaming/industry-behind-the-scenes veins) —
and prioritize titles with direct precedent in his own rated history over
pure analogy, plus titles where real review text is actually retrievable
(evidence thinness/split reception was the stated cause of every first-sweep
close-miss kill). Scratchpad:
`/private/tmp/claude-501/-Users-anping-Documents-Stuff-AI-Space-media-hub/009324b1-0160-40fe-ab60-bff5f78ff9bb/scratchpad/runA2/`

### 0. Session setup

Snapshot taken BEFORE any network I/O:
`python3 recommend/history.py --db media.db snapshot --out snapA2.json`
→ `{"rated": 1702, "wishlist": 91, "shells": 222, "rec_log": 16}` — rec_log
now has 16 rows (8 from this ask's first sweep, verdict column not yet
populated in this snapshot; 8 more from an unrelated concurrent run,
`南京照相馆`/`浪浪山小妖怪`/etc., not relevant to this ask). Index rebuilt:
`python3 recommend/history.py index --snapshot snapA2.json --out indexA2.txt`
→ 1717 lines, ends in the `# END OF INDEX` sentinel (complete read).
Confirmed the 8 already-judged titles from `recommendations` table
(`sqlite3 media.db "SELECT id,title FROM recommendations"` rows 1-8): The
Paper, Parks and Recreation, What We Do in the Shadows, Abbott Elementary,
Jury Duty, Superstore, 30 Rock, Nathan for You — excluded per the brief,
alongside everything already watched/wishlisted/`no`-verdicted per §2.

### 1. Interpret the ask

Same underlying ask as the first sweep (loved The Office, wants more), but
this pass's interpretation is explicitly reframed by the brief: instead of
"what else has the designed-awkward-comedy DNA," the working question became
"where else in this user's own rated history does he already show the same
kind of enthusiasm the mockumentary lineage was chasing, in genres the first
sweep never looked at." TASTE.md names two explicit high-hit-rate zones in
its own prose (not read literally by the first sweep, which stayed inside
sitcom/mockumentary): "动画他爱看" (adult animation, cited as de facto
long-form content alongside American sitcoms) and "纪录片命中率高...实际
五星集中在美食、游戏、行业幕后三类" (documentary hit rate is high, with
five-stars clustering in food, gaming, and industry-behind-the-scenes). Both
zones were mined from `analysis/taste_mining_2026-07-28.json` before any
external search, confirming the prose claim with real numbers:
`genre_tv` block — documentary n=16, avg 4.375, five_pct 62.5% (highest of
any TV genre); animation n=108, avg 4.333, five_pct 50.0% (second highest,
far above comedy's n=237/avg 4.055).

### 2. Work the history — zone mining (the core of this sweep's method)

**Adult animation anchors** (grep of indexA2.txt + taste_mining five_star
list): 马男波杰克 BoJack Horseman S1/S3/S4/S5 all 5.0 (S2 4.0, S6 unrated) —
his single strongest animation anchor. 瑞克和莫蒂 Rick and Morty S1-S4 all
5.0, **S6 dropped to 3.0** — a real, in-history decay data point in this
exact genre, reinforcing the brief's "shorter/completed runs" steer. 辛普森
一家 Simpsons 23 seasons rated, remarkably stable 4-5 throughout (a
counter-example showing decay isn't universal, just common). 外星也难民
Solar Opposites S1-S3 all watched (4,5,5 — improving, not decaying), 哈莉·
奎茵 Harley Quinn S1-S3 all watched (4,5,3 — decaying), 怪诞小镇 Gravity
Falls S1-S2 both watched 5.0 (complete series, no more seasons to chase),
咱们裸熊 We Bare Bears S1-S3 watched (5,5,4), 爱，死亡和机器人 Love, Death &
Robots S1-S3 watched (5,3,4). All of the above are **watched, excluded** —
logged here because they map the zone and supplied the BoJack lineage used
for Tuca & Bertie's case.

**Documentary anchors**, filtered from taste_mining's `five_star` list by
`documentary` genre tag (15 total 5-star docs): 舌尖上的中国 第一季 (2012,
food), 风味人间 S1/S2/S3 (2018-21, food, all 5.0), 剑指高分/High Score
(2020, gaming — his own review text: "我喜欢游戏 我喜欢好的纪录片 现在一个
好的游戏纪录片出现了"), 幻程故事/The Imagineering Story (2019, industry-
behind-the-scenes), 迪士尼乐园项目大起底/Behind the Attraction S1 (2021,
industry-behind-the-scenes), 守护解放西 S1/S2 (2019-20, Chinese police-
station observational doc, industry-adjacent — S3 dropped to 2.0, another
in-history decay point, S4-S6 recovered to 4-4.5), 二十二/Twenty Two, 人生
果实/Life Is Fruity, 五月天 x2 music docs, 兰迪·波许教授的最后一课, 如果国
宝会说话 S2. All watched/excluded; these anchors seeded and validated the
three sub-veins pursued in §3.

**Excluded** per §2 (checked via `history.py lookup` by title, not
work_id-verified individually for every hit given volume, but cross-checked
against the snapshot's `rated`/`wishlist`/`shells` sections which `lookup`
searches natively): all animation/documentary titles named above (watched),
plus candidates considered and ruled out as already-in-history during the
sweep itself — Close Enough S1 (watched, 3.0), Central Park S1 (watched,
4.0), American Factory (watched, 4.0 — not 5, logged as a real ceiling on
how far "industry doc" alone carries him without the food/gaming specificity),
舌尖上的中国 第三季 (checked, NOT in his history, but self-excluded on
evidence: NeoDB rating 3.5/162 votes, a well-known steep quality drop from
S1/S2 due to a different production team and a real fabrication controversy
— logged as OUT in Cut 1 below rather than silently dropped).

### 3. Sweep — channels and yields

**a. History-anchor-driven candidate generation (the primary channel this
pass, not a catalogue API sweep).** Rather than TMDB `/recommendations` off
a single anchor (which the first sweep already exhausted for the
mockumentary lineage and which returns weak, generic results for
documentary/anthology titles — confirmed by a live check: `/tv/106754
(High Score)/recommendations` returned 20 near-random talk-show/game-show
titles with 0% genre relevance, useless as a channel for this vein), this
sweep worked outward from named anchors via WebSearch/TMDB-search for
"same director," "same creative lineage," and "same sub-genre" titles:
- From 舌尖上的中国 S1 (5.0, food): checked for unwatched sequels directly
  — S2 (found, kept) and S3 (found, cut on evidence, see §2).
- From 风味人间/舌尖上的中国 (Chinese food-doc wave): 人生一串/The Story of
  Chuaner surfaced via WebSearch as the other major Chinese food-doc
  franchise of the same era, different house style (Bilibili street-food
  vs. CCTV prestige).
- From 高分/High Score (5.0, gaming): TMDB `discover/tv` and
  `discover/movie` with `with_genres=99` (documentary) `+
  with_keywords=282` ("video game") — 20 TV results (mostly obscure,
  vote_count ≤5) and 20 movie results (much stronger — The King of Kong:
  A Fistful of Quarters at vote_count=510 led the movie list by a wide
  margin). Also tried `with_keywords=166939` ("esports") — 13 TV results,
  nearly all vote_count=0, confirming esports-documentary is a thin
  catalogue at TMDB (a finding to log, not a channel failure).
- From 幻程故事/Behind the Attraction (5.0 x2, industry-behind-the-scenes):
  WebSearch for "documentary industry behind the scenes [craft]" surfaced
  Light & Magic (2022, ILM/visual-effects industry, direct Disney+
  sibling-in-spirit to the two existing anchors) and, more broadly,
  Abstract: The Art of Design and The Toys That Made Us as the two other
  major English-language "how a creative industry actually works"
  anthology docs.
- From 马男波杰克/BoJack Horseman (5.0 x4, adult animation): checked
  creator/studio lineage directly — Tuca & Bertie (creator Lisa Hanawalt
  was BoJack's production designer) surfaced immediately as the closest
  same-well, different-show candidate; also considered and set aside Big
  Mouth (long-running, 8 seasons, weaker direct-lineage tie) and Bob's
  Burgers (very long-running, higher decay-risk profile per the brief's
  steer, not pursued for a dossier slot).

**b. Shell sweep** (§2's mandated first-class channel) — re-swept the full
222-shell list this pass (not re-grepped from the first sweep's keyword
list, which was Office/mockumentary-specific) for food/gaming/animation/
documentary/industry terms in both English and Chinese. **One hit: The King
of Kong: A Fistful of Quarters (work_id 4319)** — already in his library,
unwatched, external_ids pre-verified at load (imdb tt0923752, tmdb_movie
13958, plex_guid present). This is the strongest possible candidate shape
per SCOUT.md §2's own argument (already deliberately acquired + zero
identity-verification risk) and became the lead dossier. No other shell
matched the target zones; 权力的游戏/鱿鱼游戏/Industry (finance drama, not
documentary despite the title) were shells that surfaced on generic
keyword overlap and were rejected as off-target on inspection.

**c. Review mining — tiered per §3c**, run per finalist rather than as a
separate bulk pass:
- TMDB `/reviews` checked for every English-language finalist (King of
  Kong, Chef's Table, Salt Fat Acid Heat, Jiro Dreams of Sushi, Tuca &
  Bertie, Light & Magic, Toys That Made Us, Abstract) — **0 results on
  every single one.** This is a real, reportable finding distinct from the
  first sweep's experience (which got real TMDB review hits for 3/8
  narrative-comedy finalists): documentary/anthology-format titles appear
  to draw far less TMDB user-review engagement than narrative sitcoms,
  regardless of critical acclaim or vote_count. Logged as a channel
  characteristic for future SCOUT.md runs, not a per-title flaw.
- Fell back to WebSearch (Tier 2) for all, and for three (King of Kong,
  Light & Magic, and an attempted-but-blocked NYT piece) followed up with
  direct WebFetch against the actual review page/RT editorial article to
  recover genuine verbatim quotes rather than only search-summary
  paraphrase — succeeded for King of Kong
  (editorial.rottentomatoes.com, Kim Newman's full quotes) and Light &
  Magic (thewrap.com, Lauren Piester's full quotes); failed for
  nytimes.com (paywalled, "unable to fetch") and realityblurred.com
  (403). Graded these two successful WebFetch pulls as Tier 1 (verbatim,
  attributed quotes meet the letter of the Tier 1 definition even though
  the channel is neither TMDB nor NeoDB) — flagged as a judgment call in
  the "ambiguous" section below.
- NeoDB `/api/tv/{uuid}/posts/?type=review` (Tier 1 for Chinese titles)
  checked for both Chinese finalists (舌尖上的中国 S2, 人生一串 S1) at
  both season-level and parent uuid, per the RUNBOOK gotcha about
  season/item path traps — **genuine zero on both**, confirmed via
  correct typed path (`/api/tv/{uuid}`, verified the uuid resolves to
  category `tv` before concluding zero, per the "genuine zero vs masked
  404" gotcha). Fell back to WebSearch `豆瓣 影评/评价` queries per the
  evidence hierarchy, which returned real aggregate scores (豆瓣8.7-9.0)
  and named characterizations, including one honestly-surfaced negative
  (舌尖2's fabrication controversy and narration-fatigue complaints).
- NeoDB catalog `/api/catalog/search` (Tier 3 floor) pulled for both
  Chinese titles regardless: 舌尖2 rating 7.9/263, 人生一串 rating
  8.7/449.
- TMDB `vote_average`/`vote_count` (Tier 3 floor) pulled for all 8
  English-identified titles.

**d. Editorial** — folded into the WebSearch review-mining queries above
(e.g. "Abstract: The Art of Design ... Emmy critical reception" doubled as
both review-mining and editorial-list discovery); no separate curated-list
pass run given the narrow, anchor-driven nature of this sweep.

**e. Recency** — not pursued as a separate channel; every finalist in this
set is an established, already-aired title (oldest 2007, newest 2022), consistent
with the brief's "shorter/completed runs" steer rather than a recency angle.

**Gathered pool total: ~28 distinct titles** considered across §3's
channels before narrowing — deliberately smaller than the ~100-200 target
in SCOUT.md §3, and logged here as an intentional, narrow-angle finding per
§4's explicit allowance: this sweep targeted three specific, previously-
unswept sub-genres (food doc, gaming doc, industry doc) plus one animation
lineage, rather than a broad genre discover pass, so the pool size reflects
the angle's genuine narrowness rather than a shortfall.

### 4. Narrow

**Cut 1 (metadata + first-pass evidence check) — ~28 → 12 survivors.**
Eliminated with reason:
- OUT 舌尖上的中国 第三季 (2018): NeoDB rating 3.5/162 — a real, sharp
  quality drop from S1/S2 (different production team, documented
  fabrication controversy in one segment). Direct-precedent logic cuts
  both ways: an unwatched sequel to a loved anchor is only strong evidence
  when the sequel itself is well-received, and this one isn't.
- OUT Free to Play (2014, Valve/Dota2 documentary): thin critical footprint
  (vote_count 159 vs. King of Kong's 510) and narrower single-game subject
  vs. King of Kong's more universally-praised sports-narrative structure;
  redundant with the stronger gaming pick.
- OUT Salt Fat Acid Heat (2018, 4-episode food miniseries): solid
  candidate (vote_average 7.886/35) but cut for pool balance once Chef's
  Table, Jiro Dreams of Sushi, and both Chinese food docs already filled
  the food-doc slots more strongly; logged as a reasonable alternate, not
  a quality-based kill.
- OUT Street Food: Asia (2019) and Ugly Delicious (2018): both decent
  (7.6/42 and 6.85/34 respectively) but weaker numbers and less
  distinctive critical narrative than the four food docs that advanced;
  cut for redundancy within an already-strong sub-vein.
- OUT The Toys That Made Us (2017): the closest competitor to Abstract for
  the second industry-behind-the-scenes slot. TMDB 7.545/100 (weaker than
  Abstract's 7.789/83 and Light & Magic's 7.864/59) plus one identified
  negative review ("it stunk," Yahoo Entertainment) sitting next to
  positive ones — a split-reception profile the brief specifically warned
  produced every first-sweep close-miss kill. Cut in favor of Abstract's
  cleaner, more unanimous reception (NYT critic top pick, two Emmy
  nominations, an IDA award, no located dissent).
- OUT Big Mouth (2017-2024, 8 seasons): weaker direct-lineage tie to any
  existing anchor than Tuca & Bertie, and its 8-season length cuts against
  this sweep's "shorter/completed runs" steer more than Tuca & Bertie's
  3-season, twice-cancelled run does.
- OUT Bob's Burgers (2011-ongoing): still airing, no season-by-season
  decay data available to evaluate against this user's demonstrated
  late-season-decline pattern in the genre (Rick and Morty S6 dropped to
  3.0 in his own history); judged a real risk not worth taking when
  shorter-run alternatives with cleaner critical pictures were available.
- OUT Close Enough, Central Park, American Factory: already watched
  (§2), never real candidates.

**Cut 2 (light evidence pull, all 12 survivors) — 12 → 8 dossiered.** The
8 that advanced are listed in §5 below. No further eliminations beyond
Cut 1 were needed to reach the target of 8 — the Cut-1 survivor pool
landed almost exactly at the dossier target given the narrower gathered
pool, so Cut 2 functioned as the deep-evidence pass for the final 8 rather
than a separate narrowing stage (consistent with SCOUT.md's "stage sizes
scale with the gathered pool" allowance).

### 5. Dossiers

Written to
`/private/tmp/claude-501/-Users-anping-Documents-Stuff-AI-Space-media-hub/009324b1-0160-40fe-ab60-bff5f78ff9bb/scratchpad/runA2/dossiers.json`
(8 objects, valid JSON, verified by parse). Final 8: The King of Kong: A
Fistful of Quarters (2007, gaming doc, shell), 舌尖上的中国 第二季 (2014,
food doc, direct sequel to a 5★ anchor), 人生一串 第一季 (2018, food doc),
Chef's Table (2015, food doc), Jiro Dreams of Sushi (2011, food doc), Tuca
& Bertie (2019, adult animation), Light & Magic (2022, industry-behind-
the-scenes doc), Abstract: The Art of Design (2017, industry-behind-the-
scenes doc). `evidence_tier` distribution: 2 at Tier 1 (King of Kong, Light
& Magic — both via directly-fetched review-page verbatim quotes), 6 at
Tier 2 (WebSearch-sourced attributable characterization/aggregate score,
TMDB `/reviews` empty on all 8, NeoDB review-post channel empty on both
Chinese titles). Every `external_ids` entry verified at source this
session: TMDB ids via `/search` + `/external_ids` calls, the King of Kong
shell's ids cross-checked against media.db's already-stored (load-time-
verified) `external_ids`, and both Chinese douban ids cross-verified via
two independent paths (NeoDB `external_resources` field AND an independent
WebSearch hit landing on the identical douban subject URL) — none written
from memory.

### 6. Handoff

Per SCOUT.md §6: the critic (spawned separately by the controller) receives
the profile, `indexA2.txt` contents + the path to `snapA2.json`,
`dossiers.json`, the distribution/cell data, the pitch target line, and
CRITIC.md only. This funnel log, channel-yield detail, and the Cut-1/Cut-2
elimination reasoning are NOT passed to it.

### Notes on SCOUT.md — ambiguous or judgment-call points this pass hit

- **Grading a WebFetch'd verbatim quote as Tier 1.** §3c defines Tier 1 as
  "TMDB `/movie|tv/{id}/reviews`, `/tv/{id}/reviews`... NeoDB..." by
  channel name, but the actual distinguishing property stated in the tier
  ladder is "verbatim quotes" vs. "characterization, no body quote" vs.
  "metadata floor." When TMDB/NeoDB reviews came back empty (as they did
  for every documentary in this set) but a direct WebFetch of a named
  critic's actual review page recovered real, attributed verbatim text
  (Rotten Tomatoes editorial for King of Kong, TheWrap for Light & Magic),
  I graded those specific evidence entries Tier 1 on the substance of the
  definition rather than downgrading them to Tier 2 for using a different
  channel. SCOUT.md doesn't explicitly rule on this case (a WebFetch that
  succeeds where the "official" Tier 1 channels are silent) — this is a
  judgment call worth the critic/user knowing about, not a bug in the
  contract.
- **Documentary/anthology titles appear to have near-zero TMDB
  `/reviews` coverage as a class**, independent of acclaim or vote_count
  (0/8 hit rate this pass, vs. 3/8 for the first sweep's narrative
  sitcoms). SCOUT.md's evidence hierarchy was written and measured
  primarily against narrative film/TV; this pass's experience suggests
  the hierarchy's TMDB-first ordering may need a documentary-specific
  caveat if future sweeps target this genre again. Recording as a finding
  for the Source notes section, not editing SCOUT.md myself per the
  read-only-during-a-run convention.
- **No genuine ambiguity in the exclusion/dedup mechanics** — `history.py
  lookup` behaved as documented, the shell channel worked exactly as
  described in §2, and the snapshot-then-index-then-lookup workflow from
  §0 required no deviation.
