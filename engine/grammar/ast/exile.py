"""Cards **naming the exile zone** (CR 406): going there, and coming back.

Split out of ``ast/cards.py`` at Tempest's third wave, when Living Death's
per-seat return crossed that module's thousand-line guard. The line is the one
``effects/exile.py`` drew when it split off ``effects/cards.py`` two sets
earlier, read as a question about a *node* rather than about a reader —

    "What stayed in ``cards`` is what the module's own docstring claims — a
    card *moving* between hand, library and graveyard; what came here names the
    exile zone, and the two shared no production."

— and ``ast/cards.py``'s docstring is the other half of the argument, because
it has never listed these: "Cards moving: draw, discard, mill, search, shuffle,
reveal." Exile was not one of the six and had not been for two sets.

That file also recorded, in the same breath, why these nodes had stayed put:
"``ast/`` has no ``exile`` for the reason ``zones``, ``library`` and
``permissions`` already record: the guard fires on the readers, and these nodes
sit perfectly well beside the other card nodes." Both clauses were true when
they were written and the first one has now expired — the guard fired on the
nodes. The family name is the mirror's, unchanged, so ``effects/exile.py``,
``lowering/exile.py`` and this file are one subject with one word for it.

**The cut is by subject, not by reader**, and it has to be: the two reader-side
families disagree about four of these nodes and always have. ``ExileTopOfLibrary``
parses in ``effects/zones.py`` and lowers in ``lowering/linked_exile.py``;
``ExileRandomFromHand`` parses in ``effects/cards.py`` and lowers in
``lowering/hand.py``; ``CastFromExiledWith`` lowers in ``lowering/permissions.py``.
Following either reader would have split this family down the middle and left
the other half wherever its reader happened to live. What every node below has
in common is the zone it names, which is the one thing none of them disagrees
about.

A family rather than a floor, and it reads nothing: like every other module in
this package it imports ``_core`` and ``costs`` and no sibling, and
``__init__`` re-exports it flat — so no caller outside this package names the
family, and moving a node here is a non-event by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import (
    Amount,
    GraveyardPosition,
    ObjectFilter,
    PlayerRef,
    Zone,
)


@dataclass(frozen=True)
class ExileRandomFromHand:
    """``<player> exiles a card at random from their hand.`` (Elkin Lair.)

    The same object phrase :class:`RevealRandomFromHand` reads — one card the
    player does not choose — under a different verb, and a node of its own
    rather than a mode on that one because the two effects share nothing past
    the phrase. A reveal leaves the card where it was and records "the revealed
    card"; this moves it to another zone and records the *pile* every "you may
    play that card" behind it reads. One node with a verb field would be one
    referent for two questions, which is how a sentence about the card you
    revealed comes to be answered with the card you exiled.
    """
    player: PlayerRef


@dataclass(frozen=True)
class PutExiledCardIntoZone:
    """``Put that card into your hand.`` (Necropotence, inside its delay.)

    ``If you haven't played it, put it into its owner's graveyard.``
    (Grinning Totem, inside its delay.)

    "That card" / "it" is the one an earlier step of the **same effect**
    exiled, so this reads the resolution's own record rather than choosing
    anything — the same back-reference "you may play cards exiled this way"
    makes, and demanded of its producer for the same reason: a sentence with
    nothing behind it is the sentence read wrong.

    The zone was fixed by the node until Mirage printed the second
    destination, and it is a field now for the reason every parameter in this
    grammar is payload: what changes between the two sentences is where the
    card goes, and nothing else. Which destinations have a handler is the
    lowering's question, and it refuses the rest by name.

    ``only_if_unplayed`` is Grinning Totem's printed condition. It states what
    the move already does rather than narrowing it — a card that was played is
    no longer in exile, and this instruction only ever moves a card out of
    exile — so it changes no outcome and is carried anyway, because a word
    consumed and never read could be deleted with no sign, and because it is
    what lets the log say *why* nothing moved.
    """
    zone: Zone
    only_if_unplayed: bool = False


@dataclass(frozen=True)
class PutExiledThisWay:
    """``Each player … puts all cards they exiled this way onto the
    battlefield.`` (Living Death.)

    :class:`PutExiledCardIntoZone`'s sibling with a **subject**, and the
    subject is the whole difference. That node reads the resolution's flat
    record — what this effect exiled, whoever exiled it — which is the right
    reading while one seat does the exiling. Distributed over the table the
    same record answers the wrong question: "cards **they** exiled this way"
    names one seat's pile per seat, and a flat list read once per player hands
    each of them the whole table's graveyards.

    So the record this reads is the per-seat one
    (``oracle_types.EXILED_BY_SEAT``), and :attr:`actor` is what says the
    sentence is asking it per seat rather than as a whole. It is demanded of
    its producer like every other back-reference in this grammar: with no
    exiling step behind it the words name nothing and the card would compile
    supported and put nothing anywhere.

    The destination is a field for the reason every parameter here is payload —
    a printing that gave the cards back to a hand would be this sentence with
    another zone — and which destinations have a handler is the lowering's
    question.
    """

    zone: Zone
    #: The printed narrowing, if the sentence prints one ("all **creature**
    #: cards they exiled this way"). Carried rather than assumed empty: the
    #: pile is whatever the exiling step put there, and a card whose phrase
    #: named a subset would otherwise get the lot back.
    filter: ObjectFilter = field(default_factory=ObjectFilter)
    #: Who puts them there — and, through CR 110.2a, who controls what arrives.
    #: ``None`` is the unnamed subject every bare imperative has: the ability's
    #: own controller.
    actor: PlayerRef | None = None


@dataclass(frozen=True)
class ExileBoundCard:
    """``Exile that card from your graveyard.`` (Necropotence.)

    The card the firing event named, exiled out of the zone that event put it
    in. Not an :class:`Exile` of a permanent: nothing is on the battlefield and
    nothing is chosen — "that card" is the discard the trigger watched, and the
    only place it can be read is the event's own captured context.

    ``from_zone`` is None where the card prints no zone at all ("Whenever a
    nontoken creature is put into your graveyard from the battlefield, **exile
    that card**", Purgatory). It is not the same sentence with a word missing:
    Necropotence's trigger is about a *discard*, whose card could have been
    replaced somewhere else on its way (Library of Leng), which is why that
    spelling names the pile it expects to find it in. A death trigger has
    already said where the card went — its own condition is "is put into <a>
    graveyard" — so the zone is in the event rather than in the effect, and the
    two lower to two handlers that look in two places.
    """
    from_zone: Zone | None = None


@dataclass(frozen=True)
class ExileCostSacrifices:
    """"…, then **exile this artifact and those creature cards**." (Sword of
    the Ages.)

    What the ability's own cost sacrificed, exiled from the graveyard it is
    already in. Not an ordinary exile of a permanent: CR 601.2h paid the cost
    before the ability reached the stack, so by the time this step runs there is
    nothing on the battlefield to move — and CR 400.7 makes each of them a new
    object in the graveyard, which is why "those creature cards" says *cards*.

    No fields: the set is the one the activation recorded, and "this artifact"
    is the ability's own source. A production that let the sentence name some
    other set would be naming objects nothing kept.
    """


@dataclass(frozen=True)
class ExileGraveyard:
    """``Exile target player's graveyard.`` (Tormod's Crypt.)

    A whole *zone*, not a card in one, which is why it is its own node rather
    than an :class:`Exile` over a noun phrase: there is nothing to filter, no
    target among the cards, and the count is however many are there when it
    resolves.

    ``player`` is None for "exile **all graveyards**" (Bazaar of Wonders) — the
    sweep over every seat, which names nobody and targets nothing. A sentinel
    seat would have been the other way to say it and is the wrong one: "all
    graveyards" chooses no target (CR 115.1), and a ``PlayerRef`` here is read
    by the picker as one.
    """
    player: PlayerRef | None


@dataclass(frozen=True)
class ExileEntireLibrary:
    """``That player exiles all cards from their library.`` (Thought Lash.)

    Beside :class:`ExileTopOfLibrary` rather than a very large count of it: that
    one names a printed number and can exile fewer cards than it says when the
    library runs short, and this one is defined by the *zone being emptied* — so
    it is payable, and meaningful, on a library of any size including none.

    Carries whose library, because the sentence names a seat and the pool prints
    both readings ("**you** exile" / "**that player** exiles"). Dropping it
    would empty the resolving player's library for a card naming somebody
    else's.
    """
    player: "PlayerRef"


@dataclass(frozen=True)
class ExileTopOfLibrary:
    """``Exile the top three cards of your library.`` (Chandra, Heart of Fire's
    +1.) Always the controller's own library — no card prints another player's
    — and the exiled cards are recorded for a following sentence's "cards
    exiled this way" to read, which is the reason this is not a Mill with a
    different destination.

    *face_down* is Knowledge Vault's rider (CR 406.3): the cards go to exile
    face down, so no player may look at them. It rides the node rather than
    becoming a second statement because it is a property of the exiling, not an
    effect after it — a face-up exile followed by a "turn them face down" is
    not what the card says.
    """
    count: Amount
    face_down: bool = False


@dataclass(frozen=True)
class ExileGraveyardPosition:
    """``Exile the bottom card of target player's graveyard.`` (Phyrexian
    Furnace.) The same phrase Barrow Ghoul and Circling Vultures print as the
    price of an "unless you …" offer, which the board family decomposes into a
    :class:`~.statements.May` around this node.

    Beside :class:`ExileTopOfLibrary` and separate from it for
    :class:`~.costs.ExileGraveyardPositionCost`'s stated reason: a library exile
    is counted off the top blind, and this one **scans** the ordered pile
    (CR 404.1/404.2) for the printed characteristic. It carries a whole
    :class:`~._core.GraveyardPosition` rather than the three fields loose,
    because that spec is exactly what the cost node carries — one referent read
    once, so a cost and an effect printing the same words cannot disagree about
    which card they name.
    """
    position: GraveyardPosition


@dataclass(frozen=True)
class PutExiledWithSource:
    """``Put all cards exiled with this artifact into their owner's hand.``
    (Knowledge Vault, both of its linked abilities — the other one says
    "exiled with **it**" and lands in their owner's graveyard.)

    A *linked* ability (CR 610.3): the pile it names is exactly the cards the
    source's own earlier ability exiled, which is why there is nothing here to
    filter and no target to pick — the record answers "which cards", and the
    only thing printed that varies is where they land.

    That is why *zone* is a payload field and not part of a kind name: a second
    card printing the same sentence with a different destination needs no code.

    ``chosen`` is the other printed quantity: "Return **a card you own** exiled
    with this artifact to your hand" (Gustha's Scepter) moves *one* card and
    the ability's controller says which. It is a field rather than a second
    node because everything else about the sentence is this one — the same
    linked pile, the same destinations, the same self-reference — and the
    difference the card states is how many cards move. ``owned_by_you`` is the
    restriction printed beside it, and it is only meaningful when one card is
    picked: a sweep of the whole pile sends every card to its own owner and so
    cannot be narrowed by whose it is.
    """
    zone: Zone
    chosen: bool = False
    owned_by_you: bool = False
    #: "Put **all other** cards you own exiled with this enchantment into your
    #: hand." (Duplicity.) A back-reference on a *sweep*: "other" means other
    #: than the cards the same ability exiled a sentence earlier, so the
    #: lowering demands that step and the handler excludes exactly the entries
    #: it created. Not expressible as a filter — the pile may already hold
    #: another copy of the same card, and a hand repeats one immutable
    #: ``CardDefinition`` per copy, so the cards are not distinct either.
    others_only: bool = False
    #: "Return **each creature card** exiled with this artifact…" (Cold
    #: Storage). The printed card type narrowing the pile, as a card-type word.
    #: Carried rather than consumed for the reason ``owned_by_you`` is: the pile
    #: a linked ability names is whatever its twin put there, and Cold Storage's
    #: twin exiles only creatures — but "only" is a fact about *today's* board,
    #: not about the sentence, and a permanent whose types were changed while
    #: exiled would make a dropped narrowing visible. Empty means the sentence
    #: printed none and the whole pile moves.
    card_type: str | None = None
    #: "…to the battlefield **under your control**" (Cold Storage). CR 110.2a's
    #: seat spelled out on the sweep, where ``chosen``'s battlefield form infers
    #: it from the absent possessive. Its own field rather than that inference,
    #: because Safe Haven prints "under **its owner's** control" onto the same
    #: sweep and the two are different seats — inferring would hand Cold
    #: Storage's creatures to whoever owned them.
    under_your_control: bool = False


@dataclass(frozen=True)
class SearchAndExile:
    """``Search your graveyard and library for any number of <filter> cards,
    exile them, then shuffle.`` (Chandra, Heart of Fire's −9.)
    ``Search your library for three cards, exile them, then shuffle.``
    (Foresight.)

    Not a :class:`SearchLibrary`: that node's whole contract is *one* found
    card put into the hand, and this one exiles several.

    The two printed shapes differ in exactly two facts, so both are fields
    rather than a second node. :attr:`zones` is which piles are searched —
    named rather than assumed, because a wording that searched fewer places
    than printed would be a silently smaller effect. :attr:`count` is the
    printed ceiling, ``None`` for "any number"; CR 701.23b lets a search find
    fewer, so it is a maximum and never a requirement.
    """
    filter: ObjectFilter
    zones: tuple[str, ...] = ("graveyard", "library")
    count: int | None = None
    #: "…exile them **in a face-down pile**" (Mangara's Tome). Two printed
    #: facts, and two fields rather than one, because they are separable: the
    #: pile is hidden (CR 406.3) *and* it is a pile — a run of cards recorded
    #: on the exiling permanent (CR 610.3), which is what a later ability
    #: naming "the exiled pile" can be linked to. A card printing the phrase
    #: without the shuffle would be the same effect minus the randomisation.
    face_down_pile: bool = False
    #: "…**and shuffle that pile**" (Mangara's Tome). The pile's *order* is
    #: randomised, which is the whole point of a card that then reads it one
    #: card at a time from the top — a searched pile in library order would let
    #: the searcher choose what comes back and in what sequence.
    shuffle_pile: bool = False


@dataclass(frozen=True)
class PutExiledPileTopIntoHand:
    """"Put the top card of the exiled pile into its owner's hand."
    (Mangara's Tome.)

    "The exiled pile" is CR 610.3's linked pile — the run of cards the same
    permanent's other ability exiled — so this names no zone the sentence could
    have meant differently and carries no payload: which cards, and whose, are
    the record's answer rather than this node's.
    """


@dataclass(frozen=True)
class ExileGraveyardUntilLeaves:
    """``Exile all creature cards with mana value 3 or less from your graveyard
    until this artifact leaves the battlefield.`` (Idol of Endurance.)

    A sweep of a *graveyard*, not of a battlefield, with a duration tied to the
    source rather than to a turn — so the exiled cards are remembered **on the
    permanent**: they come back when it leaves, and there is nothing to sweep
    at cleanup.

    The set it exiles is also the set its other ability casts from ("cards
    exiled with this artifact"), which is why the pile is recorded rather than
    merely moved: a second reading of "what did this exile?" could not answer.
    """
    filter: ObjectFilter


@dataclass(frozen=True)
class CastFromExiledWith:
    """``Until end of turn, you may cast a creature spell from among cards
    exiled with this artifact without paying its mana cost.``
    (Idol of Endurance.)

    A CR 601.3 permission over the pile the line above recorded, with CR 118.9's
    cost waiver. Its own node rather than a ``CastPermission`` variant because
    the *source* of the pile is a permanent rather than a resolution: "cards
    exiled with this artifact" names a set that outlives the effect that made
    it.
    """
    filter: ObjectFilter
    free: bool = True
