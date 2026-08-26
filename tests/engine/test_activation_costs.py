"""A cost the grammar admits must be a cost the engine charges.

The grammar parses an ability's cost clause into ``ast.Cost`` nodes and then
*discards* them — what is actually collected comes from
``parse_activated_ability_cost``. Two readers of one clause drift silently, and
the direction they drift in is free abilities: Atog sacrificed nothing for its
+2/+2 for as long as both readers existed and only one of them was consulted.

So this compares them over the whole pool rather than over a list of cards.
A card that prints a cost the charger cannot express is expected to be
*unsupported* — refusing loudly is the alternative to charging wrongly — which
is why only supported cards are checked.
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.grammar import ast, parse_line
from engine.mixins.stack.activation import COST_PERFORMING_KINDS
from engine.oracle import compile_card_oracle, parse_activated_ability_cost


@pytest.fixture(scope="module")
def pool():
    return load_cards(manifest_set_paths(include_measured=True))


def test_every_admitted_cost_clause_is_charged(pool):
    unpaid: list[str] = []
    for card in pool:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for ability in program.activated_abilities:
            if not ability.supported or ability.instruction is None:
                continue
            if ability.instruction.kind in COST_PERFORMING_KINDS:
                # The handler performs its own cost clause; charging it here
                # too would collect the same cost twice.
                continue
            try:
                node = parse_line(ability.source_line)
            except Exception:
                continue  # a card-hooked line; its hook performs the whole line
            if not isinstance(node, ast.ActivatedAbilityNode):
                continue
            charged = parse_activated_ability_cost(ability.source_line)
            for cost in node.costs:
                if isinstance(cost, ast.SacrificeCost) and not cost.filter.is_source:
                    if charged.sacrifice_filter is None:
                        unpaid.append(f"{card.name}: {ability.source_line}")
                    elif charged.sacrifice_filter != cost.filter.to_payload():
                        # Not "is something charged" but "is *this* charged".
                        # The grammar admits the line on the strength of the
                        # whole noun phrase, so a charger reading a smaller one
                        # collects a smaller cost — "a creature with defender"
                        # charged as "a creature" is the dropped-rider bug with
                        # the card still reporting supported.
                        unpaid.append(
                            f"{card.name}: charged {charged.sacrifice_filter} for "
                            f"{cost.filter.to_payload()}"
                        )
                if isinstance(cost, ast.DiscardCost) and not cost.last_drawn:
                    # "Discard your hand" and "Discard this card" are their own
                    # fields, not counts — one is never unpayable and the other
                    # names a specific card the payer does not choose — so each
                    # is checked against the flag that charges it rather than
                    # against ``discard_cards``, which stays zero for both.
                    if cost.whole_hand:
                        if not charged.discard_whole_hand:
                            unpaid.append(f"{card.name}: {ability.source_line}")
                        continue
                    if cost.self_card:
                        if not charged.discard_self:
                            unpaid.append(f"{card.name}: {ability.source_line}")
                        continue
                    if not charged.discard_cards:
                        unpaid.append(f"{card.name}: {ability.source_line}")
                    # Not "is a discard charged" but "is *this* discard charged",
                    # the same tightening the sacrifice branch above makes and
                    # for the same reason: "a land card or Shrine card" collected
                    # as "a card" is an ability payable with anything in hand,
                    # still reporting supported.
                    elif tuple(charged.discard_filters) != tuple(
                        f.to_payload() for f in cost.filters
                    ):
                        unpaid.append(
                            f"{card.name}: charged {charged.discard_filters} for "
                            f"{tuple(f.to_payload() for f in cost.filters)}"
                        )
                if isinstance(cost, ast.PayLifeCost):
                    # Not "is life charged" but "is *this much* charged". The
                    # amount is printed, and a charger reading a smaller one is
                    # the same dropped-rider shape a narrowed sacrifice is —
                    # here it would be an ability cheaper than the card.
                    wanted = cost.amount.value if isinstance(cost.amount, ast.Fixed) else None
                    if charged.pay_life != wanted:
                        unpaid.append(
                            f"{card.name}: charged {charged.pay_life} life for {wanted}"
                        )
    assert not unpaid, "cost clauses parsed but never charged: " + "; ".join(unpaid)
