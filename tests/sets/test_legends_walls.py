"""Per-card tests for Legends' Walls and the creatures that shield themselves
from a described class of source.

Every card here is a Creature by printed type, so by `tests/sets/README.md` it
would live in `test_legends_creatures.py`; it is split out because these five
share one mechanism (`prevention._SOURCE_CLASSES`) and the round that bought
them is easier to find whole. See tests/sets/README.md.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.damage_events import deal_damage
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _creature(name: str, power: int = 3, toughness: int = 3,
              type_line: str = "Creature - Test") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _aura() -> CardDefinition:
    return CardDefinition(
        name="Test Aura", mana_cost="", cmc=0.0, type_line="Enchantment - Aura",
        oracle_text="Enchant creature", colors=(), color_identity=(),
        keywords=(), produced_mana=(),
        raw={"name": "Test Aura", "type_line": "Enchantment - Aura"},
    )


def _damage(game, recipient, amount, source, *, combat=True) -> int:
    return deal_damage(game, {
        "recipient": recipient, "amount": amount, "source": source, "combat": combat,
    }).dealt


# ---------------------------------------------------------------------------
# "…by enchanted creatures" — a state of the source object
# ---------------------------------------------------------------------------


def test_wall_of_putrid_flesh_stops_a_creature_that_is_enchanted(set_pool):
    wall = Permanent(card=set_pool("LEG")["Wall of Putrid Flesh"])
    attacker = Permanent(card=_creature("Attacker"))
    aura = Permanent(card=_aura())
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker, aura]),
        PlayerState(name="P2", battlefield=[wall]),
    ])
    attach_aura(aura, attacker)

    assert _damage(game, wall, 3, attacker) == 0


def test_wall_of_putrid_flesh_takes_damage_from_an_unenchanted_creature(set_pool):
    """The narrowing, checked in the direction that matters: a shield that
    ignored "enchanted" would make the Wall immune to everything."""
    wall = Permanent(card=set_pool("LEG")["Wall of Putrid Flesh"])
    attacker = Permanent(card=_creature("Attacker"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[wall]),
    ])

    assert _damage(game, wall, 3, attacker) == 3


def test_enchanted_being_shields_only_combat_damage(set_pool):
    """"Prevent all **combat** damage … by enchanted creatures." One word off
    Wall of Putrid Flesh's line, and it is the whole difference."""
    being = Permanent(card=set_pool("LEG")["Enchanted Being"])
    attacker = Permanent(card=_creature("Attacker"))
    aura = Permanent(card=_aura())
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker, aura]),
        PlayerState(name="P2", battlefield=[being]),
    ])
    attach_aura(aura, attacker)

    assert _damage(game, being, 3, attacker) == 0
    assert _damage(game, being, 3, attacker, combat=False) == 3


# ---------------------------------------------------------------------------
# "…by Walls" — a subtype (CR 205.3)
# ---------------------------------------------------------------------------


def test_marble_priest_ignores_a_walls_combat_damage(set_pool):
    priest = Permanent(card=set_pool("LEG")["Marble Priest"])
    wall = Permanent(card=_creature("Some Wall", type_line="Creature - Wall"))
    other = Permanent(card=_creature("Not A Wall"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[wall, other]),
        PlayerState(name="P2", battlefield=[priest]),
    ])

    assert _damage(game, priest, 3, wall) == 0
    assert _damage(game, priest, 3, other) == 3


def test_marble_priest_compels_every_able_wall_to_block_it(set_pool):
    """"All Walls able to block this creature do so." Lure's requirement
    (CR 509.1c) narrowed to a printed noun, so a non-Wall may stay back."""
    priest = Permanent(card=set_pool("LEG")["Marble Priest"])
    wall = Permanent(card=_creature("Some Wall", type_line="Creature - Wall"))
    bystander = Permanent(card=_creature("Bystander"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[priest]),
        PlayerState(name="P2", battlefield=[wall, bystander]),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()

    assert not game.declare_blockers(1, {})[0], "the Wall had to block"
    assert game.declare_blockers(1, {0: 0})[0], "the non-Wall may stay back"


# ---------------------------------------------------------------------------
# "…by creatures it's blocking" — a relationship, not a property
# ---------------------------------------------------------------------------


def _wall_blocking(set_pool, wall_name: str):
    wall = Permanent(card=set_pool("LEG")[wall_name])
    attacker = Permanent(card=_creature("Attacker", 5, 5))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[wall]),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()
    return game, wall, attacker


def test_wall_of_vapor_takes_nothing_from_what_it_blocks(set_pool):
    game, wall, attacker = _wall_blocking(set_pool, "Wall of Vapor")

    assert _damage(game, wall, 5, attacker) == 0


def test_wall_of_vapor_is_not_shielded_before_it_blocks(set_pool):
    """The relationship is read off combat, so it does not exist outside it —
    a shield keyed on the attacker's own properties would be permanent."""
    wall = Permanent(card=set_pool("LEG")["Wall of Vapor"])
    attacker = Permanent(card=_creature("Attacker", 5, 5))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[wall]),
    ])

    assert _damage(game, wall, 5, attacker) == 5


def test_the_shield_is_directional(set_pool):
    """"…by creatures **it's** blocking" — the Wall is the blocker. A creature
    blocking the Wall is not a creature the Wall is blocking, and reading the
    combat map either way round would shield both."""
    game, wall, attacker = _wall_blocking(set_pool, "Wall of Vapor")

    assert _damage(game, attacker, 1, wall) == 1


def test_wall_of_vapor_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Wall of Vapor"])
    assert program.supported, program.reason
