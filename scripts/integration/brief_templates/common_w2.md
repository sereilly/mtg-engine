<!-- The wave-2 common brief, filled by scripts/integration/write_briefs.py --wave 2.
     Derived from Darksteel's (2026-11-11). -->

# {{SET_NAME}} ({{CODE}}) wave-2 brief — the part every group shares

{{W1_SUMMARY}}

**Read `C:\Users\qwv48_66yef5i\Desktop\Magic\.worktrees\scratch\{{code}}\BRIEF_COMMON_W1.md`
first: every rule in it holds for you** (where you work, memory, the tools,
the rules of the round, running tests, finishing), with the changes below.
Then your group's `BRIEF.md`. The pile your brief is cut from is
`scratch\{{code}}\WAVE2_PILE.md`; the wave-1 reports are in
`scratch\{{code}}\reports\w1g*.md` — read the ones your brief names.

## What changes from the wave-1 brief

- **Your base is the merged wave-1 chain**, branch `{{W2_BASE}}` (each link
  gated), not the wave-1 base. Your worktree is
  `C:\Users\qwv48_66yef5i\Desktop\Magic\.worktrees\{{code}}-<group>` on branch
  `{{code}}/<group>`.
- **Your report is your final message**, not a file: a subagent cannot write
  `REPORT.md` (the tool refuses it). The integrator saves it verbatim. Same ten
  sections as wave 1's "Finishing".
- **Snapshot both differentials before your first edit**:
  `python scripts/oracle_diff.py snapshot --snapshot <scratch>\od.json` **and**
  `python scripts/sim_fingerprint.py snapshot --workers 1` (twelve seeded games, ~4 min;
  through `run_and_wait.sh`; its default is four processes at ~1.5 GB each, and a
  wave's groups snapshotting at once would exhaust the machine). Compare both at the end. Three wave-1 groups had
  to rebuild a base snapshot from an export because nobody asked for this one.
  An AI group's change is *expected* to move seeded games — name each game
  that moved and why.
- **Never `sed -i` a source file**: in Git Bash it rewrites CRLF files as LF
  (two wave-1 groups hit it twice each). Use the Edit tool, or a script that
  reads bytes and writes the same line ending back.
- **Per-set test sections**: wave 1's sections are closed. Put a wave-2 test of
  a {{SET_NAME}} card at the **end** of the per-set file for its printed type,
  under your own markers (`# ==== W2Gn ====` … `# ==== end W2Gn ====`, prefix
  helpers `_w2gN_`); anything else in a file of your own in `tests/ui/`,
  `tests/ai/`, `tests/regressions/` or `tests/rules/` (`test_{{code}}_w2gN_*.py`).
- **The reds on your base** (`{{W2_BASE}}`), the only ones you should see:
{{BASE_REDS}}
  - Anything else red on your base is a finding: report it the day you see
    it (a message to the integrator is fine — just keep working).
- **`tests_for_diff.py` does not name every census your change reaches.**
  Darksteel's W1G3 was red in `tests/ai/test_ai_graveyard_denial.py` on its
  own branch, a census no list named. When you change what a seat chooses, grep
  `tests/ai/` for the function names and the card names your change reaches
  and run those files by name.
- **Promotion rehearsal**: the integrator is running the promotion in memory
  (`MTG_PROMOTE={{CODE}}`) over the whole quick pass and every sampled census as
  you start; any red it finds in your subject arrives by message.

## Memory

About 35–43 GB of commit is free; three agents plus the integrator's gates.
Keep wave 1's rules: pytest serially, one heavy process at a time, `-n 2` only
for the one `tests/engine` run.
