"""CR 616.1 — choosing which applicable effect to apply, and in what order.

When two or more replacement (CR 614) and/or prevention (CR 615) effects are
attempting to modify one event, the rules do **not** fix an order. The affected
object's controller — or the affected player — chooses one to apply; the chosen
one is applied; and then the process repeats over whatever is *still* applicable
(616.1f). Any single fixed order is one legal set of those choices, which is why
running a hardcoded cascade is usually right and occasionally not.

This module is that process, and it is the only place either registry decides
what runs next. Both feed it: ``engine/prevention/`` (CR 615 shields) and
``engine/replacements/`` (CR 614), with ``engine/damage_events.py`` putting a
damage event's members of both into the one candidate list the rule describes.
Three things follow from putting the process here:

**Applicability is separable from application.** An effect used to answer "do I
apply?" by applying itself — the guard and the work were one function, so there
was no way to ask how many effects were in contention without running one. Each
registration now carries an ``applies`` predicate, and the guard *moved* there
rather than being copied: the interceptor body starts after the decision, so the
two cannot disagree. That is the whole reason 616.1 was unimplementable before.

**616.1f is real.** Applying one effect can change which others apply — a
partial replacement lowers the amount, a shield is consumed, a redirect moves
the damage to a different recipient. The loop re-gathers after every
application instead of walking a list decided up front.

**The choice is asked, and asking needs nothing to be undone.** 616.1e is the
affected player's, and :func:`apply_in_order` puts it to them through the
``ask`` hook. What makes that possible without continuations or snapshots is the
first point above: predicates are pure, so at the moment a contended round is
reached, *nothing has happened yet*. The process can be abandoned there and the
whole event re-run later against the same state, arriving at the same round with
the same contenders and the answer now recorded. Suspending is free precisely
because there is nothing to roll back.

The caller supplies the re-run, because an event is more than its replacements —
a draw nothing replaces still has to draw — and only the caller knows what doing
it again means. A caller that cannot offer one simply does not, and every seat
takes the default there: a missing capability at one declared place rather than
a branch scattered through the process. **Every damage call in the engine
offers one** — each carries its consequences as a ``then``, and each is either a
step of a loop that records the work behind it (``engine/resumption.py``) or
the last thing its own step does: the handlers and the combat damage step
(``tests/engine/test_kg_damage_handler_asks.py``), and everything else — an
upkeep toll or sweep resolved inline, a prompt's answer, a land's rider, an
Aura's entry, Eye for an Eye's mirror, a shield's rider and the damage a CR
614.9 redirect moves (``replacements/redirects.deal_redirected_damage``, the
modified event's own 616.1 process, asked of its new affected player)
(``tests/engine/test_kg3_damage_asks_outside_handlers.py``). Several seats
asked about one effect's damage are asked in APNAP order (616.1's last
sentence, :func:`in_apnap_order`).

A non-interactive seat is never asked, so AI and headless play stay entirely
synchronous.

Note that 616.1 is not the *only* sequencing a damage event has. CR 120.4 splits
one into "damage is dealt" and "what was dealt is processed into its results",
and 616.1 runs inside each half. ``engine/damage_events.py`` holds that
structure; this module is only the choosing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Candidate:
    """One effect that could modify the event in front of it.

    key           -- stable id, used in logs and by the choice seat
    order         -- the default order, which is what a non-interactive seat
                     chooses. Lower runs first.
    applies       -- ``(game, event) -> bool``. Pure: it must not consume a
                     shield, move damage, or draw a card, because it is asked
                     about effects that may then not be chosen.
    apply         -- ``(game, event) -> outcome``. Runs only once chosen, and
                     may assume ``applies`` just returned True.
    label         -- what the effect does, as the ``effect_order`` prompt
                     shows it and the log names it: one short line
                     (:func:`option_label`)
    sources       -- ``(game, event) -> [source, …]``: the objects generating
                     this effect for this event (CR 616.1), which the option
                     names beside the label (:func:`option_text`). Pure.
    """

    key: str
    order: int
    applies: Callable[[Any, dict], bool]
    apply: Callable[[Any, dict], Any]
    label: str = ""
    # Whether this effect *prevents* the event (CR 615) or *moves* it to another
    # recipient (CR 614.9) — the two things "damage … can't be prevented or
    # dealt instead to another permanent or player" (Whippoorwill) switches off.
    # Declared at registration rather than derived from a list of keys or an
    # order range, because a list of registrations goes stale the day a new one
    # is added and the failure is silent: the lock would quietly stop being a
    # lock over whatever was added last.
    prevents_or_redirects: bool = False
    # The narrower half of the same clause, for the sentence that prints only
    # that half: "…and the damage **can't be prevented**" (Urza's Rage) switches
    # off CR 615 prevention and leaves a CR 614.9 redirect standing — Jade
    # Monolith may still take the ten. Every ``prevents`` contender is also a
    # ``prevents_or_redirects`` one; the reverse is what this field is for.
    prevents: bool = False
    #: What this effect does to the **amount** of the event, for the two shapes
    #: whose best order depends on each other: :data:`CAP` ("if a source would
    #: deal 3 or more damage, it deals 2 instead" — Forethought Amulet, Divine
    #: Presence) and :data:`MULTIPLIER` ("…it deals double that damage instead"
    #: — Furnace of Rath, Fiery Emancipation). Empty for every other effect.
    #: Declared at registration for ``prevents_or_redirects``' reason: read off
    #: an order range instead, it would go stale the day a new one is added.
    amount_role: str = ""
    #: CR 615.12: what applying this **prevention** effect to damage that can't
    #: be prevented does. "Any applicable prevention effects are still applied
    #: to it. Those effects won't prevent any damage, but any additional effects
    #: they have will take place." So a ``prevents`` contender is not simply
    #: dropped by a lock when it carries an additional effect that does not
    #: depend on the amount prevented — Nine Lives' incarnation counter, a
    #: Phantom's +1/+1 counter, Rock Hydra's counter per point — and this is
    #: that effect alone, run in place of ``apply``. None for every effect whose
    #: additional effect is sized by the damage prevented (Reverse Damage gains
    #: life equal to 0) or that has none: dropping those is what 615.12 already
    #: means for them, and 615.12's last sentence keeps their shields unspent.
    #: Applied at most once per event (615.12a), which the loop below gives
    #: every candidate.
    unpreventable_apply: Callable[[Any, dict], Any] | None = None
    #: What generates this effect for the event in front of it: the
    #: permanents whose text it is, the shields' granting cards, the spell
    #: that armed it. Read only to *name* the effect — never to decide whether
    #: it applies, which ``applies`` alone answers — and pure for the same
    #: reason. None names nothing beside the label.
    sources: Callable[[Any, dict], Any] | None = None


#: ``Candidate.amount_role`` values. See :func:`choose_effect`.
CAP = "cap"
MULTIPLIER = "multiplier"

#: The longest ``Candidate.label`` a registration may give: one line of an
#: ``effect_order`` prompt's option list.
OPTION_LABEL_LIMIT = 80


def option_label(label: str, *, key: str) -> str:
    """*label* as the option CR 616.1e's ``effect_order`` prompt shows the
    affected player, or ``ValueError`` at registration if it cannot be one.

    The option a person picks between two effects in contention, so it is one
    short line saying what the effect does — never the registration's
    docstring, which both registries used to cut at its first colon: three
    candidates showed a paragraph (the plain "prevent the next N damage" pool
    among them, so most real contentions did), and one showed its function
    name. Raised at import, like a duplicate order, so a label that cannot be
    shown is found at startup rather than in front of a player.
    """
    text = (label or "").strip()
    if not text or "\n" in text or len(text) > OPTION_LABEL_LIMIT or text == key:
        raise ValueError(
            f"{key}: an effect_order option label is one line of at most "
            f"{OPTION_LABEL_LIMIT} characters saying what the effect does, "
            f"not {label!r}"
        )
    return text


def source_name(source) -> str:
    """How one source of an effect is named to every seat: a permanent or a
    stack object by its card's name — for a face-down one, the blank 2/2's
    (CR 708.2: ``Permanent.card`` *is* the blank while it is hidden) — a card
    by its name, and a name recorded when the effect was created as itself.

    Duck-typed, for the reason :func:`affected_seat` is: this module imports
    nothing from the engine."""
    if isinstance(source, str):
        return source
    card = getattr(source, "card", None)
    if card is not None and getattr(card, "name", None):
        return str(card.name)
    return str(getattr(source, "name", "") or "")


def source_names(sources) -> list[str]:
    """The name of each of *sources*, in order and once each — two Sulfuric
    Vortexes are one effect in contention (one candidate stands for both), and
    the option says which card it is, not how many."""
    names: list[str] = []
    for source in sources or ():
        name = source_name(source)
        if name and name not in names:
            names.append(name)
    return names


def option_text(game, event: dict, candidate: Candidate) -> str:
    """The option CR 616.1e's ``effect_order`` prompt offers for *candidate*:
    what the effect does and, beside it, what generates it — "Gain no life
    instead (Sulfuric Vortex)".

    The label alone named the effect and not its source, so two effects that do
    the same thing read the same, and one that does what an exemplar card does
    read as that card whatever printed it. CR 616.1 is a choice among *effects*;
    a person tells two apart by where each comes from. Everything named is
    public — a permanent, a resolved spell, a name written when the effect was
    created — and a face-down source is named as every seat sees it
    (:func:`source_name`)."""
    names = source_names(candidate.sources(game, event)) if candidate.sources else []
    if not names:
        return candidate.label
    return f"{candidate.label} ({', '.join(names)})"


@dataclass
class OrderingTrace:
    """What the loop did, for tests and logs. Cheap to build and easy to assert
    on: the interesting property of a 616.1 implementation is the *sequence* of
    choices, which is otherwise invisible in the final numbers."""

    applied: list[str] = field(default_factory=list)
    contended: list[tuple[str, ...]] = field(default_factory=list)
    #: The process stopped to ask the affected player which effect applies
    #: first. **Nothing was applied** — see :func:`apply_in_order` for why that
    #: is what makes suspending safe. The caller must not carry on with the
    #: event; answering the prompt restarts it.
    suspended: bool = False
    #: Rounds that contended but took the default because the process was
    #: already under way (CR 616.2 can make a fresh effect applicable after one
    #: has been applied, and by then the prefix is no longer pure). Empty for
    #: every card in this pool; recorded rather than asserted so the day one
    #: arrives it is visible instead of silent.
    unasked: list[tuple[str, ...]] = field(default_factory=list)


# Upper bound on 616.1f iterations. Each application should reduce the
# applicable set, so this is a backstop against an effect whose predicate stays
# True after it runs — a bug, but one that must not hang the game.
MAX_ROUNDS = 64


def affected_seat(game, affected) -> int | None:
    """The seat CR 616.1 gives the choice to: the affected player, or the
    affected permanent's controller.

    Duck-typed on identity rather than on a type, so this module keeps importing
    nothing from the engine and both registries can share one answer to "whose
    choice is this?" — a question every candidate list has to answer the same
    way or the prompt would go to different seats depending on which registry
    happened to gather the event.

    None when the event names no affected object, or names one that has left the
    battlefield: the process still runs, it just has no seat to ask.
    """
    if affected is None:
        return None
    for index, player in enumerate(game.players):
        if player is affected:
            return index
    return game.controller_index_of(affected)


def in_apnap_order(game, recipients, *, affected: Callable[[Any], Any] | None = None) -> list:
    """*recipients* in the order CR 616.1's choices about them are made.

    "If two or more players have to make these choices at the same time,
    choices are made in APNAP order (see rule 101.4)." One effect dealing
    damage to several recipients deals it at once, so every affected player's
    616.1e choice is made at the same time — the active player's (about
    themself and every permanent they control), then each other player's in
    turn order. The engine deals the events one at a time and each asks as it
    is dealt, so the order a loop deals in *is* the order the seats are asked
    in, and a loop walking ``game.players`` asked seat 0 first on every turn.

    Each recipient is ranked by the seat :func:`affected_seat` gives the
    choice to; *affected* maps a loop's item to the player or permanent it is
    about, for a loop whose items are something else (a seat index is read as
    that seat). Stable: within one seat the caller's order stands, which is
    the player's own order of their choices defaulted (CR 101.4c). A
    recipient with no seat to ask goes last. Seats that have left the game
    keep their place — whether to deal to them is the caller's question.
    """
    rank = {
        seat: place
        for place, seat in enumerate(game.apnap_seats(include_lost=True))
    }

    def seat_of(item) -> int | None:
        about = item if affected is None else affected(item)
        if isinstance(about, int) and not isinstance(about, bool):
            return about
        return affected_seat(game, about)

    return sorted(recipients, key=lambda item: rank.get(seat_of(item), len(rank)))


#: Returned by an ``ask`` hook that has queued a prompt instead of answering.
SUSPENDED = object()


def choose_effect(game, chooser_index: int | None, candidates: list[Candidate]) -> Candidate:
    """The default choice (CR 616.1e): the lowest ``order`` — except that a
    multiplier goes ahead of a cap it contends with.

    What a non-interactive seat takes, and what every seat takes on an event
    that cannot suspend to ask. Any single order is a legal set of 616.1e
    choices, so this is a correct game; the orders are picked so that it is
    also the game the affected player would have chosen.

    **One static number cannot say that for a cap and a multiplier.** A cap
    sits at order 5, ahead of the prevention shields (a shield spent on the
    printed damage is wasted when the cap would have taken it to 2 anyway),
    and a multiplier at 700, behind them (a shield spent after tripling
    absorbs its points from three times as much). Each is right against the
    shields and together they are wrong against each other: Divine Presence
    ("…3 or more damage … deals 3 instead") beside Furnace of Rath turned 5
    into 3 and then into **6**, where the affected player — whose choice this
    is — would double first and take 3.

    So the default *chooses* where the numbers cannot: on a round where a cap
    and a multiplier both apply, the multiplier is applied first. That is never
    worse for the affected player. With the damage at or over the threshold the
    cap's result is the same number either way, and applying it last means
    nothing multiplies it; under the threshold the cap does not apply yet, this
    rule is not reached, and the ordinary order runs — after which CR 616.1f
    re-asks the cap about the multiplied amount. Shields keep their place
    relative to both: behind the cap, so they absorb from the capped number.
    """
    if any(candidate.amount_role == CAP for candidate in candidates):
        multipliers = [c for c in candidates if c.amount_role == MULTIPLIER]
        if multipliers:
            return min(multipliers, key=lambda candidate: candidate.order)
    return min(candidates, key=lambda candidate: candidate.order)


def apply_in_order(
    game,
    event: dict,
    candidates: list[Candidate],
    *,
    chooser_index: int | None = None,
    stop: Callable[[Any, dict], bool] | None = None,
    ask: Callable[[Any, int | None, list[Candidate], dict], Any] | None = None,
    default: Callable[[Any, int | None, list[Candidate], dict], Candidate] | None = None,
) -> OrderingTrace:
    """Apply *candidates* to *event* following CR 616.1.

    Each round re-asks every candidate whether it still applies (616.1f),
    because the previous application may have changed the answer. ``stop`` ends
    the process early — a consumed event has nothing left for anything to
    modify.

    ``ask`` is how the affected player is consulted (616.1e):
    ``ask(game, chooser_index, applicable, event)``, the event so the options
    can name each effect's sources (:func:`option_text`). It is called only
    on a round with more than one applicable effect, and only **before anything
    has been applied**. It returns the chosen candidate, or :data:`SUSPENDED`
    to mean "a prompt is queued; stop".

    That "before anything has been applied" restriction is the whole trick, and
    it is worth being explicit about why it is safe rather than merely
    convenient. Every ``applies`` predicate is pure, so the work done before the
    first application is *nothing at all* — the process can be abandoned
    mid-round and re-run from the top later against the same game state and
    reach the same round with the same contenders. Suspending needs no snapshot,
    no continuation and no rollback, because there is nothing yet to undo.

    Once one effect has been applied that is no longer true, so a later round
    that contends takes the default and is recorded in ``trace.unasked``. In
    this pool that cannot happen: applying an effect only ever makes predicates
    go true→false, so if any round contends the first one did.

    ``default`` is the first round's choice for a seat nobody asks, in place
    of :func:`choose_effect`'s stated order — ``default(game, chooser_index,
    applicable, event)``, the same arguments ``ask`` takes. A damage event
    passes a measured one (``engine/measured_effect_order.py``); a later round
    takes the stated order whatever is passed, since by then the process is
    no longer pure.
    """
    trace = OrderingTrace()
    remaining = list(candidates)
    for _ in range(MAX_ROUNDS):
        if stop is not None and stop(game, event):
            return trace
        applicable = [c for c in remaining if c.applies(game, event)]
        if not applicable:
            return trace
        trace.contended.append(tuple(c.key for c in applicable))
        if len(applicable) == 1:
            chosen = applicable[0]
        elif ask is None or trace.applied:
            if ask is not None:
                trace.unasked.append(tuple(c.key for c in applicable))
            chosen = (
                default(game, chooser_index, applicable, event)
                if default is not None and not trace.applied
                else choose_effect(game, chooser_index, applicable)
            )
        else:
            answer = ask(game, chooser_index, applicable, event)
            if answer is SUSPENDED:
                trace.suspended = True
                return trace
            chosen = answer
        chosen.apply(game, event)
        trace.applied.append(chosen.key)
        # An effect applies once per event. Re-gathering is about the *others*
        # becoming (in)applicable, not about running this one again.
        remaining = [c for c in remaining if c is not chosen]
    return trace  # pragma: no cover - MAX_ROUNDS is a backstop
