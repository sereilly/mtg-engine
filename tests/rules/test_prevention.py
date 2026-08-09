"""Tests for Magic: The Gathering Comprehensive Rules Section 615.

Covers:
  615.1  — Prevention effects act as shields around a player or permanent
  615.5  — A prevention effect may carry an additional effect referring to the
           amount prevented (Reverse Damage's life gain)
  615.7  — Numeric shields ("prevent the next N damage") reduce by 1 per point;
           the remainder is dealt normally
  615.8  — "Next time a source would deal damage" shields prevent the whole
           instance, whatever its size
  615.9  — Source-property shields recheck the source; a non-matching source is
           not prevented and the shield is not used up
  614.7a — A 0-damage event has nothing to prevent, so no shield is consumed
  616.1  — When several shields apply to one event they are applied in sequence,
           each consumed at most once

These exercise engine/prevention.py, the registry that replaced the hardcoded
prevention cascade. The per-card end-to-end behavior (casting Reverse Damage,
activating a Circle of Protection, Forcefield in combat) is covered by the set
and regression suites; this file pins the rule semantics of the pipeline.
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.prevention import (
    PREVENTION_EFFECTS,
    apply_prevention,
    prevention_effect,
)


def _mk_creature(
    name: str, colors: tuple[str, ...] = (), power: int = 2, toughness: int = 2
) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Test",
        oracle_text="",
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


def _game() -> tuple[Game, PlayerState, PlayerState]:
    p1 = PlayerState(name="P1", life=20)
    p2 = PlayerState(name="P2", life=20)
    return Game(players=[p1, p2]), p1, p2


# ---------------------------------------------------------------------------
# Numeric shields (CR 615.7)
# ---------------------------------------------------------------------------

@pytest.mark.cr("615.1", "615.7")
def test_615_7_pool_prevents_up_to_its_size_and_the_rest_is_dealt():
    """A 2-point shield facing 5 damage prevents 2 and lets 3 through, and the
    shield is spent down to 0 rather than being consumed whole."""
    game, p1, _ = _game()
    p1.damage_prevention_pool = 2

    remaining = game._prevent_damage(p1, 5)

    assert remaining == 3
    assert p1.damage_prevention_pool == 0


@pytest.mark.cr("615.7")
def test_615_7_pool_larger_than_the_damage_keeps_its_remainder():
    """Preventing 1 damage reduces the shield by 1 — no more. The leftover
    shield stays available for later damage this turn."""
    game, p1, _ = _game()
    p1.damage_prevention_pool = 5

    assert game._prevent_damage(p1, 2) == 0
    assert p1.damage_prevention_pool == 3
    assert game._prevent_damage(p1, 3) == 0
    assert p1.damage_prevention_pool == 0


@pytest.mark.cr("615.7")
def test_615_7_the_same_shield_protects_a_creature():
    """"Prevent the next N damage that would be dealt to any target" can shield
    a creature instead of a player, and behaves identically. One registered
    interceptor serves both — permanents and players both carry the pool."""
    game, p1, _ = _game()
    bear = Permanent(card=_mk_creature("Bear"))
    p1.battlefield.append(bear)
    bear.damage_prevention_pool = 2

    marked = game._mark_damage_on_permanent(bear, 3)

    assert marked == 1
    assert bear.damage_marked == 1
    assert bear.damage_prevention_pool == 0


@pytest.mark.cr("615.7")
def test_615_7_exhausted_shield_clears_its_ui_source():
    """The badge naming the card that granted the shield is cleared with the
    shield itself, so a spent shield leaves no ghost badge behind."""
    game, p1, _ = _game()
    p1.damage_prevention_pool = 1
    p1.damage_prevention_source = "Healing Salve"

    game._prevent_damage(p1, 4)

    assert p1.damage_prevention_pool == 0
    assert p1.damage_prevention_source is None


# ---------------------------------------------------------------------------
# Whole-instance shields (CR 615.8, 615.5)
# ---------------------------------------------------------------------------

@pytest.mark.cr("615.8")
def test_615_8_chosen_source_shield_prevents_the_whole_instance():
    """Reverse Damage names a source, not an amount: the next instance from
    that source is prevented however large it is."""
    game, p1, p2 = _game()
    ogre = Permanent(card=_mk_creature("Ogre"))
    p2.battlefield.append(ogre)
    p1.reverse_damage_sources.append(ogre)

    assert game._prevent_damage(p1, 9, source=ogre) == 0
    assert p1.reverse_damage_sources == []


@pytest.mark.cr("615.8")
def test_615_8_subsequent_damage_from_the_same_source_is_dealt_normally():
    """Once the instance has been prevented the shield is gone — the same
    source's next hit lands in full."""
    game, p1, p2 = _game()
    ogre = Permanent(card=_mk_creature("Ogre"))
    p2.battlefield.append(ogre)
    p1.reverse_damage_sources.append(ogre)

    game._prevent_damage(p1, 4, source=ogre)

    assert game._prevent_damage(p1, 4, source=ogre) == 4


@pytest.mark.cr("615.5")
def test_615_5_prevention_happens_first_then_the_life_gain():
    """"Prevent that damage. You gain life equal to the damage prevented this
    way." The additional effect reads the amount actually prevented."""
    game, p1, p2 = _game()
    ogre = Permanent(card=_mk_creature("Ogre"))
    p2.battlefield.append(ogre)
    p1.reverse_damage_sources.append(ogre)

    game._prevent_damage(p1, 6, source=ogre)

    assert p1.life == 26


@pytest.mark.cr("615.8")
def test_615_8_a_different_source_does_not_consume_the_shield():
    """The shield waits for its own source; damage from anything else is dealt
    normally and the shield survives."""
    game, p1, p2 = _game()
    ogre = Permanent(card=_mk_creature("Ogre"))
    goblin = Permanent(card=_mk_creature("Goblin"))
    p2.battlefield.extend([ogre, goblin])
    p1.reverse_damage_sources.append(ogre)

    assert game._prevent_damage(p1, 3, source=goblin) == 3
    assert p1.reverse_damage_sources == [ogre]
    assert p1.life == 20


# ---------------------------------------------------------------------------
# Source-property shields (CR 615.9)
# ---------------------------------------------------------------------------

@pytest.mark.cr("615.9")
def test_615_9_color_shield_prevents_damage_from_a_matching_source():
    """A Circle of Protection shield is checked against the source's colors at
    the moment damage would be dealt, and prevents that damage entirely."""
    game, p1, p2 = _game()
    red_ogre = Permanent(card=_mk_creature("Red Ogre", colors=("R",)))
    p2.battlefield.append(red_ogre)
    p1.color_prevention_shields.append("R")

    assert game._prevent_damage(p1, 7, source=red_ogre) == 0
    assert p1.color_prevention_shields == []


@pytest.mark.cr("615.9")
def test_615_9_non_matching_source_is_not_prevented_and_the_shield_survives():
    """If the source's properties don't match, the damage isn't prevented and
    the shield isn't used up."""
    game, p1, p2 = _game()
    green_bear = Permanent(card=_mk_creature("Green Bear", colors=("G",)))
    p2.battlefield.append(green_bear)
    p1.color_prevention_shields.append("R")

    assert game._prevent_damage(p1, 3, source=green_bear) == 3
    assert p1.color_prevention_shields == ["R"]


# ---------------------------------------------------------------------------
# No event to prevent (CR 614.7a)
# ---------------------------------------------------------------------------

@pytest.mark.cr("614.7a")
def test_614_7a_zero_damage_consumes_no_shield():
    """A source that would deal 0 damage deals no damage at all, so there is no
    event for any shield to apply to — none of them are spent."""
    game, p1, p2 = _game()
    red_ogre = Permanent(card=_mk_creature("Red Ogre", colors=("R",)))
    p2.battlefield.append(red_ogre)
    p1.damage_prevention_pool = 3
    p1.color_prevention_shields.append("R")
    p1.reverse_damage_charges = 1

    assert game._prevent_damage(p1, 0, source=red_ogre) == 0
    assert p1.damage_prevention_pool == 3
    assert p1.color_prevention_shields == ["R"]
    assert p1.reverse_damage_charges == 1


# ---------------------------------------------------------------------------
# Several shields on one event (CR 616.1)
# ---------------------------------------------------------------------------

@pytest.mark.cr("616.1")
def test_616_1_multiple_shields_apply_in_sequence_to_one_event():
    """A cap and a numeric shield both apply to the same damage: the cap takes
    the event down to 1, then the shield absorbs that last point. Each is
    consumed exactly once."""
    game, p1, p2 = _game()
    attacker = Permanent(card=_mk_creature("Attacker"))
    p2.battlefield.append(attacker)
    p1.combat_damage_cap_one_charges = 1
    p1.damage_prevention_pool = 5

    assert game._prevent_damage(p1, 6, source=attacker) == 0
    assert p1.combat_damage_cap_one_charges == 0
    assert p1.damage_prevention_pool == 4


@pytest.mark.cr("616.1")
def test_616_1_a_shield_is_not_spent_on_damage_already_prevented():
    """Once nothing is left to prevent, no further shield applies — a
    whole-instance shield does not also drain the numeric pool behind it."""
    game, p1, p2 = _game()
    red_ogre = Permanent(card=_mk_creature("Red Ogre", colors=("R",)))
    p2.battlefield.append(red_ogre)
    p1.color_prevention_shields.append("R")
    p1.damage_prevention_pool = 4

    assert game._prevent_damage(p1, 3, source=red_ogre) == 0
    assert p1.damage_prevention_pool == 4


# ---------------------------------------------------------------------------
# Registry invariants
# ---------------------------------------------------------------------------

@pytest.mark.cr("616.1")
def test_616_1_prevention_order_is_total_and_unambiguous():
    """Which shield is consumed first is a rules-visible decision, so the
    registry must impose one unambiguous order — no two shields may share an
    order, and a collision fails at import rather than as a rare misplay."""
    orders = [order for order, _ in PREVENTION_EFFECTS]
    assert orders == sorted(orders)
    assert len(orders) == len(set(orders)), "two prevention effects share an order"

    with pytest.raises(ValueError, match="already used"):
        prevention_effect(orders[0])(lambda game, event: None)

    assert [order for order, _ in PREVENTION_EFFECTS] == orders, (
        "a rejected registration must not be added to the table"
    )


# ---------------------------------------------------------------------------
# Blanket combat shields (CR 510.2, 615.1a)
# ---------------------------------------------------------------------------

def _blocked_combat(shield_setup=None) -> tuple[Game, Permanent, Permanent, PlayerState]:
    """A 2/2 attacker blocked by a 3/3, stopped just before combat damage so a
    shield can be armed while the event is still upcoming (CR 615.4)."""
    attacker = Permanent(card=_mk_creature("Attacker", power=2, toughness=2))
    blocker = Permanent(card=_mk_creature("Blocker", power=3, toughness=3))
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    game.declare_attackers(0, [0])
    game.advance_combat_phase()  # declare_blockers
    game.declare_blockers(1, {0: 0})
    if shield_setup is not None:
        shield_setup(game, attacker, blocker)
    game.advance_combat_phase()  # combat damage (auto-resolves: one blocker)
    return game, attacker, blocker, p2


@pytest.mark.cr("510.2")
def test_510_2_unshielded_combat_deals_damage_both_ways():
    """The control for the shield tests below: with no shield armed, the 2/2
    and the 3/3 both mark damage. Without this, a harness that quietly stopped
    resolving combat damage would make every shield test pass vacuously."""
    _game_, attacker, blocker, _p2 = _blocked_combat(None)

    assert attacker.damage_marked == 3
    assert blocker.damage_marked == 2


@pytest.mark.cr("510.2", "615.1")
def test_615_1_fog_prevents_combat_damage_in_both_directions():
    """Fog: "Prevent all combat damage that would be dealt this turn." Nothing
    assigned in the combat damage step is dealt."""

    def arm(game, attacker, blocker):
        game.combat_damage_prevented_until_eot = True

    _game_, attacker, blocker, _p2 = _blocked_combat(arm)

    assert attacker.damage_marked == 0
    assert blocker.damage_marked == 0


@pytest.mark.cr("615.1a")
def test_615_1a_fog_does_not_prevent_noncombat_damage():
    """Fog names *combat* damage, so a burn spell resolving under it is dealt
    in full. The shields share one registry, so this scoping is what keeps a
    combat-only effect out of every other damage event."""
    game, p1, _ = _game()
    bear = Permanent(card=_mk_creature("Bear"))
    p1.battlefield.append(bear)
    game.combat_damage_prevented_until_eot = True

    assert game._mark_damage_on_permanent(bear, 3) == 3
    assert game._prevent_damage(p1, 3) == 3


@pytest.mark.cr("510.2", "615.1")
def test_615_1_creature_shield_prevents_damage_dealt_to_and_by_it():
    """Ebony Horse: "Prevent all combat damage that would be dealt to and dealt
    by that creature this turn." One shield, both directions — the shielded
    creature takes none and deals none."""

    def arm(game, attacker, blocker):
        attacker.metadata["prevent_combat_damage_to_and_by_until_eot"] = True

    _game_, attacker, blocker, _p2 = _blocked_combat(arm)

    assert attacker.damage_marked == 0, "damage dealt to the shielded creature"
    assert blocker.damage_marked == 0, "damage dealt by the shielded creature"


@pytest.mark.cr("615.1a")
def test_615_1a_creature_combat_shield_does_not_prevent_noncombat_damage():
    """The same shield says "combat damage", so a Lightning Bolt still burns
    the creature it protects."""
    game, p1, _ = _game()
    bear = Permanent(card=_mk_creature("Bear"))
    p1.battlefield.append(bear)
    bear.metadata["prevent_combat_damage_to_and_by_until_eot"] = True

    assert game._mark_damage_on_permanent(bear, 3) == 3


@pytest.mark.cr("616.1")
def test_616_1_blanket_shield_does_not_spend_a_consumable_shield():
    """A blanket combat shield is a flag, not a charge. It applies first so the
    player's one-shot shields survive damage that was never going to land."""
    game, p1, p2 = _game()
    attacker = Permanent(card=_mk_creature("Attacker"))
    p2.battlefield.append(attacker)
    game.combat_damage_prevented_until_eot = True
    p1.damage_prevention_pool = 4
    p1.reverse_damage_charges = 1

    assert game._prevent_damage(p1, 3, source=attacker, combat=True) == 0
    assert p1.damage_prevention_pool == 4
    assert p1.reverse_damage_charges == 1
    assert p1.life == 20, "a prevented event carries no life gain rider"


@pytest.mark.cr("615.1")
def test_615_1_shields_apply_to_players_and_permanents_through_one_pipeline():
    """Prevention is one pipeline over a recipient, not two parallel cascades:
    the same call shields a player and a permanent, and shields that only make
    sense for a player decline a permanent rather than crashing on it."""
    game, p1, _ = _game()
    bear = Permanent(card=_mk_creature("Bear"))
    p1.battlefield.append(bear)
    bear.damage_prevention_pool = 2
    p1.damage_prevention_pool = 2
    p1.reverse_damage_charges = 1

    assert apply_prevention(game, {"recipient": bear, "amount": 3, "source": None}) == 1
    assert apply_prevention(game, {"recipient": p1, "amount": 3, "source": None}) == 0
    # The player-only shield took the player's event and left the creature's
    # pool to do the work on the creature's.
    assert p1.reverse_damage_charges == 0
    assert p1.damage_prevention_pool == 2
