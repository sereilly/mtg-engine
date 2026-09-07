"""Whether one seat answers a printed comparison against another (CR 601.2c).

"…chooses target player **who controls more creatures than they do** and is
their opponent" (Oath of Druids); "Choose target opponent **who has at least
two fewer creature cards in their graveyard than you do** as you activate this
ability" (Keeper of the Dead). Ten Exodus cards over two printed frames and one
question: which seats a sentence is allowed to name.

**This is a picker's question and it has to be, or the clause does nothing.**
A restriction on which targets may be chosen is enforced at announcement or it
is enforced nowhere: an ability whose narrowing is dropped is one that works
*more often than the card allows* — wrong in its controller's favour and
silent, because nothing crashes and nothing is missing. So the clause is
parsed into the ``targets`` description the enumerator reads
(``engine/legality.py``'s seat loop) and answered here, and the lowering that
writes the description refuses any comparison this cannot take
(``grammar/lowering/_targets.player_comparison_payload``) — one table, read by
the gate that admits the card and by the enforcement that answers it, which is
the arrangement ``activation_restrictions.py`` states for a timing clause.

The count itself is **not** re-implemented here. ``handlers/_common``'s
``evaluate_count`` is the engine's one evaluator for "how many of these does
this player have", taken over a spec the ordinary count lowering wrote — so
"more creatures" counts what "the number of creatures you control" counts, and
a card printed about artifacts or about a library needs nothing added.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game


def comparison_reference_seat(
    described: dict,
    *,
    caster_index: int,
    that_player_seat: "int | None",
) -> "int | None":
    """Which seat *described* compares its candidates against, or None.

    "than **you** do" is the seat announcing — the ability's controller, which
    for the Keepers is the player activating it. "than **they** do" is the seat
    the sentence in front of it named, which under the Oaths' trigger is the
    player whose upkeep it is; the fire site froze that seat (CR 603.10) and it
    reaches the picker on the spec, exactly as "that player controls" does.

    None where the reference was never frozen, and the caller must then admit
    **nobody**: a comparison against a seat that does not exist has no answer,
    and offering every player instead is the silent widening this module exists
    to prevent (CR 601.2c).
    """
    return caster_index if described.get("than") == "you" else that_player_seat


def player_comparison_holds(
    game: "Game", seat: int, reference: int, described: dict
) -> bool:
    """Whether *seat* answers the comparison *described* against *reference*.

    "More" and "fewer" are the same arithmetic with the sign turned over, and
    the printed threshold is the margin: a bare "more" is a margin of one and
    "at least two more" is a margin of two, so one comparison covers every
    printing (CR 107.1).

    Both sides go through the one evaluator with the *same* spec, which is what
    makes the sentence mean what it says — "more creature cards in their
    graveyard than you do" compares two graveyards read the same way, where two
    specs could have compared a graveyard against a battlefield.
    """
    from .handlers._common import evaluate_count

    count = described.get("count") or {}
    mine = evaluate_count(game, game.players[seat], dict(count))
    theirs = evaluate_count(game, game.players[reference], dict(count))
    margin = max(1, int(described.get("margin", 1) or 1))
    difference = mine - theirs if described.get("more") else theirs - mine
    return difference >= margin


def seat_answers_comparison(
    game: "Game",
    seat: int,
    described: dict,
    *,
    caster_index: int,
    that_player_seat: "int | None",
) -> bool:
    """Whether *seat* is a legal answer to the whole printed clause.

    The two questions above plus the conjoined one the Oaths print, asked
    together because they are one sentence: which seat this is measured
    against, whether that seat is excluded by "…**and is their opponent**"
    (CR 102.2), and whether the count comes out. A caller that asked two of the
    three would be enforcing two thirds of a printed restriction.

    **One function because there are now two moments.** CR 601.2c asks it while
    the target is being chosen (``legality``'s seat loop, the list the picker
    and the announcement gate share) and CR 608.2b asks it again as the object
    resolves (``legality.stale_comparison_refusal``). A restriction whose
    picker and whose re-check were separate readings is this repo's recurring
    defect; here the *only* way to change what the clause means is to change it
    where both look.

    False where the reference was never frozen or is out of range, which admits
    **nobody**: a comparison against a seat that does not exist has no answer,
    and offering every player instead is the silent widening this module exists
    to prevent.
    """
    reference = comparison_reference_seat(
        described, caster_index=caster_index, that_player_seat=that_player_seat,
    )
    if reference is None or not 0 <= reference < len(game.players):
        return False
    # "…**and is their opponent**" (CR 102.2), relative to the seat the
    # comparison is against and not to the caster — under the Oaths' trigger
    # those are two different players, and reading it as `opponents_only` would
    # have offered the upkeep player their own face.
    if described.get("is_opponent") and seat == reference:
        return False
    return player_comparison_holds(game, seat, reference, described)
