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
