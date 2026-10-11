"""A search that finds one card per printed description (``one_of_each``).

"a land card **of each basic land type**" (Gaea's Balance) and "a creature
card, a land card, and a noncreature, nonland card" (Guided Passage) are the
two printings; the machinery is the search prompt's, so it is tested here
rather than in either card's file.

Three readers have to agree about one phrase — the picker's list of what may be
found, the resolver's check of an answer, and the default a seat nobody asks
takes — and the thing they have to agree about is not a property of a card: a
Tropical Island is a Forest card *and* an Island card, so whether it is a legal
find beside a basic Forest depends on which of the two it is being read as.
``search_filters.slot_assignment`` answers that exactly, and these hold all
three readers to it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_search_cards
from engine.search_filters import (
    ONE_OF_EACH,
    search_matches,
    search_slots,
    slot_assignment,
)

#: The five descriptions "a land card of each basic land type" lowers to, in
#: the printed order.
_LAND_SLOTS = [
    {"card_type": "land", "restrictions": {"subtypes": [word]}}
    for word in ("plains", "island", "swamp", "mountain", "forest")
]
_BALANCE = {"card_type": "land", "restrictions": {ONE_OF_EACH: _LAND_SLOTS}}

#: Guided Passage's three.
_PASSAGE = {
    "card_type": "any",
    "restrictions": {
        ONE_OF_EACH: [
            {"card_type": "creature"},
            {"card_type": "land"},
            {"exclude_types": ["creature", "land"]},
        ],
    },
}


@pytest.fixture(scope="module")
def lea(set_pool):
    return set_pool("LEA")


def _assigned(lea, names, data):
    return slot_assignment([lea[name] for name in names], data)


def test_the_picker_offers_the_union_of_the_descriptions(lea):
    """What ``search_matches`` answers for one card: it fills *some*
    description. A land with no basic land type fills none of Gaea's Balance's,
    and a creature is no land at all."""
    assert search_slots(_BALANCE) == tuple(_LAND_SLOTS)
    assert search_matches(lea["Forest"], _BALANCE)
    assert search_matches(lea["Tropical Island"], _BALANCE)
    assert not search_matches(lea["Grizzly Bears"], _BALANCE)
    # Every card answers one of Guided Passage's three, which is the point of
    # the three: creature, land, or neither.
    for name in ("Grizzly Bears", "Forest", "Sol Ring", "Clockwork Beast"):
        assert search_matches(lea[name], _PASSAGE), name


def test_a_card_fills_one_description_however_many_it_answers(lea):
    """A dual land is found as one type or the other and never as both: two
    cards for two descriptions, and a third Forest has nowhere to go."""
    assert _assigned(lea, ["Tropical Island"], _BALANCE) in ([1], [4])
    assert None not in _assigned(lea, ["Tropical Island", "Forest"], _BALANCE)
    assert None not in _assigned(lea, ["Tropical Island", "Island"], _BALANCE)
    assert None in _assigned(lea, ["Forest", "Forest"], _BALANCE)
    assert None in _assigned(lea, ["Tropical Island", "Forest", "Island"], _BALANCE)


def test_the_assignment_is_exact_where_first_fit_would_refuse(lea):
    """Tropical Island, Taiga and a basic Forest are three legal finds — but
    only with the Tropical Island read as the Island and the Taiga as the
    Mountain. A first-fit that gave either dual the Forest slot would strand
    the basic, in whichever order the three were named."""
    import itertools

    for order in itertools.permutations(["Tropical Island", "Taiga", "Forest"]):
        assigned = _assigned(lea, list(order), _BALANCE)
        assert None not in assigned, order
        assert len(set(assigned)) == 3, order
        assert assigned[order.index("Forest")] == 4, "only the Forest slot fits it"


def test_an_artifact_creature_is_not_a_noncreature_card(lea):
    """Clockwork Beast answers the creature description alone, so beside a
    second creature it has nowhere to go even with the third slot empty."""
    assert _assigned(lea, ["Clockwork Beast"], _PASSAGE) == [0]
    assert None in _assigned(lea, ["Clockwork Beast", "Grizzly Bears"], _PASSAGE)
    assert _assigned(lea, ["Grizzly Bears", "Forest", "Sol Ring"], _PASSAGE) == [0, 1, 2]


def _armed(lea, library, data, *, chooser=0, owner=0, up_to):
    """A game with a one-per-description search armed on *chooser* over
    *owner*'s library, three hands' worth of destinations."""
    players = [PlayerState(name="P0"), PlayerState(name="P1")]
    players[owner].library = [lea[name] for name in library]
    game = Game(players=players)
    slots = len(data["restrictions"][ONE_OF_EACH])
    game.arm_pending_choice(
        "search_library", chooser,
        zone_seat=owner, count=slots, card_type=data["card_type"],
        zones=("library",), restrictions=dict(data["restrictions"]),
        destination="hand", destinations=["hand"] * slots,
        tapped=[False] * slots, up_to=up_to, card_name="Test",
    )
    return game


def _picks(*indices):
    return [{"zone": "library", "index": index} for index in indices]


def test_the_resolver_checks_the_answer_whole_and_moves_nothing_it_refuses(lea):
    library = ["Forest", "Forest", "Tropical Island", "Grizzly Bears"]
    game = _armed(lea, library, _BALANCE, up_to=True)

    assert not game.confirm_search_library_picks(0, _picks(0, 1)), "two Forests"
    assert not game.confirm_search_library_picks(0, _picks(3)), "not a land"
    assert [card.name for card in game.players[0].library] == library
    assert game.confirm_search_library_picks(0, _picks(0, 2))
    assert sorted(card.name for card in game.players[0].hand) == [
        "Forest", "Tropical Island",
    ]


def test_without_up_to_the_floor_is_the_largest_assignment(lea):
    """CR 701.23d's "as many as possible", for a pick that prints no "up to":
    three creatures and a land answer two descriptions, so two is both the
    least and the most that may be taken."""
    library = ["Grizzly Bears", "Hill Giant", "Serra Angel", "Forest"]
    game = _armed(lea, library, _PASSAGE, chooser=1, owner=0, up_to=False)
    (choice,) = game.pending_choices

    assert game._search_findable_count(choice) == 2
    assert game._search_floor(choice) == 2
    assert not game.confirm_search_library_picks(1, _picks(3)), "one short"
    assert not game.decline_search_library(1)
    assert game.confirm_search_library_picks(1, _picks(1, 3))
    assert [card.name for card in game.players[0].hand] == ["Hill Giant", "Forest"]
    assert game.players[1].hand == []


def test_the_default_answer_is_one_the_resolver_admits_and_meets_the_floor(lea):
    """A seat nobody asks: the policy's own list is exact (best card first,
    kept only while every card kept can still be given a description), so the
    resolver takes it without falling back, floor and all."""
    library = ["Tropical Island", "Swamp", "Grizzly Bears", "Taiga", "Forest"]
    game = _armed(lea, library, _BALANCE, up_to=False)
    (choice,) = game.pending_choices

    proposed = choose_search_cards(game, 0, choice.data, 5)
    names = [library[pick["index"]] for pick in proposed]
    assert sorted(names) == ["Forest", "Swamp", "Taiga", "Tropical Island"]

    game.auto_resolve_pending_choices()
    assert game.pending_choices == []
    assert sorted(card.name for card in game.players[0].hand) == sorted(names)
    assert [card.name for card in game.players[0].library] == ["Grizzly Bears"]


def test_a_seat_choosing_for_another_hand_gives_up_its_least(lea):
    """Whose hand the finds are for decides which way the policy leans. Out of
    an opponent's library **into that opponent's hand** (Guided Passage; the
    shape Jester's Mask refills a hand with), the chooser hands over the
    weakest card of each kind; the same pick for its own hand takes the best.
    """
    library = ["Black Lotus", "Sol Ring", "Serra Angel", "Grizzly Bears", "Forest"]

    def chosen(chooser, owner):
        game = _armed(lea, library, _PASSAGE, chooser=chooser, owner=owner, up_to=False)
        (choice,) = game.pending_choices
        return sorted(
            library[pick["index"]]
            for pick in choose_search_cards(game, chooser, choice.data, 3)
        )

    for_itself = chosen(0, 0)
    for_its_opponent = chosen(1, 0)
    assert len(for_itself) == len(for_its_opponent) == 3
    assert for_itself != for_its_opponent
    assert "Forest" in for_itself and "Forest" in for_its_opponent, "the only land"
    from engine.ai_policy import _score_tutor_choice

    def worth(seat, names):
        game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
        return sum(_score_tutor_choice(game, seat, lea[name]) for name in names)

    assert worth(0, for_itself) > worth(0, for_its_opponent)
