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
    context.results[key] = None
    card_name = getattr(context.card, "name", "")
    chooser = game.players.index(context.caster)
    seats = [
        seat
        for seat, player in enumerate(game.players)
        if seat != chooser and not player.lost
    ]
    if not seats:
        game.log.append(f"{card_name}: no opponent to choose")
        return True, "resolved"
    if len(seats) == 1:
        context.results[key] = seats[0]
        return True, "resolved"
    game.arm_player_choice(
        chooser,
        card_name=card_name,
        prompt=str(instruction.payload.get("prompt") or "Choose an opponent."),
        result_key=key,
        seats=seats,
        context=context,
    )
    return True, "resolved"
