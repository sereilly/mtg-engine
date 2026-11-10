#!/usr/bin/env bash
# meeting.sh <tree> <tag> [workers] — the meeting-point run: the gate between merges.
#
# The tests where two branches can meet, on a staged or committed link:
#   - every test file any branch merged since $MEETING_BASE (default main) added or edited;
#   - the set's own per-set files (tests/sets/test_<round>_*.py, if any);
#   - $SCRATCH/yield.txt     — the ingest's red tests, one path per line;
#   - $SCRATCH/surprises.txt — every file a full gate turned red that this
#                              list did not hold (it grows; that is the point);
#   - every census over a registry the merged branches added members to or
#     removed members from (scripts/tests_for_diff.py --censuses, against
#     $MEETING_BASE) — the class Mirrodin's wave-close gate found eight of;
#   - the structural guards below.
# Never a hand-picked list per merge. A path that does not exist is refused,
# because xdist reports a typo as "no tests ran" and exits 0.
set -u
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
tree="$1"; tag="$2"; workers="${3:-4}"
cd "$tree" || exit 2
GUARDS="tests/engine/test_grammar_layering.py tests/engine/test_import_hygiene.py
tests/engine/test_grammar_categories.py tests/engine/test_card_lines.py
tests/engine/test_cr_citation_subjects.py tests/engine/test_ast_effect_union.py
tests/engine/test_parse_coverage.py tests/engine/test_keyword_registry.py
tests/engine/test_front_end_safety.py tests/engine/test_card_format.py
tests/engine/test_manifest_roles.py tests/engine/test_no_hollow_support.py
tests/engine/test_effect_labels.py tests/engine/test_layer_reads.py
tests/engine/test_control_reads.py tests/engine/test_card_name_reads.py
tests/engine/test_hand_removal_seam.py tests/engine/test_draw_seam.py
tests/engine/test_set_test_convention.py tests/engine/test_face_blind_guards.py
tests/engine/test_hook_reliance.py tests/engine/test_trigger_dispatchers.py
tests/engine/test_subject_filters.py tests/engine/test_targeting.py
tests/engine/test_activation_targeting.py tests/engine/test_stack_targets.py
tests/engine/test_color_write_seam.py tests/engine/test_module_size.py
tests/regressions/test_derived_card_memo_identity.py"
read_list() { [ -f "$1" ] && tr -d '\r' < "$1"; }
# MEETING_BASE: the ref the "changed" list is read from (default main). Set it
# to the staged branch's merge-base with the chain (git merge-base <link>
# <branch>): that is the branch's own files plus every link merged since its
# base — the playbook's blind-spot rule — and it does not accumulate while
# main is held at the round's base (Mirrodin: 47 files at the first link,
# 87 by the wave-2 chain, 230 s -> 504 s).
BASE="${MEETING_BASE:-main}"
CHANGED=$(git diff --name-only --diff-filter=AM "$BASE" HEAD -- tests/; git diff --cached --name-only --diff-filter=AM -- tests/)
SETS=$(ls tests/sets/test_"${ROUND}"_*.py 2>/dev/null)
CENSUSES=""
if [ -f scripts/tests_for_diff.py ]; then
  CENSUSES=$("$PY" scripts/tests_for_diff.py --censuses --list --base "$BASE") || { echo "tests_for_diff.py failed"; exit 3; }
  echo "$CENSUSES" > "$GATE/meeting_censuses_$tag.txt"
fi
FILES=$(printf "%s\n" $CHANGED $SETS $CENSUSES $(read_list "$SCRATCH/yield.txt") $(read_list "$SCRATCH/surprises.txt") $GUARDS | grep '\.py$' | sort -u)
missing=0
for f in $FILES; do [ -f "$f" ] || { echo "NO SUCH FILE: $f"; missing=1; }; done
[ "$missing" -eq 1 ] && exit 3
echo "$FILES" > "$GATE/meeting_files_$tag.txt"
echo "meeting-point files: $(echo "$FILES" | wc -l) (changed since $BASE; $(echo "$CENSUSES" | grep -c .) registry censuses)"
"$PY" -m pytest -n "$workers" --dist worksteal -q -p no:cacheprovider $FILES > "$GATE/meeting_$tag.log" 2>&1
code=$?
echo "exit=$code" >> "$GATE/meeting_$tag.log"
echo "exit=$code  FAILED=$(grep -c '^FAILED' "$GATE/meeting_$tag.log")"
grep '^FAILED\|^ERROR' "$GATE/meeting_$tag.log" | sed 's/ - .*//' | sort
