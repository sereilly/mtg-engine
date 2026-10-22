---
description: The after-integration sweep once a wave's branches are all merged
---

After the last branch of a wave is merged (SET_PLAYBOOK.md "Integration";
`export ROUND=<round>`):

1. Duplicate-idea sweep: `scripts/integration/dup_ideas.py <wave-base>` — two
   branches that invented the same helper, field or production merge clean and
   then shadow each other or keep two mechanisms for one fact. Also scan merged
   modules for a module-level constant assigned twice.
2. `./.venv/Scripts/python.exe scripts/support_report.py --set <CODE>` — the
   supported count must equal the wave's claims, and `--hollow-lines` must be
   clean for every card a group called done.
3. The full gate on the wave's last link: `scripts/integration/gate.sh <link>
   <tag>`, then `gate_report.sh <tag>`; add every red file the meeting runs did
   not hold to `surprises.txt`. Then `scripts/check_all.py --freshness` on the
   clean tree. CI's numbers are per shard and come only from a pushed run
   (`gh run view <id> --log | grep "suite wall time"`).
4. Size check: `scripts/integration/headroom.py` — two groups' additions can sum
   into the 200-line band below the 2,000-line module cap (or past the per-set
   test cap) with neither at fault. Split now, not mid-round.
5. Update ROADMAP.md's live sections with what the wave changed.
