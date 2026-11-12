#!/usr/bin/env bash
# fails_before.sh <base-ref> <test-id> <file>...
#
# Shows that a test is red with the named files at their <base-ref> version and
# green as they are — the proof a fix owes that its test can fail (a backwards
# check), without swapping files in and out of your own tree by hand.
#
#   - a throwaway detached worktree of HEAD is made in .worktrees/ (removed on
#     exit), carrying this tree's uncommitted changes too (modified, deleted
#     and untracked files, copied in), so "as they are" is this tree, not just
#     its last commit;
#   - "before": each <file> is checked out at <base-ref> there (deleted, if
#     <base-ref> has no such file) and <test-id> is run;
#   - "after": each <file> is put back as it is in this tree and the test is
#     run again.
#
# Both runs are `python -m pytest -q -p no:cacheprovider <test-id>` in the
# throwaway, with the main checkout's venv; a file or test named runs whole,
# `full`-marked tests too. Paths and the test id are relative to the tree's
# root (or to the directory you run from inside it). Logs land in
# $FAILS_BEFORE_LOGS (default .worktrees/scratch/fails_before/<time>-<pid>/).
#
# Exit: 0 proven (before exit 1, after exit 0); 1 not proven (the test passes
# with the files at <base-ref>, or fails as they are); 3 inconclusive (before
# ended some other way: 2 or 4 is a collection or usage error — often the test does
# not import against the base — 3/137 an internal error or memory, 5 nothing
# collected); 2 usage. Two runs can take minutes: wrap it in run_and_wait.sh.
set -u
usage() { echo "usage: fails_before.sh <base-ref> <test-id> <file>..." >&2; exit 2; }
[ $# -ge 3 ] || usage
base_ref=$1; test_id=$2; shift 2

TREE=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "not inside a git checkout" >&2; exit 2; }
prefix=$(git rev-parse --show-prefix)
REPO=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
if [ -x "$REPO/.venv/Scripts/python.exe" ]; then PY="$REPO/.venv/Scripts/python.exe"; else PY="$REPO/.venv/bin/python"; fi
base=$(git rev-parse --verify --quiet "$base_ref^{commit}") || { echo "$base_ref names no commit" >&2; exit 2; }
head=$(git rev-parse HEAD)

files=()
for f in "$@"; do
  rel="${prefix}${f#./}"
  if [ ! -e "$TREE/$rel" ] && ! git cat-file -e "$base:$rel" 2>/dev/null; then
    echo "$f: neither in this tree nor at $base_ref" >&2; exit 2
  fi
  files+=("$rel")
done
case "$test_id" in /*|[A-Za-z]:*) ;; *) test_id="${prefix}${test_id#./}" ;; esac

stamp="$(date +%Y%m%d-%H%M%S)-$$"
LOGS="${FAILS_BEFORE_LOGS:-$REPO/.worktrees/scratch/fails_before}/$stamp"
mkdir -p "$LOGS"
WT="$REPO/.worktrees/fails_before-$$"
git -C "$TREE" worktree add --detach "$WT" "$head" > /dev/null 2>&1 || { echo "could not create $WT" >&2; exit 2; }
cleanup() {
  cd "$REPO" || return
  git worktree remove --force "$WT" > /dev/null 2>&1 || { rm -rf "$WT"; git worktree prune; }
}
trap cleanup EXIT

# This tree's uncommitted state, carried into the throwaway.
carried=0
while IFS= read -r path; do
  [ -n "$path" ] || continue
  if [ -e "$TREE/$path" ]; then
    mkdir -p "$(dirname "$WT/$path")" && cp "$TREE/$path" "$WT/$path"
  else
    rm -f "$WT/$path"
  fi
  carried=$((carried + 1))
done < <(git -C "$TREE" diff --name-only --no-renames HEAD; git -C "$TREE" ls-files --others --exclude-standard)

run() {  # run <label> -> exit code of the test run, output in $LOGS/<label>.log
  (cd "$WT" && PYTHONIOENCODING=utf-8 "$PY" -m pytest -q -p no:cacheprovider "$test_id") > "$LOGS/$1.log" 2>&1
}
verdict() {  # verdict <exit>
  case "$1" in
    0) echo "green" ;;
    1) echo "red: $(grep -c '^FAILED' "$LOGS/$2.log") FAILED" ;;
    2|4) echo "a collection or usage error (read the log)" ;;
    5) echo "no tests collected" ;;
    *) echo "an internal error or a worker killed (memory?)" ;;
  esac
}

echo "fails_before: $test_id"
echo "  HEAD $(git rev-parse --short "$head")$( [ "$carried" -gt 0 ] && echo " + $carried uncommitted path(s) of this tree"); at $base_ref ($(git rev-parse --short "$base")): ${files[*]}"

for f in "${files[@]}"; do
  if git cat-file -e "$base:$f" 2>/dev/null; then
    git -C "$WT" checkout -q "$base" -- "$f" || { echo "could not check $f out at $base_ref" >&2; exit 2; }
  else
    rm -f "$WT/$f"
  fi
done
run before; before=$?
echo "  before (files at $base_ref): exit $before — $(verdict $before before)   log $LOGS/before.log"
grep '^FAILED\|^ERROR' "$LOGS/before.log" | sed 's/ - .*//' | head -10 | sed 's/^/    /'

for f in "${files[@]}"; do
  if [ -e "$TREE/$f" ]; then
    mkdir -p "$(dirname "$WT/$f")" && cp "$TREE/$f" "$WT/$f"
  else
    rm -f "$WT/$f"
  fi
done
run after; after=$?
echo "  after (files as they are): exit $after — $(verdict $after after)   log $LOGS/after.log"
grep '^FAILED\|^ERROR' "$LOGS/after.log" | sed 's/ - .*//' | head -10 | sed 's/^/    /'

if [ "$before" -ne 0 ] && [ "$before" -ne 1 ]; then
  echo "inconclusive: the run with the files at $base_ref ended with exit $before, not a test failing"
  exit 3
fi
if [ "$before" -eq 1 ] && [ "$after" -eq 0 ]; then
  echo "proven: red with the files at $base_ref, green as they are"
  exit 0
fi
[ "$before" -eq 0 ] && echo "not proven: the test passes with the files at $base_ref"
[ "$after" -ne 0 ] && echo "not proven: the test does not pass as the files are"
exit 1
