"""Which recipient key a printed player reference becomes, and what narrowing
it carries.

The two questions are one subject and they arrived a wave apart. A recipient
key says *which* seats a sentence acts on; a narrowing says which **of those**
it acts on, and both are read off the same ``ast.PlayerRef`` by lowerings that
otherwise share nothing. The stampers came down here from ``lowering/damage.py``
at the size guard, on the seam this module's own name draws.

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
from ._common import player_deed_payload, testable_filter_payload


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


def _stamp_recipient_deed(payload: dict, recipient, node) -> None:
    """"…deals 2 damage to **each player who sacrificed a Plains this way**."
    (Desolation.)

    The seat narrowing the recipient printed, carried to the handler that loops
    the seats. Its own two lines rather than a branch inside each arm because
    both seat-set recipients take it identically — what the clause narrows is
    *which of the loop's seats*, and the loop is the only difference between
    the two arms.

    ``player_deed_payload`` raises on a clause it cannot express, which is the
    behaviour this call wants: an unenforced narrowing is a card that damages
    every player, and a card that refuses to compile says so.
    """
    deed = player_deed_payload(recipient, node)
    if deed is not None:
        payload["recipient_did"] = deed

def _stamp_recipient_control(payload: dict, recipient, node) -> None:
    """"…to **each player who controls a white creature**." (Disorder.)

    The board narrowing the recipient printed, carried to the handler that
    loops the seats — the twin of :func:`_stamp_recipient_deed` beside it, and
    beside it for its reason: both seat-set recipients take it identically, and
    what the clause narrows is *which of the loop's seats*.

    Every key of the phrase must be one ``subject_matches`` can test, because a
    narrowing the matcher drops here is a card that damages every player at the
    table — the direction this whole family refuses in.
    """
    described = getattr(recipient, "controls", None)
    if described is None:
        return
    payload["recipient_controls"] = testable_filter_payload(
        described,
        refusal="the seat narrowing cannot test this restriction",
        node=node,
        require_narrowing=False,
    )
