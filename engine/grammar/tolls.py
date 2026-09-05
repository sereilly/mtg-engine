"""The **toll** — "unless <player> <pays a price>" and what each way of
covering it buys.

Split out of ``sentence_clauses`` at the thousand-line guard, along the
boundary that module's own docstring already drew. ``sentence_clauses`` is the
*frame* ``parse_statement`` reads around a body — a leading "For each …,", a
linked duration, a rounding that distributes across a chain — and every one of
those answers "what does this clause say about the shape of the sentence".
These answer a different question: **what price is offered, to whom, and what
does paying it buy.** That is one family with one vocabulary (a payer, a price,
a consequence), and it is the family the pool keeps adding printed currencies
to — mana, a discard, a mill, a counter placement, a card put back on a library,
and now a sacrifice — so it is the half that grows with the pool.

Below ``sentence_clauses``, which imports it and is never imported back, and
handed ``parse_body`` rather than reaching for ``statements``: the same
inversion ``sentence_clauses`` itself makes one layer up.

``prices.py`` is the *other* module named for a price and it is a different
layer, deliberately: that one is a floor under ``phrases`` reading a printed
mana or life cost out of a sentence, and these productions read whole
**effects** as prices ("unless that player sacrifices a permanent of their
choice") and so must sit above ``effects``. One reads symbols, the other reads
sentences.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .errors import GrammarError
from .references import parse_player_ref
from .stream import TokenStream
from .phrases import _accept_life_alternative, _parse_mana_payment
from .sacrifices import _parse_counted_sacrifice
from .effects import (_parse_discard, _parse_mill, _parse_put_counter,
                      _parse_put_hand_cards_on_library)


def _parse_unless_player_pays(stream: TokenStream, parse_body) -> "ast.UnlessPlayerPays | None":
    """``Unless <player> pays <cost>, <statement>.`` (Scarwood Bandits.)

    Returns None with the cursor untouched for anything else opening with
    "unless", so the trailing "…unless <condition>" every other sentence can
    carry keeps its own reader.

    The payer must be a *player reference the engine can enumerate seats from*;
    the cost must be mana. Both are refused rather than skipped, because a payer
    nobody is asked and a cost nobody is charged are the same failure — the
    effect happening unconditionally, which is the card without its clause.
    """
    mark = stream.mark()
    if not stream.accept_word("unless"):
        return None
    payer = parse_player_ref(stream)
    if payer is None or not stream.accept_word("pays", "pay"):
        stream.reset(mark)
        return None
    try:
        cost = _parse_mana_payment(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if cost is None or not stream.accept_punct(","):
        stream.reset(mark)
        return None
    return ast.UnlessPlayerPays(payer, cost, parse_body(stream))


#: Payer references naming a *set* of seats one payment satisfies. "Any player
#: pays {3}" (Icy Prison) is one toll the whole table is offered and the first
#: acceptance ends — which is exactly :class:`ast.UnlessPlayerPays`, a chain,
#: and not one prompt per seat. Every other reference names a single seat, whose
#: offer is the ``May`` an "unless" already is.


_ENUMERATED_PAYERS = frozenset({"each_player", "each_opponent", "target_opponent"})


#: The player references a graded toll's outcome sentences may name. All three
#: are the *offered* seat rather than a seat of their own: "that player" and
#: "they" are the back-reference every consumer already reads as one referent,
#: and "its controller" is the offer's own printed actor restated.
_TOLL_OUTCOME_PAYERS = frozenset({"that_player", "controller"})


def _graded_offer(statement) -> "ast.May | None":
    """The cost offer an outcome sentence would attach to, or None.

    One statement in and one node out, because the offer may be printed inside
    a loop — "**For each of those creatures,** its controller may pay {1} or
    {2}" (Winter's Chill) — and the sentences behind it are still about that
    one offer. Anything else is not this shape and keeps whatever refusal it
    already had.
    """
    if isinstance(statement, ast.ForEach):
        statement = statement.effect
    if not isinstance(statement, ast.May) or statement.cost is None:
        return None
    if not isinstance(statement.actor, ast.PlayerRef):
        return None
    return statement


def _replace_offer(statement, offer: "ast.May"):
    """*statement* with its offer swapped for *offer* — the inverse of
    :func:`_graded_offer`, so the loop around it survives the rewrite."""
    if isinstance(statement, ast.ForEach):
        return dataclasses.replace(statement, effect=offer)
    return offer


def _accept_graded_toll_outcomes(parse_body, stream, statement):
    """``. If that player doesn't, <A>. If that player pays only {N}, <B>.``

    "Choose X target attacking creatures. For each of those creatures, its
    controller may pay {1} or {2}. **If that player doesn't, destroy that
    creature at end of combat. If that player pays only {1}, prevent all combat
    damage** …" (Winter's Chill.)

    The sentences that say what each way of covering an offer *buys*. They are
    read here, around the sentence that made the offer, rather than as
    statements of their own for the reason every other clause in this module is:
    they modify a sentence the parser has already read, and on their own they
    name a decision nobody made. Two of them, and each is a different question —
    "doesn't" is the decline branch every ``May`` already has, and "pays only
    {N}" is which of CR 118.8's alternatives was taken, which is the part no
    offer in the pool had needed before: an alternative is normally a second way
    to cover *one* consequence, and here the three ways buy three different
    things.

    Refuses without consuming, so a sentence opening with "if" that is not one
    of these keeps whatever reading it had.
    """
    offer = _graded_offer(statement)
    if offer is None:
        return None
    costs = (offer.cost, *offer.cost_alternatives)
    outcomes = list(offer.option_effects) or [None] * len(costs)
    otherwise = offer.otherwise
    changed = False
    while True:
        mark = stream.mark()
        if not (stream.accept_punct(".") and stream.accept_word("if")):
            stream.reset(mark)
            break
        payer = parse_player_ref(stream)
        if payer is None or payer.kind not in _TOLL_OUTCOME_PAYERS:
            stream.reset(mark)
            break
        # "…**doesn't**" — the decline branch. Folded onto the offer's own
        # ``otherwise`` rather than becoming a conditional beside it, because
        # that is the same branch: two spellings of one field would be two
        # places for a handler to look.
        declined = bool(stream.accept_word("doesn't"))
        paid: "ast.ManaCost | None" = None
        if not declined:
            if not (stream.accept_word("pays", "pay") and stream.accept_word("only")):
                stream.reset(mark)
                break
            try:
                paid = _parse_mana_payment(stream)
            except GrammarError:
                stream.reset(mark)
                break
        if not stream.accept_punct(","):
            stream.reset(mark)
            break
        try:
            body = parse_body(stream)
        except GrammarError:
            stream.reset(mark)
            break
        if declined:
            if otherwise is not None:
                # Two decline branches would be two consequences for one
                # refusal, and nothing says which. Refusing keeps the line's
                # own error rather than silently dropping one of them.
                stream.reset(mark)
                break
            otherwise = body
        else:
            # "…pays **only {1}**" names one of the printed alternatives. A
            # cost the offer never printed is a sentence about an option that
            # does not exist, so the clause is handed back rather than attached
            # to whichever option happens to be first.
            if paid not in costs:
                stream.reset(mark)
                break
            outcomes[costs.index(paid)] = body
        changed = True
    if not changed:
        return None
    return _replace_offer(
        statement,
        dataclasses.replace(
            offer, otherwise=otherwise,
            # Only when a "pays only {N}" clause really named one. "…its
            # controller may pay {1}. **If that player doesn't**, …" (Tidal
            # Flats) prints the decline branch and nothing else, which is not a
            # graded offer at all — one empty slot per printed option would
            # make the lowering read it as an offer where every way of paying
            # buys nothing, and refuse the line.
            option_effects=(
                tuple(outcomes) if any(o is not None for o in outcomes) else ()
            ),
        ),
    )


def _accept_price_action(
    stream: TokenStream, payer: ast.PlayerRef
) -> "ast.Statement | None":
    """One printed **price** a toll may charge, with the payer already read —
    or None with the cursor back where it started.

    Every currency here is an *action* rather than a mana cost, and each is
    decomposed the same way for the same reason: an "unless" is an offer with a
    penalty, which is exactly what :class:`ast.May` already says, so the offer,
    the penalty and the "you have nothing to give" case all come from machinery
    that already works. Nothing new is fused.

    A reader of its own rather than a chain inside :func:`_accept_trailing_toll`
    because one printed clause can name **two** of these — "unless that player
    sacrifices a permanent of their choice **or** discards a card" (Forbidden
    Ritual) — and the alternation has to read the same price list on both sides
    of the "or". Two copies would be two vocabularies, and the second half of
    the sentence would understand fewer currencies than the first.

    A price it half-recognizes is rewound whole and refused, never dropped: a
    toll nobody is charged is the effect happening unconditionally, which is
    the card without its clause.
    """
    mark = stream.mark()
    # "…unless you **discard a card**" (Oath of Lim-Dul). A cost mana cannot
    # express, and the same decomposition the board family's "unless you
    # sacrifice" tails take: the discard is the offer's *action*, so the
    # takeability check that already knows an empty hand cannot pay it applies
    # unchanged.
    if stream.at_word("discards", "discard"):
        try:
            discard = _parse_discard(stream, payer)
        except GrammarError:
            stream.reset(mark)
            return None
        if discard is None:
            stream.reset(mark)
            return None
        return discard
    # "…unless you **mill two cards**" (Deep Spawn). The third cost mana cannot
    # express, decomposed exactly as the discard above is: the mill is the
    # offer's *action*, so it reaches the same `May` and the same prompt.
    #
    # No takeability entry answers it, and that is the rule rather than an
    # omission — CR 701.17b mills the whole library when it is shorter than the
    # number, so a player can always take this offer and a "can you?" check
    # would withdraw one the card makes.
    if stream.at_word("mills", "mill"):
        try:
            return _parse_mill(stream, payer)
        except GrammarError:
            stream.reset(mark)
            return None
    # "…unless that player **sacrifices a permanent of their choice**"
    # (Forbidden Ritual). The fifth printed currency, and the one the board
    # family has read since Mold Demon in its *own* "unless you sacrifice"
    # tail — read here through the same `sacrifices` floor, so the phrase means
    # one thing whichever sentence prints it and the offer, the takeability
    # gate and the charge cannot disagree about what the card asks for.
    #
    # Where the board family's tail is fixed to "you", this one carries the
    # payer the toll already read: the sentence names the seat out loud, and
    # CR 701.21a makes that seat the one who picks which permanent goes.
    if stream.at_word("sacrifices", "sacrifice"):
        stream.advance()
        try:
            return _parse_counted_sacrifice(stream, payer)
        except GrammarError:
            stream.reset(mark)
            return None
    # "…unless the player **puts a -1/-1 counter on a creature they control**"
    # (Thelon's Chant, Tourach's Chant). Another printed currency beside mana
    # and a discard, and the same decomposition for the same reason.
    if stream.at_word("puts", "put"):
        # "…unless they **put a card from their hand on top of their library**"
        # (Tainted Specter). The currency read before the counter branch
        # because both open on "put" and only one of them can consume "a card
        # from their hand"; the production refuses without consuming, so a
        # counter sentence still reaches the branch below.
        back_on_top = _parse_put_hand_cards_on_library(stream, payer)
        if back_on_top is not None:
            return back_on_top
        try:
            placement = _parse_put_counter(stream)
        except GrammarError:
            stream.reset(mark)
            return None
        # Only a *counter placement*: "put" also opens the object-moving family
        # ("put that card onto the battlefield"), which is not a price anybody
        # pays out of their own resources and has no takeability test behind it.
        if not isinstance(placement, ast.PutCounter):
            stream.reset(mark)
            return None
        return placement
    return None


def _accept_price_alternatives(
    stream: TokenStream, payer: ast.PlayerRef, first: ast.Statement, first_at: int
) -> ast.Statement:
    """*first*, or an :class:`ast.OneOf` when the toll goes on with "**or**".

    "…unless that player sacrifices a permanent of their choice **or** discards
    a card." (Forbidden Ritual.) Two ways to cover **one** offer, the payer
    choosing which — which is the same question CR 118.8's "…pay {B} or {3}"
    asks about a mana cost and the same node "sacrifice a creature or discard a
    creature card" (Crypt Lurker) already produces. So it is the same
    :class:`ast.OneOf`, the same prompt, the same default and the same
    takeability narrowing; inventing a second mechanism would mean two prompts
    and two places for an option to go unoffered.

    Not the mana spelling's ``cost_alternatives``, which is a list of *costs* on
    one offer: these alternatives are whole actions, and an action is not a
    symbol dict. The two answer the same printed word about different
    currencies.

    A near-miss rewinds to the "or" and leaves the sentence alone, so a trailing
    clause that is not a second price keeps whatever reading it had — and full
    token consumption then refuses the line rather than dropping half a price.
    """
    options = [first]
    spans = [(first_at, stream.pos)]
    while True:
        mark = stream.mark()
        if not stream.accept_word("or"):
            break
        start = stream.pos
        alternative = _accept_price_action(stream, payer)
        if alternative is None:
            stream.reset(mark)
            break
        options.append(alternative)
        spans.append((start, stream.pos))
    if len(options) == 1:
        return first
    return ast.OneOf(
        tuple(options), tuple(stream.text_between(a, b) for a, b in spans)
    )


def _accept_trailing_toll(
    parse_body,
    stream: TokenStream, body: ast.Statement
) -> "ast.Statement | None":
    """``<body> unless <player> pays <cost>`` — the toll, trailing its effect.

    One production for every printed cost shape, because what varies between
    the cards printing this sentence is the payer, the cost and the consequence
    and never the shape: an "unless" is an offer with a penalty, which is what
    :class:`ast.May` already says. The action-shaped prices are
    :func:`_accept_price_action`, one per printed currency; the mana one is read
    here because that spelling can also be a *chain* over several seats, which
    is a different node.

    Returns None with the cursor untouched for anything else opening with
    "unless" — a trailing condition, or a clause a verb's own production means
    to read — so this reader can sit around every sentence without claiming
    one it does not understand. A cost it half-recognizes is rewound whole
    rather than dropped: a toll nobody is charged is the effect happening
    unconditionally, which is the card without its clause.
    """
    # A printed **restriction** is not an effect a toll can put a penalty on.
    # "This creature can't block creatures with power 3 or greater **unless you
    # pay {1}**" (Hipparion) reads as an offer only if you forget that the body
    # is a static fact about declaring blockers, not something that resolves —
    # so the offer would be made at no moment, and the restriction would go
    # unenforced. `engine/combat_restrictions.py` is the reader that implements
    # it, gating `_can_block_attacker` and charging in `declare_blockers`.
    #
    # Refusing here rather than at lowering is the rule CLAUDE.md states for
    # exactly this collision: a derivation table is reached only where every
    # production refuses the line **in full**, because parsed-but-unlowered is
    # still parsed and takes the table's line away. Held by
    # `test_combat_restrictions_match_the_derivation_table_exactly`, which
    # compares the two readers over the whole shipped pool and found this one.
    if isinstance(body, ast.CombatRestriction):
        return None

    mark = stream.mark()
    if not stream.accept_word("unless"):
        return None
    payer = parse_player_ref(stream)
    if payer is None:
        stream.reset(mark)
        return None
    price_at = stream.pos
    action = _accept_price_action(stream, payer)
    if action is not None:
        # Not offered to an enumerated payer: `ast.May` is one offer to one
        # seat, and "each player" would be a chain — which only the mana
        # spelling below has a node for.
        if payer.kind in _ENUMERATED_PAYERS:
            stream.reset(mark)
            return None
        return ast.May(
            actor=payer,
            action=_accept_price_alternatives(stream, payer, action, price_at),
            otherwise=body,
        )
    if not stream.accept_word("pays", "pay"):
        stream.reset(mark)
        return None
    try:
        cost = _parse_mana_payment(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if cost is None:
        stream.reset(mark)
        return None
    if payer.kind in _ENUMERATED_PAYERS:
        return ast.UnlessPlayerPays(payer, cost, body)
    return ast.May(
        actor=payer,
        cost=cost,
        life_alternative=_accept_life_alternative(stream),
        otherwise=body,
    )


def accept_delayed_toll(
    parse_body, stream: TokenStream, body: "ast.Statement"
) -> "ast.Statement | None":
    """``<effect> <delay> unless <player> pays <cost> before that step``
    — the toll printed *behind* a trailing delay (Sabertooth Cobra).

    :func:`_accept_trailing_toll` runs around the sentence **body**, and this
    one runs around the sentence's *delay*: "the player gets another poison
    counter at the beginning of their next upkeep unless they pay {2} before
    that step" prints the window between the effect and its price, so by the
    time the words "unless" are reached the body reader has long stopped. The
    offer belongs inside the delayed ability rather than beside it — it is made
    when that ability resolves, which is the moment the card names.

    **"Before that step" is required**, and it is why this is not simply the
    trailing toll read a second time. The phrase is the payment *window*, and
    this engine has no priority window before a step in which a player could
    pre-commit — so what it means here is that the offer is made at the start of
    the named step, ahead of the effect it buys off. That is the same choice
    with the same information (a player untaps before their own upkeep, so the
    mana available is the mana the phrase was written about), and stating the
    requirement is what keeps the words from being a rider that could be deleted
    with no change to the parse. A card printing the toll after a delay *without*
    the window refuses, and grows a reading of its own.
    """
    mark = stream.mark()
    offer = _accept_trailing_toll(parse_body, stream, body)
    if offer is None:
        return None
    if not stream.accept_phrase("before", "that", "step"):
        stream.reset(mark)
        return None
    return offer


