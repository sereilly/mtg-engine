"""Darksteel artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
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

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.named_counters import add_counters as _w1g5_add_counters
from engine.named_counters import counters_on as _w1g5_counters_on
from tests.helpers import settle as _w1g5_settle


def _w1g5_table(set_pool, *, mine=(), theirs=(), hand=(), life=20, interactive=()):
    """A two-seat game before seat 0's first turn. Cards are named (DST, LEA
    or ATQ); Alice starts at *life* — set before the turn starts, so the
    life-loss sweep's first sight of her records it rather than reading a
    loss of the difference."""
    pools = [set_pool("DST"), set_pool("LEA"), set_pool("ATQ")]

    def named(name):
        return next(pool[name] for pool in pools if name in pool)

    game = _W1G5Game(players=[
        _W1G5PlayerState(name="Alice", hand=[named(n) for n in hand],
                         library=[named("Island")] * 10),
        _W1G5PlayerState(name="Bob", library=[named("Island")] * 10),
    ])
    game.players[0].life = life
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G5Permanent(card=named(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    return game, placed[0], placed[1]


def _w1g5_untapped(game, seat, name):
    return sum(1 for p in game.controlled_by(seat) if p.card.name == name and not p.tapped)


def test_w1g5_well_of_lost_dreams_pays_and_draws_up_to_the_life_gained(set_pool):
    """"Whenever you gain life, you may pay {X}, where X is less than or equal
    to the amount of life you gained. If you do, draw X cards." Nourish gains
    6 with four lands up: a seat nobody asks pays what the board covers (4),
    under the ceiling, and draws 4. Angel's Feather's 1 life caps the next
    payment at 1 with lands to spare: one land tapped, one card drawn."""
    game, _mine, _theirs = _w1g5_table(
        set_pool, mine=["Well of Lost Dreams"] + ["Forest"] * 4, hand=["Nourish"],
    )
    game.start_turn(0)
    _w1g5_settle(game)
    game.cast_from_hand(0, "Nourish")
    _w1g5_settle(game)
    alice = game.players[0]
    assert alice.life == 26
    assert len(alice.hand) == 4 and len(alice.library) == 6
    assert _w1g5_untapped(game, 0, "Forest") == 0
    assert "Alice drew 4 card(s) (Well of Lost Dreams)" in game.log

    game, _mine, _theirs = _w1g5_table(
        set_pool, mine=["Well of Lost Dreams", "Angel's Feather"] + ["Forest"] * 3,
        hand=["Savannah Lions"],
    )
    game.start_turn(0)
    _w1g5_settle(game)
    game.cast_from_hand(0, "Savannah Lions")
    _w1g5_settle(game)
    assert game.players[0].life == 21
    assert len(game.players[0].hand) == 1
    assert _w1g5_untapped(game, 0, "Forest") == 2


def test_w1g5_well_of_lost_dreams_holds_an_asked_seat_to_the_ceiling(set_pool):
    """Asked, the seat names X itself (CR 107.3f) — and the clause bounds the
    answer: with 1 life gained, paying 2 is refused and the prompt stays owed;
    paying 1 taps one land and draws one card. The prompt carries the ceiling
    as its ``maximum``."""
    game, _mine, _theirs = _w1g5_table(
        set_pool, mine=["Well of Lost Dreams", "Angel's Feather"] + ["Forest"] * 3,
        hand=["Savannah Lions"], interactive=(0,),
    )
    game.start_turn(0)
    _w1g5_settle(game)
    game.cast_from_hand(0, "Savannah Lions")
    feather = _w1g5_settle(game, defaults=False)
    assert feather.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    offer = _w1g5_settle(game, defaults=False)
    assert offer.kind == "pay_any_amount" and offer.data["maximum"] == 1
    assert not game.confirm_pay_any_amount(0, 2)
    assert game.confirm_pay_any_amount(0, 1)
    _w1g5_settle(game)
    assert game.players[0].life == 21
    assert len(game.players[0].hand) == 1
    assert _w1g5_untapped(game, 0, "Forest") == 2


def test_w1g5_lichs_tomb_keeps_its_controller_alive_below_zero_at_a_price(set_pool):
    """"You don't lose the game for having 0 or less life. Whenever you lose
    life, sacrifice a permanent for each 1 life you lost." At 2 life, a
    Lightning Bolt takes Alice to -1: CR 704.5a does not end the game, and
    three permanents go — not the Tomb, which a seat nobody asks gives up last
    because its departure loses the game. When the Tomb itself leaves, she
    loses at the next check."""
    game, mine, _theirs = _w1g5_table(
        set_pool,
        mine=["Lich's Tomb", "Forest", "Grizzly Bears", "Ornithopter", "Sol Ring"],
        hand=["Lightning Bolt"], life=2,
    )
    game.start_turn(0)
    _w1g5_settle(game)
    tomb = mine[0]
    game.cast_from_hand(0, "Lightning Bolt", target_player_index=0)
    _w1g5_settle(game)
    alice = game.players[0]
    assert alice.life == -1 and not alice.lost
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Lich's Tomb"]
    assert sum("(Lich's Tomb)" in line and "sacrificed" in line for line in game.log) == 3

    game.sacrifice_permanent(tomb)
    _w1g5_settle(game)
    assert alice.lost
    assert "Alice lost the game (704.5a: 0 or less life)" in game.log


def test_w1g5_lichs_tomb_asks_its_controller_which_permanents_and_how_many(set_pool):
    """Asked, the controller picks exactly as many permanents as life was
    lost — 3 for a Bolt: two are refused, three are taken. A life gain is not
    a loss and asks nothing."""
    game, mine, _theirs = _w1g5_table(
        set_pool,
        mine=["Lich's Tomb", "Forest", "Grizzly Bears", "Ornithopter", "Sol Ring"],
        hand=["Lightning Bolt", "Nourish"], interactive=(0,),
    )
    game.start_turn(0)
    _w1g5_settle(game)
    _tomb, forest, bears, thopter, ring = mine
    game.cast_from_hand(0, "Lightning Bolt", target_player_index=0)
    owed = _w1g5_settle(game, defaults=False)
    assert owed.kind == "sacrifice" and owed.data["count"] == 3
    assert not game.confirm_sacrifice(0, permanent_ids=[forest.permanent_id, ring.permanent_id])
    assert game.confirm_sacrifice(
        0, permanent_ids=[forest.permanent_id, thopter.permanent_id, ring.permanent_id],
    )
    _w1g5_settle(game)
    assert game.players[0].life == 17
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Lich's Tomb"]
    game.cast_from_hand(0, "Nourish")
    assert _w1g5_settle(game, defaults=False) is None
    assert game.players[0].life == 23
    assert any(p is bears for p in game.controlled_by(0))


def test_w1g5_darksteel_reactor_wins_at_twenty_charge_counters(set_pool):
    """"When this artifact has twenty or more charge counters on it, you win
    the game." A state trigger (CR 603.8) and CR 104.2b's win: at 19 counters
    the upkeep's charge counter makes 20, and Alice wins. At 18 the upkeep
    makes 19 and the game goes on — and an asked seat that declines the
    counter stays at 19 and does not win."""
    game, mine, _theirs = _w1g5_table(set_pool, mine=["Darksteel Reactor"])
    _w1g5_add_counters(mine[0], "charge", 19)
    game.start_turn(0)
    _w1g5_settle(game)
    assert _w1g5_counters_on(mine[0], "charge") == 20
    assert game.is_game_over()
    assert game.players[1].lost and not game.players[0].lost
    assert "Darksteel Reactor: Alice wins the game (104.2b)" in game.log

    game, mine, _theirs = _w1g5_table(set_pool, mine=["Darksteel Reactor"])
    _w1g5_add_counters(mine[0], "charge", 18)
    game.start_turn(0)
    _w1g5_settle(game)
    assert _w1g5_counters_on(mine[0], "charge") == 19
    assert not game.is_game_over()

    game, mine, _theirs = _w1g5_table(set_pool, mine=["Darksteel Reactor"], interactive=(0,))
    _w1g5_add_counters(mine[0], "charge", 19)
    game.start_turn(0)
    offer = _w1g5_settle(game, defaults=False)
    assert offer is not None
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_settle(game)
    assert _w1g5_counters_on(mine[0], "charge") == 19
    assert not game.is_game_over()

# ==== end W1G5 ======================================================
