"""The upkeep step's target answer is a permanent, not a battlefield slot.

The upkeep's targeted triggers are asked before the step runs: the prompt
(``get_upkeep_target_triggers`` / ``get_optional_upkeep_triggers``) offers
``valid_targets``, the seat answers, and ``resolve_upkeep(trigger_targets=…)``
reads the answer. The answer was a ``(seat, battlefield index)`` pair, and the
three readers looked the slot up **again** when the step ran — Halfdane's
base-P/T copy (``_resolve_upkeep_trigger_target``), the stamp a stack trigger
carries (Erhnam Djinn), and Vesuvan Doppelganger's re-copy. A permanent
leaving in between renumbered the slot onto its neighbour, and an index past
the end fell back to the engine's first candidate: the player's choice became
somebody else's without a word. It was unreachable only because nothing
resolves inside the web layer's upkeep-decision window.

Now each ``valid_targets`` entry carries the permanent's ``id``, the web writer
files that id, and every reader resolves it (``_upkeep_target_pick``): an id
names its permanent or nothing (CR 400.7). The census runs each reader on a
board where a bystander *before* the chosen permanent leaves between the
answer and the step, and requires the chosen one to get the effect — and,
switched back to a slot reader, requires the census to name the neighbour.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.models import Permanent
from web.app import app, store
from web.runtime import CARD_BY_NAME
from web.turn_steps import _gather_upkeep_decisions
from tests.helpers import _nosick, resolve_stack

client = TestClient(app)

READERS = ("Halfdane", "Erhnam Djinn", "Vesuvan Doppelganger")


def _put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return _nosick(permanent)


def _leave(game, permanent) -> None:
    seat = game.controller_index_of(permanent)
    game.remove_from_battlefield(permanent)
    game.players[seat].graveyard.append(permanent.card)


def _table(*, interactive: bool = False) -> Game:
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.turn = 3
    return game


def _board(set_pool, reader: str, *, interactive: bool = False):
    """*reader*'s source on seat 0 and, on seat 1, a bystander, the creature
    the seat will choose, and its neighbour — in that slot order."""
    lea, leg, arn = set_pool("LEA"), set_pool("LEG"), set_pool("ARN")
    game = _table(interactive=interactive)
    if reader == "Vesuvan Doppelganger":
        original = _put(game, 0, lea["Grizzly Bears"])
        game.players[0].hand.append(lea["Vesuvan Doppelganger"])
        game.cast_from_hand(
            0, "Vesuvan Doppelganger",
            target_player_index=0, target_permanent_index=game.battlefield_index_of(original),
        )
        resolve_stack(game)
        source = game.players[0].battlefield[-1]
        assert source.copied_from == "Grizzly Bears"
    else:
        pool = leg if reader == "Halfdane" else arn
        source = _put(game, 0, pool[reader])
    bystander = _put(game, 1, lea["Grizzly Bears"])
    # P/T unlike each other and unlike Halfdane's printed 3/3, so a copy
    # says whose it is.
    chosen = _put(game, 1, lea["Craw Wurm"])
    neighbour = _put(game, 1, lea["Air Elemental"])
    return game, source, bystander, chosen, neighbour


def _prompt(game, source) -> dict:
    offers = game.get_upkeep_target_triggers(0) + game.get_optional_upkeep_triggers(0)
    (prompt,) = [
        entry for entry in offers if entry.get("permanent_id") == source.permanent_id
    ]
    return prompt


def _upkeep(game, source, answer) -> None:
    game.resolve_upkeep(
        0,
        optional_choices={source.permanent_id: True},
        trigger_targets={source.permanent_id: answer},
    )
    resolve_stack(game)


def _who_got_it(game, reader, source, candidates) -> str | None:
    """Which of *candidates* the reader's effect reached, by name."""
    if reader == "Halfdane":
        hits = [
            p for p in candidates
            if (source.effective_power, source.effective_toughness)
            == (p.effective_power, p.effective_toughness)
        ]
    elif reader == "Erhnam Djinn":
        hits = [p for p in candidates if game._has_keyword(p, "forestwalk")]
    else:
        hits = [p for p in candidates if source.copied_from == p.card.name]
    assert len(hits) <= 1, [p.card.name for p in hits]
    return hits[0].card.name if hits else None


def _census(set_pool) -> dict:
    """Each reader, answered with the Craw Wurm, after the Bears in the slot
    before it has left: which creature the effect reached."""
    reached = {}
    for reader in READERS:
        game, source, bystander, chosen, neighbour = _board(set_pool, reader)
        prompt = _prompt(game, source)
        offered = {entry["name"]: entry["id"] for entry in prompt["valid_targets"]}
        assert offered["Craw Wurm"] == chosen.permanent_id, prompt["valid_targets"]
        _leave(game, bystander)
        _upkeep(game, source, offered["Craw Wurm"])
        reached[reader] = _who_got_it(game, reader, source, [chosen, neighbour])
    return reached


@pytest.mark.parametrize("reader", READERS)
def test_every_offered_target_carries_its_permanent_id(set_pool, reader):
    game, source, *_rest = _board(set_pool, reader)
    entries = _prompt(game, source)["valid_targets"]
    assert len(entries) >= 3
    for entry in entries:
        named = game.permanent_at(entry["seat"], entry["index"])
        assert named is not None and entry["id"] == named.permanent_id, entry


def test_the_answer_reaches_the_creature_chosen_after_its_slot_moved(set_pool):
    assert _census(set_pool) == {reader: "Craw Wurm" for reader in READERS}


def test_the_census_names_a_reader_that_looks_the_slot_up_again(set_pool, monkeypatch):
    """Backwards: the readers switched to the slot the chosen creature had
    when the prompt was built. Every one reaches the Air Elemental instead."""
    slots: dict = {}
    real_prompts = Game.get_upkeep_target_triggers, Game.get_optional_upkeep_triggers

    def recording(real):
        def offer(self, player_index):
            entries = real(self, player_index)
            for entry in entries:
                for target in entry.get("valid_targets") or ():
                    slots[target["id"]] = (target["seat"], target["index"])
            return entries
        return offer

    def by_slot(self, source, trigger_targets):
        chosen = (trigger_targets or {}).get(source.permanent_id)
        if chosen is None:
            return False, None
        return True, self.permanent_at(*slots[chosen])

    monkeypatch.setattr(Game, "get_upkeep_target_triggers", recording(real_prompts[0]))
    monkeypatch.setattr(Game, "get_optional_upkeep_triggers", recording(real_prompts[1]))
    monkeypatch.setattr(Game, "_upkeep_target_pick", by_slot)

    assert _census(set_pool) == {reader: "Air Elemental" for reader in READERS}


def test_halfdane_whose_chosen_creature_left_copies_nobody(set_pool):
    """The pick names a creature that has gone. The first candidate is not
    put in its place: the ability's only target is illegal, and CR 608.2b
    removes it."""
    game, source, bystander, chosen, neighbour = _board(set_pool, "Halfdane")
    printed = (source.effective_power, source.effective_toughness)
    _leave(game, chosen)
    _upkeep(game, source, chosen.permanent_id)
    assert (source.effective_power, source.effective_toughness) == printed
    assert any("no longer a legal one (CR 608.2b)" in line for line in game.log)


def test_vesuvan_whose_chosen_creature_left_stays_what_it_was(set_pool):
    game, source, bystander, chosen, neighbour = _board(set_pool, "Vesuvan Doppelganger")
    _leave(game, chosen)
    _upkeep(game, source, chosen.permanent_id)
    assert source.copied_from == "Grizzly Bears"
    assert "Vesuvan Doppelganger: no valid creature chosen to copy" in game.log


def test_erhnam_djinn_whose_chosen_creature_left_asks_again(set_pool):
    """A stack trigger whose pick has gone is put on the stack with nothing
    announced and chooses for itself (CR 603.3d): the seat that answered is
    asked again, from the legal list — not handed the creature in the slot."""
    game, source, bystander, chosen, neighbour = _board(
        set_pool, "Erhnam Djinn", interactive=True,
    )
    _leave(game, chosen)
    game.resolve_upkeep(
        0, defer_priority=True, trigger_targets={source.permanent_id: chosen.permanent_id},
    )
    (prompt,) = game.pending_choices
    assert [entry["name"] for entry in prompt.data["targets"]] == [
        "Grizzly Bears", "Air Elemental",
    ]
    assert not any(game._has_keyword(p, "forestwalk") for p in (bystander, neighbour))
    assert game.confirm_trigger_target(0, permanent_id=neighbour.permanent_id)
    resolve_stack(game)
    assert game._has_keyword(neighbour, "forestwalk")
    assert not game._has_keyword(bystander, "forestwalk")


def test_an_answer_written_as_a_slot_is_refused(set_pool):
    game, source, _bystander, chosen, _neighbour = _board(set_pool, "Erhnam Djinn")
    with pytest.raises(TypeError, match="permanent_id"):
        game.resolve_upkeep(0, trigger_targets={source.permanent_id: (1, 1)})


# --- the wire -------------------------------------------------------------------


def _djinn_session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 9,
    }).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.active_player_index = 0
    session.current_turn = 0
    djinn = Permanent(card=CARD_BY_NAME["erhnam djinn"])
    bears = Permanent(card=CARD_BY_NAME["grizzly bears"])
    wall = Permanent(card=CARD_BY_NAME["wall of wood"])
    giant = Permanent(card=CARD_BY_NAME["hill giant"])
    game.players[0].battlefield = [djinn]
    game.players[1].battlefield = [bears, wall, giant]
    game._settle()
    game._set_phase_and_step("beginning", "upkeep")
    assert _gather_upkeep_decisions(session, 0)
    return sid, session, game, djinn, bears, wall, giant


def _answer(sid, djinn, **target):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "resolve_optional_trigger", "card_name": "Erhnam Djinn",
        "prompt_permanent_id": djinn.permanent_id, "accept": True, **target,
    })


def test_the_wire_offers_the_id_and_files_the_answer_under_it():
    sid, session, game, djinn, bears, wall, giant = _djinn_session()
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    (pending,) = state["optional_trigger"]["pending"]
    assert [(t["name"], t["id"]) for t in pending["valid_targets"]] == [
        ("Grizzly Bears", bears.permanent_id), ("Hill Giant", giant.permanent_id),
    ]

    response = _answer(sid, djinn, target_permanent_id=giant.permanent_id)
    assert response.status_code == 200, response.text
    assert game._has_keyword(giant, "forestwalk")
    assert not game._has_keyword(bears, "forestwalk")


def test_a_seat_and_slot_body_is_filed_as_the_id_of_what_is_in_the_slot():
    """What the shipped client sends today (`target_seat`,
    `target_permanent_index`), turned into an id as the request arrives."""
    sid, session, game, djinn, bears, wall, giant = _djinn_session()
    response = _answer(
        sid, djinn, target_seat=1, target_permanent_index=game.battlefield_index_of(giant),
    )
    assert response.status_code == 200, response.text
    assert game._has_keyword(giant, "forestwalk")


def test_a_stale_id_is_a_404_and_the_prompt_stays():
    sid, session, game, djinn, bears, wall, giant = _djinn_session()
    gone = giant.permanent_id
    game.remove_from_battlefield(giant)
    response = _answer(sid, djinn, target_permanent_id=gone)
    assert response.status_code == 404, response.text
    assert session.optional_trigger_targets == {}
    assert not session.optional_trigger_resolved
    assert not game._has_keyword(bears, "forestwalk")


def test_an_id_the_prompt_did_not_offer_is_a_400():
    sid, session, game, djinn, bears, wall, giant = _djinn_session()
    response = _answer(sid, djinn, target_permanent_id=wall.permanent_id)
    assert response.status_code == 400, response.text
    assert "invalid target" in response.json()["detail"]
    assert session.optional_trigger_targets == {}
