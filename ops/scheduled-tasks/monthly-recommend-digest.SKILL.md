---
name: monthly-recommend-digest
description: Monthly recommend-system refresh: harvest TMDB/Douban CF into the candidate pool, then produce a vetted digest of film/TV picks
---

Run Anping's monthly recommend-system digest. Execute every command yourself with the Bash tool; never hand a step list back to him. Working directory for everything: `/Users/anping/Documents/Stuff/AI Space/media-hub`.

This runs a few days after `monthly-douban-backup`, deliberately: that job refreshes media.db (new ratings, new watches), and this job's harvest expands from those fresh anchors. If media.db looks stale or that job clearly has not run this month, say so in your report rather than working around it.

**Step 1 — data refresh (one command).**
```
bash recommend/run_digest.sh
```
It harvests TMDB and Douban collaborative-filtering recommendations off Anping's ≥4.5★ anchors, upserts them into the `candidate_pool` table, runs `suppress-sync` (marking anything newly watched or previously rejected), and prints pool stats. It is idempotent and resumable — the Douban half honours a checkpoint and a politeness budget. **A Douban rate-limit stop or circuit-breaker trip is a normal outcome, not a failure**: record the checkpoint position reached and carry on. Never retry into a block or raise the request rate.

**Step 2 — produce the digest recommendation.**
Invoke the `/recommend` skill in digest mode (no ask given, so it uses `recommend/DIGEST-INTENT.md` as the ask). Follow `.claude/skills/recommend/SKILL.md` exactly — its step 0 is already satisfied by step 1 above, so continue from step 1 of that file. The essentials it will hold you to, stated here so you recognise them: take the history snapshot before any network I/O; candidates come only from the external candidate pool, never from his library; the critic runs as a genuinely separate blind subagent that must not see the scout's search; and the pitch target and cap come from `recommend/README.md`'s bindings, passed to the critic explicitly.

**Step 3 — render and log.** Follow SKILL.md's step 5 (log every candidate that reached the critic to the `recommendations` table, with sealed predictions) and step 5b (`recommend/render.py`, the pitch page). **Read `render.py`'s `id_warnings` output and report it** — it catches external ids that resolve to the wrong title, a real defect that has occurred before.

**Before the first media.db write of the run**, follow the write ritual in `recommend/README.md`: `lsof media.db*` (stop if another process holds it — several agent sessions run on this machine), check STATE.md lane ownership, `PRAGMA wal_checkpoint(TRUNCATE)`, then back up to `backups/media-recommend-<timestamp>.db`. Only `candidate_pool` and `recommendations` may be written; never touch `works`, `records` or `external_ids`.

**Report to Anping** with: the pool stats before and after, the Douban checkpoint position, the pitched candidates with their predicted stars and percentile and the specific titles from his own history that justify each, anything the critic killed and why, any `id_warnings`, and a machine-readable list of source skips or failures. Then update `STATE.md` with a dated section covering the run.

Keep the report short and lead with the picks. If nothing cleared the bar, say so plainly — an honest empty slate is a valid result and better than a padded one.