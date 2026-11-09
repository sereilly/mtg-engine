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
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.equipment import attach_equipment as _w1g7_attach
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_march_board(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    names = ["Grizzly Bears", "Bonesplitter", "Serum Tank", "Seat of the Synod", "Ornithopter"]
    perms = {
        name: _w1g7_nosick(_w1g7_Permanent(card=mrd[name] if name in mrd else lea[name]))
        for name in names
    }
    p1 = _w1g7_PlayerState(
        name="P1", battlefield=list(perms.values()),
        hand=[mrd["March of the Machines"]], library=[lea["Island"]] * 10,
    )
    p2 = _w1g7_PlayerState(name="P2", library=[lea["Island"]] * 10)
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    assert _w1g7_attach(game, perms["Bonesplitter"], perms["Grizzly Bears"])
    return game, p1, perms


def test_w1g7_march_of_the_machines_animates_each_noncreature_artifact(set_pool):
    """"Each noncreature artifact is an artifact creature with power and
    toughness each equal to its mana value." Titania's Song's sentence without
    the ability loss: a row in `global_statics` beside it.

    The 2004-12-01 rulings, each driven: an Equipment that becomes a creature
    becomes unattached and stays on the battlefield (CR 301.5c, 704.5n); an
    artifact land has mana value 0 and dies as a 0/0 (704.5f); an artifact
    that already was a creature is not a *noncreature* artifact and keeps its
    own P/T. Abilities stay (a Tank is still a Tank). When March leaves, all of
    it ends."""
    game, p1, perms = _w1g7_march_board(set_pool)
    bears, splitter, tank = perms["Grizzly Bears"], perms["Bonesplitter"], perms["Serum Tank"]
    seat, thopter = perms["Seat of the Synod"], perms["Ornithopter"]
    assert (bears.effective_power, bears.effective_toughness) == (4, 2)

    assert game.cast_from_hand(0, "March of the Machines").supported
    _w1g7_resolve(game)
    game.check_state_based_actions()

    assert splitter.is_creature and splitter.has_type("artifact")
    assert (splitter.effective_power, splitter.effective_toughness) == (1, 1)
    assert game.is_on_battlefield(splitter), "unattached, not destroyed"
    assert (bears.effective_power, bears.effective_toughness) == (2, 2), "it fell off"
    assert any("Bonesplitter became unattached" in line for line in game.log)
    assert tank.is_creature and (tank.effective_power, tank.effective_toughness) == (3, 3)
    assert not game.is_on_battlefield(seat)
    assert [c.name for c in p1.graveyard] == ["Seat of the Synod"]
    assert (thopter.effective_power, thopter.effective_toughness) == (0, 2)
    assert game.can_attack(tank, 1), "under its controller's control since the turn began"

    march = next(p for p in p1.battlefield if p.card.name == "March of the Machines")
    game.sacrifice_permanent(march)
    game.check_state_based_actions()
    assert not splitter.is_creature and not tank.is_creature
    assert thopter.is_creature


def test_w1g7_march_of_the_machines_an_artifact_that_just_arrived_is_summoning_sick(set_pool):
    """2009-10-01 ruling: a noncreature permanent that turns into a creature is
    subject to CR 302.6 — one that entered this turn cannot attack."""
    game, p1, _perms = _w1g7_march_board(set_pool)
    assert game.cast_from_hand(0, "March of the Machines").supported
    _w1g7_resolve(game)
    sphere = _w1g7_Permanent(card=set_pool("MRD")["Chromatic Sphere"])
    game._put_permanent_onto_battlefield(0, sphere, None)
    game.check_state_based_actions()
    assert sphere.is_creature and (sphere.effective_power, sphere.effective_toughness) == (1, 1)
    assert not game.can_attack(sphere, 1)


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
