"""What a permanent's state *was* when the turn began (CR 502).

"If Rasputin started the turn untapped" is a question the board cannot answer.
By the time an upkeep trigger asks it, the untap step has already run and every
permanent that was tapped is untapped — so the answer has to be recorded before
the untapping, which is where ``phases/untap_step.py`` records it.

Two keys, and the pair is the point. One says **which turn** the record is
about; the others say what was true then, one per state word. A permanent that
entered part-way through the turn did not start it, and reading a lone
"was it tapped?" flag would answer that permanent's question as "no, so it
started the turn untapped" — a card growing a counter it never earned. The turn
stamp is what makes "it was not there" a third answer rather than a silent yes.

One record per state word, so a card asking about a different state ("started
the turn tapped", and whatever the next set prints) is the same rule with
different payload rather than a second flag on the permanent.

The records travel with the permanent and die with it, which CR 400.7 gives for
free — a permanent that leaves and returns is a new object carrying none of
them, and correctly did not start the turn.
"""

from __future__ import annotations

#: The turn the records below are about.
TURN_START_TURN_KEY = "_turn_start_turn"

#: The metadata key one state's turn-start record lives under.
STATE_AT_TURN_START_KEY = "_turn_start_{state}"

#: The states worth recording: the ones a printed "started the turn <word>"
#: clause can name. Each is read off the permanent by attribute, so adding one
#: is adding a word here and nothing else.
RECORDED_STATES: tuple[str, ...] = ("tapped",)


def record_turn_start_states(permanents, turn: int) -> None:
    """Stamp what each permanent's state is, as the state it started *turn* in.

    Called from the untap step before anything untaps, over **every**
    battlefield rather than the active player's: the turn began for every
    permanent there is, and a card asking about one an opponent controls would
    otherwise read no record and be told it was not there.
    """
    for permanent in permanents:
        permanent.metadata[TURN_START_TURN_KEY] = turn
        for state in RECORDED_STATES:
            permanent.metadata[STATE_AT_TURN_START_KEY.format(state=state)] = bool(
                getattr(permanent, state, False)
            )


def started_the_turn(permanent, state: str, turn: int) -> bool | None:
    """Whether *permanent* began *turn* in *state* — or None if it was not there.

    None rather than False, because the two answers differ: "it started the turn
    tapped" and "it started the turn untapped" are both false of a permanent
    that entered this turn, and a caller collapsing that to False would make one
    of them true.
    """
    if permanent.metadata.get(TURN_START_TURN_KEY) != turn:
        return None
    return bool(permanent.metadata.get(STATE_AT_TURN_START_KEY.format(state=state)))


__all__ = [
    "RECORDED_STATES",
    "STATE_AT_TURN_START_KEY",
    "TURN_START_TURN_KEY",
    "record_turn_start_states",
    "started_the_turn",
]


# ---------------------------------------------------------------------------
# Which of a seat's turns a permanent last attacked on
# ---------------------------------------------------------------------------
#
# "It attacked during your last turn" (Giant Turtle, Goblin Rock Sled) and "it
# attacked during its controller's last turn" (Tangle Kelp) are the same
# question asked by two different steps — the declare-attackers step refuses an
# attack, the untap step refuses an untap — so the record and the arithmetic
# over it live here rather than being read twice.
#
# The stamp is deliberately *not* in ``mixins/_constants._EOT_METADATA_KEYS``:
# ``attacked_this_turn`` is swept at cleanup and this question is asked a whole
# turn later. It dies with the permanent instead, which CR 400.7 gives for
# free — a creature that leaves and returns is a new object that has never
# attacked.

#: The metadata key holding ``{"seat": …, "seat_turn": …}`` for the most recent
#: attack. Overwritten on each attack: only the latest one can be "last turn".
ATTACKED_ON_SEAT_TURN_KEY = "attacked_on_seat_turn"

#: The metadata key for the *current* turn's attack (CR 508.1), stamped by the
#: declare-attackers step and swept at cleanup with the rest of the turn's
#: marks. It is not a field on ``Permanent``, which is why it needs a reader:
#: every caller asking "did it attack this turn?" through ``getattr`` gets
#: False forever, and that is a card that acts as though nothing ever attacked.
ATTACKED_THIS_TURN_KEY = "attacked_this_turn"


def attacked_this_turn(permanent) -> bool:
    """Whether *permanent* has been declared as an attacker this turn."""
    return bool(permanent.metadata.get(ATTACKED_THIS_TURN_KEY))


#: The metadata key holding the seats this permanent has been declared as an
#: attacker **against** this turn, as a list (CR 508.1a: a creature is declared
#: attacking a player, a planeswalker or a battle).
#:
#: A record rather than a read of ``Permanent.defending_player_index``, which is
#: the *live* relation and is cleared when combat ends — "target creature that
#: attacked you this turn" (Jabari's Influence) is printed on a card whose other
#: line is "cast this spell only after combat", so by the time the question is
#: asked there is nothing live to read.
#:
#: A list, not one seat: a turn may have two combat phases (Relentless Assault),
#: and a creature that attacked two different players in them attacked both.
#: Swept at cleanup with ``attacked_this_turn``, whose window this shares.
ATTACKED_SEATS_THIS_TURN_KEY = "attacked_seats_this_turn"


def record_attacked_seat(permanent, seat: int | None) -> None:
    """Stamp that *permanent* was declared attacking *seat* this turn.

    ``None`` — CR 508.5's planeswalker attack — records nothing: the creature
    attacked a permanent, not the player, and "attacked you" is about the
    player. Dropping it is the narrow direction, which is the one a target
    description may not get wrong.
    """
    if seat is None:
        return
    seats = permanent.metadata.setdefault(ATTACKED_SEATS_THIS_TURN_KEY, [])
    if seat not in seats:
        seats.append(seat)


def attacked_seat_this_turn(permanent, seat: int) -> bool:
    """Whether *permanent* attacked *seat* this turn."""
    return seat in (permanent.metadata.get(ATTACKED_SEATS_THIS_TURN_KEY) or ())


def record_attack(permanent, seat: int, seat_turn: int) -> None:
    """Stamp that *permanent* attacked on *seat*'s turn number *seat_turn*."""
    permanent.metadata[ATTACKED_ON_SEAT_TURN_KEY] = {
        "seat": seat,
        "seat_turn": seat_turn,
    }


#: The metadata key holding ``{"seat": ..., "seat_turn": ...}`` for the most
#: recent combat *block* this permanent was on either side of. Beside the attack
#: stamp above because it is the same shape answering the same kind of question
#: — "since your last upkeep" is one seat-turn ordinal back, exactly as "during
#: your last turn" is — and beside it rather than folded into it because a
#: creature that attacked and a creature that blocked are two different facts
#: about the same combat.
#:
#: Also deliberately not in ``mixins/_constants._EOT_METADATA_KEYS``: the window
#: this answers spans the opponents' turns in between, so a sweep at cleanup
#: would erase the record a turn before it is read. It dies with the permanent,
#: which CR 400.7 gives for free.
IN_A_BLOCK_ON_SEAT_TURN_KEY = "in_a_block_on_seat_turn"


def record_block_involvement(permanent, seat: int, seat_turn: int) -> None:
    """Stamp that *permanent* blocked or was blocked on *seat*'s turn number
    *seat_turn* (CR 509.1a, either side of the relation)."""
    permanent.metadata[IN_A_BLOCK_ON_SEAT_TURN_KEY] = {
        "seat": seat,
        "seat_turn": seat_turn,
    }


#: The two id lists ``phases/declare_blockers_step._record_block_history``
#: writes, one per side of the relation: the attackers a creature blocked, and
#: the blockers that blocked it. Named here because :func:`block_partners_this_turn`
#: is the first reader that wants *both* — "blocked **or was blocked by**" is one
#: question about a symmetric relation, and reading one list would answer it for
#: half the combats the creature was in.
BLOCKED_ATTACKER_IDS_KEY = "blocked_attacker_ids_this_turn"
BLOCKED_BY_BLOCKER_IDS_KEY = "blocked_by_blocker_ids_this_turn"


def block_partners_this_turn(game, permanent) -> list:
    """Every creature on the far side of a block *permanent* was in this turn.

    Both directions of CR 509.1a's relation, from the pair records the declare
    blockers step writes — which is where a block becomes a fact about the two
    permanents rather than about the declaration, so an effect that *made* a
    creature block (Sorrow's Path) is counted here exactly as a declaration is.

    **Only survivors are returned**, by the same ``permanent_by_id`` resolution
    every other reader of those lists uses (``handlers/destruction.py``,
    ``targeting.py``): the record is a list of ids, and a creature that has left
    the battlefield has no object to ask a characteristic of. That is a real
    narrowing on a clause like "blocked or was blocked by a blue creature this
    turn", whose answer under the rules does not depend on the other creature
    still being there; it is the narrowing this engine already lives with
    everywhere else these records are read, and closing it means last-known
    information for a departed permanent, which nothing here has.
    """
    ids: list[int] = []
    for key in (BLOCKED_ATTACKER_IDS_KEY, BLOCKED_BY_BLOCKER_IDS_KEY):
        for permanent_id in permanent.metadata.get(key) or ():
            if permanent_id not in ids:
                ids.append(permanent_id)
    found = []
    for permanent_id in ids:
        other = game.permanent_by_id(permanent_id)
        if other is not None:
            found.append(other)
    return found


def in_a_block_since_seats_last_upkeep(game, permanent, seat: int) -> bool:
    """Whether *permanent* has blocked or been blocked since *seat*'s previous
    upkeep (Wiitigo).

    The same ordinal arithmetic :func:`attacked_during_seats_last_turn` does,
    and it lands on the same comparison for a reason worth writing down: a
    seat's own turn counter does not move while its opponents take their turns,
    so every moment between the beginning of that seat's turn N-1 and the
    beginning of its turn N stamps ``N-1``. The window "since your last upkeep"
    is exactly that span — an upkeep is the first thing in a turn, and combat
    comes after it, so a block on turn N cannot precede turn N's upkeep.

    The stamp's *seat* is part of the comparison for
    :func:`attacked_during_seats_last_turn`'s reason: a creature that blocked
    while a thief controlled it blocked during the thief's turn.
    """
    stamp = permanent.metadata.get(IN_A_BLOCK_ON_SEAT_TURN_KEY)
    if not isinstance(stamp, dict):
        return False
    return (
        stamp.get("seat") == seat
        and stamp.get("seat_turn") == game.seat_turn_counts.get(seat, 0) - 1
    )


#: The metadata key holding ``{"seat": …, "turn": …}`` for the **first** of its
#: controller's upkeeps this permanent has been present for — CR 702.30a's
#: "came under your control since the beginning of your last upkeep", recorded
#: from the other end.
#:
#: Recorded rather than derived, and that is what ``record_turn_start_states``
#: at the head of this module already says about a different question: a
#: permanent that came under your control two of your turns ago and one that
#: arrived during the opponent's turn in between look identical on the board,
#: and every per-turn record of the difference is swept before the upkeep that
#: asks. So the upkeep step writes the fact once and this reads it.
#:
#: **From the other end** is the whole design. The obvious record is "when did
#: this come under your control", compared against a clock; the clock costs an
#: ordinal that has to advance in step with every driver, and it has to not
#: move between CR 603.4's two checks of the same condition — the one that
#: decides whether the ability triggers and the one at resolution. Recording
#: which upkeep was the *first* this permanent saw satisfies both by
#: construction: it is written once, at the top of the step, and it is never
#: overwritten while the controller stays the same, so the prompt that offers
#: the payment, the gate that fires the trigger and the re-check that resolves
#: it read one unchanging answer.
#:
#: Nothing sweeps it and nothing may. It dies with the permanent, which CR 400.7
#: gives for free: what leaves and returns is a new object that has just come
#: under your control, which is exactly what echo says about it.
FIRST_CONTROLLERS_UPKEEP_KEY = "first_controllers_upkeep"


def record_controllers_upkeep(game, permanents, seat: int) -> None:
    """Stamp this upkeep as the first of *seat*'s that each of *permanents* has
    seen — for the ones that have not seen one already.

    ``setdefault`` is the whole rule: a permanent that already carries a stamp
    for this seat has been through an earlier upkeep of theirs and must keep
    saying so, and one that carries a stamp for somebody else has changed hands
    without :func:`forget_controllers_upkeep` running, which is a record about a
    seat that is not being asked about.

    Called from the top of the upkeep step over the permanents that seat
    controls **at that moment**. At the top so CR 603.4's two checks of the same
    condition cannot straddle the write; over the permanents present then, so
    one that enters later in the same step is correctly still owed its first
    upkeep.
    """
    for permanent in permanents:
        stamp = permanent.metadata.get(FIRST_CONTROLLERS_UPKEEP_KEY)
        if isinstance(stamp, dict) and stamp.get("seat") == seat:
            continue
        permanent.metadata[FIRST_CONTROLLERS_UPKEEP_KEY] = {
            "seat": int(seat), "turn": int(game.turn),
        }


def forget_controllers_upkeep(permanent) -> None:
    """Drop the stamp because *permanent* has changed hands.

    CR 702.30a is about coming under a **controller's** control, so a permanent
    that changes hands starts the window again — for the new controller, and
    also for the old one if it ever comes back. Storing the seat is not enough
    to say so: a permanent stolen and returned between two of your upkeeps came
    under your control again, and a stamp still naming you would deny it.
    """
    permanent.metadata.pop(FIRST_CONTROLLERS_UPKEEP_KEY, None)


def came_under_control_since_seats_last_upkeep(game, permanent, seat: int) -> bool:
    """Whether *permanent* came under *seat*'s control since the beginning of
    that seat's previous upkeep — CR 702.30a's intervening-if.

    True in exactly two cases, and the pair is the reading:

    * **the stamp names this turn** — this upkeep is the first of *seat*'s that
      the permanent has seen, so it cannot have been here at the previous one;
    * **there is no stamp for this seat at all** — it has seen none of *seat*'s
      upkeeps yet, which is the answer while the offer is being collected
      (``get_upkeep_pay_triggers`` runs before the step writes anything) and the
      answer for a permanent placed straight onto a battlefield by a test
      fixture. Both want the same thing, and both are self-correcting: the step
      stamps this turn a moment later and every later upkeep reads False.

    A stamp naming a different seat reads as no stamp, which is the same
    "it has seen none of *your* upkeeps" and the honest answer for a permanent
    whose record is about somebody else.
    """
    stamp = permanent.metadata.get(FIRST_CONTROLLERS_UPKEEP_KEY)
    if not isinstance(stamp, dict) or stamp.get("seat") != seat:
        return True
    return stamp.get("turn") == game.turn


def attacked_during_seats_last_turn(game, permanent, seat: int) -> bool:
    """Whether *permanent* attacked during *seat*'s previous turn.

    Ordinal arithmetic against that seat's own turn counter, which
    ``mixins/turn_management`` increments as a turn begins — so during any step
    of *seat*'s current turn, "your last turn" is the ordinal one below the
    current one.

    The stamp's *seat* is part of the comparison, not just its number: a
    creature that attacked while a thief controlled it attacked during the
    thief's turn, and once it is home it is free again.
    """
    stamp = permanent.metadata.get(ATTACKED_ON_SEAT_TURN_KEY)
    if not isinstance(stamp, dict):
        return False
    return (
        stamp.get("seat") == seat
        and stamp.get("seat_turn") == game.seat_turn_counts.get(seat, 0) - 1
    )


# ---------------------------------------------------------------------------
# A window that opens on a named seat's *next* turn
# ---------------------------------------------------------------------------
#
# "That creature can't attack during **its controller's next turn**" (Wall of
# Dust) and "**During that player's next turn**, the chosen creatures attack if
# able, and other creatures can't attack. At the beginning of **that turn's**
# end step, destroy each of the chosen creatures that didn't attack this turn."
# (Oracle en-Vec.) One printed shape: an effect that resolves now and takes hold
# during a turn that has not started yet.
#
# Every other carrier this engine has is the wrong length for it. The resolution
# scratchpad is gone when the resolution ends; a permanent's ``_EOT`` metadata is
# swept at the next cleanup, which is *before* the named turn begins; and a
# delayed triggered ability answers to a moment rather than spanning a turn. So
# the window is a **stamp**: which seat, and which of that seat's turns, written
# while the creating effect still knows and compared against the seat's own turn
# counter at every step that reads it.
#
# Nothing sweeps a stamp, and nothing needs to. ``seat_turn_counts`` only ever
# rises, so a stamp naming a turn that has been and gone answers False to every
# later question — and one on a permanent that leaves is gone with it, which
# CR 400.7 gives for free.
#
# Wall of Dust wrote this shape inline a set before Oracle en-Vec printed three
# more clauses over it. Named here now for the reason every other pair of
# writer-and-reader in this file is: two spellings of one comparison is how a
# stamp comes to be written in a form nothing reads.


def seats_next_turn_window(game, seat: int) -> dict:
    """The stamp naming *seat*'s **next** turn.

    ``+ 1`` against that seat's own counter rather than against ``game.turn``:
    a seat's counter does not move while its opponents take their turns, so
    "your next turn" is one ordinal up however many turns away it is.
    """
    return {"seat": int(seat), "seat_turn": game.seat_turn_counts.get(seat, 0) + 1}


def stamped_turn_is_now(game, stamp) -> bool:
    """Whether *stamp* names the turn currently being taken.

    Both halves of the comparison, because either alone is wrong: the seat
    without the ordinal answers True on every one of that player's turns for
    the rest of the game, and the ordinal without the seat answers True on
    whichever player's turn happens to share the number.
    """
    if not isinstance(stamp, dict):
        return False
    seat = stamp.get("seat")
    return (
        seat == game.active_player_index
        and stamp.get("seat_turn") == game.seat_turn_counts.get(seat, 0)
    )


def stamped_turn_has_passed(game, stamp) -> bool:
    """Whether the turn *stamp* names is over — or was never reachable.

    For the one carrier that is a list on the game rather than a mark on a
    permanent: a stamp on a permanent needs no sweep because the permanent is
    the entry, and a game-level entry would otherwise accumulate for the rest
    of the game. True once the seat's counter has passed the named turn, which
    happens as that seat's *following* turn begins.
    """
    if not isinstance(stamp, dict):
        return False
    seat = stamp.get("seat")
    try:
        named = int(stamp.get("seat_turn"))
    except (TypeError, ValueError):
        return False
    return game.seat_turn_counts.get(seat, 0) > named


#: The mark "that creature can't attack during its controller's next turn"
#: (Wall of Dust) leaves, and the two beside it Oracle en-Vec leaves: a
#: requirement to attack, and an end-step destruction for staying home. All
#: three carry a :func:`seats_next_turn_window` stamp and are read by the step
#: that enforces them — the declaration for the first two, the end step for the
#: third.
#:
#: Named here rather than spelled at the write and the read for this module's
#: standing reason, and it is not hypothetical: ``attacked_this_turn`` needed a
#: reader function in this file because every caller reaching for it through
#: ``getattr`` got False forever.
CANT_ATTACK_ON_SEAT_TURN_KEY = "cant_attack_on_seat_turn"
MUST_ATTACK_ON_SEAT_TURN_KEY = "must_attack_on_seat_turn"
DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY = "destroy_if_did_not_attack_on_seat_turn"


def marked_for_this_turn(game, permanent, key: str) -> bool:
    """Whether *permanent* carries *key* stamped for the turn being taken."""
    return stamped_turn_is_now(game, permanent.metadata.get(key))


#: The printed window "**during that player's next turn**" (Oracle en-Vec),
#: spelled once for the three readers of it: the duration table that parses the
#: words, the lowerings that put it in a payload, and the handlers that turn it
#: into a :func:`seats_next_turn_window` stamp. "That player" is the seat an
#: earlier step of the same resolution recorded — the one it asked to choose —
#: so the window is not knowable until the effect resolves, which is why it
#: travels as a *name* and not as a stamp.
#:
#: One value, and that is the honest state rather than a table waiting to grow:
#: it is the only window in this engine that a *later* sentence can refer back
#: to as "that turn", and until a second one prints, "that turn" needs no record
#: to disambiguate it. A second value is the moment that changes.
THAT_PLAYERS_NEXT_TURN = "that_players_next_turn"
