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

# ==== end W1G10 ======================================================
