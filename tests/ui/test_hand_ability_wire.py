"""An ability of a card in **hand** is reachable from the browser (CR 113.6j).

``Game.activate_from_hand`` shipped with M21's Waker of Waves — "{1}{U},
Discard this card: Look at the top two cards of your library…" — and had no
route through the web layer at all: no ``ActionKind``, no handler, no payload
entry, and no gesture on a hand card, whose only affordance is "cast". A
supported card no player can use is the Roots class, and Urza's Saga's cycling
(CR 702.29a) lands 34 more cards on it, so the route is built once here rather
than 34 times.

Pinned from both ends, the way ``test_special_action_wire.py`` is: the **offer**
the state serves, and the **body** the button builds — because the only reader
of that body is the browser, where a missing required field is a silent 422.

Waker of Waves rather than a cycling card because Urza's Saga is still
``measured``: no player can deck one of its cards, so ``CARD_BY_NAME`` does not
hold them. The route is the same route; ``tests/rules/test_cycling.py`` and
``tests/sets/test_usg_*.py`` drive the keyword itself.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from web.app import app, store
from web.runtime import CARD_BY_NAME

from ..helpers import resolve_stack

client = TestClient(app)

_APP_JS = Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"


def _session_holding_waker(*, mana: int = 0):
    """A session whose seat 0 holds Waker of Waves with priority."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 11,
    }).json()
    sid = created["session_id"]
    game = store.get(sid).game
    game.active_player_index = 0
    game.priority_player_index = 0
    waker = CARD_BY_NAME["waker of waves"]
    game.players[0].hand.append(waker)
    if mana:
        game.players[0].mana_pool["U"] = mana
    return sid, game, waker


def test_the_state_offers_the_hand_ability_with_the_line_as_printed():
    """One entry per (hand card, hand-activatable ability), carrying the index
    the action sends back and the line the button is labelled with."""
    sid, game, waker = _session_holding_waker(mana=3)

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    offers = [e for e in state["hand_abilities"] if e["name"] == "Waker of Waves"]

    assert len(offers) == 1
    entry = offers[0]
    assert entry["ability_index"] == 0
    assert game.players[0].hand[entry["hand_index"]] is waker
    assert entry["text"] == (
        "{1}{U}, Discard this card: Look at the top two cards of your library. "
        "Put one of them into your hand and the other into your graveyard."
    )
    # The button is named by the *price*, not the sentence — a control wide
    # enough for Waker of Waves' whole line would be wider than the phase rail,
    # and the half a player chooses by is what it costs. On a cycling card this
    # is the printed keyword line itself, "Cycling {2}".
    assert entry["cost_text"] == "{1}{U}, Discard this card"
    assert entry["payable"] is True


def test_a_board_that_cannot_pay_still_shows_the_offer_unpayable():
    """``payable`` is a flag rather than a filter: the affordance stays visible
    on a board that cannot afford it, which is what a cycling card in an opening
    hand should look like. The client disables the button."""
    sid, _game, _waker = _session_holding_waker()

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    entry = next(e for e in state["hand_abilities"] if e["name"] == "Waker of Waves")

    assert entry["payable"] is False


def test_the_posted_body_activates_the_ability_from_hand():
    """Exactly the body ``renderHandAbilities`` builds."""
    sid, game, waker = _session_holding_waker(mana=3)
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    entry = next(e for e in state["hand_abilities"] if e["name"] == "Waker of Waves")

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0,
        "action": "activate_hand",
        "card_name": entry["name"],
        "hand_index": entry["hand_index"],
        "ability_index": entry["ability_index"],
    })

    assert response.status_code == 200, response.text
    assert waker not in game.players[0].hand
    assert any(card is waker for card in game.players[0].graveyard)


def test_the_offer_disappears_once_the_card_has_left_the_hand():
    """The list is a read of the hand, so it cannot go stale into a button that
    activates a card the seat no longer holds."""
    sid, game, waker = _session_holding_waker(mana=3)
    game.players[0].hand.remove(waker)

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()

    assert [e for e in state["hand_abilities"] if e["name"] == "Waker of Waves"] == []


def test_a_hand_index_outside_the_hand_is_refused():
    """A stale index is an error rather than a silent fall back to a different
    card — the rule the permanent-id seam keeps, one zone over."""
    sid, game, _waker = _session_holding_waker(mana=3)

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate_hand",
        "hand_index": len(game.players[0].hand) + 5, "ability_index": 0,
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "card not in hand"


def test_an_ordinary_creature_in_hand_is_not_offered():
    """The offer is CR 113.6's zone read, not "every card with an ability": a
    Grizzly Bears in hand offers nothing, and so does a card whose ability
    functions only on the battlefield."""
    sid, game, _waker = _session_holding_waker(mana=3)
    game.players[0].hand.append(CARD_BY_NAME["prodigal sorcerer"])

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    names = {entry["name"] for entry in state["hand_abilities"]}

    assert "Prodigal Sorcerer" not in names


def test_the_button_body_carries_every_field_the_handler_reads():
    """Read out of ``app.js``, because the browser is the only other reader of
    that object literal and a missing field there is a silent 422."""
    source = _APP_JS.read_text(encoding="utf-8")
    match = re.search(
        r"function renderHandAbilities\(.*?\n\}\n", source, re.DOTALL
    )
    assert match, "app.js no longer defines renderHandAbilities"
    body = match.group(0)

    assert '"activate_hand"' in body
    assert "entry.cost_text" in body
    for field in ("seat,", "card_name:", "hand_index:", "ability_index:"):
        assert field in body, field


def test_the_look_top_prompt_renders_after_a_hand_activation():
    """A `NameError` in `web/prompts.py` that no path could reach until now.

    `_look_top_pick` read `owner.library` and nothing bound `owner`, so
    `GET /state` answered 500 the moment a `look_top_pick` prompt was owed to a
    browser viewer. Thirteen shipped cards produce that prompt (Orcish
    Librarian, Diabolic Vision, Browse, Lim-Dûl's Vault, Ashnod's Cylix,
    Ancestral Memories, Preferred Selection, Sealed Fate, Impulse, Ancestral
    Knowledge, See the Truth, Waker of Waves, Garruk's Harbinger) and every one
    of them crashed the poll — a missing name in a function body waits for its
    line to run, and this one was found by driving the app rather than by any
    test.

    Waker of Waves is the one that found it, because activating it from hand is
    the route this file adds and there was no way to reach it before.
    """
    sid, game, waker = _session_holding_waker(mana=3)
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    entry = next(e for e in state["hand_abilities"] if e["name"] == "Waker of Waves")

    assert client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate_hand", "card_name": entry["name"],
        "hand_index": entry["hand_index"], "ability_index": entry["ability_index"],
    }).status_code == 200
    # The ability is on the stack; the prompt is armed as it resolves.
    resolve_stack(game)

    response = client.get(f"/api/sessions/{sid}/state?seat=0")

    assert response.status_code == 200, response.text
    prompt = response.json()["look_top_pick"]
    assert prompt is not None
    assert prompt["top_count"] == 2
    assert len(prompt["cards"]) == 2
    assert prompt["pile_seat"] == 0
