"""Whole printed lines that are **continuous** abilities (CR 613).

The parse mirror of ``engine/grammar/statics.py``, split out of ``parser.py``
at the 1,000-line guard the round Homarid's leading-order condition landed —
and the file had been sitting on 995 of it, so the boundary was already there
to be found. It is the one ``parser.py`` already drew in its own shape: every
production here reads a line the sentence loop would fail, because the line's
*frame* is a condition rather than a verb, and each one hands back an
``ast.StaticAbilityNode`` rather than a step.

**The name.** The mirror's word is ``statics``, and that path is taken one
directory up by the lowering half — so this is ``OracleProgram.static_lines``'
own word for the same thing rather than a new one. Which is also what the
module is: what these productions produce is exactly what the compiler records
under that name.

Sits between ``riders`` and ``costs`` in the layer order: it reads whole
sentences (``statements``), conditions and one shared phrase fragment, and
nothing above it reaches back.
"""

from __future__ import annotations

from dataclasses import replace

from . import ast
from .conditions import _parse_condition
from .errors import GrammarError
from .phrases import accept_member_state_clause
from .statements import parse_statement
from .stream import TokenStream


def _looks_static(statement: ast.Statement) -> bool:
    """A continuous effect with no duration on a non-targeted subject is a
    static ability.

    A *conjunction* of them is one too — "Other Goblins get +1/+1 and have
    mountainwalk" is a single static ability with two halves, not a spell
    effect. It reached ``SpellEffectLine`` only because this predicate looked at
    one effect at a time, which put the lord lines on a different lowering path
    from the anthem lines that say exactly the same kind of thing.
    """
    if isinstance(statement, ast.Conjunction):
        return bool(statement.effects) and all(
            _looks_static(effect) for effect in statement.effects
        )
    if isinstance(statement, ast.Pump):
        return statement.duration.kind is None and (
            not isinstance(statement.subject, ast.TargetSpec)
            or statement.subject.quantifier not in ("target", "up_to")
        )
    if isinstance(statement, (ast.GainKeyword, ast.LoseKeyword)):
        return statement.duration.kind is None and (
            not isinstance(statement.subject, ast.TargetSpec)
            or statement.subject.quantifier not in ("target", "up_to")
        )
    return False


def _parse_turn_scoped_static_line(
    stream: TokenStream,
) -> ast.StaticAbilityNode | None:
    """``During your turn, <continuous effect>.`` / ``During turns other than
    yours, <continuous effect>.`` (Vibrating Sphere, CR 613 layer 7c.)

    The same shape :func:`_parse_static_condition_line` reads with the condition
    printed *last*, and it lands on the same node — so the two word orders
    cannot mean different things. What it is **not** is a duration: nothing
    resolves here, and the bonus is gone at the next untap step with nothing to
    undo (the distinction that function's docstring draws for "as long as").

    Deliberately narrowed to a **distributive** subject, and that narrowing is
    the ordering rule rather than a convenience: "During your turn, this
    creature has first strike" (Radha, Heart of Keld) is read by
    ``engine/static_bonuses.conditional_static_for``, a derivation table the
    grammar reaches only where every production refuses the line *in full*
    (``engine/grammar/derived.py``). A production that parsed that sentence and
    then refused in lowering would take the table's line away — parsed-but-
    unlowered is still parsed — so the refusal happens here, in the parse.
    """
    mark = stream.mark()
    if not stream.accept_word("during"):
        return None
    if stream.accept_phrase("your", "turn"):
        negated = False
    elif stream.accept_phrase("turns", "other", "than", "yours"):
        negated = True
    else:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    try:
        statement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if (
        not stream.exhausted
        or not _looks_static(statement)
        or _distributive_subject(statement) is None
    ):
        stream.reset(mark)
        return None
    return ast.StaticAbilityNode(statement, ast.TurnIsYours(negated=negated))


def _parse_leading_static_condition_line(
    stream: TokenStream,
) -> ast.StaticAbilityNode | None:
    """``As long as <counter count>, <continuous effect>.``

    "As long as there is exactly one tide counter on this creature, it gets
    -1/-1." (Homarid.) "As long as there are exactly three tide counters on
    this enchantment, all blue creatures get +2/+0." (Tidal Influence.) One
    sentence with the subject and the affected set changed, and the two land on
    the same node as :func:`_parse_static_condition_line`'s trailing word order
    — so which half of the line the condition was printed on cannot change what
    the ability means.

    **Restricted to the counter-count condition**, and the restriction is the
    ordering rule rather than a convenience. ``engine/static_bonuses.py`` reads
    this exact word order ("As long as you control a Swamp, this creature gets
    +1/+1") as a derivation table, which the grammar reaches only where every
    production refuses the line *in full* (``engine/grammar/derived.py``). A
    production that read every leading condition would parse those sentences
    and then refuse them in lowering — parsed-but-unlowered is still parsed —
    and take the table's lines away. The counter count is the one condition
    that table cannot read at all: it has no row for it, and its effect side is
    anchored on the literal subject "this creature ", which "it gets -1/-1"
    is not.
    """
    mark = stream.mark()
    if not stream.accept_phrase("as", "long", "as"):
        return None
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(condition, ast.SourceCounterCount):
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    try:
        statement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.exhausted or not _looks_static(statement):
        stream.reset(mark)
        return None
    return ast.StaticAbilityNode(statement, condition)


def _parse_static_condition_line(stream: TokenStream) -> ast.StaticAbilityNode | None:
    """``<continuous effect> as long as <condition>.`` (CR 613, Sedge Troll,
    Kird Ape, Giant Tortoise.)

    The condition lands on :class:`ast.StaticAbilityNode` rather than becoming
    an ``ast.Conditional``, and the distinction is the whole content of the
    sentence. A ``Conditional`` lowers to ``if_then``: tested once, and if it
    holds the effect happens and then stays. "As long as" says the bonus exists
    exactly while the condition does — it appears and disappears with the
    Swamp. Reading one as the other gives a Kird Ape that keeps +1/+2 after its
    Forest is destroyed.

    Nothing here lowers. ``lower_ability`` refuses every ``StaticAbilityNode``
    until the CR 613 layers engine exists (roadmap phase 6), and the engine
    keeps running these cards off the compiler's static-line path exactly as it
    did. What the production buys is a backlog that points at the right thing —
    the lines move out of "unconsumed text", which reads as a parser gap, into
    the phase they are actually waiting on — plus an AST for phase 6 to lower
    instead of a sentence to re-read.

    Every one of the three gates below can only *reduce* what this claims: an
    unmodelled condition, a token left over, or an effect that is not
    continuous all send the line back to the ordinary path untouched.
    """
    mark = stream.mark()
    try:
        statement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("as", "long", "as"):
        stream.reset(mark)
        return None
    # "…**as long as it's not attacking**" over a distributive subject
    # (Arcades Sabboth). Tried first, and only for that subject, because the two
    # readings of "it" differ: over "each creature you control" it is a member
    # of the set and the clause narrows the noun phrase, while over "this
    # creature" it is the source and the clause is an ordinary state condition
    # (Giant Tortoise), which `_parse_condition` below already reads. Folding it
    # into the filter is what keeps the answer per-creature — as a condition it
    # would be asked once, of the source.
    narrowed = _narrow_by_member_state(stream, statement)
    if narrowed is not None:
        stream.accept_punct(".")
        if stream.exhausted and _looks_static(narrowed):
            return ast.StaticAbilityNode(narrowed, None)
        stream.reset(mark)
        return None
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.exhausted or not _looks_static(statement):
        stream.reset(mark)
        return None
    # A fourth reducing gate, in the spirit of the three above: a condition
    # narrowed to "**of the chosen color**" (Jihad) reads a colour recorded on
    # the *source permanent* as it entered (CR 614.1c). Nothing a continuous
    # buff's condition is evaluated by can see that — the answer belongs to one
    # permanent's metadata, not to a board — and `engine/lord_buffs.py`
    # implements this exact sentence through `chosen_color_permanent`. So the
    # production declines the line rather than claiming it and refusing a layer
    # later, which is the one failure the derivation-table fallback cannot
    # recover from: `parse_line` reaches the tables only on a *parse* refusal.
    if getattr(getattr(condition, "filter", None), "chosen_color", False):
        stream.reset(mark)
        return None
    return ast.StaticAbilityNode(statement, condition)


def _distributive_subject(statement: ast.Statement) -> ast.TargetSpec | None:
    """The one ``all``/``each`` subject *statement* is about, or None.

    None for a conjunction whose halves disagree, for a targeted or singular
    subject, and for anything with no subject at all — every case where "it" in
    a trailing clause does not name a member of a described set.
    """
    effects = statement.effects if isinstance(statement, ast.Conjunction) else (statement,)
    if not effects:
        return None
    subjects = {getattr(effect, "subject", None) for effect in effects}
    if len(subjects) != 1:
        return None
    subject = subjects.pop()
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier not in ("all", "each"):
        return None
    return subject


def _narrow_by_member_state(
    stream: TokenStream, statement: ast.Statement
) -> ast.Statement | None:
    """*statement* with a trailing ``it's [not] <state>`` folded into its
    subject, or None when the clause is not there or the subject is not a set.

    Refuses when the noun phrase already states the field — "each attacking
    creature … as long as it's not attacking" describes nothing, and silently
    letting the later word win would be a set the card never printed.
    """
    subject = _distributive_subject(statement)
    if subject is None:
        return None
    state = accept_member_state_clause(stream)
    if state is None:
        return None
    field_name, value = state
    if getattr(subject.filter, field_name) is not None:
        return None
    narrowed = replace(
        subject, filter=replace(subject.filter, **{field_name: value})
    )
    effects = statement.effects if isinstance(statement, ast.Conjunction) else (statement,)
    rebuilt = tuple(replace(effect, subject=narrowed) for effect in effects)
    return ast.Conjunction(rebuilt) if isinstance(statement, ast.Conjunction) else rebuilt[0]
