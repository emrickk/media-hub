# recommend/ — instance bindings (user #1)

The engine is SCOUT.md + CRITIC.md (user-agnostic; spec Part A). This
file binds the engine to its first instance. A second user would get a
different README and profile — nothing else changes.

All commands and paths in this document assume the working directory is
the `media-hub` repo root.

- **Profile document:** `TASTE.md` (calibrated 2026-07-28; the spec's
  Part B schema in prose form). Rating semantics: 3★＝一般还行,
  4★＝挺好看值得, 5★＝情绪冲顶.
- **Pitch target: the 70th percentile of the candidate's cell,
  mid-rank convention.** A candidate survives the critic's
  predicted-rating check when its `predicted_percentile` reaches **70**
  within the cell it belongs to — see "Why a percentile, not a star
  floor" below for the measured ladders and why 70 rather than 80. This
  is the line the orchestrator copies verbatim into the critic's prompt,
  tie convention included.
- **Pitch cap: 5** (spec: pitch 2–5 survivors). Pass this to the critic
  with the pitch target; the critic ranks and marks which survivors fit
  the cap, and the orchestrator pitches that selection as given.
- **History DB:** `media.db` — kinds in scope: `film,tv,show,drama`.
- **Helpers:** `recommend/history.py` — `snapshot` (run BEFORE any
  network I/O), `index` (the critic's complete one-line-per-work map of
  the rated history), `distribution` (the shape of the whole rated scale
  plus its per-population cells), `cell` (one population's base rate,
  by `--kind` / `--year`), `percentile-of` (one candidate's mid-rank
  percentile within its cell, by `--kind` / `--year` / `--stars`),
  `lookup` (full detail incl. review text, by `--work-id` / `--title` /
  `--creator`, from the snapshot file alone), `sibling-seasons` (has the
  user already watched/wishlisted ANY OTHER season or the show-level
  parent of a TV candidate? — `--title`/`--year`/`--kind`/`--ext` for one
  candidate, or `--batch FILE` for a whole shortlist in one call; SCOUT.md
  §4 makes the batch form mandatory before dossiers); `recommend/reclog.py`
  (the only write surface for the `recommendations` log; init already
  applied).
- **Pool helpers (v2):** `recommend/pool.py` — `init` (create
  `candidate_pool`, idempotent), `upsert` (batch insert-or-merge
  candidates from a harvester's batch JSON), `query` (local, no-network
  filtered read — `--kind`/`--year-from`/`--year-to`/`--tag`/`--channel`,
  the last two repeatable and OR'd — the interactive scout's primary
  channel), `attach-evidence` (cache one candidate's fetched review
  evidence permanently), `suppress-sync` (mark rows watched/rejected
  since the last refresh; never deletes), `stats` (pool-wide counts).
  `recommend/harvest_tmdb.py` — `anchors` (DB read, no network),
  `fetch` (raw-first pull of `/recommendations` + recency `discover` +
  genre maps), `transform` (raw files → pool-upsert batch, no network).
  `recommend/harvest_douban.py` — the same three-stage shape, pulling
  Douban's mobile rexxar `/recommendations` CF block instead of TMDB's
  (verified endpoint shape in SCOUT.md's Source notes). Full detail in
  "Candidate pool bindings" below.

## Why a percentile, not a star floor

The pitch bar used to be an absolute "≥4★ enthusiasm threshold". On this
user's history that bar is close to meaningless:

- **4★ is his modal rating — 41.7% of 1,702 rated works** — and
  **60.5% of everything he has ever rated is ≥4★**. A bar of ≥4★ sits
  exactly on the mode and admits the majority outcome. A title drawn at
  random from his own history clears it three times in five, so "16/16
  survived at ≥4★" is not a strong slate; it is the base rate.
- **3★ (29.6% of his ratings — "fine, watchable, forgettable" in
  `TASTE.md`) was never used by the critic at all.** A predictor that
  cannot say the modal-adjacent middle is asserting, not predicting.
- **He behaves very differently across populations.** TV: 74% ≥4★ and
  31% five-star. Films released 2020–26: **44% ≥4★ and only 4%
  five-star**. An identical 4.0 prediction for a TV series and for a
  recent film is therefore two completely different claims wearing the
  same number — the first is roughly ordinary, the second is a strong
  bet. A single absolute floor cannot express that difference; a
  percentile target does it automatically, being lenient where he is
  generous and strict where he is cold.

Hence the positional target: the critic must argue that a candidate
beats a fixed share of the works this user has actually rated **in that
population** — a claim that stays equally demanding whether the cell is
his warm TV history or his cold recent-film history. Engine purity: the
number lives here, in the instance layer. `CRITIC.md` carries no number
and refers only to "the pitch target as given to you".

### The tie convention, and why the target is 70 and not 80

Star ratings are a coarse grid with huge ties — 671 of 1,609 rated works
sit on exactly 4.0 — so "what percentile is a 4★?" has no answer until
the tie convention is fixed. **We use the mid-rank (average-rank)
convention**: a star's percentile is `(count below + half the count
equal) / n`. Measured on the real snapshot:

```
film 2020-2026 (n=105)          tv/show, all years (n=498)
  3★   → 33.3                     3★   → 15.8
  4★   → 74.8   ← clears 70       4★   → 46.7   ← does NOT clear 70
  4.5★ → 94.8                     4.5★ → 68.3
  5★   → 98.1                     5★   → 84.4
```

That is exactly the behaviour we want, and it falls out of the data
rather than being imposed: **a 4★ recent film clears the bar and a 4★
series does not.** Only 43.8% of his 2020-26 films reach ≥4★ and just
3.8% reach 5★, so a 4★ there is genuinely notable. In series, 74.3%
reach ≥4★ and 31.1% earn a full 5, so an ordinary 4★ series is not worth
his time. The same predicted star means different things in different
populations, and the percentile is what expresses that. (The era cell
the critic actually receives for a recent series, `tv/show 2020-2026`,
n=142, gives 4★ → 54.9 — same conclusion, comfortably below 70.)

**At 80 the gate would be near-shut**: a film would need 4.5★ (94.8) and
a series a clear 5★ (84.4). Almost nothing would survive. 70 is the
setting where the populations separate on their own.

**The naive convention would silently re-open the gate.** Counting every
work at or below the star (`count ≤ star / n`) puts a 4★ film at **93.3**
and a 4★ series at **67.7** — the film sails through a target of 80 and
the series nearly clears 70, which is the "everything predicts 4.0 and
everything survives" failure all over again. Mid-rank is not a detail;
it is the mechanism. **Compute `predicted_percentile` from the cell's
`histogram` under mid-rank.** The cell's `percentiles` map runs the other
direction (star-at-percentile) and does **not** use mid-rank — for
`tv/show 2020-2026` it reports `"70": 4.0`, which read as a gate would
pass the very 4★ series mid-rank correctly rejects at 54.9. Treat
`percentiles` as orientation, never as the survive/kill test.

**Expected consequence — this inverts the previous run's slate.** The
16-candidate run that motivated this rework predicted 4.0/4.5 across the
board and killed nothing. Under this rule its 4.0-predicted *series* stop
qualifying while its 4.0-predicted *recent films* still do. That flip is
the intended correction, not a regression to investigate.

Recalibration: these figures come from
`python3 recommend/history.py distribution --snapshot <snap.json>` and
`... cell --kind <k> --year <y>` (run the snapshot into a scratchpad, not
the repo). Re-read them when the history grows materially, and move the
target here (not in `CRITIC.md`) if the shape shifts.

### `p_top` — retained, scoring deferred

The critic emits `p_top` per candidate, but nothing scores it yet:
`reclog.py stats` / `sealed_vs_actual` only pairs `predicted_stars`
against the user's eventual rating. `p_top` is **not** a column on
`recommendations`; it is preserved verbatim inside the row's `dossier`
column under the `critic` key, alongside `predicted_percentile`,
`base_rate_argument`, and the ranking fields, and is recoverable by
query from there. Designing a scoring method for it is deliberately
deferred — no schema change until there is one.

## Candidate pool bindings (v2)

- **Table:** `candidate_pool` in `media.db` — one row per not-yet-watched
  candidate; provenance-carrying, non-destructive (rows are suppressed,
  never deleted). Schema, dedup keys, and the merge rules are documented
  in `pool.py --help` — read it rather than re-deriving the contract
  from memory; it is the authority, this bullet list is not.
- **Raw dirs (raw-first, per house rule):**
  `recommend/raw/tmdb/<YYYY-MM-DD>/` and
  `recommend/raw/douban/<YYYY-MM-DD>/`. Every harvester response lands
  here, verbatim, before any transformation — `harvest_tmdb.py fetch` /
  `harvest_douban.py fetch` do this automatically; `transform` never
  touches the network and depends entirely on these saved files.
- **Refresh cadence: monthly**, riding the digest run (SKILL.md step 0).
  No standing scheduled-pipeline wiring exists for this yet — that is a
  separate, explicit-approval-required change per HANDOFF.md §8. Between
  monthly refreshes, an interactive ask's tier-2 top-up (SCOUT.md §3) is
  the only thing that can add new pool rows, and it logs what it added
  as a pool gap for the next monthly refresh to cover properly.
- **Budgets:**
  - TMDB harvest: 2 pages per anchor's `/recommendations`
    (`harvest_tmdb.py fetch --pages`, default 2), recency `discover`
    window 18 months (`--recency-months`, default 18) — override either
    only with a stated reason.
  - Douban harvest: `--budget` newly-attempted anchors per session
    (default 40), `--delay-min`/`--delay-max` jittered 5–10s between
    requests, 8 consecutive non-block failures trips the circuit
    breaker, an HTTP 403/redirect-to-challenge trips an immediate block
    stop. All three are findings to report on completion, not crashes —
    the run still exits 0.
  - Interactive sweep: ~10 network calls total (SCOUT.md "Run modes"),
    almost all of it evidence fetching for the shortlisted candidates'
    pool-cache gaps, not candidate generation (that's the local pool
    query).
- **Mode split** (full detail in SCOUT.md's "Run modes" section):
  **interactive** is pool-first — local pool query, cached-evidence-first,
  no auto-resweep (a thin slate is reported honestly and the user is
  offered a deeper pass, never silently topped up); **digest**
  harvests/refreshes the pool first (SKILL.md step 0), then runs the
  full v1-shaped deep funnel with auto-resweep allowed. Both modes
  converge at the critic, which cannot tell which mode produced its
  dossiers.

## Profile grading — the engine expects structure this profile lacks

CRITIC.md asks the critic to answer each profile entry's **discriminating
question** and to treat **low-confidence entries** as stated risks rather
than kills. `TASTE.md` today is prose: it has no labeled discriminating
questions and no per-entry confidence grades, so read literally that
machinery can never fire and every entry reads as a hard rule — the
"labels not case law" failure the spec forbids. Restructuring the profile
into the Part B schema is deliberately deferred, not forgotten. Until it
lands, grade entries by what the prose itself says:

- An entry the profile states as **confirmed / calibrated / observed
  repeatedly**, with named exemplars on both sides → treat as a
  **calibrated** entry: its discriminating question is the distinction
  the exemplars actually draw, and it may carry a kill.
- An entry the profile marks as **partial, unanswered, tentative,
  "probably", "needs more data", or open** → treat as **provisional**:
  it fires as a stated risk in the survivor annotation, never as a
  silent kill.
- An entry with no exemplars and no hedge either way → provisional. The
  safe default is a stated risk, because a wrongly-killed candidate is
  invisible to the user while a wrongly-flagged one is not.
- Only the entries the profile itself frames as absolute (its hard
  constraints) are hard constraints.

## Policy: all recommendations are external — library is never a source

**Standing policy (2026-08-23), not a temporary tuning choice: every
candidate this system pitches comes from outside the user's own
library.** Candidates originate only from `candidate_pool` (harvested
from TMDB and Douban) and, when the pool is thin for a given ask, a
targeted live fetch from those same external sources — never from
`shells` or any other library-derived surface. The reason: the purpose
of a recommendation is discovery, and a title already sitting in the
library, watched or not, is not a discovery. This was set after a live
run surfaced 5 candidates, 4 of which were already in the library, and
the user rejected the slate outright on exactly this ground. Library
presence is never a pitch slot; at most it is a note on a candidate
that arrived from an external source and happens to coincide (see
"Shells and their ids" below). SCOUT.md §3's channel hierarchy encodes
this — it has no library/shells tier.

## Shells and their ids

`shells` (works with no watch/wish record — 222 at last count) are
**context and deduplication only, per SCOUT.md §2 — never a retrieval
channel**, per the policy above. Two uses remain: (1) noting "you
already have this" when an externally-sourced candidate happens to
already be a shell, and (2) taste context (an acquisition is a signal
about this user's taste, fair evidence when judging a pool candidate,
never grounds to originate one). The snapshot carries the
`external_ids` `media.db` already holds for them, and coverage is
currently **complete — all 222 carry at least one id** (216 imdb, 160
`plex_guid`, 147 tmdb_movie, 71 tmdb_tv; per-namespace coverage is
partial, per-entry coverage is not). Use them directly for the dedup
match: they were verified at source when they were loaded, so reading
them is reading stored data, not recalling an id from memory. A future
shell could still arrive with an empty `external_ids`, and that one
gets resolved at source like any other newly-found candidate.
- **Funnel logs:** `recommend/logs/<YYYY-MM-DD>-<slug>.md`, one per
  session.
- **Digest ask:** `recommend/DIGEST-INTENT.md`.
- **Keys:** TMDB_API_KEY in `../douban-export/sources/sources.env`.
- **Write ritual (before a session's first media.db write):**
  `lsof media.db*` (no other writer) → check STATE.md lanes →
  `sqlite3 media.db "PRAGMA wal_checkpoint(TRUNCATE);"` →
  `cp media.db backups/media-recommend-$(date +%Y%m%d-%H%M%S).db`.
- **Verdict flow:** `interested` rows go to the wishlist only with the
  user's explicit confirmation, via `mediahub.py add` — never silently.
- **Spec:** `docs/superpowers/specs/2026-08-23-media-recommend-design.md`
  (v1) amended by
  `docs/superpowers/specs/2026-08-23-media-recommend-v2-pool-design.md`
  (v2 — candidate pool, harvesters, run modes; wins on conflict).
