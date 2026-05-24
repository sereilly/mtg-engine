from engine import Game, PlayerState, classify_card
from engine.models import CardDefinition, Permanent


def _mk_card(name: str, type_line: str, oracle_text: str = "", colors: tuple[str, ...] = ()) -> CardDefinition:
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
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def test_draw_reduces_library():
    p = PlayerState(name="A", library=[])
    drawn = p.draw(1)
    assert drawn == 0


def test_destroy_all_lands_spell(all_cards):
    armageddon = next(card for card in all_cards if card.name == "Armageddon")
    plains = next(card for card in all_cards if card.name == "Plains")

    p1 = PlayerState(name="P1", hand=[armageddon])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(plains))
    p2.battlefield.append(Permanent(plains))

    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Armageddon", target_player_index=1)

    assert result.supported
    assert len(p1.battlefield) == 0
    assert len(p2.battlefield) == 0


def test_ancestral_recall_draws_three(all_cards):
    recall = next(card for card in all_cards if card.name == "Ancestral Recall")
    island = next(card for card in all_cards if card.name == "Island")

    p1 = PlayerState(name="P1", hand=[recall])
    p2 = PlayerState(name="P2", library=[island, island, island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Ancestral Recall", target_player_index=1)

    assert result.supported
    assert len(p2.hand) == 3


def test_counterspell_counters_spell_on_stack(all_cards):
    recall = next(card for card in all_cards if card.name == "Ancestral Recall")
    counterspell = next(card for card in all_cards if card.name == "Counterspell")
    island = next(card for card in all_cards if card.name == "Island")

    p1 = PlayerState(name="P1", hand=[recall])
    p2 = PlayerState(name="P2", hand=[counterspell], library=[island, island, island, island])
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Ancestral Recall", target_player_index=1)
    game.queue_from_hand(1, "Counterspell", target_player_index=0)
    game.resolve_stack()

    assert len(p2.hand) == 0
    assert len(p2.graveyard) == 1
    assert p2.graveyard[0].name == "Counterspell"
    assert len(p1.graveyard) == 1
    assert p1.graveyard[0].name == "Ancestral Recall"


def test_disenchant_destroys_target_artifact(all_cards):
    disenchant = next(card for card in all_cards if card.name == "Disenchant")
    lotus = next(card for card in all_cards if card.name == "Black Lotus")

    p1 = PlayerState(name="P1", hand=[disenchant])
    p2 = PlayerState(name="P2")
    p2.battlefield.append(Permanent(card=lotus))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Disenchant", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard
    assert p2.graveyard[0].name == "Black Lotus"


def test_ice_storm_destroys_selected_target_land(all_cards):
    ice_storm = next(card for card in all_cards if card.name == "Ice Storm")
    island = next(card for card in all_cards if card.name == "Island")
    mountain = next(card for card in all_cards if card.name == "Mountain")

    p1 = PlayerState(name="P1", hand=[ice_storm])
    p2 = PlayerState(name="P2")
    p2.battlefield.append(Permanent(card=island))
    p2.battlefield.append(Permanent(card=mountain))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0,
        "Ice Storm",
        target_player_index=1,
        target_permanent_index=1,
    )

    assert result.supported
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].card.name == "Island"
    assert p2.graveyard
    assert p2.graveyard[0].name == "Mountain"


def test_bad_moon_applies_global_black_creature_buff(all_cards):
    bad_moon = next(card for card in all_cards if card.name == "Bad Moon")
    black_knight = next(card for card in all_cards if card.name == "Black Knight")

    p1 = PlayerState(name="P1", hand=[bad_moon])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(card=black_knight))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Bad Moon")

    assert result.supported
    knight_perm = p1.battlefield[0]
    assert knight_perm.effective_power == 3
    assert knight_perm.effective_toughness == 3


def test_destroy_all_creatures_effect():
    wrath = _mk_card("Wrath Test", "Sorcery", "Destroy all creatures.")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[wrath], battlefield=[Permanent(card=bear)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wrath Test", target_player_index=1)

    assert result.supported
    assert len(p1.battlefield) == 0
    assert len(p2.battlefield) == 0


def test_discard_effect():
    spell = _mk_card("Discard Test", "Sorcery", "Target player discards two cards.")
    island = _mk_card("Island", "Basic Land — Island")

    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", hand=[island, island, island])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Discard Test", target_player_index=1)
    assert len(p2.hand) == 1
    assert len(p2.graveyard) == 2


def test_lose_life_effect():
    spell = _mk_card("Lose Life Test", "Sorcery", "Target player loses 3 life.")
    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Lose Life Test", target_player_index=1)
    assert p2.life == 17


def test_tap_and_untap_effects():
    tap_spell = _mk_card("Tap Test", "Instant", "Tap target creature.")
    untap_spell = _mk_card("Untap Test", "Instant", "Untap target creature.")
    creature = _mk_card("Target Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[tap_spell, untap_spell])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature, tapped=False)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Tap Test", target_player_index=1)
    assert p2.battlefield[0].tapped is True

    game.cast_from_hand(0, "Untap Test", target_player_index=1)
    assert p2.battlefield[0].tapped is False


def test_prevention_shield_reduces_damage():
    prevent = _mk_card("Prevent Test", "Instant", "Prevent the next 2 damage that would be dealt to you this turn.")
    bolt = _mk_card("Bolt Test", "Instant", "Bolt Test deals 3 damage to any target.")

    p1 = PlayerState(name="P1", hand=[prevent])
    p2 = PlayerState(name="P2", hand=[bolt], life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Prevent Test", target_player_index=0)
    game.cast_from_hand(1, "Bolt Test", target_player_index=0)
    assert p1.life == 19


def test_regeneration_shield_saves_creature_once():
    regen = _mk_card("Regen Test", "Instant", "Regenerate target creature.")
    wrath = _mk_card("Wrath Test", "Sorcery", "Destroy all creatures.")
    creature = _mk_card("Regen Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[regen], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2", hand=[wrath])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Regen Test", target_player_index=0)
    game.cast_from_hand(1, "Wrath Test", target_player_index=0)
    assert len(p1.battlefield) == 1
    assert p1.battlefield[0].tapped is True


def test_aura_creature_buff_applies():
    aura = _mk_card("Aura Buff", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +2/+1.")
    creature = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Aura Buff", target_player_index=1)
    assert p2.battlefield[0].effective_power == 4
    assert p2.battlefield[0].effective_toughness == 3


def test_aura_land_logs_simplified_resolution():
    aura = _mk_card("Land Aura", "Enchantment — Aura", "Enchant land\nWhenever enchanted land is tapped for mana, its controller adds {G}.")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Land Aura", target_player_index=1)
    assert result.supported
    assert any("enchants a land" in line.lower() for line in game.log)


def test_creature_with_keyword_reminder_is_supported(all_cards):
    serra_angel = next(card for card in all_cards if card.name == "Serra Angel")
    classification = classify_card(serra_angel)
    assert classification.supported


def test_creature_with_activated_damage_is_supported(all_cards):
    prodigal = next(card for card in all_cards if card.name == "Prodigal Sorcerer")
    classification = classify_card(prodigal)
    assert classification.supported


def test_activate_prodigal_sorcerer_ability(all_cards):
    prodigal = next(card for card in all_cards if card.name == "Prodigal Sorcerer")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prodigal)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)

    assert result.supported
    assert p2.life == 19
    assert p1.battlefield[0].tapped is True


def test_activate_black_lotus_adds_mana_and_sacrifices(all_cards):
    lotus = next(card for card in all_cards if card.name == "Black Lotus")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lotus)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Black Lotus", target_player_index=1)

    assert result.supported
    assert p1.mana_pool["G"] == 3
    assert not p1.battlefield
    assert p1.graveyard and p1.graveyard[0].name == "Black Lotus"


def test_activate_black_lotus_with_selected_color(all_cards):
    lotus = next(card for card in all_cards if card.name == "Black Lotus")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lotus)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0,
        "Black Lotus",
        target_player_index=1,
        mana_color="U",
    )

    assert result.supported
    assert p1.mana_pool["U"] == 3
    assert p1.mana_pool["G"] == 0
    assert not p1.battlefield
    assert p1.graveyard and p1.graveyard[0].name == "Black Lotus"


def test_raise_dead_style_returns_creature_from_graveyard():
    spell = _mk_card("Raise Test", "Sorcery", "Return target creature card from your graveyard to your hand.")
    creature = _mk_card("Dead Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[spell], graveyard=[creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raise Test", target_player_index=0)

    assert result.supported
    assert any(card.name == "Dead Bear" for card in p1.hand)
    assert all(card.name != "Dead Bear" for card in p1.graveyard)


def test_braingeyser_draws_x_cards(all_cards):
    braingeyser = next(card for card in all_cards if card.name == "Braingeyser")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", hand=[braingeyser])
    p2 = PlayerState(name="P2", library=[island, island, island, island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Braingeyser", target_player_index=1, x_value=4)

    assert result.supported
    assert len(p2.hand) == 4


def test_disintegrate_deals_x_damage():
    spell = _mk_card("X Bolt", "Sorcery", "X Bolt deals X damage to any target.")
    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "X Bolt", target_player_index=1, x_value=5)

    assert result.supported
    assert p2.life == 15


def test_reanimate_to_battlefield():
    spell = _mk_card(
        "Reanimate Test",
        "Sorcery",
        "Return target creature card from your graveyard to the battlefield.",
    )
    creature = _mk_card("Dead Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[spell], graveyard=[creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Reanimate Test", target_player_index=0)

    assert result.supported
    assert any(perm.card.name == "Dead Bear" for perm in p1.battlefield)


def test_ankh_of_mishra_triggers_on_land_entry(all_cards):
    ankh = next(card for card in all_cards if card.name == "Ankh of Mishra")
    plains = next(card for card in all_cards if card.name == "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ankh)])
    p2 = PlayerState(name="P2", hand=[plains], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Plains", target_player_index=1)

    assert result.supported
    assert p2.life == 18


def test_black_vise_upkeep_trigger(all_cards):
    vise = next(card for card in all_cards if card.name == "Black Vise")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", hand=[vise])
    p2 = PlayerState(name="P2", hand=[island, island, island, island, island, island], life=20)
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Black Vise", target_player_index=1)
    game.resolve_upkeep(1)

    assert cast_result.supported
    # 6 cards in hand means 2 damage from Black Vise.
    assert p2.life == 18


def test_unsummon_returns_target_creature(all_cards):
    unsummon = next(card for card in all_cards if card.name == "Unsummon")
    creature = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[unsummon])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Unsummon", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert any(card.name == "Bear" for card in p2.hand)


def test_wheel_of_fortune_discards_then_draws(all_cards):
    wheel = next(card for card in all_cards if card.name == "Wheel of Fortune")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", hand=[wheel, island], library=[island] * 10)
    p2 = PlayerState(name="P2", hand=[island, island], library=[island] * 10)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wheel of Fortune", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7
    assert len(p2.hand) == 7


def test_timetwister_resets_and_draws_seven(all_cards):
    twister = next(card for card in all_cards if card.name == "Timetwister")
    island = next(card for card in all_cards if card.name == "Island")
    bear = _mk_card("Dead Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[twister, island], graveyard=[bear], library=[island] * 10)
    p2 = PlayerState(name="P2", hand=[island], graveyard=[bear], library=[island] * 10)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Timetwister", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7
    assert len(p2.hand) == 7


def test_demonic_tutor_puts_library_card_into_hand(all_cards):
    tutor = next(card for card in all_cards if card.name == "Demonic Tutor")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", hand=[tutor], library=[island])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Demonic Tutor", target_player_index=0)

    assert result.supported
    assert any(card.name == "Island" for card in p1.hand)


def test_time_walk_grants_extra_turn(all_cards):
    time_walk = next(card for card in all_cards if card.name == "Time Walk")
    p1 = PlayerState(name="P1", hand=[time_walk])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Time Walk", target_player_index=0)

    assert result.supported
    assert game.extra_turns.get(0, 0) == 1


def test_sacrifice_spell_adds_black_mana(all_cards):
    sacrifice = next(card for card in all_cards if card.name == "Sacrifice")
    creature = _mk_card("Mana Bear", "Creature — Bear")
    creature = CardDefinition(
        name=creature.name,
        mana_cost=creature.mana_cost,
        cmc=3.0,
        type_line=creature.type_line,
        oracle_text=creature.oracle_text,
        colors=creature.colors,
        color_identity=creature.color_identity,
        keywords=creature.keywords,
        produced_mana=creature.produced_mana,
        raw=creature.raw,
    )
    p1 = PlayerState(name="P1", hand=[sacrifice], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sacrifice", target_player_index=0)

    assert result.supported
    assert p1.mana_pool["B"] == 3
    assert not p1.battlefield


def test_lace_spell_changes_target_color(all_cards):
    deathlace = next(card for card in all_cards if card.name == "Deathlace")
    creature = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[deathlace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Deathlace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "B"


def test_orcish_oriflamme_applies_power_bonus(all_cards):
    oriflamme = next(card for card in all_cards if card.name == "Orcish Oriflamme")
    creature = _mk_card("Attacker", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[oriflamme], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Orcish Oriflamme", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].effective_power == 3


def test_jayemdae_tome_activated_draw(all_cards):
    tome = next(card for card in all_cards if card.name == "Jayemdae Tome")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tome)], library=[island])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Jayemdae Tome", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 1


def test_glasses_of_urza_look_at_hand(all_cards):
    glasses = next(card for card in all_cards if card.name == "Glasses of Urza")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=glasses)])
    p2 = PlayerState(name="P2", hand=[island, island])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Glasses of Urza", target_player_index=1)

    assert result.supported
    assert any("looked at" in line.lower() for line in game.log)


def test_black_knight_classifies_supported(all_cards):
    knight = next(card for card in all_cards if card.name == "Black Knight")
    result = classify_card(knight)
    assert result.supported


def test_shivan_dragon_activated_plus_one_power(all_cards):
    dragon = next(card for card in all_cards if card.name == "Shivan Dragon")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=dragon)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before = p1.battlefield[0].effective_power
    result = game.activate_permanent_ability(0, "Shivan Dragon", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_power == before + 1


def test_granite_gargoyle_activated_plus_one_toughness(all_cards):
    gargoyle = next(card for card in all_cards if card.name == "Granite Gargoyle")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=gargoyle)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before = p1.battlefield[0].effective_toughness
    result = game.activate_permanent_ability(0, "Granite Gargoyle", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_toughness == before + 1


def test_frozen_shade_activated_plus_one_plus_one(all_cards):
    shade = next(card for card in all_cards if card.name == "Frozen Shade")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=shade)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before_power = p1.battlefield[0].effective_power
    before_toughness = p1.battlefield[0].effective_toughness
    result = game.activate_permanent_ability(0, "Frozen Shade", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_power == before_power + 1
    assert p1.battlefield[0].effective_toughness == before_toughness + 1


def test_goblin_balloon_brigade_gains_flying_flag(all_cards):
    goblin = next(card for card in all_cards if card.name == "Goblin Balloon Brigade")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=goblin)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Goblin Balloon Brigade", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].metadata.get("gains_flying_until_eot") is True


def test_clockwork_beast_enters_with_seven_plus_zero(all_cards):
    beast = next(card for card in all_cards if card.name == "Clockwork Beast")
    p1 = PlayerState(name="P1", hand=[beast])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Clockwork Beast", target_player_index=1)

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.power_bonus >= 7


def test_rock_hydra_x_counters_on_entry(all_cards):
    hydra = next(card for card in all_cards if card.name == "Rock Hydra")
    p1 = PlayerState(name="P1", hand=[hydra])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Rock Hydra", target_player_index=1, x_value=3)

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.power_bonus >= 3
    assert perm.toughness_bonus >= 3


def test_sea_serpent_attack_restriction(all_cards):
    serpent = next(card for card in all_cards if card.name == "Sea Serpent")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=serpent)])
    p2 = PlayerState(name="P2", battlefield=[])
    game = Game(players=[p1, p2])

    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is False
    p2.battlefield.append(Permanent(card=island))
    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is True


def test_keldon_warlord_dynamic_pt(all_cards):
    warlord = next(card for card in all_cards if card.name == "Keldon Warlord")
    creature = _mk_card("Helper", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=warlord), Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    warlord_perm = p1.battlefield[0]
    assert warlord_perm.effective_power == 2
    assert warlord_perm.effective_toughness == 2


def test_verduran_enchantress_draw_trigger(all_cards):
    enchantress = next(card for card in all_cards if card.name == "Verduran Enchantress")
    blessing = next(card for card in all_cards if card.name == "Blessing")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", hand=[blessing], library=[island], battlefield=[Permanent(card=enchantress)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blessing", target_player_index=0)

    assert result.supported
    assert len(p1.hand) == 1


def test_fog_sets_combat_damage_prevention(all_cards):
    fog = next(card for card in all_cards if card.name == "Fog")
    p1 = PlayerState(name="P1", hand=[fog])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fog", target_player_index=0)

    assert result.supported
    assert game.combat_damage_prevented_until_eot is True


def test_howling_mine_draw_step_bonus(all_cards):
    mine = next(card for card in all_cards if card.name == "Howling Mine")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mine)])
    p2 = PlayerState(name="P2", library=[island, island, island])
    game = Game(players=[p1, p2])

    drawn = game.resolve_draw_step(1)

    assert drawn == 2
    assert len(p2.hand) == 2


def test_stasis_skips_untap_step(all_cards):
    stasis = next(card for card in all_cards if card.name == "Stasis")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=stasis)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island, tapped=True)])
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 0
    assert p2.battlefield[0].tapped is True


def test_smoke_limits_creature_untap(all_cards):
    smoke = next(card for card in all_cards if card.name == "Smoke")
    c1 = _mk_card("Bear A", "Creature — Bear")
    c2 = _mk_card("Bear B", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=smoke)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=c1, tapped=True), Permanent(card=c2, tapped=True)],
    )
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 1
    assert sum(1 for perm in p2.battlefield if not perm.tapped) == 1


def test_winter_orb_limits_land_untap(all_cards):
    orb = next(card for card in all_cards if card.name == "Winter Orb")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=orb, tapped=False)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=island, tapped=True), Permanent(card=island, tapped=True)],
    )
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 1


def test_meekstone_prevents_big_creature_untap(all_cards):
    meekstone = next(card for card in all_cards if card.name == "Meekstone")
    big = _mk_card("Big", "Creature — Giant")
    small = _mk_card("Small", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=meekstone)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=big, tapped=True), Permanent(card=small, tapped=True)],
    )
    p2.battlefield[0].metadata["absolute_power"] = 4
    p2.battlefield[0].metadata["absolute_toughness"] = 4
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 1
    assert p2.battlefield[0].tapped is True
    assert p2.battlefield[1].tapped is False


def test_mana_flare_adds_extra_mana(all_cards):
    mana_flare = next(card for card in all_cards if card.name == "Mana Flare")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mana_flare), Permanent(card=island)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(0, "Island")

    assert ok
    assert p1.mana_pool["U"] == 2


def test_mana_pool_empties_between_steps(all_cards):
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", mana_pool={"W": 0, "U": 2, "B": 0, "R": 0, "G": 0, "C": 1})
    p2 = PlayerState(name="P2", library=[island])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p1.mana_pool["U"] == 0
    assert p1.mana_pool["C"] == 0


def test_jade_statue_animates_until_end_combat(all_cards):
    statue = next(card for card in all_cards if card.name == "Jade Statue")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=statue)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Jade Statue", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_power == 3
    assert p1.battlefield[0].effective_toughness == 6
    game.end_combat()
    assert p1.battlefield[0].metadata.get("absolute_power") is None


def test_cleanup_step_discards_and_expires_temporary_effects():
    creature = _mk_card("Temp Bear", "Creature - Bear")
    hand_cards = [_mk_card(f"Card {idx}", "Sorcery") for idx in range(9)]
    permanent = Permanent(card=creature, power_bonus=2, toughness_bonus=3)
    permanent.metadata["temporary_power_bonus_until_eot"] = 2
    permanent.metadata["temporary_toughness_bonus_until_eot"] = 3
    permanent.metadata["gains_flying_until_eot"] = True
    p1 = PlayerState(name="P1", hand=hand_cards, battlefield=[permanent], damage_prevention_pool=4)
    p2 = PlayerState(name="P2", combat_damage_cap_one_charges=1)
    game = Game(players=[p1, p2], combat_damage_prevented_until_eot=True)

    game.resolve_cleanup_step(0)

    assert game.current_phase == "cleanup"
    assert len(p1.hand) == 7
    assert len(p1.graveyard) == 2
    assert permanent.power_bonus == 0
    assert permanent.toughness_bonus == 0
    assert permanent.metadata.get("gains_flying_until_eot") is None
    assert p1.damage_prevention_pool == 0
    assert p2.combat_damage_cap_one_charges == 0
    assert game.combat_damage_prevented_until_eot is False


def test_the_hive_creates_wasp_token(all_cards):
    hive = next(card for card in all_cards if card.name == "The Hive")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=hive)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "The Hive", target_player_index=1)

    assert result.supported
    assert any(perm.card.name == "Wasp" for perm in p1.battlefield)


def test_animate_wall_allows_wall_to_attack(all_cards):
    animate_wall = next(card for card in all_cards if card.name == "Animate Wall")
    wall = next(card for card in all_cards if card.name == "Wall of Stone")
    p1 = PlayerState(name="P1", hand=[animate_wall])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Animate Wall", target_player_index=1)

    assert result.supported
    wall_perm = p2.battlefield[0]
    assert game.can_attack(wall_perm, defending_player_index=0) is True


def test_black_lotus_is_classified_supported(all_cards):
    lotus = next(card for card in all_cards if card.name == "Black Lotus")
    classification = classify_card(lotus)
    assert classification.supported


def test_castle_buffs_untapped_creatures_toughness(all_cards):
    castle = next(card for card in all_cards if card.name == "Castle")
    bear = _mk_card("Guard", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[castle], battlefield=[Permanent(card=bear, tapped=False)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Castle", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].effective_toughness >= 4


def test_circle_of_protection_activation_sets_prevention(all_cards):
    cop = next(card for card in all_cards if card.name == "Circle of Protection: Blue")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: Blue", target_player_index=0)

    assert result.supported
    assert p1.damage_prevention_pool == 1


def test_conversion_sacrifices_on_upkeep_without_white_mana(all_cards):
    conversion = next(card for card in all_cards if card.name == "Conversion")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=conversion)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not p1.battlefield
    assert any(card.name == "Conversion" for card in p1.graveyard)


def test_dwarven_warriors_can_grant_unblockable(all_cards):
    warriors = next(card for card in all_cards if card.name == "Dwarven Warriors")
    bear = _mk_card("Small Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=warriors)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Dwarven Warriors", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("cant_be_blocked_until_eot") is True


def test_nightmare_dynamic_power_toughness_by_swamps(all_cards):
    nightmare = next(card for card in all_cards if card.name == "Nightmare")
    swamp = next(card for card in all_cards if card.name == "Swamp")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=nightmare), Permanent(card=swamp), Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    nm = p1.battlefield[0]
    assert nm.effective_power == 2
    assert nm.effective_toughness == 2


def test_sedge_troll_gets_bonus_with_swamp(all_cards):
    troll = next(card for card in all_cards if card.name == "Sedge Troll")
    swamp = next(card for card in all_cards if card.name == "Swamp")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=troll), Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    tr = p1.battlefield[0]
    assert tr.effective_power >= 3
    assert tr.effective_toughness >= 3


def test_balance_equalizes_lands_creatures_and_hand(all_cards):
    balance = next(card for card in all_cards if card.name == "Balance")
    plains = next(card for card in all_cards if card.name == "Plains")
    bear = _mk_card("Bear", "Creature — Bear")
    elf = _mk_card("Elf", "Creature — Elf")

    p1 = PlayerState(
        name="P1",
        hand=[balance, plains, plains],
        battlefield=[Permanent(card=plains), Permanent(card=plains), Permanent(card=bear)],
    )
    p2 = PlayerState(
        name="P2",
        hand=[plains],
        battlefield=[Permanent(card=plains), Permanent(card=elf), Permanent(card=elf)],
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Balance", target_player_index=1)

    assert result.supported
    assert sum(1 for perm in p1.battlefield if perm.card.primary_type == "land") == 1
    assert sum(1 for perm in p2.battlefield if perm.card.primary_type == "land") == 1
    assert sum(1 for perm in p1.battlefield if perm.card.primary_type == "creature") == 1
    assert sum(1 for perm in p2.battlefield if perm.card.primary_type == "creature") == 1
    assert len(p1.hand) == len(p2.hand)


def test_forcefield_caps_next_damage_to_one(all_cards):
    forcefield = next(card for card in all_cards if card.name == "Forcefield")
    bolt = _mk_card("Bolt Test", "Instant", "Bolt Test deals 3 damage to any target.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=forcefield)], life=20)
    p2 = PlayerState(name="P2", hand=[bolt], life=20)
    game = Game(players=[p1, p2])

    activation = game.activate_permanent_ability(0, "Forcefield", target_player_index=0)
    result = game.cast_from_hand(1, "Bolt Test", target_player_index=0)

    assert activation.supported
    assert result.supported
    assert p1.life == 19


def test_gloom_tax_log_on_white_spell(all_cards):
    gloom = next(card for card in all_cards if card.name == "Gloom")
    white_spell = _mk_card("White Test", "Sorcery", "Target player loses 3 life.", colors=("W",))
    p1 = PlayerState(name="P1", hand=[gloom])
    p2 = PlayerState(name="P2", hand=[white_spell], life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Gloom", target_player_index=1)
    result = game.cast_from_hand(1, "White Test", target_player_index=0)

    assert result.supported
    assert any("taxed by gloom" in line.lower() for line in game.log)


def test_kormus_bell_animates_swamps(all_cards):
    bell = next(card for card in all_cards if card.name == "Kormus Bell")
    swamp = next(card for card in all_cards if card.name == "Swamp")
    p1 = PlayerState(name="P1", hand=[bell], battlefield=[Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Kormus Bell", target_player_index=1)

    assert result.supported
    game._refresh_dynamic_creatures()
    assert p1.battlefield[0].metadata.get("land_animated") is True
    assert p1.battlefield[0].effective_power == 1
    assert p1.battlefield[0].effective_toughness == 1


def test_living_lands_animates_forests(all_cards):
    living = next(card for card in all_cards if card.name == "Living Lands")
    forest = next(card for card in all_cards if card.name == "Forest")
    p1 = PlayerState(name="P1", hand=[living], battlefield=[Permanent(card=forest)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Living Lands", target_player_index=1)

    assert result.supported
    game._refresh_dynamic_creatures()
    assert p1.battlefield[0].metadata.get("land_animated") is True
    assert p1.battlefield[0].effective_power == 1
    assert p1.battlefield[0].effective_toughness == 1


def test_library_of_leng_sets_no_max_hand_size(all_cards):
    library = next(card for card in all_cards if card.name == "Library of Leng")
    p1 = PlayerState(name="P1", hand=[library])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Library of Leng", target_player_index=0)

    assert result.supported
    assert p1.has_no_max_hand_size is True


def test_natural_selection_reorders_top_three(all_cards):
    natural = next(card for card in all_cards if card.name == "Natural Selection")
    a = _mk_card("A", "Sorcery")
    b = _mk_card("B", "Sorcery")
    c = _mk_card("C", "Sorcery")
    d = _mk_card("D", "Sorcery")
    p1 = PlayerState(name="P1", hand=[natural])
    p2 = PlayerState(name="P2", library=[a, b, c, d])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Natural Selection", target_player_index=1)

    assert result.supported
    assert [card.name for card in p2.library[:3]] == ["C", "B", "A"]


def test_word_of_command_forces_play_from_hand(all_cards):
    word = next(card for card in all_cards if card.name == "Word of Command")
    card_in_hand = _mk_card("Victim Spell", "Sorcery")
    p1 = PlayerState(name="P1", hand=[word])
    p2 = PlayerState(name="P2", hand=[card_in_hand])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Word of Command", target_player_index=1)

    assert result.supported
    assert len(p2.hand) == 0
    assert any(card.name == "Victim Spell" for card in p2.graveyard)


def test_magical_hack_marks_target_text_modified(all_cards):
    hack = next(card for card in all_cards if card.name == "Magical Hack")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[hack])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Magical Hack", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("text_modified") is True


def test_sleight_of_mind_marks_target_text_modified(all_cards):
    sleight = next(card for card in all_cards if card.name == "Sleight of Mind")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[sleight])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sleight of Mind", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("text_modified") is True


def test_blaze_of_glory_sets_forced_blocking_marker(all_cards):
    blaze = next(card for card in all_cards if card.name == "Blaze of Glory")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[blaze])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blaze of Glory", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("must_block_all_until_eot") is True


def test_camouflage_resolves_supported(all_cards):
    camouflage = next(card for card in all_cards if card.name == "Camouflage")
    p1 = PlayerState(name="P1", hand=[camouflage])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Camouflage", target_player_index=1)

    assert result.supported
    assert any("pile blocking" in line.lower() for line in game.log)


def test_cyclopean_tomb_marks_land_as_swamp(all_cards):
    tomb = next(card for card in all_cards if card.name == "Cyclopean Tomb")
    plains = next(card for card in all_cards if card.name == "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tomb)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Cyclopean Tomb", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("land_type_override") == "swamp"


def test_false_orders_marks_creature_removed_from_combat(all_cards):
    false_orders = next(card for card in all_cards if card.name == "False Orders")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[false_orders])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "False Orders", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("removed_from_combat") is True


def test_raging_river_casts_as_supported_permanent(all_cards):
    river = next(card for card in all_cards if card.name == "Raging River")
    p1 = PlayerState(name="P1", hand=[river])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raging River", target_player_index=1)

    assert result.supported
    assert any(perm.card.name == "Raging River" for perm in p1.battlefield)


def test_sunglasses_of_urza_sets_white_as_red_flag(all_cards):
    sunglasses = next(card for card in all_cards if card.name == "Sunglasses of Urza")
    p1 = PlayerState(name="P1", hand=[sunglasses])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sunglasses of Urza", target_player_index=1)

    assert result.supported
    assert p1.can_spend_white_as_red is True


def test_cockatrice_classifies_supported(all_cards):
    cockatrice = next(card for card in all_cards if card.name == "Cockatrice")
    classification = classify_card(cockatrice)
    assert classification.supported


def test_force_of_nature_classifies_supported(all_cards):
    force = next(card for card in all_cards if card.name == "Force of Nature")
    classification = classify_card(force)
    assert classification.supported


def test_hypnotic_specter_classifies_supported(all_cards):
    specter = next(card for card in all_cards if card.name == "Hypnotic Specter")
    classification = classify_card(specter)
    assert classification.supported


def test_juggernaut_classifies_supported(all_cards):
    juggernaut = next(card for card in all_cards if card.name == "Juggernaut")
    classification = classify_card(juggernaut)
    assert classification.supported


def test_banding_keyword_cards_classify_supported(all_cards):
    benalish_hero = next(card for card in all_cards if card.name == "Benalish Hero")
    mesa_pegasus = next(card for card in all_cards if card.name == "Mesa Pegasus")
    timber_wolves = next(card for card in all_cards if card.name == "Timber Wolves")

    assert classify_card(benalish_hero).supported
    assert classify_card(mesa_pegasus).supported
    assert classify_card(timber_wolves).supported


def test_helm_of_chatzuk_grants_banding_until_eot(all_cards):
    helm = next(card for card in all_cards if card.name == "Helm of Chatzuk")
    bear = _mk_card("Band Target", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=helm)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].tapped is True
    assert p2.battlefield[0].metadata.get("gains_banding_until_eot") is True


def test_helm_of_chatzuk_requires_valid_creature_target(all_cards):
    helm = next(card for card in all_cards if card.name == "Helm of Chatzuk")
    island = next(card for card in all_cards if card.name == "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=helm)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=1)

    assert result.supported is False
    assert result.details == "no valid creature target for banding effect"
    assert p1.battlefield[0].tapped is False


def test_next_wave_creature_cards_classify_supported(all_cards):
    names = [
        "Demonic Hordes",
        "Dwarven Warriors",
        "Fungusaur",
        "Gaea's Liege",
        "Nettling Imp",
        "Personal Incarnation",
        "Scavenging Ghoul",
        "Stone Giant",
    ]
    for name in names:
        card = next(c for c in all_cards if c.name == name)
        assert classify_card(card).supported


def test_clone_and_fork_classify_supported(all_cards):
    clone = next(card for card in all_cards if card.name == "Clone")
    fork = next(card for card in all_cards if card.name == "Fork")

    assert classify_card(clone).supported
    assert classify_card(fork).supported


def test_gaeas_liege_activation_turns_land_into_forest(all_cards):
    liege = next(card for card in all_cards if card.name == "Gaea's Liege")
    plains = next(card for card in all_cards if card.name == "Plains")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=liege)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Gaea's Liege", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("land_type_override") == "forest"


def test_nettling_imp_marks_target_for_attack(all_cards):
    imp = next(card for card in all_cards if card.name == "Nettling Imp")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=imp)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Nettling Imp", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("must_attack_until_eot") is True


def test_stone_giant_grants_temp_flying_and_delayed_destroy(all_cards):
    giant = next(card for card in all_cards if card.name == "Stone Giant")
    small = _mk_card("Small Ally", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=giant), Permanent(card=small)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Stone Giant", target_player_index=1)

    assert result.supported
    target = p1.battlefield[1]
    assert target.metadata.get("gains_flying_until_eot") is True
    assert target.metadata.get("destroy_at_next_end_step") is True


def test_clone_copies_existing_creature_stats_on_entry(all_cards):
    clone = next(card for card in all_cards if card.name == "Clone")
    bear = _mk_card("Big Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[clone], battlefield=[Permanent(card=bear)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Clone", target_player_index=1)

    assert result.supported
    clone_perm = next(perm for perm in p1.battlefield if perm.card.name == "Clone")
    assert clone_perm.metadata.get("copied_from") == "Big Bear"
    assert clone_perm.effective_power == 2
    assert clone_perm.effective_toughness == 2


def test_fork_copies_top_spell_effect(all_cards):
    fork = next(card for card in all_cards if card.name == "Fork")
    bolt = _mk_card("Bolt Test", "Instant", "Bolt Test deals 3 damage to any target.")

    p1 = PlayerState(name="P1", hand=[bolt], life=20)
    p2 = PlayerState(name="P2", hand=[fork], life=20)
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Bolt Test", target_player_index=0)
    game.queue_from_hand(1, "Fork", target_player_index=0)
    game.resolve_stack()

    assert p1.life == 14


def test_remaining_cards_classify_supported(all_cards):
    names = ["Contract from Below", "Darkpact", "Demonic Attorney", "Copy Artifact"]
    for name in names:
        card = next(c for c in all_cards if c.name == name)
        assert classify_card(card).supported


def test_contract_from_below_discards_hand_then_draws_seven(all_cards):
    contract = next(card for card in all_cards if card.name == "Contract from Below")
    island = next(card for card in all_cards if card.name == "Island")

    p1 = PlayerState(name="P1", hand=[contract, island], library=[island] * 10)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Contract from Below", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 7


def test_demonic_attorney_antes_top_card_for_each_player(all_cards):
    attorney = next(card for card in all_cards if card.name == "Demonic Attorney")
    island = next(card for card in all_cards if card.name == "Island")

    p1 = PlayerState(name="P1", hand=[attorney], library=[island, island])
    p2 = PlayerState(name="P2", library=[island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Demonic Attorney", target_player_index=1)

    assert result.supported
    assert len(p1.library) == 1
    assert len(p2.library) == 1


def test_copy_artifact_copies_artifact_on_entry(all_cards):
    copy_artifact = next(card for card in all_cards if card.name == "Copy Artifact")
    lotus = next(card for card in all_cards if card.name == "Black Lotus")

    p1 = PlayerState(name="P1", hand=[copy_artifact], battlefield=[Permanent(card=lotus)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Copy Artifact", target_player_index=1)

    assert result.supported
    perm = next(perm for perm in p1.battlefield if perm.card.name == "Copy Artifact")
    assert perm.metadata.get("copied_from") == "Black Lotus"
