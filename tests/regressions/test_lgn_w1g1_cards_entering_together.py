"""Cards put onto the battlefield from a hand together leave the hand together.

Found by amplify (CR 702.38a: "You can't reveal ... any other cards that are
entering the battlefield at the same time as this card"): the two handlers that
put several hand cards onto the battlefield at once (``put_chosen_hand_cards_
onto_battlefield`` — Tempting Wurm, Stronghold Gambit, Ugin's −10 — and the
``put_cards_from_hand_onto_battlefield`` sweep) moved them one at a time, so
the second card was still in its owner's hand while the first one's entry
replacement read that hand.

A shipped card already showed it. Heightened Awareness is "As this enchantment
enters, discard your hand" (CR 614.1c): a Tempting Wurm's opponent putting it
down beside a Grizzly Bears, the Awareness first in hand order, discarded the
Bears it was entering with.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from tests.helpers import resolve_stack

_CARDS = {card.name: card for card in load_catalog()}


def test_an_entry_discard_does_not_reach_a_card_entering_beside_it():
    p1 = PlayerState(name="A", hand=[_CARDS["Tempting Wurm"]],
                     library=[_CARDS["Island"]] * 5)
    p2 = PlayerState(
        name="B",
        hand=[_CARDS["Heightened Awareness"], _CARDS["Grizzly Bears"], _CARDS["Lightning Bolt"]],
        library=[_CARDS["Island"]] * 5,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()

    result = game.queue_from_hand(0, "Tempting Wurm")
    assert result.supported, result.details
    resolve_stack(game)

    entered = sorted(p.card.name for p in game.controlled_by(1))
    assert entered == ["Grizzly Bears", "Heightened Awareness"]
    # What stayed in the hand is what the Awareness discards: the Bolt alone.
    assert [c.name for c in p2.graveyard] == ["Lightning Bolt"]
    assert p2.hand == []
