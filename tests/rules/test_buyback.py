"""Buyback — CR 702.27.

The keyword's whole content is the two static abilities CR 702.27a says it
*is*: an optional additional cost (CR 601.2b) and a replacement of where the
spell goes as it resolves (CR 608.2n's graveyard becomes its owner's hand). So
these tests drive real casts through a real ``Game`` rather than calling the
reader — what is being checked is that the printed word produces an offer the
cast path charges, and that the offer being taken is still knowable at
resolution, which is the half that has no other instrument.

The fixtures are **invented** cards rather than Tempest's twelve. The per-card
tests for those are in ``tests/sets/test_tmp_instants.py`` /
``test_tmp_sorceries.py``; what is asserted here is that the keyword works on
any card printing it, which is the claim a rewrite makes and a card-shaped test
cannot check.

``engine/cast_costs.py`` documents the rewrite.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.cast_costs import (additional_costs, buyback_cost, buyback_paid,
                               expand_buyback_line, is_buyback_line,
                               unread_cost_sentence)
from engine.card_loader import load_catalog
from engine.models import CardDefinition, PlayerState
from engine.oracle import compile_card_oracle, expand_card_lines

_CATALOG_FOR_BUYBACK = {card.name: card for card in load_catalog()}


def _mk(name: str, mana_cost: str, buyback: str, effect: str) -> CardDefinition:
    """An instant whose text is a buyback line plus one effect line.

    The reminder text is printed too, because that is what the ingested cards
    carry and stripping it is part of what the reader has to do.
    """
    reminder = (
        f" (You may pay an additional {buyback} as you cast this spell. "
        "If you do, put this card into your hand as it resolves.)"
    )
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=0.0,
        type_line="Instant",
        oracle_text=f"Buyback {buyback}{reminder}\n{effect}",
        colors=(),
        color_identity=(),
        keywords=("Buyback",),
        produced_mana=(),
        raw={},
    )


def _cast(card: CardDefinition, *, pool: dict[str, int], **kwargs):
    caster = PlayerState(name="A", hand=[card], library=[card])
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = True
    for symbol, count in pool.items():
        caster.mana_pool[symbol] = count
    game._settle()
    result = game.cast_from_hand(0, card.name, **kwargs)
    game._settle()
    if game.stack:
        game.resolve_top_of_stack()
        game._settle()
    return game, caster, result


@pytest.mark.cr("702.27a", "601.2b")
def test_the_keyword_line_becomes_the_additional_cost_the_rule_defines():
    """"Buyback [cost]" *means* "You may pay an additional [cost] as you cast
    this spell" — so the line is rewritten into that sentence before any line is
    classified, and from there nothing downstream knows the word."""
    card = _mk("Probe Bolt", "{R}", "{2}", "Probe Bolt deals 1 damage to any target.")

    assert is_buyback_line(card.oracle_text.split("\n")[0])
    assert expand_card_lines(card)[0] == (
        "As an additional cost to cast this spell, you may pay {2}."
    )
    offers = [
        offer for cost in additional_costs(card) for offer in cost.optional_mana
    ]
    assert [(o.symbols, o.repeatable) for o in offers] == [("{2}", False)]


@pytest.mark.cr("702.27a")
def test_a_coloured_buyback_cost_keeps_its_pips():
    """The cost is taken off the printed line, so {1}{U} is not flattened to
    {2} — a buyback charged in generic mana is a cheaper card than the one
    printed."""
    card = _mk("Probe Recall", "{U}", "{1}{U}", "Draw a card.")
    assert buyback_cost(card.oracle_text) == "{1}{U}"


@pytest.mark.cr("702.27a", "608.2n")
def test_paying_buyback_returns_the_spell_to_its_owners_hand():
    """The rule's second static ability: "If the buyback cost was paid, put this
    spell into its owner's hand instead of into that player's graveyard as it
    resolves." """
    card = _mk("Probe Recall", "{U}", "{2}", "Draw a card.")
    game, caster, result = _cast(
        card, pool={"U": 3}, optional_cost_payments={"{2}": 1},
    )

    assert result.supported, result.details
    assert [c.name for c in caster.hand] == ["Probe Recall", "Probe Recall"], (
        "the card it drew, and the spell itself coming back"
    )
    assert caster.graveyard == []


@pytest.mark.cr("702.27a", "608.2n")
def test_declining_buyback_leaves_the_spell_in_the_graveyard():
    """"**If** the buyback cost was paid" — an offer nobody took replaces
    nothing, and CR 608.2n's ordinary destination stands."""
    card = _mk("Probe Recall", "{U}", "{2}", "Draw a card.")
    game, caster, result = _cast(card, pool={"U": 3})

    assert result.supported, result.details
    assert [c.name for c in caster.graveyard] == ["Probe Recall"]
    assert sum(caster.mana_pool.values()) == 2, "the printed {U} and none of the offer"


@pytest.mark.cr("601.2b")
def test_buyback_may_be_paid_once_and_the_second_announcement_is_refused():
    """CR 702.27a's cost is not CR 601.2b's "any number of times": the offer is
    a single "you may pay". Announcing it twice is an illegal proposal
    CR 601.2e rewinds, not a payment to clamp."""
    card = _mk("Probe Recall", "{U}", "{2}", "Draw a card.")
    game, caster, result = _cast(
        card, pool={"U": 9}, optional_cost_payments={"{2}": 2},
    )

    assert not result.supported
    assert "may be paid once" in result.details
    assert [c.name for c in caster.hand] == ["Probe Recall"]
    assert sum(caster.mana_pool.values()) == 9, "nothing was spent"


@pytest.mark.cr("601.2h")
def test_a_buyback_the_pool_cannot_pay_refuses_the_cast_before_anything_is_spent():
    """The offer is announced before payment, so an announcement the pool cannot
    cover refuses the whole cast — CR 601.2h — rather than being silently
    dropped down to the printed cost."""
    card = _mk("Probe Recall", "{U}", "{5}", "Draw a card.")
    game, caster, result = _cast(
        card, pool={"U": 2}, optional_cost_payments={"{5}": 1},
    )

    assert not result.supported
    assert [c.name for c in caster.hand] == ["Probe Recall"]
    assert sum(caster.mana_pool.values()) == 2


@pytest.mark.cr("702.27a")
def test_a_buyback_cost_this_engine_cannot_read_makes_the_card_unsupported():
    """The wide shape is what the support gate asks, exactly as
    ``equipment._EQUIP_SHAPE`` is: a printing the rewrite refuses must be
    reported rather than falling through to a gate that never heard of the
    keyword — which would cast the spell at its printed mana cost with the
    price nobody was offered and no return.

    The invented cost is a coin flip rather than a sacrifice: CR 702.27's cost
    is *any* cost, and since Constant Mists the rewrite writes a non-mana one
    the cost table can charge into CR 601.2b's optional sentence. What must
    still refuse is a clause nothing charges, which is what this names.
    """
    card = CardDefinition(
        name="Probe Coin", mana_cost="{B}", cmc=1.0, type_line="Instant",
        oracle_text="Buyback-Flip a coin.\nDraw a card.",
        colors=(), color_identity=(), keywords=("Buyback",), produced_mana=(),
        raw={},
    )

    assert expand_buyback_line(card.oracle_text.split("\n")[0]) is None
    assert unread_cost_sentence(card.oracle_text.split("\n")[0]) is not None
    program = compile_card_oracle(card)
    assert not program.supported
    assert "printed cost nothing charges" in program.reason


@pytest.mark.cr("702.27a")
def test_the_read_back_is_keyed_to_the_cost_this_card_prints():
    """One reader for the rewrite and for the resolution, so the key the
    announcement was recorded under is the key the return is asked by. A card
    printing no buyback is never bought back by a neighbour's key."""
    bought = _mk("Probe Recall", "{U}", "{2}", "Draw a card.")
    plain = CardDefinition(
        name="Probe Plain", mana_cost="{U}", cmc=1.0, type_line="Instant",
        oracle_text="Draw a card.", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={},
    )

    assert buyback_paid(bought, {"additional_costs_paid": {"{2}": 1}})
    assert not buyback_paid(bought, {"additional_costs_paid": {"{3}": 1}})
    assert not buyback_paid(plain, {"additional_costs_paid": {"{2}": 1}})


@pytest.mark.cr("702.27a", "701.6a")
def test_a_bought_back_spell_that_is_countered_goes_to_the_graveyard():
    """"…as it **resolves**." A countered spell does not resolve, so CR 702.27a's
    replacement never applies and CR 701.6a's graveyard stands — even though the
    buyback cost was paid and nothing is refunded (CR 701.6b).

    Right here by construction rather than by a check: only the resolution site
    passes ``hand_instead`` to ``_bin_spell_card``, and the two countering call
    sites share that seam without it. The test is what makes that a decision
    rather than an accident, because taking the parameter out of the signature
    and asking the question inside would pass every other test in this file.
    """
    card = _mk("Probe Recall", "{U}", "{2}", "Draw a card.")
    caster = PlayerState(name="A", hand=[card], library=[card])
    counterer = PlayerState(
        name="B", hand=[_CATALOG_FOR_BUYBACK["Counterspell"]]
    )
    game = Game(players=[caster, counterer])
    game.enforce_mana_costs = False

    game.queue_from_hand(0, "Probe Recall", optional_cost_payments={"{2}": 1})
    game.queue_from_hand(1, "Counterspell", target_player_index=0)
    game.resolve_stack()

    assert [c.name for c in caster.graveyard] == ["Probe Recall"]
    assert caster.hand == [], (
        "the buyback cost was paid, and CR 702.27a still does not apply to a "
        "spell that never resolved"
    )
