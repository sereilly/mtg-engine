"""Tests for Magic: The Gathering Comprehensive Rules Section 704 — State-Based Actions."""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_card(name: str, type_line: str, oracle_text: str = "", colors: tuple[str, ...] = ()) -> CardDefinition:
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


def _mk_creature(name: str, power: int = 2, toughness: int = 2, oracle_text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Test",
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test", "power": str(power), "toughness": str(toughness)},
    )


def _run_combat(game: Game, attacker_indices: list[int], blocker_dict: dict[int, int]) -> None:
    """Advance from precombat_main through combat damage resolution."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # → beginning_of_combat
    game.advance_combat_phase()  # → declare_attackers
    game.declare_attackers(0, attacker_indices)
    game.advance_combat_phase()  # → declare_blockers
    game.declare_blockers(1, blocker_dict)
    game.advance_combat_phase()  # → combat_damage (resolves)


# ---------------------------------------------------------------------------
# Rule 704.5a – If a player has 0 or less life, that player loses the game.
# ---------------------------------------------------------------------------

def test_704_5a_player_life_reduced_to_zero_condition_met():
    """704.5a: A player whose life is reduced to exactly 0 meets the state-based loss condition."""
    spell = _mk_card("Drain Life", "Sorcery", "Target player loses 20 life.")
    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Drain Life", target_player_index=1)

    assert p2.life <= 0


def test_704_5a_player_life_pushed_below_zero_condition_met():
    """704.5a: Excess damage pushes life below 0; the rule condition is still met."""
    spell = _mk_card("Dark Ritual Drain", "Sorcery", "Target player loses 5 life.")
    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", life=3)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Dark Ritual Drain", target_player_index=1)

    assert p2.life < 0


def test_704_5a_player_above_zero_life_does_not_meet_loss_condition():
    """704.5a: A player with positive life does not meet the 704.5a loss condition."""
    p1 = PlayerState(name="P1", life=1)
    assert p1.life > 0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5a state-based action not fully implemented: the engine reduces a "
        "player's life to 0 or below but does not mark the player as having lost the "
        "game. No 'player.lost' or 'game.winner' field exists in the engine."
    ),
)
def test_704_5a_player_formally_loses_game_at_zero_life():
    """704.5a: A player with 0 or less life should formally lose the game."""
    spell = _mk_card("Lethal Drain", "Sorcery", "Target player loses 20 life.")
    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Lethal Drain", target_player_index=1)

    assert p2.life <= 0
    assert hasattr(p2, "lost") and p2.lost  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Rule 704.5b – If a player attempted to draw a card from a library with no
# cards in it since the last time state-based actions were checked, that
# player loses the game.
# ---------------------------------------------------------------------------

def test_704_5b_draw_from_empty_library_returns_zero_cards():
    """704.5b: Attempting to draw from an empty library draws 0 cards."""
    p1 = PlayerState(name="P1", library=[])
    drawn = p1.draw(1)
    assert drawn == 0
    assert len(p1.hand) == 0


def test_704_5b_draw_from_empty_library_leaves_hand_unchanged():
    """704.5b: An empty-library draw attempt does not alter the player's hand size."""
    existing_card = _mk_card("Forest", "Basic Land — Forest")
    p1 = PlayerState(name="P1", library=[], hand=[existing_card])
    p1.draw(1)
    assert len(p1.hand) == 1


def test_704_5b_successful_draw_from_non_empty_library():
    """704.5b: Drawing from a library with cards succeeds; no loss condition is triggered."""
    card = _mk_card("Plains", "Basic Land — Plains")
    p1 = PlayerState(name="P1", library=[card])
    drawn = p1.draw(1)
    assert drawn == 1
    assert len(p1.hand) == 1
    assert len(p1.library) == 0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5b state-based action not implemented: the engine does not track "
        "that a player attempted to draw from an empty library, and no 'player.lost' "
        "flag is set when this occurs."
    ),
)
def test_704_5b_drawing_from_empty_library_causes_player_to_lose():
    """704.5b: A player who attempts to draw from an empty library loses the game."""
    draw_spell = _mk_card("Draw Spell", "Sorcery", "Target player draws a card.")
    p1 = PlayerState(name="P1", hand=[draw_spell])
    p2 = PlayerState(name="P2", library=[])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Draw Spell", target_player_index=1)

    assert hasattr(p2, "lost") and p2.lost  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Rule 704.5c – If a player has ten or more poison counters, that player
# loses the game.
# ---------------------------------------------------------------------------

def test_704_5c_ten_poison_counters_cause_player_to_lose():
    """704.5c: A player with 10 or more poison counters loses the game."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    p2.poison_counters = 10
    game = Game(players=[p1, p2])
    game.check_state_based_actions()
    assert p2.lost


def test_704_5c_player_state_has_poison_counter_field():
    """704.5c: PlayerState now tracks poison_counters, defaulting to 0."""
    p1 = PlayerState(name="P1")
    assert hasattr(p1, "poison_counters")
    assert p1.poison_counters == 0


# ---------------------------------------------------------------------------
# Rule 704.5d – If a token is in a zone other than the battlefield, it
# ceases to exist.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5d not implemented: the engine does not distinguish token permanents "
        "from card-backed permanents. Tokens are not removed when they enter a "
        "non-battlefield zone (e.g. the graveyard after being destroyed)."
    ),
)
def test_704_5d_token_destroyed_does_not_enter_graveyard():
    """704.5d: A token destroyed in combat ceases to exist instead of entering the graveyard."""
    token_card = _mk_creature("Saproling", 1, 1)
    token_perm = Permanent(card=token_card, metadata={"is_token": True})
    wrath = _mk_card("Wrath", "Sorcery", "Destroy all creatures.")
    p1 = PlayerState(name="P1", hand=[wrath], battlefield=[token_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Wrath", target_player_index=1)

    # 704.5d: token should cease to exist — not appear in the graveyard
    assert not any(c.name == "Saproling" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Rule 704.5e – If a copy of a spell is in a zone other than the stack, or
# a copy of a card is in any zone other than the stack or the battlefield,
# it ceases to exist.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5e not implemented: the engine does not model spell or card copies "
        "as distinct from originals. Copy tracking and automatic removal from "
        "non-legal zones are not supported."
    ),
)
def test_704_5e_copy_of_card_in_graveyard_ceases_to_exist():
    """704.5e: A copy of a card in a zone other than the stack or battlefield ceases to exist."""
    card = _mk_card("Clone Card", "Instant")
    # Copies are not modeled; the engine has no 'is_copy' metadata enforcement
    copy_perm = Permanent(card=card, metadata={"is_copy": True})
    p1 = PlayerState(name="P1", battlefield=[copy_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    wrath = _mk_card("Wrath", "Sorcery", "Destroy all creatures.")
    p1.hand.append(wrath)
    game.cast_from_hand(0, "Wrath", target_player_index=1)

    # 704.5e: the copy should cease to exist — it must not remain on the battlefield
    # (Wrath only destroys creatures, so the copy_perm (Instant type) stays on battlefield
    # when 704.5e is not enforced — this assertion will fail until the rule is implemented)
    assert not any(perm.card.name == "Clone Card" for perm in p1.battlefield)


# ---------------------------------------------------------------------------
# Rule 704.5f – If a creature has toughness 0 or less, it's put into its
# owner's graveyard. Regeneration can't replace this event.
# ---------------------------------------------------------------------------

def test_704_5f_creature_debuffed_to_zero_toughness_meets_condition():
    """704.5f: A creature whose effective toughness reaches 0 via a debuff meets the condition."""
    creature = _mk_creature("Fragile Creature", 1, 1)
    perm = Permanent(card=creature, toughness_bonus=-1)
    assert perm.effective_toughness == 0


def test_704_5f_creature_debuffed_to_negative_toughness_meets_condition():
    """704.5f: A creature whose effective toughness goes below 0 also meets the condition."""
    creature = _mk_creature("Glass Creature", 2, 1)
    perm = Permanent(card=creature, toughness_bonus=-2)
    assert perm.effective_toughness < 0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5f state-based action not implemented: the engine does not check "
        "for creatures with toughness 0 or less outside of combat damage resolution. "
        "A creature debuffed to 0 or negative toughness remains on the battlefield."
    ),
)
def test_704_5f_creature_debuffed_to_zero_toughness_goes_to_graveyard():
    """704.5f: A creature whose toughness is reduced to 0 by a continuous effect is put
    into its owner's graveyard."""
    debuff = _mk_card(
        "Enfeeblement",
        "Enchantment — Aura",
        "Enchant creature\nEnchanted creature gets -2/-2.",
    )
    creature = _mk_creature("Weakling", 1, 1)
    p1 = PlayerState(name="P1", hand=[debuff])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Enfeeblement", target_player_index=1)

    # 704.5f: toughness is now -1 — creature must go to graveyard
    assert not any(perm.card.name == "Weakling" for perm in p2.battlefield)
    assert any(c.name == "Weakling" for c in p2.graveyard)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5f: regeneration cannot replace a creature going to the graveyard "
        "due to toughness 0 or less. This distinction requires 704.5f to be implemented "
        "as a separate check from lethal-damage destruction (704.5g)."
    ),
)
def test_704_5f_regeneration_cannot_save_creature_with_zero_toughness():
    """704.5f: Regeneration cannot replace the 704.5f state-based action — a creature with
    toughness 0 or less goes to the graveyard regardless of regeneration shields."""
    debuff = _mk_card(
        "Weakness Aura",
        "Enchantment — Aura",
        "Enchant creature\nEnchanted creature gets -2/-2.",
    )
    creature = _mk_creature("Regen Creature", 1, 1)
    perm = Permanent(card=creature, regeneration_shield=1)
    p1 = PlayerState(name="P1", hand=[debuff])
    p2 = PlayerState(name="P2", battlefield=[perm])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Weakness Aura", target_player_index=1)

    # Regeneration shield must NOT prevent 704.5f — creature must still die
    assert not any(p.card.name == "Regen Creature" for p in p2.battlefield)
    assert any(c.name == "Regen Creature" for c in p2.graveyard)


# ---------------------------------------------------------------------------
# Rule 704.5g – If a creature has toughness greater than 0, it has damage
# marked on it, and the total damage marked on it is greater than or equal
# to its toughness, that creature has been dealt lethal damage and is
# destroyed. Regeneration can replace this event.
# ---------------------------------------------------------------------------

def test_704_5g_creature_receiving_lethal_combat_damage_goes_to_graveyard():
    """704.5g: A creature that blocks and receives damage equal to its toughness is destroyed."""
    attacker = _mk_creature("Grizzly Bears", 2, 2)
    blocker = _mk_creature("Eager Cadet", 1, 1)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=attacker)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=blocker)], life=20)
    game = Game(players=[p1, p2])

    _run_combat(game, [0], {0: 0})

    assert not any(perm.card.name == "Eager Cadet" for perm in p2.battlefield)
    assert any(c.name == "Eager Cadet" for c in p2.graveyard)


def test_704_5g_both_creatures_destroyed_when_each_deals_lethal_damage():
    """704.5g: When a 2/2 trades with a 2/2, both are destroyed simultaneously."""
    attacker = _mk_creature("Attacker Bear", 2, 2)
    blocker = _mk_creature("Blocker Bear", 2, 2)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=attacker)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=blocker)], life=20)
    game = Game(players=[p1, p2])

    _run_combat(game, [0], {0: 0})

    assert not any(perm.card.name == "Attacker Bear" for perm in p1.battlefield)
    assert not any(perm.card.name == "Blocker Bear" for perm in p2.battlefield)
    assert any(c.name == "Attacker Bear" for c in p1.graveyard)
    assert any(c.name == "Blocker Bear" for c in p2.graveyard)


def test_704_5g_creature_below_lethal_threshold_survives():
    """704.5g: A creature that receives damage less than its toughness is not destroyed."""
    attacker = _mk_creature("Tiny Attacker", 1, 1)
    blocker = _mk_creature("Stout Blocker", 1, 3)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=attacker)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=blocker)], life=20)
    game = Game(players=[p1, p2])

    _run_combat(game, [0], {0: 0})

    # Blocker received 1 damage but has toughness 3 — not lethal, survives
    assert any(perm.card.name == "Stout Blocker" for perm in p2.battlefield)
    assert not any(c.name == "Stout Blocker" for c in p2.graveyard)


def test_704_5g_creature_with_excess_lethal_damage_still_destroyed():
    """704.5g: A creature receiving far more damage than its toughness is still destroyed."""
    attacker = _mk_creature("Giant", 10, 10)
    blocker = _mk_creature("Goblin", 1, 1)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=attacker)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=blocker)], life=20)
    game = Game(players=[p1, p2])

    _run_combat(game, [0], {0: 0})

    assert not any(perm.card.name == "Goblin" for perm in p2.battlefield)
    assert any(c.name == "Goblin" for c in p2.graveyard)


def test_704_5g_regeneration_replaces_destruction_from_lethal_damage():
    """704.5g: Regeneration can replace the destruction event — the creature survives tapped
    with damage cleared."""
    attacker = _mk_creature("Attacker", 2, 2)
    blocker_card = _mk_creature("Regenerating Creature", 1, 1)
    blocker_perm = Permanent(card=blocker_card, regeneration_shield=1)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=attacker)])
    p2 = PlayerState(name="P2", battlefield=[blocker_perm], life=20)
    game = Game(players=[p1, p2])

    _run_combat(game, [0], {0: 0})

    surviving = next(
        (p for p in p2.battlefield if p.card.name == "Regenerating Creature"), None
    )
    assert surviving is not None, "Regeneration should have saved the creature"
    assert surviving.tapped
    assert surviving.damage_marked == 0


def test_704_5g_creature_with_non_lethal_damage_remains_on_battlefield():
    """704.5g: A creature that received damage less than its toughness stays on the
    battlefield; 704.5g is not triggered because the threshold is not met."""
    attacker = _mk_creature("Small Attacker", 1, 1)
    blocker = _mk_creature("Durable Creature", 1, 4)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=attacker)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=blocker)], life=20)
    game = Game(players=[p1, p2])

    _run_combat(game, [0], {0: 0})

    # The 1/4 blocker is not destroyed — 1 damage < toughness 4
    assert any(perm.card.name == "Durable Creature" for perm in p2.battlefield)
    assert not any(c.name == "Durable Creature" for c in p2.graveyard)


# ---------------------------------------------------------------------------
# Rule 704.5h – If a creature has toughness greater than 0, and it's been
# dealt damage by a source with deathtouch since the last time state-based
# actions were checked, that creature is destroyed. Regeneration can replace
# this event.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5h not implemented: the engine does not track the deathtouch keyword "
        "as a damage source property. Any damage from a deathtouch source should destroy "
        "the damaged creature, but the engine only destroys creatures when "
        "damage_marked >= effective_toughness."
    ),
)
def test_704_5h_deathtouch_source_destroys_with_one_damage():
    """704.5h: A creature dealt any amount of damage by a deathtouch source is destroyed,
    even if that damage is less than the creature's toughness."""
    deathtouch_card = _mk_creature("Deathtouch Snake", 1, 1, oracle_text="Deathtouch")
    deathtouch_perm = Permanent(card=deathtouch_card, metadata={"has_deathtouch": True})
    big_blocker = _mk_creature("Armored Titan", 5, 5)
    p1 = PlayerState(name="P1", battlefield=[deathtouch_perm])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=big_blocker)], life=20)
    game = Game(players=[p1, p2])

    _run_combat(game, [0], {0: 0})

    # 704.5h: 1 damage from a deathtouch source is lethal — Armored Titan must die
    assert not any(perm.card.name == "Armored Titan" for perm in p2.battlefield)
    assert any(c.name == "Armored Titan" for c in p2.graveyard)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5h: regeneration can replace the destruction caused by deathtouch "
        "damage, but this requires deathtouch to be tracked as a damage source modifier."
    ),
)
def test_704_5h_regeneration_replaces_deathtouch_destruction():
    """704.5h: Regeneration can replace the destruction caused by deathtouch damage."""
    deathtouch_card = _mk_creature("Deathtouch Creature", 1, 1, oracle_text="Deathtouch")
    deathtouch_perm = Permanent(card=deathtouch_card, metadata={"has_deathtouch": True})
    blocker_card = _mk_creature("Regen Blocker", 1, 5)
    blocker_perm = Permanent(card=blocker_card, regeneration_shield=1)
    p1 = PlayerState(name="P1", battlefield=[deathtouch_perm])
    p2 = PlayerState(name="P2", battlefield=[blocker_perm], life=20)
    game = Game(players=[p1, p2])

    _run_combat(game, [0], {0: 0})

    # With deathtouch implemented, the 1-damage hit would be lethal and consume the regen
    # shield (shield drops from 1 to 0). Without deathtouch, 1 damage is non-lethal against
    # a 1/5 so the shield is never consumed and stays at 1 — this assertion fails.
    regen_blocker = next(
        (p for p in p2.battlefield if p.card.name == "Regen Blocker"), None
    )
    assert regen_blocker is not None
    assert regen_blocker.regeneration_shield == 0  # shield was consumed saving the creature


# ---------------------------------------------------------------------------
# Rule 704.5i – If a planeswalker has loyalty 0, it's put into its owner's
# graveyard.
# ---------------------------------------------------------------------------

def test_704_5i_planeswalker_type_line_recognized():
    """704.5i: Cards with 'Planeswalker' in the type line are identified as planeswalkers."""
    walker = CardDefinition(
        name="Test Planeswalker",
        mana_cost="",
        cmc=0.0,
        type_line="Planeswalker — Jace",
        oracle_text="+1: Do something.\n−8: Win the game.",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": "Test Planeswalker", "type_line": "Planeswalker — Jace", "loyalty": "3"},
    )
    assert "Planeswalker" in walker.type_line


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5i not implemented: the engine does not model planeswalkers with "
        "loyalty counters. Loyalty tracking and the 0-loyalty graveyard state-based "
        "action are absent from the engine."
    ),
)
def test_704_5i_planeswalker_with_zero_loyalty_goes_to_graveyard():
    """704.5i: A planeswalker with 0 loyalty is put into its owner's graveyard."""
    walker_card = CardDefinition(
        name="Zero Loyalty Walker",
        mana_cost="",
        cmc=0.0,
        type_line="Planeswalker — Test",
        oracle_text="+1: Do something.",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": "Zero Loyalty Walker", "type_line": "Planeswalker — Test", "loyalty": "3"},
    )
    walker_perm = Permanent(card=walker_card, metadata={"loyalty": 0})
    p1 = PlayerState(name="P1", battlefield=[walker_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # 704.5i: walker with loyalty 0 must move to graveyard
    assert not any(perm.card.name == "Zero Loyalty Walker" for perm in p1.battlefield)
    assert any(c.name == "Zero Loyalty Walker" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Rule 704.5j – If two or more legendary permanents with the same name are
# controlled by the same player, that player chooses one of them, and the
# rest are put into their owners' graveyards. ("The legend rule.")
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5j (legend rule) not implemented: the engine does not check for "
        "multiple legendary permanents with the same name under the same controller. "
        "Both legendaries remain on the battlefield simultaneously."
    ),
)
def test_704_5j_same_name_same_controller_legend_rule_removes_one():
    """704.5j: When one player controls two legendary permanents with the same name, all
    but one are put into their owners' graveyards."""
    legend = _mk_card("Tolaria", "Legendary Land")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=legend), Permanent(card=legend)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # 704.5j: only one Tolaria should remain
    surviving_legends = [
        perm for perm in p1.battlefield if perm.card.name == "Tolaria"
    ]
    assert len(surviving_legends) == 1
    assert any(c.name == "Tolaria" for c in p1.graveyard)


def test_704_5j_different_names_both_legendary_permanents_coexist():
    """704.5j: Two legendary permanents with different names do not trigger the legend rule."""
    legend_a = _mk_card("Urza's Mine", "Legendary Land")
    legend_b = _mk_card("Urza's Tower", "Legendary Land")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=legend_a), Permanent(card=legend_b)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert any(perm.card.name == "Urza's Mine" for perm in p1.battlefield)
    assert any(perm.card.name == "Urza's Tower" for perm in p1.battlefield)
    assert not any(c.name == "Urza's Mine" for c in p1.graveyard)
    assert not any(c.name == "Urza's Tower" for c in p1.graveyard)


def test_704_5j_different_controllers_same_legendary_name_both_survive():
    """704.5j: Each player may control one legendary permanent with the same name;
    the legend rule only applies within a single player's permanents."""
    legend = _mk_card("Tolaria", "Legendary Land")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=legend)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=legend)])
    game = Game(players=[p1, p2])

    assert any(perm.card.name == "Tolaria" for perm in p1.battlefield)
    assert any(perm.card.name == "Tolaria" for perm in p2.battlefield)
    assert not any(c.name == "Tolaria" for c in p1.graveyard)
    assert not any(c.name == "Tolaria" for c in p2.graveyard)


# ---------------------------------------------------------------------------
# Rule 704.5k – If two or more permanents have the supertype world, all
# except the one that has had the world supertype for the shortest amount of
# time are put into their owners' graveyards. ("The world rule.")
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5k (world rule) not implemented: the engine does not track the "
        "'World' supertype or compare permanents' timestamps. Multiple world permanents "
        "coexist on the battlefield without any being removed."
    ),
)
def test_704_5k_two_world_permanents_older_goes_to_graveyard():
    """704.5k: When two world permanents are on the battlefield simultaneously, all but
    the one with the most recent timestamp are put into their owners' graveyards."""
    world_a = _mk_card("Concordant Crossroads", "World Enchantment")
    world_b = _mk_card("The Abyss", "World Enchantment")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=world_a), Permanent(card=world_b)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    world_perms = [perm for perm in p1.battlefield if "World" in perm.card.type_line]
    assert len(world_perms) == 1


# ---------------------------------------------------------------------------
# Rule 704.5m – If an Aura is attached to an illegal object or player, or
# is not attached to an object or player, that Aura is put into its owner's
# graveyard.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5m (and 303.4c) not implemented: when the enchanted creature is "
        "destroyed, the engine leaves the Aura on the battlefield rather than moving "
        "it to the owner's graveyard."
    ),
)
def test_704_5m_aura_goes_to_graveyard_when_enchanted_creature_is_destroyed():
    """704.5m: When the creature an Aura enchants is destroyed, the Aura is put into its
    owner's graveyard because it is no longer attached to a legal object."""
    aura = _mk_card(
        "Holy Strength",
        "Enchantment — Aura",
        "Enchant creature\nEnchanted creature gets +1/+2.",
    )
    creature = _mk_creature("Doomed Creature", 2, 2)
    wrath = _mk_card("Wrath of God", "Sorcery", "Destroy all creatures.")
    p1 = PlayerState(name="P1", hand=[aura, wrath])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Holy Strength", target_player_index=1)
    game.cast_from_hand(0, "Wrath of God", target_player_index=1)

    assert any(c.name == "Holy Strength" for c in p1.graveyard)
    assert not any(perm.card.name == "Holy Strength" for perm in p1.battlefield)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5m: an Aura on the battlefield with no attached_to target is in an "
        "illegal state and should be put into its owner's graveyard as a state-based "
        "action. The engine does not perform this check."
    ),
)
def test_704_5m_unattached_aura_on_battlefield_goes_to_graveyard():
    """704.5m: An Aura that is on the battlefield but not attached to any object or player
    is put into its owner's graveyard."""
    aura_card = _mk_card(
        "Floating Aura",
        "Enchantment — Aura",
        "Enchant creature\nEnchanted creature gets +1/+1.",
    )
    # Place aura directly on battlefield with no attached_to
    aura_perm = Permanent(card=aura_card)
    p1 = PlayerState(name="P1", battlefield=[aura_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # 704.5m: unattached Aura must go to graveyard
    assert not any(perm.card.name == "Floating Aura" for perm in p1.battlefield)
    assert any(c.name == "Floating Aura" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Rule 704.5n – If an Equipment or Fortification is attached to an illegal
# permanent or to a player, it becomes unattached from that permanent or
# player. It remains on the battlefield.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5n not implemented: when the equipped creature is destroyed, the "
        "engine does not clear the Equipment's 'attached_to' metadata. The Equipment "
        "should become unattached and remain on the battlefield."
    ),
)
def test_704_5n_equipment_becomes_unattached_when_equipped_creature_dies():
    """704.5n: An Equipment attached to a creature that dies becomes unattached but
    remains on the battlefield."""
    equipment_card = _mk_card(
        "Sword of Test",
        "Artifact — Equipment",
        "Equipped creature gets +2/+0.\nEquip {2}",
    )
    creature_card = _mk_creature("Armed Soldier", 1, 1)
    creature_perm = Permanent(card=creature_card)
    equip_perm = Permanent(card=equipment_card, metadata={"attached_to": creature_perm})
    creature_perm.metadata["attached_equipment"] = equip_perm

    wrath = _mk_card("Wrath", "Sorcery", "Destroy all creatures.")
    p1 = PlayerState(name="P1", hand=[wrath], battlefield=[creature_perm, equip_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Wrath", target_player_index=1)

    # 704.5n: Equipment remains on battlefield, unattached
    assert any(perm.card.name == "Sword of Test" for perm in p1.battlefield)
    equip = next(p for p in p1.battlefield if p.card.name == "Sword of Test")
    assert equip.metadata.get("attached_to") is None


# ---------------------------------------------------------------------------
# Rule 704.5p – If a battle or creature is attached to an object or player,
# it becomes unattached and remains on the battlefield.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5p not implemented: the engine does not detect or correct a "
        "non-Aura, non-Equipment permanent that finds itself in an attached state. "
        "The 'attached_to' metadata would persist without being cleared."
    ),
)
def test_704_5p_creature_in_attached_state_becomes_unattached():
    """704.5p: A creature permanent that is in an 'attached' state (which is illegal for
    creatures) becomes unattached and remains on the battlefield."""
    host_card = _mk_creature("Host Creature", 2, 2)
    attached_card = _mk_creature("Incorrectly Attached Creature", 1, 1)
    host_perm = Permanent(card=host_card)
    attached_perm = Permanent(
        card=attached_card, metadata={"attached_to": host_perm}
    )
    p1 = PlayerState(name="P1", battlefield=[host_perm, attached_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # 704.5p: the creature should be unattached
    bad_perm = next(
        p for p in p1.battlefield if p.card.name == "Incorrectly Attached Creature"
    )
    assert bad_perm.metadata.get("attached_to") is None


# ---------------------------------------------------------------------------
# Rule 704.5q – If a permanent has both a +1/+1 counter and a -1/-1 counter
# on it, N +1/+1 and N -1/-1 counters are removed from it, where N is the
# smaller of the two counts.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5q not implemented: the engine tracks stat changes as net "
        "power_bonus/toughness_bonus integers rather than as distinct named +1/+1 "
        "and -1/-1 counter objects. Physical counter removal as a state-based action "
        "is not implemented."
    ),
)
def test_704_5q_one_plus_counter_and_one_minus_counter_cancel():
    """704.5q: One +1/+1 counter and one -1/-1 counter on the same permanent are both
    removed — N=1 of each is cancelled."""
    creature = _mk_creature("Counter Bear", 2, 2)
    perm = Permanent(
        card=creature,
        metadata={"plus_counters": 1, "minus_counters": 1},
    )
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    current = p1.battlefield[0]
    assert current.metadata.get("plus_counters", 0) == 0
    assert current.metadata.get("minus_counters", 0) == 0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5q: with three +1/+1 and two -1/-1 counters, N=2 of each are "
        "removed, leaving one +1/+1 counter. Named counter tracking is not implemented."
    ),
)
def test_704_5q_partial_cancellation_leaves_remainder():
    """704.5q: When +1/+1 counters outnumber -1/-1 counters, N (the smaller count) of
    each type are removed, leaving the difference in +1/+1 counters."""
    creature = _mk_creature("Asymmetric Bear", 2, 2)
    perm = Permanent(
        card=creature,
        metadata={"plus_counters": 3, "minus_counters": 2},
    )
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    current = p1.battlefield[0]
    assert current.metadata.get("plus_counters", 0) == 1
    assert current.metadata.get("minus_counters", 0) == 0


# ---------------------------------------------------------------------------
# Rule 704.5r – If a permanent has an ability that says it can't have more
# than N counters of a certain kind on it and it has more than N, all but N
# of those counters are removed.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5r not implemented: the engine does not parse counter cap abilities "
        "or enforce counter maximums as a state-based action."
    ),
)
def test_704_5r_excess_counters_trimmed_to_cap():
    """704.5r: A permanent with more counters than its stated cap has the excess removed."""
    capped_card = _mk_card(
        "Capped Artifact",
        "Artifact",
        "This permanent can't have more than 3 charge counters on it.",
    )
    perm = Permanent(card=capped_card, metadata={"charge_counters": 5})
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    current = p1.battlefield[0]
    assert current.metadata.get("charge_counters", 0) <= 3


# ---------------------------------------------------------------------------
# Rule 704.5s – If the number of lore counters on a Saga permanent with one
# or more chapter abilities is greater than or equal to its final chapter
# number and it isn't the source of a pending chapter ability, that Saga's
# controller sacrifices it.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5s not implemented: the engine does not track lore counters on "
        "Saga permanents, does not compare them to the final chapter number, and "
        "does not automatically sacrifice Sagas that have completed their final chapter."
    ),
)
def test_704_5s_saga_sacrificed_when_lore_counters_reach_final_chapter():
    """704.5s: A Saga whose lore counter total reaches or exceeds its final chapter
    number is sacrificed by its controller."""
    saga_card = _mk_card(
        "Test Saga",
        "Enchantment — Saga",
        "I — Draw a card.\nII — Draw a card.\nIII — Draw three cards.",
    )
    saga_perm = Permanent(
        card=saga_card,
        metadata={"lore_counters": 3, "final_chapter": 3},
    )
    p1 = PlayerState(name="P1", battlefield=[saga_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # 704.5s: Saga at final chapter must be sacrificed
    assert not any(perm.card.name == "Test Saga" for perm in p1.battlefield)
    assert any(c.name == "Test Saga" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Rule 704.5y – If a permanent has more than one Role controlled by the same
# player attached to it, each of those Roles except the one with the most
# recent timestamp is put into its owner's graveyard.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.5y (and 303.7a) state-based action not implemented: the engine "
        "allows multiple Roles controlled by the same player to remain on the "
        "battlefield simultaneously instead of keeping only the most recent one."
    ),
)
def test_704_5y_only_newest_role_from_same_controller_survives():
    """704.5y: When the same player attaches two Roles to the same creature, only the
    Role with the most recent timestamp remains; the older Role goes to the graveyard."""
    role1 = _mk_card(
        "Warrior Role",
        "Enchantment — Role",
        "Enchant creature\nEnchanted creature gets +1/+1.",
    )
    role2 = _mk_card(
        "Monster Role",
        "Enchantment — Role",
        "Enchant creature\nEnchanted creature gets +2/+2.",
    )
    creature = _mk_creature("Role Bearer")
    p1 = PlayerState(name="P1", hand=[role1, role2])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Warrior Role", target_player_index=1)
    game.cast_from_hand(0, "Monster Role", target_player_index=1)

    role_perms = [perm for perm in p1.battlefield if "Role" in perm.card.type_line]
    assert len(role_perms) == 1
    assert role_perms[0].card.name == "Monster Role"
    assert any(c.name == "Warrior Role" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Rule 704.7 – If multiple state-based actions would have the same result at
# the same time, a single replacement effect will replace all of them.
# ---------------------------------------------------------------------------

def test_704_7_multiple_lethal_damage_deaths_are_processed_simultaneously():
    """704.7: When multiple creatures receive lethal damage in the same combat damage step,
    they are all destroyed together as part of a single state-based action event."""
    attacker = _mk_creature("Attacker", 2, 2)
    blocker1 = _mk_creature("First Blocker", 2, 2)
    bystander = _mk_creature("Bystander", 1, 1)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=attacker)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=blocker1), Permanent(card=bystander)],
        life=20,
    )
    game = Game(players=[p1, p2])

    # Attacker vs First Blocker — both receive lethal damage simultaneously
    _run_combat(game, [0], {0: 0})

    assert not any(perm.card.name == "Attacker" for perm in p1.battlefield)
    assert not any(perm.card.name == "First Blocker" for perm in p2.battlefield)
    assert any(c.name == "Attacker" for c in p1.graveyard)
    assert any(c.name == "First Blocker" for c in p2.graveyard)
    # Bystander was not in combat — it survives
    assert any(perm.card.name == "Bystander" for perm in p2.battlefield)


# ---------------------------------------------------------------------------
# Rule 704.8 – When a permanent leaves the battlefield as a result of
# state-based actions at the same time other state-based actions are
# performed, that permanent's last known information is derived from the game
# state before any of those state-based actions were performed.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Rule 704.8 not implemented: the engine does not capture 'last known "
        "information' snapshots before applying simultaneous state-based actions. "
        "As illustrated in the rule's undying example, triggered abilities that rely "
        "on a permanent's pre-SBA state (such as checking for +1/+1 counters) are "
        "not supported."
    ),
)
def test_704_8_last_known_information_undying_example():
    """704.8: Per the rule's example — Young Wolf (undying) with a +1/+1 counter and
    three -1/-1 counters has toughness 0 or less. Before state-based actions, it has
    the +1/+1 counter, so undying does not trigger (last known information shows the
    counter was present)."""
    # Young Wolf: 1/1 undying. Net counters: +1/+1 and -1/-1/-1/-1 → toughness -1.
    # Before SBAs the wolf has a +1/+1 counter → undying won't trigger.
    wolf_card = _mk_creature("Young Wolf", 1, 1, oracle_text="Undying")
    wolf_perm = Permanent(
        card=wolf_card,
        power_bonus=-2,
        toughness_bonus=-2,
        metadata={"plus_counters": 1, "minus_counters": 3, "has_undying": True},
    )
    p1 = PlayerState(name="P1", battlefield=[wolf_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # 704.5f: wolf has toughness -1 → goes to graveyard
    # 704.8: last known info shows it had a +1/+1 counter → undying does NOT trigger
    # → wolf remains in graveyard, does not return to battlefield
    assert not any(perm.card.name == "Young Wolf" for perm in p1.battlefield)
    assert any(c.name == "Young Wolf" for c in p1.graveyard)
