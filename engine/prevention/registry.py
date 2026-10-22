"""The prevention registry itself: the default-order space, the decorator, and
the candidates a damage event contends with (CR 615, CR 616.1).

Every shield in this package takes its ``order`` from the bands below, and
``@prevention_effect`` raises at import on a duplicate — so the bands are one
table in one module, and a new shield picks its slot here, beside the reason
each band sits where it does. ``shield_candidates`` hands the whole registry to
``engine/damage_events.py`` as one half of a damage event's contention set; the
other half is ``engine/replacements/``' damage kinds, whose orders share this
space (see the package docstring).

``source_has_type`` is here because it is the floor both halves of the package
read — the shields a recipient was given and a permanent's own static
prevention alike ask what type a damage source is — and three modules outside
the package ask it too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..effect_ordering import Candidate


# Order bands. Protection runs first of all: it is the widest free shield on the
# list — it takes the whole instance, it is never used up, and a recipient that
# has it has it against every point the source could ever deal — so letting it
# go first is the blanket band's own argument at its strongest. A consumable
# spent ahead of it would be spent on damage that was never going to land.
# Zero rather than a free slot in the middle: the damage replacements
# (``engine/replacements/registry.py``) share this one order space and already
# occupy 1-8, and protection has to be ahead of *those* too — a redirect chosen
# first (Jade Monolith, order 1) would move the event onto a player who is not
# protected and land damage the rule prevented.
PROTECTION = 0  # CR 702.16e
# Blanket combat shields run next: they are flags rather than
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
# "Prevent all damage that would be dealt to creatures." (Bubble Matrix) /
# "…to creatures you control." (Inner Sanctum.) The same static blanket as
# Glacial Chasm's above with a *described set of permanents* in the recipient
# slot instead of a player. Beside the others for their reason: no charges, so
# applying it costs its recipient nothing and spends no shield that could have
# covered later damage.
MATCHING_BLANKET = 30
# "…the next time it would deal damage this turn, prevent that damage."
# (Desperate Gambit.) One instance from one chosen source, to **anything** — the
# only shield in this package that names no recipient at all, which is why its
# record lives on the source instead of on a protected object
# (``engine/next_damage.py``).
#
# It is a charge rather than a blanket, and it still belongs here rather than
# down among the consumables at 100-600. CR 616.1e gives the choice to the
# *affected* player, and this is not their charge: somebody else armed it, so
# applying it costs them nothing and leaves every shield of their own unspent
# for the next source. That is the blanket band's own argument — "applying one
# costs the recipient nothing" — read from the seat that actually chooses.
CHOSEN_SOURCE_ONE_SHOT = 31
# "If a source would deal 3 or less damage to this creature, prevent that
# damage." (Callous Giant.) A permanent's own static shield whose narrowing is
# the **size of the event** — free like every blanket above it, so it sits with
# them. Being early is what makes it compose the way its controller would
# choose (CR 616.1e): a small event is taken whole before any consumable is
# spent on it, and a large one is simply not this shield's business until
# something else has cut it down — CR 616.1f re-asks after every applied
# effect, so a pool that brings 5 down to 3 hands the remainder here.
SMALL_EVENT_BLANKET = 32
# "Prevent all damage that would be dealt to a creature by another creature if
# they share a color." (Well-Laid Plans.) A blanket over the whole table whose
# narrowing is a **relation between the two ends of the event**. No charges, so
# beside the others and ahead of every consumable, for their reason.
SHARED_COLOR_BLANKET = 33
# "Prevent all damage that would be dealt to you this turn by a source of your
# choice." (Samite Ministration, Protective Sphere.) A blanket a player was
# handed against one named source — never used up, so applying it costs its
# holder nothing and it sits with the others here, ahead of every consumable.
# That is the whole reason it is not the whole-instance shield at 310 with its
# charge left on: a Reverse Damage naming the same source would be spent first
# on damage this was always going to stop.
CHOSEN_SOURCE_BLANKET = 34
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
# "If a source would deal damage to you, prevent 1 of that damage."
# (Urza's Armor.) A permanent's own static prevention of a *fixed number of
# points*, which is a shape neither band above nor below it has: it is partial
# like Forcefield's cap and free like a blanket. It sits here, at the bottom of
# the free band, for the blanket band's own argument — applying it costs its
# controller nothing, so letting it go first keeps a consumable from being spent
# on a point that was never going to land. Behind the blankets themselves,
# because an event a blanket takes whole leaves this one nothing to shave.
STATIC_POINTS = 40
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
#: The same pool with CR 615.5's counters behind it (Temper). Before the plain
#: pool, which is where every other rider-bearing shield sits relative to its
#: rider-less twin on this list (Reverse Damage before Pentagram of the Ages):
#: the rider is what the card was played for, and CR 616.1e lets the affected
#: player choose any order anyway — this is only the default a non-interactive
#: seat takes.
#: Hidden Retreat's blanket over one cast spell. With the other blankets rather
#: than with the consumable shields, and before them: it is a flag rather than a
#: charge, so applying it costs its controller nothing and letting it go first
#: keeps a consumable from being spent on damage that was never going to be
#: dealt — the reason stated at the top of this list for every blanket on it.
SPELL_BLANKET = 13
POOL_WITH_COUNTERS = 599
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
            # Every entry in this package is CR 615 prevention by construction,
            # which is what "can't be prevented" (Whippoorwill) switches off.
            prevents_or_redirects=True,
            prevents=True,
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
# ``damage_source_colors`` (imported at the top of ``shields.py`` and
# ``static.py``) is what every site in this package now asks.


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
