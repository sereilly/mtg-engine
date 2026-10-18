"""Lodestone Bauble over the wire: the body Phase 5 sent, and what follows.

    {"action":"activate","permanent_name":"Lodestone Bauble",
     "target_seat":0,"target_permanent_indices":[1,2,3]}

"Put up to four target basic land cards from a player's graveyard on top of
their library in any order. That player draws a card at the beginning of the
next turn's upkeep." Aimed at the activator's own graveyard, the *opponent*
drew at its upkeep, and "in any order" was never asked.

Now: the ability resolves into a ``reorder_library`` prompt for the library's
owner (CR 401.4, ``position: "top"``), answered with ``reorder_library_confirm``
and a ``card_order``; and the graveyard's owner is who draws
(``tests/rules/test_delayed_that_player.py``).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import _mk_card, resolve_stack
from web.app import app, store
from web.runtime import CARD_BY_NAME

client = TestClient(app)


def _basic(name: str):
    return _mk_card(name=name, type_line=f"Basic Land — {name}")


def test_the_activators_own_graveyard_then_the_order_then_their_draw():
    created = client.post(
        "/api/sessions", json={"mode": "human_vs_human", "seed": 5150},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    game.interactive_seats = {0, 1}
    me, you = game.players
    bauble = Permanent(card=CARD_BY_NAME["lodestone bauble"])
    bauble.metadata["summoning_sickness_turn"] = -99
    me.battlefield = [bauble]
    me.mana_pool = {symbol: 0 for symbol in me.mana_pool}
    me.mana_pool["C"] = 1
    me.graveyard = [
        _mk_card(name="Black Lotus", type_line="Artifact"),
        _basic("Mountain"), _basic("Island"), _basic("Forest"),
    ]
    game._settle()

    def act(seat: int, **body):
        return client.post(
            f"/api/sessions/{sid}/action", json={"seat": seat, **body},
        )

    activated = act(
        0, action="activate", permanent_name="Lodestone Bauble",
        target_seat=0, target_permanent_indices=[1, 2, 3],
    )
    assert activated.status_code == 200, activated.text
    # Both seats pass and the ability resolves — into the owner's order.
    for seat in (0, 1):
        if game.stack and game.pending_reorder_library is None:
            assert act(seat, action="pass_priority").status_code == 200

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    prompt = state["reorder_library"]
    assert prompt is not None, game.log[-6:]
    assert prompt["caster_seat"] == 0 and prompt["target_seat"] == 0
    assert prompt["position"] == "top" and prompt["may_shuffle"] is False
    assert [card["name"] for card in prompt["cards"]] == ["Mountain", "Island", "Forest"]

    ordered = act(0, action="reorder_library_confirm", card_order=[2, 0, 1])
    assert ordered.status_code == 200, ordered.text
    assert [card.name for card in me.library][:3] == ["Forest", "Mountain", "Island"]
    assert [card.name for card in me.graveyard] == ["Black Lotus", "Lodestone Bauble"]

    # "That player" is the graveyard's owner: at the next turn's upkeep —
    # the other player's turn — it is the activator who draws.
    hands = [len(me.hand), len(you.hand)]
    game.resolve_upkeep(1)
    resolve_stack(game)
    assert [len(me.hand) - hands[0], len(you.hand) - hands[1]] == [1, 0], game.log[-6:]
    assert me.hand[-1].name == "Forest"
