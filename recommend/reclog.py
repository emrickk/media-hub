#!/usr/bin/env python3
"""reclog.py: the recommendations log in media.db (spec Part A §A5).

The only write surface of the recommend system. Insert-and-update only —
this tool has no destructive commands by design.

`log --json` batch-row contract: each row is a JSON object. Required (all
three, non-empty — validated up front against the WHOLE batch before any
insert; a bad batch inserts nothing): `intention`, `kind`, `title`.
Optional, each defaulted if absent: `year`, `work_id` (null),
`predicted_stars`, `predicted_confidence`,
`critic_killed` (0), `kill_reason` (''), `session_date` (defaults to the
log call's own timestamp).

Every live recommendation must carry a verified TMDB identity and a complete
three-part card dossier. Killed audit rows are exempt because they are never
shown as recommendations.

STAR SCALES: `records.rating` in media.db is 0-10; `predicted_stars` here
is in STARS, 0.5-5.0 (conversion is rating/2). The two must never mix in
one field — `stats` compares `predicted_stars` against `rating/2.0`, so a
0-10 value smuggled in as `predicted_stars` silently produces a nonsense
accuracy metric. Guarded in TWO places, asymmetrically:
  * `_validate_log_rows` rejects any out-of-range `predicted_stars`
    before a single row is inserted. This is the guard that protects the
    EXISTING `recommendations` table in the real media.db.
  * the DDL carries a `CHECK` constraint, which SQLite applies only to
    tables it actually creates. `init` is `CREATE TABLE IF NOT EXISTS`
    and the live table predates the constraint, so the live table does
    NOT have it and deliberately is NOT dropped or rebuilt to acquire it
    (that would destroy logged history for a redundant guard). New
    databases get both guards; the live one is protected by the
    validator.
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from datetime import datetime, timezone
from precedence import pick_best

DDL = """
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY,
    session_date TEXT NOT NULL,
    intention TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    year INTEGER,
    external_ids TEXT NOT NULL DEFAULT '{}',
    work_id INTEGER REFERENCES works(id),
    dossier TEXT NOT NULL DEFAULT '{}',
    predicted_stars REAL CHECK (predicted_stars IS NULL
                                OR (predicted_stars >= 0.5
                                    AND predicted_stars <= 5.0)),
    predicted_confidence TEXT,
    critic_killed INTEGER NOT NULL DEFAULT 0,
    kill_reason TEXT NOT NULL DEFAULT '',
    verdict TEXT CHECK (verdict IN ('interested','no','meh','watched') OR verdict IS NULL),
    verdict_note TEXT NOT NULL DEFAULT '',
    verdict_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reco_title ON recommendations(title, year);
"""
FEEDBACK_DDL = """
CREATE TABLE IF NOT EXISTS recommendation_feedback (
    id INTEGER PRIMARY KEY,
    recommendation_id INTEGER NOT NULL REFERENCES recommendations(id),
    reaction TEXT NOT NULL CHECK (reaction IN
        ('start','bookmark','wrong_title','weak_pitch','seen','note')),
    note TEXT NOT NULL DEFAULT '',
    miss_part TEXT NOT NULL DEFAULT '' CHECK (miss_part IN
        ('','retrieval','profile-gap','judgment','axis','delivery')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_recommendation
    ON recommendation_feedback(recommendation_id);
"""
VERDICTS = ("interested", "no", "meh", "watched")
REACTIONS = {
    "start": ("interested", ""),
    "bookmark": ("interested", ""),
    "wrong_title": ("no", "judgment"),
    "weak_pitch": ("meh", "delivery"),
    "seen": ("watched", "retrieval"),
    "note": (None, ""),
}
MISS_PARTS = {"", "retrieval", "profile-gap", "judgment", "axis", "delivery"}
LOG_REQUIRED_FIELDS = ("intention", "kind", "title")
STARS_MIN, STARS_MAX = 0.5, 5.0
BUSY_TIMEOUT_MS = 15000
TMDB_NAMESPACES = ("tmdb_movie", "tmdb_tv", "tmdb")

def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    # Several agent sessions run against this DB concurrently; wait for a
    # competing writer's lock instead of erroring out immediately.
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return con

def cmd_init(con, args):
    con.executescript(DDL + FEEDBACK_DDL); con.commit()
    print("ok")

def _validate_log_rows(rows) -> list[str]:
    """Check the WHOLE batch and return one human-readable problem string
    per bad row (empty list if the batch is clean). Reports every bad row
    at once — a caller fixing five problems one traceback at a time is
    exactly the failure mode this guards against, since the batch JSON is
    LLM-assembled and a missing/blank field is a realistic, likely
    failure. Every shape this checks reached the INSERT as a bare
    traceback before: a non-object row (`AttributeError` on `.get`), a
    null `critic_killed` (`TypeError` in `int(None)`), and an
    out-of-range `predicted_stars` (no error at all — it inserted
    silently and corrupted the accuracy metric)."""
    problems = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            problems.append(f"row {i}: expected a JSON object, got "
                            f"{type(r).__name__}")
            continue
        missing = [f for f in LOG_REQUIRED_FIELDS if not r.get(f)]
        title = r.get("title")
        label = f'row {i} ("{title}")' if title else f"row {i}"
        if missing:
            problems.append(f"{label}: missing required field(s): {', '.join(missing)}")
        stars = r.get("predicted_stars")
        if stars is not None:
            try:
                value = float(stars)
            except (TypeError, ValueError):
                problems.append(f"{label}: predicted_stars must be a number "
                                f"in stars ({STARS_MIN}-{STARS_MAX}) or null, "
                                f"got {stars!r}")
            else:
                if not (STARS_MIN <= value <= STARS_MAX):
                    problems.append(
                        f"{label}: predicted_stars {value} is outside the star "
                        f"scale {STARS_MIN}-{STARS_MAX} — media.db's "
                        f"records.rating is 0-10, stars are rating/2; do not "
                        f"mix the two scales")
        killed = r.get("critic_killed")
        if killed is not None:
            try:
                int(killed)
            except (TypeError, ValueError):
                problems.append(f"{label}: critic_killed must be 0, 1, or "
                                f"absent, got {killed!r}")
        try:
            is_killed = bool(int(killed or 0))
        except (TypeError, ValueError):
            is_killed = False
        if is_killed:
            continue

        external_ids = r.get("external_ids")
        if not isinstance(external_ids, dict) or not any(
                str(external_ids.get(namespace) or "").strip()
                for namespace in TMDB_NAMESPACES):
            problems.append(
                f"{label}: live recommendations require a verified TMDB "
                "identity (tmdb_movie, tmdb_tv, or legacy tmdb)")

        dossier = r.get("dossier")
        if not isinstance(dossier, dict):
            problems.append(f"{label}: dossier must be a JSON object")
            continue
        scout = dossier.get("scout")
        enrichment = scout.get("enrichment") if isinstance(scout, dict) else None
        if not isinstance(enrichment, dict):
            problems.append(f"{label}: dossier.scout.enrichment must be a JSON object")
            continue
        for field in ("summary", "special", "personal_hook"):
            if not isinstance(enrichment.get(field), str) or not enrichment[field].strip():
                problems.append(f"{label}: enrichment.{field} must be a non-empty string")
        entry = enrichment.get("entry")
        if not isinstance(entry, dict):
            problems.append(f"{label}: enrichment.entry must be a JSON object")
        inside = enrichment.get("inside")
        if not isinstance(inside, dict):
            problems.append(f"{label}: enrichment.inside must be a JSON object")
        else:
            for field in ("moments", "quotes"):
                if not isinstance(inside.get(field), list):
                    problems.append(f"{label}: enrichment.inside.{field} must be a list")
    return problems


def _pending_duplicate_problems(con, rows) -> list[str]:
    """Reject retry-created duplicates while the original still needs feedback."""
    problems, batch_seen = [], {}
    for index, row in enumerate(rows):
        try:
            if int(row.get("critic_killed") or 0):
                continue
        except (TypeError, ValueError):
            continue
        ids = row.get("external_ids") or {}
        identity = next(((namespace, str(ids[namespace]))
                         for namespace in TMDB_NAMESPACES if ids.get(namespace)), None)
        if not identity:
            continue
        namespace, value = identity
        label = f"{namespace}:{value}"
        if label in batch_seen:
            problems.append(
                f'row {index} ("{row.get("title")}"): {label} duplicates row '
                f"{batch_seen[label]} in this batch")
            continue
        batch_seen[label] = index
        existing = con.execute(
            "SELECT id, title FROM recommendations "
            "WHERE critic_killed=0 AND verdict IS NULL "
            "AND CAST(json_extract(external_ids, ?) AS TEXT)=? LIMIT 1",
            (f"$.{namespace}", value)).fetchone()
        if existing:
            problems.append(
                f'row {index} ("{row.get("title")}"): {label} already has '
                f'a pending recommendation row #{existing["id"]} '
                f'("{existing["title"]}"); reuse it instead of logging twice')
    return problems

def cmd_log(con, args):
    rows = json.loads(open(args.json, encoding="utf-8").read())
    if not isinstance(rows, list):
        sys.exit("log --json expects a JSON list of candidate rows")
    problems = _validate_log_rows(rows)
    if not problems:
        problems.extend(_pending_duplicate_problems(con, rows))
    if problems:
        sys.exit("log --json batch failed validation, nothing inserted:\n"
                  + "\n".join(f"  - {p}" for p in problems))
    ids, ts = [], now()
    try:
        for r in rows:
            cur = con.execute(
                """INSERT INTO recommendations
                   (session_date, intention, kind, title, year, external_ids,
                    work_id, dossier, predicted_stars, predicted_confidence,
                    critic_killed, kill_reason, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r.get("session_date") or ts, r["intention"], r["kind"],
                 r["title"], r.get("year"),
                 json.dumps(r.get("external_ids", {}), ensure_ascii=False),
                 r.get("work_id"),
                 json.dumps(r.get("dossier", {}), ensure_ascii=False),
                 r.get("predicted_stars"), r.get("predicted_confidence"),
                 # `or 0`, not a get-default: an explicit JSON null must
                 # fall back to 0 too, not blow up in int(None).
                 int(r.get("critic_killed") or 0), r.get("kill_reason") or "",
                 ts, ts))
            ids.append(cur.lastrowid)
    except Exception:
        con.rollback()
        raise
    con.commit()
    print(json.dumps(ids))

def _row_out(row) -> dict:
    d = dict(row)
    for k in ("external_ids", "dossier"):
        try: d[k] = json.loads(d[k])
        except (TypeError, ValueError): pass
    return d

def cmd_check(con, args):
    if args.title and not args.year:
        sys.exit("check --title requires --year (title-only matching risks "
                  "conflating remakes/same-name works across years, which is "
                  "exactly the identity error this project guards against); "
                  "use --ext namespace:value for id-based lookup instead")
    hits, seen = [], set()
    for pair in args.ext or []:
        ns, _, val = pair.partition(":")
        for row in con.execute(
                "SELECT * FROM recommendations WHERE json_extract(external_ids, ?) = ?",
                (f"$.{ns}", val)):
            if row["id"] not in seen:
                seen.add(row["id"]); hits.append(_row_out(row))
    if args.title and args.year:
        for row in con.execute(
                "SELECT * FROM recommendations WHERE lower(title)=lower(?) AND year=?",
                (args.title, args.year)):
            if row["id"] not in seen:
                seen.add(row["id"]); hits.append(_row_out(row))
    print(json.dumps({"prior": hits}, ensure_ascii=False))

def cmd_verdict(con, args):
    cur = con.execute(
        """UPDATE recommendations
           SET verdict=?, verdict_note=?, verdict_date=?, updated_at=?
           WHERE id=?""",
        (args.verdict, args.note or "", now(), now(), args.id))
    con.commit()
    if cur.rowcount != 1:
        sys.exit(f"no recommendation row with id {args.id}")
    print("ok")


def _feedback_rows(payload):
    if isinstance(payload, list):
        return payload, ""
    if isinstance(payload, dict):
        return payload.get("feedback"), (payload.get("overall") or "").strip()
    return None, ""


def _validate_feedback(con, rows, *, allow_empty=False) -> list[str]:
    if not isinstance(rows, list):
        return ["feedback must be a non-empty list"]
    if not rows:
        return [] if allow_empty else ["feedback must be a non-empty list"]
    errors, ids = [], set()
    for index, row in enumerate(rows):
        label = f"row {index}"
        if not isinstance(row, dict):
            errors.append(f"{label}: expected a JSON object")
            continue
        rid, reaction = row.get("id"), row.get("reaction")
        if not isinstance(rid, int):
            errors.append(f"{label}: id must be an integer")
        elif rid in ids:
            errors.append(f"{label}: duplicate recommendation id {rid}")
        else:
            ids.add(rid)
            found = con.execute(
                "select critic_killed from recommendations where id=?", (rid,)
            ).fetchone()
            if found is None:
                errors.append(f"{label}: no recommendation row with id {rid}")
            elif found["critic_killed"]:
                errors.append(f"{label}: recommendation {rid} was critic-killed and never pitched")
        if reaction not in REACTIONS:
            errors.append(f"{label}: bad reaction {reaction!r}; expected one of "
                          f"{sorted(REACTIONS)}")
        miss_part = row.get("miss_part")
        if miss_part is not None and miss_part not in MISS_PARTS:
            errors.append(f"{label}: bad miss_part {miss_part!r}")
        if row.get("note") is not None and not isinstance(row.get("note"), str):
            errors.append(f"{label}: note must be a string")
    return errors


def cmd_feedback(con, args):
    """Ingest a whole HTML feedback packet transactionally.

    The legacy verdict remains the scoring/suppression interface. The richer
    reaction is stored separately so a bad title and a bad explanation never
    collapse into the same learning signal.
    """
    payload = json.loads(open(args.json, encoding="utf-8").read())
    rows, overall = _feedback_rows(payload)
    con.executescript(FEEDBACK_DDL)
    problems = _validate_feedback(con, rows, allow_empty=bool(overall))
    if problems:
        sys.exit("feedback batch failed validation, nothing recorded:\n"
                 + "\n".join(f"  - {problem}" for problem in problems))
    timestamp = now()
    try:
        for row in rows:
            reaction = row["reaction"]
            verdict, default_part = REACTIONS[reaction]
            note = (row.get("note") or "").strip()
            miss_part = row.get("miss_part")
            if miss_part is None:
                miss_part = default_part
            con.execute(
                "insert into recommendation_feedback "
                "(recommendation_id,reaction,note,miss_part,created_at) "
                "values (?,?,?,?,?)",
                (row["id"], reaction, note, miss_part, timestamp))
            if verdict is not None:
                con.execute(
                    "update recommendations set verdict=?, verdict_note=?, "
                    "verdict_date=?, updated_at=? where id=?",
                    (verdict, note, timestamp, timestamp, row["id"]))
    except Exception:
        con.rollback()
        raise
    con.commit()
    print(json.dumps({"recorded": len(rows), "overall": overall}, ensure_ascii=False))


def cmd_feedback_stats(con, args):
    con.executescript(FEEDBACK_DDL)
    by_reaction = {row["reaction"]: row["n"] for row in con.execute(
        "select reaction,count(*) n from recommendation_feedback "
        "group by reaction order by reaction")}
    by_miss_part = {row["miss_part"]: row["n"] for row in con.execute(
        "select miss_part,count(*) n from recommendation_feedback "
        "where miss_part<>'' group by miss_part order by miss_part")}
    print(json.dumps({"by_reaction": by_reaction,
                      "by_miss_part": by_miss_part}, ensure_ascii=False))

def cmd_pending(con, args):
    rows = con.execute(
        """SELECT * FROM recommendations
           WHERE critic_killed=0 AND verdict IS NULL ORDER BY id""").fetchall()
    print(json.dumps([_row_out(r) for r in rows], ensure_ascii=False))

def cmd_stats(con, args):
    # pitched/hits are plain counts over `recommendations` alone (no join to
    # records), so they were never subject to the multi-source duplication
    # defect below — each recommendation row counts exactly once already.
    pitched = con.execute(
        "SELECT count(*) FROM recommendations WHERE critic_killed=0").fetchone()[0]
    hits = con.execute(
        """SELECT count(*) FROM recommendations
           WHERE critic_killed=0 AND verdict IN ('interested','watched')""").fetchone()[0]
    # sealed_vs_actual: one entry per recommendation row (fix round 2,
    # 2026-08-23). A work watched+rated via multiple sources used to yield
    # one sealed row PER SOURCE (a plain JOIN to records) — the same defect
    # `history.py`'s `rated` had. Resolve the actual rating with the same
    # precedence via precedence.pick_best rather than a second ad hoc copy.
    candidates = con.execute(
        """SELECT id, title, predicted_stars, work_id FROM recommendations
           WHERE critic_killed=0 AND work_id IS NOT NULL
             AND predicted_stars IS NOT NULL""").fetchall()
    sealed = []
    for rec in candidates:
        rated_rows = con.execute(
            """SELECT source, rating FROM records
               WHERE work_id=? AND status='watched' AND rating IS NOT NULL""",
            (rec["work_id"],)).fetchall()
        best = pick_best(rated_rows)
        if best is None:
            continue
        sealed.append({"id": rec["id"], "title": rec["title"],
                        "predicted_stars": rec["predicted_stars"],
                        "actual_stars": best["rating"] / 2.0})
    print(json.dumps({
        "pitched": pitched, "hits": hits,
        "hit_rate": round(hits / pitched, 3) if pitched else None,
        "sealed_vs_actual": sealed,
    }, ensure_ascii=False))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("log"); s.add_argument("--json", required=True)
    s = sub.add_parser("check")
    s.add_argument("--title"); s.add_argument("--year", type=int)
    s.add_argument("--ext", action="append",
                   help="namespace:value, repeatable")
    s = sub.add_parser("verdict")
    s.add_argument("--id", type=int, required=True)
    s.add_argument("--verdict", choices=VERDICTS, required=True)
    s.add_argument("--note")
    s = sub.add_parser("feedback")
    s.add_argument("--json", required=True)
    sub.add_parser("feedback-stats")
    sub.add_parser("pending")
    sub.add_parser("stats")
    args = p.parse_args()
    con = connect(args.db)
    try:
        {"init": cmd_init, "log": cmd_log, "check": cmd_check,
         "verdict": cmd_verdict, "feedback": cmd_feedback,
         "feedback-stats": cmd_feedback_stats, "pending": cmd_pending,
         "stats": cmd_stats}[args.cmd](con, args)
    finally:
        con.close()

if __name__ == "__main__":
    main()
