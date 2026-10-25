"""Guard: a card off the battlefield is asked its colour with its seat in hand.

CR 613.1 applies the layers to an **object**, and CR 109.1's objects include a
card in a hand, a graveyard, a library or exile and a spell on the stack.
"Nonland permanents you control are white. **The same is true for spells you
control and nonland cards you own that aren't on the battlefield.**"
(Celestial Dawn) is a layer-5 effect over exactly those objects, and it is a
property of a *seat*: whose card it is decides whether it is white. So the one
reader of an off-battlefield colour, ``object_colors.card_colors``, needs the
game and the card's seat, and a caller that cannot say gets the printed answer.

The card matchers are where every printed narrowing on such a card is asked —
"target **blue or red** creature card from your graveyard" (Crypt Angel),
"search your library for a **green** creature card" (Natural Order), "reveal
any number of **white** cards in your hand" (Scent of Jasmine) — and before the
round that wrote this file most of their calls handed over neither: 86 of 133
calls in 40 modules, and ``graveyard_card_matches``, ``graveyard_slots_matching``,
``positions_named`` and ``_exile_search_matches`` had no way to be handed one at
all. Under a Dawn the
graveyard picker offered a red creature card to "target green card" (Revive)
and refused one to "target white or black creature card" (Dreams of the Dead),
which is the card backwards both ways, and nothing crashed.

So every call of a matcher in ``engine/`` and ``web/`` names ``game=`` and
``owner=``. Spelled out at the call, keyword by keyword, because a default of
``None`` is the silent printed answer this guard exists to keep out: a caller
that genuinely has no seat writes ``owner=None`` where a reviewer can see it,
and :data:`EXPLICITLY_UNSEATED` holds those to a count and a reason.

``tests/regressions/test_kg_colour_dawn_census.py`` is the behaviour half: the
pool's colour-narrowed cards driven under a Dawn on each side of the table.
"""

from __future__ import annotations

import ast
import inspect

from tests.source_index import REPO_ROOT, python_files, source_tree

#: The matchers that answer a printed noun phrase about a card that is not a
#: permanent — or wrap one that does. Every one of them reaches
#: ``object_colors.card_colors`` (directly, or through ``_card_matches_filter``
#: / ``search_matches``) and so needs the game and the card's seat.
READERS = {
    "graveyard_card_matches": "engine.handlers._filters",
    "graveyard_slots_matching": "engine.handlers._filters",
    "_card_matches_filter": "engine.handlers._filters",
    "card_matches_any": "engine.subject_filters",
    "search_matches": "engine.search_filters",
    "slot_assignment": "engine.search_filters",
    "positions_named": "engine.graveyard_order",
    "_exile_search_matches": None,  # a staticmethod on the search-choice mixin
}

#: module -> (calls handing ``owner=None`` on purpose, why). Held in both
#: directions: one more is a new seatless read to justify, one fewer is a stale
#: allowance.
EXPLICITLY_UNSEATED: dict[str, tuple[int, str]] = {
    "engine/damage_ledger.py": (
        1,
        "the spell's colours are already folded onto the card by "
        "`_cast_as_it_was` (`_stack_item_colors`, which asks the caster's "
        "seat and the Lace record); asking the seat again would let a Dawn "
        "override a Lace that is newer than it",
    ),
}


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _reader_calls():
    calls = []
    for path in python_files("engine", "web"):
        module = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(source_tree(path)):
            if isinstance(node, ast.Call) and _call_name(node) in READERS:
                keywords = {k.arg: k.value for k in node.keywords if k.arg}
                calls.append((module, node.lineno, _call_name(node), keywords))
    return calls


def test_every_matcher_call_names_the_game_and_the_seat():
    """A matcher handed no seat answers with the printed colours, in silence."""
    calls = _reader_calls()
    # The floor: the sweep found the population it is about. 132 calls when
    # this was written; a rename that blinds the scan reads as a pass otherwise.
    assert len(calls) >= 100, f"only {len(calls)} matcher calls found"
    assert {name for _m, _l, name, _k in calls} == set(READERS)
    missing = [
        f"{module}:{line}: {name} without {', '.join(k for k in ('game', 'owner') if k not in kws)}"
        for module, line, name, kws in calls
        if "game" not in kws or "owner" not in kws
    ]
    assert not missing, (
        "a card matcher called without the game and the card's seat answers "
        "from the printed colours (CR 613.1 asks the object) — pass game= and "
        "owner= (the card's owner; a spell's controller), or owner=None with a "
        "reason in EXPLICITLY_UNSEATED:\n  " + "\n  ".join(missing)
    )


def test_an_explicitly_unseated_call_is_one_the_table_names():
    counted: dict[str, int] = {}
    for module, _line, _name, kws in _reader_calls():
        owner = kws.get("owner")
        if isinstance(owner, ast.Constant) and owner.value is None:
            counted[module] = counted.get(module, 0) + 1
    expected = {module: count for module, (count, _why) in EXPLICITLY_UNSEATED.items()}
    assert counted == expected, (
        f"owner=None calls {counted} != the table {expected}: a new seatless "
        "read needs its reason here, and a drained one leaves the table"
    )


def test_every_reader_takes_the_game_and_the_seat():
    """The guard above is only as good as the readers' signatures: a matcher
    that took no ``owner`` would make every call site's keyword a TypeError
    nobody wrote a test for — or, through ``**kwargs``, a silent drop."""
    import importlib

    from engine.mixins.stack.choices.search import LibrarySearchChoicesMixin

    for name, module in READERS.items():
        function = (
            getattr(importlib.import_module(module), name) if module
            else getattr(LibrarySearchChoicesMixin, name)
        )
        parameters = inspect.signature(function).parameters
        assert {"game", "owner"} <= set(parameters), (name, list(parameters))
        assert all(
            parameters[key].kind is inspect.Parameter.KEYWORD_ONLY
            for key in ("game", "owner")
        ), name


# ---------------------------------------------------------------------------
# The bare attribute, one step past the matchers
# ---------------------------------------------------------------------------
#
# ``tests/engine/test_layer_reads.py`` ratchets ``card.colors`` spelled as an
# attribute; ``getattr(card, "colors", ())`` is the same read spelled so a
# missing field cannot raise, and the regex there cannot see a string literal.
# Three of the reads this round drained were spelled that way (Grindstone's
# shared colour, Justice's red spell, the Titan's triggering spell).

#: module -> (count, why the printed colours are what it means).
GETATTR_COLOR_READS: dict[str, tuple[int, str]] = {
    "engine/object_colors.py": (
        1, "the reader itself: the printed colours it starts from (CR 202.2)",
    ),
    "engine/commander.py": (
        1, "colour identity (CR 903.4) is the printed mana symbols, which no "
        "colour-changing effect touches",
    ),
    "engine/damage_ledger.py": (
        1, "compares the spell's folded colours with the printed ones to decide "
        "whether a replaced card is needed at all",
    ),
    "engine/damage_source_colors.py": (
        1, "a damage source asked with no game: the printed answer, the safe "
        "direction (every engine caller passes the game)",
    ),
}


def _getattr_color_reads() -> dict[str, int]:
    counted: dict[str, int] = {}
    for path in python_files("engine"):
        module = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(source_tree(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "colors"
            ):
                counted[module] = counted.get(module, 0) + 1
    return counted


def test_no_new_printed_colour_read_by_getattr():
    counted = _getattr_color_reads()
    expected = {module: count for module, (count, _why) in GETATTR_COLOR_READS.items()}
    assert counted == expected, (
        f"getattr(..., 'colors') reads {counted} != the table {expected}: a card "
        "off the battlefield is asked through object_colors.card_colors with its "
        "seat; a read that really means the printed mana cost goes in the table "
        "with its reason, and a drained one leaves it"
    )
