"""Coin flips that may stop to ask (CR 705): which coin is kept, and the runs.

**Which coin is kept.** "If you would flip a coin, instead flip two coins and
ignore one." (Krark's Thumb.) The flipper chooses which, seeing every coin:
the card's rulings — 2019-01-25, "You will know the results of all
simultaneous flips before choosing which to ignore"; 2004-10-04, "If you and
your opponent both flip at the same time, you can see your opponent's result
before choosing which result to keep." So every flip in the engine is
:func:`flip_together`: each flipper's coins are flipped through the one seam
(``_common.flip_coins_for``, which asks the CR 614 replacements how many coins
the flip became), and a flipper whose coins disagree is asked which to keep —
the ``ignore_coin`` prompt (``mixins/stack/choices/numbers.py``), one seat at
a time in APNAP order (CR 101.4: "the active player … makes any choices
required, then the next player in turn order", each knowing the earlier
choices, 101.4b). The prompt suspends the resolution (CR 608.2): what a flip
decides — the record behind "if you win the flip", a creature removed from
combat, the next flip of a run — is the *then* of :func:`flip_together`,
which runs once every kept coin is known. A seat nobody asks keeps the win,
or heads, where the prompt is armed (``default_at_arm``), which is the coin
every flip kept before the question was asked — so AI and seeded games draw
and keep exactly what they always did.

Not a guess at a preference: the pool has cards that reward the losing flip
(Puppet's Verdict's "if you lose the flip, destroy all creatures with power 3
or greater"; Winter Sky's draw; Impulsive Maneuvers on an opponent's
attacker), which is why the keep is asked rather than decided.

**The runs.** "Flip a coin that many times or until you lose a flip" (Squee's
Revenge), "flip a coin until you lose a flip" (Crazed Firecat), "…or choose to
stop flipping" (Fiery Gambit) and Game of Chaos's flip for the stakes: the
``flip_coins_until_loss`` and ``coin_flip_stakes_loop`` kinds, dispatched here
from ``control_flow`` (which sits near the module cap). Each flip of a run is a
:func:`flip_together`, so a run stops to ask mid-way and carries on from the
answer. Fiery Gambit's run has a **decision between flips** — the ruling
(2004-12-01): "After each flip, you choose whether to continue flipping" — so
each won flip asks the flipper through the ``flip_again`` prompt Game of Chaos
already answers, and the answer that goes on runs this same instruction again
with the count so far on its payload.

Every run writes the records a run writes: ``coin_flip`` (no flip lost),
``COIN_FLIPS_MADE``, ``COIN_FLIPS_WON`` — and, for a run printed with "If you
lose a flip, <this> has no effect", ``COIN_FLIP_RUN_VOIDED`` on a loss, which
every "if you win N or more flips" reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ..oracle_types import (COIN_FLIP_RUN_VOIDED, COIN_FLIPS_MADE,
                            COIN_FLIPS_WON, OracleInstruction)
from ..resumption import run_resumable
from ._common import (COIN_FACES_BY_SEAT, announce_won_flip, flip_coin,
                      flip_coins_for)

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext

#: Where a run its flipper never stops gives up, for ``control_flow``'s
#: ``_UNBOUNDED_FLIP_GUARD`` reason: only a rigged coin reaches it.
_RUN_GUARD = 1000

#: Where an unbounded run of flips ("until you lose a flip") gives up. Not a
#: rule — CR 705 sets no ceiling — but the probability of a fair coin reaching
#: it is 2**-1000, so only a rigged coin ever does.
UNBOUNDED_FLIP_GUARD = 1000


def coin_label(up: bool, *, wins: bool) -> str:
    """What a coin came up as a person reads it: "won" / "lost" for a flip
    its flipper wins or loses, "heads" / "tails" for one nobody wins
    (CR 705.2)."""
    if wins:
        return "won" if up else "lost"
    return "heads" if up else "tails"


def flip_together(
    game: "Game", flippers: list, *, flip, card_name: str, wins: bool,
    then: Callable[[list[bool]], None],
) -> None:
    """Each of *flippers* flips a coin, at once; *then* is handed the coin
    each one kept, in *flippers*' order (True: a win, or heads).

    *wins* is CR 705.2's line: True for a flip its flipper wins or loses —
    each kept win is announced as that flipper's (``announce_won_flip``) —
    False for one that only comes up heads or tails, which nobody wins.

    Every flipper's coins are flipped before anybody chooses, in *flippers*'
    order (the order each caller always drew in, so a seeded game draws the
    same coins for the same seats). A flipper whose coins all agree keeps
    that; one whose coins disagree is asked (``ignore_coin``), in APNAP order
    of the choosing seats (CR 101.4), each prompt showing the other flippers'
    coins and what each earlier chooser kept (101.4b). *then* is this
    function's last step (``engine/resumption.py``): work after the call does
    not run when a seat is asked, so a caller puts everything that reads the
    result in *then*.
    """
    # A flip nobody makes (no seat) is one coin (``coins_for_one_flip``), so
    # it is never asked about.
    seats = [
        game.players.index(player) if player in game.players else None
        for player in flippers
    ]
    flipped = [flip_coins_for(game, player, flip=flip) for player in flippers]
    kept: list = [coins[0] if len(set(coins)) == 1 else None for coins in flipped]

    def finish() -> None:
        if wins:
            for player, up in zip(flippers, kept):
                if up:
                    announce_won_flip(game, player)
        then([bool(up) for up in kept])

    owed = [position for position, up in enumerate(kept) if up is None]
    if not owed:
        finish()
        return
    turn = {seat: place for place, seat in enumerate(game.apnap_seats(include_lost=True))}
    owed.sort(key=lambda position: turn.get(seats[position], len(turn)))

    def ask(position: int) -> None:
        from ..replacements.coin_flips import coin_doubler_names

        flipper = flippers[position]
        game.arm_pending_choice(
            "ignore_coin", seats[position],
            card_name=card_name,
            wins=wins,
            coins=[coin_label(up, wins=wins) for up in flipped[position]],
            others=[
                {
                    "seat": seats[other],
                    "name": flippers[other].name,
                    "coins": [coin_label(up, wins=wins) for up in flipped[other]],
                    "kept": (
                        None if kept[other] is None
                        else coin_label(kept[other], wins=wins)
                    ),
                }
                for other in range(len(flippers)) if other != position
            ],
            ignored_by=coin_doubler_names(game, flipper),
            _kept=kept,
            _position=position,
        )

    run_resumable(game, owed, ask, then=finish)


def flip_won_or_lost(
    game: "Game", flipper, *, flip, card_name: str, then: Callable[[bool], None],
) -> None:
    """One flip *flipper* wins or loses (CR 705.2), and *then* with whether
    the coin kept is a win — :func:`flip_together` for one flipper."""
    flip_together(
        game, [flipper], flip=flip, card_name=card_name, wins=True,
        then=lambda kept: then(kept[0]),
    )


def flip_a_coin(
    game: "Game", instruction: OracleInstruction,
    context: "OracleExecutionContext", *, flip,
) -> tuple[bool, str]:
    """The ``flip_coin`` kind's flip (``control_flow.flip_a_coin`` says what
    each flipper payload means), its record written by the flip's last step."""
    card_name = getattr(context.card, "name", "an effect")
    who = instruction.payload.get("flipper")
    if who == "each_player":
        # One coin per seat still in the game, in APNAP order (CR 101.4), and
        # a flip nobody wins or loses — so no announcement of a win and
        # nothing written under ``coin_flip``; what the sentences after it
        # read is each seat's face.
        seats = game.apnap_seats()

        def faces_kept(kept: list[bool]) -> None:
            faces: dict[int, str] = {}
            for seat, heads in zip(seats, kept):
                faces[seat] = "heads" if heads else "tails"
                game.log.append(
                    f"{card_name}: {game.players[seat].name} flipped {faces[seat]}"
                )
            context.results[COIN_FACES_BY_SEAT] = faces

        flip_together(
            game, [game.players[seat] for seat in seats], flip=flip,
            card_name=card_name, wins=False, then=faces_kept,
        )
        return True, "resolved"
    flipper = context.caster
    named = ""
    if who == "event_subject_player":
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not 0 <= seat < len(game.players):
            game.log.append(f"{card_name}: no player to flip the coin")
            return True, "resolved"
        flipper = game.players[seat]
        named = f"{flipper.name} "

    def won_kept(won: bool) -> None:
        context.results["coin_flip"] = won
        game.log.append(
            f"{card_name}: {named}{'won' if won else 'lost'} the coin flip"
        )

    flip_won_or_lost(game, flipper, flip=flip, card_name=card_name, then=won_kept)
    return True, "resolved"


def flip_until_loss(
    game: "Game", instruction: OracleInstruction,
    context: "OracleExecutionContext", *, flip,
) -> tuple[bool, str]:
    """A run bounded by a number an earlier step recorded, or by the first
    loss alone (``control_flow.flip_coins_until_loss`` says which).

    Each flip is a :func:`flip_won_or_lost` whose *then* goes on to the next
    one: played in a ``while`` while every flip settles straight away, so a
    run of a thousand wins costs no stack, and re-entered from the answer when
    a flip stopped to ask. The records and the summary line are the run's last
    step, written once the run has ended either way.
    """
    bounded = instruction.payload.get("amount_from") is not None
    limit = (
        max(0, int(context.results.get(str(instruction.payload["amount_from"]), 0) or 0))
        if bounded else UNBOUNDED_FLIP_GUARD
    )
    card_name = getattr(context.card, "name", "an effect")
    run = {"made": 0, "clean": True}

    def finish() -> None:
        made, clean = run["made"], run["clean"]
        context.results["coin_flip"] = clean
        context.results[COIN_FLIPS_MADE] = made
        context.results[COIN_FLIPS_WON] = made if clean else made - 1
        if bounded:
            game.log.append(
                f"{card_name}: {made} of {limit} flip(s) made, "
                + ("every one won" if clean else "the last one lost")
            )
        else:
            game.log.append(
                f"{card_name}: won {context.results[COIN_FLIPS_WON]} flip(s) "
                "before losing one"
            )

    def play() -> None:
        while True:
            if run["made"] >= limit or not run["clean"]:
                finish()
                return
            here = {"inline": True, "again": False}

            def kept(won: bool, here=here) -> None:
                run["clean"] = won
                run["made"] += 1
                game.log.append(
                    f"{card_name}: {'won' if won else 'lost'} the coin flip"
                )
                if here["inline"]:
                    here["again"] = True
                else:
                    play()

            flip_won_or_lost(
                game, context.caster, flip=flip, card_name=card_name, then=kept,
            )
            here["inline"] = False
            if not here["again"]:
                # The flip stopped to ask which coin to keep: its answer runs
                # ``kept``, which comes back here for the next flip.
                return

    play()
    return True, "resolved"


def flip_until_loss_or_stop(
    game: "Game", instruction: OracleInstruction,
    context: "OracleExecutionContext",
) -> tuple[bool, str]:
    """One flip of the run, and the offer to flip again after a win."""
    payload = instruction.payload
    caster = context.caster
    card_name = getattr(context.card, "name", "an effect")
    made = int(payload.get("made", 0) or 0) + 1

    def kept(won: bool) -> None:
        game.log.append(f"{card_name}: {'won' if won else 'lost'} the coin flip")
        context.results["coin_flip"] = won
        context.results[COIN_FLIPS_MADE] = made
        context.results[COIN_FLIPS_WON] = made if won else made - 1
        if not won:
            if payload.get("void_on_loss"):
                # "If you lose a flip, Fiery Gambit has no effect."
                context.results[COIN_FLIP_RUN_VOIDED] = True
                game.log.append(f"{card_name}: a flip was lost, so it has no effect")
            return
        if made >= _RUN_GUARD:
            return
        # "…or choose to stop flipping." The offer, for the flipper alone; the
        # stated default (a seat nobody asks) is to stop, taken where it is
        # armed (``FLIP_AGAIN_SPEC.default_at_arm``).
        game.arm_pending_choice(
            "flip_again", game.players.index(caster),
            card_name=card_name,
            flips_won=made,
            _again=OracleInstruction(instruction.kind, "", {**payload, "made": made}),
            _context=context,
        )

    flip_won_or_lost(game, caster, flip=flip_coin, card_name=card_name, then=kept)
    return True, "resolved"


def flip_for_stakes(
    game: "Game", instruction: OracleInstruction,
    context: "OracleExecutionContext", *, flip,
) -> tuple[bool, str]:
    """Game of Chaos's round (``control_flow.coin_flip_stakes_loop`` says
    who decides what): the caster's flip, then the stake moved and the offer
    of the next round to whoever the kept coin favoured."""
    caster = context.caster
    opponent = context.target
    card_name = getattr(context.card, "name", "an effect")
    if opponent is None or opponent is caster:
        game.log.append(f"{card_name}: no opponent to play against")
        return True, "resolved"
    stake = max(0, int(instruction.payload.get("stake", 1)))

    def kept(won: bool) -> None:
        context.results["coin_flip"] = won
        if won:
            game._gain_life(caster, stake, card_name)
            opponent.life -= stake
            decider = caster
        else:
            caster.life -= stake
            game._gain_life(opponent, stake, card_name)
            decider = opponent
        game.log.append(
            f"{card_name}: {caster.name} {'won' if won else 'lost'} the flip "
            f"for {stake} life"
        )
        # "Double the life stakes with each flip." Applied to what the *next*
        # round would run at, not to this one: the first flip is for the
        # printed number.
        next_stake = stake * 2 if instruction.payload.get("doubling") else stake
        game.arm_pending_choice(
            "flip_again", game.players.index(decider),
            card_name=card_name,
            stake=next_stake,
            _again=OracleInstruction(
                instruction.kind, "", {**instruction.payload, "stake": next_stake}
            ),
            _context=context,
        )

    flip_won_or_lost(game, caster, flip=flip, card_name=card_name, then=kept)
    return True, "resolved"
