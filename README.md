# media-hub

A personal media records system, and a film/TV recommendation engine built
on top of it.

`media.db` is the single canonical store for everything watched, read and
played — films, TV, books, games, music. Douban, Plex, Letterboxd, Ryot,
TMDB, Spotify and WeRead are loader inputs or consumers; none of them is
the source of truth. **The database is not in this repo** (see
[What's deliberately missing](#whats-deliberately-missing)).

## Start with only your chat history

This repository is designed to live inside Codex or Claude Code. Give your
coding agent the GitHub URL and say only:

> https://github.com/emrickk/LLM-movie-recommendation install and recommend

**Agent:** after cloning, enter the repository and read `AGENTS.md`, then
follow it immediately. Do not stop at installation; continue until the user
can view the finished recommendation page.

Codex discovers `AGENTS.md`; Claude Code discovers `CLAUDE.md`. Those entry
points tell the agent to continue through the whole workflow without requiring
the user to know the repository structure, skill name, or slash command. The
agent asks one short privacy question before reading conversations beyond the
current chat whenever permission is not already explicit. It reviews permitted
history before deciding whether any taste questions are necessary, then
separates what the user explicitly expressed from
what it only infers, initializes a local database, runs the scout and blind
rejecting critic, and produces an HTML page with 8–10 rich cards (fewer when
the evidence does not support them). Nothing personal is committed back to
GitHub.

On first use, the agent pauses once for your free TMDB **API Read Access
Token**, available from [TMDB API settings](https://www.themoviedb.org/settings/api).
It stores the token only in local, gitignored `profile/tmdb.env`. The token lets
the repository verify exact titles and fetch the covers shown on each card; no
shared project credential is embedded in this public repository.

The page accepts **Start now**, **Bookmark**, **Wrong title**, **Right title,
weak pitch**, or **Already seen**, plus written feedback. Copy the result back
to the agent: wrong titles are suppressed, weak pitches remain eligible for a
better explanation, and watched/rated works strengthen the next round.

---

## The recommendation engine

Give it a free-text ask — `我最近看了 the office，有没有别的推荐？`, `下饭剧`,
"like Rear Window but modern" — and it predicts what *you specifically*
would rate each candidate, against your own 1,700-work rating history, and
refuses anything that wouldn't land in the top slice of what you actually
like.

```
ask → scout → critic (blind) → pitch → HTML page → verdict → score
```

Two properties make it different from a recommender that returns
"because you liked X":

**Most of the program is prose.** `recommend/SCOUT.md` (retrieval and
funnel) and `recommend/CRITIC.md` (the gate) are read by an LLM at runtime
as its operating contract. The Python files are only the deterministic I/O
edges — snapshotting history, querying the candidate pool, sealing
predictions. A wording ambiguity in those two documents is a runtime bug
and gets treated as harshly as a code defect.

**The critic is blind and adversarial.** It never sees the scout's search:
not the queries, not the funnel log, not how hard anything was to find. It
receives the taste profile, the rating history index, the candidate's
population cell, and the dossiers — nothing else. Its own contract tells it
to refuse and report a violation if search effort leaks in. This is
load-bearing: a judge that knows how much work went into finding something
is no longer judging the something.

**Judgment is percentile-calibrated, not an absolute star floor.** 4★ is
this user's *mode* — 60.5% of everything ever rated is ≥4★ — so a "≥4★"
bar admits the majority of viewing and kills nothing. The bar is instead
the **70th percentile of the candidate's own cell** (mid-rank convention),
which auto-adjusts: a 4★ film clears it, a 4★ series does not, because the
same number means different things across populations he treats
differently. See `recommend/README.md` for the measured ladders.

Every prediction is **sealed into `recommendations` before you react**, so
the engine can be scored against reality later rather than graded on how
convincing its reasoning sounded.

### Running it

```bash
/recommend 下饭剧，低认知负荷，可打断
```

The recommendation skill (`.claude/skills/recommend/SKILL.md`) orchestrates
it end to end and opens an HTML page with covers, synopses, the case for
each pick, concrete inside-the-work hooks and entry points, the sealed
prediction, and differentiated feedback buttons.

Render a logged slate again at any time — read-only, safe to run while
anything else holds the DB:

```bash
python3 recommend/render.py --db media.db --open
```

Refresh the candidate pool (monthly; harvests TMDB + Douban collaborative
filtering, raw-first):

```bash
./recommend/run_digest.sh
```

Score the engine:

```bash
python3 recommend/reclog.py --db media.db stats
```

`hit_rate` is `(interested + watched) / pitched`; `sealed_vs_actual` pairs
each sealed prediction against the real rating once one exists. **This is
the only measurement of whether any of it works.**

---

## Layout

| Path | What it is |
|---|---|
| `ARCHITECTURE.md` | design authority: the canonical-store rule, adapter contract, gotcha ledger |
| `STATE.md` | living status — read before starting work, update when you change state |
| `TASTE.md` | the taste profile the critic binds to. The user's own voice; **never co-edited** |
| `recommend/SCOUT.md` · `CRITIC.md` | the engine, as prose contracts. User-agnostic |
| `recommend/PROFILER.md` | chat history → expressed evidence and engine inference |
| `skills/media-taste/SKILL.md` | the clone-to-first-recommendation journey |
| `recommend/README.md` | instance bindings — profile path, pitch target, write ritual |
| `recommend/HANDOFF.md` | cold-start guide. Read this first if you're picking the system up |
| `recommend/*.py` | the deterministic edges: history, pool, harvesters, log, render |
| `mediahub.py` · `load_*.py` · `pull_*.py` | the media-hub loaders and CLI |
| `docs/superpowers/` | specs, plans, and the decision log |

There is no git history before this commit, so
`docs/superpowers/decisions/` is the only record of *why* things are the
way they are. Read it before overriding anything.

```bash
python3 -m pytest recommend/tests/ -q      # 163 tests
```

---

## Hard rules

These are here because each one has already cost something.

- **Never write an external id from memory.** Verify against the source
  first. Two fabricated TMDB ids reached `media.db` on 2026-08-23 — one
  pointed at a 1994 jazz special, the other at a Philippine newscast — and
  nothing caught them until `render.py` tried to fetch their posters. Its
  `id_warnings` output is now the standing check.
- **Back up before any DB-writing pass**, checkpointing the WAL first.
- **One writer at a time.** Multiple agent sessions run against this
  concurrently: check `lsof media.db*` and STATE.md lane ownership before
  writing. Readers take their snapshot in one transaction before any
  network I/O.
- **Raw-first.** Every network pull lands as a dated immutable snapshot
  before any transformation touches it.
- **Non-destructive merges.** Loaders upsert; nothing bulk-deletes. The
  Letterboxd rows are a frozen sole-source copy — that account is deleted.
- **Chinese-only content is first-class.** `douban_id` + title + year is a
  complete identity; absence from IMDb/TMDB is a documented negative, not
  a failure.

## What's deliberately missing

`media.db`, its backups, the raw snapshot archives, generated HTML, cover
caches, and all credentials are gitignored. This repo is the system; the
library is local. Everything excluded is either regenerable by the code
here or personal data that has no business in a remote.

The TMDB credential lives in `profile/tmdb.env`; older private installations
may still use `douban-export/sources/sources.env`. Other source credentials live
in `media-hub/sync-config.json`. All are ignored and never committed.
