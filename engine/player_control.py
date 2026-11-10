"""Controlling another player (CR 723) — who makes a seat's decisions.

"You control target player during that player's next turn." (Mindslaver.)
Only control of the **player** changes (CR 723.3): every permanent, spell and
ability keeps its controller, the controlled player is still the active
player, and their cards and mana are still the only ones their costs are paid
with (CR 723.5a). What moves is who answers for the seat — every choice and
decision the rules or an object asks of it (CR 723.5) — while the controller
goes on answering for itself (CR 723.8).

**One question, asked where a decision is handed to a seat.** :func:`decider_of`
answers "which seat decides for this seat right now", and
:func:`asks_a_person` "is a person asked this seat's decisions" — the second is
what every reader of ``Game.interactive_seats`` asks about a particular seat
(``tests/engine/test_player_control_seam.py`` holds the membership spelling
to this module). ``interactive_seats`` keeps its own meaning: the seats a
person sits at.

The record is two ``Game`` fields:

* ``player_controls_waiting`` — ``{controlled seat: controller seat}``, written
  as the effect resolves. Keyed by the controlled seat, so a later effect
  overwrites an earlier one (CR 723.1a: "the last one to be created is the one
  that works").
* ``player_controls`` — ``{controlled seat: (controller seat, turn)}``: the one
  control in force. Made as the controlled seat's turn begins
  (``begin_turn_bookkeeping``), which is after the turns that were skipped have
  been spent (``_compute_next_active_player``), so the effect waits for the
  next turn the player actually takes (CR 723.1b). Dropped as the next turn
  begins (CR 723.1: "the effect doesn't end until the beginning of the next
  turn"). Stamped with the turn number, because the web's Time Vault decline
  begins a turn twice and the second beginning is not the next turn.

Neither field is bookkeeping for ``ai_rehearsal.position_digest``: the pending
record is the whole of what resolving the effect does, and the control in
force moves only at a turn boundary.
"""

from __future__ import annotations


def record_player_control(game, controlled: int, controller: int) -> None:
    """The effect resolved: *controller* will control *controlled* during
    that player's next turn (CR 723.1). A later effect replaces an earlier
    one for the same player (CR 723.1a)."""
    game.player_controls_waiting[controlled] = controller


def begin_controlled_turn(game, seat: int) -> None:
    """*seat*'s turn is beginning (``begin_turn_bookkeeping``): the control in
    force from an earlier turn ends (CR 723.1), and a control waiting for this
    seat's next turn starts (CR 723.1, 723.1b)."""
    for controlled, (controller, turn) in list(game.player_controls.items()):
        if turn == game.turn and controlled == seat:
            # The same turn beginning again (the web's Time Vault decline
            # runs the beginning twice): not the next turn.
            continue
        del game.player_controls[controlled]
        game.log.append(
            f"{game.players[controller].name} no longer controls "
            f"{game.players[controlled].name} (CR 723.1)"
        )
    controller = game.player_controls_waiting.pop(seat, None)
    if controller is None:
        return
    game.player_controls[seat] = (controller, game.turn)
    if controller == seat:
        # CR 723.9: control of yourself — you decide as you always do.
        game.log.append(
            f"{game.players[seat].name} controls themselves this turn (CR 723.9)"
        )
        return
    game.log.append(
        f"{game.players[controller].name} controls "
        f"{game.players[seat].name} during this turn (CR 723)"
    )


def return_skipped_control(game, seat: int) -> None:
    """*seat*'s turn, already begun, is skipped (Time Vault's "you may skip
    that turn instead"): a control that started with it waits for the next
    turn the player actually takes (CR 723.1b)."""
    entry = game.player_controls.get(seat)
    if entry is None or entry[1] != game.turn:
        return
    del game.player_controls[seat]
    game.player_controls_waiting.setdefault(seat, entry[0])


def decider_of(game, seat: int) -> int:
    """The seat making *seat*'s choices and decisions right now (CR 723.5):
    its controller while a control is in force, else itself.

    One hop is the whole answer — a control applies only during the
    controlled player's own turn, so only the active player is ever
    controlled and a controller is never itself controlled. A controller who
    has left the game decides for nobody (CR 800.4a ends the effects that
    give them control of anything)."""
    entry = game.player_controls.get(seat)
    if entry is None:
        return seat
    controller = entry[0]
    if not 0 <= controller < len(game.players) or game.players[controller].lost:
        return seat
    return controller


def asks_a_person(game, seat: int) -> bool:
    """Whether a person is asked *seat*'s decisions right now: the seat that
    decides for it (:func:`decider_of`) is one a person sits at
    (``Game.interactive_seats``). The one membership question about that set
    — "is this seat interactive" — for every reader that asks it of a
    particular seat."""
    return decider_of(game, seat) in game.interactive_seats


def controls_another(game, seat: int) -> bool:
    """Whether *seat* is controlling another player right now."""
    return any(
        controlled != seat and decider_of(game, controlled) == seat
        for controlled in game.player_controls
    )


def decided_by(game, seat: int) -> list[int]:
    """Every seat whose decisions *seat* makes right now, itself first
    (CR 723.8)."""
    return [seat] + sorted(
        controlled for controlled in game.player_controls
        if controlled != seat and decider_of(game, controlled) == seat
    )


__all__ = [
    "asks_a_person",
    "begin_controlled_turn",
    "controls_another",
    "decided_by",
    "decider_of",
    "record_player_control",
    "return_skipped_control",
]
