"""Riders: a sentence that modifies the one before it.

A rider is not a step of its own. "If you do, …" branches the decision the
previous sentence offered; "Its controller creates a token" names the permanent
that sentence exiled; "…and it can't be regenerated" narrows the damage it
dealt. Every one of them reads a referent the previous step bound, which is why
they are read by the sentence loop rather than by ``parse_statement``: on their
own they name nothing.

Split out of ``parser.py`` when that file crossed 1,000 lines again. A family
rather than an arbitrary cut — this is the whole of what "a sentence about the
previous sentence" means, and the loop that drives them stays behind in
``parser.py`` with the line-level productions it belongs to.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

from . import ast
from .amounts import parse_amount
from .errors import GrammarError
from .lexer import PT
from .nouns import parse_object_filter
from .effects import _parse_create_token, _parse_gains
from .phrases import _accept_number
from .statements import _parse_condition, parse_statement
from .effects import _parse_loses
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


# Sentinel: the rider was folded into the previous step, nothing to append.


def _parse_exile_instead_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """``If that spell would be put into your graveyard, exile it instead.``
    after a cast-permission sentence (Chandra, Flame's Catalyst's −2).

    Folded onto the permission rather than parsed as a step, because it is a
    property of the cast the permission allows — the engine stamps it onto the
    stack object at cast time — and as a standalone sentence "that spell"
    would dangle with nothing binding it.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.CastPermission) or last.what != "target_card":
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "that", "spell", "would", "be", "put", "into", "your", "graveyard"
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase("exile", "it", "instead"):
        stream.reset(mark)
        return False
    steps[-1] = replace(last, exile_instead=True)
    return True


def _parse_its_controller_creates_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``Its controller creates a <token>.`` after a sentence that chose a
    target (Angelic Ascension, Secure the Scene — both after an exile).

    "Its" names the previous sentence's chosen permanent, which is gone by the
    time the token arrives — so the token rides the controller the exile step
    recorded, and the lowering demands that producer. Parsed as its own
    sentence, "its controller" would name nobody at all.
    """
    if not steps or _statement_bound_target(steps[-1]) is None:
        return None
    mark = stream.mark()
    if not stream.accept_phrase("its", "controller"):
        return None
    if not stream.at_word("creates"):
        stream.reset(mark)
        return None
    try:
        token = _parse_create_token(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    assert isinstance(token, ast.CreateToken)
    return replace(token, recipient="exiled_permanent_controller")


def _parse_that_controller_reveals_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``That creature's controller reveals cards from the top of their library
    until they reveal a creature card. That player puts that card onto the
    battlefield, then shuffles the rest into their library.`` (Transmogrify.)

    The same shape as the "its controller creates a token" rider beside it, and
    for the same reason: "that creature" names the permanent the previous
    sentence exiled, which is gone by the time this runs, so the library read
    rides the controller that step recorded. Parsed as its own sentence it names
    nobody.

    All three sentences are consumed here. They describe one procedure over one
    revealed pile — "that card" is what the reveal stopped on and "the rest" is
    exactly what it turned over first — so parsed apart the last two would
    dangle referents nothing binds.
    """
    if not steps or _statement_bound_target(steps[-1]) is None:
        return None
    mark = stream.mark()
    if not stream.accept_phrase("that", "creature", "'s", "controller"):
        return None
    if not stream.accept_phrase(
        "reveals", "cards", "from", "the", "top", "of", "their", "library",
        "until", "they", "reveal",
    ):
        stream.reset(mark)
        return None
    try:
        stream.accept_word("a", "an")
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not filt.is_card:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    # Every word of the destination and of what happens to the rest. A card
    # that milled the pile instead of shuffling it back is a different card, and
    # the difference does not show until this sentence.
    if not stream.accept_phrase(
        "that", "player", "puts", "that", "card", "onto", "the", "battlefield",
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "then", "shuffles", "the", "rest", "into", "their", "library",
    ):
        stream.reset(mark)
        return None
    return ast.RevealUntil("exiled_permanent_controller", filt)


def _parse_conditional_instead_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """``You gain 4 life. If a creature died this turn, you gain 8 life
    instead.`` (Life Goes On.) ``{T}: Add {C}. If you control an Urza's
    Power-Plant and an Urza's Tower, add {C}{C} instead.`` (Urza's Mine.)

    The second sentence *replaces* the first when its condition holds, so the
    pair folds into one ``Conditional`` — then the bigger gain, otherwise the
    printed base. Parsed apart, the two sentences would gain 12 life on a
    death; the "instead" is the whole content of the sentence, so it is
    required, and only a same-shaped statement may replace the last step.
    """
    # The statement kinds this rider can replace. `AddMana` joins `GainLife`
    # for the Antiquities land cycle — "{T}: Add {C}. If you control an Urza's
    # Power-Plant and an Urza's Tower, add {C}{C} instead." — which is the same
    # sentence pair with a different verb. The replacement must be the *same*
    # kind as what it replaces (checked below), so widening the set cannot let
    # one kind silently stand in for another.
    _REPLACEABLE = (ast.GainLife, ast.AddMana)

    last = steps[-1] if steps else None
    if not isinstance(last, _REPLACEABLE):
        return False
    mark = stream.mark()
    if not stream.accept_word("if"):
        return False
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    try:
        replacement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    if type(replacement) is not type(last) or not stream.accept_word("instead"):
        stream.reset(mark)
        return False
    steps[-1] = ast.Conditional(condition, then=replacement, otherwise=last)
    return True


def _parse_who_cant_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``Each opponent who can't loses N life.`` after an each-player discard
    (Liliana, Waker of the Dead). The loss applies only to opponents who could
    not perform the previous sentence's action, so it is recorded as a
    back-reference the lowering turns into a reader of that step's result."""
    last = steps[-1] if steps else None
    if not (isinstance(last, ast.Discard) and last.player.kind == "each_player"):
        return None
    mark = stream.mark()
    if not (
        stream.accept_word("each")
        and stream.accept_word("opponent")
        and stream.accept_phrase("who", "can't")
    ):
        stream.reset(mark)
        return None
    try:
        stream.expect_word("loses", "lose")
        amount = parse_amount(stream)
        stream.expect_word("life")
    except GrammarError:
        stream.reset(mark)
        return None
    return ast.LoseLife(ast.PlayerRef("each_opponent"), amount, who_could_not="discard")


def _attach_if_you_do(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "If you do, …" / "If you don't, …" into the preceding ``May``.

    These are branches of the optional action, not steps of their own: "You may
    pay {1}. If you do, you gain 1 life." is one decision with a consequence.
    Parsing them as separate sentences would make the life gain unconditional —
    the same class of mistake as treating "you may pay {2}" as a plain cost.
    """
    # "You may draw X cards, where X is …. If you do, discard a card."
    # (Sanctum of Calm Waters.) The where-clause wraps the whole sentence, so
    # the May is one level down — lifted off here and put back on outside the
    # fold, because the definition binds the branch as well as the offer.
    target = steps[-1]
    definition = target.definition if isinstance(target, ast.WhereX) else None
    if definition is not None:
        target = target.statement
    mark = stream.mark()
    if not stream.accept_word("if"):
        return False
    if not stream.accept_word("you"):
        stream.reset(mark)
        return False

    if stream.accept_word("do"):
        declined = False
    elif stream.accept_word("don't") or stream.accept_phrase("do", "not"):
        declined = True
    else:
        stream.reset(mark)
        return False

    stream.accept_punct(",")
    try:
        branch = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False

    if not isinstance(target, ast.May):
        # "Exile it. **If you do**, create a … token." (Archfiend's Vessel.)
        # The preceding action was not optional, so there is no decision to
        # branch on — the branch asks whether the action *took place*, and the
        # pairing with the step before it is made here, where "the step before
        # it" is a fact rather than a guess.
        # "If you **don't**" has no reading here: an action that was not
        # optional has no declining, so the words are refused rather than
        # folded onto a branch that could never be taken.
        if declined:
            stream.reset(mark)
            return False
        steps.append(ast.Conditional(ast.ItHappened(), branch))
        return True

    may = target
    folded = ast.May(
        actor=may.actor,
        cost=may.cost,
        action=may.action,
        then=branch if not declined else may.then,
        otherwise=branch if declined else may.otherwise,
    )
    steps[-1] = ast.WhereX(folded, definition) if definition is not None else folded
    return True


def _bind_that_creature_after_enchanted(branch: ast.Statement) -> ast.Statement:
    """*branch* with a "that creature" keyword grant bound to the enchanted
    creature an earlier step of the same branch names.

    "…put a +1/+1 counter on **enchanted creature**, and **that creature**
    gains flying." (Cocoon.) "That creature" restates the step before it, and
    the noun parser must not learn the phrase — every sentence printing those
    words would then lower through a filter naming a creature nobody bound. The
    pairing is made here, where the antecedent is a fact: only a bare "that
    creature" is rewritten, and only when an enchanted-creature step precedes
    it in the same branch.
    """
    def bind(
        statement: ast.Statement, enchanted: ast.TargetSpec | None
    ) -> tuple[ast.Statement, ast.TargetSpec | None]:
        # Sequences nest right-leaning ("A, B, and C" parses as (A, (B, C))),
        # so the walk recurses instead of reading one level of steps.
        if isinstance(statement, ast.Sequence):
            rebuilt = []
            for step in statement.steps:
                step, enchanted = bind(step, enchanted)
                rebuilt.append(step)
            return ast.Sequence(tuple(rebuilt)), enchanted
        if (
            isinstance(statement, ast.GainKeyword)
            and isinstance(statement.subject, ast.TargetSpec)
            and statement.subject.quantifier == "that"
            and statement.subject.filter == ast.ObjectFilter(card_types=("creature",))
            and enchanted is not None
        ):
            return replace(statement, subject=enchanted), enchanted
        subject = getattr(statement, "subject", None)
        if isinstance(subject, ast.TargetSpec) and subject.filter.is_enchanted:
            enchanted = subject
        return statement, enchanted

    bound, _ = bind(branch, None)
    return bound


def _attach_if_you_cant(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "If you can't, …" into the preceding mandatory action.

    "At the beginning of your upkeep, remove a pupa counter from this Aura. If
    you can't, sacrifice it, put a +1/+1 counter on enchanted creature, and
    that creature gains flying." (Cocoon.) The mirror of the un-optional
    "If you do" (``ItHappened``): the action before it was mandatory, so there
    is no decision to branch on — the branch asks whether the action *could be
    performed*, which for a counter removal is whether a counter was there to
    remove. Paired with the step in front of it here, where "the step before
    it" is a fact; the lowering (``_lower_steps``) is what checks that the
    step records an answer to read, exactly as it does for "if you do".

    Only a ``RemoveCounter`` is folded onto: it is the producing step the pool
    prints this rider after, and a wider fold would pair the words with steps
    whose "can't" nobody records.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.RemoveCounter):
        return False
    mark = stream.mark()
    if not (
        stream.accept_word("if")
        and stream.accept_word("you")
        and stream.accept_word("can't")
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    try:
        branch = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    steps.append(
        ast.Conditional(ast.CouldNot(), _bind_that_creature_after_enchanted(branch))
    )
    return True


def _attach_when_you_do(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "When you do, …" into the preceding ``May`` as its reflexive branch.

    One word apart from ``_attach_if_you_do`` and a different rule (CR 603.12):
    "if you do" is the rest of this resolution, "when you do" is a *new*
    triggered ability the payment creates, which chooses its own targets as it is
    created. Tolarian Kraken is the difference — "you may tap or untap target
    creature" has a target the drawing of a card never named, so folded onto the
    ``then`` branch it would run against whatever the producing action happened
    to point at.

    Read as its own production rather than as a flag on the other so that the
    two cannot be conflated by a later edit to either.
    """
    target = steps[-1]
    definition = target.definition if isinstance(target, ast.WhereX) else None
    if definition is not None:
        target = target.statement
    if not isinstance(target, ast.May):
        return False
    mark = stream.mark()
    if not stream.accept_phrase("when", "you", "do"):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    try:
        branch = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False

    folded = ast.May(
        actor=target.actor,
        cost=target.cost,
        action=target.action,
        then=target.then,
        otherwise=target.otherwise,
        reflexive=branch,
    )
    steps[-1] = ast.WhereX(folded, definition) if definition is not None else folded
    return True


def _attach_spend_only(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "Spend this mana only to …" into the mana production before it.

    A rider and not a step: the sentence adds nothing to the game, it says what
    the *previous* sentence's mana may pay for (CR 106.6). Parsed as its own
    step it would be an effect nothing performs, and the mana would go into the
    unrestricted pool with the restriction reported as understood.

    Which restrictions exist is `engine/restricted_mana.py`'s question, asked
    through its own matcher over the sentence's printed text — the delegation
    round 85 established for a registry-claimed sentence, and for its reason: a
    copy of the phrase here would be free to drift from the predicate that
    enforces it, and mana spent more freely than the card allows is the
    direction that drift goes.
    """
    from ..restricted_mana import mana_restriction_for

    if not isinstance(steps[-1], ast.AddMana):
        return False
    mark = stream.mark()
    start = stream.pos
    while not stream.exhausted and not stream.at_punct(".", ";"):
        stream.advance()
    sentence = stream.text_between(start, stream.pos)
    restriction = mana_restriction_for(sentence)
    if restriction is None:
        stream.reset(mark)
        return False
    steps[-1] = dataclasses.replace(steps[-1], spend_only=restriction.key)
    return True


def _attach_unpaid_penalty(statement: ast.Statement, penalty: str) -> ast.Statement:
    """Fold "If that player doesn't, …" into the "unless … pays" it belongs to.

    Raises when there is no such effect to attach to. A penalty for declining a
    cost that was never offered is not something the grammar can place, and
    consuming the sentence anyway is precisely the dropped-rider bug the
    full-consumption invariant exists to prevent.
    """
    if isinstance(statement, ast.CounterSpell) and statement.unless_pays is not None:
        return ast.CounterSpell(statement.subject, statement.unless_pays, penalty)
    raise GrammarError("an unpaid-cost penalty with no cost to decline")


def _attach_riders(statement: ast.Statement, riders: ast.DamageRiders) -> ast.Statement:
    """Fold damage riders into the most recent DealDamage of *statement*."""
    if isinstance(statement, ast.DealDamage):
        merged = ast.DamageRiders(
            no_regen=statement.riders.no_regen or riders.no_regen,
            exile_if_dies=statement.riders.exile_if_dies or riders.exile_if_dies,
            divided=statement.riders.divided,
            divided_evenly=statement.riders.divided_evenly,
        )
        return ast.DealDamage(
            statement.source, statement.amount, statement.recipients, merged, statement.chooser
        )
    if isinstance(statement, ast.Sequence) and statement.steps:
        steps = list(statement.steps)
        steps[-1] = _attach_riders(steps[-1], riders)
        return ast.Sequence(tuple(steps))
    if isinstance(statement, ast.Conjunction) and statement.effects:
        effects = list(statement.effects)
        effects[0] = _attach_riders(effects[0], riders)
        return ast.Conjunction(tuple(effects))
    raise GrammarError("damage rider with no damage effect to attach to")


def _attach_counter_cap(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "This ability can't cause the total number of <kind> counters on
    this <noun> to be greater than N." into the placement before it.

    The counter kind is checked against the placement's own, not just consumed:
    a card capping a *different* counter than the one it just placed is saying
    something this rider cannot express, and matching it anyway would cap the
    wrong pile.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.PutCounter):
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "this", "ability", "can't", "cause", "the", "total", "number", "of"
    ):
        stream.reset(mark)
        return False
    token = stream.peek()
    if token is None or token.kind != PT or token.text != last.counter:
        stream.reset(mark)
        return False
    stream.advance()
    if not stream.accept_word("counters"):
        stream.reset(mark)
        return False
    if not stream.accept_phrase("on", "this"):
        stream.reset(mark)
        return False
    # The noun is **required**, not merely accepted. Optional, the rider still
    # matched with the word deleted — which the parse-coverage deletion probe
    # reported as a silently ignored word, and it was right: "on this to be
    # greater than four" is not a sentence, and a rule that accepts it is a
    # rule that would accept a cap on some other permanent's counters too.
    if not stream.accept_word(
        "creature", "artifact", "enchantment", "land", "permanent"
    ):
        stream.reset(mark)
        return False
    if not stream.accept_phrase("to", "be", "greater", "than"):
        stream.reset(mark)
        return False
    cap = _accept_number(stream)
    if cap is None:
        stream.reset(mark)
        return False
    steps[-1] = dataclasses.replace(last, cap=cap)
    return True
