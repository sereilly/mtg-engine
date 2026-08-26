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


@dataclass(frozen=True)
class AttackAsThough:
    """``<subject> can attack [duration] as though it didn't have <keyword>.``
    (Wall of Wonder's activated ability.)

    CR 609.4: an "as though" effect applies **only** to the stated effect, so
    this is a *permission* rather than a keyword removal — the creature still
    has defender for everything else, which is the distinction
    ``declare_attackers_step._ignores_defender`` is written around and the
    reason this is not a :class:`~ast.LoseKeyword` with a narrower duration.

    The ignored ability is carried as data rather than baked into the node's
    name, for the reason :class:`CantBe` gives: a wording naming some other
    keyword still reaches lowering, which refuses it by name instead of the
    parser having to know which permissions exist.
    """
    subject: Recipient
    ignored_keyword: str
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class AttackingDoesntTap:
    """``Attacking doesn't cause <subject> to tap this combat[ if <condition>].``
    (Johan.)

    CR 508.1f's tap, turned off for a set of creatures the sentence names. Not
    a :class:`~ast.GainKeyword` of vigilance however alike the two behave: the
    card grants no ability, so nothing that reads abilities — "creatures with
    vigilance", a removal of all abilities, a copy effect — can see it. Keeping
    them apart in the AST is what stops the difference being lost at the one
    place it is still recoverable.

    The trailing "if …" is a *standing* test rather than one made as the effect
    resolves: Johan's exemption applies for as long as Johan is untapped and
    stops the moment he taps. So it is carried on the node rather than read as
    the enclosing sentence's intervening-if, which would test it once and
    forget it.

    It arrives already reduced to the state word it asks about, because the one
    thing this node's gate can be is a state of the effect's own source — the
    same question "untapped creature you control" asks with an adjective. The
    production refuses any other condition rather than storing it: a
    :class:`~ast.conditions.Condition` here would make this family import the
    conditions module, which is the sideways reach `ast/` is held against, and
    it would be storing a shape that has no reader.
    """

    subject: Recipient
    #: An ``ObjectFilter`` field name — "tapped", "attacking" — or None for an
    #: ungated exemption.
    gate_state: str | None = None
    #: Whether the printed clause negated it ("is **un**tapped").
    gate_negated: bool = False
