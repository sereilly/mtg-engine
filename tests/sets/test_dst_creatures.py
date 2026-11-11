"""Darksteel creatures (legendary ones too).

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
#
# Leonin Shikari's instant-speed equip, and the drive list's creatures
# (Auriok Glaivemaster, Steelshaper Apprentice, Slobad, Pteron Ghost).

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.equipment import equipped_creature as _w1g2_equipped
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import declare_attack as _w1g2_declare_attack
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, interactive=()):
    island = set_pool("LEA")["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[island] * 20) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_activate(game, seat, permanent, **kwargs):
    return game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), **kwargs,
    )


def test_w1g2_leonin_shikari_equips_at_instant_speed(set_pool):
    """"You may activate equip abilities any time you could cast an instant."
    CR 304.5: with priority — here in the declare blockers step, onto an
    attacker (the 2004-12-01 ruling's own example). Without the Shikari the
    same activation is refused (CR 702.6a's "Activate only as a sorcery"); an
    opponent's Shikari is not "you" (CR 109.5); and a sorcery-speed ability
    that is not an equip ability stays sorcery-speed."""
    dst, mrd, lea = set_pool("DST"), set_pool("MRD"), set_pool("LEA")

    game = _w1g2_table(set_pool)
    _w1g2_put(game, dst["Leonin Shikari"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 0)
    basket = _w1g2_put(game, set_pool("6ED")["Snake Basket"], 0)
    _w1g2_declare_attack(game, 0)
    assert game.has_priority(0)
    result = _w1g2_activate(game, 0, star, target_permanent_ids=[bears.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert _w1g2_equipped(star) is bears
    assert bears.effective_power == 4
    refused = _w1g2_activate(game, 0, basket, x_value=1)
    assert not refused.supported
    assert "sorcery" in str(refused).lower()

    # The same table with the Shikari on the other side.
    game = _w1g2_table(set_pool)
    _w1g2_put(game, dst["Leonin Shikari"], 1)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 0)
    _w1g2_declare_attack(game, 0)
    refused = _w1g2_activate(game, 0, star, target_permanent_ids=[bears.permanent_id])
    assert not refused.supported
    assert "sorcery" in str(refused).lower()
    assert _w1g2_equipped(star) is None

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
