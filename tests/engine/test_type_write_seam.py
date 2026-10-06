"""Guard: a type-changing effect is recorded in one place, with its timestamp.

CR 613.7 orders the effects in a layer by timestamp, and a resolved effect's is
"the time it's created" (CR 613.7b). Five sites wrote a permanent's gained or
lost types by appending a dict to a metadata list — four handlers in
``handlers/board_misc.py`` and one in ``handlers/zones.py`` — and none of them
recorded when. The layer bridge had nothing to order by and gave both lists the
constant 0, additions in front of removals: a Snow-Covered Forest thawed by
Arcum's Weathervane and then frozen again was not snow, and a land frozen under
Melting stayed thawed although the freeze was the later effect
(``tests/rules/test_type_effects_timestamp_order.py`` is the census).

``engine/type_changes.py`` is the write API now, with the stamp inside
``gain_types`` / ``lose_types``. This file is what keeps it the only one — the
layer-4 twin of ``test_color_write_seam.py``, and built the same way: a sixth
direct write would be a sixth effect with no timestamp, and it would not fail
anything else, because an unstamped record reads as older than everything,
which is wrong only in a game where something else is changing the same
permanent's types.

**Read off the AST, never as text**, for the reason that file gives: a pattern
that *is* a string literal can never match a line with its string literals
blanked.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine import type_changes
from tests.source_index import (REPO_ROOT, python_files, source_tree,
                                string_key_uses)

OWNER = "engine/type_changes.py"

#: The metadata keys nothing but the write API may spell, anywhere.
_PRIVATE_KEYS = (
    type_changes.GAINED_TYPES,
    type_changes.LOST_TYPES,
    type_changes.DERIVED_LOST_SUPERTYPES,
    type_changes.STATIC_TYPE_ORDER,
)

#: The two constants' *names*, which a module could import and index a
#: permanent's metadata with — the same poke with the string spelled once
#: removed, and invisible to a scan for the string.
_KEY_NAMES = ("GAINED_TYPES", "LOST_TYPES", "DERIVED_LOST_SUPERTYPES", "STATIC_TYPE_ORDER")

#: Who may *import* a key's name, and why. Held in both directions: one more
#: is a new holder of the key to justify, one fewer a stale allowance.
_NAME_IMPORTERS = {
    "engine/layer_bridge.py": (
        ("GAINED_TYPES", "LOST_TYPES"),
        "re-exported under the names this module has always exported — three "
        "tests another round wrote import them from here to build a board by "
        "hand; nothing in the module indexes with either",
    ),
}

#: module -> how many times it names each writer, and what the uses are. Both
#: directions: a count that rose is a new type-writing effect (welcome — it is
#: stamped — but worth a look), one that fell a stale row.
_WRITER_USES = {
    "engine/handlers/board_misc.py": {
        "gain_types": (
            3, "become_aura_with_enchant, gain_type, change_supertype's gaining half",
        ),
        "lose_types": (
            2, "become_aura_with_enchant's replaced types, change_supertype's losing half",
        ),
    },
    "engine/handlers/zones.py": {
        "lose_types": (1, "return_source_card_to_battlefield's 'as a non-Aura enchantment'"),
    },
}

#: The readers of what is recorded: the layer-4 collector, and nothing else.
_READERS = (
    "gained_types", "lost_types", "derived_lost_supertypes", "static_type_order",
)


def _modules() -> list[tuple[str, Path]]:
    return [
        (str(path.relative_to(REPO_ROOT)).replace("\\", "/"), path)
        for path in python_files("engine", "web")
    ]


def _name_loads(path: Path, names: tuple[str, ...]) -> list[tuple[int, str]]:
    """Every place *path* **uses** one of *names* as a bare name or attribute
    (``GAINED_TYPES``, ``type_changes.GAINED_TYPES``) — imports excluded."""
    found = []
    for node in ast.walk(source_tree(path)):
        if isinstance(node, ast.Name) and node.id in names:
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr in names:
            found.append((node.lineno, node.attr))
    return sorted(found)


def _imported_names(path: Path, names: tuple[str, ...]) -> list[str]:
    return sorted(
        alias.name
        for node in ast.walk(source_tree(path))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in names
    )


def test_the_key_reader_sees_a_string_constant():
    """The scanner is sighted — asked of the one module that must spell every
    key, it finds each of them."""
    spelled = {key for _line, key in string_key_uses(REPO_ROOT / OWNER, _PRIVATE_KEYS)}
    assert spelled == set(_PRIVATE_KEYS)


def test_no_module_but_the_write_api_spells_a_type_channel():
    """A sixth direct write would be an effect with no timestamp. The keys only
    ``engine/type_changes.py`` has any business naming appear nowhere else in
    ``engine/`` or ``web/`` — not as a write, not as a read."""
    offenders = []
    examined = 0
    for name, path in _modules():
        examined += 1
        if name == OWNER:
            continue
        offenders.extend(
            f"  {name}:{line}: {key!r}" for line, key in string_key_uses(path, _PRIVATE_KEYS)
        )
    assert not offenders, (
        "a type channel named outside engine/type_changes.py — record the "
        "effect with gain_types(perm, …) / lose_types(perm, …) so it is "
        "stamped (CR 613.7b), and read it through the collector:\n"
        + "\n".join(offenders)
    )
    # "No offenders" over a sweep that opened nothing is a true statement
    # about nothing.
    assert examined >= 400, examined


def test_no_module_indexes_a_permanent_with_an_imported_key():
    """The same poke with the string once removed: a module that imports
    ``GAINED_TYPES`` and writes ``perm.metadata[GAINED_TYPES]`` spells no
    string at all. So the *names* are held too — used nowhere outside the
    write API, and imported only where the table above says, for the reason it
    gives."""
    used, imported = {}, {}
    for name, path in _modules():
        if name == OWNER:
            continue
        loads = _name_loads(path, _KEY_NAMES)
        if loads:
            used[name] = loads
        names = _imported_names(path, _KEY_NAMES)
        if names:
            imported[name] = tuple(names)
    assert not used, (
        "a type channel's key used outside engine/type_changes.py — a write "
        "through it is a write with no timestamp:\n"
        + "\n".join(f"  {name}: {loads}" for name, loads in sorted(used.items()))
    )
    assert imported == {
        name: names for name, (names, _why) in _NAME_IMPORTERS.items()
    }, imported


def test_the_writers_are_the_ones_counted():
    """Every type-writing effect goes through ``gain_types`` / ``lose_types``,
    and which handlers those are is written down — module by module and count
    by count, so a writer added anywhere is a line in this table and a reader
    of this file knows where layer 4's recorded half comes from."""
    counted: dict[str, dict[str, int]] = {}
    for name, path in _modules():
        if name == OWNER:
            continue
        for _line, word in _name_loads(path, ("gain_types", "lose_types")):
            counted.setdefault(name, {}).setdefault(word, 0)
            counted[name][word] += 1
    allowed = {
        name: {word: count for word, (count, _why) in uses.items()}
        for name, uses in _WRITER_USES.items()
    }
    assert counted == allowed, (
        "gain_types / lose_types are named somewhere this table does not "
        f"account for (or a row is stale): counted {counted}, allowed {allowed}"
    )


def test_the_collector_is_the_only_reader_of_the_recorded_changes():
    """One consumer: ``layer_bridge`` applies the layer. A second caller of
    ``gained_types()`` is a second opinion about what the effects add up to —
    ``Permanent.has_type`` / ``has_supertype`` are the answer."""
    callers: dict[str, set[str]] = {}
    for name, path in _modules():
        if name == OWNER:
            continue
        # Calls, not names: a handler may well hold a local it calls
        # ``gained_types`` (the words a sentence set), which reads nothing.
        for node in ast.walk(source_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            word = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if word in _READERS:
                callers.setdefault(word, set()).add(name)
    assert callers == {word: {"engine/layer_bridge.py"} for word in _READERS}, callers


def _type_writing_instructions():
    """Every one-shot type-writing instruction over both manifest roles, with
    the card it is on."""
    import dataclasses

    from engine.card_loader import load_cards, manifest_set_paths
    from engine.oracle import compiled_units
    from engine.oracle_types import OracleInstruction

    def walk(value, seen):
        if id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, OracleInstruction):
            yield value
            yield from walk(value.payload, seen)
        elif isinstance(value, dict):
            for item in value.values():
                yield from walk(item, seen)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                yield from walk(item, seen)
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            for field in dataclasses.fields(value):
                yield from walk(getattr(value, field.name), seen)

    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    found = []
    for card, program in compiled_units(pool.values()):
        for instruction in walk(program, set()):
            if instruction.kind in ("gain_type", "change_supertype"):
                found.append((card.name, instruction))
    return len(pool), found


def test_every_recorded_type_change_in_the_pool_has_a_duration_a_sweep_ends():
    """A record carries its own duration and is ended by the sweep that owns
    it: never, the cleanup step (CR 514.2), or its controller's next upkeep.
    A card whose type change lasts "until end of combat" would be written with
    a duration nothing sweeps — an effect that never ended, silently. This is
    the test that says so the day such a card is ingested."""
    pool_size, found = _type_writing_instructions()
    durations = {
        str(instruction.payload.get("duration", "permanent"))
        for _name, instruction in found
    }
    assert durations <= {"permanent", "until_end_of_turn", "until_your_next_upkeep"}, (
        "a type change with a duration no sweep ends: "
        + str(sorted({
            f"{name}: {instruction.payload.get('duration')}"
            for name, instruction in found
        }))
    )
    # The floor: both manifest roles, and the cards the census is built on.
    assert pool_size >= 4700, pool_size
    assert {name for name, _instruction in found} >= {
        "Arcum's Weathervane", "Ashnod's Transmogrant", "Karn, Silver Golem",
        "Xenic Poltergeist",
    }, sorted({name for name, _instruction in found})


@pytest.mark.parametrize("write", ["gain_types", "lose_types"])
def test_the_write_api_stamps_the_record_it_writes(write):
    """The write API's own contract, stated on a permanent: the words are
    stored as given, the stamp beside them is the clock's, a second write is a
    second record with a later one, and the reader reports exactly that."""
    from engine.continuous import next_timestamp
    from engine.models import CardDefinition, Permanent

    perm = Permanent(card=CardDefinition(
        name="Test Forest", mana_cost="", cmc=0.0, type_line="Basic Land — Forest",
        oracle_text="", colors=(), color_identity=("G",), keywords=(),
        produced_mana=("G",), raw={},
    ))
    read = getattr(type_changes, write.replace("gain", "gained").replace("lose", "lost"))
    assert read(perm) == ()

    watermark = next_timestamp()
    first = getattr(type_changes, write)(
        perm, supertypes=["Snow"], source="test", duration="until_end_of_turn",
    )
    assert first > watermark
    (recorded,) = read(perm)
    assert (recorded["supertypes"], recorded["timestamp"]) == (["snow"], first)
    assert recorded["duration"] == "until_end_of_turn"

    second = getattr(type_changes, write)(perm, card_types=["artifact"], source="test")
    assert second > first
    assert [record["timestamp"] for record in read(perm)] == [first, second]

    # Ending drops what the predicate names and nothing else, from either list.
    assert type_changes.end_type_changes(
        perm, lambda record: record.get("duration") == "until_end_of_turn"
    ) == 1
    assert [record["timestamp"] for record in read(perm)] == [second]


def test_a_later_removal_and_a_later_addition_each_win_on_one_permanent():
    """What the stamp is for, on the smallest board there is: of "becomes snow"
    and "is no longer snow" on one land, the later is what the land is — in
    both orders. Unstamped, both lists applied at the constant 0 with the
    additions first, so the removal won whichever came last."""
    from engine.models import CardDefinition, Permanent

    def forest():
        return Permanent(card=CardDefinition(
            name="Test Forest", mana_cost="", cmc=0.0, type_line="Basic Land — Forest",
            oracle_text="", colors=(), color_identity=("G",), keywords=(),
            produced_mana=("G",), raw={},
        ))

    thawed_then_frozen = forest()
    type_changes.lose_types(thawed_then_frozen, supertypes=["snow"], source="thaw")
    type_changes.gain_types(thawed_then_frozen, supertypes=["snow"], source="freeze")
    assert thawed_then_frozen.has_supertype("snow")

    frozen_then_thawed = forest()
    type_changes.gain_types(frozen_then_thawed, supertypes=["snow"], source="freeze")
    type_changes.lose_types(frozen_then_thawed, supertypes=["snow"], source="thaw")
    assert not frozen_then_thawed.has_supertype("snow")
    assert frozen_then_thawed.has_supertype("basic")
