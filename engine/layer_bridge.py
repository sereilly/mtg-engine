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
    aura_color_grants,
    aura_conditional_grant_holds,
    aura_conditional_keyword_grants,
    aura_keyword_grants,
    aura_keyword_removals,
    aura_land_animation,
    aura_pt_grant_per_counter,
    aura_static_pt_grant,
    aura_card_type_grants,
    aura_type_grants,
    auras_attached_to,
    chosen_landwalk_grants,
)
from .color_changes import color_changes
from .named_counters import counters_on
from .control import control_changes, has_control_change
from .enter_effects import CHOSEN_COLOR_KEY, own_chosen_color
from .global_statics import (STACK_STATICS_KEY, changes_types,
                             global_static_sources, global_statics_applying_to,
                             removes_all_abilities)
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
from .landwalk import BOARD_NAMED_LANDWALKS, landwalk_requirement
from .land_types import land_type_changes
from .lord_buffs import QUALIFIER_FIELDS
from .type_changes import (
    GAINED_TYPES,
    LAND_ANIMATION_ORDER,
    LOST_TYPES,
    derived_lost_supertypes,
    gained_types,
    lost_types,
    static_type_order,
)

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
# ``GAINED_TYPES`` / ``LOST_TYPES`` — the types a resolved effect added to or
# took from a permanent — are ``engine/type_changes.py``'s, the write API that
# stamps them (CR 613.7b). Imported above so the name this module has always
# exported still resolves; nothing here spells either key.
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

#: Each entry takes the permanent **and the seat whose lord contributed the
#: buff** (CR 109.5's "you"), because one qualifier is a relation to that seat
#: rather than a state of the creature. Every row takes it so there is one
#: signature: a table of two arities is a table whose reader has to know which
#: row it is looking at.
_QUALIFIER_HOLDS = {
    "attacking": lambda perm, observer: bool(perm.attacking),
    # CR 508.1a's negative half. Its own row rather than a "not" the reader
    # applies, so the import guard below counts it and a qualifier the table can
    # produce always has something here that checks it.
    "not attacking": lambda perm, observer: not perm.attacking,
    # "all creatures **attacking you**" (Watchdog). CR 508.1a makes attacking a
    # state of the creature; *whom* it attacks is the defending player it was
    # declared against, so this is two questions and answering only the first
    # would shrink the attackers aimed at somebody else in a multiplayer game.
    # With no observer there is no "you" for the phrase to be relative to and
    # the answer is no — the direction that applies the buff to nobody rather
    # than to the whole board.
    "attacking you": lambda perm, observer: (
        bool(perm.attacking)
        and observer is not None
        and perm.defending_player_index == observer
    ),
    # CR 509.1a: a creature is blocking once it has been declared as a blocker.
    "blocking": lambda perm, observer: perm.blocking_attacker_index is not None,
    "tapped": lambda perm, observer: bool(perm.tapped),
    "untapped": lambda perm, observer: not perm.tapped,
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


def qualifier_holds(
    perm: Permanent, qualifier: str, observer: int | None = None
) -> bool:
    """Whether *perm* is currently in the state *qualifier* names.

    *observer* is the seat controlling the lord that contributed the buff —
    CR 109.5's "you" — needed by the one qualifier that names a relation to it
    ("attacking you") and ignored by the rest.
    """
    return _QUALIFIER_HOLDS[qualifier](perm, observer)


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
    """The keywords printed in one keyword line.

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
        # **A keyword line, and nothing else.** "Does this line give *this
        # permanent* this keyword?" is a question about the line's subject, and
        # the compiler's line classifier has already answered it: a line that
        # states the object's own keyword abilities is a ``keyword_line``
        # (CR 702), one that gives them to it on a condition is a
        # ``conditional_static`` and one that gives them to a class of
        # permanents is a ``lord_buff`` -- the last two contributed in layer 6
        # by their own readers, with the condition and the class enforced.
        #
        # A ``static_line`` is what is left: a sentence some text-keyed table
        # claimed and no instruction carries. This scan used to read those too,
        # and a word search has no subject, so it seeded whatever keyword the
        # sentence *mentioned*: Gliding Licid flew because it says "enchanted
        # creature has flying", Guardian Beast was indestructible because the
        # artifacts beside it are, Rootwater Shaman had flash because Auras may
        # be cast "as though they had flash", and Gosta Dirk had the islandwalk
        # his own text switches off. Faerie Squadron ("…and with flying", for a
        # *kicked* one) was the first found and was skipped by pattern; a skip
        # per sentence is a deny-list of a table that names no legitimate
        # entry. Over both manifest roles the pool carries 199 static lines, 18
        # of them mention a keyword, and not one of the 18 gives it to the
        # permanent printing it
        # (``tests/engine/test_printed_keyword_seed.py``).
        if instruction.kind != "keyword_line":
            continue
        value = instruction.value or ""
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
    # The key is ``(qualifiers, observer_seat)``: two lords printing the same
    # description contribute to the same entry only when they are *also* the
    # same "you", because "attacking you" means a different set of creatures
    # for each of them.
    for (qualifiers, observer), (power, toughness) in sorted(
        (meta.get(QUALIFIED_BUFFS) or {}).items(),
        key=lambda item: (item[0][0], -1 if item[0][1] is None else item[0][1]),
    ):
        if all(
            qualifier_holds(perm, qualifier, observer) for qualifier in qualifiers
        ):
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
    # 7b — "Enchanted land is a **5/6** green Treefolk creature that's still a
    # land." (Living Terrain.) The printed body's size, beside Animate
    # Artifact's computed one and stamped the same way; the type and colour
    # halves are layers 4 and 5 below.
    for aura in auras_attached_to(perm):
        body = aura_land_animation(aura.effective_card.oracle_text)
        if body is not None:
            effects.append(set_pt(
                only, body["power"], body["toughness"],
                timestamp=int(aura.metadata.get("aura_timestamp", _DERIVED_TIMESTAMP)),
                label=f"animated:{aura.card.name}",
            ))

    # The P/T half of a gained-type record that says so ("…with power and
    # toughness each equal to its mana value", Xenic Poltergeist). Layer 7b,
    # beside Animate Artifact's, and the same value: CR 202.3's mana value of
    # the permanent, which for a 0-cost artifact really is 0/0 and really does
    # die to CR 704.5f.
    for gained in gained_types(perm):
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
        # "…and have base power and toughness 1/1." (Humility.) CR 613.4b, the
        # same sublayer as the mana-value setting beside it and read off the
        # same static — so a +1/+1 counter or an anthem still applies at 7c and
        # the creature ends up 2/2. The printed pair rather than a computed
        # value is the only difference between the two branches.
        if static.sets_base_pt:
            power, toughness = static.sets_base_pt
            effects.append(
                set_pt(only, power, toughness,
                       timestamp=_DERIVED_TIMESTAMP, label=static.name)
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
    # …and the third (Jade Statue), for the reason the second is read here:
    # what an animation contributes to its layer does not depend on when it
    # ends. This key held a bare ``True`` until Jade Statue stopped being a
    # card hook, so the Statue was a creature and not a **Golem**: a lord did
    # not pump it and "destroy target Golem" missed it.
    for _key in (
        "animate_until_end_of_turn", "animate_indefinitely",
        "animate_until_end_of_combat",
    ):
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

    # Landwalks the permanent's own text names off its controller's lands —
    # "For each basic land type among lands you control, this creature has
    # landwalk of that type." (Magnigoth Treefolk.) The words are not in the
    # text and need the game to count, so the refresh that owns the count
    # (``_refresh_dynamic_creatures``, behind its layer-4 passes) derives them
    # and this collector — which is deliberately game-free — reads what it
    # left. In front of the removal below, so "all creatures lose …" still
    # takes a walk away.
    named_walks = perm.metadata.get(BOARD_NAMED_LANDWALKS) or ()
    if named_walks:
        effects.append(
            grant_abilities(
                only, list(named_walks), timestamp=0, label="board-named landwalk"
            )
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
        # "Enchanted creature has landwalk **of the chosen type**." (Traveler's
        # Cloak.) The one grant whose word is not in the text: it is the land
        # type this Aura recorded as it entered, re-read here so a late answer
        # to the entry prompt is the one the creature walks with.
        granted.extend(chosen_landwalk_grants(aura))
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

    # Nothing here for CR 305.7's losing half, and there used to be: a layer-6
    # removal of the land's printed keywords, stamped with the type change's
    # own timestamp. It was the wrong layer twice over. The loss is part of
    # the layer-4 effect that set the type, not an ability-removing effect of
    # its own, so it has no place in layer 6's timestamp order — an ability
    # another effect granted the land *before* its type was set is kept
    # exactly as one granted after is ("this doesn't remove any abilities that
    # were granted to the land by other effects"), and a removal stamped later
    # than the grant took it. And it reached only the keywords. The land's
    # text is struck where the text is read (``Permanent.effective_card``), so
    # the seed this layer starts from already holds no keyword of the land's
    # own.

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
        effects.append(add_types(
            only,
            card_types=list(gained.get("card_types") or ()),
            subtypes=list(gained.get("subtypes") or ()),
            supertypes=list(gained.get("supertypes") or ()),
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
    # the second (``handlers/board_misc.ANIMATE_INDEFINITELY``), which is the
    # whole of the difference between them.
    # …and the third (Jade Statue), for the reason the second is read here:
    # what an animation contributes to its layer does not depend on when it
    # ends. This key held a bare ``True`` until Jade Statue stopped being a
    # card hook, so the Statue was a creature and not a **Golem**: a lord did
    # not pump it and "destroy target Golem" missed it.
    for _key in (
        "animate_until_end_of_turn", "animate_indefinitely",
        "animate_until_end_of_combat",
    ):
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
                # Zero for every record written before a replacement could be
                # one: the additions commute, so nothing needed an order. A
                # replacement does not — Opal Acrolith turns itself back into
                # an enchantment and then animates again — so those records
                # carry the stamp CR 613.7b gives them.
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
    for static in meta.get(STACK_STATICS_KEY) or ():
        if changes_types(static):
            effect = global_static_type_effect(oid, None, static, timestamp=0)
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
    oid: int, *, timestamp: int, sequence: int = 0
) -> ContinuousEffect:
    """Layer 4: a land animator makes this land a creature "that's still a
    land" (CR 205.1b) — the creature type, added."""
    return add_types(
        scope_only(oid), card_types=["creature"], timestamp=timestamp,
        sequence=sequence, label="animated",
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
    subtypes = list(static.adds_subtypes)
    replaced: frozenset[str] = frozenset()
    if static.sets_creature_type:
        # Imported here rather than at module scope: this module is pulled in
        # by ``handlers/_common`` long before ``engine.grammar`` finishes
        # importing, and a top-level import of the vocabulary closes a cycle
        # through the grammar package.
        from .grammar.vocabulary import CREATURE_TYPES

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
    from .grammar.vocabulary import LAND_TYPES

    printed_types, printed_subtypes = printed_shape(perm.effective_card)
    if printed_types == {"land"}:
        return frozenset(LAND_TYPES | printed_subtypes)
    return frozenset(LAND_TYPES)


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


#: The printed colour word as the symbol every colour channel in this engine
#: spells one with. Here rather than in ``global_statics`` because that module
#: holds what the *card prints*, which is the word.
_COLOR_WORD_SYMBOLS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}


def collect_color_effects(perm: Permanent, oid: int) -> list[ContinuousEffect]:
    """Layer 5: colour-changing effects (the laces, "becomes red").

    **Every effect here carries the timestamp CR 613.7 gives it, and nothing
    else orders them.** They were five channels with a constant apiece — the
    permanent's own chosen colour −1, an indefinite recolour 0, a turn-long one
    1, a board-wide static 2 — so which effect applied last was decided by what
    *kind* it was: under Darkest Hour a later "becomes white until end of turn"
    did nothing, and a lace cast after a turn-long recolour lost to it. Each
    ``set_colors`` below replaces every colour the permanent had (CR 105.3), so
    the order is the whole answer and the stamps have to be real:

    * a resolved spell's or ability's effect — when it was created (CR 613.7b),
      stamped by ``color_changes.change_color``, the one writer;
    * a static ability's — its object's (CR 613.7a), which is the moment that
      object entered the battlefield (CR 613.7d) or, for an Aura or Equipment,
      last became attached (CR 613.7e): ``Permanent.timestamp`` either way.

    No dependency (CR 613.8) can arise among them: no colour-setting static in
    the pool has a scope that asks about colour, and a resolved recolour's set
    of objects was fixed when it resolved (CR 611.2c). Held to the pool by
    ``tests/rules/test_color_effects_timestamp_order.py``.

    A copy's colours are *not* here. CR 707.2a derives them from the copied mana
    cost, which makes them a copiable value settled in layer 1 — and modelling
    them as a layer-5 effect is what made Vesuvan Doppelganger's exception
    inexpressible, because "keeps its own colour" then had to mean "no effect was
    recorded", which is also what a copy of a colourless artifact looked like.
    """
    only = scope_only(oid)
    effects = []
    # "This creature is the chosen color." (Alloy Golem.) The permanent's own
    # static about its own colour, so its effect has the permanent's own
    # timestamp (CR 613.7a): the moment it entered. A lace or a Sway of
    # Illusion aimed at the Golem is necessarily later and wins; a Darkest Hour
    # that arrives after the Golem wins; a Darkest Hour that was **already
    # there** is earlier, and the Golem is the colour it chose.
    #
    # **It is not a characteristic-defining ability, and that was a ruling to
    # settle.** It shipped as one (`from_cda=True`, applied before every other
    # layer-5 effect, CR 613.3) on CR 604.3a's five criteria read down the
    # list. Two things in the rules say otherwise. CR 604.3 itself: a CDA
    # "functions in all zones ... outside the game and before the game begins",
    # and this colour exists nowhere but on a permanent that made a choice as
    # it entered (CR 614.1c). And criterion (5) - a CDA "does not set the
    # values of such characteristics only if certain conditions are met": the
    # sentence is linked to the choice (CR 607.2d) and does nothing where no
    # choice was made, which is the rules' own worked example for the pattern
    # (CR 607.2's Voice of All and Unstable Shapeshifter - "never had a chance
    # for a color to be chosen for it ... so it doesn't gain a protection
    # ability"). A value set only where a choice exists is a value set on a
    # condition. No ruling on the card speaks to it; this is the rules read as
    # written, and `from_cda=True` on the call below is the whole of the other
    # reading.
    #
    # Not contributed once its abilities are gone (CR 613.1f is layer 6, but a
    # removal that has already happened is the same predicate layer 6 itself
    # asks).
    own = own_chosen_color(perm)
    if own is not None and not removes_all_abilities(perm):
        effects.append(
            set_colors(
                only, [own], timestamp=perm.timestamp, label="chosen colour",
            )
        )
    # What a spell or an ability did to this permanent — an indefinite lace
    # ("Target permanent becomes red", CR 105), a turn-long one ("One or more
    # target creatures become red until end of turn", the five Legends colour
    # spells) — and what a land-animating static keeps saying of it ("All
    # Swamps are 1/1 **black** creatures", Kormus Bell). One reader for all
    # three, each contribution with the stamp its writer gave it
    # (``engine/color_changes.py``).
    for change in color_changes(perm):
        effects.append(
            set_colors(
                only, change["colors"], timestamp=int(change["timestamp"]),
                label=str(change.get("label") or "colour change"),
            )
        )

    # "Nonland permanents you control are white." (Celestial Dawn.) Board-wide,
    # and derived from the source's own text on every recompute exactly as the
    # Aura channel below is, so a source leaving simply stops contributing and
    # there is nothing to sweep. Walked as source/static *pairs* because the
    # source is what the effect is stamped by (CR 613.7a) — and, for Shifting
    # Sky, what it reads its colour from.
    for source, static in global_static_sources(
        perm.metadata.get("global_static_sources") or ()
    ):
        # ``is not None``, not truthiness: the **empty tuple** is CR 105.2c's
        # colourless ("All permanents are colorless", Thran Lens) -- an object
        # with no colours, rather than a static that says nothing about colour.
        # A falsy test reads the two as one and drops the whole effect.
        if static.sets_colors is not None:
            effects.append(
                set_colors(
                    only,
                    [_COLOR_WORD_SYMBOLS[word] for word in static.sets_colors],
                    timestamp=source.timestamp,
                    label=f"board-wide colour ({source.card.name})",
                )
            )
        # "All nonland permanents are **the chosen color**." (Shifting Sky.)
        # The same effect with the colour read off the **source** rather than
        # off the sentence — chosen as that permanent entered (CR 614.1c) and
        # recorded on it, the way layer 4 reads Conspiracy's chosen creature
        # type. A second answer to the entry prompt is the colour the board
        # then is; the timestamp is still the source's, because it is still
        # that object's static ability.
        if static.sets_chosen_color:
            chosen = source.metadata.get(CHOSEN_COLOR_KEY)
            # No contribution while the source is still entering, or if the
            # choice was never made: turning every nonland permanent colourless
            # on the strength of an unanswered choice is the card doing
            # something it does not say.
            if chosen:
                effects.append(
                    set_colors(
                        only, [str(chosen)], timestamp=source.timestamp,
                        label=f"board-wide chosen colour ({source.card.name})",
                    )
                )

    from .grammar.vocabulary import COLOR_WORDS

    # "Enchanted creature gets +3/-1 **and is black**." (Grave Servitude.)
    # Derived from the Aura's own text on each recompute and stamped with the
    # moment it attached (CR 613.7e), so detaching one simply stops
    # contributing the colour. That is the whole reason it is here rather than
    # recorded through ``change_color`` when the Aura resolves — a recorded
    # effect would outlive the Aura, and CR 105.3 replaces every colour the
    # creature had, so there would be nothing left to put back.
    for aura in auras_attached_to(perm):
        # The printed word mapped to the symbol every other colour in this
        # engine is spelled with, at the call site rather than in the reader —
        # `aura_protection_colors`' rule, and for its reason: the text change
        # that could rewrite the word (Sleight of Mind) is layer 3, already
        # folded into ``effective_card``, so the word read here is the word the
        # Aura currently says.
        granted = [
            COLOR_WORDS[word]
            for word in aura_color_grants(aura.effective_card.oracle_text)
            if word in COLOR_WORDS
        ]
        # "…a 5/6 **green** Treefolk creature…" (Living Terrain.) The body's
        # colour, already a symbol, on the same stamp as the rest of the Aura.
        body = aura_land_animation(aura.effective_card.oracle_text)
        if body is not None:
            granted.extend(body["colors"])
        if not granted:
            continue
        effects.append(
            set_colors(
                only, granted, timestamp=aura.timestamp,
                label=f"aura:{aura.card.name}",
            )
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
    "attached_animation_type_effect",
    "collect_control_effects", "collect_own_type_effects", "collect_pt_effects",
    "collect_static_type_effects", "computed_controller", "computed_pt",
    "computed_supertypes", "global_static_type_effect",
    "land_animation_type_effect", "land_type_effect", "lost_supertype_effect",
    "seed_characteristics",
]
