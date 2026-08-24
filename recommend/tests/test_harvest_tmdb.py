import json, sqlite3, subprocess, sys
from pathlib import Path

H = str(Path(__file__).resolve().parents[1] / "harvest_tmdb.py")

REC = {"results": [
    {"id": 100, "name": "Good Show", "original_name": "Good Show",
     "first_air_date": "2021-03-01", "genre_ids": [35],
     "vote_average": 8.0, "vote_count": 500},
    {"id": 101, "name": "Junk", "first_air_date": "2020-01-01",
     "genre_ids": [35], "vote_average": 9.9, "vote_count": 3}]}
GENRES_TV = {"genres": [{"id": 35, "name": "Comedy"}]}

MOVIE_REC = {"results": [
    {"id": 603, "title": "The Matrix", "original_title": "The Matrix",
     "release_date": "1999-03-31", "genre_ids": [28],
     "vote_average": 8.7, "vote_count": 22000}]}
GENRES_MOVIE = {"genres": [{"id": 28, "name": "Action"}]}


def _run(*a):
    return subprocess.run([sys.executable, H, *a], capture_output=True, text=True)


# --------------------------------------------------------------- transform

def test_transform(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()
    (raw / "rec_tv_42_p1.json").write_text(json.dumps(
        dict(REC, _meta={"channel": "tmdb_rec", "anchor_work_id": 42,
                          "media": "tv", "fetched": "2026-08-23"})))
    (raw / "genres_tv.json").write_text(json.dumps(GENRES_TV))
    out = tmp_path / "batch.json"
    r = _run("transform", "--raw-dir", str(raw), "--out", str(out))
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
    # dropped count reported on stdout
    report = json.loads(r.stdout)
    assert report["dropped_vote_floor"] == 1
    assert report["candidates"] == 1


def test_transform_movie_shaped_results(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()
    (raw / "rec_movie_9_p1.json").write_text(json.dumps(
        dict(MOVIE_REC, _meta={"channel": "tmdb_rec", "anchor_work_id": 9,
                                "media": "movie", "fetched": "2026-08-23"})))
    (raw / "genres_movie.json").write_text(json.dumps(GENRES_MOVIE))
    out = tmp_path / "batch_movie.json"
    r = _run("transform", "--raw-dir", str(raw), "--out", str(out))
    assert r.returncode == 0, r.stderr
    batch = json.loads(out.read_text())
    assert len(batch) == 1
    c = batch[0]
    assert c["kind"] == "film" and c["year"] == 1999
    assert c["title"] == "The Matrix"
    assert c["external_ids"] == {"tmdb_movie": "603"}
    assert c["tags"] == ["Action"]
    assert c["sources"][0] == {"channel": "tmdb_rec", "anchor_work_id": 9,
                               "fetched": "2026-08-23"}


def test_transform_skips_file_without_meta(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()
    # No _meta block at all -- must be skipped with a warning, not crash.
    (raw / "rec_tv_1_p1.json").write_text(json.dumps(REC))
    (raw / "genres_tv.json").write_text(json.dumps(GENRES_TV))
    out = tmp_path / "batch3.json"
    r = _run("transform", "--raw-dir", str(raw), "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text()) == []
    assert "_meta" in r.stderr
    report = json.loads(r.stdout)
    assert report["skipped_files"] == ["rec_tv_1_p1.json"]


def test_transform_empty_raw_dir(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()
    out = tmp_path / "batch_empty.json"
    r = _run("transform", "--raw-dir", str(raw), "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text()) == []


# ------------------------------------------------------------------ anchors

def _mkdb(tmp_path, name="t.db"):
    db = tmp_path / name
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE works (id INTEGER PRIMARY KEY, kind TEXT, title TEXT,
        original_title TEXT DEFAULT '', year INTEGER,
        created_at TEXT DEFAULT '', updated_at TEXT DEFAULT '');
      CREATE TABLE records (id INTEGER PRIMARY KEY, work_id INTEGER, source TEXT,
        status TEXT, rating REAL, marked_at TEXT DEFAULT '', review TEXT DEFAULT '',
        raw TEXT DEFAULT '', updated_at TEXT DEFAULT '');
      CREATE TABLE external_ids (work_id INTEGER, namespace TEXT, value TEXT);
    """)
    con.commit(); con.close()
    return db


def test_anchors_movie_shaped(tmp_path):
    db = _mkdb(tmp_path)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO works VALUES (1,'film','Great Film','',2019,'','')")
    con.execute("INSERT INTO records (work_id,source,status,rating) "
                "VALUES (1,'douban','watched',9.5)")
    con.execute("INSERT INTO external_ids VALUES (1,'tmdb_movie','603')")
    con.commit(); con.close()

    r = _run("anchors", "--db", str(db))
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert rows == [{"work_id": 1, "kind": "film", "tmdb_id": 603,
                     "media": "movie", "title": "Great Film"}]


def test_anchors_filters_rating_and_missing_id(tmp_path):
    db = _mkdb(tmp_path)
    con = sqlite3.connect(db)
    con.executemany("INSERT INTO works VALUES (?,?,?,?,?,?,?)", [
        (1, "tv", "High Rated With Id", "", 2021, "", ""),
        (2, "tv", "High Rated No Id", "", 2020, "", ""),
        (3, "film", "Low Rated With Id", "", 2018, "", ""),
    ])
    con.executemany(
        "INSERT INTO records (work_id,source,status,rating) VALUES (?,?,?,?)", [
            (1, "douban", "watched", 9.0),
            (2, "douban", "watching", 10.0),
            (3, "douban", "watched", 8.0),   # below default min-rating 9
        ])
    con.execute("INSERT INTO external_ids VALUES (1,'tmdb_tv','777')")
    con.execute("INSERT INTO external_ids VALUES (3,'tmdb_movie','1')")
    con.commit(); con.close()

    rows = json.loads(_run("anchors", "--db", str(db)).stdout)
    assert rows == [{"work_id": 1, "kind": "tv", "tmdb_id": 777,
                     "media": "tv", "title": "High Rated With Id"}]

    rows_lenient = json.loads(
        _run("anchors", "--db", str(db), "--min-rating", "8").stdout)
    ids = {r["work_id"] for r in rows_lenient}
    assert ids == {1, 3}   # work 2 still excluded: no tmdb id at all
