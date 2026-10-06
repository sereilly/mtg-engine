"""The derived-card caches in ``engine/models.py`` hold the card they answer for.

Four of them — abilities granted, all abilities gone, printed lines struck
out, keywords struck out — are keyed on ``id(card)``, because a
``CardDefinition`` carries a dict and cannot be hashed. An ``id`` is an
address, and CPython hands a freed object's address to the next object of its
size. So a cache that did not keep its key alive answered for a card that no
longer existed: asked about a basic Island, it returned the nonbasic land an
earlier board had built in the same place.

It surfaced as ``test_w1g5_star_compass_reads_what_the_basic_land_makes_now``
failing in one full run of the suite out of two, with nothing in the test or
near it changed — the round that found it only made the suite build and free
more boards. Here the reuse is forced, so the failure is every run's.
"""
from __future__ import annotations

import gc

import pytest

from engine.models import (CardDefinition, _with_granted_abilities,
                           _without_ability_lines, _without_any_abilities,
                           _without_keyword_parts)


def _card(name: str, type_line: str, text: str, keywords=()) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=tuple(keywords), produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


#: Each cache, as ``(the question, the arguments both cards are asked with)``.
CACHES = {
    "granted": (_with_granted_abilities, (("Flying",),)),
    "stripped": (_without_any_abilities, ()),
    "lines": (_without_ability_lines, (("flying",),)),
    "keywords": (_without_keyword_parts, (("flying",),)),
}


@pytest.mark.parametrize("which", sorted(CACHES))
def test_a_freed_cards_address_does_not_answer_for_the_next_card(which):
    """Ask about one card, drop it, and build another until one lands at the
    first one's address — the answer must be about the card that was asked.
    With the key kept alive the address is never handed out again, so the
    loop runs dry, which is the fix; without it the reuse arrives within a
    few attempts and the second card is told it is the first."""
    ask, arguments = CACHES[which]
    reused = 0
    for _attempt in range(200):
        first = _card("Probe Nonbasic", "Land - Island", "Flying", ("Flying",))
        ask(first, *arguments)
        address = id(first)
        del first
        gc.collect()
        second = _card("Probe Basic", "Basic Land - Island", "Flying", ("Flying",))
        if id(second) != address:
            continue
        reused += 1
        answer = ask(second, *arguments)
        assert (answer.name, answer.type_line) == ("Probe Basic", "Basic Land - Island")
    assert reused == 0, "a card with a cache entry was freed and its address reused"
