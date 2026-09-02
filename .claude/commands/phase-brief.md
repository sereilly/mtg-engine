---
description: Assemble a wave-group brief from the census instruments
---

Assemble the brief for the named group from instrument output, not memory
(SET_PLAYBOOK.md Phase 2/3 — roughly a third of every hand-written brief has
been wrong):

1. `./.venv/Scripts/python.exe scripts/support_report.py --set <CODE> --refusals --fragments`
   — group by the fragments' cards column, never by a shared word.
2. A refusal site is a work-list entry, not a diagnosis: probe each sentence and
   record which *layer* fails (parse / lowering / no handler / front end).
3. `./.venv/Scripts/python.exe scripts/picker_sweep.py --set <CODE>` and
   `scripts/behaviour_classes.py --set <CODE>` for the picker and
   lands-in-an-existing-class questions.
4. Every brief carries the standing paragraphs from SET_PLAYBOOK.md Phase 3
   (differential, Rock Hydra test via `run_ai_simulation(required=…)`, caps).
