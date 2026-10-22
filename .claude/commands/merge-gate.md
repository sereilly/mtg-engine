---
description: The between-merges gate loop for integrating a wave branch
---

Run the gate for one branch's merge (SET_PLAYBOOK.md "Integration";
`scripts/integration/README.md`). `export ROUND=<round>` first.

1. `scripts/integration/chain_stage.sh <group> <base-ref>` — stages the merge in
   its own link worktree (`.worktrees/$ROUND-int-<group>`), snapshots
   `oracle_diff` there, unions per-set test blocks, and prints the size band.
   Resolve anything still unmerged by hand, hunk by hunk: read both sides for
   what each *adds*, and union unless they genuinely contradict.
2. In the link: `./.venv/Scripts/python.exe scripts/oracle_diff.py compare` —
   read every card that moved; a card outside the merged group's scope is a
   merge hazard. If the branch edited a text-keyed table (combat_restrictions,
   untap/draw-step modifiers, cast/activation_restrictions, cost_modifiers,
   REPLACEMENT_LINES), diff that table too — the compiled map cannot see it.
   For a merge meant to move no behaviour, `scripts/sim_fingerprint.py compare`
   must read 0 moved.
3. `scripts/integration/dups.py` and `missing_names.py` over the changed files
   (a name bound twice in one scope merges without a conflict).
4. `scripts/integration/meeting.sh <link> <tag>` — **the gate between merges**:
   the changed test files, the set's files, the yield, `surprises.txt` and the
   structural guards. Never a hand-picked list.
5. `scripts/integration/chain_commit.sh <group> <msg-file>` — commit, regenerate
   trackers (never `--accept`). Its tip is the next link's base.
6. At a wave's close and on the promotion commit only:
   `scripts/integration/gate.sh <tree> <tag>` (the whole suite, `-n 4` while
   agents run, `-n 8` otherwise) and `gate_report.sh <tag>`. Every red file the
   meeting run did not hold goes into `surprises.txt`. `main` fast-forwards only
   to a link whose gate was read.
