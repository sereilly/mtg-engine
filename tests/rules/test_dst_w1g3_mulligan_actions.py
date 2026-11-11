"""CR 103.5b: an action a player may perform "any time [they] could mulligan".

"If an effect allows a player to perform an action 'any time [that player]
could mulligan,' the player may perform that action at a time they would
declare whether they will take a mulligan. This need not be in the first round
of mulligans. Other players may have already made their mulligan declarations
by the time the player has the option to perform this action. If the player
performs the action, they then declare whether they will take a mulligan."

The one card that grants such an action is Serum Powder (Darksteel):
``Game.pregame_hand_exchange`` (``engine/mulligan_exchanges.py``), asked by the
AI's mulligan rounds (``ai_mulligan.take_opening_mulligans``) and the web
pregame (``mulligan_exchange``). Cards come from ``set_pool``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_mulligan import take_opening_mulligans


def _table(set_pool, alice_hand):
    dst, lea = set_pool("DST"), set_pool("LEA")
    pool = {**lea, **dst}
    library = (
        [lea["Forest"]] * 17 + [lea["Grizzly Bears"]] * 20 + [dst["Serum Powder"]]
    )
    alice = PlayerState(name="Alice", library=library)
    bob = PlayerState(name="Bob", library=[lea["Forest"]] * 17 + [lea["Grizzly Bears"]] * 23)
    game = Game(players=[alice, bob])
    for name in alice_hand:
        card = next(c for c in alice.library if c.name == pool[name].name)
        alice.library.remove(card)
        alice.hand.append(card)
    return game, alice, bob


@pytest.mark.cr("103.5b")
def test_the_action_is_taken_in_a_declaration_and_the_seat_then_declares(set_pool):
    """The exchange is made where the seat would declare, and the seat then
    declares over the new hand. Other players may already have declared: Bob,
    the starting player, keeps first; Alice exchanges in her own declaration
    and only then keeps."""
    game, alice, bob = _table(set_pool, ["Serum Powder"] + ["Grizzly Bears"] * 6)
    for name in ["Forest"] * 3 + ["Grizzly Bears"] * 4:
        card = next(c for c in bob.library if c.name == name)
        bob.library.remove(card)
        bob.hand.append(card)
    take_opening_mulligans(game, 1)
    exchange = next(i for i, line in enumerate(game.log) if "(Serum Powder)" in line)
    bob_keeps = next(i for i, line in enumerate(game.log) if line.startswith("Bob keeps"))
    alice_keeps = next(i for i, line in enumerate(game.log) if line.startswith("Alice keeps"))
    assert bob_keeps < exchange < alice_keeps, game.log
    assert len(alice.exile) == 7


@pytest.mark.cr("103.5b", "103.5")
def test_the_action_need_not_be_in_the_first_round(set_pool):
    """After a mulligan the seat may still exchange (the 2017-11-17 ruling:
    "taking a mulligan doesn't prevent you from using a Serum Powder's
    ability if you happen to draw one in your new hand"), and CR 103.5's
    bottom for that mulligan is paid before the hand is exiled; a mulligan
    taken after an exchange leaves the exiled cards in exile."""
    game, alice, bob = _table(set_pool, [])
    game.deal_opening_hands(0)
    assert game.pregame_mulligan_draw(0)
    alice.library.extend(alice.hand)
    alice.hand.clear()
    for name in ["Serum Powder"] + ["Grizzly Bears"] * 6:
        card = next(c for c in alice.library if c.name == name)
        alice.library.remove(card)
        alice.hand.append(card)
    assert game.pregame_hand_exchange(0, [1])
    assert len(alice.hand) == 6 and len(alice.exile) == 6
    exiled = list(alice.exile)
    assert game.pregame_mulligan_draw(0)
    assert alice.exile == exiled, "exiled for the rest of the game"
    assert len(alice.hand) == 7 and game.mulligan_bottom_owed(0) == 2


@pytest.mark.cr("103.5b")
def test_only_a_card_in_the_hand_grants_the_action(set_pool):
    """"…and this card is in your hand": no Powder in the hand, no exchange,
    and nothing moves."""
    game, alice, bob = _table(set_pool, ["Grizzly Bears"] * 7)
    assert not game.pregame_hand_exchange(0)
    assert len(alice.hand) == 7 and alice.exile == []
