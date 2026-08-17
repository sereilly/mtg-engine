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
    TargetSpec,
)


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
