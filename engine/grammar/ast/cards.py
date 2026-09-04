"""Cards moving: draw, discard, mill, search, shuffle, reveal.

Draw, discard and mill share a shape — a player and a count — and are separate
nodes anyway, because the zones a card moves between are what each of them
means.

Mana used to be here. It is `ast/mana.py` now, mirroring `lowering/mana.py`,
which split off for the same reason: what a permanent *produces* turned out to
be a family of its own rather than a corner of this one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .costs import ManaCost
from ._core import (
    Amount,
    Duration,
    Fixed,
    ObjectFilter,
    PlayerRef,
    TargetSpec,
    Zone,
)


@dataclass(frozen=True)
class Draw:
    player: PlayerRef
    count: Amount = field(default_factory=lambda: Fixed(1))
    # "Each player may draw **up to** two cards." (Truce.) The same field
    # :class:`Discard` below carries and for the same reason: fewer is a legal
    # answer, none included, so the number is a ceiling rather than an amount.
    # Not a second count — what changes is whether it is a floor as well.
    up_to: bool = False


@dataclass(frozen=True)
class Discard:
    player: PlayerRef
    count: Amount = field(default_factory=lambda: Fixed(1))
    at_random: bool = False
    # "Discard your hand" (Chandra, Heart of Fire) — every card, however many.
    whole_hand: bool = False
    # "Discard **up to** two cards" (Kinetic Augur) — fewer is a legal answer,
    # including none. Not a second count: the number is the same, what changes
    # is whether it is a floor as well as a ceiling.
    up_to: bool = False
    # "Discard a **creature** card" (Crypt Lurker) — what the discarded card has
    # to be. None is "any card", which is what the bare template means; an empty
    # filter would say the same thing in a way a reader could mistake for a
    # narrowing that got lost.
    filter: "ObjectFilter | None" = None
    # "Draw two cards, then discard one **of them**." (Krovikan Sorcerer.) The
    # discard comes out of the cards the sentence in front of it drew, not out
    # of the hand at large. Not a `filter`: what it names is identity — *these*
    # cards — and an ObjectFilter describes characteristics, so a card already
    # in hand that happened to match would pay a cost the printed words do not
    # allow. Recorded here and refused by every lowering but the fused
    # draw-then-discard, which is the only one holding the cards it points at.
    of_drawn: bool = False


@dataclass(frozen=True)
class PutHandCardsOnLibrary:
    """``Put two cards from your hand on top of your library in any order.``
    (Brainstorm.) ``Target player chooses three cards from their hand and puts
    them on top of their library in any order.`` (Stunted Growth.)

    A zone change like :class:`Discard`, and **not** one: CR 701.9a makes
    discarding a specific action that a "whenever you discard" ability sees
    (Necropotence exiles what you discard). Putting a card back on your library
    is none of those things, so it is its own node and its own prompt rather
    than the discard one with a destination flag — the flag exists, for Library
    of Leng, and means "this discard lands somewhere else", which is a different
    sentence.

    Both printings choose *which* cards and, with "in any order", what order
    they land in; the player who owns the hand is the player who chooses
    (CR 103.4-style: a hand is a hidden zone its owner reads).
    """
    player: PlayerRef
    count: Amount = field(default_factory=lambda: Fixed(1))
    #: "Target opponent puts **the cards from their hand** on top of their
    #: library." (Jester's Mask.) The whole hand rather than a printed number,
    #: which is not a count the parser can write down: how many there are is a
    #: fact about the board at resolution. Its own flag rather than a magic
    #: ``count``, because only this spelling can never be short — CR 608.2's
    #: "as much as it can" has nothing to trim.
    whole_hand: bool = False
    #: Which end of the library the cards go on. ``"top"`` is every printing
    #: but one; Dream Cache prints ``"either_end"`` — "put two cards from your
    #: hand **both on top of your library or both on the bottom of your
    #: library**", where the end is the player's to choose and both cards go to
    #: the same one. A field rather than two nodes, because the choice is the
    #: only difference: the same cards leave the same hand through the same
    #: prompt.
    destination: str = "top"


@dataclass(frozen=True)
class Mill:
    """"Target player mills N cards." (CR 701.13a, Millstone.)

    A zone change like :class:`Draw`, and kept separate from it for the same
    reason draw and discard are separate: the cards move library-to-graveyard
    without ever being in a hand, so nothing about drawing describes it.
    """
    player: PlayerRef
    count: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class MillUntil:
    """``Target opponent mills a card, then repeats this process until a
    creature card or X cards have been put into their graveyard this way,
    whichever comes first.`` (Helm of Obedience.)

    Not a :class:`Mill` with a count: a mill of N is one move of N cards and
    nothing looks at them on the way, where this one is a **loop** asked after
    every single card whether to keep going, and *which* card came off the top
    decides. Both stopping conditions are fields because both are printed and
    either can be the one that fires - a loop that only counted would keep
    milling past the creature it was looking for, and one that only watched
    would empty a creatureless library into a graveyard.

    "Whichever comes first" is not a third field: it states what two stopping
    conditions on one loop already mean.
    """
    player: PlayerRef
    stop_filter: ObjectFilter
    limit: Amount


@dataclass(frozen=True)
class PutMilledCardOntoBattlefield:
    """``…put one of them onto the battlefield under your control.`` (Helm of
    Obedience, the sentence after its loop.)

    "Them" is the set the loop recorded, not a target and not a search: the
    cards are in an opponent's graveyard, and *which* of them may be taken is
    answered only by what this effect put there. A card the graveyard already
    held is not one of them.

    Its own node rather than a reanimation with a back-reference field, for
    :class:`ExiledThisWay`'s reason one file over: what separates it from every
    other reanimation is which earlier step recorded the set, and a node
    carrying the record's name as data would be a back-reference free to name a
    record nothing writes.
    """
    filter: ObjectFilter = field(default_factory=ObjectFilter)


@dataclass(frozen=True)
class Scry:
    """"Scry N." (CR 701.22a.)

    No player field, unlike Draw/Discard/Mill: CR 701.22a defines scrying over
    *your own* library, and every printed template is the bare imperative. A
    subject-taking spelling would be a different sentence and earns its own
    node when a card prints one, rather than a player ref that is always "you".

    Beside Mill because both move cards off the top of a library without
    passing through a hand; scry differs in that the cards may come back, which
    is why it is a decision rather than a transfer.
    """
    count: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class Shuffle:
    player: PlayerRef


@dataclass(frozen=True)
class RevealHand:
    """``<player> reveals their hand`` (CR 701.16).

    The reveal on its own — Inquisition, whose next sentence reads the hand's
    *size*, and the first half of "…**and** discards all nonland cards"
    (Amnesia) or "…and discards a creature card at random" (Rag Man).

    Its own node rather than a flag on the discard beside it, because the reveal
    is a game action with its own consequence — the hand becomes public
    information, which is what makes an at-random discard verifiable — and it
    composes: a card printing a reveal in front of some *other* act on the same
    hand needs no second production. :class:`RevealHandAndChoose` stays separate
    because its three sentences share a *choice*, which is not composable in
    that way: the middle sentence names a card the first one revealed.
    """
    player: PlayerRef


@dataclass(frozen=True)
class RevealRandomFromHand:
    """``<player> reveals a card at random from their hand.`` (Wand of Ith.)

    Not a :class:`RevealHand` with a count: that reveal makes the *whole* hand
    public and chooses nothing, while this one picks one card the player does
    not choose (CR 701.16 over a random selection). The distinction matters
    downstream — the sentences behind this one ask what "it" is, and there is
    no "it" after a hand reveal.

    Its record is the one every "if it's a …" already reads, so the branch
    behind it is the existing condition rather than a second one.
    """
    player: PlayerRef


@dataclass(frozen=True)
class DiscardRevealedUnlessPayLife:
    """``<player> discards it unless they pay <N> life.`` (Wand of Ith.)

    "It" is the card an earlier sentence of the same effect revealed. An offer
    made to a seat that is not the ability's controller, with the discard as its
    declined branch — the shape :class:`UnlessPlayerPays` has for a mana cost
    made to an opponent, printed the other way round and paid in life.

    ``mana_value_of_revealed`` is the second printed amount: "life equal to
    **its** mana value" is a number nothing knows until the card is revealed, so
    it is a flag rather than an :class:`Amount` the parser could resolve.
    """
    player: PlayerRef
    amount: Amount | None = None
    mana_value_of_revealed: bool = False


@dataclass(frozen=True)
class RevealHandAndChoose:
    """``Target opponent reveals their hand. You choose a <filter> card from
    it. That player discards that card.`` (Duress.)

    Three printed sentences, one node — for the same reason See the Truth's
    three are one: they share the revealed hand, and parsed apart the middle
    sentence would be a choice over a zone nobody revealed and the last one a
    discard of a card nobody chose.

    *fate* is what happens to the chosen card, because that is the only thing
    the family varies (Kitesail Freebooter exiles it instead of discarding it,
    Painful Memories puts it on top of that player's library), and it decides
    which handler ending runs.
    """
    player: PlayerRef
    filter: ObjectFilter
    fate: str = "discard"
    #: "…and choose **X** cards from it" (Mind Warp). How many are chosen, which
    #: the family varies as freely as it varies the fate. One rather than none
    #: is the default because that is what every printing before this one says.
    count: Amount = field(default_factory=lambda: Fixed(1))
    #: Whether the hand was **revealed** (Duress) or only **looked at** (Mind
    #: Warp). CR 701.20 makes a reveal public and CR 701.16 makes a look
    #: private, so the two sentences give different information to everyone who
    #: is not the chooser — the same choice, made from a zone the rest of the
    #: table can or cannot see.
    revealed: bool = True


@dataclass(frozen=True)
class RepeatedGraveyardPick:
    """Forgotten Lore's whole four-sentence effect.

    ``Target opponent chooses a card in your graveyard. You may pay {G}. If you
    do, repeat this process except that opponent can't choose a card already
    chosen for <this card>. Then put the last chosen card into your hand.``

    One node for the paragraph, for the reason every other paragraph node here
    is one: no sentence after the first can be read alone. "This process" is
    the first sentence, "a card already chosen" is the set the repetitions
    built, and "the last chosen card" is whichever pick the loop stopped on.

    ``cost`` is what buys another repetition, and it is the only thing that
    varies: a card printing the same loop for {1} needs no code.
    """
    chooser: PlayerRef
    cost: ManaCost


@dataclass(frozen=True)
class PutExiledCardIntoHand:
    """``Put that card into your hand.`` (Necropotence, inside its delay.)

    "That card" is the one an earlier step of the **same effect** exiled, so
    this reads the resolution's own record rather than choosing anything —
    the same back-reference "you may play cards exiled this way" makes, and
    demanded of its producer for the same reason: a sentence with nothing
    behind it is the sentence read wrong.

    The zone is fixed by the node: only a hand is printed, and a card printing
    another destination is a different sentence this production refuses.
    """
    player: PlayerRef


@dataclass(frozen=True)
class ExileBoundCard:
    """``Exile that card from your graveyard.`` (Necropotence.)

    The card the firing event named, exiled out of the zone that event put it
    in. Not an :class:`Exile` of a permanent: nothing is on the battlefield and
    nothing is chosen — "that card" is the discard the trigger watched, and the
    only place it can be read is the event's own captured context.

    ``from_zone`` is read rather than assumed, because "exile that card" with no
    zone would be a different sentence about an object that may be anywhere.
    """
    from_zone: Zone


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


@dataclass(frozen=True)
class TransmuteBySacrifice:
    """Transmute Artifact's whole effect, as one statement.

    "Sacrifice an artifact. If you do, search your library for an artifact card.
    If that card's mana value is less than or equal to the sacrificed artifact's
    mana value, put it onto the battlefield. If it's greater, you may pay {X},
    where X is the difference. If you do, put it onto the battlefield. If you
    don't, put it into its owner's graveyard. Then shuffle."

    One node for the whole paragraph, the shape Necromentia and Tawnos's Coffin
    already use, and for the same reason: the sentences are not effects that
    happen to follow one another. Every clause after the first is *about* the
    two objects the first two chose — the artifact given up and the card found —
    and the sizes of both are only knowable once each choice has been made. A
    parse producing seven statements would produce six with nothing to read.

    Both filters ride the node because both are printed nouns, and a card
    printed "sacrifice a creature … search for a creature card" is the same
    machine with different words.
    """

    sacrificed: ObjectFilter
    found: ObjectFilter


@dataclass(frozen=True)
class OwnershipExchangeUnlessPaid:
    """Bronze Tablet's whole four-sentence ability.

    "Exile this artifact and target nontoken permanent an opponent owns. That
    player may pay 10 life. If they do, put this card into its owner's
    graveyard. Otherwise, that player owns this card and you own the other
    exiled card."

    One node, in `paragraphs.py`'s family, because the sentences are one effect:
    the exile is what there is to exchange, the payment decides whether the
    exchange happens, and both branches name the two cards the first sentence
    took. CR 108.3 says ownership never changes — this is one of the handful of
    ante cards (CR 407) that is the exception, which is why the effect exists at
    all and why it is inert in a game not played for ante.

    The life and the target's noun phrase ride the node; a card printing the same
    machine with a different number or a different noun needs no code.
    """

    life: int
    target: "ObjectFilter"


@dataclass(frozen=True)
class AnteOfferOwnershipExchange:
    """Timmerian Fiends' whole four-sentence ability.

    "The owner of target <type> may ante the top card of their library. If that
    player doesn't, exchange ownership of that <type> and this permanent. Put
    the <type> card into your graveyard and this permanent from anywhere into
    that player's graveyard. This change in ownership is permanent."

    One node, in `paragraphs.py`'s family and for
    :class:`RandomRevealOwnershipExchange`'s reason: sentence two names "that
    <type>", which only sentence one chose; sentence three is *how* sentence
    two's exchange is carried out, since this engine's ownership is which
    player's zone a card sits in; and sentence four (CR 108.3's ante exception,
    CR 407) is what makes the two moves permanent rather than a loan.

    ``type_word`` is the printed card type the ability targets, and it is
    payload rather than part of the node: the same paragraph about a creature is
    the same effect, and the word has to be *the same* in all three sentences
    or the paragraph is not describing one object.
    """

    type_word: str


@dataclass(frozen=True)
class RandomRevealOwnershipExchange:
    """Tempest Efreet's whole five-sentence ability.

    "Target opponent may pay <N> life. If that player doesn't, they reveal a
    card at random from their hand. Exchange ownership of the revealed card and
    this creature. Put the revealed card into your hand and this creature from
    anywhere into that player's graveyard. This change in ownership is
    permanent."

    One node, in `paragraphs.py`'s family and for its reason: sentence three
    names "the revealed card", which only sentence two produced, and sentence
    four is *how* sentence three's exchange is carried out — this engine's
    ownership is which player's zone a card sits in, so the two moves are the
    exchange rather than a consequence of it. Sentence five says the exchange
    outlasts the game (CR 108.3's ante exception, CR 407), which is what makes
    the moves permanent instead of an until-end-of-turn loan.

    The life total is the only payload; every other word was required by the
    production that read it.
    """

    life: int

@dataclass(frozen=True)
class CastPermission:
    """A sentence whose effect is permission to cast or play from somewhere
    the rules alone would not allow (CR 601.3):

    * "Until end of turn, you may play cards exiled this way." — Chandra,
      Heart of Fire's +1: ``what="exiled_this_way"``, ``mode="play"``.
    * "You may cast them this turn." — her −9's back-reference to the cards
      the same resolution just exiled: also ``what="exiled_this_way"``.
    * "You may cast target red instant or sorcery card from your graveyard."
      — Chandra, Flame's Catalyst's −2: ``what="target_card"``, the chosen
      card on ``target``.
    * "Until end of turn, you may cast spells from your hand without paying
      their mana costs." — her −8: ``what="spells_from_hand"``, ``free=True``.

    The duration is recorded (both printed spellings, "until end of turn" and
    "this turn", are the same end-of-turn scope); ``target_card`` legitimately
    has none, which CR 611.2a reads as lasting — bounded by the card staying
    in its zone (CR 400.7).

    ``mode="look"`` is the same sentence about a different verb: "You may
    **look at** it for as long as it remains exiled" (Gustha's Scepter). It is
    a mode rather than a node of its own because the sentence is word-for-word
    this one bar the verb — subject, referent and every duration spelling are
    read by the same code — and the lowering routes the verb to its own
    instruction kind, so a look permission can never reach a cast one.
    """
    mode: str  # "play" | "cast" | "look"
    what: str  # "exiled_this_way" | "target_card" | "spells_from_hand"
    target: TargetSpec | None = None
    until_end_of_turn: bool = False
    #: "…**until you exile another card with this enchantment**" (Furious Rise).
    #: A stated duration (CR 611.2a) whose ending event is this same permanent
    #: granting again — so it is neither of the two the model had, and reading it
    #: as either is wrong in a direction: end-of-turn throws the card away at
    #: cleanup, and no-duration lets every card the enchantment ever exiled stay
    #: playable at once. The event may simply never happen (the enchantment
    #: leaves, or no end step finds a creature with power 4), and then the
    #: permission lasts, which is what the card says.
    until_source_grants_again: bool = False
    #: "**Until the beginning of your next upkeep**, you may play that card."
    #: (Elkin Bottle.) A third stated duration (CR 611.2a), and its own field
    #: rather than a wider ``until_end_of_turn`` because reading it as either of
    #: the other two is wrong in a stated direction: end-of-turn throws the
    #: exiled card away at this turn's cleanup, and no-duration leaves it
    #: playable for the rest of the game.
    until_your_next_upkeep: bool = False
    #: "You may cast that card **for as long as it remains exiled**." (Ice
    #: Cauldron.) A fourth stated duration, and its own field for the reason the
    #: third has one: reading it as any of the others is wrong in a stated
    #: direction. It ends on a *zone change* rather than at a moment in the
    #: turn — which is the one duration the permission's own membership check
    #: already enforces, so what it costs the runtime is nothing and what it
    #: costs to leave unstated is a grant that outlives the card.
    while_exiled: bool = False
    free: bool = False
    # "If that spell would be put into your graveyard, exile it instead." —
    # attached by the rider parser, so a wording carrying it cannot shed it.
    exile_instead: bool = False


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


@dataclass(frozen=True)
class NameAndStrip:
    """``Choose a card name other than a basic land card name. Search target
    opponent's graveyard, hand, and library for any number of cards with that
    name and exile them. That player shuffles, then creates a 2/2 black Zombie
    creature token for each card exiled from their hand this way.``
    (Necromentia.)

    One node for the whole three-sentence effect, because the sentences share
    one choice and one pile: "that name" is what the first sentence chose, and
    "each card exiled from their hand **this way**" counts exactly the subset
    the second sentence took from one of the three zones. Parsed apart, the
    third sentence would count a pile nobody had recorded.

    The zone list is data rather than three booleans: a card searching two of
    them is the same effect over a shorter list, and the *order* is the printed
    one because it is the order the cards are found in.
    """
    zones: tuple[str, ...]
    token_zone: str
    token_power: int
    token_toughness: int
    token_colors: tuple[str, ...]
    token_subtypes: tuple[str, ...]


@dataclass(frozen=True)
class NameAndRandomReveal:
    """``Choose a card name. Target opponent reveals X cards at random from
    their hand. Then that player discards all cards with that name revealed
    this way.`` (Nebuchadnezzar.)

    One node for the whole three-sentence effect, for the reason
    :class:`NameAndStrip` is one: the sentences share a choice and a pile.
    "That name" is what the first sentence chose, and "all cards with that name
    **revealed this way**" is a strict subset of the hand — the cards the
    random reveal happened to turn up, not every copy in it. Parsed apart, the
    third sentence would discard the whole hand's worth of that name and the
    randomness would mean nothing.

    ``count`` is an :class:`Amount` because the number is the announced X, and
    ``zone`` is read where it is printed: the same effect over a graveyard is
    the same template with one word changed.
    """

    player: PlayerRef
    count: Amount
    zone: str


@dataclass(frozen=True)
class NameThenRevealTop:
    """``Target player chooses a card name, then reveals the top card of their
    library. If that card has the chosen name, that player puts it into their
    hand. If it doesn't, the player puts it into their graveyard.``
    (Petra Sphinx.)

    One node for the whole three-sentence effect, for the reason
    :class:`NameAndStrip` is one: the sentences share a choice no board read can
    recover. "The chosen name" is what the first sentence named and "that card"
    is what it turned over — parsed apart, the last two sentences would each
    test a record nobody had written.

    The two destinations are payload rather than part of the node's meaning. A
    card printing "…puts it on the bottom of their library" otherwise is this
    same guess with one word changed, and spelling "hand" and "graveyard" into
    the lowering is what would make that card a second production.
    """
    who: PlayerRef
    match_zone: str
    miss_zone: str
    #: "…and this artifact **deals 2 damage to them**." (Vexing Arcanix.) The
    #: miss branch's second half, payload on the same node because it is a
    #: consequence of the same guess: nothing outside this paragraph knows
    #: whether the name was hit. 0 is the honest "no such rider" — CR 120.8
    #: makes a 0-damage event no event at all, so the two cannot be confused.
    miss_damage: int = 0


@dataclass(frozen=True)
class NameThenConsult:
    """``Choose a card name. Exile the top six cards of your library, then
    reveal cards from the top of your library until you reveal a card with the
    chosen name. Put that card into your hand and exile all other cards
    revealed this way.`` (Demonic Consultation.)

    One node for the whole paragraph, for the reason :class:`NameThenRevealTop`
    is one: every sentence after the first reads the name it chose, and the last
    reads the pile the third turned over. Parsed apart, three of the four would
    have nothing to look at.

    **The order is the card.** Naming before the exile is what makes this a
    gamble rather than a tutor: the six cards go without being looked at, and
    the named card may be among them. A reading that searched for the name
    first would be Demonic Tutor with extra words.

    ``exile_count`` is the only number the sentence carries, so it is the only
    field — a card printing "the top three cards" is this same paragraph.
    """
    exile_count: Amount


@dataclass(frozen=True)
class RevealUntil:
    """``…reveals cards from the top of their library until they reveal a
    creature card. That player puts that card onto the battlefield, then
    shuffles the rest into their library.`` (Transmogrify.)

    One node for the whole search, not three: the reveal, the destination and
    the shuffle are a single procedure whose steps cannot be separated — "that
    card" names what the reveal stopped on, and "the rest" names exactly the
    cards it turned over before that. Lowered apart they would need two
    back-references into a list nothing had recorded.

    *whose* is the library read: "your" or the referent of a previous step
    ("that creature's controller"). *filter* is what the reveal stops on.
    *destination* is where the found card goes, and *rest* where the others do —
    both stated, because a card that milled the rest instead of shuffling them
    back is a different card and the difference is invisible in the first two
    sentences.
    """
    whose: str
    filter: ObjectFilter
    destination: str = "battlefield"
    rest: str = "shuffle_into_library"


@dataclass(frozen=True)
class ChooseCardsInHand:
    """"choose two cards in your hand drawn this turn" (Sylvan Library).

    A *pick*, not a move: the cards stay where they are and a later sentence
    of the same effect is what does something to them ("for each of those
    cards, …"). So the node carries only what was printed — how many, what
    they have to be, and whether the phrase narrowed them by provenance.

    ``drawn_this_turn`` is that provenance and rides here rather than on the
    :class:`ObjectFilter`, because it is not a characteristic of a card at
    all: nothing on the face answers it and no reader of a card in a zone can.
    It is a fact about the *player's* turn, so it is answered where the player
    is known — see ``handlers/cards.chosen_hand_card_candidates``, the one rule
    the picker and the resolver both ask.
    """
    count: Amount
    filter: ObjectFilter
    drawn_this_turn: bool = False


@dataclass(frozen=True)
class PutIteratedCardOnLibrary:
    """"put the card on top of your library" (Sylvan Library).

    "The card" is the one the enclosing "for each of those cards" is on, which
    is why this is its own node rather than a :class:`PutOnLibraryTop` with an
    unusual target: that node moves a *permanent* off the battlefield, and this
    moves a card that has been in a hand the whole time.

    ``position`` is payload for the reason every printed word is: a card
    printing "on the bottom" is the same production.
    """
    position: str = "top"


@dataclass(frozen=True)
class PlayWithHandRevealed:
    """``<player> play with their hand revealed <duration>`` (Stromgald Spy).

    CR 701.20a's reveal made continuous. Nothing moves and the hand stays a
    hidden zone by classification (CR 400.2, which says so even when every card
    in one happens to be revealed) — the whole effect is who may see what.

    Beside :class:`RevealHand` and not a flag on it: that node is the one-shot
    action a resolution performs, this one is a continuous effect with a
    duration, and the two are answered by different halves of the engine. A
    reveal that lasted "for as long as" would have to be swept; this one is
    *derived*, from a record on the source that stops being in the scan when the
    source leaves.

    ``player`` is the printed reference, not a resolved seat: "defending player"
    is CR 506.2's, frozen by the combat fire site, and only the handler is in a
    position to read it.
    """
    player: PlayerRef
    duration: "Duration" = field(default_factory=lambda: Duration())
