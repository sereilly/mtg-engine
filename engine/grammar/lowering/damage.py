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
from ...subject_filters import untestable_filter_keys
from ...oracle_types import X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT
from ._amounts import tapped_this_way_record
from ._counted_damage import (
    _LOOPED_PLAYER_RECIPIENTS,
    _lower_board_count_damage,
    _lower_chosen_cast_damage,
    _lower_cost_sacrifice_damage,
    _lower_cost_counters_removed_damage,
    _lower_cost_discard_damage,
    _lower_cost_tap_damage,
    _lower_counted_damage,
    lower_difference_damage,
    lower_revealed_this_way_damage,
)

from ._bites import lower_bite
from ._superlatives import superlative_pick

from ._sweeps import (
    _sweep_kind,
    lower_counted_sweep_damage,
    refuse_unswept_multiplier,
)
from ._common import (
    _amount_payload,
    card_divided_each_description,
    _filter_payload, _is_enchanted,
)
from ._events import (_chosen_cast_amount, SWEPT_CONTROLLER_SEATS,
                      _back_reference_payload)
from ._recipients import lower_damage_recipient
from ._conjuncts import lower_damage_conjunction, lower_split_recipients


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
    event_subject: object | None = None,
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
    lowered = _lower_damage_shape(node, event, produced, event_subject)
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
    if node.riders.cant_be_prevented and not _lock_survives(
        lowered, key="cant_be_prevented"
    ):
        raise LoweringError(
            "no damage handler carries the printed 'the damage can't be "
            "prevented' here",
            node=node,
        )
    # "…to each player **who controls a white creature**." (Disorder.) The same
    # post-condition the riders above get, for the same reason and in the same
    # place: only two arms carry the clause, and a recipient that printed one
    # and reached any other arm would be a sentence damaging every player. A
    # branch added later gets the check for free.
    if any(
        getattr(recipient, "controls", None) is not None
        for recipient in node.recipients
    ) and not any(
        instruction.payload.get("recipient_controls") for instruction in lowered
    ):
        raise LoweringError(
            "no damage handler carries the printed seat narrowing here", node=node
        )
    lowered = _with_attached_dealer(node, lowered)
    lowered = _with_foreign_dealer(node, lowered, produced)
    return lowered


#: The record an earlier step of the same resolution writes about **the one
#: object it named**, which a later "that <noun> deals damage …" can be read
#: from. The ``Permanent`` itself, frozen before the step acts on it
#: (``handlers/destruction``: CR 608.2h, last known information) — so the
#: dealer still has its colours, its types and its controller after it has
#: gone to a graveyard. A tuple because the next card will name what was
#: exiled or tapped; one entry because one card prints the shape.
_DEALER_RECORDS = ("destroyed_target",)

#: The quantifiers that make a damage sentence's printed subject a **class or
#: a chosen object** — "creatures deal …", "each creature deals …", "target
#: creature deals …" — rather than the ability's own source or a back-reference.
_CLASS_DEALER_QUANTIFIERS = frozenset({"all", "each", "target"})


def _with_foreign_dealer(
    node: ast.DealDamage, lowered: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"Destroy target artifact. **That artifact** deals damage equal to its
    mana value to this creature." (Goblin Tinkerer.)

    The third post-condition on the dealer, beside ``_with_attached_dealer``
    and for its reason. ``_lower_damage_shape`` builds a plain ``deal_damage``
    from the recipients and the amount and never reads the subject, so a
    sentence whose subject is *some other object* compiled as the ability's own
    source dealing the damage — CR 120.7's source read off the wrong object,
    with the card reporting supported. Goblin Tinkerer, a red creature, burned
    itself: protection from red stopped damage the card says an artifact
    deals, protection from artifacts did not, and a lifelinking or deathtouching
    artifact creature it destroyed did nothing on the way out.

    Two answers, and never the third (dropping the subject):

    * **"that <noun>"** is a back-reference, and the dealer is the object an
      earlier step recorded. ``biter`` is the key every dealer already rides
      (``"attached"``, ``"event_subject"``); its value here is the record the
      handler reads it from. With no such record the line refuses — a
      back-reference to nothing is a dealer nobody can find.
    * **a class or a target** ("creatures deal …", "target creature deals …")
      has no handler that makes each of them the source, so it refuses. No card
      in the pool prints it; it was found by the deletion probe on cards whose
      name opens with a type word — delete "Flames" from Tribal Flames and
      "Tribal deals X damage to any target" is a class subject that used to
      lower to the very same instruction.

    Only where the dealer is certainly dropped — one plain ``deal_damage``
    carrying no ``biter``. A fight, a bite and the per-creature sweeps lower to
    kinds that name their own dealers and are not this function's business;
    neither is "it", which is the source wherever the pool prints it bare
    (Mogg Bombers: "sacrifice this creature and it deals 3 damage …").
    """
    source = node.source
    if (
        not isinstance(source, ast.TargetSpec)
        or source.filter.is_source
        or _is_enchanted(source)
        or len(lowered) != 1
        or lowered[0].kind != "deal_damage"
        or "biter" in lowered[0].payload
    ):
        return lowered
    if source.quantifier == "that":
        record = next((key for key in _DEALER_RECORDS if key in produced), None)
        if record is None:
            raise LoweringError(
                "no earlier step records the object this damage's printed "
                "dealer refers back to",
                node=node,
            )
        instruction = lowered[0]
        return (
            dataclasses.replace(
                instruction, payload={**instruction.payload, "biter": record}
            ),
        )
    if source.quantifier in _CLASS_DEALER_QUANTIFIERS:
        raise LoweringError(
            "no damage handler makes the printed class or target the source "
            "of this damage",
            node=node,
        )
    return lowered


def _with_attached_dealer(
    node: ast.DealDamage, lowered: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"**Enchanted creature** deals 1 damage to …" (Dizzying Gaze).

    The printed subject of a damage sentence, which this module had never read:
    every branch of :func:`_lower_damage_shape` builds its payload from the
    *recipients* and the amount, so an Aura's own ability dealt the damage as
    the **Aura**. CR 120.7 makes that the wrong source — protection from the
    host's colour would not have stopped it and protection from the Aura's
    would, which is the rule backwards — and the log said so out loud.

    ``biter: "attached"`` is not a new key. ``_bites`` has emitted it since
    Farrel's Mantle for the power-reading form of the same sentence, with the
    same reasoning written down: CR 113.7a leaves the ability the Aura's, so
    only the **dealer** moves. One name for one fact; what was missing is that
    a *fixed* amount never reached it.

    A post-condition rather than a line in each branch, for the reason the
    riders above are one: a branch added later gets it for free. And it
    **refuses** rather than dropping the subject, because a shape that cannot
    carry the dealer is a card whose damage would come from the wrong object —
    the failure this whole function exists to make loud.
    """
    if node.source is None or not _is_enchanted(node.source):
        return lowered
    if len(lowered) == 1 and lowered[0].payload.get("biter") == "attached":
        # Already carried. ``_bites`` stamps this key itself for the
        # power-reading form (Farrel's Mantle), and stamping it twice here
        # would be one fact with two producers — but the *refusal* below would
        # be worse: the differential caught this branch turning a shipped,
        # correct card unsupported, because its kind is `source_bites_target`
        # rather than `deal_damage`. The question is whether the dealer
        # survives, not which family answered it.
        return lowered
    if len(lowered) != 1 or lowered[0].kind != "deal_damage":
        raise LoweringError(
            "no damage handler carries the printed attached dealer here",
            node=node,
        )
    instruction = lowered[0]
    return (
        dataclasses.replace(
            instruction, payload={**instruction.payload, "biter": "attached"}
        ),
    )


def _lock_survives(
    lowered: tuple[OracleInstruction, ...], key: str = "unpreventable_to_creature",
) -> bool:
    """Whether Lava Burst's lock reaches a branch that actually applies it.

    *key* is which of the two printed locks is asked about. Urza's Rage's
    ("cant_be_prevented") is threaded to the same single-recipient branches
    plus the one that deals to a chosen **player**, which is still "no named
    recipient, one target" and so the same test.

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
    if not payload.get(key):
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
    event_subject: object | None = None,
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
    # "…deals damage to each player equal to **twice** the number of nonbasic
    # lands that player controls." (Price of Progress.) A printed factor over a
    # counted quantity, unwrapped here and handed to the count branch below as a
    # number rather than as a node: `count_spec` already carries a `multiplier`
    # (CR 107.3, `handlers/_common._scaled` applies it once for every
    # aggregate), so the factor travels the channel every other scaled count
    # travels and no handler learns a new key.
    #
    # Read *before* the count branch and only over a `CountOf`, because that is
    # the one definition below that can carry a factor: a `Times` over anything
    # else falls to the refusal at the end of this function rather than silently
    # losing the word, which on this card would be half the damage it prints.
    #
    # ``CountOfRevealsThisWay`` joins it for the same reason one record over:
    # "deals **3** damage … for each card of the chosen type revealed this way"
    # (Blood Oath) is a rate over a count, and its spec carries the identical
    # ``multiplier`` key. Every other amount still falls to the refusal at the
    # end of this function rather than losing the word.
    multiplier, amount = 1, node.amount
    if isinstance(amount, ast.Times) and isinstance(
        amount.of, (ast.CountOf, ast.CountOfRevealsThisWay)
    ):
        multiplier, node = amount.factor, dataclasses.replace(node, amount=amount.of)
    # "…for each card of the chosen type **revealed this way**" (Blood Oath).
    # Beside the board count below rather than inside it: what is counted is a
    # list of *cards* an earlier sentence of this same effect recorded, and no
    # reading of any zone is that set — the hand it came from goes on changing.
    if isinstance(node.amount, ast.CountOfRevealsThisWay):
        return lower_revealed_this_way_damage(
            node, produced, multiplier=multiplier, event=event
        )
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
            return lower_counted_sweep_damage(
                node, node.recipients[0], multiplier=multiplier
            )
        return _lower_counted_damage(node, event, multiplier=multiplier)
    # "…equal to the sacrificed creature's power" (Freyalise Supplicant, under
    # the half above). A characteristic of what the cost ate rather than a count
    # of anything on a board, so it sits beside the count rather than inside it.
    # "…equal to the number of creatures you control **in excess of** the
    # number of creatures target opponent controls." (Superior Numbers.) One
    # quantity with two counted halves, beside the counts above rather than
    # inside them: the subtrahend is scoped to a *different* seat, which is the
    # one thing `count_spec` cannot carry on a filter.
    if isinstance(node.amount, ast.Minus):
        return lower_difference_damage(node)
    if isinstance(node.amount, ast.SacrificedForCost):
        return _lower_cost_sacrifice_damage(node)
    # "…equal to **the tapped creature's power**" (Unerring Sling) — the same
    # shape one payment over, and beside it for that branch's reason: a
    # characteristic of what the cost acted on rather than a count of anything
    # on a board.
    if isinstance(node.amount, ast.TappedForCost):
        return _lower_cost_tap_damage(node)
    # "…equal to **the number of pain counters removed this way**" (Torture
    # Chamber) — the fourth payment channel, beside its three siblings and for
    # their reason: a quantity the ability's own cost produced rather than a
    # count of anything on a board.
    if isinstance(node.amount, ast.CountersRemovedForCost):
        return _lower_cost_counters_removed_damage(node)
    # "…equal to **the mana value of the discarded card**" (Pyromancy) — the
    # fifth payment channel, beside the four above and for their reason: a
    # quantity the ability's own cost produced rather than a count of any board.
    if isinstance(node.amount, ast.DiscardedForCost):
        return _lower_cost_discard_damage(node)
    if isinstance(node.amount, ast.BoardCount):
        return _lower_board_count_damage(node, produced)
    # A **bite**: one named object deals damage equal to its own power, and
    # is itself the source of that damage (`_bites`). Probed before the
    # quantity branches below because the amount is a *read* rather than a
    # number — and after the counted ones above, which a bite never is.
    bite = lower_bite(node, produced, event)
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
    elif isinstance(node.amount, ast.CountOfTapsThisWay):
        # "…tap all untapped creatures that player controls that didn't attack
        # this turn. This artifact deals damage to the player equal to **the
        # number of creatures tapped this way**." (Angel's Trumpet.) The sweep in
        # front of this one is the only thing that can say how many it turned —
        # by the time this step runs the board says how many *are* tapped, which
        # is a different set and always the larger one.
        #
        # The node has had a lowering since Monsoon printed the same quantity as
        # a ", where X is …" trailer; this is the other printed position, and it
        # asks the same floor for the same two refusals rather than growing a
        # copy of them (``_amounts.tapped_this_way_record``). Without this branch
        # the amount reached `_amount_payload` and refused as "unsupported
        # quantity CountOfTapsThisWay" — a card whose trigger compiled an ability
        # part with no instruction behind it, which is what
        # ``support_report --hollow-lines`` and ``parse_coverage`` were both
        # reporting about the sentence.
        back_reference = {
            "amount_from": tapped_this_way_record(
                node.amount.filter, produced, node
            )
        }
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
        return lower_split_recipients(
            node, event, produced, event_subject, _lower_damage
        )

    recipient = node.recipients[0]
    # "…deals 2 damage to **the creature with the least toughness**" (Purging
    # Scythe). The recipient is not chosen and not described: it is the end of a
    # range, so the sentence becomes the pick and then the damage, and the
    # damage reads what the pick recorded through the ``permanents_from``
    # channel every other bound permanent travels
    # (``deal_damage_to_recorded_permanents``, which Winter Blast's "those
    # creatures" already reaches).
    #
    # Read *before* the payload below because none of the shapes it assembles
    # apply: the recorded-permanents handler takes a printed number and a
    # filter, and every computed amount and every rider would be built here and
    # then dropped. They refuse instead.
    pick = superlative_pick(recipient, node=node, verb="damage")
    if pick is not None:
        step, key = pick
        if back_reference or bonus or node.riders.divided:
            raise LoweringError(
                "a superlative recipient cannot carry a computed damage "
                "amount or a division",
                node=node,
            )
        return (
            OracleInstruction("sequence", "", {"steps": (
                step,
                OracleInstruction(
                    "deal_damage_to_recorded_permanents", "",
                    {"amount": amount, "permanents_from": key, "filter": {}},
                ),
            )}),
        )
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
    if node.riders.cant_be_prevented:
        payload["cant_be_prevented"] = True

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
        # "…among **one, two, or three** targets." (Arc Lightning.) CR 601.2c's
        # printed ceiling on a count the caster still chooses, carried under the
        # same ``max_targets`` key every other picker spec uses — the client,
        # `legality.py`'s cast gate and `divided_damage.division_refusal` all
        # already read it, and the last of those has cited Arc Lightning's
        # spelling in its docstring since Contagion arrived. A `None` here is
        # "among any number of", which is a different sentence rather than a
        # ceiling of infinity.
        if isinstance(recipient, ast.TargetSpec) and recipient.max_count is not None:
            described["max_targets"] = recipient.max_count
        payload["targets"] = described
        return (OracleInstruction("deal_damage", "", payload),)

    # "Firestorm deals X damage to **each of X targets**." The same cross-seat
    # announcement the branch above makes, with the card supplying the count and
    # nothing supplying a division (`card_divided_each_description`). Here
    # rather than in the several-targets branch below, which describes a list of
    # *permanents*: CR 115.4's "any target" spans the players' faces too.
    each_of = card_divided_each_description(recipient)
    if each_of is not None:
        if back_reference or bonus:
            raise LoweringError(
                "a card-divided damage cannot carry a computed amount", node=node
            )
        payload["targets"] = each_of
        return (OracleInstruction("deal_damage", "", payload),)

    return lower_damage_recipient(
        node, recipient, payload, amount, back_reference, bonus, event, produced,
        event_subject,
    )


def _names_the_source(spec: "ast.TargetSpec | None") -> bool:
    """Whether a damage clause's *source* is the object printing it — the card's
    own name or "this spell" in the first sentence, "it" in the second."""
    return isinstance(spec, ast.TargetSpec) and spec.filter.is_source


def kicked_second_damage_target(
    steps: tuple[ast.Statement, ...],
) -> "ast.Conditional | None":
    """"Magma Burst deals 3 damage to any target. **If this spell was kicked,
    it deals 3 damage to another target.**" as one two-armed sentence, or None.

    CR 702.33g: the second target is chosen only if the spell was kicked, and
    the printed "another" (CR 601.2c) makes it a *different* one. So the kicked
    spell deals its amount to each of two targets and the unkicked one to one —
    which is the sentence "…deals 3 damage to **each of two targets**" already
    lowers, behind the same condition the card prints. Returned as that
    ``Conditional`` for the dispatcher to lower: then = the damage over two
    targets, otherwise = the printed first sentence.

    **Why not a slot per clause**, which is what Rushing River's identical
    sentence over permanents gets (``_roles.plan_another_target_roles``): "any
    target" is a seat *or* an object (CR 115.4), and an ordered-roles
    announcement decides which of the two a slot is from its *kind*, before
    anything is chosen — its seat rides the one ``target_player_index`` a stack
    item has. Two "any target" slots may both be players, which that channel
    cannot say. The card-divided list is the engine's one announcement of
    targets spanning both battlefields and the players' faces
    (``_targets.card_divided_target_description``), so the kicked arm goes
    there, and ``targeting._as_kicked`` already collapses the pair to the arm a
    given cast will run.

    Nothing observable is lost by the two damages sharing one step: no player
    receives priority inside a resolution (CR 117.3b) and state-based actions
    wait for it to end (CR 704.3), so the only order a spell's own steps can
    expose is one reading what an earlier one did — and neither damage reads
    the other.

    Narrow, for the cards this must not claim:

    * the condition is "was kicked", un-negated, with no other arm. Any other
      condition leaves both targets announced whichever way it resolves
      (CR 601.2c exempts only a mode and a cost), which is a different
      announcement;
    * both clauses are one plain "any target" dealt by the source itself, the
      second printing "another";
    * **the same amount and the same riders.** Different amounts would be a
      card-dictated *share* per target, which is Cone of Flame's lowering and
      not this one's; a rider on one clause alone has no payload to ride.

    None hands the sentence on to the roles planner and, past it, to
    ``_refuse_unfused_distinctness``.
    """
    if len(steps) != 2:
        return None
    first, guarded = steps
    if not isinstance(first, ast.DealDamage) or not isinstance(guarded, ast.Conditional):
        return None
    condition = guarded.condition
    if (
        not isinstance(condition, ast.WasKicked)
        or condition.negated
        or guarded.negated
        or guarded.otherwise is not None
    ):
        return None
    again = guarded.then
    if not isinstance(again, ast.DealDamage):
        return None
    if len(first.recipients) != 1 or len(again.recipients) != 1:
        return None
    target, other = first.recipients[0], again.recipients[0]
    for spec in (target, other):
        if not (
            isinstance(spec, ast.TargetSpec)
            and spec.quantifier == "any_target"
            and spec.targeted
            and spec.count == 1
            and not spec.count_from_x
        ):
            return None
    if target.distinct_from_prior or not other.distinct_from_prior:
        return None
    if dataclasses.replace(other, distinct_from_prior=False) != target:
        return None
    if not (_names_the_source(first.source) and _names_the_source(again.source)):
        return None
    if (
        again.amount != first.amount
        or again.riders != first.riders
        or again.chooser != first.chooser
        or again.per_each != first.per_each
        or first.riders.divided
    ):
        return None
    both = dataclasses.replace(
        first, recipients=(dataclasses.replace(target, count=2),)
    )
    return ast.Conditional(condition, then=both, otherwise=first)




def _lower_damage_conjunction(
    node: ast.Conjunction,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """:func:`_conjuncts.lower_damage_conjunction`, holding this module's own
    ``_lower_damage`` for it.

    The name stays here because ``statement_dispatch`` imports it and a
    conjunction is a damage shape however small its lowering has become; what
    moved is the *reasoning*, which is what crossed the size guard. A floor may
    not import its family, so the callback is handed down rather than reached
    for — three lines here instead of a cycle there.
    """
    return lower_damage_conjunction(
        node, event, produced, event_subject, _lower_damage
    )


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
