"""Champions of Kamigawa enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (
    _game as _w1g8_game,
    _nosick as _w1g8_nosick,
    settle as _w1g8_settle,
    stock_libraries as _w1g8_stock_libraries,
)


def _w1g8_table(mine=(), theirs=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's precombat main phase of turn 2, the permanents
    placed through the entry funnel, libraries stocked."""
    game = _w1g8_game(
        _w1g8_PlayerState(name="P1", hand=list(hand), life=20),
        _w1g8_PlayerState(name="P2", hand=list(opponent_hand), life=20),
    )
    _w1g8_stock_libraries(game)
    game.turn = 2
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        row = []
        for card in cards:
            permanent = _w1g8_Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_w1g8_nosick(permanent))
        placed.append(row)
    game._sync_control()
    _w1g8_settle(game)
    return game, placed[0], placed[1]


def _w1g8_zone_names(game, seat, zone):
    return [card.name for card in getattr(game.players[seat], zone)]


# --- Vassal's Duty ------------------------------------------------------------
# "{1}: The next 1 damage that would be dealt to target legendary creature you
# control this turn is dealt to you instead." CR 614.9's redirect as a point
# pool (Daughter of Autumn's record), the ability's controller taking it.


def test_w1g8_vassals_duty_moves_one_point_to_its_controller(set_pool):
    duty = set_pool("CHK")["Vassal's Duty"]
    kumano = set_pool("CHK")["Kumano, Master Yamabushi"]
    bolt = set_pool("LEA")["Lightning Bolt"]
    game, (_, legend), _ = _w1g8_table([duty, kumano], [], opponent_hand=[bolt, bolt])
    used = game.activate_permanent_ability(
        0, "Vassal's Duty", target_permanent_ids=[legend.permanent_id]
    )
    assert used.supported, used.details
    _w1g8_settle(game)
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[legend.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.players[0].life == 19
    assert legend.damage_marked == 2
    # Spent: the next Bolt is dealt to Kumano whole, and kills it.
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[legend.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.players[0].life == 19
    assert not game.is_on_battlefield(legend)


def test_w1g8_vassals_duty_targets_only_a_legendary_creature_you_control(set_pool):
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    duty = set_pool("CHK")["Vassal's Duty"]
    kumano = set_pool("CHK")["Kumano, Master Yamabushi"]
    bears = set_pool("LEA")["Grizzly Bears"]
    ability = compile_card_oracle(duty).activated_abilities[0]
    assert derive_activation_spec(ability) == {
        "kind": "creature", "own_only": True,
        "filter": {"supertypes": ["legendary"]},
    }
    game, (_, bear), (theirs,) = _w1g8_table([duty, bears], [kumano])
    for chosen in (bear, theirs):
        assert not game.activate_permanent_ability(
            0, "Vassal's Duty", target_permanent_ids=[chosen.permanent_id]
        ).supported

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
