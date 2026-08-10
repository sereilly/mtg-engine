"""Per-card tests for Limited Edition Alpha's creature cards.

Split out of the 9,400-line test_lea_cards.py by the type of the
card each test names. See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine.ai_policy import (
    choose_cast_action,
    choose_activation_action,
    choose_combat_blockers,
    choose_combat_instant_cast_action,
    choose_reorder_library_order,
)
from engine import Game, PlayerState, classify_card, load_cards
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, lex_oracle_text, parse_activated_ability_cost
import json
from tests.helpers import (
    _mk_card,
    _mk_creature_card,
    _pass_priority,
    _resolve_top_stack,
    client,
    _get,
)
from tests.sets.lea_helpers import (
    _forest,
    _grizzly,
    _island,
    _mountain,
    _plains,
    _start_session_with_p0_graveyard,
    _swamp,
)


def test_serra_angel_enters_with_flying_and_vigilance(all_cards):
    angel = _get(all_cards, "Serra Angel")
    p1 = PlayerState(name="P1", hand=[angel])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Serra Angel")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.effective_power == 4
    assert perm.effective_toughness == 4
    assert any(k.lower() == "flying" for k in angel.keywords)
    assert any(k.lower() == "vigilance" for k in angel.keywords)


def test_prodigal_sorcerer_enters_battlefield(all_cards):
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    p1 = PlayerState(name="P1", hand=[prodigal])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Prodigal Sorcerer")

    assert result.supported
    assert p1.battlefield[0].card.name == "Prodigal Sorcerer"
    assert p1.battlefield[0].effective_power == 1
    assert p1.battlefield[0].effective_toughness == 1


def test_activate_prodigal_sorcerer_ability(all_cards):
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prodigal)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert result.supported
    assert p2.life == 19
    assert p1.battlefield[0].tapped is True


def test_black_knight_classifies_supported(all_cards):
    knight = _get(all_cards, "Black Knight")
    result = classify_card(knight)
    assert result.supported


def test_shivan_dragon_activated_plus_one_power(all_cards):
    dragon = _get(all_cards, "Shivan Dragon")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=dragon)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before = p1.battlefield[0].effective_power
    result = game.activate_permanent_ability(0, "Shivan Dragon", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_power == before + 1


def test_granite_gargoyle_activated_plus_one_toughness(all_cards):
    gargoyle = _get(all_cards, "Granite Gargoyle")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=gargoyle)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before = p1.battlefield[0].effective_toughness
    result = game.activate_permanent_ability(0, "Granite Gargoyle", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_toughness == before + 1


def test_frozen_shade_activated_plus_one_plus_one(all_cards):
    shade = _get(all_cards, "Frozen Shade")
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
    goblin = _get(all_cards, "Goblin Balloon Brigade")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=goblin)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Goblin Balloon Brigade", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].has_keyword("flying") is True


def test_clockwork_beast_enters_with_seven_plus_zero(all_cards):
    beast = _get(all_cards, "Clockwork Beast")
    p1 = PlayerState(name="P1", hand=[beast])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Clockwork Beast", target_player_index=1)

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.power_bonus >= 7


def test_rock_hydra_x_counters_on_entry(all_cards):
    hydra = _get(all_cards, "Rock Hydra")
    p1 = PlayerState(name="P1", hand=[hydra])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Rock Hydra", target_player_index=1, x_value=3)

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.power_bonus >= 3
    assert perm.toughness_bonus >= 3


def test_sea_serpent_attack_restriction(all_cards):
    serpent = _get(all_cards, "Sea Serpent")
    island = _get(all_cards, "Island")
    # Sea Serpent's controller must control an Island or it is sacrificed
    # (state-based) before it can attack.
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=serpent), Permanent(card=island)])
    p2 = PlayerState(name="P2", battlefield=[])
    game = Game(players=[p1, p2])

    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is False
    p2.battlefield.append(Permanent(card=island))
    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is True


def test_keldon_warlord_dynamic_pt(all_cards):
    warlord = _get(all_cards, "Keldon Warlord")
    creature = _mk_card("Helper", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=warlord), Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    warlord_perm = p1.battlefield[0]
    assert warlord_perm.effective_power == 2
    assert warlord_perm.effective_toughness == 2


def test_verduran_enchantress_draw_trigger(all_cards):
    enchantress = _get(all_cards, "Verduran Enchantress")
    blessing = _get(all_cards, "Blessing")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[blessing], library=[island], battlefield=[Permanent(card=enchantress)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blessing", target_player_index=0, target_permanent_index=0)

    assert result.supported
    # "you may draw a card" — the draw is now an optional yes/no prompt rather than
    # an automatic draw, so it is queued and not yet drawn.
    assert any(e["card_name"] == "Verduran Enchantress" for e in game.pending_optional_pays)
    assert len(p1.hand) == 0
    game.confirm_optional_pay(0, "Verduran Enchantress", accept=True)
    assert len(p1.hand) == 1


def test_dwarven_warriors_can_grant_unblockable(all_cards):
    warriors = _get(all_cards, "Dwarven Warriors")
    bear = _mk_card("Small Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=warriors)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Dwarven Warriors", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("cant_be_blocked_until_eot") is True


def test_nightmare_dynamic_power_toughness_by_swamps(all_cards):
    nightmare = _get(all_cards, "Nightmare")
    swamp = _get(all_cards, "Swamp")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=nightmare), Permanent(card=swamp), Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    nm = p1.battlefield[0]
    assert nm.effective_power == 2
    assert nm.effective_toughness == 2


def test_sedge_troll_gets_bonus_with_swamp(all_cards):
    troll = _get(all_cards, "Sedge Troll")
    swamp = _get(all_cards, "Swamp")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=troll), Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()
    tr = p1.battlefield[0]
    assert tr.effective_power >= 3
    assert tr.effective_toughness >= 3


def test_cockatrice_classifies_supported(all_cards):
    cockatrice = _get(all_cards, "Cockatrice")
    classification = classify_card(cockatrice)
    assert classification.supported


def test_force_of_nature_classifies_supported(all_cards):
    force = _get(all_cards, "Force of Nature")
    classification = classify_card(force)
    assert classification.supported


def test_hypnotic_specter_classifies_supported(all_cards):
    specter = _get(all_cards, "Hypnotic Specter")
    classification = classify_card(specter)
    assert classification.supported


def test_juggernaut_classifies_supported(all_cards):
    juggernaut = _get(all_cards, "Juggernaut")
    classification = classify_card(juggernaut)
    assert classification.supported


def test_clone_and_fork_classify_supported(all_cards):
    clone = _get(all_cards, "Clone")
    fork = _get(all_cards, "Fork")

    assert classify_card(clone).supported
    assert classify_card(fork).supported


def test_nettling_imp_marks_target_for_attack(all_cards):
    imp = _get(all_cards, "Nettling Imp")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=imp)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])
    # "Activate only during an opponent's turn, before attackers are declared."
    game.active_player_index = 1

    result = game.activate_permanent_ability(0, "Nettling Imp", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("must_attack_until_eot") is True


def test_stone_giant_grants_temp_flying_and_delayed_destroy(all_cards):
    giant = _get(all_cards, "Stone Giant")
    small = _mk_card("Small Ally", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=giant), Permanent(card=small)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Stone Giant", target_player_index=1)

    assert result.supported
    target = p1.battlefield[1]
    assert target.has_keyword("flying") is True
    assert target.metadata.get("destroy_at_next_end_step") is True


def test_clone_copies_existing_creature_stats_on_entry(all_cards):
    clone = _get(all_cards, "Clone")
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


def test_compile_creature_program_keeps_clockwork_beast_supported():
    card = _mk_card(
        "Clockwork Beast",
        "Artifact Creature — Beast",
        "This creature enters with seven +1/+0 counters on it.\n"
        "At end of combat, if this creature attacked or blocked this combat, remove a +1/+0 counter from it.\n"
        "{X}, {T}: Put up to X +1/+0 counters on this creature. This ability can't cause the total number of +1/+0 counters on this creature to be greater than seven. Activate only during your upkeep.",
    )

    program = compile_card_oracle(card)

    assert program.supported is True
    assert any(ability.supported for ability in program.activated_abilities)


def test_juggernaut_must_attack_and_cannot_be_blocked_by_walls(all_cards):
    juggernaut = _get(all_cards, "Juggernaut")
    wall = _get(all_cards, "Wall of Stone")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=juggernaut)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall)])
    game = Game(players=[p1, p2])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    ok, details = game.declare_attackers(0, [])
    assert ok is False
    assert "Juggernaut must attack if able" in details

    ok, _ = game.declare_attackers(0, [0])
    assert ok

    game.advance_combat_phase()
    ok, details = game.declare_blockers(1, {0: 0})
    assert ok is False
    assert "cannot block" in details


def test_hill_giant_classifies_supported(all_cards):
    giant = _get(all_cards, "Hill Giant")
    assert classify_card(giant).supported
    perm = Permanent(card=giant)
    assert perm.effective_power == 3
    assert perm.effective_toughness == 3


def test_nether_shadow_classifies_supported(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    assert classify_card(shadow).supported


def test_nether_shadow_returns_with_three_creatures_above(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    bolt = _get(all_cards, "Lightning Bolt")
    # Graveyard ordered oldest→newest (append order). Cards "above" Nether Shadow
    # are those put in more recently — later in the list. Three creatures sit above
    # it (a non-creature in the mix shouldn't count toward the threshold).
    p1 = PlayerState(
        name="P1",
        graveyard=[shadow, bears, bolt, bears, bears],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert all(c.name != "Nether Shadow" for c in p1.graveyard)
    returned = [perm for perm in p1.battlefield if perm.card.name == "Nether Shadow"]
    assert len(returned) == 1
    # Haste: it should not be summoning sick the turn it returns.
    assert not game._is_summoning_sick(returned[0])


def test_nether_shadow_stays_with_too_few_creatures_above(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    bolt = _get(all_cards, "Lightning Bolt")
    # Only two creature cards above Nether Shadow — below the threshold of three.
    p1 = PlayerState(
        name="P1",
        graveyard=[shadow, bears, bolt, bears],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert any(c.name == "Nether Shadow" for c in p1.graveyard)
    assert all(perm.card.name != "Nether Shadow" for perm in p1.battlefield)


def test_nether_shadow_only_returns_on_owners_upkeep(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(
        name="P1",
        graveyard=[shadow, bears, bears, bears],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Opponent's upkeep — "your upkeep" must not fire for P1's graveyard card.
    game.resolve_upkeep(1)

    assert any(c.name == "Nether Shadow" for c in p1.graveyard)
    assert all(perm.card.name != "Nether Shadow" for perm in p1.battlefield)


def test_get_optional_upkeep_triggers_lists_eligible_nether_shadow(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", graveyard=[shadow, bears, bears, bears])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    triggers = game.get_optional_upkeep_triggers(0)

    assert len(triggers) == 1
    assert triggers[0]["card_name"] == "Nether Shadow"
    assert triggers[0]["kind"] == "upkeep_return_self_from_graveyard"
    assert "Nether Shadow" in triggers[0]["prompt"]


def test_nether_shadow_optional_choice_declined_keeps_in_graveyard(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", graveyard=[shadow, bears, bears, bears])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0, optional_choices={"Nether Shadow": False})

    assert any(c.name == "Nether Shadow" for c in p1.graveyard)
    assert all(perm.card.name != "Nether Shadow" for perm in p1.battlefield)


def test_nether_shadow_optional_choice_accepted_returns(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", graveyard=[shadow, bears, bears, bears])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0, optional_choices={"Nether Shadow": True})

    assert all(c.name != "Nether Shadow" for c in p1.graveyard)
    assert any(perm.card.name == "Nether Shadow" for perm in p1.battlefield)


def test_nether_shadow_upkeep_prompts_human_then_accepts(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    sid, session = _start_session_with_p0_graveyard([shadow, bears, bears, bears], seed=91)

    assert session.game.current_step == "upkeep", "must pause at upkeep for the optional trigger"
    assert any(c["card_name"] == "Nether Shadow" for c in session.optional_trigger_choices)
    # Must not act before the player decides.
    assert any(c.name == "Nether Shadow" for c in session.game.players[0].graveyard)

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    info = state["optional_trigger"]
    assert info is not None
    assert any(c["card_name"] == "Nether Shadow" for c in info["pending"])

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_trigger", "card_name": "Nether Shadow", "accept": True},
    )
    assert resp.status_code == 200
    p0 = session.game.players[0]
    assert any(p.card.name == "Nether Shadow" for p in p0.battlefield)
    assert all(c.name != "Nether Shadow" for c in p0.graveyard)
    assert session.game.current_turn_phase == "precombat_main"


def test_nether_shadow_upkeep_prompt_declined(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    sid, session = _start_session_with_p0_graveyard([shadow, bears, bears, bears], seed=92)

    assert session.game.current_step == "upkeep"

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_trigger", "card_name": "Nether Shadow", "accept": False},
    )
    assert resp.status_code == 200
    p0 = session.game.players[0]
    assert all(p.card.name != "Nether Shadow" for p in p0.battlefield)
    assert any(c.name == "Nether Shadow" for c in p0.graveyard)
    assert session.game.current_turn_phase == "precombat_main"


def test_northern_paladin_destroys_black_permanent(all_cards):
    paladin = _get(all_cards, "Northern Paladin")
    black_knight = _get(all_cards, "Black Knight")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=paladin)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=black_knight)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Northern Paladin", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert any(card.name == "Black Knight" for card in p2.graveyard)
    assert p1.battlefield[0].tapped is True


def test_obsianus_golem_classifies_supported(all_cards):
    golem = _get(all_cards, "Obsianus Golem")
    assert classify_card(golem).supported


def test_orcish_artillery_deals_damage_and_self_damage(all_cards):
    artillery = _get(all_cards, "Orcish Artillery")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=artillery)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Orcish Artillery", target_player_index=1)

    assert result.supported
    assert p2.life == 18
    assert p1.life == 17


def test_pearled_unicorn_classifies_supported(all_cards):
    unicorn = _get(all_cards, "Pearled Unicorn")
    assert classify_card(unicorn).supported


def test_air_elemental_cannot_be_blocked_by_ground_creature(all_cards):
    """Air Elemental has flying; a creature without flying or reach cannot block it."""
    air_elemental = _get(all_cards, "Air Elemental")
    grizzly_bears = _get(all_cards, "Grizzly Bears")

    air_perm = Permanent(card=air_elemental)
    bear_perm = Permanent(card=grizzly_bears)

    p1 = PlayerState(name="P1", battlefield=[air_perm])
    p2 = PlayerState(name="P2", battlefield=[bear_perm])
    game = Game(players=[p1, p2])

    # bear_perm (blocker) cannot block air_perm (attacker with flying)
    assert game._can_block_attacker(bear_perm, air_perm) is False


def test_birds_of_paradise_classifies_supported(all_cards):
    bop = _get(all_cards, "Birds of Paradise")
    result = classify_card(bop)
    assert result.supported


def test_birds_of_paradise_taps_for_any_color_mana(all_cards):
    bop = _get(all_cards, "Birds of Paradise")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=bop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Birds of Paradise", target_player_index=1, mana_color="U")

    assert result.supported
    assert p1.mana_pool["U"] == 1
    assert p1.battlefield[0].tapped is True


def test_bog_wraith_classifies_supported_with_swampwalk(all_cards):
    bog = _get(all_cards, "Bog Wraith")
    result = classify_card(bog)
    assert result.supported
    assert any(k.lower() == "swampwalk" for k in bog.keywords)


def test_dragon_whelp_activated_pumps_power(all_cards):
    # Dragon Whelp: "{R}: This creature gets +1/+0 until end of turn."
    dragon_whelp = _get(all_cards, "Dragon Whelp")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=dragon_whelp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before = p1.battlefield[0].effective_power
    result = game.activate_permanent_ability(0, "Dragon Whelp")

    assert result.supported
    assert p1.battlefield[0].effective_power == before + 1


def test_drudge_skeletons_regeneration_activation(all_cards):
    # Drudge Skeletons: "{1}{B} — {B}: Regenerate this creature."
    drudge = _get(all_cards, "Drudge Skeletons")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=drudge)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Drudge Skeletons")

    assert result.supported
    assert p1.battlefield[0].regeneration_shield == 1


def test_drudge_skeletons_regeneration_shield_prevents_wrath(all_cards):
    # Wrath of God says "They can't be regenerated." — regeneration shield is bypassed.
    drudge = _get(all_cards, "Drudge Skeletons")
    wrath = _get(all_cards, "Wrath of God")

    p1 = PlayerState(name="P1", hand=[wrath], battlefield=[Permanent(card=drudge)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(0, "Drudge Skeletons")
    assert p1.battlefield[0].regeneration_shield == 1

    result = game.cast_from_hand(0, "Wrath of God")

    assert result.supported
    # Wrath says "can't be regenerated" — the regeneration shield must NOT save the creature
    assert len(p1.battlefield) == 0
    assert any(c.name == "Drudge Skeletons" for c in p1.graveyard)


def test_drudge_skeletons_regeneration_shield_prevents_ordinary_destroy(all_cards):
    # Regeneration shield saves a creature from a plain "destroy target creature" effect
    # (no 'can't be regenerated' clause).  Use a synthetic sorcery to avoid card-specific
    # restrictions (Terror targets non-black, Wrath bypasses regen).
    drudge = _get(all_cards, "Drudge Skeletons")
    destroy_spell = _mk_card("Plain Destroy", "Sorcery", "Destroy target creature.")

    p1 = PlayerState(name="P1", hand=[destroy_spell])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=drudge)])
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(1, "Drudge Skeletons")
    assert p2.battlefield[0].regeneration_shield == 1

    result = game.cast_from_hand(0, "Plain Destroy", target_player_index=1, target_permanent_index=0)

    assert result.supported
    # Drudge Skeletons regenerated (shield consumed, creature tapped, stays on battlefield)
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].card.name == "Drudge Skeletons"
    assert p2.battlefield[0].regeneration_shield == 0
    assert p2.battlefield[0].tapped is True


def test_dwarven_demolition_team_destroys_wall(all_cards):
    # Dwarven Demolition Team: "{2}{R} — {T}: Destroy target Wall."
    team = _get(all_cards, "Dwarven Demolition Team")
    wall = _get(all_cards, "Wall of Stone")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=team)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Dwarven Demolition Team", target_player_index=1)

    assert result.supported
    # The team tapped to use its ability
    assert p1.battlefield[0].tapped is True
    # The wall was destroyed
    assert len(p2.battlefield) == 0
    assert p2.graveyard[0].name == "Wall of Stone"


def test_earth_elemental_enters_battlefield(all_cards):
    # Earth Elemental: "{3}{R}{R}" — vanilla 4/5 Creature — Elemental
    earth_elemental = _get(all_cards, "Earth Elemental")

    p1 = PlayerState(name="P1", hand=[earth_elemental])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Earth Elemental")

    assert result.supported
    assert len(p1.battlefield) == 1
    assert p1.battlefield[0].card.name == "Earth Elemental"


def test_elvish_archers_enters_battlefield(all_cards):
    archers = _get(all_cards, "Elvish Archers")
    p1 = PlayerState(name="P1", hand=[archers])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Elvish Archers")

    assert result.supported
    assert len(p1.battlefield) == 1
    perm = p1.battlefield[0]
    assert perm.card.name == "Elvish Archers"
    assert perm.effective_power == 2
    assert perm.effective_toughness == 1


def test_giant_spider_can_block_flying_attacker(all_cards):
    spider = _get(all_cards, "Giant Spider")
    air_elem = _get(all_cards, "Air Elemental")

    spider_perm = Permanent(card=spider)
    air_perm = Permanent(card=air_elem)

    p1 = PlayerState(name="P1", battlefield=[spider_perm])
    p2 = PlayerState(name="P2", battlefield=[air_perm])
    game = Game(players=[p1, p2])

    assert game._can_block_attacker(spider_perm, air_perm) is True


def test_goblin_king_buffs_other_goblins_with_mountainwalk(all_cards):
    king = _get(all_cards, "Goblin King")
    goblin = _mk_card("Test Goblin", "Creature — Goblin")

    p1 = PlayerState(name="P1", hand=[king], battlefield=[Permanent(card=goblin)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Goblin King")

    assert result.supported
    goblin_perm = p1.battlefield[0]
    assert goblin_perm.effective_power == 3
    assert goblin_perm.effective_toughness == 3
    assert goblin_perm.metadata.get("has_mountainwalk") is True


def test_hurloon_minotaur_classifies_supported(all_cards):
    minotaur = _get(all_cards, "Hurloon Minotaur")
    classification = classify_card(minotaur)
    assert classification.supported
    perm = Permanent(card=minotaur)
    assert perm.effective_power == 2
    assert perm.effective_toughness == 3


def test_ironclaw_orcs_cannot_block_power_2_or_greater(all_cards):
    orcs = _get(all_cards, "Ironclaw Orcs")
    grizzly = _get(all_cards, "Grizzly Bears")  # 2/2

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=orcs)], life=20)
    game = Game(players=[p1, p2])

    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    # Ironclaw Orcs cannot block a creature with power 2 or greater
    assert game._can_block_attacker(p2.battlefield[0], p1.battlefield[0]) is False


def test_ironroot_treefolk_classifies_supported(all_cards):
    treefolk = _get(all_cards, "Ironroot Treefolk")
    assert classify_card(treefolk).supported


def test_ley_druid_untaps_target_land(all_cards):
    druid = _get(all_cards, "Ley Druid")
    forest = _get(all_cards, "Forest")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=druid), Permanent(card=forest, tapped=True)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Ley Druid", target_player_index=0)

    assert result.supported
    assert p1.battlefield[1].tapped is False


def test_lord_of_atlantis_buffs_other_merfolk_with_islandwalk(all_cards):
    lord = _get(all_cards, "Lord of Atlantis")
    merfolk = _get(all_cards, "Merfolk of the Pearl Trident")

    p1 = PlayerState(name="P1", hand=[lord], battlefield=[Permanent(card=merfolk)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Lord of Atlantis")

    assert result.supported
    merfolk_perm = p1.battlefield[0]
    assert merfolk_perm.effective_power == 2
    assert merfolk_perm.effective_toughness == 2
    assert merfolk_perm.metadata.get("has_islandwalk") is True


def test_lord_of_the_pit_upkeep_sacrifices_creature(all_cards):
    pit = _get(all_cards, "Lord of the Pit")
    creature = _mk_card("Fodder", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pit), Permanent(card=creature)], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert p1.life == 20
    assert any(c.name == "Fodder" for c in p1.graveyard)
    assert len(p1.battlefield) == 1


def test_lord_of_the_pit_upkeep_deals_damage_without_creature(all_cards):
    pit = _get(all_cards, "Lord of the Pit")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pit)], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert p1.life == 13


def test_mahamoti_djinn_classifies_supported(all_cards):
    djinn = _get(all_cards, "Mahamoti Djinn")
    result = classify_card(djinn)
    assert result.supported
    perm = Permanent(card=djinn)
    assert perm.effective_power == 5
    assert perm.effective_toughness == 6


def test_merfolk_of_the_pearl_trident_classifies_supported(all_cards):
    merfolk = _get(all_cards, "Merfolk of the Pearl Trident")
    result = classify_card(merfolk)
    assert result.supported
    perm = Permanent(card=merfolk)
    assert perm.effective_power == 1
    assert perm.effective_toughness == 1


def test_ai_skips_prodigal_sorcerer_when_opponent_fully_shielded(all_cards):
    """Regression: choose_activation_action must return None (or prefer another
    action) when the only damage ability would deal 0 effective damage because
    the target's damage_prevention_pool covers the full amount."""
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    # Opponent has a 3-point prevention shield; Prodigal deals 1 → fully prevented
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prodigal)])
    p2 = PlayerState(name="P2", life=20, damage_prevention_pool=3)
    game = Game(players=[p1, p2])

    action = choose_activation_action(game, 0)

    assert action is None, (
        "AI should not waste Prodigal Sorcerer's activation when the opponent's "
        "prevention shield would absorb all damage"
    )


def test_ai_still_activates_prodigal_sorcerer_without_full_shield(all_cards):
    """Companion to the shield test: AI should still activate Prodigal Sorcerer
    when the opponent has no (or partial) prevention shielding."""
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prodigal)])
    p2 = PlayerState(name="P2", life=20, damage_prevention_pool=0)
    game = Game(players=[p1, p2])

    action = choose_activation_action(game, 0)

    assert action is not None
    assert action.permanent_name == "Prodigal Sorcerer"


def test_phantasmal_forces_sacrifices_at_upkeep_without_blue_mana(all_cards):
    forces = _get(all_cards, "Phantasmal Forces")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=forces)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not p1.battlefield
    assert any(card.name == "Phantasmal Forces" for card in p1.graveyard)


def test_phantasmal_forces_survives_upkeep_when_blue_mana_paid(all_cards):
    forces = _get(all_cards, "Phantasmal Forces")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=forces)], mana_pool={"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0})
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert any(p.card.name == "Phantasmal Forces" for p in p1.battlefield)


def test_phantom_monster_classifies_supported(all_cards):
    monster = _get(all_cards, "Phantom Monster")
    assert classify_card(monster).supported


def test_pirate_ship_cannot_attack_without_defending_island(all_cards):
    ship = _get(all_cards, "Pirate Ship")
    island = _get(all_cards, "Island")

    # Controller keeps an Island so Pirate Ship isn't sacrificed (state-based).
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ship), Permanent(card=island)])
    p2 = PlayerState(name="P2", battlefield=[])
    game = Game(players=[p1, p2])

    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is False


def test_pirate_ship_can_attack_with_defending_island(all_cards):
    ship = _get(all_cards, "Pirate Ship")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ship), Permanent(card=island)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)])
    game = Game(players=[p1, p2])

    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is True


def test_pirate_ship_tap_deals_1_damage(all_cards):
    ship = _get(all_cards, "Pirate Ship")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ship), Permanent(card=island)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Pirate Ship", target_player_index=1)

    assert result.supported
    assert p2.life == 19
    assert p1.battlefield[0].tapped is True


def test_pirate_ship_sacrifices_at_upkeep_without_islands(all_cards):
    ship = _get(all_cards, "Pirate Ship")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ship)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not any(p.card.name == "Pirate Ship" for p in p1.battlefield)
    assert any(card.name == "Pirate Ship" for card in p1.graveyard)


def test_plague_rats_power_toughness_equals_rat_count(all_cards):
    rat = _get(all_cards, "Plague Rats")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=rat), Permanent(card=rat)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._refresh_dynamic_creatures()

    assert p1.battlefield[0].effective_power == 2
    assert p1.battlefield[0].effective_toughness == 2
    assert p1.battlefield[1].effective_power == 2
    assert p1.battlefield[1].effective_toughness == 2


def test_roc_of_kher_ridges_classifies_supported_with_flying(all_cards):
    roc = _get(all_cards, "Roc of Kher Ridges")
    assert classify_card(roc).supported
    assert "Flying" in roc.keywords


def test_royal_assassin_destroys_tapped_creature(all_cards):
    assassin = _get(all_cards, "Royal Assassin")
    bear = _mk_card("Tapped Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=assassin)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear, tapped=True)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Royal Assassin", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard and p2.graveyard[0].name == "Tapped Bear"
    assert p1.battlefield[0].tapped is True


def test_samite_healer_prevents_one_damage(all_cards):
    healer = _get(all_cards, "Samite Healer")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=healer)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Samite Healer", target_player_index=1)

    assert result.supported
    assert p2.damage_prevention_pool == 1
    assert p1.battlefield[0].tapped is True


def test_savannah_lions_enters_battlefield(all_cards):
    lions = _get(all_cards, "Savannah Lions")
    p1 = PlayerState(name="P1", hand=[lions])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Savannah Lions")

    assert result.supported
    assert len(p1.battlefield) == 1
    perm = p1.battlefield[0]
    assert perm.card.name == "Savannah Lions"
    assert perm.effective_power == 2
    assert perm.effective_toughness == 1


def test_scathe_zombies_enters_battlefield(all_cards):
    zombies = _get(all_cards, "Scathe Zombies")
    p1 = PlayerState(name="P1", hand=[zombies])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Scathe Zombies")

    assert result.supported
    assert len(p1.battlefield) == 1
    perm = p1.battlefield[0]
    assert perm.card.name == "Scathe Zombies"
    assert perm.effective_power == 2
    assert perm.effective_toughness == 2


def test_scryb_sprites_enters_as_one_one_with_flying(all_cards):
    sprites = _get(all_cards, "Scryb Sprites")
    p1 = PlayerState(name="P1", hand=[sprites])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Scryb Sprites")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Scryb Sprites"
    assert perm.effective_power == 1
    assert perm.effective_toughness == 1
    assert any(k.lower() == "flying" for k in sprites.keywords)


def test_sengir_vampire_enters_battlefield(all_cards):
    vampire = _get(all_cards, "Sengir Vampire")
    p1 = PlayerState(name="P1", hand=[vampire])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sengir Vampire")

    assert result.supported
    assert p1.battlefield[0].card.name == "Sengir Vampire"
    assert p1.battlefield[0].effective_power == 4
    assert p1.battlefield[0].effective_toughness == 4


def test_shanodin_dryads_enters_with_forestwalk(all_cards):
    dryads = _get(all_cards, "Shanodin Dryads")
    p1 = PlayerState(name="P1", hand=[dryads])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Shanodin Dryads")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Shanodin Dryads"
    assert perm.effective_power == 1
    assert perm.effective_toughness == 1
    assert any(k.lower() == "forestwalk" for k in dryads.keywords)


def test_thicket_basilisk_enters_as_two_four(all_cards):
    basilisk = _get(all_cards, "Thicket Basilisk")
    p1 = PlayerState(name="P1", hand=[basilisk])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Thicket Basilisk")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Thicket Basilisk"
    assert perm.effective_power == 2
    assert perm.effective_toughness == 4


def test_vesuvan_doppelganger_copies_creature_on_entry(all_cards):
    doppelganger = _get(all_cards, "Vesuvan Doppelganger")
    serra = _get(all_cards, "Serra Angel")

    p1 = PlayerState(name="P1", hand=[doppelganger])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=serra)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Vesuvan Doppelganger")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.metadata.get("copied_from") == "Serra Angel"
    assert perm.effective_power == 4
    assert perm.effective_toughness == 4


def test_veteran_bodyguard_enters_battlefield(all_cards):
    bodyguard = _get(all_cards, "Veteran Bodyguard")
    p1 = PlayerState(name="P1", hand=[bodyguard])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Veteran Bodyguard")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Veteran Bodyguard"
    assert perm.effective_power == 2
    assert perm.effective_toughness == 5


def test_wall_of_air_enters_battlefield(all_cards):
    wall = _get(all_cards, "Wall of Air")
    p1 = PlayerState(name="P1", hand=[wall])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wall of Air")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Wall of Air"
    assert perm.effective_power == 1
    assert perm.effective_toughness == 5


def test_wall_of_brambles_regeneration_activated_ability(all_cards):
    wall = _get(all_cards, "Wall of Brambles")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wall)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Wall of Brambles")

    assert result.supported
    assert p1.battlefield[0].regeneration_shield >= 1


def test_wall_of_fire_pump_activated_ability(all_cards):
    wall = _get(all_cards, "Wall of Fire")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wall)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before_power = p1.battlefield[0].effective_power
    result = game.activate_permanent_ability(0, "Wall of Fire")

    assert result.supported
    assert p1.battlefield[0].effective_power == before_power + 1


def test_wall_of_ice_enters_battlefield(all_cards):
    wall = _get(all_cards, "Wall of Ice")
    p1 = PlayerState(name="P1", hand=[wall])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wall of Ice")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Wall of Ice"
    assert perm.effective_toughness == 7


def test_wall_of_swords_enters_battlefield(all_cards):
    wall = _get(all_cards, "Wall of Swords")
    p1 = PlayerState(name="P1", hand=[wall])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wall of Swords")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Wall of Swords"
    assert perm.effective_power == 3
    assert perm.effective_toughness == 5


def test_wall_of_water_pump_activated_ability(all_cards):
    wall = _get(all_cards, "Wall of Water")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wall)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    before_power = p1.battlefield[0].effective_power
    result = game.activate_permanent_ability(0, "Wall of Water")

    assert result.supported
    assert p1.battlefield[0].effective_power == before_power + 1


def test_wall_of_wood_enters_battlefield(all_cards):
    wall = _get(all_cards, "Wall of Wood")
    p1 = PlayerState(name="P1", hand=[wall])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wall of Wood")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Wall of Wood"
    assert perm.effective_toughness == 3


def test_war_mammoth_enters_with_trample(all_cards):
    mammoth = _get(all_cards, "War Mammoth")
    p1 = PlayerState(name="P1", hand=[mammoth])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "War Mammoth")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "War Mammoth"
    assert perm.effective_power == 3
    assert perm.effective_toughness == 3
    assert any(k.lower() == "trample" for k in mammoth.keywords)


def test_water_elemental_enters_battlefield(all_cards):
    elemental = _get(all_cards, "Water Elemental")
    p1 = PlayerState(name="P1", hand=[elemental])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Water Elemental")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Water Elemental"
    assert perm.effective_power == 5
    assert perm.effective_toughness == 4


def test_white_knight_enters_battlefield(all_cards):
    knight = _get(all_cards, "White Knight")
    p1 = PlayerState(name="P1", hand=[knight])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "White Knight")

    assert result.supported
    assert p1.battlefield[0].card.name == "White Knight"
    assert p1.battlefield[0].effective_power == 2
    assert p1.battlefield[0].effective_toughness == 2


def test_will_o_the_wisp_regeneration_activated_ability(all_cards):
    wisp = _get(all_cards, "Will-o'-the-Wisp")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wisp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Will-o'-the-Wisp")

    assert result.supported
    assert p1.battlefield[0].regeneration_shield >= 1


def test_fire_elemental_vanilla_stats_and_cast(all_cards):
    elemental = _get(all_cards, "Fire Elemental")
    assert classify_card(elemental).supported
    p1 = PlayerState(name="P1", hand=[elemental])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fire Elemental")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Fire Elemental"
    assert perm.effective_power == 5
    assert perm.effective_toughness == 4


def test_gray_ogre_vanilla_stats_and_cast(all_cards):
    ogre = _get(all_cards, "Gray Ogre")
    assert classify_card(ogre).supported
    p1 = PlayerState(name="P1", hand=[ogre])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Gray Ogre")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.effective_power == 2
    assert perm.effective_toughness == 2


def test_zombie_master_grants_swampwalk_and_regeneration_to_other_zombies(all_cards):
    master = _get(all_cards, "Zombie Master")
    zombies = _get(all_cards, "Scathe Zombies")
    zombie_perm = Permanent(card=zombies)
    p1 = PlayerState(name="P1", hand=[master], battlefield=[zombie_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Zombie Master")

    assert result.supported
    # "Other Zombie creatures have swampwalk."
    assert zombie_perm.metadata.get("has_swampwalk") is True
    # 'Other Zombies have "{B}: Regenerate this permanent."'
    assert zombie_perm.metadata.get("granted_regen_ability") is True
    regen = game.activate_permanent_ability(0, "Scathe Zombies")
    assert regen.supported
    assert zombie_perm.regeneration_shield == 1


def test_demonic_hordes_tap_ability_destroys_target_land(all_cards):
    hordes = _get(all_cards, "Demonic Hordes")
    plains = _get(all_cards, "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=hordes)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Demonic Hordes", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard and p2.graveyard[0].name == "Plains"
    assert p1.battlefield[0].tapped is True


def test_demonic_hordes_upkeep_paid_with_bbb_keeps_it_untapped(all_cards):
    hordes = _get(all_cards, "Demonic Hordes")
    swamp = _get(all_cards, "Swamp")
    hordes_perm = Permanent(card=hordes)
    p1 = PlayerState(
        name="P1",
        battlefield=[hordes_perm, Permanent(card=swamp)],
        mana_pool={"W": 0, "U": 0, "B": 3, "R": 0, "G": 0, "C": 0},
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert hordes_perm.tapped is False
    assert p1.mana_pool["B"] == 0
    assert any(p.card.name == "Swamp" for p in p1.battlefield)


def test_demonic_hordes_upkeep_unpaid_taps_it_and_sacrifices_own_land(all_cards):
    hordes = _get(all_cards, "Demonic Hordes")
    swamp = _get(all_cards, "Swamp")
    plains = _get(all_cards, "Plains")
    hordes_perm = Permanent(card=hordes)
    p1 = PlayerState(name="P1", battlefield=[hordes_perm, Permanent(card=swamp)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert hordes_perm.tapped is True
    # The controller sacrifices their own land; the opponent's land is untouched.
    assert not any(p.card.primary_type == "land" for p in p1.battlefield)
    assert any(c.name == "Swamp" for c in p1.graveyard)
    assert any(p.card.name == "Plains" for p in p2.battlefield)


def test_fungusaur_gets_counter_when_dealt_nonlethal_damage(all_cards):
    fungusaur = _get(all_cards, "Fungusaur")
    zap = _mk_card("Test Zap", "Instant", "Test Zap deals 1 damage to any target.")
    fungusaur_perm = Permanent(card=fungusaur)
    p1 = PlayerState(name="P1", battlefield=[fungusaur_perm])
    p2 = PlayerState(name="P2", hand=[zap])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Test Zap", target_player_index=0, target_permanent_index=0)

    assert result.supported
    # 2/2 base, 1 damage marked, +1/+1 counter from the trigger -> survives as a 3/3
    assert fungusaur_perm in p1.battlefield
    assert fungusaur_perm.damage_marked == 1
    assert fungusaur_perm.effective_power == 3
    assert fungusaur_perm.effective_toughness == 3


def test_personal_incarnation_death_halves_owner_life(all_cards):
    incarnation = _get(all_cards, "Personal Incarnation")
    terror = _get(all_cards, "Terror")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=incarnation)], life=20)
    p2 = PlayerState(name="P2", hand=[terror])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Terror", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert not p1.battlefield
    # "its owner loses half their life, rounded up" — 20 -> 10
    assert p1.life == 10


def test_personal_incarnation_redirect_ability_marks_redirect(all_cards):
    incarnation = _get(all_cards, "Personal Incarnation")
    incarnation_perm = Permanent(card=incarnation)
    p1 = PlayerState(name="P1", battlefield=[incarnation_perm], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Personal Incarnation")

    assert result.supported
    assert incarnation_perm.metadata.get("redirect_one_damage_to_owner_until_eot") == 1


def test_scavenging_ghoul_corpse_counters_and_regeneration(all_cards):
    ghoul = _get(all_cards, "Scavenging Ghoul")
    bears = _get(all_cards, "Grizzly Bears")
    bolt = _get(all_cards, "Lightning Bolt")
    ghoul_perm = Permanent(card=ghoul)
    p1 = PlayerState(name="P1", battlefield=[ghoul_perm])
    p2 = PlayerState(name="P2", hand=[bolt], battlefield=[Permanent(card=bears)])
    game = Game(players=[p1, p2])

    # A creature dies this turn...
    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    assert result.supported
    assert not p2.battlefield

    # ...so at the end step the Ghoul gets a corpse counter
    game.resolve_end_step(0)
    # The end-step trigger goes on the stack and resolves off it (CR 603.3).
    game.resolve_stack()
    assert ghoul_perm.metadata.get("corpse_counters") == 1

    # "Remove a corpse counter from this creature: Regenerate this creature."
    regen = game.activate_permanent_ability(0, "Scavenging Ghoul")
    assert regen.supported
    assert ghoul_perm.regeneration_shield == 1
    assert ghoul_perm.metadata.get("corpse_counters") == 0

    # With no corpse counters left, the ability cannot be activated
    regen_again = game.activate_permanent_ability(0, "Scavenging Ghoul")
    assert not regen_again.supported


def test_nettling_imp_cannot_activate_on_own_turn(all_cards):
    imp = _get(all_cards, "Nettling Imp")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=imp)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])
    game.active_player_index = 0  # the Imp's controller's own turn

    result = game.activate_permanent_ability(0, "Nettling Imp", target_player_index=1)

    assert not result.supported
    assert "opponent's turn" in result.details
    assert not p2.battlefield[0].metadata.get("must_attack_until_eot")


def test_personal_incarnation_thief_cannot_activate_but_owner_can(all_cards):
    incarnation = _get(all_cards, "Personal Incarnation")
    incarnation_perm = Permanent(card=incarnation)
    theft_source = Permanent(card=_mk_card("Theft Source", "Artifact"))
    theft_source.metadata["stolen_permanent"] = incarnation_perm
    theft_source.metadata["stolen_owner_index"] = 0
    p1 = PlayerState(name="P1", battlefield=[theft_source])   # owner (seat 0)
    p2 = PlayerState(name="P2", battlefield=[incarnation_perm])  # controller
    game = Game(players=[p1, p2])

    # The thief controls it but does not own it: activation is illegal.
    result = game.activate_permanent_ability(1, "Personal Incarnation")
    assert not result.supported
    assert "owner" in result.details
    assert not incarnation_perm.metadata.get("redirect_one_damage_to_owner_until_eot")

    # The owner may activate it even while an opponent controls it.
    result = game.activate_permanent_ability(
        0, "Personal Incarnation", source_controller_index=1
    )
    assert result.supported
    assert incarnation_perm.metadata.get("redirect_one_damage_to_owner_until_eot") == 1
