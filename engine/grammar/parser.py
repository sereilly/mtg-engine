"""Recursive-descent parser for oracle-text ability lines.

Precedence here is *structural*, not numeric. The legacy registry gave every
rule a hand-picked global order integer and ran a linear first-match scan, so
"destroy all creatures" had to be given a lower number than "destroy target
creature" and every new rule author had to reason about the whole ordering
space. In a grammar the same distinction falls out of the noun parser
returning ``quantifier="all"`` versus ``"target"`` from one ``destroy``
production — there is nothing to order.

The controlling invariant is **full token consumption**: a production that
matches must account for every token of its line. Leftover tokens raise
``GrammarError``. That is what makes "parsed" mean "understood in full", and it
is the structural fix for the dropped-rider bug class the parse-coverage
deletion probe was built to detect empirically.

**This file is the *line* layer.** What kind of line is this (keyword-only,
registry-derived, static), what costs and trigger event does it carry, how do
its sentences join, and ``parse_line`` — the one entry point. The layers below,
in strict dependency order, none importing back:

    phrases      word tables, and productions that read a fragment
    effects/     one production per thing a card can do, in seven families
    statements   one whole sentence
    parser       one printed line          <- you are here

The split follows the banners the file already carried. Two corrections came
out of the dependency graph rather than out of reading it: four effect
productions had drifted down into the line section and were the only cycle, and
two fragment productions filed as effects were the only thing coupling the
effect families. Nothing changed but where the code lives — held to that by a
whole-pool snapshot of every compiled program and every line's parse result,
diffed before and after.
"""

import re
from dataclasses import replace

from . import ast
from .amounts import parse_amount
from .derived import derived_instruction_for_line
from .errors import GrammarError
from .lexer import (BULLET, MANA, PUNCT, QUOTE, SELF, tokenize)
from .nouns import (parse_target_spec)
from .registries import registry_for_line
from .stream import TokenStream
from .vocabulary import (COLOR_WORDS, KEYWORD_INDEX, match_longest)
from .phrases import (
    _AT_EVENTS,
    _WHENEVER_EVENTS,
)
from .effects import (
    _expect_counter_kind,
    _parse_activation_restriction,
    _parse_create_token,
    _parse_damage_rider_sentence,
    _parse_gains,
    _parse_loses,
    _parse_unpaid_penalty_sentence,
)
from .statements import (
    _parse_condition,
    parse_statement,
)


# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------


def _is_keyword_line(stream: TokenStream) -> tuple[ast.KeywordInstance, ...] | None:
    """A line that is nothing but keyword abilities.

    The separator is a comma, "and", or a **semicolon**: Magic's templating
    switches to semicolons once one of the keywords carries reminder text
    ("Trample; banding (…)"), and the lexer strips the reminder while leaving
    the semicolon behind. Without it Mesa Pegasus and War Elephant fail on
    their first keyword and are reported as missing a *subject*, which points
    at nothing that exists.
    """
    mark = stream.mark()
    keywords: list[ast.KeywordInstance] = []
    while not stream.exhausted:
        matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
        if matched is None:
            stream.reset(mark)
            return None
        name, consumed = matched
        stream.advance(consumed)
        argument: str | None = None
        if name == "protection" and stream.accept_word("from"):
            word = stream.peek_word()
            if word is None:
                stream.reset(mark)
                return None
            stream.advance()
            argument = word
        keywords.append(ast.KeywordInstance(name, argument))
        if stream.exhausted:
            break
        if not (stream.accept_punct(",", ";") or stream.accept_word("and")):
            stream.reset(mark)
            return None
    return tuple(keywords) if keywords else None


def _parse_registry_line(stream: TokenStream, line: str) -> ast.RegistryLine | None:
    """A line implemented by a text-keyed sidecar registry rather than by any
    instruction — ``engine/grammar/registries.py`` names the implementing code
    for each shape it admits.

    Nothing is matched *structurally* here, and that is deliberate. A
    shape-based production ("cast this spell only" followed by anything, "…
    don't untap during" followed by anything) would parse wordings no registry
    implements and report them as understood, which is worse than the current
    loud refusal. Instead the registry's own matcher is asked whether it claims
    the whole line, so full consumption holds by construction: the tokens are
    advanced past the end only once something has accounted for all of them.

    A line claimed here is never offered to the effect productions, so an entry
    may only exist while the line has no instruction at all. When one grows a
    real lowering, its registry entry has to go — otherwise this would shadow
    it silently.
    """
    registry = registry_for_line(line)
    if registry is None:
        return None
    stream.advance(len(stream) - stream.pos)
    return ast.RegistryLine(registry, line)


def _parse_cost_object(stream: TokenStream, verb: str) -> ast.ObjectFilter:
    """The noun phrase naming what a cost gives up, after *verb*.

    Delegates to the noun parser rather than skipping a token, so "Sacrifice
    this artifact" and "Sacrifice a creature" end up as *different* filters —
    one flagged ``is_source``, one carrying a card type. The old
    ``accept_phrase("sacrifice", "this")`` + ``advance()`` read any word at all
    as the noun and produced the same empty filter either way, which reads as
    "sacrifice any object" to anyone who later lowers these.

    Only the two quantifiers the pool prints are admitted. "Sacrifice two
    creatures" or "Sacrifice target creature" would parse here and mean
    something the rest of the cost machinery has no way to express, so they
    raise instead.
    """
    # "Sacrifice **another** creature" (Hobblefiend). The word sits where the
    # article does, so the noun behind it parses bare — `parse_target_spec`
    # returns quantifier "all" for "creature" and None for "another creature".
    # Teaching the noun parser an "another" quantifier would change every
    # targeted line in the pool, so the exclusion is read here and carried on
    # the filter's existing `other_than_source` field: CR 602.5c's "another" is
    # a restriction on what may pay, not a different kind of cost.
    another = bool(stream.accept_word("another"))
    spec = parse_target_spec(stream)
    if spec is None:
        raise stream.error(f"expected what to {verb} as a cost")
    allowed = ("all",) if another else ("this", "a")
    if spec.quantifier not in allowed or spec.count != 1:
        raise stream.error(f"unsupported {verb} cost quantifier {spec.quantifier!r}")
    return replace(spec.filter, other_than_source=True) if another else spec.filter


def _is_chargeable_sacrifice(filt: ast.ObjectFilter) -> bool:
    """Whether the payment path can actually collect this sacrifice cost.

    ``queue_permanent_ability`` charges it with one card type (plus "another"),
    which is everything the pool prints but "a creature **with defender**"
    (Portcullis Vine). A rider the charger cannot express must refuse the line
    rather than be dropped — dropped, the Vine sacrifices any creature at all
    while still reporting supported, which is the dropped-rider bug class.
    Compared for equality against the bare filter, so a field the AST grows
    later is refused here instead of silently ignored.
    """
    if filt.is_source:
        return True
    bare = ast.ObjectFilter(
        card_types=filt.card_types, other_than_source=filt.other_than_source
    )
    return len(filt.card_types) == 1 and filt == bare


def _parse_counter_removal_cost(stream: TokenStream) -> ast.RemoveCounterCost:
    """``Remove a <kind> counter from this <permanent>`` (Scavenging Ghoul).

    The counter's name is read as free text, where ``_parse_put_counter``
    additionally rejects a P/T-shaped kind outside the four the engine knows.
    The difference is what happens downstream: a *put* is lowered onto a
    handler, so a P/T counter nothing implements would be silently
    mis-executed, while a cost is recorded and never lowered — the name is
    carried verbatim (CR 122.1 lets a counter have any name) and the
    surrounding words pin the structure.

    The subject must be the ability's own source: :class:`ast.RemoveCounterCost`
    has no subject field, so "remove a counter from target creature" would be
    consumed and then read as the source's counter. That refuses instead.
    """
    stream.expect_word("remove")
    count = ast.Fixed(1) if stream.accept_word("a", "an") else parse_amount(stream)
    counter = _expect_counter_kind(stream, " to remove").text
    stream.expect_word("counter", "counters")
    stream.expect_word("from")
    subject = _parse_cost_object(stream, "remove a counter from")
    if not subject.is_source:
        raise stream.error("a counter-removal cost only reads the ability's own source")
    return ast.RemoveCounterCost(counter, count)


def _parse_costs(stream: TokenStream) -> tuple[ast.Cost, ...]:
    """Parse the cost clause left of an activated ability's colon."""
    costs: list[ast.Cost] = []
    pips: dict[str, int] = {}
    while True:
        token = stream.accept_kind(MANA)
        if token is not None:
            symbol = token.text.strip("{}")
            if symbol == "T":
                costs.append(ast.TapSelf())
            elif symbol.isdigit():
                pips["generic"] = pips.get("generic", 0) + int(symbol)
            elif symbol in ("W", "U", "B", "R", "G", "C"):
                pips[symbol] = pips.get(symbol, 0) + 1
            elif symbol == "X":
                pips["X"] = pips.get("X", 0) + 1
            else:
                raise stream.error(f"unsupported mana symbol {token.text!r}")
            stream.accept_punct(",")
            continue
        if stream.accept_word("sacrifice"):
            sacrificed = _parse_cost_object(stream, "sacrifice")
            if not _is_chargeable_sacrifice(sacrificed):
                raise stream.error("no cost path charges a narrowed sacrifice")
            costs.append(ast.SacrificeCost(sacrificed))
            stream.accept_punct(",")
            continue
        if stream.accept_word("exile"):
            # ``ExileSelf`` names no object, so exiling anything else would be
            # consumed and then read as the source leaving the battlefield.
            exiled = _parse_cost_object(stream, "exile")
            if not exiled.is_source:
                raise stream.error("only exiling the ability's own source is a known cost")
            costs.append(ast.ExileSelf())
            stream.accept_punct(",")
            continue
        if stream.at_word("remove"):
            costs.append(_parse_counter_removal_cost(stream))
            stream.accept_punct(",")
            continue
        if stream.at_word("discard"):
            stream.advance()
            if stream.accept_phrase("the", "last", "card", "you", "drew", "this", "turn"):
                costs.append(ast.DiscardCost(ast.Fixed(1), last_drawn=True))
            elif stream.accept_phrase("a", "card"):
                # "Discard a card" (Seasoned Hallowblade) — the payer picks, and
                # ``ActivatedAbilityCost.discard_cards`` is what collects it.
                # Only the singular is admitted: a counted "discard two cards"
                # is a shape nothing charges, and admitting it would describe a
                # payment that never happens.
                costs.append(ast.DiscardCost(ast.Fixed(1)))
            else:
                raise stream.error("unrecognized discard cost")
            stream.accept_punct(",")
            continue
        break
    if pips:
        costs.insert(0, ast.ManaCost(tuple(sorted(pips.items()))))
    if not stream.exhausted:
        raise stream.error("unrecognized activation cost")
    return tuple(costs)


def _split_on_colon(tokens: tuple) -> int | None:
    for index, token in enumerate(tokens):
        if token.kind == PUNCT and token.text == ":":
            return index
    return None


def _parse_quantified_tap_event(stream: TokenStream) -> ast.TriggerEvent | None:
    """"Whenever **a Forest an opponent controls** becomes tapped" (Lifetap) /
    "Whenever **a Mountain** is tapped for mana" (Gauntlet of Might).

    The two tapping events whose subject is *quantified* rather than named. The
    literal phrases in ``_WHENEVER_EVENTS`` cover the named subjects ("enchanted
    land", "this land", "a player taps a land"); here the subject is a noun
    phrase, so it is parsed and carried on the event instead of being spelled
    out once per printed land type.

    Tried only after that table, which is what keeps "whenever enchanted land
    becomes tapped" reading as ``enchanted_land_tapped``: ``parse_target_spec``
    would happily claim "enchanted land" as a quantified subject and name a
    condition the legacy table does not, which is precisely the disagreement
    ``test_every_executed_trigger_agrees_with_the_legacy_condition_table``
    exists to catch.
    """
    mark = stream.mark()
    spec = parse_target_spec(stream)
    # Only the indefinite "a <filter>" reading. "each"/"all"/"target" would be a
    # different event, and "this"/"enchanted" belong to the table above.
    if spec is not None and spec.quantifier == "a" and spec.filter is not None:
        if stream.accept_phrase("becomes", "tapped"):
            return ast.TriggerEvent(
                "permanent_becomes_tapped", "whenever", subject=spec.filter
            )
        if stream.accept_phrase("is", "tapped", "for", "mana"):
            return ast.TriggerEvent(
                "land_tapped_for_mana", "whenever", subject=spec.filter
            )
    stream.reset(mark)
    return None


def _parse_trigger_event(stream: TokenStream) -> ast.TriggerEvent | None:
    if stream.accept_word("whenever"):
        # "…casts a *blue* spell" (the Rod/Cup/Sphere cycle). The colour is part
        # of the condition rather than a per-card hook, which is what lets one
        # dispatcher serve every card written this way.
        mark = stream.mark()
        if stream.accept_phrase("a", "player", "casts", "a"):
            colour = stream.peek_word()
            if colour in COLOR_WORDS:
                stream.advance()
                if stream.accept_word("spell"):
                    return ast.TriggerEvent(
                        "spell_cast", "whenever",
                        subject=ast.ObjectFilter(colors=(COLOR_WORDS[colour],)),
                    )
        stream.reset(mark)
        # "…you cast a spell that's white, blue, black, or red" (Quirion
        # Dryad): a colour-list narrowing of you_cast_spell. Read before the
        # phrase table, whose bare "you cast a spell" entry is its prefix.
        mark = stream.mark()
        if stream.accept_phrase("you", "cast", "a", "spell", "that", "'s"):
            colors: list[str] = []
            while True:
                word = stream.peek_word()
                if word not in COLOR_WORDS:
                    break
                stream.advance()
                colors.append(COLOR_WORDS[word])
                if stream.accept_punct(","):
                    stream.accept_word("or")
                    continue
                if stream.accept_word("or"):
                    continue
                break
            if len(colors) >= 2:
                return ast.TriggerEvent(
                    "you_cast_spell", "whenever",
                    subject=ast.ObjectFilter(colors=tuple(colors)),
                )
        stream.reset(mark)
        for kind, phrase in _WHENEVER_EVENTS:
            if stream.accept_phrase(*phrase):
                return ast.TriggerEvent(kind, "whenever")
        return _parse_quantified_tap_event(stream)
    if stream.accept_word("at"):
        for kind, phrase in _AT_EVENTS:
            if stream.accept_phrase(*phrase):
                return ast.TriggerEvent(kind, "at")
        return None
    if stream.accept_word("when"):
        if stream.accept_phrase("this", "creature", "dies"):
            return ast.TriggerEvent("dies", "when")
        if stream.accept_phrase("you", "control", "no", "islands"):
            return ast.TriggerEvent("no_islands", "when")
        if stream.accept_phrase("you", "control", "no", "lands"):
            return ast.TriggerEvent("no_lands", "when")
        mark = stream.mark()
        if stream.at_kind(SELF) or stream.at_word("this"):
            stream.advance()
            if not stream.at_kind(SELF):
                stream.accept_word("creature", "artifact", "enchantment", "land", "aura")
            if stream.accept_word("enters"):
                stream.accept_phrase("the", "battlefield")
                return ast.TriggerEvent("enters_battlefield", "when")
            if stream.accept_word("leaves"):
                stream.accept_phrase("the", "battlefield")
                return ast.TriggerEvent("leaves_battlefield", "when")
        stream.reset(mark)
        return None
    return None


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
_RIDER_FOLDED = ast.RawEffect("rider-folded")


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


def _parse_conditional_instead_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """``You gain 4 life. If a creature died this turn, you gain 8 life
    instead.`` (Life Goes On.)

    The second sentence *replaces* the first when its condition holds, so the
    pair folds into one ``Conditional`` — then the bigger gain, otherwise the
    printed base. Parsed apart, the two sentences would gain 12 life on a
    death; the "instead" is the whole content of the sentence, so it is
    required, and only a same-shaped statement may replace the last step.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.GainLife):
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
    if not isinstance(replacement, ast.GainLife) or not stream.accept_word("instead"):
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


def _statements_from_sentences(stream: TokenStream) -> ast.Statement:
    """Parse the remaining tokens as one or more sentences, joining them into a
    ``Sequence``. A rider sentence folds into the effect it modifies instead of
    becoming a step of its own."""
    steps: list[ast.Statement] = []
    while not stream.exhausted:
        if stream.accept_punct(".", ";", ","):
            continue
        # A sentence opening with "Then …" ("Create a 3/3 green Beast creature
        # token. Then if an opponent controls more creatures than you, …",
        # Garruk, Unleashed) — sequencing the sentence loop already provides.
        if steps and stream.accept_word("then"):
            continue

        if steps:
            riders = _parse_damage_rider_sentence(stream)
            if riders is not None:
                steps[-1] = _attach_riders(steps[-1], riders)
                continue
            penalty = _parse_unpaid_penalty_sentence(stream)
            if penalty is not None:
                steps[-1] = _attach_unpaid_penalty(steps[-1], penalty)
                continue
            if _attach_if_you_do(stream, steps):
                continue
            pronoun_grant = _parse_pronoun_grant_rider(stream, steps)
            if pronoun_grant is not None:
                if pronoun_grant is not _RIDER_FOLDED:
                    steps.append(pronoun_grant)
                continue
            who_cant = _parse_who_cant_rider(stream, steps)
            if who_cant is not None:
                steps.append(who_cant)
                continue
            if _parse_exile_instead_rider(stream, steps):
                continue
            if _parse_conditional_instead_rider(stream, steps):
                continue
            controller_token = _parse_its_controller_creates_rider(stream, steps)
            if controller_token is not None:
                steps.append(controller_token)
                continue
            # A trailing "Activate only during your upkeep." belongs to the
            # ability, not to the effect. Consuming it here keeps the line
            # fully accounted for; enforcement stays on the raw text.
            if _parse_activation_restriction(stream) is not None:
                continue

        steps.append(parse_statement(stream))
        if not stream.exhausted and not stream.at_punct(".", ";"):
            raise stream.error("unconsumed text")

    if not steps:
        raise GrammarError("empty line", line=stream.line)
    return steps[0] if len(steps) == 1 else ast.Sequence(tuple(steps))


def _attach_if_you_do(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "If you do, …" / "If you don't, …" into the preceding ``May``.

    These are branches of the optional action, not steps of their own: "You may
    pay {1}. If you do, you gain 1 life." is one decision with a consequence.
    Parsing them as separate sentences would make the life gain unconditional —
    the same class of mistake as treating "you may pay {2}" as a plain cost.
    """
    if not isinstance(steps[-1], ast.May):
        return False
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

    may = steps[-1]
    steps[-1] = ast.May(
        actor=may.actor,
        cost=may.cost,
        action=may.action,
        then=branch if not declined else may.then,
        otherwise=branch if declined else may.otherwise,
    )
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
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.exhausted or not _looks_static(statement):
        stream.reset(mark)
        return None
    return ast.StaticAbilityNode(statement, condition)


_EMBLEM_LINE_RE = re.compile(
    r'^\s*you get an emblem with\s+["“](?P<text>.+)["”]\.?\s*$',
    re.IGNORECASE | re.DOTALL,
)

# "Until end of turn, creatures you control gain "You may have this creature
# assign its combat damage as though it weren't blocked."" (Garruk, Savage
# Herald's −7.) The quoted grant is matched whole: the granted sentence IS the
# effect, so a paraphrase is a different card and must keep refusing.
_ASSIGN_UNBLOCKED_LINE_RE = re.compile(
    r'^\s*until end of turn, creatures you control gain\s+'
    r'["“]you may have this creature assign its combat damage as though it '
    r'wasn.t blocked\.?["”]\.?\s*$'
    .replace("wasn.t", r"(?:wasn|weren)['’]t"),
    re.IGNORECASE,
)


def _parse_emblem_line(line: str) -> "ast.CreateEmblem | None":
    """The whole-line emblem shape, read off the raw text.

    Raw rather than token-by-token because the payload IS the raw text: the
    quoted ability keeps its printed casing and punctuation, which is what the
    compiler will read when the emblem fires.
    """
    match = _EMBLEM_LINE_RE.match(line.strip())
    if match is None:
        return None
    return ast.CreateEmblem(text=match.group("text").strip())


def parse_line(line: str, *, card_name: str | None = None) -> ast.AbilityNode:
    """Parse one oracle-text line into an :class:`AbilityNode`.

    Raises :class:`GrammarError` when the line cannot be accounted for in full.

    The derivation tables (``engine/grammar/derived.py``) are consulted **only**
    once every production has refused the line. That ordering is the whole
    safety argument for them: a table matching on text is exactly the shape this
    migration is deleting, so it may only ever reach sentences no production
    could read, and can never shadow one. ``engine/lord_buffs.py`` would happily
    claim "Other Goblins get +1/+1" — it never gets the chance, because that
    line parses.
    """
    try:
        return _parse_line(line, card_name=card_name)
    except GrammarError:
        derived = derived_instruction_for_line(line)
        if derived is not None:
            return ast.DerivedLine(derived[0], line)
        raise


def _parse_line(line: str, *, card_name: str | None = None) -> ast.AbilityNode:
    lexed = tokenize(line, card_name=card_name)
    if not lexed.tokens:
        raise GrammarError("empty line", line=line)

    # A single leading bullet is one mode's clause, handed here by the
    # compiler's mode assembly; parse it as an ordinary effect line. The head
    # that precedes those bullets is an ordinary line too — `_parse_modal_head`
    # reads it, and the dash it ends with is a token like any other, so nothing
    # is rejected here on the sight of one. (It was: every em dash in the pool
    # failed the line as a "modal line", which is why an ability word — "Battalion
    # — Whenever …", CR 207.2c — was filed under the modal backlog.)
    #
    # Several bullets on one line is a different thing: the mode list arriving
    # collapsed into a single string, where the parser cannot tell one mode's
    # tokens from the next's.
    bullets = sum(1 for token in lexed.tokens if token.kind == BULLET)
    start = 0
    if bullets == 1 and lexed.tokens[0].kind == BULLET:
        start = 1
    elif bullets:
        raise GrammarError("several modal bullets on one line", line=line)
    if any(token.kind == QUOTE for token in lexed.tokens):
        # "You get an emblem with "<ability>"." (CR 114.2) — the one quoted
        # shape with a production. The quoted ability is carried as raw text
        # and compiled when the emblem fires; the walker's support gate
        # compiles it up front, so an unreadable emblem text still refuses the
        # card rather than shipping an emblem that does nothing.
        emblem = _parse_emblem_line(line)
        if emblem is not None:
            return ast.SpellEffectLine(emblem)
        if _ASSIGN_UNBLOCKED_LINE_RE.match(line.strip()):
            return ast.SpellEffectLine(
                ast.RawEffect("grant_team_assign_unblocked_until_eot")
            )
        raise GrammarError("granted ability in quotes", line=line)

    body = lexed.tokens[start:]
    stream = TokenStream(body, line)

    keywords = _is_keyword_line(stream)
    if keywords is not None and stream.exhausted:
        return ast.KeywordLine(keywords)
    stream.reset(0)

    # Lines a text-keyed registry runs off the raw oracle text. Checked against
    # the *original* line, not the lexed tokens: that is the string the
    # registries themselves match on.
    registry_line = _parse_registry_line(stream, line)
    if registry_line is not None:
        return registry_line
    stream.reset(0)

    colon = _split_on_colon(body)
    if colon is not None:
        costs = _parse_costs(TokenStream(body[:colon], line))
        effect_stream = TokenStream(body[colon + 1:], line)
        statement = _statements_from_sentences(effect_stream)
        return ast.ActivatedAbilityNode(costs, statement)

    event = _parse_trigger_event(stream)
    if event is not None:
        stream.accept_punct(",")
        intervening: ast.Condition | None = None
        if stream.at_word("if"):
            mark = stream.mark()
            stream.advance()
            try:
                intervening = _parse_condition(stream)
                stream.accept_punct(",")
            except GrammarError:
                stream.reset(mark)
                intervening = None
        statement = _statements_from_sentences(stream)
        return ast.TriggeredAbilityNode(event, statement, intervening)
    stream.reset(0)

    # "…as long as <condition>" is a whole-line shape: the condition qualifies
    # the ability, not one sentence of it. Tried before the sentence loop
    # because that loop would read the effect, find "as" unaccounted for, and
    # fail the line on unconsumed text.
    static_condition = _parse_static_condition_line(stream)
    if static_condition is not None:
        return static_condition

    statement = _statements_from_sentences(stream)
    if _looks_static(statement):
        return ast.StaticAbilityNode(statement)
    return ast.SpellEffectLine(statement)


__all__ = ["parse_line", "parse_statement"]
