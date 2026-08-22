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
DISCARD_DESTINATION = 10  # Library of Leng
# Before the two draw replacements that *consume* the event, and for the
# player's benefit: a doubler applied first turns one draw into two, and the
# Lamp then replaces one of them, so the player gets both effects. The other
# way round the Lamp consumes the only draw there was and the doubler never
# applies — which CR 616.1e permits, and which is a card fewer.
DRAW_DOUBLED = 5  # Teferi's Ageless Insight
DRAW_FROM_OUTSIDE = 10  # Ring of Ma'rûf
DRAW_LOOKING_AT_TOP = 20  # Aladdin's Lamp
EXTRA_PLUS1_COUNTER = 10  # Conclave Mentor
EXILE_INSTEAD_OF_ENTERING = 10  # Containment Priest

# Set on the event once an interceptor consumes it. It lives on the payload
# because the payload is the one piece of state the 616.1 loop threads through
# every candidate — and it is popped by the entry points below, so it never
# escapes to a caller.
REPLACED = "_replaced"


def replacement_effect(
    kind: str, order: int, *, applies: Applicability
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
                      label=(fn.__doc__ or fn.__name__).split(":")[0].strip())
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
    """Whether *source* is an unblocked attacking creature.

    CR 509.1h: an attacker with a blocker declared for it *is* a blocked
    creature, and stays one even if every blocker leaves combat. So a trampler's
    excess damage to the player is not dealt "by an unblocked creature" — read
    off the permanent's own combat state rather than off which loop the combat
    step happens to be in.
    """
    return bool(getattr(source, "attacking", False)) and not getattr(source, "blocked", False)


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
    "damage_to_player", REDIRECT_WHOLE_EVENT, applies=_applies_bodyguard_redirect
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
    "damage_to_creature", REDIRECT_WHOLE_EVENT, applies=_applies_jade_monolith
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
    "damage_to_creature", REDIRECT_ONE_POINT, applies=_applies_redirect_one_damage
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
    "damage_to_creature", SOURCE_TYPE_SHIELD, applies=_applies_desert_shield
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


# ---------------------------------------------------------------------------
# Interactive replacements (CR 614 + engine/replacement_choices.py)
#
# Each of these is optional or offers a choice, so it cannot simply mutate the
# event: it offers a ReplacementChoice and the paired resolver finishes the job
# once the chooser answers (immediately, for a non-interactive seat).
# ---------------------------------------------------------------------------

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
    return redirect_to_self_source_class(normalized) is not None
