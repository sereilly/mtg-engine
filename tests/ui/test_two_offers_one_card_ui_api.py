"""Two offers on one card, each saying its own sentence — and a graveyard
pick that is not an exile saying so.

Gurzigost prints two offers: an upkeep toll ("…sacrifice this creature
unless you put two cards from your graveyard on the bottom of your library")
and an activated "You may have this creature assign its combat damage this
turn as though it weren't blocked." ``offer_wording`` declined to choose
between two offer sentences on one card, so both ``optional_pay`` prompts
carried the whole two-sentence text and a person could not tell which was
being asked. The resolving context carries the printed line that armed the
offer (``ability_text``), and an offer sentence in that line is the offer's.

Paying the toll is a ``graveyard_exile_pick`` with ``destination:
"library_bottom"``; its dialog said "exile" in the title, the sentence and
the button.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import app_js_function_body, run_app_js
from web.app import app, store

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_TOLL = (
    "At the beginning of your upkeep, sacrifice this creature unless you put two "
    "cards from your graveyard on the bottom of your library."
)
_ACTIVATED = (
    "{G}{G}, Discard a card: You may have this creature assign its combat damage "
    "this turn as though it weren't blocked."
)


def _session(set_pool, *, hand=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 1250,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.active_player_index = 0
    session.current_turn = 0
    for player in game.players:
        player.battlefield.clear()
        player.graveyard.clear()
    lea = set_pool("LEA")
    game.players[0].hand = list(hand)
    game.players[0].graveyard = [lea["Giant Growth"], lea["Lightning Bolt"], lea["Shivan Dragon"]]
    gurzigost = Permanent(card=set_pool("TOR")["Gurzigost"])
    game._put_permanent_onto_battlefield(0, gurzigost, None)
    gurzigost.metadata["summoning_sickness_turn"] = -99
    return sid, game, gurzigost


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_the_upkeep_toll_says_its_own_sentence_and_which_half_is_which(set_pool):
    sid, game, _gurzigost = _session(set_pool)
    game.resolve_upkeep(0, defer_priority=True)
    game.resolve_top_of_stack()

    (offer,) = _state(sid)["optional_pay"]["pending"]
    assert offer["card_name"] == "Gurzigost"
    assert offer["card_text"] == _TOLL
    assert offer["decline_text"] == "sacrifice this creature"
    assert offer["accept_text"] == (
        "you put two cards from your graveyard on the bottom of your library"
    )

    # Paying is the graveyard pick, which says where the cards go.
    answered = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "resolve_optional_pay", "accept": True, "card_name": "Gurzigost",
    })
    assert answered.status_code == 200, answered.text
    pick = _state(sid)["graveyard_exile_pick"]
    assert (pick["destination"], pick["count"], pick["up_to"]) == ("library_bottom", 2, False)


def test_the_activated_offer_says_its_own_sentence(set_pool):
    sid, game, _gurzigost = _session(set_pool, hand=[set_pool("LEA")["Giant Growth"]])
    game.current_phase = "combat"
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    game.activate_permanent_ability(0, "Gurzigost")

    (offer,) = _state(sid)["optional_pay"]["pending"]
    assert offer["card_text"] == _ACTIVATED
    # "You may …": yes is the sentence, so there are no halves to name.
    assert "accept_text" not in offer and "decline_text" not in offer


@needs_node
@pytest.mark.parametrize("destination, title, sentence, button", [
    ("library_bottom", "Put Cards on the Bottom of a Library",
     "Gurzigost: choose 2 card(s) from Host's graveyard to put on the bottom of your library, then Confirm.",
     "Put 0 of 2 on the bottom"),
    ("exile", "Exile Cards from a Graveyard",
     "Gurzigost: choose 2 card(s) from Host's graveyard to exile, then Confirm.",
     "Exile 0 of 2"),
])
def test_the_graveyard_pick_says_where_its_cards_go(set_pool, destination, title, sentence, button):
    """The dialog over the prompt the server sent for Gurzigost's toll, and
    the same prompt as an exile, which reads as it did."""
    sid, game, _gurzigost = _session(set_pool)
    game.resolve_upkeep(0, defer_priority=True)
    game.resolve_top_of_stack()
    assert client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "resolve_optional_pay", "accept": True, "card_name": "Gurzigost",
    }).status_code == 200
    pick = {**_state(sid)["graveyard_exile_pick"], "destination": destination}

    out = run_app_js(
        ["graveyardPickWords", "renderGraveyardExileModal"],
        """
        renderGraveyardExileModal(INPUT.pick);
        return {
          title: nodes.graveyardExileTitle.textContent,
          sentence: nodes.graveyardExileSubtitle.textContent,
          button: nodes.graveyardExileConfirmBtn.textContent,
          disabled: nodes.graveyardExileConfirmBtn.disabled,
        };
        """,
        {"pick": pick},
        prelude="""
        let seat = 0;
        let graveyardExileSelected = new Set();
        const escapeHtml = (s) => String(s);
        const updateActionHint = () => {};
        const sendAction = async () => {};
        const node = () => ({
          textContent: "", innerHTML: "", disabled: false, onclick: null,
          classList: { add() {}, remove() {}, toggle() {} },
          querySelectorAll: () => [],
        });
        const nodes = {
          graveyardExileModal: node(), graveyardExileTitle: node(),
          graveyardExileSubtitle: node(), graveyardExileGrid: node(),
          graveyardExileConfirmBtn: node(),
        };
        const document = { getElementById: (id) => nodes[id] || null };
        """,
    )
    assert out == {"title": title, "sentence": sentence, "button": button, "disabled": True}


def test_the_dialog_names_the_destination_rather_than_exile():
    body = app_js_function_body("renderGraveyardExileModal")
    assert "graveyardPickWords(info)" in body
    assert '"Exile nothing"' not in body
