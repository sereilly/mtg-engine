"""CR 603.3 — every ability whose trigger condition is met triggers.

Two things are pinned here.

The first is that a permanent with more than one matching trigger fires all of
them. The scan used to stop at the first match per permanent, so a card with
two upkeep triggers would silently fire only one. No card in the current pool
has that shape, which is exactly why it needs a synthetic test: the bug was
invisible and would have surfaced as a mystery when the first such card
arrived.

The second is the event bus (``engine/events.py``): announcing an event must
find matching triggers wherever they are, without the caller knowing which
cards exist.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.events import Event, collect, emit
from engine.models import CardDefinition, Permanent
from engine.trigger_utils import iter_triggered_abilities


def _card(name: str, oracle_text: str, type_line: str = "Creature — Test") -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = "2", "2"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=oracle_text,
        colors=(), color_identity=(), keywords=(), produced_mana=(), raw=raw,
        power=raw.get("power"), toughness=raw.get("toughness"),
    )


def _game(*permanents: Permanent) -> tuple[Game, PlayerState, PlayerState]:
    owner = PlayerState(name="P1", battlefield=list(permanents), life=20)
    opponent = PlayerState(name="P2", life=20)
    game = Game(players=[owner, opponent])
    game.enforce_mana_costs = False
    return game, owner, opponent


@pytest.mark.cr("603.3")
def test_a_permanent_with_two_matching_triggers_fires_both():
    twice = Permanent(card=_card(
        "Twice-Triggered Thing",
        "At the beginning of your upkeep, this creature deals 1 damage to you.\n"
        "At the beginning of your upkeep, this creature deals 2 damage to you.",
    ))
    game, owner, _ = _game(twice)

    matches = list(
        iter_triggered_abilities(game, condition_kinds={"upkeep_self"})
    )
    assert len(matches) == 2, "both upkeep triggers must be found, not just the first"


@pytest.mark.cr("603.3")
def test_first_match_only_is_opt_in():
    """The capped scan still exists for presence checks — it just is not the
    default any more."""
    twice = Permanent(card=_card(
        "Twice-Triggered Thing",
        "At the beginning of your upkeep, this creature deals 1 damage to you.\n"
        "At the beginning of your upkeep, this creature deals 2 damage to you.",
    ))
    game, _, _ = _game(twice)

    capped = list(
        iter_triggered_abilities(
            game, condition_kinds={"upkeep_self"}, first_match_only=True
        )
    )
    assert len(capped) == 1


@pytest.mark.cr("603.3")
def test_emit_puts_every_matching_trigger_on_the_stack():
    one = Permanent(card=_card(
        "Pinger", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    two = Permanent(card=_card(
        "Other Pinger", "At the beginning of your upkeep, this creature deals 2 damage to you."
    ))
    game, _, _ = _game(one, two)

    fired = emit(game, "upkeep_self")
    assert fired == 2
    assert len(game.stack) == 2


@pytest.mark.cr("603.3")
def test_emit_finds_nothing_when_no_trigger_matches():
    plain = Permanent(card=_card("Bear", ""))
    game, _, _ = _game(plain)
    assert emit(game, "upkeep_self") == 0
    assert game.stack == []


@pytest.mark.cr("603.2")
def test_collect_reports_the_controller_of_each_trigger():
    """Trigger events carry the controller index, which is what
    ``_enqueue_triggered_batch`` orders by (CR 603.3b, APNAP)."""
    mine = Permanent(card=_card(
        "Mine", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    theirs = Permanent(card=_card(
        "Theirs", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    owner = PlayerState(name="P1", battlefield=[mine], life=20)
    opponent = PlayerState(name="P2", battlefield=[theirs], life=20)
    game = Game(players=[owner, opponent])

    events = collect(game, Event("upkeep_self"))
    assert {event["controller_index"] for event in events} == {0, 1}


@pytest.mark.cr("603.3")
def test_emit_can_be_scoped_to_one_players_permanents():
    mine = Permanent(card=_card(
        "Mine", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    theirs = Permanent(card=_card(
        "Theirs", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    owner = PlayerState(name="P1", battlefield=[mine], life=20)
    opponent = PlayerState(name="P2", battlefield=[theirs], life=20)
    game = Game(players=[owner, opponent])

    events = collect(game, Event("upkeep_self", players=[owner]))
    assert [event["source_permanent"] for event in events] == [mine]


@pytest.mark.cr("603.2")
def test_event_payload_reaches_the_trigger_as_context():
    pinger = Permanent(card=_card(
        "Pinger", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    game, _, _ = _game(pinger)

    events = collect(game, Event("upkeep_self", payload={"amount": 7}))
    assert events[0]["trigger_context"] == {"amount": 7}
