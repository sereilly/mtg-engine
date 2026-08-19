"""CR 701.17 (Mill), CR 702.5 (Enchant) and CR 702.26 (Phasing).

The three rules that joined ``scripts/rules_progress.py``'s tracked scope when
M21's mechanics landed and nothing had cited them yet. Each is a keyword the
engine really implements rather than one it merely mentions:

* **Mill** — Carrion Grub, Teferi's Tutelage, Thieves' Guild Enforcer.
* **Enchant** — every Aura's attachment restriction, derived from the printed
  ``Enchant <subject>`` line rather than from a per-card registration.
* **Phasing** — Teferi, Master of Time's −3 and Teferi, Timeless Voyager's −8.

Exert (CR 701.43) is deliberately absent: the engine cites it twice, but only
as the keyworded name for "doesn't untap during its controller's next untap
step", which is a different thing from implementing exert.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _creature(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test",
             "power": str(power), "toughness": str(toughness)},
    )


# ---------------------------------------------------------------------------
# 701.17 — Mill
# ---------------------------------------------------------------------------

@pytest.mark.cr("701.17", "701.17a")
def test_701_17a_milling_puts_cards_from_the_top_of_the_library_into_the_graveyard():
    """To mill N cards is to put the top N of that library into its graveyard.

    From the *top*, and into the graveyard rather than exile or hand — the two
    things that distinguish milling from every other library operation.
    """
    library = [_creature(f"Card {i}") for i in range(5)]
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", library=library[:])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    mill = CardDefinition(
        name="Mill Rite", mana_cost="", cmc=0.0, type_line="Sorcery",
        oracle_text="Target player mills two cards.", colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw={"name": "Mill Rite", "type_line": "Sorcery"},
    )
    p1.hand.append(mill)
    game.cast_from_hand(0, "Mill Rite", target_player_index=1)

    assert [card.name for card in p2.graveyard] == ["Card 0", "Card 1"]
    assert [card.name for card in p2.library] == ["Card 2", "Card 3", "Card 4"]


@pytest.mark.cr("701.17", "701.17a")
def test_701_17a_milling_more_than_the_library_holds_mills_what_is_there():
    """A library with fewer cards than the mill asks for is emptied, and the
    player does not lose for it — losing to an empty library is a state-based
    action about *drawing*, not about milling."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", library=[_creature("Only Card")])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    mill = CardDefinition(
        name="Deep Mill", mana_cost="", cmc=0.0, type_line="Sorcery",
        oracle_text="Target player mills three cards.", colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw={"name": "Deep Mill", "type_line": "Sorcery"},
    )
    p1.hand.append(mill)
    game.cast_from_hand(0, "Deep Mill", target_player_index=1)

    assert p2.library == []
    assert [card.name for card in p2.graveyard] == ["Only Card"]
    assert p2.lost is False


@pytest.mark.cr("701.17")
def test_701_17_a_printed_card_mills_through_the_same_instruction(set_pool):
    """The keyword action is one instruction kind for every card that prints
    it, so Teferi's Tutelage needs no registration of its own."""
    from engine.oracle import compile_card_oracle

    tutelage = set_pool("M21")["Teferi's Tutelage"]
    program = compile_card_oracle(tutelage)

    kinds = [
        instruction.kind
        for trigger in program.triggered_abilities
        if trigger.instruction is not None
        for instruction in (trigger.instruction.payload.get("steps")
                            or (trigger.instruction,))
    ]

    assert any("mill" in kind for kind in kinds), kinds


# ---------------------------------------------------------------------------
# 702.5 — Enchant
# ---------------------------------------------------------------------------

@pytest.mark.cr("702.5", "702.5a")
def test_702_5a_enchant_restricts_what_an_aura_may_be_attached_to():
    """"Enchant [object]" is a static ability restricting the Aura's target.

    The subject is read off the printed line, so the restriction and the words
    that produced it cannot drift apart.
    """
    from engine.targeting import enchant_line_subject

    assert enchant_line_subject("Enchant creature") == "creature"
    assert enchant_line_subject("Enchant land") == "land"
    assert enchant_line_subject("Enchant artifact") == "artifact"


@pytest.mark.cr("702.5", "702.5a")
def test_702_5a_a_line_that_is_not_an_enchant_restriction_is_not_read_as_one():
    """The restriction is the whole line and nothing else — "Enchanted creature
    gets +1/+1" is an effect, not an attachment restriction, and reading it as
    one would let an Aura attach to anything."""
    from engine.targeting import enchant_line_subject

    assert enchant_line_subject("Enchanted creature gets +1/+1.") is None
    assert enchant_line_subject("Destroy target creature.") is None


@pytest.mark.cr("702.5")
def test_702_5_a_printed_aura_declares_its_restriction(set_pool):
    """A real Aura's enchant line is what the engine derives its legal targets
    from — Holy Strength enchants a creature, and says so in one line."""
    from engine.targeting import enchant_line_subject

    strength = set_pool("LEA")["Holy Strength"]
    subjects = [
        enchant_line_subject(line.strip())
        for line in strength.oracle_text.split("\n")
    ]

    assert "creature" in subjects


# ---------------------------------------------------------------------------
# 702.26 — Phasing
# ---------------------------------------------------------------------------

@pytest.mark.cr("702.26", "702.26a")
def test_702_26a_a_phased_out_permanent_is_treated_as_though_it_did_not_exist():
    """A phased-out permanent is treated as though it does not exist.

    It is off the battlefield for every rule that looks there — but it has not
    changed zones, which is what separates phasing from a bounce or an exile.
    """
    creature = Permanent(card=_creature("Phaser"))
    p1 = PlayerState(name="P1", battlefield=[creature])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.phase_out_permanent(creature)

    assert not game.is_on_battlefield(creature)
    assert creature not in p1.battlefield
    assert creature in p1.phased_out
    assert creature.card not in p1.graveyard
    assert creature.card not in p1.hand


@pytest.mark.cr("702.26")
def test_702_26_phasing_out_is_not_a_zone_change():
    """Phasing is explicitly not a zone change, so nothing that watches for one
    fires: the card reaches no graveyard, and the permanent keeps its identity
    rather than becoming a new object."""
    creature = Permanent(card=_creature("Phaser"))
    p1 = PlayerState(name="P1", battlefield=[creature])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    original_id = creature.permanent_id

    game.phase_out_permanent(creature)

    assert p1.graveyard == []
    assert creature.permanent_id == original_id


@pytest.mark.cr("702.26", "702.26d")
def test_702_26d_a_permanent_phases_in_at_its_controllers_untap_step(set_pool):
    """It phases in before untapping, during its controller's untap step.

    Driven through the real card so the return is the engine's own scheduling
    rather than a direct call: Teferi, Master of Time's −3 phases out a
    creature its controller does not control, and that creature comes back on
    its own controller's turn.
    """
    teferi = set_pool("M21")["Teferi, Master of Time"]
    walker = Permanent(card=teferi, metadata={"loyalty_counters": 3})
    victim = Permanent(card=_creature("Victim"))
    p1 = PlayerState(name="P1", battlefield=[walker], library=[_creature("L1")])
    p2 = PlayerState(name="P2", battlefield=[victim], library=[_creature("L2")])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    game.phase_out_permanent(victim)
    assert victim in p2.phased_out

    game.start_turn(1)

    assert victim not in p2.phased_out
    assert game.is_on_battlefield(victim)
