"""Per-card tests for the Arabian Nights set (cards/ARN_cards.json)."""

from __future__ import annotations

from unittest.mock import patch

from engine import Game, PlayerState
from engine.classifier import classify_card
from engine.models import Permanent


def _get(cards, name):
    return next(c for c in cards if c.name == name)


def _get_startswith(cards, prefix):
    return next(c for c in cards if c.name.startswith(prefix))


# ===========================================================================
# Untap-related static lines
# ===========================================================================

def test_brass_man_is_supported_and_does_not_untap(arn_by_name, all_cards):
    brass_man = arn_by_name["Brass Man"]
    program = classify_card(brass_man)
    assert program.supported

    plains = _get(all_cards, "Plains")
    perm = Permanent(card=brass_man, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[perm, Permanent(card=plains)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_untap_step(0)

    assert perm.tapped is True


def test_island_fish_jasconius_doesnt_untap_and_pay_to_untap_uses_creature_wording(arn_by_name):
    from engine.oracle import compile_card_oracle

    fish = arn_by_name["Island Fish Jasconius"]
    program = compile_card_oracle(fish)
    kinds = {ab.instruction.kind for ab in program.triggered_abilities if ab.instruction}
    assert "upkeep_pay_to_untap_self" in kinds


def test_island_fish_jasconius_pay_to_untap_untaps_it(arn_by_name, all_cards):
    fish = arn_by_name["Island Fish Jasconius"]
    island = _get(all_cards, "Island")
    perm = Permanent(card=fish, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[perm, Permanent(card=island)], mana_pool={"U": 3})
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0, human_choices={"Island Fish Jasconius": True})

    assert perm.tapped is False


def test_island_fish_jasconius_sacrificed_with_no_islands(arn_by_name):
    # "When you control no Islands, sacrifice this creature" — already
    # supported generically via the no_islands trigger + sacrifice_self.
    fish = arn_by_name["Island Fish Jasconius"]
    perm = Permanent(card=fish, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[perm], mana_pool={"U": 3})
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0, human_choices={"Island Fish Jasconius": True})

    assert perm not in p1.battlefield
    assert any(c.name == "Island Fish Jasconius" for c in p1.graveyard)


# ===========================================================================
# Conditional land-count bonus (generalized from Sedge Troll's swamp bonus)
# ===========================================================================

def test_kird_ape_gets_bonus_with_forest(arn_by_name, all_cards):
    ape = arn_by_name["Kird Ape"]
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ape), Permanent(card=forest)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    perm = p1.battlefield[0]
    assert perm.effective_power == 2
    assert perm.effective_toughness == 3


def test_kird_ape_no_bonus_without_forest(arn_by_name):
    ape = arn_by_name["Kird Ape"]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ape)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    perm = p1.battlefield[0]
    assert perm.effective_power == 1
    assert perm.effective_toughness == 1


# ===========================================================================
# Conditional own-tapped-state bonus
# ===========================================================================

def test_giant_tortoise_bonus_while_untapped(arn_by_name):
    tortoise = arn_by_name["Giant Tortoise"]
    perm = Permanent(card=tortoise, tapped=False)
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    assert perm.effective_power == 1
    assert perm.effective_toughness == 4


def test_giant_tortoise_loses_bonus_when_tapped(arn_by_name):
    tortoise = arn_by_name["Giant Tortoise"]
    perm = Permanent(card=tortoise, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    assert perm.effective_power == 1
    assert perm.effective_toughness == 1


# ===========================================================================
# Hurr Jackal — deny regeneration
# ===========================================================================

def test_hurr_jackal_denies_regeneration(arn_by_name, all_cards):
    jackal = arn_by_name["Hurr Jackal"]
    bear = _get(all_cards, "Grizzly Bears")
    target = Permanent(card=bear)
    target.regeneration_shield = 1
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=jackal)])
    p2 = PlayerState(name="P2", battlefield=[target])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Hurr Jackal", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert target.metadata.get("cant_be_regenerated_this_turn") is True


# ===========================================================================
# Set base power/toughness until end of turn
# ===========================================================================

def test_sorceress_queen_sets_base_pt_and_excludes_self(all_cards, arn_by_name):
    queen = arn_by_name["Sorceress Queen"]
    bear = _get(all_cards, "Grizzly Bears")
    target = Permanent(card=bear)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=queen)])
    p2 = PlayerState(name="P2", battlefield=[target])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Sorceress Queen", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert target.effective_power == 0
    assert target.effective_toughness == 2


def test_sorceress_queen_cannot_target_herself(arn_by_name):
    queen = arn_by_name["Sorceress Queen"]
    queen_perm = Permanent(card=queen)
    p1 = PlayerState(name="P1", battlefield=[queen_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Sorceress Queen", target_player_index=0, target_permanent_index=0)

    assert queen_perm.effective_power == 1
    assert queen_perm.effective_toughness == 1


def test_sorceress_queen_wears_off_at_cleanup(all_cards, arn_by_name):
    queen = arn_by_name["Sorceress Queen"]
    bear = _get(all_cards, "Grizzly Bears")
    target = Permanent(card=bear)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=queen)])
    p2 = PlayerState(name="P2", battlefield=[target])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Sorceress Queen", target_player_index=1, target_permanent_index=0)
    assert target.effective_power == 0

    game.resolve_cleanup_step(0)
    assert target.effective_power == 2
    assert target.effective_toughness == 2


def test_singing_tree_sets_power_only_of_attacking_creature(all_cards, arn_by_name):
    tree = arn_by_name["Singing Tree"]
    bear = _get(all_cards, "Grizzly Bears")
    attacker = Permanent(card=bear, attacking=True)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tree)])
    p2 = PlayerState(name="P2", battlefield=[attacker])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Singing Tree", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert attacker.effective_power == 0
    assert attacker.effective_toughness == 2  # untouched


def test_singing_tree_rejects_non_attacking_creature(all_cards, arn_by_name):
    tree = arn_by_name["Singing Tree"]
    bear = _get(all_cards, "Grizzly Bears")
    non_attacker = Permanent(card=bear, attacking=False)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tree)])
    p2 = PlayerState(name="P2", battlefield=[non_attacker])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Singing Tree", target_player_index=1, target_permanent_index=0)

    assert non_attacker.effective_power == 2


def test_island_of_wak_wak_sets_power_of_flying_creature(all_cards, arn_by_name):
    wak_wak = arn_by_name["Island of Wak-Wak"]
    flyer = _get(all_cards, "Air Elemental")
    target = Permanent(card=flyer)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wak_wak)])
    p2 = PlayerState(name="P2", battlefield=[target])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Island of Wak-Wak", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert target.effective_power == 0
    assert target.effective_toughness == 4  # untouched


def test_island_of_wak_wak_rejects_non_flying_creature(all_cards, arn_by_name):
    wak_wak = arn_by_name["Island of Wak-Wak"]
    bear = _get(all_cards, "Grizzly Bears")
    target = Permanent(card=bear)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wak_wak)])
    p2 = PlayerState(name="P2", battlefield=[target])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Island of Wak-Wak", target_player_index=1, target_permanent_index=0)

    assert target.effective_power == 2


# ===========================================================================
# King Suleiman / Elephant Graveyard — subtype-filtered targeting
# ===========================================================================

def test_king_suleiman_destroys_djinn(all_cards, arn_by_name):
    suleiman = arn_by_name["King Suleiman"]
    djinn = arn_by_name["Erhnam Djinn"]
    target = Permanent(card=djinn)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=suleiman)])
    p2 = PlayerState(name="P2", battlefield=[target])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "King Suleiman", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert target not in p2.battlefield


def test_king_suleiman_cannot_destroy_non_djinn_efreet(all_cards, arn_by_name):
    suleiman = arn_by_name["King Suleiman"]
    bear = _get(all_cards, "Grizzly Bears")
    target = Permanent(card=bear)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=suleiman)])
    p2 = PlayerState(name="P2", battlefield=[target])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "King Suleiman", target_player_index=1, target_permanent_index=0)

    assert target in p2.battlefield


def test_elephant_graveyard_regenerates_elephant_only(arn_by_name):
    graveyard = arn_by_name["Elephant Graveyard"]
    camel = arn_by_name["Camel"]  # not an Elephant
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=graveyard), Permanent(card=camel)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0, "Elephant Graveyard", target_player_index=0, target_permanent_index=1, ability_index=1,
    )

    assert not result.supported or p1.battlefield[1].regeneration_shield == 0


# ===========================================================================
# Land abilities beyond mana production
# ===========================================================================

def test_desert_pings_attacking_creature(all_cards, arn_by_name):
    desert = arn_by_name["Desert"]
    bear = _get(all_cards, "Grizzly Bears")
    attacker = Permanent(card=bear, attacking=True)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=desert)])
    p2 = PlayerState(name="P2", battlefield=[attacker])
    game = Game(players=[p1, p2])
    game._set_phase_and_step("combat", "end_of_combat")  # "Activate only during the end of combat step."

    result = game.activate_permanent_ability(
        0, "Desert", target_player_index=1, target_permanent_index=0, ability_index=1,
    )

    assert result.supported
    assert attacker.damage_marked == 1


def test_desert_nomads_immune_to_desert_damage(all_cards, arn_by_name):
    desert = arn_by_name["Desert"]
    nomads = arn_by_name["Desert Nomads"]
    attacker = Permanent(card=nomads, attacking=True)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=desert)])
    p2 = PlayerState(name="P2", battlefield=[attacker])
    game = Game(players=[p1, p2])
    game._set_phase_and_step("combat", "end_of_combat")

    game.activate_permanent_ability(0, "Desert", target_player_index=1, target_permanent_index=0, ability_index=1)

    assert attacker.damage_marked == 0


def test_camel_immune_to_desert_damage_while_attacking(all_cards, arn_by_name):
    desert = arn_by_name["Desert"]
    camel = arn_by_name["Camel"]
    attacker = Permanent(card=camel, attacking=True)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=desert)])
    p2 = PlayerState(name="P2", battlefield=[attacker])
    game = Game(players=[p1, p2])
    game._set_phase_and_step("combat", "end_of_combat")

    game.activate_permanent_ability(0, "Desert", target_player_index=1, target_permanent_index=0, ability_index=1)

    assert attacker.damage_marked == 0


def test_camel_not_immune_to_desert_damage_while_not_attacking(all_cards, arn_by_name):
    # The shield is conditional on Camel itself attacking (CR 113.7a: another
    # source's damage isn't affected once that condition is false).
    desert = arn_by_name["Desert"]
    camel = arn_by_name["Camel"]
    non_attacker = Permanent(card=camel, attacking=False)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=desert)])
    p2 = PlayerState(name="P2", battlefield=[non_attacker])
    game = Game(players=[p1, p2])

    # Desert's ability can only target ATTACKING creatures per its own text,
    # so drive the damage through the generic handler directly to isolate
    # the replacement-effect condition being tested.
    game._mark_damage_on_permanent(non_attacker, 1, source=p1.battlefield[0])

    assert non_attacker.damage_marked == 1


def test_bazaar_of_baghdad_draws_two_discards_three(all_cards, arn_by_name):
    bazaar = arn_by_name["Bazaar of Baghdad"]
    bear = _get(all_cards, "Grizzly Bears")
    starting_hand = [bear, bear, bear]
    library = [bear, bear]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=bazaar)], library=library, hand=starting_hand)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Bazaar of Baghdad", target_player_index=0)

    assert result.supported
    assert len(p1.hand) == 5  # 3 starting + 2 drawn, discard not yet resolved
    assert game.pending_discard is not None
    assert game.pending_discard["count"] == 3


def test_diamond_valley_gains_life_equal_to_sacrificed_toughness(all_cards, arn_by_name):
    valley = arn_by_name["Diamond Valley"]
    troll = _get(all_cards, "Sedge Troll")  # 2/2 base
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=valley), Permanent(card=troll)],
        life=20,
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0, "Diamond Valley", target_player_index=0, target_permanent_index=1,
    )

    assert result.supported
    assert p1.life == 22
    assert len(p1.battlefield) == 1


# ===========================================================================
# El-Hajjaj — gain life equal to damage dealt
# ===========================================================================

def test_el_hajjaj_gains_life_on_combat_damage_to_player(arn_by_name):
    hajjaj = arn_by_name["El-Hajjâj"]
    attacker = Permanent(card=hajjaj)
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game._fire_combat_damage_to_player_triggers(attacker, p2, 1)
    assert game.stack
    game._settle()

    assert not game.stack
    assert p1.life == 21


# ===========================================================================
# Serendib Djinn — upkeep land sacrifice + no-lands state trigger
# ===========================================================================

def test_serendib_djinn_sacrifices_island_and_takes_damage(all_cards, arn_by_name):
    djinn = arn_by_name["Serendib Djinn"]
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=djinn), Permanent(card=island)], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not any(p.card.primary_type == "land" for p in p1.battlefield)
    assert p1.life == 17


def test_serendib_djinn_sacrifices_non_island_no_damage(all_cards, arn_by_name):
    djinn = arn_by_name["Serendib Djinn"]
    mountain = _get(all_cards, "Mountain")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=djinn), Permanent(card=mountain)], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not any(p.card.primary_type == "land" for p in p1.battlefield)
    assert p1.life == 20


def test_serendib_djinn_sacrificed_when_no_lands_remain(arn_by_name):
    djinn = arn_by_name["Serendib Djinn"]
    perm = Permanent(card=djinn)
    p1 = PlayerState(name="P1", battlefield=[perm], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    assert perm not in p1.battlefield
    assert any(c.name == "Serendib Djinn" for c in p1.graveyard)


# ===========================================================================
# Rukh Egg — delayed token creation at the next end step
# ===========================================================================

def test_rukh_egg_arms_delayed_token_on_death(arn_by_name):
    egg = arn_by_name["Rukh Egg"]
    perm = Permanent(card=egg)
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    p1.battlefield.remove(perm)
    game._permanent_to_graveyard(p1, perm)

    assert len(game.pending_end_step_tokens) == 1
    spec = game.pending_end_step_tokens[0]
    assert spec["name"] == "Bird"
    assert spec["power"] == 4 and spec["toughness"] == 4
    assert spec["colors"] == ("R",)
    assert spec["keywords"] == ("Flying",)


def test_rukh_egg_token_appears_at_end_step(arn_by_name):
    egg = arn_by_name["Rukh Egg"]
    perm = Permanent(card=egg)
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    p1.battlefield.remove(perm)
    game._permanent_to_graveyard(p1, perm)
    game.resolve_end_step(0)

    bird = next((p for p in p1.battlefield if p.card.name == "Bird"), None)
    assert bird is not None
    assert bird.metadata.get("is_token") is True
    assert bird.effective_power == 4
    assert bird.effective_toughness == 4
    assert "Flying" in bird.card.keywords
    assert game.pending_end_step_tokens == []


# ===========================================================================
# Mijae Djinn / Ydwen Efreet — coin-flip combat triggers
# ===========================================================================

def _declare_combat(p1, p2):
    game = Game(players=[p1, p2])
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"
    return game


def test_mijae_djinn_stays_in_combat_on_win(arn_by_name):
    djinn = arn_by_name["Mijae Djinn"]
    attacker = Permanent(card=djinn)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", life=20)
    game = _declare_combat(p1, p2)

    with patch("engine.handlers.combat.random.random", return_value=0.0):
        ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
        assert ok
        game._settle()

    assert 0 in game.combat_attackers
    assert attacker.tapped is True  # tapped from attacking, not from losing


def test_mijae_djinn_removed_from_combat_and_tapped_on_loss(arn_by_name):
    djinn = arn_by_name["Mijae Djinn"]
    attacker = Permanent(card=djinn)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", life=20)
    game = _declare_combat(p1, p2)

    with patch("engine.handlers.combat.random.random", return_value=0.9):
        ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
        assert ok
        game._settle()

    assert 0 not in game.combat_attackers
    assert attacker.tapped is True


def test_ydwen_efreet_removed_from_combat_on_loss(all_cards, arn_by_name):
    efreet = arn_by_name["Ydwen Efreet"]
    bear = _get(all_cards, "Grizzly Bears")
    attacker = Permanent(card=bear)
    blocker = Permanent(card=efreet)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
    game = _declare_combat(p1, p2)

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    with patch("engine.handlers.combat.random.random", return_value=0.9):
        ok, _ = game.declare_blockers(1, {0: 0})
        assert ok
        game._settle()

    assert 1 not in game.combat_blockers
    assert not attacker.blocked


def test_ydwen_efreet_stays_blocking_on_win(all_cards, arn_by_name):
    efreet = arn_by_name["Ydwen Efreet"]
    bear = _get(all_cards, "Grizzly Bears")
    attacker = Permanent(card=bear)
    blocker = Permanent(card=efreet)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
    game = _declare_combat(p1, p2)

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    with patch("engine.handlers.combat.random.random", return_value=0.0):
        ok, _ = game.declare_blockers(1, {0: 0})
        assert ok
        game._settle()

    assert 1 in game.combat_blockers


# ===========================================================================
# Erhnam Djinn — grant forestwalk until next upkeep
# ===========================================================================

def test_erhnam_djinn_grants_forestwalk_to_opponent_creature(all_cards, arn_by_name):
    djinn = arn_by_name["Erhnam Djinn"]
    bear = _get(all_cards, "Grizzly Bears")
    target = Permanent(card=bear)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=djinn)])
    p2 = PlayerState(name="P2", battlefield=[target])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert game._has_keyword(target, "forestwalk")


def test_erhnam_djinn_skips_wall(all_cards, arn_by_name):
    djinn = arn_by_name["Erhnam Djinn"]
    wall = _get(all_cards, "Wall of Air")
    target = Permanent(card=wall)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=djinn)])
    p2 = PlayerState(name="P2", battlefield=[target])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not game._has_keyword(target, "forestwalk")


def test_erhnam_djinn_forestwalk_expires_at_next_upkeep(all_cards, arn_by_name):
    djinn = arn_by_name["Erhnam Djinn"]
    bear = _get(all_cards, "Grizzly Bears")
    target = Permanent(card=bear)
    djinn_perm = Permanent(card=djinn)
    p1 = PlayerState(name="P1", battlefield=[djinn_perm])
    p2 = PlayerState(name="P2", battlefield=[target])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)
    assert game._has_keyword(target, "forestwalk")

    # P2's upkeep passes (not the granting player's), so the grant persists.
    game.resolve_upkeep(1)
    assert game._has_keyword(target, "forestwalk")

    # Erhnam Djinn leaves before its next upkeep would re-grant a fresh one —
    # the earlier grant expires right on schedule.
    p1.battlefield.remove(djinn_perm)
    game.resolve_upkeep(0)
    assert not game._has_keyword(target, "forestwalk")


# ===========================================================================
# Nafs Asp — delayed life loss unless paid before next draw step
# ===========================================================================

def test_nafs_asp_arms_obligation_on_damage(arn_by_name):
    asp = arn_by_name["Nafs Asp"]
    attacker = Permanent(card=asp)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game._fire_combat_damage_to_player_triggers(attacker, p2, 1)
    game._settle()

    assert len(game.pending_draw_step_life_loss) == 1
    ob = game.pending_draw_step_life_loss[0]
    assert ob["player_index"] == 1
    assert ob["amount"] == 1 and ob["cost"] == 1


def test_nafs_asp_loses_life_if_unpaid(arn_by_name):
    asp = arn_by_name["Nafs Asp"]
    attacker = Permanent(card=asp)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", life=20, library=[], mana_pool={})
    game = Game(players=[p1, p2])

    game._fire_combat_damage_to_player_triggers(attacker, p2, 1)
    game._settle()
    game.resolve_draw_step(1)

    assert p2.life == 19
    assert game.pending_draw_step_life_loss == []


def test_nafs_asp_no_life_loss_if_paid(arn_by_name):
    asp = arn_by_name["Nafs Asp"]
    attacker = Permanent(card=asp)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", life=20, library=[], mana_pool={"C": 1})
    game = Game(players=[p1, p2])

    game._fire_combat_damage_to_player_triggers(attacker, p2, 1)
    game._settle()
    game.resolve_draw_step(1, pay_life_loss={"Nafs Asp": True})

    assert p2.life == 20
    assert game.pending_draw_step_life_loss == []


# ===========================================================================
# Erg Raiders — end-step damage if it didn't attack
# ===========================================================================

def test_erg_raiders_deals_damage_if_it_did_not_attack(arn_by_name):
    raiders = arn_by_name["Erg Raiders"]
    perm = Permanent(card=raiders)
    perm.metadata["summoning_sickness_turn"] = -99  # not new this turn
    p1 = PlayerState(name="P1", battlefield=[perm], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.turn = 5

    game.resolve_end_step(0)
    game.resolve_stack()

    assert p1.life == 18


def test_erg_raiders_no_damage_if_it_attacked(arn_by_name):
    raiders = arn_by_name["Erg Raiders"]
    perm = Permanent(card=raiders)
    perm.metadata["summoning_sickness_turn"] = -99
    perm.metadata["attacked_this_turn"] = True
    p1 = PlayerState(name="P1", battlefield=[perm], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.turn = 5

    game.resolve_end_step(0)
    game.resolve_stack()

    assert p1.life == 20


def test_erg_raiders_no_damage_if_it_just_came_under_control(arn_by_name):
    raiders = arn_by_name["Erg Raiders"]
    perm = Permanent(card=raiders)
    p1 = PlayerState(name="P1", battlefield=[perm], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.turn = 5
    perm.metadata["summoning_sickness_turn"] = game.turn  # came under control this turn

    game.resolve_end_step(0)
    game.resolve_stack()

    assert p1.life == 20


# ===========================================================================
# Ali from Cairo — life floor at 1
# ===========================================================================

def test_ali_from_cairo_floors_life_at_one(all_cards, arn_by_name):
    ali = arn_by_name["Ali from Cairo"]
    bolt = _get(all_cards, "Lightning Bolt")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ali)], life=3)
    p2 = PlayerState(name="P2", hand=[bolt])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)

    assert result.supported
    assert p1.life == 1


def test_ali_from_cairo_does_not_prevent_normal_damage(all_cards, arn_by_name):
    ali = arn_by_name["Ali from Cairo"]
    bolt = _get(all_cards, "Lightning Bolt")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ali)], life=20)
    p2 = PlayerState(name="P2", hand=[bolt])
    game = Game(players=[p1, p2])

    game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)

    assert p1.life == 17


def _combat_against(game: Game, attacker_indices: list[int]) -> None:
    """Run a full combat with the given attackers and no blocks."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    game.declare_blockers(1, {})
    game.advance_combat_phase()  # combat damage


def test_ali_from_cairo_floors_combat_damage_at_one(all_cards, arn_by_name):
    """The floor is not spell-only. Combat damage applies life loss on its own
    path, which used to skip the replacement entirely and kill through Ali."""
    from tests.helpers import _nosick

    ali = arn_by_name["Ali from Cairo"]
    ogre = _nosick(Permanent(card=_get(all_cards, "Hurloon Minotaur")))  # 2/3
    p1 = PlayerState(name="P1", battlefield=[ogre], life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=ali)], life=1)
    game = Game(players=[p1, p2])

    _combat_against(game, [0])

    assert p2.life == 1
    assert p2.lost is False


def test_ali_from_cairo_floors_combat_damage_from_several_attackers(all_cards, arn_by_name):
    """Each attacker's damage is applied in turn, and once the life total is at
    the floor the later ones take it no lower (CR 616.1f re-checks which
    effects still apply after each one)."""
    from tests.helpers import _nosick

    ali = arn_by_name["Ali from Cairo"]
    attackers = [
        _nosick(Permanent(card=_get(all_cards, "Hurloon Minotaur"))) for _ in range(3)
    ]
    p1 = PlayerState(name="P1", battlefield=attackers, life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=ali)], life=3)
    game = Game(players=[p1, p2])

    _combat_against(game, [0, 1, 2])

    assert p2.life == 1


def test_combat_damage_kills_a_player_without_ali_from_cairo(all_cards):
    """The control for the two tests above: the same combat is lethal when the
    floor is absent, so they cannot pass by simply dealing no damage."""
    from tests.helpers import _nosick

    ogre = _nosick(Permanent(card=_get(all_cards, "Hurloon Minotaur")))  # 2/3
    p1 = PlayerState(name="P1", battlefield=[ogre], life=20)
    p2 = PlayerState(name="P2", life=1)
    game = Game(players=[p1, p2])

    _combat_against(game, [0])

    assert p2.life == -1


def test_ali_from_cairo_does_not_protect_opponent(all_cards, arn_by_name):
    ali = arn_by_name["Ali from Cairo"]
    bolt = _get(all_cards, "Lightning Bolt")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ali)], life=20)
    p2 = PlayerState(name="P2", hand=[bolt], life=2)
    game = Game(players=[p1, p2])

    game.cast_from_hand(1, "Lightning Bolt", target_player_index=1)

    assert p2.life == -1


# ===========================================================================
# Aladdin — linked-duration artifact control steal
# ===========================================================================

def test_aladdin_steals_artifact(all_cards, arn_by_name):
    aladdin = arn_by_name["Aladdin"]
    lotus = _get(all_cards, "Black Lotus")
    stolen = Permanent(card=lotus)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=aladdin)])
    p2 = PlayerState(name="P2", battlefield=[stolen])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Aladdin", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert stolen in p1.battlefield
    assert stolen not in p2.battlefield


def test_aladdin_artifact_reverts_when_aladdin_leaves(all_cards, arn_by_name):
    aladdin = arn_by_name["Aladdin"]
    lotus = _get(all_cards, "Black Lotus")
    stolen = Permanent(card=lotus)
    aladdin_perm = Permanent(card=aladdin)
    p1 = PlayerState(name="P1", battlefield=[aladdin_perm])
    p2 = PlayerState(name="P2", battlefield=[stolen])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Aladdin", target_player_index=1, target_permanent_index=0)
    assert stolen in p1.battlefield

    p1.battlefield.remove(aladdin_perm)
    game._permanent_to_graveyard(p1, aladdin_perm)

    assert stolen in p2.battlefield
    assert stolen not in p1.battlefield


# ===========================================================================
# Ghazbân Ogre — control passes to whoever has the most life
# ===========================================================================

def test_ghazban_ogre_control_passes_to_life_leader(arn_cards):
    ogre = _get_startswith(arn_cards, "Ghazb")
    perm = Permanent(card=ogre)
    p1 = PlayerState(name="P1", battlefield=[perm], life=10)
    p2 = PlayerState(name="P2", life=25)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert perm in p2.battlefield
    assert perm not in p1.battlefield


def test_ghazban_ogre_stays_with_leader(arn_cards):
    ogre = _get_startswith(arn_cards, "Ghazb")
    perm = Permanent(card=ogre)
    p1 = PlayerState(name="P1", battlefield=[perm], life=25)
    p2 = PlayerState(name="P2", life=10)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert perm in p1.battlefield


def test_ghazban_ogre_no_change_on_tie(arn_cards):
    ogre = _get_startswith(arn_cards, "Ghazb")
    perm = Permanent(card=ogre)
    p1 = PlayerState(name="P1", battlefield=[perm], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert perm in p1.battlefield


# ===========================================================================
# Magnetic Mountain — blue creatures don't untap; pay {4} each to untap anyway
# ===========================================================================

def test_magnetic_mountain_blocks_blue_creature_untap(all_cards, arn_by_name):
    mountain = arn_by_name["Magnetic Mountain"]
    flyer = _get(all_cards, "Air Elemental")  # blue creature
    blocked = Permanent(card=flyer, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mountain), blocked])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_untap_step(0)

    assert blocked.tapped is True


def test_magnetic_mountain_does_not_block_other_colors(all_cards, arn_by_name):
    mountain = arn_by_name["Magnetic Mountain"]
    bear = _get(all_cards, "Grizzly Bears")  # green creature
    unaffected = Permanent(card=bear, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mountain), unaffected])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_untap_step(0)

    assert unaffected.tapped is False


def test_magnetic_mountain_pays_to_untap_at_upkeep(all_cards, arn_by_name):
    mountain = arn_by_name["Magnetic Mountain"]
    flyer = _get(all_cards, "Air Elemental")
    blocked = Permanent(card=flyer, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mountain), blocked], mana_pool={"C": 4})
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert blocked.tapped is False
    assert sum(p1.mana_pool.values()) == 0


def test_magnetic_mountain_no_untap_without_mana(all_cards, arn_by_name):
    mountain = arn_by_name["Magnetic Mountain"]
    flyer = _get(all_cards, "Air Elemental")
    blocked = Permanent(card=flyer, tapped=True)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mountain), blocked])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert blocked.tapped is True


# ===========================================================================
# Guardian Beast — untapped artifact protection
# ===========================================================================

def test_guardian_beast_grants_indestructible_while_untapped(all_cards, arn_by_name):
    beast = arn_by_name["Guardian Beast"]
    lotus = _get(all_cards, "Black Lotus")
    protected = Permanent(card=lotus)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=beast, tapped=False), protected])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert game._is_indestructible(protected)


def test_guardian_beast_no_protection_while_tapped(all_cards, arn_by_name):
    beast = arn_by_name["Guardian Beast"]
    lotus = _get(all_cards, "Black Lotus")
    unprotected = Permanent(card=lotus)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=beast, tapped=True), unprotected])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert not game._is_indestructible(unprotected)


def test_guardian_beast_blocks_control_theft(all_cards, arn_by_name):
    beast = arn_by_name["Guardian Beast"]
    aladdin = arn_by_name["Aladdin"]
    lotus = _get(all_cards, "Black Lotus")
    protected = Permanent(card=lotus)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=beast, tapped=False), protected])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=aladdin)])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(1, "Aladdin", target_player_index=0, target_permanent_index=1)

    assert protected in p1.battlefield


# ===========================================================================
# City in a Bottle — set-membership ban and sacrifice
# ===========================================================================

def test_city_in_a_bottle_sacrifices_other_arn_permanents(arn_by_name):
    bottle = arn_by_name["City in a Bottle"]
    camel = arn_by_name["Camel"]
    camel_perm = Permanent(card=camel)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=bottle), camel_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    assert camel_perm not in p1.battlefield
    assert any(c.name == "Camel" for c in p1.graveyard)


def test_city_in_a_bottle_does_not_sacrifice_itself_or_other_sets(all_cards, arn_by_name):
    bottle = arn_by_name["City in a Bottle"]
    bottle_perm = Permanent(card=bottle)
    bear = _get(all_cards, "Grizzly Bears")  # LEA card, not ARN
    bear_perm = Permanent(card=bear)
    p1 = PlayerState(name="P1", battlefield=[bottle_perm, bear_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    assert bottle_perm in p1.battlefield
    assert bear_perm in p1.battlefield


def test_city_in_a_bottle_bans_casting_arn_cards(arn_by_name):
    bottle = arn_by_name["City in a Bottle"]
    camel = arn_by_name["Camel"]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=bottle)], hand=[camel])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Camel", target_player_index=0)

    assert not result.supported
    assert camel in p1.hand


def test_city_in_a_bottle_does_not_ban_other_sets(all_cards, arn_by_name):
    bottle = arn_by_name["City in a Bottle"]
    bear = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=bottle)], hand=[bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Grizzly Bears", target_player_index=0)

    assert result.supported


def test_city_of_brass_damages_controller_when_tapped(arn_by_name):
    brass = arn_by_name["City of Brass"]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=brass)], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(0, "City of Brass", chosen_color="W")

    assert ok
    assert p1.life == 19


# ===========================================================================
# Upkeep self-damage — "this creature deals N damage to you" (Juzám Djinn,
# Serendib Efreet). Fires only on the controller's own upkeep.
# ===========================================================================

def test_juzam_djinn_deals_upkeep_damage_to_controller(arn_by_name):
    juzam = arn_by_name["Juzám Djinn"]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=juzam)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert p1.life == 19


def test_juzam_djinn_does_not_damage_on_opponents_upkeep(arn_by_name):
    juzam = arn_by_name["Juzám Djinn"]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=juzam)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p1.life == 20


def test_serendib_efreet_deals_upkeep_damage_to_controller(arn_by_name):
    efreet = arn_by_name["Serendib Efreet"]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=efreet)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert p1.life == 19


# ===========================================================================
# Old Man of the Sea — conditional control-steal, reverts continuously
# ===========================================================================

def test_old_man_of_the_sea_steals_weaker_creature(arn_by_name):
    old_man = arn_by_name["Old Man of the Sea"]
    camel = arn_by_name["Camel"]
    camel_perm = Permanent(card=camel)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=old_man)])
    p2 = PlayerState(name="P2", battlefield=[camel_perm])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Old Man of the Sea", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert camel_perm in p1.battlefield
    assert camel_perm not in p2.battlefield


def test_old_man_of_the_sea_cannot_steal_stronger_creature(arn_by_name):
    old_man = arn_by_name["Old Man of the Sea"]
    djinn = arn_by_name["Erhnam Djinn"]
    djinn_perm = Permanent(card=djinn)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=old_man)])
    p2 = PlayerState(name="P2", battlefield=[djinn_perm])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Old Man of the Sea", target_player_index=1, target_permanent_index=0)

    assert djinn_perm in p2.battlefield
    assert djinn_perm not in p1.battlefield


def test_old_man_of_the_sea_reverts_when_it_untaps(arn_by_name):
    old_man = arn_by_name["Old Man of the Sea"]
    camel = arn_by_name["Camel"]
    camel_perm = Permanent(card=camel)
    old_man_perm = Permanent(card=old_man)
    p1 = PlayerState(name="P1", battlefield=[old_man_perm])
    p2 = PlayerState(name="P2", battlefield=[camel_perm])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Old Man of the Sea", target_player_index=1, target_permanent_index=0)
    assert camel_perm in p1.battlefield

    old_man_perm.tapped = False
    game.check_state_based_actions()

    assert camel_perm in p2.battlefield
    assert camel_perm not in p1.battlefield


def test_old_man_of_the_sea_reverts_when_stolen_creature_gets_stronger(arn_by_name):
    from engine.pt import add_pt_modifier

    old_man = arn_by_name["Old Man of the Sea"]
    camel = arn_by_name["Camel"]
    camel_perm = Permanent(card=camel)
    old_man_perm = Permanent(card=old_man)
    p1 = PlayerState(name="P1", battlefield=[old_man_perm])
    p2 = PlayerState(name="P2", battlefield=[camel_perm])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Old Man of the Sea", target_player_index=1, target_permanent_index=0)
    assert camel_perm in p1.battlefield

    add_pt_modifier(camel_perm, power=5)
    game.check_state_based_actions()

    assert camel_perm in p2.battlefield
    assert camel_perm not in p1.battlefield


def test_old_man_of_the_sea_reverts_when_it_leaves(arn_by_name):
    old_man = arn_by_name["Old Man of the Sea"]
    camel = arn_by_name["Camel"]
    camel_perm = Permanent(card=camel)
    old_man_perm = Permanent(card=old_man)
    p1 = PlayerState(name="P1", battlefield=[old_man_perm])
    p2 = PlayerState(name="P2", battlefield=[camel_perm])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Old Man of the Sea", target_player_index=1, target_permanent_index=0)
    assert camel_perm in p1.battlefield

    p1.battlefield.remove(old_man_perm)
    game._permanent_to_graveyard(p1, old_man_perm)

    assert camel_perm in p2.battlefield
    assert camel_perm not in p1.battlefield


# ===========================================================================
# Oubliette — scoped phasing (exile-and-return linked to the source)
# ===========================================================================

def test_oubliette_phases_out_target_creature(arn_by_name):
    oubliette = arn_by_name["Oubliette"]
    camel = arn_by_name["Camel"]
    camel_perm = Permanent(card=camel)
    p1 = PlayerState(name="P1", hand=[oubliette])
    p2 = PlayerState(name="P2", battlefield=[camel_perm])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Oubliette", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert camel_perm not in p2.battlefield
    oubliette_perm = p1.battlefield[0]
    assert oubliette_perm.metadata.get("phased_out_permanent") is camel_perm


def test_oubliette_returns_creature_tapped_when_it_leaves(arn_by_name):
    oubliette = arn_by_name["Oubliette"]
    camel = arn_by_name["Camel"]
    camel_perm = Permanent(card=camel)
    p1 = PlayerState(name="P1", hand=[oubliette])
    p2 = PlayerState(name="P2", battlefield=[camel_perm])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Oubliette", target_player_index=1, target_permanent_index=0)
    oubliette_perm = p1.battlefield[0]

    p1.battlefield.remove(oubliette_perm)
    game._permanent_to_graveyard(p1, oubliette_perm)

    assert camel_perm in p2.battlefield
    assert camel_perm.tapped


def test_oubliette_phased_out_creature_is_invisible_to_state_based_actions(arn_by_name):
    oubliette = arn_by_name["Oubliette"]
    camel = arn_by_name["Camel"]
    camel_perm = Permanent(card=camel)
    p1 = PlayerState(name="P1", hand=[oubliette], life=20)
    p2 = PlayerState(name="P2", battlefield=[camel_perm], life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Oubliette", target_player_index=1, target_permanent_index=0)
    game.check_state_based_actions()

    assert camel_perm not in p2.battlefield
    assert camel_perm not in p1.battlefield
    assert not any(c.name == "Camel" for c in p2.graveyard)


# ===========================================================================
# Piety — "Blocking creatures get +0/+3 until end of turn."
# (Found by the parse-coverage deletion probe: the "blocking" qualifier was
# being dropped, buffing every creature.)
# ===========================================================================

def test_piety_buffs_only_blocking_creatures(arn_by_name, all_cards):
    piety = arn_by_name["Piety"]
    attacker = Permanent(card=_get(all_cards, "Grizzly Bears"))
    attacker.metadata["summoning_sickness_turn"] = -99
    blocker = Permanent(card=_get(all_cards, "Scryb Sprites"))
    idle = Permanent(card=_get(all_cards, "Pearled Unicorn"))

    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", hand=[piety], battlefield=[blocker, idle])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = 1
    game.declare_attackers(0, [0], 1)
    game._set_phase_and_step("combat", "declare_blockers")
    game.declare_blockers(1, {0: 0})

    result = game.cast_from_hand(1, "Piety", target_player_index=0)
    assert result.supported
    game.resolve_stack()

    assert blocker.effective_toughness == 4   # 1 + 3
    assert idle.effective_toughness == 2      # untouched
    assert attacker.effective_toughness == 2  # untouched


# ===========================================================================
# Fixes for gaps found by the parse-coverage validator
# ===========================================================================

def test_cyclone_pays_and_deals_wind_counter_damage(arn_by_name, all_cards):
    cyclone = Permanent(card=arn_by_name["Cyclone"])
    sprite = Permanent(card=_get(all_cards, "Scryb Sprites"))  # 1/1 dies to 1
    p1 = PlayerState(name="P1", battlefield=[cyclone], mana_pool={"G": 1}, life=20)
    p2 = PlayerState(name="P2", battlefield=[sprite], life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert cyclone.metadata.get("wind_counters") == 1
    assert cyclone in p1.battlefield  # paid, not sacrificed
    assert p1.mana_pool.get("G") == 0
    assert p1.life == 19 and p2.life == 19
    assert sprite not in p2.battlefield  # 1 damage killed the 1/1


def test_cyclone_sacrificed_when_green_cannot_be_paid(arn_by_name):
    cyclone = Permanent(card=arn_by_name["Cyclone"])
    p1 = PlayerState(name="P1", battlefield=[cyclone], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert cyclone not in p1.battlefield
    assert any(c.name == "Cyclone" for c in p1.graveyard)
    assert p1.life == 20 and p2.life == 20  # no payment, no damage


def test_cyclone_upkeep_prompt_quotes_escalated_cost(arn_by_name):
    cyclone = Permanent(card=arn_by_name["Cyclone"])
    cyclone.metadata["wind_counters"] = 2
    p1 = PlayerState(name="P1", battlefield=[cyclone])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    choices = game.get_upkeep_pay_triggers(0)
    entry = next(c for c in choices if c["card_name"] == "Cyclone")
    assert entry["mana"] == {"G": 3}  # this upkeep's counter is included


def test_eye_for_an_eye_mirrors_damage_to_source_controller(arn_by_name, all_cards):
    from tests.helpers import _game as _mk_game, _nosick as _clear_sick

    p1 = PlayerState(name="P1", hand=[arn_by_name["Eye for an Eye"]], life=20)
    p2 = PlayerState(
        name="P2",
        battlefield=[_clear_sick(Permanent(card=_get(all_cards, "Orcish Artillery")))],
        life=20,
    )
    game = _mk_game(p1, p2)
    game.cast_from_hand(0, "Eye for an Eye", target_player_index=1)
    game.resolve_stack()
    assert p1.mirror_damage_charges == 1

    # Orcish Artillery: "{T}: deals 2 damage to any target and 3 damage to you."
    game.activate_permanent_ability(1, "Orcish Artillery", target_player_index=0)

    assert p1.life == 18            # the damage still happens
    assert p2.life == 20 - 3 - 2    # its own 3, plus the mirrored 2
    assert p1.mirror_damage_charges == 0  # one-shot


def test_unstable_mutation_decays_the_enchanted_creature(arn_by_name, all_cards):
    bear = Permanent(card=_get(all_cards, "Grizzly Bears"))
    mutation = Permanent(card=arn_by_name["Unstable Mutation"])
    mutation.metadata["attached_to"] = bear
    bear.metadata["attached_aura"] = mutation
    bear.power_bonus += 3
    bear.toughness_bonus += 3  # the aura's +3/+3, as applied at attach
    p1 = PlayerState(name="P1", battlefield=[bear, mutation])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)
    assert bear.effective_power == 4 and bear.effective_toughness == 4

    game.resolve_upkeep(0)
    assert bear.effective_power == 3 and bear.effective_toughness == 3


def test_unstable_mutation_decay_kills_at_zero_toughness(arn_by_name, all_cards):
    bear = Permanent(card=_get(all_cards, "Grizzly Bears"))
    mutation = Permanent(card=arn_by_name["Unstable Mutation"])
    mutation.metadata["attached_to"] = bear
    bear.metadata["attached_aura"] = mutation
    bear.toughness_bonus -= 1  # next counter takes the 2/2 to toughness 0
    p1 = PlayerState(name="P1", battlefield=[bear, mutation])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert bear not in p1.battlefield
    assert any(c.name == "Grizzly Bears" for c in p1.graveyard)


def test_drop_of_honey_destroys_least_power_creature(arn_by_name, all_cards):
    honey = Permanent(card=arn_by_name["Drop of Honey"])
    sprite = Permanent(card=_get(all_cards, "Scryb Sprites"))   # 1/1
    giant = Permanent(card=_get(all_cards, "Hill Giant"))       # 3/3
    sprite.regeneration_shield = 1  # "It can't be regenerated."
    p1 = PlayerState(name="P1", battlefield=[honey, giant])
    p2 = PlayerState(name="P2", battlefield=[sprite])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert sprite not in p2.battlefield
    assert any(c.name == "Scryb Sprites" for c in p2.graveyard)
    assert giant in p1.battlefield


def test_ifh_biff_efreet_damages_fliers_and_players(arn_by_name, all_cards):
    from tests.helpers import _nosick as _clear_sick

    efreet = _clear_sick(Permanent(card=arn_by_name["Ifh-Bíff Efreet"]))
    flier = Permanent(card=_get(all_cards, "Scryb Sprites"))     # 1/1 flying
    grounded = Permanent(card=_get(all_cards, "Grizzly Bears"))  # no flying
    p1 = PlayerState(name="P1", battlefield=[efreet], mana_pool={"G": 1}, life=20)
    p2 = PlayerState(name="P2", battlefield=[flier, grounded], life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Ifh-Bíff Efreet", target_player_index=1)

    assert result.supported
    assert p1.life == 19 and p2.life == 19  # each player
    assert flier not in p2.battlefield      # 1 damage killed the 1/1 flier
    assert grounded in p2.battlefield       # non-fliers untouched
    # The Efreet is itself a 3/3 flier - it took the 1 damage too.
    assert efreet.damage_marked == 1


def test_ifh_biff_efreet_any_player_may_activate(arn_by_name):
    from tests.helpers import _nosick as _clear_sick

    efreet = _clear_sick(Permanent(card=arn_by_name["Ifh-Bíff Efreet"]))
    p1 = PlayerState(name="P1", battlefield=[efreet], life=20)
    p2 = PlayerState(name="P2", mana_pool={"G": 1}, life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True  # prove the ACTIVATOR pays the {G}

    # The OPPONENT (seat 1) activates the seat-0 Efreet's ability and pays.
    result = game.activate_permanent_ability(
        1, "Ifh-Bíff Efreet", target_player_index=0, source_controller_index=0
    )

    assert result.supported
    assert p2.mana_pool.get("G") == 0
    assert p1.life == 19 and p2.life == 19


def test_only_controller_may_activate_ordinary_abilities(arn_by_name, all_cards):
    from tests.helpers import _game as _mk_game, _nosick as _clear_sick

    sindbad = _clear_sick(Permanent(card=arn_by_name["Sindbad"]))
    p1 = PlayerState(name="P1", battlefield=[sindbad], library=[_get(all_cards, "Forest")])
    p2 = PlayerState(name="P2")
    game = _mk_game(p1, p2)

    result = game.activate_permanent_ability(
        1, "Sindbad", target_player_index=0, source_controller_index=0
    )

    assert not result.supported
    assert "controller" in result.details


def test_desert_ping_gated_to_end_of_combat(arn_by_name, all_cards):
    desert = Permanent(card=arn_by_name["Desert"])
    attacker = Permanent(card=_get(all_cards, "Grizzly Bears"), attacking=True)
    p1 = PlayerState(name="P1", battlefield=[desert])
    p2 = PlayerState(name="P2", battlefield=[attacker])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0, "Desert", target_player_index=1, target_permanent_index=0, ability_index=1
    )

    assert not result.supported
    assert "end of combat" in result.details
    assert attacker.damage_marked == 0


def test_merchant_ship_gains_life_only_when_unblocked(arn_by_name, all_cards):
    from tests.helpers import _game as _mk_game, _nosick as _clear_sick

    ship = _clear_sick(Permanent(card=arn_by_name["Merchant Ship"]))
    island = Permanent(card=_get(all_cards, "Island"))
    p1 = PlayerState(name="P1", battlefield=[ship, island], life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=_get(all_cards, "Island"))], life=20)
    game = _mk_game(p1, p2)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.declare_attackers(0, [0])
    game.resolve_stack()
    assert p1.life == 20  # NOT at attack declaration any more

    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    game.resolve_stack()
    assert p1.life == 22  # unblocked: the trigger fired with blocks known


def test_merchant_ship_gains_nothing_when_blocked(arn_by_name, all_cards):
    from tests.helpers import _game as _mk_game, _nosick as _clear_sick

    ship = _clear_sick(Permanent(card=arn_by_name["Merchant Ship"]))
    island = Permanent(card=_get(all_cards, "Island"))
    blocker = _clear_sick(Permanent(card=_get(all_cards, "Grizzly Bears")))
    p1 = PlayerState(name="P1", battlefield=[ship, island], life=20)
    p2 = PlayerState(
        name="P2",
        battlefield=[blocker, Permanent(card=_get(all_cards, "Island"))],
        life=20,
    )
    game = _mk_game(p1, p2)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.declare_attackers(0, [0])
    game.resolve_stack()
    game._set_phase_and_step("combat", "declare_blockers")
    game.declare_blockers(1, {0: 0})
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    game.resolve_stack()

    assert p1.life == 20  # blocked: no life


def test_merchant_ship_gains_life_once_across_both_strike_passes(arn_by_name, all_cards):
    """CR 510.4 gives a combat two damage steps when anything in it has first
    strike, and the "attacked and wasn't blocked" trigger is fired from the
    method that runs one step. A first striker attacking beside the Ship used to
    hand the Ship's trigger to the stack once per step — 4 life instead of 2 —
    because the guard on it tested ``combat_damage_resolved``, which the
    first-strike pass deliberately leaves False."""
    from tests.helpers import _game as _mk_game, _nosick as _clear_sick

    ship = _clear_sick(Permanent(card=arn_by_name["Merchant Ship"]))
    island = Permanent(card=_get(all_cards, "Island"))
    # White Knight has first strike, so CR 510.4's second damage step exists.
    knight = _clear_sick(Permanent(card=_get(all_cards, "White Knight")))
    p1 = PlayerState(name="P1", battlefield=[ship, island, knight], life=20)
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=_get(all_cards, "Island"))], life=20
    )
    game = _mk_game(p1, p2)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.declare_attackers(0, [0, 2])
    game.resolve_stack()

    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_all_combat_damage(0)
    game.resolve_stack()

    assert game.combat_first_strike_done and game.combat_damage_resolved
    assert (
        game.log.count("Merchant Ship triggered (attacked and wasn't blocked)") == 1
    ), "the trigger belongs to the combat, not to each of its damage steps"
    assert p1.life == 22


# ===========================================================================
# Ebony Horse — untap + "prevent all combat damage dealt to and by"
# ===========================================================================

def test_ebony_horse_untaps_attacker_and_prevents_combat_damage(arn_by_name, all_cards):
    from tests.helpers import _nosick

    horse = Permanent(card=arn_by_name["Ebony Horse"])
    attacker = _nosick(Permanent(card=_get(all_cards, "Grizzly Bears")))  # 2/2
    blocker = Permanent(card=_get(all_cards, "Hill Giant"))               # 3/3
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[horse, attacker], library=[island])
    p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, _ = game.declare_attackers(0, [1])
    assert ok
    game.advance_combat_phase()  # declare_blockers
    ok, _ = game.declare_blockers(1, {0: 1})
    assert ok

    result = game.activate_permanent_ability(
        0, "Ebony Horse", target_player_index=0, target_permanent_index=1
    )
    assert result.supported
    assert attacker.tapped is False
    assert attacker.metadata.get("prevent_combat_damage_to_and_by_until_eot") is True

    game.advance_combat_phase()  # combat damage auto-resolves (single blocker)
    # "Prevent all combat damage that would be dealt to and dealt by that
    # creature this turn": neither side of the blocked combat marks damage.
    assert blocker.damage_marked == 0
    assert attacker.damage_marked == 0
    assert p2.life == 20


def test_ebony_horse_shield_expires_in_cleanup(arn_by_name, all_cards):
    horse_target = Permanent(card=_get(all_cards, "Grizzly Bears"))
    horse_target.metadata["prevent_combat_damage_to_and_by_until_eot"] = True
    p1 = PlayerState(name="P1", battlefield=[horse_target])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_cleanup_step(0)

    assert horse_target.metadata.get("prevent_combat_damage_to_and_by_until_eot") is None


# ===========================================================================
# Jihad — enter choice, conditional anthem, auto-sacrifice
# ===========================================================================

def test_jihad_defaults_conditional_anthem_and_auto_sacrifice(arn_by_name, all_cards):
    jihad = arn_by_name["Jihad"]
    white_knight = Permanent(card=_get(all_cards, "White Knight"))  # white 2/2
    green_perm = Permanent(card=_get(all_cards, "Grizzly Bears"))   # green nontoken
    p1 = PlayerState(name="P1", hand=[jihad], battlefield=[white_knight])
    p2 = PlayerState(name="P2", battlefield=[green_perm])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Jihad", target_player_index=1)

    assert result.supported
    jihad_perm = next(p for p in p1.battlefield if p.card.name == "Jihad")
    # Headless defaults: the cast target, and the color they control most of.
    assert jihad_perm.metadata.get("chosen_player_index") == 1
    assert jihad_perm.metadata.get("chosen_color") == "G"
    # Anthem is live while the chosen player controls a green nontoken permanent.
    assert white_knight.effective_power == 4
    assert white_knight.effective_toughness == 3

    # The last green permanent leaves: Jihad is sacrificed and the buff ends.
    p2.battlefield.remove(green_perm)
    game.check_state_based_actions()
    assert all(p.card.name != "Jihad" for p in p1.battlefield)
    assert any(c.name == "Jihad" for c in p1.graveyard)
    assert white_knight.effective_power == 2


def test_jihad_interactive_prompt_confirms_color_and_opponent(arn_by_name, all_cards):
    jihad = arn_by_name["Jihad"]
    white_perm = Permanent(card=_get(all_cards, "White Knight"))
    green_perm = Permanent(card=_get(all_cards, "Grizzly Bears"))
    p1 = PlayerState(name="P1", hand=[jihad])
    p2 = PlayerState(name="P2", battlefield=[green_perm, white_perm])
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}

    result = game.cast_from_hand(0, "Jihad", target_player_index=1)

    assert result.supported
    pending = game.pending_enter_choice
    assert pending is not None
    assert pending["needs_color"] is True
    assert pending["opponents"] == [1]

    assert game.confirm_enter_choice(0, 1, "W") is True
    jihad_perm = next(p for p in p1.battlefield if p.card.name == "Jihad")
    assert jihad_perm.metadata.get("chosen_color") == "W"
    assert jihad_perm.metadata.get("chosen_player_index") == 1
    assert game.pending_enter_choice is None
    # Still alive: the chosen player controls a white nontoken permanent.
    assert any(p.card.name == "Jihad" for p in p1.battlefield)


# ===========================================================================
# Drop of Honey — the controller chooses among creatures tied for least power
# ===========================================================================

def test_drop_of_honey_tie_prompts_human_controller(arn_by_name, all_cards):
    honey = Permanent(card=arn_by_name["Drop of Honey"])
    own_sprite = Permanent(card=_get(all_cards, "Scryb Sprites"))   # 1/1
    enemy_hero = Permanent(card=_get(all_cards, "Benalish Hero"))   # 1/1
    p1 = PlayerState(name="P1", battlefield=[honey, own_sprite])
    p2 = PlayerState(name="P2", battlefield=[enemy_hero])
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}

    game.resolve_upkeep(0)

    pending = game.pending_least_power_choice
    assert pending is not None
    assert pending["controller_index"] == 0
    assert {c["name"] for c in pending["candidates"]} == {"Scryb Sprites", "Benalish Hero"}
    # Nothing is destroyed until the controller picks.
    assert own_sprite in p1.battlefield and enemy_hero in p2.battlefield

    assert game.confirm_least_power_choice(0, 1, 0) is True
    assert enemy_hero not in p2.battlefield
    assert any(c.name == "Benalish Hero" for c in p2.graveyard)
    assert own_sprite in p1.battlefield
    assert game.pending_least_power_choice is None


def test_drop_of_honey_tie_rejects_non_candidate_choice(arn_by_name, all_cards):
    honey = Permanent(card=arn_by_name["Drop of Honey"])
    sprite = Permanent(card=_get(all_cards, "Scryb Sprites"))  # 1/1 (tied)
    hero = Permanent(card=_get(all_cards, "Benalish Hero"))    # 1/1 (tied)
    giant = Permanent(card=_get(all_cards, "Hill Giant"))      # 3/3 (not tied)
    p1 = PlayerState(name="P1", battlefield=[honey, sprite])
    p2 = PlayerState(name="P2", battlefield=[hero, giant])
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}

    game.resolve_upkeep(0)

    assert game.pending_least_power_choice is not None
    # The 3/3 is not tied for least power — an illegal pick is refused.
    assert game.confirm_least_power_choice(0, 1, 1) is False
    assert giant in p2.battlefield
    assert game.pending_least_power_choice is not None


# ===========================================================================
# Metamorphosis — "Spend this mana only to cast creature spells."
# ===========================================================================

def test_metamorphosis_mana_spendable_only_on_creature_spells(arn_by_name, all_cards):
    metamorphosis = arn_by_name["Metamorphosis"]
    bears_card = _get(all_cards, "Grizzly Bears")   # {1}{G} creature
    vise_card = _get(all_cards, "Black Vise")       # {1} artifact
    fodder = Permanent(card=_get(all_cards, "Hill Giant"))  # mana value 4 -> X = 5
    p1 = PlayerState(
        name="P1",
        hand=[metamorphosis, bears_card, vise_card],
        battlefield=[fodder],
        mana_pool={"G": 1},
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True

    result = game.cast_from_hand(0, "Metamorphosis", target_permanent_index=0, new_color="G")

    assert result.supported
    assert any(c.name == "Hill Giant" for c in p1.graveyard)
    # 1 + mana value 4 = 5 green mana, restricted to creature spells.
    assert p1.creature_only_mana.get("G") == 5
    assert p1.mana_pool.get("G", 0) == 0

    # A noncreature spell can't be paid with the restricted mana.
    result = game.cast_from_hand(0, "Black Vise", target_player_index=1)
    assert not result.supported
    assert "insufficient mana" in result.details

    # A creature spell can — and consumes the restricted mana first.
    result = game.cast_from_hand(0, "Grizzly Bears")
    assert result.supported
    assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)
    assert p1.creature_only_mana.get("G") == 3


# ===========================================================================
# Shahrazad — subgame simplification: the caster is treated as the winner
# ===========================================================================

def test_shahrazad_halves_opponent_life_rounded_up(arn_by_name):
    """"Players play a Magic subgame... Each player who doesn't win the subgame
    loses half their life, rounded up."

    Subgames are out of scope, so the engine resolves the documented
    simplification: the caster is the winner and everyone else pays. Before
    this, the card matched the whitelist's bare "loses" pattern and resolved
    as a no-op while reporting supported."""
    p1 = PlayerState(name="P1", hand=[arn_by_name["Shahrazad"]], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Shahrazad", target_player_index=1)

    assert result.supported
    assert p2.life == 10
    assert p1.life == 20, "the caster is treated as the subgame's winner"


def test_shahrazad_rounds_the_loss_up(arn_by_name):
    """Half of an odd life total rounds up: at 7 life the loss is 4, not 3."""
    p1 = PlayerState(name="P1", hand=[arn_by_name["Shahrazad"]], life=20)
    p2 = PlayerState(name="P2", life=7)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Shahrazad", target_player_index=1)

    assert p2.life == 3


def test_shahrazad_says_in_the_log_that_the_subgame_was_not_played(arn_by_name):
    """A simplification a player can see is a different thing from a card that
    quietly does nothing, so the log names it rather than reporting the effect
    as though it were the printed card."""
    p1 = PlayerState(name="P1", hand=[arn_by_name["Shahrazad"]], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Shahrazad", target_player_index=1)

    assert any("subgame not played" in line for line in game.log)


# ===========================================================================
# Modal activated abilities (CR 700.2)
# ===========================================================================

def test_pyramids_modal_head_is_read_by_the_parser_not_a_regex(arn_by_name):
    """Pyramids' "{2}: Choose one —" becomes one activated ability per bullet,
    and *which lines get that treatment* is now the grammar's answer.

    The head used to be matched by a regex that admitted a run of mana symbols
    followed by the literal words "choose one" — so the count could never be
    anything else and any other cost shape would have been left as an
    unreadable head line with two orphan bullets under it. The card compiles
    the same way; what changed is that a second reader of the sentence is gone.
    """
    from engine.grammar import ast as grammar_ast, compile_line
    from engine.oracle import compile_card_oracle

    pyramids = arn_by_name["Pyramids"]
    head = pyramids.oracle_text.splitlines()[0]
    node = compile_line(head).node

    assert isinstance(node, grammar_ast.ActivatedAbilityNode)
    assert node.statement == grammar_ast.ModalNode(1)

    program = compile_card_oracle(pyramids)
    assert [ability.instruction.kind for ability in program.activated_abilities] == [
        "destroy_target_permanent", "shield_target_land_from_destruction"
    ]
    # The bullets are alternatives of an ability, never cast-time modes.
    assert program.modes == ()
