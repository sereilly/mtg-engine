"""Two cards in hand payable together outrank one card and an ability that
can wait, even when the ability is the smaller want (Mirrodin's promotion
rehearsal, W2G0).

``tests/ai/test_kg2_payment_colour_census.py``'s two-wants census read four
strands the day Mirrodin joined the pool: its sample's {1} became Aether
Spellbomb ("{U}, Sacrifice this artifact: Return target creature to its
owner's hand. / {1}, Sacrifice this artifact: Draw a card."), the first card
of that cost to bring an activated ability of its own into the payment's
wants (``mana_wants.wants_left_behind``, the abilities' tier). The sparing
choice packs wants together smallest first, so the Spellbomb's one-pip {U}
went in ahead of the two-pip cards, and either choice packed "{U} and one
card": the cards' tier tied, and the board-order Plains paid the {1},
stranding the {W}{R} and {W}{U} pair a Mountain would have kept. The cards'
tier is now packed on its own for that key (``mana_payment._wants_left``).
Validated backwards: on the scoring before it this board taps the Plains.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_payment import _PaymentPlanner, _paying_for
from engine.models import Permanent


def _board(set_pool, lands, hand):
    pools = [set_pool(code) for code in ("LEA", "MRD", "M21", "INV")]

    def card(name):
        return next(pool[name] for pool in pools if name in pool)

    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.players[0].battlefield = [Permanent(card=card(name)) for name in lands]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.players[0].hand = [card(name) for name in hand]
    game._recompute_continuous_effects()
    return game, card


def test_paying_for_a_spellbomb_keeps_both_gold_cards_payable_together(set_pool):
    game, card = _board(
        set_pool,
        ["Tundra", "Plains", "Island", "Mountain", "Mountain"],
        ["Aether Spellbomb", "Alpine Houndmaster", "Angelic Shield"],
    )
    player = game.players[0]
    with _paying_for(card("Aether Spellbomb")):
        planner = _PaymentPlanner(game, player)
    slots, _colours = planner.plan({"generic": 1})

    tapped = [game.permanent_at(0, slot).card.name for slot in slots]
    assert tapped == ["Mountain"], tapped
    left = [source for source in planner.sources if source.slot not in slots]
    assert planner._plan_with(left, {"W": 2, "R": 1, "U": 1}) is not None
