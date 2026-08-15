"""Guards against first-match-wins shadowing in the trigger-condition tables.

The tables in engine/oracle.py are matched with an unanchored ``re.match`` in
listed order, so a pattern that is a strict prefix of a later pattern's
canonical text silently swallows it (this happened to
``creature_attacks_or_blocks`` and ``creature_deals_damage_to_opponent``). Each
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
from tests.helpers import LEA_PATH

# Canonical oracle-text (normalized) example for every trigger-condition kind.
# When adding a pattern to a table, add its example here — the shadowing test
# fails otherwise.
#
# A kind may carry **several** examples, as a tuple: one printed wording per
# pattern that names it ("whenever a creature you control dies" and the
# explicit-self spelling Basri's Lieutenant prints). Without that, a second
# spelling would be untested by the shadowing guard — the lookup is by kind,
# so it would only ever see the first.
EXAMPLE_TEXTS: dict[str, str | tuple[str, ...]] = {
    # whenever
    "land_dies": "whenever a land is put into a graveyard from the battlefield",
    "creature_dies": "whenever a creature dies",
    "creature_you_control_dies": (
        "whenever a creature you control dies",
        "whenever this creature or another creature you control dies",
    ),
    "creature_opponent_controls_dies": "whenever a creature an opponent controls dies",
    "creature_deals_damage": "whenever this creature deals damage",
    "creature_deals_combat_damage": "whenever this creature deals combat damage to a player",
    "creature_blocks_or_blocked_by_nonwall": "whenever this creature blocks or becomes blocked by a non-wall creature",
    "creature_deals_damage_to_opponent": "whenever this creature deals damage to an opponent",
    "creature_attacks": "whenever this creature attacks",
    # A narrowed spelling beside its bare one: the subject filter is what makes
    # the pair two different firings (CR 509.3c/509.3d), so both are checked
    # against every earlier pattern of every other kind.
    "matching_creature_attacks": "whenever a creature you control with deathtouch attacks",
    "matching_creature_damages_planeswalker": (
        "whenever a creature you control with deathtouch deals damage to a planeswalker"
    ),
    "creature_blocks": (
        "whenever this creature blocks",
        "whenever this creature blocks a creature with flying",
    ),
    "creature_becomes_blocked": (
        "whenever this creature becomes blocked",
        "whenever this creature becomes blocked by a creature",
    ),
    "creature_attacks_or_blocks": "whenever this creature attacks or blocks",
    "creature_dealt_damage": "whenever this creature is dealt damage",
    "creature_dealt_damage_by_self_dies": "whenever a creature dealt damage by this creature this turn dies",
    "enchanted_land_tapped": "whenever enchanted land becomes tapped",
    "self_becomes_tapped": "whenever this land becomes tapped",
    "permanent_becomes_tapped": "whenever a forest an opponent controls becomes tapped",
    "land_tapped_for_mana": "whenever a player taps a land for mana",
    "spell_cast": "whenever a player casts a spell",
    "opponent_casts_spell": "whenever an opponent casts a spell",
    "you_cast_spell": "whenever you cast a spell",
    "enchantment_cast": "whenever you cast an enchantment spell",
    "land_enters": "whenever a land enters the battlefield",
    "matching_permanent_enters": (
        "whenever a creature you control with power 4 or greater enters"
    ),
    "one_or_more_attack": "whenever one or more creatures you control attack",
    "draws_card": "whenever you draw a card",
    "draws_second_card": "whenever you draw your second card each turn",
    "you_gain_life": "whenever you gain life",
    "counters_put_on_creature": (
        "whenever one or more +1/+1 counters are put on another non-hydra "
        "creature you control"
    ),
    "deals_damage_to_player": "whenever this creature deals damage to a player",
    # when
    "enters_battlefield": "when this creature enters the battlefield",
    "leaves_battlefield": "when this creature leaves the battlefield",
    "dies": "when this creature dies",
    "becomes_target": "when this creature becomes the target of a spell",
    "no_islands": "when you control no islands",
    "no_lands": "when you control no lands",
    # at
    "upkeep_self": "at the beginning of your upkeep",
    "upkeep_each": "at the beginning of each upkeep",
    "upkeep_enchanted_controller": "at the beginning of the upkeep of enchanted creature's controller",
    "upkeep_chosen": "at the beginning of the chosen player's upkeep",
    "draw_step_each": "at the beginning of each player's draw step",
    "end_step": "at the beginning of the end step",
    "combat_your_turn": "at the beginning of combat on your turn",
    "combat": "at the beginning of combat",
}

_TABLES = [
    ("whenever", WHENEVER_TRIGGER_PATTERNS),
    ("when", WHEN_TRIGGER_PATTERNS),
    ("at", AT_TRIGGER_PATTERNS),
]


def _examples(kind: str) -> tuple[str, ...]:
    """Every canonical text for *kind* — one entry may hold several."""
    found = EXAMPLE_TEXTS.get(kind)
    if found is None:
        return ()
    return (found,) if isinstance(found, str) else tuple(found)


def test_every_pattern_has_an_example():
    missing = [
        kind
        for _, table in _TABLES
        for kind, _ in table
        if kind not in EXAMPLE_TEXTS
    ]
    assert not missing, f"add canonical examples for: {missing}"


def test_every_example_matches_its_own_pattern():
    """Each trigger kind's canonical example must be matched by at least one of
    that kind's patterns.

    A kind can have several patterns — a narrowed form and its general one, as
    with "casts a *blue* spell" ahead of "casts a spell". Requiring every
    pattern to match the one example would make that impossible; requiring at
    least one keeps the guard's real purpose, which is that no kind is
    unreachable.
    """
    for _, table in _TABLES:
        patterns_by_kind: dict[str, list] = {}
        for kind, pattern in table:
            patterns_by_kind.setdefault(kind, []).append(pattern)
        for kind, patterns in patterns_by_kind.items():
            for example in _examples(kind):
                assert any(re.match(pattern, example) for pattern in patterns), (
                    f"{kind}: canonical example {example!r} matches none of its patterns"
                )


@pytest.mark.parametrize("table_name,table", _TABLES)
def test_no_pattern_shadows_a_later_one(table_name, table):
    """An earlier pattern must never match a later pattern's canonical text —
    otherwise the later (more specific) pattern is dead code.

    Same-kind pairs are exempt, and only those: shadowing is harmful because
    the swallowed text compiles to a *different* condition than it names, and
    two patterns producing one kind produce one answer. Two spellings of one
    kind still have to earn their place — every example is checked against
    every earlier pattern of every *other* kind.
    """
    for i, (early_kind, early_pattern) in enumerate(table):
        for later_kind, _ in table[i + 1:]:
            if later_kind == early_kind:
                continue
            for example in _examples(later_kind):
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
    cards = {c.name: c for c in load_cards(LEA_PATH)}
    program = compile_card_oracle(cards["Hypnotic Specter"])
    kinds = [ta.condition.kind for ta in program.triggered_abilities]
    assert kinds == ["creature_deals_damage_to_opponent"]
