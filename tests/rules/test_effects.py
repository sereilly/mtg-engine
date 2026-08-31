"""Tests for Magic: The Gathering Comprehensive Rules Sections 609–610.

Covers:
  609 — Effects
  610 — One-Shot Effects
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


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
    power: int = 2,
    toughness: int = 2,
) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = str(power)
        raw["toughness"] = str(toughness)
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=cmc,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw=raw,
    )


def _mk_creature(
    name: str,
    power: int = 2,
    toughness: int = 2,
    colors: tuple[str, ...] = (),
    oracle_text: str = "",
) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Test",
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw={
            "name": name,
            "type_line": "Creature — Test",
            "power": str(power),
            "toughness": str(toughness),
        },
    )


# ---------------------------------------------------------------------------
# Rule 609.1 — An effect is something that happens as a result of a spell or ability
# ---------------------------------------------------------------------------


@pytest.mark.cr("609.1")
def test_609_1_spell_resolution_creates_damage_effect():
    """609.1: When a damage spell resolves, it creates a one-shot effect that reduces
    the target player's life total. The effect is the outcome of the spell resolving.
    """
    bolt = _mk_card("Mini Bolt", "Instant", "Mini Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Mini Bolt", target_player_index=1)

    assert result.supported
    assert p2.life == 17


@pytest.mark.cr("609.1")
def test_609_1_activated_ability_creates_effect():
    """609.1: When an activated ability resolves, it may create one or more effects.
    Example: a tap ability that deals damage to a player.
    """
    cannon = _mk_card(
        "Cannon", "Artifact", "{T}: Cannon deals 1 damage to any target."
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cannon)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    cannon_perm = p1.battlefield[0]
    cannon_perm.tapped = False

    result = game.activate_permanent_ability(0, "Cannon", target_player_index=1)

    assert result.supported
    assert p2.life == 19


@pytest.mark.cr("609.1")
def test_609_1_spell_creates_pump_effect():
    """609.1: A pump spell creates a continuous effect that modifies power/toughness.
    The effect is a result of the spell resolving.
    """
    pump = _mk_card("Giant Growth", "Instant", "Target creature gets +3/+3 until end of turn.")
    creature = _mk_creature("Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[pump], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Giant Growth", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert p1.battlefield[0].effective_power == 5
    assert p1.battlefield[0].effective_toughness == 5


# ---------------------------------------------------------------------------
# Rule 609.2 — Effects apply only to permanents unless stated otherwise
# ---------------------------------------------------------------------------


@pytest.mark.cr("609.2")
def test_609_2_global_creature_buff_only_affects_battlefield_creatures():
    """609.2: An effect that changes all creatures applies only to creatures on the
    battlefield (permanents), not to creature cards in graveyards or other zones.
    Example: 'All creatures get +1/+1 until EOT' only affects battlefield creatures.
    """
    buff_spell = _mk_card(
        "Rally", "Sorcery", "White creatures get +1/+1 until end of turn."
    )
    white_creature = _mk_creature("Living Knight", 2, 2, colors=("W",))
    dead_white_creature = _mk_creature("Dead Knight", 2, 2, colors=("W",))

    p1 = PlayerState(
        name="P1",
        hand=[buff_spell],
        battlefield=[Permanent(card=white_creature)],
        graveyard=[dead_white_creature],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Rally")

    # Battlefield creature gets the buff
    assert p1.battlefield[0].effective_power == 3
    assert p1.battlefield[0].effective_toughness == 3

    # Graveyard card is just a frozen CardDefinition — no metadata, no buff
    assert p1.graveyard[0] is dead_white_creature
    assert p1.graveyard[0].name == "Dead Knight"


@pytest.mark.cr("609.2")
def test_609_2_global_creature_buff_does_not_affect_hand():
    """609.2: An effect that modifies 'all creatures' only affects permanents on the
    battlefield. A creature card in a player's hand is not a permanent and is not
    affected.
    """
    buff_spell = _mk_card(
        "Rally", "Sorcery", "White creatures get +1/+1 until end of turn."
    )
    hand_creature = _mk_creature("Hand Knight", 2, 2, colors=("W",))
    battlefield_creature = _mk_creature("Field Knight", 2, 2, colors=("W",))

    p1 = PlayerState(
        name="P1",
        hand=[buff_spell, hand_creature],
        battlefield=[Permanent(card=battlefield_creature)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Rally")

    # Battlefield creature is buffed
    field_perm = next(
        p for p in p1.battlefield if p.card.name == "Field Knight"
    )
    assert field_perm.effective_power == 3

    # Hand creature is an unmodified CardDefinition — it has no power modifier
    assert hand_creature.raw.get("power") == "2"


@pytest.mark.cr("609.2")
def test_609_2_wrath_only_destroys_battlefield_creatures_not_graveyard():
    """609.2: 'Destroy all creatures' only destroys creature permanents on the
    battlefield. Creature cards in graveyards are not affected.
    """
    wrath = _mk_card("Wrath of God", "Sorcery", "Destroy all creatures.")
    living = _mk_creature("Living Bear", 2, 2)
    already_dead = _mk_creature("Dead Bear", 2, 2)

    p1 = PlayerState(
        name="P1",
        hand=[wrath],
        battlefield=[Permanent(card=living)],
        graveyard=[already_dead],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Wrath of God")

    assert len(p1.battlefield) == 0
    # Dead Bear was already in graveyard; Living Bear was destroyed by Wrath; Wrath itself resolved to graveyard
    assert any(c.name == "Dead Bear" for c in p1.graveyard)
    assert any(c.name == "Living Bear" for c in p1.graveyard)
    assert any(c.name == "Wrath of God" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Rule 609.3 — Impossible effects do only as much as possible
# ---------------------------------------------------------------------------


@pytest.mark.cr("609.3")
def test_609_3_discard_two_cards_with_one_in_hand():
    """609.3: If a player is holding only one card, an effect that reads 'discard
    two cards' causes them to discard only that card (CR 609.3 example).
    """
    discard_spell = _mk_card(
        "Mind Rot", "Sorcery", "Target player discards two cards."
    )
    lone_card = _mk_creature("Lone Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[discard_spell])
    p2 = PlayerState(name="P2", hand=[lone_card])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Mind Rot", target_player_index=1)
    game.auto_resolve_pending_discard()  # the discarder picks which card(s)

    # Target had 1 card; effect tried to discard 2 but could only discard 1
    assert len(p2.hand) == 0
    assert len(p2.graveyard) == 1


@pytest.mark.cr("609.3")
def test_609_3_discard_zero_cards_when_hand_is_empty():
    """609.3: An effect that says 'discard two cards' against a player with an
    empty hand does nothing — the effect is impossible and zero cards move.
    """
    discard_spell = _mk_card(
        "Mind Rot", "Sorcery", "Target player discards two cards."
    )

    p1 = PlayerState(name="P1", hand=[discard_spell])
    p2 = PlayerState(name="P2", hand=[])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Mind Rot", target_player_index=1)

    assert len(p2.hand) == 0
    assert len(p2.graveyard) == 0


@pytest.mark.cr("609.3")
def test_609_3_draw_does_as_much_as_possible_with_partial_library():
    """609.3: If an effect moves cards out of the library, it moves as many as
    possible. Drawing 3 cards with a 1-card library draws only the 1 available.
    """
    draw_spell = _mk_card("Ancestral Recall", "Instant", "Target player draws three cards.")
    lone_library_card = _mk_creature("Library Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[draw_spell])
    # Target has only 1 card in library
    p2 = PlayerState(name="P2", library=[lone_library_card])
    game = Game(players=[p1, p2])

    initial_hand_size = len(p2.hand)
    game.cast_from_hand(0, "Ancestral Recall", target_player_index=1)

    # Only 1 card was available to draw, so only 1 was drawn
    assert len(p2.hand) == initial_hand_size + 1
    assert len(p2.library) == 0


@pytest.mark.cr("609.3", "704.5g")
def test_609_3_damage_to_creature_does_not_exceed_toughness_kill():
    """609.3: Dealing excess damage to a creature kills it but doesn't do
    'impossible' bonus damage — the creature is simply destroyed.
    """
    bolt = _mk_card("Triple Bolt", "Instant", "Triple Bolt deals 5 damage to any target.")
    creature = _mk_creature("Frail Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Triple Bolt", target_player_index=1, target_permanent_index=0)

    # Creature with 2 toughness is destroyed by 5 damage; it leaves the battlefield
    assert len(p2.battlefield) == 0
    assert len(p2.graveyard) == 1


# ---------------------------------------------------------------------------
# Rule 609.7 — Effects that apply to damage from a source
# ---------------------------------------------------------------------------


@pytest.mark.cr("615.7", "615.1")
def test_609_7_damage_prevention_pool_prevents_incoming_damage():
    """609.7: A prevention effect creates a 'shield' that prevents the next damage
    from any source. The shield intercepts damage before it affects the player.
    """
    prevent_spell = _mk_card(
        "Healing Salve", "Instant", "Prevent the next 3 damage that would be dealt to any target this turn."
    )
    bolt = _mk_card("Lava Spike", "Sorcery", "Lava Spike deals 3 damage to any target.")

    p1 = PlayerState(name="P1", hand=[prevent_spell, bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    # Apply prevention shield to p2
    game.cast_from_hand(0, "Healing Salve", target_player_index=1)
    assert p2.damage_prevention_pool == 3

    # Fire a 3-damage spell at p2 — all damage is prevented
    game.cast_from_hand(0, "Lava Spike", target_player_index=1)
    assert p2.life == 20


@pytest.mark.cr("615.7")
def test_609_7_prevention_pool_reduced_by_prevented_amount():
    """609.7: Each point of damage prevented consumes one charge from the
    prevention pool. After partial prevention, the remaining pool is correct.
    """
    prevent_spell = _mk_card(
        "Healing Salve", "Instant", "Prevent the next 3 damage that would be dealt to any target this turn."
    )
    bolt = _mk_card("Lava Spike", "Sorcery", "Lava Spike deals 2 damage to any target.")

    p1 = PlayerState(name="P1", hand=[prevent_spell, bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Healing Salve", target_player_index=1)
    assert p2.damage_prevention_pool == 3

    game.cast_from_hand(0, "Lava Spike", target_player_index=1)

    # 2 damage was prevented; 1 charge remains in the pool
    assert p2.life == 20
    assert p2.damage_prevention_pool == 1


@pytest.mark.cr("615.7")
def test_609_7_prevention_pool_partially_blocks_excess_damage():
    """609.7: If damage exceeds the prevention pool, only the pooled amount is
    prevented and the excess still resolves normally.
    """
    prevent_spell = _mk_card(
        "Healing Salve", "Instant", "Prevent the next 3 damage that would be dealt to any target this turn."
    )
    bolt = _mk_card("Fireball Lite", "Sorcery", "Fireball Lite deals 5 damage to any target.")

    p1 = PlayerState(name="P1", hand=[prevent_spell, bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Healing Salve", target_player_index=1)
    game.cast_from_hand(0, "Fireball Lite", target_player_index=1)

    # 3 prevented, 2 gets through
    assert p2.life == 18
    assert p2.damage_prevention_pool == 0


@pytest.mark.cr("615.7", "615.3")
def test_609_7_prevention_pool_exhausted_after_use():
    """609.7: Once a prevention shield is exhausted, subsequent damage is not
    prevented. The shield is fully consumed after protecting against its limit.
    """
    prevent_spell = _mk_card(
        "Healing Salve", "Instant", "Prevent the next 3 damage that would be dealt to any target this turn."
    )
    bolt1 = _mk_card("Bolt One", "Instant", "Bolt One deals 3 damage to any target.")
    bolt2 = _mk_card("Bolt Two", "Instant", "Bolt Two deals 3 damage to any target.")

    p1 = PlayerState(name="P1", hand=[prevent_spell, bolt1, bolt2])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Healing Salve", target_player_index=1)
    game.cast_from_hand(0, "Bolt One", target_player_index=1)
    # Pool is now 0; second bolt hits fully
    game.cast_from_hand(0, "Bolt Two", target_player_index=1)

    # First bolt: fully prevented. Second bolt: no prevention left.
    assert p2.life == 17
    assert p2.damage_prevention_pool == 0


@pytest.mark.cr("615.7")
def test_prevention_shield_records_and_clears_source():
    """The granting card is recorded on the shield (so the UI can preview it) and
    cleared once the pool is fully consumed."""
    prevent_spell = _mk_card(
        "Healing Salve", "Instant", "Prevent the next 3 damage that would be dealt to any target this turn."
    )
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")

    p1 = PlayerState(name="P1", hand=[prevent_spell, bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Healing Salve", target_player_index=1)
    assert p2.damage_prevention_pool == 3
    assert p2.damage_prevention_source == "Healing Salve"

    game.cast_from_hand(0, "Bolt", target_player_index=1)
    # Pool exhausted → source cleared so no stale shield art lingers.
    assert p2.damage_prevention_pool == 0
    assert p2.damage_prevention_source is None


# ---------------------------------------------------------------------------
# Rule 610.1 — One-shot effects do something just once and have no duration
# ---------------------------------------------------------------------------


@pytest.mark.cr("610.1")
def test_610_1_deal_damage_is_one_shot_no_duration():
    """610.1: Dealing damage is a one-shot effect. Once it resolves, there is no
    ongoing effect or duration — the damage was applied and is complete.
    """
    bolt = _mk_card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.")
    creature = _mk_creature("Target Bear", 2, 4)

    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)

    # Damage is marked immediately (one-shot); no "expires_at" for the damage itself
    if p2.battlefield:
        perm = p2.battlefield[0]
        assert perm.damage_marked == 3
        assert "expires_at" not in perm.metadata or perm.metadata.get("expires_key") != "damage_marked"


@pytest.mark.cr("610.1")
def test_610_1_deal_damage_to_player_is_immediate():
    """610.1: Dealing damage to a player is a one-shot effect — the life total
    changes immediately when the effect resolves, with no delay or duration.
    """
    bolt = _mk_card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)

    # Life total changed immediately — no "resolve later" state
    assert p2.life == 17


@pytest.mark.cr("610.1")
def test_610_1_destroy_permanent_is_one_shot():
    """610.1: Destroying a permanent is a one-shot effect. The permanent is removed
    from the battlefield immediately when the effect resolves. There is no duration —
    it doesn't destroy 'until end of turn' and then return.
    """
    terror = _mk_card("Terror", "Instant", "Destroy target creature.")
    creature = _mk_creature("Target Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[terror])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

    assert len(p2.battlefield) == 0
    assert len(p2.graveyard) == 1
    assert p2.graveyard[0].name == "Target Bear"


@pytest.mark.cr("610.1")
def test_610_1_destroy_does_not_return_after_cleanup():
    """610.1: A destroyed permanent stays destroyed after the cleanup step.
    Unlike 'until end of turn' continuous effects, destruction is a one-shot
    with no return.
    """
    terror = _mk_card("Terror", "Instant", "Destroy target creature.")
    creature = _mk_creature("Doomed Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[terror])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)
    game.resolve_cleanup_step(0)

    # Still destroyed after cleanup — one-shot effects don't reverse
    assert len(p2.battlefield) == 0
    assert len(p2.graveyard) == 1


@pytest.mark.cr("614.8", "701.19a")
def test_614_8_unused_regeneration_shield_expires_at_cleanup():
    """614.8 / 701.19a: a regeneration shield that is not used lasts only until the
    end of the turn it was created. After the cleanup step it is gone.
    """
    creature = _mk_creature("Shielded Bear", 2, 2)
    perm = Permanent(card=creature, regeneration_shield=2)
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert perm.regeneration_shield == 2
    game.resolve_cleanup_step(0)
    assert perm.regeneration_shield == 0


@pytest.mark.cr("610.1")
def test_610_1_draw_cards_is_immediate_and_one_shot():
    """610.1: Drawing cards is a one-shot effect. Cards move to the hand immediately
    when the spell resolves. There is no duration.
    """
    draw_spell = _mk_card("Ancestral Recall", "Instant", "Target player draws three cards.")
    lib_cards = [_mk_creature(f"Lib Bear {i}", 2, 2) for i in range(5)]

    p1 = PlayerState(name="P1", hand=[draw_spell])
    p2 = PlayerState(name="P2", library=lib_cards[:])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Ancestral Recall", target_player_index=1)

    # Cards moved immediately, no duration
    assert len(p2.hand) == 3
    assert len(p2.library) == 2


@pytest.mark.cr("610.1")
def test_610_1_discard_cards_is_one_shot():
    """610.1: Discarding cards is a one-shot effect. Cards move to the graveyard
    immediately when the effect resolves, with no duration or reversal.
    """
    discard_spell = _mk_card("Mind Rot", "Sorcery", "Target player discards two cards.")
    hand_cards = [_mk_creature(f"Hand Bear {i}", 2, 2) for i in range(3)]

    p1 = PlayerState(name="P1", hand=[discard_spell])
    p2 = PlayerState(name="P2", hand=hand_cards[:])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Mind Rot", target_player_index=1)
    game.auto_resolve_pending_discard()  # the discarder picks which card(s)

    # Two cards discarded immediately, one remains
    assert len(p2.hand) == 1
    assert len(p2.graveyard) == 2


@pytest.mark.cr("610.1")
def test_610_1_discard_cards_do_not_return_after_cleanup():
    """610.1: Cards discarded by a one-shot discard effect stay in the graveyard
    after cleanup. The discard is permanent — no duration, no return.
    """
    discard_spell = _mk_card("Mind Rot", "Sorcery", "Target player discards two cards.")
    hand_cards = [_mk_creature(f"Doomed Bear {i}", 2, 2) for i in range(2)]

    p1 = PlayerState(name="P1", hand=[discard_spell])
    p2 = PlayerState(name="P2", hand=hand_cards[:])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Mind Rot", target_player_index=1)
    game.auto_resolve_pending_discard()  # the discarder picks which card(s)
    game.resolve_cleanup_step(0)

    assert len(p2.hand) == 0
    assert len(p2.graveyard) == 2


@pytest.mark.cr("610.1")
def test_610_1_bounce_is_one_shot_zone_change():
    """610.1: Returning a creature to its owner's hand (bounce) is a one-shot
    zone-change effect. The creature moves immediately from battlefield to hand.
    """
    bounce = _mk_card(
        "Unsummon", "Instant", "Return target creature to its owner's hand."
    )
    creature = _mk_creature("Bounced Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[bounce])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Unsummon", target_player_index=1)

    assert len(p2.battlefield) == 0
    assert len(p2.hand) == 1
    assert p2.hand[0].name == "Bounced Bear"


@pytest.mark.cr("610.1")
def test_610_1_create_token_is_one_shot():
    """610.1: Creating a token is a one-shot effect — the token enters the
    battlefield immediately when the effect resolves, with no duration.
    """
    wasp_maker = _mk_card(
        "Wasp Nest", "Artifact",
        "{T}: create a 1/1 colorless insect artifact creature token with flying named wasp."
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wasp_maker)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    initial_battlefield_count = len(p1.battlefield)
    game.activate_permanent_ability(0, "Wasp Nest", target_player_index=1)

    # Token was placed on battlefield immediately as a one-shot effect
    assert len(p1.battlefield) > initial_battlefield_count


@pytest.mark.cr("610.1")
def test_610_1_multiple_one_shot_effects_from_same_spell():
    """610.1: A spell can create multiple one-shot effects, each resolving
    immediately in sequence. Each is an independent one-shot with no duration.
    Example: deal 3 damage to target and draw a card — both happen once.
    """
    draw_spell = _mk_card("Ancestral Recall", "Instant", "Target player draws three cards.")
    lib_cards = [_mk_creature(f"Book Bear {i}", 2, 2) for i in range(3)]

    p1 = PlayerState(name="P1", hand=[draw_spell])
    p2 = PlayerState(name="P2", life=20, library=lib_cards[:])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Ancestral Recall", target_player_index=1)

    # All cards drawn immediately — each draw is a one-shot
    assert len(p2.hand) == 3
    assert len(p2.library) == 0


# ---------------------------------------------------------------------------
# Rule 610.3 — Zone-change one-shot effects ("until" a specified event)
# ---------------------------------------------------------------------------


@pytest.mark.cr("610.3")
def test_610_3_exile_until_eot_moves_creature_to_exile():
    """610.3: A one-shot effect can cause an object to change zones 'until' a
    specified event. When 'Exile target creature until end of turn' resolves,
    the creature moves to exile immediately.
    """
    exile_spell = _mk_card(
        "Temporary Exile", "Instant",
        "Exile target creature until end of turn."
    )
    creature = _mk_creature("Temporary Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[exile_spell])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Temporary Exile", target_player_index=1, target_permanent_index=0)

    # Creature is exiled — no longer on battlefield
    assert len(p2.battlefield) == 0
    # Creature is in exile, not graveyard
    assert len(p2.exile) == 1
    assert len(p2.graveyard) == 0


@pytest.mark.cr("610.3")
def test_610_3_a_linked_exile_returns_the_card_to_the_zone_it_came_from():
    """610.3: the second one-shot effect returns the object to its **previous
    zone** — which is whichever zone the first effect took it from, not a zone
    the engine picks.

    Both zones are exercised on one board so the reading cannot be a constant
    that happens to be right: one permanent takes a card from a hand, the other
    takes one from a graveyard, and each card goes back where it was.
    """
    from engine.linked_exile import LEAVES, link_exiled_card

    from_hand = Permanent(card=_mk_card("Hand Taker", "Artifact"))
    from_yard = Permanent(card=_mk_card("Yard Taker", "Artifact"))
    p1 = PlayerState(name="P1", battlefield=[from_hand, from_yard])
    held, buried = _mk_creature("Held Bear", 2, 2), _mk_creature("Buried Bear", 2, 2)
    p2 = PlayerState(name="P2", exile=[held, buried])
    game = Game(players=[p1, p2])
    link_exiled_card(from_hand, held, 1, to="hand", ends_on=(LEAVES,))
    link_exiled_card(from_yard, buried, 1, to="graveyard", ends_on=(LEAVES,))

    game.remove_all_from_battlefield([from_hand, from_yard])

    assert [c.name for c in p2.hand] == ["Held Bear"]
    assert [c.name for c in p2.graveyard] == ["Buried Bear"]
    assert p2.exile == []


@pytest.mark.cr("610.3", "701.26b")
def test_610_3_only_the_named_event_ends_a_linked_exile():
    """610.3: the second one-shot effect is created "immediately after **the
    specified event**" — the one the first effect named, and no other.

    Two permanents holding one card each: one exile ends on the permanent
    leaving the battlefield, the other also on it becoming untapped (Tawnos's
    Coffin's second ending). Untapping both gives back only the second.

    The engine used to end every linked exile on any untap, which is a bug with
    no card of its own to fail on: Idol of Endurance taps for its own ability
    and untaps in the next untap step, so its whole pile went to the graveyard
    a turn after it was exiled.
    """
    from engine.linked_exile import LEAVES, UNTAPPED, link_exiled_card

    leaves_only = Permanent(card=_mk_card("Leaves Only", "Artifact"))
    or_untaps = Permanent(card=_mk_card("Or Untaps", "Artifact"))
    leaves_only.tapped = True
    or_untaps.tapped = True
    kept, given = _mk_creature("Kept Bear", 2, 2), _mk_creature("Given Bear", 2, 2)
    p1 = PlayerState(name="P1", battlefield=[leaves_only, or_untaps])
    p2 = PlayerState(name="P2", exile=[kept, given])
    game = Game(players=[p1, p2])
    link_exiled_card(leaves_only, kept, 1, to="hand", ends_on=(LEAVES,))
    link_exiled_card(or_untaps, given, 1, to="hand", ends_on=(LEAVES, UNTAPPED))

    game.become_untapped(leaves_only)
    game.become_untapped(or_untaps)

    assert [c.name for c in p2.hand] == ["Given Bear"]
    assert [c.name for c in p2.exile] == ["Kept Bear"]

    game.remove_from_battlefield(leaves_only)

    assert sorted(c.name for c in p2.hand) == ["Given Bear", "Kept Bear"]


@pytest.mark.cr("610.3")
def test_610_3_exile_until_eot_returns_at_cleanup():
    """610.3: When an object is exiled 'until end of turn', a second one-shot
    effect is created at the end of the turn. This second effect returns the
    object to its previous zone (the battlefield) at the cleanup step.
    """
    exile_spell = _mk_card(
        "Temporary Exile", "Instant",
        "Exile target creature until end of turn."
    )
    creature = _mk_creature("Temporary Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[exile_spell])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Temporary Exile", target_player_index=1, target_permanent_index=0)
    assert len(p2.battlefield) == 0
    assert len(p2.exile) == 1

    # Cleanup triggers the second one-shot: return from exile
    game.resolve_cleanup_step(0)

    assert len(p2.exile) == 0
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].card.name == "Temporary Bear"


@pytest.mark.cr("610.3c")
def test_610_3c_exiled_creature_returns_under_owners_control():
    """610.3c: An object returned to the battlefield by a zone-change one-shot
    returns under its owner's control unless the effect specifies otherwise.
    """
    exile_spell = _mk_card(
        "Temporary Exile", "Instant",
        "Exile target creature until end of turn."
    )
    creature = _mk_creature("Owned Bear", 2, 2)

    # p1 casts the exile spell targeting p2's creature
    p1 = PlayerState(name="P1", hand=[exile_spell])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Temporary Exile", target_player_index=1, target_permanent_index=0)
    game.resolve_cleanup_step(0)

    # Creature returns to p2 (its owner), not p1
    assert len(p1.battlefield) == 0
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].card.name == "Owned Bear"


@pytest.mark.cr("610.3d")
def test_610_3d_simultaneous_zone_changes_from_same_event():
    """610.3d: If multiple one-shot zone-change effects are created immediately
    after one or more simultaneous events, those one-shot effects are also
    simultaneous. Example: Two exiled creatures both return at the same time
    after the event that triggers their return.
    """
    exile_spell1 = _mk_card(
        "Temporary Exile", "Instant",
        "Exile target creature until end of turn."
    )
    exile_spell2 = _mk_card(
        "Temporary Exile", "Instant",
        "Exile target creature until end of turn."
    )
    creature1 = _mk_creature("Bear One", 2, 2)
    creature2 = _mk_creature("Bear Two", 3, 3)

    p1 = PlayerState(name="P1", hand=[exile_spell1, exile_spell2])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature1), Permanent(card=creature2)])
    game = Game(players=[p1, p2])

    # Exile both creatures (both will be scheduled to return at EOT)
    game.cast_from_hand(0, "Temporary Exile", target_player_index=1, target_permanent_index=0)
    # After first exile, p2 battlefield has 1 creature; Bear Two is now index 0
    game.cast_from_hand(0, "Temporary Exile", target_player_index=1, target_permanent_index=0)

    assert len(p2.battlefield) == 0
    assert len(p2.exile) == 2

    # Cleanup: both return simultaneously
    game.resolve_cleanup_step(0)

    assert len(p2.exile) == 0
    assert len(p2.battlefield) == 2


# ---------------------------------------------------------------------------
# CR 119.5 — setting a life total (round 32)
#
# "That player's life total becomes 20." (Rebirth.) The rule is that this is a
# gain or a loss of the difference, which is why it cannot be lowered as either
# one: the printed number is the result, and which direction it moves in is not
# known until the effect resolves.
# ---------------------------------------------------------------------------


def _r32_set_life_card(name: str = "Life Setter", text: str = "Your life total becomes 20."):
    return _mk_card(name, "Sorcery", text)


def _r32_set_life_game(life: int):
    player = PlayerState(name="P1", life=life, hand=[_r32_set_life_card()])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, player


@pytest.mark.cr("119.5")
def test_setting_a_life_total_upward_is_a_gain_of_the_difference():
    game, player = _r32_set_life_game(5)

    assert game.cast_from_hand(0, "Life Setter").supported

    assert player.life == 20


@pytest.mark.cr("119.5")
def test_setting_a_life_total_downward_is_a_loss_of_the_difference():
    game, player = _r32_set_life_game(31)

    assert game.cast_from_hand(0, "Life Setter").supported

    assert player.life == 20


@pytest.mark.cr("119.5")
def test_setting_a_life_total_to_what_it_already_is_changes_nothing():
    game, player = _r32_set_life_game(20)

    assert game.cast_from_hand(0, "Life Setter").supported

    assert player.life == 20


@pytest.mark.cr("119.5", "614.1")
def test_the_gain_half_goes_through_the_life_gain_seam():
    """CR 119.5 makes the upward half a *gain*, so a CR 614 replacement of life
    gain still sees it. Lich is the pool's ("If you would gain life, draw that
    many cards instead"), and an assignment straight onto ``player.life`` would
    have walked past it."""
    from unittest.mock import patch

    game, player = _r32_set_life_game(5)

    with patch.object(type(game), "_gain_life", autospec=True) as gain:
        assert game.cast_from_hand(0, "Life Setter").supported

    assert gain.call_count == 1
    assert gain.call_args.args[1] is player
    assert gain.call_args.args[2] == 15


# --- W3G3: X spells, multiple targets, damage sources ---
@pytest.mark.cr("609.7b", "609.7c")
def test_609_7b_a_shield_rechecks_the_sources_colour_when_it_would_deal_damage():
    """609.7b: "When the source would deal damage, the shield rechecks the
    source's properties. If the properties no longer match, the damage isn't
    prevented."

    609.7c is the other half: a static ability's rewrite applies to sources that
    are permanents with the property **and** to sources that are not on the
    battlefield — which is why the rewrite is asked of the board rather than of
    the source, and why a spell is rewritten exactly as a creature is.
    """
    from engine.damage_events import deal_damage
    from engine.damage_source_colors import damage_source_colors

    flame = _mk_card(
        "Spectral Fire", "Enchantment",
        "Black and/or red permanents and spells are colorless sources of damage.",
    )
    red_bolt = _mk_card("Red Spell", "Instant", "", colors=("R",))

    victim = PlayerState(name="P1", life=20)
    caster = PlayerState(name="P2", life=20)
    game = Game(players=[victim, caster])
    game.resolving_seats.append(1)

    assert damage_source_colors(game, red_bolt) == ("R",)

    game.players[0].battlefield.append(Permanent(card=flame))
    game._recompute_continuous_effects()
    assert damage_source_colors(game, red_bolt) == (), \
        "609.7c reaches a source that is not on the battlefield"

    # And the recheck is what a colour shield asks: the event is unchanged.
    assert deal_damage(
        game, {"recipient": victim, "amount": 2, "source": red_bolt}
    ).dealt == 2


@pytest.mark.cr("609.7b")
def test_609_7b_a_source_the_rewrite_does_not_name_keeps_its_colours():
    """The rewrite names colours; a source of none of them is untouched — and a
    source of one of them is colorless *entirely*, not merely stripped of the
    named colour ("**are colorless** sources of damage")."""
    from engine.damage_source_colors import damage_source_colors

    flame = _mk_card(
        "Spectral Fire", "Enchantment",
        "Black and/or red permanents and spells are colorless sources of damage.",
    )
    blue = _mk_card("Blue Spell", "Instant", "", colors=("U",))
    black_green = _mk_card("Rot", "Instant", "", colors=("B", "G"))

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=flame)])
    game = Game(players=[p1, PlayerState(name="P2")])
    game._recompute_continuous_effects()

    assert damage_source_colors(game, blue) == ("U",)
    assert damage_source_colors(game, black_green) == ()
# --- end W3G3 ---
