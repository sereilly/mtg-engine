"""CR 614.11 / 121.6a, 406.3 and 616.1e under Shared Fate (Mirrodin W2G2).

"If a player would draw a card, that player exiles the top card of one of
their opponents' libraries face down instead. / Each player may look at cards
they exiled with this enchantment, and they may play lands and cast spells
from among those cards."

A draw replacement applies with an empty library (CR 614.11, 121.6a), so no
draw is attempted and CR 704.5b has nothing to see. A card exiled face down
may be examined only where an instruction allows it (CR 406.3), and played
from exile when the ability that exiled it allows that (CR 406.3a) — here
only by the seat that exiled it. Two Shared Fates are two applicable
replacement effects, and the affected player chooses one (CR 616.1e).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.cast_permissions import playable_from_zones
from engine.linked_exile import face_down_exiled_cards
from engine.models import Permanent


def _table(set_pool, *, bob_library=None, fates: int = 1, interactive=()) -> Game:
    lea, mrd = set_pool("LEA"), set_pool("MRD")
    game = Game(players=[
        PlayerState("Alice", library=[lea["Forest"]] * 5),
        PlayerState(
            "Bob",
            library=list(bob_library if bob_library is not None else [lea["Grizzly Bears"]] * 3),
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for _ in range(fates):
        game._put_permanent_onto_battlefield(0, Permanent(card=mrd["Shared Fate"]), None)
    return game


@pytest.mark.cr("614.11", "121.6a", "704.5b")
def test_a_replaced_draw_from_an_empty_library_loses_nobody(set_pool):
    game = _table(set_pool, bob_library=[])
    alice, bob = game.players
    game._draw_with_replacements(bob, 1)
    game._draw_with_replacements(alice, 1)
    game.check_state_based_actions()
    assert not alice.lost and not bob.lost
    # Bob's draw took Alice's top card; Alice's found Bob's library empty and
    # took nothing from her own.
    assert len(alice.library) == 4 and alice.hand == [] and bob.hand == []


@pytest.mark.cr("406.3", "406.3a")
def test_only_the_exiler_examines_and_plays_the_face_down_card(set_pool):
    game = _table(set_pool)
    alice, bob = game.players
    game._draw_with_replacements(alice, 1)
    (exiled,) = bob.exile
    assert face_down_exiled_cards(game, 1, viewer_index=1) == [exiled]
    assert face_down_exiled_cards(game, 1, viewer_index=0) == []
    assert [e["owner_seat"] for e in playable_from_zones(game, 0)] == [1]
    assert playable_from_zones(game, 1) == []


@pytest.mark.cr("616.1e")
def test_with_two_shared_fates_the_drawer_chooses_one(set_pool):
    game = _table(set_pool, fates=2, interactive=(0,))
    alice, bob = game.players
    game._draw_with_replacements(alice, 1)
    (order,) = [choice for choice in game.pending_choices if choice.kind == "effect_order"]
    assert order.player_index == 0 and len(order.data["options"]) == 2
    assert game.resolve_pending_choice("effect_order", 0, option_index=0)
    # Replaced once: one card exiled, none drawn.
    assert len(bob.exile) == 1 and alice.hand == []
