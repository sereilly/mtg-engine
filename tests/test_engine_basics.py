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
