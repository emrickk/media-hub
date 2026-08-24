# Media Recommend v2 — candidate pool & platform-CF design

**Date:** 2026-08-23 · **Status:** draft for Anping's review
**Amends:** `2026-08-23-media-recommend-design.md` (v1). Part A's judgment
layer (blind critic, percentile calibration, case law, evidence tiers,
logging) is **unchanged**. This spec restructures candidate GENERATION and
run ECONOMICS. Where the two conflict, this document wins.

## 1. Why v2 (findings from calibration session #1)

1. **Per-ask sweeping re-derives a static corpus.** Scout runs cost 13–16
   min / 50–75 tool calls each; ~80% of that is sequential per-candidate
   review fetching, much of it for candidates the critic then kills. The
   inputs (anchor neighborhoods, review text) change on a monthly-or-slower
   clock; the system re-fetched them per ask.
2. **The re-sweep loop is economically indefensible interactively.** A
   70th-percentile gate passes ~30% by construction; 8 dossiers ⇒ ~2.4
   expected survivors vs a floor of 2. Shortfalls are routine, and each
   costs another 15–20 min for one or two more titles.
3. **Candidate generation half-reinvents recsys.** LLM-generated keyword
   queries are the measured-weakest surface; TMDB `/recommendations` is the
   measured-strongest; Douban's own 「喜欢这部电影的人也喜欢」 CF — computed
   over the population closest to the user's taste — was never touched.
   Per-ask sweeps hand-pick ~7 of ~309 available anchors (2% of the free CF
   signal).
4. **The system's real advantages** (knowing the user, statistics over
   their history, reading evidence, adversarial critique, asking questions)
   are the LLM layer. Generation is commodity; judgment is the moat.

## 2. Architecture: three layers

```
LAYER 1 — GENERATION (platforms' CF; harvested, cached, refreshed monthly)
  TMDB /recommendations across ALL anchors (films: 138/145 tmdb-ready)
  Douban subject-page 也喜欢 across Chinese anchors (TV: 162/162 douban-
    ready — this is the ONLY CF surface for the TV lane)
  TMDB discover (genre-combination + recency window)
  Library shells (owned, unwatched)
        ▼  upsert into
  ┌────────────────────────────────────────────────┐
  │ candidate_pool (media.db)                       │
  │ one row per candidate: ids, tags, aggregates,   │
  │ provenance (which anchor/channel), shape,       │
  │ CACHED EVIDENCE (lazy, fetched once, kept)      │
  └────────────────────────────────────────────────┘
LAYER 2 — FILTER (deterministic; already built in v1)
  dedup vs history/rec-log · cells & base rates · mid-rank percentiles ·
  70th-percentile gate
LAYER 3 — JUDGMENT (LLM; already built in v1, one addition)
  open-ended ask interpretation · CLARIFYING QUESTION when the ask
  materially splits · blind critic · case-law prediction · pitch ·
  verdict loop
```

## 3. The `candidate_pool` table

One row per candidate work not yet watched. Columns: `kind`, `title`,
`original_title`, `year`, `external_ids` (JSON, verified), `tags` (JSON:
genres/keywords), `aggregates` (JSON: tmdb_vote/votes, douban rating when
seen), `shape` (JSON), `sources` (JSON provenance list — each entry names
the channel, the anchor work_id it came from, and the fetch date),
`evidence` (JSON, NULL until first fetched — then cached permanently),
`evidence_fetched_at`, `suppressed` (0/1 — set when watched or verdict
'no'; never deleted), timestamps. Dedup at upsert: match by any shared
external id first, else (kind, title, year); merges append provenance
rather than duplicating rows. Non-destructive always.

Expected scale: ~309 anchors × ~15–20 CF neighbors, deduped ⇒ roughly
2,000–4,000 rows. A thin, provenance-carrying slice of the platforms —
not a mirror.

## 4. Harvesting (raw-first, rate-disciplined)

- **TMDB:** for every anchor bearing a tmdb id: `/movie|tv/{id}/recommendations`
  (2 pages). Plus a recency pass: `discover` over the trailing ~18 months
  with a vote floor. Responses land as dated immutable snapshots under
  `recommend/raw/tmdb/<date>/` before any transformation (house raw-first
  rule). Cheap: pure JSON, no review fetching at harvest time.
- **Douban 也喜欢:** for every Chinese anchor (douban id): fetch the
  subject page with the existing douban-export curl-cffi pattern and
  parse the recommendations block. Discipline: randomized 5–10s+ delays,
  resumable checkpoint, raw HTML snapshots to `recommend/raw/douban/<date>/`,
  bounded per-session page budget. ~310 pages ⇒ one slow bootstrap
  (≈45–90 min, unattended) then only new-anchor increments monthly.
  Markup is parsed from a freshly fetched page, never assumed.
- **Evidence** (reviews) is NOT harvested. It is fetched lazily the first
  time a candidate reaches any ask's shortlist, then written back to the
  pool row and never fetched again.
- **Refresh cadence:** monthly, riding the existing scheduled pipeline —
  new anchors' neighborhoods, recency window, shells sync, suppression of
  newly watched titles. (Wiring into the scheduled task itself is a
  standing-automation change and happens only with Anping's explicit
  approval.)

## 5. Run modes

**Interactive ask (the default, target ≤5 min):**
1. Interpret ask. **If it admits two materially different readings and the
   choice would change most of the slate — ask ONE question first.** (v1
   permitted this; v2 requires the check every run and logs the decision.)
2. History snapshot (unchanged) + pool query (local, no network).
3. Shortlist from the pool knowing the bar: the scout receives the
   percentile target and each candidate's cell, and shortlists only
   candidates it can argue past the gate — no more shipping 4★-series
   candidates into a 70th-percentile wall.
4. Evidence: read cached; fetch only what's missing (typically ≤10 calls);
   write fetched evidence back to the pool.
5. Critic (unchanged, blind, calibrated). **No automatic re-sweep**: a
   thin slate is reported honestly with the offer to go deeper; the user
   opts in.
6. Pitch, verdicts, rec-log (unchanged).
Targeted top-up: if the pool genuinely lacks the ask's territory (a niche
ask), one narrow TMDB/Douban fetch for that ask, logged as a pool gap so
the next refresh covers it.

**Digest (monthly, unattended):** harvest/refresh first, then the deep
run — full funnel, auto re-sweep allowed, web-search editorial pass
allowed (its one proven niche: recent Chinese-cinema recency, where TMDB
discover is weak and Douban rate-limits).

**Web search elsewhere: removed.** Not an interactive channel, not an
evidence tier source ahead of cached NeoDB/TMDB review text.

## 6. What explicitly does NOT change

Blind critic contract & inputs · percentile gate, mid-rank convention,
cells (`history.py distribution/cell/percentile-of`) · evidence tier
semantics and confidence caps · case-law reasoning & profile handling ·
`recommendations` log schema, sealed predictions, one-row-per-candidate ·
funnel logging discipline · all house DB rules (one writer, backup ritual,
raw-first, non-destructive, verify-ids-at-source, Chinese-first identity).

## 7. Consequences & measures

- Interactive latency: ~20–35 min → target ≤5 min (pool-first, lazy
  cached evidence, no auto-resweep).
- Anchor coverage for generation: ~2% → 100% of ≥4.5★ anchors.
- The TV lane gains its first real CF signal (Douban 也喜欢).
- Pool health becomes reportable: size, coverage by kind/era, evidence
  cache hit rate, gap log. The digest reports it monthly.

## 8. Open questions

- Whether to enrich TV anchors with tmdb_tv ids via NeoDB cross-references
  (would add TMDB CF to the TV lane too) — nice-to-have, not v2-blocking.
- Trakt.tv as an additional TV CF source (needs a free API key from
  Anping) — deferred unless Douban 也喜欢 under-delivers for TV.
- Pool staleness policy beyond monthly (e.g. explicit `refresh` command
  before a big ask) — start with monthly + manual, revisit with data.
