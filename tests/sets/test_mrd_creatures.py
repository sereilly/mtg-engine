"""Mirrodin creatures (legendary ones too).

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
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.cost_modifiers import cast_mana_charge as _w1g3_charge
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_table(set_pool, hand=(), mine=()):
    """Seat 0's turn, mana costs enforced (affinity changes a price), every
    permanent past summoning sickness."""
    mrd = set_pool("MRD")
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", hand=[mrd[n] for n in hand]),
        _W1G3PlayerState(name="W1G3-B"),
    ])
    w1g3_game.enforce_mana_costs = True
    w1g3_game.interactive_seats = set()
    w1g3_game.active_player_index = 0
    w1g3_row = []
    for w1g3_name in mine:
        w1g3_perm = _W1G3Permanent(card=mrd[w1g3_name])
        w1g3_game._put_permanent_onto_battlefield(0, w1g3_perm, None)
        w1g3_perm.metadata["summoning_sickness_turn"] = -99
        w1g3_row.append(w1g3_perm)
    return w1g3_game, w1g3_row  # _w1g3_table


def _w1g3_tap_blue(game, count):
    """Tap *count* of seat 0's Seats of the Synod for {U}."""
    w1g3_lands = [
        p for p in game.controlled_by(0)
        if p.card.name == "Seat of the Synod" and not p.tapped
    ][:count]
    assert len(w1g3_lands) == count
    for w1g3_land in w1g3_lands:
        assert game.tap_land_for_mana(
            0, w1g3_land.card.name, "U", permanent_id=w1g3_land.permanent_id,
        )  # _w1g3_tap_blue


def test_w1g3_broodstar_costs_what_its_artifacts_leave_and_counts_them(set_pool):
    """"Affinity for artifacts" and "Broodstar's power and toughness are each
    equal to the number of artifacts you control" (CR 604.3). Printed
    {8}{U}{U}: eight artifact lands take the {8} off, two of them pay
    {U}{U}, and Broodstar enters an 8/8 flier — it is not an artifact itself.
    The CDA recounts continuously: an artifact entering makes it 9/9, three
    sacrificed make it 6/6. Seven artifacts would have left {1}{U}{U}."""
    broodstar = set_pool("MRD")["Broodstar"]
    game, mine = _w1g3_table(
        set_pool, hand=["Broodstar"], mine=["Seat of the Synod"] * 8,
    )
    charge = _w1g3_charge(game, 0, broodstar)
    assert (charge.get("generic"), charge.get("U")) == (0, 2)
    _w1g3_tap_blue(game, 2)
    cast = game.cast_from_hand(0, "Broodstar")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    star = next(p for p in game.controlled_by(0) if p.card.name == "Broodstar")
    assert (star.effective_power, star.effective_toughness) == (8, 8)
    assert game._has_keyword(star, "flying")
    assert sum(game.players[0].mana_pool.values()) == 0

    game._put_permanent_onto_battlefield(
        0, _W1G3Permanent(card=set_pool("MRD")["Frogmite"]), None
    )
    assert (star.effective_power, star.effective_toughness) == (9, 9)
    game.sacrifice_permanents(mine[:3])
    # CR 704.3: the state check before anyone next receives priority is where
    # the board's continuous effects are recomputed (CR 611.3a).
    game.check_state_based_actions()
    assert (star.effective_power, star.effective_toughness) == (6, 6)

    game, _mine = _w1g3_table(set_pool, mine=["Seat of the Synod"] * 7)
    charge = _w1g3_charge(game, 0, broodstar)
    assert (charge.get("generic"), charge.get("U")) == (1, 2)


def test_w1g3_somber_hoverguard_flies_in_for_one_blue(set_pool):
    """Printed {5}{U}; five artifact lands leave {U}, one of them pays it, and
    a 3/2 flier enters. Four lands leave {1}{U}, which one land cannot pay."""
    game, _mine = _w1g3_table(
        set_pool, hand=["Somber Hoverguard"], mine=["Seat of the Synod"] * 5,
    )
    _w1g3_tap_blue(game, 1)
    cast = game.cast_from_hand(0, "Somber Hoverguard")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    drone = next(
        p for p in game.controlled_by(0) if p.card.name == "Somber Hoverguard"
    )
    assert (drone.effective_power, drone.effective_toughness) == (3, 2)
    assert game._has_keyword(drone, "flying")

    game, _mine = _w1g3_table(
        set_pool, hand=["Somber Hoverguard"], mine=["Seat of the Synod"] * 4,
    )
    _w1g3_tap_blue(game, 1)
    refused = game.cast_from_hand(0, "Somber Hoverguard")
    assert not refused.supported and "insufficient mana" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Somber Hoverguard"]

# ==== end W1G3 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
