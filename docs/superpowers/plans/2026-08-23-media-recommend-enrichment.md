# Enrichment & entry points — implementation plan

> **Status (2026-08-24): superseded by the lean chat-history product plan.**
> The enrichment contract and renderer were implemented, but the parked
> GTA6 acceptance run and subagent ceremony are not part of the shipped MVP.
> See `2026-08-24-chat-history-product.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-08-23-media-recommend-enrichment-design.md`
— read it first; this plan implements it and adds nothing beyond it.
**Gate:** do not start until Anping approves the spec.
**No media.db schema change anywhere in this plan.** If a task appears to
need one, stop and report — that is a design error, not an obstacle to
work around.

Working dir for all commands: the media-hub repo root.

---

## Task 1 — SCOUT.md: version-identity rule + enrichment schema

*Engine-layer prose. Wording precision is runtime correctness here.*

- [ ] In SCOUT.md's history/analogue guidance (the section governing how
  rated history is used as case law), add the **version-identity rule**:
  a rating attaches to an execution, not an IP; before citing a rated
  title in an analogy or elimination, resolve WHICH version the row is
  (year + kind + review text) and match it to the version the argument
  needs; a low rating on one version leaves other versions untested, not
  condemned. Include the general class enumeration from spec §4 (remake vs
  original, live-action vs animation, US vs regional, reboot vs
  continuation, per-season drift, adaptation vs source) and the concrete
  cautionary case: 星际牛仔 2021 Netflix remake (2.0★, 「大制作烂片」) vs
  the unrated 1998 anime.
- [ ] In SCOUT.md's dossier-schema section, add the `enrichment` block
  exactly per spec §5 — field table, the honesty contract (§3a) in full
  (basis labels, falsifiable anchors, thin-knowledge degradation, recency
  rule, spoiler discipline, quote/attribution caps), and the
  applicability rule (episodic > 1 season or > 13 episodes → `entry`
  required; films → `entry.applicable: false`).
- [ ] State the source decision in SCOUT.md where dossier evidence rules
  live: enrichment is generated from model knowledge in-session, never
  web-searched; fetched evidence remains what it already is.
- [ ] Keep every addition user-agnostic — no reference to Anping, his
  quotes, or his history anywhere in SCOUT.md.

**Verify:** re-read the two amended sections top to bottom for
contradictions with the surrounding contract (esp. the evidence-tier rules
and the ~10-network-call budget, which must be untouched).

## Task 2 — CRITIC.md: judge the enrichment

- [ ] Add enrichment to the critic's judged inputs: the new sendback
  grounds verbatim from spec §6 (no anchors; generic mush; episode-level
  specificity or quotes on a `knowledge: "thin"` work; named-source
  citation in `reception`; hook argued from category labels).
- [ ] Add the version-check duty for `history_analogues`: every analogy
  citing a rated title states its version match or flags the gap; an
  analogy resting on the wrong version is `kill_rule: fact`.
- [ ] Confirm the critic's input list needs no change (enrichment arrives
  inside dossiers.json, which it already receives) and its blindness
  rules are untouched.

**Verify:** the critic's output schema section — `outcome`, `kill_rule`,
sendback semantics — still enumerates a closed set; the new grounds must
map into existing values (`sendback`, `kill_rule: fact` /
`reason-quality`), not invent new ones.

## Task 3 — SKILL.md orchestration touchpoints

- [ ] Step 2 (scout): dossiers for shortlist finalists must each carry an
  `enrichment` block per SCOUT.md; enrichment is generated at dossier
  time, finalists only.
- [ ] Step 4 (pitch): the chat pitch includes each survivor's one-line
  entry point when `entry.applicable`.
- [ ] Step 5 needs no change (the block rides inside `dossier.scout`,
  which is already stored whole) — state this explicitly so no one
  "helpfully" adds columns.

## Task 4 — render.py: three card sections + tests

- [ ] `card_of`: lift `enrichment` from `dossier.scout` (tolerant of
  absence, like every other lifted field).
- [ ] Card template: 「从哪里开始」 (`start_at` + `why` + `exit_test`),
  「里面有什么」 (moments list; quotes styled as quotes with speaker
  attribution), reception as one muted line; a small honest marker when
  `knowledge: "thin"`. All three sections render nothing when their data
  is absent — old rows must render exactly as before.
- [ ] Tests in `recommend/tests/test_render.py`: enrichment present →
  sections appear with content; absent → card identical to pre-change
  output; `thin` marker renders; quotes render speaker attribution.
  Follow the existing test style (schema fixture + `make_row`).

**Verify:** `python3 -m pytest recommend/tests/ -q` all green;
`python3 recommend/render.py --db media.db --ids 29,30 --no-network`
renders legacy rows unchanged (visual spot-check of the HTML).

## Task 5 — acceptance test: finish the parked GTA6 run under the new contract

The parked run is the acceptance test — its slate (128-episode sitcoms,
8-season docs, a 3-episode doc, thin-knowledge candidates like 氰化欢乐秀
and 俗女养成记) exercises every rule in the spec.

- [ ] Rebuild the 8 parked dossiers (scratchpad `gta/dossiers.json`) with
  `enrichment` blocks; expect at least two to come out `knowledge: "thin"`
  and degrade honestly — if all eight claim rich knowledge, that is a red
  flag to inspect, not a success.
- [ ] Re-run the version-identity check over the parked slate's analogues
  (the Space Dandy elimination is already known-bad: re-admit it to
  shortlist consideration on its own evidence, where it lives or dies on
  the Watanabe-1998-anime question being honestly labeled a gap, not on
  the 2021 remake's score).
- [ ] Dispatch the critic per SKILL.md step 3 (now including enrichment),
  then steps 4–7 in full: pitch, log (write ritual first), render
  (`--ids`, read `id_warnings`), report with `prediction_spread` and
  `reclog.py stats`.
- [ ] In the report, list each candidate's `knowledge` level and whether
  the critic sent anything back on enrichment grounds — this is the
  spec's first field test and the result goes in STATE.md either way.

## Task 6 — closeout

- [ ] STATE.md: dated section — feedback (verbatim), spec+plan paths, the
  layer-placement correction (version rule went to engine, not priors),
  acceptance-run outcome with counts.
- [ ] `git add` the changed prose + code + docs, commit, push to
  `emrickk/media-hub` (main). No data files.
- [ ] Tests all green in the same commit.

---

## Acceptance criteria (the whole plan, judged at the end)

1. Every pitched card for an episodic work > 1 season shows a concrete,
   anchored entry point with an exit test — or an honest thin-knowledge
   fallback. Zero unfalsifiable entry claims.
2. Legacy rows render byte-identical sections (no regressions on cards
   without enrichment).
3. SCOUT.md/CRITIC.md additions contain nothing user-specific.
4. The GTA6 run completes end-to-end under the new contract and is logged,
   rendered, and reported with the standard counts.
5. No new media.db columns or tables.
