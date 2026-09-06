"""Lowering combat **requirements** — CR 508.1d and CR 509.1c, "attacks/blocks
if able".

Split off ``lowering/combat.py`` when Tempest's second wave took that module
past the thousand-line guard on Trumpeting Armodon's and Magnetic Web's block
requirements — the second time the guard has fired on that module and the
second time the line was already drawn. ``prohibitions`` left it on the printed
voice; this leaves it on the CR's own pair of words. CR 506.3 names exactly
two things an effect can do to a declaration: a **restriction** says a creature
*can't*, and a **requirement** says it *must*. Everything left in ``combat``
lowers the first, plus the permissions that lift one; everything here lowers
the second.

The distinction is not stylistic, and CR 509.1c is where it shows: a
requirement is obeyed "to the maximum possible number **without disobeying any
restrictions**", so the two are asked in a fixed order at every enforcement
site and neither can be written as the negation of the other.

It completes ``permissions``/``prohibitions``' pair into the trio the rules
use — may, may not, must — and takes the third name from the same place they
took theirs. A **lowering-only** family, like ``zones``, ``library`` and
``mana``: the parse side keeps both productions in ``effects/combat.py``, where
each is one branch of a verb table, and it is the lowerings that outgrew the
cap.

A family rather than a floor: ``combat`` does not read it —
``grammar/by_node.py`` reaches both lowerings directly, one layer up — so
nothing here is below anything and no lowering family imports it.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _describe_targets, _is_source, _names_several_targets, _restrictions_beyond,
    testable_filter_payload,
)


#: Trigger events whose fire site records the **attacking** creature, so
#: "…block *that creature* this turn if able" (Magnetic Web) names it. A subset
#: of `_EVENT_SUBJECT_OBJECTS` rather than that set itself: the pronoun here
#: has to name an attacker, and most of those events are about a permanent that
#: entered, was tapped or was dealt damage — none of which is in combat at all,
#: so a requirement aimed at one would compel a block nobody could make.
_BOUND_ATTACKER_EVENTS = frozenset({"matching_creature_attacks"})


def _lower_force_chosen_creature_to_attack(
    node: ast.ForceChosenCreatureToAttack,
) -> tuple[OracleInstruction, ...]:
    """Nettling Imp / Norritt's three sentences, as the one instruction the
    engine already had a handler, a target spec and a legality rule for.

    Fused rather than composed into a ``sequence``, and this is the shape the
    composition rule asks for rather than an exception to it: the second and
    third sentences have no subject of their own to compose over — both name
    the creature the first one chose — and the third is conditional on what
    that creature did about the second. Three instructions would need a
    scratchpad key to pass the chosen creature between them and a fourth to
    remember the requirement, which is a fused instruction with extra steps.

    Arcum's Whistle puts a price on it — "That player may pay {X}, where X is
    that creature's mana value. **If they don't pay**, …" — and that half *is*
    composed, through the ordinary offer: the requirement is the offer's
    declined branch and nothing else about it changes. ``that_player`` is the
    seat the ability's own target names (the creature's controller, which this
    template's noun phrase already fixes as the active player), and the price is
    the one computed amount every other offer carries.
    """
    requirement = OracleInstruction("mark_non_wall_target_to_attack", "", {})
    if not node.unless_controller_pays_mana_value:
        return (requirement,)
    return (
        OracleInstruction("may", "", {
            "actor": "that_player",
            "cost": {"generic": "x"},
            "x_from_count": {
                "object_characteristic": {
                    "object": "target", "characteristic": "mana_value",
                    "offset": 0,
                },
            },
            # The **declined** branch, which is where the target lives:
            # `targeting._from_instructions` reads an offer's `otherwise` last
            # and for exactly this reason — CR 601.2c picks the creature as the
            # ability is activated, before anyone is offered the payment.
            "otherwise": (requirement,),
        }),
    )


def _lower_attacks_this_turn_if_able(
    node: ast.AttacksThisTurnIfAble,
) -> tuple[OracleInstruction, ...]:
    """CR 508.1a's requirement for one turn, on the source or on a chosen
    creature.

    "…this creature deals 3 damage to you **and attacks this turn if able**"
    (Kookus) names its own source and needs no picker. "**Target creature**
    attacks this turn if able." (Boiling Blood) names one the caster chose, and
    the note that used to stand here — "a targeted spelling would need a
    picker" — was the work item rather than the reason: the picker falls out of
    the ``targets`` description, because ``targeting._from_targets_payload``
    reads a description into a spec for any kind that carries one.

    Two kinds rather than one with an optional target, because the two answer
    "which permanent?" in different places: the source is on the context and a
    chosen creature is a target CR 601.2c fixed at announcement, and a single
    kind would have to guess which it was handed.

    Not the printed static ``engine/combat_restrictions.py`` reads for "attacks
    **each combat** if able": that one holds for as long as the permanent is on
    the battlefield and this ends with the turn (CR 611.2a). The production in
    front of this one refuses the "each combat" spelling in the *parse*, which
    is what leaves the table its line.
    """
    if _is_source(node.subject):
        return (OracleInstruction("force_self_to_attack_until_eot", "", {}),)
    if isinstance(node.subject, ast.TargetSpec) and node.subject.targeted:
        if _names_several_targets(node.subject):
            raise LoweringError(
                "the attack requirement marks one creature; nothing here "
                "collects several",
                node=node,
            )
        described = testable_filter_payload(
            node.subject.filter,
            refusal=(
                "the attack requirement is enforced against the chosen "
                "creature, so a narrowing the matcher cannot test would be "
                "dropped and the picker would offer creatures the card "
                "never names"
            ),
            node=node,
            require_narrowing=False,
        )
        payload: dict[str, object] = {}
        _describe_targets(payload, node.subject)
        if described.get("type_filter") != "creature":
            # CR 508.1a is about creatures; a noun phrase this lowering cannot
            # confirm names one would put the mark on a permanent that can
            # never meet the requirement.
            raise LoweringError(
                "an attack requirement names a creature", node=node
            )
        return (
            OracleInstruction("force_target_to_attack_until_eot", "", payload),
        )
    raise LoweringError(
        "no handler makes that subject attack this turn", node=node
    )


def _lower_blocks_this_turn_if_able(
    node: ast.BlocksThisTurnIfAble,
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """CR 509.1c's requirement for one turn, on named creatures and aimed at one
    named attacker (Trumpeting Armodon, Magnetic Web).

    Two halves, and both are checked here rather than trusted.

    The **attacker** is what must be blocked, and there are two referents. The
    ability's own source is Trumpeting Armodon's; "that creature" is the
    object the trigger's event was about (Magnetic Web's attacker), which only
    resolves under an event whose fire site records one — on any other trigger
    the handler would find nothing and the card would compile clean while
    compelling nobody. A block is a pair (CR 509.1a) and a requirement whose
    second half was dropped would compel the creature to block anything at all.

    The **subject** is who must block: a *target*, so the picker falls out of
    the ``targets`` description exactly as it does for the attack twin, or a
    quantified noun phrase, which reaches every creature it describes and so
    carries no picker at all.
    """
    if isinstance(node.attacker, ast.TargetSpec) and _is_source(node.attacker):
        attacker = "source"
    elif (
        isinstance(node.attacker, ast.TargetSpec)
        and node.attacker.quantifier == "that"
        and not _restrictions_beyond(
            node.attacker.filter, frozenset({"card_types"})
        )
    ):
        if event not in _BOUND_ATTACKER_EVENTS:
            raise LoweringError(
                "\"that creature\" is the attacker this trigger's event was "
                "about, and this event records none",
                node=node,
            )
        attacker = "bound"
    else:
        raise LoweringError(
            "the block requirement names one attacker, and neither the "
            "ability's source nor a bound attacker is what this names",
            node=node,
        )
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("all", "each")
    ):
        # "**All creatures with magnet counters on them** block that creature
        # this turn if able." (Magnetic Web.) Every creature the noun phrase
        # describes, so there is nothing to target and nothing for a picker to
        # ask — the filter travels as `subject` and the handler sweeps the
        # board with it, through the same `subject_matches` every other
        # printed noun phrase goes through.
        described = testable_filter_payload(
            node.subject.filter,
            refusal=(
                "the block requirement is enforced against every creature the "
                "phrase describes, so a narrowing the matcher cannot test "
                "would compel a strictly larger set than the card names"
            ),
            node=node,
            require_narrowing=False,
        )
        if described.get("type_filter") != "creature":
            raise LoweringError(
                "a block requirement names a creature", node=node
            )
        return (
            OracleInstruction(
                "force_subject_to_block_until_eot", "",
                {"attacker": attacker, "subject": described},
            ),
        )
    if not (
        isinstance(node.subject, ast.TargetSpec) and node.subject.targeted
    ):
        raise LoweringError(
            "no handler makes that subject block this turn", node=node
        )
    if attacker != "source":
        raise LoweringError(
            "a targeted block requirement resolves only against the ability's "
            "own source",
            node=node,
        )
    if _names_several_targets(node.subject):
        raise LoweringError(
            "the block requirement marks one creature; nothing here collects "
            "several",
            node=node,
        )
    described = testable_filter_payload(
        node.subject.filter,
        refusal=(
            "the block requirement is enforced against the chosen creature, so "
            "a narrowing the matcher cannot test would be dropped and the "
            "picker would offer creatures the card never names"
        ),
        node=node,
        require_narrowing=False,
    )
    if described.get("type_filter") != "creature":
        # CR 509.1a is about creatures; a noun phrase this lowering cannot
        # confirm names one would put the mark on a permanent that can never
        # meet the requirement.
        raise LoweringError("a block requirement names a creature", node=node)
    payload: dict[str, object] = {"attacker": attacker}
    _describe_targets(payload, node.subject)
    return (
        OracleInstruction("force_target_to_block_until_eot", "", payload),
    )
