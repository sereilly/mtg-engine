#!/usr/bin/env bash
# gate_report.sh <tag> — print the reading of gate.sh <tree> <tag>.
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
tag="$1"
[ -f "$GATE/done_$tag" ] || echo "(gate $tag has not finished)"
echo "--- oracle_diff"; head -1 "$GATE/od_$tag.log"; grep -E "^[~+-] " "$GATE/od_$tag.log" | head -80; grep -E "Traceback|Error|od_exit" "$GATE/od_$tag.log" | head -5
echo "--- scans"; grep -E "^(DUP|MISSING|SYNTAX)|^duplicates:|^missing names:" "$GATE/scans_$tag.log"
echo "--- suite"; tail -1 "$GATE/full_$tag.log"; echo "FAILED lines: $(grep -c '^FAILED' "$GATE/full_$tag.log")"; grep -E "^(FAILED|ERROR)" "$GATE/full_$tag.log" | sed 's/ - .*//' | sort -u | head -40
echo "--- check_all"; grep -v " ok " "$GATE/checkall_$tag.log" | grep -v "^$" | head -40
echo "--- support (whole pool)"; grep -E "Supported cards|Unsupported cards" "$GATE/support_$tag.log"
