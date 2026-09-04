"""Parsing a change of who controls a permanent (CR 613 layer 2).

The mirror of ``lowering/control_changes.py``, which split off ``board`` at the
1,000-line guard one merge earlier; this half followed the next time the same
module crossed it. Reusing the name is the point — one template has one home per
side, so "gain control of target creature" is findable from the family it is in
on either side rather than from whichever module happened to be small that week.

A control change is a **contribution with a timestamp**, not a move, and it is
the one board effect whose whole subject matter is a seat rather than an object:
everything left in ``board`` destroys, returns, taps or sacrifices a permanent,
where these two only ever answer "and whose is it now?".
"""

from __future__ import annotations

from .. import ast
from ..lexer import NUMBER
from ..references import parse_recipient
from ..stream import TokenStream
from ..phrases import _accept_self_reference, _parse_that_object
from ..vocabulary import NUMBER_WORDS


def _parse_gain_control(
    stream: TokenStream, *, leading_duration: str | None = None
) -> ast.GainControl | None:
    """``Gain control of <subject> <duration>.``

    Returns None — cursor untouched — unless the line really opens "gain
    control": "gains flying", "you gain 3 life" and "gains control of this
    creature" (Ghazbán Ogre, whose subject comes first) all begin with the same
    verb and are read elsewhere.

    Only the shapes a handler implements are admitted: "until end of turn",
    "for as long as you control this <noun>" (Aladdin, The Wretched), that
    clause with "…and this <noun> remains tapped" behind it (Willow Satyr,
    Rubinia Soulsinger), and — since Ritual of the Machine — **no clause at
    all**, which CR 611.2a makes an indefinite change rather than a missing one.
    A differently-conditioned one (Old Man of the Sea's power comparison)
    reverts on things nothing here watches, and is this production's sentence
    with the ending changed, so it has to fail rather than borrow a linked
    duration it does not print.

    The untimed reading is deliberately the **fall-through** and not a lookahead
    for the end of the line: an ending this production does not know stays
    unconsumed, and the grammar's whole-line rule then refuses the line. So
    "gain control of target creature until end of combat" is still a loud
    failure — it is not silently read as forever, which is the direction a
    control change must never be wrong in.
    """
    mark = stream.mark()
    stream.expect_word("gain")
    if not stream.accept_word("control"):
        stream.reset(mark)
        return None
    if not stream.accept_word("of"):
        stream.reset(mark)
        return None
    # "that creature" (Disharmony) — the object a previous sentence already
    # chose, read by the same back-reference the destroy production uses so
    # the two cannot drift apart about what the phrase names.
    subject = _parse_that_object(stream) or parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to gain control of")
    # "…until end of turn" (Traitorous Greed). A lifetime of its own rather than
    # one tied to a permanent that is still there: the spell that granted it is
    # in a graveyard by the time the turn ends, so nothing can be watched for —
    # CR 611.2c ends it at cleanup instead.
    if leading_duration is not None:
        # "**For as long as this creature remains tapped,** gain control of …"
        # (Preacher.) The duration printed in front of the verb instead of
        # behind it, read by the statement layer and handed down — the same
        # sentence either way, so there is one production and one lowering. A
        # card printing *both* is refused rather than having one silently win.
        if stream.at_word("until", "for"):
            raise stream.error("this sentence prints two different durations")
        return ast.GainControl(subject, leading_duration)
    if stream.accept_phrase("until", "end", "of", "turn"):
        return ast.GainControl(subject, "until_end_of_turn")
    if not stream.accept_phrase("for", "as", "long", "as"):
        # "Gain control of target nonartifact, nonblack creature." (Ritual of
        # the Machine.) CR 611.2a: a continuous effect with no stated duration
        # lasts as long as the game does — which for a layer-2 contribution
        # means nothing ever drops it, not that nothing records it.
        return ast.GainControl(subject, "indefinite")
    # "…for as long as **this creature remains on the battlefield**" (Scarwood
    # Bandits). A weaker link than "you control this creature": an opponent who
    # steals the Bandits breaks that one and not this one, so the two are
    # different durations and the sweep tests them separately. Read before the
    # control clause because the two share only the four words above.
    mark = stream.mark()
    if _accept_self_reference(stream) and stream.accept_phrase(
        "remains", "on", "the", "battlefield"
    ):
        return ast.GainControl(subject, "while_source_on_battlefield")
    stream.reset(mark)
    if not stream.accept_phrase("you", "control"):
        raise stream.error(
            "no handler for a control change without a duration the engine ends"
        )
    if not _accept_self_reference(stream):
        raise stream.error("expected the permanent the control change is linked to")
    # "…and this creature remains tapped" — the second condition of the linked
    # duration (CR 611.2b). Only the self-referential spelling is admitted:
    # a condition about any other object would be one the sweep has no record
    # to check, so the words stay unconsumed and the line fails loudly.
    if stream.accept_word("and"):
        if not _accept_self_reference(stream) or not stream.accept_phrase(
            "remains", "tapped"
        ):
            raise stream.error(
                "the only compound linked duration is "
                "'…and this permanent remains tapped'"
            )
        return ast.GainControl(subject, "while_you_control_source_tapped")
    return ast.GainControl(subject, "while_you_control_source")


def _parse_bid_life_for_control(
    stream: TokenStream, bidders: "ast.Recipient"
) -> "ast.BidLifeForControl | None":
    """``<each player> may bid life for control of <subject>.`` and the four
    sentences of procedure behind it (Illicit Auction).

    Reached from the ``may`` dispatcher with the offer's subject already read,
    so the words this consumes start at "bid".

    **It reads past the full stops on purpose.** The four sentences after the
    first are not effects — "the bidding ends if the high bid stands" changes
    no board — they are the auction's rules, and the handler performs exactly
    them. Left to the sentence loop each would have to become a step nothing
    could execute; read here they are what makes the first sentence mean
    something specific. The `phases out` branch in ``subject_verb`` already
    crosses a sentence boundary for the same reason: the rider is the effect.

    Every one of them is **required**, and a differently-worded procedure
    refuses the line rather than being read as this one. An auction whose bids
    go round in a different order, or whose winner pays something other than
    the high bid, is a different card — and admitting it here would be the
    dropped-rider bug with a whole paragraph in it.

    Returns None with the cursor untouched when the sentence is not this one:
    "may bid" opens nothing else today, but a production that consumed on
    refusal would replace some future sentence's own error with this one's.
    """
    mark = stream.mark()
    if not stream.accept_phrase("bid", "life", "for", "control", "of"):
        stream.reset(mark)
        return None
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what the bidding is for")
    if not stream.accept_punct("."):
        raise stream.error("expected the sentence that opens the bidding")
    # "You start the bidding with a bid of **0**." The opening bid is the
    # printed number, not a constant: a card that started the bidding at 3
    # would be this same auction, and the handler reads the value off the
    # payload rather than assuming zero.
    if not stream.accept_phrase("you", "start", "the", "bidding", "with", "a", "bid", "of"):
        raise stream.error("expected 'you start the bidding with a bid of N'")
    token = stream.peek()
    if token is not None and token.kind == NUMBER:
        stream.advance()
        starting_bid = int(token.text)
    else:
        word = NUMBER_WORDS.get(stream.peek_word() or "")
        if word is None:
            raise stream.error("expected the number the bidding starts at")
        stream.advance()
        starting_bid = int(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the sentence that orders the bidding")
    # The three procedural sentences, in the printed order. Each is spelled out
    # rather than skipped to the end of the line: what the handler implements is
    # this procedure, and a line that says something else about the order, the
    # ending or the price must fail loudly.
    if not stream.accept_phrase("in", "turn", "order"):
        raise stream.error("expected 'in turn order'")
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "each", "player", "may", "top", "the", "high", "bid"
    ):
        raise stream.error("expected 'each player may top the high bid'")
    if not stream.accept_punct("."):
        raise stream.error("expected the sentence that ends the bidding")
    if not stream.accept_phrase(
        "the", "bidding", "ends", "if", "the", "high", "bid", "stands"
    ):
        raise stream.error("expected 'the bidding ends if the high bid stands'")
    if not stream.accept_punct("."):
        raise stream.error("expected the sentence that pays for the creature")
    if not stream.accept_phrase(
        "the", "high", "bidder", "loses", "life", "equal", "to", "the", "high",
        "bid", "and", "gains", "control", "of", "the",
    ):
        raise stream.error(
            "expected 'the high bidder loses life equal to the high bid and "
            "gains control of the …'"
        )
    # The head noun the last sentence repeats ("…gains control of the
    # **creature**"). Consumed as one word rather than checked against the
    # subject's own noun, because the two are the same object by construction
    # and a comparison would only decide which spelling of it is canonical —
    # but it has to be *consumed*, or the whole-line rule fails the card.
    if stream.peek_word() is None:
        raise stream.error("expected the noun the winner gains control of")
    stream.advance()
    stream.accept_punct(".")
    return ast.BidLifeForControl(bidders, subject, starting_bid=starting_bid)


def _parse_exchange_control(stream: TokenStream) -> ast.Statement:
    """``Exchange control of <first> and <second>.`` (CR 701.12b — Gauntlets of
    Chaos.)

    Both halves go through ``parse_recipient``, so the printed type list
    ("target artifact, creature, or land you control") and the printed
    controller ("target permanent an opponent controls") are read by the noun
    phrase every other production already uses.

    "…that shares one of those types with it" is read *here* rather than by the
    noun parser, and that is the point: it compares the second permanent with
    the **first**, and an ``ObjectFilter`` describes one permanent with nothing
    to compare against. Parsed there it could only have been dropped, and a
    dropped restriction is an exchange the card does not allow — a Mox traded
    for a Forest. The production that holds both slots is the one that can
    carry it.
    """
    stream.expect_word("exchange")
    stream.expect_word("control")
    stream.expect_word("of")
    first = parse_recipient(stream)
    if first is None:
        raise stream.error("expected what to exchange control of")
    if not stream.accept_word("and"):
        raise stream.error("expected 'and' between the two permanents exchanged")
    second = parse_recipient(stream)
    if second is None:
        raise stream.error("expected the other permanent of the exchange")
    shares = stream.accept_phrase(
        "that", "shares", "one", "of", "those", "types", "with", "it"
    )
    return ast.ExchangeControl(first, second, shares_a_type=bool(shares))
