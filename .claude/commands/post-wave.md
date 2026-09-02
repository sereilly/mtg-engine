---
description: The after-integration sweep once a wave's branches are all merged
---

After the last branch of a wave is merged (SET_PLAYBOOK.md "Integration"):

1. Duplicate-idea sweep: two branches that invented the same helper/production
   merge clean and shadow each other — grep for same-named functions and
   registry keys added this wave (memory: parallel-merge-shadowing).
2. `./.venv/Scripts/python.exe scripts/support_report.py --set <CODE>` — the
   supported count must equal the wave's claims, and `--hollow-lines` must be
   clean for every card a group called done.
3. `./.venv/Scripts/python.exe scripts/check_all.py --freshness` on the clean
   tree, plus `python -m pytest` (serial once, for a CI-comparable number).
4. Line-cap check: two groups' additions can sum past the 1,000-line grammar
   cap or the per-set test cap with neither at fault — split now, not mid-round.
5. Update ROADMAP.md's live sections with what the wave changed.
