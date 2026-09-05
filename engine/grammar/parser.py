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
from .derived import derived_instruction_for_line
from .errors import GrammarError
from .lexer import (BULLET, PUNCT, QUOTE, tokenize)
from .costs import _parse_costs
from .registries import registry_for_line
from .pronouns import (_RIDER_FOLDED, _attach_returned_text_change,
                       _attach_sacrifice_when_control_lost,
                       _parse_conditional_pronoun_grant_rider,
                       _parse_conditional_quoted_grant_rider,
                       _parse_exile_instead_of_leaving_rider,
                       _parse_pronoun_counter_rider,
                       _parse_pronoun_grant_rider, _parse_pronoun_verb_rider)
from .control_flow import (_attach_if_that_card_was_returned, _attach_if_you_cant,
                          _attach_if_you_do, _attach_otherwise, _attach_when_you_do)
from .repeats import (_attach_repeat_for_types,
                      _attach_repeat_optional_process,
                      _attach_repeat_this_process)
from .riders import (_attach_destroyed_this_way, _attach_no_regeneration,
    _attach_unaffected_when_cost_paid, _attach_exchanged_this_way, _attach_tap_when_control_lost, _attach_riders, _attach_source_damage_lock, _attach_counter_cap, _attach_new_target_bound, _attach_spend_only, _attach_unpaid_penalty, _parse_conditional_instead_rider, _parse_exile_instead_rider, _parse_its_controller_creates_rider, _parse_that_controller_reveals_rider, _parse_who_cant_rider)
from .static_lines import (_looks_static, _parse_leading_static_condition_line,
                           _parse_static_condition_line,
                           _parse_turn_scoped_static_line)
from .stream import TokenStream
from .vocabulary import (KEYWORD_INDEX, match_longest)
from .rebinding import (bind_recorded_card,
                        rebind_alternative_pronoun_to_choice_target,
                        rebind_keyword_loss_pronoun_to_clause_target,
                        rebind_attachment_pronoun_to_sentence_target,
                        rebind_delayed_pronoun_to_sentence_target,
                        rebind_pump_pronoun_to_sentence_target,
                        rebind_pronoun_to_event_subject)
from .triggers import _parse_trigger_event
from .effects import (
    _parse_activation_restriction,
    _parse_x_spend_restriction,
    _parse_cost_x_definition,
    _parse_damage_rider_sentence,
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


def _parse_registry_line(
    stream: TokenStream, line: str, card_name: str | None = None
) -> ast.RegistryLine | None:
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
    registry = registry_for_line(line, card_name)
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










def _parse_quoted_token_line(stream: TokenStream) -> ast.Statement | None:
    """A token-creating sentence whose ``with`` clause holds quoted abilities,
    or None when the line is something else.

    Its own entry point because the quote guard above runs before the ordinary
    statement dispatch: without this, every such line would be refused for
    containing a quote at all.
    """
    mark = stream.mark()
    # The quoted token may be the whole line ("Create a … token with …") or the
    # effect half of a trigger ("When this creature enters, each opponent
    # creates a … token with …"), and Pursued Whale prints the second. The
    # trigger prefix is read first so the statement behind it sees the sentence
    # it would have seen on a line of its own.
    event = _parse_trigger_event(stream)
    if event is not None:
        stream.accept_punct(",")
    # Every sentence, not one. This read a single statement and then accepted a
    # trailing full stop as the end of the line, which silently dropped every
    # word behind it — Tetravus prints three sentences ("…you may remove any
    # number of +1/+1 counters… If you do, create that many … tokens. They each
    # have flying and "This token can't be enchanted."") and compiled to the
    # first one alone. The quote guard above routes any line carrying a quote
    # here, so this was the one production in the grammar that could return a
    # partial match instead of raising.
    #
    # The full stop inside the quoted ability is not a sentence boundary here:
    # the token production consumes a quoted line whole, closing quote included,
    # before this loop sees the tokens again.
    try:
        statement = _statements_from_sentences(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.exhausted:
        stream.reset(mark)
        return None
    if event is not None:
        return ast.TriggeredAbilityNode(
            event, rebind_pronoun_to_event_subject(event, statement)
        )
    return statement








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


def _sentence_ended_on_a_quote(stream: TokenStream) -> bool:
    """Whether the sentence just read ended on a closing quotation mark.

    "…that creature gains "Remove a matrix counter from this creature:
    Regenerate this creature." **Activate only during your upkeep.**" (Life
    Matrix.) Magic prints the sentence's full stop *inside* the quoted ability,
    so the quoted ability's own terminator ends the outer sentence as well and
    there is no bare "." left for the loop below to see. Without this the words
    behind the quote read as unconsumed text and the whole line refuses — which
    is the loud failure this parser wants everywhere the boundary is genuinely
    missing, and exactly the wrong answer where the card printed one.
    """
    previous = stream.peek(-1)
    return previous is not None and previous.kind == QUOTE


def _attach_granted_ability_permission(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold a trailing "who may activate" sentence into the ability the step
    before it granted, and say whether one was found.

    "Until end of turn, target creature you control gains "{0}: …" **Only you
    may activate this ability.**" (Martyrdom.) The permission is about the
    granted ability, not about the spell: what reaches the battlefield is the
    quoted line, and `engine/keywords.py` records exactly that string for
    `Permanent.effective_card` to fold in and the compiler to read. A clause
    left outside it belongs to a spell that is in its owner's graveyard by the
    time anyone activates — read there it would restrict nothing.

    So the sentence is appended to the quoted text, which is the same rewrite
    `oracle.expand_equip_lines` makes one layer up and for the same reason:
    every reader of what the creature now says has to see the same sentence.
    `engine/activation_permissions.py` is asked first, so a permission that
    module does not implement leaves the line refused rather than consumed and
    dropped.

    Only a grant with **one** quoted ability is claimed. A sentence naming
    "this ability" after two of them names one of the two and the card would
    have to say which; nothing prints that, and guessing is what this refuses.
    """
    from ..activation_permissions import permission_clause_readable

    if not steps or not isinstance(steps[-1], ast.GainAbilityText):
        return False
    grant = steps[-1]
    if len(grant.abilities) != 1:
        return False
    mark = stream.mark()
    stream.accept_punct(".", ";")
    if not stream.at_word("any", "only"):
        stream.reset(mark)
        return False
    words: list[str] = []
    while not stream.exhausted and not stream.at_punct("."):
        words.append(str(stream.next().text))
    sentence = " ".join(words).replace(" '", "'")
    if not permission_clause_readable(sentence):
        stream.reset(mark)
        return False
    stream.accept_punct(".")
    steps[-1] = dataclasses.replace(
        grant, abilities=(f"{grant.abilities[0]}. {sentence.capitalize()}",)
    )
    return True


def _parse_statement_alternatives(
    stream: TokenStream, first: ast.Statement, first_at: int
) -> ast.Statement:
    """*first*, or an :class:`ast.OneOf` if the sentence goes on with "**or**".

    "Put a +1/+1 counter on target creature **or** that creature gains banding,
    first strike, or trample." (Nature's Blessing.) One action with two ways to
    take it, the controller choosing which as the effect is applied
    (CR 608.2d) — not a `Sequence`, which does both, and not a modal spell's
    bulleted "Choose one —", which is chosen as the spell is cast (CR 601.2b).

    ``statements._parse_optional_action`` already reads this shape behind "you
    may" (Crypt Lurker) and its docstring records why it was written there and
    not at large: a statement-level "or" is rare, and putting a production in
    front of every sentence in the game on the strength of one card is a bad
    trade. What makes this position safe is not the count of cards but *where
    it sits*: the statement has already been parsed and the cursor is on a word
    that is neither a full stop nor a semicolon, which is the state the line
    fails in three lines further down. So this can only claim text that is
    being refused today.

    An alternative that does not parse is left alone — the cursor rewinds and
    the "unconsumed text" refusal below stands, naming the same offset it names
    now.
    """
    if not stream.at_word("or"):
        return first
    options: list[ast.Statement] = [first]
    spans: list[tuple[int, int]] = [(first_at, stream.pos)]
    while stream.at_word("or"):
        mark = stream.mark()
        stream.advance()
        start = stream.pos
        try:
            options.append(parse_statement(stream, top_level=False))
        except GrammarError:
            stream.reset(mark)
            break
        spans.append((start, stream.pos))
    if len(options) == 1:
        return first
    return rebind_alternative_pronoun_to_choice_target(
        ast.OneOf(
            tuple(options), tuple(stream.text_between(a, b) for a, b in spans)
        )
    )


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
            if _attach_if_that_card_was_returned(stream, steps):
                continue
            if _attach_if_you_cant(stream, steps):
                continue
            if _attach_when_you_do(stream, steps):
                continue
            # "Repeat this process until no one puts a card onto the
            # battlefield." (Eureka.) A clause about the sentence before it,
            # folded into that sentence the way every other rider here is.
            if _attach_repeat_this_process(stream, steps):
                continue
            # "You may repeat this process any number of times." (Forbidden
            # Ritual.) The same word about *every* sentence read so far rather
            # than about the last one, and a different mechanism behind it —
            # see `engine/grammar/repeats.py`, which holds both and says why
            # they are not one production.
            if _attach_repeat_optional_process(stream, steps):
                continue
            # "Repeat this process for artifacts and creatures." (Equipoise.)
            # The same word again and a third mechanism behind it: a printed
            # list of parameters rather than a loop.
            if _attach_repeat_for_types(stream, steps):
                continue
            # "Otherwise, it gets +4/-X until end of turn." (Blood Lust.) The
            # second arm of the conditional sentence before it.
            if _attach_otherwise(stream, steps):
                stream.accept_punct(".")
                continue
            # "This ability can't cause the total number of +1/+0 counters on
            # this creature to be greater than N." (the Clockwork cycle.) A
            # bound on the sentence before it, not a step.
            # "If this creature is destroyed this way, it deals 7 damage to
            # you." (Cosmic Horror.) A consequence of what the sentence before
            # it did, not a step.
            if _attach_destroyed_this_way(stream, steps):
                stream.accept_punct(".")
                continue
            # "A creature destroyed this way can't be regenerated." (Soul Rend.)
            # CR 701.15c's rider on a destroy the sentence layer has already
            # wrapped in a conditional, which is why the destroy production's
            # own probe of the same words could not reach it.
            if _attach_no_regeneration(stream, steps):
                stream.accept_punct(".")
                continue
            # "If this spell's additional cost was paid, this effect doesn't
            # affect combat damage that would be dealt by red creatures."
            # (Undergrowth.) A width on the prevention the sentence before it
            # created, not a step: "this effect" names that one and nothing
            # else.
            if _attach_unaffected_when_cost_paid(stream, steps):
                stream.accept_punct(".")
                continue
            # "When you lose control of the creature, tap it." (Ray of
            # Command.) CR 603.7's delayed trigger on the control change the
            # sentence before it made — a clause about that sentence, not a
            # step: alone, "the creature" names nothing.
            # "Sacrifice the creature when you lose control of this creature."
            # (Seraph, Krovikan Vampire.) The same CR 603.7 delay one verb over,
            # and read beside its sibling so the two spellings of "when you lose
            # control" stay together — but folded onto a battlefield *entry*
            # rather than onto a control change, which is why it is its own
            # production and lives with the pronoun binders.
            if _attach_sacrifice_when_control_lost(stream, steps):
                continue
            if _attach_tap_when_control_lost(stream, steps):
                stream.accept_punct(".")
                continue
            # "If those permanents are exchanged this way, destroy all Auras
            # attached to them." (Gauntlets of Chaos.) Same shape, same reason.
            if _attach_exchanged_this_way(stream, steps):
                stream.accept_punct(".")
                continue
            if _attach_counter_cap(stream, steps):
                stream.accept_punct(".")
                continue
            # "The new target must be a player." (Reflecting Mirror.) A bound on
            # the choice the sentence before it will make at resolution, not a
            # step of its own.
            if _attach_new_target_bound(stream, steps):
                stream.accept_punct(".")
                continue
            if _attach_spend_only(stream, steps):
                continue
            pronoun_verb = _parse_pronoun_verb_rider(stream, steps)
            if pronoun_verb is not None:
                steps.append(pronoun_verb)
                continue
            # "…and put a -1/-0 counter on **it**." (Jabari's Influence.) The
            # counter's own pronoun, beside the imperative one above: parsed
            # fresh, "it" is the ability's source and the counter lands on the
            # wrong permanent — or, for a spell, on nothing at all.
            pronoun_counter = _parse_pronoun_counter_rider(stream, steps)
            if pronoun_counter is not None:
                steps.append(pronoun_counter)
                continue
            # "It loses "enchant creature" and gains "…"." (Takklemaggot.) The
            # quoted half, read before the keyword rider below, whose "It
            # loses …" reading is about a keyword and would refuse a quote.
            if _attach_returned_text_change(stream, steps):
                stream.accept_punct(".")
                continue
            pronoun_grant = _parse_pronoun_grant_rider(stream, steps)
            if pronoun_grant is not None:
                if pronoun_grant is not _RIDER_FOLDED:
                    steps.append(pronoun_grant)
                continue
            conditional_grant = _parse_conditional_pronoun_grant_rider(stream, steps)
            if conditional_grant is not None:
                steps.append(conditional_grant)
                continue
            # "If it doesn't have "<ability>," it gains that ability."
            # (Musician.) The quoted twin of the rider above, read after it
            # because that one's condition parser would refuse a quote and
            # rewind — leaving this sentence to fail the whole line.
            quoted_grant = _parse_conditional_quoted_grant_rider(stream, steps)
            if quoted_grant is not None:
                steps.append(quoted_grant)
                continue
            who_cant = _parse_who_cant_rider(stream, steps)
            if who_cant is not None:
                steps.append(who_cant)
                continue
            # "If the creature would leave the battlefield, exile it instead
            # of putting it anywhere else." (Dreams of the Dead.) Read before
            # the two "instead" riders below, whose own openings would consume
            # the "if" and rewind — leaving this sentence to fail the line.
            if _parse_exile_instead_of_leaving_rider(stream, steps) is not None:
                continue
            if _parse_exile_instead_rider(stream, steps):
                continue
            if _parse_conditional_instead_rider(stream, steps):
                continue
            # "If <the source> would deal damage to a creature, that damage
            # can't be prevented or dealt instead to another permanent or
            # player." (Lava Burst.) A statement about the damage the sentence
            # in front of it deals, so it folds into that sentence's riders.
            if _attach_source_damage_lock(stream, steps):
                stream.accept_punct(".")
                continue
            reveals = _parse_that_controller_reveals_rider(stream, steps)
            if reveals is not None:
                steps.append(reveals)
                continue
            controller_token = _parse_its_controller_creates_rider(stream, steps)
            if controller_token is not None:
                steps.append(controller_token)
                continue
            # "…gains "<ability>." **Only you may activate this ability.**"
            # (Martyrdom.) A sentence about the *granted* ability, printed
            # outside the quotes because the quotes hold what the creature
            # gains and this says who may use it — so it folds into the quoted
            # text rather than becoming a step. Read before the trailing
            # restriction below, which would consume the same sentence and
            # record it on a **spell**: the spell is in a graveyard by the time
            # anybody activates, so the clause would be enforced by nobody.
            if _attach_granted_ability_permission(stream, steps):
                continue
            # A trailing "Activate only during your upkeep." belongs to the
            # ability, not to the effect. Consuming it here keeps the line
            # fully accounted for; enforcement stays on the raw text.
            if _parse_activation_restriction(stream) is not None:
                continue
            # A trailing "X is the number of pin counters on this artifact."
            # belongs to the ability's *cost*, not to its effect — same
            # arrangement, same reason, and enforcement likewise stays on the
            # raw text (engine/cost_x_definitions.py).
            if _parse_cost_x_definition(stream) is not None:
                continue
            # A trailing "Spend only red mana on X." (Crimson Hellkite) belongs
            # to the cost too — the third of the same family, consumed here and
            # charged by the activation path off the raw text.
            if _parse_x_spend_restriction(stream) is not None:
                continue

        sentence_at = stream.pos
        statement = parse_statement(stream)
        # "Destroy this enchantment **if it has five or more hunger counters on
        # it**." (Fasting.) The trailing spelling of the "if <condition>,
        # <statement>" sentence `statements.py` already reads — one clause, one
        # meaning, printed at the other end. It is folded here rather than
        # inside `parse_statement` because the condition modifies the whole
        # sentence, and a production that consumed it would have to be written
        # once per verb.
        #
        # Refusing without consuming (the reset below) is what keeps every
        # other "if" reading intact: a clause `_parse_condition` cannot describe
        # falls through to the "unconsumed text" error it already raised, rather
        # than being silently dropped off a card that would then destroy itself
        # unconditionally.
        if not stream.exhausted and stream.at_word("if"):
            if_mark = stream.mark()
            stream.advance()
            try:
                condition = _parse_condition(stream)
            except GrammarError:
                stream.reset(if_mark)
            else:
                statement = ast.Conditional(condition, statement)
        statement = _parse_statement_alternatives(stream, statement, sentence_at)
        steps.append(statement)
        if (
            not stream.exhausted
            and not stream.at_punct(".", ";")
            and not _sentence_ended_on_a_quote(stream)
        ):
            raise stream.error("unconsumed text")

    if not steps:
        raise GrammarError("empty line", line=stream.line)
    # One sentence has nothing in front of it to refer back to; a sequence
    # does, and this is the one place a whole printed line's sentences are in
    # hand. It runs here rather than in `parse_line`'s tail because an
    # activated ability's effect never reaches that tail -- and an activated
    # ability is exactly where Orcish Captain prints the pronoun.
    # The cross-*clause* pronoun, which a one-sentence line can also print:
    # "…and that creature loses flying until end of turn" (Burning Palm
    # Efreet). Run over every line rather than only over a multi-sentence one,
    # because the `Sequence` it reads is the one `statements.py` built from an
    # "and" join inside a single sentence.
    if len(steps) == 1:
        return rebind_keyword_loss_pronoun_to_clause_target(steps[0])
    sequence = rebind_keyword_loss_pronoun_to_clause_target(
        rebind_pump_pronoun_to_sentence_target(ast.Sequence(tuple(steps)))
    )
    # The other cross-sentence pronoun, and the same argument: "remove all
    # -1/-1 counters from **the creature**" (Giant Oyster) names the creature
    # the sentence in front of it chose, and read as the bare source pronoun it
    # empties the ability's own permanent instead. Composed rather than folded
    # into the walk above, because the two rewrite different nodes under
    # different conditions — see `rebinding.py` for why each is narrow.
    return rebind_delayed_pronoun_to_sentence_target(sequence)












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


#: The reanimation Aura's entry line, whole (Animate Dead, Dance of the Dead) —
#: a whole-line pattern for the reason the emblem shape below is one: the
#: quotation marks are part of what the sentence says, and the three sentences
#: are one effect on one object rather than three statements. The two printings
#: differ by one verb and one word of timing, which is what makes this a
#: template rather than a card, and what retired the name-keyed hook that used
#: to claim the first of them. Exact on purpose: a card printing one of the
#: three sentences and not the others is a different card.
_REANIMATION_AURA_LINE_RE = re.compile(
    r'^\s*when this (?:aura|enchantment) enters, if it.s on the battlefield, '
    r'it loses ["“]enchant creature card in a graveyard["”] and gains '
    r'["“]enchant creature put onto the battlefield with this '
    r'(?:aura|enchantment)\.?["”]\.?\s*'
    r'(?:return|put) enchanted creature card (?:to|onto) the battlefield '
    r'(?P<tapped>tapped )?under your control and attach this '
    r'(?:aura|enchantment) to it\.\s*'
    r'when this (?:aura|enchantment) leaves the battlefield, '
    r'that creature.s controller sacrifices it\.?\s*$',
    re.IGNORECASE,
)


def _parse_reanimation_aura_line(line: str) -> "ast.TriggeredAbilityNode | None":
    """The reanimation Aura's entry line as one triggered ability, or None.

    Off the raw text, as the emblem shape below is: what the pattern pins down
    is the quoted rewrite and the sentence order, both of them punctuation the
    token stream has already discarded.
    """
    match = _REANIMATION_AURA_LINE_RE.match(line.strip())
    if match is None:
        return None
    return ast.TriggeredAbilityNode(
        ast.TriggerEvent(kind="enters_battlefield", word="when"),
        ast.ReanimateEnchantedCard(tapped=bool(match.group("tapped"))),
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
        # The reanimation Aura's whole entry line (Animate Dead, Dance of the
        # Dead), before the token paths below: they see three sentences where
        # the card states one deal, and would refuse the quoted rewrite anyway.
        reanimation = _parse_reanimation_aura_line(lexed.source)
        if reanimation is not None:
            return reanimation
        if _ASSIGN_UNBLOCKED_LINE_RE.match(line.strip()):
            return ast.SpellEffectLine(
                ast.RawEffect("grant_team_assign_unblocked_until_eot")
            )
        # "…creates a 1/1 red Pirate creature token **with "This token can't
        # block" and "Creatures you control attack each combat if able.""**
        # (Pursued Whale.) A token whose abilities are printed lines rather than
        # keywords, which the token production reads — so the line is given to
        # the ordinary parser rather than refused for containing a quote.
        #
        # Tried last, after the emblem shape above: both carry quoted text, and
        # the difference is which production claims the words around it.
        #
        # The quoted token may also be the effect of an *activated* ability
        # ("{4}, {T}: Create a … token. It has "…"", Serpent Generator). The
        # quote guard routes the whole line here before the ordinary colon
        # split below can see it, so the cost prefix is read the same way —
        # but only a colon left of the first quote is an activation colon; one
        # inside the quotes belongs to the granted ability's own text.
        body = lexed.tokens[start:]
        first_quote = next(i for i, token in enumerate(body) if token.kind == QUOTE)
        colon = _split_on_colon(body[:first_quote])
        if colon is not None:
            costs = _parse_costs(TokenStream(body[:colon], lexed.source))
            effect = _parse_quoted_token_line(
                TokenStream(body[colon + 1:], lexed.source)
            )
            if effect is not None and not isinstance(effect, ast.TriggeredAbilityNode):
                return ast.ActivatedAbilityNode(costs, effect)
            raise GrammarError("granted ability in quotes", line=line)
        token_line = _parse_quoted_token_line(TokenStream(body, lexed.source))
        if token_line is not None:
            # Already a whole ability line when a trigger prefix was read;
            # otherwise a bare effect that still needs wrapping.
            if isinstance(token_line, ast.TriggeredAbilityNode):
                return token_line
            return ast.SpellEffectLine(token_line)
        raise GrammarError("granted ability in quotes", line=line)

    body = lexed.tokens[start:]
    # `lexed.source`, never the raw *line*: the tokens' offsets index the string
    # the lexer walked, and a production recovering a printed span through
    # `text_between` slices this. See `LexResult.source`.
    stream = TokenStream(body, lexed.source)

    keywords = _is_keyword_line(stream)
    if keywords is not None and stream.exhausted:
        return ast.KeywordLine(keywords)
    stream.reset(0)

    # Lines a text-keyed registry runs off the raw oracle text. Checked against
    # the *original* line, not the lexed tokens: that is the string the
    # registries themselves match on.
    registry_line = _parse_registry_line(stream, line, card_name)
    if registry_line is not None:
        return registry_line
    stream.reset(0)

    colon = _split_on_colon(body)
    if colon is not None:
        costs = _parse_costs(TokenStream(body[:colon], lexed.source))
        effect_stream = TokenStream(body[colon + 1:], lexed.source)
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
        return ast.TriggeredAbilityNode(
            event,
            # Two bindings, both of them about the whole line: which object a
            # bare pronoun names, and which event recorded the card "that card"
            # names. Only a reader holding the trigger, the intervening-if and
            # the effect at once can answer either.
            bind_recorded_card(
                event.kind, intervening,
                rebind_pronoun_to_event_subject(event, statement),
            ),
            intervening,
        )
    stream.reset(0)

    # "…as long as <condition>" is a whole-line shape: the condition qualifies
    # the ability, not one sentence of it. Tried before the sentence loop
    # because that loop would read the effect, find "as" unaccounted for, and
    # fail the line on unconsumed text.
    static_condition = _parse_static_condition_line(stream)
    if static_condition is not None:
        return static_condition

    # The same whole-line shape with the condition printed *first* ("As long as
    # there is exactly one tide counter on this creature, it gets -1/-1",
    # Homarid). Beside its mirror, and for the reason the turn-scoped one below
    # is here: the sentence loop would read "as" as the start of an effect and
    # fail the line on a subject it never finds.
    leading_condition = _parse_leading_static_condition_line(stream)
    if leading_condition is not None:
        return leading_condition
    stream.reset(0)

    # The same whole-line shape with the condition printed *first* as a timing
    # clause ("During your turn, …"). Tried here, beside its mirror, for the
    # same reason: the sentence loop would read "during" as the start of an
    # effect and fail the line on a subject it never finds.
    turn_scoped = _parse_turn_scoped_static_line(stream)
    if turn_scoped is not None:
        return turn_scoped
    stream.reset(0)

    statement = _statements_from_sentences(stream)
    if _looks_static(statement):
        return ast.StaticAbilityNode(statement)
    return ast.SpellEffectLine(
        rebind_attachment_pronoun_to_sentence_target(statement)
    )


__all__ = ["parse_line", "parse_statement"]
