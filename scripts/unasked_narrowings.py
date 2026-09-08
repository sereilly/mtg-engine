"""Which printed narrowings reach a handler that never asks them?

**The bug class this exists for.** ``engine/subject_filters.subject_matches`` is
the one answer for what a printed noun phrase means, and five of the things a
phrase can say are facts *no read of a permanent can supply*: which seat is
"you" (CR 109.5), which seat is "defending player" (CR 506.2), which seat "that
player" or "target opponent" named, and which permanent the ability's own source
is. Each arrives as a keyword argument, and the matcher **refuses the word** when
its caller does not supply one — deliberately, because narrowing to nothing is
safer than narrowing to everything.

That refusal is invisible at the call site. It looks exactly like "this
permanent does not match", so a handler that forgets an argument produces a
sweep that finds nothing, a picker that offers nothing, or a target that
resolves against nothing — with the card reported supported, its line claimed,
its compiled program unchanged and every ratchet green. Three shipped cards were
dead this way when this script was written: Sidar Jabari's "tap target creature
**defending player** controls" logged "no valid permanent to tap" every time,
Jangling Automaton's "untap all creatures **defending player** controls" swept
the empty set, and Scalding Salamander's damage sweep found nothing to damage.
All three were found by playing a card, not by an instrument.

**What this asks.** Two halves, joined:

1. a census of the pool — for each instruction kind, which
   argument-requiring narrowings do the compiled payloads actually carry, and
   on which cards;
2. a static read of ``engine/handlers/`` — for each ``@effect_handler`` kind,
   which keyword arguments does anything it calls hand to ``subject_matches``?

A kind that produces a narrowing its handler never supplies the argument for is
a finding: the phrase is carried the whole way and then not asked.

**Why static and not a runtime probe.** A runtime counter over a corpus of games
would be more precise, and it would also only ever report the phrases the corpus
happened to play — which for a card like Sidar Jabari means a seeded AI game has
to attack with it. The payload census reads every card in the pool whether or
not anybody has drawn it.

Advisory, like ``scripts/rules_gaps.py``: it prints findings and exits 0 unless
``--check`` is given. A finding is a work-list entry, not a diagnosis — a
handler may legitimately answer a phrase itself (``_tap_or_untap_all_matching``
rewrites "that player" into "you" against a frozen seat before it calls the
matcher at all), and this cannot see that.

Usage:
    python scripts/unasked_narrowings.py           # report
    python scripts/unasked_narrowings.py --check   # exit 1 if anything is found
    python scripts/unasked_narrowings.py --kinds   # per-kind detail
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.card_loader import load_cards, manifest_set_paths  # noqa: E402
from engine.oracle import compile_card_oracle  # noqa: E402

HANDLERS_DIR = REPO_ROOT / "engine" / "handlers"
#: The whole engine, because a handler routinely asks the question through a
#: ``Game`` method in another module (``_destroy_target_permanent`` carries the
#: defending seat for every destroy in the pool). Scanning only the handler
#: package reported each of those as a handler that never asks.
ENGINE_DIR = REPO_ROOT / "engine"

#: The keyword argument each argument-requiring narrowing needs, keyed by what
#: the payload says. Read straight off ``subject_filters.subject_matches``: the
#: value of ``controller`` decides three of them, and two more keys are relative
#: to the observer whatever they say.
#:
#: ``("controller", "you")`` and ``("controller", "opponent")`` fall to the
#: matcher's final ``else``, which needs the observer.
CONTROLLER_ARGUMENT = {
    "defending_player": "defending",
    "that_player": "that_player",
    "target_opponent": "targeted_player",
    "target_player": "targeted_player",
    # "the active player" is the one seat word that needs nothing: whose turn
    # it is is a fact about the game rather than about the ability.
    "active_player": None,
}
#: Keys that are relative to the observer whatever their value.
OBSERVER_KEYS = ("owner", "owner_or_controller")
#: …and the key that needs the ability's own source (CR 109.5's "another").
SOURCE_KEYS = ("another",)

#: The default scope, and the reason this instrument is usable at all: the
#: three seats the matcher documents as **refused when the caller cannot say**.
#: They are the fail-closed set — a phrase naming one of them narrows to
#: *nothing* without its argument, which is the silence this exists to break.
#:
#: ``observer`` is deliberately not here. "You control" is the commonest phrase
#: in the pool and the most thoroughly implemented, and a handler can arrive at
#: the seat by half a dozen routes this static read cannot follow — so
#: including it buries three real findings under forty that are not.
#: ``--all-arguments`` turns it back on for a deliberate audit.
STRICT_SEATS = ("defending", "that_player", "targeted_player")

#: The call this instrument follows. ``permanent_matches_filter`` is the pure
#: half and takes none of these arguments at all, so a relative key reaching it
#: is a different (and louder) finding that the compiler's own key gate already
#: refuses — see ``TESTABLE_SUBJECT_FILTER_KEYS``.
MATCHER = "subject_matches"

#: How many hops from an ``@effect_handler`` to count as "this handler asks".
#: See :func:`handler_arguments` — two is the deepest real delegation shape in
#: this package, and unbounded is the same as no instrument at all.
MAX_DELEGATION_DEPTH = 2


def _narrowings(payload) -> set[str]:
    """Every argument-requiring narrowing *payload* carries, as argument names.

    Walks nested filters — ``targets.filter``, ``filter``, ``attached_to_filter``
    — because a phrase's seat can sit at any depth and the matcher recurses into
    the same places.
    """
    found: set[str] = set()
    if isinstance(payload, dict):
        controller = payload.get("controller")
        if isinstance(controller, str):
            argument = CONTROLLER_ARGUMENT.get(controller, "observer")
            if argument is not None:
                found.add(argument)
        for key in OBSERVER_KEYS:
            if payload.get(key) is not None:
                found.add("observer")
        for key in SOURCE_KEYS:
            if payload.get(key) is not None:
                found.add("source")
        for value in payload.values():
            found |= _narrowings(value)
    elif isinstance(payload, (list, tuple)):
        for entry in payload:
            found |= _narrowings(entry)
    return found


def _instructions(instruction, out: list) -> None:
    if instruction is None:
        return
    out.append(instruction)
    for value in (instruction.payload or {}).values():
        if hasattr(value, "kind"):
            _instructions(value, out)
        elif isinstance(value, (list, tuple)):
            for entry in value:
                if hasattr(entry, "kind"):
                    _instructions(entry, out)


def census() -> dict[str, dict[str, set[str]]]:
    """``{instruction kind: {argument name: {card names}}}`` over both manifest
    roles — a measured set's cards are exactly the ones nobody has played yet,
    which is when this question is cheapest to answer."""
    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards([path]):
            pool.setdefault(card.name, card)

    rows: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for name, card in sorted(pool.items()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        seen: list = []
        for instruction in program.instructions:
            _instructions(instruction, seen)
        for ability in program.activated_abilities:
            _instructions(ability.instruction, seen)
        for trigger in program.triggered_abilities:
            _instructions(trigger.instruction, seen)
        for instruction in seen:
            for argument in _narrowings(instruction.payload or {}):
                rows[instruction.kind][argument].add(name)
    return rows


class _Reader(ast.NodeVisitor):
    """Per-function: the ``subject_matches`` keywords it passes, and the
    same-module functions it calls (so a handler that delegates is followed)."""

    def __init__(self) -> None:
        self.functions: dict[str, tuple[set[str], set[str]]] = {}
        self.kinds: dict[str, set[str]] = defaultdict(set)
        self._stack: list[str] = []

    def _enter(self, node) -> None:
        name = node.name
        self._stack.append(name)
        self.functions.setdefault(name, (set(), set()))
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and getattr(decorator.func, "id", None) == "effect_handler"
            ):
                for argument in decorator.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        self.kinds[argument.value].add(name)
        self.generic_visit(node)
        self._stack.pop()

    visit_FunctionDef = _enter
    visit_AsyncFunctionDef = _enter

    def visit_Call(self, node: ast.Call) -> None:
        if self._stack:
            passes, calls = self.functions[self._stack[-1]]
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == MATCHER:
                passes.update(kw.arg for kw in node.keywords if kw.arg)
            elif name:
                calls.add(name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # A *reference* is an edge too, and the commonest shape in this package
        # is exactly that: a handler defines `def _matches(perm)` around the
        # matcher and hands it to `resolve_target_permanent(predicate=_matches)`
        # without ever calling it by name. Following calls alone reported every
        # one of those as a handler that never asks.
        if self._stack and isinstance(node.ctx, ast.Load):
            self.functions[self._stack[-1]][1].add(node.id)
        self.generic_visit(node)


def handler_arguments() -> dict[str, set[str]]:
    """``{instruction kind: {keyword names handed to subject_matches}}``.

    Transitive through calls, because a handler is routinely one line
    delegating to something that asks the question for it — a shared sweep in
    the same module (``untap_all_matching`` -> ``_tap_or_untap_all_matching``)
    or a ``Game`` method in another (``_destroy_target_permanent`` carries the
    defending seat for every destroy in the pool).

    Resolution is **module-first**: a call resolves to a definition in the same
    file if there is one, and otherwise to a definition elsewhere in ``engine/``
    only when exactly one exists. A merged bare name is how a static read of
    this shape leaks — and the leak is silent, because it can only ever make
    findings *disappear*.

    The matcher itself is never followed. ``subject_matches`` recurses into
    itself passing every seat it was given, so treating it as an ordinary
    callee credits every handler that calls it with all five arguments — which
    is precisely a green report over the three cards this instrument was
    written to find.
    """
    modules: dict[str, dict[str, tuple[set[str], set[str]]]] = {}
    kinds: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for path in sorted(ENGINE_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        reader = _Reader()
        reader.visit(ast.parse(path.read_text(encoding="utf-8")))
        key = str(path)
        modules[key] = reader.functions
        for kind, names in reader.kinds.items():
            kinds[kind] |= {(key, name) for name in names}

    defined_in: dict[str, list[str]] = defaultdict(list)
    for module, functions in modules.items():
        for name in functions:
            defined_in[name].append(module)

    resolved: dict[tuple[str, str, int], set[str]] = {}
    visiting: set[tuple[str, str, int]] = set()

    def _home(module: str, name: str) -> str | None:
        if name in modules.get(module, {}):
            return module
        homes = defined_in.get(name, [])
        return homes[0] if len(homes) == 1 else None

    def _resolve(module: str, name: str, depth: int) -> set[str]:
        """Every ``subject_matches`` keyword reachable from this function within
        *depth* hops.

        **Depth is the whole accuracy knob.** The real delegation shapes are one
        hop (a handler calling a shared sweep, or a ``Game`` method that asks
        for it) and two (a handler defining a closure around the matcher and
        handing it to a target resolver). Beyond that the closure stops
        describing this handler and starts describing ``engine/``: an unbounded
        walk credits every damage handler with every seat, because some helper
        four hops down asks the matcher a different question about a different
        filter. Unbounded, this instrument reported the pre-round engine clean
        on two of the three cards it was written to find.

        Memoized per (site, remaining depth) and cycle-guarded: the call graph
        has plenty of mutual recursion.
        """
        if name == MATCHER or depth < 0:
            return set()
        home = _home(module, name)
        if home is None:
            return set()
        site = (home, name, depth)
        if site in resolved:
            return resolved[site]
        if site in visiting:
            return set()
        visiting.add(site)
        passes, calls = modules[home][name]
        total = set(passes)
        for callee in calls:
            total |= _resolve(home, callee, depth - 1)
        visiting.discard(site)
        resolved[site] = total
        return total

    per_kind: dict[str, set[str]] = defaultdict(set)
    for kind, sites in kinds.items():
        for module, name in sites:
            per_kind[kind] |= _resolve(module, name, MAX_DELEGATION_DEPTH)
    return per_kind


def findings(*, every_argument: bool = False):
    rows = census()
    supplied = handler_arguments()
    scope = None if every_argument else set(STRICT_SEATS)
    out = []
    for kind in sorted(rows):
        known = supplied.get(kind)
        if known is None:
            continue  # no handler in engine/handlers/ — a control-flow kind
        for argument in sorted(rows[kind]):
            if scope is not None and argument not in scope:
                continue
            if argument not in known:
                out.append((kind, argument, sorted(rows[kind][argument])))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 on any finding")
    parser.add_argument("--kinds", action="store_true", help="list every kind's narrowings")
    parser.add_argument(
        "--all-arguments", action="store_true",
        help="widen past the three refused seats to `observer` and `source`",
    )
    args = parser.parse_args()

    if args.kinds:
        rows = census()
        supplied = handler_arguments()
        for kind in sorted(rows):
            asked = ",".join(sorted(supplied.get(kind, ()))) or "-"
            needs = ",".join(sorted(rows[kind]))
            print(f"{kind:44s} needs={needs:34s} asks={asked}")
        return 0

    found = findings(every_argument=args.all_arguments)
    if not found:
        print("No printed narrowing reaches a handler that never supplies its argument.")
        return 0
    print(f"{len(found)} narrowing(s) carried to a handler that never asks:\n")
    for kind, argument, cards in found:
        shown = ", ".join(cards[:6]) + (" …" if len(cards) > 6 else "")
        print(f"  {kind}  needs `{argument}=`  ({len(cards)} card(s): {shown})")
    print(
        "\nAdvisory. A handler may answer the phrase itself before calling the\n"
        "matcher (rewriting 'that player' into 'you' against a frozen seat);\n"
        "read each finding as a work-list entry, not a diagnosis."
    )
    return 1 if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
