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
#
# Turn the Tables (a CR 614.9 redirect of every source's combat damage onto
# an announced attacker) and Hallow (Hidden Retreat's spell shield with CR
# 615.5's life gain, carried onto a permanent spell's permanent by CR 400.7c).
from engine import Game as _W1G6Game
from engine.models import Permanent as _W1G6Permanent
from engine.models import PlayerState as _W1G6PlayerState
from engine.oracle import compile_card_oracle as _w1g6_compile
from engine.targeting import derive_cast_spec as _w1g6_derive_cast_spec

from tests.helpers import declare_attack as _w1g6_declare_attack
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=(), opponent_hand=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8),
        _W1G6PlayerState(
            name="Bob", hand=list(opponent_hand), library=[lea["Island"]] * 8,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._settle()
    return game


def _w1g6_put(game, seat, card, *, tapped=False):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    game._sync_control()
    return permanent


def test_w1g6_turn_the_tables_sends_the_attack_back_onto_one_attacker(set_pool):
    """"All combat damage that would be dealt to you this turn is dealt to
    target attacking creature instead." Bob attacks with a Grizzly Bears and
    a Hill Giant; Turn the Tables on the Giant moves both attackers' damage
    onto it — 5 damage, and it dies — and Alice takes none. The picker offers
    attacking creatures."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    tables = dst["Turn the Tables"]
    assert _w1g6_derive_cast_spec(tables, _w1g6_compile(tables)) == {
        "kind": "creature", "attacking_only": True,
    }
    game = _w1g6_table(set_pool, hand=[tables])
    bear = _w1g6_put(game, 1, lea["Grizzly Bears"])
    giant = _w1g6_put(game, 1, lea["Hill Giant"])
    _w1g6_declare_attack(game, 1)
    result = game.cast_from_hand(0, "Turn the Tables", target_permanent_ids=[giant.permanent_id])
    assert result.supported, result.details
    _w1g6_settle(game)
    _w1g6_drive_combat(game)
    assert game.players[0].life == 20
    assert not game.is_on_battlefield(giant)
    assert game.is_on_battlefield(bear)
    assert sum("damage to Alice is dealt to Hill Giant instead" in line for line in game.log) == 2


def test_w1g6_turn_the_tables_targets_only_an_attacker_and_moves_only_combat_damage(set_pool):
    """A creature that is not attacking is no legal target; and the record
    moves combat damage alone — a Lightning Bolt at Alice later in the turn
    still hits her."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(
        set_pool, hand=[dst["Turn the Tables"]], opponent_hand=[lea["Lightning Bolt"]],
    )
    attacker = _w1g6_put(game, 1, lea["Grizzly Bears"])
    home = _w1g6_put(game, 1, lea["Hill Giant"], tapped=True)
    _w1g6_declare_attack(game, 1)
    refused = game.cast_from_hand(0, "Turn the Tables", target_permanent_ids=[home.permanent_id])
    assert not refused.supported
    assert game.cast_from_hand(
        0, "Turn the Tables", target_permanent_ids=[attacker.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g6_settle(game)
    assert game.players[0].life == 17
    _w1g6_drive_combat(game)
    assert game.players[0].life == 17
    assert not game.is_on_battlefield(attacker)


def test_w1g6_turn_the_tables_does_nothing_once_its_target_is_gone(set_pool):
    """Ruling (2004-12-01): "If the targeted creature isn't on the
    battlefield when the combat damage would be dealt, the damage isn't
    redirected." The Giant is Terrored after Turn the Tables resolves; the
    Bears' 2 then land on Alice."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[dst["Turn the Tables"], lea["Terror"]])
    _w1g6_put(game, 1, lea["Grizzly Bears"])
    giant = _w1g6_put(game, 1, lea["Hill Giant"])
    _w1g6_declare_attack(game, 1)
    assert game.cast_from_hand(
        0, "Turn the Tables", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[giant.permanent_id]).supported
    _w1g6_settle(game)
    assert not game.is_on_battlefield(giant)
    _w1g6_drive_combat(game)
    assert game.players[0].life == 18


def test_w1g6_hallow_prevents_a_spells_damage_and_pays_its_caster(set_pool):
    """"Prevent all damage target spell would deal this turn. You gain life
    equal to the damage prevented this way." Bob's Lightning Bolt at Alice is
    on the stack; Hallow on it: the 3 is prevented and Alice gains 3. Aimed
    at Alice's creature instead, the creature lives and Alice still gains 3.
    The picker offers the stack."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    hallow = dst["Hallow"]
    assert _w1g6_derive_cast_spec(hallow, _w1g6_compile(hallow)) == {"kind": "stack"}
    game = _w1g6_table(set_pool, hand=[hallow], opponent_hand=[lea["Lightning Bolt"]])
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    result = game.cast_from_hand(0, "Hallow", target_stack_index=0)
    assert result.supported, result.details
    _w1g6_settle(game)
    assert [player.life for player in game.players] == [23, 20]

    game = _w1g6_table(set_pool, hand=[hallow], opponent_hand=[lea["Lightning Bolt"]])
    bear = _w1g6_put(game, 0, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bear.permanent_id],
    ).supported
    assert game.cast_from_hand(0, "Hallow", target_stack_index=0).supported
    _w1g6_settle(game)
    assert game.is_on_battlefield(bear) and bear.damage_marked == 0
    assert [player.life for player in game.players] == [23, 20]


def test_w1g6_hallow_follows_a_creature_spell_onto_the_battlefield(set_pool):
    """CR 400.7c: "Prevention effects that apply to damage from a permanent
    spell on the stack continue to apply to damage from the permanent that
    spell becomes." Hallow on Bob's Flametongue Kavu spell: the Kavu's entry
    trigger's 4 damage to Alice's Hill Giant is prevented, and the rider comes
    with it — Alice gains 4."""
    dst, lea, pls = set_pool("DST"), set_pool("LEA"), set_pool("PLS")
    game = _w1g6_table(
        set_pool, hand=[dst["Hallow"]], opponent_hand=[pls["Flametongue Kavu"]],
    )
    giant = _w1g6_put(game, 0, lea["Hill Giant"])
    assert game.queue_from_hand(
        1, "Flametongue Kavu", target_permanent_ids=[giant.permanent_id],
    ).supported
    assert game.cast_from_hand(0, "Hallow", target_stack_index=0).supported
    _w1g6_settle(game)
    assert game.is_on_battlefield(giant) and giant.damage_marked == 0
    assert [player.life for player in game.players] == [24, 20]

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
