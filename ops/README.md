# ops/

Machine-level configuration that the system depends on but that does not
live inside the repo on a running machine.

## scheduled-tasks/

Copies of the Claude Code scheduled tasks that drive this system. The live
copies live in `~/.claude/scheduled-tasks/<name>/SKILL.md` — **these are
copies for reproducibility, not the running definitions.** Editing a file
here changes nothing until it is copied back.

| file | task | schedule |
|---|---|---|
| `monthly-recommend-digest.SKILL.md` | `monthly-recommend-digest` | `17 4 3 * *` — 04:17 on the 3rd |

`monthly-recommend-digest` runs `recommend/run_digest.sh` (harvest → upsert
→ suppress-sync → stats), then a full unattended `/recommend` digest run,
logging sealed predictions and rendering the pitch page. It is deliberately
sequenced a few days after `monthly-douban-backup` (`0 10 1 * *`, not
reproduced here — it belongs to the wider media pipeline, not this repo) so
its harvest expands from freshly refreshed anchors.

To restore on a new machine, copy the file to
`~/.claude/scheduled-tasks/monthly-recommend-digest/SKILL.md` and register
it with the same cron expression.

**This is a standing automation that writes to media.db** (`candidate_pool`
and `recommendations` only, with a backup taken first). It was registered
on 2026-08-23. Per `recommend/HANDOFF.md` §8, standing-automation changes
are the owner's call — check that it is still wanted before assuming its
presence here is an endorsement.
