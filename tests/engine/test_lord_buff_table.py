"""``engine/lord_buffs.py`` — the lord/anthem derivation table.

What this file exists to prove is that the table is a **template**, not a list
of the cards that happen to be in the pool. The bug this family shipped with
was the other kind: the gate admitted every line starting ``"other "`` and the
consumer re-read the sentence with a regex that knew about colour and
controller only, so what a line meant depended on which of the two you asked.

Every test below therefore uses an **invented** card wherever the point is that
the template generalizes. A test naming only Goblin King would have passed
against the broken version — that is precisely how the same defect survived in
``combat_restrictions.py`` until a card printed with a different land type
turned up.
"""

from __future__ import annotations

import pytest

from engine.lord_buffs import (
    CONDITIONS,
    GRANTED_ACTIVATED_ABILITIES,
    LORD_BUFF_KIND,
    QUALIFIER_FIELDS,
    LordBuff,
    LordBuffFilter,
    grantable_keywords,
    lord_buff_for,
    lord_buff_from_payload,
    lord_buff_payload,
)
from engine.models import CardDefinition
from engine.oracle import compile_card_oracle, normalize_creature_line


def _lord(oracle_text: str, *, type_line: str = "Creature — Goblin") -> CardDefinition:
    """An invented card with the given rules text."""
    return CardDefinition(
        name="Nonexistent Card", mana_cost="{1}{R}", cmc=2.0, type_line=type_line,
        oracle_text=oracle_text, colors=("R",), color_identity=("R",),
        keywords=(), produced_mana=(),
        raw={"name": "Nonexistent Card", "type_line": type_line,
             "power": "2", "toughness": "2"},
    )


def _derive(line: str) -> LordBuff | None:
    return lord_buff_for(normalize_creature_line(line))


# ---------------------------------------------------------------------------
# The template generalizes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,expected",
    [
        # Every parameter moved off the printed cards one at a time. None of
        # these sentences is printed on any card in the pool.
        (
            "Other Elves get +2/+3 and have forestwalk.",
            LordBuff(
                LordBuffFilter(subtypes=("elf",), other_than_source=True),
                2, 3, ("forestwalk",),
            ),
        ),
        (
            "Green creatures get +3/+3.",
            LordBuff(LordBuffFilter(colors=("G",)), 3, 3),
        ),
        (
            "Attacking creatures you control get +4/+0.",
            LordBuff(LordBuffFilter(controller="you", qualifiers=("attacking",)), 4, 0),
        ),
        (
            "Untapped creatures you control get +0/+5.",
            LordBuff(LordBuffFilter(controller="you", qualifiers=("untapped",)), 0, 5),
        ),
        (
            "Blocking creatures you control get +0/+1.",
            LordBuff(LordBuffFilter(controller="you", qualifiers=("blocking",)), 0, 1),
        ),
        (
            "Tapped creatures get +1/+1.",
            LordBuff(LordBuffFilter(qualifiers=("tapped",)), 1, 1),
        ),
        (
            "Creatures you control get +1/+1.",
            LordBuff(LordBuffFilter(controller="you"), 1, 1),
        ),
        (
            "Other Wall creatures have flying.",
            LordBuff(LordBuffFilter(subtypes=("wall",), other_than_source=True), 0, 0,
                     ("flying",)),
        ),
        # The signs are read as printed (Kaervek, the Spiteful's "-1/-1") —
        # a debuff is the same layer-7c contribution with a negative delta.
        (
            "Other Goblins get -2/-1.",
            LordBuff(
                LordBuffFilter(subtypes=("goblin",), other_than_source=True), -2, -1,
            ),
        ),
    ],
)
def test_an_invented_card_with_the_template_derives(line, expected):
    assert _derive(line) == expected


def test_the_subtype_is_data_however_it_is_pluralised():
    """"Goblins", "Merfolk" and "Zombie creatures" are three spellings of the
    same slot. The catalog in data/vocabulary/ stores singulars, so nothing here
    may assume a trailing "s" — Plains-style invariants are why the old code's
    ``subtype[:-1]`` produced subtypes no card has."""
    assert _derive("Other Goblins get +1/+1.").filter.subtypes == ("goblin",)
    assert _derive("Other Merfolk get +1/+1.").filter.subtypes == ("merfolk",)
    assert _derive("Other Zombie creatures get +1/+1.").filter.subtypes == ("zombie",)
    # A type that is not a creature type at all is not a subtype slot.
    assert _derive("Other Mountains get +1/+1.") is None


def test_other_is_derived_rather_than_assumed():
    """CR 613 applies a static ability to its own source unless the card
    excludes it, so the two readings must be distinguishable."""
    assert _derive("Other Goblins get +1/+1.").filter.other_than_source is True
    assert _derive("Goblins get +1/+1.").filter.other_than_source is False


def test_controller_scope_is_derived_rather_than_assumed():
    assert _derive("Black creatures get +1/+1.").filter.controller is None
    assert _derive("Black creatures you control get +1/+1.").filter.controller == "you"


# ---------------------------------------------------------------------------
# CR 611.2c — the spell reading of the same sentence is a different effect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Attacking creatures get +2/+0 until end of turn.",
        "Blocking creatures get +0/+3 until end of turn.",
        "Creatures you control get +1/+1 until end of combat.",
    ],
)
def test_a_clause_carrying_a_duration_is_not_a_static_ability(line):
    """A one-shot buff locks its set in at resolution (CR 611.2c) and keeps
    ``buff_creatures_global``; a static ability is re-derived on every recompute
    (CR 611.3a). Duration is the whole distinction, and this table must not
    claim the spell side of it — Army of Allah lowered here would buff whatever
    happened to be attacking whenever the board was next recalculated."""
    assert _derive(line) is None


def test_the_spells_keep_their_own_instruction_kind(catalog_by_name):
    for name in ("Army of Allah", "Piety"):
        kinds = [i.kind for i in compile_card_oracle(catalog_by_name[name]).instructions]
        assert "buff_creatures_global" in kinds, name
        assert LORD_BUFF_KIND not in kinds, name


# ---------------------------------------------------------------------------
# Refusals name the missing code instead of widening
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,why",
    [
        ("Other Goblins glimmer uncontrollably.", "no effect the table models"),
        ("Other Goblins get +1/+1 and have shadow.", "layer 6 carries no shadow"),
        ('Other Zombies have "{5}: Regenerate this permanent."',
         "nothing charges {5} for the granted ability"),
        ("Other Goblins get +1/+1 as long as you control a Mountain.",
         "an unmodelled condition would become permanent if dropped"),
        # "Creatures **with** flying get +1/+1" stood here until Serra Aviary
        # printed it and ``LordBuffFilter.with_keywords`` learned to carry it,
        # and "**without** flying" stood beside it until Chaosphere printed
        # that and ``without_keywords`` did the same. What is left of the
        # question is the sharper row: a word the consumer cannot *ask* about.
        # "Protection" is a category, not an ability ``has_keyword`` answers, so
        # a filter carrying it would match nothing and the anthem would reach
        # nobody -- which is the direction a table must refuse rather than
        # derive.
        ("Creatures with protection get +1/+1.",
         "has_keyword cannot answer a category word"),
        ("Creatures without protection get +1/+1.",
         "the negation cannot answer a category word either"),
    ],
)
def test_an_unimplemented_shape_refuses_rather_than_partly_matching(line, why):
    assert _derive(line) is None, why


def test_a_keyword_restriction_on_the_buffed_set_is_carried():
    """Serra Aviary's "Creatures with flying get +1/+1", the positive half of
    the two rows above. Asserted beside them so the pair reads as a line the
    table draws rather than as a table that reads nothing."""
    buff = _derive("Creatures with flying get +1/+1.")

    assert buff is not None
    assert buff.filter.with_keywords == ("flying",)
    assert (buff.power, buff.toughness) == (1, 1)


def test_a_granted_protection_rides_its_own_channel_not_layer_6():
    """It refused until round 105, with the reason "protection is a channel of
    its own, not layer 6" — which was true and is still the reason it is a
    *separate field* rather than a keyword. What changed is that the channel now
    reads a lord's grant: derived on every recompute, exactly as an Aura's is,
    because a stamped grant would be one nothing clears."""
    buff = _derive("Other Cats you control get +1/+1 and have protection from Dogs.")

    assert buff is not None
    assert buff.protection_from == ("dogs",)
    assert buff.keywords == (), "protection is not among the layer-6 words"
    assert (buff.power, buff.toughness) == (1, 1)


def test_an_unsupported_shape_makes_the_whole_card_unsupported():
    """Failing loud is the contract. The gate asks this table, so a line it
    cannot claim can no longer be admitted by a prefix and then do nothing."""
    assert not compile_card_oracle(_lord("Other Goblins glimmer uncontrollably.")).supported
    assert compile_card_oracle(_lord("Other Goblins get +1/+1.")).supported


# ---------------------------------------------------------------------------
# The table and the code that carries it out are one list, not two
# ---------------------------------------------------------------------------


def test_every_qualifier_has_a_predicate_that_evaluates_it():
    """A qualifier the table can derive with nothing to check it would be a buff
    applied unconditionally — the failure this whole family had. Asserted at
    import in layer_bridge as well; stated here so the reason is findable."""
    from engine.layer_bridge import _QUALIFIER_HOLDS

    assert set(_QUALIFIER_HOLDS) == set(QUALIFIER_FIELDS)


def test_every_condition_has_a_predicate_that_evaluates_it():
    from engine.mixins.permanent_state import PermanentStateMixin

    for condition in CONDITIONS.values():
        method = PermanentStateMixin._LORD_BUFF_CONDITIONS[condition]
        assert callable(getattr(PermanentStateMixin, method))


def test_every_granted_ability_flag_is_read_by_the_activation_path():
    """The flag names an ability someone can actually activate. An entry here
    with no reader would grant an ability that does nothing."""
    import inspect

    from engine.mixins.stack import activation

    source = inspect.getsource(activation)
    for flag in GRANTED_ACTIVATED_ABILITIES.values():
        assert flag in source, flag


def test_grantable_keywords_are_all_ones_layer_6_resolves():
    from engine.grammar.vocabulary import IMPLEMENTED_KEYWORDS

    assert grantable_keywords() <= IMPLEMENTED_KEYWORDS
    # Category words, not abilities: claiming them would say layer 6 carries
    # something it does not.
    assert "protection" not in grantable_keywords()
    assert "landwalk" not in grantable_keywords()


# ---------------------------------------------------------------------------
# Payload round trip — the instruction is the only thing the consumer sees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Other Goblins get +1/+1 and have mountainwalk.",
        "Black creatures get +1/+1.",
        "Attacking creatures you control get +1/+0.",
        "Untapped creatures you control get +0/+2.",
        'Other Zombies have "{B}: Regenerate this permanent."',
    ],
)
def test_the_payload_round_trips(line):
    buff = _derive(line)
    assert lord_buff_from_payload(lord_buff_payload(buff)) == buff


# ---------------------------------------------------------------------------
# The pool, swept by shape rather than by name
# ---------------------------------------------------------------------------


def test_every_lord_shaped_line_in_the_pool_derives(catalog):
    """Swept by shape, not from a list of the cards someone remembered. A card
    ingested later whose text matches the shape and which **nothing** reads
    shows up here.

    "Nothing reads it" is the invariant, and it is not the same as "the table
    does not claim it" — which is what this guard used to assert. The grammar
    runs *before* the derivation tables (`tests/engine/test_grammar_derived_lines.py`
    holds that order), so a production claiming a lord-shaped sentence is
    exactly the case where the table is *supposed* to stay silent, and reading
    the table alone reports a working card as a gap.

    Fallen Empires collected on that at its promotion gate. Tidal Influence
    prints "As long as there are exactly three tide counters on this
    enchantment, all blue creatures get +2/+0" — a conditioned anthem the
    grammar reads into a `lord_buff` with a condition, colour-correctly and
    with the sibling `-2/-0` line working at one counter. The table does not
    claim it and must not: the production consumed the line first. So the
    question is asked of the compiled program, which is where both readers'
    answers land.
    """
    unclaimed: list[str] = []
    for card in catalog:
        lord_shaped = []
        for raw in (card.oracle_text or "").splitlines():
            normalized = normalize_creature_line(raw)
            if " get +" not in normalized and " have " not in normalized:
                continue
            if not (normalized.startswith("other ") or " creatures get +" in normalized):
                continue
            if any(word in normalized for word in ("until end of", "this turn")):
                continue  # the spell reading; CR 611.2c
            if lord_buff_for(normalized) is not None:
                continue
            lord_shaped.append(normalized)
        if not lord_shaped:
            continue
        # The table declined every line above. Ask the other reader: a
        # production that consumed the sentence leaves a `lord_buff`
        # instruction behind, and that is the whole of what the table would
        # have produced.
        program = compile_card_oracle(card)
        buffs = sum(
            1 for instruction in program.instructions
            if instruction.kind == LORD_BUFF_KIND
        )
        if buffs >= len(lord_shaped):
            continue
        unclaimed.extend(f"{card.name}: {line}" for line in lord_shaped)
    assert not unclaimed, (
        "lord-shaped line(s) neither the derivation table nor a grammar "
        "production claims:\n  " + "\n  ".join(sorted(set(unclaimed)))
    )
