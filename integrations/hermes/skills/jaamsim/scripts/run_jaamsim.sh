#!/usr/bin/env bash
# Run a JaamSim model headless and VERIFY it actually produced output.
#
# Why this wrapper exists: JaamSim's headless runner exits 0 no matter what.
# A typo in an output name, a broken .cfg, a missing entity — all still exit 0
# and either leave the old .dat in place or write garbage. The only reliable
# success signal is that the .dat/.rep files were rewritten by THIS run.
#
# Usage: run_jaamsim.sh <model.cfg>
#
# Exit codes: 0 = ran and outputs are fresh, 1 = usage/setup error,
#             2 = java failed, 3 = outputs were NOT refreshed (silent failure).

set -uo pipefail

JAR="${JAAMSIM_JAR:-$HOME/course/jaamsim/JaamSim2026-05.jar}"

if [ $# -lt 1 ]; then
  echo "usage: run_jaamsim.sh <model.cfg>" >&2
  exit 1
fi

CFG="$1"
[ -f "$CFG" ] || { echo "ERROR: model not found: $CFG" >&2; exit 1; }
[ -f "$JAR" ] || { echo "ERROR: JaamSim jar not found: $JAR" >&2; exit 1; }

CFG_DIR="$(cd "$(dirname "$CFG")" && pwd)"
BASE="$(basename "$CFG" .cfg)"
DAT="$CFG_DIR/$BASE.dat"
REP="$CFG_DIR/$BASE.rep"

mtime() { [ -f "$1" ] && stat -c %Y "$1" || echo 0; }
DAT_BEFORE="$(mtime "$DAT")"
REP_BEFORE="$(mtime "$REP")"

START="$(date +%s)"
echo "=== running: java -jar $JAR $CFG -headless ==="
java -jar "$JAR" "$CFG" -headless
JAVA_RC=$?
ELAPSED=$(( $(date +%s) - START ))
echo "=== java exit code: $JAVA_RC (NOT trustworthy), elapsed ${ELAPSED}s ==="

if [ "$JAVA_RC" -ne 0 ]; then
  echo "ERROR: java itself failed (rc=$JAVA_RC)." >&2
  exit 2
fi

DAT_AFTER="$(mtime "$DAT")"
REP_AFTER="$(mtime "$REP")"

FRESH=1
[ "$DAT_AFTER" -gt "$DAT_BEFORE" ] || FRESH=0
[ "$REP_AFTER" -gt "$REP_BEFORE" ] || FRESH=0

if [ "$FRESH" -ne 1 ]; then
  echo "FAILED: outputs were not refreshed by this run." >&2
  echo "  $DAT  mtime ${DAT_BEFORE} -> ${DAT_AFTER}" >&2
  echo "  $REP  mtime ${REP_BEFORE} -> ${REP_AFTER}" >&2
  echo "The run silently did nothing. Check the .cfg: entity names in" >&2
  echo "Simulation RunOutputList must match the Define'd names exactly." >&2
  exit 3
fi

if [ ! -s "$DAT" ]; then
  echo "FAILED: $DAT is empty." >&2
  exit 3
fi

echo "=== VERIFIED: outputs freshly written ==="
echo "  $DAT"
echo "  $REP"
echo
echo "=== $BASE.dat ==="
cat "$DAT"
echo "=== end of .dat ==="
echo
echo "Reading the .dat: the header row names the outputs from"
echo "Simulation RunOutputList. One row per replication, then a final row with"
echo "no replication number holding the mean and standard deviation of each"
echo "output across replications (value, stddev, value, stddev, ...)."
exit 0
