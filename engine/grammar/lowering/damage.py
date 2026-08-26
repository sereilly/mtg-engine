"""Lowering damage.

Plain damage, the counted and board-count variants whose arithmetic a dedicated
handler performs in full, the "unless they pay" shape, and damage conjunctions.
The CR 615 prevention shields left for `prevention` when this module reached the
thousand-line guard; they shared no helper with anything here.

`deal_damage` is the one instruction that records a value other steps can read
(`_PRODUCES` in `categories.py`), which is why "deal damage, then gain that much
life" is two instructions in a sequence rather than a fused kind.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS
from ...oracle_types import X_FROM_COUNT
from ._common import (
    _REST_OF_TURN,
    _describe_several_targets,
    _names_several_targets,
    count_spec,
    _amount_payload,
    _describe_targets,
    _filter_payload,
    _restrictions_beyond,
    _full_mana_payload,
    _is_source,
    _is_target,
    _is_you,
    _targets_payload,
)
from ._events import (
    _EVENT_SUBJECT_CONTROLLERS,
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_PLAYER,
    _back_reference_payload,
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


# Counted damage whose arithmetic a dedicated handler performs in full. Keyed
# by the exact noun phrase counted, because that phrase *is* the handler's
# contract: `_on__upkeep_each__deal_damage_equal_to_swamps` counts the Swamps
# controlled by the player whose upkeep is resolving and reads an empty payload,
# so a filter that differs in any way — a different land type, a different
# controller — has no handler and must refuse rather than count the wrong thing.
_SWAMPS_THEY_CONTROL = ast.ObjectFilter(subtypes=("swamp",), controller="that_player")

# Named board counts (ast.BoardCount) mapped to the instruction that computes
# them. `deal_damage` appears here for `untapped_lands_at_turn_start` because
# that is genuinely how the engine encodes Power Surge today: the upkeep
# handlers read `amount == "x"` as "untapped lands the player controlled at the
# start of this turn" (engine/phases/upkeep_effects.py). The coupling is
# implicit in the handler, so it is written down here rather than left to be
# rediscovered — and it is the reason an unnamed X may never lower to this kind.
_BOARD_COUNT_DAMAGE: dict[str, tuple[str, dict[str, object]]] = {
    # The direction is payload on the legacy side, so the grammar carries it
    # too — the differential compares payloads, and a bare {} here would report
    # a disagreement rather than a match. The *threshold* is no longer written
    # here: it comes off ``BoardCount.base``, because Black Vise's 4 and The
    # Rack's 3 are one arithmetic with one number changed.
    "cards_in_hand_over_base": (
        "upkeep_chosen_player_hand_overflow_damage",
        {"direction": "overflow"},
    ),
    # The mirror, and the branch the handler has computed since Black Vise
    # landed while nothing in the grammar could reach it (The Rack got there
    # through a card hook instead).
    "base_over_cards_in_hand": (
        "upkeep_chosen_player_hand_overflow_damage",
        {"direction": "deficit"},
    ),
    "untapped_lands_at_turn_start": ("deal_damage", {"amount": "x"}),
}

# Board counts whose handler needs the constant the phrase captured. Named
# rather than inferred from ``base is not None``: a count that grew an optional
# constant would otherwise start silently forwarding it to a handler that reads
# no such key.
_BOARD_COUNTS_WITH_BASE = frozenset(
    {"cards_in_hand_over_base", "base_over_cards_in_hand"}
)


def _damaged_player_is(recipients: tuple[ast.Recipient, ...], kind: str) -> bool:
    """Whether the damage lands on exactly one player reference of *kind*."""
    return (
        len(recipients) == 1
        and isinstance(recipients[0], ast.PlayerRef)
        and recipients[0].kind == kind
    )


def _lower_counted_damage(node: ast.DealDamage) -> tuple[OracleInstruction, ...]:
    """"…deals damage to that player equal to the number of Swamps they control."
    (Karma.)

    Both halves are checked, not just the count: the handler damages the player
    whose upkeep is resolving, so lowering a clause that damages someone else
    onto it would hit the wrong seat while the card still reported as supported.
    """
    assert isinstance(node.amount, ast.CountOf)
    if (
        node.amount.filter == _SWAMPS_THEY_CONTROL
        and _damaged_player_is(node.recipients, "that_player")
        and node.riders == ast.DamageRiders()
    ):
        return (OracleInstruction("deal_damage_equal_to_swamps", "", {}),)
    # "…deals damage to any target equal to the number of Dogs you control."
    # (Rin and Seri, Inseparable.) The general form, through the one counting
    # evaluator every other computed amount already uses — Karma's fused kind
    # above stays because its *recipient* is the upkeep's player rather than a
    # chosen target, which is not something this shape can express.
    if node.riders != ast.DamageRiders():
        raise LoweringError("a counted damage carries no riders yet", node=node)
    if len(node.recipients) != 1:
        raise LoweringError("a counted damage reaches one recipient", node=node)
    recipient = node.recipients[0]
    # "any target" (CR 115.4) is a quantifier of its own, not a narrower
    # "target": it admits a player, a planeswalker or a creature, which is
    # exactly what `deal_damage`'s resolver already picks between.
    if not (
        _is_target(recipient)
        or (isinstance(recipient, ast.TargetSpec)
            and recipient.quantifier == "any_target")
        or (isinstance(recipient, ast.PlayerRef)
            and recipient.kind in ("target_player", "target_opponent"))
    ):
        raise LoweringError("no handler aims this counted damage", node=node)
    payload: dict[str, object] = {
        "amount": "x", X_FROM_COUNT: count_spec(node.amount.filter, node),
    }
    _describe_targets(payload, recipient)
    return (OracleInstruction("deal_damage", "", payload),)


def _lower_board_count_damage(node: ast.DealDamage) -> tuple[OracleInstruction, ...]:
    """Damage sized by a named board count (Black Vise, Power Surge)."""
    assert isinstance(node.amount, ast.BoardCount)
    found = _BOARD_COUNT_DAMAGE.get(node.amount.name)
    if found is None:
        raise LoweringError(
            f"nothing computes the {node.amount.name!r} count", node=node
        )
    # Both handlers damage the player whose upkeep is resolving — they take the
    # seat from the upkeep context, not from the instruction — so a clause
    # aimed anywhere else has no handler.
    if not _damaged_player_is(node.recipients, "that_player"):
        raise LoweringError("this counted damage only reaches 'that player'", node=node)
    if node.riders != ast.DamageRiders():
        raise LoweringError("no counted-damage handler carries damage riders", node=node)
    kind, payload = found
    payload = dict(payload)
    if node.amount.name in _BOARD_COUNTS_WITH_BASE:
        if node.amount.base is None:
            raise LoweringError(
                f"the {node.amount.name!r} count needs the constant it "
                "subtracts against",
                node=node,
            )
        payload["base"] = node.amount.base
    return (OracleInstruction(kind, "", payload),)


def _lower_damage_unless_pay(
    node: ast.DamageUnlessPay, event: str | None
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
    if not _is_you(node.payer):
        raise LoweringError(
            "both pay-or-else flows offer the cost to the ability's controller", node=node
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

    # `self_damage_unless_pay` puts a single generic number on the prompt, so a
    # coloured cost would be silently charged as {0}.
    pips = dict(node.cost.pips)
    generic = int(pips.pop("generic", 0))
    if pips:
        raise LoweringError(
            "the optional-pay prompt reads one generic cost, not coloured mana", node=node
        )
    return (
        OracleInstruction("self_damage_unless_pay", "", {"amount": amount, "cost": generic}),
    )


def _fused_prepare_then_interact(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"<do something to target 1>. Then <target 1> <fights|bites> target 2."
    (Primal Might, Hunter's Edge.)

    One instruction, because the second sentence's subject **is** the first
    sentence's target: "Then **it** fights…" and "Then **that creature** deals
    damage…" name a creature nobody picks a second time. Lowered as two steps
    the pair compiles cleanly and does the wrong thing — Primal Might did,
    pumping whichever creature its single picker offered and then fighting
    nobody (round 39).

    The two slots are *differently* restricted ("target creature you control",
    "target creature you don't control"), which is what the per-slot `filters`
    of round 40 are for.

    Returning None rather than raising leaves a near-miss to the ordinary step
    lowering, which refuses it by name.
    """
    if len(steps) != 2:
        return None
    setup, interaction = steps

    if isinstance(setup, ast.Pump):
        first = setup.subject
        if setup.duration.kind not in _REST_OF_TURN or setup.power_negative:
            return None
        prepare: dict[str, object] = {
            "kind": "pump",
            "power": _amount_payload(setup.power),
            "toughness": _amount_payload(setup.toughness),
        }
    elif isinstance(setup, ast.PutCounter):
        first = setup.subject
        if setup.counter != "+1/+1" or setup.up_to or setup.then_double:
            return None
        if not isinstance(setup.count, ast.Fixed) or setup.count.value != 1:
            return None
        prepare = {"kind": "counter"}
    else:
        return None

    if isinstance(interaction, ast.Fight):
        subject, second, mode = interaction.subject, interaction.opponent, "fight"
    elif isinstance(interaction, ast.DealDamage):
        # "…deals damage equal to its power to <target 2>" — the one-way half.
        if (
            not isinstance(interaction.amount, ast.ThatMuch)
            or interaction.amount.source != "its_power"
            or len(interaction.recipients) != 1
            or interaction.riders != ast.DamageRiders()
        ):
            return None
        subject, second, mode = (
            interaction.source, interaction.recipients[0], "bite"
        )
    else:
        return None

    # The second sentence has to be *about* the first one's target: either the
    # bare "it"/self reference or the bound "that <noun>". Anything else names
    # something this instruction does not resolve.
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier not in (
        "this", "it", "that"
    ):
        return None
    if subject.quantifier in ("this", "it") and not subject.filter.is_source:
        return None
    if not _is_target(first) or not _is_target(second):
        return None
    assert isinstance(first, ast.TargetSpec) and isinstance(second, ast.TargetSpec)
    return (
        OracleInstruction(
            "prepare_then_interact", "",
            {
                "prepare": prepare,
                "mode": mode,
                "targets": {
                    "quantifier": "target",
                    "kind": "object",
                    "filter": _filter_payload(first.filter),
                    "filters": [
                        _filter_payload(first.filter),
                        _filter_payload(second.filter),
                    ],
                    "count": 2,
                },
            },
        ),
    )


def _lower_fight(
    node: ast.Fight, whole_effect: bool = True
) -> tuple[OracleInstruction, ...]:
    """"This creature fights another target creature." (Brash Taunter.)

    Only the shape where the ability's own source is one of the two fighters:
    the other is a chosen target, so one picker answers the whole clause. A
    fight between *two* chosen creatures picks twice and is a different
    instruction; refusing it here keeps the difference visible rather than
    quietly fighting the source instead.

    ``whole_effect`` is what separates the two spellings of "it". On a
    permanent's own ability it is the source; as the *second sentence* of a
    spell — "Target creature you control gets +X/+X … **Then it** fights up to
    one target creature you don't control" (Primal Might) — it back-references
    the target the first sentence chose, and a sorcery has no source permanent
    at all. Lowered as this instruction, Primal Might pumped whichever creature
    the single picker offered and then fought nobody: supported, and doing
    something else. The fused two-target pair is what that card wants.
    """
    if not whole_effect:
        raise LoweringError(
            "\"it fights\" after another sentence names that sentence's target, "
            "which needs the two-target fused pair",
            node=node,
        )
    if not _is_source(node.subject):
        raise LoweringError(
            "only a fight with the ability's own source has a handler", node=node
        )
    if not _is_target(node.opponent):
        raise LoweringError("the creature fought must be a chosen target", node=node)
    assert isinstance(node.opponent, ast.TargetSpec)
    payload: dict[str, object] = {
        "exclude_self": bool(node.opponent.filter.other_than_source),
    }
    _describe_targets(payload, node.opponent)
    return (OracleInstruction("source_fights_target", "", payload),)


def _lower_damage(
    node: ast.DealDamage,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    if isinstance(node.amount, ast.CountOf):
        return _lower_counted_damage(node)
    if isinstance(node.amount, ast.BoardCount):
        return _lower_board_count_damage(node)
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
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and _is_source(node.source)
        and len(node.recipients) == 1
        and _is_target(node.recipients[0])
    ):
        assert isinstance(node.recipients[0], ast.TargetSpec)
        payload: dict[str, object] = {}
        _describe_targets(payload, node.recipients[0])
        payload["filter"] = _filter_payload(node.recipients[0].filter)
        return (OracleInstruction("source_bites_target", "", payload),)

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
        # The sweep handlers take a plain number. A back-reference reaching one
        # would be dropped here and dealt as zero — visible nowhere, since the
        # card would still report supported — so it refuses instead.
        if back_reference or bonus:
            raise LoweringError(
                "a board sweep cannot carry a computed damage amount", node=node
            )
        return (OracleInstruction(sweep, "", {"amount": amount}),)

    if len(node.recipients) != 1:
        raise LoweringError("multi-recipient damage without a sweep shape", node=node)

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

    # Divided damage (Fireball) picks its targets at cast time and carries them
    # on the stack item, so the noun phrase here is "any number of targets"
    # rather than a resolvable recipient. The *handler* therefore needs nothing
    # from the recipient — but the caster still has to be prompted for the
    # targets, and "deal_damage {amount: x}" alone cannot say so: it is the same
    # payload Lightning Bolt produces. Recording the division here is what lets
    # engine/targeting.py raise the divided prompt from the compiled program
    # rather than from a "divided" substring in legality.py.
    if node.riders.divided:
        payload["targets"] = {"quantifier": "divided", "kind": "divided"}
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
            payload["recipient"] = "event_subject_controller"
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
    elif isinstance(recipient, ast.TargetSpec) and recipient.quantifier not in (
        "any_target", "target", "this"
    ):
        raise LoweringError("unsupported damage target quantifier", node=node)

    targets = _targets_payload(recipient)
    if targets is not None:
        payload["targets"] = targets
    return (OracleInstruction("deal_damage", "", payload),)


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
