"""What a cast candidate scores: **the one place every candidate is finished**,
whichever builder made it.

A builder (``ai_casts._cast_candidate_announcing`` for one mode at one answer
to the optional costs, ``ai_entwine.entwined_cast`` for every mode at once,
``ai_policy._combat_instant_candidate`` for an instant weighed at instant
speed) settles what the cast announces and rehearses it, and hands the
finished announcement here: :func:`finished_cast_candidate` sums what the
cast does (``ai_scoring.cast_score_terms``) and what the zone and the moment
add — :func:`zone_cast_bonus`, :func:`stack_response_bonus` — which no builder
adds for itself. Each of those was once added inline by one builder and not
by its sibling, and the sibling's candidates lost or won for it:

* an entwined Wail of the Nim, scored without the zone's bonus its single
  modes carried, lost to its own best mode out of a graveyard opened until end
  of turn (the zone-cast census at Mirrodin's promotion);
* an instant weighed at instant speed never had the zone's bonus at all, so a
  Lightning Bolt the main phase cast out of such a graveyard was left there at
  the opponent's end step for the hand's copy.

The terms are recorded for whoever is listening (``ai_cast_trace.scored``,
read by ``ai_cast_explain.explain_cast``), so an explanation is this sum's own
parts. ``tests/ai/test_ai_cast_explain.py`` fails a builder that calls the
scorer or an adjustment itself, or builds a ``CastAction`` with a score of its
own.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from . import ai_cast_trace as cast_trace
from .ai_scoring import cast_score_terms, summed_terms
from .ai_weighed_cast import cast_weighed

if TYPE_CHECKING:
    from .ai_actions import CastAction
    from .ai_rehearsal import Rehearsal
    from .ai_weighed_cast import PermittedCast
    from .game import Game
    from .models import CardDefinition


#: What casting from the command zone is worth over casting the same card from
#: hand: a net card. A command-zone cast spends nothing from hand — the
#: commander is CR 903.8's standing extra card — and `_score_cast` already
#: prices a net card at 4.0 (its draw weight), so the same number is used
#: rather than a second opinion about what a card is worth. The tax needs no
#: weight of its own: it is generic mana in the cost, so an unaffordable recast
#: is skipped by the tap planner exactly as any other unaffordable spell is.
COMMAND_ZONE_CAST_BONUS = 4.0

#: What a cast under a permission that **ends** is worth over the same cast
#: from hand ("until end of turn, you may play that card": an Elkin Bottle's
#: card, a graveyard under Yawgmoth's Will). The same net card, for the mirror
#: reason: a hand card not cast this turn is still in hand next turn, and this
#: one is not castable at all — so it goes first. **Not** given to a permission
#: that lasts as long as the card stays put (flashback, CR 702.34a; Yawgmoth's
#: Agenda): that cast will be there next turn, and it competes with the hand
#: on what the spell does — a seat with five lands should not flash a Firebolt
#: back for {4}{R} while it holds a five-drop. A tie between the two goes to
#: the hand (``ai_policy._is_better_cast``).
EXPIRING_PERMISSION_BONUS = COMMAND_ZONE_CAST_BONUS


def zone_cast_bonus(from_zone: str, under: "PermittedCast | None") -> float:
    """What a cast out of *from_zone* under *under* is worth over the same
    cast from hand: `COMMAND_ZONE_CAST_BONUS` from the command zone,
    `EXPIRING_PERMISSION_BONUS` under a permission that ends, else nothing.

    A fact about **where the cast is made from**, not about what the spell
    does, so every candidate of one card in one zone carries it alike — a
    single mode and the entwined cast of every mode (``ai_entwine``) are
    compared on what each does, and an entwined cast scored without it lost
    to its own best bullet out of an opened graveyard while it won from the
    hand (Wail of the Nim, the zone-cast census at Mirrodin's promotion).
    """
    if from_zone == "command":
        return COMMAND_ZONE_CAST_BONUS
    if under is not None and under.zone != "hand" and under.expires:
        return EXPIRING_PERMISSION_BONUS
    return 0.0


def stack_response_bonus(game: "Game", caster_index: int) -> float:
    """What answering the object on top of the stack adds to a cast's score,
    beyond what the cast was measured to do.

    One rule, and it is about whose object that is: a seat does not spend a
    reaction on its own spell. Everything this used to add — six for a
    counterspell that could name the top spell, more for the words "prevent",
    "gain … life" and "destroy" in the card's text — was a guess at what the
    response would be worth, and the candidate's score is now that worth,
    measured. Nothing on an empty stack, which is the main phase's moment.
    """
    if not game.stack:
        return 0.0
    if game.stack[-1].caster_index == caster_index:
        return -0.5
    return 0.0


def finished_cast_candidate(
    game: "Game", seat: int, card: "CardDefinition", action: "CastAction",
    rehearsal: "Rehearsal | None",
) -> "CastAction":
    """*action* with its score: **the one place a cast candidate is scored**,
    whichever builder made it — one mode
    (``ai_casts._cast_candidate_announcing``), the entwined cast
    (``ai_entwine.entwined_cast``), an instant at instant speed
    (``ai_policy._combat_instant_candidate``).

    The score is `ai_scoring.cast_score_terms` — what the cast does, or what
    the permanent is — and then **what the moment and the zone add**, which
    no builder adds for itself: the zone's bonus (`zone_cast_bonus`, read off
    the action's zone and the permission being weighed,
    ``ai_weighed_cast.cast_weighed``) and the stack's
    (`stack_response_bonus`). Each was once added inline by one builder and
    not its sibling: an entwined Wail of the Nim lost to its own best mode out
    of an opened graveyard for want of the zone's bonus (Mirrodin's
    promotion), and an instant weighed at instant speed never had it at all.
    A builder that scores a cast for itself fails
    ``tests/ai/test_ai_cast_explain.py``'s guard.

    The terms are added in the order listed (`ai_scoring.summed_terms`) and
    recorded for whoever is listening (``ai_cast_trace.scored``), so an
    explanation is this sum's own parts.
    """
    terms = cast_score_terms(
        game, seat, card, action.target_player_index, action.x_value, rehearsal,
    )
    terms.append(("zone bonus", zone_cast_bonus(action.from_zone, cast_weighed(card))))
    terms.append(("answering its own spell", stack_response_bonus(game, seat)))
    score = summed_terms(terms)
    finished = replace(action, score=score)
    cast_trace.scored(game, finished, terms, score, rehearsal)
    return finished


__all__ = [
    "COMMAND_ZONE_CAST_BONUS",
    "EXPIRING_PERMISSION_BONUS",
    "finished_cast_candidate",
    "stack_response_bonus",
    "zone_cast_bonus",
]
