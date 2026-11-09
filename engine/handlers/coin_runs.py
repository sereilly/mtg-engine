"""A run of coin flips its flipper may stop (CR 705), one flip per answer.

    "Flip a coin until you lose a flip or choose to stop flipping. If you lose
    a flip, Fiery Gambit has no effect. If you win one or more flips, …"
    (Fiery Gambit.)

The ``flip_coins_until_loss`` kind with ``may_stop`` on its payload, split out
of ``control_flow`` (which sits near the module cap and dispatches here). The
other two runs that kind performs are bounded by a number or by the first loss
alone, and loop inside one call; this one has a **decision between flips** —
the ruling (2004-12-01): "After each flip, you choose whether to continue
flipping" — so each won flip asks the flipper through the ``flip_again``
prompt Game of Chaos already answers, and the answer that goes on runs this
same instruction again with the count so far on its payload. The prompt
suspends the resolution (CR 608.2), so the rewards behind the run wait for the
last answer and read the records the last flip left.

Every flip goes through ``flip_coin_for`` (CR 705.2's won-or-lost flip, a
Krark's Thumb's coins included) and writes the records a run writes:
``coin_flip`` (no flip lost), ``COIN_FLIPS_MADE``, ``COIN_FLIPS_WON`` — and,
for a run printed with "If you lose a flip, <this> has no effect",
``COIN_FLIP_RUN_VOIDED`` on a loss, which every "if you win N or more flips"
reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..oracle_types import (COIN_FLIP_RUN_VOIDED, COIN_FLIPS_MADE,
                            COIN_FLIPS_WON, OracleInstruction)
from ._common import flip_coin, flip_coin_for

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext

#: Where a run its flipper never stops gives up, for ``control_flow``'s
#: ``_UNBOUNDED_FLIP_GUARD`` reason: only a rigged coin reaches it.
_RUN_GUARD = 1000


def flip_until_loss_or_stop(
    game: "Game", instruction: OracleInstruction,
    context: "OracleExecutionContext",
) -> tuple[bool, str]:
    """One flip of the run, and the offer to flip again after a win."""
    payload = instruction.payload
    caster = context.caster
    card_name = getattr(context.card, "name", "an effect")
    made = int(payload.get("made", 0) or 0)
    won = flip_coin_for(game, caster, flip=flip_coin)
    made += 1
    game.log.append(f"{card_name}: {'won' if won else 'lost'} the coin flip")
    context.results["coin_flip"] = won
    context.results[COIN_FLIPS_MADE] = made
    context.results[COIN_FLIPS_WON] = made if won else made - 1
    if not won:
        if payload.get("void_on_loss"):
            # "If you lose a flip, Fiery Gambit has no effect."
            context.results[COIN_FLIP_RUN_VOIDED] = True
            game.log.append(f"{card_name}: a flip was lost, so it has no effect")
        return True, "resolved"
    if made >= _RUN_GUARD:
        return True, "resolved"
    # "…or choose to stop flipping." The offer, for the flipper alone; the
    # stated default (a seat nobody asks) is to stop, taken where it is armed
    # (``FLIP_AGAIN_SPEC.default_at_arm``).
    game.arm_pending_choice(
        "flip_again", game.players.index(caster),
        card_name=card_name,
        flips_won=made,
        _again=OracleInstruction(instruction.kind, "", {**payload, "made": made}),
        _context=context,
    )
    return True, "resolved"
