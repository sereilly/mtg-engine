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

from .effect_ordering import Candidate
from .models import PlayerState
from .named_counters import add_counters, counters_key, counters_on
from .pt import remove_plus1_counters
from .shields import (
    PREVENT_ALL_BUT,
    PREVENT_AND_GAIN_LIFE,
    PREVENT_FROM_COLOR,
    PREVENT_NEXT_N,
    Shield,
    drop_spent,
    shields_on,
)

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
COMBAT_SHIELD = 20  # "…dealt to and dealt by that creature this turn"
# "Prevent all damage that would be dealt to this creature by artifact
# sources." (Argothian Treefolk.) A permanent's own blanket shield against a
# class of source — no charges, so applying it costs its recipient nothing, and
# it belongs with the other blankets rather than with the consumables below.
SOURCE_TYPE_BLANKET = 25
SOURCE_CAP = 100  # Forcefield against a chosen attacker
GENERIC_CAP = 200  # Forcefield with no chosen attacker
SOURCE_SHIELD = 300  # Reverse Damage against a chosen source
GENERIC_SHIELD = 400  # Reverse Damage with no chosen source
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
        )
        for c in PREVENTION_EFFECTS
    ]


# ---------------------------------------------------------------------------
# Source matching
# ---------------------------------------------------------------------------

def source_colors(source) -> tuple[str, ...]:
    """Color symbols of a damage source — a Permanent (honoring a color
    override), a CardDefinition (spell), or None."""
    if source is None:
        return ()
    meta = getattr(source, "metadata", None)
    if isinstance(meta, dict) and meta.get("color_override"):
        return (str(meta["color_override"]),)
    card = getattr(source, "card", source)
    return tuple(getattr(card, "colors", ()) or ())


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


# Ebony Horse: "Prevent all combat damage that would be dealt to and dealt by
# that creature this turn." — a per-creature marker set by the
# untap_attacker_and_prevent_combat_damage handler, cleared in cleanup.
_COMBAT_SHIELD_KEY = "prevent_combat_damage_to_and_by_until_eot"

#: Which end of the event a combat shield covers. Ebony Horse's marker means
#: BOTH, and it stays a bare boolean so nothing that reads it has to change;
#: the Legends cards need the halves, because "Prevent all combat damage that
#: would be dealt **by** target creature this turn" (Horn of Deafening, Lady
#: Evangela) leaves the creature perfectly able to *take* combat damage, and
#: folding it into the two-way shield would make those creatures unkillable in
#: combat.
COMBAT_SHIELD_BY = "by"
COMBAT_SHIELD_TO = "to"
COMBAT_SHIELD_BOTH = "to_and_by"

#: The directional turn-long marker, beside Ebony Horse's boolean rather than
#: replacing it. Both are swept by ``_EOT_METADATA_KEYS``.
_COMBAT_SHIELD_DIRECTION_KEY = "prevent_combat_damage_direction_until_eot"

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


def _combat_shield_directions(perm) -> frozenset[str]:
    """Every direction *perm* is currently shielded in, from either source.

    Accepts None and non-permanent damage sources (a spell's
    ``CardDefinition``), which carry no shield at all.
    """
    metadata = getattr(perm, "metadata", None)
    if not metadata:
        return frozenset()
    directions: set[str] = set()
    if metadata.get(_COMBAT_SHIELD_KEY):
        directions.add(COMBAT_SHIELD_BOTH)
    marker = metadata.get(_COMBAT_SHIELD_DIRECTION_KEY)
    if marker:
        directions.add(str(marker))
    attached = _attached_combat_shield(perm)
    if attached is not None:
        directions.add(attached)
    return frozenset(directions)


def shields_combat_damage(perm, *, dealt_to: bool) -> bool:
    """Whether *perm*'s combat shields cover an event it is on one end of.

    *dealt_to* says which end: True when *perm* is the recipient, False when it
    is the source. The two-way marker answers both; a one-way one answers only
    its own end, which is the whole point of carrying the direction.
    """
    directions = _combat_shield_directions(perm)
    wanted = COMBAT_SHIELD_TO if dealt_to else COMBAT_SHIELD_BY
    return COMBAT_SHIELD_BOTH in directions or wanted in directions


def combat_shielded(perm) -> bool:
    """Whether *perm* carries a "prevent all combat damage to and by this
    creature" shield. Accepts None and non-permanent damage sources (a spell's
    CardDefinition), which never carry one."""
    metadata = getattr(perm, "metadata", None)
    return bool(metadata) and bool(metadata.get(_COMBAT_SHIELD_KEY))


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
    if shield.color is not None and shield.color not in source_colors(source):
        return False
    if shield.source_type is not None and not source_has_type(
        game, source, shield.source_type
    ):
        return False
    return True


def _live(game, event: dict, kind: str, *, chosen: bool | None = None):
    """Shields of *kind* on the event's recipient that could modify this event.

    *chosen* selects one half of the order space: True for shields naming a
    source, False for the "any source" fallback an AI or headless activation
    arms. They are separate registrations because they take separate default
    orders, and CR 616.1e's default is rules-visible.
    """
    recipient = event["recipient"]
    amount = event["amount"]
    for shield in shields_on(recipient):
        if shield.kind != kind or shield.spent:
            continue
        if chosen is not None and (shield.source is not None) != chosen:
            continue
        if not _source_matches(game, shield, event.get("source")):
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


def _applies_combat_to_and_by(game, event: dict) -> bool:
    """Whether either end of this combat damage event is shielded.

    Each end is asked with the direction it is on, so a "dealt **by**" shield
    stops the shielded creature's own damage without also stopping damage dealt
    *to* it — which is the difference between Gaseous Form and Demonic Torment,
    printed one word apart.
    """
    return bool(event.get("combat")) and (
        shields_combat_damage(event["recipient"], dealt_to=True)
        or shields_combat_damage(event.get("source"), dealt_to=False)
    )


# ---------------------------------------------------------------------------
# Shields
# ---------------------------------------------------------------------------
#
# The first two are turn-wide flags rather than shields a recipient holds, which
# is why they read a game flag and a permanent's marker instead of the
# collection: nothing is consumed, so there is no charge, no lifetime and no
# remaining-uses bookkeeping for a Shield to carry. Ebony Horse's also has to be
# readable off the damage's *source* ("dealt to and dealt by"), which a
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


@prevention_effect(COMBAT_SHIELD, applies=_applies_combat_to_and_by)
def _prevent_combat_damage_to_and_by(game, event: dict) -> PreventionOutcome | None:
    """Ebony Horse: "Prevent all combat damage that would be dealt to and dealt
    by that creature this turn." Both directions are one check here — the
    shielded creature may be either end of the event."""
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


def _log_color_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    game.log.append(
        f"Circle of Protection prevented {prevented} damage to "
        f"{event['recipient'].name} from a {used[0].color} source"
    )


@prevention_effect(COLOR_SHIELD, applies=_arms(PREVENT_FROM_COLOR, player_only=True))
def _circle_of_protection(game, event: dict) -> PreventionOutcome | None:
    """Circle of Protection: "The next time a <color> source of your choice
    would deal damage to you this turn, prevent that damage." One shield per
    activation, matched against the source's colors at damage time (CR 615.9)
    and prevented in full."""
    return _spend(game, event, PREVENT_FROM_COLOR, rider=_log_color_prevention)


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
_PREVENT_ALL_FROM_SOURCE_TYPE_RE = re.compile(
    r"^prevent all (?P<combat>combat )?damage that would be dealt to "
    r"(?P<subject>this|enchanted|equipped) "
    r"(?:artifact|creature|enchantment|land|permanent) by "
    r"(?P<source>"
    r"(?:artifact|creature|enchantment|land) (?:sources|creatures|artifacts|permanents)"
    r"|enchanted creatures"
    r"|walls"
    r"|creatures it's blocking"
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
}


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
    if wanted.get("blocked_by_recipient"):
        # "…by creatures **it's blocking**" (Wall of Shadows, Wall of Vapor).
        # The Wall is the blocker and the source is an attacker it was declared
        # against, so the relationship is read off combat rather than off
        # either object — and it is directional: a creature blocking the Wall
        # is not a creature the Wall is blocking.
        if not _recipient_is_blocking(game, recipient, source):
            return False
    return True


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
    """The source class and event narrowing one matched line describes."""
    wanted = _SOURCE_CLASSES.get(match.group("source"))
    if wanted is None:
        # A phrase the pattern admits with no class behind it would be a shield
        # against everything. Answering None keeps the card unsupported.
        return None
    return {**wanted, "combat_only": bool(match.group("combat"))}


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
        if wanted is not None:
            return wanted
    for attached in auras_attached_to(recipient):
        for line in attached.effective_card.oracle_text.splitlines():
            wanted = attached_prevent_all_from_source_type(line)
            if wanted is not None:
                return wanted
    return None


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


@prevention_effect(SOURCE_TYPE_BLANKET, applies=_applies_source_type_blanket)
def _prevent_all_from_source_type(game, event: dict) -> PreventionOutcome | None:
    source_type = _source_type_shielded_by(game, event)
    if source_type is None:
        return None
    recipient = event["recipient"]
    game.log.append(
        f"{recipient.card.name} prevented {event['amount']} damage "
        f"from an {source_type} source"
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
            permanent.metadata[counters_key(counter)] = have - removed
    if removed <= 0:
        return None
    game.log.append(
        f"{permanent.card.name} removed {removed} {counter} counter(s) to "
        f"prevent {removed} damage"
    )
    return PreventionOutcome(prevented=removed)


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
    )
