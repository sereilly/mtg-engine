"""A creature type as the word a text change replaces (CR 612, ONS W1G5).

Artificial Evolution's half of ``engine/text_changes.py``: the written forms of
one creature type (the singular and a plural that is not always "-s"), the
type line and the rules text both rewritten (CR 612.1), and no card name
touched even where it is made of the word (CR 612.2). Invented cards, because
each case is one sentence and the real printings that carry them are spread
over the whole pool.
"""
from __future__ import annotations

import pytest

from engine.models import Permanent
from engine.text_changes import (apply_text_changes, change_creature_word,
                                 changed_words, creature_type_plural,
                                 creature_types_written, text_changes)
from tests.helpers import _mk_card


@pytest.mark.parametrize(("word", "plural"), [
    ("goblin", "goblins"), ("elf", "elves"), ("dwarf", "dwarves"),
    ("wolf", "wolves"), ("merfolk", "merfolk"), ("treefolk", "treefolk"),
    ("djinn", "djinn"), ("sphinx", "sphinxes"), ("harpy", "harpies"),
    ("ox", "oxen"), ("faerie", "faeries"),
])
def test_a_creature_types_plural_is_the_one_cards_print(word, plural):
    assert creature_type_plural(word) == plural


def _changed(card, old, new):
    permanent = Permanent(card=card)
    assert change_creature_word(permanent, old, new, label="test")
    return permanent.effective_card


def test_both_written_forms_and_the_type_line_change():
    """"Other Elf creatures" and "Elves you control" are both instances of the
    word, and so is the "— Elf" of the type line: all three are rewritten, the
    plural to the new word's plural, with the printed capitalisation."""
    lord = _mk_card(
        "W1G5 Elf Lord", "{2}{G}", "Creature — Elf Warrior",
        "Other Elf creatures get +1/+1. Elves you control have trample.",
    )
    changed = _changed(lord, "elf", "goblin")
    assert changed.type_line == "Creature — Goblin Warrior"
    assert changed.oracle_text == (
        "Other Goblin creatures get +1/+1. Goblins you control have trample."
    )


def test_a_card_name_is_never_rewritten():
    """CR 612.2: the card's own name in its rules text, and a name a "named"
    phrase spells, keep their words — and the name itself is untouched."""
    card = _mk_card(
        "Elf Herald", "{1}{G}", "Creature — Elf",
        "Elf Herald gets +1/+1 for each other Elf you control. Search your "
        "library for a card named Elf Queen.",
    )
    changed = _changed(card, "elf", "zombie")
    assert changed.name == "Elf Herald"
    assert changed.type_line == "Creature — Zombie"
    assert changed.oracle_text == (
        "Elf Herald gets +1/+1 for each other Zombie you control. Search your "
        "library for a card named Elf Queen."
    )


def test_two_changes_apply_in_timestamp_order_and_the_renderer_sees_the_net():
    """Elf to Goblin, then Goblin to Elf: every word that was either now reads
    Elf (CR 613.7), and ``changed_words`` reports the one edit a player sees —
    the original Goblin words, struck through for Elf."""
    card = _mk_card(
        "W1G5 Two Tribes", "{2}", "Creature — Elf",
        "Other Goblin creatures get +1/+1.",
    )
    permanent = Permanent(card=card)
    assert change_creature_word(permanent, "elf", "goblin", label="first")
    assert change_creature_word(permanent, "goblin", "elf", label="second")
    assert len(text_changes(permanent)) == 2
    folded = apply_text_changes(card, text_changes(permanent))
    assert folded.type_line == "Creature — Elf"
    assert folded.oracle_text == "Other Elf creatures get +1/+1."
    assert changed_words(permanent) == [
        {"from": "goblins", "to": "elves"}, {"from": "goblin", "to": "elf"},
    ]


def test_the_same_word_or_no_creature_type_records_nothing():
    """"It can't change a word to the same word." (the ruling), and CR 205.3m
    bounds both words."""
    permanent = Permanent(card=_mk_card("W1G5 Bear", "{1}{G}", "Creature — Bear", ""))
    assert not change_creature_word(permanent, "bear", "bear")
    assert not change_creature_word(permanent, "bear", "forest")
    assert not change_creature_word(permanent, "island", "bear")
    assert text_changes(permanent) == ()


def test_the_words_written_on_a_card_are_the_ones_a_change_reaches():
    """``creature_types_written``: the type line first, then the rules text,
    each type once and singular, never one inside a card name — the default
    word a seat nobody asks replaces."""
    card = _mk_card(
        "Goblin Herald", "{1}{R}", "Creature — Goblin Shaman",
        "Goblin Herald gets +1/+1 for each Elf. Wolves you control have haste.",
    )
    assert creature_types_written(card) == ("goblin", "shaman", "elf", "wolf")
    assert creature_types_written(_mk_card("Plain", "{1}", "Artifact", "")) == ()
