"""A refused cast or activation — the one way one is answered.

CR 733.1: "If a player takes an illegal action or starts to take an action but
can't legally complete it, the entire action is reversed and any payments
already made are canceled. No abilities trigger and no effects apply as a
result of an undone action." An illegal action is undone, not played, and
CR 733.2 hands the player priority back to "redo the reversed action in a legal
way or take any other action". So a refusal is an answer **to the player who
tried**, and nothing else: there is no event for the table to learn of.

The engine had it the other way round. Every refusal site appended its reason
to ``Game.log`` before returning it — and ``game.log`` is one list, served
whole to every seat and spectator (``web/state_view.py``), so a line in it is
an announcement. "insufficient mana for Exalted Angel" about a card in the
actor's hand reached the opponent's payload on every drag-cast from an empty
pool (the client sends the cast first and offers Auto-Tap on that refusal),
and a person who confirmed the printed cost, was refused and then cast the card
face down had named the face-down card. 87 of the 96 refusal sites wrote their
own line.

Now there are two pieces, and neither writes anything:

* :func:`refuse` is the only constructor of a refused result. It returns the
  :class:`Refusal` the site used to build — the same four fields, the reason
  unchanged — and the actor reads it where it always has: the HTTP 400
  ``detail`` the web raises from it, ``SimulationResult.details`` for the AI
  and the simulator (``refused_casts`` is keyed on it). The other seats are
  told nothing; nor is the actor's own log, which is the other seats' too.
* :func:`take_back_refused_attempt` is what the four attempt wrappers
  (``queue_from_hand``, ``queue_permanent_ability``, ``activate_from_hand``,
  ``activate_from_graveyard``) do with a refusal: every line the attempt wrote
  before it was refused is taken back, because it was part of the action that
  was reversed. Measured over the shipped pool (13,458 refused attempts), what
  those lines are is the announcement itself — "chose Human to cast …",
  "… costs less to cast", "…: chose flying" — never a payment: the structural
  guards hold every refusal above the mana payment, which is the first thing
  either path spends (``tests/engine/test_activation_checks_before_costs.py``
  for an activation; ``_cast_onto_stack`` refuses nothing below
  ``_pay_cast_mana``). Only a :class:`Refusal` is taken back. A mana ability
  whose own effect fails as it resolves inline has paid its costs by then, and
  its lines are what happened.

``tests/engine/test_kg2_refusal_seam.py`` holds every refused result to this
module (an AST walk of ``engine/`` and ``web/``) and drives refusals over the
pool to read that each leaves ``game.log`` as it found it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .game_types import SimulationResult

if TYPE_CHECKING:
    from .game import Game


@dataclass
class Refusal(SimulationResult):
    """A ``SimulationResult`` with ``supported`` False that came from
    :func:`refuse` — an action reversed before it was taken (CR 733.1), as
    opposed to one that was taken and did not work."""


def refuse(card_name: str, effect_kind: "str | None", details: str) -> Refusal:
    """The answer to an action that cannot be taken: *details* for the actor,
    and nothing written anywhere a seat reads (see the module docstring)."""
    return Refusal(card_name, False, effect_kind, details)


def take_back_refused_attempt(
    game: "Game", log_mark: int, result: SimulationResult,
) -> SimulationResult:
    """CR 733.1 for the log: when *result* is a :class:`Refusal`, every line
    written since *log_mark* (``len(game.log)`` as the attempt began) belonged
    to the action that was reversed, and goes with it. Returns *result*."""
    if isinstance(result, Refusal):
        del game.log[log_mark:]
    return result
