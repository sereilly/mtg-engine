"""What a "sacrifice …" clause names — the noun phrase and how it is priced.

Split out of ``phrases`` when Mirage's second wave took that module past the
thousand-line guard, and it left under ``lowering/_sacrifices.py``'s name, the
mirror re-forming rather than forking. The seam is the one
``parse_counted_subject``'s own docstring already drew: these four readers are
the *shared* half of one clause, read by three families that never see each
other — the board family's "sacrifice …" and its "unless you sacrifice …" tails,
the combat family's attack cost (CR 508.1g), and the stack family's counter
tails. One reading is what keeps the offer, the cost gate and the charge from
disagreeing about what the card asks for.

Above ``phrases``, which it reads and which never reads it back: a sacrifice
clause is built out of noun phrases and numbers, and none of those is built out
of a sacrifice.
"""

from . import ast
from .lexer import NUMBER
from .phrases import _accept_number, parse_subject_filter_at
from .references import parse_bound_subject
from .stream import TokenStream


def _parse_sacrificed_subject(
    stream: TokenStream, player: ast.PlayerRef
) -> ast.Statement:
    """What a "sacrifice …" sentence names when ``parse_recipient`` refused it.

    Two readings reach here, and neither is a noun phrase the recipient parser
    has: the object an earlier step of this same ability *bound* ("sacrifice
    **that creature**", Phantasmal Mount), and a bare count in front of an
    untargeted plural ("sacrifice **two Islands**", Leviathan). The bound one is
    tried first because "that creature" would otherwise reach
    :func:`parse_counted_subject`, which has no count to read and would refuse
    the whole line.

    Only the *sacrifice* verb comes through this door; the "unless you
    sacrifice" tails go straight to the counted reader, because an alternative
    cost naming an object the sentence already chose is not a shape any card
    prints.
    """
    bound = parse_bound_subject(stream)
    if bound is not None:
        return ast.Sacrifice(player, bound)
    return _parse_counted_sacrifice(stream, player)


def _parse_counted_sacrifice(
    stream: TokenStream, player: ast.PlayerRef
) -> ast.Statement:
    """"two Swamps" / "an Island" — what an "unless you sacrifice" asks for.

    The printed number is read here rather than by ``parse_recipient``, which
    has no reading for a bare count in front of an untargeted plural: the
    counted position is the one the noun parser wants told about
    (``plural=True``), exactly as a counted trigger subject is. One number and
    one noun phrase, so "an Island" and "two Swamps" are one production with
    the count as data.
    """
    # The noun phrase itself is `parse_counted_subject` above: Leviathan's
    # "can't attack unless you sacrifice two Islands" is the same phrase read by
    # the combat family, and one reading is what keeps the offer, the gate and
    # the charge agreeing about what the card asks for.
    # "…sacrifice **any number of creatures with total power 12 or greater**."
    # (Phyrexian Dreadnought.) Read before the counted phrase, whose reader has
    # no number to find here: "any number" is the *absence* of a printed count,
    # and what stands in for it is a threshold on the aggregate of whatever set
    # the seat picks. Refused whole rather than in part — a version that read
    # "any number of creatures" and stopped would sacrifice one creature for a
    # cost the card prices at twelve power.
    aggregate = _accept_aggregate_sacrifice(stream)
    if aggregate is not None:
        described, total = aggregate
        return ast.Sacrifice(
            player,
            ast.TargetSpec("any_number", described),
            total_at_least=total,
        )
    # "…sacrifice **that many** permanents." (Phyrexian Negator.) How many is
    # the number the *firing event* carried — the damage just dealt — so there
    # is no printed number for `parse_counted_subject` to find and it refused
    # the whole line. Read before it for that reason rather than after: "that"
    # is not a count, and the counted reader has no branch that could grow one.
    #
    # The amount rides on ``TargetSpec.count_amount``, which is the field for
    # exactly this ("how many, said by a clause in front of the noun phrase
    # rather than by a printed number") and is documented as the **whole**
    # count rather than a ceiling on one — which is what "that many" is. The
    # noun phrase itself is read plural, as every counted position in this
    # grammar is, so "permanents" resolves through the one noun parser.
    #
    # What the back-reference *means* is not decided here. This production only
    # records that the count is one; ``lowering/board.py`` asks
    # ``_back_reference_payload`` which channel carries it, and that refuses a
    # trigger whose event freezes no quantity — so a card printing this phrase
    # under an event with no number is reported unsupported rather than
    # sacrificing nothing.
    that_many = _accept_that_many_sacrifice(stream)
    if that_many is not None:
        return ast.Sacrifice(
            player, ast.TargetSpec("a", that_many, count_amount=ast.ThatMuch(None))
        )
    # "Each player sacrifices **X** lands of their choice." (Tectonic Break.)
    # Read before the counted phrase for :func:`_accept_that_many_sacrifice`'s
    # reason: there is no number here until the spell is cast (CR 601.2b), so
    # ``parse_counted_subject`` — which answers with an ``int`` — has no branch
    # that could grow one and refused the whole line.
    x_count = _accept_x_sacrifice(stream)
    if x_count is not None:
        return ast.Sacrifice(
            player, ast.TargetSpec("a", x_count, count=0, count_from_x=True)
        )
    counted = parse_counted_subject(stream)
    if counted is None:
        raise stream.error("expected what to sacrifice")
    count, described = counted
    return ast.Sacrifice(player, ast.TargetSpec("a", described, count=count))


def _accept_x_sacrifice(stream: TokenStream) -> "ast.ObjectFilter | None":
    """``X <plural noun>`` — the noun phrase, or None with the cursor untouched.

    "Each player sacrifices **X lands** of their choice." (Tectonic Break.)

    Its own reader beside :func:`_accept_that_many_sacrifice` and for that
    reader's reason: the count is not an ``int`` and cannot be a branch of a
    reader that returns one. It carries the announced X of the spell or ability
    that is sacrificing (CR 107.3), which the lowering puts on the payload as
    ``"x"`` and the handler resolves against ``context.x_value``.

    The count is **zero with a flag** and never 1: a count of 1 would parse, the
    card would compile supported, and each player would sacrifice one land
    however large X was — the quiet direction of wrong ``references.py`` records
    the same lesson about.

    Both parts are required before anything is consumed, and the noun phrase is
    read plural, as every counted position in this grammar is.
    """
    mark = stream.mark()
    if (stream.peek_word() or "").lower() != "x":
        return None
    stream.advance()
    described = parse_subject_filter_at(stream, plural=True)
    if described is None:
        stream.reset(mark)
        return None
    return described


def _accept_that_many_sacrifice(
    stream: TokenStream,
) -> "ast.ObjectFilter | None":
    """``that many <plural noun>`` — the noun phrase, or None with the cursor
    untouched.

    Its own reader beside :func:`_accept_aggregate_sacrifice` and for that
    reader's reason: it answers "how many" with something no number can express,
    so it cannot be a branch of the counted reader that returns an ``int``.

    Both words are required before anything is consumed, and the noun phrase
    after them must parse — a half-consumed "that" would strand the rest of the
    line on a production that then refused it, which is the one outcome worse
    than refusing here.
    """
    mark = stream.mark()
    if not stream.accept_phrase("that", "many"):
        return None
    described = parse_subject_filter_at(stream, plural=True)
    if described is None:
        stream.reset(mark)
        return None
    return described


#: The characteristics a printed aggregate threshold may total. Both are
#: computed through CR 613's layers rather than read off a card, which is what
#: makes a pumped creature count for what it is now.
_TOTAL_CHARACTERISTICS = ("power", "toughness")


def _accept_aggregate_sacrifice(
    stream: TokenStream,
) -> "tuple[ast.ObjectFilter, tuple[str, int]] | None":
    """``any number of <plural noun> with total <characteristic> <N> or
    greater`` — the noun phrase and the threshold, or None with the cursor
    untouched.

    A separate reader rather than a branch of ``parse_counted_subject`` because
    it answers a different question: that one returns *how many*, and this one
    returns a constraint on the set, which no number can express — whether five
    creatures are enough depends on which five.
    """
    mark = stream.mark()
    if not stream.accept_phrase("any", "number", "of"):
        return None
    described = parse_subject_filter_at(stream, plural=True)
    if described is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("with", "total"):
        stream.reset(mark)
        return None
    word = stream.peek_word()
    if word not in _TOTAL_CHARACTERISTICS:
        stream.reset(mark)
        return None
    stream.advance()
    # A printed digit is its own token kind, so a word-table test alone reads
    # "twelve" and refuses "12" — which is the only spelling the card uses.
    if stream.at_kind(NUMBER):
        amount = int(stream.next().text)
    else:
        amount = _accept_number(stream)
    if amount is None or not stream.accept_phrase("or", "greater"):
        # Only the floor is read. "…or less" is a different rule and would need
        # its own validation, and a production that admitted the words without
        # honouring them would price a cost at the wrong end.
        stream.reset(mark)
        return None
    return described, (word, int(amount))


def parse_counted_subject(
    stream: TokenStream,
) -> "tuple[int, ast.ObjectFilter] | None":
    """``two Swamps`` / ``an Island`` — a printed count in front of a plural
    noun phrase, as ``(count, filter)``; None with the cursor untouched when the
    words are not that.

    Here rather than with the sacrifice production that first needed it, because
    two families read the same phrase: "unless you sacrifice **two Islands**"
    (the `board` family's destroy and sacrifice tails) and "can't attack unless
    you sacrifice **two Islands**" (the `combat` family's attack cost, CR
    508.1g). One reading, so the offer, the cost gate and the charge cannot
    disagree about what the card asks for.

    "**an** Island" (Elder Spawn) prints its count as the article, and
    ``NUMBER_WORDS`` reads an article as one — so ``_accept_number`` would
    consume it and leave a bare noun behind, which ``parse_subject_filter_at``
    quantifies as the sweep "all" and then refuses against the singular it was
    asked for. The article is left where it is instead: a singular subject is a
    reading that parser already has.
    """
    mark = stream.mark()
    count = None if stream.peek_word() in ("a", "an") else _accept_number(stream)
    described = parse_subject_filter_at(stream, plural=(count or 1) != 1)
    if described is None:
        stream.reset(mark)
        return None
    return count or 1, described
