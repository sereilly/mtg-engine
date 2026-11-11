---
paths:
  - "engine/ai_*.py"
  - "engine/limited_deck.py"
  - "tests/ai/**"
  - "scripts/simulate_ai_games.py"
  - "scripts/sim_fingerprint.py"
  - "web/game_flow.py"
  - "web/seats.py"
  - "web/pregame.py"
  - "engine/mana_wants.py"
  - "engine/mana_drawbacks.py"
---

# The AI simulator

Part of `CLAUDE.md`, kept here so it loads when you open a file it
describes (the `paths` above). The root file's rule for editing applies,
and you can open this file directly whenever its subject is yours.

`run_ai_simulation` deals each seat a random *limited* deck from the pool it is
given (CR 100.2b: 40 cards, 17 lands; basics from the set or, if it prints none,
the manifest), seeded from the run's seed so a seed reproduces a run exactly.
`required_cards=` pins a card into every deck, for a regression test whose
subject must be in play. Each seat is also dealt a **sideboard** — the rest of
the pool its deck was built from (CR 100.4b), by name and with no randomness,
so the decks are byte-identical with or without it — which is what a Wish or
Ring of Ma'rûf brings in from outside the game.

**It plays the engine's turn, never a copy of it.** Every piece the loop once
open-coded went missing silently — untap/upkeep/draw, the main phase, combat,
the ending phase, mana, a step's prompt answered in a later step, extra turns,
a cycling ability left on the stack, casts from zones other than the hand,
priority — and each time the run completed with a non-zero interaction count
and no issues. So the loop calls the engine's stepping (`Game.start_turn`,
`start_next_turn`, `advance_combat_phase` through `engine/ai_combat.py`, the
`prompt_driver` and `priority_driver` seams), and every piece has an **honesty
count** in `SimulationReport` (`interaction_count`, `lands_played`,
`steps_left_owing`, `extra_turns_taken`, `modal_casts`, `casts_from_zones`,
`casts_in_response`, `casts_in_combat`, `casts_on_opponents_turn`,
`casts_before_blocks`, `activations_at_instant_speed`,
`activations_from_graveyard`, `refused_casts`, `refused_attacks`,
`rehearsals_raised`, `special_actions_taken`, `refused_special_actions`,
`special_actions_in_response`, `cards_from_outside_game`, `face_down_casts`,
`mulligans_taken`, `controlled_turns` (a seat's turn another seat decided,
CR 723), the combat counts). A run that
cast nothing exits 1. A new piece of the turn arrives with its count. CR 116
special actions are weighed in `engine/ai_special_actions.py`, before the
first combat and in response to another seat's object
(`special_action_in_response`: a morph turned face up over a spell).

- **Casting**: every cast site goes through `ai_actions.cast_announcement` (an
  AST test fails a site that spells a cast keyword itself), and every
  activation site through `ai_actions.activation_announcement` (an AST test
  holds the executors to it; the text-change words ride `ActivationAction`);
  the mode chooser
  loops `Game.announceable_modes`; `ai_weighed_cast.permitted_casts` is the one
  reader of what `cast_permissions` opens (`CastAction.from_zone`). Whether a
  card may be cast at instant speed is the engine's question
  (`cast_timing.casts_at_instant_speed`, never its type); when the AI wants
  to is `ai_policy._weighed_at_instant_speed_now` (a creature at another
  seat's end step, in response when its entry trigger names a spell, or in
  the declare-attackers step of an attack on its seat, to block with; before
  the blocks a seat that is not defending casts nothing).
- **Why a cast was or wasn't made**: `ai_cast_explain.explain_cast(game,
  seat, card)` asks the real chooser (`choose_cast_action` in the seat's own
  main phase on an empty stack, `choose_combat_instant_cast_action` otherwise;
  `speed=` names one) with the decision's trace listening
  (`ai_cast_trace.listening`), and returns every candidate built for the card
  — each zone, mode, offer answer, life-X size, the entwined and every-mode
  casts — with its score's named terms, the rehearsal behind it, the decision,
  and each dropped candidate's gate reason; `print()` it. Start there before
  writing a tracing probe (W2G9 spent most of a 76-minute round finding a
  missing zone bonus by hand). The builders write the trace themselves (a gate
  returns `cast_trace.dropped("why")`, never a bare `None`); with nobody
  listening each hook is one ContextVar read, so a seeded run is
  byte-identical and the explanation cannot drift from the decision. **Every
  cast candidate is scored in one place**,
  `ai_cast_score.finished_cast_candidate`: `ai_scoring.cast_score_terms` plus
  the zone's bonus (`zone_cast_bonus`) and the stack's
  (`stack_response_bonus`), which no builder adds for itself — each was once
  inline at one builder and missing at its sibling. `tests/ai/test_ai_cast_explain.py`
  fails a builder that calls a scorer or an adjustment directly, or builds a
  `CastAction` with a score of its own. **Both choosers build with one
  builder** (`ai_casts._priced_candidate`, `speed="main"` or `"instant"`,
  carried as `ai_actions._SPEED_WEIGHED`): every gate, variant and target
  chooser is the main phase's at instant speed too, and the speed changes
  only how the finished cast is read — a permanent rehearsed,
  `ai_scoring.read_at_instant_speed` (before the blocks, and a response
  before them), `held_at_instant_speed`, `ai_cast_score.kept_above_the_floor`.
- **Mana**: one exact matching (`ai_payment._PaymentPlanner`, also asked by the
  web's auto-tap) over lands, then tap-only non-land sources
  (`ai_valuation.planned_mana_yield`; a source whose mana is restricted, CR
  106.6, only for a payment `restricted_mana.restriction_admits`), then a
  mana ability whose cost taps
  other permanents (Birchlore Rangers,
  `ai_mana_sources.tap_cost_mana_activations`: the summoning-sick and least
  valuable first, never the permanent being paid for), then a
  self-sacrificing source only when the lands cannot pay and the spell is
  worth more. Of the sources that could pay, the matching spends those the
  seat's other wants need least (`mana_payment._sparing_choice` over
  `mana_wants.mana_wants`: wants paid together first, a held card's price
  before an ability that can wait, and the price of a card a graveyard
  ability is bringing back, `mana_wants.bringing_back`), then those charging
  least beyond the
  tap (`engine/mana_drawbacks.py`: a painland's damage, a depletion counter,
  a land that will not untap, a trigger the tap fires — read off what the
  tap runs), with the pips matched to the chosen sources the cheapest way —
  the one preference every planner shares. A face-down spell's hidden card
  still wants its turn-up cost (`mana_wants.wants_brought_by`, CR 702.37e);
  a cast permanent its own abilities and an instant or sorcery leaving the
  hand its flashback (`wants_left_behind`, told by `mana_wants(cast=…)`),
  and a card castable from outside the hand under a permission its price.
  Floating mana pays generic through the same choice
  (`mana_payment.floating_units_for_generic`,
  colourless first where nothing is wanted), in `plan_payment` and the cast
  path's pool spend.
  `tap_planned_lands` binds every slot to its permanent before the first
  tap (a sacrifice renumbers).
- **Mulligans**: `engine/ai_mulligan.py` is the one keep decision and London
  bottom choice (CR 103.5: lands against the curve on the hand left after
  the bottom choice), asked by the simulator (`take_opening_mulligans`, CR
  103.5's rounds), the web pregame (`web/pregame.py`, by the same rounds)
  and the no-pregame deal (`session_store._begin_pregame`); the cards owed are
  `Game.mulligan_bottom_owed` — `mulligan_effective_count` (CR 103.5c's free
  first mulligan) less what a hand exchange already bottomed. "Any time you
  could mulligan" (CR 103.5b, Serum Powder) is `engine/mulligan_exchanges.py`
  and `Game.pregame_hand_exchange`: a seat exchanges a hand it would not keep
  before it mulligans (`ai_mulligan.take_hand_exchanges`), then declares
  again.
- **Priority**: `Game.offer_priority` gives it in CR 117.3b–d order, before each
  resolution and at a step's end on an empty stack; inert without a driver, at
  a table with an interactive seat, and in the untap step. The simulator and
  the web AI seat answer with one function, `ai_priority.act_at_priority`, in
  the moments `instant_speed_window` names: the cast chooser
  (`choose_combat_instant_cast_action`), then
  `choose_instant_speed_activation` (every non-mana ability of a permanent,
  each turned-down one set aside alone — with that ability of every
  identical permanent, `ai_policy._making_the_same_proposal`; an effect
  removing its own source is a rescue there), then, in a response,
  `ai_special_actions.special_action_in_response` (while it asks, the seat
  is recorded as holding priority, which the special-action gate reads),
  then the hand
  (`ai_hand_activations.choose_hand_activation_action(at_instant_speed=True)`:
  a cycle whose trigger pays now; a cycle whose trigger finds nothing is held
  at sorcery speed), then the graveyard chooser
  (`ai_graveyard_activations.choose_graveyard_activation_action`, alone in
  the seat's own upkeep), each through its own executor; the web AI's own
  upkeep stops for it when the seat holds a graveyard ability. In the
  declare-attackers step before the blocks (`ai_rehearsal.blocks_still_to_come`)
  each proposal is read again through the rest of that combat and made only
  where it adds a block that pays (`pays_before_the_blocks`), and a response
  there (`blocks_owed`) is read through that combat too; at instant speed the
  activation chooser weighs a tapped or summoning-sick permanent's abilities
  without {T}. The web AI seat acts only while it holds priority
  (`game_flow._ai_holds_priority`, CR 117.1a) and gives that answer
  everywhere but its own main phase with an empty stack; there its doors are
  the casts — asked at every `ai_step` at a table with a person, a loop at a
  table of AI seats (the simulator's `_play_casts`) — and the main-phase
  chooser (`ai_abilities.choose_activation_action`, asked only at sorcery
  speed, as the simulator's `_play_activations` asks it), each activation
  door once a step (`Session.ai_doors_spent`); a land it plays keeps its
  priority (CR 116.3). Whatever any door puts on
  the stack goes round the table before it resolves (`_hand_priority_round`,
  CR 117.3c), and, flagged or not, a step the AI's turn arrives at with
  objects on the stack goes round before it is left (`_advance_ai_turn` →
  `_ai_answers_over_the_stack`; the AI's upkeep and draw steps stop for
  theirs, `turn_steps._stops_for_the_steps_objects`), as the combat damage
  step's triggers do at a table with a person (CR 510.3). In declare attackers the AI answers in the request that
  declared its attack (`_ai_declares_attackers`, CR 508.2), and in declare
  blockers once the blocks are in; a person with no legal block has the
  empty declaration made through the engine's `declare_blockers`
  (`_declares_for_a_person_who_cannot_block`). The rail's hold on the AI's
  turn is `_hold_at_flagged_step`: the AI declares and answers first; the
  hold refuses while a declaration is owed (`_declaration_owed`) and hands
  priority round in turn order (`_priority_round`), asking each AI seat it
  reaches (`_ai_respond_to_priority`), to the person — or to nobody once
  every player still in the game has passed. A flagged upkeep or draw step
  stops with the AI's priority open, and its next `ai_step` makes the hold.
- **Rehearsal**: `ai_rehearsal.rehearse` casts the candidate on a scratch copy
  (`ai_scratch_copy.scratch_copy`), resolves on defaults and reads
  `ai_standing.seat_standing` (life, cards, `permanent_worth` through the
  layers, less `SKIPPED_TURN_WORTH` for each turn it will skip) right after
  and at the end of the turn — what lasts counts in full, what ends this turn
  a quarter. A cast that moves nothing, or leaves its caster worse off, is
  not proposed — nor is an ability, read with its {T} on both copies
  (`ai_activation_rehearsal._moves_something`); a one-shot artifact keeps its
  flat score but is read with itself given up on both copies
  (`_spends_a_one_shot_on_something`; a library's order alone is nothing,
  `Rehearsal.reordered_only`), and a cost that sacrifices permanents is
  rehearsed with the whole cost paid and its victim named
  (`_sacrifice_priced_activation`, `ActivationAction.cost_permanent_ids`). A
  precombat cast whose good is gone by the end of the turn is
  rehearsed through the fight (`through_combat=True`), and such an ability
  that changes neither the attack nor the blocks
  (`Rehearsal.declarations_changed`) waits for the declare-blockers step;
  `_fight_the_combat` also finishes a combat already under way, from the step
  it is in, and in its declare-blockers step, on an empty stack, the
  rehearsal's own seat may activate an ability once where a creature of its
  is in a block (`_fight_priority_driver`, one level down; a through-combat
  activation reading leaves the copy with nothing activated holding that
  mana). The attack policy rehearses an attack with a creature the bodies
  keep home when its seat holds an ability it could activate
  (`ai_declarations._attacks_its_held_trick_wins`). A rehearsal's own randomness is seeded from
  `ai_scratch_copy.public_counts` (turn, step and what every seat can count),
  never the log or a process-wide counter, and a seeded run in one process
  plays as in a fresh one (`tests/ai/test_kg4_determinism_rehearsal_seed.py`,
  `test_kg4_determinism_process_state.py`). An opponent's mode choice (CR
  700.2e), a copy offer's reply and a copy of an exiled card cast during a
  resolution (Isochron Scepter, `ai_policy.choose_copy_cast`) are the prompts
  rehearsed inside a rehearsal, one level down (`ai_prompt_picks._one_level_deeper`), so a
  caster's rehearsal prices the answer it will get.
- **A copy sees what its seat sees** (`ai_scratch_copy.conceal_from`, CR
  400.2): libraries reshuffled, other hands redealt, and every card face down
  to the seat — another seat's face-down permanents and spells, an exiled
  card it may not look at (Shared Fate) — dealt again before anything is
  cast on it. Held by `tests/ai/test_ai_hidden_information_census.py`.
- **A rehearsal that raises is counted** (`ai_rehearsal.REHEARSALS_RAISED`), each
  distinct one is an issue, and the script exits 1 — otherwise it is a card
  silently never cast.
- One decision's no-cast baseline is read once (`with deliberating():`). A
  class-level spy on `Game` sees rehearsal copies too (which run the end step
  and the next turn's bookkeeping), so guard a spy with
  `ai_rehearsal.rehearsing()`. The AI is two families of modules: the
  choosers (`ai_policy` and the `ai_*` modules it fronts — among them
  `ai_prompt_picks`, what a seat nobody asks picks, by worth, for every
  prompt kind's default) and what a card or a position is worth
  (`ai_valuation`, `ai_standing` — the one measure of a seat's position —,
  `ai_rehearsal`, `ai_scratch_copy`, `ai_weighed_cast`, `ai_target_sides` and
  `ai_slot_sides` — one target's side, and each slot's of an announcement
  naming several —, `ai_prompt_readers`, `ai_compelled_blocks` — a fight's
  outcome, read by the blocks and by a trigger that compels a block — and
  `ai_combat_triggers`, what a creature's own attack or block trigger
  gambles, read by the declarations).

What the simulator does not do yet is in ROADMAP.
