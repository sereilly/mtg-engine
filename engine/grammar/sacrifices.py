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
    counted = parse_counted_subject(stream)
    if counted is None:
        raise stream.error("expected what to sacrifice")
    count, described = counted
    return ast.Sacrifice(player, ast.TargetSpec("a", described, count=count))


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
