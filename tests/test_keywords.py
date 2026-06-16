"""Tests for the keyword abilities surfaced by the web UI's ``_DISPLAY_KEYWORDS``.

Every keyword listed in :data:`web.app._DISPLAY_KEYWORDS` is exercised here against
the rule that defines it in the Comprehensive Rules section 702 ("Keyword
Abilities"). Each test cites the specific subrule it covers.

The keyword set under test (in display order):
    Flying, First Strike, Double Strike, Trample, Deathtouch, Reach, Vigilance,
    Haste, Defender, Banding, Fear, Lifelink, Shroud, Protection, Rampage,
    Flanking, Plainswalk, Islandwalk, Swampwalk, Mountainwalk, Forestwalk.

Combat tests are driven through the real engine (declare attackers, declare
blockers, resolve combat damage) rather than poking handlers directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import Game, load_cards
from engine.models import CardDefinition, Permanent, PlayerState

import web.app as web_app


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


def _mk_land(name: str, subtype: str) -> CardDefinition:
    type_line = f"Land - {subtype}"
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
        raw={"name": name, "type_line": type_line},
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


def _game(p1_battlefield: list[Permanent], p2_battlefield: list[Permanent], *, life: int = 20):
    p1 = PlayerState(name="P1", battlefield=p1_battlefield)
    p2 = PlayerState(name="P2", battlefield=p2_battlefield, life=life)
    return Game(players=[p1, p2]), p1, p2


def _to_declare_attackers(game: Game) -> None:
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers


def _to_declare_blockers(game: Game, attacker_indices: list[int]) -> None:
    _to_declare_attackers(game)
    ok, msg = game.declare_attackers(0, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"


def _resolve_combat(game: Game) -> None:
    """Advance from declare_blockers through the combat damage step."""
    game.advance_combat_phase()  # combat_damage (auto-resolves single-blocker cases)


@pytest.fixture(scope="module")
def all_cards():
    return load_cards(Path(__file__).resolve().parent.parent / "lea_cards.json")


def _get(all_cards, name: str) -> CardDefinition:
    return next(card for card in all_cards if card.name == name)


# ---------------------------------------------------------------------------
# The set of keywords under test matches the UI's display list
# ---------------------------------------------------------------------------


def test_display_keywords_are_all_covered_here():
    """Guard: every keyword the UI displays has a test section in this file."""
    expected = {
        "Flying", "First Strike", "Double Strike", "Trample", "Deathtouch",
        "Reach", "Vigilance", "Haste", "Defender", "Banding", "Fear",
        "Lifelink", "Shroud", "Protection", "Rampage", "Flanking",
        "Plainswalk", "Islandwalk", "Swampwalk", "Mountainwalk", "Forestwalk",
    }
    assert set(web_app._DISPLAY_KEYWORDS) == expected


# ---------------------------------------------------------------------------
# 702.9 — Flying
# ---------------------------------------------------------------------------


def test_702_9b_flying_cannot_be_blocked_by_ground_creature():
    flier = Permanent(card=_mk_creature("Flier", 2, 2, keywords=("Flying",)))
    grounder = Permanent(card=_mk_creature("Grounder", 2, 2))
    game, _, _ = _game([flier], [grounder])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok


def test_702_9b_flying_can_be_blocked_by_another_flier():
    flier = Permanent(card=_mk_creature("Flier", 2, 2, keywords=("Flying",)))
    blocker = Permanent(card=_mk_creature("Other Flier", 2, 2, keywords=("Flying",)))
    game, _, _ = _game([flier], [blocker])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok


def test_702_9b_flier_can_block_a_nonflier():
    """A creature with flying can block a creature with or without flying."""
    attacker = Permanent(card=_mk_creature("Ground Pounder", 2, 2))
    flier = Permanent(card=_mk_creature("Flier", 2, 2, keywords=("Flying",)))
    game, _, _ = _game([attacker], [flier])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok


# ---------------------------------------------------------------------------
# 702.17 — Reach
# ---------------------------------------------------------------------------


def test_702_17b_reach_can_block_a_flier():
    flier = Permanent(card=_mk_creature("Flier", 2, 2, keywords=("Flying",)))
    reacher = Permanent(card=_mk_creature("Spider", 2, 2, keywords=("Reach",)))
    game, _, _ = _game([flier], [reacher])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok


def test_702_17b_reach_alone_does_not_grant_evasion():
    """Reach lets you block fliers; it does not make the creature itself evasive."""
    reacher = Permanent(card=_mk_creature("Spider", 2, 2, keywords=("Reach",)))
    grounder = Permanent(card=_mk_creature("Grounder", 2, 2))
    game, _, _ = _game([reacher], [grounder])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok


# ---------------------------------------------------------------------------
# 702.7 — First Strike
# ---------------------------------------------------------------------------


def test_702_7_first_striker_kills_before_taking_damage():
    """702.7b: a first striker deals combat damage in a separate, earlier step.
    A 2/2 first striker kills an equal vanilla blocker before it can hit back."""
    striker = Permanent(card=_mk_creature("Striker", 2, 2, keywords=("First Strike",)))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    game, p1, p2 = _game([striker], [blocker])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})
    _resolve_combat(game)

    assert all(p.card.name != "Blocker" for p in p2.battlefield)  # blocker died first
    assert any(p.card.name == "Striker" for p in p1.battlefield)  # striker untouched
    assert p1.battlefield[0].damage_marked == 0


def test_702_7_first_strike_real_card_black_knight(all_cards):
    bk = Permanent(card=_get(all_cards, "Black Knight"))  # 2/2 first strike
    blocker = Permanent(card=_mk_creature("Bear", 2, 2))
    game, p1, p2 = _game([bk], [blocker])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})
    _resolve_combat(game)

    assert all(p.card.name != "Bear" for p in p2.battlefield)
    assert any(p.card.name == "Black Knight" for p in p1.battlefield)


# ---------------------------------------------------------------------------
# 702.4 — Double Strike
# ---------------------------------------------------------------------------


def test_702_4_double_strike_deals_damage_twice_to_player():
    """702.4: a double striker assigns combat damage in both the first-strike and
    the regular combat damage step — an unblocked 2/2 deals 4 to the defender."""
    ds = Permanent(card=_mk_creature("Double", 2, 2, keywords=("Double Strike",)))
    game, _, p2 = _game([ds], [], life=20)
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {})
    _resolve_combat(game)

    assert p2.life == 16


def test_702_4_double_strike_deals_two_rounds_to_blocker():
    ds = Permanent(card=_mk_creature("Double", 2, 2, keywords=("Double Strike",)))
    blocker = Permanent(card=_mk_creature("Wall", 0, 3))
    game, p1, p2 = _game([ds], [blocker])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})
    _resolve_combat(game)

    # 2 (first strike) + 2 (regular) = 4 >= 3 toughness -> blocker dies.
    assert all(p.card.name != "Wall" for p in p2.battlefield)


# ---------------------------------------------------------------------------
# 702.19 — Trample
# ---------------------------------------------------------------------------


def test_702_19b_trample_assigns_excess_to_player():
    trampler = Permanent(card=_mk_creature("Trampler", 4, 4, keywords=("Trample",)))
    blocker = Permanent(card=_mk_creature("Chump", 2, 2))
    game, _, p2 = _game([trampler], [blocker], life=20)
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})
    _resolve_combat(game)

    # 2 lethal to the 2/2, 2 trample over to the player.
    assert p2.life == 18
    assert all(p.card.name != "Chump" for p in p2.battlefield)


def test_702_19_no_trample_means_no_excess_to_player():
    attacker = Permanent(card=_mk_creature("Brute", 4, 4))
    blocker = Permanent(card=_mk_creature("Chump", 2, 2))
    game, _, p2 = _game([attacker], [blocker], life=20)
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})
    _resolve_combat(game)

    assert p2.life == 20  # all damage stays on the blocker


# ---------------------------------------------------------------------------
# 702.2 — Deathtouch
# ---------------------------------------------------------------------------


def test_702_2b_any_damage_from_deathtouch_is_lethal():
    deathtoucher = Permanent(card=_mk_creature("Viper", 1, 1, keywords=("Deathtouch",)))
    big = Permanent(card=_mk_creature("Giant", 5, 5))
    game, _, p2 = _game([deathtoucher], [big])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})
    _resolve_combat(game)

    assert all(p.card.name != "Giant" for p in p2.battlefield)


def test_702_2c_deathtouch_with_trample_assigns_one_then_tramples():
    """702.2c/702.19: with deathtouch, 1 damage is lethal, so a 4/4 deathtouch
    trampler need only assign 1 to a 3/3 blocker and tramples the other 3."""
    creature = Permanent(
        card=_mk_creature("Hydra", 4, 4, keywords=("Deathtouch", "Trample"))
    )
    blocker = Permanent(card=_mk_creature("Ogre", 3, 3))
    game, _, p2 = _game([creature], [blocker], life=20)
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})
    _resolve_combat(game)

    assert all(p.card.name != "Ogre" for p in p2.battlefield)
    assert p2.life == 17  # 4 - 1 lethal = 3 trampled


# ---------------------------------------------------------------------------
# 702.3 — Defender
# ---------------------------------------------------------------------------


def test_702_3b_defender_cannot_attack():
    wall = Permanent(card=_mk_creature("Wall", 0, 4, keywords=("Defender",)))
    game, _, _ = _game([wall], [])
    assert game.can_attack(wall, 1) is False


def test_702_3b_defender_attack_declaration_rejected():
    wall = Permanent(card=_mk_creature("Wall", 0, 4, keywords=("Defender",)))
    game, _, _ = _game([wall], [])
    _to_declare_attackers(game)
    ok, _ = game.declare_attackers(0, [0])
    assert not ok


# ---------------------------------------------------------------------------
# 702.20 — Vigilance
# ---------------------------------------------------------------------------


def test_702_20b_vigilance_does_not_tap_when_attacking():
    serra = Permanent(card=_mk_creature("Serra", 4, 4, keywords=("Vigilance",)))
    game, p1, _ = _game([serra], [])
    _to_declare_attackers(game)
    ok, _ = game.declare_attackers(0, [0])
    assert ok
    assert p1.battlefield[0].tapped is False


def test_702_20b_without_vigilance_attacking_taps():
    bear = Permanent(card=_mk_creature("Bear", 2, 2))
    game, p1, _ = _game([bear], [])
    _to_declare_attackers(game)
    game.declare_attackers(0, [0])
    assert p1.battlefield[0].tapped is True


def test_702_20b_serra_angel_real_card_keeps_untapped(all_cards):
    serra = Permanent(card=_get(all_cards, "Serra Angel"))
    game, p1, _ = _game([serra], [])
    _to_declare_attackers(game)
    ok, _ = game.declare_attackers(0, [0])
    assert ok
    assert p1.battlefield[0].tapped is False


# ---------------------------------------------------------------------------
# 702.10 — Haste
# ---------------------------------------------------------------------------


def test_702_10b_haste_lets_a_summoning_sick_creature_attack():
    hasty = Permanent(card=_mk_creature("Raider", 2, 2, keywords=("Haste",)))
    game, p1, _ = _game([hasty], [])
    # Mark it as having entered this turn (summoning sick).
    game.turn = 1
    hasty.metadata["summoning_sickness_turn"] = 1
    assert game.can_attack(hasty, 1) is True


def test_702_10b_without_haste_summoning_sick_cannot_attack():
    sick = Permanent(card=_mk_creature("Recruit", 2, 2))
    game, p1, _ = _game([sick], [])
    game.turn = 1
    sick.metadata["summoning_sickness_turn"] = 1
    assert game.can_attack(sick, 1) is False


# ---------------------------------------------------------------------------
# 702.13 — Fear (engine models the Alpha-era "can't be blocked except by
# artifact and/or black creatures" evasion)
# ---------------------------------------------------------------------------


def test_fear_cannot_be_blocked_by_plain_creature():
    sneak = Permanent(card=_mk_creature("Sneak", 2, 2, keywords=("Fear",)))
    plain = Permanent(card=_mk_creature("Plain", 2, 2))
    game, _, _ = _game([sneak], [plain])
    _to_declare_blockers(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok


def test_fear_can_be_blocked_by_black_creature():
    sneak = Permanent(card=_mk_creature("Sneak", 2, 2, keywords=("Fear",)))
    black = Permanent(card=_mk_creature("Shade", 2, 2, colors=("B",)))
    game, _, _ = _game([sneak], [black])
    _to_declare_blockers(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok


def test_fear_can_be_blocked_by_artifact_creature():
    sneak = Permanent(card=_mk_creature("Sneak", 2, 2, keywords=("Fear",)))
    golem = Permanent(
        card=_mk_creature("Golem", 2, 2, type_line="Artifact Creature - Golem")
    )
    game, _, _ = _game([sneak], [golem])
    _to_declare_blockers(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok


# ---------------------------------------------------------------------------
# 702.15 — Lifelink
# ---------------------------------------------------------------------------


def test_702_15b_lifelink_gains_life_on_player_damage():
    ll = Permanent(card=_mk_creature("Vampire", 3, 3, keywords=("Lifelink",)))
    game, p1, p2 = _game([ll], [], life=20)
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {})
    _resolve_combat(game)

    assert p2.life == 17
    assert p1.life == 23  # controller gained 3


def test_702_15b_lifelink_gains_life_when_blocking():
    attacker = Permanent(card=_mk_creature("Raider", 2, 2))
    ll_blocker = Permanent(card=_mk_creature("Cleric", 2, 2, keywords=("Lifelink",)))
    game, _, p2 = _game([attacker], [ll_blocker], life=20)
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})
    _resolve_combat(game)

    # The lifelink blocker deals 2 to the attacker -> its controller gains 2.
    assert p2.life == 22


def test_702_15b_lifelink_on_trample_counts_all_damage_dealt():
    ll = Permanent(
        card=_mk_creature("Beast", 4, 4, keywords=("Lifelink", "Trample"))
    )
    blocker = Permanent(card=_mk_creature("Chump", 2, 2))
    game, p1, p2 = _game([ll], [blocker], life=20)
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})
    _resolve_combat(game)

    # 2 to the blocker + 2 trampled = 4 total damage dealt -> 4 life gained.
    assert p1.life == 24
    assert p2.life == 18


# ---------------------------------------------------------------------------
# 702.18 — Shroud
# ---------------------------------------------------------------------------


def test_702_18a_shroud_cannot_be_targeted_by_a_spell():
    bolt = _mk_instant("Bolt", "Bolt deals 3 damage to target creature.", colors=("R",))
    victim = Permanent(card=_mk_creature("Hidden One", 2, 3, keywords=("Shroud",)))
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Bolt", target_player_index=1, target_permanent_index=0)
    assert p2.battlefield[0].damage_marked == 0  # spell did nothing


def test_702_18a_shroud_blocks_even_your_own_spells():
    pump = _mk_instant("Pump", "Target creature gets +3/+3 until end of turn.", colors=("G",))
    own = Permanent(card=_mk_creature("Loner", 2, 2, keywords=("Shroud",)))
    p1 = PlayerState(name="P1", hand=[pump], battlefield=[own])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Pump", target_player_index=0, target_permanent_index=0)
    assert p1.battlefield[0].effective_power == 2  # untargetable -> no buff


def test_702_18a_a_creature_without_shroud_is_targetable():
    bolt = _mk_instant("Bolt", "Bolt deals 3 damage to target creature.", colors=("R",))
    victim = Permanent(card=_mk_creature("Open One", 2, 4))
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Bolt", target_player_index=1, target_permanent_index=0)
    assert p2.battlefield[0].damage_marked == 3


# ---------------------------------------------------------------------------
# 702.16 — Protection
# ---------------------------------------------------------------------------


def test_702_16f_protection_cannot_be_blocked_by_that_color(all_cards):
    """702.16f: an attacker with protection from white can't be blocked by white."""
    bk = Permanent(card=_get(all_cards, "Black Knight"))  # protection from white
    white_blocker = Permanent(card=_mk_creature("Cleric", 2, 2, colors=("W",)))
    game, _, _ = _game([bk], [white_blocker])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok


def test_702_16e_protection_prevents_damage_from_that_color(all_cards):
    """702.16e: damage from a white source to the Black Knight is prevented."""
    white_attacker = Permanent(card=_mk_creature("Crusader", 3, 3, colors=("W",)))
    bk = Permanent(card=_get(all_cards, "Black Knight"))  # 2/2, prot white, first strike
    game, _, p2 = _game([white_attacker], [bk])
    _to_declare_blockers(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    _resolve_combat(game)

    # The Black Knight survives: the white attacker's damage is prevented.
    survivor = next(p for p in p2.battlefield if p.card.name == "Black Knight")
    assert survivor.damage_marked == 0


def test_702_16b_protection_cannot_be_targeted_by_that_color(all_cards):
    white_bolt = _mk_instant(
        "Holy Light", "Holy Light deals 3 damage to target creature.", colors=("W",)
    )
    bk = Permanent(card=_get(all_cards, "Black Knight"))
    p1 = PlayerState(name="P1", hand=[white_bolt])
    p2 = PlayerState(name="P2", battlefield=[bk])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Holy Light", target_player_index=1, target_permanent_index=0)
    assert p2.battlefield[0].damage_marked == 0


def test_702_16b_protection_does_not_stop_other_colors(all_cards):
    """Protection from white does not stop a red spell from killing the Knight."""
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


def test_702_16_white_knight_protection_from_black(all_cards):
    """White Knight (protection from black) can't be blocked by a black creature."""
    wk = Permanent(card=_get(all_cards, "White Knight"))
    black_blocker = Permanent(card=_mk_creature("Zombie", 2, 2, colors=("B",)))
    game, _, _ = _game([wk], [black_blocker])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok


# ---------------------------------------------------------------------------
# 702.23 — Rampage
# ---------------------------------------------------------------------------


def _mk_rampage(name: str, n: int, power: int = 3, toughness: int = 3) -> CardDefinition:
    return _mk_creature(
        name,
        power,
        toughness,
        keywords=(f"Rampage {n}",),
        oracle_text=f"Rampage {n} (Whenever this creature becomes blocked, "
        f"it gets +{n}/+{n} until end of turn for each creature blocking it beyond the first.)",
    )


def test_702_23a_rampage_buffs_per_blocker_beyond_the_first():
    ramp = Permanent(card=_mk_rampage("Rampager", 2, 3, 3))
    b1 = Permanent(card=_mk_creature("B1", 1, 1))
    b2 = Permanent(card=_mk_creature("B2", 1, 1))
    b3 = Permanent(card=_mk_creature("B3", 1, 1))
    game, p1, _ = _game([ramp], [b1, b2, b3])
    _to_declare_blockers(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0, 1: 0, 2: 0})
    assert ok

    # 3 blockers -> 2 beyond the first -> +2/+2 twice = +4/+4.
    assert p1.battlefield[0].effective_power == 7
    assert p1.battlefield[0].effective_toughness == 7


def test_702_23a_rampage_no_bonus_with_a_single_blocker():
    ramp = Permanent(card=_mk_rampage("Rampager", 3, 3, 3))
    b1 = Permanent(card=_mk_creature("B1", 1, 1))
    game, p1, _ = _game([ramp], [b1])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})

    assert p1.battlefield[0].effective_power == 3
    assert p1.battlefield[0].effective_toughness == 3


def test_702_23b_rampage_bonus_wears_off_end_of_turn():
    ramp = Permanent(card=_mk_rampage("Rampager", 2, 3, 3))
    b1 = Permanent(card=_mk_creature("B1", 1, 1))
    b2 = Permanent(card=_mk_creature("B2", 1, 1))
    game, p1, _ = _game([ramp], [b1, b2])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0, 1: 0})
    assert p1.battlefield[0].effective_power == 5

    game.resolve_cleanup_step(0)
    assert p1.battlefield[0].effective_power == 3


# ---------------------------------------------------------------------------
# 702.25 — Flanking
# ---------------------------------------------------------------------------


def test_702_25a_flanking_gives_blocker_minus_one_minus_one():
    flanker = Permanent(card=_mk_creature("Knight", 2, 2, keywords=("Flanking",)))
    blocker = Permanent(card=_mk_creature("Footman", 2, 2))
    game, _, p2 = _game([flanker], [blocker])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})

    survivor = next(p for p in p2.battlefield if p.card.name == "Footman")
    assert survivor.effective_power == 1
    assert survivor.effective_toughness == 1


def test_702_25a_flanking_kills_an_x_1_blocker_outright():
    flanker = Permanent(card=_mk_creature("Knight", 2, 2, keywords=("Flanking",)))
    weakling = Permanent(card=_mk_creature("Goblin", 1, 1))
    game, _, p2 = _game([flanker], [weakling])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})

    # -1/-1 drops the 1/1 to 0 toughness -> dies to state-based actions.
    assert all(p.card.name != "Goblin" for p in p2.battlefield)


def test_702_25a_flanking_does_not_debuff_another_flanker():
    flanker = Permanent(card=_mk_creature("Knight", 2, 2, keywords=("Flanking",)))
    other = Permanent(card=_mk_creature("Rival", 2, 2, keywords=("Flanking",)))
    game, _, p2 = _game([flanker], [other])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})

    survivor = next(p for p in p2.battlefield if p.card.name == "Rival")
    assert survivor.effective_power == 2
    assert survivor.effective_toughness == 2


# ---------------------------------------------------------------------------
# 702.14 — Landwalk (Plains/Island/Swamp/Mountain/Forest walk)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "walk_keyword,land_subtype",
    [
        ("Plainswalk", "Plains"),
        ("Islandwalk", "Island"),
        ("Swampwalk", "Swamp"),
        ("Mountainwalk", "Mountain"),
        ("Forestwalk", "Forest"),
    ],
)
def test_702_14c_landwalk_is_unblockable_when_defender_has_that_land(walk_keyword, land_subtype):
    walker = Permanent(card=_mk_creature("Walker", 2, 2, keywords=(walk_keyword,)))
    blocker = Permanent(card=_mk_creature("Guard", 2, 2))
    land = Permanent(card=_mk_land(land_subtype, land_subtype))
    game, _, _ = _game([walker], [blocker, land])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok


@pytest.mark.parametrize(
    "walk_keyword,land_subtype",
    [
        ("Plainswalk", "Plains"),
        ("Islandwalk", "Island"),
        ("Swampwalk", "Swamp"),
        ("Mountainwalk", "Mountain"),
        ("Forestwalk", "Forest"),
    ],
)
def test_702_14c_landwalk_is_blockable_without_that_land(walk_keyword, land_subtype):
    walker = Permanent(card=_mk_creature("Walker", 2, 2, keywords=(walk_keyword,)))
    blocker = Permanent(card=_mk_creature("Guard", 2, 2))
    # Defender controls a different land type, so the walk grants no evasion.
    other = "Forest" if land_subtype != "Forest" else "Plains"
    land = Permanent(card=_mk_land(other, other))
    game, _, _ = _game([walker], [blocker, land])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok


def test_702_14_real_card_forestwalk(all_cards):
    """Jungle Lion-style — use an Alpha card with forestwalk if present."""
    forestwalker = next(
        (c for c in all_cards if "Forestwalk" in c.keywords and c.primary_type == "creature"),
        None,
    )
    if forestwalker is None:
        pytest.skip("no forestwalk creature in the card pool")
    walker = Permanent(card=forestwalker)
    blocker = Permanent(card=_mk_creature("Guard", 2, 2))
    land = Permanent(card=_mk_land("Forest", "Forest"))
    game, _, _ = _game([walker], [blocker, land])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok


# ---------------------------------------------------------------------------
# 702.22 — Banding
# ---------------------------------------------------------------------------


def test_702_22_banding_keyword_is_recognized(all_cards):
    """702.22a: banding is a static ability. The engine recognizes it on the three
    Alpha banding creatures via ``_has_keyword``."""
    hero = Permanent(card=_get(all_cards, "Benalish Hero"))
    game, _, _ = _game([hero], [])
    assert game._has_keyword(hero, "banding")


def test_702_22_banding_creature_attacks_and_fights_normally(all_cards):
    """A banding creature attacks and is blocked like any other; full multi-creature
    band declaration is not modeled, but ordinary combat with one must not crash."""
    hero = Permanent(card=_get(all_cards, "Benalish Hero"))  # 1/1 banding
    blocker = Permanent(card=_mk_creature("Bear", 2, 2))
    game, p1, _ = _game([hero], [blocker])
    _to_declare_blockers(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    _resolve_combat(game)

    # The 1/1 hero trades into a 2/2 and dies; no exception during resolution.
    assert all(p.card.name != "Benalish Hero" for p in p1.battlefield)


def test_grant_banding_until_end_of_turn_sets_flag():
    """The "target creature gains banding until end of turn" ability (e.g. Helm of
    Chatzuk) stamps the until-eot flag on one of the controller's creatures."""
    helm = _mk_creature(
        "Bander", 0, 0, type_line="Artifact",
        oracle_text="{0}: Target creature gains banding until end of turn.",
    )
    target = _mk_creature("Soldier", 2, 2)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=helm), Permanent(card=target)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Bander", target_player_index=0)
    assert result.supported, result.details
    assert any(
        perm.metadata.get("gains_banding_until_eot")
        for perm in p1.battlefield
    )
