#!/usr/bin/env bash
# census.sh CODE [tree] — Phase 1's census, every instrument, canonical file names.
#
# Runs, serially (one pool compile at a time), in <tree> (default: the main
# checkout) with CODE ingested: the support report and its three views
# (--refusals, --fragments, --hollow-lines), parse_coverage (2 workers),
# picker_sweep, census_new.py and card_table.py. Writes each to
# $SCRATCH/census/<code>_<instrument>.log — the names gen_cards.py,
# card_table.py and furthest.py read — with its exit code on the last line,
# and touches $SCRATCH/census/done. Scourge's integrator wrote this in scratch
# and Mirrodin's re-did it by hand (card_table.py then missed its input);
# committed so a round starts from it.
set -u
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
code="${1:?name the set code}"; tree="${2:-$REPO}"
lc=$(echo "$code" | tr 'A-Z' 'a-z')
C="$SCRATCH/census"
mkdir -p "$C"
rm -f "$C/done"
cd "$tree" || exit 2
run() { local out="$1"; shift; "$PY" "$@" > "$C/$out" 2>&1; echo "exit=$?" >> "$C/$out"; }
run "${lc}_support.log"   scripts/support_report.py --set "$code"
run "${lc}_refusals.log"  scripts/support_report.py --set "$code" --refusals
run "${lc}_fragments.log" scripts/support_report.py --set "$code" --fragments
run "${lc}_hollow.log"    scripts/support_report.py --set "$code" --hollow-lines
run "${lc}_parse.log"     scripts/parse_coverage.py --set "$code" --workers 2
run "${lc}_picker.log"    scripts/picker_sweep.py --set "$code"
run "${lc}_new.log"       "$TOOLS/census_new.py" "$code"
run "${lc}_table.txt"     "$TOOLS/card_table.py" "$code" "$C"
touch "$C/done"
grep -H "^exit=" "$C/${lc}_"*.log "$C/${lc}_table.txt"
