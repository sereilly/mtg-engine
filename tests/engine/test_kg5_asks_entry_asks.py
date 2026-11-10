"""Guard: an entry's "would enter" replacements put CR 616.1e's choice to the
affected player, and every reader of the entry tells a question still owed
from an entry a replacement took away.

``mixins/zone_funnels._begin_entry`` raised ``would_enter_battlefield`` with no
way to re-run the entry, so every seat took the default order there — Land
Equilibrium beside an Alliances land's unpaid toll, Containment Priest beside
a toll on a creature nobody cast — and ``tests/engine/test_kg4_asks_replacement_sites.py``
recorded the site as declined: its callers read "consumed" as "replaced" and
ran their continuation at once. Since round kg5 `asks` the site passes
``restart`` and ``_begin_entry`` returns ``ENTRY_SUSPENDED`` for an entry whose
question is owed; the answer re-runs it and runs the caller's ``then``
(``tests/regressions/test_kg5_asks_contended_entry.py`` drives the boards).

The kg4 census excuses ``_begin_entry`` as a whole for its one silent call —
the CR 614.17 "can't" (Worms of the Earth), asked first and alone — so this
holds the site **per kind**, and holds every caller of ``_begin_entry`` to
reading the suspension.
"""

from __future__ import annotations

import ast

from engine.replacements.registry import REPLACEMENTS
from tests.source_index import REPO_ROOT, python_files, source_text, source_tree

_ENGINE = REPO_ROOT / "engine"
_SITE = ("mixins/zone_funnels.py", "_begin_entry")


def _called(call: ast.Call) -> str:
    return getattr(call.func, "attr", getattr(call.func, "id", ""))


def _functions(mentioning: str):
    for path in python_files("engine"):
        if mentioning not in source_text(path):
            continue
        module = path.relative_to(_ENGINE).as_posix()
        for node in ast.walk(source_tree(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield module, node


def _site_calls() -> dict[str, list[bool]]:
    """``_begin_entry``'s ``apply_replacements`` calls: literal kind -> whether
    each passes ``restart``."""
    calls: dict[str, list[bool]] = {}
    for module, function in _functions("apply_replacements"):
        if (module, function.name) != _SITE:
            continue
        for node in ast.walk(function):
            if not (isinstance(node, ast.Call) and _called(node) == "apply_replacements"):
                continue
            kind = node.args[1].value if (
                len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
            ) else "?"
            asks = any(keyword.arg == "restart" for keyword in node.keywords)
            calls.setdefault(kind, []).append(asks)
    return calls


def test_the_entry_asks_and_only_the_cant_is_silent():
    calls = _site_calls()
    assert calls, f"{_SITE} raises no replacement event any more — update this guard"
    assert calls.get("would_enter_battlefield") == [True], calls
    assert calls.get("cant_enter_battlefield") == [False], calls
    assert set(calls) == {"would_enter_battlefield", "cant_enter_battlefield"}, calls


def test_the_cant_is_never_one_of_the_contenders():
    """CR 614.17c: an event that can't happen may be replaced only by a
    self-replacement effect — so Worms of the Earth is its own event, never an
    option the affected player could apply after a toll that sends the land to
    a graveyard."""
    cant = [c.key for c in REPLACEMENTS.get("cant_enter_battlefield", ())]
    contenders = [c.key for c in REPLACEMENTS.get("would_enter_battlefield", ())]
    assert cant == ["_lands_cannot_enter"], cant
    assert "_lands_cannot_enter" not in contenders, contenders
    # …and there is still something to ask about: a contention needs two.
    assert len(contenders) >= 2, contenders


def test_every_reader_of_an_entry_tells_a_question_from_a_replacement():
    readers = {
        f"{module}:{function.name}": function
        for module, function in _functions("_begin_entry")
        if function.name != "_begin_entry"
        and any(
            isinstance(node, ast.Call) and _called(node) == "_begin_entry"
            for node in ast.walk(function)
        )
    }
    # A floor: the lone entry, an event's close and the answer's re-run.
    assert len(readers) >= 3, sorted(readers)
    blind = sorted(
        label for label, function in readers.items()
        if not any(
            isinstance(node, ast.Name) and node.id == "ENTRY_SUSPENDED"
            for node in ast.walk(function)
        )
    )
    assert not blind, (
        "a caller of _begin_entry that reads None as 'replaced' without "
        "checking ENTRY_SUSPENDED runs its continuation for an entry whose "
        f"CR 616.1e question is still owed: {blind}"
    )
