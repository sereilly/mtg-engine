"""Statement productions: one whole sentence, assembled from effects.

Three productions and the layer they name. `_parse_subject_verb` reads the
common `<subject> <verb> …` shape and dispatches into `effects`;
`parse_statement` is the entry point for one sentence; `_parse_condition` reads
the condition half of a trigger or an intervening-if.

The narrow waist of the parser — below is a fragment, above is a *line*.
"""

from . import ast
from .errors import GrammarError
from .lexer import (SELF, WORD)
from .nouns import (parse_object_filter, parse_player_ref, parse_recipient)
from .stream import TokenStream
from .phrases import (
    _parse_duration,
    _parse_mana_payment,
)
from .effects import (
    _parse_add_mana,
    _parse_become_color,
    _parse_cant_attack_or_block,
    _parse_change_text,
    _parse_colour_source_prevention,
    _parse_counter,
    _parse_create_token,
    _parse_damage,
    _parse_destroy,
    _parse_discard,
    _parse_draw,
    _parse_enchant,
    _parse_extra_turn,
    _parse_gain_control,
    _parse_gains,
    _parse_game_is_a_draw,
    _parse_gets,
    _parse_has,
    _parse_look_at_hand,
    _parse_loses,
    _parse_mill,
    _parse_scry,
    _parse_modal_head,
    _parse_player_adds_mana,
    _parse_prevent,
    _parse_put_counter,
    _parse_remove_counter,
    _parse_return,
    _parse_search_library,
    _parse_tap_untap,
    _parse_wins,
)


# ---------------------------------------------------------------------------
# Statement productions
# ---------------------------------------------------------------------------


def _parse_subject_verb(stream: TokenStream) -> ast.Statement:
    """``<subject> <verb> …`` — the common imperative-with-subject shape."""
    # "The next time a <colour> source of your choice would deal damage to you
    # this turn, prevent that damage." opens with a noun phrase rather than a
    # verb, so it is tried before the subject-verb shapes below.
    colour_shield = _parse_colour_source_prevention(stream)
    if colour_shield is not None:
        return colour_shield
    # "The game is a draw." — a subjectless sentence, tried before the noun
    # phrase for the same reason the colour shield is.
    game_draw = _parse_game_is_a_draw(stream)
    if game_draw is not None:
        return game_draw
    # "Choose one —" (CR 700.2). A *statement* rather than a line shape so the
    # three places a modal head is printed — bare on a spell, after an
    # activation cost, after a trigger condition — all read it through the line
    # layer that already handles those prefixes. It refuses quietly, so every
    # other "choose …" sentence keeps the backlog reason it had.
    if stream.at_word("choose"):
        modal = _parse_modal_head(stream)
        if modal is not None:
            return modal
    # A bare imperative verb has an implied "you"/the source as subject.
    if stream.at_word("destroy"):
        return _parse_destroy(stream)
    if stream.at_word("tap", "untap"):
        return _parse_tap_untap(stream)
    if stream.at_word("put"):
        return _parse_put_counter(stream)
    if stream.at_word("remove"):
        removal = _parse_remove_counter(stream)
        if removal is not None:
            return removal
    if stream.at_word("change"):
        return _parse_change_text(stream)
    if stream.at_word("gain"):
        control = _parse_gain_control(stream)
        if control is not None:
            return control
    if stream.at_word("create"):
        return _parse_create_token(stream)
    if stream.at_word("return"):
        return _parse_return(stream)
    if stream.at_word("prevent"):
        return _parse_prevent(stream)
    if stream.at_word("sacrifice"):
        stream.advance()
        subject = parse_recipient(stream)
        if subject is None:
            raise stream.error("expected something to sacrifice")
        # "… unless you pay {W}{W}" — a pay-or-else prompt, kept fused because
        # that is the shape the upkeep dispatcher's handlers implement.
        mark = stream.mark()
        if stream.accept_phrase("unless", "you", "pay"):
            return ast.SacrificeUnlessPay(subject, _parse_mana_payment(stream))
        stream.reset(mark)
        return ast.Sacrifice(ast.PlayerRef("you"), subject)
    if stream.at_word("regenerate"):
        stream.advance()
        subject = parse_recipient(stream)
        if subject is None:
            raise stream.error("expected something to regenerate")
        return ast.Regenerate(subject)
    if stream.at_word("exile"):
        stream.advance()
        subject = parse_recipient(stream)
        if subject is None:
            raise stream.error("expected something to exile")
        return ast.Exile(subject, _parse_duration(stream))
    if stream.at_word("add"):
        return _parse_add_mana(stream)
    if stream.at_word("look"):
        return _parse_look_at_hand(stream)
    if stream.at_word("search"):
        return _parse_search_library(stream)
    # "Scry N" has no subject for the same reason "draw a card" has none: the
    # effect's controller is implied. It belongs with the other bare
    # imperatives rather than in the subject-verb table below, which is why
    # `Scry 1.` used to die on "expected a subject" — and why every scry line
    # in the pool produced no instruction at all while its card still reported
    # supported on the strength of its other line.
    if stream.at_word("scry"):
        return _parse_scry(stream)
    if stream.at_word("take"):
        return _parse_extra_turn(stream)
    if stream.at_word("draw"):
        return _parse_draw(stream, ast.PlayerRef("you"))
    # A bare "discard N cards" is the effect's *controller* discarding, the same
    # implied subject a bare "draw" already carries. Without it "Draw two cards,
    # then discard three cards" strands its second clause and the whole line
    # fails; with it the line parses and lowering decides whether the pair has a
    # handler.
    if stream.at_word("discard"):
        return _parse_discard(stream, ast.PlayerRef("you"))
    # "Mill four cards." — the same implied controller a bare draw or discard
    # carries. Without this the line dies on "expected a subject", which is
    # what the subject-verb table below says about a sentence that has none.
    if stream.at_word("mill"):
        return _parse_mill(stream, ast.PlayerRef("you"))
    if stream.at_word("counter"):
        return _parse_counter(stream)
    if stream.at_word("enchant"):
        return _parse_enchant(stream)

    mark = stream.mark()

    # The self-reference token the lexer emits for the card's own name, plus
    # the "it" of a trigger's remainder clause, both denote the source.
    source_spec: ast.Recipient | None = None
    if stream.at_kind(SELF):
        stream.advance()
        source_spec = ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    elif stream.at_word("it"):
        stream.advance()
        source_spec = ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    else:
        source_spec = parse_recipient(stream)

    if source_spec is None:
        stream.reset(mark)
        raise stream.error("expected a subject")

    token = stream.peek()
    if token is None:
        stream.reset(mark)
        raise stream.error("expected a verb")

    if token.kind == WORD:
        source_target = source_spec if isinstance(source_spec, ast.TargetSpec) else None
        if token.text in ("deals", "deal"):
            return _parse_damage(stream, source_target)
        if token.text in ("gets", "get"):
            return _parse_gets(stream, source_spec)
        if token.text in ("gains", "gain"):
            return _parse_gains(stream, source_spec)
        if token.text in ("loses", "lose"):
            return _parse_loses(stream, source_spec)
        if token.text in ("wins", "win"):
            return _parse_wins(stream, source_spec)
        if token.text in ("has", "have"):
            return _parse_has(stream, source_spec)
        if token.text in ("adds", "add") and isinstance(source_spec, ast.PlayerRef):
            return _parse_player_adds_mana(stream, source_spec)
        if token.text in ("draws", "draw") and isinstance(source_spec, ast.PlayerRef):
            return _parse_draw(stream, source_spec)
        if token.text in ("discards", "discard") and isinstance(source_spec, ast.PlayerRef):
            return _parse_discard(stream, source_spec)
        if token.text in ("mills", "mill") and isinstance(source_spec, ast.PlayerRef):
            return _parse_mill(stream, source_spec)
        if token.text == "becomes":
            return _parse_become_color(stream, source_spec)
        if token.text in ("can't", "cannot"):
            return _parse_cant_attack_or_block(stream, source_spec)

    stream.reset(mark)
    raise stream.error("unrecognized effect verb")


def parse_statement(stream: TokenStream) -> ast.Statement:
    """One sentence's worth of effect, including ``if``/``may`` wrappers."""
    # "if <condition>, <statement>"
    if stream.at_word("if"):
        mark = stream.mark()
        stream.advance()
        try:
            condition = _parse_condition(stream)
            stream.accept_punct(",")
            then = parse_statement(stream)
            return ast.Conditional(condition, then)
        except GrammarError:
            stream.reset(mark)

    # "you may <pay a cost | take an action>"
    if stream.at_word("you"):
        mark = stream.mark()
        stream.advance()
        if stream.accept_word("may"):
            if stream.at_word("pay"):
                stream.advance()
                cost = _parse_mana_payment(stream)
                return ast.May(ast.PlayerRef("you"), cost=cost)
            # The causative "you may have <subject> <verb> …" (Goblin
            # Arsonist's "you may have it deal 1 damage to any target") is the
            # optional form of the unwrapped sentence — the verb table already
            # accepts the uninflected spelling the causative leaves behind, so
            # consuming "have" is the whole difference.
            stream.accept_word("have")
            try:
                action = parse_statement(stream)
                return ast.May(ast.PlayerRef("you"), action=action)
            except GrammarError:
                stream.reset(mark)
        else:
            stream.reset(mark)

    statement = _parse_subject_verb(stream)

    # "<statement>, then <statement>" / "<statement> and <statement>"
    while True:
        mark = stream.mark()
        joined = False
        if stream.accept_punct(","):
            if stream.accept_word("then"):
                joined = True
            else:
                stream.reset(mark)
                break
        elif stream.accept_word("and"):
            joined = True
        elif stream.accept_word("then"):
            joined = True

        if not joined:
            stream.reset(mark)
            break
        try:
            follow = parse_statement(stream)
        except GrammarError:
            stream.reset(mark)
            break
        statement = ast.Sequence((statement, follow))
    return statement


def _parse_condition(stream: TokenStream) -> ast.Condition:
    """Conditions the grammar models today. Anything else raises so the line
    falls back rather than silently losing the condition — the legacy compiler
    dropped intervening-ifs entirely, making conditional triggers always fire."""
    mark = stream.mark()

    player = parse_player_ref(stream)
    if player is not None:
        if stream.accept_word("control", "controls"):
            negated = stream.accept_word("no")
            # "you control **a** Swamp". The article carries no meaning of its
            # own, but the noun parser refuses it as an unknown adjective, so
            # leaving it would refuse every singular condition in the pool.
            stream.accept_word("a", "an")
            filt = parse_object_filter(stream)
            comparison = None if not negated else ast.Comparison("eq", ast.Fixed(0))
            return ast.Controls(player, filt, comparison)
        stream.reset(mark)

    if stream.accept_phrase("a", "creature", "died"):
        _parse_duration(stream)
        return ast.DiedThisTurn(ast.ObjectFilter(card_types=("creature",)))

    # "it is untapped" and "it's untapped" are the same condition; the lexer
    # splits the contraction into "it" + "'s", so both spellings are listed
    # rather than the apostrophe being skipped wherever it turns up.
    if stream.accept_phrase("it", "is", "untapped") or stream.accept_phrase(
        "it", "'s", "untapped"
    ):
        return ast.IsState(ast.TargetSpec("this", ast.ObjectFilter(is_source=True)), "tapped", negated=True)
    if stream.accept_phrase("this", "is", "untapped"):
        return ast.IsState(ast.TargetSpec("this", ast.ObjectFilter(is_source=True)), "tapped", negated=True)

    raise stream.error("unrecognized condition")
