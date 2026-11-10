"""The tap's colour is CR 616.1e's choice between two substitutions, over the wire.

A Forest under Infernal Darkness ("If a land is tapped for mana, it produces
{B} instead of any other type") and a Deep Water record ("…it produces {U}
instead of any other type") makes {B} or {U}, as its controller orders the two
(CR 616.1e–f). The tap happens mid-payment and cannot wait on a prompt (CR
601.2g), so the choice rides the tap action's own colour: the Forest's
``produced_mana`` offers both symbols (the client's colour fan reads it,
``getDualLandColors``), and ``mana_color`` picks the order.

Beside it, the "that land could produce" wire (CR 106.7): Benthic Explorers'
``symbols_by_cost`` names what an opponent's Reflecting Pool could produce on
that board — the opponent's Forest's {G} — and the activation makes it.

Backwards on the base (59f133e63): the Forest offers one symbol and makes {U}
asked for {B}; the Pool is offered as all five colours and makes {B}.
"""
from __future__ import annotations

import pytest

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, resolve_stack
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}


def _session(mine=(), theirs=(), *, deep_water=False):
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
    game.interactive_seats = set()
    placed = {}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.setdefault(name, permanent)
    if deep_water:
        enforced = game.enforce_mana_costs
        game.enforce_mana_costs = False
        activated = game.activate_permanent_ability(0, "Deep Water")
        assert activated.supported, activated.details
        resolve_stack(game)
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
    return sid, game, placed


def _entry(sid, permanent, seat=0):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()
    return next(
        entry for player in state["players"] for entry in player["battlefield"]
        if entry.get("id") == permanent.permanent_id
    )


def _activate(sid, permanent, **fields):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": permanent.permanent_id, **fields,
    })


@pytest.mark.parametrize("asked", ["B", "U"])
def test_the_forest_offers_both_symbols_and_makes_the_one_asked(asked):
    sid, game, placed = _session(["Forest", "Infernal Darkness", "Deep Water"], deep_water=True)
    forest = placed["Forest"]
    entry = _entry(sid, forest)
    assert sorted(entry["produced_mana"]) == ["B", "U"], entry["produced_mana"]
    # The land's own abilities say nothing here: its summary is the answer.
    assert entry.get("ability_mana") is None
    response = _activate(sid, forest, mana_color=asked)
    assert response.status_code == 200, response.text
    assert forest.tapped
    made = {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}
    assert made == {asked: 1}, game.log[-3:]
    assert f"Forest produced {{{asked}}} instead" in game.log


def test_benthic_explorers_is_offered_what_the_opponent_s_pool_could_produce():
    sid, game, placed = _session(["Benthic Explorers"], ["Reflecting Pool", "Forest"])
    explorers, pool = placed["Benthic Explorers"], placed["Reflecting Pool"]
    pool.tapped = True
    (entry,) = _entry(sid, explorers)["ability_mana"]
    assert entry["symbols_by_cost"][str(pool.permanent_id)] == ["G"]
    response = _activate(
        sid, explorers, cost_permanent_ids=[pool.permanent_id], mana_color="B",
    )
    assert response.status_code == 200, response.text
    assert not pool.tapped
    made = {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}
    assert made == {"G": 1}, game.log[-3:]
