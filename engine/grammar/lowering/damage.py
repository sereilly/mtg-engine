"""Lowering damage.

Plain damage, the "unless they pay" shape, the halved amount and damage
conjunctions. The CR 615 prevention shields left for `prevention` when this
module reached the thousand-line guard; they shared no helper with anything
here. The **computed** amounts left for `_amounts` the next time it did — a
quantity counted off a board or out of the scratchpad against the sentence that
spends it, and a floor rather than a family because this module reads it.

The **pay-or-consequence** shapes left for `upkeep` the third time it did:
"unless you pay" is a damage event a player is offered the chance not to take,
where everything still here is a damage event happening.

`deal_damage` is the one instruction that records a value other steps can read
(`_PRODUCES` in `_records.py`), which is why "deal damage, then gain that much
life" is two instructions in a sequence rather than a fused kind.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ...subject_filters import (
    TESTABLE_SUBJECT_FILTER_KEYS, card_only_filter, untestable_filter_keys,
)
from ...oracle_types import (ATTACHED_PERMANENT_CONTROLLER,
                             LAST_DAMAGER_CONTROLLER,
                             X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT)
from ._amounts import (
    _LOOPED_PLAYER_RECIPIENTS,
    _lower_board_count_damage,
    _lower_chosen_cast_damage,
    _lower_cost_sacrifice_damage,
    _lower_cost_tap_damage,
    _lower_counted_damage,
)

from ._bites import lower_bite

from ._sweeps import (
    _sweep_kind,
    lower_described_set_damage,
    lower_counted_sweep_damage,
    lower_each_matching_damage,
    refuse_unswept_multiplier,
)
from ._common import (
    _describe_several_targets,
    _names_several_targets,
    _amount_payload,
    _filter_payload,
    _is_source,
    _is_you,
    _targets_payload,
)
from ._events import (
    _chosen_cast_amount,
    _EVENT_SUBJECT_CONTROLLERS,
    _EVENT_SUBJECT_OBJECTS,
    _BOUND_OBJECT_DELAYED_EVENTS,
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_CONTROLLER,
    EVENT_SUBJECT_PLAYER,
    LOOP_BOUND_PLAYER,
    SWEPT_CONTROLLER_SEATS,
    _back_reference_payload,
    _RECORDED_PERMANENTS,
)


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------


def _lower_halved_damage(
    node: ast.DealDamage,
    event: str | None,
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"…deals half X damage, rounded down, to any target, **and half X damage,
    rounded up, to you**." (Banshee; Eternal Flame prints the same half against
    a count.)

    Lowered by lowering the quantity underneath and halving the result, rather
    than as a damage shape of its own. A half is not a different effect — the
    recipient, the riders and the picker are the same ones the whole quantity
    would have produced — and writing it as a shape would mean re-deciding all
    of them beside the arithmetic, which is where the two copies start to
    disagree.

    Which key the rounding rides on is decided by what the quantity turned out
    to be, and both were already there:

    * a **count** halves inside the count evaluator (`spec["half"]`, the channel
      Peer into the Abyss's "half the number of cards in their library" opened),
      so the number is halved once, where it is computed;
    * an announced **X** (CR 601.2b) is not computed at all — it is already
      sitting in the resolution's context — so it halves at the point of use.

    A single `deal_damage` is required rather than assumed. Every other shape
    this module emits (a sweep, a fused Karma-style kind, a two-target bite)
    reaches a handler that has no place to apply a rounding, and a payload key
    those handlers never read would deal the *unhalved* amount on a card
    reporting itself supported.
    """
    assert isinstance(node.amount, ast.Half)
    whole = _lower_damage(
        dataclasses.replace(node, amount=node.amount.of), event, produced
    )
    if len(whole) != 1:
        raise LoweringError("no handler halves this damage amount", node=node)
    payload = dict(whole[0].payload)
    counted = payload.get(X_FROM_COUNT)
    if isinstance(counted, dict):
        # The rounding rides *inside the count*, so it is applied by the count
        # evaluator at the single dispatch point before any handler sees the
        # number — which is why this branch does not care which kind the
        # quantity underneath lowered to. Floodgate's is a sweep
        # (`deal_damage_each_matching`), and it halves exactly as Eternal
        # Flame's single recipient does.
        payload[X_FROM_COUNT] = {**counted, "half": node.amount.rounding}
        return (dataclasses.replace(whole[0], payload=payload),)
    if whole[0].kind != "deal_damage":
        # An announced X halves at the *point of use* instead, on a payload key
        # only `deal_damage` reads — so every other shape would deal the
        # unhalved amount on a card reporting itself supported.
        raise LoweringError("no handler halves this damage amount", node=node)
    payload["amount_half"] = node.amount.rounding
    return (dataclasses.replace(whole[0], payload=payload),)


#: Instruction kinds that *read* the two CR 701.19c / CR 614 riders a damage
#: clause can print ("it can't be regenerated this turn", "if it would die this
#: turn, exile it instead"). One kind, because one handler stamps them —
#: ``handlers/damage.deal_damage``, on the single creature it resolved.
_RIDER_READING_KINDS = frozenset({"deal_damage"})


def _lower_damage(
    node: ast.DealDamage,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """:func:`_lower_damage_shape`, with the printed riders proved to survive.

    Every branch below that is not the plain single-recipient one builds its
    **own** payload dict — a sweep, a narrowed creature sweep, a bound set, a
    fused two-target bite — and each of them silently dropped ``no_regen`` and
    ``exile_if_dies`` on the floor. Nothing raised: the sentence parsed, the
    riders were folded onto the node by the sentence loop, the branch never
    looked at them, and the card compiled *supported* dealing damage that any
    regeneration still answers. Only ``_lower_split_recipients`` had noticed,
    and it guarded itself alone.

    So the check is a **post-condition on the result** rather than a line in
    each branch: a branch added later gets it for free, which is the whole
    difference between this and the four copies it replaces. The argument is
    `_lower_halved_damage`'s, one field over — it already requires its own
    single ``deal_damage`` for exactly this reason, and the rounding it protects
    is no more droppable than the riders are.
    """
    lowered = _lower_damage_shape(node, event, produced)
    riders = (
        ("no_regen", node.riders.no_regen),
        ("exile_if_dies", node.riders.exile_if_dies),
    )
    for key, printed in riders:
        if not printed:
            continue
        # Both halves are checked. The *kind* has to be one that reads the key
        # — a payload it never looks at is the same drop wearing a key — and the
        # key has to actually be there, which is what catches a branch that
        # reaches `deal_damage` by a route that rebuilt the payload.
        if (
            len(lowered) != 1
            or lowered[0].kind not in _RIDER_READING_KINDS
            or not lowered[0].payload.get(key)
        ):
            raise LoweringError(
                f"no damage handler carries the printed {key!r} rider here",
                node=node,
            )
    if node.riders.unpreventable_to_creature and not _lock_survives(lowered):
        raise LoweringError(
            "no damage handler carries the printed can't-be-prevented lock here",
            node=node,
        )
    return lowered


def _lock_survives(lowered: tuple[OracleInstruction, ...]) -> bool:
    """Whether Lava Burst's lock reaches a branch that actually applies it.

    The same post-condition the two riders above get, spelled out separately
    because it is stricter than "the key is present". ``deal_damage`` is one
    handler with a dozen branches, and only the two that damage **one chosen
    creature** hand the flag to the damage event — the sweeps, the divided
    list, the several-targets loop and the player recipients each build their
    own event and would carry the key without reading it. So the shapes refuse
    here rather than compiling supported with a lock nothing arms; a card that
    prints one of them is a card this needs widening for, and it will say so.
    """
    if len(lowered) != 1 or lowered[0].kind != "deal_damage":
        return False
    payload = lowered[0].payload
    if not payload.get("unpreventable_to_creature"):
        return False
    # A named recipient is a player, the source, or a per-seat sweep — none of
    # them the single chosen creature the flag is threaded to.
    if payload.get("recipient") is not None:
        return False
    targets = payload.get("targets") or {}
    if targets.get("kind") == "divided":
        return False
    count = targets.get("count")
    return not (isinstance(count, int) and count > 1)


def _lower_damage_shape(
    node: ast.DealDamage,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    # "…for each Aura attached to that creature" (Baki's Curse). Read before
    # every branch below rather than inside the one that honours it: a
    # multiplier is a rider on the printed amount, and the twenty branches that
    # do not know about it would each *drop* it — a flat 2 to the whole board,
    # supported and wrong. `_sweeps` owns both the refusal and the reading, so
    # the two cannot come apart.
    refuse_unswept_multiplier(node)
    # "…equal to half the damage dealt by one of those sorcery spells this
    # turn" (Backdraft). Read first: the amount carries a *decision*, and every
    # branch below assumes a quantity computable where it stands.
    chosen = _chosen_cast_amount(node.amount)
    if chosen is not None:
        return _lower_chosen_cast_damage(node, chosen, produced)
    # "…deals **half X damage, rounded up**, to you." (Banshee, Eternal Flame.)
    # Read before every branch below, because a half is a half *of* one of them:
    # the halving is the last arithmetic step and the recipient, the riders and
    # the picker are whatever the quantity underneath already lowers to.
    if isinstance(node.amount, ast.Half):
        return _lower_halved_damage(node, event, produced)
    if isinstance(node.amount, ast.CountOf):
        # "…deals damage to **each nonblue creature without flying** equal to
        # half the number of Islands you control" (Floodgate). A described set
        # (CR 611.2c) rather than a chosen recipient, so it goes to the sweep
        # family — `_lower_counted_damage` builds one `deal_damage` and has no
        # branch for a set nobody picks.
        if (
            len(node.recipients) == 1
            and isinstance(node.recipients[0], ast.TargetSpec)
            and node.recipients[0].quantifier in ("each", "all")
            and not node.recipients[0].targeted
        ):
            return lower_counted_sweep_damage(node, node.recipients[0])
        return _lower_counted_damage(node, event)
    # "…equal to the sacrificed creature's power" (Freyalise Supplicant, under
    # the half above). A characteristic of what the cost ate rather than a count
    # of anything on a board, so it sits beside the count rather than inside it.
    if isinstance(node.amount, ast.SacrificedForCost):
        return _lower_cost_sacrifice_damage(node)
    # "…equal to **the tapped creature's power**" (Unerring Sling) — the same
    # shape one payment over, and beside it for that branch's reason: a
    # characteristic of what the cost acted on rather than a count of anything
    # on a board.
    if isinstance(node.amount, ast.TappedForCost):
        return _lower_cost_tap_damage(node)
    if isinstance(node.amount, ast.BoardCount):
        return _lower_board_count_damage(node, produced)
    # A **bite**: one named object deals damage equal to its own power, and
    # is itself the source of that damage (`_bites`). Probed before the
    # quantity branches below because the amount is a *read* rather than a
    # number — and after the counted ones above, which a bite never is.
    bite = lower_bite(node, produced)
    if bite is not None:
        return bite

    # "…it deals **that much** damage to target opponent." (Brash Taunter.) The
    # number is the firing event's, not this effect's, so it arrives as a
    # trigger-context key rather than as an amount — the same two channels
    # `_back_reference_payload` decides between everywhere else.
    # "…deals **X plus 3** damage" (Hellfire): the printed constant beside the
    # quantity. Zero for every other shape, and declared here rather than in the
    # branch that can carry one so the payload below never reads it unset.
    bonus = 0
    if isinstance(node.amount, ast.ThatMuch):
        back_reference = _back_reference_payload(node.amount, produced, event)
        amount: int | str = 0
    elif isinstance(node.amount, ast.CountOfDeathsThisWay):
        # "…deals damage … equal to the number of Mountains **put into a
        # graveyard this way**" (Volcanic Eruption). One earlier step's result,
        # not a count of any zone, so it reads the record the destroy branches
        # write — the same `amount_from` channel every scratchpad-read amount
        # travels, and the same producer discipline: with nothing recorded in
        # front of it the words name nothing, and a zero is a number the card
        # never printed.
        if "destroyed_this_way" not in produced:
            raise LoweringError(
                "back-reference to 'destroyed_this_way' with no producer in "
                "this effect",
                node=node,
            )
        # Only the bare noun is admitted — the printed restatement of what the
        # step in front destroyed. The record is a *number*, so a narrowing
        # beyond the noun ("black creatures put into a graveyard this way") is
        # a question nothing can re-ask; it refuses rather than counting as
        # though the narrowing were not there (`lower_where_x`'s rule for the
        # identical node, one printed position over).
        described = node.amount.filter.to_payload()
        if (
            set(described) - {"type_filter", "subtype_filter"}
            or node.amount.filter.zone != "battlefield"
        ):
            raise LoweringError(
                "'put into a graveyard this way' counts what the earlier step "
                "destroyed and cannot be narrowed further",
                node=node,
            )
        if node.amount.per_controller:
            # "…deals damage to each player equal to the number of artifacts
            # **they controlled** that were put into a graveyard this way."
            # (Builder's Bane.) The same record, read one seat at a time: the
            # count is each player's own share of what the destroy in front of
            # this one took, never the whole of it. Dropped, the possessive
            # would deal every player the *total* — five artifacts destroyed
            # and both seats take five — which is a card that reports supported
            # and hits twice as hard as it prints.
            #
            # It travels the per-recipient channel every other one-number-per-
            # seat clause travels, with the record named rather than a board
            # described: by the time this runs the artifacts are cards in a
            # graveyard (CR 400.7), so the only thing that can say whose each
            # was is the seat map the destroy step froze (CR 608.2h).
            if not isinstance(node.recipients, tuple) or len(node.recipients) != 1:
                raise LoweringError(
                    "a per-controller death count damages one set of seats",
                    node=node,
                )
            seats_recipient = node.recipients[0]
            if (
                not isinstance(seats_recipient, ast.PlayerRef)
                or seats_recipient.kind not in _LOOPED_PLAYER_RECIPIENTS
            ):
                raise LoweringError(
                    "no handler counts this death record per recipient", node=node
                )
            if SWEPT_CONTROLLER_SEATS not in produced:
                raise LoweringError(
                    f"back-reference to {SWEPT_CONTROLLER_SEATS!r} with no "
                    "producer in this effect",
                    node=node,
                )
            return (
                OracleInstruction(
                    "deal_damage", "",
                    {
                        "recipient": seats_recipient.kind,
                        X_FROM_COUNT_PER_RECIPIENT: {
                            "seat_tally_of": SWEPT_CONTROLLER_SEATS,
                        },
                    },
                ),
            )
        back_reference = {"amount_from": "destroyed_this_way"}
        amount = 0
    elif isinstance(node.amount, ast.CountersOnSource):
        # "…deals damage equal to the number of doom counters on it…"
        # (Armageddon Clock). A read off the source at resolution rather than a
        # number, so it travels the same payload-key channel "its power" does —
        # one key, not a second instruction kind.
        back_reference = {"amount_from_named_counters": node.amount.kind}
        amount = 0
    else:
        back_reference = {}
        printed = node.amount
        # "…deals **X plus 3** damage to you" (Hellfire). The constant rides its
        # own key rather than being folded into the where-clause's count: the
        # clause says what X *is*, and adding the 3 there would make the card's
        # own X mean a number it never printed — visible the moment a second
        # sentence reads that X. `deal_damage` adds the two at resolution.
        if isinstance(printed, ast.Plus):
            if not isinstance(printed.right, ast.Fixed):
                raise LoweringError(
                    "the printed addend on damage has to be a number", node=node
                )
            bonus = printed.right.value
            printed = printed.left
        amount = _amount_payload(printed)

    sweep = _sweep_kind(node.recipients)
    if sweep is not None:
        # The sweep handlers read a printed number, an announced X, the
        # counters on the ability's own source, or a scratchpad record
        # (`handlers/damage._sweep_amount`, the one reader all four share).
        # Every *other* computed amount would be dropped here and dealt as
        # zero — visible nowhere, since the card would still report supported —
        # so it refuses instead.
        if bonus or set(back_reference) - {"amount_from_named_counters", "amount_from"}:
            raise LoweringError(
                "a board sweep cannot carry a computed damage amount", node=node
            )
        if back_reference:
            return (OracleInstruction(sweep, "", dict(back_reference)),)
        return (OracleInstruction(sweep, "", {"amount": amount}),)

    if len(node.recipients) != 1:
        return _lower_split_recipients(node, event, produced)

    recipient = node.recipients[0]
    payload: dict[str, object] = (
        dict(back_reference) if back_reference else {"amount": amount}
    )
    if bonus:
        payload["amount_bonus"] = bonus
    if node.riders.no_regen:
        payload["no_regen"] = True
    if node.riders.exile_if_dies:
        payload["exile_if_dies"] = True
    if node.riders.unpreventable_to_creature:
        payload["unpreventable_to_creature"] = True

    # Divided damage (Fireball) picks its targets at cast time and carries them
    # on the stack item, so the noun phrase here is "any number of targets"
    # rather than a resolvable recipient. The *handler* therefore needs nothing
    # from the recipient — but the caster still has to be prompted for the
    # targets, and "deal_damage {amount: x}" alone cannot say so: it is the same
    # payload Lightning Bolt produces. Recording the division here is what lets
    # engine/targeting.py raise the divided prompt from the compiled program
    # rather than from a "divided" substring in legality.py.
    if node.riders.divided:
        described: dict[str, object] = {
            "quantifier": "divided",
            "kind": "divided",
            # **Which division the card prints** (CR 601.2d). "Divided evenly,
            # rounded down" is the game's; "divided as you choose" is the
            # caster's, announced with the spell. The parser has told the two
            # apart since it was written and nothing read the answer, so four
            # cards printing the second sentence were played as the first.
            "division": "evenly" if node.riders.divided_evenly else "chosen",
        }
        if node.riders.rounding == "up":
            # No card in this pool prints it, and rounding a share down where
            # the card says up deals less damage than printed — a refusal here
            # is the loud direction.
            raise LoweringError("a division rounded up is not implemented", node=node)
        if node.riders.rounding:
            described["rounding"] = node.riders.rounding
        # "…among any number of **target creatures**" (Fire Covenant). The
        # printed noun narrows the picker, and dropping it is why the engine
        # offered a player's face as a legal Fire Covenant target: this branch
        # returned before the recipient was ever read.
        narrowing = (
            _filter_payload(recipient.filter)
            if isinstance(recipient, ast.TargetSpec) else {}
        )
        if narrowing:
            if untestable_filter_keys(narrowing):
                raise LoweringError(
                    "a divided spell's targets carry a narrowing nothing tests",
                    node=node,
                )
            described["filter"] = narrowing
        payload["targets"] = described
        return (OracleInstruction("deal_damage", "", payload),)

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
        described = _filter_payload(recipient.filter)
        if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the event-subject damage cannot test this restriction", node=node
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
    elif isinstance(recipient, ast.PlayerRef) and recipient.kind == "each_opponent":
        # "…deals 2 damage to each opponent" (Storm Caller). The handler loops
        # the caster's living opponents through the same player-damage path a
        # single face takes, so shields and replacements see each event.
        payload["recipient"] = "each_opponent"
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
        described = _filter_payload(recipient.filter)
        if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the bound-set damage cannot test this restriction", node=node
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


def _lower_split_recipients(
    node: ast.DealDamage,
    event: str | None,
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"…it deals 2 damage to **you and each creature you control**."
    (Sorrow's Path.)

    One printed clause naming several recipients, and no sweep handler that
    batches exactly this set. Lowered as one instruction per recipient — the
    composition rule this engine already applies to "deal damage, then gain
    that much life" — rather than as a fused kind per printed pairing, which is
    what the legacy compiler did and is combinatorial in the number of shapes.
    `_sweep_kind` is asked first, so the three sets that *do* have a batching
    handler keep it.

    CR 120.4 makes the printed clause one event and this makes it several. What
    that can be seen through is a state-based action, and none runs between two
    steps of one resolution (CR 704.3) — so simultaneous lethal damage still
    kills together, which is the property the fused sweeps were written for.

    The split is only legal where nothing is *chosen*. A target is announced
    once, as the object is put on the stack (CR 601.2c); two instructions each
    describing one would raise two pickers for one printed choice, and the
    second would be collected against a target the card never announced. So a
    chosen recipient refuses here, and a sentence with two whole printed clauses
    — each announcing its own targets — goes through the conjunction below
    instead.
    """
    if node.riders != ast.DamageRiders():
        raise LoweringError(
            "a multi-recipient damage clause carries no riders", node=node
        )
    if any(_targets_payload(recipient) is not None for recipient in node.recipients):
        raise LoweringError(
            "multi-recipient damage without a sweep shape cannot name a target",
            node=node,
        )
    lowered: tuple[OracleInstruction, ...] = ()
    for recipient in node.recipients:
        lowered += _lower_damage(
            dataclasses.replace(node, recipients=(recipient,)), event, produced
        )
    return lowered


def _lower_damage_conjunction(node: ast.Conjunction) -> tuple[OracleInstruction, ...]:
    """Two damage clauses sharing a source.

    The legacy compiler minted a dedicated instruction kind per pairing
    (``deal_damage_and_self_damage``, ``deal_damage_and_opponent_choice``) —
    28 of its 120 kinds were conjunctions like these, which is combinatorial in
    the number of effects. Here the first shape decomposes into two ordinary
    damage instructions and the kind disappears.
    """
    first, second = node.effects
    assert isinstance(first, ast.DealDamage) and isinstance(second, ast.DealDamage)

    # "…and N damage to any target of an opponent's choice" keeps its dedicated
    # handler: the second target is chosen by a different player, which needs
    # the pending-prompt machinery rather than a second instruction.
    if second.chooser is not None:
        return (
            OracleInstruction(
                "deal_damage_and_opponent_choice", "",
                {
                    "amount": _amount_payload(first.amount),
                    "opponent_amount": _amount_payload(second.amount),
                },
            ),
        )
    return _lower_damage(first) + _lower_damage(second)


def _lower_damage_dealt_riders(
    node: "ast.DamageRidersUntilEndOfTurn",
) -> tuple[OracleInstruction, ...]:
    """Runesword's two rider sentences (CR 701.19c, CR 614).

    The riders are the same payload keys the damage lowering already writes;
    what differs is *when* they are read — the marker sits on the damager and
    the damage seam stamps the victim, rather than the dealer stamping one
    victim now. One kind for both sentences, because a card printing either
    alone is the same instruction with one key.
    """
    payload: dict[str, object] = {"subject": node.subject}
    if node.riders.no_regen:
        payload["no_regen"] = True
    if node.riders.exile_if_dies:
        payload["exile_if_dies"] = True
    return (OracleInstruction("grant_damage_riders_until_eot", "", payload),)
