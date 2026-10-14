---
description: The between-merges gate loop for integrating a wave branch
---

Gate the branch just merged onto the link (SET_PLAYBOOK.md "Integration"). The
full suite is one run at a time on this machine, so **a merge gets the list and
a batch of merges gets the suite** — a link is not green on the list.

Per merge, as its own commit on the link:

1. Never stage a merge on a tree a test run is reading. A run owns its worktree
   until it exits; start a new link instead.
2. Resolve a conflict hunk by hunk, with a replayable script that asserts each
   region it read — never a whole-file `--theirs`/`--ours`. When both sides add
   an arm, check what the arms are arms *of*.
3. `./.venv/Scripts/python.exe scripts/oracle_diff.py compare` — read every card
   that moved; a card outside the merged group's scope is a merge hazard
   (SET_PLAYBOOK.md "silent merge hazards"). Snapshot first if none exists.
4. `./.venv/Scripts/python.exe scripts/meeting_point.py --base main --set <CODE>`
   — the changed test files, the set's own, the structural guards and every
   file a gate has surprised. Always the script, never a hand-picked list.
   Reconcile a red here in the merge, with the reason in its message.
5. If the branch edited a text-keyed table (combat_restrictions, untap/draw-step
   modifiers, cast/activation_restrictions, cost_modifiers, REPLACEMENT_LINES),
   diff that table too — the compiled map cannot see it.
6. `oracle_diff.py snapshot` again before the next merge.

Per batch (a few merges, or the wave's end), on the link:

7. Read free memory, then `./.venv/Scripts/python.exe -m pytest -n 8 --dist worksteal` once.
   Stop anything of your own that takes the machine under a gigabyte free.
   `main` fast-forwards only to a tree whose own suite was green.
8. `./.venv/Scripts/python.exe scripts/check_all.py` — every CI guard check.
9. A red the meeting-point runs did not show: bisect it by running that test on
   each link beneath, fix it on the link, and **add its file to
   `scripts/meeting_point_surprises.txt` with the reason** the same day.
10. Do not re-run a red gate and take the green. A test that fails in a full
    run and passes alone is a finding (SET_PLAYBOOK.md, the probe-after-every-
    test plugin).
