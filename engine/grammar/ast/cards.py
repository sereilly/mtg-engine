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

from ._core import (
    Amount,
    Comparison,
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
class SearchLibrary:
    player: PlayerRef
    filter: ObjectFilter
    to: Zone
    # "search your library **and/or graveyard**" — a second zone the search may
    # look in, not a wording of the first. It rides on the node rather than on
    # the filter because it says where the search happens, not what it may
    # find; the filter's `named` field carries the latter.
    graveyard: bool = False
    #: "…for **up to two** basic land cards … put **one** onto the battlefield
    #: tapped **and the other** into your hand" (Cultivate). One entry per find,
    #: in the printed order, so how many are found and where each goes are the
    #: same fact. ``to`` above is the single-find spelling and stays the first
    #: entry's zone; a card printing three destinations needs no new field.
    extra_destinations: tuple[Zone, ...] = ()
    #: Whether each find enters tapped, aligned with the destinations above.
    tapped: tuple[bool, ...] = ()
    #: "Up to" — finding fewer, none included, is a legal answer (CR 701.19b's
    #: fail-to-find is always legal, but this says so on the card).
    up_to: bool = False
    #: "…, **reveal it**, …" / "…, **reveal those cards**, …" (CR 701.20). What
    #: the word buys is the public record: a search that prints it shows the
    #: found cards' faces to every player, and the engine's reveal-event feed
    #: (``Game.record_reveal``) is that showing. A search without it — Demonic
    #: Tutor's — records nothing, so the field defaults off.
    reveal: bool = False
    #: "Then if you control four or more lands, untap that land." (Fabled
    #: Passage.) A rider on *this* search rather than a second statement,
    #: because "that land" is the card this search just found — a sentence after
    #: the search would run before the player has answered its prompt, and would
    #: have nothing to refer to. The filter is what is counted; the threshold is
    #: how many are needed.
    #: "a card named Alpine Watchdog **and/or** a card named Igneous Cur"
    #: (Alpine Houndmaster). One find per printed name, each optional — the
    #: "and/or" is what says a player may take either, both or neither. Its own
    #: field rather than a filter, because the filter carries what *one* find may
    #: be and this is a list of them.
    named_alternatives: tuple[str, ...] = ()
    untap_found_if: "Comparison | None" = None
    untap_found_filter: "ObjectFilter | None" = None


@dataclass(frozen=True)
class Shuffle:
    player: PlayerRef


@dataclass(frozen=True)
class LookAtLibraryTop:
    """``Look at the top five cards of target player's library. You may then
    have that player shuffle that library.`` (Visions.)

    Distinct from ``LookTopPickToHand`` below, which is always about *your own*
    library and always takes a card out of it. This one takes nothing: the
    whole effect is the information, plus an offer to shuffle away the order
    the looker just learned. ``may_shuffle`` is on the node because the offer
    is about the library this sentence named — carried separately it would have
    to name a player again.
    """
    count: "Amount"
    player: PlayerRef
    may_shuffle: bool = False


@dataclass(frozen=True)
class LookTopPickToHand:
    """``Look at the top three cards of your library. Put one of those cards
    into your hand and the rest on the bottom of your library in any order.
    If this spell was cast from anywhere other than your hand, put each of
    those cards into your hand instead.`` (See the Truth.)

    One node for the whole three-sentence template — the sentences share one
    set of looked-at cards, so parsed apart two of them dangle. The cast-zone
    conditional is part of the shape, not a separate statement: it reads the
    resolution context's ``cast_from_zone``, the field the stack object
    carries since the permission-seam round.

    Garruk's Harbinger prints the same shape with three differences, and each is
    a field rather than a second node because each is a *parameter* of the same
    procedure: the count is a back-reference ("that many"), the pick is optional
    and filtered ("you **may** reveal a creature card or Garruk planeswalker
    card"), and the rest go down **in a random order** rather than in any order.
    The last is a real distinction — "any order" leaves them as they lay because
    the ordering is the player's by rule, where "a random order" is a stated
    shuffle nobody may choose.
    """
    count: Amount
    #: What the taken card must be, as filter payload alternatives OR'd
    #: together. Empty means the See the Truth shape, where any of the looked-at
    #: cards may be taken.
    filters: tuple[dict, ...] = ()
    #: "You **may** reveal …" — declining is a legal answer, and not the same as
    #: an illegal one: the rest still go to the bottom.
    optional: bool = False
    #: "in a random order" vs "in any order".
    rest_order: str = "any"
    #: Where the cards *not* taken go. "Put one of them into your hand and **the
    #: other into your graveyard**" (Waker of Waves) is a different card from
    #: one that bottoms them, and the difference is invisible until the pile is
    #: looked at again — so the destination is stated rather than defaulted.
    rest_destination: str = "library_bottom"
    #: See the Truth's third sentence, which is its whole reason to exist. A
    #: wording without it is a different card, so the two shapes cannot be
    #: allowed to collapse into one another.
    all_to_hand_if_cast_elsewhere: bool = False


@dataclass(frozen=True)
class RevealHandAndChoose:
    """``Target opponent reveals their hand. You choose a <filter> card from
    it. That player discards that card.`` (Duress.)

    Three printed sentences, one node — for the same reason See the Truth's
    three are one: they share the revealed hand, and parsed apart the middle
    sentence would be a choice over a zone nobody revealed and the last one a
    discard of a card nobody chose.

    *fate* is what happens to the chosen card, because that is the only thing
    the family varies (Kitesail Freebooter exiles it instead of discarding it),
    and it decides which handler ending runs.
    """
    player: PlayerRef
    filter: ObjectFilter
    fate: str = "discard"


@dataclass(frozen=True)
class RevealHand:
    """``<player> reveals their hand.`` (Inquisition.)

    The reveal on its own (CR 701.20), with nothing chosen from it. Its own node
    rather than a `RevealHandAndChoose` with an empty choice: that one is one
    node *because* the three printed sentences share a card nothing else could
    carry, and an "empty" choice there would be a picker armed over nothing. The
    sentence after this one on Inquisition reads the hand's *size*, which the
    reveal makes public and which no chosen card is involved in.
    """
    player: PlayerRef


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
    """
    player: PlayerRef


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
    """
    zone: Zone


@dataclass(frozen=True)
class SearchAndExile:
    """``Search your graveyard and library for any number of <filter> cards,
    exile them, then shuffle.`` (Chandra, Heart of Fire's −9.)

    Not a :class:`SearchLibrary`: that node's whole contract is *one* found
    card put into the hand, and this one exiles any number. The zones are
    fixed by the words read — both are expected, so a wording searching one
    zone refuses rather than silently searching fewer places than printed.
    """
    filter: ObjectFilter


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
    """
    mode: str  # "play" | "cast"
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
class RevealTop:
    """``Reveal the top card of your library.`` (Track Down.)

    The reveal alone. CR 701.20a makes revealing a card show it to all players
    and move it nowhere, so what this does to the game is *record what is
    there* — and the sentences after it read that record rather than the
    library, because by then a draw may have taken the card.

    Its own node beside :class:`RevealTopToHandOrBottom` rather than that one
    generalised. That template is one node for three sentences on purpose: its
    two destinations are the effect, and every word of them is required. This is
    the opposite decomposition — a reveal that records, and whatever ordinary
    conditional follows it — so folding them together would make the Garruk
    template's own docstring untrue of half its cases.
    """


@dataclass(frozen=True)
class RevealTopToHandOrBottom:
    """"Reveal the top card of your library. If it's a <filter>, put it into
    your hand. Otherwise, put it on the bottom of your library." (Garruk,
    Savage Herald.) One node for the whole three-sentence template: the
    sentences reference one revealed card, so parsing them separately would
    leave two of them meaning nothing on their own."""
    filter: ObjectFilter


@dataclass(frozen=True)
class LookAtHand:
    """"Look at target player's hand." (Glasses of Urza, CR 402.3.)

    An information effect: nothing about the game state changes, so it is a
    leaf of its own rather than a flavour of ``ReturnToZone``. The player is
    modeled rather than assumed, because *whose* hand is looked at is the whole
    content of the clause.
    """
    player: PlayerRef


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
