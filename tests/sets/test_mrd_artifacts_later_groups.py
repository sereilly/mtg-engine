"""Mirrodin artifacts, the later groups' sections.

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


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Drive list: Rustspore Ram and Duskworker, the two artifact creatures among
# W1G2's supported-on-arrival cards, each given a headless game.
from engine import Game as _W1G2Game
from engine.aura_attachment import attach_aura as _w1g2_attach_aura
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import declare_attack as _w1g2_declare_attack
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8)
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


def test_w1g2_rustspore_ram_destroys_an_equipment_as_it_enters(set_pool):
    """"When this creature enters, destroy target Equipment." The target is
    the trigger's (CR 603.3d): an opponent's Equipment is destroyed and the
    creature it equipped loses the bonus; with no Equipment anywhere the
    trigger is removed from the stack and nothing else is touched."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, hand=[mrd["Rustspore Ram"]])
    bear = _w1g2_put(game, 1, lea["Grizzly Bears"])
    _w1g2_put(game, 1, mrd["Leonin Scimitar"], wearing=bear)
    assert game.cast_from_hand(0, "Rustspore Ram").supported
    _w1g2_drain(game)
    game.check_state_based_actions()
    assert [card.name for card in bob.graveyard] == ["Leonin Scimitar"]
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)

    game, _alice, bob = _w1g2_table(set_pool, hand=[mrd["Rustspore Ram"]])
    bear = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Rustspore Ram").supported
    _w1g2_drain(game)
    assert bob.graveyard == [] and game.is_on_battlefield(bear)
    assert any("no legal target (603.3d)" in line for line in game.log)


def test_w1g2_duskworker_regenerates_when_blocked_and_pumps_for_three(set_pool):
    """"Whenever this creature becomes blocked, regenerate it." Blocked by a
    Craw Wurm, the 2/2 takes lethal damage and regenerates (CR 701.19a:
    tapped, damage removed) instead of dying. "{3}: This creature gets +1/+0
    until end of turn." pays from the pool and pumps."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g2_table(set_pool)
    duskworker = _w1g2_put(game, 0, mrd["Duskworker"])
    _w1g2_put(game, 1, lea["Craw Wurm"])
    _w1g2_declare_attack(game, 0, blocks={0: 0})
    _w1g2_drain(game)
    assert duskworker.regeneration_shield == 1
    game.advance_combat_phase()
    _w1g2_drain(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(duskworker)
    assert duskworker.damage_marked == 0 and duskworker.tapped
    assert any(line == "Duskworker regenerated" for line in game.log)

    game, alice, _bob = _w1g2_table(set_pool)
    game.enforce_mana_costs = True
    duskworker = _w1g2_put(game, 0, mrd["Duskworker"])
    alice.mana_pool.update({"C": 3})
    result = game.activate_permanent_ability(
        0, "Duskworker", permanent_index=game.battlefield_index_of(duskworker),
    )
    assert result.supported, result.details
    _w1g2_drain(game)
    assert (duskworker.effective_power, duskworker.effective_toughness) == (3, 2)
    assert sum(alice.mana_pool.values()) == 0

# ==== end W1G2 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


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
