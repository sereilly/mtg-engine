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
5. And the four from "Integration" that are about the machine and the merge,
   not the cards:
   - **Never the full suite.** Run the files you wrote, every test file you
     edited and the files covering the modules you touched, serially or at
     `-n 2`, and list them. `scripts/meeting_point.py --base <your base> --list`
     prints the guards that sit far from your code.
   - **Commit as soon as the first card lands**, so an interrupted wave resumes
     from a branch and not from a transcript.
   - **Write only inside your marked section** of each per-set test file, with
     your imports at the top of your own block.
   - **Report every red on your base** beyond the ones this brief names. That
     list is the earliest gate there is.

At most five agents at once; hold the rest of the wave and start each as a slot
frees.
