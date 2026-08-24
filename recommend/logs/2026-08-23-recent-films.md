# Funnel log — 2026-08-23 — "有什么最近的好看的电影推荐？"

Run: runB. Snapshot: `scratchpad/runB/snapB.json` (1702 rated, 91 wishlist, 222
shells, 0 rec_log). Index: `scratchpad/runB/indexB.txt` (1702 entries).

## 0. Ask interpretation

Verbatim ask: `有什么最近的好看的电影推荐？` — two words carry the whole
constraint: **电影** (films only, explicitly not TV/剧集, even though the DB's
in-scope kinds are film/tv/show/drama) and **最近的** (recent).

"Recent" here reads as *recent release*, not "recently watched by him" — the
ask is a request for new-to-him good films that came out lately, which is the
digest-style "recency" channel per SCOUT.md §3e, not a request to re-examine
his own viewing history's chronology. Working interpretation adopted: **recent
= released roughly within the last ~2 years of today (2026-08-23), i.e.
2024-09 through 2026-08, with a strong bias toward 2025-2026** and any older
title excluded outright regardless of quality. This is stated explicitly here
per the brief's instruction not to silently narrow — a stricter "2025-2026
only" reading was considered and rejected because it would have cut a few
strong 2024 H2 Chinese titles (雄狮少年2, 风流一代, 一部未完成的电影, 小小的我)
that are still clearly "recent" in ordinary usage.

Kind scope for this run: **film only** — the ask's "电影" is unambiguous, so TV
candidates surfaced incidentally during sweep (e.g. from shared genre/anchor
searches) were not pursued as dossiers even when good.

## 1. History work — neighborhood, anchors, anti-anchors

Read TASTE.md in full (calibrated 2026-07-28) and the complete 1702-line
history index. Since the ask has no genre/mood axis of its own, "neighborhood"
here is effectively his whole recent-era film rating history, with heavier
weight on 2021+ per the brief's guidance that recent-era taste matters more
than the 2011-2015 catch-up period.

**Recent-era anchors (4-5★, 2019-2026 films, used to drive TMDB
recommendations/keyword searches):**
- 一战再战 One Battle After Another (2025, 4.0) — PTA, crime/political
- 走走停停 (2024, 4.5), 好东西/Her Story (2024, 4.0) — Chinese dramedy
- 哪吒之魔童闹海 (2025, 4.0), 流浪地球2 (2023, 4.0) — Chinese blockbuster (good execution)
- 周处除三害 (2023, 4.0) — Taiwan crime
- 奥本海默 Oppenheimer (2023, 5.0), 瞬息全宇宙 EEAAO (2022, 5.0)
- 机器人之梦 Robot Dreams (2023, 5.0)
- 犯罪都市/犯罪都市2 (2017/2022, 4.0 both), 无双 (2018, 4.0) — Asian crime-action
- 极速车王 Ford v Ferrari (2019, 5.0), 壮志凌云2 Top Gun: Maverick (2022, 4.0) — racing/veteran-mentor
- 火星救援 The Martian (2015, 4.0), 星际穿越 Interstellar (2014, 4.0) — hard sci-fi
- 利刃出鞘 Knives Out (2019, 4.0), 真相捕捉/The Capture (2019 s1, 5.0) — whodunit
- 罗小黑战记 (2019, 5.0), 雄狮少年 (2021, 4.0), 百变狸猫 (1994, 5.0) — Chinese/Japanese animation
- 绅士们 The Gentlemen (2019, 5.0) — crime-comedy caper
- 白头神探 The Naked Gun (1988, 4.0) — spoof comedy anchor

**Anti-anchors (2★ and below, or explicit hard rules from TASTE.md):**
- Transformers franchise: 变形金刚4 (1.0, his joint-lowest score in the whole
  history), 变形金刚2 (2.0), 变形金刚 (2.0) — a documented franchise-level
  aversion, not a one-off.
- 恐怖片 (horror) — explicit hard "don't recommend" (Q8 in TASTE.md).
- 说教/政治正确挂帅/自我感动/强行升华 (preachiness, forced uplift/sublimation) —
  hard red line, named with 豆瓣's "田园女权和强装深沉和升华主题的高分" as the
  thing he specifically distrusts.
- 角色降智 (character stupidity driving plot), 拖沓注水 (dragging/padding),
  做作/尬演 (amateurish/awkward acting as a craft failure, not as intentional
  device) — all hard red lines.
- Named person-vetoes: 杜汶泽 (political), 杨幂, 黄晓明, 郭敬明 — none of these
  appeared in this sweep's candidate pool, so no dossier was affected.

**Shells channel (§2/§3 first-class channel):** the snapshot's 222 shells
include 150 films, checked in full. Under the "recent" interpretation this
channel yielded **zero usable candidates** — the newest film shells are from
2023 (Poor Things, Perfect Days, Smoking Causes Coughing, The Roundup: No Way
Out, Aftersun), all pre-dating even the loosest 2024-09 recency cutoff used
here. This is stated honestly rather than silently dropped: shells are a
strong channel for open-ended asks but structurally cannot answer a
recency-gated ask, since his Plex library was populated over years and nothing
in it is a 2024-2026 release. Noted as a real finding, not a channel failure.

## 2. Sweep — channels and yields

**a. Anchor expansion (TMDB `/movie/{id}/recommendations`, filtered to
`release_date >= 2024-06-01`)** run against: One Battle After Another,
Oppenheimer, Dune: Part Two, EEAAO, Poor Things, Ne Zha 2, 周处除三害, The
Roundup, Robot Dreams, Guardians of the Galaxy Vol. 3, Spider-Verse. Yield:
~14 recent titles, incl. She Rides Shotgun, 1992, Caught Stealing, Nuremberg,
The Legend of Hei 2 (直接命中 — sequel to a 5★ anchor), Wallace & Gromit:
Vengeance Most Fowl (already rated, excluded), Superman (already rated,
excluded), Transformers One (surfaced but flagged as anti-anchor franchise).

**b. Generated queries — TMDB discover, genre-combination
(`primary_release_date.gte=2024-09-01`, `.lte=2026-08-23`, `vote_count.gte`
tuned per genre)**: Crime+Action (49 total, 20 pulled), Chinese-language Drama
(23 total), Animation (38 total), Sci-Fi (74 total), Chinese-language Comedy
(12 total), Thriller+Mystery (27 total). Yield: the bulk of the gathered pool
— ~35 distinct new titles after removing already-rated/franchise duplicates
(Zootopia 2, The Wild Robot, Superman, Captain America: Brave New World,
唐探1900, 戏台, Fantastic Four: First Steps all appeared here and were
excluded as already-rated per §2, not re-logged as Cut1 eliminations).

**c. Review mining — tiered by language, per §3c**:
- English-language finalists: TMDB `/movie/{id}/reviews` — 100% coverage in
  the sample pulled (Project Hail Mary 26 reviews, Wake Up Dead Man 6, Black
  Bag 7, F1 9). Substantive, quotable, Tier 1.
- Chinese-language finalists: NeoDB `/api/catalog/search` → uuid →
  `/api/item/{uuid}/posts/?type=review` → `/api/review/{uuid}`. Hit rate on
  the 4 Chinese finalists checked: 2/4 had a genuine full-length review
  (浪浪山小妖怪, 罗小黑战记2 — both Tier 1), 2/4 had zero review posts
  (南京照相馆, 捕风追影 — confirmed genuinely empty, not an endpoint bug: the
  movie-typed path `/api/movie/{uuid}/posts/` 404s for these ids, and both
  `urllib` and `curl` agree the item-typed path returns `count: 0`). For
  those 2, fell back to WebSearch `<title> 豆瓣 影评/评价` per §3c's documented
  fallback — got real attributable Douban aggregate-score + review-title
  signal (Tier 2), not a fabricated quote.
- Douban `new_search_subjects` was **not** used this run — SCOUT.md's own
  source notes mark it as good for exactly one call per session with a long
  backoff, and TMDB+NeoDB+WebSearch already covered the needed ground without
  spending that one shot.

**d. Editorial (WebSearch)**: `best films of 2025 so far critics list` (English)
and `2025年豆瓣高分电影推荐` (Chinese). Both returned real, current
aggregator/critic-list content and surfaced titles not found via TMDB discover
alone: Sinners, Marty Supreme, The Secret Agent, Black Bag, Wake Up Dead Man,
Sound of Falling (English, from Hollywood Reporter / IndieWire / CriticsTop10
aggregation); 南京照相馆, 罗小黑战记2, 浪浪山小妖怪, 捕风追影, 诡才之道, F1,
疯狂动物城2 (Chinese, from Douban's own 2025 year-end doulist coverage).

**e. Recency**: not run as a separate channel — channels a-d were already
date-filtered at the source (TMDB `primary_release_date.gte`), so this stage
folded into (b).

**Gathered pool total: 44 candidates** (28 Western/international, 16
Chinese/Asian). This is below the ~60-100 target stated in the brief — logged
honestly rather than padded. The shortfall is mostly structural: the ask's
strict recency gate collapses several normally-productive channels (shells,
as noted above, and anchor-expansion recommendations skew heavily toward
titles already released before an anchor, not after it), and the session was
time-boxed. The 44 gathered do cover every channel SCOUT.md names as working,
and the eventual 8 dossiers are drawn from real breadth (crime, sci-fi,
mystery, spy-thriller, racing drama, war drama, 2x animation) rather than
one lucky vein.

## 3. Cut 1 — metadata only (44 → 27)

- OUT In Cold Light (2026): vote_count 44, too thin to assess against the
  profile with any confidence in the time available.
- OUT All the Devils Are Here (2025): vote_count 87, ambiguous genre-tag soup
  ([Thriller, Crime, Mystery]), no findable identity signal beyond bare
  metadata.
- OUT The World Will Tremble (2025): vote_count 112; redundant war-drama slot
  already covered more strongly by Nuremberg and 南京照相馆.
- OUT Sinners (2025): horror-vampire genre core. Hard rule: "恐怖片：明确不喜欢，
  不要推荐" (TASTE.md Q8) — cut despite excellent critical reception, because
  the rule is absolute, not a soft preference.
- OUT Transformers One (2024): Transformers is a documented anti-anchor
  (变形金刚4 1.0★ — his joint-lowest score in the whole history; 变形金刚2 2.0★;
  变形金刚 2.0★). Franchise-level aversion outweighs this entry's individually
  better reviews.
- OUT Caddo Lake (2024): supernatural-mystery, Shyamalan-produced, marketed
  with horror beats — overlaps the horror hard-rule risk.
- OUT 诡才之道/鬼才之道 (2024/2025): confirmed via WebSearch to be reviewed as
  genuine horror-comedy ("真吓人，真好笑，真感人") — overlaps the horror hard
  rule despite otherwise good reception.
- OUT Den of Thieves 2: Pantera (2025): redundant heist-crime slot, weaker
  signal (6.6/850) than the crime candidates carried forward.
- OUT Ballerina (2025): John Wick spinoff; the JW franchise itself is only a
  3★ (unenthusiastic) anchor for him, and the spinoff had a notably poor
  theatrical run — thin upside for a franchise he was never enthusiastic about.
- OUT Toy Story 5 (2026): redundant animation slot; his Toy Story ratings are
  solid-not-rapturous and trending down (TS2 4.0, TS3 4.0, TS4 3.0) — no
  found reason this entry beats the two Chinese animation picks already ahead
  of it in signal strength.
- OUT Demon Slayer: Infinity Castle (2025): mid-franchise anime film requiring
  cumulative context; no anchor for this specific series anywhere in his
  1702-work history.
- OUT Chainsaw Man: Reze Arc (2025): same reason — mid-arc anime film, no
  anchor.
- OUT Predator: Badlands (2025): redundant sci-fi-action slot against Project
  Hail Mary, which has a direct Andy Weir/Martian analogue; no comparable
  anchor for Predator anywhere in his history.
- OUT 熊猫计划 Panda Plan (2024): verified via WebSearch — Douban settled at
  5.5/38k+ ratings, reported as thin/formulaic even by its own coverage.
  Documented poor reception, not assumed.
- OUT 射雕英雄传：侠之大者 (2025): verified via WebSearch — Douban 5.5/330k+,
  reported as "2025春节档最差口碑", cast and CGI-heavy departure from source
  widely panned. Documented poor reception, not assumed.
- OUT 星河入梦 Per Aspera Ad Astra (2026): verified via WebSearch — Douban
  settled ~6.9, "narrative structure" criticized, idol-cast sci-fi-romance
  register with no anchor anywhere in his history. Thin/mixed, cut.
- OUT 猎狐·行动 Fox Hunt (2025): vote_count 33, too thin to assess in the time
  available.

**Survivors: 27.**

## 4. Cut 2 — light evidence pulled, narrowed to the 8 dossiered (27 → 8)

Light evidence (TMDB vote_average/vote_count + a skim of aggregate signal)
was pulled for all 27 survivors before this cut, per §4. The 19 below were
cut with the evidence in hand, not blind:

- OUT She Rides Shotgun (2025, TMDB 7.0/323): decent modest-scale genre
  thriller (Taron Egerton); cut for pool-size discipline — the crime-thriller
  register is already carried by 捕风追影 and Wake Up Dead Man with stronger
  evidence trails found in the time available.
- OUT 1992 (2024, TMDB 6.9/231): LA-riots heist premise is interesting but the
  evidence trail found was thinner than the picks kept; redundant crime slot.
- OUT Caught Stealing (2025, TMDB 6.8/1102, Aronofsky): comparable or even
  slightly higher raw score than Black Bag, but cut for redundancy in the
  "director-pedigree crime/thriller" register that Black Bag and 捕风追影
  already cover with Tier-1/Tier-2 evidence in hand; this is a pool-size call,
  not a quality judgment.
- OUT Nuremberg (2025, TMDB 7.6/1355, Russell Crowe/Rami Malek): genuinely
  strong prestige historical-legal drama, but redundant heavy-history slot
  against 南京照相馆, which is both more evidenced (Douban 8.8 vs. TMDB's
  smaller sample) and more directly recent/relevant. Flagged as the strongest
  alternate cut in this batch.
- OUT It Was Just an Accident (2025, Jafar Panahi, Palme d'Or 2025): a real,
  well-supported taste-fit exists (一次别离/A Separation, 4.0★, is a genuine
  Iranian-cinema anchor) — this was a close call, cut for pool-size discipline
  once the 8 slots filled with a different genre mix, not for any quality or
  fit defect found.
- OUT The Housemaid (2025, TMDB 7.3/2912): broad Blumhouse-adjacent thriller;
  no distinct pedigree signal found beyond decent aggregate numbers; cut for
  genre redundancy against Black Bag/Wake Up Dead Man.
- OUT Marty Supreme (2025, TMDB 7.4/2103, Josh Safdie): interesting pedigree,
  but no direct anchor found in his history for its specific
  obsessive-underdog-competitive register; cut for pool-size discipline.
- OUT The Secret Agent (2025, TMDB 7.2/824, Cannes Best Director+Actor):
  genuinely strong Brazilian political thriller, but Portuguese-language
  festival arthouse sits outside any measured anchor in his history; cut for
  pool-size discipline against the mystery/thriller/spy registers already
  covered by Black Bag and Wake Up Dead Man.
- OUT Sound of Falling (2025, Cannes Jury Prize, German): slow-cinema family
  drama; no anchor found for German festival slow cinema specifically; cut for
  pool-size discipline.
- OUT KPop Demon Hunters (2025, TMDB 8.0/3132): hugely acclaimed animated
  musical, but no anchor anywhere in his history for K-pop-adjacent content,
  and the animation slot is already filled twice (浪浪山小妖怪, 罗小黑战记2);
  cut for redundancy plus a genuinely weak taste-fit signal beyond "well made."
- OUT The Naked Gun (2025, TMDB 6.35/1915): has a real direct anchor (原版
  白头神探 4.0★), but his recent 4-5★ live-action Western films skew toward
  serious craft/prestige rather than spoof-parody; cut for pool-size
  discipline, flagged as a legitimate alternate.
- OUT Havoc (2025, Gareth Evans/Tom Hardy): his action-crime taste runs
  through polished genre craft, but press coverage found for this one skewed
  toward "style over substance" more than 捕风追影's aggregate signal; cut for
  pool-size discipline.
- OUT 雄狮少年2 (2024): direct anchor (雄狮少年 4.0★) — genuinely strong, but
  the animation slot is already filled twice; cut for redundancy, flagged as
  a strong alternate.
- OUT 左撇子女孩 Left-Handed Girl (2025, Sean Baker produced, Cannes
  Directors' Fortnight): genuinely acclaimed, but no anchor found for Taiwan
  indie coming-of-age specifically; cut for pool-size discipline.
- OUT 风流一代 Caught by the Tides (2024, Jia Zhangke, Cannes competition):
  genuine arthouse pedigree, but assembled from ~20 years of archival footage
  into a deliberately loose, essayistic structure — risks his explicit hard
  rule against dragging/padding (拖沓，注水，太长); cut for genre-pacing risk.
- OUT 一部未完成的电影 An Unfinished Film (2024, Lou Ye): genuine arthouse
  pedigree but a heavily restricted/censored release with a thin verifiable
  evidence trail found in the time available; cut for evidence-thinness plus
  pool-size discipline.
- OUT 东极岛 Dongji Rescue (2025, TMDB 8.3/64 — thin sample): war-action,
  redundant against 南京照相馆's WWII-history slot; also his recent big-cast
  Chinese blockbuster ratings have run middling (长安的荔枝 2.0, 唐探1900 3.0),
  an unproven register; cut for redundancy plus genre risk.
- OUT 镖人：风起大漠 Blades of the Guardians (2026): animated wuxia; animation
  slot already filled twice; wuxia adaptations in his history are mixed at
  best (射雕英雄传之东成西就 3.0, a comedy spoof not a serious analogue); cut
  for redundancy.
- OUT 小小的我 Big World (2024, Yi Yangqianxi, disability drama): decent
  reception, but the "inspirational uplift" register risks his explicit hard
  rule against self-congratulatory forced sublimation (自我感动、强行升华); cut
  for genre-tone risk.

**Survivors / dossiered: 8.**

## 5. Final 8 dossiers

Written to `scratchpad/runB/dossiers.json`. Titles, in dossier order:

1. **南京照相馆** (Dead to Rights, 2025) — war/historical drama — evidence_tier 2
2. **浪浪山小妖怪** (Nobody, 2025) — animation — evidence_tier 1
3. **罗小黑战记2** (The Legend of Hei 2, 2025) — animation — evidence_tier 1
4. **捕风追影** (The Shadow's Edge, 2025) — crime-action — evidence_tier 2
5. **Project Hail Mary** (2026) — sci-fi — evidence_tier 1
6. **Wake Up Dead Man: A Knives Out Mystery** (2025) — mystery — evidence_tier 1
7. **Black Bag** (2025) — spy thriller — evidence_tier 1
8. **F1** (2025) — racing drama — evidence_tier 1

Full dossier objects (identical to `dossiers.json`) are below for the audit
record.

```json
SEE scratchpad/runB/dossiers.json — omitted here verbatim to avoid drift
between two copies; that file is the source of truth and was written in the
same session immediately before this log entry.
```

## 6. Places SCOUT.md was ambiguous or hard to follow

- **"~60-100 gathered" target vs. a recency-gated ask.** SCOUT.md's sweep
  target assumes an open-ended ask where every channel (including shells) is
  productive. A strict recency gate structurally starves the shells channel
  (his Plex library predates the window entirely) and narrows anchor-expansion
  recommendations (a film's `/recommendations` list skews toward titles
  released *before* it, not after). Landed at 44 gathered, honestly logged
  short of the target rather than padded with weak filler. Worth a note in
  SCOUT.md's own guidance that recency-gated asks should expect a smaller
  gathered pool and that this is not evidence of an under-run sweep.
- **NeoDB endpoint shape for films vs. TV.** Confirmed during this run (and
  cross-checked against a parallel smoke-test's mid-run tip) that
  `/api/item/{uuid}/posts/?type=review` is correct for films, while
  `/api/movie/{uuid}/posts/` 404s — the reverse of what the tip warned about
  for TV seasons. Both `urllib` (Python) and `curl` agreed on `count: 0` for
  the two Chinese titles that returned no reviews, so this is a genuine
  finding, not an endpoint-access bug. Worth adding to SCOUT.md's Source
  notes as a positive confirmation for the film-specific endpoint shape.
- **§4's "log ~40 / ~12" stage-size language reads as an absolute scale**
  even though the surrounding text calls them targets, not laws. With a
  44-item gathered pool the proportional equivalents (~18 and ~13) were used
  instead of the literal numbers; this required a judgment call the document
  could make explicit with a "scale to your actual gathered size" note.
- **No ambiguity found in the dossier schema itself** (§5) — the
  evidence_tier rule (best tier present, not worst or average) was
  unambiguous and applied literally throughout.
