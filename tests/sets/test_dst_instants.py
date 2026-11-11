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

from tests.helpers import drive_combat as _w1g9_drive_combat
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



def _w1g9_attackers_table(set_pool):
    """Alice in her declare attackers step with Grizzly Bears and Scathe
    Zombies attacking and Llanowar Elves at home; Tears of Rage in hand."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool, hand=[dst["Tears of Rage"]])
    bears = _w1g9_put(game, 0, lea["Grizzly Bears"])
    zombies = _w1g9_put(game, 0, lea["Scathe Zombies"])
    elves = _w1g9_put(game, 0, lea["Llanowar Elves"])
    return game, alice, bob, (bears, zombies, elves)


def test_w1g9_tears_of_rage_pumps_the_attackers_by_their_number_then_sacrifices_them(set_pool):
    """"Attacking creatures you control get +X/+0 until end of turn, where X is
    the number of attacking creatures. Sacrifice those creatures at the
    beginning of the next end step." Two attackers: each gets +2/+0, the Elves
    at home get nothing; at the end step exactly those two are sacrificed."""
    game, alice, bob, (bears, zombies, elves) = _w1g9_attackers_table(set_pool)
    refused = game.cast_from_hand(0, "Tears of Rage")
    assert not refused.supported, "only during the declare attackers step"
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [alice.battlefield.index(bears), alice.battlefield.index(zombies)]
    ok, why = game.declare_attackers(0, slots, defending_player_index=1)
    assert ok, why
    result = game.cast_from_hand(0, "Tears of Rage")
    assert result.supported, result.details
    _w1g9_settle(game)
    assert (bears.effective_power, zombies.effective_power) == (4, 4)
    assert elves.effective_power == 1
    _w1g9_drive_combat(game)
    assert bob.life == 12
    game.resolve_end_step(0)
    _w1g9_settle(game)
    assert [p.card.name for p in alice.battlefield] == ["Llanowar Elves"]
    assert {"Grizzly Bears", "Scathe Zombies"} <= {c.name for c in alice.graveyard}
    assert any("Tears of Rage: sacrificed Grizzly Bears, Scathe Zombies" in line
               for line in game.log)


def test_w1g9_tears_of_rage_sacrifices_the_set_it_pumped_not_the_attackers_by_then(set_pool):
    """"Those creatures" is the set the first sentence reached (CR 611.2c), so
    the Bears, no longer attacking once combat is over, are still sacrificed,
    and the Zombies, already gone, are skipped (CR 608.2b)."""
    game, alice, bob, (bears, zombies, elves) = _w1g9_attackers_table(set_pool)
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [alice.battlefield.index(bears), alice.battlefield.index(zombies)]
    assert game.declare_attackers(0, slots, defending_player_index=1)[0]
    assert game.cast_from_hand(0, "Tears of Rage").supported
    _w1g9_settle(game)
    game.sacrifice_permanent(zombies)
    _w1g9_drive_combat(game)
    assert not bears.attacking
    game.resolve_end_step(0)
    _w1g9_settle(game)
    assert [p.card.name for p in alice.battlefield] == ["Llanowar Elves"]

# ==== end W1G9 ======================================================
