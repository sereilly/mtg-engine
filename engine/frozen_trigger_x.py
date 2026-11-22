"""A triggered ability's X, counted **as it triggers** (CR 603.3d, 603.10a).

"Kodama of the Center Tree has soulshift X, where X is the number of Spirits
you control." The soulshift rewrite (``engine/soulshift.py``) makes that CR
702.46a's sentence with X for N, and the X **bounds the target**: "return
target Spirit card with mana value X or less". Every other where-clause in the
engine is counted as its effect happens (CR 608.2; ``mixins/oracle_instructions``
substitutes the count at the dispatch point), which is too late here — CR
603.3d chooses a triggered ability's target as it is put on the stack, the
choice has to be judged against a number, and CR 608.2b judges it again at
resolution against the same one. So the lowering marks the count
(``oracle_types.X_COUNTED_AT_TRIGGER``; ``lowering/where_x._lower_counted_at_trigger``)
and this module takes it where the ability triggers — the one road every
triggered ability is put on the stack by, ``_enqueue_triggered_ability`` —
and the number rides the stack object as its ``x_value``, which is what the
target picker (``mixins/stack/trigger_targets``), the resolution re-check and
the dispatcher all read (``oracle_types.announcing_x``,
``substitute_x_bounds``).

**A leaves-the-battlefield trigger looks back** (CR 603.10a): the card's
2005-02-01 ruling — "the gamestate is referenced immediately before the
Soulshift trigger to determine the value of X. Soulshift X includes Kodama of
the Center Tree. So, X is always at least 1" — and a Wrath taking Kodama and two
other Spirits counts all three, since each was there immediately before. The
battlefield count adds what the departure under way has taken off that the
battlefield no longer lists (``Game.looked_back_permanents``), so every road
to the graveyard — a sweep that moves its permanents while they are listed, a
sacrifice or a single destruction that takes one off first, the legend rule —
counts the same set. Taken before the trigger is held for an announcement
(``deferring_triggers``): a Kodama sacrificed to pay a cost is counted while
its departure is still the open one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .oracle_types import X_COUNTED_AT_TRIGGER, X_FROM_COUNT

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game
    from .models import CardDefinition, Permanent
    from .oracle_types import OracleInstruction


def trigger_count_spec(instruction: "OracleInstruction | None") -> dict | None:
    """The where-clause count *instruction* takes as it triggers, or None.

    The top level alone is read: the lowering stamps the spec onto every
    instruction of the sentence, its wrappers included
    (``lowering/_amounts._stamp_x_from_count``), so a nested step never carries
    one its parent does not.
    """
    payload = getattr(instruction, "payload", None)
    spec = payload.get(X_FROM_COUNT) if isinstance(payload, dict) else None
    if isinstance(spec, dict) and spec.get(X_COUNTED_AT_TRIGGER):
        return spec
    return None


def frozen_trigger_x(
    game: "Game",
    instruction: "OracleInstruction | None",
    *,
    controller_index: int,
    source_permanent: "Permanent | None",
    card: "CardDefinition | None",
) -> int | None:
    """The X *instruction*'s where-clause comes to as it triggers, or None
    for an ability that takes no count then.

    Through the resolution's own evaluator (``count_from_payload``) with the
    ability's controller as "you" (CR 109.5) and its source as the source, so
    the count reads the printed noun phrase exactly as the dispatcher would —
    plus the look-back the battlefield scan adds for a spec carrying the flag.
    """
    spec = trigger_count_spec(instruction)
    if spec is None or not 0 <= controller_index < len(game.players):
        return None
    from .game_types import OracleExecutionContext
    from .handlers._amounts import count_from_payload

    stack_card = card if card is not None else getattr(source_permanent, "card", None)
    if stack_card is None:
        return None
    controller = game.players[controller_index]
    context = OracleExecutionContext(
        caster=controller, target=controller, card=stack_card,
        source_permanent=source_permanent,
    )
    return max(0, int(count_from_payload(game, context, spec, instruction)))


__all__ = ["frozen_trigger_x", "trigger_count_spec"]
