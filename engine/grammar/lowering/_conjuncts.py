"""One printed damage sentence that names **several** things.

The mirror of ``grammar/conjuncts.py`` one package over, and named for it: that
module reads the trailing clauses joined onto a sentence's printed subject, and
this one lowers the two shapes a *damage* sentence reaches by the same
grammatical route — several recipients under one clause ("…to **you and each
creature you control**", Sorrow's Path) and several whole clauses under one
source ("…1 damage to any target, 2 damage to another target, **and** 3 damage
to a third target", Cone of Flame).

Split out of ``damage.py`` at the thousand-line guard, along the boundary that
module's own docstring already drew — it lists "damage conjunctions" as one of
the four things it holds, and this is that one. A **floor**, not a family, for
``_sweeps``' reason exactly: ``damage`` imports it and nothing here imports
back.

Nothing here imports back **because the callback is an argument**. Every shape
in this module ends by lowering its pieces as ordinary damage clauses, which is
``damage.py``'s own entry point, so ``lower_damage`` is passed in — the same
arrangement ``statement_dispatch`` uses for ``_lower_steps``'s
``lower_statement``. Importing it instead would make a floor read its family,
which is the one direction
``test_families_import_only_their_package_shared_module`` forbids.

The question these two shapes share is CR 601.2c's: **how many choices did the
sentence announce?** One printed clause naming several recipients announces at
most one, so it may be split into an instruction each; two printed clauses
announce their own, so they may not be fused into one picker. Every refusal
below is that rule read in one of the two directions.
"""

from __future__ import annotations

import dataclasses
from typing import Callable

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (_amount_payload, card_divided_shares_payload,
                      _targets_payload)

#: What ``damage.py`` hands in: its own ``_lower_damage``, so a piece of a
#: multi-recipient sentence is lowered by exactly the function a card printing
#: that piece alone would reach.
LowerDamage = Callable[..., "tuple[OracleInstruction, ...]"]


def lower_split_recipients(
    node: ast.DealDamage,
    event: str | None,
    produced: frozenset[str],
    event_subject: object | None,
    lower_damage: LowerDamage,
) -> tuple[OracleInstruction, ...]:
    """"…it deals 2 damage to **you and each creature you control**."
    (Sorrow's Path.)

    One printed clause naming several recipients, and no sweep handler that
    batches exactly this set. Lowered as one instruction per recipient — the
    composition rule this engine already applies to "deal damage, then gain
    that much life" — rather than as a fused kind per printed pairing, which is
    what the legacy compiler did and is combinatorial in the number of shapes.
    `_sweep_kind` is asked first, so the three sets that *do* have a batching
    handler keep it.

    CR 120.4 makes the printed clause one event and this makes it several. What
    that can be seen through is a state-based action, and none runs between two
    steps of one resolution (CR 704.3) — so simultaneous lethal damage still
    kills together, which is the property the fused sweeps were written for.

    The split is only legal where nothing is *chosen*. A target is announced
    once, as the object is put on the stack (CR 601.2c); two instructions each
    describing one would raise two pickers for one printed choice, and the
    second would be collected against a target the card never announced. So a
    chosen recipient refuses here, and a sentence with two whole printed clauses
    — each announcing its own targets — goes through the conjunction below
    instead.
    """
    if node.riders != ast.DamageRiders():
        raise LoweringError(
            "a multi-recipient damage clause carries no riders", node=node
        )
    named = [r for r in node.recipients if _targets_payload(r) is not None]
    if len(named) == 1:
        # "…deals X damage to **target player or planeswalker** and **each
        # creature that player or that planeswalker's controller controls**."
        # (Heart of Bogardan.) One printed choice, not two: the second half is
        # a *description* keyed to the object the first half named, so the
        # split raises one picker and the sweep reads the seat it announced.
        return _lower_target_and_its_board(
            node, named[0], event, produced, event_subject, lower_damage
        )
    if named:
        raise LoweringError(
            "multi-recipient damage without a sweep shape cannot name a target",
            node=node,
        )
    lowered: tuple[OracleInstruction, ...] = ()
    for recipient in node.recipients:
        lowered += lower_damage(
            dataclasses.replace(node, recipients=(recipient,)),
            event, produced, event_subject,
        )
    return lowered


#: The pronoun a described set uses for the recipient its own sentence targeted,
#: and the seat key the matcher answers it with. Rewritten rather than passed
#: through, because ``that_player`` is what a *trigger's frozen event* means
#: everywhere else in this file — and on Heart of Bogardan that seat is the
#: player who failed to pay, which is a different player from the one the
#: ability targets whenever the card is played the way it is meant to be.
_ANTECEDENT_SEAT_KEY = "target_player"


def _lower_target_and_its_board(
    node: ast.DealDamage,
    named: ast.Recipient,
    event: str | None,
    produced: frozenset[str],
    event_subject: object | None,
    lower_damage: LowerDamage,
) -> tuple[OracleInstruction, ...]:
    """"…to target player or planeswalker **and each creature that player …
    controls**." (Heart of Bogardan.)

    The shape :func:`_lower_split_recipients` refuses one recipient short of:
    there *is* a chosen recipient, but only one, and every other recipient is a
    set described relative to it. So the split raises exactly one picker — the
    thing CR 601.2c/603.3d allow only once — and the sweep asks the matcher for
    the seat that picker announced.

    Every refusal below is a way the sentence could otherwise reach further
    than it names:

    * a described half that narrows by anything but the pronoun is a phrase
      whose antecedent this cannot prove is the target, and reading it as one
      would burn a board the card never pointed at;
    * a half that is not a sweep at all ("target player and target creature")
      is two printed choices and belongs to the refusal above;
    * the printed riders are already refused for the whole shape by
      :func:`_lower_split_recipients`'s first check.
    """
    rewritten: list[ast.Recipient] = []
    for recipient in node.recipients:
        if recipient is named:
            rewritten.append(recipient)
            continue
        if not (
            isinstance(recipient, ast.TargetSpec)
            and recipient.quantifier == "each"
            and not recipient.targeted
            and recipient.filter.controller == "that_player"
        ):
            raise LoweringError(
                "a described half of a targeted damage clause must be the set "
                "the target controls",
                node=node,
            )
        rewritten.append(
            dataclasses.replace(
                recipient,
                filter=dataclasses.replace(
                    recipient.filter, controller=_ANTECEDENT_SEAT_KEY
                ),
            )
        )
    # "…or that **planeswalker's controller**" — the one printed clause whose
    # target may be an object rather than a seat, and it says which seat that
    # then means. Carried as payload so the sweep resolves it only where the
    # card printed the word: a sweep that inferred a controller from any
    # permanent target would answer a seat for sentences that never named one.
    walks = isinstance(named, ast.PlayerRef) and named.or_planeswalker
    lowered: tuple[OracleInstruction, ...] = ()
    for recipient in rewritten:
        for instruction in lower_damage(
            dataclasses.replace(node, recipients=(recipient,)),
            event, produced, event_subject,
        ):
            if walks and instruction.kind == "deal_damage_each_matching":
                instruction = OracleInstruction(
                    instruction.kind, instruction.value,
                    instruction.payload | {"target_controller_if_permanent": True},
                )
            lowered += (instruction,)
    return lowered


def lower_damage_conjunction(
    node: ast.Conjunction,
    event: str | None,
    produced: frozenset[str],
    event_subject: object | None,
    lower_damage: LowerDamage,
) -> tuple[OracleInstruction, ...]:
    """Two damage clauses sharing a source.

    The legacy compiler minted a dedicated instruction kind per pairing
    (``deal_damage_and_self_damage``, ``deal_damage_and_opponent_choice``) —
    28 of its 120 kinds were conjunctions like these, which is combinatorial in
    the number of effects. Here the first shape decomposes into two ordinary
    damage instructions and the kind disappears.
    """
    # "Cone of Flame deals 1 damage to any target, 2 damage to another target,
    # and 3 damage to a third target." One announcement, so one instruction
    # (`card_divided_shares_payload` states every condition and why).
    shared = card_divided_shares_payload(node.effects)
    if shared is not None:
        return (OracleInstruction("deal_damage", "", shared),)
    if len(node.effects) != 2:
        # A run of three the fuse declined. Refused by name rather than
        # destructured into two below, which is a ValueError at import-shaped
        # distance from the card that caused it.
        raise LoweringError(
            "no handler deals three damage clauses of one sentence", node=node
        )
    first, second = node.effects
    assert isinstance(first, ast.DealDamage) and isinstance(second, ast.DealDamage)

    # "…and N damage to any target of an opponent's choice" keeps its dedicated
    # handler: the second target is chosen by a different player, which needs
    # the pending-prompt machinery rather than a second instruction.
    if second.chooser is not None:
        return (
            OracleInstruction(
                "deal_damage_and_opponent_choice", "",
                {
                    "amount": _amount_payload(first.amount),
                    "opponent_amount": _amount_payload(second.amount),
                },
            ),
        )
    # The trigger travels into both halves. Without it a "that creature's
    # controller" printed as one arm of a conjunction fell through to
    # `target_player` — a *choice* the card never offers, resolved against
    # whatever the resolution context happened to carry — while the identical
    # clause printed alone read the seat the fire site froze. One phrase, two
    # readings, decided by whether a second clause was printed beside it:
    # exactly the fragment fork `statement_dispatch`'s own docstring says the
    # threading exists to prevent (Gloom Sower), reintroduced by the one branch
    # that dropped the argument on its way down.
    return (
        lower_damage(first, event, produced, event_subject)
        + lower_damage(second, event, produced, event_subject)
    )
