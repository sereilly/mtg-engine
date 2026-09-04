"""Lowering a **bite**: one named object deals damage equal to a characteristic
it still has.

Split out of ``lowering/damage.py`` at Mirage's third wave, the fifth time that
module reached the thousand-line guard, along the line the branches themselves
already drew. Everything left in `damage` computes a **quantity** — a printed
number, a count of a board, a record of an earlier step — and hands it to the
generic ``deal_damage``, whose source is the spell or the ability. A bite reads
one object's **power** at resolution (CR 613's computed value, not the printed
one) and that object is the *dealer*: CR 119.3's damage is dealt by the
creature, so lifelink, "a source you control" and "damage dealt by a creature"
all answer differently from the generic kind. That is why each of these is its
own instruction rather than an amount key.

Who the dealer is, is the axis the kinds are named along:

* ``source_bites_target`` — the ability's own source (or, on an Aura, the
  permanent it enchants, CR 113.7a).
* ``target_bites_target`` — two chosen targets, the biter first.
* ``bound_bites_source`` — a permanent an earlier step of this same effect
  recorded, biting the ability's source.
* ``bound_bites_player`` — the same biter, biting a **player** (Delirium).

A floor rather than a family for ``_amounts``' reason exactly: ``damage`` reads
it and it reads nothing back, and inside a package a module a family imports
cannot itself be one.
"""

from ...oracle_types import ATTACHED_PERMANENT_CONTROLLER, OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _describe_targets,
    _filter_payload,
    _is_enchanted,
    _is_source,
    _is_target,
    _restrictions_beyond,
)
from ._events import _DAMAGED_PERMANENTS


def lower_bite(
    node: ast.DealDamage, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...] | None:
    """The bite *node* describes, or None when no bite reading applies.

    None rather than a raise, because the caller has a dozen readings left to
    try: this is a probe among the branches of one damage lowering, not a
    dispatch point. The refusals inside are the other kind — a sentence that
    *is* a bite and names something no handler can find — and those raise.
    """
    # "Target creature you control deals damage equal to its power to another
    # target creature." (Garruk, Savage Herald's −2.) A fused kind: the biter
    # and the bitten are two chosen targets resolved as a list, and the amount
    # is the biter's power read at resolution — which is why the generic
    # deal_damage cannot carry it.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and node.source.quantifier == "target"
        and len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.TargetSpec)
        and node.recipients[0].distinct_from_prior
        # Both slots are *targets*. "another target creature" and "another
        # creature" are different cards — the second chooses on resolution
        # (CR 601.2c names nothing) — and this kind builds a two-slot cast-time
        # picker, so admitting the untargeted phrase would raise a picker for a
        # choice the card never announces and drop the printed word.
        and node.recipients[0].targeted
    ):
        return (
            OracleInstruction(
                "target_bites_target",
                "",
                {
                    "targets": {
                        "quantifier": "target",
                        "kind": "object",
                        "filter": _filter_payload(node.source.filter),
                        # Two picks: the biter (first), then the bitten — and
                        # they are *differently* restricted. "Target creature
                        # you control deals damage … to **another target
                        # creature**" names the caster's creature and then
                        # anyone's, and one filter for both slots is what made
                        # the picker offer only the caster's for the second:
                        # Garruk's -2 could bite nothing but his own board while
                        # its handler was written to allow either.
                        "filters": [
                            _filter_payload(node.source.filter),
                            _filter_payload(node.recipients[0].filter),
                        ],
                        "count": 2,
                    },
                },
            ),
        )
    # "This creature deals damage equal to its power to target **player** or
    # planeswalker." (Leafkin Avenger.) The recipient is not an object, so the
    # bites handler below — which resolves a permanent — cannot carry it. The
    # generic damage instruction can: what is new is only where the *number*
    # comes from, and that is one payload key rather than a kind.
    # "…**it** deals damage equal to **its** power to **its controller**"
    # (Consuming Ferocity). Three pronouns, one referent, and none of them is
    # the ability's source: the sentence in front of this one put a counter on
    # "enchanted creature", so every "it" behind it is that creature and "its
    # controller" is that creature's seat (CR 608.2h).
    #
    # Read before the source branch below, which cannot tell the two apart —
    # a bare "it" parses to the same spec either way — and gated on the record
    # rather than on the word, because the record is the only thing that says
    # a step of this effect named the attachment. Without it the branch below
    # takes the line and the Aura deals damage equal to *its own* power, which
    # is zero.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and not node.amount.bonus
        and node.source is not None
        and (_is_source(node.source) or _is_enchanted(node.source))
        and len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.PlayerRef)
        and node.recipients[0].kind in ("controller", "that_player")
        and ATTACHED_PERMANENT_CONTROLLER in produced
    ):
        return (
            OracleInstruction(
                "deal_damage", "",
                {
                    "amount_from_attached_power": True,
                    "recipient": ATTACHED_PERMANENT_CONTROLLER,
                },
            ),
        )
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and _is_source(node.source)
        and len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.PlayerRef)
    ):
        payload: dict[str, object] = {"amount_from_source_power": True}
        _describe_targets(payload, node.recipients[0])
        return (OracleInstruction("deal_damage", "", payload),)
    # "It deals damage equal to **its power** to target creature or
    # planeswalker." (Heartfire Immolator.) The source is sacrificed to pay the
    # cost, so by resolution it is in a graveyard — its power is last-known
    # information (CR 608.2), which the Permanent object still carries because
    # nothing off the battlefield touches it. Its own kind rather than the
    # generic damage, because the amount is a *read* rather than a number.
    # …and on an **Aura**, whose biter is the permanent it enchants (Farrel's
    # Mantle): the ability stays the Aura's (CR 113.7a) and the dealer is
    # payload, because an Aura has no power to deal.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and (_is_source(node.source) or _is_enchanted(node.source))
        and len(node.recipients) == 1
        and _is_target(node.recipients[0])
    ):
        assert isinstance(node.recipients[0], ast.TargetSpec)
        payload: dict[str, object] = {}
        _describe_targets(payload, node.recipients[0])
        payload["filter"] = _filter_payload(node.recipients[0].filter)
        if _is_enchanted(node.source):
            payload["biter"] = "attached"
            # "…to **another** target creature": other than the creature
            # *dealing* it — left as ``exclude_self`` the picker excludes the
            # Aura, never on the list, and offers the host as its own victim.
            described = (payload.get("targets") or {}).get("filter") or {}
            if described.pop("exclude_self", None):
                described["exclude_attached"] = True
                payload["exclude_biter"] = True
        # "…its power **plus 2**" (Farrel's Mantle): CR 107.3's constant.
        if node.amount.bonus:
            payload["power_bonus"] = node.amount.bonus
        return (OracleInstruction("source_bites_target", "", payload),)

    # "**That creature** deals damage equal to its power to this creature."
    # (Tracker.) The second half of a printed exchange: the biter is the
    # creature the sentence in front of this one chose, and the bitten is the
    # ability's own source. Its own kind rather than CR 701.14's fight, which
    # this looks like and is not — a fight is all-or-nothing (701.14b), so a
    # source that has left the battlefield stops *both* halves, while these are
    # two sentences and the first one still happened.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and isinstance(node.source, ast.TargetSpec)
        and node.source.quantifier == "that"
        and len(node.recipients) == 1
        and _is_source(node.recipients[0])
        and node.riders == ast.DamageRiders()
    ):
        if _restrictions_beyond(node.source.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound object carries no narrowing the bite could honour",
                node=node,
            )
        if _DAMAGED_PERMANENTS not in produced:
            # The handler reads the biter out of the resolution scratchpad, and
            # with nothing recorded it would deal nothing while the card
            # compiled clean — the discipline every back-reference here follows.
            raise LoweringError(
                f"back-reference to {_DAMAGED_PERMANENTS!r} with no producer "
                "in this effect",
                node=node,
            )
        return (
            OracleInstruction(
                "bound_bites_source", "",
                {"permanents_from": _DAMAGED_PERMANENTS},
            ),
        )

    return None
