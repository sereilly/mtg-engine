"""Which recipient key a printed player reference becomes.

A **floor**, not a family, for ``_amounts``' stated reason one file over: two
lowering families ask it -- ``game`` for CR 407's ante and ``life`` for
CR 119.5's "that player's life total becomes N" -- and a leaf several lowerings
read sits below the families however small it is. It arrived here at the split
that made ``life`` a family of its own, where it would otherwise have been one
family importing another or, worse, a second copy of a three-row table.

The table is closed and the miss raises. A seat this cannot name is one the
handler would have to guess at, and a guessed seat is an effect landing on
whichever player the resolution happened to be carrying -- which is the failure
every referent table in this package exists to refuse instead.
"""

from __future__ import annotations

from .. import ast
from ..errors import LoweringError


_ANTE_RECIPIENTS: dict[str, str] = {
    "you": "caster",
    "each_player": "each_player",
    "that_player": "that_player",
}


def _player_recipient(player: "ast.PlayerRef", node) -> str:
    """The recipient key *player* names, or a refusal naming the word."""
    recipient = _ANTE_RECIPIENTS.get(player.kind)
    if recipient is None:
        raise LoweringError(
            f"no seat is named by {player.kind!r} here", node=node
        )
    return recipient
