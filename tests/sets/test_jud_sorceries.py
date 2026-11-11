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
        0, "Rats' Feast", x_value=2, target_player_index=1, target_graveyard_indices=[1, 3],
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
        0, "Rats' Feast", x_value=2, target_player_index=1, target_graveyard_indices=[1],
    ).supported
    assert not game.queue_from_hand(
        0, "Rats' Feast", x_value=1, target_player_index=1, target_graveyard_indices=[1, 2],
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
#
# The Wishes: "You may reveal a <type> card you own from outside the game and
# put it into your hand. Exile <this>." Outside the game is a player's
# sideboard (CR 400.11a, 100.4 — the sanctioned reading of the 2009-10-01
# ruling; this engine has no collection), and the card brought in stays in the
# game (CR 400.11b). The "you may" is an offer (optional_pay) made only when a
# card qualifies; the pick is an ``outside_game_pick`` prompt over the
# caster's own sideboard, checked against the printed type.

import pytest as _w1g6_pytest  # noqa: E402

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState  # noqa: E402
from tests.helpers import resolve_stack as _w1g6_resolve_stack  # noqa: E402

_W1G6_SIDEBOARD = (
    "Lightning Bolt", "Stone Rain", "Shivan Dragon", "Forest", "Sol Ring",
    "Wild Growth",
)


def _w1g6_table(set_pool, wish, sideboard=_W1G6_SIDEBOARD, *, interactive=False, life=20):
    """Seat 0 holds *wish* with *sideboard* outside the game, its turn begun."""
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="Alice", hand=[set_pool("JUD")[wish]], life=life,
            library=[lea["Island"]] * 5, sideboard=[lea[name] for name in sideboard],
        ),
        _W1G6PlayerState(name="Bob", library=[lea["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(0)
    return game


def _w1g6_cast_headless(game, wish):
    """Cast and resolve with nobody asked: the offer and the pick are answered
    by the registry's defaults, as an AI seat's are."""
    result = game.cast_from_hand(0, wish)
    assert result.supported, result.details
    _w1g6_resolve_stack(game)
    game.auto_resolve_pending_choices()


def _w1g6_names(zone):
    return [card.name for card in zone]


@_w1g6_pytest.mark.parametrize(
    "wish, sideboard, fetched",
    [
        ("Burning Wish", ("Lightning Bolt", "Stone Rain", "Shivan Dragon"), "Stone Rain"),
        ("Golden Wish", ("Lightning Bolt", "Sol Ring", "Shivan Dragon"), "Sol Ring"),
        ("Golden Wish", ("Stone Rain", "Wild Growth", "Forest"), "Wild Growth"),
        ("Living Wish", ("Lightning Bolt", "Stone Rain", "Forest"), "Forest"),
        ("Living Wish", ("Lightning Bolt", "Sol Ring", "Shivan Dragon"), "Shivan Dragon"),
    ],
)
def test_w1g6_a_wish_brings_in_only_a_card_of_its_printed_type_and_exiles_itself(
    set_pool, wish, sideboard, fetched,
):
    """Each sideboard holds exactly one card the printed type admits, so a
    pick of anything else would be a wish fetching what it does not name. The
    find is revealed (CR 701.20a): the log names it and the reveal feed carries
    it. The Wish is exiled, not binned (CR 608.2n's move is replaced by its
    own last instruction)."""
    game = _w1g6_table(set_pool, wish, sideboard)
    _w1g6_cast_headless(game, wish)
    alice = game.players[0]

    assert _w1g6_names(alice.hand) == [fetched]
    assert sorted(_w1g6_names(alice.sideboard)) == sorted(
        name for name in sideboard if name != fetched
    )
    assert _w1g6_names(alice.exile) == [wish] and alice.graveyard == []
    assert (
        f"Alice revealed {fetched} from outside the game and put it into "
        f"their hand ({wish})"
    ) in game.log
    assert game.reveal_events[-1]["cards"] == [fetched]


def test_w1g6_living_wish_offers_a_creature_or_a_land_and_nothing_else(set_pool):
    """The person is offered exactly the union the card prints — the two
    candidates, by sideboard position — and the pick list is the engine's own,
    so an answer naming the Bolt is refused with the prompt kept."""
    game = _w1g6_table(set_pool, "Living Wish", interactive=True)
    assert game.cast_from_hand(0, "Living Wish").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.resolve_pending_choice("optional_pay", 0, accept=True, option=None)

    (pick,) = game.pending_choices_of("outside_game_pick")
    sideboard = game.players[0].sideboard
    assert [sideboard[i].name for i in game.live_outside_game_picks(pick)] == [
        "Shivan Dragon", "Forest",
    ]
    assert not game.confirm_outside_game_pick(0, 0)          # Lightning Bolt
    assert game.pending_choices_of("outside_game_pick")
    assert game.confirm_outside_game_pick(0, 3)              # Forest
    _w1g6_resolve_stack(game)
    assert _w1g6_names(game.players[0].hand) == ["Forest"]
    assert _w1g6_names(game.players[0].exile) == ["Living Wish"]


def test_w1g6_burning_wish_waits_on_the_stack_for_the_offer_and_the_pick(set_pool):
    """CR 608.2: the spell is still resolving while its caster is asked, so it
    is on the stack, unexiled, through both questions — the "you may" and the
    pick — and is exiled once the last is answered. The pick is mandatory once
    the offer was taken: a decline is refused with the prompt kept."""
    game = _w1g6_table(set_pool, "Burning Wish", interactive=True)
    assert game.cast_from_hand(0, "Burning Wish").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert _w1g6_names(item.card for item in game.stack) == ["Burning Wish"]
    assert game.players[0].exile == []

    assert game.resolve_pending_choice("optional_pay", 0, accept=True, option=None)
    assert [c.kind for c in game.pending_choices] == ["outside_game_pick"]
    assert _w1g6_names(item.card for item in game.stack) == ["Burning Wish"]
    assert not game.confirm_outside_game_pick(0, None)

    assert game.confirm_outside_game_pick(0, 1)              # Stone Rain
    _w1g6_resolve_stack(game)
    assert game.stack == [] and game.pending_choices == []
    assert _w1g6_names(game.players[0].hand) == ["Stone Rain"]
    assert _w1g6_names(game.players[0].exile) == ["Burning Wish"]


def test_w1g6_declining_the_offer_brings_nothing_in_and_still_exiles_the_wish(set_pool):
    game = _w1g6_table(set_pool, "Burning Wish", interactive=True)
    assert game.cast_from_hand(0, "Burning Wish").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.resolve_pending_choice("optional_pay", 0, accept=False, option=None)
    _w1g6_resolve_stack(game)

    assert game.players[0].hand == []
    assert len(game.players[0].sideboard) == len(_W1G6_SIDEBOARD)
    assert _w1g6_names(game.players[0].exile) == ["Burning Wish"]
    assert game.pending_choices == []


def test_w1g6_nothing_to_wish_for_is_an_offer_never_made(set_pool):
    """A sideboard with no sorcery (and a sorcery in *exile*, which is in the
    game and cannot be acquired — 2009-10-01) makes no offer at all, so an
    interactive seat is not asked a question whose only honest answer is no;
    the Wish exiles itself and the log says why nothing came."""
    game = _w1g6_table(
        set_pool, "Burning Wish", ("Lightning Bolt", "Shivan Dragon"), interactive=True,
    )
    game.players[0].exile.append(set_pool("LEA")["Stone Rain"])
    assert game.cast_from_hand(0, "Burning Wish").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    _w1g6_resolve_stack(game)

    assert game.pending_choices == []
    assert game.players[0].hand == []
    assert _w1g6_names(game.players[0].exile) == ["Stone Rain", "Burning Wish"]
    assert _w1g6_names(game.players[0].sideboard) == ["Lightning Bolt", "Shivan Dragon"]


@_w1g6_pytest.mark.parametrize("for_ante", [False, True])
def test_w1g6_an_ante_card_outside_the_game_comes_in_only_in_a_game_for_ante(
    set_pool, for_ante,
):
    """CR 407.3: when not playing for ante, the ante cards "can't be brought
    into the game from outside the game". Contract from Below is a sorcery, so
    Burning Wish's phrase admits it — the reader Ring of Ma'rûf already asks is
    what keeps it out."""
    game = _w1g6_table(
        set_pool, "Burning Wish", ("Contract from Below", "Stone Rain"), interactive=True,
    )
    game.playing_for_ante = for_ante
    assert game.cast_from_hand(0, "Burning Wish").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.resolve_pending_choice("optional_pay", 0, accept=True, option=None)

    (pick,) = game.pending_choices_of("outside_game_pick")
    offered = [game.players[0].sideboard[i].name for i in game.live_outside_game_picks(pick)]
    assert offered == (["Contract from Below", "Stone Rain"] if for_ante else ["Stone Rain"])
    assert game.confirm_outside_game_pick(0, 0) is for_ante


@_w1g6_pytest.mark.parametrize("life, after", [(20, 10), (15, 7), (1, 0)])
def test_w1g6_death_wish_loses_half_its_casters_life_rounded_up_even_finding_nothing(
    set_pool, life, after,
):
    """"You lose half your life, rounded up" — 15 loses 8 — and the 2007-05-01
    ruling: "If you fail to find something, you still lose half your life,
    rounded up." An empty sideboard finds nothing and the life is lost all the
    same; the card is exiled."""
    game = _w1g6_table(set_pool, "Death Wish", (), life=life)
    _w1g6_cast_headless(game, "Death Wish")

    assert game.players[0].life == after
    assert game.players[0].hand == []
    assert _w1g6_names(game.players[0].exile) == ["Death Wish"]


def test_w1g6_death_wish_takes_any_card_and_does_not_reveal_it(set_pool):
    """No type, so every card outside the game is offered; no "reveal", so the
    find is never named in the log every seat reads, nor sent to the reveal
    feed — the hand it goes to is hidden (CR 400.2)."""
    game = _w1g6_table(set_pool, "Death Wish", interactive=True)
    assert game.cast_from_hand(0, "Death Wish").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.resolve_pending_choice("optional_pay", 0, accept=True, option=None)
    (pick,) = game.pending_choices_of("outside_game_pick")
    assert game.live_outside_game_picks(pick) == list(range(len(_W1G6_SIDEBOARD)))

    assert game.confirm_outside_game_pick(0, 2)              # Shivan Dragon
    _w1g6_resolve_stack(game)
    assert _w1g6_names(game.players[0].hand) == ["Shivan Dragon"]
    assert game.players[0].life == 10
    assert game.reveal_events == []
    assert not any("Shivan Dragon" in line for line in game.log)
    assert (
        "Alice put a card they own from outside the game into their hand "
        "(Death Wish)"
    ) in game.log


def test_w1g6_the_card_brought_in_is_in_the_game_and_can_be_cast(set_pool):
    """CR 400.11b: the card stays in the game. Golden Wish fetches Sol Ring and
    the Ring is cast from the hand like any other card."""
    game = _w1g6_table(set_pool, "Golden Wish", ("Sol Ring", "Lightning Bolt"))
    _w1g6_cast_headless(game, "Golden Wish")
    assert _w1g6_names(game.players[0].hand) == ["Sol Ring"]

    assert game.cast_from_hand(0, "Sol Ring").supported
    _w1g6_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Sol Ring"]

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
#
# Threshold "instead" sorceries: the second paragraph replaces the first when
# seven or more cards are in the caster's graveyard as the spell resolves
# (CR 608.2c), and exactly one of the two ever happens.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.oracle import compile_card_oracle as _w1g7_compile
from engine.targeting import derive_cast_spec as _w1g7_derive_cast_spec
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_table(set_pool, catalog_by_name, graveyard=()):
    """Two seats; seat 0's graveyard holds *graveyard* (card names), mana off."""
    jud = set_pool("JUD")

    def card(name):
        return jud[name] if name in jud else catalog_by_name[name]

    island = catalog_by_name["Island"]
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="Alice", library=[island] * 10,
                         graveyard=[card(name) for name in graveyard]),
        _W1G7PlayerState(name="Bob", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    game._w1g7_card = card
    return game


def _w1g7_bears(game, seat):
    return [p for p in game.controlled_by(seat) if p.card.name == "Bear Token"]


@_w1g7_pytest.mark.parametrize(("others", "bears"), [(6, 2), (7, 4)])
def test_w1g7_grizzly_fate_makes_four_bears_only_at_threshold(
    set_pool, catalog_by_name, others, bears,
):
    """Two 2/2 green Bears, or four instead with seven cards in the graveyard
    — never six: the pair is one effect."""
    game = _w1g7_table(set_pool, catalog_by_name, ["Island"] * others)
    game.players[0].hand.append(game._w1g7_card("Grizzly Fate"))
    assert game.cast_from_hand(0, "Grizzly Fate").supported
    _w1g7_resolve_stack(game)

    made = _w1g7_bears(game, 0)
    assert len(made) == bears
    assert all(
        (p.effective_power, p.effective_toughness) == (2, 2) for p in made
    )
    assert _w1g7_bears(game, 1) == []
    assert [c.name for c in game.players[0].graveyard][-1] == "Grizzly Fate"


def test_w1g7_grizzly_fate_flashed_back_does_not_count_itself(
    set_pool, catalog_by_name,
):
    """Ruling 2013-04-15: "At the time this spell is resolving, it is on the
    stack and not in the graveyard. This means that you should not count this
    card when determining whether the Threshold effect occurs." Six other
    cards plus Grizzly Fate is seven before the flashback cast and six while it
    resolves: two Bears, and the card is exiled (CR 702.34a)."""
    game = _w1g7_table(
        set_pool, catalog_by_name, ["Island"] * 6 + ["Grizzly Fate"]
    )
    result = game.cast_from_hand(0, "Grizzly Fate", from_zone="graveyard")
    assert result.supported, result.details
    _w1g7_resolve_stack(game)

    assert len(_w1g7_bears(game, 0)) == 2
    assert [c.name for c in game.players[0].exile] == ["Grizzly Fate"]
    assert len(game.players[0].graveyard) == 6


@_w1g7_pytest.mark.parametrize(
    ("others", "to_hand", "to_battlefield"), [(4, True, False), (5, False, True)],
)
def test_w1g7_stitch_together_returns_to_hand_or_to_the_battlefield(
    set_pool, catalog_by_name, others, to_hand, to_battlefield,
):
    """The target creature card counts toward the seven: with it, a Hill Giant
    and four Islands (six) it goes to the hand, with five Islands (seven) it
    enters the battlefield instead — the one card the spell targeted either
    way, and never the Giant."""
    game = _w1g7_table(
        set_pool, catalog_by_name,
        ["Island"] * others + ["Hill Giant", "Grizzly Bears"],
    )
    caster = game.players[0]
    stitch = game._w1g7_card("Stitch Together")
    caster.hand.append(stitch)
    bears_slot = len(caster.graveyard) - 1
    offered = {t["name"] for t in game.cast_target_spec(0, stitch)["valid_targets"]}
    assert offered == {"Hill Giant", "Grizzly Bears"}
    assert game.cast_from_hand(
        0, "Stitch Together", target_player_index=0,
        target_graveyard_indices=[bears_slot],
    ).supported
    _w1g7_resolve_stack(game)

    assert ("Grizzly Bears" in [c.name for c in caster.hand]) is to_hand
    on_board = [p.card.name for p in game.controlled_by(0)]
    assert ("Grizzly Bears" in on_board) is to_battlefield
    assert "Hill Giant" in [c.name for c in caster.graveyard]
    assert "Hill Giant" not in on_board


def test_w1g7_stitch_together_with_its_target_gone_does_nothing(
    set_pool, catalog_by_name,
):
    """CR 608.2b: its one target left the graveyard in response, so the spell
    does not resolve — no other creature card is returned in its place, by
    either arm."""
    game = _w1g7_table(
        set_pool, catalog_by_name, ["Island"] * 6 + ["Hill Giant", "Grizzly Bears"],
    )
    caster = game.players[0]
    caster.hand.append(game._w1g7_card("Stitch Together"))
    assert game.queue_from_hand(
        0, "Stitch Together", target_player_index=0,
        target_graveyard_indices=[len(caster.graveyard) - 1],
    ).supported
    caster.exile.append(caster.graveyard.pop())     # the Bears, in response
    _w1g7_resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(0)] == []
    assert "Hill Giant" in [c.name for c in caster.graveyard]
    assert "Hill Giant" not in [c.name for c in caster.hand]


def test_w1g7_threshold_sorceries_pickers_name_what_the_cards_print(set_pool):
    """Stitch Together names a creature card in its caster's own graveyard;
    Grizzly Fate names nothing."""
    jud = set_pool("JUD")
    stitch, fate = jud["Stitch Together"], jud["Grizzly Fate"]
    assert _w1g7_derive_cast_spec(stitch, _w1g7_compile(stitch)) == {
        "kind": "graveyard_creature", "own_graveyard_only": True,
    }
    assert _w1g7_derive_cast_spec(fate, _w1g7_compile(fate)) is None


@_w1g7_pytest.mark.parametrize(("others", "swept"), [(6, False), (7, True)])
def test_w1g7_swirling_sandstorm_needs_threshold_and_spares_fliers(
    set_pool, catalog_by_name, others, swept,
):
    """Drive list. Ruling 2004-10-04: "This card does nothing if you don't
    have seven cards in your graveyard when it resolves." With seven, 5 damage
    to each creature without flying — the caster's own Craw Wurm included —
    and the Suntail Hawk is untouched."""
    from engine.models import Permanent

    game = _w1g7_table(set_pool, catalog_by_name, ["Island"] * others)
    board = {}
    for seat, name in ((1, "Grizzly Bears"), (1, "Suntail Hawk"), (0, "Craw Wurm")):
        board[name] = Permanent(card=game._w1g7_card(name))
        game._put_permanent_onto_battlefield(seat, board[name], None)
    _w1g7_resolve_stack(game)
    game.players[0].hand.append(game._w1g7_card("Swirling Sandstorm"))
    assert game.cast_from_hand(0, "Swirling Sandstorm").supported
    _w1g7_resolve_stack(game)

    assert game.is_on_battlefield(board["Grizzly Bears"]) is not swept
    assert game.is_on_battlefield(board["Craw Wurm"]) is not swept
    assert game.is_on_battlefield(board["Suntail Hawk"])
    assert board["Suntail Hawk"].damage_marked == 0

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
from engine import Game as _w1g8_Game
from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import _nosick as _w1g8_nosick
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_duel() -> "_w1g8_Game":
    """Two seats, mana costs waived, seat 0's turn started for real."""
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P1"), _w1g8_PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g8_names(zone) -> list[str]:
    return sorted(card.name for card in zone)


def _w1g8_therapy_victim(set_pool, game) -> None:
    lea = set_pool("LEA")
    game.players[1].hand.extend([
        lea["Lightning Bolt"], lea["Lightning Bolt"], lea["Forest"],
        lea["Grizzly Bears"],
    ])


# --- Cabal Therapy --------------------------------------------------------

def test_w1g8_cabal_therapy_discards_every_card_with_the_chosen_name(set_pool):
    """"Choose a nonland card name. Target player reveals their hand and
    discards all cards with that name." Ruling 2016-06-08: the name is chosen
    as Cabal Therapy resolves, and nothing happens between the naming and the
    discard — the resolution waits on the name, then reveals and discards."""
    game = _w1g8_duel()
    game.players[0].hand.append(set_pool("JUD")["Cabal Therapy"])
    _w1g8_therapy_victim(set_pool, game)
    assert game.queue_from_hand(0, "Cabal Therapy", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    owed = game.pending_choices_of("choose_card_name")
    assert [choice.player_index for choice in owed] == [0]
    assert _w1g8_names(game.players[1].hand) == [
        "Forest", "Grizzly Bears", "Lightning Bolt", "Lightning Bolt",
    ]
    assert game.confirm_choose_card_name(0, "Lightning Bolt")
    _w1g8_resolve_stack(game)
    assert _w1g8_names(game.players[1].hand) == ["Forest", "Grizzly Bears"]
    assert _w1g8_names(game.players[1].graveyard) == ["Lightning Bolt", "Lightning Bolt"]
    assert _w1g8_names(game.players[0].graveyard) == ["Cabal Therapy"]
    assert "P1 named Lightning Bolt" in game.log


def test_w1g8_cabal_therapy_refuses_a_land_name(set_pool):
    """"…a **nonland** card name": a land's name is refused with the prompt
    kept (the answer check the Meddling Mage entry choice already asks), and
    the default a non-interactive seat takes obeys the bound too."""
    game = _w1g8_duel()
    game.players[0].hand.append(set_pool("JUD")["Cabal Therapy"])
    _w1g8_therapy_victim(set_pool, game)
    lea = set_pool("LEA")
    # What the caster can see of the target: a graveyard of Forests and one
    # Bolt. The commonest *nonland* name there is the Bolt.
    game.players[1].graveyard.extend([lea["Forest"], lea["Forest"], lea["Lightning Bolt"]])
    assert game.queue_from_hand(0, "Cabal Therapy", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    assert not game.confirm_choose_card_name(0, "Forest")
    (choice,) = game.pending_choices_of("choose_card_name")
    assert choice.data["excluded_card_type"] == "land"
    assert choice.data["default_name"] == "Lightning Bolt"
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)
    assert _w1g8_names(game.players[1].hand) == ["Forest", "Grizzly Bears"]


def test_w1g8_cabal_therapy_flashes_back_by_sacrificing_a_creature(set_pool):
    """"Flashback—Sacrifice a creature." Cast from the graveyard, the creature
    is the price (CR 702.34a, CR 118.9), the spell does what it does from a
    hand, and it is exiled afterwards."""
    game = _w1g8_duel()
    therapy = set_pool("JUD")["Cabal Therapy"]
    game.players[0].graveyard.append(therapy)
    bears = _w1g8_nosick(_w1g8_Permanent(card=set_pool("LEA")["Grizzly Bears"]))
    game.players[0].battlefield.append(bears)
    _w1g8_therapy_victim(set_pool, game)
    assert game.queue_from_hand(
        0, "Cabal Therapy", from_zone="graveyard", target_player_index=1,
    ).supported
    assert game.stack[-1].flashback
    assert not any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0))
    _w1g8_resolve_stack(game)
    assert game.confirm_choose_card_name(0, "Grizzly Bears")
    _w1g8_resolve_stack(game)
    assert _w1g8_names(game.players[1].hand) == ["Forest", "Lightning Bolt", "Lightning Bolt"]
    assert _w1g8_names(game.players[0].exile) == ["Cabal Therapy"]
    assert _w1g8_names(game.players[0].graveyard) == ["Grizzly Bears"]


def test_w1g8_cabal_therapy_without_a_creature_cannot_be_flashed_back(set_pool):
    """CR 601.2h: no creature to sacrifice is a flashback cost that cannot be
    paid, and the card stays in the graveyard."""
    game = _w1g8_duel()
    game.players[0].graveyard.append(set_pool("JUD")["Cabal Therapy"])
    _w1g8_therapy_victim(set_pool, game)
    refused = game.cast_from_hand(
        0, "Cabal Therapy", from_zone="graveyard", target_player_index=1,
    )
    assert not refused.supported
    assert _w1g8_names(game.players[0].graveyard) == ["Cabal Therapy"]
    assert len(game.players[1].hand) == 4


# --- Firecat Blitz --------------------------------------------------------

def _w1g8_blitz_board(set_pool, mountains: int) -> "tuple[_w1g8_Game, list]":
    """Seat 0: Firecat Blitz in its graveyard, *mountains* Mountains and a
    Forest on the battlefield, exactly {R}{R} floating — costs enforced."""
    lea = set_pool("LEA")
    game = _w1g8_duel()
    game.enforce_mana_costs = True
    player = game.players[0]
    player.graveyard.append(set_pool("JUD")["Firecat Blitz"])
    lands = [_w1g8_nosick(_w1g8_Permanent(card=lea["Mountain"])) for _ in range(mountains)]
    player.battlefield.extend(lands + [_w1g8_nosick(_w1g8_Permanent(card=lea["Forest"]))])
    player.mana_pool["R"] = 2
    return game, lands


def _w1g8_board_names(game, seat: int) -> list[str]:
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g8_firecat_blitz_flashes_back_sacrificing_x_mountains(set_pool):
    """"Flashback—{R}{R}, Sacrifice X Mountains." The X announced with the cast
    sizes the sacrifice and the tokens alike (CR 107.3a): the two Mountains the
    caster named go, the third stays, and two hasty 1/1 Elemental Cats are
    exiled at the beginning of the next end step."""
    game, lands = _w1g8_blitz_board(set_pool, 3)
    spec = game.cast_target_spec(0, set_pool("JUD")["Firecat Blitz"], from_zone="graveyard")
    assert spec["announces_x"] and spec["max_x"] == 3
    named = [lands[0].permanent_id, lands[2].permanent_id]
    cast = game.cast_from_hand(
        0, "Firecat Blitz", from_zone="graveyard", x_value=2,
        alternative_cost_permanent_ids=named,
    )
    assert cast.supported, cast.details
    _w1g8_resolve_stack(game)
    assert any(p is lands[1] for p in game.controlled_by(0))
    assert _w1g8_board_names(game, 0) == [
        "Elemental Cat Token", "Elemental Cat Token", "Forest", "Mountain",
    ]
    cats = [p for p in game.controlled_by(0) if p.card.name == "Elemental Cat Token"]
    assert all(game._has_keyword(cat, "haste") for cat in cats)
    assert _w1g8_names(game.players[0].graveyard) == ["Mountain", "Mountain"]
    assert _w1g8_names(game.players[0].exile) == ["Firecat Blitz"]
    game.resolve_end_step(0)
    _w1g8_resolve_stack(game)
    assert _w1g8_board_names(game, 0) == ["Forest", "Mountain"]


def test_w1g8_firecat_blitz_cannot_sacrifice_more_mountains_than_it_has(set_pool):
    """CR 601.2h: three Mountains are no payment for an X of four, and naming
    one Mountain for an X of two is a partial payment — both refused with
    nothing spent and the card still in the graveyard."""
    game, lands = _w1g8_blitz_board(set_pool, 3)
    refused = game.cast_from_hand(0, "Firecat Blitz", from_zone="graveyard", x_value=4)
    assert not refused.supported and "flashback cost" in refused.details
    refused = game.cast_from_hand(
        0, "Firecat Blitz", from_zone="graveyard", x_value=2,
        alternative_cost_permanent_ids=[lands[0].permanent_id],
    )
    assert not refused.supported
    assert _w1g8_board_names(game, 0) == ["Forest", "Mountain", "Mountain", "Mountain"]
    assert game.players[0].mana_pool["R"] == 2
    assert _w1g8_names(game.players[0].graveyard) == ["Firecat Blitz"]


def test_w1g8_firecat_blitz_flashed_back_with_no_x_announced_sacrifices_nothing(set_pool):
    """The flashback's X is paid in Mountains, not mana, so mana floating says
    nothing about it: with {R}{R}{R}{R} in the pool and no X announced, the cast
    is X = 0 — no Mountain is sacrificed and no cat made — rather than an X
    inferred from the pool and charged in lands nobody named."""
    game, _lands = _w1g8_blitz_board(set_pool, 3)
    game.players[0].mana_pool["R"] = 4
    cast = game.cast_from_hand(0, "Firecat Blitz", from_zone="graveyard")
    assert cast.supported, cast.details
    _w1g8_resolve_stack(game)
    assert _w1g8_board_names(game, 0) == ["Forest", "Mountain", "Mountain", "Mountain"]
    assert game.players[0].mana_pool["R"] == 2
    assert _w1g8_names(game.players[0].exile) == ["Firecat Blitz"]


def test_w1g8_firecat_blitz_from_hand_makes_x_cats_and_sacrifices_nothing(set_pool):
    """Cast from a hand for {X}{R}{R}: X cats, no Mountain sacrificed."""
    game, _lands = _w1g8_blitz_board(set_pool, 2)
    game.enforce_mana_costs = False
    blitz = game.players[0].graveyard.pop()
    game.players[0].hand.append(blitz)
    assert game.cast_from_hand(0, "Firecat Blitz", x_value=3).supported
    _w1g8_resolve_stack(game)
    assert _w1g8_board_names(game, 0).count("Elemental Cat Token") == 3
    assert _w1g8_board_names(game, 0).count("Mountain") == 2
    assert _w1g8_names(game.players[0].graveyard) == ["Firecat Blitz"]

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
