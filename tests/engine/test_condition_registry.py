"""Every condition the compiled pool carries has a handler, and every handler
has a card.

``evaluate_condition`` answers **False** for a kind it does not know. That is
deliberate — the grammar refuses to lower a condition it cannot describe — and
it is also the shape of a silent wrong answer: a lowering that produced a kind
nobody registered would compile, read as supported, and never be true. While
the conditions were seventy-two arms of one function there was nothing to
compare the lowering against. They are a registry now
(``engine/handlers/conditions.CONDITIONS``), so the comparison is one set
difference in each direction, over every compiled program in the pool.

Conditional *statics* are the one other evaluator: ``static_bonuses`` reads
"as long as …" with a vocabulary of its own, and the kinds only it knows are
named below, each held to still being spelled in that module.
"""

from __future__ import annotations

import dataclasses
from functools import lru_cache
from pathlib import Path

import pytest

from engine import static_bonuses
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.handlers.conditions import CONDITIONS, condition, evaluate_condition
from engine.oracle import compile_card_oracle
from tests.source_index import source_text

#: Kinds the pool carries under a condition key that ``evaluate_condition`` is
#: never asked: a conditional static's, evaluated by
#: ``static_bonuses.conditional_static_holds``.
STATIC_ONLY_KINDS = frozenset({
    "all_share_a_color",
    "attached_matches",
    "controls_planeswalker",
    "drawn_cards_this_turn",
    "graveyard_size",
    "has_plus1_counter",
    "shares_most_common_color",
})

#: Payload keys whose value is a condition, and the keys a condition nests
#: further conditions under.
_CONDITION_KEYS = frozenset({"condition", "conditions", "unless", "if", "only_if", "intervening_if"})
_NESTING_KEYS = frozenset({"conditions", "condition", "all_of", "any_of", "operands", "not"})


def _walk(value, found: dict, name: str, is_condition: bool = False) -> None:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            _walk(getattr(value, field.name), found, name, field.name in _CONDITION_KEYS)
    elif isinstance(value, dict):
        if is_condition and isinstance(value.get("kind"), str):
            found.setdefault(value["kind"], set()).add(name)
        for key, inner in value.items():
            _walk(
                inner, found, name,
                key in _CONDITION_KEYS or (is_condition and key in _NESTING_KEYS),
            )
    elif isinstance(value, (list, tuple)):
        for inner in value:
            _walk(inner, found, name, is_condition)


@lru_cache(maxsize=1)
def condition_kinds_in_the_pool() -> dict:
    """``{condition kind: the cards whose compiled program carries it}``."""
    found: dict = {}
    pool = load_cards(manifest_set_paths(include_measured=True))
    for card in compilation_units(pool):
        _walk(compile_card_oracle(card), found, card.name)
    return found


def test_the_walk_finds_the_pools_conditions():
    """The floors are what stop a renamed payload key from making the two
    comparisons below pass by examining nothing."""
    found = condition_kinds_in_the_pool()
    # 80 kinds on 440 cards (October 2026). Floors, not equalities: the pool grows.
    assert len(found) >= 75, len(found)
    carrying = len(set().union(*found.values()))
    assert carrying >= 415, carrying
    assert "controls" in found and "was_kicked" in found


def test_no_compiled_condition_is_a_kind_nothing_evaluates():
    found = condition_kinds_in_the_pool()
    unevaluated = {
        kind: sorted(cards)[:5]
        for kind, cards in found.items()
        if kind not in CONDITIONS and kind not in STATIC_ONLY_KINDS
    }
    assert not unevaluated, (
        "the pool compiles conditions of kinds with no @condition handler, so "
        f"each is False for ever: {unevaluated}"
    )


def test_no_registered_condition_is_one_nothing_in_the_pool_produces():
    found = condition_kinds_in_the_pool()
    dead = sorted(kind for kind in CONDITIONS if kind not in found)
    assert not dead, (
        f"@condition handlers no compiled program reaches: {dead}. A handler "
        "whose producer was removed is dead, not wrong — delete it with the "
        "production, or this walk has stopped reading the key it travels under."
    )


def test_a_static_only_kind_is_still_one_the_static_evaluator_spells():
    source = source_text(Path(static_bonuses.__file__))
    found = condition_kinds_in_the_pool()
    for kind in sorted(STATIC_ONLY_KINDS):
        assert f'"{kind}"' in source, kind
        assert kind in found, f"{kind} is no longer produced: drop it from STATIC_ONLY_KINDS"
        assert kind not in CONDITIONS, f"{kind} has a handler now: drop it from STATIC_ONLY_KINDS"


def test_a_kind_cannot_be_registered_twice():
    taken = next(iter(CONDITIONS))
    with pytest.raises(ValueError, match="registered twice"):
        condition(taken)(lambda game, context, payload: True)


@pytest.mark.parametrize("payload", [
    {"kind": "no_such_condition"},
    {},
    {"kind": None},
    {"kind": ["controls"]},
])
def test_an_unknown_kind_answers_false(payload):
    assert evaluate_condition(None, None, payload) is False


def test_the_dispatcher_keeps_its_old_address():
    """Nineteen modules import it from ``handlers.control_flow``; the handlers
    moved and the address did not."""
    from engine.handlers import control_flow

    assert control_flow.evaluate_condition is evaluate_condition
