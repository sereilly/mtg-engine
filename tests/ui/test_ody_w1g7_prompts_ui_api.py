"""ODY W1G7: what the wire carries for the prompts this group's cards arm.

The running app cannot hold a measured set's card, so each test puts an
invented card printing the same sentence into a session and drives it through
the action endpoint — the same route a browser takes.

Four things are pinned here, two of them shipped defects the Rites found:

* **An "up to" discard answered with no cards was a 400.** The engine has
  accepted the empty answer since Kinetic Augur; the action handler refused it
  ("discard_indices is required") before the engine was asked, so over the
  wire "discard any number of cards" could not be answered with none.
* **A keep and a discard owed together refused each other.** Balancing Act
  arms a keep-and-sacrifice and then a discard; the keep did not hold the
  resolution, so both prompts were queued for one seat and each answer was
  refused naming the other (ROADMAP's "two prompts that meet refuse each
  other"). The keep suspends the resolution now, so they are asked in order.
* a surveil is scry's prompt with ``destination: "graveyard"``;
* a look-and-pick says where the pick and the rest go.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import CardDefinition, Permanent
from web.app import app, store

client = TestClient(app)


def _card(name: str, type_line: str, oracle_text: str, **raw) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": type_line, **raw},
    )


def _filler(index: int) -> CardDefinition:
    return _card(f"Filler {index}", "Sorcery", "")


def _session(*, hand0=(), hand1=(), lib0=(), lib1=(), bf0=(), bf1=()):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 4242,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    for seat, (hand, library) in enumerate(((hand0, lib0), (hand1, lib1))):
        game.players[seat].hand = list(hand)
        game.players[seat].library = list(library)
        game.players[seat].graveyard = []
    for player in game.players:
        for permanent in list(game.controlled_by(player)):
            game.remove_from_battlefield(permanent)
    for seat, cards in enumerate((bf0, bf1)):
        for card in cards:
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    return sid, game


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _cast_and_resolve(sid: str, name: str, **extra):
    cast = _act(sid, seat=0, action="cast", card_name=name, **extra)
    assert cast.status_code == 200, cast.json()
    for seat in (0, 1):
        passed = _act(sid, seat=seat, action="pass_priority")
        assert passed.status_code == 200, passed.json()


# --- an "up to" discard may be answered with nothing ----------------------------

_ANY_NUMBER = _card(
    "Small Rite", "Instant",
    "Discard any number of cards. You gain 2 life for each card discarded this way.",
)


def test_a_discard_of_any_number_may_be_answered_with_none_over_the_wire():
    sid, game = _session(hand0=[_ANY_NUMBER, _filler(1), _filler(2)])
    _cast_and_resolve(sid, "Small Rite")

    prompt = _state(sid)["discard_select"]
    assert prompt is not None and prompt["up_to"] is True and prompt["count"] == 2

    answered = _act(sid, seat=0, action="discard_confirm", discard_indices=[])
    assert answered.status_code == 200, answered.json()
    assert len(game.players[0].hand) == 2
    assert game.players[0].life == 20
    assert _state(sid)["discard_select"] is None
    assert not game.stack


def test_a_discard_of_any_number_takes_the_cards_it_is_given():
    sid, game = _session(hand0=[_ANY_NUMBER, _filler(1), _filler(2)])
    _cast_and_resolve(sid, "Small Rite")
    answered = _act(sid, seat=0, action="discard_confirm", discard_indices=[1])
    assert answered.status_code == 200, answered.json()
    assert [card.name for card in game.players[0].hand] == ["Filler 1"]
    assert game.players[0].life == 22


def test_an_exact_discard_still_refuses_an_empty_answer():
    exact = _card("Plain Discard", "Sorcery", "Discard two cards.")
    sid, game = _session(hand0=[exact, _filler(1), _filler(2), _filler(3)])
    _cast_and_resolve(sid, "Plain Discard")
    assert _state(sid)["discard_select"]["up_to"] is False
    refused = _act(sid, seat=0, action="discard_confirm", discard_indices=[])
    assert refused.status_code == 400
    assert len(game.players[0].hand) == 3, "nothing moved"


# --- a keep and then a discard, one after the other ------------------------------

_LEVELLER = _card(
    "Leveller", "Sorcery",
    "Each player chooses a number of permanents they control equal to the "
    "number of permanents controlled by the player who controls the fewest, "
    "then sacrifices the rest. Each player discards cards the same way.",
)


def _relic(index: int) -> CardDefinition:
    return _card(f"Relic {index}", "Artifact", "")


def test_a_keep_and_the_discard_behind_it_are_asked_in_order_and_both_answerable():
    sid, game = _session(
        hand0=[_LEVELLER, _filler(1), _filler(2), _filler(3)], hand1=[_filler(9)],
        bf0=[_relic(1), _relic(2), _relic(3)], bf1=[_relic(9)],
    )
    _cast_and_resolve(sid, "Leveller")

    state = _state(sid)
    assert state["keep_permanents"] is not None
    assert state["discard_select"] is None, (
        "the discard waits for the keep: two prompts owed at once refuse "
        "each other's answers"
    )
    keep_id = next(iter(game.controlled_by(0))).permanent_id
    kept = _act(
        sid, seat=0, action="keep_permanents_confirm", target_permanent_ids=[keep_id],
    )
    assert kept.status_code == 200, kept.json()
    assert len(list(game.controlled_by(0))) == 1

    state = _state(sid)
    assert state["keep_permanents"] is None
    assert state["discard_select"]["count"] == 2
    discarded = _act(sid, seat=0, action="discard_confirm", discard_indices=[0, 1])
    assert discarded.status_code == 200, discarded.json()
    assert len(game.players[0].hand) == 1 and len(game.players[1].hand) == 1
    assert not game.stack and not game.pending_choices


# --- what the two library prompts say --------------------------------------------

def test_a_surveil_is_scrys_prompt_and_says_graveyard():
    surveil = _card("Deep Look", "Sorcery", "Surveil 2.")
    sid, game = _session(hand0=[surveil], lib0=[_filler(1), _filler(2), _filler(3)])
    _cast_and_resolve(sid, "Deep Look")
    prompt = _state(sid)["scry"]
    assert prompt["destination"] == "graveyard"
    assert [card["name"] for card in prompt["cards"]] == ["Filler 1", "Filler 2"]
    assert _state(sid, seat=1)["scry"] is None, "a look is its looker's alone"

    answered = _act(sid, seat=0, action="scry_confirm", card_order=[1, 0], bottom_count=1)
    assert answered.status_code == 200, answered.json()
    assert [card.name for card in game.players[0].library] == ["Filler 2", "Filler 3"]
    assert "Filler 1" in [card.name for card in game.players[0].graveyard]


def test_a_scry_says_bottom():
    scry = _card("Shallow Look", "Sorcery", "Scry 1.")
    sid, _game = _session(hand0=[scry], lib0=[_filler(1), _filler(2)])
    _cast_and_resolve(sid, "Shallow Look")
    assert _state(sid)["scry"]["destination"] == "bottom"


def test_a_revealed_pick_out_of_another_library_says_where_the_cards_go():
    shell = _card(
        "Shell Game", "Sorcery",
        "Target player reveals the top four cards of their library. You choose "
        "two of those cards and put them into that player's graveyard. Put the "
        "rest on top of their library in any order.",
    )
    sid, game = _session(hand0=[shell], lib1=[_filler(i) for i in range(1, 6)])
    _cast_and_resolve(sid, "Shell Game", target_seat=1)

    prompt = _state(sid)["look_top_pick"]
    assert (prompt["caster_seat"], prompt["pile_seat"]) == (0, 1)
    assert prompt["pick_destination"] == "graveyard"
    assert prompt["rest_destination"] == "library_top"
    assert prompt["remaining"] == 2
    assert len(prompt["cards"]) == 4

    for _ in range(2):
        picked = _act(sid, seat=0, action="look_top_pick_confirm", hand_index=0)
        assert picked.status_code == 200, picked.json()
    assert [card.name for card in game.players[1].graveyard] == ["Filler 1", "Filler 2"]
    order = _state(sid)["reorder_library"]
    assert order is not None, "the rest go back in an order the caster chooses"
