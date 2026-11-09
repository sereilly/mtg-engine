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
#
# Drive list: Contaminated Bond, whose "its controller" read a record nothing
# wrote until the combat fire sites froze the combatant's seat.
from engine import Game as _W1G2Game
from engine.aura_attachment import attach_aura as _w1g2_attach_aura
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import declare_attack as _w1g2_declare_attack
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", library=[lea["Plains"]] * 8)
    bob = _W1G2PlayerState(name="Bob", library=[lea["Island"]] * 8)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g2_put(game, seat, card, *, wearing=None):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    if wearing is not None:
        _w1g2_attach_aura(permanent, wearing)
        game._recompute_continuous_effects()
    return permanent


def _w1g2_drain(game):
    """Answer what blocks the game and drain the stack, until nothing does."""
    for _ in range(20):
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        elif game.stack:
            _w1g2_resolve_stack(game)
        else:
            return


def test_w1g2_contaminated_bond_drains_the_enchanted_creatures_controller(set_pool):
    """"Whenever enchanted creature attacks or blocks, its controller loses 3
    life." Bob's Bond on Alice's Grizzly Bears: Alice loses 3 when the Bears
    attack and 3 when they block — the creature's controller, not the
    Aura's (CR 603.3a gives the Aura's controller the ability; "its" is the
    creature). Before the fire sites froze the seat nobody lost anything."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    for blocking in (False, True):
        game, alice, bob = _w1g2_table(set_pool)
        bears = _w1g2_put(game, 0, lea["Grizzly Bears"])
        _w1g2_put(game, 1, lea["Grizzly Bears"])
        _w1g2_put(game, 1, mrd["Contaminated Bond"], wearing=bears)
        if blocking:
            _w1g2_declare_attack(game, 1, blocks={0: 0})
        else:
            _w1g2_declare_attack(game, 0)
        _w1g2_drain(game)
        assert (alice.life, bob.life) == (17, 20), blocking
        assert any("Contaminated Bond: Alice lost 3 life" in line for line in game.log)


def test_w1g2_contaminated_bond_on_its_own_controllers_creature(set_pool):
    """The same seat when the Aura's controller is the creature's: Alice's
    Bond on Alice's own attacker costs Alice the 3."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g2_table(set_pool)
    bears = _w1g2_put(game, 0, lea["Grizzly Bears"])
    _w1g2_put(game, 0, mrd["Contaminated Bond"], wearing=bears)
    _w1g2_declare_attack(game, 0)
    _w1g2_drain(game)
    assert (alice.life, bob.life) == (17, 20)

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

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
