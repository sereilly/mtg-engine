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






















































































