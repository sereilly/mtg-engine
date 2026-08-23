"""Lowering damage, and preventing it.

Plain damage, the counted and board-count variants whose arithmetic a dedicated
handler performs in full, the "unless they pay" shape, damage conjunctions, and
the CR 615 prevention shields.

`deal_damage` is the one instruction that records a value other steps can read
(`_PRODUCES` in `categories.py`), which is why "deal damage, then gain that much
life" is two instructions in a sequence rather than a fused kind.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ...oracle_types import X_FROM_COUNT
from ._common import (
    _EVENT_SUBJECT_CONTROLLERS,
    _REST_OF_TURN,
    _describe_several_targets,
    _names_several_targets,
    count_spec,
    _amount_payload,
    _describe_targets,
    _filter_payload,
    _restrictions_beyond,
    _full_mana_payload,
    _back_reference_payload,
    _is_source,
    _is_target,
    _is_you,
    _targets_payload,
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
    # The threshold and the direction are payload on the legacy side, so the
    # grammar carries them too — the differential compares payloads, and a
    # bare {} here would report a disagreement rather than a match.
    "cards_in_hand_minus_four": (
        "upkeep_chosen_player_hand_overflow_damage",
        {"base": 4, "direction": "overflow"},
    ),
    "untapped_lands_at_turn_start": ("deal_damage", {"amount": "x"}),
}


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
    return (OracleInstruction(kind, "", dict(payload)),)


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
        amount = _amount_payload(node.amount)

    sweep = _sweep_kind(node.recipients)
    if sweep is not None:
        # The sweep handlers take a plain number. A back-reference reaching one
        # would be dropped here and dealt as zero — visible nowhere, since the
        # card would still report supported — so it refuses instead.
        if back_reference:
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
        if recipient.kind == "that_player" and event in _EVENT_SUBJECT_CONTROLLERS:
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


def _lower_prevent_damage(node: ast.PreventDamage) -> tuple[OracleInstruction, ...]:
    """"Prevent the next N damage …" and the Circle-of-Protection shield.

    One handler, `grant_prevention_shield`, with the recipient encoded as two
    booleans it reads. They are not interchangeable: `to_self` shields the
    ability's controller, `to_source` the permanent the ability is on, and
    neither shields a chosen target — so the recipient decides the payload
    rather than being dropped.
    """
    recipient = node.to
    if isinstance(node.amount, ast.AllOf):
        return _lower_prevent_all(node)
    if node.combat_only:
        # Only the blanket form above has a combat-scoped handler.
        # `grant_prevention_shield` counts damage of any kind, so lowering a
        # "prevent the next N combat damage" onto it would also eat N damage
        # from a burn spell.
        raise LoweringError("no counted shield is scoped to combat damage", node=node)
    if node.from_filter is not None:
        # Colour-scoped whole-instance shield. The handler keys on the colour;
        # a shield against an uncoloured "source of your choice" (Reverse
        # Damage) is a different handler entirely, so refuse rather than emit a
        # colourless Circle of Protection.
        colours = node.from_filter.colors
        card_types = node.from_filter.card_types
        if len(colours) + len(card_types) != 1:
            raise LoweringError("no handler for this source-scoped shield", node=node)
        if not _is_you(recipient):
            raise LoweringError("colour-scoped shields only protect their controller", node=node)
        if card_types:
            # Circle of Protection: Artifacts. Same instruction, same handler,
            # same band — the shield records a card type where the colour
            # Circles record a colour, and CR 615.9 rechecks whichever one it
            # holds.
            return (
                OracleInstruction(
                    "grant_prevention_shield", "",
                    {
                        "amount": 1,
                        "protection_kind": "source_type",
                        "prevention_source_type": card_types[0],
                    },
                ),
            )
        return (
            OracleInstruction(
                "grant_prevention_shield", "",
                {"amount": 1, "protection_kind": "color", "prevention_color": colours[0]},
            ),
        )

    payload: dict[str, object] = {
        "amount": _amount_payload(node.amount),
        "to_self": bool(_is_you(recipient)),
        "to_source": bool(_is_source(recipient)),
    }
    if payload["to_self"] or payload["to_source"]:
        return (OracleInstruction("grant_prevention_shield", "", payload),)
    # A chosen recipient. The handler's last branch calls
    # `apply_prevention_shield(game, target, target_permanent_index, …)`, which
    # shields the chosen *permanent* when one was picked and the chosen
    # *player* when none was — so "to target player" and "to target creature"
    # are the same instruction, and both are honoured. A quantifier other than
    # "target"/"any target" is not: nothing enumerates a shield per member of a
    # set.
    if isinstance(recipient, ast.PlayerRef):
        if recipient.kind not in ("target_player", "target_opponent"):
            raise LoweringError("no handler for this prevention recipient", node=node)
        _describe_targets(payload, recipient)
        return (OracleInstruction("grant_prevention_shield", "", payload),)
    if not isinstance(recipient, ast.TargetSpec) or recipient.quantifier not in ("target", "any_target"):
        raise LoweringError("no handler for this prevention recipient", node=node)
    _describe_targets(payload, recipient)
    return (OracleInstruction("grant_prevention_shield", "", payload),)


def _lower_prevent_all(node: ast.PreventDamage) -> tuple[OracleInstruction, ...]:
    """"Prevent all combat damage that would be dealt this turn." (Fog.)

    ``prevent_all_combat_damage`` sets one turn-wide flag
    (``game.combat_damage_prevented_until_eot``) that
    ``prevention._prevent_all_combat_damage`` reads on every damage event whose
    ``combat`` flag is set. That is the entirety of its contract, and it takes
    an empty payload — so every narrowing the sentence could carry is something
    the handler would ignore, and each one is checked here instead of dropped:

    * not combat-scoped — the flag only sees combat damage, so lowering
      "prevent all damage that would be dealt this turn" onto it would leave
      every burn spell going through while the card reported as supported;
    * a recipient — the flag is global, so a shield written for one creature or
      one player would silently protect the whole table (Desert Nomads);
    * a source filter — same reason, in the other direction;
    * a duration other than this turn — the flag is cleared in the cleanup step,
      so it *is* "this turn" and nothing else.
    """
    if not node.combat_only:
        raise LoweringError("no handler prevents all damage of every kind", node=node)
    if node.dealt_by is not None:
        # "…dealt **by** target creature this turn" (Horn of Deafening, Lady
        # Evangela). A shield on the damage's *source*, which is why it is a
        # different instruction from every branch below: those protect a
        # recipient, and a creature whose damage is prevented is still perfectly
        # able to be dealt damage itself.
        if node.to is not None:
            raise LoweringError(
                "no handler shields a recipient and a source at once", node=node
            )
        if node.duration.kind not in _REST_OF_TURN:
            raise LoweringError(
                "the directional combat shield lasts exactly this turn", node=node
            )
        if not isinstance(node.dealt_by, ast.TargetSpec) or node.dealt_by.quantifier != "target":
            raise LoweringError(
                "no handler prevents the damage of an untargeted source", node=node
            )
        payload: dict[str, object] = {}
        _describe_targets(payload, node.dealt_by)
        return (
            OracleInstruction("prevent_combat_damage_by_target_until_eot", "", payload),
        )
    if node.to is not None:
        # "…to Dogs you control" (Pack Leader). A *set* named by a printed noun
        # phrase, which the scoped record can carry and re-match when damage
        # would be dealt; anything else — one player, one creature, a chosen
        # target — is a shield on one recipient and stays refused, because the
        # record covers whoever matches rather than whoever was there.
        if (
            isinstance(node.to, ast.TargetSpec)
            and not node.to.targeted
            and node.to.quantifier in ("all", "each")
            and node.to.filter.controller == "you"
        ):
            if node.duration.kind not in _REST_OF_TURN:
                raise LoweringError(
                    "the scoped combat-damage record lasts exactly this turn",
                    node=node,
                )
            leftover = _restrictions_beyond(
                node.to.filter,
                frozenset({"card_types", "subtypes", "controller", "type_match"}),
            )
            if leftover:
                raise LoweringError(
                    "the scoped prevention cannot narrow by: " + ", ".join(leftover),
                    node=node,
                )
            return (
                OracleInstruction(
                    "prevent_all_combat_damage_to_matching", "",
                    {"filter": _filter_payload(node.to.filter)},
                ),
            )
        raise LoweringError(
            "prevent_all_combat_damage is turn-wide; no handler scopes a blanket "
            "prevention to one recipient",
            node=node,
        )
    if node.from_filter is not None:
        raise LoweringError(
            "no handler scopes a blanket prevention to a source", node=node
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "the combat-damage flag lasts exactly this turn", node=node
        )
    return (OracleInstruction("prevent_all_combat_damage", "", {}),)
