# /recommend smoke test — 2026-08-23

Synthetic ask: 聪明的犯罪剧，剧情要有反转. Isolated run against a copy of
media.db (`$SC/smoke.db`); real `media.db` was never opened for write
(mtime unchanged throughout, confirmed at end of run) and no funnel log
landed in `recommend/logs/`. All artifacts live under
`.../scratchpad/smoke/` (snap.json, index.txt, dossiers.json,
critic-prompt.md, critic.json, batch.json, logs/2026-08-23-smoke-crime-reversal.md).

## Status
Done. Ran end-to-end: **yes** — every documented seam (snapshot → index →
scout sweep/narrow/dossier → critic pass → batch build → log → pending →
verdict → stats) executed successfully against the isolated DB copy with
no crashes and no unrecoverable contract violations.

## Defect list (terse, one-liner each)

1. **SCOUT.md §2 "semantic relevance... not string matching" vs. actual
   practice**: building the history neighborhood in this run used
   keyword `grep` over index.txt to find crime-adjacent titles, which
   IS string matching — the exact thing §2 prohibits. It worked because
   the anchors happened to be lexically obvious English titles (Breaking
   Bad, Ozark, etc.); it would silently miss Chinese or non-obviously-
   named crime titles already in the 1717-line index. At smoke scale
   this was a deliberate speed shortcut, but it's a real defect in how
   the contract will actually get followed at full scale unless the
   scout is made to read the whole index, not grep it.
2. **`douban-export/sources/sources.env`, as sourced per the brief's
   exact instruction, throws `command not found` on line 32**
   (`SPOTIFY_CLIENT_SECRET=...`) when `source`d from a zsh/bash shell —
   the value likely contains an unescaped shell-special character. It's
   harmless here (TMDB_API_KEY still loads fine after the error), but
   the instructed command is not clean and prints a scary-looking error
   to stderr every time; out of scope for `recommend/` but hit exactly
   per the brief's own instructed step.
3. **NeoDB endpoint confusion — `/api/item/{uuid}` 404s for TV-season
   records**; the correct endpoint is category-specific,
   `/api/tv/season/{uuid}` (discoverable only via the `api_url` field
   embedded in the post-chain JSON, not documented anywhere in SCOUT.md
   itself). SCOUT.md's evidence-hierarchy section describes the review
   chain (`/api/item/{uuid}/posts/` → `/api/review/{uuid}`) but never
   mentions that resolving the *item itself* (for shape/external_ids
   verification) needs a different, category-typed path. Cost one failed
   call per title before finding the fix.
4. **NeoDB JSON responses contain raw control characters that break
   Python's default `json.load`/`json.loads`** (`Invalid control
   character` errors) — needed `strict=False` to parse. Not mentioned
   anywhere in SCOUT.md's source notes; a scout following the notes
   literally with a naive JSON parser will hit this on some fraction of
   NeoDB calls.
5. **`urllib.request` (Python stdlib, no custom headers) gets a flat
   HTTP 403 from `neodb.social/api/review/{uuid}`, while plain `curl`
   (default UA) gets 200** — an undocumented NeoDB user-agent gate that
   isn't in SCOUT.md's source notes (which otherwise carefully catalog
   which fetch method works where per site). Cost a debugging detour.
6. **`history.py lookup --title` substring matching is noisy for short/
   common words** — `--title "Dark"` for dedup-checking the show *Dark*
   (2017) returned 8 unrelated matches (Darkest Hour, Dark Fate, Dark
   Knight x2, Thor: The Dark World, Star Trek Into Darkness, Transformers:
   Dark of the Moon, a shell "Dark Matter (2024)") requiring manual
   external-id/year comparison to clear each one. CRITIC.md documents
   the dedup mechanism but not this noise; it worked (I could rule all 8
   out by hand) but would not scale well to a batch of many one-word-
   titled candidates in a full run.
7. **CRITIC.md's "blindness" instruction is not actually achievable
   without a real subagent** — per this brief's own constraint (no
   subagent dispatch), the "critic pass" was performed by the same
   context/session that ran the scout. I did not re-derive any scout-
   only reasoning while writing critic.json, but the underlying model
   context still *contains* the scout transcript; this is a **simulated**
   blindness boundary, not a real one, and the smoke test cannot certify
   that a real fresh-context critic would reach the same verdicts. This
   is a property of the smoke-test's forced constraint, not of the real
   pipeline (which does spawn a genuinely fresh subagent) — flagging it
   per the brief's own instruction to report this honestly.
8. **Minor, not a defect**: `reclog.py stats`'s `sealed_vs_actual` stayed
   `[]` even after a `verdict interested` was recorded — correct
   behavior per the tool's own docs (sealing needs an actual watched
   rating in `works`, which a synthetic smoke run never produces), just
   noting it so it isn't mistaken for a broken seam by a future reader
   of this report.

No other seam broke. `snapshot`/`index`/`lookup` (history.py),
`log`/`pending`/`verdict`/`stats` (reclog.py) all behaved exactly as
documented, including the correct exclusion of the killed candidate from
`pending`.

## Cost estimate
Wall-clock for the tool-call portion of this run: **~9.5 minutes**
(576s measured start-to-finish of scratchpad setup through `stats`).
Roughly **45–50 tool calls** total (reads of the 4 spec docs + TASTE.md;
~20 Bash calls for snapshot/index/curl sweeps/lookups/dossier-and-batch
building; a handful of Write/Edit-equivalent file writes). This was a
3-dossier run against an ~8-title cut1 and a ~27-title gather; a full-
scale run (100–200 gathered, ~40 cut1, ~12 cut2, ~12 dossiers) is roughly
4–6x this pool size, so a naive linear scale-up suggests **35–60 minutes
wall-clock** and **150–300 tool calls** for the scout+critic portion
alone, before the orchestrator's own pitch-writing and any user-driven
re-sweep/sendback passes. The biggest scale risk found here is defect
#1: a genuinely non-grep, full-index semantic read at ~1700 lines is
itself cheap, but doing so for EVERY ask (not reusable across asks) adds
real per-run cost that this smoke test shortcut around.

## Index/lookup usability for the scout
Good but not free. `history.py index` produced a complete, readable
1717-line list; `lookup --work-id` and `lookup --title` both returned
rich, correctly-sectioned JSON (review text, external_ids, section
provenance) fast and reliably. The one real friction point is noted as
defect #6 (title-substring noise) and defect #1 (the honest way to build
the neighborhood is a full read, not a grep, and that's slower than what
was actually done here).

## Evidence channels
TMDB `/recommendations` off the Breaking Bad anchor worked exactly as
the source notes predicted (0% junk, all crime/drug-trade dramas).
TMDB `discover` with a crime+mystery genre combination also matched the
source notes (mixed but usable, ~15-20% needed manual filtering for
anime/superhero/teen-soap genre-creep). TMDB `/reviews` returned 0
results for 3 of 5 English-ish candidates tried (Sneaky Pete, Dark
Winds, Griselda) despite reasonable vote counts — thinner English-review
coverage than the source notes' measured sample suggested, a real
finding worth folding back into SCOUT.md's probe log. NeoDB's review
chain worked and returned genuinely substantive, quotable Chinese essays
for all 3 Chinese titles tried, including one usefully NEGATIVE review
(隐秘的角落) that became the deciding evidence for a kill — the channel
is not just a source of positive-spin evidence, which matters for the
critic's adversarial stance.

## Was the critic able to do its job from its contract-permitted inputs?
Yes, with the caveat in defect #7. Working from only CRITIC.md + TASTE.md
+ index.txt + dossiers.json, the critic pass could: verify identity
(no network needed, just internal consistency), run dedup via `lookup`
(caught the "Dark" title-noise but resolved it), build a real predicted-
rating case by analogy using named history exemplars pulled via
`lookup` (Better Call Saul, Ozark, Killing Eve, 白夜追凶), and apply the
evidence-tier confidence caps correctly. The single most useful thing
the contract gave the critic was `lookup`'s access to REVIEW TEXT on
anti-anchors (Ozark S2, Killing Eve S4) — those two independent reviews
naming the identical failure mode ("characters get dumber to manufacture
drama") were what actually decided the one kill in this run, and that
mechanism (case law from the user's own words, not label-matching)
worked exactly as CRITIC.md intends.

## Three candidates, one line each
- **Dark** (2017, DE) — SURVIVE, 4.0★ medium: praised for the same
  scrutiny-proof plotting Better Call Saul earns 5★ for, but genre-blend
  (sci-fi-forward) and one review calling it "slow" (echoes a hard-line
  dislike) keep confidence at medium.
- **沉默的真相 / The Long Night** (2020, CN) — SURVIVE, 4.5★ high: a
  NeoDB review's "you truly couldn't have guessed it, and it holds
  together logically" is close to a verbatim match to what earned
  Better Call Saul its 5-star reviews.
- **隐秘的角落 / The Bad Kids** (2020, CN) — KILL (predicted): the one
  review obtained says the reversal wasn't foreshadowed and leaned on
  coincidence ("我觉得被欺骗了" / I felt cheated) — structurally the
  same complaint that got Ozark S2 and Killing Eve S4 downgraded 2 full
  stars in this user's own rated history.
