"""Judgment sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

import pytest as _w1g2_pytest

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


@_w1g2_pytest.mark.parametrize(
    ("graveyard", "survives", "damage", "counters"),
    [(0, True, 0, 2), (7, False, 6, 2)],
    ids=["four-damage-prevented", "threshold-six-unpreventable"],
)
def test_w1g2_lightning_surge_against_a_phantom(
    set_pool, catalog_by_name, graveyard, survives, damage, counters,
):
    """Lightning Surge, from the drive list, against Phantom Centaur (3
    counters, 2/0). Without threshold its 4 damage is prevented for a counter.
    With seven cards in its caster's graveyard it deals 6 "and the damage can't
    be prevented": the 6 is marked, and the Phantom still pays its counter
    (2022-12-08: "the damage is dealt and a +1/+1 counter is removed",
    CR 615.12) — so a 4/1 takes 6 and dies."""
    jud = set_pool("JUD")
    island = catalog_by_name["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="Alice", library=[island] * 5),
        _W1G2PlayerState(name="Bob", library=[island] * 5,
                         graveyard=[island] * graveyard),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game.current_turn_phase = "main1"
    centaur = _W1G2Permanent(card=jud["Phantom Centaur"])
    game._put_permanent_onto_battlefield(0, centaur, None)
    _w1g2_resolve_stack(game)
    game.players[1].hand.append(jud["Lightning Surge"])
    result = game.cast_from_hand(
        1, "Lightning Surge", target_player_index=0,
        target_permanent_ids=[centaur.permanent_id],
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    damage_marked = centaur.damage_marked
    game._settle()

    assert game.is_on_battlefield(centaur) is survives
    assert damage_marked == damage
    assert int(centaur.metadata.get("plus_counters", 0)) == counters

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
#
# Rats' Feast (supported on arrival, driven here): "Exile X target cards from a
# single graveyard." The X cards are targets announced with the spell
# (CR 601.2c), all in one pile, and a card gone in response is not replaced
# (CR 608.2b).

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from engine.stack_targets import chosen_targets as _w1g3_chosen_targets
from tests.helpers import resolve_stack as _w1g3_resolve

_W1G3_THEIRS = ("Swamp", "Hill Giant", "Terror", "Craw Wurm")


def _w1g3_feast_game(set_pool):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P0", hand=[jud["Rats' Feast"]], graveyard=[lea["Grizzly Bears"]],
            library=[lea["Swamp"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[lea[name] for name in _W1G3_THEIRS],
            library=[lea["Island"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def test_w1g3_rats_feast_names_x_cards_of_one_pile_and_does_not_replace_a_lost_one(set_pool):
    game = _w1g3_feast_game(set_pool)
    spec = game.cast_target_spec(0, set_pool("JUD")["Rats' Feast"])
    assert spec["single_graveyard"] and spec["x_targets"]
    assert {t["seat"] for t in spec["valid_targets"]} == {0, 1}

    assert game.queue_from_hand(
        0, "Rats' Feast", x_value=2, target_player_index=1, target_permanent_index=[1, 3],
    ).supported
    named = _w1g3_chosen_targets(game, game.stack[-1])
    assert [(t.stamp.seat, t.stamp.card.name) for t in named] == [
        (1, "Hill Giant"), (1, "Craw Wurm"),
    ]
    victim = game.players[1]
    victim.hand.append(victim.graveyard.pop(1))            # the Giant, in response
    _w1g3_resolve(game)

    assert [c.name for c in victim.exile] == ["Craw Wurm"]
    assert [c.name for c in victim.graveyard] == ["Swamp", "Terror"]
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears", "Rats' Feast"]


def test_w1g3_rats_feast_names_exactly_x_and_x_zero_names_none(set_pool):
    game = _w1g3_feast_game(set_pool)
    assert not game.queue_from_hand(
        0, "Rats' Feast", x_value=2, target_player_index=1, target_permanent_index=[1],
    ).supported
    assert not game.queue_from_hand(
        0, "Rats' Feast", x_value=1, target_player_index=1, target_permanent_index=[1, 2],
    ).supported
    assert game.stack == []
    assert game.queue_from_hand(0, "Rats' Feast", x_value=0).supported
    _w1g3_resolve(game)
    assert game.players[1].exile == [] and len(game.players[1].graveyard) == 4

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
#
# "Any player may have <this> deal N damage to them. If no one does, <effect>."
# CR 118.12a's toll over a set of seats, printed the long way round: the
# ``unless_player_pays`` chain with a *deed* for its price
# (``ast.UnlessPlayerPays.action``). Each seat is asked in turn from the active
# player (CR 101.4); the first that takes the damage ends the chain; the effect
# happens only when nobody does.

import pytest as _w1g5_pytest  # noqa: E402

from tests.sets import jud_w1g5_helpers as _w1g5  # noqa: E402


def _w1g5_cast(game, name, **targets):
    result = game.cast_from_hand(0, name, **targets)
    assert result.supported, result.details
    game.resolve_top_of_stack(pause_for_choices=True)
    return result


def test_w1g5_browbeat_asks_each_seat_from_the_active_player_and_the_taker_ends_it(set_pool):
    """The caster is asked first and declines; the opponent takes the five.
    Nobody draws: CR 118.12a's "if no one does" is false."""
    game = _w1g5.table(set_pool, hands=(["Browbeat"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5_cast(game, "Browbeat", target_player_index=0)

    assert _w1g5.answer_offers(game, {1: True}) == [0, 1]
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [20, 15]
    assert game.players[0].hand == []
    assert "Browbeat dealt 5 damage to P2" in game.log


def test_w1g5_browbeat_nobody_taking_it_draws_the_target_not_the_last_seat_asked(set_pool):
    """The unpaid branch reads the target the spell chose — the opponent here —
    and not the seat the last link of the chain was aimed at."""
    game = _w1g5.table(set_pool, hands=(["Browbeat"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5_cast(game, "Browbeat", target_player_index=1)

    assert _w1g5.answer_offers(game, {}) == [0, 1]
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [20, 20]
    assert [len(player.hand) for player in game.players] == [0, 3]


def test_w1g5_the_caster_may_take_browbeats_damage_and_nobody_else_is_asked(set_pool):
    game = _w1g5.table(set_pool, hands=(["Browbeat"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5_cast(game, "Browbeat", target_player_index=1)

    assert _w1g5.answer_offers(game, {0: True}) == [0]
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [15, 20]
    assert [len(player.hand) for player in game.players] == [0, 0]


def test_w1g5_browbeat_at_a_three_seat_table_asks_in_turn_order_from_the_active_player(set_pool):
    """Seat 1 is active: it is asked first, then seat 2, then the caster."""
    game = _w1g5.table(
        set_pool, hands=([], ["Browbeat"], []), interactive=(0, 1, 2),
    )
    game.start_turn(1)
    result = game.cast_from_hand(1, "Browbeat", target_player_index=1)
    assert result.supported, result.details
    held = len(game.players[1].hand)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g5.answer_offers(game, {0: True}) == [1, 2, 0]
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [15, 20, 20]
    assert len(game.players[1].hand) == held


def test_w1g5_book_burning_mills_its_target_when_nobody_takes_six(set_pool):
    game = _w1g5.table(set_pool, hands=(["Book Burning"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5_cast(game, "Book Burning", target_player_index=1)

    _w1g5.answer_offers(game, {})
    _w1g5.settle(game)

    assert [len(player.library) for player in game.players] == [20, 14]
    assert len(game.players[1].graveyard) == 6


def test_w1g5_book_burning_taken_burns_the_taker_and_mills_nobody(set_pool):
    game = _w1g5.table(set_pool, hands=(["Book Burning"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5_cast(game, "Book Burning", target_player_index=1)

    _w1g5.answer_offers(game, {1: True})
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [20, 14]
    assert [len(player.library) for player in game.players] == [20, 20]


def test_w1g5_breaking_point_destroys_every_creature_past_a_regeneration_shield(set_pool):
    """"Creatures destroyed this way can't be regenerated" rides the unpaid
    branch: a Drudge Skeletons with a shield up still goes."""
    game = _w1g5.table(set_pool, hands=(["Breaking Point"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5.put(game, set_pool, 0, "Grizzly Bears")
    skeletons = _w1g5.put(game, set_pool, 1, "Drudge Skeletons")
    shield = game.activate_permanent_ability(1, "Drudge Skeletons")
    assert shield.supported, shield.details
    _w1g5.settle(game)
    assert skeletons.regeneration_shield == 1

    _w1g5_cast(game, "Breaking Point")
    _w1g5.answer_offers(game, {})
    _w1g5.settle(game)

    assert _w1g5.names(game, 0) == [] and _w1g5.names(game, 1) == []
    assert "Drudge Skeletons regenerated" not in game.log


def test_w1g5_breaking_point_taken_spares_the_board(set_pool):
    game = _w1g5.table(set_pool, hands=(["Breaking Point"], []), interactive=(0, 1))
    game.start_turn(0)
    _w1g5.put(game, set_pool, 1, "Grizzly Bears")
    _w1g5_cast(game, "Breaking Point")

    _w1g5.answer_offers(game, {1: True})
    _w1g5.settle(game)

    assert [player.life for player in game.players] == [20, 14]
    assert _w1g5.names(game, 1) == ["Grizzly Bears"]


def _w1g5_headless(set_pool, name, *, theirs=(), mine=(), their_life=20, target=None):
    """*name* cast by seat 0 with nobody interactive — every link answered by
    the stated policy — and the game settled."""
    game = _w1g5.table(set_pool, hands=([name], []))
    game.players[1].life = their_life
    for seat, board in ((0, mine), (1, theirs)):
        for creature in board:
            _w1g5.put(game, set_pool, seat, creature)
    game.start_turn(0)
    targets = {} if target is None else {"target_player_index": target}
    result = game.cast_from_hand(0, name, **targets)
    assert result.supported, result.details
    _w1g5.settle(game)
    return game


@_w1g5_pytest.mark.parametrize(
    "theirs, takes_six",
    [
        ((), False),                                     # nothing to save
        (("Craw Wurm", "Hill Giant", "Serra Angel"), True),  # worth more than 6
    ],
)
def test_w1g5_a_seat_nobody_asks_weighs_breaking_points_six_against_its_own_creatures(
    set_pool, theirs, takes_six
):
    """"Pay tolls" took the six every time — a seat with an empty board paid
    6 life to save nothing. The decline of a link is priced as the unpaid
    branch for *this* seat: its own creatures the sweep would take."""
    game = _w1g5_headless(set_pool, "Breaking Point", theirs=theirs)

    assert game.players[1].life == (14 if takes_six else 20)
    assert _w1g5.names(game, 1) == (sorted(theirs) if takes_six else [])


def test_w1g5_the_caster_pays_breaking_point_to_keep_a_bigger_board(set_pool):
    """The caster is asked first (CR 101.4) and is a seat like any other here:
    with more to lose than six life, it takes the six itself."""
    game = _w1g5_headless(
        set_pool, "Breaking Point",
        mine=("Craw Wurm", "Serra Angel"), theirs=("Grizzly Bears",),
    )

    assert [player.life for player in game.players] == [14, 20]
    assert _w1g5.names(game, 0) == ["Craw Wurm", "Serra Angel"]


def test_w1g5_a_seat_nobody_asks_lets_book_burning_mill_it(set_pool):
    """Six cards off the top of a library are priced far below six life."""
    game = _w1g5_headless(set_pool, "Book Burning", target=1)

    assert game.players[1].life == 20
    assert len(game.players[1].library) == 14


@_w1g5_pytest.mark.parametrize("life, takes_five", [(20, True), (5, False)])
def test_w1g5_a_seat_nobody_asks_takes_browbeats_five_but_never_with_the_game(
    set_pool, life, takes_five
):
    """Three cards to somebody else is a trade nothing here prices, so the
    standing policy pays — and a price that kills is never paid for a penalty
    nobody can price."""
    game = _w1g5_headless(set_pool, "Browbeat", their_life=life, target=0)

    assert game.players[1].life == (life - 5 if takes_five else life)
    assert len(game.players[0].hand) == (0 if takes_five else 3)


@_w1g5_pytest.mark.parametrize("name", ["Browbeat", "Book Burning", "Breaking Point"])
def test_w1g5_the_offer_holds_the_spell_on_the_stack_until_it_is_answered(set_pool, name):
    """CR 608.2: the spell is still resolving while a seat is being asked, so
    it is on the stack and the caster does not have priority to do anything
    else in between."""
    game = _w1g5.table(set_pool, hands=([name], []), interactive=(0, 1))
    game.start_turn(0)
    targets = {} if name == "Breaking Point" else {"target_player_index": 1}
    _w1g5_cast(game, name, **targets)

    assert _w1g5.owed(game) == [0]
    assert [item.card.name for item in game.stack] == [name]

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

import pytest as _w1g10_pytest

from engine import Game as _W1G10Game, PlayerState as _W1G10PlayerState
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_table(set_pool, *, library, graveyard=(), hand=(), interactive=()):
    """Seat 0 on its first main phase with the named cards in each zone."""
    pool = {**set_pool("LEA"), **set_pool("WTH"), **set_pool("JUD")}
    game = _W1G10Game(players=[
        _W1G10PlayerState(
            name="P0", life=20,
            library=[pool[name] for name in library],
            graveyard=[pool[name] for name in graveyard],
            hand=[pool[name] for name in hand],
        ),
        _W1G10PlayerState(name="P1", life=20, library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g10_names(cards):
    return sorted(card.name for card in cards)


def test_w1g10_morality_shift_exchanges_graveyard_and_library(set_pool):
    """"Exchange your graveyard and library. Then shuffle your library." The
    old graveyard is the new library and the old library the new graveyard —
    both piles taken before a card moves (CR 701.12f), so nothing comes back
    the way it went. The spell itself reaches the graveyard afterwards, as a
    resolved sorcery does (CR 608.2n)."""
    game = _w1g10_table(
        set_pool,
        library=["Island", "Forest", "Grizzly Bears"],
        graveyard=["Lightning Bolt", "Hill Giant"],
        hand=["Morality Shift"],
    )
    assert game.queue_from_hand(0, "Morality Shift").supported
    _w1g10_resolve_stack(game)

    assert _w1g10_names(game.players[0].library) == ["Hill Giant", "Lightning Bolt"]
    assert _w1g10_names(game.players[0].graveyard) == [
        "Forest", "Grizzly Bears", "Island", "Morality Shift",
    ]
    assert game.players[0].graveyard[-1].name == "Morality Shift"
    assert any("exchanged their graveyard (2 card(s))" in line for line in game.log)
    assert any("shuffled their library" in line for line in game.log)


@_w1g10_pytest.mark.parametrize(
    "library,graveyard",
    [(["Island", "Forest"], []), ([], ["Hill Giant", "Lightning Bolt"])],
    ids=["empty graveyard", "empty library"],
)
def test_w1g10_morality_shift_works_with_an_empty_zone(set_pool, library, graveyard):
    """The ruling (2004-10-04): "This spell works even if your graveyard or
    library is empty." CR 701.12f — the zones are still exchanged."""
    game = _w1g10_table(
        set_pool, library=library, graveyard=graveyard, hand=["Morality Shift"],
    )
    assert game.queue_from_hand(0, "Morality Shift").supported
    _w1g10_resolve_stack(game)

    assert _w1g10_names(game.players[0].library) == sorted(graveyard)
    assert _w1g10_names(game.players[0].graveyard) == sorted(
        library + ["Morality Shift"]
    )


def test_w1g10_morality_shift_puts_the_library_into_the_graveyard_from_the_library(set_pool):
    """Each old library card goes to the graveyard **from the library**, so a
    card that watches for exactly that move sees it: Gaea's Blessing ("When
    this card is put into your graveyard from your library, shuffle your
    graveyard into your library") triggers and shuffles the old library back
    in. The trigger goes on the stack only once Morality Shift has finished
    resolving and is in the graveyard itself (CR 608.2n, 603.3), so the spell
    is shuffled in with the rest and the graveyard ends empty."""
    game = _w1g10_table(
        set_pool,
        library=["Island", "Gaea's Blessing", "Forest"],
        graveyard=["Hill Giant"],
        hand=["Morality Shift"],
    )
    assert game.queue_from_hand(0, "Morality Shift").supported
    _w1g10_resolve_stack(game)

    assert any("Gaea's Blessing" in line for line in game.log)
    assert _w1g10_names(game.players[0].graveyard) == []
    assert _w1g10_names(game.players[0].library) == [
        "Forest", "Gaea's Blessing", "Hill Giant", "Island", "Morality Shift",
    ]


_W1G10_SPECULATION_LIBRARY = [
    "Island", "Firebolt", "Lightning Bolt", "Deep Analysis", "Moment's Peace",
    "Ray of Revelation",
]


def _w1g10_speculation_table(set_pool, *, interactive=(0,)):
    pool = {**set_pool("LEA"), **set_pool("ODY"), **set_pool("TOR"), **set_pool("JUD")}
    game = _W1G10Game(players=[
        _W1G10PlayerState(
            name="P0", life=20, library=[pool["Island"]] * 5,
            hand=[pool["Quiet Speculation"]],
        ),
        _W1G10PlayerState(
            name="P1", life=20,
            library=[pool[name] for name in _W1G10_SPECULATION_LIBRARY],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def test_w1g10_quiet_speculation_bins_up_to_three_flashback_cards(set_pool):
    """"Search target player's library for up to three cards with flashback
    and put them into that player's graveyard. Then the player shuffles." The
    target is chosen as the spell is cast (CR 601.2c); a card without
    flashback is no find; two of the four flashback cards are a legal answer
    ("up to"); they land in the **searched** player's graveyard (CR 404.1), and
    the rest of that library is still there."""
    game = _w1g10_speculation_table(set_pool)
    cast = game.queue_from_hand(0, "Quiet Speculation", target_player_index=1)
    assert cast.supported, cast.details
    game.resolve_top_of_stack()

    prompt = game.pending_search_library
    assert prompt["zone_seat"] == 1 and prompt["count"] == 3 and prompt["up_to"]
    assert not game.confirm_search_library_picks(
        0, [{"zone": "library", "index": 0}]
    ), "an Island has no flashback"
    assert not game.confirm_search_library_picks(
        0, [{"zone": "library", "index": 2}]
    ), "nor does Lightning Bolt"
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": 1}, {"zone": "library", "index": 5}]
    )
    _w1g10_resolve_stack(game)

    assert _w1g10_names(game.players[1].graveyard) == ["Firebolt", "Ray of Revelation"]
    assert _w1g10_names(game.players[1].library) == [
        "Deep Analysis", "Island", "Lightning Bolt", "Moment's Peace",
    ]
    assert _w1g10_names(game.players[0].graveyard) == ["Quiet Speculation"]
    assert game.pending_choices == []


def test_w1g10_quiet_speculation_headless_takes_three_flashback_cards(set_pool):
    """A seat nobody asks answers through the AI's search policy, which reads
    the same predicate: three finds, every one a card with flashback."""
    game = _w1g10_speculation_table(set_pool, interactive=())
    assert game.queue_from_hand(0, "Quiet Speculation", target_player_index=1).supported
    _w1g10_resolve_stack(game)
    game.auto_resolve_pending_choices()

    binned = _w1g10_names(game.players[1].graveyard)
    assert len(binned) == 3
    assert set(binned) <= {"Firebolt", "Deep Analysis", "Moment's Peace", "Ray of Revelation"}
    assert "Island" in _w1g10_names(game.players[1].library)
    assert "Lightning Bolt" in _w1g10_names(game.players[1].library)

# ==== end W1G10 ======================================================
