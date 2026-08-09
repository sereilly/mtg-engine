"""Lower a parsed AST into ``OracleInstruction`` sequences.

The grammar deliberately stops at the IR rather than interpreting the AST
directly against game state. Three reasons:

1. The 121 registered effect handlers encode game-rule behavior that is
   orthogonal to parsing — CR 608.2b fizzling, state-based-action batching,
   replacement-effect dispatch, divided-damage arithmetic. Re-implementing that
   inside an AST interpreter would regress it.
2. ``OracleInstruction`` has many consumers beyond resolution: ``ai_policy``
   scores by instruction kind, ``StackItem`` carries instructions,
   ``trigger_utils`` filters on them, the web layer serializes them. Keeping the
   IR stable isolates the parser rewrite from the AI and UI at the same time.
3. Strangler-fig migration needs the old and new front ends to be *comparable*.
   Both emit instructions, so "grammar agrees with the legacy rules" is a
   dataclass equality check rather than a full game simulation.

Payload keys reproduce what the legacy rules have always emitted, byte for
byte; anything new is additive and read with ``payload.get`` defaults on the
handler side.
"""

from __future__ import annotations

import dataclasses

from ..oracle_types import OracleInstruction
from . import ast
from .errors import LoweringError

# Which migration category each lowered instruction belongs to. The gate in
# engine/grammar/__init__.py turns categories on one at a time; an instruction
# whose kind is missing here can be lowered but never gated on, which is a bug
# the ratchet surfaces rather than a silent fallback.
INSTRUCTION_CATEGORIES: dict[str, str] = {
    "deal_damage": "damage",
    "earthquake_damage": "damage",
    "hurricane_damage": "damage",
    "deal_damage_each_creature_and_player": "damage",
    "deal_damage_each_attacking_creature": "damage",
    "deal_damage_and_opponent_choice": "damage",
    "self_damage_unless_pay": "damage",
    # Dispatched by the (trigger condition, instruction kind) registry in
    # engine/phases/upkeep_effects.py rather than by EFFECT_HANDLERS, so they
    # share the category of the other upkeep pay-or-else shapes.
    "upkeep_pay_or_deal_damage_to_controller": "upkeep",
    "upkeep_chosen_player_hand_overflow_damage": "upkeep",
    "deal_damage_equal_to_swamps": "upkeep",
    "pump_target_creature_until_eot": "pump",
    "pump_self": "pump",
    "pump_enchanted_creature": "pump",
    "buff_creatures_global": "pump",
    "set_base_pt_target_until_eot": "pump",
    "grant_target_flying_until_eot": "pump",
    "grant_self_flying_until_eot": "pump",
    "grant_banding_to_target": "pump",
    "add_counter_to_self": "pump",
    # Counter placements sized by a board count. Their own category rather than
    # "pump": a corpse counter never touches power or toughness (it is
    # regeneration fuel), so gating it behind the pump switch would tie two
    # unrelated migrations together. Keeping it out of the differential's
    # MIGRATED_CATEGORIES also means these two lines stay compared against the
    # legacy rules for as long as those rules exist.
    "add_corpse_counters_for_each_creature_died": "counters",
    "add_plus1_counters_for_each_creature_died": "counters",
    "draw_then_discard_self": "zones",
    "target_gains_life": "life",
    "target_loses_life": "life",
    "destroy_target_permanent": "destruction",
    "destroy_all_creatures": "destruction",
    "destroy_all_enchantments": "destruction",
    "destroy_all_lands": "destruction",
    "destroy_all_lands_of_type": "destruction",
    "destroy_all_artifacts_creatures_enchantments": "destruction",
    "tap_target_permanent": "tapping",
    "untap_target_permanent": "tapping",
    "untap_target_land": "tapping",
    "untap_self": "tapping",
    "untap_enchanted_creature": "tapping",
    "grant_prevention_shield": "prevention",
    "prevent_all_combat_damage": "prevention",
    "recolor_target_from_text": "recolor",
    "sacrifice_self": "zones",
    "upkeep_pay_or_sacrifice_enchantment": "upkeep",
    "upkeep_pay_or_sacrifice_self": "upkeep",
    "discard_target_cards": "zones",
    "discard_x_target_cards": "zones",
    "grant_regeneration_to_target_creature": "regeneration",
    "grant_regeneration_to_self": "regeneration",
    "grant_regeneration_to_enchanted_creature": "regeneration",
    # "Target creature can't be regenerated this turn" is the negative half of
    # the same subject, so it shares the category rather than minting one that
    # would always be switched on and off alongside it.
    "deny_regeneration_to_target": "regeneration",
    # Looking at a hand reads a hidden zone; the legacy rule and the handler
    # both live in the engine's zones modules.
    "look_at_target_hand": "zones",
    # A library search moves a card between hidden zones — same module, same
    # category as the other zone-change handlers.
    "search_library": "zones",
    "grant_extra_turn": "turns",
    "grant_unblockable_to_low_power_target": "evasion",
    # Restrictions on declaring attackers/blockers (CR 506, 509).
    "cant_attack_without_land_type": "combat_restrictions",
    "cant_block_power_n_or_greater": "combat_restrictions",
    "counter_top_stack_spell": "counterspells",
    "tap_or_untap_target": "tapping",
    "draw_target_cards": "zones",
    "draw_controller_cards": "zones",
    "return_creature_from_graveyard_to_hand": "zones",
    "reanimate_creature": "zones",
    "bounce_target_creature": "zones",
    "add_mana_from_text": "mana",
    "create_token": "tokens",
    # Optional actions. Parsed and lowered, not switched on — see _WRAPPER_KINDS.
    "may": "optional",
}


def _filter_payload(filt: ast.ObjectFilter) -> dict[str, object]:
    """A filter's payload, refusing shapes no handler implements."""
    payload = filt.to_payload()
    if "type_filter_all" in payload:
        raise LoweringError(
            "no handler matches a permanent that is several types at once", node=filt
        )
    # `to_payload` cannot express a zone, so every handler reached through here
    # searches the battlefield. Emitting a graveyard-scoped filter as a plain
    # one would point the handler — and engine/targeting.py's picker — at the
    # wrong zone entirely, so the whole line is refused instead. Effects that
    # genuinely move cards between zones read the filter directly.
    if filt.zone != "battlefield" or filt.is_card:
        raise LoweringError(
            f"no handler reads a filter scoped to the {filt.zone}", node=filt
        )
    if filt.mana_value is not None:
        # ``to_payload`` has no key for a mana-value restriction and
        # ``permanent_matches_filter`` cannot test one, so every handler reached
        # through this function would ignore it. The one card that restricts by
        # mana value is a counterspell, whose own lowering reads the field
        # directly; anything else must refuse rather than widen its effect to
        # every mana value.
        raise LoweringError("no handler filters on mana value", node=filt)
    return payload


def _restrictions_beyond(
    filt: ast.ObjectFilter, honoured: frozenset[str]
) -> tuple[str, ...]:
    """Names of *filt*'s non-default fields that *honoured* does not cover.

    Written against the dataclass rather than a hand-listed tuple of the fields
    known today: a restriction added to ``ObjectFilter`` later is then refused
    by default, instead of being quietly ignored by every lowering that was
    written before it existed. Silently widening an effect is the failure mode
    worth engineering against — a card that refuses is visibly unsupported.
    """
    default = ast.ObjectFilter()
    return tuple(
        field.name
        for field in dataclasses.fields(filt)
        if field.name not in honoured
        and getattr(filt, field.name) != getattr(default, field.name)
    )


# Payload keys the grammar emits that no legacy rule produces and no existing
# handler reads. They are additive *descriptions* of what a line targets, kept
# so the engine can answer "what does this spell target?" from the compiled
# program instead of re-reading oracle text (engine/targeting.py replacing
# engine/legality.py). The grammar-vs-legacy differential compares payloads
# with these removed — a key nothing consumes cannot change behaviour, and
# treating it as a divergence would mean an ACCEPTED_DIFFS entry per migrated
# card, which would gut the ratchet.
GRAMMAR_ONLY_PAYLOAD_KEYS = frozenset({"targets"})


def _describe_targets(payload: dict[str, object], recipient: ast.Recipient) -> None:
    """Record what *recipient* refers to on *payload*, if it names a target."""
    described = _targets_payload(recipient)
    if described is not None:
        payload["targets"] = described


def _targets_only(recipient: ast.Recipient) -> dict[str, object]:
    """A payload carrying nothing but the target description — for handlers
    whose behaviour takes no filter but whose *card* still targets."""
    payload: dict[str, object] = {}
    _describe_targets(payload, recipient)
    return payload


def _targets_payload(recipient: ast.Recipient) -> dict[str, object] | None:
    """A description of what *recipient* refers to, for engine/targeting.py.

    Only the shapes that name a cast-time target are described. "You" and
    "each player" are not targets at all (CR 115.10b), so they get no entry
    rather than a misleading one.
    """
    if isinstance(recipient, ast.PlayerRef):
        if recipient.kind == "target_player":
            return {"quantifier": "target", "kind": "player"}
        return None
    if not isinstance(recipient, ast.TargetSpec):
        return None
    if recipient.quantifier == "any_target":
        return {"quantifier": "any_target", "kind": "any"}
    if recipient.quantifier != "target":
        return None
    return {"quantifier": "target", "kind": "object", "filter": _filter_payload(recipient.filter)}


def _amount_payload(amount: ast.Amount) -> int | str:
    """Legacy payloads carry a plain int, or the string "x" for a variable."""
    if isinstance(amount, ast.Fixed):
        return amount.value
    if isinstance(amount, ast.Var):
        return amount.name
    raise LoweringError(f"unsupported quantity {type(amount).__name__}", node=amount)


def _is_source(subject: ast.Recipient) -> bool:
    return isinstance(subject, ast.TargetSpec) and subject.filter.is_source


def _is_enchanted(subject: ast.Recipient) -> bool:
    return isinstance(subject, ast.TargetSpec) and subject.filter.is_enchanted


def _is_target(subject: ast.Recipient) -> bool:
    return isinstance(subject, ast.TargetSpec) and subject.quantifier in ("target", "up_to")


def _is_you(recipient: ast.Recipient) -> bool:
    return isinstance(recipient, ast.PlayerRef) and recipient.kind == "you"


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
    "cards_in_hand_minus_four": ("upkeep_chosen_player_hand_overflow_damage", {}),
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
    raise LoweringError("no handler computes this counted damage", node=node)


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


def _lower_damage(node: ast.DealDamage) -> tuple[OracleInstruction, ...]:
    if isinstance(node.amount, ast.CountOf):
        return _lower_counted_damage(node)
    if isinstance(node.amount, ast.BoardCount):
        return _lower_board_count_damage(node)
    amount = _amount_payload(node.amount)

    sweep = _sweep_kind(node.recipients)
    if sweep is not None:
        return (OracleInstruction(sweep, "", {"amount": amount}),)

    if len(node.recipients) != 1:
        raise LoweringError("multi-recipient damage without a sweep shape", node=node)

    recipient = node.recipients[0]
    payload: dict[str, object] = {"amount": amount}
    if node.riders.no_regen:
        payload["no_regen"] = True
    if node.riders.exile_if_dies:
        payload["exile_if_dies"] = True

    # Divided damage (Fireball) picks its targets at cast time and carries them
    # on the stack item, so the noun phrase here is "any number of targets"
    # rather than a resolvable recipient.
    if node.riders.divided:
        return (OracleInstruction("deal_damage", "", payload),)

    # Damage aimed at the source's own controller rather than the spell's
    # target. `deal_damage` reads this the same way `target_gains_life`
    # already reads its "recipient" key.
    if _is_you(recipient):
        payload["recipient"] = "caster"
    elif isinstance(recipient, ast.PlayerRef) and recipient.kind not in (
        "target_player", "that_player", "controller", "each_player"
    ):
        raise LoweringError(f"unsupported damage recipient {recipient.kind!r}", node=node)
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


# ---------------------------------------------------------------------------
# Power / toughness
# ---------------------------------------------------------------------------


def _signed(amount: ast.Amount, negative: bool) -> int | str:
    value = _amount_payload(amount)
    if negative and isinstance(value, int):
        return -value
    if negative:
        raise LoweringError("negative variable pump is not supported", node=amount)
    return value


def _lower_pump(node: ast.Pump) -> tuple[OracleInstruction, ...]:
    power = _signed(node.power, node.power_negative)
    toughness = _signed(node.toughness, node.toughness_negative)

    if node.duration.kind is None:
        raise LoweringError("continuous pump needs the CR 613 layers engine", node=node)

    if _is_enchanted(node.subject):
        return (
            OracleInstruction(
                "pump_enchanted_creature", "", {"power": power, "toughness": toughness}
            ),
        )
    if _is_source(node.subject):
        return (OracleInstruction("pump_self", "", {"power": power, "toughness": toughness}),)
    if _is_target(node.subject):
        assert isinstance(node.subject, ast.TargetSpec)
        payload: dict[str, object] = {"power": power, "toughness": toughness}
        payload["blocking_only"] = bool(node.subject.filter.blocking)
        _describe_targets(payload, node.subject)
        return (OracleInstruction("pump_target_creature_until_eot", "", payload),)

    # "White creatures get +1/+1", "Attacking creatures get +2/+0 until end of turn"
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier == "all":
        filt = node.subject.filter
        if filt.card_types != ("creature",):
            raise LoweringError("global buff on a non-creature scope", node=node)
        payload = {"power": power, "toughness": toughness}
        if filt.colors:
            payload["color"] = filt.colors[0]
        payload["all"] = filt.controller != "you"
        if filt.attacking:
            payload["attacking_only"] = True
        if filt.blocking:
            payload["blocking_only"] = True
        return (OracleInstruction("buff_creatures_global", "", payload),)

    raise LoweringError("unsupported pump subject", node=node)


def _lower_set_base_pt(node: ast.SetBasePT) -> tuple[OracleInstruction, ...]:
    if node.duration.kind != "until_end_of_turn":
        raise LoweringError("base P/T change needs an end-of-turn duration", node=node)
    if not _is_target(node.subject):
        raise LoweringError("base P/T change on a non-target subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    filt = node.subject.filter
    payload: dict[str, object] = {
        "power": _amount_payload(node.power) if node.power is not None else None,
        "toughness": _amount_payload(node.toughness) if node.toughness is not None else None,
        "exclude_self": filt.other_than_source,
    }
    if node.toughness is None:
        payload["attacking_only"] = bool(filt.attacking)
        payload["flying_only"] = filt.with_keywords == ("flying",)
    return (OracleInstruction("set_base_pt_target_until_eot", "", payload),)


_KEYWORD_GRANTS: dict[tuple[str, str], str] = {
    ("flying", "target"): "grant_target_flying_until_eot",
    ("flying", "self"): "grant_self_flying_until_eot",
    ("banding", "target"): "grant_banding_to_target",
}


def _lower_gain_keyword(node: ast.GainKeyword) -> tuple[OracleInstruction, ...]:
    if node.duration.kind is None:
        raise LoweringError("continuous keyword grant needs the CR 613 layers engine", node=node)
    if len(node.keywords) != 1:
        raise LoweringError("multi-keyword grant has no instruction kind", node=node)
    scope = "self" if _is_source(node.subject) else ("target" if _is_target(node.subject) else None)
    if scope is None:
        raise LoweringError("unsupported keyword-grant subject", node=node)
    kind = _KEYWORD_GRANTS.get((node.keywords[0], scope))
    if kind is None:
        raise LoweringError(f"no handler for granting {node.keywords[0]!r} to {scope}", node=node)
    return (OracleInstruction(kind, "", {}),)


def _lower_put_counter(node: ast.PutCounter) -> tuple[OracleInstruction, ...]:
    if not _is_source(node.subject):
        raise LoweringError("counters on a non-source subject", node=node)
    if node.counter != "+1/+1" or node.up_to:
        raise LoweringError(f"no handler for {node.counter} counters", node=node)
    if not isinstance(node.count, ast.Fixed) or node.count.value != 1:
        raise LoweringError("variable counter counts have no handler", node=node)
    return (OracleInstruction("add_counter_to_self", "", {"power": 1, "toughness": 1}),)


# Counter placements repeated once per creature that died this turn, keyed by
# the counter's printed name — the only thing that differs between the two
# cards written this way, and what decides which handler runs. Both handlers
# read the death count from the trigger's own context rather than from the
# payload, so the payloads here are the legacy rules' literals and nothing
# more.
_PER_DEATH_COUNTERS: dict[str, tuple[str, dict[str, object]]] = {
    # Scavenging Ghoul — regeneration fuel, spent by its own activated ability.
    "corpse": ("add_corpse_counters_for_each_creature_died", {}),
    # Khabál Ghoul — P/T counters.
    "+1/+1": ("add_plus1_counters_for_each_creature_died", {"power": 1, "toughness": 1}),
}

# The exact subject both handlers act on. Compared for equality rather than
# probed field by field, so a filter field added to the AST later refuses by
# default instead of being ignored by a lowering written before it existed.
_PER_DEATH_SUBJECT = ast.TargetSpec(
    "this", ast.ObjectFilter(card_types=("creature",), is_source=True)
)

# Both handlers count *every* creature that died, with no narrowing available
# to them, so any filtered set has to refuse rather than over-count.
_ANY_CREATURE_DIED = ast.DiedThisTurn(ast.ObjectFilter(card_types=("creature",)))


def _lower_for_each(node: ast.ForEach) -> tuple[OracleInstruction, ...]:
    """"…put a <kind> counter on this creature for each creature that died this
    turn." (Scavenging Ghoul, Khabál Ghoul.)

    The legacy registry needed a whole-sentence substring rule per card, and the
    +1/+1 one carries a comment saying it must out-rank the plain "put a +1/+1
    counter on this creature" rule — which sits 96,500 order slots away, because
    the two rules are unrelated except that one is a prefix of the other. Losing
    that race would drop the per-death scaling and put down a single counter.
    Here the "for each …" clause is a node, so the two shapes are simply
    different ASTs and there is no race to lose.

    Everything else refuses, because neither handler reads anything from its
    payload: the subject, the multiplier and the counted set are all fixed in
    the handler's own source, so a clause differing in any of them would be
    executed as if it had not.
    """
    if node.iterator != _ANY_CREATURE_DIED:
        raise LoweringError("no handler repeats an effect over this set", node=node)
    placement = node.effect
    if not isinstance(placement, ast.PutCounter):
        raise LoweringError("no handler repeats this effect per death", node=node)
    if placement.subject != _PER_DEATH_SUBJECT:
        raise LoweringError(
            "the per-death counter handlers only ever reach their own source", node=node
        )
    if placement.up_to or placement.count != ast.Fixed(1):
        raise LoweringError("no handler places more than one counter per death", node=node)
    found = _PER_DEATH_COUNTERS.get(placement.counter)
    if found is None:
        raise LoweringError(
            f"no handler places {placement.counter!r} counters per death", node=node
        )
    kind, payload = found
    return (OracleInstruction(kind, "", dict(payload)),)


# ---------------------------------------------------------------------------
# Life
# ---------------------------------------------------------------------------


def _lower_gain_life(
    node: ast.GainLife, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    recipient = "caster" if node.player.kind == "you" else "target"
    if isinstance(node.amount, ast.ThatMuch):
        # "You gain life equal to the damage dealt" — reads the value the
        # preceding damage instruction recorded in the resolution scratchpad,
        # which is what lets the two effects be separate instructions at all.
        #
        # That only holds when the producer is in *this* resolution. On a
        # triggered ability ("Whenever this creature deals damage, you gain that
        # much life") the amount comes from the trigger's captured event, which
        # is a different mechanism — so refuse rather than read an empty
        # scratchpad and silently gain 0 life.
        if node.amount.source not in produced:
            raise LoweringError(
                f"back-reference to {node.amount.source!r} with no producer in this effect",
                node=node,
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {"amount_from": node.amount.source, "recipient": recipient},
            ),
        )
    payload: dict[str, object] = {
        "amount": _amount_payload(node.amount), "recipient": recipient,
    }
    _describe_targets(payload, node.player)
    return (OracleInstruction("target_gains_life", "", payload),)


# ---------------------------------------------------------------------------
# Destruction, tapping, zones
# ---------------------------------------------------------------------------

# "Destroy all X" shapes with a dedicated sweep handler.
_DESTROY_ALL_KINDS: dict[tuple[str, ...], str] = {
    ("creature",): "destroy_all_creatures",
    ("enchantment",): "destroy_all_enchantments",
    ("land",): "destroy_all_lands",
    ("artifact", "creature", "enchantment"): "destroy_all_artifacts_creatures_enchantments",
}

_BASIC_LAND_TYPES = frozenset({"plains", "island", "swamp", "mountain", "forest"})


def _lower_destroy(node: ast.Destroy) -> tuple[OracleInstruction, ...]:
    if not isinstance(node.subject, ast.TargetSpec):
        raise LoweringError("destroy needs an object target", node=node)
    spec = node.subject
    filt = spec.filter

    if spec.quantifier in ("all", "each"):
        # "Destroy all Plains" — a basic land type, not a creature subtype.
        if filt.subtypes and not filt.card_types:
            if len(filt.subtypes) == 1 and filt.subtypes[0] in _BASIC_LAND_TYPES:
                subtype = filt.subtypes[0]
                # The handler keys on the plural form the card prints; Plains is
                # already plural.
                plural = subtype if subtype.endswith("s") else f"{subtype}s"
                return (
                    OracleInstruction(
                        "destroy_all_lands_of_type", "", {"land_type": plural},
                    ),
                )
            raise LoweringError("no sweep handler for this subtype", node=node)
        kind = _DESTROY_ALL_KINDS.get(tuple(sorted(filt.card_types)))
        if kind is None:
            raise LoweringError("no sweep handler for this destroy scope", node=node)
        payload = {"bypass_regeneration": True} if node.no_regen else {}
        return (OracleInstruction(kind, "", payload),)

    if spec.quantifier not in ("target", "up_to"):
        raise LoweringError("unsupported destroy quantifier", node=node)

    payload = _filter_payload(filt)
    if node.no_regen:
        payload["bypass_regeneration"] = True
    _describe_targets(payload, spec)
    return (OracleInstruction("destroy_target_permanent", "", payload),)


def _lower_tap(node: ast.Tap | ast.Untap) -> tuple[OracleInstruction, ...]:
    if not isinstance(node.subject, ast.TargetSpec):
        raise LoweringError("tap/untap needs an object target", node=node)
    spec = node.subject

    # "Untap this artifact" (Basalt Monolith, Mana Vault) and "untap enchanted
    # creature" have their own handlers — the source and the enchanted
    # permanent are known without a target being chosen. There is no matching
    # tap handler, so tapping those shapes still refuses.
    if isinstance(node, ast.Untap):
        if _is_source(spec):
            return (OracleInstruction("untap_self", "", {}),)
        if _is_enchanted(spec):
            return (OracleInstruction("untap_enchanted_creature", "", {}),)

    if spec.quantifier not in ("target", "up_to"):
        raise LoweringError("no handler for non-targeted tap/untap", node=node)
    payload = _filter_payload(spec.filter)

    if isinstance(node, ast.Tap):
        tap_payload = dict(payload)
        _describe_targets(tap_payload, spec)
        return (OracleInstruction("tap_target_permanent", "", tap_payload),)

    # Untap has two handlers with different reach: the generic one ignores
    # filters entirely, so a restricted untap must route to the land-specific
    # handler or refuse. Lowering "untap target land" to the generic kind would
    # let it untap a creature.
    if not payload:
        return (OracleInstruction("untap_target_permanent", "", _targets_only(spec)),)
    if payload == {"type_filter": "land"}:
        return (OracleInstruction("untap_target_land", "", _targets_only(spec)),)
    raise LoweringError("no untap handler honors this restriction", node=node)


def _reads_no_return_restriction(filt: ast.ObjectFilter) -> bool:
    """Whether *filt* carries a narrowing none of the zone-change handlers reads.

    All three take their whole instruction from the card: two read an empty
    payload and the third reads one boolean. So any adjective beyond the card
    type is invisible to them, and a filter carrying one has to refuse — "return
    target *black* creature card from your graveyard to your hand" lowered to
    Raise Dead's instruction would happily return a white one.
    """
    tri_state = (filt.tapped, filt.attacking, filt.blocking, filt.blocked)
    return bool(
        filt.supertypes or filt.subtypes or filt.colors or filt.excluded_colors
        or filt.excluded_types or filt.excluded_subtypes or filt.with_keywords
        or filt.without_keywords or filt.controller or filt.power or filt.toughness
        or filt.mana_value or filt.named or filt.other_than_source
        or filt.is_source or filt.is_enchanted
        or any(state is not None for state in tri_state)
    )


def _lower_return_to_zone(node: ast.ReturnToZone) -> tuple[OracleInstruction, ...]:
    """"Return <object> [from <zone>] to <zone>" — Raise Dead, Regrowth,
    Resurrection and Unsummon.

    The *pair* of zones picks the handler, which is why they are both parsed
    rather than pattern-matched out of the sentence: graveyard→hand,
    graveyard→battlefield and battlefield→owner's hand are three unrelated
    handlers reading three different target indices (a graveyard position, a
    graveyard position, a battlefield position). The legacy rules told them
    apart by substring, and told Raise Dead from Regrowth by probing for
    ``"creature card" not in text`` — which is why "return target artifact card
    from your graveyard to your hand" would have returned a creature.

    Nothing here is described for engine/targeting.py. The `targets` vocabulary
    names battlefield permanents, so describing a graveyard card with it would
    tell the picker to offer creatures in play for a reanimation spell — the
    exact bug the Animate Dead targeting test pins.
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "target":
        raise LoweringError("no handler for returning a non-targeted object", node=node)
    filt = subject.filter
    if _reads_no_return_restriction(filt):
        raise LoweringError("no return handler honours this restriction", node=node)

    source, destination = node.from_zone, node.to

    if source is not None and source.name == "graveyard":
        # Both graveyard handlers search the caster's own graveyard and nowhere
        # else, so "from a graveyard" is a different card, not a wording of this
        # one.
        if source.owner is None or source.owner.kind != "you":
            raise LoweringError("no handler searches a graveyard but your own", node=node)
        if not filt.is_card:
            raise LoweringError("a graveyard holds cards, not permanents", node=node)

        if destination.name == "hand":
            if destination.owner is None or destination.owner.kind != "you":
                raise LoweringError("this handler returns cards to your own hand", node=node)
            # The handler's single restriction: creature cards only, or any card.
            if filt.card_types == ("creature",):
                any_card = False
            elif not filt.card_types:
                any_card = True
            else:
                raise LoweringError("this handler reads creature-or-any, not a type", node=node)
            return (
                OracleInstruction(
                    "return_creature_from_graveyard_to_hand", "", {"any_card": any_card}
                ),
            )

        if destination.name == "battlefield":
            if destination.owner is not None:
                raise LoweringError("no handler for a reanimation under another's control", node=node)
            # `reanimate_creature` only ever puts a creature onto the
            # battlefield. Regrowth's untyped "target card" has no lowering
            # here: claiming it would silently narrow the player's choice.
            if filt.card_types != ("creature",):
                raise LoweringError("the reanimation handler only moves creature cards", node=node)
            return (OracleInstruction("reanimate_creature", "", {}),)

        raise LoweringError(f"no handler moves a card to the {destination.name}", node=node)

    if source is None and destination.name == "hand":
        # A permanent going home. `bounce_target_creature` returns it to its
        # owner's hand by construction, so "to your hand" is a different effect
        # (it matters the moment you have stolen the creature) and refuses.
        if destination.owner is None or destination.owner.kind != "owner":
            raise LoweringError("the bounce handler returns a permanent to its owner", node=node)
        if filt.is_card:
            raise LoweringError("no handler bounces a card that is not in play", node=node)
        if filt.card_types != ("creature",):
            raise LoweringError("the bounce handler only returns creatures", node=node)
        return (OracleInstruction("bounce_target_creature", "", {}),)

    raise LoweringError("no handler for this zone change", node=node)


def _lower_tap_or_untap(node: ast.TapOrUntap) -> tuple[OracleInstruction, ...]:
    """"Tap or untap target <objects>." (Twiddle.)

    ``tap_or_untap_target`` toggles whatever permanent was chosen —
    ``predicate=lambda p: True`` — so it honours no restriction at all. Any
    filter therefore has to refuse: lowering "tap or untap target creature" to
    this kind would let it untap a land, and the card would still report as
    supported. The plain ``tap_target_permanent`` handler is the one that
    filters; there is no filtered toggle.
    """
    spec = node.subject
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier != "target":
        raise LoweringError("no handler for a non-targeted tap-or-untap", node=node)
    if _filter_payload(spec.filter):
        raise LoweringError("no tap-or-untap handler honours this restriction", node=node)
    return (OracleInstruction("tap_or_untap_target", "", _targets_only(spec)),)


def _lower_regenerate(node: ast.Regenerate) -> tuple[OracleInstruction, ...]:
    """"Regenerate target creature" / "Regenerate this creature" (CR 701.19).

    Three handlers exist, differing in *what* they shield: the spell's target,
    the ability's own source, or the creature an Aura enchants. Picking by the
    subject keeps each one's contract rather than routing everything through
    the targeted one, which would shield the wrong creature.
    """
    subject = node.subject
    if _is_enchanted(subject):
        return (OracleInstruction("grant_regeneration_to_enchanted_creature", "", {}),)
    if _is_source(subject):
        return (OracleInstruction("grant_regeneration_to_self", "", {}),)
    if not (isinstance(subject, ast.TargetSpec) and subject.quantifier == "target"):
        raise LoweringError("no handler for regenerating this subject", node=node)
    filt = subject.filter
    payload: dict[str, object] = {}
    # Elephant Graveyard regenerates a *target Elephant*. The handler honours
    # exactly one restriction, `subtype_filter`; anything else it would ignore
    # must be refused rather than dropped, or the shield lands on the wrong
    # creature while the card still reports as supported.
    if filt.subtypes:
        if len(filt.subtypes) > 1:
            raise LoweringError("no handler for a multi-subtype regenerate", node=node)
        payload["subtype_filter"] = filt.subtypes[0]
    if (
        filt.colors or filt.excluded_colors or filt.excluded_types
        or filt.with_keywords or filt.without_keywords or filt.attacking or filt.blocking
    ):
        raise LoweringError("no handler honours this regenerate restriction", node=node)
    _describe_targets(payload, subject)
    return (OracleInstruction("grant_regeneration_to_target_creature", "", payload),)


# Restrictions ``counter_top_stack_spell`` reads off its own payload: the
# colour gate (the Blasts, Lifeforce, Deathgrip) and the mana-value gate
# (Spell Blast). Every other field of the noun phrase is refused by
# _restrictions_beyond, because this handler picks the spell to counter itself
# and would ignore anything it was not told to check.
_COUNTER_HONOURED_FILTER_FIELDS = frozenset({"colors", "mana_value"})

# The "unless … pays" cost the counter flow can offer. ``{X}`` is the only one:
# handlers/stack.py arms a pending payment sized from the caster's chosen X, and
# there is no flow for a fixed or coloured cost.
_COUNTER_UNLESS_PAYS_X = (("X", 1),)

# Penalties for declining that cost which the counter flow performs while it
# counters (engine/card_hooks.py ON_SPELL_COUNTERED, run from
# mixins/stack_casting._resolve_mana_payment). Declared here so a penalty the
# engine does not perform refuses instead of riding along unimplemented; the
# matching parse-coverage claim lives in HANDLER_CLAIMS in
# scripts/parse_coverage.py.
_COUNTER_PERFORMED_PENALTIES = frozenset({"tap_lands_and_empty_pool"})


def _lower_counter_spell(node: ast.CounterSpell) -> tuple[OracleInstruction, ...]:
    """"Counter target spell", with the colour, mana-value and "unless … pays"
    riders the pool's counterspells carry. The handler chooses the spell to
    counter itself, so a restriction it cannot honour must be refused rather
    than dropped — countering the wrong spell is worse than not supporting the
    card."""
    spec = node.subject
    if spec.quantifier != "target":
        raise LoweringError("no handler for a non-targeted counter", node=node)
    filt = spec.filter
    payload: dict[str, object] = {}
    if filt.colors:
        if len(filt.colors) > 1:
            raise LoweringError("no handler for a multi-colour counter filter", node=node)
        payload["color_filter"] = filt.colors[0]
    if filt.mana_value is not None:
        # Spell Blast: "counter target spell with mana value X". The handler
        # compares the X chosen on the cast against the target's mana value;
        # that equality is the only mana-value question it can ask, so a fixed
        # number or an inequality ("mana value 3 or less") has to refuse rather
        # than counter regardless of cost.
        if filt.mana_value.op != "eq" or not isinstance(filt.mana_value.value, ast.Var):
            raise LoweringError("no handler for this mana-value restriction", node=node)
        payload["mv_equals_x"] = True
    leftover = _restrictions_beyond(filt, _COUNTER_HONOURED_FILTER_FIELDS)
    if leftover:
        raise LoweringError(
            "no handler honours this counter restriction: " + ", ".join(leftover), node=node
        )

    if node.unless_pays is not None:
        if node.unless_pays.pips != _COUNTER_UNLESS_PAYS_X:
            raise LoweringError("no counter flow offers this cost", node=node)
        payload["unless_pays_x"] = True
    if node.unpaid_penalty is not None:
        if node.unless_pays is None:
            raise LoweringError("a decline penalty with no cost to decline", node=node)
        if node.unpaid_penalty not in _COUNTER_PERFORMED_PENALTIES:
            raise LoweringError(
                f"nothing performs the {node.unpaid_penalty!r} penalty", node=node
            )

    # A counterspell targets a *spell on the stack*, not a permanent. Describing
    # it with the generic object shape would tell the targeting layer to offer
    # battlefield permanents.
    payload["targets"] = {"quantifier": "target", "kind": "spell"}
    return (OracleInstruction("counter_top_stack_spell", "", payload),)


def _lower_discard(node: ast.Discard) -> tuple[OracleInstruction, ...]:
    """"Target player discards N cards [at random]."

    Only the targeted form has a handler; "you discard" and "each player
    discards" are different effects, not this one with a flag.

    **Who picks the cards is what separates the two handlers**, so "at random"
    decides which one this lowers to rather than being a rider either could
    carry. ``discard_target_cards`` raises a pending choice and lets the
    discarding player choose (Disrupting Scepter); ``discard_x_target_cards``
    takes them with ``random.sample`` (Mind Twist). Lowering an "at random"
    line onto the first would hand the victim the choice their card denies
    them, and lowering a plain discard onto the second would take it away.

    The random handler is also the *variable* one: it sizes itself from the X
    chosen as the spell was cast (``context.x_value``) and never reads the
    payload, which is why the amount is emitted only for the counted form —
    matching what the legacy rule wrote, and keeping the payload honest about
    what the handler actually consults.
    """
    if node.player.kind not in ("target_player", "that_player"):
        raise LoweringError(f"no discard handler for {node.player.kind!r}", node=node)
    amount = _amount_payload(node.count)
    payload: dict[str, object] = {}
    if amount == "x":
        if not node.at_random:
            raise LoweringError(
                "the only variable-count discard handler discards at random; "
                "a chosen discard of X cards has none",
                node=node,
            )
        kind = "discard_x_target_cards"
    else:
        if node.at_random:
            raise LoweringError(
                "no handler discards a fixed number of cards at random", node=node
            )
        kind = "discard_target_cards"
        payload["amount"] = amount
    _describe_targets(payload, node.player)
    return (OracleInstruction(kind, "", payload),)


_MANA_KEYS = ("W", "U", "B", "R", "G", "C")


def _full_mana_payload(cost: ast.ManaCost) -> dict[str, int]:
    """The mana dict the upkeep handlers read: every colour present, zeroed,
    plus `generic`. They index it directly, so a sparse dict would KeyError."""
    pips = dict(cost.pips)
    payload = {key: int(pips.get(key, 0)) for key in _MANA_KEYS}
    payload["generic"] = int(pips.get("generic", 0))
    return payload


def _lower_sacrifice_unless_pay(node: ast.SacrificeUnlessPay) -> tuple[OracleInstruction, ...]:
    """"Sacrifice this <permanent> unless you pay <cost>."

    Two handlers exist and the noun picks between them — an enchantment's
    prompt is a different registry entry from any other permanent's. Both
    sacrifice the source, so only a self-referential subject is accepted;
    sacrificing something *chosen* needs the pending-choice queue.
    """
    subject = node.subject
    if not _is_source(subject):
        raise LoweringError("no handler for sacrificing a chosen permanent", node=node)
    types = subject.filter.card_types if isinstance(subject, ast.TargetSpec) else ()
    kind = (
        "upkeep_pay_or_sacrifice_enchantment"
        if types == ("enchantment",)
        else "upkeep_pay_or_sacrifice_self"
    )
    return (OracleInstruction(kind, "", {"mana": _full_mana_payload(node.cost)}),)


def _lower_become_color(node: ast.BecomeColor) -> tuple[OracleInstruction, ...]:
    """The Lace cycle. `recolor_target_from_text` re-reads the card's own text
    to find the colour, so the payload only names it; the subject must still be
    a chosen target, since the handler recolours what was targeted."""
    if not isinstance(node.subject, ast.TargetSpec) or node.subject.quantifier != "target":
        raise LoweringError("no handler for recolouring a non-targeted object", node=node)
    # Deliberately *not* described for engine/targeting.py. The Lace cycle
    # targets "spell or permanent" — a union of a stack object and a
    # battlefield object that the `targets` vocabulary cannot express. Emitting
    # the generic object shape would derive "permanent" and drop spells on the
    # stack from the picker, so the description is omitted and legality.py
    # keeps answering `spell_or_permanent` until the vocabulary grows.
    return (OracleInstruction("recolor_target_from_text", "", {"target_color": node.color}),)


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
        if len(colours) != 1:
            raise LoweringError("no handler for this source-scoped shield", node=node)
        if not _is_you(recipient):
            raise LoweringError("colour-scoped shields only protect their controller", node=node)
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
    if node.to is not None:
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


def _lower_sacrifice(node: ast.Sacrifice) -> tuple[OracleInstruction, ...]:
    """Only "sacrifice this <permanent>" has a handler.

    Sacrificing something *chosen* ("sacrifice a creature") is a different
    problem: the choice belongs to a player, so it needs the pending-choice
    machinery rather than an instruction that acts on a known permanent.
    Refusing here keeps that distinction visible instead of quietly sacrificing
    the wrong thing.
    """
    if not _is_source(node.subject):
        raise LoweringError("no handler for sacrificing a chosen permanent", node=node)
    if node.player.kind != "you":
        raise LoweringError("no handler for another player sacrificing", node=node)
    return (OracleInstruction("sacrifice_self", "", {}),)


def _fused_draw_then_discard(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Draw N cards, then discard M cards." (Bazaar of Baghdad.)

    Kept fused because the decomposition has nowhere to go. ``draw_controller_cards``
    exists, but there is no controller-*discard* handler at all —
    ``discard_target_cards`` makes a chosen player discard — so a
    two-instruction lowering would draw the cards and then either discard
    nothing or empty the wrong player's hand, while the card reported as
    supported. ``draw_then_discard_self`` performs exactly this pair for the
    effect's controller and is already parameterised by both counts, so nothing
    about it is per-card: the legacy rule it replaces reads the two numbers out
    of the sentence the same way.

    Returning None rather than raising leaves a near-miss ("…then discard three
    cards at random") to the ordinary step lowering, which refuses it by name.
    """
    if len(steps) != 2:
        return None
    draw, discard = steps
    if not (isinstance(draw, ast.Draw) and isinstance(discard, ast.Discard)):
        return None
    if not (_is_you(draw.player) and _is_you(discard.player)) or discard.at_random:
        return None
    if not (isinstance(draw.count, ast.Fixed) and isinstance(discard.count, ast.Fixed)):
        return None
    return (
        OracleInstruction(
            "draw_then_discard_self", "",
            {"draw": draw.count.value, "discard": discard.count.value},
        ),
    )


def _lower_draw(node: ast.Draw) -> tuple[OracleInstruction, ...]:
    """"You draw" and "target player draws" are different handlers, not one
    handler with a recipient flag: ``draw_controller_cards`` draws for the
    effect's controller, ``draw_target_cards`` for the chosen player. Picking by
    the drawer keeps each one's existing contract intact."""
    kind = "draw_controller_cards" if node.player.kind == "you" else "draw_target_cards"
    payload: dict[str, object] = {"amount": _amount_payload(node.count)}
    _describe_targets(payload, node.player)
    return (OracleInstruction(kind, "", payload),)


def _lower_add_mana(node: ast.AddMana) -> tuple[OracleInstruction, ...]:
    """Emit the mana as structured pips rather than clause text.

    "Add one mana of any color" (Birds of Paradise, Celestial Prism) is the one
    player-chosen shape that lowers, and it is the exception that keeps the
    text. ``add_mana_from_text``'s any-colour branch is ``_add_mana_from_text``
    probing for the literal phrase "one mana of any color"; the chosen symbol
    arrives separately as ``color``, injected by mixins/stack_casting when
    ``any_color`` is set. Structured pips would say nothing the handler could
    read, so the clause rides along in ``oracle_text`` exactly as the legacy
    rule wrote it — which is what :attr:`ast.AddMana.source_text` exists for,
    and what keeps this payload byte-identical while the handler stays
    text-keyed.

    Any other count refuses. That probe recognizes *one* mana and no other
    number, so Black Lotus's "Add three mana of any one color" lowered here
    would add nothing while reporting success; it keeps its own fused
    ``sacrifice_self_for_mana`` handler on the legacy path.
    """
    if node.pips:
        return (OracleInstruction("add_mana_from_text", "", {"pips": node.pips}),)
    if node.any_color != 1:
        raise LoweringError(
            "only one mana of any colour has a handler; "
            f"{node.any_color} does not",
            node=node,
        )
    return (
        OracleInstruction(
            "add_mana_from_text", "", {"oracle_text": node.source_text, "any_color": True}
        ),
    )


def _title(words: str) -> str:
    """Title-case a lexed vocabulary word, preserving multiword entries."""
    return " ".join(part.capitalize() for part in words.split())


def _lower_create_token(node: ast.CreateToken) -> tuple[OracleInstruction, ...]:
    """"Create a 1/1 colorless Insect artifact creature token with flying named
    Wasp." (The Hive.)

    ``create_token`` builds the token's ``CardDefinition`` from the payload
    (engine/tokens.py), so this is pure characteristic transcription: the type
    line is re-rendered in the order the card printed it, and each optional key
    is emitted only when the card states it — matching the legacy rule, whose
    Hive payload carries no ``colors`` entry for a colourless token and no
    ``count`` for a single one.

    Two shapes refuse rather than guess:

    * **A token with no printed name.** CR 111.4 makes it "<subtypes> Token",
      but the engine's other token maker (``arm_end_step_token``, Rukh Egg)
      names it after the subtype alone. Choosing either here would make one of
      the two token families print the wrong name, and a token's name is what
      every "creatures named …" effect reads.
    * **A token with no creature type at all.** ``make_token_card`` always
      builds a creature card, and a type line with no card types would come out
      as a bare subtype the loader could not classify.
    """
    if not node.name:
        raise LoweringError(
            "a token with no printed name has no agreed naming convention "
            "(CR 111.4 says '<subtypes> Token'; arm_end_step_token uses the "
            "subtype alone)",
            node=node,
        )
    if "creature" not in node.types:
        raise LoweringError("make_token_card only builds creature tokens", node=node)

    type_line = " ".join(_title(word) for word in node.types)
    if node.subtypes:
        type_line += " — " + " ".join(_title(word) for word in node.subtypes)

    payload: dict[str, object] = {
        "name": _title(node.name),
        "power": node.power,
        "toughness": node.toughness,
        "type_line": type_line,
    }
    if node.colors:
        payload["colors"] = node.colors
    if node.keywords:
        payload["keywords"] = tuple(_title(word) for word in node.keywords)
    count = _amount_payload(node.count)
    if count != 1:
        payload["count"] = count
    return (OracleInstruction("create_token", "", payload),)


def _lower_look_at_hand(node: ast.LookAtHand) -> tuple[OracleInstruction, ...]:
    """"Look at target player's hand." (Glasses of Urza.)

    ``look_at_target_hand`` reads one chosen player off the resolution context
    and builds a single reveal from their hand. "Each opponent's hand" would
    need a loop it does not have and "your hand" is not an effect at all, so
    only the targeted form has a contract to lower onto.
    """
    if node.player.kind != "target_player":
        raise LoweringError(
            f"no handler for looking at {node.player.kind!r}'s hand", node=node
        )
    return (OracleInstruction("look_at_target_hand", "", _targets_only(node.player)),)


# Restrictions the search flow can honour. `card_type` is compared against the
# card's `primary_type` by ai_policy.choose_search_library_index and by the web
# picker, and `is_card` only says the noun phrase named cards — which a library
# holds by definition (CR 400.1). Every other field of the noun phrase is
# refused by _restrictions_beyond, because nothing in the flow tests one: the
# player would simply be offered their whole library.
_SEARCH_HONOURED_FILTER_FIELDS = frozenset({"card_types", "is_card"})


def _lower_search_library(node: ast.SearchLibrary) -> tuple[OracleInstruction, ...]:
    """"Search your library for a card, put that card into your hand, then
    shuffle." (Demonic Tutor.)

    ``search_library`` arms ``pending_search_library``, and
    ``confirm_search_library`` moves exactly **one** card into the *searcher's*
    hand and shuffles. That is its whole contract, so the two halves the parser
    read are checked against it here rather than dropped: a destination other
    than the searcher's own hand has no flow, and a restriction the picker
    cannot test would leave the player choosing from their entire library while
    the card still reported as supported.

    ``count`` is emitted even though only the UI displays it — the legacy rule
    wrote it and the payload has to stay byte-identical — but it is pinned to
    1, the number the confirm flow actually moves.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no flow searches {node.player.kind!r}'s library", node=node
        )
    if node.to.name != "hand" or node.to.owner is None or node.to.owner.kind != "you":
        raise LoweringError(
            "the search flow puts the found card into the searcher's own hand", node=node
        )
    filt = node.filter
    if not filt.is_card:
        # "Search your library for a creature" would be a permanent; a library
        # holds cards. Refusing keeps the noun phrase's head word load-bearing.
        raise LoweringError("a library holds cards, not permanents", node=node)
    leftover = _restrictions_beyond(filt, _SEARCH_HONOURED_FILTER_FIELDS)
    if leftover:
        raise LoweringError(
            "the search picker cannot test this restriction: " + ", ".join(leftover),
            node=node,
        )
    if len(filt.card_types) > 1:
        # The picker compares one `primary_type`, so a union would silently
        # widen to whichever type happened to be written first.
        raise LoweringError("the search picker tests one card type", node=node)
    card_type = filt.card_types[0] if filt.card_types else "any"
    return (
        OracleInstruction("search_library", "", {"count": 1, "card_type": card_type}),
    )


def _lower_extra_turn(node: ast.ExtraTurn) -> tuple[OracleInstruction, ...]:
    """"Take an extra turn after this one." (Time Walk, Time Vault.)

    ``grant_extra_turn`` queues the turn for the effect's *controller*; it takes
    no player argument. A card handing the extra turn to someone else is a
    different effect, so it is refused rather than lowered onto a handler that
    would give the turn to the wrong player.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no handler for {node.player.kind!r} taking an extra turn", node=node
        )
    return (OracleInstruction("grant_extra_turn", "", {}),)


# The restriction `grant_unblockable_to_low_power_target` hardcodes, in
# engine/handlers/combat.py *and* again in engine/legality.py's target
# enumerator. Written out here so the mismatch is checked rather than assumed.
_UNBLOCKABLE_POWER_LIMIT = ast.Comparison("le", ast.Fixed(2))

# Durations meaning "for the rest of this turn". Both handlers below set a flag
# listed in engine/mixins/_constants.py's _EOT_METADATA_KEYS, which is cleared
# in the cleanup step — so these two wordings are the same effect, and any other
# duration (or none) is not.
_REST_OF_TURN = ("this_turn", "until_end_of_turn")


def _lower_combat_restriction(node: ast.CombatRestriction) -> tuple[OracleInstruction, ...]:
    """``can't attack unless …`` / ``can't block creatures with power N …``.

    Lowers to the instruction kinds the combat steps already dispatch on, with
    the payloads ``engine/combat_restrictions.py`` produces for the legacy path
    — byte for byte, so the differential can hold the two to agreement rather
    than merely to "both did something".
    """
    return (OracleInstruction(node.kind, "", dict(node.payload)),)


def _lower_cant_be(node: ast.CantBe) -> tuple[OracleInstruction, ...]:
    """"Target creature can't be regenerated/blocked this turn."

    Both handlers act on one creature chosen as the ability is activated and
    honour **no** payload filter — they set a flag on whatever
    ``resolve_target_permanent`` returns. So every restriction the noun phrase
    carries has to be checked here or it would be silently dropped, which is why
    the subject's filter is compared for *equality* against the exact shape each
    handler implements rather than probed field by field: a filter field added
    to the AST later cannot slip through an equality check.
    """
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "a restriction with no end-of-turn duration is a static ability, "
            "which needs the CR 613 layers engine",
            node=node,
        )
    if not _is_target(node.subject):
        raise LoweringError("no handler for restricting a non-targeted subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    filt = node.subject.filter

    if node.action == "regenerated":
        if filt != ast.ObjectFilter(card_types=("creature",)):
            raise LoweringError(
                "deny_regeneration_to_target honours no target restriction", node=node
            )
        return (
            OracleInstruction("deny_regeneration_to_target", "", _targets_only(node.subject)),
        )

    if node.action == "blocked":
        # The trap: the handler's "power 2 or less" is a literal in its own
        # source, not something it reads from the payload. A card reading
        # "power 3 or less" would compile cleanly and get the wrong threshold,
        # so the parsed comparison is checked against the hardcoded one.
        if filt.power != _UNBLOCKABLE_POWER_LIMIT:
            raise LoweringError(
                "grant_unblockable_to_low_power_target hardcodes 'power 2 or "
                "less'; no handler implements another threshold",
                node=node,
            )
        if filt != ast.ObjectFilter(card_types=("creature",), power=_UNBLOCKABLE_POWER_LIMIT):
            raise LoweringError(
                "grant_unblockable_to_low_power_target honours no further target "
                "restriction",
                node=node,
            )
        # Deliberately *not* described for engine/targeting.py. `ObjectFilter.
        # to_payload` has no vocabulary for a power comparison, so the
        # description would read "target creature" and the picker would offer
        # creatures the ability cannot legally affect. legality.py keeps
        # answering this one until the description vocabulary grows.
        return (OracleInstruction("grant_unblockable_to_low_power_target", "", {}),)

    raise LoweringError(f"no handler for a {node.action!r} restriction", node=node)


def _lower_lose_life(node: ast.LoseLife) -> tuple[OracleInstruction, ...]:
    if node.player.kind not in ("target_player", "target_opponent", "that_player"):
        raise LoweringError(f"unsupported life-loss target {node.player.kind!r}", node=node)
    return (
        OracleInstruction("target_loses_life", "", {"amount": _amount_payload(node.amount)}),
    )


# ---------------------------------------------------------------------------
# Statement dispatch
# ---------------------------------------------------------------------------


# Values an instruction records in the resolution scratchpad, so a later
# back-reference ("that much") can verify it has a producer.
_PRODUCES: dict[str, str] = {"deal_damage": "damage_dealt"}


def lower_statement(
    statement: ast.Statement,
    produced: frozenset[str] = frozenset(),
    *,
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """Lower one statement into the instructions that perform it, in order.

    *produced* names the scratchpad values earlier steps of the same effect
    already recorded; a back-reference without a producer is refused.

    *event* is the trigger kind when this statement is a triggered ability's
    whole effect, and None everywhere else. It is deliberately **not** threaded
    into nested statements: the flows that read it (the upkeep pay-or-else
    registry, the pending optional-pay queue) act on a trigger's own effect, so
    a nested occurrence sees None and refuses rather than assuming the enclosing
    trigger's dispatch would reach it.
    """
    if isinstance(statement, ast.DealDamage):
        return _lower_damage(statement)
    if isinstance(statement, ast.DamageUnlessPay):
        return _lower_damage_unless_pay(statement, event)
    if isinstance(statement, ast.Pump):
        return _lower_pump(statement)
    if isinstance(statement, ast.SetBasePT):
        return _lower_set_base_pt(statement)
    if isinstance(statement, ast.GainKeyword):
        return _lower_gain_keyword(statement)
    if isinstance(statement, ast.PutCounter):
        return _lower_put_counter(statement)
    if isinstance(statement, ast.GainLife):
        return _lower_gain_life(statement, produced)
    if isinstance(statement, ast.LoseLife):
        return _lower_lose_life(statement)
    if isinstance(statement, ast.Destroy):
        return _lower_destroy(statement)
    if isinstance(statement, (ast.Tap, ast.Untap)):
        return _lower_tap(statement)
    if isinstance(statement, ast.TapOrUntap):
        return _lower_tap_or_untap(statement)
    if isinstance(statement, ast.Draw):
        return _lower_draw(statement)
    if isinstance(statement, ast.AddMana):
        return _lower_add_mana(statement)
    if isinstance(statement, ast.CreateToken):
        return _lower_create_token(statement)

    if isinstance(statement, ast.Conjunction):
        if len(statement.effects) == 2 and all(
            isinstance(effect, ast.DealDamage) for effect in statement.effects
        ):
            return _lower_damage_conjunction(statement)
        return _lower_steps(statement.effects, produced)

    if isinstance(statement, ast.SacrificeUnlessPay):
        return _lower_sacrifice_unless_pay(statement)

    if isinstance(statement, ast.BecomeColor):
        return _lower_become_color(statement)

    if isinstance(statement, ast.PreventDamage):
        return _lower_prevent_damage(statement)

    if isinstance(statement, ast.Regenerate):
        return _lower_regenerate(statement)

    if isinstance(statement, ast.CounterSpell):
        return _lower_counter_spell(statement)

    if isinstance(statement, ast.Discard):
        return _lower_discard(statement)

    if isinstance(statement, ast.ReturnToZone):
        return _lower_return_to_zone(statement)

    if isinstance(statement, ast.Sacrifice):
        return _lower_sacrifice(statement)

    if isinstance(statement, ast.LookAtHand):
        return _lower_look_at_hand(statement)

    if isinstance(statement, ast.SearchLibrary):
        return _lower_search_library(statement)

    if isinstance(statement, ast.ExtraTurn):
        return _lower_extra_turn(statement)

    if isinstance(statement, ast.CombatRestriction):
        return _lower_combat_restriction(statement)

    if isinstance(statement, ast.CantBe):
        return _lower_cant_be(statement)

    if isinstance(statement, ast.ForEach):
        return _lower_for_each(statement)

    if isinstance(statement, ast.Sequence):
        fused = _fused_draw_then_discard(statement.steps)
        if fused is not None:
            return fused
        return _lower_steps(statement.steps, produced)

    if isinstance(statement, ast.Conditional):
        then = lower_statement(statement.then, produced)
        otherwise = lower_statement(statement.otherwise, produced) if statement.otherwise else ()
        return (
            OracleInstruction(
                "if_then", "",
                {
                    "condition": _lower_condition(statement.condition),
                    "then": then,
                    "else": otherwise,
                },
            ),
        )

    if isinstance(statement, ast.May):
        return _lower_may(statement, produced)

    raise LoweringError(f"no lowering for {type(statement).__name__}", node=statement)


def _lower_may(node: ast.May, produced: frozenset[str]) -> tuple[OracleInstruction, ...]:
    """"You may pay {N}. If you do, …" and "You may <action>".

    This replaces the ``optional_pay`` hook shape, which could only express a
    fixed vocabulary of consequences (gain N life, draw N cards, take N damage)
    and so needed a name-keyed entry per card. Here the consequence is an
    ordinary instruction sequence, so any effect can sit behind an optional
    cost.

    **Known limit — a spell whose whole effect is optional.** The prompt still
    rides ``pending_optional_pays``, and only the triggered-ability resolution
    path holds that queue open and drains it (``resolve_top_of_stack``'s
    ``pause_for_choices``, ``auto_resolve_pending_optional_pays``). A spell
    leaves the stack the instant it resolves, so a line like Twiddle's "You may
    tap or untap target artifact, creature, or land." would queue its effect and
    never perform it — measured, not assumed: lowering Twiddle that way makes
    all three of its pinned regression tests fail with the permanent untouched.
    No card reaches that shape today (every usable ``may`` in the pool is a
    trigger remainder), and the check cannot live here: the coverage script and
    the lowering tests compile bare *clauses*, which are indistinguishable from
    a spell's whole line once the trigger prefix is gone. It stops being a trap
    when the prompt moves to the general pending-choice queue (roadmap phase 4).
    """
    action = lower_statement(node.action, produced) if node.action else ()
    then = lower_statement(node.then, produced) if node.then else ()
    otherwise = lower_statement(node.otherwise, produced) if node.otherwise else ()

    payload: dict[str, object] = {"actor": node.actor.kind}
    if node.cost is not None:
        if not isinstance(node.cost, ast.ManaCost):
            raise LoweringError("only mana costs can be offered optionally", node=node)
        generic = dict(node.cost.pips).get("generic", 0)
        colored = {sym: n for sym, n in node.cost.pips if sym != "generic"}
        if colored:
            raise LoweringError(
                "optional colored costs need a real cost-payment prompt", node=node
            )
        payload["cost"] = generic
    if action:
        payload["action"] = action
    if then:
        payload["then"] = then
    if otherwise:
        payload["otherwise"] = otherwise
    if not (action or then or otherwise):
        raise LoweringError("an optional action with no consequence", node=node)
    return (OracleInstruction("may", "", payload),)


def _lower_steps(
    steps: tuple[ast.Statement, ...], produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """Lower consecutive steps, threading what each one records forward."""
    instructions: tuple[OracleInstruction, ...] = ()
    for step in steps:
        lowered = lower_statement(step, produced)
        for instruction in lowered:
            result = _PRODUCES.get(instruction.kind)
            if result is not None:
                produced = produced | {result}
        instructions += lowered
    return instructions


def _lower_condition(condition: ast.Condition) -> dict[str, object]:
    if isinstance(condition, ast.Controls):
        payload = {
            "kind": "controls",
            "who": condition.who.kind,
            "filter": condition.filter.to_payload(),
        }
        if condition.comparison is not None and isinstance(condition.comparison.value, ast.Fixed):
            payload["count"] = condition.comparison.value.value
            payload["op"] = condition.comparison.op
        return payload
    if isinstance(condition, ast.IsState):
        return {"kind": "is_state", "state": condition.state, "negated": condition.negated}
    if isinstance(condition, ast.DiedThisTurn):
        return {"kind": "died_this_turn", "filter": condition.filter.to_payload()}
    raise LoweringError(f"no lowering for condition {type(condition).__name__}", node=condition)


def lower_ability(node: ast.AbilityNode) -> tuple[OracleInstruction, ...]:
    """Lower a whole ability line. Keyword and static lines carry no
    instructions of their own — they are recorded by the compiler as keyword or
    static lines instead."""
    if isinstance(node, ast.SpellEffectLine):
        return lower_statement(node.statement)
    if isinstance(node, ast.TriggeredAbilityNode):
        instructions = lower_statement(node.statement, event=node.event.kind)
        # An upkeep trigger is dispatched by the (condition, instruction kind)
        # pair in engine/phases/upkeep_effects.py, whose handlers are written
        # against the *fused* kinds the legacy rules produce
        # (`upkeep_pay_to_untap_self`, …). A decomposed `may(pay, untap_self)`
        # is a more faithful reading of the card, but no upkeep handler is
        # keyed to it, so claiming the line would leave the card compiling
        # cleanly and doing nothing at all. Refuse until the upkeep flow can
        # execute decomposed instructions (roadmap phase 4).
        decomposed = set(_WRAPPER_KINDS) | {"may"}
        if node.event.kind.startswith("upkeep") and any(
            instruction.kind in decomposed for instruction in instructions
        ):
            raise LoweringError(
                "upkeep triggers are dispatched by fused instruction kind; a "
                "decomposed wrapper has no handler",
                node=node,
            )
        if node.intervening_if is not None:
            # CR 603.4: the condition is checked when the trigger would fire and
            # again on resolution. The legacy compiler dropped these outright,
            # so conditional triggers always fired.
            condition = _lower_condition(node.intervening_if)
            instructions = tuple(
                OracleInstruction(
                    instruction.kind, instruction.value,
                    {**instruction.payload, "intervening_if": condition},
                )
                for instruction in instructions
            )
        return instructions
    if isinstance(node, ast.ActivatedAbilityNode):
        return lower_statement(node.statement)
    if isinstance(node, ast.KeywordLine):
        return ()
    if isinstance(node, ast.RegistryLine):
        # Zero instructions is the correct lowering, not a gap: the line is
        # already executed by a text-keyed registry reading the card's oracle
        # text (see engine/grammar/registries.py). Emitting anything here would
        # duplicate an effect the engine is already applying.
        return ()
    if isinstance(node, ast.StaticAbilityNode):
        raise LoweringError("static abilities need the CR 613 layers engine", node=node)
    raise LoweringError(f"no lowering for {type(node).__name__}", node=node)


# Control-flow wrappers take the categories of whatever they wrap, so gating
# "damage" is enough to turn on a sequence of damage instructions without
# inventing a category nobody could reason about.
#
# ``may`` is deliberately NOT in here: it gets its own ungated category below.
# Lowering an optional action is correct, but the prompt it raises still rides
# the one-card ``pending_optional_pays`` flow, and cards already on that flow
# (Soul Net, the Rod cycle) hold their trigger on the stack until the player
# answers — behavior the generic handler does not yet reproduce. Switching
# "optional" on is gated behind the pending-choice queue.
_WRAPPER_KINDS: dict[str, tuple[str, ...]] = {
    "sequence": ("steps",),
    "if_then": ("then", "else"),
    "for_each": ("effect",),
}


def categories_of(instructions: tuple[OracleInstruction, ...]) -> frozenset[str]:
    """Migration categories covered by a lowered instruction sequence."""
    found: set[str] = set()
    for instruction in instructions:
        nested_keys = _WRAPPER_KINDS.get(instruction.kind)
        if nested_keys is not None:
            nested: tuple[OracleInstruction, ...] = ()
            for key in nested_keys:
                nested += tuple(instruction.payload.get(key) or ())
            if not nested:
                return frozenset({"__ungated__"})
            inner = categories_of(nested)
            if "__ungated__" in inner:
                return frozenset({"__ungated__"})
            found |= inner
            continue
        category = INSTRUCTION_CATEGORIES.get(instruction.kind)
        if category is None:
            return frozenset({"__ungated__"})
        found.add(category)
    return frozenset(found)


__all__ = [
    "INSTRUCTION_CATEGORIES", "categories_of", "lower_ability", "lower_statement",
]
