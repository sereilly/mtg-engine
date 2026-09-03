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
from ..amounts import parse_amount
from ..records import _parse_for_each_history, _parse_for_each_this_way
from ..errors import GrammarError
from ..lexer import PT
from ..references import parse_recipient
from ..stream import TokenStream
from ..vocabulary import CARD_TYPES
from ..nouns import parse_object_filter
from ..phrases import (_accept_number, _expect_counter_kind, _parse_for_each,
                       is_pt_counter, parse_pair_ordinal_subject)


def _parse_put_counter(stream: TokenStream) -> ast.Statement:
    """``put [up to] N <counter> counter(s) on <subject> [for each …]`` — and
    the object-moving "put" family, tried first because its object is a noun
    phrase rather than a counter: ``put <objects> on top of its owner's
    library`` (Teferi, Timeless Voyager) and ``put <objects> onto the
    battlefield [under your control]`` (Ugin, Liliana's emblem)."""
    # "…unless the player **puts** a -1/-1 counter on a creature they control"
    # (Thelon's Chant, Tourach's Chant). The third-person spelling is the same
    # sentence with its subject printed in front of it, and the toll reader that
    # meets it has already read that subject — so it is this production's verb
    # in another inflection, not a production of its own.
    stream.expect_word("put", "puts")
    move_mark = stream.mark()
    # "Put **that card** onto the battlefield under your control." (Seraph,
    # Krovikan Vampire.) The bound object: the card of the creature the trigger
    # watched die, which by resolution is in a graveyard and so is a *card*,
    # not a permanent anything could target. Read locally, exactly as the return
    # production reads the identical phrase one family over, and for that
    # production's reason — teaching the shared noun parser the words would hand
    # them to every line that prints them. The lowering checks a binder exists.
    moved: "ast.Recipient | None"
    # "Put **the top card of your graveyard** on the bottom of your library."
    # (Soldevi Digger.) Read here, before the recipient parser, because the
    # phrase is not a noun phrase at all: the card is named by its *position* in
    # an ordered pile (CR 404.1), so `parse_recipient` refuses it on the number
    # it expects after "the top". The destination is still read below by the
    # branch every other "put … on …" sentence uses.
    top_of_graveyard = stream.mark()
    if stream.accept_phrase("the", "top", "card", "of", "your", "graveyard"):
        if stream.accept_phrase(
            "on", "the", "bottom", "of", "your", "library"
        ):
            return ast.PutGraveyardTopOnLibraryBottom()
    stream.reset(top_of_graveyard)
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
        # "…on top of **your** library" (Reinforcements). The third spelling of
        # the same destination, and the one that names a *fixed* seat rather
        # than following the cards: "their" above means whoever the sentence
        # already chose, and this means the ability's controller however the
        # cards were picked. Carried as the printed word so the lowering can
        # refuse a sentence whose two halves name different players.
        if stream.accept_phrase("on", "top", "of", "your", "library"):
            in_any_order = bool(stream.accept_phrase("in", "any", "order"))
            return ast.PutOnLibraryTop(
                moved, in_any_order=in_any_order, to_owner="you",
            )
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
    # "Put a +0/+1 counter **or** a +1/+0 counter on target creature."
    # (Dwarven Armorer.) One placement with two kinds to pick from, chosen by
    # the ability's controller as it resolves — not two placements, which would
    # put both. The alternatives are read here, where the kinds are printed,
    # rather than at the sentence level: `_parse_optional_action`'s "or" joins
    # two whole statements, and this "or" is inside one, between a noun and the
    # subject they share.
    alternatives: list[str] = [counter]
    while True:
        alternative_mark = stream.mark()
        if not stream.accept_word("or"):
            break
        stream.accept_word("a", "an")
        try:
            other = _expect_counter_kind(stream)
        except GrammarError:
            stream.reset(alternative_mark)
            break
        if other.kind == PT and not is_pt_counter(other.text):
            raise stream.error(f"unsupported counter kind {other.text!r}")
        if not stream.accept_word("counter", "counters"):
            stream.reset(alternative_mark)
            break
        alternatives.append(other.text)
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
    if len(alternatives) > 1:
        # A choice between kinds is the modal handler's question, so it lowers
        # onto `ast.OneOf` — the same node "sacrifice a creature **or** discard
        # a creature card" produces, and therefore the same prompt, the same
        # default and the same handler. A second mechanism for one question
        # would be two prompts and two places for an option to go unoffered.
        #
        # The riders below are refused rather than distributed: "then double
        # the number of X counters" names one kind, and a placement repeated
        # per member of a set is a multiplication this shape cannot carry
        # option by option. Nothing in the pool prints either beside an "or",
        # and guessing which reading was meant is what a refusal is for.
        if then_double or up_to:
            raise stream.error(
                "a choice of counter kinds carries no rider on the placement"
            )
        options = tuple(
            ast.PutCounter(subject, kind, count, up_to) for kind in alternatives
        )
        labels = tuple(f"a {kind} counter" for kind in alternatives)
        if _parse_for_each(stream) is not None or _parse_for_each_this_way(stream) is not None:
            raise stream.error(
                "a choice of counter kinds is not placed per member of a set"
            )
        return ast.OneOf(options, labels)

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
        # "…**for each 1 damage dealt to you this turn**." (Discordant Spirit.)
        # A count like the clause above and over the same shape of number — one
        # counter per unit — but read out of the turn's damage ledger instead of
        # out of this resolution's scratchpad. Beside it rather than inside it
        # for that reason: "this way" names what the sentence in front of it did
        # and this names what the turn did, so one reader answering both would
        # have to guess which record was meant.
        counted = _parse_for_each_history(stream, parse_object_filter)
    if counted is None:
        return placement
    if up_to or not isinstance(count, ast.Fixed) or count.value != 1:
        raise stream.error(
            "a counter placed per recorded unit is placed one at a time"
        )
    return dataclasses.replace(placement, count=counted)


def _parse_distribute_counters(stream: TokenStream) -> ast.PutCounter | None:
    """``Distribute <amount> <counter> counters among any number of target
    <objects>.`` (Spoils of War.)

    The counter twin of "deals N damage divided as you choose among any number
    of targets", and deliberately the same shape: CR 601.2d covers both with one
    sentence ("divide or distribute an effect (such as damage **or counters**)
    among one or more targets"), the caster announces the division as part of
    casting, and the shares ride the chosen targets. So it lowers onto the same
    ``divided`` target description and the same ``divided_targets`` list, rather
    than inventing a second way to say the same thing.

    Its own production rather than a branch of :func:`_parse_put_counter`: the
    printed verb is different, and every noun after it means something else —
    "among" names the set the shares are split across where "on" names the one
    permanent that gets them all.
    """
    mark = stream.mark()
    if not stream.accept_word("distribute"):
        return None
    count = parse_amount(stream)
    if count is None:
        stream.reset(mark)
        return None
    counter = _expect_counter_kind(stream)
    if not stream.accept_word("counter", "counters"):
        stream.reset(mark)
        return None
    # "among **any number of** target creatures" — or the bounded spelling,
    # "among **one or two**" (Contagion) / "among **one, two, or three**"
    # (Bounty of the Hunt). One of the two is required: "among two target
    # creatures" is a fixed count this shape does not carry, and reading
    # either as unbounded would let Contagion's caster name three.
    if not stream.accept_word("among"):
        stream.reset(mark)
        return None
    if stream.accept_phrase("any", "number", "of"):
        bound = None
    else:
        bound = _accept_target_bound(stream)
        if bound is None:
            stream.reset(mark)
            return None
    subject = parse_recipient(stream)
    if not isinstance(subject, ast.TargetSpec):
        stream.reset(mark)
        return None
    if bound is not None:
        subject = dataclasses.replace(subject, max_count=bound)
    return ast.PutCounter(
        subject, counter.text, count, distributed=True,
    )


def _accept_target_bound(stream: TokenStream) -> int | None:
    """``one or two`` / ``one, two, or three`` — the ceiling it names.

    CR 601.2c's variable target count, printed as an enumeration rather than as
    a range. The enumeration must run ``1, 2, … n`` with nothing skipped and
    nothing repeated: a card printing "one or three" would mean something this
    returns no room to say, and answering ``3`` for it would let the caster
    name two. Nothing consumed when the words are not an enumeration, so the
    caller can reset and refuse the line whole.
    """
    mark = stream.mark()
    numbers: list[int] = []
    while True:
        stream.accept_punct(",")
        stream.accept_word("or")
        value = _accept_number(stream)
        if value is None:
            break
        numbers.append(value)
        if not (stream.at_punct(",") or stream.at_word("or")):
            break
    if numbers != list(range(1, len(numbers) + 1)) or len(numbers) < 2:
        stream.reset(mark)
        return None
    return numbers[-1]


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

