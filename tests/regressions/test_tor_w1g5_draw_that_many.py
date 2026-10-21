"""Regression (TOR W1G5): "draw that many cards" read by every draw handler.

The lowering writes the number a bare "that many" names as ``amount_from`` —
the scratchpad key an earlier step of the same resolution recorded — on
whichever draw kind the drawer picks. ``draw_target_cards`` read it;
``draw_controller_cards`` never did, so a draw by the effect's own controller
behind a counted step drew zero while the card compiled supported:

* Tolarian Winds (Urza's Saga, shipped): "Discard all the cards in your hand,
  then draw that many cards." Discarded the hand and drew nothing.
* Nantuko Cultivator (Torment): "…you may discard any number of land cards.
  Put that many +1/+1 counters on this creature and draw that many cards."
  Found by driving it — the counters had a defect of their own (a bare "that
  many" fell to Tetravus's ``trigger_count``), fixed beside this one.

The census runs every draw instruction in both manifest roles that carries
``amount_from`` through its own handler with that record set, and asks that
exactly that many cards were drawn. It carries a floor on what it examined.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.game_types import OracleExecutionContext
from engine.handlers import EFFECT_HANDLERS
from engine.oracle import compiled_units
from tests.helpers import _mk_card, resolve_stack


def _walk(value):
    if hasattr(value, "kind") and hasattr(value, "payload"):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def _counted_draws():
    pool = load_cards(manifest_set_paths(include_measured=True))
    for card, program in compiled_units(pool):
        parts = [program.instructions]
        parts += [ability.instruction for ability in program.triggered_abilities]
        parts += [
            getattr(ability, "instruction", None)
            for ability in program.activated_abilities
        ]
        for part in parts:
            for instruction in _walk(part):
                if instruction.kind.startswith("draw") and "amount_from" in (
                    instruction.payload
                ):
                    yield card, instruction


def _two_seats():
    library = [_mk_card(name=f"Library {i}", type_line="Land") for i in range(10)]
    return Game(players=[
        PlayerState("A", library=list(library)),
        PlayerState("B", library=list(library)),
    ])


def test_every_draw_of_that_many_draws_the_recorded_number():
    examined = 0
    wrong: list[str] = []
    for card, instruction in _counted_draws():
        game = _two_seats()
        a, b = game.players
        record = str(instruction.payload["amount_from"])
        seat_record = instruction.payload.get("drawer_seat_record")
        results = {record: 2}
        if seat_record:
            results[str(seat_record)] = 0
        context = OracleExecutionContext(
            caster=a, target=a, card=card, results=results,
            trigger_context={str(seat_record): 0} if seat_record else None,
        )
        EFFECT_HANDLERS[instruction.kind](game, instruction, context)
        examined += 1
        drawn = len(a.hand) + len(b.hand)
        if drawn != 2:
            wrong.append(f"{card.name} ({instruction.kind}): drew {drawn}")
    assert not wrong, wrong
    # Six when this was written: Forget, Nantuko Cultivator (twice — its
    # trigger and its program), Robber Fly, Shocker, Teferi's Puzzle Box,
    # Tolarian Winds.
    assert examined >= 6, f"the census examined only {examined} draws"


def test_tolarian_winds_draws_as_many_cards_as_it_discarded(set_pool):
    winds = set_pool("USG")["Tolarian Winds"]
    lea = set_pool("LEA")
    library = [_mk_card(name=f"Library {i}", type_line="Land") for i in range(10)]
    game = Game(players=[
        PlayerState(
            "A", library=list(library),
            hand=[winds, lea["Forest"], lea["Island"], lea["Lightning Bolt"]],
        ),
        PlayerState("B", library=list(library)),
    ])
    game.enforce_mana_costs = False
    game._sync_control()

    result = game.cast_from_hand(0, winds.name)
    resolve_stack(game)

    assert result.supported, result.details
    assert [card.name for card in game.players[0].hand] == [
        "Library 0", "Library 1", "Library 2",
    ]
    assert "Tolarian Winds drew 3 card" in game.log
