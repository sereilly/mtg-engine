"""Guards for cast-time targeting derived from the compiled program.

`engine/legality.py` is a second parser of oracle text, kept only because the
compiled program does not yet carry target specs for every card. Two parsers of
the same text must agree forever or the UI offers targets the engine rejects,
so `engine/targeting.py` derives what it can from the program and this file
holds the two together.

The differential caught two real bugs while the derivation was being written:
Animate Dead ("Enchant creature card in a graveyard") derived as a battlefield
creature, and every permanent with a targeted activated ability — Royal
Assassin, Pyramids, King Suleiman — derived a cast-time target it does not have.
"""

import pytest

from engine.card_loader import load_catalog
from engine.legality import _classify_cast
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_target


@pytest.fixture(scope="module")
def supported_cards():
    return [c for c in load_catalog() if compile_card_oracle(c).supported]


def test_derivation_never_disagrees_with_the_text_cascade(supported_cards):
    """Wherever the program carries the evidence, its answer must match what
    the text cascade concluded. A disagreement is a real defect either way: the
    UI and the engine would be working from different ideas of what is
    targetable."""
    mismatches = []
    for card in supported_cards:
        derived = derive_cast_target(card, compile_card_oracle(card))
        if derived is None:
            continue
        # _classify_cast, not cast_target_kind: the latter now prefers the
        # derivation, so comparing against it would compare it to itself.
        expected = _classify_cast(card)["kind"]
        if derived != expected:
            mismatches.append((card.name, derived, expected))

    assert not mismatches, (
        "compiled-program targeting disagrees with legality.py "
        f"(derived, cascade): {mismatches}"
    )


def test_a_permanent_has_no_cast_time_target_derived_from_its_abilities(supported_cards):
    """Only a spell picks targets as it is cast. A permanent's instructions
    belong to its abilities, which target on activation — deriving from those
    would make the UI demand a target to cast Royal Assassin."""
    for name in ("Royal Assassin", "Pyramids", "King Suleiman", "Dwarven Demolition Team"):
        card = next(c for c in supported_cards if c.name == name)
        assert derive_cast_target(card, compile_card_oracle(card)) is None, name


def test_an_aura_on_a_graveyard_card_is_not_a_battlefield_target(supported_cards):
    """Animate Dead reads "Enchant creature card in a graveyard". Deriving
    "creature" from the leading words would offer battlefield creatures for a
    reanimation spell, whose target index means a graveyard position."""
    animate_dead = next(c for c in supported_cards if c.name == "Animate Dead")

    assert derive_cast_target(animate_dead, compile_card_oracle(animate_dead)) is None


@pytest.mark.parametrize(
    "name,expected",
    [
        # Derived from the grammar's lowered `targets` description — evidence the
        # legacy rules never recorded. Lightning Bolt and Earthbind both compile
        # to a bare `deal_damage`; only the target description tells them apart.
        ("Lightning Bolt", "any"),
        ("Disintegrate", "any"),
        ("Flight", "creature"),           # Enchant creature
        ("Evil Presence", "land"),        # Enchant land
        ("Steal Artifact", "artifact"),   # Enchant artifact
        ("Shatter", "artifact"),          # type_filter=artifact
        ("Stone Rain", "land"),           # type_filter=land
        ("Disenchant", "permanent"),      # type_filter=artifact_or_enchantment
    ],
)
def test_derives_the_expected_kind(supported_cards, name, expected):
    card = next(c for c in supported_cards if c.name == name)

    assert derive_cast_target(card, compile_card_oracle(card)) == expected


def test_shadow_parser_reliance_does_not_grow(supported_cards):
    """A ratchet on the shadow parser. `legality.py` exists only for cards whose
    compiled program cannot yet answer; that set must shrink as lowering starts
    emitting target specs, never grow.

    Raise the floor when it improves — a card that stops being derivable means
    a parser change quietly took evidence away.
    """
    derivable = sum(
        1 for c in supported_cards if derive_cast_target(c, compile_card_oracle(c)) is not None
    )

    assert derivable >= 76, (
        f"only {derivable} cards derive their cast target from the compiled "
        "program (was 76) — a parser change removed targeting evidence"
    )


def test_the_grammar_supplies_evidence_the_legacy_rules_never_recorded(supported_cards):
    """`deal_damage` alone cannot say what a spell targets — Lightning Bolt
    ("any target") and Desert's ability ("target attacking creature") share the
    kind. The grammar's lowered `targets` description is what distinguishes
    them, so targeting coverage now grows as a by-product of parser migration
    rather than needing its own text rules."""
    bolt = next(c for c in supported_cards if c.name == "Lightning Bolt")
    program = compile_card_oracle(bolt)
    payloads = [i.payload for i in program.instructions if "targets" in i.payload]

    assert payloads, "Lightning Bolt's damage instruction should describe its target"
    assert payloads[0]["targets"]["kind"] == "any"
    assert derive_cast_target(bolt, program) == "any"
