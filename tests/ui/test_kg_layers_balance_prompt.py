"""Balance's prompt on the wire: what each round offers is what the engine
counts and accepts, through the layers.

``web/prompt_board.py`` listed Balance's lands and creatures by
``card.primary_type`` while the engine counted them through CR 613 layer 4, and
described each by its printed card. On a board with an animated Mishra's
Factory and an Opalescence enchantment that meant the creature list was
*empty* while the plan owed a creature — a prompt nobody could answer — and the
Factory was offered only as a land, drawn as a plain land.

The lists are ``Game.balance_candidates`` now, one round at a time (lands, then
cards in hand, then creatures, each counted as it starts), and each permanent
is described by ``PromptContext.serialize_permanent``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack
from web.app import app, store

client = TestClient(app)


@pytest.fixture(scope="module")
def by_name():
    return {card.name: card for card in load_catalog()}


def _session(by_name):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 5151,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False

    def put(name, seat):
        perm = _nosick(Permanent(card=by_name[name]))
        game._put_permanent_onto_battlefield(seat, perm, None)
        _nosick(perm)
        return perm

    game.players[0].battlefield = []
    game.players[1].battlefield = []
    factory = put("Mishra's Factory", 0)
    put("Plains", 0)
    put("Plains", 0)
    put("Opalescence", 0)
    crusade = put("Crusade", 0)
    put("Island", 1)
    put("Grizzly Bears", 1)
    game._recompute_continuous_effects()
    game.players[0].hand = [by_name["Balance"]]
    game.players[1].hand = []
    session.current_turn = 0
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"

    result = game.activate_permanent_ability(
        0, "Mishra's Factory",
        permanent_index=game.battlefield_index_of(factory), ability_index=1,
    )
    assert result.supported, result
    resolve_stack(game)
    game._recompute_continuous_effects()
    assert factory.is_creature and factory.has_type("land")
    assert crusade.is_creature
    assert factory.card.primary_type == "land" and crusade.card.primary_type == "enchantment"

    game.cast_from_hand(0, "Balance")
    return sid, session, game, factory, crusade


def _prompt(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()["balance_select"]


def test_the_first_round_offers_every_land_the_engine_counts(by_name):
    """Three lands against one: two to give up, chosen among the Factory and
    both Plains — and the Factory is described as what it is now."""
    sid, _session_, game, factory, _crusade = _session(by_name)

    info = _prompt(sid)
    # Every count the prompt owes can be answered from what it offers. On
    # the base tree it owed a creature and listed none: the Factory was only
    # a land to it and the Crusade only an enchantment.
    assert len(info["lands"]) >= info["lands_to_sacrifice"]
    assert len(info["creatures"]) >= info["creatures_to_sacrifice"]
    assert sorted(entry["name"] for entry in info["lands"]) == ["Mishra's Factory", "Plains", "Plains"]
    assert info["lands_to_sacrifice"] == 2
    shown = next(entry for entry in info["lands"] if entry["name"] == "Mishra's Factory")
    assert "Creature" in shown["type"] and "Land" in shown["type"], shown["type"]

    assert info["stage"] == "lands"
    assert (info["creatures_to_sacrifice"], info["cards_to_discard"]) == (0, 0)
    assert info["creatures"] == []
    offered = {entry["id"]: entry for entry in info["lands"]}
    assert set(offered) == {perm.permanent_id for _slot, perm in game.balance_candidates(0, "lands")}
    assert offered[factory.permanent_id] == shown


def test_the_last_round_offers_the_creatures_the_first_one_left(by_name):
    """Keep the Factory, give up both Plains; then the creatures are counted
    on that board — the Factory and the Opalescence'd Crusade against one
    Bear — and both are offered, described as creatures."""
    sid, _session_, game, factory, crusade = _session(by_name)
    plains_slots = [entry["index"] for entry in _prompt(sid)["lands"] if entry["name"] == "Plains"]

    answered = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "balance_confirm", "land_indices": plains_slots},
    )
    assert answered.status_code == 200, answered.text
    assert not any(p.card.name == "Plains" for p in game.controlled_by(0))

    info = _prompt(sid)
    assert info["stage"] == "creatures"
    assert (info["lands_to_sacrifice"], info["creatures_to_sacrifice"]) == (0, 1)
    assert info["lands"] == []
    offered = {entry["id"]: entry for entry in info["creatures"]}
    assert set(offered) == {factory.permanent_id, crusade.permanent_id}
    assert "Creature" in offered[crusade.permanent_id]["type"]

    crusade_slot = offered[crusade.permanent_id]["index"]
    answered = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "balance_confirm", "creature_indices": [crusade_slot]},
    )
    assert answered.status_code == 200, answered.text
    assert _prompt(sid) is None
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Mishra's Factory", "Opalescence"]
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Grizzly Bears", "Island"]


def test_a_round_refuses_a_permanent_it_did_not_offer(by_name):
    """A slot outside the round's list is refused and the prompt stays owed:
    the creature-round answer is not accepted during the land round."""
    sid, _session_, game, _factory, crusade = _session(by_name)
    crusade_slot = game.battlefield_index_of(crusade)

    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "balance_confirm", "land_indices": [crusade_slot, 0]},
    )
    assert refused.status_code == 400
    assert _prompt(sid)["stage"] == "lands"
    assert game.is_on_battlefield(crusade)
