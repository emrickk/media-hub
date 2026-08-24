# SCOUT — retrieval & funnel contract (engine; user-agnostic)

Implements spec Part A §A3 steps 1–4. Instance bindings (which profile,
which DB, which kinds, key paths) live in README.md — this document never
names a specific user or their tastes.

## 0. Session setup
1. Read the profile document (binding in README.md) in full.
2. Take the history snapshot FIRST — before any network I/O:
   `python3 recommend/history.py --db <db> snapshot --out <scratchpad>/snap.json`
   Then build the critic's index from it (no DB access, so order after
   the snapshot is all that matters):
   `python3 recommend/history.py index --snapshot <scratchpad>/snap.json --out <scratchpad>/index.txt`
   The snapshot is far too large to read linearly — you too should work
   it with `history.py lookup --snapshot <scratchpad>/snap.json` rather
   than opening the file, whenever you need one work's detail.
3. Open a funnel log at `recommend/logs/<YYYY-MM-DD>-<slug>.md` (slug from
   the ask). Every stage below appends to it as it happens.

## Run modes

Every run is either **interactive** (a live ask, target ≤5 minutes) or
**digest** (the scheduled, unattended monthly sweep — deep, no time
pressure). The orchestrator tells you which one this session is; absent
that, an ask-bearing session is interactive and an empty-ask /
DIGEST-INTENT.md session (§1) is digest. §§1–6 below are shared by both
modes; this section is the map of where they diverge.

**Interactive — pool-first, budget ≤~10 network calls, no auto-resweep.**
The `candidate_pool` table (populated by the digest harvest — harvester
bindings in README.md) already holds a cached, provenance-carrying
slice of TMDB's and Douban's own collaborative-filtering output. An
interactive ask queries it locally instead of re-deriving a corpus that
has not changed since the last harvest:
1. §1 interpret + the mandatory clarify check.
2. §2 history snapshot, as always before any network I/O — this also
   unlocks §3 tier 1, a **local, no-network** pool query.
3. §3 sweep: tier 1 (pool query) first — the only generation channel
   interactive mode needs, most of the time. Tier 2 (targeted top-up)
   fires only for a logged pool gap and stays inside the ~10-call
   budget. Tier 3 (LLM-generated queries) and the editorial pass (§3d)
   do not run interactively at all.
4. §4 narrow: shortlist directly from the pool **knowing the bar**
   (§4's "shortlist against the target") rather than the full Cut
   1/Cut 2 funnel — that funnel is a digest-mode cost.
5. Evidence: read each shortlisted candidate's cached evidence first
   (§3c); fetch only what's missing — most of the ~10-call budget —
   then write it back via `pool.py attach-evidence`.
6. §5 dossiers, §6 handoff to the critic — unchanged.
7. **No automatic re-sweep.** If fewer candidates survive the critic
   than the floor, report the thin slate honestly in the pitch and
   offer to go deeper (a user-approved extra pass) instead of silently
   re-running tiers 2–3 the way digest does. This is a deliberate
   behavior change from v1: a 70th-percentile gate passes ~30% by
   construction, so the old automatic re-sweep fired routinely, not
   exceptionally, costing another 15–20 minutes for one or two more
   titles — indefensible against a ≤5-minute interactive target.

**Digest — harvest/refresh first, then the full deep funnel, auto-resweep
allowed.** Before scouting starts, the orchestrator runs the harvest
step (`harvest_tmdb`, `harvest_douban`, `pool.py upsert`,
`suppress-sync` — SKILL.md's digest step 0; SCOUT.md does not invoke the
harvesters itself). Once the pool is refreshed, digest proceeds through
§§1–6 as the full v1-style funnel: §3's sweep still leads with the pool
(tier 1) but legitimately reaches tiers 2–3 and the editorial pass at
full scale (the ~100–200 gathered-title target in §3 and the Cut 1/Cut 2
stages in §4 are digest-scale figures), and a critic-triggered re-sweep
(floor rule) proceeds automatically, capped at one per SKILL.md's
orchestration.

Both modes converge at §6 handoff and afterward — the critic's contract
does not know or care which mode produced its dossiers.

## 1. Interpret the ask
- The ask is free text; interpret it as a whole. There is NO taxonomy and
  no fixed set of axes — whatever the ask expresses (a genre, a mood, a
  reference title, "surprise me", "something bad on purpose") IS the
  target. Do not force it into any schema.
- **Clarifying-question check — mandatory, before any sweeping.** Every
  interactive run, explicitly decide and log ONE of these two outcomes —
  do not skip the check, and do not silently pick a reading because a
  question feels like friction:
  1. **Does the ask admit two materially different readings whose choice
     would change most of the resulting slate** — not a minor emphasis
     shift, a genuinely different candidate set? If yes: ask the user
     ONE question naming the fork, then **wait for the answer** before
     doing any §2/§3 work. Do not guess and proceed "to save time."
  2. If no: proceed on your working interpretation, stated in the pitch.
  Log the decision either way in the funnel log — `clarify: asked
  "<question>"` or `clarify: not needed — <one-line reason>` — so a
  reviewer can see the check actually ran. This check exists because a
  merely-permitted question does not get asked: three real interactive
  runs under the old "may ask" wording asked zero questions, including
  one ask that genuinely split two ways ("more shows like X" vs "other
  things I'd love") and was silently guessed on instead.
- If the ask is empty (digest mode), read DIGEST-INTENT.md as the ask.
  Digest mode never asks the clarifying question — no one is present to
  answer it — so log `clarify: skipped — digest mode, no user present`
  and proceed on the stored interpretation.
- Write the interpretation into the funnel log.

## 2. Work the history (the primary evidence base)
From snap.json, assemble and log:
- **Neighborhood**: rated items relevant to the interpretation — semantic
  relevance judged by you from titles + review text, not string matching.
  Include both loved and hated items; the hated ones sharpen the target.
- **Anchors**: the high-star neighborhood exemplars (per the profile's
  rating semantics). These seed retrieval.
- **Anti-anchors**: low-star neighbors; their review text tells you what
  failure looks like in this region.
- **Shells — context and deduplication only, never a retrieval channel.
  This is standing policy, not a temporary tuning choice.** Every
  candidate this system pitches must originate outside the user's
  existing library, because a recommendation's entire purpose is a
  discovery — a title he does not already have — and a library item is
  by definition not that. The snapshot's `shells` section (every
  in-scope work with NO watch/wish record at all — in practice,
  overwhelmingly titles that entered the library some other way and
  were never watched) is therefore never swept for the ask and shell
  titles never compete for a pitch slot; §3's channel hierarchy has no
  shells tier. Two purposes remain, and only these two:
  1. **Dedup / "you already have this."** When a candidate the pool or a
     live external fetch surfaced on its own merits happens to already
     be a shell, that coincidence is worth a note in the pitch (he may
     already own the disc/file) — never the reason the candidate was
     found, and never grounds to originate a candidate from the shell
     side.
  2. **Taste context.** An acquisition is still a taste signal — it was
     *already deliberately chosen* by this user, before any
     recommendation existed — and is fair evidence when judging a pool
     candidate's fit, the same way a rated work's review text is.
  Two caveats to state honestly rather than paper over when using
  shells this way. First, "shell" asserts only the *absence of a
  watch/wish record* — that is true of most library-present works but
  is not the same claim, and the snapshot does not carry the
  library-presence flag, so never tell the user a shell is definitely
  on hand without checking. Second, shells carry `external_ids` and you
  should use them for the dedup match — they are stored ids that were
  verified at source when they were loaded, so trusting them is reading
  the database, not recalling an id from memory. Coverage is good but
  not guaranteed: where a shell's `external_ids` comes back empty,
  resolve its identity at source from title + year like any other
  candidate, per the identity rules in §3.
- **Excluded**: every watched/watching item; every rec_log row with
  verdict `no` (never re-enter the funnel); wishlist items (they can only
  appear in the pitch as an "already on your list" note). Shells are a
  different case, not a candidate-exclusion rule at all — they were
  never eligible to enter the funnel as candidates in the first place
  (Shells, above), so there is nothing here to exclude. If a
  pool-or-live-sourced candidate happens to coincide with a shell,
  library presence does not disqualify it; it is folded into the pitch
  as a "you already have this" note, per the Shells bullet.
- **TV season/parent verification is part of this exclusion, and it is
  mandatory, not optional.** This database stores TV one row per
  Douban/NeoDB season plus a show-level parent row that never carries
  its own record — so a title can look unwatched (no direct hit in
  `rated`/`wishlist`/`shells`) while a DIFFERENT season of the same show
  is fully watched. Checking this by hand — stripping `第N季` off the
  title and grepping the history index per candidate — is slow and
  error-prone, and it is exactly what failed in a live run that pitched
  Only Murders in the Building, Brooklyn Nine-Nine, and Poker Face as
  fresh discoveries though all three were already watched to completion.
  Do not check this by hand. Use `history.py sibling-seasons` instead
  (command form and its one real limitation are in §4, at the point in
  the funnel where it must run).

## 3. Sweep — channel hierarchy
Channels form a **strict hierarchy**, not an equally-weighted mix. Work
top-down; drop to the next tier only when the one above has been tried
and comes up short for the ask — a logged gap — never as a default
starting point. Log every query and its yield regardless of tier.

1. **Candidate pool query — local, no network.** `python3 recommend/pool.py
   --db <db> query --kind <k> --year-from <y> --year-to <y> --tag <t>
   --channel <c> ...` (`--tag` and `--channel` both repeatable, OR'd
   across repeats). This is the default channel and, in interactive mode,
   usually the ONLY generation channel needed: the pool already holds
   TMDB `/recommendations` and Douban 也喜欢 CF output harvested across
   (ideally) every anchor and refreshed monthly (harvester bindings in
   README.md). Query broadly for the ask's territory — genre/kind/year
   tags, or no filter at all for an open-ended ask — and let pool
   candidates compete on merit exactly as v1's gathered pool did.
2. **Targeted top-up — only for a logged pool gap.** If the pool
   genuinely lacks the ask's territory (a niche combination no anchor's
   neighborhood reaches, or a title released after the last harvest), run
   narrow live fetches — the anchor-expansion and generated-query
   channels below (a, b) — but log each one as `pool gap: <what was
   missing>` in the funnel log (this is what tells the next harvest what
   to add) and stay inside the run mode's network-call budget (see "Run
   modes" below).
3. **LLM-generated keyword/tag queries — last resort only.** Measured the
   weakest retrieval surface (Source notes below); reach for this only
   when tiers 1–2 leave the ask's territory still thin, and log the
   query and yield like any other channel.

**The library is never a candidate-generation channel, in either run
mode.** All candidates come from the external candidate pool and,
when the pool is genuinely thin for an ask, a targeted live fetch from
the same external sources (TMDB, Douban) — never from `shells` or any
other in-library surface. See §2's Shells bullet for the one remaining,
non-retrieval use of library data (dedup/context).

**Web search is removed as a candidate-generation channel in interactive
mode.** It survives in exactly one place: the digest-mode editorial pass
(d, below) — its one proven niche is recent-Chinese-cinema recency,
where TMDB discover under-serves and Douban rate-limits hard. It is
never a fallback for tiers 1–3, and never an evidence-tier source ahead
of cached NeoDB/TMDB review text (c, below, and §5).

Digest mode's target of ~100–200 gathered titles (v1's figure) still
describes the full sweep across all three tiers at digest scale;
interactive mode does not aim for this number at all — see "Run modes".

The channel mechanics below are unchanged in substance from v1 and are
where tiers 2–3 (and digest's larger sweep) do their work:
a. **Anchor expansion**: similar/recommendations APIs for each anchor
   (e.g. TMDB `/movie/{id}/similar`, `/tv/{id}/recommendations`); works
   by the creators/directors/writers of top anchors. In interactive mode
   this is tier-2 top-up only — the pool query already covers anchors
   the last harvest reached.
b. **Generated queries**: derive search keywords/tags from ask ×
   neighborhood; run against catalog surfaces (TMDB discover with
   genre/keyword filters, Douban tag pages, NeoDB search). See
   "Source notes" below for which surfaces retrieve well. Tier-2/3 only
   in interactive mode.
c. **Review mining — tiered, by language.** **Pool evidence cache — check
   first, in BOTH run modes.** Before fetching any evidence below for a
   candidate, check whether its pool row already carries cached evidence
   (a non-null `evidence` field — `pool.py query --has-evidence`, or
   inspect the row directly). Read cached evidence first; fetch only
   what is missing. After fetching new evidence, write it back
   permanently so no future ask re-fetches it: `python3 recommend/pool.py
   --db <db> attach-evidence --id <pool row id> --json <path to the new
   evidence entries>`. This is what makes the pool worth having — evidence
   is fetched once, ever, per candidate. Work highest-tier-first:
   - **Tier 1, verbatim quotes**: English-language titles — TMDB
     `/movie/{id}/reviews`, `/tv/{id}/reviews` (100% coverage measured on
     English titles; ~0% genuine Chinese-language criticism despite
     returning HTTP 200 — don't rely on it for Chinese titles). Chinese-
     language titles — NeoDB `/api/item/{uuid}/posts/?type=review` then
     `/api/review/{uuid}` (anonymous, real full-length Chinese review
     essays, ~80% coverage); this is the primary channel for
     Chinese-language titles.
   - **Tier 2, attributable characterization, no body quote**: WebSearch
     snippets — aggregate scores, thematic characterization, review-
     essay titles. No page fetch, not blocked.
   - **Tier 3, metadata floor**: vote_average/vote_count, keywords, tags,
     overview. Not review evidence — a confidence ceiling only.
   - **Documented negatives, do not retry**: Douban HTML reviews/comments
     (JS challenge, not bypassable anonymously), Letterboxd (403), Rotten
     Tomatoes (JS-rendered, empty), IMDb (403).
   Reviewers naming neighbors ("does what X does, better") remains a
   retrieval channel no tag search replicates — mine it at whichever tier
   you reach.
d. **Editorial — digest mode only.** Web-search curated/critic lists
   matching the ask. Not available interactively (see the removal note
   above): interactive review evidence is TMDB/NeoDB per §3c, never a
   web-search editorial sweep.
e. **Recency**: notable releases since the last run. Digest mode covers
   this via `harvest_tmdb`'s recency discover pass and the editorial
   pass (d); interactive mode only reaches for a live recency fetch as a
   tier-2 top-up, logged as a pool gap like any other.
Rules: identity is Chinese-first where applicable (douban id + title +
year definitive; absence from IMDb/TMDB is a documented negative).
Dedup the gathered pool against §2 Excluded before narrowing.

## 4. Narrow — progressive cuts, progressive evidence

**Interactive mode: shortlist against the target, not a fixed funnel.**
The orchestrator gives you the pitch target (a percentile) and pitch
cap — the same values it will separately hand the critic (SKILL.md step
3) — and, for each pool candidate under real consideration, that
candidate's population cell (`python3 recommend/history.py cell
--snapshot <snap.json> --kind <k> --year <y>`). Use them to shortlist:
before spending evidence-fetch budget on a candidate, form your own
case-law judgment — from the §2 neighborhood/anti-anchors and the
candidate's tags/aggregates already sitting in its pool row — of
whether it can plausibly clear the target within its cell. Drop what
you don't believe clears the bar; carry forward only what you would
actually argue for. This is not a numeric prediction — you are not the
critic, and you do not compute or assert a percentile for the candidate
yourself — it is the same qualitative judgment §2/§3 already ask of
you, now informed by knowing what "good enough" means numerically for
this run, so effort stops going into full dossiers for candidates
already visibly doomed to fail a bar you can see. This replaces the
Cut 1/Cut 2 progressive funnel below for interactive mode; go straight
from the shortlist to dossiers for whatever survives it.

**This does not weaken the critic's blindness, and a future reader must
not "fix" this by removing it.** Blindness protects the critic from
seeing the *scout's effort and search history* — the funnel log, the
channel yields, which candidates got cut and why, how many tries it
took to find something good. The scout knowing the *standard* the
critic will apply is symmetric information, not leakage: it is the same
relationship a lawyer knowing the law has to an independent judge —
knowing the statute does not tell the lawyer what the judge will
privately conclude about this case's facts, and telling the scout the
target does not tell the scout what the critic will privately conclude
about a specific candidate's evidence. The critic still receives
nothing about which candidates the scout shortlisted-out or why; it
sees only the finished dossiers of what survived, exactly as before.
What changed is which candidates get a dossier built at all, not what
the critic is told.

**Digest mode (and interactive when the pool genuinely lacks the ask's
territory — see §3 tier 2): the full progressive-cut funnel**, unchanged
in substance from v1:
- **Cut 1 (→ ~40)**: metadata only (title/year/genre/shape/creators + what
  you already know). One line per elimination in the funnel log:
  `- OUT <title> (<year>): <reason>`.
- **Cut 2 (→ ~12)**: pull light review evidence for all survivors (1–2
  sources each, skim level, highest tier reachable — see §3c). Same
  elimination logging.
- **Dossiers (~12)**: deep evidence per finalist (below).
Stage sizes are targets, not laws — log the actual sizes. **Stage sizes
scale with the gathered pool, not with the ~40/~12 figures above.** Those
figures assume the §3 target of ~100–200 gathered titles; when the ask
legitimately narrows the gathered pool below that (e.g. a recency-
constrained ask, a narrow genre, a thin catalogue for the ask), scale
Cut 1 and Cut 2 down proportionally rather than trying to hit ~40/~12
from a smaller pool. A smaller pool from a legitimately narrow ask is a
**finding to log** — state in the funnel log why the pool came in small
— not a shortfall to pad with weaker candidates. Never lower the
evidence bar to fill a stage; a thin stage is reported thin, and a small
stage from a narrow ask is reported small, both honestly rather than
padded to hit the target number.

### TV season/parent verification — mandatory, before dossiers, in both modes

Once you have your shortlist (interactive: the shortlist-against-the-bar
survivors; digest: Cut 2's survivors) and before spending any evidence
budget building dossiers, run the whole shortlist's TV candidates through
`history.py sibling-seasons` **in one `--batch` call** — not per-candidate,
not by stripping `第N季` and grepping the index (§2's Excluded bullet
explains why that manual approach is unsafe as well as slow):

```
python3 recommend/history.py sibling-seasons --snapshot <snap.json> --batch <shortlist.json>
# shortlist.json: a JSON list of {title, year, kind, external_ids}, one per
# TV candidate on the shortlist — results come back in the same order.
```

(The single-candidate form — `--title "扑克脸" [--year 2023] [--kind tv]
[--ext douban:35651341 ...]` — exists for one-off checks, e.g. a tier-2
top-up candidate found mid-run; the batch form is what a shortlist-sized
check should use, one call instead of one per candidate.) Drop any
candidate the result reports `watched: true` for — that means some season
or the show-level parent already has a real watched/watching status, so
the candidate is not a discovery regardless of what its own row shows.
Log the drop like any other elimination (`- OUT <title> (<year>): already
watched — <matched season/parent title>, per sibling-seasons`).

**Pass `external_ids` whenever the pool row carries them.** This is the
one real limitation: without an `--ext` id, `sibling-seasons` will not
fuzzy-match an English title against a Chinese season family — this is
deliberate, not a gap to work around, since this project puts verified
ids above name similarity (house rule: never trust a title match where a
verified id could settle it). A pool row that arrived from Douban CF
almost always carries a `douban` id already; use it. A candidate with no
id and a title in a different script than the family it might belong to
can silently pass this check when it shouldn't — that residual risk is
worth a line in the candidate's `flags` (§5) rather than a false
assumption that a clean `sibling-seasons` result is airtight without ids.

## 5. Dossier — one JSON object per finalist
```json
{
  "kind": "film|tv|show|drama",
  "title": "...", "original_title": "...", "year": 2024,
  "external_ids": {"tmdb": "...", "imdb": "...", "douban": "..."},
  "shape": {"runtime_min": 0, "seasons": 0, "episodes": 0,
             "ep_runtime_min": 0, "status": "ended|ongoing|film"},
  "case": "why this is good, argued in the profile's persuasive terms",
  "ask_fit": "why it fits THIS ask",
  "evidence": [{"source": "tmdb|neodb|websearch|douban|letterboxd|rt|...",
                 "url": "...", "tier": 1,
                 "quote": "verbatim quote (tier 1); characterization (tier 2); metadata figure (tier 3) — what you actually read, never fabricated"}],
  "evidence_tier": 1,
  "history_analogues": [{"work_id": 0, "title": "...", "stars": 0.0,
                          "relation": "why comparable"}],
  "confidence": {"ids": "high|medium|low", "shape": "...", "case": "..."},
  "flags": ["anything the critic should probe"]
}
```
- `external_ids` are verified at source during dossier building — open the
  actual TMDB/Douban/IMDb page; never write an id from memory.
- Each `evidence` entry's own `tier` is that entry's grade — 1/2/3 per
  §3c's tier definitions. The dossier-level `evidence_tier` is **the
  BEST — numerically LOWEST — tier that any single evidence entry in the
  dossier reached**, since Tier 1 is the strongest and Tier 3 the
  weakest. A dossier holding one Tier 1 quote plus four Tier 3 metadata
  lines is `evidence_tier: 1`; a dossier holding only Tier 2 and Tier 3
  entries is `evidence_tier: 2`. Never write the worst tier present or
  an average — the critic caps `predicted_confidence` off this number,
  so a mislabeled dossier is scored against the wrong ceiling. A dossier
  resting on Tier 2 or Tier 3 evidence is submitted honestly labeled as
  such, not padded to look like Tier 1.
- Thin dossiers are submitted anyway; killing is the critic's job and
  kills are data.
- Write all dossiers to `<scratchpad>/dossiers.json` (a JSON list) and
  copy them into the funnel log.

## 6. Handoff
Spawn the critic per CRITIC.md. The critic receives ONLY: the profile,
the history (the **contents** of index.txt plus the **path** to
snap.json, so it can query the whole history itself — never the
snapshot inlined, and never a subset you selected), the rating
distribution and one population cell per candidate (`history.py
distribution` / `history.py cell` — the base rates its positional gate
measures against), dossiers.json, the pitch target line, and CRITIC.md
itself. Never pass the funnel log, channel yields, or any
account of search effort — blindness is the point (spec A2.6, A3).
Choosing which history the judge sees would destroy that blindness just
as surely as showing it your search transcript, which is why the critic
gets query access to everything instead of a curated extract.

## Source notes (maintained by probe runs; append findings here)

> **How to read this section.** These are dated MEASUREMENTS from probe
> runs, kept verbatim as evidence. They are not the contract. **§3c
> above is the normative guidance and wins on every point of conflict.**
> The probes ran in sequence and later ones overturned earlier
> conclusions, so a recommendation written in an earlier block may
> already be wrong; superseded recommendations are marked SUPERSEDED
> inline, with the measurement that produced them left intact. When you
> find guidance here that §3c does not endorse, follow §3c.

### 2026-08-23 harvester note — Douban 也喜欢 recommendations CF, WORKING (do not rediscover this)

Earlier probes below (and v1) only tested Douban's desktop subject page,
tag pages, and review/comment endpoints — all JS-challenge-walled or
retired, documented as failures below. **Those findings are about
review/tag scraping and do not extend to Douban's own CF
recommendations block ("喜欢这部电影/剧集的人也喜欢")**, which was never
probed until the v2 harvester was built and turns out to be reachable
cleanly: Douban's **mobile rexxar JSON API**, the same host
`mediahub.py`'s `cmd_enrich_douban` already uses successfully for
enrichment, answers a `/recommendations` sub-path with exactly this CF
block, as JSON, no HTML parsing, no JS challenge observed:

```
GET https://m.douban.com/rexxar/api/v2/movie/{douban_id}/recommendations?for_mobile=1
Headers: User-Agent: <a mobile UA>, Accept: application/json, text/plain, */*
         Referer: https://m.douban.com/movie/subject/{douban_id}/
```

Verified live against real anchors (2026-08-23): film 458 海洋之歌
(douban 11584019) → HTTP 200, 20 items, all `type: "movie"`; tv 455
守望者 (douban 26635374) → HTTP 200, 20 items, all `type: "tv"`. Each
item carries `id` (douban subject id), `title`, `type` (`movie`/`tv`),
`rating.value`, and `card_subtitle` — whose leading 4-digit token is the
year (verified on all 40 sampled items, 100%, 0 exceptions; extracted by
a regex anchored at the string's start, never guessed when absent).

This is the working precedent for the TV lane's ONLY collaborative-
filtering surface (162/162 TV anchors carry a douban id vs. 7/162 tmdb).
It is fully implemented in `recommend/harvest_douban.py` (subcommands
`anchors`/`fetch`/`transform`; the module's own docstring carries the
full revision history and live-verification detail — read it before
touching the fetch logic). **This is a digest-mode harvester concern,
not an interactive sweep channel**: per "Run modes" above, an
interactive ask reads this CF output from the `candidate_pool` table
(§3 tier 1), never re-fetches it live. The one interactive exception is
a tier-2 top-up for a single specific anchor missing from the pool,
subject to the same polite-delay discipline (`--delay-min`/`--delay-max`,
checkpointed, budget-capped) `harvest_douban.py fetch` already
implements — do not roll a second, undisciplined fetch path for this
endpoint.

### 2026-08-23 probe

- TMDB discover (genre+keyword, vote_count.gte=200): strong when the genre carries the load and the keyword narrows it, weak when the keyword is asked to do the work alone. `with_genres=80&with_keywords=10051` (crime + "heist") returned 10/10 relevant TV titles (Money Heist, Lupin, Sneaky Pete, Kaleidoscope) at 0% junk — but the set is small and exhausts fast. A vaguer ask ("sophisticated-plot sci-fi") broke the literal keyword approach entirely: `with_keywords=362567` ("mind-bending") alone returned 9 results, all vote_count=0/1, useless. Dropping the keyword and combining two genres instead — `with_genres=878,9648` (sci-fi + mystery) & `vote_count.gte=500` — returned 93 results with The Prestige, Arrival, 2001: A Space Odyssey, Twelve Monkeys, Contact, Source Code at the top; junk rate ~10-15% (a couple of animated/kids titles like The Secret of NIMH, one superhero adaptation). Lesson: for abstract asks, prefer genre-combination discover over a single free-text keyword; reserve `search/keyword` for concrete, nameable subgenres (heist, sitcom), not moods.
- TMDB similar vs recommendations: `/recommendations` is clearly the better surface. For anchor tv/1396 (Breaking Bad), `/recommendations` returned Better Call Saul, Narcos, Narcos: Mexico, Snowfall, Animal Kingdom, Queen of the South, Griselda, The Penguin — all crime/drug dramas, 0% junk in the top 15, vote counts in the hundreds-to-thousands. `/similar` (total_results=57580, essentially the whole TV catalog loosely ranked) surfaced Le Jun Kai (1 vote), Titus (45 votes), Esplendor (5 votes), Jogomaya (0 votes), My Naughty Classmates (0 votes) mixed in with a few real hits (Weeds, The Flight Attendant) — junk rate roughly 60-70% in the top 15 by relevance/obscurity. Use `/recommendations` as the default; treat `/similar` as unusable without a hard vote_count filter, and even then it is noisier.
- Douban tag pages (anonymous): blocked, but not by anti-scraping — the old `/tag/<term>` browsing page is retired (HTTP 404 with a full browser header set, "页面不存在", not a redirect or empty body). The working replacement is the internal JSON endpoint `movie.douban.com/j/new_search_subjects?tags=<term>&sort=U&range=0,10&start=0` (needs `Referer: https://movie.douban.com/explore`) — it returned 10 relevant, well-formed results for tag 犯罪 (title, douban rate, director, cast, subject id) including 肖申克的救赎 (9.7) and 悬案, with one clear genre-creep item (疯狂动物城2, an animated family film tagged into "crime"). This endpoint rate-limits fast: a second call ~30s later returned `{"msg":"检测到有异常请求从您的IP发出，请登录再试!","r":1}` (anomalous request detected, login required). Pattern to use: `new_search_subjects` with the Referer header, one call then a long randomized delay/backoff per the RUNBOOK's existing guidance — not viable for rapid repeated querying in a single session.
- NeoDB search: works cleanly and anonymously (`GET /api/catalog/search?query=...&category=tv`, HTTP 200, valid JSON, no auth). For "heist thriller" it returned 33 total hits (17 on page 1): Money Heist, Money Heist Season 2, Money Heist: Korea, Evil Genius, This is a Robbery, The Great Heist, The Helicopter Heist, Bling Ring: Hollywood Heist, The Diamond Heist. Precise but literal — it is a title/text match, not a semantic or thematic search, so it only surfaces titles whose text contains heist-adjacent words, and it returns TVSeason-level records (Money Heist appears 3+ times as separate season entries), producing near-duplicates that need de-duping by parent_uuid. Useful for identity resolution (it carries a douban subject URL as an external_resource) but not for open-ended genre discovery.
- Review mining: Letterboxd works anonymously but needs a fuller header set — a bare `User-Agent`-only request to `/film/<slug>/reviews/` 403'd; adding `Referer: https://letterboxd.com/` and a standard `Sec-Fetch-*`/`Accept-Language` set got HTTP 200 (114KB) with 13 review blocks. Text quality varies: several one-liners ("peak", "actually cried for 20 mins") alongside longer reflective reviews (300-527 chars). In this sample (Shawshank Redemption, sorted by activity) none of the 13 reviews named a neighbor title — 0 cross-film links found in the review-text HTML — so a single reviews-list fetch is not reliable for neighbor-title mining; would need to sample many anchor titles or crawl into individual long reviews. Douban: reviews/comments pages (`/subject/<id>/comments`) are challenge-walled, not just rate-limited — the response is a 200 OK "载入中..." (loading) shell posting a signed token to `/c`, i.e. a JS-based anti-bot checkpoint, distinct from and stricter than the tag-search rate limit above. Anonymous review text from Douban is not obtainable with a plain HTTP client. RT (Rotten Tomatoes): not probed this pass (out of budget) — treat as unverified, not "works".
- Recommended default channel mix (**its DISCOVERY guidance stands and is
  reflected in §3a/§3b; its closing clause on review mining is
  ⚠ SUPERSEDED** — this probe reached Letterboxd with a full header set
  from a raw HTTP client, but the later probes found WebFetch gets a flat
  403 there, so Letterboxd is a §3c documented negative and not a
  fallback of any kind; and this probe never tested the TMDB `/reviews`
  or NeoDB review endpoints that §3c now makes the Tier 1 channels):
  lead with TMDB `/recommendations` off known anchors (highest signal, near-zero junk) + TMDB `discover` using genre-combinations for abstract asks (avoid single free-text keywords except for concrete subgenres); use NeoDB search only for exact-title identity lookups and douban-id cross-referencing, not discovery; use Douban `new_search_subjects` sparingly (one call per session, long backoff) as a Chinese-market signal supplement, never as a primary loop; skip Douban review/comment mining entirely (challenge-walled) and treat Letterboxd review mining as a low-yield, high-cost fallback rather than a default channel.

**Skip list (machine-readable):**
```
- surface: douban_tag_page_html
  endpoint: movie.douban.com/tag/<term>
  status: failed
  reason: HTTP 404 - page structure retired, not a scraping block
  retried: true
  replacement: movie.douban.com/j/new_search_subjects?tags=<term>
- surface: douban_new_search_subjects
  endpoint: movie.douban.com/j/new_search_subjects
  status: partial
  reason: works once, then rate-limited (msg: 检测到有异常请求从您的IP发出，请登录再试!)
  retried: false (budget - one success then block observed)
  usable_pattern: single call + long randomized delay/backoff, Referer header required
- surface: douban_reviews_comments
  endpoint: movie.douban.com/subject/<id>/comments
  status: failed
  reason: JS anti-bot challenge page (载入中... loading shell, signed token POST to /c), not plain block
  retried: false (distinct failure mode from tag rate-limit, no header combination bypasses a JS challenge)
  replacement: none found anonymously
- surface: letterboxd_reviews_bare_ua
  endpoint: letterboxd.com/film/<slug>/reviews/
  status: failed
  reason: HTTP 403 with User-Agent-only headers
  retried: true
  replacement: add Referer + Sec-Fetch-* headers -> HTTP 200
- surface: rotten_tomatoes
  endpoint: n/a
  status: not_probed
  reason: out of time budget this pass
```

### 2026-08-23 probe addendum — review-evidence access

- **Q1 — curl-cffi against Douban (subject 1292052, 肖申克的救赎):** Reused
  the project's exact sanctioned pattern — `curl_cffi.requests.Session(impersonate="chrome")`
  plus jittered `polite_get()`, taken verbatim from
  `media-hub/mediahub.py` (`lb_session()`/`lb_get()`, lines ~519–542), the
  same helper the project uses for Letterboxd. Fired 2 requests, spaced
  ~3–5s apart, at `movie.douban.com/subject/1292052/comments?status=P` and
  `.../reviews`. Both returned HTTP 200 but the **final URL** was
  `sec.douban.com/c?r=...` — a JS "载入中..." (loading) interstitial with a
  hidden `tok`/`cha` challenge-response form, body ~3KB, zero comment or
  review DOM nodes. Chrome TLS impersonation does **not** clear this wall —
  unlike Letterboxd's Cloudflare TLS-fingerprint gate (which curl-cffi does
  pass, per `mediahub.py`'s own comment), Douban's is a JS computation
  challenge, a different class of block entirely. **Result: no review text,
  confirms the first probe — Douban review/comment endpoints are unreachable
  anonymously even with the project's best available fetch pattern.**

- **Q2 — WebFetch on the three target pages:**
  - Douban comments (`movie.douban.com/subject/1292052/comments?status=P`):
    WebFetch reported a 302 to the same `sec.douban.com/c?...` challenge URL
    seen in Q1. Blocked, no text. Also tested two specific Douban review
    permalinks surfaced by the Q4 search (`movie.douban.com/review/7539789/`
    and `m.douban.com/movie/review/7113909/`) — both redirect to the same
    `sec.douban.com` challenge. The wall covers review permalinks too, not
    just list endpoints.
  - Letterboxd (`letterboxd.com/film/parasite-2019/reviews/by/activity/`):
    WebFetch got a flat **HTTP 403 Forbidden**, no body. Notable: this is the
    one site the project's own curl-cffi script *can* reach (per
    `mediahub.py`'s `lb_session()` comment) — but plain WebFetch, with no
    TLS impersonation, is blocked outright.
  - Rotten Tomatoes (`rottentomatoes.com/m/parasite_2019/reviews`): WebFetch
    got HTTP 200 and real page structure, but no review text — the page is a
    client-side web-component shell (`<rt-text>` custom elements) that loads
    review content via JS/XHR after page load, which WebFetch's static
    fetch-and-convert does not execute. WebFetch itself described it as
    showing only a "Load More" button with reviews not yet loaded.
  - **None of the three produced quotable review text through WebFetch.**
  - Follow-up sanity checks (not in the original three, run to separate "WebFetch is broadly broken" from "these specific sites block it"): `en.wikipedia.org` loaded fine and returned real article text ("Parasite... is a 2019 South Korean black comedy thriller film..."), so WebFetch itself works generally. But two more English review sources surfaced by the Q4 search — `imdb.com/title/tt6751668/reviews/` and `rogerebert.com/reviews/parasite-movie-review-2019` — both also returned flat **HTTP 403**. So the block is broad across dedicated review-hosting sites (Douban, Letterboxd, IMDb, RogerEbert all blocked; RT loads but is JS-empty), not just a Douban-specific problem.

- **Q3 — Rotten Tomatoes baseline (never probed before):** Reachable at the
  HTTP layer (200 OK, ~96KB HTML) both via plain `curl` with a browser
  User-Agent and via WebFetch, for both critic and audience URL shapes:
  `rottentomatoes.com/m/<slug>/reviews` (critics) and
  `rottentomatoes.com/m/<slug>/reviews?type=user` (audience). But the
  fetched HTML contains **zero review text** in either case — the page ships
  as a shell of `<rt-text>` web components and hydrates review content via
  client-side JS/XHR after load, which neither curl nor WebFetch executes.
  Grepping the raw HTML for review-content markers (`review-row`,
  `reviewText`, populated `<rt-text>` bodies) found none — only chrome/nav/
  cookie-banner text. **Verdict: RT is technically unblocked but effectively
  empty for both curl and WebFetch — a JS-rendering gap, not an anti-bot
  wall, with the same practical outcome (no evidence).**

- **Q4 — Does WebSearch substitute for scraping?** Ran `豆瓣 影评 霸王别姬`
  and `Parasite 2019 film review`.
  - Chinese query: returned real Douban review URLs as hits (e.g.
    `movie.douban.com/review/7539789/`, `movie.douban.com/review/7113909/`,
    `m.douban.com/movie/subject/1291546/reviews`) plus a synthesized Chinese
    summary of review themes (character tragedy, Cultural Revolution
    backdrop, art-vs-social-order tension) — genuine thematic content, but
    it is an aggregated paraphrase attributed loosely to "豆瓣上的评论"
    rather than a quote tied to one named reviewer, and (per Q2) the linked
    Douban pages themselves are not independently fetchable to pull a
    verbatim line.
  - English query: returned real critic-adjacent URLs (IMDb, RogerEbert,
    The Review Geek, Medium) plus a synthesized paragraph carrying an actual
    critical stance, e.g. calling it "the most original film of 2019,"
    "wickedly funny and darkly disturbing." That's a genuine, usable
    opinion fragment — short quotable phrases are available straight from
    the search result, no page fetch needed.
  - **Verdict: WebSearch gives usable reviewer-opinion content for English
    titles directly in the result text (short quotable phrases, informally
    sourced to an outlet). For Chinese titles it gives real Douban review
    URLs plus a thematic summary, but the summary is a paraphrase, not a
    quote tied to a specific reviewer** — the underlying pages it points to
    are the same ones Q1/Q2 confirmed are walled, so search is the only
    channel that produced anything for a Chinese title, but at a lower
    evidentiary grade than a true quote.

- **Evidence-channel recommendation — ⚠ SUPERSEDED in full by the
  "API evidence channels" probe below; do NOT follow it.** It was written
  before anyone tested the API surfaces, and it is wrong in three ways
  that matter. (1) It says to reach English-language reviews through
  WebSearch snippets; TMDB `/movie|tv/{id}/reviews` in fact returns
  substantive verbatim English review text at 100% coverage in the
  measured sample, which is Tier 1. Following this note would
  self-downgrade every English title to Tier 2 — and Tier 2 is defined
  as "attributable characterization, **no body quote**", so its
  instruction to "quote the short opinion fragments" is not even
  internally consistent with the tier scheme. (2) It concludes no
  channel returns a verbatim Chinese-language line; the NeoDB review
  chain does, at ~80% coverage on Chinese titles. (3) Its fallback to
  "the metadata already in `media.db`" is not available to anyone: the
  candidates being evaluated are by definition NOT in the DB (they are
  unwatched, unlisted titles the sweep just found), and the critic sees
  only the snapshot and the dossiers. The correct floor is the Tier 3
  metadata the scout gathers into the dossier from TMDB
  (`vote_average`/`vote_count`/`keywords`) and NeoDB
  (`rating`/`rating_count`/`tags`), labeled as Tier 3. The measurements
  in this block stand and are the reason the blocked-source list in §3c
  exists; only its recommendations are void. Original text, for the
  record:
  > For **English-language titles**, do
  > not rely on WebFetch against dedicated review sites — Letterboxd, IMDb,
  > and RogerEbert all returned flat HTTP 403 and Rotten Tomatoes returns 200
  > but empty (JS-rendered) content; **use WebSearch directly and quote the
  > short opinion fragments it returns in the result text itself**, citing the
  > outlet named in the result, without a follow-up WebFetch to the walled
  > page. For **Chinese-language titles**, Douban's comment/review/permalink
  > endpoints are uniformly walled behind a JS challenge for both curl-cffi
  > (Chrome-impersonated) and WebFetch — **there is no reachable channel that
  > returns a verbatim quotable line**; the best available fallback is
  > WebSearch's synthesized thematic summary (paraphrase, not quote), used
  > with an explicit "paraphrased/no verbatim source" caveat rather than
  > presented as a quote. **When neither channel yields evidence** (a Chinese
  > title with no or thin search-result coverage), the critic mechanism should
  > fall back explicitly to the metadata already in `media.db` (douban rating,
  > tags, existing `review` field if the user logged one) rather than
  > fabricating or inferring quoted review text — a documented absence, per
  > this project's existing "negatives are documented, not silent" norm, not
  > a silent failure.

### 2026-08-23 run notes — NeoDB access details

Learned the hard way during a live calibration run; write these down so
no future run rediscovers them by trial and error.

- **`/api/item/{uuid}` 404s for TV-season records** — the working path is
  category-typed, e.g. `/api/tv/season/{uuid}`. Films use
  `/api/item/{uuid}/posts/` rather than `/api/movie/{uuid}/posts/`.
  **The danger here is not just wasted calls: a 404 on the wrong path
  reads exactly like "no reviews exist" and would get recorded as a
  documented negative** (per §3c's "documented negatives, do not retry"
  norm) when the review data may be sitting one path away. That mistake
  would land disproportionately on Chinese-language titles — precisely
  the titles NeoDB exists to serve, since TV seasons are common in that
  catalogue. **On a 404, retry with the typed path (`/api/tv/season/`,
  `/api/movie/`, or the relevant category) before recording any
  negative** for a title.
- **NeoDB JSON can contain raw control characters** that break a default
  `json.load`/`json.loads` call. Parse with `strict=False`.
- **The review endpoint 403s to `urllib.request` but returns 200 to
  plain `curl`** — an undocumented user-agent gate, distinct from the
  Douban/Letterboxd blocks documented above. If Python's stdlib HTTP
  client is refused, retry the same URL with plain `curl` before
  concluding the endpoint is blocked.
- **A genuine zero is distinguishable from a masked 404**: a real "no
  reviews" answer is HTTP 200 with `count: 0` in the body, not an HTTP
  404. Given the season/item path trap above, verify at both the
  season-level uuid and the parent (show/movie-level) uuid before
  concluding a title has no reviews — a 404 at one level with an
  untried typed path at the other is not yet a confirmed zero.
- **`history.py lookup --title` is substring-matched and returns false
  positives on short or common titles.** Verify a lookup hit by
  `work_id`, not by title text alone — a wrong match silently corrupts
  the already-watched exclusion (§2 Excluded) in both directions: a
  false-positive match wrongly excludes an unrelated candidate, and a
  missed match wrongly lets an already-watched title back into the
  funnel.

### 2026-08-23 probe — API evidence channels

- **TMDB `/movie|tv/{id}/reviews`** — real, substantive, user-submitted reviews (not scraped junk), but **coverage skews hard to English-language titles and is near-zero for Chinese titles**. Measured:
  - Inception (movie 27205): 8 reviews, 9,453 chars total (avg 1,182 chars/review) — genuine analytical criticism.
  - Breaking Bad (tv 1396): 5 reviews, 2,299 chars total.
  - The Man from Earth (movie 13363, mid-popularity indie): 4 reviews, 4,659 chars total.
  - English-title coverage: **3/3 tested had reviews** (100%), average ~5.7 reviews/title.
  - Let the Bullets Fly (movie 51533): 1 review — but written in **English** by a non-Chinese reviewer (author "badelf", explicitly says "this movie might actually be my first Chinese spaghetti western").
  - The Wandering Earth (movie 535167): 1 review, also English-language.
  - The Bad Kids (tv 104960): 0 reviews.
  - The Long Season (tv 225008): 0 reviews.
  - Empresses in the Palace / 甄嬛传 (tv 50878): 0 reviews.
  - Chinese-title coverage: **2/5 had any review (40%), but 0/5 had a Chinese-language review** — every non-empty result was an English-language review by an apparent Western fan, not evidence of Chinese critical reception. Effective Chinese-language coverage rate: **0%**.
  - `language=zh-CN` param does not filter to Chinese-authored content; TMDB's review corpus is simply thin outside English-speaking users regardless of language param.

- **TMDB adjacent metadata (`vote_average`, `vote_count`, `keywords`, `overview`)** — reliably present for all 6 titles tested, English and Chinese alike (vote_count ranged 84–39,973; keyword counts 3–29; overview always populated when the title exists in TMDB at all). This is real numeric/tag signal but **not review text** — no quotable criticism, just a score and a synopsis. Useful as a fallback confidence signal, never as "evidence" in the critic's quote sense.

- **NeoDB catalog metadata (`/api/catalog/search`)** — works anonymously, no auth, and returns strong aggregate signal for Chinese titles: `rating` (0–10 scale), `rating_count`, and a folksonomy `tags` list (genre/theme/actor tags), e.g. Let the Bullets Fly: rating 8.8, rating_count 2,662, 20 tags. This corroborates prior probes that catalog search works; it is not review text.

- **NeoDB `/api/item/{uuid}/posts/?type=review`** — **this is the fix.** Undocumented in the OpenAPI summary list by name but present as `journal_apis_post_list_posts_for_item`, works fully anonymously (no token), and returns federated (ActivityPub) posts announcing full-length member-authored reviews, each with a `review_uuid` embedded in the post's HTML content, resolvable via `/api/review/{review_uuid}` (also anonymous, `OptionalOAuthAccessTokenAuth`) to get the full review `body` text and `title`. Measured coverage across the same 5 Chinese titles:
  - Let the Bullets Fly: 5 reviews (`count`), fetched one full essay — 5,794 chars, substantive film criticism (analysis of "revolutionary narrative" tropes across PRC film history).
  - The Bad Kids: 3 reviews; fetched one — 1,509 chars, a considered personal reaction essay with a real title ("我做过的最后悔的事情，就是给你们开了门").
  - The Long Season: 4 reviews; fetched one — 572 chars, thematic comparison to another show.
  - The Wandering Earth: 6 reviews; fetched one — 274 chars, shorter but still original critical commentary with a title.
  - Empresses in the Palace: 0 reviews (only title with zero in this channel).
  - Chinese-title NeoDB-review coverage: **4/5 titles (80%) had at least one genuine Chinese-language review**, with per-title counts of 3–6 (this is `count`, not just the fetched page — `pages`/`count` fields confirm the full total). All text sampled was original, substantive, and directly quotable (titled essays, not one-line ratings).
  - Cross-check on an English title: Inception on NeoDB also returned `count=3` reviews (NeoDB's user base skews Chinese-language, so even English-market titles get Chinese commentary there) — meaning NeoDB is plausibly useful as a secondary channel for English titles too, though TMDB is the stronger primary source for those.

- **WebSearch quality check (Chinese titles, no page fetch)** — for 漫长的季节 and 隐秘的角落, `<title> 豆瓣 影评 短评` searches returned rich attributable signal without needing to fetch the blocked Douban pages: aggregate scores ("豆瓣评分...均分9.4...评价人数超过40万"), thematic characterization ("风格写实而充满绝望感", "反其道而行之地在明朗爽利的东北秋天背景下讲述故事"), and a list of individually-titled review essay links (e.g. "关于《隐秘的角落》里细思极恐的几点思考", "浅评《隐秘的角落》：总觉得差点东西") that a scout could cite as *evidence of existing critical discourse* (title + inferred stance) even without the verbatim body. This is weaker than a real quote — it's reception-summary, not review-body — but it is real, attributable, and free of the JS-challenge block since it only touches search snippets, not the article pages themselves.

- **Evidence hierarchy** — ranked, empirically-grounded order for the scout to try:
  1. **English-language titles**: TMDB `/reviews` first (100% coverage in this sample, substantive 1,000+ char English criticism, directly quotable). Fall back to NeoDB `/api/item/{uuid}/posts/?type=review` → `/api/review/{uuid}` if TMDB is empty (rare for English titles but costs nothing to check) since NeoDB carries some English-title coverage too.
  2. **Chinese-language titles**: NeoDB `/api/catalog/search` to resolve the uuid, then `/api/item/{uuid}/posts/?type=review` → `/api/review/{review_uuid}` as the **primary** channel (80% coverage in this sample, real quotable Chinese essays, fully anonymous, no rate-limit friction observed). Do NOT rely on TMDB reviews for Chinese titles — confirmed near-0% genuine-language coverage even though the raw endpoint returns 200.
  3. **When NeoDB review posts are empty** (this sample: Empresses in the Palace / 甄嬛传): fall back to a `WebSearch` for `<title> 豆瓣 影评 短评` (or `<title> 豆瓣 评价`) and extract the aggregate score/count plus any review-essay titles and one-line characterizations surfaced in the snippet — cite this as reception-summary evidence, explicitly weaker than a body-text quote, and never fabricate a verbatim quote longer than what the snippet actually shows.
  4. **Always record, regardless of title language**: TMDB `vote_average`/`vote_count`/`keywords` and NeoDB `rating`/`rating_count`/`tags` as a numeric-confidence floor — present for essentially every title tested (6/6) and cheap to fetch, useful to justify a "well-attested but unquoted" status rather than an outright rejection.
  5. **When every channel above is empty** (record explicitly, don't silently drop the candidate): log a structured "no evidence found" note — title, all uuids/ids tried, endpoints tried, timestamp — so the critic can make an informed low-confidence call (or defer) rather than the scout inventing text. Do not retry Douban HTML, Letterboxd, Rotten Tomatoes, or IMDb — independently confirmed blocked by JS challenge/403 in prior probes; this probe did not re-test them per the brief's constraint.
