"""The shuffles: a library put back into a random order (CR 701.24).

Five nodes, and the axis between them is *what* is shuffled in first: a
graveyard or a part of one (Feldon's Cane, Barishi, Gaea's Blessing), the
ability's own source (Alabaster Dragon), a chosen permanent (Rishadan
Pawnshop), a hand or a part of one (Winds of Change, Lat-Nam's Legacy), and
nothing at all — the bare "Then that player shuffles" (Prophecy).

Split off ``ast/board.py`` at Planeshift's Phase 0, when that module sat 35
lines under the thousand-line guard with a wave about to open on it. These were
the nodes its docstring had never claimed. It lists destroy, sacrifice, exile,
regeneration and return-to-zone — "what happens *to* a permanent" — and four of
the five here never touch a battlefield: a graveyard, a hand and a library are
piles of cards. The fifth does, and travels with them for the reason its own
docstring gives: it is :class:`ShuffleSourceIntoLibrary` with the object chosen
instead of named.

They were also the half that grows. ``board`` gained 123 lines after
``control_changes`` left it at Exodus's second wave, and 49 of them landed here
(``ShuffleHandIntoLibrary`` twice, ``ShuffleTargetIntoLibrary`` whole), where
``Destroy``, ``Sacrifice`` and ``Exile`` themselves did not change by a
character.

The name is ``lowering/shuffles.py``'s and the mirror is exact: that module
lowers these five nodes and no other, and nothing else lowers one of them. Its
line is this file's — a zone change answers "which zone does this object end up
in", a shuffle answers "what order is this library in now" — which is why this
is not ``zones``, the word the *parse* side would have offered. All five are
built in ``effects/zones.py``, but on the lowering side ``zones`` names the
question the shuffles left. There is no ``effects/shuffles.py``: the
productions' module is nowhere near its guard.

``ast/cards.py`` is where its own first line would put them ("Cards moving:
draw, discard, mill, search, shuffle, reveal"), and they were never there; it
stood at 794 lines and could not have taken them. The three-line ``Shuffle`` it
does hold is the up-front inventory's node and nothing builds it —
:class:`ShuffleLibrary` below is the bare shuffle the productions produce.

A family rather than a floor, and it reads nothing: ``_core`` and no sibling,
re-exported flat by ``__init__``, so no caller names it and none moved.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._core import ObjectFilter, PlayerRef, Recipient, TargetSpec


@dataclass(frozen=True)
class ShuffleGraveyardIntoLibrary:
    """``Shuffle your graveyard into your library.`` (Feldon's Cane.)

    Its own node rather than a `ReturnToZone` with a zone pair: this moves a
    *whole zone* rather than any object a filter could name, and shuffling is
    part of the move rather than a rider on it (CR 701.24a).
    """
    whose: PlayerRef
    #: "Shuffle **all creature cards** from your graveyard into your library."
    #: (Barishi.) Which cards move, when the sentence names a set instead of
    #: the zone. None is Feldon's Cane's whole graveyard.
    #:
    #: A field rather than a second node, because the difference really is a
    #: narrowing: nothing is chosen either way (a graveyard is a public zone
    #: and "all" leaves no decision), the destination is the same library, and
    #: CR 701.24a makes it one shuffle either way. What the field must never do
    #: is go unread — a filter dropped here is Barishi shuffling back every
    #: land and every spell as well.
    cards: ObjectFilter | None = None
    #: "Target player shuffles **up to three target cards** from their
    #: graveyard into their library." (Gaea's Blessing.) The moving subset
    #: again, this time **chosen** rather than described: the controller names
    #: the slots at announcement (CR 601.2c), where ``cards`` above leaves
    #: nobody a decision.
    #:
    #: Beside ``cards`` rather than folded into it because the two are read by
    #: different machinery — a filter is tested against every card in the pile,
    #: a target list is enumerated for a picker and re-checked at resolution —
    #: and a card printing both would be naming one set twice.
    chosen: "TargetSpec | None" = None


@dataclass(frozen=True)
class ShuffleSourceIntoLibrary:
    """``When this creature dies, shuffle it into its owner's library.``
    (Alabaster Dragon.)

    One *object* rather than a pile, which is what separates it from the three
    nodes around it: they move a zone, and this moves the ability's own card
    out of wherever it now is. By the time the trigger resolves that is a
    graveyard (CR 603.10), but the sentence names no source zone at all, so the
    handler reaches whichever zone actually holds it.

    ``owner`` is read rather than assumed. CR 404.1 sends a permanent to its
    owner's graveyard and CR 701.24a shuffles a library its owner owns, so "its
    owner's" is the only seat this sentence can name — but a card printing
    "your library" instead would be a different card for a creature that
    changed hands, and consuming the possessive unread is how it would compile
    onto this one.
    """
    owner: PlayerRef


@dataclass(frozen=True)
class ShuffleTargetIntoLibrary:
    """``{2}, {T}: Shuffle target nontoken permanent you control into its
    owner's library.`` (Rishadan Pawnshop.)

    :class:`ShuffleSourceIntoLibrary` with the object **chosen** instead of
    named. Its own node rather than a ``subject`` field on that one, because
    the two ask different things of everything downstream: this one is a target
    (CR 601.2c — announced, offered by a picker, rechecked at resolution) where
    that one is the ability's own card, and a node that meant either would give
    the picker nothing to enumerate on half the cards it reached.

    Deliberately not :class:`PutOnLibraryTop` with a flag: that node's whole
    subject is a *position* in the library, and a shuffle has none — CR 701.24a
    randomises the pile, so "where did it go" stops being a question rather than
    getting a different answer.

    ``owner`` is read for :class:`ShuffleSourceIntoLibrary`'s reason and it
    matters more here: the phrase says "you control", so the permanent's
    controller is the activator, while CR 400.3 sends the *card* to its owner's
    library — and on a permanent taken with a control-change effect those are
    two different players.
    """
    target: Recipient
    owner: PlayerRef


@dataclass(frozen=True)
class ShuffleHandIntoLibrary:
    """``Each player shuffles the cards from their hand into their library,
    then draws that many cards.`` (Winds of Change.)

    Beside the graveyard shuffle above and for the same reason: a whole zone
    moves, and the shuffle is part of the move rather than a rider on it
    (CR 701.24a). ``then_draw`` is on the node instead of being a second
    statement because "that many" is the number the shuffle just moved — a
    count nothing else in the sentence knows, so a draw parsed apart from it
    would have no producer to read.
    """
    whose: PlayerRef
    then_draw: bool = False
    #: "…into their library, **then draws seven cards**." (Time Spiral.) The
    #: same trailing draw with a *printed* number instead of "that many", which
    #: is a different card rather than a spelling of the same one: Winds of
    #: Change hands back exactly what it took, and this draws seven whatever the
    #: hand held — an empty hand and graveyard still draw a full grip.
    #:
    #: Its own field rather than a widening of ``then_draw`` above, because the
    #: two answer different questions of the handler ("how many moved?" against
    #: "how many does the card say?") and a bool that also meant a number would
    #: make ``then_draw=1`` and ``then_draw=True`` the same payload.
    then_draw_count: int | None = None
    #: How many cards move, when the sentence names a **number** of them rather
    #: than the whole zone: "Shuffle **a card** from your hand into your
    #: library." (Lat-Nam's Legacy.) None is Winds of Change's whole hand.
    #:
    #: The difference is a decision, not only a count. A whole hand moves with
    #: nothing to choose; a counted subset is the hand's owner picking which
    #: cards, and a hidden zone means nobody else can (CR 402.1). So the two
    #: readings lower to two handlers, and this field is what tells them apart.
    count: int | None = None
    #: "Shuffle **any number of** cards from your hand into your library."
    #: (Credit Voucher.) The count above with the number left to the player
    #: instead of printed — CR 601.2b's kind of announcement made during a
    #: resolution, so nothing knows it until the hand's owner says.
    #:
    #: Its own flag rather than a sentinel in ``count`` for that field's own
    #: reason: a number and "as many as you like" are different questions of the
    #: handler, and an integer that also meant "ask" would make ``count=0`` and
    #: "shuffle none" the same payload. It is also what makes the trailing "then
    #: draw that many cards" legal here where a *printed* number refuses it —
    #: behind a printed number "that many" would be the number said twice, and
    #: behind this one it is the only place the number exists.
    any_number: bool = False
    #: "Each player shuffles their hand **and graveyard** into their library."
    #: (Diminishing Returns.) A second pile joining the same move, and part of
    #: this node rather than a `ShuffleGraveyardIntoLibrary` beside it because
    #: CR 701.24 makes the whole thing **one** shuffle: two statements would
    #: randomise the library twice and, worse, would let a card land in the
    #: library from the hand and then be shuffled again knowing it was there.
    #: The seats also have to agree — "their … their" is one player per
    #: iteration, which two independent statements cannot promise.
    with_graveyard: bool = False


@dataclass(frozen=True)
class ShuffleLibrary:
    """``Then that player shuffles.`` (Prophecy.) ``Shuffle your library.``

    CR 701.24's shuffle with **nothing moving into the library first**, which
    is the whole of what separates it from the two nodes above: those are zone
    moves whose shuffle is part of the move, and this is a card having been
    looked at and the deck being randomised again so nobody knows where it went.
    Folding it into either would give a shuffle a pile to move that the printed
    sentence never names.

    Not a rider on the sentence before it, either. A search shuffles because
    CR 701.23h ends every search with one, and that shuffle is spelled inside
    the search production for exactly that reason; a *reveal* ends with no
    shuffle at all, so Prophecy prints one and it is a statement of its own.
    """
    whose: PlayerRef
