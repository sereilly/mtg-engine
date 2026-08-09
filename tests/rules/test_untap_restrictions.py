"""Tests for Magic: The Gathering Comprehensive Rules Section 502.

Covers:
  502.3 — Normally all of a player's permanents untap, but effects can keep
          one or more of them from untapping

These pin the *derivation* of untap restrictions from oracle text
(engine/untap_restrictions.py), which replaced a name-keyed table. The point of
that change is that a card the engine has never seen behaves correctly as long
as it uses a printed template, so most of these use invented card names — a
test naming Winter Orb could pass against a lookup table keyed by "Winter Orb".
The real cards are covered by the set suites.
"""

import pytest

from engine.untap_restrictions import untap_restriction_for


def _restriction(text: str):
    return untap_restriction_for(text)


@pytest.mark.cr("502.3")
def test_502_3_skip_the_untap_step_entirely():
    """"Players skip their untap steps." (Stasis)"""
    r = _restriction("Players skip their untap steps.")

    assert r is not None
    assert (r.scope, r.limit) == ("all", 0)


@pytest.mark.cr("502.3")
def test_502_3_per_type_untap_limit():
    """"Players can't untap more than one land during their untap steps."
    (Winter Orb) and the creature-scoped variant (Smoke)."""
    lands = _restriction("Players can't untap more than one land during their untap steps.")
    creatures = _restriction(
        "Players can't untap more than one creature during their untap steps."
    )

    assert (lands.scope, lands.limit) == ("land", 1)
    assert (creatures.scope, creatures.limit) == ("creature", 1)


@pytest.mark.cr("502.3")
def test_502_3_untap_limit_reads_the_printed_count():
    """The count is read from the text, not assumed to be one — a card
    printed with "more than two lands" gets a limit of 2."""
    r = _restriction("Players can't untap more than two lands during their untap steps.")

    assert (r.scope, r.limit) == ("land", 2)


@pytest.mark.cr("502.3")
def test_502_3_power_gated_untap_block():
    """"Creatures with power 3 or greater don't untap during their
    controllers' untap steps." (Meekstone)"""
    r = _restriction(
        "Creatures with power 3 or greater don't untap during their controllers' untap steps."
    )

    assert (r.scope, r.min_power) == ("creature", 3)


@pytest.mark.cr("502.3")
def test_502_3_power_threshold_reads_the_printed_number():
    """A hypothetical Meekstone variant at a different threshold needs no
    registration — the number comes from the text."""
    r = _restriction(
        "Creatures with power 5 or greater don't untap during their controllers' untap steps."
    )

    assert r.min_power == 5


@pytest.mark.cr("502.3")
def test_502_3_color_gated_untap_block():
    """"Blue creatures don't untap during their controllers' untap steps."
    (Magnetic Mountain), and the same template in another color."""
    blue = _restriction("Blue creatures don't untap during their controllers' untap steps.")
    green = _restriction("Green creatures don't untap during their controllers' untap steps.")

    assert (blue.scope, blue.color) == ("creature_color", "U")
    assert (green.scope, green.color) == ("creature_color", "G")


@pytest.mark.cr("502.3")
def test_502_3_as_long_as_untapped_qualifier_applies_to_any_restriction():
    """"As long as this artifact is untapped, ..." (Winter Orb) qualifies the
    restriction that follows it rather than being part of one wording, so it
    composes with the others."""
    orb = _restriction(
        "As long as this artifact is untapped, players can't untap more than "
        "one land during their untap steps."
    )
    composed = _restriction(
        "As long as this enchantment is untapped, creatures with power 2 or "
        "greater don't untap during their controllers' untap steps."
    )

    assert (orb.scope, orb.limit, orb.only_while_source_untapped) == ("land", 1, True)
    assert (composed.min_power, composed.only_while_source_untapped) == (2, True)


@pytest.mark.cr("502.3")
def test_502_3_the_restriction_may_sit_on_any_line_of_the_card():
    """Stasis carries an upkeep clause after its restriction; Magnetic Mountain
    carries one too. The restriction is found wherever it is printed."""
    r = _restriction(
        "Players skip their untap steps.\n"
        "At the beginning of your upkeep, sacrifice this enchantment unless you pay {U}."
    )

    assert (r.scope, r.limit) == ("all", 0)


@pytest.mark.cr("502.3")
def test_502_3_unrelated_untap_text_imposes_no_restriction():
    """Plenty of cards mention untapping without restricting the untap step.
    A loose keyword scan would claim these; the templates must not."""
    for text in (
        "{T}: Add {C}. This artifact doesn't untap during your untap step.",
        "You may choose not to untap this creature during your untap step.",
        "Untap target creature.",
        "Enchanted creature doesn't untap during its controller's untap step.",
        "At the beginning of your upkeep, untap all creatures you control.",
        "",
    ):
        assert _restriction(text) is None, text
