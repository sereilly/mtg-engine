"""Damage-prevention registry (CR 615).

A prevention effect is a shield sitting on a player or a permanent that removes
points from a damage event before the damage is dealt (CR 615.1). Like
replacement effects (CR 614, ``engine/replacements.py``) each shield is a
registered interceptor that self-selects from game state, so supporting a new
kind of shield means registering a function — never editing a cascade.

**The state is generic too.** This registry's shields once read a
``PlayerState`` field named after the card that granted them
(``forcefield_capped_sources``, ``reverse_damage_charges``,
``color_prevention_shields``), so "register a function" was only half true: the
other half was a new field on a model the web payload, the AI simulator and
forty tests read. A shield is now a :class:`~engine.shields.Shield` in one
collection on its recipient — what it answers to, how much it absorbs, how many
uses remain, how long it lasts — and the old names survive as views over that
collection. Adding a shield is one registration plus a ``Shield``; see
``engine/shields.py``.

Preventers run in ascending ``order`` over one event payload::

    {"recipient": PlayerState | Permanent, "amount": int, "source": Any | None,
     "combat": bool}

``combat`` marks the event as combat damage, which is the only thing a
"prevent all combat damage" shield may touch; every other shield ignores it.

Each returns the number of points it removes, or ``None`` to pass. The event
stops as soon as nothing is left to prevent, so a shield later in the order is
never consumed by damage an earlier one already absorbed — and a 0-damage event
consumes no shield at all (CR 614.7a).

Recipients are deliberately not split by type: ``Permanent`` and ``PlayerState``
both carry the shield collection, so the numeric shield of CR 615.7 is one
interceptor covering creatures and players alike. A shield whose additional
effect needs a player (Reverse Damage's life gain) guards on the recipient type
itself.

**Ordering (CR 616.1).** When several prevention and/or replacement effects
could apply to one event, the rules give the *affected* player the choice of
which to apply, and re-ask after each one (616.1f). That process lives in
``engine/effect_ordering.py`` and this registry runs through it: every shield
carries an ``applies`` predicate so the contenders can be counted before any of
them runs, and the orders below are the *default* choice a non-interactive seat
makes rather than a fixed cascade. Any single order is a legal set of choices;
only the aggregate outcome can differ, and only when one recipient holds two
applicable shields at once — a Circle of Protection and a prevention pool, say,
which this card pool reaches easily.

The shields are only *half* of a damage event's contenders: CR 616.1 does not
separate prevention from replacement, so the orders below share one space with
the damage entries in ``engine/replacements.py`` and the union is what actually
runs. ``engine/damage_events.py`` is where the two are put together, and it
raises at import if the union ever collides. There is deliberately no
shields-only entry point here — a caller holding half a contention set is the
shape this pipeline exists to remove, and ``shield_candidates`` hands the halves
over rather than running them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .damage_source_colors import damage_source_colors
from .effect_ordering import Candidate
from .models import PlayerState
from .named_counters import add_counters, counters_on, remove_counters
from .pt import remove_plus1_counters
from .shields import (END_OF_TURN as SHIELD_END_OF_TURN, PREVENT_ALL_BUT,
                      PREVENT_AND_DAMAGE_SOURCE, PREVENT_AND_GAIN_LIFE,
                      PREVENT_HALF, PREVENT_FROM_COLOR,
                      PREVENT_FROM_SUBJECT, PREVENT_FROM_TARGETING_SOURCE,
                      PREVENT_NEXT_N, PREVENT_WHOLE, PREVENT_AND_EXILE,
                      PREVENT_TEAM, Shield, drop_spent, shields_on)

# Order bands. Blanket combat shields run first: they are flags rather than
# charges, so applying one costs the recipient nothing, and letting it go first
# keeps a consumable shield from being spent on damage that was never going to
# be dealt. Caps run before whole-event shields so a capped event can still be
# shielded outright; the numeric pool runs last so an all-or-nothing shield is
# spent before points are drawn from a pool that could cover later damage.
COMBAT_BLANKET = 10  # "Prevent all combat damage that would be dealt this turn"
# The same blanket narrowed to a printed noun phrase (Pack Leader). Beside the
# unscoped one and before every consumable shield, for the same reason: it has
# no charges, so applying it costs its recipient nothing.
COMBAT_BLANKET_SCOPED = 11
# The same blanket with a **source** description cut out of it (Undergrowth with
# its additional cost paid). Beside the two above and before every consumable,
# for their reason: it has no charges, so applying it costs its recipient
# nothing.
COMBAT_BLANKET_EXCEPT = 12
COMBAT_SHIELD = 20  # "…dealt to and dealt by that creature this turn"
# "Prevent all damage that would be dealt to this creature by artifact
# sources." (Argothian Treefolk.) A permanent's own blanket shield against a
# class of source — no charges, so applying it costs its recipient nothing, and
# it belongs with the other blankets rather than with the consumables below.
SOURCE_TYPE_BLANKET = 25
# "Prevent all damage that would be dealt to you." (Glacial Chasm.) The same
# blanket with the *player* as recipient and no source narrowing at all — the
# unnarrowed member of the family above, so it sits beside it and ahead of
# every consumable, for the same reason: it has no charges, so applying it
# costs its controller nothing and spends no shield that could cover later
# damage.
CONTROLLER_BLANKET = 28
# "Prevent all damage that would be dealt by instant and sorcery spells."
# (Energy Storm.) A blanket over the whole table with no recipient at all —
# whoever the damage was headed for. Beside the others here for the reason they
# are here: it has no charges, so applying it costs nobody anything and spends
# no shield that could cover later damage.
SPELL_CLASS_BLANKET = 29
# "Prevent all damage that would be dealt to you this turn by attacking
# creatures without flying." (Al-abara's Carpet.) A blanket a *player* was
# handed rather than one a permanent prints, but a blanket all the same — no
# charges, so it sits with the others here and ahead of every consumable.
SUBJECT_BLANKET = 26
# "If a spell or ability that targets that creature would cause a source to deal
# damage to that creature this turn, prevent that damage." (Silhouette.) A third
# blanket, beside the other two and for the same reason: no charges, so applying
# it costs its recipient nothing.
TARGETING_BLANKET = 27
SOURCE_CAP = 100  # Forcefield against a chosen attacker
# "…prevent half that damage, rounded down" (Dark Sphere) against a chosen
# source. Beside Forcefield's cap and for the same reason the note above gives:
# it is a *partial* prevention, so it runs before the whole-event shields — a
# halved event can still be shielded outright, and a whole-event shield spent
# first would leave this one halving nothing.
SOURCE_HALF = 150
GENERIC_HALF = 160  # the same shield with no source recorded
GENERIC_CAP = 200  # Forcefield with no chosen attacker
SOURCE_SHIELD = 300  # Reverse Damage against a chosen source
# "…prevent that damage. Exile cards from the top of your library equal to the
# damage prevented this way." (Bone Mask.) CR 615.5's other rider, beside
# Reverse Damage's and just behind it: both absorb the whole instance, and the
# one that *pays* its controller is the shield a seat spends first. CR 616.1e
# permits any order; this is the default a non-interactive seat takes.
SOURCE_EXILE_SHIELD = 305
# "…prevent that damage. If damage from a black source is prevented this way,
# you gain that much life." (Shadowbane.) The third CR 615.5 rider, beside the
# other two: all three absorb the whole instance from one chosen source and
# differ only in what they do afterwards.
SOURCE_TEAM_SHIELD = 307
# "…prevent that damage. If damage from a red source is prevented this way, ~
# deals that much damage to the source's controller." (Honorable Passage.) The
# fourth CR 615.5 rider, beside the other three for their reason — one chosen
# source, the whole instance absorbed — and behind them because it is the only
# rider that *hurts somebody*. CR 616.1e gives the choice to the affected
# player, and a shield they can spend for a gain is one they would spend before
# a shield they can spend for an attack on a third party.
SOURCE_REFLECT_SHIELD = 308
# "…prevent that damage", with nothing after it (Pentagram of the Ages). The
# same absorption as Reverse Damage's shield against the same chosen source, so
# it sits beside it — behind, because Reverse Damage's rider gains its
# controller life and a shield that also pays is the one a player spends first.
# CR 616.1e permits any order; this is the default a non-interactive seat takes.
SOURCE_WHOLE = 310
GENERIC_SHIELD = 400  # Reverse Damage with no chosen source
GENERIC_EXILE_SHIELD = 405  # Bone Mask with no chosen source
GENERIC_TEAM_SHIELD = 407  # Shadowbane with no chosen source
GENERIC_REFLECT_SHIELD = 408  # Honorable Passage with no chosen source
GENERIC_WHOLE = 410  # the same rider-less shield with no source recorded
COLOR_SHIELD = 500  # Circle of Protection
POOL = 600  # "Prevent the next N damage" (CR 615.7)
# A permanent's own static prevention, which is never used up by the event —
# only by what it *charges*. Nine Lives prevents the whole instance and puts an
# incarnation counter on itself, and nine of those exile it into "you lose the
# game", so applying it is the most expensive way to take zero damage on this
# list. Last, therefore: every consumable above is already paid for, and a
# shield that covers the event outright leaves this one unasked, so the counter
# is only ever spent on damage nothing else stopped. CR 616.1e permits any
# order; this is the default a non-interactive seat takes.
STATIC_WHOLE_EVENT = 650
#: A permanent's own per-point counter shield (Rock Hydra's automatic half).
#: After the whole-event static: it spends a resource per point, so anything
#: that prevents outright should be offered first.
PER_POINT_COUNTER_SHIELD = 660


@dataclass
class PreventionOutcome:
    """Points this shield removes from the event. 0 means the shield looked but
    did not apply, which is indistinguishable from passing."""

    prevented: int = 0


Preventer = Callable[[Any, dict], Optional[PreventionOutcome]]
Applicability = Callable[[Any, dict], bool]

PREVENTION_EFFECTS: list[Candidate] = []


def prevention_effect(order: int, *, applies: Applicability) -> Callable[[Preventer], Preventer]:
    """Register a prevention interceptor at *order* (ascending).

    ``applies`` is the shield's guard — "would this shield apply to this
    event?" — and it is **required**, because CR 616.1 has to count the effects
    in contention before running any of them. It must be pure: a predicate that
    consumed a charge would spend shields the player never chose.

    A duplicate order raises at import time, matching ``@parse_rule``: with the
    default choice being the lowest order, a collision is a real ambiguity about
    which shield is consumed first, so it should surface at startup rather than
    as a rare misplay.
    """

    def decorator(fn: Preventer) -> Preventer:
        for existing in PREVENTION_EFFECTS:
            if existing.order == order:
                raise ValueError(
                    f"prevention_effect order {order} already used by "
                    f"{existing.key}; pick a free slot"
                )
        PREVENTION_EFFECTS.append(
            Candidate(key=fn.__name__, order=order, applies=applies, apply=fn,
                      label=(fn.__doc__ or fn.__name__).split(":")[0].strip())
        )
        PREVENTION_EFFECTS.sort(key=lambda candidate: candidate.order)
        return fn

    return decorator


def spent(game, event: dict) -> bool:
    """Nothing left to prevent, so nothing more can apply (CR 615.7's "any
    remaining damage is dealt normally")."""
    return event["amount"] <= 0


def _consume(game, event: dict, preventer: Preventer) -> None:
    """Apply one shield and keep ``event["amount"]`` in step, so the next round
    of CR 616.1f asks the remaining shields about what is actually left."""
    outcome = preventer(game, event)
    if outcome is not None and outcome.prevented > 0:
        event["amount"] = max(0, event["amount"] - outcome.prevented)


def shield_candidates() -> list[Candidate]:
    """Every shield as a CR 616.1 candidate, with the amount bookkeeping already
    wired into ``apply``.

    Exposed rather than kept private because a damage event's contenders are the
    shields *and* the replacements, and whoever unions the two must not have to
    re-implement what applying a shield does to the event.
    """
    return [
        Candidate(
            key=c.key, order=c.order, applies=c.applies, label=c.label,
            apply=lambda g, e, fn=c.apply: _consume(g, e, fn),
            # Every entry in this file is CR 615 prevention by construction,
            # which is what "can't be prevented" (Whippoorwill) switches off.
            prevents_or_redirects=True,
        )
        for c in PREVENTION_EFFECTS
    ]


# ---------------------------------------------------------------------------
# Source matching
# ---------------------------------------------------------------------------

# ``source_colors`` used to live here. It moved to
# ``engine/damage_source_colors.py`` when a *second* question grew beside it:
# Ghostly Flame rewrites what colour a source is **as a source of damage**
# without changing the object's colour, so the answer is no longer read off the
# object at all — and it is asked by protection's damage prevention
# (CR 702.16e) as well as by the shields here, which is two files.
# ``damage_source_colors`` (imported at the top of this module) is what every
# site below now asks.


def source_has_type(game, source, card_type: str) -> bool:
    """Whether a damage source is of *card_type* ("artifact", "creature", …).

    A source is a Permanent or, for a spell, the CardDefinition itself
    (CR 109.5), so both shapes are read. A permanent answers through the layer
    system — an animated artifact land *is* an artifact source, and reading its
    printed line would say otherwise — and a card in no zone has only what is
    printed on it.
    """
    if source is None:
        return False
    if hasattr(source, "has_type"):
        return bool(source.has_type(card_type))
    card = getattr(source, "card", source)
    return card_type in (getattr(card, "type_line", "") or "").lower()


#: Which end of the event a combat shield covers. "Prevent all combat damage
#: that would be dealt **to and dealt by** that creature this turn" (Ebony
#: Horse, Maze of Ith) covers both; the Legends cards need the halves, because
#: "…that would be dealt **by** target creature this turn" (Horn of Deafening,
#: Lady Evangela) leaves the creature perfectly able to *take* combat damage,
#: and folding it into the two-way shield would make those creatures unkillable
#: in combat.
#:
#: Ebony Horse's used to be a bare boolean on its own metadata key, written by a
#: name-keyed hook. Maze of Ith prints the same sentence, which is what that
#: hook's entry bar forbids — so the sentence became a grammar production and
#: the boolean became the two-way value of this one record.
COMBAT_SHIELD_BY = "by"
COMBAT_SHIELD_TO = "to"
COMBAT_SHIELD_BOTH = "to_and_by"

#: The directional turn-long marker, swept by ``_EOT_METADATA_KEYS``.
#:
#: The record is a list of ``[direction, combat_only]`` pairs rather than one
#: direction word, because **how wide the shield is, is payload**: "Prevent all
#: *combat* damage that would be dealt by target creature this turn" (Horn of
#: Deafening, Lady Evangela) and "Prevent all damage that would be dealt this
#: turn by target creature you control" (Kry Shield) are the same sentence one
#: word apart. A second metadata key per width would be a second mechanism for
#: a narrowing, and the wide one would then have to be remembered in every place
#: the narrow one already is.
_COMBAT_SHIELD_DIRECTION_KEY = "prevent_combat_damage_direction_until_eot"


def add_directional_shield(
    perm, direction: str, *, combat_only: bool, lifetime: str = SHIELD_END_OF_TURN,
) -> None:
    """Shield *perm* in *direction* until *lifetime* ends (CR 615.1).

    *combat_only* is the printed word "combat": True covers combat damage
    alone, False covers damage of every kind. Duplicate records are folded, so
    two resolutions of the same effect leave one entry.

    *lifetime* is the printed window, and it is a third element of the entry for
    the reason ``combat_only`` is the second: **how long the shield lasts is
    payload**. "…dealt to and dealt by that creature **this turn**" (Ebony
    Horse, Maze of Ith) and "…**this combat**" (Winter's Chill) are the same
    sentence four characters apart, and a card whose shield outlived its combat
    would go on preventing through a second combat phase the card never
    mentions. It takes the same two words ``engine/shields.py`` gives every
    other shield, so the two sweeps that already run — end of combat, and
    cleanup — are the two that end these.
    """
    record = [list(entry) for entry in (perm.metadata.get(_COMBAT_SHIELD_DIRECTION_KEY) or ())]
    entry = [str(direction), bool(combat_only), str(lifetime)]
    if entry not in record:
        record.append(entry)
    perm.metadata[_COMBAT_SHIELD_DIRECTION_KEY] = record


def clear_directional_shields(perm, lifetime: str) -> None:
    """Drop *perm*'s directional shields whose window is *lifetime*.

    The twin of ``shields.clear_shields`` for the marker form, called from the
    same end-of-combat sweep — so "this combat" is implemented by *having a
    sweep* rather than by the phrase being read and then forgotten. The
    end-of-turn entries are left to ``_EOT_METADATA_KEYS``, which has always
    cleared the whole key at cleanup.
    """
    metadata = getattr(perm, "metadata", None)
    if not metadata:
        return
    kept = [
        list(entry) for entry in (metadata.get(_COMBAT_SHIELD_DIRECTION_KEY) or ())
        if _shield_lifetime(entry) != lifetime
    ]
    if kept:
        metadata[_COMBAT_SHIELD_DIRECTION_KEY] = kept
    else:
        metadata.pop(_COMBAT_SHIELD_DIRECTION_KEY, None)


def _shield_lifetime(entry) -> str:
    """One directional record's window. Entries written before the window was
    payload carry two elements and mean the rest of the turn."""
    return str(entry[2]) if len(entry) > 2 else SHIELD_END_OF_TURN

#: The Aura form (Gaseous Form, Demonic Torment). Not a marker at all - it is
#: read off the attached Aura's own text at the moment damage would be dealt,
#: so the shield ends when the Aura leaves with nothing having to clear it.
#: The same shape ``_source_type_shielded_by`` uses one screen down.
_ATTACHED_COMBAT_SHIELD_RE = re.compile(
    r"^prevent all combat damage that would be dealt "
    r"(?P<direction>to and dealt by|to|by) "
    r"(?:enchanted|equipped) (?:artifact )?creature$"
)


def attached_combat_shield_direction(line: str) -> str | None:
    """Which end of a combat damage event one printed Aura line shields, or None.

    One matcher, asked by the interceptor below and by ``engine/auras.py``'s
    support gate, so what is claimed and what is carried out are one rule.
    """
    match = _ATTACHED_COMBAT_SHIELD_RE.match(
        " ".join(line.strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    printed = match.group("direction")
    return COMBAT_SHIELD_BOTH if printed == "to and dealt by" else printed


def _attached_combat_shield(perm) -> str | None:
    """The direction an Aura attached to *perm* shields it in, if any."""
    from .auras import auras_attached_to

    if not hasattr(perm, "metadata"):
        return None
    for aura in auras_attached_to(perm):
        for line in (aura.effective_card.oracle_text or "").splitlines():
            direction = attached_combat_shield_direction(line)
            if direction is not None:
                return direction
    return None


def _shield_directions(perm, *, combat: bool) -> frozenset[str]:
    """Every direction *perm* is currently shielded in against an event of this
    width, from any of the three places a directional shield is recorded.

    *combat* is the event's own ``combat`` flag. The Aura form is printed
    "combat damage", so it answers nothing at all for a burn spell; the marker
    records its width per entry.

    Accepts None and non-permanent damage sources (a spell's
    ``CardDefinition``), which carry no shield at all.
    """
    metadata = getattr(perm, "metadata", None)
    if not metadata:
        return frozenset()
    directions: set[str] = set()
    for entry in metadata.get(_COMBAT_SHIELD_DIRECTION_KEY) or ():
        direction, combat_only = entry[0], entry[1]
        if combat_only and not combat:
            # "Prevent all **combat** damage …": a shield that ignored the word
            # would stop the creature's ping ability as well, which is a
            # strictly larger effect than the card prints.
            continue
        directions.add(str(direction))
    if combat:
        attached = _attached_combat_shield(perm)
        if attached is not None:
            directions.add(attached)
    return frozenset(directions)


def shields_damage(perm, *, dealt_to: bool, combat: bool) -> bool:
    """Whether *perm*'s shields cover an event it is on one end of.

    *dealt_to* says which end: True when *perm* is the recipient, False when it
    is the source. The two-way marker answers both; a one-way one answers only
    its own end, which is the whole point of carrying the direction.
    """
    directions = _shield_directions(perm, combat=combat)
    wanted = COMBAT_SHIELD_TO if dealt_to else COMBAT_SHIELD_BY
    return COMBAT_SHIELD_BOTH in directions or wanted in directions



# ---------------------------------------------------------------------------
# Reading the collection (CR 616.1's pure half)
# ---------------------------------------------------------------------------
#
# "Does this shield apply?" is separated from "apply it", because 616.1 has to
# know how many effects are in contention *before* any of them runs. The guard
# each shield used to open with *moved* here rather than being copied, so the
# shield body starts after the decision and the two cannot drift. Predicates are
# pure: none of them spends a charge, since a shield that is asked about may
# then not be chosen — ``Shield.would_prevent`` computes, ``Shield.spend``
# mutates, and only the second is reachable from an ``apply``.


def _source_matches(game, shield: Shield, source) -> bool:
    """Whether *shield* answers damage from *source*.

    Two independent narrowings, both rechecked at damage time rather than
    locked in when the shield was armed (CR 615.9): the chosen source of
    CR 615.8, matched the way every other chosen-source effect in the engine
    matches one, and the source *property* a Circle of Protection names. A
    shield recording neither answers to any source.
    """
    if shield.source is not None:
        if game._match_chosen_damage_source([shield.source], source) is None:
            return False
    if shield.colors and not set(shield.colors) & set(
        damage_source_colors(game, source)
    ):
        return False
    if shield.source_type is not None and not source_has_type(
        game, source, shield.source_type
    ):
        return False
    if shield.source_filter is not None and not _source_in_subject(game, shield, source):
        return False
    return True


def _source_in_subject(game, shield: Shield, source) -> bool:
    """Whether *source* is one of the objects *shield*'s noun phrase names.

    Asked through ``subject_filters.subject_matches`` — the one answer every
    reader of a printed noun phrase uses — rather than field by field here, so
    a phrase the matcher cannot test is refused where the line is *compiled*
    instead of being quietly ignored at damage time.

    **A source that is not a permanent gets the one question a card can answer.**
    A spell reaches the damage paths as its printed ``CardDefinition``
    (CR 109.5), which has no battlefield, no controller and no layers — so every
    key in the vocabulary is unanswerable about it except ``named``, which is a
    characteristic of the card itself. "…would be dealt to this creature **by
    Torrent of Lava** this turn" names a spell and nothing else, and answering
    it "no" because the source is not a permanent would have made the shield
    Torrent of Lava grants prevent nothing at all. A phrase describing anything
    wider still declines, which is the safe direction: a shield is smaller than
    the card prints, never larger.
    """
    from .search_filters import name_key
    from .subject_filters import subject_matches

    described = dict(shield.source_filter or {})
    if source is None:
        return False
    if not hasattr(source, "metadata"):
        if set(described) != {"named"}:
            return False
        return name_key(getattr(source, "name", "") or "") == name_key(
            str(described["named"])
        )
    return subject_matches(
        game, source, described, observer=shield.filter_seat
    )


def _object_targets_recipient(game, recipient) -> bool:
    """Whether the spell or ability now resolving targets *recipient*.

    ``Game.resolving_targets`` is the seam ``_execute_oracle_instruction``
    pushes around every instruction, and it is the only place the answer lives:
    a spell reaches the damage paths as its printed ``CardDefinition``, which
    records nothing about what was chosen, and the stack object is popped before
    its instructions run.

    Spells **and** abilities, unlike ``_spell_targets_recipient`` beside it:
    Bronze Horse's static says "spells that target it", and this reads a card
    that says "a spell or ability", which is the same seam asked without the
    narrowing rather than a second mechanism. Combat damage is caused by no
    resolving object at all, so it is outside this by construction.
    """
    permanent_id = getattr(recipient, "permanent_id", None)
    if permanent_id is None:
        return False
    chosen = getattr(game, "resolving_targets", None) or ()
    return bool(chosen) and permanent_id in chosen[-1]


def _class_shields(game, recipient) -> list[Shield]:
    """The shields that watch *recipient* by a printed **noun phrase** rather
    than by hanging off it, oldest first.

    A shield normally lives on the recipient it protects, which is what makes it
    findable at all. "…would deal damage to you **and/or creatures you
    control**" (Shadowbane) names a phrase instead, and a phrase is not an
    object: the creatures it covers include ones that have not entered the
    battlefield yet, so there is nothing to hang it on and nothing to update
    when one arrives. So it lives on the seat it also protects, in the same
    collection, and is matched by asking the phrase about each damaged
    permanent.

    The exact twin of ``damage_redirects.class_redirects``, which the redirect
    side has had since Blood of the Martyr — and it keeps the sweeps and the
    lifetimes as they were, because the cleanup step already clears every
    player's shields.

    Only a permanent can be watched this way. The player half of the phrase is
    the seat the shield already hangs off, so asking a ``PlayerState`` here
    would find the same shield twice.
    """
    if not hasattr(recipient, "metadata"):
        return []
    from .subject_filters import subject_matches

    found: list[Shield] = []
    for player in game.players:
        for shield in shields_on(player):
            if shield.recipients is None:
                continue
            if subject_matches(
                game, recipient, dict(shield.recipients),
                observer=shield.filter_seat,
            ):
                found.append(shield)
    return found


def _live(game, event: dict, kind: str, *, chosen: bool | None = None):
    """Shields of *kind* on the event's recipient that could modify this event.

    *chosen* selects one half of the order space: True for shields naming a
    source, False for the "any source" fallback an AI or headless activation
    arms. They are separate registrations because they take separate default
    orders, and CR 616.1e's default is rules-visible.
    """
    recipient = event["recipient"]
    amount = event["amount"]
    # The recipient's own collection, plus — when the recipient is a permanent
    # — the class-scoped shields sitting on a *seat* whose printed phrase names
    # it. A team shield covers its holder as well as the phrase ("**you** and/or
    # creatures you control"), so it is not excluded from the holder's own list;
    # and a permanent is never in that list, so nothing is counted twice.
    for shield in list(shields_on(recipient)) + _class_shields(game, recipient):
        if shield.kind != kind or shield.spent:
            continue
        if chosen is not None and (shield.source is not None) != chosen:
            continue
        if not _source_matches(game, shield, event.get("source")):
            continue
        if shield.targets_recipient and not _object_targets_recipient(game, recipient):
            # Checked here rather than in `_source_matches`, and the difference
            # is real: this is not a property of the source but a relation
            # between the *resolving object* and the recipient, and only the
            # event knows who the recipient is.
            continue
        if shield.would_prevent(amount) <= 0:
            continue
        yield shield


def _arms(kind: str, *, chosen: bool | None = None, player_only: bool = False) -> Applicability:
    """The applicability predicate for a shield of *kind*: is one armed that
    would remove at least a point from this event?

    "Would remove a point" rather than merely "is armed" is the deliberate
    reading, and it is the one place this differs from Aladdin's Lamp — see
    ``_forcefield_chosen_attacker``, which is the shield it could bite.
    """

    def applies(game, event: dict) -> bool:
        if player_only and not isinstance(event["recipient"], PlayerState):
            return False
        return next(_live(game, event, kind, chosen=chosen), None) is not None

    return applies


def _spend(game, event: dict, kind: str, *, chosen: bool | None = None, rider=None):
    """Apply the recipient's shields of *kind* to this event.

    Draining every matching shield rather than one is what keeps CR 615.7's
    "such effects count only the amount of damage" true when a recipient holds
    two numeric pools: the pair behaves as the single total the old integer
    field held. A whole-instance shield takes the event to 0 on its first
    application and the loop stops there, so exactly one is consumed.

    *rider* is CR 615.5's "additional effect, which may refer to the amount of
    damage that was prevented" — run after the prevention, with the shields that
    did it, never before.
    """
    remaining = event["amount"]
    prevented = 0
    used: list[Shield] = []
    for shield in list(_live(game, event, kind, chosen=chosen)):
        take = shield.would_prevent(remaining)
        if take <= 0:
            continue
        shield.spend(take)
        used.append(shield)
        prevented += take
        remaining -= take
        if remaining <= 0:
            break
    drop_spent(event["recipient"])
    if rider is not None and prevented > 0:
        rider(game, event, used, prevented)
    return PreventionOutcome(prevented=prevented)


def _applies_all_combat(game, event: dict) -> bool:
    return bool(event.get("combat")) and game.combat_damage_prevented_until_eot


def _applies_scoped_combat(game, event: dict) -> bool:
    """Whether an armed "…to <noun phrase>" prevention covers this event.

    The noun phrase is matched **now**, not when the effect resolved (CR 611.2c
    fixes a set only where the effect says so, and "Dogs you control" does not):
    a Dog that entered after Pack Leader attacked is still a Dog its controller
    controls when the damage would be dealt.
    """
    if not event.get("combat"):
        return False
    recipient = event.get("recipient")
    if recipient is None or not hasattr(recipient, "card"):
        # A player is not a "Dog you control". Only permanents are scoped.
        return False
    from .subject_filters import subject_matches

    for entry in getattr(game, "combat_damage_prevented_for", ()) or ():
        seat = entry.get("seat")
        if subject_matches(game, recipient, entry.get("filter") or {}, observer=seat):
            return True
    return False


def _applies_all_combat_except(game, event: dict) -> bool:
    """Undergrowth with its cost paid: every combat damage event **but** the
    ones whose source the printed noun phrase names.

    The source is re-matched at the moment damage would be dealt rather than
    captured when the spell resolved, exactly as ``_applies_scoped_combat``
    re-matches its recipients: a creature that turned red since, or entered
    since, is one the sentence exempts.

    A source that is not a permanent — a spell, an ability — cannot be matched
    and is therefore not exempt, which is the right way round: this is a
    *combat* damage shield, and combat damage is only ever dealt by a permanent.
    """
    if not event.get("combat"):
        return False
    records = getattr(game, "combat_damage_prevented_except_from", ()) or ()
    if not records:
        return False
    from .subject_filters import subject_matches
    from .models import Permanent

    source = event.get("source")
    for entry in records:
        if isinstance(source, Permanent) and subject_matches(
            game, source, entry.get("filter") or {}, observer=entry.get("seat"),
        ):
            continue  # the sentence lets this source's damage through
        return True
    return False


def _applies_combat_to_and_by(game, event: dict) -> bool:
    """Whether either end of this damage event is shielded.

    Each end is asked with the direction it is on, so a "dealt **by**" shield
    stops the shielded creature's own damage without also stopping damage dealt
    *to* it — which is the difference between Gaseous Form and Demonic Torment,
    printed one word apart. The event's own width is passed down rather than
    checked here, because a shield that names no "combat" covers a ping as well
    (Kry Shield) and one that names it covers only combat.
    """
    combat = bool(event.get("combat"))
    return shields_damage(event["recipient"], dealt_to=True, combat=combat) or shields_damage(
        event.get("source"), dealt_to=False, combat=combat
    )


# ---------------------------------------------------------------------------
# Shields
# ---------------------------------------------------------------------------
#
# The first two are turn-wide flags rather than shields a recipient holds, which
# is why they read a game flag and a permanent's marker instead of the
# collection: nothing is consumed, so there is no charge, no lifetime and no
# remaining-uses bookkeeping for a Shield to carry. The directional one also has
# to be readable off the damage's *source* ("dealt to and dealt by"), which a
# recipient-keyed collection cannot express.

@prevention_effect(COMBAT_BLANKET, applies=_applies_all_combat)
def _prevent_all_combat_damage(game, event: dict) -> PreventionOutcome | None:
    """Fog / Holy Day: "Prevent all combat damage that would be dealt this
    turn." A turn-wide flag rather than a shield, so it is never used up — and
    it applies only to combat damage, leaving spell and ability damage alone."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(COMBAT_BLANKET_SCOPED, applies=_applies_scoped_combat)
def _prevent_scoped_combat_damage(game, event: dict) -> PreventionOutcome | None:
    """Pack Leader: "Prevent all combat damage that would be dealt this turn to
    Dogs you control." A turn-wide record like the blanket above rather than a
    shield each Dog holds, so it is never used up and it covers Dogs that were
    not on the battlefield when it resolved."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(COMBAT_BLANKET_EXCEPT, applies=_applies_all_combat_except)
def _prevent_all_combat_damage_except_from(game, event: dict) -> PreventionOutcome | None:
    """Undergrowth, cost paid: "Prevent all combat damage that would be dealt
    this turn… this effect doesn't affect combat damage that would be dealt by
    red creatures."

    The blanket above with a hole in it. A turn-wide record rather than a shield
    for that one's reason — nothing is used up — and the hole is described by
    the source, so it covers a creature that becomes red after this resolves and
    exempts one that stops being red."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(COMBAT_SHIELD, applies=_applies_combat_to_and_by)
def _prevent_combat_damage_to_and_by(game, event: dict) -> PreventionOutcome | None:
    """Ebony Horse, Maze of Ith: "Prevent all combat damage that would be dealt
    to and dealt by that creature this turn." Both directions are one check here
    — the shielded creature may be either end of the event."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(SOURCE_CAP, applies=_arms(PREVENT_ALL_BUT, chosen=True))
def _forcefield_chosen_attacker(game, event: dict) -> PreventionOutcome | None:
    """Forcefield: "The next time an unblocked creature of your choice would
    deal combat damage to you this turn, prevent all but 1 of that damage."
    The chosen attacker is consumed by the damage it caps.

    A shield that would prevent nothing does not apply, so a chosen attacker
    dealing exactly 1 leaves it armed. That is the one place this pool's shields
    could have taken Aladdin's Lamp's shape instead — a charge spent even when
    it does nothing (CR 614.1) — and CR 615.8 arguably says they should. It is
    left as it was rather than changed under cover of a refactor; see
    ROADMAP.md's phase 5 entry."""
    return _spend(game, event, PREVENT_ALL_BUT, chosen=True)


@prevention_effect(GENERIC_CAP, applies=_arms(PREVENT_ALL_BUT, chosen=False))
def _forcefield_generic(game, event: dict) -> PreventionOutcome | None:
    """Forcefield activated without recording a chosen attacker (AI / headless):
    the next damage event from any source is capped to 1."""
    return _spend(game, event, PREVENT_ALL_BUT, chosen=False)


def _gain_prevented_life(game, event: dict, used: list[Shield], prevented: int) -> None:
    # CR 615.5: the prevention happens first, then the rest of the effect —
    # here a life gain referring to the amount prevented.
    recipient = event["recipient"]
    game.log.append(f"Reverse Damage prevented {prevented} damage to {recipient.name}")
    game._gain_life(recipient, prevented, source_name="Reverse Damage")


@prevention_effect(SOURCE_HALF, applies=_arms(PREVENT_HALF, chosen=True, player_only=True))
def _half_prevention_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Dark Sphere: "The next time a source of your choice would deal damage to
    you this turn, prevent half that damage, rounded down."

    Half of *this* event, computed by the shield when the event exists — see
    ``Shield.would_prevent``. A 1-damage event therefore prevents nothing and
    leaves the shield armed, the same reading ``_forcefield_chosen_attacker``
    takes of the same situation and for the same reason.
    """
    return _spend(game, event, PREVENT_HALF, chosen=True)


@prevention_effect(GENERIC_HALF, applies=_arms(PREVENT_HALF, chosen=False, player_only=True))
def _half_prevention_generic(game, event: dict) -> PreventionOutcome | None:
    """Dark Sphere sacrificed without recording a chosen source (AI / headless):
    the next damage event from any source is halved."""
    return _spend(game, event, PREVENT_HALF, chosen=False)


@prevention_effect(
    SOURCE_SHIELD, applies=_arms(PREVENT_AND_GAIN_LIFE, chosen=True, player_only=True)
)
def _reverse_damage_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Reverse Damage: "The next time a source of your choice would deal damage
    to you this turn, prevent that damage. You gain life equal to the damage
    prevented this way." The whole instance is prevented regardless of its size
    (CR 615.8)."""
    return _spend(game, event, PREVENT_AND_GAIN_LIFE, chosen=True, rider=_gain_prevented_life)


@prevention_effect(
    GENERIC_SHIELD, applies=_arms(PREVENT_AND_GAIN_LIFE, chosen=False, player_only=True)
)
def _reverse_damage_generic(game, event: dict) -> PreventionOutcome | None:
    """Reverse Damage cast without recording a chosen source (AI / headless):
    the next damage event from any source is prevented and gained as life."""
    return _spend(game, event, PREVENT_AND_GAIN_LIFE, chosen=False, rider=_gain_prevented_life)


def _exile_for_prevented(game, event: dict, used: list[Shield], prevented: int) -> None:
    """Bone Mask's rider (CR 615.5): the prevention happens first, then cards
    equal to what it absorbed leave the top of the shielded player's library.

    The recipient's own library, because "your library" is the shield holder's
    and this shield only ever sits on a player (``player_only`` below). An empty
    library exiles what is there and no more — running out is not a loss until
    a draw is attempted (CR 104.3c), and this is not a draw.
    """
    recipient = event["recipient"]
    taken = min(prevented, len(recipient.library))
    exiled = [recipient.library.pop(0) for _ in range(taken)]
    recipient.exile.extend(exiled)
    game.log.append(
        f"{used[0].source_name or 'A shield'} prevented {prevented} damage to "
        f"{recipient.name}"
        + (
            ", exiling " + ", ".join(card.name for card in exiled)
            if exiled else ", with no cards left to exile"
        )
    )


@prevention_effect(
    SOURCE_EXILE_SHIELD, applies=_arms(PREVENT_AND_EXILE, chosen=True, player_only=True)
)
def _exile_prevention_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Bone Mask: the whole instance from the chosen source, and then the
    library pays for it."""
    return _spend(game, event, PREVENT_AND_EXILE, chosen=True, rider=_exile_for_prevented)


@prevention_effect(
    GENERIC_EXILE_SHIELD,
    applies=_arms(PREVENT_AND_EXILE, chosen=False, player_only=True),
)
def _exile_prevention_generic(game, event: dict) -> PreventionOutcome | None:
    """The same shield armed without recording a chosen source (AI / headless):
    the next damage event from any source is prevented and paid for."""
    return _spend(game, event, PREVENT_AND_EXILE, chosen=False, rider=_exile_for_prevented)


def _gain_life_if_rider_colour(
    game, event: dict, used: list[Shield], prevented: int
) -> None:
    """Shadowbane's rider (CR 615.5): the prevention happens first, then the
    life gain — but only when the source was one of the colours the shield
    recorded.

    The colour is rechecked against the source *now* rather than when the shield
    was armed (CR 615.9's reading, applied to the rider's own condition): a
    source that has changed colour since is tested by what it is now.

    The life goes to the shield's holder, not to the damage's recipient: "you
    gain that much life" is the caster's sentence and the recipient may be one
    of their creatures.
    """
    shield = used[0]
    holder = (
        game.players[shield.filter_seat]
        if shield.filter_seat is not None
        and 0 <= shield.filter_seat < len(game.players)
        else event["recipient"]
    )
    recipient = event["recipient"]
    game.log.append(
        f"{shield.source_name or 'A shield'} prevented {prevented} damage to "
        f"{getattr(recipient, 'name', None) or recipient.card.name}"
    )
    if not shield.rider_colors:
        game._gain_life(holder, prevented, source_name=shield.source_name)
        return
    if set(shield.rider_colors) & set(damage_source_colors(game, event.get("source"))):
        game._gain_life(holder, prevented, source_name=shield.source_name)


@prevention_effect(
    SOURCE_TEAM_SHIELD, applies=_arms(PREVENT_TEAM, chosen=True)
)
def _team_prevention_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Shadowbane: the whole instance from the chosen source, wherever on this
    player's side it was headed."""
    return _spend(
        game, event, PREVENT_TEAM, chosen=True, rider=_gain_life_if_rider_colour
    )


@prevention_effect(
    GENERIC_TEAM_SHIELD, applies=_arms(PREVENT_TEAM, chosen=False)
)
def _team_prevention_generic(game, event: dict) -> PreventionOutcome | None:
    """The same shield cast without recording a chosen source (AI / headless):
    the next damage event from any source is prevented."""
    return _spend(
        game, event, PREVENT_TEAM, chosen=False, rider=_gain_life_if_rider_colour
    )


def _damage_the_source_controller(
    game, event: dict, used: list[Shield], prevented: int
) -> None:
    """Honorable Passage's rider (CR 615.5): the prevention happens first, then
    the damage comes back — but only when the source was one of the colours the
    shield recorded.

    Three things are read *now* rather than at the arming, and each is a rule
    rather than a convenience:

    * the colour, because CR 615.9's recheck is against the source as it is when
      the damage would be dealt (the same reading ``_gain_life_if_rider_colour``
      takes one rider over);
    * how much, because "that much" is what this shield absorbed and no arming
      knows it;
    * **whose** source it was — ``source_seat``, derived once inside
      ``deal_damage`` for CR 109.5's reason: a spell's ``source`` is the card as
      printed, shared by every copy and controlled by nobody, so no read of it
      can answer.

    The damage is dealt by the *card that armed the shield*, not by the
    prevented source: "Honorable Passage deals that much damage" names itself.
    ``source_name`` is the only handle the shield keeps on it, so the shield's
    own recorded name is what a later reader sees on the log line.
    """
    shield = used[0]
    game.log.append(
        f"{shield.source_name or 'A shield'} prevented {prevented} damage to "
        f"{recipient_label(event['recipient'])}"
    )
    if prevented <= 0:
        return
    if shield.rider_colors and not (
        set(shield.rider_colors)
        & set(damage_source_colors(game, event.get("source")))
    ):
        return
    seat = event.get("source_seat")
    if seat is None or not (0 <= seat < len(game.players)):
        # CR 109.5 has no answer for a source nobody controls (a turn-based
        # action), and the card names one. Nothing happens rather than the
        # damage landing on a guessed seat.
        return
    controller = game.players[seat]
    if getattr(controller, "lost", False):
        return
    game._deal_damage_to_player(
        controller, prevented, source=shield.source_name, asks=True,
        then=lambda dealt, name=shield.source_name, who=controller: game.log.append(
            f"{name or 'A shield'} dealt {dealt} damage to {who.name}"
        ),
    )


@prevention_effect(
    SOURCE_REFLECT_SHIELD, applies=_arms(PREVENT_AND_DAMAGE_SOURCE, chosen=True)
)
def _reflect_prevention_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Honorable Passage: the whole instance from the chosen source, wherever
    on the table it was headed."""
    return _spend(
        game, event, PREVENT_AND_DAMAGE_SOURCE, chosen=True,
        rider=_damage_the_source_controller,
    )


@prevention_effect(
    GENERIC_REFLECT_SHIELD, applies=_arms(PREVENT_AND_DAMAGE_SOURCE, chosen=False)
)
def _reflect_prevention_generic(game, event: dict) -> PreventionOutcome | None:
    """The same shield cast without recording a chosen source (AI / headless):
    the next damage event from any source is prevented and answered."""
    return _spend(
        game, event, PREVENT_AND_DAMAGE_SOURCE, chosen=False,
        rider=_damage_the_source_controller,
    )


def _log_whole_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    game.log.append(
        f"{used[0].source_name or 'A shield'} prevented {prevented} damage to "
        f"{recipient_label(event['recipient'])}"
    )


def recipient_label(recipient) -> str:
    """A damage recipient's name, whichever of CR 615.1's two kinds it is.

    A ``PlayerState`` has a ``name`` and a ``Permanent`` has a card that does.
    Every log line here read the player half until Circle of Despair armed a
    whole-instance shield on a creature, which is not a case a log line should
    ever have been able to decide.
    """
    return getattr(recipient, "name", None) or recipient.card.name


@prevention_effect(SOURCE_WHOLE, applies=_arms(PREVENT_WHOLE, chosen=True))
def _whole_prevention_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Pentagram of the Ages: "The next time a source of your choice would deal
    damage to you this turn, prevent that damage."

    CR 615.8's plain sentence, and the whole instance regardless of its size —
    the same absorption ``_reverse_damage_chosen_source`` performs, without the
    life gain that one's card prints after it.
    """
    return _spend(game, event, PREVENT_WHOLE, chosen=True, rider=_log_whole_prevention)


# ``player_only`` is gone from both of these, and it was never the rule: CR
# 615.1 puts a shield around "a player or a permanent", and every card that
# armed one of these happened to protect a player until Circle of Despair
# printed "…would deal damage to **any target**". A flag that says which cards
# exist rather than which the rule allows is one this engine removes when a card
# disagrees with it.
@prevention_effect(GENERIC_WHOLE, applies=_arms(PREVENT_WHOLE, chosen=False))
def _whole_prevention_generic(game, event: dict) -> PreventionOutcome | None:
    """The same shield activated without recording a chosen source (AI /
    headless): the next damage event from any source is prevented."""
    return _spend(game, event, PREVENT_WHOLE, chosen=False, rider=_log_whole_prevention)


def _log_color_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    game.log.append(
        f"Circle of Protection prevented {prevented} damage to "
        f"{event['recipient'].name} from a "
        + ("/".join(used[0].colors) or str(used[0].source_type or "chosen"))
        + " source"
    )


@prevention_effect(COLOR_SHIELD, applies=_arms(PREVENT_FROM_COLOR, player_only=True))
def _circle_of_protection(game, event: dict) -> PreventionOutcome | None:
    """Circle of Protection: "The next time a <color> source of your choice
    would deal damage to you this turn, prevent that damage." One shield per
    activation, matched against the source's colors at damage time (CR 615.9)
    and prevented in full."""
    return _spend(game, event, PREVENT_FROM_COLOR, rider=_log_color_prevention)


def _log_subject_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    game.log.append(
        f"{used[0].source_name or 'A shield'} prevented {prevented} damage to "
        f"{event['recipient'].name}"
    )


@prevention_effect(SUBJECT_BLANKET, applies=_arms(PREVENT_FROM_SUBJECT))
def _prevent_from_subject(game, event: dict) -> PreventionOutcome | None:
    """Al-abara's Carpet: "Prevent all damage that would be dealt to you this
    turn by attacking creatures without flying."

    A blanket rather than a charge: the shield holds neither points nor uses, so
    every matching source this turn is prevented in full and the sweep is what
    ends it. Which sources match is the printed noun phrase, rechecked against
    each one when the damage would be dealt (CR 615.9) — a creature that has
    since gained flying, or has left combat, is no longer described by it.
    """
    return _spend(game, event, PREVENT_FROM_SUBJECT, rider=_log_subject_prevention)


@prevention_effect(
    TARGETING_BLANKET, applies=_arms(PREVENT_FROM_TARGETING_SOURCE)
)
def _prevent_from_targeting_source(game, event: dict) -> PreventionOutcome | None:
    """Silhouette: "If a spell or ability that targets that creature would cause
    a source to deal damage to that creature this turn, prevent that damage."

    A blanket, so every qualifying event this turn is prevented in full and the
    cleanup sweep is what ends it. What qualifies is rechecked when the damage
    would be dealt (CR 615.9) — a burn spell aimed elsewhere that splashes onto
    this creature is not "a spell that targets that creature", and combat damage
    never is.
    """
    return _spend(game, event, PREVENT_FROM_TARGETING_SOURCE)


def _log_pool_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    recipient = event["recipient"]
    if not isinstance(recipient, PlayerState):
        game.log.append(f"Prevented {prevented} damage to {recipient.card.name}")


@prevention_effect(POOL, applies=_arms(PREVENT_NEXT_N))
def _prevention_pool(game, event: dict) -> PreventionOutcome | None:
    """"Prevent the next N damage that would be dealt to <recipient> this turn"
    (Healing Salve's prevention mode, Samite Healer, Rock Hydra, …). Each point
    prevented reduces the shield by 1; the remainder is dealt normally
    (CR 615.7). The one shield that protects creatures as well as players."""
    return _spend(game, event, PREVENT_NEXT_N, rider=_log_pool_prevention)


# ---------------------------------------------------------------------------
# A permanent's own static prevention, and the printed lines it implements
# ---------------------------------------------------------------------------
#
# Everything above is a shield a recipient was *given*: something resolved,
# armed it, and it is spent. This is the other shape — a static ability that
# applies while its source is on the battlefield, with no charges and no
# lifetime, so there is no Shield to hold and nothing for the sweeps to clear.
# It is read off the source's text at damage time for the same reason
# engine/replacements.py's interceptors are: the card says it, so the card is
# where the answer lives.

#: "If a source would deal damage to you, prevent that damage and put an
#: incarnation counter on this enchantment." (Nine Lives.) The counter's word
#: and the noun the card calls itself are **payload**, not part of the pattern's
#: meaning — a second card printing this with a different counter needs no code
#: here, which is the same reason engine/combat_restrictions.py holds its land
#: type as data.
_PREVENT_AND_COUNT_RE = re.compile(
    r"^if a source would deal damage to you, prevent that damage and put "
    r"an? (?P<counter>[a-z]+) counter on this "
    r"(?:artifact|creature|enchantment|land|permanent)$"
)


def prevent_and_count_kind(line: str) -> str | None:
    """The counter *line* places when it prevents, or None if it is not that
    line. One matcher, asked by the interceptor below and by both claim
    readers, so what is implemented and what is claimed cannot drift."""
    match = _PREVENT_AND_COUNT_RE.match(" ".join(line.strip().lower().rstrip(".").split()))
    return match.group("counter") if match else None


#: "Prevent all damage that would be dealt to this creature by artifact
#: sources." (Argothian Treefolk.) / "…by artifact creatures." (Argothian
#: Pixies.) The source class is payload, the way every other text-keyed table
#: here holds its parameter — a card printed "by red sources" needs no code.
#:
#: Anchored at both ends. A line saying more than this is a prevention this
#: file does not implement, and a prefix match would claim it and then enforce
#: the narrower rule, which is damage prevented that the card does not prevent.
#:
#: The subject is captured rather than fixed, because Artifact Ward prints the
#: same sentence about the creature it **enchants**. Two readers rather than one
#: permissive matcher: the shield is derived by reading a permanent's text, and
#: an Aura is itself a permanent — a single matcher would have Artifact Ward
#: shielding *itself* from artifact sources, which is a card nobody printed.
#: The optional leading condition (Bronze Horse: "**As long as you control
#: another creature,** prevent all damage ..."). CR 611.2's "as long as" clause
#: on a static ability -- the shield exists only while it holds, and it is
#: rechecked on every event rather than latched, because the creature it counts
#: may leave. The noun phrase is read by the same reader every other printed
#: noun phrase goes through, so "another creature" means here what it means
#: everywhere.
_PREVENT_ALL_FROM_SOURCE_TYPE_RE = re.compile(
    r"^(?:as long as you control (?P<condition>[^,]+), )?"
    r"prevent all (?P<combat>combat )?damage that would be dealt to "
    r"(?P<subject>this|enchanted|equipped) "
    r"(?:artifact|creature|enchantment|land|permanent) by "
    r"(?P<source>"
    r"(?:artifact|creature|enchantment|land) (?:sources|creatures|artifacts|permanents)"
    r"|enchanted creatures"
    r"|walls"
    r"|creatures it's blocking"
    r"|spells that target it"
    # "…by **creatures**" (Uncle Istvan). The bare plural, which is the same
    # class the two-word "creature sources" names — the printed noun says what
    # the source must be and "sources" says nothing further. Last in the
    # alternation because two phrases above open with the same word; the
    # pattern is anchored, so neither can be shadowed, and the order says
    # which reading is the narrow one.
    r"|creatures"
    # "…by **sources of the chosen color**." (Prismatic Ward.) / "…of the
    # **last** chosen color." (Chromatic Armor, which lets its controller
    # re-choose.) The property is one the *holder* recorded as it entered
    # (CR 614.1c), not one the phrase names outright — so it is resolved
    # against the permanent carrying the line before the source is tested, and
    # a holder that recorded nothing shields against nothing rather than
    # against everything. Both printings are one alternative: "last" says which
    # of several choices counts, and only the latest is kept either way.
    r"|sources of the (?:last )?chosen color"
    r")$"
)

#: What each printed source phrase means, as the fields
#: :func:`_source_shield_matches` tests. Data rather than a branch per phrase,
#: for the reason the land type in ``combat_restrictions.py`` is data: a card
#: printed with another noun in the same sentence is the same effect.
#:
#: The three Legends phrases are each a *different kind* of narrowing, which is
#: why the value is a dict rather than the type string this used to return.
#: "Walls" is a subtype (CR 205.3), "enchanted creatures" is a state of the
#: source object, and "creatures it's blocking" is a relationship between the
#: source and the recipient that neither object carries on its own.
_SOURCE_CLASSES: dict[str, dict[str, object]] = {
    "artifact sources": {"card_type": "artifact"},
    "artifact creatures": {"card_type": "artifact"},
    "artifact permanents": {"card_type": "artifact"},
    "creature sources": {"card_type": "creature"},
    # Uncle Istvan's bare plural. The same class, because the printed noun is
    # what narrows the source and "sources" adds nothing to it.
    "creatures": {"card_type": "creature"},
    "creature creatures": {"card_type": "creature"},
    "creature permanents": {"card_type": "creature"},
    "enchantment sources": {"card_type": "enchantment"},
    "enchantment creatures": {"card_type": "enchantment"},
    "enchantment permanents": {"card_type": "enchantment"},
    "land sources": {"card_type": "land"},
    "land creatures": {"card_type": "land"},
    "land permanents": {"card_type": "land"},
    "walls": {"subtype": "wall"},
    "enchanted creatures": {"card_type": "creature", "enchanted": True},
    "creatures it's blocking": {"card_type": "creature", "blocked_by_recipient": True},
    # "...by **spells that target it**" (Bronze Horse). Not a property of the
    # source object at all: it is a fact about the spell on the stack that is
    # dealing the damage, and the same spell aimed at something else is not
    # shielded against. A fourth kind of narrowing beside the three above, which
    # is why the value is a dict rather than a type word.
    "spells that target it": {"spell_targets_recipient": True},
    # Resolved against the holder before the source is tested — see
    # :func:`_resolved_chosen_color`. The key is deliberately not `color`: a
    # class that reached the matcher unresolved must answer *nothing* rather
    # than every source, and a key no branch of `_source_shield_matches` reads
    # would do the opposite.
    "sources of the chosen color": {"chosen_color": True},
    "sources of the last chosen color": {"chosen_color": True},
}


def _resolved_chosen_color(wanted: dict, holder) -> dict | None:
    """*wanted* with a chosen-colour class turned into the colour the holder
    recorded, or None when it recorded none.

    CR 614.1c puts the choice at entry and ``engine/mixins/permanent_state.py``
    stamps it, so the answer lives on the permanent whose text carried the line
    — which is why it is resolved here, where that permanent is in hand, rather
    than in the pure matcher below. The same shape
    ``handlers/_common._resolve_chosen_color`` gives the noun-phrase side.

    None rather than an unnarrowed shield: a holder with no colour recorded has
    named no property for CR 615.9 to recheck, and a shield answering to every
    source is the widest possible reading of a sentence that names one colour.
    """
    if not wanted.get("chosen_color"):
        return wanted
    color = (getattr(holder, "metadata", {}) or {}).get("chosen_color")
    if not color:
        return None
    resolved = {k: v for k, v in wanted.items() if k != "chosen_color"}
    resolved["color"] = color
    return resolved


def _source_shield_matches(game, source, recipient, wanted: dict) -> bool:
    """Whether *source* is in the class *wanted* names.

    Every key is checked, never a subset: a shield whose phrase this file
    admits and whose narrowing it then ignores is damage prevented that the
    card does not prevent, which is the direction every gate in this codebase
    is written against.
    """
    card_type = wanted.get("card_type")
    if card_type and not source_has_type(game, source, str(card_type)):
        return False
    subtype = wanted.get("subtype")
    if subtype:
        if not hasattr(source, "has_type") or not source.has_type(str(subtype)):
            return False
    if wanted.get("enchanted"):
        from .auras import auras_attached_to

        if not hasattr(source, "metadata") or not auras_attached_to(source):
            return False
    color = wanted.get("color")
    if color and color not in damage_source_colors(game, source):
        # CR 615.9 rechecks the recorded property when the damage would be
        # dealt, so a source that has changed colour since the Aura entered is
        # tested by what it is now.
        return False
    if wanted.get("chosen_color"):
        # Unresolved: nothing was recorded, so the class names no source at all.
        # Answering True here would shield against every source in the game.
        return False
    if wanted.get("spell_targets_recipient") and not _spell_targets_recipient(
        game, source, recipient
    ):
        return False
    if wanted.get("blocked_by_recipient"):
        # "…by creatures **it's blocking**" (Wall of Shadows, Wall of Vapor).
        # The Wall is the blocker and the source is an attacker it was declared
        # against, so the relationship is read off combat rather than off
        # either object — and it is directional: a creature blocking the Wall
        # is not a creature the Wall is blocking.
        if not _recipient_is_blocking(game, recipient, source):
            return False
    return True


def _spell_targets_recipient(game, source, recipient) -> bool:
    """Whether *source* is a spell on the stack that targets *recipient*.

    A spell's damage source is the card itself (CR 109.5) -- the card as
    printed, which records neither who cast it nor what it was aimed at. So the
    targets come from ``Game.resolving_targets``, the seam
    ``_execute_oracle_instruction`` pushes around every instruction, exactly as
    the seat does. Reading the stack instead does not work and is not merely
    slower: the object is popped before its instructions run, so by the time the
    damage would be dealt there is nothing there to ask.

    "Spells", not abilities: an activated or triggered ability is not a spell
    (CR 113.7a), and its damage source is the permanent it is on -- which is what
    the first refusal below tests, because a permanent is not a spell however it
    is dealing the damage.

    By the stable target *id* rather than a recorded index: an index is a slot
    in a battlefield list, and anything leaving renumbers every later one.
    """
    if source is None or hasattr(source, "metadata"):
        return False
    permanent_id = getattr(recipient, "permanent_id", None)
    if permanent_id is None:
        return False
    chosen = getattr(game, "resolving_targets", None) or ()
    return bool(chosen) and permanent_id in chosen[-1]


def _recipient_is_blocking(game, recipient, source) -> bool:
    """Whether *recipient* was declared as a blocker of *source* (CR 509.1a)."""
    if not hasattr(recipient, "metadata") or not hasattr(source, "metadata"):
        return False
    attacker_index = game.battlefield_index_of(source)
    blocker_index = game.battlefield_index_of(recipient)
    blocker_seat = game.controller_index_of(recipient)
    if attacker_index is None or blocker_index is None or blocker_seat is None:
        return False
    assignments = game.combat_blockers.get(blocker_seat, {})
    return attacker_index in (assignments.get(blocker_index) or ())


def _source_type_shield_match(line: str):
    return _PREVENT_ALL_FROM_SOURCE_TYPE_RE.match(
        " ".join(line.strip().lower().rstrip(".").split())
    )


def _shield_from_match(match) -> dict | None:
    """The source class, event narrowing and condition one matched line
    describes."""
    wanted = _SOURCE_CLASSES.get(match.group("source"))
    if wanted is None:
        # A phrase the pattern admits with no class behind it would be a shield
        # against everything. Answering None keeps the card unsupported.
        return None
    described = {**wanted, "combat_only": bool(match.group("combat"))}
    phrase = match.group("condition")
    if phrase is not None:
        # The grammar's own noun-phrase reader, lazily imported because the
        # grammar's parse claim imports this module. A phrase it cannot read
        # answers None, which keeps the card unsupported rather than shielding
        # it unconditionally -- a condition dropped is a shield strictly wider
        # than the card prints.
        from .grammar import subject_filter_payload

        filt = subject_filter_payload(phrase)
        if filt is None:
            return None
        described["condition"] = {"kind": "controls", "who": "you", "filter": filt}
    return described


def prevent_all_from_source_type(line: str) -> dict | None:
    """The class of source *line* shields the permanent printing it against, or
    None if it is not that line. One matcher, asked by the interceptor below and
    by the claim reader, so what is implemented and what is claimed cannot
    drift."""
    match = _source_type_shield_match(line)
    if match is None or match.group("subject") != "this":
        return None
    return _shield_from_match(match)


def attached_prevent_all_from_source_type(line: str) -> dict | None:
    """The same answer for the "enchanted / equipped" form (Artifact Ward),
    where the shield covers what the Aura or Equipment is attached to rather
    than the permanent printing the line.

    Exported for ``engine/auras.py``'s support gate, which claims the line by
    asking the code that carries it out.
    """
    match = _source_type_shield_match(line)
    if match is None or match.group("subject") == "this":
        return None
    return _shield_from_match(match)


def _source_type_shielded_by(game, event: dict) -> dict | None:
    """The source class the damaged permanent is shielded against.

    Pure: it reads text and answers, spending nothing. Two places print the
    line, and both are read here: the recipient's own text ("dealt to **this**
    creature", so a second copy on the battlefield shields itself and not its
    twin) and the text of whatever is attached to it ("dealt to **enchanted**
    creature", which is a shield the recipient's own text says nothing about).
    """
    from .auras import auras_attached_to

    recipient = event["recipient"]
    if isinstance(recipient, PlayerState) or recipient is None:
        return None
    for line in getattr(recipient, "effective_card", recipient.card).oracle_text.splitlines():
        wanted = prevent_all_from_source_type(line)
        if wanted is None or not _condition_holds(game, wanted, recipient):
            continue
        resolved = _resolved_chosen_color(wanted, recipient)
        if resolved is not None:
            return resolved
    for attached in auras_attached_to(recipient):
        for line in attached.effective_card.oracle_text.splitlines():
            wanted = attached_prevent_all_from_source_type(line)
            if wanted is None or not _condition_holds(game, wanted, attached):
                continue
            # The colour is the **Aura's**, recorded as it entered — not the
            # enchanted creature's, which has none of its own.
            resolved = _resolved_chosen_color(wanted, attached)
            if resolved is not None:
                return resolved
    return None


def _condition_holds(game, wanted: dict, holder) -> bool:
    """Whether a shield's "as long as" clause holds right now (CR 611.2).

    Asked here, where the permanent whose text carried the line is in hand, and
    asked on every event rather than latched: the creature the clause counts may
    leave, and a shield that outlived its condition is one the card does not
    print. Pure, like every other predicate in this file.

    The clause is evaluated by ``engine/static_bonuses.conditional_static_holds``
    -- the same payload shape and the same evaluator the conditional P/T bonuses
    use, so "you control another creature" has one meaning in the engine.
    """
    condition = wanted.get("condition")
    if condition is None:
        return True
    from .static_bonuses import conditional_static_holds

    seat = game.controller_index_of(holder)
    if seat is None:
        return False
    return conditional_static_holds(game, seat, holder, condition)


def _applies_source_type_blanket(game, event: dict) -> bool:
    wanted = _source_type_shielded_by(game, event)
    if wanted is None:
        return False
    if wanted.get("combat_only") and not event.get("combat"):
        # "Prevent all **combat** damage … by Walls" (Marble Priest). A shield
        # that ignored the word would stop a Wall's ping as well, which is a
        # strictly larger effect than the card prints.
        return False
    return _source_shield_matches(game, event.get("source"), event["recipient"], wanted)


def _source_class_label(wanted: dict) -> str:
    """The printed class a shield answers to, in words rather than as its dict.

    The log line used to interpolate the payload itself, which put
    ``{'card_type': 'artifact', 'combat_only': False}`` in front of a player.
    Built from the same keys the matcher reads, so a narrowing added there and
    forgotten here shows as the generic word instead of as a silently different
    claim.
    """
    color = wanted.get("color")
    if color:
        # The symbol back to the printed word, through the grammar's own colour
        # table rather than a second copy of it.
        from .grammar.vocabulary import COLOR_WORDS

        return next(
            (word for word, symbol in COLOR_WORDS.items() if symbol == color),
            str(color),
        )
    for key in ("subtype", "card_type"):
        value = wanted.get(key)
        if value:
            return str(value).lower()
    if wanted.get("enchanted"):
        return "enchanted creature"
    if wanted.get("blocked_by_recipient"):
        return "blocked creature"
    if wanted.get("spell_targets_recipient"):
        return "targeting spell"
    return "matching"


@prevention_effect(SOURCE_TYPE_BLANKET, applies=_applies_source_type_blanket)
def _prevent_all_from_source_type(game, event: dict) -> PreventionOutcome | None:
    wanted = _source_type_shielded_by(game, event)
    if wanted is None:
        return None
    recipient = event["recipient"]
    game.log.append(
        f"{recipient.card.name} prevented {event['amount']} damage "
        f"from a {_source_class_label(wanted)} source"
    )
    return PreventionOutcome(prevented=event["amount"])


def _static_prevention_source(game, event: dict):
    """The recipient's own permanent whose static prevention covers this event,
    with the counter it charges — or None.

    Pure, like every other applicability predicate here: it looks the permanent
    up and reads its text, and the counter is only placed by the ``apply`` half.
    """
    recipient = event["recipient"]
    if not isinstance(recipient, PlayerState):
        return None
    for permanent in game.controlled_by(recipient):
        for line in permanent.effective_card.oracle_text.splitlines():
            counter = prevent_and_count_kind(line)
            if counter is not None:
                return permanent, counter
    return None


def _applies_static_whole_event(game, event: dict) -> bool:
    return _static_prevention_source(game, event) is not None


@prevention_effect(STATIC_WHOLE_EVENT, applies=_applies_static_whole_event)
def _prevent_and_place_counter(game, event: dict) -> PreventionOutcome | None:
    """Nine Lives: "If a source would deal damage to you, prevent that damage
    and put an incarnation counter on this enchantment."

    The whole instance is prevented however large it is, and the counter is
    placed once per prevented event rather than once per point — CR 615.5's
    "additional effect", which happens *after* the prevention and refers to the
    event, not to the damage's size. Nine damage and one damage each cost the
    same counter, which is what makes the card a nine-*event* shield.
    """
    found = _static_prevention_source(game, event)
    if found is None:
        return None
    permanent, counter = found
    total = add_counters(permanent, counter, 1)
    game.log.append(
        f"{permanent.card.name} prevented {event['amount']} damage to "
        f"{event['recipient'].name} ({total} {counter} counter(s))"
    )
    return PreventionOutcome(prevented=event["amount"])


#: "For each 1 damage that would be dealt to this creature, if it has a +1/+1
#: counter on it, remove a +1/+1 counter from it and prevent that 1 damage."
#: (Rock Hydra.) The counter's word is payload, exactly as Nine Lives' is
#: above; the backreference holds the removal to the same counter the
#: condition asked about, so a line naming two different counters is not this
#: shape and refuses.
_PER_DAMAGE_COUNTER_RE = re.compile(
    r"^for each 1 damage that would be dealt to this "
    r"(?:artifact|creature|enchantment|land|permanent), "
    r"if it has an? (?P<counter>\S+) counter on it, "
    r"remove an? (?P=counter) counter from it and prevent that 1 damage$"
)


def per_damage_counter_kind(line: str) -> str | None:
    """The counter *line* spends per point of damage, or None if it is not
    that line. One matcher for the interceptor and both claim readers, so what
    is implemented and what is claimed cannot drift."""
    match = _PER_DAMAGE_COUNTER_RE.match(
        " ".join(line.strip().lower().rstrip(".").split())
    )
    return match.group("counter") if match else None


def _counters_available(permanent, counter: str) -> int:
    """How many *counter* counters *permanent* holds. "+1/+1" lives on the
    P/T channel (engine/pt.py — it has layer-7d meaning); every other word is
    an inert named counter."""
    if counter == "+1/+1":
        return int(permanent.metadata.get("plus_counters", 0))
    return counters_on(permanent, counter)


def _per_damage_counter_shield(game, event: dict) -> str | None:
    """The counter kind the recipient's own per-point shield spends, or None."""
    recipient = event["recipient"]
    if isinstance(recipient, PlayerState):
        return None
    for line in recipient.effective_card.oracle_text.splitlines():
        counter = per_damage_counter_kind(line)
        if counter is not None:
            return counter
    return None


def _applies_per_damage_counter(game, event: dict) -> bool:
    counter = _per_damage_counter_shield(game, event)
    return counter is not None and _counters_available(event["recipient"], counter) > 0


@prevention_effect(PER_POINT_COUNTER_SHIELD, applies=_applies_per_damage_counter)
def _remove_counter_per_damage(game, event: dict) -> PreventionOutcome | None:
    """Rock Hydra's automatic half: one counter per point, only as far as the
    counters go (CR 615.7's partial prevention) — three counters against five
    damage remove all three and let two through.

    This was the acknowledged line the roadmap called "the Nine Lives class
    hiding behind a verified-sounding acknowledgement": prevention.py was
    credited with it while implementing only the activated {R} shield, so the
    damage went through in full with the counters untouched.
    """
    counter = _per_damage_counter_shield(game, event)
    if counter is None:
        return None
    permanent = event["recipient"]
    if counter == "+1/+1":
        removed = remove_plus1_counters(permanent, event["amount"])
    else:
        have = counters_on(permanent, counter)
        removed = min(event["amount"], have)
        if removed > 0:
            remove_counters(permanent, counter, removed)
    if removed <= 0:
        return None
    game.log.append(
        f"{permanent.card.name} removed {removed} {counter} counter(s) to "
        f"prevent {removed} damage"
    )
    return PreventionOutcome(prevented=removed)


#: "Prevent all damage that would be dealt to you." (Glacial Chasm.) A static
#: prevention on the permanent's **controller** rather than on the permanent
#: itself, and the unnarrowed member of the family above: no source class, no
#: charges and no duration, because a static ability applies while its source is
#: on the battlefield and stops the moment it is not.
#:
#: The printed "combat" is captured for the reason
#: ``_PREVENT_ALL_FROM_SOURCE_TYPE_RE`` captures its own: a shield that ignored
#: the word would stop a burn spell as well, which is a strictly larger effect
#: than such a card prints.
#:
#: Anchored at both ends, and **without** a duration: "…this turn" is a one-shot
#: effect a spell resolves, which the grammar's ``PreventDamage`` production
#: reads and this must not claim. Claiming the line here takes it away from
#: those productions entirely (``engine/grammar/registries.py``), so the anchor
#: is what keeps the two sentences apart.
_PREVENT_ALL_TO_CONTROLLER_RE = re.compile(
    r"^prevent all (?P<combat>combat )?damage that would be dealt to you$"
)


def prevent_all_to_controller(line: str) -> dict | None:
    """The blanket *line* gives the permanent's controller, or None.

    One matcher, asked by the interceptor below and by the claim reader, so
    what is implemented and what is claimed cannot drift.
    """
    match = _PREVENT_ALL_TO_CONTROLLER_RE.match(
        " ".join(line.strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    return {"combat_only": bool(match.group("combat"))}


def _controller_blanket_for(game, event: dict) -> dict | None:
    """The blanket shielding this player, read off their own battlefield. Pure.

    A player has no text of their own, so the line is found on the permanents
    they control — the same read ``_source_type_shielded_by`` makes of a
    damaged permanent, one relation out. Through the control seam rather than a
    battlefield list, so a Glacial Chasm somebody else has taken control of
    shields *them*.
    """
    recipient = event["recipient"]
    if not isinstance(recipient, PlayerState):
        return None
    seat = game.players.index(recipient) if recipient in game.players else None
    if seat is None:
        return None
    for permanent in game.controlled_by(seat):
        for line in permanent.effective_card.oracle_text.splitlines():
            described = prevent_all_to_controller(line)
            if described is not None:
                return described
    return None


def _applies_controller_blanket(game, event: dict) -> bool:
    described = _controller_blanket_for(game, event)
    if described is None:
        return False
    if event["amount"] <= 0:
        return False
    return bool(event.get("combat")) or not described["combat_only"]


@prevention_effect(CONTROLLER_BLANKET, applies=_applies_controller_blanket)
def _prevent_all_to_controller(game, event: dict) -> PreventionOutcome | None:
    """Glacial Chasm: "Prevent all damage that would be dealt to you."

    Every point, from every source, for as long as the permanent printing it is
    on the battlefield. Nothing is spent and nothing is recorded — the next
    event asks the board again, which is what makes the shield end with the
    permanent (CR 611.2) rather than needing a sweep.
    """
    game.log.append(
        f"{event['recipient'].name} prevented {event['amount']} damage "
        "(all damage that would be dealt to them)"
    )
    return PreventionOutcome(prevented=event["amount"])


#: "Prevent all damage that would be dealt by instant and sorcery spells."
#: (Energy Storm.) A static prevention with **no recipient** — every point every
#: spell of the named classes would deal, to anything. The narrowing is on the
#: source's card type, which is what makes it a different reader from the
#: recipient-scoped blanket above: there is no object to hang the shield off, so
#: the permanent printing the line is scanned for on every event instead.
#:
#: The classes are captured and split on "and", so a card printing one type or
#: three needs no code — the same choice ``_SOURCE_DAMAGE_CAP`` makes about its
#: own printed class one file over.
_PREVENT_ALL_FROM_SPELL_CLASS_RE = re.compile(
    r"^prevent all (?P<combat>combat )?damage that would be dealt by "
    r"(?P<classes>[a-z ]+?) spells$"
)


def prevent_all_from_spell_class(line: str) -> dict | None:
    """The spell classes *line* shields the whole table from, or None.

    One matcher, asked by the interceptor below and by the claim reader, so what
    is prevented and what is claimed cannot drift.

    A class naming no readable type refuses the whole line rather than
    shielding against everything: ``source_has_type`` answers False for a word
    it does not know, and a shield that matched every spell would be a card
    nobody printed.
    """
    match = _PREVENT_ALL_FROM_SPELL_CLASS_RE.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    classes = tuple(
        word.strip()
        for word in match.group("classes").replace(" and ", ",").split(",")
        if word.strip()
    )
    if not classes or any(word not in _SPELL_CLASSES for word in classes):
        return None
    return {"classes": classes, "combat_only": bool(match.group("combat"))}


#: The card types a spell class may name. A closed set rather than any word,
#: because ``source_has_type`` substring-matches a type line: an unlisted word
#: would answer False for every spell and the shield would silently do nothing,
#: which is the failure this file's claim readers exist to keep out of the
#: supported pool.
_SPELL_CLASSES = frozenset({
    "artifact", "creature", "enchantment", "instant", "sorcery",
})


def _spell_class_blanket(game, event: dict) -> dict | None:
    """The spell-class blanket covering this event, or None. Pure.

    Scanned over every battlefield rather than the recipient's: the sentence
    names no recipient at all, so an opponent's Energy Storm covers this damage
    exactly as your own would.
    """
    if event["amount"] <= 0:
        return None
    source = event.get("source")
    if source is None or hasattr(source, "metadata"):
        # A permanent is not a spell however it is dealing the damage
        # (CR 110.1). A spell's source is the card as printed (CR 109.5), which
        # is the shape with no ``metadata``.
        return None
    for permanent in game.all_permanents():
        for line in permanent.effective_card.oracle_text.splitlines():
            described = prevent_all_from_spell_class(line)
            if described is None:
                continue
            if described["combat_only"] and not event.get("combat"):
                continue
            if any(
                source_has_type(game, source, word)
                for word in described["classes"]
            ):
                return described
    return None


def _applies_spell_class_blanket(game, event: dict) -> bool:
    return _spell_class_blanket(game, event) is not None


@prevention_effect(SPELL_CLASS_BLANKET, applies=_applies_spell_class_blanket)
def _prevent_all_from_spell_class(game, event: dict) -> PreventionOutcome | None:
    """Energy Storm: "Prevent all damage that would be dealt by instant and
    sorcery spells."

    Every point, for as long as the permanent printing it is on the
    battlefield. Nothing is spent and nothing recorded — the next event asks the
    board again, which is what ends the shield with the permanent (CR 611.2)
    rather than with a sweep.
    """
    described = _spell_class_blanket(game, event)
    if described is None:  # pragma: no cover - the predicate just said otherwise
        return None
    game.log.append(
        f"{event['amount']} damage from a "
        f"{'/'.join(described['classes'])} spell is prevented"
    )
    return PreventionOutcome(prevented=event["amount"])


def prevention_claims_line(line: str) -> bool:
    """Whether one printed line is, in full, a static prevention effect
    implemented above.

    The twin of ``replacements.replacement_claims_line`` and read by the same
    two callers — the grammar's parse claim (engine/grammar/registries.py) and
    the support gate (engine/oracle.py) — because a permanent whose ability is a
    prevention produces no instruction either. Nine Lives happened to print
    three other lines, so it reported supported with this one silently doing
    nothing; a card printing only this one would have reported unsupported while
    working perfectly, which is the other half of the same hole.
    """
    return (
        prevent_and_count_kind(line) is not None
        or per_damage_counter_kind(line) is not None
        or prevent_all_from_source_type(line) is not None
        or attached_prevent_all_from_source_type(line) is not None
        or attached_combat_shield_direction(line) is not None
        or prevent_all_to_controller(line) is not None
        or prevent_all_from_spell_class(line) is not None
    )
