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

# Round 31 — Wood Elemental: a variable sacrifice as it enters, counted back
# ---------------------------------------------------------------------------
#
# "As this creature enters, sacrifice any number of untapped Forests." plus
# "Wood Elemental's power and toughness are each equal to the number of Forests
# sacrificed as it entered."
#
# Two mechanisms meet here. The sacrifice prompt learned a **ceiling** ("any
# number", none included) and learned to record how many were given up onto the
# permanent that asked. The CDA table learned a row that reads that number back
# — the Forests are cards in a graveyard by then (CR 400.7), so there is nothing
# on any battlefield left to count.


def _r31_forest(name: str = "Forest") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Basic Land - Forest",
        oracle_text="", colors=(), color_identity=("G",), keywords=(),
        produced_mana=("G",),
        raw={"name": name, "type_line": "Basic Land - Forest"},
    )


def _r31_wood_elemental(set_pool, *, forests=3, tapped=0, interactive=True):
    """Seat 0 with *forests* Forests, of which *tapped* are tapped, casting it."""
    lands = []
    for i in range(forests):
        perm = Permanent(card=_r31_forest())
        perm.tapped = i < tapped
        lands.append(perm)
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Wood Elemental"]],
                     battlefield=lands)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    game.cast_from_hand(0, "Wood Elemental")
    return game, p1


def test_wood_elemental_offers_its_forests_as_it_enters(set_pool):
    """CR 614.1c: the sacrifice is part of entering, and the offer is a ceiling
    — a tapped Forest is not among what the card names."""
    game, p1 = _r31_wood_elemental(set_pool, forests=3, tapped=1)

    prompt = game.pending_sacrifice_state()
    assert prompt is not None and prompt["player_index"] == 0
    assert prompt["count"] == 2, "only the untapped Forests are offered"
    assert prompt["up_to"] is True, "any number, not exactly two"
    elemental = next(p for p in p1.battlefield if p.card.name == "Wood Elemental")
    assert (elemental.effective_power, elemental.effective_toughness) == (0, 0)


def test_wood_elementals_body_is_the_number_of_forests_it_ate(set_pool):
    game, p1 = _r31_wood_elemental(set_pool, forests=3)
    prompt = game.pending_sacrifice_state()

    assert game.confirm_sacrifice(0, prompt["valid_indices"][:2])

    elemental = next(p for p in p1.battlefield if p.card.name == "Wood Elemental")
    assert (elemental.effective_power, elemental.effective_toughness) == (2, 2)
    assert [p.card.name for p in p1.battlefield if p.card.name == "Forest"] == ["Forest"]
    assert len(p1.graveyard) == 2


def test_a_different_number_of_forests_is_a_different_body(set_pool):
    """The control on the test above: nothing about the card is 2/2."""
    game, p1 = _r31_wood_elemental(set_pool, forests=4)
    prompt = game.pending_sacrifice_state()

    assert game.confirm_sacrifice(0, prompt["valid_indices"])

    elemental = next(p for p in p1.battlefield if p.card.name == "Wood Elemental")
    assert (elemental.effective_power, elemental.effective_toughness) == (4, 4)


def test_sacrificing_none_is_a_legal_answer_and_kills_it(set_pool):
    """"Any number" includes none, and a 0/0 dies to CR 704.5f. Refusing the
    empty answer would force a player to give up lands the card offered them
    the choice of keeping."""
    game, p1 = _r31_wood_elemental(set_pool, forests=3)

    assert game.confirm_sacrifice(0, [])

    assert [p.card.name for p in p1.battlefield] == ["Forest"] * 3
    assert [c.name for c in p1.graveyard] == ["Wood Elemental"]


def test_a_non_interactive_seat_gives_up_nothing(set_pool):
    """The stated policy, not a heuristic: a seat that is merely offered the
    chance to pay a cost pays none of it, and the card does what it does when
    its controller declines. Nothing is left queued either — a suspending prompt
    an AI seat never answers would be a hang, not a weak play."""
    game, p1 = _r31_wood_elemental(set_pool, forests=3, interactive=False)

    assert game.pending_choices == []
    assert [p.card.name for p in p1.battlefield] == ["Forest"] * 3
    assert [c.name for c in p1.graveyard] == ["Wood Elemental"]


def test_with_no_forests_at_all_it_asks_nothing(set_pool):
    game, p1 = _r31_wood_elemental(set_pool, forests=0)

    assert game.pending_choices == []
    assert [c.name for c in p1.graveyard] == ["Wood Elemental"]


# ---------------------------------------------------------------------------
# Round 31 — Primordial Ooze: an offer whose price is what the card has grown to
# ---------------------------------------------------------------------------
#
# "At the beginning of your upkeep, put a +1/+1 counter on this creature. Then
# you may pay {X}, where X is the number of +1/+1 counters on it. If you don't,
# tap this creature and it deals X damage to you."
#
# Nothing here is a new prompt. The offer is the ordinary ``optional_pay``, and
# the whole card is three additions to things that already existed: a P/T
# counter is a counter kind the "the number of <kind> counters on it" phrase can
# name; a where-clause may be defined by one; and an offered mana cost may carry
# an ``{X}`` that is read at resolution rather than at lowering — which is what
# CR 608.2 asks for, since the counter this ability just placed is part of the
# number.


def _r31_ooze(set_pool, *, counters=0, lands=4, interactive=True):
    """Primordial Ooze under seat 0 with *lands* untapped Mountains beside it."""
    from engine.pt import add_pt_counters
    from tests.helpers import CARDS_BY_NAME

    ooze = Permanent(card=set_pool("LEG")["Primordial Ooze"])
    if counters:
        add_pt_counters(ooze, "+1/+1", counters)
    battlefield = [ooze] + [
        Permanent(card=CARDS_BY_NAME["Mountain"]) for _ in range(lands)
    ]
    p1 = PlayerState(name="P1", battlefield=battlefield,
                     library=[_vanilla("Filler", 1, 1) for _ in range(5)])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    game.start_turn(0)
    game._settle()
    return game, p1, ooze


def test_the_upkeep_offer_is_priced_by_the_counter_it_just_placed(set_pool):
    """CR 608.2: the count is taken when the ability resolves, and the counter
    this same ability placed is part of it — two counters plus the new one is
    {3}, not {2}."""
    game, _p1, ooze = _r31_ooze(set_pool, counters=2)

    assert ooze.metadata["plus_counters"] == 3
    offer = game.pending_optional_pays[0]
    assert offer["cost"] == {"generic": 3}
    assert offer["prompt"] == "Pay {3}?"
    assert game.waiting_prompt() is not None, "the upkeep waits on the answer"


def test_paying_leaves_it_untapped_and_unharmed(set_pool):
    game, p1, ooze = _r31_ooze(set_pool, counters=2)

    assert game.resolve_pending_choice("optional_pay", 0, accept=True)

    assert not ooze.tapped and p1.life == 20
    untapped = [p for p in p1.battlefield if p.card.name == "Mountain" and not p.tapped]
    assert len(untapped) == 1, "three of the four lands paid for it"


def test_declining_taps_it_and_deals_that_same_number(set_pool):
    """The "if you don't" branch reads the *same* X the offer was priced by —
    one sentence, one number."""
    game, p1, ooze = _r31_ooze(set_pool, counters=2)

    assert game.resolve_pending_choice("optional_pay", 0, accept=False)

    assert ooze.tapped and p1.life == 17


def test_a_seat_that_cannot_pay_is_never_offered_and_takes_the_consequence(set_pool):
    """An offer nobody could take is not made, and its decline branch still
    applies — the ordinary rule for an optional cost, here with a variable one."""
    game, p1, ooze = _r31_ooze(set_pool, counters=2, lands=0)

    assert game.pending_optional_pays == []
    assert ooze.tapped and p1.life == 17


def test_the_price_grows_with_the_creature(set_pool):
    """The control: nothing about this card is {3}. A second upkeep is a bigger
    creature and a bigger bill."""
    game, p1, ooze = _r31_ooze(set_pool, counters=0)

    assert game.pending_optional_pays[0]["cost"] == {"generic": 1}
    assert game.resolve_pending_choice("optional_pay", 0, accept=False)
    assert p1.life == 19

    game.start_turn(0)
    game._settle()
    assert ooze.metadata["plus_counters"] == 2
    assert game.pending_optional_pays[0]["cost"] == {"generic": 2}

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


# ---------------------------------------------------------------------------
# Round 32 — a trigger that reads the combat it fired in, and a record that
# switches off combat damage
# ---------------------------------------------------------------------------


def _r32_spuzzem_game(set_pool, catalog_by_name):
    """Floral Spuzzem and an artifact of *its own* under P1; two of P2's.

    The artifact on P1's side is the whole point of the board: "target artifact
    **defending player controls**" must never offer it, and the fire site used
    to stamp the attacker's own battlefield slot as the target — so what the
    ability destroyed was whatever sat at that index on the attacker's side.
    """
    spuzzem = Permanent(card=set_pool("LEG")["Floral Spuzzem"])
    p1 = PlayerState(name="P1", battlefield=[
        spuzzem, Permanent(card=catalog_by_name["Mox Pearl"]),
    ])
    p2 = PlayerState(name="P2", battlefield=[
        Permanent(card=catalog_by_name["Mox Ruby"]),
        Permanent(card=catalog_by_name["Black Lotus"]),
    ])
    game = Game(players=[p1, p2])
    # An interactive seat is what makes the two prompts *queue* rather than take
    # their defaults at once, which is what lets a test answer them.
    game.interactive_seats = {0}
    return game, p1, p2, spuzzem


def _r32_attack_unblocked(game):
    """Attack with the creature in slot 0 and run to the moment blocks lock."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    game.advance_combat_phase()   # declare blockers
    ok, msg = game.declare_blockers(1, {})
    assert ok, msg
    game._settle()
    game.advance_combat_phase()   # blocks lock: the trigger fires here
    return game.pending_choices_of("trigger_target")


def _r32_finish_combat(game):
    """Advance to the end of the combat phase, however many steps are left."""
    game._settle()
    for _ in range(len(list(game._phase_steps("combat"))) + 1):
        if game.current_turn_phase != "combat":
            break
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        game._settle()
        if (game.current_turn_phase, game.current_step) == before:
            break


def test_floral_spuzzem_offers_only_the_defending_players_artifacts(
    set_pool, catalog_by_name
):
    """CR 603.3d: the ability chooses its target as it goes on the stack, and
    the noun phrase is "artifact **defending player controls**" — so the
    attacker's own Mox is not a candidate."""
    game, _, p2, _ = _r32_spuzzem_game(set_pool, catalog_by_name)

    pending = list(_r32_attack_unblocked(game))

    assert len(pending) == 1, game.log
    offered = pending[0].data["targets"]
    assert {t["name"] for t in offered} == {"Mox Ruby", "Black Lotus"}, game.log
    assert {t["seat"] for t in offered} == {1}, game.log
    assert {t["permanent_id"] for t in offered} == {
        p.permanent_id for p in p2.battlefield
    }


def test_floral_spuzzem_destroys_the_artifact_and_then_deals_no_combat_damage(
    set_pool, catalog_by_name
):
    """The rider is the card. "If you do, this creature assigns no combat
    damage this turn" has to be read by the damage step, not merely set — so
    this asserts the defending player's life, not a flag."""
    game, _, p2, spuzzem = _r32_spuzzem_game(set_pool, catalog_by_name)

    pending = list(_r32_attack_unblocked(game))
    chosen = pending[0].data["targets"][0]
    assert game.confirm_trigger_target(0, chosen["permanent_id"])
    game._settle()
    assert game.confirm_optional_pay(0, "Floral Spuzzem", accept=True)
    _r32_finish_combat(game)

    assert [p.card.name for p in p2.battlefield] == ["Black Lotus"], game.log
    assert p2.life == 20, game.log


def test_floral_spuzzem_declining_the_may_leaves_the_damage_alone(
    set_pool, catalog_by_name
):
    """The other half of "if you do": nothing destroyed, so the rider never
    runs and the 2/2 connects for two."""
    game, _, p2, spuzzem = _r32_spuzzem_game(set_pool, catalog_by_name)

    pending = list(_r32_attack_unblocked(game))
    assert game.confirm_trigger_target(0, pending[0].data["targets"][0]["permanent_id"])
    game._settle()
    assert game.confirm_optional_pay(0, "Floral Spuzzem", accept=False)
    _r32_finish_combat(game)

    assert len(p2.battlefield) == 2, game.log
    assert p2.life == 18, game.log


def test_floral_spuzzem_is_free_to_hit_again_next_turn(set_pool, catalog_by_name):
    """"…this turn": the mark is swept with the rest of the turn's records, so
    a second combat is unaffected by the first. The test that catches a record
    written once and never ended."""
    game, _, p2, spuzzem = _r32_spuzzem_game(set_pool, catalog_by_name)

    pending = list(_r32_attack_unblocked(game))
    assert game.confirm_trigger_target(0, pending[0].data["targets"][0]["permanent_id"])
    game._settle()
    assert game.confirm_optional_pay(0, "Floral Spuzzem", accept=True)
    _r32_finish_combat(game)
    assert p2.life == 20, game.log

    # CR 514.2's cleanup is what ends "this turn", and it is the only thing
    # that does — the mark is swept there with the rest of the turn's records.
    game.resolve_cleanup_step(0)
    assert not spuzzem.metadata.get("assigns_no_combat_damage_until_eot")

    pending = list(_r32_attack_unblocked(game))
    # Only one artifact left, so there is still a legal target and the ability
    # still goes on the stack — this time the offer is declined.
    assert game.confirm_trigger_target(0, pending[0].data["targets"][0]["permanent_id"])
    game._settle()
    assert game.confirm_optional_pay(0, "Floral Spuzzem", accept=False)
    _r32_finish_combat(game)

    assert p2.life == 18, game.log


def test_floral_spuzzem_with_no_artifact_to_name_never_goes_on_the_stack(
    set_pool, catalog_by_name
):
    """CR 603.3d's last sentence: "if no legal choices can be made for it …
    the ability is simply removed from the stack." An empty defending board is
    that case, and the attack is an ordinary one."""
    spuzzem = Permanent(card=set_pool("LEG")["Floral Spuzzem"])
    p1 = PlayerState(name="P1", battlefield=[
        spuzzem, Permanent(card=catalog_by_name["Mox Pearl"]),
    ])
    p2 = PlayerState(name="P2", battlefield=[])
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}

    assert list(_r32_attack_unblocked(game)) == []
    assert not game.stack, game.log
    _r32_finish_combat(game)

    assert p2.life == 18, game.log


# ---------------------------------------------------------------------------
# Round 33 — a token that names its maker, and two delays pointing opposite ways
# ---------------------------------------------------------------------------


def _r33_stangg(set_pool):
    """Stangg cast and resolved under P1, its enters-trigger settled."""
    pool = set_pool("LEG")
    p1 = PlayerState(name="P1", hand=[pool["Stangg"]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.queue_from_hand(0, "Stangg")
    game.resolve_stack()
    game._settle()
    stangg = next(p for p in p1.battlefield if p.card.name == "Stangg")
    return game, p1, p2, stangg


def _r33_twin(player):
    return next(
        (p for p in player.battlefield if p.card.name == "Stangg Twin"), None
    )


def test_stangg_creates_a_legendary_three_four_red_and_green_twin(set_pool):
    """Every printed characteristic of the token, the supertype included: the
    legend rule (CR 704.5j) reads the type line, so "legendary" is not a word
    the payload may drop."""
    _game, p1, _p2, _stangg = _r33_stangg(set_pool)

    twin = _r33_twin(p1)
    assert twin is not None
    assert twin.effective_power == 3 and twin.effective_toughness == 4
    assert set(twin.card.colors) == {"R", "G"}
    assert twin.has_type("human") and twin.has_type("warrior")
    assert twin.card.is_legendary


def test_stangg_twins_name_survives_the_lexers_self_reference(set_pool):
    """The token's printed name *contains* the card's own name, which the lexer
    has already collapsed into one SELF token. The name is recovered from that
    token's text — read as a name rather than as the card talking about
    itself."""
    _game, p1, _p2, _stangg = _r33_stangg(set_pool)

    assert _r33_twin(p1).card.name == "Stangg Twin"


def test_stangg_leaving_exiles_the_twin(set_pool):
    """"Exile that token when Stangg leaves the battlefield." The delay watches
    Stangg and acts on the token — the binding runs one way."""
    game, p1, _p2, stangg = _r33_stangg(set_pool)
    assert _r33_twin(p1) is not None

    game._destroy_swept_permanents(p1, lambda perm: perm is stangg)
    game._settle()

    assert _r33_twin(p1) is None, game.log
    # CR 111.7: a token that has left the battlefield ceases to exist, so
    # nothing named Stangg Twin is sitting in a zone anywhere.
    assert all(card.name != "Stangg Twin" for card in p1.exile)
    assert all(card.name != "Stangg Twin" for card in p1.graveyard)


def test_the_twin_leaving_sacrifices_stangg(set_pool):
    """"Sacrifice Stangg when that token leaves the battlefield." The other
    delay, watching the token and acting on the source — the binding the
    creating instruction could not have made, because the token did not exist
    until the instruction in front of it had run."""
    game, p1, _p2, _stangg = _r33_stangg(set_pool)
    twin = _r33_twin(p1)

    game._destroy_swept_permanents(p1, lambda perm: perm is twin)
    game._settle()

    assert all(perm.card.name != "Stangg" for perm in p1.battlefield), game.log
    assert any(card.name == "Stangg" for card in p1.graveyard), game.log


def test_stangg_being_exiled_still_exiles_the_twin(set_pool):
    """CR 603.6c's event is *any* move off the battlefield, not a death — which
    is why this is its own delayed event rather than the dies one beside it."""
    game, p1, _p2, stangg = _r33_stangg(set_pool)

    game.remove_from_battlefield(stangg)
    p1.exile.append(stangg.card)
    game._settle()

    assert _r33_twin(p1) is None, game.log


def test_the_twin_leaving_sacrifices_only_its_own_stangg(set_pool):
    """The delay is bound by **id**, not by name or by value. An opponent's
    Stangg is a different object (CR 400.7) and is untouched when this one's
    token leaves — the look-alike bug this engine keeps finding, in a delayed
    entry instead of on a battlefield.

    Under the opponent rather than beside it, because two legendary permanents
    named Stangg under one player is the legend rule (CR 704.5j) answering the
    question instead of the binding."""
    game, p1, p2, _stangg = _r33_stangg(set_pool)
    other = Permanent(card=set_pool("LEG")["Stangg"])
    p2.battlefield.append(other)

    twin = _r33_twin(p1)
    game._destroy_swept_permanents(p1, lambda perm: perm is twin)
    game._settle()

    assert all(perm.card.name != "Stangg" for perm in p1.battlefield), game.log
    assert [perm for perm in p2.battlefield if perm.card.name == "Stangg"] == [other]


# ---------------------------------------------------------------------------
# Round 35 — Blazing Effigy, and a record of what each source dealt this turn
# ---------------------------------------------------------------------------


def _r35_effigies(set_pool, count: int):
    """*count* Blazing Effigies under P1, and a second seat that owns nothing."""
    effigy = set_pool("LEG")["Blazing Effigy"]
    mine = [Permanent(card=effigy) for _ in range(count)]
    p1 = PlayerState(name="P1", battlefield=mine)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)
    return game, p1, p2, mine


def test_blazing_effigy_deals_three_with_nothing_behind_it(set_pool):
    """"X is 3 plus the amount of damage dealt to this creature this turn."
    The printed floor, which is what the card does on an empty history — and
    the number a reader that gave up on a missing record would silently drop."""
    game, p1, _p2, effigies = _r35_effigies(set_pool, 2)

    game._destroy_swept_permanents(p1, lambda perm: perm is effigies[0])
    game._settle()

    # 3 damage on a 0/3 is lethal, so the second one dies to the first's trigger.
    assert p1.battlefield == [], game.log
    assert any("dealt 3 damage" in line for line in game.log), game.log


def test_the_chain_adds_what_the_previous_effigy_dealt(set_pool):
    """The card's whole point: each Effigy that dies passes on 3 plus what the
    one before it dealt to the one after. 3, then 6, then 9.

    The 6 is the number this round exists for — the damage that made it is on a
    creature that is in a graveyard by the time its own trigger asks, with the
    damage marked on it wiped when it left (CR 400.7). Nothing on a board can
    answer it; ``engine/damage_ledger.py`` is the record that can."""
    game, p1, _p2, effigies = _r35_effigies(set_pool, 3)

    game._destroy_swept_permanents(p1, lambda perm: perm is effigies[0])
    game._settle()

    assert p1.battlefield == [], game.log
    assert any("dealt 6 damage" in line for line in game.log), game.log


def test_damage_from_a_differently_named_source_is_not_counted(set_pool):
    """"…by other sources **named** Blazing Effigy" (CR 201.2). A ledger that
    summed every point dealt to the creature would make this Effigy's trigger
    deal 5, and it would still look like a working card."""
    from tests.helpers import _damage_dealt

    game, p1, _p2, effigies = _r35_effigies(set_pool, 2)
    bolt = _vanilla("Not An Effigy", 1, 1)
    _damage_dealt(game, effigies[0], 2, source=bolt)

    game._destroy_swept_permanents(p1, lambda perm: perm is effigies[0])
    game._settle()

    assert any("dealt 3 damage" in line for line in game.log), game.log
    assert not any("dealt 5 damage" in line for line in game.log), game.log


def test_the_record_is_per_permanent_and_not_per_card(set_pool):
    """A ``CardDefinition`` is shared by every copy in every deck, so a record
    keyed on the card would credit one Effigy with what another one took.

    Asked of the record itself rather than through a trigger, because the
    difference is invisible on a board small enough to run: the first Effigy is
    dealt nothing and the second is dealt 3, and a card-keyed ledger would
    answer 3 for both. Keyed on ``permanent_id``, which CR 400.7 makes one per
    time on the battlefield."""
    from engine.damage_ledger import damage_dealt_to_permanent

    game, p1, _p2, effigies = _r35_effigies(set_pool, 3)
    first, second = effigies[0].permanent_id, effigies[1].permanent_id

    game._destroy_swept_permanents(p1, lambda perm: perm is effigies[0])
    game._settle()

    assert damage_dealt_to_permanent(game, first, source_name="Blazing Effigy") == 0
    assert damage_dealt_to_permanent(game, second, source_name="Blazing Effigy") == 3
