"""Replacement-effect registry (CR 614).

"If X would happen, do Y instead" effects intercept an event before the
default action applies. Each event kind has an ordered interceptor list; an
interceptor inspects the game/payload and either passes (returns None),
modifies the event amount, or consumes the event entirely (the default action
does not happen).

Interceptors self-select from game state (metadata flags, oracle-text
probes), so the registry stays name-free — bespoke per-card registration
belongs in engine/card_hooks.py.

Event kinds and their payload keys:

- ``life_gain``:          {player, amount, source_name}
- ``damage_to_creature``: {recipient, amount, source, combat}
- ``damage_to_player``:   {recipient, amount, source, combat}
- ``damage_marked``:      {recipient, amount, dealt, source, combat}
- ``life_loss``:          {recipient, amount, dealt, source, combat}
- ``would_die``:          {player, permanent}
- ``discard``:            {player, card}
- ``draw``:               {player, count, drawn}

``discard`` and ``draw`` are *interactive*: their interceptors offer a
:class:`~engine.replacement_choices.ReplacementChoice` rather than applying
the effect outright, and report what they did through ``payload["drawn"]``.

The four damage kinds spell their subject ``recipient`` rather than
``permanent``/``player`` because a damage event is *one* event shared with
engine/prevention.py — see the ordering note below.

**A damage event has two halves, and they are different kinds** (CR 120.4).
First damage is *dealt*, as modified by the effects that interact with damage
— shields and redirects (120.4b). Then the damage that was dealt is *processed
into its results*, as modified by the effects that interact with those results
(120.4c): life lost for a player, damage marked for a creature. So
``damage_to_player`` and ``damage_to_creature`` are the first half, ``life_loss``
and ``damage_marked`` the second.

That is not a distinction for its own sake. Ali from Cairo — "damage that would
reduce your life total to less than 1 reduces it to 1 instead" — modifies the
*result*, so the damage is still dealt in full: lifelink gains the full amount
(CR 120.3f) and a "whenever ~ deals damage to a player" trigger sees the full
amount, while only the life loss is capped. Collapsing the two halves into one
number is what forced the combat damage step to run its shields and its
replacements at two different moments for years.

**Ordering (CR 616.1).** Interceptors do not run as a fixed chain. Each carries
an ``applies`` predicate and an ``order``, and ``engine/effect_ordering.py``
gathers everything applicable, applies one, then re-asks the rest against what
is now true (616.1f). The predicate is the guard the interceptor used to open
with, *moved* rather than copied, so the body starts after the decision and the
two cannot drift; and it must be pure, because an effect that is asked about may
then not be chosen.

Order is a per-kind space — two kinds are never in contention — with one
exception that matters. CR 616.1 does not separate replacement from prevention:
a damage event's replacements and its shields are *one* contention set. So the
two damage kinds share an order space with ``engine/prevention.py``, and
``engine/damage_events.py`` is where the union is formed and where a collision
between the two registries raises at import.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .effect_ordering import (
    SUSPENDED,
    Candidate,
    affected_seat,
    apply_in_order,
    choose_effect,
)
from .damage_redirects import (
    DamageRedirect,
    _is_permanent,
    applicable_redirect,
    drop_spent,
    live_recipient,
)
from .hand_locks import lock_card_in_hand
from .search_filters import card_has_type
from .models import PlayerState
from .replacement_choices import (
    ReplacementChoice,
    offer_replacement_choice,
    replacement_choice,
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
# The damage-dealt kinds (CR 120.4b) share one space with engine/prevention.py's
# shields, which sit at 10–600 there. Redirects go *before* the shields, for both
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
# engine/prevention.py), for the reason stated above: a shield spent on damage
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

# …and multipliers go *after* the shields, at the far end of the shared space.
# CR 616.1e gives the choice to the affected player, and this is the order they
# would pick: a shield spent first absorbs its points from the printed damage,
# where a shield spent after the multiplier absorbs them from three times as
# much. "Prevent the next 3" against a tripled 3 is 0 dealt one way round and 6
# the other. The rule permits either; the default should not be the one that
# costs the player six life.
DAMAGE_MULTIPLIER = 700  # Fiery Emancipation

# The results kinds (CR 120.4c) have a space of their own. No shield lives there:
# prevention stops damage being *dealt*, and by 120.4c it already has been.
LIFE_FLOOR = 10  # Ali from Cairo

# Kinds with a contention set of their own. Small numbers, spaced, no relation
# to the damage space above.
LIFE_GAIN_TO_DRAW = 10  # Lich
EXILE_INSTEAD_OF_DYING = 10  # Disintegrate's "exile it instead"
RETURN_TO_HAND_INSTEAD_OF_DYING = 20  # Firestorm Phoenix
DISCARD_DESTINATION = 10  # Library of Leng
# Before the two draw replacements that *consume* the event, and for the
# player's benefit: a doubler applied first turns one draw into two, and the
# Lamp then replaces one of them, so the player gets both effects. The other
# way round the Lamp consumes the only draw there was and the doubler never
# applies — which CR 616.1e permits, and which is a card fewer.
DRAW_DOUBLED = 5  # Teferi's Ageless Insight
DRAW_FROM_OUTSIDE = 10  # Ring of Ma'rûf
DRAW_LOOKING_AT_TOP = 20  # Aladdin's Lamp
# Last of the draw replacements, and deliberately so. CR 616.1e gives the choice
# to the affected player and the lowest order is the default they are taken to
# make; every effect above this one is something the player armed for their own
# benefit, and this one takes the draw away. Applying a Ring of Ma'rûf or an
# Aladdin's Lamp first consumes the draw and this never applies — which is the
# order the player would pick, and the rule permits.
DRAW_DISCARD_INSTEAD = 30  # Chains of Mephistopheles
# Beside it, and last for the same reason: this one takes the draw away too.
# Between the two the order is arbitrary — no card in the pool prints both, and
# CR 616.1e would put the choice to the affected player if one ever did — so
# they are ordered by the number that keeps each of them behind every
# replacement the player armed for their own benefit.
DRAW_REVEALS_TOP = 31  # Enduring Renewal
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
# After it, and it has to be: the exile replacement means the permanent never
# enters, and a rider hung on an entry that did not happen is a sacrifice for
# nothing.
SACRIFICE_AFTER_ENTERING = 20  # Land Equilibrium
COUNTERS_REMOVED_INSTEAD_OF_UNTAPPING = 10  # Freyalise's Winds

# Set on the event once an interceptor consumes it. It lives on the payload
# because the payload is the one piece of state the 616.1 loop threads through
# every candidate — and it is popped by the entry points below, so it never
# escapes to a caller.
REPLACED = "_replaced"


def replacement_effect(
    kind: str, order: int, *, applies: Applicability, redirects: bool = False
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
                      prevents_or_redirects=redirects)
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

    The counterpart of ``prevention.shield_candidates``: a damage event's
    contenders are both lists together, and neither caller should have to
    re-implement what applying one does to the event.
    """
    return [
        Candidate(
            key=c.key, order=c.order, applies=c.applies, label=c.label,
            apply=lambda g, e, fn=c.apply: _record(g, e, fn),
            prevents_or_redirects=c.prevents_or_redirects,
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


# ---------------------------------------------------------------------------
# LEA interceptors
# ---------------------------------------------------------------------------

# The oracle phrases these interceptors self-select on. Named constants rather
# than inline literals because a second reader now needs the *exact* string:
# engine/grammar/registries.py claims these lines for the grammar on the
# strength of this file implementing them. A copy over there would be free to
# drift, and a drifted copy would claim a line nothing implements — the silence
# the grammar's full-consumption invariant exists to remove.
LIFE_GAIN_TO_DRAW_TEXT = "if you would gain life, draw that many cards instead"
DAMAGE_LIFE_FLOOR_TEXT = (
    "damage that would reduce your life total to less than 1 reduces it to 1 instead"
)
EXTRA_PLUS1_COUNTER_TEXT = (
    "if one or more +1/+1 counters would be put on a creature you control, "
    "that many plus one +1/+1 counters are put on that creature instead"
)
TRIPLE_DAMAGE_TEXT = (
    "if a source you control would deal damage to a permanent or player, "
    "it deals triple that damage to that permanent or player instead"
)
DOUBLE_DRAW_TEXT = (
    "if you would draw a card except the first one you draw in each of your "
    "draw steps, draw two cards instead"
)


def _applies_life_gain_to_draw(game, payload: dict) -> bool:
    return game._player_controls_text(payload["player"], LIFE_GAIN_TO_DRAW_TEXT)


def _applies_extra_plus1_counter(game, payload: dict) -> bool:
    player = payload.get("player")
    return player is not None and game._player_controls_text(
        player, EXTRA_PLUS1_COUNTER_TEXT
    )


@replacement_effect(
    "plus1_counters", EXTRA_PLUS1_COUNTER, applies=_applies_extra_plus1_counter
)
def _one_more_plus1_counter(game, payload: dict) -> ReplacementOutcome | None:
    """Conclave Mentor: "If one or more +1/+1 counters would be put on a
    creature you control, that many plus one +1/+1 counters are put on that
    creature instead."

    A *modifying* replacement, not a consuming one: the event still happens,
    with a bigger number. Returning ``new_amount`` would be the shape damage
    uses, but this event's quantity is ``count`` — so the payload is written
    directly and nothing is consumed, which is also what keeps a second
    Mentor from being skipped (CR 616.1f re-asks the rest against the raised
    count, and each applies once).
    """
    payload["count"] = int(payload.get("count", 0)) + 1
    permanent = payload.get("permanent")
    name = getattr(getattr(permanent, "card", None), "name", "a creature")
    game.log.append(f"{name} gets one more +1/+1 counter (Conclave Mentor)")
    return ReplacementOutcome()


@replacement_effect("life_gain", LIFE_GAIN_TO_DRAW, applies=_applies_life_gain_to_draw)
def _draw_instead_of_life_gain(game, payload: dict) -> ReplacementOutcome | None:
    """Lich: "If you would gain life, draw that many cards instead."

    The draw this creates is a draw like any other, so it goes back through the
    draw replacements (CR 616.2: an effect can become applicable *because*
    another replacement modified the event). This pairing is the rule's own
    worked example, and taking cards off the library directly would silently
    skip a Ring of Ma'rûf or an Aladdin's Lamp the player had armed.
    """
    player = payload["player"]
    amount = payload["amount"]
    drawn = game._draw_with_replacements(player, amount)
    source = f" from {payload['source_name']}" if payload.get("source_name") else ""
    game.log.append(
        f"{player.name} would gain {amount} life{source}; drew {drawn} card(s) instead (Lich)"
    )
    return ReplacementOutcome(replaced=True)


def _floored_amount(game, payload: dict) -> int | None:
    """How much life this damage would still cost once the floor applies, or
    None when the floor has nothing to do. Shared by the predicate and the
    interceptor so "does the floor apply" and "what does it floor to" have one
    answer."""
    recipient = payload["recipient"]
    amount = payload["amount"]
    if amount <= 0 or not game._player_controls_text(recipient, DAMAGE_LIFE_FLOOR_TEXT):
        return None
    floor_amount = max(0, recipient.life - 1)
    return None if floor_amount >= amount else floor_amount


def _applies_life_floor(game, payload: dict) -> bool:
    return _floored_amount(game, payload) is not None


@replacement_effect("life_loss", LIFE_FLOOR, applies=_applies_life_floor)
def _floor_life_at_one(game, payload: dict) -> ReplacementOutcome | None:
    """Ali from Cairo: "Damage that would reduce your life total to less than
    1 reduces it to 1 instead."

    A CR 120.4c effect — it modifies the damage's *result*, not the damage. The
    damage is dealt in full, so lifelink gains the full amount (CR 120.3f) and a
    "deals damage to a player" trigger sees the full amount; only the life loss
    is capped. ``payload["dealt"]`` is that full amount, kept beside the life
    loss so the difference is readable rather than lost.
    """
    return ReplacementOutcome(new_amount=_floored_amount(game, payload))


VETERAN_BODYGUARD_TEXT = (
    "all damage that would be dealt to you by unblocked creatures is dealt to "
    "this creature instead"
)

#: "As long as this creature is untapped, all damage that would be dealt to you
#: by **<source class>** is dealt to this creature instead." Veteran Bodyguard
#: says "unblocked creatures"; Martyrs of Korlis says "artifacts". One
#: redirection with the class as data, because the two sentences differ in
#: nothing else — and the untapped condition is part of the printed line rather
#: than a separate static, which is why it is matched here and not asked
#: elsewhere.
_REDIRECT_TO_SELF = re.compile(
    r"^as long as this creature is untapped, all damage that would be dealt to "
    r"you by (?P<source_class>unblocked creatures|artifacts|creatures) is dealt "
    r"to this creature instead$"
)


def redirect_to_self_source_class(line: str) -> str | None:
    """The class of source *line* redirects, or None if it is not that line.

    One matcher, asked by the interceptor and by the claim reader, so what is
    redirected and what is claimed cannot drift.
    """
    return _match_group(_REDIRECT_TO_SELF, line, "source_class")


#: "If an **instant or sorcery** source would deal **3** or more damage to you,
#: it deals **2** damage to you instead." (Forethought Amulet.) All three of the
#: bold parts are payload, for the reason every parameter in this engine is: a
#: card printing a different source class, threshold or cap is the same
#: sentence. The class is spelled as the card spells it and split on "or" below,
#: so "an artifact source" and "an instant or sorcery source" are one row.
_SOURCE_DAMAGE_CAP = re.compile(
    r"^if an? (?P<source_class>[a-z ]+?) source would deal (?P<threshold>\d+) or "
    r"more damage to you, it deals (?P<capped>\d+) damage to you instead$"
)


def source_damage_cap(line: str) -> tuple[tuple[str, ...], int, int] | None:
    """``(source types, threshold, capped amount)`` *line* imposes, or None.

    One matcher, asked by the interceptor below and by
    :func:`replacement_claims_line`, so what is capped and what is claimed
    cannot drift. The types come back as a tuple because the printed class may
    name several ("an instant or sorcery source") and every one of them answers
    the class.
    """
    match = _SOURCE_DAMAGE_CAP.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    types = tuple(
        word.strip() for word in match.group("source_class").split(" or ") if word.strip()
    )
    # A class naming no readable type refuses the line rather than capping
    # everything: `source_has_type` answers False for a word it does not know,
    # so an unread class would be a cap that never fires — the silent shape this
    # module's claim reader exists to keep out of the supported pool.
    if not types:
        return None
    return types, int(match.group("threshold")), int(match.group("capped"))


def _capped_source_damage(game, payload: dict) -> int | None:
    """The amount a printed source cap would leave, or None when none applies.

    Both the applicability predicate and the effect call this, which is what
    keeps applicability *pure* (CR 616.1f re-asks the contenders after each
    applied effect, so an effect that answered "do I apply?" by applying itself
    would make them uncountable).
    """
    from .prevention import source_has_type

    recipient = payload["recipient"]
    amount = payload["amount"]
    source = payload.get("source")
    if amount <= 0 or not hasattr(recipient, "life"):
        return None
    best: int | None = None
    for permanent in game.controlled_by(recipient):
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            read = source_damage_cap(line)
            if read is None:
                continue
            types, threshold, capped = read
            if amount < threshold or capped >= amount:
                continue
            if not any(source_has_type(game, source, word) for word in types):
                continue
            best = capped if best is None else min(best, capped)
    return best


def _applies_source_damage_cap(game, payload: dict) -> bool:
    return _capped_source_damage(game, payload) is not None


@replacement_effect(
    "damage_to_player", DAMAGE_SOURCE_CAP, applies=_applies_source_damage_cap
)
def _cap_damage_from_source_class(game, payload: dict) -> ReplacementOutcome | None:
    """Forethought Amulet: "If an instant or sorcery source would deal 3 or more
    damage to you, it deals 2 damage to you instead."

    A CR 120.4b effect — it changes the damage *dealt*, not its result, so the
    capped number is what lifelink gains and what a "deals damage to a player"
    trigger sees. That is the difference from Ali from Cairo two entries up,
    which caps the life lost and leaves the damage whole.

    "To you" is the Amulet's controller (CR 109.5), which is why the scan is over
    the recipient's own battlefield: an opponent's Amulet does nothing for the
    player being burned.
    """
    capped = _capped_source_damage(game, payload)
    game.log.append(
        f"{payload['recipient'].name} takes {capped} damage instead of "
        f"{payload['amount']} (source cap)"
    )
    return ReplacementOutcome(new_amount=capped)


def _match_group(pattern, line: str, group: str) -> str | None:
    match = pattern.match(" ".join((line or "").strip().lower().rstrip(".").split()))
    return match.group(group) if match is not None else None


def _source_answers_class(game, source, source_class: str) -> bool:
    """Whether *source* is in the class a redirect names."""
    if source_class == "unblocked creatures":
        return _unblocked_attacker(source)
    from .prevention import source_has_type

    return source_has_type(game, source, source_class.rstrip("s"))


def _unblocked_attacker(source) -> bool:
    """Whether *source* is an unblocked attacking creature (CR 509.1h).

    Delegated to ``handlers/_common.unblocked_attacker``, which is the same word
    the ``unblocked_only`` filter key answers to — Kjeldoran Royal Guard prints
    Veteran Bodyguard's source class with a duration on it, so the static read
    here and the recorded redirect's filter must not be two readings.
    """
    from .handlers._common import unblocked_attacker

    return unblocked_attacker(source)


def _protecting_bodyguard(game, payload: dict):
    """The untapped permanent that would take this damage instead, or None.

    Veteran Bodyguard and Martyrs of Korlis are one effect with different
    source classes, so the class is read off each candidate's own line and
    checked against the damage's source — rather than one card's sentence being
    a constant and the other needing a second interceptor.
    """
    if payload["amount"] <= 0:
        return None
    for permanent in game.controlled_by(payload["recipient"]):
        if permanent.tapped:
            continue
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            source_class = redirect_to_self_source_class(line)
            if source_class is None:
                continue
            if _source_answers_class(game, payload.get("source"), source_class):
                return permanent
    return None


def _applies_bodyguard_redirect(game, payload: dict) -> bool:
    return _protecting_bodyguard(game, payload) is not None


@replacement_effect(
    "damage_to_player", REDIRECT_WHOLE_EVENT, applies=_applies_bodyguard_redirect, redirects=True
)
def _redirect_damage_to_bodyguard(game, payload: dict) -> ReplacementOutcome | None:
    """Veteran Bodyguard: "As long as this creature is untapped, all damage that
    would be dealt to you by unblocked creatures is dealt to this creature
    instead."

    All damage, not all combat damage — an unblocked attacker's activated ability
    is redirected too, which reading the source's combat state gets right for
    free. Ordered before the shields protecting the player, because a shield
    spent here would be spent on damage that is about to become the creature's.
    """
    bodyguard = _protecting_bodyguard(game, payload)
    recipient = payload["recipient"]
    game._mark_damage_on_permanent(
        bodyguard,
        payload["amount"],
        source=payload.get("source"),
        combat=bool(payload.get("combat")),
    )
    game.log.append(
        f"{bodyguard.card.name} takes {payload['amount']} damage instead of "
        f"{recipient.name} (redirect)"
    )
    return ReplacementOutcome(replaced=True)


def _jade_monolith_seat(game, payload: dict) -> int | None:
    """The seat Jade Monolith's redirect would send this damage to, or None when
    it does not apply — the chosen source has to match, and an unrecorded choice
    matches anything (legacy / AI activations)."""
    recipient = payload["recipient"]
    if payload["amount"] <= 0:
        return None
    seat = recipient.metadata.get("redirect_damage_to_player")
    if not (isinstance(seat, int) and 0 <= seat < len(game.players)):
        return None
    chosen_source = recipient.metadata.get("redirect_damage_source")
    if not game._damage_source_matches(chosen_source, payload.get("source")):
        return None
    return seat


def _applies_jade_monolith(game, payload: dict) -> bool:
    return _jade_monolith_seat(game, payload) is not None


@replacement_effect(
    "damage_to_creature", REDIRECT_WHOLE_EVENT, applies=_applies_jade_monolith, redirects=True
)
def _redirect_damage_to_player(game, payload: dict) -> ReplacementOutcome | None:
    """Jade Monolith: "The next time a source of your choice would deal damage
    to target creature this turn, that source deals that damage to you
    instead." Redirects the whole instance (combat damage included) — but only
    when the damage comes from the chosen source."""
    permanent = payload["recipient"]
    amount = payload["amount"]
    redirect_idx = _jade_monolith_seat(game, payload)
    permanent.metadata.pop("redirect_damage_to_player", None)
    permanent.metadata.pop("redirect_damage_source", None)
    game._deal_damage_to_player(game.players[redirect_idx], amount)
    game.log.append(
        f"Damage to {permanent.card.name} redirected to {game.players[redirect_idx].name} (Jade Monolith)"
    )
    return ReplacementOutcome(replaced=True)


def _applies_redirect_one_damage(game, payload: dict) -> bool:
    charges = int(
        payload["recipient"].metadata.get("redirect_one_damage_to_owner_until_eot", 0)
    )
    return charges > 0 and payload["amount"] > 0


@replacement_effect(
    "damage_to_creature", REDIRECT_ONE_POINT, applies=_applies_redirect_one_damage, redirects=True
)
def _redirect_one_damage_to_owner(game, payload: dict) -> ReplacementOutcome | None:
    """Personal Incarnation: "The next 1 damage that would be dealt to this
    creature this turn is dealt to its owner instead." One point per charge,
    replaced before the rest is marked."""
    permanent = payload["recipient"]
    amount = payload["amount"]
    redirect = int(permanent.metadata.get("redirect_one_damage_to_owner_until_eot", 0))
    permanent.metadata["redirect_one_damage_to_owner_until_eot"] = redirect - 1
    owner_seat = game.controller_index_of(permanent)
    owner = game.players[owner_seat] if owner_seat is not None else None
    if owner is not None:
        game._deal_damage_to_player(owner, 1)
        game.log.append(f"1 damage redirected from {permanent.card.name} to {owner.name}")
    return ReplacementOutcome(new_amount=amount - 1)


def _recorded_redirect(game, payload: dict):
    """The general redirect record that would move this damage, or None. Pure —
    see ``engine/damage_redirects.py`` for why the predicate may not spend one."""
    if payload["amount"] <= 0:
        return None
    return applicable_redirect(
        game, payload["recipient"], payload.get("source"),
        combat=bool(payload.get("combat")),
    )


def _applies_recorded_redirect(game, payload: dict) -> bool:
    return _recorded_redirect(game, payload) is not None


@replacement_effect(
    "damage_to_player", RECORDED_REDIRECT, applies=_applies_recorded_redirect, redirects=True
)
@replacement_effect(
    "damage_to_creature", RECORDED_REDIRECT, applies=_applies_recorded_redirect, redirects=True
)
def _apply_recorded_redirect(game, payload: dict) -> ReplacementOutcome | None:
    """CR 614.9: the damage is dealt to another recipient instead.

    One interceptor for both ends of the event, registered twice, because a
    redirect is one effect that happens to be printed with a player on one side
    (Shimian Night Stalker moves *your* damage onto a creature) or a permanent
    (Jade Monolith's shape, moving a creature's onto a player). Which of the two
    kinds the event is says nothing about what the record does.

    **The damage is dealt, not prevented.** It is handed to the ordinary damage
    path for its new recipient with the same source, so lifelink (CR 120.3f),
    "whenever ~ deals damage" triggers, deathtouch and the dealt-damage records
    all see it exactly as they would have seen the original event — none of which
    a prevention-plus-fresh-damage spelling would get right. The original event
    is then consumed, which is what stops the same damage landing twice.

    The combat flag travels with it: damage redirected during the combat damage
    step is still combat damage (CR 510.2 does not stop being true because the
    recipient changed), so a Fog or a Circle still sees what it should.
    """
    redirect = _recorded_redirect(game, payload)
    if redirect is None:  # pragma: no cover - the predicate just said otherwise
        return None
    if redirect.optional:
        return _offer_optional_redirect(game, payload, redirect)
    recipient = payload["recipient"]
    new_recipient = live_recipient(game, redirect)
    amount = payload["amount"]
    source = payload.get("source")
    redirect.spend()
    # Held while the hand-off runs so a pair of records aimed at each other
    # cannot recurse: the new event runs the whole contention set again, and an
    # unspent record with no uses limit would still be applicable.
    redirect.applying = True
    try:
        if isinstance(new_recipient, PlayerState):
            game._deal_damage_to_player(new_recipient, amount, source=source)
            taker = new_recipient.name
        else:
            game._mark_damage_on_permanent(
                new_recipient, amount, source=source, combat=bool(payload.get("combat"))
            )
            taker = new_recipient.card.name
    finally:
        redirect.applying = False
    drop_spent(recipient)
    for items in (getattr(game, "resolving_items", None) or (),):
        for item in items:
            drop_spent(item)
    from_name = getattr(recipient, "name", None) or getattr(
        getattr(recipient, "card", None), "name", "it"
    )
    game.log.append(
        f"{amount} damage to {from_name} is dealt to {taker} instead"
        + (f" ({redirect.source_name})" if redirect.source_name else "")
    )
    return ReplacementOutcome(replaced=True)


#: The seat a class-scoped optional redirect asks, and the labels it offers.
#: Option 0 takes the damage; option 1 leaves it where it was dealt.
_TAKE_THE_DAMAGE = 0
_LEAVE_THE_DAMAGE = 1


def _would_be_lethal(permanent, amount: int) -> bool:
    """Whether *amount* more damage would be lethal to *permanent* (CR 704.5g).

    ``effective_toughness`` rather than the printed number, because that is the
    layer-aware accessor every other read of a creature's size goes through.
    """
    return permanent.effective_toughness - int(permanent.damage_marked or 0) <= amount


def _optional_redirect_default(game, payload: dict, redirect: DamageRedirect) -> int:
    """The stated policy a non-interactive seat takes on "you may have that
    damage dealt to you instead".

    Take the damage exactly when it would otherwise kill the creature *and* the
    taker survives at 1 or more life. That is a policy about the two facts the
    sentence trades between and nothing about which card printed it: below
    lethal, the creature keeps the damage and heals at cleanup, so paying life
    for it buys nothing; at or above the taker's life total it loses the game
    to save a creature, which no board state makes worth it.

    Stated here rather than defaulting to the offer (the shape every other
    ``ReplacementChoice`` takes) because this offer is the only one in the
    engine that can *lose the game* — Blood of the Martyr's controller is
    offered every point of damage every creature on the board would take,
    including their opponents' burn aimed at their opponents' creatures.
    """
    taker = redirect.new_recipient
    recipient = payload["recipient"]
    amount = int(payload["amount"])
    if getattr(taker, "life", 0) - amount < 1:
        return _LEAVE_THE_DAMAGE
    if _is_permanent(recipient) and _would_be_lethal(recipient, amount):
        return _TAKE_THE_DAMAGE
    return _LEAVE_THE_DAMAGE


def _offer_optional_redirect(
    game, payload: dict, redirect: DamageRedirect
) -> ReplacementOutcome | None:
    """CR 614 + CR 614.9: "you **may** have that damage dealt to you instead."

    The event is consumed either way and the resolver deals the damage, because
    that is what makes both answers one code path: "yes" is the ordinary
    redirect above and "no" is the event running again with this record held
    out of it. An interceptor that declined by returning ``None`` could not
    exist — the answer arrives on a later request, and by then
    ``apply_replacements`` has long returned.
    """
    taker = redirect.new_recipient
    if not isinstance(taker, PlayerState):  # pragma: no cover - lowering refuses it
        return None
    recipient = payload["recipient"]
    from_name = getattr(recipient, "name", None) or getattr(
        getattr(recipient, "card", None), "name", "it"
    )
    suspended, _ = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="optional_damage_redirect",
            player_index=game.players.index(taker),
            options=(
                f"take the {payload['amount']} damage yourself",
                f"leave it on {from_name}",
            ),
            default_option=_optional_redirect_default(game, payload, redirect),
            data={
                "_redirect": redirect,
                "_recipient": recipient,
                "_source": payload.get("source"),
                "amount": int(payload["amount"]),
                "combat": bool(payload.get("combat")),
                "from_name": from_name,
            },
        ),
    )
    if suspended:
        game.log.append(
            f"{taker.name} may take the {payload['amount']} damage headed for "
            f"{from_name} ({redirect.source_name or 'redirect'})"
        )
    return ReplacementOutcome(replaced=True)


@replacement_choice("optional_damage_redirect")
def _resolve_optional_damage_redirect(
    game, choice: ReplacementChoice, option_index: int
) -> int:
    """Deal the damage the offer suspended, to whichever recipient was chosen.

    ``applying`` is held over the hand-off in both branches and for the same
    reason it is in the compulsory redirect: the damage is re-run through the
    whole contention set, so a record still applicable would offer itself
    again — forever on the declining branch, which is the one the flag exists
    for here.
    """
    redirect = choice.data["_redirect"]
    recipient = choice.data["_recipient"]
    source = choice.data["_source"]
    amount = int(choice.data["amount"])
    taker = game.players[choice.player_index]
    redirect.applying = True
    try:
        if option_index == _TAKE_THE_DAMAGE:
            redirect.spend()
            game._deal_damage_to_player(taker, amount, source=source)
            game.log.append(
                f"{amount} damage to {choice.data['from_name']} is dealt to "
                f"{taker.name} instead"
                + (f" ({redirect.source_name})" if redirect.source_name else "")
            )
        elif isinstance(recipient, PlayerState):  # pragma: no cover - not printed
            game._deal_damage_to_player(recipient, amount, source=source)
        else:
            game._mark_damage_on_permanent(
                recipient, amount, source=source, combat=bool(choice.data["combat"])
            )
    finally:
        redirect.applying = False
    return 0


def _is_desert(source) -> bool:
    card = getattr(source, "card", source)
    return (
        card is not None
        and getattr(card, "primary_type", None) == "land"
        and "desert" in card.type_line.lower()
    )


_CAMEL_SHIELD_TEXT = "prevent all damage deserts would deal to this creature"


def _banded_desert_shield(game, permanent) -> bool:
    """Camel's second clause: the shield also covers "creatures banded with
    this creature". Bands are only declared for the attacking player, so find
    the damaged creature's attacker index and scan its band for an attacking
    Camel.

    The band lasts for the rest of combat (CR 702.22e) and attacking creatures
    stay attacking until the end of combat step ends (CR 511.3), so the shield
    still covers a band-mate targeted by a Desert during that step.

    The index lookup is by identity: Permanent is a plain dataclass, so
    ``list.index`` compares field-by-field and would return a *different*,
    identically-stated attacker — losing the shield on the creature that
    actually is in the band.
    """
    if not permanent.attacking:
        return False
    for player in game.players:
        index = next(
            (i for i, perm in enumerate(player.battlefield) if perm is permanent), None
        )
        if index is None:
            continue
        band = game._attacker_band(index)
        if not band:
            return False
        for other in band:
            if other == index or not (0 <= other < len(player.battlefield)):
                continue
            mate = player.battlefield[other]
            if mate.attacking and _CAMEL_SHIELD_TEXT in (mate.effective_card.oracle_text or "").lower():
                return True
        return False
    return False


def _applies_desert_shield(game, payload: dict) -> bool:
    """The whole of this effect is its guard — being shielded from Deserts does
    not do anything to the event beyond consuming it — so the predicate carries
    all three ways a creature can be covered."""
    permanent = payload["recipient"]
    if not _is_desert(payload.get("source")):
        return False
    text = (permanent.effective_card.oracle_text or "").lower()
    return (
        "prevent all damage that would be dealt to this creature by deserts" in text
        or (_CAMEL_SHIELD_TEXT in text and permanent.attacking)
        or _banded_desert_shield(game, permanent)
    )


@replacement_effect(
    "damage_to_creature", SOURCE_TYPE_SHIELD, applies=_applies_desert_shield, redirects=True
)
def _prevent_desert_damage(game, payload: dict) -> ReplacementOutcome | None:
    """Desert Nomads: "Prevent all damage that would be dealt to this
    creature by Deserts." / Camel: same shield while attacking, extended to
    creatures banded with it. Checked against oracle text directly (like
    Lich's life-gain replacement) rather than a compiled instruction."""
    return ReplacementOutcome(replaced=True)


def _damage_multiplier(game, payload: dict) -> int:
    """How much this event's damage is multiplied by, or 1 for not at all.

    Read off the seat that controls the *source* (CR 109.5), which is the whole
    reason a damage event carries one — the payload's ``source`` is a bare
    ``CardDefinition`` for a spell, so a Permanent-only reading would triple a
    creature's damage and silently not a burn spell's.

    **One candidate stands in for every copy.** CR 616.1 would apply two Fiery
    Emancipations one at a time, and the affected player would choose where the
    shields go among them — but every copy is the same effect at the same order,
    so applying them together is exactly the sequence the default choice
    produces. Registering one interceptor and counting the sources is therefore
    the same game, where returning ``3`` and being asked once would be a
    different one: an effect applies once per event
    (``engine/effect_ordering.py``), so the second Emancipation would be
    dropped rather than deferred.
    """
    seat = payload.get("source_seat")
    if payload["amount"] <= 0 or seat is None:
        return 1
    sources = sum(
        1
        for perm in game.controlled_by(seat)
        if TRIPLE_DAMAGE_TEXT in (perm.effective_card.oracle_text or "").lower()
    )
    return 3 ** sources


def _applies_damage_multiplier(game, payload: dict) -> bool:
    return _damage_multiplier(game, payload) > 1


@replacement_effect(
    "damage_to_creature", DAMAGE_MULTIPLIER, applies=_applies_damage_multiplier
)
@replacement_effect(
    "damage_to_player", DAMAGE_MULTIPLIER, applies=_applies_damage_multiplier
)
def _multiply_damage_dealt(game, payload: dict) -> ReplacementOutcome | None:
    """Fiery Emancipation: "If a source you control would deal damage to a
    permanent or player, it deals triple that damage to that permanent or player
    instead."

    A CR 120.4b effect, so the bigger number is the damage *dealt*: lifelink
    gains it (CR 120.3f), a "deals damage to a player" trigger sees it, and
    deathtouch and trample read it. One body for both recipients because the
    card makes no distinction — "a permanent or player" is the whole of its
    scope — and the two kinds differ only in which list they are registered in.
    """
    multiplier = _damage_multiplier(game, payload)
    amount = payload["amount"]
    game.log.append(
        f"{amount} damage becomes {amount * multiplier} (Fiery Emancipation)"
    )
    return ReplacementOutcome(new_amount=amount * multiplier)


def _applies_exile_instead_of_dying(game, payload: dict) -> bool:
    return bool(payload["permanent"].metadata.get("exile_if_dies_this_turn"))


@replacement_effect(
    "would_die", EXILE_INSTEAD_OF_DYING, applies=_applies_exile_instead_of_dying
)
def _exile_instead_of_dying(game, payload: dict) -> ReplacementOutcome | None:
    """Disintegrate-style: "if it would die this turn, exile it instead." The
    permanent never reaches the graveyard, so no dies-triggers fire (CR 614)."""
    permanent = payload["permanent"]
    if not permanent.metadata.get("is_token", False):
        payload["player"].exile.append(permanent.card)
    game.log.append(f"{permanent.card.name} was exiled instead of dying")
    return ReplacementOutcome(replaced=True)


RETURN_TO_HAND_INSTEAD_TEXT = (
    "if this creature would die, return it to its owner's hand instead. until "
    "that player's next turn, that player plays with that card revealed in "
    "their hand and can't play it"
)


def _applies_return_to_hand_instead(game, payload: dict) -> bool:
    permanent = payload["permanent"]
    # A token returned to a hand ceases to exist (CR 111.7) rather than being
    # held there, so the sentence has nothing to do — and the rider that
    # follows it is about a card in a hand, which a token never becomes.
    if permanent.metadata.get("is_token", False):
        return False
    text = (permanent.effective_card.oracle_text or "").lower()
    return RETURN_TO_HAND_INSTEAD_TEXT in text


@replacement_effect(
    "would_die",
    RETURN_TO_HAND_INSTEAD_OF_DYING,
    applies=_applies_return_to_hand_instead,
)
def _return_to_hand_instead_of_dying(game, payload: dict) -> ReplacementOutcome | None:
    """Firestorm Phoenix: "If this creature would die, return it to its owner's
    hand instead. Until that player's next turn, that player plays with that
    card revealed in their hand and can't play it."

    The permanent never reaches the graveyard, so nothing that watches a death
    sees one (CR 614) — no dies-trigger, and the game-wide "creatures died this
    turn" record is untouched. It goes to its **owner's** hand, not its
    controller's (CR 400.3), which is the difference a stolen Phoenix makes.

    The second sentence is not decoration and is not a second effect: it is the
    same replacement's rider, so it is applied here, in the same breath as the
    return. ``engine/hand_locks.py`` holds it, and holds it only while the card
    actually arrived — a card diverted to the command zone (CR 903.9b) is in no
    hand to be revealed in.
    """
    permanent = payload["permanent"]
    owner_seat = game.owner_index_of(permanent)
    if owner_seat is None:
        owner_seat = game.players.index(payload["player"])
    owner = game.players[owner_seat]
    if game.put_card_into_hand(owner, permanent.card):
        lock_card_in_hand(game, owner_seat, permanent.card, permanent.card.name)
        game.log.append(
            f"{permanent.card.name} returned to {owner.name}'s hand instead of dying, "
            f"revealed and unplayable until their next turn"
        )
    return ReplacementOutcome(replaced=True)


EXILE_UNCAST_CREATURE_TEXT = (
    "if a nontoken creature would enter and it wasn't cast, exile it instead"
)


def _applies_exile_uncast_creature(game, payload: dict) -> bool:
    permanent = payload["permanent"]
    # Every clause of the printed sentence, asked here rather than in the body:
    # CR 616.1 counts the effects in contention before running any, so an
    # interceptor that answered by applying itself would make them uncountable.
    if payload["was_cast"] or permanent.metadata.get("is_token", False):
        return False
    if not permanent.is_creature:
        return False
    # "…would enter" is any battlefield, not just its controller's: Containment
    # Priest stops an opponent's reanimation too. ``_player_controls_text``
    # answers about one seat, so the question is asked of every seat.
    return any(
        game._player_controls_text(player, EXILE_UNCAST_CREATURE_TEXT)
        for player in game.players
    )


@replacement_effect(
    "would_enter_battlefield", EXILE_INSTEAD_OF_ENTERING,
    applies=_applies_exile_uncast_creature,
)
def _exile_instead_of_entering(game, payload: dict) -> ReplacementOutcome | None:
    """Containment Priest: "If a nontoken creature would enter and it wasn't
    cast, exile it instead."

    The permanent never enters, so nothing that watches entering sees it — no
    enters-the-battlefield trigger, no layer contribution, no summoning-sickness
    stamp. That is the whole point of a CR 614 replacement over a
    "when it enters, exile it" trigger, which would let every one of those
    happen first.

    A token is *created* rather than put onto the battlefield from a zone, and
    ceases to exist rather than being exiled (CR 111.7), which is why the
    printed word "nontoken" is a clause of the applicability rather than an
    approximation of it.
    """
    permanent = payload["permanent"]
    owner_index = game.owner_index_of(permanent)
    owner = game.players[owner_index if owner_index is not None else payload["controller_index"]]
    owner.exile.append(permanent.card)
    game.log.append(
        f"{permanent.card.name} was exiled instead of entering the battlefield"
    )
    return ReplacementOutcome(replaced=True)


def _entry_exile_requirement(game, payload: dict) -> dict | None:
    """What the entering permanent's own text demands it exile, or None.

    Asked of ``engine/enter_effects.entry_exile_requirement`` - the same reader
    the entry state performs the exile with and the support gate claims the line
    with - so the sentence that refuses the entry and the sentence that carries
    it out cannot describe different cards.
    """
    from .enter_effects import entry_exile_requirement

    permanent = payload["permanent"]
    return entry_exile_requirement(
        permanent.card, permanent.metadata.get("cast_x_value")
    )


def _applies_unpayable_entry_cost(game, payload: dict) -> bool:
    """Whether the controller cannot pay the entry cost the permanent prints.

    Pure, as CR 616.1 requires: it counts the graveyard rather than emptying it.
    "From **your** graveyard" is the seat the permanent would enter under, which
    is the payload's own ``controller_index`` - a replacement is asked about the
    event that *would* happen, and the permanent is on no battlefield yet to
    have a controller derived for it.
    """
    from .handlers._common import _card_matches_filter

    required = _entry_exile_requirement(game, payload)
    if required is None:
        return False
    count = int(required["count"])
    # "Exile zero cards" is something everyone can do, so the sentence below is
    # not reached - Frankenstein's Monster cast for X=0 enters as its printed
    # 0/1 with nothing exiled and no counter on it.
    if count <= 0:
        return False
    described = required["filter"]
    available = sum(
        1
        for card in game.players[payload["controller_index"]].graveyard
        if _card_matches_filter(card, described)
    )
    return available < count


@replacement_effect(
    "would_enter_battlefield", UNPAYABLE_ENTRY_COST,
    applies=_applies_unpayable_entry_cost,
)
def _graveyard_instead_of_entering(game, payload: dict) -> ReplacementOutcome | None:
    """Frankenstein's Monster: "If you can't, put this creature into its owner's
    graveyard instead of onto the battlefield."

    A consuming replacement, and it has to be one: the permanent never enters,
    so nothing that watches entering sees it - no permanent id, no layer
    contribution, no enters-the-battlefield trigger, no summoning-sickness
    stamp. A "when it enters, sacrifice it" reading would let every one of those
    happen first and would put a *permanent* into a graveyard, which is a death
    (CR 700.4) and fires the dies triggers this card never should.

    Its owner's graveyard, not its controller's: the card is going to the zone
    CR 400.3 gives it, and the two differ for a creature cast off a Ring of
    Ma'ruf or under a control effect that changed hands before it resolved.

    The claim for this sentence lives in ``engine/enter_effects.py`` with the
    other two sentences of the same CR 614.1c effect, rather than in
    ``REPLACEMENT_LINES`` beside every other interceptor here: the three
    sentences are one paragraph and one replacement, and claiming a sentence of
    it twice is two claims free to drift. ``_entry_exile_requirement`` above
    reads that module, so this interceptor still self-selects off the card's own
    text the way every other one in this file does.
    """
    permanent = payload["permanent"]
    owner_index = game.owner_index_of(permanent)
    owner = game.players[
        owner_index if owner_index is not None else payload["controller_index"]
    ]
    owner.graveyard.append(permanent.card)
    game.log.append(
        f"{permanent.card.name} was put into {owner.name}'s graveyard instead of "
        f"entering the battlefield"
    )
    return ReplacementOutcome(replaced=True)



# ---------------------------------------------------------------------------
# The untap step (CR 502, CR 614)
# ---------------------------------------------------------------------------

#: "If a permanent with a wind counter on it would untap during its controller's
#: untap step, remove all wind counters from it instead." (Freyalise's Winds.)
#:
#: Matched by **shape**, like the redirect and the damage cap below
#: :func:`replacement_claims_line`, because the counter's word is payload: a
#: card printing "frost counter" is the same sentence and must need no second
#: constant. The word is repeated in the pattern with a backreference, so a line
#: that puts one counter on and removes a *different* one stays unclaimed rather
#: than being read as this effect.
_COUNTERS_INSTEAD_OF_UNTAP = re.compile(
    r"^if a permanent with an? (?P<counter>[a-z][a-z' -]*) counter on it would "
    r"untap during its controller's untap step, remove all (?P=counter) "
    r"counters from it instead$"
)


def counters_instead_of_untap(line: str) -> str | None:
    """The counter word *line* removes in place of an untap, or None.

    One reader, three callers: the support gate through
    :func:`replacement_claims_line`, the applicability predicate below, and the
    interceptor. A second reader of the phrase is how a card ends up claimed by
    a gate and replaced by nobody.
    """
    normalized = " ".join((line or "").split()).strip().lower().rstrip(".")
    match = _COUNTERS_INSTEAD_OF_UNTAP.match(normalized)
    return match.group("counter") if match is not None else None


def _untap_counter_kinds(game) -> list[str]:
    """Every counter word a permanent on the battlefield says to remove instead
    of untapping.

    Every battlefield, because the sentence names no seat: "a permanent" is any
    permanent and "its controller's untap step" is whichever step that is. Read
    off ``effective_card`` so a text change (CR 612) and a granted line both
    count.
    """
    kinds: list[str] = []
    for permanent in game.all_permanents():
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            counter = counters_instead_of_untap(line)
            if counter is not None and counter not in kinds:
                kinds.append(counter)
    return kinds


def _applies_counters_instead_of_untap(game, payload: dict) -> bool:
    from .named_counters import counters_on

    permanent = payload.get("permanent")
    if permanent is None:
        return False
    return any(
        counters_on(permanent, kind) > 0 for kind in _untap_counter_kinds(game)
    )


@replacement_effect(
    "would_untap", COUNTERS_REMOVED_INSTEAD_OF_UNTAPPING,
    applies=_applies_counters_instead_of_untap,
)
def _remove_counters_instead_of_untapping(
    game, payload: dict
) -> ReplacementOutcome | None:
    """Freyalise's Winds: "If a permanent with a wind counter on it would untap
    during its controller's untap step, remove all wind counters from it
    instead."

    A genuine CR 614 replacement rather than an entry in
    ``engine/untap_restrictions.py``: that table says which permanents *do not
    untap*, and a row there would keep the permanent tapped and leave the
    counters on it forever — the card is a soft lock, not a hard one, and the
    difference is one turn per counter.
    """
    from .named_counters import counters_on, remove_counters

    permanent = payload["permanent"]
    removed = 0
    for kind in _untap_counter_kinds(game):
        held = counters_on(permanent, kind)
        if held:
            remove_counters(permanent, kind, held)
            removed += held
    if not removed:
        return None
    game.log.append(
        f"{permanent.card.name} does not untap; {removed} counter(s) removed instead"
    )
    return ReplacementOutcome(replaced=True)


# ---------------------------------------------------------------------------
# Interactive replacements (CR 614 + engine/replacement_choices.py)
#
# Each of these is optional or offers a choice, so it cannot simply mutate the
# event: it offers a ReplacementChoice and the paired resolver finishes the job
# once the chooser answers (immediately, for a non-interactive seat).
# ---------------------------------------------------------------------------

LANDS_CANT_ENTER_TEXT = "lands can't enter the battlefield"


def _applies_lands_cant_enter(game, payload: dict) -> bool:
    # Layer 4, not the printed line: an animated land is still a land, and a
    # permanent that is a land as it *would* exist on the battlefield is what
    # CR 614.17d says to check.
    if not payload["permanent"].has_type("land"):
        return False
    # "Lands can't" is every battlefield, not just the source controller's —
    # the sentence names no seat at all. `_player_controls_text` answers about
    # one seat, so the question is asked of every one.
    return any(
        game._player_controls_text(player, LANDS_CANT_ENTER_TEXT)
        for player in game.players
    )


@replacement_effect(
    "would_enter_battlefield", LANDS_CANT_ENTER,
    applies=_applies_lands_cant_enter,
)
def _lands_cannot_enter(game, payload: dict) -> ReplacementOutcome | None:
    """Worms of the Earth: "Lands can't enter the battlefield."

    CR 614.17: a "can't" effect is not a replacement effect, but it follows the
    same rules, which is why it is registered here — this is the one place the
    engine asks "may this permanent enter?" before it does. It is not the play
    restriction beside it on the same card: that one (CR 305.1, enforced through
    ``Game._may_play_another_land``) is about the *action* of playing a land,
    and this one is about a land arriving from anywhere at all — a reanimation,
    a search that puts one onto the battlefield, a token.

    The land does not enter and nothing that watches entering sees it: no
    permanent id, no layer contribution, no enters-the-battlefield trigger. It
    stays a card in whatever zone the caller took it from, which is why nothing
    is appended to a graveyard or an exile here — CR 614.17 removes the event
    rather than redirecting it, and a destination this rule does not name would
    be a card the effect quietly moved.
    """
    game.log.append(
        f"{payload['permanent'].card.name} can't enter the battlefield"
    )
    return ReplacementOutcome(replaced=True)


TOP_OF_LIBRARY_DISCARD_TEXT = (
    "if an effect causes you to discard a card, discard it, but you may put it "
    "on top of your library instead"
)


def _applies_leng_discard(game, payload: dict) -> bool:
    return game._player_controls_text(payload["player"], TOP_OF_LIBRARY_DISCARD_TEXT)


@replacement_effect("discard", DISCARD_DESTINATION, applies=_applies_leng_discard)
def _top_of_library_instead_of_graveyard(game, payload: dict) -> ReplacementOutcome | None:
    """Library of Leng: "If an effect causes you to discard a card, discard it,
    but you may put it on top of your library instead of into your graveyard."

    The discarded card is in no zone until the choice is answered — it has left
    the hand and its destination is still undecided (CR 701.9c)."""
    player = payload["player"]
    card = payload["card"]
    suspended, _ = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="leng_discard",
            player_index=game.players.index(player),
            options=("top of library", "graveyard"),
            default_option=0,
            data={"card": card},
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} discarded {card.name} — Library of Leng: "
            "choose graveyard or top of library"
        )
    return ReplacementOutcome(replaced=True)


@replacement_choice("leng_discard")
def _resolve_leng_discard(game, choice: ReplacementChoice, option_index: int) -> int:
    player = game.players[choice.player_index]
    card = choice.data["card"]
    if option_index == 0:
        game.put_card_into_library(player, card, "top")
        game.log.append(
            f"{player.name} put discarded {card.name} on top of their library (Library of Leng)"
        )
    else:
        player.graveyard.append(card)
        game.log.append(f"{player.name} put discarded {card.name} into their graveyard")
    return 0


def _doubled_draw_count(game, payload: dict) -> int:
    """How many cards this draw event should take, once the doublers have had
    it — the same number back when none apply.

    Two things the arithmetic has to keep apart. CR 121.2 makes an event of
    ``count`` draws *that many individual draws*, and the rider exempts **one
    draw**, not one event: a draw step with a Howling Mine out draws 1 + 1, and
    only the first of those two is the one you drew first in your draw step. And
    CR 614.5 stops a doubler applying to the draws it created, so each affected
    draw becomes two rather than dividing forever.

    Copies multiply, for the reason ``_damage_multiplier`` records: an effect
    applies once per event, so counting the sources is the only way a second
    doubler is not silently dropped. Teferi's Ageless Insight is legendary and
    Alhammarret's Archive is not in this pool, so today the count is one — the
    legend rule is round 49's open block, and "there can only be one" is exactly
    the kind of claim about the pool that expires without anyone editing it.
    """
    count = int(payload.get("count", 0))
    exempt = 1 if payload.get("turn_based") else 0
    doublers = sum(
        1
        for perm in game.controlled_by(payload["player"])
        if DOUBLE_DRAW_TEXT in (perm.effective_card.oracle_text or "").lower()
    )
    affected = max(0, count - exempt)
    return exempt + affected * (2 ** doublers)


def _applies_double_draw(game, payload: dict) -> bool:
    return _doubled_draw_count(game, payload) > int(payload.get("count", 0))


@replacement_effect("draw", DRAW_DOUBLED, applies=_applies_double_draw)
def _draw_two_cards_instead(game, payload: dict) -> ReplacementOutcome | None:
    """Teferi's Ageless Insight: "If you would draw a card except the first one
    you draw in each of your draw steps, draw two cards instead."

    A *modifying* replacement, like Conclave Mentor's extra counter and unlike
    the two below it: the event still happens, with a bigger number, so nothing
    is consumed and the draws stay ordinary draws — a Ring of Ma'rûf or an
    Aladdin's Lamp armed alongside still gets one of them (CR 616.1f re-asks
    against the raised count).
    """
    player = payload["player"]
    before = int(payload["count"])
    payload["count"] = _doubled_draw_count(game, payload)
    game.log.append(
        f"{player.name} draws {payload['count']} instead of {before} "
        "(Teferi's Ageless Insight)"
    )
    return ReplacementOutcome()


def _applies_outside_game_draw(game, payload: dict) -> bool:
    return game.players.index(payload["player"]) in game.outside_game_draw_replacements


@replacement_effect("draw", DRAW_FROM_OUTSIDE, applies=_applies_outside_game_draw)
def _draw_from_outside_the_game(game, payload: dict) -> ReplacementOutcome | None:
    """Ring of Ma'rûf: the next draw is replaced by putting a card you own from
    outside the game into your hand.

    Nothing is drawn from the library, so this reports 0 cards drawn and a
    "whenever you draw a card" effect correctly sees no draw. With no eligible
    card there is nothing to take and the replacement is spent anyway
    (CR 614.1). CR 407.3 keeps ante cards out of a game not played for ante.
    """
    player = payload["player"]
    player_index = game.players.index(player)
    game.outside_game_draw_replacements.discard(player_index)
    available = game._outside_game_choices(player_index)
    remaining = payload["count"] - 1
    if not available:
        game.log.append(
            f"{player.name} has no cards outside the game to take (Ring of Ma'rûf)"
        )
        if remaining > 0:
            game._draw_with_replacements(player, remaining)
        payload["drawn"] = 0
        return ReplacementOutcome(replaced=True)
    suspended, drawn = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="outside_game_draw",
            player_index=player_index,
            options=tuple(player.sideboard[i].name for i in available),
            default_option=0,
            # Sideboard positions behind each offered name, so a choice made
            # against the filtered list still pulls the right card.
            data={"sideboard_indices": available, "remaining_draws": remaining},
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} looks through the cards they own from outside the game (Ring of Ma'rûf)"
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


@replacement_choice("outside_game_draw")
def _resolve_outside_game_draw(game, choice: ReplacementChoice, option_index: int) -> int:
    indices = choice.data.get("sideboard_indices") or list(range(len(choice.options)))
    game._finish_outside_game_draw(choice.player_index, indices[option_index])
    remaining = int(choice.data.get("remaining_draws", 0))
    if remaining > 0:
        game._draw_with_replacements(game.players[choice.player_index], remaining)
    return 0


def _applies_lamp_draw(game, payload: dict) -> bool:
    """Armed, not "will do something". The charge is spent even when the library
    turns out to be too short to look at anything (CR 614.1), so the short-library
    case has to be inside the effect rather than in front of it — a predicate
    that declined there would leave the charge unspent."""
    return bool(game.lamp_draw_replacements.get(game.players.index(payload["player"])))


@replacement_effect("draw", DRAW_LOOKING_AT_TOP, applies=_applies_lamp_draw)
def _look_at_top_cards_and_draw_one(game, payload: dict) -> ReplacementOutcome | None:
    """Aladdin's Lamp: the next draw is replaced by "look at the top X cards of
    your library, draw one of them, then put the rest on the bottom in a random
    order". The charge is spent even when the library is too short to look at
    anything, in which case the draw happens normally (CR 614.1)."""
    player = payload["player"]
    player_index = game.players.index(player)
    x = game.lamp_draw_replacements.pop(player_index)
    x = min(int(x), len(player.library))
    if x <= 0:
        return None
    suspended, drawn = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="lamp_draw",
            player_index=player_index,
            options=tuple(card.name for card in player.library[:x]),
            default_option=0,
            data={"remaining_draws": payload["count"] - 1},
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} looks at the top {x} card(s) of their library (Aladdin's Lamp)"
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


@replacement_choice("lamp_draw")
def _resolve_lamp_draw(game, choice: ReplacementChoice, option_index: int) -> int:
    player = game.players[choice.player_index]
    looked_at = min(len(choice.options), len(player.library))
    drawn = game._finish_lamp_draw(choice.player_index, option_index, looked_at)
    remaining = int(choice.data.get("remaining_draws", 0))
    if remaining > 0:
        drawn += game._draw_with_replacements(player, remaining)
    return drawn


LAND_EQUILIBRIUM_TEXT = (
    "if an opponent who controls at least as many lands as you do would put a "
    "land onto the battlefield, that player instead puts that land onto the "
    "battlefield then sacrifices a land of their choice"
)

#: The metadata key an entry replacement's "then …" half is recorded under,
#: read once the permanent is actually on the battlefield.
ENTRY_SACRIFICE_KEY = "sacrifice_land_after_entering"


def _land_count(game, seat: int) -> int:
    """How many lands *seat* controls, through the control seam and layer 4 —
    so an animated land is still a land and a stolen one counts for whoever
    controls it now."""
    return sum(1 for perm in game.controlled_by(seat) if perm.has_type("land"))


def _land_equilibrium_watchers(game, payload: dict) -> list:
    """The permanents whose replacement this entry answers to.

    Every clause of the printed sentence, asked here rather than in the body,
    because CR 616.1 counts the effects in contention before running any:

    * the entering permanent is a land (layer 4, not the printed line);
    * the seat it would enter under is an **opponent** of the source's
      controller — a Land Equilibrium never taxes its own controller;
    * that opponent controls **at least as many** lands as the source's
      controller *now*, before the land arrives. A replacement effect is asked
      about the event that *would* happen (CR 614.1), and the land that would
      enter is not on the battlefield to be counted yet.

    A list rather than a boolean because two copies are two effects and each
    charges its own land, the reason ``_damage_multiplier`` counts its sources.
    """
    permanent = payload["permanent"]
    if not permanent.has_type("land"):
        return []
    entering_seat = payload["controller_index"]
    watchers = []
    for perm in game.all_permanents():
        if LAND_EQUILIBRIUM_TEXT not in (perm.effective_card.oracle_text or "").lower():
            continue
        owner_seat = game.controller_index_of(perm)
        if owner_seat is None or entering_seat not in game.opponents_of(owner_seat):
            continue
        if _land_count(game, entering_seat) >= _land_count(game, owner_seat):
            watchers.append(perm)
    return watchers


def _applies_land_equilibrium(game, payload: dict) -> bool:
    return bool(_land_equilibrium_watchers(game, payload))


@replacement_effect(
    "would_enter_battlefield",
    SACRIFICE_AFTER_ENTERING,
    applies=_applies_land_equilibrium,
)
def _sacrifice_after_entering(game, payload: dict) -> ReplacementOutcome | None:
    """Land Equilibrium: "If an opponent who controls at least as many lands as
    you do would put a land onto the battlefield, that player instead puts that
    land onto the battlefield then sacrifices a land of their choice."

    A *modifying* replacement, not a consuming one — the land still enters, and
    every enters-the-battlefield trigger and layer contribution happens
    normally. What the sentence adds is the word "then": the sacrifice comes
    after the entry, so the land that just arrived is itself a legal choice.

    The event is still in front of the entry here, so the sacrifice is recorded
    on the permanent and armed by :func:`apply_entry_riders` once the
    battlefield actually holds it. Arming it from this line would offer a
    non-interactive seat a board the new land is not on yet.
    """
    permanent = payload["permanent"]
    watchers = _land_equilibrium_watchers(game, payload)
    permanent.metadata[ENTRY_SACRIFICE_KEY] = (
        int(permanent.metadata.get(ENTRY_SACRIFICE_KEY, 0)) + len(watchers)
    )
    game.log.append(
        f"{game.players[payload['controller_index']].name} will sacrifice "
        f"{len(watchers)} land(s) for {permanent.card.name} "
        f"({watchers[0].card.name})"
    )
    return ReplacementOutcome()


def apply_entry_riders(game, permanent, controller_index: int) -> None:
    """The "…**then** X" half of an entry replacement, once the permanent is on
    the battlefield.

    Called from the one entry path there is, for the same reason the entry
    replacement itself is asked there: a rider per caller is a rider forgotten
    by every caller that arrives later. Nothing is recorded for an ordinary
    entry, so this is a metadata read and a return.
    """
    owed = int(permanent.metadata.pop(ENTRY_SACRIFICE_KEY, 0))
    if owed <= 0:
        return
    game.arm_forced_sacrifice(
        controller_index,
        owed,
        filter={"type_filter": "land"},
        reason="Land Equilibrium",
    )


DISCARD_INSTEAD_OF_DRAW_TEXT = (
    "if a player would draw a card except the first one they draw in each of "
    "their draw steps, that player discards a card instead. if the player "
    "discards a card this way, they draw a card. if the player doesn't discard "
    "a card this way, they mill a card"
)


def _chains_sources(game, payload: dict) -> list:
    """Every permanent whose text is this replacement and that has not already
    had its opportunity on this event (CR 614.5).

    Scanned over the whole board, not one seat's: the sentence says "a player",
    so the enchantment replaces its own controller's draws as well as their
    opponents'. Reading ``_player_controls_text`` here would have made it a
    one-sided card, which is the narrowing this pool keeps producing.
    """
    exclude = set(payload.get("exclude_sources") or ())
    return [
        perm
        for perm in game.all_permanents()
        if DISCARD_INSTEAD_OF_DRAW_TEXT in (perm.effective_card.oracle_text or "").lower()
        and perm.permanent_id not in exclude
    ]


#: Enduring Renewal, all three printed sentences. The constant is the whole
#: line because the interceptor performs the whole line — the reveal, the
#: graveyard for a creature card and the draw for anything else. A claim
#: stopping at the first sentence would admit the card with two-thirds of it
#: doing nothing.
REVEAL_TOP_INSTEAD_OF_DRAW_TEXT = (
    "if you would draw a card, reveal the top card of your library instead. "
    "if it's a creature card, put it into your graveyard. otherwise, draw a card"
)


def _reveal_top_sources(game, payload: dict) -> list:
    """Every permanent whose text is this replacement, on the **drawing
    player's** board, that has not already had its opportunity on this event
    (CR 614.5).

    One seat's board and not every board, because the sentence says "**you**":
    an Enduring Renewal an opponent controls replaces *their* draws. Chains of
    Mephistopheles one function down scans every board for exactly the opposite
    reason — it says "a player" — which is why the scope is written per card
    rather than shared.

    The exclusion is what stops the "otherwise, draw a card" branch from
    replacing the draw it just created and looping forever. A *second* Enduring
    Renewal is a different effect and does apply, which is why it names the
    source rather than the wording.
    """
    exclude = set(payload.get("exclude_sources") or ())
    seat = game.players.index(payload["player"])
    return [
        perm
        for perm in game.controlled_by(seat)
        if REVEAL_TOP_INSTEAD_OF_DRAW_TEXT in (perm.effective_card.oracle_text or "").lower()
        and perm.permanent_id not in exclude
    ]


def _applies_reveal_top_instead_of_draw(game, payload: dict) -> bool:
    return int(payload.get("count", 0)) > 0 and bool(
        _reveal_top_sources(game, payload)
    )


@replacement_effect(
    "draw", DRAW_REVEALS_TOP, applies=_applies_reveal_top_instead_of_draw
)
def _reveal_top_instead_of_drawing(game, payload: dict) -> ReplacementOutcome | None:
    """Enduring Renewal: "If you would draw a card, reveal the top card of your
    library instead. If it's a creature card, put it into your graveyard.
    Otherwise, draw a card."

    One draw at a time, because that is what the sentence replaces (CR 121.2
    makes an N-card draw N individual draws). The event is consumed and the
    draws queued behind it are made through the seam again, so a second
    replacement armed alongside still gets its own.

    The "otherwise" branch is a **new draw**, not a resumption of the replaced
    one, and it goes back through the seam carrying this source in
    ``exclude_sources`` — CR 614.5 gives a replacement one opportunity per
    event, so it must not replace the draw it just created and loop. A second
    Enduring Renewal is a different effect and does apply, which is why the
    exclusion names the source rather than the wording.

    An empty library reveals nothing and draws nothing: CR 704.5b fires on an
    *attempted* draw, and the attempt was replaced.
    """
    player = payload["player"]
    count = int(payload["count"])
    source = min(
        _reveal_top_sources(game, payload), key=lambda perm: perm.permanent_id
    )
    excludes = tuple(payload.get("exclude_sources") or ()) + (source.permanent_id,)
    drawn = 0
    if player.library:
        revealed = player.library[0]
        game.record_reveal(game.players.index(player), [revealed.name])
        if card_has_type(revealed, "creature"):
            player.library.pop(0)
            player.graveyard.append(revealed)
            game.log.append(
                f"{player.name} revealed {revealed.name} and put it into their "
                f"graveyard ({source.card.name})"
            )
        else:
            game.log.append(
                f"{player.name} revealed {revealed.name} and draws it "
                f"({source.card.name})"
            )
            drawn += game._draw_with_replacements(
                player, 1, exclude_sources=excludes
            )
    else:
        game.log.append(
            f"{player.name} has no card to reveal ({source.card.name})"
        )
    # The draws queued behind this one are their own events (CR 121.2) and get
    # their own trip through the seam — including this replacement again, which
    # is what a two-card draw under Enduring Renewal is.
    if count > 1:
        drawn += game._draw_with_replacements(
            player, count - 1,
            turn_based=False,
            exclude_sources=tuple(payload.get("exclude_sources") or ()),
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


def _chains_affected_draws(payload: dict) -> int:
    """How many of this event's draws the exemption leaves.

    The same arithmetic ``_doubled_draw_count`` sets out: CR 121.2 makes an
    event of ``count`` draws that many individual draws, and "except the first
    one they draw in each of their draw steps" exempts **one draw**, not one
    event — a draw step with a Howling Mine out draws 1 + 1, and only the first
    of the two is exempt.
    """
    exempt = 1 if payload.get("turn_based") else 0
    return max(0, int(payload.get("count", 0)) - exempt)


def _applies_discard_instead_of_draw(game, payload: dict) -> bool:
    return _chains_affected_draws(payload) > 0 and bool(_chains_sources(game, payload))


@replacement_effect(
    "draw", DRAW_DISCARD_INSTEAD, applies=_applies_discard_instead_of_draw
)
def _discard_instead_of_drawing(game, payload: dict) -> ReplacementOutcome | None:
    """Chains of Mephistopheles: "If a player would draw a card except the first
    one they draw in each of their draw steps, that player discards a card
    instead. If the player discards a card this way, they draw a card. If the
    player doesn't discard a card this way, they mill a card."

    One draw at a time, because that is what the sentence replaces. The event is
    consumed; the exempt draw in front of it and the draws queued behind it are
    made through the seam again, so a second replacement armed alongside still
    gets its own.

    The three branches are the printed three. Which card is discarded is the
    player's choice, so it goes through the ordinary ``discard`` prompt with the
    draw hung on it as the prompt's follow-on — a human picks, an AI takes the
    default, and either way the draw happens *after* the discard rather than
    before it. The only way not to discard is to have nothing to discard
    (CR 701.9a), and that is the branch that mills.
    """
    player = payload["player"]
    seat = game.players.index(player)
    count = int(payload["count"])
    exempt = 1 if payload.get("turn_based") else 0
    drawn = 0
    if exempt:
        # Not replaced, and still a draw like any other: it goes back through
        # the seam so an Aladdin's Lamp armed for the draw step still takes it.
        drawn += game._draw_with_replacements(player, exempt, turn_based=True)
    remaining = count - exempt - 1
    source = min(_chains_sources(game, payload), key=lambda perm: perm.permanent_id)
    # CR 614.5: the draw this effect creates is not replaced by this effect
    # again. A *second* copy is a different effect and still applies, which is
    # why the exclusion names the source rather than the wording.
    excludes = tuple(payload.get("exclude_sources") or ()) + (source.permanent_id,)
    if player.hand:
        game.arm_pending_choice(
            "discard",
            seat,
            count=1,
            filter={},
            draw_that_many=True,
            draw_exclude_sources=excludes,
            queued_draws=max(0, remaining),
        )
        game.log.append(
            f"{player.name} discards a card instead of drawing ({source.card.name})"
        )
    else:
        milled = _mill_cards(game, player, 1)
        game.log.append(
            f"{player.name} had no card to discard and milled {milled} card(s) "
            f"({source.card.name})"
        )
        if remaining > 0:
            drawn += game._draw_with_replacements(player, remaining)
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


def _mill_cards(game, player, count: int) -> int:
    """CR 701.13a: put the top *count* cards of *player*'s library into their
    graveyard, stopping at whatever is there.

    Milling is not a draw and never has been — CR 704.5b's loss is about
    *attempting to draw* from an empty library — so an empty library mills
    nothing and costs nothing.
    """
    milled = 0
    for _ in range(count):
        if not player.library:
            break
        player.graveyard.append(player.library.pop(0))
        milled += 1
    return milled


# ---------------------------------------------------------------------------
# Which printed lines this registry implements, for the two readers that ask
# ---------------------------------------------------------------------------

#: Each entry is ``(the phrase an interceptor above self-selects on, the
#: trailing clause that same interceptor also performs)``. The tail is spelled
#: out in full rather than left as an open-ended "and whatever follows" — it is
#: the one place an entry could otherwise claim text nothing implements.
#:
#: **Both readers ask here rather than keeping their own copy.**
#: ``engine/grammar/registries.py`` asks to account for the line's *parse*:
#: nothing the grammar could lower would run these, because the interceptor
#: already does, from the card's text, on every relevant event.
#: ``engine/oracle.py``'s support gate asks to account for the card's
#: *support* — and until this round it did not. It asked the other six
#: text-keyed tables (untap restrictions, land plays, global statics, draw-step
#: bonuses, cost modifiers, entry effects) and not the CR 614 one, so a
#: permanent whose *only* ability is a replacement effect produced no
#: instruction, claimed nothing, and reported unsupported however well the
#: interceptor worked. Every card in the pool that reaches an interceptor here
#: happened to print a second, readable line — Lich, Ali from Cairo, Library of
#: Leng, Conclave Mentor all do — so the gap had no card behind it until Fiery
#: Emancipation, whose whole text is one replacement.
#:
#: A list in either caller would be free to drift from the interceptors. Here it
#: cannot: the phrases *are* the constants the interceptors probe for.
REPLACEMENT_LINES: tuple[tuple[str, str], ...] = (
    # _draw_instead_of_life_gain (Lich): the phrase is the whole line.
    (LIFE_GAIN_TO_DRAW_TEXT, ""),
    # _floor_life_at_one (Ali from Cairo): the phrase is the whole line.
    (DAMAGE_LIFE_FLOOR_TEXT, ""),
    # _top_of_library_instead_of_graveyard (Library of Leng). The constant the
    # interceptor probes for stops at "...on top of your library instead"; the
    # ReplacementChoice it raises offers exactly the two destinations the tail
    # names ("top of library", "graveyard"), so the interceptor implements the
    # tail as well.
    (TOP_OF_LIBRARY_DISCARD_TEXT, " of into your graveyard"),
    # _one_more_plus1_counter (Conclave Mentor): the phrase is the whole line,
    # matched against the counter-placing seam in mixins/effects.py.
    (EXTRA_PLUS1_COUNTER_TEXT, ""),
    # _multiply_damage_dealt (Fiery Emancipation): the phrase is the whole line,
    # and this is the entry that made the support gate's omission visible — the
    # card prints nothing else.
    (TRIPLE_DAMAGE_TEXT, ""),
    # _draw_two_cards_instead (Teferi's Ageless Insight): the phrase is the whole
    # line, rider included — the exemption is implemented, not ignored, so the
    # claim covers the words that state it.
    (DOUBLE_DRAW_TEXT, ""),
    # _exile_instead_of_entering (Containment Priest): the phrase is the whole
    # line, and every clause of it — nontoken, creature, not cast — is a clause
    # of the applicability predicate rather than an approximation of one.
    (EXILE_UNCAST_CREATURE_TEXT, ""),
    # _discard_instead_of_drawing (Chains of Mephistopheles): the constant is
    # all three printed sentences, because the interceptor performs all three —
    # the discard, the draw behind a discard that happened, and the mill behind
    # one that could not. A claim stopping at the first sentence would be a
    # rider claimed and not executed.
    (DISCARD_INSTEAD_OF_DRAW_TEXT, ""),
    # _return_to_hand_instead_of_dying (Firestorm Phoenix): the constant is both
    # printed sentences, because the interceptor performs both — the return and
    # the reveal-and-lock rider behind it (engine/hand_locks.py). A claim
    # stopping at the first sentence would admit the card with half its text
    # doing nothing.
    (RETURN_TO_HAND_INSTEAD_TEXT, ""),
    # _reveal_top_instead_of_drawing (Enduring Renewal): the constant is all
    # three printed sentences, because the interceptor performs all three — the
    # reveal, the graveyard for a creature card and the draw for anything else.
    (REVEAL_TOP_INSTEAD_OF_DRAW_TEXT, ""),
    # _lands_cannot_enter (Worms of the Earth): the phrase is the whole line,
    # and every land entering from anywhere is refused — the interceptor tests
    # the type through layer 4 rather than the printed one, so the claim covers
    # exactly what the sentence says.
    (LANDS_CANT_ENTER_TEXT, ""),
    # _sacrifice_after_entering (Land Equilibrium): the constant is the whole
    # sentence, "then sacrifices a land of their choice" included — the entry
    # is let through and the sacrifice is armed once the land is on the
    # battlefield, which is what "then" says.
    (LAND_EQUILIBRIUM_TEXT, ""),
)


def replacement_claims_line(line: str) -> bool:
    """Whether one printed line is, in full, a replacement effect implemented
    above.

    The reduction matches what the interceptors really see: they probe the
    card's lowercased oracle text, and a line differs from it only by its
    trailing full stop.
    """
    normalized = line.strip().lower().rstrip(".")
    if any(normalized == phrase + tail for phrase, tail in REPLACEMENT_LINES):
        return True
    # "As long as this creature is untapped, all damage … is dealt to this
    # creature instead" (Veteran Bodyguard, Martyrs of Korlis). Matched by
    # shape rather than listed as a constant, because the source class is
    # payload — and asked of the same reader the interceptor uses, so a class
    # it cannot answer leaves the line unclaimed rather than admitted with the
    # redirect silently not firing.
    if redirect_to_self_source_class(normalized) is not None:
        return True
    # "If a permanent with a wind counter on it would untap during its
    # controller's untap step, remove all wind counters from it instead."
    # (Freyalise's Winds), matched by shape because the counter word is payload.
    if counters_instead_of_untap(normalized) is not None:
        return True
    # "If an instant or sorcery source would deal 3 or more damage to you…"
    # (Forethought Amulet), the same arrangement for the same reason.
    return source_damage_cap(normalized) is not None
