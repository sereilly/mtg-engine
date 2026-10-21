"""A discard to hand size sets off what watches it in the same cleanup step.

CR 514.3a: "…the game checks to see if any state-based actions would be
performed and/or any triggered abilities are waiting to be put onto the stack.
If so, those state-based actions are performed, then those triggered abilities
are put on the stack, then the active player gets priority."

The cleanup step settled the stack only when a *delayed* trigger fired there,
so a trigger the CR 514.1 discard itself set off — Megrim's "Whenever an
opponent discards a card", or a madness card's own trigger (Torment) — was put
on the stack and left there into the next turn, resolving in its untap-to-
upkeep window a whole turn late. Found while driving madness (W1G1, Torment
wave 1): Obsessive Search discarded to hand size was cast on the *next* turn.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent


def test_megrim_punishes_a_cleanup_discard_in_that_cleanup_step():
    sth = {card.name: card for card in load_cards(manifest_set_path("STH"))}
    lea = {card.name: card for card in load_cards(manifest_set_path("LEA"))}
    game = Game(players=[
        PlayerState(name="P0", hand=[lea["Island"]] * 8),
        PlayerState(name="P1", battlefield=[Permanent(card=sth["Megrim"])]),
    ])
    game.active_player_index = 0
    assert game.resolve_cleanup_step(0)
    assert not game.stack
    assert game.players[0].life == 18
    assert len(game.players[0].hand) == 7
