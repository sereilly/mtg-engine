"""CR 701.19 — regeneration, in both of its shapes.

A shield (701.19a) is created by a resolving spell or ability and is spent by the
next destruction this turn. A *static* regeneration (701.19b) is the permanent's
own text and applies **each time** it would be destroyed; there is nothing to
spend. Both are the same decision at the same moment — "is this destruction
replaced?" — and `engine/regeneration.py` is where both are answered, because
the shield half had been written out at each destruction path and the two copies
had already drifted over whether the marked damage is removed.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_cards, manifest_set_path
from engine.models import CardDefinition, Permanent, PlayerState
from engine.regeneration import (
    regenerates_itself,
    regeneration_replaces_destruction,
    self_regeneration_line,
)

_LEG = {
    c.name: c
    for c in load_cards(manifest_set_path("LEG", include_measured=True))
}


def _r29_vanilla(name: str, power: int, toughness: int, text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _r29_game(card):
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, permanent, None)
    game._settle()
    return game, permanent


@pytest.mark.cr("701.19a")
def test_a_shield_is_spent_by_one_destruction():
    game, bear = _r29_game(_r29_vanilla("Shielded Bear", 2, 2))
    bear.regeneration_shield = 1

    assert regeneration_replaces_destruction(game, bear)
    assert bear.regeneration_shield == 0
    assert bear.tapped

    assert not regeneration_replaces_destruction(game, bear)


@pytest.mark.cr("701.19a")
def test_regeneration_removes_the_marked_damage():
    """Both destruction paths go through this, which is the drift the seam
    removed: one of them left the damage marked, so a creature the lethal-damage
    sweep regenerated was destroyed again on the next pass."""
    game, bear = _r29_game(_r29_vanilla("Shielded Bear", 2, 2))
    bear.regeneration_shield = 1
    bear.damage_marked = 2

    assert regeneration_replaces_destruction(game, bear)
    assert bear.damage_marked == 0


@pytest.mark.cr("701.19b")
def test_a_static_regeneration_applies_every_time_and_spends_nothing():
    game, clergy = _r29_game(_LEG["Clergy of the Holy Nimbus"])

    assert regenerates_itself(clergy)
    for _ in range(3):
        clergy.tapped = False
        assert regeneration_replaces_destruction(game, clergy)
        assert clergy.tapped
    assert clergy.regeneration_shield == 0


@pytest.mark.cr("701.19b", "616.1")
def test_a_static_regeneration_is_preferred_over_a_shield():
    """Both are replacement effects and the choice is the affected permanent's
    controller's; no controller spends a one-shot shield while an unlimited
    static is available, so the shield survives for later."""
    game, clergy = _r29_game(_LEG["Clergy of the Holy Nimbus"])
    clergy.regeneration_shield = 1

    assert regeneration_replaces_destruction(game, clergy)
    assert clergy.regeneration_shield == 1


@pytest.mark.cr("701.19c")
def test_cant_be_regenerated_makes_both_shapes_inert():
    game, clergy = _r29_game(_LEG["Clergy of the Holy Nimbus"])
    clergy.regeneration_shield = 1
    clergy.metadata["cant_be_regenerated_this_turn"] = True

    assert not regeneration_replaces_destruction(game, clergy)
    assert clergy.regeneration_shield == 1, "the rider stops it being applied, not created"


@pytest.mark.cr("701.19b")
def test_the_static_is_claimed_only_by_the_unconditional_printing():
    """A conditional variant is a different replacement and has to keep
    refusing, rather than be admitted by a prefix and then regenerate always."""
    assert self_regeneration_line("If this creature would be destroyed, regenerate it.")
    assert self_regeneration_line("If this artifact would be destroyed, regenerate it")
    assert not self_regeneration_line(
        "If this creature would be destroyed during your turn, regenerate it."
    )
    assert not self_regeneration_line("Regenerate this creature.")


@pytest.mark.cr("701.19b", "707.2")
def test_the_static_is_read_off_the_effective_card():
    """A copy has the ability and a permanent that lost its abilities does not,
    so the question is asked of layer 1/6's answer rather than the printed card."""
    game, bear = _r29_game(_r29_vanilla("Plain Bear", 2, 2))
    assert not regenerates_itself(bear)

    game, clergy = _r29_game(_LEG["Clergy of the Holy Nimbus"])
    assert regenerates_itself(clergy)
    assert clergy.effective_card.oracle_text == clergy.card.oracle_text
