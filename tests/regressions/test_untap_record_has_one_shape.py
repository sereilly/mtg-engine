"""Two handlers that write one scratchpad record must write the same thing.

"At the beginning of your upkeep, you may untap target tapped creature an
opponent controls. If you do, untap this creature." (Soldevi Golem.)

``untap_target_permanent`` records what it untapped under
``untapped_permanents`` as a **tuple** of ids. ``untap_self`` then recorded
itself with ``results.setdefault("untapped_permanents", []).append(...)`` —
correct alone, and an ``AttributeError`` whenever a sibling had written first.
So accepting the Golem's own offer raised out of the upkeep step: for a seat
that takes defaults (an AI seat, the simulator) every time there was a tapped
creature across the table.

Found by driving every targeted trigger in the pool on a guarded board, which
is the only reason anything resolved this one: no test named the card.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack

_ENGINE = Path(__file__).resolve().parents[2] / "engine"


def _upkeep(catalog_by_name, *, opposing_tapped: bool):
    game = Game(players=[
        PlayerState("A", library=[catalog_by_name["Forest"]] * 12),
        PlayerState("B", library=[catalog_by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    golem = _nosick(Permanent(card=catalog_by_name["Soldevi Golem"]))
    game._put_permanent_onto_battlefield(0, golem, None)
    golem.tapped = True
    bears = _nosick(Permanent(card=catalog_by_name["Grizzly Bears"]))
    game._put_permanent_onto_battlefield(1, bears, None)
    bears.tapped = opposing_tapped
    game.active_player_index = 0
    game.start_turn(0)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return game, golem, bears


def test_soldevi_golem_untaps_a_creature_and_then_itself(catalog_by_name):
    """The offer taken: the opposing Grizzly Bears untaps, and because it did,
    so does the Golem. This raised ``'tuple' object has no attribute
    'append'``."""
    game, golem, bears = _upkeep(catalog_by_name, opposing_tapped=True)

    assert not bears.tapped
    assert not golem.tapped
    assert game.is_on_battlefield(golem) and game.is_on_battlefield(bears)


def test_soldevi_golem_stays_tapped_with_nothing_to_untap(catalog_by_name):
    """No tapped creature across the table: there is no target, nothing is
    untapped, and "if you do" does not happen — the Golem stays tapped."""
    _game, golem, bears = _upkeep(catalog_by_name, opposing_tapped=False)

    assert golem.tapped
    assert not bears.tapped


def _is_results(node) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "results"


def _appending_and_tuple_writers() -> dict:
    """``{record key: (list-append sites, tuple sites)}`` over ``engine/``.

    Only what an AST can see: a write through ``<x>.results`` under a string
    literal. A key held in a variable is invisible here, so this is a floor
    on the class and not a proof — it is the shape that was shipped."""
    appending: dict = defaultdict(list)
    tuples: dict = defaultdict(list)
    for path in sorted(_ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        where = path.relative_to(_ENGINE).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript) and _is_results(target.value)
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                        and (
                            isinstance(node.value, ast.Tuple)
                            or (
                                isinstance(node.value, ast.Call)
                                and isinstance(node.value.func, ast.Name)
                                and node.value.func.id == "tuple"
                            )
                        )
                    ):
                        tuples[target.slice.value].append(f"{where}:{node.lineno}")
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setdefault" and _is_results(node.func.value)
                and len(node.args) == 2 and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and isinstance(node.args[1], ast.List)
            ):
                appending[node.args[0].value].append(f"{where}:{node.lineno}")
    return {
        key: (appending[key], tuples[key])
        for key in appending if key in tuples
    }


def test_no_record_is_appended_to_in_one_handler_and_a_tuple_in_another():
    """``results.setdefault(key, []).append(...)`` beside ``results[key] =
    (...)`` is a crash waiting for the two to meet in one resolution. One key
    was written both ways (``untapped_permanents``); none is."""
    mixed = _appending_and_tuple_writers()

    assert not mixed, mixed


def test_the_scan_sees_the_shape_it_is_for(tmp_path, monkeypatch):
    """Backwards: the two lines that shipped, in a file of their own."""
    package = tmp_path / "engine"
    package.mkdir()
    (package / "sample.py").write_text(
        "def first(context, perm):\n"
        "    context.results['untapped_permanents'] = (perm,)\n"
        "def second(context, perm):\n"
        "    context.results.setdefault('untapped_permanents', []).append(perm)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "tests.regressions.test_untap_record_has_one_shape._ENGINE", package,
    )

    assert set(_appending_and_tuple_writers()) == {"untapped_permanents"}
