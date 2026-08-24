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
        created_at TEXT DEFAULT '', updated_at TEXT DEFAULT '',
        season_number INTEGER, meta TEXT DEFAULT '');
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
    con.execute("INSERT INTO works (id,kind,title,year,created_at,updated_at) "
               "VALUES (42,'tv','Neighbor Show',2021,'','')")
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

def test_suppress_sync_watched_via_sibling_season(tmp_path):
    """Season/parent asymmetry fix: a pool candidate representing a
    whole show (a platform's own unit — never a season) must be
    suppressed when the user has watched ANY season of it, even though
    the season's own external_ids never carry the show-level id (the
    season-tt gotcha — that id lives only in the season's `meta`).
    Covers both the id-match path (stronger evidence) and the base-title
    fallback for a candidate that carries no id at all."""
    db = mkdb(tmp_path)
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO works (id,kind,title,year,created_at,updated_at,"
        "season_number,meta) VALUES (43,'tv','神探夏洛克 第一季',2010,'','',"
        "1,'{\"show_tmdb_id\":\"19885\",\"show_imdb_id\":\"tt1475582\"}')")
    con.execute("INSERT INTO records (work_id,source,status,rating) "
               "VALUES (43,'douban','watched',10.0)")
    con.commit(); con.close()

    by_id = dict(ROW, title="神探夏洛克", kind="tv", year=2014,
                external_ids={"tmdb_tv": "19885"})
    by_title = dict(ROW, title="神探夏洛克", kind="tv", year=2010,
                    external_ids={})
    _upsert(db, [by_id], tmp_path, "s1.json")
    _upsert(db, [by_title], tmp_path, "s2.json")

    out = json.loads(run(db, "suppress-sync").stdout)
    assert out["watched"] == 2
    remaining = {r["title"] for r in json.loads(run(db, "query").stdout)}
    assert "神探夏洛克" not in remaining
    suppressed = json.loads(run(db, "query", "--include-suppressed").stdout)
    reasons = {r["year"]: r["suppressed_reason"] for r in suppressed
              if r["title"] == "神探夏洛克"}
    assert reasons == {2014: "watched", 2010: "watched"}

def test_suppress_sync_does_not_collapse_same_title_different_years(tmp_path):
    """No real season family exists for this title at all — the
    base-title fallback must never fire, so an unrelated, genuinely
    unwatched candidate sharing a title is NOT suppressed."""
    db = mkdb(tmp_path)
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO works (id,kind,title,year,created_at,updated_at) "
        "VALUES (44,'film','画皮',1966,'','')")
    con.execute("INSERT INTO records (work_id,source,status,rating) "
               "VALUES (44,'douban','watched',8.0)")
    con.commit(); con.close()
    unrelated = dict(ROW, title="画皮", kind="film", year=2008, external_ids={})
    _upsert(db, [unrelated], tmp_path, "s3.json")
    out = json.loads(run(db, "suppress-sync").stdout)
    assert out["watched"] == 0
    remaining = {r["title"] for r in json.loads(run(db, "query").stdout)}
    assert "画皮" in remaining

def test_stats(tmp_path):
    db = mkdb(tmp_path)
    _upsert(db, [ROW], tmp_path)
    s = json.loads(run(db,"stats").stdout)
    assert s["total"] == 1 and s["by_kind"]["tv"] == 1
    assert s["evidence_cached"] == 0 and s["by_channel"]["tmdb_rec"] == 1
