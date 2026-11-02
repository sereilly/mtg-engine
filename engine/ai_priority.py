"""What a seat nobody asks does with priority at instant speed — **one
answer for every table that plays one**: the AI simulator's priority driver
(``ai_simulator._answer_priority``) and the web app's AI seat
(``web/game_flow._ai_respond_to_priority`` and its own upkeep).

CLAUDE.md: the simulator "plays the engine's turn, never a copy of it". The
web AI seat had a copy of this answer, and the copy was a third of it: it
cast instants whenever it was handed priority and did nothing else — no
ability at instant speed, no graveyard ability, no own-upkeep window — so
the six "Activate only during your upkeep" graveyard abilities (Necrosavant,
Hammer of Bogardan, Shard Phoenix, Ashen Ghoul, …) were the simulator's and
never a web AI's, and the windows the simulator chooses to spend a
deliberation in were not the web's.

Two functions: :func:`instant_speed_window` (which moment this is, or none
worth asking about) and :func:`act_at_priority` (choose, by the choosers the
two drivers share, and carry it out). What a driver records about it — the
simulator's report and log lines — is the driver's own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .ai_graveyard_activations import (
    activate_chosen_graveyard_ability,
    choose_graveyard_activation_action,
    holds_a_graveyard_ability,
)
from .ai_policy import (
    activate_chosen_ability,
    cast_chosen_instant,
    choose_combat_instant_cast_action,
    choose_instant_speed_activation,
    holds_an_ability_it_could_activate,
    holds_an_instant_it_could_pay_for,
)
from .ai_rehearsal import blocks_still_to_come, mid_resolution

if TYPE_CHECKING:
    from .game import Game
    from .models import CardDefinition


def instant_speed_window(game: "Game", seat: int) -> "str | None":
    """Which of the moments a seat nobody asks answers priority in *seat*
    has just been given it in, or None for one it passes in without asking.

    The engine gives every seat priority before each resolution and at each
    step's end (`Game.offer_priority`); this is the choice of which of those
    to spend a deliberation on, in the order of what they are worth:

    * ``"response"`` — an object **another seat** controls is on the stack: a
      counterspell, a shield in front of a burn spell, removal in response to
      a pump. A seat does not answer its own object — it lets it resolve and
      is asked again (CR 117.3c gives it priority first, and it passes).
    * ``"declare_attackers"`` — the declare-attackers step with the attack
      declared and the blocks still to come (CR 508.2,
      ``ai_rehearsal.blocks_still_to_come``), for **every** seat: the
      defender's ambush blocker (a creature with flash), an ability that
      changes who can block whom (gaining flying to block a flier; Swooping
      Talon shedding its own so the creature it provoked can block it; a seat
      that is not defending casts nothing here, ``ai_policy.
      _weighed_at_instant_speed_now``). What is done here is only what adds a
      block, read through the fight (``ai_rehearsal.pays_before_the_blocks``);
      the rest waits for:
    * ``"combat"`` — the declare-blockers step with attackers in it, for
      **both** seats (CR 509.2): the trick that wins a block, the removal that
      kills an attacker, the pump on an unblocked one.
    * ``"end_step"`` — the opponent's end step with the stack empty: removal
      for a creature cast on that turn, a draw that was held up.
    * ``"upkeep"`` — the seat's **own** upkeep with the stack empty, and only
      for an ability of a card in its graveyard (:func:`act_at_priority`):
      most of those print "Activate only during your upkeep" (Necrosavant,
      Shard Phoenix, Ashen Ghoul, Hammer of Bogardan), and a seat that
      answered no upkeep could never activate one. Nothing else is weighed
      there, so every other card is played where it always was.

    Everything else — the opponent's upkeep, the draw step, beginning of
    combat, the combat-damage and end-of-combat steps, a seat's own end step —
    is passed without asking (named in ROADMAP as what is left); the engine
    still gives priority there, so adding one is a line here.
    """
    if game.stack:
        return "response" if game.stack[-1].caster_index != seat else None
    if blocks_still_to_come(game):
        return "declare_attackers"
    if (
        game.current_turn_phase == "combat"
        and game.current_step == "declare_blockers"
        and game.combat_attackers
    ):
        return "combat"
    if game.current_step == "end" and seat != game.active_player_index:
        return "end_step"
    if game.current_step == "upkeep" and seat == game.active_player_index:
        return "upkeep"
    return None


@dataclass
class PriorityAsk:
    """What :func:`act_at_priority` asked on the way, for a driver that
    counts it: whether the moment was one the instant choosers weigh
    (``offered``), and whether the seat held an instant it could pay for, so
    the cast chooser was asked (``weighed``)."""

    offered: bool = False
    weighed: bool = False


@dataclass(frozen=True)
class PriorityAct:
    """What :func:`act_at_priority` did: ``kind`` is ``"cast"``,
    ``"activate"`` or ``"graveyard"``; ``action`` the chooser's action;
    ``result`` the engine's answer; ``card`` the spell cast (a cast only);
    ``answering`` the top of the stack as the seat acted (None on an empty
    stack); ``in_combat`` / ``off_turn`` where the seat acted."""

    window: str
    kind: str
    action: object
    result: object
    card: "CardDefinition | None" = None
    answering: "str | None" = None
    in_combat: bool = False
    off_turn: bool = False

    @property
    def supported(self) -> bool:
        return bool(getattr(self.result, "supported", False))


def act_at_priority(
    game: "Game", seat: int, *, asked: "PriorityAsk | None" = None,
) -> "PriorityAct | None":
    """*seat* has priority: cast what
    `ai_policy.choose_combat_instant_cast_action` chooses or, with no spell
    worth casting, activate what `ai_policy.choose_instant_speed_activation`
    chooses, then an ability of a card in the graveyard
    (`ai_graveyard_activations.choose_graveyard_activation_action`) — and
    carry it out through the executor each chooser shares. None when nothing
    was done.

    Asked only in :func:`instant_speed_window`'s moments, only where no
    resolution is part-way through (a rehearsal cannot be run there, and a
    response nobody weighed is a guess — `ai_rehearsal.mid_resolution`), and
    only once the cheap question has said there is something the seat could
    pay for (`ai_policy.holds_an_instant_it_could_pay_for`,
    `holds_an_ability_it_could_activate`); every chooser rehearses what it
    proposes, and a table asks this dozens of times a turn. In the seat's own
    upkeep only the graveyard is weighed (see :func:`instant_speed_window`).
    """
    window = instant_speed_window(game, seat)
    if window is None or mid_resolution(game):
        return None
    answering = game.stack[-1].card.name if game.stack else None
    where = {
        "answering": answering,
        "in_combat": game.current_turn_phase == "combat",
        "off_turn": seat != game.active_player_index,
    }
    if window == "upkeep":
        return _from_graveyard(game, seat, window, where)
    if asked is not None:
        asked.offered = True
    action = None
    if holds_an_instant_it_could_pay_for(game, seat):
        if asked is not None:
            asked.weighed = True
        action = choose_combat_instant_cast_action(game, seat)
    if action is None:
        # No spell worth casting: an ability, then (a regeneration shield in
        # front of a burn spell, a ping in the opponent's end step), asked
        # the same cheap question first — and then one of a card in the
        # graveyard (Glory in front of a burn spell, Carrionette at the end
        # of the opponent's turn).
        if holds_an_ability_it_could_activate(game, seat):
            activation = choose_instant_speed_activation(game, seat)
            if activation is not None:
                result = activate_chosen_ability(game, seat, activation)
                return PriorityAct(window, "activate", activation, result, **where)
        return _from_graveyard(game, seat, window, where)
    card, result = cast_chosen_instant(game, seat, action)
    return PriorityAct(window, "cast", action, result, card=card, **where)


def _from_graveyard(game: "Game", seat: int, window: str, where: dict) -> "PriorityAct | None":
    """The ability of a card in *seat*'s graveyard the graveyard chooser
    picks — in a response, combat or end-step window only where what it does
    outlasts the turn (``lasting_only``), and in the seat's own upkeep by the
    main phase's rule, since that is the only moment most of them allow —
    carried out; None when there is none."""
    if not holds_a_graveyard_ability(game, seat):
        return None
    action = choose_graveyard_activation_action(
        game, seat, lasting_only=window != "upkeep",
    )
    if action is None:
        return None
    result = activate_chosen_graveyard_ability(game, seat, action)
    return PriorityAct(window, "graveyard", action, result, **where)


__all__ = [
    "PriorityAct",
    "PriorityAsk",
    "act_at_priority",
    "instant_speed_window",
]
