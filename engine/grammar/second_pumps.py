"""A **second pump** on the creatures the sentence in front of it reached.

"Target creature gets +1/+1 until end of turn. **That creature gets an
additional +4/+4** until end of turn unless any player pays {2}." (Wild
Might.) "Creatures you control gain first strike until end of turn. **If this
spell was kicked, they get +1/+1** until end of turn." (Savage Offensive.)
"Creatures you control get +1/+1 until end of turn. **If this spell was
kicked, Zombie creatures you control get an additional +2/+2** until end of
turn." (Strength of Night.) One question, asked three ways: may this pump be
handed the subject of the effect in front of it — the same chosen target, or
the same set, which CR 611.2c fixes for both effects in the one resolution —
and, where it prints "an additional", did a pump of those creatures come
first? ``_parse_gets`` admits that word only from a caller that has checked,
and both callers that pass it are here.

Pre-split out of ``pronouns`` at Torment's Phase 0, 38 lines under the
thousand-line guard with no Torment card known to land in it: the
shared-and-tight case, since every family that teaches "it" a new antecedent
reads through that module. The seam is that module's own growth. Since it last
took code (the possessives, at Nemesis' Phase 0, at 770 lines) three sets had
added one rider each — Prophecy the first below, Invasion the second,
Apocalypse the third with ``_narrows_filter`` beside it — 192 lines, and each
docstring below is written against the one before it. None of the three
reads the binding ``pronouns`` names as its method
(``rebinding.statement_bound_target``): the antecedent here is the step in
front's own ``subject``, and that may be a **sweep** — "they", "those
creatures" — which no binding covers, because a sweep chose nothing. The
third has no pronoun at all; what licenses it is containment in the set the
pump in front reached.

The plural "Each of them gets +1/+1 until end of turn" (Hope and Glory) stayed
in ``pronouns``. It too hands a bound subject to ``_parse_gets``, but its
antecedent is the several targets a sentence *chose*, read through
``rebinding.statement_bound_several_targets``: that module's binding in the
plural, between the two riders that read it in the singular. It used
to call :func:`_parse_pronoun_pump_rider` before reading its own words, which
was the one edge between the halves; the sentence loop
(``sequences._statements_from_sentences``) now asks the two in that order
itself, so no function in either module calls one in the other.

Beside ``pronouns`` in ``PARSE_LAYERS``, neither importing the other; both
take the statement grammar from ``statements`` and are driven from
``sequences``. No mirror name to reuse: a second pump is an ordinary ``Pump``
step — inside the ``ast.Conditional`` ``statement_dispatch`` lowers inline,
for the two behind a kicker — lowered by ``lowering/characteristics``'
``_lower_pump`` exactly as the first one is, so the lowering side has no
module this could be the twin of: ``conditional_instead``'s answer, for its
reason one node over.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .errors import GrammarError
from .effects import _parse_gets
from .references import parse_recipient
from .statements import _parse_condition, _parse_statement_body
from .stream import TokenStream
from .tolls import _accept_trailing_toll


def _parse_pronoun_pump_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """A **second pump** on what the pump before it named, read off that pump.

    "Target creature gets +1/+1 until end of turn. **That creature gets an
    additional +4/+4** until end of turn unless any player pays {2}." (Wild
    Might.) "Creatures you control get +0/+1 until end of turn. **They get an
    additional +0/+2** until end of turn unless any player pays {2}." (Rhystic
    Shield.) The pronoun names the previous pump's subject — one chosen target
    ("that creature", "it") or the set a sweep named ("they", "those
    creatures") — and the new pump is given that subject, a copy of it: the
    same ``targets`` payload, so CR 601.2c's one choice is asked once, and for
    a sweep the same noun phrase, which is the same set (CR 611.2c fixes both
    when the effects begin, in the same resolution).

    Read by the plural rider's method
    (``pronouns._parse_plural_pronoun_pump_rider``: the ordinary
    ``_parse_gets`` with the bound subject handed in), and only after a
    ``Pump``: "an additional" is what that antecedent licenses, and without it
    "they" is a player word. The trailing toll is read too, because a rider is
    parsed outside ``parse_statement`` and the toll is the whole point of these
    two cards.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.Pump) or not isinstance(last.subject, ast.TargetSpec):
        return None
    bound = last.subject
    mark = stream.mark()
    if bound.quantifier == "target" and bound.targeted:
        named = stream.accept_word("it") or stream.accept_phrase("that", "creature")
    elif bound.quantifier in ("all", "each"):
        named = stream.accept_word("they") or stream.accept_phrase("those", "creatures")
    else:
        return None
    if not named or not stream.at_word("gets", "get"):
        stream.reset(mark)
        return None
    try:
        pump = _parse_gets(stream, bound, additional=True)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(pump, ast.Pump):
        stream.reset(mark)
        return None
    return _accept_trailing_toll(_parse_statement_body, stream, pump) or pump


def _parse_conditional_set_pump_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``If <condition>, they get +N/+N [duration].`` after a sentence about a
    **set** of creatures.

    "Creatures you control gain first strike until end of turn. **If this
    spell was kicked, they get +1/+1 until end of turn.**" (Savage Offensive.)
    The plural pronoun names the set the sentence in front described — not a
    target, so none of the singular binders has anything to hand it, and read
    fresh "they" is a player word and the line refuses at "expected a
    subject".

    The pump is given that sentence's own subject, a copy of it: the same noun
    phrase is the same set, because both effects begin in the one resolution
    and CR 611.2c fixes each of them then. That is
    :func:`_parse_pronoun_pump_rider`'s argument for "They get an additional
    +0/+2" (Rhystic Shield), one antecedent kind over — that rider reads the
    pronoun after a *pump* and needs "an additional" to license it; this one
    reads it after a pump **or a keyword grant**, and what licenses it is the
    condition in front, which makes the sentence a second effect on the same
    creatures rather than a restatement of the first.

    Only a sweep ("all" / "each", untargeted) is an antecedent. After a target
    the pronoun is "it" / "that creature" and
    :func:`pronouns._parse_conditional_pronoun_grant_rider` and the "instead"
    pair own those sentences; a plural pronoun there would name several
    targets, which :func:`pronouns._parse_plural_pronoun_pump_rider` reads with
    its "each of".
    """
    last = steps[-1] if steps else None
    if not isinstance(last, (ast.GainKeyword, ast.Pump)):
        return None
    bound = last.subject
    if not (
        isinstance(bound, ast.TargetSpec)
        and bound.quantifier in ("all", "each")
        and not bound.targeted
    ):
        return None
    mark = stream.mark()
    if not stream.accept_word("if"):
        return None
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    named = stream.accept_word("they") or stream.accept_phrase("those", "creatures")
    if not named or not stream.at_word("gets", "get"):
        stream.reset(mark)
        return None
    try:
        pump = _parse_gets(stream, bound)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(pump, ast.Pump):
        stream.reset(mark)
        return None
    return ast.Conditional(condition, pump)


def _narrows_filter(wider: ast.ObjectFilter, narrower: ast.ObjectFilter) -> bool:
    """Whether every restriction *wider* prints, *narrower* prints too.

    Field by field: a field *wider* leaves at its default restricts nothing,
    and one it sets must be set to the same value on *narrower* — so
    "creatures you control" is wider than "Zombie creatures you control" and
    not than "Zombie creatures", which may be an opponent's.
    """
    return all(
        getattr(wider, field.name) in (field.default, getattr(narrower, field.name))
        for field in dataclasses.fields(wider)
    )


def _parse_conditional_additional_pump_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``If <condition>, <a narrower set> get an additional +N/+N [duration].``

    "Creatures you control get +1/+1 until end of turn. **If this spell was
    kicked, Zombie creatures you control get an additional +2/+2 until end of
    turn.**" (Strength of Night.) :func:`_parse_conditional_set_pump_rider`
    with the set *named* instead of referred to: no pronoun to bind, so the
    subject is read by the ordinary reader, and what this rider adds is the
    licence for "an additional" — which ``_parse_gets`` hands only to a caller
    that has checked a pump of the same creatures came first.

    Here that check is containment rather than identity. The sweep in front
    must be a pump and every restriction it prints must be printed again on
    this one (:func:`_narrows_filter`), so each creature the second pump
    reaches was reached by the first and "additional" is true of all of them.
    A set the first sweep did not cover refuses: for those creatures the word
    would be false, and the sentence is one no card prints.

    The word is required, not merely admitted — without it the sentence is an
    ordinary conditional sweep the statement grammar already reads.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.Pump):
        return None
    bound = last.subject
    if not (
        isinstance(bound, ast.TargetSpec)
        and bound.quantifier in ("all", "each")
        and not bound.targeted
    ):
        return None
    mark = stream.mark()
    if not stream.accept_word("if"):
        return None
    try:
        condition = _parse_condition(stream)
        if not stream.accept_punct(","):
            raise stream.error("expected ',' after the condition")
        subject = parse_recipient(stream)
        if not (
            isinstance(subject, ast.TargetSpec)
            and subject.quantifier in ("all", "each")
            and not subject.targeted
            and _narrows_filter(bound.filter, subject.filter)
            and stream.at_word("gets", "get")
            and stream.words_from(1)[:2] == ("an", "additional")
        ):
            raise stream.error("not an additional pump of a covered set")
        pump = _parse_gets(stream, subject, additional=True)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(pump, ast.Pump):
        stream.reset(mark)
        return None
    return ast.Conditional(condition, pump)
