"""Guard: support is derived from the tables that do the work.

Several noncreature behaviours are implemented by text-keyed rule tables that
read a permanent's oracle text directly at the step that needs them —
``untap_restrictions``, ``draw_step_modifiers``, ``cost_modifiers``,
``enter_effects``. They need no instruction to *work*.

They were nonetheless absent from the support gate, which listed the same
behaviours as whitelist literals with the table's parameters baked in:
"creatures with power **3** or greater don't untap", "players can't untap more
than **one** creature". So a card printed "power 4 or greater" was enforced
correctly by the table and reported **unsupported** — the false-negative half
of the gate/dispatch split that produced the combat-restriction and
characteristic-defining bugs in their supported-but-wrong form.

The gate now asks the tables. These tests use parameter values no card in the
pool prints, because a test built from Meekstone and Smoke passes against the
version that hardcoded exactly their numbers.
"""

import dataclasses

import pytest

from engine.card_loader import load_catalog
from engine.oracle import compile_card_oracle
from engine.replacements import REPLACEMENT_LINES, replacement_claims_line
from engine.untap_restrictions import untap_restriction_for


@pytest.fixture(scope="module")
def artifact_card():
    return {c.name: c for c in load_catalog()}["Meekstone"]


def _probe(artifact_card, text):
    return compile_card_oracle(
        dataclasses.replace(artifact_card, name="Probe Artifact", oracle_text=text)
    )


@pytest.mark.parametrize(
    "text",
    [
        # The threshold is data to the table; it was a literal to the gate.
        "Creatures with power 1 or greater don't untap during their controllers' untap steps.",
        "Creatures with power 4 or greater don't untap during their controllers' untap steps.",
        "Creatures with power 9 or greater don't untap during their controllers' untap steps.",
        # So is the count, and the permanent type it counts.
        "Players can't untap more than two creatures during their untap steps.",
        "Players can't untap more than one land during their untap steps.",
        "Players can't untap more than three lands during their untap steps.",
    ],
)
def test_a_parameterized_untap_restriction_is_supported(artifact_card, text):
    """Implemented-but-unsupported is still a bug: the card would be excluded
    from decks and coverage reports while the engine enforced it correctly."""
    assert untap_restriction_for(text) is not None, "table should claim it"
    assert _probe(artifact_card, text).supported, text


@pytest.mark.parametrize(
    "text",
    [
        "Blue spells cost {2} more to cast.",
        "Green spells cost {1} more to cast.",
        "Black spells cost {4} more to cast.",
    ],
)
def test_a_parameterized_cost_tax_is_supported(artifact_card, text):
    """Gloom's literal named white and {3}; the table has always taken both as
    parameters."""
    assert _probe(artifact_card, text).supported, text


def test_the_derived_marker_names_the_table_that_claims_it(artifact_card):
    """The marker records *which* table carries the behaviour, so a card whose
    support comes from a table can be traced to it without re-reading text."""
    program = _probe(
        artifact_card,
        "Creatures with power 4 or greater don't untap during their controllers' untap steps.",
    )
    derived = [i for i in program.instructions if i.kind == "derived_static_rule"]
    assert [i.value for i in derived] == ["untap_restrictions"]


def test_real_cards_keep_their_support(artifact_card):
    catalog = {c.name: c for c in load_catalog()}
    expected = {
        "Meekstone": "untap_restrictions",
        "Smoke": "untap_restrictions",
        "Winter Orb": "untap_restrictions",
        "Howling Mine": "draw_step_modifiers",
        "Gloom": "cost_modifiers",
        # One claim for the whole entry-state registry: naming a subset of
        # engine/enter_effects.py here would be the same partial-list mistake
        # the derivation tables exist to remove.
        "Library of Leng": "enter_effects",
        "Sunglasses of Urza": "enter_effects",
        "Copy Artifact": "enter_effects",
    }
    for name, table in expected.items():
        program = compile_card_oracle(catalog[name])
        assert program.supported, name
        values = [i.value for i in program.instructions if i.kind == "derived_static_rule"]
        assert table in values, f"{name}: {values}"


def test_text_no_table_claims_is_still_unsupported(artifact_card):
    """The gate must not have become permissive. A restriction none of the
    tables understands stays unsupported."""
    assert not _probe(
        artifact_card,
        "Creatures with three heads don't untap during their controllers' untap steps.",
    ).supported


def test_no_permanent_is_supported_by_a_whitelist_substring_alone():
    """The ratchet that keeps the whitelist from growing back.

    ``spell_pattern`` is a marker recording that a substring matched. It
    carries no behaviour, so a permanent whose *every* instruction is one — and
    which has no ability either — is supported on the strength of a string
    comparison and nothing else. That is how Shahrazad shipped as a no-op, and
    how 44 Auras were classified without anyone checking their effects.

    Instants and sorceries are covered by test_no_hollow_support.py (which
    requires a registered handler); Auras by tests/rules/test_aura_support.py.
    This is the remaining case: artifacts and non-Aura enchantments.

    A new card failing here needs its behaviour claimed by the code that
    implements it — a derivation table, a parse rule producing a real
    instruction, or an entry-state phrase — not a new whitelist literal.
    """
    from engine.card_loader import load_catalog
    from engine.oracle import compile_card_oracle

    hollow = []
    for card in load_catalog():
        type_line = card.type_line.lower()
        # "equipment" beside "aura", and for the same reason: an Equipment's
        # "Equipped creature gets +1/+1" is read off its own text by
        # `auras.aura_static_pt_grant` and applied through the CR 613 layer 7c
        # bridge, so it leaves no instruction here while working perfectly. The
        # scan is about permanents whose behaviour is a *string comparison*, and
        # a permanent whose behaviour is a derivation table is not one — which is
        # exactly what `test_no_hollow_support.py`'s control test says about
        # these same two cards.
        if any(
            t in type_line
            for t in ("instant", "sorcery", "creature", "land", "aura", "equipment")
        ):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if any(i.kind != "spell_pattern" for i in program.instructions):
            continue
        if any(a.supported for a in program.activated_abilities) or program.triggered_abilities:
            continue
        hollow.append((card.name, [f"{i.kind}:{i.value}" for i in program.instructions]))

    assert not hollow, (
        "permanent(s) supported only by a whitelist substring, with no "
        "instruction, ability or rule table behind them:\n"
        + "\n".join(f"  {name}: {kinds}" for name, kinds in sorted(hollow))
    )


# ---------------------------------------------------------------------------
# The seventh table (CR 614)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase,tail", [(p, t) for p, t in REPLACEMENT_LINES], ids=lambda v: v[:28]
)
def test_a_permanent_whose_only_ability_is_a_replacement_is_supported(
    artifact_card, phrase, tail
):
    """The gate asked six text-keyed tables and not the CR 614 one.

    An interceptor self-selects off the card's own text at the event it
    modifies, so like the other six it needs no instruction to work — and unlike
    them it was not a claim, so a permanent whose *only* ability is a
    replacement produced nothing, claimed nothing, and reported unsupported
    however well the interceptor ran. Every such card in the pool happened to
    print a second readable line (Lich, Ali from Cairo, Library of Leng,
    Conclave Mentor), which is why the gap waited for Fiery Emancipation.

    Parametrized over the registry rather than over a list of cards: an
    interceptor added without a claim behind it fails here on the day it is
    written, not on the day a card prints it alone.
    """
    program = _probe(artifact_card, (phrase + tail).capitalize() + ".")

    assert program.supported, program.reason
    assert any(
        i.kind == "derived_static_rule" and i.value == "replacements"
        for i in program.instructions
    ), [f"{i.kind}:{i.value}" for i in program.instructions]


def test_the_support_gate_and_the_grammar_read_one_table():
    """Both readers of ``REPLACEMENT_LINES`` ask the implementer.

    The phrases used to live in ``engine/grammar/registries.py``, next to the
    parse claim and away from the interceptors — which was survivable while
    there was one reader. A second copy for the support gate would have been
    free to drift, and a drifted copy claims a line nothing implements.
    """
    from engine.grammar.registries import registry_for_line

    for phrase, tail in REPLACEMENT_LINES:
        line = phrase + tail
        assert replacement_claims_line(line), line
        assert registry_for_line(line) == "replacements", line
