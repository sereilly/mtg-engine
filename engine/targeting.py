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
from .divided_damage import CHOSEN, DIVIDED_TARGETS, divided_entry
from .enter_effects import copy_on_enter_type
from .subject_filters import filter_head_noun

# "Enchant creature", "Enchant land", ... — but NOT "Enchant creature card in a
# graveyard" (Animate Dead), which targets a graveyard card rather than a
# permanent on the battlefield. The negative lookahead is load-bearing: without
# it Animate Dead derives "creature" and the UI would offer battlefield
# creatures for a reanimation spell.
# An "Enchant <subject>" clause is a **type** half and an optional **seat**
# half (CR 702.5's [quality]), and the two are independent: any of the five
# nouns can be printed with either seat clause. Spelling the combinations out
# as one flat alternation is what made "creature you control" have to be
# listed first — the alternation is first-match, so a plain "creature" would
# consume its prefix and leave " you control" to fail the whole-line anchor,
# which is a claim withdrawn rather than narrowed. Composing the halves
# instead means the tenth combination costs nothing, which is how "artifact an
# opponent controls" (Relic Bind — the only card in the pool printing it)
# arrived without a second entry.
_ENCHANT_NOUNS = ("creature", "land", "artifact", "enchantment", "wall")
_ENCHANT_SEAT_CLAUSES = {"you control": "you", "an opponent controls": "opponent"}
_ENCHANT_SUBJECT = (
    rf"(?:{'|'.join(_ENCHANT_NOUNS)})"
    rf"(?: (?:{'|'.join(_ENCHANT_SEAT_CLAUSES)}))?"
)
# Anchored at both ends, and read one printed line at a time. It used to be
# searched over the card's whole *normalized* text, which is space-joined - so
# Steal Artifact ("Enchant artifact" / "You control enchanted artifact") reads
# as one string in which "artifact you control" appears, and the clause gained
# a seat restriction the card never printed. The line structure is the only
# thing that says where the clause ends, so the reader keeps it.
_WHOLE_ENCHANT_LINE = re.compile(rf"^enchant ({_ENCHANT_SUBJECT})$")


def enchant_subject_seat(subject: str) -> tuple[str, str | None]:
    """Split an enchant subject into its noun and its seat requirement.

    ``"artifact an opponent controls"`` -> ``("artifact", "opponent")``; a bare
    noun -> ``(noun, None)``. The one place the two halves of the clause come
    apart, so the picker, the cast gate, the CR 704.5m sweep and the AI read
    one split rather than keeping four ``endswith`` tests between them.
    """
    for clause, seat in _ENCHANT_SEAT_CLAUSES.items():
        suffix = f" {clause}"
        if subject.endswith(suffix):
            return subject[: -len(suffix)].strip(), seat
    return subject, None


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

    The reader :func:`card_enchant_subject` runs over a card's printed
    lines, sharing its subject vocabulary so the two cannot drift. It exists so
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


def card_enchant_subject(oracle_text: str) -> str | None:
    """The "Enchant <subject>" clause *oracle_text* prints, or None.

    Per printed line, through the same :func:`enchant_line_subject` the grammar
    asks whether the line is claimed - so what the picker offers and what the
    parse-coverage gate calls accounted for are one reading. The line is
    *found*, not assumed to be the first: Capture Sphere prints "Flash" above
    it (see ``stack/casting.aura_enchant_noun``, which learned the same lesson).
    """
    for line in (oracle_text or "").splitlines():
        subject = enchant_line_subject(line)
        if subject is not None:
            return subject
    return None


_ENCHANT_NOUN_TO_SPEC: dict[str, dict] = {
    "creature": {"kind": "creature"},
    "wall": {"kind": "creature", "enchant_wall": True},
    "land": {"kind": "land"},
    "artifact": {"kind": "artifact"},
    "enchantment": {"kind": "permanent", "enchant_enchantment": True},
}

# The seat half of the clause as the picker's own flag. It is a seat test, not
# a permanent test, which is why `_enumerate_targets` applies it rather than
# `permanent_matches_filter` — and the cast gate, the CR 704.5m sweep and the
# AI enforce the same half through `enchant_noun_seat`.
_ENCHANT_SEAT_TO_FLAG = {"you": "own_only", "opponent": "opponent_only"}


def enchant_subject_spec(subject: str) -> dict | None:
    """The cast-time target spec an "Enchant <subject>" clause describes.

    "Enchant creature you control" (Cocoon) and "Enchant artifact an opponent
    controls" (Relic Bind) are one noun spec plus one flag, so the
    combinations are composed here rather than enumerated.
    """
    noun, seat = enchant_subject_seat(subject)
    spec = _ENCHANT_NOUN_TO_SPEC.get(noun)
    if spec is None:
        return None
    spec = dict(spec)
    flag = _ENCHANT_SEAT_TO_FLAG.get(seat)
    if flag is not None:
        spec[flag] = True
    return spec


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
    for key in ("attacking_only", "blocking_only", "flying_only"):
        if source.get(key):
            flags[key] = True
    # Carried by value, not flattened to a flag: "attacking or blocking" and
    # "tapped or blocking" are the same key with different words in it, and a
    # bare True would tell the picker a union applies without saying which one.
    any_states = source.get("any_states")
    if any_states:
        flags["any_states"] = list(any_states)
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
    elif source.get("controller") == "opponent":
        # "target artifact **an opponent controls**" (Hyperion Blacksmith). The
        # mirror of `own_only` and a seat test for the same reason, so it is the
        # picker's job rather than the permanent matcher's. Without it the
        # narrowing had nowhere to go: `permanent_matches_filter` cannot answer
        # a controller, so the lowering refused the line outright rather than
        # let a "an opponent controls" ability untap the activator's own
        # artifact — a restriction dropped in the player's favour.
        flags["opponent_only"] = True
    elif source.get("controller") == "defending_player":
        # "target artifact **defending player controls**" (Floral Spuzzem).
        # The third seat test, and the one the enumerator cannot answer on its
        # own: "you" and "opponent" are relative to the seat choosing, while
        # this one is relative to the *combat* the ability's trigger fired in.
        # So the flag says the narrowing exists and the caller that knows the
        # attack — the trigger's announcement — supplies the seat beside it.
        # With no seat supplied the enumerator offers nothing, which is the
        # safe direction: an unanswerable narrowing must never widen to "any".
        flags["defending_player_only"] = True
    if source.get("enchanted_only"):
        # "destroy target **enchanted** creature" (Ramses Overdark) — the
        # positive twin of ``not_enchanted`` below, and a picker flag for the
        # same reason: the enumerator narrows with the same matcher the handler
        # re-asks at resolution, so what is offered and what is destroyed cannot
        # disagree.
        flags["enchanted_only"] = True
    if source.get("not_enchanted"):
        # "target permanent **that isn't enchanted**" (Time Elemental) —
        # CR 303.4a. A picker flag rather than a restriction left to the
        # handler, and for the reason ``own_only`` above gives: the handler
        # already refuses an enchanted permanent at resolution, so a picker that
        # offered one would let a player tap the Elemental and pay {2}{U}{U} for
        # a bounce that then returns nothing, with nothing on screen saying why.
        flags["not_enchanted"] = True
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
    if source.get("blocked_by_source"):
        # "target creature **it's blocking**" (Goblin Snowman, Tinder Wall).
        # A relation to the ability's own source, so the enumerator applies it —
        # it holds the source, and ``permanent_matches_filter`` could not answer
        # it from the candidate alone. Without the flag the picker offered every
        # creature on the board for a ping the card aims at exactly one.
        flags["blocked_by_source"] = True
    if source.get("attacking_you"):
        # "target creature **that's attacking you**" (Ice Floe, Snow Fortress).
        # A seat test like ``own_only`` — which player the creature was declared
        # against — and the enumerator's for the same reason: the seat choosing
        # is the one it is relative to.
        flags["attacking_you"] = True
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
    "target_gains_life": {"kind": "any"},
    "remove_creature_from_combat": {"kind": "creature"},
    "grant_target_flying_until_eot": {"kind": "creature"},
    "simulacrum_redirect": {"kind": "creature"},
    "exile_creature_gain_life_equal_to_power": {"kind": "creature"},
    "bounce_target_creature": {"kind": "creature"},
    "phase_out_target_creature_until_source_leaves": {"kind": "creature"},
    "reanimate_creature": {"kind": "graveyard_creature", "own_graveyard_only": True},
    "exchange_ante_with_top_library": {"kind": "none"},
    # Dream Coat: "Enchanted creature becomes the color or colors of your
    # choice." The *permanent* is not chosen — an Aura's ability acts on its
    # own host (CR 303.4) — so there is no target picker; what the activator
    # chooses is a colour, which rides `mana_color` like every other CR 609.3
    # choice. A positive "nothing to point at", not an absent derivation:
    # without the row the ability answered None and the guard could not tell
    # the two apart.
    "recolor_enchanted_chosen_color": {"kind": "none"},
    # Shyft: the same positive "nothing to point at" — the sentence names
    # the source itself, so no picker is offered and none is missing.
    "recolor_self_chosen_color": {"kind": "none"},
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
    # Dark Sphere prints the same phrase and so runs the same prompt — a
    # permanent on any battlefield or a spell on the stack. What its shield then
    # does with the chosen source is the handler's business, not the picker's.
    "grant_half_prevention_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # Nova Pentacle: "The next time **a source of your choice** would deal damage
    # to you this turn…". The same prompt those two run — a permanent on any
    # battlefield or a spell on the stack — because it is the same printed
    # phrase. The creature that takes the redirected damage is *not* here: an
    # opponent picks it (CR 601.2c's chooser is not always the controller), so
    # it is a prompt the resolution arms rather than one this picker runs.
    "redirect_damage_from_chosen_source_until_eot": {
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
    "grant_target_ability_text": {"kind": "creature"},
    "add_named_counter_to_target": {"kind": "creature"},
    "grant_flying_and_delayed_destruction": {"kind": "creature"},
    "grant_unblockable_to_target": {"kind": "creature"},
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
    "look_at_target_library_top": {"kind": "player"},
    "discard_target_cards": {"kind": "player"},
    # "Search **target opponent's** graveyard, hand, and library …"
    # (Necromentia). The searched player is a target chosen as the spell is cast
    # (CR 601.2c); the *card name* is chosen on resolution and is not a target at
    # all, which is why the kind is a plain player rather than something
    # card-shaped.
    "name_and_strip": {"kind": "player"},
    "name_then_reveal_top": {"kind": "player"},
    # "Target opponent loses 2 life for each creature card in their graveyard."
    # (Liliana, Death Mage's ultimate.) The recipient is a seat; the per-each
    # count is read at resolution and names nothing.
    "target_loses_life": {"kind": "player"},
    # "Exchange life totals with target opponent." (Mirror Universe.) The other
    # seat is a target chosen as the ability is activated (CR 602.2b); the
    # controller's own half is not chosen at all.
    "exchange_life_totals": {"kind": "player"},
    # Cuombajj Witches. Its handler delegates the controller's half to
    # `deal_damage`, which takes a player or a permanent; the opponent's half is
    # a pending choice made after resolution, not a target chosen here.
    "deal_damage_and_opponent_choice": {"kind": "any"},
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
    described = getattr(cost, "exile_filter", None)
    if described is not None:
        # "Exile a creature you control" (City of Shadows) / "Exile a creature
        # card from your graveyard" (Necropolis). The sacrifice picker one zone
        # over: the *choice* is the same announcement (CR 601.2b), and only the
        # list it is made from differs. ``exile_cost`` is what tells the client
        # to send the answer on the cost field and to say "exile" rather than
        # "target" — a cost is not a target (idiom 10).
        if getattr(cost, "exile_zone", "battlefield") == "graveyard":
            spec = {
                "kind": GRAVEYARD_TARGET_KIND,
                "own_graveyard_only": True,
                "exile_cost": True,
            }
            wanted = described.get("type_filter")
            if isinstance(wanted, str):
                spec["card_type"] = wanted
            return spec
        spec = {
            "kind": filter_head_noun(described),
            "own_only": True,
            "exile_cost": True,
        }
        if described.get("exclude_self"):
            spec["exclude_source"] = True
        narrowing = {
            key: value
            for key, value in described.items()
            if key not in ("exclude_self", "controller")
            and not (key == "type_filter" and isinstance(value, str))
        }
        if narrowing:
            spec["filter"] = narrowing
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
            # ``own_only`` above already *is* "you control", so carrying the
            # seat again would be the same restriction written twice — and the
            # second copy would reach an enumerator with no observer, which
            # refuses every candidate rather than narrowing anything.
            if key not in ("exclude_self", "controller")
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
    any_classes = payload.get("any_classes")
    if any_classes:
        # "target instant or Aura spell" (Avoid Fate, Ring of Immortals) — the
        # cross-axis union, handed to the picker in the same shape the handler
        # tests, so the two cannot offer and counter different sets.
        spec["stack_any_classes"] = [list(entry) for entry in any_classes]
    targets_filter = payload.get("targets_filter")
    if targets_filter:
        # "…that targets a permanent you control". Offering a spell this
        # narrowing excludes would let Ring of Immortals be activated with
        # nothing it could legally counter — the cost paid for no effect.
        spec["stack_targets_filter"] = dict(targets_filter)
    if payload.get("targets_source"):
        # "…that targets **this creature**" (Mistfolk). The picker resolves the
        # word against the ability's own permanent, which `legality` has in hand
        # and this table does not — so the flag travels and the enumeration
        # answers it. Without it the ability offers every spell on the stack and
        # then counters nothing, which is the {U} paid for no effect the
        # narrowing beside it exists to prevent.
        spec["stack_targets_source"] = True
    return spec


def _chosen_permanent_spec(payload: dict) -> dict | None:
    """Whose battlefield a mid-resolution choice is drawn from.

    "You and **target player** exchange control of the creature you each control
    with the greatest mana value" (Juxtapose). The permanents are not targets —
    they are chosen as the spell resolves (CR 601.2c chose nothing but the
    player) — but the *player* is, and this instruction's ``controlled_by``
    is the only place the compiled program records it. ``_controlled_by_seat``
    reads the same word at resolution, so the seat the picker asks for and the
    seat the exchange draws from are one answer.

    The caster's own side answers None: "you" names no choice, and a spell whose
    every step named the caster would otherwise raise a player picker for a
    choice nobody makes.
    """
    if payload.get("controlled_by") == "target" or payload.get("chooser") == "target":
        return {"kind": "player"}
    return None


def _counter_ability_spec(payload: dict) -> dict | None:
    """"Counter target activated ability from an artifact source" (Rust, Ayesha
    Tanaka) — an *ability* on the stack, not a spell.

    The same "stack" picker a counterspell raises, because the object is chosen
    from the same zone; what differs is which objects it may offer, and every
    narrowing is handed over in the shape the handler tests it in
    (``ability_kinds``, ``source_card_types``). One reading, so the ability the
    picker offers and the ability the counter would actually counter are the
    same set — an offer the handler then refuses is a tap paid for nothing.

    "Counter **that** ability" (Imprison) chooses nothing: the object is the one
    its trigger fired on, found by identity. None is the answer there, exactly
    as it is for the counterspell's "counter it".
    """
    if payload.get("bound_to_trigger"):
        return None
    spec: dict = {
        "kind": "stack",
        "stack_ability_kinds": list(payload.get("ability_kinds") or ()) or ["activated", "triggered"],
    }
    source_types = payload.get("source_card_types")
    if source_types:
        spec["stack_ability_source_types"] = list(source_types)
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


def _graveyard_exile_spec(payload: dict) -> dict:
    """"Exile target card from a graveyard", narrowed to the card type it may
    take.

    Any seat's graveyard, so no ``own_graveyard_only`` — the picker is the
    reanimation one because the *choice* is identical; only where the card goes
    afterwards differs, and that is the handler's business.

    Derived from the payload rather than a fixed dict, for the reason
    :func:`_graveyard_return_spec` is: Return to Nature takes any card, Grave
    Robbers an artifact card and Eater of the Dead a creature card, and a fixed
    ``any_card`` spec would offer Grave Robbers a creature its own re-check then
    refuses. ``graveyard_card_matches`` reads the same keys in all three places.
    """
    spec: dict = {"kind": GRAVEYARD_TARGET_KIND}
    card_type = payload.get("card_type")
    if payload.get("any_card") or card_type is None:
        spec["any_card"] = True
    elif card_type != "creature":
        # "creature" is the enumerator's own default, so naming it changes
        # nothing; every other type is carried.
        spec["card_type"] = card_type
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
        spec = {
            "kind": "permanent",
            "color_filter": payload.get("prevention_color"),
            "also_stack": True,
        }
        colours = payload.get("prevention_colors")
        if colours:
            # "a black **or red** source of your choice". The picker narrows to
            # exactly what the shield will answer to, so the offer and the
            # recheck at damage time (CR 615.9) agree; dropping it here would
            # offer a green source for a shield that can never match one.
            spec["any_colors"] = list(colours)
        return spec
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
def _graveyard_to_library_spec(payload: dict) -> dict:
    """Drafna's Restoration's picker: cards of one type, in *any* graveyard.

    Not scoped to the caster's own — the spell names a target player, and the
    graveyard the cards come from is theirs. The maximum is deliberately absent:
    "any number" prints no ceiling, so the only cap is how many legal targets
    exist, which `cast_target_spec` fills in once it has enumerated them.
    """
    return {
        "kind": GRAVEYARD_TARGET_KIND,
        "card_type": payload.get("card_type", "artifact"),
        "unbounded_targets": True,
    }


def _retarget_spec(payload: dict) -> dict:
    """Reflecting Mirror: "target spell with a single target if that target is
    you" (CR 115.7a, CR 115.9a).

    The same "stack" picker a counterspell raises — the object is chosen from
    the same zone — narrowed by the one question this card asks about it. The
    count and the "is you" are **one** key rather than two because they are one
    question in the end: ``single_player_target`` answers "does this spell have
    exactly one target, and which player is it" or refuses, and splitting them
    would let a picker enforce half of a restriction whose halves are only
    meaningful together.

    Handed over in the shape the handler tests it in, so the spells offered and
    the spells the ability could actually re-aim are the same set — an offer the
    handler then refuses is {X} and a tap paid for nothing.
    """
    return {"kind": "stack", "stack_single_target_is": payload.get("current_target")}


_KIND_TO_SPEC_FROM_PAYLOAD = {
    "choose_new_target_player": _retarget_spec,
    "change_target_spell_target": _retarget_spec,
    "put_graveyard_cards_on_library_top": _graveyard_to_library_spec,
    "sacrifice_matching_permanent": _forced_sacrifice_spec,
    "target_gains_life": _life_gain_spec,
    "counter_top_stack_spell": _counter_spec,
    "counter_stack_ability": _counter_ability_spec,
    "choose_permanent": _chosen_permanent_spec,
    # Reverberation names a spell on the stack the same way a counter does, and
    # narrows it the same way ("target **sorcery** spell"), so it derives the
    # same picker — the spec is about what is being *chosen*, not about what is
    # then done to it.
    "redirect_damage_from_target_spell_until_eot": _counter_spec,
    "return_creature_from_graveyard_to_hand": _graveyard_return_spec,
    "exile_target_graveyard_card": _graveyard_exile_spec,
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

    enchant = card_enchant_subject(card.oracle_text)
    if enchant is not None:
        return enchant_subject_spec(enchant)

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
#: The wrappers a targeting instruction can be *inside*, and where each keeps
#: its steps. `if_then` carries both arms for the reason `_from_instructions`
#: reads both: CR 601.2c chooses an ability's targets when it is activated,
#: whichever way the condition later falls. It was missing here while
#: `_from_instructions` handled it by hand, so the spec recursed into a
#: conditional branch and every other reader of this table stopped at the
#: wrapper — which is how Lesser Werewolf's "target creature blocking or blocked
#: by this creature" reached `legality.py` as an `if_then` with no filter.
_WRAPPER_STEP_KEYS = {
    "sequence": ("steps",),
    "may": ("action", "then"),
    "if_then": ("then", "else"),
}


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
        if instruction.kind == "if_then":
            # "If you lose the flip, counter target artifact spell you control."
            # (Goblin Artisans.) A branch that may not run still *chooses* — CR
            # 601.2c and 602.2b pick targets as the ability is activated,
            # whichever way the coin lands — so both arms are read, and an
            # ability whose only targeting sits behind a conditional gets its
            # prompt rather than the picker's silent fallback.
            nested = _from_instructions(
                tuple(instruction.payload.get("then") or ())
                + tuple(instruction.payload.get("else") or ())
            )
            if nested is not None:
                return nested
            continue
        if instruction.kind == "unless_player_pays":
            # "Unless an opponent pays {2}, gain control of **target artifact**
            # …" (Scarwood Bandits). The ability's target sits on the *unpaid*
            # branch, and CR 601.2c picks it as the ability is activated —
            # before anyone is offered the cost — so this branch is read where
            # an offer's declined branch deliberately is not.
            nested = _from_instructions(
                tuple(instruction.payload.get("unpaid") or ())
            )
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
                # …and the **declined** branch, last. "Destroy target creature
                # unless its controller pays life equal to its toughness"
                # (Essence Vortex) puts the whole spell on this branch, and the
                # creature is a target of the *spell*: CR 601.2c picks it as the
                # spell is announced, before anybody is offered the payment, so
                # a picker that skipped this branch would leave the spell with
                # no prompt and the destruction pointed at nothing.
                #
                # Read after the two above rather than beside them, so an offer
                # that targets on both sides still answers with the branch it
                # takes. ``reflexive`` stays out: CR 603.12 makes it a separate
                # ability that chooses its own targets when the payment creates
                # it, which has not happened yet.
                + tuple(instruction.payload.get("otherwise") or ())
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
        if described.get("division") == CHOSEN:
            # **How much there is to divide**, so the picker can ask for a
            # division that totals it (CR 601.2d). Read off the payload here
            # rather than copied into the `targets` description at lowering: the
            # amount is the instruction's own field, and a second copy beside
            # the target description is a second thing to keep in step.
            # ``amount`` for damage and ``count`` for a distributed counter
            # placement — CR 601.2d covers both with one sentence, and each
            # instruction family spells its quantity with the word its own
            # handler reads. A variable ("x") is no total yet: the picker learns
            # it once the caster announces X, or the card defines one.
            amount = instruction.payload.get(
                "amount", instruction.payload.get("count", 0)
            )
            if isinstance(amount, int):
                described["division_total"] = amount
            described["division_x_bonus"] = int(
                instruction.payload.get("amount_bonus", 0) or 0
            )
        return described
    type_filter = instruction.payload.get("type_filter")
    if type_filter:
        kind = _kind_for_type_filter(type_filter)
        if kind is None:
            return None
        return {"kind": kind, **_narrowing_flags(instruction.payload)}
    by_kind = _KIND_TO_SPEC.get(instruction.kind)
    return dict(by_kind) if by_kind is not None else None


#: The spec ``kind`` a several-**role** target description takes.
#:
#: Every other kind names one picker over one list, because every other spell in
#: the pool chooses its targets from one set: "up to two target creatures" is two
#: slots of the same kind, and ``_enumerate_targets`` answers all of them at
#: once. "Target creature that **target Wall** blocked this turn" (Glyph of
#: Delusion) is not that. The two slots have different kinds, different
#: narrowings, and — the part no flag can express — the second slot's legal set
#: is decided by what was chosen for the first.
#:
#: So a roles spec carries an ordered ``roles`` list instead of a single kind,
#: and ``engine/legality.py`` enumerates role *n* only with roles 0…n-1 settled.
#: Anything that reads ``spec["kind"]`` and does not know this name sees a kind
#: it has no branch for, which is the loud direction: a roles spec silently
#: reduced to its first role would let a spell be cast with a target no gate
#: ever checked.
ROLES_TARGET_KIND = "roles"


def roles_spec(targets: dict) -> dict | None:
    """The ordered-role spec a ``kind: "roles"`` description means.

    Each role is itself an ordinary object description, so it goes through the
    same :func:`_from_targets_payload` every one-target spell does — the picker
    flags a role carries mean exactly what they mean anywhere else, and a
    narrowing added to that reader reaches a role for free.

    ``depends_on`` is lifted out of the role's own key so every consumer asks
    one question ("which earlier role settles this one?") rather than knowing
    the vocabulary of relations. The relation *key* travels beside it, because
    the enumerator has to know not merely that there is a dependency but what
    it asks of the pair.
    """
    roles: list[dict] = []
    for entry in targets.get("roles") or ():
        if not isinstance(entry, dict):
            return None
        described = _from_targets_payload({**entry, "kind": entry.get("kind", "object")})
        if described is None:
            return None
        described["role"] = entry.get("role")
        relation, depends_on = role_dependency(entry)
        if relation is not None:
            described["relation"] = relation
            described["depends_on"] = depends_on
        roles.append(described)
    if len(roles) < 2:
        # One role is not a roles description — it is an ordinary one-target
        # spell wearing a shape nothing else reads. Refusing here rather than
        # flattening it keeps the two shapes from both being able to mean the
        # same spell.
        return None
    return {"kind": ROLES_TARGET_KIND, "roles": roles}


#: What each dependent-role relation asks of the pair, given the *earlier*
#: role's chosen permanent and a candidate for the later one.
#:
#: One table, three readers: ``engine/legality.py`` narrows the picker with it,
#: the same module's gate re-asks it over the targets a caster named, and the
#: handler re-asks it once more at resolution (CR 608.2b). A relation whose
#: picker and whose re-check were separate tables is the defect this repo keeps
#: finding; here the *only* way to add a relation is to add it where all three
#: look.
#:
#: A relation the grammar can describe and this table does not know refuses —
#: ``legality`` offers nothing for it and the re-check answers False — because
#: an unanswerable narrowing must never widen to "any".
#:
#: Each test takes ``(earlier, candidate, game)``. The game is there for the
#: relations that are not readable off the two objects: control is CR 613
#: layer 2 and only ``Game.controller_index_of`` answers it, and a relation
#: that read ``base_controller_index`` instead would be a second opinion about
#: who controls what — the thing the control seam exists to abolish. A test
#: that does not need it simply ignores the argument.
ROLE_RELATION_TESTS = {
    # "target creature that **target Wall** blocked this turn" (Glyph of
    # Delusion). The record is stamped on the blocker by the declare-blockers
    # step and read by id, never by slot: both permanents may leave and return
    # between the cast and the resolution, and CR 400.7 makes the returning one
    # a different object.
    "blocked_by_role": lambda earlier, candidate, game: (
        candidate.permanent_id
        in set(earlier.metadata.get("blocked_attacker_ids_this_turn") or ())
    ),
    # "two target blocking creatures controlled by **the same opponent**"
    # (Sorrow's Path). Which opponent is not a property of either creature —
    # each role's own filter already says "an opponent controls this one", and
    # two roles carrying that filter would admit one blocker from each of two
    # opponents in a CR 802 multi-defender combat. The relation is what makes
    # the second choice depend on the first, and it is asked of the control
    # seam because control moves (CR 613 layer 2).
    "same_controller_role": lambda earlier, candidate, game: (
        game is not None
        and game.controller_index_of(earlier) is not None
        and game.controller_index_of(earlier) == game.controller_index_of(candidate)
    ),
}


def role_dependency(role: dict) -> tuple[str | None, str | None]:
    """*role*'s dependency as ``(relation key, earlier role name)``.

    One reader for **both** shapes a role is held in: the lowering's ``targets``
    payload, where the relation *is* the key (``"blocked_by_role": "blocker"``),
    and the derived spec, which lifts it into ``relation``/``depends_on`` so a
    picker can ask one question. Written once because the CR 608.2b re-check at
    resolution holds the payload while the picker holds the spec — and a reader
    that knew only the spec's spelling answered "no dependency" about the
    payload, which is a re-check that passes whatever the board says.
    """
    relation = role.get("relation")
    if isinstance(relation, str):
        depends_on = role.get("depends_on")
        return relation, depends_on if isinstance(depends_on, str) else None
    for key, value in role.items():
        if key.endswith("_role") and isinstance(value, str):
            return key, value
    return None, None


def role_relation_holds(role: dict, earlier, candidate, game=None) -> bool:
    """Whether *candidate* satisfies *role*'s dependency on *earlier*.

    True when the role has no dependency at all — the question does not arise
    for role 0 — and False whenever it has one this engine cannot answer or the
    earlier role resolves to nothing.

    *game* is passed by both callers (the picker in ``engine/legality.py`` and
    the CR 608.2b re-check in ``engine/handlers/_common.py``) and consumed by
    the relations that need it. It defaults to None so a relation asked without
    one refuses rather than answering from a narrower reading — the same
    direction an unknown relation takes.
    """
    relation, _depends_on = role_dependency(role)
    if relation is None:
        return True
    test = ROLE_RELATION_TESTS.get(relation)
    if test is None or earlier is None or candidate is None:
        return False
    return bool(test(earlier, candidate, game))


def spec_roles(spec: dict | None) -> list[dict]:
    """The ordered roles *spec* names, empty for every one-target spec.

    The one accessor, so a caller never has to test ``kind == "roles"`` *and*
    remember the key. An empty list is the honest answer for a spell that
    chooses one thing, and every loop written over it then reads the same for
    both shapes.
    """
    if not spec or spec.get("kind") != ROLES_TARGET_KIND:
        return []
    return list(spec.get("roles") or ())


def payload_role_slot(payload: dict | None, role: str | None) -> int | None:
    """Which slot of the chosen-target list *role* occupies, read straight off
    an instruction's own ``targets`` description.

    The resolution's form of :func:`role_slot`. A handler holds the payload the
    lowering wrote and not the derived spec, and re-deriving one to ask a
    question the payload already answers is the second reading this module
    exists to abolish. Same list, same order, one answer.
    """
    targets = (payload or {}).get("targets")
    if not isinstance(targets, dict) or targets.get("kind") != ROLES_TARGET_KIND:
        return None
    for index, entry in enumerate(targets.get("roles") or ()):
        if isinstance(entry, dict) and entry.get("role") == role:
            return index
    return None


def role_slot(spec: dict | None, role: str | None) -> int | None:
    """Which slot of the chosen-target list *role* occupies, or None.

    The wire, the stack item and the resolution all carry a spell's targets as
    one positional list, and for a roles spell that list is in **dependency
    order** — the order :func:`spec_roles` reports. This is the one translation
    from a role's name to its slot, so the handler that reads "the subject" and
    the where-clause that reads "the blocked creature" cannot disagree about
    which of the two the caster picked.
    """
    if role is None:
        return None
    for index, entry in enumerate(spec_roles(spec)):
        if entry.get("role") == role:
            return index
    return None


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
    if kind == "roles":
        return roles_spec(targets)
    if kind == "any":
        return {"kind": "any"}
    if kind == "divided":
        # Fireball: "X damage divided evenly … among any number of targets".
        # The UI picks the targets and X follows from how many were chosen, so
        # this is its own prompt rather than a repeated "any target".
        spec = {"kind": "divided", "division": targets.get("division", "evenly")}
        # "…among any number of **target creatures**" (Fire Covenant). The
        # printed noun, carried through so the picker offers what the card
        # names — without it the seat loop in `legality._enumerate_targets`
        # offers both players' faces, which is a legal Fire Covenant target
        # only in an engine that never read the noun.
        narrowing = targets.get("filter") or {}
        if narrowing.get("type_filter") == "creature":
            spec["creatures_only"] = True
        return spec
    if kind == "player":
        spec = {"kind": "player"}
        if targets.get("attacked_this_turn"):
            # "target player **who attacked this turn**" (Fire and Brimstone) —
            # the printed narrowing, carried to the seat loop that enforces it.
            spec["attacked_this_turn"] = True
        if targets.get("opponents_only"):
            # "Target opponent" — the caster's own seat is not a legal answer
            # (CR 115.4). The same flag Word of Command's kind-table entry
            # carries, enforced by legality's seat check.
            spec["opponents_only"] = True
        return spec
    if kind == "player_or_planeswalker":
        # Chandra's Magmutt: player faces plus planeswalker permanents — the
        # "any" picker minus its creature half.
        spec = {"kind": "player_or_planeswalker"}
        if targets.get("opponents_only"):
            # "Target **opponent** or planeswalker" (Eternal Flame): the same
            # union with the caster's own seat struck out (CR 115.4), carried on
            # the same flag the plain player picker above reads. Legality's seat
            # loop already asks it for this kind; without it here the flag never
            # reaches the loop and the caster is offered as a legal target.
            spec["opponents_only"] = True
        return spec
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
    elif count == "x":
        # "**X** target creatures" (Part Water, Winter Blast). The count is the
        # announced X, so there is no number here to be a maximum — and saying
        # nothing at all left the picker on its one-target default, which is
        # how Winter Blast came to tap a single creature in the browser while
        # its handler had read a list since round 23. Reported as a flag rather
        # than a number: how many the caster may name depends on what they can
        # pay, which is knowable at the picker and nowhere earlier.
        flags = {**flags, "x_targets": True}
    elif targets.get("unbounded"):
        # "One or more target creatures" names no maximum. `legality.py` turns
        # this into a `max_targets` once it knows how many legal targets exist,
        # which is the same route Drafna's Restoration's "any number of" takes.
        flags = {**flags, "unbounded_targets": True}
    type_filter = filt.get("type_filter")
    if not type_filter:
        # A targeted object with no type restriction is any permanent.
        return {"kind": "permanent", **flags}
    derived = _kind_for_type_filter(type_filter)
    return {"kind": derived, **flags} if derived is not None else None


def spec_only_subtype(spec: dict | None) -> str | None:
    """The one permanent subtype *spec* restricts its targets to, or None.

    "Can this spell target **only** Walls?" — the question Wall of Shadows asks
    of whatever is aiming at it (CR 115.1a: the target description is the phrase
    after "target"). It is a question about the *target description*, not about the source, so it is answered here, where the
    description was derived, rather than by a second reading of the source's
    oracle text.

    ``wall_only`` is ``_narrowing_flags``' own name for a Wall subtype filter,
    so this reads that flag rather than the payload it came from: a caller
    holding a spec holds the flag and not the filter, and inventing a second
    route to the same fact is how the picker and the restriction come to
    disagree. The generic ``filter`` branch is what a spec carrying its whole
    narrowing (``_from_instructions``' line-502 form) answers from, so a subtype
    that later grows a flag of its own needs nothing here.
    """
    if not spec:
        return None
    if spec.get("wall_only"):
        return "wall"
    described = spec.get("filter")
    if isinstance(described, dict):
        subtype = described.get("subtype_filter")
        if isinstance(subtype, str):
            return subtype
    return None


def bounce_subject_filter(payload: dict) -> dict:
    """What "Return target <noun> to its owner's hand" named, as a filter.

    One reading for the cast gate, because the payload spells the subject two
    ways and neither is the whole answer on its own: a several-target bounce
    ("up to two target creatures") describes its slots under ``targets``, while
    a one-target narrowed bounce carries ``filter``. A bare payload is
    Unsummon's, whose noun was "creature" — the default every other reader of
    this instruction kind already assumes.

    Read by the cast-time target gate and by the AI's "is this worth casting?"
    check, so neither of them re-reads the printed noun: it was ``is_creature``
    in one and ``primary_type == "creature"`` in the other, which is Unsummon's
    noun standing in for Boomerang's and Flash Flood's.
    """
    targets = payload.get("targets")
    if isinstance(targets, dict) and isinstance(targets.get("filter"), dict):
        return targets["filter"]
    described = payload.get("filter")
    if isinstance(described, dict):
        return described
    return {"type_filter": "creature"}


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


# ---------------------------------------------------------------------------
# What an object already *on* the stack announced (CR 115.9)
# ---------------------------------------------------------------------------

#: The cast-spec kinds whose announced target can be a **player's face**. A
#: spell whose spec is anything else chose an object, so it is never "a spell
#: whose single target is a player" however its stack item happens to be
#: filled in.
_PLAYER_TARGET_SPEC_KINDS = frozenset({
    "player", "any", "player_or_planeswalker", "divided",
})


def stack_object_mana_value(item) -> int:
    """The mana value of a spell on the stack (CR 202.3, CR 202.3b).

    The printed cost, **plus** whatever X was announced for each ``{X}`` in it:
    CR 202.3b says that while a spell is on the stack, an X in its mana cost is
    the chosen value, so Fireball cast for X=3 has mana value 4 and not 1. That
    is the whole difference from ``handlers/zones._mana_value_of``, which asks
    about a card in a graveyard — a zone where CR 107.3g pins X at 0.

    One reader, because the number is asked by things that must agree: a cost
    the card defines from it (Reflecting Mirror) and a counter that compares it
    against a chosen X (Spell Blast).
    """
    card = getattr(item, "card", None)
    if card is None:
        return 0
    base = int(getattr(card, "cmc", 0) or 0)
    x_symbols = (getattr(card, "mana_cost", "") or "").lower().count("{x}")
    if not x_symbols:
        return base
    return base + x_symbols * int(getattr(item, "x_value", 0) or 0)


def single_player_target(game, item) -> int | None:
    """The one player a spell on the stack chose as its **only** target
    (CR 115.9a / CR 115.9c), or None when it did not or the engine cannot say.

    Reflecting Mirror's "target spell with a single target if that target is
    you" is the question, and it is asked twice — by the picker in front of the
    activation and by the handler at resolution — so it is one function.

    **None is a refusal, not "no".** CR 115.9a counts what was chosen as the
    object was put on the stack, and this engine's stack item cannot always
    say: a seat and a chosen player reach it through the same
    ``target_player_index`` (which is why "every target is illegal" is not
    answerable for player-targeted spells, ROADMAP), and a modal spell's
    targets belong to the mode rather than to the card. Where the count cannot
    be established the spell is simply not offered — an under-offer is a
    narrower card, while an over-offer is a card redirecting spells it was
    never allowed to.

    So every way of *not* being a lone player target is checked first, and only
    then is the seat believed:

    * an **ability** on the stack has no card and is not a spell (CR 113.7a);
    * anything the item recorded that is not a player — a permanent, a
      graveyard card, another stack object — rules the question out at once,
      because ``target_player_index`` beside one of those is the battlefield or
      pile it names rather than a target;
    * a **modal** spell announces its targets per mode (CR 115.8, CR 700.2), and
      ``derive_cast_spec`` answers about mode 0 alone;
    * a **divided** spell records every target it chose in ``divided_targets``,
      so the count is read there and a face is the only single answer;
    * and the card itself has to be one that *can* target a player, asked of
      the compiled program rather than inferred from the field being filled in.
    """
    if getattr(item, "ability_instruction", None) is not None:
        return None
    card = getattr(item, "card", None)
    if card is None:
        return None
    if getattr(item, "chosen_modes", ()) or getattr(item, "chosen_mode_index", None) is not None:
        return None
    if item.target_permanent_index is not None or item.target_permanent_id is not None:
        return None
    if getattr(item, "target_graveyard_card", None) is not None:
        return None
    if getattr(item, "target_stack_item", None) is not None:
        return None

    seats = range(len(game.players))
    divided = (getattr(item, "choices", None) or {}).get(DIVIDED_TARGETS)
    if divided:
        if len(divided) != 1:
            return None
        seat, permanent_index, _share = divided_entry(divided[0])
        if permanent_index is not None:
            return None
        return int(seat) if int(seat) in seats else None

    seat = item.target_player_index
    if seat is None or seat not in seats:
        return None

    from .oracle import compile_card_oracle

    spec = derive_cast_spec(card, compile_card_oracle(card))
    if spec is None or spec.get("kind") not in _PLAYER_TARGET_SPEC_KINDS:
        return None
    if spec.get("land_filter"):
        # Volcanic Eruption's "X target Mountains" is a divided spell whose
        # targets are permanents; the seat beside them is a battlefield.
        return None
    if spec.get("max_targets") not in (None, 1):
        return None
    return int(seat)
