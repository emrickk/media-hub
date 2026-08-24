"""One lean acceptance test for the clone-to-feedback product path."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run(script, *args):
    return subprocess.run([sys.executable, str(ROOT / script), *args],
                          capture_output=True, text=True)


def test_empty_store_to_rich_card_to_rejection_suppression(tmp_path):
    db = tmp_path / "media.db"
    assert run("recommend/bootstrap.py", "--db", str(db)).returncode == 0

    candidate = [{
        "kind": "tv", "title": "One Complete Mystery", "year": 2024,
        "external_ids": {"tmdb_tv": "123"}, "tags": ["mystery"],
        "sources": [{"channel": "first_run_topup", "fetched": "2026-08-24"}],
    }]
    candidate_file = tmp_path / "candidate.json"
    candidate_file.write_text(json.dumps(candidate), "utf-8")
    assert run("recommend/pool.py", "--db", str(db), "upsert", "--json",
               str(candidate_file)).returncode == 0

    dossier = {
        "scout": {
            "case": "A concrete structural match.", "evidence_density": "adjacent",
            "enrichment": {
                "knowledge": "rich", "basis": "model-knowledge",
                "summary": "Several conversations converge into one mystery.",
                "special": "The apparently separate episodes form one complete story.",
                "personal_hook": "The payoff depends on noticing visible structural clues.",
                "good_to_know": "Watch the short season in order.",
                "entry": {"applicable": True, "start_at": "S1E1",
                          "why": "The mystery begins immediately.",
                          "exit_test": "Try two episodes."},
                "inside": {"moments": ["Every conversation leaves a clue."],
                           "quotes": []},
                "ratings": [{"source": "IMDb", "value": "8.2/10"}],
            },
        },
        "critic": {"pitch_rank": 1, "pitch_selected": True,
                   "predicted_percentile": 82, "predicted_appetite": "high",
                   "appetite_case": "The on-ramp is immediate.",
                   "selection_reason": "Strongest start-now case."},
    }
    recommendation = [{
        "intention": "Recommend something from chat history", "kind": "tv",
        "title": "One Complete Mystery", "year": 2024,
        "external_ids": {"tmdb_tv": "123"}, "dossier": dossier,
        "predicted_stars": 4.5, "predicted_confidence": "medium",
    }]
    recommendation_file = tmp_path / "recommendation.json"
    recommendation_file.write_text(json.dumps(recommendation), "utf-8")
    logged = run("recommend/reclog.py", "--db", str(db), "log", "--json",
                 str(recommendation_file))
    assert logged.returncode == 0, logged.stderr
    rid = json.loads(logged.stdout)[0]

    html = tmp_path / "recommendations.html"
    rendered = run("recommend/render.py", "--db", str(db), "--ids", str(rid),
                   "--out", str(html), "--no-network")
    assert rendered.returncode == 0, rendered.stderr
    page = html.read_text("utf-8")
    assert "What makes it special" in page
    assert "Right title, weak pitch" in page
    assert "media-hub-feedback-v1" in page

    feedback_file = tmp_path / "feedback.json"
    feedback_file.write_text(json.dumps({"feedback": [
        {"id": rid, "reaction": "wrong_title", "note": "Not for me."},
    ]}), "utf-8")
    assert run("recommend/reclog.py", "--db", str(db), "feedback", "--json",
               str(feedback_file)).returncode == 0
    assert run("recommend/pool.py", "--db", str(db), "suppress-sync").returncode == 0
    remaining = run("recommend/pool.py", "--db", str(db), "query")
    assert json.loads(remaining.stdout) == []
