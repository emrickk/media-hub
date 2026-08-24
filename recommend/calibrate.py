#!/usr/bin/env python3
"""calibrate.py: the feedback -> engine-prior loop.

Why this exists: the verdict log records *that* a pitch landed or didn't.
It cannot record *why*. The why arrives as prose, in a sentence like
"these look low-rated from the poster" or "I don't start very old films" —
and until now that sentence had nowhere to live, so it was acted on once
in conversation and then lost.

This is the second half of the calibration loop the design already
committed to (spec Part B, 2026-08-23 amendment): mispredictions update
the ENGINE's priors, never the user's profile document. `TASTE.md` is the
user's own voice and is never co-edited; nothing here ever writes to it,
and nothing here should ever be shown to the user as a claim about
themselves to ratify. A prior is a statement about *the prediction
problem* — what this engine keeps getting wrong — not about the person.

    engine_priors        one row per rule, carrying the feedback that
                         produced it verbatim, the evidence, and a status
    calibrate.py active  the block the orchestrator injects into a run
    calibrate.py add     record a feedback session and its derived priors

Subcommands
-----------
    init      create the table (idempotent)
    add       record a session: --json FILE  (see SCHEMA below)
    active    print active priors, `--format prompt|json`
    list      every prior with its status and evidence
    retire    --id N --reason "..."  (never deletes; priors are an audit trail)
    check     score active priors against the verdict log

`add` batch JSON shape:
    {"session_date": "...", "feedback_verbatim": "<the user's own words>",
     "priors": [
        {"prior_key": "recency-appetite",
         "kind": "risk_flag",              # filter|risk_flag|rank_weight|target
         "statement": "<the rule the engine applies>",
         "evidence": "<verdict ids, measured rates, what would falsify it>",
         "confidence": "low|medium|high"}
     ]}
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

KINDS = {"filter", "risk_flag", "rank_weight", "target"}
CONFIDENCE = {"low", "medium", "high"}

SCHEMA = """
create table if not exists engine_priors (
    id integer primary key,
    created_at text not null,
    session_date text not null,
    feedback_verbatim text not null,
    prior_key text not null,
    kind text not null,
    statement text not null,
    evidence text not null default '',
    confidence text not null default 'low',
    status text not null default 'active',
    retired_reason text not null default '',
    updated_at text not null
);
create index if not exists idx_prior_status on engine_priors(status);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str, write: bool = False) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    if write:
        con.execute("pragma foreign_keys = on")
    return con


def cmd_init(args) -> None:
    con = connect(args.db, write=True)
    con.executescript(SCHEMA)
    con.commit()
    print(json.dumps({"ok": True, "table": "engine_priors"}))


def cmd_add(args) -> None:
    batch = json.loads(Path(args.json).read_text("utf-8"))
    feedback = (batch.get("feedback_verbatim") or "").strip()
    if not feedback:
        sys.exit("feedback_verbatim is required — a prior with no recorded "
                 "origin cannot be audited or retired on evidence later")
    priors = batch.get("priors") or []
    if not priors:
        sys.exit("no priors in batch")

    session_date = batch.get("session_date") or now()
    con = connect(args.db, write=True)
    con.executescript(SCHEMA)

    ids = []
    for p in priors:
        for field in ("prior_key", "kind", "statement"):
            if not (p.get(field) or "").strip():
                sys.exit(f"prior missing required field: {field}")
        if p["kind"] not in KINDS:
            sys.exit(f"bad kind {p['kind']!r}; expected one of {sorted(KINDS)}")
        conf = p.get("confidence", "low")
        if conf not in CONFIDENCE:
            sys.exit(f"bad confidence {conf!r}; expected {sorted(CONFIDENCE)}")

        # A repeat key supersedes rather than duplicates — priors get
        # sharper as evidence accumulates, and two live rules with the
        # same key would silently contradict each other in the prompt.
        con.execute(
            "update engine_priors set status='superseded', updated_at=? "
            "where prior_key=? and status='active'", (now(), p["prior_key"]))
        cur = con.execute(
            "insert into engine_priors (created_at, session_date, "
            "feedback_verbatim, prior_key, kind, statement, evidence, "
            "confidence, status, updated_at) "
            "values (?,?,?,?,?,?,?,?,'active',?)",
            (now(), session_date, feedback, p["prior_key"], p["kind"],
             p["statement"].strip(), (p.get("evidence") or "").strip(),
             conf, now()))
        ids.append(cur.lastrowid)
    con.commit()
    print(json.dumps({"inserted": ids, "count": len(ids)}, ensure_ascii=False))


def active_priors(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "select * from engine_priors where status='active' "
        "order by case kind when 'filter' then 0 when 'target' then 1 "
        "when 'risk_flag' then 2 else 3 end, id").fetchall()


def cmd_active(args) -> None:
    con = connect(args.db)
    con.executescript(SCHEMA)
    rows = active_priors(con)
    if args.format == "json":
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=1))
        return

    if not rows:
        print("ENGINE PRIORS: none recorded yet.")
        return

    # The prompt block. Deliberately carries the confidence and the
    # evidence: a prior stated without its strength invites the reader to
    # treat a one-session hunch as a settled rule.
    out = [
        "ENGINE PRIORS — corrections learned from this user's past reactions.",
        "",
        "These are properties of THIS ENGINE'S past mistakes, not claims about",
        "the user to be repeated back to them. Apply them; never quote them at",
        "the user as facts about their taste, and never treat one as",
        "outranking direct evidence in the candidate's own dossier.",
        "",
    ]
    for r in rows:
        out.append(f"[{r['kind']}] {r['prior_key']} (confidence: {r['confidence']})")
        out.append(f"  {r['statement']}")
        if r["evidence"]:
            out.append(f"  evidence: {r['evidence']}")
        out.append("")
    out.append("END OF ENGINE PRIORS")
    print("\n".join(out))


def cmd_list(args) -> None:
    con = connect(args.db)
    con.executescript(SCHEMA)
    rows = con.execute("select * from engine_priors order by id").fetchall()
    for r in rows:
        mark = {"active": "*", "retired": "-", "superseded": "~"}.get(r["status"], "?")
        print(f"{mark} #{r['id']:>3} [{r['kind']:<10}] {r['prior_key']:<22} "
              f"{r['confidence']:<6} {r['status']}")
        print(f"      {r['statement'][:150]}")
        if r["retired_reason"]:
            print(f"      retired: {r['retired_reason']}")
    print(f"\n{len(rows)} prior(s); "
          f"{sum(1 for r in rows if r['status']=='active')} active")


def cmd_retire(args) -> None:
    con = connect(args.db, write=True)
    con.executescript(SCHEMA)
    cur = con.execute(
        "update engine_priors set status='retired', retired_reason=?, "
        "updated_at=? where id=? and status='active'",
        (args.reason, now(), args.id))
    con.commit()
    if not cur.rowcount:
        sys.exit(f"no active prior with id {args.id}")
    print(json.dumps({"retired": args.id, "reason": args.reason},
                     ensure_ascii=False))


def cmd_check(args) -> None:
    """Score the verdict log against the shape each prior predicts.

    This is what keeps a prior honest. A rule recorded from one session
    is a hypothesis; if later verdicts stop supporting it, it should be
    retired rather than quietly compounding."""
    con = connect(args.db)
    rows = [dict(r) for r in con.execute(
        "select predicted_stars s, year y, verdict v from recommendations "
        "where verdict is not null and predicted_stars is not null")]
    if not rows:
        print("no verdicts logged yet — nothing to check priors against")
        return

    def rate(sub):
        if not sub:
            return None
        hit = sum(1 for r in sub if r["v"] in ("interested", "watched"))
        return hit, len(sub), 100.0 * hit / len(sub)

    print(f"verdicts scored: {len(rows)}\n")
    print("landing rate by predicted stars (the gate's own axis):")
    for star in sorted({r["s"] for r in rows}):
        got = rate([r for r in rows if r["s"] == star])
        print(f"  {star:>4}star  {got[0]}/{got[1]}  {got[2]:.0f}%")
    print("\nlanding rate by release era:")
    for lo, hi, lab in ((0, 2000, "pre-2000"), (2000, 2015, "2000-2014"),
                        (2015, 3000, "2015+")):
        sub = [r for r in rows if r["y"] and lo <= r["y"] < hi]
        got = rate(sub)
        if got:
            print(f"  {lab:<10} {got[0]}/{got[1]}  {got[2]:.0f}%")
    print("\nA gate that works shows a rising landing rate as predicted stars\n"
          "rise. If the top band is not the best band, the gate is ranking on\n"
          "the wrong quantity and the priors below are load-bearing.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    p = sub.add_parser("add")
    p.add_argument("--json", required=True)
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("active")
    p.add_argument("--format", choices=("prompt", "json"), default="prompt")
    p.set_defaults(func=cmd_active)

    sub.add_parser("list").set_defaults(func=cmd_list)

    p = sub.add_parser("retire")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_retire)

    sub.add_parser("check").set_defaults(func=cmd_check)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
