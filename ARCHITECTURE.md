# Media Records System — Architecture

Written 2026-07-28. The reference design for Anping's personal media records
(movies/TV, books, games, music). Everything here is grounded in what already
exists in `AI Space/media-hub/` and `AI Space/douban-export/`; nothing is
aspirational hand-waving — each layer names the files that implement it today
or the concrete gap to fill.

## 1. The shape of the system

```
SOURCES ──► RAW SNAPSHOTS ──► RESOLVE & MERGE ──► CANONICAL DB ──► VERIFY ──► OUTPUTS
(pull-only)  (immutable)      (identity match)     (media.db)      (human    (library.html,
                                                                    gates)    blog, Ryot…)
```

One canonical store: **`media-hub/media.db`** (SQLite). Everything upstream
feeds it; everything downstream is generated from it. The Emrick-clean JSONs
stop being a parallel center and become the *loader input* / *derived export*.

Sources never write to the DB directly. Outputs never read from sources.
Ryot/Yamtrack on the NAS are optional downstream consumers, **not** stores of
record — if they die or get wiped (as Ryot was 2026-07-27), nothing is lost.

### Directory layout (media-hub/, since the 2026-07-29 cleanup)

Root is flat and boring on purpose: authority docs + the DB + the ~12 live
scripts. Anything retired goes to `attic/` (moved, never deleted); every raw
network pull goes under `sources/raw/<source>/<date>/`. Don't re-nest the
live scripts into subpackages — they same-dir-import each other
(`from mediahub import …`) and concurrent sessions + docs reference these
paths.

```
media-hub/
├── ARCHITECTURE.md · STATE.md · TASTE.md   # authority docs
├── media.db (+ -wal/-shm)                  # THE canonical store
├── mediahub.py                             # CLI: ingest-douban / resolve / dump / stats / report / sync-plex
├── resolved.py                             # resolved-view computation (source precedence)
├── load_clean.py · load_spotify.py         # loaders → media.db
├── pull_spotify.py · pull_weread_notes.py · pull_weread_bookinfo.py   # pull adapters (raw-first)
├── build_library_db.py → library.html      # main private output
├── build_db_review.py  → review.html       # standing sync-review surface
├── fetch_covers_db.py  → covers/           # DB-driven cover ladder
├── export_letterboxd.py → letterboxd-import/  # fresh-account seed CSVs (open thread)
├── export_ryot.py                          # optional NAS consumer (regenerates ryot-import.json)
├── sync-config.json                        # plex token — credential, never commit
├── sources/raw/<source>/<date>/            # immutable raw snapshots (tmdb, weread, spotify, wikidata…)
├── dumps/                                  # per-table JSONL after every mutating run — recovery source of truth
├── backups/                                # dated pre-pass media.db copies
├── exports/                                # blog-facing JSON exports
├── analysis/                               # taste reports + audit ledgers (incl. lb-additions verdicts)
└── attic/                                  # retired one-offs, reference only — see attic/README.md
```

`douban-export/` is a **source project** feeding this one (Douban walk →
NeoDB identity cleaning → covers → Emrick-clean JSONs consumed by
`load_clean.py`); it keeps its own pipeline scripts, sources/, and RUNBOOK.md.

## 2. Sources layer (pull adapters)

| Source | Media | Adapter today | Auth |
|---|---|---|---|
| Douban (user Emrick) | all five kinds: status, rating, comment, marked_at | `douban-export/douban_export.py` | none (public profile) |
| Steam Web API | owned games, hours, last played | `douban-export/pull_steam.py` | key+vanity in `douban-export/sources/sources.env` |
| PSN via PSNAWP | play history, hours, trophies | `douban-export/pull_psn.py` | npsso in same file |
| WeRead | bookshelf, progress, reading hours, **highlights & notes** | shelf via the books_merged loader; annotations via `media-hub/pull_weread_notes.py` (renewal + bookmarklist/review endpoints, raw-first, resume-safe) | cookie in `AI Space/.mcp.json` |
| Letterboxd (user emrickw) — **SOURCE CLOSED: account deleted by Anping 2026-07-28** | watched history + ratings | ~~`mediahub.py sync-letterboxd`~~ never run again — the profile no longer exists. The 1,131 letterboxd records in media.db (after the 2026-07-28 mislog purges, verdicts in `analysis/lb-additions-decisions-20260728.json`) are a **frozen historical import and the only copy anywhere**; treat them as sole-source data, never bulk-delete. `lb_cleanup` (229 slugs) is a historical ledger only — the once-planned supervised diary-fix browser session is cancelled, nothing left to fix | — |
| Plex (NAS server) | watch state, read-only | `mediahub.py sync-plex` — discovers the server via plex.tv resources, reads libraries; last run 2026-07-27, 83 entries | token in sync-config.json |
| Spotify | **listening history** via the privacy export (Extended Streaming History, landed + loaded 2026-07-29: 98,754 plays 2018-10-09→2026-07-27 — the Web API exposes only the last 50 plays, never full history); **Liked Songs, playlists (+tracks), top artists/tracks, follows** via one-time user OAuth (read-only scopes); track/album metadata + ISRC/UPC via API client-credentials flow | `media-hub/pull_spotify.py` — `ingest` snapshots the export ZIP raw-first; `load-plays` upserts the snapshot into `track_events` kind='play' (schema decided 2026-07-29, see §3; idempotent via play-uid unique index); `test` smoke-tests credentials; `auth` = loopback OAuth on `http://127.0.0.1:8899/callback` (must be registered in the app settings), refresh token → `sources/spotify_token.json` (0600, auto-refreshed); `library` = raw-first paged pull of liked/playlists/top/follows/recent-50; `hydrate` resolves spotify_track_uri → ISRC + album ids via single `/tracks/{id}` calls (the batch `?ids=` endpoint 403s in dev mode — §9), checkpointed to the day's raw dir; album-UPC pulls and work matching stay in load_spotify.py (music lane) | client id+secret in `douban-export/sources/sources.env`; export ZIP drops into `media-hub/sources/raw/spotify/incoming/` |
| **Claude, conversationally** | anything — but especially Anping's comments/ratings on books, games, movies/TV, and book quotes with per-passage thoughts | Anping tells Claude in a session; Claude writes it via `mediahub.py add` (to build). This IS the manual source — there is no separate CSV workflow | — |

Adapter contract (the robustness rules — every adapter, present and future):

1. **Raw first, immutable.** Every run writes its raw pull untouched to
   `sources/raw/<source>/<YYYY-MM-DD>/…` (JSONL) before any transform. Never
   overwrite a previous day's raw. Disk is cheap; re-derivation is not.
2. **Checkpointed & resume-safe.** Network loops cache per-item JSONL and skip
   completed items on rerun (already the pattern in clean_movies.py,
   fetch_covers*.py — keep it universal).
3. **Idempotent upserts, keyed on external IDs only.** `(namespace, value)`
   in `external_ids` is the identity. Title+year similarity may *propose* a
   match into `match_queue`; it never auto-merges.
4. **Never destructive.** A pull can add or update; it cannot delete. An item
   that disappears from a source gets flagged (tombstone in the run report),
   reviewed by a human. Ratings/statuses that *regress* (5★→3★, 读过→想读)
   are conflicts, not silent updates.
5. **Per-run diff report.** Each run appends to `sync_runs` and emits
   added / updated / conflicted / vanished counts with item lists. Conflicts
   land in a review queue, not in the canonical row.
6. **Rate-limit + retry with backoff** on every external API; hard caps so a
   bug can't hammer a service.
7. **Credentials stay local** (`sources.env`, `.mcp.json`,
   `sync-config.json`) — never in any repo, never in output JSONs.

Extra rules for the conversational (Claude) source, since a chat message is
fuzzier than an API payload:

- **Resolve before writing.** Claude must map the mentioned title to an
  existing work via external IDs / aliases and echo back exactly which work
  it resolved to ("久石让 → work #1234, imdb tt…") before the write lands.
  No confident-sounding guesses; ambiguity → ask, or park in match_queue.
- **New works are explicit.** If the item isn't in the DB yet, Claude says so
  and creates it through the same identity pipeline (NeoDB/IMDb lookup), not
  as a bare title row.
- **Same non-destructive rule.** Claude appends records/annotations with
  source=`manual`; editing or deleting an existing row requires Anping's
  explicit say-so in that session.
- **Every session's writes are logged** to `sync_runs` (source `manual`,
  note = date + short description), so conversational edits are as auditable
  as API pulls.
- `manual` sits at the top of the precedence order — what Anping says
  directly always beats what a platform scraped.

## 3. Canonical data model (media.db, evolved)

Existing tables (keep): `works`, `external_ids`, `records`, `match_queue`,
`work_aliases`, `sync_runs`, `ryot_exported`.

### works — one row per creative work
`kind` (film | tv | show | book | game | music | drama), `title`
(zh-preferred display), `original_title`, year, `season_number` (tv),
`neodb_uuid`, `title_en`, `creators` (authors/directors/artists, display
string), `meta` JSON (kind-specific extras: pub_house, translators,
platforms, show-level ids… — anything that doesn't earn a column).

**TV is season-level canon** (implemented 2026-07-28): one work per Douban/
NeoDB season, because Anping rates each season separately. `kind='show'` is
the series-level entity (Plex shows, Letterboxd, old merged shells) — a
separate kind so name-resolution never mixes the two models.
merge_tv_seasons.py (which had collapsed seasons for Ryot's one-entity-per-
series model, deleting clashing per-season records in the process) is
retired (archived under `attic/`); that collapse is an export-time concern. Season works carry the
show-level imdb tt and series tmdb id in `meta`, never as external_ids —
otherwise every season of a show would cross-link (the season-tt gotcha).

### external_ids — identity anchors
Namespaces: douban, imdb, **tmdb_movie, tmdb_tv** (split 2026-07-28: TMDB
movie and tv ids share one number space — movie/240 is The Godfather II,
tv/240 is Jackie Chan Adventures — a single 'tmdb' namespace produced false
identity conflicts), isbn, weread, steam, psn, psn_npwr (trophy-set NPWR
ids), neodb, letterboxd, plex_guid; future: igdb, musicbrainz/spotify.
One work may hold many; `(namespace, value)` unique.
`suppressed_ids` records values PROVEN wrong for this library —
_attach_externals refuses them forever, so loader re-runs can't resurrect a
corrected mistake.

### records — per-source, per-status facts (provenance preserved)
One row per (source, work, status): status, rating (normalized 0–10),
marked_at, review (the item-level comment), raw payload. Sources:
douban|letterboxd|plex|steam|psn|weread|manual.
Status is ONE universal code set across kinds (original wording kept in
`raw`; display layers translate per kind):
- `watched`  = done (看过 / 读过 / 玩过)
- `watching` = in progress (在看 / 在读 / 在玩)
- `wishlist` = wants to (想看 / 想读 / 想玩)
- `owned`    = in the library, untouched (未读 / 库存)

**Resolved view (new, computed not stored):** one status/rating/date per work
for display, with precedence `manual > douban > weread > letterboxd > plex >
steam/psn`, latest marked_at wins ties, hours SUMMED across steam+psn
(PS4/PS5 are separate PSN titles — always sum; strip "(PlayStation®5)"
suffixes before matching).

### tracks / track_events / playlists — the music event layer

`tracks`: one row per Spotify track (`spotify_id` key; ISRC when hydrated;
`work_id` only when its album matched a music work, UPC-corroborated —
name similarity never auto-links). `playlists`: playlist snapshots.
`track_events`: kind = `liked` | `playlist_add` | `play`.
**Plays schema (decided 2026-07-29, was §8 open):** one `track_events` row
per stream from the Extended Streaming History export — `ts`, `ms_played`,
`context` = platform, `uid` = `"ts|track_id|ms_played"` (partial unique
index where kind='play' makes re-loads idempotent), `raw` = slim JSON
`{rs,re,sh,sk,cc}` (reason start/end, shuffle, skipped, country). IP
addresses never enter the DB — the full payload lives only in the immutable
raw snapshot. Podcast/audiobook/video-episode rows stay raw-only. Unknown
tracks get stub rows (INSERT … DO NOTHING, so hydrated rows are never
clobbered by a re-load).

### annotations — NEW (the books requirement)
```sql
CREATE TABLE annotations (
  id INTEGER PRIMARY KEY,
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  source TEXT NOT NULL,          -- weread|manual|douban
  kind TEXT NOT NULL,            -- highlight|note|quote  (note = comment attached to a passage)
  chapter TEXT DEFAULT '',
  location TEXT DEFAULT '',      -- source-native range/position string
  quote TEXT DEFAULT '',         -- the underlined/cited sentence(s)
  comment TEXT DEFAULT '',       -- Anping's thought on that passage
  created_at TEXT DEFAULT '',
  raw TEXT DEFAULT ''
);
```
This is what makes books richer than one flat comment: a book has an
item-level record (rating + short review) **plus** N annotation rows.
WeRead's `get_book_notes_and_highlights` supplies quote text, chapter, and
attached thoughts — today only the *count* (e.g. `weread_notes: 52`) is
stored; pulling the actual text is the first new adapter to build. The same
table serves manual quotes from paper books, and could later hold game
screenshots-with-comments or lyric annotations if wanted (kind is open).

### covers — NEW (make cover quality first-class)
```sql
CREATE TABLE covers (
  work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  file TEXT NOT NULL,            -- relative path under covers/
  source TEXT NOT NULL,          -- douban|neodb|tmdb|steam|sgdb|weread|manual
  width INTEGER, height INTEGER, bytes INTEGER, sha1 TEXT,
  grade TEXT NOT NULL DEFAULT 'unverified',  -- good|low|placeholder|unverified
  preferred INTEGER NOT NULL DEFAULT 0
);
```
Files stay on disk keyed by work id (as in Emrick-clean/covers*/). Grading
rules encoded, not remembered: min height ~600px = good; NeoDB stale-snapshot
placeholders detected and demoted; language preference applied
(refresh_covers_lang.py logic); SGDB fallback for games (sgdb_covers.py);
Steam portrait art from
`cdn.cloudflare.steamstatic.com/steam/apps/<appid>/library_600x900.jpg`;
doubanio requires a `Referer: douban.com` header or serves nothing.

### recommendations — the recommend system's log

`recommendations` — the recommend system's log (spec
`docs/superpowers/specs/2026-08-23-media-recommend-design.md` §A5): every
pitched/killed candidate with sealed `predicted_stars`, verdicts, dossier
JSON. Written only by `recommend/reclog.py` (insert/update, never
destructive). Consumer: the `/recommend` skill.

Scale note, because two scales meet in this table: `records.rating` is
**0–10**; `predicted_stars` is in **stars, 0.5–5.0** (`rating / 2`).
`reclog.py`'s batch validator rejects an out-of-range `predicted_stars`,
and the DDL carries a `CHECK` for newly created databases — the live
table predates that constraint and is deliberately not rebuilt, so the
validator is what protects it.

### candidate_pool — the recommend system's harvested candidate cache (v2)

`candidate_pool` — the target of the v2 harvesters (spec
`docs/superpowers/specs/2026-08-23-media-recommend-v2-pool-design.md` §3):
one row per not-yet-watched candidate, columns `kind`/`title`/
`original_title`/`year`, `external_ids`/`tags`/`aggregates`/`shape` (all
JSON), `sources` (JSON provenance list — every harvest that surfaced this
candidate, never overwritten), `evidence`/`evidence_fetched_at` (fetched
once, cached forever), `suppressed`/`suppressed_reason`. Rows ACCUMULATE
across harvester runs instead of being rebuilt per ask — the whole point
is that platform-recommendation results and review evidence are fetched
once and reused by every future ask. Written only by `recommend/pool.py`
(`init/upsert/query/attach-evidence/suppress-sync/stats`); matching on
upsert is shared-`external_ids` first, else exact `(kind, lower(title),
year)`, and a merge only gap-fills empty fields — an existing non-empty
value is never overwritten, so two harvesters hitting the same candidate
from different anchors both survive in `sources` rather than clobbering
each other. Suppression (`suppress-sync`, watched-since or previously
`verdict='no'`) is a pure UPDATE, same non-destructive rule as
`recommendations`: rows are marked, never deleted.

## 3a. The recommend system (`recommend/` + `.claude/skills/recommend/`)

Design authority: `docs/superpowers/specs/2026-08-23-media-recommend-design.md`
(Part A = user-agnostic engine, Part B = profile schema, Part C =
instance bindings). A scout/critic pipeline that predicts **what this
user would rate a title** and pitches only what clears their enthusiasm
threshold. Unusually for this repo, **most of the engine is prose read by
an LLM at runtime** — a wording ambiguity in those documents is a runtime
bug and they are maintained with the same rigor as code.

| File | Role |
|---|---|
| `recommend/SCOUT.md` | retrieval + funnel contract (interpret ask → work the history → sweep channels → two cuts → dossiers). Engine; **no user-specific facts**. Carries the dated source-probe notes and the Tier 1/2/3 evidence hierarchy. |
| `recommend/CRITIC.md` | adversarial gate contract: 6 ordered checks, predicted stars + confidence, kill rules. Engine; **no user-specific facts**. |
| `recommend/README.md` | the ONLY file holding instance bindings (which profile, which DB, thresholds, key paths, write ritual). A second user swaps this file and the profile; nothing else changes. |
| `recommend/DIGEST-INTENT.md` | the stored default ask for digest mode. |
| `recommend/history.py` | read side. `snapshot` = ALL media.db reads for a run, in one transaction, before any network I/O (`rated`/`wishlist`/`shells`/`rec_log`). `index` + `lookup` are the critic's query surface over that snapshot. |
| `recommend/precedence.py` | shared source-precedence resolver (`manual > douban > letterboxd > plex`, then `watched > watching`, then recency) used by both helpers so they can never silently disagree. |
| `recommend/reclog.py` | write side — the only write surface. `init/log/check/verdict/pending/stats`. |
| `recommend/pool.py` | v2: the `candidate_pool` write/read surface (`init/upsert/query/attach-evidence/suppress-sync/stats`) — see the table entry above. |
| `recommend/harvest_tmdb.py` | v2: sweeps TMDB `/recommendations` (CF) across every tmdb-bearing anchor plus a recency-gated `/discover`, raw-first into `recommend/raw/tmdb/<date>/`, `transform`s into a `pool.py upsert` batch. Films' only CF surface (138/145 anchors carry a tmdb id; TV mostly doesn't). |
| `recommend/harvest_douban.py` | v2: Douban's own 「喜欢这部电影/剧集的人也喜欢」 CF via the mobile rexxar JSON endpoint (`m.douban.com/rexxar/api/v2/{media}/{id}/recommendations`) — the TV lane's *only* CF surface (all 162 top-rated TV anchors carry a douban id, only 7 a tmdb one). Raw-first per-anchor JSON into `recommend/raw/douban/<date>/`; resumable checkpoint at `recommend/raw/douban/checkpoint.json` (survives across sessions — a bounded `--budget` run is expected to leave anchors unfetched, not a shortfall); randomized 5–10s inter-request delay; stops (not crashes) on a 403/challenge or an 8-consecutive-failure circuit breaker, exit 0 with a report either way. |
| `recommend/logs/` | one funnel log per session, `<YYYY-MM-DD>-<slug>.md`. |
| `recommend/tests/` | pytest suite over the three python modules. |
| `.claude/skills/recommend/SKILL.md` | `/recommend` orchestration: the step order and the seams between scout, critic, and log. |

Two structural properties worth not breaking:

- **Critic blindness.** The critic runs as a fresh subagent that receives
  only the profile, the history, the dossiers, and CRITIC.md — never the
  funnel log, the queries tried, or any account of search effort, so it
  cannot be persuaded by how hard the candidate was to find. It is also
  never handed a scout-selected *subset* of the history: it gets the
  complete index plus the snapshot path and queries it itself, because
  letting the searching party choose which history the judge sees would
  defeat the same principle.
- **The snapshot is too big to read.** `snap.json` is ~900KB / ~40,000
  lines; a model Read caps out long before the end and returns a recency
  slice with no truncation signal. `history.py index` (~1,700 lines, one
  line per rated work, ending in an `END OF INDEX` marker) is the
  complete map; `history.py lookup` pulls detail. Anything that hands
  the raw snapshot to a model is a defect.

## 4. Resolution & verification pipeline

Identity resolution (exists, keep as-is): NeoDB catalog/fetch → IMDb
suggestion fallback → Wikidata deep pass (P4529, pinyin) → human
adjudication (`apply_adjudications.py`), audit trail in
`_fallback_decisions.json`. Provenance grades per item; items with no
external anchor are **documented negatives** (douban_id + title + year is
their identity — Chinese-only content is first-class, not a failure).

Verification gates before anything reaches an output:
1. **Identity**: every new work either carries an external ID or is a
   reviewed, documented negative. New fuzzy matches sit in `match_queue`
   until adjudicated.
2. **Covers**: every displayed work has a `preferred` cover graded `good`,
   or an explicit text-spine fallback.
3. **Data sanity assertions** (run per sync, fail loudly): years are original
   release years (Douban release_date is often the CN re-release — NeoDB year
   wins); TV season IMDb tt must come from the parent show, never the
   premiere-episode tt; Steam beta/test branches filtered; ratings in range;
   marked_at parseable.
4. **Human review surface**: `build_review.py` grid pattern — every batch of
   new/changed items gets a visual review page before it's blessed.

## 5. Outputs (all generated from media.db, never hand-edited)

| Output | Audience | Content policy |
|---|---|---|
| `library.html` (build_library.py, ported to read the DB) | private, local | everything — comments, hours, backlogs, annotations |
| Blog `/library` page (Astro, theneverless.com) | public | **gated** — see below |
| Per-book notes pages (optional, later) | public/private | annotations rendered as quote+comment threads |
| Ryot / Yamtrack import (export_ryot.py) | private NAS UIs | optional consumers; keep or drop freely |
| JSONL dumps of all tables (`dumps/`) | backup / git history | full |

**Publishing gate (standing rule, from BLOG-HANDOFF.md):** before the blog
page ships, Anping decides per class: my_comment texts, WeRead hours/progress,
Steam/PSN hours & last-played, owned-but-untouched backlogs, wishlists.
Safe default: publish completed items + ratings only; everything else opt-in.
The exporter implements this as an explicit field allowlist in one place —
not scattered ifs.

## 6. Operational safety

- **iCloud hazard:** media.db lives under iCloud-synced Documents. SQLite +
  iCloud sync is a real corruption risk. Mitigation now: pipeline runs
  single-process, connections closed promptly, and **after every mutating run
  dump all tables to `media-hub/dumps/*.jsonl`** — the dumps are the recovery
  source of truth and diff cleanly. Better later: move media.db out of iCloud
  (e.g. `~/.mediahub/media.db`) and leave only dumps in AI Space.
- Snapshots + dumps are dated and immutable; `sync_runs` is the run ledger.
- Any destructive maintenance (merges, deletes) goes through scripts that
  print their plan and require confirmation, mirroring the match_queue flow.

## 7. Migration plan (from today's state to this design)

1. **Freeze v1**: today's Emrick-clean JSONs + covers are the blessed 2026-07
   snapshot; don't regenerate until the loader exists.
2. **Schema migration**: add `annotations`, `covers`, `works.title_en`,
   `works.creators`, `works.meta`; register new external_id namespaces.
3. **Loader** (`load_clean.py`): upsert the three merged JSONs
   (all_clean/books_merged/games_merged) + Steam/PSN raw pulls into media.db
   — reconciling against the douban/letterboxd/plex records already there via
   external IDs, fuzzy leftovers → match_queue.
4. **WeRead annotations adapter**: pull full highlights/notes per book via
   the WeRead MCP (or direct API with the cookie) → `annotations`.
   Checkpointed per book; ~300 books with notes.
5. **Cover registry**: walk covers*/ folders into the `covers` table with
   dims/hash/grade; re-grade with the QA rules.
6. **Port outputs**: build_library.py and the blog exporter read the DB.
   review.html becomes the standing review surface for each sync.
7. **Music** (654 works already in media.db, uncleaned): same NeoDB pipeline
   when Anping wants it; loads through the same loader.
8. **Retire** ryot-import JSONs as source-of-truth; export_ryot.py stays as
   an optional consumer.

## 8. Open decisions (Anping's calls, not defaults)

- Blog privacy gates per §5 (comments / hours / backlogs / wishlists).
- Keep Ryot, Yamtrack, both, or neither as NAS browsing UIs.
- When to clean music (654 items).
- ~~Plays-table schema for Spotify listening history~~ DECIDED 2026-07-29:
  reuse `track_events` kind='play' — see §3 music event layer.
- Move media.db out of iCloud now or accept dump-based recovery.
- Whether annotations ever go public (per-book opt-in seems right).

## 9. Gotcha ledger (hard-won; encode as assertions, don't rediscover)

- doubanio images: require `Referer: douban.com` header.
- NeoDB TVSeason `imdb` = premiere-episode tt; show tt from parent record.
- Douban `release_date` = CN (re-)release; use NeoDB original year.
- PSN: PS4/PS5 are separate titles — SUM hours; strip "(PlayStation®5)".
- NeoDB covers can be stale ~2021-22 placeholder snapshots.
- IMDb indexes CN variety under pinyin romanizations.
- 5 "uncovered" games are Steam beta branches — filter from public views.
- WeRead cover fetch (`/web/book/info`) needs the cookie.
- WeRead sessions: POST `/web/login/renewal` FIRST to mint a fresh `wr_skey`
  from the long-lived cookie. With a stale skey, `/api/user/notebook` still
  answers normally but `/web/book/bookmarklist` returns literally `{}` (no
  error!) and `/web/review/list` errors -2012 登录超时 — a silent
  partial-auth state that looks like "no highlights". bookmarklist also wants
  `Referer: /web/reader/<bookId>`. Notebook counts: `noteCount` = underlines,
  `bookmarkCount` = bookmarks (different things).
- iCloud sync races mass file writes → write-only-if-changed everywhere.
- Steam art CDN (added 2026-07-28 evening, covers pass): the file named
  `library_600x900.jpg` is served at 300x450 — the real 600x900 is
  `library_600x900_2x.jpg`. Post-~2023 games live on
  `shared.steamstatic.com/store_item_assets/steam/apps/<appid>/…` instead of
  `cdn.cloudflare.steamstatic.com/steam/apps/…`; some games (even 2025
  releases, e.g. BALL x PIT) have NO portrait art at all and only
  header/hero banners; demo appids (Last Gas Station 3690030) carry partial
  art sets — fall through to SteamGridDB by name. appdetails API
  (`store.steampowered.com/api/appdetails?appids=X`, keyless, ~200req/5min)
  is the last-resort header source.
- SteamGridDB API (sgdb_covers.py): passing `dimensions`/`types` query
  params silently returns EMPTY data — fetch unfiltered and filter
  client-side (portrait = height>width; static = mime image/*). The image
  CDN rejects requests carrying the API bearer header (HTTP 401) — download
  with a clean session. Grid sizes are 600x900, 660x930 AND 342x482. Key in
  `douban-export/sources/sources.env` (STEAMGRIDDB_API_KEY).
- Unicode name matching: normalize-then-strip is WRONG for ™ — NFKD
  decomposes ™ into the letters "tm" ("RESOGUN™" → "resoguntm"). Strip
  [™®©] BEFORE NFKD. PSN also appends "(PlayStation®5)"-style suffixes and
  "Trophy"/"Trophies" bookkeeping rows (IGN, "No Man's Sky Trophies" are not
  games at all).
- Cover language policy (refresh_covers_lang.py, Anping's preference
  2026-07-28): posters in each title's ORIGINAL language — CN/HK/TW/MO keep
  Douban covers untouched; others get TMDB posters via
  `include_image_language=<lang>,null` (highest vote), TV rows try
  season-specific posters before show-level. TMDB key in sources.env.
- Non-portrait art handling: `_cover_aspects.json` (sips-measured) drives a
  letterbox render (blurred backdrop + object-fit contain) in
  build_library.py — never center-crop landscape/square art into 2:3.
- Cover feedback loop: library.html cards are click-to-flag (localStorage
  `coverFlags`, 复制清单 copies "tab:id title" lines) — Anping flags while
  browsing, agent batch-fixes from the pasted list.
- Album art APIs, ranked (2026-07-28 music pass): (1) barcode -> MusicBrainz
  release search -> Cover Art Archive front-1200 — ID-linked to the exact
  physical edition, keyless, ~1 req/s etiquette + descriptive UA; also banks
  the MBID as an anchor. (2) Deezer — fully keyless, cover_xl = 1000px,
  50 req/5s. (3) Spotify — 640px max, client-credentials SHARE ONE QUOTA
  across all sessions using the app, and app-level 429s carry Retry-After of
  HOURS (76,918s observed) — cap honored waits and save partial results, or
  a run silently sleeps for a day. (4) iTunes Search — keyless and deep CN
  catalog but throttles at ~20 req/min; artwork URL rewrites (100x100 ->
  600x600/1200x1200) work when you do get through. Douban's own album art
  maxes out small for pre-2010s CDs — /subject/l/ is often byte-identical
  to /m/.
- Spotify Web API, newer dev-mode apps (2026-07-28): the legacy
  `/playlists/{id}/tracks` endpoint returns bare 403 — contents moved to
  `/playlists/{id}/items`, and the playlist object carries an `items` key
  (no `tracks` at all; `/me/playlists` rows lack `tracks.total`). Own
  playlists readable via /items; OTHER users' playlists (and editorial)
  stay 403 in dev mode. Batch `GET /v1/tracks?ids=` also returns bare 403
  in dev mode — with BOTH app and user tokens (2026-07-29); single
  `GET /v1/tracks/{id}` works fine, so hydration loops single calls
  (~1.6 req/s, checkpointed). OAuth redirect must be literal `http://127.0.0.1:…`
  (the string "localhost" is rejected). Client-credentials (no user consent)
  suffices for `/tracks/{ids}` ISRC/UPC lookups; user consent adds
  liked/playlists/top/follows but NEVER full listening history (API max =
  last 50 plays — the privacy export is the only history source).

### Recommend system — v2 additions (2026-08-23)

- `candidate_pool` — external candidates harvested from platform
  collaborative-filtering engines (TMDB `/recommendations`, Douban's mobile
  rexxar CF API) expanded from Anping's ≥4.5★ anchors. 6,473 rows. Written
  only by `recommend/pool.py` (upsert/suppress, never destructive). The
  library is NOT a candidate source — external only, by standing policy.
- `recommend/harvest_tmdb.py`, `recommend/harvest_douban.py` — the harvesters.
  Raw-first: every response lands under `recommend/raw/<source>/<date>/`
  before transformation. Douban honours a resumable checkpoint and a
  politeness budget (298/298 anchors complete).
- `recommend/render.py` — renders logged `recommendations` rows into a
  self-contained pitch page; its `id_warnings` output is the standing check
  for external ids that resolve to the wrong title.
- `recommend/run_digest.sh` — one-command monthly data refresh (harvest →
  upsert → suppress-sync → stats). Driven by the `monthly-recommend-digest`
  scheduled task, sequenced after `monthly-douban-backup`.
