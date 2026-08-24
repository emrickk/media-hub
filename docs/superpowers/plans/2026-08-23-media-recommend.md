# Media Recommend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the film/TV recommendation system per the approved spec: scout funnel + blind critic + `recommendations` table in media.db + `/recommend` skill, engine user-agnostic, instance #1 = Anping.

**Architecture:** Two Python helpers (`reclog.py` for the recommendations table, `history.py` for the one-transaction history snapshot) plus three methodology documents (SCOUT.md, CRITIC.md — engine, user-agnostic) and a thin skill entry point whose instance bindings live in README.md. The LLM session is the runtime; the helpers are its deterministic I/O edges.

**Tech Stack:** Python 3.10+ stdlib (`sqlite3`, `argparse`, `json`) — no third-party deps in helpers; pytest for tests; `curl` + TMDB API for the probe task; Claude Code skill (markdown).

**Spec:** `media-hub/docs/superpowers/specs/2026-08-23-media-recommend-design.md` — read it before executing any task. Part A = engine, Part B = profile schema, Part C = instance bindings.

## Global Constraints

- **No git.** `AI Space` is not a git repository (iCloud is the store). Every "commit" step in the normal workflow is replaced by a verification step. Do not `git init`.
- **DB discipline (spec C3):** before a session's FIRST write to media.db: `lsof media-hub/media.db*` must show no other writer, check STATE.md lane ownership, then `sqlite3 media.db "PRAGMA wal_checkpoint(TRUNCATE);" && cp media.db backups/media-recommend-$(date +%Y%m%d-%H%M%S).db`. Reads for a pipeline run happen in ONE transaction before any network I/O. Never destructive: no DELETE, no DROP, no bulk UPDATE.
- **External ids are verified at source, never from memory.**
- **Chinese-first identity:** douban_id + title + year is definitive; absence from IMDb/TMDB is a documented negative, not a failure.
- **Engine docs contain zero user-specific facts.** SCOUT.md and CRITIC.md must read "the profile" / "the user"; anything Anping-specific goes in `recommend/README.md` (instance bindings) or DIGEST-INTENT.md. Reviewers should reject any task that leaks instance facts into engine docs.
- **Star scale:** predictions are in the user's star language (0.5–5.0, `predicted_stars REAL`). `records.rating` is 0–10; conversion is `stars = rating / 2`. Never mix the scales in one field.
- **kinds in scope v1:** `film`, `tv`, `show`, `drama` (all four are film/TV-lane values present in works; games/books/music excluded).
- **Temp files** go to the session scratchpad, never `/tmp`, never the repo.
- Session reports end with counts + a machine-readable skip/failure list (RUNBOOK standard).

---

### Task 1: `recommendations` table + `reclog.py` helper

**Files:**
- Create: `media-hub/recommend/reclog.py`
- Create: `media-hub/recommend/tests/test_reclog.py`
- Modify: `media-hub/ARCHITECTURE.md` (register the new table + consumer)
- Modify: `media-hub/STATE.md` (schema change is state)

**Interfaces:**
- Produces CLI (used by SKILL.md in Task 5 and calibration in Task 7):
  - `python3 recommend/reclog.py --db PATH init`
  - `python3 recommend/reclog.py --db PATH log --json FILE` → prints inserted row ids as JSON list
  - `python3 recommend/reclog.py --db PATH check --title T [--year Y] [--ext namespace:value ...]` → JSON `{"prior": [...rows...]}`
  - `python3 recommend/reclog.py --db PATH verdict --id N --verdict {interested,no,meh,watched} [--note S]`
  - `python3 recommend/reclog.py --db PATH pending` → pitched rows with NULL verdict
  - `python3 recommend/reclog.py --db PATH stats` → hit rate + sealed-vs-actual join
- Produces table `recommendations` (DDL below) — consumed by Task 2's snapshot.

- [ ] **Step 1: Ensure pytest is available**

Run: `python3 -m pytest --version || python3 -m pip install --user pytest`

- [ ] **Step 2: Write the failing tests**

`media-hub/recommend/tests/test_reclog.py`:

```python
import json, sqlite3, subprocess, sys
from pathlib import Path

RECLOG = str(Path(__file__).resolve().parents[1] / "reclog.py")

def run(db, *args, input=None):
    return subprocess.run([sys.executable, RECLOG, "--db", str(db), *args],
                         capture_output=True, text=True, input=input)

def make_db(tmp_path):
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE works (id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
        title TEXT NOT NULL, year INTEGER, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL);
      CREATE TABLE records (id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL,
        source TEXT NOT NULL, status TEXT NOT NULL, rating REAL,
        marked_at TEXT DEFAULT '', review TEXT DEFAULT '', raw TEXT DEFAULT '',
        updated_at TEXT NOT NULL);
    """)
    con.commit(); con.close()
    assert run(db, "init").returncode == 0
    return db

SAMPLE = [{
    "kind": "tv", "title": "Test Show", "year": 2024,
    "external_ids": {"tmdb": "123", "imdb": "tt0000001"},
    "dossier": {"case": "tight writing", "evidence": []},
    "predicted_stars": 4.5, "predicted_confidence": "medium",
    "critic_killed": 0, "kill_reason": "",
    "session_date": "2026-08-23T12:00:00", "intention": "test ask"
}]

def test_init_creates_table(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(recommendations)")}
    assert {"intention", "kind", "title", "year", "external_ids", "dossier",
            "predicted_stars", "predicted_confidence", "critic_killed",
            "kill_reason", "verdict", "verdict_note", "verdict_date",
            "work_id", "session_date"} <= cols

def test_log_and_check_by_ext_id(tmp_path):
    db = make_db(tmp_path)
    f = tmp_path / "batch.json"; f.write_text(json.dumps(SAMPLE))
    out = run(db, "log", "--json", str(f))
    assert out.returncode == 0
    ids = json.loads(out.stdout)
    assert len(ids) == 1
    chk = json.loads(run(db, "check", "--title", "ignored",
                         "--ext", "tmdb:123").stdout)
    assert len(chk["prior"]) == 1
    assert chk["prior"][0]["title"] == "Test Show"

def test_check_by_title_year(tmp_path):
    db = make_db(tmp_path)
    f = tmp_path / "b.json"; f.write_text(json.dumps(SAMPLE))
    run(db, "log", "--json", str(f))
    chk = json.loads(run(db, "check", "--title", "test show",
                         "--year", "2024").stdout)
    assert len(chk["prior"]) == 1          # case-insensitive title match

def test_verdict_and_pending(tmp_path):
    db = make_db(tmp_path)
    f = tmp_path / "b.json"; f.write_text(json.dumps(SAMPLE))
    rid = json.loads(run(db, "log", "--json", str(f)).stdout)[0]
    pend = json.loads(run(db, "pending").stdout)
    assert [r["id"] for r in pend] == [rid]
    assert run(db, "verdict", "--id", str(rid), "--verdict", "no",
               "--note", "not my thing").returncode == 0
    assert json.loads(run(db, "pending").stdout) == []
    chk = json.loads(run(db, "check", "--ext", "tmdb:123").stdout)
    assert chk["prior"][0]["verdict"] == "no"

def test_verdict_rejects_bad_value(tmp_path):
    db = make_db(tmp_path)
    assert run(db, "verdict", "--id", "1", "--verdict", "amazing").returncode != 0

def test_killed_rows_not_pending(tmp_path):
    db = make_db(tmp_path)
    killed = [dict(SAMPLE[0], title="Dead One", critic_killed=1,
                   kill_reason="fact check failed",
                   external_ids={"tmdb": "999"})]
    f = tmp_path / "k.json"; f.write_text(json.dumps(killed))
    run(db, "log", "--json", str(f))
    assert json.loads(run(db, "pending").stdout) == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd "media-hub" && python3 -m pytest recommend/tests/test_reclog.py -v`
Expected: FAIL / errors (reclog.py does not exist).

- [ ] **Step 4: Write `reclog.py`**

```python
#!/usr/bin/env python3
"""reclog.py: the recommendations log in media.db (spec Part A §A5).

The only write surface of the recommend system. Insert-and-update only —
this tool has no destructive commands by design.
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from datetime import datetime, timezone

DDL = """
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY,
    session_date TEXT NOT NULL,
    intention TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    year INTEGER,
    external_ids TEXT NOT NULL DEFAULT '{}',
    work_id INTEGER REFERENCES works(id),
    dossier TEXT NOT NULL DEFAULT '{}',
    predicted_stars REAL,
    predicted_confidence TEXT,
    critic_killed INTEGER NOT NULL DEFAULT 0,
    kill_reason TEXT NOT NULL DEFAULT '',
    verdict TEXT CHECK (verdict IN ('interested','no','meh','watched') OR verdict IS NULL),
    verdict_note TEXT NOT NULL DEFAULT '',
    verdict_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reco_title ON recommendations(title, year);
"""
VERDICTS = ("interested", "no", "meh", "watched")

def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con

def cmd_init(con, args):
    con.executescript(DDL); con.commit()
    print("ok")

def cmd_log(con, args):
    rows = json.loads(open(args.json, encoding="utf-8").read())
    if not isinstance(rows, list):
        sys.exit("log --json expects a JSON list of candidate rows")
    ids, ts = [], now()
    for r in rows:
        cur = con.execute(
            """INSERT INTO recommendations
               (session_date, intention, kind, title, year, external_ids,
                work_id, dossier, predicted_stars, predicted_confidence,
                critic_killed, kill_reason, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r.get("session_date") or ts, r["intention"], r["kind"],
             r["title"], r.get("year"),
             json.dumps(r.get("external_ids", {}), ensure_ascii=False),
             r.get("work_id"),
             json.dumps(r.get("dossier", {}), ensure_ascii=False),
             r.get("predicted_stars"), r.get("predicted_confidence"),
             int(r.get("critic_killed", 0)), r.get("kill_reason", ""),
             ts, ts))
        ids.append(cur.lastrowid)
    con.commit()
    print(json.dumps(ids))

def _row_out(row) -> dict:
    d = dict(row)
    for k in ("external_ids", "dossier"):
        try: d[k] = json.loads(d[k])
        except (TypeError, ValueError): pass
    return d

def cmd_check(con, args):
    hits, seen = [], set()
    for pair in args.ext or []:
        ns, _, val = pair.partition(":")
        for row in con.execute(
                "SELECT * FROM recommendations WHERE json_extract(external_ids, ?) = ?",
                (f"$.{ns}", val)):
            if row["id"] not in seen:
                seen.add(row["id"]); hits.append(_row_out(row))
    if args.title and args.year:
        for row in con.execute(
                "SELECT * FROM recommendations WHERE lower(title)=lower(?) AND year=?",
                (args.title, args.year)):
            if row["id"] not in seen:
                seen.add(row["id"]); hits.append(_row_out(row))
    print(json.dumps({"prior": hits}, ensure_ascii=False))

def cmd_verdict(con, args):
    cur = con.execute(
        """UPDATE recommendations
           SET verdict=?, verdict_note=?, verdict_date=?, updated_at=?
           WHERE id=?""",
        (args.verdict, args.note or "", now(), now(), args.id))
    con.commit()
    if cur.rowcount != 1:
        sys.exit(f"no recommendation row with id {args.id}")
    print("ok")

def cmd_pending(con, args):
    rows = con.execute(
        """SELECT * FROM recommendations
           WHERE critic_killed=0 AND verdict IS NULL ORDER BY id""").fetchall()
    print(json.dumps([_row_out(r) for r in rows], ensure_ascii=False))

def cmd_stats(con, args):
    pitched = con.execute(
        "SELECT count(*) FROM recommendations WHERE critic_killed=0").fetchone()[0]
    hits = con.execute(
        """SELECT count(*) FROM recommendations
           WHERE critic_killed=0 AND verdict IN ('interested','watched')""").fetchone()[0]
    sealed = con.execute(
        """SELECT r.id, r.title, r.predicted_stars, rec.rating/2.0 AS actual_stars
           FROM recommendations r
           JOIN records rec ON rec.work_id = r.work_id
             AND rec.status='watched' AND rec.rating IS NOT NULL
           WHERE r.critic_killed=0 AND r.work_id IS NOT NULL
             AND r.predicted_stars IS NOT NULL""").fetchall()
    print(json.dumps({
        "pitched": pitched, "hits": hits,
        "hit_rate": round(hits / pitched, 3) if pitched else None,
        "sealed_vs_actual": [dict(r) for r in sealed],
    }, ensure_ascii=False))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("log"); s.add_argument("--json", required=True)
    s = sub.add_parser("check")
    s.add_argument("--title"); s.add_argument("--year", type=int)
    s.add_argument("--ext", action="append",
                   help="namespace:value, repeatable")
    s = sub.add_parser("verdict")
    s.add_argument("--id", type=int, required=True)
    s.add_argument("--verdict", choices=VERDICTS, required=True)
    s.add_argument("--note")
    sub.add_parser("pending")
    sub.add_parser("stats")
    args = p.parse_args()
    con = connect(args.db)
    try:
        {"init": cmd_init, "log": cmd_log, "check": cmd_check,
         "verdict": cmd_verdict, "pending": cmd_pending,
         "stats": cmd_stats}[args.cmd](con, args)
    finally:
        con.close()

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "media-hub" && python3 -m pytest recommend/tests/test_reclog.py -v`
Expected: 6 passed. (Note: `--verdict amazing` fails at argparse level via `choices` — that is the intended rejection path.)

- [ ] **Step 6: Apply `init` to the real media.db, with the write ritual**

Run, in order (STOP if the lsof shows another writer):
```bash
cd "media-hub"
lsof media.db* ; true
sqlite3 media.db "PRAGMA wal_checkpoint(TRUNCATE);"
cp media.db backups/media-recommend-init-$(date +%Y%m%d-%H%M%S).db
python3 recommend/reclog.py --db media.db init
sqlite3 media.db "PRAGMA table_info(recommendations);" | head -5
```
Expected: table exists; no other tables touched.

- [ ] **Step 7: Register in ARCHITECTURE.md and STATE.md**

ARCHITECTURE.md: in the schema/tables section, add one entry:
> `recommendations` — the recommend system's log (spec `docs/superpowers/specs/2026-08-23-media-recommend-design.md` §A5): every pitched/killed candidate with sealed `predicted_stars`, verdicts, dossier JSON. Written only by `recommend/reclog.py` (insert/update, never destructive). Consumer: the `/recommend` skill.

STATE.md: add a dated section noting the new table, the backup filename created in Step 6, and that the recommend lane now exists.

---

### Task 2: `history.py` — one-transaction history snapshot

**Files:**
- Create: `media-hub/recommend/history.py`
- Create: `media-hub/recommend/tests/test_history.py`

**Interfaces:**
- Consumes: `recommendations` table (Task 1) — read-only here.
- Produces CLI (used by SKILL.md Task 5; MUST run before any network I/O in a session):
  - `python3 recommend/history.py --db PATH snapshot [--kinds film,tv,show,drama] [--out FILE]`
  - Output JSON shape (exact keys):
    ```json
    {
      "generated_at": "...", "kinds": ["film","tv","show","drama"],
      "rated":    [{"work_id":1,"kind":"tv","title":"...","original_title":"...",
                    "year":2020,"stars":4.5,"review":"...","marked_at":"...",
                    "source":"douban","external_ids":{"douban":"123"}}],
      "wishlist": [{"work_id":2,"kind":"film","title":"...","year":2021,
                    "external_ids":{}}],
      "shells":   [{"work_id":3,"kind":"tv","title":"...","year":2024}],
      "rec_log":  [{"id":1,"title":"...","year":2024,"kind":"tv",
                    "external_ids":{},"critic_killed":0,"verdict":"no"}],
      "counts":   {"rated":0,"wishlist":0,"shells":0,"rec_log":0}
    }
    ```
  - `rated` = records with status `watched`/`watching` and non-NULL rating, plus unrated `watched` rows (they carry review text); stars = rating/2. `shells` = works with a plex/steam record but no watched/rated record (library presence only). All reads in ONE `BEGIN` transaction.

- [ ] **Step 1: Write the failing tests**

`media-hub/recommend/tests/test_history.py`:

```python
import json, sqlite3, subprocess, sys
from pathlib import Path

HISTORY = str(Path(__file__).resolve().parents[1] / "history.py")
RECLOG  = str(Path(__file__).resolve().parents[1] / "reclog.py")

def make_db(tmp_path):
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE works (id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
        title TEXT NOT NULL, original_title TEXT DEFAULT '', year INTEGER,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
      CREATE TABLE records (id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL,
        source TEXT NOT NULL, status TEXT NOT NULL, rating REAL,
        marked_at TEXT DEFAULT '', review TEXT DEFAULT '', raw TEXT DEFAULT '',
        updated_at TEXT NOT NULL);
      CREATE TABLE external_ids (work_id INTEGER NOT NULL,
        namespace TEXT NOT NULL, value TEXT NOT NULL);
    """)
    ts = "2026-01-01T00:00:00"
    w = [(1,"tv","Watched Show","",2020,ts,ts),
         (2,"film","Wish Film","",2021,ts,ts),
         (3,"tv","Plex Shell","",2024,ts,ts),
         (4,"game","A Game","",2022,ts,ts)]
    con.executemany("INSERT INTO works VALUES (?,?,?,?,?,?,?)", w)
    r = [(1,1,"douban","watched",9.0,"2026-01-02","great pacing","",ts),
         (2,2,"douban","wishlist",None,"","","",ts),
         (3,3,"plex","owned",None,"","","",ts),
         (4,4,"steam","watched",8.0,"","","",ts)]
    con.executemany("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)", r)
    con.execute("INSERT INTO external_ids VALUES (1,'douban','111')")
    con.commit(); con.close()
    subprocess.run([sys.executable, RECLOG, "--db", str(db), "init"], check=True)
    return db

def snap(db, *extra):
    out = subprocess.run([sys.executable, HISTORY, "--db", str(db),
                          "snapshot", *extra], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)

def test_sections_and_kind_filter(tmp_path):
    s = snap(make_db(tmp_path))
    assert [r["title"] for r in s["rated"]] == ["Watched Show"]   # game excluded
    assert s["rated"][0]["stars"] == 4.5
    assert s["rated"][0]["review"] == "great pacing"
    assert s["rated"][0]["external_ids"] == {"douban": "111"}
    assert [w["title"] for w in s["wishlist"]] == ["Wish Film"]
    assert [w["title"] for w in s["shells"]] == ["Plex Shell"]
    assert s["counts"] == {"rated":1, "wishlist":1, "shells":1, "rec_log":0}

def test_rec_log_included(tmp_path):
    db = make_db(tmp_path)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps([{"kind":"tv","title":"Old Pitch","year":2019,
        "intention":"x","external_ids":{"tmdb":"5"}}]))
    subprocess.run([sys.executable, RECLOG, "--db", str(db),
                    "log", "--json", str(batch)], check=True)
    s = snap(db)
    assert s["counts"]["rec_log"] == 1
    assert s["rec_log"][0]["title"] == "Old Pitch"

def test_out_file(tmp_path):
    db = make_db(tmp_path)
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(db), "snapshot",
                    "--out", str(dest)], check=True)
    assert json.loads(dest.read_text())["counts"]["rated"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "media-hub" && python3 -m pytest recommend/tests/test_history.py -v`
Expected: FAIL (history.py missing).

- [ ] **Step 3: Write `history.py`**

```python
#!/usr/bin/env python3
"""history.py: one-transaction read snapshot of the user's film/TV history.

Spec Part A §A3 step 2: ALL media.db reads for a pipeline run happen here,
in one BEGIN..COMMIT, BEFORE any network I/O. The scout and critic both
work from this file, never from live queries mid-run.
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from datetime import datetime, timezone

DEFAULT_KINDS = ("film", "tv", "show", "drama")

def snapshot(con: sqlite3.Connection, kinds) -> dict:
    con.row_factory = sqlite3.Row
    ph = ",".join("?" for _ in kinds)
    con.execute("BEGIN")
    ext = {}
    for r in con.execute(f"""SELECT e.work_id, e.namespace, e.value
                             FROM external_ids e JOIN works w ON w.id=e.work_id
                             WHERE w.kind IN ({ph})""", kinds):
        ext.setdefault(r["work_id"], {})[r["namespace"]] = r["value"]
    rated = [dict(work_id=r["work_id"], kind=r["kind"], title=r["title"],
                  original_title=r["original_title"], year=r["year"],
                  stars=(r["rating"] / 2 if r["rating"] is not None else None),
                  review=r["review"], marked_at=r["marked_at"],
                  source=r["source"], external_ids=ext.get(r["work_id"], {}))
             for r in con.execute(f"""
        SELECT w.id AS work_id, w.kind, w.title, w.original_title, w.year,
               rec.rating, rec.review, rec.marked_at, rec.source
        FROM records rec JOIN works w ON w.id = rec.work_id
        WHERE w.kind IN ({ph}) AND rec.status IN ('watched','watching')
        ORDER BY rec.marked_at DESC, w.id""", kinds)]
    wishlist = [dict(work_id=r["work_id"], kind=r["kind"], title=r["title"],
                     year=r["year"], external_ids=ext.get(r["work_id"], {}))
                for r in con.execute(f"""
        SELECT DISTINCT w.id AS work_id, w.kind, w.title, w.year
        FROM records rec JOIN works w ON w.id = rec.work_id
        WHERE w.kind IN ({ph}) AND rec.status = 'wishlist'
        ORDER BY w.id""", kinds)]
    shells = [dict(r) for r in con.execute(f"""
        SELECT DISTINCT w.id AS work_id, w.kind, w.title, w.year
        FROM works w JOIN records rec ON rec.work_id = w.id
        WHERE w.kind IN ({ph})
          AND w.id NOT IN (SELECT work_id FROM records
                           WHERE status IN ('watched','watching','wishlist'))
        ORDER BY w.id""", kinds)]
    rec_log = [dict(id=r["id"], title=r["title"], year=r["year"],
                    kind=r["kind"],
                    external_ids=json.loads(r["external_ids"] or "{}"),
                    critic_killed=r["critic_killed"], verdict=r["verdict"])
               for r in con.execute("SELECT * FROM recommendations ORDER BY id")]
    con.execute("COMMIT")
    return {
        "generated_at": datetime.now(timezone.utc).astimezone()
                        .isoformat(timespec="seconds"),
        "kinds": list(kinds),
        "rated": rated, "wishlist": wishlist, "shells": shells,
        "rec_log": rec_log,
        "counts": {"rated": len(rated), "wishlist": len(wishlist),
                   "shells": len(shells), "rec_log": len(rec_log)},
    }

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--kinds", default=",".join(DEFAULT_KINDS))
    s.add_argument("--out")
    args = p.parse_args()
    con = sqlite3.connect(args.db)
    try:
        data = snapshot(con, tuple(k.strip() for k in args.kinds.split(",") if k.strip()))
    finally:
        con.close()
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
        print(json.dumps(data["counts"]))
    else:
        print(text)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "media-hub" && python3 -m pytest recommend/tests/ -v`
Expected: all pass (reclog's 6 + history's 3).

- [ ] **Step 5: Smoke-run against the real DB (read-only)**

```bash
cd "media-hub"
python3 recommend/history.py --db media.db snapshot --out "$SCRATCHPAD/snap.json" 
```
(Use the session scratchpad path for `$SCRATCHPAD`.) Expected: counts printed; `rated` ≈ 1,500–2,100 (douban 1,544 rated + plex/letterboxd watched rows), `rec_log` = 0. Report the actual counts.

---

### Task 3: `SCOUT.md` + `DIGEST-INTENT.md`

**Files:**
- Create: `media-hub/recommend/SCOUT.md` (engine doc — ZERO instance facts)
- Create: `media-hub/recommend/DIGEST-INTENT.md` (instance file)
- Create: `media-hub/recommend/logs/.gitkeep` (empty placeholder file so the dir exists)

**Interfaces:**
- Consumes: `history.py snapshot` JSON (Task 2 shape).
- Produces: the dossier JSON schema (§5 below) — CRITIC.md (Task 4) and `reclog.py log` batches (Task 1) use exactly this shape; the funnel-log file convention `recommend/logs/<YYYY-MM-DD>-<slug>.md` used by Tasks 4, 5, 7.

- [ ] **Step 1: Write `SCOUT.md` with exactly this content**

````markdown
# SCOUT — retrieval & funnel contract (engine; user-agnostic)

Implements spec Part A §A3 steps 1–4. Instance bindings (which profile,
which DB, which kinds, key paths) live in README.md — this document never
names a specific user or their tastes.

## 0. Session setup
1. Read the profile document (binding in README.md) in full.
2. Take the history snapshot FIRST — before any network I/O:
   `python3 recommend/history.py --db <db> snapshot --out <scratchpad>/snap.json`
3. Open a funnel log at `recommend/logs/<YYYY-MM-DD>-<slug>.md` (slug from
   the ask). Every stage below appends to it as it happens.

## 1. Interpret the ask
- The ask is free text; interpret it as a whole. There is NO taxonomy and
  no fixed set of axes — whatever the ask expresses (a genre, a mood, a
  reference title, "surprise me", "something bad on purpose") IS the
  target. Do not force it into any schema.
- If the ask materially splits two ways (two readings → materially
  different candidate sets), ask the user ONE question. Otherwise proceed
  and state the working interpretation in the pitch.
- If the ask is empty (digest mode), read DIGEST-INTENT.md as the ask.
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
- **Excluded**: every watched/watching item; every rec_log row with
  verdict `no` (never re-enter the funnel); wishlist items (they can only
  appear in the pitch as an "already on your list" note).

## 3. Sweep — channels (target ~100–200 gathered titles)
Use any mix; log each query and its yield. Typical channels:
a. **Anchor expansion**: similar/recommendations APIs for each anchor
   (e.g. TMDB `/movie/{id}/similar`, `/tv/{id}/recommendations`); works
   by the creators/directors/writers of top anchors.
b. **Generated queries**: derive search keywords/tags from ask ×
   neighborhood; run against catalog surfaces (TMDB discover with
   genre/keyword filters, Douban tag pages, NeoDB search). See
   "Source notes" below for which surfaces retrieve well.
c. **Review mining**: read reviews of anchors on review sites (Douban,
   Letterboxd, Rotten Tomatoes…); reviewers naming neighbors ("does what
   X does, better") is a retrieval channel no tag search replicates.
d. **Editorial**: web-search curated/critic lists matching the ask.
e. **Recency**: notable releases since the last run (digest mode mainly).
Rules: identity is Chinese-first where applicable (douban id + title +
year definitive; absence from IMDb/TMDB is a documented negative).
Dedup the gathered pool against §2 Excluded before narrowing.

## 4. Narrow — progressive cuts, progressive evidence
- **Cut 1 (→ ~40)**: metadata only (title/year/genre/shape/creators + what
  you already know). One line per elimination in the funnel log:
  `- OUT <title> (<year>): <reason>`.
- **Cut 2 (→ ~12)**: pull light review evidence for all survivors (1–2
  sources each, skim level). Same elimination logging.
- **Dossiers (~12)**: deep evidence per finalist (below).
Stage sizes are targets, not laws — log the actual sizes. Never lower the
evidence bar to fill a stage; a thin stage is reported thin.

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
  "evidence": [{"source": "letterboxd|douban|rt|...", "url": "...",
                 "quote": "verbatim quote you actually read"}],
  "history_analogues": [{"work_id": 0, "title": "...", "stars": 0.0,
                          "relation": "why comparable"}],
  "confidence": {"ids": "high|medium|low", "shape": "...", "case": "..."},
  "flags": ["anything the critic should probe"]
}
```
- `external_ids` are verified at source during dossier building — open the
  actual TMDB/Douban/IMDb page; never write an id from memory.
- Thin dossiers are submitted anyway; killing is the critic's job and
  kills are data.
- Write all dossiers to `<scratchpad>/dossiers.json` (a JSON list) and
  copy them into the funnel log.

## 6. Handoff
Spawn the critic per CRITIC.md. The critic receives ONLY: the profile,
snap.json, dossiers.json, and CRITIC.md itself. Never pass the funnel
log, channel yields, or any account of search effort — blindness is the
point (spec A2.6, A3).

## Source notes (maintained by probe runs; append findings here)
_(populated by the source-surface probe task; keep entries dated)_
````

- [ ] **Step 2: Write `DIGEST-INTENT.md` with exactly this content**

```markdown
# Digest default ask (instance file — edit freely)

下饭剧优先：低认知负荷、分集式、可打断，可以边吃饭/边玩游戏放的剧；
外加一部值得专门找时间看的高密度电影。范围：新近上映/开播或口碑新起的，
以及经典中明显契合口味而从未看过的。总量小而准：剧 2–3 部、电影 1–2 部。
```

- [ ] **Step 3: Verify engine purity**

Run: `grep -inE "anping|douban user|emrick|下饭|尴尬|taste\.md" media-hub/recommend/SCOUT.md`
Expected: no matches (TASTE.md may only be referenced via "the profile document (binding in README.md)"). If matches, fix before proceeding.

---

### Task 4: `CRITIC.md`

**Files:**
- Create: `media-hub/recommend/CRITIC.md` (engine doc — ZERO instance facts)

**Interfaces:**
- Consumes: profile doc, `snap.json`, `dossiers.json` (Task 3 schema).
- Produces: critic output JSON (schema below) — SKILL.md (Task 5) converts it into the pitch and the `reclog.py log` batch.

- [ ] **Step 1: Write `CRITIC.md` with exactly this content**

````markdown
# CRITIC — adversarial gate contract (engine; user-agnostic)

Implements spec Part A §A3 (critic) and A2.3/A2.4. You are a fresh
context. You must receive ONLY: the profile document, the history
snapshot (snap.json), the dossiers (dossiers.json), and this file. If you
have been given the scout's search transcript or funnel log, STOP and
report a contract violation instead of proceeding.

Your stance is adversarial: your job is to kill candidates, not to
protect the effort spent finding them (you can't — you never saw it).

## Core judgment: predicted rating
For each dossier, the central question is: **given this user's rated
history and review text, what would THEY rate this title?** Express the
answer in the user's own star language as defined in the profile's
rating-semantics section, with a confidence grade and an evidence chain.
The pitch threshold is the profile's enthusiasm threshold — UNLESS the
ask explicitly moves the bar (e.g. the user asked for something bad on
purpose; the ask always wins).

How to argue a prediction:
- **By analogy, with names.** Cite specific rated items from snap.json
  (the dossier's `history_analogues` are the scout's suggestions — check
  them and find better ones if they're weak) with the user's actual stars
  and review words.
- **Case law, not labels.** Where a profile entry (taste dimension or
  hard constraint) is in play, answer its DISCRIMINATING QUESTION using
  the dossier's review evidence, and argue which side's exemplars the
  candidate resembles. Never apply an entry name as a verdict by itself.
- **Hard constraints** are case-law entries at maximal confidence: strong
  evidence toward the bottom of the user's scale, still argued with their
  calibrated nuance and exemplar boundaries.
- **Low-confidence profile entries** that fire become stated risks in the
  survivor annotation, not silent kills.
- Evidence quotes must come from the dossier or snap.json. You have no
  network access by contract; a claim needing outside verification is an
  `unverifiable` finding, handled under check 1.

## Checklist per candidate, in order (log every kill: rule + evidence)
1. **Fact/identity**: external_ids present and self-consistent with shape
   facts? A dossier whose CENTRAL facts are unverified or contradictory
   (wrong-year phantom, id mismatch, made-up season count) = KILL
   (`fact`). Peripheral gaps → flag as risk instead.
2. **Dedup**: candidate matches (by external id, else title+year) a
   watched/watching item, or a rec_log row with verdict `no` = KILL
   (`dedup`). Matches a wishlist item → demote to "already on your list"
   note (`wishlist-note`), not a pitch slot.
3. **Predicted rating**: as above. Below threshold = KILL (`predicted`),
   citing the analogy chain.
4. **Ask fit**: does it actually answer the stated ask (as interpreted in
   the dossier's `ask_fit`)? Quality never rescues a mismatch = KILL
   (`ask-fit`).
5. **Reason quality**: the case must be argued in the profile's
   persuasive terms; category-membership arguments, aggregate-score
   arguments, or an evidence-free case = KILL (`reason-quality`) — or
   SEND-BACK if the candidate seems strong but the dossier is lazy.
6. **Survivor annotation**: residual risks (including any low-confidence
   profile entries that fired) + overall confidence.

## Floor rule
If fewer than 2 survive: do NOT lower the bar. Return your kill report to
the orchestrator requesting ONE re-sweep from a different angle. After
that, whatever survives is the honest answer — the pitch reports the real
count and the reasons.

## Output — a single JSON document
```json
{
  "contract_ok": true,
  "candidates": [{
    "title": "...", "year": 2024,
    "outcome": "survive|kill|sendback|wishlist-note",
    "kill_rule": "fact|dedup|predicted|ask-fit|reason-quality|null",
    "kill_evidence": "one paragraph, specific",
    "predicted_stars": 4.5, "predicted_confidence": "high|medium|low",
    "evidence_chain": ["named analogue + user's stars/words → inference",
                        "review evidence → discriminating-question answer"],
    "residual_risks": ["..."]
  }],
  "resweep_requested": false,
  "resweep_angle": null
}
```
````

- [ ] **Step 2: Verify engine purity**

Run: `grep -inE "anping|emrick|下饭|尴尬|taste\.md|douban user" media-hub/recommend/CRITIC.md`
Expected: no matches.

- [ ] **Step 3: Cross-check schema consistency**

Verify by eye: every field CRITIC.md reads (`history_analogues`, `ask_fit`, `evidence`, `confidence`, `flags`) exists in SCOUT.md §5's dossier schema; `predicted_stars`/`predicted_confidence`/`kill_reason` naming matches `reclog.py` DDL (Task 1). Fix any drift now.

---

### Task 5: skill entry point + `README.md` (instance bindings)

**Files:**
- Create: `media-hub/.claude/skills/recommend/SKILL.md`
- Create: `media-hub/recommend/README.md`

**Interfaces:**
- Consumes: everything above — `history.py snapshot`, SCOUT.md, CRITIC.md, `reclog.py`.
- Produces: the `/recommend` skill; README.md is the ONE place instance facts live.

- [ ] **Step 1: Write `media-hub/recommend/README.md` with exactly this content**

```markdown
# recommend/ — instance bindings (user #1)

The engine is SCOUT.md + CRITIC.md (user-agnostic; spec Part A). This
file binds the engine to its first instance. A second user would get a
different README and profile — nothing else changes.

- **Profile document:** `../TASTE.md` (calibrated 2026-07-28; the spec's
  Part B schema in prose form). Enthusiasm threshold: **≥4★** per its
  rating semantics (3★＝一般还行, 4★＝挺好看值得, 5★＝情绪冲顶).
- **History DB:** `../media.db` — kinds in scope: `film,tv,show,drama`.
- **Helpers:** `history.py` (snapshot; run BEFORE any network I/O),
  `reclog.py` (the only write surface; init already applied).
- **Funnel logs:** `logs/<YYYY-MM-DD>-<slug>.md`, one per session.
- **Digest ask:** `DIGEST-INTENT.md`.
- **Keys:** TMDB_API_KEY in `../../douban-export/sources/sources.env`.
- **Write ritual (before a session's first media.db write):**
  `lsof ../media.db*` (no other writer) → check ../STATE.md lanes →
  `sqlite3 ../media.db "PRAGMA wal_checkpoint(TRUNCATE);"` →
  `cp ../media.db ../backups/media-recommend-$(date +%Y%m%d-%H%M%S).db`.
- **Verdict flow:** `interested` rows go to the wishlist only with the
  user's explicit confirmation, via `mediahub.py add` — never silently.
- **Spec:** `../docs/superpowers/specs/2026-08-23-media-recommend-design.md`.
```

- [ ] **Step 2: Write `media-hub/.claude/skills/recommend/SKILL.md` with exactly this content**

````markdown
---
name: recommend
description: Recommend film/TV using the user's watch history + taste profile. Use when the user asks what to watch, wants recommendations, says /recommend <ask>, or the digest schedule fires. The ask may be ANY free text (genre, mood, "like X but Y", 下饭, "something bad on purpose"...). Not for games/books/music (not built yet).
---

# /recommend — orchestration

You are the orchestrator. Methodology lives in `recommend/SCOUT.md`
(retrieval + funnel) and `recommend/CRITIC.md` (gate); instance bindings
in `recommend/README.md`. Read all three BEFORE acting. Follow SCOUT.md
for steps 1–5; this file only defines orchestration order and the seams.

1. **Setup**: read README.md bindings + the profile it names. History
   snapshot FIRST (one transaction, before ANY network I/O):
   `python3 recommend/history.py --db media.db snapshot --out <scratchpad>/snap.json`
2. **Scout**: run SCOUT.md §§1–5 in this session (interpret → history →
   sweep → narrow → dossiers). Keep the funnel log current as you go.
3. **Critic**: spawn a subagent (general-purpose) whose prompt contains
   ONLY: the text of CRITIC.md, the profile document, snap.json, and
   dossiers.json (attach file contents or paths). DO NOT include the
   funnel log, channel/query history, or any mention of search effort.
   If the critic requests a re-sweep (floor rule): do ONE differently-
   angled sweep pass, rebuild dossiers for new finalists, spawn a FRESH
   critic subagent. Max one re-sweep.
4. **Pitch** to the user: state your interpretation of the ask first;
   then each survivor — the case (profile-persuasive terms only), key
   evidence, predicted stars + confidence, residual risks; then
   wishlist-notes if any; then the honest survivor count if < 2.
   Category names and aggregate scores are never reasons.
5. **Log** (media.db write — run the README write ritual first): build
   one JSON batch of ALL candidates that reached the critic (survivors
   AND kills, with kill_rule/kill_evidence mapped to kill_reason), then
   `python3 recommend/reclog.py --db media.db log --json <scratchpad>/batch.json`
   Set `work_id` only for titles already in works (match via snap.json
   ids); leave null otherwise.
6. **Verdicts**: when the user reacts, record each with
   `python3 recommend/reclog.py --db media.db verdict --id N --verdict V --note "..."`.
   `interested` → offer (never auto-run) the wishlist add per README.
7. **Report**: end with counts (gathered / cut1 / cut2 / dossiers /
   survivors) + a machine-readable list of source skips/failures, and the
   funnel log path. If any profile entry was contradicted by a verdict,
   note it as a recalibration candidate (spec Part B lifecycle).

Digest mode (no ask given / scheduled): use DIGEST-INTENT.md as the ask;
everything else identical.
````

- [ ] **Step 3: Verify skill loads and paths resolve**

Run: `cd "media-hub" && ls .claude/skills/recommend/SKILL.md recommend/README.md recommend/SCOUT.md recommend/CRITIC.md recommend/DIGEST-INTENT.md recommend/reclog.py recommend/history.py && grep -c "recommend/" .claude/skills/recommend/SKILL.md`
Expected: all files listed, grep count ≥ 5. Then verify every relative path mentioned in README.md exists (`ls` each).

---

### Task 6: source-surface probe (spec C4 first task)

**Files:**
- Modify: `media-hub/recommend/SCOUT.md` (append dated findings to "Source notes")

**Interfaces:**
- Consumes: TMDB_API_KEY from `douban-export/sources/sources.env`.
- Produces: a filled "Source notes" section — the scout's guidance on which retrieval surfaces work.

- [ ] **Step 1: Probe TMDB keyword + discover surfaces**

Using three representative asks of different shapes — (a) "高智商犯罪剧 / smart crime TV", (b) "sophisticated-plot sci-fi film", (c) "comfort episodic comedy" — run for each:

```bash
source "douban-export/sources/sources.env"
# keyword resolution
curl -s "https://api.themoviedb.org/3/search/keyword?query=heist&api_key=$TMDB_API_KEY" | python3 -m json.tool | head -30
# discover by genre+keyword, vote-count floor
curl -s "https://api.themoviedb.org/3/discover/tv?with_genres=80&with_keywords=<id-from-above>&sort_by=vote_average.desc&vote_count.gte=200&api_key=$TMDB_API_KEY" | python3 -c "import json,sys; d=json.load(sys.stdin); print([ (r['name'], r.get('first_air_date','')[:4]) for r in d['results'][:15] ])"
# similar/recommendations for one known anchor id
curl -s "https://api.themoviedb.org/3/tv/1396/recommendations?api_key=$TMDB_API_KEY" | python3 -c "import json,sys; d=json.load(sys.stdin); print([r['name'] for r in d['results'][:15]])"
```
Record per surface: yield size, relevance (your judgment), junk rate.

- [ ] **Step 2: Probe Douban tag pages and NeoDB search (anonymous)**

```bash
curl -s -A "Mozilla/5.0" "https://movie.douban.com/tag/%E7%8A%AF%E7%BD%AA" | grep -o 'class="title"[^<]*' | head -5 ; echo "---"
curl -s "https://neodb.social/api/catalog/search?query=heist%20thriller&category=tv" | python3 -m json.tool | head -40
```
If Douban tag pages block anonymous fetch (empty/redirect), record that as a documented negative — check `douban-export/RUNBOOK.md` for the working fetch pattern (curl-cffi) and retry once with it.

- [ ] **Step 3: Probe review mining**

For one anchor title, fetch its Letterboxd reviews page and one Douban reviews page anonymously; judge whether review text (a) loads without auth, (b) names neighbor titles. Record which sites are viable at what depth.

- [ ] **Step 4: Append findings to SCOUT.md "Source notes"**

Format:
```markdown
### 2026-08-XX probe
- TMDB discover (genre+keyword, vote_count.gte=200): <verdict, junk rate>
- TMDB similar vs recommendations: <which is better, evidence>
- Douban tag pages (anonymous): <works / blocked — pattern to use>
- NeoDB search: <verdict>
- Review mining: Letterboxd <verdict>; Douban <verdict>; RT <verdict>
- Recommended default channel mix: <one line>
```
Also report the machine-readable skip list for any surface that failed.

---

### Task 7: calibration session #1 (USER-GATED)

**Files:**
- Create: `media-hub/recommend/logs/<date>-<slug>.md` (produced by the run)
- Modify: `media-hub/STATE.md` (session close-out)

**Interfaces:** Consumes the entire system. This task is the acceptance test — spec §A8: the user audits the reasoning, not just the picks.

- [ ] **Step 1: Get a real ask from the user** — do not invent one. Ask: "Give me a real ask for the first calibration run — anything, in your words."
- [ ] **Step 2: Run the `/recommend` skill end-to-end** exactly as written (no shortcuts; the funnel log must be complete).
- [ ] **Step 3: Deliver the pitch + the audit bundle** — pitch per SKILL.md step 4, plus links to: the funnel log, dossiers.json, the critic's JSON, and the reclog row ids.
- [ ] **Step 4: Record verdicts** via `reclog.py verdict` as they arrive; run `reclog.py --db media.db stats` and report it.
- [ ] **Step 5: Close out** — update STATE.md (dated section: first calibration run, counts, backup file created, any recalibration candidates surfaced). Report the session with counts + skip list.

---

## Deferred (tracked in spec C4, not tasks here)

- TASTE.md explicit case-law restructuring (diff shown to the user first).
- Digest scheduling (a scheduled task invoking the skill with no ask) — trivial once calibration sessions pass; set up when the user asks.
- Games/music/books lanes; multi-user productization.
