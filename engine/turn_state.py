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
