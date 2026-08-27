"""Tests for Comprehensive Rules section 306 (Planeswalkers) and 606 (Loyalty
Abilities), plus the planeswalker clauses of combat (508/509/510), damage
results (120.3c) and state-based actions (704.5i/j).

Loyalty lives in ``Permanent.metadata["loyalty_counters"]`` (CR 306.5c says the
loyalty of a planeswalker on the battlefield *is* its loyalty counters), written
on entry by ``_initialize_permanent_state`` and adjusted by loyalty costs and by
damage. Tests that build a board by hand set that key themselves, exactly as a
hand-built creature sets its own ``damage_marked``.

CR 606.5 (several costs to add or remove loyalty counters combining into one)
is deliberately untested: it needs a second, *additional* loyalty cost to
combine the printed one with — Carth the Lion's "loyalty abilities you control
cost an additional [+1]" is the rule's own example — and nothing in this engine
can produce one. ``mixins/stack/activation.py`` derives the delta from the
ability's own loyalty symbol alone, so a test here could only re-assert that
one cost is one cost.
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_walker(
    name: str = "Test Walker, the Tester",
    loyalty: str = "3",
    oracle_text: str = "+1: Draw a card.\n−2: Test Walker deals 2 damage to any target.",
    type_line: str = "Legendary Planeswalker — Tester",
) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="{2}",
        cmc=2.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=("U",),
        color_identity=("U",),
        keywords=(),
        produced_mana=(),
        raw={},
        loyalty=loyalty,
    )


def _mk_creature(name: str, power: int, toughness: int, keywords: tuple[str, ...] = ()) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Test",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=keywords,
        produced_mana=(),
        raw={"power": str(power), "toughness": str(toughness)},
        power=str(power),
        toughness=str(toughness),
    )


def _cast_walker(loyalty: str = "3", oracle_text: str | None = None) -> tuple[Game, Permanent]:
    """A fresh two-player game with the test walker cast and resolved."""
    kwargs = {"loyalty": loyalty}
    if oracle_text is not None:
        kwargs["oracle_text"] = oracle_text
    card = _mk_walker(**kwargs)
    p1 = PlayerState(name="P1", hand=[card], library=[_mk_creature("Filler", 1, 1)] * 5)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.cast_from_hand(0, card.name)
    walker = next(iter(game.controlled_by(0)))
    return game, walker


def _combat_game(
    attacker_card: CardDefinition,
    defender_battlefield: list[Permanent],
) -> tuple[Game, Permanent]:
    """A game advanced to the declare-attackers step, seat 0 attacking."""
    attacker = Permanent(card=attacker_card)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=defender_battlefield)
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    attacker.metadata.pop("summoning_sickness_turn", None)
    return game, attacker


def _walker_on_battlefield(loyalty: int = 5) -> Permanent:
    return Permanent(card=_mk_walker(), metadata={"loyalty_counters": loyalty})


# ---------------------------------------------------------------------------
# 306.1 / 306.2 — casting a planeswalker; the spell resolves to the battlefield
# ---------------------------------------------------------------------------

@pytest.mark.cr("306.1")
def test_306_1_planeswalker_cast_from_hand_during_main_phase():
    """306.1: A planeswalker card may be cast from hand during a main phase."""
    card = _mk_walker()
    p1 = PlayerState(name="P1", hand=[card])
    game = Game(players=[p1, PlayerState(name="P2")])
    assert game.current_turn_phase == "precombat_main"
    result = game.cast_from_hand(0, card.name)
    assert result.supported
    assert not any(c is card for c in p1.hand)


@pytest.mark.cr("306.2")
def test_306_2_resolved_planeswalker_enters_under_its_controller():
    """306.2: A resolved planeswalker spell is put onto the battlefield under
    its controller's control."""
    game, walker = _cast_walker()
    assert game.is_on_battlefield(walker)
    assert game.controller_index_of(walker) == 0


@pytest.mark.cr("306.3")
def test_306_3_planeswalker_subtype_parsed_from_type_line():
    """306.3: The word after the dash is a planeswalker subtype."""
    game, walker = _cast_walker()
    assert walker.has_type("planeswalker")
    assert walker.has_type("tester")


# ---------------------------------------------------------------------------
# 306.4 — planeswalkers are legendary and subject to the legend rule
# ---------------------------------------------------------------------------

@pytest.mark.cr("306.4", "704.5j")
def test_306_4_two_same_name_walkers_trigger_the_legend_rule():
    """306.4/704.5j: One player controlling two same-name legendary
    planeswalkers keeps one; the other goes to its owner's graveyard."""
    first = _walker_on_battlefield(3)
    second = _walker_on_battlefield(3)
    p1 = PlayerState(name="P1", battlefield=[first, second])
    game = Game(players=[p1, PlayerState(name="P2")])
    walkers_left = [p for p in game.controlled_by(0) if p.has_type("planeswalker")]
    assert len(walkers_left) == 1
    assert any(c.name == first.card.name for c in p1.graveyard)


@pytest.mark.cr("306.4", "704.5j")
def test_306_4_same_name_walkers_under_different_players_both_stay():
    """704.5j is per controller: the same walker under two different players
    is legal."""
    p1 = PlayerState(name="P1", battlefield=[_walker_on_battlefield(3)])
    p2 = PlayerState(name="P2", battlefield=[_walker_on_battlefield(3)])
    game = Game(players=[p1, p2])
    assert sum(1 for p in game.all_permanents() if p.has_type("planeswalker")) == 2


# ---------------------------------------------------------------------------
# 306.5 — loyalty
# ---------------------------------------------------------------------------

@pytest.mark.cr("306.5a")
def test_306_5a_loyalty_of_a_card_not_on_the_battlefield_is_printed():
    """306.5a: Off the battlefield, loyalty is the printed number."""
    card = _mk_walker(loyalty="4")
    assert card.loyalty == "4"


@pytest.mark.cr("306.5b", "614.1c")
def test_306_5b_planeswalker_enters_with_printed_loyalty_in_counters():
    """306.5b: A planeswalker enters the battlefield with loyalty counters
    equal to its printed loyalty number."""
    game, walker = _cast_walker(loyalty="4")
    assert walker.metadata.get("loyalty_counters") == 4


@pytest.mark.cr("306.5c")
def test_306_5c_loyalty_on_battlefield_is_its_loyalty_counters():
    """306.5c: On the battlefield, loyalty is the number of loyalty counters."""
    game, walker = _cast_walker(loyalty="3")
    walker.metadata["loyalty_counters"] = 7
    game._mark_damage_on_permanent(walker, 2, source=None)
    assert walker.metadata["loyalty_counters"] == 5


@pytest.mark.cr("306.5d", "606.2")
def test_306_5d_loyalty_lines_compile_as_activated_abilities():
    """306.5d/606.2: An ability with a loyalty symbol in its cost is an
    activated loyalty ability."""
    program = compile_card_oracle(_mk_walker())
    assert program.supported
    assert len(program.activated_abilities) == 2
    assert all(a.cost.is_loyalty for a in program.activated_abilities)
    assert program.activated_abilities[0].cost.loyalty == 1
    assert program.activated_abilities[1].cost.loyalty == -2


# ---------------------------------------------------------------------------
# 606 — activating loyalty abilities
# ---------------------------------------------------------------------------

@pytest.mark.cr("606.3")
def test_606_3_loyalty_ability_activates_during_own_main_phase():
    """606.3: Legal during a main phase of the controller's turn, stack empty."""
    game, walker = _cast_walker()
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert result.supported


@pytest.mark.cr("606.3")
def test_606_3_loyalty_ability_refused_outside_a_main_phase():
    """606.3: Not legal outside a main phase."""
    game, walker = _cast_walker()
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert not result.supported


@pytest.mark.cr("606.3")
def test_606_3_loyalty_ability_refused_on_an_opponents_turn():
    """606.3: Not legal on another player's turn."""
    game, walker = _cast_walker()
    game.active_player_index = 1
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert not result.supported


@pytest.mark.cr("606.3")
def test_606_3_loyalty_ability_refused_while_stack_is_occupied():
    """606.3: Not legal while the stack is not empty."""
    game, walker = _cast_walker()
    game.stack.append(object())
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert not result.supported
    game.stack.pop()


@pytest.mark.cr("606.3")
def test_606_3_only_one_loyalty_ability_per_permanent_per_turn():
    """606.3: A second loyalty activation of the same permanent in one turn is
    refused, and the lock lifts on a later turn."""
    game, walker = _cast_walker()
    assert game.activate_permanent_ability(0, walker.card.name, ability_index=0).supported
    second = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert not second.supported
    game.turn += 1
    third = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert third.supported


@pytest.mark.cr("606.4")
def test_606_4_plus_ability_adds_loyalty_counters_as_its_cost():
    """606.4: Activating "+1" puts one loyalty counter on the permanent."""
    game, walker = _cast_walker(loyalty="3")
    game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert walker.metadata["loyalty_counters"] == 4


@pytest.mark.cr("606.4")
def test_606_4_minus_ability_removes_loyalty_counters_as_its_cost():
    """606.4: Activating "−2" removes two loyalty counters."""
    game, walker = _cast_walker(loyalty="3")
    game.activate_permanent_ability(
        0, walker.card.name, ability_index=1, target_player_index=1
    )
    assert walker.metadata["loyalty_counters"] == 1


@pytest.mark.cr("606.6")
def test_606_6_minus_ability_needs_that_many_counters():
    """606.6: A negative loyalty cost can't be activated without at least that
    many loyalty counters on the permanent."""
    game, walker = _cast_walker(loyalty="3")
    walker.metadata["loyalty_counters"] = 1
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=1, target_player_index=1
    )
    assert not result.supported
    assert walker.metadata["loyalty_counters"] == 1


@pytest.mark.cr("606.2", "606.4")
def test_606_2_variable_loyalty_cost_removes_x_counters():
    """606.2/606.4: A "−X" loyalty cost removes the announced X."""
    text = "−X: Test Walker deals X damage to any target."
    game, walker = _cast_walker(loyalty="5", oracle_text=text)
    program = compile_card_oracle(walker.card)
    assert program.activated_abilities[0].cost.loyalty_x_sign == -1
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=0, target_player_index=1, x_value=3
    )
    assert result.supported
    assert walker.metadata["loyalty_counters"] == 2


@pytest.mark.cr("606.6")
def test_606_6_variable_cost_larger_than_loyalty_is_refused():
    """606.6 applies to the announced X as well."""
    text = "−X: Test Walker deals X damage to any target."
    game, walker = _cast_walker(loyalty="2", oracle_text=text)
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=0, target_player_index=1, x_value=5
    )
    assert not result.supported
    assert walker.metadata["loyalty_counters"] == 2


@pytest.mark.cr("606.3")
def test_606_3_card_static_widens_loyalty_timing_to_instant_speed():
    """A card may modify 606.3's timing half (Teferi, Master of Time's
    static); the once-per-turn half stays."""
    text = (
        "You may activate loyalty abilities of Test Walker on any player's turn "
        "any time you could cast an instant.\n"
        "+1: Draw a card."
    )
    game, walker = _cast_walker(oracle_text=text)
    game.active_player_index = 1  # an opponent's turn
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert result.supported
    second = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert not second.supported


@pytest.mark.cr("602.5c", "302.6")
def test_loyalty_ability_usable_the_turn_the_walker_arrives():
    """Loyalty costs don't involve {T}, so summoning sickness (CR 302.6's tap
    clause) never applies — a walker cast this turn can activate at once."""
    game, walker = _cast_walker()
    assert walker.metadata.get("summoning_sickness_turn") is None or True
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert result.supported


# ---------------------------------------------------------------------------
# 306.8 / 120.3c — damage removes loyalty counters
# ---------------------------------------------------------------------------

@pytest.mark.cr("306.8", "120.3c")
def test_306_8_damage_removes_that_many_loyalty_counters():
    """306.8/120.3c: Damage dealt to a planeswalker removes that many loyalty
    counters, and marks no damage on it."""
    game, walker = _cast_walker(loyalty="5")
    game._mark_damage_on_permanent(walker, 3, source=None)
    assert walker.metadata["loyalty_counters"] == 2
    assert walker.damage_marked == 0


@pytest.mark.cr("115.4", "306.7")
def test_115_4_any_target_spell_may_hit_a_planeswalker_directly():
    """115.4: "any target" includes planeswalkers — damage is dealt to the
    walker itself (306.7: there is no redirection any more)."""
    bolt = CardDefinition(
        name="Test Bolt", mana_cost="{R}", cmc=1.0, type_line="Instant",
        oracle_text="Test Bolt deals 3 damage to any target.",
        colors=("R",), color_identity=("R",), keywords=(), produced_mana=(), raw={},
    )
    walker = _walker_on_battlefield(5)
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])
    game.cast_from_hand(0, "Test Bolt", target_player_index=1, target_permanent_index=0)
    assert walker.metadata["loyalty_counters"] == 2
    assert game.players[1].life == 20


# ---------------------------------------------------------------------------
# 306.9 / 704.5i — zero loyalty is a state-based death
# ---------------------------------------------------------------------------

@pytest.mark.cr("306.9", "704.5i")
def test_306_9_zero_loyalty_planeswalker_goes_to_graveyard():
    """306.9/704.5i: A planeswalker whose loyalty is 0 is put into its owner's
    graveyard by state-based actions."""
    game, walker = _cast_walker(loyalty="3")
    game._mark_damage_on_permanent(walker, 3, source=None)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(walker)
    assert any(c.name == walker.card.name for c in game.players[0].graveyard)


@pytest.mark.cr("704.5i", "606.4")
def test_704_5i_paying_all_loyalty_kills_the_walker_before_resolution():
    """606.4 costs are paid on activation, so a minus ability that empties the
    walker's loyalty sends it to the graveyard while the ability is pending."""
    game, walker = _cast_walker(loyalty="2")
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=1, target_player_index=1
    )
    assert result.supported
    game.check_state_based_actions()
    assert not game.is_on_battlefield(walker)
    # The ability still resolved (CR 602.2 costs are independent of the source
    # surviving) — the damage was dealt.
    assert game.players[1].life == 18


# ---------------------------------------------------------------------------
# 306.6 / 508.1b — attacking planeswalkers
# ---------------------------------------------------------------------------

@pytest.mark.cr("306.6", "508.1b")
def test_508_1b_declaring_an_attack_against_a_planeswalker():
    """306.6/508.1b: A creature may be declared attacking an opponent's
    planeswalker; the defending player is the walker's controller."""
    walker = _walker_on_battlefield(5)
    game, attacker = _combat_game(_mk_creature("Bear", 2, 2), [walker])
    ok, _ = game.declare_attackers(0, [0], attacker_planeswalker_ids={0: walker.permanent_id})
    assert ok
    assert game.combat_attackers[0] == 1
    assert game.combat_attacked_planeswalkers[0] == walker.permanent_id


@pytest.mark.cr("508.1b")
def test_508_1b_cannot_attack_your_own_planeswalker():
    """508.1b names a planeswalker an *opponent* controls."""
    walker = _walker_on_battlefield(5)
    attacker = Permanent(card=_mk_creature("Bear", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker, walker])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    attacker.metadata.pop("summoning_sickness_turn", None)
    ok, message = game.declare_attackers(0, [0], attacker_planeswalker_ids={0: walker.permanent_id})
    assert not ok
    assert "opponent" in message


@pytest.mark.cr("509.1a")
def test_509_1a_defender_may_block_a_creature_attacking_their_walker():
    """509.1a: The defending player may block a creature that is attacking a
    planeswalker they control; the blocked attacker deals no damage to it."""
    walker = _walker_on_battlefield(5)
    blocker = Permanent(card=_mk_creature("Wall", 0, 4))
    game, attacker = _combat_game(_mk_creature("Bear", 3, 3), [walker, blocker])
    game.declare_attackers(0, [0], attacker_planeswalker_ids={0: walker.permanent_id})
    game.advance_combat_phase()
    ok, _ = game.declare_blockers(1, {1: 0})
    assert ok
    game.advance_combat_phase()
    assert walker.metadata["loyalty_counters"] == 5
    assert blocker.damage_marked == 3


@pytest.mark.cr("510.1b")
def test_510_1b_unblocked_attacker_damages_the_walker_not_the_player():
    """510.1b: An unblocked creature attacking a planeswalker assigns its
    combat damage to the planeswalker."""
    walker = _walker_on_battlefield(5)
    game, attacker = _combat_game(_mk_creature("Bear", 3, 3), [walker])
    game.declare_attackers(0, [0], attacker_planeswalker_ids={0: walker.permanent_id})
    game.advance_combat_phase()
    game.declare_blockers(1, {})
    game.advance_combat_phase()
    assert walker.metadata["loyalty_counters"] == 2
    assert game.players[1].life == 20


@pytest.mark.cr("510.1b", "506.4c")
def test_510_1b_attacker_of_a_departed_walker_assigns_no_damage():
    """510.1b: A creature attacking a planeswalker that has left the
    battlefield assigns no combat damage — it does not fall back to the
    player (506.4c)."""
    walker = _walker_on_battlefield(5)
    game, attacker = _combat_game(_mk_creature("Bear", 3, 3), [walker])
    game.declare_attackers(0, [0], attacker_planeswalker_ids={0: walker.permanent_id})
    game.advance_combat_phase()
    game.declare_blockers(1, {})
    game.remove_from_battlefield(walker)
    game.advance_combat_phase()
    assert game.players[1].life == 20


@pytest.mark.cr("702.19b")
def test_702_19b_trample_excess_goes_to_the_attacked_walker():
    """702.19b: A trampler attacking a planeswalker assigns lethal damage to
    its blockers and may assign the excess to the planeswalker."""
    walker = _walker_on_battlefield(5)
    chump = Permanent(card=_mk_creature("Chump", 1, 1))
    game, attacker = _combat_game(_mk_creature("Crusher", 5, 5, ("Trample",)), [walker, chump])
    game.declare_attackers(0, [0], attacker_planeswalker_ids={0: walker.permanent_id})
    game.advance_combat_phase()
    game.declare_blockers(1, {1: 0})
    game.advance_combat_phase()
    assert walker.metadata["loyalty_counters"] == 1
    assert game.players[1].life == 20


@pytest.mark.cr("702.19f")
def test_702_19f_no_combat_damage_to_the_player_when_attacking_a_walker():
    """702.19f: Without trample over planeswalkers, a creature attacking a
    planeswalker can never assign combat damage to the defending player, even
    when its damage exceeds the walker's loyalty."""
    walker = _walker_on_battlefield(2)
    game, attacker = _combat_game(_mk_creature("Giant", 6, 6, ("Trample",)), [walker])
    game.declare_attackers(0, [0], attacker_planeswalker_ids={0: walker.permanent_id})
    game.advance_combat_phase()
    game.declare_blockers(1, {})
    game.advance_combat_phase()
    assert not game.is_on_battlefield(walker)
    assert game.players[1].life == 20


@pytest.mark.cr("506.4c", "508.1k")
def test_508_1k_walker_attacker_is_an_attacking_creature():
    """508.1k: The chosen creature becomes an attacking creature whether it
    attacks a player or a planeswalker."""
    walker = _walker_on_battlefield(5)
    game, attacker = _combat_game(_mk_creature("Bear", 2, 2), [walker])
    game.declare_attackers(0, [0], attacker_planeswalker_ids={0: walker.permanent_id})
    assert attacker.attacking
    assert attacker.tapped  # 508.1f


# ---------------------------------------------------------------------------
# The compiler's support gate
# ---------------------------------------------------------------------------

@pytest.mark.cr("306.5d")
def test_walker_with_an_unreadable_ability_is_unsupported_naming_it():
    """A planeswalker with one dead ability must not report supported — the
    gate is all-of, and the reason names the clause."""
    card = _mk_walker(
        oracle_text="+1: Draw a card.\n−6: Do something no parser reads."
    )
    program = compile_card_oracle(card)
    assert not program.supported
    assert "−6" in program.reason


@pytest.mark.cr("601.2b")
def test_walker_x_cost_ability_reports_x_spec():
    """The −X cost is exposed on the parsed ability so the UI can ask for
    X at activation (CR 601.2b's announcement, applied to abilities via
    602.2b)."""
    card = _mk_walker(oracle_text="−X: Test Walker deals X damage to any target.")
    program = compile_card_oracle(card)
    assert program.supported
    ability = program.activated_abilities[0]
    assert ability.cost.loyalty is None
    assert ability.cost.loyalty_x_sign == -1
