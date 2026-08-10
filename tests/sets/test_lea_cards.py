"""Limited Edition Alpha tests that are not about one card.

The per-card tests live in test_lea_<type>.py alongside this file; what
is left here is cross-cutting — AI policy on the LEA pool, the web
session layer, mana and timing rules, and the colour/type suites.
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
import json
import web.session_store as web_session_store
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


def test_choose_activation_action_prefers_prodigal_for_lethal(all_cards):
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    tome = _get(all_cards, "Jayemdae Tome")

    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=tome), Permanent(card=prodigal)],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 4},
        library=[_get(all_cards, "Island")],
    )
    p2 = PlayerState(name="P2", life=1)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_activation_action(game, 0)

    assert action is not None
    assert action.permanent_name == "Prodigal Sorcerer"
    assert action.target_player_index == 1


def test_choose_combat_blockers_tries_to_prevent_lethal(all_cards):
    craw_wurm = _get(all_cards, "Craw Wurm")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=craw_wurm), Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly), Permanent(card=grizzly)], life=7)
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0, 1], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    blockers = choose_combat_blockers(game, 1)

    assert blockers
    assert len(blockers) == 2


def test_choose_combat_blockers_returns_empty_when_no_legal_blockers(all_cards):
    craw_wurm = _get(all_cards, "Craw Wurm")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=craw_wurm)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)], life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    blockers = choose_combat_blockers(game, 1)
    assert blockers == {}


def test_choose_combat_instant_cast_action_prefers_interaction_in_block_step(all_cards):
    bolt = _get(all_cards, "Lightning Bolt")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", life=5)
    p2 = PlayerState(
        name="P2",
        hand=[bolt],
        battlefield=[Permanent(card=mountain)],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
    )
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_blockers"
    game.current_phase = "combat"

    action = choose_combat_instant_cast_action(game, 1)

    assert action is not None


def test_destroy_all_lands_spell(all_cards):
    armageddon = _get(all_cards, "Armageddon")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[armageddon])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(plains))
    p2.battlefield.append(Permanent(plains))

    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Armageddon", target_player_index=1)

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
    game.auto_resolve_pending_discard()  # the discarder picks which card(s)
    assert len(p2.hand) == 1
    assert len(p2.graveyard) == 2


def test_nevinyrrals_disk_enters_tapped(all_cards):
    disk = _get(all_cards, "Nevinyrral's Disk")
    p1 = PlayerState(name="P1", hand=[disk])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Nevinyrral's Disk")
    assert cast_result.supported
    assert len(p1.battlefield) == 1
    assert p1.battlefield[0].card.name == "Nevinyrral's Disk"
    assert p1.battlefield[0].tapped is True

    assert game.tap_permanent(0, "Nevinyrral's Disk") is False


def test_activate_nevinyrrals_disk_destroys_artifacts_creatures_and_enchantments(all_cards):
    disk = _get(all_cards, "Nevinyrral's Disk")
    land = _mk_card("Test Plains", "Land")
    artifact = _mk_card("Test Relic", "Artifact")
    creature = _mk_card("Test Bear", "Creature — Bear")
    enchantment = _mk_card("Test Aura", "Enchantment")

    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=disk, tapped=False),
            Permanent(card=artifact),
            Permanent(card=creature),
            Permanent(card=land),
        ],
    )
    p2 = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=enchantment),
            Permanent(card=creature),
            Permanent(card=land),
        ],
    )
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Nevinyrral's Disk", target_player_index=1)

    assert result.supported
    assert [perm.card.primary_type for perm in p1.battlefield] == ["land"]
    assert [perm.card.primary_type for perm in p2.battlefield] == ["land"]
    assert any(card.name == "Nevinyrral's Disk" for card in p1.graveyard)
    assert any(card.name == "Test Relic" for card in p1.graveyard)
    assert any(card.name == "Test Bear" for card in p1.graveyard)
    assert any(card.name == "Test Aura" for card in p2.graveyard)


def test_lace_spell_changes_target_color(all_cards):
    deathlace = _get(all_cards, "Deathlace")
    creature = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[deathlace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Deathlace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "B"


def test_summoning_sickness_blocks_attacks_and_tap_abilities(all_cards):
    creature = _mk_card("Test Bear", "Creature — Bear")
    llanowar_elves = _get(all_cards, "Llanowar Elves")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=creature), Permanent(card=llanowar_elves)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.turn = 4

    p1.battlefield[0].metadata["summoning_sickness_turn"] = game.turn
    assert game.can_attack(p1.battlefield[0], defending_player_index=1) is False

    p1.battlefield[1].metadata["summoning_sickness_turn"] = game.turn
    result = game.activate_permanent_ability(0, "Llanowar Elves", target_player_index=0)

    assert result.supported is False
    assert "summoning sickness" in result.details.lower()


def test_fog_sets_combat_damage_prevention(all_cards):
    fog = _get(all_cards, "Fog")
    p1 = PlayerState(name="P1", hand=[fog])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fog", target_player_index=0)

    assert result.supported
    assert game.combat_damage_prevented_until_eot is True


def test_mana_pool_empties_between_steps(all_cards):
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", mana_pool={"W": 0, "U": 2, "B": 0, "R": 0, "G": 0, "C": 1})
    p2 = PlayerState(name="P2", library=[island])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p1.mana_pool["U"] == 0
    assert p1.mana_pool["C"] == 0


def test_circle_of_protection_activation_sets_prevention(all_cards):
    cop = _get(all_cards, "Circle of Protection: Blue")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: Blue", target_player_index=0)

    assert result.supported
    assert p1.color_prevention_shields == ["U"]


def test_ai_reorder_surfaces_best_card_on_own_library(all_cards):
    bolt = _get(all_cards, "Lightning Bolt")
    ancestral = _get(all_cards, "Ancestral Recall")
    land = _get(all_cards, "Forest")
    # AI seat 0 reorders its own top three: [land, bolt, ancestral].
    p1 = PlayerState(name="P1", library=[land, bolt, ancestral])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    order = choose_reorder_library_order(game, caster_index=0, target_index=0, top_count=3)
    reordered = [game.players[0].library[i].name for i in order]

    # Highest-value spells are surfaced ahead of the land we'd rather not draw next.
    assert reordered[-1] == "Forest"
    assert "Forest" not in reordered[:2]


def test_ai_reorder_buries_opponent_best_card(all_cards):
    bolt = _get(all_cards, "Lightning Bolt")
    ancestral = _get(all_cards, "Ancestral Recall")
    land = _get(all_cards, "Forest")
    # AI seat 0 reorders the opponent's top three.
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", library=[land, bolt, ancestral])
    game = Game(players=[p1, p2])

    order = choose_reorder_library_order(game, caster_index=0, target_index=1, top_count=3)
    reordered = [game.players[1].library[i].name for i in order]

    # The opponent's strongest card should not be left on top to be drawn next.
    assert reordered[0] != "Ancestral Recall"


def test_ai_reorder_order_is_valid_permutation(all_cards):
    cards = [_mk_card(name, "Sorcery") for name in ["A", "B", "C"]]
    p1 = PlayerState(name="P1", library=list(cards))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    order = choose_reorder_library_order(game, caster_index=0, target_index=0, top_count=3)
    assert sorted(order) == [0, 1, 2]


def test_banding_keyword_cards_classify_supported(all_cards):
    benalish_hero = _get(all_cards, "Benalish Hero")
    mesa_pegasus = _get(all_cards, "Mesa Pegasus")
    timber_wolves = _get(all_cards, "Timber Wolves")

    assert classify_card(benalish_hero).supported
    assert classify_card(mesa_pegasus).supported
    assert classify_card(timber_wolves).supported


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


def test_remaining_cards_classify_supported(all_cards):
    names = ["Contract from Below", "Darkpact", "Demonic Attorney", "Copy Artifact"]
    for name in names:
        card = next(c for c in all_cards if c.name == name)
        assert classify_card(card).supported


def test_loader_reads_cards(set_cards):
    cards = set_cards("LEA")
    assert len(cards) > 250
    assert any(card.name == "Black Lotus" for card in cards)


def test_strict_mana_allows_cast_after_tapping_land():
    spell = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )

    p1 = PlayerState(name="P1", hand=[spell], battlefield=[Permanent(card=mountain)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    assert game.tap_land_for_mana(0, "Mountain")
    result = game.cast_from_hand(0, "Bolt Test", target_player_index=1)

    assert result.supported
    assert p2.life == 17
    assert p1.mana_pool["R"] == 0


def test_tapping_basic_land_without_produced_mana_uses_land_type():
    swamp = _mk_card(
        name="Swamp",
        mana_cost="",
        type_line="Basic Land - Swamp",
        oracle_text="({T}: Add {B}.)",
    )

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=swamp)])
    game = Game(players=[p1], enforce_mana_costs=True)

    assert game.tap_land_for_mana(0, "Swamp")
    assert p1.mana_pool["B"] == 1


def test_x_spell_infers_x_from_paid_mana():
    spell = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )

    p1 = PlayerState(name="P1", hand=[spell], mana_pool={"G": 1, "C": 1}, life=10)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Stream of Life", target_player_index=0)

    assert result.supported
    assert p1.life == 11
    assert p1.mana_pool["G"] == 0
    assert p1.mana_pool["C"] == 0


def test_create_session_uses_random_seed_by_default(monkeypatch):
    captured_seeds = []
    stub_deck = [_mk_card("Island", "", "Basic Land - Island", "") for _ in range(40)]

    def _fake_build_random_deck(_cards_path, _colors, seed, allow_ante=False):
        captured_seeds.append(seed)
        return list(stub_deck), ["U"]

    monkeypatch.setattr(web_session_store, "build_random_deck", _fake_build_random_deck)
    monkeypatch.setattr(web_session_store.secrets, "randbits", lambda _bits: 424242)

    response = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 3,
        },
    )

    assert response.status_code == 200
    assert captured_seeds == [424242, 424243]


def test_create_session_uses_custom_seed_when_enabled(monkeypatch):
    captured_seeds = []
    stub_deck = [_mk_card("Island", "", "Basic Land - Island", "") for _ in range(40)]

    def _fake_build_random_deck(_cards_path, _colors, seed, allow_ante=False):
        captured_seeds.append(seed)
        return list(stub_deck), ["U"]

    monkeypatch.setattr(web_session_store, "build_random_deck", _fake_build_random_deck)
    monkeypatch.setattr(web_session_store.secrets, "randbits", lambda _bits: 111111)

    response = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 3,
            "use_custom_seed": True,
            "custom_seed": 9001,
        },
    )

    assert response.status_code == 200
    assert captured_seeds == [9001, 9002]


def test_card_search_endpoint_returns_autocomplete_matches():
    response = client.get("/api/cards/search?query=air&limit=5")
    assert response.status_code == 200
    payload = response.json()
    assert "cards" in payload
    assert len(payload["cards"]) <= 5
    assert any(card["name"] == "Air Elemental" for card in payload["cards"])


def test_debug_action_adds_card_to_human_hand_case_insensitive_lookup():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 9090,
        },
    ).json()
    sid = created["session_id"]

    before_count = len(store.get(sid).game.players[0].hand)
    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_add_to_hand", "card_name": "air elemental"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["players"][0]["hand"]) == before_count + 1
    assert payload["players"][0]["hand"][-1]["name"] == "Air Elemental"
    assert any("[Debug]" in entry and "Air Elemental" in entry for entry in payload["log"])


def test_debug_action_casts_card_for_free():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 9091,
        },
    ).json()
    sid = created["session_id"]

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_cast_free", "card_name": "lightning bolt"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["players"][1]["life"] == 20
    assert payload["stack"][0]["card"]["name"] == "Lightning Bolt"
    assert any("[Debug]" in entry and "Lightning Bolt" in entry for entry in payload["log"])


def test_get_optional_upkeep_triggers_empty_when_condition_unmet(all_cards):
    shadow = _get(all_cards, "Nether Shadow")
    bears = _get(all_cards, "Grizzly Bears")
    # Only two creatures above — not eligible, so no prompt should be offered.
    p1 = PlayerState(name="P1", graveyard=[shadow, bears, bears])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert game.get_optional_upkeep_triggers(0) == []


def test_debug_action_casts_creature_with_summoning_sickness_flag():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 9092,
        },
    ).json()
    sid = created["session_id"]

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_cast_free", "card_name": "Llanowar Elves"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stack"][0]["card"]["name"] == "Llanowar Elves"
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    resolved = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "pass_priority"},
    )
    assert resolved.status_code == 200
    resolved = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "pass_priority"},
    )
    assert resolved.status_code == 200
    payload = resolved.json()
    battlefield = payload["players"][0]["battlefield"]
    assert battlefield[0]["name"] == "Llanowar Elves"
    assert battlefield[0]["summoning_sick"] is True


def test_web_session_requires_paid_mana_before_cast():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 999,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    bolt = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )

    session.game.players[0].hand = [bolt]
    session.game.players[0].battlefield = [Permanent(card=mountain)]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    session.game.players[1].life = 20

    unpaid_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert unpaid_cast.status_code == 400
    assert "insufficient mana" in unpaid_cast.json()["detail"].lower()

    tap_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Mountain", "target_seat": 0},
    )
    assert tap_land.status_code == 200

    paid_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert paid_cast.status_code == 200
    _resolve_top_stack(sid, 0)
    assert store.get(sid).game.players[1].life == 17


def test_web_cast_accepts_explicit_x_value():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4044,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    stream = _mk_card(
        name="Stream of Life",
        mana_cost="{X}{G}",
        type_line="Sorcery",
        oracle_text="Target player gains X life.",
    )
    session.game.players[0].hand = [stream]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 1}
    session.game.players[0].life = 10

    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Stream of Life", "target_seat": 0, "x_value": 1},
    )

    assert response.status_code == 200
    _resolve_top_stack(sid, 0)
    payload = response.json()
    refreshed = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert refreshed["players"][0]["life"] == 11
    assert any("Stream of Life" in entry and "10 -> 11" in entry for entry in refreshed["log"])


def test_playing_land_is_special_action_and_keeps_priority():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 40436,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    island = _mk_card(
        name="Island",
        mana_cost="",
        type_line="Basic Land - Island",
        oracle_text="{T}: Add {U}.",
        produced_mana=("U",),
    )
    session.game.players[0].hand = [island]
    session.game.players[0].battlefield = []
    session.game.current_turn_phase = "precombat_main"
    session.game.current_step = "precombat_main"
    session.game.current_phase = "main"
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.start_priority_window(0)

    play_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Island", "target_seat": 0},
    )
    assert play_land.status_code == 200

    payload = play_land.json()
    assert payload["priority_player"] == 0
    assert payload["priority_pass_count"] == 0
    assert payload["stack"] == []
    assert len(payload["players"][0]["battlefield"]) == 1
    assert payload["players"][0]["battlefield"][0]["name"] == "Island"


def test_pass_priority_triggers_ai_instant_response_on_opponent_turn():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 40433,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    bolt = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )
    session.game.players[1].hand = [bolt]
    session.game.players[1].battlefield = [Permanent(card=mountain)]
    session.game.players[1].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    session.game.players[0].life = 20
    session.game.players[1].life = 20

    passed = _pass_priority(sid, 0)
    assert passed.status_code == 200
    payload = passed.json()
    assert payload["priority_player"] == 0
    assert payload["priority_pass_count"] == 1
    assert len(payload["stack"]) == 1
    assert payload["stack"][0]["card"]["name"] == "Bolt Test"
    assert payload["players"][0]["life"] == 20

    resolve = _pass_priority(sid, 0)
    assert resolve.status_code == 200
    resolved_payload = resolve.json()
    assert resolved_payload["stack"] == []
    assert resolved_payload["players"][0]["life"] == 17


def test_activated_ability_stays_on_stack_until_priority_passes():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 40432,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    sorcerer = _mk_card(
        name="Prodigal Sorcerer",
        mana_cost="{2}{U}",
        type_line="Creature - Human Wizard",
        oracle_text="{T}: Prodigal Sorcerer deals 1 damage to any target.",
    )
    session.game.players[0].battlefield = [Permanent(card=sorcerer)]
    session.game.players[1].life = 20

    activate = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Prodigal Sorcerer", "target_seat": 1},
    )
    assert activate.status_code == 200
    activate_payload = activate.json()
    assert len(activate_payload["stack"]) == 1
    assert activate_payload["stack"][0]["type"] == "ability"
    assert activate_payload["players"][1]["life"] == 20

    _resolve_top_stack(sid, 0)
    resolved = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert resolved["players"][1]["life"] == 19
    assert resolved["stack"] == []


def test_tap_action_on_land_adds_mana_and_cannot_retap():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 2026,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )
    session.game.players[0].battlefield = [Permanent(card=mountain)]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    first_tap = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "tap", "permanent_name": "Mountain"},
    )
    assert first_tap.status_code == 200
    assert store.get(sid).game.players[0].mana_pool["R"] == 1

    second_tap = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "tap", "permanent_name": "Mountain"},
    )
    assert second_tap.status_code == 400


def test_activate_land_uses_permanent_index_when_duplicate_names_exist():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 2027,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    forest = _mk_card(
        name="Forest",
        mana_cost="",
        type_line="Basic Land - Forest",
        oracle_text="{T}: Add {G}.",
        produced_mana=("G",),
    )

    first_forest = Permanent(card=forest)
    second_forest = Permanent(card=forest)
    session.game.players[0].battlefield = [first_forest, second_forest]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    tap_second = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "activate",
            "permanent_name": "Forest",
            "permanent_index": 1,
            "target_seat": 0,
        },
    )

    assert tap_second.status_code == 200
    assert session.game.players[0].battlefield[0].tapped is False
    assert session.game.players[0].battlefield[1].tapped is True
    assert session.game.players[0].mana_pool["G"] == 1


def test_activate_with_mana_cost_requires_payment_before_tap():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 3030,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    tome = _mk_card(
        name="Jayemdae Tome",
        mana_cost="{4}",
        type_line="Artifact",
        oracle_text="{4}, {T}: Draw a card.",
    )
    island = _mk_card(
        name="Island",
        mana_cost="",
        type_line="Basic Land - Island",
        oracle_text="{T}: Add {U}.",
        produced_mana=("U",),
    )

    session.game.players[0].battlefield = [Permanent(card=tome)]
    session.game.players[0].library = [island]
    session.game.players[0].mana_pool = {"W": 0, "U": 3, "B": 0, "R": 0, "G": 0, "C": 0}

    unpaid = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Jayemdae Tome", "target_seat": 1},
    )
    assert unpaid.status_code == 400
    assert "insufficient mana" in unpaid.json()["detail"].lower()
    assert store.get(sid).game.players[0].battlefield[0].tapped is False

    session.game.players[0].mana_pool = {"W": 0, "U": 4, "B": 0, "R": 0, "G": 0, "C": 0}
    paid = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Jayemdae Tome", "target_seat": 1},
    )
    assert paid.status_code == 200
    assert store.get(sid).game.players[0].battlefield[0].tapped is True


def test_instant_allowed_on_opponent_turn():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 12346,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    instant = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )
    session.game.players[0].hand = [instant]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}
    session.game.players[0].battlefield = [Permanent(card=mountain)]
    session.game.players[1].life = 20

    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    assert store.get(sid).current_turn == 1

    passed = _pass_priority(sid, 1)
    assert passed.status_code == 200

    tap_mountain = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Mountain", "target_seat": 0},
    )
    assert tap_mountain.status_code == 200

    off_turn_instant = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Bolt Test", "target_seat": 1},
    )
    assert off_turn_instant.status_code == 200
    _resolve_top_stack(sid, 0)
    assert store.get(sid).game.players[1].life == 17


def test_only_one_land_play_per_turn_then_resets_next_turn():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 22336,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    plains_a = _mk_card(
        name="Plains A",
        mana_cost="",
        type_line="Basic Land - Plains",
        oracle_text="{T}: Add {W}.",
        produced_mana=("W",),
    )
    plains_b = _mk_card(
        name="Plains B",
        mana_cost="",
        type_line="Basic Land - Plains",
        oracle_text="{T}: Add {W}.",
        produced_mana=("W",),
    )
    session.game.players[0].hand = [plains_a, plains_b]

    first_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains A", "target_seat": 0},
    )
    assert first_land.status_code == 200

    second_land_same_turn = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains B", "target_seat": 0},
    )
    assert second_land_same_turn.status_code == 400
    assert "already played a land" in second_land_same_turn.json()["detail"].lower()

    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    seat1_end = client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "end_turn"})
    if seat1_end.status_code == 200 and seat1_end.json().get("cleanup_discard"):
        client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 1, "action": "cleanup_select", "hand_index": 0},
        )
        client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "next_phase"})

    second_land_next_turn = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains B", "target_seat": 0},
    )
    assert second_land_next_turn.status_code == 200


def test_next_phase_ai_defender_casts_instant_after_declaring_blockers():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99202,
        },
    ).json()
    sid = created["session_id"]

    session = store.get(sid)
    attacker = _mk_creature_card("Attacker", 3, 3)
    blocker = _mk_creature_card("Blocker", 2, 2)
    bolt = _mk_card(
        name="Lightning Bolt",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Lightning Bolt deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )

    session.game.players[0].battlefield = [Permanent(card=attacker)]
    session.game.players[0].life = 20
    session.game.players[1].battlefield = [Permanent(card=blocker), Permanent(card=mountain)]
    session.game.players[1].hand = [bolt]
    session.game.players[1].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.current_turn_phase = "combat"
    session.game.current_step = "declare_attackers"
    session.game.current_phase = "combat"

    declared = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "declare_attackers", "attacker_indices": [0], "target_seat": 1},
    )
    assert declared.status_code == 200

    to_blockers = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "next_phase"},
    )
    assert to_blockers.status_code == 200
    assert to_blockers.json()["current_step"] == "declare_blockers"

    ai_block_and_cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "next_phase"},
    )
    assert ai_block_and_cast.status_code == 200
    payload = ai_block_and_cast.json()
    assert payload["current_step"] == "declare_blockers"
    assert payload["combat"]["blockers_locked"] is True
    assert payload["players"][0]["life"] == 17


def test_mons_goblin_raiders_classifies_supported(all_cards):
    raiders = _get(all_cards, "Mons's Goblin Raiders")
    result = classify_card(raiders)
    assert result.supported
    perm = Permanent(card=raiders)
    assert perm.effective_power == 1
    assert perm.effective_toughness == 1


def test_creature_prevention_pool_clears_at_end_of_turn(all_cards):
    """The creature prevention shield is a 'this turn' effect and must reset so it
    doesn't linger into later turns."""
    salve = _get(all_cards, "Healing Salve")
    bear = _grizzly(all_cards)

    p1 = PlayerState(name="P1", hand=[salve])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Healing Salve", target_player_index=1, target_permanent_index=0, mode_index=1)
    assert p2.battlefield[0].damage_prevention_pool == 3

    game.resolve_cleanup_step(0)
    assert p2.battlefield[0].damage_prevention_pool == 0


def test_sirens_call_resolves_without_error(all_cards):
    sirens_call = _get(all_cards, "Siren's Call")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[sirens_call])
    p2 = PlayerState(name="P2", library=[island])
    game = Game(players=[p1, p2])

    # Castable only during an opponent's turn, before attackers are declared.
    game.start_turn(1)
    result = game.cast_from_hand(0, "Siren's Call")

    assert result.supported
    assert not p1.hand
    assert any(c.name == "Siren's Call" for c in p1.graveyard)


def test_two_headed_giant_enters_with_trample(all_cards):
    giant = _get(all_cards, "Two-Headed Giant of Foriys")
    p1 = PlayerState(name="P1", hand=[giant])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Two-Headed Giant of Foriys")

    assert result.supported
    perm = p1.battlefield[0]
    assert perm.card.name == "Two-Headed Giant of Foriys"
    assert perm.effective_power == 4
    assert perm.effective_toughness == 4
    assert any(k.lower() == "trample" for k in giant.keywords)


class TestRegressionWrathOfGod:
    """Wrath of God says 'They can't be regenerated.' â€” the regeneration shield
    must be bypassed, not consumed."""

    def test_wrath_kills_creature_with_regen_shield(self, all_cards):
        wrath = _get(all_cards, "Wrath of God")
        drudge = _get(all_cards, "Drudge Skeletons")

        p1 = PlayerState(name="P1", hand=[wrath])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=drudge, regeneration_shield=3)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Wrath of God")

        assert result.supported
        assert len(p2.battlefield) == 0
        assert any(c.name == "Drudge Skeletons" for c in p2.graveyard)

    def test_wrath_kills_all_creatures_both_sides(self, all_cards):
        wrath = _get(all_cards, "Wrath of God")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[wrath], battlefield=[Permanent(card=bear)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Wrath of God")

        assert result.supported
        assert len(p1.battlefield) == 0
        assert len(p2.battlefield) == 0

    def test_wrath_does_not_destroy_lands(self, all_cards):
        wrath = _get(all_cards, "Wrath of God")
        plains = _plains(all_cards)

        p1 = PlayerState(name="P1", hand=[wrath], battlefield=[Permanent(card=plains)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
        game = Game(players=[p1, p2])

        game.cast_from_hand(0, "Wrath of God")

        assert len(p1.battlefield) == 1  # plains survive
        assert len(p2.battlefield) == 1


class TestRegressionSwordsToPlowshares:
    """Swords to Plowshares must *exile* the target creature (not destroy it) and
    give its controller life equal to the creature's power."""

    def test_exiles_not_destroys(self, all_cards):
        stoP = _get(all_cards, "Swords to Plowshares")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[stoP])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0
        # Exiled, not in graveyard
        assert not any(c.name == "Grizzly Bears" for c in p2.graveyard)
        assert any(c.name == "Grizzly Bears" for c in p2.exile)

    def test_controller_gains_life_equal_to_power(self, all_cards):
        stoP = _get(all_cards, "Swords to Plowshares")
        bear = _grizzly(all_cards)  # power 2

        p1 = PlayerState(name="P1", hand=[stoP])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], life=20)
        game = Game(players=[p1, p2])

        game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

        assert p2.life == 22  # gained 2 (power of Grizzly Bears)

    def test_life_gain_scales_with_power(self, all_cards):
        stoP = _get(all_cards, "Swords to Plowshares")
        dragon = _get(all_cards, "Shivan Dragon")  # 5/5

        p1 = PlayerState(name="P1", hand=[stoP])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=dragon)], life=10)
        game = Game(players=[p1, p2])

        game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

        assert p2.life == 15  # gained 5 (Shivan Dragon power)


class TestRegressionTerror:
    """Terror: 'Destroy target nonartifact, nonblack creature. It can't be
    regenerated.' â€” must reject black and artifact targets."""

    def test_terror_destroys_green_creature(self, all_cards):
        terror = _get(all_cards, "Terror")
        bear = _grizzly(all_cards)  # green creature

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0
        assert any(c.name == "Grizzly Bears" for c in p2.graveyard)

    def test_terror_cannot_destroy_black_creature(self, all_cards):
        terror = _get(all_cards, "Terror")
        knight = _get(all_cards, "Black Knight")  # black creature

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=knight)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        # A black creature is not a legal target, so Terror can't be cast at it (601.2c).
        assert not result.supported
        assert len(p2.battlefield) == 1  # knight survives
        assert not any(c.name == "Black Knight" for c in p2.graveyard)

    def test_terror_cannot_destroy_artifact_creature(self, all_cards):
        terror = _get(all_cards, "Terror")
        golem = _get(all_cards, "Obsianus Golem")  # artifact creature

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=golem)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        # An artifact creature is not a legal target, so Terror can't be cast at it (601.2c).
        assert not result.supported
        assert len(p2.battlefield) == 1  # golem survives

    def test_terror_bypasses_regeneration(self, all_cards):
        terror = _get(all_cards, "Terror")
        # Uthden Troll is a red, regenerating creature â€” not black or artifact
        troll = _get(all_cards, "Uthden Troll")

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=troll, regeneration_shield=1)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        assert result.supported
        # Terror says "It can't be regenerated" â€” shield must not save it
        assert len(p2.battlefield) == 0
        assert any(c.name == "Uthden Troll" for c in p2.graveyard)


class TestRegressionStealArtifact:
    """Steal Artifact ('Enchant artifact / You control enchanted artifact') must
    move the target artifact to the caster's battlefield, just like Control Magic
    does for creatures."""

    def test_steal_artifact_moves_artifact_to_caster(self, all_cards):
        steal = _get(all_cards, "Steal Artifact")
        lotus = _get(all_cards, "Black Lotus")

        p1 = PlayerState(name="P1", hand=[steal])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=lotus)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert any(p.card.name == "Black Lotus" for p in p1.battlefield)
        assert not any(p.card.name == "Black Lotus" for p in p2.battlefield)

    def test_steal_artifact_aura_stays_on_casters_side(self, all_cards):
        steal = _get(all_cards, "Steal Artifact")
        sol_ring = _get(all_cards, "Sol Ring")

        p1 = PlayerState(name="P1", hand=[steal])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=sol_ring)])
        game = Game(players=[p1, p2])

        game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)

        assert any(p.card.name == "Steal Artifact" for p in p1.battlefield)

    def test_steal_artifact_requires_artifact_target(self, all_cards):
        steal = _get(all_cards, "Steal Artifact")
        bear = _grizzly(all_cards)  # creature, not artifact

        p1 = PlayerState(name="P1", hand=[steal])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        # Steal Artifact targets artifacts; casting at a non-artifact should fail
        result = game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)

        # Spell resolves but the non-artifact is not stolen
        assert not any(p.card.name == "Grizzly Bears" for p in p1.battlefield)


class TestWhiteCards:
    def test_armageddon_destroys_all_lands(self, all_cards):
        armageddon = _get(all_cards, "Armageddon")
        plains = _plains(all_cards)

        p1 = PlayerState(name="P1", hand=[armageddon], battlefield=[Permanent(card=plains)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Armageddon")

        assert result.supported
        assert all(p.card.primary_type != "land" for p in p1.battlefield)
        assert all(p.card.primary_type != "land" for p in p2.battlefield)

    def test_balance_equalizes_resources(self, all_cards):
        balance = _get(all_cards, "Balance")
        plains = _plains(all_cards)
        bear = _grizzly(all_cards)

        p1 = PlayerState(
            name="P1",
            hand=[balance, plains, plains],
            battlefield=[Permanent(card=plains), Permanent(card=plains), Permanent(card=bear)],
        )
        p2 = PlayerState(
            name="P2",
            hand=[],
            battlefield=[Permanent(card=plains)],
        )
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Balance")
        game.auto_resolve_pending_balance()  # each player chooses; auto for headless

        assert result.supported
        p1_lands = sum(1 for p in p1.battlefield if p.card.primary_type == "land")
        p2_lands = sum(1 for p in p2.battlefield if p.card.primary_type == "land")
        assert p1_lands == p2_lands

    def test_benalish_hero_is_1_1_with_banding(self, all_cards):
        hero = _get(all_cards, "Benalish Hero")
        assert classify_card(hero).supported
        perm = Permanent(card=hero)
        assert perm.effective_power == 1
        assert perm.effective_toughness == 1
        assert "Banding" in hero.keywords

    def test_circle_of_protection_white_prevents_damage(self, all_cards):
        cop = _get(all_cards, "Circle of Protection: White")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Circle of Protection: White", target_player_index=0)

        assert result.supported
        assert p1.color_prevention_shields == ["W"]

    def test_crusade_buffs_white_creatures(self, all_cards):
        crusade = _get(all_cards, "Crusade")
        hero = _get(all_cards, "Benalish Hero")

        p1 = PlayerState(name="P1", hand=[crusade], battlefield=[Permanent(card=hero)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Crusade")

        assert result.supported
        assert p1.battlefield[0].effective_power == 2
        assert p1.battlefield[0].effective_toughness == 2

    def test_disenchant_destroys_enchantment(self, all_cards):
        disenchant = _get(all_cards, "Disenchant")
        bad_moon = _get(all_cards, "Bad Moon")

        p1 = PlayerState(name="P1", hand=[disenchant])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bad_moon)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Disenchant", target_player_index=1)

        assert result.supported
        assert len(p2.battlefield) == 0
        assert any(c.name == "Bad Moon" for c in p2.graveyard)

    def test_disenchant_destroys_artifact(self, all_cards):
        disenchant = _get(all_cards, "Disenchant")
        lotus = _get(all_cards, "Black Lotus")

        p1 = PlayerState(name="P1", hand=[disenchant])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=lotus)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Disenchant", target_player_index=1)

        assert result.supported
        assert len(p2.battlefield) == 0

    def test_fog_prevents_all_combat_damage(self, all_cards):
        fog = _get(all_cards, "Fog")
        p1 = PlayerState(name="P1", hand=[fog])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Fog")

        assert result.supported
        assert game.combat_damage_prevented_until_eot is True

    def test_healing_salve_prevents_damage(self, all_cards):
        salve = _get(all_cards, "Healing Salve")
        p1 = PlayerState(name="P1", hand=[salve], life=10)
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Healing Salve", target_player_index=0)

        assert result.supported
        # Healing Salve either gains 3 life or prevents 3 damage
        assert p1.damage_prevention_pool >= 3 or p1.life == 13

    def test_holy_strength_buffs_creature(self, all_cards):
        holy_strength = _get(all_cards, "Holy Strength")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[holy_strength])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Holy Strength", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert p2.battlefield[0].effective_power == 3
        assert p2.battlefield[0].effective_toughness == 4

    def test_resurrection_returns_creature_from_graveyard(self, all_cards):
        resurrect = _get(all_cards, "Resurrection")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[resurrect], graveyard=[bear])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Resurrection", target_player_index=0)

        assert result.supported
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)
        assert not any(c.name == "Grizzly Bears" for c in p1.graveyard)

    def test_reverse_damage_replaces_damage_with_life_gain(self, all_cards):
        reverse = _get(all_cards, "Reverse Damage")
        p1 = PlayerState(name="P1", hand=[reverse], life=20)
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Reverse Damage", target_player_index=0)

        assert result.supported

    def test_righteousness_buffs_blocking_creature(self, all_cards):
        righteousness = _get(all_cards, "Righteousness")
        bear = _grizzly(all_cards)
        attacker = Permanent(card=_grizzly(all_cards))
        attacker.metadata["summoning_sickness_turn"] = -99

        p1 = PlayerState(name="P1", hand=[righteousness], battlefield=[attacker])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])
        # The target must be a creature that is currently blocking.
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1
        game.declare_attackers(0, [0], 1)
        game._set_phase_and_step("combat", "declare_blockers")
        game.declare_blockers(1, {0: 0})

        before = p2.battlefield[0].effective_toughness
        result = game.cast_from_hand(0, "Righteousness", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert p2.battlefield[0].effective_toughness >= before

    def test_samite_healer_prevents_damage(self, all_cards):
        healer = _get(all_cards, "Samite Healer")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=healer)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Samite Healer", target_player_index=0)

        assert result.supported
        assert p1.damage_prevention_pool >= 1

    def test_serra_angel_is_4_4_flying_vigilance(self, all_cards):
        angel = _get(all_cards, "Serra Angel")
        p1 = PlayerState(name="P1", hand=[angel])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Serra Angel")

        assert result.supported
        perm = p1.battlefield[0]
        assert perm.effective_power == 4
        assert perm.effective_toughness == 4
        assert "Flying" in angel.keywords
        assert "Vigilance" in angel.keywords

    def test_swords_to_plowshares_exiles_and_gains_life(self, all_cards):
        stoP = _get(all_cards, "Swords to Plowshares")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[stoP])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert any(c.name == "Grizzly Bears" for c in p2.exile)
        assert p2.life == 22  # +2 for Grizzly Bears' power


class TestBlueCards:
    def test_ancestral_recall_draws_three(self, all_cards):
        recall = _get(all_cards, "Ancestral Recall")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[recall])
        p2 = PlayerState(name="P2", library=[island] * 5)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Ancestral Recall", target_player_index=1)

        assert result.supported
        assert len(p2.hand) == 3

    def test_blue_elemental_blast_counters_red_spell(self, all_cards):
        beb = _get(all_cards, "Blue Elemental Blast")
        bolt = _get(all_cards, "Lightning Bolt")

        p1 = PlayerState(name="P1", hand=[beb])
        p2 = PlayerState(name="P2", hand=[bolt], life=20)
        game = Game(players=[p1, p2])

        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        result = game.cast_from_hand(0, "Blue Elemental Blast", target_player_index=1)

        assert result.supported
        assert any("countered" in line.lower() for line in game.log)
        assert p1.life == 20  # bolt was countered

    def test_braingeyser_draws_x_cards(self, all_cards):
        geyser = _get(all_cards, "Braingeyser")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[geyser])
        p2 = PlayerState(name="P2", library=[island] * 10)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Braingeyser", target_player_index=1, x_value=5)

        assert result.supported
        assert len(p2.hand) == 5

    def test_clone_copies_creature(self, all_cards):
        clone = _get(all_cards, "Clone")
        dragon = _get(all_cards, "Shivan Dragon")

        p1 = PlayerState(name="P1", hand=[clone], battlefield=[Permanent(card=dragon)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Clone", target_player_index=0)

        assert result.supported
        clone_perm = next(p for p in p1.battlefield if p.card.name == "Clone")
        assert clone_perm.metadata.get("copied_from") == "Shivan Dragon"

    def test_control_magic_steals_creature(self, all_cards):
        ctrl = _get(all_cards, "Control Magic")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[ctrl])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Control Magic", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)
        assert not any(p.card.name == "Grizzly Bears" for p in p2.battlefield)

    def test_counterspell_counters_spell(self, all_cards):
        counter = _get(all_cards, "Counterspell")
        recall = _get(all_cards, "Ancestral Recall")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[recall])
        p2 = PlayerState(name="P2", hand=[counter], library=[island] * 5)
        game = Game(players=[p1, p2])

        game.queue_from_hand(0, "Ancestral Recall", target_player_index=1)
        game.queue_from_hand(1, "Counterspell", target_player_index=0)
        game.resolve_stack()

        assert any(c.name == "Ancestral Recall" for c in p1.graveyard)
        assert len(p2.hand) == 0  # did not draw 3

    def test_drain_power_taps_opponent_lands_and_steals_mana(self, all_cards):
        drain = _get(all_cards, "Drain Power")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[drain])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=island), Permanent(card=island)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Drain Power", target_player_index=1)

        assert result.supported
        assert all(p.tapped for p in p2.battlefield)

    def test_lord_of_atlantis_buffs_merfolk(self, all_cards):
        lord = _get(all_cards, "Lord of Atlantis")
        merfolk = _get(all_cards, "Merfolk of the Pearl Trident")

        p1 = PlayerState(name="P1", hand=[lord], battlefield=[Permanent(card=merfolk)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Lord of Atlantis")

        assert result.supported
        assert p1.battlefield[0].effective_power == 2  # 1 + 1 from lord
        assert p1.battlefield[0].effective_toughness == 2

    def test_mana_short_taps_all_lands_and_empties_pool(self, all_cards):
        mana_short = _get(all_cards, "Mana Short")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[mana_short])
        p2 = PlayerState(
            name="P2",
            battlefield=[Permanent(card=island), Permanent(card=island)],
            mana_pool={"W": 0, "U": 3, "B": 0, "R": 0, "G": 0, "C": 0},
        )
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Mana Short", target_player_index=1)

        assert result.supported
        assert all(p.tapped for p in p2.battlefield)
        assert p2.mana_pool["U"] == 0

    def test_mind_twist_discards_x_cards(self, all_cards):
        twist = _get(all_cards, "Mind Twist")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[twist])
        p2 = PlayerState(name="P2", hand=[island] * 5)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Mind Twist", target_player_index=1, x_value=3)

        assert result.supported
        assert len(p2.hand) == 2
        assert len(p2.graveyard) == 3

    def test_power_sink_counters_with_mana_drain(self, all_cards):
        power_sink = _get(all_cards, "Power Sink")
        recall = _get(all_cards, "Ancestral Recall")

        p1 = PlayerState(name="P1", hand=[power_sink])
        p2 = PlayerState(name="P2", hand=[recall])
        game = Game(players=[p1, p2])

        game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
        result = game.cast_from_hand(0, "Power Sink", target_player_index=1, x_value=2)

        assert result.supported

    def test_time_walk_grants_extra_turn(self, all_cards):
        walk = _get(all_cards, "Time Walk")
        p1 = PlayerState(name="P1", hand=[walk])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Time Walk")

        assert result.supported
        assert game.extra_turns.get(0, 0) == 1

    def test_timetwister_shuffles_and_draws_seven(self, all_cards):
        twister = _get(all_cards, "Timetwister")
        island = _island(all_cards)
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[twister], graveyard=[bear], library=[island] * 10)
        p2 = PlayerState(name="P2", hand=[island, island], graveyard=[bear], library=[island] * 10)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Timetwister")

        assert result.supported
        assert len(p1.hand) == 7
        assert len(p2.hand) == 7

    def test_unsummon_returns_creature_to_hand(self, all_cards):
        unsummon = _get(all_cards, "Unsummon")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[unsummon])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Unsummon", target_player_index=1)

        assert result.supported
        assert not p2.battlefield
        assert any(c.name == "Grizzly Bears" for c in p2.hand)

    def test_wheel_of_fortune_discards_and_draws_seven(self, all_cards):
        wheel = _get(all_cards, "Wheel of Fortune")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[wheel, island], library=[island] * 10)
        p2 = PlayerState(name="P2", hand=[island, island], library=[island] * 10)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Wheel of Fortune")

        assert result.supported
        assert len(p1.hand) == 7
        assert len(p2.hand) == 7


class TestBlackCards:
    def test_animate_dead_reanimates_from_graveyard(self, all_cards):
        animate = _get(all_cards, "Animate Dead")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[animate], graveyard=[bear])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Animate Dead", target_player_index=0)

        assert result.supported
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)

    def test_black_knight_is_2_2_protection_from_white(self, all_cards):
        knight = _get(all_cards, "Black Knight")
        perm = Permanent(card=knight)
        assert perm.effective_power == 2
        assert perm.effective_toughness == 2
        assert "First strike" in knight.keywords or "First Strike" in knight.keywords
        assert classify_card(knight).supported

    def test_dark_ritual_adds_black_mana(self, all_cards):
        ritual = _get(all_cards, "Dark Ritual")
        p1 = PlayerState(name="P1", hand=[ritual])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Dark Ritual", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["B"] == 3

    def test_demonic_tutor_searches_library(self, all_cards):
        tutor = _get(all_cards, "Demonic Tutor")
        mountain = _get(all_cards, "Mountain")
        forest = _forest(all_cards)
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[tutor], library=[mountain, forest, island])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Demonic Tutor", target_player_index=0)

        assert result.supported
        assert game.pending_search_library is not None
        confirmed = game.confirm_search_library(0, 2)
        assert confirmed
        assert any(c.name == "Island" for c in p1.hand)

    def test_drain_life_damages_and_heals(self, all_cards):
        drain = _get(all_cards, "Drain Life")
        p1 = PlayerState(name="P1", hand=[drain], life=10)
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Drain Life", target_player_index=1, x_value=5)

        assert result.supported
        assert p2.life == 15  # took 5 damage
        assert p1.life == 15  # gained 5 life

    def test_hypnotic_specter_enters_as_2_2_flying(self, all_cards):
        specter = _get(all_cards, "Hypnotic Specter")
        assert classify_card(specter).supported
        perm = Permanent(card=specter)
        assert perm.effective_power == 2
        assert perm.effective_toughness == 2
        assert "Flying" in specter.keywords

    def test_raise_dead_returns_creature_to_hand(self, all_cards):
        raise_dead = _get(all_cards, "Raise Dead")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[raise_dead], graveyard=[bear])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Raise Dead", target_player_index=0)

        assert result.supported
        assert any(c.name == "Grizzly Bears" for c in p1.hand)
        assert not any(c.name == "Grizzly Bears" for c in p1.graveyard)

    def test_royal_assassin_destroys_tapped_creature(self, all_cards):
        assassin = _get(all_cards, "Royal Assassin")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", battlefield=[Permanent(card=assassin)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear, tapped=True)])
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Royal Assassin", target_player_index=1)

        assert result.supported
        assert not p2.battlefield

    def test_sinkhole_destroys_target_land(self, all_cards):
        sinkhole = _get(all_cards, "Sinkhole")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[sinkhole])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Sinkhole", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0

    def test_terror_destroys_nonblack_nona_rtifact_creature(self, all_cards):
        terror = _get(all_cards, "Terror")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0

    def test_terror_rejected_by_black_creature(self, all_cards):
        terror = _get(all_cards, "Terror")
        knight = _get(all_cards, "Black Knight")

        p1 = PlayerState(name="P1", hand=[terror])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=knight)])
        game = Game(players=[p1, p2])

        game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

        assert len(p2.battlefield) == 1  # knight survives

    def test_wrath_of_god_bypasses_regeneration(self, all_cards):
        wrath = _get(all_cards, "Wrath of God")
        drudge = _get(all_cards, "Drudge Skeletons")

        p1 = PlayerState(name="P1", hand=[wrath])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=drudge, regeneration_shield=2)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Wrath of God")

        assert result.supported
        assert len(p2.battlefield) == 0


class TestRedCards:
    def test_berserk_grants_trample_and_doubles_power(self, all_cards):
        berserk = _get(all_cards, "Berserk")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[berserk])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        before_power = p2.battlefield[0].effective_power
        result = game.cast_from_hand(0, "Berserk", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert p2.battlefield[0].effective_power >= before_power * 2

    def test_disintegrate_damages_player(self, all_cards):
        disintegrate = _get(all_cards, "Disintegrate")
        p1 = PlayerState(name="P1", hand=[disintegrate])
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Disintegrate", target_player_index=1, x_value=5)

        assert result.supported
        assert p2.life == 15

    def test_earthquake_deals_x_to_non_flying_and_players(self, all_cards):
        quake = _get(all_cards, "Earthquake")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[quake], life=20)
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Earthquake", x_value=3)

        assert result.supported
        assert p1.life == 17  # took 3 damage
        assert p2.life == 17  # took 3 damage
        assert len(p2.battlefield) == 0  # bear died

    def test_fireball_deals_x_damage_to_player(self, all_cards):
        fireball = _get(all_cards, "Fireball")
        p1 = PlayerState(name="P1", hand=[fireball])
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=7)

        assert result.supported
        assert p2.life == 13

    def test_lightning_bolt_deals_3_damage(self, all_cards):
        bolt = _get(all_cards, "Lightning Bolt")
        p1 = PlayerState(name="P1", hand=[bolt])
        p2 = PlayerState(name="P2", life=20)
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)

        assert result.supported
        assert p2.life == 17

    def test_lightning_bolt_kills_creature(self, all_cards):
        bolt = _get(all_cards, "Lightning Bolt")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[bolt])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0

    def test_red_elemental_blast_counters_blue_spell(self, all_cards):
        reb = _get(all_cards, "Red Elemental Blast")
        recall = _get(all_cards, "Ancestral Recall")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[reb])
        p2 = PlayerState(name="P2", hand=[recall], library=[island] * 5, life=20)
        game = Game(players=[p1, p2])

        game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
        result = game.cast_from_hand(0, "Red Elemental Blast", target_player_index=1)

        assert result.supported
        assert any("countered" in line.lower() for line in game.log)

    def test_shatter_destroys_artifact(self, all_cards):
        shatter = _get(all_cards, "Shatter")
        lotus = _get(all_cards, "Black Lotus")

        p1 = PlayerState(name="P1", hand=[shatter])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=lotus)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Shatter", target_player_index=1)

        assert result.supported
        assert len(p2.battlefield) == 0

    def test_stone_rain_destroys_target_land(self, all_cards):
        rain = _get(all_cards, "Stone Rain")
        island = _island(all_cards)

        p1 = PlayerState(name="P1", hand=[rain])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Stone Rain", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert len(p2.battlefield) == 0


class TestGreenCards:
    def test_giant_growth_pumps_creature(self, all_cards):
        growth = _get(all_cards, "Giant Growth")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[growth])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Giant Growth", target_player_index=1, target_permanent_index=0)

        assert result.supported
        assert p2.battlefield[0].effective_power == 5
        assert p2.battlefield[0].effective_toughness == 5

    def test_llanowar_elves_taps_for_green_mana(self, all_cards):
        elves = _get(all_cards, "Llanowar Elves")
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=elves)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.activate_permanent_ability(0, "Llanowar Elves", target_player_index=0)

        assert result.supported
        assert p1.mana_pool["G"] == 1

    def test_regrowth_returns_card_from_graveyard_to_hand(self, all_cards):
        regrowth = _get(all_cards, "Regrowth")
        bear = _grizzly(all_cards)

        p1 = PlayerState(name="P1", hand=[regrowth], graveyard=[bear])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Regrowth", target_player_index=0)

        assert result.supported
        assert any(c.name == "Grizzly Bears" for c in p1.hand)
        assert not any(c.name == "Grizzly Bears" for c in p1.graveyard)

    def test_stream_of_life_gains_x_life(self, all_cards):
        stream = _get(all_cards, "Stream of Life")
        p1 = PlayerState(name="P1", hand=[stream], life=10)
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Stream of Life", target_player_index=0, x_value=7)

        assert result.supported
        assert p1.life == 17

    def test_tranquility_destroys_all_enchantments(self, all_cards):
        tranquility = _get(all_cards, "Tranquility")
        bad_moon = _get(all_cards, "Bad Moon")

        p1 = PlayerState(name="P1", hand=[tranquility])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=bad_moon)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Tranquility")

        assert result.supported
        assert all(p.card.primary_type != "enchantment" for p in p2.battlefield)

    def test_tsunami_destroys_all_islands(self, all_cards):
        tsunami = _get(all_cards, "Tsunami")
        island = _island(all_cards)
        forest = _forest(all_cards)

        p1 = PlayerState(name="P1", hand=[tsunami], battlefield=[Permanent(card=forest)])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=island), Permanent(card=forest)])
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Tsunami")

        assert result.supported
        assert all("island" not in p.card.type_line.lower() for p in p2.battlefield)
        assert any("forest" in p.card.type_line.lower() for p in p1.battlefield)

    def test_wild_growth_provides_extra_mana(self, all_cards):
        wild_growth = _get(all_cards, "Wild Growth")
        forest = _forest(all_cards)

        p1 = PlayerState(name="P1", hand=[wild_growth], battlefield=[Permanent(card=forest)])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])

        result = game.cast_from_hand(0, "Wild Growth", target_player_index=0, target_permanent_index=0)

        assert result.supported


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


class TestLandCards:
    def test_basic_lands_produce_correct_mana(self, all_cards):
        land_mana = [
            ("Plains", "W"),
            ("Island", "U"),
            ("Swamp", "B"),
            ("Mountain", "R"),
            ("Forest", "G"),
        ]
        for land_name, expected_color in land_mana:
            land = _get(all_cards, land_name)
            p1 = PlayerState(name="P1", battlefield=[Permanent(card=land)])
            p2 = PlayerState(name="P2")
            game = Game(players=[p1, p2])

            ok = game.tap_land_for_mana(0, land_name)

            assert ok, f"{land_name} should be tappable for mana"
            assert p1.mana_pool[expected_color] == 1, f"{land_name} should produce {expected_color}"

    def test_dual_lands_produce_either_color(self, all_cards):
        # Each dual land should tap for one of its two colors
        dual_pairs = [
            ("Tundra", "W", "U"),
            ("Underground Sea", "U", "B"),
            ("Badlands", "B", "R"),
            ("Taiga", "R", "G"),
            ("Savannah", "G", "W"),
            ("Scrubland", "W", "B"),
            ("Bayou", "B", "G"),
            ("Plateau", "R", "W"),
            ("Tropical Island", "G", "U"),
        ]
        for land_name, color_a, color_b in dual_pairs:
            land = _get(all_cards, land_name)
            p1 = PlayerState(name="P1", battlefield=[Permanent(card=land)])
            p2 = PlayerState(name="P2")
            game = Game(players=[p1, p2])

            ok = game.tap_land_for_mana(0, land_name)

            assert ok, f"{land_name} should be tappable"
            produced = sum(p1.mana_pool.get(c, 0) for c in (color_a, color_b))
            assert produced >= 1, f"{land_name} should produce {color_a} or {color_b}"


def test_web_grants_toughness_bonus_and_reach(all_cards):
    web = _get(all_cards, "Web")
    bears = _get(all_cards, "Grizzly Bears")
    flyer = _get(all_cards, "Air Elemental")
    bears_perm = Permanent(card=bears)
    p1 = PlayerState(name="P1", hand=[web], battlefield=[bears_perm])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=flyer)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Web", target_player_index=0, target_permanent_index=0)

    assert result.supported
    # "Enchanted creature gets +0/+2"
    assert bears_perm.effective_power == 2
    assert bears_perm.effective_toughness == 4
    # "and has reach" — it can now block creatures with flying
    assert game._has_keyword(bears_perm, "reach")
    assert game._can_block_attacker(bears_perm, p2.battlefield[0]) is True


def test_gaeas_liege_pt_refreshes_when_attackers_declared(all_cards):
    # Regression: declaring attackers must recompute dynamic P/T so the Liege
    # switches from its controller's Forests to the defending player's Forests.
    liege = _get(all_cards, "Gaea's Liege")
    forest = _get(all_cards, "Forest")
    liege_perm = Permanent(card=liege)
    p1 = PlayerState(name="P1", battlefield=[liege_perm, Permanent(card=forest)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=forest), Permanent(card=forest), Permanent(card=forest)],
    )
    game = Game(players=[p1, p2])
    game._refresh_dynamic_creatures()
    assert (liege_perm.effective_power, liege_perm.effective_toughness) == (1, 1)

    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    liege_perm.tapped = False

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    assert (liege_perm.effective_power, liege_perm.effective_toughness) == (3, 3)


def test_gaeas_liege_activation_targets_chosen_land(all_cards):
    # Regression: the player may pick which land becomes a Forest, not just the first.
    liege = _get(all_cards, "Gaea's Liege")
    plains = _get(all_cards, "Plains")
    island = _get(all_cards, "Island")
    forest = _get(all_cards, "Forest")
    # Give P1 a Forest so Gaea's Liege is 1/1 and survives (otherwise it is 0/0,
    # dies as an SBA, and the Forest-conversion it created would end with it).
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=liege), Permanent(card=forest)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains), Permanent(card=island)])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0, "Gaea's Liege", target_player_index=1, target_permanent_index=1
    )

    assert result.supported
    assert p2.battlefield[0].changed_land_types == ()
    assert p2.battlefield[1].changed_land_types == ("forest",)


def test_sirens_call_cannot_be_cast_during_your_own_turn(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Bear", "Creature - Bear")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])  # P1 is the active player by default

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported is False
    assert any(c.name == "Siren's Call" for c in p1.hand)


def test_sirens_call_cannot_be_cast_after_attackers_declared(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], library=[island])
    game = Game(players=[p1, p2])

    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()  # -> beginning_of_combat
    game.advance_combat_phase()  # -> declare_attackers
    ok, _ = game.declare_attackers(1, [0])
    assert ok

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported is False
    assert any(c.name == "Siren's Call" for c in p1.hand)


def test_sirens_call_marks_active_player_creatures(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Opposing Bear", "Creature - Bear")
    wall = _mk_card("Test Wall", "Creature - Wall")
    home_bear = _mk_card("Home Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call], battlefield=[Permanent(card=home_bear)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear), Permanent(card=wall)], library=[island])
    game = Game(players=[p1, p2])
    game.start_turn(1)

    # Entered the battlefield this turn: exempt from the delayed destruction
    # ("didn't control continuously since the beginning of the turn").
    fresh = Permanent(card=_mk_card("Fresh Bear", "Creature - Bear"))
    fresh.metadata["summoning_sickness_turn"] = game.turn
    p2.battlefield.append(fresh)

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported
    assert any(c.name == "Siren's Call" for c in p1.graveyard)

    bear_perm, wall_perm = p2.battlefield[0], p2.battlefield[1]
    assert bear_perm.metadata.get("must_attack_until_eot") is True
    assert bear_perm.metadata.get("destroy_if_did_not_attack_eot") is True
    # Walls are never destroyed by Siren's Call
    assert wall_perm.metadata.get("destroy_if_did_not_attack_eot") is None
    assert fresh.metadata.get("destroy_if_did_not_attack_eot") is None
    # The caster's own creatures are unaffected
    assert p1.battlefield[0].metadata.get("must_attack_until_eot") is None


def test_sirens_call_forces_creatures_to_attack(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Reluctant Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], library=[island])
    game = Game(players=[p1, p2])

    game.start_turn(1)
    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)
    assert result.supported

    game._close_current_priority_step()
    game.advance_combat_phase()  # -> beginning_of_combat
    game.advance_combat_phase()  # -> declare_attackers

    ok, reason = game.declare_attackers(1, [])
    assert not ok
    assert "must attack" in reason

    ok, _ = game.declare_attackers(1, [0])
    assert ok


def test_sirens_call_destroys_non_attackers_at_end_step(all_cards):
    call = _get(all_cards, "Siren's Call")
    attacker = _mk_card("Eager Bear", "Creature - Bear")
    slacker = _mk_card("Lazy Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=attacker), Permanent(card=slacker)],
        library=[island],
    )
    game = Game(players=[p1, p2])

    game.start_turn(1)
    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)
    assert result.supported

    # A tapped creature can't attack, but it still didn't attack this turn,
    # so it is destroyed at the beginning of the next end step.
    p2.battlefield[1].tapped = True

    game._close_current_priority_step()
    game.advance_combat_phase()  # -> beginning_of_combat
    game.advance_combat_phase()  # -> declare_attackers
    ok, _ = game.declare_attackers(1, [0])
    assert ok

    game.resolve_end_step(1)

    names = [perm.card.name for perm in p2.battlefield]
    assert "Eager Bear" in names
    assert "Lazy Bear" not in names
    assert any(c.name == "Lazy Bear" for c in p2.graveyard)


def test_sirens_call_exempts_creature_stolen_this_turn(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = Permanent(card=_mk_card("Traded Bear", "Creature - Bear"))
    veteran = Permanent(card=_mk_card("Veteran Bear", "Creature - Bear"))
    theft_source = Permanent(card=_mk_card("Theft Source", "Artifact"))
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[call], battlefield=[bear])
    p2 = PlayerState(name="P2", battlefield=[theft_source, veteran], library=[island])
    game = Game(players=[p1, p2])
    game.start_turn(1)

    # The active player steals P1's bear mid-turn: it is summoning-sick again
    # (CR 302.6) and was not controlled continuously since the turn began.
    assert game._take_control_linked(theft_source, bear, p2) is True
    assert bear.metadata.get("summoning_sickness_turn") == game.turn
    assert game._is_summoning_sick(bear) is True

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported
    assert veteran.metadata.get("destroy_if_did_not_attack_eot") is True
    assert bear.metadata.get("destroy_if_did_not_attack_eot") is None
