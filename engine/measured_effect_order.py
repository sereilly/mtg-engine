"""CR 616.1e's default for a **damage** event, measured rather than stated.

"The affected object's controller (or its owner if it doesn't have a
controller) or the affected player chooses one to apply" (CR 616.1). A seat
nobody asks — an AI or headless seat, or a person whose prompt is answered by
its default — took ``effect_ordering.choose_effect``'s *stated* order: the
lowest registration order, a multiplier ahead of a cap. Any order is a legal
set of choices, and the orders are picked to be the one the player would
usually want, but one number per effect cannot see the board: Veteran
Bodyguard's redirect (order 1) went ahead of the Circle of Protection the
same player had just armed against the attacker, so the Bodyguard took the
Craw Wurm's 6 and died, where the Circle first would have prevented all of it
and kept both.

So the default is measured: each applicable effect is applied **first** on a
scratch copy (``ai_scratch_copy.scratch_copy_with``, the event carried into
it), the copy's contention set is rebuilt there by the event itself
(``damage_events.deal_damage`` gathers ``damage_candidates`` on the copy, the
first choice the recorded answer a person's prompt leaves,
``Game.effect_order_answers``), the rest of the process takes the stated
order, the result is applied, and what the affected seat **lost** is read
(``ai_standing.seat_standing``, before and after). The first choice costing
it least is the default; a tie keeps the stated one, so a board where the
order changes nothing plays exactly as it did.

**A loss, not a gain.** What an effect left unspent is worth is unknowable —
the stated bands put a blanket ahead of a consumable so the consumable
survives damage that was never going to land — so a first choice that only
*gains* (Reverse Damage spent where a Fog would have stopped the damage, for
the life) ties with one that changes nothing, and the stated order stands.
The measurement overrides the bands only where they cost the seat something
another order avoids: a creature lost, life lost.

Measured where it can be, stated where it cannot:

* only the **first** contended round — once one effect has been applied the
  process is no longer pure (``apply_in_order``'s docstring), and the copy
  would have to start part-way;
* not on a table held for an answer (``ai_scratch_copy.held_for_an_answer``):
  what it owes is closures over the original;
* not inside a measurement (a redirect's moved damage contending on the copy
  takes the stated order), so a measurement never nests;
* the module's random state is put back afterwards, so a seeded game is
  reproduced exactly whatever was measured;
* a source-keyed shield's additional effect deferred to its dealing's finish
  (``simultaneous_damage.defer_afterward``) is not seen — the copy's dealing
  is never finished.

Damage only. Every other replacement kind (a draw, a zone change) has no
result this can apply on the copy without its caller, and keeps the stated
order.
"""

from __future__ import annotations

import random

from .effect_ordering import Candidate, choose_effect

#: Set on a measurement's copy: what contends there takes the stated order.
MEASURING = "_measuring_effect_order"
#: Two first choices whose standings differ by less than this are a tie.
_TIE = 1e-6


def measured_damage_default(
    game, chooser_index: int | None, applicable: list[Candidate], event: dict,
) -> Candidate:
    """The first effect to apply to damage *event* for a seat nobody asks: the
    one whose whole process costs *chooser_index* least, measured on scratch
    copies; ``choose_effect``'s stated order on a tie and wherever nothing can
    be measured."""
    from .ai_standing import seat_standing

    stated = choose_effect(game, chooser_index, applicable)
    if not _measurable(game, chooser_index, applicable):
        return stated
    before = seat_standing(game, chooser_index)
    scores = {}
    for candidate in applicable:
        score = _score(game, event, candidate.key, chooser_index, before)
        if score is None:
            return stated
        scores[candidate.key] = score
    best = max(scores.values())
    if scores[stated.key] >= best - _TIE:
        return stated
    return min(
        (c for c in applicable if scores[c.key] >= best - _TIE),
        key=lambda candidate: candidate.order,
    )


def _measurable(game, chooser_index, applicable) -> bool:
    from .ai_scratch_copy import held_for_an_answer

    if chooser_index is None or len(applicable) < 2:
        return False
    if getattr(game, MEASURING, False):
        return False
    return not held_for_an_answer(game)


def _score(game, event: dict, key: str, seat: int, before: float) -> float | None:
    """What *seat* lost (a number at most 0) once *event* has been dealt with
    the effect *key* applied first, on a scratch copy, against its standing
    *before*; None when the copy's event stopped to ask (it cannot, every
    copy seat being non-interactive, and is read as nothing measured)."""
    from .ai_scratch_copy import _detach, scratch_copy_with
    from .ai_standing import seat_standing
    from .damage_events import damage_kind, deal_damage
    from .models import PlayerState

    state = random.getstate()
    try:
        clone, carried = scratch_copy_with(game, dict(event))
        _detach(clone)
        setattr(clone, MEASURING, True)
        recipient = carried["recipient"]
        clone.effect_order_answers[(damage_kind(recipient), seat)] = (key,)
        outcome = deal_damage(clone, carried, restart=lambda: None)
        if outcome.suspended:
            return None
        if outcome.result > 0:
            if isinstance(recipient, PlayerState):
                recipient.life -= outcome.result
            elif clone.is_on_battlefield(recipient):
                recipient.damage_marked = int(recipient.damage_marked or 0) + outcome.result
        clone.check_state_based_actions()
        return min(0.0, seat_standing(clone, seat) - before)
    finally:
        random.setstate(state)
