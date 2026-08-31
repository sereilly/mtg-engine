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
from .. import ast
from ..errors import LoweringError
from ._events import _DEFENDING_PLAYER_EVENTS
from .categories import _PRODUCES, primary_produced, produced_keys


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
     # "… unless **its controller** pays life equal to its toughness."
     # (Essence Vortex.) The seat is not one the resolution already carries —
     # it is read off the permanent the sentence targeted — so ``_offered_seats``
     # answers it by asking the control seam rather than by reading
     # ``context.target``, which is the reading the note below warns about.
     "controller"}
)


#: Player references that name *every* opponent rather than one chosen seat.
#: "An opponent" reaches the AST as ``target_opponent`` — the reference reader's
#: spelling for the bare article — and it is not a target here: CR 601.2b's cost
#: announcement chooses nobody, so each opponent is asked in turn until one pays.
_OPPONENT_PAYERS = frozenset({"target_opponent", "each_opponent", "opponent"})


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

    * the payer must be a reference the handler can enumerate seats from. "You"
      is an offer to the ability's own controller, which is a ``May`` and a
      different card; a payer nobody is asked is the effect happening
      unconditionally.
    * the branch must lower to something. A clause bought off with nothing
      behind it is a payment charged for no reason.
    """
    if node.payer.kind not in _OPPONENT_PAYERS:
        raise LoweringError(
            "the only payer this clause can enumerate is an opponent", node=node
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
                "payer": "opponent",
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
    collapsed = _each_player_optional_discard(node)
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
    payload: dict[str, object] = {"actor": node.actor.kind}
    if node.cost is not None:
        if not isinstance(node.cost, ast.ManaCost):
            raise LoweringError("only mana costs can be offered optionally", node=node)
        # The whole cost, symbol by symbol. It used to be the generic part
        # alone, with a coloured pip refusing the line — not a parser gap but a
        # *payer* one: the prompt collected its cost by counting to a number, so
        # a {B} had nothing to collect it with. `engine/mana_payment.py` is what
        # made the refusal unnecessary.
        payload["cost"] = _may_cost_payload(node)
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
    if not (action or then or otherwise or reflexive):
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


#: The branches of a ``may`` whose records are visible to the steps *after* it.
#: The offer's action and its "if you do" consequence are steps of this same
#: resolution, so a later sentence naming what they recorded ("**those cards**"
#: after "you may draw two additional cards. If you do, choose two cards…") is
#: naming something this effect really does write.
#:
#: ``otherwise`` and ``reflexive`` are deliberately absent, for the reasons
#: ``_lower_may`` gives about threading *into* them: the first runs only when
#: the action did not happen, and the second is a separate ability under
#: CR 603.12 with a scratchpad of its own.
_MAY_BRANCHES_VISIBLE_AFTER = ("action", "then")


def _records_produced(instruction: OracleInstruction) -> frozenset[str]:
    """The scratchpad keys *instruction* may write, its own and its offer's.

    An offer records nothing itself, so a step after "you may … If you do,
    choose two cards in your hand" would otherwise see an empty set and refuse
    the back-reference that follows it. What is threaded is only the
    *possibility*: a declined offer writes nothing and the loop after it runs
    over nothing, which is what the card says happens.

    Read through ``_PRODUCES`` at every level rather than a second table, so an
    instruction's record has one declaration however deeply it is nested.
    """
    keys = set(produced_keys(instruction.kind))
    if instruction.kind == "may":
        for branch in _MAY_BRANCHES_VISIBLE_AFTER:
            for nested in instruction.payload.get(branch) or ():
                keys |= _records_produced(nested)
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
) -> tuple[OracleInstruction, ...]:
    """*instructions* with *folded* appended to the offer's "if you do" branch.

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
    then = tuple(offer.payload.get("then") or ()) + folded
    rebuilt = OracleInstruction(offer.kind, offer.value, {**offer.payload, "then": then})
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
        last_produced = None
        offer_index = offer_keys = None
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
            if instruction.kind == "may" and inner:
                offer_index = len(instructions) + position
                offer_keys = inner
        instructions += lowered
    return instructions
