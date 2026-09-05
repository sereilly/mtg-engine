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

from ..oracle_types import DREW_BY_SEAT
from . import ast
from .errors import GrammarError
from .lexer import NUMBER, PT, WORD
from .nouns import parse_object_filter
from .references import parse_recipient
from .vocabulary import singular as _singular
from .stream import TokenStream
from .phrases import _accept_number, _accept_self_reference
from .records import accept_additional_cost_paid
from .effects import (_parse_gain_control,
                      _parse_linked_untap_restriction)
# The toll family left for `tolls` at the thousand-line guard and is re-exported
# here so every caller keeps the import it had — the same courtesy `phrases`
# extends `prices`, and the reason `statements` needs no edit to find it.
from .tolls import (_accept_graded_toll_outcomes, _accept_trailing_toll,
                    _parse_unless_player_pays, accept_delayed_toll)


# ---------------------------------------------------------------------------
# Statement productions
# ---------------------------------------------------------------------------


#: "for each **card** less than two a player **draws** this way" (Truce) — the
#: printed noun and verb that name a per-seat record an earlier step of the same
#: effect wrote, and the scratchpad key it wrote it under. A table for
#: ``amounts._THIS_WAY_COUNTS``'s reason, and checked as a *pair* for its
#: reason too: "for each card less than two a player discards this way" is a
#: sentence about the other record, and reading one for the other computes a
#: number the card never printed.
_SHORTFALL_RECORDS: dict[tuple[str, str], str] = {
    ("card", "draws"): DREW_BY_SEAT,
}

#: The head nouns those rows can open with, so the reader can decline before it
#: consumes anything.
_SHORTFALL_NOUNS = frozenset(noun for noun, _ in _SHORTFALL_RECORDS)


def _parse_leading_controller_of_each(
    stream: TokenStream,
) -> "ast.ChosenThisWay | None":
    """``The controller of each of those <noun>`` — a loop printed as a subject.

    "**The controller of each of those artifacts** gains life equal to its mana
    value." (Seeds of Innocence.) The same sentence
    :func:`_parse_leading_for_each` reads one word order over ("for each of
    those artifacts, its controller gains …"), and it produces the same
    iterator: the difference is Wizards' templating, and two nodes would be two
    answers to what "those" names.

    Only the head is consumed. The verb phrase behind it is the caller's, read
    through ``parse_subject_verb`` with "its controller" carried in as the
    subject — so every effect a loop body can already hold is reachable here
    with no second copy of the verb table.

    Returns None with the cursor where it found it.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "the", "controller", "of", "each", "of", "those"
    ):
        stream.reset(mark)
        return None
    try:
        named = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    return ast.ChosenThisWay(named)


def _parse_leading_for_each(
    parse_body,
    stream: TokenStream,
) -> ("ast.DiedThisWay | ast.ExiledThisWay | ast.TappedThisWay "
     "| ast.ChosenThisWay | ast.EachLifeLost | ast.PlayerRef | None"):
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
    # "**For each additional {1}{R} you paid,** destroy another target artifact."
    # (Primitive Justice, Taste of Paradise.) The third count-shaped iterator,
    # and the only one whose number comes from the *cast* rather than from the
    # board or the firing event — CR 601.2b's optional additional cost, taken as
    # many times as the caster chose. Read beside the two counts above and
    # before the noun phrase, which has no reading for a mana symbol and would
    # fail the line on a word this clause understands.
    # "**For each +1/+1 counter you put on a creature this way,** remove a +1/+1
    # counter from that creature …" (Bounty of the Hunt.) The fourth "this way"
    # window, and the only one that walks *counters* rather than objects — a
    # creature given two is named twice. Read before the noun phrase below,
    # which would take the counter kind for a quantified object.
    placed = stream.mark()
    if stream.peek() is not None and not stream.at_word("counter", "counters"):
        kind = stream.peek()
        if kind.kind in (PT, WORD):
            stream.advance()
            if stream.accept_word("counter", "counters") and stream.accept_phrase(
                "you", "put", "on", "a", "creature", "this", "way"
            ) and stream.accept_punct(","):
                return ast.CountersPlacedThisWay(counter=kind.text)
    stream.reset(placed)
    paid = stream.mark()
    symbols = accept_additional_cost_paid(stream)
    if symbols is not None and stream.accept_punct(","):
        return ast.EachAdditionalCostPaid(symbols=symbols)
    stream.reset(paid)
    # "**For each card less than two a player draws this way,** that player
    # gains 2 life." (Truce.) A count that is a *shortfall*, one per seat.
    # Read beside the count above and before the noun phrase below, which would
    # take "card" as a quantified object and then fail the line on "less".
    short = stream.mark()
    noun = stream.peek_word()
    if noun is not None and _singular(noun) in _SHORTFALL_NOUNS:
        stream.advance()
        base = _accept_number(stream) if stream.accept_phrase("less", "than") else None
        if base is not None and stream.accept_phrase("a", "player"):
            verb = stream.peek_word()
            record = (
                _SHORTFALL_RECORDS.get((_singular(noun), verb))
                if verb is not None else None
            )
            if record is not None:
                stream.advance()
                if stream.accept_phrase("this", "way") and stream.accept_punct(","):
                    return ast.EachShortOfThisWay(record=record, base=base)
    stream.reset(short)
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
    # "For each of **those creatures**, …" (Winter's Chill) — the same
    # back-reference over permanents rather than over cards in a hand. Read
    # here, beside the hand spelling and before the noun phrase below, for that
    # branch's reason: "those creatures" is not a filter, and read as one it
    # would name every creature on the battlefield.
    those = stream.mark()
    if stream.accept_phrase("of", "those"):
        try:
            named = parse_object_filter(stream)
        except GrammarError:
            stream.reset(those)
        else:
            if stream.accept_punct(","):
                return ast.ChosenThisWay(named)
            stream.reset(those)
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
    # "For each creature **tapped this way**, …" (Raiding Party.) The bare
    # participle again, over the set an earlier step *tapped* — a third record
    # rather than a reuse of either above, because a tap destroys nothing and
    # exiles nothing, so both of theirs would name an empty set.
    #
    # The one window whose objects are still on the battlefield, which is why
    # it cannot fall through to the board branch at the bottom: "creature
    # tapped this way" read as a live noun phrase would be every tapped
    # creature in play, including the ones this effect never touched.
    if stream.accept_phrase("tapped", "this", "way"):
        if not stream.accept_punct(","):
            stream.reset(mark)
            return None
        return ast.TappedThisWay(filt)
    if not stream.accept_phrase("that", "died", "this", "way"):
        # "**For each attacking red creature,** prevent all combat damage …"
        # (Heroism) / "**For each attacking creature without flying,** its
        # controller may pay {1}." (Tidal Flats.) The set the board holds right
        # now, with no window and no earlier step behind it — which is what
        # ``ast.ForEach``'s iterator union has always said an ``ObjectFilter``
        # means, and what nothing in the leading position could produce.
        #
        # Read **last**, after all four windows above, so a phrase that names a
        # history keeps naming one: "creature that died this way" is a strictly
        # longer phrase whose prefix this branch would otherwise take, turning a
        # loop over a graveyard into a loop over the battlefield.
        #
        # Two guards. The phrase must name something *on the battlefield* — a
        # zone the loop cannot walk is `_parse_leading_count_scale`'s multiplier
        # reading, tried before this one — and it must narrow at all: "for each
        # permanent," names every object in play, which no card prints and which
        # a bare article could reach by accident.
        if (
            filt.zone == "battlefield"
            and not filt.is_card
            and filt != ast.ObjectFilter()
            and stream.accept_punct(",")
        ):
            return filt
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
    # The same recursion one node over. "Until end of turn, target creature
    # gains haste **and** "{0}: Untap this creature."" (Touch of Vitae) prints
    # one duration over two effects joined inside a single sentence, where the
    # sequence above joins whole sentences — and a conjunction has no duration
    # field of its own, so without this the prefix had nothing to attach to and
    # the line failed on the wrapper's name.
    if isinstance(statement, ast.Conjunction):
        return dataclasses.replace(
            statement,
            effects=tuple(
                _distribute_duration(effect, duration, stream)
                for effect in statement.effects
            ),
        )
    # A delayed triggered ability's window is CR 603.7b's "stated duration",
    # and it is a key of `delayed_triggers.DELAYED_EVENTS`' vocabulary rather
    # than a `Duration` node — so it takes the prefix by translation instead of
    # by `replace`. Without this branch the recursion reached `existing.kind` on
    # a string and raised `AttributeError`, which is not a `GrammarError` and so
    # escaped the parser rather than refusing the line.
    if isinstance(statement, ast.CreateDelayedTrigger):
        if duration.kind != "until_end_of_turn":
            raise stream.error(
                "a delayed ability's stated duration is until end of turn"
            )
        if statement.duration not in (None, "end_of_turn"):
            raise stream.error("this sentence prints two different durations")
        return dataclasses.replace(statement, duration="end_of_turn")
    # A combat restriction keeps its duration in ``payload`` rather than in a
    # field — the kind and its parameters are what that node carries — so it
    # takes the prefix by translation, exactly as the delayed trigger above
    # does and for the same reason: the ``replace`` below would find no
    # ``duration`` field and refuse a sentence the grammar can read.
    #
    # "This turn and next turn, **creatures can't attack**, and …" (Peace
    # Talks). The production leaves the duration off when the sentence prints
    # it in front, and the lowering refuses a restriction that ends up with
    # none — so a prefix that failed to arrive here is a loud refusal rather
    # than a permanent effect the card never printed.
    if isinstance(statement, ast.CombatRestriction):
        payload = dict(statement.payload)
        printed = payload.get("duration")
        if printed is not None and printed != duration.kind:
            raise stream.error("this sentence prints two different durations")
        payload["duration"] = duration.kind
        return dataclasses.replace(statement, payload=tuple(payload.items()))
    fields = {field.name for field in dataclasses.fields(statement)}
    if "duration" not in fields:
        raise stream.error(
            f"a leading duration has nothing to attach to in {type(statement).__name__}"
        )
    existing = getattr(statement, "duration")
    if existing.kind is not None and existing.kind != duration.kind:
        raise stream.error("this sentence prints two different durations")
    return dataclasses.replace(statement, duration=duration)


#: The condition a fronted "for as long as <self> remains tapped" names, spelled
#: the way ``engine/control.LINKED_CONTROL_CONDITIONS`` and
#: ``DelayedTrigger.duration`` both read it. One name, because the control
#: contribution, the untap lock and the delayed ability behind that comma are
#: three readers of one printed clause.
LINKED_WHILE_SOURCE_TAPPED = "while_source_tapped"


def _link_leading_duration(statement: "ast.Statement", stream: TokenStream) -> "ast.Statement":
    """*statement* with the fronted "for as long as this creature remains
    tapped" attached, or a refusal naming what could not take it.

    The linked twin of :func:`_distribute_duration`, and separate from it for
    the reason that function's ``CreateDelayedTrigger`` branch already states:
    a linked duration is not a :class:`ast.Duration` node at all. It is a
    *string* naming the condition a sweep re-checks (the control contribution),
    the state a record is read back under (the untap lock), or CR 603.7b's
    stated duration on a delayed ability — three different fields, one printed
    clause.

    Recursing through a conjunction is the whole point: Giant Oyster prints the
    clause once and shares it between the restriction and the delayed ability
    behind the comma, exactly as Chaos Moon shares "until end of turn" between
    its anthem and its delayed mana trigger.
    """
    if isinstance(statement, ast.Conjunction):
        return dataclasses.replace(
            statement,
            effects=tuple(
                _link_leading_duration(effect, stream)
                for effect in statement.effects
            ),
        )
    if isinstance(statement, ast.Sequence):
        return dataclasses.replace(
            statement,
            steps=tuple(
                _link_leading_duration(step, stream) for step in statement.steps
            ),
        )
    if isinstance(statement, ast.DoesntUntapWhileSourceTapped):
        # The node *is* the linked restriction — its whole meaning is this
        # duration, which is what the trailing spelling states in its own
        # words. Nothing to attach.
        return statement
    if isinstance(statement, ast.CreateDelayedTrigger):
        if statement.duration not in (None, LINKED_WHILE_SOURCE_TAPPED):
            raise stream.error("this sentence prints two different durations")
        return dataclasses.replace(
            statement, duration=LINKED_WHILE_SOURCE_TAPPED
        )
    raise stream.error(
        "a leading linked duration has nothing to attach to in "
        f"{type(statement).__name__}"
    )


def _parse_leading_linked_duration(
    stream: TokenStream, parse_body
) -> "ast.Statement | None":
    """``For as long as <self> remains tapped, <effect>.`` (Preacher, Giant
    Oyster.)

    Returns None with the cursor untouched for anything else opening "for as
    long as", so the trailing spelling every other card prints keeps its reader
    and an unreadable condition still fails loudly on its own words.

    Two effects take it, and both for the same reason: the clause names a
    *condition* something re-checks rather than a moment anything could hook, so
    it cannot be the ordinary ``Duration`` the reader below distributes. A
    control change carries it as the link its sweep re-asks (Preacher); an untap
    restriction carries it as the record the untap step reads back off the
    source (Giant Oyster) — the very same effect Phyrexian Gremlins prints with
    the clause behind the sentence instead of in front of it.

    Whatever follows the restriction's comma is governed by the clause too, and
    is read by the ordinary sentence parser rather than by a branch here: Giant
    Oyster's "…, **and at the beginning of each of your draw steps, put a -1/-1
    counter on that creature**" is a delayed triggered ability whose CR 603.7b
    window is this same condition. It is required to be a shape
    :func:`_link_leading_duration` can attach the clause to — a conjunct that
    silently kept its own duration would be an ability nothing ever lifts.
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
    # Gated on the verb rather than tried and caught: `_parse_gain_control`
    # opens with ``expect_word("gain")`` and *raises* on anything else, so
    # calling it speculatively would replace the untap restriction's own
    # refusal with "expected 'gain'" — which is the refusal Giant Oyster
    # reported for two rounds while the sentence it prints was a control change
    # in nobody's reading.
    if stream.at_word("gain"):
        control = _parse_gain_control(
            stream, leading_duration=LINKED_WHILE_SOURCE_TAPPED
        )
        if control is not None:
            return control
        stream.reset(mark)
        return None
    lock = _parse_linked_untap_restriction(stream)
    if lock is None:
        stream.reset(mark)
        return None
    # "…, **and** at the beginning of each of your draw steps, …" The rest of
    # the sentence, under the same clause. Read only when the conjunction is
    # printed; without it the restriction is the whole sentence and the caller's
    # own end-of-sentence check does the rest.
    conjoined = stream.mark()
    if not (stream.accept_punct(",") and stream.accept_word("and")):
        stream.reset(conjoined)
        return lock
    try:
        rest = parse_body(stream)
    except GrammarError:
        # The conjunct is part of this sentence and the clause governs it, so a
        # half-read one is not a shorter card — it is the linked window silently
        # dropped off whatever follows. Declining leaves the line's own refusal.
        stream.reset(mark)
        return None
    return ast.Sequence((lock, _link_leading_duration(rest, stream)))


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
