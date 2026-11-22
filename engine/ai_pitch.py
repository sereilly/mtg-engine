"""Whether an AI seat pitches a card whose mana value names the spell's X
(CR 118.9, CR 107.3a), and which card it pitches.

"You may exile a red card with mana value X from your hand rather than pay
this spell's mana cost." (Blazing Shoal; the five Betrayers of Kamigawa
Shoals.) CR 107.3a makes X the caster's announcement and the clause holds the
exiled card to it (``AlternativeCost.exile_from_hand_counts_x``), so a caster
who names the card names the number (``Game.x_named_by_alternative_card``).
The seat never pitched one: it sized X by its lands (``ai_scoring.
_pick_x_value``), and with no mana an X of 0 is a price paid for nothing, so a
Shoal was hard-cast or held.

**A pitch is a different spell, not a cheaper one** — its X is the pitched
card's, which mana may not reach — so it is weighed **beside** the cast paid
in mana, never only where the mana cost cannot be paid (the CR 118.9b reading
``ai_casts._announced_candidate`` gives every other price that is not mana
alone): one candidate per X the hand can name, each built whole by the
cast's own builder (its targets chosen at that X, its rehearsal read at that
X) while :func:`pitching` holds the pitch, and the best-scoring of all of
them, the mana cast included, is the cast (:func:`best_of_the_pitches`).

**What the pitched card costs** is the rehearsal's to weigh: the copy exiles
it, and the standing (``ai_standing.seat_standing``) counts the card gone, so
a pitch wins only where the larger X buys more than a card. **Which card of
an X** is the one least worth holding (``ai_prompt_picks.held_worth``, hand
order between equals) — the ordering ``ai_prompt_readers.
graveyard_price_order`` gives a graveyard paid as a price, asked of a hand:
a card exiled has no road back, so what holding it is worth is what it costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from . import ai_cast_trace as cast_trace

if TYPE_CHECKING:
    from .ai_actions import CastAction
    from .game import Game
    from .models import CardDefinition


#: The most values of X a hand's pitches are weighed at, the largest kept:
#: each is a whole candidate, its targets and rehearsal included.
PITCHES_WEIGHED = 4


@dataclass(frozen=True)
class Pitch:
    """One pitch a candidate is built with: the card at *hand_slot* (its
    place in the hand with the spell still in it) exiled for the alternative
    cost at *alternative_index* among ``Game.applicable_alternative_costs``
    (None where it is the only one), naming *x_value*."""

    hand_slot: int
    x_value: int
    alternative_index: "int | None"
    card_name: str


def _pitch_costs(game: "Game", seat: int, card: "CardDefinition"):
    """``([(index, cost), …], how many apply)``: each alternative cost of
    *card* that exiles a card from hand whose mana value is the X (CR
    107.3a), by its index among the applicable ones — ``([], 0)`` for a card
    printing none (asked of the printed costs first: the board is not
    scanned for every card in a hand)."""
    from .alternative_costs import alternative_costs

    if not any(cost.exile_from_hand_counts_x for cost in alternative_costs(card)):
        return [], 0
    applicable = game.applicable_alternative_costs(seat, card)
    return [
        (index, cost) for index, cost in enumerate(applicable)
        if cost.exile_from_hand_counts_x
    ], len(applicable)


def pitches_to_weigh(
    game: "Game", seat: int, card: "CardDefinition", hand_index: int, *,
    from_zone: str,
) -> "list[Pitch]":
    """The pitches a cast of *card* (at *hand_index* in *seat*'s hand) is
    weighed with: for each X the hand's payers name (the engine's own list,
    ``Game._alternative_cost_payers``, the spell's slot withheld), the payer
    least worth holding — at most :data:`PITCHES_WEIGHED` values of X, the
    largest kept. Empty off the hand, under unenforced mana costs (a pitch
    then saves nothing), and for a card printing no such cost."""
    from .ai_prompt_picks import held_worth
    from .ai_weighed_cast import cast_weighed

    if from_zone != "hand" or not game.enforce_mana_costs or cast_weighed(card) is not None:
        # CR 118.9a: a cast made under a permission already has its price.
        return []
    costs, applicable = _pitch_costs(game, seat, card)
    if not costs:
        return []
    hand = game.players[seat].hand
    best: dict[int, Pitch] = {}
    worth: dict[int, float] = {}
    for index, cost in costs:
        payers = game._alternative_cost_payers(
            seat, cost, spell_hand_index=hand_index, spell=card, x_value=None,
        )
        for slot, held in enumerate(hand):
            if slot == hand_index or not any(held is payer for payer in payers):
                continue
            x_value = game.x_named_by_alternative_card(cost, held)
            if not x_value:
                # An X of 0 is a price paid for nothing (CR 107.3a's choice).
                continue
            value = held_worth(game, seat, held)
            if x_value in best and worth[x_value] <= value:
                continue
            best[x_value] = Pitch(
                hand_slot=slot, x_value=x_value,
                alternative_index=index if applicable > 1 else None,
                card_name=held.name,
            )
            worth[x_value] = value
    kept = sorted(best, reverse=True)[:PITCHES_WEIGHED]
    # Weighed cheapest card first: a later pitch replaces an earlier one only
    # when it scores more, so of two that do the same the cheaper card goes.
    return [best[x] for x in sorted(kept, key=lambda x: (worth[x], -x))]


def pitched_card_price(game: "Game", seat: int, action: "CastAction") -> float:
    """What the card *action* pitches costs its seat **beyond the card**
    the rehearsal already counts (``ai_standing.CARD_WORTH``, flat for every
    card in a hand): what holding it is worth (``ai_prompt_picks.held_worth``,
    the score casting it would get) over a card's worth, or 0 — the term
    ``ai_cast_score.finished_cast_candidate`` subtracts, so a Shoal pitches a
    spare two-drop before a Patron when both name an X that does the job,
    and a bomb is pitched only for what outweighs it. 0 for a cast that
    pitches nothing (``CastAction.alternative_cost_hand_index`` unnamed)."""
    slot = getattr(action, "alternative_cost_hand_index", None)
    if slot is None or action.from_zone != "hand":
        return 0.0
    hand = game.players[seat].hand
    if not 0 <= slot < len(hand):
        return 0.0
    from .ai_prompt_picks import held_worth
    from .ai_standing import CARD_WORTH

    return max(0.0, held_worth(game, seat, hand[slot]) - CARD_WORTH)


def best_of_the_pitches(
    game: "Game", seat: int, card: "CardDefinition", hand_index: int, *,
    from_zone: str, build: "Callable[[], CastAction | None]",
) -> "CastAction | None":
    """The best of *build*'s cast paid in mana and the same builder's cast at
    each pitch :func:`pitches_to_weigh` names (held by :func:`pitching`
    while it builds), or None where none is proposed. The cast in mana wins a
    tie: it spends no card."""
    from .ai_weighed_cast import pitching

    best = build()
    for pitch in pitches_to_weigh(game, seat, card, hand_index, from_zone=from_zone):
        with pitching(card, pitch):
            candidate = build()
        if candidate is not None and (best is None or candidate.score > best.score):
            best = candidate
    return best


def note_the_pitch(pitch: "Pitch") -> None:
    """Record, for whoever is listening, which card the candidate being built
    pitches (``ai_cast_trace.note``)."""
    cast_trace.note(
        f"pitching {pitch.card_name} (hand #{pitch.hand_slot}) for X={pitch.x_value}"
        " (CR 118.9, 107.3a)"
    )


__all__ = [
    "PITCHES_WEIGHED",
    "Pitch",
    "best_of_the_pitches",
    "note_the_pitch",
    "pitched_card_price",
    "pitches_to_weigh",
]
