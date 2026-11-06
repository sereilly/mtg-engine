"""Storm's prompts and Mind's Desire's play from exile, over the real routes.

Scourge is still under ``measured``, so no deck holds its cards; the board is
placed on the session's game directly, as the Debug Menu does for a shipped
card. What is asked of the wire is what a person at the table needs:

* every storm copy with one permanent or player target is its own
  ``copy_spell_target`` prompt, rendered and answered one at a time;
* a copy aimed at a card in a graveyard (Reaping the Graves) is a
  ``retarget_choice`` with "keep" and the other cards, answered by position;
* Mind's Desire's exiled card is offered to its seat in
  ``castable_from_zones``, free, and the cast route takes it.
"""

from __future__ import annotations

from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import client, seat_plays_first
from web.app import store


def _pool():
    names = {card.name: card for card in load_cards(manifest_set_path("LEA"))}
    names.update({
        card.name: card
        for card in load_cards(manifest_set_path("SCG", include_measured=True))
    })
    return names


def _session(hand, *, theirs=(), graveyard=(), library=None):
    pool = _pool()
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "seed": 4001,
    }).json()
    session_id = created["session_id"]
    client.post(f"/api/sessions/{session_id}/join", json={"guest_name": "Joiner"})
    seat_plays_first(session_id)
    game = store.get(session_id).game
    game.enforce_mana_costs = False
    game.players[0].hand = [pool[name] for name in hand]
    game.players[0].graveyard = [pool[name] for name in graveyard]
    if library is not None:
        game.players[0].library = [pool[name] for name in library]
    placed = []
    for name in theirs:
        permanent = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(1, permanent, None)
        placed.append(permanent)
    game._recompute_continuous_effects()
    return session_id, game, placed


def _act(session_id: str, **body):
    return client.post(f"/api/sessions/{session_id}/action", json=body)


def _state(session_id: str, seat: int):
    return client.get(f"/api/sessions/{session_id}/state", params={"seat": seat}).json()


def _resolve_top(session_id: str):
    for seat in (0, 1):
        _act(session_id, seat=seat, action="pass_priority")


def _cast_rituals(session_id, game, count):
    for _ in range(count):
        assert _act(session_id, seat=0, action="cast", card_name="Dark Ritual").status_code == 200
        _resolve_top(session_id)
    assert not game.stack


def test_each_storm_copy_is_its_own_target_prompt_over_the_wire():
    session_id, game, bears = _session(
        ["Dark Ritual", "Dark Ritual", "Scattershot"],
        theirs=["Grizzly Bears", "Grizzly Bears", "Grizzly Bears"],
    )
    _cast_rituals(session_id, game, 2)
    assert _act(
        session_id, seat=0, action="cast", card_name="Scattershot",
        target_seat=1, target_permanent_id=bears[0].permanent_id,
    ).status_code == 200
    _resolve_top(session_id)  # the storm trigger
    for bear in bears[1:]:
        prompt = _state(session_id, 0)["copy_spell_target"]
        assert prompt is not None and prompt["player_seat"] == 0
        assert {c["id"] for c in prompt["candidates"]} >= {b.permanent_id for b in bears}
        assert _state(session_id, 1)["copy_spell_target"] is None
        assert _act(
            session_id, seat=0, action="copy_spell_target_confirm",
            target_permanent_id=bear.permanent_id,
        ).status_code == 200
    assert _state(session_id, 0)["copy_spell_target"] is None
    for _ in range(3):
        _resolve_top(session_id)
    assert [bear.damage_marked for bear in bears] == [1, 1, 1], game.log


def test_a_graveyard_targeting_copy_is_a_retarget_choice_over_the_wire():
    session_id, game, _ = _session(
        ["Dark Ritual", "Reaping the Graves"],
        graveyard=["Grizzly Bears", "Craw Wurm", "Forest"],
    )
    _cast_rituals(session_id, game, 1)
    # Announced on the engine (slot 0 of the graveyard: the Bears), and the
    # stack driven over the wire from here.
    assert game.queue_from_hand(0, "Reaping the Graves", target_permanent_index=0).supported
    _resolve_top(session_id)
    prompt = _state(session_id, 0)["retarget_choice"]
    assert prompt is not None
    names = [option["name"] for option in prompt["options"]]
    assert names == ["Keep the original's target", "Craw Wurm in Host's graveyard"]
    assert _act(
        session_id, seat=0, action="retarget_choice_confirm",
        target_index=prompt["options"][1]["index"],
    ).status_code == 200
    for _ in range(2):
        _resolve_top(session_id)
    assert sorted(card.name for card in game.players[0].hand) == ["Craw Wurm", "Grizzly Bears"]


def test_minds_desire_offers_its_exiled_card_free_and_the_route_casts_it():
    session_id, game, _ = _session(["Mind's Desire"], library=["Craw Wurm"] * 6)
    assert _act(session_id, seat=0, action="cast", card_name="Mind's Desire").status_code == 200
    for _ in range(2):
        _resolve_top(session_id)
    assert [card.name for card in game.players[0].exile] == ["Craw Wurm"]
    offered = [
        entry for entry in _state(session_id, 0)["castable_from_zones"]
        if entry["zone"] == "exile"
    ]
    assert len(offered) == 1
    (way,) = offered[0]["ways"]
    assert way["free"] is True and way["source"] == "Mind's Desire"
    game.enforce_mana_costs = True
    assert _act(
        session_id, seat=0, action="cast", card_name="Craw Wurm", from_zone="exile",
    ).status_code == 200
    _resolve_top(session_id)
    assert any(
        permanent.card.name == "Craw Wurm"
        for permanent in game.controlled_by(game.players[0])
    ), game.log
