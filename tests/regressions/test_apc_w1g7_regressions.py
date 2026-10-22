"""Shipped-card regressions found while Apocalypse's wave-1 group 7 drove its
cards (the stack, colour and type words).

Each test names the shipped card it is about and asserts what a game showed.
"""

from engine import Game, PlayerState
from engine.handlers.value_choices import _best_creature_type_to_sweep
from engine.models import Permanent
from tests.helpers import resolve_stack


def _duel():
    p0, p1 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    return game, p0, p1


def _put(game, seat, card):
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    return permanent


def test_extinctions_default_names_a_creature_type_not_a_land_type(catalog_by_name):
    """"Destroy all creatures of the creature type of your choice."
    (Extinction.) A seat nobody asks takes a stated default, and the default
    scored every *subtype* a creature had — so under Living Lands, where the
    opponent's Forests are creatures, the best-scoring word was "forest": not a
    creature type (CR 205.3m), and an answer the prompt's own resolver refuses
    from a human. The sweep then destroyed three animated lands.

    Found while giving "Choose a creature type **other than Wall**" (Unnatural
    Selection) its exclusion, which narrows the same default."""
    game, p0, p1 = _duel()
    _put(game, 0, catalog_by_name["Living Lands"])
    forests = [_put(game, 1, catalog_by_name["Forest"]) for _ in range(3)]
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])
    game._recompute_continuous_effects()
    assert all(forest.is_creature for forest in forests)

    assert _best_creature_type_to_sweep(game, 0) == "bear"

    p0.hand = [catalog_by_name["Extinction"]]
    assert game.cast_from_hand(0, "Extinction").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()

    assert bears not in p1.battlefield
    assert all(forest in p1.battlefield for forest in forests)
