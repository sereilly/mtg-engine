"""Riders whose subject is a **pronoun** pointing at the sentence before it.

"Put a +1/+1 counter on up to one target creature. **It** gains indestructible
until end of turn." The pronoun names the previous sentence's chosen object, and
nothing inside one sentence's parse can see back that far — so these read the
statement already parsed, bind to what it chose, and either append a step or
fold into it.

Split out of `riders.py` at the thousand-line guard, along the boundary that
module already drew: everything here answers "what does this pronoun name?",
where the rest of `riders.py` answers "which branch of the sentence before it
does this clause belong to". The two share not one helper in that direction —
`riders` imports the binding, never the other way round, which is why this sits
below it.
"""

from __future__ import annotations

from dataclasses import replace

from . import ast
from .errors import GrammarError
from .lexer import PT, QUOTE
from .effects import _parse_gains, _parse_loses
from .effects.characteristics import _parse_quoted_abilities
from .statements import _parse_condition
from .stream import TokenStream


_RIDER_FOLDED = ast.RawEffect("rider-folded")


def _statement_bound_target(statement: ast.Statement) -> ast.TargetSpec | None:
    """The chosen target a following pronoun sentence refers back to, or None.

    "Put a +1/+1 counter on up to one target creature. **It** gains
    indestructible until end of turn." — the pronoun names the previous
    sentence's target, not the ability's source. Walks a Sequence or
    Conjunction from its last step, because the pronoun binds to the nearest
    preceding choice.
    """
    if isinstance(statement, (ast.Sequence,)):
        for step in reversed(statement.steps):
            found = _statement_bound_target(step)
            if found is not None:
                return found
        return None
    if isinstance(statement, ast.Conjunction):
        for step in reversed(statement.effects):
            found = _statement_bound_target(step)
            if found is not None:
                return found
        return None
    # "Soul Sear deals 5 damage to target creature or planeswalker. It loses
    # indestructible…" — the damage sentence's chosen recipient is what the
    # pronoun names. Recipients live in their own tuple on DealDamage, which
    # the field scan below cannot see.
    if isinstance(statement, ast.DealDamage):
        for recipient in reversed(statement.recipients):
            if isinstance(recipient, ast.TargetSpec) and recipient.quantifier in ("target", "up_to"):
                return recipient
        return None
    for field_name in ("subject", "target"):
        candidate = getattr(statement, field_name, None)
        if isinstance(candidate, ast.TargetSpec) and candidate.quantifier in ("target", "up_to"):
            return candidate
    return None


def _parse_pronoun_verb_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``Untap that creature.`` after a sentence that chose one.

    The sibling of :func:`_parse_pronoun_grant_rider`: that one binds the
    previous target to a *grant*, this one to a plain imperative verb. "Untap
    that creature" (Traitorous Greed) has no target of its own — the spell chose
    one sentence ago, and re-parsing it as a fresh target would raise a second
    picker for a choice CR 601.2c says was made once.

    Only "untap" today, and one verb at a time deliberately: each imperative has
    to be checked against the shape its handler implements, and a table of verbs
    admitted wholesale would claim sentences nothing performs.
    """
    target = _statement_bound_target(steps[-1]) if steps else None
    if target is None:
        return None
    mark = stream.mark()
    if not stream.accept_word("untap"):
        return None
    if not (
        stream.accept_phrase("that", "creature")
        or stream.accept_phrase("that", "permanent")
        or stream.accept_word("it")
    ):
        stream.reset(mark)
        return None
    return ast.Untap(target)


def _parse_pronoun_grant_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``It gains <keywords> [duration].`` after a sentence that chose a target.

    Re-uses the previous sentence's own :class:`ast.TargetSpec` as the grant's
    subject, so both instructions describe — and resolve — the same choice.
    Without this the sentence parses on its own with "it" read as the source,
    which is the trigger-remainder reading and grants the ability's *source*
    the keyword (Basri Ket +1 would make Basri indestructible, not the
    creature).
    """
    target = _statement_bound_target(steps[-1]) if steps else None
    if target is None:
        return None
    mark = stream.mark()
    # "It gains …" / "That permanent loses …" (Soul Sear) — two spellings of
    # the same back-reference. The noun spelling is only claimed when a
    # grant/loss verb follows, so "that creature's controller …" (a different
    # referent) keeps its own reading.
    if not stream.accept_word("it"):
        if not stream.accept_word("that"):
            return None
        if not stream.accept_word("creature", "permanent", "planeswalker"):
            stream.reset(mark)
            return None
        if not stream.at_word("gains", "gain", "loses", "lose"):
            stream.reset(mark)
            return None
    # "It loses indestructible until end of turn." (Soul Sear) — the negative
    # half of the same pronoun binding: the previous sentence's target loses a
    # keyword, not the ability's source.
    if stream.at_word("loses", "lose"):
        try:
            loss = _parse_loses(stream, target)
        except GrammarError:
            stream.reset(mark)
            return None
        if not isinstance(loss, ast.LoseKeyword):
            # "It loses 2 life" would be a pronoun for a player, which this
            # binding cannot mean — leave the sentence to fail loudly.
            stream.reset(mark)
            return None
        return loss
    if not stream.at_word("gains", "gain"):
        stream.reset(mark)
        return None
    try:
        grant = _parse_gains(stream, target)
    except GrammarError:
        stream.reset(mark)
        return None
    # "Put target creature card from a graveyard onto the battlefield under
    # your control. It gains haste." (Liliana, Waker of the Dead's emblem.)
    # A durationless grant to a reanimated card folds into the reanimation —
    # the permanent does not exist until that step runs, so a separate grant
    # instruction would have nothing to grant to.
    if (
        isinstance(grant, ast.GainKeyword)
        and grant.duration.kind is None
        and isinstance(steps[-1], ast.PutOntoBattlefield)
    ):
        steps[-1] = replace(steps[-1], gains=steps[-1].gains + grant.keywords)
        return _RIDER_FOLDED
    return grant


def _parse_conditional_pronoun_grant_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``If <condition>, it gains <keywords> [duration].`` after a sentence that
    chose a target.

    "Target creature gains first strike until end of turn. **If it doesn't have
    rampage, that creature gains rampage 2 until end of turn.**" (Rapid Fire.)

    Its own rider rather than a branch of the sentence parser, for the reason
    :func:`_parse_pronoun_grant_rider` exists at all: the pronoun names the
    sentence *before* this one, and nothing inside a single sentence's parse can
    see back that far. Read without the binding, "that creature" is a subject
    nobody chose and the whole line refuses.

    The grant half is delegated to that function rather than re-implemented, so
    the two spellings of the pronoun, the loss half and the reanimation fold all
    stay in one place. Only the condition is read here.
    """
    if not steps or _statement_bound_target(steps[-1]) is None:
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
    grant = _parse_pronoun_grant_rider(stream, steps)
    # `_RIDER_FOLDED` means the grant merged into the previous step, which a
    # conditional cannot do — the merge would run the grant unconditionally.
    if grant is None or grant is _RIDER_FOLDED:
        stream.reset(mark)
        return None
    return ast.Conditional(condition, grant)


def _parse_conditional_quoted_grant_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``If it doesn't have "<ability>," it gains that ability.`` after a
    sentence that chose a target.

    "{T}: Put a music counter on target creature. **If it doesn't have "At the
    beginning of your upkeep, destroy this creature unless you pay {1} for each
    music counter on it," it gains that ability.**" (Musician.)

    The quoted twin of :func:`_parse_conditional_pronoun_grant_rider`, and its
    own reader for two reasons that reader cannot absorb:

    * the condition tests a whole printed *ability* rather than a keyword, so
      the generic condition parser has nothing to read it with;
    * the arm says "that ability" — a back-reference to the sentence inside the
      condition, which no independently parsed grant could name.

    Both halves therefore come out of one production, and the result is a single
    grant carrying the condition as ``only_if_absent`` rather than a
    :class:`ast.Conditional` over a condition nothing else prints. The two are
    the same statement: the test is about the very ability being granted, and
    splitting them would be two readings of one quote that could disagree about
    which sentence was meant.
    """
    if not steps:
        return None
    target = _statement_bound_target(steps[-1])
    if target is None:
        return None
    mark = stream.mark()
    if not stream.accept_phrase("if", "it", "doesn't", "have"):
        return None
    if not stream.at_kind(QUOTE):
        stream.reset(mark)
        return None
    try:
        abilities, self_name = _parse_quoted_abilities(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("it", "gains", "that", "ability"):
        stream.reset(mark)
        return None
    return ast.GainAbilityText(
        target, abilities, self_name=self_name, only_if_absent=True
    )


def _returned_permanent_step(statement: ast.Statement) -> ast.ReturnToZone | None:
    """The battlefield return a following "It loses …" sentence is about.

    Walks the branch a preceding rider folded, because that is where the return
    ends up: "If they don't, return this card … as a non-Aura enchantment. It
    loses …" (Takklemaggot) prints the second sentence outside the conditional
    and means it inside.
    """
    if isinstance(statement, ast.Conditional):
        for branch in (statement.otherwise, statement.then):
            if branch is None:
                continue
            found = _returned_permanent_step(branch)
            if found is not None:
                return found
        return None
    if isinstance(statement, ast.ReturnToZone) and statement.to.name == "battlefield":
        return statement
    return None


def _replace_returned_permanent_step(
    statement: ast.Statement, updated: ast.ReturnToZone
) -> ast.Statement:
    """*statement* with its battlefield return swapped for *updated*."""
    if isinstance(statement, ast.Conditional):
        for field_name in ("otherwise", "then"):
            branch = getattr(statement, field_name)
            if branch is not None and _returned_permanent_step(branch) is not None:
                return replace(statement, **{
                    field_name: _replace_returned_permanent_step(branch, updated)
                })
        return statement
    return updated


def _attach_returned_text_change(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold ``It loses "A" [and gains "B"].`` into the return before it.

    "…return this card to the battlefield under your control as a non-Aura
    enchantment. **It loses "enchant creature" and gains "…"**."
    (Takklemaggot.) CR 613.1f layer 6 on the permanent the sentence before it
    created — and that permanent is a new object (CR 400.7), so no reference
    reaches it and nothing but the move itself can be told about it. Hence a
    rider onto the move rather than a step of its own, the same shape every
    other fold on this page has.

    Only quoted *text* is read here. "It loses flying" is a keyword loss with a
    reader of its own (:func:`_parse_pronoun_grant_rider`), and claiming it here
    would give one sentence two readings.
    """
    if not steps:
        return False
    target = _returned_permanent_step(steps[-1])
    if target is None:
        return False
    mark = stream.mark()
    if not stream.accept_word("it"):
        return False
    losing: tuple[str, ...] = ()
    gaining: tuple[str, ...] = ()
    try:
        if stream.accept_word("loses", "lose"):
            if not stream.at_kind(PT) and stream.at_kind(QUOTE):
                losing, _ = _parse_quoted_abilities(stream)
            else:
                stream.reset(mark)
                return False
            if stream.accept_word("and") and stream.accept_word("gains", "gain"):
                gaining, _ = _parse_quoted_abilities(stream)
        elif stream.accept_word("gains", "gain") and stream.at_kind(QUOTE):
            gaining, _ = _parse_quoted_abilities(stream)
        else:
            stream.reset(mark)
            return False
    except GrammarError:
        stream.reset(mark)
        return False
    steps[-1] = _replace_returned_permanent_step(
        steps[-1],
        replace(
            target,
            losing_abilities=target.losing_abilities + losing,
            gaining_abilities=target.gaining_abilities + gaining,
        ),
    )
    return True
