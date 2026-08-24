#!/bin/bash
# recommend/run_digest.sh
#
# One-command entry point for the recommend system's monthly DIGEST DATA
# REFRESH — SKILL.md step 0, made runnable as a single command instead of
# a list of prose steps a human has to follow by hand. Runs, in order:
#   1. TMDB harvest   (anchors -> fetch -> transform)
#   2. Douban harvest (anchors -> fetch -> transform, honoring its
#      resumable checkpoint and --budget)
#   3. write ritual (lsof / wal checkpoint / backup) — before the FIRST
#      media.db write, which is the upsert below, not the harvesters
#      (the harvesters only read media.db, via their own `anchors`
#      subcommand, and otherwise touch only recommend/raw/.. on disk)
#   4. pool.py upsert, once per harvested batch
#   5. pool.py suppress-sync
#   6. pool.py stats
#
# This script does NOT run the recommendation itself. That is the
# `/recommend` skill in digest mode (SCOUT.md's "Run modes" -> digest;
# SKILL.md steps 1-7) — this script is only the data-refresh half that
# must precede it, so the digest skill's step 0 becomes "run this script"
# instead of re-deriving the harvest sequence by hand each time.
#
# Idempotent & resumable:
#   - TMDB: `fetch` overwrites its dated raw-dir's files (safe to re-run
#     within the same day) and `pool.py upsert` is a non-destructive
#     gap-fill merge (safe to re-run on any day) — see pool.py --help's
#     "Upsert contract". There is no TMDB-side checkpoint because none is
#     needed: a full TMDB sweep completes in one invocation.
#   - Douban: `fetch` is checkpointed at a PERSISTENT path
#     (recommend/raw/douban/checkpoint.json, not inside the dated raw
#     dir) and budget-capped per invocation. Re-running this script picks
#     up exactly where the last invocation stopped, whether it stopped on
#     budget, an HTTP block, or the circuit breaker — none of those are
#     treated as failures (see "Exit codes" below).
#
# Exit codes:
#   0  — normal completion, INCLUDING a Douban rate-limit block or
#        circuit-breaker trip. Those are findings (reported in the log
#        and in this run's summary line), not failures — SKILL.md step 0
#        already documents a Douban block as "a finding to report on
#        completion, not a failure", and the harvester itself always
#        exits 0 in that case (it prints a JSON report and stops).
#   1  — a real failure: a missing TMDB_API_KEY, a malformed batch that
#        pool.py's validator rejected, a Python traceback from any step,
#        or any command actually crashing.
#   2  — the write-ritual precondition failed (media.db is held open by
#        another process right now — see the "One writer at a time" house
#        rule) or --db does not point at an existing file. The run stops
#        BEFORE touching media.db in either case.
#
# Usage:
#   recommend/run_digest.sh [--budget N] [--pages N] [--recency-months N]
#                            [--db PATH] [--dry-run]
#   recommend/run_digest.sh --help
#
# --budget N            Douban: max newly-attempted anchors this run
#                        (default 40, matches README.md's binding).
# --pages N              TMDB: /recommendations pages per anchor (default 2).
# --recency-months N     TMDB: discover recency window (default 18).
# --db PATH               media.db path (default: media.db, i.e. the repo
#                        root's canonical DB — override only for a test DB).
# --dry-run                print every command this run would execute, in
#                        order, and exit 0 without touching the network,
#                        media.db, or the filesystem beyond argument
#                        parsing. No TMDB_API_KEY lookup, no lsof, no
#                        backup. Use this to verify the sequence.
#
# Logs to recommend/logs/digest-<YYYY-MM-DD>.log (created if absent,
# appended to if a second run happens the same day), and echoes the same
# lines to stdout.

set -uo pipefail

# ---------------------------------------------------------------- setup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

BUDGET=40
PAGES=2
RECENCY_MONTHS=18
DB="media.db"
DRY_RUN=0

usage() {
    sed -n '2,71p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --budget) BUDGET="$2"; shift 2 ;;
        --pages) PAGES="$2"; shift 2 ;;
        --recency-months) RECENCY_MONTHS="$2"; shift 2 ;;
        --db) DB="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

TODAY="$(date +%Y-%m-%d)"
NOW="$(date +%Y%m%d-%H%M%S)"
TMDB_RAW_DIR="recommend/raw/tmdb/$TODAY"
DOUBAN_RAW_DIR="recommend/raw/douban/$TODAY"
DOUBAN_CHECKPOINT="recommend/raw/douban/checkpoint.json"
LOG_DIR="recommend/logs"
LOG_FILE="$LOG_DIR/digest-$TODAY.log"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/recommend-digest.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT

TMDB_ANCHORS="$SCRATCH/tmdb_anchors.json"
TMDB_BATCH="$SCRATCH/tmdb_batch.json"
DOUBAN_ANCHORS="$SCRATCH/douban_anchors.json"
DOUBAN_BATCH="$SCRATCH/douban_batch.json"

FAILED=0
FINDINGS=()

log() {
    local line="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$line"
    [ "$DRY_RUN" -eq 1 ] || { mkdir -p "$LOG_DIR"; echo "$line" >> "$LOG_FILE"; }
}

run_step() {
    # run_step <description> -- <command...>
    # Logs the command, runs it with its combined stdout+stderr teed into
    # the log file as well as the terminal, logs its exit code. Sets
    # FAILED=1 on a non-zero exit — callers that want to treat a non-zero
    # exit as an expected finding (none do, currently; harvest_douban.py
    # fetch always exits 0) inline their own invocation instead of using
    # this helper. Do NOT call this for a command whose STDOUT needs to
    # be captured into a variable/file by the caller (e.g. the `anchors`
    # subcommands, whose JSON output IS the next step's input) — use a
    # direct redirection there instead, exactly as the anchors steps
    # above do; piping through `tee` here would interleave log lines
    # into that captured output.
    local desc="$1"; shift
    log "-- $desc"
    log "   \$ $*"
    if [ "$DRY_RUN" -eq 1 ]; then
        return 0
    fi
    "$@" 2>&1 | tee -a "$LOG_FILE"
    local rc=${PIPESTATUS[0]}
    if [ $rc -ne 0 ]; then
        log "   FAILED (exit $rc): $desc"
        FAILED=1
    fi
    return $rc
}

# ------------------------------------------------------------- dry run

if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY RUN — printing the command sequence only, nothing executed."
    run_step "TMDB anchors (DB read)" python3 recommend/harvest_tmdb.py anchors --db "$DB"
    run_step "TMDB fetch" python3 recommend/harvest_tmdb.py fetch --anchors "$TMDB_ANCHORS" --raw-dir "$TMDB_RAW_DIR" --pages "$PAGES" --recency-months "$RECENCY_MONTHS"
    run_step "TMDB transform" python3 recommend/harvest_tmdb.py transform --raw-dir "$TMDB_RAW_DIR" --out "$TMDB_BATCH"
    run_step "Douban anchors (DB read)" python3 recommend/harvest_douban.py anchors --db "$DB"
    run_step "Douban fetch (needs uv run: PEP 723 requests dep)" uv run recommend/harvest_douban.py fetch --anchors "$DOUBAN_ANCHORS" --raw-dir "$DOUBAN_RAW_DIR" --checkpoint "$DOUBAN_CHECKPOINT" --budget "$BUDGET"
    run_step "Douban transform" python3 recommend/harvest_douban.py transform --raw-dir "$DOUBAN_RAW_DIR" --out "$DOUBAN_BATCH"
    log "-- write ritual: lsof \"$DB\"* ; PRAGMA wal_checkpoint(TRUNCATE) ; cp \"$DB\" backups/media-recommend-digest-<timestamp>.db"
    run_step "pool upsert (TMDB batch)" python3 recommend/pool.py --db "$DB" upsert --json "$TMDB_BATCH"
    run_step "pool upsert (Douban batch)" python3 recommend/pool.py --db "$DB" upsert --json "$DOUBAN_BATCH"
    run_step "pool suppress-sync" python3 recommend/pool.py --db "$DB" suppress-sync
    run_step "pool stats" python3 recommend/pool.py --db "$DB" stats
    log "DRY RUN complete — no network calls, no media.db access, no writes."
    exit 0
fi

log "=== recommend digest data-refresh starting (db=$DB budget=$BUDGET pages=$PAGES recency_months=$RECENCY_MONTHS) ==="

if [ ! -f "$DB" ]; then
    log "ABORT: --db $DB does not exist. Nothing was touched."
    exit 2
fi

# ------------------------------------------------------------ 1. TMDB

log "== Step 1: TMDB harvest =="
log "-- TMDB anchors"
log "   \$ python3 recommend/harvest_tmdb.py anchors --db $DB > $TMDB_ANCHORS"
python3 recommend/harvest_tmdb.py anchors --db "$DB" > "$TMDB_ANCHORS" 2>"$SCRATCH/tmdb_anchors.err"
if [ $? -ne 0 ]; then cat "$SCRATCH/tmdb_anchors.err" >> "$LOG_FILE"; log "TMDB anchors FAILED (see $LOG_FILE)"; exit 1; fi
log "-- TMDB fetch"
log "   \$ python3 recommend/harvest_tmdb.py fetch --anchors $TMDB_ANCHORS --raw-dir $TMDB_RAW_DIR --pages $PAGES --recency-months $RECENCY_MONTHS"
python3 recommend/harvest_tmdb.py fetch --anchors "$TMDB_ANCHORS" --raw-dir "$TMDB_RAW_DIR" --pages "$PAGES" --recency-months "$RECENCY_MONTHS" >>"$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then log "TMDB fetch failed (see $LOG_FILE) — most likely TMDB_API_KEY is missing from env or ../douban-export/sources/sources.env"; exit 1; fi
run_step "TMDB transform" python3 recommend/harvest_tmdb.py transform --raw-dir "$TMDB_RAW_DIR" --out "$TMDB_BATCH" || exit 1
log "TMDB batch written: $TMDB_BATCH ($(python3 -c "import json;print(len(json.load(open('$TMDB_BATCH'))))" 2>/dev/null || echo '?') rows)"

# ---------------------------------------------------------- 2. Douban

log "== Step 2: Douban harvest (checkpoint=$DOUBAN_CHECKPOINT budget=$BUDGET) =="
log "-- Douban anchors"
log "   \$ python3 recommend/harvest_douban.py anchors --db $DB > $DOUBAN_ANCHORS"
python3 recommend/harvest_douban.py anchors --db "$DB" > "$DOUBAN_ANCHORS" 2>"$SCRATCH/douban_anchors.err"
if [ $? -ne 0 ]; then cat "$SCRATCH/douban_anchors.err" >> "$LOG_FILE"; log "Douban anchors FAILED (see $LOG_FILE)"; exit 1; fi

DOUBAN_REPORT="$SCRATCH/douban_fetch_report.json"
log "-- Douban fetch"
log "   \$ uv run recommend/harvest_douban.py fetch --anchors $DOUBAN_ANCHORS --raw-dir $DOUBAN_RAW_DIR --checkpoint $DOUBAN_CHECKPOINT --budget $BUDGET"
uv run recommend/harvest_douban.py fetch --anchors "$DOUBAN_ANCHORS" --raw-dir "$DOUBAN_RAW_DIR" \
    --checkpoint "$DOUBAN_CHECKPOINT" --budget "$BUDGET" > "$DOUBAN_REPORT" 2>>"$LOG_FILE"
DOUBAN_FETCH_RC=$?
if [ $DOUBAN_FETCH_RC -ne 0 ]; then
    # The harvester only exits non-zero for a real problem (e.g. `requests`
    # not installed under `uv run`, or an uncaught crash) — a rate-limit
    # block or circuit-breaker trip is reported via the JSON report below
    # with exit 0, never a non-zero exit. So a non-zero exit here IS a
    # real failure.
    cat "$DOUBAN_REPORT" >> "$LOG_FILE" 2>/dev/null
    log "Douban fetch FAILED (exit $DOUBAN_FETCH_RC, see $LOG_FILE)"
    exit 1
fi
cat "$DOUBAN_REPORT" >> "$LOG_FILE"
log "Douban fetch report: $(cat "$DOUBAN_REPORT")"
if python3 -c "
import json, sys
r = json.load(open('$DOUBAN_REPORT'))
sys.exit(0 if (r.get('blocked') or r.get('circuit_breaker_tripped') or r.get('budget_hit')) else 1)
"; then
    log "FINDING: Douban harvest stopped early this run (block/circuit-breaker/budget — see report above). This is expected behaviour, not a failure; the checkpoint will resume it next run."
fi

run_step "Douban transform" python3 recommend/harvest_douban.py transform --raw-dir "$DOUBAN_RAW_DIR" --out "$DOUBAN_BATCH" || exit 1
log "Douban batch written: $DOUBAN_BATCH ($(python3 -c "import json;print(len(json.load(open('$DOUBAN_BATCH'))))" 2>/dev/null || echo '?') rows)"

# ------------------------------------------------------- 3. write ritual

log "== Step 3: write ritual (before the first media.db WRITE — the upsert next) =="
LSOF_OUT="$(lsof "$DB" "$DB"-wal "$DB"-shm 2>/dev/null)"
if [ -n "$LSOF_OUT" ]; then
    log "ABORT: $DB (or its -wal/-shm) is held open by another process:"
    log "$LSOF_OUT"
    log "Per the house 'one writer at a time' rule, this run stops here without touching media.db. Re-run once the other process is done. (Note: STATE.md lane ownership is a human-judgment check this script cannot parse automatically — read STATE.md yourself before re-running if you are not sure another agent's harvest has finished.)"
    exit 2
fi
log "lsof clean — no other process holds $DB open."
run_step "wal_checkpoint(TRUNCATE)" sqlite3 "$DB" "PRAGMA wal_checkpoint(TRUNCATE);" || exit 1
mkdir -p backups
BACKUP_PATH="backups/media-recommend-digest-$NOW.db"
run_step "backup" cp "$DB" "$BACKUP_PATH" || exit 1
log "backup written: $BACKUP_PATH"

# --------------------------------------------------------- 4. upsert

log "== Step 4: pool.py upsert =="
run_step "upsert TMDB batch" python3 recommend/pool.py --db "$DB" upsert --json "$TMDB_BATCH" || exit 1
run_step "upsert Douban batch" python3 recommend/pool.py --db "$DB" upsert --json "$DOUBAN_BATCH" || exit 1

# ----------------------------------------------------- 5. suppress-sync

log "== Step 5: pool.py suppress-sync =="
run_step "suppress-sync" python3 recommend/pool.py --db "$DB" suppress-sync || exit 1

# ------------------------------------------------------------ 6. stats

log "== Step 6: pool.py stats =="
STATS="$(python3 recommend/pool.py --db "$DB" stats)"
STATS_RC=$?
if [ $STATS_RC -ne 0 ]; then
    log "pool stats FAILED (exit $STATS_RC)"
    exit 1
fi
log "pool stats: $STATS"

if [ "$FAILED" -eq 1 ]; then
    log "=== recommend digest data-refresh FINISHED WITH FAILURES — see $LOG_FILE ==="
    exit 1
fi

log "=== recommend digest data-refresh complete. Next: run the /recommend skill in digest mode (SKILL.md steps 1-7) to actually produce this month's pitch. ==="
exit 0
