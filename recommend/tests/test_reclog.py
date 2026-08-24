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
    # (fix round 2, 2026-08-23: --title without --year now fails loudly —
    # see test_check_title_without_year_exits_nonzero — so an id-based
    # check omits --title entirely rather than passing a throwaway value.)
    chk = json.loads(run(db, "check", "--ext", "tmdb:123").stdout)
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

# --- Fix round 2 (2026-08-23) ---

def test_check_title_without_year_exits_nonzero(tmp_path):
    db = make_db(tmp_path)
    out = run(db, "check", "--title", "Test Show")
    assert out.returncode != 0
    assert "year" in out.stderr.lower()
    # id-based check still works fine without a title
    f = tmp_path / "b.json"; f.write_text(json.dumps(SAMPLE))
    run(db, "log", "--json", str(f))
    ext_only = run(db, "check", "--ext", "tmdb:123")
    assert ext_only.returncode == 0
    assert len(json.loads(ext_only.stdout)["prior"]) == 1

def test_stats_sealed_vs_actual_one_entry_per_recommendation(tmp_path):
    """Finding 1: sealed_vs_actual must not double-count a work rated via
    multiple sources. Under the pre-fix JOIN-to-records query this work
    (douban 8.0 + letterboxd 6.0) would have produced TWO sealed rows;
    this asserts exactly one, with the actual rating resolved by the same
    manual>douban>letterboxd>plex precedence as history.py's `rated`."""
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    ts = "2026-01-01T00:00:00"
    con.execute("INSERT INTO works VALUES (42,'film','Dual Source Film',2020,?,?)",
                (ts, ts))
    con.executemany("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)", [
        (1, 42, "douban",     "watched", 8.0, "2026-01-05", "", "", ts),
        (2, 42, "letterboxd", "watched", 6.0, "2026-01-03", "", "", ts),
    ])
    con.commit(); con.close()

    batch = [dict(SAMPLE[0], title="Dual Source Film", work_id=42,
                  predicted_stars=4.0, external_ids={"tmdb": "777"})]
    f = tmp_path / "b.json"; f.write_text(json.dumps(batch))
    out = run(db, "log", "--json", str(f))
    assert out.returncode == 0
    rid = json.loads(out.stdout)[0]
    assert run(db, "verdict", "--id", str(rid), "--verdict", "watched").returncode == 0

    stats = json.loads(run(db, "stats").stdout)
    assert stats["pitched"] == 1
    assert stats["hits"] == 1
    assert stats["hit_rate"] == 1.0        # each recommendation counted once
    sealed = stats["sealed_vs_actual"]
    assert len(sealed) == 1                # NOT 2 — one row per recommendation, not per source
    assert sealed[0]["actual_stars"] == 4.0  # douban (8.0/2) outranks letterboxd (6.0/2)

def test_log_batch_missing_field_rejects_whole_batch(tmp_path):
    """Finding 4: a bad row must fail loudly (row index + missing field(s)
    named) and insert NOTHING — not crash with a bare KeyError partway
    through, and not leave earlier rows committed."""
    db = make_db(tmp_path)
    batch = [
        dict(SAMPLE[0], title="Good One", external_ids={"tmdb": "1"}),
        dict(SAMPLE[0], title="Dark Matter", external_ids={"tmdb": "2"}),
        dict(SAMPLE[0], title="Also Good", external_ids={"tmdb": "3"}),
    ]
    del batch[1]["intention"]
    f = tmp_path / "bad.json"; f.write_text(json.dumps(batch))
    out = run(db, "log", "--json", str(f))
    assert out.returncode != 0
    assert "row 1" in out.stderr
    assert "Dark Matter" in out.stderr
    assert "intention" in out.stderr
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM recommendations").fetchone()[0] == 0

def test_log_batch_multiple_bad_rows_all_named_at_once(tmp_path):
    """Finding 4: every bad row is reported in the SAME failure, not just
    the first one — a caller shouldn't have to fix problems one traceback
    at a time."""
    db = make_db(tmp_path)
    batch = [dict(SAMPLE[0], title="Row Zero"), dict(SAMPLE[0], title="Row One")]
    del batch[0]["kind"]
    del batch[1]["intention"]
    f = tmp_path / "bad2.json"; f.write_text(json.dumps(batch))
    out = run(db, "log", "--json", str(f))
    assert out.returncode != 0
    assert "row 0" in out.stderr and "kind" in out.stderr
    assert "row 1" in out.stderr and "intention" in out.stderr
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM recommendations").fetchone()[0] == 0

# --- Final fix wave (2026-08-23) ---

def test_predicted_stars_out_of_star_range_rejected(tmp_path):
    """I7: `records.rating` is 0-10 and `predicted_stars` is 0.5-5.0.
    A 0-10 value smuggled in here used to insert silently and then be
    compared against rating/2.0 by `stats`, producing a nonsense accuracy
    metric with no error anywhere."""
    db = make_db(tmp_path)
    batch = [dict(SAMPLE[0], title="Ten Scale", predicted_stars=9.0)]
    f = tmp_path / "b.json"; f.write_text(json.dumps(batch))
    out = run(db, "log", "--json", str(f))
    assert out.returncode != 0
    assert "predicted_stars" in out.stderr and "0.5" in out.stderr
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM recommendations").fetchone()[0] == 0

def test_predicted_stars_zero_and_null_and_bounds(tmp_path):
    db = make_db(tmp_path)
    # null is allowed (a killed candidate may carry no prediction)
    ok = [dict(SAMPLE[0], title="No Prediction", predicted_stars=None,
               external_ids={"tmdb": "10"}),
          dict(SAMPLE[0], title="Floor", predicted_stars=0.5,
               external_ids={"tmdb": "11"}),
          dict(SAMPLE[0], title="Ceiling", predicted_stars=5.0,
               external_ids={"tmdb": "12"})]
    f = tmp_path / "ok.json"; f.write_text(json.dumps(ok))
    assert run(db, "log", "--json", str(f)).returncode == 0
    # 0.0 is below the floor of the star scale and must be rejected
    bad = [dict(SAMPLE[0], title="Zero", predicted_stars=0.0)]
    f2 = tmp_path / "bad.json"; f2.write_text(json.dumps(bad))
    assert run(db, "log", "--json", str(f2)).returncode != 0

def test_ddl_check_constraint_on_new_databases(tmp_path):
    """The CHECK exists for databases this DDL actually creates. The live
    media.db table predates it and is deliberately NOT rebuilt, so the
    validator is what protects that one."""
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name='recommendations'"
                      ).fetchone()[0]
    assert "CHECK" in sql and "predicted_stars" in sql
    try:
        con.execute("INSERT INTO recommendations (session_date,intention,kind,"
                    "title,predicted_stars,created_at,updated_at) "
                    "VALUES ('d','i','tv','T',9.0,'c','u')")
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised

def test_log_batch_non_dict_row_fails_validator_not_traceback(tmp_path):
    db = make_db(tmp_path)
    batch = [dict(SAMPLE[0], title="Fine"), "just a string", 42]
    f = tmp_path / "b.json"; f.write_text(json.dumps(batch))
    out = run(db, "log", "--json", str(f))
    assert out.returncode != 0
    assert "row 1" in out.stderr and "row 2" in out.stderr
    assert "JSON object" in out.stderr
    assert "Traceback" not in out.stderr
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM recommendations").fetchone()[0] == 0

def test_log_batch_null_critic_killed_defaults_to_zero(tmp_path):
    """`int(None)` used to raise a bare TypeError mid-insert."""
    db = make_db(tmp_path)
    batch = [dict(SAMPLE[0], title="Null Killed", critic_killed=None)]
    f = tmp_path / "b.json"; f.write_text(json.dumps(batch))
    out = run(db, "log", "--json", str(f))
    assert out.returncode == 0, out.stderr
    con = sqlite3.connect(db)
    assert con.execute("SELECT critic_killed FROM recommendations").fetchone()[0] == 0

def test_log_batch_non_numeric_critic_killed_rejected(tmp_path):
    db = make_db(tmp_path)
    batch = [dict(SAMPLE[0], title="Bad Killed", critic_killed="maybe")]
    f = tmp_path / "b.json"; f.write_text(json.dumps(batch))
    out = run(db, "log", "--json", str(f))
    assert out.returncode != 0
    assert "critic_killed" in out.stderr

def test_log_rollback_holds_when_the_insert_itself_fails(tmp_path):
    """The rollback must still hold for a failure the validator does NOT
    catch: row 0 is perfectly valid and row 1 passes validation but has an
    unbindable `predicted_confidence` (an object where sqlite3 needs a
    scalar), so it fails inside the INSERT loop after row 0 was already
    executed. Zero rows may survive."""
    db = make_db(tmp_path)
    bad = [dict(SAMPLE[0], title="Row A", external_ids={"tmdb": "1"}),
           dict(SAMPLE[0], title="Row B", predicted_confidence={"not": "a scalar"})]
    f = tmp_path / "b.json"; f.write_text(json.dumps(bad))
    out = run(db, "log", "--json", str(f))
    assert out.returncode != 0
    # this one IS a traceback by design — it is not a contract violation
    # the validator can anticipate, only a guarantee about atomicity.
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM recommendations").fetchone()[0] == 0

def test_stats_with_nothing_pitched(tmp_path):
    db = make_db(tmp_path)
    stats = json.loads(run(db, "stats").stdout)
    assert stats == {"pitched": 0, "hits": 0, "hit_rate": None,
                     "sealed_vs_actual": []}

def test_stats_hit_rate_ignores_killed_rows(tmp_path):
    db = make_db(tmp_path)
    batch = [dict(SAMPLE[0], title="Pitched One", external_ids={"tmdb": "1"}),
             dict(SAMPLE[0], title="Killed One", critic_killed=1,
                  kill_reason="predicted: below threshold",
                  external_ids={"tmdb": "2"})]
    f = tmp_path / "b.json"; f.write_text(json.dumps(batch))
    ids = json.loads(run(db, "log", "--json", str(f)).stdout)
    assert len(ids) == 2
    stats = json.loads(run(db, "stats").stdout)
    assert stats["pitched"] == 1 and stats["hits"] == 0
    assert stats["hit_rate"] == 0.0
    run(db, "verdict", "--id", str(ids[0]), "--verdict", "interested")
    assert json.loads(run(db, "stats").stdout)["hit_rate"] == 1.0

def test_log_prints_inserted_ids_in_batch_order(tmp_path):
    """SKILL.md step 6 tells the orchestrator to take the --id values for
    `verdict` from this output, positionally."""
    db = make_db(tmp_path)
    batch = [dict(SAMPLE[0], title="First",  external_ids={"tmdb": "1"}),
             dict(SAMPLE[0], title="Second", external_ids={"tmdb": "2"}),
             dict(SAMPLE[0], title="Third",  external_ids={"tmdb": "3"})]
    f = tmp_path / "b.json"; f.write_text(json.dumps(batch))
    ids = json.loads(run(db, "log", "--json", str(f)).stdout)
    con = sqlite3.connect(db)
    titles = [con.execute("SELECT title FROM recommendations WHERE id=?",
                          (i,)).fetchone()[0] for i in ids]
    assert titles == ["First", "Second", "Third"]
