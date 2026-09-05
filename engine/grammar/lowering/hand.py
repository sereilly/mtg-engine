"""Lowering a hand emptying: the cards chosen out of one, and where they go.

The mirror of ``effects/hand.py``, split off ``lowering/cards.py`` at the
thousand-line guard in the same round and along the same seam. What stays in
``cards`` lowers a card *arriving* or *leaving for a graveyard* — a draw, a
mill, a discard, a scry; what left is the family that names cards **in a hand**
and moves them: Sylvan Library's pick, the loop over what it picked, and the
three printings that put a hand back onto a library.

``CHOSEN_HAND_CARDS_RESULT`` came with them, which is the argument for the
boundary rather than a consequence of it: one half of this module writes that
key and the other reads it, and nothing outside does either.
"""

from __future__ import annotations

from ...oracle_types import CHOSEN_TARGET_PERMANENTS, OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import _amount_payload, _describe_targets, _filter_payload
from ._events import _EVENT_SUBJECT_PLAYERS, EVENT_SUBJECT_PLAYER


#: The scratchpad key "choose N cards in your hand" writes and "for each of
#: those cards" reads. One name, declared once, so the two halves of the
#: sentence cannot be wired to different keys — the same discipline
#: ``destroyed_this_way_objects`` follows in ``lowering/board.py``.
CHOSEN_HAND_CARDS_RESULT = "chosen_hand_cards"


def _lower_choose_cards_in_hand(
    node: ast.ChooseCardsInHand,
) -> tuple[OracleInstruction, ...]:
    """"Choose two cards in your hand drawn this turn." (Sylvan Library.)

    The pick alone: nothing moves, and the cards are recorded for the sentence
    after this one to repeat over.

    ``zone`` and ``zone_owner`` are honoured **by construction** rather than
    carried in the payload — this instruction reads one hand and it is the
    hand of the seat making the choice — so they are named here as carried and
    everything else in the phrase has to survive ``card_only_filter``. A
    narrowing that cannot be tested refuses the line, because a prompt offering
    a wider set than the card prints is a card that reports supported and
    cheats.
    """
    from ...subject_filters import card_only_filter
    from ._common import _restrictions_beyond, _PAYLOAD_HONOURED_FILTER_FIELDS

    filt = node.filter
    if filt.zone_owner is None or filt.zone_owner.kind != "you":
        raise LoweringError("the hand pick reads your own hand", node=node)
    leftover = _restrictions_beyond(
        filt,
        _PAYLOAD_HONOURED_FILTER_FIELDS | {"is_card", "zone", "zone_owner"},
    )
    if leftover:
        raise LoweringError(
            f"the hand pick does not honour {leftover[0]!r}", node=node
        )
    payload_filter = filt.to_payload()
    payload_filter.pop("zone", None)
    payload_filter.pop("zone_owner", None)
    described = card_only_filter(payload_filter)
    if described is None:
        raise LoweringError("no hand pick can test this narrowing", node=node)
    count = _amount_payload(node.count)
    if not isinstance(count, int) or count < 1:
        raise LoweringError("the hand pick chooses a printed number", node=node)
    return (
        OracleInstruction(
            "choose_cards_in_hand", "",
            {
                "count": count,
                "card_filter": described,
                # The provenance the phrase printed. Its own key rather than a
                # filter entry, because no reader of a *card* can answer it —
                # see ``ast.ChooseCardsInHand``.
                "drawn_this_turn": bool(node.drawn_this_turn),
                "result_key": CHOSEN_HAND_CARDS_RESULT,
            },
        ),
    )


def _lower_put_iterated_card_on_library(
    node: ast.PutIteratedCardOnLibrary,
) -> tuple[OracleInstruction, ...]:
    """"Put the card on top of your library." (Sylvan Library.)

    "The card" is the one the enclosing repetition is on, so this lowers to an
    instruction that reads ``context.iteration_target`` and nothing else. Its
    refusal outside a loop is the handler's, not this lowering's: a sentence
    can name the loop's object several steps in (inside an alternative, inside
    a conditional), and a lowering that tried to prove the loop exists from
    here would have to re-derive the whole enclosing statement.
    """
    return (
        OracleInstruction(
            "put_iterated_card_on_library", "", {"position": node.position}
        ),
    )


def _lower_for_each_short_of_this_way(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each card less than two a player draws this way,** that player
    gains 2 life." (Truce.)

    :func:`_lower_for_each_life_lost`'s twin, and a *nested* loop where that one
    is flat. The sentence names two things at once — "a player" and, inside it,
    a count — so it lowers to a loop over seats (CR 101.4's turn order) with a
    counted repetition inside it. The seat loop is what binds "that player", and
    the inner count is one number per seat, read out of the record the sentence
    in front of it wrote.

    Two refusals, each a way the words could otherwise mean more than they
    say:

    * a step of this same effect must record the count. "This way" is a
      back-reference, and one with no producer names nothing — here it would
      compute the printed base and hand every player the *maximum* life, which
      is the card upside down (idiom 7).
    * the body must lower to something, for :func:`_lower_for_each_chosen`'s
      reason: an empty loop reports supported and does not run.
    """
    record = node.iterator.record
    if record not in produced:
        raise LoweringError(
            f"nothing in this effect records the {record!r} count this loop is "
            "short of",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-shortfall loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {
                # The seats, in turn order, so "that player" names one of them
                # per iteration — the same binding every multi-seat offer makes.
                "iterator": {"players": "each_player"},
                "effect": (
                    OracleInstruction(
                        "for_each", "",
                        {
                            "iterator": {
                                "repeat_from_record": {
                                    "record": record, "base": node.iterator.base,
                                }
                            },
                            "effect": inner,
                        },
                    ),
                ),
            },
        ),
    )


def _lower_for_each_chosen(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each of those cards,** <effect>." (Sylvan Library.)
    "**For each of those creatures,** <effect>." (Winter's Chill.)

    The sibling of ``_lower_for_each_destroyed``, and refused the same way: a
    back-reference with no earlier step that made a choice names nothing, and
    an empty loop is a sentence that reports supported and does not run.

    Two records, one clause. Which of them answers is the printed noun: a hand
    spelling reads the cards a "choose two cards in your hand" step recorded,
    and a permanent spelling reads the permanents a "choose X target …"
    sentence did. Reading either as the other walks an empty list, which is a
    sentence that reports supported and does nothing — so the noun decides and
    the missing producer refuses.
    """
    named = node.iterator.subject
    if named is not None:
        # Which record "those" names is decided by what an earlier step of this
        # same effect actually wrote, in the order the phrase can mean them: a
        # step that *chose* permanents is the closer referent (Winter's Chill
        # names its own targets), and a sweep that destroyed some is the other
        # ("Destroy all artifacts. … **each of those artifacts** …", Seeds of
        # Innocence).
        #
        # Read off *produced* rather than fixed by the parse, for the reason
        # every back-reference here is: the printed word is the same either way
        # and only the effect around it can say which set exists. Neither
        # recorded refuses, exactly as before — an empty loop is a sentence that
        # reports supported and does not run.
        record = None
        if CHOSEN_TARGET_PERMANENTS in produced:
            record = CHOSEN_TARGET_PERMANENTS
        elif "destroyed_this_way" in produced:
            record = "destroyed_this_way_objects"
        if record is None:
            raise LoweringError(
                "'those <permanents>' with no earlier step in this effect that "
                "chose or destroyed any",
                node=node,
            )
        if not inner:
            raise LoweringError("a per-permanent loop with no effect in it", node=node)
        # The printed noun rides beside the record's name, exactly as it does
        # for a destruction sweep's loop: "for each of those **creatures**"
        # after a sentence that targeted attacking creatures is a restatement,
        # and a restatement checked is a restatement. ``for_each`` applies it
        # with ``permanent_matches_filter``, so a target that stopped answering
        # the phrase drops out of the loop rather than being acted on.
        return (
            OracleInstruction(
                "for_each", "",
                {
                    "iterator": {
                        "produced_by": record,
                        **_filter_payload(named),
                    },
                    "effect": inner,
                },
            ),
        )
    if CHOSEN_HAND_CARDS_RESULT not in produced:
        raise LoweringError(
            "'those cards' with no earlier step in this effect that chose any",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-card loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {"iterator": {"produced_by": CHOSEN_HAND_CARDS_RESULT}, "effect": inner},
        ),
    )


def _lower_put_hand_cards_on_library(
    node: ast.PutHandCardsOnLibrary, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """Brainstorm, Stunted Growth, Teferi's Puzzle Box.

    One kind for all three printings: the seat is payload, under the same
    ``recipient`` key ``_lower_mill`` reads, so "who does this happen to" has
    one convention rather than one per effect family.

    A seat this cannot name refuses rather than defaulting to the caster —
    putting the *wrong player's* cards back would be a strictly different card,
    and silently so, since both spellings move the same number of cards.

    *event* is the firing trigger's condition kind, and it is what tells "that
    player" apart from itself: under an offer (Tainted Specter) the seat is the
    one the resolution already targeted, and under "at the beginning of each
    player's draw step" (Teferi's Puzzle Box) it is the seat the fire site
    froze. Both are printed "that player", so nothing but the event can say
    which — the same fork ``_lower_mill`` and ``_lower_discard`` read one
    module over.
    """
    payload: dict[str, object] = {"amount": _amount_payload(node.count)}
    # "…**both on top of your library or both on the bottom**" (Dream Cache).
    # Emitted only when the card offers the choice, so every payload written
    # before this is byte-identical — and the prompt refuses a bottoming answer
    # without it, which is what keeps a client from bottoming a Brainstorm.
    if node.destination != "top":
        payload["destination"] = node.destination
    if node.whole_hand:
        # "**the cards from** their hand" — how many is a fact about the board
        # at resolution, so the handler counts and the payload only says to.
        # ``amount`` above stays as it was for a reader written before this
        # spelling existed; the flag is what the handler reads.
        payload["whole_hand"] = True
    if node.player.kind in ("target_player", "target_opponent"):
        _describe_targets(payload, node.player)
        return _with_that_many_draw(node, payload)
    if node.player.kind == "you":
        payload["recipient"] = "caster"
        return _with_that_many_draw(node, payload)
    if node.player.kind == "that_player":
        # "…**that player** puts the cards in their hand on the bottom of their
        # library" (Teferi's Puzzle Box). The seat this firing is about, frozen
        # by the fire site (CR 603.10) — the source's controller is the wrong
        # one on every draw step but their own, and `context.target` under a
        # trigger that chose nothing holds whatever the resolution was already
        # carrying.
        if event in _EVENT_SUBJECT_PLAYERS:
            payload["recipient"] = EVENT_SUBJECT_PLAYER
            return _with_that_many_draw(node, payload)
        # "Target player discards a card unless **they** put a card from their
        # hand on top of their library." (Tainted Specter.) The offer's own
        # payer, which the sentence in front of it already targeted — so the
        # seat is the resolution's chosen player and no second target is
        # described. ``recipient`` says which of the two seats the handler reads
        # rather than leaving it to the key's absence: the same seat
        # ``_offered_seats`` hands the offer to, spelled once on both sides.
        payload["recipient"] = "target"
        return _with_that_many_draw(node, payload)
    raise LoweringError(
        f"no handler puts {node.player.kind!r}'s hand cards on their library",
        node=node,
    )


#: The scratchpad key ``put_hand_cards_on_library`` writes and "then draws that
#: many cards" reads. Declared in ``lowering/_records._PRODUCES`` under the same
#: name; spelled here so the two halves of Teferi's Puzzle Box's one sentence
#: cannot be wired to different keys.
HAND_CARDS_TO_LIBRARY_RESULT = "hand_cards_to_library"


def _with_that_many_draw(
    node: ast.PutHandCardsOnLibrary, payload: dict[str, object],
) -> tuple[OracleInstruction, ...]:
    """The put, and behind it the draw the same sentence asks for.

    "…, **then draws that many cards**" (Teferi's Puzzle Box) counts what the
    put actually moved, which is the only place the number exists: by the time
    the draw runs the hand is empty. The put records it before arming its
    prompt, so the two steps are one ``sequence`` and the draw reads the record
    — ``run_resumable`` is what carries the draw across the prompt, since the
    order the cards land in is a decision the player has not made yet.

    The drawer is the same seat the put named. Read off ``recipient`` rather
    than re-derived, because "that many cards" is drawn by the player who just
    put them back and by nobody else.
    """
    put = OracleInstruction("put_hand_cards_on_library", "", payload)
    if not node.then_draw:
        return (put,)
    draw: dict[str, object] = {"amount_from": HAND_CARDS_TO_LIBRARY_RESULT}
    recipient = payload.get("recipient")
    if recipient == EVENT_SUBJECT_PLAYER:
        draw["drawer_seat_record"] = EVENT_SUBJECT_PLAYER
    elif recipient == "caster":
        draw["recipient"] = "caster"
    else:
        raise LoweringError(
            "no handler draws for the seat this put named", node=node
        )
    return (
        OracleInstruction(
            "sequence", "",
            {"steps": (put, OracleInstruction("draw_target_cards", "", draw))},
        ),
    )
