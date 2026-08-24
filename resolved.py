#!/usr/bin/env python3
"""resolved.py: the computed resolved view over media.db (ARCHITECTURE §3).

records keeps one row per (source, work, status) — full provenance. Displays
want ONE answer per work. This module computes it; nothing is stored.

Rules:
  * status: the most advanced state wins across sources
    (watched > watching > owned > wishlist) — a film wishlisted on douban but
    watched on letterboxd IS watched.
  * rating / review / marked_at: from the highest-precedence source that has
    one — manual > douban > weread > letterboxd > plex > steam > psn.
    marked_at additionally prefers a source that agrees with the winning
    status (a douban 想看 date must not timestamp a letterboxd watch).
  * hours: steam + psn summed (PS4/PS5 already summed upstream);
    weread progress/hours/note-count ride along for books.
"""

from __future__ import annotations

import json

PRECEDENCE = ["manual", "douban", "weread", "letterboxd", "plex", "steam", "psn"]
ADVANCE = {"watched": 3, "watching": 2, "owned": 1, "wishlist": 0}


def _prec(source: str) -> int:
    return PRECEDENCE.index(source) if source in PRECEDENCE else len(PRECEDENCE)


def resolve_all(conn) -> dict[int, dict]:
    """work_id -> resolved facts. One pass over records."""
    by_work: dict[int, list] = {}
    for r in conn.execute(
        "SELECT work_id, source, status, rating, marked_at, review, raw FROM records"
    ):
        by_work.setdefault(r["work_id"], []).append(r)

    out: dict[int, dict] = {}
    for wid, rows in by_work.items():
        status = max(rows, key=lambda r: (ADVANCE.get(r["status"], 0), -_prec(r["source"])))["status"]
        with_status = sorted(
            (r for r in rows if r["status"] == status),
            key=lambda r: (_prec(r["source"]), r["marked_at"] or "~"),
        )
        marked = next((r["marked_at"] for r in with_status if r["marked_at"]), "")

        rated = sorted((r for r in rows if r["rating"] is not None), key=lambda r: _prec(r["source"]))
        reviewed = sorted((r for r in rows if r["review"]), key=lambda r: _prec(r["source"]))

        steam_h = psn_h = 0.0
        trophies = 0
        last_played = ""
        weread: dict = {}
        for r in rows:
            try:
                raw = json.loads(r["raw"]) if r["raw"] else {}
            except json.JSONDecodeError:
                raw = {}
            if r["source"] == "steam":
                steam_h = float(raw.get("steam_hours") or 0)
                last_played = max(last_played, str(raw.get("last_played") or ""))
            elif r["source"] == "psn":
                psn_h = float(raw.get("psn_hours") or 0)
                trophies = int(raw.get("psn_trophies") or 0)
                last_played = max(last_played, str(raw.get("last_played") or ""))
            elif r["source"] == "weread":
                weread = {
                    "progress": raw.get("weread_progress"),
                    "hours": raw.get("weread_reading_hours"),
                }

        out[wid] = {
            "status": status,
            "rating": rated[0]["rating"] if rated else None,   # 0-10
            "review": reviewed[0]["review"] if reviewed else "",
            "marked_at": marked,
            "sources": sorted({r["source"] for r in rows}, key=_prec),
            "hours": round(steam_h + psn_h, 1) if (steam_h or psn_h) else None,
            "trophies": trophies or None,
            "last_played": last_played[:10],
            "weread": weread,
        }
    return out
