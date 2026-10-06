"""An entry choice, over the wire: what every seat is told a permanent chose.

``tests/engine/test_entry_choices_reach_the_client.py`` holds the engine's
table to the pool. This is the route: a Ward, a Runed Halo and a Black Vise
resolved in a real session, the ``enter_choice`` prompt answered through the
action endpoint, and the state payload read back from **each** seat — because
the player who needs to see what was chosen is the one who did not choose it.

Shipped cards only (the running app cannot hold a card from a measured set);
Meddling Mage and Voice of All are covered engine-side by that guard.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import app_js_function_body, resolve_stack
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _w2g3_session(hand):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 4245,
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


def _w2g3_permanent(sid, name, *, viewer):
    """*name* on the host's battlefield, as *viewer* (a seat, or None for a
    spectator) is sent it."""
    params = {} if viewer is None else {"seat": viewer}
    state = client.get(f"/api/sessions/{sid}/state", params=params).json()
    return next(
        card for card in state["players"][0]["battlefield"] if card["name"] == name
    )


def _w2g3_answer(sid, **fields):
    response = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "enter_choice_confirm", **fields},
    )
    assert response.status_code == 200, response.text


def test_w2g3_a_named_card_is_shown_to_every_seat():
    """Runed Halo: "As this enchantment enters, choose a card name. You have
    protection from the chosen card name." The opponent has to be told which."""
    sid, game = _w2g3_session(["Runed Halo"])
    assert game.cast_from_hand(0, "Runed Halo").supported
    # One step, not `resolve_stack`: that helper answers a prompt that is
    # holding the stack with its default, and the prompt is what this test
    # answers over the wire.
    game.resolve_top_of_stack()
    assert game.pending_choice_of("enter_choice", 0) is not None

    # Nothing is shown while the name is still being asked: the value stamped
    # as it enters is the engine's placeholder, not a choice anyone has made.
    # This asserted the opposite ("the default … is already visible") until a
    # browser showed "Chosen color: white" beside a colour prompt still on the
    # screen - and to an opponent, a card name nobody had named.
    before = _w2g3_permanent(sid, "Runed Halo", viewer=1)["entry_choices"]
    assert before == []

    _w2g3_answer(sid, card_name="Lightning Bolt")
    for viewer in (0, 1, None):
        halo = _w2g3_permanent(sid, "Runed Halo", viewer=viewer)
        assert halo["entry_choices"] == [
            {"label": "Named card", "value": "Lightning Bolt"},
        ], viewer


def test_w2g3_a_chosen_color_is_shown_as_the_colour():
    """Flickering Ward: "As this Aura enters, choose a color. Enchanted
    creature has protection from the chosen color." The Aura carries the
    choice, in a word rather than a mana symbol."""
    sid, game = _w2g3_session(["Flickering Ward"])
    bears = game.players[0].battlefield[0]
    cast = game.cast_from_hand(
        0, "Flickering Ward",
        target_player_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert cast.supported, cast.details
    game.resolve_top_of_stack()
    assert game.pending_choice_of("enter_choice", 0) is not None
    _w2g3_answer(sid, mana_color="R", target_seat=0)

    ward = _w2g3_permanent(sid, "Flickering Ward", viewer=1)
    assert ward["entry_choices"] == [{"label": "Chosen color", "value": "red"}]
    # …and the creature it protects shows the protection the choice grants,
    # which is the badge that already existed.
    protected = _w2g3_permanent(sid, "Grizzly Bears", viewer=1)
    assert "Protection from red" in protected["keywords"]
    assert protected["entry_choices"] == []


def test_w2g3_a_chosen_player_is_shown_by_name():
    """Black Vise: "As this artifact enters, choose an opponent." With one
    opponent the choice is forced and no prompt is queued — and it is still a
    choice the table is told."""
    sid, game = _w2g3_session(["Black Vise"])
    assert game.cast_from_hand(0, "Black Vise").supported
    resolve_stack(game)
    vise = _w2g3_permanent(sid, "Black Vise", viewer=1)
    assert vise["entry_choices"] == [
        {"label": "Chosen player", "value": game.players[1].name},
    ]


def test_w2g3_a_permanent_with_no_entry_choice_sends_an_empty_list():
    sid, _game = _w2g3_session([])
    assert _w2g3_permanent(sid, "Grizzly Bears", viewer=0)["entry_choices"] == []


def test_w2g3_the_card_preview_renders_what_the_payload_carries():
    """The board is a canvas, so the hover preview is where a permanent's
    keywords are spelled out — and where its entry choices are, beside them."""
    preview = app_js_function_body("showCardPreview")
    assert "previewEntryChoiceLines(card)" in preview
    # Above the rules text that says "the chosen color".
    assert preview.index("previewEntryChoiceLines(card)") < preview.index(
        "renderOracleTextWithChanges(previewText"
    )
    lines = app_js_function_body("previewEntryChoiceLines")
    assert "card.entry_choices" in lines
    assert "choice.label" in lines and "choice.value" in lines
    # Escaped on the way into the DOM: a card name is text, never markup.
    assert "renderSymbolsInline(line)" in preview
