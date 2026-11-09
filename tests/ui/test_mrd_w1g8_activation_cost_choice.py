"""The wire for an ability with a choice of printed costs (the Mirrodin Shards).

"{3}, {T} or {R}, {T}: This artifact deals 1 damage to any target." (Granite
Shard.) One ability, two prices (2004-10-04: "You can pay either of the two
costs (but not both at the same time)"), announced as it is activated
(CR 602.2b through 601.2b). The controller's view of the permanent carries
``ability_cost_alternatives`` — the printed prices per usable ability, in
printed order — and the activate action's ``alternative_cost_index`` (the
request field the cast path reads for CR 118.9a's choice) names the one paid;
absent, the engine pays the cheapest the pool, else the board, covers.

The client half (a picker that offers the two prices and sends the index) is
the wave-2 client group's; this file holds the server's side of the wire.
"""
from __future__ import annotations

from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import client, resolve_stack
from web.app import store

_MRD = {
    card.name: card
    for card in load_cards(manifest_set_path("MRD", include_measured=True))
}
_LEA = {card.name: card for card in load_cards(manifest_set_path("LEA"))}


def _table(pool, *, lands=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4411,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.hand = []
    game.enforce_mana_costs = False
    shard = Permanent(card=_MRD["Granite Shard"])
    game._put_permanent_onto_battlefield(0, shard, None)
    for name in lands:
        land = Permanent(card=_LEA[name])
        game._put_permanent_onto_battlefield(0, land, None)
    resolve_stack(game)
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool)
    game.stack.clear()
    game.pending_choices.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game, shard


def _activate(sid, shard, **extra):
    body = {
        "seat": 0, "action": "activate", "permanent_name": "Granite Shard",
        "permanent_id": shard.permanent_id, "target_seat": 1,
    }
    body.update(extra)
    return client.post(f"/api/sessions/{sid}/action", json=body)


def test_the_controller_is_offered_both_prices():
    sid, game, shard = _table({"R": 3})
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    entry = next(e for e in state["players"][0]["battlefield"] if e["id"] == shard.permanent_id)
    assert entry["ability_cost_alternatives"] == [["{3}", "{R}"]]


def test_the_announced_index_is_the_cost_paid():
    sid, game, shard = _table({"R": 3})
    response = _activate(sid, shard, alternative_cost_index=0)
    assert response.status_code == 200, response.json()
    assert "Granite Shard: activated for {3}" in game.log
    assert sum(game.players[0].mana_pool.values()) == 0

    sid, game, shard = _table({"R": 3})
    assert _activate(sid, shard, alternative_cost_index=1).status_code == 200
    assert "Granite Shard: activated for {R}" in game.log
    assert game.players[0].mana_pool["R"] == 2


def test_an_index_naming_no_printed_cost_is_refused():
    sid, game, shard = _table({"R": 3})
    response = _activate(sid, shard, alternative_cost_index=5)
    assert response.status_code == 400
    assert "no printed activation cost" in response.json()["detail"]
    assert not shard.tapped and game.players[0].mana_pool["R"] == 3


def test_the_auto_tap_taps_for_the_cheapest_price_the_board_pays():
    """No index and an empty pool: the default is the cheapest cost the board
    could pay, so the auto-tap taps the Mountain alone, not three lands."""
    sid, game, shard = _table({}, lands=("Mountain", "Island", "Island", "Island"))
    response = _activate(sid, shard, auto_tap=True)
    assert response.status_code == 200, response.json()
    tapped = sorted(p.card.name for p in game.players[0].battlefield if p.tapped)
    assert tapped == ["Granite Shard", "Mountain"]
    assert "Granite Shard: activated for {R}" in game.log
