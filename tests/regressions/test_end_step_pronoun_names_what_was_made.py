"""'<Verb> it at the beginning of the next end step' behind a step that *made*
the permanent (found at INV W1G8, driving Cauldron Dance).

"Create a 3/1 black and red Graveborn creature token with haste. **Sacrifice
it** at the beginning of the next end step." compiled to
``arm_self_action_at_next_end_step`` with ``subject: bound``, whose handler
reads the pronoun as "the ability's target, else its source". Behind a token
maker both are wrong and nothing failed loudly:

* **Balduvian Dead** marked *itself* for the sacrifice and kept the token —
  the drawback landed on the wrong permanent and the 3/1 haste stayed for good;
* **Hornet Cannon** marked itself for destruction and kept the Hornet;
* **Tidal Wave** is an instant, so there was no source at all: the handler
  returned "ability not implemented" and the 5/5 Wall was permanent.

All three reported supported with every sentence claimed. The lowering now
freezes the maker's record into a delayed entry (CR 603.7c), the shape Sneak
Attack and Shallow Grave already compiled to.
"""

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(set_pool, code: str, name: str, *, on_battlefield: bool):
    """Seat 0 on its own turn holding *name* — on the battlefield or in hand."""
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    card = set_pool(code)[name]
    source = None
    if on_battlefield:
        source = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, source, None)
        source.metadata["summoning_sickness_turn"] = -99
    else:
        game.players[0].hand = [card]
    return game, source


def _mine(game) -> list[str]:
    return sorted(
        permanent.effective_card.name
        for permanent in game.controlled_by(game.players[0])
    )


def test_balduvian_dead_sacrifices_the_token_and_not_itself(set_pool):
    game, dead = _table(set_pool, "ALL", "Balduvian Dead", on_battlefield=True)
    game.players[0].graveyard.append(set_pool("LEA")["Hill Giant"])

    assert game.activate_permanent_ability(0, "Balduvian Dead").supported
    resolve_stack(game)
    assert _mine(game) == ["Balduvian Dead", "Graveborn Token"]

    game.resolve_end_step(0)
    resolve_stack(game)

    assert _mine(game) == ["Balduvian Dead"]
    assert game.is_on_battlefield(dead)


def test_hornet_cannon_destroys_the_hornet_and_not_itself(set_pool):
    game, cannon = _table(set_pool, "STH", "Hornet Cannon", on_battlefield=True)

    assert game.activate_permanent_ability(0, "Hornet Cannon").supported
    resolve_stack(game)
    assert _mine(game) == ["Hornet", "Hornet Cannon"]

    game.resolve_end_step(0)
    resolve_stack(game)

    assert _mine(game) == ["Hornet Cannon"]
    assert game.is_on_battlefield(cannon)


def test_tidal_wave_sacrifices_its_wall_at_the_next_end_step(set_pool):
    game, _none = _table(set_pool, "MIR", "Tidal Wave", on_battlefield=False)

    assert game.cast_from_hand(0, "Tidal Wave").supported
    resolve_stack(game)
    assert len(_mine(game)) == 1

    game.resolve_end_step(0)
    resolve_stack(game)

    assert _mine(game) == []
