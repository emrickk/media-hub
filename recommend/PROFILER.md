# PROFILER — read chat history into recommendation judgment

The coding agent does this work directly. Do not build a personality
classifier, keyword rules, or a questionnaire. Read the user's permitted Codex
or Claude Code conversations, make judgment calls in context, and keep only
what can improve recommendations.

## Local outputs

Create two gitignored files:

- `profile/USER.md` — only what the user actually expressed or did: direct
  statements, ratings, reactions, choices, and useful short source excerpts.
- `profile/INFERENCES.md` — the engine's hypotheses, each with confidence,
  supporting evidence, counterevidence, and what would prove it wrong.

Never put an inference in `USER.md` or repeat it back as a fact about the
person.

## How to read the history

First scan broadly to find high-information conversations. Then deeply read
the ones containing media reactions, personal interests, voluntary decisions,
recommendation corrections, or explanations of what created or destroyed
interest. Do not give every conversation equal weight.

Use this evidence order:

1. Explicit enjoyment or rejection with a reason; actual ratings and watched,
   finished, or abandoned works.
2. Repeated reactions across unrelated conversations.
3. A concrete choice or spontaneous reaction.
4. A topic the user asked about. A question shows momentary curiosity, not
   necessarily enjoyment or willingness to watch.
5. Assistant-authored claims are not evidence about the user.

Separate work context from personal interest. Employment, assigned tasks, and
technical questions may explain what the user knows without showing what they
like. Judge each claim in context; do not classify an entire thread or person.

A negative reaction attaches to the exact version, adaptation, season, or
execution discussed. It does not automatically condemn the whole IP.

## What the profile must answer

Keep the result decision-oriented:

- What kinds of works and qualities have direct positive or negative evidence?
- What makes the user start or bookmark something before watching?
- Which visual, structural, emotional, social, or practical hooks repeatedly
  matter?
- What recommendation language creates understanding, and what becomes vague
  or unpersuasive?
- Where is the evidence strong, adjacent, contradictory, or genuinely blank?

Do not write a broad personality portrait unless it changes a recommendation.

## When to stop reading and recommend

Stop when the evidence supports an honest first slate of 8–10 works containing
mostly anchored recommendations, some adjacent bets, and one or two clearly
labelled explorations. Do not wait for a complete understanding; recommend to
learn.

Ask no questions when the history is sufficient. During cold start, ask at
most three concise questions only when each answer would change several
candidates or resolve a live work-versus-life ambiguity. Never administer a
taste quiz or ask the user to ratify an engine personality claim.

## Learn after every slate

- `start` / `bookmark`: positive starting appetite, not yet a quality rating.
- `wrong_title`: diagnose a candidate-selection miss and suppress the title.
- `weak_pitch`: the title stays eligible; the delivery failed.
- `seen`: deduplication missed; retain it as watched history.
- The user's written explanation is the highest-value signal.

Append direct feedback to `USER.md`. Put derived corrections in
`INFERENCES.md` at honest confidence. Retire contradicted hypotheses instead of
silently rewriting them. On later runs, read new conversations and feedback
incrementally rather than rebuilding the profile from scratch.
