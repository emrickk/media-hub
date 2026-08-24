import json
import sqlite3
import subprocess
import sys
from pathlib import Path


BOOTSTRAP = str(Path(__file__).resolve().parents[1] / "bootstrap.py")
HISTORY = str(Path(__file__).resolve().parents[1] / "history.py")


def run(script, *args):
    return subprocess.run([sys.executable, script, *args],
                          capture_output=True, text=True)


def test_bootstrap_creates_complete_empty_recommendation_store(tmp_path):
    db = tmp_path / "media.db"

    out = run(BOOTSTRAP, "--db", str(db))

    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout)
    assert report["created"] is True
    con = sqlite3.connect(db)
    tables = {row[0] for row in con.execute(
        "select name from sqlite_master where type='table'")}
    assert {"works", "records", "external_ids", "recommendations",
            "recommendation_feedback", "candidate_pool", "engine_priors"} <= tables
    work_columns = {row[1] for row in con.execute("pragma table_info(works)")}
    assert {"original_title", "season_number", "creators", "meta"} <= work_columns

    snapshot = tmp_path / "snapshot.json"
    snap = run(HISTORY, "--db", str(db), "snapshot", "--out", str(snapshot))
    assert snap.returncode == 0, snap.stderr
    data = json.loads(snapshot.read_text("utf-8"))
    assert data["counts"] == {"rated": 0, "wishlist": 0, "shells": 0,
                              "rec_log": 0}


def test_bootstrap_is_idempotent_and_preserves_existing_rows(tmp_path):
    db = tmp_path / "media.db"
    assert run(BOOTSTRAP, "--db", str(db)).returncode == 0
    con = sqlite3.connect(db)
    con.execute("insert into works (kind,title,created_at,updated_at) "
                "values ('film','Keep Me','t','t')")
    con.commit(); con.close()

    second = run(BOOTSTRAP, "--db", str(db))

    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["created"] is False
    con = sqlite3.connect(db)
    assert con.execute("select title from works").fetchone()[0] == "Keep Me"
