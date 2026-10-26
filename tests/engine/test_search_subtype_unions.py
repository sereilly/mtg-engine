"""Every library search that names two subtypes finds a card carrying either.

"Search your library for an **Island or Swamp** card" (Bad River, Polluted
Delta) is a printed union: the noun parser reads it so
(``ObjectFilter.subtype_match == "any"``), and the search lowering emitted it
as ``restrictions["subtypes"]``, which ``search_filters.search_matches`` AND'd
— a card that is both an Island and a Swamp, which no basic land is. Ten
fetchlands across both manifest roles (Mirage's five, Onslaught's five) paid
their cost and found nothing, every one of them reported supported, and no
instrument saw it: the program compiles, every sentence is claimed, the picker
has nothing to pick. Found by driving Onslaught's fetches (W1G11).

The census compiles every card of both roles, takes each search restriction
naming two or more subtypes (a one-of-each search's slots included), and asks
the one predicate the engine, the AI and the web picker answer with whether a
basic land of each named type is a legal find. Validated backwards: the same
restriction spelled the old way finds none of them.
"""

from __future__ import annotations

from engine import load_cards
from engine.card_loader import manifest_set_paths
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle
from engine.search_filters import search_matches

#: Ten on the day this was written; a floor, because a census that reaches
#: nothing passes.
_MIN_SEARCHES = 10


def _steps(instruction):
    if instruction is None:
        return
    yield instruction
    for value in instruction.payload.values():
        children = value if isinstance(value, (list, tuple)) else (value,)
        for child in children:
            if hasattr(child, "kind") and hasattr(child, "payload"):
                yield from _steps(child)


def _restriction_sets(restrictions):
    if not isinstance(restrictions, dict):
        return
    yield restrictions
    for slot in restrictions.get("one_of_each") or ():
        yield from _restriction_sets(slot.get("restrictions"))


def _union_searches():
    pool = load_cards(manifest_set_paths(include_measured=True))
    seen: set[str] = set()
    for card in compilation_units(list(pool)):
        if card.name in seen:
            continue
        seen.add(card.name)
        program = compile_card_oracle(card)
        roots = [*program.instructions]
        roots += [ability.instruction for ability in program.activated_abilities]
        roots += [
            getattr(trigger, "instruction", None)
            for trigger in program.triggered_abilities
        ]
        for root in roots:
            for step in _steps(root):
                if step.kind != "search_library":
                    continue
                for restrictions in _restriction_sets(step.payload.get("restrictions")):
                    named = tuple(restrictions.get("any_subtypes") or ()) or tuple(
                        restrictions.get("subtypes") or ()
                    )
                    if len(named) >= 2:
                        yield card.name, step.payload, restrictions, named


def _basics():
    return {
        card.name.lower(): card
        for card in load_cards(manifest_set_paths(include_measured=True))
        if card.name in ("Plains", "Island", "Swamp", "Mountain", "Forest")
    }


def test_every_two_subtype_search_finds_a_card_of_either_type():
    basics = _basics()
    found = list(_union_searches())
    assert len(found) >= _MIN_SEARCHES, found
    failures = []
    for name, payload, restrictions, named in found:
        data = {"card_type": payload.get("card_type", "any"), "restrictions": restrictions}
        for subtype in named:
            card = basics.get(subtype)
            assert card is not None, f"{name}: no basic land named {subtype}"
            if not search_matches(card, data):
                failures.append((name, subtype))
    assert not failures, failures


def test_the_census_names_the_and_reading():
    """Backwards: each union spelled as the AND it used to be finds none of
    the basics it names."""
    basics = _basics()
    found = list(_union_searches())
    assert found
    for name, payload, _restrictions, named in found:
        data = {
            "card_type": payload.get("card_type", "any"),
            "restrictions": {"subtypes": list(named)},
        }
        assert not any(search_matches(basics[subtype], data) for subtype in named), name
