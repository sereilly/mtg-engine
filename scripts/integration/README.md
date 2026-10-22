# Integration toolkit

The integrator's scripts for a parallel round — a set (SET_PLAYBOOK.md) or a
fix round. They lived uncommitted in `.worktrees/scratch/<round>/tools/` and
were copied forward and re-patched every set; these are the parametrized
versions. Run them from Git Bash. Every shell script needs `ROUND` set: the
branch prefix, the worktree prefix and the scratch folder
(`.worktrees/scratch/$ROUND/`). For a set it is the code in lower case.

```bash
export ROUND=ons
```

| Script | When | What |
| --- | --- | --- |
| `census_new.py CODE` | Phase 1, after the ingest | new-to-pool cards, the origin trap, unsupported cards, layouts |
| `card_table.py CODE <census-dir>` | grouping | one line per card: U / P / . with type, cost, text |
| `furthest.py CODE <groups.json> <out>` | briefing, Phase 0 round 3 | per refused line, the furthest production that accepted |
| `gen_cards.py CODE <logs> <groups.json> <out>` | briefing | each group's `CARDS.md` from the instruments' output |
| `open_test_files.py CODE <group>...` | before the fan-out | per-set test files with one marked section per group |
| `headroom.py` | briefing, every stage | modules inside the size band (`check_all --caps` without the checks) |
| `status.sh [--wait N] <base> <group>...` | while agents run | commits, dirty files, exit files per group |
| `chain_stage.sh <group> <base-ref>` | each merge | stage the merge in its own link worktree; union per-set test blocks |
| `meeting.sh <tree> <tag>` | **each merge** | the meeting-point run — the gate between merges |
| `chain_commit.sh <group> <msg-file>` | each merge | commit the link, regenerate trackers |
| `gate.sh <tree> <tag>` + `gate_report.sh <tag>` | **wave close, promotion** | the full gate: oracle_diff, scans, whole suite, check_all, support |
| `regen.sh <label>` | after any merge | regenerate every tracker (never `--accept`) and commit |
| `dups.py <files>` | each merge | a name defined twice in one scope (merge shadowing) |
| `dup_ideas.py <base>` | after a wave | a new name defined in two modules (one idea, two homes) |
| `missing_names.py <files>` | each merge | a name loaded but never defined or imported |
| `merge_blocks.py <branch>` | conflicts | append-append conflicts in per-set test files, by bytes |
| `resolve_both.py <file> <n>` | conflicts | keep both sides of exactly *n* conflicts (refuses any other count) |
| `promote.py CODE [--wrong]` | Phase 4 | the manifest move; `--wrong` is the wrong-end rehearsal |
| `checked_sim.py <out.json> <sim args>` | after touching a fast path | the simulator under `fast_paths.CHECKING` |

Two differentials sit beside them in `scripts/`: `oracle_diff.py`
(every compiled program) and `sim_fingerprint.py` (twelve seeded games,
byte-compared). A change meant to move nothing reads 0 on both.

## The gate cadence

Between merges, `meeting.sh` is the gate: every test file the merged branches
added or edited, the set's own files, the ingest's yield (`yield.txt`), every
file a full gate has surprised you with (`surprises.txt`, which only grows)
and the structural guards. In Torment it predicted every full gate. The full
gate (`gate.sh`) runs at each wave's close and on the promotion commit, and
whatever it finds that the meeting run did not goes into `surprises.txt`.

Gates write to `$GATE` (`.worktrees/scratch/$ROUND/gate/`) and never pipe
pytest through `tail`: the exit code is the command's own. Use `-n 4` (the
default) while agents are running and `-n 8` when the machine is yours; an
exit 3 or 137 with no `FAILED` line is a worker killed for memory — re-run
smaller, never read it as red.
