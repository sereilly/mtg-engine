"""The AI's keep decision and its London-mulligan bottom choice
(``engine/ai_mulligan.py``), over hand fixtures.

Until the ``kg2`` round no AI seat ever mulliganed: the simulator and the web
table kept every hand as dealt. These pin the decision itself — lands against
the curve, judged on the hand left after the bottom choice — so a change to a
window number is a change someone reads here.
"""
from __future__ import annotations

import pytest

from engine.ai_mulligan import (
    ALWAYS_KEEP_AT,
    bottom_choice,
    keep_window,
    keeps,
    keeps_opening_hand,
    opening_hand_bottom,
)
from engine.game import Game
from engine.models import PlayerState

#: A limited deck's land share (CR 100.2b's 40 cards, 17 lands), what the
#: simulator deals.
LIMITED = 17 / 40


@pytest.fixture
def lea(set_pool):
    return set_pool("LEA")


def _hand(lea, *names):
    return [lea[name] for name in names]


# -- seven cards, nothing owed ----------------------------------------------------


def test_a_seven_with_no_land_is_mulliganed(lea):
    hand = _hand(
        lea, "Grizzly Bears", "Llanowar Elves", "Giant Growth", "Wall of Wood",
        "Craw Wurm", "Gray Ogre", "Lightning Bolt",
    )
    assert keeps(hand, 0, land_share=LIMITED) is False


def test_a_seven_with_one_land_is_mulliganed(lea):
    hand = _hand(
        lea, "Forest", "Grizzly Bears", "Llanowar Elves", "Giant Growth",
        "Wall of Wood", "Craw Wurm", "Force of Nature",
    )
    assert keeps(hand, 0, land_share=LIMITED) is False


def test_a_two_land_seven_with_a_play_those_lands_begin_is_kept(lea):
    hand = _hand(
        lea, "Forest", "Forest", "Grizzly Bears", "Craw Wurm", "Force of Nature",
        "Shivan Dragon", "Hill Giant",
    )
    assert keeps(hand, 0, land_share=LIMITED) is True


def test_a_two_land_seven_whose_lands_begin_nothing_is_mulliganed(lea):
    """The floor of the window asks for a play: two Forests and nothing green
    under four mana is a hand that does nothing until it draws lands of the
    other colour."""
    hand = _hand(
        lea, "Forest", "Forest", "Lightning Bolt", "Gray Ogre", "Hill Giant",
        "Craw Wurm", "Shivan Dragon",
    )
    assert keeps(hand, 0, land_share=LIMITED) is False


def test_a_morph_card_is_a_play_two_lands_begin(lea, set_pool):
    """A morph card is castable face down for {3} of any colour (CR 702.37c),
    so it is the play a two-land hand at the floor needs."""
    ons = set_pool("ONS")
    hand = _hand(lea, "Forest", "Forest", "Lightning Bolt", "Hill Giant", "Shivan Dragon")
    hand += [ons["Exalted Angel"], ons["Daru Lancer"]]
    assert keeps(hand, 0, land_share=LIMITED) is True
    hand_without = hand[:5] + _hand(lea, "Craw Wurm", "Earth Elemental")
    assert keeps(hand_without, 0, land_share=LIMITED) is False


def test_a_five_land_seven_is_kept(lea):
    hand = _hand(
        lea, "Forest", "Forest", "Forest", "Mountain", "Mountain", "Grizzly Bears",
        "Lightning Bolt",
    )
    assert keeps(hand, 0, land_share=LIMITED) is True


def test_a_six_land_seven_is_mulliganed(lea):
    hand = _hand(
        lea, "Forest", "Forest", "Forest", "Mountain", "Mountain", "Mountain",
        "Grizzly Bears",
    )
    assert keeps(hand, 0, land_share=LIMITED) is False


def test_a_seven_land_seven_is_mulliganed(lea):
    hand = _hand(lea, *(["Forest"] * 4 + ["Mountain"] * 3))
    assert keeps(hand, 0, land_share=LIMITED) is False


# -- after a mulligan: the seven drawn, one card owed --------------------------------


def test_after_one_mulligan_a_five_land_draw_bottoms_a_land_and_keeps(lea):
    hand = _hand(
        lea, "Forest", "Forest", "Forest", "Mountain", "Mountain", "Grizzly Bears",
        "Lightning Bolt",
    )
    going = bottom_choice(hand, 1, land_share=LIMITED)
    assert len(going) == 1 and hand[going[0]].type_line.startswith("Basic Land")
    assert keeps(hand, 1, land_share=LIMITED) is True


def test_after_one_mulligan_a_six_land_draw_is_mulliganed_again(lea):
    """Six lands of seven, one bottomed: five lands and a spell in six cards is
    over the six-card window's four."""
    hand = _hand(
        lea, "Forest", "Forest", "Forest", "Mountain", "Mountain", "Mountain",
        "Grizzly Bears",
    )
    assert keeps(hand, 1, land_share=LIMITED) is False


def test_after_one_mulligan_a_one_land_draw_is_mulliganed_again(lea):
    hand = _hand(
        lea, "Forest", "Grizzly Bears", "Llanowar Elves", "Giant Growth",
        "Wall of Wood", "Craw Wurm", "Gray Ogre",
    )
    assert keeps(hand, 1, land_share=LIMITED) is False


def test_a_six_card_hand_keeps_its_lands_and_bottoms_the_dearest_spell(lea):
    hand = _hand(
        lea, "Forest", "Forest", "Mountain", "Grizzly Bears", "Shivan Dragon",
        "Lightning Bolt", "Gray Ogre",
    )
    going = bottom_choice(hand, 1, land_share=LIMITED)
    assert [hand[i].name for i in going] == ["Shivan Dragon"]
    assert keeps(hand, 1, land_share=LIMITED) is True


def test_a_spell_the_kept_lands_cannot_colour_goes_before_a_dearer_one_they_can(lea):
    """Price is mana value plus two for a spell no kept land colours: a
    Lightning Bolt beside three Forests costs more to keep than a Grizzly
    Bears."""
    hand = _hand(
        lea, "Forest", "Forest", "Forest", "Grizzly Bears", "Llanowar Elves",
        "Giant Growth", "Lightning Bolt",
    )
    going = bottom_choice(hand, 1, land_share=LIMITED)
    assert [hand[i].name for i in going] == ["Lightning Bolt"]


def test_the_land_bottomed_is_the_one_whose_colour_no_spell_asks_for(lea):
    """Two cards owed from a five-land seven: lands down to three of five,
    and the Island and the Mountain go — no spell in the hand is blue or
    red."""
    hand = _hand(
        lea, "Island", "Forest", "Forest", "Mountain", "Forest", "Grizzly Bears",
        "Llanowar Elves",
    )
    going = bottom_choice(hand, 2, land_share=LIMITED)
    assert sorted(hand[i].name for i in going) == ["Island", "Mountain"]


def test_a_hand_short_of_lands_never_bottoms_one(lea):
    hand = _hand(
        lea, "Forest", "Forest", "Grizzly Bears", "Llanowar Elves", "Giant Growth",
        "Wall of Wood", "Craw Wurm",
    )
    going = bottom_choice(hand, 2, land_share=LIMITED)
    assert all(not hand[i].type_line.startswith("Basic Land") for i in going)
    assert len(set(going)) == 2


def test_at_the_floor_every_hand_is_kept(lea):
    """Three cards owed is a hand of four: kept whatever it holds."""
    hand = _hand(
        lea, "Grizzly Bears", "Llanowar Elves", "Giant Growth", "Wall of Wood",
        "Craw Wurm", "Gray Ogre", "Lightning Bolt",
    )
    assert len(hand) - 3 == ALWAYS_KEEP_AT
    assert keeps(hand, 3, land_share=LIMITED) is True


def test_the_window_scales_with_the_deck():
    """A deck with no lands keeps every hand; a two-thirds-land deck is not
    mulliganed for holding them; a limited deck reads the table."""
    assert keep_window(7, LIMITED) == (2, 5)
    assert keep_window(6, LIMITED) == (2, 4)
    assert keep_window(5, LIMITED) == (1, 4)
    assert keep_window(7, 0.0)[0] == 0
    assert keep_window(7, 2 / 3)[1] == 6


def test_a_landless_deck_keeps_a_landless_hand(lea):
    hand = _hand(
        lea, "Black Lotus", "Sol Ring", "Grizzly Bears", "Giant Growth",
        "Wall of Wood", "Gray Ogre", "Lightning Bolt",
    )
    assert keeps(hand, 0, land_share=0.0) is True


# -- asked of a game ------------------------------------------------------------------


def _game_with(lea, hand, library):
    seat = PlayerState(name="AI", hand=list(hand), library=list(library))
    return Game(players=[seat, PlayerState(name="Other")])


def test_the_game_reader_reads_the_deck_share_and_the_count_owed(lea):
    """``keeps_opening_hand`` judges the hand against the deck the seat holds
    (hand and library, counted) and owes what ``mulligan_effective_count``
    says: the same six-land seven is mulliganed owing nothing and kept owing
    two, which go as two of its lands."""
    hand = _hand(
        lea, "Forest", "Forest", "Forest", "Mountain", "Mountain", "Mountain",
        "Grizzly Bears",
    )
    library = _hand(lea, *(["Grizzly Bears"] * 30 + ["Forest"] * 3))
    game = _game_with(lea, hand, library)
    assert keeps_opening_hand(game, 0) is False
    game.players[0].mulligans_taken = 2  # a two-player game: owes two
    assert keeps_opening_hand(game, 0) is True
    going = opening_hand_bottom(game, 0)
    assert len(going) == 2
    assert all(hand[i].type_line.startswith("Basic Land") for i in going)


def test_the_decision_reads_the_library_as_a_count_not_an_order(lea):
    """CR 400.2: a seat knows its decklist, not its library's order. The same
    hand over the same library in another order gets the same answer and the
    same bottom."""
    hand = _hand(
        lea, "Forest", "Forest", "Forest", "Mountain", "Mountain", "Grizzly Bears",
        "Lightning Bolt",
    )
    library = _hand(lea, *(["Forest"] * 10 + ["Grizzly Bears"] * 23))
    one = _game_with(lea, hand, library)
    other = _game_with(lea, hand, list(reversed(library)))
    for game in (one, other):
        game.players[0].mulligans_taken = 1
    assert keeps_opening_hand(one, 0) == keeps_opening_hand(other, 0)
    assert opening_hand_bottom(one, 0) == opening_hand_bottom(other, 0)
