#!/usr/bin/env bash
# gate.sh <tree> <tag> [workers] [quick|full] — the full gate (SET_PLAYBOOK.md, "Integration").
#
# Run on a merge *staged but not committed* (so oracle_diff reads the merge's
# own delta) or on a clean tree. In order: oracle_diff compare, the duplicate-
# definition and missing-name scans over the changed files, the whole suite,
# check_all, the whole-pool support report. Every result goes to a file in
# $GATE named for <tag>; nothing is piped through tail, so every exit code is
# the command's own. `gate_report.sh <tag>` prints the reading.
#
# When to run it: at a wave's close and at the promotion. Between merges the
# meeting-point run (meeting.sh) is the gate — it predicted every full gate in
# Torment — and the full gate is for what no list can name.
#
# The suite runs as the quick pass at a wave's close and as the full pass
# (`full`: `pytest --full`, every test marked `full` and every sampled census
# whole — tests/passes.py) on the promotion commit, and nowhere else.
set -u
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
tree="$1"; tag="$2"; workers="${3:-4}"; pass="${4:-quick}"
case "$pass" in quick) full_flag="" ;; full) full_flag="--full" ;; *) echo "pass is quick or full, not $pass"; exit 2 ;; esac
cd "$tree" || exit 2
rm -f "$GATE/done_$tag"
"$PY" scripts/oracle_diff.py compare > "$GATE/od_$tag.log" 2>&1
echo "od_exit=$?" >> "$GATE/od_$tag.log"
changed=$( (git diff --cached --name-only --diff-filter=AM; git diff --name-only --diff-filter=AM) | sort -u | grep '\.py$')
"$PY" "$TOOLS/dups.py" $changed > "$GATE/scans_$tag.log" 2>&1
"$PY" "$TOOLS/missing_names.py" $(echo "$changed" | grep -E '^(engine|web|scripts)/') >> "$GATE/scans_$tag.log" 2>&1
"$PY" -m pytest -n "$workers" -q -p no:cacheprovider $full_flag > "$GATE/full_$tag.log" 2>&1
echo "exit=$?" >> "$GATE/full_$tag.log"
"$PY" scripts/check_all.py > "$GATE/checkall_$tag.log" 2>&1
echo "exit=$?" >> "$GATE/checkall_$tag.log"
"$PY" scripts/support_report.py > "$GATE/support_$tag.log" 2>&1
touch "$GATE/done_$tag"
