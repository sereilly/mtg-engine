"""Census: every refused cast or activation reaches the one refusal seam, and
none writes to the shared log.

``game.log`` is one list, served whole to every seat (``web/state_view.py``),
so a line in it is an announcement. CR 733.1 has an illegal action reversed —
"no abilities trigger and no effects apply as a result of an undone action" —
and CR 733.2 hands the player priority back, so a refusal is an answer to the
actor and nothing else. Every refusal site appended its reason to the log
before returning it, and "insufficient mana for Exalted Angel" about a card in
the actor's hand reached the other seat's payload (Onslaught's Phase 5).

``engine/refusals.py`` is the seam: :func:`~engine.refusals.refuse` is the only
constructor of a refused result and writes nothing, and the four attempt
wrappers take back whatever the attempt wrote before it was refused
(:func:`~engine.refusals.take_back_refused_attempt`). Three halves:

* **Structural** — an AST walk of every module of ``engine/`` and ``web/``
  (walked, not listed, with a floor on what it read): a ``SimulationResult``
  whose ``supported`` is anything but the literal ``True`` is built in the seam
  and nowhere else; no refusal's straight-line tail appends to ``log``; each
  attempt wrapper takes a refusal back.
* **Behavioural** — refusals driven over the pool (a cast from an empty pool, a
  cast with no target named, each battlefield, hand and graveyard ability from
  an empty pool): every refused result is a :class:`~engine.refusals.Refusal`
  and leaves ``game.log`` exactly as it found it, with floors on how many
  refusals and how many distinct reasons it read.
* **The three announcements measured before a refusal** — Caller of the
  Hunt's chosen creature type, Avatar of Will's reduction, Phyrexian
  Splicer's chosen keyword — each taken back with the refusal.

Validated backwards on the base (``main`` at ``f41b06e3``): the structural walk
found 96 refused results built outside any seam and 87 of them with the log
append directly before the return; the behavioural sweep found 13,458 refused
attempts over the shipped pool, every one of which wrote a line and 13,400 of
which named the card.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import engine.refusals as refusals_module
from engine import Game, PlayerState
from engine.faces import face_cards
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.refusals import Refusal
from tests.helpers import stable_sample

_ROOT = Path(__file__).resolve().parents[2]
_SEAM = Path(refusals_module.__file__).resolve()

#: The two ``SimulationResult``s with a computed ``supported`` that are not
#: refusals: a mana ability resolving inline as it is activated (CR 605.3a,
#: 605.3b), whose ``supported`` is its own effect's outcome *after* its costs
#: were paid. Not an action reversed — an action taken that did not work — so
#: neither is a ``Refusal`` and neither is taken back from the log. Keyed by
#: module and enclosing function; each must still be there.
_NOT_REFUSALS = {
    ("engine/mixins/stack/activation.py", "_activate_onto_stack"),
    ("engine/mixins/stack/card_activation.py", "_activate_from_hand"),
}

#: The attempt wrappers: the only callers of the four private announcement
#: functions, and so the place a refusal from any of their ninety-odd returns
#: comes back through.
_ATTEMPTS = {
    "engine/mixins/stack/casting.py": "queue_from_hand",
    "engine/mixins/stack/activation.py": "queue_permanent_ability",
    "engine/mixins/stack/card_activation.py": (
        "activate_from_hand", "activate_from_graveyard",
    ),
}


def _modules():
    paths = [
        path for package in ("engine", "web")
        for path in sorted((_ROOT / package).rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    # Floor: the walk reads the packages, so a module that splits is still in
    # it; under this it has stopped reading them.
    assert len(paths) >= 600, len(paths)
    return paths


def _called(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _supported_argument(call: ast.Call):
    if len(call.args) >= 2:
        return call.args[1]
    return next((kw.value for kw in call.keywords if kw.arg == "supported"), None)


def _is_refused_construction(node) -> bool:
    """A ``SimulationResult(...)`` whose ``supported`` is not literally True."""
    if not isinstance(node, ast.Call) or _called(node) != "SimulationResult":
        return False
    flag = _supported_argument(node)
    return not (isinstance(flag, ast.Constant) and flag.value is True)


def _is_refusal_return(stmt) -> bool:
    """``return refuse(...)``, or the spelling the seam replaced
    (``return SimulationResult(<name>, False, ...)``) — read both, so the log
    check below has something to find on a tree without the seam."""
    if not isinstance(stmt, ast.Return) or not isinstance(stmt.value, ast.Call):
        return False
    call = stmt.value
    if _called(call) == "refuse":
        return True
    flag = _supported_argument(call) if _called(call) == "SimulationResult" else None
    return isinstance(flag, ast.Constant) and flag.value is False


def _writes_log(stmt) -> bool:
    """``….log.append(…)`` / ``….log.extend(…)`` / ``….log += …``."""
    for node in ast.walk(stmt):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("append", "extend", "insert")
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "log"
        ):
            return True
        if (
            isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute)
            and node.target.attr == "log"
        ):
            return True
    return False


def _enclosing_functions(tree):
    """``{id(node): name of the innermost function holding it}``."""
    owner: dict[int, str] = {}

    def visit(node, name):
        for child in ast.iter_child_nodes(node):
            inner = (
                child.name
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                else name
            )
            owner[id(child)] = inner
            visit(child, inner)

    visit(tree, None)
    return owner


def _relative(path: Path) -> str:
    return path.resolve().relative_to(_ROOT).as_posix()


def test_every_refused_result_is_built_by_the_seam():
    outside: list[str] = []
    allowed_seen: set = set()
    seam_calls = 0
    modules_calling = set()
    for path in _modules():
        if path.resolve() == _SEAM:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner = _enclosing_functions(tree)
        relative = _relative(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _called(node) == "refuse":
                seam_calls += 1
                modules_calling.add(relative)
            if _is_refused_construction(node):
                key = (relative, owner.get(id(node)))
                if key in _NOT_REFUSALS:
                    allowed_seen.add(key)
                    continue
                outside.append(f"{relative}:{node.lineno} in {key[1]}")
    assert not outside, (
        "a refused SimulationResult built outside engine/refusals.py — return "
        "refuse(card_name, effect_kind, details) instead, which writes nothing "
        f"public (CR 733.1): {outside}"
    )
    # Each exception is still where it is said to be: a stale entry would
    # excuse whatever came to sit under its name next.
    assert allowed_seen == _NOT_REFUSALS, _NOT_REFUSALS - allowed_seen
    # Floors: 96 refusal sites in 10 modules when the seam was cut.
    assert seam_calls >= 96, seam_calls
    assert len(modules_calling) >= 10, sorted(modules_calling)


def test_no_refusal_writes_the_log():
    """The straight-line run of statements a refusal returns at the end of —
    back to the block's previous compound statement — appends nothing to a
    log. That run is where every one of the 87 log appends stood."""
    written: list[str] = []
    examined = 0
    for path in _modules():
        if path.resolve() == _SEAM:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for field in ("body", "orelse", "finalbody"):
                block = getattr(node, field, None)
                if not isinstance(block, list):
                    continue
                for index, stmt in enumerate(block):
                    if not _is_refusal_return(stmt):
                        continue
                    examined += 1
                    for earlier in reversed(block[:index]):
                        if isinstance(earlier, (
                            ast.If, ast.For, ast.While, ast.With, ast.Try,
                            ast.FunctionDef, ast.ClassDef,
                        )):
                            break
                        if _writes_log(earlier):
                            written.append(f"{_relative(path)}:{earlier.lineno}")
    assert not written, (
        "a refusal writes the shared log before it returns — every seat reads "
        f"game.log, and the actor already has the reason: {written}"
    )
    assert examined >= 96, examined


def test_each_attempt_wrapper_takes_a_refusal_back():
    for relative, names in _ATTEMPTS.items():
        names = (names,) if isinstance(names, str) else names
        tree = ast.parse((_ROOT / relative).read_text(encoding="utf-8"))
        for name in names:
            function = next(
                (node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == name),
                None,
            )
            assert function is not None, (relative, name)
            calls = [
                node for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and _called(node) == "take_back_refused_attempt"
            ]
            assert len(calls) == 1, (relative, name, len(calls))


def test_the_seam_writes_nothing():
    """The seam itself names no log: ``refuse`` reads nothing but its three
    arguments, and only the take-back touches ``log`` (to shorten it)."""
    tree = ast.parse(_SEAM.read_text(encoding="utf-8"))
    refuse = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "refuse"
    )
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "log"
        for node in ast.walk(refuse)
    )
    assert not any(_writes_log(node) for node in tree.body)


#: The three announcement functions the take-back covers besides
#: ``_activate_onto_stack`` (``test_activation_checks_before_costs.py`` reads
#: that one), each with the mana payment that is its hinge: the last gate and
#: the first payment.
_HINGES = {
    "_cast_onto_stack": "_pay_cast_mana",
    "_activate_from_hand": "_pay_mana_cost",
    "_activate_from_graveyard": "_pay_mana_cost",
}


def _stack_functions():
    """Every function defined in ``engine/mixins/stack/``, by name (walked)."""
    found: dict = {}
    paths = sorted((_ROOT / "engine" / "mixins" / "stack").glob("*.py"))
    assert len(paths) >= 14, len(paths)
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef):
                found.setdefault(node.name, []).append(node)
    return found


@pytest.mark.parametrize("name", sorted(_HINGES))
def test_nothing_is_refused_below_the_mana_payment(name):
    """What makes the take-back safe: a refused attempt has paid nothing, so
    every line it wrote was an announcement. Asked of the method and of every
    step it calls — a step that can return a refusal (``return refuse(…)``
    anywhere in it) called below the hinge would be a refusal after a payment,
    and the take-back would hide that payment's line."""
    functions = _stack_functions()
    (method,) = functions[name]
    refusing = {
        function_name for function_name, nodes in functions.items()
        if any(
            _is_refusal_return(inner) for node in nodes for inner in ast.walk(node)
        )
    }
    hinge = None
    for node in ast.walk(method):
        if isinstance(node, (ast.If, ast.Assign)) and any(
            isinstance(inner, ast.Call) and _called(inner) == _HINGES[name]
            for inner in ast.walk(node.test if isinstance(node, ast.If) else node.value)
        ):
            hinge = node.end_lineno if isinstance(node, ast.If) else node.lineno
    assert hinge is not None, f"{name} no longer calls {_HINGES[name]}"
    late = sorted(
        (node.lineno, ast.unparse(node)[:60]) for node in ast.walk(method)
        if node is not method and getattr(node, "lineno", 0) > hinge
        and (
            _is_refusal_return(node)
            or (isinstance(node, ast.Call) and _called(node) in refusing)
        )
    )
    assert not late, f"{name} refuses below its mana payment (line {hinge}): {late}"
    # Floor: the method does refuse — above the hinge.
    early = [
        node for node in ast.walk(method)
        if getattr(node, "lineno", 0) <= hinge
        and (
            _is_refusal_return(node)
            or (isinstance(node, ast.Call) and _called(node) in refusing)
        )
    ]
    assert len(early) >= 3, (name, len(early))


# --- behaviour: refusals driven over the pool ------------------------------


def _table(enforce: bool) -> Game:
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = enforce
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.start_priority_window(0)
    return game


def _attempts(card):
    """``(label, game, attempt)`` for each refusal this card can be driven
    into on an empty table: cast from an empty pool, cast with no target
    named, and each ability from the battlefield, a hand and a graveyard with
    an empty pool."""
    for face_name in [card.name, *(face.name for face in face_cards(card))]:
        for enforce in (True, False):
            game = _table(enforce)
            game.players[0].hand = [card]
            yield (
                f"cast {face_name} ({'empty pool' if enforce else 'free'})",
                game, lambda game=game, name=face_name: game.queue_from_hand(0, name),
            )
    abilities = len(compile_card_oracle(card).activated_abilities)
    for index in range(abilities):
        if card.primary_type not in ("instant", "sorcery"):
            game = _table(True)
            permanent = Permanent(card=card)
            permanent.metadata["summoning_sickness_turn"] = -99
            game.players[0].battlefield = [permanent]
            yield (
                f"activate {card.name} #{index}", game,
                lambda game=game, index=index: game.queue_permanent_ability(
                    0, card.name, ability_index=index,
                ),
            )
        game = _table(True)
        game.players[0].hand = [card]
        yield (
            f"activate {card.name} #{index} from a hand", game,
            lambda game=game, index=index: game.activate_from_hand(
                0, card.name, ability_index=index, hand_index=0,
            ),
        )
        game = _table(True)
        game.players[0].graveyard = [card]
        yield (
            f"activate {card.name} #{index} from a graveyard", game,
            lambda game=game, index=index: game.activate_from_graveyard(
                0, card.name, ability_index=index, graveyard_index=0,
            ),
        )


def test_a_refused_attempt_leaves_the_log_as_it_found_it(catalog):
    """One card in four in the quick pass (about 2 s), the whole pool in the
    full one (about 7 s; ``tests.helpers.stable_sample``)."""
    refused = 0
    reasons: set[str] = set()
    wrong: list[str] = []
    for card in catalog:
        if not stable_sample(card.name, 4):
            continue
        for label, game, attempt in _attempts(card):
            before = list(game.log)
            result = attempt()
            if result.supported:
                continue
            refused += 1
            reasons.add(result.details.replace(card.name, "<card>"))
            if not isinstance(result, Refusal):
                wrong.append(f"{label}: {result.details!r} is not a Refusal")
            elif game.log != before:
                wrong.append(f"{label}: wrote {game.log[len(before):]}")
            elif not result.details:
                wrong.append(f"{label}: refused with no reason for the actor")
    assert not wrong, wrong[:20]
    # Floors: when this was written the sample refused 3,305 attempts over 53
    # different reasons (the whole pool 13,458 over 134) — a sweep that
    # refused nothing, or refused everything for want of mana, found nothing.
    assert refused >= 2500, refused
    assert len(reasons) >= 40, sorted(reasons)


@pytest.mark.parametrize("name, attempt, announcement", [
    # CR 601.2b's chosen creature type, announced before the mana was found
    # missing.
    ("Caller of the Hunt", "cast", "chose Human to cast Caller of the Hunt"),
    # CR 601.2f's reduction, its own line, before the payment refused.
    ("Avatar of Will", "cast", "Avatar of Will costs less to cast"),
    # CR 601.2b through 602.2b: the keyword a "choose flying, …" cost names.
    ("Phyrexian Splicer", "activate", "Phyrexian Splicer: chose flying"),
])
def test_what_an_attempt_announced_goes_with_its_refusal(
    catalog_by_name, name, attempt, announcement,
):
    """The three announcements the base wrote ahead of a refusal (measured over
    the shipped pool): each is part of the action CR 733.1 reverses, and
    each named a card the other seat could not see."""
    card = catalog_by_name[name]
    game = _table(True)
    if attempt == "cast":
        game.players[0].hand = [card]
        result = game.queue_from_hand(0, name)
    else:
        permanent = Permanent(card=card)
        permanent.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield = [permanent]
        result = game.queue_permanent_ability(0, name, ability_index=0)
    assert isinstance(result, Refusal), result
    assert result.details, result
    assert not any(announcement.lower() in line.lower() for line in game.log), game.log
    assert not any(name in line for line in game.log), game.log
    if attempt == "cast":
        assert game.players[0].hand == [card]


def test_a_refused_land_tap_answers_the_tapper_and_writes_nothing(catalog_by_name):
    """Tapping a land for mana is activating its mana ability (CR 106.12),
    and the tap seam is the other door to it: a refused tap returns its
    reason (``tap_land_for_mana_or_refusal``) and logs nothing, where it
    logged "Forest has summoning sickness" and the web told the tapper only
    "failed to tap land for mana". ``tap_land_for_mana`` is the same answer
    as a bool."""
    game = _table(True)
    forest = Permanent(card=catalog_by_name["Forest"])
    forest.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield = [forest]
    game._sync_control()
    before = list(game.log)

    assert game.tap_land_for_mana_or_refusal(
        0, "Forest", "Q", permanent_id=forest.permanent_id,
    ) == "'Q' is not a mana symbol"
    forest.tapped = True
    # CR 107.5, in the activation path's sentence (``tap_symbol_refusal``).
    assert game.tap_land_for_mana_or_refusal(
        0, "Forest", permanent_id=forest.permanent_id,
    ) == "Forest is already tapped"
    assert not game.tap_land_for_mana(0, "Forest", permanent_id=forest.permanent_id)
    assert game.log == before
    forest.tapped = False
    assert game.tap_land_for_mana_or_refusal(
        0, "Forest", permanent_id=forest.permanent_id,
    ) is None
    assert forest.tapped and game.players[0].mana_pool["G"] == 1

    # The refusal the base logged: a land that is a creature (Living Lands)
    # and came under its controller's control this turn (CR 302.6).
    game = _table(True)
    game.players[0].battlefield = [Permanent(card=catalog_by_name["Living Lands"])]
    sick = Permanent(card=catalog_by_name["Forest"])
    sick.metadata["summoning_sickness_turn"] = game.turn
    game.players[0].battlefield.append(sick)
    game._sync_control()
    game._recompute_continuous_effects()
    assert sick.is_creature
    before = list(game.log)
    assert game.tap_land_for_mana_or_refusal(
        0, "Forest", permanent_id=sick.permanent_id,
    ) == "Forest has summoning sickness"
    assert game.log == before and not sick.tapped
