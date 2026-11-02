"""Guard: a card off the battlefield is asked its subtypes with its seat in hand.

The type twin of ``test_kg_colour_off_battlefield_reads.py``. CR 613.1 applies
the layers to an **object**, and "the same is true for creature spells you
control and creature cards you own that aren't on the battlefield"
(Conspiracy) is a layer-4 effect over objects with no permanent to ask — so the
one reader of an off-battlefield object's subtypes,
``object_creature_types.card_creature_types``, takes the game and the card's
seat, and ``search_filters.card_has_type`` asks it for a creature-type word
when it is told the seat.

``printed_characteristics.printed_shape`` is the printed parse that reader
starts from, and its **card-type** half is the whole answer off the battlefield
(nothing in the pool changes a card's card type there). Its **subtype** half is
not: round kg3 found it read directly by the graveyard matcher ("return target
Mercenary card", Strongarm Thug), a cast trigger ("whenever you cast a Dog
spell", Rin and Seri), the counter-class reader and Aphetto Dredging's default
— each blind to a Conspiracy. So the subtype half is ratcheted here: a read is
either the reader itself, the layer system's own seed, or a reason in
:data:`PRINTED_SUBTYPE_READS`.

``tests/regressions/test_kg3_types_conspiracy_census.py`` is the behaviour half.
"""

from __future__ import annotations

import ast

from tests.source_index import REPO_ROOT, python_files, source_tree

#: module -> (count, why the printed subtypes are what it means).
PRINTED_SUBTYPE_READS: dict[str, tuple[int, str]] = {
    "engine/object_creature_types.py": (
        1, "the reader itself: the printed parse it starts from (CR 205.3) "
        "before its owner's static is asked",
    ),
    "engine/type_layer.py": (
        1, "a permanent's layer-4 seed off its effective card — the copiable "
        "values every layer starts from (CR 613.2c)",
    ),
    "engine/handlers/types.py": (
        1, "CR 205.1a: the copiable line a card type set by a Licid's sentence "
        "replaces, read off a permanent's effective card",
    ),
}


def _parents(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _reads_the_subtypes(call, parents) -> bool:
    """Whether the result of a ``printed_shape(...)`` call has its subtype
    half read. Index 0 and an unpacking whose second name starts with ``_``
    read the card types alone; anything else (index 1, a named second
    target, the pair handed on whole) counts as a subtype read."""
    parent = parents.get(call)
    if isinstance(parent, ast.Subscript) and parent.value is call:
        index = parent.slice
        return not (isinstance(index, ast.Constant) and index.value == 0)
    if isinstance(parent, ast.Assign) and parent.value is call:
        target = parent.targets[0]
        if isinstance(target, ast.Tuple) and len(target.elts) == 2:
            second = target.elts[1]
            return not (isinstance(second, ast.Name) and second.id.startswith("_"))
    return True


def _printed_subtype_reads() -> tuple[dict[str, int], int]:
    counted: dict[str, int] = {}
    calls = 0
    for path in python_files("engine", "web"):
        module = path.relative_to(REPO_ROOT).as_posix()
        tree = source_tree(path)
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None
            )
            if name != "printed_shape":
                continue
            calls += 1
            if _reads_the_subtypes(node, parents):
                counted[module] = counted.get(module, 0) + 1
    return counted, calls


def test_printed_subtypes_are_read_only_where_they_are_meant():
    counted, calls = _printed_subtype_reads()
    # The floor: the scan found the population it is about (fourteen calls
    # when this was written, most of them card-type reads).
    assert calls >= 10, f"only {calls} printed_shape calls found"
    expected = {module: count for module, (count, _why) in PRINTED_SUBTYPE_READS.items()}
    assert counted == expected, (
        f"printed_shape subtype reads {counted} != the table {expected}: a "
        "card off the battlefield is asked its subtypes through "
        "object_creature_types.card_creature_types with its seat (CR 613.1 — "
        "its owner's Conspiracy retypes it, CR 205.1a); a read that really "
        "means the printed line goes in the table with its reason, and a "
        "drained one leaves it"
    )


def test_card_has_type_takes_the_game_and_the_seat():
    """The seat-aware half of ``card_has_type`` is keyword-only, so a caller
    that cannot say whose card it is gets the printed answer visibly."""
    import inspect

    from engine.search_filters import card_has_type

    parameters = inspect.signature(card_has_type).parameters
    assert {"game", "owner"} <= set(parameters)
    assert all(
        parameters[key].kind is inspect.Parameter.KEYWORD_ONLY
        for key in ("game", "owner")
    )
