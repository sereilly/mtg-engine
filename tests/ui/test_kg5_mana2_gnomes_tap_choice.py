"""A Gnomed Plains beside Hall of Gemstone, over the wire (CR 616.1e).

Quarum Trench Gnomes' "If target Plains is tapped for mana, it produces
colorless mana instead of white mana" and Hall of Gemstone's "lands tapped for
mana produce mana of the chosen color instead of any other color" are two
replacements over one tap (CR 106.12b): Hall first is the chosen {R}, the
Gnomes first is {C}. The tap cannot wait on a prompt (CR 601.2g), so the
choice rides the tap action's own colour: the Plains' ``produced_mana`` offers
both (the client's colour fan reads it, ``getDualLandColors``) and
``mana_color`` picks the order.

Backwards on ``e245e624c``: the Plains offers ``["C"]`` alone and makes {C}
asked for {R}.
"""
from __future__ import annotations

import pytest

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, settle
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 5151,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    for player in game.players:
        player.hand.clear()
    game.remove_all_from_battlefield(list(game.all_permanents()))
    seats = set(game.interactive_seats)
    enforced = game.enforce_mana_costs
    game.enforce_mana_costs = False
    placed = {}
    for name in ("Plains", "Quarum Trench Gnomes", "Hall of Gemstone"):
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed[name] = permanent
    plains = placed["Plains"]
    # Hall's upkeep choice, answered {R} by the seat whose upkeep it is, and
    # the Gnomes aimed at the Plains: both through the engine's own entries.
    game.interactive_seats = {0}
    game.start_turn(0)
    settle(game, answers={
        "color_choice": lambda g, c: g.confirm_color_choice(c.player_index, "R"),
    })
    activated = game.activate_permanent_ability(
        0, "Quarum Trench Gnomes", target_permanent_ids=[plains.permanent_id],
    )
    assert activated.supported, activated.details
    settle(game)
    game.enforce_mana_costs = enforced
    for permanent in game.all_permanents():
        permanent.tapped = False
    for symbol in game.players[0].mana_pool:
        game.players[0].mana_pool[symbol] = 0
    game.interactive_seats = seats
    game.pending_choices.clear()
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game, plains


def _entry(sid, permanent, seat=0):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()
    return next(
        entry for player in state["players"] for entry in player["battlefield"]
        if entry.get("id") == permanent.permanent_id
    )


@pytest.mark.parametrize("asked", ["R", "C"])
def test_the_gnomed_plains_offers_both_orders_and_makes_the_one_asked(asked):
    sid, game, plains = _session()
    entry = _entry(sid, plains)
    assert sorted(entry["produced_mana"]) == ["C", "R"], entry["produced_mana"]
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": plains.permanent_id,
        "mana_color": asked,
    })
    assert response.status_code == 200, response.text
    assert plains.tapped
    made = {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}
    assert made == {asked: 1}, game.log[-3:]
    assert f"Plains produced {{{asked}}} instead" in game.log
