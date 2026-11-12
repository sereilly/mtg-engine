"""Why is this line refused? Every layer the compiler consults, with its verdict.

    python scripts/probe_line.py --card "Goblin Charbelcher"     # a card, either manifest role
    python scripts/probe_line.py "Frobnicate the gribble."       # a raw line, on an invented card
    python scripts/probe_line.py --type Instant "Draw a card." "Scry 2."   # lines of one invented card
    python scripts/probe_line.py --card "Shared Fate" --json     # the same report as one JSON object
    python scripts/probe_line.py --card "Shared Fate" --full     # grammar nodes and instruction payloads too
    python scripts/probe_line.py --card "Aether Vial" --ast      # each line's parsed tree, field by field

Each line the compiler reads (after ``expand_ability_lines``) gets the layers
it passed through, in the order the compiler asked them, and one verdict:
``refused at <layer>: <reason>`` or ``accepted (<instruction kinds>)``.

A lowering refusal is printed with **where it was raised**: the innermost
``LoweringError`` of the chain ``compile_line``'s lowering let out, at its
``raise`` (``file:line``), and the lowering frames that led there
(:func:`lowering_refusal`). The message alone names what the lowering wanted,
and the furthest frame of a parse names where the *parser* stopped — neither is
the line of lowering code that said no.

``--ast`` prints each line's parsed tree as the grammar built it — every node
with the fields it set (a field at its default is left out) — and, for a line
of more than one sentence, each sentence asked alone, which is where a
refusal inside a longer line is localised. A sentence asked alone is read out
of its context ("it", "that player"), so its verdict is a lead.

**Nothing here decides what the compiler decides.** The verdicts are read off
the compiler's own run:

* **The compile is the compiler's.** ``oracle._compile_card_program`` runs on
  the card (on each face of a split card), past its caches, while every reader
  in :data:`READERS` is observed: rebound, for the length of the probe, to a
  tracer that records the call, the text it was handed and the answer, then
  calls through. What a reader said, at what depth and in what order, is the
  trace; a line is *claimed* when a reader the line loop called directly
  claimed it, and *refused* when a gate named it or nothing claimed it.
* **The grammar** is ``grammar.compile_line`` asked of the text the compiler
  handed it for the line: parse error, lowering error, node, instructions, and
  the furthest production that accepted (:func:`furthest_production` — the
  ``TokenStream.advance`` watch ``scripts/integration/furthest.py`` used to
  carry by itself).
* **Card hooks** are ``card_hooks.card_line_instruction`` for the line and
  every public name-keyed table in ``card_hooks`` that holds the card's name.
* **The support gate** is the program's ``supported`` and ``reason``;
  **handlers** are ``handlers.EFFECT_HANDLERS`` and the lowering's
  ``INSTRUCTION_CATEGORIES`` for every kind the line produced; a supported
  ability with no instruction behind it is *hollow* (``support_report.py
  --hollow-lines``).

Two things a compile does not say about a line, and how they are filled:

* A creature or planeswalker is refused at its **first** unreadable line, and
  a card gate refuses before any line is read, so the lines after a refusal are
  never asked. The probe compiles the card again without the printed line that
  refused, until every line has been read or nothing more can be removed. A
  verdict read that way names the lines removed: a card missing a line is a
  different card, so read it as a lead.
* A noncreature card is supported when *any* line is, so its compile never
  refuses a line by itself. A line none of its passes claimed is asked of the
  readers that carry such a line outside the compile — the land path's
  static-text gate (``_unread_land_text``, which asks the keyword, static,
  enter-effect and derived tables of one line) and the two cast-cost tables the
  creature loop asks — and only a line all of them pass on is refused.

The trace is only as wide as :data:`READERS`. A reader that no longer exists is
reported (``drift`` in the output, and ``tests/engine/test_probe_line.py``
fails on it); a new reader the compiler grows is invisible until it is added
there, which the consistency test over the pool is for.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import re
import sys
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import card_hooks  # noqa: E402
from engine import oracle  # noqa: E402
from engine.card_loader import (load_cards, manifest_measured_codes,  # noqa: E402
                                manifest_set_paths)
from engine.faces import face_cards  # noqa: E402
from engine.grammar import GRAMMAR_CATEGORIES, LoweringError, compile_line  # noqa: E402
from engine.grammar import stream as grammar_stream  # noqa: E402
from engine.grammar.lowering.categories import INSTRUCTION_CATEGORIES  # noqa: E402
from engine.grammar.parser import each_line_parsed_once  # noqa: E402
from engine.handlers import EFFECT_HANDLERS  # noqa: E402
from engine.line_normalization import normalize_creature_line  # noqa: E402
from engine.line_rewrites import expand_ability_lines  # noqa: E402
from engine.models import CardDefinition  # noqa: E402
from engine.oracle_types import OracleInstruction  # noqa: E402
from engine.self_reference import _restriction_line  # noqa: E402
from set_argument import add_set_argument, resolve_set  # noqa: E402


# ---------------------------------------------------------------------------
# The readers observed
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reader:
    """One function the compiler consults, and how to read its answer.

    *role* is what an answer from it means for a line:

    * ``root`` — the compile itself, called past its cache and not recorded;
    * ``gate`` — a whole-card check: an answer other than None refuses the line
      it names (or the card, when it names none);
    * ``line`` — a reader a line loop hands one line: a truthy answer claims
      the line, when the loop asked it directly;
    * ``whole`` — a reader handed the whole text, whose answer this module
      spreads over the lines it names (:func:`_whole_text_verdicts`);
    * ``detail`` — asked on the way to someone else's answer (the grammar, the
      trigger table, the hooks): shown, never decisive.
    """

    module: str
    name: str
    layer: str
    role: str


READERS: tuple[Reader, ...] = (
    Reader("engine.oracle", "_compile_card_oracle", "compile", "root"),
    # The gates oracle._compile_card_oracle asks before any line is classified,
    # and the one _compile_card_program asks after.
    Reader("engine.cast_costs", "unread_cost_sentence", "card gate: uncharged cost", "gate"),
    Reader("engine.alternative_costs", "unread_alternative_cost_sentence",
           "card gate: uncharged alternative cost", "gate"),
    Reader("engine.alternative_costs", "unread_granted_alternative_cost_sentence",
           "card gate: uncharged granted alternative cost", "gate"),
    Reader("engine.entwine", "unsupported_entwine", "card gate: entwine", "gate"),
    Reader("engine.cast_costs", "unlinked_kicker_question", "card gate: kicker question", "gate"),
    Reader("engine.cast_costs", "unenforced_x_spend_restriction",
           "card gate: X spend restriction", "gate"),
    Reader("engine.cast_costs", "unchosen_number_definition", "card gate: chosen number", "gate"),
    Reader("engine.cycling", "unread_cycling_line", "card gate: cycling", "gate"),
    Reader("engine.fading", "unread_fading_line", "card gate: fading", "gate"),
    Reader("engine.modular", "unread_modular_line", "card gate: modular", "gate"),
    Reader("engine.flashback", "unread_flashback_line", "card gate: flashback", "gate"),
    Reader("engine.madness", "unread_madness_line", "card gate: madness", "gate"),
    Reader("engine.affinity", "unread_affinity_line", "card gate: affinity", "gate"),
    Reader("engine.storm", "unread_storm_line", "card gate: storm", "gate"),
    Reader("engine.flashback", "flashback_x_unannounced", "card gate: flashback X", "gate"),
    # The line loops (engine/line_classification.py) and what they hand a line.
    Reader("engine.ability_lines", "_modal_trigger_ability", "modal trigger", "line"),
    Reader("engine.keyword_lines", "_is_supported_keyword_line", "keyword line", "line"),
    Reader("engine.keyword_lines", "keyword_line_triggers", "keyword trigger", "line"),
    Reader("engine.cast_costs", "cast_cost_claims_line", "cast cost table", "line"),
    Reader("engine.alternative_costs", "alternative_cost_claims_line",
           "alternative cost table", "line"),
    Reader("engine.special_actions", "special_action_line", "special action table", "line"),
    Reader("engine.ability_lines", "_parse_triggered_ability", "triggered ability", "line"),
    Reader("engine.ability_lines", "_parse_activated_ability", "activated ability", "line"),
    Reader("engine.line_classification", "_parse_loyalty_ability", "loyalty ability", "line"),
    Reader("engine.line_classification", "_planeswalker_static_line",
           "planeswalker static", "line"),
    Reader("engine.static_line_support", "_is_supported_static_creature_line",
           "static-line tables", "line"),
    Reader("engine.static_line_support", "_grammar_static_creature_instructions",
           "grammar static", "line"),
    Reader("engine.characteristic_defining", "dynamic_pt_for",
           "characteristic-defining P/T table", "line"),
    Reader("engine.static_bonuses", "static_bonus_for", "static bonus table", "line"),
    Reader("engine.lord_buffs", "lord_buff_for", "lord buff table", "line"),
    Reader("engine.combat_restrictions", "combat_restriction_for",
           "combat restriction table", "line"),
    Reader("engine.enter_effects", "enter_effect_line", "enter effects table", "line"),
    Reader("engine.ability_lines", "_parse_delayed_attack_trigger",
           "delayed trigger table", "line"),
    Reader("engine.ability_lines", "_split_trailing_delayed_trigger",
           "trailing delayed trigger", "line"),
    Reader("engine.front_ends", "_line_instruction", "front ends", "line"),
    # Asked on the way.
    Reader("engine.trigger_conditions", "trigger_condition_of_line",
           "trigger-condition table", "detail"),
    Reader("engine.ability_lines", "_reads_as_registry_line", "registry line", "detail"),
    Reader("engine.front_ends", "_grammar_instruction", "grammar front end", "detail"),
    Reader("engine.front_ends", "_card_hook_instruction", "card hook", "detail"),
    Reader("engine.equipment", "is_equip_line", "equip line", "detail"),
    Reader("engine.grammar", "compile_line", "grammar", "detail"),
    # Handed the whole text.
    Reader("engine.ability_lines", "_modal_options", "modal spell", "whole"),
    Reader("engine.front_ends", "_grammar_static_coeffects", "derived co-effects", "whole"),
    Reader("engine.derived_static_claims", "_derived_static_claims",
           "derived static tables", "whole"),
    Reader("engine.auras", "unclaimed_aura_lines", "Aura/Equipment gate", "whole"),
    Reader("engine.line_classification", "_unread_land_text", "land static gate", "whole"),
)


def resolve_readers() -> tuple[list[tuple[Reader, Callable]], list[str]]:
    """Each reader with the function it names, and the names that resolve to
    nothing — the drift :data:`READERS` has to be told about."""
    found: list[tuple[Reader, Callable]] = []
    missing: list[str] = []
    for reader in READERS:
        try:
            function = getattr(importlib.import_module(reader.module), reader.name)
        except (ImportError, AttributeError):
            missing.append(f"{reader.module}.{reader.name}")
            continue
        found.append((reader, function))
    return found, missing


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """One call of an observed reader during a compile."""

    reader: Reader
    args: tuple
    kwargs: dict
    depth: int
    parent: int | None
    result: Any = None
    raised: str | None = None
    #: Asked by this module after the compile (the noncreature fallback), not
    #: by the compiler.
    asked_by_probe: bool = False
    line: int | None = None


class _Recorder:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.stack: list[int] = []
        self.asked_by_probe = False

    def open(self, reader: Reader, args: tuple, kwargs: dict) -> int:
        self.events.append(Event(
            reader, args, kwargs, len(self.stack),
            self.stack[-1] if self.stack else None,
            asked_by_probe=self.asked_by_probe,
        ))
        self.stack.append(len(self.events) - 1)
        return self.stack[-1]

    def close(self, index: int, result: Any = None, raised: str | None = None) -> None:
        self.stack.pop()
        self.events[index].result = result
        self.events[index].raised = raised


_RECORDING: _Recorder | None = None
_SESSION: dict[str, Any] = {"depth": 0, "bindings": [], "tracers": {}, "missing": []}


def _tracer(reader: Reader, original: Callable) -> Callable:
    uncached = getattr(original, "__wrapped__", original) if reader.role == "root" else original

    def traced(*args, **kwargs):
        recorder = _RECORDING
        if recorder is None:
            return original(*args, **kwargs)
        if reader.role == "root":
            return uncached(*args, **kwargs)
        index = recorder.open(reader, args, kwargs)
        try:
            result = uncached(*args, **kwargs)
        except BaseException as exc:
            recorder.close(index, raised=f"{type(exc).__name__}: {exc}")
            raise
        recorder.close(index, result)
        return result

    traced.__probe_original__ = original
    traced.__wrapped__ = original
    return traced


def _engine_namespaces():
    for name, module in list(sys.modules.items()):
        if module is not None and (name == "engine" or name.startswith("engine.")):
            yield vars(module)


@contextmanager
def observing():
    """Rebind every reader in :data:`READERS`, wherever the engine holds it,
    to its tracer; restore them all on the way out. Re-entrant.

    Outside a recording a tracer calls straight through, so a module imported
    while this is open and binding a tracer behaves as the original — and is
    found and restored on exit all the same."""
    if _SESSION["depth"] == 0:
        found, missing = resolve_readers()
        by_id = {id(function): (reader, function) for reader, function in found}
        tracers = {id(function): _tracer(reader, function) for reader, function in found}
        bindings = []
        for namespace in _engine_namespaces():
            for attribute, value in list(namespace.items()):
                hit = by_id.get(id(value))
                if hit is not None and value is hit[1]:
                    namespace[attribute] = tracers[id(value)]
                    bindings.append((namespace, attribute, value))
        _SESSION.update(bindings=bindings, tracers=tracers, missing=missing)
    _SESSION["depth"] += 1
    try:
        yield _SESSION["missing"]
    finally:
        _SESSION["depth"] -= 1
        if _SESSION["depth"] == 0:
            for namespace, attribute, value in _SESSION["bindings"]:
                namespace[attribute] = value
            originals = {
                id(tracer): tracer.__probe_original__
                for tracer in _SESSION["tracers"].values()
            }
            for namespace in _engine_namespaces():
                for attribute, value in list(namespace.items()):
                    if id(value) in originals:
                        namespace[attribute] = originals[id(value)]
            _SESSION.update(bindings=[], tracers={})


@contextmanager
def _recording(recorder: _Recorder):
    global _RECORDING
    previous, _RECORDING = _RECORDING, recorder
    try:
        yield recorder
    finally:
        _RECORDING = previous


def traced_compile(unit: CardDefinition):
    """``(program, events)``: *unit* compiled by the compiler, uncached, with
    every observed reader's call recorded in the order it was made."""
    recorder = _Recorder()
    with observing(), _recording(recorder), each_line_parsed_once():
        program = oracle._compile_card_program(unit)
    return program, recorder.events


# ---------------------------------------------------------------------------
# The grammar layer
# ---------------------------------------------------------------------------

_GRAMMAR_DIR = str(Path(importlib.import_module("engine.grammar").__file__).parent).lower()


@dataclass
class Furthest:
    """How far the parse got: the highest token the stream reached, and the
    grammar functions on the stack at that moment (innermost last)."""

    token: int
    total: int
    unread: str
    frames: list[tuple[str, int, str]]


def furthest_production(line: str, card_name: str | None = None):
    """``(compiled, furthest)`` — ``compile_line`` of *line*, with the
    furthest production that accepted.

    Watches ``TokenStream.advance`` for the highest cursor reached and the
    grammar frames on the stack then. It names where the parser stopped, not
    where the sentence will be taught: a lead. Asked outside a compile, so the
    parse is fresh rather than the compile's memo."""
    best: dict[str, Any] = {"pos": -1, "frames": [], "stream": None, "first": None}
    original = grammar_stream.TokenStream.advance
    original_init = grammar_stream.TokenStream.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if best["first"] is None:
            best["first"] = self

    def advance(self, count=1):
        original(self, count)
        if self.pos >= best["pos"]:
            frames = [
                frame for frame in traceback.extract_stack()[:-1]
                if frame.filename.lower().startswith(_GRAMMAR_DIR)
            ]
            best.update(
                pos=self.pos, stream=self,
                frames=[
                    (frame.filename[len(_GRAMMAR_DIR) + 1:].replace("\\", "/"),
                     frame.lineno, frame.name)
                    for frame in frames
                ],
            )

    grammar_stream.TokenStream.advance = advance
    grammar_stream.TokenStream.__init__ = init
    try:
        compiled = compile_line(line, card_name=card_name)
    finally:
        grammar_stream.TokenStream.advance = original
        grammar_stream.TokenStream.__init__ = original_init
    stream, position = best["stream"], best["pos"]
    if stream is None:
        # Refused before a single token was taken: the line's own stream.
        stream, position = best["first"], 0
    if stream is None:
        return compiled, Furthest(0, 0, "", [])
    unread = " ".join(token.text for token in stream.tokens[position:])
    return compiled, Furthest(position, len(stream.tokens), unread, best["frames"])


_ROOT = Path(__file__).resolve().parent.parent
_GRAMMAR_PACKAGE = importlib.import_module("engine.grammar")


@dataclass
class LoweringRefusal:
    """Where a lowering said no: the innermost ``LoweringError`` of the chain
    that left ``lower_ability``, at its ``raise``.

    *chain* is every message, outermost (the one ``compile_line`` reports)
    first; *frames* the lowering's frames from ``lower_ability`` to the raise,
    innermost last."""

    site: str
    message: str
    chain: list[str]
    frames: list[tuple[str, int, str]]


def _repo_path(filename: str) -> str:
    try:
        return Path(filename).resolve().relative_to(_ROOT).as_posix()
    except ValueError:
        return filename


def lowering_refusal(error: LoweringError) -> LoweringRefusal:
    """The innermost ``LoweringError`` behind *error*, read off its chain.

    A lowering that catches one refusal and raises another (``raise
    LoweringError(...)`` inside an ``except``, or ``from``) leaves the first as
    the second's cause or context; the innermost is the one raised first, and
    its traceback's last frame is the ``raise``. A ``from None`` ends the chain
    where the code said it ends."""
    chain = [error]
    while True:
        current = chain[-1]
        inner = current.__cause__ if current.__cause__ is not None else (
            None if current.__suppress_context__ else current.__context__)
        if not isinstance(inner, LoweringError) or any(inner is seen for seen in chain):
            break
        chain.append(inner)
    innermost = chain[-1]
    frames = [
        (_repo_path(frame.filename), frame.lineno, frame.name)
        for frame in traceback.extract_tb(innermost.__traceback__)
    ]
    site = f"{frames[-1][0]}:{frames[-1][1]} ({frames[-1][2]})" if frames else "unknown"
    # From the lowering's entry on: the watch's own frame is not the engine's.
    engine = [frame for frame in frames if frame[0].startswith("engine/")]
    return LoweringRefusal(site, str(innermost), [str(item) for item in chain], engine)


@contextmanager
def _lowering_watch():
    """Every ``LoweringError`` ``compile_line``'s lowering lets out, as it
    leaves ``lower_ability`` — observed on the grammar's own call (the name is
    looked up in ``engine.grammar`` as the line compiles), never re-asked."""
    caught: list[LoweringError] = []
    original = _GRAMMAR_PACKAGE.lower_ability

    def watched(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except LoweringError as error:
            caught.append(error)
            raise

    _GRAMMAR_PACKAGE.lower_ability = watched
    try:
        yield caught
    finally:
        _GRAMMAR_PACKAGE.lower_ability = original


def compile_line_watched(text: str, card_name: str | None):
    """``(compiled, refusal)``: ``compile_line`` of *text*, and where its
    lowering refused it (None when it did not)."""
    with _lowering_watch() as caught:
        compiled = compile_line(text, card_name=card_name)
    refusal = None
    if compiled.lowering_error is not None and caught:
        refusal = lowering_refusal(caught[-1])
    return compiled, refusal


@dataclass
class GrammarVerdict:
    text: str
    parse_error: str | None
    lowering_error: str | None
    node: str | None
    node_repr: str | None
    kinds: list[str]
    categories: list[str]
    usable: bool
    blank: bool
    furthest: Furthest | None
    #: The text-keyed registry a ``RegistryLine`` hands the line to.
    registry: str | None = None
    #: Where the lowering refused the line, when it did.
    lowering: LoweringRefusal | None = None

    @property
    def parsed(self) -> bool:
        return self.node is not None


def grammar_verdict(text: str, card_name: str | None) -> GrammarVerdict:
    """The grammar's verdict on *text*; the furthest production only when the
    parse failed (watching it costs a stack walk per token)."""
    compiled, refusal = compile_line_watched(text, card_name)
    furthest = furthest_production(text, card_name)[1] if compiled.parse_error else None
    return GrammarVerdict(
        text=text,
        parse_error=compiled.parse_error,
        lowering_error=compiled.lowering_error,
        node=type(compiled.node).__name__ if compiled.node is not None else None,
        node_repr=repr(compiled.node) if compiled.node is not None else None,
        kinds=[instruction.kind for instruction in compiled.instructions],
        categories=sorted(compiled.categories),
        usable=compiled.usable,
        blank=compiled.blank,
        furthest=furthest,
        registry=getattr(compiled.node, "registry", None),
        lowering=refusal,
    )


# ---------------------------------------------------------------------------
# The parsed tree (--ast)
# ---------------------------------------------------------------------------

def _is_default(item: dataclasses.Field, value: Any) -> bool:
    if item.default is not dataclasses.MISSING:
        return value == item.default
    if item.default_factory is not dataclasses.MISSING:
        return value == item.default_factory()
    return False


def ast_dict(value: Any) -> Any:
    """*value* as plain data: a node is ``{"node": <type>, <field>: ...}``
    with only the fields it sets (a field at its default is left out).

    A set is sorted by repr, so two processes print it alike."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out: dict[str, Any] = {"node": type(value).__name__}
        for item in dataclasses.fields(value):
            child = getattr(value, item.name)
            if not _is_default(item, child):
                out[item.name] = ast_dict(child)
        return out
    if isinstance(value, (tuple, list)):
        return [ast_dict(child) for child in value]
    if isinstance(value, (set, frozenset)):
        return [ast_dict(child) for child in sorted(value, key=repr)]
    if isinstance(value, dict):
        return {str(key): ast_dict(child) for key, child in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _inline(value: Any) -> str | None:
    """*value* on one line, when it holds no node."""
    if isinstance(value, dict) and "node" in value:
        return f"{value['node']}()" if len(value) == 1 else None
    if isinstance(value, list):
        parts = [_inline(child) for child in value]
        if any(part is None for part in parts):
            return None
        return "(" + ", ".join(parts) + ("," if len(parts) == 1 else "") + ")"
    if isinstance(value, dict):
        parts = [_inline(child) for child in value.values()]
        if any(part is None for part in parts):
            return None
        return "{" + ", ".join(f"{key!r}: {part}" for key, part in zip(value, parts)) + "}"
    return repr(value)


def ast_lines(value: Any, indent: str = "", label: str = "") -> list[str]:
    """:func:`ast_dict`'s output as an indented tree, one field a line."""
    inline = _inline(value)
    if inline is not None:
        return [f"{indent}{label}{inline}"]
    if isinstance(value, list):
        out = [f"{indent}{label}({len(value)})"] if label else []
        for i, child in enumerate(value):
            out += ast_lines(child, indent + ("  " if label else ""), f"[{i}] ")
        return out
    if isinstance(value, dict) and "node" not in value:
        out = [f"{indent}{label}{{…}}"]
        for key, child in value.items():
            out += ast_lines(child, indent + "  ", f"{key!r}: ")
        return out
    out = [f"{indent}{label}{value['node']}"]
    for key, child in value.items():
        if key != "node":
            out += ast_lines(child, indent + "  ", f"{key}: ")
    return out


def sentences(text: str) -> list[str]:
    """*text* cut after each full stop (or "!") that ends a sentence, never
    inside a quoted ability or a parenthesis (reminder text) — but after a
    parenthesis that closes on one, as reminder text ending a sentence does."""
    out, start, depth, quoted = [], 0, 0, False
    for i, char in enumerate(text):
        ends = i + 1 == len(text) or text[i + 1].isspace()
        if char == '"':
            quoted = not quoted
        elif char == "(" and not quoted:
            depth += 1
        elif char == ")" and not quoted and depth:
            depth -= 1
            if not depth and ends and text[i - 1] in ".!":
                out.append(text[start:i + 1].strip())
                start = i + 1
        elif char in ".!" and not quoted and not depth and ends:
            if text[start:i + 1].strip():
                out.append(text[start:i + 1].strip())
            start = i + 1
    if text[start:].strip():
        out.append(text[start:].strip())
    # Reminder text standing after its sentence's full stop belongs to it.
    merged: list[str] = []
    for part in out:
        if merged and part.startswith("(") and part.endswith(")"):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def ast_reading(text: str, card_name: str | None, alone: bool = False) -> dict:
    """The grammar's tree for *text* and what became of it."""
    compiled, refusal = compile_line_watched(text, card_name)
    return {
        "text": text,
        "alone": alone,
        "blank": compiled.blank,
        "parse_error": compiled.parse_error,
        "ast": ast_dict(compiled.node) if compiled.node is not None else None,
        "lowering_error": compiled.lowering_error,
        "lowering": _jsonable(refusal) if refusal is not None else None,
        "kinds": [instruction.kind for instruction in compiled.instructions],
    }


def attach_ast(reports: list["UnitReport"]) -> None:
    """Each line's tree (``LineReport.ast``): the line as the compiler handed
    it to the grammar, then — for a line of more than one sentence — each
    sentence asked alone."""
    for unit in reports:
        for line in unit.lines:
            if line.blank:
                continue
            readings = [ast_reading(line.grammar.text, unit.name)]
            parts = sentences(line.grammar.text)
            if len(parts) > 1:
                readings += [ast_reading(part, unit.name, alone=True) for part in parts]
            line.ast = readings


# ---------------------------------------------------------------------------
# Reading an answer
# ---------------------------------------------------------------------------

CLAIM, REFUSE, PASS, INFO = "claim", "refuse", "pass", "info"


def _instructions_in(value: Any) -> list[OracleInstruction]:
    """The instructions an answer carries, at its top level."""
    if isinstance(value, OracleInstruction):
        return [value]
    instruction = getattr(value, "instruction", None)
    if isinstance(instruction, OracleInstruction):
        return [instruction]
    if isinstance(value, (tuple, list)):
        found: list[OracleInstruction] = []
        for item in value:
            if isinstance(item, OracleInstruction):
                found.append(item)
            elif isinstance(getattr(item, "instruction", None), OracleInstruction):
                found.append(item.instruction)
            elif hasattr(item, "kind") and hasattr(item, "payload"):
                found.append(OracleInstruction(item.kind, "", dict(item.payload)))
        return found
    kind = getattr(value, "kind", None)
    if isinstance(kind, str) and hasattr(value, "payload"):
        return [OracleInstruction(kind, "", dict(getattr(value, "payload") or {}))]
    return []


def answer(event: Event) -> tuple[str, str]:
    """``(verdict, summary)`` of one recorded call — what the reader said."""
    name, result = event.reader.name, event.result
    if event.raised:
        return REFUSE, f"raised {event.raised}"
    if name == "compile_line":
        if result.blank:
            return INFO, "blank (reminder text only)"
        if result.parse_error:
            return INFO, f"parse error: {result.parse_error}"
        node = type(result.node).__name__
        if result.lowering_error:
            return INFO, f"parsed {node}; lowering error: {result.lowering_error}"
        kinds = [instruction.kind for instruction in result.instructions]
        usable = "" if result.usable else " (not usable)"
        return INFO, f"parsed {node}, lowered {kinds}{usable}"
    if name == "trigger_condition_of_line":
        condition = result[0]
        if condition is None:
            return INFO, "no row reads the condition"
        return INFO, f"condition {condition.kind} ({condition.raw_text!r})"
    if name == "_reads_as_registry_line":
        return INFO, "a registry line" if result else "not a registry line"
    if event.reader.role == "gate":
        return (PASS, "passes") if result is None else (REFUSE, str(result))
    if name == "_modal_trigger_ability":
        if result is None:
            return PASS, "not a modal trigger head"
        if isinstance(result, str):
            return REFUSE, result
        return CLAIM, f"modal trigger with {result[1]} mode line(s)"
    if name in ("_parse_triggered_ability", "_parse_activated_ability", "_parse_loyalty_ability"):
        if result is None:
            what = {"_parse_triggered_ability": "no trigger condition read (or a registry line)",
                    "_parse_activated_ability": "no activation colon",
                    "_parse_loyalty_ability": "not a loyalty ability"}[name]
            return PASS, what
        condition = getattr(result, "condition", None)
        said = f"condition {condition.kind}; " if condition is not None else ""
        if not result.supported:
            return REFUSE, f"{said}its effect is not read"
        if result.instruction is None:
            return CLAIM, f"{said}supported, no instruction (hollow)"
        return CLAIM, f"{said}{result.instruction.kind} ({result.effect_kind})"
    if name in ("_line_instruction", "_grammar_instruction", "_card_hook_instruction"):
        if result is None:
            return PASS, "no reading"
        return CLAIM, f"{result[0].kind} ({result[1]})"
    if name == "unclaimed_aura_lines":
        return INFO, f"unclaimed: {result}" if result else "every line claimed"
    if name == "_unread_land_text":
        return INFO, "every line read" if result is None else f"unread: {result}"
    if name in ("_derived_static_claims", "_grammar_static_coeffects", "_modal_options"):
        if not result:
            return INFO, "nothing"
        if name == "_modal_options":
            return INFO, f"{len(result)} mode(s)"
        if name == "_grammar_static_coeffects":
            return INFO, f"{[instruction.kind for instruction in result]}"
        return INFO, ", ".join(result)
    if isinstance(result, bool):
        return (CLAIM, "claims it") if result else (PASS, "does not claim it")
    if result is None or (isinstance(result, (tuple, list, str)) and not result):
        return PASS, "does not claim it"
    kinds = [instruction.kind for instruction in _instructions_in(result)]
    return CLAIM, f"claims it {kinds}" if kinds else "claims it"


# ---------------------------------------------------------------------------
# Lines, and which line a call was about
# ---------------------------------------------------------------------------

def _read_lines(text: str, unit: CardDefinition) -> list[str]:
    expanded = expand_ability_lines(
        text or "", card_name=unit.name, legendary=unit.is_legendary
    )
    return [line.strip() for line in expanded.splitlines() if line.strip()]


def _aliases(line: str, card_name: str) -> set[str]:
    """Every spelling of *line* a reader is handed it in."""
    label = " ".join(line.lstrip("•").split())
    return {
        line, normalize_creature_line(line), _restriction_line(line, card_name),
        label, label.rstrip("."),
    } - {""}


def _subject(event: Event) -> str | None:
    """The text a call was about, when it was handed one line or clause."""
    if event.reader.name == "_modal_trigger_ability":
        lines, index = event.args[0], event.args[1]
        return str(lines[index]).strip()
    if event.reader.role in ("whole", "root"):
        return None
    if event.reader.role == "gate" and event.reader.name not in (
        "unread_cost_sentence", "unread_alternative_cost_sentence",
        "unread_granted_alternative_cost_sentence",
    ):
        return None
    if event.args and isinstance(event.args[0], str):
        return event.args[0].strip()
    return None


def _match_line(text: str, lines: list[str], aliases: list[set[str]],
                prefer: int | None = None) -> int | None:
    """The line *text* is, or is a clause of, or names."""
    text = text.strip()
    if not text:
        return None
    exact = [i for i, spelled in enumerate(aliases) if text in spelled]
    if exact:
        return prefer if prefer in exact else exact[0]
    lowered = text.lower()
    if prefer is not None:
        return prefer
    inside = [i for i, spelled in enumerate(aliases)
              if any(alias and alias.lower() in lowered for alias in spelled)]
    if inside:
        return max(inside, key=lambda i: len(lines[i]))
    holds = [i for i, spelled in enumerate(aliases)
             if any(lowered in alias.lower() for alias in spelled)]
    return holds[0] if holds else None


def _attribute(events: list[Event], lines: list[str], card_name: str) -> None:
    aliases = [_aliases(line, card_name) for line in lines]
    for event in events:
        parent = events[event.parent].line if event.parent is not None else None
        subject = _subject(event)
        if subject is not None:
            event.line = _match_line(subject, lines, aliases, prefer=parent)
        elif event.reader.role == "gate" and isinstance(event.result, str):
            event.line = _match_line(event.result, lines, aliases)
        elif event.reader.role != "whole":
            event.line = parent


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """A claim or a refusal of one line, and who made it.

    A refusal's *kind* says what it is evidence of:

    * ``gate`` — refused on the gate's own terms (a cost nothing charges, a
      kicker the card does not print, a mode that targets undescribably): the
      gate is the site, whatever else reads the line;
    * ``composite`` — a gate that asks many readers and refuses when none
      claims the line (the Aura gate, the land static gate): it is where the
      compiler refused, so it names the site, with the grammar's verdict on
      the line beside it;
    * ``reader`` — one reader declined it; the site is read off the layers
      behind it (:func:`_site`).
    """

    layer: str
    reader: str
    text: str
    kinds: list[str] = field(default_factory=list)
    kind: str = "reader"
    asked_by_probe: bool = False

    @property
    def gate(self) -> bool:
        return self.kind == "gate"

    @property
    def overrides(self) -> bool:
        """The compiler's last word on the line, whatever claimed it first."""
        return self.kind in ("gate", "composite")


@dataclass
class Verdict:
    accepted: bool
    layer: str
    reason: str
    kinds: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.layer == "blank":
            return "blank (reminder text only)"
        if self.accepted:
            return f"accepted ({', '.join(self.kinds) or self.reason})"
        if self.layer == "not reached":
            return f"not reached: {self.reason}"
        return f"refused at {self.layer}: {self.reason}"


@dataclass
class LineReport:
    index: int
    text: str
    printed: str | None
    blank: bool
    consulted: list[dict]
    claims: list[Finding]
    refusals: list[Finding]
    grammar: GrammarVerdict
    condition: str | None
    hook: str | None
    handlers: list[dict]
    hollow: bool
    support: str
    verdict: Verdict
    round: int
    removed: list[str]
    notes: list[str] = field(default_factory=list)
    #: The parsed trees (``--ast``, :func:`attach_ast`): the whole line, then
    #: each sentence asked alone when it has more than one.
    ast: list[dict] | None = None


@dataclass
class UnitReport:
    name: str
    type_line: str
    primary_type: str
    origin: str
    supported: bool
    reason: str
    program: Any
    hooks: list[str]
    card_level: list[str]
    lines: list[LineReport]
    drift: list[str]
    trace_matches_cache: bool | None

    @property
    def refused_lines(self) -> list[LineReport]:
        return [line for line in self.lines
                if not line.verdict.accepted and line.verdict.layer != "blank"]


def _walk_kinds(instruction: OracleInstruction, seen: list[str]) -> None:
    if instruction.kind not in seen:
        seen.append(instruction.kind)
    for value in instruction.payload.values():
        items = value if isinstance(value, (tuple, list)) else (value,)
        for item in items:
            if isinstance(item, OracleInstruction):
                _walk_kinds(item, seen)
            elif isinstance(item, dict) and isinstance(item.get("instruction"), OracleInstruction):
                _walk_kinds(item["instruction"], seen)


def _handler_rows(instructions: list[OracleInstruction]) -> list[dict]:
    kinds: list[str] = []
    for instruction in instructions:
        _walk_kinds(instruction, kinds)
    return [
        {"kind": kind, "handler": kind in EFFECT_HANDLERS,
         "category": INSTRUCTION_CATEGORIES.get(kind)}
        for kind in kinds
    ]


def _whole_text_verdicts(events, lines, claims, refusals) -> None:
    """Spread the answers of the readers handed the whole text over the lines
    each names — what the compiler does with them, read off their answers."""
    def claim(i, finding):
        if i is not None:
            claims.setdefault(i, []).append(finding)

    def refuse(i, finding):
        if i is not None:
            refusals.setdefault(i, []).append(finding)

    aliases = [set(_aliases(line, "")) for line in lines]
    for event in events:
        if event.depth != 0 or event.raised:
            continue
        name, result = event.reader.name, event.result
        if name == "_modal_options" and result:
            first = None
            for mode in result:
                i = _match_line(mode.label, lines, aliases)
                first = i if first is None else first
                kinds = [mode.instruction.kind] if mode.instruction is not None else []
                if mode.instruction is not None:
                    claim(i, Finding("modal spell", name, "a mode", kinds))
                else:
                    refuse(i, Finding("modal spell", name, "a mode nothing reads",
                                      kind="reader"))
            if first is not None and first > 0:
                claim(first - 1, Finding("modal spell", name, "the modal head"))
        elif name == "_modal_trigger_ability" and isinstance(result, tuple):
            head = event.line
            if head is not None:
                for offset in range(1, result[1] + 1):
                    if head + offset < len(lines):
                        claim(head + offset, Finding("modal trigger", name, "a mode of the trigger"))
        elif name == "_grammar_static_coeffects" and result:
            for child in events:
                if (child.parent is not None and events[child.parent] is event
                        and child.reader.name == "compile_line" and child.result.usable
                        and type(child.result.node).__name__ == "DerivedLine"):
                    kinds = [instruction.kind for instruction in child.result.instructions]
                    claim(child.line, Finding("derived co-effects", name, "a board-wide co-effect", kinds))
        elif name == "unclaimed_aura_lines":
            unclaimed = set(result or ())
            for i, line in enumerate(lines):
                if normalize_creature_line(line) in unclaimed:
                    refuse(i, Finding("Aura/Equipment gate", name,
                                      "no Aura or Equipment reader claims the line",
                                      kind="composite"))
                elif normalize_creature_line(line):
                    claim(i, Finding("Aura/Equipment gate", name, "claimed by the attached-effect readers"))
        elif name == "_unread_land_text":
            unread = result
            stop = None
            if unread is not None:
                stop = _match_line(unread, lines, aliases)
                refuse(stop, Finding("land static gate", name,
                                     "no static-text reader claims the line",
                                     kind="composite"))
            for child in events:
                if (child.parent is None or events[child.parent] is not event
                        or child.line is None or child.line == stop):
                    continue
                verdict, summary = answer(child)
                if verdict == CLAIM:
                    claim(child.line, Finding(child.reader.layer, child.reader.name, summary))


def _equipment_gate(events, lines, program, refusals) -> None:
    """The Equipment gate's refusal of an equip line the rewrite left alone.

    An "Equip" line the rewrite could not turn into its activated ability
    reaches the compiler as printed, and the gate refuses the card naming it
    — the gate's own terms, read off its answers: the program's reason names
    the line, and ``is_equip_line`` said yes to it."""
    if program.supported:
        return
    named = _names_line(program.reason, lines)
    if named is None:
        return
    if any(event.reader.name == "is_equip_line" and event.result is True
           and _subject(event) == lines[named] for event in events):
        refusals.setdefault(named, []).append(Finding(
            "Equipment gate", "is_equip_line",
            "an equip line the rewrite did not turn into an activated ability",
            kind="gate"))


def _program_abilities(program, line: str):
    for ability in (*program.activated_abilities, *program.triggered_abilities):
        source = (ability.source_line or "").strip()
        if source == line or source.startswith(line + " •"):
            yield ability


def _names_line(reason: str, lines: list[str]) -> int | None:
    """The line a refusal reason quotes, if it quotes one.

    The compiler's reasons quote a line whole, after a colon and to the end of
    the reason (or of one face's half of it): "creature text too complex:
    '<line>'", "unimplemented aura effect: <normalized line>". Anchored on that,
    so a short line ("Flying") is not found inside some other sentence."""
    def quoted(text: str) -> bool:
        return re.search(
            r": ['\"]?" + re.escape(text) + r"\.?['\"]?(?:;|$)", reason
        ) is not None

    hits = []
    for i, line in enumerate(lines):
        label = " ".join(line.lstrip("•").split()).rstrip(".")
        spellings = {line, repr(line)[1:-1], normalize_creature_line(line), label} - {""}
        if any(quoted(text) for text in spellings):
            hits.append(i)
    return max(hits, key=lambda i: len(lines[i])) if hits else None


def _grammar_said(grammar: GrammarVerdict) -> str:
    if grammar.parse_error:
        return f"grammar: {grammar.parse_error}"
    if grammar.lowering_error:
        return f"grammar lowering: {grammar.lowering_error}"
    if grammar.kinds:
        return f"grammar: lowers it to {grammar.kinds} as a {grammar.node}"
    return f"grammar: parsed {grammar.node}"


def _site(line: LineReport, unit: CardDefinition, program) -> tuple[str, str]:
    """Where a refused line was refused, read off the layers' own verdicts in
    the order the compiler meets them on that line's path."""
    for refusal in line.refusals:
        if refusal.gate:
            return refusal.layer, refusal.text
    grammar = line.grammar
    for refusal in line.refusals:
        if refusal.kind == "composite":
            return refusal.layer, f"{refusal.text} ({_grammar_said(grammar)})"
    if line.text.startswith("•") and not line.claims and not line.refusals:
        return ("modal head",
                "a mode is read only through the head above it, and that head was not "
                "read as one (see the line above)")
    if grammar.parse_error:
        return "grammar", grammar.parse_error
    if grammar.lowering_error:
        return "grammar (lowering)", grammar.lowering_error
    if grammar.node == "TriggeredAbilityNode" and line.condition is None:
        head = normalize_creature_line(line.text).split(",")[0]
        return ("trigger-condition table",
                f"no row reads {head!r} (the grammar reads the line as a trigger)")
    kinds = grammar.kinds
    for refusal in line.refusals:
        return (refusal.layer,
                f"{refusal.text} — though the grammar reads the line ({grammar.node}, {kinds})")
    if grammar.node == "RegistryLine":
        return ("text-keyed registry",
                f"the grammar leaves the line to a text-keyed registry, and nothing on the "
                f"{unit.primary_type} path claims it")
    if grammar.node == "KeywordLine":
        return "keyword table", "a keyword line, and not one IMPLEMENTED_KEYWORDS admits"
    if grammar.usable:
        return (f"{unit.primary_type} line reader",
                f"the grammar lowers it to {kinds} as a {grammar.node}, and no reader on "
                f"the {unit.primary_type} path takes that")
    if grammar.parsed:
        off = sorted(set(grammar.categories) - GRAMMAR_CATEGORIES)
        return "grammar categories", f"lowers to {grammar.categories}; not switched on: {off}"
    return "support gate", program.reason


def _consulted(events: list[Event], index: int) -> list[dict]:
    rows, seen = [], set()
    for event in events:
        if event.line != index:
            continue
        verdict, summary = answer(event)
        subject = _subject(event) or ""
        key = (event.reader.name, subject, summary, event.asked_by_probe)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "depth": event.depth, "layer": event.reader.layer, "reader": event.reader.name,
            "verdict": verdict, "summary": summary, "asked_by_probe": event.asked_by_probe,
            "text": subject,
        })
    return rows


_NONCREATURE = frozenset({"artifact", "enchantment", "instant", "sorcery"})


def _ask_outside_the_compile(unit: CardDefinition, lines: list[str], indexes: list[int]) -> list[Event]:
    """The noncreature fallback (the module docstring's second point): each
    of *indexes* asked of the creature loop's two cost tables and of the land
    path's static-text gate, recorded like the compile's own calls."""
    from engine import alternative_costs, cast_costs, line_classification

    recorder = _Recorder()
    recorder.asked_by_probe = True
    with observing(), _recording(recorder), each_line_parsed_once():
        # Looked up inside the session, so what is called is the tracer.
        for i in indexes:
            cast_costs.cast_cost_claims_line(lines[i])
            alternative_costs.alternative_cost_claims_line(lines[i])
            line_classification._unread_land_text(lines[i], unit.name)
    return recorder.events


def _post_claims(events: list[Event], lines: list[str], unit: CardDefinition):
    """The claims the noncreature fallback found, by line."""
    aliases = [_aliases(line, unit.name) for line in lines]
    claims: dict[int, list[Finding]] = {}
    for event in events:
        if event.depth != 0 or event.raised:
            continue
        index = _match_line(event.args[0], lines, aliases)
        if index is None:
            continue
        name = event.reader.name
        if name == "_unread_land_text":
            if event.result is not None:
                continue
            inner = [
                f"{answer(child)[1]} ({child.reader.layer})" for child in events
                if child.parent is not None and events[child.parent] is event
                and answer(child)[0] == CLAIM
            ]
            claims.setdefault(index, []).append(Finding(
                "static text, read outside the compile", name,
                "; ".join(inner) or "read", asked_by_probe=True))
        elif event.result:
            claims.setdefault(index, []).append(Finding(
                f"{event.reader.layer}, read outside the compile", name, "claims it",
                asked_by_probe=True))
    return claims


def _judge_round(unit, program, events, lines, full_index, judged, round_number,
                 removed, final_reports):
    """Verdicts for the lines this compile read that no earlier one did."""
    _attribute(events, lines, unit.name)
    claims: dict[int, list[Finding]] = {}
    refusals: dict[int, list[Finding]] = {}
    for event in events:
        if event.line is None or event.asked_by_probe:
            continue
        if event.depth != 0 or event.reader.role not in ("line", "gate"):
            continue
        verdict, summary = answer(event)
        # A modal trigger's refusal names its own defect (a condition the
        # table cannot read, a mode that targets undescribably), as a gate's does.
        own_terms = event.reader.role == "gate" or event.reader.name == "_modal_trigger_ability"
        finding = Finding(event.reader.layer, event.reader.name, summary,
                          [i.kind for i in _instructions_in(event.result)] if verdict == CLAIM else [],
                          kind="gate" if own_terms else "reader")
        if verdict == CLAIM:
            claims.setdefault(event.line, []).append(finding)
        elif verdict == REFUSE:
            refusals.setdefault(event.line, []).append(finding)
    _whole_text_verdicts(events, lines, claims, refusals)
    _equipment_gate(events, lines, program, refusals)
    # Read means a line loop handed the line to a reader. A whole-card gate
    # that passed every line read none of them (it stands before the loops).
    consulted = {event.line for event in events
                 if event.line is not None and event.depth == 0
                 and event.reader.role == "line" and not event.asked_by_probe}
    consulted |= set(claims) | set(refusals)

    asked: list[Event] = []
    if unit.primary_type in _NONCREATURE:
        # Only a line nothing claimed *and* nothing refused: a reader that
        # refused a line (an activated ability whose effect it cannot read)
        # has said what the compile thinks of it.
        pending = [i for i in sorted(consulted) if not claims.get(i)
                   and not refusals.get(i) and normalize_creature_line(lines[i])]
        if pending:
            asked = _ask_outside_the_compile(unit, lines, pending)
            for i, found in _post_claims(asked, lines, unit).items():
                claims.setdefault(i, []).extend(found)
            _attribute(asked, lines, unit.name)

    newly = []
    for i, line in enumerate(lines):
        target = full_index.get(i)
        if target is None or target in judged or i not in consulted:
            continue
        judged.add(target)
        newly.append(target)
        report = _line_report(
            unit, program, line, i, lines, events + asked, claims.get(i, []),
            refusals.get(i, []), round_number, removed,
        )
        report.index = target + 1
        final_reports[target] = report
    return newly


def _line_report(unit, program, line, i, lines, events, claims, refusals, round_number, removed):
    texts = [_subject(e) for e in events if e.line == i and e.reader.name == "compile_line"]
    grammar_text = line if line in texts or not texts else texts[0]
    grammar = grammar_verdict(grammar_text, unit.name)
    # The trigger table's answer as the compile got it, when the compile asked.
    asked = [e.result[0] for e in events if e.line == i and not e.raised
             and e.reader.name == "trigger_condition_of_line" and _subject(e) == line]
    condition = (asked[0] if asked else
                 importlib.import_module("engine.trigger_conditions")
                 .trigger_condition_of_line(line, unit.name)[0])
    hook = card_hooks.card_line_instruction(unit.name, normalize_creature_line(line))
    blank = not normalize_creature_line(line)
    instructions: list[OracleInstruction] = []
    for event in events:
        if (event.line == i and event.depth == 0 and not event.asked_by_probe
                and event.reader.role == "line" and answer(event)[0] == CLAIM):
            instructions.extend(_instructions_in(event.result))
    abilities = list(_program_abilities(program, line))
    hollow = any(a.supported and a.instruction is None for a in abilities)
    dead = [a for a in abilities if not a.supported]
    named = (not program.supported) and _names_line(program.reason, lines) == i
    support = ("supported" if program.supported else
               f"unsupported — {program.reason}" + (" (names this line)" if named else ""))
    if round_number > 1:
        support = f"without the removed lines: {support}"
    report = LineReport(
        index=i + 1, text=line, printed=None, blank=blank,
        consulted=_consulted(events, i), claims=claims, refusals=refusals,
        grammar=grammar,
        condition=condition.kind if condition is not None else None,
        hook=f"{hook.instruction.kind} ({hook.effect_kind})" if hook is not None else None,
        handlers=_handler_rows(instructions), hollow=hollow, support=support,
        verdict=Verdict(False, "", ""), round=round_number, removed=list(removed),
    )
    if (unit.primary_type in _NONCREATURE and not claims and not refusals
            and grammar.node == "RegistryLine"):
        # The grammar's own claim on a registry's behalf: zero instructions,
        # because the registry reads the printed text where it acts.
        claims = [Finding(f"text-keyed registry ({grammar.registry})", "compile_line",
                          "the grammar hands the line to this registry", asked_by_probe=True)]
        report.claims = claims
    overridden = any(f.overrides for f in refusals)
    compiled = [f for f in claims if not f.asked_by_probe]
    if blank:
        report.verdict = Verdict(True, "blank", "reminder text only")
    elif not overridden and not dead and (compiled or (claims and not refusals)):
        kinds = []
        for finding in claims:
            for kind in finding.kinds:
                if kind not in kinds:
                    kinds.append(kind)
        first = claims[0]
        reason = f"{first.layer}" + (" — hollow: no instruction" if hollow else "")
        report.verdict = Verdict(True, first.layer, reason, kinds)
        if grammar.node == "TriggeredAbilityNode" and condition is None and not abilities:
            report.notes.append(
                "the grammar reads a trigger here and the trigger-condition table has no "
                "row for it, so no triggered ability was built: the line is carried as "
                "an instruction, and nothing fires it as a trigger")
    else:
        if dead and not refusals:
            report.refusals.append(Finding(
                "program", "OracleProgram", "the program carries this ability unsupported"))
        layer, reason = _site(report, unit, program)
        report.verdict = Verdict(False, layer, reason)
        if program.supported:
            report.notes.append(
                "the card is supported on its other lines, so nothing refused it: this "
                "is a line no reader the compile consults claims. A channel outside "
                "the compile may still carry it (scripts/parse_coverage.py's CHANNELS, "
                "a card hook) — or it is a sentence the card silently drops")
    return report


def _printed_origins(unit: CardDefinition, printed: list[str], lines: list[str]) -> dict[int, int]:
    """Which printed line each read line was rewritten from: the one whose
    removal makes it vanish from ``expand_ability_lines``'s output."""
    from collections import Counter

    full = Counter(lines)
    origin: dict[int, int] = {}
    for p in range(len(printed)):
        reduced = Counter(_read_lines("\n".join(printed[:p] + printed[p + 1:]), unit))
        for i, line in enumerate(lines):
            if i not in origin and reduced[line] < full[line]:
                origin[i] = p
    return origin


def _align(reduced: list[str], lines: list[str], live: list[int]) -> dict[int, int]:
    """Reduced-text line index -> full line index, in order."""
    mapping: dict[int, int] = {}
    cursor = 0
    for r, line in enumerate(reduced):
        for k in range(cursor, len(live)):
            if lines[live[k]] == line:
                mapping[r] = live[k]
                cursor = k + 1
                break
    return mapping


def probe_unit(unit: CardDefinition, origin: str = "") -> UnitReport:
    """Every read line of one compilation unit, each with its layers and verdict."""
    with observing() as missing:
        cached = oracle.compile_card_oracle(unit)
        printed = (unit.oracle_text or "").split("\n")
        lines = _read_lines(unit.oracle_text, unit)
        origins = _printed_origins(unit, printed, lines)
        reports: dict[int, LineReport] = {}
        judged: set[int] = set()
        removed: list[int] = []
        first_program = None
        matches = None
        card_level: list[str] = []
        for round_number in range(1, len(printed) + 2):
            text = "\n".join(p for k, p in enumerate(printed) if k not in removed)
            current = unit if not removed else dataclasses.replace(unit, oracle_text=text)
            program, events = traced_compile(current)
            reduced_lines = _read_lines(text, unit)
            live = [i for i in range(len(lines)) if origins.get(i) not in removed]
            mapping = _align(reduced_lines, lines, live)
            removed_text = [printed[k] for k in removed]
            newly = _judge_round(unit, program, events, reduced_lines, mapping,
                                 judged, round_number, removed_text, reports)
            if first_program is None:
                first_program = program
                matches = program == cached
                # A gate's refusal that names no line is the card's.
                card_level = sorted({
                    f"{e.reader.layer}: {answer(e)[1]}" for e in events
                    if e.depth == 0 and e.line is None and e.reader.role == "gate"
                    and e.result is not None
                })
            if len(judged) == len(lines) or program.supported:
                break
            culprit = _culprit(program, reduced_lines, mapping, reports, newly)
            if culprit is None or origins.get(culprit) is None or origins[culprit] in removed:
                break
            removed.append(origins[culprit])
        program = first_program
        for i, line in enumerate(lines):
            if i in reports:
                if line != _printed_line(printed, origins.get(i)):
                    reports[i].printed = _printed_line(printed, origins.get(i))
                continue
            report = _line_report(unit, program, line, i, lines, [], [], [], 0, [])
            if not report.blank:
                report.verdict = Verdict(
                    False, "not reached",
                    f"the compiler refused the card before reading it ({program.reason})")
            reports[i] = report
    hooks = sorted(
        attribute for attribute in dir(card_hooks)
        if not attribute.startswith("_")
        and isinstance(getattr(card_hooks, attribute), (dict, set, frozenset))
        and unit.name in getattr(card_hooks, attribute)
    )
    return UnitReport(
        name=unit.name, type_line=unit.type_line, primary_type=unit.primary_type,
        origin=origin, supported=program.supported, reason=program.reason,
        program=program, hooks=hooks, card_level=card_level,
        lines=[reports[i] for i in range(len(lines))], drift=list(missing),
        trace_matches_cache=matches,
    )


def _printed_line(printed: list[str], index: int | None) -> str | None:
    return printed[index].strip() if index is not None else None


def _culprit(program, reduced_lines, mapping, reports, newly) -> int | None:
    """The line that stopped this compile, as a full line index."""
    named = _names_line(program.reason, reduced_lines) if not program.supported else None
    if named is not None and mapping.get(named) in newly:
        return mapping[named]
    refused = [i for i in newly if not reports[i].verdict.accepted
               and reports[i].verdict.layer != "blank"]
    gated = [i for i in refused if any(f.overrides for f in reports[i].refusals)]
    if gated:
        return gated[0]
    return refused[-1] if refused else None


def probe_card(card: CardDefinition) -> list[UnitReport]:
    """One report per compilation unit: each face of a split card, or the card."""
    label = origin_label(card)
    return [probe_unit(unit, label) for unit in (face_cards(card) or (card,))]


def census_site(line: LineReport) -> tuple[str, str]:
    """``(status, detail)`` for a census row: ``refused`` with the site, or
    ``unlowered`` with the lowering error, or ``clean``.

    A grammar refusal keeps its parse error verbatim as the detail — the key
    the refusal rollup has always grouped by — and every other layer is named
    in front of its reason, so a table-keyed refusal can no longer pass for a
    production. A line the compiler never reached falls back to the grammar's
    verdict on it."""
    verdict = line.verdict
    if verdict.accepted:
        return "clean", ""
    if verdict.layer == "not reached":
        if line.grammar.parse_error:
            return "refused", line.grammar.parse_error
        if line.grammar.lowering_error:
            return "unlowered", line.grammar.lowering_error
        return "clean", ""
    if verdict.layer == "grammar":
        return "refused", verdict.reason
    if verdict.layer == "grammar (lowering)":
        return "unlowered", verdict.reason
    return "refused", f"{verdict.layer}: {verdict.reason}"


# ---------------------------------------------------------------------------
# Choosing the card
# ---------------------------------------------------------------------------

def origin_label(card: CardDefinition) -> str:
    code = (card.set_code or "").upper()
    if not code:
        return "invented"
    measured = {c.upper() for c in manifest_measured_codes()}
    return f"{code} (measured, not shipped)" if code in measured else code


def invented_card(lines: list[str], type_line: str | None, name: str) -> CardDefinition:
    """A card printing *lines*, for a raw line probe. With no *type_line*, a
    sorcery when the grammar reads the first line as a spell's effect and a
    creature otherwise — the two loops that refuse a line by themselves."""
    text = "\n".join(lines)
    if type_line is None:
        first = compile_line(lines[0], card_name=name) if lines else None
        spell = first is not None and type(first.node).__name__ == "SpellEffectLine"
        type_line = "Sorcery" if spell else "Creature — Shapeshifter"
    raw = {"name": name, "type_line": type_line, "oracle_text": text}
    creature = "Creature" in type_line
    return CardDefinition(
        name=name, mana_cost="{3}", cmc=3.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=(), produced_mana=(), raw=raw,
        power="2" if creature else None, toughness="2" if creature else None,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _furthest_lines(furthest: Furthest, indent: str) -> list[str]:
    out = [f"{indent}furthest: token {furthest.token} of {furthest.total}; "
           f"unread: {furthest.unread[:110]!r}"]
    out += [f"{indent}  {path}:{lineno} {name}" for path, lineno, name in furthest.frames[-6:]]
    return out


def _refusal_lines(refusal: LoweringRefusal | None, indent: str) -> list[str]:
    if refusal is None:
        return []
    out = [f"{indent}raised at {refusal.site}"]
    if len(refusal.chain) > 1:
        out.append(f"{indent}innermost of {len(refusal.chain)} chained: {refusal.message!r}")
    via = refusal.frames[:-1][-6:]
    if via:
        out.append(f"{indent}via:")
        out += [f"{indent}  {path}:{lineno} {name}" for path, lineno, name in via]
    return out


def _ast_reading_lines(reading: dict, indent: str) -> list[str]:
    if reading["blank"]:
        return [f"{indent}blank (reminder text only)"]
    if reading["parse_error"]:
        return [f"{indent}parse error: {reading['parse_error']}"]
    out = ast_lines(reading["ast"], indent)
    if reading["alone"]:
        if reading["lowering_error"]:
            out.append(f"{indent}lowering: error: {reading['lowering_error']}")
            lowering = reading["lowering"]
            if lowering is not None:
                out += _refusal_lines(LoweringRefusal(
                    lowering["site"], lowering["message"], lowering["chain"],
                    [tuple(frame) for frame in lowering["frames"]]), indent + "  ")
        else:
            out.append(f"{indent}lowering: {reading['kinds']}")
    return out


def _ast_block(line: "LineReport") -> list[str]:
    out = []
    readings = line.ast or []
    parts = [reading for reading in readings if reading["alone"]]
    for reading in readings:
        if not reading["alone"]:
            asked = f" (of {reading['text']!r})" if reading["text"] != line.text else ""
            out.append(f"      ast{asked}:")
        else:
            number = parts.index(reading) + 1
            out.append(f"      sentence {number} of {len(parts)}, asked alone "
                       f"(out of its context: a lead): {reading['text']!r}")
        out += _ast_reading_lines(reading, "        ")
    return out


def render_text(reports: list[UnitReport], full: bool = False) -> str:
    out: list[str] = []
    for unit in reports:
        out.append(f"{unit.name} — {unit.type_line} — {unit.origin}")
        out.append("program: " + ("supported" if unit.supported else "UNSUPPORTED")
                   + f" — {unit.reason}")
        if unit.drift:
            out.append(f"DRIFT: readers this probe observes no longer exist: {unit.drift}")
        if unit.trace_matches_cache is False:
            out.append("DRIFT: the traced compile differs from the cached program")
        out.append("card hooks: " + (", ".join(unit.hooks) if unit.hooks else "none"))
        for note in unit.card_level:
            out.append(f"card-level: {note}")
        if full:
            program = unit.program
            for instruction in program.instructions:
                out.append(f"  instruction: {instruction!r}"[:3000])
            for ability in program.activated_abilities:
                out.append(f"  activated: {ability!r}"[:3000])
            for ability in program.triggered_abilities:
                out.append(f"  triggered: {ability!r}"[:3000])
            for line in program.static_lines:
                out.append(f"  static: {line}")
            for mode in program.modes:
                out.append(f"  mode: {mode!r}"[:3000])
        for line in unit.lines:
            out.append("")
            out.append(f"  [{line.index}] {line.text}")
            if line.printed:
                out.append(f"      rewritten from: {line.printed}")
            if line.round > 1:
                out.append(f"      read with these printed lines removed: {line.removed}")
            if line.blank:
                out.append(f"      verdict: {line.verdict}")
                continue
            if line.consulted:
                out.append("      consulted, in order:")
                for row in line.consulted[:40]:
                    mark = " [asked by the probe]" if row["asked_by_probe"] else ""
                    out.append(f"        {'  ' * row['depth']}{row['layer']} "
                               f"({row['reader']}): {row['summary']}{mark}")
                if len(line.consulted) > 40:
                    out.append(f"        … {len(line.consulted) - 40} more")
            grammar = line.grammar
            if grammar.parse_error:
                out.append(f"      grammar: parse error: {grammar.parse_error}")
                if grammar.furthest is not None:
                    out += _furthest_lines(grammar.furthest, "        ")
            else:
                out.append(f"      grammar: parsed {grammar.node}"
                           + (f" (asked of {grammar.text!r})" if grammar.text != line.text else ""))
                if full and grammar.node_repr:
                    out.append(f"        node: {grammar.node_repr[:3000]}")
                if grammar.lowering_error:
                    out.append(f"      lowering: error: {grammar.lowering_error}")
                    out += _refusal_lines(grammar.lowering, "        ")
                else:
                    usable = "usable" if grammar.usable else "not usable"
                    out.append(f"      lowering: {grammar.kinds} {grammar.categories} ({usable})")
            if line.ast:
                out += _ast_block(line)
            out.append("      trigger table: "
                       + (line.condition or "no condition row (not a trigger to it)"))
            out.append("      card hook: " + (line.hook or "no CARD_LINE_INSTRUCTIONS entry"))
            if line.handlers:
                out.append("      handlers: " + "; ".join(
                    f"{row['kind']} {'has a handler' if row['handler'] else 'NO handler'}"
                    f" ({row['category'] or 'no category'})" for row in line.handlers))
            if line.hollow:
                out.append("      hollow: a supported ability with no instruction behind it")
            out.append(f"      support gate: {line.support}")
            out.append(f"      verdict: {line.verdict}")
            for note in line.notes:
                out.append(f"      note: {note}")
        out.append("")
    return "\n".join(out)


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def render_json(reports: list[UnitReport]) -> str:
    payload = []
    for unit in reports:
        record = _jsonable(dataclasses.replace(unit, program=None))
        del record["program"]
        for line in record["lines"]:
            line["verdict"]["text"] = None
        for report, line in zip(unit.lines, record["lines"]):
            line["verdict"]["text"] = str(report.verdict)
        payload.append(record)
    return json.dumps(payload, indent=1, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Why is this line refused? Every layer the compiler consults, with its verdict."
    )
    parser.add_argument("line", nargs="*",
                        help="raw printed line(s), compiled on one invented card")
    parser.add_argument("--card", metavar="NAME",
                        help="a card by name; looked up in the shipped and measured sets "
                             "unless --set/--all/--cards narrows the pool")
    parser.add_argument("--type", dest="type_line", metavar="TYPE_LINE",
                        help="the invented card's type line (default: Sorcery for a "
                             "spell-effect line, else Creature — Shapeshifter)")
    parser.add_argument("--name", default="Probe Card", help="the invented card's name")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument("--full", action="store_true",
                        help="print the program, grammar nodes and instruction payloads")
    parser.add_argument("--ast", action="store_true",
                        help="print each line's parsed tree, node by node with the fields "
                             "it sets, and each sentence of a longer line asked alone")
    add_set_argument(parser, default=None)
    return parser


def _find_card(parser, args) -> CardDefinition | None:
    from retrieve_oracle import retrieve_oracle_text

    selection = resolve_set(parser, args)
    named = args.set_code is not None or args.whole_pool or args.cards_path
    paths = selection.paths if named else manifest_set_paths(include_measured=True)
    card, candidates = retrieve_oracle_text(args.card, load_cards(paths))
    if card is None:
        if candidates:
            print("Several or close matches: " + "; ".join(candidates), file=sys.stderr)
        else:
            print(f"No card named {args.card!r} in {selection.label if named else 'either manifest role'}.",
                  file=sys.stderr)
    return card


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.card) == bool(args.line):
        parser.error("name a card with --card, or give raw line(s) — one or the other")
    if args.card:
        card = _find_card(parser, args)
        if card is None:
            return 1
        reports = probe_card(card)
    else:
        reports = probe_card(invented_card(args.line, args.type_line, args.name))
    if args.ast:
        attach_ast(reports)
    print(render_json(reports) if args.json else render_text(reports, full=args.full))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
