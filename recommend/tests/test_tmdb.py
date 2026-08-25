import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tmdb  # noqa: E402


def test_local_bearer_token_is_loaded_without_exposing_its_value(tmp_path, capsys):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "tmdb.env").write_text("TMDB_READ_ACCESS_TOKEN=secret-token\n")

    credential = tmdb.load_credential(repo_root=tmp_path, environ={})

    assert credential.mode == "bearer"
    assert credential.value == "secret-token"
    assert credential.source.endswith("profile/tmdb.env")
    assert "secret-token" not in capsys.readouterr().out


def test_bearer_auth_uses_header_and_never_puts_secret_in_url():
    credential = tmdb.Credential("bearer", "secret-token", "test")

    request = tmdb.make_request("/authentication", credential, {"language": "en-US"})

    assert "secret-token" not in request.full_url
    assert "language=en-US" in request.full_url
    assert request.get_header("Authorization") == "Bearer secret-token"


def test_legacy_api_key_uses_v3_query_parameter():
    credential = tmdb.Credential("api_key", "legacy-key", "test")

    request = tmdb.make_request("/authentication", credential, {})

    assert "api_key=legacy-key" in request.full_url
    assert request.get_header("Authorization") is None


def test_resolver_chooses_exact_title_and_year_not_first_search_result():
    row = {"kind": "film", "title": "The Creator", "year": 2023,
           "external_ids": {}, "dossier": {"scout": {}}}
    response = {"results": [
        {"id": 11, "title": "The Creator", "original_title": "The Creator",
         "release_date": "2016-01-01", "vote_count": 9000},
        {"id": 22, "title": "The Creator", "original_title": "The Creator",
         "release_date": "2023-09-29", "vote_count": 100},
    ]}

    resolved = tmdb.resolve_row(row, search=lambda media, query: response)

    assert resolved["external_ids"] == {"tmdb_movie": "22"}
    assert resolved["dossier"]["scout"]["external_ids"] == {"tmdb_movie": "22"}


def test_resolver_fails_instead_of_guessing_when_title_and_year_do_not_match():
    row = {"kind": "tv", "title": "Human Planet", "year": 2011,
           "external_ids": {}, "dossier": {"scout": {}}}
    response = {"results": [
        {"id": 2795, "name": "GMA Network News", "original_name": "GMA Network News",
         "first_air_date": "1992-01-01", "vote_count": 5000},
    ]}

    with pytest.raises(tmdb.ResolutionError, match="Human Planet"):
        tmdb.resolve_row(row, search=lambda media, query: response)


def test_resolver_does_not_collapse_unrelated_non_latin_titles_to_empty_strings():
    row = {"kind": "film", "title": "花样年华", "year": 2000,
           "external_ids": {}, "dossier": {"scout": {}}}
    response = {"results": [
        {"id": 99, "title": "卧虎藏龙", "original_title": "卧虎藏龙",
         "release_date": "2000-01-01", "vote_count": 5000},
    ]}

    with pytest.raises(tmdb.ResolutionError, match="花样年华"):
        tmdb.resolve_row(row, search=lambda media, query: response)


def test_resolve_batch_writes_nothing_if_any_title_is_unresolved(tmp_path):
    rows = [
        {"kind": "film", "title": "Found", "year": 2020,
         "external_ids": {}, "dossier": {"scout": {}}},
        {"kind": "film", "title": "Missing", "year": 2020,
         "external_ids": {}, "dossier": {"scout": {}}},
    ]
    out = tmp_path / "resolved.json"

    with pytest.raises(tmdb.ResolutionError, match="Missing"):
        tmdb.resolve_batch(rows, search=lambda media, query: {
            "results": ([{"id": 7, "title": "Found", "original_title": "Found",
                          "release_date": "2020-01-01", "vote_count": 5}]
                        if query == "Found" else [])
        })

    assert not out.exists()
