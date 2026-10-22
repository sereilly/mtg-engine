#!/usr/bin/env bash
# chain_commit.sh <group> <message-file> — commit a link's staged merge, then its trackers.
#
# Commits the merge staged by chain_stage.sh in .worktrees/$ROUND-int-<group>
# and regenerates the trackers there (regen.sh; never an --accept). Prints the
# tip, which is the base for the next chain_stage.sh. Safe while that link's
# gate is still running: it changes only generated .md files.
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
g="$1"; msg="$2"
cd "$REPO/.worktrees/$ROUND-int-$g" || exit 2
[ -n "$(git diff --name-only --diff-filter=U)" ] && { echo "unmerged files remain"; exit 1; }
git commit -q -F "$msg" || exit 1
git log --oneline -1 | cat
"$TOOLS/regen.sh" "$(echo "$g" | tr a-z A-Z)"
