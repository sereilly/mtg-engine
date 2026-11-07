"""Census: no reader of a printed "<creature type> card" narrows it to a creature
card (CR 109.2a, 205.3m, 308.2).

A creature type is a creature's or a kindred's, so "a Goblin card" in a hand, a
library or a graveyard is any card with the subtype — a Kindred Sorcery —
Goblin among them. ``nouns.parse_object_filter`` implied the creature type
after a creature subtype under every head noun, card heads included, and
every reader downstream took it: twenty-four programs in the pool on the base
(4c3d6e34) carried ``card_type: "creature"`` (or ``type_filter``) beside a
subtype the card prints as "<type> card" — Goblin Matron's search, Lord of the
Undead's return, the Apocalypse recruiters' reveal, Soulless One's graveyard
count, Infernal Caretaker's sweep and the rest. The text-keyed readers that
parse a card phrase at run time took it too (Putrid Raptor's "Discard a
Zombie card", Conspicuous Snoop's "a Goblin card" on top of a library).

Exact on a pool with no Kindred card — which this one is — so the census is
over what the programs *say*, and the board is in
``tests/rules/test_kg4_kindred2_subtype_card.py`` with invented Kindred cards.

The census reads only card-zone readers (a graveyard pick, a search, a revealed
pile, a graveyard count): "destroy target Wall" names a permanent on the
battlefield (CR 109.2), which is not this question, and a card printing both
("the number of Zombies on the battlefield plus the number of Zombie cards in
all graveyards", Soulless One) is read zone by zone.

Validated backwards: on the base the program census names the 24 cards and the
text-keyed test names both readers; each carries a floor on what it examined.
"""

from __future__ import annotations

import re

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.grammar.vocabulary import CREATURE_TYPES
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction

_WORDS = sorted(CREATURE_TYPES, key=len, reverse=True)
_ALT = "|".join(re.escape(word) for word in _WORDS)
#: "<type> card(s)" and "<type> or/and/or <type> card(s)" — never "<type>
#: creature card" or "<type> permanent card", which print their own type.
_CARD_PHRASE = re.compile(
    rf"\b((?:{_ALT})(?:(?: and/or | or )(?:{_ALT}))?) cards?\b", re.I,
)
#: Zones a card is in when it is not a permanent (CR 109.2a).
_CARD_ZONES = frozenset({"graveyard", "hand", "library", "exile"})
#: Instruction kinds whose ``filter`` is a description of cards in a zone.
_CARD_FILTER_KINDS = frozenset({
    "reveal_top_sorting_by_filter", "return_all_cards_from_graveyard",
})


def _phrase_subtypes(text: str) -> set[str]:
    found: set[str] = set()
    for match in _CARD_PHRASE.finditer(text):
        for word in re.split(r" and/or | or ", match.group(1)):
            found.add(word.lower())
    return found


def _types_of(value) -> tuple[str, ...]:
    if value in (None, "", "any"):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(word) for word in value)
    return (str(value),)


def _rows(obj, out, *, kind=None):
    """Every card-zone narrowing under *obj*, as ``(subtypes, card types)``."""
    if isinstance(obj, OracleInstruction):
        _rows(obj.payload, out, kind=obj.kind)
        return
    if isinstance(obj, dict):
        subtypes = set(obj.get("graveyard_subtypes") or ())
        if subtypes:
            types = _types_of(obj.get("card_types")) or _types_of(obj.get("card_type"))
            out.append((subtypes, types))
        restrictions = obj.get("restrictions")
        if isinstance(restrictions, dict):
            searched = set(restrictions.get("subtypes") or ()) | set(
                restrictions.get("any_subtypes") or ()
            )
            if searched:
                out.append((searched, _types_of(obj.get("card_type", "any"))))
        described = obj.get("filter")
        if isinstance(described, dict) and (
            kind in _CARD_FILTER_KINDS or obj.get("zone") in _CARD_ZONES
        ):
            sub = described.get("subtype_filter")
            subs = set(sub) if isinstance(sub, (list, tuple)) else {sub} if sub else set()
            if subs:
                out.append((subs, _types_of(described.get("type_filter"))))
        for key, value in obj.items():
            # A nested count's own zone decides its filter; this dict's
            # instruction kind is not its.
            _rows(value, out, kind=kind if key != "plus_count" else None)
        return
    if isinstance(obj, (list, tuple)):
        for value in obj:
            _rows(value, out, kind=kind)
        return
    for name in getattr(obj, "__dataclass_fields__", ()):
        _rows(getattr(obj, name, None), out, kind=kind)


@pytest.fixture(scope="module")
def census():
    examined: dict[str, list] = {}
    narrowed: dict[str, list] = {}
    for unit in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        wanted = _phrase_subtypes(unit.oracle_text or "")
        if not wanted:
            continue
        program = compile_card_oracle(unit)
        rows: list = []
        _rows((program.instructions, program.triggered_abilities,
               program.activated_abilities,
               tuple(mode.instruction for mode in program.modes)), rows)
        mine = [(subs, types) for subs, types in rows if subs & wanted]
        if mine:
            examined[unit.name] = mine
        bad = [(sorted(subs), types) for subs, types in mine if types == ("creature",)]
        if bad:
            narrowed[unit.name] = bad
    return examined, narrowed


def test_no_card_phrase_reader_narrows_a_creature_type_to_a_creature_card(census):
    _examined, narrowed = census
    assert not narrowed, (
        "a printed '<creature type> card' read as a creature card (a Kindred "
        "card of the type is a card of it, CR 205.3m):\n  "
        + "\n  ".join(f"{name}: {rows}" for name, rows in sorted(narrowed.items()))
    )


def test_the_census_examined_what_it_claims(census):
    """The floor, and the readers the census is known to reach."""
    examined, _narrowed = census
    assert len(examined) >= 20, sorted(examined)
    assert {
        "Goblin Matron", "Lord of the Undead", "Goblin Ringleader",
        "Soulless One", "Infernal Caretaker", "Corpse Harvester",
        "Unholy Grotto", "Lin Sivvi, Defiant Hero", "Cruel Revival",
    } <= set(examined)


@pytest.mark.parametrize("word", ["zombie", "goblin", "sliver"])
def test_the_text_keyed_card_phrase_readers_name_no_card_type(word):
    """The readers that parse a card phrase as the game is played: a discard
    cost ("Morph—Discard a Zombie card", Putrid Raptor) and the top of a
    library ("…is a Goblin card", Conspicuous Snoop). Neither reaches a
    compiled program, so ``oracle_diff`` cannot see them."""
    from engine.chargeable_costs import _chargeable_discard_filters
    from engine.library_top import _filter_for

    assert _chargeable_discard_filters(f"a {word} card") == ({"subtype_filter": word},)
    assert _filter_for(word) == {"subtype_filter": word}
