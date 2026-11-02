"""Choices a resolution makes about *players* and about *casts*.

Beside ``permanent_choices.py`` and for its reason: what the sentence picks is
neither a target nor anything on a board, so the picker has to enumerate a set
the rules describe and then record what was chosen for a later step to read.
What differs is only the set — here it is the turn's history
(``engine/damage_ledger.py``) rather than the battlefield.

Backdraft is the whole of it today: "Choose a player who cast one or more
sorcery spells this turn. Backdraft deals damage to that player equal to half
the damage dealt by one of those sorcery spells this turn, rounded down." Two
decisions, in the order the card prints them, each a step of one resolution —
which is why they are two handlers rather than one, and why the second reads the
first out of the scratchpad instead of re-deciding it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..damage_ledger import cast_options, damage_dealt_by_cast
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle_types import OracleInstruction


@effect_handler("choose_player_who_cast")
def choose_player_who_cast(
    game: "Game", instruction: "OracleInstruction", context: "OracleExecutionContext"
) -> tuple[bool, str]:
    """"Choose a player who cast one or more sorcery spells this turn."

    The key is written before anything else, for the reason
    ``choose_permanent`` writes its own first: a later step reading it finds
    ``None`` rather than a key error when there was nobody to choose, and "no
    legal choice" is an outcome rather than a failure.

    A single candidate is recorded without asking. The card makes the choice
    forced in that case, and prompting anyway asks a player a question with one
    answer — the same shortcut Juxtapose's ``only_on_tie`` takes.
    """
    payload = instruction.payload
    key = str(payload["result_key"])
    context.results[key] = None
    card_type = str(payload.get("card_type") or "sorcery")
    minimum = max(1, int(payload.get("minimum", 1) or 1))
    card_name = getattr(context.card, "name", "")

    counts: dict[int, int] = {}
    for _index, entry in cast_options(game, card_type=card_type):
        counts[entry.seat] = counts.get(entry.seat, 0) + 1
    seats = [
        seat
        for seat, count in counts.items()
        if count >= minimum
        and 0 <= seat < len(game.players)
        and not game.players[seat].lost
    ]
    if not seats:
        game.log.append(
            f"{card_name}: nobody cast {minimum} or more {card_type} spells this turn"
        )
        return True, "resolved"
    if len(seats) == 1:
        context.results[key] = seats[0]
        game.log.append(f"{card_name}: {game.players[seats[0]].name} is the only choice")
        return True, "resolved"
    game.arm_player_choice(
        game.players.index(context.caster),
        card_name=card_name,
        prompt=f"Choose a player who cast one or more {card_type} spells this turn.",
        result_key=key,
        seats=seats,
        context=context,
    )
    return True, "resolved"


@effect_handler("choose_cast_this_turn")
def choose_cast_this_turn(
    game: "Game", instruction: "OracleInstruction", context: "OracleExecutionContext"
) -> tuple[bool, str]:
    """"…the damage dealt by **one of those** sorcery spells this turn."

    What is recorded is the *number*, not the cast: the sentence behind this one
    asks how much damage that spell dealt, and nothing else about the spell
    survives it. Zero by default, for the reason above — a player who cast a
    sorcery that dealt nothing is a legal choice with a legal answer.

    The set is narrowed by the seat the sentence in front of this one chose, so
    the two decisions cannot disagree about whose spells are on offer.
    """
    payload = instruction.payload
    key = str(payload["result_key"])
    context.results[key] = 0
    card_name = getattr(context.card, "name", "")
    seat = context.results.get(str(payload["by_result"]))
    if not isinstance(seat, int):
        game.log.append(f"{card_name}: no player was chosen, so no spell to name")
        return True, "resolved"
    options = cast_options(game, seat=seat, card_type=str(payload.get("card_type") or ""))
    if not options:
        game.log.append(f"{card_name}: that player cast no such spell this turn")
        return True, "resolved"
    if len(options) == 1:
        context.results[key] = damage_dealt_by_cast(game, options[0][1].item)
        return True, "resolved"
    game.arm_cast_choice(
        game.players.index(context.caster),
        card_name=card_name,
        prompt="Choose one of those spells.",
        result_key=key,
        options=options,
        context=context,
    )
    return True, "resolved"


@effect_handler("choose_target_player")
def choose_target_player(
    game: "Game", instruction: "OracleInstruction", context: "OracleExecutionContext"
) -> tuple[bool, str]:
    """"**Choose target opponent.**" (Soldevi Sentry.)

    A sentence whose whole content is CR 601.2c's choosing of targets, over a
    *player*. Nothing happens when it resolves — the seat was chosen when the
    ability was activated (CR 602.2b), hours of game time before this — so what
    the instruction does is exist: ``engine/targeting.py`` derives the picker
    from it, which is where every other card's picker comes from.

    It also **records** the seat, which is the difference from the object form
    beside it. The sentence that names the chosen player is two sentences later
    and is a *delayed* ability (CR 603.7), so by the time it fires this
    resolution is over and its scratchpad is gone — the seat has to be frozen
    into the entry, and this is where it is available.

    Nothing recorded is not an error: CR 608.2b's illegal target leaves the seat
    unset, and the step reading it back arms nothing rather than guessing.
    """
    key = str(instruction.payload.get("result_key") or "chosen_player")
    context.results[key] = None
    chosen = context.target
    if chosen is None or chosen.lost:
        game.log.append(f"{context.card.name}: no player was chosen")
        return True, "no target"
    context.results[key] = game.players.index(chosen)
    game.log.append(f"{context.card.name} chose {chosen.name}")
    return True, "resolved"


@effect_handler("choose_opponent")
def choose_opponent(
    game: "Game", instruction: "OracleInstruction", context: "OracleExecutionContext"
) -> tuple[bool, str]:
    """"**An opponent** gains control of this land …" (Rainbow Vale.)

    CR 608.2c/608.2d: a choice an effect offers with nobody named is announced
    by the controller of the spell or ability while applying it — so the seat
    that activated the ability picks which opponent, and the sentence behind
    this one reads the answer rather than deciding again.

    A step of its own rather than a word the control handler resolves, for
    ``choose_player_who_cast``'s reason: a pick made in a two-player game has
    exactly one answer and a pick made at four seats is a prompt, and a handler
    that has to stop and ask cannot also finish the sentence. Recorded under the
    key every "that player" reads, so any later step naming the chosen seat is
    already wired.

    The key is written first, so a table where nobody is left to choose reads
    ``None`` rather than raising — "no legal choice" is an outcome.
    """
    key = str(instruction.payload["result_key"])
    card_name = getattr(context.card, "name", "")
    if not ask_which_opponent(
        game, context,
        card_name=card_name,
        prompt=str(instruction.payload.get("prompt") or "Choose an opponent."),
        result_key=key,
    ):
        game.log.append(f"{card_name}: no opponent to choose")
    return True, "resolved"


#: The scratchpad key the seat a controller named as "an opponent" is written
#: under when the step that spends it is a pick *another* seat makes (CR
#: 601.7a / 602.3a / 608.2d) — read by ``permanent_choices._chooser_seat``'s
#: "opponent" row, so the seat asked and the battlefield it picks from
#: ("…target creature **they** control", Echo Chamber, Preacher) are one
#: answer. Its own key rather than ``chosen_player``, which every pick writes
#: for its own chooser and so may already name the controller.
NAMED_OPPONENT = "named_opponent"


def ask_which_opponent(
    game: "Game", context: "OracleExecutionContext", *,
    card_name: str,
    prompt: str = "Choose an opponent.",
    result_key: str = NAMED_OPPONENT,
    could_choose=None,
    then=None,
    announcing=None,
) -> bool:
    """**Which** opponent an unnamed "an opponent" is, asked of the effect's
    controller — and then *then* with that seat (or None).

    CR 601.7a / 602.3a for a choice made as a spell is cast or an ability
    activated, CR 700.2e for a mode, CR 608.2d for one made as the effect is
    applied: "If there is more than one opponent who could make such a
    choice, the spell's controller decides which of those opponents will make
    the choice." So the seats offered are the living opponents for whom
    *could_choose* (a seat → bool) holds — every one of them when it is None
    — and with one there is no question to ask. Several, and the controller is
    asked through the ``player_choice`` prompt; a controller nobody asks takes
    its stated default, the first seat offered, which is the seat this engine
    handed every such choice to before it asked anyone.

    The answer is recorded under *result_key* in the resolution's scratchpad
    (None first, so a reader finds no seat rather than a key error), and
    *then* runs once it is known — as the last step of a resumable loop
    (``engine/resumption.py``), because an interactive controller's prompt
    suspends the effect and the pick that spends the seat must wait for it.
    Nothing may follow this call in its caller for the same reason. Returns
    whether any opponent could be offered at all.

    *announcing* is the stack object whose announcement the choice belongs to
    (a mode, CR 700.2e): the prompt holds it there until it is answered
    (``arm_player_choice``).
    """
    from ..resumption import run_resumable

    context.results[result_key] = None
    controller = game.players.index(context.caster)
    seats = [
        seat for seat in game.opponents_of(controller)
        if could_choose is None or could_choose(seat)
    ]
    if len(seats) <= 1:
        context.results[result_key] = seats[0] if seats else None
        if then is not None:
            then(context.results[result_key])
        return bool(seats)

    def step(which: str) -> None:
        if which == "ask":
            game.arm_player_choice(
                controller,
                card_name=card_name,
                prompt=prompt,
                result_key=result_key,
                seats=seats,
                context=context,
                announcing=announcing,
            )
        elif then is not None:
            seat = context.results.get(result_key)
            then(seat if isinstance(seat, int) and seat in seats else None)

    run_resumable(game, ("ask", "then"), step)
    return True
