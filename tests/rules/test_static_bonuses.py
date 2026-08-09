"""Tests for Magic: The Gathering Comprehensive Rules Section 613.

Covers:
  613.1g — Layer 7c: effects that modify power/toughness

"Gets +N/+N as long as <condition>" is printed in two word orders. Only the
trailing one was dispatched; the leading one was admitted by a support-gate
literal that spelled out *Swamp*, so a card printed that way was reported
supported and never got the bonus — while the same sentence naming any other
land type was reported unsupported. These use invented cards throughout: a test
naming only Sedge Troll, Kird Ape and Giant Tortoise passes against the broken
version, because every real card in the pool uses the order that worked.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, normalize_creature_line
from engine.static_bonuses import BASIC_LAND_WORDS, static_bonus_for


def _shade(text: str) -> CardDefinition:
    return CardDefinition(
        name="Probe Shade", mana_cost="{2}{B}", cmc=3.0,
        type_line="Creature — Shade", oracle_text=text,
        colors=("B",), color_identity=("B",), keywords=(), produced_mana=(),
        raw={"name": "Probe Shade", "type_line": "Creature — Shade",
             "power": "1", "toughness": "1"},
    )


@pytest.mark.cr("613.1g")
def test_613_1g_both_word_orders_grant_the_same_bonus():
    trailing = static_bonus_for(normalize_creature_line(
        "This creature gets +1/+1 as long as you control a Swamp."))
    leading = static_bonus_for(normalize_creature_line(
        "As long as you control a Swamp, this creature gets +1/+1."))

    assert trailing is not None and leading is not None
    assert trailing == leading


@pytest.mark.cr("613.1g")
def test_613_1g_the_leading_order_works_for_every_land_type():
    """The gate listed this order as a literal naming Swamp, and the dispatch
    regex did not handle the order at all — so Swamp was supported-and-wrong
    and every other type was unsupported."""
    for land in BASIC_LAND_WORDS:
        program = compile_card_oracle(_shade(
            f"As long as you control a {land.title()}, this creature gets +2/+3."))
        assert program.supported, land
        bonuses = [i for i in program.instructions if i.kind == "conditional_land_bonus"]
        assert len(bonuses) == 1, f"{land}: {program.instructions}"
        assert bonuses[0].payload == {"power": 2, "toughness": 3, "land_type": land}


@pytest.mark.cr("613.1g")
def test_613_1g_the_leading_order_actually_applies_the_bonus():
    """Payload-correct is not behaviour-correct. Against the old code this card
    compiled to a bare static line and stayed 1/1 while reporting supported."""
    catalog = {c.name: c for c in load_catalog()}
    shade = Permanent(card=_shade(
        "As long as you control a Mountain, this creature gets +3/+3."))
    player = PlayerState(name="P1", battlefield=[shade])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game._refresh_dynamic_creatures()
    assert (shade.effective_power, shade.effective_toughness) == (1, 1)

    player.battlefield.append(Permanent(card=catalog["Mountain"]))
    game._refresh_dynamic_creatures()
    assert (shade.effective_power, shade.effective_toughness) == (4, 4)


@pytest.mark.cr("613.1g")
def test_613_1g_an_unrecognized_condition_is_unsupported_not_silently_dropped():
    """A condition this table cannot evaluate must fail loud. The gate used to
    admit the leading order by prefix, so an unimplemented condition in that
    position became a static line and the creature quietly kept its printed
    P/T."""
    program = compile_card_oracle(_shade(
        "As long as you control a Wall, this creature gets +1/+1."))
    assert not program.supported


@pytest.mark.cr("613.1g")
def test_613_1g_real_cards_are_unchanged():
    catalog = {c.name: c for c in load_catalog()}
    expected = {
        "Sedge Troll": {"power": 1, "toughness": 1, "land_type": "swamp"},
        "Kird Ape": {"power": 1, "toughness": 2, "land_type": "forest"},
    }
    for name, payload in expected.items():
        program = compile_card_oracle(catalog[name])
        bonuses = [i for i in program.instructions if i.kind == "conditional_land_bonus"]
        assert len(bonuses) == 1, name
        assert bonuses[0].payload == payload
