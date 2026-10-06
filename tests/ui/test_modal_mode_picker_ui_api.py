"""The browser's side of a modal spell: one mode, one picker, the engine's own.

``web/serialization`` used to derive each mode's target kind from a table of
its own — four instruction kinds and a fall-through that answered "player" —
and enumerate that kind's targets through ``enumerate_targets_for_kind``, a
path that never ran the cast gate's per-kind arm. Two derivations of one
question: 33 of the pool's 47 object-targeting modes were sent the wrong
picker (Chaos Charm's "deals 1 damage to target creature" asked for a
*player*), and a mode that targets nothing asked for one too.

A mode's payload is now ``Game.cast_target_spec(mode_index=)`` — the spec the
engine's gate derives for that mode, with the list the gate accepts — and
three things are held here:

* what a mode is sent is what a cast of that mode is accepted for;
* the castable highlight is "some mode has a legal announcement", where it
  read mode 0 (so a card whose first mode had nothing to target never glowed,
  and Reign of Chaos — two modes, both of two roles — never glowed at all);
* a cast over the wire naming an illegal target for its mode is refused.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _mk_card
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _w2g2_session(hand, *, mine=(), theirs=()):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 4251,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].battlefield = [Permanent(card=card) for card in mine]
    game.players[1].battlefield = [Permanent(card=card) for card in theirs]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.players[0].hand = [_CARDS[name] for name in hand]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _w2g2_hand_card(sid, name):
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    return state, next(c for c in state["players"][0]["hand"] if c["name"] == name)


def _bear(name="Bear"):
    return _mk_card(name=name, type_line="Creature - Bear", colors=("G",), power=2, toughness=2)


def test_w2g2_a_mode_is_sent_the_picker_its_own_sentence_prints():
    """Chaos Charm: "Destroy target Wall" / "deals 1 damage to target
    creature" / "Target creature gains haste". The second and third were sent
    as ``player``."""
    wall = _mk_card(name="Wall", type_line="Creature - Wall", power=0, toughness=4)
    sid, game = _w2g2_session(
        ["Chaos Charm"], mine=[_CARDS["Forest"]], theirs=[_bear(), wall, _CARDS["Island"]],
    )

    _state, card = _w2g2_hand_card(sid, "Chaos Charm")
    modes = card["modes"]

    assert [mode["target_kind"] for mode in modes] == ["creature", "creature", "creature"]
    names = [
        sorted(target["name"] for target in mode["valid_targets"]) for mode in modes
    ]
    assert names[0] == ["Wall"], "the Wall-only mode offered more than the Wall"
    assert names[1] == ["Bear", "Wall"] and names[2] == ["Bear", "Wall"]
    for index, mode in enumerate(modes):
        assert mode["target_spec"]["kind"] == mode["target_kind"]
        assert mode["target_spec"]["valid_targets"] == mode["valid_targets"]
        assert mode["announceable"] is True
        # what the browser is offered is what the engine's gate enumerates
        assert mode["valid_targets"] == game.cast_target_spec(
            0, _CARDS["Chaos Charm"], mode_index=index
        )["valid_targets"]


def test_w2g2_a_mode_that_targets_nothing_asks_for_nothing():
    """Hearth Charm's "Attacking creatures get +1/+0 until end of turn" fell
    through the old table to "player" and opened the life-pill prompt."""
    sid, _game = _w2g2_session(["Hearth Charm"], theirs=[_bear()])

    _state, card = _w2g2_hand_card(sid, "Hearth Charm")

    assert card["modes"][1]["target_kind"] == "none"
    assert card["modes"][1]["valid_targets"] == []
    assert card["modes"][1]["announceable"] is True


def test_w2g2_a_mode_with_nothing_to_name_is_marked_and_the_card_still_glows():
    """Destructive Tampering: "Destroy target artifact" / "Creatures without
    flying can't block this turn". With no artifact in play the first mode
    cannot be announced and the second can — the card is castable, and it did
    not glow, because the highlight read mode 0."""
    sid, _game = _w2g2_session(["Destructive Tampering"], theirs=[_bear()])

    state, card = _w2g2_hand_card(sid, "Destructive Tampering")

    assert [mode["announceable"] for mode in card["modes"]] == [False, True]
    assert state["players"][0]["playable_hand_indices"] == [0]


def test_w2g2_a_modal_card_with_no_announceable_mode_does_not_glow():
    sid, game = _w2g2_session(["Chaos Charm"], theirs=[_CARDS["Island"]])

    state, card = _w2g2_hand_card(sid, "Chaos Charm")

    assert [mode["announceable"] for mode in card["modes"]] == [False, False, False]
    assert state["players"][0]["playable_hand_indices"] == []
    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Chaos Charm", "mode_index": 1},
    )
    assert refused.status_code >= 400, refused.json()
    assert [c.name for c in game.players[0].hand] == ["Chaos Charm"]


def test_w2g2_reign_of_chaos_glows_when_one_of_its_modes_has_a_chain():
    """Both modes are two roles, so the card-level spec answered "modal" with
    no targets and the roles arm of the highlight said no on every board."""
    merfolk = _mk_card(name="Merfolk", type_line="Creature - Merfolk", colors=("U",))
    sid, _game = _w2g2_session(
        ["Reign of Chaos"], theirs=[_CARDS["Island"], merfolk],
    )

    state, card = _w2g2_hand_card(sid, "Reign of Chaos")

    assert [mode["target_kind"] for mode in card["modes"]] == ["roles", "roles"]
    assert [mode["announceable"] for mode in card["modes"]] == [False, True]
    assert state["players"][0]["playable_hand_indices"] == [0]
    walk = card["modes"][1]["target_spec"]["valid_targets"]
    assert [entry["name"] for entry in walk] == ["Island"]
    assert [entry["name"] for entry in walk[0]["next"]] == ["Merfolk"]


def test_w2g2_a_cast_over_the_wire_is_held_to_its_mode():
    wall = _mk_card(name="Wall", type_line="Creature - Wall", power=0, toughness=4)
    sid, game = _w2g2_session(["Chaos Charm"], theirs=[_bear(), wall])
    bear, wall_perm = list(game.controlled_by(1))

    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Chaos Charm", "mode_index": 0,
            "target_seat": 1, "target_permanent_id": bear.permanent_id,
        },
    )
    assert refused.status_code >= 400, "a Bear was accepted for 'destroy target Wall'"
    assert game.is_on_battlefield(bear)
    assert [c.name for c in game.players[0].hand] == ["Chaos Charm"]

    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Chaos Charm", "mode_index": 0,
            "target_seat": 1, "target_permanent_id": wall_perm.permanent_id,
        },
    )
    assert cast.status_code == 200, cast.json()
    assert game.players[0].hand == []


# ---------------------------------------------------------------------------
# The client half, read as source (app.js is DOM-coupled; see
# tests/ui/test_cast_target_kinds.py for why it is read rather than run)
# ---------------------------------------------------------------------------


def test_w2g2_the_client_runs_a_mode_on_the_modes_own_spec():
    """``dispatchModalCast`` lays the chosen mode's ``target_spec`` over the
    card, so every prompt that asks ``targetSpecOf(card)`` — the roles walk,
    the several-target count, the graveyard narrowing — reads the mode's.
    Without it Hull Breach's two-target mode was offered one permanent."""
    from tests.helpers import app_js_function_body

    body = app_js_function_body("dispatchModalCast")
    assert "target_spec: modeSpec" in body
    assert "startCastPromptForKind" in body
    for caller in ("chooseModalMode", "promptNextModeTarget"):
        assert "mode.target_spec" in app_js_function_body(caller), caller


def test_w2g2_the_client_declines_a_mode_the_server_marked_unannounceable():
    from tests.helpers import app_js_function_body

    assert "mode.announceable === false" in app_js_function_body("chooseModalMode")
