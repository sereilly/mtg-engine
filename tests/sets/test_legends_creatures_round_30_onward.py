"""Per-card tests for Legends' creatures, from round 30 onward.

Split from `test_legends_creatures_late_rounds.py` at the 2,600-line
readability cap, on the same axis that file was cut from
`test_legends_creatures.py`: every card in all three is a creature, so the type
axis has no room left and the cut is a **round boundary**
(`tests/sets/README.md`). Each round section is self-contained, so cutting
between sections keeps every section whole and keeps a test findable from its
round.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _vanilla(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )

# ---------------------------------------------------------------------------
# Round 30 — a trigger that fires in combat and resolves at end of combat
# ---------------------------------------------------------------------------


def _r30_board(set_pool, others=(), defenders=()):
    """Time Elemental under P1, *others* beside it, *defenders* under P2."""
    elemental = Permanent(card=set_pool("LEG")["Time Elemental"])
    p1 = PlayerState(name="P1", battlefield=[elemental, *others])
    p2 = PlayerState(name="P2", battlefield=list(defenders))
    game = Game(players=[p1, p2])
    return game, p1, p2, elemental


def _r30_to_end_of_combat(game, *, attackers, blockers=None):
    """Run one combat phase to the end-of-combat step, settling every step."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    ok, msg = game.declare_attackers(0, attackers)
    assert ok, msg
    game._settle()
    yield "attackers_declared"
    game.advance_combat_phase()   # declare blockers
    ok, msg = game.declare_blockers(1, blockers or {})
    assert ok, msg
    game._settle()
    game.advance_combat_phase()   # combat damage
    game._settle()
    yield "end_of_combat"
    game.advance_combat_phase()   # past the end-of-combat step
    game._settle()
    yield "combat_over"


def test_time_elemental_arms_its_sacrifice_rather_than_performing_it(set_pool):
    """"When this creature attacks or blocks, **at end of combat**, sacrifice it
    …" — CR 603.7. The trigger fires on the declaration, and all it does then is
    create the delayed ability: an engine that performed the sentence at once
    would remove the attacker before it ever dealt damage."""
    bears = _vanilla("Bears", 2, 2)
    game, p1, _p2, elemental = _r30_board(
        set_pool, defenders=[Permanent(card=bears)]
    )
    steps = _r30_to_end_of_combat(game, attackers=[0])

    assert next(steps) == "attackers_declared"

    assert any(perm is elemental for perm in p1.battlefield)
    assert p1.life == 20
    entry, = game.delayed_triggers
    assert entry.event == "next_end_of_combat"


def test_time_elemental_sacrifices_itself_and_burns_its_controller_at_end_of_combat(set_pool):
    """The other end of the same ability: combat damage has already been dealt
    when it fires, and the 5 damage goes to the Elemental's own controller."""
    bears = _vanilla("Bears", 2, 2)
    game, p1, _p2, elemental = _r30_board(
        set_pool, defenders=[Permanent(card=bears)]
    )
    steps = _r30_to_end_of_combat(game, attackers=[0])
    next(steps)

    assert next(steps) == "end_of_combat"
    next(steps)

    assert not any(perm is elemental for perm in p1.battlefield)
    assert "Time Elemental" in [card.name for card in p1.graveyard]
    assert p1.life == 15
    assert not game.delayed_triggers


def test_time_elemental_triggers_on_blocking_as_well_as_attacking(set_pool):
    """"attacks **or** blocks" is one condition covering both halves. The
    Elemental is defending here and never attacks at all."""
    attacker = _vanilla("Raider", 2, 2)
    game, _p1, p2, elemental = _r30_board(set_pool, defenders=[])
    # Swap the seats: P2 attacks, and the Elemental blocks.
    game.players[0], game.players[1] = game.players[1], game.players[0]
    game.players[0].battlefield = [Permanent(card=attacker)]
    p1_defending = game.players[1]
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    game.advance_combat_phase()
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()

    entry, = game.delayed_triggers
    assert entry.event == "next_end_of_combat"

    game.advance_combat_phase()
    game._settle()
    game.advance_combat_phase()
    game._settle()

    assert not any(perm is elemental for perm in p1_defending.battlefield)
    assert p1_defending.life == 15


def test_time_elemental_never_offers_an_enchanted_permanent_as_a_bounce_target(set_pool):
    """"Return target permanent **that isn't enchanted** to its owner's hand."

    The restriction has to reach the *picker*, not only the handler: the handler
    already returns nothing when the choice is illegal, so a picker that offered
    the enchanted creature would let a player tap the Elemental and pay
    {2}{U}{U} for a bounce that does nothing at all.

    The Aura itself stays on the list — an Aura enchants, it is not enchanted —
    and so does the Elemental.
    """
    from engine.auras import attach_aura
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    lea = set_pool("LEA")
    bare = Permanent(card=lea["Grizzly Bears"])
    enchanted = Permanent(card=lea["Grizzly Bears"])
    aura = Permanent(card=lea["Holy Strength"])
    game, _p1, _p2, elemental = _r30_board(
        set_pool, defenders=[bare, enchanted, aura]
    )
    attach_aura(aura, enchanted)
    program = compile_card_oracle(elemental.card)
    ability, = program.activated_abilities
    spec = derive_activation_spec(ability)

    offered = game._enumerate_targets(
        0, elemental.card, spec, for_cast=False,
        ability_instruction=ability.instruction,
        source_permanent=elemental, ability_source=elemental,
    )

    keys = {entry["key"] for entry in offered}
    assert keys == {"0-0", "1-0", "1-2"}, offered
