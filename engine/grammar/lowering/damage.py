"""Lowering damage.

Plain damage, the "unless they pay" shape, the halved amount and damage
conjunctions. The CR 615 prevention shields left for `prevention` when this
module reached the thousand-line guard; they shared no helper with anything
here. The **computed** amounts left for `_amounts` the next time it did — a
quantity counted off a board or out of the scratchpad against the sentence that
spends it, and a floor rather than a family because this module reads it.

`deal_damage` is the one instruction that records a value other steps can read
(`_PRODUCES` in `_records.py`), which is why "deal damage, then gain that much
life" is two instructions in a sequence rather than a fused kind.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ...subject_filters import (
    TESTABLE_SUBJECT_FILTER_KEYS, untestable_filter_keys,
)
from ...oracle_types import PER_OBJECT_SEAT_RECORDS, X_FROM_COUNT
from ._amounts import (
    _damaged_player_is,
    _lower_board_count_damage,
    _lower_chosen_cast_damage,
    _lower_cost_sacrifice_damage,
    _lower_counted_damage,
)
from ._sacrifices import _SACRIFICE_CARRIED, _forced_sacrifice_filter
from ._common import (
    _lower_described_set_damage,
    _describe_several_targets,
    _names_several_targets,
    _amount_payload,
    _describe_targets,
    _filter_payload,
    _restrictions_beyond,
    _full_mana_payload,
    _is_enchanted,
    _is_source,
    _is_target,
    _is_you,
    _targets_payload,
)
from ._events import (
    _chosen_cast_amount,
    _EVENT_SUBJECT_CONTROLLERS,
    _EVENT_SUBJECT_CONTROLLERS,
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_CONTROLLER,
    EVENT_SUBJECT_PLAYER,
    _back_reference_payload,
    _DAMAGED_PERMANENTS,
    _RECORDED_PERMANENTS,
)


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------


def _sweep_kind(recipients: tuple[ast.Recipient, ...]) -> str | None:
    """Recognize the board-sweep damage shapes as their dedicated handlers.

    These are genuinely different effects, not riders: they damage every player
    *and* a filtered set of creatures as one state-based-action batch.
    """
    hits_players = any(
        isinstance(r, ast.PlayerRef) and r.kind in ("each_player", "each_opponent")
        for r in recipients
    )
    creature_specs = [
        r for r in recipients
        if isinstance(r, ast.TargetSpec) and r.quantifier == "each"
    ]
    if len(creature_specs) != 1:
        return None
    filt = creature_specs[0].filter
    if filt.card_types != ("creature",):
        return None

    if hits_players:
        if filt.without_keywords == ("flying",):
            return "earthquake_damage"
        if filt.with_keywords == ("flying",):
            return "hurricane_damage"
        if not filt.with_keywords and not filt.without_keywords:
            return "deal_damage_each_creature_and_player"
        return None
    if filt.attacking and not filt.with_keywords and not filt.without_keywords:
        return "deal_damage_each_attacking_creature"
    return None


def _lower_damage_unless_pay(
    node: ast.DamageUnlessPay,
    event: str | None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"<source> deals N damage to you unless you pay <cost>."

    Two engine flows implement this and the *trigger* picks between them, which
    is why the event kind is threaded down here rather than inferred from the
    clause. On an upkeep trigger the pair (condition, instruction kind) is
    looked up in engine/phases/upkeep_effects.py, so only the fused
    ``upkeep_pay_or_deal_damage_to_controller`` is dispatched; everywhere else
    the trigger resolves through EFFECT_HANDLERS, where ``self_damage_unless_pay``
    arms the pending optional-pay prompt. Emitting either one under the other's
    trigger produces a card that compiles cleanly and does nothing.
    """
    damage = node.damage
    # "…deals 2 damage to **that player** unless **they** pay {2}" (Soul
    # Barrier, Seizures): payer and recipient are one seat, the one the firing
    # event named and froze into the trigger's context (CR 603.10). Both words
    # are required to agree — a clause damaging one player while offering the
    # cost to another is a card neither flow implements.
    on_event_player = (
        isinstance(node.payer, ast.PlayerRef)
        and node.payer.kind == "that_player"
        and _damaged_player_is(damage.recipients, "that_player")
    )
    if not on_event_player:
        if not _is_you(node.payer):
            raise LoweringError(
                "both pay-or-else flows offer the cost to the ability's controller",
                node=node,
            )
        if not (len(damage.recipients) == 1 and _is_you(damage.recipients[0])):
            raise LoweringError(
                "both pay-or-else flows damage the ability's controller", node=node
            )
    if damage.riders != ast.DamageRiders():
        raise LoweringError("no pay-or-else flow carries damage riders", node=node)
    amount = _amount_payload(damage.amount)
    if not isinstance(amount, int):
        raise LoweringError("a pay-or-else flow needs a fixed damage amount", node=node)

    # "For each land destroyed this way, <source> deals 1 damage to **that
    # land's controller** unless **they** pay {2}." (Stench of Evil.) The seat
    # is neither the ability's controller nor a trigger's frozen event subject:
    # it is a fact an earlier *step of this same spell* recorded about the
    # object the loop is currently on, which is the third channel
    # `PER_OBJECT_SEAT_RECORDS` exists for. Admitted only when a step really
    # wrote that record, which is what `produced` is; without one the words
    # name nobody and the clause keeps the refusal below.
    #
    # The printed possessive collapses to `that_player` in the AST — "that
    # land's controller", "that player" and "they" are one referent to every
    # consumer — so what distinguishes this reading is the record, not the
    # spelling. A card printing a bare "that player" behind such a sweep would
    # reach it too; the handler finds no seat for the loop it is not in, and
    # does nothing, which is the safe direction.
    controller_record = PER_OBJECT_SEAT_RECORDS["controller"]
    if on_event_player and controller_record in produced:
        return (
            OracleInstruction(
                "self_damage_unless_pay", "",
                {
                    "amount": amount,
                    "cost": _generic_only(node.cost, node),
                    "payer_seat_record": controller_record,
                },
            ),
        )
    if event is None:
        raise LoweringError(
            "a pay-or-else damage prompt exists only as a trigger's own effect",
            node=node,
        )
    if event.startswith("upkeep"):
        if event != "upkeep_self":
            raise LoweringError(
                f"no upkeep handler pairs {event!r} with a pay-or-else damage prompt",
                node=node,
            )
        return (
            OracleInstruction(
                "upkeep_pay_or_deal_damage_to_controller", "",
                {"damage": amount, "mana": _full_mana_payload(node.cost)},
            ),
        )

    payload: dict[str, object] = {
        "amount": amount, "cost": _generic_only(node.cost, node),
    }
    if on_event_player:
        # Which seat is offered the cost, as payload rather than a second kind:
        # same prompt, same damage, same decline — only the player differs, and
        # the handler reads the seat off the trigger's frozen context.
        #
        # **Which** frozen key depends on the event, and this branch used to
        # name one without asking. "That player" is the seat the event was
        # *about* under an upkeep or a cast; under a tap it is the seat that
        # controlled the object the event was about, stamped under a different
        # key by a different fire site. Seizures ("whenever enchanted creature
        # becomes tapped, this Aura deals 3 damage to **that creature's
        # controller** unless that player pays {3}") compiled to the first key
        # under an event that stamps the second, so the handler found no seat
        # and the Aura did nothing at all — on every tap, since it was printed.
        if event in _EVENT_SUBJECT_PLAYERS:
            payload["payer"] = EVENT_SUBJECT_PLAYER
        elif event in _EVENT_SUBJECT_CONTROLLERS:
            payload["payer"] = EVENT_SUBJECT_CONTROLLER
        else:
            raise LoweringError(
                f"no event named {event!r} freezes the seat 'that player' names",
                node=node,
            )
    return (OracleInstruction("self_damage_unless_pay", "", payload),)


def _generic_only(cost, node) -> int:
    """The one generic number ``self_damage_unless_pay``'s prompt can charge.

    Refuses a coloured pip rather than dropping it: the prompt puts a single
    generic number on screen, so a coloured cost would be charged as {0} and the
    card would be strictly easier to buy off than it is printed.
    """
    pips = dict(cost.pips)
    generic = int(pips.pop("generic", 0))
    if pips:
        raise LoweringError(
            "the optional-pay prompt reads one generic cost, not coloured mana",
            node=node,
        )
    return generic


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
    if len(whole) != 1 or whole[0].kind != "deal_damage":
        raise LoweringError("no handler halves this damage amount", node=node)
    payload = dict(whole[0].payload)
    counted = payload.get(X_FROM_COUNT)
    if isinstance(counted, dict):
        payload[X_FROM_COUNT] = {**counted, "half": node.amount.rounding}
    else:
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
        return _lower_counted_damage(node, event)
    # "…equal to the sacrificed creature's power" (Freyalise Supplicant, under
    # the half above). A characteristic of what the cost ate rather than a count
    # of anything on a board, so it sits beside the count rather than inside it.
    if isinstance(node.amount, ast.SacrificedForCost):
        return _lower_cost_sacrifice_damage(node)
    if isinstance(node.amount, ast.BoardCount):
        return _lower_board_count_damage(node, produced)
    # "Target creature you control deals damage equal to its power to another
    # target creature." (Garruk, Savage Herald's −2.) A fused kind: the biter
    # and the bitten are two chosen targets resolved as a list, and the amount
    # is the biter's power read at resolution — which is why the generic
    # deal_damage cannot carry it.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and node.source.quantifier == "target"
        and len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.TargetSpec)
        and node.recipients[0].distinct_from_prior
        # Both slots are *targets*. "another target creature" and "another
        # creature" are different cards — the second chooses on resolution
        # (CR 601.2c names nothing) — and this kind builds a two-slot cast-time
        # picker, so admitting the untargeted phrase would raise a picker for a
        # choice the card never announces and drop the printed word.
        and node.recipients[0].targeted
    ):
        return (
            OracleInstruction(
                "target_bites_target",
                "",
                {
                    "targets": {
                        "quantifier": "target",
                        "kind": "object",
                        "filter": _filter_payload(node.source.filter),
                        # Two picks: the biter (first), then the bitten — and
                        # they are *differently* restricted. "Target creature
                        # you control deals damage … to **another target
                        # creature**" names the caster's creature and then
                        # anyone's, and one filter for both slots is what made
                        # the picker offer only the caster's for the second:
                        # Garruk's -2 could bite nothing but his own board while
                        # its handler was written to allow either.
                        "filters": [
                            _filter_payload(node.source.filter),
                            _filter_payload(node.recipients[0].filter),
                        ],
                        "count": 2,
                    },
                },
            ),
        )
    # "This creature deals damage equal to its power to target **player** or
    # planeswalker." (Leafkin Avenger.) The recipient is not an object, so the
    # bites handler below — which resolves a permanent — cannot carry it. The
    # generic damage instruction can: what is new is only where the *number*
    # comes from, and that is one payload key rather than a kind.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and _is_source(node.source)
        and len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.PlayerRef)
    ):
        payload: dict[str, object] = {"amount_from_source_power": True}
        _describe_targets(payload, node.recipients[0])
        return (OracleInstruction("deal_damage", "", payload),)
    # "It deals damage equal to **its power** to target creature or
    # planeswalker." (Heartfire Immolator.) The source is sacrificed to pay the
    # cost, so by resolution it is in a graveyard — its power is last-known
    # information (CR 608.2), which the Permanent object still carries because
    # nothing off the battlefield touches it. Its own kind rather than the
    # generic damage, because the amount is a *read* rather than a number.
    # …and the same sentence on an **Aura**, where the biter is the permanent it
    # enchants rather than the Aura (Farrel's Mantle). CR 113.7a keeps the
    # ability the Aura's, so the source stays the Aura and *which permanent
    # deals the damage* is payload — the same split
    # `assign_no_combat_damage_until_eot` makes for the same reason, and the
    # only one available: an Aura's power is nothing at all, so a bite read off
    # the source would deal zero and report itself resolved.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and (_is_source(node.source) or _is_enchanted(node.source))
        and len(node.recipients) == 1
        and _is_target(node.recipients[0])
    ):
        assert isinstance(node.recipients[0], ast.TargetSpec)
        payload: dict[str, object] = {}
        _describe_targets(payload, node.recipients[0])
        payload["filter"] = _filter_payload(node.recipients[0].filter)
        if _is_enchanted(node.source):
            payload["biter"] = "attached"
            # "…to **another** target creature" (Farrel's Mantle). "Another"
            # than the creature dealing the damage (CR 109.5's rule read about
            # the object the sentence names, not about the Aura it is printed
            # on) — so the exclusion moves with the biter. Left as
            # ``exclude_self`` the picker would exclude the *Aura*, which is
            # not a creature and was never on the list, and offer the attacker
            # itself as its own victim.
            for described in (payload.get("targets") or {}), payload:
                if described.get("filter", {}).pop("exclude_self", None):
                    described["filter"]["exclude_attached"] = True
        # "…equal to its power **plus 2**" (Farrel's Mantle). CR 107.3's
        # constant, carried rather than dropped: two fewer damage than the card
        # prints is exactly the silent narrowing a dropped rider always is.
        if node.amount.bonus:
            payload["power_bonus"] = node.amount.bonus
        return (OracleInstruction("source_bites_target", "", payload),)

    # "**That creature** deals damage equal to its power to this creature."
    # (Tracker.) The second half of a printed exchange: the biter is the
    # creature the sentence in front of this one chose, and the bitten is the
    # ability's own source. Its own kind rather than CR 701.14's fight, which
    # this looks like and is not — a fight is all-or-nothing (701.14b), so a
    # source that has left the battlefield stops *both* halves, while these are
    # two sentences and the first one still happened.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and isinstance(node.source, ast.TargetSpec)
        and node.source.quantifier == "that"
        and len(node.recipients) == 1
        and _is_source(node.recipients[0])
        and node.riders == ast.DamageRiders()
    ):
        if _restrictions_beyond(node.source.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound object carries no narrowing the bite could honour",
                node=node,
            )
        if _DAMAGED_PERMANENTS not in produced:
            # The handler reads the biter out of the resolution scratchpad, and
            # with nothing recorded it would deal nothing while the card
            # compiled clean — the discipline every back-reference here follows.
            raise LoweringError(
                f"back-reference to {_DAMAGED_PERMANENTS!r} with no producer "
                "in this effect",
                node=node,
            )
        return (
            OracleInstruction(
                "bound_bites_source", "",
                {"permanents_from": _DAMAGED_PERMANENTS},
            ),
        )

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
        if recipient.kind == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
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
        elif not recipient.or_planeswalker:
            payload["recipient"] = "target_player"
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
        # "…deals 2 damage to **each creature you control**" (Sorrow's Path).
        # A creature sweep narrowed by a printed noun phrase, which is what
        # `_sweep_kind`'s three fused kinds each are with the narrowing baked
        # into the kind's name. Here the narrowing is payload, so a card
        # printing a different one needs no code — and the fused kinds keep
        # their cards because `_sweep_kind` is consulted first, above.
        #
        # Creatures only, checked rather than assumed: CR 120.3 lists what
        # damage can even be dealt to, and a sweep written over "each
        # permanent" would quietly mark damage on artifacts and lands that
        # nothing would ever read.
        if recipient.filter.card_types != ("creature",):
            raise LoweringError(
                "only a creature sweep is damaged by the printed noun phrase",
                node=node,
            )
        if back_reference or bonus:
            raise LoweringError(
                "a creature sweep cannot carry a computed damage amount", node=node
            )
        described = _filter_payload(
            dataclasses.replace(recipient.filter, card_types=())
        )
        # Idiom 2: a restriction the matcher cannot test is one the handler
        # would silently ignore, which widens the sweep rather than narrowing
        # it — every creature on the board instead of the printed set.
        if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the creature sweep cannot test this restriction", node=node
            )
        return (
            OracleInstruction(
                "deal_damage_each_matching", "",
                {"amount": amount, "filter": described},
            ),
        )
    elif isinstance(recipient, ast.TargetSpec) and recipient.quantifier not in (
        "any_target", "target", "this"
    ):
        return _lower_described_set_damage(node, recipient, amount, back_reference or bonus)

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


def _lower_damage_reduced_by_paid_mana(
    node: ast.DamageReducedByPaidMana,
) -> tuple[OracleInstruction, ...]:
    """Power Leak / Errant Minion's three sentences, with the number as payload.

    The ordinary ``deal_damage`` kind plus one key, not a kind of its own: the
    ``(upkeep_enchanted_controller, deal_damage)`` handler in
    ``engine/phases/upkeep_effects.py`` is what implements the whole clause, and
    a second kind would be a second pair in that registry doing the same thing.

    ``prevent_up_to_paid_mana`` is what that handler used to read as a substring
    of the permanent's oracle text — the gate and the dispatch agreeing by
    coincidence rather than by construction. It is payload now, so a card whose
    clause this production has *not* read cannot be reduced by a payment nobody
    offered.
    """
    if node.amount <= 0:
        raise LoweringError("the upkeep damage takes a fixed amount", node=node)
    return (
        OracleInstruction(
            "deal_damage", "",
            {"amount": node.amount, "prevent_up_to_paid_mana": True},
        ),
    )


def _lower_upkeep_damage_unless_cost(
    node: ast.UpkeepDamageUnlessCost,
) -> tuple[OracleInstruction, ...]:
    """Mishra's War Machine / Minion of Leshrac's two sentences, with the number
    and the cost as payload.

    Fused rather than composed, for the reason the damage family's "unless"
    docstring already gives about this shape: two upkeep handlers implement it
    whole, and the tap rides the *damage* branch — a `May` whose otherwise-arm
    carries a rider is the fusion with extra steps.

    The sacrifice filter goes through the forced-sacrifice reducer, the same one
    every other charged sacrifice in the engine reads, so a noun phrase the
    prompt cannot test refuses the line rather than being charged as "any
    permanent".
    """
    amount = _amount_payload(node.amount)
    if not isinstance(amount, int) or amount <= 0:
        raise LoweringError("the upkeep damage takes a fixed amount", node=node)
    payload: dict[str, object] = {"amount": amount}
    if node.taps_source:
        payload["taps_source"] = True
    if node.discard:
        payload["discard"] = node.discard
        return (OracleInstruction("upkeep_damage_unless_cost", "", payload),)
    assert node.sacrifice is not None
    described = _forced_sacrifice_filter(node.sacrifice)
    if described is None:
        raise LoweringError(
            "the upkeep alternative cannot charge this sacrifice", node=node
        )
    payload["sacrifice"] = described
    # Carried beside the filter rather than inside it: the charger compares by
    # identity against the ability's source, which no filter key can express.
    if node.sacrifice.other_than_source:
        payload["exclude_self"] = True
    return (OracleInstruction("upkeep_damage_unless_cost", "", payload),)
