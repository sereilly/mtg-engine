"""Censuses: "its controller", asked of a record somebody wrote.

Two sweeps over **both manifest roles**, each with a floor, each validated
backwards on the tree before the fix.

**The reader-without-a-writer sweep.** A seat a sentence refers back to —
"its controller" of the object an earlier step chose — is read at resolution
from a record (the spell's, the permanent's, or the per-object map a sweep
fills). The lowering picks which, and it picked without asking what the step
in front had produced: a life loss always read the permanent record and a
draw always read the per-object one. So every instruction in the pool that
reads one of those records is checked for a **writer in front of it** in its
own sequence (``lowering._records.produced_keys``), an enclosing ``for_each``,
or a firing event that freezes the seat. On the base tree this names two
shipped cards and nothing else:

* **Undermine** — ``target_loses_life`` reading ``last_target_controller``
  behind a ``counter_top_stack_spell``. It never made anyone lose life.
* **Kavu Lair** — ``draw_target_cards`` reading ``swept_controller_seats``
  under a trigger, with no sweep anywhere. "Whenever a creature with power 4
  or greater enters, its controller draws a card" had never drawn a card.

**The rider sweep.** Invented cards — "Counter target spell. ⟨rider⟩" over
eight rider verbs and three spellings of the seat — each resolved against the
caster's own spell, an opponent's, and an opponent's spell of a card the
caster owns. A rider is right when the one seat it touched is the spell's
controller. On the base tree 23 of 57 driven cases are wrong (20 on the
caster's own spell, where the default seat is the wrong one, and Undermine's
three on every board). A probe the grammar refuses is counted separately:
refusing is the loud direction and not a defect.

    python -m tests.regressions.test_ody_w2g8_spell_controller_census
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game_types import StackItem
from engine.grammar.lowering._events import _EVENT_SUBJECT_CONTROLLERS
from engine.grammar.lowering._records import produced_keys
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import (COUNTERED_SPELL_CONTROLLER,
                                 LAST_TARGET_CONTROLLER,
                                 PER_OBJECT_SEAT_RECORDS)
from tests.helpers import _mk_card, resolve_stack

#: The records "its controller" is read from, by what "it" was.
SEAT_RECORDS = frozenset({
    LAST_TARGET_CONTROLLER, COUNTERED_SPELL_CONTROLLER,
    PER_OBJECT_SEAT_RECORDS["controller"],
})

READER_FLOOR = 20
RIDER_FLOOR = 50


def _pool():
    cards = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            cards.setdefault(card.name, card)
    return cards


def _nested(instruction):
    """``(key, steps)`` for every payload value holding instructions."""
    for key, value in (instruction.payload or {}).items():
        if hasattr(value, "kind"):
            yield key, [value]
        elif isinstance(value, (tuple, list)) and value and all(
            hasattr(step, "kind") for step in value
        ):
            yield key, list(value)


def _readers(instruction, written, in_loop, found):
    """Every seat-record read under *instruction*, with whether a writer
    stands in front of it. *written* is what the steps already walked in this
    effect produce; *in_loop* is whether a ``for_each`` encloses it (the
    per-object map is read one entry per iteration there)."""
    payload = instruction.payload or {}
    for key, value in payload.items():
        if isinstance(value, str) and value in SEAT_RECORDS:
            per_object = value == PER_OBJECT_SEAT_RECORDS["controller"]
            found.append((
                instruction.kind, key, value,
                (in_loop if per_object else value in written),
            ))
    looping = in_loop or instruction.kind == "for_each"
    for _key, steps in _nested(instruction):
        seen = set(written)
        for step in steps:
            _readers(step, frozenset(seen), looping, found)
            seen |= produced_keys(step)


def readers_without_a_writer(pool) -> tuple[int, list[str]]:
    examined, orphans = 0, []
    for unit in compilation_units(list(pool.values())):
        program = compile_card_oracle(unit)
        roots = [(None, instruction) for instruction in program.instructions]
        roots += [
            (None, ability.instruction) for ability in program.activated_abilities
            if ability.instruction is not None
        ]
        roots += [
            (trigger.condition.kind, trigger.instruction)
            for trigger in program.triggered_abilities
            if trigger.instruction is not None
        ]
        seen_rows = set()
        for event, root in roots:
            found: list = []
            _readers(root, frozenset(), False, found)
            for kind, key, record, has_writer in found:
                row = (kind, key, record, has_writer, event)
                if row in seen_rows:
                    continue
                seen_rows.add(row)
                examined += 1
                if not has_writer:
                    orphans.append(
                        f"{unit.name}: {kind} reads {key}={record} with no "
                        f"step in front of it that writes it"
                        + (f" (under {event})" if event else "")
                    )
    return examined, orphans


def test_every_its_controller_record_has_a_writer_in_front_of_it():
    examined, orphans = readers_without_a_writer(_pool())
    assert examined >= READER_FLOOR, f"only {examined} readers examined"
    assert orphans == []


def test_the_event_table_the_draw_lowering_reads_freezes_kavu_lairs_seat():
    """The reader sweep excuses nothing by event — a seat an event froze is
    read under its own key — so the one event this fix leans on is pinned."""
    assert "matching_permanent_enters" in _EVENT_SUBJECT_CONTROLLERS


# --- the rider sweep ---------------------------------------------------------

SEAT_PHRASES = ("Its controller", "That spell's controller", "That player")
RIDERS = {
    "loses life": "{S} loses 3 life.",
    "gains life": "{S} gains 3 life.",
    "draws": "{S} draws a card.",
    "discards": "{S} discards a card.",
    "mills": "{S} mills two cards.",
    "sacrifices": "{S} sacrifices a creature.",
    "damage": "Probe Rider deals 2 damage to {s}.",
    "token": "{S} creates a 1/1 white Soldier creature token.",
}
SHIPPED = ("Undermine", "Illumination")
ORIENTATIONS = (("own", 0, 0), ("theirs", 1, 1), ("stolen", 1, 0))


def _snapshot(game):
    return [
        [player.life, len(player.hand), len(player.library),
         len(player.graveyard), len(player.exile),
         len(list(game.controlled_by(seat)))]
        for seat, player in enumerate(game.players)
    ]


def _touched(pool, card, controller, owner):
    """The seats *card* visibly did something to, beyond the counter itself;
    None when the cast was refused."""
    text = (card.oracle_text or "").lower()
    target_name = "Sol Ring" if "artifact or enchantment" in text else "Grizzly Bears"
    filler = [pool["Forest"]] * 30
    game = Game(players=[
        PlayerState("P1", library=list(filler), hand=[card, pool["Swamp"], pool["Swamp"]]),
        PlayerState("P2", library=list(filler), hand=[pool["Swamp"], pool["Swamp"]]),
    ])
    game.enforce_mana_costs = False
    for seat in (0, 1):
        game._put_permanent_onto_battlefield(
            seat, Permanent(card=pool["Grizzly Bears"]), None
        )
    game.turn += 1
    game.start_turn(0)
    game._stack_push(StackItem(
        card=pool[target_name], caster_index=controller, owner_index=owner,
        target_player_index=None, target_permanent_index=None, x_value=None,
    ))
    before = _snapshot(game)
    if not game.queue_from_hand(0, card.name, target_stack_index=0).supported:
        return None
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    after = _snapshot(game)
    # What the counter itself moves: the counterspell out of its caster's hand
    # into their graveyard, and the countered card into its owner's.
    before[0][1] -= 1
    before[0][3] += 1
    before[owner][3] += 1
    return {seat for seat in (0, 1) if after[seat] != before[seat]}


def rider_census(pool) -> tuple[int, int, list[str]]:
    cases = []
    for label, template in RIDERS.items():
        for phrase in SEAT_PHRASES:
            text = "Counter target spell. " + template.format(
                S=phrase, s=phrase[0].lower() + phrase[1:]
            )
            cases.append((
                f"{label} / {phrase}",
                _mk_card("Probe Rider", "{1}{U}", "Instant", text),
            ))
    cases += [(name, pool[name]) for name in SHIPPED]
    driven, refused, wrong = 0, 0, []
    for label, card in cases:
        if not compile_card_oracle(card).supported:
            refused += 1
            continue
        for orientation, controller, owner in ORIENTATIONS:
            touched = _touched(pool, card, controller, owner)
            driven += 1
            if touched != {controller}:
                wrong.append(
                    f"{label} [{orientation}]: touched "
                    f"{'nobody' if not touched else sorted(touched)}, the "
                    f"spell's controller is seat {controller}"
                )
    return driven, refused, wrong


def test_a_rider_about_a_countered_spells_controller_reaches_that_player():
    driven, _refused, wrong = rider_census(_pool())
    assert driven >= RIDER_FLOOR, f"only {driven} cases driven"
    assert wrong == []


def test_kavu_lair_draws_for_the_controller_of_the_creature_that_entered(set_pool):
    """The second card the reader sweep named. Each seat's own big creature
    draws that seat a card (CR 603.10: the event's seat, not the Lair's)."""
    pool = {**set_pool("LEA"), **set_pool("INV")}
    for seat in (0, 1):
        forest = pool["Forest"]
        hands = [[], []]
        hands[seat] = [pool["Craw Wurm"]]
        game = Game(players=[
            PlayerState("P1", library=[forest] * 20, hand=hands[0]),
            PlayerState("P2", library=[forest] * 20, hand=hands[1]),
        ])
        game.enforce_mana_costs = False
        game._put_permanent_onto_battlefield(0, Permanent(card=pool["Kavu Lair"]), None)
        game.turn += 1
        game.start_turn(seat)
        before = [len(player.hand) for player in game.players]

        assert game.queue_from_hand(seat, "Craw Wurm").supported
        resolve_stack(game)

        expected = list(before)
        expected[seat] = before[seat] - 1 + 1   # the Wurm left, a card arrived
        assert [len(player.hand) for player in game.players] == expected


def test_kavu_lair_ignores_a_creature_too_small_to_trigger_it(set_pool):
    pool = {**set_pool("LEA"), **set_pool("INV")}
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("P1", library=[forest] * 20, hand=[pool["Grizzly Bears"]]),
        PlayerState("P2", library=[forest] * 20, hand=[]),
    ])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Kavu Lair"]), None)
    game.turn += 1
    game.start_turn(0)
    before = len(game.players[0].hand)

    assert game.queue_from_hand(0, "Grizzly Bears").supported
    resolve_stack(game)

    assert len(game.players[0].hand) == before - 1


if __name__ == "__main__":
    pool = _pool()
    examined, orphans = readers_without_a_writer(pool)
    print(f"seat-record readers examined: {examined}; without a writer: {len(orphans)}")
    for line in orphans:
        print("  ", line)
    driven, refused, wrong = rider_census(pool)
    print(f"rider cases driven: {driven}; wrong: {len(wrong)}; probes refused at compile: {refused}")
    for line in wrong:
        print("  ", line)
