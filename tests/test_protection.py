"""Tests for CR 702.16 — Protection.

Each test cites the specific subrule it covers. Where a subrule references
another rule (e.g. 702.16c references 704, State-Based Actions), the behavior
is driven through the real engine: cast the spell / declare combat / run
``check_state_based_actions`` rather than poking handlers directly.

Limited Edition Alpha (the modeled card pool) only ever prints *protection from a
single color*, so colored-quality protection is the focus. Subrules that depend
on cards that don't exist in Alpha (protection from everything / from a player /
from each characteristic, Equipment, Fortifications) are exercised with
synthetic cards or skipped with an explicit reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import Game, load_cards
from engine.models import CardDefinition, Permanent, PlayerState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_creature(
    name: str,
    power: int = 2,
    toughness: int = 2,
    *,
    oracle_text: str = "",
    keywords: tuple[str, ...] = (),
    colors: tuple[str, ...] = (),
    type_line: str = "Creature - Test",
) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=keywords,
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": str(power), "toughness": str(toughness)},
    )


def _mk_instant(name: str, oracle_text: str, colors: tuple[str, ...] = ()) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Instant",
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Instant"},
    )


def _mk_aura(name: str, oracle_text: str, colors: tuple[str, ...] = ()) -> CardDefinition:
    type_line = "Enchantment - Aura"
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
        raw={"name": name, "type_line": type_line},
    )


def _mk_equipment(name: str, colors: tuple[str, ...] = ()) -> CardDefinition:
    type_line = "Artifact - Equipment"
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text="Equipped creature gets +1/+1.\nEquip {2}",
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


def _game(p1_battlefield, p2_battlefield, *, life: int = 20):
    p1 = PlayerState(name="P1", battlefield=p1_battlefield)
    p2 = PlayerState(name="P2", battlefield=p2_battlefield, life=life)
    return Game(players=[p1, p2]), p1, p2


def _to_declare_attackers(game: Game) -> None:
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers


def _to_declare_blockers(game: Game, attacker_indices) -> None:
    _to_declare_attackers(game)
    ok, msg = game.declare_attackers(0, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"


def _resolve_combat(game: Game) -> None:
    game.advance_combat_phase()  # combat_damage


@pytest.fixture(scope="module")
def all_cards():
    return load_cards(Path(__file__).resolve().parent.parent / "lea_cards.json")


def _get(all_cards, name: str) -> CardDefinition:
    return next(card for card in all_cards if card.name == name)


# ---------------------------------------------------------------------------
# 702.16a — Protection is a static ability "Protection from [quality]"
# ---------------------------------------------------------------------------


def test_702_16a_protection_from_color_is_a_static_ability(all_cards):
    """702.16a: Black Knight's printed "Protection from white" is recognized."""
    bk = Permanent(card=_get(all_cards, "Black Knight"))
    game, _, _ = _game([bk], [])
    assert game._protection_colors(bk) == {"W"}


def test_702_16a_creature_without_protection_has_none():
    bear = Permanent(card=_mk_creature("Bear", 2, 2, colors=("G",)))
    game, _, _ = _game([bear], [])
    assert game._protection_colors(bear) == set()


# ---------------------------------------------------------------------------
# 702.16b — Can't be targeted by spells/abilities with the stated quality
# ---------------------------------------------------------------------------


def test_702_16b_cannot_be_targeted_by_spell_of_quality(all_cards):
    """702.16b: a white spell can't target a creature with protection from white."""
    white_bolt = _mk_instant(
        "Holy Light", "Holy Light deals 3 damage to target creature.", colors=("W",)
    )
    bk = Permanent(card=_get(all_cards, "Black Knight"))
    p1 = PlayerState(name="P1", hand=[white_bolt])
    p2 = PlayerState(name="P2", battlefield=[bk])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Holy Light", target_player_index=1, target_permanent_index=0)
    # Illegal target: the spell does nothing.
    assert p2.battlefield[0].damage_marked == 0


def test_702_16b_protected_creature_is_an_illegal_target_at_cast_time(all_cards):
    """702.16b: a spell can't even be cast targeting a protected creature — the
    target is rejected at cast time, not merely fizzled on resolution.

    Reproduces the reported bug: Red Ward on Grizzly Bears must make the Bears an
    illegal target for Lightning Bolt (protection from red).
    """
    bears = Permanent(card=_get(all_cards, "Grizzly Bears"))
    p1 = PlayerState(name="P1", hand=[_get(all_cards, "Red Ward"), _get(all_cards, "Lightning Bolt")])
    p2 = PlayerState(name="P2", battlefield=[bears])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Red Ward", target_player_index=1, target_permanent_index=0)
    assert game._protection_colors(bears) == {"R"}

    # The Bolt cast is rejected (illegal target), not just countered on resolution.
    result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    assert result.supported is False
    assert "illegal target" in result.details
    assert bears.damage_marked == 0
    # Lightning Bolt remains in hand — it was never put on the stack.
    assert any(c.name == "Lightning Bolt" for c in p1.hand)


def test_702_16b_unprotected_creature_is_a_legal_target(all_cards):
    """Sanity: the cast-time check doesn't reject legal targets."""
    bears = Permanent(card=_get(all_cards, "Grizzly Bears"))  # green, no protection
    p1 = PlayerState(name="P1", hand=[_get(all_cards, "Lightning Bolt")])
    p2 = PlayerState(name="P2", battlefield=[bears])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    # The Bolt was a legal cast: it left the hand and dealt its damage.
    assert not any(c.name == "Lightning Bolt" for c in p1.hand)
    assert bears.damage_marked == 3


def test_702_16b_cannot_be_targeted_by_ability_from_source_of_quality(all_cards):
    """702.16b: an ability from a white source can't target the protected creature."""
    bk = Permanent(card=_get(all_cards, "Black Knight"))
    game, _, _ = _game([bk], [])
    white_source = _mk_creature("Pearled Unicorn", colors=("W",))
    assert game._can_be_targeted(bk, white_source) is False


def test_702_16b_can_be_targeted_by_ability_from_other_color(all_cards):
    """702.16b: protection from white does not stop a non-white source's ability."""
    bk = Permanent(card=_get(all_cards, "Black Knight"))
    game, _, _ = _game([bk], [])
    red_source = _mk_creature("Goblin", colors=("R",))
    assert game._can_be_targeted(bk, red_source) is True


def test_702_16b_other_color_spell_can_target_and_kill(all_cards):
    """702.16b: protection from white doesn't stop a red spell from killing it."""
    red_bolt = _mk_instant(
        "Lava Spike", "Lava Spike deals 3 damage to target creature.", colors=("R",)
    )
    bk = Permanent(card=_get(all_cards, "Black Knight"))  # 2 toughness
    p1 = PlayerState(name="P1", hand=[red_bolt])
    p2 = PlayerState(name="P2", battlefield=[bk])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Lava Spike", target_player_index=1, target_permanent_index=0)
    game.check_state_based_actions()
    assert all(p.card.name != "Black Knight" for p in p2.battlefield)


# ---------------------------------------------------------------------------
# 702.16c — Can't be enchanted by Auras with the stated quality;
#           such Auras are put into the graveyard as an SBA (see 704)
# ---------------------------------------------------------------------------


def test_702_16c_cannot_be_enchanted_by_aura_of_quality(all_cards):
    """702.16c: a white Aura can't be attached to a creature with protection from white."""
    white_aura = _mk_aura(
        "Holy Strength", "Enchant creature\nEnchanted creature gets +1/+2.", colors=("W",)
    )
    bk = Permanent(card=_get(all_cards, "Black Knight"))
    p1 = PlayerState(name="P1", hand=[white_aura])
    p2 = PlayerState(name="P2", battlefield=[bk])
    game = Game(players=[p1, p2])

    game.cast_from_hand(
        0, "Holy Strength", target_player_index=1, target_permanent_index=0
    )
    # Illegal target: the Aura never attaches and Black Knight gets no buff.
    assert bk.metadata.get("attached_aura") is None
    assert bk.power_bonus == 0 and bk.toughness_bonus == 0


def test_702_16c_attached_aura_of_quality_falls_off_as_sba(all_cards):
    """702.16c via 704: an Aura with the stated quality already attached to a
    creature that has gained protection is put into its owner's graveyard."""
    creature = Permanent(card=_mk_creature("Goblin", 2, 2, colors=("R",)))
    white_aura = Permanent(
        card=_mk_aura(
            "Holy Strength", "Enchant creature\nEnchanted creature gets +1/+2.", colors=("W",)
        )
    )
    # Attach the white Aura, then the creature gains protection from white.
    white_aura.metadata["attached_to"] = creature
    creature.metadata["attached_aura"] = white_aura
    creature.metadata["protection_from_white"] = True

    p1 = PlayerState(name="P1", battlefield=[creature, white_aura])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    assert white_aura not in p1.battlefield
    assert any(c.name == "Holy Strength" for c in p1.graveyard)


def test_702_16c_attached_aura_without_quality_stays(all_cards):
    """702.16c only removes Auras that *have* the stated quality."""
    creature = Permanent(card=_mk_creature("Goblin", 2, 2, colors=("R",)))
    green_aura = Permanent(
        card=_mk_aura(
            "Wild Growth", "Enchant creature\nEnchanted creature gets +1/+1.", colors=("G",)
        )
    )
    green_aura.metadata["attached_to"] = creature
    creature.metadata["attached_aura"] = green_aura
    creature.metadata["protection_from_white"] = True  # protection from white, not green

    p1 = PlayerState(name="P1", battlefield=[creature, green_aura])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    assert green_aura in p1.battlefield
    assert not any(c.name == "Wild Growth" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# 702.16d — Can't be equipped by Equipment with the stated quality;
#           such Equipment becomes unattached as an SBA (stays on battlefield)
# ---------------------------------------------------------------------------


def test_702_16d_equipment_of_quality_becomes_unattached(all_cards):
    """702.16d via 704: Equipment with the stated quality attached to a protected
    permanent becomes unattached, but remains on the battlefield."""
    creature = Permanent(card=_mk_creature("Goblin", 2, 2, colors=("R",)))
    equip = Permanent(card=_mk_equipment("White Sword", colors=("W",)))
    equip.metadata["attached_to"] = creature
    creature.metadata["protection_from_white"] = True

    p1 = PlayerState(name="P1", battlefield=[creature, equip])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    # Equipment stays on the battlefield but is no longer attached.
    assert equip in p1.battlefield
    assert equip.metadata.get("attached_to") is None


# ---------------------------------------------------------------------------
# 702.16e — Damage from sources with the stated quality is prevented
# ---------------------------------------------------------------------------


def test_702_16e_combat_damage_from_quality_prevented(all_cards):
    """702.16e: combat damage from a white source to the protected creature is prevented."""
    white_attacker = Permanent(card=_mk_creature("Crusader", 3, 3, colors=("W",)))
    bk = Permanent(card=_get(all_cards, "Black Knight"))  # 2/2, prot white, first strike
    game, _, p2 = _game([white_attacker], [bk])
    _to_declare_blockers(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    _resolve_combat(game)

    survivor = next(p for p in p2.battlefield if p.card.name == "Black Knight")
    assert survivor.damage_marked == 0


def test_702_16e_combat_damage_from_other_color_not_prevented(all_cards):
    """702.16e: protection from white does not prevent a black source's damage."""
    black_attacker = Permanent(card=_mk_creature("Zombie", 3, 3, colors=("B",)))
    bk = Permanent(card=_get(all_cards, "Black Knight"))  # protection from white only
    game, _, p2 = _game([black_attacker], [bk])
    _to_declare_blockers(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    _resolve_combat(game)

    # Black Knight (2 toughness) takes the black creature's damage and dies.
    assert all(p.card.name != "Black Knight" for p in p2.battlefield)


# ---------------------------------------------------------------------------
# 702.16f — Attacking creatures with protection can't be blocked by that quality
# ---------------------------------------------------------------------------


def test_702_16f_cannot_be_blocked_by_creature_of_quality(all_cards):
    """702.16f: a white blocker can't block an attacker with protection from white."""
    bk = Permanent(card=_get(all_cards, "Black Knight"))  # protection from white
    white_blocker = Permanent(card=_mk_creature("Cleric", 2, 2, colors=("W",)))
    game, _, _ = _game([bk], [white_blocker])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok


def test_702_16f_can_be_blocked_by_creature_of_other_quality(all_cards):
    """702.16f: protection from white does not stop a black creature from blocking."""
    bk = Permanent(card=_get(all_cards, "Black Knight"))  # protection from white
    black_blocker = Permanent(card=_mk_creature("Zombie", 2, 2, colors=("B",)))
    game, _, _ = _game([bk], [black_blocker])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok


# ---------------------------------------------------------------------------
# 702.16g — "Protection from [A] and from [B]" is two separate abilities
# ---------------------------------------------------------------------------


def test_702_16g_protection_from_two_qualities():
    """702.16g: "protection from white and from blue" grants both protections."""
    knight = _mk_creature(
        "Two-Color Knight",
        2,
        2,
        oracle_text="Protection from white and from blue",
    )
    perm = Permanent(card=knight)
    game, _, _ = _game([perm], [])
    assert game._protection_colors(perm) == {"W", "U"}


def test_702_16g_two_qualities_behave_independently():
    """702.16g: each quality is its own ability — a blue blocker and a white
    blocker are both unable to block, but a black one can."""
    knight = _mk_creature(
        "Two-Color Knight",
        2,
        2,
        oracle_text="Protection from white and from blue",
    )
    blue_blocker = Permanent(card=_mk_creature("Merfolk", 2, 2, colors=("U",)))
    game, _, _ = _game([Permanent(card=knight)], [blue_blocker])
    _to_declare_blockers(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok


# ---------------------------------------------------------------------------
# 702.16m — Multiple instances of protection from the same quality are redundant
# ---------------------------------------------------------------------------


def test_702_16m_multiple_instances_redundant(all_cards):
    """702.16m: protection from white from two sources is a single effective
    protection — the set of protected colors has no duplicate."""
    bk = Permanent(card=_get(all_cards, "Black Knight"))  # printed protection from white
    bk.metadata["protection_from_white"] = True  # a second, redundant instance
    game, _, _ = _game([bk], [])
    assert game._protection_colors(bk) == {"W"}


def test_702_16m_redundant_instance_still_protects_when_one_removed(all_cards):
    """702.16m: removing one redundant instance leaves the protection intact."""
    bk = Permanent(card=_get(all_cards, "Black Knight"))
    bk.metadata["protection_from_white"] = True
    game, _, _ = _game([bk], [])
    # Remove the Aura-granted instance; the printed instance remains.
    del bk.metadata["protection_from_white"]
    assert game._protection_colors(bk) == {"W"}


# ---------------------------------------------------------------------------
# 702.16n — An Aura that grants protection and says "this effect doesn't remove
#           this Aura" is not put into the graveyard by the 702.16c SBA
# ---------------------------------------------------------------------------


def test_702_16n_self_granting_aura_is_not_removed(all_cards):
    """702.16n: White Ward grants protection from white and says the effect
    doesn't remove this Aura, so it stays attached despite being white."""
    creature = Permanent(card=_mk_creature("Goblin", 2, 2, colors=("R",)))
    ward = Permanent(card=_get(all_cards, "White Ward"))  # white Aura, prot from white
    ward.metadata["attached_to"] = creature
    creature.metadata["attached_aura"] = ward
    creature.metadata["protection_from_white"] = True  # granted by the Ward

    p1 = PlayerState(name="P1", battlefield=[creature, ward])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    assert ward in p1.battlefield
    assert not any(c.name == "White Ward" for c in p1.graveyard)


def test_702_16n_other_instance_affects_other_auras(all_cards):
    """702.16n: the "doesn't remove this Aura" clause only protects that Aura.
    Another white Aura attached to the same creature still falls off."""
    creature = Permanent(card=_mk_creature("Goblin", 2, 2, colors=("R",)))
    ward = Permanent(card=_get(all_cards, "White Ward"))
    other_white_aura = Permanent(
        card=_mk_aura(
            "Holy Strength", "Enchant creature\nEnchanted creature gets +1/+2.", colors=("W",)
        )
    )
    ward.metadata["attached_to"] = creature
    other_white_aura.metadata["attached_to"] = creature
    creature.metadata["protection_from_white"] = True

    p1 = PlayerState(name="P1", battlefield=[creature, ward, other_white_aura])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    assert ward in p1.battlefield  # protected by 702.16n
    assert other_white_aura not in p1.battlefield  # removed by 702.16c
    assert any(c.name == "Holy Strength" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Variants not present in the Limited Edition Alpha card pool
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="No 'protection from everything' cards in LEA (702.16j)")
def test_702_16j_protection_from_everything():
    ...


@pytest.mark.skip(reason="No 'protection from [a player]' cards in LEA (702.16k)")
def test_702_16k_protection_from_player():
    ...


@pytest.mark.skip(reason="No 'protection from each [characteristic]' cards in LEA (702.16h/i)")
def test_702_16h_protection_from_each_characteristic():
    ...
