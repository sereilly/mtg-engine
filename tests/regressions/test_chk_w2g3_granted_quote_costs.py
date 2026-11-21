"""A quoted grant's cost clauses, read by the grammar and by the charger.

`tests/engine/test_activation_costs.py` compares the two readers of every
activated ability a card *prints*. A quote an Aura or Equipment grants is
compiled on its host and never appears among the granter's own abilities, so
that guard never reads one — and the costs a quote can print are exactly the
ones that name the granter: "{T}, Unattach Heartseeker" and "{T}, Remove all
aim counters from Hankyu" (CR 201.5a, written as the relation by
``granted_abilities.bind_granter``). A charger that read "remove all aim
counters" and not "from the permanent that granted this ability" takes the
counters off the creature, which never has any.

The census is validated backwards in its own body: with the charger's granter
reader blinded it must name Hankyu.
"""

from __future__ import annotations

import pytest

from engine import activation_costs
from engine.activation_costs import parse_activated_ability_cost
from engine.aura_grants import aura_quoted_grants
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.grammar import ast, parse_line
from engine.granted_abilities import bind_granter


@pytest.fixture(scope="module")
def granted_quotes():
    quotes = []
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        for quote in aura_quoted_grants(card.oracle_text or ""):
            quotes.append((card.name, bind_granter(quote, card.name)))
    return quotes


def _unpaid(granted_quotes) -> tuple[list[str], int]:
    unpaid: list[str] = []
    examined = 0
    for name, line in granted_quotes:
        try:
            node = parse_line(line)
        except Exception:
            continue
        if not isinstance(node, ast.ActivatedAbilityNode):
            continue
        charged = parse_activated_ability_cost(line, name)
        for cost in node.costs:
            if isinstance(cost, ast.RemoveCounterCost) and cost.granter_id is not None:
                examined += 1
                if (
                    charged.remove_counter, charged.remove_counter_granter_id,
                ) != (cost.counter, cost.granter_id):
                    unpaid.append(
                        f"{name}: charged {charged.remove_counter!r} off "
                        f"{charged.remove_counter_granter_id} for "
                        f"{cost.counter!r} off {cost.granter_id}"
                    )
            if isinstance(cost, ast.UnattachGranterCost):
                examined += 1
                if charged.unattach_granter_id != cost.permanent_id:
                    unpaid.append(f"{name}: unattach not charged")
    return unpaid, examined


def test_every_granter_cost_a_quote_prints_is_charged_off_the_granter(granted_quotes):
    unpaid, examined = _unpaid(granted_quotes)
    assert not unpaid, "\n".join(unpaid)
    # Hankyu's removal and the three unattach Equipment (Heartseeker, Leonin
    # Bola, Surestrike Trident) at least: a census that read none would pass.
    assert examined >= 4, examined


def test_the_census_names_a_charger_blind_to_the_granter(granted_quotes, monkeypatch):
    monkeypatch.setattr(
        activation_costs, "_counter_removal_granter_id", lambda cost_lower: None
    )
    unpaid, _examined = _unpaid(granted_quotes)
    assert any(line.startswith("Hankyu:") for line in unpaid), unpaid
