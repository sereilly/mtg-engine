"""Lowering a hand emptying: the cards chosen out of one, and where they go.

The mirror of ``effects/hand.py``, split off ``lowering/cards.py`` at the
thousand-line guard and along the seam that module's docstring drew: what stays
in ``cards`` lowers a card **arriving** — a draw, a mill, a scry — and what is
here names cards **in a hand** and moves them. Sylvan Library's pick and its
"put the card on top", Elkin Lair's random exile, the three printings that put
a hand back onto a library, and the whole discard family.

**Two loops came with the first group and left at Prophecy's Phase 0**, for
``loops.py``, because neither names a card in a hand. "For each of those
cards" was read as the other half of Sylvan Library's pick, and the key the two
share was this module's argument for its own boundary — but the same function
reads "those creatures" (Winter's Chill) and "those artifacts" (Seeds of
Innocence) off two records no hand step writes, lowers onto ``for_each`` like
every loop there, and called ``_lower_for_each_destroyed`` its sibling while it
sat a module away from it. Truce's "for each card less than two a player draws
this way" read no hand at all; it is the twin of ``loops``' life-lost loop, as
its own docstring always said. The key went to ``_record_keys``, so the pick
here and the loop there spell it once.

**The discard came second**, when ``cards`` crossed the guard again, and the
boundary moved rather than being redrawn: the first split's docstring put a
discard on the "leaving for a graveyard" side of the line, and CR 701.9a
defines discarding as moving a card **from its owner's hand** — the hand is the
zone the rule names first, and it is the zone the prompt, the narrowing and the
per-seat tally are all about. The two fused shapes (a draw whose rider is a
discard, and a discard whose rider is a draw) came with it: they are one
sentence and had to stay with the function that reads the other half.

The parse side keeps its discard productions in ``effects/cards.py``, which is
the ordinary asymmetry this package already documents — the lowering half of a
family outgrows its parse half, and the mirror re-forms on the name rather than
on the contents.

``_lower_discard`` is the half of this module that grows: every line added here
since the discard arrived landed in it. So when the guard comes near again, cut
*inside* it, along its per-seat branches, rather than moving the family out of
the zone CR 701.9a names.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import (CHOSEN_COLOR_THIS_WAY, X_FROM_COUNT_PER_RECIPIENT,
                             OracleInstruction)
from .. import ast
from ..errors import LoweringError
from ._amounts import halved_count_spec
from ._common import (_amount_payload, _describe_targets, _is_you,
                      chargeable_card_filter)
from ._events import (_DAMAGED_PLAYER_EVENTS, _DEFENDING_PLAYER_EVENTS,
                      _EVENT_SUBJECT_CONTROLLERS, _EVENT_SUBJECT_PLAYERS,
                      EVENT_SUBJECT_CONTROLLER, EVENT_SUBJECT_PLAYER)
from ._record_keys import CHOSEN_HAND_CARDS_RESULT


def _lower_choose_cards_in_hand(
    node: ast.ChooseCardsInHand,
) -> tuple[OracleInstruction, ...]:
    """"Choose two cards in your hand drawn this turn." (Sylvan Library.)

    The pick alone: nothing moves, and the cards are recorded for the sentence
    after this one to repeat over.

    ``zone`` and ``zone_owner`` are honoured **by construction** rather than
    carried in the payload — this instruction reads one hand and it is the
    hand of the seat making the choice — so they are named here as carried and
    everything else in the phrase has to survive ``card_only_filter``. A
    narrowing that cannot be tested refuses the line, because a prompt offering
    a wider set than the card prints is a card that reports supported and
    cheats.
    """
    from ...subject_filters import card_only_filter
    from ._common import _restrictions_beyond, _PAYLOAD_HONOURED_FILTER_FIELDS

    filt = node.filter
    if filt.zone_owner is None or filt.zone_owner.kind != "you":
        raise LoweringError("the hand pick reads your own hand", node=node)
    leftover = _restrictions_beyond(
        filt,
        _PAYLOAD_HONOURED_FILTER_FIELDS | {"is_card", "zone", "zone_owner"},
    )
    if leftover:
        raise LoweringError(
            f"the hand pick does not honour {leftover[0]!r}", node=node
        )
    payload_filter = filt.to_payload()
    payload_filter.pop("zone", None)
    payload_filter.pop("zone_owner", None)
    described = card_only_filter(payload_filter)
    if described is None:
        raise LoweringError("no hand pick can test this narrowing", node=node)
    count = _amount_payload(node.count)
    if not isinstance(count, int) or count < 1:
        raise LoweringError("the hand pick chooses a printed number", node=node)
    return (
        OracleInstruction(
            "choose_cards_in_hand", "",
            {
                "count": count,
                "card_filter": described,
                # The provenance the phrase printed. Its own key rather than a
                # filter entry, because no reader of a *card* can answer it —
                # see ``ast.ChooseCardsInHand``.
                "drawn_this_turn": bool(node.drawn_this_turn),
                "result_key": CHOSEN_HAND_CARDS_RESULT,
            },
        ),
    )


def _lower_exile_random_from_hand(
    node: "ast.ExileRandomFromHand", event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """"At the beginning of each player's upkeep, **that player exiles a card at
    random from their hand**." (Elkin Lair.)

    Whose hand rides the ``recipient`` key the mill, the discard and Thought
    Lash's library exile already use — one convention for "which seat is this
    instruction about" rather than a second per family.

    "That player" is admitted only under an event that *freezes* a seat
    (CR 603.10), exactly as :func:`_lower_exile_entire_library` admits it. Read
    as the resolving player instead, this card would take a card out of its own
    controller's hand on every opponent's upkeep — wrong in the loud direction
    on three turns in four, and silent, because both readings exile exactly one
    card.

    The record it leaves is ``exiled_cards``, which is what makes the two
    sentences behind it lowerable at all: "the player may play that card" and
    "if the player hasn't played the card" are back-references, and the registry
    in ``_records.py`` is where the producer is declared.
    """
    kind = node.player.kind
    if kind == "you":
        recipient = "caster"
    elif kind == "that_player":
        if event not in _EVENT_SUBJECT_PLAYERS:
            raise LoweringError(
                "no event named {!r} freezes the seat 'that player' names".format(event),
                node=node,
            )
        recipient = EVENT_SUBJECT_PLAYER
    else:
        raise LoweringError(
            f"no handler exiles a card at random from {kind!r}'s hand", node=node
        )
    return (
        OracleInstruction(
            "exile_random_card_from_hand", "", {"recipient": recipient}
        ),
    )


def _lower_put_iterated_card_on_library(
    node: ast.PutIteratedCardOnLibrary,
) -> tuple[OracleInstruction, ...]:
    """"Put the card on top of your library." (Sylvan Library.)

    "The card" is the one the enclosing repetition is on, so this lowers to an
    instruction that reads ``context.iteration_target`` and nothing else. Its
    refusal outside a loop is the handler's, not this lowering's: a sentence
    can name the loop's object several steps in (inside an alternative, inside
    a conditional), and a lowering that tried to prove the loop exists from
    here would have to re-derive the whole enclosing statement.
    """
    return (
        OracleInstruction(
            "put_iterated_card_on_library", "", {"position": node.position}
        ),
    )


def _lower_put_hand_cards_on_library(
    node: ast.PutHandCardsOnLibrary, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """Brainstorm, Stunted Growth, Teferi's Puzzle Box.

    One kind for all three printings: the seat is payload, under the same
    ``recipient`` key ``_lower_mill`` reads, so "who does this happen to" has
    one convention rather than one per effect family.

    A seat this cannot name refuses rather than defaulting to the caster —
    putting the *wrong player's* cards back would be a strictly different card,
    and silently so, since both spellings move the same number of cards.

    *event* is the firing trigger's condition kind, and it is what tells "that
    player" apart from itself: under an offer (Tainted Specter) the seat is the
    one the resolution already targeted, and under "at the beginning of each
    player's draw step" (Teferi's Puzzle Box) it is the seat the fire site
    froze. Both are printed "that player", so nothing but the event can say
    which — the same fork ``_lower_mill`` reads one module over and
    ``_lower_discard`` reads below.
    """
    payload: dict[str, object] = {"amount": _amount_payload(node.count)}
    # "…**both on top of your library or both on the bottom**" (Dream Cache).
    # Emitted only when the card offers the choice, so every payload written
    # before this is byte-identical — and the prompt refuses a bottoming answer
    # without it, which is what keeps a client from bottoming a Brainstorm.
    if node.destination != "top":
        payload["destination"] = node.destination
    if node.whole_hand:
        # "**the cards from** their hand" — how many is a fact about the board
        # at resolution, so the handler counts and the payload only says to.
        # ``amount`` above stays as it was for a reader written before this
        # spelling existed; the flag is what the handler reads.
        payload["whole_hand"] = True
    if node.player.kind in ("target_player", "target_opponent"):
        _describe_targets(payload, node.player)
        return _with_that_many_draw(node, payload)
    if node.player.kind == "you":
        payload["recipient"] = "caster"
        return _with_that_many_draw(node, payload)
    if node.player.kind == "that_player":
        # "…**that player** puts the cards in their hand on the bottom of their
        # library" (Teferi's Puzzle Box). The seat this firing is about, frozen
        # by the fire site (CR 603.10) — the source's controller is the wrong
        # one on every draw step but their own, and `context.target` under a
        # trigger that chose nothing holds whatever the resolution was already
        # carrying.
        if event in _EVENT_SUBJECT_PLAYERS:
            payload["recipient"] = EVENT_SUBJECT_PLAYER
            return _with_that_many_draw(node, payload)
        # "Target player discards a card unless **they** put a card from their
        # hand on top of their library." (Tainted Specter.) The offer's own
        # payer, which the sentence in front of it already targeted — so the
        # seat is the resolution's chosen player and no second target is
        # described. ``recipient`` says which of the two seats the handler reads
        # rather than leaving it to the key's absence: the same seat
        # ``_offered_seats`` hands the offer to, spelled once on both sides.
        payload["recipient"] = "target"
        return _with_that_many_draw(node, payload)
    raise LoweringError(
        f"no handler puts {node.player.kind!r}'s hand cards on their library",
        node=node,
    )


#: The scratchpad key ``put_hand_cards_on_library`` writes and "then draws that
#: many cards" reads. Declared in ``lowering/_records._PRODUCES`` under the same
#: name; spelled here so the two halves of Teferi's Puzzle Box's one sentence
#: cannot be wired to different keys.
HAND_CARDS_TO_LIBRARY_RESULT = "hand_cards_to_library"


def _with_that_many_draw(
    node: ast.PutHandCardsOnLibrary, payload: dict[str, object],
) -> tuple[OracleInstruction, ...]:
    """The put, and behind it the draw the same sentence asks for.

    "…, **then draws that many cards**" (Teferi's Puzzle Box) counts what the
    put actually moved, which is the only place the number exists: by the time
    the draw runs the hand is empty. The put records it before arming its
    prompt, so the two steps are one ``sequence`` and the draw reads the record
    — ``run_resumable`` is what carries the draw across the prompt, since the
    order the cards land in is a decision the player has not made yet.

    The drawer is the same seat the put named. Read off ``recipient`` rather
    than re-derived, because "that many cards" is drawn by the player who just
    put them back and by nobody else.
    """
    put = OracleInstruction("put_hand_cards_on_library", "", payload)
    if not node.then_draw:
        return (put,)
    draw: dict[str, object] = {"amount_from": HAND_CARDS_TO_LIBRARY_RESULT}
    recipient = payload.get("recipient")
    if recipient == EVENT_SUBJECT_PLAYER:
        draw["drawer_seat_record"] = EVENT_SUBJECT_PLAYER
    elif recipient == "caster":
        draw["recipient"] = "caster"
    else:
        raise LoweringError(
            "no handler draws for the seat this put named", node=node
        )
    return (
        OracleInstruction(
            "sequence", "",
            {"steps": (put, OracleInstruction("draw_target_cards", "", draw))},
        ),
    )


def _lower_discard(node: ast.Discard, event: str | None = None) -> tuple[OracleInstruction, ...]:
    """"Target player discards N cards [at random]."

    Only the targeted form has a handler; "you discard" and "each player
    discards" are different effects, not this one with a flag.

    **Who picks the cards is what separates the two handlers**, so "at random"
    decides which one this lowers to rather than being a rider either could
    carry. ``discard_target_cards`` raises a pending choice and lets the
    discarding player choose (Disrupting Scepter); ``discard_x_target_cards``
    takes them with ``random.sample`` (Mind Twist). Lowering an "at random"
    line onto the first would hand the victim the choice their card denies
    them, and lowering a plain discard onto the second would take it away.

    The random handler is also the *variable* one: it sizes itself from the X
    chosen as the spell was cast (``context.x_value``) and never reads the
    payload, which is why the amount is emitted only for the counted form —
    matching what the legacy rule wrote, and keeping the payload honest about
    what the handler actually consults.
    """
    if node.of_drawn:
        # "…discard one **of them**" points at cards a *previous step* drew, and
        # only the fused draw-then-discard below holds them. Anywhere else the
        # pronoun has no referent, so the restriction would be dropped and the
        # discard would come out of the whole hand — wider than the card says.
        raise LoweringError(
            "'discard one of them' only reads the cards the step before it drew",
            node=node,
        )
    # "Discard your hand" (Chandra, Heart of Fire) — the effect's controller
    # discards every card. Checked before the targeted forms: the subject is
    # the implied "you", which they refuse.
    # "Target player reveals their hand and discards **all nonland cards**."
    # (Amnesia.) Not a count at all: every card answering the phrase goes, so
    # nobody chooses and there is no prompt — which is why it is read before the
    # counted forms rather than as an amount one of them could carry. The filter
    # is gated by the same reader every other card phrase is, so a narrowing the
    # matcher cannot test refuses instead of being dropped into a discard that
    # empties the whole hand.
    if isinstance(node.count, ast.AllOf) and not node.whole_hand:
        if node.player.kind not in ("target_player", "target_opponent"):
            raise LoweringError(
                "no handler discards every matching card from a seat nobody "
                "targeted", node=node,
            )
        if node.at_random:
            raise LoweringError(
                "'all' names every matching card, so nothing is chosen at "
                "random", node=node,
            )
        payload: dict[str, object] = {}
        if node.filter is not None:
            # "…discards all cards **of that color**." (Persecute.) The colour
            # an earlier sentence of this same resolution chose (CR 608.2d),
            # taken off the filter **before** the testability gate and put back
            # as its own key after it: no card matcher holds a resolution, so a
            # gate asking "can every key be answered?" must not be shown one
            # that only the handler can. The same shape `subject_matches`'
            # ``subtype_filter_from`` takes for the identical question one
            # characteristic over.
            described_filter = node.filter
            carried: dict[str, object] = {}
            if described_filter.color_chosen_this_way:
                described_filter = dataclasses.replace(
                    described_filter, color_chosen_this_way=False
                )
                carried["color_filter_from"] = CHOSEN_COLOR_THIS_WAY
            described = chargeable_card_filter(described_filter)
            if described is None:
                raise LoweringError(
                    "no discard can test this narrowing", node=node
                )
            # An empty payload is a phrase that reduced to "all cards", which is
            # the whole hand — right for "discards all cards of that color",
            # where the *colour* is the whole narrowing and rides its own key.
            if described:
                payload["filter"] = described
            elif not carried:
                raise LoweringError(
                    "no discard can test this narrowing", node=node
                )
            payload.update(carried)
        _describe_targets(payload, node.player)
        return (OracleInstruction("discard_all_matching_cards", "", payload),)
    # Only the controller's own discard and the at-random one below carry a
    # narrowing; every other handler arms a prompt that takes the whole hand, so
    # a filter reaching them would be silently dropped.
    if (
        node.filter is not None
        and node.player.kind != "you"
        and not (
            node.at_random
            and node.player.kind in ("target_player", "target_opponent")
        )
    ):
        raise LoweringError(
            f"no {node.player.kind!r} discard handler carries a narrowing", node=node
        )
    if node.whole_hand:
        if node.player.kind == "you":
            return (OracleInstruction("discard_hand", "", {}),)
        # "…, that player discards their hand" (Nicol Bolas). The same effect
        # aimed at the seat the firing event recorded, so it is the same
        # instruction with a `who` — a second kind would be a second copy of
        # emptying a hand. Admitted only under a trigger whose fire site
        # actually froze a damaged player: under any other event the words name
        # a seat nobody recorded, and the discard would silently empty the
        # ability's own controller's hand.
        if node.player.kind == "that_player" and event in _DAMAGED_PLAYER_EVENTS:
            return (
                OracleInstruction("discard_hand", "", {"who": "damaged_player"}),
            )
        # "**Each player** discards their hand, then draws cards equal to the
        # greatest number of cards a player discarded this way." (Windfall.)
        # The same emptying offered to every living seat, so it is the same
        # instruction with a ``who`` rather than a second kind — the reading the
        # branch above already takes for the seat a trigger froze. Nobody
        # chooses which cards, so there is no prompt and no ordering to settle
        # (CR 101.4 orders decisions, and this effect asks for none).
        if node.player.kind == "each_player":
            return (
                OracleInstruction("discard_hand", "", {"who": "each_player"}),
            )
        # "…**target opponent** discards their hand." (Brink of Madness.) The
        # same emptying aimed at a seat the *announcement* chose (CR 601.2c /
        # 603.3d) rather than at one an event froze, so it is the same
        # instruction with a third ``who`` — a second kind would be a second
        # copy of emptying a hand, which is what the two branches above already
        # refuse to be.
        #
        # ``who`` says which seat the handler reads rather than leaving it to
        # the key's absence: an unkeyed payload is the controller's own hand
        # one branch up, and that is the one player this effect must not hit.
        # The ``targets`` description beside it is what raises the picker —
        # ``targeting._from_instruction`` reads it generically, so the trigger
        # announces an opponent (``_choose_trigger_targets``) instead of
        # falling through to the first living one.
        if node.player.kind in ("target_player", "target_opponent"):
            payload: dict[str, object] = {"who": "target"}
            _describe_targets(payload, node.player)
            return (OracleInstruction("discard_hand", "", payload),)
        # "Whenever this creature becomes blocked, **defending player** discards
        # all the cards in their hand, then draws that many cards." (Robber
        # Fly.) CR 506.2's seat, frozen by the combat fire site — the same
        # ``who`` channel the three branches above use, gated on an event that
        # really stamped one, exactly as the counted discard one screen down
        # gates the identical phrase.
        if node.player.kind == "defending_player":
            if event not in _DEFENDING_PLAYER_EVENTS:
                raise LoweringError(
                    '"defending player" names a seat this event did not record',
                    node=node,
                )
            return (
                OracleInstruction(
                    "discard_hand", "", {"who": "defending_player"}
                ),
            )
        raise LoweringError(
            f"no whole-hand discard handler for {node.player.kind!r}", node=node
        )
    # "Each player discards a card." (Liliana, Waker of the Dead.) The handler
    # records which players could not, because the printed rider "Each opponent
    # who can't loses 3 life." reads that answer out of the same resolution.
    if node.player.kind == "each_player":
        if node.at_random or node.filter is not None or node.up_to:
            raise LoweringError(
                "the each-player discard is chosen, unnarrowed and exact",
                node=node,
            )
        # "…discards **a third of the cards in their hand**" (Pox). One number
        # per seat, so it cannot be an amount: it is a count taken over *that*
        # player's hand, and the handler asks the evaluator once per seat
        # through the channel the per-recipient damage already uses.
        per_seat = (
            halved_count_spec(node.count, node)
            if isinstance(node.count, ast.Half) else None
        )
        if per_seat is not None:
            return (
                OracleInstruction(
                    "each_player_discards_a_card", "",
                    {X_FROM_COUNT_PER_RECIPIENT: per_seat},
                ),
            )
        if isinstance(node.count, ast.AnyNumber):
            # "**Each player discards any number of cards**, then draws that
            # many cards." (Flux.) A ceiling with no printed number: the bound
            # is the seat's own hand, which only the resolution knows, so it
            # travels as a flag and the handler sizes each prompt. The same
            # prompt Mind Bomb's "up to three" arms — "any number" and "up to
            # N" are one decision with two ceilings, and the "may" is already
            # inside both (a player may answer with none).
            return (
                OracleInstruction(
                    "each_player_discards_up_to_cards", "",
                    {"actor": node.player.kind, "any_number": True},
                ),
            )
        if not isinstance(node.count, ast.Fixed):
            raise LoweringError("each-player discards have a one-card handler", node=node)
        # A printed 1 keeps the empty payload every card written before the
        # count existed produced, so nothing that worked changes shape.
        payload = {} if node.count.value == 1 else {"amount": node.count.value}
        return (OracleInstruction("each_player_discards_a_card", "", payload),)
    # "You may draw a card. If you do, discard a card." (Jeskai Elder) — the
    # effect's own controller discards, choosing the cards through the same
    # pending choice the targeted form uses. Fixed counts only: the variable
    # form stays with the random handler below, whose contract it is.
    if node.player.kind == "you":
        if isinstance(node.count, ast.AnyNumber) and not node.at_random:
            # "…**discard any number of creature cards**." (Mind Maggots.) A
            # ceiling with no printed number, which is the same sentence the
            # each-player branch above already reads (Flux) pointed at one seat:
            # the bound is what the printed phrase names in the caster's own
            # hand, and only the resolution knows it. So it travels as a flag
            # and ``discard_controller_cards`` sizes the prompt, exactly as that
            # branch leaves the sizing to its handler.
            #
            # "Any number" carries its own "may" — a player may answer with
            # none — so the prompt is armed as a ceiling (``up_to``) rather than
            # as an amount. Read as an amount it would force the whole hand out,
            # which is a strictly larger cost than the card asks for.
            #
            # ``at_random`` is excluded rather than folded in: who picks is what
            # separates this handler from ``discard_x_target_cards``, and
            # nobody chooses a random discard's size either.
            payload: dict[str, object] = {"amount": 0, "any_number": True}
            if node.filter is not None:
                # The same reader the counted branch below uses, and for its
                # reason: a phrase ``_card_matches_filter`` cannot test would be
                # dropped where the prompt applies it, and a dropped narrowing
                # here offers the whole hand to a sentence naming one card type.
                described = chargeable_card_filter(node.filter)
                if not described:
                    raise LoweringError(
                        "no discard prompt can test this narrowing", node=node
                    )
                payload["filter"] = described
            return (
                OracleInstruction("discard_controller_cards", "", payload),
            )
        amount = _amount_payload(node.count)
        # "Discard **X** cards, then …" (Recall). The count may be the cast's X:
        # `discard_controller_cards` sizes its prompt through `resolve_amount`,
        # which reads `"x"` off the context, so the variable form is the same
        # handler with the same payload key rather than a second kind. What
        # stays refused is "at random" — who picks is what separates this
        # handler from `discard_x_target_cards`, and lowering a chosen discard
        # onto the random one takes the choice the card leaves its controller.
        if node.at_random:
            # "{5}, {T}: **Discard a card at random**, then draw two cards."
            # (Ring of Renewal.) Nobody chooses, so it is not this handler at
            # all: `discard_x_target_cards` is the one that samples, and what
            # separates the two is the chooser rather than the seat. Routed to
            # it with the seat named, because that handler reads
            # ``context.target`` by default — which for an activated ability
            # nobody targeted with is the **opponent**, so the ring would have
            # emptied the wrong hand while reporting itself resolved.
            if not isinstance(amount, (int, str)):
                raise LoweringError(
                    "the random controller discard is counted or X", node=node
                )
            random_payload: dict[str, object] = {
                "amount": amount, "who": "caster",
            }
            if node.filter is not None:
                # The same reader the targeted random discard uses one branch
                # down (Rag Man): a phrase the card matcher cannot test would
                # widen the sample to the whole hand, which is the one direction
                # a narrowing must never be dropped in.
                described = chargeable_card_filter(node.filter)
                if not described:
                    raise LoweringError(
                        "no random discard can test this narrowing", node=node
                    )
                random_payload["filter"] = described
            return (
                OracleInstruction("discard_x_target_cards", "", random_payload),
            )
        if not isinstance(amount, (int, str)):
            raise LoweringError(
                "the controller discard is chosen, and counted or X", node=node
            )
        payload: dict[str, object] = {"amount": amount}
        # "Discard a **creature** card" (Crypt Lurker). Gated by the same reader
        # the discard *cost* is (round 87): the prompt and its re-check ask
        # ``_card_matches_filter``, so a phrase reaching past what that can
        # answer would be dropped where it is applied — and a dropped narrowing
        # here is a discard that takes any card at all while the card still
        # reports supported.
        if node.filter is not None:
            described = chargeable_card_filter(node.filter)
            if not described:
                raise LoweringError(
                    "no discard prompt can test this narrowing", node=node
                )
            payload["filter"] = described
        return (OracleInstruction("discard_controller_cards", "", payload),)
    # "Each opponent discards two cards." (Bad Deal.) Chosen discards, one
    # pending choice per opponent — the random and variable forms stay with the
    # targeted handlers below, whose contracts they are.
    if node.player.kind == "each_opponent":
        amount = _amount_payload(node.count)
        if node.at_random or not isinstance(amount, int):
            raise LoweringError(
                "the each-opponent discard is chosen and fixed-count", node=node
            )
        return (
            OracleInstruction("each_opponent_discards_cards", "", {"amount": amount}),
        )
    # "**Defending player** discards a card at random." (Cloak of Confusion.)
    # CR 506.2's seat, frozen into the trigger's context by the combat fire site
    # — so the phrase names a player only under an event that stamped one, the
    # same gate ``control_flow`` puts in front of an offer made to that seat.
    # Under any other event nothing recorded the seat and the discard would
    # empty whichever hand the resolution happened to be carrying.
    if node.player.kind == "defending_player":
        if event not in _DEFENDING_PLAYER_EVENTS:
            raise LoweringError(
                '"defending player" names a seat this event did not record',
                node=node,
            )
        amount = _amount_payload(node.count)
        if node.filter is not None or not isinstance(amount, int):
            raise LoweringError(
                "the defending-player discard is unnarrowed and counted",
                node=node,
            )
        if node.at_random:
            return (
                OracleInstruction(
                    "discard_x_target_cards", "",
                    {"amount": amount, "who": "defending_player"},
                ),
            )
        # "…**defending player discards three cards**." (Mindstab Thrull.) The
        # same seat, chosen rather than sampled — so it is the chosen handler
        # with the same ``who`` key, not the random one with a count. Who picks
        # the cards is what separates the two handlers everywhere else in this
        # function, and reading a chosen discard onto the random one would take
        # the decision away from the player the card leaves it to.
        return (
            OracleInstruction(
                "discard_target_cards", "",
                {"amount": amount, "who": "defending_player"},
            ),
        )
    # "Whenever a green creature dies, **its controller** discards a card."
    # (Bereavement.) The possessive with nothing in front of it: it names the
    # seat that controlled the object the *trigger's own event* was about, which
    # is not the ability's controller and is not a seat anybody targeted. The
    # same gate the sacrifice lowering puts in front of the identical phrase one
    # family over — admitted only under an event whose fire site actually froze
    # a controller, because with no record the discard would empty whichever
    # hand a targetless resolution happens to be carrying, and on this card that
    # is its own controller's every time their own creature dies.
    if node.player.kind == "controller":
        if event not in _EVENT_SUBJECT_CONTROLLERS:
            raise LoweringError(
                f"no event named {event!r} freezes the seat 'its controller' "
                "names",
                node=node,
            )
        amount = _amount_payload(node.count)
        if node.at_random or node.filter is not None or not isinstance(amount, int):
            # The pool prints one shape here — a chosen, unnarrowed, counted
            # discard — and every other shape refuses rather than being folded
            # into it: a narrowing the prompt never applies is a discard that
            # takes any card at all, which is the failure this file refuses on
            # behalf of every seat it does not name.
            raise LoweringError(
                "the frozen-controller discard is chosen, unnarrowed and counted",
                node=node,
            )
        return (
            OracleInstruction(
                "discard_target_cards", "",
                {"amount": amount, "who": EVENT_SUBJECT_CONTROLLER},
            ),
        )
    if node.player.kind not in ("target_player", "target_opponent", "that_player"):
        raise LoweringError(f"no discard handler for {node.player.kind!r}", node=node)
    amount = _amount_payload(node.count)
    # "…, that player discards a card at random" on a damage trigger. The
    # handler discards exactly one, at random, from the player the trigger
    # recorded — so every part of that shape is checked rather than assumed, and
    # a count, a chooser or a trigger other than those makes it fall through to
    # the general forms below and be refused there.
    if (
        node.player.kind == "that_player"
        and node.at_random
        and amount == 1
        and event in _DAMAGED_PLAYER_EVENTS
    ):
        return (OracleInstruction("opponent_discards_random_card_on_damage", "", {}),)
    payload: dict[str, object] = {}
    if amount == "x":
        if not node.at_random:
            raise LoweringError(
                "the only variable-count discard handler discards at random; "
                "a chosen discard of X cards has none",
                node=node,
            )
        kind = "discard_x_target_cards"
    elif node.at_random:
        # "**That player**" names the seat a firing event recorded, and only the
        # damage-trigger shape above knows one was. Under any other event this
        # handler's ``context.target`` is a seat nobody chose, so the discard
        # would empty the wrong hand while the card reported supported — which
        # is why that shape is matched in full rather than folded in below.
        if node.player.kind == "that_player":
            # "At the beginning of each player's upkeep, **that player discards
            # a card at random**." (Bottomless Pit.) The seat the firing event
            # froze (CR 603.10), under the one ``who``/``EVENT_SUBJECT_PLAYER``
            # convention `_lower_exile_random_from_hand` uses above —
            # and gated on the same table, because an event that froze nobody
            # leaves this handler emptying whichever hand the resolution happens
            # to be carrying. On this card that is its own controller's, on
            # three upkeeps in four, silently.
            if event is None and isinstance(amount, int) and node.filter is None:
                # "Target player discards a card at random. **Then that player
                # discards another card at random** …" (Flay.) No trigger froze
                # a seat, so the words point back at the player this effect
                # itself targeted — ``context.target``, the handler's default
                # and the same reading the chosen discard below already gives
                # "that player". No second ``targets`` description: the
                # announcement chose once (CR 601.2c).
                return (
                    OracleInstruction(
                        "discard_x_target_cards", "", {"amount": amount}
                    ),
                )
            if event not in _EVENT_SUBJECT_PLAYERS:
                raise LoweringError(
                    "no event named {!r} freezes the seat 'that player' names"
                    .format(event),
                    node=node,
                )
            random_payload: dict[str, object] = {
                "amount": amount, "who": EVENT_SUBJECT_PLAYER,
            }
            if node.filter is not None:
                described = chargeable_card_filter(node.filter)
                if not described:
                    raise LoweringError(
                        "no random discard can test this narrowing", node=node
                    )
                random_payload["filter"] = described
            if not isinstance(amount, int):
                raise LoweringError(
                    "the frozen-seat random discard is counted", node=node
                )
            return (
                OracleInstruction("discard_x_target_cards", "", random_payload),
            )
        if node.player.kind not in ("target_player", "target_opponent"):
            raise LoweringError(
                "no handler discards at random from a seat nobody targeted",
                node=node,
            )
        # "Target player discards a card at random." (Gwendlyn Di Corci.) The
        # random handler again — the chooser is what picks the handler, and it
        # is nobody here as much as it is for Mind Twist. The count rides in the
        # payload rather than in the kind, so the variable and the printed forms
        # are one handler.
        kind = "discard_x_target_cards"
        payload["amount"] = amount
        # "…discards a **creature** card at random." (Rag Man.) The sample is
        # drawn from the cards answering the phrase rather than from the whole
        # hand — through the same card reader every other narrowing uses, so a
        # phrase it cannot test refuses here instead of widening the sample to
        # every card.
        if node.filter is not None:
            described = chargeable_card_filter(node.filter)
            if not described:
                raise LoweringError(
                    "no random discard can test this narrowing", node=node
                )
            payload["filter"] = described
    else:
        kind = "discard_target_cards"
        payload["amount"] = amount
    _describe_targets(payload, node.player)
    return (OracleInstruction(kind, "", payload),)


def _fused_draw_then_discard(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Draw N cards, then discard M cards." (Bazaar of Baghdad.)

    Kept fused because the decomposition has nowhere to go. ``draw_controller_cards``
    exists, but there is no controller-*discard* handler at all —
    ``discard_target_cards`` makes a chosen player discard — so a
    two-instruction lowering would draw the cards and then either discard
    nothing or empty the wrong player's hand, while the card reported as
    supported. ``draw_then_discard_self`` performs exactly this pair for the
    effect's controller and is already parameterised by both counts, so nothing
    about it is per-card: the legacy rule it replaces reads the two numbers out
    of the sentence the same way.

    That reason is history: ``discard_controller_cards`` arrived later (Recall,
    in :func:`_lower_discard`), so the plain spelling could now be two steps.
    Krovikan Sorcerer's "one **of them**" below still could not.

    Returning None rather than raising leaves a near-miss ("…then discard three
    cards at random") to the ordinary step lowering, which now reads it as two
    steps — the random discard is Ring of Renewal's branch of ``_lower_discard``.
    """
    if len(steps) != 2:
        return None
    draw, discard = steps
    if not (isinstance(draw, ast.Draw) and isinstance(discard, ast.Discard)):
        return None
    if not (_is_you(draw.player) and _is_you(discard.player)) or discard.at_random:
        return None
    if not (isinstance(draw.count, ast.Fixed) and isinstance(discard.count, ast.Fixed)):
        return None
    payload: dict[str, object] = {
        "draw": draw.count.value, "discard": discard.count.value,
    }
    if discard.of_drawn:
        # "Draw two cards, then discard one **of them**." (Krovikan Sorcerer.)
        # The discard is restricted to what this same resolution just drew — an
        # identity, not a characteristic — and this is the only lowering that
        # can carry it, because it is the only one that performs both halves.
        # Dropped instead, the seat could pitch anything in hand, which is a
        # strictly better card than the one printed.
        payload["from_drawn"] = True
    return (OracleInstruction("draw_then_discard_self", "", payload),)


def _fused_discard_then_draw(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Discard up to two cards, then draw that many cards." (Kinetic Augur.)

    The mirror of :func:`_fused_draw_then_discard`, and fused for a *different*
    reason. That one is fused because no controller-discard handler existed;
    this one because **the second number is the answer to the first**. "That
    many" is however many cards the player chose to discard, and the choice is a
    pending prompt — so decomposed, the draw would run while the prompt was
    still owed and draw nothing at all, with the card reporting supported.

    One instruction arms the prompt and records what to do when it is answered.
    That is also why the pair must be exactly this shape: any other second step
    has no reason to wait, and any other count has nothing to read.
    """
    if len(steps) != 2:
        return None
    discard, draw = steps
    if not (isinstance(discard, ast.Discard) and isinstance(draw, ast.Draw)):
        return None
    if not (_is_you(discard.player) and _is_you(draw.player)):
        return None
    if discard.at_random or discard.whole_hand or discard.filter is not None:
        return None
    if not isinstance(discard.count, ast.Fixed) or not isinstance(draw.count, ast.ThatMuch):
        return None
    return (
        OracleInstruction(
            "discard_then_draw_that_many", "",
            {"amount": discard.count.value, "up_to": discard.up_to},
        ),
    )
