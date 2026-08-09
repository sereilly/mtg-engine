"""Tests for Magic: The Gathering Comprehensive Rules Section 303.

Covers:
  303.4  — Auras, their enchant ability and the effects they apply

An Aura was classified supported by a single whitelist substring —
"enchant creature" — with nothing ever examining its effect lines. "Enchanted
creature glimmers uncontrollably" compiled as supported. So did an Aura whose
only line was the enchant clause. At 44 Auras in the pool that is 44 cards
whose support status was never actually checked.

engine/auras.py names the effect lines the engine carries out, and the compiler
requires every effect line of an Aura to match one. These tests use invented
Auras throughout: every real Aura in the pool is claimed, so a test built only
from real cards passes against the version that checked nothing.
"""

import pytest

from engine.auras import aura_effect_claim, unclaimed_aura_lines
from engine.card_loader import load_catalog
from engine.models import CardDefinition
from engine.oracle import compile_card_oracle, normalize_creature_line


def _aura(text: str, name: str = "Probe Aura") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{W}", cmc=1.0, type_line="Enchantment — Aura",
        oracle_text=text, colors=("W",), color_identity=("W",),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Enchantment — Aura"},
    )


@pytest.mark.cr("303.4")
def test_303_4_an_aura_with_an_unimplemented_effect_is_unsupported():
    """The whole point: "enchant creature" is a targeting restriction, not
    evidence that the Aura's effect is implemented."""
    for text in (
        "Enchant creature\nEnchanted creature glimmers uncontrollably.",
        "Enchant creature\nEnchanted creature has protection from everything.",
        "Enchant land\nEnchanted land produces an additional {G} when tapped.",
        "Enchant artifact\nEnchanted artifact hums a merry tune.",
    ):
        program = compile_card_oracle(_aura(text))
        assert not program.supported, text
        assert "unimplemented aura effect" in program.reason


@pytest.mark.cr("303.4")
def test_303_4_implemented_aura_effects_stay_supported():
    for text in (
        "Enchant creature\nEnchanted creature has flying.",
        "Enchant creature\nEnchanted creature gets +2/+2.",
        "Enchant creature\nEnchanted creature gets -1/-0.",
        "Enchant creature\nEnchanted creature gets +0/+2 and has reach.",
        "Enchant creature\nEnchanted creature has protection from red. "
        "This effect doesn't remove this Aura.",
        "Enchant land\nEnchanted land is a Swamp.",
        "Enchant creature\nYou control enchanted creature.",
    ):
        assert compile_card_oracle(_aura(text)).supported, text


@pytest.mark.cr("303.4")
def test_303_4_a_self_referential_etb_trigger_is_matched_by_the_cards_own_name():
    """Older printings name the card where modern Oracle says "this Aura". The
    subject is checked against the card's actual name — a wildcard subject
    would re-open the hole this table closes."""
    own = ("When Animate Dead enters, if it's on the battlefield, return "
           "enchanted creature card to the battlefield under your control.")
    assert aura_effect_claim(normalize_creature_line(own), "Animate Dead") is not None
    # Same sentence on a card that isn't Animate Dead is not its own ETB
    # trigger, and must not inherit the claim.
    assert aura_effect_claim(normalize_creature_line(own), "Unrelated Aura") is None


@pytest.mark.cr("303.4")
def test_303_4_every_aura_in_the_pool_has_all_its_effect_lines_claimed():
    """The ratchet. Ingesting a set with an Aura whose effect is not
    implemented fails here, naming the line."""
    unclaimed: list[tuple[str, str]] = []
    for card in load_catalog():
        if "aura" not in card.type_line.lower():
            continue
        lines = [normalize_creature_line(l) for l in card.oracle_text.split("\n")]
        for line in unclaimed_aura_lines(lines, card.name):
            unclaimed.append((card.name, line))
    assert not unclaimed, "Aura effect lines nothing implements:\n" + "\n".join(
        f"  {name}: {line}" for name, line in unclaimed
    )


@pytest.mark.cr("303.4")
def test_303_4_the_enchant_line_itself_is_not_an_effect():
    """"Enchant creature" is the targeting restriction (consumed by
    targeting.py), so it must not be mistaken for an implemented effect — an
    Aura carrying nothing else does nothing at all."""
    assert unclaimed_aura_lines(["enchant creature"]) == []
    assert aura_effect_claim("enchant creature") is None
