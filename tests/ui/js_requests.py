"""What the browser's scripts put in a request — read without a JS engine.

The server's half of a request is declared (``web/schemas.py``, the handlers'
own refusals); the client's half is whatever object literal a click happens to
build, and the only reader of that line is the browser, where a missing field is
a 422 in a console nobody opens. This module reads the client's half so a test
can hold the two together. Four small pieces, each deliberately dumb:

* :func:`mask` — a lexer that blanks every comment, string body, template text
  and regex literal to same-length filler (newlines kept), so every bracket,
  comma and colon left is code. Brace matching on the result is exact — which
  the old ``sendAction({`` scan was not: a ``"{"`` in a string or a
  ``/\\{x\\}/`` regex inside a body would have ended it early.
* :class:`Script` — one file's bracket pairs and named functions.
* :class:`Reader` — a small evaluator. An object literal is a body; a name is
  followed to its bindings in the enclosing functions, or, when it is a
  function's parameter, to the argument every caller passes, with all of that
  function's parameters bound to that caller's arguments (so
  ``applyChoiceButtonPrompt(info, { action, field })`` is read once per caller,
  with that caller's ``action`` and ``field``); a call of a script function is
  read through its ``return``; and every ``name.key =`` / ``name[expr] =`` write
  a function makes to a body it holds or was handed adds that key (so
  ``withPermanentId(body, "permanent_id", …)`` adds ``permanent_id``).
  Anything it cannot follow makes the body **open** — "may carry keys not
  shown" — so a check over it can only report a field it never saw supplied.
* :func:`request_sites` — every place a request leaves: the *funnels* (a
  function whose ``fetch`` posts one of its parameters as the body — ``postJson``
  — and a function that hands one of its parameters to a funnel with a fixed
  URL — ``sendAction``) are found from the code, and every call of one outside
  the funnels is a site, with its URL and its body expression.

Path-insensitive by design: every binding, branch and caller is a candidate,
and a write anywhere in the function counts. A field supplied on one branch is
therefore read as supplied — the reader errs towards silence about a body it saw
supply the field somewhere, never towards a false alarm.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from pathlib import Path

IDENT = r"[A-Za-z_$][\w$]*"
_IDENT_RE = re.compile(rf"{IDENT}\Z")
_KEY_RE = re.compile(rf"({IDENT})\s*:")
_QUOTED_KEY_RE = re.compile(r"([\"'])(x*)\1\s*:")
_REGEX_AFTER_CHARS = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_AFTER_WORDS = {
    "return", "typeof", "case", "in", "of", "new", "delete", "void", "throw",
    "instanceof", "yield", "await", "else", "do",
}
# A ``(…) {`` whose head is one of these is a statement's block, not a function.
_BLOCK_HEADS = {"if", "for", "while", "switch", "catch", "with"}
_STRING_RE = re.compile(r"([\"'`])(x*)\1\Z")
_CONTINUES_LINE = set("=+-*/%&|?:.,<>!~^(")
_STARTS_CONTINUATION = set("?:.&|+-*/%<>=,")


def mask(source: str) -> str:
    """*source* with string bodies, template text and regex literals replaced
    by ``x`` filler of the same length, and comments by spaces (newlines
    kept).

    A template's ``${…}`` stays code — its braces are a pair like any other —
    and its text either side is blanked; a ``/`` is a regex where an operand
    is expected (after an operator, an opening bracket or a keyword such as
    ``return``) and a division elsewhere.
    """
    out = list(source)
    n = len(source)
    depth = 0
    template_depths: list[int] = []
    i = 0
    last_sig = ""
    last_word = ""

    def blank(start: int, end: int, filler: str = "x") -> None:
        for k in range(start, min(end, n)):
            if out[k] != "\n":
                out[k] = filler

    def template_text(start: int) -> int:
        nonlocal depth
        k = start
        while k < n:
            ch = source[k]
            if ch == "\\":
                blank(k, k + 2)
                k += 2
                continue
            if ch == "`":
                return k + 1
            if ch == "$" and k + 1 < n and source[k + 1] == "{":
                depth += 1
                template_depths.append(depth)
                return k + 2
            blank(k, k + 1)
            k += 1
        return n

    while i < n:
        c = source[i]
        # A comment is blanked to **spaces**, not filler: it is no operand,
        # and filler left a comment inside an object literal reading as the
        # start of the property after it — the key and its value were dropped
        # from every body that put a comment above them.
        if c == "/" and source.startswith("//", i):
            end = source.find("\n", i)
            end = n if end < 0 else end
            blank(i, end, " ")
            i = end
            continue
        if c == "/" and source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = n if end < 0 else end + 2
            blank(i, end, " ")
            i = end
            continue
        if c in "'\"":
            k = i + 1
            while k < n and source[k] != c and source[k] != "\n":
                k += 2 if source[k] == "\\" else 1
            blank(i + 1, k)
            i = k + 1
            last_sig, last_word = c, ""
            continue
        if c == "`":
            i = template_text(i + 1)
            last_sig, last_word = "`", ""
            continue
        if c == "/" and (
            last_sig in _REGEX_AFTER_CHARS or last_sig == ""
            or last_word in _REGEX_AFTER_WORDS
        ):
            k = i + 1
            in_class = False
            while k < n and source[k] != "\n":
                ch = source[k]
                if ch == "\\":
                    k += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    break
                k += 1
            blank(i + 1, k)
            i = k + 1
            while i < n and source[i].isalnum():
                i += 1
            last_sig, last_word = "/", ""
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            if template_depths and template_depths[-1] == depth:
                template_depths.pop()
                depth -= 1
                i = template_text(i + 1)
                last_sig, last_word = "`", ""
                continue
            depth -= 1
        if c.isalnum() or c in "_$":
            start = i
            while i < n and (source[i].isalnum() or source[i] in "_$"):
                i += 1
            last_word = source[start:i]
            last_sig = last_word[-1]
            continue
        if not c.isspace():
            last_sig, last_word = c, ""
        i += 1
    return "".join(out)


def split_top_level(code: str, start: int, end: int, match: dict) -> list[tuple[int, int]]:
    """The comma-separated parts of ``code[start:end]`` at its own depth, as
    trimmed spans, empty parts dropped."""
    parts = []
    part_start = start
    j = start
    while j < end:
        ch = code[j]
        if ch in "([{":
            j = match[j] + 1
            continue
        if ch == ",":
            parts.append((part_start, j))
            part_start = j + 1
        j += 1
    parts.append((part_start, end))
    return [span for span in (_trim(code, a, b) for a, b in parts) if span[0] < span[1]]


def _trim(code: str, a: int, b: int) -> tuple[int, int]:
    while a < b and code[a].isspace():
        a += 1
    while b > a and (code[b - 1].isspace() or code[b - 1] == ";"):
        b -= 1
    return a, b



@dataclass(frozen=True)
class Param:
    #: The bound name, or None for a destructured parameter.
    name: str | None
    #: The names a destructured ``{ a, b: c }`` parameter binds, each to the
    #: property it reads: ``(("a", "a"), ("c", "b"))``.
    destructured: tuple = ()
    #: The span of a default value (``castAction = "cast"``), if any.
    default: tuple | None = None

    def binds(self, name: str) -> bool:
        return self.name == name or any(local == name for local, _ in self.destructured)


@dataclass(frozen=True)
class Function:
    name: str
    params: tuple
    body_open: int
    body_close: int

    def param_index(self, name: str) -> int | None:
        for index, param in enumerate(self.params):
            if param.binds(name):
                return index
        return None


class Script:
    """One browser script: its masked text, bracket pairs and function bodies."""

    def __init__(self, path: Path, source: str | None = None):
        self.path = path
        self.name = path.name
        self.source = path.read_text(encoding="utf-8") if source is None else source
        self.code = mask(self.source)
        self._newlines = [i for i, ch in enumerate(self.source) if ch == "\n"]
        self.match: dict = {}
        self.opener_of: dict = {}
        stack: list = []
        for index, ch in enumerate(self.code):
            if ch in "([{":
                stack.append(index)
            elif ch in ")]}":
                if not stack:
                    raise ValueError(f"{self.name}: unbalanced {ch!r} at line {self.line(index)}")
                opener = stack.pop()
                self.match[opener] = index
                self.opener_of[index] = opener
        if stack:
            raise ValueError(f"{self.name}: unclosed bracket at line {self.line(stack[-1])}")
        # Every function body, named or not, as a sorted list of openers.
        self._bodies = sorted(
            opener for opener, closer in self.match.items()
            if self.code[opener] == "{" and self._opens_function_body(opener)
        )
        self.functions = self._named_functions()
        self.function_at = {fn.body_open: fn for fn in self.functions}
        self._around: dict = {}
        self.globals = self._top_level_declarations()

    # --- positions ---------------------------------------------------------

    def line(self, position: int) -> int:
        return bisect.bisect_left(self._newlines, position) + 1

    def next_significant(self, position: int) -> int:
        j = position
        while j < len(self.code) and self.code[j].isspace():
            j += 1
        return j

    def previous_significant(self, position: int) -> int:
        j = position - 1
        while j >= 0 and self.code[j].isspace():
            j -= 1
        return j

    def is_group(self, a: int, b: int, opener: str) -> bool:
        """Whether ``[a, b)`` is exactly one bracketed group."""
        return self.code[a:a + 1] == opener and self.match.get(a) == b - 1

    def string_at(self, a: int, b: int) -> str | None:
        """The value of ``source[a:b]`` when it is one string literal (a
        template only when it has no ``${…}``)."""
        a, b = _trim(self.code, a, b)
        if _STRING_RE.fullmatch(self.code[a:b]):
            return self.source[a + 1:b - 1]
        return None

    def template_at(self, a: int, b: int) -> str | None:
        """A string or template literal with every ``${…}`` written ``{}``."""
        a, b = _trim(self.code, a, b)
        if self.code[a:a + 1] not in ("'", '"', "`") or self.code[b - 1:b] != self.code[a]:
            return None
        out = []
        j = a + 1
        while j < b - 1:
            if self.code.startswith("${", j):
                out.append("{}")
                j = self.match[j + 1] + 1
                continue
            out.append(self.source[j])
            j += 1
        return "".join(out)

    def interpolations(self, a: int, b: int) -> list:
        """The expression spans of a template literal's ``${…}``."""
        spans = []
        j = a
        while j < b:
            if self.code.startswith("${", j):
                closer = self.match[j + 1]
                spans.append((j + 2, closer))
                j = closer + 1
                continue
            j += 1
        return spans

    def expression_end(self, start: int) -> int:
        """Where the expression starting at *start* ends: a ``;``, a ``,`` or a
        closing bracket at its own depth, or a line break that ends the
        statement (the line neither ends on nor the next starts with an
        operator)."""
        j = start
        code = self.code
        n = len(code)
        while j < n:
            ch = code[j]
            if ch in "([{":
                j = self.match[j] + 1
                continue
            if ch in ")]};,":
                return j
            if ch == "\n":
                prev = self.previous_significant(j)
                nxt = self.next_significant(j)
                if (
                    prev >= start and code[prev] not in _CONTINUES_LINE
                    and nxt < n and code[nxt] not in _STARTS_CONTINUATION
                ):
                    return j
            j += 1
        return n

    # --- functions and scopes ---------------------------------------------

    def _opens_function_body(self, opener: int) -> bool:
        j = self.previous_significant(opener)
        if j >= 1 and self.code[j - 1:j + 1] == "=>":
            return True
        if j < 0 or self.code[j] != ")":
            return False
        k = self.previous_significant(self.opener_of[j]) + 1
        start = k
        while start > 0 and (self.code[start - 1].isalnum() or self.code[start - 1] in "_$"):
            start -= 1
        word = self.code[start:k]
        return bool(word) and word not in _BLOCK_HEADS

    def _params(self, open_paren: int) -> tuple:
        params = []
        for a, b in split_top_level(self.code, open_paren + 1, self.match[open_paren], self.match):
            default = None
            m = re.match(rf"(?:\.\.\.)?({IDENT})\s*(=)?", self.code[a:b])
            if self.code[a] == "{":
                names = []
                for pa, pb in split_top_level(self.code, a + 1, self.match[a], self.match):
                    part = self.code[pa:pb].split("=")[0].strip()
                    if ":" in part:
                        prop, local = (s.strip() for s in part.split(":", 1))
                    else:
                        prop = local = part.lstrip(".").strip()
                    names.append((local, prop))
                params.append(Param(None, tuple(names)))
                continue
            if m and m.group(2):
                default = (a + m.end(), b)
            params.append(Param(m.group(1) if m else None, (), default))
        return tuple(params)

    def scope_params(self, opener: int) -> tuple:
        """The parameters of the function whose body opens at *opener*."""
        fn = self.function_at.get(opener)
        if fn is not None:
            return fn.params
        j = self.previous_significant(opener)
        if self.code[j - 1:j + 1] == "=>":
            k = self.previous_significant(j - 1)
            if self.code[k] == ")":
                return self._params(self.opener_of[k])
            start = k + 1
            while start > 0 and (self.code[start - 1].isalnum() or self.code[start - 1] in "_$"):
                start -= 1
            return (Param(self.code[start:k + 1]),)
        if self.code[j] == ")":
            return self._params(self.opener_of[j])
        return ()

    def _named_functions(self) -> list:
        found = []
        for m in re.finditer(rf"\bfunction\s*\*?\s*({IDENT})\s*\(", self.code):
            paren = m.end() - 1
            body = self.next_significant(self.match[paren] + 1)
            if self.code[body:body + 1] == "{":
                found.append(Function(m.group(1), self._params(paren), body, self.match[body]))
        arrow = re.compile(rf"\b(?:const|let|var)\s+({IDENT})\s*=\s*(?:async\s*)?\(")
        for m in arrow.finditer(self.code):
            paren = m.end() - 1
            after = self.next_significant(self.match[paren] + 1)
            if not self.code.startswith("=>", after):
                continue
            body = self.next_significant(after + 2)
            if self.code[body:body + 1] == "{":
                found.append(Function(m.group(1), self._params(paren), body, self.match[body]))
        found.sort(key=lambda f: f.body_open)
        return found

    def function_body_around(self, position: int) -> int | None:
        """The opening brace of the innermost function body, named or not
        (an arrow's, a callback's), around *position*."""
        if position in self._around:
            return self._around[position]
        index = bisect.bisect_left(self._bodies, position) - 1
        found = None
        while index >= 0:
            opener = self._bodies[index]
            if self.match[opener] > position:
                found = opener
                break
            index -= 1
        self._around[position] = found
        return found

    def scopes(self, position: int) -> list:
        """Every function body around *position*, innermost first, as
        ``(opener, the named Function or None)``."""
        chain = []
        opener = self.function_body_around(position)
        while opener is not None:
            chain.append((opener, self.function_at.get(opener)))
            opener = self.function_body_around(opener)
        return chain

    def enclosing_functions(self, position: int) -> list:
        """The named functions whose bodies hold *position*, innermost first."""
        return [fn for _, fn in self.scopes(position) if fn is not None]

    def _top_level_declarations(self) -> frozenset:
        names = set()
        for m in re.finditer(rf"\b(?:let|const|var)\s+({IDENT})", self.code):
            if self.function_body_around(m.start()) is None:
                names.add(m.group(1))
        return frozenset(names)

    def declares(self, opener: int, name: str) -> bool:
        """Whether the function body at *opener* declares *name* itself (a
        parameter, or a ``let``/``const``/``var`` directly in it)."""
        if any(param.binds(name) for param in self.scope_params(opener)):
            return True
        body = self.code[opener:self.match[opener]]
        for m in re.finditer(rf"\b(?:let|const|var)\s+{re.escape(name)}\b", body):
            if self.function_body_around(opener + m.start()) == opener:
                return True
        return False

    def returns_of(self, opener: int) -> list:
        """The expression of every ``return`` in the function body at
        *opener* (not one in a callback nested inside it)."""
        spans = []
        for m in re.finditer(r"\breturn\b", self.code[opener:self.match[opener]]):
            start = opener + m.end()
            if self.function_body_around(start) != opener:
                continue
            a, b = _trim(self.code, start, self.expression_end(start))
            if a < b:
                spans.append((a, b))
        return spans

    def calls_of(self, name: str) -> list:
        """Every call ``name(…)`` in this script with its argument spans —
        never the declaration and never a method ``x.name(…)``."""
        found = []
        for m in re.finditer(rf"(?<![\w$.]){re.escape(name)}\s*\(", self.code):
            if re.search(r"function\s*\*?\s*$", self.code[max(0, m.start() - 12):m.start()]):
                continue
            paren = m.end() - 1
            found.append((paren, split_top_level(self.code, paren + 1, self.match[paren], self.match)))
        return found


# ---------------------------------------------------------------------------
# The evaluator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Body:
    """One object a script can send as a body, as far as it could be read."""
    script: str
    line: int
    #: The ``action`` the body names, or None when it could not be read.
    kinds: frozenset | None
    keys: frozenset
    #: A spread, a computed key or a relay this reader could not follow may
    #: have added keys it did not see.
    open: bool
    #: The callers the body was reached through, outermost first.
    trail: tuple = ()
    #: ``(key, (script, start, end, context))`` for every value the body was
    #: seen to be given — what a nested model's entries are read from.
    values: tuple = field(default=(), compare=False, repr=False)

    def value_of(self, key: str) -> list:
        return [value for name, value in self.values if name == key]

    def where(self) -> str:
        via = f" via {' <- '.join(reversed(self.trail))}" if self.trail else ""
        return f"{self.script}:{self.line}{via}"


@dataclass(frozen=True)
class _Ctx:
    """Where an expression is read: the position its names are looked up
    from, what parameters are bound to (an argument span in a caller, with
    the caller's own context), and which bindings are being read already."""
    position: int
    env: tuple = ()
    depth: int = 0
    trail: tuple = ()
    visiting: frozenset = frozenset()

    def bound(self, name: str):
        for key, value in self.env:
            if key == name:
                return value
        return None

    def at(self, position: int, *, env=None, trail=None, visit=None) -> "_Ctx":
        return _Ctx(
            position,
            self.env if env is None else env,
            self.depth + 1,
            self.trail if trail is None else trail,
            self.visiting | {visit} if visit is not None else self.visiting,
        )


_OPEN = None  # a value that could not be followed
_NOTHING = {"null", "undefined", "false", "true", "0", "[]"}
_MEMBER_RE = re.compile(rf"({IDENT})((?:\??\.{IDENT})+)\Z")
BODIES, STRINGS, ELEMENTS = "bodies", "strings", "elements"


def _combine(kind: str, results: list):
    if any(result is _OPEN for result in results):
        return _OPEN
    if kind == STRINGS:
        return set().union(*results) if results else set()
    return [item for result in results for item in result]


class Reader:
    """Evaluates expressions of a set of scripts to the bodies, strings or
    array entries they can be."""

    MAX_DEPTH = 14

    def __init__(self, scripts: list):
        self.scripts = scripts
        self._functions: dict = {}
        for script in scripts:
            for fn in script.functions:
                self._functions.setdefault(fn.name, []).append((script, fn))

    # --- entry points ------------------------------------------------------

    def bodies_at(self, script: Script, a: int, b: int):
        """The bodies the expression at ``[a, b)`` can be; None when it could
        not be followed."""
        return self._eval(BODIES, script, a, b, _Ctx(a))

    def strings_at(self, script: Script, a: int, b: int):
        return self._eval(STRINGS, script, a, b, _Ctx(a))

    def elements_of(self, value) -> list | None:
        """The object entries of the array a body was given (a value from
        ``Body.value_of``), or None."""
        script, a, b, ctx = value
        return self._eval(ELEMENTS, script, a, b, ctx)

    # --- dispatch ----------------------------------------------------------

    def _eval(self, kind: str, script: Script, a: int, b: int, ctx: _Ctx):
        if ctx.depth > self.MAX_DEPTH:
            return _OPEN
        a, b = _trim(script.code, a, b)
        code = script.code
        text = code[a:b]
        if not text:
            return _OPEN
        if text in _NOTHING:
            return set() if kind == STRINGS else []
        for prefix in ("await ", "new Set(", "Array.from("):
            if text.startswith(prefix) and prefix.endswith("(") and script.match.get(a + len(prefix) - 1) == b - 1:
                return self._eval(kind, script, a + len(prefix), b - 1, ctx)
            if text.startswith(prefix) and not prefix.endswith("("):
                return self._eval(kind, script, a + len(prefix), b, ctx)
        if script.is_group(a, b, "("):
            return self._eval(kind, script, a + 1, b - 1, ctx)
        # The conditional operator binds loosest, so it is split first.
        branches = self._ternary(script, a, b)
        if branches is not None:
            return _combine(kind, [self._eval(kind, script, x, y, ctx) for x, y in branches])
        leaf = self._leaf(kind, script, a, b, ctx)
        if leaf is not NotImplemented:
            return leaf
        call = re.match(rf"({IDENT})\s*\(", text)
        if call and script.match.get(a + call.end() - 1) == b - 1:
            return self._call(kind, script, a + call.end() - 1, call.group(1), ctx)
        if _IDENT_RE.match(text):
            return self._name(kind, script, text, ctx)
        member = _MEMBER_RE.match(text)
        if member:
            props = [p for p in re.split(r"\??\.", member.group(2)) if p]
            return self._member(kind, script, member.group(1), props, ctx)
        indexed = re.match(rf"({IDENT})\s*\[", text)
        if indexed and script.match.get(a + indexed.end() - 1) == b - 1:
            # ``TABLE[key]``: whichever of the table's values the key names.
            holders = self._name(BODIES, script, indexed.group(1), ctx)
            if holders is _OPEN or any(holder.open for holder in holders):
                return _OPEN
            return _combine(kind, [
                self._eval(kind, s, x, y, inner)
                for holder in holders for _key, (s, x, y, inner) in holder.values
            ])
        return _OPEN

    def _leaf(self, kind: str, script: Script, a: int, b: int, ctx: _Ctx):
        code = script.code
        if kind == BODIES:
            if script.is_group(a, b, "{"):
                return self._literal(script, a, ctx)
            return NotImplemented
        if kind == STRINGS:
            value = script.string_at(a, b)
            if value is not None:
                return {value}
            if code[a] == "`":
                return _OPEN
            # ``castAction || "cast"``: the fallback the author wrote names
            # the family; the variable's other values are read where *they*
            # are built (a branch that sends "activate" builds its own body).
            for op in ("||", "??"):
                parts = self._split_operator(script, a, b, op)
                if parts:
                    tail = script.string_at(*parts[-1])
                    if tail is not None:
                        return {tail}
                    return _OPEN
            return NotImplemented
        # ELEMENTS
        if script.is_group(a, b, "["):
            results = []
            for x, y in split_top_level(code, a + 1, b - 1, script.match):
                if code.startswith("...", x):
                    results.append(self._eval(ELEMENTS, script, x + 3, y, ctx.at(x)))
                elif script.is_group(x, y, "{"):
                    results.append(self._literal(script, x, ctx.at(x)))
            return _combine(ELEMENTS, results)
        # ``xs.map(cb)`` — perhaps followed by ``.filter(…)`` or ``.sort(…)``,
        # which choose among the same entries.
        for m in reversed(list(re.finditer(r"\.map\(", code[a:b]))):
            paren = a + m.end() - 1
            if self._at_top(script, a, paren):
                return self._callback_results(script, paren, ctx)
        for m in re.finditer(r"\.(?:filter|sort|slice|reverse)\(", code[a:b]):
            paren = a + m.end() - 1
            if self._at_top(script, a, paren) and script.match[paren] == b - 1:
                return self._eval(ELEMENTS, script, a, a + m.start(), ctx)
        return NotImplemented

    @staticmethod
    def _at_top(script: Script, a: int, position: int) -> bool:
        j = a
        while j < position:
            if script.code[j] in "([{":
                closer = script.match[j]
                if closer > position:
                    return False
                j = closer + 1
                continue
            j += 1
        return True

    def _split_operator(self, script: Script, a: int, b: int, op: str):
        parts = []
        start = a
        j = a
        code = script.code
        while j < b:
            if code[j] in "([{":
                j = script.match[j] + 1
                continue
            if code.startswith(op, j):
                parts.append((start, j))
                start = j + len(op)
                j += len(op)
                continue
            j += 1
        if not parts:
            return None
        parts.append((start, b))
        return parts

    def _ternary(self, script: Script, a: int, b: int):
        """``c ? x : y`` at the expression's own depth -> the two branch spans."""
        code = script.code
        j = a
        question = None
        nested = 0
        while j < b:
            ch = code[j]
            if ch in "([{":
                j = script.match[j] + 1
                continue
            if ch == "?" and code[j + 1:j + 2] not in (".", "?") and code[j - 1:j] != "?":
                if question is None:
                    question = j
                else:
                    nested += 1
            elif ch == ":" and question is not None:
                if nested:
                    nested -= 1
                else:
                    return [(question + 1, j), (j + 1, b)]
            j += 1
        return None

    # --- names -------------------------------------------------------------

    def _name(self, kind: str, script: Script, name: str, ctx: _Ctx):
        """What *name* can hold: its bound argument, else its bindings in the
        innermost function body that has any, else — for a parameter of a
        named function — what every caller passes, else, for a variable
        declared at the top of the file, every assignment to it."""
        bound = ctx.bound(name)
        if bound is not None:
            s, x, y, outer = bound
            result = self._eval(kind, s, x, y, outer)
            return self._with_writes(kind, script, name, ctx, result)
        for opener, fn in script.scopes(ctx.position):
            bindings = self._bindings(script, name, opener, ctx.position)
            if bindings:
                result = self._read_bindings(kind, script, bindings, ctx)
                return self._with_writes(kind, script, name, ctx, result)
            if any(param.binds(name) for param in script.scope_params(opener)):
                if fn is None:
                    return _OPEN  # a callback's parameter: its caller is the platform
                result = self._relay(kind, script, fn, name, ctx)
                return self._with_writes(kind, script, name, ctx, result)
        if name in script.globals:
            bindings = [
                binding for binding in self._bindings(script, name, 0, len(script.code))
                if not any(script.declares(opener, name) for opener, _ in script.scopes(binding[0]))
            ]
            result = self._read_bindings(kind, script, bindings, ctx)
            return self._with_writes(kind, script, name, ctx, result, everywhere=True)
        return _OPEN

    def _read_bindings(self, kind: str, script: Script, bindings: list, ctx: _Ctx):
        results = []
        for at, x, y in bindings:
            key = (script.name, at)
            if key in ctx.visiting:
                continue  # a binding reading itself adds nothing new
            results.append(self._eval(kind, script, x, y, ctx.at(at, visit=key)))
        return _combine(kind, results)

    def _bindings(self, script: Script, name: str, lo: int, hi: int) -> list:
        """``(where the name is, value start, value end)`` of every
        ``name = …`` in ``[lo, hi)``."""
        spans = []
        pattern = rf"(?<![\w$.]){re.escape(name)}\s*=(?![=>])"
        for m in re.finditer(pattern, script.code[lo:hi]):
            start = lo + m.end()
            spans.append((lo + m.start(), start, script.expression_end(start)))
        return spans

    def _env_for(self, fn: Function, s: Script, args: list, caller: _Ctx) -> tuple:
        """*fn*'s parameters bound to the arguments of one call of it (in
        script *s*), an omitted one to its default."""
        home = next(script for script in self.scripts if fn in script.functions)
        env = []
        for position, param in enumerate(fn.params):
            if position >= len(args):
                if param.name is not None and param.default is not None:
                    at = _Ctx(param.default[0], (), caller.depth, caller.trail, caller.visiting)
                    env.append((param.name, (home, *param.default, at)))
                continue
            x, y = args[position]
            if param.name is not None:
                env.append((param.name, (s, x, y, caller)))
            elif s.is_group(x, y, "{"):
                props = self._properties(s, x)
                for local, prop in param.destructured:
                    if prop in props:
                        env.append((local, (s, *props[prop], caller)))
        return tuple(env)

    def _relay(self, kind: str, script: Script, fn: Function, name: str, ctx: _Ctx):
        """*name* is *fn*'s parameter: what each caller passes for it, read
        with all of *fn*'s parameters bound to that caller's arguments (an
        omitted one to its default)."""
        key = (script.name, fn.body_open, name)
        if key in ctx.visiting:
            return [] if kind != STRINGS else set()
        calls = [(s, paren, args) for s in self.scripts for paren, args in s.calls_of(fn.name)]
        if not calls:
            return _OPEN
        results = []
        for s, paren, args in calls:
            caller = _Ctx(paren, (), ctx.depth + 1, ctx.trail, ctx.visiting | {key})
            env = self._env_for(fn, s, args, caller)
            trail = ctx.trail + (f"{s.name}:{s.line(paren)}",)
            here = _Ctx(ctx.position, env, ctx.depth + 1, trail, ctx.visiting | {key})
            if here.bound(name) is not None:
                results.append(self._name(kind, script, name, here))
            # else: not passed and no default — undefined is no value
        return _combine(kind, results)

    def _with_writes(self, kind: str, script: Script, name: str, ctx: _Ctx, result, everywhere=False):
        """For bodies, every key written onto *name* by the function reading
        it (the whole file, for a top-level variable); for entries, every
        ``name.push(…)``."""
        if result is _OPEN or kind == STRINGS:
            return result
        scopes = script.scopes(ctx.position)
        if everywhere or not scopes:
            lo, hi = 0, len(script.code)
        else:
            named = [opener for opener, fn in scopes if fn is not None]
            opener = named[0] if named else scopes[0][0]
            lo, hi = opener, script.match[opener]
        code = script.code[lo:hi]
        if kind == ELEMENTS:
            found = list(result)
            for m in re.finditer(rf"(?<![\w$.]){re.escape(name)}\.push\(", code):
                paren = lo + m.end() - 1
                for x, y in split_top_level(script.code, paren + 1, script.match[paren], script.match):
                    got = self._eval(BODIES, script, x, y, ctx.at(paren))
                    if got is _OPEN:
                        return _OPEN
                    found.extend(got)
            return found
        keys = set()
        values = []
        is_open = False
        for m in re.finditer(rf"(?<![\w$.]){re.escape(name)}\.({IDENT})\s*=(?![=>])", code):
            keys.add(m.group(1))
            start = lo + m.end()
            values.append((m.group(1), (script, start, script.expression_end(start),
                                        ctx.at(lo + m.start()))))
        for m in re.finditer(rf"(?<![\w$.]){re.escape(name)}\[", code):
            opener = lo + m.end() - 1
            closer = script.match[opener]
            after = script.next_significant(closer + 1)
            if script.code[after:after + 1] != "=" or script.code[after + 1:after + 2] in ("=", ">"):
                continue
            got = self._eval(STRINGS, script, opener + 1, closer, ctx.at(opener))
            if got is _OPEN:
                is_open = True
            else:
                keys |= got
        for m in re.finditer(rf"\bObject\.assign\(\s*{re.escape(name)}\s*,", code):
            paren = lo + m.start() + len("Object.assign")
            for x, y in split_top_level(script.code, paren + 1, script.match[paren], script.match)[1:]:
                got = self._eval(BODIES, script, x, y, ctx.at(x))
                if got is _OPEN:
                    is_open = True
                    continue
                for body in got:
                    keys |= body.keys
                    values.extend(body.values)
                    is_open = is_open or body.open
        if not keys and not is_open:
            return result
        return [
            Body(b.script, b.line, b.kinds, b.keys | keys, b.open or is_open, b.trail,
                 b.values + tuple(values))
            for b in result
        ]

    def _member(self, kind: str, script: Script, base: str, props: list, ctx: _Ctx):
        """``base.a.b`` — the value each object *base* can be gives ``a``."""
        holders = self._name(BODIES, script, base, ctx)
        for depth, prop in enumerate(props):
            if holders is _OPEN:
                return _OPEN
            last = depth == len(props) - 1
            results = []
            for holder in holders:
                given = holder.value_of(prop)
                if not given:
                    if holder.open:
                        return _OPEN
                    continue
                for s, x, y, inner in given:
                    results.append(self._eval(kind if last else BODIES, s, x, y, inner))
            holders = _combine(kind if last else BODIES, results)
        return holders

    # --- literals and calls -----------------------------------------------

    def _key_of(self, script: Script, a: int, b: int):
        """``(key, value span)`` of one property, or None for a spread, a
        computed key or a method."""
        text = script.code[a:b]
        m = _KEY_RE.match(text)
        if m:
            return m.group(1), (a + m.end(), b)
        m = _QUOTED_KEY_RE.match(text)
        if m:
            return script.source[a + 1:a + 1 + len(m.group(2))], (a + m.end(), b)
        if _IDENT_RE.match(text):
            return text, (a, b)
        return None

    def _properties(self, script: Script, opener: int) -> dict:
        props = {}
        for a, b in split_top_level(script.code, opener + 1, script.match[opener], script.match):
            found = self._key_of(script, a, b)
            if found is not None:
                props[found[0]] = found[1]
        return props

    def _literal(self, script: Script, opener: int, ctx: _Ctx) -> list:
        """An object literal as a body — once per caller of its function when
        its ``action``, a computed key or a spread reads that function's
        parameters (so ``{ seat, action, [field]: … }`` keeps each caller's
        ``action`` with that caller's ``field``)."""
        fork = self._forks(script, opener, ctx)
        if fork is not None:
            return fork
        code = script.code
        keys = set()
        values = []
        is_open = False
        action = None
        spread = []
        for a, b in split_top_level(code, opener + 1, script.match[opener], script.match):
            text = code[a:b]
            if text.startswith("..."):
                got = self._eval(BODIES, script, a + 3, b, ctx.at(a))
                if got is _OPEN:
                    is_open = True
                elif got:
                    spread.append(got)
                continue
            if text.startswith("["):
                got = self._eval(STRINGS, script, a + 1, script.match[a], ctx.at(a))
                if got is _OPEN:
                    is_open = True
                else:
                    keys |= got
                continue
            found = self._key_of(script, a, b)
            if found is None:
                continue  # a method is no field of a body
            key, value = found
            keys.add(key)
            values.append((key, (script, *value, ctx.at(value[0]))))
            if key == "action":
                action = value
        kinds = None
        if action is not None:
            got = self._eval(STRINGS, script, *action, ctx.at(action[0]))
            kinds = frozenset(got) if got is not _OPEN else None
        line = script.line(opener)
        if len(spread) == 1:
            # One spread of several candidates (``{ seat, ...pending.actionBody,
            # auto_tap: true }``): one body per candidate, each with what it
            # brings — a union would let one candidate's field cover another's.
            return [
                Body(script.name, line,
                     kinds if action is not None else body.kinds,
                     frozenset(keys) | body.keys, is_open or body.open,
                     ctx.trail, tuple(values) + body.values)
                for body in spread[0]
            ]
        flat = [body for group in spread for body in group]
        if action is None and flat and all(body.kinds is not None for body in flat):
            kinds = frozenset().union(*(body.kinds for body in flat))
        for body in flat:
            keys |= body.keys
            values.extend(body.values)
            is_open = is_open or body.open
        return [Body(script.name, line, kinds, frozenset(keys), is_open, ctx.trail, tuple(values))]

    def _forks(self, script: Script, opener: int, ctx: _Ctx):
        scopes = script.scopes(opener)
        fn = next((fn for _, fn in scopes if fn is not None), None)
        if fn is None:
            return None
        names = {param.name for param in fn.params if param.name}
        names |= {local for param in fn.params for local, _ in param.destructured}
        names = {n for n in names if ctx.bound(n) is None}
        if not names:
            return None
        code = script.code
        read = []
        for a, b in split_top_level(code, opener + 1, script.match[opener], script.match):
            text = code[a:b]
            if text.startswith("...") or text.startswith("["):
                read.append(text)
                continue
            found = self._key_of(script, a, b)
            if found and found[0] == "action":
                read.append(code[slice(*found[1])])
        words = set(re.findall(IDENT, " ".join(read)))
        if not words & names:
            return None
        key = (script.name, fn.body_open, "fork")
        if key in ctx.visiting:
            return None
        calls = [(s, paren, args) for s in self.scripts for paren, args in s.calls_of(fn.name)]
        if not calls:
            return None
        bodies = []
        for s, paren, args in calls:
            caller = _Ctx(paren, (), ctx.depth + 1, ctx.trail, ctx.visiting | {key})
            env = self._env_for(fn, s, args, caller)
            here = _Ctx(ctx.position, ctx.env + env, ctx.depth + 1,
                        ctx.trail + (f"{s.name}:{s.line(paren)}",), ctx.visiting | {key})
            bodies.extend(self._literal(script, opener, here))
        return bodies

    def _call(self, kind: str, script: Script, paren: int, name: str, ctx: _Ctx):
        """``name(args)`` where *name* is one function of these scripts: what
        its ``return`` can be, its parameters bound to these arguments."""
        targets = self._functions.get(name, [])
        if len(targets) != 1:
            return _OPEN
        s, fn = targets[0]
        key = (s.name, fn.body_open, "call")
        if key in ctx.visiting:
            return [] if kind != STRINGS else set()
        args = split_top_level(script.code, paren + 1, script.match[paren], script.match)
        caller = _Ctx(paren, ctx.env, ctx.depth + 1, ctx.trail, ctx.visiting)
        env = self._env_for(fn, script, args, caller)
        returns = s.returns_of(fn.body_open)
        if not returns:
            return _OPEN
        return _combine(kind, [
            self._eval(kind, s, x, y, _Ctx(x, env, ctx.depth + 1, ctx.trail, ctx.visiting | {key}))
            for x, y in returns
        ])

    def _callback_results(self, script: Script, paren: int, ctx: _Ctx):
        """What the arrow passed to the call at *paren* returns — its
        expression body, or every ``return`` of its block — as entries."""
        args = split_top_level(script.code, paren + 1, script.match[paren], script.match)
        if not args:
            return _OPEN
        x, y = args[0]
        arrow = script.code.find("=>", x, y)
        if arrow < 0:
            return _OPEN
        start = script.next_significant(arrow + 2)
        if script.code[start] == "{" and script.match[start] == y - 1:
            spans = script.returns_of(start)
        else:
            spans = [(start, y)]
        return _combine(BODIES, [self._eval(BODIES, script, a, b, ctx.at(a)) for a, b in spans])


# ---------------------------------------------------------------------------
# Where requests leave
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Funnel:
    """A function every call of which sends one request: its URL is one of
    its parameters (``url_param``) or fixed (``url``), its body is one of its
    parameters, and its method is fixed or one of its parameters."""
    script: str
    name: str
    body_param: int
    url_param: int | None = None
    url: str | None = None
    method: str | None = None
    method_param: int | None = None


@dataclass(frozen=True)
class Site:
    """One call of a funnel: a request that leaves the page."""
    script: Script
    position: int
    funnel: Funnel
    #: The URL template (``${…}`` written ``{}``), or None when not literal.
    url: str | None
    method: str | None
    body: tuple  # the body expression's span

    @property
    def line(self) -> int:
        return self.script.line(self.position)


def _fetch_calls(script: Script, reader: "Reader"):
    """Every ``fetch(url, options)``: ``(paren, url span, options
    properties or None)``."""
    found = []
    for paren, args in script.calls_of("fetch"):
        options = None
        if len(args) > 1 and script.is_group(*args[1], "{"):
            options = reader._properties(script, args[1][0])
        found.append((paren, args[0], options))
    return found


def find_funnels(scripts: list) -> list:
    """The functions requests are sent through, found from the code.

    A first-order funnel's ``fetch`` posts a parameter as its body
    (``body: JSON.stringify(param)``) to a parameter URL; a second-order one
    hands a parameter — itself, or spread into a literal it builds — to a
    first-order funnel at a fixed URL (``sendAction``)."""
    reader = Reader(scripts)
    funnels = []
    for script in scripts:
        for paren, url_span, options in _fetch_calls(script, reader):
            if not options or "body" not in options:
                continue
            chain = script.enclosing_functions(paren)
            if not chain:
                continue
            fn = chain[0]
            body_text = script.code[slice(*options["body"])].strip()
            m = re.fullmatch(rf"JSON\.stringify\(\s*({IDENT})\s*\)", body_text)
            url_text = script.code[slice(*url_span)].strip()
            if not m or fn.param_index(m.group(1)) is None or fn.param_index(url_text) is None:
                continue
            method = method_param = None
            if "method" in options:
                method = script.string_at(*options["method"])
                if method is None:
                    method_param = fn.param_index(script.code[slice(*options["method"])].strip())
            funnels.append(Funnel(
                script.name, fn.name, fn.param_index(m.group(1)),
                url_param=fn.param_index(url_text), method=method, method_param=method_param,
            ))
    for funnel in list(funnels):
        for script in scripts:
            for paren, args in script.calls_of(funnel.name):
                chain = script.enclosing_functions(paren)
                if not chain or len(args) <= max(funnel.body_param, funnel.url_param):
                    continue
                fn = chain[0]
                url = script.template_at(*args[funnel.url_param])
                if url is None:
                    continue
                body_text = script.code[slice(*args[funnel.body_param])].strip()
                handed = _handed_param(script, reader, fn, body_text, paren)
                if handed is not None:
                    funnels.append(Funnel(script.name, fn.name, handed, url=url, method=funnel.method))
    return funnels


def _handed_param(script: Script, reader: Reader, fn: Function, body_text: str, before: int):
    """Which of *fn*'s parameters *body_text* hands on: the parameter itself,
    or a local bound to a literal spreading it."""
    if fn.param_index(body_text) is not None:
        return fn.param_index(body_text)
    if not _IDENT_RE.match(body_text):
        return None
    for _at, x, y in reader._bindings(script, body_text, fn.body_open, before):
        x, y = _trim(script.code, x, y)
        if not script.is_group(x, y, "{"):
            continue
        for a, b in split_top_level(script.code, x + 1, y - 1, script.match):
            text = script.code[a:b]
            if text.startswith("...") and fn.param_index(text[3:].strip()) is not None:
                return fn.param_index(text[3:].strip())
    return None


def request_sites(scripts: list, funnels: list | None = None) -> list:
    """Every call of a funnel outside the funnels themselves."""
    funnels = find_funnels(scripts) if funnels is None else funnels
    names = {f.name for f in funnels}
    sites = []
    for funnel in funnels:
        for script in scripts:
            for paren, args in script.calls_of(funnel.name):
                chain = script.enclosing_functions(paren)
                if chain and chain[0].name in names:
                    continue  # the funnel's own forwarding call
                url = funnel.url
                if funnel.url_param is not None and funnel.url_param < len(args):
                    url = script.template_at(*args[funnel.url_param])
                method = funnel.method
                if funnel.method_param is not None and funnel.method_param < len(args):
                    method = script.string_at(*args[funnel.method_param])
                body = args[funnel.body_param] if funnel.body_param < len(args) else (paren, paren)
                sites.append(Site(script, paren, funnel, url, method, body))
    return sites


@dataclass(frozen=True)
class Query:
    """One body-less ``fetch``: the URL template(s) it can request, its
    method, and the query parameter names it was seen to set (in the URL's
    own text, or on a ``URLSearchParams`` it interpolates)."""
    script: Script
    position: int
    method: str
    urls: tuple
    names: frozenset

    @property
    def line(self) -> int:
        return self.script.line(self.position)


def query_requests(scripts: list) -> list:
    """Every ``fetch`` that sends no body, with what it asks for."""
    reader = Reader(scripts)
    found = []
    for script in scripts:
        for paren, url_span, options in _fetch_calls(script, reader):
            if options and "body" in options:
                continue
            method = "GET"
            if options and "method" in options:
                method = script.string_at(*options["method"]) or "GET"
            urls = _url_templates(script, reader, *url_span, paren)
            names = set()
            for url, spans in urls:
                names |= set(re.findall(rf"(?:\?|&)({IDENT})=", url))
                for x, y in spans:
                    names |= _search_params_names(script, reader, x, y, paren)
            found.append(Query(script, paren, method, tuple(sorted({u for u, _ in urls})), frozenset(names)))
    return found


def _url_templates(script: Script, reader: Reader, a: int, b: int, before: int) -> list:
    """``(template, interpolation spans after its "?")`` of every URL the
    expression can be."""
    a, b = _trim(script.code, a, b)
    template = script.template_at(a, b)
    if template is not None:
        query_at = script.source.find("?", a, b)
        spans = [s for s in script.interpolations(a, b) if 0 <= query_at < s[0]]
        return [(template, spans)]
    branches = reader._ternary(script, a, b)
    if branches is not None:
        return [t for x, y in branches for t in _url_templates(script, reader, x, y, before)]
    text = script.code[a:b]
    if _IDENT_RE.match(text):
        for opener, _fn in script.scopes(before):
            bindings = reader._bindings(script, text, opener, before)
            if bindings:
                return [t for _at, x, y in bindings for t in _url_templates(script, reader, x, y, before)]
    return []


def _search_params_names(script: Script, reader: Reader, a: int, b: int, before: int) -> set:
    """The names a ``URLSearchParams`` named at ``[a, b)`` is built with or
    ``.set``/``.append``-ed."""
    text = script.code[a:b].strip()
    if not _IDENT_RE.match(text):
        return set()
    scopes = script.scopes(before)
    lo, hi = (scopes[0][0], script.match[scopes[0][0]]) if scopes else (0, len(script.code))
    names = set()
    for _at, x, y in reader._bindings(script, text, lo, before):
        x, y = _trim(script.code, x, y)
        m = re.match(r"new\s+URLSearchParams\(", script.code[x:y])
        if m:
            paren = x + m.end() - 1
            args = split_top_level(script.code, paren + 1, script.match[paren], script.match)
            if args and script.is_group(*args[0], "{"):
                names |= set(reader._properties(script, args[0][0]))
    for m in re.finditer(rf"(?<![\w$.]){re.escape(text)}\.(?:set|append)\(", script.code[lo:hi]):
        paren = lo + m.end() - 1
        args = split_top_level(script.code, paren + 1, script.match[paren], script.match)
        if args:
            value = script.string_at(*args[0])
            if value is not None:
                names.add(value)
    return names


def load_scripts(static_dir: Path) -> list:
    """Every first-party script the page loads (a vendored, minified library
    is not one)."""
    return [
        Script(path) for path in sorted(static_dir.glob("*.js"))
        if not path.name.endswith(".min.js")
    ]
