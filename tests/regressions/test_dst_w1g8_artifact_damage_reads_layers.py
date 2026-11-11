"""Reverse Polarity counts damage dealt "by artifacts" — what the source *is*.

"You gain X life, where X is twice the damage dealt to you so far this turn by
artifacts." (Reverse Polarity.) The tally (``PlayerState
.artifact_damage_taken_this_turn``) read the source permanent's **printed**
type line, so a creature Mycosynth Lattice or Memnarch had made an artifact
dealt "non-artifact" damage, and an artifact creature Neurok Transmuter had
stripped of the type still counted. The source is asked through layer 4 now.
"""

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import drive_combat, declare_attack, settle


def _table(set_pool):
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[island] * 20) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _put(game, card, seat=0):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._settle()
    return permanent


def test_a_creature_the_lattice_made_an_artifact_deals_artifact_damage(set_pool):
    game = _table(set_pool)
    _put(game, set_pool("LEA")["Grizzly Bears"])
    _put(game, set_pool("DST")["Mycosynth Lattice"])
    settle(game)
    declare_attack(game, 0)
    drive_combat(game)
    assert game.players[1].life == 18
    assert game.players[1].artifact_damage_taken_this_turn == 2


def test_an_artifact_creature_neurok_stripped_deals_no_artifact_damage(set_pool):
    game = _table(set_pool)
    myr = _put(game, set_pool("MRD")["Myr Enforcer"])
    _put(game, set_pool("DST")["Neurok Transmuter"])
    assert game.activate_permanent_ability(
        0, "Neurok Transmuter", ability_index=1,
        target_permanent_ids=[myr.permanent_id],
    ).supported
    settle(game)
    assert not myr.has_type("artifact")
    attackers = declare_attack(game, 0)
    assert myr in attackers
    drive_combat(game)
    assert game.players[1].life == 20 - 4 - 2   # the Myr and the Transmuter
    assert game.players[1].artifact_damage_taken_this_turn == 0


def test_reverse_polarity_reads_the_tally(set_pool):
    """The spell itself, after a Lattice-artifact Bears hit its caster."""
    game = _table(set_pool)
    _put(game, set_pool("LEA")["Grizzly Bears"], seat=1)
    _put(game, set_pool("DST")["Mycosynth Lattice"], seat=1)
    game.players[0].hand.append(set_pool("ATQ")["Reverse Polarity"])
    game.start_turn(1)
    settle(game)
    declare_attack(game, 1)
    drive_combat(game)
    assert game.players[0].life == 18
    assert game.queue_from_hand(0, "Reverse Polarity").supported
    settle(game)
    assert game.players[0].life == 22
