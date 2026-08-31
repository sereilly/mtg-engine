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
    # "…can't be blocked **by Walls** this turn." (Tower of Coireall.) The class
    # of blocker the restriction names, as the noun phrase that describes it.
    # None is the unnarrowed printing (Teleport), which is a strictly *larger*
    # restriction — so the two cannot share a lowering, and a narrowing dropped
    # here would make a creature unblockable that the card only makes
    # unblockable by Walls.
    by: Recipient | None = None


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

    ``frees_blocked_attackers`` is the printed clause that follows on three
    cards — ", and creatures it was blocking that had become blocked by only
    that creature this combat become unblocked" (Imprison, and the same
    sentence on Ydwen Efreet and False Orders). It is carried rather than
    consumed because it is not a restatement of the removal: CR 509.1h keeps an
    attacker blocked when its blockers leave combat, so unblocking it is
    something those cards add.
    """

    subject: Recipient
    frees_blocked_attackers: bool = False


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


@dataclass(frozen=True)
class AssignsNoCombatDamage:
    """``<subject> assigns no combat damage <duration>.`` (Floral Spuzzem.)

    CR 510.1's assignment turned off for the creatures the sentence names. Not
    a prevention effect (CR 615) and not a P/T change: the creature still has
    its power, still deals *non*-combat damage, and nothing is "prevented" — the
    combat damage step simply assigns nothing from it. Keeping the three apart
    is what stops a shield's counter being spent or a lord's +1/+1 being lost
    where the card says neither.

    The duration is carried rather than baked in for the reason every other
    node here carries one: "this turn" and "this combat" are the same
    restriction over different windows, and a card printing the second is a
    payload change rather than a second node.
    """

    subject: Recipient
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class ForceChosenCreatureToAttack:
    """``Choose target non-Wall creature the active player has controlled
    continuously since the beginning of the turn. That creature attacks this
    turn if able. Destroy it at the beginning of the next end step if it didn't
    attack this turn.`` (Nettling Imp, Norritt, and Arcum's Whistle's opening.)

    One node for three sentences, because the second and third have nothing to
    read on their own: "that creature" and "it" are both the creature the first
    sentence chose, and the destruction is conditional on what that creature did
    with the requirement the second sentence imposed. Parsed apart, two of the
    three dangle.

    Every printing of this template names the same creature — non-Wall, the
    active player's, controlled since the turn began — and imposes the same
    requirement; what differs between Nettling Imp and Norritt is the activation
    restriction, which is a clause of the *ability* rather than of this effect
    and is read where every other one is.

    ``unless_controller_pays_mana_value`` is Arcum's Whistle, the one printing
    that puts a price on the requirement: "That player may pay {X}, where X is
    that creature's mana value. If they don't pay, …". A field rather than a
    second node because everything after the offer is this effect, unchanged —
    the same requirement, the same delayed destruction, the same chosen
    creature. The price is not carried: it is that creature's mana value on
    every card that prints this, and a number here would be a parameter no
    printing varies.
    """

    unless_controller_pays_mana_value: bool = False


@dataclass(frozen=True)
class ChooseBlocksForDefenders:
    """``You choose which creatures block this combat and how those creatures
    block.`` (Melee.)

    CR 509.1a's *chooser*, substituted. The declaration stays the defending
    player's turn-based action and their creatures are still the ones that
    block — what moves is every decision inside it: which of them block, and
    which attacker each one is assigned to. The two halves of the printed
    sentence are exactly CR 509.1a's two sentences, which is why one node
    carries both rather than a second node for "and how those creatures block".

    ``duration`` is carried for the reason every node in this module carries
    one: "this combat" and "this turn" are the same substitution over different
    windows, and a card printing the second (Master Warcraft) is a payload
    change rather than a second node. Only the combat-scoped window is parsed
    today — the lowering refuses the other, because a turn-scoped one would have
    to survive a combat reset it has no state to survive.
    """

    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class ReassignBlockersBetweenAttackers:
    """``Choose two target blocked attacking creatures. If each of those
    creatures could be blocked by all creatures that the other is blocked by,
    each creature that's blocking exactly one of those attacking creatures stops
    blocking it and is blocking the other attacking creature.`` (General
    Jarkeld.)

    Two printed sentences and one effect, which is why it is a paragraph: the
    second names "those creatures" and "the other", both of which only the first
    sentence supplies, and the first on its own would choose two targets and do
    nothing with them.

    It is the **mirror** of Sorrow's Path, not a second spelling of it. That
    card chooses two *blocking* creatures and swaps what each blocks; this one
    chooses two *blocked attacking* creatures and swaps who blocks each. The
    hypothetical is the same question asked from the other end — "could be
    blocked by all creatures that the other is blocked by" against "could block
    all creatures that the other is blocking" — and both are answered by the one
    gate a real declaration passes.

    "**exactly one** of those attacking creatures" is the clause that keeps this
    from being a plain swap: a creature blocking *both* chosen attackers is
    blocking neither of them exactly once and stays where it is.
    """

    subject: Recipient
