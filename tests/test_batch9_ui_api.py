"""Web-API tests for the ninth batch of in-game card failures whose fix lives in
the web serialization layer (the canvas/UI reads these fields).

- Gloom: "The additional cost isn't reflected in the pay mana prompt ui." The
  viewer's own hand cards now carry the Gloom-taxed cost in ``mana_cost`` (and the
  unmodified printed value in ``printed_mana_cost``).
- Scavenging Ghoul: "I can use the card ability but I can't see the corpse counters
  on the card." The permanent JSON now exposes ``corpse_counters`` / ``counters``.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
import web.app as webapp
from web.app import app, store

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(Path(__file__).resolve().parent.parent / "lea_cards.json")}


def _session():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 5},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.current_turn = 0
    return sid, session, session.game


def _hand_card(state, seat, name):
    return next(c for c in state["players"][seat]["hand"] if c["name"] == name)


def test_gloom_taxes_white_spell_in_hand_payload():
    sid, session, game = _session()
    game.players[0].battlefield = [Permanent(card=_CARDS["Gloom"])]
    game.players[0].hand = [_CARDS["Holy Strength"]]  # white Aura, printed {W}
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    card = _hand_card(state, 0, "Holy Strength")
    assert card["printed_mana_cost"] == "{W}"
    assert card["mana_cost"] == "{3}{W}"        # +{3} from Gloom, shown in the pay prompt
    assert card["effective_mana_cost"] == "{3}{W}"
    assert card["cost_increased"] is True


def test_no_gloom_leaves_white_spell_cost_unchanged():
    sid, session, game = _session()
    game.players[0].battlefield = []
    game.players[0].hand = [_CARDS["Holy Strength"]]
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    card = _hand_card(state, 0, "Holy Strength")
    assert card["mana_cost"] == "{W}"
    assert card["cost_increased"] is False


def test_gloom_does_not_tax_nonwhite_spell():
    sid, session, game = _session()
    game.players[0].battlefield = [Permanent(card=_CARDS["Gloom"])]
    game.players[0].hand = [_CARDS["Lightning Bolt"]]  # red, printed {R}
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    card = _hand_card(state, 0, "Lightning Bolt")
    assert card["mana_cost"] == "{R}"
    assert card["cost_increased"] is False


def test_scavenging_ghoul_exposes_corpse_counters():
    sid, session, game = _session()
    ghoul = Permanent(card=_CARDS["Scavenging Ghoul"])
    ghoul.metadata["corpse_counters"] = 2
    game.players[0].battlefield = [ghoul]
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    perm = next(p for p in state["players"][0]["battlefield"] if p["name"] == "Scavenging Ghoul")
    assert perm["corpse_counters"] == 2
    assert perm["counters"] == {"corpse": 2}


def test_permanent_without_counters_reports_empty_map():
    sid, session, game = _session()
    game.players[0].battlefield = [Permanent(card=_CARDS["Grizzly Bears"])]
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    perm = next(p for p in state["players"][0]["battlefield"] if p["name"] == "Grizzly Bears")
    assert perm["corpse_counters"] == 0
    assert perm["counters"] == {}


def test_phantasmal_terrain_prompts_controller_for_land_type():
    # Phantasmal Terrain: the controller chooses the enchanted land's basic type.
    sid, session, game = _session()
    land = Permanent(card=_CARDS["Forest"])
    game.players[1].battlefield = [land]
    game.players[0].hand = [_CARDS["Phantasmal Terrain"]]
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Phantasmal Terrain", target_player_index=1, target_permanent_index=0)

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    info = state["land_type_choice"]
    assert info is not None
    assert info["card_name"] == "Phantasmal Terrain"
    assert info["options"] == ["plains", "island", "swamp", "mountain", "forest"]

    # The choice resolves through the action endpoint.
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "land_type_confirm", "land_type": "mountain"},
    )
    assert resp.status_code == 200
    assert land.metadata.get("land_type_override") == "mountain"
    assert game.pending_land_type_choice is None


def test_land_type_choice_hidden_from_opponent():
    sid, session, game = _session()
    land = Permanent(card=_CARDS["Forest"])
    game.players[1].battlefield = [land]
    game.players[0].hand = [_CARDS["Phantasmal Terrain"]]
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Phantasmal Terrain", target_player_index=1, target_permanent_index=0)
    # Seat 1 (the opponent) must not see the controller's pending choice.
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    assert state["land_type_choice"] is None


def test_kudzu_tap_prompts_controller_to_reattach():
    # Kudzu: tapping the enchanted land prompts the human controller to pick the
    # land to re-enchant (instead of auto-attaching to the first land).
    sid, session, game = _session()
    forest = Permanent(card=_CARDS["Forest"])
    island = Permanent(card=_CARDS["Island"])
    plains = Permanent(card=_CARDS["Plains"])
    kudzu = Permanent(card=_CARDS["Kudzu"])
    kudzu.metadata["attached_to"] = forest
    forest.metadata["attached_aura"] = kudzu
    game.players[0].battlefield = [forest, island, plains, kudzu]

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "tap", "permanent_index": 0, "mana_color": "G"},
    )
    assert resp.status_code == 200

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    info = state["kudzu_reattach"]
    assert info is not None
    names = {land["name"] for land in info["lands"]}
    assert names == {"Island", "Plains"}

    # Re-enchant the Plains (its current battlefield index after Forest is removed).
    plains_index = next(land["index"] for land in info["lands"] if land["name"] == "Plains")
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "kudzu_reattach_confirm", "target_permanent_index": plains_index},
    )
    assert resp.status_code == 200
    assert kudzu.metadata.get("attached_to") is plains
    assert game.pending_kudzu_reattach is None


def _tapped(name):
    p = Permanent(card=_CARDS[name])
    p.tapped = True
    return p


def test_smoke_untap_selection_untaps_only_chosen_creature():
    # Smoke: the controller picks which single creature untaps during their untap
    # step; the rest stay tapped. Driven through the untap_select/untap_confirm API.
    sid, session, game = _session()
    smoke = Permanent(card=_CARDS["Smoke"])
    c1, c2, c3 = _tapped("Grizzly Bears"), _tapped("Hill Giant"), _tapped("Gray Ogre")
    game.players[0].battlefield = [smoke, c1, c2, c3]
    game._set_phase_and_step("beginning", "untap")
    # Arm the deferred untap selection as _begin_turn would for a human.
    options = game.get_untap_land_selection_options(0)
    assert options is not None and options["max_count"] == 1
    session.untap_candidate_indices = [int(i) for i in options["candidate_indices"]]
    session.untap_selected_indices = []
    session.untap_required_lands = int(options["max_count"])

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    info = state["untap_land_selection"]
    assert info is not None
    assert set(info["candidate_indices"]) == {1, 2, 3}

    # Select Hill Giant (index 2) and confirm.
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "untap_select", "permanent_index": 2},
    )
    assert resp.status_code == 200
    resp = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "untap_confirm"})
    assert resp.status_code == 200

    assert c2.tapped is False           # the chosen creature untapped
    assert c1.tapped is True and c3.tapped is True  # the others stayed tapped


def test_channel_active_surfaces_synthetic_emblem():
    # Channel: while active, the controller sees a clickable "pay life for {C}"
    # emblem. It carries kind="channel" so the client routes to channel_mana.
    sid, session, game = _session()
    game.players[0].channel_active_until_eot = True
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    emblems = state["players"][0]["emblems"]
    channel = next((e for e in emblems if e["kind"] == "channel"), None)
    assert channel is not None
    assert channel["name"] == "Channel"
    assert "{C}" in channel["label"]


def test_no_channel_emblem_when_inactive():
    sid, session, game = _session()
    game.players[0].channel_active_until_eot = False
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    emblems = state["players"][0]["emblems"]
    assert not any(e["kind"] == "channel" for e in emblems)


def test_illusionary_mask_prompts_eligible_hand_creatures():
    # Illusionary Mask: the controller is offered hand creatures within X to cast
    # face down. Force of Nature (cmc 8) is filtered out at X=3.
    sid, session, game = _session()
    mask = Permanent(card=_CARDS["Illusionary Mask"])
    game.players[0].battlefield = [mask]
    game.players[0].hand = [_CARDS["Grizzly Bears"], _CARDS["Force of Nature"]]
    game.enforce_mana_costs = False
    game.activate_permanent_ability(0, "Illusionary Mask", permanent_index=0, x_value=3)

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    info = state["face_down_cast"]
    assert info is not None
    assert info["max_cmc"] == 3
    names = {c["name"] for c in info["choices"]}
    assert names == {"Grizzly Bears"}  # Force of Nature (cmc 8) excluded

    hand_index = next(c["hand_index"] for c in info["choices"] if c["name"] == "Grizzly Bears")
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "face_down_cast_confirm", "hand_index": hand_index},
    )
    assert resp.status_code == 200
    fd = [p for p in game.players[0].battlefield if p.metadata.get("face_down")]
    assert len(fd) == 1
    assert game.pending_face_down_cast is None


def _time_vault_session():
    sid, session, game = _session()
    vault = Permanent(card=_CARDS["Time Vault"])
    vault.tapped = True
    game.players[0].battlefield = [vault]
    webapp._begin_turn(session, 0, defer_untap_selection=True)
    return sid, session, game, vault


def test_time_vault_prompt_surfaces_and_skip_advances_turn():
    sid, session, game, vault = _time_vault_session()
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["time_vault"] == {"permanents": ["Time Vault"]}

    turn_before = game.turn
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "time_vault_skip", "card_name": "Time Vault"},
    )
    assert resp.status_code == 200
    assert vault.tapped is False             # untapped
    assert game.turn > turn_before           # the turn was skipped (advanced)
    assert game.skip_turn_counts.get(0, 0) == 0  # no double-skip
    assert session.time_vault_pending == []


def test_time_vault_decline_keeps_turn_and_leaves_it_tapped():
    sid, session, game, vault = _time_vault_session()
    resp = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "time_vault_decline"})
    assert resp.status_code == 200
    assert vault.tapped is True               # not untapped
    assert session.time_vault_pending == []
    assert session.current_turn == 0          # still this player's turn


def test_time_vault_prompt_hidden_from_opponent():
    sid, session, game, vault = _time_vault_session()
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    assert state["time_vault"] is None
