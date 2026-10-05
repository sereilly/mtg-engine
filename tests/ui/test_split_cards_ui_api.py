"""Split cards over the wire (CR 709) — what the client is told, and what it
may send.

The engine half is ``tests/rules/test_split_cards.py``. What is pinned here is
the part with no other instrument: that a hand card with two halves *says so*
in the polled state, with each half shaped exactly like the single-face hand
card the client's cast flow already knows how to cast; that the half is named
by sending its own name as ``card_name`` (the wire has no "which half" field
and needs none — CR 709.4a gives the card both names); and that the timing
gates in the route judge the **half** (CR 709.3a), which is the one place the
web layer rather than the engine decides something about a cast.

Invasion is ``measured``, so no session can be dealt one of its split cards:
they are placed into a hand directly — the arrangement every suite over a
measured card makes — and the two catalog-keyed lookups are exercised with the
maps the running app builds at import, extended for the test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import load_catalog, manifest_set_path
from engine.faces import face_cards, name_aliases
from engine.models import CardDefinition, CardFace, Permanent
from web import runtime
from web.app import app, store
from web.deck_builder import build_deck_from_entries

from tests.helpers import app_js_function_body

client = TestClient(app)

APP_JS = (Path(__file__).resolve().parents[2] / "web" / "static" / "app.js").read_text(
    encoding="utf-8"
)

_SHIPPED = {card.name: card for card in load_catalog()}
_INV = {
    card.name: card
    for card in load_cards(manifest_set_path("INV", include_measured=True))
}
ASSAULT_BATTERY = _INV["Assault // Battery"]

#: An instant on one half and a sorcery on the other — no Invasion card pairs
#: them, and the route's timing gate has to be shown to read the half's type.
QUICK_SLOW = CardDefinition(
    name="Quick // Slow",
    mana_cost="{R} // {G}",
    cmc=2.0,
    type_line="Instant // Sorcery",
    oracle_text="",
    colors=("G", "R"),
    color_identity=("G", "R"),
    keywords=(),
    produced_mana=(),
    raw={},
    layout="split",
    faces=(
        CardFace("Quick", "{R}", "Instant", "Quick deals 1 damage to any target."),
        CardFace("Slow", "{G}", "Sorcery", "You gain 3 life."),
    ),
)


def _session(*, turn: int = 0):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 709,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = True
    for player in game.players:
        player.battlefield = []
        player.hand = []
    session.current_turn = turn
    game.active_player_index = turn
    return sid, session, game


def _state(sid: str, seat: int = 0) -> dict:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _cast(sid: str, seat: int, name: str, **fields):
    return client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": seat, "action": "cast", "card_name": name, **fields},
    )


def _mountains(game, seat: int, count: int) -> None:
    for _ in range(count):
        game._put_permanent_onto_battlefield(
            seat, Permanent(card=_SHIPPED["Mountain"]), None
        )


# ---------------------------------------------------------------------------
# The hand payload
# ---------------------------------------------------------------------------


def test_a_split_card_in_hand_lists_each_half_as_a_castable_card():
    """One hand entry (CR 709.2) carrying two ``faces``, each with the full
    shape a single-face hand card has — so the client's cast flow runs with the
    chosen half in the card's place and learns nothing else."""
    sid, _session_obj, game = _session()
    game.players[0].hand.append(ASSAULT_BATTERY)
    _mountains(game, 0, 1)

    hand = _state(sid)["players"][0]["hand"]
    assert len(hand) == 1
    card = hand[0]
    assert card["name"] == "Assault // Battery" and card["layout"] == "split"
    # The whole card: both colours, both texts, and no spell of its own.
    assert sorted(card["colors"]) == ["G", "R"]
    assert "Assault deals 2 damage" in card["oracle_text"]
    assert "Elephant" in card["oracle_text"]
    assert card["target_spec"]["kind"] == "faces"

    assault, battery = card["faces"]
    assert (assault["name"], assault["mana_cost"], assault["type"], assault["colors"]) == (
        "Assault", "{R}", "Sorcery", ["R"],
    )
    assert assault["oracle_text"] == "Assault deals 2 damage to any target."
    assert assault["target_spec"]["kind"] == "any"
    assert assault["target_spec"]["valid_targets"], "a legal target is enumerated"
    assert (battery["name"], battery["mana_cost"], battery["colors"]) == (
        "Battery", "{3}{G}", ["G"],
    )
    assert battery["target_spec"]["kind"] == "none"
    assert "face_of" not in card and assault["face_of"] == "Assault // Battery"


def test_each_half_says_whether_it_can_be_cast_right_now():
    """CR 709.3a: one Mountain casts Assault ({R}) and cannot cast Battery
    ({3}{G}). The card is highlighted because *a* half is castable; the prompt
    that offers the halves is told which."""
    sid, _session_obj, game = _session()
    game.players[0].hand.append(ASSAULT_BATTERY)
    _mountains(game, 0, 1)

    me = _state(sid)["players"][0]
    assert me["playable_hand_indices"] == [0]
    assert {face["name"]: face["castable_now"] for face in me["hand"][0]["faces"]} == {
        "Assault": True, "Battery": False,
    }

    game.players[0].battlefield = []
    me = _state(sid)["players"][0]
    assert me["playable_hand_indices"] == []
    assert [face["castable_now"] for face in me["hand"][0]["faces"]] == [False, False]


def test_an_opponent_sees_no_faces_in_a_hidden_hand():
    sid, _session_obj, game = _session()
    game.players[0].hand.append(ASSAULT_BATTERY)
    assert _state(sid, seat=1)["players"][0]["hand"] == ["<hidden>"]


# ---------------------------------------------------------------------------
# The cast action
# ---------------------------------------------------------------------------


def test_the_cast_action_names_the_half_and_the_stack_shows_the_half():
    sid, _session_obj, game = _session()
    me, them = game.players
    me.hand.append(ASSAULT_BATTERY)
    me.mana_pool["R"] = 1

    whole = _cast(sid, 0, "Assault // Battery", target_seat=1)
    assert whole.status_code == 400
    assert "Assault or Battery" in whole.json()["detail"]
    assert "709.3" in whole.json()["detail"]
    assert me.hand == [ASSAULT_BATTERY] and me.mana_pool["R"] == 1

    cast = _cast(sid, 0, "Assault", target_seat=1)
    assert cast.status_code == 200, cast.text
    state = _state(sid)
    (item,) = state["stack"]
    assert item["label"] == "Assault"
    assert item["card"]["name"] == "Assault" and item["card"]["colors"] == ["R"]
    assert item["card"]["face_of"] == "Assault // Battery"
    assert item["card"]["type"] == "Sorcery" and "faces" not in item["card"]
    assert state["players"][0]["hand"] == []

    game.resolve_stack()
    assert them.life == 18
    graveyard = _state(sid)["players"][0]["graveyard"]
    assert [card["name"] for card in graveyard] == ["Assault // Battery"]
    assert [face["name"] for face in graveyard[0]["faces"]] == ["Assault", "Battery"]


@pytest.mark.parametrize(
    "half, expected_status",
    [("Quick", 200), ("Slow", 400)],
)
def test_the_routes_timing_gate_reads_the_halfs_type(half, expected_status):
    """An instant half is castable on the opponent's turn and its sorcery
    sibling is not — the gate in ``web/actions.py`` judges the spell being
    cast (CR 709.3a), where the card it is printed on is both types at once."""
    sid, session, game = _session(turn=1)
    game.players[0].hand.append(QUICK_SLOW)
    game.players[0].mana_pool["R"] = 1
    game.players[0].mana_pool["G"] = 1
    game.start_priority_window(0)

    response = _cast(sid, 0, half, target_seat=1)

    assert response.status_code == expected_status, response.text
    if expected_status == 400:
        assert "your turn" in response.json()["detail"]
        assert game.players[0].hand == [QUICK_SLOW]
    else:
        assert [item.card.name for item in game.stack] == ["Quick"]


def test_the_ai_seat_casts_a_half_by_name():
    """The web AI's executor reads ``ai_policy.spell_being_cast``: the policy
    proposes ``card_name="Assault"`` out of the hand slot holding the split
    card, and the executor must cast that name, not the slot's."""
    from engine.ai_policy import choose_cast_action, spell_being_cast

    sid, _session_obj, game = _session()
    me = game.players[0]
    me.hand.append(ASSAULT_BATTERY)
    _mountains(game, 0, 1)
    game.start_turn(0)
    game.current_phase = "main"

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Assault"
    assert action.hand_index == 0
    assert spell_being_cast(me.hand, action) is face_cards(ASSAULT_BATTERY)[0]


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def test_a_decklist_may_spell_a_split_card_by_either_half_or_one_slash():
    """Moxfield writes "Assault // Battery" and sometimes "Assault". Every
    spelling is the one card (CR 709.2), and none shadows a real card name."""
    assert name_aliases(ASSAULT_BATTERY) == (
        "Assault", "Battery", "Assault / Battery", "Assault/Battery", "Assault//Battery",
    )
    assert name_aliases(_SHIPPED["Lightning Bolt"]) == ()

    catalog = [ASSAULT_BATTERY, _SHIPPED["Mountain"]]
    deck = build_deck_from_entries(
        catalog,
        [
            {"name": "Assault", "count": 1},
            {"name": "battery", "count": 1},
            {"name": "Assault / Battery", "count": 1},
            {"name": "Assault // Battery", "count": 1},
            {"name": "Mountain", "count": 2},
        ],
        seed=None,
    )
    assert sum(1 for card in deck if card is ASSAULT_BATTERY) == 4
    assert len(deck) == 6


def test_the_cast_spec_endpoint_answers_for_a_half_by_its_name(monkeypatch):
    """The Debug Menu's free cast and a mid-announcement re-ask both fetch a
    spec by name. A half's name returns the half's spec; the whole card's name
    returns the choice between them."""
    monkeypatch.setitem(runtime.CARD_BY_NAME, "assault // battery", ASSAULT_BATTERY)
    for face in face_cards(ASSAULT_BATTERY):
        monkeypatch.setitem(runtime.SPELL_BY_NAME, face.name.casefold(), face)
    assert runtime.spell_by_name("Battery") is face_cards(ASSAULT_BATTERY)[1]
    assert runtime.spell_by_name("Assault // Battery") is ASSAULT_BATTERY

    sid, _session_obj, _game = _session()

    def spec(name: str) -> dict:
        response = client.get(
            f"/api/sessions/{sid}/card_target_spec",
            params={"card_name": name, "seat": 0},
        )
        assert response.status_code == 200, response.text
        return response.json()

    assert spec("Assault")["name"] == "Assault"
    assert spec("Assault")["target_spec"]["kind"] == "any"
    assert spec("Battery")["target_spec"]["kind"] == "none"
    assert spec("Assault // Battery")["target_spec"]["kind"] == "faces"


def test_the_debug_free_cast_takes_a_half_and_puts_the_whole_card_in_play(monkeypatch):
    """``debug_cast_free`` looks the name up in the catalog, puts that card in
    the hand and casts it. Asked for "Battery" it must find the *card* (so one
    whole card enters the game) and cast the *half* (so a spell does)."""
    monkeypatch.setitem(runtime.CARD_BY_NAME, "assault // battery", ASSAULT_BATTERY)
    for alias in name_aliases(ASSAULT_BATTERY):
        monkeypatch.setitem(runtime.CARD_BY_NAME, alias.casefold(), ASSAULT_BATTERY)
    for face in face_cards(ASSAULT_BATTERY):
        monkeypatch.setitem(runtime.SPELL_BY_NAME, face.name.casefold(), face)

    sid, _session_obj, game = _session()
    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_cast_free", "card_name": "Battery"},
    )
    assert response.status_code == 200, response.text
    assert [item.card.name for item in game.stack] == ["Battery"]
    game.resolve_stack()
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Elephant Token"]
    assert game.players[0].graveyard == [ASSAULT_BATTERY]

    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "debug_cast_free", "card_name": "Assault // Battery"},
    )
    assert refused.status_code == 400 and "709.3" in refused.json()["detail"]
    assert game.players[0].hand == [], "the injected card was rolled back"


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


def test_every_cast_entry_asks_which_half_before_anything_else():
    """CR 709.3 precedes modes, costs and targets (CR 709.3a evaluates only the
    chosen half for all three). ``app.js`` has three places a cast begins — a
    hand click, a zone cast and a drag onto the battlefield — and each runs the
    same chain; the half prompt is first in every one."""
    entries = [
        index for index in range(len(APP_JS))
        if APP_JS.startswith("startModalChoicePrompt(card)", index)
    ]
    assert len(entries) >= 3
    for index in entries:
        before = APP_JS[max(0, index - 700):index]
        assert "startFaceChoicePrompt(card)" in before, APP_JS[index - 200:index + 60]


def test_the_chosen_half_stands_in_for_the_card_and_is_sent_by_its_own_name():
    prompt = app_js_function_body("startFaceChoicePrompt")
    assert "faceChoice: true" in prompt and "cardFaces(card)" in prompt
    assert "castable_now !== false" in prompt

    chosen = app_js_function_body("chooseModalMode")
    assert "choice.faceChoice" in chosen
    assert "castChosenFace(face, choice.castAction)" in chosen

    # ``async function`` — outside what ``app_js_function_body`` matches, so the
    # body is cut the same way here: to the first closing brace in column 0.
    start = APP_JS.index("async function castChosenFace(")
    chain = APP_JS[start:APP_JS.index("\n}\n", start)]
    for step in (
        "startModalChoicePrompt(face, castAction)",
        "startCastOfferPrompt(face, castAction)",
        "startCastCostPrompt(face, castAction)",
        "startCastTargetCascade(face, castAction)",
    ):
        assert step in chain, step
    assert "card_name: cardName" in chain
    assert "normalizeCardName(face)" in chain


# ---------------------------------------------------------------------------
# W2G4 — Word of Command forcing a split card (CR 709.3, CR 723.5)
# ---------------------------------------------------------------------------
#
# The caster chooses the card the target plays, and for a split card that is
# half an answer: which half is the caster's choice too. The prompt lists each
# half, the answer rides `card_name` (the field a cast already names a half
# on), and a split card answered whole is refused with the cast path's own
# reason rather than recorded and then failing to play.


def _w2g4_word_of_command(held):
    sid, _session_obj, game = _session()
    game.enforce_mana_costs = False
    game.players[0].hand = [_SHIPPED["Word of Command"]]
    game.players[1].hand = list(held)
    assert game.cast_from_hand(0, "Word of Command", target_player_index=1).supported
    return sid, game


def _w2g4_confirm(sid, **fields):
    return client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "word_of_command_confirm", **fields},
    )


def test_w2g4_the_word_of_command_prompt_lists_a_split_cards_halves():
    sid, _game = _w2g4_word_of_command([_SHIPPED["Grizzly Bears"], QUICK_SLOW])

    choices = _state(sid)["word_of_command"]["choices"]
    assert choices[0] == {"hand_index": 0, "name": "Grizzly Bears"}
    assert choices[1]["name"] == "Quick // Slow" and choices[1]["hand_index"] == 1
    assert choices[1]["faces"] == [
        {"name": "Quick", "mana_cost": "{R}",
         "oracle_text": "Quick deals 1 damage to any target."},
        {"name": "Slow", "mana_cost": "{G}", "oracle_text": "You gain 3 life."},
    ]
    # The target is not shown the caster's prompt (nor, through it, a hand).
    assert _state(sid, seat=1)["word_of_command"] is None


def test_w2g4_a_forced_split_card_is_answered_with_the_half():
    sid, game = _w2g4_word_of_command([QUICK_SLOW])
    them = game.players[1]

    whole = _w2g4_confirm(sid, hand_index=0)
    assert whole.status_code == 400
    assert "Quick or Slow" in whole.json()["detail"] and "709.3" in whole.json()["detail"]
    wrong = _w2g4_confirm(sid, hand_index=0, card_name="Quick // Slow")
    assert wrong.status_code == 400
    assert "chosen_hand_index" not in game.pending_word_of_command, "nothing was recorded"

    assert _w2g4_confirm(sid, hand_index=0, card_name="Slow").status_code == 200
    # Recorded; the spell waits on the stack for the caster to release priority.
    assert any(item.card.name == "Word of Command" for item in game.stack)
    assert them.hand == [QUICK_SLOW]
    # Whoever holds priority passes until the stack is empty: the caster
    # releases Word of Command, then the forced spell gets its own round.
    for _ in range(8):
        if not game.stack and game.pending_word_of_command is None:
            break
        holder = game.priority_player_index
        passed = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0 if holder is None else holder, "action": "pass_priority"},
        )
        assert passed.status_code == 200, passed.text
    assert not game.stack

    assert them.life == 23, "Slow, the half that was named — not Quick, the first"
    assert them.hand == [] and them.graveyard[-1] is QUICK_SLOW


def test_w2g4_the_client_offers_one_button_per_half_and_sends_its_name():
    body = app_js_function_body("applyWordOfCommandPrompt")
    assert "c.faces" in body and "data-woc-face" in body
    assert "answer.card_name = btn.dataset.wocFace" in body
    # A card with one face is still one button carrying only its hand index.
    assert 'data-woc-hand="${c.hand_index}">' in body
