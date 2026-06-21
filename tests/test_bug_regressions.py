"""Regression tests for bugs found during testing (all 7).

Each test documents the bug, shows the expected (correct) behavior after the
fix, and guards against regressions.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine import Game, PlayerState, load_cards
from engine.models import CardDefinition, Permanent


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def all_cards():
    root = Path(__file__).resolve().parent.parent
    return load_cards(root / "lea_cards.json")


def _get(cards, name: str) -> CardDefinition:
    return next(c for c in cards if c.name == name)


def _mk_card(name: str, type_line: str, oracle_text: str = "", colors: tuple = ()) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = "2"
        raw["toughness"] = "2"
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Bug 1: Ley Druid — casting should NOT require a land target
#
# Root cause: the frontend `cardRequiresTargetLand` was checking all oracle
# text lines, including the activated ability "{T}: Untap target land." line.
# On the backend, creatures never require a target at cast time (only instants
# and sorceries do), so this test confirms the engine always accepts Ley Druid
# without a permanent_index.
# ---------------------------------------------------------------------------

def test_bug1_ley_druid_cast_without_land_target(all_cards):
    """Ley Druid (a creature) must be castable without supplying a target land."""
    druid = _get(all_cards, "Ley Druid")

    p1 = PlayerState(name="P1", hand=[druid])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # No target_permanent_index — land target is NOT needed at cast time
    result = game.cast_from_hand(0, "Ley Druid")

    assert result.supported, f"Expected Ley Druid to cast successfully, got: {result.details}"
    assert any(perm.card.name == "Ley Druid" for perm in p1.battlefield)


def test_bug1_ley_druid_activated_ability_still_requires_land_target(all_cards):
    """After entering the battlefield, the {T}: Untap target land ability works."""
    druid = _get(all_cards, "Ley Druid")
    forest = _get(all_cards, "Forest")

    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=druid), Permanent(card=forest, tapped=True)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Ley Druid", target_player_index=0)

    assert result.supported
    assert p1.battlefield[1].tapped is False


# ---------------------------------------------------------------------------
# Bug 2: Animate Dead — failed to find a target when the creature is in the
#         opponent's graveyard instead of the caster's.
#
# Root cause: `_apply_aura_effect` searched only `target_player.graveyard`.
# Fix: search all players' graveyards, starting with the caster's.
# ---------------------------------------------------------------------------

def test_bug2_animate_dead_targets_casters_own_graveyard(all_cards):
    """Animate Dead reanimates a creature from the caster's own graveyard."""
    animate = _get(all_cards, "Animate Dead")
    bear = _mk_card("Dead Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[animate], graveyard=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Animate Dead", target_player_index=0)

    assert result.supported
    assert any(perm.card.name == "Dead Bear" for perm in p1.battlefield)


def test_bug2_animate_dead_targets_opponents_graveyard(all_cards):
    """Bug 2 regression: Animate Dead must also work when the creature is in the
    opponent's graveyard (caster has no creature in their own graveyard)."""
    animate = _get(all_cards, "Animate Dead")
    big_bear = _mk_card("Big Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[animate])
    p2 = PlayerState(name="P2", graveyard=[big_bear])
    game = Game(players=[p1, p2])

    # Bug was: cast failed with "no valid target" because only p1's graveyard was checked
    result = game.cast_from_hand(0, "Animate Dead", target_player_index=1)

    assert result.supported, f"Expected success; got: {result.details}"
    # Revived creature should land on the caster's battlefield
    assert any(perm.card.name == "Big Bear" for perm in p1.battlefield)


# ---------------------------------------------------------------------------
# Bug 3: Circle of Protection — prevention pool applied to the wrong player
#
# Root cause: `grant_prevention_shield` added the prevention to `target`
# (opponent by default) instead of `caster` (controller of the CoP).
# Fix: when `source_permanent is not None` (activated ability), use `caster`.
# ---------------------------------------------------------------------------

def test_bug3_cop_activation_protects_controller(all_cards):
    """Activating Circle of Protection must add to the *controller's* prevention pool."""
    cop = _get(all_cards, "Circle of Protection: Red")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: Red", target_player_index=0)

    assert result.supported
    # Prevention must be on P1 (the controller), NOT on P2
    assert p1.damage_prevention_pool == 1
    assert p2.damage_prevention_pool == 0


def test_bug3_cop_activation_does_not_protect_opponent(all_cards):
    """Bug 3 regression: CoP activation must not add to the opponent's prevention pool."""
    cop = _get(all_cards, "Circle of Protection: White")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Even if target_player_index is explicitly the opponent, shield goes to controller
    game.activate_permanent_ability(0, "Circle of Protection: White", target_player_index=1)

    assert p1.damage_prevention_pool == 1, "Controller should have prevention"
    assert p2.damage_prevention_pool == 0, "Opponent must NOT have prevention (bug 3 guard)"


# ---------------------------------------------------------------------------
# Bug 4: Alpha Strike / attacker selection — summoning-sick creatures and
#         "can't attack" creatures were included in valid attacker lists.
#
# The engine's `can_attack` already respected summoning sickness; this test
# documents that behavior and guards against regressions.
# ---------------------------------------------------------------------------

def test_bug4_summoning_sick_creature_cannot_attack(all_cards):
    """A creature that entered the battlefield this turn cannot attack (summoning sickness)."""
    grizzly = _mk_card("Grizzly Bears", "Creature — Bear")
    perm = Permanent(card=grizzly)

    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Set summoning sickness to the current turn
    perm.metadata["summoning_sickness_turn"] = game.turn

    assert not game.can_attack(perm, 1), "Summoning-sick creature must not be able to attack"


def test_summoning_sickness_persists_through_opponents_turn(all_cards):
    """Sickness must clear at the controller's *own* next turn, not the opponent's.

    Regression: ``_is_summoning_sick`` compared the marker to the global turn
    counter, which advances every player's turn. A creature P1 played on turn 1
    therefore looked non-sick on turn 2 (P2's turn) — a full turn early. The
    untap-step re-stamp keeps the marker aligned so the creature stays sick until
    P1's next turn (turn 3).
    """
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    perm = Permanent(card=bear)
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Turn 1: P1 plays the bear.
    game.turn = 1
    game._initialize_permanent_state(perm, 0, None)
    assert game._is_summoning_sick(perm), "sick on the turn it entered"

    # Turn 2: P2's untap step. P1's bear is still summoning sick.
    game.turn = 2
    game.resolve_untap_step(1)
    assert game._is_summoning_sick(perm), "still sick during the opponent's turn"

    # Turn 3: P1's own untap step clears the sickness.
    game.turn = 3
    game.resolve_untap_step(0)
    assert not game._is_summoning_sick(perm), "sickness clears on the controller's next turn"


def test_bug4_creature_without_sickness_can_attack(all_cards):
    """A creature that has been in play since last turn can attack freely."""
    wolf = _mk_card("Timber Wolves", "Creature — Wolf")
    perm = Permanent(card=wolf)

    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # No summoning_sickness_turn set  → creature has been in play for a full turn
    assert game.can_attack(perm, 1), "Non-sick creature must be able to attack"


def test_bug4_cant_attack_creature_is_excluded(all_cards):
    """A creature with a 'can't attack' instruction cannot be declared as attacker."""
    cant_atk = _mk_card(
        "Pacifist Bear",
        "Creature — Bear",
        oracle_text="This creature can't attack.",
    )
    perm = Permanent(card=cant_atk)

    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert not game.can_attack(perm, 1), "cant_attack creature must not be allowed to attack"


# ---------------------------------------------------------------------------
# Bug 5: Banding — grant_banding_to_target should apply to the caster's own
#         creatures, not the opponent's creatures.
#
# Example card: Helm of Chatzuk — "{T}: Target creature gains banding until
# end of turn."
# ---------------------------------------------------------------------------

def test_bug5_banding_granted_to_casters_own_creature(all_cards):
    """Bug 5 regression: banding should be applied to the caster's own creature."""
    helm = _get(all_cards, "Helm of Chatzuk")
    own_bear = _mk_card("Own Bear", "Creature — Bear")
    opp_bear = _mk_card("Opp Bear", "Creature — Bear")

    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=helm), Permanent(card=own_bear)],
    )
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=opp_bear)])
    game = Game(players=[p1, p2])

    # Activating with target_player_index=0 (own side)
    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=0)

    assert result.supported
    # Own Bear should gain banding, opponent's Bear should not
    assert p1.battlefield[1].metadata.get("gains_banding_until_eot") is True
    assert not p2.battlefield[0].metadata.get("gains_banding_until_eot")


def test_bug5_banding_not_granted_to_opponent(all_cards):
    """Activating Helm of Chatzuk must NOT grant banding to the opponent's creature."""
    helm = _get(all_cards, "Helm of Chatzuk")
    own_bear = _mk_card("My Bear", "Creature — Bear")
    opp_bear = _mk_card("Their Bear", "Creature — Bear")

    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=helm), Permanent(card=own_bear)],
    )
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=opp_bear)])
    game = Game(players=[p1, p2])

    # The old bug used target_player_index to route banding to the opponent
    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=1)

    assert result.supported
    # Banding should still go to P1's bear (the controller's own creature)
    assert p1.battlefield[1].metadata.get("gains_banding_until_eot") is True
    # Opponent's creature should NOT have banding
    assert not p2.battlefield[0].metadata.get("gains_banding_until_eot"), (
        "Bug 5 regression: banding must not be granted to opponent"
    )


# ---------------------------------------------------------------------------
# Bug 6: Sleight of Mind — unable to choose a replacement color.
#
# Root cause: `mark_text_modified` only marked `text_modified = True` with no
# actual color change. Fix: thread `new_color` through StackItem →
# OracleExecutionContext and call `_apply_color_override` in the handler.
# ---------------------------------------------------------------------------

def test_bug6_sleight_of_mind_applies_color_override(all_cards):
    """Bug 6 regression: casting Sleight of Mind with new_color must change the
    target permanent's color via color_override metadata."""
    sleight = _get(all_cards, "Sleight of Mind")
    blue_enchantment = _mk_card(
        "Blue Ward",
        "Enchantment",
        oracle_text="Blue Ward gives target creature protection from blue.",
        colors=("U",),
    )

    p1 = PlayerState(name="P1", hand=[sleight])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=blue_enchantment)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0,
        "Sleight of Mind",
        target_player_index=1,
        target_permanent_index=0,
        new_color="R",
    )

    assert result.supported
    # The target permanent should have its color overridden to Red
    assert p2.battlefield[0].metadata.get("color_override") == "R", (
        "Bug 6 regression: color_override must be set to new_color"
    )


def test_bug6_sleight_of_mind_without_color_resolves_gracefully(all_cards):
    """Casting Sleight of Mind without a new_color should resolve without error."""
    sleight = _get(all_cards, "Sleight of Mind")
    any_perm = _mk_card("Test Perm", "Enchantment")

    p1 = PlayerState(name="P1", hand=[sleight])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=any_perm)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sleight of Mind", target_player_index=1)

    assert result.supported


# ---------------------------------------------------------------------------
# Bug 7: Victory / Defeat — game did not check for a winner after combat
#         damage, so the game ended without showing a result.
#
# The engine calls `check_state_based_actions` after combat damage resolution
# (combat.py). These tests verify that `player.lost` is set correctly when
# life drops to ≤ 0, and that `is_game_over()` returns True.
# ---------------------------------------------------------------------------

def test_bug7_check_sba_sets_player_lost_at_zero_life():
    """704.5a: check_state_based_actions must set player.lost when life drops to ≤ 0."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Simulate lethal damage after game creation (mirrors combat damage flow)
    p1.life = 0
    changed = game.check_state_based_actions()

    assert changed
    assert p1.lost is True
    assert p2.lost is False


def test_bug7_is_game_over_after_lethal_damage():
    """Bug 7 regression: is_game_over() must return True after a player's life hits 0."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    p2.life = 0
    game.check_state_based_actions()

    assert game.is_game_over() is True
    assert game.get_winner() is p1


def test_bug7_draw_when_both_players_lose_simultaneously():
    """104.4a: if all players lose at the same time, the game is a draw."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    p1.life = 0
    p2.life = 0
    game.check_state_based_actions()

    assert game.is_game_over() is True
    assert game.is_draw is True
    assert game.get_winner() is None


# ---------------------------------------------------------------------------
# Bug 8: creatures with 0 toughness must die to state-based actions
#
# Root cause: the 704.5f check in check_state_based_actions used a strict
# `effective_toughness < 0` comparison, so a creature that entered the
# battlefield with 0 toughness (or was reduced to exactly 0) survived.
# CR 704.5f: a creature with toughness 0 or less is put into its owner's
# graveyard.
# ---------------------------------------------------------------------------

def _mk_creature(name: str, power: int, toughness: int) -> CardDefinition:
    type_line = "Creature - Test"
    raw = {"name": name, "type_line": type_line, "power": str(power), "toughness": str(toughness)}
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw=raw,
    )


def test_bug8_creature_entering_with_zero_toughness_dies():
    """A creature cast with 0 toughness must go straight to the graveyard (704.5f)."""
    zero = _mk_creature("Zero Born", 0, 0)
    p1 = PlayerState(name="P1", hand=[zero])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Zero Born")

    assert result.supported
    assert not any(perm.card.name == "Zero Born" for perm in p1.battlefield)
    assert any(card.name == "Zero Born" for card in p1.graveyard)


def test_bug8_creature_reduced_to_zero_toughness_dies():
    """A creature whose toughness is reduced to exactly 0 dies on the next SBA check."""
    bear = _mk_creature("Test Bear", 2, 2)
    perm = Permanent(card=bear)
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    perm.toughness_bonus = -2
    changed = game.check_state_based_actions()

    assert changed
    assert not p1.battlefield
    assert any(card.name == "Test Bear" for card in p1.graveyard)


def test_bug8_creature_with_positive_toughness_survives():
    """Sanity check: the <= 0 fix must not kill creatures with toughness 1+."""
    bear = _mk_creature("Test Bear", 2, 2)
    perm = Permanent(card=bear)
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    perm.toughness_bonus = -1
    game.check_state_based_actions()

    assert perm in p1.battlefield
