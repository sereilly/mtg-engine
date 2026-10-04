"""CR 613.4b: what a permanent's base power and toughness **are**.

Split out of ``characteristics.py`` at Tempest's first wave, the second time
that module crossed the thousand-line guard — and along the line CR 613 already
draws, which is the same line ``lowering/base_pt.py`` was split on one package
over. What stays behind **modifies** a characteristic (a pump at 7c, a switch at
7d, a doubling, a colour, a text change); what left **replaces** the printed
value: "<subject>'s power becomes …" and "Change <subject>'s base toughness to
…" are one rewrite in two printed word orders.

The name is the one ``lowering/base_pt.py``, ``engine/pt.py`` and
``engine/handlers/base_pt.py`` already carry for that channel, so the mirror
re-forms rather than forking a fourth vocabulary.

**"has base power N" stays in ``characteristics``**, and that is the family rule
rather than an oversight: ``_parse_has`` and ``_parse_gains`` both branch into
it mid-sentence, and a family that imported it would be reaching sideways —
which is exactly what ``test_families_do_not_import_each_other`` exists to stop.
What moved is the cluster nothing in that module calls: the two *imperative*
rewrites and the "the power of <object>" fragment they share.

A family rather than a floor: nothing in ``effects/`` reads it. ``parser`` and
``imperatives`` reach it through the package's flat re-export, exactly as they
reach the half left behind.
"""

from .. import ast
from ..amounts import expect_pt, parse_amount
from ..errors import GrammarError
from ..lexer import PT
from ..nouns import parse_object_filter
from ..durations import _parse_duration
from ..references import parse_recipient
from ..stream import TokenStream


#: The two characteristics a printed "the <X> of <object>" phrase can name.
#: A tuple rather than a free word: the accessor behind each is
#: ``effective_power``/``effective_toughness``, and a third word would be a
#: quantity the lowering has no reader for — refused here, where the refusal
#: names the phrase, rather than three layers down.
_READABLE_CHARACTERISTICS = ("power", "toughness")

#: What "minus"/"plus" contribute to a read characteristic's offset.
_CHARACTERISTIC_OFFSET_WORDS = {"minus": -1, "plus": 1}


def _accept_characteristic_of_target(
    stream: TokenStream,
) -> "ast.CharacteristicOfTarget | None":
    """``the <power|toughness> of <object>[ minus N | plus N]``, or None with
    the cursor untouched.

    Sentinel prints it as the addend of a sum ("1 plus **the power of** target
    creature blocking or blocked by this creature"); Sworn Defender prints it
    bare with a subtrahend behind it ("**the toughness of** target creature
    blocking or being blocked by this creature **minus 1**"). One fragment for
    both, because two readers of one printed phrase is the fork
    ``SET_PLAYBOOK.md`` records finding in the where-clause parsers: which noun
    phrases a card could use would depend on which sentence it printed them in.

    The trailing constant is read here rather than by the caller for the reason
    ``CharacteristicOfTarget.offset`` exists at all — "minus 1" left to a caller
    that did not expect it is either unconsumed text (the loud failure) or a
    dropped rider (the silent one), and only the phrase that read the
    characteristic knows the constant belongs to it.
    """
    mark = stream.mark()
    if not stream.accept_word("the"):
        return None
    word = stream.peek_word()
    if word is None or word not in _READABLE_CHARACTERISTICS:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("of"):
        stream.reset(mark)
        return None
    try:
        referent = parse_recipient(stream)
    except GrammarError:
        referent = None
    if not isinstance(referent, ast.TargetSpec):
        # A pronoun ("that creature") is not a noun phrase this reader knows,
        # and the caller's back-reference branch is what reads it. Resetting
        # rather than raising is what lets that branch have its turn; a caller
        # with no such branch keeps its own refusal on the words left behind.
        stream.reset(mark)
        return None
    offset = 0
    sign = stream.peek_word()
    if sign in _CHARACTERISTIC_OFFSET_WORDS:
        after = stream.mark()
        stream.advance()
        try:
            constant = parse_amount(stream)
        except GrammarError:
            stream.reset(after)
            constant = None
        if isinstance(constant, ast.Fixed):
            offset = _CHARACTERISTIC_OFFSET_WORDS[sign] * constant.value
        else:
            # "…minus the number of …" is arithmetic this node cannot carry, so
            # the words stay unconsumed and the line refuses on them rather than
            # being read as the characteristic alone.
            stream.reset(after)
    return ast.CharacteristicOfTarget(referent, word, offset)


def _parse_becomes_base_pt(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.ChangeBasePT | None":
    """``<subject>'s power becomes <amount> <duration>[, and its toughness
    becomes <amount> <duration>]`` (Sworn Defender).

    CR 613.4b's rewrite in the *possessive* voice, where
    :func:`_parse_change_base_pt` reads the imperative one ("Change <subject>'s
    base toughness to …"). The same node, because they are the same effect.
    Folding the two productions together is not possible, though: this one has
    no "Change" to dispatch on and no "base" to confirm the sentence with, and
    its value is two whole clauses rather than one.

    Sworn Defender's second clause says the *other* characteristic about the
    **same** creature ("…and its toughness becomes 1 plus the power of **that
    creature**"), which is what makes the ability target once: the
    back-reference is bound to the first clause's ``TargetSpec`` here rather
    than parsed as a second noun phrase, because a second phrase would be a
    second target and the card names one.

    Refuses without consuming, so any other sentence whose subject is followed
    by a possessive keeps its own refusal.
    """
    mark = stream.mark()
    if not stream.accept_word("'s"):
        return None
    first = stream.peek_word()
    if first is None or first not in _READABLE_CHARACTERISTICS:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("becomes", "become"):
        stream.reset(mark)
        return None
    stats: dict[str, ast.Amount] = {}
    stats[first] = _parse_becomes_pt_amount(stream)
    duration = _parse_duration(stream)
    bound = _characteristic_referent(stats[first])
    conjunct = stream.mark()
    if stream.accept_punct(",") and stream.accept_word("and"):
        if not stream.accept_word("its"):
            raise stream.error("expected 'its' before the second characteristic")
        second = stream.peek_word()
        if second is None or second not in _READABLE_CHARACTERISTICS:
            raise stream.error("expected a characteristic after 'its'")
        if second == first:
            raise stream.error("one clause per characteristic")
        stream.advance()
        stream.expect_word("becomes", "become")
        stats[second] = _parse_becomes_pt_amount(stream, bound=bound)
        if _parse_duration(stream) != duration:
            raise stream.error("the two clauses print different durations")
    else:
        stream.reset(conjunct)
    return ast.ChangeBasePT(
        subject,
        power=stats.get("power"),
        toughness=stats.get("toughness"),
        duration=duration,
    )


def _parse_becomes_pt_amount(
    stream: TokenStream, *, bound: "ast.TargetSpec | None" = None
) -> ast.Amount:
    """One clause's new value: a read characteristic, or a printed number with
    one added to it ("1 plus the power of that creature").

    *bound* is the ``TargetSpec`` an earlier clause of the same sentence already
    chose. With one in hand the pronoun "that <noun>" resolves to it; without
    one the pronoun has nothing to name, so the phrase has to spell its object
    out and this reader refuses.
    """
    read = _accept_characteristic_of_target(stream)
    if read is not None:
        return read
    referenced = _accept_bound_characteristic(stream, bound)
    if referenced is not None:
        return referenced
    amount = parse_amount(stream)
    if not stream.accept_word("plus"):
        raise stream.error("expected a characteristic to read for this clause")
    read = _accept_characteristic_of_target(stream)
    if read is None:
        read = _accept_bound_characteristic(stream, bound)
    if read is None:
        raise stream.error("expected a characteristic after 'plus'")
    return ast.Plus(amount, read)


def _accept_bound_characteristic(
    stream: TokenStream, bound: "ast.TargetSpec | None"
) -> "ast.CharacteristicOfTarget | None":
    """``the <power|toughness> of that <noun>`` — the same object an earlier
    clause of this sentence chose.

    Read here rather than through ``parse_recipient``, which does not carry
    "that <noun>" at all, and bound to the earlier clause's own ``TargetSpec``
    rather than to a fresh one: the two clauses name one target (CR 601.2c
    picks it once), and a second spec would put a second creature in the
    picker.

    The head noun still has to be one the earlier phrase named, so a sentence
    pointing at something else refuses instead of quietly reading the one
    target it has.
    """
    if bound is None:
        return None
    mark = stream.mark()
    if not stream.accept_word("the"):
        return None
    word = stream.peek_word()
    if word is None or word not in _READABLE_CHARACTERISTICS:
        stream.reset(mark)
        return None
    stream.advance()
    if not (stream.accept_word("of") and stream.accept_word("that")):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun is None or noun not in (bound.filter.card_types or ()):
        stream.reset(mark)
        return None
    stream.advance()
    return ast.CharacteristicOfTarget(bound, word, 0)


def _characteristic_referent(amount: ast.Amount) -> "ast.TargetSpec | None":
    """The object *amount* reads, when it reads one."""
    if isinstance(amount, ast.CharacteristicOfTarget):
        return amount.subject
    if isinstance(amount, ast.Plus):
        return _characteristic_referent(amount.right)
    return None


def _parse_change_base_pt(stream: TokenStream) -> ast.ChangeBasePT | None:
    """``Change <subject>'s base [power and] toughness to <value> [duration].``

    CR 613.4b, the Legends rewrite template — Sentinel, Wall of Tombstones,
    Halfdane, Brine Hag. Returns None without consuming when the sentence is
    not this shape, so "Change the text of …" keeps falling through to
    :func:`_parse_change_text`.

    Two printed subject positions, one node: the possessive ("change this
    creature's base toughness…", "change Halfdane's base power and toughness…"
    — the lexer has already collapsed the self-name to SELF plus its
    possessive marker) and the of-phrase ("change the base power and toughness
    of all creatures that dealt damage to it this turn…").

    Three printed value shapes: a P/T pair ("to 0/2"), a quantity with an
    addend ("to 1 plus the number of …", "to 1 plus the power of target …"),
    and both stats of one chosen creature ("to the power and toughness of
    target creature…"). Each is recorded whole — an addend or a referent
    consumed and dropped would be the dropped-rider class this grammar exists
    to refuse.
    """
    mark = stream.mark()
    stream.expect_word("change")
    both = False
    from_pt_of: ast.Recipient | None = None
    if stream.at_word("the"):
        stream.advance()
        if not stream.accept_word("base"):
            # "Change the text of …" — not this production's sentence.
            stream.reset(mark)
            return None
        stream.expect_word("power")
        stream.expect_word("and")
        stream.expect_word("toughness")
        stream.expect_word("of")
        both = True
        subject = parse_recipient(stream)
    else:
        subject = parse_recipient(stream)
        if subject is None or not stream.accept_word("'s"):
            stream.reset(mark)
            return None
        if not stream.accept_word("base"):
            stream.reset(mark)
            return None
        if stream.accept_phrase("power", "and", "toughness"):
            both = True
        elif not stream.accept_word("toughness"):
            raise stream.error("expected 'power and toughness' or 'toughness'")
    if subject is None:
        raise stream.error("expected whose base power/toughness to change")
    stream.expect_word("to")

    power: ast.Amount | None = None
    toughness: ast.Amount | None = None
    token = stream.peek()
    if token is not None and token.kind == PT:
        pt_power, power_negative, pt_toughness, toughness_negative = expect_pt(stream)
        if power_negative or toughness_negative:
            raise stream.error("a base P/T is a value, not a modification")
        if both:
            power, toughness = pt_power, pt_toughness
        else:
            raise stream.error("a toughness-only change takes one number")
    elif stream.accept_phrase("the", "power", "and", "toughness", "of"):
        # Halfdane: both stats read off one chosen creature at resolution.
        if not both:
            raise stream.error("both stats must be named to copy both stats")
        from_pt_of = parse_recipient(stream)
        if from_pt_of is None:
            raise stream.error("expected whose power and toughness to copy")
    else:
        amount: ast.Amount = parse_amount(stream)
        if stream.accept_word("plus"):
            addend_mark = stream.mark()
            read = _accept_characteristic_of_target(stream)
            if read is not None:
                # "1 plus the power of target creature …" (Sentinel). The
                # quantity itself carries the sentence's target.
                amount = ast.Plus(amount, read)
            elif stream.accept_phrase("the", "number", "of"):
                # "1 plus the number of creature cards in your graveyard"
                # (Wall of Tombstones).
                amount = ast.Plus(amount, ast.CountOf(parse_object_filter(stream)))
            else:
                stream.reset(addend_mark)
                raise stream.error("expected a count or a power after 'plus'")
        if both:
            raise stream.error(
                "one quantity cannot set both base power and base toughness"
            )
        toughness = amount

    duration = _parse_duration(stream)
    return ast.ChangeBasePT(
        subject, power, toughness, from_pt_of=from_pt_of, duration=duration
    )







