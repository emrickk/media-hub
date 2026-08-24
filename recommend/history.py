#!/usr/bin/env python3
"""history.py: one-transaction read snapshot of the user's film/TV history,
plus two read-only query surfaces over that snapshot.

Spec Part A §A3 step 2: ALL media.db reads for a pipeline run happen in
`snapshot`, in one BEGIN..COMMIT, BEFORE any network I/O. The scout and
critic both work from that file, never from live queries mid-run.

Subcommands
-----------
`snapshot`  write the full snapshot JSON (needs `--db`).
`index`     one compact line per rated work — the COMPLETE map of the
            rated history, small enough to read in a single pass. The
            snapshot itself is ~900KB / ~40,000 lines and CANNOT be read
            linearly by a model without silent truncation; the index
            exists so nothing is silently missing.

            SIZE BUDGET — why the last line is a sentinel. A model's
            file read caps at 2,000 lines and returns the truncated head
            with no signal that anything was cut, which is exactly the
            failure this subcommand exists to prevent. The index is
            currently 1,717 lines (1,702 entries + 15 header lines + the
            sentinel), so it fits with ~283 lines of headroom, and it
            grows only as the user rates more works. `build_index`
            therefore ends the file with
            `# END OF INDEX — <n> entries listed above.` and CRITIC.md
            instructs the reader to treat a missing sentinel as proof of
            a truncated read. **Revisit this design once the rated count
            passes ~1,900** — at that point paginate the index, or split
            it, rather than letting it silently cross the cap. The
            sentinel converts that overrun from silent to loud; it does
            not remove the need to act on it.
`lookup`    full detail (including review text) for specific works, by
            work id / title substring / creator. Searches every section
            of the snapshot (`rated`, `wishlist`, `shells`, `rec_log`)
            and labels each hit with the section it came from, so it also
            answers dedup questions.
`distribution`  base-rate statistics over the whole rated history: one
            overall block plus a standard set of per-cell blocks (each
            kind alone, each kind split into era buckets). This is what
            lets a prediction be judged against the population it
            actually belongs to, instead of one global gate — see
            "Base rates" below for why this exists and the conventions
            it uses.
`cell`      the single cell object a candidate (`--kind` + `--year`)
            belongs to, widening to a less specific cell (and reporting
            that it did) when the specific one is too small to trust.
`percentile-of`  the mid-rank percentile of one candidate rating within
            its resolved cell — `--kind` + `--year` + `--stars`. This
            is the one call site that should ever answer "does this
            prediction clear a target"; do not hand-derive it from the
            `percentiles` ladder (see "Percentile convention" below for
            exactly why that is unsafe).
`sibling-seasons`  has the user watched/is watching/wishlisted ANY OTHER
            season (or the show-level parent) of a candidate's show?
            `--title "扑克脸" [--year 2023] [--kind tv] [--ext
            douban:35651341 ...]`, or `--batch FILE` (a JSON list of
            `{title, year, kind, external_ids}` objects) to check a whole
            shortlist in one call. See "Sibling-seasons check" below for
            why this exists and exactly what it answers.

`index`, `lookup`, `distribution`, `cell`, `percentile-of` and
`sibling-seasons` read from a snapshot FILE (`--snapshot PATH`) so they
need no DB access and stay consistent with the run's frozen snapshot.
All six also accept `--db` as a convenience, which takes a fresh
snapshot in memory first.

Sibling-seasons check
----------------------
Two live runs both overshot their time target and the dominant cost was
the same manual work: for every TV candidate, determine whether the user
has already watched a DIFFERENT season of the same show (this DB stores
TV per-season — see "Season/parent asymmetry" below — so a title can
look unwatched while its seasons are rated). There was no tool for this;
the scout stripped `第N季` by hand and grepped the whole history index
per candidate, which is slow and error-prone — and when it failed once,
three already-watched shows (Brooklyn Nine-Nine, Only Murders in the
Building, Poker Face) were pitched as fresh discoveries.

`sibling-seasons` answers exactly that one question, from a NEW
precomputed snapshot section, `season_index` (built once in `snapshot`,
so a caller checking N candidates never re-derives it): one entry per
show/season family — `base_title`, the family's real season `years`
(the same fallback-guard population as `shells`'/`suppress-sync`'s
`sibling_years`), `show_ids` (ids from each season row's `meta.show_*_id`
UNION the show-level parent row's own `external_ids`, when a parent row
sharing that exact base title exists), and `seasons` — every season/
parent row in the family with its own `status` (`"watched"` — covers
both `watched` and `watching` — `"wishlist"`, or `null`), `stars`,
`marked_at`. Built with the SAME identity primitives `shells` uses
(`_strip_season_suffix`, `_show_ids_from_meta`, `_show_identity` — see
"Season/parent asymmetry" below), not a third copy of that logic.

A query matches a family, in order (id before title — this project's
verify-before-write rule): (1) any of the candidate's own `--ext`
ids overlaps that family's `show_ids`; (2) else the candidate's title
(suffix-stripped) equals the family's `base_title` AND — same guard as
`shells` — the candidate's own year (when given) is one of that family's
real season years, so two unrelated works that merely share a title
across different years can never collide. The response reports
`watched` (true only when the matched family has at least one season/
parent row with a real status — matching the family by id or title
alone, with nobody actually watched, correctly reports `false`),
`matched_by` (`"external_id"` / `"base_title"` / `null`), the `base_title`
actually used (the candidate's own title with any `第N季` suffix
stripped), and `matching_works` (every season/parent row in the matched
family that DOES carry a status — evidence, not a bare boolean).

Base rates
----------
A live run predicted 4.0 or 4.5 for every candidate and gated on the
user's own *modal* rating (41.7% of everything he rates is 4★), which
kills nothing — 60.5% of his history is ≥4★ already. Worse, a single
global gate cannot tell a TV pitch from a 2020s film pitch apart, and
those two populations behave very differently (TV: mean 3.98, 74% ≥4;
recent film: mean 3.37, 44% ≥4). `distribution` and `cell` exist so a
prediction can be compared against the population it actually belongs
to (`cell`) or presented as "top X% for him in this category"
(`percentile_of`, below).

Only works with an actual star rating count — the 93 watched-but-never-
rated works are excluded from every statistic, same as `index` marks
them `-` rather than as a zero.

**Median convention**: sort the cell's star values; odd n takes the
middle value, even n averages the two middle values (the standard
convention — NOT the nearest-rank convention below, so `median` and
`percentiles["50"]` can legitimately differ by a tie-break on even n).

**Percentile convention — mid-rank (average-rank), NOT "at or below".**
This is the single most load-bearing convention in this module and MUST
NOT be "simplified" back to `count(<= star) / n`. His ratings are lumpy
whole/half stars, so every real prediction lands inside a wide tie band
rather than at a clean boundary — e.g. for films released 2020-26, every
4★ rating (his single most common value in that cell) occupies the
56.2nd-to-93.3rd percentile band. A naive "at or below" score reports
whichever prediction lands at the *top* of its own tie band — 93.3 for
that whole band — which clears almost any gate and silently reintroduces
the exact soft gate this rework exists to remove (a live run that only
ever predicted 4.0/4.5 and never used the bottom two-thirds of the
scale). Mid-rank instead credits a tied value with *half* its own band,
crediting `4★` at 74.8 in that same cell — an honest read of where a 4★
film actually sits for him, not an artificially inflated one.

`percentile_of(star, cell)` = `100 * (count_below + count_equal / 2) / n`
— every work strictly below `star` counts fully, every work tied with it
counts for half, works above count for nothing. Returns `None` for a
cell with zero rated works.

**`percentiles` (the ladder) and `percentile_of` are NOT exact inverses
of each other — a real reader WILL misread the ladder as a gate, so this
has to be unmistakable, not a footnote.** `percentiles[P]` is built by
searching for the smallest star value `v` with `percentile_of(v, cell)
>= P`, clamping to the maximum star value present if none reaches P.
That construction guarantees only a ONE-WAY, conditional fact: every
star value *strictly below* `percentiles[P]` has a mid-rank score under
P. It does NOT guarantee `percentile_of(percentiles[P], cell) >= P` —
that direction fails exactly when the clamp fires, and the clamp is not
a rare corner case, it is forced by the scale's own ceiling. On the
`tv/show` cell (real DB, all years), 31.1% of works are rated 5★ — the
top of the scale, nothing can outrank it — so 5★'s own mid-rank score
tops out at `100 − 31.1/2 ≈ 84.4` no matter what the rest of the
distribution looks like, and `percentiles["90"]`/`["95"]` both clamp to
5★ while that clamped value's own score (84.4) never reaches either
label. Read casually, `percentiles["90"] == 5.0` looks like "a 5★ rating
clears a 90 target" — it does not; `percentile_of(5.0, cell)` says 84.4.
This is why the two CANNOT be made into exact inverses without either
(a) inventing a star value above 5.0 to report, which does not exist, or
(b) going back to the naive "at or below" convention this module
deliberately rejects (§ above) — so the module keeps the mid-rank ladder
and documents the gap instead of pretending it away. Both `overall` and
every cell carry a `percentiles_note` field stating this in the JSON
itself (see `PERCENTILES_NOTE`), specifically so a caller reading only
the JSON — not this docstring — still gets the warning.

**The rule that follows from this**: `percentiles` is orientation only —
"roughly where in the scale does this population's ratings sit", useful
for a human skimming a cell. It is never a substitute for a real
threshold check. Any code (or LLM) deciding "does candidate rating X
clear a target" MUST call `percentile_of(X, cell)` (or the
`percentile-of` CLI subcommand) directly — never look up a ladder value
and reason backward from it, and never assume a ladder rank and a
`percentile_of` score at the same star value must match.

What the correct (`percentile_of`-based) score buys: the SAME predicted
star means something different in different populations. A predicted 4★
film sits at percentile_of ≈ 74.8 in the film-2020-26 cell — genuinely
notable, since only ~44% of recent films he rates clear 4★ at all. The
identical 4★ prediction for a TV series sits at ≈ 46.7 in the tv/show
cell — unremarkable, since 74% of series clear 4★ and a third earn a
full 5★. Same number, opposite verdict; that's the whole point of
grading against the right population — and it is `percentile_of`, not
`percentiles`, that delivers it correctly in every case, clamp or not.

**Cell fallback rule** (`cell` subcommand): a base rate computed from a
handful of works looks exactly as authoritative as one computed from
hundreds and is far more likely to be noise. If the most specific cell
(kind + era) has fewer than `LOW_N_THRESHOLD` (30) rated works, widen
to the kind alone (drop the era); if that is still under threshold,
widen to the overall population (drop the kind too). Either widening
sets `fallback_used: true` and a `fallback_note` naming what was
dropped and why. `distribution`'s cells are never dropped for low n —
they are marked `low_n: true` instead, so a thin cell stays visible as
a stated risk rather than disappearing silently (spec: "suppress or
mark", chosen: mark).

Section meanings
----------------
`rated`     one entry per work with a watched/watching record; multi-
            source disagreement stays visible in `rating_variants`.
`wishlist`  works with a `wishlist` record.
`shells`    works in scope with NO watch/wish record at all — i.e. no
            `watched`, `watching`, or `wishlist` row in `records`, AND no
            SIBLING season/parent row that does (see "Season/parent
            asymmetry" below). In practice these are overwhelmingly
            library-present-but-unwatched titles, but "library presence"
            is NOT what the query asserts and is not true of all of
            them. Describe them accurately as "no watch/wish record",
            never as "owned".
            Shell entries carry `external_ids` just as `rated` and
            `wishlist` entries do. These are STORED ids that were
            verified at source when they were loaded, so a consumer may
            use them directly — reading them here is reading the
            database, not recalling an id from memory, and the project's
            verify-before-you-write rule is satisfied. A shell whose
            `external_ids` comes back empty must have its identity
            resolved at source like any other newly found candidate.
`rec_log`   prior recommendations from the `recommendations` table.

Season/parent asymmetry (fix, 2026-08-23)
------------------------------------------
TV in this DB is season-level canon: one `kind='tv'` row per Douban/NeoDB
season, PLUS a `kind='show'` row for the series as a whole
(ARCHITECTURE.md §3, "TV is season-level canon"). The `show` row never
carries its own watched/watching/wishlist record — the user rates each
season, not the series — so a shells query keyed on "no record for THIS
work id" alone falsely listed a `show` row as unwatched for every series
watched season-by-season (measured: 62 of 222 shells, 28%, e.g. 神探夏洛克
watched S1-S3, listed as a shell anyway), and would falsely list a not-
yet-watched SEASON as a shell too if its siblings had been watched.

Fixed by excluding a candidate when it shares "show identity" with a
watched/watching/wishlisted season, checked two ways, id first (stronger
evidence, per this project's verify-before-you-write rule):
  1. **id overlap.** A season row's OWN `external_ids` never carries the
     show-level tmdb/imdb id — that lives in `meta.show_tmdb_id` /
     `show_imdb_id` instead, deliberately kept out of `external_ids` so
     seasons don't cross-link (the "season-tt gotcha", ARCHITECTURE.md
     §9). Those `meta` ids are exactly the ids the show-level parent row
     DOES carry in its own `external_ids`, so a parent-vs-season id
     match is `parent.external_ids ∩ meta(season).show_*_id`.
  2. **base-title fallback**, for the (common) case where the parent row
     carries no ids of its own: strip a `第N季` suffix (N = digits or
     Chinese numerals) to get the base title, and match a candidate's
     base title against the base title of any watched/wishlisted season.
     This is GATED so it can never collapse two unrelated works that
     merely share a title (e.g. an unrelated remake from a different
     year): the match only fires when a real season family — at least
     one `season_number IS NOT NULL` row sharing that exact base title —
     actually exists, AND the candidate's own year (when it has one) is
     one of that family's real season years. A base title with no
     season family behind it, or a year outside the family's actual
     years, never matches on title alone.
Deliberately NOT keyed on `kind` matching, since the two sides of a real
pair differ in kind (`show` parent vs `tv` season) by design.

Verified against the real DB (2026-08-23): 65 of the 222 pre-fix shells
excluded (157 remain), 3 more than the 62 first spotted by eye — the
extra 3 (Gravity Falls/怪诞小镇, Rick and Morty/瑞克和莫蒂, Love Death &
Robots/爱，死亡和机器人) are Plex-sourced `show` rows carrying the
show's ENGLISH title, matched to their Chinese-titled Douban season
family only via id overlap — exactly the case the base-title fallback
alone could never have caught, confirming id-first evidence pulls its
own weight here, not just as a documented fallback order. All 65
verified to have an actual watched/watching/wishlisted sibling season;
zero suspected over-exclusions.
"""
from __future__ import annotations
import argparse, json, re, sqlite3, sys
from collections import Counter
from datetime import datetime, timezone
from precedence import pick_best

DEFAULT_KINDS = ("film", "tv", "show", "drama")
BUSY_TIMEOUT_MS = 15000
INDEX_SECTION = "rated"

# --------------------------------------------------- season/parent identity
#
# See the module docstring's "Season/parent asymmetry" section for why this
# exists. Shared shape used by both the id-overlap check and the base-title
# fallback in `snapshot`'s `shells` construction.

SEASON_SUFFIX_RE = re.compile(r"^(.*?)\s*第[0-9一二三四五六七八九十百]+季$")

def _strip_season_suffix(title: str | None) -> str | None:
    """Base title with a trailing `第N季` suffix removed (N = digits or
    Chinese numerals), or None if `title` carries no such suffix — e.g.
    "真相捕捉 第三季" -> "真相捕捉". Season rows in this DB always carry
    this suffix; a show-level parent row never does."""
    if not title:
        return None
    m = SEASON_SUFFIX_RE.match(title.strip())
    if not m:
        return None
    base = m.group(1).strip()
    return base or None

def _show_ids_from_meta(meta_json: str | None) -> set[tuple[str, str]]:
    """The show-level ids a SEASON row carries in `meta` — never in its
    own `external_ids` (the season-tt gotcha, ARCHITECTURE.md §9), so a
    plain external_ids join can't see this relationship. Namespaces
    (`tmdb_tv`, `imdb`) match what the show-level PARENT row's own
    `external_ids` use, so the two sides are directly comparable."""
    if not meta_json:
        return set()
    try:
        meta = json.loads(meta_json)
    except (TypeError, ValueError):
        return set()
    if not isinstance(meta, dict):
        return set()
    ids = set()
    if meta.get("show_tmdb_id"):
        ids.add(("tmdb_tv", str(meta["show_tmdb_id"])))
    if meta.get("show_imdb_id"):
        ids.add(("imdb", str(meta["show_imdb_id"])))
    return ids

def _show_identity(title: str, season_number, meta_json, own_ext: dict):
    """(base_title_or_None, show_ids) for one work, used to compare a
    candidate against the watched/wishlisted season index built in
    `snapshot`. A season row's base is its title with the suffix
    stripped and its ids come from `meta`; a parent/standalone row's
    base is its own title as-is and its ids are its own `external_ids`
    (those ARE the show-level ids for a parent row)."""
    if season_number is not None:
        return _strip_season_suffix(title), _show_ids_from_meta(meta_json)
    return title, set(own_ext.items())

def _rated_entries(con, ph, kinds, ext) -> list[dict]:
    """One entry per work_id, collapsing every watched/watching record for
    that work across sources per precedence.SOURCE_PRECEDENCE. Disagreements
    across sources stay visible via `rating_variants` rather than being
    silently resolved. `status` is selected so that a SAME-SOURCE tie
    (one source holding both a watched and a watching row — permitted by
    `UNIQUE(source, work_id, status)`) resolves deterministically instead
    of by cursor order; see precedence.pick_best."""
    groups: dict[int, dict] = {}
    order: list[int] = []
    for r in con.execute(f"""
        SELECT w.id AS work_id, w.kind, w.title, w.original_title, w.year,
               w.creators,
               rec.rating, rec.review, rec.marked_at, rec.source, rec.status
        FROM records rec JOIN works w ON w.id = rec.work_id
        WHERE w.kind IN ({ph}) AND rec.status IN ('watched','watching')
        ORDER BY w.id""", kinds):
        wid = r["work_id"]
        if wid not in groups:
            groups[wid] = {"meta": r, "rows": []}
            order.append(wid)
        groups[wid]["rows"].append(r)

    entries = []
    for wid in order:
        meta = groups[wid]["meta"]
        rows = groups[wid]["rows"]
        rated_rows = [r for r in rows if r["rating"] is not None]
        reviewed_rows = [r for r in rows if r["review"]]
        marked_values = [r["marked_at"] for r in rows if r["marked_at"]]

        best_rating_row = pick_best(rated_rows)
        best_review_row = pick_best(reviewed_rows)

        if best_rating_row is not None:
            stars = best_rating_row["rating"] / 2
            source = best_rating_row["source"]
        else:
            stars = None
            source = pick_best(rows)["source"]

        review = best_review_row["review"] if best_review_row is not None else ""
        marked_at = max(marked_values) if marked_values else ""

        # One rating per SOURCE, chosen by the same precedence rather than
        # by cursor order — `setdefault` used to hide a source's second
        # (watched vs watching) rating from `rating_variants` entirely.
        rows_by_source: dict[str, list] = {}
        for r in rated_rows:
            rows_by_source.setdefault(r["source"], []).append(r)
        ratings_by_source = {src: pick_best(srows)["rating"] / 2
                             for src, srows in rows_by_source.items()}

        entry = dict(work_id=wid, kind=meta["kind"], title=meta["title"],
                     original_title=meta["original_title"], year=meta["year"],
                     creators=meta["creators"] or "",
                     stars=stars, review=review, marked_at=marked_at,
                     source=source, sources=sorted({r["source"] for r in rows}),
                     external_ids=ext.get(wid, {}))
        if len(set(ratings_by_source.values())) >= 2:
            entry["rating_variants"] = ratings_by_source
        entries.append(entry)

    # marked_at DESC, then work_id ASC — two stable passes (ascending id
    # first so ties on marked_at keep id order, same as the old SQL ORDER BY).
    entries.sort(key=lambda e: e["work_id"])
    entries.sort(key=lambda e: e["marked_at"], reverse=True)
    return entries

def _season_index(con, ph, kinds, ext, rated, wishlist) -> list[dict]:
    """The `season_index` snapshot section powering `sibling-seasons` —
    see the module docstring's "Sibling-seasons check". One entry per
    show/season family (base title after `第N季` stripping), built with
    the SAME identity primitives `shells` uses (`_show_identity`,
    `_strip_season_suffix`, `_show_ids_from_meta`) rather than a third
    copy of that logic. `rated`/`wishlist` (already computed by the time
    this runs) are indexed by work_id to attach each family member's
    watch status/stars/marked_at without a further DB round trip."""
    rated_by_id = {e["work_id"]: e for e in rated}
    wishlist_ids = {w["work_id"] for w in wishlist}

    season_rows = con.execute(f"""
        SELECT id AS work_id, kind, title, year, season_number, meta
        FROM works
        WHERE kind IN ({ph}) AND season_number IS NOT NULL""", kinds).fetchall()

    families: dict[str, dict] = {}
    for r in season_rows:
        base, ids = _show_identity(r["title"], r["season_number"], r["meta"], {})
        if not base:
            continue
        fam = families.setdefault(
            base, {"base_title": base, "years": set(), "ids": set(), "rows": []})
        if r["year"] is not None:
            fam["years"].add(r["year"])
        fam["ids"] |= ids
        fam["rows"].append(r)

    if families:
        ph2 = ",".join("?" for _ in families)
        parent_rows = con.execute(f"""
            SELECT id AS work_id, kind, title, year, season_number
            FROM works
            WHERE kind IN ({ph}) AND season_number IS NULL
              AND title IN ({ph2})""", (*kinds, *families)).fetchall()
        for r in parent_rows:
            fam = families[r["title"]]
            own_ext = ext.get(r["work_id"], {})
            base, ids = _show_identity(r["title"], r["season_number"], None, own_ext)
            fam["rows"].append(r)
            fam["ids"] |= ids
            if r["year"] is not None:
                fam["years"].add(r["year"])

    out = []
    for base, fam in families.items():
        seasons = []
        for r in fam["rows"]:
            wid = r["work_id"]
            rated_entry = rated_by_id.get(wid)
            if rated_entry is not None:
                status = "watched"
                stars, marked_at = rated_entry["stars"], rated_entry["marked_at"]
            elif wid in wishlist_ids:
                status, stars, marked_at = "wishlist", None, None
            else:
                status, stars, marked_at = None, None, None
            seasons.append(dict(work_id=wid, kind=r["kind"], title=r["title"],
                                season_number=r["season_number"], year=r["year"],
                                status=status, stars=stars, marked_at=marked_at,
                                external_ids=ext.get(wid, {})))
        out.append(dict(base_title=base,
                        years=sorted(y for y in fam["years"] if y is not None),
                        show_ids=sorted(fam["ids"]), seasons=seasons))
    return out

def snapshot(con: sqlite3.Connection, kinds) -> dict:
    con.row_factory = sqlite3.Row
    ph = ",".join("?" for _ in kinds)
    con.execute("BEGIN")
    ext = {}
    for r in con.execute(f"""SELECT e.work_id, e.namespace, e.value
                             FROM external_ids e JOIN works w ON w.id=e.work_id
                             WHERE w.kind IN ({ph})""", kinds):
        ext.setdefault(r["work_id"], {})[r["namespace"]] = r["value"]
    rated = _rated_entries(con, ph, kinds, ext)
    wishlist = [dict(work_id=r["work_id"], kind=r["kind"], title=r["title"],
                     year=r["year"], creators=r["creators"] or "",
                     external_ids=ext.get(r["work_id"], {}))
                for r in con.execute(f"""
        SELECT DISTINCT w.id AS work_id, w.kind, w.title, w.year, w.creators
        FROM records rec JOIN works w ON w.id = rec.work_id
        WHERE w.kind IN ({ph}) AND rec.status = 'wishlist'
        ORDER BY w.id""", kinds)]
    # shells = works with NO watch/wish record at all — deliberately NOT
    # joined to records (fix round 1, 2026-08-23): a true shell can have
    # zero records rows, so joining records could only ever return
    # nothing. See the module docstring for what `shells` does and does
    # not assert about library presence.
    #
    # Season/parent asymmetry fix (2026-08-23, see module docstring):
    # a candidate with no record of its own is still excluded from
    # `shells` when a SIBLING season/parent row shares its show identity
    # and DOES have a watched/watching/wishlist record.
    watched_season_rows = con.execute(f"""
        SELECT DISTINCT w.title, w.season_number, w.meta
        FROM works w JOIN records rec ON rec.work_id = w.id
        WHERE w.kind IN ({ph}) AND rec.status IN ('watched','watching','wishlist')
          AND w.season_number IS NOT NULL""", kinds).fetchall()
    watched_show_titles: set[str] = set()
    watched_show_ids: set[tuple[str, str]] = set()
    for r in watched_season_rows:
        base = _strip_season_suffix(r["title"])
        if base:
            watched_show_titles.add(base)
        watched_show_ids |= _show_ids_from_meta(r["meta"])

    # The real season family (regardless of watch status) for every base
    # title — the guard that stops the base-title fallback from ever
    # collapsing two unrelated same-titled works: a title only matches if
    # a genuine season family exists for it AND the candidate's own year
    # (when present) is one of that family's real years.
    sibling_years: dict[str, set] = {}
    for r in con.execute(f"""
        SELECT title, year FROM works
        WHERE kind IN ({ph}) AND season_number IS NOT NULL""", kinds):
        base = _strip_season_suffix(r["title"])
        if base:
            sibling_years.setdefault(base, set()).add(r["year"])

    shells = []
    for r in con.execute(f"""
        SELECT w.id AS work_id, w.kind, w.title, w.year, w.season_number,
               w.meta, COALESCE(w.creators,'') AS creators
        FROM works w
        WHERE w.kind IN ({ph})
          AND w.id NOT IN (SELECT work_id FROM records
                           WHERE status IN ('watched','watching','wishlist'))
        ORDER BY w.id""", kinds):
        own_ext = ext.get(r["work_id"], {})
        base, own_ids = _show_identity(r["title"], r["season_number"],
                                       r["meta"], own_ext)
        id_match = bool(own_ids & watched_show_ids)
        title_match = False
        if not id_match and base and base in watched_show_titles:
            family_years = sibling_years.get(base)
            title_match = bool(family_years) and \
                (r["year"] is None or r["year"] in family_years)
        if id_match or title_match:
            continue
        shells.append(dict(work_id=r["work_id"], kind=r["kind"],
                           title=r["title"], year=r["year"],
                           creators=r["creators"], external_ids=own_ext))
    rec_log = [dict(id=r["id"], title=r["title"], year=r["year"],
                    kind=r["kind"],
                    external_ids=json.loads(r["external_ids"] or "{}"),
                    critic_killed=r["critic_killed"], verdict=r["verdict"])
               for r in con.execute("SELECT * FROM recommendations ORDER BY id")]
    season_index = _season_index(con, ph, kinds, ext, rated, wishlist)
    con.execute("COMMIT")
    return {
        "generated_at": datetime.now(timezone.utc).astimezone()
                        .isoformat(timespec="seconds"),
        "kinds": list(kinds),
        "rated": rated, "wishlist": wishlist, "shells": shells,
        "rec_log": rec_log, "season_index": season_index,
        "counts": {"rated": len(rated), "wishlist": len(wishlist),
                   "shells": len(shells), "rec_log": len(rec_log)},
    }

# ---------------------------------------------------------------- index

INDEX_HEADER = """\
# HISTORY INDEX — the COMPLETE list of rated works in this snapshot.
# Generated {generated_at} from {origin}; kinds: {kinds}
# Entries below: {n} (one line per rated work; nothing is omitted or sampled)
# Columns:  work_id | stars | R | year | title [<< original_title]
#   stars  the user's own rating, 0.5-5.0; "-" = watched but never rated
#   R      "R" = this work has review text (pull it with `lookup`);
#          "." = no review text
# Detail (review text, creators, ids, per-source ratings) is NOT here.
# Get it with:
#   python3 recommend/history.py lookup --snapshot <snap.json> --work-id N
#   python3 recommend/history.py lookup --snapshot <snap.json> --title "sub"
# The last line of this file is an END-OF-INDEX marker naming the entry
# count. If you do not see it, your read was TRUNCATED and you have only
# part of the history — re-read from an offset until you reach it.
"""

def build_index(data: dict, origin: str = "snapshot") -> str:
    entries = data.get(INDEX_SECTION, [])
    lines = [INDEX_HEADER.format(
        generated_at=data.get("generated_at", "?"), origin=origin,
        kinds=",".join(data.get("kinds", [])) or "?",
        n=len(entries)).rstrip("\n")]
    for e in entries:
        stars = f"{e['stars']:.1f}" if e.get("stars") is not None else "-"
        year = e.get("year")
        title = e.get("title") or ""
        orig = e.get("original_title") or ""
        line = (f"{e['work_id']:>6} {stars:>4} {'R' if e.get('review') else '.'} "
                f"{year if year is not None else '????':>4}  {title}")
        if orig and orig != title:
            line += f"  << {orig}"
        lines.append(line)
    lines.append(f"# END OF INDEX — {len(entries)} entries listed above.")
    return "\n".join(lines) + "\n"

# --------------------------------------------------------------- lookup

LOOKUP_SECTIONS = ("rated", "wishlist", "shells", "rec_log")

def lookup(data: dict, work_ids=(), titles=(), creators=()) -> list[dict]:
    """Return full snapshot entries matching ANY of the given filters,
    each tagged with the section it came from. Title and creator matching
    is case-insensitive substring matching, applied to `title`,
    `original_title` and `creators`. Results are deduped by
    (section, work_id/id) and returned in section order."""
    wanted_ids = {int(w) for w in work_ids}
    subs = [t.lower() for t in titles if t]
    creator_subs = [c.lower() for c in creators if c]
    hits, seen = [], set()
    for section in LOOKUP_SECTIONS:
        for entry in data.get(section, []):
            key = (section, entry.get("work_id", entry.get("id")))
            if key in seen:
                continue
            ident = entry.get("work_id")
            if ident is None and section == "rec_log":
                ident = entry.get("id")
            match = ident is not None and ident in wanted_ids
            if not match and subs:
                hay = f"{entry.get('title') or ''}\n{entry.get('original_title') or ''}".lower()
                match = any(s in hay for s in subs)
            if not match and creator_subs:
                hay = (entry.get("creators") or "").lower()
                match = bool(hay) and any(c in hay for c in creator_subs)
            if match:
                seen.add(key)
                hits.append(dict(entry, section=section))
    return hits

# ------------------------------------------------------------- base rates

# Kind grouping used by both `distribution` and `cell`: film stands alone;
# `show` pools with `tv` (same "episodic thing watched over time"
# population, and `show` is a vanishingly rare kind in this DB — 8 works
# at time of writing — too thin to model separately). `drama` does NOT
# pool with either: in this schema `kind='drama'` means live theatre
# (话剧), a different medium with different viewing/rating behaviour, not
# "TV drama" — a category error that happened to be statistically
# invisible while n=1 (coordinator ruling, 2026-08-23, work #346 乌龙山
# 伯爵). It gets its own (near-certainly `low_n`) cell instead, and the
# fallback ladder already handles a near-empty kind with no special-
# casing needed.
KIND_GROUPS = {"film": ("film",), "tv/show": ("tv", "show"), "drama": ("drama",)}
KIND_ALIASES = {k: group for group, kinds in KIND_GROUPS.items() for k in kinds}

# Era buckets, fixed except the current one, which runs from 2020 through
# whatever "now" is (matches the exact cell a fresh candidate needs: e.g.
# "film 2020-2026" today). `year_from`/`year_to` are inclusive; None means
# unbounded on that side.
def _era_buckets(ref_year: int):
    return [
        ("pre-2000", None, 1999),
        ("2000-2009", 2000, 2009),
        ("2010-2019", 2010, 2019),
        (f"2020-{ref_year}", 2020, ref_year),
    ]

PERCENTILE_RANKS = (50, 70, 80, 90, 95)
LOW_N_THRESHOLD = 30

# Carried in the JSON itself (every `overall`/cell block) so the caveat
# survives even when a caller only ever reads the data, not this
# docstring. See "Percentile convention" above for the full argument and
# the worked tv/show 90/95 clamp example.
PERCENTILES_NOTE = (
    "Orientation only, NOT a gate. percentiles[P] is the smallest star "
    "value whose own mid-rank score clears P, clamped to the max star "
    "value when none does — it does not guarantee percentile_of(that "
    "value, cell) >= P (a heavy top tie forces the clamp; see the "
    "module docstring). To check whether a specific candidate rating "
    "clears a target, call percentile_of(stars, cell) directly (or the "
    "`percentile-of` CLI subcommand) — never read a threshold off this "
    "ladder.")

def _year_in_range(year, year_from, year_to) -> bool:
    if year is None:
        return False
    if year_from is not None and year < year_from:
        return False
    if year_to is not None and year > year_to:
        return False
    return True

def _median(values_sorted: list[float]) -> float | None:
    """Standard median: odd n takes the middle value, even n averages the
    two middle values. See the module docstring for why this can differ
    from `percentiles["50"]`, which uses the mid-rank convention."""
    n = len(values_sorted)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return values_sorted[mid]
    return (values_sorted[mid - 1] + values_sorted[mid]) / 2

def _mid_rank_scores(values_sorted: list[float]) -> list[tuple]:
    """(value, mid-rank percentile) pairs, one per DISTINCT value, ascending.
    mid-rank percentile of `v` = 100 * (count strictly below v + count
    equal to v / 2) / n — the same formula `percentile_of` uses (see the
    module docstring's "Percentile convention"). Shared by `_percentiles`
    (the ladder) and `percentile_of` so the two can never disagree about
    the same cell."""
    n = len(values_sorted)
    counts = Counter(values_sorted)
    scored, below = [], 0
    for v in sorted(counts):
        equal = counts[v]
        scored.append((v, 100 * (below + equal / 2) / n))
        below += equal
    return scored

def _percentiles(values_sorted: list[float], ranks=PERCENTILE_RANKS) -> dict:
    """Mid-rank percentile LADDER — orientation only, NOT an exact inverse
    of `percentile_of` and NOT a gate; see the module docstring's
    "Percentile convention" for the full rationale, including the real
    tv/show cell where this bites. `percentiles[P]` is the smallest star
    value `v` with `percentile_of(v, cell) >= P`; if no value reaches P
    (one tie dominates the top of the distribution — always possible
    near the 5★ ceiling, since nothing can outscore the maximum), clamps
    to the maximum value present. In that clamped case
    `percentile_of(percentiles[P], cell)` can legitimately fall short of
    P — do not "fix" that by re-deriving a threshold from this ladder;
    call `percentile_of` directly for any real threshold check."""
    n = len(values_sorted)
    if n == 0:
        return {str(r): None for r in ranks}
    scored = _mid_rank_scores(values_sorted)
    out = {}
    for r in ranks:
        out[str(r)] = next((v for v, score in scored if score >= r),
                           scored[-1][0])
    return out

def _histogram(values: list[float]) -> dict:
    counts = Counter(values)
    return {f"{v:.1f}": counts[v] for v in sorted(counts)}

def _stats_block(values: list[float]) -> dict:
    """The shared statistics payload for `overall` and for every cell:
    n, mean, median, pct_ge4, pct_5, histogram, percentiles,
    percentiles_note. Percentages are rounded to one decimal place; mean
    is rounded to 3 decimal places (enough precision to not be "rounded
    to death" per the brief, since stars are half-integers and small n
    makes coarser rounding lossy). `percentiles_note` (see
    `PERCENTILES_NOTE`) is the same fixed string on every block — it
    exists so the ladder-vs-`percentile_of` caveat travels with the data
    itself, not just this module's docstring. Handles n == 0 without
    dividing by zero — every numeric field comes back None and
    histogram/percentiles come back empty/all-None."""
    values_sorted = sorted(values)
    n = len(values_sorted)
    if n == 0:
        return {"n": 0, "mean": None, "median": None,
                "pct_ge4": None, "pct_5": None,
                "histogram": {}, "percentiles": _percentiles([]),
                "percentiles_note": PERCENTILES_NOTE}
    return {
        "n": n,
        "mean": round(sum(values_sorted) / n, 3),
        "median": _median(values_sorted),
        "pct_ge4": round(100 * sum(1 for v in values_sorted if v >= 4) / n, 1),
        "pct_5": round(100 * sum(1 for v in values_sorted if v == 5) / n, 1),
        "histogram": _histogram(values_sorted),
        "percentiles": _percentiles(values_sorted),
        "percentiles_note": PERCENTILES_NOTE,
    }

def _build_cell(values, label, kinds, year_from, year_to) -> dict:
    cell = {"label": label, "kinds": list(kinds),
            "year_from": year_from, "year_to": year_to}
    block = _stats_block(values)
    cell.update(block)
    if block["n"] < LOW_N_THRESHOLD:
        cell["low_n"] = True
    return cell

def _rated_stars(data: dict, kinds=None) -> list[dict]:
    """`rated` entries with an actual star rating (excludes the
    watched-but-never-rated works), optionally restricted to `kinds`."""
    entries = data.get("rated", [])
    if kinds is not None:
        entries = [e for e in entries if e.get("kind") in kinds]
    return [e for e in entries if e.get("stars") is not None]

def distribution(data: dict, ref_year: int | None = None) -> dict:
    """Base-rate statistics over the whole rated history: one `overall`
    block (every rated-with-stars work, any kind, any year) plus a
    standard set of `cells` — each kind alone, and each kind split into
    era buckets (see `_era_buckets`). Cells are never suppressed for
    thin n; they carry `low_n: true` instead (see module docstring)."""
    ref_year = ref_year or datetime.now().year
    overall_entries = _rated_stars(data)
    overall = _stats_block([e["stars"] for e in overall_entries])

    cells = []
    for kind_label, kinds in KIND_GROUPS.items():
        kind_entries = _rated_stars(data, kinds)
        cells.append(_build_cell([e["stars"] for e in kind_entries],
                                  kind_label, kinds, None, None))
        for era_text, yf, yt in _era_buckets(ref_year):
            era_values = [e["stars"] for e in kind_entries
                          if _year_in_range(e.get("year"), yf, yt)]
            cells.append(_build_cell(era_values, f"{kind_label} {era_text}",
                                      kinds, yf, yt))
    return {"overall": overall, "cells": cells}

def resolve_cell(data: dict, kind: str, year: int,
                  ref_year: int | None = None,
                  low_n_threshold: int = LOW_N_THRESHOLD) -> dict:
    """The single cell object `kind`+`year` belongs to, widening per the
    module docstring's "Cell fallback rule" when the specific cell is too
    thin to trust. Returns the winning cell object with `fallback_used`
    (bool) added, plus `fallback_note` when a widening happened."""
    ref_year = ref_year or datetime.now().year
    kind_label = KIND_ALIASES.get(kind)
    if kind_label is None:
        sys.exit(f"unknown --kind {kind!r}; expected one of "
                 f"{sorted(KIND_ALIASES)}")
    kinds = KIND_GROUPS[kind_label]
    kind_entries = _rated_stars(data, kinds)

    era_text, yf, yt = next(b for b in _era_buckets(ref_year)
                            if _year_in_range(year, b[1], b[2]))
    specific = _build_cell(
        [e["stars"] for e in kind_entries if _year_in_range(e.get("year"), yf, yt)],
        f"{kind_label} {era_text}", kinds, yf, yt)
    if specific["n"] >= low_n_threshold:
        specific.pop("low_n", None)
        return {**specific, "fallback_used": False}

    kind_cell = _build_cell([e["stars"] for e in kind_entries],
                            kind_label, kinds, None, None)
    if kind_cell["n"] >= low_n_threshold:
        kind_cell.pop("low_n", None)
        note = (f"widened from '{specific['label']}' (n={specific['n']}) to "
                f"'{kind_cell['label']}' (n={kind_cell['n']}) — dropped the "
                f"era filter because the specific cell had fewer than "
                f"{low_n_threshold} rated works")
        return {**kind_cell, "fallback_used": True, "fallback_note": note}

    overall_entries = _rated_stars(data)
    overall_cell = _build_cell([e["stars"] for e in overall_entries],
                               "overall", list(DEFAULT_KINDS), None, None)
    note = (f"widened from '{specific['label']}' (n={specific['n']}) to "
            f"'{kind_cell['label']}' (n={kind_cell['n']}) to "
            f"'{overall_cell['label']}' (n={overall_cell['n']}) — both the "
            f"era-specific and kind-only cells had fewer than "
            f"{low_n_threshold} rated works")
    return {**overall_cell, "fallback_used": True, "fallback_note": note}

def percentile_of(star: float, cell: dict) -> float | None:
    """Given a star value and a cell (or the top-level `overall` block —
    both carry `histogram`), return that cell's MID-RANK percentile for
    `star`: works strictly below `star` count fully, works tied with it
    count for HALF, works above count for nothing —
    `100 * (below + equal / 2) / n`.

    DO NOT change this to `count(<= star) / n` ("at or below"). That is
    the naive convention this function deliberately does not use, and
    the reason is the entire point of this module: his ratings are lumpy
    whole/half stars, so a real prediction always lands inside a wide tie
    band rather than at a clean boundary (e.g. every 4★ film rated
    2020-26 occupies the same 56.2-93.3rd percentile band). "At or below"
    always reports the *top* of that shared band — 93.3 for every 4★ film
    alike — which clears almost any threshold and silently re-creates the
    exact soft gate this rework exists to remove. Mid-rank instead
    credits a tie with half its own band (≈74.8 for that same cell): an
    honest statement of where that rating actually sits, not an inflated
    one. See the module docstring's "Percentile convention" for the full
    argument and the worked TV-vs-film comparison.

    This is what lets a prediction be expressed as "top X% for him in
    this category": percentile_of(4.5, cell) == 96.2 means his other
    ratings are, on average across the tie, below that 4.5 96.2% of the
    time. THIS is the function to call for a real threshold decision —
    the `percentiles` ladder field is NOT an exact inverse of this
    function and must not be used as one: `_percentiles` is built from
    this same mid-rank formula, but the smallest-value-that-clears-P
    search it does can clamp to the maximum star value without that
    value's own score actually reaching P (forced whenever one tie —
    commonly the 5★ ceiling — dominates the top of a cell; see the
    module docstring's "Percentile convention" for the concrete tv/show
    example). The ladder is orientation; this function is the gate.
    Returns None for a cell with zero rated works rather than dividing
    by zero."""
    histogram = cell.get("histogram", {})
    n = sum(histogram.values())
    if n == 0:
        return None
    below = sum(count for k, count in histogram.items() if float(k) < star)
    equal = sum(count for k, count in histogram.items() if float(k) == star)
    return round(100 * (below + equal / 2) / n, 1)

def resolve_percentile_of(data: dict, kind: str, year: int, stars: float,
                          ref_year: int | None = None,
                          low_n_threshold: int = LOW_N_THRESHOLD) -> dict:
    """The `percentile-of` subcommand's payload: resolve the `kind`+`year`
    cell exactly as `cell` does (same fallback ladder, same
    `fallback_used`/`fallback_note`), then score `stars` against it with
    `percentile_of` — the one call site meant to answer "does this
    predicted rating clear a target", so a caller never has to (and
    never should) hand-derive that from the `percentiles` ladder."""
    cell = resolve_cell(data, kind, year, ref_year, low_n_threshold)
    return {"kind": kind, "year": year, "stars": stars,
            "percentile": percentile_of(stars, cell), "cell": cell}

# ---------------------------------------------------------- sibling-seasons

def resolve_sibling_seasons(data: dict, title: str, year: int | None = None,
                            kind: str | None = None,
                            external_ids: dict | None = None) -> dict:
    """Has the user watched/is watching/wishlisted ANY season (or the
    show-level parent) of the show `title` belongs to? Answers purely
    from the snapshot's precomputed `season_index` (see the module
    docstring's "Sibling-seasons check") — no DB access, so this is safe
    to call once per shortlist candidate from a frozen snapshot.

    Matching order (id before title — this project's ids-over-title-
    similarity rule): (1) any `external_ids` pair overlaps a family's
    `show_ids`; (2) else the title (its `第N季` suffix stripped) equals a
    family's `base_title` AND — the over-matching guard, identical to
    `shells`/`suppress-sync` — `year` (when given) is one of that
    family's real season years. `watched` is true only when the matched
    family has at least one season/parent row carrying an actual status;
    matching a family by id or title alone, with nobody in it actually
    watched, correctly reports `watched: false` and `matched_by: null`."""
    external_ids = external_ids or {}
    base = _strip_season_suffix(title) or title
    families = data.get("season_index", [])
    own_ids = {(ns, val) for ns, val in external_ids.items() if val not in (None, "")}

    matched_family = None
    matched_by = None
    if own_ids:
        for fam in families:
            fam_ids = {tuple(pair) for pair in fam.get("show_ids", [])}
            if own_ids & fam_ids:
                matched_family, matched_by = fam, "external_id"
                break
    if matched_family is None:
        for fam in families:
            if fam["base_title"] != base:
                continue
            fam_years = set(fam.get("years", []))
            if not fam_years:
                continue
            if year is None or year in fam_years:
                matched_family, matched_by = fam, "base_title"
                break

    matching_works = []
    if matched_family is not None:
        matching_works = [s for s in matched_family["seasons"] if s.get("status")]
    watched = bool(matching_works)

    return {"title": title, "year": year, "kind": kind,
            "external_ids": external_ids, "base_title": base,
            "watched": watched, "matched_by": matched_by if watched else None,
            "matching_works": matching_works}

def resolve_sibling_seasons_batch(data: dict, items: list[dict]) -> list[dict]:
    """`resolve_sibling_seasons` for a whole shortlist in one call — the
    part that actually recovers the scout's time, per the module
    docstring's "Sibling-seasons check": one call instead of N. Order-
    preserving; one result per input item, in input order. Each item is
    `{title, year, kind, external_ids}` (all but `title` optional)."""
    return [resolve_sibling_seasons(data, item.get("title") or "",
                                    item.get("year"), item.get("kind"),
                                    item.get("external_ids") or {})
           for item in items]

# ------------------------------------------------------------------ cli

def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    # Several agent sessions run against this DB concurrently; wait for a
    # competing writer's lock instead of erroring out immediately.
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return con

def _kinds(raw) -> tuple:
    return tuple(k.strip() for k in raw.split(",") if k.strip())

def _load(args) -> tuple[dict, str]:
    """Load a snapshot for `index`/`lookup`: from --snapshot (the path the
    critic uses — the run's frozen snapshot, no DB access) or, as a
    convenience, freshly from --db."""
    if args.snapshot:
        with open(args.snapshot, encoding="utf-8") as fh:
            return json.load(fh), args.snapshot
    if args.db:
        con = _connect(args.db)
        try:
            return snapshot(con, _kinds(args.kinds)), args.db
        finally:
            con.close()
    sys.exit("need --snapshot PATH (preferred) or --db PATH")

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", help="media.db path (required for `snapshot`)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="full JSON snapshot (needs --db)")
    s.add_argument("--kinds", default=",".join(DEFAULT_KINDS))
    s.add_argument("--out")

    s = sub.add_parser("index", help="one compact line per rated work")
    s.add_argument("--snapshot", help="snapshot JSON written by `snapshot --out`")
    s.add_argument("--kinds", default=",".join(DEFAULT_KINDS))
    s.add_argument("--out")

    s = sub.add_parser("lookup", help="full detail for specific works")
    s.add_argument("--snapshot", help="snapshot JSON written by `snapshot --out`")
    s.add_argument("--kinds", default=",".join(DEFAULT_KINDS))
    s.add_argument("--work-id", type=int, action="append", dest="work_id",
                   help="repeatable")
    s.add_argument("--title", action="append",
                   help="case-insensitive substring, repeatable")
    s.add_argument("--creator", action="append",
                   help="case-insensitive substring, repeatable")

    s = sub.add_parser("distribution",
                       help="overall + per-cell base-rate statistics")
    s.add_argument("--snapshot", help="snapshot JSON written by `snapshot --out`")
    s.add_argument("--kinds", default=",".join(DEFAULT_KINDS))

    s = sub.add_parser("cell",
                       help="the single base-rate cell a kind+year belongs to")
    s.add_argument("--snapshot", help="snapshot JSON written by `snapshot --out`")
    s.add_argument("--kinds", default=",".join(DEFAULT_KINDS))
    s.add_argument("--kind", required=True, help="e.g. film, tv, show, drama")
    s.add_argument("--year", required=True, type=int)

    s = sub.add_parser("percentile-of",
                       help="mid-rank percentile of one candidate rating "
                            "within its resolved cell — the gate, not the ladder")
    s.add_argument("--snapshot", help="snapshot JSON written by `snapshot --out`")
    s.add_argument("--kinds", default=",".join(DEFAULT_KINDS))
    s.add_argument("--kind", required=True, help="e.g. film, tv, show, drama")
    s.add_argument("--year", required=True, type=int)
    s.add_argument("--stars", required=True, type=float,
                   help="predicted/candidate star rating, 0.5-5.0")

    s = sub.add_parser("sibling-seasons",
                       help="has the user watched/wishlisted ANY season of "
                            "this show already? — the scout's per-candidate "
                            "watched-season-family check")
    s.add_argument("--snapshot", help="snapshot JSON written by `snapshot --out`")
    s.add_argument("--kinds", default=",".join(DEFAULT_KINDS))
    s.add_argument("--title", help="candidate title (ignored if --batch given)")
    s.add_argument("--year", type=int)
    s.add_argument("--kind")
    s.add_argument("--ext", action="append", dest="ext",
                   help="NAMESPACE:VALUE, repeatable, e.g. --ext douban:35651341")
    s.add_argument("--batch",
                   help="JSON file: a list of {title, year, kind, "
                        "external_ids} objects, checked in one call; "
                        "results come back in the same order")

    args = p.parse_args()

    if args.cmd == "snapshot":
        if not args.db:
            sys.exit("snapshot needs --db PATH")
        con = _connect(args.db)
        try:
            data = snapshot(con, _kinds(args.kinds))
        finally:
            con.close()
        text = json.dumps(data, ensure_ascii=False, indent=1)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
            print(json.dumps(data["counts"]))
        else:
            print(text)
        return

    if args.cmd == "index":
        data, origin = _load(args)
        text = build_index(data, origin)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
            print(json.dumps({"entries": len(data.get(INDEX_SECTION, [])),
                              "out": args.out}))
        else:
            sys.stdout.write(text)
        return

    if args.cmd == "lookup":
        if not (args.work_id or args.title or args.creator):
            sys.exit("lookup needs at least one of --work-id / --title / --creator")
        data, _ = _load(args)
        hits = lookup(data, args.work_id or (), args.title or (),
                      args.creator or ())
        print(json.dumps({"query": {"work_id": args.work_id,
                                    "title": args.title,
                                    "creator": args.creator},
                          "count": len(hits), "results": hits},
                         ensure_ascii=False, indent=1))
        return

    if args.cmd == "distribution":
        data, _ = _load(args)
        print(json.dumps(distribution(data), ensure_ascii=False, indent=1))
        return

    if args.cmd == "cell":
        data, _ = _load(args)
        print(json.dumps(resolve_cell(data, args.kind, args.year),
                         ensure_ascii=False, indent=1))
        return

    if args.cmd == "percentile-of":
        data, _ = _load(args)
        result = resolve_percentile_of(data, args.kind, args.year, args.stars)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return

    if args.cmd == "sibling-seasons":
        data, _ = _load(args)
        if args.batch:
            items = json.loads(open(args.batch, encoding="utf-8").read())
            if not isinstance(items, list):
                sys.exit("sibling-seasons --batch expects a JSON list of "
                         "{title, year, kind, external_ids} objects")
            results = resolve_sibling_seasons_batch(data, items)
            print(json.dumps({"count": len(results), "results": results},
                             ensure_ascii=False, indent=1))
            return
        if not args.title:
            sys.exit("sibling-seasons needs --title TITLE or --batch FILE")
        ext = {}
        for pair in (args.ext or []):
            if ":" not in pair:
                sys.exit(f"--ext expects NAMESPACE:VALUE, got {pair!r}")
            ns, val = pair.split(":", 1)
            ext[ns] = val
        result = resolve_sibling_seasons(data, args.title, args.year, args.kind, ext)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return

if __name__ == "__main__":
    main()
