---
paths:
  - "engine/mixins/draws_and_discards.py"
  - "engine/mixins/zone_funnels.py"
  - "engine/mixins/stack/pool_payment.py"
  - "engine/entry_awaiting.py"
  - "engine/faces.py"
  - "engine/face_down.py"
  - "engine/linked_exile.py"
  - "engine/mana_*.py"
  - "engine/board_payment.py"
  - "tests/engine/test_discard_cost_seam.py"
  - "tests/engine/test_draw_seam.py"
  - "tests/engine/test_exile_arrival_seam.py"
  - "tests/engine/test_face_blind_guards.py"
  - "tests/engine/test_hand_removal_seam.py"
  - "tests/engine/test_hidden_cards_stay_out_of_the_log.py"
  - "tests/engine/test_kg3_batch_roads.py"
  - "tests/engine/test_kg3_entry_callers.py"
  - "tests/engine/test_kg4_together_departure_roads.py"
  - "tests/engine/test_mana_ability_library_criterion.py"
---

# Zones, draws, discards, mana

Part of `CLAUDE.md`, kept here so it loads when you open a file it
describes (the `paths` above). The root file's rule for editing applies,
and you can open this file directly whenever its subject is yours.

## Zones, draws, discards, mana

- **Outside the game is not a zone** (CR 400.11): it is `PlayerState.sideboard`,
  read through `Game._outside_game_choices` (CR 407.3's ante bar, CR 903.11a's
  Commander bar) and moved by `Game.bring_card_from_outside_game`. A printed
  "card you own from outside the game" is `ObjectFilter.outside_the_game`,
  refused by name by every lowering not written for it (the Wishes, Ring of
  Ma'rûf).
- **Drawing is one seam.** `Game._draw_with_replacements`
  (`mixins/draws_and_discards.py`) is where a draw becomes
  a CR 614 event; `PlayerState.draw` underneath is banned outside it by
  `tests/engine/test_draw_seam.py` (only pregame draws are allowed). **Draws are
  made one at a time** (CR 616.1f): a prompt armed during a seat's draw is
  stamped (`replacement_choices.DRAW_OF`) and a later draw for it is parked
  (`Game.parked_draws`) until the answer. A doubler has one opportunity per
  event (CR 614.5), passed down as `exclude_sources`.
- **Discarding is one seam, and the event says who caused it.**
  `Game._discard_card` raises the `discard` event with `cause_seat`
  (`discard_cause_seat`), because "a spell or ability an opponent controls causes
  you to discard" is a question about the cause — and with `as_cost` when the
  discard pays a cost, because "if an effect causes you to discard" (Library
  of Leng) is one too. Every discard in the four cost-paying modules passes it
  (`tests/engine/test_discard_cost_seam.py`). So does a cost CR 118.12 pays
  at resolution: an offer printing "if [player] does/doesn't" or "unless"
  marks its action's discards `as_cost` at lowering
  (`lowering/control_flow._paid_as_cost`, `COST_PAYABLE_DISCARD_KINDS`); the
  chosen discard's prompt carries `_as_cost` with no library top, and
  `discard_cause_seat(as_cost=True)` is None — a cost is caused by nobody
  (`tests/engine/test_kg5_costs_resolution_discard_costs.py`).
- **Every "put into a hand / a library"** goes through `Game.put_card_into_hand`
  (`mixins/zone_funnels.py`)
  / `put_card_into_library` (CR 903.9b has no single fire site).
- **Arriving in exile is one transition**: `Game.put_card_into_exile` returns
  the object the pile now holds — a new, equal one when some exile already
  holds that object (CR 400.7) — and the caller writes that down, so no exile
  holds one object twice and every record about an exiled card names one card.
  The Debug Menu's raw-state paste goes through it too
  (`tests/engine/test_exile_arrival_seam.py`). **So is arriving in a
  graveyard** (Mirrodin W2G7): `put_card_into_graveyard` returns the object
  the pile holds — a new, equal one on a collision
  (`graveyard_order.distinct_graveyard_object`) — "put there from the
  battlefield this turn" is an identity record retired at the object's next
  arrival, and a permanent that died records the object it became
  (`graveyard_order.CARD_IN_GRAVEYARD`), which an ability resolving after its
  source left reads as "this card" (`graveyard_order.graveyard_object_of`).
- **An entry that asks waits** (CR 614.12a): `_enter_battlefield` performs the
  entry state with the permanent in no zone (`engine/entry_awaiting.py`;
  `controller_index_of` answers its seat), and at a table that holds for
  answers an entry that leaves a prompt open finishes at its last answer
  (`_finish_answered_entries`). A caller acts on the entered permanent through
  `then` (`tests/engine/test_kg3_entry_callers.py`), which runs for an entry
  a replacement took away too, so whatever it does to the permanent, or says
  of it, asks `entry_awaiting.entry_happened` first; a line written once an
  event has closed asks `entry_replaced`
  (`tests/engine/test_kg5_entry2_entry_log_lines.py`). No default is stamped
  before a person's prompt (`_stamps_entry_default`), and a table that holds
  for nothing takes an entry prompt's default as it is armed
  (`Game._an_entry_nobody_waits_for`). **Permanents one event puts onto the
  battlefield enter together** (CR 603.6a): a road that enters several wraps
  them in `Game.entering_together()` — each newcomer is handed to the event
  as its call is made (`entry_awaiting.DeferredEntry`, its id stamped then),
  and when the event closes each one's entry state is performed in no zone in
  APNAP order of the seat it enters under (CR 101.4, 613.7m;
  `entry_awaiting.apnap_order`), then all are appended, recomputed once and
  announced with every newcomer present; an event whose newcomers ask waits
  as one, at the last answer any of them owes. An event can outlive a
  decision: a prompt armed inside it carries it (`entry_awaiting.ENTRY_EVENT`),
  its answer re-joins it, and it closes once its opener is done and no
  suspending prompt it stamped is owed — a resumable loop opens one with
  `Game.entering_together_through` (a multi-seat `may`, Show and Tell; a
  single-leaf `for_each`). `tests/engine/test_kg3_batch_roads.py` holds every
  entry made in a loop to the block. **What one event takes off the
  battlefield looks back at itself** (CR 603.10a, 704.3): each state-based
  pass (`_state_based_pass`), each destruction of several permanents and
  every loop removing several permanents for one action runs inside
  `Game.leaving_together()`; the death scans, the `events.LOOKS_BACK_IN_TIME`
  announcements and the transition's attachment and token-maker scans add
  `departed_in_this_event()`; an inline leaves-the-battlefield effect waits
  for the event (`after_this_departure`); a loop whose repetitions sacrifice
  at their answers (Fade Away, Tariff) holds them on its context
  (`sacrificing_together_through`, `OracleExecutionContext.sacrifice_batch`)
  for its last step — and a toll's penalty that sacrifices nothing waits for
  those sacrifices (`run_penalty`, `penalties_after=`: Read the Runes'
  ruling, the sacrifices then the discards).
  `tests/engine/test_kg4_together_departure_roads.py`
  holds every departing call made in a loop to the block. **A card that
  cannot enter stays where it is** (CR 400.4a, and CR 614.17's "can't",
  Worms of the Earth): every road that puts a card onto the battlefield out
  of a zone asks `permanent_cards.stays_out_of_battlefield` before it takes
  the card (`is_permanent_card` is CR 110.4a's one reading;
  `cant_enter_sources` asks the registry's `cant_enter_battlefield`
  predicates), and `tests/engine/test_kg5_kindred_entry_roads.py` and
  `test_kg5_entry2_cant_enter_roads.py` hold every caller of
  `_put_permanent_onto_battlefield` to it.
- **Leaving a hand is one transition**: `Game.take_card_from_hand(owner, card)`
  removes exactly one copy by identity — every copy of a card in a hand is the
  same `CardDefinition` object. Guarded by `tests/engine/test_hand_removal_seam.py`.
- `engine/mana_payment.py` — whether a cost can be paid, and how. Casting and
  activating spend the *pool* (`_pay_mana_cost`, `mixins/stack/pool_payment.py`);
  an effect's "you may pay"
  gives no priority window, so it taps lands **for mana**, one at a time,
  through `Game._pay_planned_cost`. `plan_payment` is an exact matching over
  `Game.payment_lands`, told who is paying (`payer=`, so a CR 106.6 spending
  permission is planned; an AST guard fails a call with none) — and for a
  cost an effect collects, each land is planned as the units one tap of it
  adds (`board_payment.plan_over_land_units`, named by
  `payment_units_in_force`), so Ancient Tomb is {C}{C} of one source: every
  such cost's "can this be paid?" and its plan ask `Game.effect_payment_plan`.
  Which sources pay is `_sparing_choice`'s, against the payer's wants
  (`engine/mana_wants.py`, read only from what that seat can see) and then
  each source's price (`engine/mana_drawbacks.py`); `Game._pay_planned_cost`
  names both for the length of a payment (`payment_wants_in_force`,
  `payment_prices_in_force`). A cost is a symbol dict everywhere
  (`generic_cost(n)`).
- **What a mana ability is** is one predicate, `engine/mana_abilities.is_mana_ability` (CR 605.1a's
  four criteria, including "doesn't move a card to or from a library"), asked
  **fail-closed**: a zone-moving step beside an add-mana step is presumed to
  reach a library unless listed in `LIBRARY_SAFE_ZONE_KINDS`
  (`tests/engine/test_mana_ability_library_criterion.py`).
- **"Tapped for mana" is one event** (CR 106.12), `Game._land_tapped_for_mana`,
  on all three roads (explicit tap, a cost an effect collects, an activation).
  **A tap is the activation of one mana ability, and asking for a symbol picks
  it** (`board_payment.tap_alone_ability_for`); what a land can make is read per
  ability (`tap_alone_symbols`), never off the printed summary. **Two
  substitutions on one land are CR 616.1 candidates, one per effect**
  (`land_mana_swaps.swapped_productions`, registered with `instances=`; a
  one-symbol record such as Quarum Trench Gnomes' is one,
  `ManaSubstitution.replaces`), chosen before the tap, which cannot wait
  mid-payment: the symbol asked for picks the first order that makes it
  (`ordered_substitutions`), so the tap's `mana_color` is the answer and no
  prompt is armed. The substitution readers start from
  `Permanent.unswapped_produced_mana`. What a land "could produce" (CR
  106.7) is `mana_could_produce.lands_could_produce`: every order of each
  land's substitutions, and `also=` for a land that has left, beside the
  board it left.
- `engine/board_payment.py` — `board_can_pay`: can this seat pay from its pool
  plus what its untapped lands would add (default — what an automatic payment
  asks), or plus every tap-alone source and every mana ability whose cost taps
  other permanents (`nonland_sources=True` — what a player is asked; the
  castable highlight passes it), or from the pool alone (`pool_only=True`).
- `engine/faces.py` — multi-face cards (CR 709). **A face is a card**: each half
  is derived once as its own `CardDefinition` carrying `face_of`, and that half
  compiles and goes on the stack; `whole_card` is CR 709.4 at the zone seams —
  and CR 708.9 for a face-down object, whose real card it returns. The
  whole card's program has **no instructions**, so a guard whose population is
  "each card, compiled" passes over every half without examining one — blind,
  not red. Text questions iterate `faces.compilation_units(pool)` /
  `oracle.compiled_units`; card questions keep the card. Held by
  `tests/engine/test_face_blind_guards.py`.
- `engine/face_down.py` — morph (CR 702.37) and face-down spells and
  permanents (CR 708). **While hidden, a face-down `StackItem.card` /
  `Permanent.card` *is* the blank 2/2** (`face_down_card`) and the real card
  rides on it as `CardDefinition.face_down_of` — substitution, chosen because
  `.card.name` is read everywhere and a hidden card must be fail-closed;
  `copies.FACE_DOWN_AS_IT_LEFT` keeps last-known information. Casting face
  down is an alternative cost; turning face up is the `turn_face_up` special
  action (CR 116.2b); effects turn a permanent down or up through
  `turn_face_down` / `turn_face_up(game, perm, how=…)`. The wire carries
  `face_down` and, to the controller alone, `hidden_card`; the AI's rehearsal
  copy conceals an opponent's face-down cards (CR 708.5). A non-mana morph
  cost is read and paid by the alternative-cost reader
  (`alternative_costs._read_cost_clauses`) the special action's offer names.
  **`game.log` is every seat's, so a line names only what every seat may
  see**: a card exiled face down, a private find or a card behind a
  face-down object is counted, not named (`linked_exile.exiled_cards_for_the_log`),
  and a face-down exile stays face down after its exiler leaves
  (`keep_face_down_after_departure`). Held by
  `tests/engine/test_hidden_cards_stay_out_of_the_log.py`.
