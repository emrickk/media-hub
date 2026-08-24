# HANDOFF — media-hub recommend system

**Written:** 2026-08-23, updated 2026-08-24 for the chat-history product MVP.
**For:** any agent (Codex or otherwise) picking this up cold. Read this file
top to bottom before touching anything. It is written to be self-contained —
you do not need the originating conversation.

**Owner:** Anping (Douban user `Emrick`). Working dir for every command in
this document: `/Users/anping/Documents/Stuff/AI Space/media-hub` (referred
to below as the **repo root**).

---

## 1. What this is

A local-first film/TV recommendation system. A new user gives the repository
to Codex or Claude Code, permits access to selected conversation history, and
the agent builds a cautious taste profile before answering a free-text ask
(`我最近看了 the office，有没有别的推荐？`), it searches external catalogs,
and a deliberately **blind critic** rejects weak candidates before the user
sees them. The original Anping instance still uses his calibrated rated history;
a new user's true cold start remains provisional until ratings accumulate.

Its unusual property: **most of the program is prose.** `recommend/SCOUT.md`
and `recommend/CRITIC.md` are read by an LLM at runtime as its operating
contract. A wording ambiguity in those files is a runtime bug and must be
treated as harshly as a code defect. The Python files are only the
deterministic I/O edges.

**Status: COMPLETE and running.** The lean product path is
`README.md` → `skills/media-taste/SKILL.md` → `recommend/PROFILER.md` →
scout → blind critic → rich HTML → feedback. v1 (judgment layer) is calibrated;
v2 (candidate pool + platform-CF harvesting) built, fully harvested (298/298
Douban anchors, 6,473 candidates), and wired to a monthly scheduled refresh.
The system has run end-to-end on four real asks. Remaining work is deferred
scope only (see §8/§9), not unfinished build.

---

## 2. Read these, in this order

1. `docs/superpowers/specs/2026-08-23-media-recommend-design.md` — v1 design.
   Part A = user-agnostic engine, Part B = profile schema, Part C = Anping's
   instance bindings.
2. `docs/superpowers/specs/2026-08-23-media-recommend-v2-pool-design.md` —
   v2 (candidate pool + platform-CF). **Amends** v1; its §6 pins exactly what
   v1 keeps unchanged.
3. `docs/superpowers/plans/2026-08-24-chat-history-product.md` — the lean
   product plan now implemented. The older enrichment plan is superseded.
4. `docs/superpowers/decisions/2026-08-23-media-recommend-decision-log.md` —
   every ruling made during the build, each with its reasoning and what it
   costs if wrong. Read it before overriding anything.
5. `recommend/README.md` — instance bindings (profile path, DB, pitch
   target, write ritual, helper CLIs).
6. `../CLAUDE.md` and `./ARCHITECTURE.md`, `./STATE.md` — house rules for
   the wider media system. STATE.md is the cross-machine handoff for the
   whole repo; update it when you change state.

---

## 3. Current state (verified 2026-08-23)

**Files** (all under repo root):
```
recommend/SCOUT.md        retrieval + funnel contract   (engine, user-agnostic)
recommend/CRITIC.md       blind adversarial gate        (engine, user-agnostic)
recommend/PROFILER.md     direct chat-history distillation contract
recommend/README.md       runtime bindings; new-user personal state stays under ignored profile/
recommend/DIGEST-INTENT.md  stored default ask for digest mode
recommend/history.py      one-transaction history snapshot + index/lookup/distribution/cell/percentile-of
recommend/reclog.py       the recommendations log (the system's ONLY write surface)
recommend/bootstrap.py    minimal first-run database creation
recommend/render.py       rich cards + copyable feedback packet
recommend/precedence.py   shared source-precedence helper
recommend/tests/          76 tests, all passing
recommend/logs/           per-run funnel logs (audit trail; a deliverable, not bookkeeping)
.claude/skills/recommend/SKILL.md   the /recommend orchestration entry point
skills/media-taste/SKILL.md         clone-and-run agent entry point
```

**Verify it still works:**
```
python3 -m pytest recommend/tests/ -q          # expect: 158 passed
sqlite3 media.db "select count(*) from recommendations;"   # expect: 24
python3 recommend/history.py --db media.db snapshot --out /tmp/s.json
# expect: {"rated": 1702, "wishlist": 91, "shells": 222, "rec_log": 24}
```

**Database:** `recommendations` table holds 24 rows — 13 survivors, 11
killed, 0 verdicts recorded yet. Rows 1–16 each carry BOTH the original
uncalibrated prediction (`dossier.critic_uncalibrated`) and the calibrated
one (`dossier.critic`), so both systems can be scored when Anping rates
something. Rows 17–24 are re-sweep candidates (calibrated only).

---

## 4. How it works (the parts that matter)

**Pipeline:** ask → scout (interpret, snapshot history, sweep catalogs,
narrow with a logged reason per elimination, build ~8 dossiers) → **critic
in a fresh context that never sees the scout's search** → pitch → verdicts
logged.

**The critic's blindness is load-bearing.** It receives only: CRITIC.md, the
profile (`../TASTE.md`), the history index, the rating distribution, each
candidate's cell, and the dossiers. It must never receive the funnel log,
the scout's transcript, or any account of search effort — its own contract
tells it to refuse and report a violation. Preserve this.

**Judgment is percentile-calibrated, not an absolute star floor.** This is
the most important thing to understand, and the reason for it is empirical:

- Anping's ratings: 4★ is his *mode* (41.7%); **60.5% of everything he has
  ever rated is ≥4★**. An absolute ≥4★ gate therefore admits the majority
  of his viewing and killed nothing (16/16 passed in the first real run).
- He is generous to series and harsh on films. TV: 74% reach ≥4★, 31% earn
  a full 5. Films released 2020-26: only 44% reach ≥4★ and just 4% get a 5.
- So the target is **the 70th percentile of the candidate's own cell**
  (`recommend/README.md` carries the binding). This auto-adjusts: a 4★ film
  clears (74.8th pct) while a 4★ series does not (54.9th) — correctly, since
  a merely-good series is unremarkable for him.

**MID-RANK PERCENTILE CONVENTION — do not "simplify" this.** His ratings are
lumpy whole stars, so every prediction sits inside a large tie band. A 4★
recent film spans the 56.2nd–93.3rd percentile. Under the naive "count ≤
star" convention it scores 93.3 and sails through any target — silently
restoring the broken gate. Mid-rank scores it 74.8. `percentile_of` uses
`(count_below + count_equal/2)/n`. There is a test that would fail if
someone reverts this; **if a test about percentiles fails, fix the test's
invariant, never the convention** (the ladder and `percentile_of` are
genuinely not inverses — that is documented in history.py's docstring).

**Signal hierarchy:** a star rating IS Anping's verdict and is the strongest
evidence about him. A written comment merely explains a verdict and never
outranks one. **Two-thirds of his history (1,144 of 1,702) has no comment,
and he writes more often when annoyed** (commented mean 3.59 vs silent 3.71;
1-2★ is 14.2% of commented works vs 7.1% of silent) — so reasoning only from
quotable entries samples a skewed subset. This was a real bug he caught.

**Evidence tiers, and why thin evidence must not kill.** Review pages are
mostly unreachable from this machine (see §6). So: Tier 1 = verbatim quotes
(TMDB `/reviews` for English; NeoDB review chain for Chinese), Tier 2 =
attributable characterization (WebSearch snippets), Tier 3 = metadata only.
Thin evidence **widens the confidence band; it never lowers the central
estimate.** A candidate is rejected for evidence it is *bad*, never for the
*absence* of evidence — otherwise the system silently punishes titles whose
reviews merely happen to be unreachable, which falls hardest on
Chinese-language films and violates the project's Chinese-first rule.

---

## 5. v2 — complete

Spec: `docs/superpowers/specs/2026-08-23-media-recommend-v2-pool-design.md`.
Plan: `docs/superpowers/plans/2026-08-23-media-recommend-v2-pool.md`.
Decision log: `docs/superpowers/decisions/2026-08-23-media-recommend-v2-decision-log.md`.

**Why v2 exists.** v1 re-derived a static corpus on every ask (13-16 min per
scout run, ~80% of it sequential review fetching for candidates the critic then
rejected), and its automatic re-sweep was economically indefensible: a
70th-percentile gate passes ~30% by construction, so 8 dossiers yield ~2.4
expected survivors against a floor of 2.

**What exists:**
```
recommend/pool.py            candidate_pool table + CLI (init/upsert/query/
                             attach-evidence/suppress-sync/stats)
recommend/harvest_tmdb.py    TMDB CF harvest (anchors/fetch/transform)
recommend/harvest_douban.py  Douban CF harvest via the mobile rexxar JSON API
recommend/render.py          pitch page (SKILL.md step 5b) — carries id_warnings
recommend/run_digest.sh      one-command monthly data refresh
recommend/raw/tmdb|douban/   dated raw snapshots + douban checkpoint (298/298)
```
Pool: **6,473 candidates** (film 4,788 / tv 1,685); by channel tmdb_rec 3,265,
douban_rec 3,160, tmdb_discover_recent 50; 1,019 suppressed (watched or
previously rejected). 99.7% of douban_rec rows carry genre tags. A pool query
runs in ~0.04s, replacing 13-16 minutes of network sweeping.

**Douban CF is the important surface.** Only 7 of Anping's 162 top-rated series
carry a TMDB id while all 162 carry a Douban id, so Douban is the TV lane's ONLY
collaborative-filtering signal. The desktop `/subject/<id>/` page is behind a JS
proof-of-work challenge and is NOT usable. The working path (also used by
`mediahub.py cmd_enrich_douban`) is the **mobile rexxar JSON API**:
```
GET https://m.douban.com/rexxar/api/v2/movie/{douban_id}/recommendations?for_mobile=1
    User-Agent: mediahub.py's MOBILE_UA
    Accept: application/json, text/plain, */*
    Referer: https://m.douban.com/movie/subject/{douban_id}/
```
Returns a JSON **list** of 20 items (`alg_json, card_subtitle, id, interest,
pic, rating, sharing_url, title, type, uri, url`). `type` gives movie/tv,
`rating.value` the Douban score, `card_subtitle`'s leading 4-digit token the
year. Reuse `mediahub.py`'s `polite_get`, 403/302 stop, and 8-failure circuit
breaker — do not write new fetch machinery. The full 298-anchor harvest
completed with zero blocks and no breaker trips.

**Standing policies set by Anping, not tuning knobs:**
- **All candidates are external.** The library is never a candidate source —
  recommending things he already owns is inventory management, not discovery.
  Library presence is a dedup/context note only.
- **Interactive asks do not auto-re-sweep.** A thin slate is reported honestly
  with an offer to go deeper. Auto-resweep is digest-only.

**Automation:** `monthly-recommend-digest` scheduled task (3rd of each month,
04:17 local), sequenced after the existing `monthly-douban-backup` so it
harvests from fresh anchors. It runs `run_digest.sh` then the `/recommend`
skill in digest mode, and reports `id_warnings`.

## 6. Environment gotchas that will waste your time

- **There is NO git in this repo.** It lives in iCloud Documents. Do not
  `git init`. Verification replaces commits: tests + greps + real runs. The
  decision log in `docs/superpowers/decisions/` is the substitute for git
  history — keep appending to it.
- **Multiple Claude/agent sessions run on this machine concurrently.**
  Before ANY media.db write: `lsof media.db*` (stop if another writer holds
  it), check STATE.md lane ownership, `PRAGMA wal_checkpoint(TRUNCATE)`,
  then `cp media.db backups/media-recommend-$(date +%Y%m%d-%H%M%S).db`.
- **iCloud produces " 2.jpg"-style conflict copies.** Watch for them.
- **Credentials:** `../douban-export/sources/sources.env` holds
  `TMDB_API_KEY`. Sourcing it prints a harmless `command not found` on the
  Spotify line. **Never print the key.**
- **Blocked/unreachable from here** (all empirically probed — don't re-probe
  without reason, and don't conclude "no reviews exist" from a failure):
  - Douban `/subject/<id>/comments` and `/reviews` — JS anti-bot challenge,
    NOT bypassable, even with the project's own curl-cffi pattern.
  - Letterboxd — 403 to WebFetch; 200 to curl only with a full header set.
  - Rotten Tomatoes — 200 but JS-rendered, no text in the HTML.
  - IMDb, RogerEbert — 403.
  - Douban `/tag/<term>` — 404, the URL structure is retired. Replacement:
    `movie.douban.com/j/new_search_subjects?tags=<term>` with a
    `Referer: https://movie.douban.com/explore` header — works ONCE then
    rate-limits hard. One call per session, long backoff.
- **NeoDB traps:** `/api/item/{uuid}` 404s for TV seasons — the working path
  is category-typed (`/api/tv/season/{uuid}`). A 404 here reads as "no
  reviews exist" and would become a false documented-negative on exactly
  the Chinese titles NeoDB exists to serve. Its JSON contains raw control
  characters (parse with `strict=False`), and its review endpoint 403s to
  `urllib` but 200s to plain `curl` (UA gate).
- **`history.py lookup --title` is substring-matched** and returns false
  positives on short titles — verify by `work_id`.
- Full probe findings are in `recommend/SCOUT.md`'s "Source notes" section.

---

## 7. House rules (violations have burned this project before)

- **Never write an external id from memory.** Verify against the source page
  first. A wrongly-recalled tt id corrupted data once.
- **Chinese-only content is first-class.** douban_id + title + year is a
  definitive identity; absence from IMDb/TMDB is a documented negative, not
  a failure.
- **Raw-first:** every network pull lands as a dated immutable snapshot
  before any transformation.
- **Non-destructive:** loaders upsert; never bulk-delete. Pool rows get
  suppressed, never deleted.
- **One writer at a time** (see §6).
- **Engine purity:** `SCOUT.md` and `CRITIC.md` must contain ZERO
  user-specific facts — no name, no tastes, no naming the profile file. They
  say "the profile document" / "the user". `README.md` and `SKILL.md` are the
  instance layer and may hold specifics. Check with:
  `grep -inE "anping|emrick|下饭|尴尬|taste\.md" recommend/SCOUT.md recommend/CRITIC.md`
  (matches inside SCOUT.md's Source notes describing probed URLs are fine).
- **Report every pass with counts + a machine-readable list of skips/failures.**
- **Anping's working style:** zero legwork — do every step yourself, never
  hand him a step list. Answer exactly what he asks, at full effort. Surface
  unexpected diffs and get confirmation before loading them.

---

## 8. Open items for Anping (do not decide these yourself)

1. **His star rating for The Office (US).** `TASTE.md` records it as 想看
   (wanted, not watched); he has since watched it and loved it. media.db has
   no record. **Do not invent a rating** — ask.
2. **Verdicts on the 13 live candidates.** `python3 recommend/reclog.py --db
   media.db pending` lists them. Recording verdicts is what turns the sealed
   predictions into a measurable accuracy score — currently we have zero
   evidence the predictions are any good, only that they are plausible.
3. **What 别的推荐 meant** in his Office ask: "more shows like The Office"
   or "other things I'd love"? The re-sweep assumed the latter and returned
   documentaries. Under the calibrated gate the former mostly fails — Parks
   and Rec, What We Do in the Shadows and Nathan for You all landed at 4.5★
   but only the 66th–68th percentile.
4. **v2 go-ahead** and, separately, **explicit approval before adding
   harvest steps to the monthly scheduled pipeline** (a standing-automation
   change).
5. **TASTE.md is his voice and is NOT co-edited — ever.** A recalibration
   attempt on 2026-08-23 (population-scale hypothesis mining, N1-N6) was
   rejected on principle and the rejection was adopted as design: outcome
   statistics are properties of the prediction problem, not of the person, so
   never present him with claims about his own taste to ratify. Calibration
   runs through the verdict loop instead (light = pitch verdicts, heavy =
   post-watch ratings vs sealed predictions), and mispredictions update the
   ENGINE's priors, never his file. See the v1 spec's 2026-08-23 Part B
   amendment and `analysis/taste-recalibration-hypotheses-2026-08-23.md`
   (retained as prediction priors, retracted as taste claims). If he ever
   wants self-understanding material, that is a distinct genre: a readable
   portrait in his own words with observations framed as questions — not a
   regression table.

---

## 9. Known weaknesses (honest list)

- **No accuracy evidence yet.** 24 sealed predictions, 0 verdicts.
- **The gate has been exercised on exactly two asks.** The 0%→46% kill rate
  shift is one data point, not a validated calibration.
- **`p_top` has no consumer.** It is preserved inside the dossier JSON but
  `reclog.py stats` only scores `predicted_stars`. Scoring method deferred.
- **The index has ~283 lines of headroom** (1,717 of a 2,000-line read cap).
  Past ~1,900 rated works it must paginate or split. There is an
  `END OF INDEX` sentinel so an overrun fails loudly instead of silently —
  that silent-truncation failure mode is exactly what the index exists to
  prevent, so do not remove the sentinel.
- **Games, music and books lanes are not built.** Games need their own taste
  calibration first (playtime ≠ love).
- **v1's pitch-cap selection was, for one run, an unlogged hand-cut by the
  orchestrator** — the only filter in the pipeline that discarded candidates
  without a written reason. Selection has since moved into the critic, which
  ranks and logs a reason per candidate. Do not move it back out.
