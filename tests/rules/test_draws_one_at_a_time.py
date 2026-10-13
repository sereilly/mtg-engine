"""CR 121.2 — "Cards may only be drawn one at a time. If a player is
instructed to draw multiple cards, that player performs that many individual
card draws."

Each draw is its own event. CR 616.1 runs over it to the end — 616.1f: the
chosen effect is applied and the process repeats over what still applies —
before the next draw exists, and CR 614.5 gives a replacement one opportunity
per event, the modified events that replace it included.

The engine keeps the first by parking a draw behind one that is still waiting
on its player (``Game._draw_prompt_open``) and the second by carrying what an
event has been through on the draws made of it (``replacements.draws_behind``).
The pool-wide census is ``tests/engine/test_draw_replacement_pair_census.py``;
these are the rules, one scenario each.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import _mk_card


def _land(name):
    return _mk_card(name=name, type_line="Land")


def _spell(name):
    return _mk_card(name=name, type_line="Artifact")


def _game(*cards, library=None, interactive=True):
    permanents = [Permanent(card=card) for card in cards]
    me = PlayerState(
        name="P0", battlefield=list(permanents), life=20,
        library=library or [
            _land("L1"), _spell("S1"), _land("L2"), _spell("S2"),
            _land("L3"), _spell("S3"),
        ],
    )
    game = Game(players=[me, PlayerState(name="P1", life=20)])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    return game, me, permanents


def _apply_first(game, label: str) -> None:
    order = game.pending_choice_of("effect_order")
    assert order is not None, [c.kind for c in game.pending_choices]
    assert game.resolve_pending_choice(
        "effect_order", 0, option_index=order.data["options"].index(label),
    )


def _owed(game) -> list[str]:
    return sorted(
        choice.kind for spec, choice in game.iter_pending_prompts()
        if spec.holds_priority and spec.open_for(game, choice)
    )


@pytest.mark.cr("121.2", "616.1f")
def test_121_2_the_next_draw_does_not_begin_while_one_owes_a_decision(set_pool):
    """Abundance declined hands its draw back to the seam, where Pursuit of
    Knowledge has its own opportunity (CR 616.1f). The draw *behind* waits for
    that answer: it used to be put to CR 616.1e at once, and the two prompts
    each refused the other's answer."""
    game, me, (_abundance, pursuit) = _game(
        set_pool("USG")["Abundance"], set_pool("STH")["Pursuit of Knowledge"],
    )

    game._draw_with_replacements(me, 2)

    _apply_first(game, "Abundance")
    assert game.confirm_reveal_until_kind_draw(0, 2)  # "Draw a card"
    assert _owed(game) == ["draw_becomes_counter"]
    assert [entry["count"] for entry in game.parked_draws] == [1]
    assert me.hand == [], "nothing is drawn while the offer is open"

    assert game.confirm_draw_becomes_counter(0, take_the_counter=False)
    assert [card.name for card in me.hand] == ["L1"]
    # …and only now the second draw, with both replacements back in contention.
    assert _owed(game) == ["effect_order"]
    assert not game.parked_draws
    _apply_first(game, "Pursuit of Knowledge")
    assert game.confirm_draw_becomes_counter(0, take_the_counter=True)

    assert _owed(game) == []
    assert counters_on(pursuit, "study") == 1
    assert [card.name for card in me.hand] == ["L1"]


@pytest.mark.cr("121.2")
def test_121_2_a_look_at_the_top_cards_is_not_drawn_from_underneath(set_pool):
    """Aladdin's Lamp looks at the top two cards for the first draw. The draw
    behind it used to be offered at once, and a seat that took *that* card
    first drew one of the two the Lamp was showing — the Lamp then chose from
    a library that had moved."""
    game, me, _permanents = _game(set_pool("STH")["Pursuit of Knowledge"])
    game.lamp_draw_replacements[0] = 2

    game._draw_with_replacements(me, 2)

    _apply_first(game, "Pursuit of Knowledge")
    assert game.confirm_draw_becomes_counter(0, take_the_counter=False)
    # The declined draw is the Lamp's now; the second draw waits behind it.
    assert _owed(game) == ["lamp_draw"]
    assert game.pending_lamp_draw["card_names"] == ["L1", "S1"]
    assert [entry["count"] for entry in game.parked_draws] == [1]

    assert game.confirm_lamp_draw(0, 1)
    assert [card.name for card in me.hand] == ["S1"]
    # Released: the Lamp is spent, so Pursuit alone asks about the second.
    assert _owed(game) == ["draw_becomes_counter"]
    assert game.confirm_draw_becomes_counter(0, take_the_counter=False)
    assert len(me.hand) == 2 and not game.parked_draws


@pytest.mark.cr("614.5")
def test_614_5_a_doubler_has_one_opportunity_at_the_draws_it_made(set_pool):
    """"…draw two cards instead" makes two draws of one, and both are that
    event modified: the doubler does not apply to either again, whatever takes
    the first of them. Pursuit of Knowledge is offered each of the two — and
    no third."""
    game, me, (_insight, pursuit) = _game(
        set_pool("M21")["Teferi's Ageless Insight"],
        set_pool("STH")["Pursuit of Knowledge"],
    )

    game._draw_with_replacements(me, 1)

    _apply_first(game, "Teferi's Ageless Insight")
    offers = 0
    while game.pending_draw_becomes_counters:
        offers += 1
        assert offers <= 2, "the doubler doubled a draw it had already made"
        assert game.confirm_draw_becomes_counter(0, take_the_counter=True)

    assert offers == 2
    assert counters_on(pursuit, "study") == 2
    assert me.hand == [] and _owed(game) == []


@pytest.mark.cr("614.5")
def test_614_5_a_declined_replacement_is_not_offered_the_doubled_draws(set_pool):
    """The other order. Pursuit of Knowledge applied first and declined has
    had its opportunity at this event; the two draws the doubler then makes of
    it are that event modified, so both are simply drawn."""
    game, me, (_insight, pursuit) = _game(
        set_pool("M21")["Teferi's Ageless Insight"],
        set_pool("STH")["Pursuit of Knowledge"],
    )

    game._draw_with_replacements(me, 1)

    _apply_first(game, "Pursuit of Knowledge")
    assert game.confirm_draw_becomes_counter(0, take_the_counter=False)

    assert _owed(game) == []
    assert [card.name for card in me.hand] == ["L1", "S1"]
    assert counters_on(pursuit, "study") == 0


@pytest.mark.cr("121.2")
def test_121_2_a_seat_nobody_asks_draws_straight_through(set_pool):
    """Headless and AI seats take each default where it stands, so nothing is
    ever owed, nothing is parked, and the draws happen in one call as they
    always did."""
    game, me, _permanents = _game(
        set_pool("USG")["Abundance"], set_pool("STH")["Pursuit of Knowledge"],
        interactive=False,
    )

    game._draw_with_replacements(me, 3)

    assert not game.parked_draws
    assert not game.pending_choices and not game.pending_replacement_choices
    assert len(me.hand) == 3
