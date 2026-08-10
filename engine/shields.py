"""Prevention shields as *state* (CR 615).

``engine/prevention.py`` registers what a shield **does**; this module is what a
shield **is**. The split matters because the two used to be welded together by
name: every card that granted a shield got its own ``PlayerState`` field —
``forcefield_capped_sources``, ``reverse_damage_charges``,
``color_prevention_shields`` — and the interceptor that consumed it read the
field named after the card that made it. Adding a shield therefore meant adding
a field, in a dataclass the web payload, the AI simulator and forty tests all
read.

A shield is a small, closed set of facts, and none of them is a card name:

- **who it protects** — the collection lives on its recipient, and CR 615.1's
  "shield around whatever they're affecting" is a player *or* a permanent, so
  both models carry one.
- **what it answers to** — ``source`` (CR 615.8's "a source of your choice",
  ``None`` meaning any source) and ``color`` (CR 615.9's rechecked property).
- **how much it absorbs** — ``amount`` points (``None`` for CR 615.8's whole
  instance, whatever its size) and ``leave``, the points it deliberately lets
  through ("prevent all but 1 of that damage").
- **how many uses remain** — ``uses`` (``None`` for a shield that is spent by
  points rather than by instances, i.e. CR 615.7's numeric pool).
- **how long it lasts** — ``lifetime``, which is why the turn-step sweeps can be
  one generic call instead of a line per card.

``kind`` is the one link back to behaviour: it names the registered interceptor
that consumes this shield, so a shield and the effect that spends it cannot
drift apart. Kinds are named for what the shield does, never for the card that
granted it.

**Purity.** ``would_prevent`` computes; ``spend`` mutates. CR 616.1 has to count
the effects contending over an event before any of them runs (see
``engine/effect_ordering.py``), so the predicate side of every interceptor calls
only the first. A shield that answered "do I apply?" by decrementing itself
would be spent on effects the player was merely asked about.

**Legacy views.** The old field names survive as properties over this collection
(see ``engine/models.py``), so ``web/serialization.py``'s payload, the AI simulator's
snapshot and the existing tests read exactly what they always did. They are
derived on every read, so they cannot disagree with the shields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Lifetimes (CR 615.3: "until they're used up or their duration has expired")
# ---------------------------------------------------------------------------

END_OF_COMBAT = "end_of_combat"
END_OF_TURN = "end_of_turn"

# ---------------------------------------------------------------------------
# Kinds — which registered interceptor consumes the shield
# ---------------------------------------------------------------------------

#: "Prevent the next N damage that would be dealt to <recipient> this turn"
#: (CR 615.7). Spent by points, not by instances.
PREVENT_NEXT_N = "prevent_next_n"
#: "…prevent all but N of that damage" — a cap, spent whole on one instance.
PREVENT_ALL_BUT = "prevent_all_but"
#: "…prevent that damage. You gain life equal to the damage prevented this way"
#: (CR 615.5's additional effect).
PREVENT_AND_GAIN_LIFE = "prevent_and_gain_life"
#: "The next time a <colour> source of your choice would deal damage to you this
#: turn, prevent that damage" (CR 615.9's rechecked property).
PREVENT_FROM_COLOR = "prevent_from_color"


@dataclass
class Shield:
    """One CR 615 shield sitting on the player or permanent it protects.

    kind        -- the registered interceptor that consumes it
    amount      -- points it can still absorb; None for a whole-instance shield
    leave       -- points it deliberately lets through ("all but 1")
    uses        -- instances it can still apply to; None when only ``amount``
                   governs expiry
    source      -- the chosen damage source it waits for; None = any source
    color       -- the colour the source must have; None = no colour recorded
    lifetime    -- END_OF_COMBAT or END_OF_TURN
    source_name -- the card that granted it, for the UI's shield badge
    """

    kind: str
    amount: int | None = None
    leave: int = 0
    uses: int | None = 1
    source: Any | None = None
    color: str | None = None
    lifetime: str = END_OF_TURN
    source_name: str | None = None

    @property
    def spent(self) -> bool:
        """Used up (CR 615.3), so it no longer exists to be applied."""
        return (self.uses is not None and self.uses <= 0) or (
            self.amount is not None and self.amount <= 0
        )

    def would_prevent(self, amount: int) -> int:
        """Points this shield would remove from an event of *amount*.

        Pure — this is the half CR 616.1's applicability predicate is allowed to
        call. 0 means the shield has nothing to do with this event, which is
        also how "prevent all but 1" declines a 1-point event.
        """
        available = amount - self.leave
        if self.amount is not None:
            available = min(available, self.amount)
        return max(0, available)

    def spend(self, prevented: int) -> None:
        """Charge *prevented* points against the shield. The mutating half."""
        if self.amount is not None:
            self.amount -= prevented
        if self.uses is not None:
            self.uses -= 1


# ---------------------------------------------------------------------------
# The collection
# ---------------------------------------------------------------------------

#: Where the list hangs off a recipient. Reached through :func:`shields_on`
#: rather than a dataclass field so that the legacy views below can be assigned
#: from a model's own generated ``__init__`` without depending on field order.
_SHIELDS_ATTR = "_prevention_shields"


def shields_on(recipient) -> list[Shield]:
    """The shields protecting *recipient*, created on first use.

    Works for a ``PlayerState`` or a ``Permanent`` without either importing this
    module's behaviour, which is what keeps CR 615.1's "player or permanent"
    one code path instead of two parallel cascades.
    """
    shields = getattr(recipient, _SHIELDS_ATTR, None)
    if shields is None:
        shields = []
        setattr(recipient, _SHIELDS_ATTR, shields)
    return shields


def add_shield(recipient, shield: Shield) -> Shield:
    """Put *shield* on *recipient* and return it."""
    shields_on(recipient).append(shield)
    return shield


def shields_of_kind(recipient, kind: str) -> list[Shield]:
    """Live shields of *kind*, oldest first."""
    return [s for s in shields_on(recipient) if s.kind == kind and not s.spent]


def drop_spent(recipient) -> None:
    """Forget shields that have been used up (CR 615.3).

    Called after applying one, so the derived views never report a shield that
    no longer exists — the badge that outlived its pool was its own small bug
    class, fixed here by construction rather than by a clearing line per card.
    """
    shields = shields_on(recipient)
    shields[:] = [s for s in shields if not s.spent]


def clear_shields(recipient, lifetime: str | None = None) -> None:
    """Expire shields whose duration has run out (CR 615.3).

    *lifetime* None clears every shield (the cleanup step); naming one clears
    only shields of that duration (the end of combat step), so a turn-step sweep
    is one call rather than a line per card-named field.
    """
    shields = shields_on(recipient)
    shields[:] = [s for s in shields if lifetime is not None and s.lifetime != lifetime]


# ---------------------------------------------------------------------------
# Legacy views (engine/models.py installs these)
# ---------------------------------------------------------------------------
#
# Each old per-card field is a property computed from the collection, so the web
# payload, the AI simulator and the existing tests keep reading the name they
# always read, and the two can never disagree — there is only one place the
# state lives. Writes go the other way: assigning rebuilds the shields the name
# stood for, which is what lets a test still say ``player.damage_prevention_pool
# = 3``.


class _ShieldValues(list):
    """A list view over one attribute of one kind of shield, writing through.

    A plain derived list would silently drop ``shields.append(x)`` — several
    tests and the granting handlers arm a shield exactly that way — so this is a
    real ``list`` (for ``==``, ``in``, indexing and iteration) whose mutators
    also update the collection it was built from.
    """

    def __init__(self, owner, kind: str, attribute: str, make: Callable[[Any], Shield]):
        super().__init__(
            getattr(s, attribute)
            for s in shields_of_kind(owner, kind)
            if getattr(s, attribute) is not None
        )
        self._owner = owner
        self._kind = kind
        self._attribute = attribute
        self._make = make

    def append(self, value) -> None:
        super().append(value)
        add_shield(self._owner, self._make(value))

    def extend(self, values) -> None:
        for value in values:
            self.append(value)

    def remove(self, value) -> None:
        super().remove(value)
        shields = shields_on(self._owner)
        for shield in shields:
            if shield.kind == self._kind and getattr(shield, self._attribute) == value:
                shields.remove(shield)
                return

    def clear(self) -> None:
        super().clear()
        shields = shields_on(self._owner)
        shields[:] = [
            s
            for s in shields
            if not (s.kind == self._kind and getattr(s, self._attribute) is not None)
        ]

    def _unsupported(self, *args, **kwargs):
        """Every access builds a fresh view, so a mutator that isn't wired
        through would change a list that is thrown away — a silent no-op on
        game state. Refuse loudly instead; add the write-through if a caller
        genuinely needs one."""
        raise TypeError(
            f"{type(self).__name__} supports append/extend/remove/clear; "
            "assign the whole list to replace its shields"
        )

    __setitem__ = __delitem__ = insert = pop = sort = reverse = _unsupported


def _replace_kind(owner, kind: str, shields: list[Shield]) -> None:
    live = shields_on(owner)
    live[:] = [s for s in live if s.kind != kind] + shields


def pool_view(doc: str) -> property:
    """``damage_prevention_pool``: the points CR 615.7's numeric shields hold.

    Summed rather than stored, because several "prevent the next N damage"
    effects on one recipient are several shields; the total is what the old
    single integer meant. Assigning replaces them with one shield of that size,
    which is what the cleanup sweep and the tests that arm a pool directly do.
    """

    def get(self) -> int:
        return sum(s.amount or 0 for s in shields_of_kind(self, PREVENT_NEXT_N))

    def set(self, value: int) -> None:
        total = int(value)
        name = self.damage_prevention_source
        _replace_kind(
            self,
            PREVENT_NEXT_N,
            [Shield(kind=PREVENT_NEXT_N, amount=total, uses=None, source_name=name)]
            if total > 0
            else [],
        )

    return property(get, set, doc=doc)


def charge_view(kind: str, make: Callable[[], Shield], doc: str) -> property:
    """A count of shields of *kind* that name no source — the "any source"
    fallback an AI or headless activation arms when the caster picked nothing.
    """

    def get(self) -> int:
        return sum(1 for s in shields_of_kind(self, kind) if s.source is None)

    def set(self, value: int) -> None:
        keep = [s for s in shields_of_kind(self, kind) if s.source is not None]
        _replace_kind(self, kind, keep + [make() for _ in range(max(0, int(value)))])

    return property(get, set, doc=doc)


def list_view(kind: str, attribute: str, make: Callable[[Any], Shield], doc: str) -> property:
    """A write-through list of one attribute of one kind of shield."""

    def get(self) -> _ShieldValues:
        return _ShieldValues(self, kind, attribute, make)

    def set(self, values) -> None:
        keep = [s for s in shields_of_kind(self, kind) if getattr(s, attribute) is None]
        _replace_kind(self, kind, keep + [make(value) for value in values])

    return property(get, set, doc=doc)


def badge_view(doc: str) -> property:
    """``damage_prevention_source``: the card whose art the UI shows on the
    shield badge — the most recently armed live shield that named one.

    Derived, so a spent shield takes its badge with it. Assignable because the
    name is bookkeeping rather than shield state: it renames the newest shield,
    and None clears every name.
    """

    def get(self) -> str | None:
        return next(
            (s.source_name for s in reversed(shields_on(self)) if s.source_name and not s.spent),
            None,
        )

    def set(self, value: str | None) -> None:
        live = [s for s in shields_on(self) if not s.spent]
        if value is None:
            for shield in live:
                shield.source_name = None
        elif live:
            live[-1].source_name = value

    return property(get, set, doc=doc)


def color_badge_view(doc: str) -> property:
    """``damage_prevention_color``: the colour of the newest live colour shield.

    **Read-only, and the one legacy field that could not take a setter.** The
    colour is not decoration — it is what the shield matches the damage source
    against (CR 615.9), so writing it would either invent a shield or silently
    widen an existing one to match every source. It goes when its shields go.
    """
    return property(
        lambda self: next(
            (s.color for s in reversed(shields_on(self)) if s.color and not s.spent), None
        ),
        doc=doc,
    )


# The shield each legacy list/count view arms when something appends to it.


def make_numeric_pool(amount: int, source_name: str | None = None) -> Shield:
    return Shield(
        kind=PREVENT_NEXT_N, amount=amount, uses=None, source_name=source_name
    )


def make_capped_source(source) -> Shield:
    return Shield(
        kind=PREVENT_ALL_BUT, leave=1, uses=1, source=source, lifetime=END_OF_COMBAT
    )


def make_capped_charge() -> Shield:
    return Shield(kind=PREVENT_ALL_BUT, leave=1, uses=1, lifetime=END_OF_COMBAT)


def make_life_gain_source(source, source_name: str | None = None) -> Shield:
    return Shield(kind=PREVENT_AND_GAIN_LIFE, uses=1, source=source, source_name=source_name)


def make_life_gain_charge(source_name: str | None = None) -> Shield:
    return Shield(kind=PREVENT_AND_GAIN_LIFE, uses=1, source_name=source_name)


def make_color_shield(color: str, source_name: str | None = None) -> Shield:
    return Shield(kind=PREVENT_FROM_COLOR, uses=1, color=color, source_name=source_name)
