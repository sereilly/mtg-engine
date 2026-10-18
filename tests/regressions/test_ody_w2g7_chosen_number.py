"""A number chosen as a spell is cast (CR 601.2b) is that spell's X — and
nothing else may be.

Liquid Fire's cost, "As an additional cost to cast this spell, choose a number
between 0 and 5", rides the cast's announced X: its other line reads the number
back as "where X is the chosen number", and CR 601.2b makes a variable defined
by a choice in the announcement a choice made *then*. That is honest only
while three things hold of every card that prints the cost, so they are held
over the whole pool, both manifest roles, rather than of the one card:

* the X prices nothing — no ``{X}`` in the mana cost, no clause that charges
  X cards, permanents or life beside the choice;
* the number is *spent* — the card's program reads an X, and the card says in
  words that the X is the chosen number;
* the picker's range is the gate's range, at both ends.

And the reverse: the words "where X is the chosen number" compile only on a
card whose cost chooses one.
"""

from __future__ import annotations

from engine import Game, PlayerState, faces
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_costs import (additional_costs, cast_announces_x,
                               unchosen_number_definition)
from engine.grammar.lowering._amounts import _mentions_x
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_WORDS = "where x is the chosen number"


def _pool():
    cards = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
    return cards


def test_a_chosen_number_is_the_casts_x_and_prices_nothing():
    pool = _pool()
    choosers = []
    for card in faces.compilation_units(list(pool.values())):
        costs = [cost for cost in additional_costs(card) if cost.choose_number]
        if not costs:
            continue
        choosers.append(card.name)
        (cost,) = costs
        low, high = cost.choose_number
        program = compile_card_oracle(card)
        assert program.supported, (card.name, program.reason)
        # The X prices nothing.
        assert "{X}" not in (card.mana_cost or "").upper(), card.name
        assert not (
            cost.pay_life_x or cost.return_count_x
            or cost.exile_graveyard_count_x or cost.discard_count_x
            or cost.optional_mana
        ), card.name
        # It is announced, and it is spent.
        assert cast_announces_x(card), card.name
        assert _mentions_x(tuple(program.instructions)), card.name
        assert _WORDS in " ".join((card.oracle_text or "").lower().split()), card.name
        # The picker's range is the gate's range.
        game = Game(players=[
            PlayerState("A", library=[pool["Forest"]] * 5, hand=[card]),
            PlayerState("B", library=[pool["Forest"]] * 5),
        ])
        game.enforce_mana_costs = False
        victim = Permanent(card=pool["Craw Wurm"])
        game._put_permanent_onto_battlefield(1, victim, None)
        spec = game.cast_target_spec(0, card)
        assert spec.get("announces_x") is True, card.name
        assert spec.get("max_x") == high, card.name
        assert spec.get("min_x", 0) == low, card.name
        for chosen in (low - 1, high + 1):
            assert cost.number_refusal(chosen) is not None, (card.name, chosen)
        for chosen in range(low, high + 1):
            assert cost.number_refusal(chosen) is None, (card.name, chosen)
    # A sweep that examined nothing looks exactly like one that found nothing.
    # A floor, not the list: the next card to print the cost is held to the
    # same three things by the loop above and should not have to edit this.
    assert "Liquid Fire" in choosers, choosers


def test_the_words_compile_only_where_a_cost_chooses_the_number():
    pool = _pool()
    printing_the_words = []
    for card in faces.compilation_units(list(pool.values())):
        if _WORDS not in " ".join((card.oracle_text or "").lower().split()):
            continue
        printing_the_words.append(card.name)
        chooses = any(cost.choose_number for cost in additional_costs(card))
        gate = unchosen_number_definition(
            card.oracle_text or "", card.name, card.is_legendary,
            spell=card.primary_type in {"instant", "sorcery"},
        )
        assert (gate is None) == chooses, card.name
        assert compile_card_oracle(card).supported == chooses, card.name
    assert "Liquid Fire" in printing_the_words, printing_the_words
