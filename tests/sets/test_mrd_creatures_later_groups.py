"""Mirrodin creatures, the later groups' sections (legendary ones too).

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


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


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
# The drive list: Mirrodin creatures that compiled supported on arrival and
# had never been run, each given a game through the real entry points.

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


def _w1g12_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=(),
                 graveyard=(), interactive=()):
    """Seat 0 (A) in its first main phase, mana off; each named permanent
    untapped and able to act."""
    card = lambda name: _w1g12_card(set_pool, name)  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState(
            "A", hand=[card(n) for n in hand], library=[card("Forest")] * 12,
            graveyard=[card(n) for n in graveyard],
        ),
        _w1g12_PlayerState(
            "B", hand=[card(n) for n in opponent_hand],
            library=[card("Island")] * 12,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
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


def test_w1g12_rustmouth_ogre_destroys_an_artifact_the_damaged_player_controls(set_pool):
    # "…you may destroy target artifact that player controls." The seat is
    # the damage event's (pinned in test_stack_targets for that reason):
    # through a real combat damage step only B's artifacts are offered, A's
    # own Sol Ring is refused, and the one named is destroyed.
    game, (_ogre, sol), (scimitar, thopter) = _w1g12_table(
        set_pool, mine=["Rustmouth Ogre", "Sol Ring"],
        theirs=["Leonin Scimitar", "Ornithopter"], interactive=(0,),
    )
    _w1g12_declare_attack(game, 0)
    game.advance_combat_phase()
    assert game.players[1].life == 15
    (choice,) = game.pending_choices
    assert choice.kind == "trigger_target"
    offered = {entry["permanent_id"] for entry in choice.data["targets"]}
    assert offered == {scimitar.permanent_id, thopter.permanent_id}
    assert not game.confirm_trigger_target(0, permanent_id=sol.permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=thopter.permanent_id)
    _w1g12_resolve_stack(game)
    assert game.confirm_optional_pay(0, accept=True)
    _w1g12_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Leonin Scimitar"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Rustmouth Ogre", "Sol Ring"]


def test_w1g12_rustmouth_ogre_default_seat_takes_the_damaged_players_artifact(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Rustmouth Ogre", "Sol Ring"], theirs=["Leonin Scimitar"],
    )
    _w1g12_declare_attack(game, 0)
    game.advance_combat_phase()
    _w1g12_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g12_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == []
    assert "Sol Ring" in [p.card.name for p in game.controlled_by(0)]

# ==== end W1G12 ======================================================
