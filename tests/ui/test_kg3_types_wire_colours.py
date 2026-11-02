"""The wire's hand and stack cards carry the colours the engine reads.

"Nonland permanents you control are white. The same is true for spells you
control and nonland cards you own that aren't on the battlefield." (Celestial
Dawn.) The engine has asked ``object_colors.card_colors`` with the card's seat
since round kg, so a Dawn player's Lightning Bolt is a white spell to every
rule — and ``web/serialization.py`` still sent the printed ``card.colors`` for
the viewer's own hand and for a spell on the stack, so the client drew the
Bolt red in hand and red on the stack (the Known-gaps entry's "two colour reads
stay printed outside the matchers"). The hand asks ``card_colors`` with the
viewer's seat now, and the stack the engine's own ``_stack_item_colors``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from web.serialization import _serialize_player, _serialize_stack_item


@pytest.fixture(scope="module")
def pool(set_pool):
    found = dict(set_pool("4ED"))
    found["Celestial Dawn"] = set_pool("6ED")["Celestial Dawn"]
    return found


def _dawn_game(pool, dawn_seat=0):
    library = [pool["Plains"]] * 5
    players = [
        PlayerState(name="P0", hand=[pool["Lightning Bolt"], pool["Dark Ritual"],
                                     pool["Mountain"]], library=list(library)),
        PlayerState(name="P1", hand=[pool["Lightning Bolt"]], library=list(library)),
    ]
    players[dawn_seat].battlefield.append(Permanent(card=pool["Celestial Dawn"]))
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    return game


def test_a_dawn_players_hand_reaches_them_white(pool):
    game = _dawn_game(pool)

    mine = _serialize_player(game.players[0], 0, 0, game)
    colours = {card["name"]: card["colors"] for card in mine["hand"]}
    assert colours["Lightning Bolt"] == ["W"]
    assert colours["Dark Ritual"] == ["W"]
    # "nonland cards": a land in hand is not recoloured.
    assert colours["Mountain"] == []

    # The other seat has no Dawn: its own Bolt reaches it red.
    theirs = _serialize_player(game.players[1], 1, 1, game)
    assert [card["colors"] for card in theirs["hand"]] == [["R"]]


def test_a_dawn_players_spell_reaches_the_stack_white(pool):
    game = _dawn_game(pool)
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    (item,) = game.stack

    wire = _serialize_stack_item(item, game)

    assert wire["card"]["colors"] == ["W"]
    assert wire["color_override"] is None


def test_the_other_seats_spell_keeps_its_own_colours(pool):
    """The Dawn is a property of its controller's seat: the opponent's Bolt,
    cast under no Dawn of its own, is red on the stack."""
    game = _dawn_game(pool, dawn_seat=0)
    game.active_player_index = game.priority_player_index = 1
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    (item,) = game.stack

    assert _serialize_stack_item(item, game)["card"]["colors"] == ["R"]
