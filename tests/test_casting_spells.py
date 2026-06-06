"""Tests for Magic: The Gathering Comprehensive Rules Section 601 — Casting Spells."""

import pytest
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.game import StackItem


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
) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = "2"
        raw["toughness"] = "2"
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=cmc,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=produced_mana,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Rule 601.2a — Casting moves card to the stack
# ---------------------------------------------------------------------------


def test_601_2a_casting_moves_card_from_hand_to_stack():
    """Casting a spell moves it from the hand to the stack (601.2a)."""
    bolt = _mk_card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 0
    assert len(game.stack) == 1
    assert game.stack[0].card.name == "Lightning Bolt"


def test_601_2a_spell_becomes_topmost_object_on_stack():
    """Each newly cast spell becomes the topmost object on the stack (601.2a)."""
    spell1 = _mk_card("First Spell", "Instant", "First Spell deals 1 damage to any target.")
    spell2 = _mk_card("Second Spell", "Instant", "Second Spell deals 2 damage to any target.")
    p1 = PlayerState(name="P1", hand=[spell1, spell2])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "First Spell", target_player_index=1)
    game.queue_from_hand(0, "Second Spell", target_player_index=1)

    assert game.stack[-1].card.name == "Second Spell"
    assert game.stack[0].card.name == "First Spell"


def test_601_2a_spell_remains_on_stack_until_resolved():
    """A spell remains on the stack until it resolves or is countered (601.2a)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Bolt", target_player_index=1)
    assert len(game.stack) == 1

    game.resolve_top_of_stack()
    assert len(game.stack) == 0


def test_601_2a_caster_becomes_controller_of_spell():
    """The player who casts a spell becomes its controller on the stack (601.2a)."""
    spell = _mk_card("Spell", "Instant", "Spell deals 1 damage to any target.")
    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Spell", target_player_index=1)

    assert game.stack[0].caster_index == 0


def test_601_2a_second_player_caster_index_is_set():
    """When the second player casts a spell, they become its controller (601.2a)."""
    drain = _mk_card("Drain Life", "Sorcery", "Drain Life deals 2 damage to any target.")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", hand=[drain])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Drain Life", target_player_index=0)

    assert game.stack[0].caster_index == 1


# ---------------------------------------------------------------------------
# Rule 601.2b — Announcing choices: X values
# ---------------------------------------------------------------------------


def test_601_2b_x_value_stored_on_stack_item():
    """The announced X value is stored on the stack item at cast time (601.2b)."""
    fireball = _mk_card(
        "Fireball",
        "Sorcery",
        "Fireball deals X damage to any target.",
        mana_cost="{X}{R}",
        colors=("R",),
    )
    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Fireball", target_player_index=1, x_value=4)

    assert game.stack[-1].x_value == 4


def test_601_2b_x_value_zero_is_a_valid_announcement():
    """X can be announced as zero; the spell is still placed on the stack (601.2b)."""
    fireball = _mk_card(
        "Fireball",
        "Sorcery",
        "Fireball deals X damage to any target.",
        mana_cost="{X}{R}",
        colors=("R",),
    )
    p1 = PlayerState(name="P1", hand=[fireball])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Fireball", target_player_index=1, x_value=0)

    assert game.stack[-1].x_value == 0


def test_601_2b_x_value_inferred_from_available_mana():
    """If X is not given, the engine infers it from the player's available mana pool (601.2b).

    With mana_cost={X}{R} and 5R in the pool: 1R covers the {R} component,
    leaving 4 generic mana which becomes X.
    """
    fireball = _mk_card(
        "Fireball",
        "Sorcery",
        "Fireball deals X damage to any target.",
        mana_cost="{X}{R}",
        colors=("R",),
    )
    p1 = PlayerState(name="P1", hand=[fireball], mana_pool={"R": 5})
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Fireball", target_player_index=1)  # x_value intentionally omitted

    assert game.stack[-1].x_value == 4


# ---------------------------------------------------------------------------
# Rule 601.2c — Announcing targets
# ---------------------------------------------------------------------------


def test_601_2c_target_player_announced_and_stored():
    """The target player is announced at cast time and stored on the stack item (601.2c)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Bolt", target_player_index=1)

    assert game.stack[-1].target_player_index == 1


def test_601_2c_target_permanent_index_announced_and_stored():
    """The target permanent is announced at cast time and stored on the stack item (601.2c)."""
    tap_spell = _mk_card("Paralyze", "Instant", "Tap target creature.")
    creature = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[tap_spell])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Paralyze", target_player_index=1, target_permanent_index=0)

    assert game.stack[-1].target_player_index == 1
    assert game.stack[-1].target_permanent_index == 0


def test_601_2c_spell_can_target_its_own_controller():
    """A player may target themselves with a spell (601.2c)."""
    heal = _mk_card("Healing Salve", "Instant", "Target player gains 3 life.")
    p1 = PlayerState(name="P1", hand=[heal])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Healing Salve", target_player_index=0)

    assert p1.life == 23


# ---------------------------------------------------------------------------
# Rule 601.2d — Dividing effects among targets
# ---------------------------------------------------------------------------


def test_601_2d_divided_damage_each_target_receives_at_least_one():
    """When an effect is divided among targets, each target receives at least one (601.2d).

    Simulates a split-damage spell with two creature targets. Damage is divided
    equally so each target receives damage_marked > 0.
    """
    forked_bolt = _mk_card(
        "Forked Bolt",
        "Sorcery",
        "Forked Bolt deals 2 damage to any target.",
    )
    creature1 = _mk_card("Goblin A", "Creature — Goblin")
    creature2 = _mk_card("Goblin B", "Creature — Goblin")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=creature1), Permanent(card=creature2)],
    )
    game = Game(players=[p1, p2])

    # Directly place a multi-target stack item to represent the announced division (601.2d)
    game.stack.append(
        StackItem(
            card=forked_bolt,
            caster_index=0,
            target_player_index=1,
            target_permanent_index=[0, 1],
            x_value=2,
        )
    )
    game.resolve_top_of_stack()

    # Both targets should have received damage
    assert p2.battlefield[0].damage_marked > 0
    assert p2.battlefield[1].damage_marked > 0


def test_601_2d_total_damage_is_preserved_across_division():
    """The total damage dealt equals the spell's damage value when divided (601.2d).

    Two 2/2 creatures split 2 damage: each gets 1 (2 // 2 = 1).
    """
    bolt = _mk_card("Divide Bolt", "Sorcery", "Divide Bolt deals 2 damage to any target.")
    creature1 = _mk_card("Target A", "Creature — Bear")
    creature2 = _mk_card("Target B", "Creature — Bear")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=creature1), Permanent(card=creature2)],
    )
    game = Game(players=[p1, p2])

    game.stack.append(
        StackItem(
            card=bolt,
            caster_index=0,
            target_player_index=1,
            target_permanent_index=[0, 1],
            x_value=2,
        )
    )
    game.resolve_top_of_stack()

    total_damage = sum(p.damage_marked for p in p2.battlefield)
    assert total_damage == 2


# ---------------------------------------------------------------------------
# Rule 601.2e — Legality check after proposal
# ---------------------------------------------------------------------------


def test_601_2e_illegal_spell_card_stays_in_hand():
    """If the proposed spell is illegal, the game returns to the prior state — card stays in hand (601.2e)."""
    unsupported = _mk_card(
        "Unknown Effect",
        "Sorcery",
        "Perform a completely unsupported action with no implemented instruction.",
    )
    p1 = PlayerState(name="P1", hand=[unsupported])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Unknown Effect", target_player_index=1)

    assert not result.supported
    assert len(p1.hand) == 1
    assert len(game.stack) == 0


def test_601_2e_game_state_unchanged_when_spell_proposal_fails():
    """Life totals and battlefield are unaffected when an illegal spell fails (601.2e)."""
    unsupported = _mk_card(
        "Bad Spell",
        "Sorcery",
        "An unsupported mysterious happening that cannot be compiled.",
    )
    p1 = PlayerState(name="P1", hand=[unsupported])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Bad Spell", target_player_index=1)

    assert p2.life == 20


# ---------------------------------------------------------------------------
# Rule 601.2f — Determining total cost
# ---------------------------------------------------------------------------


def test_601_2f_base_cost_is_the_mana_cost():
    """The total cost of a spell is normally its printed mana cost (601.2f)."""
    bolt = _mk_card(
        "Red Bolt",
        "Instant",
        "Red Bolt deals 3 damage to any target.",
        mana_cost="{R}",
        colors=("R",),
        cmc=1.0,
    )
    p1 = PlayerState(name="P1", hand=[bolt], mana_pool={"R": 1})
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Red Bolt", target_player_index=1)

    assert result.supported
    assert p2.life == 17


def test_601_2f_gloom_increases_cost_of_white_spells():
    """Gloom adds {3} to the total cost of white spells (601.2f — additional cost effects)."""
    white_spell = _mk_card(
        "White Bolt",
        "Instant",
        "White Bolt deals 3 damage to any target.",
        mana_cost="{W}",
        colors=("W",),
        cmc=1.0,
    )
    gloom = _mk_card("Gloom", "Enchantment", "White spells cost {3} more to cast.")
    p1 = PlayerState(name="P1", hand=[white_spell], mana_pool={"W": 1})
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=gloom)])
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    # Only {W} available — not enough to cover {W} + 3 generic Gloom tax
    result = game.cast_from_hand(0, "White Bolt", target_player_index=1)

    assert not result.supported
    assert "insufficient mana" in result.details


def test_601_2f_gloom_cost_payable_with_sufficient_mana():
    """A white spell can be cast under Gloom when enough mana covers the extra {3} tax (601.2f)."""
    white_spell = _mk_card(
        "Radiant Bolt",
        "Instant",
        "Radiant Bolt deals 3 damage to any target.",
        mana_cost="{W}",
        colors=("W",),
        cmc=1.0,
    )
    gloom = _mk_card("Gloom", "Enchantment", "White spells cost {3} more to cast.")
    # Pool has {W}{W}{W}{W} — one W for the spell, three generic for Gloom
    p1 = PlayerState(name="P1", hand=[white_spell], mana_pool={"W": 4})
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=gloom)], life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Radiant Bolt", target_player_index=1)

    assert result.supported
    assert p2.life == 17


def test_601_2f_zero_mana_cost_spell_is_castable():
    """A spell with no mana cost (effectively {0}) can be cast without spending any mana (601.2f)."""
    free_spell = _mk_card(
        "Free Spell",
        "Instant",
        "Target player loses 1 life.",
        mana_cost="",
    )
    p1 = PlayerState(name="P1", hand=[free_spell])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Free Spell", target_player_index=1)

    assert result.supported
    assert p2.life == 19


# ---------------------------------------------------------------------------
# Rule 601.2g — Activating mana abilities before paying costs
# ---------------------------------------------------------------------------


def test_601_2g_mana_generated_before_casting_allows_spell_to_resolve():
    """Mana abilities activated before paying costs make a spell castable (601.2g).

    The player activates a mana ability (Sol Ring taps for {C}{C}) before casting
    a {1} spell. Costs must be available in the pool when casting begins.
    """
    sol_ring = _mk_card(
        "Sol Ring",
        "Artifact",
        "{T}: Add {C}{C}.",
        produced_mana=("C", "C"),
    )
    bolt = _mk_card(
        "Generic Bolt",
        "Instant",
        "Generic Bolt deals 3 damage to any target.",
        mana_cost="{1}",
        cmc=1.0,
    )
    p1 = PlayerState(
        name="P1",
        hand=[bolt],
        battlefield=[Permanent(card=sol_ring, tapped=False)],
    )
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    # 601.2g: Activate mana ability first, then pay spell cost
    game.activate_permanent_ability(0, "Sol Ring")
    result = game.cast_from_hand(0, "Generic Bolt", target_player_index=1)

    assert result.supported
    assert p2.life == 17


def test_601_2g_spell_fails_without_prior_mana_generation():
    """Without activating mana abilities first, a spell with a mana cost cannot be cast (601.2g)."""
    bolt = _mk_card(
        "Red Bolt",
        "Instant",
        "Red Bolt deals 3 damage to any target.",
        mana_cost="{R}",
        colors=("R",),
        cmc=1.0,
    )
    p1 = PlayerState(name="P1", hand=[bolt])  # no mana in pool
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Red Bolt", target_player_index=1)

    assert not result.supported
    assert p2.life == 20


# ---------------------------------------------------------------------------
# Rule 601.2h — Paying the total cost
# ---------------------------------------------------------------------------


def test_601_2h_mana_deducted_from_pool_when_spell_is_cast():
    """Paying the mana cost deducts mana from the player's pool (601.2h)."""
    bolt = _mk_card(
        "Bolt",
        "Instant",
        "Bolt deals 3 damage to any target.",
        mana_cost="{R}",
        colors=("R",),
        cmc=1.0,
    )
    p1 = PlayerState(name="P1", hand=[bolt], mana_pool={"R": 3})
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    game.cast_from_hand(0, "Bolt", target_player_index=1)

    assert p1.mana_pool.get("R", 0) == 2


def test_601_2h_insufficient_mana_prevents_casting():
    """If the player cannot pay the total cost, the spell cannot be cast (601.2h)."""
    bolt = _mk_card(
        "Bolt",
        "Instant",
        "Bolt deals 3 damage to any target.",
        mana_cost="{R}",
        colors=("R",),
        cmc=1.0,
    )
    p1 = PlayerState(name="P1", hand=[bolt], mana_pool={"R": 0})
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Bolt", target_player_index=1)

    assert not result.supported
    assert p2.life == 20
    assert len(p1.hand) == 1


def test_601_2h_partial_payment_not_allowed():
    """A player cannot partially pay a spell's cost — all mana must be available at once (601.2h)."""
    expensive = _mk_card(
        "Drain Life",
        "Sorcery",
        "Target player loses 3 life.",
        mana_cost="{2}{B}",
        colors=("B",),
        cmc=3.0,
    )
    # Only 1B available — not enough to pay {2}{B}
    p1 = PlayerState(name="P1", hand=[expensive], mana_pool={"B": 1})
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Drain Life", target_player_index=1)

    assert not result.supported
    assert p2.life == 20


def test_601_2h_cost_locked_in_before_payment():
    """The total cost is 'locked in' before payment is made (601.2h).

    Rule 601.2f states that cost is determined and then locked. Gloom's tax of {3}
    is included in the locked cost; paying exactly that locked amount succeeds.
    The player has W + 3 colorless — matching the Gloom-taxed cost of {W} + {3}.
    """
    white_spell = _mk_card(
        "White Healing",
        "Instant",
        "Target player gains 3 life.",
        mana_cost="{W}",
        colors=("W",),
        cmc=1.0,
    )
    gloom = _mk_card("Gloom", "Enchantment", "White spells cost {3} more to cast.")
    p1 = PlayerState(name="P1", hand=[white_spell], mana_pool={"W": 1, "C": 3})
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=gloom)])
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    # Exactly W + 3 generic meets the locked-in cost (base {W} + Gloom {3})
    result = game.cast_from_hand(0, "White Healing", target_player_index=0)

    assert result.supported


# ---------------------------------------------------------------------------
# Rule 601.2i — Spell becomes cast; triggered abilities fire; effect applies
# ---------------------------------------------------------------------------


def test_601_2i_spell_effect_applies_after_resolution():
    """After a spell is cast and resolves, its effect is applied (601.2i)."""
    shock = _mk_card("Shock", "Instant", "Shock deals 2 damage to any target.")
    p1 = PlayerState(name="P1", hand=[shock])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Shock", target_player_index=1)

    assert p2.life == 18


def test_601_2i_creature_spell_enters_battlefield_on_resolution():
    """A creature spell that resolves enters the battlefield under its caster's control (601.2i)."""
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Grizzly Bears", target_player_index=1)

    assert len(p1.battlefield) == 1
    assert p1.battlefield[0].card.name == "Grizzly Bears"


def test_601_2i_card_leaves_hand_as_soon_as_it_is_put_on_stack():
    """The spell leaves the hand when it moves to the stack, before it resolves (601.2i/601.2a)."""
    spell = _mk_card("Quick Bolt", "Instant", "Quick Bolt deals 1 damage to any target.")
    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Quick Bolt", target_player_index=1)

    assert len(p1.hand) == 0  # card left hand immediately (not after resolution)
    assert len(game.stack) == 1  # it's waiting on the stack


# ---------------------------------------------------------------------------
# Rule 601.3 — Legal casting requirements
# ---------------------------------------------------------------------------


def test_601_3_player_can_cast_a_supported_spell():
    """A player may cast a spell when no rule or effect prohibits it (601.3)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Bolt", target_player_index=1)

    assert result.supported
    assert p2.life == 17


def test_601_3_unsupported_card_cannot_be_cast():
    """A card with no recognised effect cannot be cast — no rule allows it (601.3)."""
    mystery = _mk_card(
        "Mystery Card",
        "Sorcery",
        "Completely unknown mechanic that no oracle parser understands at all.",
    )
    p1 = PlayerState(name="P1", hand=[mystery])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Mystery Card", target_player_index=1)

    assert not result.supported
    assert len(p1.hand) == 1


def test_601_3_card_not_in_hand_raises_error():
    """Attempting to cast a card the player doesn't hold raises an error (601.3)."""
    p1 = PlayerState(name="P1", hand=[])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    with pytest.raises(ValueError, match="Card not in hand"):
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)


# ---------------------------------------------------------------------------
# Rule 601.5 — Illegal spell after proposal returns game to prior state
# ---------------------------------------------------------------------------


def test_601_5_stack_is_empty_when_spell_proposal_fails():
    """If a spell cannot be cast, nothing is ever placed on the stack (601.5)."""
    unsupported = _mk_card(
        "Uncastable",
        "Sorcery",
        "Something impossible and unsupported by the oracle parser.",
    )
    p1 = PlayerState(name="P1", hand=[unsupported])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Uncastable", target_player_index=1)

    assert len(game.stack) == 0


def test_601_5_mana_not_spent_when_cast_fails_due_to_insufficient_mana():
    """Mana pool is unchanged when a cast fails due to insufficient mana (601.5)."""
    bolt = _mk_card(
        "Expensive Bolt",
        "Instant",
        "Expensive Bolt deals 3 damage to any target.",
        mana_cost="{3}{R}",
        colors=("R",),
        cmc=4.0,
    )
    p1 = PlayerState(name="P1", hand=[bolt], mana_pool={"R": 1})
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    game.cast_from_hand(0, "Expensive Bolt", target_player_index=1)

    # Mana pool is unchanged — the partial mana was never consumed
    assert p1.mana_pool.get("R", 0) == 1


# ---------------------------------------------------------------------------
# Rule 601.7 — Altering costs does not retroactively affect spells on the stack
# ---------------------------------------------------------------------------


def test_601_7_new_cost_modifier_does_not_affect_already_queued_spell():
    """An effect that alters costs has no impact on spells already on the stack (601.7).

    A white spell is queued while no cost modifier is in play — its cost was
    already determined at that point. Gloom entering the battlefield afterward
    does not retroactively change the queued spell's resolution.
    """
    white_bolt = _mk_card(
        "White Bolt",
        "Instant",
        "White Bolt deals 3 damage to any target.",
        colors=("W",),
    )
    gloom = _mk_card("Gloom", "Enchantment", "White spells cost {3} more to cast.")
    p1 = PlayerState(name="P1", hand=[white_bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    # Spell cost is determined and locked in here — no Gloom present yet
    game.queue_from_hand(0, "White Bolt", target_player_index=1)

    # Gloom enters after the spell is already on the stack
    p2.battlefield.append(Permanent(card=gloom))

    # The already-queued spell resolves normally; its locked-in cost is unaffected
    game.resolve_top_of_stack()

    assert p2.life == 17
