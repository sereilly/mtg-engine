"""Which tests take a population through the manifest's ``measured`` role?

``scripts/tests_for_diff.py --ingest CODE`` asks this module, so Phase 1 of a
set (SET_PLAYBOOK) can run, first and whole, every test an ingest can turn red
— before the wave, rather than eighty minutes into it. An ingest adds one card
file under ``measured`` and nothing else, so the only tests it can move are the
ones whose population includes that set: Darksteel's full pass read 13 reds in
9 files, every one a census over both manifest roles, and Mirrodin's,
Scourge's, Legions', Onslaught's and Judgment's yields were the same class.

A test is named when, statically, it **walks a population drawn through the
measured role**:

- **the sources**: ``manifest_set_paths(include_measured=True)``,
  ``manifest_measured_codes()`` / ``manifest_measured_sets()``,
  ``manifest_set_path(code, include_measured=True)`` / ``manifest_set`` and the
  ``set_cards`` / ``set_pool`` factories (``tests/conftest.py``) for a code that
  is one of those or is *CODE* itself, ``["measured"]`` read off the manifest,
  and a string naming the set (its code, its card file, or its name outside a
  card name — Onslaught's ``"... printed in the Onslaught expansion"``);
- **carried** through assignments, returns, fixtures, module-level names, and
  imports between test modules (one test file's ``POOL`` is another's);
- **walked**: iterated, counted, compared or set-subtracted, parametrized
  over, or handed to a function that walks it — in the test, in a helper, or in
  a fixture it requests.

What is *not* a walk — and what keeps the selection to the censuses, about
half the test files that read both roles — is an **index** (``{card.name:
card for card in ...}``, or a loop that only fills one by name) read one card
at a time, and a search for one card by name. A lookup of a named card cannot
change when a set arrives; a census can. A census over ``load_catalog()`` is
not named either: it meets the measured set only under ``MTG_PROMOTE``, which
is ``scripts/integration/census_rehearsal.sh``'s question.

Each test is one row (``path::test``, a class's ``path::Class::test``), so a
run names node ids, not files. A module whose own import walks the population
with no test reading it is named whole: the import runs for any of its tests.

The analysis is static and deliberately over-approximate inside a test (an
object built from a walked population carries it), so it errs on naming a test
too many; the backwards check that holds it is
``tests/engine/test_measured_censuses.py``.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: The three kinds a value can carry: a population (a collection whose members
#: include the measured set's cards, paths or codes), an index of one by name
#: (read one card at a time), and a member of a walked population.
POOL, INDEX, ELEM = 1, 2, 4
WHOLE = POOL | INDEX
KINDS = POOL | INDEX | ELEM
#: In the walk of a function over what it is handed, parameter *i* carries bit
#: ``FIRST_PARAM_BIT + i`` beside its kind, so a helper that walks only its
#: second argument is not charged to a caller that hands the pool as its first.
FIRST_PARAM_BIT = 3

#: card_loader's readers of the ``measured`` role alone.
MEASURED_ROLE = frozenset({"manifest_measured_codes", "manifest_measured_sets"})
#: Its readers of both roles, with ``include_measured=True``.
BOTH_ROLES = frozenset({"manifest_set_paths"})
#: Its readers of one set by code, which reach a measured one with ``include_measured=True``.
ONE_SET = frozenset({"manifest_set_path", "manifest_set"})
#: ``tests/conftest.py``'s set factories, which resolve a measured code.
SET_FIXTURES = {"set_cards": POOL, "set_pool": INDEX}
#: Calls that consume what they are handed: a count, a verdict over every member.
CONSUMERS = frozenset({"len", "any", "all", "sum", "min", "max", "Counter"})
#: Methods that add their arguments to the receiver.
MUTATORS = frozenset({"append", "add", "extend", "update", "insert", "setdefault",
                      "appendleft", "extendleft"})
#: Methods that read one member.
LOOKUPS = frozenset({"get", "pop", "index", "count"})
VIEWS = frozenset({"values", "items", "keys"})
_MEMBERSHIP = (ast.In, ast.NotIn, ast.Is, ast.IsNot)
_SET_OPS = (ast.Sub, ast.BitAnd, ast.BitXor)
_IMPORT_LINE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import\s+(\([^)]*\)|[^\n]*)|import\s+([\w., ]+))", re.M
)


def _prov(kind: int) -> int:
    return kind & ~KINDS


def _dotted(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _truthy_keyword(call: ast.Call, name: str) -> bool:
    for keyword in call.keywords:
        if keyword.arg == name:
            value = keyword.value
            return not (isinstance(value, ast.Constant) and not value.value)
    return False


def _bound_names(target) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for elt in target.elts for n in _bound_names(elt)]
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return []


def _is_name_of(node, targets) -> bool:
    """``t.name`` for a loop variable *t*: the key of a by-name index."""
    return (isinstance(node, ast.Attribute) and node.attr == "name"
            and isinstance(node.value, ast.Name) and node.value.id in targets)


def _index_store(stmt, targets) -> str | None:
    """``d.setdefault(t.name, ...)`` / ``d[t.name] = ...``: the dict it fills."""
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        func = stmt.value.func
        if (isinstance(func, ast.Attribute) and func.attr == "setdefault"
                and isinstance(func.value, ast.Name) and stmt.value.args
                and _is_name_of(stmt.value.args[0], targets)):
            return func.value.id
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target = stmt.targets[0]
        if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                and _is_name_of(target.slice, targets)):
            return target.value.id
    return None


def _index_builder(loop: ast.For, outer=()) -> set[str] | None:
    """The dicts a loop does nothing but fill by name — an index of the pool,
    read later one card at a time, not a census of it."""
    if loop.orelse:
        return None
    targets = set(outer) | set(_bound_names(loop.target))
    filled: set[str] = set()
    for stmt in loop.body:
        if isinstance(stmt, ast.For):
            inner = _index_builder(stmt, targets)
            if inner is None:
                return None
            filled |= inner
            continue
        name = _index_store(stmt, targets)
        if name is None:
            return None
        filled.add(name)
    return filled or None


def _constant(node) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_constant(e) for e in node.elts)
    return False


def _name_lookup(generators) -> bool:
    """``... for c in pool if c.name == "X"``: finding one card by name."""
    targets = {n for g in generators for n in _bound_names(g.target)}
    for generator in generators:
        for test in generator.ifs:
            if (isinstance(test, ast.Compare) and _is_name_of(test.left, targets)
                    and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.In))
                    and _constant(test.comparators[0])):
                return True
    return False


def _decorator_name(decorator) -> str:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr
    return getattr(target, "id", "")


def _params(func) -> list[str]:
    args = func.args
    return [a.arg for a in (*args.posonlyargs, *args.args)]


# ---------------------------------------------------------------------------
# the set being asked about
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MeasuredSet:
    """What a test can name the set by: its code, its card file, its name —
    the name less every card name that contains it (Mirrodin's Darksteel
    Ingot is not Darksteel)."""

    code: str
    name: str
    file: str
    card_names: tuple[str, ...] = ()

    @classmethod
    def read(cls, root: Path, code: str) -> "MeasuredSet":
        """*root*'s manifest entry for *code* under ``measured`` (read through
        ``engine.card_loader``, the one reader of the manifest); raises
        ``KeyError`` naming the measured codes when it is not one."""
        from engine.card_loader import MANIFEST_PATH, manifest_measured_sets, manifest_sets

        manifest = Path(root) / "cards" / MANIFEST_PATH.name
        measured = manifest_measured_sets(manifest)
        wanted = code.strip().upper()
        entry = next((e for e in measured if str(e["code"]).upper() == wanted), None)
        if entry is None:
            codes = ", ".join(str(e["code"]) for e in measured) or "none"
            raise KeyError(f"{code!r} is not a measured set in {manifest} (measured: {codes})")
        name = str(entry.get("name", ""))
        pattern = re.compile(r'"name":\s*"([^"\\]*' + re.escape(name) + r'[^"\\]*)"')
        names = set()
        for other in manifest_sets(manifest) + measured:
            path = manifest.parent / other["file"]
            if path.is_file():
                names.update(pattern.findall(path.read_text(encoding="utf-8", errors="replace")))
        # A card called just the set's name (Exodus' Onslaught) is not stripped:
        # the string is the set's name too, and naming it is the question.
        names.discard(name)
        return cls(wanted, name, str(entry.get("file", "")),
                   tuple(sorted(names, key=len, reverse=True)))

    def named_in(self, text: str) -> bool:
        """Whether *text* names the set: its code exactly, its card file, or
        its name as a word outside a card name."""
        if text.strip().upper() == self.code or (self.file and self.file in text):
            return True
        if not self.name or self.name not in text:
            return False
        for card in self.card_names:
            text = text.replace(card, "")
        return re.search(rf"\b{re.escape(self.name)}\b", text) is not None

    def tokens(self) -> tuple[str, ...]:
        """Text a module must hold to name the set at all (the prefilter)."""
        return tuple(t for t in (f'"{self.code}"', f"'{self.code}'", f'"{self.code.lower()}"',
                                 f"'{self.code.lower()}'", self.file, self.name) if t)


# ---------------------------------------------------------------------------
# the modules
# ---------------------------------------------------------------------------


#: Text a module must hold to read the measured role itself.
_ROLE_TOKENS = ("include_measured", "manifest_measured", '"measured"', "'measured'")
_FACTORY_BY_VARIABLE = re.compile(r"\bset_(?:cards|pool)\(\s*[^\s\"')]")


class Module:
    def __init__(self, root: Path, path: Path, text: str):
        self.path = path
        self.rel = path.relative_to(root).as_posix()
        self.dotted = _dotted(root, path)
        self.is_test = path.name.startswith("test_")
        self.text = text
        self.tree = ast.parse(text)
        self.imports: dict[str, tuple[str, str | None]] = {}
        self.functions: dict[str, ast.FunctionDef] = {}
        self.tests: list[str] = []
        self.fixtures: dict[str, str] = {}   # fixture name -> function key
        self.names: dict[str, int] = {}
        self.returns: dict[str, int] = {}
        self.own: dict[str, int] = {}       # walks the measured role by itself
        self.walks: dict[str, int] = {}     # parameters whose population it walks
        self.passes: dict[str, int] = {}    # parameters whose population it returns
        self.events: dict[str, list[tuple[int, str]]] = {}   # key ("" = module) -> walks
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self.imports[alias.asname] = (alias.name, None)
                    else:
                        head = alias.name.split(".")[0]
                        self.imports[head] = (head, None)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = self.dotted.split(".")
                    parts = parts[: len(parts) - node.level]
                    base = ".".join(parts + ([base] if base else []))
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = (base, alias.name)
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._define(node.name, node)
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._define(f"{node.name}.{item.name}", item,
                                     collected=node.name.startswith("Test"))

    def _define(self, key: str, func, collected: bool = True) -> None:
        self.functions[key] = func
        if any(_decorator_name(d) == "fixture" for d in func.decorator_list):
            self.fixtures[func.name] = key
        elif collected and func.name.startswith("test"):
            self.tests.append(key)

    def node_id(self, key: str) -> str:
        return f"{self.rel}::{key.replace('.', '::')}"


def _imported_modules(dotted: str, text: str) -> set[str]:
    """The modules the module *dotted* imports, and ``pkg.name`` for each ``from
    pkg import name`` (which may be a module), read without parsing it."""
    found = set()
    for match in _IMPORT_LINE.finditer(text):
        if match.group(1):
            base = match.group(1)
            if base.startswith("."):
                level = len(base) - len(base.lstrip("."))
                parts = dotted.split(".")[: -level]
                base = ".".join(parts + ([base.lstrip(".")] if base.lstrip(".") else []))
            found.add(base)
            for name in re.findall(r"\w+", match.group(2).split("#", 1)[0]):
                found.add(f"{base}.{name}")
        else:
            for part in match.group(3).split(","):
                found.add(part.strip().split(" ")[0])
    return found


class Scan:
    """The walk over ``tests/``: every module that can carry the measured role
    (it reads it, names the set, or imports from one that does), to a fixpoint."""

    def __init__(self, root: Path, measured: MeasuredSet):
        self.root = root
        self.measured = measured
        #: The modules whose tables moved in this pass, and those to walk next.
        self._moved: set[str] = set()
        self._dirty: set[str] = set()
        self.passes = 0
        self._texts: dict[str, tuple[Path, str]] = {}
        for path in sorted((root / "tests").rglob("*.py")):
            if "__pycache__" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="replace")
                self._texts[_dotted(root, path)] = (path, text)
        self._imports = {d: _imported_modules(d, text) for d, (_, text) in self._texts.items()}
        tokens = _ROLE_TOKENS + measured.tokens()
        self.modules: dict[str, Module] = {}
        self._add(
            dotted for dotted, (path, text) in self._texts.items()
            if path.name == "conftest.py" or any(t in text for t in tokens)
            or _FACTORY_BY_VARIABLE.search(text)
        )

    def _add(self, dotteds) -> None:
        """Parse each module, and every test module it imports (a helper whose
        walk of its argument decides a caller's verdict)."""
        pending = sorted(dotteds)
        while pending:
            dotted = pending.pop()
            if dotted in self.modules or dotted not in self._texts:
                continue
            path, text = self._texts[dotted]
            try:
                self.modules[dotted] = Module(self.root, path, text)
            except SyntaxError:
                continue
            pending.extend(m for m in self._imports[dotted] if m in self._texts)
            self._dirty.add(dotted)

    def _importers_of_carriers(self) -> set[str]:
        """The modules not yet read that import from one exporting the measured
        role: a tainted name, a function returning or walking it."""
        carriers = {
            dotted for dotted, module in self.modules.items()
            if any(module.names.values()) or any(module.returns.values())
            or any(module.own.values())
        }
        return {
            dotted for dotted, imported in self._imports.items()
            if dotted not in self.modules and imported & carriers
        }

    # --- resolution ---------------------------------------------------------

    def module_of(self, module: Module, local: str):
        """The analysed module a local name binds, if it binds one."""
        if local not in module.imports:
            return None
        base, name = module.imports[local]
        return self.modules.get(base if name is None else f"{base}.{name}")

    def function(self, module: Module, func) -> tuple[Module, str] | None:
        if isinstance(func, ast.Name):
            if func.id in module.functions:
                return module, func.id
            if func.id in module.imports:
                base, name = module.imports[func.id]
                owner = self.modules.get(base)
                if owner is not None and name in owner.functions:
                    return owner, name
            return None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            owner = self.module_of(module, func.value.id)
            if owner is not None and func.attr in owner.functions:
                return owner, func.attr
        return None

    def global_kind(self, module: Module, name: str) -> int:
        if name in module.names:
            return module.names[name]
        if name in module.imports:
            base, imported = module.imports[name]
            owner = self.modules.get(base)
            if owner is not None and imported is not None:
                return owner.names.get(imported, 0)
        return 0

    def fixture(self, module: Module, name: str) -> tuple[Module, str] | None:
        """The fixture a test parameter names: its own module's, then each conftest up."""
        if name in module.fixtures:
            return module, module.fixtures[name]
        parts = module.dotted.split(".")
        for depth in range(len(parts) - 1, 0, -1):
            conftest = self.modules.get(".".join(parts[:depth]) + ".conftest")
            if conftest is not None and name in conftest.fixtures:
                return conftest, conftest.fixtures[name]
        return None

    # --- the walk -----------------------------------------------------------

    def _readers(self) -> dict[str, set[str]]:
        """For each module, the analysed modules whose tables it reads: what it
        imports, and the conftests its fixtures may come from."""
        readers: dict[str, set[str]] = {}
        for dotted in self.modules:
            parts = dotted.split(".")
            read = {m for m in self._imports.get(dotted, ()) if m in self.modules}
            read |= {".".join(parts[:depth]) + ".conftest" for depth in range(1, len(parts))}
            for source in read | {dotted}:
                readers.setdefault(source, set()).add(dotted)
        return readers

    def run(self) -> "Scan":
        while True:
            readers = self._readers()
            while self._dirty and self.passes < 60:
                self.passes += 1
                self._moved = set()
                for dotted in sorted(self._dirty):
                    self._module(self.modules[dotted], record=False)
                self._dirty = {r for moved in self._moved for r in readers.get(moved, ())}
            more = self._importers_of_carriers()
            if not more:
                break
            self._add(more)
        for module in self.modules.values():
            module.events = {}
            self._module(module, record=True)
        return self

    def set(self, module: Module, table: dict, key, value) -> None:
        old = table.get(key, 0)
        if value | old != old:
            table[key] = value | old
            self._moved.add(module.dotted)

    def _module(self, module: Module, *, record: bool) -> None:
        _Walker(self, module, module.names, None, record).body(module.tree.body, top=True)
        for key, func in module.functions.items():
            params = _params(func) + [a.arg for a in func.args.kwonlyargs]
            fixtures: dict[str, int] = {}
            requested = []
            if key in module.tests or func.name in module.fixtures:
                for param in params:
                    found = self.fixture(module, param) if param not in SET_FIXTURES else None
                    if found is not None:
                        owner, fixture_key = found
                        if owner.returns.get(fixture_key):
                            fixtures[param] = owner.returns[fixture_key] & KINDS
                        if owner.own.get(fixture_key):
                            requested.append(param)
            # What it reads by itself: the test or fixture as pytest runs it.
            own = _Walker(self, module, dict(fixtures), key, record)
            for param in requested:
                own.event(func, f"requests the fixture {param}, which walks it", POOL)
            own.decorators(func)
            own.body(func.body)
            own.body(func.body)
            self.set(module, module.returns, key, own.returned & KINDS)
            self.set(module, module.own, key, int(bool(own.walked)))
            if record:
                continue
            # What it does with a population it is handed, parameter by parameter.
            handed = dict(fixtures)
            for index, param in enumerate(_params(func)):
                if param not in handed and param not in ("self", "cls") and param not in SET_FIXTURES:
                    handed[param] = POOL | (1 << (FIRST_PARAM_BIT + index))
            walks = _Walker(self, module, handed, key, False)
            walks.body(func.body)
            walks.body(func.body)
            self.set(module, module.walks, key, walks.walked >> FIRST_PARAM_BIT)
            if walks.returned & WHOLE:
                self.set(module, module.passes, key, walks.returned >> FIRST_PARAM_BIT)

    # --- the answer ---------------------------------------------------------

    def selection(self) -> dict[str, tuple[int, str]]:
        """``{node id: (line, why)}`` — each test that walks the population, and
        each module whose import walks it while none of its tests reads it (by
        path: the import runs for any of them)."""
        picked: dict[str, tuple[int, str]] = {}
        for module in self.modules.values():
            if not module.is_test:
                continue
            tests = [key for key in module.tests if module.events.get(key)]
            for key in tests:
                picked[module.node_id(key)] = module.events[key][0]
            if not tests and module.events.get(""):
                line, why = module.events[""][0]
                picked[module.rel] = (line, f"its import walks it: {why}")
        return picked


class _Walker:
    """One flow-insensitive walk of a body: the kinds its names carry, what it
    returns, and every place it walks a population."""

    def __init__(self, scan: Scan, module: Module, env: dict, key, record: bool):
        self.scan = scan
        self.module = module
        self.env = env
        self.key = key
        self.record = record
        self.returned = 0
        self.walked = 0

    def event(self, node, why: str, kind: int) -> None:
        self.walked |= kind | POOL
        if self.record:
            snippet = ast.unparse(node).replace("\n", " ") if isinstance(node, ast.expr) else ""
            text = f"{why}: {snippet}" if snippet else why
            self.module.events.setdefault(self.key or "", []).append(
                (getattr(node, "lineno", 0), text[:140])
            )

    def kind_of(self, name: str) -> int:
        if name in self.env:
            return self.env[name]
        return self.scan.global_kind(self.module, name)

    def bind(self, name: str, kind: int) -> None:
        if not kind:
            return
        if self.key is None:
            self.scan.set(self.module, self.module.names, name, kind & KINDS)
        else:
            self.env[name] = self.env.get(name, 0) | kind

    # --- statements ---------------------------------------------------------

    def decorators(self, func) -> None:
        for decorator in func.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            name = _decorator_name(decorator)
            kinds = [self.ev(a) for a in decorator.args]
            for keyword in decorator.keywords:
                kind = self.ev(keyword.value)
                if name == "fixture" and keyword.arg == "params" and kind & WHOLE:
                    self.event(keyword.value, "fixture params", kind)
            if name == "parametrize" and len(kinds) > 1 and kinds[1] & WHOLE:
                self.event(decorator.args[1], "parametrized over it", kinds[1])

    def body(self, stmts, top: bool = False) -> None:
        for stmt in stmts:
            self.stmt(stmt, top)

    def stmt(self, node, top: bool = False) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not top:  # a nested function reads the enclosing scope
                self.decorators(node)
                self.body(node.body)
            return
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.stmt(item)
                elif not top:
                    self.body(item.body)
            return
        if isinstance(node, ast.Assign):
            kind = self.ev(node.value)
            for target in node.targets:
                self.assign(target, kind, node.value)
            return
        if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            kind = self.ev(node.value) if node.value is not None else 0
            self.assign(node.target, kind, node.value)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            kind = self.ev(node.iter)
            filled = _index_builder(node) if isinstance(node, ast.For) else None
            if kind & WHOLE:
                if filled:
                    for name in filled:
                        self.bind(name, INDEX | _prov(kind))
                else:
                    self.event(node.iter, "walks", kind)
            if kind:
                for name in _bound_names(node.target):
                    self.bind(name, ELEM | _prov(kind))
            self.body(node.body)
            self.body(node.orelse)
            return
        if isinstance(node, ast.Return):
            if node.value is not None:
                self.returned |= self.ev(node.value)
            return
        if isinstance(node, (ast.While, ast.If)):
            self.ev(node.test)
            self.body(node.body)
            self.body(node.orelse)
            return
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                kind = self.ev(item.context_expr)
                if item.optional_vars is not None:
                    self.assign(item.optional_vars, kind, None)
            self.body(node.body)
            return
        if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            self.body(node.body)
            for handler in node.handlers:
                self.body(handler.body)
            self.body(node.orelse)
            self.body(node.finalbody)
            return
        if isinstance(node, ast.Match):
            self.ev(node.subject)
            for case in node.cases:
                self.body(case.body)
            return
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            return  # a docstring
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.ev(child)

    def assign(self, target, kind: int, value) -> None:
        if isinstance(target, ast.Name):
            self.bind(target.id, kind)
        elif isinstance(target, (ast.Tuple, ast.List)):
            # `pool, game = pool_and_game()`: a tuple of the same length is
            # bound element by element, so the game does not carry the pool.
            if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts):
                for elt, part in zip(target.elts, value.elts):
                    self.assign(elt, self.ev(part), part)
                return
            for elt in target.elts:
                self.assign(elt, kind, None)
        elif isinstance(target, ast.Starred):
            self.assign(target.value, kind, None)
        elif isinstance(target, ast.Subscript):
            self.ev(target.slice)
            if isinstance(target.value, ast.Name) and kind:
                self.bind(target.value.id, (POOL if kind & (ELEM | POOL) else kind) | _prov(kind))
        elif isinstance(target, ast.Attribute):
            self.ev(target.value)

    # --- expressions --------------------------------------------------------

    def ev(self, node) -> int:
        if node is None:
            return 0
        handler = _EXPRESSIONS.get(type(node))
        if handler is not None:
            return handler(self, node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.ev(child)
        return 0

    def _literal(self, node) -> int:
        if isinstance(node.value, str) and self.scan.measured.named_in(node.value):
            self.event(node, "names the set", POOL)
            return POOL
        return 0

    def _name(self, node) -> int:
        return self.kind_of(node.id)

    def _attribute(self, node) -> int:
        if isinstance(node.value, ast.Name):
            owner = self.scan.module_of(self.module, node.value.id)
            if owner is not None:
                return owner.names.get(node.attr, 0)
        return self.ev(node.value)

    def _subscript(self, node) -> int:
        value = self.ev(node.value)
        key = self.ev(node.slice)
        if isinstance(node.slice, ast.Constant) and node.slice.value == "measured":
            return POOL
        if isinstance(node.slice, ast.Slice):
            return value
        if key & ELEM and value & WHOLE:
            return ELEM | _prov(key | value)  # `POOL[name]` for a name the walk is on
        return ELEM | _prov(value) if value & (POOL | ELEM) else 0

    def _compare(self, node) -> int:
        kind = self.ev(node.left)
        for comparator in node.comparators:
            kind |= self.ev(comparator)
        if kind & WHOLE and any(not isinstance(op, _MEMBERSHIP) for op in node.ops):
            self.event(node, "compares", kind)
        return 0

    def _union(self, parts) -> int:
        kind = 0
        for part in parts:
            kind |= self.ev(part)
        return kind

    def _binop(self, node) -> int:
        kind = self.ev(node.left) | self.ev(node.right)
        if isinstance(node.op, _SET_OPS) and kind & WHOLE:
            self.event(node, "set arithmetic", kind)
        return kind

    def _unaryop(self, node) -> int:
        kind = self.ev(node.operand)
        return 0 if isinstance(node.op, ast.Not) else kind

    def _ifexp(self, node) -> int:
        self.ev(node.test)
        return self.ev(node.body) | self.ev(node.orelse)

    def _lambda(self, node) -> int:
        self.ev(node.body)
        return 0

    def _yield(self, node) -> int:
        kind = self.ev(node.value)
        self.returned |= kind
        return kind

    def _namedexpr(self, node) -> int:
        kind = self.ev(node.value)
        self.bind(node.target.id, kind)
        return kind

    def comprehension(self, node) -> int:
        iters = 0
        for generator in node.generators:
            kind = self.ev(generator.iter)
            iters |= kind
            if kind:
                for name in _bound_names(generator.target):
                    self.env[name] = self.env.get(name, 0) | ELEM | _prov(kind)
            for test in generator.ifs:
                self.ev(test)
        if isinstance(node, ast.DictComp):
            element = self.ev(node.key) | self.ev(node.value)
        else:
            element = self.ev(node.elt)
        if iters & WHOLE:
            targets = {n for g in node.generators for n in _bound_names(g.target)}
            if _name_lookup(node.generators):
                return 0
            if (isinstance(node, ast.DictComp) and _is_name_of(node.key, targets)
                    and not any(g.ifs for g in node.generators)):
                return INDEX | _prov(iters)
            self.event(node, "walks", iters)
            return POOL | _prov(iters)
        if iters & ELEM:
            return ELEM | _prov(iters)
        return element & ~ELEM if element & WHOLE else 0

    def call(self, node: ast.Call) -> int:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None)
        receiver = self.ev(func.value) if isinstance(func, ast.Attribute) else 0
        args = [self.ev(a) for a in node.args]
        keywords = {k.arg: self.ev(k.value) for k in node.keywords}
        handed = 0
        for kind in (*args, *keywords.values()):
            handed |= kind
        if name in MEASURED_ROLE:
            return POOL
        if name in BOTH_ROLES and _truthy_keyword(node, "include_measured"):
            return POOL
        if name in ONE_SET:
            return POOL if _truthy_keyword(node, "include_measured") and args and args[0] else 0
        if isinstance(func, ast.Name) and name in SET_FIXTURES and name not in self.module.functions:
            return SET_FIXTURES[name] if args and args[0] else 0
        known = self.scan.function(self.module, func)
        if known is not None:
            return self.known_call(node, known, args, keywords, handed)
        if isinstance(func, ast.Attribute):
            if name in MUTATORS and isinstance(func.value, ast.Name) and handed:
                if (name == "setdefault" and node.args and isinstance(node.args[0], ast.Attribute)
                        and node.args[0].attr == "name"):
                    self.bind(func.value.id, INDEX | _prov(handed))
                else:
                    self.bind(func.value.id,
                              (POOL if handed & (ELEM | POOL) else handed) | _prov(handed))
                return 0
            if receiver & WHOLE:
                if name in VIEWS:
                    return POOL | _prov(receiver)
                if name in LOOKUPS:
                    return 0
                return receiver
            if receiver & ELEM:
                return ELEM | _prov(receiver)
        if name in CONSUMERS and handed & WHOLE:
            self.event(node, "counts", handed)
            return 0
        return handed

    def known_call(self, node, known, args, keywords, handed) -> int:
        owner, key = known
        params = _params(owner.functions[key])
        walked = owner.walks.get(key, 0)
        passed = owner.passes.get(key, 0)
        hits_walk = hits_pass = 0
        handed_at = [(index, kind) for index, kind in enumerate(args)]
        handed_at += [(params.index(k), kind) for k, kind in keywords.items() if k in params]
        for index, kind in handed_at:
            if kind & WHOLE and index < len(params):
                bit = 1 << index
                hits_walk |= kind if walked & bit else 0
                hits_pass |= kind if passed & bit else 0
        where = f"{owner.dotted.rsplit('.', 1)[-1]}.{key}"
        if owner.own.get(key):
            self.event(node, f"calls {where}, which walks it", POOL)
        elif hits_walk:
            self.event(node, f"hands it to {where}, which walks it", hits_walk)
        result = owner.returns.get(key, 0)
        if hits_pass:
            result |= POOL | _prov(hits_pass)
        return result | (handed & ELEM)



#: The walker's reading of each expression type; any other walks its children.
_EXPRESSIONS = {
    ast.Constant: _Walker._literal,
    ast.Name: _Walker._name,
    ast.Attribute: _Walker._attribute,
    ast.Subscript: _Walker._subscript,
    ast.Call: _Walker.call,
    ast.Compare: _Walker._compare,
    ast.BoolOp: lambda walker, node: walker._union(node.values),
    ast.BinOp: _Walker._binop,
    ast.UnaryOp: _Walker._unaryop,
    ast.IfExp: _Walker._ifexp,
    ast.Lambda: _Walker._lambda,
    ast.ListComp: _Walker.comprehension,
    ast.SetComp: _Walker.comprehension,
    ast.GeneratorExp: _Walker.comprehension,
    ast.DictComp: _Walker.comprehension,
    ast.List: lambda walker, node: walker._union(node.elts),
    ast.Tuple: lambda walker, node: walker._union(node.elts),
    ast.Set: lambda walker, node: walker._union(node.elts),
    ast.Dict: lambda walker, node: walker._union((*node.keys, *node.values)),
    ast.Starred: lambda walker, node: walker.ev(node.value),
    ast.Yield: _Walker._yield,
    ast.YieldFrom: _Walker._yield,
    ast.NamedExpr: _Walker._namedexpr,
}

def scan(root: Path, code: str) -> Scan:
    """The walk of *root*'s ``tests/`` for the measured set *code*."""
    return Scan(Path(root), MeasuredSet.read(Path(root), code)).run()
