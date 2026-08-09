"""Tests for Magic: The Gathering Comprehensive Rules Section 611/613.

Covers:
  611.3  — a continuous effect from a permanent ends when it leaves
  613.7b — an effect is timestamped when it starts applying

An Aura's static P/T grant used to be *applied once* into the enchanted
creature's ``power_bonus``, with the delta recorded on the Aura and subtracted
again on removal. That is the shape that shipped the Aspect of Wolf compounding
bug (tests/regressions/test_batch17.py): a subtraction that does not exactly
match its addition compounds on every recompute, and CR 611.3a means the
recompute runs constantly.

It is now derived from the Aura's own text on every recompute
(``auras.aura_static_pt_grant``, collected by ``layer_bridge`` at layer 7c), so
detaching the Aura is simply ceasing to contribute.
"""

import pytest

from engine import Game, PlayerState
from engine.auras import aura_static_pt_grant, auras_attached_to
from engine.card_loader import load_catalog
from engine.models import Permanent


@pytest.fixture(scope="module")
def catalog():
    return {c.name: c for c in load_catalog()}


def _bear_with_auras(catalog, *aura_names):
    bear = Permanent(card=catalog["Grizzly Bears"])
    player = PlayerState(
        name="P1", hand=[catalog[n] for n in aura_names], battlefield=[bear]
    )
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    for name in aura_names:
        game.cast_from_hand(0, name, target_player_index=0, target_permanent_index=0)
    return game, player, bear


@pytest.mark.cr("613.1g")
def test_613_1g_an_aura_never_writes_into_the_creatures_own_pt_channel(catalog):
    """The invariant the refactor buys: the Aura contributes, it does not
    mutate. ``power_bonus`` holds counters and one-shot boosts, which belong to
    the creature and must survive the Aura leaving."""
    game, _, bear = _bear_with_auras(catalog, "Holy Strength", "Unholy Strength")

    assert (bear.effective_power, bear.effective_toughness) == (5, 5)
    assert bear.power_bonus == 0
    assert bear.toughness_bonus == 0


@pytest.mark.cr("613.7b")
def test_613_7b_each_aura_is_timestamped_when_it_becomes_attached(catalog):
    """Every Aura's contribution used to be read out of one metadata channel
    with a single shared derived timestamp, so two Auras had no order relative
    to each other. Addition commutes, so that was invisible — until a layer-7c
    effect that does not commute meets one."""
    game, player, bear = _bear_with_auras(catalog, "Holy Strength", "Unholy Strength")
    auras = [p for p in player.battlefield if "Aura" in p.card.type_line]

    stamps = [a.metadata["aura_timestamp"] for a in auras]
    assert len(set(stamps)) == 2, stamps
    # Attach order is timestamp order (613.7b).
    assert stamps == sorted(stamps)


@pytest.mark.cr("611.3")
def test_611_3_removing_one_aura_leaves_the_others_contribution(catalog):
    game, player, bear = _bear_with_auras(catalog, "Holy Strength", "Unholy Strength")
    holy = next(p for p in player.battlefield if p.card.name == "Holy Strength")

    game._remove_aura_effects(holy)
    player.battlefield.remove(holy)
    game._refresh_dynamic_creatures()

    # 2/2 base + Unholy Strength's +2/+1.
    assert (bear.effective_power, bear.effective_toughness) == (4, 3)
    assert [a.card.name for a in auras_attached_to(bear)] == ["Unholy Strength"]


@pytest.mark.cr("611.3")
def test_611_3_counters_survive_the_aura_leaving(catalog):
    """The separation that the shared channel made impossible: a +1/+1 counter
    put on the creature while an Aura is attached belongs to the creature."""
    game, player, bear = _bear_with_auras(catalog, "Unholy Strength")
    bear.power_bonus += 1
    bear.toughness_bonus += 1
    game._refresh_dynamic_creatures()
    assert (bear.effective_power, bear.effective_toughness) == (5, 4)

    unholy = next(p for p in player.battlefield if p.card.name == "Unholy Strength")
    game._remove_aura_effects(unholy)
    player.battlefield.remove(unholy)
    game._refresh_dynamic_creatures()

    assert (bear.effective_power, bear.effective_toughness) == (3, 3)


@pytest.mark.cr("611.3")
def test_611_3_detaching_one_aura_does_not_detach_the_others(catalog):
    """``aura_granted_meta`` records "every key that appeared on the target
    while this Aura attached" and pops them on removal — which swept up the
    attachment list itself and detached every other Aura. A capture-anything
    heuristic will keep finding new things to eat; this pins the case found."""
    game, player, bear = _bear_with_auras(catalog, "Holy Strength", "Unholy Strength")
    holy = next(p for p in player.battlefield if p.card.name == "Holy Strength")

    game._remove_aura_effects(holy)

    remaining = auras_attached_to(bear)
    assert len(remaining) == 1
    assert remaining[0].card.name == "Unholy Strength"


@pytest.mark.cr("613.1g")
def test_613_1g_the_grant_is_read_from_the_auras_text_not_remembered():
    """Derivation, not bookkeeping: the value comes from the card every time."""
    assert aura_static_pt_grant("Enchant creature\nEnchanted creature gets +1/+2.") == (1, 2)
    assert aura_static_pt_grant("Enchant creature\nEnchanted creature gets -2/-1.") == (-2, -1)
    # An activated ability the Aura grants is not a static grant: it applies
    # when activated, not while attached.
    assert aura_static_pt_grant(
        "Enchant creature\n{R}: Enchanted creature gets +1/+0 until end of turn."
    ) is None
    assert aura_static_pt_grant("Enchant creature\nEnchanted creature has flying.") is None


def _nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


@pytest.mark.cr("613.1f")
def test_613_1f_an_aura_keyword_grant_is_a_layer_6_effect(catalog):
    """Keyword grants follow the P/T grant: derived from the Aura, stamped when
    it attached, gone when it leaves. They used to be written onto the creature
    and undone by popping remembered metadata keys."""
    game, player, bear = _bear_with_auras(catalog, "Flight", "Web")

    assert game._has_keyword(bear, "flying") is True
    assert game._has_keyword(bear, "reach") is True
    assert (bear.effective_power, bear.effective_toughness) == (2, 4)  # Web's +0/+2

    flight = next(p for p in player.battlefield if p.card.name == "Flight")
    game._remove_aura_effects(flight)
    player.battlefield.remove(flight)
    game._refresh_dynamic_creatures()

    # Only Flight's grant ends; Web's keyword and P/T both survive.
    assert game._has_keyword(bear, "flying") is False
    assert game._has_keyword(bear, "reach") is True
    assert (bear.effective_power, bear.effective_toughness) == (2, 4)


@pytest.mark.cr("702.14b")
def test_702_14b_aura_granted_landwalk_works_and_ends_through_combat(catalog):
    """Landwalk is a keyword like any other now. The combat check reads
    *computed* abilities, so it never learns an Aura exists — where it used to
    read a `has_<walk>` flag the Aura stamped directly, which is what kept the
    grant outside the layer system."""
    attacker = _nosick(Permanent(card=catalog["Grizzly Bears"]))
    blocker = _nosick(Permanent(card=catalog["Grizzly Bears"]))
    p1 = PlayerState(name="P1", hand=[catalog["Burrowing"]], battlefield=[attacker])
    p2 = PlayerState(
        name="P2", battlefield=[blocker, Permanent(card=catalog["Mountain"])]
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    assert game._can_block_attacker(blocker, attacker) is True

    game.cast_from_hand(0, "Burrowing", target_player_index=0, target_permanent_index=0)
    assert game._has_keyword(attacker, "mountainwalk") is True
    # Defender controls a Mountain, so mountainwalk makes it unblockable.
    assert game._can_block_attacker(blocker, attacker) is False

    burrowing = next(p for p in p1.battlefield if p.card.name == "Burrowing")
    game._remove_aura_effects(burrowing)
    p1.battlefield.remove(burrowing)
    game._refresh_dynamic_creatures()

    assert game._can_block_attacker(blocker, attacker) is True


@pytest.mark.cr("613.1f")
def test_613_1f_a_granted_quoted_ability_is_not_claimed_as_a_keyword(catalog):
    """Farmstead grants an ability in quotes and the Wards grant protection.
    Neither is a keyword, and claiming them here would say the layer-6 grant
    carries them when it does not."""
    from engine.auras import aura_keyword_grants

    assert aura_keyword_grants(catalog["Farmstead"].oracle_text) == ()
    assert aura_keyword_grants(catalog["White Ward"].oracle_text) == ()
    # Consecrate Land's line carries two effects. The keyword half is claimed
    # here and the trailing clause separately as a restriction, so the compound
    # is fully accounted for rather than half-matched.
    assert aura_keyword_grants(catalog["Consecrate Land"].oracle_text) == ("indestructible",)


@pytest.mark.cr("509.1b")
def test_509_1b_invisibility_restricts_blockers_only_while_attached(catalog):
    """Restrictions are not characteristics, so CR 613's layers do not apply —
    but the ownership does. The reader asks which Auras are attached now
    instead of the Aura stamping a flag someone must remember to clear."""
    attacker = _nosick(Permanent(card=catalog["Grizzly Bears"]))
    blocker = _nosick(Permanent(card=catalog["Grizzly Bears"]))
    p1 = PlayerState(name="P1", hand=[catalog["Invisibility"]], battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    assert game._can_block_attacker(blocker, attacker) is True

    game.cast_from_hand(0, "Invisibility", target_player_index=0, target_permanent_index=0)
    assert game._can_block_attacker(blocker, attacker) is False

    aura = next(p for p in p1.battlefield if p.card.name == "Invisibility")
    game._remove_aura_effects(aura)
    p1.battlefield.remove(aura)
    assert game._can_block_attacker(blocker, attacker) is True


@pytest.mark.cr("508.1a")
def test_508_1a_animate_wall_permission_ends_with_the_aura(catalog):
    wall = _nosick(Permanent(card=catalog["Wall of Stone"]))
    p1 = PlayerState(name="P1", hand=[catalog["Animate Wall"]], battlefield=[wall])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    assert game.can_attack(wall, 1) is False
    game.cast_from_hand(0, "Animate Wall", target_player_index=0, target_permanent_index=0)
    assert game.can_attack(wall, 1) is True

    aura = next(p for p in p1.battlefield if p.card.name == "Animate Wall")
    game._remove_aura_effects(aura)
    p1.battlefield.remove(aura)
    assert game.can_attack(wall, 1) is False


@pytest.mark.cr("702.16c")
def test_702_16c_ward_protection_ends_with_the_aura(catalog):
    game, player, bear = _bear_with_auras(catalog, "Black Ward")
    assert "B" in game._protection_colors(bear)

    ward = next(p for p in player.battlefield if p.card.name == "Black Ward")
    game._remove_aura_effects(ward)
    player.battlefield.remove(ward)

    assert "B" not in game._protection_colors(bear)


@pytest.mark.cr("702.16c")
def test_702_16c_protection_granted_outside_an_aura_still_counts(catalog):
    """The metadata channel stays for protection granted with a lifetime of its
    own. Deleting it because no card in the pool uses it would have made
    CR 702.16c depend on the protection's *source*, which the rule does not."""
    bear = Permanent(card=catalog["Grizzly Bears"])
    player = PlayerState(name="P1", battlefield=[bear])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    bear.metadata["protection_from_white"] = True
    assert "W" in game._protection_colors(bear)


@pytest.mark.cr("502.1")
def test_502_1_paralyze_untap_restriction_is_read_from_the_aura(catalog):
    from engine.auras import aura_restriction_active

    assert "doesnt_untap" in __import__(
        "engine.auras", fromlist=["aura_restrictions"]
    ).aura_restrictions(catalog["Paralyze"].oracle_text)

    bear = Permanent(card=catalog["Grizzly Bears"], tapped=True)
    player = PlayerState(name="P1", hand=[catalog["Paralyze"]], battlefield=[bear])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Paralyze", target_player_index=0, target_permanent_index=0)

    assert aura_restriction_active(bear, "doesnt_untap") is True
    game.resolve_untap_step(0)
    assert bear.tapped is True          # held down by the Aura

    aura = next(p for p in player.battlefield if p.card.name == "Paralyze")
    game._remove_aura_effects(aura)
    player.battlefield.remove(aura)
    game.resolve_untap_step(0)
    assert bear.tapped is False         # and released the moment it leaves


@pytest.mark.cr("302.6", "702.10b")
def test_302_6_attack_as_though_hasty_does_not_permit_tap_abilities(catalog):
    """Instill Energy says "can attack as though it had haste" — it does not
    grant haste.

    CR 302.6 has two clauses: a summoning-sick creature can't attack, and can't
    activate a {T} ability. CR 702.10b says haste lifts *the attack clause*.
    This wording lifts the same one clause and no more. Modelling it as a haste
    grant lifted both, so a summoning-sick Llanowar Elves under Instill Energy
    tapped for mana a turn early.
    """
    elves = Permanent(card=catalog["Llanowar Elves"])
    player = PlayerState(
        name="P1", hand=[catalog["Instill Energy"]], battlefield=[elves]
    )
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    elves.metadata["summoning_sickness_turn"] = game.turn   # arrived this turn

    game.cast_from_hand(
        0, "Instill Energy", target_player_index=0, target_permanent_index=0
    )

    assert game.can_attack(elves, 1) is True          # the clause it does lift
    assert game._has_keyword(elves, "haste") is False  # it is not a haste grant
    result = game.activate_permanent_ability(0, "Llanowar Elves")
    assert result.supported is False                   # the clause it does not
    assert player.mana_pool["G"] == 0


@pytest.mark.cr("302.6")
def test_302_6_the_permission_ends_when_the_aura_leaves(catalog):
    elves = Permanent(card=catalog["Llanowar Elves"])
    player = PlayerState(
        name="P1", hand=[catalog["Instill Energy"]], battlefield=[elves]
    )
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    elves.metadata["summoning_sickness_turn"] = game.turn
    game.cast_from_hand(
        0, "Instill Energy", target_player_index=0, target_permanent_index=0
    )
    assert game.can_attack(elves, 1) is True

    aura = next(p for p in player.battlefield if p.card.name == "Instill Energy")
    game._remove_aura_effects(aura)
    player.battlefield.remove(aura)

    assert game.can_attack(elves, 1) is False
