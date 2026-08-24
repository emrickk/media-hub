"""Tests for harvest_douban.py — all offline, no network, no real DB.

Second-pass note: the module was rewritten around Douban's rexxar mobile
JSON API (`m.douban.com/rexxar/api/v2/movie/<id>/recommendations`) after
the coordinator identified it as the actual working precedent
(`mediahub.py`'s `cmd_enrich_douban`) and verified it live. The two
"happy path" fixtures below (`douban_rec_film_sample.json`,
`douban_rec_tv_sample.json`) are REAL captured responses (one film
anchor, one TV anchor; 20 items each), not synthetic data — see
harvest_douban.py's module docstring for the exact probe. The old
challenge-shell HTML fixture (`douban_subject_sample.html.gz`, from the
first pass's desktop-subject-page probe) is kept as the negative fixture
for `is_blocked`, since that same interstitial can still appear if the
JSON endpoint's session gets walled.
"""
import gzip, json, sqlite3, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = str(ROOT / "harvest_douban.py")
FIXTURES = ROOT / "tests" / "fixtures"
CHALLENGE_FIXTURE = FIXTURES / "douban_subject_sample.html.gz"
FILM_FIXTURE = FIXTURES / "douban_rec_film_sample.json"
TV_FIXTURE = FIXTURES / "douban_rec_tv_sample.json"

sys.path.insert(0, str(ROOT))
import harvest_douban as hd


def run(*a):
    return subprocess.run([sys.executable, H, *a], capture_output=True, text=True)


def challenge_html() -> str:
    with gzip.open(CHALLENGE_FIXTURE, "rt", encoding="utf-8") as fh:
        return fh.read()


def load_fixture_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------- is_blocked

def test_challenge_fixture_is_blocked():
    """The ACTUAL captured response from the first pass's live probe of
    https://movie.douban.com/subject/10561953/ — Douban's proof-of-work
    interstitial. Kept as the negative-case fixture since the rexxar JSON
    endpoint can still be walled with this same HTML shell."""
    assert hd.is_blocked(challenge_html()) is True


def test_blocked_by_final_url_alone():
    assert hd.is_blocked("<html>anything</html>",
                          "https://sec.douban.com/c?r=x") is True


def test_unblocked_synthetic_page_not_flagged():
    html = "<html><body>" + ("<p>hello world</p>" * 2000) + "</body></html>"
    assert hd.is_blocked(html) is False


# ------------------------------------------------------- parse_recommendations

def test_parse_recommendations_happy_path_film_real_fixture():
    """REAL data: 20 items from a live fetch of a film anchor's
    recommendations. All items observed to be `type: 'movie'` -> kind
    'film', and all 20 card_subtitles start with a 4-digit year."""
    payload = load_fixture_payload(FILM_FIXTURE)
    entries = hd.parse_recommendations(payload["results"])
    assert len(entries) >= 5
    assert len(entries) == 20
    for e in entries:
        assert isinstance(e["douban_id"], int)
        assert e["title"]
        assert e["kind"] == "film"
        assert isinstance(e["year"], int) and 1900 < e["year"] < 2030
        assert isinstance(e.get("rating"), float)


def test_parse_recommendations_happy_path_tv_real_fixture():
    """REAL data: 20 items from a live fetch of a TV anchor's
    recommendations. All items observed to be `type: 'tv'` -> kind 'tv' —
    proving kind comes from the ITEM, not the anchor (this fixture's own
    anchor is also tv, so a true cross-kind item wasn't observed live,
    but the mapping is exercised end to end regardless)."""
    payload = load_fixture_payload(TV_FIXTURE)
    entries = hd.parse_recommendations(payload["results"])
    assert len(entries) == 20
    for e in entries:
        assert isinstance(e["douban_id"], int)
        assert e["title"]
        assert e["kind"] == "tv"
        assert isinstance(e["year"], int) and 1900 < e["year"] < 2030
        assert isinstance(e.get("rating"), float)


def test_parse_recommendations_kind_from_item_not_anchor():
    """Direct proof that kind mapping is item-driven: a synthetic batch
    mixing 'movie' and 'tv' types (something a real anchor's CF panel can
    do even though neither of our two live-captured fixtures happened to)
    maps each item independently."""
    results = [
        {"id": "1", "title": "A Film Neighbor", "type": "movie",
         "card_subtitle": "2020 / USA / Drama", "rating": {"value": 8.0}},
        {"id": "2", "title": "A TV Neighbor", "type": "tv",
         "card_subtitle": "2019 / USA / Drama", "rating": {"value": 7.5}},
    ]
    entries = hd.parse_recommendations(results)
    assert entries[0]["kind"] == "film"
    assert entries[1]["kind"] == "tv"


def test_parse_recommendations_unrecognized_type_passthrough(capsys):
    results = [{"id": "1", "title": "Mystery Kind", "type": "drama",
                "card_subtitle": "2020 / X", "rating": {"value": 8.0}}]
    entries = hd.parse_recommendations(results)
    assert entries[0]["kind"] == "drama"
    assert "unrecognized" in capsys.readouterr().err


def test_parse_recommendations_no_year_prefix_leaves_year_null():
    results = [{"id": "1", "title": "No Year Here", "type": "movie",
                "card_subtitle": "USA / Drama", "rating": {"value": 8.0}}]
    entries = hd.parse_recommendations(results)
    assert entries[0]["year"] is None


def test_parse_recommendations_skips_malformed_items():
    results = [
        {"id": "1", "title": "Good", "type": "movie", "card_subtitle": "2020 / X"},
        {"id": None, "title": "No id"},
        {"id": "2", "title": ""},
        "not a dict",
        {"id": "not-numeric", "title": "Bad id"},
    ]
    entries = hd.parse_recommendations(results)
    assert len(entries) == 1
    assert entries[0]["title"] == "Good"


def test_parse_recommendations_empty_list_returns_empty():
    assert hd.parse_recommendations([]) == []


def test_parse_recommendations_no_rating_key_omitted():
    results = [{"id": "1", "title": "No Rating", "type": "movie",
                "card_subtitle": "2020 / X"}]
    entries = hd.parse_recommendations(results)
    assert "rating" not in entries[0]


# ------------------------------------------------------------- extract_genres
#
# Genre extraction (2026-08-23): every douban_rec pool row carried
# `tags: []`. `card_subtitle`'s 3rd `" / "`-split field IS the genre
# segment, but ONLY when Douban actually included one — a handful of
# titles omit it entirely, sliding the director's name into that
# position instead, so position alone is not trustworthy; see
# harvest_douban.py's module docstring "Genre extraction" for the full
# rationale and the real-corpus numbers behind GENRE_VOCAB.

def test_extract_genres_real_fixture_first_item():
    """REAL data: the TV fixture's first item's card_subtitle genre
    segment is '剧情 动作 犯罪'."""
    payload = load_fixture_payload(TV_FIXTURE)
    cs = payload["results"][0]["card_subtitle"]
    assert hd.extract_genres(cs) == ["剧情", "动作", "犯罪"]

def test_extract_genres_single_genre_five_field_form():
    assert hd.extract_genres(
        "2014 / 法国 / 动画 / 亚历山大·西伯恩 伯努瓦·菲利 / 奥玛·希 伊莎雅·海格林"
    ) == ["动画"]

def test_extract_genres_three_field_form_no_director_or_cast():
    """Real form seen when Douban has neither director nor cast credits
    but DOES have a genre: only 3 fields, genre still in position 2."""
    assert hd.extract_genres("2021 / 美国 / 纪录片") == ["纪录片"]

def test_extract_genres_multi_word_three_field_form():
    assert hd.extract_genres("2021 / 美国 / 悬疑 纪录片 犯罪 运动") == \
        ["悬疑", "纪录片", "犯罪", "运动"]

def test_extract_genres_documented_negative_genre_omitted_director_in_slot():
    """Real captured case: Douban omitted the genre segment entirely for
    this title, so the director's name slides into the 3rd field's
    position instead of a genre word. A position-only extractor would
    misreport this director as a genre; extract_genres must refuse (the
    documented negative this task calls for, not a guess)."""
    assert hd.extract_genres(
        "2020 / 美国 / 伊恩·B·麦克唐纳 / 卡梅隆·莫纳汉 Cameron Monaghan 诺尔·费舍"
    ) == []
    assert hd.extract_genres("2018 / 美国 / 约翰·奥利弗") == []

def test_extract_genres_too_few_fields_returns_empty():
    assert hd.extract_genres("USA / Drama") == []
    assert hd.extract_genres("") == []
    assert hd.extract_genres(None) == []

def test_extract_genres_mixed_known_and_unknown_token_rejects_whole_field():
    """A field with even ONE non-vocabulary token must not partially
    extract — that would silently promote a name fragment to a genre."""
    assert hd.extract_genres("2020 / 美国 / 喜剧 张三") == []


# ------------------------------------------------------------------ anchors

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
    """)
    ts = "2026-01-01T00:00:00"
    con.executemany("INSERT INTO works VALUES (?,?,?,?,?,?)", [
        (1, "tv", "High Rated Show", 2020, ts, ts),
        (2, "film", "Low Rated Film", 2019, ts, ts),
        (3, "tv", "No Douban Id Show", 2021, ts, ts),
        (4, "game", "A Game", 2022, ts, ts),
    ])
    con.executemany("INSERT INTO records (work_id,source,status,rating) VALUES (?,?,?,?)", [
        (1, "douban", "watched", 9.0),
        (2, "douban", "watched", 6.0),
        (3, "douban", "watched", 10.0),
        (4, "douban", "watched", 10.0),
    ])
    con.executemany("INSERT INTO external_ids VALUES (?,?,?)", [
        (1, "douban", "1546"),
        (2, "douban", "9999"),
        (4, "douban", "7777"),
    ])
    con.commit(); con.close()
    return db


def test_anchors_filters_kind_rating_and_douban_id(tmp_path):
    db = mkdb(tmp_path)
    out = run("anchors", "--db", str(db), "--min-rating", "9", "--kinds", "tv,show,film")
    assert out.returncode == 0, out.stderr
    anchors = json.loads(out.stdout)
    assert anchors == [{"work_id": 1, "kind": "tv", "title": "High Rated Show",
                        "douban_id": "1546"}]


def test_anchors_kinds_filter_includes_game_when_asked(tmp_path):
    db = mkdb(tmp_path)
    out = run("anchors", "--db", str(db), "--min-rating", "9", "--kinds", "game")
    assert out.returncode == 0, out.stderr
    anchors = json.loads(out.stdout)
    assert [a["work_id"] for a in anchors] == [4]


# ------------------------------------------------------------------- fetch

class FakeResponse:
    def __init__(self, text, status_code=200, url="https://m.douban.com/x"):
        self.text = text
        self.status_code = status_code
        self.url = url

    def json(self):
        return json.loads(self.text)


def _args(anchors_file, raw_dir, checkpoint, budget=40, delay=0):
    class Args:
        pass
    a = Args()
    a.anchors = str(anchors_file); a.raw_dir = str(raw_dir)
    a.checkpoint = str(checkpoint); a.budget = budget
    a.delay_min = delay; a.delay_max = delay
    return a


def _run_cmd_fetch_captured(args):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        hd.cmd_fetch(args)
    return json.loads(buf.getvalue())


def test_fetch_blocked_on_403_stops_run(tmp_path, monkeypatch):
    import types
    calls = []

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kw):
            calls.append(url)
            if "/movie/2/" in url:
                return FakeResponse("blocked body", status_code=403,
                                     url="https://m.douban.com/rexxar/api/v2/movie/2/recommendations")
            return FakeResponse(json.dumps([{"id": "9", "title": "Neighbor",
                                             "type": "movie", "card_subtitle": "2020 / X",
                                             "rating": {"value": 8.0}}]))

    fake_requests = types.SimpleNamespace(Session=FakeSession, RequestException=Exception)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setattr(hd.time, "sleep", lambda s: None)

    anchors_file = tmp_path / "anchors.json"
    anchors_file.write_text(json.dumps([
        {"work_id": 1, "kind": "tv", "title": "A", "douban_id": "1"},
        {"work_id": 2, "kind": "tv", "title": "B", "douban_id": "2"},
        {"work_id": 3, "kind": "tv", "title": "C", "douban_id": "3"},
    ]))
    raw_dir = tmp_path / "raw"
    checkpoint = tmp_path / "checkpoint.json"
    args = _args(anchors_file, raw_dir, checkpoint)

    report = _run_cmd_fetch_captured(args)
    assert report["fetched"] == 1
    assert report["blocked"] is True
    assert report["circuit_breaker_tripped"] is False
    assert report["attempted"] == 2       # never reached anchor 3
    assert calls == [
        "https://m.douban.com/rexxar/api/v2/movie/1/recommendations?for_mobile=1",
        "https://m.douban.com/rexxar/api/v2/movie/2/recommendations?for_mobile=1",
    ]

    raw1 = json.loads((raw_dir / "1.json").read_text())
    assert raw1["_meta"]["status"] == "fetched"
    assert len(raw1["results"]) == 1
    raw2 = json.loads((raw_dir / "2.json").read_text())
    assert raw2["_meta"]["status"] == "blocked"
    assert raw2["_meta"]["http_status"] == 403

    cp = json.loads(checkpoint.read_text())
    assert cp["1"]["status"] == "fetched"
    assert cp["2"]["status"] == "blocked"
    assert "3" not in cp

    # Resume: 1 and 2 are checkpointed -> skipped; only 3 attempted.
    calls.clear()
    report2 = _run_cmd_fetch_captured(args)
    assert report2["skipped_resumed"] == 2
    assert report2["attempted"] == 1
    assert calls == ["https://m.douban.com/rexxar/api/v2/movie/3/recommendations?for_mobile=1"]


def test_fetch_circuit_breaker_trips_after_eight_consecutive_failures(tmp_path, monkeypatch):
    import types

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kw):
            # Every request "succeeds" at the HTTP layer but returns junk
            # (not a JSON list, and not the known challenge shell either)
            # -- an unrecognized-failure case, not an outright 403/302 block.
            return FakeResponse("not json at all", status_code=200)

    fake_requests = types.SimpleNamespace(Session=FakeSession, RequestException=Exception)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setattr(hd.time, "sleep", lambda s: None)

    anchors_file = tmp_path / "anchors.json"
    anchors_file.write_text(json.dumps(
        [{"work_id": i, "kind": "tv", "title": f"T{i}", "douban_id": str(i)}
         for i in range(1, 11)]))
    raw_dir = tmp_path / "raw"
    checkpoint = tmp_path / "checkpoint.json"
    args = _args(anchors_file, raw_dir, checkpoint)

    report = _run_cmd_fetch_captured(args)
    assert report["circuit_breaker_tripped"] is True
    assert report["blocked"] is False
    assert report["attempted"] == 8
    assert report["fetched"] == 0


def test_fetch_budget_stops_run(tmp_path, monkeypatch):
    import types

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kw):
            return FakeResponse(json.dumps([]))

    fake_requests = types.SimpleNamespace(Session=FakeSession, RequestException=Exception)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setattr(hd.time, "sleep", lambda s: None)

    anchors_file = tmp_path / "anchors.json"
    anchors_file.write_text(json.dumps(
        [{"work_id": i, "kind": "tv", "title": f"T{i}", "douban_id": str(i)}
         for i in range(1, 6)]))
    raw_dir = tmp_path / "raw"
    checkpoint = tmp_path / "checkpoint.json"
    args = _args(anchors_file, raw_dir, checkpoint, budget=2)

    report = _run_cmd_fetch_captured(args)
    assert report["budget_hit"] is True
    assert report["attempted"] == 2
    assert report["fetched"] == 2


# ---------------------------------------------------------------- transform

def test_transform_end_to_end_real_fixtures(tmp_path):
    """Real captured data straight through `transform` (subprocess, no
    mocking): both real fixtures dropped into a raw-dir yield 40 batch
    rows matching pool.py's upsert contract."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "11584019.json").write_text(FILM_FIXTURE.read_text(encoding="utf-8"))
    (raw_dir / "26635374.json").write_text(TV_FIXTURE.read_text(encoding="utf-8"))

    out = tmp_path / "batch.json"
    r = run("transform", "--raw-dir", str(raw_dir), "--out", str(out))
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report == {"raw_pages": 2, "blocked": 0, "skipped": 0, "entries": 40}

    rows = json.loads(out.read_text())
    assert len(rows) == 40
    kinds = {r["kind"] for r in rows}
    assert kinds == {"film", "tv"}
    for row in rows:
        assert row["kind"] and row["title"]
        assert row["sources"] and row["sources"][0]["channel"] == "douban_rec"
        assert set(row["external_ids"]) == {"douban"}
        assert isinstance(row["external_ids"]["douban"], str)
        assert isinstance(row["year"], int)                 # all 40 real items had a year
        assert isinstance(row["aggregates"]["douban_rating"], float)
        # genre extraction (2026-08-23): all 40 real fixture items carry a
        # confidently-extractable genre segment.
        assert row["tags"] and all(g in hd.GENRE_VOCAB for g in row["tags"])
    film_rows = [r for r in rows if r["kind"] == "film"]
    assert all(r["sources"][0]["anchor_work_id"] == 458 for r in film_rows)
    tv_rows = [r for r in rows if r["kind"] == "tv"]
    assert all(r["sources"][0]["anchor_work_id"] == 455 for r in tv_rows)


def test_transform_counts_blocked_page_not_a_crash(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    payload = {"_meta": {"channel": "douban_rec", "anchor_work_id": 1, "anchor_kind": "tv",
                          "douban_id": "1546", "status": "blocked", "http_status": 403,
                          "fetched": "2026-08-23"}}
    (raw_dir / "1546.json").write_text(json.dumps(payload))

    out = tmp_path / "batch.json"
    r = run("transform", "--raw-dir", str(raw_dir), "--out", str(out))
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report == {"raw_pages": 1, "blocked": 1, "skipped": 0, "entries": 0}
    assert json.loads(out.read_text()) == []


def test_transform_skips_file_with_no_meta(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "junk.json").write_text(json.dumps({"results": []}))

    out = tmp_path / "batch.json"
    r = run("transform", "--raw-dir", str(raw_dir), "--out", str(out))
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report == {"raw_pages": 0, "blocked": 0, "skipped": 1, "entries": 0}
    assert json.loads(out.read_text()) == []


def test_transform_row_shape_matches_pool_upsert_contract(tmp_path):
    """Direct check against recommend/pool.py's actual validator/merge
    fields (kind, title, sources required; year/external_ids/aggregates
    optional), not the plan text."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    payload = {
        "_meta": {"channel": "douban_rec", "anchor_work_id": 7, "anchor_kind": "tv",
                  "douban_id": "42", "status": "fetched", "fetched": "2026-08-23"},
        "results": [{"id": "555", "title": "Neighbor A", "type": "movie",
                     "card_subtitle": "2018 / USA / Drama", "rating": {"value": 8.4}}],
    }
    (raw_dir / "42.json").write_text(json.dumps(payload))

    out = tmp_path / "batch.json"
    r = run("transform", "--raw-dir", str(raw_dir), "--out", str(out))
    assert r.returncode == 0, r.stderr
    rows = json.loads(out.read_text())
    # NB: this fixture's card_subtitle genre segment is the synthetic
    # English word "Drama", not a GENRE_VOCAB (Chinese) token, so no
    # `tags` key is expected here — see the dedicated genre-extraction
    # tests above for the real-Chinese-vocabulary happy path.
    assert rows == [{
        "kind": "film", "title": "Neighbor A", "year": 2018,
        "external_ids": {"douban": "555"},
        "sources": [{"channel": "douban_rec", "anchor_work_id": 7, "fetched": "2026-08-23"}],
        "aggregates": {"douban_rating": 8.4},
    }]

    sys.path.insert(0, str(ROOT))
    import pool
    problems = pool._validate_upsert_rows(rows)
    assert problems == []


def test_transform_row_omits_tags_key_when_genre_not_extractable(tmp_path):
    """Documented negative (2026-08-23): a genre-omitted card_subtitle
    (director's name slid into the genre position) must leave the row
    with NO `tags` key at all — never a guessed/wrong genre list — and
    still satisfy pool.py's upsert contract (tags is optional)."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    payload = {
        "_meta": {"channel": "douban_rec", "anchor_work_id": 7, "anchor_kind": "tv",
                  "douban_id": "42", "status": "fetched", "fetched": "2026-08-23"},
        "results": [{"id": "556", "title": "No Genre Here", "type": "tv",
                     "card_subtitle": "2018 / 美国 / 约翰·奥利弗"}],
    }
    (raw_dir / "42.json").write_text(json.dumps(payload))

    out = tmp_path / "batch.json"
    r = run("transform", "--raw-dir", str(raw_dir), "--out", str(out))
    assert r.returncode == 0, r.stderr
    rows = json.loads(out.read_text())
    assert len(rows) == 1
    assert "tags" not in rows[0]

    sys.path.insert(0, str(ROOT))
    import pool
    assert pool._validate_upsert_rows(rows) == []
