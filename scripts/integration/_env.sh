# Shared settings for the integration scripts. Sourced, never run.
#
#   ROUND  the round's name — a set code in lower case for a set (`ons`), or a
#          name for a fix round (`r5`, `cap`). It is the branch prefix
#          (`$ROUND/w1g3`), the worktree prefix (`.worktrees/$ROUND-w1g3`) and
#          the scratch folder (`.worktrees/scratch/$ROUND`). Required.
#
# REPO is the *main* checkout even when a script runs inside a worktree, because
# the venv, the scratch folder and every worktree hang off it.

: "${ROUND:?set ROUND to the name of the round, e.g. ROUND=ons}"
REPO=$(cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
TOOLS="$REPO/scripts/integration"
SCRATCH="$REPO/.worktrees/scratch/$ROUND"
GATE="$SCRATCH/gate"
if [ -x "$REPO/.venv/Scripts/python.exe" ]; then
  PY="$REPO/.venv/Scripts/python.exe"
else
  PY="$REPO/.venv/bin/python"
fi
export PYTHONIOENCODING=utf-8
mkdir -p "$GATE"
