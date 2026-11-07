"""A card an earlier seat put into a Show and Tell is shown to that seat, and
to nobody else, while a later seat chooses.

"Each player may put an artifact, creature, enchantment, or land card from
their hand onto the battlefield." The players choose in turn order and the
cards enter together after the last choice (CR 101.4, 603.6a; the card's
2008-04-01 ruling), so the first seat's card leaves its hand at its answer and
waits, in no zone, inside the open entry event (``Game.open_entry_events``)
while the second seat chooses. CR 101.4a lets a card chosen from a hidden
zone stay face down as it is chosen — the other seats need not be shown it —
but its controller chose it, and the wire showed that seat nothing either:
gone from its hand and on no battlefield. ``serialization._serialize_arriving``
now lists an open event's puts, arriving (``entering: true``), on their
controller's battlefield **for that viewer alone**.

Driven at a human-vs-human table where the person casting answers first.
Backwards on the base: seat 0's payload during seat 1's choice holds no
Grizzly Bears anywhere.
"""
from __future__ import annotations

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _pass_priority, client, resolve_stack
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}


def _table():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4409,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield = []
        player.hand = []
    observer = Permanent(card=_CARDS["Soul Warden"])
    game._put_permanent_onto_battlefield(1, observer, None)
    observer.metadata["summoning_sickness_turn"] = -99
    resolve_stack(game)
    game.players[0].hand = [_CARDS["Show and Tell"], _CARDS["Grizzly Bears"]]
    game.players[1].hand = [_CARDS["Craw Wurm"]]
    game.stack.clear()
    game.pending_choices.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _state(sid, seat):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _names(zone):
    return [entry["name"] for entry in zone if isinstance(entry, dict)]


def _answer_the_offer(sid, game, seat: int, name: str):
    """*seat* takes its offer and picks *name* from its hand."""
    offer = game.pending_choices[0]
    assert (offer.kind, offer.player_index) == ("optional_pay", seat), offer.kind
    taken = client.post(f"/api/sessions/{sid}/action", json={
        "seat": seat, "action": "resolve_optional_pay", "card_name": "Show and Tell",
        "accept": True,
    })
    assert taken.status_code == 200, taken.text
    pick = next(c for c in game.pending_choices if c.kind == "put_from_hand_choice")
    assert pick.player_index == seat
    hand_index = [card.name for card in game.players[seat].hand].index(name)
    put = client.post(f"/api/sessions/{sid}/action", json={
        "seat": seat, "action": "put_from_hand_confirm", "hand_index": hand_index,
    })
    assert put.status_code == 200, put.text


def test_the_first_seat_s_card_is_shown_to_it_alone_while_the_second_chooses():
    sid, game = _table()
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Show and Tell",
    })
    assert cast.status_code == 200, cast.text
    assert _pass_priority(sid, 0).status_code == 200
    assert _pass_priority(sid, 1).status_code == 200

    _answer_the_offer(sid, game, 0, "Grizzly Bears")
    # Seat 1 is choosing now; the Bears wait in the open event, in no zone.
    assert game.pending_choices and game.pending_choices[0].player_index == 1
    assert any(put.permanent.card.name == "Grizzly Bears"
               for event in game.open_entry_events for put in event.puts)
    assert not any(p.card.name == "Grizzly Bears" for p in game.all_permanents())

    own = _state(sid, 0)["players"][0]
    arriving = [entry for entry in own["battlefield"] if entry.get("entering")]
    assert _names(arriving) == ["Grizzly Bears"], own["battlefield"]
    assert "Grizzly Bears" not in _names(own["hand"])
    # CR 101.4a: the other seat is shown nothing of it — not on the board, and
    # its hand count already one less.
    other_view = _state(sid, 1)["players"][0]
    assert "Grizzly Bears" not in _names(other_view["battlefield"])
    assert other_view["hand_count"] == 0

    # Seat 1 answers: both enter together, the Bears now an ordinary permanent
    # for both seats, and the Soul Warden saw two creatures enter at once.
    life_before = game.players[1].life
    _answer_the_offer(sid, game, 1, "Craw Wurm")
    resolve_stack(game)
    for seat in (0, 1):
        board = _state(sid, seat)["players"][0]["battlefield"]
        assert _names(board) == ["Grizzly Bears"]
        assert not any(entry.get("entering") for entry in board)
    assert game.players[1].life == life_before + 2

