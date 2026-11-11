"""A harmful Aura's -X/-X goes on the host it kills.

Both ways an Aura gets a host by the AI's choice ranked the other side's
creatures by board order (``ai_targets._choose_aura_target``, the cast) or by
the side alone (``ai_targets.choose_returning_aura_host``, the Aura put onto
the battlefield without a cast): Screams from Within came back onto a Grizzly
Bears it shrinks, beside a Llanowar Elves it would kill (DST W1G9), and a
Weakness was cast at whichever opposing creature had been out longest.
``ai_targets.aura_kills_its_host`` reads the Aura's static grant the way the
layers apply it (``aura_grants.aura_static_pt_grant``) and puts the host it
leaves at 0 toughness (CR 704.5f) first.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_targets import _choose_aura_target, aura_kills_its_host, choose_returning_aura_host
from engine.models import Permanent


def _table(set_pool, hand=()) -> Game:
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name="AI", hand=list(hand), library=[lea["Swamp"]] * 8),
        PlayerState(name="Opp", library=[lea["Forest"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game


def _put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_the_static_grant_is_what_kills(set_pool):
    """Weakness's -2/-1 kills an X/1 and not a 2/2; Holy Strength's +1/+2
    kills nothing; Paralyze prints no P/T at all."""
    lea = set_pool("LEA")
    game = _table(set_pool)
    elves = _put(game, 1, lea["Llanowar Elves"])
    bears = _put(game, 1, lea["Grizzly Bears"])
    assert aura_kills_its_host(lea["Weakness"], elves)
    assert not aura_kills_its_host(lea["Weakness"], bears)
    assert not aura_kills_its_host(lea["Holy Strength"], elves)
    assert not aura_kills_its_host(lea["Paralyze"], elves)


def test_weakness_is_cast_at_the_creature_it_kills(set_pool):
    """Grizzly Bears out first, Llanowar Elves beside it: the cast's host is
    the Elves, which -2/-1 kills, not the first on the board."""
    lea = set_pool("LEA")
    game = _table(set_pool, hand=[lea["Weakness"]])
    _put(game, 1, lea["Grizzly Bears"])
    elves = _put(game, 1, lea["Llanowar Elves"])
    seat, index = _choose_aura_target(game, 0, lea["Weakness"])
    assert seat == 1 and game.players[1].battlefield[index] is elves


def test_a_returning_harmful_aura_takes_the_host_it_kills(set_pool):
    """The pick for an Aura returned without a cast, among both sides'
    creatures: the other side's first, and of those the one it kills."""
    lea, dst = set_pool("LEA"), set_pool("DST")
    game = _table(set_pool)
    own = _put(game, 0, lea["Llanowar Elves"])
    bears = _put(game, 1, lea["Grizzly Bears"])
    elves = _put(game, 1, lea["Llanowar Elves"])
    screams = dst["Screams from Within"]
    assert choose_returning_aura_host(game, 0, screams, [own, bears, elves]) is elves
    assert choose_returning_aura_host(game, 0, screams, [own, bears]) is bears
