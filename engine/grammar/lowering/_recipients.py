"""Which recipient a damage clause names.

The other half of ``lowering/damage.py``'s one big production. That module
answers **how much** — the count, the payment channel, the record, the printed
number — and this answers **to whom**, which is a chain over one
``ast.Recipient`` and nothing else: a seat the resolution chose, a seat the
firing event froze, a seat an earlier step of the same effect recorded, one
described set, one bound set, one superlative pick.

A **floor**, not a family, and a single-importer one exactly as ``_bites`` and
``_conjuncts`` are: `damage` is the only family that asks the question, and the
module exists because that family crossed the thousand-line guard. The seam is
the one the module's own docstring already drew when the computed amounts left
for ``_amounts`` and the prevention shields for ``prevention`` — what stayed was
"a damage event happening", and a damage event has an amount and a recipient.

``_seats`` beside it answers a *narrower* question for *more* families: which
recipient key a printed player reference becomes, and what narrowing rides on
it, for `game`'s ante and `life`'s life-total set as well as for this chain.
The two are not one module because a floor three families read must not carry
one family's dispatch — this chain refuses on damage riders, damage records and
damage handlers, none of which the other two callers have.
"""

from ...oracle_types import (ATTACHED_PERMANENT_CONTROLLER,
                             LAST_DAMAGER_CONTROLLER, OracleInstruction)
from ...subject_filters import card_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import (_describe_several_targets, _is_source, _is_you,
                      _names_several_targets, _targets_payload,
                      testable_filter_payload)
from ._delays import _BOUND_OBJECT_DELAYED_EVENTS
from ._events import (DAMAGED_PERMANENT_CONTROLLER, EVENT_SUBJECT_CONTROLLER,
                      EVENT_SUBJECT_PLAYER, LOOP_BOUND_PLAYER,
                      _EVENT_SUBJECT_CONTROLLERS, _EVENT_SUBJECT_OBJECTS,
                      _EVENT_SUBJECT_PLAYERS, _RECORDED_PERMANENTS,
                      damage_trigger_names_damaged_end)
from ._seats import _stamp_recipient_control, _stamp_recipient_deed
from ._sweeps import lower_described_set_damage, lower_each_matching_damage


def lower_damage_recipient(
    node: "ast.DealDamage",
    recipient: "ast.Recipient",
    payload: dict,
    amount: int | str,
    back_reference: dict,
    bonus: int,
    event: str | None,
    produced: frozenset[str],
    event_subject: object | None,
) -> tuple[OracleInstruction, ...]:
    """The finished instruction(s) for *node*, once its amount is settled.

    *payload* is the amount half already assembled by the caller; every branch
    below either stamps a recipient key onto it and falls through to the one
    ``deal_damage`` at the foot, or returns an instruction of its own because
    the shape it names is not a single ``deal_damage`` at all.
    """
    # Damage aimed at the source's own controller rather than the spell's
    # target. `deal_damage` reads this the same way `target_gains_life`
    # already reads its "recipient" key.
    if _is_you(recipient):
        payload["recipient"] = "caster"
    elif (
        isinstance(recipient, ast.TargetSpec)
        and recipient.quantifier == "this"
        and _is_source(recipient)
    ):
        # "…and 3 damage to itself" (Psionic Entity). Recorded as a recipient
        # rather than left to the fall-through, for exactly the reason Detonate
        # gave the clause about a player one: this instruction is the second
        # step of a sentence whose first step targeted something, so the
        # resolution context is still carrying that target's permanent index —
        # and a bare `{"amount": 3}` reaches the same handler branch Lightning
        # Bolt does and deals the self-damage to the *other* creature, silently.
        payload["recipient"] = "source"
    elif (
        isinstance(recipient, ast.TargetSpec)
        and recipient.quantifier == "that"
        and not recipient.targeted
    ):
        # "This creature deals 2 damage to **that creature** at end of combat."
        # (Dwarven Sea Clan.) The object the creating ability bound
        # (CR 603.7c), which `create_delayed_trigger` stamps into the trigger's
        # context by id. Admitted only under an event that records one: under
        # any other the words name an object nobody wrote down, and the handler
        # would fall through to whatever the resolution context was carrying.
        # The same gate `destroy_bound_permanent` makes of the same quantifier
        # one family over, refusing with the same sentence.
        if event in _EVENT_SUBJECT_OBJECTS:
            # "…this enchantment deals that much damage to **that creature**"
            # (Mangara's Equity), under an ordinary trigger rather than a
            # delayed one. "That creature" and the bare "it" one branch down
            # name the same object — the thing the condition was about — so
            # they lower to the same recipient and re-check the same narrowing.
            # Two spellings, one reading; the branches differ only in which
            # word the card printed.
            #
            # Read before the delayed-object gate below because the two sets are
            # disjoint by construction: a delayed ability's object was chosen by
            # its *opener*, and an ordinary trigger's is the event's own
            # subject. An event in neither still refuses, which is the point.
            described = testable_filter_payload(
                recipient.filter,
                refusal="the event-subject damage cannot test this restriction",
                node=node,
                require_narrowing=False,
            )
            payload["recipient"] = "event_subject"
            if described:
                payload["filter"] = described
            return (OracleInstruction("deal_damage", "", payload),)
        if event not in _BOUND_OBJECT_DELAYED_EVENTS:
            raise LoweringError(
                "\"that\" names the firing event's object, and this event "
                "records none",
                node=node,
            )
        payload["recipient"] = "bound_permanent"
    elif (
        isinstance(recipient, ast.TargetSpec)
        and recipient.quantifier == "it"
        and not recipient.filter.is_source
    ):
        # "Whenever a creature without flying attacks you, this enchantment
        # deals 1 damage to **it**." (Barbed Foliage.) The pronoun was rebound
        # to the trigger's own subject by
        # ``rebinding.rebind_pronoun_to_event_subject``, so it is neither the
        # source nor a target — nothing was chosen and nothing may be.
        #
        # Gated on the event for the bound-object branch's reason one step up:
        # under a trigger whose fire site froze no object the words name
        # nothing, and the damage would fall through to whatever the resolution
        # context happened to be carrying — which for a targetless trigger is a
        # player's face.
        if event not in _EVENT_SUBJECT_OBJECTS:
            raise LoweringError(
                "\"it\" names the object the event was about, and this event "
                "records none",
                node=node,
            )
        described = testable_filter_payload(
            recipient.filter,
            refusal="the event-subject damage cannot test this restriction",
            node=node,
            require_narrowing=False,
        )
        payload["recipient"] = "event_subject"
        if described:
            payload["filter"] = described
    elif isinstance(recipient, ast.PlayerRef) and recipient.kind == "each_player":
        # "…deals damage … to each player" (Armageddon Clock). Its own recipient
        # rather than a fall-through: the kind used to be listed among the ones
        # the handler reads off the resolution context, which for "each player"
        # is not a seat at all — the damage went to whatever `context.target`
        # happened to hold. No card in the pool printed it until this one, so
        # the hole had never been dealt through.
        payload["recipient"] = "each_player"
        _stamp_recipient_deed(payload, recipient, node)
        _stamp_recipient_control(payload, recipient, node)
    elif isinstance(recipient, ast.PlayerRef) and recipient.kind == "each_opponent":
        # "…deals 2 damage to each opponent" (Storm Caller). The handler loops
        # the caster's living opponents through the same player-damage path a
        # single face takes, so shields and replacements see each event.
        payload["recipient"] = "each_opponent"
        _stamp_recipient_deed(payload, recipient, node)
        _stamp_recipient_control(payload, recipient, node)
    elif isinstance(recipient, ast.PlayerRef) and recipient.kind in (
        # "target opponent" joins the chosen-player forms: the damage handler
        # takes the seat off the resolution context either way, and the
        # opponents_only narrowing rides the target description below.
        "target_player", "target_opponent", "that_player", "controller"
    ):
        # The seat still comes off the context — but the *fact that a seat is
        # what this clause names* is recorded, instead of being inferred from
        # the absence of a permanent index. Detonate is why: "Destroy target
        # artifact … Detonate deals X damage to that artifact's controller" is
        # one sequence, so by the second step the resolution context is carrying
        # the first step's permanent index and the handler read it as the thing
        # to damage. A clause about a player then dealt its damage to a
        # permanent, quietly, and only because nothing had said which it was.
        #
        # "…to target player **or planeswalker**" (Chandra's Magmutt) is exactly
        # the clause that may name either, so it keeps the inference: there the
        # permanent index is the choice rather than a leftover.
        if recipient.kind == "that_player" and LOOP_BOUND_PLAYER in produced:
            # "For each player, this enchantment deals 1 damage to **that
            # player** unless they pay {B} or {3}." (Lim-Dûl's Hex.) The loop
            # rebinds the resolution's target to the seat each iteration is on
            # (`handlers/control_flow.for_each`), so the pronoun reads the
            # target slot — deliberately the same payload spelling a chosen
            # player gets, because the handler's read is the same. First among
            # these branches because the loop is the pronoun's *innermost*
            # binder: inside it the words name the iteration's seat even when
            # the enclosing trigger froze one of its own.
            payload["recipient"] = "target_player"
        elif recipient.kind == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
            # "…deals 1 damage to **that player**" under a trigger whose
            # subject *is* a seat (Underworld Dreams' draw). Nothing chose it
            # and no object stands between the event and the player, so the
            # seat is the one the fire site froze — the same reading
            # `_lower_gain_life` takes of the same words from the same table.
            # Checked before the controller table below because the two answer
            # different questions off the same phrase; they name disjoint
            # events, so the order is documentation rather than precedence.
            payload["recipient"] = EVENT_SUBJECT_PLAYER
        elif recipient.kind == "that_player" and damage_trigger_names_damaged_end(
            event, event_subject
        ):
            # "…deals 3 damage to **that creature's controller**" (Bellowing
            # Fiend). The other end of the same event the branch below reads —
            # see `damage_trigger_names_damaged_end` for why the condition's own
            # spelling of its damager is what decides. Read *first*, because
            # `damage_dealt` is in the table below and would answer with the
            # damager's seat, which on this card is the ability's own
            # controller: the Fiend would burn its own player twice and leave
            # the one whose creature it hit untouched.
            payload["recipient"] = DAMAGED_PERMANENT_CONTROLLER
        elif recipient.kind == "that_player" and event in _EVENT_SUBJECT_CONTROLLERS:
            # "…deals that much damage to **that creature's controller**"
            # (Backfire). "That creature" is the object the trigger's event was
            # about, and nothing chose it — so the seat is the one the fire site
            # froze (CR 603.10), not whatever the resolution context is
            # carrying. The same reading `_lower_lose_life` takes of the same
            # words, from the same table.
            payload["recipient"] = EVENT_SUBJECT_CONTROLLER
        elif (
            recipient.kind == "that_player"
            and ATTACHED_PERMANENT_CONTROLLER in produced
        ):
            # "Destroy enchanted land **and this Aura deals 2 damage to that
            # land's controller**." (Orcish Mine.) The third channel the same
            # printed possessive travels on, and the one where the antecedent is
            # in the *sentence* rather than in the trigger's event: "that land"
            # is the land the step in front of this one destroyed, so the seat
            # is what that step recorded about it (CR 608.2h).
            #
            # Read after the two event tables rather than before them: they name
            # events, this names a producer, and no card in the pool prints both
            # — so the order is documentation rather than precedence. Without
            # this branch the clause fell through to `target_player`, which for
            # a trigger that targets nothing is whatever the resolution context
            # was carrying: Psychic Venom's bug, in a sentence that had already
            # named the player it meant.
            payload["recipient"] = ATTACHED_PERMANENT_CONTROLLER
        elif recipient.kind == "that_player" and event is not None:
            # `_events.py`'s own contract: an event either froze a seat or it
            # did not, and a condition absent from both tables refuses the
            # line rather than guessing. This used to fall through to
            # `target_player` — a *choice* the card never offers, resolved
            # against whatever the resolution context happened to carry — and
            # every card that reached it was right only by a fire-site
            # accident (Ankh of Mishra's hand-built victim instruction, the
            # upkeep registry's own seat). The same sentence the upkeep
            # family's pay-or-else prompt already refuses with, one family
            # over.
            raise LoweringError(
                f"no event named {event!r} freezes the seat \"that player\" "
                "names",
                node=node,
            )
        elif not recipient.or_planeswalker:
            payload["recipient"] = "target_player"
    elif (
        isinstance(recipient, ast.PlayerRef)
        and recipient.kind == "last_damager_controller"
    ):
        # "…deals 4 damage to **the controller of the last red instant or
        # sorcery spell that dealt damage to you this turn**." (Suffocation.)
        # A seat nobody chose and no event froze — the turn's damage ledger is
        # asked for it at resolution — so it is its own recipient rather than a
        # spelling of `target_player`, which for a spell that targets nothing
        # would be whatever the resolution context happened to carry.
        #
        # The noun phrase goes through `card_only_filter`, not the permanent
        # matcher's key set: what it names is a *spell*, and CR 613.1 gives a
        # spell no computed characteristics, so the printed face is the whole
        # of what is testable. A phrase reaching outside it refuses the line
        # rather than being admitted with the narrowing dropped — dropped, this
        # clause deals 4 to whoever last dealt you damage by any means at all,
        # which is a card the printed one is nowhere near.
        described = card_only_filter(
            (recipient.last_damager or ast.ObjectFilter()).to_payload()
        )
        if not described:
            raise LoweringError(
                "the source this names cannot be tested against a card",
                node=node,
            )
        payload["recipient"] = LAST_DAMAGER_CONTROLLER
        payload["last_damager_filter"] = described
    elif (
        isinstance(recipient, ast.PlayerRef)
        and recipient.kind == "chosen_player"
    ):
        # "…deal 1 damage to **the second player**." (Oath of Mages.) The seat
        # an earlier step of this same resolution announced, read out of the
        # scratchpad by the branch ``handlers/damage`` has had since Backdraft
        # — and not off ``context.target``, which under a rebinding offer is
        # the player *taking* the offer rather than the one it points at.
        #
        # Its own recipient rather than a spelling of `target_player`, for that
        # card's stated reason: the seat is a record, and a resolution that
        # chose nobody damages nobody instead of whatever the target slot
        # happened to be carrying.
        payload["recipient"] = "chosen_player"
    elif isinstance(recipient, ast.PlayerRef):
        raise LoweringError(f"unsupported damage recipient {recipient.kind!r}", node=node)
    elif (
        isinstance(recipient, ast.TargetSpec)
        and _names_several_targets(recipient)
    ):
        # "…deals 6 damage to each of **up to two** target creatures and/or
        # planeswalkers." (Volcanic Salvo.) The same damage to each chosen
        # object, so it is one instruction with the several-targets description
        # rather than a second kind — and the description is what tells the
        # picker to collect up to N and the handler to resolve a list.
        #
        # Opted into here rather than admitted by the quantifier check below,
        # which is the safety the ordinary description has: a handler resolving
        # one permanent must never be handed a two-target picker, because the
        # second choice would be collected and dropped.
        several: dict[str, object] = dict(payload)
        _describe_several_targets(several, recipient)
        return (OracleInstruction("deal_damage", "", several),)
    elif isinstance(recipient, ast.TargetSpec) and recipient.quantifier == "those":
        # "Tap X target creatures. Winter Blast deals 2 damage to each of
        # **those creatures with flying**." The recipients are not chosen here
        # at all: they are whatever the sentence in front of this one acted on
        # (CR 611.2c fixed that set when the effect began), narrowed by the
        # printed adjective. So there is no target description and no picker —
        # the handler reads the record and applies the filter.
        if _RECORDED_PERMANENTS.isdisjoint(produced):
            raise LoweringError(
                "\"those creatures\" names objects nothing in this effect "
                "recorded",
                node=node,
            )
        recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
        if len(recorded) != 1:
            raise LoweringError(
                "\"those creatures\" is ambiguous: several earlier steps "
                "recorded objects",
                node=node,
            )
        if back_reference or bonus:
            raise LoweringError(
                "a bound-set damage cannot carry a computed amount", node=node
            )
        described = testable_filter_payload(
            recipient.filter,
            refusal="the bound-set damage cannot test this restriction",
            node=node,
            require_narrowing=False,
        )
        return (
            OracleInstruction(
                "deal_damage_to_recorded_permanents", "",
                {
                    "amount": amount,
                    "permanents_from": recorded[0],
                    "filter": described,
                },
            ),
        )
    elif isinstance(recipient, ast.TargetSpec) and recipient.quantifier == "each":
        # "…deals 2 damage to each creature" (Pyroclasm), "…to each creature
        # you control" (Sorrow's Path), "…to each creature for each Aura
        # attached to that creature" (Baki's Curse). One described set, and one
        # lowering for it — see `lowering/_sweeps.py`, which holds this and the
        # "all" spelling together because they are one printed idiom.
        return lower_each_matching_damage(
            node, recipient, amount, bool(back_reference or bonus)
        )
    elif isinstance(recipient, ast.TargetSpec) and recipient.quantifier not in (
        "any_target", "target", "this"
    ):
        return lower_described_set_damage(
            node, recipient, amount, bool(back_reference or bonus)
        )

    targets = _targets_payload(recipient)
    if targets is not None:
        payload["targets"] = targets
    return (OracleInstruction("deal_damage", "", payload),)
