"""Lowering an **ownership** change (CR 108.3, CR 407): who the card goes home to.

Split out of `lowering/zones.py` when two wave-2 branches' additions summed past
the thousand-line guard with neither at fault. The seam is the one that module's
own docstring draws: "everything here answers one question — which zone does
this object end up in". These three answer a different one. Bronze Tablet,
Timmerian Fiends and Tempest Efreet **exchange ownership** — the card may not
move zones at all, and what changes is whose it is when the game ends
(CR 108.3: owner is where the card started, and only an effect like these can
change it).

It reuses the name `grammar/ownership.py` has carried on the parse side since
Alpha's ante cards, so the mirror re-forms instead of forking, and it is a
family rather than a floor: nothing in `lowering/` reads it.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import _describe_targets, _filter_payload


def _lower_ownership_exchange_unless_paid(
    node: "ast.OwnershipExchangeUnlessPaid",
) -> tuple[OracleInstruction, ...]:
    """Bronze Tablet. The life total and the target's noun phrase are payload;
    every other word was required by the production that read it."""
    from ...subject_filters import object_only_filter

    described = _filter_payload(node.target, carried_separately=frozenset({"owner"}))
    described.pop("owner", None)
    if object_only_filter(described) is None:
        raise LoweringError(
            "the ownership exchange cannot test that phrase", node=node
        )
    payload: dict[str, object] = {
        "life": node.life,
        # The ownership half is carried separately from the rest of the filter:
        # the picker and the handler both ask `subject_matches`, which needs the
        # ability's controller to answer "an opponent owns" at all.
        "owner": node.target.owner,
        "filter": described,
    }
    _describe_targets(
        payload,
        ast.TargetSpec("target", node.target, targeted=True),
        carried_separately=frozenset({"owner"}),
    )
    return (OracleInstruction("exchange_ownership_unless_paid", "", payload),)

def _lower_ante_offer_ownership_exchange(
    node: "ast.AnteOfferOwnershipExchange",
) -> tuple[OracleInstruction, ...]:
    """Timmerian Fiends. The printed card type is payload, described the way
    every other object target is so the activation picker, the CR 602.2b
    legality gate and the handler all ask one question."""
    return (
        OracleInstruction(
            "ante_or_exchange_ownership", "",
            {
                "type_word": node.type_word,
                "targets": {
                    "quantifier": "target",
                    "kind": "object",
                    "filter": {"type_filter": node.type_word},
                },
                "type_filter": node.type_word,
            },
        ),
    )

def _lower_random_reveal_ownership_exchange(
    node: "ast.RandomRevealOwnershipExchange",
) -> tuple[OracleInstruction, ...]:
    """Tempest Efreet. The life total is payload; the target is the printed
    "target opponent", described the way every other player target is so the
    activation picker and the handler ask one question."""
    return (
        OracleInstruction(
            "random_reveal_ownership_exchange", "",
            {
                "life": node.life,
                "targets": {
                    "quantifier": "target",
                    "kind": "player",
                    "opponents_only": True,
                },
            },
        ),
    )


#: These three kinds' rows in `lowering/categories.INSTRUCTION_CATEGORIES`,
#: beside what builds them for the reason `zones` gives for its own half: a
#: wrapper belongs next to the thing it wraps.
#:
#: The category stays **"zones"**, and that is the point rather than an
#: oversight. A category names the migration family a *kind* belongs to, not
#: the module its lowering happens to live in, and `GRAMMAR_CATEGORIES` is
#: held equal to the set this table declares — so inventing an "ownership"
#: category here would have left it off that frozenset and, with no fallback
#: underneath, cost Timmerian Fiends and Tempest Efreet their support. It
#: did, for one run: a file split must move no card, and this is the one way
#: a file split can.
OWNERSHIP_INSTRUCTION_CATEGORIES: dict[str, str] = {
    "exchange_ownership_unless_paid": "zones",
    "ante_or_exchange_ownership": "zones",
    "random_reveal_ownership_exchange": "zones",
}
