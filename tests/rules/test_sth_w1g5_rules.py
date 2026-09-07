"""Stronghold wave 1, group 5: the CR sections behind the cards, not the cards.

Three rules the round leaned on and one of which it had to build. Each is about
a mechanism rather than a printing, so a second card reaching the same seam is
covered by construction — which is the line SET_PLAYBOOK.md draws between
`tests/sets/` and here.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.named_counters import counters_on

_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
_STH = {c.name: c for c in load_cards(manifest_set_path("STH", include_measured=True))}


def _game(*players: PlayerState, costs: bool = False) -> Game:
    game = Game(players=list(players))
    game.enforce_mana_costs = costs
    return game


@pytest.mark.cr("614.5", "121.2")
def test_614_5_a_declined_draw_replacement_is_not_offered_the_draw_it_leaves():
    """"A replacement effect doesn't invoke itself repeatedly; it gets only one
    opportunity to affect an event or any modified events that may replace that
    event."

    An *optional* replacement makes this load-bearing rather than academic. The
    interceptor consumes the draw either way — that is what lets one resolver
    finish both answers — so declining has to put the draw back through the
    same seam. Without CR 614.5's exclusion that remade draw meets the same
    permanent, is offered the same choice, and the game never leaves the draw
    step.

    Two sources make the rule visible in the other direction too: a *second*
    copy is a different effect and still gets its own opportunity, which is why
    the exclusion names the permanent rather than the wording.
    """
    first = Permanent(card=_STH["Pursuit of Knowledge"])
    second = Permanent(card=_STH["Pursuit of Knowledge"])
    game = _game(
        PlayerState(name="P1", battlefield=[first, second],
                    library=[_LEA["Forest"]] * 30, life=20),
        PlayerState(name="P2", library=[_LEA["Island"]] * 30, life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.start_next_turn()
    game.start_next_turn()
    game.resolve_stack()

    # The first copy asks. Declining hands the draw back to the seam, where the
    # *other* copy gets its own opportunity — and the first one does not.
    assert len(game.pending_draw_becomes_counters) == 1, game.log
    assert game.confirm_draw_becomes_counter(0, take_the_counter=False)
    assert len(game.pending_draw_becomes_counters) == 1, game.log
    assert game.confirm_draw_becomes_counter(0, take_the_counter=False)

    # Two offers for one draw, then the card is drawn. A third offer would be
    # one of the two copies invoking itself again.
    assert not game.pending_draw_becomes_counters, game.log
    assert len(game.players[0].hand) == 1, game.log
    assert counters_on(first, "study") == 0
    assert counters_on(second, "study") == 0


@pytest.mark.cr("305.1")
def test_305_1_a_land_put_onto_the_battlefield_was_not_played():
    """"Playing a land is a special action; it doesn't use the stack … the
    player simply puts the land onto the battlefield."

    So a land *entering* and a land being *played* are two different events, and
    a card watching one must not fire on the other. The engine announces them
    separately — `land_enters` from the entry transition and `land_played` from
    the land-drop path — and this is the guard that keeps the second from being
    read as the first.

    Horn of Greed is the card that made the unnarrowed seat reading reachable at
    all; the rule it exercises is about the event, not about the card.
    """
    horn = Permanent(card=_STH["Horn of Greed"])
    game = _game(
        PlayerState(name="P1", battlefield=[horn],
                    library=[_LEA["Mountain"]] * 8, life=20),
        PlayerState(name="P2", library=[_LEA["Swamp"]] * 8, life=20),
        costs=True,
    )
    game.start_turn(0)
    game.resolve_stack()
    before = len(game.players[0].hand)

    # Put onto the battlefield by an effect rather than played from a hand.
    game._put_permanent_onto_battlefield(
        0, Permanent(card=_LEA["Forest"]), None, from_zone="library",
    )
    game.resolve_stack()

    assert any(p.card.name == "Forest" for p in game.players[0].battlefield), game.log
    assert len(game.players[0].hand) == before, game.log
    assert game.lands_played_this_turn.get(0, 0) == 0, game.log


@pytest.mark.cr("701.9a", "109.5")
def test_701_9a_both_discard_seams_announce_the_same_event():
    """"To discard a card, move it from its owner's hand to that player's
    graveyard."

    One action, and this engine reaches it two ways — a discard taken from a
    player (`Game._discard_card`) and one they choose (`_resolve_one_discard`).
    A watcher announced on one path only fires for half the cards that discard,
    which is why both go through `announce_discard`.

    Asked here with the **opponent-scoped** reading, which is the one the seat
    comparison can get backwards: CR 109.5 makes "you" the ability's controller,
    so "an opponent" is any other seat and the board is walked in full rather
    than filtered to the discarding player's own permanents.
    """
    megrim = Permanent(card=_STH["Megrim"])
    game = _game(
        PlayerState(name="P1", battlefield=[megrim], life=20),
        PlayerState(name="P2", hand=[_LEA["Island"], _LEA["Swamp"]], life=20),
    )
    game.start_turn(0)

    # The taken discard.
    game._discard_card(game.players[1], game.players[1].hand.pop(0))
    game.resolve_stack()
    assert game.players[1].life == 18, game.log

    # And the chosen one, through the prompt seat 1 owes.
    game.arm_pending_choice("discard", 1, count=1, filter={})
    game.auto_resolve_choice(game.pending_choices[0])
    game.resolve_stack()
    assert game.players[1].life == 16, game.log
    assert not game.players[1].hand, game.log
