"""Optional sacrifices the AI never made (CHK W1G5, W1G6, W1G9).

Devouring Rage and Devouring Greed print "As an additional cost to cast this
spell, you may sacrifice any number of Spirits" and count what it ate. The
offer was classified as buying a *different* spell (``ai_valuation``'s
``OFFER_ALTERS``, Undergrowth's class), which the policy declines, so both were
cast with nothing sacrificed. An effect that counts what the offer ate makes a
*larger* spell (``OFFER_ADDS``), and "any number" is zero too: the offer is
taken and how many — none included — is weighed where the cast is built
(``ai_sacrifice_victims.cast_naming_its_sacrifices``, each set rehearsed).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.ai_valuation import OFFER_ADDS, cast_offers
from engine.models import Permanent
from tests.helpers import settle


def _w2g2_table(cards, hand, mine, *, their_life=20) -> Game:
    me = PlayerState(
        name="Me", hand=[cards[name] for name in hand],
        battlefield=[Permanent(card=cards[name]) for name in mine],
        library=[cards["Swamp"]] * 10,
    )
    you = PlayerState(name="You", life=their_life, library=[cards["Swamp"]] * 10)
    game = Game(players=[me, you], enforce_mana_costs=True)
    game._sync_control()
    for permanent in game.players[0].battlefield:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.turn = 5
    game.begin_turn_bookkeeping(0)
    game._enter_main_phase(precombat=True)
    return game


def test_the_devouring_offers_buy_a_larger_spell(set_pool):
    chk = set_pool("CHK")
    for name in ("Devouring Rage", "Devouring Greed"):
        assert [offer.buys for offer in cast_offers(chk[name])] == [OFFER_ADDS], name


def test_devouring_greed_sacrifices_the_spirits_that_make_it_lethal(set_pool):
    """At six life, two Spirits make Greed's 2 into 6: the seat sacrifices
    both and wins."""
    chk = set_pool("CHK")
    game = _w2g2_table(
        chk, ["Devouring Greed"],
        ["Swamp"] * 4 + ["Ashen-Skin Zubera", "Ashen-Skin Zubera"], their_life=6,
    )
    action = choose_cast_action(game, 0)

    assert action.card_name == "Devouring Greed"
    assert len(action.cost_permanent_ids or ()) == 2
    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    settle(game)
    assert game.players[1].life <= 0


def test_devouring_greed_keeps_its_spirits_when_the_drain_is_not_worth_them(set_pool):
    """At twenty life two more life lost is not worth a creature: the offer is
    taken with nothing named, which is the offer declined."""
    chk = set_pool("CHK")
    game = _w2g2_table(
        chk, ["Devouring Greed"],
        ["Swamp"] * 4 + ["Ashen-Skin Zubera", "Ashen-Skin Zubera"],
    )
    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Devouring Greed"
    assert not action.cost_permanent_ids
