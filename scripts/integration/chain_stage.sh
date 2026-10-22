#!/usr/bin/env bash
# chain_stage.sh <group> <base-ref> — stage one branch's merge in its own link worktree.
#
# Creates .worktrees/$ROUND-int-<group> on branch $ROUND/int-<group> at
# <base-ref>, snapshots oracle_diff there, and stages `git merge --no-commit`
# of $ROUND/<group>. Append-append conflicts in per-set test files are
# resolved by merge_blocks.py; anything else is left for a hand resolution,
# hunk by hunk. A chain of links lets one link's gate run while the next is
# being built; main only fast-forwards to a link whose own gate was read.
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
cd "$REPO" || exit 2
g="$1"; base="$2"; b="$ROUND/$g"; w=".worktrees/$ROUND-$g"; int=".worktrees/$ROUND-int-$g"
if [ -d "$w" ]; then
  dirty=$(git -C "$w" status --short | grep -v "^??" | wc -l)
  [ "$dirty" -ne 0 ] && { echo "UNCOMMITTED WORK in $w"; git -C "$w" status --short | head; exit 1; }
fi
git worktree add "$int" -b "$ROUND/int-$g" "$base" > /dev/null 2>&1 || { echo "could not create $int"; exit 1; }
cd "$int" || exit 2
echo "base: $(git log --oneline -1 | cut -c1-70)"
"$PY" scripts/oracle_diff.py snapshot 2>&1 | tail -1
git merge --no-ff --no-commit "$b" 2>&1 | grep -E "CONFLICT|went well|Already|fatal"
U=$(git diff --name-only --diff-filter=U)
if [ -n "$U" ]; then
  if echo "$U" | grep -q "^tests/sets/test_"; then "$PY" "$TOOLS/merge_blocks.py" "$b"; fi
  U=$(git diff --name-only --diff-filter=U)
  if [ -n "$U" ]; then echo "--- STILL UNMERGED in $int (resolve by hand, hunk by hunk):"; echo "$U"; exit 1; fi
fi
echo "--- staged in $int:"; git diff --cached --stat | tail -1
"$PY" "$TOOLS/headroom.py"
true
