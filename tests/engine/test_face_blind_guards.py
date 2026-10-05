"""Guard: a census over compiled text reads a split card's **halves**.

A multi-face card's own text box is empty and its own compiled program is
supported and holds no instruction (CR 709.3a: only the chosen half is
evaluated — ``engine/faces.py``). So the loop every pool-wide guard and every
coverage instrument is built on,

    for card in catalog:
        program = compile_card_oracle(card)   # or: ... in card.oracle_text

examines a split card, finds nothing, and reports it clean. **Blind, not red**:
nothing fails, the guard's own floor ("examined at least N") is met by the rest
of the pool, and the ten halves Invasion brings are never looked at.

The answer is one iterator, ``faces.compilation_units(cards)`` — each
single-face card itself and each face of a multi-face card in its place — and
this file holds the tests and scripts to using it, three ways:

* **Statically.** :func:`blind_loops` reads each test and script module and
  names every loop over a *raw* pool (``catalog``, ``load_catalog()``,
  ``load_cards(…)``, ``set_cards(…)``, and anything built from one) whose body
  compiles the loop's card or reads its ``oracle_text``. The pool is followed
  through a local name, a dict filled by a loop, a helper's return value and a
  fixture, because that is how these guards are actually written. What it finds
  must be in :data:`CARD_QUESTIONS` with the reason the whole card is the right
  thing to ask.
* **Backwards.** The scan is run over small sources written to be blind and
  must name each; and each converted guard that can be handed a pool is handed
  an invented split card with a defect on one half, and must find it — then
  the iterator is taken away again and the same guard must go blind, which is
  the tree before this file existed.
* **With a floor.** ``compilation_units`` over both manifest roles yields at
  least the ten Invasion halves.

How the scan was itself validated is the part worth keeping: it was written
*after* a dynamic census (a pytest plugin that promoted the measured set in
memory and recorded every test site that compiled, or read the text of, a
whole multi-face card) had found the blind sites by running them. On the tree
before the conversion the scan flags every one of the census's 60-odd direct
sites and some the census could not reach, because a loop that filters on
``"Creature" in card.type_line`` first never touches a split *spell* — and
would the day a layout with permanent faces is admitted.

Not covered, and said so: a loop reached only through two modules (a helper in
``tests/helpers.py`` feeding a guard elsewhere), a pool held on an attribute,
and ``tests/sets/`` — per-card files by convention
(``test_set_test_convention.py``), where a pool-wide loop is already banned.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import (CAST_FACE_LAYOUTS, compilation_units, face_cards,
                          is_face, unit_label, whole_card)
from engine.models import CardDefinition, CardFace
from engine.oracle import compile_card_oracle, compiled_units

REPO = Path(__file__).resolve().parents[2]

#: Where a pool-wide question lives. ``tests/sets`` is per-card by convention.
SCANNED = (
    "tests/engine", "tests/rules", "tests/regressions", "tests/ai", "tests/ui",
    "scripts",
)

#: Calls that return whole cards out of the manifest.
POOL_CALLS = frozenset({"load_catalog", "load_cards", "set_cards", "set_pool"})
#: Fixtures that hold the whole pool. The grandfathered per-set aliases
#: (``all_cards``, ``cards``, ``arn_cards``) are Alpha and Arabian Nights and
#: cannot hold a multi-face card.
POOL_FIXTURES = frozenset({"catalog", "catalog_by_name"})
#: The face-aware readers. A pool passed through one is no longer raw, and a
#: loop that hands its card to one is reading the faces itself.
FACE_AWARE = frozenset({
    "compilation_units", "compiled_units", "castable_faces", "face_cards",
    "compiled_faces", "face_programs",
})
#: What reading a card's *text* looks like: compiling it, or handing it to one
#: of the readers that open ``oracle_text`` themselves.
TEXT_CALLS = frozenset({
    "compile_card_oracle", "additional_costs", "derive_cast_spec",
    "cast_announces_x",
})
TEXT_ATTRS = frozenset({"oracle_text"})
_COLLECTING = frozenset({"setdefault", "append", "add", "update", "extend", "insert"})
#: Builtins that hand back the cards they were given.
_PASSTHROUGH = frozenset({
    "sorted", "list", "tuple", "set", "frozenset", "reversed", "iter",
    "enumerate", "filter", "zip", "dict", "chain",
})

#: ``{(module, function): why the whole card is what this loop should ask}``.
#: A loop the scan names that is about a **card** — the unit a player is dealt,
#: decks and is shown a verdict for (CR 709.4) — rather than about text.
CARD_QUESTIONS: dict[tuple[str, str], str] = {
    ("tests/engine/test_card_format.py", "test_whole_catalog_still_compiles_as_supported"): (
        "the supported verdict a card is shipped under; a split card's is "
        "'every face supported', which compile_card_oracle answers for the whole"
    ),
    ("tests/engine/test_front_end_safety.py", "test_every_card_in_the_pool_is_supported"): (
        "the same verdict, as the pool's headline claim — one row per card"
    ),
    ("tests/engine/test_reporting.py", "test_refusals_report_names_exactly_the_unsupported_cards"): (
        "compares the report's card names with the unsupported cards'; the "
        "report itself reads each face (support_report.refusals_report)"
    ),
    ("tests/engine/test_simple_cards.py", "test_a_simple_card_has_nothing_but_keyword_lines_in_its_program"): (
        "auto-pass is a verification row, one per card, and "
        "simple_card_keywords refuses a multi-face card outright"
    ),
}


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _names(node) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _mentions(node, names: set[str]) -> bool:
    return bool(names) and any(
        isinstance(n, ast.Name) and n.id in names for n in ast.walk(node)
    )


def _is_scope(node) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))


def _own_nodes(scope):
    """Every node of *scope* that is not inside a nested function."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not _is_scope(node):
            stack.extend(ast.iter_child_nodes(node))


def _params(scope) -> set[str]:
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()
    args = scope.args
    return {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}


class _Scan:
    """One module: which names hold raw cards, and which loops read them."""

    def __init__(self, tree: ast.Module):
        self.tree = tree
        self.pool_calls = set(POOL_CALLS)
        self.face_aware = set(FACE_AWARE)
        self.text_calls = set(TEXT_CALLS)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if alias.name in POOL_CALLS:
                        self.pool_calls.add(bound)
                    if alias.name in FACE_AWARE:
                        self.face_aware.add(bound)
                    if alias.name in TEXT_CALLS:
                        self.text_calls.add(bound)
        self.scopes = [tree, *(
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        )]
        self.helpers = {
            scope.name: scope for scope in self.scopes[1:]
        }
        #: Names holding raw cards, per scope. The module's set also carries
        #: the *functions* (helpers and fixtures) that return them.
        self.raw: dict[int, set[str]] = {id(scope): set() for scope in self.scopes}
        self.bound: dict[int, set[str]] = {
            id(scope): _params(scope) | {
                name
                for node in _own_nodes(scope)
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.For, ast.comprehension))
                for target in (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for name in _names(target)
            }
            for scope in self.scopes
        }

    # -- which expressions are raw pools ----------------------------------
    def _holds_raw(self, name: str, scope) -> bool:
        if name in self.raw[id(scope)]:
            return True
        module_raw = self.raw[id(self.tree)]
        if scope is self.tree:
            return False
        if name in _params(scope):
            # A fixture: the whole pool by name, or a helper in this module
            # that returns raw cards.
            return name in POOL_FIXTURES or name in module_raw
        return name in module_raw and name not in self.bound[id(scope)]

    def is_raw(self, node, scope) -> bool:
        if node is None:
            return False
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in self.face_aware:
                return False
            if name in self.pool_calls:
                return True
            if isinstance(node.func, ast.Name) and self._holds_raw(name, scope):
                return True
            if isinstance(node.func, ast.Attribute) and self.is_raw(node.func.value, scope):
                return True  # raw.values(), raw.items()
            if not any(self.is_raw(arg, scope) for arg in node.args):
                return False
            if name in _PASSTHROUGH:
                return True  # sorted(raw), list(raw)
            # A helper of this module handed a raw pool gives raw cards
            # back unless it goes through a face-aware reader itself.
            helper = self.helpers.get(name) if isinstance(node.func, ast.Name) else None
            return helper is not None and not any(
                isinstance(inner, ast.Call) and _call_name(inner) in self.face_aware
                for inner in ast.walk(helper)
            )
        if isinstance(node, ast.Name):
            return self._holds_raw(node.id, scope)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            cards: set[str] = set()
            for generator in node.generators:
                if self.is_raw(generator.iter, scope):
                    cards |= _names(generator.target)
            produced = [node.value] if isinstance(node, ast.DictComp) else [node.elt]
            return any(_mentions(part, cards) for part in produced)
        if isinstance(node, ast.BinOp):
            return self.is_raw(node.left, scope) or self.is_raw(node.right, scope)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return any(self.is_raw(element, scope) for element in node.elts)
        if isinstance(node, ast.Starred):
            return self.is_raw(node.value, scope)
        if isinstance(node, ast.IfExp):
            return self.is_raw(node.body, scope) or self.is_raw(node.orelse, scope)
        return False

    def _mark(self, scope, name: str) -> bool:
        target = self.raw[id(scope)]
        if name in target:
            return False
        target.add(name)
        return True

    def _settle(self) -> None:
        changed = True
        while changed:
            changed = False
            for scope in self.scopes:
                for node in _own_nodes(scope):
                    if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                        if self.is_raw(node.value, scope):
                            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                            for target in targets:
                                if isinstance(target, ast.Name):
                                    changed |= self._mark(scope, target.id)
                    elif isinstance(node, ast.For) and self.is_raw(node.iter, scope):
                        cards = _names(node.target)
                        for inner in ast.walk(node):
                            # pool.setdefault(key, card) / found.append(card)
                            if (
                                isinstance(inner, ast.Call)
                                and isinstance(inner.func, ast.Attribute)
                                and inner.func.attr in _COLLECTING
                                and isinstance(inner.func.value, ast.Name)
                                and any(_mentions(arg, cards) for arg in inner.args)
                            ):
                                changed |= self._mark(scope, inner.func.value.id)
                            # pool[key] = card
                            elif isinstance(inner, ast.Assign) and _mentions(inner.value, cards):
                                for target in inner.targets:
                                    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                                        changed |= self._mark(scope, target.value.id)
                            elif (
                                isinstance(inner, ast.Yield)
                                and inner.value is not None
                                and _mentions(inner.value, cards)
                                and isinstance(scope, ast.FunctionDef)
                            ):
                                changed |= self._mark(self.tree, scope.name)
                    elif (
                        isinstance(node, ast.Return)
                        and isinstance(scope, ast.FunctionDef)
                        and self.is_raw(node.value, scope)
                    ):
                        changed |= self._mark(self.tree, scope.name)
                    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        # helper(raw): the helper's parameter holds raw cards.
                        helper = self.helpers.get(node.func.id)
                        if helper is None:
                            continue
                        names = [a.arg for a in (*helper.args.posonlyargs, *helper.args.args)]
                        for position, arg in enumerate(node.args):
                            if position < len(names) and self.is_raw(arg, scope):
                                changed |= self._mark(helper, names[position])
                        for keyword in node.keywords:
                            if keyword.arg and self.is_raw(keyword.value, scope):
                                changed |= self._mark(helper, keyword.arg)

    # -- which loops read text off a raw card ------------------------------
    def _reads_text(self, parts, cards: set[str]):
        hit = None
        for part in parts:
            for node in ast.walk(part):
                if isinstance(node, ast.Call):
                    name = _call_name(node)
                    handed = any(
                        isinstance(arg, ast.Name) and arg.id in cards for arg in node.args
                    )
                    if handed and name in self.face_aware:
                        return None  # the loop reads the faces itself
                    if handed and name in self.text_calls and hit is None:
                        hit = (node.lineno, f"{name}({sorted(cards & _names(node))[0]})")
                elif (
                    isinstance(node, ast.Attribute)
                    and node.attr in TEXT_ATTRS
                    and isinstance(node.value, ast.Name)
                    and node.value.id in cards
                    and hit is None
                ):
                    hit = (node.lineno, f"{node.value.id}.{node.attr}")
        return hit

    def findings(self) -> list[tuple[str, int, str]]:
        self._settle()
        found: set[tuple[str, int, str]] = set()
        for scope in self.scopes:
            where = getattr(scope, "name", "<module>")
            for node in _own_nodes(scope):
                hit = None
                if isinstance(node, ast.For) and self.is_raw(node.iter, scope):
                    hit = self._reads_text(node.body, _names(node.target))
                elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                    cards: set[str] = set()
                    for generator in node.generators:
                        if self.is_raw(generator.iter, scope):
                            cards |= _names(generator.target)
                    if cards:
                        parts = [g.iter for g in node.generators]
                        parts += [test for g in node.generators for test in g.ifs]
                        parts += (
                            [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
                        )
                        hit = self._reads_text(parts, cards)
                if hit is not None:
                    found.add((where, hit[0], hit[1]))
        return sorted(found, key=lambda item: (item[1], item[0]))

    def face_aware_loops(self) -> int:
        """How many loops in this module go through a face-aware reader."""
        count = 0
        for node in ast.walk(self.tree):
            iters = []
            if isinstance(node, ast.For):
                iters = [node.iter]
            elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                iters = [g.iter for g in node.generators]
            for expression in iters:
                if any(
                    isinstance(inner, ast.Call) and _call_name(inner) in self.face_aware
                    for inner in ast.walk(expression)
                ):
                    count += 1
        return count


def blind_loops(source: str) -> list[tuple[str, int, str]]:
    """``(function, line, what was read)`` for every loop over a raw pool in
    *source* that reads a card's text without going through its faces."""
    return _Scan(ast.parse(source)).findings()


def _scanned_files() -> list[Path]:
    return sorted(
        path for folder in SCANNED for path in (REPO / folder).glob("*.py")
        if path.name != Path(__file__).name
    )


# ---------------------------------------------------------------------------
# The scan over the repository
# ---------------------------------------------------------------------------


def test_no_pool_loop_reads_a_split_card_whole():
    found: dict[tuple[str, str], list[str]] = {}
    for path in _scanned_files():
        relative = path.relative_to(REPO).as_posix()
        for function, line, read in blind_loops(path.read_text(encoding="utf-8")):
            found.setdefault((relative, function), []).append(f"line {line}: {read}")

    unreviewed = {key: lines for key, lines in found.items() if key not in CARD_QUESTIONS}
    assert not unreviewed, (
        "loops over a raw pool that compile a card or read its oracle_text. A "
        "split card read whole has an empty text box and a program with no "
        "instructions, so this loop examines its halves' text not at all — "
        "iterate `faces.compilation_units(pool)` (or `oracle.compiled_units`), "
        "or, if the question is about a card rather than text, add the loop "
        "to CARD_QUESTIONS with the reason:\n  "
        + "\n  ".join(
            f"{module}::{function}: {'; '.join(lines)}"
            for (module, function), lines in sorted(unreviewed.items())
        )
    )

    dead = sorted(key for key in CARD_QUESTIONS if key not in found)
    assert not dead, (
        "CARD_QUESTIONS entries the scan no longer finds — the loop went, or "
        f"was converted; delete them: {dead}"
    )


def test_the_scan_reads_the_guards_it_is_for():
    """A floor on the scan itself: over a tree it could not parse, or a
    vocabulary that no longer matched how these files spell a pool, it would
    report nothing and pass."""
    files = _scanned_files()
    assert len(files) >= 350, len(files)
    face_aware = sum(
        _Scan(ast.parse(path.read_text(encoding="utf-8"))).face_aware_loops()
        for path in files
    )
    assert face_aware >= 75, (
        f"{face_aware} loops go through a face-aware reader; the conversion "
        "that wrote this guard left well over that, so either they are being "
        "taken out or the scan stopped recognising them"
    )


#: Each is a shape a real guard was written in before the conversion.
_BLIND = {
    "the pool, compiled": """
def test_it(catalog):
    for card in catalog:
        program = compile_card_oracle(card)
""",
    "the pool's text, scanned": """
def _printers():
    return [card for card in load_cards(manifest_set_paths(include_measured=True))
            if "domain" in (card.oracle_text or "")]
""",
    "through a local name": """
def test_it():
    cards = load_catalog()
    first = [compile_card_oracle(card) for card in cards]
""",
    "through a dict a loop fills": """
_POOL = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)

def _census():
    for name, card in sorted(_POOL.items()):
        program = compile_card_oracle(card)
""",
    "through a helper's return": """
def _both_roles():
    cards = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
    return cards

def _kicker_cards():
    return [card for card in _both_roles().values() if "kicker" in card.oracle_text]
""",
    "through a fixture": """
@pytest.fixture(scope="module")
def pool():
    return load_cards(manifest_set_paths(include_measured=True))

def test_it(pool):
    for card in pool:
        for ability in compile_card_oracle(card).activated_abilities:
            pass
""",
    "through an aliased import": """
from engine.card_loader import load_cards as _w9_load
from engine.oracle import compile_card_oracle as _w9_compile

def test_it():
    for card in _w9_load(paths):
        _w9_compile(card)
""",
    "through a text reader the engine owns": """
def test_it(catalog_by_name):
    for name, card in catalog_by_name.items():
        spec = derive_cast_spec(card, program_of[name])
""",
    "through a helper's parameter": """
def _abilities_of(cards):
    for card in cards:
        program = compile_card_oracle(card)

def test_it():
    rows = _abilities_of(load_cards(manifest_set_paths(include_measured=True)))
""",
    "one set's pool": """
def test_it(set_pool):
    for card in set_pool("INV").values():
        for trigger in compile_card_oracle(card).triggered_abilities:
            pass
""",
}

_SIGHTED = {
    "the iterator": """
def test_it(catalog):
    for card in compilation_units(catalog):
        program = compile_card_oracle(card)
""",
    "the iterator, at the pool's source": """
def pool():
    return compilation_units(load_cards(manifest_set_paths(include_measured=True)))

def test_it():
    for card in pool():
        compile_card_oracle(card)
""",
    "a loop that reads the faces itself": """
def test_it():
    for whole in load_catalog():
        verdict = compile_card_oracle(whole)
        for card, program in compiled_faces(whole):
            pass
""",
    "a question that is not about text": """
def test_it(catalog):
    island = next(card for card in catalog if card.name == "Island")
    colours = {card.name: card.colors for card in catalog}
""",
    "one card, by name": """
def test_it(catalog_by_name):
    program = compile_card_oracle(catalog_by_name["Lightning Bolt"])
""",
    "a helper handed the units": """
def _abilities_of(cards):
    for card in cards:
        program = compile_card_oracle(card)

def test_it():
    rows = _abilities_of(compilation_units(load_catalog()))
""",
    "a local that only shares a raw name": """
def raw():
    pool = load_catalog()
    return len(pool)

def sighted():
    pool = compilation_units(load_catalog())
    return [compile_card_oracle(card) for card in pool]
""",
}


@pytest.mark.parametrize("shape", sorted(_BLIND))
def test_the_scan_names_a_blind_loop(shape):
    assert blind_loops(_BLIND[shape]), shape


@pytest.mark.parametrize("shape", sorted(_SIGHTED))
def test_the_scan_leaves_a_face_aware_loop_alone(shape):
    assert blind_loops(_SIGHTED[shape]) == [], shape


# ---------------------------------------------------------------------------
# The iterator
# ---------------------------------------------------------------------------


def _split(left: CardFace, right: CardFace) -> CardDefinition:
    return CardDefinition(
        name=f"{left.name} // {right.name}",
        mana_cost=f"{left.mana_cost} // {right.mana_cost}",
        cmc=5.0,
        type_line=f"{left.type_line} // {right.type_line}",
        oracle_text="",
        colors=("G", "R"),
        color_identity=("G", "R"),
        keywords=(),
        produced_mana=(),
        raw={},
        layout="split",
        faces=(left, right),
    )


_BOLT = CardDefinition(
    name="Test Bolt", mana_cost="{R}", cmc=1.0, type_line="Instant",
    oracle_text="Test Bolt deals 3 damage to any target.", colors=("R",),
    color_identity=("R",), keywords=(), produced_mana=(), raw={},
)
_LEFT = CardFace("Left", "{R}", "Sorcery", "Left deals 2 damage to any target.")
_RIGHT = CardFace("Right", "{3}{G}", "Sorcery", "Create a 3/3 green Elephant creature token.")
_GOOD = _split(_LEFT, _RIGHT)


def test_compilation_units_puts_each_face_in_its_cards_place():
    units = compilation_units([_BOLT, _GOOD, _BOLT])
    assert [unit.name for unit in units] == ["Test Bolt", "Left", "Right", "Test Bolt"]
    assert units[0] is _BOLT, "a single-face card is itself, not a copy"
    assert units[1:3] == list(face_cards(_GOOD))
    assert [whole_card(unit) for unit in units] == [_BOLT, _GOOD, _GOOD, _BOLT]
    assert [unit_label(unit) for unit in units] == [
        "Test Bolt", "Left // Right [Left]", "Left // Right [Right]", "Test Bolt",
    ]
    assert compilation_units([]) == []
    # Any iterable, once: a generator is a pool too.
    assert len(compilation_units(card for card in (_GOOD, _GOOD))) == 4

    pairs = compiled_units([_BOLT, _GOOD])
    assert [card.name for card, _ in pairs] == ["Test Bolt", "Left", "Right"]
    assert all(program.instructions for _, program in pairs), (
        "every unit has a program that does something — which is the point: "
        "the whole card's does not"
    )
    assert compile_card_oracle(_GOOD).instructions == ()


def test_the_iterator_reaches_every_half_in_the_manifest():
    """The floor. Both manifest roles, so it holds before and after Invasion is
    promoted: five split cards, ten halves, each a unit and none of the five
    whole cards among them."""
    pool = load_cards(manifest_set_paths(include_measured=True))
    multi = [card for card in pool if card.layout in CAST_FACE_LAYOUTS]
    units = compilation_units(pool)
    halves = [unit for unit in units if is_face(unit)]

    assert len(multi) >= 5 and len(halves) >= 10, (len(multi), len(halves))
    assert len(halves) == sum(len(face_cards(card)) for card in multi)
    assert not any(unit in multi for unit in units)
    assert len(units) == len(pool) - len(multi) + len(halves)
    for half in halves:
        assert compile_card_oracle(half).instructions, unit_label(half)
    # A half's name is the key these guards index by; it must not collide with
    # a card really called that, or one of the two is silently dropped.
    names = [unit.name for unit in units]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Backwards: a defect planted on one half must be found — and with the
# iterator taken away again, must not be.
# ---------------------------------------------------------------------------


def _finds_a_half_with_no_handler(monkeypatch) -> bool:
    """``test_no_hollow_support``: a supported spell whose instructions have no
    handler. Made by taking the handler away, so the half is real text the
    compiler reads today."""
    from tests.engine import test_no_hollow_support as guard

    monkeypatch.setattr(
        guard, "EFFECT_HANDLERS",
        {kind: fn for kind, fn in guard.EFFECT_HANDLERS.items() if kind != "create_token"},
    )
    named = [name for name, _ in guard._hollow_spells([_BOLT, _GOOD])]
    return named == ["Left // Right [Right]"]


def _finds_a_halfs_ability_label(monkeypatch) -> bool:
    """``test_effect_labels``: the abilities whose labels the guard checks. A
    half that cycles has an activated ability; the whole card has none."""
    from tests.engine import test_effect_labels as guard

    cycler = _split(_LEFT, CardFace(
        "Right", "{3}{G}", "Sorcery",
        "Create a 3/3 green Elephant creature token.\nCycling {2}",
    ))
    activated, _triggered = guard._abilities_of([cycler])
    return [name for name, _kind, _label in activated] == ["Right"]


def _finds_a_halfs_trigger_line(monkeypatch) -> bool:
    """``test_grammar_lowering``: the trigger lines its seam guards walk."""
    from tests.engine import test_grammar_lowering as guard

    permanent = _split(_LEFT, CardFace(
        "Right", "{1}{G}", "Enchantment",
        "At the beginning of your upkeep, you gain 1 life.",
    ))
    return [name for name, *_ in guard._executed_trigger_lines([permanent])] == ["Right"]


def _finds_a_halfs_unread_lord_line(monkeypatch) -> bool:
    """``test_lord_buff_table``: a lord-shaped line nothing reads."""
    from tests.engine import test_lord_buff_table as guard

    lord = _split(_LEFT, CardFace(
        "Right", "{1}{G}", "Enchantment", "Other Gribbles get +1/+1 and have frobnication.",
    ))
    try:
        guard.test_every_lord_shaped_line_in_the_pool_derives([lord])
    except AssertionError as failure:
        return "Right" in str(failure)
    return False


def _finds_a_halfs_targeting_ability(monkeypatch) -> bool:
    """``test_activation_targeting``: the population every ratchet in that
    file reads, which is where its conversion lives."""
    from tests.engine import test_activation_targeting as guard

    return [card.name for card in guard._supported_units([_GOOD, _BOLT])] == [
        "Left", "Right", "Test Bolt",
    ]


def _finds_a_halfs_cast_target(monkeypatch) -> bool:
    """``test_targeting`` and the picker-sweep acknowledgements beside it."""
    from tests.engine import test_targeting as guard

    return [card.name for card in guard._supported_units([_GOOD, _BOLT])] == [
        "Left", "Right", "Test Bolt",
    ]


_PLANTED = {
    "no_hollow_support": (_finds_a_half_with_no_handler, "test_no_hollow_support"),
    "effect_labels": (_finds_a_halfs_ability_label, "test_effect_labels"),
    "grammar_lowering": (_finds_a_halfs_trigger_line, "test_grammar_lowering"),
    "lord_buff_table": (_finds_a_halfs_unread_lord_line, "test_lord_buff_table"),
    "activation_targeting": (_finds_a_halfs_targeting_ability, "test_activation_targeting"),
    "targeting": (_finds_a_halfs_cast_target, "test_targeting"),
}


@pytest.mark.parametrize("guard", sorted(_PLANTED))
def test_a_defect_planted_on_a_half_is_found(guard, monkeypatch):
    check, _module = _PLANTED[guard]
    assert check(monkeypatch)


@pytest.mark.parametrize("guard", sorted(_PLANTED))
def test_without_the_iterator_the_same_guard_is_blind(guard, monkeypatch):
    """The tree before the conversion, reproduced: with ``compilation_units``
    handing the pool back unchanged, the guard is given the whole card, finds
    no text on it, and the planted half goes unseen."""
    import importlib

    check, module = _PLANTED[guard]
    monkeypatch.setattr(
        importlib.import_module(f"tests.engine.{module}"),
        "compilation_units", lambda cards: list(cards),
    )
    assert not check(monkeypatch)
