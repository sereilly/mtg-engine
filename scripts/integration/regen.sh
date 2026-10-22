#!/usr/bin/env bash
# regen.sh <label> — regenerate every tracker in the current tree and commit them.
#
# Never an --accept: a ratchet that moved is a decision, made by hand after
# reading it. Git's union of two branches' regenerations is not a regeneration
# of the merged tree, so this runs after every merge, even a clean one.
source "$(dirname "${BASH_SOURCE[0]}")/_env.sh"
label="$1"
for s in grammar_coverage hook_reliance parse_coverage set_progress behaviour_classes rules_progress; do
  "$PY" scripts/$s.py > /dev/null 2>&1
done
git add GRAMMAR_COVERAGE.md HOOK_RELIANCE.md PARSE_COVERAGE.md SET_PROGRESS.md BEHAVIOUR_CLASSES.md RULES_PROGRESS.md
if git diff --cached --quiet; then
  echo "trackers already fresh"
else
  git commit -q -m "Regenerate trackers after the $label merge

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1 | cat
fi
git status --short | head -5
