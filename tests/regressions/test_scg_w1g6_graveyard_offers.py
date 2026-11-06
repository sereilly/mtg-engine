"""A graveyard trigger whose return is an offer ("you may return this card
from your graveyard …") fires from the graveyard — and only for what it names.

Measured on the Scourge base: CR 113.6m's zone (``functions_from``) is stamped
by the lowering on the return itself, and the graveyard scans
(``events.graveyard_trigger_events``, the upkeep and end-step scans beside it)
ask the trigger's **top** instruction. Wrapped in a ``may``, the key was one
level down and the trigger was never collected: **Squee, Goblin Nabob**
(Mercadian Masques, shipped) never once returned to its owner's hand, and
Bladewing's Thrall never left its graveyard, both compiling supported with
every instrument quiet. ``tests/engine/test_graveyard_triggers.py`` reads the
same top-level key, so it never saw either.

The second half is what the fix exposed: the graveyard scan asked no event
filter. Collected under a narrowed event ("when **a Dragon** enters") with no
narrowing, the Thrall would have come back for every permanent that entered.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.events import EVENT_FILTERS, GRAVEYARD_EVENT_FILTERS
from engine.models import Permanent
from tests.helpers import resolve_stack


def _pool():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _game(graveyard, *, interactive=()):
    me = PlayerState(name="Me", graveyard=list(graveyard))
    game = Game(players=[me, PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def test_squee_goblin_nabob_returns_to_hand_at_its_owners_upkeep():
    """"At the beginning of your upkeep, you may return this card from your
    graveyard to your hand." Asked and accepted, it is in the hand; a seat
    nobody asks takes the gift."""
    squee = _pool()["Squee, Goblin Nabob"]
    asked = _game([squee], interactive={0})
    asked.start_turn(0)
    assert [item.card.name for item in asked.stack] == ["Squee, Goblin Nabob"]
    asked.resolve_top_of_stack()
    assert asked.confirm_optional_pay(0, "Squee, Goblin Nabob", accept=True)
    resolve_stack(asked)
    assert asked.players[0].hand == [squee]
    assert not asked.players[0].graveyard

    headless = _game([squee])
    headless.start_turn(0)
    resolve_stack(headless)
    headless.auto_resolve_pending_choices()
    assert headless.players[0].hand == [squee]


def test_squee_does_not_return_at_an_opponents_upkeep():
    """"Your upkeep": the owner's (CR 108.4a), never the active opponent's."""
    squee = _pool()["Squee, Goblin Nabob"]
    game = _game([squee])
    game.start_turn(1)
    assert not game.stack
    assert game.players[0].graveyard == [squee]


def test_a_narrowed_event_with_no_graveyard_reading_fires_nothing_from_a_graveyard():
    """Fail-closed: every event kind narrowed for a permanent observer and
    read for none in a graveyard is a kind a graveyard card cannot fire on —
    and the one family that has a graveyard reading (the subject-led events,
    "when **a Dragon** enters") is registered, which is what Bladewing's Thrall
    and the five Scourge Dragon Auras ride."""
    assert "matching_permanent_enters" in GRAVEYARD_EVENT_FILTERS
    assert set(GRAVEYARD_EVENT_FILTERS) <= set(EVENT_FILTERS)

    pool = _pool()
    game = _game([pool["Bladewing's Thrall"]])
    game.start_turn(0)
    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Grizzly Bears"]), None)
    assert not game.stack, "a non-Dragon entering fired the Thrall from a graveyard"
    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Shivan Dragon"]), None)
    assert [item.card.name for item in game.stack] == ["Bladewing's Thrall"]
