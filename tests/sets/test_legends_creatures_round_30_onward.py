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


# ---------------------------------------------------------------------------
# Round 31 — a shroud narrowed by what the *source's own description* admits
# ---------------------------------------------------------------------------


def _r31_wall_board(set_pool, extra=()):
    """Ali Baba (ARN) under P1; Wall of Shadows and *extra* (LEA) under P2."""
    ali = Permanent(card=set_pool("ARN")["Ali Baba"])
    shadows = Permanent(card=set_pool("LEG")["Wall of Shadows"])
    others = [Permanent(card=set_pool("LEA")[name]) for name in extra]
    p1 = PlayerState(name="P1", battlefield=[ali])
    p2 = PlayerState(name="P2", battlefield=[shadows, *others])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, ali, shadows, others


def test_wall_of_shadows_is_supported(set_pool):
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("LEG")["Wall of Shadows"])
    assert program.supported


def test_wall_of_shadows_refuses_a_spell_that_can_target_only_walls(set_pool):
    """Tunnel ("Destroy target Wall") cannot be aimed at it.

    The restriction is about the *spell's own target description*, not about
    what class of object the spell is — which is what makes it a different
    axis from Anti-Magic Aura's "can't be the target of spells". Tunnel is
    stopped because "target Wall" admits nothing else.
    """
    game, _ali, shadows, (stone,) = _r31_wall_board(set_pool, extra=["Wall of Stone"])
    tunnel = set_pool("LEA")["Tunnel"]

    ok, reason = game._validate_cast_targets(
        tunnel, 0, target_player_index=1, target_permanent_index=0,
    )
    assert not ok and "Wall of Shadows" in reason
    # …and the picker agrees, which is the half a player sees.
    assert [entry.get("name") for entry in game._enumerate_targets(
        0, tunnel, {"kind": "creature", "wall_only": True}, for_cast=True,
    )] == ["Wall of Stone"]
    assert stone is not shadows


def test_wall_of_shadows_still_answers_a_spell_that_can_target_any_creature(set_pool):
    """A spell whose description is wider is not stopped, however plainly it
    could kill the same Wall — "can target only Walls" is a fact about the
    description, not about the outcome."""
    game, _ali, shadows, _others = _r31_wall_board(set_pool)
    bolt = set_pool("LEA")["Lightning Bolt"]

    assert game._can_be_targeted(shadows, bolt, caster_index=0)


def test_wall_of_shadows_refuses_an_ability_that_can_target_only_walls(set_pool):
    """Ali Baba's "{R}: Tap target Wall" cannot pick it (CR 602.2b).

    Asked of the *ability's* spec rather than of Ali Baba, because a permanent
    may carry several abilities that target differently — the source object
    alone cannot say which description is choosing.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    game, ali, _shadows, (stone,) = _r31_wall_board(set_pool, extra=["Wall of Stone"])
    ability, = compile_card_oracle(ali.card).activated_abilities
    spec = derive_activation_spec(ability)

    offered = game._enumerate_targets(
        0, ali.card, dict(spec), for_cast=False,
        ability_instruction=ability.instruction,
        source_permanent=ali, ability_source=ali,
    )
    assert [entry.get("name") for entry in offered] == ["Wall of Stone"]
    assert stone.card.name == "Wall of Stone"


def test_wall_of_shadows_alone_makes_that_ability_unactivatable(set_pool):
    """No legal target means the ability is refused with nothing paid
    (CR 602.2b via 601.2c) — the gate reads the same enumerated list."""
    game, ali, _shadows, _others = _r31_wall_board(set_pool)
    game.active_player_index = 0
    game.current_turn_phase = "main"
    game.current_step = "precombat_main"
    ali.summoning_sick = False

    from engine.oracle import compile_card_oracle

    ability, = compile_card_oracle(ali.card).activated_abilities
    assert game.activation_target_refusal(0, ali, ability) is not None


def test_wall_of_shadows_survives_tunnel_in_a_real_cast(set_pool):
    """Not a compiler answer: the spell is actually cast, resolved and the board
    read afterwards.

    Aimed at the protected Wall the cast is refused outright (CR 601.2c — an
    illegal choice makes the spell uncastable, not merely ineffective); aimed at
    the Wall beside it the same spell destroys it, so the refusal is the
    restriction and not a broken card.

    Both spellings of a chosen target are cast: the battlefield slot, and the
    stable id the wire actually carries. The second is not decoration — see
    `test_r31_the_cast_gate_reads_the_ids_a_caller_names` below.
    """
    game, _ali, shadows, (stone,) = _r31_wall_board(set_pool, extra=["Wall of Stone"])
    tunnel = set_pool("LEA")["Tunnel"]
    game.players[0].hand.extend([tunnel, tunnel])
    game.active_player_index = 0
    game.current_turn_phase = "main"
    game.current_step = "precombat_main"
    shadows_slot = game.battlefield_index_of(shadows)
    stone_slot = game.battlefield_index_of(stone)

    refused = game.cast_from_hand(
        0, "Tunnel", target_player_index=1, target_permanent_index=shadows_slot,
    )
    assert not refused.supported, refused.details
    assert game.is_on_battlefield(shadows)

    allowed = game.cast_from_hand(
        0, "Tunnel", target_player_index=1, target_permanent_index=stone_slot,
    )
    assert allowed.supported, allowed.details
    game._settle()
    assert not game.is_on_battlefield(stone)
    assert game.is_on_battlefield(shadows)


def test_r31_the_cast_gate_reads_the_ids_a_caller_names(set_pool):
    """CR 702.16b/601.2c is enforced whichever way the target was addressed.

    The gate read the battlefield *slot* alone, so a caller naming its target by
    stable id — the addressing this codebase asks for, since an index renumbers
    under anything that leaves — got no check at all. Tunnel destroyed a Wall of
    Shadows that can't be its target, and Drain Life was cast at a White Knight
    it has protection from. The web layer never showed it because
    `web/actions.py` resolves the ids to indices and sends both, which is what
    makes this the quiet kind: one caller's spelling enforced, another's not.
    """
    game, _ali, shadows, _others = _r31_wall_board(set_pool)
    game.players[0].hand.append(set_pool("LEA")["Tunnel"])
    game.active_player_index = 0
    game.current_turn_phase = "main"
    game.current_step = "precombat_main"

    result = game.cast_from_hand(
        0, "Tunnel", target_player_index=1,
        target_permanent_ids=[shadows.permanent_id],
    )
    assert not result.supported, result.details
    assert "Wall of Shadows" in result.details
    assert game.is_on_battlefield(shadows)
