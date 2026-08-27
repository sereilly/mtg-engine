"""Tests for Magic: The Gathering Comprehensive Rules Section 601 — Casting Spells."""

import pytest
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.game import StackItem
from engine.oracle import compile_card_oracle


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


@pytest.mark.cr("601.2a")
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


@pytest.mark.cr("601.2a")
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


@pytest.mark.cr("601.2a")
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


@pytest.mark.cr("601.2a")
def test_601_2a_caster_becomes_controller_of_spell():
    """The player who casts a spell becomes its controller on the stack (601.2a)."""
    spell = _mk_card("Spell", "Instant", "Spell deals 1 damage to any target.")
    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Spell", target_player_index=1)

    assert game.stack[0].caster_index == 0


@pytest.mark.cr("601.2a")
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


@pytest.mark.cr("601.2b")
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


@pytest.mark.cr("601.2b")
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


@pytest.mark.cr("601.2b")
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


@pytest.mark.cr("601.2c")
def test_601_2c_target_player_announced_and_stored():
    """The target player is announced at cast time and stored on the stack item (601.2c)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Bolt", target_player_index=1)

    assert game.stack[-1].target_player_index == 1


@pytest.mark.cr("601.2c")
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


@pytest.mark.cr("601.2c")
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


@pytest.mark.cr("601.2d")
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


@pytest.mark.cr("601.2d")
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


@pytest.mark.cr("601.2e", "601.5")
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


@pytest.mark.cr("601.2e", "601.5")
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


@pytest.mark.cr("601.2f")
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


@pytest.mark.cr("601.2f")
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


@pytest.mark.cr("601.2f")
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


@pytest.mark.cr("601.2f", "118.5")
def test_601_2f_zero_mana_cost_spell_is_castable():
    """A spell whose mana cost is {0} can be cast without spending any mana
    (601.2f / 118.5). A spell with NO mana cost is different — that cost is
    unpayable and the cast is illegal (CR 118.6, tested in
    test_targets_and_costs.py)."""
    free_spell = _mk_card(
        "Free Spell",
        "Instant",
        "Target player loses 1 life.",
        mana_cost="{0}",
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


@pytest.mark.cr("601.2g")
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


@pytest.mark.cr("601.2g")
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


@pytest.mark.cr("601.2h")
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


@pytest.mark.cr("601.2h")
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


@pytest.mark.cr("601.2h")
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


@pytest.mark.cr("601.2f", "601.2h")
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


@pytest.mark.cr("601.2i")
def test_601_2i_spell_effect_applies_after_resolution():
    """After a spell is cast and resolves, its effect is applied (601.2i)."""
    shock = _mk_card("Shock", "Instant", "Shock deals 2 damage to any target.")
    p1 = PlayerState(name="P1", hand=[shock])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Shock", target_player_index=1)

    assert p2.life == 18


@pytest.mark.cr("601.2i")
def test_601_2i_creature_spell_enters_battlefield_on_resolution():
    """A creature spell that resolves enters the battlefield under its caster's control (601.2i)."""
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Grizzly Bears", target_player_index=1)

    assert len(p1.battlefield) == 1
    assert p1.battlefield[0].card.name == "Grizzly Bears"


@pytest.mark.cr("601.2a", "601.2i")
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


@pytest.mark.cr("601.3")
def test_601_3_player_can_cast_a_supported_spell():
    """A player may cast a spell when no rule or effect prohibits it (601.3)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Bolt", target_player_index=1)

    assert result.supported
    assert p2.life == 17


@pytest.mark.cr("601.3")
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


@pytest.mark.cr("601.3")
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


@pytest.mark.cr("601.5")
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


@pytest.mark.cr("601.5")
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


@pytest.mark.cr("601.7")
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


# ---------------------------------------------------------------------------
# Rule 700.2 — Modal spells
# ---------------------------------------------------------------------------
#
# A mode is announced while the spell is being cast (601.2b), so these sit with
# the rest of casting's announcements rather than in a file of their own. What
# they pin is the *reading* of the head line: how many modes it asks for, and
# whether there is a mode list at all.


@pytest.mark.cr("700.2", "700.2a", "601.2b")
def test_700_2a_the_mode_announced_at_cast_is_the_one_that_resolves():
    """The controller chooses the mode as part of casting, and the spell then
    does only that mode (700.2a, 601.2b) — not the first one printed."""
    blast = _mk_card(
        "Elemental Blast Test",
        "Instant",
        "Choose one —\n• Target player gains 3 life.\n• Target player loses 2 life.",
    )
    p1 = PlayerState(name="P1", hand=[blast])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Elemental Blast Test", target_player_index=1, mode_index=1)
    assert game.stack[-1].chosen_mode_index == 1

    game.resolve_top_of_stack()

    assert p2.life == 18


@pytest.mark.cr("700.2")
def test_700_2_a_single_bulleted_option_is_not_a_modal_spell():
    """700.2 defines a modal spell as having "two or more options in a bulleted
    list". With one option there is no choice to announce, so the card carries
    no modes for a player to pick between."""
    single = _mk_card(
        "Single Option Test", "Instant", "Choose one —\n• Target player gains 3 life."
    )

    assert compile_card_oracle(single).modes == ()


@pytest.mark.cr("700.2")
def test_700_2_a_head_choosing_a_fixed_several_is_not_reduced_to_one():
    """"Choose two -" asks for a number of modes the engine cannot announce or
    resolve, and reading it as plain "choose one" would make the card a strictly
    weaker spell that still reported itself as working.

    "Choose one **or more**" was this test's example until the stack learned to
    carry a list of chosen modes, and is read now (Sublime Epiphany). An exact
    count above one is not: nothing in the pool prints one, so the bound would
    ship unexercised, and a wrong bound is a spell performing a mode nobody
    chose. The rule the test states has not moved - the head's number is either
    understood or the card is refused.
    """
    several = _mk_card(
        "Several Modes Test",
        "Instant",
        "Choose two —\n• Target player gains 3 life.\n• Target player loses 2 life.",
    )
    program = compile_card_oracle(several)

    assert program.modes == ()
    assert program.supported is False


@pytest.mark.cr("700.2d")
def test_700_2d_a_head_choosing_one_or_more_may_take_several_modes():
    """700.2d: "some spells ... instruct a player to choose one or more". The
    modes are read, the program records that more than one may be taken, and
    the cast path performs every one chosen — in **printed** order
    (CR 608.2c), whatever order they were named in.

    The refusal above and this pair on the same card shape: what separates them
    is the printed count, which is the whole thing being read.
    """
    card = _mk_card(
        "Several Modes Test",
        "Instant",
        "Choose one or more —\n• Target player gains 3 life.\n• Target player loses 2 life.",
    )
    p1 = PlayerState(name="P1", hand=[card], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    program = compile_card_oracle(card)
    assert program.modes_at_least is True

    # Named in the *reverse* printed order, so the order the effects happen in
    # is the card's and not the caller's.
    result = game.cast_from_hand(
        0, "Several Modes Test",
        mode_choices=[
            {"index": 1, "target_player_index": 1},
            {"index": 0, "target_player_index": 0},
        ],
    )

    assert result.supported, result.details
    assert (p1.life, p2.life) == (23, 18)


@pytest.mark.cr("601.2c")
def test_601_2c_a_variable_number_of_targets_may_be_announced_as_none():
    """"If the spell has a variable number of targets, the player announces how
    many targets they will choose." Zero is one of the answers, so a spell whose
    only targeting is "up to N" is castable with nothing legal to name — where a
    spell requiring its one target could not be cast at all (CR 115.1b)."""
    dredge = _mk_card(
        "Dredge Up",
        "Sorcery",
        "Return up to two target creature cards from your graveyard to your hand.",
    )
    p1 = PlayerState(name="P1", hand=[dredge])
    game = Game(players=[p1, PlayerState(name="P2")])

    result = game.cast_from_hand(0, "Dredge Up", target_player_index=0)

    assert result.supported, result.details
    assert p1.hand == []
    assert [c.name for c in p1.graveyard] == ["Dredge Up"]


@pytest.mark.cr("601.2c")
def test_601_2c_one_instance_of_target_cannot_name_the_same_object_twice():
    """"The same target can't be chosen multiple times for any one instance of
    the word 'target'." Two slots naming one object are one choice, so the
    effect happens once — not twice, and not to a second object nobody named."""
    dredge = _mk_card(
        "Dredge Up",
        "Sorcery",
        "Return up to two target creature cards from your graveyard to your hand.",
    )
    bear = _mk_card("Bear", "Creature — Bear")
    ogre = _mk_card("Ogre", "Creature — Ogre")
    p1 = PlayerState(name="P1", hand=[dredge], graveyard=[bear, ogre])
    game = Game(players=[p1, PlayerState(name="P2")])

    result = game.cast_from_hand(
        0, "Dredge Up", target_player_index=0, target_permanent_index=[0, 0],
    )

    assert result.supported, result.details
    assert [c.name for c in p1.hand] == ["Bear"]
    assert [c.name for c in p1.graveyard] == ["Ogre", "Dredge Up"]


@pytest.mark.cr("601.2c", "115.2")
def test_601_2c_each_announced_slot_names_its_own_object():
    """A spell naming several targets affects each of them once. The objects
    here are *cards in a graveyard*, which CR 115.2 admits because the spell
    says where to look — and which have no battlefield identity, so what a slot
    means has to be settled before any of them moves."""
    dredge = _mk_card(
        "Dredge Up",
        "Sorcery",
        "Return up to two target creature cards from your graveyard to your hand.",
    )
    first = _mk_card("First Bear", "Creature — Bear")
    second = _mk_card("Second Bear", "Creature — Bear")
    third = _mk_card("Third Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[dredge], graveyard=[first, second, third])
    game = Game(players=[p1, PlayerState(name="P2")])

    result = game.cast_from_hand(
        0, "Dredge Up", target_player_index=0, target_permanent_index=[0, 1],
    )

    assert result.supported, result.details
    assert sorted(c.name for c in p1.hand) == ["First Bear", "Second Bear"]
    assert [c.name for c in p1.graveyard] == ["Third Bear", "Dredge Up"]


# ---------------------------------------------------------------------------
# CR 700.2d / 608.2c - a spell that takes several of its modes
# ---------------------------------------------------------------------------

_TWO_MODES = "• Target player gains 3 life.\n• Target player loses 2 life."


def _modal_pair(head: str):
    """A two-mode instant with *head* above its bullets, and a duel to cast it."""
    card = _mk_card("Modal Probe", "Instant", head + "\n" + _TWO_MODES)
    p1 = PlayerState(name="P1", hand=[card, card], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


@pytest.mark.cr("601.2b", "700.2d")
def test_601_2b_a_choose_one_head_refuses_a_second_mode():
    """"Choose one —" is a bound, and the cast path enforces it. Without this a
    caller could hand any modal spell every bullet it prints, which is the same
    spell only strictly better.

    Paired with the head below, so what the pair reads is the printed count and
    not the number of modes offered.
    """
    game, p1, p2 = _modal_pair("Choose one —")

    result = game.cast_from_hand(
        0, "Modal Probe",
        mode_choices=[
            {"index": 0, "target_player_index": 0},
            {"index": 1, "target_player_index": 1},
        ],
    )

    assert not result.supported
    assert "chooses one mode" in result.details
    assert (p1.life, p2.life) == (20, 20), "refused before anything happened"


@pytest.mark.cr("700.2d")
def test_700_2d_a_choose_one_or_more_head_takes_both():
    """The same two modes under the head that allows them."""
    game, p1, p2 = _modal_pair("Choose one or more —")

    result = game.cast_from_hand(
        0, "Modal Probe",
        mode_choices=[
            {"index": 0, "target_player_index": 0},
            {"index": 1, "target_player_index": 1},
        ],
    )

    assert result.supported, result.details
    assert (p1.life, p2.life) == (23, 18)


@pytest.mark.cr("700.2d")
def test_700_2d_the_same_mode_cannot_be_chosen_twice():
    """700.2d: the same mode may be chosen again only if the card says so, and
    nothing in this pool does. Refused rather than deduplicated - a caller
    asking for a mode twice is asking for something the card does not offer, and
    silently giving them one is the wrong half of the answer."""
    game, p1, p2 = _modal_pair("Choose one or more —")

    result = game.cast_from_hand(
        0, "Modal Probe",
        mode_choices=[
            {"index": 0, "target_player_index": 0},
            {"index": 0, "target_player_index": 0},
        ],
    )

    assert not result.supported
    assert "chosen twice" in result.details
    assert p1.life == 20


@pytest.mark.cr("608.2c")
def test_608_2c_chosen_modes_resolve_in_printed_order():
    """608.2c: a modal spell's chosen modes resolve in the order written on the
    card, not the order the caster named them.

    Both modes point at the same player, so the *order* is what the life total
    and the log record; a test asserting only that both happened would pass
    either way round.
    """
    game, p1, p2 = _modal_pair("Choose one or more —")

    result = game.cast_from_hand(
        0, "Modal Probe",
        mode_choices=[
            {"index": 1, "target_player_index": 0},
            {"index": 0, "target_player_index": 0},
        ],
    )

    assert result.supported, result.details
    assert p1.life == 21
    # Gained first, then lost - which is what the card prints, where the caster
    # named them the other way round.
    gained = next(i for i, line in enumerate(game.log) if "gained 3 life" in line)
    lost = next(i for i, line in enumerate(game.log) if "lost 2 life" in line)
    assert gained < lost


# ---------------------------------------------------------------------------
# Round 31 — the target gate reads whichever way a target was addressed
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2c", "702.16b")
def test_r31_protection_is_enforced_when_the_target_is_named_by_id(catalog_by_name):
    """A target named by stable id gets the same CR 702.16b check as a slot.

    ``_validate_cast_targets`` read the battlefield **slot** and nothing else,
    so a caller that addressed its target the way this codebase asks for — by
    ``Permanent.permanent_id``, because an index renumbers under anything that
    leaves the battlefield — was not checked at all. Drain Life could be cast at
    a White Knight with protection from black; the spell went on the stack and
    resolved, and only the damage step declined to hurt it.

    Both spellings are asserted together on purpose. The bug was not that either
    check was wrong, it was that two ways of naming one target disagreed, and a
    test of one spelling alone is what let them.
    """
    knight = Permanent(card=catalog_by_name["White Knight"])
    p1 = PlayerState(name="P1", hand=[catalog_by_name["Drain Life"]])
    p2 = PlayerState(name="P2", battlefield=[knight])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "main"
    game.current_step = "precombat_main"

    drain = catalog_by_name["Drain Life"]
    by_slot = game._validate_cast_targets(
        drain, 0, target_player_index=1, target_permanent_index=0,
    )
    by_id = game._validate_cast_targets(
        drain, 0, target_player_index=1,
        target_permanent_ids=[knight.permanent_id],
    )
    assert by_id[0] is False, by_id
    assert "White Knight" in by_id[1]
    assert by_slot[0] is False

    result = game.cast_from_hand(
        0, "Drain Life", target_player_index=1, x_value=2,
        target_permanent_ids=[knight.permanent_id],
    )
    assert not result.supported, result.details
    assert "White Knight" in result.details


# ---------------------------------------------------------------------------
# CR 601.2c with several targets of *different kinds* (round 34).
# ---------------------------------------------------------------------------


def _r34_wall(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Wall",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Wall",
             "power": "0", "toughness": "6"},
    )


@pytest.mark.cr("601.2c")
def test_r34_the_same_object_cannot_fill_two_target_roles(set_pool):
    """"The same target can't be chosen multiple times for any one instance of
    the word 'target'" — and a spell whose roles are both creatures could
    otherwise name one permanent twice.

    A Wall that blocked *itself* is impossible, so the rule is asserted through
    the enumeration rather than through a board that happens to make it moot:
    the second role's offered list must not contain the permanent the first
    role already took.
    """
    wall = Permanent(card=_r34_wall("Wall A"))
    p1 = PlayerState(name="P1", battlefield=[])
    p2 = PlayerState(name="P2", battlefield=[wall],
                     hand=[set_pool("LEG")["Glyph of Delusion"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    # The Wall blocked *itself* according to the record — an impossible board,
    # written by hand precisely so the only thing standing between the caster
    # and naming one permanent twice is CR 601.2c.
    wall.metadata["blocked_attacker_ids_this_turn"] = [wall.permanent_id]

    spec = game.cast_target_spec(1, game.players[1].hand[0])
    assert spec["kind"] == "roles"
    assert spec["valid_targets"] == []

    result = game.cast_from_hand(
        1, "Glyph of Delusion",
        target_permanent_ids=[wall.permanent_id, wall.permanent_id],
    )
    assert result.supported is False
    assert "no valid target" in result.details


@pytest.mark.cr("601.2c")
def test_601_2c_a_named_target_the_spell_cannot_describe_is_refused(set_pool):
    """"The player announces their choice of an appropriate object or player
    for each target." A creature is not an appropriate object for "target
    artifact", so the spell is uncastable at it — not cast, resolved, and
    quietly half-applied.

    ``_validate_cast_targets`` checks the target of the instruction kinds it
    has an arm for, and Divine Offering's primary instruction is the
    ``sequence`` wrapping its two sentences, so it reached none of them. The
    gate beside it (``legality.cast_target_refusal``) asks the same enumeration
    the picker is built from, which is why the browser could never reach this
    and a test or the AI could.
    """
    bears = Permanent(card=set_pool("LEG")["Aisling Leprechaun"])
    p1 = PlayerState(
        name="P1", hand=[set_pool("LEG")["Divine Offering"]], life=20,
        battlefield=[bears],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(
        0, "Divine Offering", target_player_index=0, target_permanent_index=0
    )

    assert not result.supported
    assert "no valid target" in result.details
    # Nothing was paid and nothing happened: the card is still in hand and the
    # life the second sentence would have gained was never gained.
    assert [card.name for card in p1.hand] == ["Divine Offering"]
    assert p1.life == 20
    assert game.stack == []
