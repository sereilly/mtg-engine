"""Collect the engine's stored channels as CR 613 continuous effects.

``engine/continuous.py`` is the layer system; this module is the adapter that
feeds it. Each of the metadata channels a permanent carries becomes a
:class:`ContinuousEffect` placed in its proper layer and sublayer, and the
layer engine — not the order the reading code happens to be written in —
decides how they combine. Layers 7 (P/T), 6 (abilities), 2 (control) and 5
(colour) are collected here, with the computed accessors that apply them; the
seed they start from is ``engine/printed_characteristics.py`` and layer 4 is
``engine/type_layer.py``.

Keeping the adapter separate from the layer engine means the engine stays pure
and testable against the rule text, while the storage it reads from can move
(counters out of metadata, effects created with real timestamps) without the
rules logic changing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import fast_paths
from .aura_grants import (animating_auras, aura_color_grants,
                          aura_conditional_grant_holds,
                          aura_conditional_keyword_grants,
                          aura_keyword_grants, aura_keyword_removals,
                          aura_land_animation, aura_pt_grant_per_counter,
                          aura_static_pt_grant, chosen_landwalk_grants)
from .aura_attachment import auras_attached_to
from .color_changes import color_changes
from .named_counters import counters_on
from .control import control_changes, has_control_change
from .entry_choices import CHOSEN_COLOR_KEY, own_chosen_color
from .global_statics import (global_static_sources, removes_all_abilities,
                             stack_statics_applying_to)
from .land_animation import LAND_ANIMATIONS_REACHING
from .pt import BASE_PT_TIMESTAMP_KEY, CDA_POWER_KEY, CDA_TOUGHNESS_KEY
from .continuous import (
    Characteristics,
    ContinuousEffect,
    State,
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
from .keywords import (abilities_lost_at, ability_effects, derived_grant_stamps,
                       derived_removals)
from .landwalk import BOARD_NAMED_LANDWALKS
from .late_modules import LateModules
from .lord_buffs import QUALIFIER_FIELDS
# Where ``object_creature_types`` was first imported, so the package loads its
# modules in the order it did before the split (``engine/late_modules.py``).
from .printed_characteristics import (_seed_shape, printed_supertypes,
                                      seed_characteristics)
from .type_changes import gained_types
from .type_layer import TYPE_EFFECT_CHANNELS, collect_type_effects

if TYPE_CHECKING:
    from .models import Permanent

#: The grammar's vocabulary, which a top-level import here cannot reach: it
#: closes a cycle through the grammar package. Read through a binding made on
#: first use rather than a function-level import, because the collectors
#: below run on every characteristic read (``engine/late_modules.py``).
_late_grammar = LateModules(f"{__package__}.grammar")

#: ``engine.face_down``, for the "face-down" qualifier below: it registers a
#: special action as it loads, so a top-level import here would move it
#: earlier in the package's load order (``engine/late_modules.py``).
_late = LateModules(__package__)


# Channels whose values are recomputed from the board on every pass carry no
# timestamp of their own; they are all layer 7c, where order does not matter
# because addition commutes.
_DERIVED_TIMESTAMP = 0


# Derived layer-7c contributions from a lord buff whose filter names a state the
# buffed creature must be in. ``{qualifier: (power, toughness)}``, cleared and
# rebuilt by ``_recalculate_lord_buffs``; the qualifier itself is checked here,
# at read time.
QUALIFIED_BUFFS = "lord_buff_while"

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
    # CR 110.5 / 708.2: "Face-down creatures get +1/+1" (Ixidor) — asked as P/T
    # is read, so a creature turned face up loses the bonus at once.
    "face-down": lambda perm, observer: _late.face_down.is_face_down(perm),
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


def collect_pt_effects(perm: Permanent, oid: int) -> list[ContinuousEffect]:
    """Every layer-7 effect currently stored on *perm*."""
    only = scope_only(oid)
    effects: list[ContinuousEffect] = []
    meta = perm.metadata

    # 7a — a characteristic-defining ability's value (CR 604.3, CR 613.4a):
    # Nightmare's Swamps. Its own sublayer, applied before every 7b effect
    # whatever either's timestamp — which is the whole of why it has a channel
    # of its own (``pt.set_cda_pt``). It was written into 7b's slot, so a
    # Nightmare that met a Humility kept the count it had been given last.
    cda_power, cda_toughness = meta.get(CDA_POWER_KEY), meta.get(CDA_TOUGHNESS_KEY)
    if cda_power is not None or cda_toughness is not None:
        effects.append(set_pt(
            only,
            int(cda_power) if cda_power is not None else None,
            int(cda_toughness) if cda_toughness is not None else None,
            timestamp=perm.timestamp, from_cda=True,
            label="characteristic-defining",
        ))

    # 7b — set to a value, each slot at the timestamp it was written with
    # (CR 613.7b, ``pt.set_base_pt``). A slot with no stamp is a board built
    # by hand; it keeps the two constants every slot used to sit at, the
    # until-end-of-turn one later so that it still wins against its twin.
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
                timestamp=int(meta.get(f"{BASE_PT_TIMESTAMP_KEY}{suffix}", stamp)),
                label=f"set{suffix}",
            )
        )

    # 7b — "Lands you control are **2/2** creatures…" (Natural Emergence,
    # Living Lands, Kormus Bell.) Read off the record the board-wide layer-4
    # pass left on this land — every animator that reached it (CR 613.6: "the
    # same set of objects in each other applicable layer") — and stamped with
    # the animator's own timestamp (CR 613.7a), one effect per animator.
    #
    # The refresh used to *write* the size of the first animator in
    # battlefield order into the persistent slot above. Two things followed.
    # The slot sat at a constant later than every derived effect, so a land
    # under Natural Emergence stayed 2/2 beneath a Humility that arrived
    # afterwards; and of two animators the one that happened to be listed
    # first decided the size, where CR 613.7 gives it to the newer.
    for animator, animation in meta.get(LAND_ANIMATIONS_REACHING) or ():
        effects.append(set_pt(
            only, int(animation.power), int(animation.toughness),
            timestamp=animator.timestamp,
            label=f"land animation ({animator.card.name})",
        ))

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
    #
    # The mana value of the **permanent** (CR 202.3), which for a copy is the
    # copied object's: the mana cost is a copiable value (CR 707.2), so a Copy
    # Artifact of a Rod of Ruin is 4 and a token copy of one is 4, where the
    # copier's own printed cost says 2 and the token's says nothing at all.
    # All three readers below asked the printed card.
    for aura in animating_auras(perm):
        mana_value = int(perm.effective_card.cmc)
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
            value = int(perm.effective_card.cmc)
            effects.append(set_pt(
                only, value, value,
                # The moment the effect that made it a creature resolved
                # (CR 613.7b) — the stamp its type half already sorts by.
                timestamp=int(gained.get("timestamp") or _DERIVED_TIMESTAMP),
                label=f"gained-pt:{gained.get('source', 'effect')}",
            ))

    # The board-wide statics, each **with the timestamp of the object it is
    # on** (CR 613.7a) — a source on the battlefield, or a spell on the stack
    # (CR 113.6b), whose stamp is the moment it was put there (CR 613.7d).
    # Every one of these sat at the constant 0, so "All creatures … have base
    # power and toughness 1/1" lost to every other 7b effect on the board
    # whenever it had arrived: the two statics among themselves came out
    # right only where the order the battlefields are walked in happened to
    # be the order the sources entered, which across two seats it is not.
    board_statics = [
        (static, source.timestamp, source)
        for source, static in global_static_sources(
            meta.get("global_static_sources") or ()
        )
    ] + [
        (static, stamp, None)
        for static, stamp in stack_statics_applying_to(perm)
    ]
    for static, stamp, _source in board_statics:
        if static.pt_from_mana_value:
            value = int(perm.effective_card.cmc)
            effects.append(
                set_pt(only, value, value, timestamp=stamp, label=static.name)
            )
        # "…and have base power and toughness 1/1." (Humility.) CR 613.4b, the
        # same sublayer as the mana-value setting beside it and read off the
        # same static — so a +1/+1 counter or an anthem still applies at 7c and
        # the creature ends up 2/2. The printed pair rather than a computed
        # value is the only difference between the two branches.
        if static.sets_base_pt:
            power, toughness = static.sets_base_pt
            effects.append(
                set_pt(only, power, toughness, timestamp=stamp, label=static.name)
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
            # Stamped when the animation resolved (CR 613.7b) — a record
            # written by hand carries none and sorts first, as it always did.
            effects.append(grant_abilities(
                only, granted, timestamp=int(animation.get("granted_at", 0)),
                label=f"animated ({_key})",
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
    #
    # Each with its **source's** timestamp (CR 613.7a). They shared one stamp
    # of 0, which is no order at all against an effect that has one: a lord
    # that arrived after a Humility and one that was there before it gave the
    # same answer.
    for word, stamp in derived_grant_stamps(perm).items():
        effects.append(
            grant_abilities(only, [word], timestamp=stamp, label="lord grant")
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

    # Nothing here for "loses all abilities" (Humility, Titania's Song,
    # Humble) as an *effect*, and there used to be: a removal of the printed
    # keywords at timestamp 0. The seed this layer starts from is
    # ``effective_card``, which has already struck the printed text and every
    # line granted before the loss — so what is left to do here is the same
    # thing for the **words**: drop every grant and removal the loss is newer
    # than, below, once they are all gathered with their stamps.

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

    # CR 613.1f over CR 613.7: an effect that takes **all** abilities takes
    # every word granted before it applied and none granted after. The loss
    # was a removal of the *printed* keywords stamped 0, so it reached no
    # grant at all — Jump and then Humble left the creature flying, and so did
    # an Aura attached before a Humility arrived. (It also named the keywords
    # of the already-struck effective card, which are exactly the ones a
    # *later* line grant put back: Rapid Fire after Humility gave the rampage
    # trigger and not the word.)
    lost_at = abilities_lost_at(perm)
    if lost_at is not None:
        effects = [effect for effect in effects if effect.timestamp > lost_at]
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
    # **Contributed whether or not its abilities are gone.** This asked
    # ``removes_all_abilities`` and stood down under Humility, on the argument
    # that "a removal that has already happened is the same predicate layer 6
    # itself asks". Nothing has already happened: CR 613.1 applies the layers
    # in order each time, layer 5 before layer 6, so the ability that makes
    # the Golem its colour is still there when its colour is decided — the
    # same reading that keeps a stripped Blood Moon making Mountains
    # (``Permanent.card_before_layer_6``).
    own = own_chosen_color(perm, perm.card_before_layer_6)
    if own is not None:
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

    COLOR_WORDS = _late_grammar.vocabulary.COLOR_WORDS

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
    gained = subtypes - printed_tail_words
    # A CDA's own types (Mistform Ultimus) are not gains while they all stand;
    # once a type-setting effect replaced them (CR 205.1a), what it set is.
    defined = _seed_shape(perm, perm.effective_card)[1] - printed_tail_words
    if defined and defined <= subtypes:
        gained -= defined
    gained_subtypes = sorted(gained)
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


def _without_type_effects(perm: Permanent) -> bool:
    """Whether no layer-4 effect can apply to *perm* (:data:`TYPE_EFFECT_CHANNELS`)."""
    return not any(map(perm.metadata.get, TYPE_EFFECT_CHANNELS))


def computed_types(perm: Permanent) -> tuple[set[str], set[str]]:
    """``(card_types, subtypes)`` after layer 4."""
    if _without_type_effects(perm):
        card_types, subtypes = _seed_shape(perm, perm.effective_card)
        answer = (set(card_types), set(subtypes))
        if fast_paths.CHECKING:
            full = _computed_types_in_full(perm)
            fast_paths.checked(
                "computed_types", answer == full,
                lambda: f"{perm.card.name!r}: {answer} against {full}",
            )
        return answer
    return _computed_types_in_full(perm)


def _computed_types_in_full(perm: Permanent) -> tuple[set[str], set[str]]:
    """:func:`computed_types`, through the layer system."""
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

    Answered from the printed line where no layer-4 effect can apply, for
    :func:`computed_types`' reason (:data:`TYPE_EFFECT_CHANNELS`).
    """
    if _without_type_effects(perm):
        answer = set(printed_supertypes(perm.effective_card.type_line))
        if fast_paths.CHECKING:
            full = _computed_supertypes_in_full(perm)
            fast_paths.checked(
                "computed_supertypes", answer == full,
                lambda: f"{perm.card.name!r}: {answer} against {full}",
            )
        return answer
    return _computed_supertypes_in_full(perm)


def _computed_supertypes_in_full(perm: Permanent) -> set[str]:
    """:func:`computed_supertypes`, through the layer system."""
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
    "collect_control_effects", "collect_pt_effects", "computed_controller",
    "computed_pt", "computed_supertypes",
]
