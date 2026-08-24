---
name: recommend
description: Recommend film/TV using the user's watch history + taste profile. Use when the user asks what to watch, wants recommendations, says /recommend <ask>, or the digest schedule fires. The ask may be ANY free text (genre, mood, "like X but Y", 下饭, "something bad on purpose"...). Not for games/books/music (not built yet).
---

# /recommend — orchestration

You are the orchestrator. Methodology lives in `recommend/SCOUT.md`
(retrieval + funnel) and `recommend/CRITIC.md` (gate); instance bindings
in `recommend/README.md`. Read all three BEFORE acting. Follow SCOUT.md
for steps 1–6, gated by its "Run modes" section — **determine interactive
vs digest first** (an ask-bearing invocation is interactive; no ask /
the scheduled trigger is digest) since it changes step 0 and steps 2–4
below. This file only defines orchestration order and the seams.
All commands assume cwd = the `media-hub` repo root.

0. **Digest harvest — digest mode only, runs before everything else.**
   Interactive mode skips straight to step 1. Refresh the pool so the
   run's pool queries (step 2) see current data:
   1. `python3 recommend/harvest_tmdb.py anchors --db media.db >
      <scratchpad>/tmdb_anchors.json`, then `harvest_tmdb.py fetch
      --anchors <scratchpad>/tmdb_anchors.json --raw-dir
      recommend/raw/tmdb/<YYYY-MM-DD>/` (new/changed anchors plus the
      recency discover pass), then `harvest_tmdb.py transform --raw-dir
      <that dir> --out <scratchpad>/tmdb_batch.json`.
   2. `python3 recommend/harvest_douban.py anchors --db media.db >
      <scratchpad>/douban_anchors.json`, then `harvest_douban.py fetch
      --anchors <scratchpad>/douban_anchors.json --raw-dir
      recommend/raw/douban/<YYYY-MM-DD>/ --checkpoint <scratchpad or a
      persistent checkpoint file>` (bounded by its own `--budget`; a
      block or the circuit breaker is a finding, not a failure — report
      it, don't retry past it), then `harvest_douban.py transform
      --raw-dir <that dir> --out <scratchpad>/douban_batch.json`.
   3. Before the first media.db **write** of this run — which is the
      upsert next, not the later history snapshot — run the README
      write ritual (`lsof media.db*`, STATE.md lane check,
      `PRAGMA wal_checkpoint(TRUNCATE)`, backup).
      `python3 recommend/pool.py --db media.db upsert --json
      <scratchpad>/tmdb_batch.json` then again with
      `douban_batch.json` (two calls — `upsert` takes one file).
   4. `python3 recommend/pool.py --db media.db suppress-sync` — marks
      pool rows watched/rejected since the last refresh.
   5. `python3 recommend/pool.py --db media.db stats` — carry this
      verbatim into the digest report (step 7).
   Raw-first per house rule: every fetched page lands under
   `recommend/raw/<source>/<date>/` before any transformation, already
   enforced by the harvesters themselves — do not skip straight to
   `transform` on a raw dir you didn't just fetch into.
1. **Setup**: read README.md bindings + the profile it names. Capture the
   ask verbatim as `intention` (in digest mode, the DIGEST-INTENT.md
   text) — this is carried unchanged into every row logged in step 5.
   History snapshot FIRST (one transaction, before ANY network I/O of
   ITS OWN — digest's step 0 harvest, if it ran, is already done and is
   not the "any network I/O" this ordering protects against; it protects
   the ask's own retrieval work from racing a concurrent writer):
   `python3 recommend/history.py --db media.db snapshot --out <scratchpad>/snap.json`
   Then build the critic's history index from that snapshot:
   `python3 recommend/history.py index --snapshot <scratchpad>/snap.json --out <scratchpad>/index.txt`
   Then build the critic's calibration input from the same snapshot:
   `python3 recommend/history.py distribution --snapshot <scratchpad>/snap.json`
   Keep its JSON — step 3 passes it to the critic verbatim. It is small
   (summary statistics, not per-work rows), so inlining it is safe and
   correct, unlike snap.json.
2. **Scout**: run SCOUT.md §§1–6 in this session (interpret + clarify
   check → history → sweep → narrow → dossiers → handoff), following
   whichever of SCOUT.md's "Run modes" paths matches this run:
   - **Interactive**: pool query (SCOUT.md §3 tier 1, local — the only
     candidate source; the library/`shells` is never swept for
     candidates, per SCOUT.md §2/§3) → shortlist-with-bar (§4's
     "shortlist against the target" — read the pitch target + cap from
     README.md's bindings and, per shortlisted candidate, its cell from
     `history.py cell`, and pass both to the scout exactly as step 3
     below passes them to the critic) → cached-evidence-first dossiers
     (§3c: read each candidate's pool-row `evidence` first, fetch only
     what's missing, write fetched evidence back with `pool.py
     attach-evidence` as you go — do not defer the write-back to the
     end of the run). Stay inside the ~10-network-call budget; a
     targeted top-up (tier 2) for a logged pool gap is the only
     sanctioned overflow.
   - **Digest**: the full funnel — §3's sweep across all tiers, §4's
     Cut 1/Cut 2, deep dossiers — exactly as v1, now starting from the
     pool step 0 just refreshed.
   Keep the funnel log current as you go, including the §1 clarify
   decision and any `pool gap:` lines. Write dossiers.json as a JSON
   **list** — its ordering is the join key for step 5, so do not reorder
   it after the critic is dispatched.
3. **Critic**: spawn a subagent (general-purpose) whose prompt contains
   ONLY: the text of CRITIC.md, the profile document, the **contents of
   index.txt**, the **path** to snap.json (plus the `history.py lookup`
   usage CRITIC.md describes), the **distribution JSON** from step 1,
   **one cell object per candidate**, dossiers.json, and one more
   required line: the **pitch target** (plus the pitch cap), stated
   explicitly and named as such (e.g. "Pitch target: <this run's pitch
   target, from README.md's bindings>. Pitch cap: <N, from README.md's
   bindings>"). **Copy the tie convention along with the number** — the
   binding states both, and a percentile target is meaningless without
   the convention that resolves ties on a coarse star grid.
   README.md is NOT one of the critic's permitted inputs
   (see CRITIC.md's input list) and the critic never receives the file
   itself — this line is the only way the target reaches it. Every
   survive/kill call in the critic's core judgment turns on this target,
   so the orchestrator must read it from README.md's bindings and copy
   it into the prompt verbatim; do not paraphrase it, do not let the
   critic infer it from the profile's rating semantics, and do not omit
   the line as redundant with the profile document.
   **Generate the per-candidate cells before spawning.** For each
   dossier, run
   `python3 recommend/history.py cell --snapshot <scratchpad>/snap.json --kind <dossier.kind> --year <dossier.year>`
   and put the returned object in the prompt tagged with that
   candidate's `dossier_index`, so the critic can pair candidate to
   cell without guessing. Cells repeat across candidates that share a
   population — emit each one once and say which indices it covers, or
   emit it per candidate; either is fine as long as every candidate has
   one. A cell that comes back with `fallback_used: true` is passed
   through as-is: the widening is the critic's to weigh, not yours to
   hide or to re-cut. The distribution and the cells are **required**
   inputs — the gate is positional and the critic returns
   `contract_ok: false` without them.
   **Never inline snap.json and never tell the critic to Read it.** It
   is ~900KB / ~40,000 lines; a Read caps at 2,000 lines and returns an
   arbitrary recency slice with no indication that anything is missing,
   so the critic would reason about the user's taste from ~5% of it
   while believing it had all of it. index.txt is ~1,700 lines and is
   the complete rated list; detail comes from `lookup`. Equally, never
   hand the critic a subset of the history that YOU chose — the scout
   picking which history the judge sees defeats the blindness the whole
   design rests on.
   DO NOT include the funnel log, channel/query history, or any mention
   of search effort.
   If the critic returns `contract_ok: false`: do NOT pitch from that
   response. Read its `contract_problem`, fix the input violation
   (usually: something search-related leaked into the prompt, an input
   was missing, or index.txt was truncated before its `END OF INDEX`
   marker), and spawn a FRESH critic with corrected inputs. If it fails
   the same way twice, stop and report the problem to the user rather
   than pitching unvetted candidates.
   If the critic requests a re-sweep (floor rule), the response depends
   on run mode:
   - **Interactive: do NOT auto-resweep.** Report the thin slate honestly
     to the user in the pitch (step 4) — how many survived, why, and
     what the floor rule found short — and offer to go deeper. Only run
     a sweep pass if the user says yes; that pass follows the same rules
     as below (one differently-angled pass, fresh dossiers, fresh critic,
     capped at one). A thin slate reported honestly is a valid, complete
     interactive run; it is not a failure state to silently patch over.
   - **Digest: auto-resweep, as v1.** Do ONE differently-angled sweep
     pass, rebuild dossiers for new finalists, spawn a FRESH critic
     subagent. Max one re-sweep.
   For any candidate the critic returns with `outcome: "sendback"`:
   rebuild that candidate's dossier once with deeper evidence and
   resubmit it to a critic pass. If a re-sweep is already happening, the
   rebuilt dossier rides along in that pass. If no re-sweep was
   requested there is no pass to ride along in, so spawn one FRESH
   critic subagent carrying only the rebuilt dossiers — this is that
   candidate's next pass, and it is the last one. If it cannot be
   rebuilt (e.g. the evidence isn't obtainable), leave it as a sendback
   and log it per step 5 with the `sendback:` prefix. Cap sendback
   rebuilds at one per candidate, same as the resweep cap.
   **Joining a critic verdict back to its dossier: use `dossier_index`,
   never the title.** Each critic candidate object carries
   `dossier_index`, its zero-based position in the dossiers.json list
   sent to that pass; `dossiers[dossier_index]` is its dossier. Titles
   look like a natural key and are not one — 漫长的季节 vs The Long
   Season, or a dropped leading article, silently fails the match and
   the row gets another title's ids. If a returned `dossier_index` is
   missing or out of range, that is a contract failure: treat it like
   `contract_ok: false` rather than falling back to title matching.
   When a candidate is judged in more than one pass (a re-sweep pass, or
   a rebuilt sendback), each pass has its OWN dossiers.json and so its
   own index space — resolve `dossier_index` against the list you sent
   to *that* pass.
4. **Pitch** to the user: state your interpretation of the ask first;
   then each survivor — the case (profile-persuasive terms only), key
   evidence, predicted stars + `predicted_percentile` (with the cell it
   is a percentile of) + confidence, residual risks; then wishlist-notes
   if any; then the honest survivor count if < 2.
   **The critic's ranking and selection are given, not advisory.** Pitch
   exactly the survivors it marked `pitch_selected: true`, in
   `pitch_rank` order. Do NOT re-cut, re-order, or substitute by your
   own taste — that hand-cut was an unlogged filter and moving it into
   the critic is the point of the ranking fields. Say how many other
   candidates survived unselected, and pass along their
   `selection_reason` if the user asks why something is missing. The
   only case for overriding is a mechanical fault (a `pitch_rank` that
   is missing, duplicated, or out of range, or more `pitch_selected`
   rows than the cap you sent) — treat that like any other contract
   failure per step 3 rather than silently repairing it. Fewer than 2 is
   reported honestly per the floor rule; never top up. **Interactive
   mode only**: if this is a thin slate the critic's floor rule flagged,
   this is where you make the offer from step 3 — state the honest
   count, why (thin evidence, tight cell, few pool candidates in the
   ask's territory), and ask whether to go deeper. Do not run the extra
   pass unasked.
   **Surface `prediction_spread` with the pitch**, in one line: the star
   range, the percentile range, and whether any candidate landed at or
   below the middle of the scale. If `non_discrimination_warning` is
   `true`, say so plainly and quote the critic's `note` — a run where
   every candidate scored effectively the same means the gate did not
   discriminate, and the user must be told that rather than left to
   spot it by comparing numbers by hand.
   Category names and aggregate scores are never reasons.
5. **Log** (media.db write — run the README write ritual first, from the
   media-hub root). Build one JSON list, one object per candidate that
   reached the critic (survivors, kills, unrebuilt sendbacks, and
   wishlist-notes).
   **Exactly one row per candidate, carrying its FINAL outcome.** A
   candidate judged in two passes — a first pass plus a re-sweep pass,
   or a sendback that was rebuilt and re-judged — still gets ONE row,
   holding the last verdict it received; its earlier verdict lives on
   inside that row's `dossier.critic`, not as a second row. Duplicate
   rows inflate the `pitched` denominator and corrupt the hit-rate the
   system judges itself by. Dedup on `external_ids` where present, else
   title+year, before writing. Every row carries these fields:
   - `session_date` — ISO timestamp of this run.
   - `intention` — the ask verbatim, carried from step 1. **Required**;
     `reclog.py log` rejects the whole batch if it is missing or blank.
   - `kind`, `title`, `year`, `external_ids` — the row's own columns,
     taken from `dossiers[dossier_index]` (not nested).
   - `work_id` — set only when the title already exists in `works`
     (matched via snap.json ids); otherwise `null`.
   - `dossier` — a JSON object with exactly two keys, `scout` and
     `critic`; nothing flattened, nothing dropped. `scout` holds the
     scout's dossier object for this candidate verbatim. `critic` holds
     the critic's full per-candidate JSON object verbatim, so
     `evidence_chain`, `residual_risks`, and `kill_evidence` survive in
     full inside it. Shape: `{"scout": {...dossier...}, "critic":
     {...candidate...}}`. This nesting is the audit trail — it keeps the
     scout's case and the critic's verdict distinguishable inside one
     stored record, since both objects separately carry `title`/`year`
     and a flat merge would silently overwrite one with the other. For a
     candidate judged twice, put the final verdict in `critic` and the
     earlier one in an additional `critic_prior` key.
   - `predicted_stars`, `predicted_confidence` — the row's own columns,
     from the critic's per-candidate object (not nested).
     `predicted_stars` is in **stars, 0.5–5.0** — media.db's
     `records.rating` is on a 0–10 scale and stars are `rating / 2`.
     Never put a 0–10 value here; `reclog.py` rejects the batch if you
     do, because `stats` would otherwise compare the two scales and
     report a nonsense accuracy figure.
   - `critic_killed` — `critic_killed = 1` means the candidate did not
     reach the user as a pitch. Map the critic's `outcome`:
     `"kill"` → 1; `"sendback"` (not rebuilt) → 1;
     `"wishlist-note"` → 1 (it is surfaced to the user as a note, not a
     pitch, so it must not count in the pitched denominator);
     `"survive"` → 0. A survivor the critic left `pitch_selected: false`
     because of the pitch cap is still `0` — it passed the gate.
     `pitch_rank`, `pitch_selected`, `selection_reason`,
     `predicted_percentile`, `p_top`, `cell_label`, `cell_base_rate`,
     `base_rate_argument`, and `middle_of_scale_check` have no columns of
     their own; they ride along verbatim inside `dossier.critic`, which
     is why that object is stored whole. Do not drop them.
   - `kill_reason` — for `critic_killed = 1` rows: `"<kill_rule>:
     <kill_evidence>"` for kills; `"sendback: <why it wasn't rebuilt>"`
     for unrebuilt sendbacks; `"wishlist-note: <why it matched the
     wishlist>"` for wishlist-notes. Empty string `""` for survivors
     (`critic_killed = 0`).

   Then: `python3 recommend/reclog.py --db media.db log --json <scratchpad>/batch.json`
   It prints a JSON list of the inserted row ids **in batch order** —
   `ids[i]` is the id of `batch[i]`. Keep that mapping; step 6 needs it.
   If you lose it (or verdicts arrive in a later session), recover the
   ids with `python3 recommend/reclog.py --db media.db pending`, which
   lists every un-verdicted pitched row with its id, title, and year.
5b. **Render and open the pitch page** — do this immediately after step 5,
   before writing the report. This is the deliverable the user actually
   reads; the chat pitch in step 4 is the summary, the page is the thing.
   ```
   python3 recommend/render.py --db media.db --ids <the step-5 ids> --open
   ```
   With no `--ids` it renders the newest logged slate, which is the same
   thing right after step 5; pass the ids anyway so a concurrent run can
   never steal the slate. Add `--include-killed` when the run's kills are
   worth showing (a thin slate, or the user asked what got cut).
   It is a read-only view — safe to re-run any time, and safe while
   another process holds media.db.
   **Read its JSON output before moving on.** `id_warnings` is a
   non-empty list when a logged `external_ids` entry does not match what
   the source says that id is — that is a fabricated id in media.db (it
   has happened: two of six rows in the 2026-08-23 run carried invented
   tmdb ids), so treat any warning as a defect to verify against the
   source and correct, not a cosmetic gap. `covers` and `synopses` below
   full coverage are ordinary — some works simply have no poster.
6. **Verdicts**: when the user reacts, record each with
   `python3 recommend/reclog.py --db media.db verdict --id N --verdict V --note "..."`
   where `N` comes from the step-5 id list (or from `pending`) and `V` is
   one of `interested` / `no` / `meh` / `watched`.
   `interested` → offer (never auto-run) the wishlist add per README.
7. **Report**: end with counts (gathered / cut1 / cut2 / dossiers /
   survivors / selected) + a machine-readable list of source
   skips/failures, and the funnel log path. If a verdict or later rating
   contradicts a prediction, record it as an ENGINE-prior update candidate
   (spec Part B lifecycle, 2026-08-23 amendment) — adjust priors, risk
   flags, or channel weights. Never propose edits to the profile document
   and never present the user with statistical claims about their own
   taste to ratify; at most, ask a genuine question about a surprising
   pattern.
   **Report the critic's `prediction_spread` verbatim** as its own line:
   `distinct_star_values`, `stars_min`–`stars_max`,
   `percentile_min`–`percentile_max`, `used_middle_or_below`, and
   `non_discrimination_warning`. When the warning is `true`, lead the
   report with it — the run's predictions came out flat, which says the
   gate failed to discriminate and the survivor list should not be
   trusted as a ranking. Report it even when it is unflattering to the
   run; that is exactly the case it exists for.
   Then show the running calibration numbers:
   `python3 recommend/reclog.py --db media.db stats` — `pitched`, `hits`,
   `hit_rate` ((interested + watched) / pitched, spec A8), and
   `sealed_vs_actual`, which pairs each sealed `predicted_stars` against
   the user's real rating once one exists. This is the only measurement
   of whether the engine is actually right; report it, and flag any
   sealed pair off by more than one star as a calibration signal.
   **Digest mode only**: also report the step 0 harvest numbers —
   `pool.py stats`' output (total rows, by kind, evidence-cached,
   suppressed, per-channel provenance) plus each harvester's own
   fetched/failed/blocked counts from step 0 — so pool health is a
   visible part of every digest report, not something read out of the
   raw logs after the fact.

Digest mode (no ask given / scheduled): use DIGEST-INTENT.md as the ask
in step 1; step 0 (harvest) runs first, run mode is "digest" throughout
steps 2–4 as detailed above (full funnel, auto-resweep), and step 7
carries the pool stats. Everything not called out above as
mode-specific is identical between the two modes.
