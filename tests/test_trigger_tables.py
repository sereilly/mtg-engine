"""Guards against first-match-wins shadowing in the trigger-condition tables.

The tables in engine/oracle.py are matched with an unanchored ``re.match`` in
listed order, so a pattern that is a strict prefix of a later pattern's
canonical text silently swallows it (this happened to
``creature_attacks_or_blocks`` and ``hypnotic_specter_deals_damage``). Each
pattern gets a canonical example text here; every earlier pattern must fail to
match every later pattern's example.
"""

from __future__ import annotations

import re

import pytest

from engine.card_loader import load_cards
from engine.oracle import (
    AT_TRIGGER_PATTERNS,
    WHEN_TRIGGER_PATTERNS,
    WHENEVER_TRIGGER_PATTERNS,
    compile_card_oracle,
)

from tests.helpers import _mk_creature_card

# Canonical oracle-text (normalized) example for every trigger-condition kind.
# When adding a pattern to a table, add its example here — the shadowing test
# fails otherwise.
EXAMPLE_TEXTS: dict[str, str] = {
    # whenever
    "land_dies": "whenever a land is put into a graveyard from the battlefield",
    "creature_dies": "whenever a creature dies",
    "creature_you_control_dies": "whenever a creature you control dies",
    "creature_deals_damage": "whenever this creature deals damage",
    "creature_deals_combat_damage": "whenever this creature deals combat damage to a player",
    "cockatrice_blocks_or_blocked": "whenever this creature blocks or becomes blocked by a non-wall creature",
    "hypnotic_specter_deals_damage": "whenever this creature deals damage to an opponent",
    "creature_attacks": "whenever this creature attacks",
    "creature_blocks": "whenever this creature blocks",
    "creature_becomes_blocked": "whenever this creature becomes blocked",
    "creature_attacks_or_blocks": "whenever this creature attacks or blocks",
    "creature_dealt_damage": "whenever this creature is dealt damage",
    "creature_dealt_damage_by_self_dies": "whenever a creature dealt damage by this creature this turn dies",
    "enchanted_land_tapped": "whenever enchanted land becomes tapped",
    "land_tapped_for_mana": "whenever a player taps a land for mana",
    "spell_cast": "whenever a player casts a spell",
    "opponent_casts_spell": "whenever an opponent casts a spell",
    "you_cast_spell": "whenever you cast a spell",
    "enchantment_cast": "whenever you cast an enchantment spell",
    "creature_enters": "whenever a creature enters the battlefield",
    "land_enters": "whenever a land enters the battlefield",
    "artifact_enters": "whenever an artifact enters the battlefield",
    "one_or_more_attack": "whenever one or more creatures you control attack",
    "draws_card": "whenever you draw a card",
    "deals_damage_to_player": "whenever this creature deals damage to a player",
    # when
    "enters_battlefield": "when this creature enters the battlefield",
    "leaves_battlefield": "when this creature leaves the battlefield",
    "dies": "when this creature dies",
    "you_gain_life": "when you gain life",
    "becomes_target": "when this creature becomes the target of a spell",
    "no_islands": "when you control no islands",
    # at
    "upkeep_self": "at the beginning of your upkeep",
    "upkeep_each": "at the beginning of each upkeep",
    "upkeep_enchanted_controller": "at the beginning of the upkeep of enchanted creature's controller",
    "upkeep_chosen": "at the beginning of the chosen player's upkeep",
    "draw_step_each": "at the beginning of each player's draw step",
    "end_step": "at the beginning of the end step",
    "combat": "at the beginning of combat",
}

_TABLES = [
    ("whenever", WHENEVER_TRIGGER_PATTERNS),
    ("when", WHEN_TRIGGER_PATTERNS),
    ("at", AT_TRIGGER_PATTERNS),
]


def test_every_pattern_has_an_example():
    missing = [
        kind
        for _, table in _TABLES
        for kind, _ in table
        if kind not in EXAMPLE_TEXTS
    ]
    assert not missing, f"add canonical examples for: {missing}"


def test_every_example_matches_its_own_pattern():
    for _, table in _TABLES:
        for kind, pattern in table:
            example = EXAMPLE_TEXTS.get(kind)
            if example is None:
                continue  # covered by test_every_pattern_has_an_example
            assert re.match(pattern, example), (
                f"{kind}: canonical example {example!r} does not match its own pattern"
            )


@pytest.mark.parametrize("table_name,table", _TABLES)
def test_no_pattern_shadows_a_later_one(table_name, table):
    """An earlier pattern must never match a later pattern's canonical text —
    otherwise the later (more specific) pattern is dead code."""
    for i, (early_kind, early_pattern) in enumerate(table):
        for later_kind, _ in table[i + 1:]:
            example = EXAMPLE_TEXTS.get(later_kind)
            if example is None:
                continue
            assert not re.match(early_pattern, example), (
                f"{table_name}: pattern {early_kind!r} shadows {later_kind!r} "
                f"(matches its example {example!r}); move the specific pattern first"
            )


# --- regression: the two shadows found in the LEA-era table -----------------

def test_attacks_or_blocks_compiles_to_specific_kind():
    card = _mk_creature_card(
        "Shadow Test", 1, 1,
        "Whenever this creature attacks or blocks, it gets +1/+0 until end of turn.",
    )
    program = compile_card_oracle(card)
    kinds = [ta.condition.kind for ta in program.triggered_abilities]
    assert "creature_attacks_or_blocks" in kinds
    assert "creature_attacks" not in kinds


def test_hypnotic_specter_compiles_to_specific_kind():
    cards = {c.name: c for c in load_cards("lea_cards.json")}
    program = compile_card_oracle(cards["Hypnotic Specter"])
    kinds = [ta.condition.kind for ta in program.triggered_abilities]
    assert kinds == ["hypnotic_specter_deals_damage"]
