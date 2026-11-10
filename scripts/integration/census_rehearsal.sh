#!/usr/bin/env bash
# census_rehearsal.sh <tree> <tag> CODE [workers] [catalog|sampled|both] — the promotion's censuses, in memory.
#
# Runs with MTG_PROMOTE=CODE (engine/card_loader.py): the measured set is read
# as shipped, at its printing-ordered place, and cards/manifest.json is not
# touched — nothing to restore, nothing to commit by mistake.
#
#   catalog  the quick pass, whole: every census over load_catalog() sees the
#            set. Mirrodin's first promotion rehearsal: 11 of its 14 new reds.
#   sampled  every sampled census whole (MTG_FULL_CENSUS=1 over the files that
#            call stable_sample / stable_part / full_census), named so their
#            `full` tests run too. Mirrodin's promotion full pass (32 min) found
#            four such reds and cost a 76-minute fix round before main moved;
#            these files take minutes.
#   both     (default) catalog, then sampled.
#
# When: at each wave's close, beside gate.sh, and before the promotion's full
# pass. A group can run its own families' censuses the same way in round:
# `MTG_PROMOTE=CODE pytest <files>` (scripts/tests_for_diff.py picks them).
#
# The shipped pool's guards fail on the set's unsupported cards until every one
# is supported, exactly as on the real move; their reds are listed apart. Logs
# go to $GATE/rehearsal_<tag>_<part>.log; nothing is piped through tail.
set -u
ALLOW_PROMOTE=1
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
tree="$1"; tag="$2"; code="$3"; workers="${4:-4}"; part="${5:-both}"
case "$part" in catalog|sampled|both) ;; *) echo "part is catalog, sampled or both, not $part"; exit 2 ;; esac
cd "$tree" || exit 2
export MTG_PROMOTE="$code"
# Fails here, naming the measured codes, if CODE is not measured in this tree.
"$PY" -c "from engine.card_loader import manifest_sets; manifest_sets()" || exit 2
unsupported=$("$PY" - <<'EOF'
import os
from engine.card_loader import load_cards, manifest_set_path
from engine.oracle import compile_card_oracle
cards = load_cards(manifest_set_path(os.environ["MTG_PROMOTE"]))
print(sum(not compile_card_oracle(card).supported for card in cards))
EOF
)
echo "MTG_PROMOTE=$code: $unsupported card(s) of the set unsupported in this tree"
# The guards a set with unsupported cards turns red on the real move too.
EXPECTED="tests/engine/test_front_end_safety.py tests/engine/test_card_format.py
tests/engine/test_parse_coverage.py tests/engine/test_no_hollow_support.py
tests/engine/test_behaviour_classes.py"

report() {  # report <log>
  local log="$1" expected_re
  expected_re=$(echo $EXPECTED | tr ' ' '|')
  echo "$(tail -1 "$log")  FAILED=$(grep -c '^FAILED' "$log")  ($log)"
  echo "  not the shipped-pool guards — read each:"
  grep '^FAILED\|^ERROR' "$log" | grep -Ev "$expected_re" | sed 's/ - .*//' | sort | sed 's/^/    /'
  echo "  the shipped-pool guards ($unsupported unsupported card(s); expected red until 0):"
  grep '^FAILED\|^ERROR' "$log" | grep -E "$expected_re" | sed 's/ - .*//' | sort | sed 's/^/    /'
}

status=0
if [ "$part" != sampled ]; then
  log="$GATE/rehearsal_${tag}_catalog.log"
  "$PY" -m pytest -n "$workers" --dist worksteal -q -p no:cacheprovider > "$log" 2>&1
  code_=$?; echo "exit=$code_" >> "$log"; [ "$code_" -ne 0 ] && status=1
  report "$log"
fi
if [ "$part" != catalog ]; then
  log="$GATE/rehearsal_${tag}_sampled.log"
  files=$(grep -rlE "stable_sample|stable_part|full_census\(" tests --include='*.py' | grep -v -e '^tests/helpers.py$' -e '^tests/passes.py$' | sort)
  echo "$files" > "$GATE/rehearsal_${tag}_sampled_files.txt"
  MTG_FULL_CENSUS=1 "$PY" -m pytest -n "$workers" --dist worksteal -q -p no:cacheprovider $files > "$log" 2>&1
  code_=$?; echo "exit=$code_" >> "$log"; [ "$code_" -ne 0 ] && status=1
  report "$log"
fi
touch "$GATE/done_rehearsal_$tag"
exit $status
