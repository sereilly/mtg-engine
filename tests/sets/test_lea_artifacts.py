"""Per-card tests for Limited Edition Alpha's artifact cards.

Split out of the 9,400-line test_lea_cards.py by the type of the
card each test names. See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState, classify_card, load_cards
from engine.models import CardDefinition, Permanent
import json
from web.app import app, store
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


def test_basalt_monolith_tap_and_untap(all_cards):
    monolith = _get(all_cards, "Basalt Monolith")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=monolith)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Tap for mana (should succeed)
    result = game.activate_permanent_ability(0, "Basalt Monolith")
    assert result.supported
    assert p1.battlefield[0].tapped is True
    assert p1.mana_pool["C"] == 3

    # Untap using ability (should succeed)
    result2 = game.activate_permanent_ability(0, "Basalt Monolith")
    assert result2.supported
    assert p1.battlefield[0].tapped is False

    # Tap again (should succeed, since it's untapped now)
    result3 = game.activate_permanent_ability(0, "Basalt Monolith")
    assert result3.supported
    assert p1.battlefield[0].tapped is True

    # Untap again (should succeed, since it's tapped)
    result4 = game.activate_permanent_ability(0, "Basalt Monolith")
    assert result4.supported
    assert p1.battlefield[0].tapped is False


def test_activate_black_lotus_adds_mana_and_sacrifices(all_cards):
    lotus = _get(all_cards, "Black Lotus")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lotus)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Black Lotus", target_player_index=1)

    assert result.supported
    assert p1.mana_pool["G"] == 3
    assert not p1.battlefield
    assert p1.graveyard and p1.graveyard[0].name == "Black Lotus"


def test_activate_black_lotus_with_selected_color(all_cards):
    lotus = _get(all_cards, "Black Lotus")
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


def test_ankh_of_mishra_triggers_on_land_entry(all_cards):
    ankh = _get(all_cards, "Ankh of Mishra")
    plains = _get(all_cards, "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ankh)])
    p2 = PlayerState(name="P2", hand=[plains], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Plains", target_player_index=1)

    assert result.supported
    assert p2.life == 18


def test_black_vise_upkeep_trigger(all_cards):
    vise = _get(all_cards, "Black Vise")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[vise])
    p2 = PlayerState(name="P2", hand=[island, island, island, island, island, island], life=20)
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Black Vise", target_player_index=1)
    game.resolve_upkeep(1)

    assert cast_result.supported
    # 6 cards in hand means 2 damage from Black Vise.
    assert p2.life == 18


def test_jayemdae_tome_activated_draw(all_cards):
    tome = _get(all_cards, "Jayemdae Tome")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tome)], library=[island])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Jayemdae Tome", target_player_index=1)

    assert result.supported
    assert len(p1.hand) == 1


def test_glasses_of_urza_look_at_hand(all_cards):
    glasses = _get(all_cards, "Glasses of Urza")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=glasses)])
    p2 = PlayerState(name="P2", hand=[island, island])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Glasses of Urza", target_player_index=1)

    assert result.supported
    assert any("looked at" in line.lower() for line in game.log)


def test_howling_mine_draw_step_bonus(all_cards):
    mine = _get(all_cards, "Howling Mine")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mine)])
    p2 = PlayerState(name="P2", library=[island, island, island])
    game = Game(players=[p1, p2])
    game.turn = 2  # an ordinary turn - turn 1 skips the draw (CR 103.8a)

    drawn = game.resolve_draw_step(1)

    assert drawn == 2
    assert len(p2.hand) == 2


def test_winter_orb_limits_land_untap(all_cards):
    orb = _get(all_cards, "Winter Orb")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=orb, tapped=False)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=island, tapped=True), Permanent(card=island, tapped=True)],
    )
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 1


def test_meekstone_prevents_big_creature_untap(all_cards):
    meekstone = _get(all_cards, "Meekstone")
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


def test_jade_statue_animates_until_end_combat(all_cards):
    statue = _get(all_cards, "Jade Statue")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=statue)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game._set_phase_and_step("combat", "beginning_of_combat")  # "Activate only during combat."

    result = game.activate_permanent_ability(0, "Jade Statue", target_player_index=1)

    assert result.supported
    assert p1.battlefield[0].effective_power == 3
    assert p1.battlefield[0].effective_toughness == 6
    game.end_combat()
    assert p1.battlefield[0].metadata.get("absolute_power") is None


def test_the_hive_creates_wasp_token(all_cards):
    hive = _get(all_cards, "The Hive")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=hive)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "The Hive", target_player_index=1)

    assert result.supported
    assert any(perm.card.name == "Wasp" for perm in p1.battlefield)


def test_black_lotus_is_classified_supported(all_cards):
    lotus = _get(all_cards, "Black Lotus")
    classification = classify_card(lotus)
    assert classification.supported


def test_forcefield_caps_next_damage_to_one(all_cards):
    forcefield = _get(all_cards, "Forcefield")
    bolt = _mk_card("Bolt Test", "Instant", "Bolt Test deals 3 damage to any target.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=forcefield)], life=20)
    p2 = PlayerState(name="P2", hand=[bolt], life=20)
    game = Game(players=[p1, p2])

    activation = game.activate_permanent_ability(0, "Forcefield", target_player_index=0)
    result = game.cast_from_hand(1, "Bolt Test", target_player_index=0)

    assert activation.supported
    assert result.supported
    assert p1.life == 19


def test_kormus_bell_animates_swamps(all_cards):
    bell = _get(all_cards, "Kormus Bell")
    swamp = _get(all_cards, "Swamp")
    p1 = PlayerState(name="P1", hand=[bell], battlefield=[Permanent(card=swamp)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Kormus Bell", target_player_index=1)

    assert result.supported
    game._refresh_dynamic_creatures()
    assert p1.battlefield[0].metadata.get("land_animated") is True
    assert p1.battlefield[0].effective_power == 1
    assert p1.battlefield[0].effective_toughness == 1


def test_library_of_leng_sets_no_max_hand_size(all_cards):
    library = _get(all_cards, "Library of Leng")
    p1 = PlayerState(name="P1", hand=[library])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Library of Leng", target_player_index=0)

    assert result.supported
    assert p1.has_no_max_hand_size is True


def test_cyclopean_tomb_marks_land_as_swamp(all_cards):
    tomb = _get(all_cards, "Cyclopean Tomb")
    plains = _get(all_cards, "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tomb)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])
    game._set_phase_and_step("beginning", "upkeep")
    game.active_player_index = 0

    result = game.activate_permanent_ability(
        0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=0
    )

    assert result.supported
    mired = p2.battlefield[0]
    assert mired.metadata.get("mire_counter") is True
    assert mired.changed_land_types == ("swamp",)
    # The land is now a Swamp: it taps for black, not white.
    assert mired.effective_produced_mana == ("B",)


def test_cyclopean_tomb_only_activates_during_your_upkeep(all_cards):
    tomb = _get(all_cards, "Cyclopean Tomb")
    plains = _get(all_cards, "Plains")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tomb)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    # Default state is a main phase — the ability is not legal here.
    result = game.activate_permanent_ability(
        0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=0
    )
    assert not result.supported
    assert p2.battlefield[0].metadata.get("mire_counter") is None

    # Not legal during the opponent's upkeep either.
    game._set_phase_and_step("beginning", "upkeep")
    game.active_player_index = 1
    result = game.activate_permanent_ability(
        0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=0
    )
    assert not result.supported
    assert p2.battlefield[0].metadata.get("mire_counter") is None


def test_cyclopean_tomb_does_not_target_swamp(all_cards):
    tomb = _get(all_cards, "Cyclopean Tomb")
    swamp = _get(all_cards, "Swamp")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tomb)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=swamp)])
    game = Game(players=[p1, p2])
    game._set_phase_and_step("beginning", "upkeep")
    game.active_player_index = 0

    result = game.activate_permanent_ability(
        0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=0
    )
    # Resolves, but a Swamp is not a legal target so no counter is placed.
    assert result.supported
    assert p2.battlefield[0].metadata.get("mire_counter") is None


def test_cyclopean_tomb_death_frees_mired_lands_over_upkeeps(all_cards):
    tomb = _get(all_cards, "Cyclopean Tomb")
    plains = _get(all_cards, "Plains")
    forest = _get(all_cards, "Forest")
    tomb_perm = Permanent(card=tomb)
    p1 = PlayerState(name="P1", battlefield=[tomb_perm])
    plains_perm = Permanent(card=plains)
    forest_perm = Permanent(card=forest)
    p2 = PlayerState(name="P2", battlefield=[plains_perm, forest_perm])
    game = Game(players=[p1, p2])
    game._set_phase_and_step("beginning", "upkeep")
    game.active_player_index = 0

    # Mire both of P2's lands across two upkeep activations (untap between).
    game.activate_permanent_ability(0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=0)
    tomb_perm.tapped = False
    game.activate_permanent_ability(0, "Cyclopean Tomb", target_player_index=1, target_permanent_index=1)
    assert plains_perm.metadata.get("mire_counter") is True
    assert forest_perm.metadata.get("mire_counter") is True

    # The Tomb dies: an obligation to free those lands is created.
    p1.battlefield.remove(tomb_perm)
    game._permanent_to_graveyard(p1, tomb_perm)
    assert len(game.mire_cleanup_obligations) == 1

    # One land is freed per controller upkeep.
    game.resolve_upkeep(0)
    freed_first = [perm for perm in (plains_perm, forest_perm) if perm.metadata.get("mire_counter") is None]
    assert len(freed_first) == 1
    assert freed_first[0].changed_land_types == ()

    # An opponent's upkeep does not advance the controller's obligation.
    game.resolve_upkeep(1)
    still_mired = [perm for perm in (plains_perm, forest_perm) if perm.metadata.get("mire_counter")]
    assert len(still_mired) == 1

    # The next controller upkeep frees the last land and clears the obligation.
    game.resolve_upkeep(0)
    assert plains_perm.metadata.get("mire_counter") is None
    assert forest_perm.metadata.get("mire_counter") is None
    assert game.mire_cleanup_obligations == []


def test_cyclopean_tomb_death_trigger_fires_on_board_wipe(all_cards):
    # A board wipe (Nevinyrral's Disk: destroy all artifacts/creatures/enchantments)
    # must still fire the Tomb's leave-the-battlefield trigger, so its mired lands
    # are freed on later upkeeps. This guards the mass-destruction path that used to
    # bypass _permanent_to_graveyard (where the leave hook lives).
    from engine.game_types import OracleExecutionContext, OracleStateMachine
    from engine.oracle import OracleInstruction

    tomb = _get(all_cards, "Cyclopean Tomb")
    plains = _get(all_cards, "Plains")
    tomb_perm = Permanent(card=tomb)
    plains_perm = Permanent(card=plains)
    p1 = PlayerState(name="P1", battlefield=[tomb_perm, plains_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game._set_phase_and_step("beginning", "upkeep")
    game.active_player_index = 0

    game.activate_permanent_ability(0, "Cyclopean Tomb", target_player_index=0, target_permanent_index=1)
    assert plains_perm.metadata.get("mire_counter") is True

    OracleStateMachine(
        game, OracleExecutionContext(caster=p1, target=p1, card=tomb)
    ).run(OracleInstruction("destroy_all_artifacts_creatures_enchantments", "", {}))

    assert not any(perm.card.name == "Cyclopean Tomb" for perm in p1.battlefield)
    assert len(game.mire_cleanup_obligations) == 1

    game.resolve_upkeep(0)
    assert plains_perm.metadata.get("mire_counter") is None
    assert plains_perm.changed_land_types == ()


def test_sunglasses_of_urza_sets_white_as_red_flag(all_cards):
    sunglasses = _get(all_cards, "Sunglasses of Urza")
    p1 = PlayerState(name="P1", hand=[sunglasses])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sunglasses of Urza", target_player_index=1)

    assert result.supported
    assert p1.can_spend_white_as_red is True


def test_helm_of_chatzuk_grants_banding_until_eot(all_cards):
    helm = _get(all_cards, "Helm of Chatzuk")
    bear = _mk_card("Band Target", "Creature — Bear")
    # Helm grants banding to the controller's own creatures (Bug 5 fix).
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=helm), Permanent(card=bear)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].tapped is True
    # Banding is granted to the caster's own creature, not an opponent's
    assert p1.battlefield[1].has_keyword("banding") is True


def test_helm_of_chatzuk_requires_valid_creature_target(all_cards):
    helm = _get(all_cards, "Helm of Chatzuk")
    # P1 has only the Helm, no creature — activation should fail
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=helm)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=0)

    assert result.supported is False
    assert result.details == "no valid target for Helm of Chatzuk"
    assert p1.battlefield[0].tapped is False


def test_web_activate_black_lotus_accepts_mana_color_choice():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4043,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    lotus = _mk_card(
        name="Black Lotus",
        mana_cost="{0}",
        type_line="Artifact",
        # The printed oracle text. Naming the card inside its own text is the
        # pre-errata wording; the reading lives in
        # card_hooks.CARD_LINE_INSTRUCTIONS under this name and this exact line,
        # so a paraphrase reaches no front end at all.
        oracle_text="{T}, Sacrifice this artifact: Add three mana of any one color.",
    )
    session.game.players[0].battlefield = [Permanent(card=lotus)]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "activate",
            "permanent_name": "Black Lotus",
            "target_seat": 0,
            "mana_color": "B",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"][0]["mana_pool"]["B"] == 3
    assert payload["players"][0]["mana_pool"]["G"] == 0
    assert payload["players"][0]["battlefield"] == []


def test_winter_orb_turn_start_requires_untap_land_selection_for_human_player():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99110,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    forest = _mk_card(
        name="Forest",
        mana_cost="",
        type_line="Basic Land - Forest",
        oracle_text="{T}: Add {G}.",
        produced_mana=("G",),
    )
    winter_orb = _mk_card(
        name="Winter Orb",
        mana_cost="{2}",
        type_line="Artifact",
        oracle_text="As long as this artifact is untapped, players can't untap more than one land during their untap steps.",
    )

    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.players[0].battlefield = [Permanent(card=winter_orb, tapped=False)]
    session.game.players[1].battlefield = [
        Permanent(card=forest, tapped=True),
        Permanent(card=forest, tapped=True),
    ]
    session.game.current_turn_phase = "postcombat_main"
    session.game.current_step = "postcombat_main"
    session.game.current_phase = "main"

    end_turn = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    assert end_turn.status_code == 200

    seat1_state = client.get(f"/api/sessions/{sid}/state?seat=1")
    assert seat1_state.status_code == 200
    state_payload = seat1_state.json()
    assert state_payload["current_turn"] == 1
    assert state_payload["current_step"] == "untap"
    assert state_payload["untap_land_selection"]["max_count"] == 1
    assert state_payload["untap_land_selection"]["selected_indices"] == []

    blocked = client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "next_phase"})
    assert blocked.status_code == 400
    assert "select untap lands" in blocked.json()["detail"].lower()

    pick_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "untap_select", "permanent_index": 0},
    )
    assert pick_land.status_code == 200
    pick_payload = pick_land.json()
    assert pick_payload["untap_land_selection"]["selected_indices"] == [0]

    confirm = client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "untap_confirm"})
    assert confirm.status_code == 200
    confirm_payload = confirm.json()
    assert confirm_payload["current_phase"] == "main"
    assert confirm_payload["current_step"] == "precombat_main"
    assert confirm_payload["untap_land_selection"] is None
    assert confirm_payload["players"][1]["battlefield"][0]["tapped"] is False
    assert confirm_payload["players"][1]["battlefield"][1]["tapped"] is True


def test_celestial_prism_adds_mana_of_chosen_color(all_cards):
    prism = _get(all_cards, "Celestial Prism")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prism)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Celestial Prism", mana_color="G")

    assert result.supported
    assert p1.mana_pool["G"] == 1
    assert p1.battlefield[0].tapped is True


def test_conservator_activated_prevents_two_damage(all_cards):
    conservator = _get(all_cards, "Conservator")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=conservator)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Conservator", target_player_index=0)

    assert result.supported
    assert p1.damage_prevention_pool == 2
    assert p1.battlefield[0].tapped is True


def test_copper_tablet_upkeep_deals_one_damage_to_active_player(all_cards):
    tablet = _get(all_cards, "Copper Tablet")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tablet)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert p1.life == 19


def test_copper_tablet_upkeep_also_damages_opponent_on_their_upkeep(all_cards):
    tablet = _get(all_cards, "Copper Tablet")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=tablet)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p2.life == 19


def test_crystal_rod_gains_life_when_controller_casts_blue_spell(all_cards):
    crystal_rod = _get(all_cards, "Crystal Rod")
    blue_spell = _mk_card("Blue Bolt", "Instant", "", mana_cost="{U}", colors=("U",))

    p1 = PlayerState(name="P1", hand=[blue_spell], life=20)
    p1.mana_pool["C"] = 1  # to pay Crystal Rod's optional {1}
    p1.battlefield.append(Permanent(card=crystal_rod))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Blue Bolt")
    game.auto_resolve_pending_optional_pays()

    assert p1.life == 21


def test_chaos_orb_flip_destroys_random_permanents_and_self(all_cards):
    import random as _random
    chaos_orb = _get(all_cards, "Chaos Orb")
    bear = _mk_card("Test Bear", "Creature - Bear")
    plains = _mk_card("Plains", "Basic Land - Plains")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=chaos_orb, tapped=False)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear), Permanent(card=plains)])
    game = Game(players=[p1, p2])

    total_before = len(p1.battlefield) + len(p2.battlefield)  # 3 (orb + bear + plains)

    _random.seed(0)
    result = game.activate_permanent_ability(0, "Chaos Orb")

    assert result.supported
    # Chaos Orb always destroys itself
    assert not any(perm.card.name == "Chaos Orb" for perm in p1.battlefield)
    assert any(card.name == "Chaos Orb" for card in p1.graveyard)
    # Total permanents remaining is between 0 and 2 (0-2 random + orb self-destroy)
    total_after = len(p1.battlefield) + len(p2.battlefield)
    assert total_after <= total_before - 1  # at least Chaos Orb destroyed
    assert total_before - total_after <= 3   # at most Chaos Orb + 2 random destroyed


def test_dingus_egg_deals_damage_when_land_destroyed(all_cards):
    # Dingus Egg: "Whenever a land is put into a graveyard from the battlefield,
    # this artifact deals 2 damage to that land's controller."
    dingus_egg = _get(all_cards, "Dingus Egg")
    stone_rain = _get(all_cards, "Stone Rain")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", hand=[stone_rain], battlefield=[Permanent(card=dingus_egg)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Stone Rain", target_player_index=1)

    assert result.supported
    assert not any(perm.card.name == "Mountain" for perm in p2.battlefield)
    assert p2.life == 18  # 2 damage from Dingus Egg


def test_disrupting_scepter_discards_card(all_cards):
    # Disrupting Scepter: "{3}, {T}: Target player discards a card."
    scepter = _get(all_cards, "Disrupting Scepter")
    island = _mk_card("Island", "Basic Land - Island")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=scepter)])
    p2 = PlayerState(name="P2", hand=[island, island, island])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Disrupting Scepter", target_player_index=1)

    assert result.supported
    # The discard now defers to the discarding player's choice; resolve it.
    assert game.pending_discard is not None
    assert game.confirm_discard(1, [0])
    assert len(p2.hand) == 2
    assert len(p2.graveyard) == 1


def test_gauntlet_of_might_buffs_red_creatures(all_cards):
    gauntlet = _get(all_cards, "Gauntlet of Might")
    red_creature = _mk_card("Red Goblin", "Creature — Goblin", colors=("R",))

    p1 = PlayerState(name="P1", hand=[gauntlet], battlefield=[Permanent(card=red_creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Gauntlet of Might")

    assert result.supported
    assert p1.battlefield[0].effective_power == 3
    assert p1.battlefield[0].effective_toughness == 3


def test_gauntlet_of_might_mountain_tap_grants_extra_red(all_cards):
    gauntlet = _get(all_cards, "Gauntlet of Might")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=gauntlet), Permanent(card=mountain)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.tap_land_for_mana(0, "Mountain")

    assert p1.mana_pool.get("R", 0) == 2


def test_gauntlet_of_might_does_not_grant_red_for_a_non_mountain(all_cards):
    """The trigger names a Mountain, so tapping any other land must add nothing.

    The land type rides the trigger condition's payload rather than a per-card
    hook, and a condition that ignored it would read as "whenever a land is
    tapped for mana" — a strictly larger effect on every board with a dual or a
    basic of another type.
    """
    gauntlet = _get(all_cards, "Gauntlet of Might")
    forest = _get(all_cards, "Forest")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=gauntlet), Permanent(card=forest)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.tap_land_for_mana(0, "Forest")

    assert p1.mana_pool.get("G", 0) == 1
    assert p1.mana_pool.get("R", 0) == 0


def test_icy_manipulator_taps_target_creature(all_cards):
    icy = _get(all_cards, "Icy Manipulator")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=icy)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Icy Manipulator", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].tapped is True


def test_illusionary_mask_classifies_supported(all_cards):
    mask = _get(all_cards, "Illusionary Mask")
    classification = classify_card(mask)
    assert classification.supported


def test_illusionary_mask_activation_creates_face_down_creature(all_cards):
    mask = _get(all_cards, "Illusionary Mask")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[grizzly], battlefield=[Permanent(card=mask)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Activate with X large enough to pay Grizzly Bears (cmc 2), then choose it.
    result = game.activate_permanent_ability(0, "Illusionary Mask", target_player_index=1, x_value=2)
    assert result.supported
    assert game.pending_face_down_cast is not None
    assert game.confirm_face_down_cast(0, 0) is True

    face_down = next(
        (perm for perm in p1.battlefield if perm.metadata.get("face_down")),
        None,
    )
    assert face_down is not None
    assert face_down.effective_power == 2
    assert face_down.effective_toughness == 2


def test_iron_star_gains_life_on_red_spell(all_cards):
    star = _get(all_cards, "Iron Star")
    lightning_bolt = _get(all_cards, "Lightning Bolt")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=star)], life=20)
    p1.mana_pool["C"] = 1  # to pay Iron Star's optional {1}
    p2 = PlayerState(name="P2", hand=[lightning_bolt], life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(1, "Lightning Bolt", target_player_index=1)
    game.auto_resolve_pending_optional_pays()

    # Iron Star should have triggered: P1 paid {1} and gains 1 life
    assert p1.life == 21


def test_ivory_cup_triggers_on_white_spell(all_cards):
    cup = _get(all_cards, "Ivory Cup")
    salve = _get(all_cards, "Healing Salve")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cup)], life=20)
    p1.mana_pool["C"] = 1  # to pay Ivory Cup's optional {1}
    p2 = PlayerState(name="P2", hand=[salve])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Healing Salve", target_player_index=1)
    game.auto_resolve_pending_optional_pays()

    assert result.supported
    assert p1.life == 21


def test_jade_monolith_redirects_damage_to_controller(all_cards):
    monolith = _get(all_cards, "Jade Monolith")
    bear = _mk_card("Bear", "Creature — Bear")
    bolt = _mk_card("Bolt Test", "Instant", "Bolt Test deals 3 damage to any target.")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=monolith)], life=20)
    p2 = PlayerState(name="P2", hand=[bolt], battlefield=[Permanent(card=bear)], life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Jade Monolith", target_player_index=1)
    assert result.supported

    result2 = game.cast_from_hand(1, "Bolt Test", target_player_index=1, target_permanent_index=0)
    assert result2.supported
    assert len(p2.battlefield) == 1  # bear survives (damage redirected)
    assert p1.life == 17             # monolith controller took 3 damage
    assert p2.life == 20


def test_mana_vault_taps_for_three_colorless_mana(all_cards):
    vault = _get(all_cards, "Mana Vault")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=vault)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mana Vault")

    assert result.supported
    assert p1.mana_pool["C"] == 3
    assert p1.battlefield[0].tapped is True


def test_mox_emerald_taps_for_green_mana(all_cards):
    mox = _get(all_cards, "Mox Emerald")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mox Emerald")

    assert result.supported
    assert p1.mana_pool["G"] == 1
    assert p1.battlefield[0].tapped is True


def test_mox_jet_taps_for_black_mana(all_cards):
    mox = _get(all_cards, "Mox Jet")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mox Jet")

    assert result.supported
    assert p1.mana_pool["B"] == 1
    assert p1.battlefield[0].tapped is True


def test_mox_pearl_taps_for_white_mana(all_cards):
    mox = _get(all_cards, "Mox Pearl")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mox Pearl")

    assert result.supported
    assert p1.mana_pool["W"] == 1
    assert p1.battlefield[0].tapped is True


def test_mox_ruby_taps_for_red_mana(all_cards):
    mox = _get(all_cards, "Mox Ruby")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mox Ruby")

    assert result.supported
    assert p1.mana_pool["R"] == 1
    assert p1.battlefield[0].tapped is True


def test_mox_sapphire_taps_for_blue_mana(all_cards):
    mox = _get(all_cards, "Mox Sapphire")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Mox Sapphire")

    assert result.supported
    assert p1.mana_pool["U"] == 1
    assert p1.battlefield[0].tapped is True


def test_rod_of_ruin_deals_one_damage_to_target(all_cards):
    rod = _get(all_cards, "Rod of Ruin")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=rod)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1)

    assert result.supported
    assert p2.life == 19
    assert p1.battlefield[0].tapped is True


def test_sol_ring_adds_two_colorless_mana(all_cards):
    sol_ring = _get(all_cards, "Sol Ring")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=sol_ring)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Sol Ring")

    assert result.supported
    assert p1.mana_pool.get("C", 0) == 2
    assert p1.battlefield[0].tapped is True


def test_soul_net_enters_battlefield(all_cards):
    soul_net = _get(all_cards, "Soul Net")
    p1 = PlayerState(name="P1", hand=[soul_net])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Soul Net")

    assert result.supported
    assert p1.battlefield[0].card.name == "Soul Net"
    assert not p1.hand


def test_throne_of_bone_gains_life_when_black_spell_cast(all_cards):
    throne = _get(all_cards, "Throne of Bone")
    black_spell = _mk_card("Dark Ritual", "Instant", "", mana_cost="{B}", colors=("B",))

    p1 = PlayerState(name="P1", hand=[black_spell], battlefield=[Permanent(card=throne)], life=20)
    p1.mana_pool["C"] = 1  # to pay Throne of Bone's optional {1}
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Dark Ritual")
    game.auto_resolve_pending_optional_pays()

    assert p1.life == 21


def test_time_vault_grants_extra_turn(all_cards):
    time_vault = _get(all_cards, "Time Vault")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=time_vault, tapped=False)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Time Vault")

    assert result.supported
    assert p1.battlefield[0].tapped is True
    assert game.extra_turns.get(0, 0) >= 1


def test_wooden_sphere_gains_life_when_green_spell_cast(all_cards):
    sphere = _get(all_cards, "Wooden Sphere")
    green_spell = _mk_card("Giant Growth", "Instant", "", mana_cost="{G}", colors=("G",))

    p1 = PlayerState(name="P1", hand=[green_spell], battlefield=[Permanent(card=sphere)], life=20)
    p1.mana_pool["C"] = 1  # to pay Wooden Sphere's optional {1}
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Giant Growth")
    game.auto_resolve_pending_optional_pays()

    assert p1.life == 21


def test_wooden_sphere_gains_life_on_green_creature_spell(all_cards):
    # Regression: rod-style life gain must also fire when the green spell that
    # resolves is a permanent (creature/artifact), not only an instant/sorcery.
    sphere = _get(all_cards, "Wooden Sphere")
    bears = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=sphere)], hand=[bears])
    p1.mana_pool["C"] = 1  # to pay Wooden Sphere's optional {1}
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    starting_life = p1.life
    game.cast_from_hand(0, "Grizzly Bears")
    game.auto_resolve_pending_optional_pays()

    assert p1.life == starting_life + 1


def test_jade_statue_cannot_animate_outside_combat(all_cards):
    statue = _get(all_cards, "Jade Statue")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=statue)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])  # default: precombat main

    result = game.activate_permanent_ability(0, "Jade Statue", target_player_index=1)

    assert not result.supported
    assert "during combat" in result.details
    assert p1.battlefield[0].metadata.get("absolute_power") is None


def test_illusionary_mask_activates_only_as_a_sorcery(all_cards):
    mask = _get(all_cards, "Illusionary Mask")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mask)], hand=[_get(all_cards, "Grizzly Bears")])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._set_phase_and_step("combat", "declare_attackers")

    result = game.activate_permanent_ability(0, "Illusionary Mask", target_player_index=1, x_value=2)

    assert not result.supported
    assert "sorcery" in result.details


def test_black_vise_duel_needs_no_prompt_even_for_a_human(all_cards):
    vise = _get(all_cards, "Black Vise")
    p1 = PlayerState(name="P1", hand=[vise])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}

    result = game.cast_from_hand(0, "Black Vise", target_player_index=1)

    assert result.supported
    # A duel has exactly one opponent — the choice is forced, no prompt.
    assert game.pending_enter_choice is None
    assert p1.battlefield[0].metadata.get("chosen_player_index") == 1


def test_black_vise_multiplayer_prompts_human_and_confirm_overrides(all_cards):
    vise = _get(all_cards, "Black Vise")
    p1 = PlayerState(name="P1", hand=[vise])
    p2 = PlayerState(name="P2")
    p3 = PlayerState(name="P3")
    game = Game(players=[p1, p2, p3])
    game.interactive_seats = {0}

    result = game.cast_from_hand(0, "Black Vise", target_player_index=2)

    assert result.supported
    vise_perm = p1.battlefield[0]
    # The cast target is the provisional default...
    assert vise_perm.metadata.get("chosen_player_index") == 2
    pending = game.pending_enter_choice
    assert pending is not None
    assert pending["controller_index"] == 0
    assert pending["opponents"] == [1, 2]
    assert pending["needs_color"] is False
    # ...and the human's confirm overrides it.
    assert game.confirm_enter_choice(0, 1) is True
    assert vise_perm.metadata.get("chosen_player_index") == 1
    assert game.pending_enter_choice is None


def test_black_vise_multiplayer_headless_defaults_without_prompt(all_cards):
    vise = _get(all_cards, "Black Vise")
    p1 = PlayerState(name="P1", hand=[vise])
    p2 = PlayerState(name="P2")
    p3 = PlayerState(name="P3")
    game = Game(players=[p1, p2, p3])  # no interactive seats (AI/headless)

    result = game.cast_from_hand(0, "Black Vise", target_player_index=2)

    assert result.supported
    assert game.pending_enter_choice is None
    assert p1.battlefield[0].metadata.get("chosen_player_index") == 2


# --- Round 95: Black Lotus without a hook -----------------------------------


def test_black_lotus_runs_off_the_grammar(cards):
    """It kept a fused ``sacrifice_self_for_mana`` card hook for exactly as long
    as "three mana of any one color" had nowhere to put its number. The
    sacrifice is an ordinary activation cost and the mana an ordinary
    instruction, so the decomposition is the card as printed — and the hook is
    gone rather than shadowed."""
    from engine.card_hooks import CARD_LINE_INSTRUCTIONS
    from engine.oracle import compile_card_oracle

    assert "Black Lotus" not in CARD_LINE_INSTRUCTIONS

    program = compile_card_oracle(cards["Black Lotus"])
    (ability,) = program.activated_abilities
    assert ability.cost.sacrifice_self
    assert ability.instruction.payload["any_color_count"] == 3


def test_black_lotus_still_adds_three_of_one_colour(cards):
    from tests.helpers import _nosick

    lotus = _nosick(Permanent(card=cards["Black Lotus"]))
    p1 = PlayerState(name="P1", battlefield=[lotus])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = True

    result = game.activate_permanent_ability(
        0, "Black Lotus", permanent_index=0, mana_color="R"
    )

    assert result.supported, result.details
    assert p1.mana_pool["R"] == 3
    assert not game.is_on_battlefield(lotus), "sacrificed to pay its own cost"


# --- Round 140: Mana Vault's draw-step damage -------------------------------


def _vault_game(cards):
    vault = Permanent(card=cards["Mana Vault"])
    p1 = PlayerState(name="P1", battlefield=[vault], library=[])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    # CR 103.8a's first-turn skip is a skip of the *draw*, not of the step, but
    # the step still has to be reached on a turn the engine does not shortcut.
    game.turn = 3
    game._sync_control()
    return game, p1, vault


def test_mana_vault_damages_its_controller_at_the_draw_step_while_tapped(cards):
    """"At the beginning of your draw step, if this artifact is tapped, it
    deals 1 damage to you." Acknowledged as unimplemented since the parsing
    registry was deleted: the draw step had no trigger dispatch and no table
    held a draw-step condition for a single permanent, so a tapped Mana Vault
    cost its controller nothing."""
    game, p1, vault = _vault_game(cards)
    vault.tapped = True

    game.resolve_draw_step(0)

    assert p1.life == 19


def test_mana_vault_deals_no_damage_at_the_draw_step_while_untapped(cards):
    """The other half of the same clause. CR 603.4's intervening-if is checked
    as the trigger would fire, so an untapped Vault never puts one on the
    stack — a gate that cannot fail is the same silence as no gate at all."""
    game, p1, vault = _vault_game(cards)
    vault.tapped = False

    game.resolve_draw_step(0)

    assert p1.life == 20


def test_mana_vault_untapped_by_its_upkeep_trigger_skips_the_draw_step_damage(cards):
    """The two triggers as one turn: paying {4} at upkeep untaps the Vault, and
    the draw step's gate then reads the state it was left in rather than the
    state it was in when the turn began."""
    game, p1, vault = _vault_game(cards)
    vault.tapped = True
    p1.mana_pool["C"] = 4  # the upkeep pay is charged from the pool, not waived

    game.resolve_upkeep(0)
    assert not vault.tapped, "the {4} was paid, so the Vault untapped"

    game.resolve_draw_step(0)

    assert p1.life == 20


class TestArtifactCards:
    def test_black_lotus_adds_three_mana(self, all_cards):
        lotus = _get(all_cards, "Black Lotus")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=lotus)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Black Lotus", mana_color="U")

        assert result.supported
        assert p1.mana_pool["U"] == 3
        assert not p1.battlefield  # lotus sacrificed itself

    def test_mox_sapphire_taps_for_blue(self, all_cards):
        mox = _get(all_cards, "Mox Sapphire")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Mox Sapphire", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["U"] == 1

    def test_mox_emerald_taps_for_green(self, all_cards):
        mox = _get(all_cards, "Mox Emerald")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Mox Emerald", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["G"] == 1

    def test_mox_jet_taps_for_black(self, all_cards):
        mox = _get(all_cards, "Mox Jet")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Mox Jet", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["B"] == 1

    def test_mox_pearl_taps_for_white(self, all_cards):
        mox = _get(all_cards, "Mox Pearl")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Mox Pearl", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["W"] == 1

    def test_mox_ruby_taps_for_red(self, all_cards):
        mox = _get(all_cards, "Mox Ruby")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=mox)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Mox Ruby", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["R"] == 1

    def test_sol_ring_taps_for_two_colorless(self, all_cards):
        ring = _get(all_cards, "Sol Ring")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=ring)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Sol Ring", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["C"] == 2

    def test_nevinyrral_disk_destroys_artifacts_creatures_enchantments(self, all_cards):
        disk = _get(all_cards, "Nevinyrral's Disk")
        bear = _grizzly(all_cards)
        bad_moon = _get(all_cards, "Bad Moon")
        plains = _plains(all_cards)

        p1 = PlayerState(
            name="P1",
            battlefield=[
                Permanent(card=disk, tapped=False),
                Permanent(card=bear),
                Permanent(card=bad_moon),
                Permanent(card=plains),
            ],
        )
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Nevinyrral's Disk")

        assert result.supported
        types_remaining = {p.card.primary_type for p in p1.battlefield}
        assert "creature" not in types_remaining
        assert "enchantment" not in types_remaining
        assert "artifact" not in types_remaining
        assert "land" in types_remaining  # plains survives

    def test_steal_artifact_moves_artifact_to_caster(self, all_cards):
        steal = _get(all_cards, "Steal Artifact")
        sol_ring = _get(all_cards, "Sol Ring")

        p1 = PlayerState(name="P1", hand=[steal])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=sol_ring)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert any(p.card.name == "Sol Ring" for p in p1.battlefield)
        assert not any(p.card.name == "Sol Ring" for p in p2.battlefield)

    def test_icy_manipulator_taps_any_permanent(self, all_cards):
        icy = _get(all_cards, "Icy Manipulator")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", battlefield=[Permanent(card=icy)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Icy Manipulator", target_player_index=1)

        assert result.supported
        assert p2.battlefield[0].tapped is True

    def test_rod_of_ruin_deals_1_damage(self, all_cards):
        rod = _get(all_cards, "Rod of Ruin")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=rod)])
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1)

        assert result.supported
        assert p2.life == 19
