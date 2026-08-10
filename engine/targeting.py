"""Cast-time targeting derived from the compiled program (CR 115).

`engine/legality.py` used to answer "what does this spell target?" by re-reading
the oracle text with ~40 substring predicates — a second parser of the same
text, which had to agree with the compiler forever or the UI would offer targets
the engine rejects. This module is its replacement: it reads the *compiled
program* the engine already built, so there is one parse and nothing to keep in
sync.

The answer is a whole spec, not just a kind. The kind decides which picker the
UI raises; the flags beside it decide what that picker offers — whose graveyard,
only the caster's creatures, a colour restriction on the stack. Deriving the
kind while leaving the flags to a text cascade would have left the second parser
alive for the interesting half, so both come from the same place.

Three kinds of evidence, in the order they are consulted:

1. **An Aura's ``Enchant <subject>`` line** names what it attaches to.
2. **A copy-on-enter phrase** (``engine/enter_effects.py``) means the caster
   chooses something to copy as the permanent arrives — a choice, not a target
   (CR 707.9a), but the same picker.
3. **The instructions themselves** — the kind, its ``targets`` description, or
   its ``type_filter`` payload.

:func:`derive_cast_spec` returns None when a card carries none of that, which
means "this spell chooses nothing as it is cast". Every supported card in the
pool now answers, and `tests/engine/test_targeting.py` fails if one that
mentions a target stops doing so — a parser change cannot quietly take the
evidence away.
"""

from __future__ import annotations

import re

from .enter_effects import copy_on_enter_type

# "Enchant creature", "Enchant land", ... — but NOT "Enchant creature card in a
# graveyard" (Animate Dead), which targets a graveyard card rather than a
# permanent on the battlefield. The negative lookahead is load-bearing: without
# it Animate Dead derives "creature" and the UI would offer battlefield
# creatures for a reanimation spell.
_ENCHANT_SUBJECTS = ("creature", "land", "artifact", "enchantment", "wall")
_ENCHANT_LINE = re.compile(
    rf"^enchant ({'|'.join(_ENCHANT_SUBJECTS)})\b(?! card)",
    re.MULTILINE,
)

# The whole-line form of the same scan, anchored at both ends so it claims a
# line that is *only* the attachment restriction.
_WHOLE_ENCHANT_LINE = re.compile(rf"^enchant ({'|'.join(_ENCHANT_SUBJECTS)})$")

# The graveyard form the scan above deliberately excludes. It is its own entry
# rather than a loosening of that pattern, because it names a different zone and
# so a different picker: `_apply_aura_effect` pops the chosen card out of
# `target_player.graveyard`, any player's, which is why `own_graveyard_only` is
# absent here and present on the spell-side reanimation below.
_ENCHANT_GRAVEYARD_LINE = re.compile(r"^enchant creature card in a graveyard\b", re.MULTILINE)

# Reminder text, stripped exactly as mixins/stack_casting.aura_enchant_noun
# strips it — "Enchant creature (Target a creature as you cast this. …)" is the
# same restriction as a bare "Enchant creature", and two consumers of one line
# must not read it differently.
_REMINDER_TEXT = re.compile(r"\([^)]*\)")


def enchant_line_subject(line: str) -> str | None:
    """What *line* attaches to, if the whole line is an ``Enchant <subject>``
    restriction (CR 702.5) — otherwise ``None``.

    The single-line form of the :data:`_ENCHANT_LINE` scan
    :func:`derive_cast_spec` runs over a card's whole normalized text, sharing
    its subject vocabulary so the two cannot drift. It exists so
    ``engine/grammar/registries.py`` can ask *this* module whether an Aura's
    attachment line is already accounted for, rather than copying the phrasing
    into the grammar where nothing would keep the copy honest.

    The trailing ``$`` is load-bearing: it keeps "Enchant creature card in a
    graveyard" (Animate Dead) out. Neither derivation here nor
    ``mixins/stack_casting.aura_enchant_noun`` implements that line — both
    deliberately refuse it, because it names a graveyard card rather than a
    battlefield permanent — so claiming it would report a reanimation Aura's
    attachment rule as handled while nothing handles it.
    """
    normalized = _REMINDER_TEXT.sub("", line).strip().lower().rstrip(".").strip()
    match = _WHOLE_ENCHANT_LINE.match(normalized)
    return match.group(1) if match is not None else None


# What an "Enchant <subject>" line means as a cast-time spec. A Wall is a
# creature to the targeting layer, narrowed by `enchant_wall`; an Aura that
# enchants an enchantment is offered the general permanent picker, narrowed by
# `enchant_enchantment`.
_ENCHANT_SUBJECT_TO_SPEC: dict[str, dict] = {
    "creature": {"kind": "creature"},
    "wall": {"kind": "creature", "enchant_wall": True},
    "land": {"kind": "land"},
    "artifact": {"kind": "artifact"},
    "enchantment": {"kind": "permanent", "enchant_enchantment": True},
}

# An instruction's type_filter, as a target kind. Filters naming more than one
# type fall back to the general permanent picker, which then applies the filter.
_TYPE_FILTER_TO_KIND = {
    "artifact": "artifact",
    "creature": "creature",
    "land": "land",
    "enchantment": "permanent",
    "permanent": "permanent",
    "artifact_or_enchantment": "permanent",
}


# Instruction kinds whose whole cast-time spec is fixed by the kind itself. A
# lace always targets a spell or permanent; a graveyard-return always targets a
# card in a graveyard. `legality.py` used to read that off the card's *text*;
# the compiled program already carries it in the kind.
#
# The flags beside a kind describe the same thing the kind's *handler* does, so
# they are read off the handler rather than off the card. `reanimate_creature`
# calls `_reanimate_creature_to_battlefield(caster, caster, …)` — always the
# caster's own graveyard — so `own_graveyard_only` belongs to the kind and not
# to whether the words "your graveyard" happen to appear.
_KIND_TO_SPEC: dict[str, dict] = {
    "recolor_target_from_text": {"kind": "spell_or_permanent"},
    "mark_text_modified": {"kind": "permanent"},
    "counter_top_stack_spell": {"kind": "stack"},
    "berserk_pump": {"kind": "creature"},
    "grant_unlimited_blocking": {"kind": "creature"},
    "deal_damage_and_gain_life": {"kind": "any"},
    "grant_prevention_shield": {"kind": "any"},
    "target_gains_life": {"kind": "any"},
    "remove_creature_from_combat": {"kind": "creature"},
    "grant_target_flying_until_eot": {"kind": "creature"},
    "simulacrum_redirect": {"kind": "creature"},
    "exile_creature_gain_life_equal_to_power": {"kind": "creature"},
    "bounce_target_creature": {"kind": "creature"},
    "phase_out_target_creature_until_source_leaves": {"kind": "creature"},
    "destroy_artifact_controller_gains_mana_value": {"kind": "artifact"},
    "reanimate_creature": {"kind": "graveyard_creature", "own_graveyard_only": True},
    "exchange_ante_with_top_library": {"kind": "none"},
    "tap_or_untap_target": {"kind": "permanent"},
    "drain_target_lands_mana": {"kind": "player"},
    "tap_target_player_lands_and_drain_mana": {"kind": "player"},
    "reorder_target_library_top": {"kind": "player"},
    "return_all_owned_artifacts_to_hand": {"kind": "player"},
    # Volcanic Eruption: "Destroy X target Mountains", where X is how many the
    # caster picks — so the divided picker runs over Mountains and skips its
    # separate X prompt.
    "volcanic_eruption": {"kind": "divided", "land_filter": "mountain", "x_equals_targets": True},
    # Word of Command looks at *target opponent's* hand: the caster's own seat is
    # not a legal choice (CR 115.4).
    "peek_hand_and_force_play": {"kind": "player", "opponents_only": True},
    # Fork copies the chosen spell and lets the caster choose new targets for the
    # copy, so the UI runs a second prompt rather than sending the cast at once.
    "copy_top_stack_spell": {
        "kind": "stack",
        "copies_spell": True,
        "stack_instant_sorcery_only": True,
    },
    # "The next time a source of your choice would deal damage to you this turn":
    # the source may be a permanent on any battlefield or a spell on the stack,
    # which `also_stack` folds into one prompt. The engine matches the chosen
    # source by identity, so no colour filter narrows it.
    "grant_reverse_damage_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    "arm_mirror_damage": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # "As an additional cost to cast this spell, sacrifice a creature." The
    # creature picked is the caster's own and is sacrificed as a cost, so the UI
    # offers only their creatures and says "sacrifice" rather than "target".
    "sacrifice_creature_for_black_mana": {
        "kind": "creature", "own_only": True, "sacrifice_cost": True,
    },
}


def _counter_spec(payload: dict) -> dict:
    """A counterspell, narrowed to the colour its payload names.

    The Elemental Blasts counter one colour and Counterspell counters any, which
    is one kind with different data — exactly why the colour is payload rather
    than part of the kind.
    """
    spec: dict = {"kind": "stack"}
    color = payload.get("color_filter")
    if color:
        spec["stack_color_filter"] = color
    return spec


def _graveyard_return_spec(payload: dict) -> dict:
    """A graveyard return, narrowed to the card type it may take.

    Regrowth takes any card, Raise Dead a creature card, Reconstruction an
    artifact card — the same instruction with different data. The handler pops
    the chosen index out of the *caster's* graveyard, so the picker is scoped to
    it.
    """
    spec: dict = {"kind": "graveyard_creature", "own_graveyard_only": True}
    if payload.get("any_card"):
        spec["any_card"] = True
    elif payload.get("card_type") not in (None, "creature"):
        spec["card_type"] = payload["card_type"]
    return spec


# One kind, several specs, decided by payload.
_KIND_TO_SPEC_FROM_PAYLOAD = {
    "counter_top_stack_spell": _counter_spec,
    "return_creature_from_graveyard_to_hand": _graveyard_return_spec,
}


def derive_cast_spec(card, program) -> dict | None:
    """The cast-time target spec of *card*, or None when it chooses nothing.

    None is the answer for a permanent whose only targeting belongs to an
    activated ability — Royal Assassin picks its victim when the ability is
    activated, not when the creature is cast.
    """
    graveyard_aura = _ENCHANT_GRAVEYARD_LINE.search(program.normalized_text or "")
    if graveyard_aura is not None:
        # Animate Dead. `_apply_aura_effect` reads the chosen index out of
        # whichever graveyard the caster pointed at, so unlike the spell-side
        # `reanimate_creature` this one is not scoped to their own.
        return {"kind": "graveyard_creature"}

    enchant = _ENCHANT_LINE.search(program.normalized_text or "")
    if enchant is not None:
        spec = _ENCHANT_SUBJECT_TO_SPEC.get(enchant.group(1))
        return dict(spec) if spec is not None else None

    copied = copy_on_enter_type(program.normalized_text or "")
    if copied is not None:
        # Clone / Copy Artifact / Vesuvan Doppelganger. `optional` is what tells
        # the UI to offer the choice only when there is something to copy, and
        # to let the permanent enter as itself otherwise (CR 707.9a).
        return {"kind": copied, "optional": True}

    # Only a spell picks a target as it is cast. A permanent's instructions
    # include those of its *abilities*, which choose their own targets on
    # activation — reading a filter off those would make the UI demand a target
    # for casting Royal Assassin because its tap ability destroys a tapped
    # creature. 27 cards in the pool derive a target they do not have if this
    # gate is removed, so it is measured rather than assumed.
    type_line = card.type_line.lower()
    if "instant" in type_line or "sorcery" in type_line:
        return _from_instructions(program.instructions)

    # A permanent's enters-the-battlefield trigger is the one exception: this
    # engine picks its target as the permanent is cast (Oubliette), where
    # CR 603.3d would choose it when the trigger goes on the stack. That is a
    # standing approximation, not a targeting question — but while it holds, the
    # prompt has to be raised at cast time or the trigger has no target at all.
    return _from_instructions([
        ability.instruction
        for ability in program.triggered_abilities
        if ability.supported
        and ability.instruction is not None
        and ability.condition.kind == "enters_battlefield"
    ])


def derive_cast_target(card, program) -> str | None:
    """The cast-time target *kind* of *card*, for callers that need no flags."""
    spec = derive_cast_spec(card, program)
    return spec["kind"] if spec is not None else None


def _from_instructions(instructions) -> dict | None:
    """The first cast-time spec any instruction in *instructions* describes.

    Recurses into `sequence` steps: a spell written as two steps carries its
    targeting on the step that targets (Psionic Blast's damage to any target,
    followed by its self-damage), and stopping at the wrapper would leave an
    otherwise fully-described spell with no prompt.
    """
    for instruction in instructions:
        if instruction.kind == "sequence":
            nested = _from_instructions(instruction.payload.get("steps") or ())
            if nested is not None:
                return nested
            continue
        described = _from_targets_payload(instruction.payload.get("targets"))
        if described is not None:
            return described
        type_filter = instruction.payload.get("type_filter")
        if type_filter:
            kind = _TYPE_FILTER_TO_KIND.get(type_filter)
            if kind is not None:
                return {"kind": kind}
            continue
        from_payload = _KIND_TO_SPEC_FROM_PAYLOAD.get(instruction.kind)
        if from_payload is not None:
            return from_payload(instruction.payload)
        by_kind = _KIND_TO_SPEC.get(instruction.kind)
        if by_kind is not None:
            return dict(by_kind)

    return None


def _from_targets_payload(targets) -> dict | None:
    """The cast-time spec from a grammar-lowered ``targets`` description.

    This is the evidence the legacy rules never recorded: it is what tells
    Lightning Bolt ("any target") apart from Earthbind ("target creature with
    flying") when both compile to a bare ``deal_damage``.
    """
    if not isinstance(targets, dict):
        return None
    kind = targets.get("kind")
    if kind == "any":
        return {"kind": "any"}
    if kind == "divided":
        # Fireball: "X damage divided evenly … among any number of targets".
        # The UI picks the targets and X follows from how many were chosen, so
        # this is its own prompt rather than a repeated "any target".
        return {"kind": "divided"}
    if kind == "player":
        return {"kind": "player"}
    if kind == "spell":
        # A spell on the stack, which the UI picks from a different zone than
        # any permanent — "stack" is the name for that picker.
        return {"kind": "stack"}
    if kind != "object":
        return None
    filt = targets.get("filter") or {}
    type_filter = filt.get("type_filter")
    if not type_filter:
        # A targeted object with no type restriction is any permanent.
        return {"kind": "permanent"}
    derived = _TYPE_FILTER_TO_KIND.get(type_filter)
    return {"kind": derived} if derived is not None else None
