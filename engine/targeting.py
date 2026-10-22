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
ability's own instruction — the evidence tables are shared, because what an
instruction kind targets does not depend on whether a spell or an ability
produced it. `legality.py` classified activation from text until this existed;
`tests/engine/test_activation_targeting.py` holds the replacement in place.

**What is here, and where the rest went.** This module keeps the entry
points — :func:`derive_cast_spec`, :func:`derive_activation_spec`,
:func:`derive_instruction_spec` and the slot readers beside them — the
subject filters a handler reads off a payload, and what an object already on
the stack announced (CR 115.9). The evidence was split out of it at the
2,000-line cap, and every name a caller pulls from ``engine.targeting`` is
still exported here:

* ``engine/enchant_targets.py`` — an Aura's "Enchant <subject>" line;
* ``engine/cast_targets.py`` — what a cast announces: its mode, its kicker,
  the zone it leaves, an entry trigger's target;
* ``engine/instruction_targets.py`` — the walk over a program's
  instructions and the kind-keyed table;
* ``engine/payload_target_specs.py`` — the kinds read off their own payload;
* ``engine/target_descriptions.py`` and ``engine/target_roles.py`` — a
  lowering's ``targets`` description, and the several-role vocabulary;
* ``engine/cost_pickers.py`` — the picker a choosable cost needs;
* ``engine/picker_probes.py`` — the text probes the picker ratchets hold the
  derivation to.
"""

from __future__ import annotations

from .activation_zones import BATTLEFIELD, ability_functions_from
from .divided_damage import DIVIDED_TARGETS, divided_entry
from .target_roles import spec_roles
from .target_descriptions import GRAVEYARD_TARGET_KIND, _TYPE_FILTER_TO_KIND
from .cost_pickers import _cost_picker_spec
from .payload_target_specs import _X_FROM_COUNT
from .instruction_targets import (_first_described_slot, _from_instructions,
                                  _nested_steps)
from .cast_targets import (_as_kicked, _cast_cost_picker, _cast_target_spec,
                           _kickers_announced, announced_mode_instructions)

# Re-exported: names other modules pull from ``engine.targeting`` that moved
# out of it at the 2,000-line split (the docstring's last paragraph says where
# each went). This module stays their import path — several of their
# importers were being split by other groups in the same round — and new code
# may import a name from the module that defines it.
from .enchant_targets import (_ENCHANT_LAND_SUBTYPES, enchant_clause_nouns,
                              enchant_line_subject, enchant_subject_colours,
                              enchant_subject_keyword_exclusion,
                              enchant_subject_seat)
from .target_roles import (ROLES_TARGET_KIND, ROLE_SEATS, SEAT_ROLE_KINDS,
                           payload_own_role, payload_role_slot,
                           recorded_role_seats, role_dependency, role_is_seat,
                           role_relation_holds, role_seat_positions)
from .target_descriptions import (SINGLE_GRAVEYARD, _from_targets_payload,
                                  slot_list_is_exact)
from .cost_pickers import spec_is_a_cost
from .cast_targets import (cast_announced_entry_trigger,
                           entry_trigger_instructions)
from .picker_probes import line_names_a_cast_target


#: Set on a graveyard-target spec derived for a cast **out of a graveyard**:
#: the card being cast is in that pile as the caster looks at it and is not a
#: candidate. CR 601.2a moves the card to the stack as the *first* step of
#: casting it and CR 601.2c chooses targets two steps later, so by the time
#: there is anything to choose the spell is no longer a card in a graveyard.
#:
#: Flashback is what made it reachable (CR 702.34a): Coffin Purge's "exile
#: target card from a graveyard" flashed back out of a graveyard holding only
#: itself was offered itself, announced at itself, paid for and resolved
#: having exiled nothing, and Recoup granted flashback to the Recoup doing the
#: granting. A flag on the spec rather than a parameter to the enumerator,
#: because the spec is the one thing the picker, the announcement gate and
#: the no-legal-target gate are all handed — and it is set only where the
#: caller says which zone the cast leaves, so the resolution-time re-check
#: (which derives the spec with no zone) never sees it: the spell is on the
#: stack by then, and a *second copy* in the pile is a legal target.
CAST_FROM_GRAVEYARD = "cast_from_graveyard"


def as_cast_from(spec: "dict | None", from_zone: str) -> "dict | None":
    """*spec* as the announcement of a cast leaving *from_zone* reads it.

    Unchanged for every zone but a graveyard and for every spec that does not
    choose a graveyard card, so a caller may pass anything. Returns a copy:
    the derived specs below are built per call but the tables behind them are
    shared, and a flag written in place would follow the spec to a caller
    that named no zone.
    """
    if (
        spec is not None
        and from_zone == "graveyard"
        and spec.get("kind") == GRAVEYARD_TARGET_KIND
    ):
        return {**spec, CAST_FROM_GRAVEYARD: True}
    return spec


def derive_cast_spec(
    card, program, *, from_zone: str = "hand",
    optional_cost_payments: dict | None = None,
    mode_index: "int | None" = None,
) -> dict | None:
    """The cast-time spec of *card* cast from *from_zone*, or None when it
    chooses nothing.

    A spec that chooses a graveyard card is marked :data:`CAST_FROM_GRAVEYARD`
    when the cast itself leaves a graveyard (:func:`as_cast_from`).
    """
    return as_cast_from(
        _derive_cast_spec(
            card, program, from_zone=from_zone,
            optional_cost_payments=optional_cost_payments,
            mode_index=mode_index,
        ),
        from_zone,
    )


def _derive_cast_spec(
    card, program, *, from_zone: str = "hand",
    optional_cost_payments: dict | None = None,
    mode_index: "int | None" = None,
) -> dict | None:
    """:func:`derive_cast_spec` before the zone the cast leaves is read onto
    the target half.

    *mode_index* is the mode a "Choose one —" spell was announced with
    (CR 601.2b): the spec is then **that mode's**, through
    :func:`announced_mode_instructions`. A caller that names none is asking
    about a cast that named none, which resolves mode 0.

    None is the answer for a permanent whose only targeting belongs to an
    activated ability — Royal Assassin picks its victim when the ability is
    activated, not when the creature is cast.

    A printed additional cost is picked as the spell is cast and belongs to the
    *cost*, so it is read from the cost table rather than from any instruction;
    ``sacrifice_cost`` / ``discard_cost`` / ``exile_cost`` are what tell the
    client to send it on the cost field and to say "sacrifice" rather than
    "target".
    """
    cost_spec = _cast_cost_picker(
        card, from_zone, announced=optional_cost_payments
    )
    # CR 702.33g: a kicked-only part's targets are chosen only if the spell was
    # kicked. Answerable exactly when the caller says what CR 601.2b's
    # announcement is so far -- *optional_cost_payments*, the same map that
    # decides the cost picker one line up -- and only for a card that prints a
    # kicker at all. A caller that passes none is asking about the card, and
    # gets every arm.
    target_spec = _cast_target_spec(
        card, program,
        kickers=_kickers_announced(card, optional_cost_payments),
        mode_index=mode_index,
    )
    if cost_spec is None:
        return target_spec
    if target_spec is None:
        return cost_spec
    # A spell whose *effect* is the payment (a forced sacrifice read off the
    # instruction) already is the cost picker, and a second one would ask twice
    # for one permanent. The same guard ``derive_activation_spec`` makes for
    # Diamond Valley, one announcement step over.
    if (
        target_spec.get("sacrifice_cost")
        or target_spec.get("discard_cost")
        or target_spec.get("exile_cost")
    ):
        return target_spec
    # Demonic Embrace, Goblin Grenade, Soul Exchange: a real target *and* a
    # cost, which CR 601.2b and CR 601.2c make two separate announcements
    # carrying two separate fields. One spec cannot be both, so the cost rides
    # beside the target under its own key and the client runs two prompts —
    # this is `derive_activation_spec`'s Dwarven Weaponsmith case on the cast
    # side, and it was missing here: the cost was returned *instead of* the
    # target, so the Aura was never asked what to enchant and the engine refused
    # the cast it had itself described.
    return {**target_spec, "cost_spec": cost_spec}


def cast_target_slot(
    card, program, *, optional_cost_payments: dict | None = None,
    mode_index: "int | None" = None,
) -> "tuple[dict, object] | None":
    """``(spec, instruction)`` for the target an **instant or sorcery**
    announces as it is cast: the target half of :func:`derive_cast_spec`
    beside the instruction that carries it, or None when the spell targets
    nothing.

    For CR 601.2c's other question. The spec says *what* may be chosen; whether
    a choice **must** be made is that one slot's printed quantifier, which only
    the instruction keeps — see :func:`_first_described_slot`. Read through the
    same :func:`_as_kicked` view the spec is (CR 702.33g), so a kicked-only
    target is a slot only for a cast that was kicked.

    A permanent spell answers None: its spec is an Aura's enchant line or an
    entry trigger's target, neither of which is a step of the spell's own
    resolution, and each has its own gate.

    *mode_index* names the chosen mode of a modal spell, whose steps are then
    the ones read (:func:`announced_mode_instructions`).
    """
    type_line = card.type_line.lower()
    if "instant" not in type_line and "sorcery" not in type_line:
        return None
    instructions = announced_mode_instructions(program, mode_index)
    kickers = _kickers_announced(card, optional_cost_payments)
    if kickers is not None:
        instructions = _as_kicked(instructions, kickers)
    return _first_described_slot(instructions)


def instructions_as_announced(
    card, program, optional_cost_payments: dict | None,
    *, mode_index: "int | None" = None,
) -> tuple:
    """*program*'s instructions as a cast announcing *optional_cost_payments*
    will run them: the :func:`_as_kicked` view for a card that prints a kicker
    and a caller that has CR 601.2b's answer, the program itself otherwise.

    For a reader that needs the **step** an announcement is about rather than
    its picker spec — today the casting path's division gate
    (``divided_damage.divided_description``). "Magma Burst deals 3 damage to
    any target. If this spell was kicked, it deals 3 damage to another target."
    and "Prevent the next 3 damage … divided as you choose. If this spell was
    kicked, prevent the next 6 damage this way instead." (Pollen Remedy) both
    keep their divided step under a ``was_kicked`` arm, and which arm it is
    decides how many targets are named and what the shares must total
    (CR 601.2c, CR 601.2d). Read off the card's every arm, that gate found no
    divided step at all — it walks a ``sequence`` and nothing else — so a
    kicked Magma Burst announced two targets, had no share stamped on either,
    and resolved the even split of 3: one damage each.

    *mode_index* is the chosen mode of a modal spell
    (:func:`announced_mode_instructions`): the steps a "Choose one —" cast
    will run are that mode's, so a division printed in one mode is a division
    only of a cast that chose it.
    """
    instructions = announced_mode_instructions(program, mode_index)
    kickers = _kickers_announced(card, optional_cost_payments)
    if kickers is None:
        return instructions
    return _as_kicked(instructions, kickers)


def derive_cast_target(card, program, *, from_zone: str = "hand") -> str | None:
    """The cast-time target *kind* of *card*, for callers that need no flags."""
    spec = derive_cast_spec(card, program, from_zone=from_zone)
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


def derive_instruction_spec(instructions) -> dict | None:
    """The target spec a bare instruction sequence describes, or None for none.

    The entry point for a sequence that is nobody's ability line: CR 603.12's
    reflexive triggered ability is created mid-resolution and chooses its own
    targets then, so there is no `ability` object to hand
    :func:`derive_activation_spec`. Same reader underneath, so what a reflexive
    ability offers and what an activated one offers cannot disagree.
    """
    return _from_instructions(instructions)


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


#: Keys a ``destroy_target_permanent`` payload carries that are **not** part of
#: the printed noun phrase. Everything else is, which is the direction that
#: matters: a key left off a hand-written *inclusion* list is a narrowing
#: silently dropped, and a dropped narrowing is an ability destroying more than
#: the card allows. Naming the exclusions instead means a new filter key is
#: enforced the day the lowering starts emitting it.
_DESTROY_NON_SUBJECT_KEYS = frozenset({
    # How the announcement was shaped, not what it may name.
    "targets",
    # CR 701.19c's rider, applied by the destruction itself.
    "bypass_regeneration",
    # The scratchpad channel another seat's choice was recorded on (The Abyss);
    # the handler reads it as *the* victim rather than as a description.
    "permanents_from",
    # "…with mana value X" (Detonate, Kaervek's Purge). The one restriction with
    # no literal to test at picker time: the caster announces the target and the
    # X together (CR 601.2b then 601.2c), so narrowing here would offer nothing
    # at all. `_validate_cast_targets` checks the pair where both halves exist.
    "mv_equals_x",
})


def destroy_subject_filter(payload: dict) -> dict:
    """What "Destroy target <noun phrase>" named, as a filter payload.

    One reading shared by the picker, the cast gate and the resolution, so the
    three cannot disagree about which permanents a destroy may name. It used to
    be three: the picker and the cast gate handed the *whole* payload to
    ``permanent_matches_filter`` — the pure half of the matcher, which has no
    game and therefore silently ignores every seat-, keyword- and
    source-relative key — and the resolution forwarded eight keys by hand.
    Merfolk Assassin's "target creature with islandwalk" destroyed a vanilla
    Bear through all three.
    """
    return {
        key: value for key, value in payload.items()
        if key not in _DESTROY_NON_SUBJECT_KEYS
    }


def cast_time_count_spec(program, *, mode_index: int | None = None) -> dict | None:
    """The count a spell's own where-clause takes **as it is cast**, or None.

    CR 601.2b: "…, where X is the number of black permanents target opponent
    controls **as you cast this spell**" (Reap). The words move the count from
    CR 608.2's resolution to the announcement, and that is not a nicety — the
    same X sizes the spell's target list, so CR 601.2c's "once the number of
    targets is determined, that number doesn't change" has nothing to fix it to
    unless the number exists before the targets are named.

    Derived from the **compiled program** rather than from a second reading of
    the card's text, which is what separates this from
    ``cost_x_definitions``'s three regex tables one file over. Those read a
    whole printed line and answer from the board; this clause is the tail of the
    sentence it modifies, so the parser has already read it, and a regex here
    would be a second reader of a sentence the grammar owns — free to disagree
    with the lowering about which board is counted.

    The top level alone is scanned: ``_stamp_x_from_count`` writes the spec onto
    every instruction of the sentence *including* the wrappers, so a nested step
    can never carry one its parent does not.
    """
    instructions = tuple(getattr(program, "instructions", ()) or ())
    modes = tuple(getattr(program, "modes", ()) or ())
    if modes:
        chosen = (
            modes[mode_index]
            if isinstance(mode_index, int) and 0 <= mode_index < len(modes)
            else None
        )
        candidates = (
            (chosen.instruction,) if chosen is not None and chosen.instruction is not None
            else tuple(
                mode.instruction for mode in modes if mode.instruction is not None
            )
        )
        instructions = instructions + candidates
    for instruction in instructions:
        spec = getattr(instruction, "payload", None)
        spec = spec.get(_X_FROM_COUNT) if isinstance(spec, dict) else None
        if isinstance(spec, dict) and spec.get("as_cast"):
            return spec
    return None


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
    else:
        spec = derive_cast_spec(card, program, mode_index=mode_index)
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
    # …and an ability that points at **nothing** is the same case: the cost
    # picker is the whole prompt. Two spellings reach here — ``None`` (the
    # program carries no evidence) and ``{"kind": "none"}`` (the derivation
    # saying positively that the sentence chooses nothing, which
    # ``grant_self_keyword_until_eot`` now does) — and they are one answer to
    # this question. Seasoned Hallowblade is the card that says so: "{1},
    # Discard a card: This creature gains indestructible until end of turn."
    # names no target at all, and its prompt is the discard.
    if target_spec is None or target_spec.get("kind") == "none":
        return cost_spec
    # Dwarven Weaponsmith: a real target *and* a cost, which CR 601.2c and
    # CR 601.2b make two separate announcements carrying two separate fields.
    # One spec cannot be both, so the cost rides beside the target under its own
    # key and the client runs two prompts — overloading one field is how the
    # cost came to eat the creature the ability was aimed at.
    return {**target_spec, "cost_spec": cost_spec}


def activation_target_slot(ability) -> "tuple[dict, object] | None":
    """``(spec, instruction)`` for the target *ability* announces as it is
    activated: the target half of :func:`derive_activation_spec` beside the
    instruction that carries it, or None when the ability targets nothing.

    :func:`cast_target_slot`'s twin, for CR 601.2c's other question asked of an
    activation (CR 602.2b sends one through CR 601.2b–i). The spec says *what*
    may be chosen; whether a choice **must** be made is that one slot's printed
    quantifier, which only the instruction keeps. Read through the same
    :func:`_first_described_slot` the spec is, so the slot whose quantifier is
    asked is the slot the picker describes — a second walk beside it is how
    "does this ability owe a target?" came to be answered about a different
    sentence than the one the picker offered targets for.
    """
    if not getattr(ability, "supported", False):
        return None
    instruction = getattr(ability, "instruction", None)
    if instruction is None:
        return None
    return _first_described_slot((instruction,))


def usable_activated_abilities(program, *, zone: str = BATTLEFIELD):
    """The activated abilities of *program* the engine can actually run **from
    *zone***.

    An unsupported ability, or one that compiled to no instruction, is not
    activatable — so it is not offered a target prompt, and it is not counted
    when the web layer indexes a permanent's abilities. Shared so the index the
    UI sends back means the same ability the engine derived a spec for.

    *zone* is CR 113.6 (``engine/activation_zones.py``), and it defaults to the
    battlefield because that is the rule's own default and what every caller of
    this function meant before cycling arrived. It is not a refinement: an
    ability that functions only from a hand — cycling, Waker of Waves — was
    offered on the battlefield by this list, which is what let a card discard
    itself while sitting in play and stay there. The filter is here rather than
    at each caller because *this list is the index*: the web layer, the AI and
    ``queue_permanent_ability`` all address an ability by its position in it,
    so a caller filtering afterwards would renumber only itself.
    """
    return [
        ability for ability in program.activated_abilities
        if ability.supported and ability.instruction is not None
        and ability_functions_from(ability) == zone
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


def spec_offers_a_player(spec: dict | None) -> bool:
    """Whether *spec*'s picker offers a **player's face** at all (CR 115.1).

    The one answer to "may the seat this announcement names be a target?",
    read by the three places that have to agree about it:
    ``legality._enumerate_targets`` (which seats the picker lists),
    ``legality.cast_target_refusal`` (whether a seat named with no object
    beside it is held to that list, CR 601.2c) and
    ``legality.illegal_targets_refusal`` (whether it is re-asked at resolution,
    CR 608.2b).

    A player kind, less the two divided shapes whose printed noun admits no
    player: "…among any number of **target creatures**" (Fire Covenant) and "X
    **target Mountains**" (Volcanic Eruption). The seat beside one of those is
    the battlefield its permanents sit on — or the seat every cast carries —
    and comparing it against a list of faces would refuse a legal cast.
    """
    return (
        bool(spec)
        and spec.get("kind") in _PLAYER_TARGET_SPEC_KINDS
        and not spec.get("land_filter")
        and not spec.get("creatures_only")
    )


#: The spec kind of a picker over the **stack** — a spell or an ability there
#: and nothing else — and, since Suffocating Blast, the kind of a *role* whose
#: object is one. A role is "itself an ordinary object description"
#: (:func:`roles_spec`), so its kind is the one-target kind for the same slot.
STACK_TARGET_KIND = "stack"


def role_is_stack(role: dict | None) -> bool:
    """Whether *role*'s object is a spell or ability on the stack.

    :func:`role_is_seat`'s sibling, for the same readers: the walk that turns
    a candidate back into an object, the gate that fills each slot from the
    channel it travels on, the stamp reader and the resolution. A role's
    object is a permanent unless one of these says otherwise, and a reader
    that did not ask would look a stack slot up on a battlefield.
    """
    return bool(role) and role.get("kind") == STACK_TARGET_KIND


def spec_names_the_stack(spec: dict | None) -> bool:
    """Whether an announcement under *spec* may name an **object on the
    stack** (CR 601.2c) — as its target, as one of two zones its target may
    be in, as CR 609.7a's chosen source, or as one role of several.

    The one answer to "has ``target_stack_index`` anything to say here?", for
    the gate that refuses a stack object named where it has not
    (``legality.stray_stack_target_refusal``, and its activation twin). Four
    shapes, because the stack reaches a spec four ways: the ``stack`` kind (a
    counter, a copy, a retarget), ``spell_or_permanent`` (the Laces, Illusion,
    Unsubstantiate), the ``also_stack`` flag on a chosen-source picker (Circle
    of Protection, Reverse Damage) and a ``stack`` **role** beside a permanent
    or a seat (Suffocating Blast).
    """
    if not spec:
        return False
    if spec.get("kind") in (STACK_TARGET_KIND, "spell_or_permanent"):
        return True
    if spec.get("also_stack"):
        return True
    return any(role_is_stack(role) for role in spec_roles(spec))


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


#: The cast-spec kinds whose announced target is an **object on the
#: battlefield**. Derived from the table that turns a printed type filter into
#: a picker rather than listed a second time, so a new noun phrase reaches this
#: reader for free; "any target" and "player or planeswalker" join it because
#: either may have been aimed at an object rather than at a face.
_PERMANENT_TARGET_SPEC_KINDS = frozenset(_TYPE_FILTER_TO_KIND.values()) | {
    "any", "player_or_planeswalker",
}


def _lone_permanent_target(game, item) -> int | None:
    """The single battlefield object *item* announced, **by identity**, or None.

    Identity rather than slot for CR 400.7's reason: the index recorded at cast
    time is a position in a battlefield list, and anything leaving in between
    renumbers every later slot. The id is preferred and the index is only the
    fallback for an item nothing stamped.

    A target that has since **left** still answers with its id. CR 115.9a counts
    what was chosen as the object was put on the stack, not what is still legal
    — and CR 115.7a is explicit that a target may be changed "even if the
    original target is itself illegal by then", so a spell whose creature died
    is exactly the spell a retarget is for.
    """
    ids = getattr(item, "target_permanent_id", None)
    if ids is not None:
        chosen = list(ids) if isinstance(ids, (list, tuple)) else [ids]
        if len(chosen) != 1 or not isinstance(chosen[0], int):
            return None
        return int(chosen[0])
    idxs = getattr(item, "target_permanent_index", None)
    if idxs is None:
        return None
    chosen = list(idxs) if isinstance(idxs, (list, tuple)) else [idxs]
    if len(chosen) != 1 or not isinstance(chosen[0], int):
        return None
    seat = getattr(item, "target_player_index", None)
    if seat is None or not (0 <= seat < len(game.players)):
        return None
    # The one sanctioned direction for an index: through the seam's bridge,
    # once, and carried as an id from here on.
    found = game.permanent_at(seat, chosen[0])
    return None if found is None else game.permanent_id_of(found)


def spell_targets(game, item) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Every seat and every permanent a spell on the stack chose (CR 601.2c).

    ``(seats, permanent_ids)``. :func:`single_spell_target`'s question without
    the CR 115.9a count on it: that one answers "what is this spell's *only*
    target", for a retarget that has to know there is just one, and refuses
    everything it cannot be certain about. This one answers "what did it point
    at at all", which is what a trigger watching for a spell aimed at its
    controller asks (Reparations), and it is allowed to name several.

    The two hazards are the ones that function documents, met the same way:

    * ``target_player_index`` is a **battlefield** beside a permanent index, not
      a target, so a seat is believed only when the card's compiled program says
      the spell can target a player at all. Read the field regardless and
      Reparations would draw off every removal spell pointed at anybody.
    * a **divided** spell records each of its targets separately, so both kinds
      are read out of that record rather than off the two scalar fields.

    Permanent targets are taken by id from the same stamp
    ``_announce_targeting`` reads, because a slot renumbers (CR 400.7) and the
    ids are settled before any trigger is announced.
    """
    from .oracle import compile_card_oracle
    from .stack_targets import permanent_spell_targets_nothing

    card = getattr(item, "card", None)
    if card is None or getattr(item, "ability_instruction", None) is not None:
        return (), ()
    if permanent_spell_targets_nothing(item):
        # CR 115.1: a creature, artifact, enchantment or planeswalker spell
        # that is not an Aura targets nothing. What its fields hold is its
        # entry trigger's target, named as the permanent is cast and chosen —
        # by CR 115.1d — as that trigger is put on the stack. Read here, a
        # Man-o'-War cast at a Grizzly Bears was "a spell that targets a
        # creature you control" and Reparations drew for it: 34 of the 55
        # (permanent, kind of target) casts in the pool.
        return (), ()
    seats: list[int] = []
    permanents: list[int] = []
    living = range(len(game.players))

    divided = (getattr(item, "choices", None) or {}).get(DIVIDED_TARGETS)
    if divided:
        for entry in divided:
            seat, permanent_index, _share = divided_entry(entry)
            if permanent_index is None:
                if int(seat) in living and int(seat) not in seats:
                    seats.append(int(seat))
                continue
            found = game.permanent_at(int(seat), permanent_index)
            if found is not None and found.permanent_id not in permanents:
                permanents.append(found.permanent_id)
        return tuple(seats), tuple(permanents)

    ids = getattr(item, "target_permanent_id", None)
    for permanent_id in (ids if isinstance(ids, (list, tuple)) else [ids]):
        if isinstance(permanent_id, int) and permanent_id not in permanents:
            permanents.append(permanent_id)
    if permanents:
        return (), tuple(permanents)

    seat = getattr(item, "target_player_index", None)
    if seat is None or seat not in living:
        return (), ()
    spec = derive_cast_spec(card, compile_card_oracle(card))
    if spec is None or spec.get("kind") not in _PLAYER_TARGET_SPEC_KINDS:
        return (), ()
    if spec.get("land_filter"):
        # Volcanic Eruption's "X target Mountains": the seat beside them is a
        # battlefield, exactly as it is above.
        return (), ()
    return (int(seat),), ()


def stack_object_target_spec(item) -> dict | None:
    """The spec the object *item* chose its targets by, or None when this
    engine cannot say.

    One reader for the two kinds of thing that sit on a stack, because
    :func:`single_spell_target` and ``handlers/stack._legal_new_targets`` both
    have to ask it and neither may get a different answer. A **spell** answers
    from the card's compiled program (CR 601.2c); an **ability** cannot —
    ``derive_cast_spec`` would hand back the spec of whatever the *card* does
    when cast, which for Silver Wyvern's Drake is nothing at all and for a
    creature with both a cast target and an ability target is the wrong list.

    So an ability answers from the instruction it carries, which is the target
    half of :func:`derive_activation_spec` — that function's other half is the
    *cost* picker (CR 602.2b), and a cost was paid before this object reached
    the stack. Asking for it here would offer a sacrifice prompt's spec as if it
    were the ability's target.

    A hook-keyed stack object (``hook_key`` with no instruction) answers None:
    it has no compiled program at all, and an under-offer is a narrower card
    while an over-offer re-aims something the rule never let it touch.
    """
    if getattr(item, "is_ability", False):
        instruction = getattr(item, "ability_instruction", None)
        if instruction is None:
            return None
        return _from_instructions((instruction,))
    card = getattr(item, "card", None)
    if card is None:
        return None
    from .oracle import compile_card_oracle
    from .stack_targets import permanent_spell_targets_nothing

    if permanent_spell_targets_nothing(item):
        # A permanent spell that is not an Aura chose no targets (CR 115.1),
        # so there is no spec it chose them *by*. ``derive_cast_spec`` answers
        # for it all the same — with its entry trigger's picker, which is the
        # question "what does the cast name" and not this one.
        return None
    return derive_cast_spec(card, compile_card_oracle(card))


def single_spell_target(game, item) -> dict | None:
    """What a spell **or ability** on the stack chose as its **only** target
    (CR 115.9a / CR 115.9c), or None when it chose several, chose something this
    engine cannot re-aim, or the count cannot be established.

    ``{"kind": "player", "seat": n}`` or ``{"kind": "permanent",
    "permanent_id": n}`` — a descriptor rather than a bare seat, because the two
    answers are the same question ("what is this spell's one target?") and a
    reader that could only say "player" is a reader Deflection cannot use.

    "Target spell with a single target" is asked twice of every card that
    prints it — by the picker in front of the cast and by the handler at
    resolution — so it is one function.

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

    * a **graveyard** card or another **stack object** rules the question out at
      once: neither is a target this engine's retarget can offer a replacement
      for, and an under-offer is a narrower card while an over-offer is a card
      re-aiming spells it was never allowed to;
    * a **modal** spell announces its targets per mode (CR 115.8, CR 700.2), and
      ``derive_cast_spec`` answers about mode 0 alone;
    * a **divided** spell records every target it chose in ``divided_targets``,
      so the count is read there and a face is the only single answer;
    * and the card itself has to be one that *can* target the kind of thing its
      stack item is filled in with, asked of the compiled program rather than
      inferred from the field being set — a seat and a chosen player reach the
      item through the same ``target_player_index``, and beside a permanent
      index that field is a *battlefield* rather than a target.
    """
    # An ability is not a spell (CR 113.7a) and it used to stop here, which was
    # right while the only readers were counterspells. It is not right for
    # CR 115.7a: an ability announced its targets at CR 602.2b exactly as a
    # spell announced them at CR 601.2c, and Silver Wyvern re-aims either. What
    # differs is only *which program* says how many targets there are, and
    # ``stack_object_target_spec`` is the one place that decides.
    from .stack_targets import permanent_spell_targets_nothing

    card = getattr(item, "card", None)
    if card is None:
        return None
    if permanent_spell_targets_nothing(item):
        # **A permanent spell that is not an Aura has no targets to count**
        # (CR 115.1; CR 115.9a counts "the number of targets chosen for" the
        # object). Its fields carry its entry trigger's target, named as it is
        # cast, and read as the spell's own that made a Man-o'-War "a spell
        # with a single target": Deflection's picker offered it, Meddle's did,
        # and the change rewrote what the *trigger* would later take as
        # announced — 45 of 55 casts in the pool. The trigger is the object
        # that targets, and it is asked as an ability, below.
        return None
    if getattr(item, "chosen_modes", ()) or getattr(item, "chosen_mode_index", None) is not None:
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
            # A divided *object* target. CR 115.7f keeps the division, so the
            # share would have to travel to the new permanent — and the entry
            # records a battlefield slot rather than an id, which is the one
            # shape ``_lone_permanent_target`` cannot answer by identity.
            return None
        return {"kind": "player", "seat": int(seat)} if int(seat) in seats else None

    if item.target_permanent_index is not None or item.target_permanent_id is not None:
        permanent_id = _lone_permanent_target(game, item)
        if permanent_id is None:
            return None
        spec = stack_object_target_spec(item)
        if spec is None or spec.get("kind") not in _PERMANENT_TARGET_SPEC_KINDS:
            return None
        if spec.get("unbounded_targets") or spec.get("max_targets") not in (None, 1):
            return None
        return {"kind": "permanent", "permanent_id": permanent_id}

    seat = item.target_player_index
    if seat is None or seat not in seats:
        return None

    spec = stack_object_target_spec(item)
    if spec is None or spec.get("kind") not in _PLAYER_TARGET_SPEC_KINDS:
        return None
    if spec.get("land_filter"):
        # Volcanic Eruption's "X target Mountains" is a divided spell whose
        # targets are permanents; the seat beside them is a battlefield.
        return None
    if spec.get("max_targets") not in (None, 1):
        return None
    return {"kind": "player", "seat": int(seat)}


def single_player_target(game, item) -> int | None:
    """The one **player** a spell on the stack chose as its only target, or
    None (CR 115.9a / CR 115.9c).

    Reflecting Mirror's half of :func:`single_spell_target`: "if that target is
    you" is a question only a face can answer, so an object target is not "no"
    with a seat beside it — it is simply not this question's answer.
    """
    chosen = single_spell_target(game, item)
    if chosen is None or chosen.get("kind") != "player":
        return None
    return int(chosen["seat"])


#: The quantifiers a lowered ``targets`` description uses for a printed
#: "target"/"any target". Read as evidence rather than as a spec: what is
#: wanted is only "did the printed line say *target*?", because the spec itself
#: comes from a kind table that fills in a default where the line said nothing.
#:
#: ``up_to`` is "**up to** N target …" — the same printed word with a ceiling
#: in front of it (``resolution._target_is_up_to`` reads the same quantifier
#: for CR 601.2c's "zero is a legal announcement"). It was missing, so "you
#: may tap up to two target creatures" (Cho-Arrim Bruiser) answered False:
#: its attack trigger kept the reference to itself that the declare-attackers
#: fire site stamps, CR 603.3d's choice was skipped, and the Bruiser tapped
#: the Bruiser. Measured over the pool before it was added: 45 instructions
#: on 28 cards answer differently, and that card is the only one any reader
#: of this predicate then treats differently — it is the one ``may`` whose
#: action describes such a target, and the one combat trigger that prints one.
_ANNOUNCED_QUANTIFIERS = frozenset({"target", "any_target", "up_to"})

#: ...and the words a lowering writes when it keeps the announcement as a plain
#: payload value instead: ``recipient``/``who``/``actor`` naming the seat this
#: instruction targets, ``controller`` inside a sweep's noun phrase ("each
#: artifact **target opponent** controls", Corrosion), ``controlled_by`` and
#: ``count_from.owner`` naming whose board a choice is made off ("choose a land
#: **that player** controls", Equipoise, where "that player" is the target
#: named one clause earlier).
#:
#: A set of *values* rather than a list of keys, because the keys are one per
#: effect family and the words are three for the whole pool — and because a
#: key list is the thing that goes stale when the next family picks a fourth
#: name for the same slot.
ANNOUNCED_PLAYER_WORDS = frozenset({"target", "target_player", "target_opponent"})


# "Is the player this cast names one its effect helps?" was answered here, for
# the web route's default seat, off a list of three instruction kinds — and
# again in ``engine/ai_valuation.py``, for the AI's tie-break, off a different
# list and a family rule. It is ``ai_valuation.cast_helps_the_player_it_names``
# now, one derivation with both readers: which kinds are a gift is a valuation
# (the families are that module's), and this module does not import it.


def announces_a_target(payload, *, described_only: bool = False) -> bool:
    """Whether the printed line this payload was lowered from named a target.

    Two callers, which is why it lives here rather than beside either: the
    trigger picker asks it before announcing a target (CR 603.3d), and
    ``handlers/control_flow``'s ``may`` asks it before rebinding
    ``context.target`` onto the seat an offer was made to — an offer whose
    action carries an announced target must not overwrite it, because the seat
    that was offered and the target that was chosen are two different answers.

    ``derive_instruction_spec`` answers a different question — "what would a
    picker offer for an instruction of this kind" — and for a **spell** that is
    the right one everywhere: a kind that targets a player targets a player,
    and the kind table may say so on its own. A *trigger* needs the narrower
    question, because the same instruction kinds are also reached with the seat
    already decided by the firing event, and announcing those would put a
    picker in front of a phrase that names nobody:

    * "…deals damage to a player, **that player** discards a card" (Abyssal
      Specter) — the seat is the one that was damaged;
    * "At the beginning of each player's draw step, **that player** draws…"
      (Anvil of Bogardan) — the seat is whose step it is;
    * "…**defending player** discards three cards" (Mindstab Thrull).

    Worse than a redundant prompt, the kind table's default is *wider* than the
    card: ``target_loses_life`` answers ``{"kind": "player"}`` with no
    narrowing, so Vito's "target **opponent**" would have been offered its own
    controller's face.

    So the evidence is the lowering's own record of the phrase — the ``targets``
    description, or one of the bare words a family that keeps no such
    description writes instead (:data:`ANNOUNCED_PLAYER_WORDS`). Walked rather
    than read off one key for :func:`_target_filter_controller`'s reason: the
    description sits at the payload's top level for one kind and under a
    wrapper for the next.

    Evidence, never the answer on its own: this is asked only of an instruction
    whose *spec* already says a player is chosen, so a per-player loop that
    spells its iterated seat "target_player" (Lim-Dûl's Hex) never reaches
    here — ``derive_instruction_spec`` answers None for a ``for_each``.

    *described_only* drops the bare-word half, and the ``may`` handler is the
    caller that needs it. A bare ``recipient: "target_player"`` is a family's
    spelling for "whoever this resolution's target is" — which for an offer is
    the **seat it was made to**, set by the rebind itself: "any player may
    sacrifice two lands or have this enchantment deal 5 damage to **that
    player**" (Worms of the Earth) says the seat that answered, not a target
    anybody announced. A ``targets`` description is the other thing entirely:
    it is what the picker reads and what CR 603.3d's announcement was made
    from, so it is the only evidence that a choice already exists to preserve.
    """
    if isinstance(payload, dict):
        targets = payload.get("targets")
        if (
            isinstance(targets, dict)
            and targets.get("quantifier") in _ANNOUNCED_QUANTIFIERS
        ):
            return True
        for value in payload.values():
            if (
                not described_only
                and isinstance(value, str)
                and value in ANNOUNCED_PLAYER_WORDS
            ):
                return True
            if announces_a_target(value, described_only=described_only):
                return True
        return False
    if isinstance(payload, (list, tuple)):
        return any(
            announces_a_target(entry, described_only=described_only)
            for entry in payload
        )
    inner = getattr(payload, "payload", None)
    return (
        False if inner is None
        else announces_a_target(inner, described_only=described_only)
    )
