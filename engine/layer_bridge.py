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

import re
from functools import lru_cache
from typing import TYPE_CHECKING

from .oracle_types import compilation_cache
from .banding import band_quality
from .auras import (
    animating_auras,
    aura_conditional_grant_holds,
    aura_conditional_keyword_grants,
    aura_keyword_grants,
    aura_keyword_removals,
    aura_pt_grant_per_counter,
    aura_static_pt_grant,
    aura_type_grants,
    auras_attached_to,
)
from .named_counters import counters_on
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
    remove_types,
    scope_only,
    set_colors,
    set_pt,
    switch_pt,
)
from .keywords import ability_effects, derived_grants, derived_removals
from .landwalk import landwalk_requirement
from .land_types import land_type_changes, lost_abilities_to_type_change
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
#: Types an effect added to a permanent, with what else the same sentence
#: said. A list, because two effects may each add a type and neither
#: replaces the other; each entry carries its own duration so the sweep
#: that clears it knows which ones it owns.
GAINED_TYPES = "gained_types"
#: Types an effect took *away* from a permanent, the mirror of the above and a
#: list for the same reason. One entry per effect, so the removal ends by
#: dropping the contribution rather than by remembering what was there.
LOST_TYPES = "lost_types"
#: Supertypes a board-wide **static** takes away ("All lands are no longer
#: snow", Melting), rebuilt from the board by
#: ``mixins/permanent_state._refresh_static_land_types`` on every recompute. A
#: plain list of words rather than a record, because a static's contribution
#: carries no duration to expire and no source to end it: it lasts exactly as
#: long as the rebuild keeps putting it back.
DERIVED_LOST_SUPERTYPES = "derived_lost_supertypes"

_QUALIFIER_HOLDS = {
    "attacking": lambda perm: bool(perm.attacking),
    # CR 508.1a's negative half. Its own row rather than a "not" the reader
    # applies, so the import guard below counts it and a qualifier the table can
    # produce always has something here that checks it.
    "not attacking": lambda perm: not perm.attacking,
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
        word for word in ("artifact", "creature", "enchantment", "instant", "land", "planeswalker", "sorcery")
        if word in lowered
    )
    subtypes: frozenset[str] = frozenset()
    if "—" in type_line or "-" in type_line:
        tail = type_line.replace("—", "-").split("-", 1)[-1]
        subtypes = frozenset(word.lower() for word in tail.split() if word)
    return card_types, subtypes


@lru_cache(maxsize=None)
def printed_supertypes(type_line: str) -> frozenset[str]:
    """The supertypes printed on *type_line* — "legendary", "basic", "snow".

    Its own reader rather than a third return value from ``_printed_shape``,
    because it answers for two different kinds of object and one of them is a
    ``Permanent``: a supertype is not something layers 4 or 6 compute here, so
    the answer is whatever line the object *effectively* has (a copy's, a text
    change's) and there is no computed accessor to defer to. Callers pass the
    line they mean and the difference stays visible at the call site.

    Read against the vocabulary rather than a literal list, so a set printing a
    new supertype needs ``fetch_vocabulary.py`` and nothing else.
    """
    from .grammar.vocabulary import TYPE_LINE_SUPERTYPES

    head = type_line.replace("—", "-").split("-", 1)[0].lower()
    return frozenset(word for word in head.split() if word in TYPE_LINE_SUPERTYPES)


def printed_shape(card) -> tuple[frozenset[str], frozenset[str]]:
    """The card types and subtypes *card* is printed with.

    The answer for an object **outside** the battlefield — a card in a hand, a
    graveyard or a library — where CR 613 does not apply at all and there is no
    permanent to ask ``has_type``. On the battlefield this is only the seed;
    layers 4 and 6 may have moved it since, so a caller holding a ``Permanent``
    wants ``has_type`` and never this.
    """
    return _printed_shape(card.type_line, card.name, card.oracle_text, card.keywords)


def seed_characteristics(perm: Permanent) -> Characteristics:
    """An object's copiable values — where layer application starts (613.2c).

    Every field reads the *same* card: ``effective_card`` is layer 1 (the copy)
    and then layer 3 (the text change), and CR 613.2c says the result of layer 1
    **is** the copiable values. While copies were stamped as overrides this
    function could not do that — colour had to seed from ``perm.card`` so
    Vesuvan Doppelganger's blue survived, and P/T had to seed from ``perm.card``
    so the copy's ``absolute_power`` stamp did not get counted twice in 7b. Both
    of those were the stamped model showing through the seam; layer 1 puts the
    exception where it belongs, in the copy effect.

    ``None`` power/toughness means the printed value is variable ("*"), so a
    characteristic-defining ability in 7a supplies it. That is the distinction
    the old code could not make, having no value for "not a number".
    """
    card = perm.effective_card
    card_types, subtypes = _printed_shape(
        card.type_line, card.name, card.oracle_text, card.keywords
    )
    return Characteristics(
        card_types=set(card_types),
        subtypes=set(subtypes),
        # CR 205.4a's half of the line, seeded here for the reason every other
        # field is: a supertype an effect adds or removes (Arcum's Weathervane,
        # Melting) is a layer-4 change like any other, and a channel that starts
        # empty could only ever *add*. ``Characteristics.supertypes`` and
        # ``add_types``' keyword had been here since the layer system was
        # written with nothing seeding them and nothing reading them back — a
        # channel built at both ends and connected at neither.
        supertypes=set(printed_supertypes(card.type_line)),
        colors=set(card.colors),
        abilities=_printed_abilities(card),
        power=card.base_power,
        toughness=card.base_toughness,
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
    "indestructible", "menace", "prowess", "flash",
    # "rampage" is the word alone, and the printed line is "Rampage 2" — so the
    # ingested keywords field seeds "rampage 2" and nothing asking for the
    # *ability* found it. CR 702.23c counts instances of rampage, which is what
    # "does it have rampage" means (Rapid Fire's "if it doesn't have rampage"),
    # and the number is the instance's parameter rather than part of the name.
    # A substring scan is safe here for the reason it is not for hexproof:
    # there is no narrower keyword whose name contains this one.
    "rampage",
    # …and "flanking", for the same two reasons: it is what a *granted* line
    # (Agility) puts back into the ability set, and it is what the next
    # flanker's own "without flanking" filter asks. The substring scan is safe
    # here on the same test — no narrower keyword's name contains this word.
    "flanking",
    # …and "phasing", which a card can carry as a printed line alone: Teferi's
    # Curse grants it as a keyword and Shimmer as a board-wide static, and the
    # untap step reads the word off this set. Same substring test as the two
    # above — no narrower keyword's name contains it.
    "phasing",
    # "hexproof" is deliberately absent: this is a substring scan, and bare
    # hexproof is a *stronger* keyword than "hexproof from <colour>" — matching
    # the word inside the phrase would upgrade Sporeweb Weaver's blue-only
    # shield to a full one. Printed hexproof arrives through the ingested
    # keywords field, which the seed consults first.
)


#: "<qualifier> <type>walk" as it is printed inside a keyword line. The
#: qualifier is captured and handed to `landwalk_requirement`, which decides
#: whether it is a real one — so this pattern is deliberately permissive.
_QUALIFIED_WALK = r"(\w+) %s\b"


def _text_keywords_in(value: str) -> set[str]:
    """The keywords printed in one keyword or static line.

    A substring scan, and the one place its hazard is answered rather than
    assumed. ``_TEXT_KEYWORDS``' own comment says a bare word is safe "for the
    reason it is not for hexproof: there is no narrower keyword whose name
    contains this one" — Ice Age is where that stopped being true. "Snow
    forestwalk" (Rime Dryad, Legions of Lim-Dul) *contains* "forestwalk", and
    the containing phrase is the **narrower** ability: seeded as plain
    forestwalk, Rime Dryad was unblockable against any Forest at all, which is a
    strictly better creature than the one printed.

    So a walk word is dropped when the printed text qualifies it, and the
    qualified ability takes its place. Which qualifiers count is asked of
    ``landwalk_requirement`` — the reader that *enforces* the ability — rather
    than of a list here, so a supertype the vocabulary gains later is covered
    the day it is fetched, and a word that is not a real qualifier leaves the
    bare ability alone.
    """
    found = {word for word in _TEXT_KEYWORDS if word in value}
    for word in list(found):
        if not word.endswith("walk"):
            continue
        for match in re.finditer(_QUALIFIED_WALK % word, value):
            if landwalk_requirement(f"{match.group(1)} {word}") is not None:
                found.discard(word)
                found.add(f"{match.group(1)} {word}")
    return found


def _printed_abilities(card) -> set[str]:
    return set(_printed_abilities_cached(
        card.name, card.type_line, card.oracle_text, card.keywords
    ))


@compilation_cache
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
        abilities.update(_text_keywords_in(value))
        # A printed "bands with other [quality]" line (CR 702.22b) — the Wolves
        # of the Hunt token Master of the Hunt makes carries one. It cannot ride
        # the word scan above: the ability's name *is* the printed quality, so
        # there is no word to look for. Each comma-joined part is asked
        # separately, exactly as the keyword-line gate admits them.
        for part in value.split(","):
            part = part.strip()
            if band_quality(part) is not None:
                abilities.add(part)
            # "Legendary landwalk" (Livonya Silone) — the same shape, and it
            # cannot ride the word scan above either: CR 702.14a builds the
            # ability's name out of the printed quality, so there is no fixed
            # word to look for. The ingested keywords field usually carries it,
            # but a fixture card built from oracle text alone has only this.
            if landwalk_requirement(part) is not None:
                abilities.add(part)
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
    # The key is the *whole* set of states the sentence named, and every one of
    # them has to hold: "each untapped creature … as long as it's not attacking"
    # (Arcades Sabboth) describes one set, not two overlapping ones, so an `all`
    # here is what keeps the buff off a creature meeting half the description.
    for qualifiers, (power, toughness) in sorted((meta.get(QUALIFIED_BUFFS) or {}).items()):
        if all(qualifier_holds(perm, qualifier) for qualifier in qualifiers):
            label = " and ".join(qualifiers)
            modifications.append((int(power), int(toughness), f"lord buff while {label}"))
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

    # The P/T half of a gained-type record that says so ("…with power and
    # toughness each equal to its mana value", Xenic Poltergeist). Layer 7b,
    # beside Animate Artifact's, and the same value: CR 202.3's mana value of
    # the permanent, which for a 0-cost artifact really is 0/0 and really does
    # die to CR 704.5f.
    for gained in meta.get(GAINED_TYPES) or ():
        if gained.get("pt_from_mana_value"):
            value = int(perm.card.cmc)
            effects.append(set_pt(
                only, value, value,
                timestamp=_DERIVED_TIMESTAMP,
                label=f"gained-pt:{gained.get('source', 'effect')}",
            ))

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
        # "…gets +1/+1 **for each soul counter on this Equipment**." (Malefic
        # Scythe.) Read before the flat grant, because the flat pattern matches
        # this line's prefix — answering it would be an Equipment whose counters
        # do nothing. The count comes off the Equipment, not the creature.
        per_counter = aura_pt_grant_per_counter(aura.effective_card.oracle_text)
        if per_counter is not None:
            power, toughness, counter = per_counter
            held = counters_on(aura, counter)
            if held:
                effects.append(modify_pt(
                    only, power * held, toughness * held,
                    timestamp=int(aura.metadata.get("aura_timestamp", _DERIVED_TIMESTAMP)),
                    label=f"{counter} counters",
                ))
            continue
        grant = aura_static_pt_grant(aura.effective_card.oracle_text)
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

    # Nothing here for a copy's keywords: they are part of its copiable values
    # (CR 707.2a — the abilities are derived from the copied rules text), so
    # they arrive in the seed with everything else printed, where a layer-6
    # removal can take them away. Granting them *in layer 6* instead made them
    # outrank a removal that was recorded earlier.

    # Deathtouch is stamped as a flag by the combat code rather than granted
    # through the keyword API; collect it so layer 6 sees it too.
    if perm.metadata.get("has_deathtouch"):
        effects.append(grant_abilities(only, ["deathtouch"], timestamp=0, label="deathtouch"))

    # "…becomes a 3/3 Sphinx creature **with flying**…" (Riddleform). The other
    # half of the same record the type collector reads: one animation, two
    # layers, and each half collected where its layer is — a grant recorded in
    # the layer-4 collector is a grant `computed_abilities` never sees, which is
    # what this comment is here to stop happening again.
    # Both animation records, because the keyword half of an animation is the
    # same grant whichever duration wrote it — the swept key and the indefinite
    # one (Mishra's Groundbreaker). Reading only the first is how a permanent
    # animation would arrive without the keywords its own sentence granted.
    for _key in ("animate_until_end_of_turn", "animate_indefinitely"):
        animation = perm.metadata.get(_key) or {}
        granted = animation.get("keywords") or ()
        if granted:
            effects.append(grant_abilities(
                only, granted, timestamp=0, label=f"animated ({_key})"
            ))

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

    # And the mirror: abilities a board-wide source is taking away right now
    # ("All creatures lose flying", Gravity Sphere). Derived every recompute
    # like the grant above, so the ability comes back the moment the source
    # leaves — there is no stored removal to reverse.
    removed = derived_removals(perm)
    if removed:
        effects.append(
            remove_abilities(only, list(removed), timestamp=0, label="lord removal")
        )

    # Layer 6 from each attached Aura, stamped with the moment it attached
    # (CR 613.7b) — derived every recompute, so the grant ends when the Aura
    # leaves without anything having to find and undo it.
    for aura in auras_attached_to(perm):
        text = aura.effective_card.oracle_text
        # "…has shroud **as long as it's untapped**." (Spectral Cloak.) The
        # condition is about the host, and it is asked here rather than recorded
        # when the Aura attached: CR 611.3a says a static ability applies
        # whenever its criteria are met, so a creature that taps between
        # recomputes loses the word immediately.
        granted = list(aura_keyword_grants(text)) + [
            keyword
            for keyword, state in aura_conditional_keyword_grants(text)
            if aura_conditional_grant_holds(perm, state)
        ]
        stamp = int(aura.metadata.get("aura_timestamp", 0))
        # "Enchanted creature **loses** flying." (Mammoth Harness.) The same
        # layer and the same attach timestamp, contributed in the opposite
        # direction — which is what CR 613.9's ordering needs: a removal
        # recorded later beats an earlier grant and a grant recorded later beats
        # an earlier removal, and only two contributions in one order can say
        # that. Derived here on every recompute like its mirror, so detaching
        # the Aura gives the ability back with nothing to undo.
        removed = aura_keyword_removals(text)
        if removed:
            effects.append(
                remove_abilities(
                    only, list(removed), timestamp=stamp,
                    label=f"aura:{aura.card.name}",
                )
            )
        if not granted:
            continue
        effects.append(
            grant_abilities(
                only,
                granted,
                timestamp=stamp,
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

    # CR 305.7's losing half. A land whose subtype an effect *set* to basic
    # land types loses the abilities its rules text generated — the same
    # removal Titania's Song makes above, on a different condition, so it is
    # built the same way and from the same printed-ability read (which is what
    # keeps a *granted* ability, as 305.7's "Note that this doesn't remove any
    # abilities that were granted to the land by other effects" requires).
    #
    # The timestamp is the type change's own, not 0: an ability granted after
    # the land became a Mountain is later in the order and survives (CR 613.7).
    if lost_abilities_to_type_change(perm):
        printed = sorted(_printed_abilities(perm.effective_card))
        if printed:
            effects.append(
                remove_abilities(
                    only, printed,
                    timestamp=max(
                        int(change.get("timestamp", 0)) for change in land_type_changes(perm)
                    ),
                    label="CR 305.7",
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
    for gained in meta.get(GAINED_TYPES) or ():
        effects.append(add_types(
            only,
            card_types=list(gained.get("card_types") or ()),
            subtypes=list(gained.get("subtypes") or ()),
            supertypes=list(gained.get("supertypes") or ()),
            timestamp=0,
            label=f"gained:{gained.get('source', 'effect')}",
        ))

    # Layer 4's removing half, applied after every addition above so a later
    # add wins on timestamp (CR 613.7). "…as a non-Aura enchantment"
    # (Takklemaggot): the returning permanent is still an enchantment and is no
    # longer an Aura, which is one subtype off the printed line and nothing
    # else. Read here rather than at the CR 704.5m sweep, so every reader of
    # "is this an Aura?" gets the same answer.
    for lost in meta.get(LOST_TYPES) or ():
        effects.append(remove_types(
            only,
            card_types=list(lost.get("card_types") or ()),
            subtypes=list(lost.get("subtypes") or ()),
            supertypes=list(lost.get("supertypes") or ()),
            timestamp=0,
            label=f"lost:{lost.get('source', 'effect')}",
        ))
    # The *derived* half of the same channel: a board-wide static's contribution
    # ("All lands are no longer snow", Melting), cleared and rebuilt from the
    # board on every continuous-effects refresh. Split from the recorded channel
    # above for the reason ``land_types.py`` splits its two — a rebuilt
    # contribution recorded alongside a stamped one accumulates an entry per
    # pass, forever.
    for word in meta.get(DERIVED_LOST_SUPERTYPES) or ():
        effects.append(remove_types(
            only,
            supertypes=[word],
            timestamp=_DERIVED_TIMESTAMP,
            label=f"static:no longer {word}",
        ))

    # Both animation records again, for the reason the keyword collector above
    # reads both: the layer-4 contribution an animation makes does not depend on
    # when it ends. The cleanup sweep clears the first key and never hears of
    # the second (``handlers/board_misc.ANIMATE_INDEFINITELY``), which is the
    # whole of the difference between them.
    for _key in ("animate_until_end_of_turn", "animate_indefinitely"):
        animation = meta.get(_key)
        if animation:
            effects.append(add_types(
                only,
                # "…a 2/2 Assembly-Worker **artifact** creature" (Mishra's
                # Factory): every type the sentence named, not just the head
                # noun. A land animated without the artifact type is a permanent
                # Shatter cannot reach and Titania's Song does not see.
                card_types=["creature", *(animation.get("card_types") or ())],
                subtypes=animation.get("subtypes") or (),
                timestamp=0,
                label=f"animated ({_key})",
            ))
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

    # "…it becomes your choice of … a 1/6 **Wall** artifact creature with
    # defender" (Primal Clay). The body's P/T is layer 7b and its keyword is
    # layer 6; its creature type is here, added rather than replacing, and
    # derived from the recorded choice so swapping bodies needs nothing undone.
    chosen_body = meta.get("chosen_body") or {}
    body_subtypes = list(chosen_body.get("subtypes") or ())
    if body_subtypes:
        effects.append(
            add_types(only, subtypes=body_subtypes, timestamp=0, label="chosen body")
        )

    # "…and is a Knight in addition to its other types" (Dub, Demonic Embrace).
    # *Added*, not replacing — which is the whole difference from the land-type
    # change below, and why the two cannot share a call. Derived from the Aura's
    # own text on every recompute and stamped with the moment it attached
    # (CR 613.7b), so detaching one simply stops contributing the type.
    for aura in auras_attached_to(perm):
        added = aura_type_grants(aura.effective_card.oracle_text)
        if not added:
            continue
        effects.append(
            add_types(
                only,
                subtypes=list(added),
                timestamp=int(aura.metadata.get("aura_timestamp", 0)),
                label=f"aura:{aura.card.name}",
            )
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
            # The source is a permanent for a linked change and a *card* for a
            # spell's until-end-of-turn one (Traitorous Greed) — the label is a
            # name either way, and asking each object for its own is what keeps
            # this from having to know which kind it was handed.
            label=f"control:{_control_source_name(entry['source'])}",
        )
        for entry in control_changes(perm)
    ]


def _control_source_name(source) -> str:
    """The name of whatever recorded a control contribution."""
    card = getattr(source, "card", None)
    return getattr(card if card is not None else source, "name", "?")


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
    """Layer 5: colour-changing effects (the laces, "becomes red").

    A copy's colours are *not* here. CR 707.2a derives them from the copied mana
    cost, which makes them a copiable value settled in layer 1 — and modelling
    them as a layer-5 effect is what made Vesuvan Doppelganger's exception
    inexpressible, because "keeps its own colour" then had to mean "no effect was
    recorded", which is also what a copy of a colourless artifact looked like.
    """
    effects = []
    # Two channels, in timestamp order (CR 613.7b), for the reason layer 7b
    # keeps two: an indefinite lace ("Target permanent becomes red", CR 105)
    # and a turn-long one ("One or more target creatures become red until end
    # of turn", the five Legends colour spells). Sharing one key would make the
    # cleanup step's sweep either drop a lace that should outlive the turn, or
    # keep a colour that should have worn off.
    for suffix, stamp in (("", 0), ("_until_eot", 1)):
        override = perm.metadata.get(f"color_override{suffix}")
        if override:
            # A *set* of colours where the card offered one ("becomes the color
            # or colors of your choice", Dream Coat) — CR 105.2 makes an object
            # of two colours one object, not two effects. Normalized here rather
            # than at every write, because this is the one reader: a channel
            # that could hold either and a reader that could only take one would
            # make a multicoloured permanent read as a list-shaped colour.
            colours = list(override) if isinstance(override, (list, tuple)) else [override]
            effects.append(
                set_colors(scope_only(oid), colours, timestamp=stamp,
                           label=f"colour override{suffix}")
            )
    return effects


def computed_abilities(perm: Permanent) -> set[str]:
    """The keyword abilities *perm* currently has, after layer 6."""
    oid = id(perm)
    state: State = {oid: seed_characteristics(perm)}
    apply_layers(collect_ability_effects(perm, oid), state)
    return state[oid].abilities


def displayed_type_line(perm: Permanent) -> str:
    """The type line to *show* for *perm*: the printed line with layer 4's
    removals dropped and its additions appended.

    ``effective_card.type_line`` is layers 1 and 3 — what the object copies and
    what a text change rewrote — and stops there, which left the screen
    disagreeing with the rules in both directions. A permanent returned "as a
    **non-Aura** enchantment" (Takklemaggot) read "Enchantment — Aura" while
    every rules query said it was not one; an Evil Presence'd Forest read
    "Basic Land — Forest" while the engine, correctly, answered Swamp and not
    Forest; and a creature wearing Demonic Embrace read "Creature — Dog" with no
    sign of the Demon its Aura grants. One rule answers all three, because they
    are one question: what does layer 4 say this permanent is?

    A **view of that answer, not a second opinion about it.** Every printed word
    is kept or dropped by asking the same computed sets :meth:`Permanent.has_type`
    and :meth:`Permanent.has_supertype` answer from, and a word that survives
    keeps its printed spelling and its printed position. That is what rebuilding
    the line from ``computed_types`` could not do — the computed sets are
    lowercase and unordered, so "Assembly-Worker" comes back mis-spelled and
    "Basic Snow Land" comes back in some other order — and it is why a permanent
    no effect touches gets its printed line back byte-identical.

    A *gained* word has no printed position to keep, so it is placed by class: a
    supertype goes ahead of the card types, which is where CR 205.4a puts one
    ("Basic Land" + snow reads "Basic Snow Land"), and a card type or subtype is
    appended after the printed ones. An animated Mishra's Factory therefore
    reads "Land Artifact Creature — Assembly-Worker" rather than the "Artifact
    Creature Land" a card printed that way would use: there is no printed
    authority for a temporary animation's word order, and inventing one would
    mean reordering the printed half to match a guess.
    """
    from .grammar.vocabulary import TYPE_LINE_SUPERTYPES, display_type_word

    line = perm.effective_card.type_line
    card_types, subtypes = computed_types(perm)
    supertypes = computed_supertypes(perm)
    # Split the same way ``_printed_shape`` seeds from, so the words being
    # judged are the words that were counted.
    head, _, tail = line.replace("—", "-").partition("-")

    printed_head = head.split()
    printed_tail = tail.split()
    # Which half of the head each printed word belongs to. A supertype and a
    # card type are checked against different computed sets, and only the line
    # itself says which a word is.
    printed_supertype_words = {
        word for word in printed_head if word.lower() in TYPE_LINE_SUPERTYPES
    }

    kept_supertypes = [
        word for word in printed_head
        if word in printed_supertype_words and word.lower() in supertypes
    ]
    kept_card_types = [
        word for word in printed_head
        if word not in printed_supertype_words and word.lower() in card_types
    ]
    kept_subtypes = [word for word in printed_tail if word.lower() in subtypes]

    printed_head_words = {word.lower() for word in printed_head}
    printed_tail_words = {word.lower() for word in printed_tail}
    gained_supertypes = sorted(supertypes - printed_head_words)
    gained_card_types = sorted(card_types - printed_head_words)
    gained_subtypes = sorted(subtypes - printed_tail_words)
    if not (gained_supertypes or gained_card_types or gained_subtypes) and (
        len(kept_supertypes) + len(kept_card_types) == len(printed_head)
        and len(kept_subtypes) == len(printed_tail)
    ):
        # Nothing added and nothing dropped: hand back the printed line itself
        # rather than a reassembled copy of it, so the punctuation and spacing
        # of a line no effect has touched are the card's own.
        return line

    words = (
        kept_supertypes
        + [display_type_word(word) for word in gained_supertypes]
        + kept_card_types
        + [display_type_word(word) for word in gained_card_types]
    )
    described = kept_subtypes + [display_type_word(word) for word in gained_subtypes]
    if not described:
        return " ".join(words)
    return f"{' '.join(words)} — {' '.join(described)}"


def computed_types(perm: Permanent) -> tuple[set[str], set[str]]:
    """``(card_types, subtypes)`` after layer 4."""
    oid = id(perm)
    state: State = {oid: seed_characteristics(perm)}
    apply_layers(collect_type_effects(perm, oid), state)
    return state[oid].card_types, state[oid].subtypes


def computed_supertypes(perm: Permanent) -> set[str]:
    """The supertypes *perm* currently has, after layer 4 (CR 205.4a).

    The computed answer to a question nine call sites used to put to the printed
    line through :func:`printed_supertypes`. That was right while no card in the
    pool could change one and wrong the moment Ice Age's Arcum's Weathervane
    arrived — the ``has_type`` story again, one layer up.
    """
    oid = id(perm)
    state: State = {oid: seed_characteristics(perm)}
    apply_layers(collect_type_effects(perm, oid), state)
    return state[oid].supertypes


def types_before_timestamp(perm: Permanent, timestamp: int) -> Characteristics:
    """The type characteristics *perm* presents to the layer-4 effect stamped
    *timestamp* — CR 613.7's intermediate state.

    "An effect with an earlier timestamp is applied before an effect with a
    later timestamp": within a layer each effect is judged against the seed
    (layers 1 and 3, via ``seed_characteristics``) plus every effect already
    applied, and nothing after it. :func:`computed_types` answers what the
    layer has *finished* saying, which is the wrong question while the layer is
    still being decided — the refresh that derives the board-wide statics'
    contributions (``mixins/permanent_state._refresh_static_land_types``) is
    computing layer 4's inputs, and reading the finished answer there feeds the
    previous pass's result back in as this pass's premise. Filtering by
    timestamp is the rule's own shape instead: the channels hold the
    contributions decided so far, and an effect not yet reached is simply not
    in the prefix this replays.
    """
    oid = id(perm)
    state: State = {oid: seed_characteristics(perm)}
    apply_layers(
        [
            effect
            for effect in collect_type_effects(perm, oid)
            if effect.timestamp < timestamp
        ],
        state,
    )
    return state[oid]


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
    "computed_pt", "computed_supertypes", "seed_characteristics",
    "types_before_timestamp",
]
