"""A permanent on its way onto the battlefield, on the wire (CR 614.12a).

The engine now makes an "as it enters" choice before the permanent enters: at
a table that holds for answers — every web table — a person's entry prompt
keeps the permanent in no zone until the answer (``engine/entry_awaiting.py``).
Two things the web layer has to do with that:

* **show it arriving**. It is sent beside its controller's board marked
  ``entering`` (``serialization._serialize_arriving``) — the shape the client
  already draws as the printed card ghosted under an ENTERING ribbon — to both
  seats, with nothing chosen on it and nothing else on the board changed;
* **render the prompt without a battlefield position** (part 6 of the
  Known-gaps entry). "As this creature enters, an opponent chooses a creature
  type" names whose creature it is from the permanent's controller, which a
  permanent on no battlefield answers through its entry record.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store
from web.prompt_values import _enter_choice
from web.prompts import PromptContext
from web.runtime import CARD_BY_NAME
from web.state_view import build_state

client = TestClient(app)
_C = {card.name: card for card in load_catalog()}


def _card(name: str):
    return CARD_BY_NAME[name.casefold()]


def _table(hand: list[str], board: list[str]):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "Alice", "guest_name": "Bob",
              "host_colors": 2, "guest_colors": 2, "seed": 7351},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Bob"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    for player in game.players:
        player.hand[:] = []
    game.remove_all_from_battlefield(list(game.all_permanents()))
    game.stack.clear()
    for name in board:
        permanent = Permanent(card=_card(name))
        permanent.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield.append(permanent)
    game._sync_control()
    game._recompute_continuous_effects()
    game.players[0].hand[:] = [_card(name) for name in hand]
    game.active_player_index = session.current_turn = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", "precombat_main"
    game.start_priority_window(0)
    return sid, session, game


def _post(sid: str, **body) -> None:
    response = client.post(f"/api/sessions/{sid}/action", json=body)
    assert response.status_code == 200, response.text


def test_a_sliver_on_its_way_is_sent_arriving_and_the_board_is_unchanged():
    sid, session, game = _table(["Ward Sliver"], ["Plated Sliver"])
    _post(sid, seat=0, action="cast", card_name="Ward Sliver")
    _post(sid, seat=0, action="pass_priority")
    _post(sid, seat=1, action="pass_priority")
    assert game.waiting_prompt() is not None and game.waiting_prompt().kind == "enter_choice"
    ward = game.waiting_prompt().data["permanent"]
    assert not game.is_on_battlefield(ward)

    for viewer in (0, 1):
        state = build_state(session, viewer)
        board = {p["name"]: p for p in state["players"][0]["battlefield"]}
        assert board["Ward Sliver"].get("entering") is True, viewer
        assert "entering" not in board["Plated Sliver"]
        assert not board["Ward Sliver"].get("entry_choices")
        assert not any("protection" in str(k).lower() for k in board["Plated Sliver"].get("keywords", []))
        assert [item["label"] for item in state["stack"]] == ["Ward Sliver"], state["stack"]

    _post(sid, seat=0, action="enter_choice_confirm", mana_color="G", target_seat=0)
    state = build_state(session, 1)
    board = {p["name"]: p for p in state["players"][0]["battlefield"]}
    assert "entering" not in board["Ward Sliver"]
    assert board["Ward Sliver"]["entry_choices"] == [{"label": "Chosen color", "value": "green"}]
    assert any("protection" in str(k).lower() for k in board["Plated Sliver"].get("keywords", []))
    assert not state["stack"]


def test_an_opponents_prompt_names_whose_creature_is_on_its_way():
    """Callous Oppressor at three seats: the controller names the opponent who
    chooses, and that opponent's prompt says whose creature it is — read from
    a permanent that is on no battlefield."""
    game = Game(players=[
        PlayerState(name="P1", hand=[_C["Callous Oppressor"]], library=[_C["Forest"]] * 5),
        PlayerState(name="P2", library=[_C["Forest"]] * 5,
                    battlefield=[Permanent(card=_C["Grizzly Bears"])]),
        PlayerState(name="P3", library=[_C["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1, 2}
    game._sync_control()
    assert game.queue_from_hand(0, "Callous Oppressor").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_enter_choice(0, opponent_index=1)

    asked = game.pending_choice_of("enter_choice", 1)
    assert asked is not None
    oppressor = asked.data["permanent"]
    assert not game.is_on_battlefield(oppressor)
    ctx = PromptContext(
        game=game, viewer_seat=1,
        serialize_card=lambda card: {"name": card.name},
        seat_type=lambda _seat: "human",
    )
    rendered = _enter_choice(ctx, [asked])
    assert rendered["controller_seat"] == 0 and rendered["controller_name"] == "P1"
    assert rendered["needs_creature_type"] is True
