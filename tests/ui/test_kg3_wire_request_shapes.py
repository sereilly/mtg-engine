"""Every value a client request body carries is one its field accepts.

Known gap "The request-body guard derives presence, not shape":
``tests/ui/test_kg_client_request_schemas.py`` holds every body to its route's
required fields and its handler's refusals, and no value's **type** was
checked — a list where an int is declared, a non-numeric string for an index,
a word no ``Literal`` lists, an object for a flag, a negative slot: each is a
422 the reader passed over.

This reads the type of every value it can follow — the same reader
(``tests/ui/js_requests.py``), with one more kind of answer (``TypeReader``):
string, template, number, boolean, null, array, object, and the calls and
operators whose result type is fixed (``Number(…)``, ``.length``,
``.map(…)``, ``!x``, ``a === b``) — through bindings, callers and returns as
the body reader does. Whether a value is acceptable is **pydantic's** answer,
not a table here: each JS type is given a representative and validated
through ``web/schemas.py``'s own model, constraints included, so a value is
refused only where every value of its JS type would be (a template string
might be numeric; a string literal is exactly itself). A nested model's
entries (``divided_targets``, ``mode_choices``, …) are checked against theirs.

The state-dependent half — the handlers that refuse on the prompt's own
state — is ``test_kg3_wire_prompt_state_bodies.py``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ValidationError

from web.schemas import GameActionRequest

from .js_requests import (IDENT, Reader, Script, _OPEN, _trim, load_scripts,
                          request_sites, split_top_level)
from .test_kg_client_request_schemas import nested_models, route_for

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"
TYPES = "types"

_NUMBER_RE = re.compile(r"-?\d+(\.\d+)?\Z")
#: Calls whose result has one type whatever they are given, by the callee's
#: last name (a method) or its whole spelling (a function).
_ARRAY_METHODS = frozenset({"map", "filter", "slice", "concat", "sort", "flatMap", "reverse"})
_NUMBER_METHODS = frozenset({"indexOf", "findIndex", "lastIndexOf"})
_TYPED_FUNCTIONS = {
    "Number": "number", "parseInt": "number", "parseFloat": "number",
    "String": "template", "Boolean": "bool",
    "Array.from": "array", "Object.keys": "array", "Object.values": "array",
    "Object.entries": "array",
}


_OPENERS: dict = {}


def _final_call(script, a: int, b: int):
    """``(callee spelling, is a method)`` of the call that is the whole
    expression ``[a, b)`` at its own depth (``xs.filter(…).map(…)`` is a
    ``map``), or None."""
    code = script.code
    if code[b - 1:b] != ")":
        return None
    openers = _OPENERS.get(id(script))
    if openers is None:
        openers = _OPENERS[id(script)] = {c: o for o, c in script.match.items()}
    opener = openers.get(b - 1)
    if opener is None or opener <= a or code[opener] != "(":
        return None
    m = re.search(rf"(\??\.)?({IDENT}(?:\.{IDENT})*)\s*\Z", code[a:opener])
    if m is None:
        return None
    return m.group(2), m.group(1) is not None


_COMPARISON = ("===", "!==", "==", "!=", "<=", ">=", " < ", " > ", " instanceof ", " in ")


class TypeReader(Reader):
    """The body reader with a fourth kind of answer: the JS types an
    expression can have, as ``(type, literal value or None)`` pairs."""

    #: How many calls, callers and bindings deep a type is followed past the
    #: value itself. The body reader's own limit is generous because a body is
    #: read once per site; a type is read for every value of every body, and a
    #: body spread from a module-level variable (``...pending.actionBody``)
    #: brings in every value of every body ever written to it.
    TYPE_DEPTH = 3

    def __init__(self, scripts):
        super().__init__(scripts)
        self._memo: dict = {}
        self._limit = None
        self._binding_memo: dict = {}

    # Reading a type re-reads the same bindings many times over (every value
    # of every body); the lookup is a pure scan of the source.
    def _bindings(self, script, name, lo, hi):
        key = (script.name, name, lo, hi)
        if key not in self._binding_memo:
            self._binding_memo[key] = super()._bindings(script, name, lo, hi)
        return self._binding_memo[key]


    def types_of(self, value):
        script, a, b, ctx = value
        # Keyed by the value's span and the argument spans its function's
        # parameters are bound to — one reading per call site, not one per
        # chain of callers that led to it.
        key = (script.name, a, b, tuple(
            (name, bound[0].name, bound[1], bound[2]) for name, bound in ctx.env
        ))
        if key not in self._memo:
            self._limit = ctx.depth + self.TYPE_DEPTH
            try:
                self._memo[key] = self._eval(TYPES, script, a, b, ctx)
            finally:
                self._limit = None
        return self._memo[key]

    def _eval(self, kind, script, a, b, ctx):
        # While a type is being read, every kind of reading it does (the
        # objects a member is read off, the callers a parameter is read from)
        # is held to the type's depth.
        if self._limit is not None and ctx.depth > self._limit:
            return _OPEN
        if kind == TYPES:
            a, b = _trim(script.code, a, b)
            text = script.code[a:b]
            if text in ("true", "false"):
                return [("bool", text == "true")]
            if text in ("null", "undefined"):
                return [("null", None)]
            if _NUMBER_RE.match(text):
                return [("number", float(text) if "." in text else int(text))]
            if text == "[]":
                return [("array", ())]
        return super()._eval(kind, script, a, b, ctx)

    def _with_writes(self, kind, script, name, ctx, result, everywhere=False):
        # A type reads the object a member is read off as it was built, not
        # every ``obj.key = …`` written onto it afterwards — the writes are a
        # scan of the whole function per reading, and a body's own writes are
        # read where the body is (below, through ``bodies_at``).
        if kind == TYPES or self._limit is not None:
            return result
        return super()._with_writes(kind, script, name, ctx, result, everywhere)

    def _leaf(self, kind, script, a, b, ctx):
        if kind != TYPES:
            return super()._leaf(kind, script, a, b, ctx)
        code = script.code
        text = code[a:b]
        literal = script.string_at(a, b)
        if literal is not None:
            return [("string", literal)]
        if text[:1] == "`":
            return [("template", None)]
        if script.is_group(a, b, "["):
            entries = []
            for x, y in split_top_level(code, a + 1, b - 1, script.match):
                if code.startswith("...", x):
                    entries = None
                    break
                got = self._eval(TYPES, script, x, y, ctx.at(x))
                if got is _OPEN or len(got) != 1:
                    entries = None
                    break
                entries.append(got[0])
            return [("array", tuple(entries) if entries is not None else None)]
        if script.is_group(a, b, "{"):
            return [("object", None)]
        if text.startswith("!") and not text.startswith("!="):
            return [("bool", None)]
        for op in ("??", "||", "&&"):
            parts = self._split_operator(script, a, b, op)
            if parts:
                results = [self._eval(TYPES, script, x, y, ctx.at(x)) for x, y in parts]
                if any(r is _OPEN for r in results):
                    return _OPEN
                return [t for r in results for t in r]
        if any(self._split_operator(script, a, b, op) for op in _COMPARISON):
            return [("bool", None)]
        if any(self._split_operator(script, a, b, op) for op in (" - ", " * ", " / ", " % ")):
            return [("number", None)]
        if re.search(rf"\.(?:length|size)\Z", text):
            return [("number", None)]
        call = _final_call(script, a, b)
        if call is not None:
            callee, dotted = call
            last = callee.rsplit(".", 1)[-1]
            method = dotted or "." in callee
            if not dotted and callee in _TYPED_FUNCTIONS:
                return [(_TYPED_FUNCTIONS[callee], None)]
            if not dotted and callee.startswith("Math."):
                return [("number", None)]
            if method and last in _ARRAY_METHODS:
                return [("array", None)]
            if method and last in _NUMBER_METHODS:
                return [("number", None)]
        return NotImplemented


def _representatives(js_type) -> list:
    """Python values a JS value of *js_type* can arrive as. A value is
    refused only when all of them are: the reader knows a template is a
    string, not which."""
    kind, literal = js_type
    if kind == "string":
        return [literal]
    if kind == "template":
        return ["1", "x"]
    if kind == "number":
        return [literal] if literal is not None else [0, 1, 1.5]
    if kind == "bool":
        return [literal] if literal is not None else [True, False]
    if kind == "null":
        return [None]
    if kind == "array":
        if literal is None:
            return [[]]
        choices = [[]]
        for entry in literal:
            choices = [c + [r] for c in choices for r in _representatives(entry)]
        return choices
    if kind == "object":
        return [{}]
    return []


def refusal(model: type[BaseModel], field: str, value) -> str | None:
    """Pydantic's own reason *model* refuses *value* for *field* — the
    field's annotation and constraints both — or None."""
    data = dict(_required_fillers(model))
    data[field] = value
    try:
        model.model_validate(data)
    except ValidationError as exc:
        for error in exc.errors():
            if error["loc"] and error["loc"][0] == field:
                return error["msg"]
    return None


@lru_cache(maxsize=None)
def _required_fillers(model) -> tuple:
    return tuple(
        (name, _filler(f)) for name, f in model.model_fields.items() if f.is_required()
    )


def _filler(field_info):
    """A value the required field accepts, so a check of another field is
    about that field alone."""
    for candidate in (0, "pass_priority", "x", {}, []):
        try:
            from pydantic import TypeAdapter

            TypeAdapter(field_info.annotation).validate_python(candidate)
            return candidate
        except ValidationError:
            continue
    return None


class Shapes:
    """Every typed value of every request body the scripts build."""

    def __init__(self, scripts, lines=None):
        self.reader = TypeReader(scripts)
        for script in scripts:
            # One scan of the source per function name, not one per reading.
            original = script.calls_of
            cache: dict = {}
            script.calls_of = (
                lambda name, _o=original, _c=cache: _c[name] if name in _c else _c.setdefault(name, _o(name))
            )
        self.checked = 0
        self.unknown = 0
        self.problems: list[str] = []
        for site in request_sites(scripts):
            if lines is not None and site.line not in lines:
                continue
            route = route_for(site.url, site.method)
            if route is None or route[2] is None:
                continue
            bodies = self.reader.bodies_at(site.script, *site.body)
            if bodies is _OPEN or bodies is None:
                continue
            for body in bodies:
                self._check(route[2], body, body.where())

    def _check(self, model, body, where: str) -> None:
        nested = nested_models(model)
        for field in model.model_fields:
            for value in body.value_of(field):
                types = self.reader.types_of(value)
                if types is _OPEN or not types:
                    self.unknown += 1
                else:
                    self.checked += 1
                    for js_type in set(types):
                        reasons = [refusal(model, field, v) for v in _representatives(js_type)]
                        if reasons and all(reasons):
                            self.problems.append(
                                f"{where}: {field} = {js_type[0]}"
                                f"{'' if js_type[1] is None else ' ' + repr(js_type[1])}"
                                f" is refused ({reasons[0]})"
                            )
                if field in nested:
                    entries = self.reader.elements_of(value)
                    for entry in entries if entries not in (None, _OPEN) else ():
                        self._check(nested[field], entry, f"{where} {field}[]")


@lru_cache(maxsize=1)
def shapes() -> Shapes:
    return Shapes(load_scripts(STATIC))


def test_the_reader_types_most_of_what_the_bodies_carry():
    found = shapes()
    # Measured at kg3: 970 of 3,217 values typed. Most of the rest are read
    # off the state payload (``info.id``, ``entry.hand_index``), whose type
    # is the server's own.
    assert found.checked >= 900, (found.checked, found.unknown)
    assert found.checked / (found.checked + found.unknown) >= 0.25, (found.checked, found.unknown)


def test_the_type_reading_reads_each_shape():
    """The shapes it has to tell apart, read off a tiny script."""
    source = (
        "function f(xs, n) {\n"
        "  const ids = xs.map((x) => x.id);\n"
        "  return { a: \"W\", b: 3, c: true, d: null, e: [1, 2], f: {}, g: ids,"
        " h: `${n}`, i: !n, j: xs.length, k: n === 1, l: ids ?? 0, m: [...xs] };\n"
        "}\n"
    )
    script = Script(Path("probe.js"), source=source)
    reader = TypeReader([script])
    opener = source.index("{ a:")
    [body] = reader.bodies_at(script, opener, script.match[opener] + 1)
    got = {key: reader.types_of(body.value_of(key)[0]) for key in body.keys}
    assert got["a"] == [("string", "W")]
    assert got["b"] == [("number", 3)]
    assert got["c"] == [("bool", True)]
    assert got["d"] == [("null", None)]
    assert got["e"] == [("array", (("number", 1), ("number", 2)))]
    assert got["f"] == [("object", None)]
    assert got["g"] == [("array", None)]
    assert got["h"] == [("template", None)]
    assert got["i"] == got["k"] == [("bool", None)]
    assert got["j"] == [("number", None)]
    assert got["l"] == [("array", None), ("number", 0)]
    assert got["m"] == [("array", None)]


def test_pydantic_says_what_a_field_refuses():
    assert refusal(GameActionRequest, "hand_index", "x")
    assert refusal(GameActionRequest, "hand_index", -1), "the ge=0 constraint is read too"
    assert refusal(GameActionRequest, "hand_index", "1") is None, "lax mode takes a numeric string"
    assert refusal(GameActionRequest, "discard_indices", 3)
    assert refusal(GameActionRequest, "mana_color", "purple")
    assert refusal(GameActionRequest, "accept", {})
    assert refusal(GameActionRequest, "target_permanent_ids", []) is None


def test_every_value_a_body_carries_is_one_its_field_accepts():
    assert shapes().problems == []


def _break(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, f"the fixture text is not unique: {old!r}"
    return source.replace(old, new)


def test_the_guard_names_values_broken_on_purpose():
    """Backwards, every run: each mutation is a 422 this guard exists for,
    made in a copy of ``app.js``; each must be named, and nothing else."""
    path = STATIC / "app.js"
    source = path.read_text(encoding="utf-8")
    broken = source
    # 1. A word where an id is declared.
    broken = _break(broken, 'action: "untap_select", permanent_id: permanentId })\n            .then(',
                    'action: "untap_select", permanent_id: "first" })\n            .then(')
    # 2. A number where a list is declared.
    broken = _break(broken, 'action: "discard_confirm", discard_indices: indices,',
                    'action: "discard_confirm", discard_indices: 3,')
    # 3. A word no Literal lists.
    broken = _break(broken, 'action: "pile_search_confirm", accept: false',
                    'action: "pile_search_confirm", accept: false, from_zone: "grave"')
    # 4. A negative slot (`ge=0`).
    broken = _break(broken, 'seat, action: "word_of_command_confirm", accept: false',
                    'seat, action: "word_of_command_confirm", accept: false, hand_index: -1')
    # 5. An object for a flag.
    broken = _break(broken, 'seat, action: "face_down_cast_confirm", accept: false',
                    'seat, action: "face_down_cast_confirm", accept: {}')
    scripts = [Script(path, source=broken) if s.name == "app.js" else s for s in load_scripts(STATIC)]
    # Read at the five mutated sites (the clean tree's every site is the test
    # above), which keeps this one quick.
    marks = ('permanent_id: "first"', "discard_indices: 3,", '"grave"', "hand_index: -1", "accept: {}")
    lines = {broken[:broken.index(mark)].count(chr(10)) + 1 for mark in marks}
    problems = Shapes(scripts, lines=lines).problems
    text = "\n".join(problems)
    assert any("permanent_id = string 'first'" in p for p in problems), text
    assert any("discard_indices = number 3" in p for p in problems), text
    assert any("from_zone = string 'grave'" in p for p in problems), text
    assert any("hand_index = number -1" in p for p in problems), text
    assert any("accept = object" in p for p in problems), text
    assert len(problems) == 5, text
