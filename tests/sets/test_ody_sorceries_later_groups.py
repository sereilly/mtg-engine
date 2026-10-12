"""Odyssey sorceries, continued: whole group sections moved out of `test_ody_sorceries.py`.

`test_ody_sorceries.py` reached the per-set size cap at wave 1's integration, on no
group's branch - nine groups each wrote a test per driven card, which is what
the briefs asked for. The sections below were moved **whole**, byte for byte,
under the marker pairs they had; a section carries its own imports and its
own `_w<wave>g<n>_` prefix, so nothing here depends on its old neighbours.
Their empty marker pairs stay behind in `test_ody_sorceries.py` so a branch still in
flight merges against unchanged context.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` (`tests/sets/README.md`).
"""


# ==== W1G7 ==========================================================

import random as _w1g7_random

import pytest as _w1g7_pytest

from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import _mk_card as _w1g7_mk_card
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=(), interactive=()):
    """A two-seat game with costs off, built from card names (ODY over LEA).
    A seat in *interactive* is asked its decisions instead of defaulting."""
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    seats = [
        _w1g7_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g7_Game(players=seats)
    game.enforce_mana_costs = False
    for seat in interactive:
        game.interactive_seats.add(seat)
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g7_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g7_names(cards):
    return [card.name for card in cards]


def _w1g7_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g7_settle(game, limit=50):
    """Drain the stack and give every owed prompt its default answer."""
    for _ in range(limit):
        _w1g7_resolve_stack(game)
        if not game.pending_choices and not game.pending_replacement_choices:
            return
        game.auto_resolve_pending_choices()
        game.auto_resolve_pending_replacement_choices()
    raise AssertionError("the game did not settle")


def _w1g7_picks(*indices):
    return [{"zone": "library", "index": index} for index in indices]


# --- Traumatize: half a library, rounded down ----------------------------------

@_w1g7_pytest.mark.parametrize(
    "library, milled", [(7, 3), (8, 4), (1, 0), (0, 0)],
)
def test_traumatize_mills_half_the_targets_library_rounded_down(
    set_pool, library, milled
):
    """"Target player mills half their library, rounded down." The half is
    taken as the spell resolves (CR 608.2h), of the *target's* library, and an
    empty one mills nothing and loses nobody the game (CR 704.5b is about a
    draw)."""
    game = _w1g7_duel(
        set_pool, hand0=["Traumatize"], lib0=["Island"] * 5,
        lib1=["Forest"] * library,
    )
    assert game.cast_from_hand(0, "Traumatize", target_player_index=1).supported
    _w1g7_settle(game)
    assert len(game.players[1].graveyard) == milled
    assert len(game.players[1].library) == library - milled
    assert len(game.players[0].library) == 5, "the caster's library is untouched"
    assert not game.players[1].lost


def test_traumatize_takes_the_top_cards_and_may_be_aimed_at_its_caster(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Traumatize"],
        lib1=["Forest", "Island", "Swamp", "Plains", "Mountain"],
    )
    game.cast_from_hand(0, "Traumatize", target_player_index=1)
    _w1g7_settle(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Forest", "Island"]
    assert _w1g7_names(game.players[1].library) == ["Swamp", "Plains", "Mountain"]

    own = _w1g7_duel(
        set_pool, hand0=["Traumatize"], lib0=["Island"] * 4, lib1=["Forest"] * 4,
    )
    own.cast_from_hand(0, "Traumatize", target_player_index=0)
    _w1g7_settle(own)
    assert len(own.players[0].library) == 2 and len(own.players[1].library) == 4


def test_a_fraction_of_a_library_is_one_quantity_however_it_is_spelled():
    """"Half their library" is "cards equal to half the number of cards in
    their library" without the noun, so both spell one spec — and the draw
    that has read the long form since Peer into the Abyss reads the same one.
    A set of seats refuses: the count is taken once."""
    def program(text):
        return _w1g7_compile(_w1g7_mk_card("Bisect", "{U}", "Sorcery", text))

    short = program("Target player mills half their library, rounded down.")
    long = program(
        "Target player mills cards equal to half the number of cards in their "
        "library, rounded down."
    )
    assert short.supported and long.supported
    assert short.instructions[0].payload == long.instructions[0].payload
    assert short.instructions[0].payload["x_from_count"] == {
        "zone": "library", "owner": "owner", "filter": {}, "half": "down",
    }
    up = program("Target player mills half their library, rounded up.")
    assert up.instructions[0].payload["x_from_count"]["half"] == "up"
    assert program("Mill half your library, rounded down.").supported
    assert not program("Each player mills half their library, rounded down.").supported
    assert not program("Target player mills half your library, rounded down.").supported
    assert not program("Target player mills half their graveyard.").supported


def test_a_rounded_up_half_and_a_third_are_counted_as_printed(set_pool):
    for text, expected in (
        ("Target player mills half their library, rounded up.", 4),
        ("Target player mills a third of their library, rounded down.", 2),
    ):
        game = _w1g7_duel(set_pool, lib1=["Forest"] * 7)
        game.players[0].hand.append(_w1g7_mk_card("Bisect", "{U}", "Sorcery", text))
        assert game.cast_from_hand(0, "Bisect", target_player_index=1).supported
        _w1g7_settle(game)
        assert len(game.players[1].graveyard) == expected, text


# --- Rites of Spring: a search with a recorded ceiling -------------------------

_W1G7_SPRING_LIBRARY = [
    "Forest", "Grizzly Bears", "Island", "Swamp", "Bayou", "Plains", "Mountain",
]


def test_rites_of_spring_finds_up_to_as_many_basics_as_cards_discarded(set_pool):
    """"Discard any number of cards. Search your library for up to that many
    basic land cards, reveal them, put them into your hand, then shuffle." Two
    discards is a ceiling of two; a nonbasic land, a nonland and a third find
    are each refused; finding fewer is legal (its ruling, 2004-10-04)."""
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Spring", "Grizzly Bears", "Giant Growth", "Terror"],
        lib0=_W1G7_SPRING_LIBRARY, interactive=(0,),
    )
    assert game.cast_from_hand(0, "Rites of Spring").supported
    assert game.confirm_discard(0, [0, 1])
    (search,) = game.pending_choices
    assert search.kind == "search_library"
    assert (search.data["count"], search.data["up_to"]) == (2, True)
    assert search.data["reveal"] is True

    library = _w1g7_names(game.players[0].library)
    at = library.index
    assert not game.confirm_search_library_picks(
        0, _w1g7_picks(at("Forest"), at("Island"), at("Swamp"))
    ), "three finds for two discards"
    assert not game.confirm_search_library_picks(0, _w1g7_picks(at("Bayou")))
    assert not game.confirm_search_library_picks(0, _w1g7_picks(at("Grizzly Bears")))
    assert game.confirm_search_library_picks(0, _w1g7_picks(at("Forest"), at("Island")))

    assert sorted(_w1g7_names(game.players[0].hand)) == ["Forest", "Island", "Terror"]
    assert sorted(_w1g7_names(game.players[0].library)) == sorted(
        ["Grizzly Bears", "Swamp", "Bayou", "Plains", "Mountain"]
    )
    assert not game.stack and not game.pending_choices
    assert any("revealed Forest, Island" in line for line in game.log)


def test_rites_of_spring_may_find_fewer_and_one_discard_is_one_find(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Spring", "Grizzly Bears", "Terror"],
        lib0=_W1G7_SPRING_LIBRARY, interactive=(0,),
    )
    game.cast_from_hand(0, "Rites of Spring")
    assert game.confirm_discard(0, [0, 1])
    library = _w1g7_names(game.players[0].library)
    assert game.confirm_search_library_picks(0, _w1g7_picks(library.index("Swamp")))
    assert _w1g7_names(game.players[0].hand) == ["Swamp"]

    single = _w1g7_duel(
        set_pool, hand0=["Rites of Spring", "Grizzly Bears"],
        lib0=_W1G7_SPRING_LIBRARY, interactive=(0,),
    )
    single.cast_from_hand(0, "Rites of Spring")
    assert single.confirm_discard(0, [0])
    library = _w1g7_names(single.players[0].library)
    assert not single.confirm_search_library(0, library.index("Bayou"))
    assert single.confirm_search_library(0, library.index("Mountain"))
    assert _w1g7_names(single.players[0].hand) == ["Mountain"]


def test_rites_of_spring_with_nothing_discarded_finds_nothing_and_shuffles(
    set_pool,
):
    """Up to no cards is still a search (CR 701.23c: the player "may still
    search that zone but can't find any cards"), so nothing is asked, nothing
    is found, and the library is shuffled all the same."""
    _w1g7_random.seed(2)
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Spring", "Grizzly Bears"],
        lib0=_W1G7_SPRING_LIBRARY, interactive=(0,),
    )
    game.cast_from_hand(0, "Rites of Spring")
    assert game.confirm_discard(0, [])
    assert not game.pending_choices and not game.stack
    assert _w1g7_names(game.players[0].hand) == ["Grizzly Bears"]
    after = _w1g7_names(game.players[0].library)
    assert sorted(after) == sorted(_W1G7_SPRING_LIBRARY)
    assert after != _W1G7_SPRING_LIBRARY, "shuffled (seeded)"
    assert any("for up to 0 cards and shuffled" in line for line in game.log)


def test_a_search_ceiling_with_no_record_behind_it_is_refused():
    assert not _w1g7_compile(_w1g7_mk_card(
        "Bare Spring", "{G}", "Sorcery",
        "Search your library for up to that many basic land cards, reveal "
        "them, put them into your hand, then shuffle.",
    )).supported


# --- Last Rites: a pick out of a revealed hand per card discarded --------------

def test_last_rites_takes_a_nonland_card_per_card_its_caster_discarded(set_pool):
    """"Discard any number of cards. Target player reveals their hand, then
    you choose a nonland card from it for each card discarded this way. That
    player discards those cards." The caster picks, a land is not a legal
    pick, and the picks number exactly what was discarded."""
    game = _w1g7_duel(
        set_pool, hand0=["Last Rites", "Forest", "Island", "Swamp"],
        hand1=["Grizzly Bears", "Forest", "Terror", "Giant Growth"],
        interactive=(0,),
    )
    assert game.cast_from_hand(0, "Last Rites", target_player_index=1).supported
    assert game.confirm_discard(0, [0, 1])
    (pick,) = game.pending_choices
    assert (pick.kind, pick.player_index) == ("revealed_hand_pick", 0)
    assert pick.data["legal_indices"] == [0, 2, 3]
    assert pick.data["remaining"] == 2

    assert not game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=1)
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=2)
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=0)
    assert not game.pending_choices and not game.stack

    assert _w1g7_names(game.players[1].hand) == ["Forest", "Giant Growth"]
    assert _w1g7_names(game.players[1].graveyard) == ["Terror", "Grizzly Bears"]
    assert _w1g7_names(game.players[0].hand) == ["Swamp"]


def test_last_rites_takes_what_there_is_and_reveals_even_for_nothing(set_pool):
    """Three discards against one nonland card is one pick (CR 608.2: as much
    as possible); no discards is a revealed hand and no pick."""
    game = _w1g7_duel(
        set_pool, hand0=["Last Rites", "Forest", "Island", "Swamp"],
        hand1=["Grizzly Bears", "Forest"], interactive=(0,),
    )
    game.cast_from_hand(0, "Last Rites", target_player_index=1)
    assert game.confirm_discard(0, [0, 1, 2])
    assert game.pending_choices[0].data["remaining"] == 1
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=0)
    assert _w1g7_names(game.players[1].hand) == ["Forest"]
    assert not game.pending_choices and not game.stack

    none = _w1g7_duel(
        set_pool, hand0=["Last Rites", "Forest"], hand1=["Grizzly Bears"],
        interactive=(0,),
    )
    none.cast_from_hand(0, "Last Rites", target_player_index=1)
    assert none.confirm_discard(0, [])
    assert not none.pending_choices and not none.stack
    assert _w1g7_names(none.players[1].hand) == ["Grizzly Bears"]
    assert any("revealed their hand" in line for line in none.log)


def test_last_rites_discards_reach_a_discard_watcher_on_both_sides(set_pool):
    """Both halves are discards (CR 701.9a) through the one seam: a Confessor
    hears the caster's own card and the one taken from the target."""
    game = _w1g7_duel(
        set_pool, hand0=["Last Rites", "Forest"], hand1=["Grizzly Bears", "Terror"],
        bf0=["Confessor"], interactive=(0,),
    )
    game.cast_from_hand(0, "Last Rites", target_player_index=1)
    assert game.confirm_discard(0, [0])
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=0)
    _w1g7_settle(game)
    assert game.players[0].life == 22


def test_a_counted_revealed_pick_needs_its_record_and_its_ending():
    def supported(text):
        return _w1g7_compile(_w1g7_mk_card("Rite", "{B}", "Sorcery", text)).supported

    pick = (
        "Target player reveals their hand, then you choose a nonland card "
        "from it for each card discarded this way."
    )
    assert supported(
        "Discard any number of cards. " + pick + " That player discards those cards."
    )
    assert not supported(pick + " That player discards those cards."), "no producer"
    assert not supported("Discard any number of cards. " + pick), "no fate"


# --- Laquatus's Creativity: a count the draw itself would change ----------------

def test_laquatuss_creativity_counts_the_hand_once_before_the_draw(set_pool):
    """"Target player draws cards equal to the number of cards in their hand,
    then discards that many cards." Three in hand is three drawn and three
    discarded — the number is fixed when the effect begins (CR 608.2h), so the
    discard is not a second count of a hand the draw has just doubled. The
    discarding player chooses, and exactly that many."""
    game = _w1g7_duel(
        set_pool, hand0=["Laquatus's Creativity"],
        hand1=["Forest", "Island", "Swamp"], lib1=["Grizzly Bears"] * 6,
        interactive=(1,),
    )
    assert game.cast_from_hand(
        0, "Laquatus's Creativity", target_player_index=1
    ).supported
    (choice,) = game.pending_choices
    assert (choice.kind, choice.player_index, choice.data["count"]) == ("discard", 1, 3)
    assert len(game.players[1].hand) == 6

    assert not game.confirm_discard(1, [0, 1]), "three, not two"
    assert game.confirm_discard(1, [0, 1, 2])
    assert _w1g7_names(game.players[1].hand) == ["Grizzly Bears"] * 3
    assert sorted(_w1g7_names(game.players[1].graveyard)) == ["Forest", "Island", "Swamp"]
    assert len(game.players[1].library) == 3
    assert not game.stack


def test_laquatuss_creativity_may_target_its_caster_and_an_empty_hand_does_nothing(
    set_pool,
):
    """The spell has left its caster's hand by the time it counts (CR 601.2a),
    so two other cards is two; and no cards is no draw and no discard."""
    game = _w1g7_duel(
        set_pool, hand0=["Laquatus's Creativity", "Forest", "Island"],
        lib0=["Grizzly Bears"] * 6, interactive=(0,),
    )
    spec = game.cast_target_spec(0, set_pool("ODY")["Laquatus's Creativity"])
    assert spec["kind"] == "player" and len(spec["valid_targets"]) == 2
    game.cast_from_hand(0, "Laquatus's Creativity", target_player_index=0)
    assert game.pending_choices[0].data["count"] == 2
    assert game.confirm_discard(0, [0, 1])
    assert _w1g7_names(game.players[0].hand) == ["Grizzly Bears"] * 2

    empty = _w1g7_duel(
        set_pool, hand0=["Laquatus's Creativity"], lib1=["Grizzly Bears"] * 6,
    )
    empty.cast_from_hand(0, "Laquatus's Creativity", target_player_index=1)
    _w1g7_settle(empty)
    assert empty.players[1].hand == [] and len(empty.players[1].library) == 6


# --- New Frontiers: each player may search for up to X ---------------------------

_W1G7_FRONTIER_0 = ["Forest", "Grizzly Bears", "Island", "Bayou", "Swamp"]
_W1G7_FRONTIER_1 = ["Plains", "Mountain", "Terror", "Mountain"]


def test_new_frontiers_offers_each_player_up_to_x_basics_tapped(set_pool):
    """"Each player may search their library for up to X basic land cards and
    put them onto the battlefield tapped. Then each player who searched their
    library this way shuffles." Each seat is asked; the one who searches finds
    at most X, basics only, and they enter tapped; the one who declines keeps
    a library nobody shuffled."""
    _w1g7_random.seed(1)
    game = _w1g7_duel(
        set_pool, hand0=["New Frontiers"], lib0=_W1G7_FRONTIER_0,
        lib1=_W1G7_FRONTIER_1, interactive=(0, 1),
    )
    assert game.cast_from_hand(0, "New Frontiers", x_value=2).supported
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    library = _w1g7_names(game.players[0].library)
    at = library.index
    assert not game.confirm_search_library_picks(
        0, _w1g7_picks(at("Forest"), at("Island"), at("Swamp"))
    ), "three finds for X = 2"
    assert not game.confirm_search_library_picks(0, _w1g7_picks(at("Bayou")))
    assert game.confirm_search_library_picks(0, _w1g7_picks(at("Forest"), at("Island")))
    assert game.resolve_pending_choice("optional_pay", 1, accept=False)
    assert not game.stack and not game.pending_choices

    mine = [(p.card.name, p.tapped) for p in game.controlled_by(0)]
    assert sorted(mine) == [("Forest", True), ("Island", True)]
    assert list(game.controlled_by(1)) == []
    assert _w1g7_names(game.players[1].library) == _W1G7_FRONTIER_1, (
        "a player who did not search does not shuffle"
    )
    assert game.players[0].hand == []


def test_new_frontiers_with_x_of_one_is_a_single_find_for_whoever_takes_it(
    set_pool,
):
    _w1g7_random.seed(1)
    game = _w1g7_duel(
        set_pool, hand0=["New Frontiers"], lib0=_W1G7_FRONTIER_0,
        lib1=_W1G7_FRONTIER_1, interactive=(0, 1),
    )
    game.cast_from_hand(0, "New Frontiers", x_value=1)
    assert game.resolve_pending_choice("optional_pay", 0, accept=False)
    assert game.resolve_pending_choice("optional_pay", 1, accept=True)
    library = _w1g7_names(game.players[1].library)
    assert not game.confirm_search_library(1, library.index("Terror"))
    assert game.confirm_search_library(1, library.index("Mountain"))
    assert [(p.card.name, p.tapped) for p in game.controlled_by(1)] == [("Mountain", True)]
    assert _w1g7_names(game.players[0].library) == _W1G7_FRONTIER_0


def test_new_frontiers_with_x_of_zero_finds_nothing_and_still_shuffles(set_pool):
    """CR 701.23c: a search that can find nothing may still be made — and a
    player who makes it shuffles, which is all X = 0 does."""
    _w1g7_random.seed(4)
    game = _w1g7_duel(
        set_pool, hand0=["New Frontiers"], lib0=_W1G7_FRONTIER_0,
        lib1=_W1G7_FRONTIER_1,
    )
    game.cast_from_hand(0, "New Frontiers", x_value=0)
    _w1g7_settle(game)
    assert list(game.controlled_by(0)) == [] and list(game.controlled_by(1)) == []
    assert sorted(_w1g7_names(game.players[0].library)) == sorted(_W1G7_FRONTIER_0)
    assert sum("for up to 0 cards and shuffled" in line for line in game.log) == 2


def test_new_frontiers_charges_its_x_and_a_seat_nobody_asks_takes_the_offer(
    set_pool,
):
    _w1g7_random.seed(1)
    game = _w1g7_duel(
        set_pool, hand0=["New Frontiers"], lib0=_W1G7_FRONTIER_0,
        lib1=_W1G7_FRONTIER_1,
    )
    game.enforce_mana_costs = True
    game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 3, "C": 0}
    assert game.cast_from_hand(0, "New Frontiers", x_value=2).supported
    assert sum(game.players[0].mana_pool.values()) == 0, "{X}{G} with X = 2"
    _w1g7_settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Forest", "Island"]
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Mountain", "Plains"]
    assert all(p.tapped for seat in (0, 1) for p in game.controlled_by(seat))


# --- Bamboozle: a revealed pile off somebody else's library ---------------------

_W1G7_PILE = ["Forest", "Grizzly Bears", "Island", "Terror", "Swamp", "Plains"]


def test_bamboozle_bins_two_of_four_and_its_caster_orders_the_rest(set_pool):
    """"Target player reveals the top four cards of their library. You choose
    two of those cards and put them into that player's graveyard. Put the rest
    on top of their library in any order." The pile is the target's, every
    decision is the caster's, and the two left go back on the *target's*
    library in the order the caster names."""
    game = _w1g7_duel(
        set_pool, hand0=["Bamboozle"], lib0=["Mountain"] * 3, lib1=_W1G7_PILE,
        interactive=(0,),
    )
    assert game.cast_from_hand(0, "Bamboozle", target_player_index=1).supported
    (pick,) = game.pending_choices
    assert (pick.kind, pick.player_index) == ("look_top_pick", 0)
    assert (pick.data["pile_index"], pick.data["top_count"], pick.data["remaining"]) == (1, 4, 2)
    assert any("P1 reveals Forest, Grizzly Bears, Island, Terror" in line for line in game.log)

    assert not game.resolve_pending_choice("look_top_pick", 0, keep_index=9)
    assert game.resolve_pending_choice("look_top_pick", 0, keep_index=1)  # Bears
    assert game.resolve_pending_choice("look_top_pick", 0, keep_index=2)  # Terror
    assert _w1g7_names(game.players[1].graveyard) == ["Grizzly Bears", "Terror"]

    (order,) = game.pending_choices
    assert (order.kind, order.player_index) == ("reorder_library", 0)
    assert (order.data["target_index"], order.data["top_count"]) == (1, 2)
    assert game.resolve_pending_choice(
        "reorder_library", 0, new_order=[1, 0], shuffle=False
    )
    assert _w1g7_names(game.players[1].library) == ["Island", "Forest", "Swamp", "Plains"]
    assert len(game.players[0].library) == 3 and game.players[1].hand == []
    assert not game.stack and not game.pending_choices


def test_bamboozle_over_a_short_library_takes_what_is_there(set_pool):
    """One card revealed is one card binned; none is nothing asked."""
    one = _w1g7_duel(set_pool, hand0=["Bamboozle"], lib1=["Forest"], interactive=(0,))
    one.cast_from_hand(0, "Bamboozle", target_player_index=1)
    assert one.resolve_pending_choice("look_top_pick", 0, keep_index=0)
    assert _w1g7_names(one.players[1].graveyard) == ["Forest"]
    assert not one.pending_choices and not one.stack

    none = _w1g7_duel(set_pool, hand0=["Bamboozle"], interactive=(0,))
    none.cast_from_hand(0, "Bamboozle", target_player_index=1)
    assert not none.pending_choices and not none.stack


def test_bamboozle_may_be_aimed_at_its_own_caster(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Bamboozle"], lib0=["Forest", "Island", "Swamp", "Plains", "Mountain"],
        interactive=(0,),
    )
    game.cast_from_hand(0, "Bamboozle", target_player_index=0)
    assert game.resolve_pending_choice("look_top_pick", 0, keep_index=0)
    assert game.resolve_pending_choice("look_top_pick", 0, keep_index=0)
    assert _w1g7_names(game.players[0].graveyard)[:2] == ["Forest", "Island"]
    assert game.resolve_pending_choice(
        "reorder_library", 0, new_order=[0, 1], shuffle=False
    )
    assert _w1g7_names(game.players[0].library) == ["Swamp", "Plains", "Mountain"]


def test_a_revealed_pick_checks_its_number_its_pronoun_and_its_graveyard():
    def supported(text):
        return _w1g7_compile(_w1g7_mk_card("Shell Game", "{U}", "Sorcery", text)).supported

    opening = "Target player reveals the top four cards of their library. You choose "
    assert supported(opening + "two of those cards and put them into that player's graveyard.")
    assert supported(opening + "one of those cards and put it into their graveyard.")
    assert not supported(opening + "four of those cards and put them into that player's graveyard.")
    assert not supported(opening + "two of those cards and put it into that player's graveyard.")
    assert not supported(opening + "two of those cards and put them into your graveyard.")


# --- Balancing Act: keep as many as the player with the fewest -------------------

def _w1g7_ids(game, seat, *names):
    pool = list(game.controlled_by(seat))
    found = []
    for name in names:
        permanent = next(p for p in pool if p.card.name == name)
        pool.remove(permanent)
        found.append(permanent.permanent_id)
    return found


def test_balancing_act_keeps_each_player_to_the_smallest_board_and_hand(set_pool):
    """"Each player chooses a number of permanents they control equal to the
    number of permanents controlled by the player who controls the fewest,
    then sacrifices the rest. Each player discards cards the same way." Five
    permanents against two is two kept — exactly two, of any kind, the
    player's choice — and four cards against one is three discarded."""
    game = _w1g7_duel(
        set_pool,
        hand0=["Balancing Act", "Forest", "Island", "Swamp", "Terror"],
        hand1=["Plains"],
        bf0=["Forest", "Forest", "Grizzly Bears", "Sol Ring", "Confessor"],
        bf1=["Mountain", "Grizzly Bears"], interactive=(0, 1),
    )
    assert game.cast_from_hand(0, "Balancing Act").supported
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("keep_permanents", 0),
    ], (
        "the seat with the fewest is asked nothing, and the discard waits for "
        "the keep — two prompts owed by one seat refuse each other's answers"
    )
    assert game.pending_choices[0].data["slots"] == [{"count": 2, "filter": {}}]

    assert not game.confirm_keep_permanents(
        0, _w1g7_ids(game, 0, "Forest", "Grizzly Bears", "Sol Ring")
    ), "three kept where two are allowed"
    assert not game.confirm_keep_permanents(0, _w1g7_ids(game, 0, "Sol Ring")), (
        "one kept where two must be"
    )
    assert game.confirm_keep_permanents(0, _w1g7_ids(game, 0, "Grizzly Bears", "Sol Ring"))
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Sol Ring"]

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 0)]
    assert game.pending_choices[0].data["count"] == 3
    assert not game.confirm_discard(0, [0, 1])
    assert game.confirm_discard(0, [0, 1, 2])
    assert _w1g7_names(game.players[0].hand) == ["Terror"]
    assert len(list(game.controlled_by(1))) == 2 and _w1g7_names(game.players[1].hand) == ["Plains"]
    assert not game.stack and not game.pending_choices


def test_balancing_act_against_an_empty_board_takes_everything(set_pool):
    """The fewest is none, so nobody keeps any: no choice to make, and the
    hands come down to the empty one."""
    game = _w1g7_duel(
        set_pool, hand0=["Balancing Act", "Forest"],
        bf0=["Forest", "Grizzly Bears"], interactive=(0, 1),
    )
    game.cast_from_hand(0, "Balancing Act")
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 0)]
    assert list(game.controlled_by(0)) == []
    assert game.confirm_discard(0, [0])
    assert game.players[0].hand == []


def test_balancing_act_on_a_level_table_does_nothing(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Balancing Act", "Forest"], hand1=["Island"],
        bf0=["Forest"], bf1=["Island"], interactive=(0, 1),
    )
    game.cast_from_hand(0, "Balancing Act")
    assert not game.pending_choices and not game.stack
    assert len(list(game.controlled_by(0))) == 1 and len(list(game.controlled_by(1))) == 1


def test_balancing_act_brings_the_opponent_down_to_its_casters_board(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Balancing Act"], hand1=["Plains", "Island", "Swamp"],
        bf0=["Forest"], bf1=["Mountain", "Grizzly Bears", "Sol Ring"],
        interactive=(0, 1),
    )
    game.cast_from_hand(0, "Balancing Act")
    assert game.confirm_keep_permanents(1, _w1g7_ids(game, 1, "Sol Ring"))
    assert game.confirm_discard(1, [0, 1, 2])
    assert [p.card.name for p in game.controlled_by(1)] == ["Sol Ring"]
    assert game.players[1].hand == []
    assert [p.card.name for p in game.controlled_by(0)] == ["Forest"]


def test_a_keep_sized_by_the_fewest_reads_one_noun_twice():
    """The noun is printed twice and must be one noun; and "the same way" is a
    rider on that keep and nothing else."""
    def supported(text):
        return _w1g7_compile(_w1g7_mk_card("Leveller", "{W}", "Sorcery", text)).supported

    keep = (
        "Each player chooses a number of {a} they control equal to the number "
        "of {b} controlled by the player who controls the fewest, then "
        "sacrifices the rest."
    )
    assert supported(keep.format(a="permanents", b="permanents"))
    assert supported(keep.format(a="lands", b="lands"))
    assert supported(
        keep.format(a="creatures", b="creatures")
        + " Each player discards cards the same way."
    )
    assert not supported(keep.format(a="lands", b="creatures"))
    assert not supported(
        "Each player chooses five lands they control and sacrifices the rest. "
        "Each player discards cards the same way."
    )


# --- The sheet's sorceries that compiled before this round, driven ---------------

def test_acceptable_losses_discards_at_random_as_it_is_cast_and_never_itself(
    set_pool,
):
    """"As an additional cost to cast this spell, discard a card at random."
    Paid as the spell is cast (CR 601.2h) — the spell is on the stack by then
    and is not a card in hand — by chance, whatever index is sent with the
    cast; and with no other card it cannot be cast at all."""
    def cast(seed, **named):
        _w1g7_random.seed(seed)
        game = _w1g7_duel(
            set_pool, hand0=["Acceptable Losses", "Forest", "Island", "Swamp"],
            bf1=["Craw Wurm"],
        )
        wurm = _w1g7_on_board(game, 1, "Craw Wurm")
        assert game.cast_from_hand(
            0, "Acceptable Losses", target_permanent_ids=[wurm.permanent_id], **named
        ).supported
        _w1g7_settle(game)
        assert wurm.damage_marked == 5
        return [n for n in _w1g7_names(game.players[0].graveyard) if n != "Acceptable Losses"]

    assert cast(3) == cast(3), "the seeded RNG picks"
    assert {tuple(cast(seed)) for seed in range(20)} == {("Forest",), ("Island",), ("Swamp",)}
    assert {tuple(cast(seed, cost_hand_index=3)) for seed in range(20)} == {
        ("Forest",), ("Island",), ("Swamp",),
    }, "naming a card does not choose a random discard"

    alone = _w1g7_duel(set_pool, hand0=["Acceptable Losses"], bf1=["Grizzly Bears"])
    bears = _w1g7_on_board(alone, 1, "Grizzly Bears")
    refused = alone.cast_from_hand(
        0, "Acceptable Losses", target_permanent_ids=[bears.permanent_id]
    )
    assert not refused.supported and "additional cost" in refused.details
    assert _w1g7_names(alone.players[0].hand) == ["Acceptable Losses"]


def test_careful_study_draws_two_and_then_its_caster_chooses_two(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Careful Study", "Forest"],
        lib0=["Island", "Swamp", "Plains"], interactive=(0,),
    )
    assert game.cast_from_hand(0, "Careful Study").supported
    assert _w1g7_names(game.players[0].hand) == ["Forest", "Island", "Swamp"]
    assert not game.confirm_discard(0, [0])
    assert game.confirm_discard(0, [0, 2])
    assert _w1g7_names(game.players[0].hand) == ["Island"]
    assert len(game.players[0].library) == 1


def test_concentrate_draws_three(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Concentrate"], lib0=["Island", "Swamp", "Plains", "Forest"],
    )
    game.cast_from_hand(0, "Concentrate")
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].hand) == ["Island", "Swamp", "Plains"]

# ==== end W1G7 ======================================================
