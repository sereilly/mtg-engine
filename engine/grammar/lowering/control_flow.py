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

from ...oracle_types import OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import _filter_payload, _restrictions_beyond
from ._events import (EVENT_SUBJECT_CONTROLLER, EVENT_SUBJECT_PLAYER,
                      _DEFENDING_PLAYER_EVENTS, _EVENT_SUBJECT_CONTROLLERS,
                      _EVENT_SUBJECT_PLAYERS)
from ._records import _PRODUCES, primary_produced, produced_keys


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
     "attached_controller"}
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


def _lower_for_each_player(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"**For each player,** this enchantment deals 1 damage to that player
    unless they pay {B} or {3}." (Lim-Dûl's Hex.)

    A loop over *seats* rather than over objects. The same ``for_each`` the
    object loops lower onto, with the seat set as the iterator — and the
    handler binds each seat as "that player" while its iteration runs, which is
    what the printed back-reference means and the only way one sentence can
    name a different player each time round.

    Refused for any other player reference: "for each opponent" is a real set
    and lowers here too, but a reference naming *one* seat is not a loop at all
    and would repeat the sentence once against a seat nobody chose.
    """
    if node.iterator.kind not in _LOOPED_SEAT_SETS:
        raise LoweringError(
            f"no loop repeats an effect over the {node.iterator.kind}", node=node
        )
    if not inner:
        raise LoweringError("a per-player loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {"iterator": {"players": node.iterator.kind}, "effect": inner},
        ),
    )


#: The player references that name a *set* of seats a loop can walk. The same
#: two ``handlers/control_flow._offered_seats`` enumerates, and deliberately no
#: more: a reference naming one seat is not a loop.
_LOOPED_SEAT_SETS = frozenset({"each_player", "each_opponent"})


def _lower_for_each_matching(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"**For each attacking creature without flying,** its controller may pay
    {1}." (Tidal Flats.) "**For each attacking red creature,** prevent all
    combat damage that would be dealt by that creature this turn unless its
    controller pays {2}{R}." (Heroism.)

    A loop over what the **board** holds when the ability resolves — the fourth
    kind of iterator beside the recorded sets, the count and the seats, and the
    one the handler has always had a branch for and nothing could reach.

    The filter is the whole iterator payload, which is what the handler matches
    each permanent against; every key in it therefore has to be one
    ``subject_matches`` answers, or the loop would run over a strictly larger
    set than the phrase names — "creature **without flying**" is a layer-6
    question (CR 613.1f), and a loop that dropped it would offer Tidal Flats'
    toll to every attacker including the fliers it is printed to let through.
    """
    described = _filter_payload(node.iterator)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the loop cannot test this restriction", node=node
        )
    if not inner:
        raise LoweringError("a per-object loop with no effect in it", node=node)
    return (
        OracleInstruction("for_each", "", {"iterator": described, "effect": inner}),
    )


def _lower_for_each_life_lost(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    event: str | None,
) -> tuple[OracleInstruction, ...]:
    """"**For each 1 life you lost,** sacrifice a permanent other than this
    enchantment unless you discard a card." (Oath of Lim-Dûl.)

    A loop whose iterator is a *number*, not a set — so the same ``for_each``
    the three "this way" sets lower onto, with the count coming off the firing
    event's frozen context instead of off the resolution scratchpad.

    Three refusals, each a way the sentence could otherwise mean more than it
    says:

    * the event must be one that freezes a life loss. Under any other trigger
      the phrase names a number nobody recorded, and an unwritten quantity
      reads as zero — a loop that runs no times on a card reporting supported.
    * the unit must be the printed 1. "For each **2** life you lost" is half as
      many repetitions, and the handler divides by nothing.
    * the body must lower to something, for ``_lower_for_each_chosen``'s
      reason: an empty loop is a sentence that reports supported and does not
      run.
    """
    if event != "you_lose_life":
        raise LoweringError(
            f"no event named {event!r} records the life this loop counts",
            node=node,
        )
    if node.iterator.per != 1:
        raise LoweringError(
            "this loop repeats once per 1 life lost, not per "
            f"{node.iterator.per}",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-life loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {"iterator": {"repeat_from_trigger": "life_lost"}, "effect": inner},
        ),
    )


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
        key for instruction in action for key in produced_keys(instruction.kind)
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
        if node.cost is not None:
            raise LoweringError(
                "an offer charges mana or life, not both", node=node
            )
        payload["life_cost"] = _life_cost_payload(node)
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


#: The branches of a ``may`` whose records are visible to the steps *after* it.
#: The offer's action and its "if you do" consequence are steps of this same
#: resolution, so a later sentence naming what they recorded ("**those cards**"
#: after "you may draw two additional cards. If you do, choose two cards…") is
#: naming something this effect really does write.
#:
#: ``reflexive`` is deliberately absent, for the reason ``_lower_may`` gives
#: about threading *into* it: it is a separate ability under CR 603.12 with a
#: scratchpad of its own. ``otherwise`` is absent from *this* tuple and has one
#: of its own below, because its records are visible on a different condition.
_MAY_BRANCHES_VISIBLE_AFTER = ("action", "then")

#: The branch whose records are visible only to a step that runs *because the
#: offer was declined*. "Target opponent may ante the top card of their library.
#: **If they don't, you flip a coin.** If you win the flip, that player loses
#: the game." (Amulet of Quoz.) The flip is written by the decline branch, so
#: the sentences reading it are steps of that branch however they were
#: punctuated -- the mirror of the fold below, one branch over, and the reason
#: it is a tuple of its own rather than a third entry above: a step is folded
#: into whichever branch actually writes what it reads, and the two branches
#: never both run.
_MAY_DECLINE_BRANCH = ("otherwise",)


def _records_produced(
    instruction: OracleInstruction,
    branches: tuple[str, ...] = _MAY_BRANCHES_VISIBLE_AFTER,
) -> frozenset[str]:
    """The scratchpad keys *instruction* may write, its own and its offer's.

    An offer records nothing itself, so a step after "you may … If you do,
    choose two cards in your hand" would otherwise see an empty set and refuse
    the back-reference that follows it. What is threaded is only the
    *possibility*: a declined offer writes nothing and the loop after it runs
    over nothing, which is what the card says happens.

    Read through ``_PRODUCES`` at every level rather than a second table, so an
    instruction's record has one declaration however deeply it is nested.

    *branches* is which of an offer's branches to look inside. The caller asks
    twice, once per fold target, because the answer decides which branch a later
    step belongs in.
    """
    keys = set(produced_keys(instruction.kind))
    if instruction.kind == "may":
        for branch in branches:
            for nested in instruction.payload.get(branch) or ():
                keys |= _records_produced(nested, branches)
    return frozenset(keys)


def _references_record(instruction: OracleInstruction, keys: frozenset[str]) -> bool:
    """Whether *instruction*, or anything nested in it, reads one of *keys*.

    A back-reference is a payload entry naming the scratchpad key it reads —
    ``{"produced_by": …}`` for a loop's set, ``{"key": …}`` for an "if you do".
    Both are matched by *value*, not by which key spells them, because what
    matters is that the name of a record turns up somewhere in the payload at
    all; a lowering that names one under a third spelling would be folded here
    too rather than silently missed.
    """

    def walk(value) -> bool:
        if isinstance(value, OracleInstruction):
            return walk(value.payload)
        if isinstance(value, dict):
            return any(
                (isinstance(v, str) and v in keys) or walk(v) for v in value.values()
            )
        if isinstance(value, (tuple, list)):
            return any(walk(item) for item in value)
        return False

    return walk(instruction.payload)


def _fold_into_offer(
    instructions: tuple[OracleInstruction, ...],
    offer_index: int,
    folded: tuple[OracleInstruction, ...],
    branch: str = "then",
) -> tuple[OracleInstruction, ...]:
    """*instructions* with *folded* appended to one of the offer's branches.

    "You may draw two additional cards. If you do, choose two cards in your
    hand drawn this turn. **For each of those cards, …**" (Sylvan Library.) The
    third sentence reads what the second one recorded, and the second one only
    happens if the offer is taken — so it is a step of the offer's consequence
    however it was punctuated. Left as a sibling step it runs *before* the
    offer is answered: an offer to an interactive seat arms a prompt and
    returns, so the sequence would carry on to the loop with nothing chosen and
    then report itself resolved.

    Folding is what keeps the order right without making every optional cost in
    the game suspend the resolution it is part of. The alternative — a
    ``suspends`` flag on the offer's prompt — stops loops that have no such
    dependency at all, which is a change to every "you may" in the pool made on
    the strength of one card.
    """
    offer = instructions[offer_index]
    # *branch* is "then" for a step reading what the offer's action recorded and
    # "otherwise" for one reading what its decline recorded (Amulet of Quoz's
    # coin flip). The same argument either way: the step runs exactly when the
    # branch that writes what it reads runs.
    kept = tuple(offer.payload.get(branch) or ()) + folded
    rebuilt = OracleInstruction(offer.kind, offer.value, {**offer.payload, branch: kept})
    return instructions[:offer_index] + (rebuilt,) + instructions[offer_index + 1:]


def _lower_steps(
    steps: tuple[ast.Statement, ...],
    produced: frozenset[str],
    event: str | None = None,
    event_subject: object | None = None,
    *,
    lower_statement,
) -> tuple[OracleInstruction, ...]:
    """Lower consecutive steps, threading what each one records forward."""
    instructions: tuple[OracleInstruction, ...] = ()
    last_produced: str | None = None
    # The most recent offer whose branches record something, and what they
    # record. A later step reading one of those names is a step of that offer's
    # consequence, whatever the punctuation says.
    offer_index: int | None = None
    offer_keys: frozenset[str] | None = None
    # The same, for the offer's *decline* branch. Tracked apart from the pair
    # above because a step is folded into the branch that writes what it reads.
    decline_keys: frozenset[str] | None = None
    for step in steps:
        # "…**If you do**, …" after an action that was not optional. The branch
        # asks whether the step before it took place, and this is the one place
        # that knows which step that was *and* what it records — so the pairing
        # is made here rather than in a field on the node, where it would be a
        # second copy of ``_PRODUCES`` free to disagree with the first.
        if isinstance(step, ast.Conditional) and isinstance(
            step.condition, (ast.ItHappened, ast.CouldNot)
        ):
            could_not = isinstance(step.condition, ast.CouldNot)
            if last_produced is None:
                raise LoweringError(
                    ("\"if you can't\"" if could_not else '"if you do"')
                    + " after a step that records nothing has no "
                    "condition to test",
                    node=step,
                )
            branch = lower_statement(
                step.then, produced, event=event, event_subject=event_subject, whole_effect=False
            )
            # "**If the player does**, <A>. **If they don't**, <B>."
            # (Takklemaggot.) One record, read twice — the second rider folded
            # itself onto the first's node rather than becoming a step, because
            # by then ``last_produced`` names the choice and nothing else could
            # say what "don't" is the complement of.
            otherwise = lower_statement(
                step.otherwise, produced, event=event,
                event_subject=event_subject, whole_effect=False,
            ) if step.otherwise is not None else ()
            condition: dict[str, object] = {
                "kind": "it_happened", "key": last_produced,
            }
            # "If you **can't**" runs the branch exactly when the record says
            # the step did not happen — one condition kind, negated, so the
            # two riders cannot drift apart in what they read.
            if could_not:
                condition["negated"] = True
            payload: dict[str, object] = {"condition": condition, "then": branch}
            if otherwise:
                payload["else"] = otherwise
            instructions += (OracleInstruction("if_then", "", payload),)
            # Deliberately *not* cleared: a second rider on the same step is the
            # printed pair above, and clearing the record here is what used to
            # make "If they don't" a branch with no condition to test.
            continue
        lowered = lower_statement(step, produced, event=event, event_subject=event_subject, whole_effect=False)
        # A step reading a record only an earlier offer's branch writes belongs
        # *inside* that offer — see ``_fold_into_offer``.
        if offer_index is not None and offer_keys and all(
            _references_record(instruction, offer_keys) for instruction in lowered
        ):
            instructions = _fold_into_offer(instructions, offer_index, lowered)
            last_produced = None
            continue
        # "...If they don't, you flip a coin. If you win the flip, ..." (Amulet
        # of Quoz.) A step reading only what the *decline* branch records
        # belongs inside it, for the reason above exactly: left as a sibling it
        # runs whether or not the offer was taken, and reads a coin flip that
        # never happened.
        if offer_index is not None and decline_keys and all(
            _references_record(instruction, decline_keys) for instruction in lowered
        ):
            instructions = _fold_into_offer(
                instructions, offer_index, lowered, branch="otherwise"
            )
            last_produced = None
            continue
        last_produced = None
        offer_index = offer_keys = decline_keys = None
        for position, instruction in enumerate(lowered):
            # Two different questions, and they take different answers. What is
            # *available* to a back-reference includes what an offer's branches
            # write; what "if you do" tests is this step's own record, because
            # the rider asks whether **this** step happened.
            inner = _records_produced(instruction)
            produced = produced | inner
            result = primary_produced(instruction.kind)
            if result is not None:
                last_produced = result
            declined = _records_produced(instruction, _MAY_DECLINE_BRANCH)
            # The decline branch's records are threaded forward too. What makes
            # that safe is the fold above, which puts a step reading one of them
            # *inside* the branch that writes it.
            produced = produced | declined
            if instruction.kind == "may" and (inner or declined):
                offer_index = len(instructions) + position
                offer_keys = inner
                decline_keys = declined - inner
        instructions += lowered
    return instructions
