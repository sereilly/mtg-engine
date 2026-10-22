"""Lowering the **offer**: `may`, `unless <player> pays`, `one_of`.

Split out of `lower.py` at the thousand-line guard. A family rather than an
arbitrary cut, and the family is named after `engine/handlers/control_flow.py`
— the three lowerings here build the offers that file dispatches (`may`,
`unless_player_pays`, `choose_one`) and not the `sequence`, `if_then` and
`for_each` it dispatches beside them, which is what "effects compose through
these instead of getting a fused instruction kind" looks like on the way in.

It has shed a composer twice since, and the docstring above is what those two
splits were cut along, so it is worth keeping current: `for_each` left as
`lowering/loops` and `sequence` left as `lowering/sequences`, and what is left
here is the offer — who is asked, what it costs, and which of its branches
runs. Naming `sequence` after it had gone made the seam read one clause wide of
where the code actually parted.

**And the table of which kinds are wrappers left at the Phase 0 before
Odyssey, because it was never the offer.** `WRAPPER_KINDS`, the walks that read
into a lowered instruction (`nested_instructions`, `offer_branches`) and
`categories_of` sat at the bottom of this file as "the kinds the four lowerings
above emit" — a sentence written after both splits above, about `sequence`,
`if_then` and `for_each`, when this module built none of them. No lowering here
called that block and it called none of them, so it is in `lower.py` now, which
every wrapper passes through and which reads the table.

`lowering/_collapses` is the floor under this one (Urza's Legacy's Phase 0): the
offers whose action carries its own ceiling, which collapse into the prompt
behind them rather than lowering as an offer at all.

Each lowering here takes `lower_statement` as a **parameter**. An option, an
optional action and a branch are all whole sentences, and reading one is
`lower.py`'s job, so the caller hands its own parser down rather than being
imported back. That is the inversion `lowering/where_x`, `postmodifiers`,
`delayed` and `subject_verb` already make, and the reason is the same each
time: what differs between the callers is only which parser they already hold.
"""

from __future__ import annotations

from ...oracle_types import (EVENT_SPELL_MANA_COST, OracleInstruction,
                             OTHER_THAN_EVENT_SUBJECT_PLAYER,
                             REVEALED_TOP_CARDS_BY_SEAT,
                             STACK_TARGET_CONTROLLER)
from .. import ast
from ..errors import LoweringError
from ._amounts import count_spec
from ._collapses import (offered_seat_performs, without_restated_target,
                         _each_player_optional_discard,
                         _each_player_optional_draw,
                         _each_player_optional_pay_mana,
                         _each_player_optional_tap,
                         _referent_seat_optional_draw)
from ._common import _amount_payload, _is_source, variable_mana_payload
from ._events import (CAST_SPELL_EVENTS, EVENT_SUBJECT_CONTROLLER,
                      EVENT_SUBJECT_PLAYER,
                      _DEFENDING_PLAYER_EVENTS, _EVENT_SUBJECT_CONTROLLERS,
                      _EVENT_SUBJECT_PLAYERS, LOOP_BOUND_OBJECT,
                      frozen_seat_record)
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

    "You may pay {X}, where X is the number of +1/+1 counters on it"
    (Primordial Ooze) is the ordinary optional payment with one number read
    late, not a second prompt.

    The conversion itself is ``_common.variable_mana_payload``, shared with the
    combat tolls that print the same ``{X}``: what a printed symbol run becomes
    does not depend on which clause printed it, and two copies would be two
    answers free to differ.
    """
    return variable_mana_payload(
        node.cost, what="an optional payment", node=node
    )


#: The player references an offer can be made to. Held to what
#: ``handlers/offers._offered_seats`` can actually name: "you" is the
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
     # "**Unless target player pays {3}**, that player loses 5 life …"
     # (Rhystic Syphon.) ``target_opponent``'s branch with the table widened
     # to every seat, the caster included — CR 115.1 lets a spell target its
     # own controller, so nothing is checked but that a seat was chosen.
     "target_player",
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
     "damaged_player",
     # "**The player who reveals the card with the greatest mana value** may
     # change the target or targets." (Psychic Battle.) A seat *described* by
     # a record an earlier step of the same effect wrote — "each player reveals
     # the top card of their library" — so it is admitted only behind that
     # step (see ``_lower_may``), and ``_offered_seats`` names it by the strict
     # maximum: a tie offers to nobody.
     "revealed_greatest_mana_value"}
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
    # "**Any other player** may pay …" (Ice Cave): every seat but the one the
    # firing event froze — admitted only under an event that froze one.
    "any_other_player": OTHER_THAN_EVENT_SUBJECT_PLAYER,
}

#: The events whose fire site records the spell cast (``cast_card``), so "that
#: spell's mana cost" names an object.
_CAST_SPELL_EVENTS = CAST_SPELL_EVENTS


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
    payer = _ENUMERATED_PAYERS.get(node.payer.kind)
    if (
        payer == OTHER_THAN_EVENT_SUBJECT_PLAYER
        and event not in _EVENT_SUBJECT_PLAYERS
    ):
        raise LoweringError(
            "\"any other player\" is measured from a seat this event did not "
            "record", node=node,
        )
    derived_cost = isinstance(node.cost, ast.EventSpellManaCost)
    if derived_cost and (payer is None or event not in _CAST_SPELL_EVENTS):
        # Read off the spell the trigger fired on, by the chain's handler.
        # With none recorded — or one seat, the ``May`` below, which has no
        # reader for it — the words name a cost of nothing, which every board
        # can pay.
        raise LoweringError(
            "\"that spell's mana cost\" is offered to a set of seats under a "
            "cast trigger", node=node,
        )
    if payer is None and node.life:
        # The parser builds a life price only over a set of seats; one seat's
        # is the ``May`` whose *action* is the payment.
        raise LoweringError("a life-priced chain needs a set of payers", node=node)
    if payer is None:
        # "…**unless you pay {R}**, …" (Goblin Flotilla); "**Unless target
        # player pays {3}**, that player loses 5 life …" (Rhystic Syphon). An
        # offer to **one** seat is a ``May`` — the clause on its declined
        # branch, and "if they do" on its accepted one — so it is built as that
        # node and handed to the offer lowering rather than given a payer of
        # its own: ``unless_player_pays`` is a *chain* over a set of seats, and
        # a chain of one is the offer with extra steps. Whether the offer can
        # name the seat at all is ``OFFERABLE_ACTORS``' question, asked there.
        return _lower_may(
            ast.May(
                actor=node.payer, cost=node.cost,
                action=None, otherwise=node.otherwise, then=node.paid,
            ),
            produced, event, event_subject, lower_statement=lower_statement,
        )

    def branch(statement) -> tuple[OracleInstruction, ...]:
        if statement is None:
            return ()
        return lower_statement(
            statement, produced, event=event, event_subject=event_subject,
            whole_effect=False,
        )

    unpaid = branch(node.otherwise)
    # "Draw three cards. Then **if any player pays {2}**, discard three cards."
    # (Rhystic Scrying.) The same chain with the polarity reversed: the
    # payment is what *causes* the effect, so it rides the accepted branch and
    # a table that declines leaves nothing behind.
    paid = branch(node.paid)
    if not (unpaid or paid):
        raise LoweringError("an unpaid clause with no consequence", node=node)
    payload: dict[str, object] = {
        "payer": payer,
        # ``{X}`` stays variable ("…unless any player pays {X}", Soul Strings):
        # the same conversion the single-seat offer uses, so the two cannot
        # disagree about what a printed X costs.
        "cost": (
            # "…that spell's mana cost" (Ice Cave), in the ``cost_from`` slot a
            # derived cost has used since Flash.
            {"cost_from": EVENT_SPELL_MANA_COST} if derived_cost
            else variable_mana_payload(node.cost, what="a toll", node=node)
        ),
    }
    if node.life:
        # "…unless any player pays **5 life**." (Aether Rift.) Beside the
        # (empty) mana cost rather than inside it: the prompt and the payer's
        # CR 119.4 test both read ``life_cost``, a different field from
        # ``cost`` for the reason the offer keeps them apart.
        payload["life"] = node.life
    if unpaid:
        # ``unpaid``, never ``otherwise`` and never ``steps``: the first is the
        # offer's *declined* branch, which every reader that walks a program
        # deliberately skips (a declined branch chooses no targets), and this
        # branch is the one carrying the ability's target. The second name is
        # reserved for a composed effect's nested instructions.
        payload["unpaid"] = unpaid
    if paid:
        payload["paid"] = paid
    return (OracleInstruction("unless_player_pays", "", payload),)


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
_SEAT_SET_ACTORS = frozenset({
    "each_player", "each_opponent", "defending_player",
    # A seat the *reveal* picked rather than one the resolution was holding,
    # which is this set's whole definition: "…may **draw a card**" behind it is
    # the revealer's draw, and "change the target or targets" is the
    # revealer's choice.
    "revealed_greatest_mana_value",
})


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


#: Offered actions that are **a pick out of a hidden zone**, so that taking the
#: offer does not yet mean the action happened: the seat may hold nothing
#: eligible, or decline the pick itself. For these — and only these — "If you
#: do" has to ask the pick's own record rather than the offer's answer.
#: "You may exile a card from your hand. **If you do**, untap this land"
#: (Forsaken City) untapped for a seat that accepted and then exiled nothing,
#: and "You may put a creature card with mana value X from your hand onto the
#: battlefield. **If you do**, return this creature to its owner's hand"
#: (Metathran Aerostat) bounced itself over a hand with no such card.
#:
#: Not every recorded action: "you may search your library … if you do, you
#: skip your draw step" (Elfhame Sanctuary) is true of a search that found
#: nothing, so a found-cards record would be the wrong question there.
_PICKS_BEHIND_AN_OFFER = frozenset({
    "exile_chosen_card_from_hand", "put_chosen_card_from_hand_onto_battlefield",
})


def _if_you_do_gate(action: tuple[OracleInstruction, ...]) -> dict | None:
    """The condition an offer's if-you-do branch waits on, or None when taking
    the offer is the doing — see :data:`_PICKS_BEHIND_AN_OFFER`."""
    if len(action) != 1 or action[0].kind not in _PICKS_BEHIND_AN_OFFER:
        return None
    recorded = sorted(produced_keys(action[0]))
    if len(recorded) != 1:
        return None
    return {"kind": "it_happened", "key": recorded[0]}


#: Instruction kinds that ask the player *performing* them to choose something,
#: and so have to be told which seat that is when an offer is made to somebody
#: other than the effect's controller. Exactly one today: an offer whose action
#: is printed as "A **or** B" (Forbidden Ritual's "unless that player sacrifices
#: a permanent of their choice or discards a card") lowers onto ``choose_one``,
#: and CR 601.2b leaves the pick to the seat taking the offer.
#:
#: A set beside :data:`OFFERED_PROMPT_KINDS` and marked the same way, for that
#: table's stated reason: the wrapper is the only node that knows who was
#: offered, so the wrapper is where the mark belongs. The seat-set actors are
#: excluded by :func:`_performed_by`, not listed here — ``_offer_to_seat``
#: already moves ``context.caster`` onto the offered seat for those, so a second
#: answer would be a second chance to disagree.
PERFORMER_CHOICE_KINDS = frozenset({"choose_one"})


def _counters_a_chosen_spell(statement: "ast.Statement | None") -> bool:
    """Whether *statement* is "counter **target** <spell>" and nothing else —
    the decline branch of an offer whose "its controller" is a spell's.

    Only the chosen form. "Counter **that spell**" under a cast trigger names
    the spell the event was about, whose controller the event tables above
    have already resolved; and a counter with a payment clause of its own is
    the counter flow's offer, not this one.
    """
    return (
        isinstance(statement, ast.CounterSpell)
        and statement == ast.CounterSpell(statement.subject)
        and isinstance(statement.subject, ast.TargetSpec)
        and statement.subject.targeted
        and statement.subject.quantifier == "target"
    )


def _performed_by(step: OracleInstruction, actor: str) -> OracleInstruction:
    """*step* told which seat is performing it — see
    :data:`PERFORMER_CHOICE_KINDS`.

    Only where the offered seat is one the handler cannot already infer.
    ``you`` is the resolution's own controller, which is what every such
    instruction reads by default; the seat-set actors already have
    ``context.caster`` rebound onto the offered seat by
    ``handlers/control_flow._offer_to_seat``. What is left is the reference
    naming a *single other* seat — "that player", "its controller", "target
    opponent" — where the caster is deliberately not moved (a known limit that
    function's docstring records), so the pick would go to the ability's
    controller: the one seat the card has just said is not choosing.
    """
    if step.kind not in PERFORMER_CHOICE_KINDS:
        return step
    if actor == "you" or actor in _SEAT_SET_ACTORS:
        return step
    return OracleInstruction(step.kind, step.value, {**step.payload, "chooser": actor})


def _may_assign_as_unblocked_static(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"You may have this creature assign its combat damage as though it weren't
    blocked." (Lone Wolf; the ability Garruk, Savage Herald's −7 grants.)

    An offer that is **not** made during a resolution. It is a static ability of
    the permanent (CR 604.3), and the decision it offers belongs to CR 510.1's
    turn-based action — so lowering it as an ordinary ``may`` would arm a prompt
    at a moment nothing is resolving, on a creature's static line where no
    handler ever runs, and the card would sit on the battlefield doing nothing.

    The two things that say so are the **subject** and the **absent duration**.
    Outmaneuver prints the same verb at "X target blocked creatures … *this
    turn*", which is a spell choosing somebody else's creatures for a window —
    that lowering is ``lowering/assignment``'s and keeps its mark. This names
    the permanent printing it and names no window at all, which for a permanent
    is "while I am here" and for a mark would be a window nothing ends. That is
    the refusal ``_lower_assigns_combat_damage_as_unblocked`` still makes, and
    still should: what changed is that there is now a record with the right
    lifetime, not that the mark grew one.

    Deliberately narrow, like every recogniser in ``lowering/_collapses``: an
    offer carrying a cost, an if-you-do, an otherwise or a reflexive is a
    sentence this static cannot express, and it keeps the ordinary offer — which
    refuses by name rather than silently dropping the clause.

    Here rather than in ``_collapses`` beside them because it is not one of
    those: those collapse an offer into the *prompt* its own ceiling already
    implies, and this collapses one into a permanent's continuous ability. Same
    shape, different claim.
    """
    if not isinstance(node.action, ast.AssignsCombatDamageAsUnblocked):
        return None
    if node.actor.kind != "you":
        return None
    if node.cost is not None or node.life_cost is not None:
        return None
    if node.then is not None or node.otherwise is not None:
        return None
    if node.reflexive is not None or node.life_alternative is not None:
        return None
    if node.cost_alternatives or node.option_effects:
        return None
    if not _is_source(node.action.subject):
        return None
    if node.action.duration.kind is not None:
        return None
    return (OracleInstruction("may_assign_as_unblocked", "", {}),)


#: The seats a change of targets can be handed to. Closed, and for a reason
#: the generic offer does not have: the handler seats the chooser *itself*, at
#: the moment the change is made, and knows these two — the effect's own
#: controller, and the seat the per-seat reveal put ahead. Every other
#: reference would reach a default and re-aim a spell by the wrong player's
#: choice, so it refuses.
_TARGET_CHANGE_CHOOSERS = frozenset({"you", "revealed_greatest_mana_value"})


def _offered_target_change(
    node: ast.May, action: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"<player> **may** change the target or targets." (Psychic Battle.)

    The offer and the change are **one instruction**, not a ``may`` around one,
    and the reason is when the answer is taken. An ``optional_pay`` is a
    queued prompt: with no interactive seat it is answered by whoever drains
    the queue, which on the headless and AI paths is after the stack has
    emptied (``StackMixin._settle``). For every other offer that is a harmless
    reordering. For this one it is the whole card — the object whose targets
    may be changed is the next thing to resolve, so an answer taken afterwards
    changes the targets of something that has already happened.

    So the handler asks while it resolves: a non-interactive seat's policy is
    read on the spot, and an interactive seat is asked through a prompt that
    suspends this resolution and carries "leave them as they are" as one of its
    answers — which is what *may* means here, with no separate yes/no in front
    of it.

    Deliberately narrow, like every collapse this lowering makes: a cost, an
    if-you-do, an otherwise or a reflexive behind the offer is a sentence the
    one instruction cannot express, and it refuses by name rather than
    dropping the clause.
    """
    if (
        node.cost is not None or node.life_cost is not None
        or node.then is not None or node.otherwise is not None
        or node.reflexive is not None or node.life_alternative is not None
        or node.cost_alternatives or node.option_effects
    ):
        raise LoweringError(
            "an offered change of targets carries no cost and no branch",
            node=node,
        )
    if node.actor.kind not in _TARGET_CHANGE_CHOOSERS:
        raise LoweringError(
            f"no handler seats {node.actor.kind!r} to change another object's targets",
            node=node,
        )
    if len(action) != 1 or action[0].kind != "change_event_object_targets":
        raise LoweringError("an offered change of targets is one instruction", node=node)
    return (
        OracleInstruction(
            action[0].kind, action[0].value,
            {**action[0].payload, "chooser": node.actor.kind, "optional": True},
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
    if node.actor.kind == "any_other_player":
        # "…**any other player** may pay that spell's mana cost. **If a player
        # does**, counter the spell." (Ice Cave.) CR 118.12's offer to a *set*
        # of seats with what paying buys behind it — the ``unless_player_pays``
        # chain with its polarity reversed (Rhystic Scrying): each seat asked in
        # turn (CR 101.4), the first payment ending it. One prompt per seat
        # instead would let two players both pay for one counter. A bare price
        # and its branches only; anything else the chain does not describe.
        if node != ast.May(
            node.actor, cost=node.cost, then=node.then, otherwise=node.otherwise
        ) or node.cost is None:
            raise LoweringError(
                "an offer to any other player is a price and what paying it "
                "buys", node=node,
            )
        return _lower_unless_player_pays(
            ast.UnlessPlayerPays(
                node.actor, node.cost, node.otherwise, paid=node.then
            ),
            produced, event, event_subject, lower_statement=lower_statement,
        )
    # "Target opponent may **draw a card**": the bare imperative's subject is
    # the seat the offer names, not the ability's controller.
    node = offered_seat_performs(node)
    for collapse in (
        _each_player_optional_discard,
        _each_player_optional_pay_mana,
        _each_player_optional_draw,
        _each_player_optional_tap,
        _may_assign_as_unblocked_static,
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
    if (
        node.actor.kind == "revealed_greatest_mana_value"
        and REVEALED_TOP_CARDS_BY_SEAT not in produced
    ):
        # The seat is read off the per-seat reveal record, and with no step in
        # front of this one that wrote it the comparison is over nothing: the
        # offer would be made to nobody on every board, which is an optional
        # effect that silently never happens.
        raise LoweringError(
            "\"the player who reveals the card with the greatest mana value\" "
            "needs an earlier step in which each player revealed one",
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
    if isinstance(node.action, ast.ChangeEventTargets):
        return _offered_target_change(node, action)
    actor = node.actor.kind
    if actor == "that_player" and LOOP_BOUND_OBJECT in produced:
        # "For each creature, its controller sacrifices a permanent of their
        # choice unless **they** pay {1}." (Fade Away.) Inside a loop over
        # objects the pronoun names the seat the *sentence* already named —
        # the iteration's own object's controller — and not a seat the firing
        # event froze. Read before the event tables below because the loop is
        # the pronoun's **innermost** binder, which is the same order the
        # damage recipient one module over takes for the seat loop's marker.
        #
        # It becomes the ``controller`` actor rather than a new one:
        # ``_offered_seats`` resolves that through ``bound_permanent``, whose
        # whole contract is "the innermost binding wins", so the offer goes to
        # a seat this engine already knows how to find.
        actor = "controller"
    elif actor == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
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
    if actor in ("controller", "that_player") and _counters_a_chosen_spell(
        node.otherwise
    ):
        # "Counter target instant or sorcery spell unless **its controller**
        # has Molten Influence deal 4 damage to them." The possessive names
        # the *spell* the sentence chose, and a spell is not a permanent:
        # ``controller`` is read off the control seam through
        # ``bound_permanent``, which finds nothing on the stack, so the offer
        # went to nobody and the counter with it — a card that compiled and
        # did nothing at all. Its own actor, read off the stack object the
        # announcement named (``STACK_TARGET_CONTROLLER``).
        actor = STACK_TARGET_CONTROLLER
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
    elif node.actor.kind == "target_player":
        # The same announcement with no "opponent" in it (Rhystic Syphon).
        payload["targets"] = {"quantifier": "target", "kind": "player"}
    action = without_restated_target(action, payload.get("targets"))
    if node.cost is not None:
        if not isinstance(node.cost, ast.ManaCost):
            raise LoweringError("only mana costs can be offered optionally", node=node)
        # The whole cost, symbol by symbol. It used to be the generic part
        # alone, with a coloured pip refusing the line — not a parser gap but a
        # *payer* one: the prompt collected its cost by counting to a number, so
        # a {B} had nothing to collect it with. `engine/mana_payment.py` is what
        # made the refusal unnecessary.
        payload["cost"] = _may_cost_payload(node)
        if node.cost_per_each is not None:
            # "…unless you pay {1} **for each card in your hand**." The count
            # rides the payload as an ordinary count spec — the same
            # ``count_spec`` shape every computed amount in this engine travels
            # on — and ``handlers/control_flow._offer_to_seat`` multiplies the
            # printed cost by it at resolution, which is when CR 608.2 says the
            # number is taken.
            payload["cost_per"] = count_spec(node.cost_per_each, node)
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
        # Stamped with the **resolved** actor rather than the printed one, and
        # here rather than where the action was lowered, because the branches
        # above are what turn "that player" into the record the fire site froze
        # — a step told the printed word would ask a seat nobody wrote down.
        payload["action"] = tuple(_performed_by(step, actor) for step in action)
    if then:
        payload["then"] = then
        # Beside the branch rather than wrapped round it, so every reader of
        # an offer's accept branch (the handler, the AI's pricing of it) still
        # sees the steps it always saw.
        gate = _if_you_do_gate(action)
        if gate is not None:
            payload["then_if"] = gate
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
