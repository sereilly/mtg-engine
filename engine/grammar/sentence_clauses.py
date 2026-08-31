"""The clauses ``parse_statement`` reads *around* a sentence body.

Split out of ``statements`` at the thousand-line guard, along the boundary that
function already drew in its own shape: it reads a frame, then a body, then more
frame. ``_parse_statement_body`` is the body and stays; the leading "For each
…," and linked-duration openers, the trailing "unless <player> pays <cost>"
toll and alternative sweep, and the rounding that distributes across a chain are
the frame and live here.

Below ``statements`` and never importing it back, the same inversion
``subject_verb`` and ``delayed`` make one layer up: a frame clause that needs to
read a whole sentence is *handed* the body parser rather than reaching for it.
That is what keeps the direction one-way and the guard able to say so.
"""

import dataclasses

from . import ast
from .errors import GrammarError
from .lexer import (NUMBER, SELF, WORD)
from .nouns import parse_object_filter
from .paragraphs import (
    _parse_random_reveal_ownership_exchange,
    _parse_exchange_greatest_mana_value,
    _parse_cast_from_exiled_with,
    _parse_ownership_exchange_unless_paid,
    _parse_exile_graveyard_until_leaves,
    _parse_exile_until_leaves_or_untaps,
    _parse_name_and_strip,
    _parse_name_then_random_reveal,
    _parse_name_then_reveal_top,
    _parse_transmute_by_sacrifice,
)
from .delayed import (_parse_choose_target, _parse_choose_then_gain,
                      _parse_create_delayed_trigger, delay_binds_an_object,
                      parse_trailing_delay,
                      resolve_that_turn)
from .references import parse_player_ref, parse_recipient
from .vocabulary import CARD_TYPES
from .stream import TokenStream
from .conditions import _parse_condition
from .where_x import parse_where_x_definition
from .subject_verb import parse_subject_verb
from .rebinding import rebind_pronoun_to_condition_target
from .phrases import (
    _accept_number,
    _accept_self_reference,
    parse_bound_subject,
    _parse_can_attack_as_though,
    _parse_duration,
    _parse_mana_payment,
)
from .effects import (
    _accept_life_alternative,
    _parse_untap_chosen_by_paying,
    _parse_for_each_destroy_unless_paid,
    _parse_have_source_deal_damage,
    _parse_add_mana,
    _parse_becomes,
    _parse_cant_attack_or_block,
    _parse_cast_permission,
    _parse_change_base_pt,
    _parse_change_text,
    _parse_source_of_choice_effect,
    _parse_damage_redirect,
    _parse_optional_damage_redirect,
    _parse_assigns_no_combat_damage,
    _parse_attacking_doesnt_tap,
    _parse_bound_targeting_prevention,
    _parse_damage_dealt_riders,
    _parse_counter,
    _parse_create_token,
    _parse_damage,
    _parse_destroy,
    _parse_discard,
    _parse_draw,
    _parse_exile_graveyard,
    _parse_reveal_hand_and_choose,
    _parse_exile_top_of_library,
    _parse_put_exiled_with_source,
    _parse_enchant,
    _parse_end_the_turn,
    _parse_extra_turn,
    _parse_ante,
    _parse_life_total_becomes,
    _parse_gain_control,
    _parse_gains,
    _parse_choose_number,
    _parse_flip_coin,
    _parse_game_is_a_draw,
    _parse_gets,
    _parse_has,
    _parse_look_at_hand,
    _parse_loses,
    _parse_mill,
    _parse_scry,
    _parse_modal_head,
    _parse_player_adds_mana,
    _parse_produces_instead,
    _parse_you_tap_produces_instead,
    _parse_spend_mana_as_though,
    _parse_prevent,
    _parse_double,
    _parse_switch_pt,
    _parse_fight,
    _parse_put_counter,
    _parse_remove_counter,
    _parse_remove_from_combat,
    _parse_return,
    _parse_reveal_top,
    _parse_sacrifice,
    _parse_counted_sacrifice,
    _parse_sacrifice_expansion_permanents,
    _parse_delayed_self_action,
    _parse_shuffle_graveyard_into_library,
    _parse_shuffle_hand_into_library,
    _parse_search_library,
    _parse_doesnt_untap_next_step,
    _parse_tap_untap,
    _parse_attach,
    _parse_exchange_control,
    _parse_wins,
)


# ---------------------------------------------------------------------------
# Statement productions
# ---------------------------------------------------------------------------


def _parse_leading_for_each(
    parse_body,
    stream: TokenStream,
) -> ("ast.DiedThisWay | ast.ExiledThisWay | ast.ChosenThisWay "
     "| ast.EachLifeLost | ast.PlayerRef | None"):
    """``For each <objects> that died this way,`` — the set a later clause
    repeats over, in the leading printed position.

    Only the "this way" window, deliberately. "That died **this turn**" is a
    different set — a window of the turn's history anything may have
    contributed to — and it already has a reader in ``phrases``, in the
    trailing position where the pool prints it. Admitting both here would let
    one clause mean either, and the two differ by every creature the spell had
    nothing to do with.

    Returns None with the cursor where it found it, so a sentence this is not
    keeps the refusal it already had rather than gaining a more confident one.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    # "For each **1 life you lost**, …" (Oath of Lim-Dûl) — an iterator that is
    # a count rather than a set. Read before the noun phrase below, which would
    # take "1 life" as a quantified object and then fail the line on a verb it
    # has no reading for.
    life_lost = stream.mark()
    # A printed digit, read off the token: the pool prints "for each **1** life
    # you lost", and `_accept_number` reads only the spelled-out words.
    digit = stream.accept_kind(NUMBER)
    number = int(digit.text) if digit is not None else _accept_number(stream)
    if number is not None and stream.accept_phrase("life", "you", "lost"):
        if not stream.accept_punct(","):
            stream.reset(mark)
            return None
        return ast.EachLifeLost(per=number)
    stream.reset(life_lost)
    # "**For each player,** this enchantment deals 1 damage to that player …"
    # (Lim-Dûl's Hex.) The players as a set, in the leading printed position.
    # Read before the noun phrase below, which has no reading for a bare
    # "player" and would fail the line on a word this clause understands.
    players = stream.mark()
    # The bare head noun, because "for each" is already consumed and
    # `parse_player_ref` reads the quantifier with it. The two spellings the
    # pool prints, mapped onto the two references every consumer downstream
    # knows — a third name for the same set would be one card's private
    # address for something the engine has.
    noun = stream.peek_word()
    if noun in ("player", "opponent"):
        stream.advance()
        if stream.accept_punct(","):
            return ast.PlayerRef(
                "each_player" if noun == "player" else "each_opponent"
            )
    stream.reset(players)
    # "For each of **those cards**, …" (Sylvan Library) — the set an earlier
    # sentence of this same effect chose. Read before the noun phrase, because
    # "those cards" is a back-reference and not a filter: read as one it would
    # name every card in every hand.
    if stream.accept_phrase("of", "those", "cards"):
        if not stream.accept_punct(","):
            stream.reset(mark)
            return None
        return ast.ChosenThisWay()
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    # "For each creature **exiled this way**, …" (Martyr's Cry). The same
    # leading position and the same "this way" window, over the set an earlier
    # step *exiled* rather than the set it destroyed — two records, so two
    # nodes, because a sweep that exiles kills nothing and the destroy family's
    # record would be empty.
    #
    # No "that": the printed participle is bare ("creature exiled this way"),
    # where the death spelling prints a relative clause ("creature **that**
    # died this way").
    if stream.accept_phrase("exiled", "this", "way"):
        if not stream.accept_punct(","):
            stream.reset(mark)
            return None
        return ast.ExiledThisWay(filt)
    # "For each land **destroyed this way**, …" (Stench of Evil.) The bare
    # participle spelling of the relative clause below, and the *same* set: what
    # a destroy sweep records is what actually died, because a regenerated or
    # indestructible permanent was not destroyed (CR 701.8c). One node, so the
    # two printings cannot come to mean two sets — the difference is Wizards'
    # templating and nothing else.
    if stream.accept_phrase("destroyed", "this", "way"):
        if not stream.accept_punct(","):
            stream.reset(mark)
            return None
        return ast.DiedThisWay(filt)
    if not stream.accept_phrase("that", "died", "this", "way"):
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    return ast.DiedThisWay(filt)


def _parse_leading_count_scale(
    parse_body, stream: TokenStream
) -> "ast.Statement | None":
    """``For each <objects in a zone>, <effects>`` — a leading **count**, not a loop.

    "For each artifact or creature card in target opponent's graveyard, add {C}
    and you gain 1 life." (Spoils of Evil.) The sibling of
    :func:`_parse_leading_for_each` and deliberately not the same production:
    that one names a *set the effect repeats over* and yields an ``ast.ForEach``
    the handler iterates, and this one names a *number the effect is multiplied
    by*. Two mana and two life is one addition and one gain, not two of each —
    and the pool already reads the multiplier in the trailing position ("Add {G}
    for each Forest you control"), so the two spellings meet at the same
    ``per_each`` field rather than at two mechanisms.

    Restricted to a filter naming a **zone other than the battlefield**, which
    is what keeps it from claiming the loop's sentences: every "for each
    creature you control, …" the pool prints is the loop reading, and a
    multiplier is only unambiguous once the phrase has said where to count.

    The scale is distributed onto the effects behind the comma, the way
    :func:`_distribute_duration` distributes a trailing duration. A statement
    with no place to carry it **raises**, because a count silently dropped is a
    card that adds one mana where it should add five.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if filt.zone in (None, "battlefield") or not stream.accept_punct(","):
        stream.reset(mark)
        return None
    return _scale_by_count(parse_body(stream), filt, stream)


#: Which statement nodes can carry a leading count, and under which field. A
#: table rather than a chain of ``isinstance``, because the answer is "the node
#: already has a ``per_each``" — the trailing spelling of the same multiplier
#: writes exactly these fields, so the two printings cannot come to mean two
#: things.
_SCALABLE_BY_COUNT = (ast.AddMana, ast.GainLife)


def _scale_by_count(
    statement: "ast.Statement", filt: "ast.ObjectFilter", stream: TokenStream
) -> "ast.Statement":
    """*statement* with *filt* folded onto every effect as its multiplier."""
    if isinstance(statement, ast.Sequence):
        return ast.Sequence(tuple(
            _scale_by_count(step, filt, stream) for step in statement.steps
        ))
    if isinstance(statement, _SCALABLE_BY_COUNT):
        if statement.per_each is not None:
            raise stream.error("this effect is already counted once")
        return dataclasses.replace(statement, per_each=filt)
    raise stream.error("no reading for a leading count over this effect")


def _distribute_duration(
    statement: ast.Statement, duration: ast.Duration, stream: TokenStream
) -> ast.Statement:
    """Attach a *leading* duration to every effect of the sentence behind it.

    "Until end of turn, A gets +0/+2 and another target creature gets -2/-0"
    (Rookie Mistake) prints one duration in front of two effects, where the
    trailing spelling attaches to the clause it follows. So the leading one is
    distributed rather than stored on a wrapper node: every consumer already
    reads a duration off the effect it belongs to, and a node above them all
    would be a second place to ask.

    Refuses rather than dropping, in three shapes — a statement with no duration
    field at all (the prefix would silently vanish), a statement already printing
    a *different* duration, and, through the recursion, a sequence with any such
    step. A dropped "until end of turn" is a permanent effect the card never
    printed.
    """
    if isinstance(statement, ast.Sequence):
        return dataclasses.replace(
            statement,
            steps=tuple(
                _distribute_duration(step, duration, stream) for step in statement.steps
            ),
        )
    fields = {field.name for field in dataclasses.fields(statement)}
    if "duration" not in fields:
        raise stream.error(
            f"a leading duration has nothing to attach to in {type(statement).__name__}"
        )
    existing = getattr(statement, "duration")
    if existing.kind is not None and existing.kind != duration.kind:
        raise stream.error("this sentence prints two different durations")
    return dataclasses.replace(statement, duration=duration)


def _parse_leading_linked_duration(stream: TokenStream) -> "ast.GainControl | None":
    """``For as long as <self> remains tapped, gain control of <subject>.``
    (Preacher.)

    Returns None with the cursor untouched for anything else opening "for as
    long as", so the trailing spelling every other card prints keeps its reader
    and an unreadable condition still fails loudly on its own words.

    Only the control change takes it. A leading duration on any other sentence
    is the ordinary ``Duration`` the reader below distributes; this one names
    the conditions a *sweep* re-checks, which only the control contribution has.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "as", "long", "as"):
        return None
    if not (
        _accept_self_reference(stream)
        and stream.accept_phrase("remains", "tapped")
        and stream.accept_punct(",")
    ):
        stream.reset(mark)
        return None
    control = _parse_gain_control(stream, leading_duration="while_source_tapped")
    if control is None:
        stream.reset(mark)
        return None
    return control


def _parse_unless_player_pays(stream: TokenStream, parse_body) -> "ast.UnlessPlayerPays | None":
    """``Unless <player> pays <cost>, <statement>.`` (Scarwood Bandits.)

    Returns None with the cursor untouched for anything else opening with
    "unless", so the trailing "…unless <condition>" every other sentence can
    carry keeps its own reader.

    The payer must be a *player reference the engine can enumerate seats from*;
    the cost must be mana. Both are refused rather than skipped, because a payer
    nobody is asked and a cost nobody is charged are the same failure — the
    effect happening unconditionally, which is the card without its clause.
    """
    mark = stream.mark()
    if not stream.accept_word("unless"):
        return None
    payer = parse_player_ref(stream)
    if payer is None or not stream.accept_word("pays", "pay"):
        stream.reset(mark)
        return None
    try:
        cost = _parse_mana_payment(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if cost is None or not stream.accept_punct(","):
        stream.reset(mark)
        return None
    return ast.UnlessPlayerPays(payer, cost, parse_body(stream))


#: Payer references naming a *set* of seats one payment satisfies. "Any player
#: pays {3}" (Icy Prison) is one toll the whole table is offered and the first
#: acceptance ends — which is exactly :class:`ast.UnlessPlayerPays`, a chain,
#: and not one prompt per seat. Every other reference names a single seat, whose
#: offer is the ``May`` an "unless" already is.


_ENUMERATED_PAYERS = frozenset({"each_player", "each_opponent", "target_opponent"})


def _accept_trailing_toll(
    parse_body,
    stream: TokenStream, body: ast.Statement
) -> "ast.Statement | None":
    """``<body> unless <player> pays <cost>`` — the toll, trailing its effect.

    One production for four printed cost shapes, because what varies between
    the cards printing this sentence is the payer, the cost and the consequence
    and never the shape: an "unless" is an offer with a penalty, which is what
    :class:`ast.May` already says.

    Returns None with the cursor untouched for anything else opening with
    "unless" — a trailing condition, or a clause a verb's own production means
    to read — so this reader can sit around every sentence without claiming
    one it does not understand. A cost it half-recognizes is rewound whole
    rather than dropped: a toll nobody is charged is the effect happening
    unconditionally, which is the card without its clause.
    """
    mark = stream.mark()
    if not stream.accept_word("unless"):
        return None
    payer = parse_player_ref(stream)
    if payer is None:
        stream.reset(mark)
        return None
    # "…unless you **discard a card**" (Oath of Lim-Dûl). A cost mana cannot
    # express, and the same decomposition the board family's "unless you
    # sacrifice" tails take: the discard is the offer's *action*, so the
    # takeability check that already knows an empty hand cannot pay it applies
    # unchanged.
    if stream.at_word("discards", "discard"):
        try:
            discard = _parse_discard(stream, payer)
        except GrammarError:
            stream.reset(mark)
            return None
        if discard is None or payer.kind in _ENUMERATED_PAYERS:
            stream.reset(mark)
            return None
        return ast.May(actor=payer, action=discard, otherwise=body)
    if not stream.accept_word("pays", "pay"):
        stream.reset(mark)
        return None
    try:
        cost = _parse_mana_payment(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if cost is None:
        stream.reset(mark)
        return None
    if payer.kind in _ENUMERATED_PAYERS:
        return ast.UnlessPlayerPays(payer, cost, body)
    return ast.May(
        actor=payer,
        cost=cost,
        life_alternative=_accept_life_alternative(stream),
        otherwise=body,
    )


def _round_every_half(node, rounding: str):
    """*node* with every :class:`ast.Half` in it rounded *rounding*, or None
    when it contains none.

    Written against the dataclass fields rather than a per-node list, for the
    reason ``_targeted_specs`` gives: a statement class added later is covered
    by default instead of silently keeping the printed default. Returning None
    for "nothing to round" is what lets the caller refuse the wording rather
    than consume it and change nothing.
    """
    if isinstance(node, ast.Half):
        return dataclasses.replace(node, rounding=rounding)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changed = False
        updates = {}
        for field in dataclasses.fields(node):
            value = getattr(node, field.name)
            rebuilt = _round_every_half(value, rounding)
            if rebuilt is not None:
                updates[field.name] = rebuilt
                changed = True
        return dataclasses.replace(node, **updates) if changed else None
    if isinstance(node, tuple):
        rebuilt_items = [_round_every_half(item, rounding) for item in node]
        if not any(item is not None for item in rebuilt_items):
            return None
        return tuple(
            new if new is not None else old for new, old in zip(rebuilt_items, node)
        )
    return None


def _accept_alternative_sweep(
    parse_body,
    stream: TokenStream, statement: ast.Statement, body_at: int
) -> ast.Statement:
    """``Destroy all enchantments **or all nonwhite enchantments**.`` (Essence
    Filter.) One verb, two object phrases, and the controller picks.

    CR 608.2d, not CR 700.2: there is no bulleted list and nothing is announced
    as the spell is cast, so this is a choice made *while applying the effect*.
    That is the same question ``_parse_optional_action``'s "or" asks, so it is
    the same :class:`ast.OneOf` and the same prompt — inventing a second
    mechanism would mean two defaults and two places for an option to go
    unoffered.

    Read here, after the body, rather than inside the destroy production: the
    shape is "the sentence again with a different object", which is a property
    of the sentence and not of the verb. Every guard below is what keeps that
    from over-claiming:

    * only a **sweep** may be repeated. A targeted alternative would be two
      target sets, one of them never chosen, and CR 601.2c picks targets as the
      spell is cast — the picker has no way to announce a set that depends on a
      choice made later. "Destroy target creature or target land" therefore
      stays refused rather than becoming a choice nobody can make.
    * the alternative must be a sweep too, and must **end the sentence**. A
      near-miss rewinds whole, so "or" introducing anything else falls through
      to the reading it already had.
    """
    subject = getattr(statement, "subject", None)
    if (
        not isinstance(statement, ast.Destroy)
        or not isinstance(subject, ast.TargetSpec)
        or subject.quantifier != "all"
    ):
        return statement
    mark = stream.mark()
    if not stream.accept_word("or"):
        return statement
    start = stream.pos
    try:
        alternative = parse_recipient(stream)
    except GrammarError:
        stream.reset(mark)
        return statement
    if (
        not isinstance(alternative, ast.TargetSpec)
        or alternative.quantifier != "all"
        or stream.peek() is not None and stream.peek().kind == WORD
    ):
        stream.reset(mark)
        return statement
    second = dataclasses.replace(statement, subject=alternative)
    return ast.OneOf(
        (statement, second),
        (stream.text_between(body_at, mark), stream.text_between(start, stream.pos)),
    )
