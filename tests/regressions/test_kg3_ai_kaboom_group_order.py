"""Kaboom!'s targets within one player's group are handled in the order the
caster chooses.

"Choose any number of target players or planeswalkers. For each of them,
reveal cards from the top of your library until you reveal a nonland card,
Kaboom! deals damage equal to that card's mana value to that player or
planeswalker, then you put the revealed cards on the bottom of your library in
any order." Its ruling (2022-09-09, Scryfall): "those targets will be handled
one at a time in turn order. Start with targets that are either the player
whose turn it is (probably you) or permanents that player controls. You choose
the relative order of targets within that group. … After that group is done,
move on to targets that are either the next player in turn order or permanents
they control."

The groups were already in turn order (the announcement's canonical order,
``target_roles.LATER_IN_TURN_ORDER_ROLE``), but within a group the order was
fixed — the player, then their planeswalkers by id — and nobody was asked.
Which target is handled first decides which revealed card it is dealt, so the
order is a real choice: the ``target_group_order`` prompt
(``handlers/_role_order.py``), armed only where a group holds two targets,
answered with the slot order by a seat nobody asks.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from tests.helpers import resolve_stack
from web.app import app, store

_CARDS = {card.name: card for card in load_catalog()}
client = TestClient(app)


def _walker(name="Chandra, Heart of Fire", loyalty=5) -> Permanent:
    walker = Permanent(card=_CARDS[name])
    walker.metadata["summoning_sickness_turn"] = -99
    add_counters(walker, "loyalty", loyalty)
    return walker


def _kaboom_table(*, interactive, seats=2, boards=None, library=("Hill Giant", "Shock", "Island")):
    boards = boards or {}
    players = [
        PlayerState(
            name=f"P{seat}",
            hand=[_CARDS["Kaboom!"]] if seat == 0 else [],
            library=[_CARDS[name] for name in (library if seat == 0 else ("Island",) * 4)],
            battlefield=list(boards.get(seat, ())),
        )
        for seat in range(seats)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(range(seats)) if interactive else set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return game


def _owed(game):
    return [choice for choice in game.pending_choices if choice.kind == "target_group_order"]


def test_the_caster_orders_one_players_group_and_the_walker_is_dealt_the_first_card():
    walker = _walker()
    game = _kaboom_table(interactive=True, boards={1: [walker]})

    assert game.cast_from_hand(0, "Kaboom!", target_role_refs=[
        {"seat": 1}, {"permanent_id": walker.permanent_id},
    ]).supported
    (choice,) = _owed(game)
    assert [(t["name"], t["group"]) for t in choice.data["targets"]] == [
        ("P1", 1), ("Chandra, Heart of Fire", 1),
    ]
    # The resolution waits on the answer (CR 608.2): nothing has been dealt.
    assert any(item.card.name == "Kaboom!" for item in game.stack)
    assert game.players[1].life == 20 and counters_on(walker, "loyalty") == 5

    assert game.confirm_target_group_order(0, [1, 0])
    resolve_stack(game)

    # Hill Giant (4) to the walker, then Shock (1) to its controller.
    assert counters_on(walker, "loyalty") == 1
    assert game.players[1].life == 19
    assert "P0 handles Kaboom!'s targets in the order Chandra, Heart of Fire, P1" in game.log


def test_a_seat_nobody_asks_takes_the_slot_order():
    """The default is the order every Kaboom! resolved in before the prompt
    existed — the player, then their planeswalkers — and nothing is queued or
    logged for it."""
    walker = _walker()
    game = _kaboom_table(interactive=False, boards={1: [walker]})

    assert game.cast_from_hand(0, "Kaboom!", target_role_refs=[
        {"seat": 1}, {"permanent_id": walker.permanent_id},
    ]).supported
    resolve_stack(game)

    assert game.players[1].life == 16
    assert counters_on(walker, "loyalty") == 4
    assert _owed(game) == []
    assert not any("handles Kaboom!'s targets" in line for line in game.log)


def test_an_order_that_moves_a_target_out_of_its_group_is_refused():
    """Only the order *within* a group is the caster's: the active player's
    group is handled first whatever the answer says. The prompt stays owed."""
    walker = _walker()
    game = _kaboom_table(interactive=True, boards={1: [walker]})
    game.cast_from_hand(0, "Kaboom!", target_role_refs=[
        {"seat": 0}, {"seat": 1}, {"permanent_id": walker.permanent_id},
    ])
    (choice,) = _owed(game)
    assert [t["group"] for t in choice.data["targets"]] == [0, 1, 1]

    assert not game.confirm_target_group_order(0, [1, 0, 2])
    assert not game.confirm_target_group_order(0, [0, 1, 1])
    assert _owed(game) == [choice]
    assert game.confirm_target_group_order(0, [0, 2, 1])


def test_no_group_of_two_asks_nothing():
    """One target per player: the turn order decides it all, and the
    resolution runs straight through for an interactive caster too."""
    game = _kaboom_table(interactive=True, seats=3)

    assert game.cast_from_hand(0, "Kaboom!", target_role_refs=[
        {"seat": 1}, {"seat": 2},
    ]).supported
    resolve_stack(game)

    assert _owed(game) == []
    assert [player.life for player in game.players] == [20, 16, 19]


def test_the_seat_is_served_the_prompt_and_answers_it_on_the_wire():
    """The payload the caster is served (``web/prompt_board``), and the route
    that answers it (`target_group_order_confirm`)."""
    walker = _walker()
    game = _kaboom_table(interactive=True, boards={1: [walker]})
    game.cast_from_hand(0, "Kaboom!", target_role_refs=[
        {"seat": 1}, {"permanent_id": walker.permanent_id},
    ])
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "H", "guest_name": "G",
        "host_colors": 2, "guest_colors": 2, "seed": 2600,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "G"})
    session = store.get(sid)
    session.pregame_phase = None
    session.current_turn = 0
    session.joined_seats = {0, 1}
    session.game = game

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    served = state["target_group_order"]
    assert served["card_name"] == "Kaboom!" and served["player_seat"] == 0
    assert [(t["index"], t["name"], t["group"], t["id"]) for t in served["targets"]] == [
        (0, "P1", 1, None), (1, "Chandra, Heart of Fire", 1, walker.permanent_id),
    ]

    refused = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "target_group_order_confirm", "target_order": [0],
    })
    assert refused.status_code == 400
    answered = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "target_group_order_confirm", "target_order": [1, 0],
    })
    assert answered.status_code == 200, answered.text
    resolve_stack(game)
    assert counters_on(walker, "loyalty") == 1 and game.players[1].life == 19
