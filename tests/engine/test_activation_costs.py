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
                    if charged.sacrifice_type is None:
                        unpaid.append(f"{card.name}: {ability.source_line}")
                    elif cost.filter.other_than_source != charged.sacrifice_excludes_source:
                        unpaid.append(f"{card.name}: 'another' dropped")
                if isinstance(cost, ast.DiscardCost) and not cost.last_drawn:
                    if not charged.discard_cards:
                        unpaid.append(f"{card.name}: {ability.source_line}")
    assert not unpaid, "cost clauses parsed but never charged: " + "; ".join(unpaid)
