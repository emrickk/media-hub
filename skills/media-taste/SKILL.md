---
name: media-taste
description: Run this repository's chat-history-first film and TV recommendation workflow in Codex or Claude Code, including rich HTML cards, feedback, and watched-history learning.
---

# Media Taste

The coding agent is the runtime. Work from the cloned repository and do the
steps yourself; do not ask the user to prepare a taste profile or operate
scripts.

## First run

1. Read `recommend/PROFILER.md`, `recommend/SCOUT.md`,
   `recommend/CRITIC.md`, and `.claude/skills/recommend/SKILL.md`.
2. Unless already authorized, confirm which locally available Codex/Claude
   conversations may be read and offer exclusions in the same sentence.
3. Run `python3 recommend/bootstrap.py --db media.db` when no local database
   exists.
4. Read the permitted history using `PROFILER.md`. Create the two local profile
   files it defines. Ask only load-bearing questions within its budget.
5. Run the existing scout → blind critic → log → HTML flow. On an empty
   candidate pool, record the gap and use the scout's targeted top-up path.

## Recommendation output

Preserve the critic: only selected survivors become the main 8–10 cards. Each
card must plainly say what the work is, what makes it special, why it may pull
this user in, useful things inside it, and where to start when relevant. Omit a
detail rather than inventing it.

## Feedback

When the user pastes a `media-hub-feedback-v1` packet, save the JSON to a
temporary file and run:

```bash
python3 recommend/reclog.py --db media.db feedback --json <packet.json>
python3 recommend/pool.py --db media.db suppress-sync
```

Update the two profile files using `PROFILER.md`. `wrong_title` suppresses the
work; `weak_pitch` does not. When the user later supplies a rating or review,
verify the exact version and record it with `mediahub.py add`; never invent an
external id.

`profile/`, `media.db`, raw history, generated HTML, covers, and credentials
remain local and must never be committed.
