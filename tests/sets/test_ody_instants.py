"""Odyssey instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
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

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

import pytest as _w1g4_pytest

from engine import Game as _w1g4_Game, PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=()):
    """A two-seat game with costs off, built from card names.

    Odyssey and Alpha in one pool: the Bursts count their own name, and what
    they are aimed at is furniture.
    """
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    seats = [
        _w1g4_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g4_Game(players=seats)
    game.enforce_mana_costs = False
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            game._put_permanent_onto_battlefield(
                seat, _w1g4_Permanent(card=pool[name]), None
            )
    return game


def _w1g4_names(cards):
    return [card.name for card in cards]


def _w1g4_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- The Bursts: "N plus the number of cards named ~ in all graveyards" ------

def test_flame_burst_counts_its_name_in_every_graveyard(set_pool):
    """2 plus one in each graveyard: 4 damage, and the copy being cast is on
    the stack while the count is taken, so it is not one of them."""
    game = _w1g4_duel(
        set_pool, hand0=["Flame Burst"], gy0=["Flame Burst"],
        gy1=["Flame Burst", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Flame Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 16
    assert _w1g4_names(game.players[0].graveyard) == ["Flame Burst", "Flame Burst"]


def test_flame_burst_with_none_in_a_graveyard_deals_its_printed_two(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Flame Burst"], bf1=["Grizzly Bears"])
    bears = _w1g4_on_board(game, 1, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Flame Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert game.players[1].life == 20


def test_muscle_burst_is_three_plus_the_bursts_in_all_graveyards(set_pool):
    """The same definition Flame Burst prints, in the +X/+X position — which
    refused ("only a count or a maximum can define X here") while the damage
    form read it: one where-clause, two readers that had drifted apart."""
    game = _w1g4_duel(
        set_pool, hand0=["Muscle Burst"], gy0=["Muscle Burst"],
        gy1=["Muscle Burst", "Flame Burst"], bf0=["Grizzly Bears"],
    )
    bears = _w1g4_on_board(game, 0, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Muscle Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (7, 7)


def test_muscle_burst_needs_a_creature_to_aim_at(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Muscle Burst"], bf1=["Forest"])
    forest = _w1g4_on_board(game, 1, "Forest")
    refused = game.cast_from_hand(
        0, "Muscle Burst", target_permanent_ids=[forest.permanent_id]
    )
    assert not refused.supported
    assert _w1g4_names(game.players[0].hand) == ["Muscle Burst"]


@_w1g4_pytest.mark.parametrize("line, expected", [
    # The arithmetic the sentence form always read, now in the pump position.
    ("Target creature gets +X/+X until end of turn, where X is twice the "
     "number of cards named Vigor Burst in all graveyards minus 1.", (5, 5)),
    ("Target creature gets +X/+0 until end of turn, where X is the number of "
     "cards in your graveyard minus the number of cards in your hand.", (4, 2)),
])
def test_a_pump_reads_the_arithmetic_a_damage_where_clause_reads(
    set_pool, line, expected
):
    """An invented card, not a name: the fork was in which *sentence* could
    carry a sum, so the proof is a card nobody printed carrying one."""
    burst = _w1g4_mk_card("Vigor Burst", "{G}", "Instant", line)
    assert _w1g4_compile(burst).supported
    game = _w1g4_duel(set_pool, bf0=["Grizzly Bears"])
    game.players[0].hand.append(burst)
    game.players[0].graveyard.extend([burst, burst])
    bears = _w1g4_on_board(game, 0, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Vigor Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == expected


def test_a_damage_where_clause_reads_the_maximum_a_pump_reads(set_pool):
    """The fork's other direction: "the greatest power among" defined a pump's
    X (Carrion Grub) and refused a damage's."""
    blast = _w1g4_mk_card(
        "Grave Blast", "{R}", "Instant",
        "Grave Blast deals X damage to any target, where X is the greatest "
        "power among creature cards in your graveyard.",
    )
    assert _w1g4_compile(blast).supported
    game = _w1g4_duel(set_pool, gy0=["Grizzly Bears", "Craw Wurm", "Forest"])
    game.players[0].hand.append(blast)
    assert game.cast_from_hand(0, "Grave Blast", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 14


def test_a_continuous_x_refuses_a_count_taken_off_a_count():
    """A durationless +X/+0 is rebuilt by the CR 613 recompute, which asks the
    zone evaluator and never the resolution-time function that subtracts — so
    the shape refuses instead of dropping its subtrahend."""
    grower = _w1g4_mk_card(
        "Odd Grower", "{G}", "Creature — Beast",
        "This creature gets +X/+0, where X is the number of cards in your "
        "hand minus the number of cards in your graveyard.",
    )
    assert not _w1g4_compile(grower).supported
    steady = _w1g4_mk_card(
        "Even Grower", "{G}", "Creature — Beast",
        "This creature gets +X/+0, where X is 1 plus the number of cards in "
        "your graveyard.",
    )
    assert _w1g4_compile(steady).supported


# --- Aether Burst: an X counted as the spell is cast (CR 601.2b/601.2c) ------

def test_aether_burst_announces_its_x_and_bounds_the_picker(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Aether Burst"], gy1=["Aether Burst"],
        bf0=["Grizzly Bears"], bf1=["Craw Wurm", "Scryb Sprites"],
    )
    card = set_pool("ODY")["Aether Burst"]
    assert game.announced_cast_x(0, card) == 2
    spec = game.cast_target_spec(0, card)
    assert spec["defined_x"] == 2 and spec["max_targets"] == 2
    assert len(spec["valid_targets"]) == 3
    every = [p.permanent_id for p in game.all_permanents()]
    refused = game.cast_from_hand(0, "Aether Burst", target_permanent_ids=every)
    assert not refused.supported
    assert refused.details == "Aether Burst has 2 targets, not 3"
    assert _w1g4_names(game.players[0].hand) == ["Aether Burst"]


def test_aether_burst_returns_what_was_named_to_its_owners_hand(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Aether Burst"], gy1=["Aether Burst"],
        bf0=["Grizzly Bears"], bf1=["Craw Wurm", "Scryb Sprites"],
    )
    theirs = [p.permanent_id for p in game.controlled_by(1)]
    assert game.cast_from_hand(
        0, "Aether Burst", target_permanent_ids=theirs
    ).supported
    _w1g4_resolve_stack(game)
    assert sorted(_w1g4_names(game.players[1].hand)) == ["Craw Wurm", "Scryb Sprites"]
    assert [p.card.name for p in game.all_permanents()] == ["Grizzly Bears"]


def test_aether_burst_may_name_nobody_and_refuses_a_land(set_pool):
    """"Up to X": naming none is a legal announcement (CR 601.2c), and what is
    named has to be a creature."""
    game = _w1g4_duel(set_pool, hand0=["Aether Burst"], bf1=["Craw Wurm"])
    assert game.cast_from_hand(0, "Aether Burst", target_permanent_ids=[]).supported
    _w1g4_resolve_stack(game)
    assert [p.card.name for p in game.all_permanents()] == ["Craw Wurm"]

    again = _w1g4_duel(set_pool, hand0=["Aether Burst"], bf1=["Forest"])
    forest = _w1g4_on_board(again, 1, "Forest")
    refused = again.cast_from_hand(
        0, "Aether Burst", target_permanent_ids=[forest.permanent_id]
    )
    assert not refused.supported
    assert _w1g4_names(again.players[0].hand) == ["Aether Burst"]


def test_aether_burst_freezes_its_x_at_the_announcement(set_pool):
    """CR 601.2c: the number of targets does not change once determined. The
    graveyards are emptied in response and one target leaves: the two that are
    left are still returned, where a count taken again would return one."""
    game = _w1g4_duel(
        set_pool, hand0=["Aether Burst"], gy1=["Aether Burst", "Aether Burst"],
        bf1=["Craw Wurm", "Scryb Sprites", "Grizzly Bears"],
    )
    ids = [p.permanent_id for p in game.controlled_by(1)]
    assert game.queue_from_hand(0, "Aether Burst", target_permanent_ids=ids).supported
    assert game.stack[-1].x_value == 3
    game.players[1].graveyard.clear()
    game.remove_from_battlefield(game.permanent_by_id(ids[0]))
    _w1g4_resolve_stack(game)
    assert sorted(_w1g4_names(game.players[1].hand)) == ["Grizzly Bears", "Scryb Sprites"]


def test_aether_burst_with_every_target_gone_does_nothing(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Aether Burst"], bf1=["Craw Wurm"])
    wurm = _w1g4_on_board(game, 1, "Craw Wurm")
    assert game.queue_from_hand(
        0, "Aether Burst", target_permanent_ids=[wurm.permanent_id]
    ).supported
    game.remove_from_battlefield(wurm)
    _w1g4_resolve_stack(game)
    assert any("608.2b" in line for line in game.log)
    assert game.players[1].hand == []


# --- Life Burst: "…for each card named ~ in each graveyard" -------------------

def test_life_burst_gains_four_then_four_per_burst_in_each_graveyard(set_pool):
    """One Life Burst in each graveyard: 4, then 8 more. "In each graveyard" is
    "in all graveyards" distributed (CR 400.1: one pile per seat), and the copy
    being cast is still on the stack."""
    game = _w1g4_duel(
        set_pool, hand0=["Life Burst"], gy0=["Life Burst"],
        gy1=["Life Burst", "Forest"],
    )
    assert game.cast_from_hand(0, "Life Burst", target_player_index=0).supported
    _w1g4_resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (32, 20)


def test_life_burst_names_its_player_and_gives_the_plain_four(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Life Burst"])
    spec = game.cast_target_spec(0, set_pool("ODY")["Life Burst"])
    assert spec["kind"] == "player" and spec["requires_target"]
    assert game.cast_from_hand(0, "Life Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (20, 24)


# --- Entomb and Predict --------------------------------------------------------

def test_entomb_puts_the_found_card_into_its_owners_graveyard(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Entomb"], lib0=["Forest", "Craw Wurm", "Island"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Entomb").supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.data["destination"] == "graveyard" and prompt.data["count"] == 1
    assert prompt.data["card_type"] == "any" and not prompt.data["up_to"]
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    graveyard = _w1g4_names(game.players[0].graveyard)
    assert len(graveyard) == 2 and "Entomb" in graveyard
    assert len(game.players[0].library) == 2


@_w1g4_pytest.mark.parametrize("named, drawn", [
    ("Grizzly Bears", 2),   # the card that is milled
    ("Craw Wurm", 1),       # a card that is not
    ("", 1),                # naming nothing
])
def test_predict_draws_two_for_the_right_name_and_one_otherwise(
    set_pool, named, drawn
):
    """The name is chosen as the spell resolves, before the mill, and it is
    the caster's to choose — a prompt on their seat while the spell is held."""
    game = _w1g4_duel(
        set_pool, hand0=["Predict"], lib0=["Forest", "Island", "Swamp"],
        lib1=["Grizzly Bears", "Craw Wurm"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Predict", target_player_index=1).supported
    game.resolve_top_of_stack()
    prompt = game.waiting_prompt()
    assert prompt.kind == "choose_card_name" and prompt.player_index == 0
    assert game.players[1].graveyard == [], "nothing is milled before the name"
    assert game.confirm_choose_card_name(0, named)
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert len(game.players[0].hand) == drawn
    assert _w1g4_names(game.players[0].graveyard) == ["Predict"]


def test_predict_may_mill_its_own_caster(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Predict"], lib0=["Forest", "Island", "Swamp"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Predict", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_choose_card_name(0, "Forest")
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[0].graveyard) == ["Forest", "Predict"]
    assert _w1g4_names(game.players[0].hand) == ["Island", "Swamp"]

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

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


def _w1g7_pt(game, seat=0):
    return sorted(
        (p.card.name, p.effective_power, p.effective_toughness)
        for p in game.controlled_by(seat) if p.is_creature
    )


# --- Sacred Rites: a pump sized by what was discarded --------------------------

def test_sacred_rites_buffs_its_controllers_creatures_by_the_cards_discarded(
    set_pool,
):
    """"Discard any number of cards. Creatures you control get +0/+1 until end
    of turn for each card discarded this way." The caster names the cards, the
    pump waits for that answer (CR 608.2), reaches only their own creatures and
    ends at cleanup (CR 514.2)."""
    game = _w1g7_duel(
        set_pool, hand0=["Sacred Rites", "Forest", "Island", "Swamp"],
        bf0=["Grizzly Bears", "Grizzly Bears"], bf1=["Grizzly Bears"],
        interactive=(0,),
    )
    assert game.cast_from_hand(0, "Sacred Rites").supported
    (choice,) = game.pending_choices
    assert (choice.kind, choice.data["count"], choice.data["up_to"]) == ("discard", 3, True)
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)] * 2, "nothing yet"

    assert game.confirm_discard(0, [0, 2])
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 4)] * 2
    assert _w1g7_pt(game, 1) == [("Grizzly Bears", 2, 2)]
    assert _w1g7_names(game.players[0].hand) == ["Island"]
    assert sorted(_w1g7_names(game.players[0].graveyard)) == [
        "Forest", "Sacred Rites", "Swamp",
    ]

    game.resolve_cleanup_step(0)
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)] * 2


def test_sacred_rites_with_nothing_discarded_buffs_by_nothing(set_pool):
    """"Any number" includes none, and an empty hand is not asked at all."""
    game = _w1g7_duel(
        set_pool, hand0=["Sacred Rites", "Forest"], bf0=["Grizzly Bears"],
        interactive=(0,),
    )
    game.cast_from_hand(0, "Sacred Rites")
    assert game.confirm_discard(0, [])
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)]
    assert _w1g7_names(game.players[0].hand) == ["Forest"]

    empty = _w1g7_duel(
        set_pool, hand0=["Sacred Rites"], bf0=["Grizzly Bears"], interactive=(0,),
    )
    empty.cast_from_hand(0, "Sacred Rites")
    assert not empty.pending_choices and not empty.stack
    assert _w1g7_pt(empty) == [("Grizzly Bears", 2, 2)]


def test_two_identical_cards_discarded_to_sacred_rites_are_two_cards(set_pool):
    """A hand holds one immutable card object per copy: discarding one of two
    Forests leaves the other, and counts one."""
    game = _w1g7_duel(
        set_pool, hand0=["Sacred Rites", "Forest", "Forest"],
        bf0=["Grizzly Bears"], interactive=(0,),
    )
    game.cast_from_hand(0, "Sacred Rites")
    assert game.confirm_discard(0, [0])
    assert _w1g7_names(game.players[0].hand) == ["Forest"]
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 3)]


def test_a_pump_for_each_card_discarded_this_way_is_any_cards_sentence(set_pool):
    """The clause is the record's, so it sizes a pump on a class, on one
    target and on the source alike — and refuses where nothing was discarded
    or where no duration would make it a continuous effect over a frozen
    number."""
    def card(text, type_line="Sorcery"):
        return _w1g7_mk_card("Rite", "{1}", type_line, text)

    opener = "Discard any number of cards. "
    tail = " until end of turn for each card discarded this way."
    assert _w1g7_compile(card(opener + "Creatures you control get +1/+1" + tail)).supported
    assert _w1g7_compile(card(opener + "Target creature gets +2/+0" + tail)).supported
    # No producer: the words name nothing.
    assert not _w1g7_compile(card("Creatures you control get +1/+1" + tail)).supported
    # A noun the record does not hold.
    assert not _w1g7_compile(card(
        opener + "Creatures you control get +1/+1 until end of turn for each "
        "creature discarded this way."
    )).supported

    game = _w1g7_duel(
        set_pool, hand0=["Forest", "Island"], bf0=["Grizzly Bears"],
        bf1=["Grizzly Bears"], interactive=(0,),
    )
    game.players[0].hand.append(card(opener + "Target creature gets +2/+0" + tail))
    theirs = _w1g7_on_board(game, 1, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Rite", target_permanent_ids=[theirs.permanent_id]
    ).supported
    assert game.confirm_discard(0, [0, 1])
    assert _w1g7_pt(game, 1) == [("Grizzly Bears", 6, 2)]
    assert _w1g7_pt(game, 0) == [("Grizzly Bears", 2, 2)]


# --- Rites of Initiation: the player chooses how many, chance chooses which ----

def test_rites_of_initiation_asks_how_many_and_discards_that_many_at_random(
    set_pool,
):
    """"Discard any number of cards **at random**." Two decisions split between
    two parties: the number is the caster's (asked, with the hand as its
    ceiling) and the cards are chance's."""
    def run(seed):
        _w1g7_random.seed(seed)
        game = _w1g7_duel(
            set_pool,
            hand0=["Rites of Initiation", "Forest", "Island", "Swamp", "Plains"],
            bf0=["Grizzly Bears"], bf1=["Grizzly Bears"], interactive=(0,),
        )
        assert game.cast_from_hand(0, "Rites of Initiation").supported
        (choice,) = game.pending_choices
        assert choice.kind == "number_choice"
        assert (choice.data["minimum"], choice.data["maximum"]) == (0, 4)
        assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)]
        assert game.confirm_number_choice(0, 2)
        assert not game.stack and not game.pending_choices
        return game

    first = run(11)
    assert _w1g7_pt(first) == [("Grizzly Bears", 4, 2)]
    assert _w1g7_pt(first, 1) == [("Grizzly Bears", 2, 2)]
    assert len(first.players[0].hand) == 2
    assert len(first.players[0].graveyard) == 3, "two discards and the spell"

    # Determinism: the seeded RNG picks, so a seed replays the same cards...
    assert _w1g7_names(run(11).players[0].hand) == _w1g7_names(first.players[0].hand)
    # ...and across seeds the caster does not get to pick.
    kept = {tuple(_w1g7_names(run(seed).players[0].hand)) for seed in range(12)}
    assert len(kept) > 1

    first.resolve_cleanup_step(0)
    assert _w1g7_pt(first) == [("Grizzly Bears", 2, 2)]


def test_rites_of_initiation_refuses_a_number_the_hand_cannot_cover(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Initiation", "Forest", "Island"],
        bf0=["Grizzly Bears"], interactive=(0,),
    )
    game.cast_from_hand(0, "Rites of Initiation")
    assert not game.confirm_number_choice(0, 3)
    assert not game.confirm_number_choice(0, -1)
    assert game.pending_choices, "a refused answer leaves the prompt owed"
    assert game.confirm_number_choice(0, 0)
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)]
    assert len(game.players[0].hand) == 2


def test_rites_of_initiation_with_an_empty_hand_asks_nothing(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Initiation"], bf0=["Grizzly Bears"],
        interactive=(0,),
    )
    game.cast_from_hand(0, "Rites of Initiation")
    assert not game.pending_choices and not game.stack
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)]


def test_a_seat_nobody_asks_takes_the_whole_offer_on_both_rites(set_pool):
    """The stated policy for a ceiling a seat does not evaluate
    (``_default_discard``), and the random spelling defaults alike."""
    for name, expected in (
        ("Sacred Rites", ("Grizzly Bears", 2, 4)),
        ("Rites of Initiation", ("Grizzly Bears", 4, 2)),
    ):
        _w1g7_random.seed(3)
        game = _w1g7_duel(
            set_pool, hand0=[name, "Forest", "Island"], bf0=["Grizzly Bears"],
        )
        game.cast_from_hand(0, name)
        _w1g7_settle(game)
        assert game.players[0].hand == [], name
        assert _w1g7_pt(game) == [expected], name


def test_a_narrowed_any_number_random_discard_is_refused():
    assert not _w1g7_compile(_w1g7_mk_card(
        "Narrow Rite", "{R}", "Instant",
        "Discard any number of creature cards at random.",
    )).supported


# --- Rites of Refusal (compiled before this round; driven) ---------------------

def _w1g7_refusal(set_pool, lands):
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Refusal", "Forest", "Island", "Swamp"],
        hand1=["Grizzly Bears"], bf1=["Forest"] * lands, interactive=(0, 1),
    )
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(0, "Rites of Refusal", target_stack_index=0).supported
    game.enforce_mana_costs = True
    game.resolve_top_of_stack(pause_for_choices=True)
    return game


def test_rites_of_refusal_prices_the_toll_at_three_per_card_discarded(set_pool):
    """"Counter target spell unless its controller pays {3} for each card
    discarded this way." Two cards is {6}: paid from six lands the spell
    resolves, and declined it is countered."""
    paid = _w1g7_refusal(set_pool, lands=6)
    assert paid.confirm_discard(0, [0, 1])
    owed = paid.pending_mana_payment
    assert owed is not None and owed["player_index"] == 1 and owed["amount"] == 6
    assert paid.confirm_mana_payment(1, True) is True
    _w1g7_resolve_stack(paid)
    assert "Grizzly Bears" in [p.card.name for p in paid.controlled_by(1)]
    assert all(p.tapped for p in paid.controlled_by(1) if p.card.name == "Forest")

    declined = _w1g7_refusal(set_pool, lands=6)
    assert declined.confirm_discard(0, [0])
    assert declined.pending_mana_payment["amount"] == 3
    assert declined.confirm_mana_payment(1, False) is True
    _w1g7_resolve_stack(declined)
    assert _w1g7_names(declined.players[1].graveyard) == ["Grizzly Bears"]


def test_rites_of_refusal_with_nothing_discarded_counters_nothing(set_pool):
    """{3} for each of no cards is {0}, which is always paid."""
    game = _w1g7_refusal(set_pool, lands=0)
    assert game.confirm_discard(0, [])
    _w1g7_settle(game)
    assert "Grizzly Bears" in [p.card.name for p in game.controlled_by(1)]
    assert len(game.players[0].hand) == 3


def test_rites_of_refusal_needs_a_spell_and_asks_nothing_if_it_leaves(set_pool):
    """CR 601.2c: no spell, no cast. CR 608.2b: with its only target gone the
    spell does not resolve, so no discard is asked for either."""
    alone = _w1g7_duel(set_pool, hand0=["Rites of Refusal", "Forest"])
    assert not alone.cast_from_hand(0, "Rites of Refusal").supported
    assert len(alone.players[0].hand) == 2

    game = _w1g7_duel(
        set_pool, hand0=["Rites of Refusal", "Forest"], hand1=["Grizzly Bears"],
        interactive=(0, 1),
    )
    game.queue_from_hand(1, "Grizzly Bears")
    game.queue_from_hand(0, "Rites of Refusal", target_stack_index=0)
    del game.stack[0]
    game.resolve_top_of_stack(pause_for_choices=True)
    assert not game.pending_choices
    assert _w1g7_names(game.players[0].hand) == ["Forest"]
    assert _w1g7_names(game.players[0].graveyard) == ["Rites of Refusal"]


# --- The sheet's instants that compiled before this round, driven ----------------

def test_repel_puts_a_creature_on_top_of_its_owners_library(set_pool):
    """Its **owner's** library (CR 400.3), so a creature under another
    player's control goes home; a noncreature is no target, and with no
    creature the spell cannot be cast (CR 601.2c)."""
    from engine.control import change_control

    game = _w1g7_duel(
        set_pool, hand0=["Repel"], bf1=["Grizzly Bears"], lib0=["Island"],
        lib1=["Swamp"],
    )
    bears = _w1g7_on_board(game, 1, "Grizzly Bears")
    change_control(bears, 0, source="test")
    game._sync_control()
    assert game.cast_from_hand(
        0, "Repel", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert _w1g7_names(game.players[1].library) == ["Grizzly Bears", "Swamp"]
    assert _w1g7_names(game.players[0].library) == ["Island"]

    ring = _w1g7_duel(set_pool, hand0=["Repel"], bf1=["Sol Ring"])
    artifact = _w1g7_on_board(ring, 1, "Sol Ring")
    assert not ring.cast_from_hand(
        0, "Repel", target_permanent_ids=[artifact.permanent_id]
    ).supported
    assert [p.card.name for p in ring.controlled_by(1)] == ["Sol Ring"]


def test_words_of_wisdom_draws_two_for_you_and_one_for_each_other_player(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Words of Wisdom"], lib0=["Island", "Swamp", "Plains"],
        lib1=["Forest", "Mountain"],
    )
    game.cast_from_hand(0, "Words of Wisdom")
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].hand) == ["Island", "Swamp"]
    assert _w1g7_names(game.players[1].hand) == ["Forest"]

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
