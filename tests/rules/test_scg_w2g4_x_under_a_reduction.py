"""An X the caster leaves to the pool grows into a generic reduction
(CR 107.3, 601.2f, 118.7).

X is generic mana, and a cost reduction applies to the total cost — X
included — once X is a number (CR 601.2f). So when the caster names no X, the
largest X the pool can pay is measured against the cost *after* the reduction
has taken what it can from X. The inference measured it against the cost
without X, so a generic reduction the rest of the cost was too small to take
was spent on nothing: Krakilin ({X}{G}{G}) with six mana under Krosan Drover
("Creature spells you cast with mana value 6 or greater cost {2} less to
cast") was inferred X=4 — mana value 6, discounted to four mana — and two
mana stayed in the pool (W1G3 measured it and left it). It is X=6 now: mana
value 8, {6}{G}{G} less {2}, all six spent.

``PoolPaymentMixin._x_reduction_credit`` is the part of a reduction's reach
the cost without X leaves unused, read through ``reduce_cost`` itself.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog, load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}
_SCG = {
    card.name: card
    for card in load_cards(manifest_set_path("SCG", include_measured=True))
}


def _table(*permanents) -> Game:
    library = [_POOL["Grizzly Bears"]] * 10
    game = Game(players=[
        PlayerState(name="Alice", library=list(library)),
        PlayerState(name="Bob", library=list(library)),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 3
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    for card in permanents:
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return game


def _cast(game, card, mana, **announce):
    player = game.players[0]
    player.hand.append(card)
    player.mana_pool.clear()
    player.mana_pool.update(mana)
    result = game.cast_from_hand(0, card.name, **announce)
    return result, {k: v for k, v in player.mana_pool.items() if v}


@pytest.mark.cr("107.3", "601.2f", "118.7a")
def test_krakilin_under_krosan_drover_infers_the_x_the_discount_pays_for():
    game = _table(_SCG["Krosan Drover"])
    result, left = _cast(game, _POOL["Krakilin"], {"G": 2, "C": 4})
    assert result.supported, result.details
    assert left == {}, f"mana stranded in the pool: {left}"
    assert "Krakilin costs less to cast at X=6 (Krosan Drover)" in game.log, game.log[-4:]
    resolve_stack(game)
    (beast,) = [p for p in game.controlled_by(0) if p.card.name == "Krakilin"]
    assert (beast.effective_power, beast.effective_toughness) == (6, 6)


@pytest.mark.cr("107.3", "601.2f")
def test_an_announced_x_is_the_casters_and_is_not_grown():
    """The caster who names X keeps it (CR 107.3a: X is announced): at X=4 the
    discount still applies and the change is two mana left over."""
    game = _table(_SCG["Krosan Drover"])
    result, left = _cast(game, _POOL["Krakilin"], {"G": 2, "C": 4}, x_value=4)
    assert result.supported, result.details
    assert left == {"C": 2}
    resolve_stack(game)
    (beast,) = [p for p in game.controlled_by(0) if p.card.name == "Krakilin"]
    assert (beast.effective_power, beast.effective_toughness) == (4, 4)


@pytest.mark.cr("107.3", "118.7a")
def test_without_a_reduction_the_inferred_x_is_what_the_pool_pays():
    game = _table()
    result, left = _cast(game, _POOL["Krakilin"], {"G": 2, "C": 4})
    assert result.supported, result.details
    assert left == {}
    resolve_stack(game)
    (beast,) = [p for p in game.controlled_by(0) if p.card.name == "Krakilin"]
    assert (beast.effective_power, beast.effective_toughness) == (4, 4)
