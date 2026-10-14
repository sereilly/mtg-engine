---
description: The after-integration sweep once a wave's branches are all merged
---

After the last branch of a wave is merged and the link's full gate is green
(SET_PLAYBOOK.md "Integration"):

1. Duplicate-idea sweep: two branches that invented the same helper/production
   merge clean and shadow each other — grep for same-named functions and
   registry keys added this wave.
2. `./.venv/Scripts/python.exe scripts/support_report.py --set <CODE>` — the
   supported count must equal the wave's claims, and `--hollow-lines` and
   `scripts/parse_coverage.py --set <CODE>` must be clean for every card a
   group called done.
3. `./.venv/Scripts/python.exe scripts/check_all.py --freshness --caps` on the
   clean tree. No local serial run: a suite-time baseline is the runner step's
   own output and nothing else (ROADMAP.md, standing invariant 2), so it is
   read at Phase 0 from a pushed branch.
4. Line-cap check, from `--caps` above: two groups' additions can sum past the
   1,000-line grammar cap or the per-set test cap with neither at fault — split
   now, not mid-round, with the script that moves whole marked sections.
5. Every file the wave's gates surprised is in
   `scripts/meeting_point_surprises.txt` with its reason.
6. Update ROADMAP.md's live sections with what the wave changed.
