# Movie recommendation runtime

This repository runs inside the coding agent. When the user asks to install,
set up, use, or recommend from this repository—including a short request such
as **“install and recommend”**—perform the complete first-run workflow.
**Do not stop** after cloning, explaining the project, initializing files, or
running tests.

1. Work from the repository root and read
   `skills/media-taste/SKILL.md` completely. Follow it as the operating
   contract; the user does not need to name the skill or use a slash command.
2. Treat the current conversation as available evidence. Before reading other
   local conversations or transcript files, get permission in one concise
   question and offer exclusions. Do not make the user locate or export
   history unless the environment cannot provide it.
3. Complete setup, profiling, scouting, blind criticism, logging, and HTML
   rendering. If the user supplied no viewing request, use the skill's default
   intention. If broader history is unavailable or declined, continue from the
   current conversation and ask only the load-bearing questions allowed by the
   profiler.
4. Open `recommend/out/latest.html` when the environment supports it;
   otherwise return a clickable absolute path. Briefly state any meaningful
   evidence or network limitations, but still produce the strongest honest
   slate possible.

Personal profiles, conversations, databases, generated pages, cover caches,
and credentials stay local. Never commit or push them.
