# Final fix wave — implementation report (2026-08-23)

Status: **DONE.** 1 Critical + 11 Important + 8 Minor findings addressed;
0 skipped outright (2 deliberately scoped down, both flagged below).
Tests: **51/51 passing** (was 18/18).

Files touched (all absolute under `/Users/anping/Documents/Stuff/AI Space/media-hub`):

| File | Lines | What |
|---|---|---|
| `recommend/history.py` | 139 → 341 | C1 `index` + `lookup`; shells docstring (I1); `creators` in snapshot; busy_timeout |
| `recommend/precedence.py` | 33 → 67 | same-source tie fix (controller's reversed ruling) |
| `recommend/reclog.py` | 215 → 269 | I7 star-range guard + DDL CHECK; row-shape validation; busy_timeout |
| `recommend/CRITIC.md` | 115 → 206 | C1 read contract, I2, I3, I5, I8, I9, minors |
| `recommend/SCOUT.md` | 299 → 379 | I1, I3, I4, handoff contract, media.db-fallback minor |
| `recommend/README.md` | 28 → 63 | I10 profile grading; shells id caveat; helper list |
| `.claude/skills/recommend/SKILL.md` | 84 → 157 | C1 dispatch, I5, I6, pitch cap, `--id`/`stats`, `contract_ok` |
| `ARCHITECTURE.md` | +§3a | I11 |
| `STATE.md` | rewritten head | I11 |
| `recommend/tests/test_history.py` | 8 → 19 tests | C1 + tie tests, `--kinds` |
| `recommend/tests/test_precedence.py` | NEW, 12 tests | resolver had no direct tests |
| `recommend/tests/test_reclog.py` | 10 → 20 tests | I7, row shapes, `hit_rate` 0, id order |

---

## C1 — the critic cannot read the history

**Fixed as ruled: query access, not a scout-curated subset.**

`history.py index` — one line per rated work, `work_id | stars | R | year |
title [<< original_title]`, with a `#`-prefixed header explaining the
columns and naming the entry count.

**Anti-truncation guard beyond the brief.** The failure mode C1 describes
is *silent* truncation, so the index ends with a sentinel:
`# END OF INDEX — 1702 entries listed above.` CRITIC.md instructs the
critic to treat a missing sentinel as proof its read was truncated, and
to re-read from an offset. This matters because the index is 1,717 lines
today against a 2,000-line Read cap — it fits now, but the guard makes a
future overrun loud instead of silent, which is the whole point of the
finding.

`history.py lookup` — `--work-id` (repeatable), `--title` (case-insensitive
substring, matched against `title` **and** `original_title`), `--creator`
(repeatable). Returns JSON with full detail incl. review text, per-source
ratings, external ids. It searches **all four sections** (`rated`,
`wishlist`, `shells`, `rec_log`) and tags each hit with its section — so
it also answers CRITIC.md check 2 (dedup), which the rated-only index
cannot.

Design note on why the index stayed rated-only: rated + wishlist + shells
= 2,015 lines, which *exceeds* the Read cap and would have reintroduced
the exact bug. Point queries via `lookup` cover the other sections
without that risk.

`--creator` required carrying `works.creators` into the snapshot (it was
not there). It is populated for 1,688 of 2,014 in-scope works, so the
filter is genuinely useful — a real query, `--creator 诺兰`, returns 13
rated works. **Side effect:** the snapshot grew 793KB/37,930 lines →
898KB/39,945 lines (+13%). That makes C1 more acute, not less, and is
harmless now that nothing reads the snapshot linearly — but it is a
change to the snapshot's shape and I am flagging it rather than burying
it.

Both subcommands work from `--snapshot PATH` alone (no DB), and also
accept `--db` (takes a fresh snapshot in memory). `--db` had to become
optional at the top level; `snapshot` now fails loudly if it is missing
(`test_snapshot_without_db_fails_loudly`).

SKILL.md step 3 now passes index **contents** + snapshot **path** +
lookup usage, and states explicitly why neither inlining the snapshot nor
passing a scout-chosen subset is acceptable. CRITIC.md gained a section
"Reading the history: the index is the map, `lookup` is the detail",
inside the existing input contract (the transcript/funnel-log exclusion
is unchanged and still first).

Tests: `test_index_line_count_matches_rated_count`,
`test_index_marks_review_presence_and_stars`,
`test_index_and_lookup_work_from_a_snapshot_file_alone`,
`test_lookup_by_work_id_returns_full_review_text`,
`test_lookup_by_title_is_case_insensitive_substring`,
`test_lookup_by_creator`, `test_lookup_requires_a_filter`.

---

## Important findings

**I2 — thin evidence widens the band, does not lower the estimate.**
CRITIC.md item 3 gained two explicit bullets: uncertainty widens the
confidence band and never shifts the central estimate downward ("do not
predict conservatively, do not apply an uncertainty discount"); and a
candidate is killed at item 3 for evidence it is *bad*, never for absence
of evidence. Item 5 now closes with the pairing stated in both
directions: "item 3 sets the central estimate from what the evidence
indicates, this item sets the band around it from how good that evidence
is. Neither one takes the other's job."

**I1 — `shells` wired in.** SCOUT.md §2 now carries shells as a
first-class retrieval channel ("sweep it exactly as you sweep an external
catalogue"), with the profile-conditional note about library-first
viewing, and shells explicitly named as NOT excluded. Both caveats stated
honestly: "shell" asserts only absence of a watch/wish record (not
ownership), and shell entries carry no `external_ids` in the snapshot.
`history.py`'s docstring carries the measured numbers (222 shells, 160
with a `plex_guid`, 62 without).

**I3 — `evidence_tier` disambiguated.** Both files now say "the BEST —
numerically LOWEST — tier any single evidence entry reached", with a
worked example (one Tier 1 quote + four Tier 3 lines ⇒ `evidence_tier:
1`) and, in SCOUT.md, why it matters ("the critic caps
`predicted_confidence` off this number"). SCOUT.md also now separates the
per-entry `tier` from the dossier-level `evidence_tier`, which the old
wording conflated.

**I4 — superseded probe recommendations marked.** A "How to read this
section" banner opens Source notes: these are dated measurements, §3c is
normative and wins every conflict. The second probe's
"Evidence-channel recommendation" is marked **⚠ SUPERSEDED in full**,
with its three specific errors named (WebSearch-first for English
self-downgrades every English title to Tier 2; the "quote the fragments"
instruction contradicts Tier 2's own "no body quote" definition; the
media.db fallback is unavailable). Original text kept verbatim as a
blockquote. The first probe's closing clause on Letterboxd review mining
is likewise marked superseded (its discovery guidance stands).

**I5 — `dossier_index`.** Added to CRITIC.md's per-candidate output object
as **required**, with the reason inline (漫长的季节 vs The Long Season).
SKILL.md joins on it, keeps `title`/`year` for legibility, and treats a
missing/out-of-range index as a contract failure rather than falling back
to title matching. It also states that each critic pass has its own
dossiers.json and therefore its own index space.

**I6 — exactly one row per candidate.** SKILL.md step 5 now states it as a
rule, with the reason (duplicate rows inflate the `pitched` denominator),
dedup key (`external_ids` else title+year), and where the superseded
verdict goes (`dossier.critic_prior`). The undefined path is now defined:
if a sendback is rebuilt and no re-sweep was requested, spawn one fresh
critic subagent carrying only the rebuilt dossiers — that is the
candidate's next and last pass.

**I7 — star-scale guard.** `_validate_log_rows` rejects any
`predicted_stars` outside 0.5–5.0 (null allowed), with an error naming
both scales. DDL gained a `CHECK`. The live table is **not** dropped or
rebuilt — verified still `CREATE TABLE recommendations (` with no CHECK
and 0 rows after the wave. The asymmetry is documented in reclog.py's
module docstring and in ARCHITECTURE.md.

**I8 — Chinese-first restated in CRITIC.md item 1**, in the document's own
voice: absence from a foreign database is a documented negative, a douban
id + title + year is full identification, kill on identity only for a
contradiction or fabrication.

**I9 — `confidence` and `flags` wired.** `confidence` into item 1 (weigh
the scout's declared grading, but it is a declaration not proof).
`flags` into item 6 with a hard rule: every flag ends up either resolved
in `evidence_chain` or carried into `residual_risks` — "a flag that is
silently dropped is a check that did not happen."

**I10 — profile grading note in README.md.** Names the gap (CRITIC.md
expects discriminating questions and per-entry confidence; TASTE.md is
prose and has neither), states the restructure is deferred not forgotten,
and gives four grading rules for the interim, with the safe default
(provisional ⇒ stated risk, because a wrongly-killed candidate is
invisible to the user and a wrongly-flagged one is not). **TASTE.md was
not touched.**

**I11 — STATE.md + ARCHITECTURE.md refreshed.** ARCHITECTURE.md gained
§3a "The recommend system" — a file-by-file table plus the two structural
properties (critic blindness incl. why no curated subset; the snapshot is
too big to read). STATE.md's head section is now "Recommend system —
BUILT", covering all six documents, three python modules, the skill, the
prose-is-runtime warning, the user-gated Task 7, and the fix wave.

**Correction ruling — same-source precedence tie.** Confirmed reachable
and fixed. `precedence.pick_best` now orders source → status (`watched` >
`watching`) → most recent `marked_at`, tolerating rows that carry neither
column (reclog's `stats` selects only source+rating) via a `_field()`
accessor that absorbs both `KeyError` and sqlite3.Row's `IndexError`.
`_rated_entries` now selects `rec.status`, and `rating_variants` resolves
each source's rating with `pick_best` instead of `setdefault` — which was
the second half of the ruling and did hide a source's second rating.
Tests: `test_same_source_tie_resolves_watched_over_watching`,
`test_same_source_same_status_tie_resolves_to_most_recent`,
`test_rated_same_source_watched_beats_watching` (deliberately makes the
`watching` row both newer and first-inserted so neither order nor recency
alone could produce the right answer by accident),
`test_rating_variants_uses_resolved_rating_per_source`.

---

## Minor findings

| # | Finding | Disposition |
|---|---|---|
| M1 | CRITIC.md cross-refs "SCOUT.md §3c" | **Fixed** — reference dropped, blocked-source content inlined in item 5. `grep -n SCOUT recommend/CRITIC.md` returns nothing. |
| M2 | SCOUT.md "fall back to the metadata already in `media.db`" | **Fixed** — inside the SUPERSEDED block, with the correct floor named (Tier 3 metadata the scout gathers into the dossier) and the reason (candidates are by definition not in the DB; the critic sees only snapshot + dossiers). |
| M3 | SKILL.md states no pitch maximum | **Fixed** — step 4: at most 5, spec 2–5; overflow reported by count, never padded. Also clarified that a capped-out survivor is still `critic_killed = 0`. |
| M4 | No source for `--id`; `stats` never surfaced | **Fixed** — step 5 documents `ids[i]` ↔ `batch[i]` and `pending` as recovery; step 7 runs `stats` and asks for any sealed pair off by >1 star to be flagged. Test: `test_log_prints_inserted_ids_in_batch_order`. |
| M5 | `contract_ok: false` never checked | **Fixed** — CRITIC.md defines when to set it (+ a `contract_problem` string); SKILL.md step 3 refuses to pitch, respawns once with corrected inputs, then stops and reports. |
| M6 | `critic_killed: null` / non-dict row raise bare tracebacks | **Fixed** — validator catches both; insert uses `int(r.get("critic_killed") or 0)`. **Rollback re-verified** by `test_log_rollback_holds_when_the_insert_itself_fails`, which uses a failure the validator deliberately does *not* catch (unbindable `predicted_confidence` in row 1, valid row 0) — 0 rows survive. |
| M7 | No `busy_timeout` | **Fixed** — `PRAGMA busy_timeout=15000` in both helpers' connect paths, before any transaction. |
| M8 | `precedence.py` untested; `stars is None`; `--kinds`; `hit_rate` at 0 | **Fixed** — new `test_precedence.py` (12 tests: unknown source, empty input, sqlite3.Row IndexError path, alphabetical tie, all tie orders). `stars is None` asserted in `test_index_marks_review_presence_and_stars` (93 real rows hit it). `--kinds` in `test_snapshot_kinds_flag_narrows_scope`. `hit_rate` in `test_stats_with_nothing_pitched` + `test_stats_hit_rate_ignores_killed_rows`. |

---

## Verification

### 1. `python3 -m pytest recommend/tests/ -v`

```
platform darwin -- Python 3.13.14, pytest-9.1.1, pluggy-1.6.0
collected 51 items

test_history.py::test_sections_and_kind_filter PASSED
test_history.py::test_rec_log_included PASSED
test_history.py::test_out_file PASSED
test_history.py::test_rated_dedupes_conflicting_ratings PASSED
test_history.py::test_rated_agreeing_ratings_no_variants PASSED
test_history.py::test_rated_precedence_splits_stars_and_review PASSED
test_history.py::test_shells_includes_works_with_zero_records PASSED
test_history.py::test_counts_rated_counts_distinct_works_not_rows PASSED
test_history.py::test_index_line_count_matches_rated_count PASSED
test_history.py::test_index_marks_review_presence_and_stars PASSED
test_history.py::test_index_and_lookup_work_from_a_snapshot_file_alone PASSED
test_history.py::test_lookup_by_work_id_returns_full_review_text PASSED
test_history.py::test_lookup_by_title_is_case_insensitive_substring PASSED
test_history.py::test_lookup_by_creator PASSED
test_history.py::test_lookup_requires_a_filter PASSED
test_history.py::test_rated_same_source_watched_beats_watching PASSED
test_history.py::test_rating_variants_uses_resolved_rating_per_source PASSED
test_history.py::test_snapshot_kinds_flag_narrows_scope PASSED
test_history.py::test_snapshot_without_db_fails_loudly PASSED
test_precedence.py::test_source_rank_orders_known_sources PASSED
test_precedence.py::test_unknown_source_ranks_last PASSED
test_precedence.py::test_unknown_source_still_loses_to_every_known_one PASSED
test_precedence.py::test_empty_input_returns_none PASSED
test_precedence.py::test_two_unknown_sources_break_ties_alphabetically PASSED
test_precedence.py::test_rows_without_status_or_marked_at_still_resolve PASSED
test_precedence.py::test_sqlite_row_with_unselected_columns_is_tolerated PASSED
test_precedence.py::test_status_rank_prefers_watched_over_watching PASSED
test_precedence.py::test_same_source_tie_resolves_watched_over_watching PASSED
test_precedence.py::test_same_source_same_status_tie_resolves_to_most_recent PASSED
test_precedence.py::test_missing_marked_at_loses_to_a_dated_row_of_equal_rank PASSED
test_precedence.py::test_source_still_outranks_status PASSED
test_reclog.py::test_init_creates_table PASSED
test_reclog.py::test_log_and_check_by_ext_id PASSED
test_reclog.py::test_check_by_title_year PASSED
test_reclog.py::test_verdict_and_pending PASSED
test_reclog.py::test_verdict_rejects_bad_value PASSED
test_reclog.py::test_killed_rows_not_pending PASSED
test_reclog.py::test_check_title_without_year_exits_nonzero PASSED
test_reclog.py::test_stats_sealed_vs_actual_one_entry_per_recommendation PASSED
test_reclog.py::test_log_batch_missing_field_rejects_whole_batch PASSED
test_reclog.py::test_log_batch_multiple_bad_rows_all_named_at_once PASSED
test_reclog.py::test_predicted_stars_out_of_star_range_rejected PASSED
test_reclog.py::test_predicted_stars_zero_and_null_and_bounds PASSED
test_reclog.py::test_ddl_check_constraint_on_new_databases PASSED
test_reclog.py::test_log_batch_non_dict_row_fails_validator_not_traceback PASSED
test_reclog.py::test_log_batch_null_critic_killed_defaults_to_zero PASSED
test_reclog.py::test_log_batch_non_numeric_critic_killed_rejected PASSED
test_reclog.py::test_log_rollback_holds_when_the_insert_itself_fails PASSED
test_reclog.py::test_stats_with_nothing_pitched PASSED
test_reclog.py::test_stats_hit_rate_ignores_killed_rows PASSED
test_reclog.py::test_log_prints_inserted_ids_in_batch_order PASSED

============================== 51 passed in 3.28s ==============================
```

All 18 pre-existing tests still pass. The only change to an existing test
was adding a `creators` column to the two fixture `works` DDLs (and
naming columns in the INSERT rather than relying on positional tuples) —
the fixtures now track the real schema more closely, no assertion was
weakened or removed.

### 2. Real-DB smoke

```
$ python3 recommend/history.py --db media.db snapshot --out <sp>/snap.json
{"rated": 1702, "wishlist": 91, "shells": 222, "rec_log": 0}

$ python3 recommend/history.py index --snapshot <sp>/snap.json --out <sp>/index.txt
{"entries": 1702, "out": ".../index.txt"}

snap:   lines=39945  bytes=898237
index:  lines=1717   bytes=96710
        entry lines: 1702
        last line: # END OF INDEX — 1702 entries listed above.
```

**rated=1702, wishlist=91, shells=222 — confirmed.**

Index is **1,717 lines / 94KB**, comfortably inside the 2,000-line Read
cap, and 1,702 of those lines are entries (15 header lines + 1 sentinel).
It reads in one pass. Independent cross-checks against the brief's own
numbers: `awk '$3=="R"'` counts **558** works with review text (brief:
"558 with review text"); `awk '$2=="-"'` counts **93** watched-but-unrated
(brief: "the `stars is None` branch fires on 93 of 1,702 real entries").

Index sample:
```
  5958  4.0 R 2025  辐射 第二季  << Fallout
  4348    - . 2021  Hacks
  5949  3.0 R 2026  克拉克森的农场 第五季  << Clarkson's Farm
```

`lookup --work-id 5958` returns the full entry incl.
`"review": "水平仍在! 感觉有点脱离游戏了, 但是仍然精彩"`, stars, both
external ids, creators, and `"section": "rated"`.

`lookup --title "cLaRkSoN"` → 5 hits, all matched via `original_title`
while the display titles are Chinese — the case-insensitive
cross-language match works on real data.

`lookup --creator "诺兰"` → 13 hits (盗梦空间 4.0, 奥本海默 5.0,
星际穿越 4.0, 西部世界 第一季 5.0, …).

Live table verified untouched: `CREATE TABLE recommendations (` with no
`CHECK`, 0 rows. `reclog.py stats` on the real DB returns
`{"pitched": 0, "hits": 0, "hit_rate": null, "sealed_vs_actual": []}` —
no crash on the empty denominator.

### 3. Purity grep — verbatim

```
$ grep -inE "anping|emrick|下饭|尴尬|taste\.md" recommend/SCOUT.md recommend/CRITIC.md
(exit 1 — no output)
```

**Zero matches, including inside Source notes.** No defects to fix.

### 4. Enum literals and CLI-vs-argparse

`outcome`: `survive|kill|sendback|wishlist-note` — unchanged.
`kill_rule`: `fact|dedup|predicted|ask-fit|reason-quality|null` — unchanged;
each of the five appears exactly once as a kill directive, and
`wishlist-note` still never appears as a `kill_rule` value.
`verdict`: `interested|no|meh|watched` — unchanged in argparse choices and
in the DDL CHECK.

Every command in SKILL.md / SCOUT.md / README.md against the real parser:

| Documented | Parser | |
|---|---|---|
| `history.py --db media.db snapshot --out X` | `history.py [--db DB] {snapshot,index,lookup}`; `snapshot [--kinds] [--out]` | ok |
| `history.py index --snapshot X --out Y` | `index [--snapshot] [--kinds] [--out]` | ok |
| `history.py lookup --snapshot X --work-id N` | `lookup [--snapshot] [--kinds] [--work-id] [--title] [--creator]` | ok |
| `reclog.py --db media.db log --json X` | `log --json JSON` | ok |
| `reclog.py --db media.db verdict --id N --verdict V --note "..."` | `verdict --id ID --verdict {interested,no,meh,watched} [--note]` | ok |
| `reclog.py --db media.db pending` | `pending` | ok |
| `reclog.py --db media.db stats` | `stats` | ok |

`check` and `init` exist in the parser and are not invoked from SKILL.md
(check is a scout-side dedup tool, init is already applied) — not a
mismatch.

### 5. Destructive SQL and one-transaction

```
$ grep -inE "\b(DROP|DELETE|TRUNCATE|ALTER|REPLACE INTO|VACUUM)\b" \
    recommend/*.py .claude/skills/recommend/SKILL.md recommend/*.md
recommend/README.md:59:  `sqlite3 media.db "PRAGMA wal_checkpoint(TRUNCATE);"` →
recommend/SCOUT.md:378: ... don't silently drop the candidate ...
```

Both are false positives: the first is the project's own sanctioned WAL
checkpoint from the write ritual; the second is the English word "drop"
in prose. **No destructive SQL anywhere in the recommend system.**

`history.py` still reads in ONE transaction: exactly one `con.execute("BEGIN")`
(line 131) and one `con.execute("COMMIT")` (line 164), with the
external_ids, rated, wishlist, shells, and rec_log queries all inside.
The new `busy_timeout` PRAGMA is issued at connect time, outside and
before the transaction. `index`/`lookup` add no DB reads at all when
driven from `--snapshot`.

---

## Concerns for the controller

1. **Shells carry no `external_ids` in the snapshot, but the DB has them.**
   I documented this per the brief rather than changing it. Measured:
   all 222 shells have at least one external id in `media.db` (216 imdb,
   160 plex_guid, 147 tmdb_movie, 71 tmdb_tv). Because the one-transaction
   rule forbids re-reading the DB mid-run, a shell promoted to a dossier
   must have its ids re-resolved over the network — ids the DB already
   holds. Adding `external_ids` to the shells query is a two-line,
   strictly additive change that would remove that round-trip and make
   I1's channel materially cheaper. I did not do it because the brief
   explicitly said to *note* the absence, and changing snapshot shape
   without a ruling seemed worse than flagging it. **Your call.**

2. **The snapshot grew 13% (793KB → 898KB)** because `creators` is now
   carried, which is what makes `lookup --creator` possible. Nothing
   reads the snapshot linearly any more, so this is cheap — but it is a
   shape change and I would rather you know than discover it.

3. **The index fits today with ~283 lines of headroom** (1,717 of 2,000).
   It is rated-only, so it grows only as Anping rates more works — roughly
   1,700 → 2,000 is several years at the current rate. The `END OF INDEX`
   sentinel makes an eventual overrun loud rather than silent, and
   CRITIC.md tells the critic what to do about it, so this degrades
   safely. Worth revisiting if the rated count passes ~1,900.

4. **`plex_guid` is in `external_ids`, not `works.meta`.** The brief's
   "of the 222, ~160 carry a plex_guid" is correct, but I initially
   checked `works.meta` and got 0. Recorded so the next agent does not
   repeat the wrong query.

5. **SKILL.md's frontmatter `description` still contains 下饭** as an
   example free-text ask. That is an instance-flavored token in a
   non-README file. I left it deliberately: the purity rule as briefed
   scopes to SCOUT.md/CRITIC.md, it was there before this wave, and the
   description string is what drives skill triggering — editing it risks
   a behavior change for a cosmetic gain. Flagging in case you want it
   generalized.

6. **CRITIC.md now names blocked review sources** (Douban review pages,
   Letterboxd, Rotten Tomatoes, IMDb) inside item 5, because I8's sibling
   problem is that the critic never sees SCOUT.md and would otherwise not
   know *why* a dossier can honestly be evidence-thin. These are
   infrastructure facts, not user facts, so I read this as
   purity-compatible — but it is a judgment call and the purity grep
   would not catch it either way.

---

# Addendum — coordinator rulings applied (2026-08-23)

Four rulings received. One required a change (shells ids); three
accepted what was already built, with one carrying a documentation
follow-up. Both were done.

## Ruling 1 — shells ids: TAKEN

`history.py` `snapshot` now attaches the ids `media.db` already holds to
every shell entry, using the same `ext` map already built for `rated`
and `wishlist`. The additive change, as instructed — the SQL, the
section's membership, and the counts are all untouched:

```python
shells = [dict(r, external_ids=ext.get(r["work_id"], {}))
          for r in con.execute(f"""
    SELECT w.id AS work_id, w.kind, w.title, w.year,
           COALESCE(w.creators,'') AS creators
    FROM works w
    ...
```

**Measured coverage is better than the review estimated: 222/222 shells
carry at least one id**, not 216/222. The 216 figure was imdb-specific.
Per-namespace: imdb 216, plex_guid 160, tmdb_movie 147, tmdb_tv 71 —
so per-*namespace* coverage is partial while per-*entry* coverage is
currently complete. I corrected that claim in all three places rather
than repeating the review's figure, and kept the empty-`external_ids`
handling path in the prose anyway: complete coverage today is a fact
about the data, not a guarantee about tomorrow, and a future shell can
arrive bare.

Prose updated to match in the three places that previously asserted the
absence:
- `recommend/history.py` docstring — shells section rewritten; states the
  ids are stored and were verified at source on load, so using them
  satisfies the project's verify-before-you-write hard rule.
- `recommend/SCOUT.md` §2 — second shells caveat rewritten from "carry NO
  `external_ids`" to "carry `external_ids` and you should use them",
  keeping the fallback for an empty dict.
- `recommend/README.md` — section retitled "Shells and their ids" with
  the measured per-namespace numbers.

Two new tests:
- `test_shells_carry_external_ids_when_the_db_has_them` — a shell with
  two ids gets both; a shell with none comes back with an empty dict,
  **present, not a missing key** (so consumers can index it
  unconditionally).
- `test_lookup_returns_shell_ids` — the ids survive into `lookup`, which
  is how the scout and critic actually reach a shell's detail.

## Ruling 3 — sentinel accepted; ~1,900 threshold recorded

Added a "SIZE BUDGET — why the last line is a sentinel" block to
`history.py`'s module docstring: the 2,000-line read cap, the current
1,717 lines (1,702 entries + 15 header + 1 sentinel), the ~283 lines of
headroom, and the explicit instruction — **revisit once the rated count
passes ~1,900**, paginating or splitting rather than letting the index
silently cross the cap. It closes on the distinction that matters: the
sentinel converts the overrun from silent to loud, it does not remove
the need to act on it.

## Rulings 2 and 4, and `下饭` — accepted, no action

No changes made to `creators` in the snapshot, to CRITIC.md's naming of
the blocked review surfaces, or to SKILL.md's frontmatter.

## Re-verification after the change

```
$ python3 -m pytest recommend/tests/ -q
53 passed in 3.43s
```

53/53 (was 51/51; +2 for the new shells-ids tests). No existing test
changed or was weakened.

```
$ python3 recommend/history.py --db media.db snapshot --out <sp>/snap.json
{"rated": 1702, "wishlist": 91, "shells": 222, "rec_log": 0}
```

**Counts unchanged — `rated=1702, wishlist=91, shells=222` confirmed
again after the change.** Membership of the shells section did not move;
only the fields on each entry did.

```
shells keys: ['creators', 'external_ids', 'kind', 'title', 'work_id', 'year']
shells with ids: 222/222   without: 0
by namespace: {'imdb': 216, 'plex_guid': 160, 'tmdb_movie': 147, 'tmdb_tv': 71}
sample: 439 早间新闻 {'tmdb_tv': '90282', 'imdb': 'tt7203552'}
```

These per-namespace numbers match the direct SQL count against
`external_ids` exactly, so the snapshot is reproducing the DB rather
than inventing anything.

Sizes: snapshot 924,318 bytes / 40,983 lines (was 898,237 / 39,945 —
+26KB for the ids). **Index unchanged at 1,717 lines / 96,710 bytes**,
since the index is rated-only and the shells change cannot touch it.

Standing invariants re-checked after the change:

| Check | Result |
|---|---|
| Purity grep on SCOUT.md + CRITIC.md | no matches |
| Destructive SQL in `recommend/*.py` | none |
| `history.py` transaction count | exactly 1 `BEGIN`, 1 `COMMIT` |
| Live `recommendations` table | 0 rows; only CHECK is the pre-existing `verdict` one; `predicted_stars REAL` still bare — never rebuilt |

Final state: 53/53 tests, all C1/I1–I11/minor findings applied, all four
coordinator rulings actioned.
