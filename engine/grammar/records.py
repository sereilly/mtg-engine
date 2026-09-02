"""Quantities read off a record of something that already happened.

The parse-side mirror of ``lowering/_records.py``, and it carries that module's
name for that reason: a handler writes a value into the resolution scratchpad
and a later sentence of the same effect reads it back, and this is the half that
reads the *printed* half of that pair. "The amount of damage dealt to this
creature this turn" (Blazing Effigy), "the sacrificed creature's toughness"
(Life Chisel), "as many cards as they discarded this way" (Forget) — every
production here answers "how many?" by naming an event rather than a number.

Split out of ``amounts.py`` when two waves' additions summed past the
1,000-line guard. The boundary is not the size: what stays in ``amounts`` is a
quantity the sentence *states* — a number, an X, a fraction, a comparison, a
printed P/T — and what moved is a quantity the sentence *refers* to. A cap on a
quantity ("but not more than the player's life total before the damage was
dealt") states its own bound and stays behind with the vocabulary.
"""

from __future__ import annotations

from ..oracle_types import EXILED_THIS_WAY
from . import ast
from .lexer import NUMBER, SELF, WORD
from .readers import accept_source_reference
from .stream import TokenStream
from .vocabulary import CARD_TYPES


def accept_damage_dealt_this_turn(
    stream: TokenStream,
) -> "ast.DamageDealtThisTurn | None":
    """``amount of damage dealt to <the source> this turn by [other] sources
    named <this card>`` — or None, cursor unmoved, when the words are not this.

    Blazing Effigy's where-clause. Called with the leading "the" already
    consumed, from the one reader of a where-clause definition, so the phrase
    means the same wherever a card prints it.

    Every narrowing is read rather than assumed, and the production refuses the
    moment one of them is missing. "This turn" is the ledger's window and a
    clause without it is asking about a different one; "other" is CR 109.5's
    identity exclusion and dropping it would count the creature's own damage to
    itself; and the name must be the SELF token — the card naming itself — so a
    clause comparing against some *other* printed name refuses here instead of
    quietly being read as this one. That last refusal is the dropped-rider bug
    with a card name on it.
    """
    mark = stream.mark()
    if not stream.accept_phrase("amount", "of", "damage", "dealt", "to"):
        stream.reset(mark)
        return None
    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("this", "turn", "by"):
        stream.reset(mark)
        return None
    others_only = bool(stream.accept_word("other"))
    if not (stream.accept_word("sources", "source") and stream.accept_word("named")):
        stream.reset(mark)
        return None
    if stream.accept_kind(SELF) is None:
        stream.reset(mark)
        return None
    return ast.DamageDealtThisTurn(others_only=others_only)


def accept_added_base(stream: TokenStream) -> int | None:
    """``<number> plus`` in front of a quantity — the constant it is added to.

    "…where X is **3 plus** the amount of damage dealt …" (Blazing Effigy). The
    number is payload for the reason every other printed number in this file is:
    a card printing "2 plus" is the same shape with one digit changed, and
    spelling the 3 into the phrase would make every other one a non-match.

    Returns None with the cursor where it found it, so a definition that does
    not open with a sum keeps the refusal it already had.
    """
    mark = stream.mark()
    token = stream.peek()
    if token is not None and token.kind == NUMBER:
        stream.advance()
        if stream.accept_word("plus"):
            return int(token.text)
    stream.reset(mark)
    return None


def accept_damage_dealt_by_chosen_cast(
    stream: TokenStream,
) -> "ast.DamageDealtByChosenCast | None":
    """``the damage dealt by one of those <type> spells this turn`` — or None,
    cursor unmoved, when the words are not this.

    Backdraft's amount. "One of those" is a back-reference to the set an earlier
    sentence described, and it is a *choice* rather than a sum: the whole point
    of the words is that the spells are several and one of them is picked. The
    lowering is where that choice becomes a step, and where the missing
    producer is refused.
    """
    mark = stream.mark()
    if not stream.accept_phrase("the", "damage", "dealt", "by", "one", "of", "those"):
        stream.reset(mark)
        return None
    # Late import for the reason every other reader in this module gives: the
    # vocabulary side depends on this one, so the cycle is broken at call time.
    from .vocabulary import CARD_TYPES, singular

    word = stream.peek_word()
    if word is None or singular(word) not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("spells", "this", "turn"):
        stream.reset(mark)
        return None
    return ast.DamageDealtByChosenCast(singular(word))


def accept_sacrificed_for_cost(stream: "TokenStream") -> "ast.SacrificedForCost | None":
    """``the sacrificed <noun>'s <characteristic>`` — or None, cursor unmoved.

    "equal to **the sacrificed creature's toughness**" (Life Chisel, Diamond
    Valley); "where X is **the sacrificed creature's mana value**" (Burnt
    Offering). A characteristic of the permanent the spell's or ability's own
    *cost* ate, not of anything a step of the effect touched: CR 601.2h pays the
    cost before the object is on the stack, so by resolution the creature is a
    memory the payment path recorded (``sacrificed_for_cost``).

    The noun and the characteristic are both read as printed, so "the sacrificed
    **artifact's** mana value" is the same production. Which of them a handler
    can actually answer is the lowering's question.

    A named function rather than an inline branch for
    :func:`accept_exiled_for_cost`'s reason: two front ends read the phrase — an
    "equal to" amount and a where-clause — and two copies of a phrase that names
    a payment channel is how the two come to name different ones. The leading
    "the" is the caller's.
    """
    mark = stream.mark()
    if stream.accept_word("sacrificed"):
        noun = stream.peek_word()
        if noun is not None:
            stream.advance()
            if stream.accept_word("'s"):
                if stream.accept_phrase("mana", "value"):
                    return ast.SacrificedForCost("mana_value")
                characteristic = stream.peek_word()
                if characteristic in ("power", "toughness"):
                    stream.advance()
                    return ast.SacrificedForCost(str(characteristic))
    stream.reset(mark)
    return None


def accept_exiled_for_cost(stream: "TokenStream") -> "ast.ExiledForCost | None":
    """``the exiled card's <characteristic>`` — or None with the cursor unmoved.

    The twin of :func:`accept_sacrificed_for_cost` one zone over, and a named
    function for the same reason: two front ends read it, an "equal to" amount
    and a where-clause. The leading "the" is the caller's.
    """
    mark = stream.mark()
    if stream.accept_word("exiled"):
        noun = stream.peek_word()
        if noun is not None:
            stream.advance()
            if stream.accept_word("'s"):
                if stream.accept_phrase("mana", "value"):
                    return ast.ExiledForCost("mana_value")
                characteristic = stream.peek_word()
                if characteristic in ("power", "toughness"):
                    stream.advance()
                    return ast.ExiledForCost(str(characteristic))
    stream.reset(mark)
    return None


# ---------------------------------------------------------------------------
# "…for each <noun> <participle> this way" — a count an earlier step recorded
# ---------------------------------------------------------------------------
#
# Here rather than in ``phrases`` because what it produces is an
# :class:`ast.ThatMuch` — a quantity, which is this module's whole subject —
# while its look-alike ``phrases._parse_for_each`` produces a *set*. The two
# read the same four opening words and answer different questions, and keeping
# the count beside the other counts is what says which is which. It moved when
# ``phrases`` crossed the thousand-line guard, along the line the two clauses
# already differed on.

# "for each card **discarded this way**" — the printed participles that name a
# set an *earlier step of this same effect* produced, and the resolution
# scratchpad key that step records its size under. Data rather than branches for
# this file's stated reason, and narrow on purpose: the noun and the participle
# are checked together, so "for each creature discarded this way" is a sentence
# nobody printed and refuses instead of quietly counting cards.
_THIS_WAY_COUNTS: dict[tuple[str, str], str] = {
    ("card", "discarded"): "discarded_count",
    # "…you gain 1 life for each card **exiled this way**." (Rysorian Badger.)
    # The count the graveyard exile in front of it recorded. The key is
    # ``oracle_types``' own constant rather than a fourth spelling of the
    # string: the handler writes it, ``lowering/_records`` declares it and this
    # table reads it, and a second spelling is how a producer gate goes vacuous
    # while the amount reads an empty record.
    ("card", "exiled"): EXILED_THIS_WAY,
    # "…for each 1 **damage prevented** this way." (Sacred Boon.) What the
    # earlier step recorded here is the *shield*, not a number — the total is
    # not known when the spell resolves and goes on accumulating all turn — so
    # the key names the shield and the lowering that reads it is the one that
    # knows to ask it for its total.
    ("damage", "prevented"): "prevention_shield",
}


def _parse_for_each_this_way(stream: TokenStream) -> ast.ThatMuch | None:
    """``for each <noun> <participle> this way`` — a trailing repetition clause
    whose number is one earlier step's result.

    A *count*, not a set, which is why it produces :class:`ast.ThatMuch` rather
    than the ``ObjectFilter`` / :class:`ast.DiedThisTurn` that
    :func:`_parse_for_each` above returns. The two clauses look alike and ask
    different questions: "for each creature that died this turn" iterates a
    window of the turn's history that anything may have contributed to, and this
    one counts exactly what the sentence in front of it did.

    "This way" is required rather than defaulted, for :func:`_parse_for_each`'s
    reason: without the words the clause would name some other set, and letting
    them be absent would let them be *deleted* with no change to the parse.
    Lowering then refuses unless a step of the same effect really records the
    key — with no producer the words name nothing, and a zero is a number the
    card never printed.

    Returning None leaves the cursor where it was, so a caller that does not
    find the clause still owes the rest of its line to full-token consumption.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    # "for each **1** damage prevented this way" (Sacred Boon) — the printed
    # unit. Only one, because the clause is a rate and the count beside it is
    # what is placed per unit: "for each 2 damage" would be a division this
    # produces no node for, and reading the number and dropping it would place
    # twice what the card says. So it is read and checked rather than skipped.
    unit = stream.peek()
    if unit is not None and unit.kind == NUMBER:
        if unit.text != "1":
            stream.reset(mark)
            return None
        stream.next()
    noun = stream.peek()
    if noun is None or noun.kind != WORD:
        stream.reset(mark)
        return None
    singular = noun.text[:-1] if noun.text.endswith("s") else noun.text
    stream.next()
    participle = stream.peek()
    key = (
        _THIS_WAY_COUNTS.get((singular, participle.text))
        if participle is not None and participle.kind == WORD
        else None
    )
    if key is None:
        stream.reset(mark)
        return None
    stream.next()
    if not stream.accept_phrase("this", "way"):
        stream.reset(mark)
        return None
    return ast.ThatMuch(key)


#: The pronoun a "this way" back-reference uses for the seat the verb in front
#: of it already named. A table rather than a bare "consume whatever pronoun is
#: there": "target player discards two cards, then draws as many cards as
#: **they** discarded this way" and "…as **you** discarded this way" are two
#: different seats, and a reader that accepted either would let the sentence
#: count one player's answer and act on another's.
_SEAT_PRONOUNS: dict[str, tuple[str, ...]] = {
    "you": ("you",),
    "target_player": ("they",),
    "target_opponent": ("they",),
    "each_player": ("they",),
    "each_opponent": ("they",),
    "that_player": ("they",),
}


def accept_as_many_as(
    stream: TokenStream, noun: tuple[str, ...], player: "ast.PlayerRef"
) -> "ast.ThatMuch | None":
    """``as many <noun> as <pronoun> <participle> this way`` — or None, unmoved.

    The comparative spelling of the back-reference ``_parse_for_each_this_way``
    above reads: "draws **as many cards as they discarded this way**" (Forget)
    names the count one earlier step of this same resolution produced, and it
    reads it through the same ``_THIS_WAY_COUNTS`` table for that function's
    stated reason — the noun and the participle are checked *together*, so "as
    many cards as they exiled this way" is a sentence nobody printed and
    refuses rather than quietly counting discards.

    *noun* is the caller's own noun ("card"/"cards" for a draw), because the
    phrase puts the noun inside the amount where every other quantity puts it
    after: the caller has already committed to what is being counted, and a
    clause counting something else is not this clause.

    *player* is the seat the verb names, and the pronoun has to agree with it
    (``_SEAT_PRONOUNS``). A mismatch refuses: the record is one seat's answer,
    and a pronoun naming a different seat would be read as though it named this
    one.
    """
    mark = stream.mark()
    if not stream.accept_phrase("as", "many"):
        return None
    counted = stream.peek()
    if counted is None or counted.kind != WORD or counted.text not in noun:
        stream.reset(mark)
        return None
    singular = counted.text[:-1] if counted.text.endswith("s") else counted.text
    stream.next()
    if not stream.accept_word("as"):
        stream.reset(mark)
        return None
    pronouns = _SEAT_PRONOUNS.get(player.kind)
    if pronouns is None or not stream.accept_word(*pronouns):
        stream.reset(mark)
        return None
    participle = stream.peek()
    key = (
        _THIS_WAY_COUNTS.get((singular, participle.text))
        if participle is not None and participle.kind == WORD
        else None
    )
    if key is None:
        stream.reset(mark)
        return None
    stream.next()
    if not stream.accept_phrase("this", "way"):
        stream.reset(mark)
        return None
    return ast.ThatMuch(key)
