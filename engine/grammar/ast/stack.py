"""The stack: countering a spell, and choosing a modal one's mode.

Two nodes, both about what happens to an object *on its way onto or off* the
stack rather than about a board change. `unless_pays` and `unpaid_penalty` are
fields on `CounterSpell` rather than statements beside it because both are
performed *by the counter flow, while countering*, and are offered to a
different player than the one whose spell it is — so neither is ever a step of
its own. `ModalNode` is here because a mode is chosen as part of casting a
spell, activating an ability, or putting a triggered ability on the stack
(CR 601.2b, CR 700.2a–b) — never during resolution.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._core import (
    ManaCost,
    PlayerRef,
    TargetSpec,
)


@dataclass(frozen=True)
class ChooseTarget:
    """``Choose target creature.`` / ``Choose target Wall creature.``
    (Reincarnation, Glyph of Life, Glyph of Doom.)

    A sentence whose *whole* content is CR 601.2c's choosing of targets. It
    does nothing on resolution — what happens to the chosen creature is the
    next sentence, which creates a delayed triggered ability about it — and
    that is why it is a node rather than a prefix folded into that sentence:
    the target is chosen as the spell is **cast**, hours of game time before
    the delayed ability exists.

    Here in the stack family for the same reason ``ModalNode`` is: a target is
    chosen while the object is being put on the stack (CR 601.2c, CR 602.2b),
    never during resolution.

    It is never parsed on its own. The production requires the sentence that
    binds the chosen creature to follow it, because a spell whose only
    instruction is this one would target a creature, resolve, and do nothing at
    all while reporting itself supported.
    """
    subject: TargetSpec


@dataclass(frozen=True)
class CounterAbility:
    """``Counter target activated or triggered ability.`` (Sublime Epiphany.)

    CR 701.5a removes the object from the stack and it does nothing. Separate
    from :class:`CounterSpell` because the object is different: a spell has a
    card that goes to its owner's graveyard (CR 701.5a's second sentence), and
    an ability on the stack has no card at all (CR 113.7a) — nothing to move
    and nothing to exile instead.

    It *does* take an "unless its controller pays" clause, which this docstring
    used to deny: Ayesha Tanaka offers one, and the object that waits while the
    payment is decided is the ability rather than a spell. The flow is the same
    one either way, because what waits is a stack object.

    Which kinds are named lives on the subject's filter, so "counter target
    activated ability" is the same node with a narrower phrase.
    """
    subject: TargetSpec
    unless_pays: "ManaCost | None" = None


@dataclass(frozen=True)
class CounterSpell:
    subject: TargetSpec
    # "unless its controller pays {X}" (Power Sink) — CR 118.3c: the spell is
    # countered only if the cost goes unpaid. Modelled as a field rather than a
    # ``Conditional`` because the payment is offered to a *different* player as
    # part of countering, which is the counter flow's job, not a second step.
    unless_pays: ManaCost | None = None
    # The named penalty a card imposes when that cost goes unpaid ("…they tap
    # all lands with mana abilities they control and lose all unspent mana").
    # A name, not a statement: the counter flow performs it while countering,
    # so it never becomes an instruction of its own — but recording *which*
    # penalty was written means lowering can refuse one nothing performs
    # instead of consuming the sentence and dropping it.
    unpaid_penalty: str | None = None
    # "…counter **that spell** unless its controller pays {4} **instead**."
    # (Lofty Denial.) The word is the whole difference between a second counter
    # and a *replacement amount* for the first one, so it is recorded rather
    # than consumed and dropped: without it the sentence pair would ask the
    # spell's controller to pay twice, which is two counters and not this card.
    replaces_prior_amount: bool = False
    # "…**if it would destroy a land you control**" (Equinox). A condition on
    # whether the counter happens at all, asked of the targeted spell as this
    # resolves (CR 608.2). A recorded *name* rather than a `Condition`, for the
    # reason `unpaid_penalty` above is one: what it asks about is the other
    # spell's own effect, which no board-state condition in this grammar can
    # express — so the sentence is read verbatim and
    # `engine/counter_conditions.py` is what answers it, refusing at lowering
    # anything it cannot.
    only_if: str | None = None


@dataclass(frozen=True)
class CopyThatSpell:
    """``Copy that spell. You may choose new targets for the copy.``
    (Double Vision.)

    "That spell" is the one the trigger fired on, not "the topmost instant or
    sorcery" — the two agree whenever nothing has been cast in response and
    part company as soon as something has. So the copy names the event's own
    spell, which the fire site records.

    The new-targets sentence is required, not optional: CR 707.10 lets the
    copy's controller choose new targets, and a card that did not offer the
    choice would be a different card. Consuming it is also what keeps this
    production from claiming a bare "copy that spell" nothing prints.
    """


@dataclass(frozen=True)
class CopySpell:
    """``Copy this spell. You may choose a new target for that copy.``
    (Chain Lightning.)

    The **resolving** spell, not the one a trigger fired on: while a spell is
    resolving this engine has already popped it off ``Game.stack`` (see
    ``mixins/stack/resolution``), so "this spell" is an object no scan of the
    stack can reach — it is ``Game.resolving_items[-1]``. That is the whole
    difference from :class:`CopyThatSpell`, which names an object still up
    there, and the reason the two are separate nodes rather than one with a
    flag: they are copies of different things found in different places.

    *controller* is who gets the copy (CR 707.10a). It is printed as the
    sentence's subject and defaults to the spell's own controller, because
    "Copy this spell" with no subject means you — but Chain Lightning's copy
    goes to the player who paid for it, which is a seat the resolving spell's
    controller may not be.

    *may_choose_new_target* records CR 707.10's offer. Recorded rather than
    consumed and dropped: a copy that could never be re-aimed is a strictly
    different card, and Chain Lightning's whole play is aiming it back.
    """

    controller: PlayerRef
    may_choose_new_target: bool = False


@dataclass(frozen=True)
class ModalNode:
    """The head of a modal spell or ability: "Choose one —" (CR 700.2).

    **It carries no options, and that is the design.** CR 700.2 says the modes
    are "two or more options in a bulleted list *preceded by* instructions for a
    player to choose a number of those options" — so the head and the modes are
    different printed lines, and every bullet is an ordinary effect line this
    parser already reads on its own. A node holding parsed copies of the bullets
    would be a second reading of the same text, free to disagree with the first;
    a node holding their raw strings would be the compiler's line classification
    smuggled into the AST. What the head declares, and all it declares, is *how
    many* of the lines below it the controller chooses.

    That is also why this is a `Statement` rather than an `AbilityNode`. The
    head is printed bare on a spell ("Choose one —"), after an activation cost
    ("{2}: Choose one —", Pyramids) and after a trigger condition ("When this
    creature enters, choose one —"), and the existing line layer already reads
    those three prefixes. As a statement the head slots into all three for free
    and the cost or trigger stays on the node that models it; as an ability node
    it would need its own copies of both fields, and a modal head whose prefix
    was dropped is exactly the silent-rider bug this grammar exists to prevent.

    ``at_least`` is "Choose one **or more** —" (Sublime Epiphany), where
    ``choose_count`` is a floor rather than the count. It is a field rather than
    a separate node so that the lowering has to look at it: the substring match
    it replaces read "choose one or more" as plain "choose one" and built a
    one-mode spell out of it.
    """

    choose_count: int
    at_least: bool = False
