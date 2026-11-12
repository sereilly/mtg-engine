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
| `census.sh CODE [tree]` | Phase 1, after the ingest | every census instrument, serially, under the file names `gen_cards.py` / `card_table.py` / `furthest.py` read |
| `bulk_rulings.py CODE <out>` | briefing | every ruling for the set's cards from Scryfall's bulk file (one download; the per-card fetch is rate-limited) |
| `check_brief_crs.py [--strict] <repo> <briefs>` | before sending a brief | each cited CR number with its rule's opening words, and `SUBJECT?` for a citation whose rule shares no word with its sentence; exit 1 on a number the CR lacks (`--strict`: on a `SUBJECT?` too) |
| `census_new.py CODE` | Phase 1, after the ingest | new-to-pool cards, the origin trap, unsupported cards, layouts |
| `../tests_for_diff.py --ingest CODE` (`--run -n N`, `--list`, `--why`) | **Phase 1, first, right after the ingest** | the ingest's yield named before it runs: every test whose population walks the measured set (`scripts/measured_censuses.py`), by node id, with recorded times; `--run` is the full pass over them (`pytest --full`), longest file first. Darksteel's 13 reds were in its 495 tests (224 files, 3,440 recorded s, against the full pass's ~14,600) — save the reds as `yield.txt` and hand them over in the briefs |
| `card_table.py CODE <census-dir>` | grouping | one line per card: U / P / . with type, cost, text |
| `furthest.py CODE <groups.json> <out>` | briefing, Phase 0 round 3 | per refused line, the layer that refused it (`scripts/probe_line.py`'s verdict) and, where the grammar refused, the furthest production that accepted |
| `write_briefs.py CODE --groups <groups.json> --census <dir> --out <scratch> [--yield YIELD.md]` (`--wave 2 --w2-base <link> --base-reds <file>`) | briefing | the common brief from `brief_templates/` (the rules once; the census's counts, hollow cards, keyword reading, groups, base, size band, per-set sections and yield filled) and a skeleton `BRIEF.md` per group; TODO lines are the integrator's |
| `gen_cards.py CODE <logs> <groups.json> <out>` | briefing | each group's `CARDS.md` from the instruments' output |
| `open_test_files.py CODE <group>...` | before the fan-out | per-set test files with one marked section per group |
| `headroom.py` | briefing, every stage | modules inside the size band (`check_all --caps` without the checks) |
| `status.sh [--wait N] <base> <group>...` | while agents run | commits, dirty files, exit files per group |
| `chain_stage.sh <group> <base-ref>` | each merge | stage the merge in its own link worktree; union per-set test blocks |
| `MEETING_BASE=$(git merge-base <link> <branch>) meeting.sh <tree> <tag>` | **each merge** | the meeting-point run — the gate between merges; its changed-files list read from the branch's merge-base, plus every census over a registry the merge moved (`scripts/tests_for_diff.py --censuses`) |
| `chain_commit.sh <group> <msg-file>` | each merge | commit the link, regenerate trackers |
| `gate.sh <tree> <tag> [workers] [quick\|full]` + `gate_report.sh <tag>` | **wave close, promotion** | the full gate: oracle_diff, scans, whole suite (the quick pass; `full` on the promotion commit), check_all, support |
| `census_rehearsal.sh <tree> <tag> CODE [workers] [catalog\|sampled\|both]` | **wave close, before the promotion's full pass** | the promotion in memory (`MTG_PROMOTE=CODE`): the quick pass whole and every sampled census whole; the shipped-pool guards' reds listed apart |
| `fails_before.sh <base-ref> <test-id> <file>...` | a fix's backwards check | the test run twice in a throwaway worktree of HEAD (carrying the tree's uncommitted changes): with the files at `<base-ref>`, then as they are; both exit codes, exit 0 only for red-then-green (1 not proven, 3 inconclusive: the base run ended other than pass/fail); wrap it in `run_and_wait.sh` |
| `run_and_wait.sh <log> <cmd...>` / `--wait <log>` | any run over ~3 min | the command detached, its exit code the log's last line and `<log>.exit`; a bounded wait (`RUN_WAIT`, 170 s) that exits with the command's code, or 75 "still running" with the resume command |
| `regen.sh <label>` | after any merge | regenerate every tracker (never `--accept`) and commit |
| `dups.py <files>` | each merge | a name defined twice in one scope (merge shadowing) |
| `extract_reports.py <out> <transcript|dir> --groups <agents.json>` | each report, the day it lands | every subagent's hand-back report out of the session transcript (a subagent cannot write a report file), one `<group>.md` each; names the groups still owed |
| `dup_ideas.py <base>` | after a wave | a new name defined in two modules (one idea, two homes) |
| `missing_names.py <files>` | each merge | a name loaded but never defined or imported |
| `merge_blocks.py <branch>` | conflicts | append-append conflicts in per-set test files, by bytes |
| `wordmerge_rows.py <file> <branch>` | conflicts | conflicted table rows (`engine/ARCHITECTURE.md`'s module table) merged word by word against the merge base; aborts on a word-level conflict |
| `resolve_both.py <file> <n>` | conflicts | keep both sides of exactly *n* conflicts (refuses any other count) |
| `promote.py CODE [--wrong]` | Phase 4 | the manifest move; `--wrong` is the wrong-end rehearsal |
| `checked_sim.py <out.json> <sim args>` | after touching a fast path | the simulator under `fast_paths.CHECKING`; every `simulate_ai_games.py` flag passes through, `--require "Card A,Card B"` (cards pinned into both decks, checked against the pool) among them |
| `board.py` (import it) | probes | `card(name)`, `place(game, seat, name)`, `table(hand=…, mine=…, theirs=…)`, `tail(game)`: a headless two-seat game over both manifest roles |
| `serve_board.py --port N --cmd <dir> [--reload]` | client work | the real web app plus a command folder: a dropped `.py` runs under the session's lock (`# sid=<id>` first line) and the board redraws; `--reload` restarts the app on an `engine/`/`web/` change with every session kept (`board_pickle.py`), the page left open. Click a card by id with the page's `__boardPoint` (the `run-magic` skill) |

Two differentials sit beside them in `scripts/`: `oracle_diff.py`
(every compiled program; a card moved only by a new defaulted field's spelling
is counted on that field's line, not as a move, and `compare --against B`
reads two stored snapshots) and `sim_fingerprint.py` (twelve seeded games,
byte-compared; a compare keeps each moved run's whole diff and new log under
`.sim_fingerprint/compare/`, and `snapshot --rev <commit>` plays the base in a
throwaway worktree when the edit came first). A change meant to move nothing
reads 0 on both. `scripts/probe_line.py` prints a lowering refusal's innermost
raise site beside its message, and `--ast` each line's parsed tree.
So does the test picker, `tests_for_diff.py`: the tests a diff owes, with
their recorded times — what an agent runs instead of grepping, and what
`meeting.sh` takes its registry censuses from. With no `--base` it reads the
diff from `$MTG_DIFF_BASE`, else from where the branch started (its reflog),
else the merge-base with `main`, and prints which; a brief for a branch cut
from a chain link need say nothing (Darksteel's W2G3 listed 512 files against
`main`). While a set is measured it also lists, by node id, every test whose
population walks it (`--no-measured` leaves them off): Darksteel's three
blind-spot reds (W1G3's graveyard-denial and conditional-grants censuses,
W1G5's upkeep window) were each among them, red in a quick run on the branch
that caused it. `simulate_ai_games.py --require "Card A,Card B"` pins cards
into both decks (`run_ai_simulation(required_cards=...)`) — the wrapper ten
of Darksteel's twelve groups wrote.

**Every script that sources `_env.sh` refuses to run under `MTG_PROMOTE`**
(the in-memory promotion): a gate, a meeting or a regeneration would read a
pool that is not the tree's. `census_rehearsal.sh` is the one that runs
under it.

## The gate cadence

Between merges, `meeting.sh` is the gate: every test file the merged branches
added or edited, the set's own files, the ingest's yield (`yield.txt`), every
file a full gate has surprised you with (`surprises.txt`, which only grows)
and the structural guards. In Torment it predicted every full gate. The full
gate (`gate.sh`) runs at each wave's close and on the promotion commit, and
whatever it finds that the meeting run did not goes into `surprises.txt`.
Its suite is the quick pass, except on the promotion commit, where it is the
full pass (`gate.sh <tree> <tag> <workers> full`: `pytest --full`).

Gates write to `$GATE` (`.worktrees/scratch/$ROUND/gate/`) and never pipe
pytest through `tail`: the exit code is the command's own. Use `-n 4` (the
default) while agents are running and `-n 8` when the machine is yours; an
exit 3 or 137 with no `FAILED` line is a worker killed for memory — re-run
smaller, never read it as red.
