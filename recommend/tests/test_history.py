import json, sqlite3, subprocess, sys
from pathlib import Path

HISTORY = str(Path(__file__).resolve().parents[1] / "history.py")
RECLOG  = str(Path(__file__).resolve().parents[1] / "reclog.py")

# distribution/cell/percentile_of operate purely on the parsed snapshot
# dict, so they're exercised by direct import against hand-built fixtures
# rather than through the DB+subprocess path the rest of this file uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import history

# Columns named explicitly: the fixture `works` table now carries a
# `creators` column (real media.db has one, and `lookup --creator` reads
# it), so positional VALUES tuples would have to grow every time the
# fixture tracks another real column.
WORKS_INSERT = ("INSERT INTO works "
                "(id,kind,title,original_title,year,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?)")

def make_db(tmp_path):
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE works (id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
        title TEXT NOT NULL, original_title TEXT DEFAULT '', year INTEGER,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        creators TEXT DEFAULT '', season_number INTEGER, meta TEXT DEFAULT '');
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
    con.executemany(WORKS_INSERT, w)
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

def _setup(tmp_path, works, records, ext_ids=()):
    """Build a scratch DB from explicit works/records rows (fix round 1,
    2026-08-23 regression tests: rated dedup + shells with zero records)."""
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE works (id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
        title TEXT NOT NULL, original_title TEXT DEFAULT '', year INTEGER,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        creators TEXT DEFAULT '', season_number INTEGER, meta TEXT DEFAULT '');
      CREATE TABLE records (id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL,
        source TEXT NOT NULL, status TEXT NOT NULL, rating REAL,
        marked_at TEXT DEFAULT '', review TEXT DEFAULT '', raw TEXT DEFAULT '',
        updated_at TEXT NOT NULL);
      CREATE TABLE external_ids (work_id INTEGER NOT NULL,
        namespace TEXT NOT NULL, value TEXT NOT NULL);
    """)
    con.executemany(WORKS_INSERT, works)
    if records:
        con.executemany("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)", records)
    for row in ext_ids:
        con.execute("INSERT INTO external_ids VALUES (?,?,?)", row)
    con.commit(); con.close()
    subprocess.run([sys.executable, RECLOG, "--db", str(db), "init"], check=True)
    return db

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
        "intention":"x","external_ids":{"tmdb":"5"},
        "dossier":{"scout":{"enrichment":{
            "summary":"A concrete summary.", "special":"A concrete distinction.",
            "personal_hook":"A concrete personal hook.",
            "entry":{}, "inside":{"moments":[], "quotes":[]}}},
            "critic":{"pitch_selected":True}}}]))
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

# --- Fix round 1 (2026-08-23): rated dedup by work_id + shells with zero
# records rows. See STATE.md / task-A-report.md for the confirmed defects. ---

def test_rated_dedupes_conflicting_ratings(tmp_path):
    ts = "2026-01-01T00:00:00"
    works = [(1, "film", "Dual Rating Film", "", 2020, ts, ts)]
    records = [
        (1, 1, "douban",     "watched", 8.0, "2026-01-05", "douban review", "", ts),
        (2, 1, "letterboxd", "watched", 7.0, "2026-01-03", "",              "", ts),
    ]
    db = _setup(tmp_path, works, records)
    s = snap(db)
    assert s["counts"]["rated"] == 1
    assert len(s["rated"]) == 1
    entry = s["rated"][0]
    assert entry["stars"] == 4.0                       # douban outranks letterboxd
    assert entry["source"] == "douban"
    assert entry["sources"] == ["douban", "letterboxd"]
    assert entry["rating_variants"] == {"douban": 4.0, "letterboxd": 3.5}

def test_rated_agreeing_ratings_no_variants(tmp_path):
    ts = "2026-01-01T00:00:00"
    works = [(1, "film", "Agree Film", "", 2020, ts, ts)]
    records = [
        (1, 1, "douban", "watched", 8.0, "2026-01-05", "", "", ts),
        (2, 1, "plex",   "watched", 8.0, "2026-01-01", "", "", ts),
    ]
    db = _setup(tmp_path, works, records)
    s = snap(db)
    assert len(s["rated"]) == 1
    entry = s["rated"][0]
    assert entry["stars"] == 4.0
    assert entry["sources"] == ["douban", "plex"]
    assert "rating_variants" not in entry

def test_rated_precedence_splits_stars_and_review(tmp_path):
    ts = "2026-01-01T00:00:00"
    works = [(1, "film", "Split Source Film", "", 2020, ts, ts)]
    records = [
        # douban carries the rating; manual (higher precedence) carries no
        # rating but does carry the review — stars must still fall back to
        # douban since manual has none, while review must prefer manual.
        (1, 1, "douban", "watched", 9.0,  "2026-01-02", "douban text",         "", ts),
        (2, 1, "manual", "watched", None, "2026-01-04", "manual review text",  "", ts),
    ]
    db = _setup(tmp_path, works, records)
    s = snap(db)
    entry = s["rated"][0]
    assert entry["stars"] == 4.5                 # only douban has a rating
    assert entry["source"] == "douban"            # source that supplied the stars
    assert entry["review"] == "manual review text"  # manual outranks douban for review
    assert "rating_variants" not in entry          # only one source has a rating at all

def test_shells_includes_works_with_zero_records(tmp_path):
    ts = "2026-01-01T00:00:00"
    works = [(1, "tv", "No Records Show", "", 2024, ts, ts)]
    db = _setup(tmp_path, works, records=[])
    s = snap(db)
    assert [w["title"] for w in s["shells"]] == ["No Records Show"]

def test_counts_rated_counts_distinct_works_not_rows(tmp_path):
    ts = "2026-01-01T00:00:00"
    works = [(1, "film", "Film A", "", 2020, ts, ts),
             (2, "film", "Film B", "", 2021, ts, ts)]
    records = [
        (1, 1, "douban",     "watched", 8.0, "2026-01-01", "", "", ts),
        (2, 1, "letterboxd", "watched", 8.0, "2026-01-02", "", "", ts),
        (3, 2, "douban",     "watched", 6.0, "2026-01-01", "", "", ts),
    ]
    db = _setup(tmp_path, works, records)
    s = snap(db)
    assert s["counts"]["rated"] == 2       # 3 records, 2 distinct works
    assert len(s["rated"]) == 2

# --- Final fix wave (2026-08-23): C1 index/lookup, same-source tie, kinds ---

def index_text(db=None, snapshot=None, *extra):
    args = [sys.executable, HISTORY]
    if db:
        args += ["--db", str(db)]
    args += ["index", *extra]
    if snapshot:
        args += ["--snapshot", str(snapshot)]
    out = subprocess.run(args, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout

def lookup_json(snapshot, *extra):
    out = subprocess.run([sys.executable, HISTORY, "lookup",
                          "--snapshot", str(snapshot), *extra],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)

def _index_db(tmp_path):
    ts = "2026-01-01T00:00:00"
    works = [(1, "film", "Reviewed Film", "Le Film", 2020, ts, ts),
             (2, "tv",   "Bare Show",     "",        2021, ts, ts),
             (3, "film", "Unrated Film",  "",        2019, ts, ts),
             (4, "film", "Wished Film",   "",        2022, ts, ts)]
    records = [
        (1, 1, "douban", "watched", 9.0, "2026-01-05", "a real review", "", ts),
        (2, 2, "douban", "watched", 6.0, "2026-01-04", "",              "", ts),
        (3, 3, "douban", "watched", None, "2026-01-03", "",             "", ts),
        (4, 4, "douban", "wishlist", None, "",          "",             "", ts),
    ]
    db = _setup(tmp_path, works, records)
    con = sqlite3.connect(db)
    con.execute("UPDATE works SET creators='Agnes Varda' WHERE id=1")
    con.commit(); con.close()
    return db

def _entry_lines(text):
    return [l for l in text.splitlines() if l and not l.startswith("#")]

def test_index_line_count_matches_rated_count(tmp_path):
    db = _index_db(tmp_path)
    s = snap(db)
    text = index_text(db)
    lines = _entry_lines(text)
    assert len(lines) == s["counts"]["rated"] == 3
    # the END marker is the anti-silent-truncation guard: it names the
    # same count and must be the last line of the file.
    assert text.rstrip().splitlines()[-1] == "# END OF INDEX — 3 entries listed above."

def test_index_marks_review_presence_and_stars(tmp_path):
    db = _index_db(tmp_path)
    lines = _entry_lines(index_text(db))
    reviewed = [l for l in lines if "Reviewed Film" in l][0]
    bare     = [l for l in lines if "Bare Show" in l][0]
    unrated  = [l for l in lines if "Unrated Film" in l][0]
    assert reviewed.split()[2] == "R"      # has review text
    assert bare.split()[2] == "."          # no review text
    assert reviewed.split()[1] == "4.5"
    assert unrated.split()[1] == "-"       # watched but never rated
    assert "<< Le Film" in reviewed        # original_title shown when it differs
    assert "<<" not in bare                # and omitted when it does not

def test_index_and_lookup_work_from_a_snapshot_file_alone(tmp_path):
    db = _index_db(tmp_path)
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(db), "snapshot",
                    "--out", str(dest)], check=True)
    from_db   = _entry_lines(index_text(db))
    from_file = _entry_lines(index_text(None, dest))
    assert from_db == from_file
    # no --db anywhere in the lookup call either
    res = lookup_json(dest, "--work-id", "1")
    assert res["count"] == 1
    assert res["results"][0]["title"] == "Reviewed Film"

def test_lookup_by_work_id_returns_full_review_text(tmp_path):
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_index_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    res = lookup_json(dest, "--work-id", "1")
    hit = res["results"][0]
    assert hit["review"] == "a real review"
    assert hit["stars"] == 4.5
    assert hit["section"] == "rated"

def test_lookup_by_title_is_case_insensitive_substring(tmp_path):
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_index_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    res = lookup_json(dest, "--title", "reVIEWed fi")
    assert [r["title"] for r in res["results"]] == ["Reviewed Film"]
    # substring across sections: a wishlist title is findable too, and is
    # labelled with the section it came from (this is how dedup works).
    res = lookup_json(dest, "--title", "film")
    assert {r["section"] for r in res["results"]} == {"rated", "wishlist"}

def test_lookup_by_creator(tmp_path):
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_index_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    res = lookup_json(dest, "--creator", "varda")
    assert [r["title"] for r in res["results"]] == ["Reviewed Film"]

def test_lookup_requires_a_filter(tmp_path):
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_index_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    out = subprocess.run([sys.executable, HISTORY, "lookup",
                          "--snapshot", str(dest)],
                         capture_output=True, text=True)
    assert out.returncode != 0
    assert "work-id" in out.stderr

def test_rated_same_source_watched_beats_watching(tmp_path):
    """Correction to an earlier ruling: UNIQUE(source, work_id, status)
    lets ONE source hold both a watched and a watching row for the same
    work, and _rated_entries gathers both — so the tie is reachable and
    must not resolve by cursor order. watched wins over watching."""
    ts = "2026-01-01T00:00:00"
    works = [(1, "tv", "Two Status Show", "", 2020, ts, ts)]
    records = [
        # the `watching` row is deliberately the NEWER of the two and is
        # inserted first, so neither insertion order nor recency alone
        # could produce the right answer by accident.
        (1, 1, "douban", "watching", 6.0, "2026-02-01", "midway note", "", ts),
        (2, 1, "douban", "watched",  9.0, "2026-01-01", "final note",  "", ts),
    ]
    db = _setup(tmp_path, works, records)
    entry = snap(db)["rated"][0]
    assert entry["stars"] == 4.5           # watched (9.0/2), not watching (6.0/2)
    assert entry["review"] == "final note"
    # and the same-source second rating is no longer hidden by setdefault:
    # one source, one resolved rating, so no spurious variants either.
    assert "rating_variants" not in entry

def test_rating_variants_uses_resolved_rating_per_source(tmp_path):
    """The per-source rating must itself be precedence-resolved, not the
    first row the cursor happened to yield."""
    ts = "2026-01-01T00:00:00"
    works = [(1, "tv", "Cross Source Show", "", 2020, ts, ts)]
    records = [
        (1, 1, "douban",     "watching", 4.0, "2026-02-01", "", "", ts),
        (2, 1, "douban",     "watched",  9.0, "2026-01-01", "", "", ts),
        (3, 1, "letterboxd", "watched",  6.0, "2026-01-02", "", "", ts),
    ]
    db = _setup(tmp_path, works, records)
    entry = snap(db)["rated"][0]
    assert entry["rating_variants"] == {"douban": 4.5, "letterboxd": 3.0}

def test_snapshot_kinds_flag_narrows_scope(tmp_path):
    ts = "2026-01-01T00:00:00"
    works = [(1, "film", "A Film", "", 2020, ts, ts),
             (2, "tv",   "A Show", "", 2021, ts, ts)]
    records = [(1, 1, "douban", "watched", 8.0, "2026-01-01", "", "", ts),
               (2, 2, "douban", "watched", 8.0, "2026-01-02", "", "", ts)]
    db = _setup(tmp_path, works, records)
    both = snap(db)
    assert both["counts"]["rated"] == 2
    only_film = snap(db, "--kinds", "film")
    assert [r["title"] for r in only_film["rated"]] == ["A Film"]
    assert only_film["kinds"] == ["film"]

def test_snapshot_without_db_fails_loudly(tmp_path):
    out = subprocess.run([sys.executable, HISTORY, "snapshot"],
                         capture_output=True, text=True)
    assert out.returncode != 0
    assert "--db" in out.stderr

def test_shells_carry_external_ids_when_the_db_has_them(tmp_path):
    """Coordinator ruling (2026-08-23): shells must carry the ids
    media.db already holds, rather than forcing a network re-resolve for
    the channel SCOUT.md §2 just promoted. Coverage is partial, so a
    shell with no ids at all must still come back — with an empty dict,
    not a missing key."""
    ts = "2026-01-01T00:00:00"
    works = [(1, "tv",   "Shell With Ids", "", 2024, ts, ts),
             (2, "film", "Shell No Ids",   "", 2023, ts, ts)]
    db = _setup(tmp_path, works, records=[],
                ext_ids=[(1, "imdb", "tt1234567"), (1, "plex_guid", "plex://x")])
    shells = {s["title"]: s for s in snap(db)["shells"]}
    assert set(shells) == {"Shell With Ids", "Shell No Ids"}
    assert shells["Shell With Ids"]["external_ids"] == {
        "imdb": "tt1234567", "plex_guid": "plex://x"}
    assert shells["Shell No Ids"]["external_ids"] == {}   # present, empty

def test_lookup_returns_shell_ids(tmp_path):
    """The ids have to survive into `lookup`, which is how the critic and
    the scout actually reach a shell's detail."""
    ts = "2026-01-01T00:00:00"
    works = [(1, "tv", "Shell With Ids", "", 2024, ts, ts)]
    db = _setup(tmp_path, works, records=[], ext_ids=[(1, "imdb", "tt1234567")])
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(db), "snapshot",
                    "--out", str(dest)], check=True)
    hit = lookup_json(dest, "--title", "shell with")["results"][0]
    assert hit["section"] == "shells"
    assert hit["external_ids"] == {"imdb": "tt1234567"}

# --- Season/parent asymmetry fix (2026-08-23) --------------------------
# TV is season-level canon (one `kind='tv'` row per season, plus a
# `kind='show'` parent row that never carries its own record — see the
# module docstring's "Season/parent asymmetry"). These pin the fix that
# stops a watched-season-by-season series from appearing as a shell.

def _set_season(db, work_id, season_number, meta=None):
    con = sqlite3.connect(db)
    con.execute("UPDATE works SET season_number=?, meta=? WHERE id=?",
               (season_number, json.dumps(meta) if meta else "", work_id))
    con.commit(); con.close()

def test_shells_excludes_parent_row_whose_season_is_watched_by_id(tmp_path):
    """Id-match path: the parent's OWN external_ids overlap the watched
    season's meta.show_tmdb_id/show_imdb_id — the strongest evidence,
    per this project's ids-over-title-similarity rule."""
    ts = "2026-01-01T00:00:00"
    works = [(1, "show", "神探夏洛克", "", 2014, ts, ts),
             (2, "tv",   "神探夏洛克 第一季", "", 2010, ts, ts)]
    records = [(1, 2, "douban", "watched", 9.0, "2026-01-01", "", "", ts)]
    db = _setup(tmp_path, works, records,
               ext_ids=[(1, "tmdb_tv", "19885"), (1, "imdb", "tt1475582")])
    _set_season(db, 2, 1, {"show_tmdb_id": "19885", "show_imdb_id": "tt1475582"})
    s = snap(db)
    assert "神探夏洛克" not in {sh["title"] for sh in s["shells"]}
    assert s["rated"][0]["title"] == "神探夏洛克 第一季"

def test_shells_excludes_parent_row_whose_season_is_watched_by_title(tmp_path):
    """Base-title fallback path: neither side carries a usable id (the
    common real case — many parent rows carry no external_ids of their
    own), so the match falls back to the stripped `第N季` base title,
    guarded by the real season family's year."""
    ts = "2026-01-01T00:00:00"
    works = [(1, "show", "早间新闻", "", 2021, ts, ts),
             (2, "tv",   "早间新闻 第一季", "", 2021, ts, ts)]
    records = [(1, 2, "douban", "watched", 8.0, "2026-01-01", "", "", ts)]
    db = _setup(tmp_path, works, records)   # no external_ids at all
    _set_season(db, 2, 1)                    # season row, no meta ids either
    s = snap(db)
    assert "早间新闻" not in {sh["title"] for sh in s["shells"]}

def test_shells_excludes_season_row_whose_sibling_season_is_watched(tmp_path):
    """A not-yet-watched SEASON must also be excluded when a sibling
    season of the same show has a watched/watching/wishlist record."""
    ts = "2026-01-01T00:00:00"
    works = [(1, "tv", "初来乍到 第一季", "", 2015, ts, ts),
             (2, "tv", "初来乍到 第二季", "", 2015, ts, ts)]
    records = [(1, 1, "douban", "watched", 10.0, "2026-01-01", "", "", ts)]
    db = _setup(tmp_path, works, records)
    _set_season(db, 1, 1)
    _set_season(db, 2, 2)                    # unwatched sibling
    s = snap(db)
    assert "初来乍到 第二季" not in {sh["title"] for sh in s["shells"]}
    assert s["rated"][0]["title"] == "初来乍到 第一季"

def test_shells_still_includes_a_genuinely_unwatched_work(tmp_path):
    """A real unrelated shell (e.g. an animated short — the genuine 160)
    must not be swept up by the fix."""
    ts = "2026-01-01T00:00:00"
    works = [(1, "show", "神探夏洛克", "", 2010, ts, ts),
             (2, "tv",   "神探夏洛克 第一季", "", 2010, ts, ts),
             (3, "film", "Balance", "", 1989, ts, ts)]
    records = [(1, 2, "douban", "watched", 9.0, "2026-01-01", "", "", ts)]
    db = _setup(tmp_path, works, records)
    _set_season(db, 2, 1)
    s = snap(db)
    assert {sh["title"] for sh in s["shells"]} == {"Balance"}

def sib_json(snapshot, *extra):
    out = subprocess.run([sys.executable, HISTORY, "sibling-seasons",
                          "--snapshot", str(snapshot), *extra],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)

def _sib_db(tmp_path):
    """DB for `sibling-seasons`: 神探夏洛克 (parent + watched S1, carries
    show-level ids), 初来乍到 (two seasons, only S1 watched, no ids at
    all — pure base-title fallback), Balance (a genuinely unrelated,
    never-seasoned standalone film), 画皮 1966/2008 (same-title-different-
    year pair, neither carries a season suffix or season family)."""
    ts = "2026-01-01T00:00:00"
    works = [(1, "show", "神探夏洛克",       "", 2010, ts, ts),
             (2, "tv",   "神探夏洛克 第一季", "", 2010, ts, ts),
             (3, "tv",   "初来乍到 第一季",   "", 2015, ts, ts),
             (4, "tv",   "初来乍到 第二季",   "", 2015, ts, ts),
             (5, "film", "Balance",          "", 1989, ts, ts),
             (6, "film", "画皮",             "", 1966, ts, ts),
             (7, "film", "画皮",             "", 2008, ts, ts)]
    records = [(1, 2, "douban", "watched", 9.0, "2026-02-01", "great", "", ts),
               (2, 3, "douban", "watched", 10.0, "2026-01-15", "", "", ts),
               (3, 6, "douban", "watched", 8.0, "2026-01-01", "", "", ts)]
    db = _setup(tmp_path, works, records,
               ext_ids=[(1, "tmdb_tv", "19885"), (1, "imdb", "tt1475582")])
    _set_season(db, 2, 1, {"show_tmdb_id": "19885", "show_imdb_id": "tt1475582"})
    _set_season(db, 3, 1)
    _set_season(db, 4, 2)
    return db

def test_sibling_seasons_parent_title_query_watched_returns_matching_seasons(tmp_path):
    """The exact scenario the fix targets: a candidate that looks like a
    fresh show (its own parent-level title) but a season is already
    rated must come back watched, with real evidence, not a bare bool."""
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_sib_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    res = sib_json(dest, "--title", "神探夏洛克")
    assert res["watched"] is True
    assert res["matched_by"] == "base_title"
    assert res["base_title"] == "神探夏洛克"
    assert [w["title"] for w in res["matching_works"]] == ["神探夏洛克 第一季"]
    hit = res["matching_works"][0]
    assert hit["season_number"] == 1
    assert hit["stars"] == 4.5
    assert hit["marked_at"] == "2026-02-01"
    assert hit["status"] == "watched"

def test_sibling_seasons_base_title_fallback_no_ids_at_all(tmp_path):
    """A not-yet-watched season, checked by title alone (no ids on
    either side), still finds its watched sibling."""
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_sib_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    res = sib_json(dest, "--title", "初来乍到 第二季", "--year", "2015")
    assert res["watched"] is True
    assert res["matched_by"] == "base_title"
    assert res["base_title"] == "初来乍到"
    assert [w["season_number"] for w in res["matching_works"]] == [1]

def test_sibling_seasons_genuinely_unwatched_title_returns_false(tmp_path):
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_sib_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    res = sib_json(dest, "--title", "Balance", "--year", "1989")
    assert res["watched"] is False
    assert res["matched_by"] is None
    assert res["matching_works"] == []

def test_sibling_seasons_id_match_wins_when_title_differs(tmp_path):
    """Direct proof id evidence outranks title text: an English title
    that shares NO text with the Chinese season family still matches,
    purely on the show-level id (exactly the Gravity Falls/怪诞小镇 case
    noted in the real fix — see the module docstring)."""
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_sib_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    res = sib_json(dest, "--title", "Sherlock", "--ext", "tmdb_tv:19885")
    assert res["watched"] is True
    assert res["matched_by"] == "external_id"
    assert [w["title"] for w in res["matching_works"]] == ["神探夏洛克 第一季"]

def test_sibling_seasons_same_title_different_year_does_not_match(tmp_path):
    """Coordinator caution (same as the shells fix): two genuinely
    different works can share a title across years. 画皮 1966 is
    watched, 画皮 2008 is not, and neither carries a season suffix or a
    season family at all, so no match must fire on title alone."""
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_sib_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    res = sib_json(dest, "--title", "画皮", "--year", "2008")
    assert res["watched"] is False
    assert res["matched_by"] is None

def test_sibling_seasons_batch_matches_single_form_and_preserves_order(tmp_path):
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_sib_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    batch = tmp_path / "batch.json"
    items = [
        {"title": "Balance", "year": 1989},
        {"title": "神探夏洛克"},
        {"title": "Sherlock", "external_ids": {"tmdb_tv": "19885"}},
        {"title": "初来乍到 第二季", "year": 2015},
        {"title": "画皮", "year": 2008},
    ]
    batch.write_text(json.dumps(items, ensure_ascii=False))
    out = subprocess.run([sys.executable, HISTORY, "sibling-seasons",
                          "--snapshot", str(dest), "--batch", str(batch)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert payload["count"] == 5
    results = payload["results"]
    assert [r["title"] for r in results] == \
        ["Balance", "神探夏洛克", "Sherlock", "初来乍到 第二季", "画皮"]
    assert [r["watched"] for r in results] == [False, True, True, True, False]

    # agrees with the single-candidate form, item by item
    sys.path.insert(0, str(Path(HISTORY).parent))
    import history
    data = json.loads(dest.read_text())
    for item, batched in zip(items, results):
        direct = history.resolve_sibling_seasons(
            data, item["title"], item.get("year"), item.get("kind"),
            item.get("external_ids") or {})
        assert direct == batched

def test_sibling_seasons_requires_title_or_batch(tmp_path):
    dest = tmp_path / "snap.json"
    subprocess.run([sys.executable, HISTORY, "--db", str(_sib_db(tmp_path)),
                    "snapshot", "--out", str(dest)], check=True)
    out = subprocess.run([sys.executable, HISTORY, "sibling-seasons",
                          "--snapshot", str(dest)],
                         capture_output=True, text=True)
    assert out.returncode != 0
    assert "title" in out.stderr or "batch" in out.stderr

def test_shells_does_not_collapse_same_title_across_different_years(tmp_path):
    """Coordinator caution: two GENUINELY different works can share a
    title across years. Neither carries a season suffix or a season
    family, so the base-title fallback must never fire between them —
    the unwatched one must remain a real shell, not vanish."""
    ts = "2026-01-01T00:00:00"
    works = [(1, "film", "画皮", "", 1966, ts, ts),   # watched, unrelated
             (2, "film", "画皮", "", 2008, ts, ts)]   # unwatched, different film
    records = [(1, 1, "douban", "watched", 8.0, "2026-01-01", "", "", ts)]
    db = _setup(tmp_path, works, records)
    s = snap(db)
    assert [sh["title"] for sh in s["shells"]] == ["画皮"]
    assert s["shells"][0]["work_id"] == 2
    assert s["shells"][0]["year"] == 2008

# --- Base-rate statistics: `distribution`, `cell`, `percentile_of` -----
#
# distribution/resolve_cell/percentile_of take a parsed snapshot dict, so
# these fixtures skip the DB entirely and hand-build "rated" lists —
# hand-computable by design, so the expected numbers below are worked out
# by hand in the comments, not copied from the implementation.

# sorted stars: [2.0, 3.0, 4.0, 4.0, 4.0, 4.5, 5.0]  (n=7; the None-stars
# entry is watched-but-unrated and must be excluded from every stat)
# mean   = 26.5/7 = 3.785714...  -> round(.,3) = 3.786
# pct_ge4 = 5/7 = 71.428...%     -> round(.,1) = 71.4
# pct_5   = 1/7 = 14.285...%     -> round(.,1) = 14.3
# median: n=7 odd, middle (4th of 7, 0-idx 3) = 4.0
# nearest-rank percentiles, idx = ceil(P/100*7)-1, clamped:
#   P50: ceil(3.5)-1=3 -> 4.0    P70: ceil(4.9)-1=4 -> 4.0
#   P80: ceil(5.6)-1=5 -> 4.5    P90: ceil(6.3)-1=6 -> 5.0
#   P95: ceil(6.65)-1=6 -> 5.0
KNOWN_FIXTURE = {"rated": [
    {"kind": "film", "year": 2021, "stars": 3.0},
    {"kind": "film", "year": 2022, "stars": 4.0},
    {"kind": "film", "year": 2023, "stars": 4.0},
    {"kind": "film", "year": 2024, "stars": 5.0},
    {"kind": "film", "year": 1995, "stars": 2.0},
    {"kind": "tv",   "year": 2020, "stars": 4.0},
    {"kind": "tv",   "year": 2021, "stars": 4.5},
    {"kind": "tv",   "year": 2021, "stars": None},  # watched, never rated
]}

def test_distribution_overall_matches_hand_computed_stats():
    d = history.distribution(KNOWN_FIXTURE)
    o = d["overall"]
    assert o["n"] == 7                       # the None-stars entry excluded
    assert o["mean"] == round(26.5 / 7, 3)
    assert o["pct_ge4"] == 71.4
    assert o["pct_5"] == 14.3
    assert o["median"] == 4.0
    # mid-rank percentile ladder (coordinator ruling, 2026-08-23): each
    # rank's value is the smallest v with percentile_of(v, cell) >= rank,
    # using percentile_of's mid-rank (not "at or below") formula. Hand
    # check for P70/P80: mid-rank(4.0) = 100*(2+3/2)/7 = 50.0 (< 70, so
    # 4.0 does NOT satisfy P70 the way the old at-or-below convention did);
    # mid-rank(4.5) = 100*(5+1/2)/7 = 78.6 (>= 70 and >= 80).
    assert o["percentiles"] == {"50": 4.0, "70": 4.5, "80": 5.0,
                                "90": 5.0, "95": 5.0}
    assert o["histogram"] == {"2.0": 1, "3.0": 1, "4.0": 3,
                              "4.5": 1, "5.0": 1}

def test_distribution_excludes_unrated_watched_works():
    # the 8th fixture entry (tv/2021/stars=None) must not appear in ANY
    # cell it would otherwise belong to (tv/show, tv/show 2020-<ref>).
    d = history.distribution(KNOWN_FIXTURE, ref_year=2024)
    tv_cell = next(c for c in d["cells"] if c["label"] == "tv/show")
    assert tv_cell["n"] == 2                 # only the two rated tv entries
    era_cell = next(c for c in d["cells"] if c["label"] == "tv/show 2020-2024")
    assert era_cell["n"] == 2

def test_distribution_emits_expected_cells_and_marks_low_n():
    d = history.distribution(KNOWN_FIXTURE, ref_year=2024)
    labels = {c["label"] for c in d["cells"]}
    assert labels == {
        "film", "film pre-2000", "film 2000-2009", "film 2010-2019", "film 2020-2024",
        "tv/show", "tv/show pre-2000", "tv/show 2000-2009", "tv/show 2010-2019", "tv/show 2020-2024",
        # drama gets its own cells even with zero drama entries in this
        # fixture — it must never be silently folded into tv/show.
        "drama", "drama pre-2000", "drama 2000-2009", "drama 2010-2019", "drama 2020-2024",
    }
    # every cell in this tiny fixture is well under the n=30 floor
    assert all(c.get("low_n") is True for c in d["cells"])
    # a bucket with literally nothing in it (e.g. tv/show pre-2000) must
    # not crash and must report itself as empty, not as a false zero
    empty = next(c for c in d["cells"] if c["label"] == "tv/show pre-2000")
    assert empty["n"] == 0
    assert empty["mean"] is None
    assert empty["median"] is None
    assert empty["histogram"] == {}
    assert empty["percentiles"] == {"50": None, "70": None, "80": None,
                                    "90": None, "95": None}

def test_percentile_of_matches_hand_computed_mid_rank():
    # Coordinator ruling, 2026-08-23: percentile_of is mid-rank
    # (below + tied/2), NOT "at or below" — the naive convention scores
    # every tied prediction at the TOP of its band, which silently
    # recreates the soft gate this rework exists to remove. These
    # assertions are chosen to FAIL under the old "at or below" formula.
    d = history.distribution(KNOWN_FIXTURE)
    overall = d["overall"]
    # 2.0 is the sole minimum (below=0, equal=1): 100*(0+0.5)/7 = 7.1.
    # (old convention: 100*1/7 = 14.3 — this assertion would fail there.)
    assert history.percentile_of(2.0, overall) == round(100 * 0.5 / 7, 1)
    # 4.0 sits STRICTLY INSIDE its own tie band (2 below, 3 tied, 2
    # above) — not at the band's top edge. mid-rank: 100*(2+1.5)/7=50.0.
    # (old "at or below" convention: 100*5/7 = 71.4 — the exact overshoot
    # the coordinator flagged; this assertion would fail there.)
    assert history.percentile_of(4.0, overall) == round(100 * 3.5 / 7, 1)
    # 5.0 is the sole maximum (below=6, equal=1): 100*(6+0.5)/7 = 92.9,
    # NOT 100 — even the top value is only credited with half its own
    # band, per mid-rank. (old convention: 100*7/7 = 100.0 — would fail.)
    assert history.percentile_of(5.0, overall) == round(100 * 6.5 / 7, 1)
    assert history.percentile_of(0.5, overall) == 0.0   # boundary: below everything, no tie at all

def test_percentile_of_single_tied_value_scores_50_not_100():
    """The case the coordinator specifically asked to pin: when EVERY
    work in a cell shares one star value, that value's mid-rank
    percentile is 50.0 (dead center of its own — the only — band), never
    100.0. 100.0 would mean "nothing else in the population reaches this
    high", which mid-rank deliberately never claims for a tied value."""
    cell = {"histogram": {"5.0": 4}}
    assert history.percentile_of(5.0, cell) == 50.0

def test_percentile_of_zero_n_cell_returns_none_not_crash():
    empty_cell = {"histogram": {}}
    assert history.percentile_of(4.0, empty_cell) is None

def test_percentiles_ladder_is_not_a_two_way_invariant_with_percentile_of():
    """Coordinator correction, 2026-08-23: `percentile_of(percentiles[P],
    cell) >= P` is NOT a universal law — it is mathematically false
    whenever the top tie's own share is large enough (the maximum value
    in ANY distribution scores `100 - (its own tie share)/2`, strictly
    under 100, so it can never clear a rank close to 100 once its tie
    share crosses that point). An earlier version of this test asserted
    the two-way form and only happened to pass because its fixture's top
    value was engineered not to trigger the clamp — exactly the kind of
    test that silently encodes a false general law. Kept here as a
    negative check: this fixture's rank-95 entry is a case where the
    two-way form does NOT hold, and that is correct, not a regression."""
    data = {"rated": [{"kind": "film", "year": 2020, "stars": s} for s in
                      [1.0, 2.0, 2.5, 3.0, 3.0, 3.5, 4.0, 4.0, 4.5, 5.0, 5.0]]}
    cell = history.distribution(data)["overall"]
    p95 = cell["percentiles"]["95"]
    assert p95 == 5.0                                    # clamped: it's the max value
    assert history.percentile_of(p95, cell) < 95          # and its own score falls short

def test_percentiles_ladder_true_direction_no_smaller_value_reaches_the_rank():
    """The direction that IS always true, unconditionally (clamp or not):
    `_percentiles` returns the SMALLEST star value whose own mid-rank
    score clears rank P (or the max, if none does) — by construction, no
    value smaller than that returned value can itself clear P. This does
    not depend on whether the clamp fires, unlike the false two-way form
    above."""
    data = {"rated": [{"kind": "film", "year": 2020, "stars": s} for s in
                      [1.0, 2.0, 2.5, 3.0, 3.0, 3.5, 4.0, 4.0, 4.5, 5.0]]}
    cell = history.distribution(data)["overall"]
    values_sorted = sorted({e["stars"] for e in data["rated"]})
    for rank_str, ladder_value in cell["percentiles"].items():
        rank = float(rank_str)
        for v in values_sorted:
            if v < ladder_value:
                assert history.percentile_of(v, cell) < rank

def test_percentiles_ladder_clamp_is_a_documented_ceiling_not_a_bug():
    """When one tie at the TOP of the scale is heavy enough, no star
    value can mathematically reach a high rank under mid-rank scoring —
    5.0 is the ceiling, so 5.0's own score caps at 100 - (its tie share)/2
    no matter how the rest of the distribution looks. `_percentiles` must
    still return something (the max, per its documented clamp) rather
    than raising, and that returned value's own `percentile_of` score is
    ALLOWED to fall short of the rank label in exactly this situation —
    confirmed against the real tv/show cell, where 31.1% of works are
    5★, capping 5★'s own score at ~84.4 (< the 90/95 rank labels that
    clamp to it)."""
    # 40% of this cell is tied at the ceiling (5.0): its own mid-rank
    # score is 100 - 40/2 = 80, which cannot reach rank 90 or 95 no
    # matter what — nothing scores higher than the max value itself.
    data = {"rated": [{"kind": "film", "year": 2020, "stars": s} for s in
                      [2.0] * 3 + [3.0] * 3 + [5.0] * 4]}
    cell = history.distribution(data)["overall"]
    assert cell["n"] == 10
    assert history.percentile_of(5.0, cell) == 80.0     # the ceiling's own score
    assert cell["percentiles"]["90"] == 5.0             # clamped: no higher value exists
    assert cell["percentiles"]["95"] == 5.0             # same clamp
    # the clamp is documented, not silently wrong: the clamped value's
    # own score (80.0) legitimately falls short of both rank labels.
    assert history.percentile_of(cell["percentiles"]["90"], cell) < 90
    assert history.percentile_of(cell["percentiles"]["95"], cell) < 95

def _rated(n, kind, year, stars):
    return [{"kind": kind, "year": year, "stars": stars} for _ in range(n)]

def test_cell_no_fallback_when_specific_cell_meets_floor():
    data = {"rated": _rated(35, "film", 2015, 4.0)}
    cell = history.resolve_cell(data, "film", 2015)
    assert cell["label"] == "film 2010-2019"
    assert cell["n"] == 35
    assert cell["fallback_used"] is False
    assert "fallback_note" not in cell
    assert "low_n" not in cell

def test_cell_falls_back_to_kind_when_era_too_thin():
    # 5 in the specific era (< 30), 35 more film works elsewhere so the
    # kind-only cell clears the floor (40 total) without needing `overall`.
    data = {"rated": _rated(5, "film", 2015, 4.0) + _rated(35, "film", 2005, 3.0)}
    cell = history.resolve_cell(data, "film", 2015)
    assert cell["label"] == "film"                # era dropped
    assert cell["n"] == 40
    assert cell["fallback_used"] is True
    assert "2010-2019" in cell["fallback_note"]
    assert "n=5" in cell["fallback_note"]

def test_cell_falls_back_to_overall_when_kind_also_too_thin():
    # only 3 tv works total (kind-only cell also < 30); 40 film works make
    # `overall` clear the floor so the widening has somewhere to land.
    data = {"rated": _rated(3, "tv", 2015, 4.0) + _rated(40, "film", 2010, 3.5)}
    cell = history.resolve_cell(data, "tv", 2015)
    assert cell["label"] == "overall"
    assert cell["n"] == 43
    assert cell["fallback_used"] is True
    assert "tv/show 2010-2019" in cell["fallback_note"]
    assert "'tv/show' (n=3)" in cell["fallback_note"]

def test_drama_is_not_pooled_with_tv_show():
    """Coordinator ruling, 2026-08-23: kind='drama' is live theatre (话剧),
    a different medium from television, and must get its own cell rather
    than being folded into the tv/show population."""
    data = {"rated": _rated(1, "drama", 2015, 3.0) + _rated(40, "tv", 2015, 4.0)}
    d = history.distribution(data, ref_year=2024)
    tv_cell = next(c for c in d["cells"] if c["label"] == "tv/show")
    assert tv_cell["n"] == 40                     # the drama row is NOT counted here
    drama_cell = next(c for c in d["cells"] if c["label"] == "drama")
    assert drama_cell["n"] == 1
    assert drama_cell["low_n"] is True

def test_cell_drama_kind_falls_back_with_only_one_work():
    """A one-work 'base rate' would look authoritative and be meaningless
    — the fallback ladder must catch it exactly like any other thin kind,
    with no special-casing for drama."""
    data = {"rated": _rated(1, "drama", 2015, 3.0) + _rated(40, "film", 2010, 3.5)}
    cell = history.resolve_cell(data, "drama", 2015)
    assert cell["fallback_used"] is True
    assert cell["label"] == "overall"              # drama-only kind cell (n=1) also under floor
    assert cell["n"] == 41
    assert "drama 2010-2019" in cell["fallback_note"]
    assert "'drama' (n=1)" in cell["fallback_note"]

def test_cell_zero_matching_works_does_not_crash():
    # no tv works at all in the snapshot
    data = {"rated": _rated(1, "film", 2015, 4.0)}
    cell = history.resolve_cell(data, "tv", 2015)
    assert cell["fallback_used"] is True
    assert cell["label"] == "overall"
    assert cell["n"] == 1                 # widened all the way, still tiny
    assert cell["low_n"] is True          # flagged even though it's the
                                          # best available cell

def test_cell_unknown_kind_fails_loudly(tmp_path):
    dest = tmp_path / "snap.json"
    dest.write_text(json.dumps(KNOWN_FIXTURE))
    out = subprocess.run([sys.executable, HISTORY, "cell",
                          "--snapshot", str(dest),
                          "--kind", "book", "--year", "2020"],
                         capture_output=True, text=True)
    assert out.returncode != 0
    assert "kind" in out.stderr

def test_distribution_and_cell_cli_round_trip(tmp_path):
    dest = tmp_path / "snap.json"
    dest.write_text(json.dumps(KNOWN_FIXTURE))
    out = subprocess.run([sys.executable, HISTORY, "distribution",
                          "--snapshot", str(dest)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    assert result["overall"]["n"] == 7
    assert len(result["cells"]) == 15   # 3 kinds (film, tv/show, drama) x 5

    out = subprocess.run([sys.executable, HISTORY, "cell",
                          "--snapshot", str(dest),
                          "--kind", "film", "--year", "2022"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    cell = json.loads(out.stdout)
    assert cell["fallback_used"] is True   # tiny fixture, always widens
    assert cell["n"] >= 5                  # widened at least to the kind cell

# --- `percentile-of`: the one call site meant to answer "does this
# prediction clear a target" — never hand-derived from the ladder. -----

def test_resolve_percentile_of_no_fallback():
    data = {"rated": _rated(35, "film", 2015, 4.0)}
    result = history.resolve_percentile_of(data, "film", 2015, 4.0)
    assert result["kind"] == "film"
    assert result["year"] == 2015
    assert result["stars"] == 4.0
    assert result["cell"]["label"] == "film 2010-2019"
    assert result["cell"]["fallback_used"] is False
    # every work in this fixture is tied at exactly 4.0 -> mid-rank 50.0
    assert result["percentile"] == 50.0

def test_resolve_percentile_of_fallback_path():
    # same thin-era setup as test_cell_falls_back_to_kind_when_era_too_thin
    data = {"rated": _rated(5, "film", 2015, 4.0) + _rated(35, "film", 2005, 3.0)}
    result = history.resolve_percentile_of(data, "film", 2015, 4.0)
    assert result["cell"]["fallback_used"] is True
    assert result["cell"]["label"] == "film"              # era dropped
    assert "fallback_note" in result["cell"]
    assert result["percentile"] is not None

def test_resolve_percentile_of_zero_n_cell_returns_none_percentile():
    data = {"rated": _rated(1, "film", 2015, 4.0)}
    result = history.resolve_percentile_of(data, "tv", 2015, 4.0)
    assert result["cell"]["fallback_used"] is True
    assert result["percentile"] is not None   # widened all the way to overall (n=1)

def test_percentile_of_cli_matches_direct_call(tmp_path):
    dest = tmp_path / "snap.json"
    data = {"rated": _rated(35, "film", 2015, 4.0)}
    dest.write_text(json.dumps(data))
    out = subprocess.run([sys.executable, HISTORY, "percentile-of",
                          "--snapshot", str(dest),
                          "--kind", "film", "--year", "2015", "--stars", "4.0"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    assert result["kind"] == "film"
    assert result["year"] == 2015
    assert result["stars"] == 4.0
    assert result["percentile"] == 50.0
    assert result["cell"]["fallback_used"] is False
    assert result["cell"]["label"] == "film 2010-2019"
    direct = history.resolve_percentile_of(data, "film", 2015, 4.0)
    assert result == direct

def test_percentile_of_cli_reports_fallback(tmp_path):
    dest = tmp_path / "snap.json"
    data = {"rated": _rated(5, "film", 2015, 4.0) + _rated(35, "film", 2005, 3.0)}
    dest.write_text(json.dumps(data))
    out = subprocess.run([sys.executable, HISTORY, "percentile-of",
                          "--snapshot", str(dest),
                          "--kind", "film", "--year", "2015", "--stars", "4.0"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    assert result["cell"]["fallback_used"] is True
    assert "fallback_note" in result["cell"]

def test_percentile_of_cli_unknown_kind_fails_loudly(tmp_path):
    dest = tmp_path / "snap.json"
    dest.write_text(json.dumps(KNOWN_FIXTURE))
    out = subprocess.run([sys.executable, HISTORY, "percentile-of",
                          "--snapshot", str(dest),
                          "--kind", "book", "--year", "2020", "--stars", "4.0"],
                         capture_output=True, text=True)
    assert out.returncode != 0
    assert "kind" in out.stderr
