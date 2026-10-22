"""The replacement registry itself: each event kind's interceptor list, the
order space they are chosen from, and the CR 616.1 process an event runs
through (CR 614, CR 616).

``@replacement_effect`` registers an interceptor under an event kind with an
explicit ``order`` and raises at import on a duplicate within the kind, so the
orders are one table in one module: a new interceptor takes its slot here,
beside the reason each band sits where it does, whichever module of this
package holds the interceptor itself. ``apply_replacements`` runs an event's
contenders under CR 616.1 and ``replacement_candidates`` hands them to a caller
that contends them with something else — ``engine/damage_events.py``, which
unions the damage kinds with ``engine/prevention/``' shields.

The interceptors are the package's other modules, by what the event is; see
the package docstring for the index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..effect_ordering import (
    SUSPENDED,
    Candidate,
    affected_seat,
    apply_in_order,
    choose_effect,
)


@dataclass
class ReplacementOutcome:
    """What an interceptor did to the event.

    replaced   -- True: the event is consumed; the default action must not run.
    new_amount -- when set, the event continues with this amount (partial
                  replacement, e.g. "the next 1 damage ... instead").
    """

    replaced: bool = False
    new_amount: int | None = None


Interceptor = Callable[[Any, dict], Optional[ReplacementOutcome]]
Applicability = Callable[[Any, dict], bool]

REPLACEMENTS: dict[str, list[Candidate]] = {}

# ---------------------------------------------------------------------------
# Orders (CR 616.1's default choice)
# ---------------------------------------------------------------------------
#
# The damage-dealt kinds (CR 120.4b) share one space with
# engine/prevention/registry.py's shields, which sit at 10–600 there. Redirects go *before* the shields, for both
# recipients and for the same reason: a shield spent on damage that then leaves
# for someone else is a shield wasted on nothing. CR 616.1e permits either order;
# this is the default a non-interactive seat takes.
REDIRECT_WHOLE_EVENT = 1  # Jade Monolith, Veteran Bodyguard
REDIRECT_ONE_POINT = 2  # Personal Incarnation
SOURCE_TYPE_SHIELD = 3  # Desert Nomads / Camel
# The general recorded redirect (engine/damage_redirects.py) — Shimian Night
# Stalker, Nova Pentacle. Behind the two card-specific redirects above only
# because they were here first; no card in this pool puts two redirects on one
# recipient, and the day one does it wants a slot chosen on purpose rather than
# this one reused. Still ahead of every prevention shield (10-600 in
# engine/prevention/registry.py), for the reason stated above: a shield spent on damage
# that then leaves for someone else is a shield spent on nothing.
RECORDED_REDIRECT = 4
# "If an instant or sorcery source would deal 3 or more damage to you, it deals
# 2 damage to you instead." (Forethought Amulet.) A cap on the damage *dealt*
# (CR 120.4b), so it shares this space — and it goes **before** the prevention
# shields at 10-600 for the reason redirects do, read the other way round: a
# shield spent first absorbs its points from the printed damage and the cap then
# takes what is left down to 2 anyway, where the cap spent first leaves the
# shield its points for the next source. Six from a sorcery against "prevent the
# next 3" is 0 dealt with the cap first and 2 dealt with the shield first. CR
# 616.1e permits either; the default should not be the one that costs the player
# two life and a shield.
DAMAGE_SOURCE_CAP = 5  # Forethought Amulet
# "If a spell would deal damage to a permanent or player, it deals that much
# damage minus 1 to that permanent or player instead." (Benevolent Unicorn.)
# The same kind of effect as the cap above — CR 120.4b, the damage *dealt* —
# and beside it for the same reasons, one slot later only because a card
# printing both would want the cap applied to the printed number first.
DAMAGE_SOURCE_DELTA = 6  # Benevolent Unicorn, Sulfuric Vapors

# "For each 1 damage that would be dealt to you until your next upkeep, you
# remove an echo counter from this enchantment instead." (Soul Echo.) A
# **substitution** of the event rather than a change to its amount, which is
# why it sits after the two amount effects above and not beside them: how many
# counters come off is "for each 1 damage that would be dealt", so the number
# has to be the one the cap and the reduction have already settled. Two
# branches of one wave each claimed slot 6 for these, and the collision is real
# rather than cosmetic — this file compares orders across both registries and
# raises at import, which is what made the choice have to be made rather than
# merged.
#
# Ahead of the prevention shields at 10-600 all the same, for
# `DAMAGE_SOURCE_CAP`'s reason read once more: a shield spent first absorbs its
# points from the printed damage and this then takes the rest in counters
# anyway, where this spent first leaves the shield its points for the next
# source. CR 616.1e lets the affected player choose either; the default should
# not be the one that costs them a shield for nothing.
DAMAGE_TO_COUNTER_REMOVAL = 7  # Soul Echo
# "If damage would be dealt to this creature, put that many -1/-1 counters on
# it instead." (Lichenthrope; Phytohydra prints the same sentence with +1/+1.)
# CR 614's substitution read at the other end of the event from Soul Echo's:
# there a *player* spends counters to escape damage, here the damage **becomes**
# counters on the creature it was headed for. Beside it and one step later, for
# the same reason it sits after the cap and the reduction: how many counters
# arrive is "that many", so the number has to be the one every amount effect
# above has already settled.
#
# Ahead of the prevention shields at 10-600 for `DAMAGE_TO_COUNTER_REMOVAL`'s
# reason exactly, and the arithmetic is starker here: this consumes the whole
# event, so a shield spent first is a shield spent on damage that was never
# going to be marked. CR 616.1e lets the affected player choose either; the
# default should not be the one that costs them a shield for nothing.
DAMAGE_BECOMES_COUNTERS = 8  # Lichenthrope
# "If damage would be dealt to a player, that player exiles that many cards from
# the top of their library instead." (Crumbling Sanctuary.) The third of these
# substitutions and the widest: neither end of the event is narrowed, so it
# covers every player at the table, and what the damage becomes is a *cost paid
# out of a library* rather than a counter. Beside the two above and one step
# later for their reason — "that many" is the amount every effect at 5-6 has
# already settled — and ahead of the prevention shields at 10-600 for
# `DAMAGE_BECOMES_COUNTERS`' reason, which reads the same here: this consumes
# the whole event, so a shield spent first is spent on damage that was never
# going to be dealt.
DAMAGE_BECOMES_LIBRARY_EXILE = 9  # Crumbling Sanctuary
# "If any source would deal 1 or more damage to a permanent or player this
# turn, it deals 2 damage to that permanent or player instead." (Equal
# Treatment.) Forethought Amulet's cap (5) with no threshold worth the name and
# every source and recipient: the damage *dealt* becomes a printed number. Ahead
# of the points shields (40-600) for the cap's reason — a shield spent first
# absorbs from the printed damage and this then sets the rest to 2 anyway,
# where this first leaves the shield its points: 5 against "prevent the next
# 3" is 0 dealt this way round and 2 the other. Behind the "prevent all"
# blankets (0-13), against which the order cannot matter, because no slot
# below 10 is free and none is needed. Declared a CAP, so a multiplier it
# contends with goes first (``effect_ordering.choose_effect``): doubling a 2
# to 4 is not what the affected player would choose. CR 616.1e lets them
# choose either; this is the default for a seat nobody asks.
TURN_DAMAGE_BECOMES = 14  # Equal Treatment
# "If damage would be dealt to **you**, put that many delay counters on this
# enchantment instead." (Delaying Shield.) / "…exile that many cards from your
# graveyard instead. If you can't, you lose the game." (Nefarious Lich.) The
# same substitution as the three at 7-9 with one difference that moves it to
# the *other* side of the shields: what the damage becomes is a **price its
# own controller pays** — a counter that costs {1}{W} or a life at the next
# upkeep, a card out of a graveyard that may be the game — where a -1/-1
# counter and a card off a symmetric library were paid whether or not a shield
# was spent. CR 616.1e gives the choice to the affected player, and that
# player would take every point a Circle of Protection or a prevention pool
# stops before paying for the rest, so these sit **behind** every shield
# (10-660) and are asked only about what the shields let through.
#
# Ahead of the multipliers at 700-720, for the mirror of that argument: the
# price is "that many", and a player choosing the order pays for the printed
# damage rather than for double it.
#
# The Shield before the Lich: both consume the event, so a seat holding both
# takes one, and the default should be the one whose price can still be paid
# off rather than the one that can end the game on the spot.
DAMAGE_TO_YOU_BECOMES_COUNTERS = 670  # Delaying Shield
DAMAGE_BECOMES_GRAVEYARD_EXILE = 680  # Nefarious Lich

# …and multipliers go *after* the shields, at the far end of the shared space.
# CR 616.1e gives the choice to the affected player, and this is the order they
# would pick: a shield spent first absorbs its points from the printed damage,
# where a shield spent after the multiplier absorbs them from three times as
# much. "Prevent the next 3" against a tripled 3 is 0 dealt one way round and 6
# the other. The rule permits either; the default should not be the one that
# costs the player six life.
DAMAGE_MULTIPLIER = 700  # Fiery Emancipation
#: The turn-scoped doubling a spell arms (Blind Fury), one step later than the
#: static multiplier above. Its own order because it is its own effect: CR 616.1
#: counts effects, and sharing a number would make the two one contender and
#: silently drop whichever was asked second. Read off the turn's records
#: (``engine/turn_replacements.py``), as Equal Treatment's setter at 14 is.
COMBAT_DAMAGE_DOUBLER = 710  # Blind Fury
#: "…the next time that source would deal damage this turn, it deals **double**
#: that damage instead." (Desperate Gambit.) The third multiplier and the only
#: one that is *spent*: the two above are standing effects re-read off the board
#: at every event, and this one fires once and is gone
#: (``engine/next_damage.py``).
#:
#: Last of the three, and the slot is genuinely free rather than argued for:
#: multiplication commutes, so a source carrying this and a Fiery Emancipation
#: deals the same damage in either order, and both apply to the one event
#: whichever runs first. What the number does have to be is *distinct* — CR
#: 616.1 counts effects, and a shared order would make two contenders one and
#: drop whichever was asked second.
NEXT_DAMAGE_DOUBLED = 720  # Desperate Gambit

# The results kinds (CR 120.4c) have a space of their own. No shield lives there:
# prevention stops damage being *dealt*, and by 120.4c it already has been.
LIFE_FLOOR = 10  # Ali from Cairo

# Kinds with a contention set of their own. Small numbers, spaced, no relation
# to the damage space above.
LIFE_GAIN_TO_DRAW = 10  # Lich
EXILE_INSTEAD_OF_DYING = 10  # Disintegrate's "exile it instead"
#: "If the creature would leave the battlefield, exile it instead of putting it
#: anywhere else." (Dreams of the Dead.) Its own event kind rather than a wider
#: reading of ``would_die``: a death is one of the ways a permanent leaves, and
#: the other three — a hand, a library, an exile — reach no graveyard at all.
EXILE_INSTEAD_OF_LEAVING = 10  # Dreams of the Dead
RETURN_TO_HAND_INSTEAD_OF_DYING = 20  # Firestorm Phoenix
LIBRARY_TOP_INSTEAD_OF_DYING = 30  # Gravebane Zombie
DISCARD_DESTINATION = 10  # Library of Leng
# Before the Library's offer: both replace where a discarded card goes, and
# CR 616.1's default for a seat nobody asks is the battlefield.
DISCARD_TO_BATTLEFIELD = 5  # Dodecapod
# CR 702.35a's static ability: "If a player would discard this card, that
# player discards it, but exiles it instead of putting it into their
# graveyard." A third destination for a discarded card, between the two above.
# Ahead of the Library's offer, which is CR 616.1e's default for a seat nobody
# asks and the order the discarding player would choose: the exile is what
# offers the cheap cast, and after it the Library has no graveyard move left
# to replace. A card printing both madness and Dodecapod's sentence would meet
# Dodecapod first; none does.
DISCARD_INTO_EXILE = 7  # madness (Fiery Temper, Arrogant Wurm)
# Before the two draw replacements that *consume* the event, and for the
# player's benefit: a doubler applied first turns one draw into two, and the
# Lamp then replaces one of them, so the player gets both effects. The other
# way round the Lamp consumes the only draw there was and the doubler never
# applies — which CR 616.1e permits, and which is a card fewer.
DRAW_DOUBLED = 5  # Teferi's Ageless Insight
DRAW_FROM_OUTSIDE = 10  # Ring of Ma'rûf
# The general form of the two above, and beside them for that reason: a
# one-shot the player armed for their own benefit, replacing the draw with
# something the ability names. Its own slot rather than a shared one --
# CR 616.1 counts *effects*, and two contenders on one number would be one
# contender with the second silently dropped -- and between them rather than
# after, because no card in the pool prints two of the three and CR 616.1e
# would put the choice to the affected player if one ever did.
DRAW_ARMED_REPLACEMENT = 15  # Mangara's Tome
DRAW_LOOKING_AT_TOP = 20  # Aladdin's Lamp
# An **optional** replacement its own controller armed for their own benefit
# (CR 109.5: "If **you** would draw a card"), so it belongs with the three above
# rather than with the mandatory consumers below - and behind all of them,
# because it consumes the draw where they hand something back. A draw a Lamp or
# a Ring has already taken away never puts this question, which is the order the
# drawing player would choose and CR 616.1e permits. Being optional, the number
# matters less than for its mandatory neighbours: declining leaves the event for
# whatever is behind it, exactly as Pursuit of Knowledge's does four slots on.
DRAW_REVEALS_UNTIL_KIND = 21  # Abundance
# Last of the draw replacements, and deliberately so. CR 616.1e gives the choice
# to the affected player and the lowest order is the default they are taken to
# make; every effect above this one is something the player armed for their own
# benefit, and this one takes the draw away. Applying a Ring of Ma'rûf or an
# Aladdin's Lamp first consumes the draw and this never applies — which is the
# order the player would pick, and the rule permits.
# An **optional** consuming replacement, and the only one here: "you *may* put
# a study counter on this enchantment instead" is a decision its own controller
# makes about their own draw (CR 109.5). Before the four mandatory consumers
# below and after everything the player armed, which is the same CR 616.1e
# argument they make: a draw a Lamp has already taken away never puts this
# question, and the affected player is exactly the one who would choose that
# order. Being optional, the number matters less than for its neighbours -
# declining leaves the event for whatever is behind it.
DRAW_BECOMES_COUNTER = 25  # Pursuit of Knowledge
# Beside it and for its reason exactly: the second optional consuming
# replacement, a decision its own controller makes about their own draw. After
# Pursuit, because that one hands something back for the draw it takes and this
# one hands back nothing — the order a player holding both would choose, which
# CR 616.1e permits. Declining either leaves the event for whatever is behind.
DRAW_MAY_BE_SKIPPED = 26  # Obstinate Familiar
# "Until end of turn, if target player would draw a card, instead that player
# skips that draw and you draw a card." (Plagiarize.) A mandatory consuming
# replacement another player armed, so behind everything the drawing player
# armed for their own benefit (5-26) for the argument the slots below make —
# and ahead of the four mandatory consumers that cost the drawing player
# something more than the card: under Chains of Mephistopheles the draw would
# become a discard first and the card *it* draws would then go to the
# Plagiarist anyway, and Forbidden Crypt can end the game, where this only
# takes the draw. CR 616.1e lets the drawing player choose; this is the default
# for a seat nobody asks.
DRAW_GIVEN_TO_ANOTHER = 29  # Plagiarize
DRAW_DISCARD_INSTEAD = 30  # Chains of Mephistopheles
# Beside it, and last for the same reason: this one takes the draw away too.
# Between the two the order is arbitrary — no card in the pool prints both, and
# CR 616.1e would put the choice to the affected player if one ever did — so
# they are ordered by the number that keeps each of them behind every
# replacement the player armed for their own benefit.
DRAW_REVEALS_TOP = 31  # Enduring Renewal
# The third of the three, and the same reasoning again: it takes the draw away
# unless somebody buys it back. It goes behind the other two because it is the
# only one that asks a *different* seat a question — a draw already consumed by
# a Lamp or a Renewal never puts that question, which is the ordering the
# drawing player would choose and the rule permits.
DRAW_REVEALED_UNLESS_PAID = 32  # Zur's Weirding
# The fourth of the consuming draw replacements, and last of them on purpose.
# CR 616.1e's default is the lowest order, and this is the only replacement in
# the engine that can **lose the affected player the game**: with an empty
# graveyard Forbidden Crypt's second sentence ends the game on the spot. A Lamp,
# a Renewal or a Weirding applied first consumes the draw and this never
# applies, which is the order the drawing player would pick and the rule
# permits.
DRAW_RETURNS_FROM_GRAVEYARD = 33  # Forbidden Crypt
# Last of the draw replacements, and the only one here that does **not** consume
# the draw: "instead they draw a card and reveal it" still draws (CR 614.1
# replaces the event with a modified one). So it is a rider, and its order is
# the same CR 616.1e argument the four above make from the other side — every
# consuming replacement is one the drawing player would rather have applied,
# because a draw a Lamp or a Renewal has already taken away never reaches this
# rider at all. Being last is what lets them.
DRAW_REVEALED_AND_TAXED = 34  # Breathstealer's Crypt
EXTRA_PLUS1_COUNTER = 10  # Conclave Mentor
EXILE_INSTEAD_OF_ENTERING = 10  # Containment Priest
# Before it, and before every other entry replacement. CR 614.17c: an event that
# **can't** happen may only be replaced by a self-replacement effect, so nothing
# else in the contention set is allowed to modify it — being asked first is how
# a prohibition that is not itself a replacement effect keeps that promise here.
LANDS_CANT_ENTER = 0  # Worms of the Earth
# Between the two: an entry cost the controller cannot pay refuses the entry the
# way Containment Priest's exile does, so it belongs with the consuming
# replacements rather than with the rider below. After Containment Priest
# because that one removes the entry outright - a creature exiled as it would
# enter never had an entry cost to fail to pay.
UNPAYABLE_ENTRY_COST = 15  # Frankenstein's Monster
# Beside it, and the same kind of effect one sentence apart: an entry toll the
# controller has nothing to pay with refuses the entry the way the exile above
# does. After it only because two entry costs on one permanent is a shape no
# card prints, so the slot is free rather than chosen - CR 616.1e would put the
# choice to the affected player if one ever did.
UNPAYABLE_ENTRY_SACRIFICE = 16  # the Alliances sac lands
# Beside it, and the same paragraph with an **optional** toll out of a hand
# (Mox Diamond). After the two above only because nothing prints two entry
# tolls on one permanent, so the slot is free rather than chosen - CR 616.1e
# would put the choice to the affected player if one ever did.
OPTIONAL_ENTRY_DISCARD = 17  # Mox Diamond
# After it, and it has to be: the exile replacement means the permanent never
# enters, and a rider hung on an entry that did not happen is a sacrifice for
# nothing.
SACRIFICE_AFTER_ENTERING = 20  # Land Equilibrium
COUNTERS_REMOVED_INSTEAD_OF_UNTAPPING = 10  # Freyalise's Winds
# After it, and only because nothing prints both: Freyalise's Winds spends a
# counter and leaves the permanent on the battlefield, so a land that has
# already gone to its owner's hand has no counter left to remove. CR 616.1e
# would put the choice to the affected player if a card ever printed the pair.
RETURNED_TO_HAND_INSTEAD_OF_UNTAPPING = 11  # Undiscovered Paradise
# CR 106.12b's kind: what a land produces is decided while its mana ability is
# resolving. One slot, because ``engine/land_mana_swaps.py`` answers "what does
# this land make instead?" for every producer of the effect at once — a
# battlefield static (Ritual of Subdual), a per-seat record (Deep Water) and a
# per-permanent one (Quarum Trench Gnomes) all reduce to a single symbol, and
# the payment planner has to be able to ask the same question without applying
# anything.
LAND_MANA_SUBSTITUTION = 10  # Ritual of Subdual, Infernal Darkness, Deep Water
#: "If a card would be put into your graveyard from anywhere, exile that card
#: instead." (Forbidden Crypt.) Its own event kind, over the seam every path
#: into a graveyard now runs through (``Game.put_card_into_graveyard``) — not a
#: widening of ``would_die``, which is one of the ways a card reaches a
#: graveyard and says nothing about a discard, a mill or a spell finishing on
#: the stack.
EXILE_INSTEAD_OF_GRAVEYARD = 10  # Forbidden Crypt
# "If Legacy Weapon would be put into a graveyard from anywhere, reveal Legacy
# Weapon and shuffle it into its owner's library instead." Behind the exile only
# as CR 616.1e's default for a seat that is not asked — the two are one
# contention set and the affected player chooses between them (the CR's own
# example under 616.1f is this pair) — and the exile is the default because it
# is the one a *different* permanent's controller put there on purpose.
SHUFFLE_INSTEAD_OF_GRAVEYARD = 20  # Legacy Weapon

# Set on the event once an interceptor consumes it. It lives on the payload
# because the payload is the one piece of state the 616.1 loop threads through
# every candidate — and it is popped by the entry points below, so it never
# escapes to a caller.
REPLACED = "_replaced"


def replacement_effect(
    kind: str, order: int, *, applies: Applicability, redirects: bool = False,
    prevents: bool = False,
    amount_role: str = "",
) -> Callable[[Interceptor], Interceptor]:
    """Register an interceptor for an event kind.

    ``applies`` answers "would this effect apply to this event?" and is
    **required**: CR 616.1 has to count the effects in contention before running
    any of them, which an interceptor that answers by applying itself makes
    impossible. It must be pure.

    A duplicate order within a kind raises at import, matching ``@parse_rule``
    and ``@prevention_effect``: with the default choice being the lowest order,
    a collision is a real ambiguity about which effect replaces the event first.
    """

    def decorator(fn: Interceptor) -> Interceptor:
        registered = REPLACEMENTS.setdefault(kind, [])
        for existing in registered:
            if existing.order == order:
                raise ValueError(
                    f"replacement_effect({kind!r}) order {order} already used by "
                    f"{existing.key}; pick a free slot"
                )
        registered.append(
            Candidate(key=fn.__name__, order=order, applies=applies, apply=fn,
                      label=(fn.__doc__ or fn.__name__).split(":")[0].strip(),
                      # CR 614.9: this one *moves* the damage rather than
                      # changing it, which is the half of Whippoorwill's clause
                      # a replacement can be. Declared here so a new redirect
                      # cannot quietly escape the lock.
                      #
                      # *prevents* is the other half, for the one interceptor
                      # in this package that is CR 615 prevention printed as
                      # such ("Prevent all damage that would be dealt to this
                      # creature by Deserts", ``damage.py``) and registered in
                      # this registry for its text-keyed guard. It was declared ``redirects=True`` to
                      # get under the same lock, which was right about the lock
                      # and wrong about the word; "the damage can't be
                      # prevented" (Urza's Rage) needs the two apart.
                      prevents_or_redirects=redirects or prevents,
                      prevents=prevents,
                      # CR 616.1e's default needs to know a cap from a
                      # multiplier (`effect_ordering.choose_effect`).
                      amount_role=amount_role)
        )
        registered.sort(key=lambda candidate: candidate.order)
        return fn

    return decorator


def _record(game, event: dict, interceptor: Interceptor) -> None:
    """Apply one interceptor and fold its outcome into the event, so the next
    round of CR 616.1f asks the rest about what is actually left."""
    outcome = interceptor(game, event)
    if outcome is None:
        return
    if outcome.new_amount is not None:
        event["amount"] = outcome.new_amount
    if outcome.replaced:
        event[REPLACED] = True


def replacement_candidates(kind: str) -> list[Candidate]:
    """*kind*'s interceptors as CR 616.1 candidates, with the outcome bookkeeping
    already wired into ``apply``.

    The counterpart of ``prevention.registry.shield_candidates``: a damage event's
    contenders are both lists together, and neither caller should have to
    re-implement what applying one does to the event.
    """
    return [
        Candidate(
            key=c.key, order=c.order, applies=c.applies, label=c.label,
            apply=lambda g, e, fn=c.apply: _record(g, e, fn),
            prevents_or_redirects=c.prevents_or_redirects,
            prevents=c.prevents,
            amount_role=c.amount_role,
        )
        for c in REPLACEMENTS.get(kind, ())
    ]


def was_replaced(game, event: dict) -> bool:
    """Whether the event has been consumed — nothing further can modify what no
    longer happens, so this is the 616.1 loop's stop condition."""
    return bool(event.get(REPLACED))


def take_replaced(event: dict) -> bool:
    """Read and clear the consumed flag, so the marker never escapes to a
    caller reading the payload it passed in."""
    return bool(event.pop(REPLACED, False))


def order_prompt_asker(kind: str, restart: Callable[[], Any]) -> Callable:
    """An ``ask`` hook for :func:`~engine.effect_ordering.apply_in_order` that
    puts CR 616.1e's choice to the affected player.

    *restart* re-runs the whole event once the answer arrives. It has to be the
    caller's own re-invocation, not a resumption of this process: an event is
    more than its replacements — a draw that nothing replaces still has to draw
    — so only the caller knows what "do this event again" means. Nothing has
    been applied when the prompt is queued, so re-running is exact rather than
    approximate.

    A non-interactive seat answers immediately with the default, so AI and
    headless play never queue and never suspend.
    """

    def ask(game, chooser_index, applicable):
        recorded = _recorded_order(game, kind, chooser_index)
        if recorded is not None:
            by_key = {c.key: c for c in applicable}
            for key in recorded:
                if key in by_key:
                    return by_key[key]
            return choose_effect(game, chooser_index, applicable)
        if chooser_index is None or chooser_index not in game.interactive_seats:
            return choose_effect(game, chooser_index, applicable)
        game.arm_pending_choice(
            "effect_order",
            chooser_index,
            event_kind=kind,
            options=[c.label or c.key for c in applicable],
            _keys=[c.key for c in applicable],
            _restart=restart,
        )
        game.log.append(
            f"{game.players[chooser_index].name} must choose which effect applies "
            f"first ({', '.join(c.label or c.key for c in applicable)})"
        )
        # Arming stopped the loop this event was a step of, so it does not run on
        # past a step that has not happened: ``effect_order`` is registered
        # ``suspends`` (engine/pending_choices.py, engine/resumption.py).
        return SUSPENDED

    return ask


def _recorded_order(game, kind: str, seat: int | None) -> tuple[str, ...] | None:
    return getattr(game, "effect_order_answers", {}).get((kind, seat))


def apply_replacements(
    game, kind: str, payload: dict, *, restart: Callable[[], Any] | None = None
) -> tuple[bool, dict]:
    """Run *kind*'s interceptors over the event under CR 616.1.

    Returns ``(consumed, payload)`` — when ``consumed`` is True the caller
    must skip the default action; otherwise ``payload["amount"]`` may have
    been reduced by partial replacements.

    Pass *restart* — a thunk that re-runs the whole event — to let CR 616.1e's
    choice be **asked** when more than one effect applies. Passing it is the
    caller declaring "this event can suspend": the answer arrives on a later
    request, so the caller must be able to report the event as taken care of
    and let the restart finish it. A suspended event reports ``consumed`` True
    for exactly that reason.

    Callers that cannot suspend simply do not pass it, and every seat takes the
    documented default. That is not a second code path so much as a missing
    capability, stated at the one place that knows whether it exists.

    Damage events should go through ``engine/damage_events.py`` instead, which
    contends these against the event's prevention shields as one set.
    """
    seat = affected_seat(game, payload.get("recipient") or payload.get("player"))
    trace = apply_in_order(
        game,
        payload,
        replacement_candidates(kind),
        chooser_index=seat,
        stop=was_replaced,
        ask=None if restart is None else order_prompt_asker(kind, restart),
    )
    if trace.suspended:
        # Nothing was applied and a prompt is queued. "Consumed" is the honest
        # answer to the caller's only question — do not carry out the default
        # action — and the restart will run the event properly.
        take_replaced(payload)
        return True, payload
    if trace.applied:
        getattr(game, "effect_order_answers", {}).pop((kind, seat), None)
    return take_replaced(payload), payload
