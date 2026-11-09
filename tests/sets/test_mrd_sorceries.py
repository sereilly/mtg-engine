"""Mirrodin sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
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

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

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

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

from engine.game import Game as _W1G11Game
from engine.models import Permanent as _W1G11Permanent
from engine.models import PlayerState as _W1G11PlayerState

from tests.helpers import resolve_stack as _w1g11_resolve_stack


def _w1g11_gambit_table(set_pool, monkeypatch, coins, *, interactive):
    import engine.handlers.coin_runs as _w1g11_coin_runs

    mrd, lea = set_pool("MRD"), set_pool("LEA")
    alice = _W1G11PlayerState(
        name="Alice", hand=[mrd["Fiery Gambit"]], library=[lea["Island"]] * 12,
    )
    bob = _W1G11PlayerState(name="Bob", library=[lea["Island"]] * 6)
    game = _W1G11Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    dragon = _W1G11Permanent(card=lea["Shivan Dragon"])
    game._put_permanent_onto_battlefield(1, dragon, None)
    land = _W1G11Permanent(card=lea["Mountain"], tapped=True)
    game._put_permanent_onto_battlefield(0, land, None)
    queue = list(coins)
    monkeypatch.setattr(
        _w1g11_coin_runs, "flip_coin", lambda win_probability=0.5: queue.pop(0),
    )
    return game, alice, bob, dragon, land


def _w1g11_cast_gambit(game, dragon):
    assert game.cast_from_hand(
        0, "Fiery Gambit", target_permanent_ids=[dragon.permanent_id],
    ).supported


def test_w1g11_fiery_gambit_three_wins_does_everything(set_pool, monkeypatch):
    """The ruling (2004-12-01): three wins is 3 to the creature, 6 to each
    opponent, nine cards and the lands untapped."""
    game, alice, bob, dragon, land = _w1g11_gambit_table(
        set_pool, monkeypatch, [True, True, True], interactive=True,
    )
    _w1g11_cast_gambit(game, dragon)
    game.resolve_top_of_stack()
    for _ in range(2):
        (offer,) = [c for c in game.pending_choices if c.kind == "flip_again"]
        assert offer.player_index == 0
        assert game.confirm_flip_again(0, True)
    (offer,) = [c for c in game.pending_choices if c.kind == "flip_again"]
    assert offer.data["flips_won"] == 3
    assert game.confirm_flip_again(0, False)
    _w1g11_resolve_stack(game)
    assert dragon.damage_marked == 3
    assert bob.life == 14
    assert len(alice.hand) == 9
    assert not land.tapped


def test_w1g11_fiery_gambit_stopping_after_one_win_burns_the_creature(set_pool, monkeypatch):
    game, alice, bob, dragon, _land = _w1g11_gambit_table(
        set_pool, monkeypatch, [True], interactive=True,
    )
    _w1g11_cast_gambit(game, dragon)
    game.resolve_top_of_stack()
    assert game.confirm_flip_again(0, False)
    _w1g11_resolve_stack(game)
    assert dragon.damage_marked == 3
    assert bob.life == 20
    assert alice.hand == []


def test_w1g11_fiery_gambit_a_lost_flip_voids_two_wins(set_pool, monkeypatch):
    """"If you lose a flip, Fiery Gambit has no effect" — even after two wins."""
    game, alice, bob, dragon, land = _w1g11_gambit_table(
        set_pool, monkeypatch, [True, True, False], interactive=True,
    )
    _w1g11_cast_gambit(game, dragon)
    game.resolve_top_of_stack()
    assert game.confirm_flip_again(0, True)
    assert game.confirm_flip_again(0, True)
    _w1g11_resolve_stack(game)
    assert dragon.damage_marked == 0
    assert bob.life == 20
    assert alice.hand == []
    assert land.tapped
    assert any("has no effect" in line for line in game.log)


def test_w1g11_fiery_gambit_left_to_itself_flips_once_and_stops(set_pool, monkeypatch):
    game, alice, bob, dragon, _land = _w1g11_gambit_table(
        set_pool, monkeypatch, [True], interactive=False,
    )
    _w1g11_cast_gambit(game, dragon)
    _w1g11_resolve_stack(game)
    assert dragon.damage_marked == 3
    assert bob.life == 20

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
