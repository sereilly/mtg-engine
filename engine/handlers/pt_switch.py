"""Power/toughness switches (CR 613.4d, layer 7d).

"Switch target creature's power and toughness until end of turn."
(Transmutation.) The layer itself has been live since the P/T channels were
written — ``engine/layer_bridge.py`` reads the ``pt_switched`` flag and
``engine/continuous.py`` applies the swap *after* 7c so two switches cancel and
a later pump is switched too. What was missing was an instruction that sets it.

Its own module rather than more of ``pump.py``: that file is at the
thousand-line boundary the grammar's size guard names as the stop-absorbing
signal, and a switch is not a modification — it takes no delta and gives none
back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..oracle_types import OracleInstruction
from ..pt import switch_pt
from ._common import resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


def _log_switch(game: "Game", source_name: str, perm) -> None:
    game.log.append(
        f"{source_name} switched {perm.card.name}'s power and toughness to "
        f"{perm.effective_power}/{perm.effective_toughness}"
    )


@effect_handler("switch_target_pt_until_eot")
def switch_target_pt_until_eot(
    game: "Game", instruction: OracleInstruction, context: "OracleExecutionContext"
) -> tuple[bool, str]:
    target = resolve_target_permanent(
        game, context, predicate=lambda perm: perm.is_creature
    )
    if target is None:
        game.log.append(f"{context.card.name}: no valid creature target")
        return True, "resolved"
    switch_pt(target)
    _log_switch(game, context.card.name, target)
    return True, "resolved"


@effect_handler("switch_self_pt_until_eot")
def switch_self_pt_until_eot(
    game: "Game", instruction: OracleInstruction, context: "OracleExecutionContext"
) -> tuple[bool, str]:
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    switch_pt(source)
    _log_switch(game, context.card.name, source)
    return True, "resolved"
