"""Onslaught's creature-type prompts, as the client words them (W2G3).

Three things wave 1 put on the wire that the client did not show:

* ``chosen_so_far`` on an each-player ``creature_type_choice`` round (Harsh
  Mercy, Patriarch's Bidding) — CR 101.4b, a player knows the choices made
  before theirs;
* ``word_role`` ("replaced" / "replacement") on Artificial Evolution's two
  questions, which read the same as each other — and as Extinction's sweep,
  whose sentence the client printed for every card;
* Callous Oppressor's entry prompt, armed on the **opponent's** seat, which
  asked them "as it enters, choose a creature type" about a creature that is
  not theirs. The server now names the permanent's controller when the seat
  asked is someone else (``controller_seat`` / ``controller_name``).

Each payload here is the one the server really sends, and the wording is the
real client function's (``creatureTypeChoiceWording``,
``enterChoiceForAnotherText``), run in node.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

from tests.helpers import run_app_js

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _table(set_pool, *, hand, mine=(), theirs=(), pool):
    """Two people; seat 0 holds *hand* with *pool* floating in its main phase,
    the battlefields as named (Onslaught cards, untapped)."""
    sid = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 51029,
    }).json()["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    ons = set_pool("ONS")
    game.players[0].hand = [ons[name] for name in hand]
    game.players[1].hand = []
    game.players[0].battlefield = [Permanent(card=ons[name]) for name in mine]
    game.players[1].battlefield = [Permanent(card=ons[name]) for name in theirs]
    game.players[0].mana_pool.update(pool)
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.priority_player_index = 0
    return sid, game


def _resolve_top(sid):
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200


def _wording(info: dict, *, seat: int) -> dict:
    return run_app_js(
        ["creatureTypeChoiceWording"],
        "return creatureTypeChoiceWording(INPUT.info);",
        {"info": info},
        prelude=f"let seat = {seat};",
    )


@needs_node
def test_w2g3_each_player_round_shows_the_words_chosen_before(set_pool):
    sid, game = _table(
        set_pool, hand=["Harsh Mercy"], mine=["Elvish Warrior"],
        theirs=["Goblin Sledder", "Glory Seeker"], pool={"W": 3},
    )
    assert _act(sid, seat=0, action="cast", card_name="Harsh Mercy").status_code == 200
    _resolve_top(sid)
    first = _state(sid, 0)["creature_type_choice"]
    assert first["chosen_so_far"] == []
    assert "you are first" in _wording(first, seat=0)["body"]
    assert _act(sid, seat=0, action="creature_type_choice_confirm",
                creature_type="elf").status_code == 200

    second = _state(sid, 1)["creature_type_choice"]
    assert second["player_index"] == 1 and second["chosen_so_far"] == ["elf"]
    words = _wording(second, seat=1)
    assert "chosen so far: Elf" in words["body"]
    assert "destroyed" not in words["body"], "Extinction's sentence is not every card's"

    # The other direction: a word nobody controls, and what that sweeps.
    assert _act(sid, seat=1, action="creature_type_choice_confirm",
                creature_type="soldier").status_code == 200
    names = [p.card.name for p in game.players[1].battlefield]
    assert names == ["Glory Seeker"]
    assert [p.card.name for p in game.players[0].battlefield] == ["Elvish Warrior"]


@needs_node
def test_w2g3_artificial_evolution_asks_two_different_questions(set_pool):
    sid, game = _table(
        set_pool, hand=["Artificial Evolution"], theirs=["Goblin Sledder"], pool={"U": 1},
    )
    sledder = game.players[1].battlefield[0]
    sent = _act(sid, seat=0, action="cast", card_name="Artificial Evolution",
                target_permanent_id=sledder.permanent_id)
    assert sent.status_code == 200, sent.text
    _resolve_top(sid)
    first = _state(sid, 0)["creature_type_choice"]
    assert first["word_role"] == "replaced"
    first_words = _wording(first, seat=0)
    assert first_words["title"] == "Choose the creature type to replace"
    assert _act(sid, seat=0, action="creature_type_choice_confirm",
                creature_type="goblin").status_code == 200

    second = _state(sid, 0)["creature_type_choice"]
    assert second["word_role"] == "replacement"
    assert set(second["excluded"]) == {"wall", "goblin"}
    assert "goblin" not in second["creature_types"]
    second_words = _wording(second, seat=0)
    assert second_words["title"] == "Choose the replacement creature type"
    assert second_words["title"] != first_words["title"]
    assert "can't be" in second_words["body"] and "Goblin" in second_words["body"]
    assert _act(sid, seat=0, action="creature_type_choice_confirm",
                creature_type="elf").status_code == 200
    assert sledder.has_type("elf") and not sledder.has_type("goblin")


@needs_node
def test_w2g3_callous_oppressor_tells_the_opponent_whose_creature_it_is(set_pool):
    sid, game = _table(
        set_pool, hand=["Callous Oppressor"], theirs=["Glory Seeker"], pool={"U": 3},
    )
    assert _act(sid, seat=0, action="cast", card_name="Callous Oppressor").status_code == 200
    _resolve_top(sid)
    assert _state(sid, 0)["enter_choice"] is None, "the controller is not asked"
    info = _state(sid, 1)["enter_choice"]
    assert info["needs_creature_type"]
    assert info["controller_seat"] == 0 and info["controller_name"] == game.players[0].name
    text = run_app_js(
        ["enterChoiceForAnotherText"],
        "return [enterChoiceForAnotherText(INPUT.info, 'a creature type'),"
        " enterChoiceForAnotherText({...INPUT.info, controller_seat: undefined}, 'x')];",
        {"info": info},
        prelude="let seat = 1;",
    )
    assert text[0].startswith(f"{game.players[0].name}'s Callous Oppressor")
    assert "you choose a creature type" in text[0]
    assert text[1] == "", "a prompt about the chooser's own permanent keeps its wording"
    sent = _act(sid, seat=1, action="enter_choice_confirm", creature_type="soldier")
    assert sent.status_code == 200, sent.text
    oppressor = next(p for p in game.players[0].battlefield if p.card.name == "Callous Oppressor")
    assert oppressor.metadata["chosen_creature_type"] == "soldier"


def test_w2g3_a_prompt_its_own_controller_answers_names_no_controller(set_pool):
    """Every other entry choice is unchanged: where the permanent's own
    controller is the seat asked ("As this enchantment enters, choose a
    creature type"), the payload carries no ``controller_seat``."""
    sid, game = _table(set_pool, hand=[], pool={})
    entering = Permanent(card=set_pool("ONS")["Glory Seeker"])
    game.players[0].battlefield.append(entering)
    game.interactive_seats = {0, 1}
    game.arm_pending_choice(
        "enter_choice", 0, card_name="Glory Seeker", permanent=entering,
        needs_color=False, opponents=[], default_seat=None, default_color=None,
        needs_creature_type=True, default_creature_type="elf",
    )
    info = _state(sid, 0)["enter_choice"]
    assert info["needs_creature_type"] and "controller_seat" not in info
