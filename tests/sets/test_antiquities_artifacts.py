"""Per-card tests for Antiquities' artifacts.

See tests/sets/README.md for the convention; ROADMAP's ATQ rounds for why each
of these was blocked.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


# ---------------------------------------------------------------------------
# Urza's Chalice (round 3) — "whenever a player casts an artifact spell"
# ---------------------------------------------------------------------------


def test_urzas_chalice_triggers_on_an_artifact_spell(set_pool):
    pool = set_pool("ATQ")
    chalice = Permanent(card=pool["Urza's Chalice"])
    p1 = PlayerState(name="P1", battlefield=[chalice], hand=[pool["Ornithopter"]])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Ornithopter")

    assert any("Urza's Chalice" in entry for entry in game.log), game.log


def test_urzas_chalice_ignores_a_nonartifact_spell(set_pool):
    """The narrowing under load. Before the `cast_type` row existed the line
    refused outright, so the card was unsupported rather than over-firing —
    but the dispatcher already read a narrowing key nothing emitted, and a
    bare `spell_cast` row would have fired this trigger on every spell."""
    pool = set_pool("ATQ")
    chalice = Permanent(card=pool["Urza's Chalice"])
    p1 = PlayerState(name="P1", battlefield=[chalice], hand=[pool["Detonate"]])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Detonate")

    assert not any("Urza's Chalice" in entry for entry in game.log), game.log


def test_urzas_chalice_compiles_its_optional_payment(set_pool):
    program = compile_card_oracle(set_pool("ATQ")["Urza's Chalice"])
    (trigger,) = program.triggered_abilities

    assert trigger.supported
    assert trigger.condition.kind == "spell_cast"
    assert trigger.condition.payload["cast_type"] == "artifact"
    assert trigger.instruction.kind == "may"


# ---------------------------------------------------------------------------
# Tablet of Epityr (round 3) — "whenever an artifact you control is put into a
# graveyard from the battlefield"
# ---------------------------------------------------------------------------


def _dies(game, seat, permanent):
    game._permanent_to_graveyard(game.players[seat], permanent)


def test_tablet_of_epityr_triggers_when_your_artifact_dies(set_pool):
    pool = set_pool("ATQ")
    tablet = Permanent(card=pool["Tablet of Epityr"])
    doomed = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[tablet, doomed])
    game = Game(players=[p1, PlayerState(name="P2")])

    _dies(game, 0, doomed)

    # CR 603.3: a trigger goes on the stack and resolves later, so the stack is
    # what the announcement is observable as — not a log line, which only
    # appears once it resolves.
    assert [item.card.name for item in game.stack] == ["Tablet of Epityr"]


def test_tablet_of_epityr_ignores_an_opponents_artifact(set_pool):
    """"an artifact **you control**" is relative to the controller of the
    triggered ability (CR 109.5), not to the dying permanent's controller —
    which is why the dispatcher passes the observer's seat to subject_matches
    rather than the dead permanent's."""
    pool = set_pool("ATQ")
    tablet = Permanent(card=pool["Tablet of Epityr"])
    theirs = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[tablet])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    _dies(game, 1, theirs)

    assert game.stack == []


def test_tablet_of_epityr_ignores_a_dying_creature(set_pool):
    """The type half of the same narrowing."""
    pool = set_pool("ATQ")
    tablet = Permanent(card=pool["Tablet of Epityr"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[tablet, druid])
    game = Game(players=[p1, PlayerState(name="P2")])

    _dies(game, 0, druid)

    assert [item.card.name for item in game.stack] == []
