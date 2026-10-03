"""Destructive Urge: "Whenever enchanted creature deals combat damage to a
player, **that player** sacrifices a land of their choice."

Found at Prophecy wave 1 (W1G6), extending the sacrifice payers for Thresher
Beast's "defending player". The sacrifice lowering read "that player" under a
damage event through the *controller* table, whose damage row names the
**damager's** controller (Backfire's reading) — so the Aura's own controller,
the attacking seat, sacrificed a land each time the creature connected, and
the damaged player lost nothing. Census at the round: of the 58 damage
triggers in the pool, this was the only sacrifice reading that seat.
"""

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import _mk_card, resolve_stack


def _put(game, seat, card):
    perm = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def test_destructive_urge_makes_the_damaged_player_sacrifice():
    urge_card = next(
        card for card in load_cards(manifest_set_path("USG"))
        if card.name == "Destructive Urge"
    )
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    attacker = _put(game, 0, _mk_card("Bear", "Creature — Bear"))
    my_lands = [_put(game, 0, _mk_card(n, f"Basic Land — {n}")) for n in ("Forest", "Swamp")]
    their_lands = [_put(game, 1, _mk_card(n, f"Basic Land — {n}")) for n in ("Island", "Mountain")]
    attach_aura(_put(game, 0, urge_card), attacker)

    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    for _ in range(6):
        game.advance_combat_phase()
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        resolve_stack(game)

    assert game.players[1].life == 18
    assert all(game.is_on_battlefield(land) for land in my_lands)
    assert not game.players[0].graveyard
    assert sum(game.is_on_battlefield(land) for land in their_lands) == 1
    assert [c.name for c in game.players[1].graveyard] in (["Island"], ["Mountain"])
