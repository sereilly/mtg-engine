#!/usr/bin/env bash
# status.sh <base-ref> <group>... — one line per group of the round.
# status.sh --wait <minutes> <base-ref> <group>... — first wait until any group's
#   commit count or scratch exit files change (or the minutes pass).
#
# Per group: commits past <base-ref>, dirty files in its worktree, the exit
# files in its scratch folder, its last commit subject. When an agent goes
# quiet, this is where to look: a green suite_exit beside an uncommitted tree
# is an agent that ended its turn on a background run and will not wake by
# itself — resume it by message.
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
cd "$REPO" || exit 2
wait_minutes=0
if [ "${1:-}" = "--wait" ]; then wait_minutes="$2"; shift 2; fi
base="$1"; shift
groups="$*"
state() {
  for g in $groups; do
    echo -n "$(git rev-list --count "$base..$ROUND/$g" 2>/dev/null) "
    ls "$SCRATCH/$g" 2>/dev/null | grep -ci exit | tr '\n' ' '
  done
}
if [ "$wait_minutes" -gt 0 ]; then
  before="$(state)"
  for _ in $(seq 1 $((wait_minutes * 3))); do sleep 20; [ "$(state)" != "$before" ] && break; done
fi
date +%H:%M
for g in $groups; do
  w=".worktrees/$ROUND-$g"
  echo "$g commits=$(git rev-list --count "$base..$ROUND/$g" 2>/dev/null) dirty=$(git -C "$w" status --short 2>/dev/null | wc -l) exits=$(ls "$SCRATCH/$g" 2>/dev/null | grep -i exit | tr '\n' ',') last='$(git log -1 --format=%s "$ROUND/$g" 2>/dev/null | cut -c1-70)'"
done
