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

import dataclasses
from dataclasses import replace

from . import ast
from .errors import GrammarError
from .lexer import PT, QUOTE
from .effects import _parse_gains, _parse_loses, _parse_put_counter
from .effects.characteristics import _parse_quoted_abilities
from .phrases import _accept_self_reference
from .statements import _parse_condition
from .stream import TokenStream
from .vocabulary import CARD_TYPES


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


def _parse_pronoun_counter_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``Put a -1/-0 counter on it.`` after a sentence that chose an object.

    Jabari's Influence prints it joined by "and": "Gain control of target
    nonartifact, nonblack creature that attacked you this turn **and put a
    -1/-0 counter on it**." The counter goes on the creature the first half
    took, not on the ability's own source — and that is what the sentence did
    before this rider, because ``parse_recipient`` reads a bare "it" as the
    source on every line whose sentence names nothing else.

    Silent both ways, which is why it is a rider rather than a refusal: on a
    spell ``add_counter_to_self`` has no permanent and places nothing, and on a
    permanent it shrinks the ability's own source. Neither raises.

    Read by parsing the sentence with the ordinary counter production and then
    substituting the subject, rather than by a second copy of that production:
    "up to two", "for each …" and the doubling rider are all things it already
    reads, and a rider that re-spelled the placement would be free to disagree
    about any of them. ``quantifier == "it"`` is what says the subject was the
    bare pronoun — "this creature" and "that creature" parse to their own
    quantifiers and keep their own referents.
    """
    target = _statement_bound_target(steps[-1]) if steps else None
    if target is None or not stream.at_word("put"):
        return None
    mark = stream.mark()
    try:
        statement = _parse_put_counter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    subject = getattr(statement, "subject", None)
    if (
        not isinstance(statement, ast.PutCounter)
        or not isinstance(subject, ast.TargetSpec)
        or subject.quantifier != "it"
    ):
        stream.reset(mark)
        return None
    return replace(statement, subject=target)


def _creates_the_permanent_it_names(statement: ast.Statement) -> bool:
    """Whether *statement* puts a card onto the battlefield, so that a pronoun
    after it names a **permanent that did not exist** when the choice was made.

    "Return target white or black creature card from your graveyard to the
    battlefield. **That creature** gains "Cumulative upkeep {2}."" (Dreams of
    the Dead.) What the sentence before it chose is a *card in a graveyard*;
    what this one talks about is the permanent that arrived. Reusing the
    previous target spec — which every other pronoun rider does, and rightly —
    would hand the grant a graveyard-scoped noun phrase, and there is no such
    permanent to grant to.

    So the pronoun is left as the bare bound marker and the lowering points it
    at what the move *recorded*, the way every other back-reference to an
    earlier step's objects is resolved.
    """
    return (
        isinstance(statement, ast.ReturnToZone)
        and statement.from_zone is not None
        and statement.from_zone.name == "graveyard"
        and statement.to.name == "battlefield"
    )


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
    # A move that *creates* the permanent the pronoun names hands over the bound
    # marker instead of its own target spec — see
    # :func:`_creates_the_permanent_it_names`.
    subject = (
        ast.TargetSpec("that", ast.ObjectFilter(card_types=("creature",)))
        if _creates_the_permanent_it_names(steps[-1]) else target
    )
    try:
        grant = _parse_gains(stream, subject)
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


def _attach_sacrifice_when_control_lost(
    stream: TokenStream, steps: list
) -> bool:
    """Fold "Sacrifice the creature when you lose control of this creature."
    into the battlefield entry before it (Seraph, Krovikan Vampire).

    CR 603.7's delayed triggered ability, watching a control change the sentence
    in front of it has not made yet: the permanent it is about is the one that
    entry is about to create, which is exactly why it is a rider and not a step.
    Parsed alone, "the creature" names nothing at all.

    Both printings are read: Krovikan Vampire says "Sacrifice **it**" and Seraph
    "Sacrifice **the creature**", and the pronoun and the repeated noun are one
    referent (idiom 20) — the pair ``lowering/control_changes`` and
    ``lowering/stack`` already read together. The noun is consumed against the
    card types rather than skipped, the discipline
    ``riders._attach_tap_when_control_lost`` states: a sentence naming something
    the entry never made would otherwise be read as this one.

    "…of **this** creature" is the ability's own source, and only that spelling
    is admitted. A control change about any other object is one the sweep in
    ``engine/linked_sacrifice.py`` has no record to check, so the words stay
    unconsumed and the line fails loudly.

    Marked wherever the entry sits, through a structural walk, because Seraph
    prints it *inside* a delayed ability ("…at the beginning of the next end
    step") and Krovikan Vampire does not.
    """
    if not any(_finds_battlefield_entry(step) for step in steps):
        return False
    mark = stream.mark()
    if not stream.accept_word("sacrifice"):
        stream.reset(mark)
        return False
    if not stream.accept_word("it"):
        if not stream.accept_word("the"):
            stream.reset(mark)
            return False
        noun = stream.peek_word()
        if noun is None or noun not in CARD_TYPES:
            stream.reset(mark)
            return False
        stream.advance()
    if not stream.accept_phrase("when", "you", "lose", "control", "of"):
        stream.reset(mark)
        return False
    if not _accept_self_reference(stream):
        stream.reset(mark)
        return False
    for index, step in enumerate(steps):
        steps[index] = _marks_entry_watched(step)
    return True


def _finds_battlefield_entry(node) -> bool:
    """Whether *node* contains a :class:`ast.PutOntoBattlefield`."""
    return _marks_entry_watched(node) is not node


def _marks_entry_watched(node):
    """*node* with every ``PutOntoBattlefield`` in it marked.

    A structural walk rather than a per-shape probe, for
    ``riders._marks_control_change_watched``'s reason: the entry can be a step,
    a conjunct, or the effect of a delayed ability, and a list of the shapes it
    has been seen in goes stale the way every fire-site list in this engine has.
    """
    if isinstance(node, ast.PutOntoBattlefield):
        return replace(node, sacrifice_when_control_lost=True)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changed = {}
        for field in dataclasses.fields(node):
            value = getattr(node, field.name)
            if isinstance(value, tuple):
                walked = tuple(_marks_entry_watched(item) for item in value)
                if any(a is not b for a, b in zip(walked, value)):
                    changed[field.name] = walked
                continue
            walked = _marks_entry_watched(value)
            if walked is not value:
                changed[field.name] = walked
        if changed:
            return replace(node, **changed)
    return node


def _parse_exile_instead_of_leaving_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``If the creature would leave the battlefield, exile it instead of
    putting it anywhere else.`` (Dreams of the Dead.)

    A pronoun rider like the grants above: "the creature" is the permanent an
    earlier sentence of the same ability put onto the battlefield, and nothing
    inside this sentence's own parse can see back that far.

    It **folds into that move** rather than becoming a step, the way the
    durationless keyword grant after a reanimation already does and for the
    same reason: the permanent does not exist until the move runs, so a
    separate step would have nothing to arm — and what it arms is not a target
    anything chose, because this ability's target is a *card* in a graveyard.
    Returns :data:`_RIDER_FOLDED` when it merges.

    **Every word of the tail is consumed literally**, and each is load-bearing:

    * "would leave the battlefield" is the whole event. Read as "would die" it
      would be a strictly *smaller* effect — a death is one of the ways a
      permanent leaves — and this clause is a drawback, so the smaller reading
      is the one that hands the player a card better than the one printed.
    * "instead of putting it anywhere else" is what says the exile replaces
      **every** destination. A production that still matched with those words
      deleted would be claiming a sentence it had not read, which is what the
      parse-coverage deletion probe reports.

    Returns None with the cursor untouched on anything else, so an ordinary
    conditional keeps its own reading.
    """
    index = next(
        (
            i for i in range(len(steps) - 1, -1, -1)
            if _creates_the_permanent_it_names(steps[i])
        ),
        None,
    )
    if index is None:
        return None
    mark = stream.mark()
    if not stream.accept_word("if"):
        return None
    # The printed noun, not a bare pronoun: the card says "the creature". Any
    # other noun is a sentence about something else and must not be read as
    # this one.
    if not stream.accept_word("the"):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun is None or noun not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("would", "leave", "the", "battlefield"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "exile", "it", "instead", "of", "putting", "it", "anywhere", "else"
    ):
        stream.reset(mark)
        return None
    steps[index] = replace(steps[index], exile_on_leave=True)
    return _RIDER_FOLDED
