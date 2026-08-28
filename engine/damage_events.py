"""One damage event, start to finish (CR 120.4, CR 616.1).

A damage event is not one decision, it is two, and the engine spent a long time
treating it as one number. CR 120.4 sets out the sequence:

- **120.4b — the damage is dealt**, as modified by the replacement and prevention
  effects that interact with *damage*: shields absorb points, redirects send the
  event somewhere else. Abilities that trigger on damage being dealt trigger on
  what comes out of this half.
- **120.4c — the damage that was dealt is processed into its results**, as
  modified by the replacement effects that interact with *those results*: life
  lost for a player, damage marked for a creature.

Within each half, CR 616.1 chooses: gather every applicable effect, apply one,
re-ask the rest (616.1f). ``engine/effect_ordering.py`` is that process; this
module supplies each half's candidates and runs them in order.

**Why the split earns its keep.** Ali from Cairo ("damage that would reduce your
life total to less than 1 reduces it to 1 instead") is a 120.4c effect, so the
damage is *dealt* in full — lifelink gains the full amount (CR 120.3f) and a
"whenever ~ deals damage to a player" trigger sees the full amount — and only
the life loss is capped. One number cannot carry both answers. That is why the
combat damage step used to apply its shields where the event was recorded (so
lifelink saw the right number) and its replacements where life was applied (so
the floor read the right life total): not two moments by necessity, but one
moment missing a second number. With :class:`DamageOutcome` carrying both, every
damage path runs the whole event in one place.

**Order.** In the 120.4b half the two registries share one order space, so the
default choice is a total order across shields and replacements alike;
``_assert_one_order_space`` makes a collision between them an import-time
failure rather than a tie broken by list order. The 120.4c half has a space of
its own — no shield lives there, because prevention stops damage being dealt and
by 120.4c it already has been.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .control import base_controller
from .damage_ledger import record_damage
from .effect_ordering import Candidate, affected_seat, apply_in_order
from .models import Permanent, PlayerState
from .prevention import shield_candidates, spent
from .replacements import (
    apply_replacements,
    order_prompt_asker,
    replacement_candidates,
    take_replaced,
    was_replaced,
)


@dataclass(frozen=True)
class DamageOutcome:
    """What one damage event did, in CR 120.4's two parts.

    consumed -- a replacement took the event whole; no damage was dealt at all
                and nothing downstream should treat this as a damage event
                (CR 120.8)
    dealt    -- damage actually dealt (CR 120.4b). What lifelink (CR 120.3f),
                "whenever ~ deals damage" triggers, and every caller asking "how
                much did that do" should read.
    result   -- how much of it lands as its result (CR 120.4c): life lost for a
                player, damage marked for a creature. Equal to ``dealt`` unless a
                result-replacement capped it — Ali from Cairo is the one card in
                this pool that separates the two.
    """

    consumed: bool
    dealt: int
    result: int
    #: The event stopped to ask the affected player which effect applies first
    #: (CR 616.1e). **Nothing happened** — no shield spent, no damage dealt, no
    #: trigger fired. The caller must do nothing at all with this outcome; the
    #: answer re-runs the whole event, consequences included.
    suspended: bool = False


# The replacement kinds a damage event passes through, by what it is dealt to.
# Prevention has no such split — one shield registry covers both recipients —
# so this is the only place the halves need lining up.
DAMAGE_KINDS = ("damage_to_player", "damage_to_creature")
RESULT_KINDS = {"damage_to_player": "life_loss", "damage_to_creature": "damage_marked"}


def damage_kind(recipient) -> str:
    """Which CR 120.4b kind an event with this recipient belongs to."""
    return "damage_to_player" if isinstance(recipient, PlayerState) else "damage_to_creature"


LIFELINK = "lifelink"


def lifelink_life_gained(source, dealt: int) -> int:
    """CR 702.15b: life *source*'s controller gains for dealing *dealt* damage.

    Reads ``dealt`` and never ``result``. That is the whole reason
    :class:`DamageOutcome` carries both numbers: Ali from Cairo caps the life
    *lost* without capping the damage *dealt*, and lifelink gains the full
    amount (CR 120.3f). A version of this reading ``result`` would be wrong only
    in the presence of one card, which is the kind of wrong that survives a
    green suite.

    **The rule lives here; the timing does not.** Three callers share it and two
    of them apply it differently, which is a real difference rather than a
    missing abstraction. The combat damage step tallies across the step and
    gains once at the end, because combat damage is dealt simultaneously
    (CR 510.2) — a creature and its blocker trading lethal damage produce one
    life-gain event, not two interleaved with deaths. Everything else gains as
    the damage is dealt.

    Lifelink applies to *any* damage the source deals, not only combat damage —
    which is what this function existing separately is for. It was combat-only
    for as long as the keyword was unimplemented, so a lifelink creature's ping
    ability would have dealt damage and gained nothing.
    """
    if dealt <= 0 or source is None:
        return 0
    has_keyword = getattr(source, "has_keyword", None)
    if has_keyword is None:
        return 0  # a spell or a bare card: no permanent to read a keyword from
    return dealt if has_keyword(LIFELINK) else 0


def damage_source_seat(game, source) -> int | None:
    """The seat that controls a damage event's *source* (CR 109.5), or None.

    Every damage payload has carried its ``source`` and none of them carried
    this, which made "a source **you** control" — Fiery Emancipation, Chandra's
    Pyreling — unwritable rather than unimplemented. The reason is worth being
    precise about, because it is not an oversight: ``source`` is a ``Permanent``
    for a permanent and a bare ``CardDefinition`` for a spell, and a
    ``CardDefinition`` is *the card as printed*. It is shared by every copy in
    every deck in the process and no player controls it, so no amount of reading
    it answers the question.

    Three answers, most specific first:

    - a permanent on the battlefield: the control seam, so a stolen creature's
      damage is the thief's (CR 613 layer 2);
    - a permanent that has left (a source sacrificed to pay for its own
      ability): the seat it entered under, which ``base_controller_index`` keeps
      precisely because it is never rewritten;
    - anything else: whoever is resolving. That is the same rule, not a
      fallback — CR 109.5 makes a spell's source its controller — and it is
      recorded at the one dispatch point that knows it.

    None outside all three: a turn-based action with no controller at all, where
    "you control it" has no answer and every predicate reading this must
    therefore say no rather than guess a seat.
    """
    if source is None:
        return None
    seat = game.controller_index_of(source)
    if seat is not None:
        return seat
    if isinstance(source, Permanent):
        base = base_controller(source)
        if base is not None:
            return base
    return game.resolving_seats[-1] if game.resolving_seats else None


#: "Damage that would be dealt to that creature this turn can't be prevented or
#: dealt instead to another permanent or player." (Whippoorwill.) A marker on
#: the creature, cleared with the turn by ``mixins/_constants._EOT_METADATA_KEYS``.
DAMAGE_LOCK = "damage_cant_be_prevented_or_redirected_until_eot"


def damage_locked(recipient) -> bool:
    """Whether *recipient* carries Whippoorwill's lock. Accepts a player, which
    never does — no card in this pool prints the clause about one."""
    metadata = getattr(recipient, "metadata", None)
    return bool(metadata) and bool(metadata.get(DAMAGE_LOCK))


def damage_candidates(recipient) -> list[Candidate]:
    """Every effect attempting to modify a damage event with this recipient
    before it is dealt (CR 120.4b) — shields and replacements together, in
    default order.

    A locked recipient (Whippoorwill) drops the contenders that *prevent* the
    damage or *move* it, and keeps the rest: the printed clause names those two
    and nothing else, so a multiplier (Fiery Emancipation) and a source cap are
    untouched. Which contenders those are is declared at each registration
    (``Candidate.prevents_or_redirects``) rather than listed here — a list of
    registrations goes stale silently, and the direction it goes stale in is a
    lock that stops locking.

    Filtered here rather than in each ``applies``: this is the one place a
    damage event's contention set is assembled, so a shield added tomorrow is
    covered without knowing the clause exists.
    """
    candidates = shield_candidates() + replacement_candidates(damage_kind(recipient))
    if damage_locked(recipient):
        candidates = [c for c in candidates if not c.prevents_or_redirects]
    return sorted(candidates, key=lambda candidate: candidate.order)


def _settled(game, event: dict) -> bool:
    """The event has been consumed, or has nothing left to modify. Either way
    no further effect can apply to it (CR 615.7, CR 614.6)."""
    return was_replaced(game, event) or spent(game, event)


def deal_damage(game, event: dict, *, restart: Callable[[], Any] | None = None) -> DamageOutcome:
    """Run a damage event through CR 120.4 and report what it did.

    *event* is ``{recipient, amount, source, combat}``. A 0-or-less event
    modifies nothing and consumes nothing (CR 120.8, CR 614.7a): no shield is
    spent and no trigger fires, which is why the amount is checked before any
    effect is asked rather than after.

    This does not apply the result — the caller does that, because what "apply"
    means differs by recipient (life loss, damage marked) and by caller (combat
    accumulates a per-defender tally the log reconstructs from).

    *restart* re-runs the event **and everything the caller does with it**, which
    is what lets CR 616.1e's choice be asked here. Damage differs from a draw in
    exactly that respect: a draw's caller can be told "0 drawn, they arrive
    later", while a damage event's caller gains life equal to it, tallies
    lifelink from it and logs it. So the thunk has to close over the caller's
    own consequences — see ``Game._deal_damage_to_player``'s ``then``, which is
    how every damage caller now passes them in.

    Re-running a single damage event is only enough when the work behind it is
    recorded, because damage is rarely the only thing in flight: a divided
    Fireball deals to each target in turn, a ``sequence`` has instructions
    queued behind the one that stopped, a spell still has CR 608.2n's graveyard
    move to make, and the combat damage step has the rest of its blockers, its
    attackers and its own completion flags. ``engine/resumption.py`` is what
    records that, and the callers that pass ``asks=True`` (or their own
    ``restart``, as the combat step's player-damage loop does) are the ones
    running inside it. Every damage path now asks.
    """
    if event["amount"] <= 0:
        return DamageOutcome(consumed=False, dealt=0, result=0)
    # Derived here rather than at each entry point, for the same reason the
    # amount check is: this is the one place every damage event passes through,
    # so an effect keyed on who dealt it cannot be missed by a path that forgot
    # to fill the key in. `setdefault`, so a caller that genuinely knows better
    # can say so.
    event.setdefault("source_seat", damage_source_seat(game, event.get("source")))
    kind = damage_kind(event["recipient"])
    trace = apply_in_order(
        game,
        event,
        damage_candidates(event["recipient"]),
        chooser_index=affected_seat(game, event["recipient"]),
        stop=_settled,
        ask=None if restart is None else order_prompt_asker(kind, restart),
    )
    if trace.suspended:
        take_replaced(event)
        return DamageOutcome(consumed=False, dealt=0, result=0, suspended=True)
    if trace.applied:
        game.effect_order_answers.pop((kind, affected_seat(game, event["recipient"])), None)
    consumed = take_replaced(event)
    dealt = max(0, event["amount"])
    if consumed or dealt <= 0:
        return DamageOutcome(consumed=consumed, dealt=0, result=0)
    # The turn's record of what each source dealt (engine/damage_ledger.py).
    # Here rather than at any damage path, for the reason `source_seat` above is
    # derived here: this is the one place every damage event passes through, and
    # a history written at the fire sites is a history with as many places to
    # forget it as there are sites. CR 120.4b's `dealt`, not 120.4c's result —
    # "the amount of damage dealt to this creature" is what was dealt.
    record_damage(game, event, dealt)
    result = _process_results(game, event, dealt)
    _announce(game, event, dealt)
    return DamageOutcome(consumed=False, dealt=dealt, result=result)


def _announce(game, event: dict, dealt: int) -> None:
    """CR 603.2: tell the game that damage was dealt.

    **The one place a "deals damage" trigger is announced from**, and the
    docstring at the top of this module has described it as such since before it
    existed: "abilities that trigger on damage being dealt trigger on what comes
    out of this half". Until it did, the announcement lived in
    ``_fire_combat_damage_to_player_triggers`` — a fire site inside the combat
    damage step's *player* loop — so El-Hajjâj ("whenever this creature deals
    damage, you gain that much life") gained nothing for damage dealt to a
    blocker, to a planeswalker, or by any ability at all, and Hypnotic Specter's
    unqualified "deals damage to an opponent" was a combat-only trigger. That
    gap was written down in the fire site's own docstring for as long as it
    existed, which is what a fire site that is not a seam looks like.

    ``dealt`` is CR 120.4b's number, not 120.4c's: Ali from Cairo caps the life
    lost without capping the damage dealt, and a trigger reading "that much"
    reads what was dealt.

    The payload carries what the effects behind these triggers read, all of it
    frozen here because none of it survives to resolution (CR 603.10): the
    damaged player's seat, the damaged permanent's id, the damager and its
    controller's seat.
    """
    from .events import emit
    from .delayed_triggers import fire_delayed_triggers

    recipient = event["recipient"]
    source = event.get("source")
    payload: dict[str, object] = {
        "subject": source,
        "amount": dealt,
        "combat": bool(event.get("combat")),
        "recipient": recipient,
        "damager_seat": event.get("source_seat"),
        # "…deals that much damage to **that creature's controller**"
        # (Backfire). The damager's controller, under the key the generic
        # recipient resolver already reads.
        "event_subject_controller": event.get("source_seat"),
    }
    if isinstance(recipient, PlayerState):
        # The name every handler in this family already reads out of a trigger
        # context — Nafs Asp's draw-step obligation, Hypnotic Specter's discard.
        payload["defending_player_index"] = game.players.index(recipient)
    else:
        damaged_id = getattr(recipient, "permanent_id", None)
        seat = game.controller_index_of(recipient)
        if damaged_id is not None:
            # The damaged permanent as a *target* of the trigger: "destroy that
            # planeswalker" (Hooded Blightfang) resolves it through the ordinary
            # destroy handler, which addresses a permanent by its controller and
            # its id. By id, not by slot, because anything leaving in between
            # renumbers every later index (CR 400.7).
            payload["target_permanent_id"] = damaged_id
            if seat is not None:
                payload["target_player_index"] = seat
        if seat is not None:
            payload["defending_player_index"] = seat
    if isinstance(recipient, PlayerState) and isinstance(source, Permanent):
        # "…if this creature dealt damage to an opponent this turn" (Whirling
        # Dervish). A *history*, so it has to be recorded as it happens
        # (CR 603.10) — and here rather than at a combat fire site for the
        # reason this whole function exists: a ping from an ability is damage
        # this record must see too. Seats rather than PlayerState objects,
        # because the clause asks "was it an opponent of the ability's
        # controller", which is a seat comparison. Cleared with the turn by
        # `_EOT_METADATA_KEYS`.
        seats = source.metadata.setdefault("dealt_damage_to_seats_this_turn", [])
        seat = game.players.index(recipient)
        if seat not in seats:
            seats.append(seat)
    if not isinstance(recipient, PlayerState) and dealt > 0:
        # "…blocked by a creature **that has been dealt damage this turn**"
        # (Giant Shark). The mirror of the record above, kept on the creature
        # that *took* the damage — and here, at the one seam every damage path
        # passes through, for the reason that one is: a ping from an ability is
        # damage this record must see too. Not a read of ``damage_marked``,
        # which is what is left on the creature: regeneration (CR 701.19a) and
        # a toughness rewrite each wipe that while the damage stays dealt.
        # Cleared with the turn by ``_EOT_METADATA_KEYS``.
        recipient.metadata["was_dealt_damage_this_turn"] = True
    emit(game, "damage_dealt", **payload)
    if not isinstance(recipient, PlayerState):
        # "Whenever that creature is dealt damage by an attacking creature this
        # turn, …" (Glyph of Life) — a delayed ability (CR 603.7) belongs to no
        # permanent, so the scan `emit` runs cannot reach it. Here rather than
        # beside one of the three `_fire_dealt_damage_triggers` call sites, for
        # the reason this whole function exists: those are three sites and this
        # is the seam they all pass through, and it is the only place that
        # knows **what dealt** the damage as well as what took it.
        fire_delayed_triggers(
            game, "bound_permanent_dealt_damage",
            subject=recipient,
            # A spell's source is the card as printed (CR 109.5), which is not
            # a permanent and cannot answer "an attacking creature". The
            # narrowing then refuses it, which is right: a Lightning Bolt is
            # not an attacking creature.
            agent=source if isinstance(source, Permanent) else None,
            trigger_context={"damage_dealt": dealt},
        )


def _process_results(game, event: dict, dealt: int) -> int:
    """CR 120.4c: how much of the damage that was dealt lands as its result.

    Carries ``dealt`` alongside the running ``amount`` so an effect that caps the
    result can still see the damage it is not changing.

    Runs without a ``restart``, so this half never asks CR 616.1e's question —
    and never has one to ask, because each results kind holds at most one effect
    and a contention needs two. That is not a coincidence to rely on quietly:
    ``test_a_results_half_contention_would_need_asking`` fails the day a second
    one is registered, because by then the first half has applied real effects
    and re-running would need the replay reasoning this deliberately avoids.
    """
    results = {
        "recipient": event["recipient"],
        "amount": dealt,
        "dealt": dealt,
        "source": event.get("source"),
        "source_seat": event.get("source_seat"),
        "combat": bool(event.get("combat")),
    }
    consumed, _ = apply_replacements(game, RESULT_KINDS[damage_kind(event["recipient"])], results)
    return 0 if consumed else max(0, results["amount"])


def _assert_one_order_space() -> None:
    """A shield and a replacement sharing an order is an ambiguity about which
    modifies a damage event first, which is rules-visible. Both registries
    already reject a duplicate within themselves; this is the check neither can
    make alone, and it runs at import for the same reason theirs do.

    Only the 120.4b half needs it — the results kinds contend with replacements
    alone, so their own per-kind check already covers them.
    """
    for kind in DAMAGE_KINDS:
        seen: dict[int, str] = {}
        for candidate in shield_candidates() + replacement_candidates(kind):
            clash = seen.get(candidate.order)
            if clash is not None:
                raise ValueError(
                    f"{kind} order {candidate.order} is used by both {clash} and "
                    f"{candidate.key}; a damage event's shields and replacements "
                    f"share one order space (see engine/damage_events.py)"
                )
            seen[candidate.order] = candidate.key


_assert_one_order_space()
