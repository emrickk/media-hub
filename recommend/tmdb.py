#!/usr/bin/env python3
"""Small TMDB boundary used by first-run setup, identity resolution, and rendering.

Credentials are read from the process environment first, then from the local,
gitignored ``profile/tmdb.env`` file. Secrets are never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


TMDB_BASE = "https://api.themoviedb.org/3"
SETTINGS_URL = "https://www.themoviedb.org/settings/api"
UA = "llm-movie-recommendation/1.0"


@dataclass(frozen=True)
class Credential:
    mode: str
    value: str
    source: str


class CredentialError(RuntimeError):
    pass


class ResolutionError(RuntimeError):
    pass


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_credential(repo_root: Path | None = None,
                    environ: Mapping[str, str] | None = None) -> Credential | None:
    env = os.environ if environ is None else environ
    for key, mode in (("TMDB_READ_ACCESS_TOKEN", "bearer"),
                      ("TMDB_API_KEY", "api_key")):
        value = (env.get(key) or "").strip()
        if value:
            return Credential(mode, value, f"environment:{key}")

    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
    local_path = root / "profile" / "tmdb.env"
    local = _parse_env_file(local_path)
    for key, mode in (("TMDB_READ_ACCESS_TOKEN", "bearer"),
                      ("TMDB_API_KEY", "api_key")):
        value = (local.get(key) or "").strip()
        if value:
            return Credential(mode, value, str(local_path))

    # Backward compatibility for existing private installations only.
    legacy_path = root.parent / "douban-export" / "sources" / "sources.env"
    legacy = _parse_env_file(legacy_path)
    value = (legacy.get("TMDB_API_KEY") or "").strip()
    return Credential("api_key", value, str(legacy_path)) if value else None


def require_credential(repo_root: Path | None = None) -> Credential:
    credential = load_credential(repo_root=repo_root)
    if credential:
        return credential
    raise CredentialError(
        "TMDB credential is missing. Create a free API Read Access Token at "
        f"{SETTINGS_URL}, then save it in profile/tmdb.env as "
        "TMDB_READ_ACCESS_TOKEN=... (this file is gitignored).")


def make_request(path: str, credential: Credential,
                 params: Mapping[str, object] | None = None) -> urllib.request.Request:
    query = dict(params or {})
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if credential.mode == "bearer":
        headers["Authorization"] = f"Bearer {credential.value}"
    elif credential.mode == "api_key":
        query["api_key"] = credential.value
    else:
        raise CredentialError(f"unsupported TMDB credential mode: {credential.mode}")
    suffix = "?" + urllib.parse.urlencode(query) if query else ""
    return urllib.request.Request(f"{TMDB_BASE}{path}{suffix}", headers=headers)


def get_json(path: str, credential: Credential,
             params: Mapping[str, object] | None = None, timeout: int = 20) -> dict:
    request = make_request(path, credential, params)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise CredentialError(f"TMDB request failed with HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise CredentialError("TMDB request failed; check the credential and network") from None


def _norm(value: str) -> str:
    return "".join(character for character in (value or "").casefold()
                   if character.isalnum())


def _year(value: str | None) -> int | None:
    return int(value[:4]) if value and len(value) >= 4 and value[:4].isdigit() else None


def _media(row: dict) -> tuple[str, str, str]:
    if row.get("kind") in ("tv", "show", "drama"):
        return "tv", "tmdb_tv", "first_air_date"
    return "movie", "tmdb_movie", "release_date"


def resolve_row(row: dict, *, search: Callable[[str, str], dict]) -> dict:
    """Resolve one LLM-authored row without trusting the first search result."""
    if int(row.get("critic_killed") or 0):
        return json.loads(json.dumps(row))
    media, namespace, date_field = _media(row)
    title = (row.get("title") or "").strip()
    wanted_title, wanted_year = _norm(title), row.get("year")
    results = search(media, title).get("results", [])
    matches = []
    for result in results:
        names = (result.get("title"), result.get("original_title"),
                 result.get("name"), result.get("original_name"))
        if wanted_title not in {_norm(name) for name in names if name}:
            continue
        found_year = _year(result.get(date_field))
        if wanted_year is not None and found_year != int(wanted_year):
            continue
        matches.append(result)
    if not matches:
        raise ResolutionError(
            f'Could not verify "{title}" ({wanted_year or "year unknown"}) in TMDB; '
            "correct the title/year instead of guessing an id.")
    matches.sort(key=lambda result: (-int(result.get("vote_count") or 0),
                                     int(result["id"])))
    tmdb_id = str(matches[0]["id"])
    resolved = json.loads(json.dumps(row))
    resolved.setdefault("external_ids", {})[namespace] = tmdb_id
    scout = resolved.setdefault("dossier", {}).setdefault("scout", {})
    scout["external_ids"] = {namespace: tmdb_id}
    return resolved


def resolve_batch(rows: list[dict], *, search: Callable[[str, str], dict]) -> list[dict]:
    resolved, failures = [], []
    for row in rows:
        try:
            resolved.append(resolve_row(row, search=search))
        except ResolutionError as error:
            failures.append(str(error))
    if failures:
        raise ResolutionError("TMDB resolution failed; no output written:\n  - "
                              + "\n  - ".join(failures))
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate the configured TMDB credential")
    resolve = sub.add_parser("resolve", help="verify and add TMDB ids to a JSON batch")
    resolve.add_argument("--input", required=True)
    resolve.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        credential = require_credential()
        if args.command == "check":
            get_json("/authentication", credential)
            print(json.dumps({"ok": True, "mode": credential.mode,
                              "source": credential.source}))
            return

        rows = json.loads(Path(args.input).read_text("utf-8"))
        if not isinstance(rows, list):
            raise ResolutionError("resolve --input must contain a JSON list")
        batch = resolve_batch(rows, search=lambda media, query: get_json(
            f"/search/{media}", credential, {"query": query, "include_adult": "false"}))
        destination = Path(args.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(batch, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps({"ok": True, "resolved": len(batch), "out": str(destination)}))
    except (CredentialError, ResolutionError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
