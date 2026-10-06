"""CR 613 layer 4, decided once for the whole board: the board-wide type
statics, in the order CR 613.7 gives and CR 613.8 rearranges.

"All Mountains are Plains" (Conversion), "Nonbasic lands are Mountains" (Blood
Moon), "All lands are no longer snow" (Melting), "All Swamps are 1/1 black
creatures that are still lands" (Kormus Bell), "Creatures you control are the
chosen type" (Conspiracy), "All Goblins … are Zombies in addition to their
other creature types" (Dralnu's Crusade), "Each noncreature artifact … becomes
an artifact creature" (Titania's Song), "Each other non-Aura enchantment is a
creature" (Opalescence). Each is a static ability whose **scope is a type** and
whose effect **changes types** — so which permanents one reaches depends on
what the others have already done, and that is the one situation the layer
system has a second ordering rule for:

    613.8a  An effect is said to "depend on" another if (a) it's applied in
            the same layer … (b) applying the other would change the text or
            the existence of the first effect, what it applies to, or what it
            does to any of the things it applies to …
    613.8b  An effect dependent on one or more other effects waits to apply
            until just after all of those effects have been applied. … If
            several dependent effects form a dependency loop, then this rule
            is ignored and the effects in the dependency loop are applied in
            timestamp order.
    613.8c  After each effect is applied, the order of remaining effects is
            reevaluated …

The engine's collectors are per-object (``layer_bridge.collect_type_effects``
takes one permanent and cannot see the board), so a board-wide static has
always been *folded* onto each permanent by a refresh — and three refreshes did
it three ways, none of them this rule. The land-type statics were chained in
timestamp order alone, so Conversion played before Blood Moon left a nonbasic
land a Mountain where both orders make it a Plains. The global statics' scopes
were judged against the **previous pass's** finished layer 4, so Dralnu's
Crusade found the Goblin a Conspiracy had just made one refresh late. The land
animators were judged last, against whatever the other two had left.

This module is the one place that decides instead. :func:`apply_type_statics`
takes every permanent and every type static on the board and **applies layer 4
once, over all of them**:

* each permanent starts from its copiable values (``seed_characteristics``,
  layers 1 and 3) and brings its *own* layer-4 effects — what a resolution did
  to it, what is attached to it (``collect_own_type_effects``). Those apply to
  one fixed object and do the same thing whatever they find, so they can never
  be the dependent side; they are the fixed points everything else is ordered
  around.
* the effects are taken in timestamp order (CR 613.7), except that a static
  **waits** while applying some effect not yet applied would change which
  permanents it reaches (CR 613.8a–b) — asked by trial, of every remaining
  effect, after every application (CR 613.8c);
* a static in a dependency **loop** does not wait on the others in that loop
  (CR 613.8b's last sentence), so the walk always has a next effect and ends
  after exactly as many steps as there are effects. There is no fixed point to
  iterate to and nothing to bound.

What comes out is, for each static, the permanents it reached and the
**applied-order key** it reached them at: ``(timestamp, order)`` — the latest
timestamp applied so far (its own, unless it waited) and its position among the
statics. Each static writes that through its ``record`` onto the derived
channel its contribution lives on, and the per-object collector re-applies it
by sorting on the key (``ContinuousEffect.timestamp`` and ``.sequence``). A
collector cannot decide a dependency; it can replay one.

**Only "what it applies to" is probed.** CR 613.8a names three things the
other effect may change. The *existence* of a layer-4 static is a layer-6
question (an ability being removed) and CR 613.8a(a) confines dependency to one
layer. *What it does* is, for every effect this layer has, independent of what
it finds — ``continuous._set_action`` is the reading: setting creature types to
Elf is the same action on a Bear and on a Bear Knight — so no layer-4 effect
depends on another through it. That leaves the scope, which is exactly what a
type-scoped static has and a per-object effect has not.

``engine/mixins/permanent_state.py`` gathers the statics (it owns what each
scope means) and writes the results; this module owns the order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Sequence

from .continuous import Characteristics, ContinuousEffect
from .layer_bridge import collect_own_type_effects, seed_characteristics

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent


@dataclass(eq=False)
class TypeStatic:
    """One board-wide static's layer-4 part.

    ``eq=False``: two statics are the same only if they are the same object —
    two Conversions on one battlefield are two effects with two timestamps.
    """

    #: The permanent the static ability is on; its timestamp is the effect's
    #: (CR 613.7a). Kept for the caller, which records reach by source.
    source: "Permanent"
    #: ``source.timestamp`` at the time the statics were gathered.
    timestamp: int
    #: Diagnostics only.
    label: str
    #: Whether the static reaches *permanent* while it presents *types* — the
    #: layer's intermediate state, never its finished answer.
    reaches: Callable[["Permanent", Characteristics], bool]
    #: The layer-4 effect on one reached permanent, at an applied-order key.
    #: The same builder the collector re-applies the contribution with, so
    #: what this pass did and what a later read does cannot differ.
    effect: Callable[["Permanent", int, int], ContinuousEffect | None]
    #: Write the contribution onto *permanent*'s derived channel with the key
    #: it applied at.
    record: Callable[["Permanent", int, int], None]
    #: Whatever else the caller needs to recognise the static by when it reads
    #: the reach back (a land animator's ``LandAnimation``, whose size and
    #: colour are other layers'). Never read here.
    payload: object = None


@dataclass(eq=False)
class _Step:
    """One effect waiting to be applied: a permanent's own, or a static."""

    timestamp: int
    index: int
    permanent: "Permanent | None" = None
    effect: ContinuousEffect | None = None
    static: TypeStatic | None = None

    @property
    def order_key(self) -> tuple[int, int, int]:
        # A static sorts behind a permanent's own effect of the same timestamp
        # — the tie the collector's sort breaks the same way, because an own
        # effect carries sequence 0 and a placed static a positive one.
        return (self.timestamp, 0 if self.static is None else 1, self.index)


def _types_only(types: Characteristics) -> Characteristics:
    """A throwaway copy of the three sets layer 4 writes.

    ``Characteristics.copy`` is a deep copy of nine fields; a dependency probe
    is asked many times per refresh and reads three.
    """
    return Characteristics(
        card_types=set(types.card_types),
        subtypes=set(types.subtypes),
        supertypes=set(types.supertypes),
    )


def _depends_on(
    static: TypeStatic, other: _Step, permanents: Sequence["Permanent"],
    state: dict[int, Characteristics],
) -> bool:
    """CR 613.8a(b): would applying *other* change what *static* applies to?

    By trial, on a copy, one object at a time — every scope here is a question
    about the one permanent it is asked of, so an effect can only move a
    static's reach on the permanents that effect itself changes.
    """
    if other.static is None:
        subjects = [(other.permanent, other.effect)]
    else:
        subjects = [
            (permanent, other.static.effect(permanent, 0, 0))
            for permanent in permanents
            if other.static.reaches(permanent, state[id(permanent)])
        ]
    for permanent, effect in subjects:
        if effect is None:
            continue
        before = state[id(permanent)]
        after = _types_only(before)
        effect.modify(after)
        if static.reaches(permanent, before) != static.reaches(permanent, after):
            return True
    return False


def _next_step(
    remaining: list[_Step], permanents: Sequence["Permanent"],
    state: dict[int, Characteristics],
) -> int:
    """The index in *remaining* of the effect CR 613.7–613.8 applies next.

    The earliest-stamped effect that is not waiting. A permanent's own effect
    never waits. A static waits on every remaining effect it depends on —
    unless that effect depends, directly or through others, back on it: that is
    a dependency loop, and CR 613.8b applies the effects in a loop in timestamp
    order, which is the order *remaining* is already in.
    """
    waits: dict[int, frozenset[int]] = {}

    def depends(index: int) -> frozenset[int]:
        if index not in waits:
            step = remaining[index]
            waits[index] = frozenset() if step.static is None else frozenset(
                other for other in range(len(remaining))
                if other != index
                and _depends_on(step.static, remaining[other], permanents, state)
            )
        return waits[index]

    def leads_back(start: int, goal: int) -> bool:
        seen, frontier = {start}, [start]
        while frontier:
            for nxt in depends(frontier.pop()):
                if nxt == goal:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return False

    for index in range(len(remaining)):
        if all(leads_back(other, index) for other in depends(index)):
            return index
    # Unreachable: among any set of effects the one that depends on nothing
    # outside its own loop exists. Timestamp order if it ever is reached.
    return 0  # pragma: no cover


def apply_type_statics(
    permanents: Sequence["Permanent"], statics: Sequence[TypeStatic]
) -> dict[int, list[TypeStatic]]:
    """Apply layer 4 over *permanents* and write each of *statics*' reach.

    Returns ``{id(permanent): [static, …]}`` — the statics that reached each
    permanent, in the order they applied. Each one's ``record`` has been called
    with the applied-order key by then.

    The caller clears the derived channels first: this writes contributions,
    it does not reconcile them.
    """
    reach: dict[int, list[TypeStatic]] = {}
    if not statics:
        # No board-wide type static: every layer-4 effect on the battlefield is
        # some permanent's own, timestamps are the whole order, and the
        # collector needs nothing from here.
        return reach
    state: dict[int, Characteristics] = {}
    steps: list[_Step] = []
    for permanent in permanents:
        oid = id(permanent)
        state[oid] = seed_characteristics(permanent)
        for effect in collect_own_type_effects(permanent, oid):
            steps.append(_Step(
                timestamp=effect.timestamp, index=len(steps),
                permanent=permanent, effect=effect,
            ))
    for static in statics:
        steps.append(_Step(
            timestamp=static.timestamp, index=len(steps), static=static,
        ))
    remaining = sorted(steps, key=lambda step: step.order_key)
    latest = 0
    placed = 0
    # One effect leaves *remaining* per turn of the loop, so it runs exactly
    # ``len(steps)`` times — a dependency loop included (see ``_next_step``).
    while remaining:
        step = remaining.pop(_next_step(remaining, permanents, state))
        # The applied-order key's first half: the latest timestamp applied so
        # far. An effect that waited takes the stamp of what it waited behind
        # ("just after", CR 613.8b); one that did not takes its own.
        latest = max(latest, step.timestamp)
        if step.static is None:
            step.effect.modify(state[id(step.permanent)])
            continue
        placed += 1
        static = step.static
        # Reach first, then apply: the effect applies to the objects that meet
        # its description as it starts to apply, all at once.
        reached = [
            permanent for permanent in permanents
            if static.reaches(permanent, state[id(permanent)])
        ]
        for permanent in reached:
            effect = static.effect(permanent, latest, placed)
            if effect is not None:
                effect.modify(state[id(permanent)])
            static.record(permanent, latest, placed)
            reach.setdefault(id(permanent), []).append(static)
    return reach


__all__ = ["TypeStatic", "apply_type_statics"]
