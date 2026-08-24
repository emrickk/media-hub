# Media Recommend v2 (Candidate Pool) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-ask network sweeping with a persistent, platform-CF-harvested candidate pool; make interactive asks pool-first (≤5 min), re-sweeps opt-in, and evidence lazily cached.

**Architecture:** New `candidate_pool` table in media.db + two harvesters (TMDB CF/discover; Douban 也喜欢 via the established curl-cffi pattern) + rewritten SCOUT/SKILL run modes. Judgment layer (critic, calibration, rec log) untouched.

**Tech Stack:** Python 3.10+ stdlib (`sqlite3`, `json`, `argparse`, `urllib`), `curl_cffi` (already a repo dependency) for Douban, pytest. No new dependencies.

**Spec:** `media-hub/docs/superpowers/specs/2026-08-23-media-recommend-v2-pool-design.md` (amends the v1 spec; v1's §6-unchanged list is binding). Read both before executing.

## Global Constraints

- **No git** (iCloud store). Commit steps are replaced by verification steps.
- **DB ritual before a session's first media.db write:** `lsof media.db*` (STOP if another writer), STATE.md lane check, `sqlite3 media.db "PRAGMA wal_checkpoint(TRUNCATE);"`, `cp media.db backups/media-recommend-$(date +%Y%m%d-%H%M%S).db`.
- **Raw-first:** every network pull lands as a dated immutable snapshot under `recommend/raw/<source>/<YYYY-MM-DD>/` before transformation.
- **Douban discipline:** randomized 5–10 s inter-request delay + jitter, resumable checkpoint, bounded per-session budget, per RUNBOOK. Never hammer on a 403/challenge — record and stop.
- **Non-destructive:** pool rows are suppressed, never deleted. No DELETE/DROP anywhere.
- **Ids verified at source, never from memory.** Chinese-first identity: douban_id+title+year definitive; absence from TMDB is a documented negative.
- **Engine purity:** SCOUT.md/CRITIC.md carry zero user-specific facts. README.md/SKILL.md are the instance layer.
- **Never print `TMDB_API_KEY`** (from `../douban-export/sources/sources.env`).
- Anchors = distinct works, kind in (film,tv,show), any watched/watching record with `rating >= 9` (0–10 scale ⇒ ≥4.5★). Current counts (verify, don't assume): 309 total; film 145 (138 tmdb), tv 162 (162 douban, 7 tmdb), show 2.
- Temp files → session scratchpad, never the repo. Tests must not touch the network or the real DB.

---

### Task 1: `recommend/pool.py` — the candidate_pool table + CLI

**Files:** Create `recommend/pool.py`, `recommend/tests/test_pool.py`.

**Interfaces (later tasks depend on these exact signatures):**
- `python3 recommend/pool.py --db PATH init`
- `... upsert --json FILE` → prints `{"inserted": n, "merged": m}`
- `... query [--kind K] [--year-from Y] [--year-to Y] [--tag T ...] [--channel C] [--needs-evidence|--has-evidence] [--limit N]` → JSON list (suppressed excluded unless `--include-suppressed`)
- `... attach-evidence --id N --json FILE`
- `... suppress-sync` → suppresses pool rows matching watched/watching works or rec-log `verdict='no'`; prints counts
- `... stats` → JSON: totals by kind, evidence-cached count, suppressed count, per-channel provenance counts

- [ ] **Step 1: failing tests** — `recommend/tests/test_pool.py`:

```python
import json, sqlite3, subprocess, sys
from pathlib import Path
POOL = str(Path(__file__).resolve().parents[1] / "pool.py")

def run(db, *a, input=None):
    return subprocess.run([sys.executable, POOL, "--db", str(db), *a],
                         capture_output=True, text=True, input=input)

def mkdb(tmp_path):
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE works (id INTEGER PRIMARY KEY, kind TEXT, title TEXT, year INTEGER,
        created_at TEXT DEFAULT '', updated_at TEXT DEFAULT '');
      CREATE TABLE records (id INTEGER PRIMARY KEY, work_id INTEGER, source TEXT,
        status TEXT, rating REAL, marked_at TEXT DEFAULT '', review TEXT DEFAULT '',
        raw TEXT DEFAULT '', updated_at TEXT DEFAULT '');
      CREATE TABLE external_ids (work_id INTEGER, namespace TEXT, value TEXT);
      CREATE TABLE recommendations (id INTEGER PRIMARY KEY, title TEXT, year INTEGER,
        kind TEXT, external_ids TEXT DEFAULT '{}', verdict TEXT, critic_killed INTEGER DEFAULT 0);
    """); con.commit(); con.close()
    assert run(db, "init").returncode == 0
    return db

ROW = {"kind":"tv","title":"Neighbor Show","year":2021,
       "external_ids":{"tmdb_tv":"555"},"tags":["comedy"],
       "aggregates":{"tmdb_vote":8.1,"tmdb_votes":900},
       "sources":[{"channel":"tmdb_rec","anchor_work_id":42,"fetched":"2026-08-23"}]}

def _upsert(db, rows, tmp_path, name="b.json"):
    f = tmp_path / name; f.write_text(json.dumps(rows))
    out = run(db, "upsert", "--json", str(f)); assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)

def test_insert_then_merge_by_external_id(tmp_path):
    db = mkdb(tmp_path)
    assert _upsert(db, [ROW], tmp_path) == {"inserted":1,"merged":0}
    again = dict(ROW, tags=["comedy","workplace"],
                 sources=[{"channel":"douban_rec","anchor_work_id":7,"fetched":"2026-08-24"}])
    assert _upsert(db, [again], tmp_path, "b2.json") == {"inserted":0,"merged":1}
    rows = json.loads(run(db, "query", "--kind", "tv").stdout)
    assert len(rows) == 1
    assert set(rows[0]["tags"]) == {"comedy","workplace"}
    assert {s["channel"] for s in rows[0]["sources"]} == {"tmdb_rec","douban_rec"}

def test_merge_by_title_year_when_no_id_overlap(tmp_path):
    db = mkdb(tmp_path)
    _upsert(db, [ROW], tmp_path)
    noid = dict(ROW, external_ids={"douban":"999"})
    assert _upsert(db, [noid], tmp_path, "b3.json")["merged"] == 1
    r = json.loads(run(db, "query").stdout)[0]
    assert r["external_ids"] == {"tmdb_tv":"555","douban":"999"}

def test_query_filters(tmp_path):
    db = mkdb(tmp_path)
    _upsert(db, [ROW, dict(ROW, title="Old Film", kind="film", year=1999,
                           external_ids={"tmdb_movie":"1"}, tags=["drama"])], tmp_path)
    assert len(json.loads(run(db,"query","--kind","film").stdout)) == 1
    assert len(json.loads(run(db,"query","--year-from","2020").stdout)) == 1
    assert len(json.loads(run(db,"query","--tag","comedy").stdout)) == 1
    assert len(json.loads(run(db,"query","--needs-evidence").stdout)) == 2

def test_evidence_attach_and_flag(tmp_path):
    db = mkdb(tmp_path)
    _upsert(db, [ROW], tmp_path)
    rid = json.loads(run(db,"query").stdout)[0]["id"]
    f = tmp_path/"e.json"; f.write_text(json.dumps({"evidence":[{"source":"tmdb","quote":"good"}]}))
    assert run(db,"attach-evidence","--id",str(rid),"--json",str(f)).returncode == 0
    assert len(json.loads(run(db,"query","--has-evidence").stdout)) == 1
    assert json.loads(run(db,"query","--needs-evidence").stdout) == []

def test_suppress_sync_watched_and_no_verdict(tmp_path):
    db = mkdb(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO works VALUES (42,'tv','Neighbor Show',2021,'','')")
    con.execute("INSERT INTO external_ids VALUES (42,'tmdb_tv','555')")
    con.execute("INSERT INTO records (work_id,source,status,rating) VALUES (42,'douban','watched',8.0)")
    con.commit(); con.close()
    _upsert(db, [ROW, dict(ROW, title="Rejected One", year=2020,
                           external_ids={"tmdb_tv":"777"})], tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO recommendations (title,year,kind,external_ids,verdict) "
                "VALUES ('Rejected One',2020,'tv','{\"tmdb_tv\":\"777\"}','no')")
    con.commit(); con.close()
    out = json.loads(run(db,"suppress-sync").stdout)
    assert out["suppressed"] == 2
    assert json.loads(run(db,"query").stdout) == []
    assert len(json.loads(run(db,"query","--include-suppressed").stdout)) == 2

def test_stats(tmp_path):
    db = mkdb(tmp_path)
    _upsert(db, [ROW], tmp_path)
    s = json.loads(run(db,"stats").stdout)
    assert s["total"] == 1 and s["by_kind"]["tv"] == 1
    assert s["evidence_cached"] == 0 and s["by_channel"]["tmdb_rec"] == 1
```

- [ ] **Step 2:** run → FAIL (pool.py missing).
- [ ] **Step 3: implement `recommend/pool.py`.** DDL:

```sql
CREATE TABLE IF NOT EXISTS candidate_pool (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL, title TEXT NOT NULL, original_title TEXT DEFAULT '',
    year INTEGER,
    external_ids TEXT NOT NULL DEFAULT '{}',
    tags TEXT NOT NULL DEFAULT '[]',
    aggregates TEXT NOT NULL DEFAULT '{}',
    shape TEXT NOT NULL DEFAULT '{}',
    sources TEXT NOT NULL DEFAULT '[]',
    evidence TEXT, evidence_fetched_at TEXT,
    suppressed INTEGER NOT NULL DEFAULT 0,
    suppressed_reason TEXT DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pool_kind_year ON candidate_pool(kind, year);
```

Implementation requirements (module docstring must state the contract):
- Upsert matching order: any shared `external_ids` (namespace,value) pair → else exact (kind, lower(title), year). Merge = union tags, append sources, merge external_ids/aggregates/shape (incoming fills gaps, never overwrites non-empty with empty), bump `updated_at`. All rows in one transaction; whole-batch validation first (required: kind, title, sources non-empty), all-or-nothing, error names row index + field like `reclog.py`.
- `query` builds WHERE from flags with parameterized SQL; `--tag` uses `EXISTS (SELECT 1 FROM json_each(tags) WHERE value = ?)` (OR across repeats); `--channel` likewise over `sources`; output rows with JSON columns decoded.
- `suppress-sync`: (a) pool rows whose external_ids match a work (via `external_ids` table) that has a watched/watching record → `suppressed=1, reason='watched'`; (b) pool rows matching a `recommendations` row (id-overlap else title+year+kind) with `verdict='no'` → `reason='rejected'`. UPDATE only, idempotent, prints `{"suppressed": n, "watched": a, "rejected": b}` (n = rows newly suppressed this run).
- `busy_timeout` 15000, same conventions as reclog.py/history.py.

- [ ] **Step 4:** run tests → all pass (plus the existing 76: `python3 -m pytest recommend/tests/ -q`).
- [ ] **Step 5:** apply `init` to real media.db (full ritual; additive only). Verify table exists; record backup filename.

---

### Task 2: `recommend/harvest_tmdb.py` — CF + recency harvest (raw-first)

**Files:** Create `recommend/harvest_tmdb.py`, `recommend/tests/test_harvest_tmdb.py`.

**Interfaces:**
- `python3 recommend/harvest_tmdb.py anchors --db PATH [--min-rating 9]` → JSON list `[{"work_id":..,"kind":"film|tv","tmdb_id":..,"media":"movie|tv","title":..}]` (media from namespace: tmdb_movie→movie, tmdb_tv→tv). One read transaction, no network.
- `... fetch --anchors FILE --raw-dir DIR [--pages 2] [--recency-months 18]` → fetches `/{media}/{id}/recommendations` per anchor + `/discover/movie` & `/discover/tv` recency pages + `/genre/{media}/list`; writes each response verbatim to `DIR/<name>.json`; prints fetch report `{"fetched": n, "failed": [...]}`. Reads `TMDB_API_KEY` from env or sources.env; never prints it. On HTTP error: record in `failed`, continue.
- `... transform --raw-dir DIR --out FILE` → pool-upsert batch JSON. No network. Per candidate: kind (movie→film, tv→tv), title/original_title/year, `external_ids` {tmdb_movie|tmdb_tv: id}, tags = genre names (mapped via the genre list file), aggregates {tmdb_vote, tmdb_votes}, sources entries `{"channel":"tmdb_rec","anchor_work_id":W,"fetched":date}` or `{"channel":"tmdb_discover_recent",...}`. Drop candidates with vote_count < 50 (junk floor) — log the dropped count.

- [ ] **Step 1: failing tests** — fixture-driven, no network:

```python
import json, subprocess, sys
from pathlib import Path
H = str(Path(__file__).resolve().parents[1] / "harvest_tmdb.py")

REC = {"results":[
  {"id": 100, "name": "Good Show", "original_name": "Good Show",
   "first_air_date": "2021-03-01", "genre_ids": [35], "vote_average": 8.0, "vote_count": 500},
  {"id": 101, "name": "Junk", "first_air_date": "2020-01-01",
   "genre_ids": [35], "vote_average": 9.9, "vote_count": 3}]}
GENRES = {"genres": [{"id": 35, "name": "Comedy"}]}

def test_transform(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()
    (raw / "rec_tv_42_p1.json").write_text(json.dumps(
        dict(REC, _meta={"channel":"tmdb_rec","anchor_work_id":42,"media":"tv",
                          "fetched":"2026-08-23"})))
    (raw / "genres_tv.json").write_text(json.dumps(GENRES))
    out = tmp_path / "batch.json"
    r = subprocess.run([sys.executable, H, "transform", "--raw-dir", str(raw),
                        "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    batch = json.loads(out.read_text())
    assert len(batch) == 1                       # vote floor dropped "Junk"
    c = batch[0]
    assert c["kind"] == "tv" and c["year"] == 2021
    assert c["external_ids"] == {"tmdb_tv": "100"}
    assert c["tags"] == ["Comedy"]
    assert c["aggregates"] == {"tmdb_vote": 8.0, "tmdb_votes": 500}
    assert c["sources"][0]["channel"] == "tmdb_rec"
    assert c["sources"][0]["anchor_work_id"] == 42
```

Also test: `anchors` against a fixture DB (reuse Task 1's `mkdb` pattern with a rated work + `tmdb_movie` id) returns media="movie"; movie-shaped results (`title`/`release_date`) parse; a raw file with no `_meta` is skipped with a warning not a crash.

- [ ] **Step 2:** FAIL. **Step 3:** implement. Fetch writes `_meta` into each saved file (channel/anchor/media/fetched) so transform is self-contained. **Step 4:** tests pass; full suite green.

---

### Task 3: `recommend/harvest_douban.py` — 也喜欢 CF harvest

**Files:** Create `recommend/harvest_douban.py`, `recommend/tests/test_harvest_douban.py`.

**Interfaces:**
- `... anchors --db PATH [--min-rating 9] [--kinds tv,show,film]` → anchors bearing a `douban` external id.
- `... fetch --anchors FILE --raw-dir DIR --checkpoint FILE [--budget 40] [--delay-min 5 --delay-max 10]` → per anchor: GET `https://movie.douban.com/subject/<id>/` via **the established douban-export curl-cffi pattern** (read `douban-export/douban_export.py` / RUNBOOK first and copy its session/headers/impersonation); save gzipped HTML to raw-dir; append to checkpoint; sleep random(delay) between requests; stop at `--budget` or on a challenge/403 (record and exit 0 with a report — a block is a finding, not a crash). Resumable: anchors already in checkpoint are skipped.
- `... transform --raw-dir DIR --out FILE` → parse each HTML's recommendations block (「喜欢这部电影/剧集的人也喜欢」) into pool-batch rows: `external_ids` {douban: id}, title, `sources` `{"channel":"douban_rec","anchor_work_id":W,"fetched":date}`. Year/kind are often absent in the block — leave year null; kind = the anchor's kind (a show's neighbors are shows; note this heuristic in the docstring). Douban aggregate rating is NOT on the block reliably — omit rather than guess.

- [ ] **Step 1 (before writing the parser): verify the markup live, once.** Fetch ONE subject page for a known anchor (respecting delays) and save it as the test fixture (`recommend/tests/fixtures/douban_subject_sample.html.gz`, plus a stripped-down inline snippet in the test). Inspect the actual recommendations block structure — id/class names, where the subject id and title live — and write the parser against what you SEE, not from memory. If the page is challenge-walled on the first try, stop and report BLOCKED (the pattern may need the RUNBOOK's exact session settings).
- [ ] **Step 2: failing parser tests** — against the saved fixture: `parse_recommendations(html)` returns ≥5 entries, each with a numeric `douban_id` and non-empty `title`; a page WITHOUT the block (fixture: strip it) returns `[]` not an exception; the challenge-shell HTML (fixture from the earlier probe if available, else a minimal `载入中` stub) is detected and reported as `blocked=True`.
- [ ] **Step 3:** implement fetch/transform per interface. **Step 4:** tests pass; full suite green. No real bulk fetching in this task — that is Task 5.

---

### Task 4: run-mode rewrite — SCOUT.md, SKILL.md, README.md

**Files:** Modify `recommend/SCOUT.md`, `.claude/skills/recommend/SKILL.md`, `recommend/README.md`. CRITIC.md untouched.

- [ ] **Step 1 — SCOUT.md:** (a) §1: replace the one-question option with a required check: "Before sweeping, decide explicitly: does this ask admit two materially different readings whose choice changes most of the slate? If yes, ask the user ONE question and wait. Log the decision either way." (b) §3 channels → a **hierarchy**: 1. candidate pool query (`pool.py query`, local); 2. shells; 3. targeted top-up (TMDB `/recommendations`/discover, Douban per budget) only for logged pool gaps; 4. LLM-generated queries last-resort only. Web search removed from interactive; one editorial pass remains digest-only for recent-Chinese-cinema recency. (c) New §"Run modes": interactive (pool-first, budget ≤~10 network calls, no auto-resweep — report thin slates honestly and offer to go deeper) vs digest (harvest/refresh first, deep funnel, auto-resweep allowed). (d) §evidence: read the pool's cached evidence first; after fetching new evidence, write it back via `pool.py attach-evidence`. (e) The scout now RECEIVES the pitch target and cells (from the orchestrator) and shortlists only candidates it can argue past the gate — note explicitly this does not weaken critic blindness (the critic still never sees scout effort; the scout knowing the bar is symmetric information, not leakage).
- [ ] **Step 2 — SKILL.md:** interactive flow = snapshot → pool query → shortlist-with-bar → cached-evidence-first dossiers → critic (unchanged dispatch incl. target+cap) → pitch → evidence write-back → log. Re-sweep: on a thin slate, ASK the user instead of auto-running; digest mode keeps auto-resweep. Digest step 0: `harvest_tmdb` (new anchors + recency) → `harvest_douban` (budget) → `pool.py upsert` → `suppress-sync` → pool `stats` into the digest report.
- [ ] **Step 3 — README.md:** add pool bindings (table, the four new CLIs with one-line purposes, raw dirs, refresh cadence, budgets), and the interactive/digest mode split.
- [ ] **Step 4 — verify:** purity grep on SCOUT.md/CRITIC.md (no user facts; no instance numbers beyond the existing Source-notes exemption); every documented command matches real argparse (`--help` each); fences balanced; full test suite still green.

---

### Task 5: bootstrap — build the real pool

- [ ] **Step 1:** DB ritual (backup; record filename). `pool.py init` already applied in Task 1.
- [ ] **Step 2 — TMDB:** `anchors` → `fetch` (all tmdb-bearing anchors, raw-first into `recommend/raw/tmdb/<date>/`) → `transform` → `pool.py upsert`. Expect roughly 138 film + 7 tv + 2 show anchors, ~2 pages each; report fetched/failed counts and the vote-floor drop count.
- [ ] **Step 3 — Douban, first tranche:** `fetch --budget 40` (≈40 anchors ≈ 5–8 min of polite delays; prioritize kind=tv). Transform → upsert. Report checkpoint progress (e.g. 40/164) — the remainder rides subsequent sessions/digests; that is by design, not a shortfall.
- [ ] **Step 4:** `suppress-sync`, then `pool.py stats` — report the pool's size, by-kind, by-channel numbers. Sanity: total ≥ 800; tv candidates from douban_rec > 0; zero suppressed rows visible in default `query`.
- [ ] **Step 5:** register in ARCHITECTURE.md (candidate_pool + harvesters, one entry each, matching document voice) and STATE.md (dated section: pool bootstrapped, counts, backup filename, douban checkpoint position).

---

### Task 6 (USER-GATED): wiring + retest

- [ ] **Step 1:** Ask Anping to approve adding the harvest/refresh steps to the monthly scheduled pipeline (standing-automation change — requires his explicit yes; present the exact commands to be added).
- [ ] **Step 2:** Run one real interactive ask of his choosing end-to-end in pool-first mode. Measure wall-clock and network-call count against the ≤5 min target; report honestly, including pool gaps hit.
- [ ] **Step 3:** Record his verdicts; STATE.md close-out.

## Deferred (spec §8)
tmdb_tv enrichment via NeoDB cross-refs · Trakt.tv (needs his API key) · staleness policy beyond monthly.
