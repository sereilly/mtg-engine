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
#
# Sphere of Purity: "If an artifact would deal damage to you, prevent 1 of
# that damage." Urza's Armor's static shield (``prevention/blankets.py``)
# narrowed by the source's card type, asked as the damage would be dealt
# (CR 609.7c) — a sacrificed Spellbomb's damage is an artifact's.

from engine import Game as _w1g12_Game
from engine import PlayerState as _w1g12_PlayerState
from engine.models import Permanent as _w1g12_Permanent
from tests.helpers import _nosick as _w1g12_nosick
from tests.helpers import declare_attack as _w1g12_declare_attack
from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w1g12_table(set_pool, *, mine=(), theirs=(), opponent_hand=()):
    card = lambda name: _w1g12_card(set_pool, name)  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState("A", library=[card("Forest")] * 12),
        _w1g12_PlayerState(
            "B", hand=[card(n) for n in opponent_hand],
            library=[card("Forest")] * 12,
        ),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g12_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w1g12_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def test_w1g12_sphere_of_purity_shaves_an_artifacts_damage_to_you(set_pool):
    # The source is sacrificed to pay the cost: what deals the damage is an
    # artifact that is no longer on the battlefield (CR 609.7c).
    game, _, _ = _w1g12_table(
        set_pool, mine=["Sphere of Purity"], theirs=["Pyrite Spellbomb"],
    )
    game.active_player_index = 1
    assert game.activate_permanent_ability(
        1, "Pyrite Spellbomb", target_player_index=0, ability_index=0,
    ).supported
    _w1g12_resolve_stack(game)
    assert game.players[0].life == 19
    assert "A prevented 1 of 2 damage (Sphere of Purity)" in game.log


def test_w1g12_sphere_of_purity_shaves_artifact_combat_damage_only(set_pool):
    # Alpha Myr (an artifact creature, 2) and Grizzly Bears (2) both
    # unblocked: one point of the Myr's is prevented and none of the Bears'.
    game, _, _ = _w1g12_table(
        set_pool, mine=["Sphere of Purity"], theirs=["Alpha Myr", "Grizzly Bears"],
    )
    _w1g12_declare_attack(game, 1)
    game.advance_combat_phase()
    assert game.players[0].life == 17


def test_w1g12_sphere_of_purity_ignores_a_spell_and_covers_only_you(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Sphere of Purity"], opponent_hand=["Lightning Bolt"],
    )
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g12_resolve_stack(game)
    assert game.players[0].life == 17
    # The opponent's Sphere protects its own controller, not the player an
    # artifact of theirs is not hitting.
    game, _, _ = _w1g12_table(
        set_pool, mine=["Pyrite Spellbomb"], theirs=["Sphere of Purity"],
    )
    assert game.activate_permanent_ability(
        0, "Pyrite Spellbomb", target_player_index=1, ability_index=0,
    ).supported
    _w1g12_resolve_stack(game)
    assert game.players[1].life == 19

# ==== end W1G12 ======================================================
