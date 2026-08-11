"""Lowering combat restrictions (CR 506, 509).

"Can't attack unless …", "can't be blocked by …", and the unblockable grant
whose power limit the handler hardcodes — recorded here as a value so the
lowering can check it rather than assume it.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _REST_OF_TURN,
    _is_target,
    _targets_only,
)


# The restriction `grant_unblockable_to_low_power_target` hardcodes, in
# engine/handlers/combat.py *and* again in engine/legality.py's target
# enumerator. Written out here so the mismatch is checked rather than assumed.
_UNBLOCKABLE_POWER_LIMIT = ast.Comparison("le", ast.Fixed(2))


def _lower_combat_restriction(node: ast.CombatRestriction) -> tuple[OracleInstruction, ...]:
    """``can't attack unless …`` / ``can't block creatures with power N …``.

    Lowers to the instruction kinds the combat steps already dispatch on, with
    the payloads ``engine/combat_restrictions.py`` produces for the legacy path
    — byte for byte, so the differential can hold the two to agreement rather
    than merely to "both did something".
    """
    return (OracleInstruction(node.kind, "", dict(node.payload)),)


def _lower_cant_be(node: ast.CantBe) -> tuple[OracleInstruction, ...]:
    """"Target creature can't be regenerated/blocked this turn."

    Both handlers act on one creature chosen as the ability is activated and
    honour **no** payload filter — they set a flag on whatever
    ``resolve_target_permanent`` returns. So every restriction the noun phrase
    carries has to be checked here or it would be silently dropped, which is why
    the subject's filter is compared for *equality* against the exact shape each
    handler implements rather than probed field by field: a filter field added
    to the AST later cannot slip through an equality check.
    """
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "a restriction with no end-of-turn duration is a static ability, "
            "which needs the CR 613 layers engine",
            node=node,
        )
    if not _is_target(node.subject):
        raise LoweringError("no handler for restricting a non-targeted subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    filt = node.subject.filter

    if node.action == "regenerated":
        if filt != ast.ObjectFilter(card_types=("creature",)):
            raise LoweringError(
                "deny_regeneration_to_target honours no target restriction", node=node
            )
        return (
            OracleInstruction("deny_regeneration_to_target", "", _targets_only(node.subject)),
        )

    if node.action == "blocked":
        # The trap: the handler's "power 2 or less" is a literal in its own
        # source, not something it reads from the payload. A card reading
        # "power 3 or less" would compile cleanly and get the wrong threshold,
        # so the parsed comparison is checked against the hardcoded one.
        if filt.power != _UNBLOCKABLE_POWER_LIMIT:
            raise LoweringError(
                "grant_unblockable_to_low_power_target hardcodes 'power 2 or "
                "less'; no handler implements another threshold",
                node=node,
            )
        if filt != ast.ObjectFilter(card_types=("creature",), power=_UNBLOCKABLE_POWER_LIMIT):
            raise LoweringError(
                "grant_unblockable_to_low_power_target honours no further target "
                "restriction",
                node=node,
            )
        # Deliberately *not* described for engine/targeting.py. `ObjectFilter.
        # to_payload` has no vocabulary for a power comparison, so the
        # description would read "target creature" and the picker would offer
        # creatures the ability cannot legally affect. legality.py keeps
        # answering this one until the description vocabulary grows.
        return (OracleInstruction("grant_unblockable_to_low_power_target", "", {}),)

    raise LoweringError(f"no handler for a {node.action!r} restriction", node=node)
