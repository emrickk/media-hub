# The recommend system as a general product — four-part architecture, audit, and design

**Date:** 2026-08-23 (late evening session)
**Status:** LEAN MVP IMPLEMENTED 2026-08-24. Chat history is read directly
by the coding agent into two local profile ledgers; the existing scout and
blind critic remain the judgment loop; enrichment and feedback ship in the
production HTML. Broader infrastructure in this document remains deferred.
**Prompted by (verbatim, the design-bearing core):**

> "We are building a general tool. I do not want you to over-index on what
> I told you specifically … not every user will do this. This pipeline
> should dive deeper, dig, get your own TASTE.md, and guide the user to
> give you more … The second thing is your own judgment call on how
> accurate this taste file is. And the [third] is the whole recommendation
> back-and-forth narrow-down critic system … and the [fourth] part is the
> entry point, the quote, the thing you give the users based on your
> understanding … If you are unsure about something, you can just ask —
> not necessarily every time, but when you think it's absolutely
> necessary."

**Standing assumption, stated so it can be corrected:** "general product"
is treated here as a *layering discipline* — every mechanism must work for
a hypothetical user #2 who never wrote a TASTE.md — not as a mandate to
build multi-tenant infrastructure. Single DB, single instance layer,
engine contracts that carry zero user facts. If actual multi-user
deployment is ever the goal, that is an infra project on top of this
design, not a change to it.

---

## 1. The four parts, named

| # | part | job | organ |
|---|------|-----|-------|
| 1 | **Understanding** | build and maintain the taste profile; guide the user to give more, without demanding it | PROFILER.md *(missing)* |
| 2 | **Self-knowledge** | the engine's own judgment of how accurate/complete its understanding is, and when that judgment says *ask* | coverage + attribution + ask policy *(fragments)* |
| 3 | **Judgment loop** | ask → scout → blind critic → pitch → verdict → prior update | SCOUT.md + CRITIC.md + reclog + calibrate *(built)* |
| 4 | **Delivery** | entry point, hooks, quotes — hand the user a way *into* the work, not just a title | enrichment spec *(designed, unimplemented)* |

The dependency order is 1 → 2 → 3 → 4 conceptually, but the build order
was 3 → 4 → (1, 2), because this instance started with a user who
hand-delivered Part 1. That is exactly the over-indexing risk: **the
current system works because its first user did Part 1's job for it.**

## 2. Audit — what exists, what is Anping-shaped, what is missing

Grounded in checks run 2026-08-23 against the actual files (not memory):

### Part 1 — Understanding: **the big gap**

| aspect | state | evidence |
|---|---|---|
| profile document exists | ✅ for user #1 | TASTE.md, 28 markers of verbatim user speech (原话/准/批注) |
| process that BUILT it | ❌ not an engine capability | the 2026-07-28 session (mine 22 hypotheses → verify one-by-one → write in his voice) was artisanal, unrecorded as procedure; grep for elicit/onboard/bootstrap machinery: **none found** |
| cold-start path for a history-only user | ❌ | nothing defines history → profile |
| cold-start path for a nothing user | ❌ | nothing |
| profile maintenance | ⚠️ aspiration only | TASTE.md says 「新观影落库后应增量再校准」; no defined trigger or procedure |
| governance (whose voice) | ✅ but instance-framed | "TASTE.md is his voice, never co-edited" — correct rule, currently written as an Anping fact rather than an engine principle |

### Part 2 — Self-knowledge: **fragments, no organ**

| aspect | state | evidence |
|---|---|---|
| per-prediction confidence | ✅ | `predicted_confidence` on every row |
| per-cell data density | ✅ | `low_n` flags, `fallback_used` in cell machinery |
| profile *coverage* model (where is the map blank) | ❌ | nothing represents "no evidence in this territory"; the critic improvises it per-candidate (Rear Window's "no Hitchcock ever rated" was ad hoc) |
| error attribution (which part failed) | ❌ | hit_rate scores the whole system as one blob; the appetite-vs-rating finding (5.0★ band landed 1/5) required manual analysis to attribute |
| ask policy | ⚠️ run-level only | SCOUT.md §1 has a mandatory clarify check with a one-question budget — good, but it only covers *this ask's* ambiguity, never *the profile's* blanks |

### Part 3 — Judgment loop: **built and measured**

Working: pool (6,473 candidates) + harvesters, funnel, blind critic,
percentile gate (mid-rank), sealed predictions, verdict loop (18 scored,
hit_rate 0.50), priors (5 active), pitch page, digest mode, 146 tests.
Engine purity verified: **zero** user-specific references in SCOUT.md or
CRITIC.md.

Honest gaps, in order of consequence:
1. **Appetite is not a first-class axis.** The gate predicts rating; the
   user answers with appetite. Evidence: predicted-5.0★ candidates landed
   1/5 (20%) — the most confident band was the worst. Currently patched
   via priors, which is a correction bolted onto the wrong output rather
   than the right output.
2. **Version identity** — designed in the enrichment spec, unimplemented.
3. `sealed_vs_actual` still empty (no post-watch ratings yet) — the heavy
   tier of calibration has never fired. Not a defect; a fact about time.

### Part 4 — Delivery: **designed, unimplemented**

The enrichment spec (2026-08-23) covers entry points, moments, quotes,
reception, the generated-not-searched decision, and the honesty contract.
Waiting on approval + implementation. Nothing further here.

## 3. Design — Part 1: PROFILER.md, the third engine contract

The engine grows a third organ beside SCOUT.md and CRITIC.md. Like them it
is prose read at runtime, user-agnostic, with the instance bound in
README.md.

### 3a. The two-ledger principle (the governance rule, generalized)

- **Ledger 1 — the profile document.** Contains ONLY what the user has
  *expressed*: ratings, review text, direct statements, answers they gave
  to genuine questions. Written in their words wherever words exist. The
  engine never writes an inference into this ledger. For a silent user
  this ledger may be nearly empty forever — that is a valid state.
- **Ledger 2 — engine inference.** Hypotheses mined from data, priors from
  verdicts, coverage notes — all confidence-labeled, all falsifiable, all
  owned by the engine (`engine_priors` + PROFILER working notes). This
  ledger does the interpretive work the user didn't volunteer.

This generalizes the rule discovered with user #1 ("TASTE.md is his voice,
never co-edited"; "never present statistical claims about the user to
ratify") from an instance fact into the engine's constitution. The reason
it must be engine-level: attributing inferred categories to a person is
wrong *generically* — it was merely *discovered* here.

### 3b. The bootstrap ladder (cold start, by what exists)

| tier | user brings | PROFILER does | profile state |
|---|---|---|---|
| 0 | nothing | seed: offer ~10 well-known works to react to (react ≠ rate: "watched-loved / watched-meh / never-started-not-interested / never-started-curious" — the 4th option is appetite signal, tier-0's scarcest data). Hard cap: one screen, skippable. | near-empty; engine runs on population priors, says so |
| 1 | importable history (Douban/Letterboxd/IMDb/Plex) | mine distribution + cells (machinery exists); derive hypotheses into **Ledger 2 at low confidence**; do NOT interview | history IS the profile; interpretation stays engine-side |
| 2 | history + accumulating verdicts | the calibrate loop (exists) sharpens Ledger 2; hypotheses that keep predicting well get promoted to higher confidence — still Ledger 2 | working understanding without the user saying a word |
| 3 | an engaged user who talks | feedback sessions (SKILL 6b, exists); genuine questions at the ask-policy rate; **user-confirmed answers enter Ledger 1 verbatim** | converges toward a TASTE.md-grade document |

The spine is **learn-by-recommending**: every pitch is an experiment, every
verdict is elicitation the user never experiences as a questionnaire. Direct
questions are the garnish, not the meal.

### 3c. Maintenance contract

After each data refresh (the monthly pipeline): (1) `sealed_vs_actual`
pass — new ratings vs sealed predictions, mispredictions attributed (§4b)
and turned into prior updates; (2) distribution drift check — a cell whose
base rate moved materially flags affected priors for re-check
(`calibrate.py check`, exists); (3) Ledger 1 is appended only by new user
expressions (new reviews, new statements), never by the refresh itself.

## 4. Design — Part 2: self-knowledge

### 4a. Coverage, made explicit and cheap

Every dossier gains one required field (scout-filled, critic-audited):

```
evidence_density: "anchored" | "adjacent" | "blank"
```

anchored = direct rated analogues exist (version-checked); adjacent =
analogues only in neighboring territory, stated as such; blank = the
argument rests on profile-general reasoning with no rated evidence nearby.
The critic caps confidence at `low` for blank-territory predictions and
must carry the blankness into `residual_risks`. This formalizes what the
critic already improvised once (Rear Window) — from ad hoc virtue into
contract.

### 4b. Attribution — scoring the parts, not just the blob

Every calibrate feedback entry and every sealed-vs-actual misprediction
gets one attribution tag:

```
miss_part: "retrieval" | "profile-gap" | "judgment" | "axis" | "delivery"
```

(wrong candidate pool territory / blank map / had evidence and misweighed /
appetite-vs-rating class / right work, pitch failed it). This is what
makes "your own judgment call on how accurate this taste file is"
*measurable*: profile accuracy is the trend of profile-gap + judgment
misses, separated from retrieval and delivery noise. Costs one enum per
entry; `calibrate.py check` learns to report the split.

### 4c. The ask policy (the stated principle, made precise)

A direct question to the user is permitted when — and only when — one of:

1. **Run-level fork** (exists today): the ask itself is ambiguous and the
   fork changes the candidate set. SCOUT.md §1, unchanged.
2. **Persistent blank**: the same `blank`-territory region has produced
   low-confidence predictions across ≥2 runs the user actually asked for
   — i.e. the map's hole is load-bearing, not incidental.
3. **Live contradiction**: a user expression and their measured behavior
   point opposite ways AND the current run must choose between them.

Budget: **at most one question per interactive run; zero in digest mode.**
Prefer the non-blocking form — pitch under a stated assumption ("this
slate assumes X; say the word if that's wrong") — over stopping to ask.
Never a ratification question ("is it accurate that you…"); always a
genuine fork the user hasn't already answered. Every ask or deliberate
non-ask is logged in the funnel log, same as the clarify check today.

## 5. Design — Part 3's one structural change: the appetite axis

The critic's output gains a second, separately-argued prediction:

```
predicted_appetite: "low" | "medium" | "high"   + appetite_case: "..."
```

- `predicted_stars` keeps meaning "what they'd rate it once watched"
  (percentile-gated, unchanged — it is well calibrated as that).
- `predicted_appetite` means "would they start it this week", argued from
  shape, era, register, and the work's on-ramp (which is why Part 4's
  entry point feeds it: a good entry point *raises* attainable appetite).
- Pitch selection uses appetite as the tiebreak and floor; ranking within
  the slate stays rating-led. The 20%-landing failure mode becomes
  impossible to hide: a 5.0★/low-appetite candidate must say so on its
  face and win its slot with an entry plan, or lose it.
- Measurement is free: verdicts (`interested`/`meh`) ARE the appetite
  ground truth; `calibrate.py check` scores the new axis with zero new
  input from the user.

This subsumes three of the five current priors (appetite-vs-rating,
recency-appetite, doc-fatigue) into structure — they become evidence the
appetite argument must weigh rather than bolted-on corrections. The priors
stay recorded; their job shrinks.

## 6. Part 4 — delivery

Designed in `2026-08-23-media-recommend-enrichment-design.md` (entry
points, moments, quotes, reception; generated-not-searched; honesty
contract; version-identity rule). One addition from this review: the
enrichment's `entry` block is an *input to the appetite argument* (§5),
which is the formal reason delivery is part of the engine and not
cosmetics.

## 7. Roadmap — order and why

| step | what | why this order |
|---|---|---|
| 1 | Enrichment + version rule (existing plan) and finish the parked GTA6 run | already planned and gated on approval; unblocks the live test; smallest distance to user-visible value |
| 2 | Appetite axis in CRITIC.md + calibrate scoring (§5) | the measured worst defect (20% at 5.0★); mostly prose + one output field; verdict data to score it already accumulates |
| 3 | PROFILER.md: two-ledger + bootstrap ladder + maintenance (§3) | the missing organ; pure prose contract; makes tier-1/2 users real |
| 4 | `evidence_density` + ask policy (§4a, 4c) | small contract additions riding on steps 2–3's edits to the same files |
| 5 | `miss_part` attribution in calibrate (§4b) | one enum + report change; becomes valuable once steps 1–4 generate attributable misses |

Steps 1–2 before 3: for the current instance, Parts 1–2's absence is
masked by a hand-built profile, while Part 3's axis defect and Part 4's
absence are live in every run. A general-product purist would build 1
first; a product that learns from its one real user builds where the
errors are measurable. The four-part architecture is served either way
because every mechanism lands engine-side.

## 8. What "done properly" will look like (acceptance, system-level)

1. A hypothetical user #2 with only a Letterboxd export gets: a working
   pitch page, predictions labeled with honest confidence, blank-territory
   candor, and zero sentences put in their mouth — with no human doing
   Part 1 by hand.
2. hit_rate is decomposable: the report can say *which part* missed.
3. The most confident band is also the best-landing band (the 5.0★
   inversion is gone or explained per-candidate on the page).
4. Every long-work pitch teaches the user where to enter it.
5. The engine asks a question rarely enough that when it does, it reads as
   judgment, not friction.
