"""Layer 4: the type-changing effects on a permanent, as CR 613 effects.

``collect_type_effects`` is the layer's collector for one object, in two halves
(its docstring says why): what is recorded on the permanent itself or
contributed by something attached to it (``collect_own_type_effects``), and
what a board-wide static says of it (``collect_static_type_effects``), which
``engine/type_statics.py`` decides once for the whole board with dependency
(CR 613.8) and this re-applies at the key that pass gave it. The builders
(``land_type_effect`` for CR 305.7, the animations, a lost supertype, a global
static's type sentence) are shared with that pass, so what it applied and what
a later read re-applies cannot differ. ``TYPE_EFFECT_CHANNELS`` is every key
the two collectors read, which ``layer_bridge``'s accessors check before
paying for the layer.

The write API is ``engine/type_changes.py`` (``gain_types`` / ``lose_types``,
stamped); this is the one reader of what it records. Split out of
``engine/layer_bridge.py`` at the size band (round kg3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .aura_grants import (animating_auras, aura_card_type_grants,
                          aura_creature_type_sets, aura_land_animation,
                          aura_type_grants)
from .aura_attachment import auras_attached_to
from .global_statics import (STACK_STATIC_STAMPS_KEY, STACK_STATICS_KEY,
                             changes_types, global_static_sources,
                             stack_statics_applying_to)
from .continuous import ContinuousEffect, add_types, remove_types, scope_only
from .land_types import DERIVED_LAND_TYPES, LAND_TYPE_EFFECTS, land_type_changes
from .late_modules import LateModules
from .printed_characteristics import COPIABLE_VALUE, printed_shape
from .land_animation import LAND_ANIMATIONS_REACHING
from .exiled_card_bodies import EXILED_CARD_BODY
from .type_changes import (
    LAND_ANIMATION_ORDER,
    LAYER_4_CHANNELS,
    derived_lost_supertypes,
    gained_types,
    land_animation_types_key,
    lost_types,
    static_type_order,
)

if TYPE_CHECKING:
    from .models import Permanent

#: The grammar's vocabulary, which a top-level import here cannot reach: it
#: closes a cycle through the grammar package. Read through a binding made on
#: first use rather than a function-level import, because the collectors
#: below run on every characteristic read (``engine/late_modules.py``).
_late_grammar = LateModules(f"{__package__}.grammar")


#: The three animation records layer 4 reads, one per duration
#: (:func:`collect_own_type_effects`).
_ANIMATION_RECORDS = (
    "animate_until_end_of_turn", "animate_indefinitely",
    "animate_until_end_of_combat",
)

# ``GAINED_TYPES`` / ``LOST_TYPES`` — the types a resolved effect added to or
# took from a permanent — are ``engine/type_changes.py``'s, the write API that
# stamps them (CR 613.7b). ``layer_bridge`` re-exported the two names for three
# tests that built a board by indexing with them; those go through
# ``gain_types`` / ``lose_types`` now, and nothing here names either key.
#: The card types an effect **set** a permanent to (CR 205.1a): "{0}: This
#: permanent becomes an enchantment." (Opal Acrolith), "Target creature becomes
#: an enchantment…" (Soul Sculptor). One slot rather than a list, exactly as an
#: animation record is one slot: a replacement says what the permanent now is,
#: so a second one is not a second contribution to fold but the same question
#: answered again — and the timestamp on the record is what decides it against
#: the animation channel, which is the effect it is printed to undo.
SET_CARD_TYPES = "set_card_types"
# ``DERIVED_LOST_SUPERTYPES`` — the supertypes a board-wide static takes away
# (Melting) — is ``engine/type_changes.py``'s too, rebuilt by
# ``engine/type_statics.py`` and read through ``derived_lost_supertypes``.


#: Every metadata key the two layer-4 collectors read off a permanent. With
#: all of them empty the collectors return nothing, so layer 4 leaves the
#: permanent with the types its copiable values give it: :func:`computed_types`
#: and :func:`computed_supertypes` answer that case from the printed shape of
#: ``effective_card`` without seeding a state and applying no effects to it.
#: Layer 4 was read 780,000 times in two simulated Mirage games, nearly always
#: of a permanent nothing had made anything else.
#:
#: **A channel either collector starts reading belongs here**, or the
#: permanent it is the only channel on keeps its printed types.
#: ``tests/engine/test_effective_card_fast_path.py`` runs both collectors
#: over a permanent whose metadata records every key read, and
#: ``engine/fast_paths.py``'s checking mode compares every shortcut answer
#: with the full computation.
TYPE_EFFECT_CHANNELS: tuple[str, ...] = (
    # ``type_changes``' own three: what an effect added and took away, and
    # what a static is taking (its keys are that module's to spell).
    *LAYER_4_CHANNELS,
    # The rest of what is recorded on the permanent
    # (:func:`collect_own_type_effects`).
    *_ANIMATION_RECORDS, SET_CARD_TYPES, "chosen_body", "attached_auras",
    EXILED_CARD_BODY,
    LAND_TYPE_EFFECTS,
    # …and what the board says of it (:func:`collect_static_type_effects`).
    "land_animated", "global_static_sources", STACK_STATICS_KEY,
    STACK_STATIC_STAMPS_KEY, DERIVED_LAND_TYPES,
)


def collect_type_effects(perm: Permanent, oid: int) -> list[ContinuousEffect]:
    """Layer 4: type- and subtype-changing effects.

    Animation (Kormus Bell's Swamps, Living Lands' Forests, Jade Statue) *adds*
    the creature type; a basic-land-type change (Evil Presence, Phantasmal
    Terrain, Blood Moon) *replaces* the land's subtypes, which is why the two
    cannot share one flag.

    Two halves, because two different things decide them. What a resolved
    spell or ability did to this permanent, and what is attached to it, is
    **its own** (:func:`collect_own_type_effects`): the set of objects such an
    effect applies to was fixed when it was created (CR 611.2c) and its
    timestamp is the whole of its place in the order. What a board-wide
    **static** says of it (:func:`collect_static_type_effects`) is neither —
    which permanents a static reaches is a question about the layer's own
    intermediate state, and where it applies can be moved by dependency
    (CR 613.8) — so that half is decided once for the whole board, by
    ``engine/type_statics.py``, and re-applied here at the key that pass gave
    it.
    """
    return collect_own_type_effects(perm, oid) + collect_static_type_effects(perm, oid)


def collect_own_type_effects(perm: Permanent, oid: int) -> list[ContinuousEffect]:
    """The layer-4 effects that belong to *perm* itself: recorded on it by a
    resolution, or contributed by something attached to it.

    Every one applies to exactly this object and does the same thing whatever
    state it finds, so none can *depend* on another effect (CR 613.8a) — which
    is what lets ``engine/type_statics.py`` treat these as the fixed points the
    board-wide statics are ordered around.
    """
    only = scope_only(oid)
    effects: list[ContinuousEffect] = []
    meta = perm.metadata

    # "…becomes a 3/3 Sphinx creature with flying **in addition to its other
    # types** until end of turn." (Riddleform.) One record, three layers: the
    # creature type and its subtypes are layer 4, the keyword is layer 6, and
    # the P/T was set through `engine/pt.py` when the ability resolved. Added
    # rather than replacing, which is what the printed phrase says.
    # "That creature becomes an **artifact** in addition to its other types."
    # (Ashnod's Transmogrant) / "…becomes an artifact **creature** …" (Xenic
    # Poltergeist.) One record for a type an effect *added* to a permanent,
    # with the duration it lasts for; layer 4 reads it here and layer 7b reads
    # the P/T half below, so a card adding a type without changing P/T costs
    # nothing extra.
    #
    # Stamped by ``type_changes.gain_types`` as the effect was created
    # (CR 613.7b). Both this list and the one below carried the constant 0, so
    # every addition applied before every removal whichever came first: a
    # Snow-Covered Forest thawed by Arcum's Weathervane and then frozen again
    # was not snow.
    for gained in gained_types(perm):
        # "Target creature **becomes that type** until end of turn."
        # (Unnatural Selection.) CR 205.1a's subtype *set*: "the new
        # subtype(s) replaces any existing subtypes from the appropriate set" —
        # the creature types, and no other subtype the permanent has, which is
        # the scoped replacement Conspiracy's static makes below. The record
        # says so rather than this collector inferring it: an *addition* of a
        # creature type ("is a Knight in addition to its other types") is the
        # same list with nothing replaced.
        replaced: frozenset[str] = frozenset()
        if gained.get("replaces_creature_types"):
            replaced = _late_grammar.vocabulary.CREATURE_TYPES
        effects.append(add_types(
            only,
            card_types=list(gained.get("card_types") or ()),
            subtypes=list(gained.get("subtypes") or ()),
            supertypes=list(gained.get("supertypes") or ()),
            replaces_subtypes_from=replaced,
            timestamp=int(gained.get("timestamp") or 0),
            label=f"gained:{gained.get('source', 'effect')}",
        ))

    # Layer 4's removing half, each at its own timestamp, so a later add wins
    # and a later removal wins (CR 613.7). "…as a non-Aura enchantment"
    # (Takklemaggot): the returning permanent is still an enchantment and is no
    # longer an Aura, which is one subtype off the printed line and nothing
    # else. Read here rather than at the CR 704.5m sweep, so every reader of
    # "is this an Aura?" gets the same answer.
    for lost in lost_types(perm):
        effects.append(remove_types(
            only,
            card_types=list(lost.get("card_types") or ()),
            subtypes=list(lost.get("subtypes") or ()),
            supertypes=list(lost.get("supertypes") or ()),
            timestamp=int(lost.get("timestamp") or 0),
            label=f"lost:{lost.get('source', 'effect')}",
        ))

    # Both animation records again, for the reason the keyword collector above
    # reads both: the layer-4 contribution an animation makes does not depend on
    # when it ends. The cleanup sweep clears the first key and never hears of
    # the second (``handlers/animation.ANIMATE_INDEFINITELY``), which is the
    # whole of the difference between them.
    # …and the third (Jade Statue), for the reason the second is read here:
    # what an animation contributes to its layer does not depend on when it
    # ends. This key held a bare ``True`` until Jade Statue stopped being a
    # card hook, so the Statue was a creature and not a **Golem**: a lord did
    # not pump it and "destroy target Golem" missed it.
    for _key in _ANIMATION_RECORDS:
        animation = meta.get(_key)
        if animation:
            # CR 205.1a where the sentence printed none of CR 205.1b's
            # retention clauses ("it becomes a 2/2 Gargoyle creature with
            # flying", Opal Gargoyle): the animation *replaces* the printed
            # card types instead of joining them, which is what makes the
            # cycle's own "if this permanent is an enchantment" false
            # afterwards. Subtypes are replaced only when the sentence named
            # some — CR 205.1a's third clause, that a removed card type takes
            # its own subtypes with it, is not modelled, and no card in the
            # pool animates a permanent carrying a subtype of the type it
            # loses.
            replaces = bool(animation.get("replaces_types"))
            subtypes = animation.get("subtypes") or ()
            effects.append(add_types(
                only,
                # "…a 2/2 Assembly-Worker **artifact** creature" (Mishra's
                # Factory): every type the sentence named, not just the head
                # noun. A land animated without the artifact type is a permanent
                # Shatter cannot reach and Titania's Song does not see.
                card_types=["creature", *(animation.get("card_types") or ())],
                subtypes=subtypes,
                replace_card_types=replaces,
                replace_subtypes=replaces and bool(subtypes),
                # CR 613.7b: the stamp the effect was created with
                # (``handlers/animation._animation_record``, the one writer).
                # It mattered first for a replacement — Opal Acrolith turns
                # itself back into an enchantment and then animates again —
                # and an addition carries one for the same reason one layer
                # of argument down: it commutes with other additions and not
                # with an effect that *sets* the card types. Zero only for a
                # record a test built by hand.
                timestamp=int(animation.get("timestamp") or 0),
                label=f"animated ({_key})",
            ))
    # "{0}: This permanent becomes an enchantment." (Opal Acrolith, Hidden
    # Stag's second line, Soul Sculptor's target.) CR 205.1a again, with no
    # creature body behind it: the record says what the permanent now is, and
    # the timestamp is what puts it after or before the animation it undoes.
    replacement = meta.get(SET_CARD_TYPES)
    if replacement:
        effects.append(add_types(
            only,
            card_types=list(replacement.get("card_types") or ()),
            subtypes=(),
            replace_card_types=True,
            replace_subtypes=True,
            timestamp=int(replacement.get("timestamp") or 0),
            label=f"set types ({replacement.get('source', 'effect')})",
        ))
    # "…it becomes your choice of … a 1/6 **Wall** artifact creature with
    # defender" (Primal Clay). The body's P/T is layer 7b and its keyword is
    # layer 6; its creature type is here, added rather than replacing, and
    # derived from the recorded choice so swapping bodies needs nothing undone.
    #
    # **Before every other layer-4 effect, and that is the rule rather than a
    # missing stamp.** CR 613.2a puts it in layer 1: "'As … enters' … abilities
    # generate copiable effects if they set power and toughness, even if they
    # also define other characteristics" — and CR 613.2c makes what layer 1
    # leaves the object's copiable values (CR 707.2), which is where every
    # later layer starts, ahead of any timestamp. So a Conspiracy that was
    # already out and one that arrives later both find a Wall and leave an
    # Elf; stamped with the permanent's own timestamp, the older Conspiracy
    # would have applied first and the Clay been an Elf Wall.
    # ``COPIABLE_VALUE`` says which kind of zero this one is.
    # "…has the power, toughness, and creature types of the last creature card
    # exiled with it. It's still a Shapeshifter." (Duplicant.) The creature
    # types of the body the refresh derived (``engine/exiled_card_bodies.py``),
    # *added* at the permanent's own timestamp (CR 613.7a): "still a
    # Shapeshifter" keeps the printed type.
    exiled_body = meta.get(EXILED_CARD_BODY) or {}
    if exiled_body.get("subtypes"):
        effects.append(add_types(
            only, subtypes=list(exiled_body["subtypes"]),
            timestamp=perm.timestamp,
            label=f"exiled card's body ({exiled_body.get('card_name', 'card')})",
        ))

    chosen_body = meta.get("chosen_body") or {}
    body_subtypes = list(chosen_body.get("subtypes") or ())
    if body_subtypes:
        effects.append(add_types(
            only, subtypes=body_subtypes, timestamp=COPIABLE_VALUE,
            label="chosen body",
        ))

    # "…and is a Knight in addition to its other types" (Dub, Demonic Embrace).
    # *Added*, not replacing — which is the whole difference from the land-type
    # change below, and why the two cannot share a call. Derived from the Aura's
    # own text on every recompute and stamped with the moment it attached
    # (CR 613.7b), so detaching one simply stops contributing the type.
    #
    # "…and is an **artifact** in addition to its other types."
    # (Transmogrifying Licid.) The same rider one level up CR 205's hierarchy,
    # so it is the same contribution with the words in the other field: a card
    # type (CR 205.2) rather than a creature subtype (CR 205.3). Read from a
    # separate function for that reason — handing "artifact" to ``subtypes``
    # would make the permanent an artifact-*subtype* nothing on any board is,
    # and handing "Knight" to ``card_types`` would make it a card type.
    for aura in auras_attached_to(perm):
        added = aura_type_grants(aura.effective_card.oracle_text)
        added_card_types = aura_card_type_grants(aura.effective_card.oracle_text)
        if not added and not added_card_types:
            continue
        effects.append(
            add_types(
                only,
                subtypes=list(added),
                card_types=list(added_card_types),
                timestamp=int(aura.metadata.get("aura_timestamp", 0)),
                label=f"aura:{aura.card.name}",
            )
        )
    # "Enchanted creature **is a Flagbearer**." (Coalition Flag.) The same
    # sentence without CR 205.1b's rider, so CR 205.1a applies: the new creature
    # type *replaces* the creature types it had and nothing else — scoped to
    # CR 205.3m's list, so an animated Forest under the Flag is still a Forest.
    # Timestamped like the addition above; two such Auras on one creature do
    # not commute, and the later one is what the creature is (CR 613.7).
    for aura in auras_attached_to(perm):
        set_types = aura_creature_type_sets(aura.effective_card.oracle_text)
        if not set_types:
            continue
        # Read late for `global_static_type_effect`'s reason below: a
        # top-level import of the vocabulary closes a cycle through the grammar.
        effects.append(
            add_types(
                only,
                subtypes=list(set_types),
                replaces_subtypes_from=_late_grammar.vocabulary.CREATURE_TYPES,
                timestamp=int(aura.metadata.get("aura_timestamp", 0)),
                label=f"aura sets type:{aura.card.name}",
            )
        )
    # "Enchanted land is a 5/6 green **Treefolk creature** that's still a land."
    # (Living Terrain.) CR 205.1b: "still a land" is the addition — the creature
    # type and the printed creature types join the land's own, nothing is
    # replaced, and the Aura leaving simply stops contributing them.
    for aura in auras_attached_to(perm):
        body = aura_land_animation(aura.effective_card.oracle_text)
        if body is None:
            continue
        effects.append(
            add_types(
                only,
                card_types=["creature"],
                subtypes=list(body["subtypes"]),
                timestamp=int(aura.metadata.get("aura_timestamp", 0)),
                label=f"animated:{aura.card.name}",
            )
        )

    # CR 305.7: setting a land's subtype *replaces* its old ones, so two of
    # these on one land do not commute — the newer contribution is what the land
    # is. They are collected rather than merged, and each carries the timestamp
    # of the effect that recorded it, so 613.7 decides that and not the order the
    # writes happened to run in (engine/land_types.py). The **recorded** ones
    # here — an Aura's, a mire counter's, a turn-long change; a static's are the
    # other half.
    for change in land_type_changes(perm, derived=False):
        effects.append(land_type_effect(
            perm, oid, str(change["land_type"]),
            additive=bool(change.get("additive")),
            timestamp=int(change.get("timestamp", 0)),
        ))

    return effects


def collect_static_type_effects(perm: Permanent, oid: int) -> list[ContinuousEffect]:
    """What the board's statics say *perm* is in layer 4, each at the
    applied-order key ``engine/type_statics.py`` gave it.

    That pass applied every layer-4 effect on the battlefield once, in CR 613.7
    timestamp order as CR 613.8 dependency rearranges it, and wrote down which
    statics reached this permanent and **where in the order** each one did —
    ``(timestamp, order)``, the timestamp it applied at and its position among
    the statics applied there. Sorting by that key (``ContinuousEffect``'s
    ``timestamp`` and ``sequence``) against this permanent's own effects
    replays the pass's answer for this one object, which is all a per-object
    collector can do: it cannot see the board, so it cannot decide a
    dependency, only re-apply one.

    A contribution with no key (a board built by hand, a flag poked in a test)
    falls back to its source's own timestamp, or to 0 where it has none.
    """
    only = scope_only(oid)
    effects: list[ContinuousEffect] = []
    meta = perm.metadata

    # "All Swamps are 1/1 black **creatures** that are still lands." (Kormus
    # Bell, Living Lands, Natural Emergence.) Its place in the order used to
    # be the constant 0, which no effect that depends on it could wait behind.
    if meta.get("land_animated"):
        stamp, order = static_type_order(perm, LAND_ANIMATION_ORDER) or (0, 0)
        effects.append(land_animation_type_effect(oid, timestamp=stamp, sequence=order))
        # "…are 1/1 green **Elf** creatures that are still lands" (Ambush
        # Commander): each animator's creature types, re-applied at the place
        # that animator took (``land_animation_types_key``) — the record the
        # refresh left of which animators reached this land is what names
        # them (CR 613.6).
        for animator, animation in meta.get(LAND_ANIMATIONS_REACHING) or ():
            if not getattr(animation, "creature_types", ()):
                continue
            stamp, order = static_type_order(
                perm, land_animation_types_key(animator)
            ) or (int(getattr(animator, "timestamp", 0) or 0), 0)
            effects.append(land_animation_type_effect(
                oid, timestamp=stamp, sequence=order,
                subtypes=animation.creature_types,
            ))

    # "All lands are no longer snow." (Melting.) Rebuilt from the board on
    # every refresh and stamped with its source's timestamp (CR 613.7a), so a
    # land an effect made snow *after* Melting arrived is snow: the later
    # effect applies last. The channel held bare words and applied at the
    # constant 0 in a list behind every addition, so the static always won.
    for removal in derived_lost_supertypes(perm):
        effects.append(lost_supertype_effect(
            oid, str(removal["supertype"]),
            timestamp=int(removal.get("timestamp") or 0),
            sequence=int(removal.get("order") or 0),
        ))

    # Animate Artifact (CR 613.1d): "As long as enchanted artifact isn't a
    # creature, it's an artifact creature…". Derived from the attached Aura, so
    # the artifact stops being a creature the moment the Aura leaves — and on
    # this half of the collector although it is one permanent's, because the
    # Aura's own condition is a *scope*: whether it applies is decided by the
    # board pass against the layer's intermediate state (``auras
    # .animating_auras``), and where, against Titania's Song, by the loop rule.
    for aura in animating_auras(perm):
        stamp, order = static_type_order(perm, aura.permanent_id) or (0, 0)
        effects.append(attached_animation_type_effect(
            oid, timestamp=stamp, sequence=order,
        ))

    # The board-wide statics recorded as **sources** on this permanent
    # (``engine/global_statics.py``), each one's layer-4 part:
    #
    # * "Each noncreature artifact … becomes an artifact creature" (Titania's
    #   Song) and "Each other non-Aura enchantment is a creature in addition
    #   to its other types" (Opalescence) — the creature type, added.
    # * "Creatures you control are the chosen type." (Conspiracy.) The one
    #   global static whose effect is not in its own text: the creature type
    #   was chosen as the **source** entered (CR 614.1c) and is recorded on
    #   that permanent. CR 205.1a's scoped replacement, not the blanket one:
    #   the chosen type replaces the creature's *creature* types and leaves any
    #   others alone, so a Forest this seat has animated is a Goblin **and
    #   still a Forest**.
    # * "All Goblins … **are Zombies in addition to their other creature
    #   types**." (Dralnu's Crusade.) CR 205.1b's addition: no replacement
    #   flag, so the Goblin keeps "goblin" and every other subtype it had.
    #
    # Derived on every recompute like the rest of the family — a source leaving
    # ends the effect by dropping out of the list, with nothing to sweep — and
    # **placed by the board pass**: the Crusade's scope is a creature type, so
    # it depends on Conspiracy (CR 613.8a) and applies just after it whichever
    # is older; Conspiracy's scope is "creature", so it waits behind whatever
    # makes a permanent one. This loop used to say the first of those by hand
    # (a `max` over the type-setting statics' timestamps) and could not say
    # the second at all.
    for source, static in global_static_sources(
        meta.get("global_static_sources") or ()
    ):
        if not changes_types(static):
            continue
        stamp, order = static_type_order(perm, source.permanent_id) or (
            source.timestamp, 0,
        )
        effect = global_static_type_effect(
            oid, source, static, timestamp=stamp, sequence=order,
        )
        if effect is not None:
            effects.append(effect)
    # …and the same from a spell on the stack (CR 113.6b). No stack static in
    # the pool has a layer-4 part; read so that one printed tomorrow is not a
    # type change the collector silently never applies.
    for static, stamp in stack_statics_applying_to(perm):
        if changes_types(static):
            effect = global_static_type_effect(oid, None, static, timestamp=stamp)
            if effect is not None:
                effects.append(effect)

    # "All Mountains are Plains." (Conversion.) "Nonbasic lands are Mountains."
    # (Blood Moon.) The **derived** land-type contributions, in the order the
    # board pass applied them — which is the statics' timestamp order unless
    # one depends on another: Conversion waits behind Blood Moon whichever
    # arrived first, because applying the Moon changes which lands are
    # Mountains (CR 613.8a).
    for change in land_type_changes(perm, derived=True):
        effects.append(land_type_effect(
            perm, oid, str(change["land_type"]),
            additive=bool(change.get("additive")),
            timestamp=int(change.get("timestamp", 0)),
            sequence=int(change.get("order") or 0),
        ))

    return effects


def land_type_effect(
    perm: Permanent, oid: int, land_type: str, *, additive: bool = False,
    timestamp: int, sequence: int = 0,
) -> ContinuousEffect:
    """Layer 4: *perm*'s land types become *land_type* (CR 305.7), or gain it.

    One builder for the recorded changes, the derived ones and the board pass
    that decides the derived ones, so what the pass applied and what a later
    read re-applies cannot differ.

    "…**in addition to its other land types**" (Blanket of Night) is the one
    printed rider that switches CR 305.7 off, and it is the *record* that says
    so: the collector has the contribution and not the sentence. Dropping it
    would make a Swamp-granting static take away every Island's blue mana,
    which is the same effect written as a strictly harsher card.
    """
    return add_types(
        scope_only(oid),
        subtypes=[land_type],
        # CR 305.7: "the new land type(s) replaces any existing **land**
        # types" — CR 205.1a's "subtypes from the appropriate set". It
        # was the blanket flag, which replaced every subtype the
        # permanent had: a Forest wearing Living Terrain stopped being
        # a Treefolk when Evil Presence arrived after it, and an
        # animated Mishra's Factory stopped being an Assembly-Worker
        # under a later Blood Moon — but only when the land-type change
        # was the *later* effect, so the same two cards gave two
        # answers by the order they were played in.
        replaces_subtypes_from=() if additive else _land_subtypes_of(perm),
        timestamp=timestamp,
        sequence=sequence,
        label=("is also a " if additive else "is a ") + land_type,
    )


def lost_supertype_effect(
    oid: int, supertype: str, *, timestamp: int, sequence: int = 0
) -> ContinuousEffect:
    """Layer 4: a board-wide static takes *supertype* away (CR 205.4a)."""
    return remove_types(
        scope_only(oid), supertypes=[supertype], timestamp=timestamp,
        sequence=sequence, label=f"static:no longer {supertype}",
    )


def land_animation_type_effect(
    oid: int, *, timestamp: int, sequence: int = 0,
    subtypes: tuple[str, ...] = (),
) -> ContinuousEffect:
    """Layer 4: a land animator makes this land a creature "that's still a
    land" (CR 205.1b) — the creature type, added, with the creature types
    the animator prints (*subtypes*, Ambush Commander's "Elf"). Added rather
    than set: "still lands" is CR 205.1b's retention, which keeps every type
    the land had."""
    return add_types(
        scope_only(oid), card_types=["creature"], subtypes=list(subtypes),
        timestamp=timestamp, sequence=sequence, label="animated",
    )


def attached_animation_type_effect(
    oid: int, *, timestamp: int, sequence: int = 0
) -> ContinuousEffect:
    """Layer 4: an attached Aura makes this artifact "an artifact creature"
    (Animate Artifact) — the creature type, added (CR 205.1b)."""
    return add_types(
        scope_only(oid), card_types=["creature"], timestamp=timestamp,
        sequence=sequence, label="animated artifact",
    )


def global_static_type_effect(
    oid: int, source, static, *, timestamp: int, sequence: int = 0
) -> ContinuousEffect | None:
    """The layer-4 part of *static* as it applies to one object, or None.

    One effect for everything the static's sentence says about types, because
    it is one continuous effect with one place in the order. None when it sets
    a type its source has not chosen yet: no contribution rather than an empty
    replacement — wiping every creature's types on the strength of an
    unanswered choice is the card doing something much larger than it says.
    """
    card_types = ["creature"] if static.adds_creature_type else []
    # "All permanents are **artifacts** in addition to their other types."
    # (Mycosynth Lattice.) CR 205.1b's addition, the printed card type.
    card_types.extend(static.adds_card_types)
    subtypes = list(static.adds_subtypes)
    replaced: frozenset[str] = frozenset()
    if static.sets_creature_type:
        # Read late rather than at module scope: this module is pulled in
        # by ``handlers/_filters`` long before ``engine.grammar`` finishes
        # importing, and a top-level import of the vocabulary closes a cycle
        # through the grammar package.
        CREATURE_TYPES = _late_grammar.vocabulary.CREATURE_TYPES

        chosen = (
            source.metadata.get("chosen_creature_type") if source is not None else None
        )
        if not chosen:
            return None
        subtypes.append(str(chosen).lower())
        replaced = CREATURE_TYPES
    if not card_types and not subtypes:
        return None
    described = "+".join([*card_types, *subtypes])
    return add_types(
        scope_only(oid),
        card_types=card_types,
        subtypes=subtypes,
        replaces_subtypes_from=replaced,
        timestamp=timestamp,
        sequence=sequence,
        label=f"{static.name}:{described}",
    )


def _land_subtypes_of(perm: Permanent) -> frozenset[str]:
    """The subtypes a land-type change replaces on *perm* (CR 305.7): every
    land type there is, and — on a card printed as a land and nothing else —
    every subtype it prints.

    The second half is what keeps this from depending on a catalog's spelling.
    A subtype correlates to a card type (CR 205.3d), so every word after the
    dash on a card whose only type is Land *is* a land type whether or not the
    vocabulary lists it that way ("Urza's"), and a Blood Moon must not leave
    one behind. On a card printed with a second type — a land creature — the
    printed words are of two sets and only the catalog can tell them apart.
    """
    LAND_TYPES = _late_grammar.vocabulary.LAND_TYPES

    printed_types, printed_subtypes = printed_shape(perm.effective_card)
    if printed_types == {"land"}:
        return frozenset(LAND_TYPES | printed_subtypes)
    return frozenset(LAND_TYPES)


__all__ = [
    "attached_animation_type_effect", "collect_own_type_effects",
    "collect_static_type_effects", "global_static_type_effect",
    "land_animation_type_effect", "land_type_effect", "lost_supertype_effect",
]
