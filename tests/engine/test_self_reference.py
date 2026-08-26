"""What a card may call itself by (CR 201.5), and what it may not.

``engine/self_reference.py`` writes a legendary card's shortened name out in
full before any line is classified. The rule is "the first word of a legendary
card's multi-word name, unless that word is one the game uses to describe
objects", and every clause of it was bought by a pool-wide probe — so the guards
here are that probe, run as a test.
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.self_reference import expand_short_self_references, short_self_name


@pytest.fixture(scope="module")
def _r28_pool():
    seen = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        seen.setdefault(card.name, card)
    return list(seen.values())


def test_a_legendary_name_shortens_at_its_first_word():
    assert short_self_name("Rasputin Dreamweaver", legendary=True) == "Rasputin"
    assert short_self_name("Hazezon Tamar", legendary=True) == "Hazezon"
    assert short_self_name("Rohgahh of Kher Keep", legendary=True) == "Rohgahh"


def test_a_comma_name_is_left_to_the_readers_that_already_split_it():
    """Both readers of a self-reference shorten at the comma themselves, and a
    second answer here would be a second copy of a rule already right."""
    assert short_self_name("Ugin, the Spirit Dragon", legendary=True) is None


def test_a_one_word_name_has_no_short_form():
    assert short_self_name("Stangg", legendary=True) is None


def test_an_article_is_not_a_name():
    """"The Tabernacle at Pendrell Vale" would otherwise shorten to "the"."""
    assert short_self_name("The Tabernacle at Pendrell Vale", legendary=True) is None


def test_a_word_the_game_uses_is_not_a_name():
    """A legend whose first word is a creature type keeps its full name: a card
    printing "other Walls" would otherwise be talking about itself.

    Asked of an invented name because the pool has no such legend today, which
    is the point — the clause is here for the set that prints one, not for a
    card anyone can look up."""
    assert short_self_name("Wall Doe", legendary=True) is None
    assert short_self_name("Green Doe", legendary=True) is None


def test_a_nonlegendary_name_never_shortens():
    """The clause that matters most. Without it Mana Flare loses the word
    "mana" and Black Ward's "protection from black" names the Aura itself."""
    assert short_self_name("Mana Flare", legendary=False) is None
    assert short_self_name("Black Ward", legendary=False) is None


def test_the_full_name_wins_where_both_are_printed():
    """"Rin and Seri" must not have its own first word rewritten inside an
    occurrence of the whole name."""
    text = "Rin and Seri, Inseparable deals damage."
    assert (
        expand_short_self_references(text, "Rin and Seri", legendary=True) == text
    )


def test_no_card_in_the_pool_loses_a_word_to_the_expansion(_r28_pool):
    """The probe that decided the rule, as a ratchet.

    Every card whose text the expansion *changes* is named here. A set that adds
    another one is a set whose card should be read — either it is a legend
    referring to itself, or the rule has found a word it should not have.
    """
    changed = {
        card.name
        for card in _r28_pool
        if expand_short_self_references(
            card.oracle_text or "", card.name, legendary=card.is_legendary
        ) != (card.oracle_text or "")
    }
    assert changed == {"Hazezon Tamar", "Rasputin Dreamweaver", "Rohgahh of Kher Keep"}
