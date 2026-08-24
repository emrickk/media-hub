#!/usr/bin/env python3
"""secrets.py: the one place media-hub reads credentials from.

Why this exists: every secret in this project used to live in
`sync-config.json` — a world-readable plaintext file, in an iCloud-synced
folder, holding Plex and Ryot tokens *and* a reused account password. Any
`git add .` would have published it, and iCloud had already replicated it
to every device on the account.

Secrets now live in `sync-config.env` (gitignored, chmod 600, never
synced anywhere deliberately). `sync-config.json` keeps only the
non-secret settings, so it stays readable and diffable.

Resolution order, first hit wins:
  1. the process environment  — for CI, one-off overrides, `KEY=… cmd`
  2. `sync-config.env`        — the normal case
  3. `sync-config.json`       — legacy fallback, warns once per key

The legacy fallback exists so nothing breaks mid-migration. It prints a
warning naming the key (never its value) so the remaining stragglers are
visible instead of silently working forever.

Usage:
    from secrets import secret, config
    token = secret("ryot_api_key")          # raises if genuinely absent
    user  = config("ryot_username", "")     # non-secret, from the json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / "sync-config.env"
JSON_PATH = HERE / "sync-config.json"

# Keys that must never sit in a committed or synced plaintext file.
SECRET_KEYS = {
    "plex_url", "plex_token",
    "ryot_url", "ryot_admin_token", "ryot_api_key", "ryot_password",
    "tmdb_api_key", "tmdb_read_token",
    "yamtrack_url", "yamtrack_password",
}

_warned: set[str] = set()


def _load_env_file() -> dict[str, str]:
    """Parse KEY=value lines. Values are taken verbatim after the first
    `=`, so tokens containing `=` (base32, JWTs) survive intact."""
    if not ENV_PATH.exists():
        return {}
    out = {}
    for line in ENV_PATH.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _load_json() -> dict:
    if not JSON_PATH.exists():
        return {}
    try:
        return json.loads(JSON_PATH.read_text("utf-8"))
    except json.JSONDecodeError:
        return {}


_ENV = _load_env_file()
_JSON = _load_json()


def secret(key: str, default: str | None = None) -> str:
    """A credential. Raises rather than returning empty — a request that
    silently goes out unauthenticated is worse than a crash."""
    for value, origin in ((os.environ.get(key), "env"),
                          (_ENV.get(key), "file")):
        if value:
            return value

    legacy = _JSON.get(key)
    if legacy:
        if key not in _warned:
            _warned.add(key)
            print(f"warning: {key} is still in sync-config.json — move it to "
                  f"{ENV_PATH.name} and rotate it; that file is plaintext and "
                  f"iCloud-synced", file=sys.stderr)
        return legacy

    if default is not None:
        return default
    raise KeyError(
        f"{key} not found. Set it in {ENV_PATH.name} (KEY=value, chmod 600) "
        f"or export it in the environment.")


def config(key: str, default=None):
    """A non-secret setting, from sync-config.json."""
    return _JSON.get(key, default)


if __name__ == "__main__":
    # Report presence only. Never prints a value.
    print(f"{'key':22} {'env':>5} {'file':>5} {'json(legacy)':>13}")
    for k in sorted(SECRET_KEYS):
        print(f"{k:22} {'yes' if os.environ.get(k) else '-':>5} "
              f"{'yes' if _ENV.get(k) else '-':>5} "
              f"{'YES' if _JSON.get(k) else '-':>13}")
    leftover = sorted(k for k in SECRET_KEYS if _JSON.get(k))
    if leftover:
        print(f"\n{len(leftover)} secret(s) still in plaintext "
              f"sync-config.json: {', '.join(leftover)}")
    else:
        print("\nno secrets left in sync-config.json")
