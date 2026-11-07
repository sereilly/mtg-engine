"""Animate Dead's sacrifice waits for the event that took the Aura.

"When this Aura leaves the battlefield, that creature's controller sacrifices
it." The engine performs that leaves-the-battlefield ability inline, in the
Aura's teardown (``ControlSeamMixin._remove_aura_effects``), rather than putting
it on the stack (CR 603.6c). Performed the moment the Aura came off, it
reached a creature the same event was about to move:

* Upheaval taking the Aura first sacrificed the creature — its card went to
  the graveyard instead of its owner's hand;
* Apocalypse ("Exile all permanents") tore every Aura down before the one
  removal, so the creature was sacrificed and then exiled: its card was in a
  graveyard **and** in exile, two cards where there had been one.

The trigger resolves after the event, by when the creature is wherever the
event sent it and there is nothing to sacrifice. Now the inline sacrifice
waits for the departure event to close (``Game.after_this_departure``), and
the exile sweep tears its attachments down after its removal. A sweep that
leaves the creature behind (Harmonic Convergence, enchantments only) still
sacrifices it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from tests.helpers import resolve_stack

_CARDS = {card.name: card for card in load_catalog()}

GIANT = "Hill Giant"


def _reanimated(order: str) -> Game:
    game = Game(players=[
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 10) for i in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.players[0].graveyard.append(_CARDS[GIANT])
    game.players[0].hand.append(_CARDS["Animate Dead"])
    assert game.cast_from_hand(0, "Animate Dead", target_player_index=0).supported
    resolve_stack(game)
    names = [perm.card.name for perm in game.players[0].battlefield]
    assert sorted(names) == ["Animate Dead", GIANT], names
    # The sweep takes the battlefield in its order; put the Aura where the
    # row says.
    aura_first = names[0] == "Animate Dead"
    if aura_first != (order == "aura_first"):
        game.players[0].battlefield.reverse()
        game._sync_control()
    return game


def _where(game: Game, name: str) -> list[str]:
    found = [
        f"{zone}"
        for player in game.players
        for zone in ("hand", "graveyard", "exile", "library")
        for card in getattr(player, zone)
        if getattr(card, "name", None) == name
    ]
    found += ["battlefield" for perm in game.all_permanents() if perm.card.name == name]
    return sorted(found)


def _sweep(game: Game, spell: str) -> None:
    game.players[0].hand.append(_CARDS[spell])
    assert game.cast_from_hand(0, spell).supported
    for _ in range(50):
        if game.stack:
            resolve_stack(game)
        elif game.pending_choices:
            game.auto_resolve_pending_choices()
        else:
            return


@pytest.mark.parametrize("order", ["aura_first", "creature_first"])
@pytest.mark.parametrize("spell, zone", [("Apocalypse", "exile"), ("Upheaval", "hand")])
def test_a_sweep_taking_aura_and_creature_moves_the_creature_once(spell, zone, order):
    game = _reanimated(order)
    _sweep(game, spell)
    assert _where(game, GIANT) == [zone], (
        f"{spell} took Animate Dead and the {GIANT} in one event; the card is "
        f"in {_where(game, GIANT)}\n" + "\n".join(game.log[-8:])
    )
    assert not any("sacrificed Hill Giant" in line for line in game.log)


@pytest.mark.parametrize("order", ["aura_first", "creature_first"])
def test_a_sweep_leaving_the_creature_behind_still_sacrifices_it(order):
    game = _reanimated(order)
    _sweep(game, "Harmonic Convergence")
    assert _where(game, GIANT) == ["graveyard"]
    assert _where(game, "Animate Dead") == ["library"]
    assert game.departure_aftermath is None
