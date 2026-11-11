"""Every request the browser builds supplies what its route requires.

``tests/ui/test_special_action_wire.py`` was written the day every CR 116
special action turned out to have been a silent 422 for four sets: the button
built ``{action, permanent_id, special_action_kind}`` and the server required
``seat``. It holds that one field over the ``sendAction({…})`` literals. Every
other required field of every model in ``web/schemas.py`` — and every field a
handler refuses an action without — was supplied by hand at each call site and
checked by nobody.

This holds the two halves together, and neither half is a hand list:

* **What the server requires** is derived. A route's body model and its
  required query parameters come from FastAPI's own route table; a model's
  required fields — and its nested models' — from pydantic's field metadata;
  and what each ``ActionKind``'s handler refuses without from the handler's own
  source (``if req.card_name is None: raise HTTPException(…)``, read by
  :func:`handler_requirements`), with the fills ``_resolve_permanent_ids`` makes
  (a ``permanent_id`` supplies a ``permanent_index``) read the same way.
* **What the client sends** is read out of ``web/static/*.js`` by
  ``tests/ui/js_requests.py``: the functions requests leave through are found
  from their ``fetch``, and every call of one is followed to the object
  literals it can send — through bindings, callers, ``return``s, spreads and
  ``body.key =`` writes.

A body the reader could not follow completely is *open*; it is checked for
what it was seen to carry, and a field it lacks is not reported against it.
The floors below say how much was read, so a reader that stops reading cannot
pass by finding nothing. ``test_the_guard_names_bodies_broken_on_purpose``
breaks bodies in a copy of the script and asserts each is named — the
backwards half, run every time.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
import typing
from functools import lru_cache
from pathlib import Path

from fastapi.routing import APIRoute
from pydantic import BaseModel

from web import actions as web_actions
from web.action_registry import ACTION_HANDLERS
from web.app import app
from web.schemas import ActionKind, GameActionRequest

from .js_requests import Reader, Script, load_scripts, query_requests, request_sites

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"
ACTION_KINDS = frozenset(typing.get_args(ActionKind))


# ---------------------------------------------------------------------------
# What the server requires
# ---------------------------------------------------------------------------


def required_fields(model: type[BaseModel]) -> frozenset:
    """The fields pydantic refuses a body of *model* without."""
    return frozenset(name for name, f in model.model_fields.items() if f.is_required())


def nested_models(model: type[BaseModel]) -> dict:
    """``field -> model`` for every field of *model* whose value is another
    model or a list of them (``divided_targets: list[DividedTargetRef] | None``)."""
    found = {}
    for name, f in model.model_fields.items():
        stack = [f.annotation]
        while stack:
            tp = stack.pop()
            if isinstance(tp, type) and issubclass(tp, BaseModel):
                found[name] = tp
                break
            stack.extend(typing.get_args(tp))
    return found


@lru_cache(maxsize=1)
def api_routes() -> tuple:
    """``(methods, path regex, body model or None, required query names)``
    for every API route, from FastAPI's own table."""
    routes = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        dependant = route.dependant
        body = None
        if dependant.body_params:
            annotation = dependant.body_params[0].field_info.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                body = annotation
        query = frozenset(
            p.name for p in dependant.query_params if p.field_info.is_required()
        )
        pattern = re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", route.path) + "$")
        routes.append((frozenset(route.methods), pattern, body, query, route.path))
    return tuple(routes)


def route_for(url: str | None, method: str | None):
    """The route a client URL template (``${…}`` written ``{}``) reaches."""
    if not url:
        return None
    path = url.partition("?")[0].replace("{}", "X")
    for methods, pattern, body, query, declared in api_routes():
        if pattern.match(path) and (method or "GET") in methods:
            return methods, pattern, body, query, declared
    return None


def _dnf(node, req: str, aliases: dict, leaf: str):
    """A test over the request's fields as OR-of-AND sets of field names,
    or None when it reads anything else. *leaf* is "missing" (``req.f is
    None``, ``not req.f``) or "present" (``req.f``, ``req.f is not None``)."""
    def field_of(expr):
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) and expr.value.id == req:
            return expr.attr
        if isinstance(expr, ast.Name) and expr.id in aliases:
            return aliases[expr.id]
        return None

    if isinstance(node, ast.BoolOp):
        parts = [_dnf(value, req, aliases, leaf) for value in node.values]
        if isinstance(node.op, ast.Or):
            # Each disjunct alone makes the whole test true, so one that reads
            # only the request is a requirement (an escape) by itself, whatever
            # the others read: ``index is None or not 0 <= index < len(pile)``
            # refuses every request without an index.
            pure = [part for part in parts if part is not None]
            return [term for part in pure for term in part] if pure else None
        if any(part is None for part in parts):
            return None
        terms = [frozenset()]
        for part in parts:
            terms = [t | p for t in terms for p in part]
        return terms
    if leaf == "missing":
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and field_of(node.operand):
            return [frozenset({field_of(node.operand)})]
        if (
            isinstance(node, ast.Compare) and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Is) and field_of(node.left)
            and isinstance(node.comparators[0], ast.Constant) and node.comparators[0].value is None
        ):
            return [frozenset({field_of(node.left)})]
        return None
    if field_of(node):
        return [frozenset({field_of(node)})]
    if (
        isinstance(node, ast.Compare) and len(node.ops) == 1
        and isinstance(node.ops[0], ast.IsNot) and field_of(node.left)
        and isinstance(node.comparators[0], ast.Constant) and node.comparators[0].value is None
    ):
        return [frozenset({field_of(node.left)})]
    return None


def _returns(node) -> bool:
    """Whether *node* can return from the function it is in (a ``return``
    not inside a nested function)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return False
    if isinstance(node, ast.Return):
        return True
    return any(_returns(child) for child in ast.iter_child_nodes(node))


def _is_refusal(body) -> bool:
    return (
        len(body) == 1 and isinstance(body[0], ast.Raise)
        and isinstance(body[0].exc, ast.Call)
        and getattr(body[0].exc.func, "id", None) == "HTTPException"
    )


def _function_ast(func):
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    return next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))


def requirements_of(func) -> list:
    """What *func* (a handler) refuses a request without, from its source:
    one set per refusal, any one field of which satisfies it.

    Read off the handler's top-level statements in order. ``if <the
    request's fields are missing>: raise HTTPException(…)`` is a
    requirement; ``if <fields are present>: …; return`` makes those fields an
    alternative to every later requirement (``search_picks`` instead of
    ``hand_index``); any other statement that can return ends the reading,
    because what follows it is conditional on something this does not model.
    A refusal whose test reads anything but the request — "in a 3+ player
    game", "while this prompt asks for a land type" — is conditional too, and
    is not a requirement here."""
    fn = _function_ast(func)
    req = fn.args.args[1].arg
    aliases: dict = {}
    escapes: frozenset = frozenset()
    found = []
    for stmt in fn.body:
        if (
            isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Attribute)
            and isinstance(stmt.value.value, ast.Name) and stmt.value.value.id == req
        ):
            aliases[stmt.targets[0].id] = stmt.value.attr
            continue
        if isinstance(stmt, ast.If) and not stmt.orelse and _is_refusal(stmt.body):
            terms = _dnf(stmt.test, req, aliases, "missing")
            if terms is not None:
                found.extend(term | escapes for term in terms)
            continue
        if _returns(stmt):
            if isinstance(stmt, ast.If) and not stmt.orelse and isinstance(stmt.body[-1], ast.Return):
                terms = _dnf(stmt.test, req, aliases, "present")
                if terms is not None:
                    escapes = escapes.union(*terms)
                    continue
            break
    return found


@lru_cache(maxsize=1)
def handler_requirements() -> dict:
    """``ActionKind -> [alternative sets]``, from every registered handler."""
    return {kind: requirements_of(spec.handler) for kind, spec in ACTION_HANDLERS.items()}


@lru_cache(maxsize=1)
def id_fills() -> dict:
    """``field -> fields it fills``: what ``_resolve_permanent_ids`` writes
    onto the request when the client sent a stable id (``permanent_id``
    fills ``permanent_index``, ``permanent_name`` and ``target_seat``)."""
    fn = _function_ast(web_actions._resolve_permanent_ids)
    req = fn.args.args[1].arg
    fills: dict = {}
    for stmt in fn.body:
        if not isinstance(stmt, ast.If):
            continue
        terms = _dnf(stmt.test, req, {}, "present")
        if not terms or len(terms) != 1 or len(terms[0]) != 1:
            continue
        (source,) = terms[0]
        for node in ast.walk(stmt):
            if (
                isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Subscript)
                and isinstance(node.targets[0].value, ast.Name)
                and node.targets[0].value.id == "update"
                and isinstance(node.targets[0].slice, ast.Constant)
            ):
                fills.setdefault(source, set()).add(node.targets[0].slice.value)
    return {key: frozenset(value) for key, value in fills.items()}


def supplies(keys: frozenset, alternatives: frozenset) -> bool:
    fills = id_fills()
    return any(
        field in keys or any(field in fills.get(key, ()) for key in keys)
        for field in alternatives
    )


# ---------------------------------------------------------------------------
# What the client sends
# ---------------------------------------------------------------------------


class Census:
    """Every request the scripts make, read once."""

    def __init__(self, scripts: list):
        self.scripts = scripts
        self.reader = Reader(scripts)
        self.sites = request_sites(scripts)
        self.queries = query_requests(scripts)
        self.read = []        # (site, body)
        self.unread = []      # sites whose body could not be followed
        for site in self.sites:
            bodies = self.reader.bodies_at(site.script, *site.body)
            if bodies is None:
                self.unread.append(site)
                continue
            self.read.extend((site, body) for body in bodies)

    def problems(self) -> dict:
        """Every disagreement between a body and its route, by check."""
        found = {"route": [], "required": [], "kind": [], "handler": [], "nested": [], "query": []}
        for site in self.sites:
            if route_for(site.url, site.method) is None:
                found["route"].append(f"{site.script.name}:{site.line} {site.method} {site.url}")
        for site, body in self.read:
            route = route_for(site.url, site.method)
            if route is None or route[2] is None:
                continue
            model = route[2]
            missing = sorted(required_fields(model) - body.keys)
            if missing and not body.open:
                found["required"].append(f"{body.where()} -> {route[4]}: no {missing}")
            if model is GameActionRequest and body.kinds is not None:
                for kind in sorted(body.kinds):
                    if kind not in ACTION_KINDS:
                        found["kind"].append(f"{body.where()}: {kind!r} is not an ActionKind")
                        continue
                    if body.open:
                        continue
                    for alternatives in handler_requirements().get(kind, ()):
                        if not supplies(body.keys, alternatives):
                            found["handler"].append(
                                f"{body.where()}: {kind} is refused without "
                                f"{' or '.join(sorted(alternatives))}"
                            )
            for name, sub in nested_models(model).items():
                for value in body.value_of(name):
                    entries = self.reader.elements_of(value)
                    if entries is None:
                        entries = self.reader._eval("bodies", *value)
                    for entry in entries or ():
                        lacking = sorted(required_fields(sub) - entry.keys)
                        if lacking and not entry.open:
                            found["nested"].append(
                                f"{body.where()}: a {name} entry built at "
                                f"{entry.script}:{entry.line} has no {lacking}"
                            )
        for query in self.queries:
            for url in query.urls:
                route = route_for(url, query.method)
                if route is None:
                    if url.startswith("/api/"):
                        found["route"].append(f"{query.script.name}:{query.line} {query.method} {url}")
                    continue
                lacking = sorted(route[3] - query.names)
                if lacking:
                    found["query"].append(f"{query.script.name}:{query.line} {url}: no {lacking}")
        return found


@lru_cache(maxsize=1)
def census() -> Census:
    return Census(load_scripts(STATIC))


# ---------------------------------------------------------------------------
# The derivation, measured
# ---------------------------------------------------------------------------


def test_the_server_side_is_derived_and_reads_what_it_should():
    """The requirements come from the code, and enough of them: a parse that
    stopped recognising the refusal shape would find nothing to hold."""
    requirements = handler_requirements()
    clauses = [c for found in requirements.values() for c in found]
    assert len(clauses) >= 70, f"only {len(clauses)} handler refusals were read"
    assert len([k for k, found in requirements.items() if found]) >= 60
    # Every field a refusal names is a field of the request: a derivation that
    # misread an attribute would hold the client to a field nobody can send.
    fields = set(GameActionRequest.model_fields)
    assert {f for c in clauses for f in c} <= fields
    # The shapes it has to read: a single field, an either-or, an early
    # return that makes a second field an alternative, and an alias.
    assert frozenset({"card_name"}) in requirements["cast"]
    assert frozenset({"card_name", "hand_index"}) in requirements["activate_hand"]
    assert frozenset({"hand_index", "search_picks"}) in requirements["search_library_confirm"]
    assert frozenset({"permanent_name", "permanent_index"}) in requirements["activate"]
    # …a refusal one of whose disjuncts reads only the request, and an early
    # return on one address making it the other's alternative.
    assert frozenset({"graveyard_index"}) in requirements["activate_graveyard"]
    assert frozenset({"hand_index", "permanent_id", "permanent_index"}) in requirements["special_action"]
    # …and the id fills the dispatcher makes before any handler runs.
    assert {"permanent_index", "permanent_name"} <= id_fills()["permanent_id"]
    # A target's id fills its seat and nothing else: the engine is handed the
    # id itself, never the slot it stands in (kg5 ids, `engine/target_keywords`).
    assert id_fills()["target_permanent_id"] == {"target_seat"}
    # The schema half: the action route takes the request model, and the
    # models it nests are found by their annotations.
    assert route_for("/api/sessions/{}/action", "POST")[2] is GameActionRequest
    assert required_fields(GameActionRequest) == {"seat", "action"}
    assert {"divided_targets", "mode_choices", "search_picks", "entry_exile_picks",
            "target_role_refs"} <= set(nested_models(GameActionRequest))


def test_the_reader_reads_every_request_the_scripts_make():
    """How much the client half examined. Every site is followed to a body,
    the funnels are the three the page has, and nearly every action body's
    kind is read — a reader that silently stopped would fail here, not pass
    the checks below by checking nothing."""
    c = census()
    funnels = {site.funnel.name for site in c.sites}
    assert funnels == {"sendAction", "postJson"}, funnels
    assert len(c.sites) >= 180, f"only {len(c.sites)} request sites were found"
    assert c.unread == [], (
        "request bodies the reader could not follow — build each as an object "
        "literal (or extend tests/ui/js_requests.py): "
        + str([f"{s.script.name}:{s.line}" for s in c.unread])
    )
    action_bodies = [b for s, b in c.read if s.url == "/api/sessions/{}/action"]
    assert len(action_bodies) >= 300
    closed = [b for b in action_bodies if not b.open]
    assert len(closed) >= 280
    with_kind = [b for b in closed if b.kinds is not None]
    assert len(with_kind) / len(closed) >= 0.95, (
        f"the kind of only {len(with_kind)} of {len(closed)} action bodies was read"
    )
    checked_kinds = {k for b in with_kind for k in b.kinds if handler_requirements().get(k)}
    assert len(checked_kinds) >= 50, sorted(checked_kinds)
    other_routes = {route_for(s.url, s.method)[4] for s, _ in c.read if s.url != "/api/sessions/{}/action"}
    assert len(other_routes) >= 9, sorted(other_routes)
    assert sum(1 for q in c.queries if route_for(next(iter(q.urls), None), q.method)) >= 8


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def test_every_request_reaches_a_route_the_server_declares():
    assert census().problems()["route"] == []


def test_every_body_carries_its_models_required_fields():
    """pydantic's required fields, per route: ``seat`` on every action (the
    CR 116 omission), ``mode`` on a session, ``card_name`` and ``status`` on
    a verification."""
    assert census().problems()["required"] == []


def test_every_kind_the_client_names_is_an_action_kind():
    """A misspelled kind is a 422 too — ``ActionKind`` is a Literal."""
    assert census().problems()["kind"] == []


def test_every_action_body_supplies_what_its_handler_refuses_without():
    """The per-kind half pydantic cannot say: ``cast`` without ``card_name``,
    ``activate_hand`` without ``card_name`` or ``hand_index``,
    ``player_choice_confirm`` without ``chosen_seat`` — each read off the
    handler that refuses it."""
    assert census().problems()["handler"] == []


def test_every_nested_entry_carries_its_models_required_fields():
    """``divided_targets`` entries need a ``seat`` even beside an ``id``,
    ``search_picks`` a ``zone`` and an ``index``, ``mode_choices`` an
    ``index``."""
    assert census().problems()["nested"] == []


def test_every_query_supplies_the_routes_required_parameters():
    """``card_target_spec`` refuses a request without ``card_name`` and
    ``seat``."""
    assert census().problems()["query"] == []


# ---------------------------------------------------------------------------
# Backwards: the guard names a body broken on purpose
# ---------------------------------------------------------------------------


def _break(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, f"the fixture text is not unique: {old!r}"
    return source.replace(old, new)


def test_the_guard_names_bodies_broken_on_purpose():
    """Each mutation is a defect this guard exists for, made in a copy of
    ``app.js``; each must be reported at the line it was made on."""
    path = STATIC / "app.js"
    source = path.read_text(encoding="utf-8")
    broken = source
    # 1. The shipped CR 116 defect: the special-action body without its seat.
    broken = _break(broken, '    seat,\n    action: "special_action",', '    action: "special_action",')
    # 2. A per-kind field: the hand ability without its card or its copy.
    broken = _break(
        broken,
        "        card_name: entry.name,\n        hand_index: entry.hand_index,\n"
        "        ability_index: entry.ability_index,\n      };",
        "        ability_index: entry.ability_index,\n      };",
    )
    # 3. A kind nobody declared.
    broken = _break(broken, 'action: "bid_life_pass"', 'action: "bid_life_skip"')
    # 4. A descriptor's field, read through the caller of the shared prompt.
    broken = _break(broken, 'field: "chosen_seat",\n    labelOf: (option) => option.name,',
                    'field: "seat_chosen",\n    labelOf: (option) => option.name,')
    # 5. A nested model's required field: an entry-exile pick without its index.
    broken = _break(broken, "entryExileSelected.map((pick) => ({\n      index: pick.index,\n",
                    "entryExileSelected.map((pick) => ({\n")
    # 6. A required query parameter.
    broken = _break(broken, "card_target_spec?card_name=${encodeURIComponent(card.name)}&seat=${casterSeat}",
                    "card_target_spec?card_name=${encodeURIComponent(card.name)}")
    assert broken != source
    scripts = [Script(path, source=broken) if s.name == "app.js" else s for s in load_scripts(STATIC)]
    problems = Census(scripts).problems()
    text = {key: "\n".join(lines) for key, lines in problems.items()}

    special = broken[:broken.index('sendAction({\n    action: "special_action",')].count("\n") + 1
    assert any(f"app.js:{special} " in line and "no ['seat']" in line
               for line in problems["required"]), text["required"]
    assert any("activate_hand is refused without card_name or hand_index" in line
               for line in problems["handler"]), text["handler"]
    assert any("'bid_life_skip' is not an ActionKind" in line for line in problems["kind"]), text["kind"]
    assert any("player_choice_confirm is refused without chosen_seat" in line
               for line in problems["handler"]), text["handler"]
    assert any("entry_exile_picks entry" in line and "no ['index']" in line
               for line in problems["nested"]), text["nested"]
    assert any("card_target_spec" in line and "seat" in line for line in problems["query"]), text["query"]
    # …and nothing else moved: the clean tree's problems are none at all, so
    # every line here is one of the six.
    clean = census().problems()
    assert all(lines == [] for lines in clean.values()), clean
