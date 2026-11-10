"""The cast decision, recorded as it is made: every candidate the cast
choosers build for a card, the terms its score is the sum of, and why one
that was never proposed was dropped.

**Read by** :func:`engine.ai_cast_explain.explain_cast`, which listens
(:func:`listening`) while it asks the real chooser — ``ai_policy``'s main-phase
or instant-speed one — and prints what this recorded. Nothing else listens.

**Written by the builders themselves**, at the points where they already
hold the answer: an entry (:func:`entry`: one place a card is cast from — a
hand slot, a zone a permission opens, the command zone — as a chooser hands it
to the candidate builder), an attempt inside it (:func:`attempt`: one mode at
one answer to the optional costs, an entwined cast, every mode at once), the
reason an attempt returned nothing (:func:`dropped`), the terms a finished
candidate's score was summed from (:func:`scored`, called by the one function
that finishes every candidate, ``ai_cast_score.finished_cast_candidate``),
and the parts of the rehearsal behind it (:func:`rehearsal_parts`).

**Why it cannot change a decision.** With nobody listening every hook is one
context-variable read and a return of what it was handed: ``dropped`` returns
None for the builder's own ``return``, an entry's ``returns`` hands back its
argument, the context managers yield nothing. With someone listening the
hooks only *append* what the builders computed to lists this module owns: no
hook touches the game, draws from a random generator, or hands a builder a
value it did not hand in. So a seeded run plays byte for byte the same with
the hooks in place (``scripts/sim_fingerprint.py``), and an explanation is the
decision's own numbers — never a second reading that could drift from it.

**Only the table being decided on is recorded.** A rehearsal casts on a
scratch copy, and a decision taken inside one (an opponent's mode choice, a
copy cast one level down) builds candidates of its own: those run on another
``Game`` and are shielded (``entry`` and ``attempt`` clear the current
records for their length), so the trace holds the decision that was asked.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class TracedCandidate:
    """One candidate a builder began: its labels, and how it ended — scored
    (``terms`` summing to ``score``, ``action`` the ``CastAction`` the builder
    returned) or ``dropped`` with the builder's reason."""

    #: ``"single"`` (one mode, or a spell with none), ``"entwined"`` (CR
    #: 702.42a, ``ai_entwine``) or ``"every mode"`` ("choose one or more").
    variant: str
    mode_index: "int | None" = None
    #: CR 601.2b's optional costs this attempt announces, or None.
    offers: "dict | None" = None
    #: The size of an X paid in life this attempt was built at, or None.
    life_x: "int | None" = None
    terms: "list[tuple[str, float]]" = field(default_factory=list)
    score: "float | None" = None
    action: object = None
    rehearsal: object = None
    #: What the rehearsal behind the score had added to it beyond the
    #: standings (``ai_scoring._rehearse_announcement``): chosen draws, a
    #: text change's words.
    rehearsal_parts: "list[tuple[str, float]]" = field(default_factory=list)
    dropped: "str | None" = None
    #: Variants weighed inside the attempt (an alternative cost, a sacrifice
    #: victim) and anything else the builder said on the way.
    notes: "list[str]" = field(default_factory=list)
    #: Every rehearsal ``_rehearse_announcement`` adjusted during the
    #: attempt, with the parts it added — matched to the scored rehearsal by
    #: identity in :func:`scored`.
    _parts_by_rehearsal: list = field(default_factory=list, repr=False)

    @property
    def finished(self) -> bool:
        return self.dropped is None and self.action is not None

    def term(self, name: str) -> "float | None":
        """The value of the term called *name*, or None where there is none."""
        return next((value for named, value in self.terms if named == name), None)


@dataclass
class TracedEntry:
    """One place a chooser asked the builder to cast *card* from, and what
    the builder returned for it (``result``)."""

    card: object
    seat: int
    from_zone: str
    zone_index: int
    #: The ``PermittedCast`` the cast would be made under (CR 601.3), or None.
    permission: object = None
    extra_generic: int = 0
    #: ``"main"`` (``choose_cast_action``) or ``"instant"``
    #: (``choose_combat_instant_cast_action``).
    speed: str = "main"
    candidates: "list[TracedCandidate]" = field(default_factory=list)
    result: object = None
    #: Why the chooser never asked the builder, where it did not.
    skipped: "str | None" = None
    #: Why the builder's pick was set aside after it was built.
    withdrawn: "str | None" = None
    notes: "list[str]" = field(default_factory=list)

    def returns(self, value):
        """Record *value* as the builder's answer for this entry, and hand
        it back."""
        self.result = value
        return value


class CastTrace:
    """Everything one listened-to decision built, entry by entry."""

    def __init__(self, game, seat: int, speed: str = "main"):
        self.game = game
        self.seat = seat
        self.speed = speed
        self.entries: list[TracedEntry] = []


class _Silent:
    """The handle a hook yields when nobody is listening: ``returns`` hands
    its argument straight back."""

    __slots__ = ()

    @staticmethod
    def returns(value):
        return value

    @staticmethod
    def note(_text: str) -> None:
        return None


_SILENT = _Silent()

_TRACE: ContextVar["CastTrace | None"] = ContextVar("ai_cast_trace", default=None)
_ENTRY: ContextVar["TracedEntry | None"] = ContextVar("ai_cast_trace_entry", default=None)
_CANDIDATE: ContextVar["TracedCandidate | None"] = ContextVar(
    "ai_cast_trace_candidate", default=None
)


@contextmanager
def listening(game, seat: int, speed: str = "main"):
    """Record every cast candidate built on *game* for the length of the
    block, into the :class:`CastTrace` this yields."""
    trace = CastTrace(game, seat, speed)
    tokens = (_TRACE.set(trace), _ENTRY.set(None), _CANDIDATE.set(None))
    try:
        yield trace
    finally:
        _CANDIDATE.reset(tokens[2])
        _ENTRY.reset(tokens[1])
        _TRACE.reset(tokens[0])


def silent() -> bool:
    """Whether nobody is listening — so a builder can skip working out the
    labels of an attempt nobody will read."""
    return _TRACE.get() is None


def _trace_for(game) -> "CastTrace | None":
    """The listening trace when *game* is the table it listens to and no
    rehearsal is running; else None."""
    trace = _TRACE.get()
    if trace is None or trace.game is not game:
        return None
    from .ai_rehearsal import rehearsing

    return None if rehearsing() else trace


@contextmanager
def _shielded():
    """A decision on another table (a rehearsal's copy): nothing it builds
    lands in the records of the one being listened to."""
    tokens = (_ENTRY.set(None), _CANDIDATE.set(None))
    try:
        yield _SILENT
    finally:
        _CANDIDATE.reset(tokens[1])
        _ENTRY.reset(tokens[0])


@contextmanager
def entry(
    game, seat: int, card, *, from_zone: str, zone_index: int,
    permission=None, extra_generic: int = 0, speed: "str | None" = None,
):
    """One place *card* is cast from, as a chooser hands it to the builder.
    Yields a handle whose ``returns(value)`` records the builder's answer
    and hands it back."""
    trace = _TRACE.get()
    if trace is None:
        yield _SILENT
        return
    if _trace_for(game) is None:
        with _shielded() as handle:
            yield handle
        return
    traced = TracedEntry(
        card=card, seat=seat, from_zone=from_zone, zone_index=zone_index,
        permission=permission, extra_generic=extra_generic,
        speed=speed or trace.speed,
    )
    trace.entries.append(traced)
    tokens = (_ENTRY.set(traced), _CANDIDATE.set(None))
    try:
        yield traced
    finally:
        _CANDIDATE.reset(tokens[1])
        _ENTRY.reset(tokens[0])


@contextmanager
def attempt(
    game, seat: int, card, *, variant: str = "single",
    mode_index: "int | None" = None, offers: "dict | None" = None,
    life_x: "int | None" = None, from_zone: str = "hand", zone_index: int = 0,
):
    """One candidate the builder begins. Inside it :func:`dropped` and
    :func:`scored` say how it ended."""
    trace = _TRACE.get()
    if trace is None:
        yield _SILENT
        return
    if _trace_for(game) is None:
        with _shielded() as handle:
            yield handle
        return
    current = _ENTRY.get()
    if current is None:
        # A builder asked without a chooser's entry around it (a test, a
        # land drop): its own entry, so the attempt is not lost.
        current = TracedEntry(
            card=card, seat=seat, from_zone=from_zone, zone_index=zone_index,
            speed=trace.speed,
        )
        trace.entries.append(current)
    traced = TracedCandidate(
        variant=variant, mode_index=mode_index,
        offers=dict(offers) if offers else None, life_x=life_x,
    )
    current.candidates.append(traced)
    token = _CANDIDATE.set(traced)
    try:
        yield traced
    finally:
        _CANDIDATE.reset(token)


def dropped(reason: str) -> None:
    """The attempt being built is not proposed, for *reason*. Returns None,
    so a builder writes ``return dropped("…")`` where it wrote
    ``return None``."""
    if _TRACE.get() is None:
        return None
    current = _CANDIDATE.get()
    if current is not None and current.dropped is None:
        current.dropped = reason
    return None


def note(text: str) -> None:
    """Something the builder weighed inside the current attempt, or — with
    no attempt open — about the current entry."""
    if _TRACE.get() is None:
        return
    current = _CANDIDATE.get()
    if current is not None:
        current.notes.append(text)
        return
    holder = _ENTRY.get()
    if holder is not None:
        holder.notes.append(text)


def scored(game, action, terms, score: float, rehearsal=None) -> None:
    """The attempt being built finished as *action*, its *score* the sum of
    *terms* (``(name, value)`` in the order they were added)."""
    if _TRACE.get() is None or _trace_for(game) is None:
        return
    current = _CANDIDATE.get()
    if current is None:
        return
    current.terms = list(terms)
    current.score = score
    current.action = action
    current.rehearsal = rehearsal
    current.rehearsal_parts = next(
        (parts for seen, parts in current._parts_by_rehearsal if seen is rehearsal),
        [],
    )


def scored_from(game, action, base, extra, score: float) -> None:
    """The attempt being built finished as *action*: the candidate *base*
    (already recorded in this entry) with *extra* terms on top — every mode
    of a "choose one or more" spell, scored as its best mode and more."""
    if _TRACE.get() is None or _trace_for(game) is None:
        return
    holder = _ENTRY.get()
    recorded = next(
        (
            candidate for candidate in (holder.candidates if holder else ())
            if candidate.action is base and candidate.terms
        ),
        None,
    )
    if recorded is None:
        scored(game, action, [("best mode's score", base.score), *extra], score)
        return
    scored(game, action, [*recorded.terms, *extra], score, recorded.rehearsal)
    current = _CANDIDATE.get()
    if current is not None:
        current.rehearsal_parts = list(recorded.rehearsal_parts)
        current.notes.append("its rehearsal is its best mode's")


def rehearsal_parts(rehearsal, parts) -> None:
    """``ai_scoring._rehearse_announcement`` added *parts* (``(name, now,
    lasting)``) to *rehearsal*'s standings swing."""
    if _TRACE.get() is None:
        return
    current = _CANDIDATE.get()
    if current is not None and rehearsal is not None:
        current._parts_by_rehearsal.append((rehearsal, list(parts)))


def withdrawn(game, candidate, reason: str) -> None:
    """The builder's pick *candidate* for the entry just built was set aside
    by its caller, for *reason*."""
    trace = _TRACE.get()
    if trace is None or _trace_for(game) is None or not trace.entries:
        return
    for traced in reversed(trace.entries):
        if traced.result is candidate:
            traced.withdrawn = reason
            return


def skipped(game, seat: int, card, *, from_zone: str, zone_index: int,
            reason: str, permission=None) -> None:
    """A chooser passed over *card* without asking the builder, for
    *reason*."""
    trace = _TRACE.get()
    if trace is None or _trace_for(game) is None:
        return
    trace.entries.append(TracedEntry(
        card=card, seat=seat, from_zone=from_zone, zone_index=zone_index,
        permission=permission, speed=trace.speed, skipped=reason,
    ))


__all__ = [
    "CastTrace",
    "TracedCandidate",
    "TracedEntry",
    "attempt",
    "dropped",
    "entry",
    "listening",
    "note",
    "rehearsal_parts",
    "scored",
    "skipped",
    "withdrawn",
]
