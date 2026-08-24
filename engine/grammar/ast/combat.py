"""Combat restrictions (CR 506, 509).

`CantBe` is the one-shot ("target creature can't be blocked this turn") and
`CombatRestriction` the continuous one ("can't attack unless defending player
controls an Island"), whose parameters are payload so that a second card with
the same template needs no parser change.

`CombatRestriction` sat below `__all__` at the bottom of the original module,
which is why that module never exported it and why the `Effect` union still
does not name it — even though `lower.py` dispatches on it exactly like a leaf
effect. Filing it here is where it always belonged; whether the union should
name it is a separate question, and moving the node does not answer it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import (
    Duration,
    Recipient,
)


@dataclass(frozen=True)
class CantBe:
    """"<subject> can't be <participle> <duration>." (CR 701.19 regenerate,
    CR 509.1b blocking restrictions.)

    One node for the whole family, with the participle carried as data. Minting
    a node per restriction would put the parser back in the business of knowing
    which effects exist; here an unmodelled participle still reaches lowering,
    which refuses it *by name* — a visibly unsupported card instead of a clause
    nothing implements.

    ``duration`` is not optional in practice: with no duration the sentence is a
    continuous restriction (an Aura's "Enchanted creature can't be blocked"),
    which is a static ability rather than a one-shot effect, and lowering
    separates the two.
    """
    subject: Recipient
    action: str                                    # "regenerated" | "blocked"
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class CombatRestriction:
    """``<subject> can't attack unless …`` / ``can't block creatures with …``.

    A restriction on when the permanent may attack or block (CR 506, 509). It
    is a *static* ability, but unlike most static shapes it does not wait on the
    layers engine: it changes what a player may declare, not what the object's
    characteristics are, and the combat steps already dispatch on the
    instruction it lowers to.

    ``kind`` is the instruction kind, and ``payload`` its data — the land type
    or the power threshold — so the number and the noun stay parameters rather
    than becoming part of the kind's name.
    """

    subject: Recipient
    kind: str
    payload: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class RemoveFromCombat:
    """``Remove <subject> from combat.`` (Disharmony; CR 506.4c.)

    A one-shot combat action, not a restriction: the creature stays on the
    battlefield and simply stops being an attacker or blocker. The subject is
    a back-reference ("remove **it** from combat") — the pool prints the
    sentence only as the tail of a conjunction whose head chose the object,
    and lowering holds it to that shape so a freestanding "remove target
    creature from combat" (False Orders' longer paragraph) keeps failing
    loudly instead of borrowing a producer nothing ran.
    """

    subject: Recipient
