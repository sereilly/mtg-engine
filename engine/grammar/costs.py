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

from ..subject_filters import object_only_filter
from . import ast
from .amounts import parse_amount
from .effects import _expect_counter_kind
from .phrases import _parse_card_alternatives
from .errors import GrammarError
from .lexer import MANA, SELF
from .lowering._common import (_PAYLOAD_HONOURED_FILTER_FIELDS,
                               _restrictions_beyond, chargeable_tap_filter)
from .nouns import parse_object_filter
from .readers import accept_source_reference
from .references import parse_target_spec
from .stream import TokenStream
from .vocabulary import CARD_TYPES, singular as _singular


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


def _is_chargeable_sacrifice(filt: ast.ObjectFilter) -> bool:
    """Whether the payment path can actually collect this sacrifice cost.

    A rider the charger cannot express must refuse the line rather than be
    dropped — dropped, Portcullis Vine sacrifices any creature at all while
    still reporting supported, which is the dropped-rider bug class.

    Which riders those are is **not** decided here. This asks the charger's own
    reader (``engine/oracle.py``'s ``_chargeable_sacrifice_filter``, through the
    filter-key set it gates on), because two readers of one clause drift and the
    direction they drift in is a cost nobody pays. The word "another" is left in
    the filter: the charger has the ability's source and compares by identity.
    """
    if filt.is_source:
        return True
    if not (filt.card_types or filt.subtypes):
        # An *unnamed* cost — one whose noun phrase pins neither a card type nor
        # a subtype — would let the charger eat anything on the board, including
        # a land. This is the one narrowing the key set cannot express, because
        # "which keys are set" and "does one of them name the object" are
        # different questions.
        #
        # A subtype alone does name it: "Sacrifice a Swamp" (Horror of Horrors)
        # is a land type (CR 205.3i) with no card type printed beside it, and
        # the charger's own reader carries it as ``subtype_filter`` — so
        # demanding a card type here refused a cost the payment path could
        # already collect, which is the two-readers-disagree failure this
        # function exists to prevent, in the direction that costs a card its
        # support rather than its narrowing.
        return False
    # ``controller`` travels beside it, for the reason the comment on the
    # charger gives: a sacrifice is paid from the payer's own battlefield, so
    # "creatures **you control**" narrows nothing the enumeration has not
    # already done — but a key handed to a matcher that cannot test it is a key
    # silently dropped, so it is lifted out rather than left in. Sword of the
    # Ages prints the phrase and refused for it.
    return object_only_filter(
        filt.to_payload(),
        carried_separately=frozenset({"exclude_self", "controller"}),
    ) is not None


def _is_chargeable_exile(filt: ast.ObjectFilter) -> bool:
    """Whether the payment path can actually collect this exile cost.

    :func:`_is_chargeable_sacrifice` one zone wider, and the same rule: the
    charger's own reader decides (``engine/oracle.py``'s
    ``chargeable_exile_payload``), so the two halves cannot answer differently.

    Two zones and no others. The battlefield is a permanent the payer controls;
    a **graveyard** is a card, and only the payer's own — "from your graveyard"
    is what Necropolis prints, and a phrase naming somebody else's pile is a
    cost this charger has no enumeration for.
    """
    from ..oracle import chargeable_exile_payload

    if filt.zone == "graveyard":
        # Whose pile. "your graveyard" (Necropolis) is the payer's own; **no
        # owner at all** is "a graveyard" — anybody's — which the charger
        # enumerates seat by seat. Anything else (a named opponent's) is a
        # phrase this charger has no enumeration for and refuses.
        if not filt.is_card:
            return False
        if filt.zone_owner is not None and filt.zone_owner.kind != "you":
            return False
    elif filt.zone != "battlefield" or filt.is_card:
        return False
    if not (filt.card_types or filt.subtypes):
        # An unnamed cost would let the charger eat anything the zone holds —
        # the same refusal `_is_chargeable_sacrifice` makes, for the same
        # reason, and it is the one narrowing a key set cannot express.
        return False
    # A restriction with no ``to_payload`` key at all would vanish before the
    # key check below ever saw it - the failure the AST gate in
    # ``subject_filter_payload`` exists for. Asked here as well, because this
    # reader does not go through that one.
    if _restrictions_beyond(
        filt, _PAYLOAD_HONOURED_FILTER_FIELDS | {"zone", "zone_owner", "is_card"}
    ):
        return False
    return chargeable_exile_payload(filt.to_payload()) is not None


def _is_chargeable_counter_target(filt: ast.ObjectFilter) -> bool:
    """Whether the payment path can find the permanent this counter goes on.

    "Put a -1/-1 counter on **a creature you control**" (Wandering Mage). The
    same two questions ``_is_chargeable_sacrifice`` asks, for the same reason:
    the payer's candidates are enumerated with ``subject_matches``, so a key it
    cannot test would be dropped — and a dropped narrowing on *this* cost is a
    counter landing somewhere the card does not name **and** an ability payable
    when it should not be.

    The phrase must also pin a card type or a subtype. Without one the cost
    could be paid by putting the counter on a land, which is no cost at all for
    a card that means to shrink a creature.
    """
    if filt.is_source:
        return True
    if not (filt.card_types or filt.subtypes):
        return False
    described = filt.to_payload()
    return not _restrictions_beyond(
        filt, _PAYLOAD_HONOURED_FILTER_FIELDS
    ) and object_only_filter(
        described, carried_separately=frozenset({"controller"})
    ) is not None


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

    The subject must be the ability's own source: :class:`ast.RemoveCounterCost`
    has no subject field, so "remove a counter from target creature" would be
    consumed and then read as the source's counter. That refuses instead.

    Asked of ``accept_source_reference`` rather than of the noun parser, because
    identity is the whole question here — the cost gives up a counter on *this*
    permanent and nothing about the permanent's characteristics is consulted. It
    is also the reader that knows a card naming itself is naming the source
    ("Remove a dream counter from **Rasputin**"), which the noun parser reads
    only in the "this <noun>" spelling; going through the filter first meant the
    self-named spelling refused with the noun parser's error rather than being
    read at all.
    """
    stream.expect_word("remove")
    count = ast.Fixed(1) if stream.accept_word("a", "an") else parse_amount(stream)
    counter = _expect_counter_kind(stream, " to remove").text
    stream.expect_word("counter", "counters")
    stream.expect_word("from")
    if not accept_source_reference(stream):
        raise stream.error("a counter-removal cost only reads the ability's own source")
    return ast.RemoveCounterCost(counter, count)


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
            elif stream.accept_word("and"):
                # "Sacrifice a creature **and a Swamp**" (Viscerid Drone). One
                # printed verb naming two *different* objects, so it becomes two
                # entries — the same decomposition Sword of the Ages' tail makes
                # one branch up, with a second noun phrase where that one has a
                # count. A single filter cannot hold it: the two are ANDed by
                # every matcher, and "a creature that is also a Swamp" is a
                # permanent this pool never prints.
                also = _parse_cost_object(stream, "sacrifice")
                if not _is_chargeable_sacrifice(also):
                    raise stream.error("no cost path charges a narrowed sacrifice")
                costs.append(ast.SacrificeCost(also))
            else:
                stream.reset(more)
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
            amount = parse_amount(stream)
            if not isinstance(amount, ast.Fixed) or amount.value <= 0:
                stream.reset(mark)
                raise stream.error("only a fixed, positive life payment is charged")
            if not stream.accept_word("life"):
                stream.reset(mark)
                raise stream.error("unrecognized activation cost")
            costs.append(ast.PayLifeCost(amount))
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
        if stream.at_word("put"):
            # "Put a page counter on this artifact" (Mazemind Tome) — a cost
            # that adds a marker rather than spending one — and "Put a -1/-1
            # counter on **a creature you control**" (Wandering Mage), which is
            # the same cost aimed somewhere else and *can* be unpayable.
            mark = stream.mark()
            stream.advance()
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
