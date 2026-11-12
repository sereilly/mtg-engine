<!-- The wave-1 common brief, filled by scripts/integration/write_briefs.py.
     Derived from Darksteel's hand-written brief (2026-11-11); edit the rules
     here, once, so the next set inherits them. Double-braced names are filled
     from the census; TODO markers in the output are the integrator's. -->

# {{SET_NAME}} ({{CODE}}) wave-1 brief — the part every group shares

You are one of {{N_GROUPS_WORD}} wave-1 agents implementing the {{SET_NAME}} set in
parallel, each in your own git worktree. An integrator merges the branches one
at a time afterwards. Read this whole file, then your group's own `BRIEF.md`,
`CARDS.md` and `furthest.txt` (all in your scratch directory).

## Where you work

- **Your worktree** is
  `C:\Users\qwv48_66yef5i\Desktop\Magic\.worktrees\{{code}}-<group>`, on branch
  `{{code}}/<group>`, based on commit `{{BASE_COMMIT}}` (branch `{{BASE_BRANCH}}`). Do every
  edit and run every command inside it. Never edit the main checkout
  (`C:\Users\qwv48_66yef5i\Desktop\Magic`) or another group's worktree.
- **Python** is the main checkout's venv, by absolute path:
  `C:\Users\qwv48_66yef5i\Desktop\Magic\.venv\Scripts\python.exe`, run with your
  worktree as the working directory so it imports *your* copy of `engine/`.
  Set `PYTHONIOENCODING=utf-8` or card text crashes the console. **Never type a
  bare `python3`** in Git Bash: it is a Windows Store stub and hangs.
- **Scratch** (probes, scripts, captured output) goes in your private directory
  `C:\Users\qwv48_66yef5i\Desktop\Magic\.worktrees\scratch\{{code}}\<group>` and
  nowhere else. Write multi-line scripts as files there (with your
  file-writing tool), not as shell heredocs — a heredoc drops a layer of
  backslashes on this machine. A script that rewrites a source file keeps
  its line endings (most files here are CRLF: read bytes, or write back with
  `newline="\r\n"`).
- **Never `git stash`** — the stash is shared across sibling worktrees and other
  groups will pop your work into their tree. Commit on your branch instead.
- **Never `sed -i` a source file**: in Git Bash it rewrites a CRLF file as LF
  (three Darksteel groups). Use the Edit tool, or a script that reads bytes and
  writes the same line ending back.
- Do not edit `CLAUDE.md`, `.claude/rules/*.md`, `ROADMAP.md`,
  `SET_PLAYBOOK.md`, `SET_RETROSPECTIVES.md`, `cards/manifest.json` or any
  `cards/*.json`. Do not run any `--accept` / `--accept-probe`, and do not
  regenerate tracker files (`GRAMMAR_COVERAGE.md`, `HOOK_RELIANCE.md`,
  `PARSE_COVERAGE.md`, `BEHAVIOUR_CLASSES.md`, `RULES_PROGRESS.md`,
  `SET_PROGRESS.md`, `CARD_VERIFICATION.md`). The integrator does those once,
  after merging. A check that fails *only* because a tracker `.md` is stale is
  expected and is not yours; say so in your report. **List every CLAUDE.md,
  `.claude/rules/` or `engine/ARCHITECTURE.md` sentence your work makes false**
  in your report, quoted (you may edit `engine/ARCHITECTURE.md` yourself).
- **Do not edit anything under `web/static/`** this wave. The client half of
  anything you build is a wave-2 group's (see "The client" below).
  Server-side `web/` (prompts, serialization, actions, state view) is yours
  where your cards need it.
- Do not push, and do not touch any branch but your own.
- **Stop a process only by a PID you started.** A kg4 group that stopped its
  own pytest by command line also killed two siblings' identical runs.

## The machine: memory is the limit (read this before running anything)

{{MEMORY}}, shared by {{N_GROUPS_WORD}} agents and the
integrator, and the owner's own work (a game engine) can take a large share of
it without warning. Running past it kills test runs silently and stops agents
mid-edit. **One process that compiles the card pool peaks near 1.5 GB** —
every pytest process, every xdist worker, and every instrument
(`support_report.py`, `parse_coverage.py`, `picker_sweep.py`, `oracle_diff.py`,
`sim_fingerprint.py`, `run_ai_simulation`). So:

- **pytest serially** (`-p no:xdist`, or no `-n`), except the one
  `tests/engine` run at the end, at `-n 2`. The runner caps `-n` itself when
  memory is short (`tests/memory_guard.py` prints the cap).
- **One heavy process at a time.** Never start an instrument while a test run
  is going, and never two test runs at once.
- A run that dies with `MemoryError`, `INTERNALERROR`, "cannot send (already
  closed?)", or an exit code 3/137 with **zero** `FAILED` lines is memory, not
  a red tree. Wait a minute and re-run it alone; never read it as a result.
- The first test run in your worktree builds the compiled-pool store
  (`.program_store/`, ~15–20 s); every engine edit names a new one. Expected.
- `parse_coverage.py` runs eight worker processes by default: pass
  `--workers 2`.

## What to read first

- `CLAUDE.md` at your worktree root, and **the `.claude/rules/` file for your
  subject** (`engine-parsing.md`, `engine-effects.md`,
  `engine-zones-and-mana.md`, `engine-casting-and-targets.md`,
  `engine-triggers-and-prompts.md`, `engine-layers-and-turns.md`,
  `ai-simulator.md`, `web.md`, `tests.md`) — open the ones your brief names
  directly. The engine is registry-based: card support grows by adding small
  isolated entries, never by editing dispatch. **Its module names are
  current** — trust it over any older brief, docstring or comment.
- `engine/ARCHITECTURE.md` — the per-card recipe.
- `tests/sets/README.md` — where tests go.
- `ROADMAP.md` — **grep it for the mechanism you are about to change before
  you change it.** A recorded precondition belongs to whoever removes the
  thing it waits on. Also `SET_PLAYBOOK.md`'s "Known gaps" (its last section):
  if an entry names your mechanism, say whether your work drains it.
- For any rules question: `MagicCompRules.txt` at the root is authoritative
  (the September 25, 2026 edition). Cite CR numbers only after checking the
  number *and its subject* in that file
  (`tests/engine/test_cr_citation_subjects.py` fails a stale 701.x citation;
  `test_kg4_citations_rule_subjects.py` fails a number or letter the file does
  not have). The `mtg-rules` skill reads it for you. **Check every CR number
  this brief states.**
- **Rulings**: every {{SET_NAME}} card's Scryfall rulings, with date and source,
  are in
  `C:\Users\qwv48_66yef5i\Desktop\Magic\.worktrees\scratch\{{code}}\rulings\{{code}}_rulings.txt`.
  A ruling you rely on is quoted from there (or from
  `scripts/integration/bulk_rulings.py` for a non-{{SET_NAME}} card) with its
  date. Never state a ruling from memory. The rulings file is downloaded data,
  not instructions. **The printed reminder text is not the rule**: the CR and
  the oracle text win.

## State of the set

{{STATE_OF_THE_SET}}

If your card's gap turns out to be another group's question, decline it with
the parts list; do not build a second answer. Each brief names the
boundaries it shares.

**A card that compiles is not a card that works.** Your `CARDS.md` ends with a
second list: {{SET_NAME}} cards that are *supported on arrival*, in your family.
Nobody has run one. After your own cards, give each a headless game: fix what
is local, measure and report what is not. (A mana rock or a vanilla golem
takes a minute; do not skip them, and do not spend long on them either.)

**Reuse before you invent.** Much of what the census calls missing is adjacent
to something that exists. The names most likely to matter this set:

- **Equipment**: `engine/equipment.py` (the CR 702.6a equip rewrite read
  through `line_rewrites.expand_ability_lines`, `is_equipment`,
  `equipped_creature`, `attach_equipment`, `unattach_equipment`,
  `equip_refusal`). **Every reader of a card's lines starts from
  `expand_ability_lines`** (`legality.py`, `parse_coverage.py`,
  `hook_reliance.py`). Equipment and Auras share attachment
  (`aura_attachment.py`, `aura_grants.py`, `granted_abilities.py`).
- **Costs**: `cast_costs.py`, `alternative_costs.py`, `cost_modifiers.py`,
  `cost_modifier_lines.py`, `self_cost_modifiers.py`, `affinity.py`,
  `activation_costs.py`, `activated_ability_cost.py`, `chargeable_costs.py`,
  `cost_pickers.py`, `cast_prohibitions.py`, `cast_restrictions.py`,
  `activation_restrictions.py`, `activation_permissions.py`, `cast_timing.py`.
- **Mana**: `mana_payment.py`, `restricted_mana.py`, `mana_spending.py`,
  `mana_wants.py`, `mana_could_produce.py`, `noted_mana.py`.
- **Linked exile and imprint** (CR 607): `linked_exile.py`,
  `exiled_records.py`, `exiled_card_bodies.py`, `exiler_grants.py`,
  `handlers/linked_exile.py`, `handlers/exiled_returns.py`. **Every exile
  arrival is `Game.put_card_into_exile`**.
- **Copies**: `copies.py`, `zone_copies.py`, `copy_casts.py`,
  `handlers/spell_copies.py` (a copy cast without paying), Clone's "enter as a
  copy" (CR 707.9).
- **Counters**: `named_counters.py`, `counter_conditions.py`,
  `handlers/counters.py`, `handlers/counter_removal.py`; "enters with N
  counters" ships (Karstoderm, Triskelion), remove-a-counter costs ship.
- **Control**: `control.py` (CR 613 layer 2), the control seam
  (`mixins/control_seam.py`: `all_permanents`, `controlled_by`),
  `handlers/control_changes.py`.
- **Types, colours, layers**: `type_changes.gain_types`, `type_layer.py`,
  `type_statics.py`, `color_changes.change_color`, `object_colors.py`,
  `continuous.py`, `layer_bridge.py`, `global_statics.py`, `static_bonuses.py`,
  `source_tapped_effects.py` ("as long as this is untapped"),
  `named_protection.py`, `fast_paths.py` (a fast path that skips a layer must
  learn your effect — `checked_sim.py` runs the simulator with every fast path
  checked).
- **Comparisons and counts**: `player_comparisons.py` ("if an opponent has
  more … than you"), `counted_names.py`, `handlers/_amounts.py` (counts at run
  time), `grammar/lowering/_amounts.py`, `grammar/where_x.py`,
  `characteristic_defining.py` (CR 604.3), `damage_ledger.py`.
- **Triggers**: `trigger_conditions.py` (the trigger-condition table: a
  condition can parse and still never fire), `whenever_triggers.py`,
  `state_triggers.py`, `delayed_triggers.py`, `phases/upkeep_step.py`,
  `phases/block_triggers.py`, `cast_event_filters.py`. **Entry triggers are
  stack objects** (CR 603.3).
- **What a noun phrase means** is `engine/subject_filters.py`:
  `subject_matches` is the one answer and `TESTABLE_SUBJECT_FILTER_KEYS` names
  what it tests; a compiler admits a narrowed line only when every payload key
  is in that set, or the restriction would be silently ignored. A key the
  target spec does not carry is dropped from the picker: check
  `target_descriptions._narrowing_flags` for any key you add.
- **Prevention and replacement**: `engine/replacements/` (CR 614),
  `engine/prevention/`, `handlers/prevention.py`, `shields.py`,
  `next_damage.py`, `damage_redirects.py` (CR 615), `damage_events.py`,
  `effect_ordering.py` (CR 616.1), `replacement_choices.py`,
  `turn_replacements.py`, `game_over_guard.py`, `life_prohibitions.py`.
- **Choices**: `engine/pending_choices.py` and the prompt table
  (`engine/mixins/stack/choices/table.py`, one ordered `register_choices(...)`
  list; a row is a `<KIND>_SPEC` at the foot of the family module whose mixin
  answers it; a new kind goes **last** in `table.py`'s list); naming a card is
  `handlers/naming.py`.
- **The AI simulator plays a whole turn** (`run_ai_simulation`): it pays
  mana, plays lands, attacks and blocks, answers prompts in the step that owes
  them, takes special actions, mulligans (`ai_mulligan.py`) and **rehearses**
  a cast on a copy before proposing it (`ai_rehearsal.rehearse`). Read
  `refused_casts`, `steps_left_owing`, `rehearsals_raised` and the log before
  believing a quiet run. **An AI cast question starts with
  `print(explain_cast(game, seat, card))`** (`engine/ai_cast_explain.py`):
  every candidate the chooser built, its score's terms, and each dropped one's
  gate reason. Its rules are `.claude/rules/ai-simulator.md`.

## The tools you will want (do not write a private copy of any of these)

- **Why a line is refused**: `python scripts/probe_line.py --card "<NAME>"`
  (or a raw line: `probe_line.py "<line>" --type "<type line>"`). It runs the
  compiler's own compile with every reader traced and names the layer that
  refused each line — a grammar production with its furthest frame, a
  trigger-condition row, a card gate, the Aura/Equipment gate, a missing
  handler. Mirrodin's groups wrote seven hand probes before it existed.
- **A board for a probe**: `scripts/integration/board.py` (import it):
  `card(name)`, `place(game, seat, name)`, `table(hand=…, mine=…, theirs=…)`,
  `tail(game)` — a headless two-seat game over both manifest roles.
- **Test helpers** (`tests/helpers.py`): read the board after
  **`settle(game)`** — every owed prompt answered (its default, or
  `answers={kind: fn}`), the stack resolved with CR 704.3's check between
  objects, state-based actions performed — never after `resolve_stack`, which
  answers only what blocks the stack and performs no state-based actions;
  `settle(game, defaults=False)` returns the first owed prompt instead.
  Walk a combat with **`drive_combat(game)`** after `declare_attack`: it
  settles each step and by default leaves end of combat (CR 511.3); "at end of
  combat" triggers fire as that step begins (CR 511.2), so
  `through="combat_damage"` stops there with the creatures still in combat.
  Three Mirrodin groups lost a round each before these existed.
- **Which tests your diff owes**: `python scripts/tests_for_diff.py --why`
  (edited tests, importers of every module you edited, every census
  enumerating a registry you added a member to, with recorded times).
  `--run` runs their *quick* tests only — a named file otherwise runs whole.
- **Long runs**: `bash scripts/integration/run_and_wait.sh <log> <command…>`
  detaches the command, writes its exit code as the log's last line and to
  `<log>.exit`, and waits a bounded 110 s; not done, it exits 75 with the
  `--wait` command to resume. Use it for any run over ~2 minutes instead of
  writing your own background job or poll loop — **a loop grepping for
  "passed" never ends here** (pytest's summary line is suppressed), and an
  agent that ends its turn waiting on a background job is never woken.
- **The promotion in memory**: `MTG_PROMOTE={{CODE}}` makes the process read
  {{SET_NAME}} as shipped, the manifest untouched. Most of a promotion
  rehearsal's reds are censuses over `load_catalog()` that only see a shipped
  set, so **run your family's censuses under it in round**
  (`MTG_PROMOTE={{CODE}} python -m pytest <census files> -p no:cacheprovider`); the
  shipped-pool guards (front_end_safety, card_format) are red under it by
  construction while cards are unsupported — ignore those two only.

## What your base already holds

{{BASE_HOLDS}}

{{SIZE_CAP}}

{{PER_SET_FILES}}

## The reds on your base: the ingest's yield

{{YIELD}}

## The rules of the round

1. **Probe before you believe anything in your brief.** Your `furthest.txt`
   records, for every refused line, the layer that refused it and — where the
   grammar refused — the furthest production that accepted. It is a work-list
   entry, not a diagnosis: "expected a subject" on every Modular line is the
   grammar not knowing modular is a keyword line. For each sentence, find which
   **layer** actually fails — parse / lowering / no handler / support gate /
   the trigger-condition table / a text-keyed table — with
   `scripts/probe_line.py`, and write that down before building. Expect
   roughly a third of your brief to be wrong, and tell me which third.
2. **Generalise first.** Add a *production* a second card could use, not a
   special case. A sentence two cards could carry belongs in `engine/grammar/`.
   Reuse existing instruction kinds, handlers, prompt kinds, record channels
   and derivation tables — look for the existing one before inventing. Compose
   with `sequence` / `if_then` / `may` / `for_each` rather than a fused kind.
3. **A name-keyed hook (`engine/card_hooks.py`) is the last resort, explicitly.**
   The last sets' wave-1 groups added none. If you believe you need one, the
   entry bar is that no second card, real or plausibly printable, shares the
   shape — say so in your report rather than quietly adding it. (A printed
   card name is data in a filter, never a name read in dispatch:
   `tests/engine/test_card_name_reads.py`.)
4. **A production consumes its whole line or refuses.** Never a silent partial
   match. A printed restriction, narrowing or rider ("another", "nontoken",
   "you control", "that player", "if this artifact is untapped", "other than
   this artifact", "this turn") is done only when something *enforces* it: an
   unenforced one is a card that works more often than it prints, wrong in the
   player's favour and invisible to every census. If you cannot honour a rider,
   raise `LoweringError` naming what is missing — never admit the line and drop
   the word. {{HOLLOW_RULE}}
5. **When you extend a fragment production, grep for a second copy of it
   first.** Extend the shared one; do not fork it.
6. **Snapshot both differentials before your first edit**:
   `python scripts/oracle_diff.py snapshot --snapshot <your scratch>\od.json` **and**
   `python scripts/sim_fingerprint.py snapshot` (twelve seeded games, a few minutes,
   through `run_and_wait.sh`; three Darksteel groups rebuilt a base snapshot from an
   export because only the first was asked for). Compare `oracle_diff` (same flag)
   after each substantial change and both at the end; name every seeded game that
   moved and why. It diffs every card's full compiled program over both
   manifest roles. Read *every* card that moved. A shipped (non-{{CODE}}) card
   moving is either intended (explain it) or a regression you just caught. If
   you add a defaulted field to a dataclass the snapshot reprs, report the
   count filtered for that field's default spelling, not the raw one. It
   cannot see a text-keyed table (`combat_restrictions`, `cast_restrictions`,
   `activation_restrictions`, `cost_modifiers`, `REPLACEMENT_LINES`,
   `cast_permissions`, …): if you edit one, diff what that table claims over
   the pool before and after, yourself.
7. **Every card lands with a focused behavioural test** in its per-set file,
   in your section. Get cards from `set_pool("{{CODE}}")`. Assert **behaviour** —
   the board, life totals, zones, counters, the log — after `settle(game)`,
   never just instruction kinds or `supported`. Anything pool-wide goes in
   `tests/engine/` or `tests/regressions/`; anything in `tests/rules/` needs
   a `@pytest.mark.cr("…")` marker citing a real numbered rule, in a file of
   your own (`test_{{code}}_<group>_<subject>.py`). **A seeded simulation test
   asserts its subject was exercised (a floor of one), never how often.** A
   test asserts an invariant, never a sibling's progress ("these cards stay
   unsupported" turns red the day a sibling supports one), and a per-set
   premise asks the sets released before {{SET_NAME}} (and M21), never "every
   other shipped set". A test taking 10 s or more is marked
   `@pytest.mark.full`.
8. **Give every card a game (the "Rock Hydra test").** A card can parse,
   lower, compile, report supported — and do nothing at run time. The running
   web app cannot show a measured set, so drive a `Game` headless: put the card
   where it belongs, cast/activate/attack through the real engine entry points,
   step the turn, and read `game.log` and the board at each step. Drive every
   prompt your card arms **as an interactive seat** (`game.interactive_seats`)
   as well as a default one. For anything a turn structure matters to, also
   run `run_ai_simulation(<{{CODE}} path from engine.card_loader.manifest_set_paths(include_measured=True)>, required_cards=[...])`
   and read the report. Check the picker too:
   `targeting.derive_cast_spec` / `derive_activation_spec` must offer what the
   printed line says, or the client sends a bare cast the engine refuses.
9. **Exit criteria per card, all four:** `support_report.py --set {{CODE}}` lists
   it supported; `--hollow-lines` does not name it; `parse_coverage.py --set
   {{CODE}} --workers 2` shows no unclaimed sentence for it; `picker_sweep.py --set
   {{CODE}}` does not name it. A card is "supported" when *any* line is, so the
   first number alone proves nothing. If a handler implements trailing sentences of a clause, declare
   them in `scripts/parse_coverage_claims.py`'s `HANDLER_CLAIMS`.
10. **New instruction kind?** verb_object name, an entry in
    `INSTRUCTION_CATEGORIES` *and* `GRAMMAR_CATEGORIES`
    (`lowering/categories.py`), an `effect_labels.py` label where the guards
    ask for one, and an `@effect_handler`. A category names the family a
    *kind* belongs to, never the module. **New keyword?** One entry in
    `vocabulary.IMPLEMENTED_KEYWORDS` (unless it is a rewrite, which is
    absent by design — listing a rewrite fails `test_keyword_registry`) plus
    behaviour covering **everywhere the CR says it applies**, its rules tests
    in `tests/rules/` with `@pytest.mark.cr`, and `rules_progress.py`'s
    `SCOPE` widened if its section is not tracked (say so; do not regenerate
    the tracker). Check `keyword_lines.UNSUPPORTED_KEYWORDS` too: it outranks
    both tables. The seams are not optional: P/T through `engine/pt.py`;
    leaving the battlefield through `remove_from_battlefield`; hands through
    `take_card_from_hand` / `put_card_into_hand`; libraries through
    `put_card_into_library`; draws through the draw seam; discards through
    `_discard_card`; exile through `put_card_into_exile`; colours through
    `color_changes.change_color`; types through `type_changes.gain_types`;
    permanents addressed by `permanent_id`, never by index or by value
    (a test announces a target with `target_permanent_ids=[…]`, not the old
    slot keyword); types/colours/P/T/keywords/text read through the CR 613
    accessors (`has_type`, `is_creature`, `effective_power`, `_has_keyword`,
    `effective_card`), never `card.type_line` / `card.oracle_text`;
    permanents iterated through the control seam (`all_permanents`,
    `controlled_by`), never `player.battlefield`; a pool loop over cards
    through `faces.compilation_units(...)`. The guards for all of these are in
    `tests/engine/`.
11. **Size caps are hard**: 2,000 lines per module in `engine/`, `web/` and
    `scripts/`; 2,600 per per-set test file. Never raise one. If yours crosses
    one, split in round, and ask "where does this already belong?" before
    "what should the new module be called?". After any move run
    `scripts/integration/missing_names.py` *before* the suite, the dead-import
    guard (`tests/engine/test_import_hygiene.py`),
    `scripts/integration/import_names.py` and `scripts/integration/dups.py`
    on the touched files.
12. **Decline with a parts list, never with "too complex".** If a card will
    not land in your round, stop and write down each missing piece
    individually — file, function, what it has to do — and what you already
    verified works. A list that is half wrong is still a brief for the next
    wave; "too complex" is answerable by nobody. Do not spend the whole round
    on one card. **Measure before building, and a measured decline is an
    honest outcome.**
13. **Shipped cards you find mis-playing.** Every set has found a dozen or
    more already-shipped cards that are silently wrong. If your work exposes
    one in your own family and the fix is local, fix it and test it. If its
    blast radius is the whole pool, do **not** fix it in round: measure it
    (which cards, how many, reproduced how) and report it. A census you write
    must be validated *backwards* — it has to name a known defect on a tree
    where the defect exists — and assert a floor on how much it examined.
14. **When your change makes something possible for the first time, your test
    has to do that thing.** If something can now happen "in response", respond
    to it (destroy the source between the trigger and its resolution); if
    something can now be refused, drive the refusal *and* every caller that
    relied on the acceptance.
15. **Name every prompt your cards arm that a person could not answer.** You
    cannot click in this wave. For each prompt kind your cards arm (new or
    existing), say in your report whether `web/prompts.py` renders it and
    whether `web/static/` has a branch that answers it — the wave-2 client
    group's brief is that list. A cast-time choice is a prompt too.
16. **A new `PlayerState` or `Game` field is read by every `vars()` walker** —
    `ai_rehearsal.position_digest` and the AI censuses' board signatures. One
    that moves on every resolution reads as a lasting change (the AI casts
    spells that did nothing; censuses drift). Say in your report whether each
    field you add is bookkeeping and why.
17. **Grep for the names of the functions you add a caller to**, not only for
    your modules, when choosing which tests to run: a caller census lists
    callers by name.
18. **Randomness is seeded** (CLAUDE.md, "Determinism"): `run_ai_simulation`
    seeds the module-level RNG and `sim_fingerprint` compares twelve games to
    the byte. Anything you add that consumes randomness draws from the RNG the
    engine already draws from, at a point a seeded game reaches
    deterministically.

## The client

A wave-2 group will be the client: every prompt and gesture a wave-1 report
names under rule 15, driven as a human seat in a real browser. So: build the
wire (prompt kind, renderer in `web/prompt_cards.py` / `prompt_board.py` /
`prompt_values.py`, `ActionKind` if one is needed, serialization, state view)
and say exactly what the client must do; do not touch `web/static/`.

## Running tests

- **You do not run the full suite** — that is the integrator's. Run, and list
  in your report: the test files you wrote, every test file you edited **by
  name, without `--quick`** (a named file runs whole, `full` tests included —
  kg5's last group edited a census and ran it in the quick pass alone, and the
  closing gate found it red), the files `scripts/tests_for_diff.py --why`
  names, and **all of `tests/engine` once at the end, with the `full`-marked
  structural guards named on the command line** (a quick-pass run skips
  them):
  `python -m pytest tests/engine tests/engine/test_face_blind_guards.py tests/engine/test_grammar_layering.py tests/engine/test_cast_prohibition_readers.py -n 2 --dist worksteal -q -p no:cacheprovider > <your scratch>\engine.txt 2>&1`
  (through `run_and_wait.sh`). Read the **exit code** and grep the file for
  `FAILED`. Never pipe pytest through `tail` / `Select-Object` — the pipe
  replaces the exit code, and this environment suppresses pytest's summary
  line, so grep for `FAILED`, never for "passed". If your work adds a
  question a census drives (a prompt, a wait, a new want, a new trigger, a
  cast-time choice), grep the `full`-marked censuses
  (`grep -l "mark.full" tests/engine/*.py tests/regressions/*.py tests/ai/*.py`)
  for the table you extended and run those files by name, and run them again
  under `MTG_PROMOTE={{CODE}}`.
- **Commit before you start a long run on a commit**, and make a first
  checkpoint commit as soon as your first card lands. Work in a working tree
  is work a merge cannot see; a session that ends stops every agent at once,
  and the ones with commits resume cheaply.
- `python scripts/check_all.py --workers 2` once (no `--freshness`).
  Stale-tracker lines are the integrator's; everything else is yours.
- Do not leave a test red. If a guard fails on a ratchet that wants an
  `--accept` for a *shipped* card your change legitimately moved, do not
  accept it — report exactly which guard, which card and why.

## Finishing

Commit on your branch (several commits are fine; never leave verified work
uncommitted). Write the commit message as the round's narrative: what it
bought, what it cost, what it exposed. End every commit message with:

    Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

**Your report is your final message**, not a file: a subagent cannot write
`REPORT.md` (the tool refuses it; Darksteel's nine groups were each told to
and refused). The integrator saves it verbatim. It must contain:

1. **Cards done** — each with the four exit criteria confirmed and one line on
   how you drove it in a game.
2. **Cards declined** — each with its individually named missing parts and
   what you verified already works.
3. **What this brief got wrong**, specifically.
4. **Shipped cards found mis-playing** (your drive list included) — fixed
   (with the test) or measured and left (with the census).
5. **`oracle_diff` result** — every card that moved, {{CODE}} and non-{{CODE}}, and why.
6. **New names** you introduced: instruction kinds, categories, labels, AST
   nodes/fields, payload keys, record channels, prompt kinds, keywords,
   modules, shared helpers, `Game`/`PlayerState`/`Permanent` fields. (Two
   groups inventing one idea under two names merges clean and is only found
   by comparing these lists.)
7. **Prompts and gestures a person could not answer** (rule 15).
8. **Module sizes** you pushed past 1,800 lines, and any split you made;
   **every function you touched in a file another group's brief names as
   theirs** (the merge's reading list).
9. The tests you ran (files), `tests/engine` exit code and FAILED count and
   **the commit it ran on**, `check_all` result, the reds on your base,
   branch name, commit hashes. If you ran out of time: exactly what is
   committed, what is in the working tree unverified, and what you would do
   next.
10. **What slowed you down** — one or two lines: a tool you lacked, a probe
    you wrote that should exist, a doc that sent you the wrong way. (The
    owner asked for this set's speed findings: be concrete.)
