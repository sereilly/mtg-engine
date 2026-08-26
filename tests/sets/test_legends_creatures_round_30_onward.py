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
# Tempest Efreet (round 31) — an exchange of *ownership*, and a random reveal
# ---------------------------------------------------------------------------


def _r31_te_game(set_pool, catalog_by_name, victim_hand, *, ante=True, copies=1):
    """A board with *copies* untapped Tempest Efreets and a hand to reveal from."""
    players = [PlayerState(name="P1"), PlayerState(name="P2", life=30)]
    players[1].hand = [catalog_by_name[name] for name in victim_hand]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.playing_for_ante = ante
    for _ in range(copies):
        perm = Permanent(card=set_pool("LEG")["Tempest Efreet"])
        game._put_permanent_onto_battlefield(0, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
    return game, players


def _r31_te_zones(players):
    return {
        "life": [player.life for player in players],
        "p1_hand": sorted(card.name for card in players[0].hand),
        "p2_hand": sorted(card.name for card in players[1].hand),
        "p1_graveyard": sorted(card.name for card in players[0].graveyard),
        "p2_graveyard": sorted(card.name for card in players[1].graveyard),
    }


def test_tempest_efreet_exchanges_ownership_when_the_opponent_declines(
    set_pool, catalog_by_name
):
    """The revealed card ends up in the activator's hand and the Efreet in the
    opponent's graveyard — which in this engine *is* the ownership change, since
    ownership is which player's zone a card sits in (CR 108.3's ante
    exception)."""
    game, players = _r31_te_game(set_pool, catalog_by_name, ["Black Lotus"])
    game.activate_permanent_ability(
        0, "Tempest Efreet", permanent_index=0, target_player_index=1
    )

    assert game.confirm_optional_pay(1, accept=False)

    zones = _r31_te_zones(players)
    assert zones["p1_hand"] == ["Black Lotus"], game.log
    assert zones["p2_hand"] == [], game.log
    assert zones["p2_graveyard"] == ["Tempest Efreet"], game.log
    assert zones["p1_graveyard"] == [], game.log


def test_paying_the_life_keeps_both_cards_where_they_were(set_pool, catalog_by_name):
    """The payment is the whole of the opponent's out, and it is a real cost:
    the Efreet is still sacrificed (it was the activation cost) and stays in its
    own owner's graveyard."""
    game, players = _r31_te_game(set_pool, catalog_by_name, ["Black Lotus"])
    game.activate_permanent_ability(
        0, "Tempest Efreet", permanent_index=0, target_player_index=1
    )

    assert game.confirm_optional_pay(1, accept=True)

    zones = _r31_te_zones(players)
    assert zones["life"] == [20, 20], game.log
    assert zones["p2_hand"] == ["Black Lotus"], game.log
    assert zones["p1_graveyard"] == ["Tempest Efreet"], game.log


def test_the_exchange_is_inert_outside_a_game_played_for_ante(
    set_pool, catalog_by_name
):
    """CR 108.3 fixes ownership and CR 407.1 makes the exception opt-in, so
    nothing is even offered — no prompt is queued and no card moves."""
    game, players = _r31_te_game(set_pool, catalog_by_name, ["Black Lotus"], ante=False)

    game.activate_permanent_ability(
        0, "Tempest Efreet", permanent_index=0, target_player_index=1
    )

    assert not game.pending_choices, game.log
    zones = _r31_te_zones(players)
    assert zones["p2_hand"] == ["Black Lotus"], game.log
    assert zones["p1_graveyard"] == ["Tempest Efreet"], game.log


def test_a_second_efreet_takes_its_own_card_not_the_first_ones(
    set_pool, catalog_by_name
):
    """Two copies share one ``CardDefinition``, so "this creature from
    anywhere" cannot be told apart by identity. The card the *second*
    activation gives away has to be the one it sacrificed — searched from the
    activator's own zones first — and not the copy already sitting in the
    opponent's graveyard from the first."""
    game, players = _r31_te_game(
        set_pool, catalog_by_name, ["Black Lotus", "Craw Wurm"], copies=2
    )
    game.activate_permanent_ability(
        0, "Tempest Efreet", permanent_index=0, target_player_index=1
    )
    game.confirm_optional_pay(1, accept=False)

    game.activate_permanent_ability(
        0, "Tempest Efreet", permanent_index=0, target_player_index=1
    )
    game.confirm_optional_pay(1, accept=False)

    zones = _r31_te_zones(players)
    assert zones["p1_hand"] == ["Black Lotus", "Craw Wurm"], game.log
    assert zones["p2_hand"] == [], game.log
    assert zones["p2_graveyard"] == ["Tempest Efreet", "Tempest Efreet"], game.log
    assert zones["p1_graveyard"] == [], game.log


def test_an_empty_hand_reveals_nothing_and_exchanges_nothing(
    set_pool, catalog_by_name
):
    """With no card to reveal there is nothing to exchange the Efreet for, so
    it stays in its own owner's graveyard."""
    game, players = _r31_te_game(set_pool, catalog_by_name, [])
    game.activate_permanent_ability(
        0, "Tempest Efreet", permanent_index=0, target_player_index=1
    )

    game.confirm_optional_pay(1, accept=False)

    zones = _r31_te_zones(players)
    assert zones["p1_hand"] == [], game.log
    assert zones["p1_graveyard"] == ["Tempest Efreet"], game.log
