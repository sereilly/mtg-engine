"""Conditions answered by a record kept about a **player**.

"…unless **one of their opponents was dealt damage this turn**" (Antagonism),
"…if **that player didn't cast a spell this turn**" (Impatience).

The cut is `condition_clauses`' own, taken one axis further. That module holds
every condition answered by a *record* rather than by a board read, and it says
so; what it does not say is that its records are about **objects** — a card that
left a zone, a creature that died this way, a permanent that changed hands. The
two clauses here are about a **seat**: which player took damage, which player
cast something. No object is involved at any point, and the noun-phrase and
back-reference vocabulary the rest of that module is built from is unused by
both.

It sits beside `seats`, `seat_comparisons` and `seat_relations`, which is the
name this family already carries on the parse side — the fourth thing a printed
sentence can say about a player, after which seat it *is*, how it *compares*
with another, and what it *owns*. What it **did**.

No mirror name to reuse, and the near miss is worth stating: `records` one layer
down is the parse-side mirror of `lowering/_records.py` and reads a *quantity*
off an event, and `histories` above it reads a record as a narrowing on a noun
phrase. Neither is this — these return a whole `Condition`, and their lowering
sits in `lowering/_record_conditions.py` beside every other condition's, which
has never split. Taking either word would fork a name inside one package rather
than re-form one across two.

Split off `condition_clauses` at Urza's Destiny's wave 1, when the second of
these clauses took that module past the thousand-line guard. Both moved, not
just the new one: a family with one member is a cut, and the point of the guard
is to find the boundary that was already there.

Below `condition_clauses`, which calls it and is never imported back.
"""

from . import ast
from .stream import TokenStream


#: Whose opponents "one of <possessive> opponents" names, as the referent the
#: lowering resolves. "Their" is the seat the firing event was about (CR 603.10,
#: frozen by the fire site); "your" is the ability's controller (CR 109.5). A
#: table rather than one printed word, because the two spellings are the same
#: sentence about two different seats and welding either in would make the other
#: unprintable.
_OPPONENT_POSSESSIVES: dict[str, str] = {
    "their": "that_player",
    "your": "you",
}


def _accept_seat_damage_record(stream: TokenStream) -> "ast.Condition | None":
    """``one of <their|your> opponents was dealt damage this turn`` — or None.

    "…this enchantment deals 2 damage to that player **unless one of their
    opponents was dealt damage this turn**." (Antagonism.)

    A record clause like every other in this reader: no board read answers it,
    because a life total is the turn's net and a player dealt 4 who then gained
    4 has still been dealt damage. ``engine/damage_ledger.py`` is what keeps it.

    Non-consuming on refusal, so the dispatcher's next branch keeps its say.
    """
    mark = stream.mark()
    if not stream.accept_phrase("one", "of"):
        return None
    referent = _OPPONENT_POSSESSIVES.get(stream.peek_word() or "")
    if referent is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("opponents"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("was", "dealt", "damage", "this", "turn"):
        # The seat class is read and the record is not: some other sentence
        # about the same players, which this must leave whole rather than
        # consume half of.
        stream.reset(mark)
        return None
    return ast.SeatWasDealtDamageThisTurn(referent)


#: The seats this clause is printed about, as the referent the evaluator
#: resolves. "That player" is the seat the firing event named and "you" the
#: ability's controller (CR 109.5) — one question about two seats, which is why
#: the word is payload rather than two conditions.
_CAST_RECORD_SEATS: dict[tuple[str, ...], str] = {
    ("that", "player"): "that_player",
    ("you",): "you",
    ("an", "opponent"): "an_opponent",
}


def _accept_seat_cast_record(stream: TokenStream) -> "ast.Condition | None":
    """``<seat> [didn't] cast a spell this turn`` — the node, or None.

    "At the beginning of each player's end step, **if that player didn't cast a
    spell this turn**, this enchantment deals 2 damage to that player."
    (Impatience.)

    A record clause like its neighbours: nothing on the board answers it. A
    resolved spell has left the stack, a countered one has left it too, and a
    permanent that entered from a cast looks exactly like a reanimated one — so
    the per-seat, per-turn list the casting path already writes is the only
    thing that can say. Both signs are read because both are printed English and
    a table holding one of a pair is how a gate nothing can fail gets written.

    Non-consuming on refusal, so the dispatcher's next branch keeps its say —
    and every word after the seat is required: "that player didn't" opens
    several sentences this must leave whole rather than consume half of.
    """
    mark = stream.mark()
    referent = None
    for words, name in _CAST_RECORD_SEATS.items():
        if stream.accept_phrase(*words):
            referent = name
            break
    if referent is None:
        return None
    negated = bool(stream.accept_word("didn't"))
    if not negated and not stream.accept_word("cast"):
        stream.reset(mark)
        return None
    if negated and not stream.accept_word("cast"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("a", "spell", "this", "turn"):
        # The seat is read and the record is not: some other sentence about the
        # same player, left whole for the branch that can read it.
        stream.reset(mark)
        return None
    return ast.SeatCastSpellThisTurn(referent, negated)


def _accept_seat_land_record(stream: TokenStream) -> "ast.Condition | None":
    """``<seat> [didn't] play a land this turn`` — the node, or None.

    "At the beginning of your end step, **if you didn't play a land this
    turn**, you may draw a card." (Mercadian Atlas.)

    The cast clause above one special action over (CR 305.1). It is a record for
    that clause's reason: by the end step a land played this turn is an ordinary
    permanent, indistinguishable from one put onto the battlefield by a spell or
    one that has been there since turn three, so ``Game.lands_played_this_turn``
    is the only thing that can answer.

    The seat table is shared with the cast clause deliberately — the two are one
    vocabulary, and a second copy is how the two spellings come to disagree
    about which words name a seat. Both signs are read for its reason too.

    Non-consuming on refusal, so the dispatcher's next branch keeps its say.
    """
    mark = stream.mark()
    referent = None
    for words, name in _CAST_RECORD_SEATS.items():
        if stream.accept_phrase(*words):
            referent = name
            break
    if referent is None:
        return None
    negated = bool(stream.accept_word("didn't"))
    if not stream.accept_word("play"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("a", "land", "this", "turn"):
        # The seat and the verb are read and the record is not — "you play a
        # land" opens several sentences this must leave whole rather than
        # consume half of.
        stream.reset(mark)
        return None
    return ast.SeatPlayedLandThisTurn(referent, negated)
