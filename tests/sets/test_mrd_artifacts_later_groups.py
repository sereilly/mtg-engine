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

from engine.game import Game as _W1G11Game
from engine.models import Permanent as _W1G11Permanent
from engine.models import PlayerState as _W1G11PlayerState
from engine.oracle import compile_card_oracle as _w1g11_compile
from engine.targeting import derive_activation_spec as _w1g11_activation_spec

from tests.helpers import resolve_stack as _w1g11_resolve_stack


def _w1g11_table(set_pool, *, library=(), bob_library=(), hand=()):
    lea = set_pool("LEA")
    alice = _W1G11PlayerState(
        name="Alice", hand=list(hand),
        library=list(library) or [lea["Plains"]] * 6,
    )
    bob = _W1G11PlayerState(
        name="Bob", library=list(bob_library) or [lea["Island"]] * 6,
    )
    game = _W1G11Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g11_put(game, seat, card):
    permanent = _W1G11Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g11_activate(game, seat, perm, **targets):
    result = game.activate_permanent_ability(
        seat, perm.card.name, permanent_index=game.battlefield_index_of(perm),
        ability_index=0, **targets,
    )
    assert result.supported, result.details
    return result


def _w1g11_belch(set_pool, library, **targets):
    mrd = set_pool("MRD")
    game, alice, bob = _w1g11_table(set_pool, library=library)
    belcher = _w1g11_put(game, 0, mrd["Goblin Charbelcher"])
    _w1g11_activate(game, 0, belcher, **targets)
    _w1g11_resolve_stack(game)
    return game, alice, bob


def test_w1g11_charbelcher_counts_the_nonland_cards_before_the_land(set_pool):
    lea = set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Lightning Bolt"], lea["Island"],
               lea["Shivan Dragon"]]
    game, alice, bob = _w1g11_belch(set_pool, library, target_player_index=1)
    assert bob.life == 18
    # The revealed pile goes to the bottom; the card under it is now on top.
    assert alice.library[0].name == "Shivan Dragon"
    assert sorted(c.name for c in alice.library[1:]) == [
        "Grizzly Bears", "Island", "Lightning Bolt",
    ]


def test_w1g11_charbelcher_doubles_on_a_mountain(set_pool):
    lea = set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Lightning Bolt"], lea["Shivan Dragon"],
               lea["Mountain"], lea["Island"]]
    game, alice, bob = _w1g11_belch(set_pool, library, target_player_index=1)
    assert bob.life == 20 - 6
    assert alice.library[0].name == "Island"


def test_w1g11_charbelcher_with_no_land_deals_one_per_card_revealed(set_pool):
    """The ruling (2016-06-08): no land revealed is damage equal to the
    number of cards revealed — the whole library."""
    lea = set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Lightning Bolt"], lea["Shivan Dragon"]]
    game, alice, bob = _w1g11_belch(set_pool, library, target_player_index=1)
    assert bob.life == 17
    assert len(alice.library) == 3


def test_w1g11_charbelcher_aims_at_a_creature_and_the_picker_offers_any_target(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    (ability,) = _w1g11_compile(mrd["Goblin Charbelcher"]).activated_abilities
    spec = _w1g11_activation_spec(ability)
    assert spec is not None and spec.get("kind") == "any", spec
    game, alice, bob = _w1g11_table(
        set_pool, library=[lea["Grizzly Bears"], lea["Mountain"]],
    )
    belcher = _w1g11_put(game, 0, mrd["Goblin Charbelcher"])
    dragon = _w1g11_put(game, 1, lea["Shivan Dragon"])
    _w1g11_activate(game, 0, belcher, target_permanent_ids=[dragon.permanent_id])
    _w1g11_resolve_stack(game)
    assert dragon.damage_marked == 2
    assert bob.life == 20

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
