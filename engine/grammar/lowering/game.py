"""Lowering the effects that change the state of the **game** itself.

An extra turn, winning, losing, ante (CR 407), a round of offers repeated
until nobody takes one, a whole-game damage history, a counted number and a
skipped step. None of them changes what a permanent is and none of them is
one player's life total -- which is the seam ``lowering/life.py`` left
through when this module crossed a thousand lines, exactly as
``lowering/tokens.py`` left through one set earlier.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (RESTRICTION_TURNS, _amount_payload, _describe_targets,
                      _filter_payload)
from ._events import COUNTED_NUMBER
from ._seats import _player_recipient


# ---------------------------------------------------------------------------
# Life
# ---------------------------------------------------------------------------






def _lower_extra_turn(node: ast.ExtraTurn) -> tuple[OracleInstruction, ...]:
    """"Take an extra turn after this one." (Time Walk) / "Take two extra
    turns after this one." (Teferi, Master of Time.)

    ``grant_extra_turn`` queues the turns for the effect's *controller*; it
    takes no player argument. A card handing the extra turn to someone else is
    a different effect, so it is refused rather than lowered onto a handler
    that would give the turn to the wrong player. The count rides in the
    payload only when it is not 1, keeping the single-turn payload byte-equal
    with what the pool has always compiled to.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no handler for {node.player.kind!r} taking an extra turn", node=node
        )
    payload: dict[str, object] = {}
    if node.count != 1:
        payload["count"] = node.count
    return (OracleInstruction("grant_extra_turn", "", payload),)


# Who a "loses the game" sentence names, and the handler that makes that player
# lose. `player_loses_game` and `target_player_loses_game` are the *same*
# function (engine/handlers/life_and_game.py registers both names) and it picks
# the loser off the kind, so the two are not interchangeable: emitting the
# targeted kind for "you lose the game" would kill whoever the spell happened to
# point at.
_LOSE_GAME_KINDS = {
    "you": "player_loses_game",
    "target_player": "target_player_loses_game",
    "target_opponent": "target_player_loses_game",
    # "If you win the flip, **that player** loses the game." (Amulet of Quoz.)
    # The seat the sentence in front of it named, which is the same
    # ``context.target`` the two rows above resolve to — ``player_loses_game``
    # reads that one field, so this is a third spelling of the row rather than
    # a fourth answer.
    "that_player": "target_player_loses_game",
}


def _lower_lose_game(node: ast.LoseGame) -> tuple[OracleInstruction, ...]:
    """"Target player loses the game." / "You lose the game." (CR 104.3e.)"""
    kind = _LOSE_GAME_KINDS.get(node.player.kind)
    if kind is None:
        raise LoweringError(
            f"no handler makes {node.player.kind!r} lose the game", node=node
        )
    return (OracleInstruction(kind, "", {}),)


def _lower_win_game(node: ast.WinGame) -> tuple[OracleInstruction, ...]:
    """"You win the game." (CR 104.2b.)

    ``player_wins_game`` wins for the effect's *controller* — it marks every
    other player as having lost (104.2a) and takes no player argument. A card
    handing the win to someone else is refused rather than lowered onto a
    handler that would win it for the wrong seat.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no handler makes {node.player.kind!r} win the game", node=node
        )
    return (OracleInstruction("player_wins_game", "", {}),)


def _lower_ante(node: ast.Ante) -> tuple[OracleInstruction, ...]:
    """"Ante the top card of your library." (CR 407.)

    One instruction for both printed shapes; who antes is payload. Demonic
    Attorney's every-seat sweep and Rebirth's per-seat offer differ only in the
    recipient key, which is exactly the difference the card prints.
    """
    return (
        OracleInstruction(
            "ante_top_card", "", {"players": _player_recipient(node.player, node)}
        ),
    )
# ---------------------------------------------------------------------------
# Damage whose shape is a whole-game process rather than an event
# ---------------------------------------------------------------------------
#
# Two sentences that print the word "damage" and share nothing with the damage
# family's vocabulary: neither reads a recipient noun phrase, a duration or a
# rider. Mana Clash is an *unbounded repeat* (CR 705) whose rounds are the
# effect, and The Fallen's recipients are a ledger kept for the whole game
# rather than a set any board can be asked for. They came here the round
# ``lowering/damage.py`` went back over the thousand-line guard, on the line
# this module is already cut on: the game and its players, rather than one
# event on the board.

#: The recipient classes the history handler resolves. "player" and "creature"
#: parse — the phrase reads the same on any of them — and refuse here, because
#: the record holds seats and permanent ids and nothing has been written that
#: turns those into a living creature or a non-opponent seat. A class admitted
#: without a resolver would name nobody and deal nothing, on a card reporting
#: itself supported.
_HISTORY_RECIPIENTS = frozenset({"opponent", "planeswalker"})


def _lower_coin_flip_stakes_loop(
    node: ast.CoinFlipStakesLoop,
) -> tuple[OracleInstruction, ...]:
    """Game of Chaos's whole paragraph as one instruction.

    Not composed out of ``flip_coin`` and two conditionals, which is how Bottle
    of Suleiman's two branches are built: those branches are the end of the
    effect, and these two each end in an *offer to run the paragraph again* —
    made to a different player depending on which branch ran, at a stake the
    round after it doubles. Nothing in the composed shape can carry either
    fact, and a lowering that dropped them would compile a card that flips once
    for one life.

    The stake must be a printed number: it is doubled by the round behind it, so
    an announced X would be a quantity resolved once and then scaled by a
    handler that never saw the announcement.
    """
    if not isinstance(node.stake, ast.Fixed):
        raise LoweringError("a doubling stake is a printed number", node=node)
    return (
        OracleInstruction(
            "coin_flip_stakes_loop", "",
            {
                "stake": int(node.stake.value),
                "doubling": bool(node.doubling),
                # "…and **target opponent** loses N life". The production reads
                # those two words as fixed text, so the target was consumed and
                # then dropped: the handler asks ``context.target`` for the seat
                # it stakes against, and nothing described the choice, so the
                # picker never ran and a free-for-all staked whichever opponent
                # the resolution happened to carry. One target, chosen at
                # announcement (CR 601.2c), described here the way every other
                # target is.
                "targets": {
                    "quantifier": "target", "kind": "player",
                    "opponents_only": True,
                },
            },
        ),
    )


def _lower_coin_flip_damage_loop(
    node: ast.CoinFlipDamageLoop,
) -> tuple[OracleInstruction, ...]:
    """Mana Clash's whole paragraph (CR 705).

    One instruction, because the loop is the effect: a flip, a reading of both
    coins, and a repeat that depends on both. Composed out of `flip_coin` and
    `if_then` it would be a *fixed* number of rounds, since nothing in the
    control-flow vocabulary repeats — and the printed sentence is unbounded.

    Only the amount is payload; who flips and which face is punished are the
    process itself.
    """
    return (
        OracleInstruction(
            "coin_flip_damage_loop", "",
            {
                "amount": _amount_payload(node.amount),
                # The opponent is chosen when the spell is cast (CR 601.2c), so
                # the picker has to be raised from the compiled program like any
                # other target.
                "targets": {
                    "quantifier": "target", "kind": "player", "opponents_only": True,
                },
            },
        ),
    )


def _lower_damage_this_game_history(
    node: ast.DamageThoseDamagedThisGame,
) -> tuple[OracleInstruction, ...]:
    """"…deals 1 damage to each opponent and planeswalker it has dealt damage to
    this game." (The Fallen.)

    The recipients are a record on the source, not a set on any board, so the
    payload carries only how much and which classes of the record to reach for.
    """
    unknown = sorted(set(node.classes) - _HISTORY_RECIPIENTS)
    if unknown:
        raise LoweringError(
            "no handler reaches the damaged-this-game " + ", ".join(unknown),
            node=node,
        )
    return (
        OracleInstruction(
            "deal_damage_to_those_damaged_this_game", "",
            {"amount": _amount_payload(node.amount), "classes": list(node.classes)},
        ),
    )


def _lower_count_objects(node: ast.CountObjects) -> tuple[OracleInstruction, ...]:
    """"Count the number of permanents." (Chaos Moon.)

    Nothing happens on any board: the whole of what the step does is write
    CR 107.1's number into the resolution scratchpad under
    ``COUNTED_NUMBER``, which ``_records._PRODUCES`` declares and the
    "if the number is odd" condition behind it reads. The same shape
    ``flip_coin`` and ``choose_player_who_cast`` have, and for their reason —
    what the value is *for* is the next sentence, not this one.

    What is counted travels as a filter payload, so a card counting something
    narrower than the whole board is this production with a different noun
    phrase. It is held to what ``subject_matches`` can test, for the reason
    every filter in this engine is: a restriction the matcher drops is a count
    over strictly more objects than the card names, and the number it produces
    then decides a branch.
    """
    from ...subject_filters import untestable_filter_keys

    described = _filter_payload(node.filter)
    untestable = untestable_filter_keys(described)
    if untestable:
        raise LoweringError(
            "a count cannot test " + ", ".join(sorted(untestable)), node=node
        )
    return (
        OracleInstruction(
            "count_objects", "", {"filter": described, "result_key": COUNTED_NUMBER}
        ),
    )


def _lower_skip_step(node: "ast.SkipStep") -> tuple[OracleInstruction, ...]:
    """"You skip your next draw step." (Ivory Gargoyle.)

    The seat is on the payload, not implied: ``Game.skip_next_step`` is keyed by
    step name and a skip with no seat is consumed by whichever player's step
    comes round first (CR 500.7 — the step belongs to a turn, and a turn belongs
    to a player).

    Only "you" today. Every other player reference the grammar can read names a
    seat this instruction would have to resolve at *resolution* rather than at
    lowering, and no card in the pool prints one — so it refuses by name rather
    than silently skipping the controller's step.
    """
    who = getattr(node.subject, "kind", None)
    if who != "you":
        raise LoweringError(
            f"no handler skips a step for {who!r}", node=node
        )
    return (
        OracleInstruction(
            "skip_next_step", "",
            {"step": node.step, "seat": "you", "count": int(node.count)},
        ),
    )


def _lower_skip_turn(node: "ast.SkipTurn") -> tuple[OracleInstruction, ...]:
    """"You skip your next turn." (Chronatog.)

    CR 500.11's turn counter — ``Game.skip_next_turn``, spent by
    ``_compute_next_active_player`` — and deliberately not the step bucket
    ``_lower_skip_step`` above writes: a turn is not one of the steps
    ``_phase_steps`` walks, so a record filed there would never be consumed and
    the card would report supported while taking no turn away.

    Only "you", for the sibling's reason exactly: every other player reference
    names a seat this instruction would have to resolve at resolution rather
    than at lowering, and no card in the pool prints one — so it refuses by
    name rather than silently skipping the controller's turn instead of
    somebody else's.
    """
    who = getattr(node.subject, "kind", None)
    if who != "you":
        raise LoweringError(f"no handler skips a turn for {who!r}", node=node)
    return (
        OracleInstruction(
            "skip_next_turn", "", {"seat": "you", "count": int(node.count)}
        ),
    )


def _lower_extra_land_plays(node: ast.ExtraLandPlays) -> tuple[OracleInstruction, ...]:
    """"You may play up to three additional lands this turn." (Summer Bloom,
    CR 305.2.)

    The count is payload and the seat is not: ``grant_extra_land_plays_this_turn``
    records the grant for the effect's own controller (CR 109.5), and a card
    handing extra land drops to somebody else would need the seat resolved at
    resolution rather than here. So it refuses by name, the way the extra-turn
    lowering above does, rather than being lowered onto a handler that would
    grant them to the wrong player.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no handler grants land plays to {node.player.kind!r}", node=node
        )
    return (
        OracleInstruction(
            "grant_extra_land_plays_this_turn", "", {"amount": int(node.amount)}
        ),
    )


def _lower_cant_play_lands(node: ast.CantPlayLands) -> tuple[OracleInstruction, ...]:
    """"Target player can't play lands this turn." (Solfatara, CR 305.1.)

    The seat *is* payload here, because the sentence names a chosen one — and
    describing it is what gives the card a picker at all. Solfatara compiled
    "supported" on its second line alone for a whole set: this sentence produced
    no instruction, so ``derive_cast_spec`` had nothing to read, the client sent
    a bare cast and the engine refused it. A supported card no player could
    cast.
    """
    if node.player.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"no handler stops {node.player.kind!r} playing lands", node=node
        )
    payload: dict[str, object] = {}
    _describe_targets(payload, node.player)
    return (OracleInstruction("forbid_land_plays_this_turn", "", payload),)


def _lower_targeting_ban(node: "ast.TargetingBan") -> tuple[OracleInstruction, ...]:
    """"…players and permanents can't be the targets of spells or activated
    abilities." (Peace Talks.)

    The window is a count of cleanup steps rather than a kind per phrase, so a
    card printing a longer one is a row in ``_common.RESTRICTION_TURNS`` and
    nothing else. A sentence with **no** window is a static ability of some
    permanent, and there is no such card and no channel for one — the ban is
    armed on the game rather than derived from a source, so nothing would end
    it when that permanent left. It refuses by name instead.
    """
    turns = RESTRICTION_TURNS.get(str(node.duration.kind))
    if turns is None:
        raise LoweringError(
            "a targeting ban with no stated window is a static ability, which "
            "nothing derives from a source",
            node=node,
        )
    return (
        OracleInstruction("ban_targeting", "", {"remaining_turns": turns}),
    )
