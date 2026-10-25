"""Onslaught artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ONS")` / `set_cards("ONS")` — never a new
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

from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.layer_bridge import computed_types as _w1g4_computed_types
from engine.models import Permanent as _W1G4Permanent
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import _nosick as _w1g4_nosick
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_card(name, subtype):
    return _w1g4_mk_card(name, "{2}", f"Creature - {subtype}", "")


def _w1g4_enter(set_pool, name, *, x_value=None, library=()):
    """*name* cast by P1 over two Elves of P1's and three Goblins of P2's."""
    elves = [_w1g4_nosick(_W1G4Permanent(card=_w1g4_card(f"My Elf {n}", "Elf"))) for n in range(2)]
    goblins = [_W1G4Permanent(card=_w1g4_card(f"Their Goblin {n}", "Goblin")) for n in range(3)]
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", hand=[set_pool("ONS")[name]], battlefield=list(elves),
            library=list(library),
        ),
        _W1G4PlayerState(name="P2", battlefield=list(goblins)),
    ])
    game.enforce_mana_costs = False
    kwargs = {"x_value": x_value} if x_value is not None else {}
    assert game.cast_from_hand(0, name, **kwargs).supported
    _w1g4_resolve_stack(game)
    source = _w1g4_nosick(
        next(perm for perm in game.controlled_by(0) if perm.card.name == name)
    )
    return game, source, elves, goblins


def test_w1g4_doom_cannon_names_a_type_its_controller_can_sacrifice(set_pool):
    """"As this artifact enters, choose a creature type. {3}, {T}, Sacrifice a
    creature of the chosen type: This artifact deals 3 damage to any target."
    A cost is paid with its payer's own creatures (CR 701.21a), so the default
    names the controller's type; at ingest it named the opponents' and the
    Cannon could never be activated."""
    game, cannon, elves, _goblins = _w1g4_enter(set_pool, "Doom Cannon")
    assert cannon.metadata["chosen_creature_type"] == "elf"

    result = game.activate_permanent_ability(0, "Doom Cannon", target_player_index=1)
    assert result.supported, result.details
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 17
    assert sum(
        1 for perm in game.controlled_by(0) if any(perm is elf for elf in elves)
    ) == 1


def test_w1g4_riptide_replicator_makes_a_token_of_the_chosen_color_and_type(set_pool):
    """"As this artifact enters, choose a color and a creature type. This
    artifact enters with X charge counters on it. {4}, {T}: Create an X/X
    creature token of the chosen color and type, where X is the number of
    charge counters on this artifact." The token is the type its controller's
    own cards have most of, at X = 2."""
    game, replicator, _elves, _goblins = _w1g4_enter(
        set_pool, "Riptide Replicator", x_value=2,
        library=[_w1g4_card("Library Elf", "Elf")] * 3,
    )
    chosen = replicator.metadata["chosen_creature_type"]
    assert chosen == "elf"
    assert game.activate_permanent_ability(0, "Riptide Replicator").supported
    _w1g4_resolve_stack(game)

    (token,) = [perm for perm in game.controlled_by(0) if perm.metadata.get("is_token")]
    assert (token.effective_power, token.effective_toughness) == (2, 2)
    assert chosen in _w1g4_computed_types(token)[1]
    assert set(token.effective_colors) == {replicator.metadata["chosen_color"]}

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


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================
