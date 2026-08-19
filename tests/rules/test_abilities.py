"""Tests for Magic: The Gathering Comprehensive Rules Sections 602–607.

Covers:
  602 — Activating Activated Abilities
  603 — Handling Triggered Abilities
  604 — Handling Static Abilities
  605 — Mana Abilities
  606 — Loyalty Abilities
  607 — Linked Abilities

The engine models an activated ability as a cost (mana + tap) plus an effect
instruction; non-mana abilities are placed on the stack and resolved, while mana
abilities resolve immediately (605.3b). Triggered abilities are fired by the
phase/step machinery (e.g. upkeep, draw step) and by event hooks (creature
dies). Static abilities create continuous effects recalculated as the board
changes.
"""

import pytest

from engine import Game, PlayerState, load_cards
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, parse_activated_ability_cost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_card(
    name: str,
    type_line: str,
    oracle_text: str = "",
    mana_cost: str = "",
    colors: tuple[str, ...] = (),
    cmc: float = 0.0,
    produced_mana: tuple[str, ...] = (),
    power: str = "2",
    toughness: str = "2",
    keywords: tuple[str, ...] = (),
) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = power
        raw["toughness"] = toughness
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=cmc,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=keywords,
        produced_mana=produced_mana,
        raw=raw,
    )


def _bear(name: str = "Bear", power: str = "2", toughness: str = "2") -> CardDefinition:
    return _mk_card(name, "Creature — Bear", power=power, toughness=toughness)


def _not_summoning_sick(game: Game, permanent: Permanent) -> None:
    """Pretend *permanent* has been controlled since the start of its
    controller's most recent turn (602.5a) by clearing its sickness marker."""
    permanent.metadata["summoning_sickness_turn"] = game.turn - 1


def _get(all_cards, name: str) -> CardDefinition:
    return next(card for card in all_cards if card.name == name)


# ===========================================================================
# Rule 602 — Activating Activated Abilities
# ===========================================================================


# 602.1 / 602.1a — an activated ability is "[Cost]: [Effect]"; the cost is
# everything before the colon and must be paid by the activating player.


@pytest.mark.cr("602.1a")
def test_602_1a_activation_cost_is_everything_before_the_colon():
    """The activation cost is everything before the colon — here two generic mana
    plus tapping the permanent (602.1a)."""
    cost = parse_activated_ability_cost("{2}, {T}: You gain 1 life.")

    assert cost.mana["generic"] == 2
    assert cost.requires_tap is True


@pytest.mark.cr("602.1a")
def test_602_1a_colored_mana_in_activation_cost_is_parsed():
    """Colored symbols in the cost are tracked individually (602.1a)."""
    cost = parse_activated_ability_cost("{R}{R}: This creature gets +1/+0 until end of turn.")

    assert cost.mana["R"] == 2
    assert cost.requires_tap is False


@pytest.mark.cr("602.1")
def test_602_1_ability_has_a_cost_and_an_effect():
    """A compiled activated ability carries both a cost and an effect
    instruction (602.1)."""
    pinger = _mk_card("Prodigal Sorcerer", "Creature — Wizard", "{T}: This creature deals 1 damage to any target.")

    program = compile_card_oracle(pinger)
    ability = program.activated_abilities[0]

    assert ability.cost.requires_tap is True
    assert ability.instruction is not None
    assert ability.instruction.kind == "deal_damage"


# 602.2 / 602.2a — activating an ability puts it on the stack as an object;
# only the object's controller may activate it.


@pytest.mark.cr("602.2a")
def test_602_2a_nonmana_ability_is_put_on_the_stack():
    """Activating a non-mana ability puts it on the stack as a new object
    (602.2a). queue defers resolution so the stack item is observable."""
    cannon = _mk_card("Cannon", "Artifact", "{T}: Cannon deals 1 damage to any target.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cannon)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.queue_permanent_ability(0, "Cannon", target_player_index=1)

    assert result.details == "queued"
    assert len(game.stack) == 1
    assert game.stack[0].ability_instruction is not None
    # The effect has not happened yet — the ability is still on the stack.
    assert p2.life == 20


@pytest.mark.cr("602.2a")
def test_602_2a_stack_ability_resolves_and_applies_its_effect():
    """When the ability on the stack resolves, its effect is applied (602.2a)."""
    cannon = _mk_card("Cannon", "Artifact", "{T}: Cannon deals 1 damage to any target.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cannon)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.queue_permanent_ability(0, "Cannon", target_player_index=1)
    game.resolve_top_of_stack()

    assert len(game.stack) == 0
    assert p2.life == 19


@pytest.mark.cr("602.2")
def test_602_2_only_the_controller_can_activate_the_ability():
    """Only the permanent's controller can activate its ability (602.2). The
    opponent cannot reach into the controller's battlefield to do so."""
    cannon = _mk_card("Cannon", "Artifact", "{T}: Cannon deals 1 damage to any target.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cannon)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    # Player 2 has no such permanent under their control.
    with pytest.raises(ValueError, match="Permanent not found"):
        game.activate_permanent_ability(1, "Cannon", target_player_index=0)


@pytest.mark.cr("602.1a", "602.2b")
def test_602_2_activating_an_ability_taps_the_permanent_for_its_cost():
    """Paying a {T} cost taps the permanent (602.1a/602.2b)."""
    cannon = _mk_card("Cannon", "Artifact", "{T}: Cannon deals 1 damage to any target.")
    perm = Permanent(card=cannon)
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Cannon", target_player_index=1)

    assert perm.tapped is True


# 602.2b — the cost (including a mana payment) must actually be paid.


@pytest.mark.cr("602.2b")
def test_602_2b_mana_cost_is_paid_from_the_pool():
    """Activating an ability deducts its mana cost from the controller's pool
    (602.2b — the activation-cost analog of a spell's mana payment)."""
    pinger = _mk_card("Pinger", "Artifact", "{2}, {T}: Pinger deals 1 damage to any target.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pinger)], mana_pool={"C": 3})
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.activate_permanent_ability(0, "Pinger", target_player_index=1)

    assert result.supported
    assert p1.mana_pool.get("C", 0) == 1  # paid 2 of 3
    assert p2.life == 19


@pytest.mark.cr("602.2b")
def test_602_2b_ability_is_illegal_without_enough_mana():
    """If the activation cost can't be paid, the activation is illegal and the
    game returns to before it began (602.2/602.2b) — no effect, no tap-only loss."""
    pinger = _mk_card("Pinger", "Artifact", "{2}, {T}: Pinger deals 1 damage to any target.")
    perm = Permanent(card=pinger)
    p1 = PlayerState(name="P1", battlefield=[perm], mana_pool={"C": 1})
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.activate_permanent_ability(0, "Pinger", target_player_index=1)

    assert not result.supported
    assert "insufficient mana" in result.details
    assert p2.life == 20
    assert len(game.stack) == 0


# 602.5 / 602.5a — a player can't begin to activate a prohibited ability; a
# creature's {T} ability needs control since the start of the most recent turn.


@pytest.mark.cr("602.5a")
def test_602_5a_summoning_sick_creature_cannot_use_a_tap_ability():
    """A creature that hasn't been controlled since the start of its controller's
    most recent turn can't activate an ability with {T} in its cost (602.5a)."""
    elf = _mk_card("Llanowar Elves", "Creature — Elf", "{T}: Add {G}.")
    perm = Permanent(card=elf)
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    p1.battlefield.append(perm)
    game._initialize_permanent_state(perm, 0, None)  # marks it summoning sick this turn

    result = game.activate_permanent_ability(0, "Llanowar Elves")

    assert not result.supported
    assert "summoning sickness" in result.details
    assert p1.mana_pool.get("G", 0) == 0


@pytest.mark.cr("602.5a", "702.10c")
def test_602_5a_haste_creature_ignores_summoning_sickness():
    """A creature with haste ignores 602.5a and may use its {T} ability the turn
    it enters (702.10)."""
    elf = _mk_card("Hasty Elf", "Creature — Elf", "{T}: Add {G}.", keywords=("Haste",))
    perm = Permanent(card=elf)
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    p1.battlefield.append(perm)
    game._initialize_permanent_state(perm, 0, None)

    result = game.activate_permanent_ability(0, "Hasty Elf")

    assert result.supported
    assert p1.mana_pool.get("G", 0) == 1


@pytest.mark.cr("602.5a")
def test_602_5a_creature_controlled_since_turn_start_can_tap():
    """Once a creature has been under its controller's control since the start of
    their most recent turn, its {T} ability is legal (602.5a)."""
    elf = _mk_card("Llanowar Elves", "Creature — Elf", "{T}: Add {G}.")
    perm = Permanent(card=elf)
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    p1.battlefield.append(perm)
    game._initialize_permanent_state(perm, 0, None)
    _not_summoning_sick(game, perm)

    result = game.activate_permanent_ability(0, "Llanowar Elves")

    assert result.supported
    assert p1.mana_pool.get("G", 0) == 1


@pytest.mark.cr("602.5")
def test_602_5_already_tapped_permanent_cannot_pay_a_tap_cost():
    """A permanent that's already tapped can't pay a {T} cost, so the ability
    can't be activated (602.5)."""
    elf = _mk_card("Llanowar Elves", "Creature — Elf", "{T}: Add {G}.")
    perm = Permanent(card=elf, tapped=True)
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    p1.battlefield.append(perm)
    game._initialize_permanent_state(perm, 0, None)
    _not_summoning_sick(game, perm)

    result = game.activate_permanent_ability(0, "Llanowar Elves")

    assert not result.supported
    assert "already tapped" in result.details


# 602.5d/e — activation instructions (e.g. timing restrictions) function at all
# times and prevent activation when their condition isn't met (602.1b).


@pytest.mark.cr("602.1b")
def test_602_1b_timing_restriction_blocks_activation_outside_its_window():
    """An "Activate only during your upkeep" instruction prevents activation
    during the main phase (602.1b — activation instructions function at all
    times)."""
    tome = _mk_card("Tome", "Artifact", "{T}: You gain 1 life. Activate only during your upkeep.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tome)], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    assert game.current_step == "precombat_main"  # not upkeep

    result = game.activate_permanent_ability(0, "Tome")

    assert not result.supported
    assert "upkeep" in result.details
    assert p1.life == 20


@pytest.mark.cr("602.1b")
def test_602_1b_timing_restriction_allows_activation_in_its_window():
    """The same ability is legal during the controller's upkeep (602.1b)."""
    tome = _mk_card("Tome", "Artifact", "{T}: You gain 1 life. Activate only during your upkeep.")
    perm = Permanent(card=tome)
    p1 = PlayerState(name="P1", battlefield=[perm], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.resolve_upkeep(0)  # advance to P1's upkeep

    result = game.activate_permanent_ability(0, "Tome")

    assert result.supported
    assert p1.life == 21  # "You gain 1 life" credits the controller


# ---------------------------------------------------------------------------
# Which of a card's abilities a caller that named none gets (602.5 / 107.5)
#
# `permanent.card.name == "Basalt Monolith"` stood in queue_permanent_ability,
# hand-picking between that card's {T} mana ability and its {3} untap ability by
# tapped state. It is not a card quirk: CR 107.5 says an already-tapped permanent
# can't be tapped again to pay {T}, so a card with both abilities has exactly one
# payable ability in each state and the choice follows from the rule. Pinned with
# an invented card, whose costs and mana differ from the Monolith's — the
# name-keyed version also matched on `cost.mana["generic"] == 3`.
# ---------------------------------------------------------------------------

_OBELISK_TEXT = (
    "This artifact doesn't untap during your untap step.\n"
    "{T}: Add {G}{G}.\n"
    "{2}: Untap this artifact."
)


@pytest.mark.cr("602.5", "107.5")
def test_602_5_default_ability_is_the_one_payable_in_the_current_state():
    """An invented card with a {T} ability and an untap ability cycles.

    Against the name-keyed version this card tapped for mana once and was then
    stuck tapped for good: its untap ability was unreachable, because the
    default was "first ability printed" and {T} can never be paid again.
    """
    obelisk = _mk_card("Granite Obelisk", "Artifact", _OBELISK_TEXT, mana_cost="{3}")
    perm = Permanent(card=obelisk)
    p1 = PlayerState(name="P1", battlefield=[perm])
    game = Game(players=[p1, PlayerState(name="P2")])

    assert game.activate_permanent_ability(0, "Granite Obelisk").supported
    assert perm.tapped is True and p1.mana_pool["G"] == 2

    assert game.activate_permanent_ability(0, "Granite Obelisk").supported
    assert perm.tapped is False

    assert game.activate_permanent_ability(0, "Granite Obelisk").supported
    assert perm.tapped is True and p1.mana_pool["G"] == 4


@pytest.mark.cr("107.5")
def test_107_5_a_lone_tap_ability_still_reports_why_it_cannot_be_paid():
    """Skipping unpayable abilities must not swallow the refusal.

    A permanent whose only ability costs {T} has nothing to fall through to, so
    it still reports "already tapped" rather than the vaguer "no implemented
    activated ability" an empty selection would produce.
    """
    tapper = _mk_card("Chill Rod", "Artifact", "{T}: Tap target creature.")
    perm = Permanent(card=tapper, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=_bear())])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0, "Chill Rod", target_player_index=1, target_permanent_index=0
    )

    assert result.supported is False
    assert "already tapped" in result.details


@pytest.mark.cr("602.5")
def test_602_5_an_explicit_ability_index_still_names_the_ability():
    """The state-aware default only applies when the caller named no ability;
    an explicit index is still honoured, so a UI offering both abilities of a
    multi-ability card keeps working."""
    obelisk = _mk_card("Granite Obelisk", "Artifact", _OBELISK_TEXT, mana_cost="{3}")
    perm = Permanent(card=obelisk)
    p1 = PlayerState(name="P1", battlefield=[perm])
    game = Game(players=[p1, PlayerState(name="P2")])

    # Index 1 is the untap ability; on an untapped permanent it is legal and
    # simply leaves it untapped (CR 107.6 has no bearing — {Q} is not its cost).
    assert game.activate_permanent_ability(0, "Granite Obelisk", ability_index=1).supported
    assert perm.tapped is False
    assert p1.mana_pool["G"] == 0


# ===========================================================================
# Rule 603 — Handling Triggered Abilities
# ===========================================================================


# 603.1 — triggered abilities are "[When/Whenever/At] [condition], [effect]."


@pytest.mark.cr("603.1")
def test_603_1_triggered_ability_has_a_condition_and_an_effect():
    """A compiled triggered ability splits into a trigger condition and an
    effect instruction (603.1)."""
    pain = _mk_card("Pain Source", "Enchantment", "At the beginning of each upkeep, Pain Source deals 1 damage to you.")

    program = compile_card_oracle(pain)
    trig = program.triggered_abilities[0]

    assert trig.condition.kind == "upkeep_each"
    assert trig.condition.trigger == "at"
    assert trig.instruction is not None
    assert trig.instruction.kind == "deal_damage"


# 603.2 / 603.2b — a matching event triggers the ability automatically; when a
# step begins, "at the beginning of" abilities trigger.


@pytest.mark.cr("603.2b")
def test_603_2b_upkeep_trigger_fires_when_the_step_begins():
    """An "at the beginning of each upkeep" ability triggers when the upkeep step
    begins (603.2b)."""
    pain = _mk_card("Pain Source", "Enchantment", "At the beginning of each upkeep, Pain Source deals 1 damage to you.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pain)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert p1.life == 19  # the active player took the upkeep damage
    assert p2.life == 20


@pytest.mark.cr("603.2")
def test_603_2_trigger_fires_on_each_players_upkeep():
    """"At the beginning of each upkeep" fires whenever any player's upkeep
    begins (603.2) — here on the second player's upkeep too."""
    pain = _mk_card("Pain Source", "Enchantment", "At the beginning of each upkeep, Pain Source deals 1 damage to you.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pain)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p2.life == 19
    assert p1.life == 20


@pytest.mark.cr("603.2")
def test_603_2_dies_trigger_fires_when_a_creature_dies():
    """A "whenever a creature dies" ability triggers automatically when a
    creature is put into a graveyard from the battlefield (603.2)."""
    soul_web = _mk_card(
        "Soul Web", "Artifact",
        "Whenever a creature dies, you may pay {2}. If you do, you gain 1 life.",
    )
    perm = Permanent(card=soul_web)
    bear = _bear()
    p1 = PlayerState(name="P1", battlefield=[perm], mana_pool={"C": 2}, life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    bear_perm = Permanent(card=bear)
    p1.battlefield.append(bear_perm)
    game._initialize_permanent_state(bear_perm, 0, None)

    game._permanent_to_graveyard(p1, bear_perm)
    p1.battlefield.remove(bear_perm)
    # The dies-trigger goes on the stack and raises its pay-prompt on resolution.
    game.resolve_stack()

    # The optional "you may pay" rider defers to a yes/no choice; accept it.
    assert game.pending_optional_pays
    game.confirm_optional_pay(0, "Soul Web", accept=True)
    assert p1.life == 21  # paid {2}, gained 1 life


# 603.5 — optional ("may") triggered abilities still trigger; the choice is made
# on resolution. Here the choice is gated on being able to pay the optional cost.


@pytest.mark.cr("603.5")
def test_603_5_optional_trigger_is_skipped_when_the_cost_cannot_be_paid():
    """An optional "you may pay {2}" rider does nothing if the controller can't
    pay — the trigger still happened, but the option isn't taken (603.5)."""
    soul_web = _mk_card(
        "Soul Web", "Artifact",
        "Whenever a creature dies, you may pay {2}. If you do, you gain 1 life.",
    )
    perm = Permanent(card=soul_web)
    bear = _bear()
    p1 = PlayerState(name="P1", battlefield=[perm], mana_pool={"C": 0}, life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    bear_perm = Permanent(card=bear)
    p1.battlefield.append(bear_perm)
    game._initialize_permanent_state(bear_perm, 0, None)

    game._permanent_to_graveyard(p1, bear_perm)
    p1.battlefield.remove(bear_perm)

    assert p1.life == 20  # could not pay {2}, so no life gained


# 603.4 — intervening "if" clause: the ability only does something if its
# condition is true. Howling Mine draws an extra card only "if this artifact is
# untapped" when the draw step begins.


@pytest.mark.cr("603.4")
def test_603_4_intervening_if_true_applies_the_effect(all_cards):
    """Howling Mine's intervening "if this artifact is untapped" is satisfied, so
    the active player draws an additional card on their draw step (603.4)."""
    mine = _get(all_cards, "Howling Mine")
    library = [_bear(f"Card {i}") for i in range(10)]
    perm = Permanent(card=mine, tapped=False)
    p1 = PlayerState(name="P1", battlefield=[perm], library=library)
    p2 = PlayerState(name="P2", library=[_bear(f"Other {i}") for i in range(10)])
    game = Game(players=[p1, p2])
    game._initialize_permanent_state(perm, 0, None)
    game.turn = 2  # an ordinary turn - turn 1 skips the draw (CR 103.8a)

    before = len(p1.hand)
    game.resolve_draw_step(0)

    assert len(p1.hand) - before == 2  # normal draw + Howling Mine's extra


@pytest.mark.cr("603.4")
def test_603_4_intervening_if_false_does_nothing(all_cards):
    """When Howling Mine is tapped the intervening "if" is false, so only the
    normal draw happens — the ability is removed and does nothing (603.4)."""
    mine = _get(all_cards, "Howling Mine")
    library = [_bear(f"Card {i}") for i in range(10)]
    perm = Permanent(card=mine, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[perm], library=library)
    p2 = PlayerState(name="P2", library=[_bear(f"Other {i}") for i in range(10)])
    game = Game(players=[p1, p2])
    game._initialize_permanent_state(perm, 0, None)
    game.turn = 2  # an ordinary turn - turn 1 skips the draw (CR 103.8a)

    before = len(p1.hand)
    game.resolve_draw_step(0)

    assert len(p1.hand) - before == 1  # normal draw only


# ===========================================================================
# Rule 604 — Handling Static Abilities
# ===========================================================================


# 604.1 / 604.2 — static abilities are always on and create a continuous effect
# that lasts as long as the permanent stays on the battlefield with the ability.


@pytest.mark.cr("604.1", "604.2")
def test_604_1_static_buff_applies_continuously_while_on_battlefield(all_cards):
    """Crusade ("White creatures get +1/+1") continuously buffs white creatures
    as long as it's on the battlefield (604.1/604.2)."""
    crusade = _get(all_cards, "Crusade")
    white_creature = next(
        c for c in all_cards if c.primary_type == "creature" and "W" in c.colors
    )
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    creature_perm = Permanent(card=white_creature)
    p1.battlefield.append(creature_perm)
    game._initialize_permanent_state(creature_perm, 0, None)
    game._recalculate_lord_buffs()
    base_power = creature_perm.effective_power

    crusade_perm = Permanent(card=crusade)
    p1.battlefield.append(crusade_perm)
    game._initialize_permanent_state(crusade_perm, 0, None)
    game._apply_global_buff(p1, crusade)
    game._recalculate_lord_buffs()

    assert creature_perm.effective_power == base_power + 1
    assert creature_perm.effective_toughness == base_power + 1


@pytest.mark.cr("604.2")
def test_604_2_static_buff_disappears_when_the_source_leaves(all_cards):
    """The continuous effect ends the moment Crusade leaves the battlefield —
    static abilities aren't locked in (604.2)."""
    crusade = _get(all_cards, "Crusade")
    white_creature = next(
        c for c in all_cards if c.primary_type == "creature" and "W" in c.colors
    )
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    creature_perm = Permanent(card=white_creature)
    p1.battlefield.append(creature_perm)
    game._initialize_permanent_state(creature_perm, 0, None)
    base_power = creature_perm.effective_power

    crusade_perm = Permanent(card=crusade)
    p1.battlefield.append(crusade_perm)
    game._initialize_permanent_state(crusade_perm, 0, None)
    game._apply_global_buff(p1, crusade)
    game._recalculate_lord_buffs()
    assert creature_perm.effective_power == base_power + 1

    p1.battlefield.remove(crusade_perm)
    game._recalculate_lord_buffs()

    assert creature_perm.effective_power == base_power


@pytest.mark.cr("604.1")
def test_604_2_static_buff_only_applies_to_matching_creatures(all_cards):
    """Crusade buffs only white creatures — a non-white creature is unaffected
    (604.1, the effect's own selection criteria)."""
    crusade = _get(all_cards, "Crusade")
    nonwhite = _mk_card("Black Bear", "Creature — Bear", colors=("B",), power="2", toughness="2")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    bear_perm = Permanent(card=nonwhite)
    p1.battlefield.append(bear_perm)
    game._initialize_permanent_state(bear_perm, 0, None)

    crusade_perm = Permanent(card=crusade)
    p1.battlefield.append(crusade_perm)
    game._initialize_permanent_state(crusade_perm, 0, None)
    game._apply_global_buff(p1, crusade)
    game._recalculate_lord_buffs()

    assert bear_perm.effective_power == 2
    assert bear_perm.effective_toughness == 2


# ===========================================================================
# Rule 605 — Mana Abilities
# ===========================================================================


# 605.1a — an activated ability that needs no target and could add mana is a
# mana ability.


@pytest.mark.cr("605.1a")
def test_605_1a_tap_for_mana_is_a_mana_ability():
    """"{T}: Add {G}." is compiled as a mana-producing ability (605.1a)."""
    elf = _mk_card("Llanowar Elves", "Creature — Elf", "{T}: Add {G}.")

    program = compile_card_oracle(elf)
    ability = program.activated_abilities[0]

    assert ability.instruction is not None
    assert ability.instruction.kind == "add_mana_from_text"
    assert ability.cost.requires_tap is True


@pytest.mark.cr("605.2")
def test_605_2_remains_a_mana_ability_even_if_it_cannot_produce_now():
    """A mana ability is still a mana ability even when the game state means it
    would produce nothing (605.2).

    605.2's own example offers two ways to be unable to produce — "{T}: Add {G}
    for each creature you control" while controlling none, *or* the permanent
    already being tapped. This uses the second, because the engine deliberately
    refuses the first: no handler scales mana by a board count, and
    ``_add_mana_from_text`` would add a single {G} and drop "for each creature
    you control" entirely. The rule's example text is therefore reported
    unsupported rather than compiled onto a handler that means something else —
    which is the only honest reading of a card the engine cannot run.
    """
    rock = _mk_card("Mana Rock", "Artifact", "{T}: Add {G}.")

    program = compile_card_oracle(rock)
    ability = program.activated_abilities[0]

    # Classified as a mana ability from the text alone. Nothing about the
    # board — the permanent may be tapped, as it is below — reaches this.
    assert ability.instruction is not None
    assert ability.instruction.kind == "add_mana_from_text"

    tapped = Permanent(card=rock, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[tapped])
    game = Game(players=[p1, PlayerState(name="P2")])
    _not_summoning_sick(game, tapped)

    # Already tapped, so it cannot produce now — and it is the same mana ability.
    assert compile_card_oracle(tapped.card).activated_abilities[0].instruction.kind == (
        "add_mana_from_text"
    )
    assert not game.activate_permanent_ability(0, "Mana Rock").supported


# 605.3b — a mana ability doesn't go on the stack; it resolves immediately.


@pytest.mark.cr("605.3b")
def test_605_3b_mana_ability_does_not_use_the_stack():
    """Activating a mana ability adds the mana immediately without ever placing
    an object on the stack (605.3b)."""
    elf = _mk_card("Llanowar Elves", "Creature — Elf", "{T}: Add {G}.")
    perm = Permanent(card=elf)
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    p1.battlefield.append(perm)
    game._initialize_permanent_state(perm, 0, None)
    _not_summoning_sick(game, perm)

    result = game.activate_permanent_ability(0, "Llanowar Elves")

    assert result.details == "resolved"  # resolved immediately, not "queued"
    assert len(game.stack) == 0
    assert p1.mana_pool.get("G", 0) == 1


@pytest.mark.cr("605.3", "602.1a")
def test_605_3b_mana_ability_taps_its_source():
    """The {T} part of a mana ability's cost still taps the source (605.3/602.1a)."""
    elf = _mk_card("Llanowar Elves", "Creature — Elf", "{T}: Add {G}.")
    perm = Permanent(card=elf)
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    p1.battlefield.append(perm)
    game._initialize_permanent_state(perm, 0, None)
    _not_summoning_sick(game, perm)

    game.activate_permanent_ability(0, "Llanowar Elves")

    assert perm.tapped is True


# 605.3c — once a player begins to activate a mana ability, it can't be
# activated again until it has resolved. With a {T} cost the source is now
# tapped, so a second activation can't pay the cost.


@pytest.mark.cr("605.3c")
def test_605_3c_mana_ability_cannot_be_activated_twice_without_untapping():
    """After a {T} mana ability resolves, the now-tapped source can't pay the tap
    cost again until it untaps (605.3c)."""
    elf = _mk_card("Llanowar Elves", "Creature — Elf", "{T}: Add {G}.")
    perm = Permanent(card=elf)
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    p1.battlefield.append(perm)
    game._initialize_permanent_state(perm, 0, None)
    _not_summoning_sick(game, perm)

    first = game.activate_permanent_ability(0, "Llanowar Elves")
    second = game.activate_permanent_ability(0, "Llanowar Elves")

    assert first.supported
    assert not second.supported
    assert p1.mana_pool.get("G", 0) == 1  # only one activation produced mana


# ===========================================================================
# Rule 606 — Loyalty Abilities
# ===========================================================================


@pytest.mark.cr("606.1", "606.2")
def test_606_lea_has_no_planeswalkers_or_loyalty_abilities(all_cards):
    """Loyalty abilities belong to planeswalkers (606.2). Limited Edition Alpha
    predates planeswalkers, so the set contains none — there are no loyalty
    abilities to activate in this engine's card pool (606.1)."""
    planeswalkers = [c for c in all_cards if "planeswalker" in c.type_line.lower()]
    loyalty_abilities = [c for c in all_cards if "loyalty" in c.type_line.lower()]

    assert planeswalkers == []
    assert loyalty_abilities == []


# ===========================================================================
# Rule 607 — Linked Abilities
# ===========================================================================


@pytest.mark.cr("607.1", "607.2c")
def test_607_linked_abilities_act_on_the_object_they_affected(all_cards):
    """Animate Dead's reanimation ability and its leaves-the-battlefield ability
    are linked: the second refers to the creature put onto the battlefield by the
    first (607.1/607.2c). The reanimated creature and the Aura attached to it both
    end up on the battlefield together."""
    animate_dead = _get(all_cards, "Animate Dead")
    bear = _bear("Reanimated Bear")
    p1 = PlayerState(name="P1", hand=[animate_dead], graveyard=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Animate Dead", target_player_index=0, target_permanent_index=0)

    assert result.supported
    battlefield_names = [perm.card.name for perm in p1.battlefield]
    assert "Reanimated Bear" in battlefield_names
    assert "Animate Dead" in battlefield_names
    # The creature was pulled out of the graveyard by the linked reanimation.
    assert all(card.name != "Reanimated Bear" for card in p1.graveyard)


@pytest.mark.cr("607.1", "607.2a")
def test_607_linked_exile_and_return_reference_the_same_card():
    """A pair of linked abilities — one exiling a card, one returning "the exiled
    card" — keeps the second referring to what the first acted on (607.1/607.2a).
    Modeled here at the parse level: the engine recognizes both halves of such a
    card without conflating them with unrelated abilities."""
    flicker = _mk_card(
        "Linked Flicker",
        "Artifact",
        "{T}: Exile target creature until end of turn.\n"
        "When this artifact leaves the battlefield, return the exiled card to the battlefield.",
    )

    program = compile_card_oracle(flicker)

    # The activated half (exile) and the triggered half (return) are both present
    # and recognized as distinct abilities on the same object.
    assert any(a.instruction is not None for a in program.activated_abilities)
    assert any(t.condition.kind == "leaves_battlefield" for t in program.triggered_abilities)


@pytest.mark.cr("603.6c", "603.10")
def test_603_6c_a_leaves_the_battlefield_ability_fires_from_the_removal_seam():
    """A leaves-the-battlefield ability triggers when a permanent moves from the
    battlefield to another zone — by *any* route.

    The condition parsed on both sides of the pipeline and had no fire site at
    all: a card compiled a real instruction under it, entered play, left, and
    nothing happened. It is announced from ``remove_from_battlefield``, the one
    transition out, so no destination can forget it — and the trigger is read
    while the permanent is still on a battlefield, which is what CR 603.10's
    last-known information amounts to here (its controller's seat).
    """
    ward = _mk_card(
        "Doomed Ward",
        "Enchantment",
        "When this enchantment leaves the battlefield, you lose the game.",
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ward)])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.active_player_index = 0
    game._sync_control()

    game.remove_from_battlefield(p1.battlefield[0])
    game._settle()

    assert p1.lost


@pytest.mark.cr("603.6c")
def test_603_6c_a_permanent_that_was_not_there_announces_nothing():
    """"Moves from the battlefield" is the event. Asking the seam to remove a
    permanent that is not on a battlefield removes nothing, so there is no
    zone change and nothing triggers — the check that keeps the fire site
    above from firing on last-known information alone."""
    ward = _mk_card(
        "Doomed Ward",
        "Enchantment",
        "When this enchantment leaves the battlefield, you lose the game.",
    )
    p1 = PlayerState(name="P1", battlefield=[])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.active_player_index = 0

    assert game.remove_from_battlefield(Permanent(card=ward)) is None
    game._settle()

    assert not p1.lost
