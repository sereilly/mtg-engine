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
from .lowering._common import chargeable_tap_filter
from .nouns import parse_object_filter
from .readers import accept_source_reference
from .references import parse_target_spec
from .stream import TokenStream


def _parse_cost_object(stream: TokenStream, verb: str) -> ast.ObjectFilter:
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
    allowed = ("all",) if another else ("this", "a")
    if spec.quantifier not in allowed or spec.count != 1:
        raise stream.error(f"unsupported {verb} cost quantifier {spec.quantifier!r}")
    return replace(spec.filter, other_than_source=True) if another else spec.filter


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
    return object_only_filter(
        filt.to_payload(), carried_separately=frozenset({"exclude_self"})
    ) is not None


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
            sacrificed = _parse_cost_object(stream, "sacrifice")
            if not _is_chargeable_sacrifice(sacrificed):
                raise stream.error("no cost path charges a narrowed sacrifice")
            costs.append(ast.SacrificeCost(sacrificed))
            stream.accept_punct(",")
            continue
        if stream.accept_word("exile"):
            # ``ExileSelf`` names no object, so exiling anything else would be
            # consumed and then read as the source leaving the battlefield.
            exiled = _parse_cost_object(stream, "exile")
            if not exiled.is_source:
                raise stream.error("only exiling the ability's own source is a known cost")
            costs.append(ast.ExileSelf())
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
            # "Put a page counter on this artifact" — a cost that adds a marker
            # rather than spending one, so it is never unpayable and the
            # affordability check below has nothing to ask of it.
            mark = stream.mark()
            stream.advance()
            if stream.accept_word("a", "an"):
                kind = stream.peek_word()
                if kind and kind not in ("counter",):
                    stream.advance()
                    if stream.accept_word("counter") and stream.accept_word("on"):
                        if stream.accept_kind(SELF) or stream.accept_phrase("this", "artifact"):
                            costs.append(ast.PutCounterCost(kind))
                            stream.accept_punct(",")
                            continue
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
