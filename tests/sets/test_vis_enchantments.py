"""Visions enchantments.

Opened at Visions' first wave. Every test here drives a real ``Game`` and reads
what happened to it: an attack restriction nothing enforces and a trigger
nothing announces both look exactly like the working thing from a compiled
program.
"""

# --- VIS w1g3: an Aura's damage trigger, and two combat tolls ---------------
#
# Imports live inside the block by the per-set convention, so a merge that
# appends another group's block cannot lose one.

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from tests.helpers import _nosick


def _w1g3e_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g3e_creature(name="Bear", power=2, toughness=4, colors=()):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={
            "name": name, "type_line": "Creature - Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )


def test_mortal_wound_destroys_the_creature_the_moment_it_is_dealt_damage(set_pool):
    """"When enchanted creature is dealt damage, destroy it."

    The condition was readable by ``engine/oracle.py``'s table under either
    printed word and by the grammar under only one, so the trigger *parsed* and
    its effect clause did not - the card compiled with a trigger that had no
    instruction behind it. What that costs is exactly this: one point of damage
    on a 2/4 and the creature should die.

    Driven through the stack, because a CR 603.3 trigger resolves off it: a
    trigger that is enqueued and never resolved looks identical to one that
    fires, from anywhere but here.
    """
    game = _w1g3e_duel()
    p1, p2 = game.players
    victim = _nosick(Permanent(card=_w1g3e_creature("Doomed Bear")))
    wound = Permanent(card=set_pool("VIS")["Mortal Wound"])
    p2.battlefield.append(victim)
    p1.battlefield.append(wound)
    attach_aura(wound, victim)

    game._mark_damage_on_permanent(victim, 1)
    game._fire_dealt_damage_triggers(victim, 1)
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()

    assert not any(p is victim for p in p2.battlefield)


def test_mortal_wound_leaves_an_undamaged_creature_alone(set_pool):
    """The control. A trigger fired by the attachment rather than by the event
    would kill the creature the moment the Aura landed, which is the failure a
    "does the card work?" test that only ever damages things cannot see."""
    game = _w1g3e_duel()
    p1, p2 = game.players
    victim = _nosick(Permanent(card=_w1g3e_creature("Healthy Bear")))
    wound = Permanent(card=set_pool("VIS")["Mortal Wound"])
    p2.battlefield.append(victim)
    p1.battlefield.append(wound)
    attach_aura(wound, victim)

    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()

    assert any(p is victim for p in p2.battlefield)


def test_elephant_grass_forbids_a_black_attacker_and_prices_the_rest(set_pool):
    """"Black creatures can't attack you." / "Nonblack creatures can't attack
    you unless their controller pays {2} for each creature they control that's
    attacking you."

    Both sentences were unclaimed on a card that reported supported, which is
    the population ``parse_coverage`` exists to find: the enchantment entered
    play and did nothing at all. Three assertions, because the two sentences
    divide the board three ways - the black attacker is forbidden outright, a
    nonblack one is priced, and neither says anything about attacking anybody
    else.
    """
    game = _w1g3e_duel()
    p1, p2 = game.players
    grass = Permanent(card=set_pool("VIS")["Elephant Grass"])
    p1.battlefield.append(grass)
    black = _nosick(Permanent(card=_w1g3e_creature("Black Bear", colors=("B",))))
    white = _nosick(Permanent(card=_w1g3e_creature("White Bear", colors=("W",))))
    p2.battlefield.extend([black, white])

    assert not game.can_attack(black, 0), "black creatures can't attack you"
    # The nonblack one is not forbidden - it is priced, and with no mana it
    # cannot pay, so the declaration is refused rather than the creature.
    assert game._attack_mana_costs_of(white, 0) == [{"generic": 2}]
    assert game._attack_mana_costs_of(black, 0) == [], (
        "the toll's noun phrase excludes the colour the other sentence forbids"
    )


def test_elephant_grass_says_nothing_about_attacking_its_opponent(set_pool):
    """"…can't attack **you**" is CR 109.5's "you": the seat controlling the
    enchantment. Read as an unscoped prohibition it would ground the creature
    against every seat at the table, which in a duel is invisible and in a
    free-for-all is three cards' worth of effect."""
    game = Game(players=[
        PlayerState(name="P1"), PlayerState(name="P2"), PlayerState(name="P3"),
    ])
    game.enforce_mana_costs = False
    p1, p2, p3 = game.players
    grass = Permanent(card=set_pool("VIS")["Elephant Grass"])
    p1.battlefield.append(grass)
    black = _nosick(Permanent(card=_w1g3e_creature("Black Bear", colors=("B",))))
    p2.battlefield.append(black)

    assert not game.can_attack(black, 0)
    assert game.can_attack(black, 2), "the third seat is protected by nothing"


def test_heat_wave_forbids_a_blue_blocker_and_charges_the_rest_life(set_pool):
    """"Blue creatures can't block creatures you control." / "Nonblue creatures
    can't block creatures you control unless their controller pays 1 life for
    each blocking creature they control."

    The blocking mirror of Elephant Grass, and both of its sentences were
    unclaimed too. The life toll is the first cost in the combat tables paid in
    something other than mana, so it is read back rather than assumed.
    """
    game = _w1g3e_duel()
    p1, p2 = game.players
    wave = Permanent(card=set_pool("VIS")["Heat Wave"])
    attacker = _nosick(Permanent(card=_w1g3e_creature("My Attacker")))
    p1.battlefield.extend([wave, attacker])
    blue = _nosick(Permanent(card=_w1g3e_creature("Blue Blocker", colors=("U",))))
    red = _nosick(Permanent(card=_w1g3e_creature("Red Blocker", colors=("R",))))
    p2.battlefield.extend([blue, red])
    attacker.attacking = True

    assert not game._can_block_attacker(blue, attacker)
    assert game._block_life_cost_of(red, attacker) == 1
    assert game._block_life_cost_of(blue, attacker) == 0, (
        "the toll's own noun phrase is **nonblue**, so it says nothing about a "
        "blue creature - which the sentence above has already forbidden "
        "outright. Two sentences, two disjoint sets, and a toll that reached "
        "both would charge for a block the card does not allow at any price"
    )


def test_heat_wave_refuses_a_blocker_its_controller_cannot_pay_for(set_pool):
    """CR 118.4: a player may pay N life only with a life total of at least N.
    Asked at the gate, so an unpayable toll makes the block illegal rather than
    being discovered after CR 509 has locked the declaration in."""
    game = _w1g3e_duel()
    p1, p2 = game.players
    wave = Permanent(card=set_pool("VIS")["Heat Wave"])
    attacker = _nosick(Permanent(card=_w1g3e_creature("My Attacker")))
    p1.battlefield.extend([wave, attacker])
    red = _nosick(Permanent(card=_w1g3e_creature("Red Blocker", colors=("R",))))
    p2.battlefield.append(red)
    attacker.attacking = True

    assert game._can_block_attacker(red, attacker)
    p2.life = 0
    assert not game._can_block_attacker(red, attacker)


def test_heat_wave_says_nothing_about_blocking_somebody_else_s_attacker(set_pool):
    """"…can't block creatures **you** control" — CR 109.5 again, on the other
    half of combat. Read with the blocker's seat as the observer this would
    protect the wrong player's creatures, which in a duel is the opposite of
    the printed card."""
    game = Game(players=[
        PlayerState(name="P1"), PlayerState(name="P2"), PlayerState(name="P3"),
    ])
    game.enforce_mana_costs = False
    p1, p2, p3 = game.players
    wave = Permanent(card=set_pool("VIS")["Heat Wave"])
    p1.battlefield.append(wave)
    third_partys_attacker = _nosick(Permanent(card=_w1g3e_creature("Their Attacker")))
    p3.battlefield.append(third_partys_attacker)
    blue = _nosick(Permanent(card=_w1g3e_creature("Blue Blocker", colors=("U",))))
    p2.battlefield.append(blue)
    third_partys_attacker.attacking = True

    assert game._can_block_attacker(blue, third_partys_attacker)
    assert game._block_life_cost_of(blue, third_partys_attacker) == 0
# --- end VIS w1g3 ---
