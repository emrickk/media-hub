---
name: media-taste
description: Install or run this repository's chat-history-first film and TV recommendations in Codex or Claude Code. Use for short requests such as "install and recommend" as well as specific viewing asks.
---

# Media Taste

The coding agent is the runtime. Work from the cloned repository and do the
steps yourself; do not ask the user to prepare a taste profile or operate
scripts. A request to install or set up this repository and recommend something
means to complete the workflow below, not merely explain it.

## Invocation defaults

- The user does not need to name this skill, use `/recommend`, repeat the
  repository's instructions, or provide a carefully written prompt.
- Treat the current conversation as permitted evidence because the user has
  already supplied it to the running agent.
- Reading other local conversations or raw transcript files requires
  permission. If that permission is not already explicit, ask once: whether
  the agent may read locally available Codex/Claude history for this purpose
  and whether anything should be excluded. Do not split this into several
  setup questions.
- If the environment cannot expose broader history, or the user declines,
  continue with the current conversation. Ask up to the profiler's question
  budget only when the missing answer would materially change the slate.
- When no specific viewing ask was supplied, use this default intention:
  **“Recommend the films or series I am most likely to want to start or
  bookmark now.”**

## First run

1. Read `recommend/PROFILER.md`, `recommend/SCOUT.md`,
   `recommend/CRITIC.md`, and `.claude/skills/recommend/SKILL.md`.
2. Run `python3 recommend/bootstrap.py --db media.db`. It is idempotent, so do
   not burden the user with environment checks that the command can perform.
3. Apply the permission rule above. Use native conversation/task access when
   available. Ask the user for an export only as a fallback, never as the
   default installation experience.
4. Read the permitted history using `PROFILER.md`. Create the two local profile
   files it defines. Ask only load-bearing questions within its budget.
5. Run the existing scout → blind critic → log → HTML flow. On an empty
   candidate pool, record the gap and use the scout's targeted top-up path.

## Recommendation output

Preserve the critic: only selected survivors become the main 8–10 cards. Each
card must plainly say what the work is, what makes it special, why it may pull
this user in, useful things inside it, and where to start when relevant. Omit a
detail rather than inventing it. Use current web information for discovery,
posters, and third-party ratings when available. If network access is missing,
continue from reliable model knowledge and local evidence, omit unverifiable
facts, and render honest fallbacks rather than stopping.

Render the completed slate to `recommend/out/latest.html` and open it. If the
environment cannot open local HTML, give the user a clickable absolute path.

## Definition of done

The first run is done only when the user can view a finished recommendation
page. A cloned repository, initialized database, written profile, candidate
list, terminal summary, or request that the user run another command is not
completion. Report any meaningful limitations briefly after delivering the
page.

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
