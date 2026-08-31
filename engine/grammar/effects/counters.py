"""Counter productions (CR 122): putting counters on, taking them off.

Split out of ``effects/characteristics.py`` when that file crossed 1,000 lines.
A family rather than an arbitrary cut, and the family already had a name — the
lowering side has carried ``lowering/counters.py`` since before this side
needed one, so the split re-forms the mirror instead of forking it.

A counter is not a characteristic: CR 122.1 makes it a marker on an object, and
what a ``+1/+1`` counter does to power is a layer-7 consequence rather than the
counter itself. Everything about the *P/T* stays next door.
"""

from __future__ import annotations

import dataclasses

from .. import ast
from ..amounts import _parse_for_each_this_way, parse_amount
from ..errors import GrammarError
from ..lexer import GToken, PT, WORD
from ..nouns import parse_object_filter
from ..references import parse_recipient
from ..stream import TokenStream
from ..vocabulary import CARD_TYPES
from ..phrases import (_accept_number, _expect_counter_kind, _parse_duration,
                       _parse_for_each, is_pt_counter, parse_pair_ordinal_subject)


def _parse_put_counter(stream: TokenStream) -> ast.Statement:
    """``put [up to] N <counter> counter(s) on <subject> [for each …]`` — and
    the object-moving "put" family, tried first because its object is a noun
    phrase rather than a counter: ``put <objects> on top of its owner's
    library`` (Teferi, Timeless Voyager) and ``put <objects> onto the
    battlefield [under your control]`` (Ugin, Liliana's emblem)."""
    stream.expect_word("put")
    move_mark = stream.mark()
    # "Put **that card** onto the battlefield under your control." (Seraph,
    # Krovikan Vampire.) The bound object: the card of the creature the trigger
    # watched die, which by resolution is in a graveyard and so is a *card*,
    # not a permanent anything could target. Read locally, exactly as the return
    # production reads the identical phrase one family over, and for that
    # production's reason — teaching the shared noun parser the words would hand
    # them to every line that prints them. The lowering checks a binder exists.
    moved: "ast.Recipient | None"
    if stream.accept_phrase("that", "card"):
        moved = ast.TargetSpec("that", ast.ObjectFilter(is_card=True))
    else:
        stream.reset(move_mark)
        try:
            moved = parse_recipient(stream)
        except GrammarError:
            moved = None
    if moved is not None and stream.at_word("on", "onto"):
        # "…on top of **their** library" (Drafna's Restoration) is the same
        # destination as "its owner's": CR 404.1 puts a card in the graveyard of
        # the player who owns it, so the cards this sentence moves are already
        # that player's. One node, two spellings.
        if stream.accept_phrase("on", "top", "of", "its", "owner", "'s", "library") or (
            stream.accept_phrase("on", "top", "of", "their", "library")
        ):
            in_any_order = bool(stream.accept_phrase("in", "any", "order"))
            return ast.PutOnLibraryTop(moved, in_any_order=in_any_order)
        # "Put target card from your graveyard on the bottom of your library."
        # (Epitaph Golem.) The zone the card leaves rides the noun phrase, as
        # in every return; the destination decides the node.
        if stream.accept_phrase("on", "the", "bottom", "of", "your", "library"):
            return ast.PutOnLibraryBottom(moved)
        if stream.accept_word("onto"):
            stream.expect_word("the")
            stream.expect_word("battlefield")
            under = bool(stream.accept_phrase("under", "your", "control"))
            # "…**under its owner's control**" (Glyph of Reincarnation) — the
            # other seat CR 400.3 lets a card arrive under. Read only when
            # "under your control" was not, so one sentence cannot claim both.
            owners = not under and bool(
                stream.accept_phrase("under", "its", "owner", "'s", "control")
            )
            return ast.PutOntoBattlefield(
                moved, under_your_control=under, under_owners_control=owners,
            )
    stream.reset(move_mark)
    up_to = stream.accept_phrase("up", "to")
    count = parse_amount(stream)

    token = _expect_counter_kind(stream)
    if token.kind == PT and not is_pt_counter(token.text):
        raise stream.error(f"unsupported counter kind {token.text!r}")
    counter = token.text
    stream.expect_word("counter", "counters")
    stream.expect_word("on")
    # "…put a -1/-1 counter on **that creature**." (Unstable Mutation;
    # Takklemaggot prints the same sentence with a -0/-1 pair.) The bound-object
    # phrase, read here exactly as :func:`_parse_remove_counter` reads its own
    # "remove a sleep counter from that creature": "that <noun>" restates an
    # object the line already bound — its trigger head — so it must not become a
    # choice, and teaching the shared noun parser the phrase would hand it to
    # every line that prints those words. The lowering is what checks a binder
    # actually exists.
    # "…put a +1/+1 counter on **the first** creature." (Infinite Authority.)
    # The same kind of back-reference with a pair to pick from, read through the
    # one shared ordinal production so this clause and the "destroy the other
    # creature" one in the same sentence cannot disagree about which is which.
    subject: ast.Recipient | None = parse_pair_ordinal_subject(stream)
    bound = stream.mark()
    if subject is not None:
        pass
    elif stream.accept_word("that"):
        bound_noun = stream.peek_word()
        if bound_noun is not None and bound_noun in CARD_TYPES:
            stream.advance()
            subject = ast.TargetSpec(
                "that", ast.ObjectFilter(card_types=(bound_noun,))
            )
        else:
            stream.reset(bound)
            subject = parse_recipient(stream)
    else:
        subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected a permanent to put counters on")
    # "…, then double the number of +1/+1 counters on that creature."
    # (Invigorating Surge.) A rider on this placement rather than a second
    # sentence: "that creature" is the one just chosen, so parsed apart the
    # doubling would be looking for a target nobody picked. The counter kind is
    # spelled out and must match what was placed — "then double the number of
    # -1/-1 counters" is a different card and has to keep refusing.
    then_double = False
    double_mark = stream.mark()
    if stream.accept_punct(",") and stream.accept_phrase("then", "double", "the", "number", "of"):
        doubled = _expect_counter_kind(stream)
        if (
            doubled.text == counter
            and stream.accept_word("counter", "counters")
            and stream.accept_phrase("on", "that", "creature")
        ):
            then_double = True
    if not then_double:
        stream.reset(double_mark)
    placement = ast.PutCounter(subject, counter, count, up_to, then_double=then_double)

    # "…for each creature that died this turn" multiplies the placement; it is
    # not a rider on it. Modelled as an iteration wrapping the placement so a
    # counter put down once and a counter put down per death are *different*
    # ASTs — the legacy registry told them apart only by giving the per-death
    # rule a lower order number than the plain one.
    iterated = _parse_for_each(stream)
    if iterated is not None:
        return ast.ForEach(iterated, placement)
    # "…**for each 1 damage prevented this way**." (Sacred Boon.) A *count*
    # rather than a set — what an earlier step of the same effect recorded, one
    # counter per unit of it — so it replaces the placement's number instead of
    # wrapping it in an iteration. Read after the set clause above, which
    # declines without consuming, so the two "for each" sentences keep their
    # own readings.
    #
    # Only over a placement of one: "put **two** counters … for each" is a
    # multiplication this node cannot carry, and reading the clause while
    # dropping the printed count would place one where the card says two.
    counted = _parse_for_each_this_way(stream)
    if counted is None:
        return placement
    if up_to or not isinstance(count, ast.Fixed) or count.value != 1:
        raise stream.error(
            "a counter placed per recorded unit is placed one at a time"
        )
    return dataclasses.replace(placement, count=counted)


def _parse_remove_counter(stream: TokenStream) -> ast.RemoveCounter | None:
    """``Remove [a|N] <kind> counter(s) from <subject>`` as an *effect*.

    The mirror of :func:`_parse_counter_removal_cost`, which reads the same
    words left of an ability's colon. Both are needed and neither subsumes the
    other: Armageddon Clock pays {4} and removes a counter as the effect, while
    Scavenging Ghoul removes one *to* activate.

    Returns None — cursor untouched — when what follows "remove" is not a
    counter at all. "Remove target creature defending player controls from
    combat" and "remove all damage marked on it" open the same way and are
    entirely different effects, so they have to keep failing on their own
    missing production instead of on a counter kind they never mentioned.
    """
    mark = stream.mark()
    stream.expect_word("remove")
    if stream.accept_word("a", "an"):
        count: ast.Amount = ast.Fixed(1)
    else:
        try:
            count = parse_amount(stream)
        except GrammarError:
            stream.reset(mark)
            return None
    try:
        counter = _expect_counter_kind(stream, " to remove").text
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_word("counter", "counters"):
        stream.reset(mark)
        return None
    stream.expect_word("from")
    # "…remove a sleep counter from **that creature**." (Venarian Gold.) The
    # bound-object phrase, read locally exactly as the destroy production reads
    # its own "destroy that creature": "that <noun>" names an object something
    # earlier in the line already bound — here the trigger head — so it must
    # not become a choice, and teaching the shared noun parser the phrase
    # would hand it to every line that prints those words. The lowering is
    # what checks a binder actually exists.
    bound = stream.mark()
    if stream.accept_word("that"):
        noun = stream.peek_word()
        if noun is not None and noun in CARD_TYPES:
            stream.advance()
            return ast.RemoveCounter(
                ast.TargetSpec("that", ast.ObjectFilter(card_types=(noun,))),
                counter,
                count,
            )
        stream.reset(bound)
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to remove a counter from")
    return ast.RemoveCounter(subject, counter, count)

