"""Disintegrate's "if it would die this turn, exile it instead" puts the card
in its **owner's** exile pile, as Dreams of the Dead's "exile it instead"
already did (``replacements/zone_changes._exile_instead_of_leaving``).

kg4's ``asks`` group read it: ``_exile_instead_of_dying`` exiled into
``payload["player"]`` — the dying permanent's controller — so a stolen
creature (Desertion, Control Magic) killed under Disintegrate's marker sat
in its thief's exile pile. The card's owner is unchanged by the steal
(CR 108.3), and every exile arrival in the engine goes to the owner's pile.
"""
from __future__ import annotations

from engine import Game, PlayerState


def _stolen_bears(set_pool):
    lea, vis = set_pool("LEA"), set_pool("VIS")
    p1 = PlayerState(name="P1", hand=[vis["Desertion"]])
    p2 = PlayerState(name="P2", hand=[lea["Grizzly Bears"]], library=[lea["Island"]] * 3)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.queue_from_hand(1, "Grizzly Bears")
    game.queue_from_hand(0, "Desertion", target_stack_index=0)
    game.resolve_stack()
    (stolen,) = p1.battlefield
    assert game.controller_index_of(stolen) == 0
    assert game.owner_index_of(stolen) == 1
    return game, p1, p2, stolen


def test_a_stolen_creature_disintegrated_goes_to_its_owners_exile(set_pool):
    game, p1, p2, stolen = _stolen_bears(set_pool)
    stolen.metadata["exile_if_dies_this_turn"] = "Disintegrate"
    stolen.damage_marked = 2
    game.check_state_based_actions()

    assert stolen not in p1.battlefield, game.log[-4:]
    assert [card.name for card in p2.exile] == ["Grizzly Bears"], game.log[-4:]
    assert p1.exile == [], game.log[-4:]
    assert "Grizzly Bears" not in [c.name for p in (p1, p2) for c in p.graveyard]
    assert any("exiled instead of dying" in line for line in game.log)


def test_an_unstolen_creature_disintegrated_stays_in_its_owners_exile(set_pool):
    """The control: a creature its owner controls is exiled where it was."""
    lea = set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[lea["Grizzly Bears"]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.queue_from_hand(0, "Grizzly Bears")
    game.resolve_stack()
    (bears,) = p1.battlefield
    bears.metadata["exile_if_dies_this_turn"] = "Disintegrate"
    bears.damage_marked = 2
    game.check_state_based_actions()

    assert [card.name for card in p1.exile] == ["Grizzly Bears"], game.log[-4:]
    assert p2.exile == []
