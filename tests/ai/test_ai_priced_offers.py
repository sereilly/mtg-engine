"""A "you may A. If you do, B." default that is not a constant.

The optional-pay default is "take gifts, pay tolls, make no trades", decided by
the offer's **leading** step. Two cards print a trade that rule gets wrong in
opposite directions:

* **Elfhame Sanctuary** — "you may search your library for a basic land card …
  If you do, **you skip your draw step this turn**." The leading step is a
  gift, so it was taken at every upkeep and the seat never drew again
  (ROADMAP, Invasion). Measured over six simulated games with it pinned: 56
  offers, 56 taken, 56 draw steps skipped.
* **Forsaken City** — "you may exile a card from your hand. If you do, untap
  this land." The leading step is a price, so it was declined at every upkeep
  (PLS W1G5: "97 declines, 0 untaps"; 122 and 0 re-measured).

Both are one question — what the offer costs and what it buys — so the two
halves are named off the compiled program (``ai_valuation.offer_trade``) and
weighed against the board (``ai_policy.offer_trade_is_worth_taking``): a land
is worth a draw to a seat short of lands and to nobody else. The City's trade
stays declined, for the reason the policy states.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import LAND_FOR_DRAW_FLOOR
from engine.ai_valuation import OfferTrade, _walk_program, offer_trade
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle

#: `may` offers in the pool the derivation was asked about.
_OFFER_FLOOR = 150


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


def test_w2g5_which_offers_are_a_price_and_a_purchase(pool):
    """The census: every `may` in both manifest roles, and which of them the
    derivation names a trade. A third card joining either shape is weighed the
    day it is ingested; this pins the two it reaches today."""
    examined = 0
    trades: dict = {}
    for name, card in pool.items():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for step in _walk_program(program):
            if step.kind != "may":
                continue
            examined += 1
            trade = offer_trade(
                tuple(step.payload.get("action") or ())
                + tuple(step.payload.get("then") or ())
            )
            if trade is not None:
                trades[name] = trade
    assert examined >= _OFFER_FLOOR, examined
    assert trades == {
        "Elfhame Sanctuary": OfferTrade(price="draw", purchase="land_card"),
        "Forsaken City": OfferTrade(price="card", purchase="untap_source"),
    }


def _w2g5_upkeep(pool, *, permanents, hand=(), library=None) -> Game:
    """Seat 0's next turn begun and its upkeep triggers answered headless."""
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("AI", library=list(library or [pool["Grizzly Bears"]] * 20 + [forest] * 10),
                    hand=[pool[name] for name in hand]),
        PlayerState("Other", library=[forest] * 30),
    ], prompt_driver=lambda played: played.auto_resolve_pending_choices())
    # The driver is what answers an upkeep prompt *in* the upkeep: without it
    # the answer is taken after the draw step and the skip it arms is spent on
    # nothing (`SimulationReport.steps_left_owing`).
    for name in permanents:
        game._put_permanent_onto_battlefield(0, Permanent(card=pool[name]), None)
    game.active_player_index = 1
    game.turn = 1
    game.start_next_turn()
    game._resolve_priority_window()
    game.auto_resolve_pending_choices()
    return game


def test_w2g5_a_seat_with_lands_keeps_its_draw_step(pool):
    """Elfhame Sanctuary beside enough lands: the offer is declined and the
    seat draws its card for the turn."""
    lands = ["Forest"] * LAND_FOR_DRAW_FLOOR
    game = _w2g5_upkeep(pool, permanents=["Elfhame Sanctuary", *lands])
    assert any("declined Elfhame Sanctuary" in line for line in game.log)
    assert not any("skip their draw step" in line for line in game.log)
    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]


def test_w2g5_a_seat_short_of_lands_takes_the_land_for_its_draw(pool):
    """…and with one land it searches: a basic land in hand, and no card drawn
    this turn — the trade the card prints, taken where it is worth taking."""
    game = _w2g5_upkeep(pool, permanents=["Elfhame Sanctuary", "Forest"])
    assert not any("declined Elfhame Sanctuary" in line for line in game.log)
    assert [card.name for card in game.players[0].hand] == ["Forest"]
    assert any("skip" in line and "draw step" in line for line in game.log)


def test_w2g5_forsaken_city_keeps_the_card_and_stays_tapped(pool):
    """Forsaken City's trade is still declined, with a full hand as with an
    empty one: nothing is exiled and the land does not untap."""
    for hand in ((), ("Grizzly Bears",) * 7):
        game = _w2g5_upkeep(pool, permanents=[], hand=hand)
        city = Permanent(card=pool["Forsaken City"])
        game._put_permanent_onto_battlefield(0, city, None)
        city.tapped = True
        game.active_player_index = 1
        game.start_next_turn()
        game._resolve_priority_window()
        game.auto_resolve_pending_choices()
        assert any("declined Forsaken City" in line for line in game.log)
        assert city.tapped and game.players[0].exile == []
