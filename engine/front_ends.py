"""Where the compiler's two front ends meet: the instruction one line reads to.

:func:`_line_instruction` reads a line through the grammar
(``engine/grammar/``), then through the name-keyed card hooks
(``card_hooks.CARD_LINE_INSTRUCTIONS``), and there is no third — a line
neither claims has no instruction, and its card is reported unsupported naming
the clause. ``engine/oracle.py``'s docstring has why that order is the whole
of the precedence.

The two are kept as two functions on purpose (:func:`_grammar_instruction`,
:func:`_card_hook_instruction`): ``tests/engine/test_front_end_safety.py``
stubs the grammar's and leaves the hooks standing.
:func:`_grammar_static_coeffects` is the grammar's other output — the
board-wide statics a derivation table reads off a line, collected after the
per-line pass — and :func:`_is_ability_line` is the question both front ends
need asked of a spell's line: is it an ability rather than an effect the
spell's resolution carries out?

Split out of ``engine/oracle.py`` at the 2,000-line cap. Every line reader
(``ability_lines``, ``line_classification``) asks here, and so does the
compiler for a spell's own lines.
"""

from __future__ import annotations

from .oracle_types import OracleInstruction
from .effect_labels import activated_label, triggered_label
from .grammar import ast as grammar_ast, compile_line as compile_grammar_line
from .line_normalization import normalize_creature_line
from .trigger_conditions import _parse_trigger_condition


# ---------------------------------------------------------------------------
# Grammar front end
# ---------------------------------------------------------------------------
#
# engine.grammar parses a line into a typed AST and lowers it to instructions.
# It runs on every line, and its result is used when every category it lowered
# to is switched on in engine.grammar.GRAMMAR_CATEGORIES. A line it refuses now
# reaches the name-keyed card hooks and then nothing — there is no legacy
# registry left underneath, so a category switched off is a card reported
# unsupported rather than a card quietly read by something else.


def _grammar_instruction(
    line: str,
    card_name: str | None,
    *,
    activated: bool = False,
    condition_kind: str | None = None,
    spell_line_only: bool = False,
    event: str | None = None,
) -> tuple[OracleInstruction, str] | None:
    """The grammar's ``(instruction, effect_kind)`` for one line, or None when
    the grammar does not claim it.

    *activated* and *condition_kind* name the **position** the line occupies —
    an ability's clause, a trigger's remainder (whose condition they carry), or
    a plain effect line. They decide only the ``effect_kind`` label
    (``engine/effect_labels.py``), never the instruction.

    A multi-instruction lowering is wrapped in a single ``sequence``
    instruction, so composition becomes first-class in the IR without changing
    the one-instruction shape that ParsedActivatedAbility,
    ParsedTriggeredAbility and the stack all currently assume.

    *spell_line_only* restricts the result to plain one-shot effect lines: the
    instructions of a card whose *resolution* carries them out. For an instant
    or sorcery the stack executes every non-``spell_pattern`` instruction in
    that list, so an activated ability's effect must never enter it — the spell
    would perform the ability on resolution.

    A permanent's list is a mirror rather than a program (see
    ``_noncreature_line_instructions``), so it does hold its abilities' effects,
    exactly as ``_parse_creature_program`` has always done for creatures.
    ``_resolve_card`` puts a permanent onto the battlefield and returns without
    reaching ``_apply_spell_text``, which is the only caller that executes this
    list — so the mirror cannot fire on cast.
    """
    compiled = compile_grammar_line(line, card_name=card_name, event=event)
    if not compiled.usable:
        return None
    if isinstance(compiled.node, grammar_ast.DerivedLine):
        # A derivation table's board-wide static is a *co-effect*, collected by
        # _grammar_static_coeffects after the per-line pass rather than here.
        # See that function for why the position matters.
        return None
    if spell_line_only and not isinstance(compiled.node, grammar_ast.SpellEffectLine):
        return None

    instructions = compiled.instructions
    if len(instructions) == 1:
        instruction = instructions[0]
    else:
        # CR 603.4's gate is attached by ``lower_ability`` to every *top-level*
        # instruction the line lowered to. Wrapping them makes the wrapper the
        # new top level, and both readers of the gate — the scan in
        # engine/phases/end_step.py and the resolution re-check in
        # engine/mixins/stack/resolution.py — read the top level. So a wrapper
        # that did not carry it put the condition on a payload nothing reads,
        # and the trigger was never enqueued at all: Sabertooth Mauler's "put a
        # +1/+1 counter on this creature **and untap it**" lowers to two
        # instructions and had never once fired, while reporting supported with
        # both halves correctly gated.
        #
        # Carried only when every step agrees, because the gate is the *line's*
        # and a wrapper cannot express two different ones. Steps that disagree
        # keep their own and the wrapper stays ungated, which is the behaviour
        # before this — no card in the pool lowers that shape.
        payload: dict = {"steps": instructions}
        gate = instructions[0].payload.get("intervening_if")
        if gate is not None and all(
            step.payload.get("intervening_if") == gate for step in instructions
        ):
            payload["intervening_if"] = gate
        instruction = OracleInstruction("sequence", "", payload)
    category = next(iter(sorted(compiled.categories)), "effect")
    if condition_kind is not None:
        effect_kind = triggered_label(instruction.kind, condition_kind)
    elif activated:
        effect_kind = activated_label(instruction.kind, category)
    else:
        effect_kind = "spell_pattern"
    return instruction, effect_kind


def _grammar_static_coeffects(
    oracle_text: str, card_name: str | None
) -> tuple[OracleInstruction, ...]:
    """Board-wide continuous statics a derivation table reads off one line.

    Kormus Bell's "All Swamps are 1/1 black creatures that are still lands.",
    Conversion's "All Mountains are Plains.", Jihad's conditional anthem — each
    derived in full by an engine table (``engine/grammar/derived.py`` names
    them) and each a *co-effect*: it coexists with whatever else the card says
    rather than being the effect the card's resolution carries out.

    Collected after the per-line pass, for the reason the deleted
    ``parse_static_coeffects`` also was: a card can state one of these alongside
    a clause that already claimed the card's instruction (Conversion's upkeep
    cost, Jihad's enter-choice and sacrifice trigger). Claiming it as an
    ordinary line instruction would *suppress* the reading of those other
    sentences, which is a different program, not a better one.
    """
    coeffects: list[OracleInstruction] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        compiled = compile_grammar_line(line, card_name=card_name)
        if compiled.usable and isinstance(compiled.node, grammar_ast.DerivedLine):
            coeffects.extend(compiled.instructions)
    return tuple(coeffects)


def _card_hook_instruction(
    line: str,
    card_name: str | None,
    *,
    spell_line_only: bool = False,
) -> tuple[OracleInstruction, str] | None:
    """The name-keyed reading of one line, for texts that are a single card.

    The second front end, consulted only where the grammar declined. Most of
    what ``engine/parsing/`` claimed is templating and belongs in a production;
    the rest is one card's sentence bound to a handler written for it, and those
    live in ``engine/card_hooks.py`` — the one file whose subject is a card's
    name (see CARD_LINE_INSTRUCTIONS for the entry bar).

    Kept out of :func:`_grammar_instruction` on purpose, so that stubbing the
    grammar (``tests/engine/test_front_end_safety.py``) leaves the hooks
    standing; folding them in would stub those too and the guard would report
    every hooked card as a loss.

    A hook carries its own ``effect_kind``, so it never consults
    ``engine/effect_labels.py`` and the position flags do not reach it.
    """
    from .card_hooks import card_line_instruction

    found = card_line_instruction(card_name, normalize_creature_line(line))
    if found is None:
        return None
    if spell_line_only and _is_ability_line(line):
        return None
    return found.instruction, found.effect_kind


def _is_ability_line(line: str) -> bool:
    """Whether *line* is an activated or triggered ability rather than a plain
    effect the card's resolution carries out.

    The same question ``spell_line_only`` asks of the grammar's node type, asked
    of the raw text — an ability's effect must never enter an instant's or
    sorcery's instruction list, or the spell would perform the ability when it
    resolves.
    """
    normalized = normalize_creature_line(line)
    if ":" in normalized:
        return True
    return _parse_trigger_condition(normalized)[0] is not None


def _line_instruction(
    line: str,
    card_name: str | None,
    *,
    activated: bool = False,
    condition_kind: str | None = None,
    spell_line_only: bool = False,
    event: str | None = None,
) -> tuple[OracleInstruction, str] | None:
    """The front ends that read one line, most general first: the grammar, then
    the name-keyed card hooks. There is no third — a line neither claims has no
    instruction, and the card is reported unsupported naming the clause."""
    found = _grammar_instruction(
        line, card_name,
        activated=activated, condition_kind=condition_kind,
        spell_line_only=spell_line_only, event=event,
    )
    if found is not None:
        return found
    return _card_hook_instruction(line, card_name, spell_line_only=spell_line_only)


def _reading(
    found: tuple[OracleInstruction, str] | None,
) -> tuple[OracleInstruction | None, str]:
    """A front end's reading, widened to the ``(instruction | None, label)`` shape
    the ability parsers return.

    This was ``_prefer_line_reading``, which took a *second* argument — the
    legacy registry's reading of the same line — and used it for two things: the
    instruction when no front end claimed the line, and the ``effect_kind``
    label whenever a legacy rule matched, even where the grammar had already
    produced the instruction. The first is gone with the registry; the second is
    ``engine/effect_labels.py``.
    """
    if found is None:
        return None, "unsupported"
    return found
