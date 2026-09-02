---
description: The between-merges gate loop for integrating a wave branch
---

Run the merge gate for the branch just merged (SET_PLAYBOOK.md "Integration"):

1. `./.venv/Scripts/python.exe scripts/oracle_diff.py compare` — read every card
   that moved; a card outside the merged group's scope is a merge hazard
   (SET_PLAYBOOK.md "silent merge hazards"). Snapshot first if none exists.
2. `./.venv/Scripts/python.exe -m pytest -n auto` — full suite, parallel.
3. `./.venv/Scripts/python.exe scripts/check_all.py` — every CI guard check.
4. If the branch edited a text-keyed table (combat_restrictions, untap/draw-step
   modifiers, cast/activation_restrictions, cost_modifiers, REPLACEMENT_LINES),
   diff that table too — the compiled map cannot see it.
5. `oracle_diff.py snapshot` again before the next merge.
