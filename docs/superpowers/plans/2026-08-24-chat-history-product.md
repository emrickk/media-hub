# Chat-history-first recommendation product — implementation plan

**Approved direction:** the coding agent is the runtime. A user gives Codex or
Claude Code this repository, permits access to selected local conversations,
and receives recommendations without first hand-writing a taste profile.

## 1. Cold start and profiling

- Add the missing `PROFILER.md` agent contract. The coding agent reads the
  locally available history directly; no separate classifier or parser. It must separate expressed
  evidence from engine inference, distinguish work context from personal
  interest, retain provenance/counterevidence/confidence, and ask questions
  only when an answer would materially change the first slate.
- Keep two human-readable local files: expressed evidence and confidence-aware
  inference. Do not build a profile database.

## 2. Universal agent entry point

- Package one repository-owned `media-taste` instruction that Codex or Claude
  Code can follow from the cloned repository.
- Make first-run, recommend, feedback, and watched/rated updates explicit
  modes of one workflow rather than unrelated commands.
- Keep personal histories, generated profiles, databases, and HTML outputs
  local and ignored by Git.

## 3. Recommendation judgment and delivery

- Preserve the existing scout and blind critic rejection gate.
- Add the appetite prediction and evidence-density/self-knowledge fields to
  the dossier/critic contracts.
- Add version-identity and honest enrichment rules so cards explain what the
  work is, what makes it special, why this user may want it, useful entry
  points, concrete inside-the-work hooks, and known risks without fabricated
  specifics.
- Render the enrichment in the production HTML, not only in experiments.

## 4. Feedback and learning

- Add a transactional rich-feedback input accepting `start`, `bookmark`,
  `wrong_title`, `weak_pitch`, and `seen` reactions plus natural-language
  notes.
- Map those reactions onto the existing verdict loop without conflating a
  bad title with a weak explanation.
- Store miss attribution and keep `wrong_title`/`seen` works out of future
  candidate pools; keep `weak_pitch` eligible for a better explanation.
- Make the HTML copy one machine-readable packet for the coding agent.

## 5. Shipping

- Replace the instance-first README entry point with a plain-language
  install/use journey while retaining the engine documentation.
- Run unit tests, skill validation, an isolated end-to-end cold-start fixture,
  and repository privacy checks.
- Commit the full branch and push it to GitHub.

## Acceptance criteria

1. An agent can read permitted Codex/Claude conversations directly and
   distill user-authored evidence without a parser or classifier layer.
2. The profiler contract can produce a persistent, provenance-backed profile
   without putting inferred claims into the user's mouth.
3. The existing critic still removes candidates before display.
4. Production cards render concrete enrichment and differentiated feedback.
5. `wrong_title` suppresses a future candidate; `weak_pitch` does not.
6. `seen` is retained as watched evidence and suppressed from future slates.
7. No personal transcript, generated profile, database, or credential enters
   the Git commit.
