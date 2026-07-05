"""Tests for Magic: The Gathering Comprehensive Rules Section 614.

Covers:
  614   — Replacement Effects
  614.1 — Definition and categories of replacement effects
  614.4 — Replacement effects must exist before the event
  614.5 — A replacement effect doesn't invoke itself repeatedly
  614.6 — A replaced event never happens
  614.7 — If the event never happens, the replacement does nothing
  614.7a — 0-damage source has no event to replace
  614.8 — Regeneration as a destruction-replacement effect
  614.9 — Damage redirection effects
  614.10 — Skip effects are replacement effects
  614.10a — Two skip effects mean two occurrences are skipped
  614.12 — Replacement effects that modify how a permanent enters the battlefield
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
# 614.1a — Effects that use the word "instead" are replacement effects.
# Damage prevention uses "prevent … instead" semantics: the damage event is
# replaced with 0 damage rather than applied then reduced after the fact.
# ---------------------------------------------------------------------------


def test_614_1a_prevention_is_replacement_effect():
    """614.1a: A prevention effect uses 'instead' — it replaces the damage
    event entirely. The damage that would be dealt is replaced with 0; the
    original event never occurs."""
    prevent = _mk_card(
        "Holy Shield",
        "Instant",
        "Prevent the next 5 damage that would be dealt to target player.",
    )
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[prevent, bolt], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    # Activate the prevention replacement effect on P2
    game.cast_from_hand(0, "Holy Shield", target_player_index=1)
    assert p2.damage_prevention_pool == 5

    # The damage event is replaced by the prevention effect — P2 takes 0 damage
    game.cast_from_hand(0, "Bolt", target_player_index=1)
    assert p2.life == 20, "Damage was replaced by prevention; life should be unchanged"


def test_614_1a_partial_prevention_replaces_part_of_event():
    """614.1a: If prevention pool is smaller than the damage, only part of the
    event is replaced. The remainder proceeds as a modified event (614.6)."""
    prevent = _mk_card(
        "Partial Shield",
        "Instant",
        "Prevent the next 2 damage that would be dealt to target player.",
    )
    bolt = _mk_card("Big Bolt", "Instant", "Big Bolt deals 5 damage to any target.")
    p1 = PlayerState(name="P1", hand=[prevent, bolt], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Partial Shield", target_player_index=1)
    game.cast_from_hand(0, "Big Bolt", target_player_index=1)

    # 2 damage prevented, 3 gets through
    assert p2.life == 17


# ---------------------------------------------------------------------------
# 614.1b — Effects that use the word "skip" are replacement effects.
# ---------------------------------------------------------------------------


def test_614_1b_skip_turn_is_replacement_effect():
    """614.1b: A 'skip your next turn' effect replaces the turn with nothing —
    the skipped player does not take that turn at all."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # P2's next turn is skipped
    game.skip_next_turn(1, count=1)

    # start_next_turn should skip P2 and return P1 as the active player
    next_player = game.start_next_turn()
    assert next_player == 0, "P2's turn was skipped; P1 should be active again"


def test_614_1b_skip_phase_replaces_phase_with_nothing():
    """614.1b: 'Skip your draw step' replaces the draw step with nothing —
    the player draws no card during that draw step."""
    p1 = PlayerState(name="P1", library=[_mk_creature("Bear")])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Skip P1's draw step this turn
    game.skip_next_step("draw")
    initial_hand_size = len(p1.hand)

    game.resolve_draw_step(0)

    assert len(p1.hand) == initial_hand_size, "Draw step was skipped; hand size unchanged"


# ---------------------------------------------------------------------------
# 614.1c — "This permanent enters tapped" is a replacement effect.
# The entering-untapped event is replaced with entering-tapped.
# ---------------------------------------------------------------------------


def test_614_1c_enters_tapped_is_replacement_effect():
    """614.1c: A permanent whose text says it enters tapped uses a replacement
    effect — the 'enters untapped' event is replaced with 'enters tapped'."""
    tapped_land = _mk_card(
        "Tapped Land",
        "Land",
        "Tapped Land enters tapped.",
    )
    p1 = PlayerState(name="P1", hand=[tapped_land])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Tapped Land")

    assert p1.battlefield[0].tapped is True, "Replacement effect caused land to enter tapped"


def test_614_1c_normal_permanent_enters_untapped():
    """614.1c baseline: Without an 'enters tapped' replacement effect, a
    permanent enters the battlefield untapped."""
    normal_land = _mk_card("Forest", "Basic Land — Forest", "")
    p1 = PlayerState(name="P1", hand=[normal_land])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Forest")

    assert p1.battlefield[0].tapped is False, "Without replacement effect, land enters untapped"


# ---------------------------------------------------------------------------
# 614.1d — Continuous effects that read "[This permanent] enters …" are
# replacement effects. "This creature enters with X +1/+1 counters on it"
# replaces the normal entering event with one that adds counters.
# ---------------------------------------------------------------------------


def test_614_1d_enters_with_x_plus1_counters():
    """614.1d: 'This creature enters with X +1/+1 counters on it' is a
    replacement effect that modifies how the permanent enters. The creature
    enters with bonus power and toughness equal to X."""
    # X=3 creature: should enter as a 5/5 (2+3 / 2+3)
    counter_creature = _mk_creature(
        "Hydra",
        power=2,
        toughness=2,
        oracle_text="This creature enters with X +1/+1 counters on it.",
    )
    p1 = PlayerState(name="P1", hand=[counter_creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Hydra", x_value=3)

    perm = p1.battlefield[0]
    assert perm.effective_power == 5, "Hydra entered with 3 +1/+1 counters (2+3=5 power)"
    assert perm.effective_toughness == 5, "Hydra entered with 3 +1/+1 counters (2+3=5 toughness)"


def test_614_1d_enters_with_x_counters_zero_x():
    """614.1d: When X=0, 'enters with X +1/+1 counters' adds no counters.
    The creature enters with its base P/T."""
    counter_creature = _mk_creature(
        "Small Hydra",
        power=2,
        toughness=2,
        oracle_text="This creature enters with X +1/+1 counters on it.",
    )
    p1 = PlayerState(name="P1", hand=[counter_creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Small Hydra", x_value=0)

    perm = p1.battlefield[0]
    assert perm.effective_power == 2
    assert perm.effective_toughness == 2


# ---------------------------------------------------------------------------
# 614.4 — Replacement effects must exist before the event; they can't go back
# in time and modify something that's already happened.
# ---------------------------------------------------------------------------


def test_614_4_prevention_before_damage_works():
    """614.4: A prevention replacement effect set up before the damage event
    occurs correctly replaces the damage event."""
    prevent = _mk_card(
        "Pre-emptive Shield",
        "Instant",
        "Prevent the next 10 damage that would be dealt to target player.",
    )
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[prevent, bolt], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Pre-emptive Shield", target_player_index=1)
    game.cast_from_hand(0, "Bolt", target_player_index=1)

    assert p2.life == 20, "Replacement effect existed before the damage; 3 damage prevented"


def test_614_4_no_replacement_means_no_prevention():
    """614.4: Without a replacement effect in place, the damage event proceeds
    unmodified — the full amount of damage is dealt."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Bolt", target_player_index=1)

    assert p2.life == 17, "No prevention replacement effect; full 3 damage dealt"


# ---------------------------------------------------------------------------
# 614.5 — A replacement effect gets only one opportunity to affect an event.
# It doesn't apply to the modified event it produced.
# ---------------------------------------------------------------------------


def test_614_5_prevention_applies_exactly_once():
    """614.5: A prevention replacement effect intercepts the damage event once.
    After applying, the modified event (0 damage or reduced damage) is the
    final event — the same effect doesn't re-apply to it."""
    prevent = _mk_card(
        "Exact Shield",
        "Instant",
        "Prevent the next 3 damage that would be dealt to target player.",
    )
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[prevent, bolt], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Exact Shield", target_player_index=1)
    assert p2.damage_prevention_pool == 3

    game.cast_from_hand(0, "Bolt", target_player_index=1)

    # Shield applied once: all 3 damage replaced; pool exhausted
    assert p2.life == 20
    assert p2.damage_prevention_pool == 0, "Pool fully consumed by single application"


def test_614_5_two_prevention_shields_each_apply_to_separate_events():
    """614.5: Two separate prevention replacement effects each get one
    opportunity — the first applies to the first damage event, leaving the
    second for the next event. They do not stack recursively."""
    prevent1 = _mk_card(
        "Shield One",
        "Instant",
        "Prevent the next 3 damage that would be dealt to target player.",
    )
    prevent2 = _mk_card(
        "Shield Two",
        "Instant",
        "Prevent the next 3 damage that would be dealt to target player.",
    )
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    bolt2 = _mk_card("Bolt2", "Instant", "Bolt2 deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[prevent1, prevent2, bolt, bolt2], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Shield One", target_player_index=1)
    game.cast_from_hand(0, "Shield Two", target_player_index=1)
    assert p2.damage_prevention_pool == 6

    # First bolt: first 3 from the pool prevents it
    game.cast_from_hand(0, "Bolt", target_player_index=1)
    assert p2.life == 20
    assert p2.damage_prevention_pool == 3

    # Second bolt: remaining 3 from the pool prevents it
    game.cast_from_hand(0, "Bolt2", target_player_index=1)
    assert p2.life == 20
    assert p2.damage_prevention_pool == 0


# ---------------------------------------------------------------------------
# 614.6 — If an event is replaced, it never happens. The modified event
# occurs instead (which may trigger abilities).
# ---------------------------------------------------------------------------


def test_614_6_replaced_damage_event_never_reduces_life():
    """614.6: When a damage event is fully replaced (all damage prevented),
    the original damage event never happens — the player's life total is
    unchanged by the original event."""
    prevent = _mk_card(
        "Full Block",
        "Instant",
        "Prevent the next 10 damage that would be dealt to target player.",
    )
    nuke = _mk_card("Nuke", "Sorcery", "Nuke deals 6 damage to any target.")
    p1 = PlayerState(name="P1", hand=[prevent, nuke], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Full Block", target_player_index=1)
    game.cast_from_hand(0, "Nuke", target_player_index=1)

    assert p2.life == 20, "Original damage event never happened; life unchanged"


# ---------------------------------------------------------------------------
# 614.7 — If a replacement effect would replace an event that never happens,
# the replacement effect simply doesn't do anything.
# ---------------------------------------------------------------------------


def test_614_7_prevention_pool_not_consumed_if_no_damage_event():
    """614.7: A prevention replacement effect watches for damage events. If no
    damage event occurs, the replacement does nothing and the pool is unchanged."""
    prevent = _mk_card(
        "Unused Shield",
        "Instant",
        "Prevent the next 5 damage that would be dealt to target player.",
    )
    p1 = PlayerState(name="P1", hand=[prevent], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Unused Shield", target_player_index=1)
    pool_after_grant = p2.damage_prevention_pool

    # No damage spell is cast; the replacement effect watches but finds no event
    assert pool_after_grant == 5, "Pool established; no damage event consumed it"
    assert p2.life == 20


# ---------------------------------------------------------------------------
# 614.7a — If a source would deal 0 damage, it does not deal damage at all.
# Replacement effects that would affect that source's damage have no event
# to replace, so they have no effect.
# ---------------------------------------------------------------------------


def test_614_7a_zero_damage_leaves_prevention_pool_intact():
    """614.7a: A source dealing 0 damage creates no damage event. A prevention
    replacement effect watching for that damage has nothing to replace and does
    not consume the prevention pool."""
    prevent = _mk_card(
        "Active Shield",
        "Instant",
        "Prevent the next 5 damage that would be dealt to target player.",
    )
    # 0/0 creature deals 0 combat damage — no damage event
    zero_attacker = _mk_creature("Zero Attacker", power=0, toughness=1)
    p1 = PlayerState(
        name="P1",
        hand=[prevent],
        battlefield=[Permanent(card=zero_attacker)],
        life=20,
    )
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Active Shield", target_player_index=1)
    pool_before = p2.damage_prevention_pool

    # Simulate the 0-power attacker dealing 0 combat damage
    game._prevent_damage(p2, 0)

    assert p2.damage_prevention_pool == pool_before, "0-damage event did not consume the pool"
    assert p2.life == 20


def test_614_7a_zero_damage_spell_has_no_event():
    """614.7a: A spell that would deal 0 damage to a player does not deal
    damage at all — the player's life total is unaffected."""
    zero_bolt = _mk_card("Zero Bolt", "Instant", "Zero Bolt deals 0 damage to any target.")
    p1 = PlayerState(name="P1", hand=[zero_bolt], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Zero Bolt", target_player_index=1)

    assert p2.life == 20


# ---------------------------------------------------------------------------
# 614.8 — Regeneration is a destruction-replacement effect.
# "The next time [permanent] would be destroyed this turn, instead remove all
# damage, tap it, and if attacking/blocking remove it from combat."
# ---------------------------------------------------------------------------


def test_614_8_regeneration_replaces_targeted_destroy():
    """614.8: A regeneration shield replaces a 'destroy' event on the creature.
    The creature stays on the battlefield instead of going to the graveyard."""
    regen = _mk_card(
        "Regen Spell",
        "Instant",
        "Regenerate target creature.",
    )
    destroy = _mk_card(
        "Terror",
        "Instant",
        "Destroy target creature.",
    )
    creature = _mk_creature("Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[regen, destroy])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Regen Spell", target_player_index=1)
    assert p2.battlefield[0].regeneration_shield == 1

    game.cast_from_hand(0, "Terror", target_player_index=1)

    assert len(p2.battlefield) == 1, "Regeneration replaced the destroy; creature survived"
    assert len(p2.graveyard) == 0, "Creature did not go to graveyard"


def test_614_8_regeneration_taps_creature_after_replacing_destroy():
    """614.8: After regeneration replaces a destruction event, the creature
    is tapped as part of the replacement (rule 614.8 effect)."""
    regen = _mk_card("Regen Spell", "Instant", "Regenerate target creature.")
    destroy = _mk_card("Terror", "Instant", "Destroy target creature.")
    creature = _mk_creature("Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[regen, destroy])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Regen Spell", target_player_index=1)
    game.cast_from_hand(0, "Terror", target_player_index=1)

    assert p2.battlefield[0].tapped is True, "Regenerated creature is tapped"


def test_614_8_regeneration_clears_damage_after_replacing_destroy():
    """614.8: After regeneration replaces a destruction event, all damage
    marked on the creature is removed as part of the replacement."""
    regen = _mk_card("Regen Spell", "Instant", "Regenerate target creature.")
    destroy = _mk_card("Terror", "Instant", "Destroy target creature.")
    creature = _mk_creature("Bear", 2, 2)
    perm = Permanent(card=creature, damage_marked=1)
    p1 = PlayerState(name="P1", hand=[regen, destroy])
    p2 = PlayerState(name="P2", battlefield=[perm])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Regen Spell", target_player_index=1)
    game.cast_from_hand(0, "Terror", target_player_index=1)

    assert p2.battlefield[0].damage_marked == 0, "Regeneration clears damage from the creature"


def test_614_8_regeneration_replaces_mass_destroy():
    """614.8: A regeneration shield also replaces destruction from mass-destroy
    effects such as 'Destroy all creatures.'"""
    regen = _mk_card("Regen Spell", "Instant", "Regenerate target creature.")
    wrath = _mk_card("Wrath", "Sorcery", "Destroy all creatures.")
    creature = _mk_creature("Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[regen, wrath])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Regen Spell", target_player_index=1)
    game.cast_from_hand(0, "Wrath", target_player_index=1)

    assert len(p2.battlefield) == 1, "Regeneration replaced mass-destroy for this creature"
    assert p2.battlefield[0].tapped is True


def test_614_8_regen_shield_consumed_once_per_use():
    """614.8: Each regeneration shield replaces exactly one destruction event.
    After the shield is consumed, the creature is vulnerable again."""
    regen = _mk_card("Regen Spell", "Instant", "Regenerate target creature.")
    destroy1 = _mk_card("Terror1", "Instant", "Destroy target creature.")
    destroy2 = _mk_card("Terror2", "Instant", "Destroy target creature.")
    creature = _mk_creature("Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[regen, destroy1, destroy2])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Regen Spell", target_player_index=1)
    game.cast_from_hand(0, "Terror1", target_player_index=1)
    # Shield consumed; creature survived first destroy
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].regeneration_shield == 0

    game.cast_from_hand(0, "Terror2", target_player_index=1)
    # No shield remaining; creature is destroyed
    assert len(p2.battlefield) == 0, "Second destroy killed the creature (no regen shield left)"
    assert len(p2.graveyard) == 1


def test_614_8_two_regen_shields_survive_two_destroys():
    """614.8: Two regeneration shields allow a creature to survive two
    separate destruction events."""
    regen1 = _mk_card("Regen 1", "Instant", "Regenerate target creature.")
    regen2 = _mk_card("Regen 2", "Instant", "Regenerate target creature.")
    destroy1 = _mk_card("Terror1", "Instant", "Destroy target creature.")
    destroy2 = _mk_card("Terror2", "Instant", "Destroy target creature.")
    creature = _mk_creature("Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[regen1, regen2, destroy1, destroy2])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Regen 1", target_player_index=1)
    game.cast_from_hand(0, "Regen 2", target_player_index=1)
    assert p2.battlefield[0].regeneration_shield == 2

    game.cast_from_hand(0, "Terror1", target_player_index=1)
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].regeneration_shield == 1

    game.cast_from_hand(0, "Terror2", target_player_index=1)
    assert len(p2.battlefield) == 1, "Second shield saved the creature from second destroy"
    assert p2.battlefield[0].regeneration_shield == 0


# ---------------------------------------------------------------------------
# 614.9 — Redirection effects replace damage to one target with the same
# damage to another target.
# ---------------------------------------------------------------------------


def test_614_9_damage_redirected_from_creature_to_player():
    """614.9: A redirection effect replaces damage-to-creature with the same
    damage to a different target (in this case, the creature's controller)."""
    redirect = _mk_card(
        "Jade Monolith",
        "Artifact",
        "{1}: The next time a source of your choice would deal damage to target creature this turn, that source deals that damage to you instead.",
    )
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    creature = _mk_creature("Target Creature", 2, 2)
    p1 = PlayerState(name="P1", hand=[bolt], battlefield=[Permanent(card=redirect)], life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)], life=20)
    game = Game(players=[p1, p2])

    # Activate redirect: mark p2's creature for redirection to p1
    game.activate_permanent_ability(0, "Jade Monolith", target_player_index=1)
    # Bolt targets the creature, but redirection sends damage to p1 instead
    game.cast_from_hand(0, "Bolt", target_player_index=1, target_permanent_index=0)

    assert p1.life == 17, "Damage was redirected from creature to p1"
    assert len(p2.battlefield) == 1, "Target creature survived (damage was redirected away)"


# ---------------------------------------------------------------------------
# 614.10 — Skip effects are replacement effects.
# "Skip [something]" = "Instead of doing [something], do nothing."
# ---------------------------------------------------------------------------


def test_614_10_skip_turn_skips_that_player():
    """614.10: 'Skip your next turn' is a replacement effect. The skipped turn
    is replaced with nothing — the player doesn't untap, doesn't draw, etc."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    initial_turn = game.turn
    game.skip_next_turn(1, count=1)  # Skip P2's next turn

    # P1 is active; next turn should go to P1 again, skipping P2
    next_player_idx = game.start_next_turn()
    assert next_player_idx == 0, "P2's turn was skipped by replacement effect"
    assert game.turn == initial_turn + 1, "Turn counter advanced even though P2 was skipped"


def test_614_10_skip_draw_step_prevents_card_draw():
    """614.10: Skipping the draw step replaces the draw-a-card event with
    nothing; the player doesn't draw during that step."""
    bear = _mk_creature("Bear")
    p1 = PlayerState(name="P1", library=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.skip_next_step("draw")
    game.resolve_draw_step(0)

    assert len(p1.hand) == 0, "Draw step skipped; no card drawn"
    assert len(p1.library) == 1, "Card remains in library"


# ---------------------------------------------------------------------------
# 614.10a — Anything scheduled for a skipped step/phase/turn won't happen.
# If two effects each cause a player to skip their next occurrence, that
# player must skip the next two.
# ---------------------------------------------------------------------------


def test_614_10a_two_skip_effects_mean_two_turns_skipped():
    """614.10a: If two 'skip your next turn' effects apply to the same player,
    that player skips two consecutive turns — one skip per effect."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Two separate skip-turn effects on P2
    game.skip_next_turn(1, count=1)
    game.skip_next_turn(1, count=1)
    assert game.skip_turn_counts.get(1, 0) == 2

    # First call: P2's first skipped turn → goes to P1
    next1 = game.start_next_turn()
    assert next1 == 0, "First of P2's two skipped turns: P1 is active"
    assert game.skip_turn_counts.get(1, 0) == 1, "One skip remaining"

    # Second call: P2's second skipped turn → goes to P1 again
    next2 = game.start_next_turn()
    assert next2 == 0, "Second of P2's two skipped turns: P1 is active again"
    assert game.skip_turn_counts.get(1, 0) == 0, "All skips consumed"

    # Third call: P2 takes their turn normally
    next3 = game.start_next_turn()
    assert next3 == 1, "P2 takes their turn after both skips are consumed"


# ---------------------------------------------------------------------------
# 614.12 — Replacement effects that modify how a permanent enters the
# battlefield. If such an effect requires a choice, the choice is made
# before the permanent enters.
# ---------------------------------------------------------------------------


def test_614_12_enters_with_counters_is_etb_replacement():
    """614.12: 'This creature enters with X +1/+1 counters on it' modifies
    how the permanent enters the battlefield. The counters are part of the
    entering event, not applied after."""
    # The replacement (adding X counters) happens as part of entering,
    # not as a separate one-shot effect after the fact.
    counter_card = _mk_creature(
        "Charging Hydra",
        power=2,
        toughness=2,
        oracle_text="This creature enters with X +1/+1 counters on it.",
    )
    p1 = PlayerState(name="P1", hand=[counter_card])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Charging Hydra", x_value=4)

    perm = p1.battlefield[0]
    assert perm.power_bonus == 4, "Replacement applied 4 +1/+1 counters on entry"
    assert perm.toughness_bonus == 4
    assert perm.effective_power == 6
    assert perm.effective_toughness == 6


def test_614_12_enters_tapped_from_card_text():
    """614.12: A permanent with its own 'enters tapped' static ability uses a
    replacement effect to enter tapped. This works even without an external
    'all permanents enter tapped' effect."""
    slow_land = _mk_card(
        "Slow Land",
        "Land",
        "Slow Land enters tapped.\n{T}: Add {G}.",
    )
    p1 = PlayerState(name="P1", hand=[slow_land])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Slow Land")

    assert p1.battlefield[0].tapped is True, "Enters-tapped replacement applied on entry"


def test_614_12_etb_replacement_from_creature_oracle_text():
    """614.12: A creature with 'this creature enters tapped' has its own ETB
    replacement effect that applies when it enters the battlefield."""
    sluggish = _mk_creature(
        "Sluggish Brute",
        power=3,
        toughness=3,
        oracle_text="This creature enters tapped.",
    )
    p1 = PlayerState(name="P1", hand=[sluggish])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Sluggish Brute")

    assert p1.battlefield[0].tapped is True, "Creature's own ETB replacement caused it to enter tapped"
