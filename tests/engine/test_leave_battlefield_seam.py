"""Every battlefield exit reaches the CR 614 leaves-the-battlefield event.

"If the creature would leave the battlefield, exile it instead of putting it
anywhere else." (Dreams of the Dead.) The event has **no single fire site**: a
permanent's card leaves for a graveyard, a hand or a library, and those are
three different seams. Two of them —
``Game.put_card_into_hand``/``put_card_into_library`` — are handed a
``CardDefinition``, which a deck shares between every copy of a card
(``web/deck_builder.py`` builds ``[card] * count``), so the event cannot be
keyed to the card. It is keyed to the ``Permanent``, which the caller has and
the seam does not — hence the ``from_battlefield=`` keyword, and hence this
guard.

Why a guard and not a comment: the clause is a **drawback**. A caller that
moves a permanent to a hand and forgets the keyword does not crash and loses
nothing visible; it makes the card strictly better than the one printed, which
is the direction a missing rider is never noticed in.

Exile is deliberately not one of the destinations. A permanent already on its
way to exile is going where "exile it instead" would send it, so there is
nothing to replace and firing the event there would exile the card twice.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from tests.source_index import source_tree

ENGINE = pathlib.Path(__file__).resolve().parents[2] / "engine"

#: The two seams that must be told which permanent is leaving.
_ZONE_SEAMS = {"put_card_into_hand", "put_card_into_library"}

#: The one transition off the battlefield (CLAUDE.md, "Leaving the battlefield
#: is one transition"). A function that calls it and then places a card is
#: moving a permanent, whatever the local variable is called.
_REMOVERS = {"remove_from_battlefield", "remove_all_from_battlefield"}

#: Calls that look like a permanent's card and are not one, each with the reason
#: it is exempt. Keyed by ``(module suffix, enclosing function)`` rather than by
#: line number, which every edit above them would invalidate.
_NOT_A_BATTLEFIELD_EXIT = {
    # The *graveyard* branch of the same function: "Return this card to its
    # owner's hand" reaches whichever zone the object is in, and this arm is
    # the one where it is already in a graveyard (CR 608.2). The battlefield
    # arm above it passes the keyword.
    ("handlers/zones.py", "return_source_card_to_owners_hand"),
    # "Return target spell or creature to its owner's hand" (Unsubstantiate).
    # ``chosen`` is a StackItem, so ``chosen.card`` is a spell on the stack —
    # not a permanent, and not a battlefield exit. Its creature half goes
    # through ``_bounce_target_creature``, which does pass the keyword.
    ("handlers/zones.py", "return_spell_or_creature_to_hand"),
    # "…put it on top of its owner's library instead of into that player's
    # graveyard" (Memory Lapse). ``countered`` is a StackItem for the same
    # reason as the row above: a countered spell is an object on the stack
    # (CR 701.5a), so its card was never on a battlefield to leave one, and
    # there is no permanent for the seam to name.
    ("handlers/stack.py", "_redirect_countered_card"),
}


def _module_key(path: pathlib.Path) -> str:
    return path.relative_to(ENGINE).as_posix()


def _offending_calls() -> list[tuple[str, int, str, str]]:
    """Every zone-seam call that looks like a battlefield exit and says nothing.

    Two signals, because either alone misses a real caller. A card argument
    spelled ``<something>.card`` is a permanent's card by shape; and a function
    that also takes a permanent off the battlefield is moving one however the
    local variable is spelled (``return_source_card_to_owners_hand`` holds it
    in ``card``).
    """
    offenders: list[tuple[str, int, str, str]] = []
    for path in sorted(ENGINE.rglob("*.py")):
        tree = source_tree(path)
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            removes = any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _REMOVERS
                for node in ast.walk(function)
            )
            for node in ast.walk(function):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _ZONE_SEAMS
                    and len(node.args) >= 2
                ):
                    continue
                if any(kw.arg == "from_battlefield" for kw in node.keywords):
                    continue
                argument = ast.unparse(node.args[1])
                if not (removes or argument.endswith(".card")):
                    continue
                if (_module_key(path), function.name) in _NOT_A_BATTLEFIELD_EXIT:
                    continue
                offenders.append(
                    (_module_key(path), node.lineno, function.name, argument)
                )
    return offenders


def test_every_battlefield_exit_to_a_hand_or_library_names_its_permanent():
    offenders = _offending_calls()
    assert not offenders, (
        "these calls move a permanent's card off the battlefield without "
        "telling the seam which permanent, so a CR 614 "
        "leaves-the-battlefield replacement cannot see them: "
        + "; ".join(
            f"{module}:{line} in {function} ({argument})"
            for module, line, function, argument in offenders
        )
    )


def test_the_exemptions_still_name_real_functions():
    """An exemption whose function has been renamed or deleted is a hole that
    reads as a pass. Checked in both directions, like every allow-list in this
    suite."""
    present = set()
    for path in sorted(ENGINE.rglob("*.py")):
        tree = source_tree(path)
        for function in ast.walk(tree):
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                present.add((_module_key(path), function.name))
    stale = _NOT_A_BATTLEFIELD_EXIT - present
    assert not stale, f"exemptions naming functions that no longer exist: {stale}"


def test_the_graveyard_exit_goes_through_the_one_transition():
    """The third destination needs no keyword because it has a seam of its own:
    ``_permanent_to_graveyard`` takes the ``Permanent`` and asks the event
    itself. What it needs instead is that nothing reaches a graveyard around
    it — Kudzu's land destruction did, and skipped the dies-triggers, the death
    count and every CR 614 replacement along with this one."""
    offenders = []
    for path in sorted(ENGINE.rglob("*.py")):
        tree = source_tree(path)
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _REMOVERS
                for node in ast.walk(function)
            ):
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and ast.unparse(node.func.value).endswith("graveyard")
                    # A card taken out of *exile* and put into a graveyard is
                    # not a battlefield exit (`put_self_into_zone`), and a
                    # resolved spell going to its owner's graveyard is not one
                    # either (`_resolve_card`).
                    and ast.unparse(node.args[0]).endswith((".card",))
                    and function.name not in ("put_self_into_zone",)
                ):
                    offenders.append(
                        (_module_key(path), node.lineno, function.name)
                    )
    assert not offenders, (
        "these functions take a permanent off the battlefield and then append "
        "its card to a graveyard by hand, skipping "
        "`_permanent_to_graveyard`: " + "; ".join(map(str, offenders))
    )


@pytest.mark.parametrize("seam", sorted(_ZONE_SEAMS))
def test_the_seams_accept_the_keyword(seam):
    """The keyword is keyword-only and defaults to None, so every existing
    caller is a caller that says "this is not a battlefield exit" rather than
    one that forgot."""
    import inspect

    from engine.mixins.helpers import GameHelpersMixin

    parameter = inspect.signature(getattr(GameHelpersMixin, seam)).parameters[
        "from_battlefield"
    ]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
