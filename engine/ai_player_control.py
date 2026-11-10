"""What an AI seat does with a player it controls (CR 723).

While a player controls another (Mindslaver), the controller makes every
choice and decision the controlled player is allowed to make (CR 723.5) — and
nothing in the rules says those choices must serve the controlled player.
This module is the AI controller's standing policy, and it is a **measured
policy, not a rule**:

* **Nothing optional is played for another seat.** Every chooser the
  simulator and the web AI seat ask for a seat's *optional* play — the land
  drop, a cast, an activation on any of the four doors, a CR 116 special
  action, an action at priority — answers None for a seat it decides for
  without being that seat (:func:`plays_for_another`), and the attack
  chooser declares the fewest attackers the requirements allow. An attack,
  a creature cast, a land played are the controlled player's resources put
  to work, which in a duel works against the controller.
* **What the rules or an object call for is still answered**, by the same
  picks every seat nobody asks gets — and where those picks rehearse, the
  rehearsal measures the **decider's** standing (``ai_rehearsal._rehearse``
  asks :func:`served_seat`), so a "you may …" the controlled seat is offered
  is taken only where it leaves the controller ahead. The picks that do not
  rehearse (a cleanup discard keeps the cards a seat values most) still pick
  as the controlled seat would: a stated limit, not a rule.

A person controlling a seat is asked its decisions instead
(``Game.asks_a_person``); none of this is consulted for them.
"""

from __future__ import annotations


def plays_for_another(game, seat: int) -> bool:
    """Whether *seat*'s decisions are made by another seat right now
    (CR 723.5): the AI choosers propose no optional play for it."""
    decider = getattr(game, "decider_of", None)
    return decider is not None and decider(seat) != seat


def served_seat(game, seat: int) -> int:
    """Whose standing a choice made for *seat* is weighed by: the seat that
    makes its decisions right now (CR 723.5), which is *seat* itself
    whenever nobody controls it."""
    decider = getattr(game, "decider_of", None)
    return seat if decider is None else decider(seat)


__all__ = ["plays_for_another", "served_seat"]
