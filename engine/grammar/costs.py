"""The cost clause of an activated ability — everything left of the colon.

Split out of `parser.py` when that file crossed 1,000 lines again. It is a
coherent family rather than an arbitrary cut: these productions all answer one
question, "what does activating this ability charge?", and each of them is
paired with a reader in `engine/oracle.py` that collects the same cost. That
pairing is the reason the file exists as a unit — the two halves of a cost must
agree, and keeping this half in one place is what makes the agreement legible.

Sits between `statements` and `parser` in the layer order: it reads noun phrases
and amounts, and nothing above it.
"""

from __future__ import annotations

from dataclasses import replace

from ..subject_filters import untestable_filter_keys
from . import ast
from .amounts import parse_amount
from .effects import _expect_counter_kind
from .phrases import _parse_card_alternatives, accept_graveyard_position
from .errors import GrammarError
from .lexer import MANA, PT, SELF, WORD
from .lowering._common import (chargeable_tap_filter,
                               graveyard_position_payload)
from ..keywords import keyword_ability_name
from .keywords import parse_keyword_list
from .chargeable import (_is_chargeable_counter_target, _is_chargeable_exile,
                         _is_chargeable_sacrifice)
from .nouns import parse_object_filter
from .readers import accept_source_reference
from .references import parse_target_spec
from .stream import TokenStream
from .vocabulary import (CARD_TYPES, IMPLEMENTED_KEYWORDS,
                         singular as _singular)


def _parse_cost_object(
    stream: TokenStream, verb: str, *, bare_plural: bool = False
) -> ast.ObjectFilter:
    """The noun phrase naming what a cost gives up, after *verb*.

    Delegates to the noun parser rather than skipping a token, so "Sacrifice
    this artifact" and "Sacrifice a creature" end up as *different* filters —
    one flagged ``is_source``, one carrying a card type. The old
    ``accept_phrase("sacrifice", "this")`` + ``advance()`` read any word at all
    as the noun and produced the same empty filter either way, which reads as
    "sacrifice any object" to anyone who later lowers these.

    Only the two quantifiers the pool prints are admitted. "Sacrifice two
    creatures" or "Sacrifice target creature" would parse here and mean
    something the rest of the cost machinery has no way to express, so they
    raise instead.
    """
    # "Sacrifice **another** creature" (Hobblefiend). The word sits where the
    # article does, so the noun behind it parses bare — `parse_target_spec`
    # returns quantifier "all" for "creature" and None for "another creature".
    # Teaching the noun parser an "another" quantifier would change every
    # targeted line in the pool, so the exclusion is read here and carried on
    # the filter's existing `other_than_source` field: CR 602.5c's "another" is
    # a restriction on what may pay, not a different kind of cost.
    another = bool(stream.accept_word("another"))
    spec = parse_target_spec(stream)
    if spec is None:
        raise stream.error(f"expected what to {verb} as a cost")
    # *bare_plural* is the "any number of **creatures you control**" tail (Sword
    # of the Ages): the count is printed in front of the phrase, so the phrase
    # itself is the bare plural the noun parser calls "all". Admitted only where
    # the caller has already read a count — an "all" quantifier reaching the
    # ordinary path still refuses, because "Sacrifice creatures you control"
    # names no number at all.
    allowed = ("all",) if (another or bare_plural) else ("this", "a")
    if spec.quantifier not in allowed or spec.count != 1:
        raise stream.error(f"unsupported {verb} cost quantifier {spec.quantifier!r}")
    return replace(spec.filter, other_than_source=True) if another else spec.filter


def _accept_cost_count(stream: TokenStream) -> "ast.Fixed | None":
    """A printed count of **two or more** in front of a cost's noun phrase.

    "Sacrifice **two** Goblins" (Goblin Warrens), "Exile **two** creature cards"
    (Night Soil). The article is deliberately not read here: "a creature" is
    already the singular every other cost prints, and reading its "a" as a count
    would turn the noun phrase behind it into the bare plural
    :func:`_parse_cost_object` admits only for a counted phrase — quietly
    widening every uncounted sacrifice in the pool.

    Returns None with the cursor unmoved when the next word is not a number, so
    a caller that does not find one still owes the rest of its clause to full
    token consumption.
    """
    mark = stream.mark()
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if isinstance(amount, ast.Fixed) and amount.value >= 2:
        return amount
    stream.reset(mark)
    return None


def _accept_sacrifice_list_tail(
    stream: TokenStream,
) -> "list[ast.ObjectFilter] | None":
    """The rest of a comma-separated sacrifice list, or None if none is printed.

    "Sacrifice **a creature named Feral Shadow, a creature named Breathstealer,
    and this creature**" (Urborg Panther). One printed verb naming three
    objects, which is the two-object "and" tail with an Oxford list in front of
    it -- and one filter cannot hold them, because every matcher ANDs a filter's
    keys and no permanent is named two things at once.

    The whole tail is speculative, and it has to be: a comma after a sacrifice
    is *also* how one cost is separated from the next ("Sacrifice a creature,
    {T}: …"). So a comma is only a list separator when the list turns out to
    end in "and <object>", and anything else rewinds to where the first object
    left off and leaves the comma to the cost loop.

    Returns the objects **after** the first, in printed order; None when the
    line prints no list.
    """
    mark = stream.mark()
    extra: list[ast.ObjectFilter] = []
    while True:
        if stream.accept_word("and"):
            try:
                extra.append(_parse_cost_object(stream, "sacrifice"))
            except GrammarError:
                stream.reset(mark)
                return None
            return extra
        if not stream.accept_punct(","):
            stream.reset(mark)
            return None
        # The Oxford comma itself: "…, and this creature". The "and" branch at
        # the top of the loop reads what follows on the next pass.
        if stream.at_word("and"):
            continue
        try:
            extra.append(_parse_cost_object(stream, "sacrifice"))
        except GrammarError:
            stream.reset(mark)
            return None


def _accept_exile_top_of_library(
    stream: TokenStream,
) -> "ast.ExileTopOfLibraryCost | None":
    """``the top [N] card[s] of your library`` after a cost's "Exile" — or None
    with the cursor unmoved.

    The cost twin of ``effects/library._parse_exile_top_of_library``, and a
    separate reader for the reason the whole of this module is separate: an
    effect's exile is lowered onto a handler and a cost's is charged by
    ``engine/oracle.py``'s reader, which has to admit exactly what this admits.
    Every word of "of your library" is expected, exactly as the effect side
    expects them — "the top card of target player's library" is somebody else's
    card and a cost this charger has no payment path for.

    Tried before :func:`_parse_cost_object`, which reads a noun phrase: "the top
    card" is not one, so the object reader refuses the line ("expected what to
    exile as a cost") wherever this one is not consulted first.
    """
    mark = stream.mark()
    if not stream.accept_phrase("the", "top"):
        stream.reset(mark)
        return None
    if stream.accept_word("card"):
        count: ast.Amount = ast.Fixed(1)
    else:
        try:
            count = parse_amount(stream)
        except GrammarError:
            stream.reset(mark)
            return None
        if not stream.accept_word("cards"):
            stream.reset(mark)
            return None
    for word in ("of", "your", "library"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    # Only a printed number is charged. ``ActivatedAbilityCost`` carries this
    # cost as an ``int`` because CR 118.3's "the necessary resources" has to be
    # counted against the library *before* the ability is activated, and an X or
    # a board-derived amount is not known then — a variable count admitted here
    # would be read as some other number by the charger, and a cost read as the
    # wrong number is one nobody pays in full.
    if not isinstance(count, ast.Fixed) or count.value <= 0:
        stream.reset(mark)
        return None
    return ast.ExileTopOfLibraryCost(count)


def _parse_counter_removal_cost(stream: TokenStream) -> ast.RemoveCounterCost:
    """``Remove a <kind> counter from this <permanent>`` (Scavenging Ghoul).

    The counter's name is read as free text, where ``_parse_put_counter``
    additionally rejects a P/T-shaped kind outside the four the engine knows.
    The difference is what happens downstream: a *put* is lowered onto a
    handler, so a P/T counter nothing implements would be silently
    mis-executed, while a cost is recorded and never lowered — the name is
    carried verbatim (CR 122.1 lets a counter have any name) and the
    surrounding words pin the structure.

    The source is read first, and by ``accept_source_reference`` rather than by
    the noun parser, because identity is the whole question in that spelling —
    the cost gives up a counter on *this* permanent and nothing about the
    permanent's characteristics is consulted. It is also the reader that knows a
    card naming itself is naming the source ("Remove a dream counter from
    **Rasputin**"), which the noun parser reads only in the "this <noun>"
    spelling; going through the filter first meant the self-named spelling
    refused with the noun parser's error rather than being read at all.

    "{2}, Remove a +1/+1 counter from **a creature you control**" (Spike Rogue)
    is the same cost paid off a permanent the payer picks, and it is read
    through the same pair the *placing* twin above is —
    :func:`_parse_cost_object` for what the phrase names and
    :func:`_is_chargeable_counter_target` for whether the payment path can find
    it. One reader for both directions, so a phrase this admits and the charger
    refuses cannot exist: that gap is an ability the grammar lets through and
    nothing charges, which is an ability activated for free.
    """
    stream.expect_word("remove")
    count = ast.Fixed(1) if stream.accept_word("a", "an") else parse_amount(stream)
    counter = _expect_counter_kind(stream, " to remove").text
    stream.expect_word("counter", "counters")
    stream.expect_word("from")
    if accept_source_reference(stream):
        return ast.RemoveCounterCost(counter, count)
    marked = stream.mark()
    try:
        subject = _parse_cost_object(stream, "remove a counter from")
    except GrammarError:
        subject = None
    if subject is not None and _is_chargeable_counter_target(subject):
        return ast.RemoveCounterCost(counter, count, subject=subject)
    stream.reset(marked)
    raise stream.error(
        "a counter-removal cost reads the ability's own source or a permanent "
        "the payer can be asked for"
    )


def _accept_mana_run(
    stream: TokenStream,
) -> tuple[tuple[str, int], ...] | None:
    """A run of mana symbols at the cursor as ``(symbol, count)`` pairs, or None
    with the cursor where it was.

    The same symbols ``_parse_costs``' own mana branch reads, gathered here for
    a payment written as prose ("Pay {1} for each ...") -- where the symbols are
    a *rate* rather than the cost, so they must not reach the pips dict that
    branch accumulates into.
    """
    mark = stream.mark()
    pips: dict[str, int] = {}
    while True:
        token = stream.accept_kind(MANA)
        if token is None:
            break
        symbol = token.text.strip("{}")
        if symbol.isdigit():
            pips["generic"] = pips.get("generic", 0) + int(symbol)
        elif symbol in ("W", "U", "B", "R", "G", "C"):
            pips[symbol] = pips.get(symbol, 0) + 1
        else:
            # {T}, {X} and the hybrids: a rate this cannot multiply. Refused
            # whole rather than read as the part that matched.
            stream.reset(mark)
            return None
    if not pips:
        stream.reset(mark)
        return None
    return tuple(sorted(pips.items()))


def _accept_per_counter(stream: TokenStream) -> str | None:
    """``for each <kind> counter on this <noun>`` at the cursor, as the counter's
    printed name — or None with the cursor where it was.

    Only the ability's **own source** is admitted. "On this enchantment" is the
    permanent the cost is being paid to activate, which is the one permanent a
    cost charger has in hand; a counter on anything else would be a board read
    the charger cannot make, and reading it as the source anyway would charge
    the wrong number.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        stream.reset(mark)
        return None
    # "for each **+1/+1** counter" (Skeleton Scavengers). A counter named by a
    # power/toughness change is its own token kind, so a reader that asked only
    # for a word saw nothing here and refused the clause -- which for an
    # activation cost is the ability's whole line. The name is the token's text
    # either way, which is what ``named_counters`` is keyed by.
    named = stream.peek()
    if named is None or named.kind not in (WORD, PT):
        stream.reset(mark)
        return None
    counter = named.text
    stream.advance()
    if not stream.accept_word("counter", "counters"):
        stream.reset(mark)
        return None
    if not stream.accept_word("on"):
        stream.reset(mark)
        return None
    if not stream.accept_word("this"):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun is None or _singular(noun) not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    return str(counter)


def _accept_mana_alternative(stream: TokenStream) -> tuple[tuple[str, int], ...]:
    """``or <mana symbols>`` at the cursor, as ``(symbol, count)`` pairs — or an
    empty tuple with the cursor where it was.

    Only a written-out run of ordinary symbols. ``{X}`` is deliberately not
    admitted: an alternative whose size the payer announces would need the
    announcement to reach a payment path that has none, and the empty tuple
    keeps the words unconsumed so the ability refuses instead.
    """
    mark = stream.mark()
    if not stream.accept_word("or"):
        stream.reset(mark)
        return ()
    pips: dict[str, int] = {}
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit():
            pips["generic"] = pips.get("generic", 0) + int(symbol)
        elif symbol in ("W", "U", "B", "R", "G", "C"):
            pips[symbol] = pips.get(symbol, 0) + 1
        else:
            stream.reset(mark)
            return ()
    if not pips:
        stream.reset(mark)
        return ()
    return tuple(sorted(pips.items()))


def _parse_costs(stream: TokenStream) -> tuple[ast.Cost, ...]:
    """Parse the cost clause left of an activated ability's colon."""
    costs: list[ast.Cost] = []
    pips: dict[str, int] = {}
    while True:
        token = stream.accept_kind(MANA)
        if token is not None:
            symbol = token.text.strip("{}")
            if symbol == "T":
                costs.append(ast.TapSelf())
            elif symbol.isdigit():
                pips["generic"] = pips.get("generic", 0) + int(symbol)
            elif symbol in ("W", "U", "B", "R", "G", "C"):
                pips[symbol] = pips.get(symbol, 0) + 1
            elif symbol == "X":
                pips["X"] = pips.get("X", 0) + 1
            else:
                raise stream.error(f"unsupported mana symbol {token.text!r}")
            stream.accept_punct(",")
            continue
        if stream.at_word("return"):
            # "**Return this enchantment to its owner's hand**" (Cycle of Life)
            # — CR 118.3's cost that is a zone change of the source. Read
            # through the same noun parser every other cost object uses, so
            # "return this artifact" and "return a creature you control" cannot
            # come out as the same empty filter; only the source is charged
            # today, and anything else refuses rather than being charged as the
            # source.
            mark = stream.mark()
            stream.advance()
            # "Return **two** Islands you control…" (Flooded Shoreline). The
            # count is printed in front of the phrase, which leaves the phrase
            # the bare plural the noun parser calls "all" — the same shape the
            # counted sacrifice below reads, admitted the same way.
            counted = _accept_cost_count(stream)
            returned = _parse_cost_object(
                stream, "return", bare_plural=counted is not None
            )
            # "…to **its** owner's hand" and "…to **their** owner's hand" are
            # English inflection over one destination, so both spellings are
            # read here; any *other* destination refuses below, because a cost
            # that put the permanent somewhere else is a cost nothing charges.
            if returned.is_source and stream.accept_phrase(
                "to", "its", "owner", "'s", "hand"
            ):
                costs.append(ast.ReturnSelfToHandCost())
                stream.accept_punct(",")
                continue
            # "Return **a Forest you control** to its owner's hand" (Quirion
            # Ranger). The chosen twin, gated the way the tap cost above is
            # gated and for its reason: the charger enumerates the payer's own
            # battlefield with ``subject_matches``, so a phrase that predicate
            # cannot test would be *dropped* rather than refused and the cost
            # would be payable off a wider set than the card names.
            if not returned.is_source and (
                stream.accept_phrase("to", "its", "owner", "'s", "hand")
                or stream.accept_phrase("to", "their", "owner", "'s", "hand")
            ):
                if chargeable_tap_filter(returned) is None:
                    stream.reset(mark)
                    raise stream.error("no cost path charges this return")
                if returned.controller not in (None, "you"):
                    # The charger draws from the *activating* player's own
                    # battlefield, so a phrase naming another seat is a cost it
                    # cannot pay — refused rather than charged off the wrong
                    # board.
                    stream.reset(mark)
                    raise stream.error("a return cost is paid from your own board")
                costs.append(
                    ast.ReturnPermanentsToHandCost(
                        1 if counted is None else counted.value, returned
                    )
                )
                stream.accept_punct(",")
                continue
            stream.reset(mark)
            raise stream.error("unrecognized activation cost")
        if stream.at_word("choose"):
            # "**Choose flying, first strike, trample, or shadow**" (Phyrexian
            # Splicer). A cost clause that spends nothing — CR 602.1a puts
            # everything before the colon in the activation cost, and CR 601.2b
            # announces the choices there, which is *before* CR 601.2c chooses
            # targets. The sentence behind it narrows its first target by the
            # answer, so no later reading of the clause would be in time.
            #
            # Every option is put to the keyword registry: a word with no
            # behaviour behind it would be an option that grants nothing, and
            # the whole card is moving the ability between two creatures. Two
            # options at least, because "choose" with one is not a choice and
            # would be a keyword the sentence could simply print.
            mark = stream.mark()
            stream.advance()
            try:
                options, _disjunctive = parse_keyword_list(stream)
            except GrammarError:
                stream.reset(mark)
                raise stream.error("unrecognized activation cost")
            if len(options) < 2 or any(
                keyword_ability_name(option) not in IMPLEMENTED_KEYWORDS
                for option in options
            ):
                stream.reset(mark)
                raise stream.error(
                    "a choice of abilities needs two or more implemented keywords"
                )
            costs.append(ast.ChooseKeywordCost(tuple(options)))
            stream.accept_punct(",")
            continue
        if stream.accept_word("sacrifice"):
            # "Sacrifice **two** Goblins" (Goblin Warrens). The count is printed
            # in front of the phrase, which leaves the phrase itself the bare
            # plural the noun parser calls "all" — the same shape Sword of the
            # Ages' "any number of" tail already reads, and admitted the same
            # way.
            counted = _accept_cost_count(stream)
            sacrificed = _parse_cost_object(
                stream, "sacrifice", bare_plural=counted is not None
            )
            if not _is_chargeable_sacrifice(sacrificed):
                raise stream.error("no cost path charges a narrowed sacrifice")
            costs.append(
                ast.SacrificeCost(sacrificed, count=counted or ast.Fixed(1))
            )
            # "Sacrifice this artifact **and any number of creatures you
            # control**" (Sword of the Ages). One printed cost naming two
            # things, so it becomes two entries: the source, and a set whose
            # size the payer chooses. Read here rather than as a second
            # "Sacrifice" clause because the card prints the verb once — and
            # without it the "and …" tail was unconsumed text that refused the
            # whole ability.
            more = stream.mark()
            if stream.accept_phrase("and", "any", "number", "of"):
                several = _parse_cost_object(
                    stream, "sacrifice", bare_plural=True
                )
                if not _is_chargeable_sacrifice(several):
                    raise stream.error("no cost path charges a narrowed sacrifice")
                costs.append(ast.SacrificeCost(several, count=ast.AnyNumber()))
            else:
                stream.reset(more)
                # "Sacrifice a creature **and a Swamp**" (Viscerid Drone), and
                # "…**a creature named Feral Shadow, a creature named
                # Breathstealer, and this creature**" (Urborg Panther). One
                # printed verb naming two or three *different* objects, so it
                # becomes that many entries — the same decomposition Sword of
                # the Ages' tail makes one branch up, with noun phrases where
                # that one has a count. A single filter cannot hold them: the
                # keys are ANDed by every matcher, and "a creature that is also
                # a Swamp" is a permanent this pool never prints.
                #
                # **Capped at three objects, one of which must be the source.**
                # That is not a grammar limit, it is what the charger can hold:
                # `ActivatedAbilityCost` has `sacrifice_self` plus two chosen
                # filters, and a fourth object would be a cost the ability is
                # admitted with and never charged. Refusing here reports the
                # card unsupported naming the clause instead — loud, and the
                # direction that never activates an ability for less than it
                # prints.
                also = _accept_sacrifice_list_tail(stream)
                if also is not None:
                    chosen = [
                        filt for filt in (sacrificed, *also) if not filt.is_source
                    ]
                    if len(chosen) > 2:
                        raise stream.error(
                            "no cost path charges more than two chosen sacrifices"
                        )
                    for filt in also:
                        if not _is_chargeable_sacrifice(filt):
                            raise stream.error(
                                "no cost path charges a narrowed sacrifice"
                            )
                        costs.append(ast.SacrificeCost(filt))
            stream.accept_punct(",")
            continue
        if stream.accept_word("exile"):
            # "Exile **the top card of your library**" (Royal Herbalist). Read
            # first because it is the one exile cost whose tail is *not* a noun
            # phrase: the cards are named by position, so the object reader
            # below refuses it outright.
            from_library = _accept_exile_top_of_library(stream)
            if from_library is not None:
                costs.append(from_library)
                stream.accept_punct(",")
                continue
            # "Exile **the top card of your graveyard**" (Alms, Nature's
            # Kiss), "…the top **creature** card…" (Necratog, Zombie
            # Scavengers). Read here for the library form's reason directly
            # above — CR 404.1/404.2 name these cards by *position*, so the object
            # reader below refuses the phrase outright — and gated by the same
            # payload builder ``engine/oracle.py``'s charger runs, so the two
            # halves of the cost cannot admit different clauses.
            #
            # Only the payer's own pile: an activation cost paid out of
            # somebody else's graveyard is a shape no payment path has a seat
            # for, and reading it as the payer's own would eat the wrong card.
            from_graveyard = accept_graveyard_position(stream)
            if from_graveyard is not None:
                if graveyard_position_payload(
                    from_graveyard, seats=frozenset({"you"})
                ) is None:
                    raise stream.error(
                        "no cost path charges an exile of this graveyard position"
                    )
                costs.append(ast.ExileGraveyardPositionCost(from_graveyard))
                stream.accept_punct(",")
                continue
            # ``ExileSelf`` names no object, so the source gets its own entry:
            # nothing is chosen, nothing can make the ability unpayable, and
            # there is no record of what was eaten.
            counted = _accept_cost_count(stream)
            exiled = _parse_cost_object(
                stream, "exile", bare_plural=counted is not None
            )
            if exiled.is_source:
                costs.append(ast.ExileSelf())
                stream.accept_punct(",")
                continue
            # "…from **a single** graveyard" (Night Soil). The noun parser stops
            # in front of it — "single" is not a zone owner it knows — so the
            # tail is read here, where the *cost* is being built and the fact it
            # states has somewhere to live. It is two facts in four words: the
            # pile may be anybody's, and every card must come out of the same
            # one. The first rides the filter's ``zone``/``zone_owner`` like
            # every other printed zone; the second cannot, because a filter is
            # asked of one card at a time, so it rides the cost.
            same_zone = False
            if stream.accept_phrase("from", "a", "single", "graveyard"):
                exiled = replace(exiled, zone="graveyard", zone_owner=None)
                same_zone = True
            # "Exile **a creature you control**" (City of Shadows) / "Exile **a
            # creature card from your graveyard**" (Necropolis). A chosen
            # object, gated by the charger's own reader for the reason the
            # sacrifice beside it is: two readers of one clause drift, and the
            # direction they drift in is a cost nobody pays.
            if not _is_chargeable_exile(exiled):
                raise stream.error("no cost path charges an exile of this shape")
            costs.append(
                ast.ExileCost(
                    exiled, count=counted or ast.Fixed(1), same_zone=same_zone
                )
            )
            stream.accept_punct(",")
            continue
        if stream.at_word("pay"):
            # "Pay 3 life" (Tavern Swindler) — CR 118.3b, charged by
            # ``ActivatedAbilityCost.pay_life``. Only a fixed positive amount is
            # admitted: the charger reads the printed number out of the same
            # clause, and a variable or zero payment is a shape it would read as
            # "no such cost", which is an ability activated for free.
            mark = stream.mark()
            stream.advance()
            # "Pay **enchanted creature's mana cost**" (Merseine). Read before
            # the amount below, which is a life payment and would refuse the
            # noun — the same position the tap branch reads its own attached
            # host from, and for the same reason: nothing is picked, so there
            # is no count for the quantity parser to find.
            attached = stream.mark()
            if stream.accept_word("enchanted", "equipped"):
                noun = stream.peek_word()
                if noun is not None and _singular(noun) in CARD_TYPES:
                    stream.advance()
                    if stream.accept_phrase("'s", "mana", "cost"):
                        costs.append(ast.PayAttachedManaCost())
                        stream.accept_punct(",")
                        continue
            stream.reset(attached)
            # "Pay **{1} for each +1/+1 counter on this creature**" (Skeleton
            # Scavengers). A mana payment rather than a life one, read here
            # because the amount parser below wants a number and would refuse
            # the line on the symbol -- the same one-token gap the attached
            # mana cost above answers.
            #
            # The per-counter clause is **required**: a bare "Pay {1}" is the
            # mana symbol spelled twice, and admitting it here would charge a
            # flat rate for a cost whose whole point is that it grows.
            # "Pay **half your life, rounded up**" (Lurking Evil). Read before
            # the amount parser below, which wants a number and refuses on the
            # word — the same one-token gap the attached mana cost above
            # answers. The rounding word is **required**: CR 107.2 leaves a
            # fraction unrounded unless the effect says which way, and reading
            # "half your life" alone would pick a direction the card never
            # printed. Rounding down is a different, strictly cheaper cost, so
            # it refuses here rather than being folded in with a flag nothing
            # in the pool sets.
            halved = stream.mark()
            if stream.accept_phrase("half", "your", "life"):
                stream.accept_punct(",")
                if stream.accept_phrase("rounded", "up"):
                    costs.append(ast.PayLifeCost(half_rounded_up=True))
                    stream.accept_punct(",")
                    continue
                stream.reset(halved)
                raise stream.error(
                    "only a life payment rounded up is charged"
                )
            stream.reset(halved)
            per_counter_mana = _accept_mana_run(stream)
            if per_counter_mana is not None:
                rate = _accept_per_counter(stream)
                if rate is None:
                    stream.reset(mark)
                    raise stream.error(
                        "a mana payment written as prose is charged only per counter"
                    )
                costs.append(
                    ast.PayManaPerCounterCost(per_counter_mana, rate)
                )
                stream.accept_punct(",")
                continue
            amount = parse_amount(stream)
            if not isinstance(amount, ast.Fixed) or amount.value <= 0:
                stream.reset(mark)
                raise stream.error("only a fixed, positive life payment is charged")
            if not stream.accept_word("life"):
                stream.reset(mark)
                raise stream.error("unrecognized activation cost")
            # "Pay 3 life **for each velocity counter on this enchantment**"
            # (Tornado). The printed number is a rate; the multiplier is a
            # counter on this ability's own source, so it is carried as the
            # counter's name and read at activation (CR 601.2f). Left unread
            # the words are unconsumed text and the whole line refuses, which
            # is how Tornado's ability compiled to nothing.
            per_counter = _accept_per_counter(stream)
            # "Pay 2 life **or {2}**" (Tidal Control). The printed disjunction,
            # read here because it belongs to this payment: left unconsumed the
            # words refuse the whole ability, and read as a second cost clause
            # the ability would charge both halves of an "or".
            alternative = _accept_mana_alternative(stream)
            costs.append(
                ast.PayLifeCost(
                    amount, per_counter=per_counter, alternative_mana=alternative
                )
            )
            stream.accept_punct(",")
            continue
        if stream.at_word("tap"):
            # "Tap two untapped Spirits you control" (Shacklegeist). Not the {T}
            # symbol — that is the source tapping itself and is lexed as mana —
            # so this is only ever the spelled-out form naming other permanents.
            mark = stream.mark()
            stream.advance()
            # "Tap **enchanted land**" (Earthlore). The host, read before the
            # count below because there is none to read: nothing is picked and
            # nothing is counted, the attachment record is the whole cost.
            attached = stream.mark()
            if stream.accept_word("enchanted", "equipped"):
                noun = stream.peek_word()
                if noun is not None and _singular(noun) in CARD_TYPES:
                    stream.advance()
                    costs.append(ast.TapAttachedCost())
                    stream.accept_punct(",")
                    continue
            stream.reset(attached)
            number = parse_amount(stream)
            if not isinstance(number, ast.Fixed) or number.value <= 0:
                stream.reset(mark)
                raise stream.error("a tap cost taps a fixed, positive number")
            try:
                tapped = parse_object_filter(stream)
            except GrammarError:
                stream.reset(mark)
                raise stream.error("expected what to tap as a cost")
            if chargeable_tap_filter(tapped) is None:
                stream.reset(mark)
                raise stream.error("no cost path charges this tap")
            costs.append(ast.TapPermanentsCost(number.value, tapped))
            stream.accept_punct(",")
            continue
        if stream.at_word("untap"):
            # "Untap a tapped land an opponent controls" (Benthic Explorers).
            # CR 602.1a — a cost is any action, and this one is performed on a
            # permanent the payer does not control. Read after the tap branch
            # above, which shares none of its words; the two are separate
            # productions because they are separate costs, and folding them
            # into one with a direction flag would put the seat question (whose
            # permanent) in a branch that has never had to ask it.
            mark = stream.mark()
            stream.advance()
            if not stream.accept_word("a", "an"):
                stream.reset(mark)
                raise stream.error("an untap cost untaps one named permanent")
            try:
                untapped = parse_object_filter(stream)
            except GrammarError:
                stream.reset(mark)
                raise stream.error("expected what to untap as a cost")
            described = untapped.to_payload()
            if untestable_filter_keys(described):
                # The charger enumerates with ``subject_matches``, so a phrase
                # it cannot test would be dropped and the cost would be payable
                # from a wider set than the card prints — the direction a cost
                # must never be wrong in.
                stream.reset(mark)
                raise stream.error("no cost path charges an untap of this shape")
            if untapped.tapped is not True:
                # "A **tapped** land": untapping an untapped permanent is no
                # payment at all, so the word is required rather than optional.
                stream.reset(mark)
                raise stream.error("an untap cost names a tapped permanent")
            costs.append(ast.UntapPermanentCost(untapped))
            stream.accept_punct(",")
            continue
        if stream.at_word("put"):
            # "Put a page counter on this artifact" (Mazemind Tome) — a cost
            # that adds a marker rather than spending one — and "Put a -1/-1
            # counter on **a creature you control**" (Wandering Mage), which is
            # the same cost aimed somewhere else and *can* be unpayable.
            mark = stream.mark()
            stream.advance()
            # "Put **a card from your hand on top of your library**" (Hidden
            # Retreat). The other thing a cost's "put" can move, and the payer
            # chooses which card but nothing narrows it — so it is read here,
            # before the counter branch below, whose counter-kind probe would
            # take "a" and then refuse the line at "card".
            if stream.accept_phrase(
                "a", "card", "from", "your", "hand", "on", "top", "of", "your",
                "library",
            ):
                costs.append(ast.PutHandCardOnLibraryCost())
                stream.accept_punct(",")
                continue
            if stream.accept_word("a", "an"):
                # The kind through the counter vocabulary rather than off a bare
                # word: a P/T counter is spelled in symbols (CR 122.1a), so
                # ``peek_word`` returned None for "-1/-1" and the branch fell
                # through to "unrecognized activation cost".
                try:
                    kind = _expect_counter_kind(stream)
                except GrammarError:
                    kind = None
                if kind is not None and stream.accept_word("counter") and stream.accept_word("on"):
                    if stream.accept_kind(SELF) or stream.accept_phrase("this", "artifact"):
                        costs.append(ast.PutCounterCost(kind.text))
                        stream.accept_punct(",")
                        continue
                    # A chosen permanent. Gated by the same key set every other
                    # chosen cost is gated by: the payment path picks with
                    # ``subject_matches``, so a phrase it cannot test would let
                    # the counter land on anything at all — and the *cost* would
                    # then be payable in cases the card does not allow, which is
                    # the direction a cost must never be wrong in.
                    marked = stream.mark()
                    try:
                        # The same reader every other chosen cost uses, so the
                        # quantifier this admits ("a creature", never "two
                        # creatures" or "target creature") is one answer rather
                        # than a second opinion about what may pay.
                        on = _parse_cost_object(stream, "put a counter on")
                    except GrammarError:
                        on = None
                    if on is not None and _is_chargeable_counter_target(on):
                        costs.append(ast.PutCounterCost(kind.text, subject=on))
                        stream.accept_punct(",")
                        continue
                    stream.reset(marked)
            stream.reset(mark)
        if stream.at_word("remove"):
            costs.append(_parse_counter_removal_cost(stream))
            # "Remove five fuse counters from this enchantment **and sacrifice
            # it**" (Goblin Bomb). One printed clause with two payments in it,
            # joined by "and" rather than by the comma every other pair of
            # costs uses — so the loop's separator never saw it and the whole
            # ability refused. The pronoun is read here, attached to the clause
            # that just named the source, because "it" has exactly one referent
            # at this point in the sentence and reading it anywhere else would
            # be a guess.
            if stream.accept_phrase("and", "sacrifice", "it"):
                costs.append(
                    ast.SacrificeCost(
                        ast.ObjectFilter(is_source=True), count=ast.Fixed(1)
                    )
                )
            stream.accept_punct(",")
            continue
        if stream.at_word("discard"):
            stream.advance()
            if stream.accept_phrase("the", "last", "card", "you", "drew", "this", "turn"):
                costs.append(ast.DiscardCost(ast.Fixed(1), last_drawn=True))
            elif stream.accept_phrase("this", "card"):
                # "Discard this card" (Waker of Waves). The card itself, which
                # is also what says the ability functions from the hand at all
                # (CR 113.6) — so it is its own cost rather than a narrowed
                # "discard a card": the payer chooses nothing.
                costs.append(ast.DiscardCost(ast.Fixed(1), self_card=True))
            elif stream.accept_phrase("your", "hand"):
                # "Discard your hand" (Subira). Every card at once — no choice
                # for the payer, no filter to narrow, and payable with an empty
                # hand, because discarding nothing is discarding your hand.
                costs.append(ast.DiscardCost(ast.Fixed(0), whole_hand=True))
            else:
                # "Discard a card" (Seasoned Hallowblade) — the payer picks, and
                # ``ActivatedAbilityCost.discard_cards`` is what collects it.
                # Only the singular is admitted: a counted "discard two cards"
                # is a shape nothing charges, and admitting it would describe a
                # payment that never happens.
                narrowed = _parse_card_alternatives(stream)
                if narrowed is None:
                    raise stream.error("unrecognized discard cost")
                # "Discard a card **at random**" (Coral Helm). Read after the
                # noun phrase because that is where it is printed, and folded
                # onto this cost rather than left for the effect parser — it
                # says how the cost is paid, not what happens afterwards.
                at_random = bool(stream.accept_phrase("at", "random"))
                costs.append(
                    ast.DiscardCost(ast.Fixed(1), filters=narrowed, at_random=at_random)
                )
            stream.accept_punct(",")
            continue
        break
    if pips:
        costs.insert(0, ast.ManaCost(tuple(sorted(pips.items()))))
    if not stream.exhausted:
        raise stream.error("unrecognized activation cost")
    return tuple(costs)
