"""Targeting derived from the compiled program (CR 115, CR 602.2b).

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

**Activated abilities ask the same question one level down.** A spell picks its
targets once, as it is cast; an ability picks them each time it is activated,
and one card may carry several abilities that target differently (Pyramids
destroys an Aura or shields a land). So :func:`derive_activation_spec` takes an
*ability*, not a card, and runs the same instruction evidence over that
ability's own instruction — the tables below are shared, because what an
instruction kind targets does not depend on whether a spell or an ability
produced it. `legality.py` classified activation from text until this existed;
`tests/engine/test_activation_targeting.py` holds the replacement in place.
"""

from __future__ import annotations

import re

from .cast_costs import additional_costs
from .enter_effects import copy_on_enter_type
from .subject_filters import filter_head_noun

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

# Reminder text, stripped exactly as mixins/stack/casting.aura_enchant_noun
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
    ``mixins/stack/casting.aura_enchant_noun`` implements that line — both
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
    # "…deals 1 damage to target planeswalker." (Sparkhunter Masticore.) Its own
    # picker rather than the general permanent one: a planeswalker is the only
    # permanent type a printed phrase names this often *without* also admitting
    # creatures, and offering every permanent would be a prompt the resolution
    # then refuses.
    "planeswalker": "planeswalker",
}


def _kind_for_type_filter(type_filter) -> str | None:
    """*type_filter* as a target kind, or None when nothing describes it.

    A filter may name a *union* of types — Icy Manipulator's "target artifact,
    creature, or land" lowers to ``["artifact", "creature", "land"]``. No single
    picker matches a union, so it takes the general permanent picker and
    ``permanent_matches_filter`` narrows it back down at enumeration time, the
    same way it does at resolution.
    """
    if isinstance(type_filter, (list, tuple)):
        return "permanent"
    return _TYPE_FILTER_TO_KIND.get(type_filter)


def _narrowing_flags(source: dict) -> dict:
    """The picker-narrowing flags *source* (a filter or a payload) carries.

    These are the restrictions the enumerator itself applies
    (`_permanent_matches_target_kind`), as opposed to the ones it delegates to
    the instruction's own filter through `_ability_target_legal`. Both are read
    from the same compiled payload; only the vocabulary differs.
    """
    flags: dict = {}
    for key in ("attacking_only", "flying_only"):
        if source.get(key):
            flags[key] = True
    if source.get("subtype_filter") == "wall":
        # The picker's name for a Wall subtype filter (Ali Baba, Dwarven
        # Demolition Team). Kept as a flag rather than left to the instruction
        # filter so a Wall-only prompt reads the same whether the narrowing
        # came from the ability's payload or from an Aura's "Enchant Wall".
        flags["wall_only"] = True
    color = source.get("color_filter")
    if color:
        flags["color_filter"] = color
    if source.get("controller") == "you":
        # "target creature you control". The enumerator applies this one itself
        # (it is a seat test, not a permanent test), and it has to: a picker
        # that offered an opponent's creature would let a player choose a target
        # the effect then declines to affect, with nothing on screen saying why.
        flags["own_only"] = True
    if source.get("exclude_self"):
        # "up to two **other** target creatures you control" (Basri's Acolyte),
        # "**another** target creature" as a fight's opponent (Brash Taunter).
        # Same argument as `own_only` directly above, and it had the same gap in
        # the other direction: every handler carrying this key already refuses
        # the source at resolution (pump.py, zones.py, damage.py), so a picker
        # that omitted it offered a target the effect then declined to affect.
        # `legality.py` has honoured `exclude_source` all along — nothing read
        # the filter key into it.
        flags["exclude_source"] = True
    return flags


# Instruction kinds whose whole spec is fixed by the kind itself. A lace always
# targets a spell or permanent; a graveyard-return always targets a card in a
# graveyard. `legality.py` used to read that off the card's *text*; the compiled
# program already carries it in the kind.
#
# The flags beside a kind describe the same thing the kind's *handler* does, so
# they are read off the handler rather than off the card. `reanimate_creature`
# calls `_reanimate_creature_to_battlefield(caster, caster, …)` — always the
# caster's own graveyard — so `own_graveyard_only` belongs to the kind and not
# to whether the words "your graveyard" happen to appear.
#
# One table, consulted by the cast side and the activation side alike: what an
# instruction targets is a property of the instruction, not of whether a spell
# or an ability produced it. `grant_target_flying_until_eot` is Jump when a
# spell carries it and Flying Carpet's ability when a permanent does, and both
# want the same creature picker.
_KIND_TO_SPEC: dict[str, dict] = {
    "recolor_target_from_text": {"kind": "spell_or_permanent"},
    # Unsubstantiate: a spell on the stack or a creature on the battlefield —
    # the recolor picker's zones, narrowed to creatures on the permanent half.
    "return_spell_or_creature_to_hand": {
        "kind": "spell_or_permanent", "permanent_kind": "creature",
    },
    # Epitaph Golem: any card in the activator's own graveyard.
    "put_graveyard_card_on_library_bottom": {
        "kind": "graveyard_creature", "own_graveyard_only": True, "any_card": True,
    },
    "mark_text_modified": {"kind": "permanent"},
    "counter_top_stack_spell": {"kind": "stack"},
    "berserk_pump": {"kind": "creature"},
    "grant_unlimited_blocking": {"kind": "creature"},
    "deal_damage_and_gain_life": {"kind": "any"},
    "target_gains_life": {"kind": "any"},
    "remove_creature_from_combat": {"kind": "creature"},
    "grant_target_flying_until_eot": {"kind": "creature"},
    "simulacrum_redirect": {"kind": "creature"},
    "exile_creature_gain_life_equal_to_power": {"kind": "creature"},
    "bounce_target_creature": {"kind": "creature"},
    "phase_out_target_creature_until_source_leaves": {"kind": "creature"},
    "destroy_artifact_controller_gains_mana_value": {"kind": "artifact"},
    "reanimate_creature": {"kind": "graveyard_creature", "own_graveyard_only": True},
    # "target card from a graveyard" — any card, any seat's graveyard, so no
    # own_graveyard_only. The picker is the reanimation one because the
    # *choice* is identical; only where the card goes afterwards differs, and
    # that is the handler's business, not the picker's.
    "exile_target_graveyard_card": {"kind": "graveyard_creature", "any_card": True},
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
    # "As an additional cost to cast this spell, sacrifice a creature" used to
    # be keyed here, by the instruction Sacrifice and Metamorphosis compile to.
    # It is a *cost*, so `derive_cast_spec` now reads it off `cast_costs` and
    # every card printing the phrase gets the picker — Village Rites and
    # Goremand buy nothing with it and were being offered no choice at all.
    # --- kinds that reach the picker through an activated ability -----------
    #
    # Each of these resolves through `resolve_target_permanent(game, context)` with
    # the default predicate — `p.is_creature` — so "creature" is what the code
    # that runs the ability accepts, not what the printed line says.
    "grant_banding_to_target": {"kind": "creature"},
    "grant_target_keyword_until_eot": {"kind": "creature"},
    "grant_islandwalk_and_linked_destroy": {"kind": "creature"},
    "grant_flying_and_delayed_destruction": {"kind": "creature"},
    "grant_unblockable_to_low_power_target": {"kind": "creature"},
    "steal_creature_while_tapped_and_weaker": {"kind": "creature"},
    "deny_regeneration_to_target": {"kind": "creature"},
    "pump_target_creature_until_eot": {"kind": "creature"},
    "grant_regeneration_to_target_creature": {"kind": "creature"},
    "mark_non_wall_target_to_attack": {"kind": "creature"},
    # "Put a +1/+1 counter on target creature" — the creature restriction is
    # part of what the kind means. Emitted by Dwarven Weaponsmith's hook and,
    # since the M21 counter round, by the grammar's put-counter lowering.
    "add_counter_to_target": {"kind": "creature"},
    # Three effects that act on a *player*: the handler reads `context.target`,
    # a seat, and never looks at the battlefield.
    "mill_target_player": {"kind": "player"},
    "look_at_target_hand": {"kind": "player"},
    "discard_target_cards": {"kind": "player"},
    # "Search **target opponent's** graveyard, hand, and library …"
    # (Necromentia). The searched player is a target chosen as the spell is cast
    # (CR 601.2c); the *card name* is chosen on resolution and is not a target at
    # all, which is why the kind is a plain player rather than something
    # card-shaped.
    "name_and_strip": {"kind": "player"},
    # "Target opponent loses 2 life for each creature card in their graveyard."
    # (Liliana, Death Mage's ultimate.) The recipient is a seat; the per-each
    # count is read at resolution and names nothing.
    "target_loses_life": {"kind": "player"},
    # Cuombajj Witches. Its handler delegates the controller's half to
    # `deal_damage`, which takes a player or a permanent; the opponent's half is
    # a pending choice made after resolution, not a target chosen here.
    "deal_damage_and_opponent_choice": {"kind": "any"},
    # Aladdin: `resolve_target_permanent(..., predicate=p.has_type("artifact"))`.
    # The kind's name says "permanent", the code it runs says artifact.
    "steal_target_permanent_linked_to_self": {"kind": "artifact"},
    # Gaea's Liege and Pyramids' second mode: both resolve through a
    # `primary_type == "land"` predicate.
    "change_target_land_type": {"kind": "land"},
    "shield_target_land_from_destruction": {"kind": "land"},
    # Cyclopean Tomb's handler refuses a Swamp outright
    # (`primary_type == "land" and not _is_swamp(p)`), so the exclusion belongs
    # to the kind rather than to the words "non-Swamp" appearing on the card.
    "add_mire_counter_to_target_land": {"kind": "land", "exclude_swamp": True},
    # Forcefield: "an unblocked creature of your choice would deal combat damage
    # to you" — the controller picks one of the attackers that got through.
    "grant_forcefield_shield": {"kind": "creature", "unblocked_attacker": True},
    # Jade Monolith picks twice: the creature it shields, and the damage source
    # whose damage is redirected. `requires_source` is what tells the UI to run
    # the second prompt.
    "jade_monolith_redirect": {"kind": "creature", "requires_source": True},
    # Diamond Valley's "Sacrifice a creature" is part of the activation cost, so
    # the creature is the controller's own and the prompt says "sacrifice" —
    # the same spec the cast-side additional cost above derives.
    "sacrifice_creature_gain_life_by_toughness": {
        "kind": "creature", "own_only": True, "sacrifice_cost": True,
    },
    # Ebony Horse: "Untap target attacking creature you control." Its handler
    # requires `p.attacking` *and* that the creature is on the activating
    # player's battlefield, and an explicit choice that fails either test
    # fizzles — so both narrowings are the ability's, and both belong here.
    "untap_attacker_and_prevent_combat_damage": {
        "kind": "creature", "attacking_only": True, "own_only": True,
    },
}


def _cost_picker_spec(cost) -> dict | None:
    """The picker a choosable cost needs, or None when the cost chooses nothing.

    Shared by the cast and activation sides because the *choice* is the same on
    both — CR 601.2b and CR 602.2b are the same announcement step — and only
    what is withheld from the list differs. ``sacrifice_cost`` / ``discard_cost``
    are what tell the client which field carries the answer and to say
    "sacrifice" rather than "target"; the payment is not a target, and a card
    can have both.

    The sacrifice's head noun is the kind, rather than a fixed "creature": Atog
    eats an artifact, and a picker offering creatures for it would offer nothing
    it could pay with. Anything the noun phrase says *beyond* its head noun rides
    along as ``filter`` — "a creature with defender" (Portcullis Vine) is a
    creature picker over a narrowed list, and the enumerator applies the
    narrowing with the same matcher the charger does, so what is offered and
    what is accepted cannot disagree.
    """
    if cost is None:
        return None
    if getattr(cost, "discard_cards", 0):
        spec = {
            "kind": "hand_card",
            "own_only": True,
            "discard_cost": True,
            "count": cost.discard_cards,
        }
        # "Discard a **land card or Shrine card**" (Sanctum of Shattered
        # Heights) — the printed alternatives ride along so the enumerator
        # narrows the offered hand with the same reader the charger accepts by.
        # Emitted only when there is a narrowing: an empty key would read as one
        # to anything that tests for its presence.
        alternatives = getattr(cost, "discard_filters", ()) or ()
        if alternatives:
            spec["filters"] = [dict(alt) for alt in alternatives]
        return spec
    described = getattr(cost, "sacrifice_filter", None)
    if described is not None:
        spec = {
            "kind": filter_head_noun(described),
            "own_only": True,
            "sacrifice_cost": True,
        }
        # "Sacrifice **another** creature" (Hobblefiend): the source is not a
        # legal payment, so a lone Hobblefiend can offer nothing and cannot
        # activate at all — which the payment path already enforces. It is
        # lifted out of the carried filter rather than left in it, because the
        # enumerator excludes by identity and a key nothing reads is a key
        # silently dropped.
        if described.get("exclude_self"):
            spec["exclude_source"] = True
        # `kind` already *is* the head noun, so re-stating it in the carried
        # filter would be the same restriction written twice. A type *union* has
        # no head noun (`kind` falls back to "permanent"), so it rides along.
        narrowing = {
            key: value
            for key, value in described.items()
            if key != "exclude_self"
            and not (key == "type_filter" and isinstance(value, str))
        }
        if narrowing:
            spec["filter"] = narrowing
        return spec
    return None


def _life_gain_spec(payload: dict) -> dict | None:
    """Who gains the life is what decides whether anything is chosen at all.

    "Target player gains 3 life" picks a player; "you gain 3 life" picks
    nothing, and **37 of the pool's 39 life gains are the second one**. One
    instruction kind serves both because only the amount and the recipient
    differ, so the kind alone could not tell them apart — and answering "any
    target" for all of them put a picker in front of spells that target nothing
    (Revitalize, Witch's Cauldron's ability). Whatever the player clicked was
    sent as a target the handler then ignored, so the prompt was not merely
    spurious: it was a question whose answer went nowhere.

    An unrecognised recipient answers None, which is the safe direction: no
    prompt in front of an effect that chooses nothing, rather than a prompt
    whose answer is discarded.

    Reading the payload here means this entry has to answer the *whole*
    question, including the half it did not come to change: a payload-keyed spec
    is authoritative in ``_from_instruction``, so returning a bare "any" for the
    targeting case would have overridden the grammar's own targets description
    and coarsened Healing Salve and Stream of Life from "target player" to
    "any target".
    """
    if payload.get("recipient") != "target":
        return None
    return _from_targets_payload(payload.get("targets")) or {"kind": "player"}


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
    card_types = payload.get("card_types")
    if card_types:
        # Miscast: "target instant or sorcery spell" — the same union the
        # handler tests at resolution, so the picker offers exactly what the
        # counter would counter.
        spec["stack_card_types"] = list(card_types)
    return spec


def _graveyard_return_spec(payload: dict) -> dict:
    """A graveyard return, narrowed to the card type it may take.

    Regrowth takes any card, Raise Dead a creature card, Reconstruction an
    artifact card — the same instruction with different data. The handler pops
    the chosen index out of the *caster's* graveyard, so the picker is scoped to
    it.
    """
    spec: dict = {"kind": "graveyard_creature", "own_graveyard_only": True}
    # "Up to two target creature cards" (Sanguine Indulgence). This kind settles
    # its own spec, so the generic `targets` reading in `_from_instruction` never
    # runs for it - the maximum has to be lifted here, or the picker collects one
    # card for a spell that names two.
    count = (payload.get("targets") or {}).get("count")
    if isinstance(count, int) and count > 1:
        spec["max_targets"] = count
    if payload.get("card_types"):
        # "target instant or sorcery card" (Shipwreck Dowser) — the union the
        # round-19 graveyard picker already tests by primary type.
        spec["card_types"] = list(payload["card_types"])
    elif payload.get("any_card"):
        spec["any_card"] = True
    elif payload.get("card_type") not in (None, "creature"):
        spec["card_type"] = payload["card_type"]
    return spec


def _prevention_shield_spec(payload: dict) -> dict | None:
    """A "prevent the next N damage" shield, and who is being shielded.

    One kind, four answers, and the payload settles which: the shield sits on
    the caster (Conservator), on the source permanent itself (Rock Hydra), on a
    *source of the named colour* the controller chooses (the Circles of
    Protection), or on a target the ability picks (Oasis, Samite Healer,
    Guardian Angel). The first two choose nothing at all, which is why this
    returns None rather than a spec.
    """
    if payload.get("to_self") or payload.get("to_source"):
        return None
    if payload.get("protection_kind") == "color":
        # The chosen source may be a permanent of that colour on any
        # battlefield, or a spell of that colour on the stack; `also_stack`
        # folds both into one prompt because the engine matches the shield by
        # colour rather than by identity.
        return {
            "kind": "permanent",
            "color_filter": payload.get("prevention_color"),
            "also_stack": True,
        }
    return _from_targets_payload(payload.get("targets")) or {"kind": "any"}


def _set_base_pt_spec(payload: dict) -> dict:
    """"Target creature ... has base power 0 until end of turn", narrowed to the
    creatures the printed line allows.

    Island of Wak-Wak reaches only fliers and Singing Tree only attackers; the
    enumerator applies both itself, so unlike a subtype or tapped restriction
    they have to reach the spec rather than being left to the instruction
    filter. Sorceress Queen's "other than this creature" does not appear here
    because `_ability_target_legal` already excludes the source.
    """
    return {"kind": "creature", **_narrowing_flags(payload)}


def _cast_permission_spec(payload: dict) -> dict | None:
    """A cast-permission grant targets only in its graveyard form ("You may
    cast target red instant or sorcery card from your graveyard", Chandra,
    Flame's Catalyst's −2); the exiled-cards and cost-waiver forms choose
    nothing as they go on the stack."""
    if not payload.get("target_graveyard_card"):
        return None
    spec: dict = {"kind": "graveyard_creature", "own_graveyard_only": True}
    card_types = tuple(payload.get("card_types") or ())
    if card_types:
        spec["card_types"] = list(card_types)
    colors = tuple(payload.get("colors") or ())
    if colors:
        spec["graveyard_color_filter"] = colors[0]
    return spec


def _forced_sacrifice_spec(payload: dict) -> dict | None:
    """Who a "sacrifices a creature" effect asks is what decides whether it
    targets at all.

    "Sacrifice a creature" (Dire Fleet Warmonger) and "each opponent sacrifices
    a creature" (Goremand) choose nothing — the payers follow from the effect's
    own controller. "Target opponent sacrifices a creature of their choice with
    flying" (Run Afoul) chooses a player, and it may not choose the caster
    (CR 115.4). One instruction kind serves all three, so only the payload can
    tell them apart; answering "player" for every one of them would put a
    picker in front of Goremand, whose answer nothing reads.
    """
    who = payload.get("who")
    if who == "target_opponent":
        return {"kind": "player", "opponents_only": True}
    if who == "target_player":
        return {"kind": "player"}
    return None


# One kind, several specs, decided by payload.
_KIND_TO_SPEC_FROM_PAYLOAD = {
    "sacrifice_matching_permanent": _forced_sacrifice_spec,
    "target_gains_life": _life_gain_spec,
    "counter_top_stack_spell": _counter_spec,
    "return_creature_from_graveyard_to_hand": _graveyard_return_spec,
    "grant_prevention_shield": _prevention_shield_spec,
    "set_base_pt_target_until_eot": _set_base_pt_spec,
    "grant_cast_permission": _cast_permission_spec,
}


def derive_cast_spec(card, program) -> dict | None:
    """The cast-time target spec of *card*, or None when it chooses nothing.

    None is the answer for a permanent whose only targeting belongs to an
    activated ability — Royal Assassin picks its victim when the ability is
    activated, not when the creature is cast.
    """
    # A printed additional cost is picked as the spell is cast, before any
    # target — and unlike a target it belongs to the *cost*, so it is read from
    # the cost table rather than from any instruction. `sacrifice_cost` is what
    # tells the client to send it on the cost field and to say "sacrifice"
    # rather than "target".
    for cost in additional_costs(card):
        cost_spec = _cost_picker_spec(cost)
        if cost_spec is not None:
            return cost_spec

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


def targets_mana_value_x(instructions) -> bool:
    """Whether these instructions target an object whose mana value must equal
    the cast's X — "counter target spell with mana value X" (Spell Blast),
    "destroy target artifact with mana value X" (Detonate).

    Read off the compiled program rather than the oracle text, and recursing
    through the wrappers for the reason :func:`_from_instructions` does: Detonate
    prints two sentences, so its destroy is a step of a ``sequence`` and a reader
    that stopped at the wrapper would answer no about the card that asks.
    """
    for instruction in instructions:
        if instruction.payload.get("mv_equals_x"):
            return True
        nested = _nested_steps(instruction)
        if nested and targets_mana_value_x(nested):
            return True
    return False


#: The wrapper kinds above, and the payload keys whose instructions they carry.
#: The same two ``_from_instructions`` descends into, and for the same reason
#: it gives — an effect written as two steps carries its targeting on the step
#: that targets.
_WRAPPER_STEP_KEYS = {"sequence": ("steps",), "may": ("action", "then")}


def _nested_steps(instruction) -> tuple:
    """The instructions a wrapper carries, empty for anything else."""
    nested: tuple = ()
    for key in _WRAPPER_STEP_KEYS.get(instruction.kind, ()):
        nested += tuple(instruction.payload.get(key) or ())
    return nested


def derive_instruction_spec(instructions) -> dict | None:
    """The target spec a bare instruction sequence describes, or None for none.

    The entry point for a sequence that is nobody's ability line: CR 603.12's
    reflexive triggered ability is created mid-resolution and chooses its own
    targets then, so there is no `ability` object to hand
    :func:`derive_activation_spec`. Same reader underneath, so what a reflexive
    ability offers and what an activated one offers cannot disagree.
    """
    return _from_instructions(instructions)


def _from_instructions(instructions) -> dict | None:
    """The first spec any instruction in *instructions* describes.

    Recurses into `sequence` steps: an effect written as two steps carries its
    targeting on the step that targets (Psionic Blast's damage to any target,
    followed by its self-damage; Orcish Artillery's ability, the same shape),
    and stopping at the wrapper would leave an otherwise fully-described effect
    with no prompt.
    """
    for instruction in instructions:
        if instruction.kind == "sequence":
            nested = _from_instructions(instruction.payload.get("steps") or ())
            if nested is not None:
                return nested
            continue
        if instruction.kind == "may":
            # An optional action still targets — "you may tap or untap target
            # creature" names a creature whether or not the offer is taken.
            #
            # `action` and `then` only. `otherwise` is the *declined* branch and
            # `reflexive` is a separate ability (CR 603.12) that chooses its own
            # targets when the payment creates it; reading either here would
            # report this instruction as targeting something it never picks —
            # and for the reflexive branch, at a moment when the choice has not
            # been offered yet.
            nested = _from_instructions(
                tuple(instruction.payload.get("action") or ())
                + tuple(instruction.payload.get("then") or ())
            )
            if nested is not None:
                return nested
            continue
        spec = _from_instruction(instruction)
        if spec is not None:
            return spec

    return None


def _from_instruction(instruction) -> dict | None:
    """The spec one instruction describes, or None when it describes none."""
    # A kind with several specs settles its own case first, because it is the
    # only reader that knows how to combine its payload with its `targets`
    # description — a colour-restricted counterspell carries both, and the
    # generic targets reading would drop the colour.
    from_payload = _KIND_TO_SPEC_FROM_PAYLOAD.get(instruction.kind)
    if from_payload is not None:
        return from_payload(instruction.payload)
    described = _from_targets_payload(instruction.payload.get("targets"))
    if described is not None:
        return described
    type_filter = instruction.payload.get("type_filter")
    if type_filter:
        kind = _kind_for_type_filter(type_filter)
        if kind is None:
            return None
        return {"kind": kind, **_narrowing_flags(instruction.payload)}
    by_kind = _KIND_TO_SPEC.get(instruction.kind)
    return dict(by_kind) if by_kind is not None else None


def _from_targets_payload(targets) -> dict | None:
    """The spec from a grammar-lowered ``targets`` description.

    This is the evidence the legacy rules never recorded: it is what tells
    Lightning Bolt ("any target") apart from Earthbind ("target creature with
    flying") when both compile to a bare ``deal_damage``.
    """
    if not isinstance(targets, dict):
        return None
    kind = targets.get("kind")
    if kind == "card":
        # A card in a graveyard is not a permanent (CR 115.2), and this function
        # only knows how to describe permanents, players and the stack. The
        # instruction that carries such a description settles its own spec in
        # `_KIND_TO_SPEC_FROM_PAYLOAD`; answering here would hand the picker a
        # battlefield when the effect reads a graveyard.
        return None
    if kind == "any":
        return {"kind": "any"}
    if kind == "divided":
        # Fireball: "X damage divided evenly … among any number of targets".
        # The UI picks the targets and X follows from how many were chosen, so
        # this is its own prompt rather than a repeated "any target".
        return {"kind": "divided"}
    if kind == "player":
        spec = {"kind": "player"}
        if targets.get("opponents_only"):
            # "Target opponent" — the caster's own seat is not a legal answer
            # (CR 115.4). The same flag Word of Command's kind-table entry
            # carries, enforced by legality's seat check.
            spec["opponents_only"] = True
        return spec
    if kind == "player_or_planeswalker":
        # Chandra's Magmutt: player faces plus planeswalker permanents — the
        # "any" picker minus its creature half.
        return {"kind": "player_or_planeswalker"}
    if kind == "spell":
        # A spell on the stack, which the UI picks from a different zone than
        # any permanent — "stack" is the name for that picker.
        return {"kind": "stack"}
    if kind != "object":
        return None
    filt = targets.get("filter") or {}
    # A description whose slots are *differently* restricted carries one filter
    # per slot. The picker enumerates one legal set for all of them, so a
    # narrowing may only be applied to that set when **every** slot has it —
    # otherwise the flag hides a target one slot legitimately admits, which is
    # what kept Garruk, Savage Herald's -2 from ever biting an opponent's
    # creature. Per-slot legality is the handler's, and it already enforced it.
    slot_filters = targets.get("filters")
    if isinstance(slot_filters, list) and len(slot_filters) > 1:
        per_slot = [_narrowing_flags(slot or {}) for slot in slot_filters]
        flags = {
            key: value
            for key, value in per_slot[0].items()
            if all(other.get(key) == value for other in per_slot[1:])
        }
    else:
        flags = _narrowing_flags(filt)
    # "Up to N target …", N > 1. The picker has to know the maximum, or it would
    # collect one target for a spell that names several — which is what the
    # instruction's own lowering refuses to emit until a handler reads a list.
    # Absent for every one-target description, so nothing downstream has to
    # special-case the common shape.
    count = targets.get("count")
    if isinstance(count, int) and count > 1:
        flags = {**flags, "max_targets": count}
    type_filter = filt.get("type_filter")
    if not type_filter:
        # A targeted object with no type restriction is any permanent.
        return {"kind": "permanent", **flags}
    derived = _kind_for_type_filter(type_filter)
    return {"kind": derived, **flags} if derived is not None else None


# The one spec kind whose chosen index is *not* a battlefield slot. Named
# rather than spelled out at each reader, because "is this index a graveyard
# index?" is asked in five places and a sixth that forgets is a spell reading a
# battlefield it never targeted.
GRAVEYARD_TARGET_KIND = "graveyard_creature"


def graveyard_target_spec(
    card, program, *, mode_index: int | None = None, instruction=None
) -> dict | None:
    """The spec of a chosen index that addresses a **graveyard**, else None.

    A card in a graveyard is not a permanent (CR 115.2) and the index that names
    it is a slot in a different list, so every reader that treats
    ``target_permanent_index`` as a battlefield slot has to ask this first. It
    used not to be asked at all: the cast-time protection check reads
    ``target.battlefield[slot]`` unconditionally, so Raise Dead naming graveyard
    slot 1 was refused because a White Knight happened to sit in battlefield
    slot 1 (CR 702.16b applied to a permanent the spell never targeted).

    Three callers, three ways of naming the same question — a spell
    (``derive_cast_spec``), one mode of a modal spell, and an ability or trigger
    that carries its own instruction. All three end at the same table, because
    what an instruction targets does not depend on what produced it.
    """
    if instruction is not None:
        spec = _from_instructions((instruction,))
    elif (
        mode_index is not None
        and program.modes
        and 0 <= mode_index < len(program.modes)
        and program.modes[mode_index].instruction is not None
    ):
        spec = _from_instructions((program.modes[mode_index].instruction,))
    else:
        spec = derive_cast_spec(card, program)
    if spec is not None and spec.get("kind") == GRAVEYARD_TARGET_KIND:
        return spec
    return None


def derive_activation_spec(ability) -> dict | None:
    """What *ability* chooses when it is activated, or None when it chooses
    nothing (CR 602.2b).

    Per ability rather than per card, and that is the whole difference from the
    cast side: a spell picks its targets once, while a permanent may carry
    several abilities that pick differently — Pyramids destroys an Aura with
    one and shields a land with the other, and classifying the *card* can only
    give one answer to a question with two.

    None is a positive answer ("this ability targets nothing"), not an absence,
    for the same reason it is on the cast side: the guard in
    `tests/engine/test_activation_targeting.py` fails if an ability whose line
    names a target answers None, so a parser change cannot turn a missing
    derivation into a silently target-free ability.
    """
    if not getattr(ability, "supported", False):
        return None
    instruction = getattr(ability, "instruction", None)
    if instruction is None:
        return None
    # A choosable cost is announced at CR 602.2b and the *instruction* cannot
    # describe it: the instruction is the effect, and the payment comes from
    # somewhere no effect here names. So it is derived from the cost and the two
    # answers are combined rather than one shadowing the other.
    cost_spec = _cost_picker_spec(getattr(ability, "cost", None))
    target_spec = _from_instructions((instruction,))
    if cost_spec is None:
        return target_spec
    # Diamond Valley's effect *is* its cost — the handler performs the sacrifice
    # — so the instruction's own spec already is the cost picker, and adding a
    # second would ask twice for one creature.
    if target_spec is not None and (
        target_spec.get("sacrifice_cost") or target_spec.get("discard_cost")
    ):
        return target_spec
    if target_spec is None:
        return cost_spec
    # Dwarven Weaponsmith: a real target *and* a cost, which CR 601.2c and
    # CR 601.2b make two separate announcements carrying two separate fields.
    # One spec cannot be both, so the cost rides beside the target under its own
    # key and the client runs two prompts — overloading one field is how the
    # cost came to eat the creature the ability was aimed at.
    return {**target_spec, "cost_spec": cost_spec}


def usable_activated_abilities(program):
    """The activated abilities of *program* the engine can actually run.

    An unsupported ability, or one that compiled to no instruction, is not
    activatable — so it is not offered a target prompt, and it is not counted
    when the web layer indexes a permanent's abilities. Shared so the index the
    UI sends back means the same ability the engine derived a spec for.
    """
    return [
        ability for ability in program.activated_abilities
        if ability.supported and ability.instruction is not None
    ]
