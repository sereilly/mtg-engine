"""Mirrodin enchantments, Auras included.

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


def _w1g3_hum_table(set_pool, mine=(), theirs=(), hand=(), their_hand=(), active=0):
    """Hum of the Radix on seat 0's battlefield beside *mine*; mana costs
    enforced for both seats."""
    mrd = set_pool("MRD")
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", hand=[mrd[n] for n in hand]),
        _W1G3PlayerState(name="W1G3-B", hand=[mrd[n] for n in their_hand]),
    ])
    w1g3_game.enforce_mana_costs = True
    w1g3_game.interactive_seats = set()
    w1g3_game.active_player_index = active
    for w1g3_seat, w1g3_names in enumerate((("Hum of the Radix",) + tuple(mine), theirs)):
        for w1g3_name in w1g3_names:
            w1g3_game._put_permanent_onto_battlefield(
                w1g3_seat, _W1G3Permanent(card=mrd[w1g3_name]), None
            )
    return w1g3_game  # _w1g3_hum_table


def _w1g3_tap_all(game, seat):
    for w1g3_land in list(game.controlled_by(seat)):
        if w1g3_land.has_type("land") and not w1g3_land.tapped:
            assert game.tap_land_for_mana(
                seat, w1g3_land.card.name,
                (w1g3_land.effective_produced_mana or ("C",))[0],
                permanent_id=w1g3_land.permanent_id,
            )  # _w1g3_tap_all


def test_w1g3_hum_taxes_each_artifact_spell_by_its_casters_artifacts(set_pool):
    """"Each artifact spell costs {1} more to cast for each artifact its
    controller controls." "Its controller" is the spell's — the player who
    cast it (CR 405.4) — so the Hum taxes its own controller by that
    player's board and an opponent by theirs, and a nonartifact spell not at
    all. Under it, with four artifact lands, Iron Myr is {2}+{4}; Frogmite is
    {4}+{4}-{4} (CR 601.2f: increases, then reductions); a Thoughtcast is just
    its affinity price, {U}. The opponent with two artifacts pays {2} for an
    Ornithopter, and with none pays nothing and is named by no tax."""
    mrd = set_pool("MRD")
    game = _w1g3_hum_table(
        set_pool, mine=["Seat of the Synod"] * 4, theirs=["Great Furnace"] * 2,
    )
    for name, generic in (("Iron Myr", 6), ("Frogmite", 4), ("Thoughtcast", 0)):
        assert _w1g3_charge(game, 0, mrd[name]).get("generic") == generic, name
    assert _w1g3_charge(game, 1, mrd["Ornithopter"]).get("generic") == 2
    assert _w1g3_charge(game, 1, mrd["Thoughtcast"]).get("generic") == 2

    game = _w1g3_hum_table(set_pool)
    assert _w1g3_charge(game, 1, mrd["Ornithopter"]).get("generic") == 0
    assert _w1g3_charge(game, 0, mrd["Iron Myr"]).get("generic") == 2


def test_w1g3_hum_charges_the_cast_and_names_itself_in_the_log(set_pool):
    """The cast path charges what the price readers quote. The Hum's own
    controller casts Frogmite for {4} off four artifact lands (taxed {4},
    discounted {4}) and cannot cast Iron Myr for {6} off the same four. On the
    opponent's turn, their two artifact lands pay the {2} an Ornithopter now
    costs, and the log names the Hum."""
    game = _w1g3_hum_table(
        set_pool, mine=["Seat of the Synod"] * 4, hand=["Iron Myr", "Frogmite"],
    )
    _w1g3_tap_all(game, 0)
    refused = game.cast_from_hand(0, "Iron Myr")
    assert not refused.supported and "insufficient mana" in refused.details
    assert sum(game.players[0].mana_pool.values()) == 4
    cast = game.cast_from_hand(0, "Frogmite")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert "Frogmite is taxed by Hum of the Radix" in game.log
    assert sum(game.players[0].mana_pool.values()) == 0
    assert [p.card.name for p in game.controlled_by(0)].count("Frogmite") == 1

    game = _w1g3_hum_table(
        set_pool, theirs=["Great Furnace"] * 2, their_hand=["Ornithopter"],
        active=1,
    )
    cast = game.cast_from_hand(1, "Ornithopter")
    assert not cast.supported and "insufficient mana" in cast.details
    _w1g3_tap_all(game, 1)
    cast = game.cast_from_hand(1, "Ornithopter")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert "Ornithopter is taxed by Hum of the Radix" in game.log
    assert [p.card.name for p in game.controlled_by(1)].count("Ornithopter") == 1

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

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
