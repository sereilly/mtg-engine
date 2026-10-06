"""Every shape of the "as this enters, choose …" prompt can be answered in the
browser.

Found by driving Runed Halo in the running app to look at what it had named.
The server arms one prompt kind (``enter_choice``) in nine shapes, renders all
of them (``web/prompts._enter_choice``) and answers all of them
(``web/action_prompt_answers``) — and the client's reader,
``getEnterChoiceInfo``, returned null for every shape that names no opponent.
So for a human seat a resolved Ward, Runed Halo, Conspiracy or Shimmer left the
panel saying "Main Phase" while the server refused every other action with
"choose an opponent (and color) for the entering permanent before other
actions": the question could not be seen, so it could not be answered, so the
game could not go on. Thirty-one permanents in the pool arm a shape the browser
had no control for; Booby Trap's was shown and could not be sent (the pill
click carried no card name).

No engine instrument can see this — the engine, the renderer and the route are
all right, and every engine-side test of these cards runs a headless seat,
which takes the default stamped at arm and never opens a prompt.

Three things are held here:

* **derived** — every entry-choosing permanent in the pool is entered under an
  interactive seat, its prompt rendered by the server, and every question that
  payload asks (``needs_*``, or a list of opponents) must be one the client's
  reader, its panel and its answer all read. A tenth shape the client has not
  been taught fails here by name;
* **the wire** — the action each shape's control sends is accepted and
  recorded, including the colour that travels with a creature type;
* what was rendered in a real browser is in the W2G3 report, not here.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_cards, load_catalog, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import app_js_function_body
from web.app import app, store
from web.prompts import PromptContext, _enter_choice

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)

_ENTRY_CHOICE_LINE = re.compile(r"^as .*\benters\b.*\bchoose\b", re.I)


def _w2g3_choosers() -> list[str]:
    return sorted(
        card.name for card in compilation_units(_POOL.values())
        if card.face_of is None
        and card.primary_type not in ("instant", "sorcery")
        and compile_card_oracle(card).supported
        and any(
            _ENTRY_CHOICE_LINE.search(line)
            for line in (card.oracle_text or "").splitlines()
        )
    )


def _w2g3_rendered_prompts(name: str) -> list[dict]:
    """The ``enter_choice`` payloads *name* raises for an interactive seat — as
    the server renders them, never as written here. Three seats, so a lone
    "choose an opponent" is a real question."""
    entering = Permanent(card=_POOL[name])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[entering]),
        PlayerState(name="P2", battlefield=[
            Permanent(card=_POOL["Grizzly Bears"]), Permanent(card=_POOL["Forest"]),
        ]),
        PlayerState(name="P3"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1, 2}
    game._initialize_permanent_state(entering, 0, 1)
    rendered = []
    for seat in range(3):
        queued = [
            choice for choice in game.pending_choices
            if choice.kind == "enter_choice" and choice.player_index == seat
        ]
        if queued:
            ctx = PromptContext(
                game=game, viewer_seat=seat,
                serialize_card=lambda card: {"name": card.name},
                seat_type=lambda _seat: "human",
            )
            rendered.append(_enter_choice(ctx, queued))
    return rendered


def _w2g3_questions(payload: dict) -> set[str]:
    """What one rendered prompt asks: its truthy ``needs_*`` flags, plus
    ``opponents`` when it lists any."""
    asked = {key for key, value in payload.items() if key.startswith("needs_") and value}
    if payload.get("opponents"):
        asked.add("opponents")
    return asked


def test_w2g3_the_client_reads_every_question_the_server_asks():
    reader = app_js_function_body("getEnterChoiceInfo") + app_js_function_body(
        "enterChoiceNamesASeat"
    )
    panel = app_js_function_body("applyEnterChoicePrompt") + app_js_function_body(
        "enterChoiceNamesASeat"
    )
    answer = app_js_function_body("enterChoicePayload")
    examined = 0
    seen: set[str] = set()
    unread: list[str] = []
    for name in _w2g3_choosers():
        for payload in _w2g3_rendered_prompts(name):
            examined += 1
            for question in _w2g3_questions(payload):
                seen.add(question)
                for where, body in (("reader", reader), ("panel", panel), ("answer", answer)):
                    if question == "opponents" and where == "answer":
                        continue  # the seat arrives as the pill that was clicked
                    if f"info.{question}" not in body:
                        unread.append(f"{name}: {question} is not read by the client's {where}")
    assert not unread, "\n".join(sorted(set(unread)))
    # Measured: 44 prompts over the 45 entry choosers in the pool, asking six things.
    assert examined >= 40, examined
    assert seen == {
        "opponents", "needs_color", "needs_card_name", "needs_creature_type",
        "needs_land_type", "needs_land_types",
    }, seen


def test_w2g3_the_panel_offers_a_control_of_its_own_when_no_opponent_is_named():
    """An opponent is chosen on the board, by its pill; a prompt naming nobody
    has no pill to click and needs a button, and the fields a player types in
    are not rebuilt under their hands on every poll."""
    panel = app_js_function_body("applyEnterChoicePrompt")
    assert "data-enter-confirm" in panel and "enterChoicePayload(info)" in panel
    assert "steps.dataset.enterChoiceKey === draft.key" in panel
    # The pill click sends what the panel holds (Booby Trap's card name).
    targeting = app_js_function_body("getPromptBoardTargeting")
    assert "enterChoicePayload(enterChoiceInfo, targetSeat)" in targeting


# --- the wire ----------------------------------------------------------------


def _w2g3_session(hand):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 4246,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.players[0].battlefield = [Permanent(card=_CARDS["Grizzly Bears"])]
    game.players[1].battlefield = [
        Permanent(card=_CARDS["Hill Giant"]), Permanent(card=_CARDS["Mountain"]),
    ]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    game.players[0].hand = [_CARDS[name] for name in hand]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


#: ``card -> (the fields the client's control sends for its shape, what the
#: permanent then reports)``. The fields are ``enterChoicePayload``'s, shape by
#: shape; ``target_seat: 0`` is the chooser's own seat, which the route asks
#: for on a shape that names no opponent.
_SENT = {
    "Psychic Allergy": (
        {"mana_color": "B", "target_seat": 0},
        [{"label": "Chosen color", "value": "black"}],
    ),
    "Mangara's Equity": (
        {"mana_color": "R", "target_seat": 0},
        [{"label": "Chosen color", "value": "red"}],
    ),
    "Runed Halo": (
        {"card_name": "Hill Giant", "target_seat": 0},
        [{"label": "Named card", "value": "Hill Giant"}],
    ),
    "Conspiracy": (
        {"creature_type": "goblin"},
        [{"label": "Chosen creature type", "value": "goblin"}],
    ),
    "Volrath's Laboratory": (
        {"creature_type": "goblin", "mana_color": "U"},
        [
            {"label": "Chosen color", "value": "blue"},
            {"label": "Chosen creature type", "value": "goblin"},
        ],
    ),
    "Shimmer": (
        {"chosen_land_type": "desert"},
        [{"label": "Chosen land type", "value": "desert"}],
    ),
    "Roots of Life": (
        {"chosen_land_type": "swamp"},
        [{"label": "Chosen land type", "value": "swamp"}],
    ),
    "Illusionary Terrain": (
        {"old_color": "G", "mana_color": "U"},
        [{"label": "Chosen land types (first, second)", "value": "forest, island"}],
    ),
    "Booby Trap": (
        {"target_seat": 1, "card_name": "Mountain Goat"},
        [
            {"label": "Chosen player", "value": "Joiner"},
            {"label": "Named card", "value": "Mountain Goat"},
        ],
    ),
}


@pytest.mark.parametrize("name", sorted(_SENT))
def test_w2g3_what_the_control_sends_is_accepted_and_recorded(name):
    fields, expected = _SENT[name]
    sid, game = _w2g3_session([name])
    assert game.cast_from_hand(0, name).supported
    game.resolve_top_of_stack()
    assert game.pending_choice_of("enter_choice", 0) is not None, name

    # While it is owed nothing else may be done — which is why a prompt the
    # client cannot show is a game that cannot go on.
    blocked = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"},
    )
    assert blocked.status_code == 400

    answered = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "enter_choice_confirm", **fields},
    )
    assert answered.status_code == 200, answered.text
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    permanent = next(
        card for card in state["players"][0]["battlefield"] if card["name"] == name
    )
    shown = [
        {**entry, "value": entry["value"] if entry["label"] != "Chosen player"
         else entry["value"]}
        for entry in permanent["entry_choices"]
    ]
    wanted = [
        {**entry, "value": game.players[1].name}
        if entry["label"] == "Chosen player" else entry
        for entry in expected
    ]
    assert shown == wanted
    assert state.get("enter_choice") is None
    assert not state["stack"]


def test_w2g3_both_seats_of_a_two_chooser_prompt_are_asked_and_answered():
    """Null Chamber: "you and an opponent each choose a card name". Two
    prompts of the one kind, each visible to its own seat."""
    sid, game = _w2g3_session(["Null Chamber"])
    assert game.cast_from_hand(0, "Null Chamber").supported
    game.resolve_top_of_stack()
    for seat, named in ((0, "Hill Giant"), (1, "Grizzly Bears")):
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()
        assert state["enter_choice"]["needs_card_name"], seat
        assert not state["enter_choice"]["opponents"]
        answered = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": seat, "action": "enter_choice_confirm",
                  "card_name": named, "target_seat": seat},
        )
        assert answered.status_code == 200, answered.text
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    chamber = next(
        card for card in state["players"][0]["battlefield"] if card["name"] == "Null Chamber"
    )
    assert chamber["entry_choices"] == [
        {"label": "Named cards", "value": "Hill Giant, Grizzly Bears"},
    ]
