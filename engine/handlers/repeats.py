"""``Repeat this process …`` — the sentence that says the sentences before it
happen again.

The handler twin of ``engine/grammar/lowering/repeats.py``, and it carries that
module's argument: the cards that print the words are different mechanisms, so
they are one family and several handlers rather than one handler with a flag.
A round of offers repeated while anybody took one (Eureka) or until a pile is
gone (Thieves' Auction), one seat's decision taken again after every round
(Forbidden Ritual), a round the toll's "if you do" runs again (Crooked
Scales), a round repeated while a record says so (Grindstone), and a round
repeated until one of its stopping clauses holds (Tainted Pact).

Every loop here is ``run_resumable`` (``engine/resumption.py``): a step of a
round suspends whenever an interactive seat is asked something, and the steps
behind it are the work still owed. Split out of ``control_flow.py`` at the
2,000-line cap's split round; a round's steps run through
``control_flow._run``, which is why this is the one family that imports it.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from ..oracle_types import (CLAIMABLE_EXILED_CARDS, EXILED_THIS_WAY_OBJECTS,
                            SWEPT_OWNER_SEATS, PROCESS_ROUNDS_SO_FAR)
from ..repeated_offers import OFFER_TAKEN_RESULTS
from ..resumption import run_resumable
from .control_flow import _run, _steps, evaluate_condition
from .offers import _offered_seats
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


#: The last item :func:`repeat_offer_round` walks: the end of one round, where
#: whether there is another one is decided.
_END_OF_ROUND = object()


@effect_handler("repeat_offer_round")
def repeat_offer_round(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Starting with you, each player may put a permanent card from their hand
    onto the battlefield. **Repeat this process until no one puts a card onto
    the battlefield.**" (Eureka.)

    One round is the offer made to every seat in turn (CR 101.4), and the round
    happens again whenever anybody took it. What "anybody took it" reads is the
    record the offered act leaves — see ``engine/repeated_offers.py``, which is
    the one table this and the lowering that admitted the clause both ask.

    Both loops are ``run_resumable``: an interactive seat's pick suspends the
    resolution, and the seats behind it — and the rounds behind *that* — are the
    work still owed. The decision about the next round therefore cannot sit
    after the loop, where it would not run at all once a seat stopped to think;
    it is the loop's own last step, which is what ``_END_OF_ROUND`` is for.

    Termination is a property of the act, not a counter: every offer taken moves
    a card out of a hand, so the rounds are bounded by the cards there were.
    """
    steps = _steps(instruction, "action")
    actor = instruction.payload.get("actor", "each_player")
    start_seat = (
        game.players.index(context.caster)
        if instruction.payload.get("offer_order") == "you"
        else None
    )
    taken = context.results.setdefault(OFFER_TAKEN_RESULTS, [])

    def run_round() -> None:
        # Re-asked each round: a seat that has left the game is nobody
        # (CR 800.4a), and a round is not a snapshot of who was there first.
        seats = _offered_seats(game, actor, context, start_seat=start_seat)
        at_round_start = len(taken)

        def offer(item) -> None:
            if item is _END_OF_ROUND:
                if len(taken) > at_round_start:
                    run_round()
                return
            # The offered seat is "their hand" and "that player" inside the act,
            # exactly as ``_offer_to_seat`` rebinds it for a one-shot offer. The
            # replacement shares this context's ``results``, which is how every
            # seat of every round appends to the one record above.
            _run(game, steps, dataclasses.replace(context, target=game.players[item]))

        run_resumable(game, [*seats, _END_OF_ROUND], offer)

    run_round()
    return True, "resolved"


def _claimable_exile_pile(game: Game, context) -> list[tuple[int, object]]:
    """The pile "one of the exiled cards" names, as ``(owner_seat, card)`` pairs.

    Read off ``EXILED_THIS_WAY_OBJECTS``, whose element type is a property of the
    zone the exile emptied — see that key. Both shapes are named here rather
    than told apart by a type test that happens to work: a battlefield sweep
    records ``Permanent``s, whose owner is the one thing CR 400.7 makes
    unanswerable once the card is in exile, and an exile out of a graveyard
    records the cards, whose owner is the seat whose pile they came out of.

    The seat is resolved **now**, while the record still says who each object
    belonged to, and carried on the pile: several decks share one
    ``CardDefinition`` object, so a scan of the exile zones later would answer
    with whichever seat was asked first.
    """
    owners = context.results.get(SWEPT_OWNER_SEATS) or {}
    pile: list[tuple[int, object]] = []
    for entry in context.results.get(EXILED_THIS_WAY_OBJECTS) or ():
        card = getattr(entry, "card", None)
        if card is not None:
            # Off the record the sweep wrote, never off the permanent: by the
            # time this runs the object has left the battlefield, so
            # ``owner_index_of`` has nothing but a metadata key a hand-built
            # board never stamps — and it would answer None for exactly the
            # permanents the sweep routed correctly a moment earlier.
            seat = owners.get(entry.permanent_id)
            if seat is None:
                seat = game.owner_index_of(entry)
        else:
            card = entry
            seat = next(
                (
                    index for index, player in enumerate(game.players)
                    if any(held is card for held in player.exile)
                ),
                None,
            )
        if seat is None or card is None:
            continue
        pile.append((seat, card))
    return pile


@effect_handler("claim_exiled_cards_in_turn")
def claim_exiled_cards_in_turn(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile all nontoken permanents. **Starting with you, each player chooses
    one of the exiled cards and puts it onto the battlefield tapped under their
    control. Repeat this process until all cards exiled this way have been
    chosen.**" (Thieves' Auction.)

    One round is the pick offered to every seat in turn (CR 101.4), and the
    rounds go on while the pile has cards in it. ``repeat_offer_round``'s shape
    one decision over, with two differences that are the whole of why it is its
    own handler: the pick is **mandatory**, so there is no record of takers to
    end on, and the bound is the pile rather than the round — four cards among
    three players is two passes, and the second stops after the first seat.

    The loop is ``run_resumable`` for that handler's stated reason: an
    interactive seat's pick suspends the resolution, and the seats behind it —
    and the rounds behind *that* — are the work still owed, so the question of
    whether there is another round has to be the loop's own last step rather
    than a line after it (``_END_OF_ROUND``).

    Termination is a property of the act: every answered pick takes a card off
    the pile, so the rounds are bounded by the cards there were. A round that
    took **nothing** ends the loop outright rather than being repeated — a
    prompt whose answer was refused would otherwise hand the same pile round
    for ever, which is a hang rather than a wrong number.
    """
    pile = context.results.get(CLAIMABLE_EXILED_CARDS)
    if pile is None:
        pile = _claimable_exile_pile(game, context)
        context.results[CLAIMABLE_EXILED_CARDS] = pile
    tapped = bool(instruction.payload.get("tapped"))
    repeat = bool(instruction.payload.get("until_pile_empty"))
    # "Starting with you" — the seat that put the spell on the stack. Without
    # the words CR 101.4's default stands, which is the active player.
    start_seat = (
        game.players.index(context.caster)
        if instruction.payload.get("claim_order") == "you"
        and context.caster in game.players
        else None
    )
    card_name = getattr(context.card, "name", "an effect")

    def run_round() -> None:
        # Re-asked each round: a seat that has left the game is nobody
        # (CR 800.4a), and a round is not a snapshot of who was there first.
        seats = _offered_seats(game, "each_player", context, start_seat=start_seat)
        at_round_start = len(pile)

        def claim(item) -> None:
            if item is _END_OF_ROUND:
                if repeat and pile and len(pile) < at_round_start:
                    run_round()
                return
            if not pile:
                # The pile ran out part-way through the round. The seats behind
                # this one are asked nothing at all, which is what "until all
                # cards have been chosen" means when the cards run out first.
                return
            game.arm_pending_choice(
                "exiled_pile_claim", item,
                card_name=card_name,
                options=[card.name for _, card in pile],
                tapped=tapped,
                _context=context,
            )

        run_resumable(game, [*seats, _END_OF_ROUND], claim)

    run_round()
    return True, "resolved"


#: The last item :func:`repeat_optional_process` walks: the end of one round,
#: where the seat is asked whether there is another. A sentinel and not a step,
#: because the question is not an effect — and it has to be *inside* the loop,
#: for ``engine/resumption.py``'s standing rule: a round that stopped to ask
#: something would never reach a line written after the loop.
_ASK_TO_REPEAT = object()


@effect_handler("repeat_optional_process")
def repeat_optional_process(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Sacrifice a nontoken permanent. If you do, target opponent loses 2 life
    unless that player sacrifices a permanent of their choice or discards a
    card. **You may repeat this process any number of times.**" (Forbidden
    Ritual.)

    One round is every step of the printed process, and the round happens again
    whenever this effect's controller says so. That is the whole difference
    from ``repeat_offer_round`` beside it, which reads a *record* to decide: an
    unbounded "any number of times" has no record and no bound, so the decision
    is a prompt and the loop ends on the answer.

    The next round is run by the prompt's own resolver, holding this same
    instruction — the shape ``coin_flip_stakes_loop`` already uses for Game of
    Chaos's "flip again?", and for that shape's reason: what runs next is a
    whole instruction rather than a branch, so nothing here has to know how many
    rounds there will be.

    Both loops are ``run_resumable``. A step of the round suspends whenever an
    interactive seat is asked something (the sacrifice prompt is the first
    thing this card does), and the steps behind it — and the question about the
    next round — are the work still owed. The loop is the last thing this
    handler does, which is the other half of that rule.
    """
    steps = _steps(instruction, "steps")
    seat = game.players.index(context.caster)

    def step(item) -> None:
        if item is _ASK_TO_REPEAT:
            game.arm_pending_choice(
                "repeat_process", seat,
                card_name=getattr(context.card, "name", "Effect"),
                _again=instruction,
                _context=context,
            )
            return
        game._execute_oracle_instruction(item, context)

    run_resumable(game, [*steps, _ASK_TO_REPEAT], step)
    return True, "resolved"


#: The loop a round is running under, for the step inside it that asks for
#: another. In the resolution's own scratchpad because that is the one thing
#: every step of a resolution shares, and because the asking step is not
#: reached by the loop at all: it runs from an ``optional_pay`` prompt's
#: resolver, after the round that armed it has finished.
REPEAT_PROCESS = "repeat_process_this_way"


@effect_handler("request_process_repeat")
def request_process_repeat(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…unless you pay {3} **and repeat this process**." (Crooked Scales.)

    What the toll bought, as the offer's "if you do" branch — and the thing
    that *runs* the next round, rather than a flag some loop reads afterwards.

    That is the shape ``repeat_optional_process`` and ``coin_flip_stakes_loop``
    already have, and here it is forced rather than chosen: an ``optional_pay``
    does not suspend the resolution that armed it, so by the time the seat has
    answered, the round — and every loop around it — has returned. A record
    read between rounds would be read before the payment existed, and Crooked
    Scales would flip exactly once however much its controller paid.

    So the round hands its own instruction down the scratchpad
    (:data:`REPEAT_PROCESS`) and this step runs it again. The dispatch is
    ``_execute_oracle_instruction``'s, not a direct call, so the next round
    goes through the same door as the first, and it is the last thing this
    handler does — ``engine/resumption.py``'s rule, since the round it starts
    can suspend on the very next toll.
    """
    again = context.results.get(REPEAT_PROCESS)
    if again is None:
        # Nothing to repeat. Only reachable if the marker outlived the wrapper
        # its lowering puts round the line, which no compiled program does —
        # said rather than assumed, because a silent no-op here is a card that
        # charges its controller {3} for nothing.
        game.log.append(
            f"{getattr(context.card, 'name', 'Effect')}: no process to repeat"
        )
        return True, "resolved"
    game.log.append(
        f"{getattr(context.card, 'name', 'Effect')}: repeating the process"
    )
    game._execute_oracle_instruction(again, context)
    return True, "resolved"


@effect_handler("repeat_process_on_request")
def repeat_process_on_request(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Flip a coin. If you win the flip, destroy target creature an opponent
    controls. If you lose the flip, destroy target creature you control
    **unless you pay {3} and repeat this process**." (Crooked Scales.)

    The fourth repeat in this file and the fourth mechanism.
    ``repeat_offer_round`` ends on a round nobody took,
    ``repeat_optional_process`` on a seat's answer to a question printed as its
    own sentence, ``repeat_process_while`` on a condition asked of what the
    round did — and this one on a **price inside the round**, charged on one
    arm of a coin flip that may not even have been taken.

    So the loop is round the *line*: what repeats is the flip and both of its
    arms, and the sentence that charges for another round is two branches down
    inside the third of them. All this handler does is run the round and say,
    in the scratchpad, which instruction another round would be — the asking is
    :func:`request_process_repeat`'s, because the answer arrives after this has
    returned.

    Through ``_run`` like every other wrapper here, so a step naming its own
    role of a shared announcement is scoped to it (``_role_scoped``) and a
    round that stops to ask something takes the rest of itself with it.

    Termination is the card's. Every round costs its controller {3} out of a
    finite pool and a round nobody pays for asks for nothing, so declining —
    or being unable to pay — ends it, as does winning the flip.
    """
    steps = _steps(instruction, "steps")
    if not steps:
        return True, "resolved"
    context.results[REPEAT_PROCESS] = instruction
    return _run(game, steps, context)


@effect_handler("repeat_process_while")
def repeat_process_while(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target player mills two cards. **If two cards that share a color were
    milled this way, repeat this process.**" (Grindstone.)

    The third repeat in this file and the third mechanism: ``repeat_offer_round``
    ends on a round nobody took, ``repeat_optional_process`` on a seat's
    answer, and this one on a **condition asked of what the round just did**.

    ``resets`` is the whole reason the loop terminates on a real board. The
    condition reads records the round writes, and those records accumulate
    across an effect by design ("what did this whole resolution mill?") — so
    each round clears exactly the keys its own steps write, which is what makes
    "milled **this way**" mean this round's cards. Without it Grindstone would
    be asked about every card it had milled so far, find a shared colour among
    them for ever, and mill until the library was empty on any two coloured
    cards at all.

    **No ``run_resumable``**, unlike the two loops above, and that is a
    property of this shape rather than an omission: the condition is asked
    *between* rounds, so a round that suspended part-way would leave the
    question about a round that had not happened. The lowering keeps that
    honest by refusing a condition whose records the round does not write —
    a round with nothing to ask about cannot be a round this repeats.

    Termination is the card's, not a cap here: the round has to write the
    record the condition reads, and a round that writes an empty one answers
    False. Grindstone's mill shrinks a finite library every time round, and an
    empty library mills nothing, which is exactly that.
    """
    steps = _steps(instruction, "steps")
    condition = dict(instruction.payload.get("condition") or {})
    resets = tuple(instruction.payload.get("resets") or ())
    if not steps or not condition:
        return True, "resolved"
    while True:
        for key in resets:
            context.results.pop(key, None)
        for item in steps:
            game._execute_oracle_instruction(item, context)
        if not evaluate_condition(game, context, condition):
            return True, "resolved"
        game.log.append(f"{getattr(context.card, 'name', 'Effect')}: repeating")


#: The loop a round is running under, for :func:`end_process_round` — the step
#: that is the end of that round and may run long after the loop has returned.
#: ``REPEAT_PROCESS``'s arrangement and for its reason.
PROCESS_UNTIL = "repeat_process_until_this_way"

#: Whether :func:`repeat_process_until` is on the Python stack *right now*, and
#: what the round that just ended inside it asked for. A round that ends
#: inline is repeated by the loop that ran it; one that ends on a seat's answer
#: finds no loop there and starts the next round itself.
_PROCESS_LOOP_LIVE = "repeat_process_until_live"
_PROCESS_ROUND_AGAIN = "repeat_process_until_again"


@effect_handler("repeat_process_until")
def repeat_process_until(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile the top card of your library. You may put that card into your
    hand unless it has the same name as another card exiled this way. **Repeat
    this process until you put a card into your hand or you exile two cards
    with the same name, whichever comes first.**" (Tainted Pact.)

    One more repeat in this file and one more mechanism: a loop that ends on
    conditions asked **when the round is over** — and whose round may end in
    an offer, so "over" can be an answer away. ``repeat_process_while`` asks
    its condition on the line after the round and says why it cannot be
    resumable; this one's question is a *step* of the round instead
    (:func:`end_process_round`, which the lowering puts on every way out of
    the round's last sentence), so it is asked wherever the round really ends:
    here, inline, or in the resolver of the prompt the round stopped on.

    That is why there are two ways to start the next round. A round that ended
    inline says so in the scratchpad and this loop runs it — a ``while``, so a
    process of sixty prompt-free rounds is sixty turns of a loop and not sixty
    nested resolutions. A round that ended on an answer finds this function
    long returned, and :func:`end_process_round` dispatches the instruction
    again, which is ``request_process_repeat``'s shape.

    ``resets`` are the records the round's own steps write. Before each round
    their lists are filed under ``PROCESS_ROUNDS_SO_FAR`` and the keys cleared:
    "that card" is this round's card, and "another card exiled this way" is
    every round's.

    The round is the last thing each turn of the loop does, which is
    ``engine/resumption.py``'s rule — after it there is only the read of what
    the round's own end step recorded.
    """
    steps = _steps(instruction, "steps")
    if not steps:
        return True, "resolved"
    results = context.results
    results[PROCESS_UNTIL] = instruction
    while True:
        earlier = results.setdefault(PROCESS_ROUNDS_SO_FAR, {})
        for key in instruction.payload.get("resets") or ():
            written = results.pop(key, None)
            if isinstance(written, (list, tuple)) and written:
                earlier.setdefault(key, []).extend(written)
        results[_PROCESS_ROUND_AGAIN] = False
        results[_PROCESS_LOOP_LIVE] = True
        try:
            _run(game, steps, context)
        finally:
            results[_PROCESS_LOOP_LIVE] = False
        if not results.pop(_PROCESS_ROUND_AGAIN, False):
            return True, "resolved"


@effect_handler("end_process_round")
def end_process_round(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The end of one round of :func:`repeat_process_until`, and the only
    place its stopping clauses are asked.

    Three answers. **A stopping clause holds**: the process is over. **The
    round did nothing** — not one record its steps write was written: a
    process that can no longer be performed is not repeated (CR 101.3: any
    part of an instruction that is impossible to perform is ignored). That is
    Tainted Pact on an empty library, where exiling the top card exiles
    nothing; nobody loses, because nothing was drawn. It is also what keeps a
    loop whose clauses can no longer come true from being a hang. **Otherwise**
    the process happens again.

    The stopping clauses come first, so a round that both ended the process
    and emptied the library reports the reason the card printed.
    """
    loop = context.results.get(PROCESS_UNTIL)
    name = getattr(context.card, "name", "Effect")
    if loop is None:
        # Only reachable if the step outlived the wrapper its lowering puts
        # round it, which no compiled program does — said rather than assumed.
        game.log.append(f"{name}: no process to repeat")
        return True, "resolved"
    if any(
        evaluate_condition(game, context, dict(condition))
        for condition in loop.payload.get("until") or ()
    ):
        game.log.append(f"{name}: the process ends")
        return True, "resolved"
    if not any(context.results.get(key) for key in loop.payload.get("resets") or ()):
        game.log.append(f"{name}: the process cannot continue")
        return True, "resolved"
    game.log.append(f"{name}: repeating the process")
    if context.results.get(_PROCESS_LOOP_LIVE):
        context.results[_PROCESS_ROUND_AGAIN] = True
        return True, "resolved"
    game._execute_oracle_instruction(loop, context)
    return True, "resolved"
