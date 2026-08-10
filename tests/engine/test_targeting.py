"""Guards for cast-time targeting derived from the compiled program.

`engine/legality.py` is a second parser of oracle text, kept only for cards
whose compiled program cannot answer. Two parsers of the same text must agree
forever or the UI offers targets the engine rejects, so `engine/targeting.py`
derives what it can from the program and this file holds the two together.

The differential caught two real bugs while the derivation was being written:
Animate Dead ("Enchant creature card in a graveyard") derived as a battlefield
creature, and every permanent with a targeted activated ability — Royal
Assassin, Pyramids, King Suleiman — derived a cast-time target it does not have.
Widening it from the kind to the whole spec caught a third: Reconstruction.
"""

import re

import pytest

from engine.card_loader import load_catalog
from engine.legality import _classify_cast
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec, derive_cast_target


@pytest.fixture(scope="module")
def supported_cards():
    return [c for c in load_catalog() if compile_card_oracle(c).supported]


def _flags(spec: dict) -> dict:
    """A spec with its unset flags dropped.

    The cascade spells out ``{"copies_spell": False}`` where the derivation
    simply omits the key; every consumer reads these with a truthiness test, so
    the two are the same spec and comparing them raw would report a difference
    that is not one.
    """
    return {key: value for key, value in spec.items() if value not in (False, None)}


# Reconstruction is the one card where the derivation deliberately disagrees,
# because the cascade is wrong about it. "Return target artifact card from your
# graveyard to your hand" classified as a *battlefield* artifact target, so the
# UI offered artifacts in play — and with none in play it offered nothing at
# all, making the spell uncastable while the engine resolved it perfectly when
# driven headlessly. The derivation reads the instruction's own payload
# (`card_type: artifact`), which is the same data its handler resolves from.
_DELIBERATE_DIVERGENCES = {"Reconstruction"}


def test_derivation_never_disagrees_with_the_text_cascade(supported_cards):
    """Wherever the program carries the evidence, its answer must match what
    the text cascade concluded — kind *and* flags. A disagreement is a real
    defect either way: the UI and the engine would be working from different
    ideas of what is targetable."""
    mismatches = []
    for card in supported_cards:
        if card.name in _DELIBERATE_DIVERGENCES:
            continue
        derived = derive_cast_spec(card, compile_card_oracle(card))
        if derived is None:
            continue
        # _classify_cast, not cast_target_spec: the latter now prefers the
        # derivation, so comparing against it would compare it to itself.
        expected = _flags(_classify_cast(card))
        if _flags(derived) != expected:
            mismatches.append((card.name, _flags(derived), expected))

    assert not mismatches, (
        "compiled-program targeting disagrees with legality.py "
        f"(derived, cascade): {mismatches}"
    )


def test_reconstruction_picks_an_artifact_card_out_of_a_graveyard(supported_cards):
    """The bug the full-spec differential found.

    Reconstruction is the artifact sibling of Raise Dead, and the text cascade
    read its "target artifact card" as an artifact *on the battlefield*. With no
    artifact in play the UI enumerated zero legal targets for a spell whose
    actual target — an artifact card in the caster's graveyard — was sitting
    right there.
    """
    from engine import PlayerState
    from tests.helpers import _game

    catalog = {c.name: c for c in supported_cards}
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    game.players[0].graveyard.append(catalog["Ornithopter"])

    spec = game.cast_target_spec(0, catalog["Reconstruction"])

    assert spec["kind"] == "graveyard_creature"
    assert spec["card_type"] == "artifact"
    assert [t["name"] for t in spec["valid_targets"]] == ["Ornithopter"]


def test_a_permanent_has_no_cast_time_target_derived_from_its_abilities(supported_cards):
    """Only a spell picks targets as it is cast. A permanent's instructions
    belong to its abilities, which target on activation — deriving from those
    would make the UI demand a target to cast Royal Assassin."""
    for name in ("Royal Assassin", "Pyramids", "King Suleiman", "Dwarven Demolition Team"):
        card = next(c for c in supported_cards if c.name == name)
        assert derive_cast_spec(card, compile_card_oracle(card)) is None, name


def test_an_aura_on_a_graveyard_card_is_not_a_battlefield_target(supported_cards):
    """Animate Dead reads "Enchant creature card in a graveyard". Deriving
    "creature" from the leading words would offer battlefield creatures for a
    reanimation spell, whose target index means a graveyard position.

    And unlike the spell-side reanimators it is *not* scoped to the caster's own
    graveyard: `_apply_aura_effect` pops the chosen index out of whichever
    graveyard the caster pointed at.
    """
    animate_dead = next(c for c in supported_cards if c.name == "Animate Dead")

    spec = derive_cast_spec(animate_dead, compile_card_oracle(animate_dead))

    assert spec == {"kind": "graveyard_creature"}


@pytest.mark.parametrize(
    "name,expected",
    [
        # Derived from the grammar's lowered `targets` description — evidence the
        # legacy rules never recorded. Lightning Bolt and Earthbind both compile
        # to a bare `deal_damage`; only the target description tells them apart.
        ("Lightning Bolt", {"kind": "any"}),
        ("Disintegrate", {"kind": "any"}),
        ("Fireball", {"kind": "divided"}),
        ("Flight", {"kind": "creature"}),           # Enchant creature
        ("Evil Presence", {"kind": "land"}),        # Enchant land
        ("Steal Artifact", {"kind": "artifact"}),   # Enchant artifact
        ("Shatter", {"kind": "artifact"}),          # type_filter=artifact
        ("Stone Rain", {"kind": "land"}),           # type_filter=land
        ("Disenchant", {"kind": "permanent"}),      # type_filter=artifact_or_enchantment
        # Flags, each from the same place its behaviour comes from.
        ("Animate Wall", {"kind": "creature", "enchant_wall": True}),
        ("Feedback", {"kind": "permanent", "enchant_enchantment": True}),
        ("Word of Command", {"kind": "player", "opponents_only": True}),
        ("Blue Elemental Blast", {"kind": "stack", "stack_color_filter": "R"}),
        ("Counterspell", {"kind": "stack"}),
        ("Fork", {
            "kind": "stack", "copies_spell": True, "stack_instant_sorcery_only": True,
        }),
        ("Clone", {"kind": "creature", "optional": True}),
        ("Copy Artifact", {"kind": "artifact", "optional": True}),
        ("Vesuvan Doppelganger", {"kind": "creature", "optional": True}),
        ("Sacrifice", {"kind": "creature", "own_only": True, "sacrifice_cost": True}),
        ("Regrowth", {
            "kind": "graveyard_creature", "own_graveyard_only": True, "any_card": True,
        }),
        ("Raise Dead", {"kind": "graveyard_creature", "own_graveyard_only": True}),
        ("Reconstruction", {
            "kind": "graveyard_creature", "own_graveyard_only": True, "card_type": "artifact",
        }),
        ("Volcanic Eruption", {
            "kind": "divided", "land_filter": "mountain", "x_equals_targets": True,
        }),
        ("Reverse Damage", {
            "kind": "permanent", "source_of_choice": True, "also_stack": True,
        }),
        # An enters-the-battlefield trigger that targets: this engine picks the
        # target as the permanent is cast, so the prompt has to exist there.
        ("Oubliette", {"kind": "creature"}),
    ],
)
def test_derives_the_expected_spec(supported_cards, name, expected):
    card = next(c for c in supported_cards if c.name == name)

    assert derive_cast_spec(card, compile_card_oracle(card)) == expected


# A cast line that picks a target as the spell resolves. Reminder text is
# stripped first: protection's "(… can't be blocked, **targeted**, dealt damage
# …)" is describing what may not happen to the creature, not something the card
# chooses. Triggered-ability lines are excluded because their target is chosen
# when the trigger goes on the stack (CR 603.3d), not as the permanent is cast —
# Erhnam Djinn's upkeep forestwalk grant is not a cast-time prompt.
_REMINDER = re.compile(r"\([^)]*\)")
_TRIGGER_PREFIX = re.compile(r"^\s*(when|whenever|at the beginning)\b")
_TARGET_WORD = re.compile(r"\btargets?\b")

# Cards that name a target the UI has no picker for, with the reason. An entry
# here is a card the engine resolves without asking, not one whose prompt went
# missing.
_NO_PICKER = {
    # "You own target card in the ante." Nothing enumerates the ante zone, so
    # the handler exchanges the card it finds there rather than one chosen.
    "Darkpact": "the ante zone has no picker",
}


def test_every_card_that_targets_as_it_is_cast_derives_its_own_prompt(supported_cards):
    """The end state of this migration, as a ratchet.

    `legality.py`'s cast cascade exists only for cards whose compiled program
    cannot answer, and that set is now empty: every supported card that names a
    target outside an activated or triggered ability derives its whole spec from
    the program. A card appearing here means a parser change took the evidence
    away, or a newly ingested card carries a shape nothing describes — either
    way it is the shadow parser growing back.
    """
    from engine.legality import _cast_lines

    gaps = []
    for card in supported_cards:
        if card.name in _NO_PICKER:
            continue
        lines = [_REMINDER.sub("", line) for line in _cast_lines(card)]
        if not any(
            _TARGET_WORD.search(line) and not _TRIGGER_PREFIX.match(line) for line in lines
        ):
            continue
        if derive_cast_target(card, compile_card_oracle(card)) in (None, "none"):
            gaps.append(card.name)

    assert gaps == [], f"these cards target but derive no prompt: {gaps}"


def test_the_no_picker_acknowledgements_are_not_stale(supported_cards):
    """An acknowledgement that stops matching a real card is how the next card
    inheriting that name gets a free pass nobody re-checked."""
    by_name = {c.name: c for c in supported_cards}

    for name in _NO_PICKER:
        card = by_name.get(name)
        assert card is not None, f"{name} is acknowledged but not in the pool"
        assert derive_cast_target(card, compile_card_oracle(card)) in (None, "none"), (
            f"{name} derives a prompt now — delete its acknowledgement"
        )


def test_the_grammar_supplies_evidence_the_legacy_rules_never_recorded(supported_cards):
    """`deal_damage` alone cannot say what a spell targets — Lightning Bolt
    ("any target"), Fireball ("divided … among any number of targets") and
    Desert's ability ("target attacking creature") all share the kind. The
    grammar's lowered `targets` description is what distinguishes them, so
    targeting coverage now grows as a by-product of parser migration rather
    than needing its own text rules."""
    bolt = next(c for c in supported_cards if c.name == "Lightning Bolt")
    program = compile_card_oracle(bolt)
    payloads = [i.payload for i in program.instructions if "targets" in i.payload]

    assert payloads, "Lightning Bolt's damage instruction should describe its target"
    assert payloads[0]["targets"]["kind"] == "any"
    assert derive_cast_target(bolt, program) == "any"
