"""Lowering cards moving between hand and library: draw, discard, mill, scry.

Includes the two fused draw/discard shapes that genuinely are one effect
rather than a sequence. The other flows this module used to hold have
families of their own: mana production in `mana.py`, the hidden-zone
search/reveal/exile-linkage flows in `library.py`.
"""

from ...oracle_types import (CHOSEN_TARGET_PERMANENTS, PER_OBJECT_SEAT_RECORDS,
                             X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT,
                             OracleInstruction)
from .. import ast
from ..errors import LoweringError
from ._amounts import count_spec, halved_count_spec
from ._common import (
    chargeable_card_filter,
    _amount_payload,
    _describe_targets,
    _filter_payload,
    _is_you,
    _restrictions_beyond,
)
from ._events import (
    _DAMAGED_PLAYER_EVENTS,
    _DEFENDING_PLAYER_EVENTS,
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_PLAYER,
    _back_reference_payload,
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
            described = chargeable_card_filter(node.filter)
            if not described:
                raise LoweringError(
                    "no discard can test this narrowing", node=node
                )
            payload["filter"] = described
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

    Returning None rather than raising leaves a near-miss ("…then discard three
    cards at random") to the ordinary step lowering, which refuses it by name.
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


def _lower_next_draw_replacement(
    node: "ast.NextDrawReplacement", effect: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"The next time you would draw a card this turn, instead <effect>."
    (Mangara's Tome.)

    *effect* is the inner sentence, already lowered by the dispatch — the same
    arrangement ``_lower_create_delayed_trigger`` has, and for its reason: what
    the sentence means does not depend on being wrapped, and lowering it here
    would be a second dispatch. It is lowered under the *line's* own event
    rather than under the replaced draw, which is the difference from a delayed
    ability: nothing in "instead put the top card of the exiled pile into its
    owner's hand" is relative to a draw, where "you gain **that much** life"
    behind a delay is relative to the event the delay names.

    An effect that lowered to nothing refuses, exactly as a delayed ability
    with no effect does: a replacement armed over an empty instruction takes
    the draw away and gives the player nothing back, which is a strictly worse
    card than the one printed.
    """
    if not effect:
        raise LoweringError("this replacement has no effect", node=node)
    # Several sentences behind one "instead" are one replacement's effect
    # (CR 608.2), so they compose the way every other multi-step effect does.
    instruction = (
        effect[0] if len(effect) == 1
        else OracleInstruction("sequence", "", {"steps": list(effect)})
    )
    return (
        OracleInstruction("arm_draw_replacement", "", {"instruction": instruction}),
    )


def _lower_draw(
    node: ast.Draw,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"You draw" and "target player draws" are different handlers, not one
    handler with a recipient flag: ``draw_controller_cards`` draws for the
    effect's controller, ``draw_target_cards`` for the chosen player. Picking by
    the drawer keeps each one's existing contract intact.

    *produced* and *event* are what a back-referenced count needs — "draws **as
    many cards as they discarded this way**" (Forget) — and they are the reason
    this lowering is dispatched from ``lower.py``'s chain rather than from
    ``by_node``'s name-only table.
    """
    # "For each creature exiled this way, **its controller** draws a card."
    # (Martyr's Cry.) A possessive with no target in front of it: whose hand it
    # is, is a fact an earlier step recorded about the loop's object, so it
    # travels as the record's name and the handler resolves it per iteration.
    #
    # Without this the pronoun fell into the branch below and drew for
    # ``context.target`` — a seat this sentence never named — which is the
    # silent widening `PER_OBJECT_SEAT_RECORDS` exists to close.
    if node.up_to:
        # "…may draw **up to** two cards" (Truce). A ceiling is a *decision* —
        # how many, answered by the drawing seat — and only the prompt behind
        # `each_player_draws_up_to_cards` asks one.
        #
        # "**Then each player draws up to seven cards.**" (Diminishing Returns.)
        # The same decision with no "may" printed in front of it, which is not a
        # different card: "up to seven" already lets a seat draw none, so the
        # offer `control_flow._each_player_optional_draw` collapses was never
        # what made the choice — the ceiling was. That collapse reaches this
        # instruction from a `May` node; this reaches it from the bare sentence,
        # and both arrive at one handler so what a seat is asked cannot depend
        # on which spelling the card used.
        if node.player.kind in ("each_player", "each_opponent"):
            return (
                OracleInstruction(
                    "each_player_draws_up_to_cards", "",
                    {"amount": _amount_payload(node.count), "actor": node.player.kind},
                ),
            )
        # "**That player** draws up to three cards." (Fatal Lore, inside the
        # mode an opponent chose.) One seat rather than a set, which is
        # `draw_up_to_cards` — the kind Arcane Denial already uses, reading its
        # drawer off a *record* rather than off `context.target`, and
        # `EVENT_SUBJECT_PLAYER` is that record for every phrase whose seat an
        # announcement froze. So the sentence needs no handler of its own: the
        # ceiling prompt, the seat lookup and the CR 614 draw are all already
        # behind that kind.
        #
        # Gated on the event, exactly as the mill and the damage readings of the
        # same two words are: with nothing frozen, "that player" names whoever
        # the resolution happened to be carrying, which is a choice the card
        # never offers.
        if node.player.kind == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
            return (
                OracleInstruction(
                    "draw_up_to_cards", "",
                    {
                        "amount": _amount_payload(node.count),
                        "drawer_seat_record": EVENT_SUBJECT_PLAYER,
                    },
                ),
            )
        # Every other drawer still refuses: read as an amount they would draw
        # the maximum, and a forced draw is a different card from an offered
        # one — on Truce, the difference is the whole of what the card does.
        raise LoweringError(
            "no draw handler offers a ceiling the drawer chooses under",
            node=node,
        )
    drawer_seat = (
        PER_OBJECT_SEAT_RECORDS["controller"]
        if node.player.kind == "controller" else None
    )
    kind = (
        "draw_controller_cards" if node.player.kind == "you" else "draw_target_cards"
    )
    # "**Each player** draws a card." (Winter Sky.) A *set* of seats, which the
    # bare `draw_target_cards` reading cannot express: the handler draws for
    # `context.target`, one seat, so a card printing "each player" drew for the
    # opponent alone — the right answer for nobody and, in a duel, half the
    # card. The same ``recipient`` key `mill_target_player` already reads for
    # exactly this phrase one zone over, so nothing new is invented: which
    # seats an effect happens to is one convention across the engine.
    looped_seats = (
        node.player.kind
        if node.player.kind in ("each_player", "each_opponent") else None
    )
    halved = (
        halved_count_spec(node.count, node) if isinstance(node.count, ast.Half) else None
    )
    if halved is not None:
        # "…draws cards equal to **half** the number of cards in their library"
        # (Peer into the Abyss). The same spec a plain count travels on, with the
        # division recorded on it — see `halved_count_spec`.
        payload: dict[str, object] = {"amount": "x", X_FROM_COUNT: halved}
    elif isinstance(node.count, ast.ColorsAmong):
        # "Draw a card **for each color among** permanents you control"
        # (Chromatic Orrery). The same spec a plain count travels on, with the
        # aggregate that says colours rather than objects — one evaluator, so
        # the where-clause form of this phrase and the per-each form cannot
        # disagree about what "colour" counts.
        payload: dict[str, object] = {
            "amount": "x",
            X_FROM_COUNT: count_spec(
                node.count.filter, node, aggregate="distinct_colors"
            ),
        }
    elif isinstance(node.count, ast.CountOf):
        # "Draw cards equal to the number of …" (Frantic Inventory). The count
        # is taken at *resolution* (CR 608.2), so it travels as the same
        # ``x_from_count`` spec a where-clause defines and the amount is the
        # string the single dispatch point already resolves. Stamped on this
        # instruction alone rather than over the sentence: the count belongs to
        # this draw, and "draw a card, then draw cards equal to …" has a
        # literal 1 in front of it that must stay one.
        payload: dict[str, object] = {
            "amount": "x", X_FROM_COUNT: count_spec(node.count.filter, node),
        }
    elif isinstance(node.count, ast.ThatMuch):
        # "Target player discards two cards, then draws **as many cards as they
        # discarded this way**." (Forget.) The number is one an earlier step of
        # this same resolution recorded, and where it is read from is decided in
        # the one place that decides it for every back-reference — which refuses
        # outright when no step of this effect produces the key, because the
        # words would otherwise name nothing and draw zero on a card reporting
        # itself supported.
        payload: dict[str, object] = {"amount": 0}
        payload.update(_back_reference_payload(node.count, produced, event))
    else:
        payload = {"amount": _amount_payload(node.count)}
    if drawer_seat is not None:
        payload["drawer_seat"] = drawer_seat
    if looped_seats is not None:
        payload["recipient"] = looped_seats
    _describe_targets(payload, node.player)
    return (OracleInstruction(kind, "", payload),)


def _lower_mill(
    node: ast.Mill, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """"Target player mills N cards." (CR 701.13a, Millstone.)

    The miller travels on the payload under the same ``recipient`` key
    ``deal_damage`` and ``target_loses_life`` already read — one convention for
    "who does this happen to" rather than a second one per effect family.
    Absent still means the chosen target, so no payload in the pool changes
    shape. A recipient the handler cannot name refuses rather than defaulting,
    which is the original reason this function refused everything.
    """
    payload: dict[str, object] = {"amount": _amount_payload(node.count)}
    if node.player.kind == "that_player":
        # "Whenever this creature deals damage to an opponent, **that player**
        # mills a card." (Reef Pirates.) The seat is the one the damage event
        # froze (CR 603.10), read from the trigger's context under the key
        # every damage announcement stamps — the same reading the on-damage
        # discard (Nicol Bolas) and the on-damage poison counter (Pit Scorpion)
        # take of the same two words.
        #
        # Gated on the event rather than admitted outright, because a trigger
        # that offers no choice has nothing in ``context.target`` but whatever
        # the resolution was already carrying: this phrase reads a seat the
        # fire site froze or it refuses, which is the contract `_events.py`
        # states and the one the damage family's own fall-through breaks.
        if event not in _DAMAGED_PLAYER_EVENTS:
            raise LoweringError(
                '"that player" mills only under a trigger whose event froze a '
                "damaged player",
                node=node,
            )
        payload["recipient"] = "damaged_player"
        return (OracleInstruction("mill_target_player", "", payload),)
    if node.player.kind in ("target_player", "target_opponent"):
        # "Target **opponent** mills two cards" (Teferi's Tutelage). The handler
        # already mills ``context.target``, whoever that is; what "opponent"
        # changes is which seats the picker may offer (CR 115.4), and that rides
        # on the targets description `_describe_targets` builds — the same
        # `opponents_only` flag every other opponent-targeted effect carries.
        # Reading it as a plain target player would have let the caster mill
        # themselves.
        _describe_targets(payload, node.player)
        return (OracleInstruction("mill_target_player", "", payload),)
    if node.player.kind == "you":
        payload["recipient"] = "caster"
        return (OracleInstruction("mill_target_player", "", payload),)
    if node.player.kind == "each_opponent":
        payload["recipient"] = "each_opponent"
        return (OracleInstruction("mill_target_player", "", payload),)
    raise LoweringError(
        f"mill_target_player cannot mill {node.player.kind!r}", node=node
    )


def _lower_mill_until(node: ast.MillUntil) -> tuple[OracleInstruction, ...]:
    """"Target opponent mills a card, then repeats this process until a
    creature card or X cards have been put into their graveyard this way,
    whichever comes first." (Helm of Obedience.)

    Its own kind rather than ``mill_target_player`` with two extra keys: that
    handler moves N cards in one go and never looks at them, and a loop is not
    a count. Reading this as one would mill X cards whatever came off the top,
    which is the same card with its whole point removed.

    The miller is a *target* opponent and nothing else. "Whose graveyard" is
    the question the record behind this sentence answers, so a wording naming a
    seat the picker cannot offer refuses rather than defaulting to whoever the
    resolution happened to be carrying.
    """
    if node.player.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"a repeated mill cannot mill {node.player.kind!r}", node=node
        )
    leftover = _restrictions_beyond(
        node.stop_filter, {"card_types", "is_card", "type_match"}
    )
    if leftover:
        raise LoweringError(
            "a repeated mill cannot stop on this restriction: "
            + ", ".join(leftover),
            node=node,
        )
    payload: dict[str, object] = {
        # A card-filter payload rather than a bare list of type words, because
        # what tests it is ``_card_matches_filter`` — the one matcher that can
        # answer of a card in a zone, where the shared permanent matcher asks
        # ``has_type`` of a battlefield object that does not exist here.
        "stop_filter": {"type_filter": list(node.stop_filter.card_types)},
        "limit": _amount_payload(node.limit),
    }
    _describe_targets(payload, node.player)
    return (OracleInstruction("mill_until_matching", "", payload),)


def _lower_put_milled_card_onto_battlefield(
    node: ast.PutMilledCardOntoBattlefield, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """"…put one of them onto the battlefield under your control." (Helm of
    Obedience.)

    The producer is demanded exactly as "that much" life is: "them" names a set
    an earlier step of this same effect recorded, and a sentence with nothing
    in front of it that recorded one is the sentence read wrong. Without the
    check it would compile against an empty list and put nothing onto the
    battlefield, which is a supported card that does nothing.
    """
    if "milled_this_way" not in produced:
        raise LoweringError(
            "'one of them' with no repeated mill in this effect to have named "
            "a set",
            node=node,
        )
    return (
        OracleInstruction(
            "put_milled_card_onto_battlefield", "",
            {"cards_from": "milled_this_way", "under_your_control": True},
        ),
    )


def _lower_scry(node: ast.Scry) -> tuple[OracleInstruction, ...]:
    """"Scry N." (CR 701.22a.)

    One instruction carrying only the count. Deliberately no recipient key: the
    one mill and life loss carry exists because those effects name a victim,
    and scry never does — CR 701.22a is defined over the controller's own
    library, so the handler reads ``context.caster``.
    """
    return (OracleInstruction("scry", "", {"amount": _amount_payload(node.count)}),)


#: The scratchpad key "choose N cards in your hand" writes and "for each of
#: those cards" reads. One name, declared once, so the two halves of the
#: sentence cannot be wired to different keys — the same discipline
#: ``destroyed_this_way_objects`` follows in ``lowering/board.py``.
CHOSEN_HAND_CARDS_RESULT = "chosen_hand_cards"


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


def _lower_for_each_short_of_this_way(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each card less than two a player draws this way,** that player
    gains 2 life." (Truce.)

    :func:`_lower_for_each_life_lost`'s twin, and a *nested* loop where that one
    is flat. The sentence names two things at once — "a player" and, inside it,
    a count — so it lowers to a loop over seats (CR 101.4's turn order) with a
    counted repetition inside it. The seat loop is what binds "that player", and
    the inner count is one number per seat, read out of the record the sentence
    in front of it wrote.

    Two refusals, each a way the words could otherwise mean more than they
    say:

    * a step of this same effect must record the count. "This way" is a
      back-reference, and one with no producer names nothing — here it would
      compute the printed base and hand every player the *maximum* life, which
      is the card upside down (idiom 7).
    * the body must lower to something, for :func:`_lower_for_each_chosen`'s
      reason: an empty loop reports supported and does not run.
    """
    record = node.iterator.record
    if record not in produced:
        raise LoweringError(
            f"nothing in this effect records the {record!r} count this loop is "
            "short of",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-shortfall loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {
                # The seats, in turn order, so "that player" names one of them
                # per iteration — the same binding every multi-seat offer makes.
                "iterator": {"players": "each_player"},
                "effect": (
                    OracleInstruction(
                        "for_each", "",
                        {
                            "iterator": {
                                "repeat_from_record": {
                                    "record": record, "base": node.iterator.base,
                                }
                            },
                            "effect": inner,
                        },
                    ),
                ),
            },
        ),
    )


def _lower_for_each_chosen(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each of those cards,** <effect>." (Sylvan Library.)
    "**For each of those creatures,** <effect>." (Winter's Chill.)

    The sibling of ``_lower_for_each_destroyed``, and refused the same way: a
    back-reference with no earlier step that made a choice names nothing, and
    an empty loop is a sentence that reports supported and does not run.

    Two records, one clause. Which of them answers is the printed noun: a hand
    spelling reads the cards a "choose two cards in your hand" step recorded,
    and a permanent spelling reads the permanents a "choose X target …"
    sentence did. Reading either as the other walks an empty list, which is a
    sentence that reports supported and does nothing — so the noun decides and
    the missing producer refuses.
    """
    named = node.iterator.subject
    if named is not None:
        # Which record "those" names is decided by what an earlier step of this
        # same effect actually wrote, in the order the phrase can mean them: a
        # step that *chose* permanents is the closer referent (Winter's Chill
        # names its own targets), and a sweep that destroyed some is the other
        # ("Destroy all artifacts. … **each of those artifacts** …", Seeds of
        # Innocence).
        #
        # Read off *produced* rather than fixed by the parse, for the reason
        # every back-reference here is: the printed word is the same either way
        # and only the effect around it can say which set exists. Neither
        # recorded refuses, exactly as before — an empty loop is a sentence that
        # reports supported and does not run.
        record = None
        if CHOSEN_TARGET_PERMANENTS in produced:
            record = CHOSEN_TARGET_PERMANENTS
        elif "destroyed_this_way" in produced:
            record = "destroyed_this_way_objects"
        if record is None:
            raise LoweringError(
                "'those <permanents>' with no earlier step in this effect that "
                "chose or destroyed any",
                node=node,
            )
        if not inner:
            raise LoweringError("a per-permanent loop with no effect in it", node=node)
        # The printed noun rides beside the record's name, exactly as it does
        # for a destruction sweep's loop: "for each of those **creatures**"
        # after a sentence that targeted attacking creatures is a restatement,
        # and a restatement checked is a restatement. ``for_each`` applies it
        # with ``permanent_matches_filter``, so a target that stopped answering
        # the phrase drops out of the loop rather than being acted on.
        return (
            OracleInstruction(
                "for_each", "",
                {
                    "iterator": {
                        "produced_by": record,
                        **_filter_payload(named),
                    },
                    "effect": inner,
                },
            ),
        )
    if CHOSEN_HAND_CARDS_RESULT not in produced:
        raise LoweringError(
            "'those cards' with no earlier step in this effect that chose any",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-card loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {"iterator": {"produced_by": CHOSEN_HAND_CARDS_RESULT}, "effect": inner},
        ),
    )


def _lower_put_hand_cards_on_library(
    node: ast.PutHandCardsOnLibrary,
) -> tuple[OracleInstruction, ...]:
    """Brainstorm, Stunted Growth.

    One kind for both printings: the seat is payload, under the same
    ``recipient`` key ``_lower_mill`` reads, so "who does this happen to" has
    one convention rather than one per effect family.

    A seat this cannot name refuses rather than defaulting to the caster —
    putting the *wrong player's* cards back would be a strictly different card,
    and silently so, since both spellings move the same number of cards.
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
        return (OracleInstruction("put_hand_cards_on_library", "", payload),)
    if node.player.kind == "you":
        payload["recipient"] = "caster"
        return (OracleInstruction("put_hand_cards_on_library", "", payload),)
    if node.player.kind == "that_player":
        # "Target player discards a card unless **they** put a card from their
        # hand on top of their library." (Tainted Specter.) The offer's own
        # payer, which the sentence in front of it already targeted — so the
        # seat is the resolution's chosen player and no second target is
        # described. ``recipient`` says which of the two seats the handler reads
        # rather than leaving it to the key's absence: the same seat
        # ``_offered_seats`` hands the offer to, spelled once on both sides.
        payload["recipient"] = "target"
        return (OracleInstruction("put_hand_cards_on_library", "", payload),)
    raise LoweringError(
        f"no handler puts {node.player.kind!r}'s hand cards on their library",
        node=node,
    )
