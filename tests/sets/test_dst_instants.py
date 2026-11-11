"""Darksteel instants.

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
#
# Purge's union of two whole noun phrases, read into the filter "a black or
# artifact creature" already builds; Tears of Rage below.
from engine import Game as _W1G9Game
from engine.models import Permanent as _W1G9Permanent
from engine.models import PlayerState as _W1G9PlayerState
from engine.oracle import compile_card_oracle as _w1g9_compile
from engine.targeting import derive_cast_spec as _w1g9_derive_cast_spec

from tests.helpers import settle as _w1g9_settle


def _w1g9_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    alice = _W1G9PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8)
    bob = _W1G9PlayerState(name="Bob", library=[lea["Swamp"]] * 8)
    game = _W1G9Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g9_put(game, seat, card):
    permanent = _W1G9Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g9_purge_destroys_an_artifact_creature_or_a_black_creature_only(set_pool):
    """"Destroy target artifact creature or black creature." The picker offers
    exactly the union — an artifact creature of any colour and a black
    creature of any type — and refuses a green creature and a noncreature
    artifact."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    purge = dst["Purge"]
    assert _w1g9_compile(purge).supported
    spec = _w1g9_derive_cast_spec(purge, _w1g9_compile(purge))
    assert spec.get("filter", spec).get("type_filter", spec.get("kind")) is not None, spec

    for name, legal in (
        ("Juggernaut", True), ("Scathe Zombies", True),
        ("Grizzly Bears", False), ("Sol Ring", False),
    ):
        game, alice, bob = _w1g9_table(set_pool, hand=[purge])
        victim = _w1g9_put(game, 1, lea[name])
        result = game.cast_from_hand(0, "Purge", target_permanent_ids=[victim.permanent_id])
        if not legal:
            assert not result.supported or not game.stack, (name, result.details)
            assert game.is_on_battlefield(victim), name
            continue
        assert result.supported, (name, result.details)
        _w1g9_settle(game)
        assert not game.is_on_battlefield(victim), name
        assert lea[name] in bob.graveyard, name


def test_w1g9_purge_ignores_a_regeneration_shield(set_pool):
    """"It can't be regenerated." Drudge Skeletons regenerates in response;
    the shield does not save it (CR 701.19c)."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool, hand=[dst["Purge"]])
    skeletons = _w1g9_put(game, 1, lea["Drudge Skeletons"])
    shield = game.activate_permanent_ability(1, "Drudge Skeletons")
    assert shield.supported, shield.details
    _w1g9_settle(game)
    result = game.cast_from_hand(0, "Purge", target_permanent_ids=[skeletons.permanent_id])
    assert result.supported, result.details
    _w1g9_settle(game)
    assert not game.is_on_battlefield(skeletons)
    assert lea["Drudge Skeletons"] in bob.graveyard

# ==== end W1G9 ======================================================
