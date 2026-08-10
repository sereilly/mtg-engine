"""Collect the engine's stored P/T channels as CR 613 continuous effects.

``engine/continuous.py`` is the layer system; this module is the adapter that
feeds it. Each of the metadata channels a permanent carries becomes a
:class:`ContinuousEffect` placed in its proper layer and sublayer, and the
layer engine — not the order the reading code happens to be written in —
decides how they combine.

Keeping the adapter separate from the layer engine means the engine stays pure
and testable against the rule text, while the storage it reads from can move
(counters out of metadata, effects created with real timestamps) without the
rules logic changing.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from .auras import (
    animating_auras,
    aura_keyword_grants,
    aura_static_pt_grant,
    auras_attached_to,
)
from .control import control_changes, has_control_change
from .global_statics import global_statics_applying_to
from .continuous import (
    Characteristics,
    ContinuousEffect,
    State,
    add_types,
    apply_layers,
    change_control,
    grant_abilities,
    modify_pt,
    remove_abilities,
    scope_only,
    set_colors,
    set_pt,
    switch_pt,
)
from .keywords import ability_effects, derived_grants
from .land_types import land_type_changes
from .lord_buffs import QUALIFIER_FIELDS

if TYPE_CHECKING:
    from .models import Permanent

# Channels whose values are recomputed from the board on every pass carry no
# timestamp of their own; they are all layer 7c, where order does not matter
# because addition commutes.
_DERIVED_TIMESTAMP = 0

# Derived layer-7c contributions from a lord buff whose filter names a state the
# buffed creature must be in. ``{qualifier: (power, toughness)}``, cleared and
# rebuilt by ``_recalculate_lord_buffs``; the qualifier itself is checked here,
# at read time.
QUALIFIED_BUFFS = "lord_buff_while"

_QUALIFIER_HOLDS = {
    "attacking": lambda perm: bool(perm.attacking),
    # CR 509.1a: a creature is blocking once it has been declared as a blocker.
    "blocking": lambda perm: perm.blocking_attacker_index is not None,
    "tapped": lambda perm: bool(perm.tapped),
    "untapped": lambda perm: not perm.tapped,
}

# The derivation table and the code that evaluates it must not be two lists: a
# qualifier the table can produce with nothing here to check it would be a buff
# applied unconditionally, which is the failure this whole family had. Raised
# rather than asserted, so `python -O` cannot switch the check off.
if set(_QUALIFIER_HOLDS) != set(QUALIFIER_FIELDS):  # pragma: no cover - import guard
    raise RuntimeError(
        "lord_buffs.QUALIFIER_FIELDS and layer_bridge._QUALIFIER_HOLDS disagree: "
        f"{sorted(set(QUALIFIER_FIELDS) ^ set(_QUALIFIER_HOLDS))}"
    )


def qualifier_holds(perm: Permanent, qualifier: str) -> bool:
    """Whether *perm* is currently in the state *qualifier* names."""
    return _QUALIFIER_HOLDS[qualifier](perm)


def _printed(perm: Permanent, key: str) -> int | None:
    # The permanent's own printed stats, not the copied card's. The engine
    # models a copy by stamping absolute_power/absolute_toughness, which apply
    # in 7b and override this seed — so reading the copied card here would
    # double-count the copy rather than layer over it.
    card = perm.card
    return card.base_power if key == "power" else card.base_toughness


@lru_cache(maxsize=None)
def _printed_shape(
    type_line: str, name: str, oracle_text: str, keywords: tuple[str, ...]
) -> tuple[frozenset[str], frozenset[str]]:
    """A card's printed types and subtypes, parsed once per distinct card.

    Seeding runs on every characteristic read — ``is_creature`` alone is called
    in tight state-based-action and combat loops — so the text parsing behind it
    is cached on the same immutable fields ``compile_card_oracle`` keys on.
    """
    lowered = type_line.lower()
    card_types = frozenset(
        word for word in ("artifact", "creature", "enchantment", "instant", "land", "sorcery")
        if word in lowered
    )
    subtypes: frozenset[str] = frozenset()
    if "—" in type_line or "-" in type_line:
        tail = type_line.replace("—", "-").split("-", 1)[-1]
        subtypes = frozenset(word.lower() for word in tail.split() if word)
    return card_types, subtypes


def seed_characteristics(perm: Permanent) -> Characteristics:
    """An object's copiable values — where layer application starts (613.1).

    ``None`` power/toughness means the printed value is variable ("*"), so a
    characteristic-defining ability in 7a supplies it. That is the distinction
    the old code could not make, having no value for "not a number".
    """
    card = perm.effective_card
    card_types, subtypes = _printed_shape(
        card.type_line, card.name, card.oracle_text, card.keywords
    )
    card_types, subtypes = set(card_types), set(subtypes)
    return Characteristics(
        card_types=card_types,
        subtypes=subtypes,
        # Colour comes from the permanent's own card: a copy that takes on its
        # source's colours records them in `copied_colors`, which applies as a
        # layer-5 effect. Vesuvan Doppelganger deliberately records none, so its
        # printed blue shows through.
        colors=set(perm.card.colors),
        abilities=_printed_abilities(card),
        power=_printed(perm, "power"),
        toughness=_printed(perm, "toughness"),
    )


# Keywords the engine recognizes on a card's own text. Kept here rather than as
# a fallback *after* layer 6, because a printed ability is part of the object's
# copiable values: it has to be in the seed so a removal in layer 6 can take it
# away. Consulted after the parsed `keywords` field so a card whose keyword only
# appears in its oracle text still has it.
_TEXT_KEYWORDS = (
    "flying", "first strike", "double strike", "trample", "vigilance", "haste",
    "defender", "reach", "banding", "fear", "deathtouch", "islandwalk",
    "mountainwalk", "swampwalk", "forestwalk", "plainswalk", "desertwalk",
)


def _printed_abilities(card) -> set[str]:
    return set(_printed_abilities_cached(
        card.name, card.type_line, card.oracle_text, card.keywords
    ))


@lru_cache(maxsize=None)
def _printed_abilities_cached(
    name: str, type_line: str, oracle_text: str, keywords: tuple[str, ...]
) -> frozenset[str]:
    """Printed keywords, including any the compiler only finds in oracle text.

    Cached per distinct card: this scans every compiled instruction for every
    known keyword, and it runs on each characteristic read.
    """
    from .models import CardDefinition
    from .oracle import compile_card_oracle

    card = CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=oracle_text,
        colors=(), color_identity=(), keywords=keywords, produced_mana=(), raw={},
    )
    abilities = {kw.lower() for kw in keywords}
    for instruction in compile_card_oracle(card).instructions:
        if instruction.kind not in ("keyword_line", "static_line"):
            continue
        value = instruction.value or ""
        # A lord line ("Other Merfolk … have islandwalk") grants the ability to
        # other creatures, not to the lord itself.
        if value.startswith("other "):
            continue
        abilities.update(word for word in _TEXT_KEYWORDS if word in value)
    return frozenset(abilities)


def collect_pt_effects(perm: Permanent, oid: int) -> list[ContinuousEffect]:
    """Every layer-7 effect currently stored on *perm*."""
    only = scope_only(oid)
    effects: list[ContinuousEffect] = []
    meta = perm.metadata

    # 7b — set to a value. The until-end-of-turn variant is stamped later than
    # the permanent one so the layer engine reproduces the precedence the old
    # hand-written property had, but now as a timestamp rather than an `elif`.
    for suffix, stamp in (("", 1), ("_until_eot", 2)):
        power = meta.get(f"absolute_power{suffix}")
        toughness = meta.get(f"absolute_toughness{suffix}")
        if power is None and toughness is None:
            continue
        effects.append(
            set_pt(
                only,
                int(power) if power is not None else None,
                int(toughness) if toughness is not None else None,
                timestamp=int(meta.get(f"absolute_pt_timestamp{suffix}", stamp)),
                label=f"set{suffix}",
            )
        )

    # 7c — modifications. Counters and one-shot boosts live on the permanent;
    # the buff channels are rebuilt from the board each recompute.
    modifications = [
        (perm.power_bonus, perm.toughness_bonus, "counters/boosts"),
        (
            int(meta.get("static_buff_power", 0)),
            int(meta.get("static_buff_toughness", 0)),
            "static buffs",
        ),
        (
            int(meta.get("derived_buff_power", 0)),
            int(meta.get("derived_buff_toughness", 0)),
            "conditional buffs",
        ),
    ]
    # A lord buff whose filter names a *state* ("attacking creatures you
    # control", "untapped creatures you control") is contributed by the
    # recompute but evaluated here, when power and toughness are read. That is
    # the difference CR 611.3a needs: a creature that taps between two
    # recomputes stops meeting "untapped" the instant it taps, not when the
    # board next happens to be recalculated. Castle's +0/+2 survived its own
    # creature attacking until this moved.
    for qualifier, (power, toughness) in sorted((meta.get(QUALIFIED_BUFFS) or {}).items()):
        if qualifier_holds(perm, qualifier):
            modifications.append((int(power), int(toughness), f"lord buff while {qualifier}"))
    for power, toughness, label in modifications:
        if power or toughness:
            effects.append(
                modify_pt(only, power, toughness, timestamp=_DERIVED_TIMESTAMP, label=label)
            )

    # 7b — Animate Artifact sets P/T to the artifact's mana value. A mana value
    # of 0 really does mean 0/0: a Mox animated this way dies to CR 704.5f, and
    # clamping it to 1/1 (as the card-rebuilding version did) kept it alive.
    for aura in animating_auras(perm):
        mana_value = int(perm.card.cmc)
        effects.append(
            set_pt(
                only,
                mana_value,
                mana_value,
                timestamp=int(aura.metadata.get("aura_timestamp", _DERIVED_TIMESTAMP)),
                label=f"animated:{aura.card.name}",
            )
        )

    for static in global_statics_applying_to(perm):
        if static.pt_from_mana_value:
            value = int(perm.card.cmc)
            effects.append(
                set_pt(only, value, value, timestamp=_DERIVED_TIMESTAMP, label=static.name)
            )

    # 7c — Auras. Derived from each attached Aura's own text on every
    # recompute and stamped with the moment it became attached (CR 613.7b), so
    # detaching one is simply ceasing to contribute: there is no remembered
    # delta to subtract, and two Auras sort by when each started applying
    # rather than sharing one derived timestamp.
    for aura in auras_attached_to(perm):
        grant = aura_static_pt_grant(aura.card.oracle_text)
        if grant is None:
            continue
        effects.append(
            modify_pt(
                only,
                grant[0],
                grant[1],
                timestamp=int(aura.metadata.get("aura_timestamp", _DERIVED_TIMESTAMP)),
                label=f"aura:{aura.card.name}",
            )
        )

    # 7d — switch.
    if meta.get("pt_switched"):
        effects.append(switch_pt(only, timestamp=_DERIVED_TIMESTAMP, label="switch"))

    return effects


# Landwalk stamped as a metadata flag rather than granted through the keyword
# API — an upkeep effect's forestwalk grant, a text-changing effect swapping one
# walk for another. Collected so layer 6 sees them too; they carry no timestamp
# of their own and sort before anything explicitly granted.
_LANDWALKS = ("islandwalk", "mountainwalk", "swampwalk", "forestwalk", "plainswalk")


def collect_ability_effects(perm: Permanent, oid: int) -> list[ContinuousEffect]:
    """Layer 6: every ability grant and removal currently on *perm*.

    Grants and removals share the layer, so a later removal beats an earlier
    grant and a later grant beats an earlier removal — which is the rule
    (613.9), and the reason they are recorded in order rather than as one flag
    per keyword per direction.
    """
    only = scope_only(oid)
    effects: list[ContinuousEffect] = []

    # Keywords a copy takes on (Clone, Vesuvan Doppelganger) are part of its
    # copiable values, so they sort before anything granted afterwards.
    copied = perm.metadata.get("copied_keywords") or ()
    if copied:
        effects.append(
            grant_abilities(only, [k.lower() for k in copied], timestamp=0, label="copied")
        )

    # Deathtouch is stamped as a flag by the combat code rather than granted
    # through the keyword API; collect it so layer 6 sees it too.
    if perm.metadata.get("has_deathtouch"):
        effects.append(grant_abilities(only, ["deathtouch"], timestamp=0, label="deathtouch"))

    for walk in _LANDWALKS:
        if perm.metadata.get(f"has_{walk}"):
            effects.append(grant_abilities(only, [walk], timestamp=0, label=f"granted {walk}"))
        if perm.metadata.get(f"lost_{walk}"):
            effects.append(remove_abilities(only, [walk], timestamp=0, label=f"lost {walk}"))

    # Abilities a board-wide source grants right now (a lord's "other Goblins …
    # have mountainwalk"). Derived every recompute, so the grant ends when the
    # lord leaves without anything having to find and undo it — and not
    # restricted to landwalk, which is all the flag channel above could carry.
    granted = derived_grants(perm)
    if granted:
        effects.append(
            grant_abilities(only, list(granted), timestamp=0, label="lord grant")
        )

    # Layer 6 from each attached Aura, stamped with the moment it attached
    # (CR 613.7b) — derived every recompute, so the grant ends when the Aura
    # leaves without anything having to find and undo it.
    for aura in auras_attached_to(perm):
        granted = aura_keyword_grants(aura.card.oracle_text)
        if not granted:
            continue
        effects.append(
            grant_abilities(
                only,
                list(granted),
                timestamp=int(aura.metadata.get("aura_timestamp", 0)),
                label=f"aura:{aura.card.name}",
            )
        )

    # Board-wide statics (Titania's Song). Derived from the source permanent
    # recorded on this one, so the removal ends when the source leaves.
    for static in global_statics_applying_to(perm):
        if static.removes_abilities:
            effects.append(
                remove_abilities(
                    only, sorted(_printed_abilities(perm.effective_card)),
                    timestamp=0, label=static.name,
                )
            )

    for entry in ability_effects(perm):
        keyword = entry["keyword"]
        stamp = int(entry["timestamp"])
        build = grant_abilities if entry["grant"] else remove_abilities
        effects.append(build(only, [keyword], timestamp=stamp, label=keyword))

    return effects


def collect_type_effects(perm: Permanent, oid: int) -> list[ContinuousEffect]:
    """Layer 4: type- and subtype-changing effects.

    Animation (Kormus Bell's Swamps, Living Lands' Forests, Jade Statue) *adds*
    the creature type; a basic-land-type change (Evil Presence, Phantasmal
    Terrain, Blood Moon) *replaces* the land's subtypes, which is why the two
    cannot share one flag.
    """
    only = scope_only(oid)
    effects: list[ContinuousEffect] = []
    meta = perm.metadata

    if meta.get("land_animated") or meta.get("animate_until_end_of_combat"):
        effects.append(
            add_types(only, card_types=["creature"], timestamp=0, label="animated")
        )

    # Animate Artifact (CR 613.1d). Derived from the attached Aura, so the
    # artifact stops being a creature the moment the Aura leaves — where the
    # card-rebuilding version had to stash the original and restore it.
    if animating_auras(perm):
        effects.append(
            add_types(only, card_types=["creature"], timestamp=0, label="animated artifact")
        )

    for static in global_statics_applying_to(perm):
        if static.adds_creature_type:
            effects.append(
                add_types(only, card_types=["creature"], timestamp=0, label=static.name)
            )

    # CR 305.7: setting a land's subtype *replaces* its old ones, so two of
    # these on one land do not commute — the newer contribution is what the land
    # is. They are collected rather than merged, and each carries the timestamp
    # of the effect that recorded it, so 613.7 decides that and not the order the
    # writes happened to run in (engine/land_types.py).
    for change in land_type_changes(perm):
        land_type = str(change["land_type"])
        effects.append(
            add_types(
                only,
                subtypes=[land_type],
                replace_subtypes=True,
                timestamp=int(change.get("timestamp", 0)),
                label=f"is a {land_type}",
            )
        )

    return effects


def collect_control_effects(perm: Permanent, oid: int) -> list[ContinuousEffect]:
    """Layer 2: control-changing effects (Control Magic, Steal Artifact,
    Aladdin, Old Man of the Sea, Ghazbán Ogre).

    Each contribution recorded in ``engine/control.py`` becomes its own effect
    carrying its own timestamp, so two thefts of the same permanent are ordered
    by CR 613.7 and not by which code path ran last — and one of them ending
    leaves the other still applying, which the previous remember-the-previous-
    controller model could not express.
    """
    only = scope_only(oid)
    return [
        change_control(
            only,
            int(entry["controller_index"]),
            timestamp=int(entry["timestamp"]),
            label=f"control:{entry['source'].card.name}",
        )
        for entry in control_changes(perm)
    ]


def computed_controller(perm: Permanent, base_seat: int) -> int:
    """The seat that controls *perm* after layer 2, starting from *base_seat*.

    The fast path matters: this is asked by ``Game.controller_index_of``, which
    sits under targeting, triggers and every "creatures you control" filter. A
    permanent nothing has ever taken control of skips the layer engine entirely.
    """
    if not has_control_change(perm):
        return base_seat
    oid = id(perm)
    state: State = {oid: Characteristics(controller_index=base_seat)}
    apply_layers(collect_control_effects(perm, oid), state)
    result = state[oid].controller_index
    return base_seat if result is None else result


def collect_color_effects(perm: Permanent, oid: int) -> list[ContinuousEffect]:
    """Layer 5: colour-changing effects (the laces, "becomes red")."""
    only = scope_only(oid)
    meta = perm.metadata

    override = meta.get("color_override")
    if override:
        return [set_colors(only, [override], timestamp=0, label="colour override")]
    copied = meta.get("copied_colors")
    if copied is not None:
        return [set_colors(only, list(copied), timestamp=0, label="copied colours")]
    return []


def computed_characteristics(perm: Permanent) -> Characteristics:
    """Every characteristic of *perm* after the layers that are wired up.

    Layers 4, 5, 6 and 7 today. Layer ordering matters between them — a land
    animated in layer 4 is a creature by the time a creature-scoped effect is
    considered — which is exactly what the system is for.
    """
    oid = id(perm)
    state: State = {oid: seed_characteristics(perm)}
    effects = (
        collect_type_effects(perm, oid)
        + collect_color_effects(perm, oid)
        + collect_ability_effects(perm, oid)
        + collect_pt_effects(perm, oid)
    )
    apply_layers(effects, state)
    return state[oid]


def computed_abilities(perm: Permanent) -> set[str]:
    """The keyword abilities *perm* currently has, after layer 6."""
    oid = id(perm)
    state: State = {oid: seed_characteristics(perm)}
    apply_layers(collect_ability_effects(perm, oid), state)
    return state[oid].abilities


def computed_types(perm: Permanent) -> tuple[set[str], set[str]]:
    """``(card_types, subtypes)`` after layer 4."""
    oid = id(perm)
    state: State = {oid: seed_characteristics(perm)}
    apply_layers(collect_type_effects(perm, oid), state)
    return state[oid].card_types, state[oid].subtypes


def computed_colors(perm: Permanent) -> set[str]:
    """The colours *perm* currently is, after layer 5."""
    oid = id(perm)
    state: State = {oid: seed_characteristics(perm)}
    apply_layers(collect_color_effects(perm, oid), state)
    return state[oid].colors


def computed_pt(perm: Permanent) -> tuple[int, int]:
    """This permanent's power and toughness, computed through the layer system.

    Single-object: the board-wide effects a permanent is subject to have
    already been folded into its own channels by the continuous-effects
    refresh, so nothing here needs the rest of the battlefield. When those
    effects become first-class :class:`ContinuousEffect` objects with real
    scopes, this becomes a whole-board computation and the refresh disappears.
    """
    oid = id(perm)
    state: State = {oid: seed_characteristics(perm)}
    apply_layers(collect_pt_effects(perm, oid), state)
    char = state[oid]
    return (char.power or 0, char.toughness or 0)


__all__ = [
    "collect_control_effects", "collect_pt_effects", "computed_controller",
    "computed_pt", "seed_characteristics",
]
