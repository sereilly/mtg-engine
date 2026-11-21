"""Redistributing life totals (CR 119.7, its rulings).

"Redistribute any number of players' life totals. (Each of those players gets
one life total back.)" (Reverse the Sands.) Every life total in the game is
taken as the spell starts to resolve, and its controller decides which player
gets which (the 2004-12-01 rulings: "You choose which player gets which life
total when the spell resolves", and "You can't split up a life total") — a
permutation of the totals over the players. "Any number of players" is that
same permutation: a player handed their own total back is a player left out.

Asked as one ``player_choice`` per total but the last, in the controller's
seat, lowest total first — "who gets 5 life?" — each offering the players not
yet given one, and only those for whom some legal assignment of what is left
remains (CR 119.7: a player who can't gain life can't receive a higher total).
The last player takes the last total. Then every player moves to theirs at
once, through the gain seam for a rise (so Lich and "whenever you gain life"
see it, the way ``exchange_life_totals`` moves) and a straight loss for a fall.

The controller's stated default — what a seat nobody asks takes — is the
assignment best for it: the highest total its own, the lowest to the opponent
most ahead (``ai_standing.seat_standing``).
"""

from __future__ import annotations

from itertools import permutations
from typing import TYPE_CHECKING

from ..life_prohibitions import life_gain_banned
from .registry import effect_handler

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction

#: The scratchpad key of the *i*-th total's answer (``player_choice``).
_ANSWER_KEY = "redistributed_life_total_{}"


def _may_receive(game, seat: int, total: int) -> bool:
    """CR 119.7: a player who can't gain life can't receive a higher total."""
    player = game.players[seat]
    return not (total > player.life and life_gain_banned(game, player))


def _completable(game, seats: list[int], totals: list[int]) -> bool:
    """Whether *totals* can still be handed out over *seats*, one each, every
    player allowed what they get."""
    return any(
        all(_may_receive(game, seat, total) for seat, total in zip(order, totals))
        for order in permutations(seats)
    )


def _preferred_assignment(game, controller: int, seats: list[int], totals: list[int]):
    """The controller's best legal assignment, as ``{seat: total}``: the
    highest total its own, the lower ones to the opponents most ahead first.
    None when no legal assignment exists."""
    from ..ai_standing import seat_standing

    def value(order) -> tuple:
        given = dict(zip(order, totals))
        mine = given.get(controller, 0)
        # Each opponent's total weighted by how far ahead they stand: the one
        # most ahead should get the least.
        weighted = sum(
            -given[seat] * (1 + seat_standing(game, seat))
            for seat in order if seat != controller
        )
        return (mine, weighted)

    legal = [
        order for order in permutations(seats)
        if all(_may_receive(game, seat, total) for seat, total in zip(order, totals))
    ]
    if not legal:
        return None
    best = max(legal, key=value)
    return dict(zip(best, totals))


@effect_handler("redistribute_life_totals")
def redistribute_life_totals(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Redistribute any number of players' life totals." (Reverse the
    Sands.) See the module docstring."""
    from ..resumption import run_resumable

    card_name = getattr(context.card, "name", "")
    controller = game.players.index(context.caster)
    seats = [index for index, player in enumerate(game.players) if not player.lost]
    # Taken as the spell starts to resolve, lowest first, each with the seat
    # it came from (for the prompt's words and the default).
    owned = sorted(
        ((game.players[seat].life, seat) for seat in seats),
        key=lambda pair: (pair[0], pair[1]),
    )
    totals = [total for total, _seat in owned]
    if len(seats) < 2 or len(set(totals)) < 2:
        game.log.append(f"{card_name}: no life total to move")
        return True, "resolved"
    preferred = _preferred_assignment(game, controller, seats, totals)
    if preferred is None:
        game.log.append(f"{card_name}: no legal way to redistribute the life totals")
        return True, "resolved"
    for index in range(len(totals)):
        context.results[_ANSWER_KEY.format(index)] = None

    def given_so_far(upto: int) -> dict[int, int]:
        given: dict[int, int] = {}
        for index in range(upto):
            seat = context.results.get(_ANSWER_KEY.format(index))
            if isinstance(seat, int) and seat in seats and seat not in given:
                given[seat] = totals[index]
        return given

    def step(which) -> None:
        if which == "apply":
            _apply(game, card_name, seats, totals, given_so_far(len(totals) - 1))
            return
        index = which
        given = given_so_far(index)
        remaining = [seat for seat in seats if seat not in given]
        rest = totals[index + 1:]
        offered = [
            seat for seat in remaining
            if _may_receive(game, seat, totals[index])
            and _completable(
                game, [other for other in remaining if other != seat], rest
            )
        ]
        if not offered:
            return
        # The stated default first, so a seat nobody asks hands the totals
        # out the way the controller would.
        best = next(
            (seat for seat, total in preferred.items()
             if total == totals[index] and seat in offered and seat not in given),
            offered[0],
        )
        offered.sort(key=lambda seat: seat != best)
        came_from = game.players[owned[index][1]].name
        game.arm_player_choice(
            controller,
            card_name=card_name,
            prompt=(
                f"Choose the player who gets {totals[index]} life "
                f"({came_from}'s life total)"
            ),
            result_key=_ANSWER_KEY.format(index),
            seats=offered,
            context=context,
            stated_default=best,
        )

    run_resumable(game, (*range(len(totals) - 1), "apply"), step)
    return True, "resolved"


def _apply(game, card_name: str, seats: list[int], totals: list[int], given: dict[int, int]) -> None:
    """Every player to their new total at once: the last total to the last
    player, then each rise through the gain seam and each fall as a loss."""
    remaining_seats = [seat for seat in seats if seat not in given]
    used = list(given.values())
    left = list(totals)
    for total in used:
        left.remove(total)
    for seat, total in zip(remaining_seats, left):
        given[seat] = total
    if len(given) != len(seats):
        game.log.append(f"{card_name}: the life totals were not redistributed")
        return
    before = {seat: game.players[seat].life for seat in seats}
    for seat, total in given.items():
        player = game.players[seat]
        if total > player.life:
            game._gain_life(player, total - player.life, card_name)
        elif total < player.life:
            player.life -= player.life - total
    game.log.append(
        f"{card_name}: life totals redistributed ("
        + ", ".join(
            f"{game.players[seat].name} {before[seat]} -> {game.players[seat].life}"
            for seat in seats
        )
        + ")"
    )


__all__ = ["redistribute_life_totals"]
