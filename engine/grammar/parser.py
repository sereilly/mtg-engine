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
    costs        the clause left of an activated ability's colon
    parser       one printed line          <- you are here

The split follows the banners the file already carried. Two corrections came
out of the dependency graph rather than out of reading it: four effect
productions had drifted down into the line section and were the only cycle, and
two fragment productions filed as effects were the only thing coupling the
effect families. Nothing changed but where the code lives — held to that by a
whole-pool snapshot of every compiled program and every line's parse result,
diffed before and after.
"""

import dataclasses
import re
from dataclasses import replace

from ..oracle_types import strip_ability_word
from . import ast
from .amounts import parse_amount
from .derived import derived_instruction_for_line
from .errors import GrammarError
from .lexer import (BULLET, MANA, PT, PUNCT, QUOTE, SELF, tokenize)
from .costs import _parse_costs
from .nouns import (parse_target_spec)
from .registries import registry_for_line
from .stream import TokenStream
from .vocabulary import (COLOR_WORDS, KEYWORD_INDEX, match_longest)
from .phrases import (
    _parse_trigger_event,
)
from .effects import (
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


def _split_on_colon(tokens: tuple) -> int | None:
    for index, token in enumerate(tokens):
        if token.kind == PUNCT and token.text == ":":
            return index
    return None


# The type words a cast-trigger narrowing may consume ("…you cast a
# noncreature spell"), mapped to the filter each means. Held to the words the
# event filter can test against a cast card's type line — mirroring the oracle
# trigger table's alternation — and deliberately without "enchantment", whose
# printed article ("an") belongs to its own condition kind.
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


def _parse_registry_claimed_sentence(stream: TokenStream) -> bool:
    """Consume a trailing sentence a text-keyed registry implements end to end.

    "{5}{W}: Tap target creature. **This ability costs {1} less to activate for
    each Shrine you control.**" (Sanctum of Tranquil Light.) The reduction is a
    whole sentence inside an activated ability's printed line, and it is not an
    effect — `engine/cost_modifiers.py` applies it while the cost is being paid,
    so there is nothing here for a production to lower.

    The claim **delegates to the implementing code** rather than restating its
    words, which is the rule `engine/grammar/registries.py` states for the
    whole-line case: a copy of the phrase here would be free to drift, and a
    drifted copy would consume a sentence nothing runs. The sentence's own source
    text is sliced back out of the line through the tokens' offsets and handed to
    the registry's matcher.
    """
    from ..cost_modifiers import cost_modifier_claims_line

    mark = stream.mark()
    start_token = stream.peek()
    if start_token is None:
        return False
    end = start_token.end
    while not stream.exhausted:
        token = stream.peek()
        if token is None:
            break
        if token.kind == PUNCT and token.text == ".":
            break
        end = token.end
        stream.advance()
    text = stream.line[start_token.start:end]
    if cost_modifier_claims_line(text):
        stream.accept_punct(".")
        return True
    stream.reset(mark)
    return False


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
            # A sentence a text-keyed registry runs, rather than an effect. It
            # contributes no step, which is the point: the words are accounted
            # for and the table does the work.
            if _parse_registry_claimed_sentence(stream):
                continue
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
            if _attach_when_you_do(stream, steps):
                continue
            if _attach_spend_only(stream, steps):
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
    # "You may draw X cards, where X is …. If you do, discard a card."
    # (Sanctum of Calm Waters.) The where-clause wraps the whole sentence, so
    # the May is one level down — lifted off here and put back on outside the
    # fold, because the definition binds the branch as well as the offer.
    target = steps[-1]
    definition = target.definition if isinstance(target, ast.WhereX) else None
    if definition is not None:
        target = target.statement
    if not isinstance(target, ast.May):
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
    the *previous* sentence's mana may pay for (CR 106.6b). Parsed as its own
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
    # CR 207.2c: an ability word is italic flavour with no rules meaning, so it
    # is dropped before anything reads the line. Both front ends drop it, from
    # the same function — a word stripped on one side only is a line whose two
    # halves disagree about what was printed.
    line = strip_ability_word(line)
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
