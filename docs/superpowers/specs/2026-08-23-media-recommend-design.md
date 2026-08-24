# Media Recommend — design spec

**Date:** 2026-08-23 (rev 2: engine/profile separation) · **Status:** draft for Anping's review
**Scope v1:** film/TV only; single user instance (Anping), engine designed user-agnostic
**Depends on:** `media-hub/media.db` (canonical store, read + one new table), `media-hub/TASTE.md` (profile instance #1)

## 0. Structure of this spec

The system is three separable things, specified in that order:

- **Part A — Engine**: the pipeline. Contains **zero user-specific facts**.
  Everything about a particular person enters only through the two data
  interfaces: their **history** and their **profile**.
- **Part B — Profile schema**: the data contract between the engine and any
  user, plus the general procedure that produces and evolves a profile.
- **Part C — Instance #1**: how Anping's existing data (media.db, TASTE.md)
  maps onto A and B. All concrete examples live here and only here.

---

# Part A — Engine (user-agnostic)

## A1. Purpose

Given an open-ended stated intention from a user, find candidates from
external sources, and pass each through an adversarial critic that predicts
the user's own rating from their history and profile. Pitch only survivors.
Conversation-first (a Claude Code skill); digest mode is the same pipeline
on a schedule with a stored default ask.

## A2. Principles

1. **Open-ended intention.** The ask is interpreted as free text by the
   LLM. No intention taxonomy, no pre-identified axes of any kind (not
   genre, not scenario, not mood). The pitch states back its
   interpretation; that is the only schema.
2. **The user's history is the primary evidence base**, not a dedup list —
   used at both ends: to anchor retrieval (what "good X for this user"
   looks like in their own ratings and review text) and to ground the
   critic's prediction.
3. **The recommendation criterion is a predicted rating.** The critic asks:
   *given this user's rated history and review text, what would they rate
   this title?* Pitch iff the prediction clears the user's enthusiasm
   threshold — a value defined in their profile's rating semantics, not in
   the engine — unless the ask itself moves the bar (a user may explicitly
   ask for something bad, obscure, or outside their norms; the ask always
   wins).
4. **Taste knowledge is case law, not rules.** The engine never applies a
   profile entry as a label/verdict; it answers that entry's discriminating
   question with evidence and argues by analogy to the entry's exemplars.
5. **Other users' reviews are a first-class source** (e.g. Douban,
   Letterboxd, Rotten Tomatoes): read as text, both for discovery (reviews
   of anchor titles name neighbors) and for evaluation (review text is the
   evidence that answers discriminating questions). This is the LLM-only
   capability the system is built around.
6. **Every elimination has a written reason.** Each narrowing stage logs
   one-line reasons; the critic logs kills with rule + evidence. The funnel
   is auditable end to end — judgment-with-receipts, not a trained ranker.
7. **Internal heuristics never become reasons.** Retrieval may use any
   category/tag internally, but pitches argue the work itself (craft,
   structure, execution) in terms the profile marks as persuasive to this
   user; aggregate scores are never arguments.

## A3. Pipeline

```
/recommend <ask, verbatim>
   ▼
SCOUT
  1. Interpret ask (open-ended). If it materially splits two ways, ask ONE
     question; otherwise state the assumption in the pitch and proceed.
  2. History retrieval — ONE read snapshot BEFORE any network I/O:
     rated items + review text in the semantic neighborhood of the ask,
     the user's to-watch list, library presence, full rec log.
     Produces: a sharpened target picture + anchor titles.
     (Prior 'no'-verdict items are excluded here, not just at the critic.)
  3. Sweep — channels, any mix per ask:
       a. anchor expansion (similar-to APIs; creator threads from the
          user's top-rated)
       b. generated keyword/tag queries against source catalogs
       c. review mining (reviews of anchors naming neighbors)
       d. editorial/critic lists via web search
       e. recency (mostly digest mode)
  4. Progressive narrowing with progressive evidence:
       ~100–200 gathered
        → ~40  metadata-only cut, one-line logged reason per elimination
        → ~12  cut with light review evidence pulled for the 40
        → dossiers for the ~12 (deep review reading, ids verified at
          source — never from memory)
     Stage sizes are targets, not laws.
   ▼
CRITIC (fresh context, blind to the scout's search effort/transcript;
        sees ONLY: profile + history access + dossiers + dedup lists)
  Per candidate, in order (every kill logged with rule + evidence):
  1. Fact/identity check — ids resolve, shape facts consistent; an
     unverifiable central fact = kill (hallucination gate).
  2. Dedup — watched / prior-'no' / to-watch (to-watch → demoted to an
     "already on your list" note, not a pitch).
  3. Predicted rating — the core judgment (A2.3): predicted stars +
     confidence + evidence chain, argued by analogy to named rated items
     and their review text. Profile hard constraints are strong evidence
     toward the bottom of the user's scale, applied with their calibrated
     nuance via discriminating questions — never as standalone labels.
  4. Ask fit — mismatch with the stated ask kills regardless of quality.
  5. Reason quality — arguments the profile marks non-persuasive,
     aggregate-score-as-argument, or an evidence-free case = kill/send-back.
  6. Survivor annotation — residual risks + confidence grade.
  Floor rule: if <2 survive, do NOT lower the bar; return the kill report
  to the scout for one differently-angled re-sweep (max one), then pitch
  honestly with the real survivor count and why.
   ▼
PITCH: 2–5 survivors; the interpretation of the ask stated back; per
  candidate the craft case, evidence, prediction + confidence, residual
  risks.
   ▼
VERDICTS → recommendations log → profile evolution (Part B).
```

## A4. Dossier format (per finalist)

Verified external ids · shape facts (length/episodes/seasons/status) ·
the case for it in this user's persuasive terms · ask-fit claim · quoted
review evidence with sources · declared per-field confidence. Thin dossiers
are still submitted — killing is the critic's job, and kills are data.

## A5. Data model — `recommendations` table

| column | notes |
|---|---|
| `id` | pk |
| `session_date`, `intention` | timestamp + the ask verbatim |
| `media_type` | v1: film/TV (values aligned with media.db conventions) |
| `title`, `year`, `external_ids` | ids verified at source; JSON |
| `work_id` | FK → works when known, else NULL |
| `dossier` | JSON: evidence + case + critic risks + funnel-stage reasons |
| `predicted_rating`, `predicted_confidence` | sealed at pitch time |
| `critic_killed`, `kill_reason` | kills are logged too — calibration gold |
| `verdict` | `interested` / `no` / `meh` / `watched` / NULL |
| `verdict_note`, `verdict_date` | user's words if any |

Rules: never re-pitch `verdict='no'`; `interested` flows to the user's
to-watch list only with explicit confirmation; a later real watch record
closes the loop (predicted vs actual becomes measurable).

## A6. Digest mode

A scheduled task invoking the same skill with a stored default ask
(editable file). Same funnel, same critic, same log. No separate code path.

## A7. Failure modes & ops

- Flaky/unreachable sources: skip and report; every session ends with
  counts + a machine-readable skip/failure list.
- No silent bar-lowering anywhere; thin evidence is reported as thin.
- Only write surface: inserts/updates on `recommendations`. Never
  destructive.

## A8. Verification & metrics

- **Sealed predictions**: prediction + confidence logged at pitch time;
  later actual ratings give the accuracy metric.
- **Hit rate**: (interested + watched) / pitched, over time.
- **Methodology audits**: the funnel's logged reasons and kill reports are
  themselves reviewable deliverables; early sessions are calibration
  sessions where the user grades the reasoning, not just the picks.

---

# Part B — Profile schema & lifecycle (user-agnostic)

## B1. Schema

A profile is a versioned document per user:

1. **Rating semantics** — what each star level means *to this user*, and
   the **enthusiasm threshold** the engine pitches at (A2.3).
2. **Taste dimensions (case law)** — each entry:
   - *principle*, in the user's own words where possible
   - *exemplars on both sides*, with the user's actual verdicts
   - *discriminating question* the critic must answer with evidence
   - *confidence* (calibrated / provisional / hypothesized)
   Low-confidence entries fired against a candidate surface as stated
   risks in the pitch rather than silent kills.
3. **Hard constraints** — red lines and veto lists (people, subjects,
   formats). Still carry exemplars and nuance boundaries; a hard
   constraint is a case-law entry with maximal confidence, not a
   different mechanism.
4. **Persuasion profile** — which kinds of arguments the user accepts as
   reasons (e.g. craft/structure) and which are banned (e.g. category
   membership, aggregate scores). Used by scout (pitch writing) and
   critic (reason-quality check).
5. **Context defaults** — the user's habitual asks, if any, for digest
   mode and ambiguity resolution. Never constrains interpretation of an
   explicit ask.
6. **Data pointers** — where this user's history, review text, to-watch
   list, and rec log live.

## B2. Profile lifecycle

- **Bootstrap with history**: mine the history for candidate entries
  (rating clusters, review-text patterns) → hypothesis interview: the
  user judges each hypothesis (accurate / partly / wrong) → confirmed
  entries with exemplars form the initial profile.
- **Cold start (no history)**: short interview seeds provisional entries;
  everything starts low-confidence; verdict learning does the rest.
- **Evolution**: every mispredict — a verdict or later actual rating that
  contradicts a sealed prediction — becomes a new exemplar on one side of
  an entry. Exemplars accumulating against a principle trigger a
  recalibration conversation with the user. Entries can flip meaning
  (a red line can become a selling point in a subregion of its domain);
  the mechanism is exemplar accumulation + re-interview, never silent
  drift.
- **Recalibration cadence**: incremental after new ratings land; the
  profile records its own last-calibrated date and method.

---

# Part C — Instance #1 (Anping) and v1 build

## C1. Data mapping

- History: `media.db` douban-sourced ratings (film 1,066 / TV 477) +
  491 短评; to-watch = wishlist; library presence = Plex shells.
- Profile: `TASTE.md` (calibrated 2026-07-28, blind-tested) already
  contains most B1 sections in prose form: rating semantics (3★/4★/5★
  meanings → enthusiasm threshold ≥4★), case-law entries (e.g. 尴尬幽默:
  principle "失误还是手法", exemplars The Office 卖点-side vs 爱情公寓
  失误-side), hard constraints (说教/升华, 降智, 注水, horror, 人物否决
  名单), persuasion profile (craft arguments in; category reasons and
  豆瓣分数 banned), context defaults (下饭剧/飞机场景 as digest default).
- A light restructuring pass may make TASTE.md's implicit
  exemplar/discriminating-question structure explicit — shown to Anping
  as a diff before adoption; meaning never changed unilaterally.
- v1 does NOT build the cold-start path (B2) — it is specified so the
  engine is honest about what is engine vs instance; instance #1 always
  has history.

## C2. Project layout

```
media-hub/recommend/
  SCOUT.md          scout methodology (Part A §3 steps 1–4, full text)
  CRITIC.md         critic methodology + kill checklist (full text)
  DIGEST-INTENT.md  stored default ask (editable)
  README.md         cold-start pointer
.claude/skills/recommend/   thin skill entry point; methodology stays in
                            the readable contracts above
```

## C3. House rules that bind the build (from AI Space CLAUDE.md / ARCHITECTURE.md)

- One read snapshot before network I/O (builder rule); `lsof` + STATE.md
  lane check, WAL checkpoint + dated backup before a session's first
  write; small insert transactions; non-destructive always.
- External ids verified at source, never from memory.
- Chinese-first identity: douban_id + title + year is definitive; absence
  from IMDb/TMDB is a documented negative, not a failure.
- Session reports with counts + machine-readable skip lists.

## C4. Open questions / deferred

- **Tag-surface probe** (first implementation task): which retrieval
  surfaces (TMDB keyword/discover, Douban tag pages, NeoDB search, review
  mining) retrieve well for real asks; findings land in SCOUT.md.
- **Games lane**: deferred; needs its own B2 bootstrap (playtime ≠ love —
  signals require their own hypothesis interview).
- **Music/books lanes**: not considered.
- **Multi-user productization**: Part B makes it specifiable; not built.

---

## Amendment (2026-08-23): Part B lifecycle — feedback replaces interviews

Anping's direction after the first attempted recalibration, adopted as design:

1. **The profile document is not a co-edited artifact.** TASTE.md stays in the
   user's voice, edited only at the user's initiative. Repeated
   hypothesis-ratification interviews are discontinued: presenting a person
   with statistical claims about their own character produces rejection
   regardless of the numbers' validity, because outcome patterns are
   properties of the prediction problem, not of the person. ("Series decay"
   is television getting worse, honestly scored — not a disposition.)
2. **Calibration = the verdict loop, two tiers.** Light signal: the pitch
   verdict (interested / no / meh) — did the recommendation make them want to
   try it. Heavy signal: the post-watch rating scored against the sealed
   prediction. Both already flow through the `recommendations` log.
   Mispredictions update the ENGINE's model (priors, risk flags, channel
   weights) — never the profile document.
3. **Statistical patterns live in the engine layer as prediction priors**
   (cells, base rates, sequel/season risk flags), labeled as such. They are
   never presented to the user as claims about their taste. The B2
   "recalibration conversation" trigger is repointed accordingly: exemplar
   accumulation prompts an engine-prior update, and at most a *question* to
   the user (e.g. "why do you think these declined?"), never a claim to ratify.
4. **Self-understanding deliverables are a distinct genre**, produced only on
   request: written as a readable portrait grounded in the user's own words
   and ratings, with observations framed as curiosities and questions, not
   verdicts. A regression table is not a mirror.
