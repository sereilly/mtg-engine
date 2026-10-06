"""A reanimation "from a graveyard" that names a seat and no card takes that
seat's card (PLS W2G6).

``reanimate_creature`` with ``any_graveyard`` reads the named player as whose
pile the card comes from, and searches — the named seat, then the caster, then
everyone else — when no card was named. It searched only when the named seat
held **nothing**. A seat *other than the caster* that did hold a card passed
that test with no slot recorded, and the step underneath then fell back to the
first eligible card in the **caster's** graveyard: the wrong pile, or nothing.

Nothing reached it while an entry trigger nobody announced for ran inline with
its own controller as "the target player". As a stack object (CR 603.3) it
takes the default every other trigger takes — an opponent — and a Necromancy
put onto the battlefield with the only creature card in that opponent's
graveyard returned nothing (``tests/sets/test_vis_enchantments.py`` holds that
play). The census below asks the handler the same question of every card that
compiles the instruction, with a floor.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

#: Coffin Queen, Hymn of Rebirth, Iridescent Drake, Necromancy, Reanimate.
_MIN_ANY_GRAVEYARD_REANIMATIONS = 5


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


def _w2g6_walk(node, found: list) -> None:
    payload = getattr(node, "payload", None)
    if getattr(node, "kind", None) == "reanimate_creature" and (payload or {}).get(
        "any_graveyard"
    ):
        found.append(node)
    if isinstance(payload, dict):
        node = payload
    if isinstance(node, dict):
        for value in node.values():
            _w2g6_walk(value, found)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _w2g6_walk(value, found)


def _w2g6_any_graveyard_reanimations(pool) -> list:
    """``(card, instruction)`` for every compiled "from a graveyard" return."""
    rows = []
    for card in pool.values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        found: list = []
        for instruction in program.instructions:
            _w2g6_walk(instruction, found)
        for ability in (*program.triggered_abilities, *program.activated_abilities):
            if getattr(ability, "instruction", None) is not None:
                _w2g6_walk(ability.instruction, found)
        for mode in program.modes:
            if mode.instruction is not None:
                _w2g6_walk(mode.instruction, found)
        if found:
            rows.append((card, found[0]))
    return sorted(rows, key=lambda row: row[0].name)


def test_w2g6_every_from_a_graveyard_return_takes_the_named_seats_card(pool):
    """Both piles hold a card the effect may take; the opponent's seat is named
    and no slot is. The opponent's card is the one that arrives, under the
    caster's control, and the caster's own pile is untouched."""
    rows = _w2g6_any_graveyard_reanimations(pool)
    assert len(rows) >= _MIN_ANY_GRAVEYARD_REANIMATIONS, [row[0].name for row in rows]
    assert {"Hymn of Rebirth", "Necromancy", "Reanimate"} <= {card.name for card, _ in rows}

    for card, instruction in rows:
        mine = [pool["Hill Giant"], pool["Unholy Strength"]]
        theirs = [pool["Grizzly Bears"], pool["Holy Strength"]]
        forest = pool["Forest"]
        game = Game(players=[
            PlayerState("Caster", library=[forest] * 5, graveyard=list(mine)),
            PlayerState("Rival", library=[forest] * 5, graveyard=list(theirs)),
        ])
        game.enforce_mana_costs = False
        source = Permanent(card=pool["Craw Wurm"])
        game._put_permanent_onto_battlefield(0, source, None)
        context = OracleExecutionContext(
            caster=game.players[0], target=game.players[1], card=card,
            source_permanent=source,
        )

        game._execute_oracle_instruction(instruction, context)
        resolve_stack(game)

        assert [c.name for c in game.players[0].graveyard] == [
            "Hill Giant", "Unholy Strength",
        ], f"{card.name}: the caster's own pile was searched"
        left = [c.name for c in game.players[1].graveyard]
        assert len(left) == 1, f"{card.name}: {left}"
        (taken,) = [name for name in ("Grizzly Bears", "Holy Strength") if name not in left]
        assert taken in [p.card.name for p in game.controlled_by(0)], (
            f"{card.name}: {taken} did not arrive under the caster's control"
        )


def test_w2g6_hymn_of_rebirth_cast_at_a_seat_takes_that_seats_creature(pool):
    """The same question through a cast: an AI seat names whose graveyard and
    no slot. With a creature card in each pile, it is the named player's that
    comes back."""
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("Caster", library=[forest] * 5, hand=[pool["Hymn of Rebirth"]],
                    graveyard=[pool["Hill Giant"]]),
        PlayerState("Rival", library=[forest] * 5, graveyard=[pool["Grizzly Bears"]]),
    ])
    game.enforce_mana_costs = False

    assert game.cast_from_hand(0, "Hymn of Rebirth", target_player_index=1).supported

    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].graveyard] == ["Hill Giant", "Hymn of Rebirth"]
    assert game.players[1].graveyard == []
