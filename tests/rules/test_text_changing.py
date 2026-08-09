"""Tests for Magic: The Gathering Comprehensive Rules Section 612/613.

Covers:
  612.1  — text-changing effects
  613.1c — layer 3: text-changing effects are applied

Sleight of Mind replaces a colour word in a permanent's rules text. That has to
happen *before* anything reads the text, which is what layer 3 means. It used to
be applied at each reader that had been taught about it — so protection honoured
the remap while Magnetic Mountain went on blocking blue creatures and Gloom went
on taxing white spells, their text notwithstanding.

``Permanent.effective_card`` applies it once. A text-keyed table (untap
restrictions, cost modifiers, draw-step bonuses) never learns that text can
change.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.cost_modifiers import cost_modifiers_for
from engine.models import Permanent
from engine.untap_restrictions import untap_restriction_for


@pytest.fixture(scope="module")
def catalog():
    return {c.name: c for c in load_catalog()}


def _board(catalog, *names):
    perms = [Permanent(card=catalog[n]) for n in names]
    player = PlayerState(name="P1", battlefield=perms)
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, perms


@pytest.mark.cr("613.1c")
def test_613_1c_a_remapped_colour_word_changes_which_creatures_dont_untap(catalog):
    """Magnetic Mountain: "Blue creatures don't untap…". Rewritten to red, it
    should hold red creatures down and release blue ones."""
    game, (mountain,) = _board(catalog, "Magnetic Mountain")
    assert untap_restriction_for(mountain.effective_card.oracle_text).color == "U"

    mountain.metadata["color_word_remap"] = {"U": "R"}

    assert untap_restriction_for(mountain.effective_card.oracle_text).color == "R"


@pytest.mark.cr("613.1c")
def test_613_1c_a_remapped_colour_word_changes_which_spells_are_taxed(catalog):
    """Gloom taxes white spells. Rewritten to red, it taxes red ones."""
    game, (gloom,) = _board(catalog, "Gloom")
    assert {m.colour for m in cost_modifiers_for(gloom.effective_card.oracle_text)} == {"W"}

    gloom.metadata["color_word_remap"] = {"W": "R"}

    assert {m.colour for m in cost_modifiers_for(gloom.effective_card.oracle_text)} == {"R"}


@pytest.mark.cr("613.1c")
def test_613_1c_protection_still_honours_the_remap(catalog):
    """The one reader that already applied it, so the seam did not lose it."""
    game, (knight,) = _board(catalog, "Black Knight")
    assert sorted(game._protection_colors(knight)) == ["W"]

    knight.metadata["color_word_remap"] = {"W": "R"}

    assert sorted(game._protection_colors(knight)) == ["R"]


@pytest.mark.cr("612.1")
def test_612_1_a_swap_does_not_collapse_both_words_into_one(catalog):
    """Replacing black with red *and* red with black is a swap. Applying the
    substitutions one after another would turn every black into red and then
    every red — including the ones just written — back into black."""
    import dataclasses

    from engine.models import _with_color_words_remapped

    card = dataclasses.replace(
        catalog["Black Knight"],
        oracle_text="Black creatures get +1/+1. White creatures get -1/-1.",
    )
    swapped = _with_color_words_remapped(card, {"B": "W", "W": "B"})

    assert swapped.oracle_text == "White creatures get +1/+1. Black creatures get -1/-1."


@pytest.mark.cr("612.1")
def test_612_1_only_whole_words_are_replaced(catalog):
    """A colour word inside a longer word is not a colour word. Without a word
    boundary "red" rewrites the "red" in "required" and "considered"."""
    from engine.models import _with_color_words_remapped

    import dataclasses

    card = dataclasses.replace(
        catalog["Black Knight"], oracle_text="Blackened redwood is required."
    )
    remapped = _with_color_words_remapped(card, {"B": "R", "R": "G"})
    assert remapped.oracle_text == "Blackened redwood is required."


@pytest.mark.cr("613.1c")
def test_613_1c_no_remap_returns_the_card_unchanged(catalog):
    """The common path must not allocate or copy: nearly every rules query
    reads effective_card."""
    game, (knight,) = _board(catalog, "Black Knight")
    assert knight.effective_card is knight.card
