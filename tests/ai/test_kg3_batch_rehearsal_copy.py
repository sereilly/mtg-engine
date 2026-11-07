"""A rehearsal copy taken while an event is putting permanents onto the
battlefield is not part of that event (CR 603.6a, ``entering_together``).

An event's newcomers are held until the block that opened it closes; the copy
of the table (``ai_scratch_copy.scratch_copy``) carries the open batch with it,
and nothing on the copy will ever close it — so a permanent the rehearsal put
onto the copy's battlefield joined the original's event and never arrived.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_scratch_copy import scratch_copy
from engine.card_loader import load_catalog
from engine.models import Permanent

_CARDS = {card.name: card for card in load_catalog()}


def test_a_copy_taken_inside_an_event_enters_its_own_permanents():
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    with game.entering_together():
        game._put_permanent_onto_battlefield(
            0, Permanent(card=_CARDS["Grizzly Bears"]), None
        )
        assert not list(game.controlled_by(0)), "held for the event"
        copy = scratch_copy(game)
        copy._put_permanent_onto_battlefield(
            0, Permanent(card=_CARDS["Llanowar Elves"]), None
        )
        assert [p.card.name for p in copy.controlled_by(0)] == ["Llanowar Elves"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
