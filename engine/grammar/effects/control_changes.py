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

import dataclasses
from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..lexer import NUMBER
from ..readers import accept_source_reference
from ..references import parse_player_ref, parse_recipient, parse_target_spec
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, CREATURE_TYPES, NUMBER_WORDS, SUBTYPE_INDEX, match_longest)
from ..phrases import (
    _accept_number, _accept_self_reference, _parse_counted_sacrifice,
    _parse_mana_payment, _parse_pay_life,
    _parse_that_object, _parse_zone,
    parse_counted_subject, parse_pair_ordinal_subject, parse_subject_filter_at,
)


def _parse_gain_control(
    stream: TokenStream, *, leading_duration: str | None = None
) -> ast.GainControl | None:
    """``Gain control of <subject> <duration>.``

    Returns None — cursor untouched — unless the line really opens "gain
    control": "gains flying", "you gain 3 life" and "gains control of this
    creature" (Ghazbán Ogre, whose subject comes first) all begin with the same
    verb and are read elsewhere.

    The duration clause is *required*, and only the shapes a handler implements
    are admitted: "until end of turn", "for as long as you control this
    <noun>" (Aladdin, The Wretched), and that clause with "…and this <noun>
    remains tapped" behind it (Willow Satyr, Rubinia Soulsinger). An untimed
    "gain control of target creature" is a permanent control change; a
    differently-conditioned one (Old Man of the Sea's power comparison)
    reverts on things nothing here watches. Each would be this production's
    sentence with the ending changed, so each has to fail rather than borrow
    a linked duration it does not print.
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
        raise stream.error(
            "no handler for a control change without a duration the engine ends"
        )
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
