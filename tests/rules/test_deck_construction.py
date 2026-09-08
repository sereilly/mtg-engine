"""CR 100.2 / 100.4 / 100.5 / 100.7 — the deck, the sideboard, "outside the
game", and the cards the rules decline to cover.

Section 100 is the one part of the rules that runs *before* a game exists, and
it was the largest untouched section in the tracker: seven rules, twenty-five
citations across ``engine/`` and ``web/``, and no test. What made it look
untestable is that it reads like preamble ("each player needs their own deck").
It is not — three of its rules are enforced code:

* **CR 100.2a/100.5** is the minimum deck size, counted over the library alone.
* **CR 100.4a** is the four-of limit, and the thing worth a test is *where* it
  counts: the deck and the sideboard **together**, so three copies in the deck
  and two in the sideboard is five copies and illegal, even though neither pile
  breaks the limit by itself.
* **CR 100.4** is the sideboard as a pool of cards "outside the game", which
  ``Ring of Ma'rûf`` reaches into mid-game. That is the rule leaving deck
  construction and becoming a game action.

* **CR 100.7** is the rule that says some cards are *outside* these rules
  altogether — the physical-dexterity cards, where the engine substitutes
  rather than implements.

The validator (``web/deck_legality.py``) is the enforcement point for the first
two, the seat's ``sideboard`` list for the third, and ``engine/dexterity.py``
for the fourth.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from web.deck_legality import validate_deck


def _catalog_by_name():
    from web.app import CATALOG_BY_NAME

    return CATALOG_BY_NAME


@pytest.mark.cr("100.2a", "100.5")
def test_100_2a_the_minimum_deck_size_counts_the_library_alone():
    """"...a minimum deck size" (CR 100.5), which CR 100.2a fixes at sixty for a
    constructed deck.

    Counted over the deck and **not** over the deck plus sideboard: a
    fifty-five-card deck with a fifteen-card sideboard is seventy cards and
    still illegal, which is the arithmetic a combined count would get wrong in
    the direction that admits an illegal deck.
    """
    short = validate_deck(
        [{"name": "Swamp", "count": 55}],
        "premodern",
        _catalog_by_name(),
        sideboard=[{"name": "Island", "count": 15}],
    )
    assert short["legal"] is False

    exact = validate_deck(
        [{"name": "Swamp", "count": 60}],
        "premodern",
        _catalog_by_name(),
        sideboard=[{"name": "Island", "count": 15}],
    )
    assert exact["legal"] is True, exact


@pytest.mark.cr("100.4a")
def test_100_4a_the_copy_limit_counts_the_deck_and_sideboard_together():
    """"...the combined deck, sideboard, and command zone."

    Neither pile is illegal alone — three copies in the deck and two in the
    sideboard — and together they are five. A validator that checked each pile
    separately passes both halves and admits the deck, which is why this is
    asserted on a split that only the combined count can catch.

    Basic lands are exempt (CR 100.2a's own carve-out), so the copies here are a
    nonbasic card.
    """
    split = validate_deck(
        [{"name": "Swamp", "count": 57}, {"name": "Hypnotic Specter", "count": 3}],
        "premodern",
        _catalog_by_name(),
        sideboard=[{"name": "Hypnotic Specter", "count": 2}],
    )
    assert split["legal"] is False
    assert any("Hypnotic Specter" in problem for problem in split["problems"]), split

    # The same five copies, with one fewer, is legal — so the failure above is
    # the limit and not something else about the list.
    ok = validate_deck(
        [{"name": "Swamp", "count": 57}, {"name": "Hypnotic Specter", "count": 3}],
        "premodern",
        _catalog_by_name(),
        sideboard=[{"name": "Hypnotic Specter", "count": 1}],
    )
    assert ok["legal"] is True, ok


@pytest.mark.cr("100.4")
def test_100_4_a_card_from_outside_the_game_comes_out_of_the_sideboard():
    """"Ring of Ma'rûf: ...instead put a card you own from **outside the game**
    into your hand."

    CR 100.4's sideboard is what "outside the game" reaches in a game with no
    tournament around it, and the seat's ``sideboard`` list is where the engine
    keeps it. It is deliberately not a zone (nothing moves *into* it during
    play), so the test is that the card leaves it for the hand and that the
    library is untouched — the Ring replaces a draw rather than performing one.
    """
    catalog = {c.name: c for c in load_catalog()}
    ring = next(c for c in catalog.values() if c.name.startswith("Ring of Ma"))
    outside = catalog["Black Lotus"]

    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=ring)],
        library=[catalog["Swamp"], catalog["Swamp"]],
        sideboard=[outside],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    assert game._outside_game_choices(0) == [0], "the one card outside the game"

    game._finish_outside_game_draw(0, 0)

    assert [c.name for c in p1.hand] == ["Black Lotus"]
    assert p1.sideboard == [], "the card left the pool outside the game"
    assert len(p1.library) == 2, "a replaced draw draws nothing from the library"


@pytest.mark.cr("100.7")
def test_100_7_a_dexterity_card_is_substituted_rather_than_implemented():
    """"Certain cards are intended for casual play and may have features and
    text that aren’t covered by these rules."

    Chaos Orb and Falling Star ask a player to flip the physical card onto the
    table from a height of at least one foot and read what it lands on. There is
    no playing area here, no geometry for "lands on", and no honest reading of
    "doesn’t turn completely over" — CR 100.7 puts all of that outside the
    rules, so the engine **substitutes** a random selection and says so.

    What is worth a test is that the substitution is one place and behaves
    within its stated bounds: it never lands on more permanents than exist, an
    empty board yields nothing rather than raising, and a minimum above zero is
    still clamped to what is there. Both cards must substitute the same way —
    two independently drifting house rules for one printed idiom is exactly what
    the shared module exists to prevent.
    """
    from engine.dexterity import flip_lands_on

    board = ["a", "b", "c"]

    for _ in range(50):
        hit = flip_lands_on(board, maximum=2)
        assert 0 <= len(hit) <= 2
        assert set(hit) <= set(board)
        assert len(set(hit)) == len(hit), "no permanent is hit twice"

    # Clamped to the board rather than to the card's number.
    assert flip_lands_on([], maximum=3, minimum=1) == []
    assert len(flip_lands_on(["only"], maximum=3, minimum=3)) == 1

