"""Lowering the control-flow composers: `sequence`, `may`, `one_of`.

Split out of `lower.py` at the thousand-line guard. A family rather than an
arbitrary cut, and the family is named after `engine/handlers/control_flow.py`
— these four produce exactly the instruction kinds that file dispatches, which
is what "effects compose through these instead of getting a fused instruction
kind" looks like on the way in.

Each takes `lower_statement` as a **parameter**. An option, an optional action
and a step are all whole sentences, and reading one is `lower.py`'s job, so the
caller hands its own parser down rather than being imported back. That is the
inversion `lowering/where_x`, `postmodifiers`, `delayed` and `subject_verb`
already make, and the reason is the same each time: what differs between the
callers is only which parser they already hold.
"""

from __future__ import annotations

from ...oracle_types import COUNTERED_SPELL_CONTROLLER, OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import _amount_payload, _filter_payload, _restrictions_beyond
from ._events import (EVENT_SUBJECT_CONTROLLER, EVENT_SUBJECT_PLAYER,
                      _DEFENDING_PLAYER_EVENTS, _EVENT_SUBJECT_CONTROLLERS,
                      _EVENT_SUBJECT_PLAYERS, frozen_seat_record)
from ._records import produced_keys


def _lower_one_of(
    node: ast.OneOf, produced: frozenset[str], event: str | None = None,
    event_subject: object | None = None,
    *,
    lower_statement,
) -> tuple[OracleInstruction, ...]:
    """"A **or** B" — one action, two ways to take it, lowered onto the modal
    handler the printed "Choose one —" already uses.

    The same *question* is being asked (which of these does the controller
    pick?), so it is the same prompt and the same handler; what differs is only
    where the alternatives were printed. Inventing a second mechanism would mean
    two prompts, two defaults and two places for a mode to go unoffered.

    Each option must lower to exactly one instruction: the mode payload carries
    one, and a silently truncated option is a branch the player could choose and
    then not get.
    """
    modes = []
    for index, option in enumerate(node.options):
        lowered = lower_statement(option, produced, event=event, event_subject=event_subject, whole_effect=False)
        if len(lowered) != 1:
            raise LoweringError(
                "an alternative that is not a single instruction has no mode to "
                "put it in",
                node=option,
            )
        label = node.labels[index] if index < len(node.labels) else ""
        modes.append({"label": label, "instruction": lowered[0]})
    return (OracleInstruction("choose_one", "", {"modes": tuple(modes)}),)


def _may_cost_payload(node: ast.May) -> dict[str, object]:
    """The symbol dict an optional payment offers, with ``{X}`` left variable.

    ``{X}`` becomes a **generic** pip whose amount is the string "x", which is
    the one channel every amount in this engine resolves an X through: by the
    time the handler runs, ``_execute_oracle_instruction`` has already turned
    the sentence's where-clause into ``context.x_value``. So "you may pay {X},
    where X is the number of +1/+1 counters on it" (Primordial Ooze) is the
    ordinary optional payment with one number read late, not a second prompt.

    A second X pip refuses: "{X}{X}" would mean twice the count, and this
    carries the amount once. No card in the pool prints it, and guessing which
    reading was meant is exactly what a refusal is for.
    """
    pips = dict(node.cost.pips)
    variable = pips.pop("X", 0)
    if variable > 1:
        raise LoweringError("an optional payment reads one X, not several", node=node)
    if variable and pips.get("generic"):
        # "{X}{2}" — a printed constant beside the variable. Nothing prints it,
        # and folding them together would make the offer a number the card
        # never named.
        raise LoweringError(
            "an optional payment cannot mix X with a printed generic cost",
            node=node,
        )
    payload: dict[str, object] = dict(pips)
    if variable:
        payload["generic"] = "x"
    return payload


#: The player references an offer can be made to. Held to what
#: ``handlers/control_flow._offered_seats`` can actually name: "you" is the
#: ability's controller, the two "each" references are a set of seats,
#: "that player"/"they" is the seat the resolution already recorded, and
#: "defending player" is the seat the *combat* recorded — admitted only under an
#: event that froze it (see ``_DEFENDING_PLAYER_EVENTS``), because a seat nobody
#: recorded is an offer made to nobody. Every other reference — "its
#: controller", "the chosen player" — reaches that function's fallback, which
#: reads the resolution's target and is a different seat entirely.
OFFERABLE_ACTORS: frozenset[str] = frozenset(
    {"you", "each_player", "each_opponent", "that_player", "defending_player",
     # "**Target opponent** may ante the top card of their library." (Amulet of
     # Quoz.) The seat the ability chose, which is exactly what
     # ``context.target`` holds — the same read "that player" beside it gets,
     # arrived at by a different route. Admitted with a branch of its own in
     # ``_offered_seats`` rather than through that function's fallback, because
     # the reference reader spells "**an** opponent" the same way and that
     # phrase chooses nobody: the branch checks the recorded seat is a real
     # opponent and offers to nobody when it is not.
     "target_opponent",
     # "… unless **its controller** pays life equal to its toughness."
     # (Essence Vortex.) The seat is not one the resolution already carries —
     # it is read off the permanent the sentence targeted — so ``_offered_seats``
     # answers it by asking the control seam rather than by reading
     # ``context.target``, which is the reading the note below warns about.
     "controller",
     # "…**its controller** may have it deal damage…" on an Aura (Farrel's
     # Mantle). The same two printed words about a different object: the
     # possessive names the permanent the *trigger's condition* named — the
     # enchanted creature — rather than one the sentence targeted, so the seat
     # is read off the attachment. Its own actor because ``_offered_seats``
     # answers the two by asking different things, and reading one as the other
     # offered Farrel's Mantle's choice to the player being attacked.
     "attached_controller",
     # "…unless **they** pay {2} before that step." (Sabertooth Cobra.) The
     # seat the *damage* froze, which is the seat this delayed ability is
     # about — the same record its own counter placement reads, so the player
     # offered the price and the player who takes the counter for refusing it
     # are one answer rather than two.
     "damaged_player"}
)


#: Player references that name *every* opponent rather than one chosen seat.
#: "An opponent" reaches the AST as ``target_opponent`` — the reference reader's
#: spelling for the bare article — and it is not a target here: CR 601.2b's cost
#: announcement chooses nobody, so each opponent is asked in turn until one pays.
_OPPONENT_PAYERS = frozenset({"target_opponent", "each_opponent", "opponent"})

#: Every payer reference this clause can enumerate, and which seat set the
#: handler asks for it. "**Any player** pays {3}" (Icy Prison) reaches the AST
#: as ``each_player`` — the reference reader's one spelling for that set — and
#: names the whole table, the ability's own controller included: an offer the
#: controller may take is the difference between a prison they can keep and one
#: only an opponent can save. A payload key rather than a second kind, because
#: what differs is which seats are asked and nothing else about the chain.
_ENUMERATED_PAYERS: dict[str, str] = {
    **{kind: "opponent" for kind in _OPPONENT_PAYERS},
    "each_player": "any_player",
}


def _lower_unless_player_pays(
    node: ast.UnlessPlayerPays, produced: frozenset[str],
    event: str | None = None, event_subject: object | None = None,
    *,
    lower_statement,
) -> tuple[OracleInstruction, ...]:
    """"Unless an opponent pays {2}, gain control of target artifact …"
    (Scarwood Bandits.)

    The unpaid branch is an ordinary instruction sequence, exactly as an
    offer's branches are, so any effect can sit behind the payment.

    Two refusals, each a way the sentence could otherwise mean more than it
    says:

    * the payer must be a reference the handler can enumerate seats from — or
      "you", which is an offer to the ability's own controller and is built as
      the ``May`` this refusal always said it was. A payer nobody is asked is
      the effect happening unconditionally.
    * the branch must lower to something. A clause bought off with nothing
      behind it is a payment charged for no reason.
    """
    if node.payer.kind == "you":
        # "…**unless you pay {R}**, …" (Goblin Flotilla). An offer to the
        # ability's own controller is a ``May`` — one seat, the resolution's
        # own, with the clause on the declined branch — which is what the
        # refusal below has said since Scarwood Bandits. Built as that node and
        # handed to the offer lowering rather than given a payer of its own:
        # ``unless_player_pays`` is a *chain* over other seats, and a chain of
        # one asked in the resolution's own seat is the offer with extra steps.
        return _lower_may(
            ast.May(
                actor=node.payer, cost=node.cost,
                action=None, otherwise=node.otherwise,
            ),
            produced, event, event_subject, lower_statement=lower_statement,
        )
    payer = _ENUMERATED_PAYERS.get(node.payer.kind)
    if payer is None:
        raise LoweringError(
            "this clause enumerates an opponent or any player, not "
            f"{node.payer.kind!r}",
            node=node,
        )
    unpaid = lower_statement(
        node.otherwise, produced, event=event, event_subject=event_subject,
        whole_effect=False,
    )
    if not unpaid:
        raise LoweringError("an unpaid clause with no consequence", node=node)
    return (
        OracleInstruction(
            "unless_player_pays", "",
            {
                "payer": payer,
                "cost": {symbol: count for symbol, count in node.cost.pips},
                # ``unpaid``, never ``otherwise`` and never ``steps``: the first
                # is the offer's *declined* branch, which every reader that
                # walks a program deliberately skips (a declined branch chooses
                # no targets), and this branch is the one carrying the ability's
                # target. The second name is reserved for a composed effect's
                # nested instructions.
                "unpaid": unpaid,
            },
        ),
    )


#: The actors whose offered seat is **not** the one the resolution already
#: holds, and so rebind what a back-reference to a player — and a bare
#: imperative — means inside the offer. The two "each" references name a set of
#: seats; "defending player" names one seat that is nonetheless somebody else's
#: (CR 506.2), and "defending player may **draw a card**" is exactly the bare
#: imperative that rule is about: without the rebind the ability's controller
#: draws for the defender's answer. Held to
#: ``handlers/control_flow._EACH_ACTORS`` by
#: ``tests/engine/test_grammar_layering.py``: the lowering decides what "that
#: player" compiles to and the handler decides which seat it resolves against,
#: and the two answering differently is the offer burning the wrong player.
_SEAT_SET_ACTORS = frozenset({"each_player", "each_opponent", "defending_player"})


#: Instruction kinds that arm a prompt of their own and whose *decline* is the
#: answer the surrounding offer already collected. "You may exile a nonland
#: card from your hand" (Ice Cauldron) is one decision printed once; the pick
#: that follows it may still be declined, because the seat is answering the
#: "may". The same instruction printed **bare** — "Exile a card from your hand
#: face down" (Gustha's Scepter) — is mandatory, and its prompt has to refuse a
#: decline or the ability quietly does nothing.
#:
#: A set rather than a default, for the reason ``repeat_offer_round`` marks the
#: step it repeats one module over: the wrapper is the only node that knows the
#: sentence said "may", so the wrapper is where the mark belongs.
OFFERED_PROMPT_KINDS = frozenset({"exile_chosen_card_from_hand"})


def _offered(step: OracleInstruction) -> OracleInstruction:
    """*step* as an **offered** action — see :data:`OFFERED_PROMPT_KINDS`."""
    if step.kind not in OFFERED_PROMPT_KINDS:
        return step
    return OracleInstruction(step.kind, step.value, {**step.payload, "optional": True})


def _lower_may(
    node: ast.May, produced: frozenset[str], event: str | None = None,
    event_subject: object | None = None,
    *,
    lower_statement,
) -> tuple[OracleInstruction, ...]:
    """"You may pay {N}. If you do, …" and "You may <action>".

    This replaces the ``optional_pay`` hook shape, which could only express a
    fixed vocabulary of consequences (gain N life, draw N cards, take N damage)
    and so needed a name-keyed entry per card. Here the consequence is an
    ordinary instruction sequence, so any effect can sit behind an optional
    cost.

    **A spell whose whole effect is optional** was a documented limit here until
    round 32, and ``lower_ability`` refused the shape: the prompt rode
    ``pending_optional_pays``, which only the triggered-ability resolution path
    held open, so a spell — which leaves the stack the instant it resolves —
    queued its effect and never performed it. That is no longer true.
    ``arm_pending_choice`` stamps the stack object the prompt is holding open
    and ``ChoiceSpec.holds_priority`` keeps it there until the last of its
    prompts is answered (CR 608.2, CR 117.3b), so Twiddle asks and then acts.

    **The actor may name a set of seats.** "Each player may …" (Rebirth) is one
    decision per player; the actor is carried as payload and
    ``handlers/control_flow.may`` arms one prompt for each named seat.
    """
    for collapse in (
        _each_player_optional_discard,
        _each_player_optional_draw,
        _each_player_optional_tap,
    ):
        collapsed = collapse(node)
        if collapsed is not None:
            return collapsed
    # The one collapse that needs what came before it: "its controller" names a
    # seat only a previous step recorded, so it is asked with *produced* in hand
    # rather than of the node alone.
    collapsed = _referent_seat_optional_draw(node, produced)
    if collapsed is not None:
        return collapsed
    # **An offer made to a set of seats rebinds what "that player" means.**
    # ``handlers/control_flow._offer_to_seat`` replaces ``context.target`` with
    # the offered seat for exactly these actors, so inside the offer the words
    # name the seat that took it — not the seat the firing event was about.
    # Clearing the event here is what makes the two halves agree: with it in
    # hand, "have this enchantment deal 5 damage to **that player**" (Worms of
    # the Earth) would lower to the frozen upkeep seat and burn whoever's turn
    # it was instead of whoever chose to take the damage.
    #
    # Only the offer's own branches lose it. The event is still the outer one
    # for anything around this node, which is why it is a local rather than a
    # rewrite of the argument.
    inner_event = None if node.actor.kind in _SEAT_SET_ACTORS else event
    action = lower_statement(node.action, produced, event=inner_event, event_subject=event_subject, whole_effect=False) if node.action else ()
    action = tuple(_offered(step) for step in action)
    # "If you do" is the rest of *this* resolution, so it can read what the
    # action just recorded: Niambi's "return another target creature you
    # control…, if you do, you gain life equal to that creature's mana value"
    # is the bounce's own record, read one instruction later. The three other
    # branches deliberately keep the outer set —
    #
    # * ``otherwise`` runs precisely when the action did *not* happen, so its
    #   records do not exist;
    # * ``reflexive`` is a separate ability under CR 603.12, created by the
    #   action and resolving later with a scratchpad of its own;
    # * the offer's own cost records nothing at all.
    #
    # Threading the action's set into any of those would make a back-reference
    # compile where nothing will have written it, and an unwritten quantity
    # reads as zero.
    after_action = produced | {
        key for instruction in action for key in produced_keys(instruction)
    }
    then = lower_statement(node.then, after_action, event=inner_event, event_subject=event_subject, whole_effect=False) if node.then else ()
    otherwise = lower_statement(node.otherwise, produced, event=inner_event, event_subject=event_subject, whole_effect=False) if node.otherwise else ()
    reflexive = (
        lower_statement(node.reflexive, produced, event=inner_event, event_subject=event_subject, whole_effect=False)
        if node.reflexive else ()
    )

    if (
        node.actor.kind == "defending_player"
        and event not in _DEFENDING_PLAYER_EVENTS
    ):
        # The seat is a fact about a combat and is frozen by the fire site;
        # outside those events nothing recorded it, and `_offered_seats` would
        # arm no prompt at all — an optional effect that silently never happens
        # rather than one a player declined.
        raise LoweringError(
            "\"defending player\" names a seat this event did not record",
            node=node,
        )
    if node.actor.kind not in OFFERABLE_ACTORS:
        # Idiom 2, for the seat an offer is made to. ``_offered_seats`` knows
        # four references and reads every other one as ``context.target`` — so
        # "destroy target creature unless **its controller** pays {4}" would
        # have offered the payment to whichever player that resolution happened
        # to carry, and the wrong seat paying is a cost the card never charged.
        # Refused here rather than guessed, which is what leaves the card
        # visibly unsupported naming the clause.
        raise LoweringError(
            f"no offer names {node.actor.kind!r} as its payer", node=node
        )
    actor = node.actor.kind
    if actor == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
        # "…**you may draw a card unless that player pays {4}**" (Mystic
        # Remora). Under an event whose subject *is* a player, "that player" is
        # the seat the fire site froze — the opponent who cast the spell — and
        # not the resolution's target. Left as ``that_player`` the offer reached
        # ``_offered_seats``' fallback, which reads ``context.target``: right in
        # a duel by coincidence, and in a three-seat game the toll was offered
        # to a player who had cast nothing.
        #
        # The same mapping the damage recipient one module over already makes
        # for these five events, applied to the seat an *offer* is made to.
        actor = EVENT_SUBJECT_PLAYER
    elif actor == "that_player" and frozen_seat_record("that_player", event) == "damaged_player":
        # "…unless **they** pay {2} before that step" (Sabertooth Cobra). Under
        # an event that froze the *damaged* player, "they" is that seat and not
        # the resolution's target — a delayed ability created by a damage
        # trigger has no target at all, so left as ``that_player`` the offer
        # reached ``_offered_seats``' fallback and asked ``context.target``,
        # which is None. Read through the one table that already says which
        # record a printed player word names under which event, so the offer
        # and the counter behind it cannot name different seats.
        actor = "damaged_player"
    elif actor == "that_player" and event in _EVENT_SUBJECT_CONTROLLERS:
        # "…unless **the player** puts a -1/-1 counter on a creature they
        # control" (Thelon's Chant, Tourach's Chant). Under an event whose
        # subject is an *object*, "that player" is that object's controller —
        # the seat the fire site froze, exactly as the damage recipient one
        # module over reads it. Left as ``that_player`` the offer would go to
        # ``context.target``, which for a permanent-entering trigger is a seat
        # nothing chose.
        actor = EVENT_SUBJECT_CONTROLLER
    if actor == "controller" and getattr(event_subject, "is_enchanted", False):
        # "its" is the trigger's own subject here, not a target this sentence
        # chose — see ``attached_controller`` in ``OFFERABLE_ACTORS``.
        actor = "attached_controller"
    payload: dict[str, object] = {"actor": actor}
    if node.actor.kind == "target_opponent":
        # "**Target opponent** may ante the top card of their library."
        # (Amulet of Quoz.) The seat being offered is the ability's *target*,
        # chosen as it is activated (CR 601.2c / 602.2b), so it is described
        # here the way every other target is — a ``targets`` payload the picker
        # reads through ``_from_targets_payload``. The actor stays beside it:
        # it is what ``_offered_seats`` asks, and the two answer different
        # questions ("who is offered?" and "what did this choose?").
        #
        # Exactly this kind and no other. The reference reader spells the bare
        # article ``opponent`` and only the printed word "target" reaches
        # ``target_opponent``, which is the distinction it was split to keep —
        # so an offer made to "an opponent" describes no target and none is
        # invented for it.
        payload["targets"] = {
            "quantifier": "target", "kind": "player", "opponents_only": True,
        }
    if node.cost is not None:
        if not isinstance(node.cost, ast.ManaCost):
            raise LoweringError("only mana costs can be offered optionally", node=node)
        # The whole cost, symbol by symbol. It used to be the generic part
        # alone, with a coloured pip refusing the line — not a parser gap but a
        # *payer* one: the prompt collected its cost by counting to a number, so
        # a {B} had nothing to collect it with. `engine/mana_payment.py` is what
        # made the refusal unnecessary.
        payload["cost"] = _may_cost_payload(node)
    if node.cost_alternatives:
        # "…unless they pay {B} **or {3}**" (Lim-Dûl's Hex). CR 118.8's second
        # way to cover the *same* offer, so it rides the one prompt rather than
        # arming a second one — and it needs the first cost beside it, because
        # a list of alternatives with nothing to be alternative *to* is just a
        # cost written oddly.
        if node.cost is None:
            raise LoweringError(
                "an alternative payment needs the cost it is an alternative to",
                node=node,
            )
        payload["cost_alternatives"] = [
            {symbol: count for symbol, count in alternative.pips}
            for alternative in node.cost_alternatives
        ]
    if node.option_effects:
        # "…may pay {1} or {2}. If that player doesn't, … **If that player pays
        # only {1}**, …" (Winter's Chill.) What each way of covering the offer
        # buys, index-aligned with ``[cost] + cost_alternatives`` — so the prompt
        # asks *which* option rather than finding the first the payer can
        # afford, and the payment reports back which one was taken. Empty on
        # every other card that prints alternatives, which is exactly CR 118.8's
        # ordinary use: two ways to buy one consequence.
        if len(node.option_effects) != 1 + len(node.cost_alternatives):
            raise LoweringError(
                "a graded offer needs one outcome slot per printed option",
                node=node,
            )
        payload["option_effects"] = [
            list(
                lower_statement(
                    outcome, produced, event=inner_event,
                    event_subject=event_subject, whole_effect=False,
                )
            ) if outcome is not None else []
            for outcome in node.option_effects
        ]
        if not any(payload["option_effects"]):
            raise LoweringError(
                "a graded offer whose options all buy nothing", node=node
            )
    if node.life_cost is not None:
        # "… unless its controller **pays life equal to its toughness**."
        # (Essence Vortex.) Its own payload key rather than a reading of
        # ``cost``: a cost is a symbol dict everywhere, and life is not a mana
        # symbol — ``_player_can_pay_optional`` already keeps the two apart for
        # Bronze Tablet, and folding them would make an unaffordable mana cost
        # read as a life one.
        #
        # **Both together is the conjunction, not the alternative.** "You may
        # pay {4} **and** 2 life" (Purgatory) is one offer with two prices; the
        # refusal that used to stand here read the pairing as impossible,
        # because the only spelling in the pool was Erosion's "**or** 1 life",
        # which is ``life_alternative`` below. Charged together, an offer the
        # payer can only half cover is one they cannot take at all (CR 601.2h
        # asked of the whole price).
        payload["life_cost"] = _life_cost_payload(node)
        if node.cost is not None and node.life_alternative is not None:
            # Nothing in the pool prints both, and the two contradict: "or 1
            # life" says the life *replaces* the mana and "and 2 life" says it
            # accompanies it, so one prompt could not say which the payer did.
            raise LoweringError(
                "an offer cannot charge life and offer it as an alternative",
                node=node,
            )
    if node.life_alternative is not None:
        # CR 118.8's alternative payment ("…pays {1} **or 1 life**", Erosion).
        # A second reading of the *same* offer, so it rides the one prompt
        # rather than arming a second one — and it needs the mana half beside
        # it, because "or 1 life" alone is a life cost and belongs in the field
        # that already says so.
        if node.cost is None:
            raise LoweringError(
                "an alternative life payment with no cost to be an alternative to",
                node=node,
            )
        payload["life_alternative"] = int(node.life_alternative)
    if action:
        payload["action"] = action
    if then:
        payload["then"] = then
    if otherwise:
        payload["otherwise"] = otherwise
    # CR 603.12: a separate key, never merged into `then`, because the handler
    # has to treat it as a separate ability — it chooses its own targets when the
    # payment creates it, and the ``then`` branch has none of its own to choose.
    if reflexive:
        payload["reflexive"] = reflexive
    if node.looked_at_top is not None:
        # "Look at the top two cards of your library. You may sacrifice this
        # enchantment and pay {2}{G}{G}. …" (Preferred Selection.) What the
        # offered seat has already seen of their own library when the question
        # is put — see ``ast.May.looked_at_top``.
        #
        # A printed number and the offer's own controller, both required rather
        # than coerced: a computed count would be a look whose size the prompt
        # could not name, and any other actor would be one seat shown another
        # seat's hidden zone (CR 400.2).
        seen = _amount_payload(node.looked_at_top)
        if not isinstance(seen, int) or seen <= 0:
            raise LoweringError(
                "a look before an offer reads a printed number of cards",
                node=node,
            )
        if node.actor.kind != "you":
            raise LoweringError(
                "a look before an offer shows the offered seat their own "
                "library, and this offer is made to somebody else",
                node=node,
            )
        payload["looked_at_library_top"] = seen
    if not (action or then or otherwise or reflexive or payload.get("option_effects")):
        raise LoweringError("an optional action with no consequence", node=node)
    return (OracleInstruction("may", "", payload),)


def _life_cost_payload(node: ast.May) -> object:
    """What an offered life cost costs, as a number or as a count spec.

    A printed digit is the number. "life equal to **its** toughness" is a
    characteristic of the object the sentence targeted, and CR 613 makes that
    computed — a creature pumped between the announcement and the offer has a
    different toughness — so it travels as the same ``object_characteristic``
    spec every other resolution-time characteristic reads, and the handler
    evaluates it through the one shared evaluator.
    """
    amount = node.life_cost
    if isinstance(amount, ast.Fixed):
        return int(amount.value)
    if isinstance(amount, ast.CharacteristicOfSubject):
        return {
            "object_characteristic": {
                "characteristic": amount.characteristic,
                "offset": amount.offset,
            }
        }
    raise LoweringError(
        f"no offer charges life measured as {type(amount).__name__}", node=node
    )


#: The actors that name a *set* of seats, spelled here as the lowering sees them.
#: The handler has its own copy of this reading (``handlers/control_flow``'s
#: ``_EACH_ACTORS``) because it is answering a different question — which seats
#: to arm — and the two are checked against each other by the pool rather than
#: by a shared constant this module would have to import upwards.
_EACH_SEAT_ACTORS = frozenset({"each_player", "each_opponent"})


def _each_player_optional_discard(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"Each player may discard **up to** three cards." (Mind Bomb.)

    One prompt per seat rather than an offer per seat, because the offer and the
    ceiling are the same decision: "up to three" already lets a player discard
    none, so the "may" in front of it adds no answer the discard prompt does not
    already have. Collapsing them is what makes the sentence behind it work —
    a discard prompt suspends the resolution until every seat has answered
    (CR 608.2), where an offer does not, and "…damage equal to 3 minus the
    number of cards **they** discarded this way" has to run after the answers
    rather than before them.

    Deliberately narrow. It returns None — leaving the ordinary offer — unless
    the whole sentence is that one shape: an unconditional offer, made to a set
    of seats, of a chosen discard with a printed ceiling and nothing behind it.
    An offer with a cost, an if-you-do or an otherwise is a second decision that
    the discard prompt genuinely cannot carry.
    """
    action = node.action
    if (
        node.cost is not None
        or node.then is not None
        or node.otherwise is not None
        or node.reflexive is not None
        or node.starting_with is not None
        or not isinstance(node.actor, ast.PlayerRef)
        or node.actor.kind not in _EACH_SEAT_ACTORS
        or not isinstance(action, ast.Discard)
        or not isinstance(action.player, ast.PlayerRef)
        or action.player.kind != "you"
        or not action.up_to
        or action.at_random
        or action.whole_hand
        or action.filter is not None
        or not isinstance(action.count, ast.Fixed)
    ):
        return None
    return (
        OracleInstruction(
            "each_player_discards_up_to_cards", "",
            {"actor": node.actor.kind, "amount": action.count.value},
        ),
    )


def _each_player_optional_draw(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"Each player may draw **up to two** cards." (Truce.)

    :func:`_each_player_optional_discard`'s twin one zone over, collapsed for
    that function's two reasons. The offer and the ceiling are one decision —
    "up to two" already lets a player draw none, so the "may" adds no answer the
    prompt does not have — and the sentence *behind* it reads the answers: "For
    each card less than two a player draws this way, that player gains 2 life"
    has to run after every seat has said how many, which an offer does not wait
    for and a suspending prompt does.

    Deliberately narrow, exactly as its two siblings are: an offer with a cost,
    an if-you-do or an otherwise is a second decision the prompt cannot carry,
    and the sentence keeps the ordinary offer.
    """
    action = node.action
    if (
        node.cost is not None
        or node.then is not None
        or node.otherwise is not None
        or node.reflexive is not None
        or node.starting_with is not None
        or not isinstance(node.actor, ast.PlayerRef)
        or node.actor.kind not in _EACH_SEAT_ACTORS
        or not isinstance(action, ast.Draw)
        or not isinstance(action.player, ast.PlayerRef)
        or action.player.kind != "you"
        or not action.up_to
        or not isinstance(action.count, ast.Fixed)
    ):
        return None
    return (
        OracleInstruction(
            "each_player_draws_up_to_cards", "",
            {"actor": node.actor.kind, "amount": action.count.value},
        ),
    )


def _referent_seat_optional_draw(
    node: ast.May, produced: frozenset[str],
) -> tuple[OracleInstruction, ...] | None:
    """"**Its controller** may draw up to two cards …" (Arcane Denial.)

    :func:`_each_player_optional_draw`'s sibling with **one** seat instead of a
    set, and the same collapse for the same two reasons: "up to two" already
    lets the seat draw none, so the offer in front of it adds no answer the
    ``draw_up_to`` prompt does not have, and the prompt suspends the resolution
    (CR 608.2e) where a plain offer does not.

    "Its controller" is the countered spell's, and it is read off the record the
    counter wrote rather than off the board — which is the whole reason this is
    gated on *produced*. CR 108.4 gives a card in a graveyard no controller at
    all, and this sentence is printed inside a delay: by the time it runs, a
    turn has passed and the spell is a card nobody controls. With no counter in
    front of it the words name a seat nothing recorded, so the sentence keeps
    the refusal it has today rather than drawing for whoever happens to be
    ``context.target``.

    Deliberately narrow, exactly as its three siblings are: an offer with a
    cost, an if-you-do or an otherwise is a second decision the prompt cannot
    carry.
    """
    action = node.action
    if (
        node.cost is not None
        or node.then is not None
        or node.otherwise is not None
        or node.reflexive is not None
        or node.starting_with is not None
        or not isinstance(node.actor, ast.PlayerRef)
        or node.actor.kind != "controller"
        or COUNTERED_SPELL_CONTROLLER not in produced
        or not isinstance(action, ast.Draw)
        or not isinstance(action.player, ast.PlayerRef)
        or action.player.kind != "you"
        or not action.up_to
        or not isinstance(action.count, ast.Fixed)
    ):
        return None
    return (
        OracleInstruction(
            "draw_up_to_cards", "",
            {
                "amount": action.count.value,
                "drawer_seat_record": COUNTERED_SPELL_CONTROLLER,
            },
        ),
    )


def _each_player_optional_tap(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"Each player may tap **any number** of untapped white creatures they
    control." (Raiding Party.)

    :func:`_each_player_optional_discard`'s twin one zone over, and the same
    collapse for the same reason: the offer and the ceiling are one decision.
    "Any number" already lets a seat tap none, so the "may" in front of it adds
    no answer the tap prompt does not already have — and collapsing them is what
    makes the sentence behind it work, because the tap prompt suspends the
    resolution until every seat has answered (CR 608.2e) where an offer does
    not. "For each creature tapped this way, that player chooses…" has to run
    after the answers rather than before them.

    Deliberately narrow, exactly as the discard is: an offer with a cost, an
    if-you-do or an otherwise is a second decision the tap prompt genuinely
    cannot carry, and the sentence keeps the ordinary offer.

    Written here rather than in the tapping family because what it recognises is
    a ``May`` — the collapse is about the offer, and the instruction it emits is
    the one the tap handler already reads.
    """
    action = node.action
    if (
        node.cost is not None
        or node.then is not None
        or node.otherwise is not None
        or node.reflexive is not None
        or node.starting_with is not None
        or not isinstance(node.actor, ast.PlayerRef)
        or node.actor.kind not in _EACH_SEAT_ACTORS | {"you"}
        or not isinstance(action, ast.Tap)
        or not isinstance(action.subject, ast.TargetSpec)
    ):
        return None
    spec = action.subject
    if spec.targeted or spec.quantifier != "any_number":
        return None
    # Every narrowing the prompt can actually test, and nothing else. The pick
    # is offered from a list ``subject_matches`` builds, so a key it cannot
    # answer would be a phrase silently dropped — and on a *choice* a dropped
    # narrowing offers permanents the card never named.
    leftovers = _restrictions_beyond(
        spec.filter,
        frozenset({"card_types", "type_match", "subtypes", "colors",
                   "controller", "tapped"}),
    )
    if leftovers:
        raise LoweringError(
            "the any-number tap cannot narrow by: " + ", ".join(leftovers),
            node=node,
        )
    described = _filter_payload(spec.filter)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the any-number tap cannot test this restriction", node=node
        )
    return (
        OracleInstruction(
            "tap_any_number_matching", "",
            {
                "filter": described,
                # ``ObjectFilter.to_payload`` emits ``untapped_only`` for the
                # tri-state's False half, and the prompt reads it there — this
                # is the same fact carried where the *prompt* reads it, which
                # is a second channel the handler already had for Siege
                # Striker. The count is what the card is about, so a dropped
                # "untapped" would offer creatures already tapped and buy their
                # controller two Plains apiece for nothing.
                "untapped_only": spec.filter.tapped is False,
                "who": node.actor.kind,
            },
        ),
    )


# ---------------------------------------------------------------------------
# What a wrapper carries (moved here from `lowering/categories.py` at the
# thousand-line guard)
# ---------------------------------------------------------------------------
#
# `categories_of` walks a lowered sequence and has to look *inside* every
# composer before it can say what a line touches. Which kinds are composers,
# and under which payload keys each keeps its steps, is a fact about this
# family — these are the kinds the four lowerings above emit — so it lives
# here and the category table reads it. Public names rather than the
# underscore-prefixed ones they carried as module-privates: they have a caller
# in another module now, and a leading underscore on a name two modules share
# is a claim that stopped being true.
# Control-flow wrappers take the categories of whatever they wrap, so gating
# "damage" is enough to turn on a sequence of damage instructions without
# inventing a category nobody could reason about.
#
# ``may`` is deliberately NOT in here: it gets its own ungated category above,
# because an offer is not the same switch as the effect behind it. Wrapping it
# with the others would let "optional" be turned off under a family that is on,
# which is a card that performs its offer's consequence without asking.
WRAPPER_KINDS: dict[str, tuple[str, ...]] = {
    "sequence": ("steps",),
    "if_then": ("then", "else"),
    "for_each": ("effect",),
    # A round of offers repeated until nobody takes it (Eureka). A wrapper for
    # the same reason ``for_each`` is: what the round *does* is the act it
    # carries, and the repetition is not an effect of its own.
    "repeat_offer_round": ("action",),
}


def nested_instructions(instruction: OracleInstruction) -> tuple[OracleInstruction, ...] | None:
    """The instructions a wrapper carries, or None if it is not one.

    ``choose_one`` is a wrapper too, and its options are ``{label, instruction}``
    pairs rather than a bare tuple — the modal shape the pending-choice prompt
    reads. Its categories are its options', because that is what the card can
    actually do; giving it a category of its own would say the *choosing* is the
    effect.
    """
    if instruction.kind == "create_delayed_trigger":
        # A delayed ability's effect is one instruction rather than a list, so
        # it cannot ride `WRAPPER_KINDS` above — but it is a wrapper all the
        # same, and an inner effect no category gates must ungate the line that
        # arms it. An entry with no instruction is an ability that would fire
        # into nothing, which is the empty-wrapper refusal below.
        inner = instruction.payload.get("instruction")
        return (inner,) if inner is not None else ()
    if instruction.kind == "arm_draw_replacement":
        # "The next time you would draw a card this turn, instead <effect>."
        # (Mangara's Tome.) A wrapper for ``create_delayed_trigger``'s reason
        # exactly — the effect is one instruction rather than a list, and what
        # the line touches is what the armed effect touches.
        inner = instruction.payload.get("instruction")
        return (inner,) if inner is not None else ()
    if instruction.kind == "choose_one":
        return tuple(
            mode["instruction"] for mode in instruction.payload.get("modes") or ()
        )
    nested_keys = WRAPPER_KINDS.get(instruction.kind)
    if nested_keys is None:
        return None
    nested: tuple[OracleInstruction, ...] = ()
    for key in nested_keys:
        nested += tuple(instruction.payload.get(key) or ())
    return nested


def categories_of(instructions: tuple["OracleInstruction", ...]) -> frozenset[str]:
    """Migration categories covered by a lowered instruction sequence.

    Here rather than in ``categories.py`` because that module is a *registry*
    and this is a walk: every step of it asks :func:`nested_instructions`, which
    lives in this file, and a wrapper whose contents it could not see would
    report the wrapper's own kind as the whole answer. The table is imported
    rather than the walk exported, which is the direction the layering allows.
    """
    from .categories import INSTRUCTION_CATEGORIES

    found: set[str] = set()
    for instruction in instructions:
        nested_keys = nested_instructions(instruction)
        if nested_keys is not None:
            if not nested_keys:
                return frozenset({"__ungated__"})
            inner = categories_of(nested_keys)
            if "__ungated__" in inner:
                return frozenset({"__ungated__"})
            found |= inner
            continue
        category = INSTRUCTION_CATEGORIES.get(instruction.kind)
        if category is None:
            return frozenset({"__ungated__"})
        found.add(category)
    return frozenset(found)
