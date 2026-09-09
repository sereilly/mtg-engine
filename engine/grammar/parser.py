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
registry-derived, quoted, static), what costs and trigger event does it carry,
and ``parse_line`` — the one entry point. **How its sentences join is not.**
That loop left for ``sequences`` at Urza's Legacy's Phase 0; what stays here is
the decision about *which* tokens are a sentence sequence — the half after an
activation colon, the half after a trigger's comma, the body of a quoted-token
line, or the whole line. The layers below, in strict dependency order, none
importing back:

    phrases      word tables, and productions that read a fragment
    effects/     one production per thing a card can do, one module per family
    statements   one whole sentence
    riders       a sentence about the sentence in front of it
    sequences    how a line's sentences join into one statement
    static_lines whole lines a *condition* frames rather than a verb
    quoted_lines whole lines their quotation marks delimit
    costs        the clause left of an activated ability's colon
    parser       one printed line          <- you are here

That first split followed the banners this file then carried, and two
corrections came out of the dependency graph rather than out of reading them:
four effect productions had drifted down into the line section and were the
only cycle, and two fragment productions filed as effects were the only thing
coupling the effect families. Every split since has been taken at the
thousand-line guard — ``costs``, ``riders``, ``static_lines``, ``quoted_lines``
and now ``sequences`` — and one banner survives, which is why the layer list
above is kept current instead. Nothing any of them changed but where the code
lives, held to that by a whole-pool snapshot of every compiled program diffed
before and after.
"""

from ..oracle_types import strip_ability_word
from . import ast
from .costs import _parse_costs
from .derived import derived_instruction_for_line
from .errors import GrammarError
from .lexer import (BULLET, PUNCT, QUOTE, tokenize)
from .quoted_lines import (_ASSIGN_UNBLOCKED_LINE_RE,
                           _parse_becomes_aura_line,
                           _parse_becomes_with_granted_ability,
                           _parse_emblem_line,
                           _parse_reanimation_aura_line)
from .rebinding import (bind_recorded_card,
                        rebind_attachment_pronoun_to_sentence_target,
                        rebind_pronoun_to_event_subject,
                        rebind_combat_role_to_event_subject)
from .registries import registry_for_line
# The sentence loop left for `sequences` at the thousand-line guard, and this
# import is also its re-export: the name keeps its old address, which is the
# courtesy `phrases` extends `prices` and `sentence_clauses` extends `tolls`.
# Only this one. The five readers that went with it — the registry-claimed
# sentence, the closing-quote probe, the granted-ability permission, and the
# statement-level "or" and its guard — are pulled by nothing outside
# `sequences`, and `tests/engine/test_import_hygiene.py` reads a re-export
# nobody pulls as the stale binding a move leaves behind. A re-export is for a
# caller that exists, not for one that might.
from .sequences import _statements_from_sentences
from .static_lines import (_looks_static, _parse_leading_static_condition_line,
                           _parse_static_condition_line,
                           _parse_turn_scoped_static_line)
from .stream import TokenStream
from .triggers import _parse_trigger_event
from .vocabulary import (KEYWORD_INDEX, match_longest)
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
            event,
            rebind_combat_role_to_event_subject(
                event, rebind_pronoun_to_event_subject(event, statement)
            ),
        )
    return statement


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
        # "It becomes an Aura with "enchant …."" (Necromancy) — the quoted
        # clause is one *sentence* of a longer trigger, so the production lifts
        # it out and hands the rest back to the ordinary parser. After the
        # reanimation shape above, which reads the same card family's other
        # printing whole.
        becomes_aura = _parse_becomes_aura_line(
            lexed.source, card_name=card_name, parse=_parse_line
        )
        if becomes_aura is not None:
            return becomes_aura
        # "…becomes a 4/4 Serpent creature with "This creature can't attack
        # unless defending player controls an Island."" (Veiled Serpent.) The
        # same lift, on a creature body rather than on an Aura's enchant
        # clause — after that one, whose sentence this pattern would also match
        # and would read as an animation the card does not print.
        becomes_granting = _parse_becomes_with_granted_ability(
            lexed.source, card_name=card_name, parse=_parse_line
        )
        if becomes_granting is not None:
            return becomes_granting
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
                rebind_combat_role_to_event_subject(
                    event,
                    rebind_pronoun_to_event_subject(
                        event, statement, intervening=intervening
                    ),
                ),
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
