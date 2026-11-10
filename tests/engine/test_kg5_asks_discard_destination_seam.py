"""Guard: a discarded card's destination is settled by one CR 616.1 process,
whichever seam discarded it.

A card is discarded through two seams — taken from the player
(``Game._discard_card``) or chosen by them
(``handlers/discards._resolve_one_discard``) — and every effect that replaces
where it goes (Dodecapod's battlefield, madness's exile, Library of Leng's
library top: the ``discard`` event; Forbidden Crypt's and Yawgmoth's Will's
exile, Legacy Weapon's shuffle: the graveyard move joined to it) is one
contention set, whose order the discarding player chooses (CR 616.1e). Until
round kg5 the chosen seam called Dodecapod's and madness's bodies itself, in a
fixed order ahead of the graveyard seam, so neither was ever asked against a
graveyard effect on a discard the player chose
(``tests/regressions/test_kg5_asks_chosen_discard.py`` drives the boards).

So: the bodies of the ``discard`` event's effects are run only by their
registered interceptors, and both seams reach the one destination.
"""

from __future__ import annotations

import ast

from engine.replacements.registry import REPLACEMENTS
from tests.source_index import REPO_ROOT, python_files, source_text, source_tree

_ENGINE = REPO_ROOT / "engine"

#: The effect bodies the ``discard`` event's interceptors run — the functions
#: a seam would call to apply one of them outside the process.
_BODIES = ("discarded_onto_battlefield", "exile_madness_card")

#: The modules a cost is paid in (``tests/engine/test_discard_cost_seam.py``):
#: a discard there must reach ``_discard_card(..., as_cost=True)``, never the
#: chosen seam, which offers Library of Leng to an effect's discard.
_COST_MODULES = (
    "mixins/stack/activation_charges.py",
    "mixins/stack/cast_additional_costs.py",
    "mixins/stack/cast_alternative_costs.py",
    "mixins/stack/card_activation.py",
)


def _called(call: ast.Call) -> str:
    return getattr(call.func, "attr", getattr(call.func, "id", ""))


def _registered_kind(function: ast.FunctionDef) -> str | None:
    for decorator in function.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and _called(decorator) == "replacement_effect"
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
        ):
            return decorator.args[0].value
    return None


def _functions(*mentioning: str):
    """Every function in an ``engine/`` module whose text mentions one of
    *mentioning*: (module, function node). The shared, cached trees."""
    for path in python_files("engine"):
        if not any(name in source_text(path) for name in mentioning):
            continue
        tree = source_tree(path)
        module = path.relative_to(_ENGINE).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield module, node


def _calls_in(function) -> list[str]:
    return [
        _called(node) for node in ast.walk(function) if isinstance(node, ast.Call)
    ]


def test_a_discard_effect_body_runs_only_through_its_interceptor():
    examined, outside = 0, []
    for module, function in _functions(*_BODIES):
        for name in _calls_in(function):
            if name not in _BODIES:
                continue
            examined += 1
            if _registered_kind(function) != "discard":
                outside.append(f"{module}:{function.name} calls {name}")
    # A floor on what was examined: each body has its interceptor.
    assert examined >= len(_BODIES), examined
    assert not outside, (
        "a discard replacement applied outside the discard's CR 616.1 process "
        "is never asked against the effects it contends with (616.1e) — call "
        f"Game.discarded_card_destination instead: {outside}"
    )
    # …and the interceptors are the live registry's.
    assert len(REPLACEMENTS.get("discard", ())) >= 3


def test_both_discard_seams_reach_the_one_destination():
    seams = {
        ("mixins/draws_and_discards.py", "_discard_card"),
        ("handlers/discards.py", "_resolve_one_discard"),
    }
    found = {
        (module, function.name): "discarded_card_destination" in _calls_in(function)
        for module, function in _functions("discarded_card_destination")
        if (module, function.name) in seams
    }
    assert set(found) == seams, f"a seam moved: {sorted(seams - set(found))}"
    assert all(found.values()), found


def test_no_cost_is_paid_through_the_chosen_seam():
    """The chosen seam offers Library of Leng whenever its prompt did not
    (the Library reaches an effect's discard, whoever controls the effect);
    "costs aren't effects" (its 2004-10-04 ruling), so no cost step of a cast
    or an activation (CR 601.2h, 602.2b) may pay a discard through it.

    (A cost paid as a spell or ability **resolves** — CR 118.12's "you may
    discard a card. If you don't, …", Masticore's upkeep — still reaches the
    chosen seam through ``may``'s discard prompt, which offers the library
    top: measured and left by round kg5 `asks`, not held here.)"""
    offenders = [
        f"{module}:{function.name}"
        for module, function in _functions("_resolve_one_discard")
        if module in _COST_MODULES
        and "_resolve_one_discard" in _calls_in(function)
    ]
    assert not offenders, offenders
    assert all((_ENGINE / module).exists() for module in _COST_MODULES)
