"""Onslaught instants.

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
from engine.models import Permanent as _W1G4Permanent
from engine.type_changes import gain_types as _w1g4_gain_types
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_creature(name, subtype):
    return _W1G4Permanent(card=_w1g4_mk_card(name, "{2}", f"Creature - {subtype}", ""))


def _w1g4_pump_game(set_pool, spell, mine, theirs, interactive=()):
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", hand=[set_pool("ONS")[spell]], battlefield=list(mine),
        ),
        _W1G4PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g4_pt(perm):
    return (perm.effective_power, perm.effective_toughness)


def test_w1g4_defensive_maneuvers_asks_on_resolution_and_toughens_only_that_type(set_pool):
    """"Creatures of the creature type of your choice get +0/+4 until end of
    turn." CR 608.2d: the type is chosen as the spell resolves, so the prompt
    holds the spell on the stack and nothing is pumped until the answer — then
    every creature of the type, the opponent's included, and nothing else."""
    elf = _w1g4_creature("Elf", "Elf")
    my_goblin = _w1g4_creature("My Goblin", "Goblin")
    their_goblin = _w1g4_creature("Their Goblin", "Goblin")
    zombie = _w1g4_creature("Zombie", "Zombie")
    game = _w1g4_pump_game(
        set_pool, "Defensive Maneuvers", [elf, my_goblin], [their_goblin, zombie],
        interactive=[0],
    )
    result = game.cast_from_hand(0, "Defensive Maneuvers")
    assert result.supported, result.details

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("creature_type_choice", 0)
    ]
    assert _w1g4_pt(my_goblin) == (2, 2), "nothing is pumped before the answer"

    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g4_resolve_stack(game)
    assert _w1g4_pt(my_goblin) == (2, 6)
    assert _w1g4_pt(their_goblin) == (2, 6)
    assert _w1g4_pt(elf) == (2, 2)
    assert _w1g4_pt(zombie) == (2, 2)
    assert any("Defensive Maneuvers: chose goblin" in line for line in game.log)


def test_w1g4_defensive_maneuvers_default_names_the_casters_own_type(set_pool):
    """A seat nobody asks names the type its own creatures have most of, net
    of the opponents' — a pump aimed at the opponents' type is not a choice a
    player makes. Elves 2 − 0 beat Goblins 1 − 3."""
    elves = [_w1g4_creature("Elf A", "Elf"), _w1g4_creature("Elf B", "Elf")]
    my_goblin = _w1g4_creature("My Goblin", "Goblin")
    theirs = [_w1g4_creature(f"Goblin {n}", "Goblin") for n in range(3)]
    game = _w1g4_pump_game(set_pool, "Defensive Maneuvers", [*elves, my_goblin], theirs)
    game.cast_from_hand(0, "Defensive Maneuvers")
    _w1g4_resolve_stack(game)

    assert game.pending_choices == []
    assert [_w1g4_pt(perm) for perm in elves] == [(2, 6), (2, 6)]
    assert _w1g4_pt(my_goblin) == (2, 2)
    assert all(_w1g4_pt(perm) == (2, 2) for perm in theirs)
    assert any("Defensive Maneuvers: chose elf" in line for line in game.log)


def test_w1g4_tribal_unity_pumps_the_named_type_by_x_through_the_layers(set_pool):
    """"Creatures of the creature type of your choice get +X/+X until end of
    turn." X is the announced one (CR 107.3a), and the type is read through
    layer 4: a creature that *became* a Goblin is one (CR 613.1d), and the
    Elf beside it that did not is left alone."""
    became_goblin = _w1g4_creature("Shifted Elf", "Elf")
    _w1g4_gain_types(became_goblin, subtypes=("goblin",), source="test")
    elf = _w1g4_creature("Elf", "Elf")
    goblin = _w1g4_creature("Goblin", "Goblin")
    game = _w1g4_pump_game(
        set_pool, "Tribal Unity", [became_goblin, elf], [goblin], interactive=[0],
    )
    result = game.cast_from_hand(0, "Tribal Unity", x_value=3)
    assert result.supported, result.details
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g4_resolve_stack(game)

    assert _w1g4_pt(became_goblin) == (5, 5)
    assert _w1g4_pt(goblin) == (5, 5)
    assert _w1g4_pt(elf) == (2, 2)


def test_w1g4_a_pump_with_no_type_to_name_pumps_nothing(set_pool):
    """No creature of the caster's means no type worth naming: the default is
    no choice, and the buff reads that as pumping nothing — never as a buff
    with no narrowing, which would pump the opponent's whole board."""
    theirs = [_w1g4_creature("Goblin", "Goblin")]
    game = _w1g4_pump_game(set_pool, "Defensive Maneuvers", [], theirs)
    game.cast_from_hand(0, "Defensive Maneuvers")
    _w1g4_resolve_stack(game)

    assert _w1g4_pt(theirs[0]) == (2, 2)
    assert any("no creature type was chosen" in line for line in game.log)

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
