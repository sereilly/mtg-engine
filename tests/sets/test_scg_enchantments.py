"""Scourge enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
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
# Decree of Silence: its opponent-cast trigger compiled to nothing until this
# round ("If there are three or more depletion counters on this enchantment"
# was a condition no production read), and its cycle trigger counters a
# spell on the stack.
from engine import Game as _W1G2Game
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand, bob_hand, *, active=1):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 6)
    bob = _W1G2PlayerState(name="Bob", hand=list(bob_hand), library=[lea["Island"]] * 6)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = active
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g2_put(game, seat, card):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    return permanent


def _w1g2_drain(game):
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)


def _w1g2_depletion(permanent):
    return permanent.metadata.get("depletion_counters", 0)


def test_w1g2_decree_of_silence_counters_each_opponent_spell_and_dies_at_three(set_pool):
    """"Whenever an opponent casts a spell, counter that spell and put a
    depletion counter on this enchantment. If there are three or more
    depletion counters on this enchantment, sacrifice it." Three spells are
    countered; the fourth resolves."""
    lea = set_pool("LEA")
    game, alice, bob = _w1g2_table(
        set_pool, [], [lea["Lightning Bolt"], lea["Lightning Bolt"],
                       lea["Grizzly Bears"], lea["Grizzly Bears"]],
    )
    decree = _w1g2_put(game, 0, set_pool("SCG")["Decree of Silence"])

    for count, name in enumerate(("Lightning Bolt", "Lightning Bolt", "Grizzly Bears"), 1):
        assert game.queue_from_hand(1, name, target_player_index=0).supported
        assert game.stack[-1].card.name == "Decree of Silence"
        _w1g2_drain(game)
        assert alice.life == 20
        if count < 3:
            assert _w1g2_depletion(decree) == count
            assert game.is_on_battlefield(decree)
    assert not game.is_on_battlefield(decree)
    assert [c.name for c in alice.graveyard] == ["Decree of Silence"]
    assert [c.name for c in bob.graveyard] == ["Lightning Bolt", "Lightning Bolt", "Grizzly Bears"]

    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g2_drain(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_w1g2_decree_of_silence_leaves_its_controllers_spells_alone(set_pool):
    lea = set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, [lea["Lightning Bolt"]], [], active=0)
    decree = _w1g2_put(game, 0, set_pool("SCG")["Decree of Silence"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert [item.card.name for item in game.stack] == ["Lightning Bolt"]
    _w1g2_drain(game)
    assert bob.life == 17 and _w1g2_depletion(decree) == 0


def test_w1g2_two_decrees_of_silence_counter_that_spell_and_no_bystander(set_pool):
    """"Counter **that spell**" is the spell the trigger fired on, found by
    identity (CR 603.3's trigger sits above it). Alice bolts Bob; Bob bolts
    back in response and both Decrees trigger. The first counters Bob's bolt;
    the second finds it gone and must not counter Alice's bolt, now the top
    spell — but it still takes its depletion counter."""
    lea, scg = set_pool("LEA"), set_pool("SCG")
    game, alice, bob = _w1g2_table(
        set_pool, [lea["Lightning Bolt"]], [lea["Lightning Bolt"]], active=0,
    )
    first = _w1g2_put(game, 0, scg["Decree of Silence"])
    second = _w1g2_put(game, 0, scg["Decree of Silence"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Lightning Bolt", "Decree of Silence", "Decree of Silence",
    ]
    _w1g2_drain(game)
    assert alice.life == 20, "Bob's bolt was countered"
    assert bob.life == 17, "Alice's bolt was not"
    assert (_w1g2_depletion(first), _w1g2_depletion(second)) == (1, 1)


def test_w1g2_decree_of_silence_cycled_counters_target_spell(set_pool):
    """"When you cycle this card, you may counter target spell." Cycled in
    response; the trigger resolves before the cycling draw (2022-12-08)."""
    lea = set_pool("LEA")
    game, alice, bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Decree of Silence"]], [lea["Lightning Bolt"]],
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.activate_from_hand(0, "Decree of Silence").supported
    trigger = game.stack[-1]
    assert trigger.ability_text.startswith("When you cycle this card")
    assert trigger.target_stack_item is not None or trigger.targets_chosen
    _w1g2_drain(game)
    assert alice.life == 20
    assert [c.name for c in bob.graveyard] == ["Lightning Bolt"]
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g2_decree_of_silence_cycles_with_no_spell_to_target(set_pool):
    """2022-12-08: "You can cycle this card even if there are no legal targets
    for the triggered ability." The draw still happens."""
    game, alice, _bob = _w1g2_table(set_pool, [set_pool("SCG")["Decree of Silence"]], [])
    assert game.activate_from_hand(0, "Decree of Silence").supported
    _w1g2_drain(game)
    assert [c.name for c in alice.hand] == ["Plains"]

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.
#
# Pyrostatic Pillar: "Whenever a player casts a spell with mana value 3 or
# less, this enchantment deals 2 damage to that player." The cast trigger's
# ``cast_mana_value`` narrowing, read off the spell's stack object (CR
# 202.3b), and "that player" the seat the trigger is about — the caster.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.models import Permanent as _W1G4Permanent
from engine.models import PlayerState as _W1G4PlayerState
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_pillar_table(set_pool, spell, caster):
    lea = set_pool("LEA")
    seats = [
        _W1G4PlayerState(name=f"P{seat + 1}", library=[lea["Island"]] * 8)
        for seat in range(2)
    ]
    game = _W1G4Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = caster
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    pillar = _W1G4Permanent(card=set_pool("SCG")["Pyrostatic Pillar"])
    game._put_permanent_onto_battlefield(0, pillar, None)
    game._sync_control()
    game.players[caster].hand.append(lea[spell])
    return game


@_w1g4_pytest.mark.parametrize("spell, x_value, caster, burned", [
    ("Grizzly Bears", None, 0, True),     # 2: its controller is burned too
    ("Grizzly Bears", None, 1, True),     # an opponent's cast
    ("Lightning Bolt", None, 1, True),    # 1
    ("Hill Giant", None, 1, False),       # {3}{R}: 4
    ("Sengir Vampire", None, 1, False),   # 5
    ("Fireball", 2, 1, True),             # {X}{R}, X=2: 3 on the stack
    ("Fireball", 3, 1, False),            # X=3: 4
])
def test_w1g4_pyrostatic_pillar_burns_whoever_casts_a_cheap_spell(
    set_pool, spell, x_value, caster, burned,
):
    game = _w1g4_pillar_table(set_pool, spell, caster)
    card = set_pool("LEA")[spell]
    announced = {} if "Creature" in card.type_line else {"target_player_index": 1 - caster}
    if x_value is not None:
        announced["x_value"] = x_value
    assert game.queue_from_hand(caster, spell, **announced).supported
    # The trigger is on the stack above the spell (CR 603.3) — or is not.
    assert len(game.stack) == (2 if burned else 1), game.log
    if burned:
        game.resolve_top_of_stack()
    lives = [player.life for player in game.players]
    expected = [20, 20]
    if burned:
        expected[caster] = 18
    assert lives == expected, game.log


def test_w1g4_pyrostatic_pillar_burns_a_face_down_spell(set_pool):
    """CR 708.4: a face-down spell is a 2/2 with no mana cost, mana value 0 —
    Krosan Colossus' 9 is hidden, and the Pillar sees a 0."""
    game = _w1g4_pillar_table(set_pool, "Island", 1)
    game.players[1].hand[:] = [set_pool("ONS")["Krosan Colossus"]]
    game.enforce_mana_costs = True
    game.players[1].mana_pool.update({"C": 3})
    assert game.queue_from_hand(1, "Krosan Colossus", alternative_cost=True).supported
    assert len(game.stack) == 2, game.log
    game.resolve_top_of_stack()
    assert [player.life for player in game.players] == [20, 18], game.log

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
