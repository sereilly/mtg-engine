"""Tests for Magic: The Gathering Comprehensive Rules Section 612/613.

Covers:
  612.1  — text-changing effects
  612.2  — only words used in the right way; never a card name
  612.3  — a granted ability is not part of the object's text
  613.1c — layer 3: text-changing effects are applied
  613.7  — and in timestamp order

Sleight of Mind replaces a colour word in a permanent's rules text; Magical Hack
replaces a basic land type wherever it is written. That has to happen *before*
anything reads the text, which is what layer 3 means. It used to be applied at
each reader that had been taught about it — so protection honoured the remap
while Magnetic Mountain went on blocking blue creatures and Gloom went on taxing
white spells, their text notwithstanding.

``Permanent.effective_card`` applies them once, in the order they were recorded
(``engine/text_changes.py``). A text-keyed table (untap restrictions, cost
modifiers, draw-step bonuses) never learns that text can change.
"""

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.cost_modifiers import cost_modifiers_for
from engine.models import Permanent
from engine.text_changes import (
    change_color_word,
    change_land_word,
    changed_words,
    one_pass,
    text_changes,
)
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
    assert untap_restriction_for(
        mountain.effective_card.oracle_text
    ).blocked["color_filter"] == "U"

    change_color_word(mountain, "U", "R")

    assert untap_restriction_for(
        mountain.effective_card.oracle_text
    ).blocked["color_filter"] == "R"


@pytest.mark.cr("613.1c")
def test_613_1c_a_remapped_colour_word_changes_which_spells_are_taxed(catalog):
    """Gloom taxes white spells. Rewritten to red, it taxes red ones."""
    game, (gloom,) = _board(catalog, "Gloom")
    assert {m.colour for m in cost_modifiers_for(gloom.effective_card.oracle_text)} == {"W"}

    change_color_word(gloom, "W", "R")

    assert {m.colour for m in cost_modifiers_for(gloom.effective_card.oracle_text)} == {"R"}


@pytest.mark.cr("613.1c")
def test_613_1c_protection_still_honours_the_remap(catalog):
    """The one reader that already applied it, so the seam did not lose it."""
    game, (knight,) = _board(catalog, "Black Knight")
    assert sorted(game._protection_colors(knight)) == ["W"]

    change_color_word(knight, "W", "R")

    assert sorted(game._protection_colors(knight)) == ["R"]


@pytest.mark.cr("612.1")
def test_612_1_one_effects_substitutions_are_simultaneous():
    """**A swap must not collapse.** Within a single text change the
    replacements happen at once. Applying them one after another would turn
    every black into red and then every red — including the ones just written —
    back into black, leaving one colour where there were two. ``one_pass`` is
    one pass over one alternation, which is what prevents it, and everything in
    this module is built on it: the sequencing test below can only mean anything
    if the step it sequences is simultaneous.
    """
    text = "Black creatures get +1/+1. Red creatures get -1/-1."

    assert one_pass(text, {"black": "red", "red": "black"}) == (
        "Red creatures get +1/+1. Black creatures get -1/-1."
    )

    # And the same guarantee for the several forms one land-type change names:
    # "swampwalk" must not be reached by the bare "swamp" rule, and vice versa.
    assert one_pass(
        "Swampwalk. All Swamps are 1/1. Return target Swamp.",
        {"swampwalk": "islandwalk", "swamps": "islands", "swamp": "island"},
    ) == "Islandwalk. All Islands are 1/1. Return target Island."


@pytest.mark.cr("613.7")
def test_613_7_two_text_changes_apply_in_timestamp_order(catalog):
    """**Text changes do not commute, and the storage has to know it.**

    Sleight of Mind is one substitution, so black -> red and red -> black are
    two *separate* effects. CR 613.7 applies them oldest first, each to the text
    the previous one produced: black becomes red, and that red then becomes
    black again — both words end up black. Recorded in the other order they both
    end up red.

    Merging the two into one substitution table (what a stamped
    ``{"B": "R", "R": "B"}`` map is) produces a third answer neither order
    gives: a swap. That is the bug this channel exists to make impossible.
    """
    text = dataclasses.replace(
        catalog["Black Knight"],
        oracle_text="Black creatures get +1/+1. Red creatures get -1/-1.",
    )

    forward = Permanent(card=text)
    change_color_word(forward, "B", "R")
    change_color_word(forward, "R", "B")
    assert forward.effective_card.oracle_text == (
        "Black creatures get +1/+1. Black creatures get -1/-1."
    )

    backward = Permanent(card=text)
    change_color_word(backward, "R", "B")
    change_color_word(backward, "B", "R")
    assert backward.effective_card.oracle_text == (
        "Red creatures get +1/+1. Red creatures get -1/-1."
    )

    # And the timestamps are what ordered them, not the list order.
    stamps = [c["timestamp"] for c in text_changes(forward)]
    assert stamps == sorted(stamps) and len(set(stamps)) == 2


@pytest.mark.cr("613.7")
def test_613_7_a_chain_of_changes_composes_for_the_ui(catalog):
    """black -> red then red -> green means black now reads green, and so does
    red. The UI payload is derived from the fold rather than from the entries,
    so it reports what the words *became* and not the two steps that got there.
    """
    knight = Permanent(card=catalog["Black Knight"])
    change_color_word(knight, "B", "R")
    change_color_word(knight, "R", "G")

    assert changed_words(knight) == [
        {"from": "black", "to": "green"},
        {"from": "red", "to": "green"},
    ]


@pytest.mark.cr("612.1")
def test_612_1_only_whole_words_are_replaced(catalog):
    """A colour word inside a longer word is not a colour word. Without a word
    boundary "red" rewrites the "red" in "required" and "considered"."""
    card = dataclasses.replace(
        catalog["Black Knight"], oracle_text="Blackened redwood is required."
    )
    perm = Permanent(card=card)
    change_color_word(perm, "B", "R")
    change_color_word(perm, "R", "G")

    assert perm.effective_card.oracle_text == "Blackened redwood is required."


@pytest.mark.cr("612.1")
def test_612_1_a_land_word_change_reaches_every_form_it_is_written_in(catalog):
    """"Replacing all instances" means the bare word, the plural and the
    landwalk compound. ``\\b`` does not reach inside "swampwalk" — there is no
    boundary after "swamp" — so the compound has to be named, longest first."""
    card = dataclasses.replace(
        catalog["Bog Wraith"],
        type_line="Creature — Wraith",
        oracle_text="Swampwalk. All Swamps are 1/1. Return target Swamp.",
        keywords=("Swampwalk",),
    )
    perm = Permanent(card=card)
    change_land_word(perm, "swamp", "island")

    effective = perm.effective_card
    assert effective.oracle_text == (
        "Islandwalk. All Islands are 1/1. Return target Island."
    )
    assert effective.keywords == ("Islandwalk",)


@pytest.mark.cr("612.1")
def test_612_1_plains_is_not_pluralised_by_appending_an_s(catalog):
    """The same trap ``singular_land_type`` guards from the other side: Plains
    is spelled the same singular and plural, so appending an "s" would look for
    "plainss" — a word no card contains — and the type line would survive the
    change untouched. It is read as singular, the reading a type line uses.
    """
    plains = Permanent(card=catalog["Plains"])
    assert plains.has_type("plains") is True

    change_land_word(plains, "plains", "mountain")

    assert plains.effective_card.type_line == "Basic Land — Mountain"
    assert plains.has_type("mountain") is True
    assert plains.has_type("plains") is False
    # CR 305.6: the type is where a basic land's mana ability comes from.
    assert plains.basic_land_mana == ("R",)


@pytest.mark.cr("612.2")
def test_612_2_a_text_change_does_not_rewrite_the_card_name(catalog):
    """612.2: an effect that changes a colour word or a subtype can't change a
    card name, even when the name contains that word."""
    knight = Permanent(card=catalog["Black Knight"])
    change_color_word(knight, "B", "R")

    assert knight.effective_card.name == "Black Knight"


@pytest.mark.cr("613.1c")
def test_613_1c_no_remap_returns_the_card_unchanged(catalog):
    """The common path must not allocate or copy: nearly every rules query
    reads effective_card."""
    game, (knight,) = _board(catalog, "Black Knight")
    assert knight.effective_card is knight.card
