"""Tests for Magic: The Gathering Comprehensive Rules Section 504.

Covers:
  504.1 — The active player draws a card as a turn-based action, and effects
          may add to what that step draws

These pin the *derivation* of the symmetric bonus-draw template from oracle
text (engine/draw_step_modifiers.py), which replaced a name-keyed entry. The
point of the change is that a card the engine has never seen works as long as
it uses the printed template, so these use invented card names — a test naming
Howling Mine could pass against a lookup keyed by "Howling Mine". The real card
is covered by the set suite.
"""

import pytest

from engine.draw_step_modifiers import draw_step_bonus_for


@pytest.mark.cr("504.1")
def test_504_1_symmetric_bonus_draw_is_derived_from_its_template():
    """"At the beginning of each player's draw step, that player draws an
    additional card." — the Howling Mine family, without the untapped clause."""
    bonus = draw_step_bonus_for(
        "At the beginning of each player's draw step, that player draws an additional card."
    )

    assert bonus is not None
    assert (bonus.count, bonus.requires_untapped) == (1, False)


@pytest.mark.cr("504.1")
def test_504_1_untapped_qualifier_is_recognized():
    """Howling Mine's own wording gates the bonus on the source being
    untapped, so tapping it turns the bonus off."""
    bonus = draw_step_bonus_for(
        "At the beginning of each player's draw step, if this artifact is "
        "untapped, that player draws an additional card."
    )

    assert (bonus.count, bonus.requires_untapped) == (1, True)


@pytest.mark.cr("504.1")
def test_504_1_bonus_size_is_read_from_the_text():
    """A card printed with a larger bonus needs no registration — the count
    comes from the wording, not from a per-card table."""
    bonus = draw_step_bonus_for(
        "At the beginning of each player's draw step, that player draws two additional cards."
    )

    assert bonus.count == 2


@pytest.mark.cr("504.1")
def test_504_1_asymmetric_and_unrelated_draw_text_grants_no_bonus():
    """The template is specifically the symmetric "each player" one. A bonus
    that applies to a single player, or text that merely mentions the draw
    step, must not be read as one — the draw step adds this to *every*
    player's draw."""
    for text in (
        "At the beginning of your draw step, you draw an additional card.",
        "At the beginning of each opponent's draw step, that player draws an additional card.",
        "If you would draw a card during your draw step, instead you may skip that draw.",
        "At the beginning of each player's draw step, that player loses 1 life.",
        "Draw a card.",
        "",
    ):
        assert draw_step_bonus_for(text) is None, text
