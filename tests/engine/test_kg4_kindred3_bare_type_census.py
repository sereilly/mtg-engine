"""Census: no program pairs a bare creature type with "creature" (CR 109.2,
205.3m, 308.2).

"Destroy target Wall", "Other Goblins get +1/+1", "Sacrifice a Goblin": a
description with a subtype and no "card" names a permanent of that subtype on
the battlefield (CR 109.2), and creature types are a creature's *or a
kindred's* (CR 205.3m) — so the printed set is every Wall permanent, not
every Wall creature. ``nouns.parse_object_filter`` implied the creature type
after every bare creature type, and the lord table beside the grammar
(``lord_buffs._parse_subject``) did the same, so on the base (243f72df) 197
programs carried ``type_filter: "creature"`` (or a lord's default
``card_types``) beside a creature type the card prints bare (the
``oracle_diff`` of the fix). Exact on a pool
with no Kindred permanent — which this one is — so this census is over what
the programs *say*; the board is ``tests/rules/test_kg4_kindred3_bare_type_permanent.py``.

Two directions, each over every battlefield narrowing in every compiled
program (both manifest roles, every face):

* a narrowing that pairs creature types with "creature" is one the card
  prints that way ("Wall **creatures**", "target Elf or Soldier
  **creature**");
* a narrowing that names creature types and no card type is one the card
  prints bare — the parse did not drop a printed "creature".

Validated backwards: on the base (243f72df) the first test names 186 units —
every one of them among the 197 programs ``oracle_diff`` moves; the other
eleven print the type both ways in the line the census holds them to ("Sacrifice
two Goblins: Create three 1/1 red Goblin creature tokens", Goblin Warrens), so
the text check is a floor rather than the whole differential. The floor test
says how much was examined.
"""

from __future__ import annotations

import re

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.grammar.vocabulary import CREATURE_TYPES, singular
from engine.lord_buffs import LORD_BUFF_KIND
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction

#: Zones a card is in when it is not a permanent (CR 109.2a) — a "<type>
#: card" phrase, which ``test_kg4_kindred2_card_phrase_census`` reads.
_CARD_ZONES = frozenset({"graveyard", "hand", "library", "exile", "stack"})
_CARD_FILTER_KINDS = frozenset({
    "reveal_top_sorting_by_filter", "return_all_cards_from_graveyard",
    # "…a Goblin **permanent card** from your hand onto the battlefield"
    # (Goblin Lackey): a card in a hand, CR 110.4a's union with the subtype.
    "put_chosen_card_from_hand_onto_battlefield",
})
_WORD = re.compile(r"[a-z][a-z'-]*")


def _subtypes(obj: dict) -> frozenset[str]:
    found: set[str] = set()
    for key in ("subtype_filter", "subtype_filter_all"):
        value = obj.get(key)
        if isinstance(value, str):
            found.add(value)
        elif isinstance(value, (list, tuple)):
            found.update(str(word) for word in value)
    return frozenset(found & CREATURE_TYPES)


def _names_creature(value) -> bool:
    """Whether a card-type field is the creature alone — the implication's
    shape. A union with creature in it ("a Goblin **permanent** card", CR
    110.4a's six types) is another phrase, read by ``targets``' census."""
    if isinstance(value, str):
        return value == "creature"
    if isinstance(value, (list, tuple)):
        return list(value) == ["creature"]
    return False


def _rows(obj, out, *, kind=None, card_zone=False):
    """Every battlefield narrowing naming creature types under *obj*, as
    ``(kind, subtypes, names "creature")``."""
    if isinstance(obj, OracleInstruction):
        if obj.kind == LORD_BUFF_KIND:
            subtypes = frozenset(obj.payload.get("subtypes") or ()) & CREATURE_TYPES
            if subtypes:
                types = obj.payload.get("card_types", ("creature",))
                out.append((obj.kind, subtypes, _names_creature(list(types))))
        _rows(obj.payload, out, kind=obj.kind, card_zone=obj.kind in _CARD_FILTER_KINDS)
        return
    if isinstance(obj, dict):
        in_card_zone = card_zone or obj.get("zone") in _CARD_ZONES or bool(
            obj.get("graveyard_subtypes") or obj.get("restrictions")
        )
        subtypes = _subtypes(obj)
        if subtypes and not in_card_zone and "card_type" not in obj:
            out.append((
                kind, subtypes,
                _names_creature(obj.get("type_filter"))
                or _names_creature(obj.get("type_filter_all")),
            ))
        for key, value in obj.items():
            _rows(value, out, kind=kind,
                  card_zone=in_card_zone and key in ("filter", "card_filter"))
        return
    if isinstance(obj, (list, tuple)):
        for value in obj:
            _rows(value, out, kind=kind, card_zone=card_zone)
        return
    for name in getattr(obj, "__dataclass_fields__", ()):
        _rows(getattr(obj, name, None), out, kind=kind, card_zone=card_zone)


def _printed_before_creature(text: str) -> set[str]:
    """The creature types the text prints immediately before "creature(s)"
    — "Wall creatures", "Elf or Soldier creature", "Zombie creature card"."""
    words = _WORD.findall(text.lower())
    found: set[str] = set()
    for index, word in enumerate(words[1:], start=1):
        if word in ("creature", "creatures"):
            before = singular(words[index - 1])
            if before in CREATURE_TYPES:
                found.add(before)
    return found


def _printed_bare(text: str) -> set[str]:
    """The creature types the text prints with no card-type noun after them
    ("a Caribou token" is bare: a token is no card type, CR 111.1)."""
    words = _WORD.findall(text.lower())
    found: set[str] = set()
    for index, word in enumerate(words):
        typed = singular(word)
        if typed not in CREATURE_TYPES:
            continue
        following = words[index + 1] if index + 1 < len(words) else ""
        if singular(following) not in ("creature", "card", "permanent", "spell"):
            found.add(typed)
    return found


@pytest.fixture(scope="module")
def census():
    paired: dict[str, list] = {}
    bare: dict[str, list] = {}
    narrowed: dict[str, list] = {}
    dropped: dict[str, list] = {}
    for unit in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        # Each triggered and activated ability is held to its **own** printed
        # line (``source_line``), so a card printing the type both ways — "Sacrifice
        # an Elf" beside "…are 1/1 green Elf creatures" (Ambush Commander) — is
        # read line by line; the spell and static half to the whole text.
        text = unit.oracle_text or ""
        parts = [(text, (program.instructions,
                         tuple(mode.instruction for mode in program.modes)))]
        parts += [
            (ability.source_line or text, ability)
            for ability in (*program.triggered_abilities, *program.activated_abilities)
        ]
        for printed, part in parts:
            rows: list = []
            _rows(part, rows)
            before_creature = _printed_before_creature(printed)
            printed_bare = _printed_bare(printed)
            for kind, subtypes, names_creature in rows:
                if names_creature:
                    paired.setdefault(unit.name, []).append((kind, sorted(subtypes)))
                    if not subtypes & before_creature:
                        narrowed.setdefault(unit.name, []).append((kind, sorted(subtypes)))
                else:
                    bare.setdefault(unit.name, []).append((kind, sorted(subtypes)))
                    if not subtypes & printed_bare:
                        dropped.setdefault(unit.name, []).append((kind, sorted(subtypes)))
    return paired, bare, narrowed, dropped


def test_no_program_reads_a_bare_creature_type_as_a_creature(census):
    _paired, _bare, narrowed, _dropped = census
    assert not narrowed, (
        "a bare creature type read as a creature of it (a Kindred permanent of "
        "the type is one, CR 109.2, 205.3m):\n  "
        + "\n  ".join(f"{name}: {rows}" for name, rows in sorted(narrowed.items()))
    )


def test_no_program_drops_a_printed_creature_beside_a_creature_type(census):
    _paired, _bare, _narrowed, dropped = census
    assert not dropped, (
        "a creature type with no card type the card never prints bare:\n  "
        + "\n  ".join(f"{name}: {rows}" for name, rows in sorted(dropped.items()))
    )


def test_the_census_examined_what_it_claims(census):
    """The floors, and readers the census is known to reach: targets, a sweep,
    a lord through the grammar and through the text table, a sacrifice and a
    tap cost, an entry trigger, a count, a static condition, an Aura's
    condition; and on the printed side, a lord and a pump that print
    "creatures"."""
    paired, bare, _narrowed, _dropped = census
    assert len(bare) >= 150, len(bare)
    assert len(paired) >= 30, len(paired)
    assert {
        "Tunnel", "Ali Baba", "Krosan Warchief", "Tivadar's Crusade",
        "Goblin King", "Zombie Master", "Acidic Sliver", "Arms Dealer",
        "Crookclaw Elder", "Aether Charge", "Riptide Director",
        "Cloudreach Cavalry", "Clutch of Undeath", "Fungal Bloom",
    } <= set(bare)
    assert {"Muscle Sliver", "Fortified Area", "Goblin Taskmaster"} <= set(paired)
