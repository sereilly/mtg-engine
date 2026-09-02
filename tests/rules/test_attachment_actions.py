"""CR 701.3's attach action asked of an **Aura**, not only of an Equipment.

``engine/equipment.py`` owns the action for both kinds of Attachment — CR 701.3a
is one rule and its last sentence is explicit that what may be attached to what
is decided per kind: "An Aura, Equipment, or Fortification can't be attached to
an object or player it couldn't *enchant, equip, or fortify, respectively*."

Both call sites of that action used to ask ``equip_refusal`` outright, whose
CR 301.5c guard refuses anything that is not an Equipment. An Aura with its own
attach ability therefore had every host refused: the picker came back empty, the
ability resolved, logged "is no longer an Equipment" about a card that never was
one, and moved nothing. Alliances' Kjeldoran Pride is the card that found it,
but nothing about the failure is Alliances' — it is CR 701.3a asked with the
wrong half of itself.

The second test is the other end of the same ability: CR 601.2h pays costs
*after* targets are chosen, so a target restriction phrased against the cost
("other than the creature tapped this way") cannot be answered from a record the
cost has not yet written.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.equipment import attachment_refusal, equip_refusal
from engine.models import CardDefinition, Permanent


def _creature(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _aura(name: str, oracle: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}{W}", cmc=2.0,
        type_line="Enchantment - Aura", oracle_text=oracle, colors=("W",),
        color_identity=("W",), keywords=("Enchant",), produced_mana=(),
        raw={"name": name, "type_line": "Enchantment - Aura"},
    )


@pytest.mark.cr("701.3a", "303.4")
def test_the_attach_action_asks_the_legality_of_the_kind_that_is_attaching():
    """An Aura's hosts are decided by its enchant ability (CR 303.4), not by
    CR 301.5's Equipment rules.

    Asserted against ``equip_refusal`` in the same breath, because the bug was
    not that the Aura was refused for a *reason* — it was that the wrong
    predicate was asked at all, and that predicate's refusal names a subtype the
    card was never printed with.
    """
    host = Permanent(card=_creature("Host"))
    aura = Permanent(card=_aura(
        "Test Aura", "Enchant creature\nEnchanted creature gets +1/+2."
    ))
    game = Game(players=[
        PlayerState(name="P0", battlefield=[host, aura]),
        PlayerState(name="P1"),
    ])

    assert attachment_refusal(game, aura, host) is None
    assert "no longer an Equipment" in (equip_refusal(game, aura, host) or ""), (
        "the Equipment predicate refuses an Aura on its subtype, which is why "
        "asking it of one refused every host in the game"
    )


@pytest.mark.cr("701.3a", "301.5c")
def test_an_equipment_still_goes_through_the_equipment_half():
    """The dispatch must not have widened into "anything may attach to
    anything": an Equipment that is itself a creature still can't equip
    (CR 301.5c), and the refusal still comes from ``equip_refusal``."""
    host = Permanent(card=_creature("Host"))
    living = Permanent(card=CardDefinition(
        name="Living Blade", mana_cost="{2}", cmc=2.0,
        type_line="Artifact Creature - Equipment", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Living Blade",
             "type_line": "Artifact Creature - Equipment",
             "power": "1", "toughness": "1"},
    ))
    game = Game(players=[
        PlayerState(name="P0", battlefield=[host, living]),
        PlayerState(name="P1"),
    ])

    refusal = attachment_refusal(game, living, host)
    assert refusal is not None and "301.5c" in refusal


@pytest.mark.cr("701.3a", "303.4j")
def test_an_aura_may_not_attach_to_something_it_could_not_enchant():
    """CR 701.3a's last sentence, and CR 303.4j's "simply doesn't move it".

    The point of dispatching rather than skipping the check: an Aura reading
    "Enchant artifact" is refused a creature, by its **own** clause.
    """
    creature = Permanent(card=_creature("Bear"))
    aura = Permanent(card=_aura(
        "Artifact Only", "Enchant artifact\nEnchanted artifact gets +1/+2."
    ))
    game = Game(players=[
        PlayerState(name="P0", battlefield=[creature, aura]),
        PlayerState(name="P1"),
    ])

    assert attachment_refusal(game, aura, creature) is not None


@pytest.mark.cr("601.2h", "602.2b")
def test_a_cost_relative_target_restriction_is_answered_before_the_cost():
    """"Target creature other than the creature tapped this way" (Veteran's
    Voice).

    CR 601.2h pays costs after targets are chosen, so at the moment CR 602.2b's
    legality is asked the cost has tapped nothing and the engine's cost-tap
    record (``engine/cost_tap_records.py``) is still empty. A restriction read
    off that record would therefore exclude nobody as the ability is announced,
    and then exclude somebody at resolution — the picker and the enforcement
    disagreeing about one list.

    So the pronoun is resolved where the cost is known: the compiler refuses the
    phrase outright unless the ability's cost is the one that taps the attached
    permanent, and the filter then names that permanent.
    """
    from engine.oracle import _parse_activated_ability

    ability = _parse_activated_ability(
        "tap enchanted creature: target creature other than the creature "
        "tapped this way gets +2/+1 until end of turn",
        "Test",
    )
    assert ability is not None and ability.supported
    assert ability.cost.tap_attached
    described = ability.instruction.payload["targets"]["filter"]
    assert described.get("other_than_attached_host") is True

    # The same sentence with a cost that taps nothing names a referent this
    # ability's cost never touches, and is refused rather than read as
    # excluding some other permanent.
    unpaid = _parse_activated_ability(
        "{2}: target creature other than the creature tapped this way gets "
        "+2/+1 until end of turn",
        "Test",
    )
    assert unpaid is not None and not unpaid.supported
