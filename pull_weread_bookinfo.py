#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.32"]
# ///
"""Backfill ISBN (and publisher/author gaps) for WeRead-sourced books.

Shelf-merged WeRead-only books have no ISBN — /web/book/info serves it
(plus publisher and author). Adapter contract as usual: raw responses to
sources/raw/weread/<date>/bookinfo-<id>.json first, resume-safe, idempotent.
E-only publications with no ISBN are recorded in meta as a documented
negative (isbn_absent=true), not retried forever.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mediahub import _attach_externals, log_run, now, open_db  # noqa: E402
from pull_weread_notes import BASE, RAW, get_json, make_session  # noqa: E402


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    conn = open_db()
    rows = conn.execute(
        """SELECT w.id AS wid, e.value AS book_id, w.title, w.creators, w.meta
           FROM works w JOIN external_ids e ON e.work_id=w.id AND e.namespace='weread'
           WHERE w.kind='book'
             AND NOT EXISTS (SELECT 1 FROM external_ids i
                             WHERE i.work_id=w.id AND i.namespace='isbn')
             AND (w.meta IS NULL OR w.meta NOT LIKE '%isbn_absent%')
           ORDER BY w.id"""
    ).fetchall()
    print(f"{len(rows)} weread books lack an isbn")
    if not rows:
        return 0
    session = make_session()

    got = absent = failures = 0
    for i, r in enumerate(rows, 1):
        raw_path = RAW / f"bookinfo-{r['book_id']}.json"
        try:
            if raw_path.exists():
                d = json.loads(raw_path.read_text(encoding="utf-8"))
            else:
                d = get_json(session, "/web/book/info", {"bookId": r["book_id"]})
                raw_path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 — keep going, circuit-break on streaks
            failures += 1
            print(f"  ! {r['title'][:24]}: {exc}")
            if failures >= 5:
                print("  ! 5 failures; stopping (resume-safe)")
                break
            continue
        failures = 0

        isbn = (d.get("isbn") or "").strip()
        meta = json.loads(r["meta"]) if r["meta"] else {}
        if isbn:
            _attach_externals(conn, r["wid"], {"isbn": isbn})
            got += 1
        else:
            meta["isbn_absent"] = True  # e-only publication, documented negative
            absent += 1
        if d.get("publisher") and not meta.get("pub_house"):
            meta["pub_house"] = d["publisher"]
        conn.execute(
            "UPDATE works SET meta=?, creators=CASE WHEN creators='' THEN ? ELSE creators END,"
            " updated_at=? WHERE id=?",
            (json.dumps(meta, ensure_ascii=False), d.get("author") or "", now(), r["wid"]),
        )
        conn.commit()
        if i % 25 == 0:
            print(f"  [{i}/{len(rows)}] +{got} isbn, {absent} e-only")

    log_run(conn, "weread-bookinfo", got, f"{absent} e-only without isbn")
    print(f"\ndone: {got} isbn attached, {absent} documented e-only, of {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
