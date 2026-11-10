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
# MTG_PROMOTE (engine/card_loader.py) reads a measured set as shipped. A gate,
# a meeting or a tracker regeneration under it would read a pool that is not
# the tree's; only census_rehearsal.sh, which sets ALLOW_PROMOTE=1, runs under it.
if [ -n "${MTG_PROMOTE:-}" ] && [ "${ALLOW_PROMOTE:-}" != "1" ]; then
  echo "MTG_PROMOTE=$MTG_PROMOTE is set: this script reads the tree's real pool — unset it (census_rehearsal.sh is the rehearsal)" >&2
  exit 2
fi
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
