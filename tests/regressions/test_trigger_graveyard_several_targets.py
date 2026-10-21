"""Several target cards in one graveyard, announced by a triggered ability.

"When this creature enters, exile **up to two target cards from a single
graveyard**." (Gravegouger, Torment.) A triggered ability chooses its targets
as it is put on the stack (CR 603.3d, through CR 601.2c), and these are
targets. Torment's wave 1 landed the card with its pile and cards picked as
the ability *resolved* — after every response, which is a different card —
and pinned it in ``tests/engine/test_stack_targets._UNANNOUNCED_TRIGGER_
TARGETS``: the trigger-target prompt could name one graveyard card and no
more. Wave 2 (W2G2) gave it the several-card shape the spell form of the same
sentence already had (Decompose: ``targeting.SINGLE_GRAVEYARD``):

* the lowering writes the ``targets`` description under a trigger too, so the
  picker is derived;
* the ``trigger_target`` prompt offers every legal card with its stamp and
  says ``max_targets`` / ``single_graveyard``, and is answered with a pile and
  its slots (``graveyard_indices``) — or one slot, or nobody;
* the stack object carries the stamps and slots in the shape a spell's
  announcement does, so the handler's announced branch, CR 608.2b's re-check
  and ``stack_targets`` read it unchanged;
* a seat nobody asks names what the resolution used to take: another seat's
  pile first, the most it may, cards their owner could still cast from there
  first.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.models import Permanent
from engine.stack_targets import chosen_targets
from tests.helpers import resolve_stack
from web.app import app, store

client = TestClient(app)


@pytest.fixture
def pool(catalog_by_name, set_pool):
    return {**catalog_by_name, **set_pool("TOR")}


def _table(pool, *, gy0=("Giant Growth",), gy1=("Lightning Bolt", "Grizzly Bears", "Giant Growth"),
           interactive=()):
    game = Game(players=[
        PlayerState(name="P0", hand=[pool["Gravegouger"]], library=[pool["Forest"]] * 5,
                    graveyard=[pool[name] for name in gy0]),
        PlayerState(name="P1", library=[pool["Forest"]] * 5,
                    graveyard=[pool[name] for name in gy1]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _asked(pool, **board):
    """Gravegouger resolved onto seat 0's battlefield, its entry trigger
    waiting on seat 0's announcement."""
    game = _table(pool, interactive=(0,), **board)
    game.queue_from_hand(0, "Gravegouger")
    game.resolve_top_of_stack()
    return game


def _names(cards):
    return [card.name for card in cards]


def test_the_trigger_asks_for_up_to_two_cards_in_one_pile(pool):
    game = _asked(pool)
    [choice] = game.pending_choices_of("trigger_target")
    assert choice.player_index == 0
    assert choice.data["max_targets"] == 2
    assert choice.data["up_to"] and choice.data["single_graveyard"]
    assert [
        (target["seat"], target["graveyard_index"], target["name"])
        for target in choice.data["targets"]
    ] == [
        (0, 0, "Giant Growth"), (1, 0, "Lightning Bolt"),
        (1, 1, "Grizzly Bears"), (1, 2, "Giant Growth"),
    ]
    # Nothing has moved: the cards are named, not yet exiled.
    assert len(game.players[1].graveyard) == 3


def test_the_announcement_is_held_to_what_was_offered(pool):
    """Each slot once, no more than two, every one in the pile named."""
    game = _asked(pool)
    assert not game.confirm_trigger_target(0, seat=1, graveyard_indices=[0, 1, 2])
    assert not game.confirm_trigger_target(0, seat=1, graveyard_indices=[0, 0])
    assert not game.confirm_trigger_target(0, seat=0, graveyard_indices=[0, 1])
    assert not game.confirm_trigger_target(0, seat=1, graveyard_indices=[5])
    assert game.pending_choices_of("trigger_target")
    assert game.confirm_trigger_target(0, seat=1, graveyard_indices=[0, 2])

    item = game.stack[-1]
    assert item.target_player_index == 1 and item.target_permanent_index == [0, 2]
    assert [target.stamp.card.name for target in chosen_targets(game, item)] == [
        "Lightning Bolt", "Giant Growth",
    ]
    resolve_stack(game)
    assert _names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert _names(game.players[1].exile) == ["Lightning Bolt", "Giant Growth"]


def test_a_target_that_leaves_in_response_is_not_replaced(pool):
    """CR 608.2b: the card that is gone is unaffected and the other is still
    exiled; with both gone the ability does nothing at all."""
    game = _asked(pool)
    assert game.confirm_trigger_target(0, seat=1, graveyard_indices=[0, 1])
    game.players[1].exile.append(game.players[1].graveyard.pop(0))
    resolve_stack(game)
    assert _names(game.players[1].graveyard) == ["Giant Growth"]
    assert _names(game.players[1].exile) == ["Lightning Bolt", "Grizzly Bears"]

    game = _asked(pool)
    assert game.confirm_trigger_target(0, seat=1, graveyard_indices=[0, 1])
    game.players[1].graveyard[:2] = []
    resolve_stack(game)
    assert _names(game.players[1].graveyard) == ["Giant Growth"]
    assert game.players[1].exile == []
    assert any("608.2b" in line for line in game.log), game.log[-4:]


def test_one_card_or_none_are_answers_too(pool):
    game = _asked(pool)
    assert game.confirm_trigger_target(0, seat=1, graveyard_index=1)
    resolve_stack(game)
    assert _names(game.players[1].exile) == ["Grizzly Bears"]

    game = _asked(pool)
    assert game.confirm_trigger_target(0, permanent_ids=[])
    resolve_stack(game)
    assert game.players[1].exile == [] and len(game.players[1].graveyard) == 3


def test_the_exiled_cards_come_back_when_it_leaves(pool):
    """The announced cards are linked to the Gravegouger (CR 607.2a), so its
    leaves-the-battlefield ability returns them."""
    game = _asked(pool)
    assert game.confirm_trigger_target(0, seat=1, graveyard_indices=[1, 2])
    resolve_stack(game)
    assert _names(game.players[1].exile) == ["Grizzly Bears", "Giant Growth"]
    gouger = next(p for p in game.controlled_by(0) if p.card.name == "Gravegouger")
    game.players[0].hand.append(pool["Swords to Plowshares"])
    game.interactive_seats = set()
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[gouger.permanent_id],
    )
    resolve_stack(game)
    assert game.players[1].exile == []
    assert sorted(_names(game.players[1].graveyard)) == [
        "Giant Growth", "Grizzly Bears", "Lightning Bolt",
    ]


def test_a_seat_nobody_asks_names_the_opponents_cards(pool):
    """The cards the resolution took before they were announced: another
    seat's pile, the most the ability allows, a card its owner could still
    cast from there (flashback) first."""
    game = _table(pool, gy1=("Lightning Bolt", "Grizzly Bears", "Deep Analysis"))
    game.cast_from_hand(0, "Gravegouger")
    resolve_stack(game)
    assert _names(game.players[0].graveyard) == ["Giant Growth"]
    assert _names(game.players[1].exile) == ["Deep Analysis", "Lightning Bolt"]


def test_with_no_card_anywhere_the_trigger_names_nothing(pool):
    game = _table(pool, gy0=(), gy1=())
    game.cast_from_hand(0, "Gravegouger")
    resolve_stack(game)
    assert any("Gravegouger exiled nothing" in line for line in game.log)


def test_the_wire_offers_the_pile_and_takes_several_slots():
    """The renderer says how many and that they share a pile; the action
    route takes ``target_seat`` with ``graveyard_indices``."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "H", "guest_name": "G",
        "host_colors": 2, "guest_colors": 2, "seed": 603,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "G"})
    session = store.get(sid)
    session.current_turn = 0
    session.pregame_phase = None
    from engine.card_loader import load_cards, manifest_set_paths

    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    game = _asked(pool)
    game.interactive_seats = {0, 1}
    session.game = game

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    info = state["trigger_target"]
    assert info["max_targets"] == 2 and info["single_graveyard"] is True
    assert {(c["kind"], c["seat"], c["graveyard_index"]) for c in info["candidates"]} == {
        ("graveyard", 0, 0), ("graveyard", 1, 0), ("graveyard", 1, 1), ("graveyard", 1, 2),
    }
    refused = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "trigger_target_confirm",
        "target_seat": 1, "graveyard_indices": [0, 1, 2],
    })
    assert refused.status_code == 400
    answered = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "trigger_target_confirm",
        "target_seat": 1, "graveyard_indices": [0, 1],
    })
    assert answered.status_code == 200, answered.text
    item = game.stack[-1]
    assert item.target_player_index == 1 and item.target_permanent_index == [0, 1]
