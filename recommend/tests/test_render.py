"""Tests for render.py — the pitch page.

Only the pure parts are tested: the id guard (which exists because a live
run wrote two fabricated tmdb ids into media.db and nothing caught them),
row flattening, and the grouping that decides which cards lead the page.
Network fetch and HTML cosmetics are deliberately not tested.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render  # noqa: E402


# ---------------------------------------------------------------- id guard

def detail(names, year):
    return {"names": set(names), "year": year}


def test_id_matches_on_exact_title():
    assert render.id_matches(detail(["Rear Window"], 1954), "Rear Window", "", 1954)


def test_id_matches_ignores_case_and_punctuation():
    assert render.id_matches(detail(["Spider-Man"], 2002), "spider man", "", 2002)


def test_id_matches_on_original_title_when_display_title_is_chinese():
    assert render.id_matches(detail(["Planet Earth"], 2006),
                             "地球脉动", "Planet Earth", 2006)


def test_id_matches_on_year_alone_when_tmdb_has_no_translation():
    """A Chinese-titled work TMDB carries only in English must not be
    accused of a bad id just because the strings differ."""
    assert render.id_matches(detail(["Some English Name"], 2011),
                             "某中文名", "", 2011)


def test_id_mismatch_when_both_title_and_year_disagree():
    """The real failure: tmdb_tv 2795 is a Philippine newscast, logged
    onto 人类星球/Human Planet (2011)."""
    assert not render.id_matches(detail(["GMA Network News"], None),
                                 "人类星球", "Human Planet", 2011)


def test_id_mismatch_when_year_is_off_by_more_than_one():
    assert not render.id_matches(detail(["Ain't Misbehavin'"], 1994),
                                 "地球脉动", "Planet Earth", 2006)


def test_id_matches_tolerates_one_year_of_drift():
    assert render.id_matches(detail(["Other Title"], 2007), "地球脉动", "", 2006)


def test_empty_detail_never_matches():
    assert not render.id_matches({}, "Anything", "", 2000)


# ------------------------------------------------------------- cache keys

def test_cache_key_prefers_tmdb_id():
    assert render.cache_key({"tmdb_movie": "567", "douban": "1"}, "x", 1) \
        == "tmdb_movie_567"


def test_cache_key_falls_back_to_douban_then_title():
    assert render.cache_key({"douban": "1871906"}, "x", 1) == "douban_1871906"
    assert render.cache_key({}, "Rear Window", 1954).startswith("title_")


# ------------------------------------------------------- row -> card view

SCHEMA = """
create table recommendations (
    id integer primary key, session_date text not null, intention text not null,
    kind text not null, title text not null, year integer,
    external_ids text not null default '{}', work_id integer,
    dossier text not null default '{}', predicted_stars real,
    predicted_confidence text, critic_killed integer not null default 0,
    kill_reason text not null default '', verdict text, verdict_note text
    not null default '', verdict_date text, created_at text not null,
    updated_at text not null);
"""


def make_row(con, rid, title, rank=None, selected=None, killed=0,
             enrichment=None, appetite=None, evidence_density=None):
    dossier = {
        "scout": {"case": f"case for {title}", "original_title": title,
                  "shape": {"runtime_min": 100},
                  **({"enrichment": enrichment} if enrichment else {}),
                  **({"evidence_density": evidence_density}
                     if evidence_density else {})},
        "critic": {"pitch_rank": rank, "pitch_selected": selected,
                   "predicted_percentile": 88.0, "cell_label": "cell",
                   "selection_reason": "because", "residual_risks": ["r"],
                   "evidence_chain": ["e"],
                   **({"predicted_appetite": appetite,
                       "appetite_case": "The concrete hook lowers the start cost."}
                      if appetite else {})},
    }
    con.execute(
        "insert into recommendations (id, session_date, intention, kind, title,"
        " year, external_ids, dossier, predicted_stars, predicted_confidence,"
        " critic_killed, kill_reason, created_at, updated_at)"
        " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, "2026-08-23T19:00:00", "the ask", "film", title, 2020, "{}",
         json.dumps(dossier), 4.5, "high", killed,
         "rule: why" if killed else "", "t", "t"))


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def test_card_of_lifts_nested_critic_fields_to_the_top(con):
    make_row(con, 1, "A", rank=2, selected=True)
    row = con.execute("select * from recommendations").fetchone()
    card = render.card_of(row)
    assert card["rank"] == 2 and card["selected"] is True
    assert card["percentile"] == 88.0
    assert card["case"] == "case for A"
    assert card["stars"] == 4.5


def test_card_of_lifts_enrichment_appetite_and_evidence_density(con):
    enrichment = {
        "knowledge": "rich", "basis": "model-knowledge",
        "summary": "A taxi driver hears conversations that converge into one mystery.",
        "special": "Thirteen short episodes form one complete story.",
        "personal_hook": "Its visual identity and structural payoff are both load-bearing.",
        "good_to_know": "Finish the season before judging its apparently separate threads.",
        "entry": {"applicable": True, "start_at": "S1E1",
                  "why": "The central mystery starts immediately.",
                  "exit_test": "Try two episodes."},
        "inside": {"moments": ["Every passenger leaves a clue."],
                   "quotes": [{"text": "Keep it short.", "speaker": "Odokawa"}]},
        "reception": "Widely praised as a tightly constructed mystery.",
        "ratings": [{"source": "IMDb", "value": "8.4/10"}],
    }
    make_row(con, 1, "Odd Taxi", enrichment=enrichment,
             appetite="high", evidence_density="anchored")

    card = render.card_of(con.execute("select * from recommendations").fetchone())

    assert card["enrichment"] == enrichment
    assert card["appetite"] == "high"
    assert card["appetite_case"].startswith("The concrete hook")
    assert card["evidence_density"] == "anchored"


def test_render_card_shows_concrete_enrichment_and_attributed_quote(con):
    enrichment = {
        "knowledge": "thin", "basis": "fetched-evidence",
        "summary": "A compact mystery.", "special": "One story, no filler.",
        "personal_hook": "It connects to the user's stated love of visible structure.",
        "good_to_know": "Specific episode claims were intentionally omitted.",
        "entry": {"applicable": True, "start_at": "S1E1",
                  "why": "The premise is established there.", "exit_test": "Try one episode."},
        "inside": {"moments": ["Conversations accumulate into evidence."],
                   "quotes": [{"text": "A short line.", "speaker": "The show"}]},
        "reception": "Strong audience reception.",
        "ratings": [{"source": "IMDb", "value": "8.0/10"}],
    }
    make_row(con, 1, "Mystery", enrichment=enrichment, appetite="high",
             evidence_density="adjacent")
    card = render.card_of(con.execute("select * from recommendations").fetchone())
    card.update({"overview": "", "id_warning": "", "poster_data": ""})

    html = render.render_card(card)

    for text in ("What it is", "What makes it special", "Why I picked it for you",
                 "Good to know", "Where to start", "Inside it",
                 "A compact mystery.", "S1E1", "Conversations accumulate",
                 "A short line.", "The show", "IMDb", "8.0/10",
                 "Knowledge is thin"):
        assert text in html


def test_render_card_without_enrichment_does_not_invent_sections(con):
    make_row(con, 1, "Legacy")
    card = render.card_of(con.execute("select * from recommendations").fetchone())
    card.update({"overview": "", "id_warning": "", "poster_data": ""})

    html = render.render_card(card)

    assert "What makes it special" not in html
    assert "Where to start" not in html
    assert "Inside it" not in html


def test_card_of_survives_a_missing_dossier(con):
    make_row(con, 1, "A")
    con.execute("update recommendations set dossier='' , external_ids='' ")
    row = con.execute("select * from recommendations").fetchone()
    card = render.card_of(row)
    assert card["title"] == "A" and card["case"] == "" and card["rank"] is None


def test_fetch_rows_defaults_to_the_latest_session_excluding_kills(con):
    make_row(con, 1, "A", rank=1, selected=True)
    make_row(con, 2, "B", killed=1)
    rows = render.fetch_rows(con, None, include_killed=False)
    assert [r["id"] for r in rows] == [1]
    rows = render.fetch_rows(con, None, include_killed=True)
    assert [r["id"] for r in rows] == [1, 2]


def test_fetch_rows_preserves_explicit_id_order(con):
    make_row(con, 1, "A")
    make_row(con, 2, "B")
    assert [r["id"] for r in render.fetch_rows(con, [2, 1], False)] == [2, 1]


def test_render_page_puts_unselected_survivors_below_the_picks(con):
    """A survivor the critic left pitch_selected=false cleared the gate —
    it belongs on the page, but never beside the actual picks."""
    make_row(con, 1, "Picked", rank=1, selected=True)
    make_row(con, 2, "Capped", rank=2, selected=False)
    cards = [render.card_of(r) for r in
             con.execute("select * from recommendations order by id")]
    for c in cards:
        c["overview"] = ""
        c["id_warning"] = ""
    picks = [c for c in cards if c["selected"] is not False]
    alsoran = [c for c in cards if c["selected"] is False]
    page = render.render_page(picks, alsoran, [], "ask", "2026-08-23 19:00")
    assert page.index("Picked") < page.index("Also passed review") < page.index("Capped")
    assert 'class="slate-card slate-card--secondary"' in page


def test_primary_card_uses_the_dark_editorial_redesign(con):
    enrichment = {
        "summary": "A direct, concrete premise.",
        "special": "The formal device that makes it distinct.",
        "personal_hook": "The exact part likely to pull this user in.",
        "good_to_know": "One useful expectation before starting.",
        "entry": {"applicable": True, "start_at": "Episode 1",
                  "why": "The premise starts there.", "exit_test": "Try two."},
        "inside": {"moments": ["A spoiler-light concrete moment."], "quotes": []},
    }
    make_row(con, 1, "Editorial Pick", rank=1, selected=True,
             enrichment=enrichment, appetite="high")
    card = render.card_of(con.execute("select * from recommendations").fetchone())
    card.update({"overview": "", "id_warning": "", "poster_file": None,
                 "vote": 8.3, "votes": 7312})

    page = render.render_page([card], [], [], "something for tonight",
                              "2026-08-24 19:30")

    assert 'class="slate-card slate-card--primary"' in page
    assert 'class="reason-grid"' in page
    assert "What makes it special" in page
    assert "Why I picked it for you" in page
    assert "Critic notes" in page
    assert 'data-status' in page
    assert "No reaction" in page
    assert "SLATE" in page and "SEALED 2026-08-24 19:30" in page
    assert "fonts.googleapis.com" in page
    assert "feedback-dock" in page


def test_killed_cards_are_audit_rows_without_feedback(con):
    make_row(con, 1, "Rejected", killed=1)
    card = render.card_of(con.execute("select * from recommendations").fetchone())
    card.update({"overview": "", "id_warning": "", "poster_file": None})

    html = render.render_killed_card(card)

    assert 'class="rejected-row"' in html
    assert "Killed" in html
    assert 'data-reaction=' not in html


def test_page_feedback_packet_uses_differentiated_reactions(con):
    make_row(con, 1, "A", rank=1, selected=True)
    card = render.card_of(con.execute("select * from recommendations").fetchone())
    card.update({"overview": "", "id_warning": ""})

    page = render.render_page([card], [], [], "ask", "2026-08-23 19:00")

    for reaction in ("start", "bookmark", "wrong_title", "weak_pitch", "seen"):
        assert f'data-reaction="{reaction}"' in page
    assert "Copy feedback for Codex / Claude" in page
    assert "media-hub-feedback-v1" in page
    assert "recommend/reclog.py --db media.db feedback --json" in page
    assert "v.reaction || 'note'" in page


def test_stars_html_renders_a_half_star():
    assert "★★★★½" in render.stars_html(4.5)
    assert "★★★★½" not in render.stars_html(4.0)
    assert render.stars_html(None) == ""
