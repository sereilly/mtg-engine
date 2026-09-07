"""What a hidden zone's contents *are*: search, look-at, reveal-top.

The AST half of the ``library`` family the parse and lowering sides have
carried since The Dark, and the last of the three to split. It was left out on
purpose - `tests/engine/test_grammar_layering.py` recorded the reason, that a
near-empty ``ast/library.py`` would buy back the symmetry and cost the thing
symmetry is for. That reason expired the day the size guard fired on
``ast/cards.py`` itself, which is what this file is.

The line is ``effects/library.py``'s own, word for word: everything here names
a **pile being looked through**, and drawing, discarding, milling, scrying and
the hand reveals stay in ``cards.py`` because they name a *card moving*. So the
two modules keep the same seam on both sides, and a template has one home per
side rather than two candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import (
    Amount,
    Fixed,
    ObjectFilter,
    PlayerRef,
    Zone,
)


@dataclass(frozen=True)
class SearchPlayerLibrary:
    """``Search target player's library for three cards and exile them. Then
    that player shuffles.`` (Jester's Cap.)

    ``Search that player's library for that many cards. That player puts those
    cards into their hand, then shuffles.`` (Jester's Mask.)

    A different effect from :class:`SearchLibrary`, which that node's own
    production has said since it was written: "the engine's search flow only
    ever opens the searcher's own library, so 'search target player's
    library' is a different card, not a wording of this one". Two seats are
    involved rather than one — CR 608.2c makes the ability's controller the
    chooser and the library is somebody else's — and both have to reach the
    flow, which is what this node carries and :class:`SearchLibrary` has no
    field for.

    ``count`` is an amount rather than a number because Jester's Mask prints
    "for **that many** cards", the quantity being the size of a hand the step
    in front of it emptied. ``to`` is where every find goes: the pool's two
    printings send them all to one place, so there is one zone rather than the
    per-find list Cultivate needs.
    """
    player: PlayerRef
    count: Amount
    filter: ObjectFilter
    to: Zone

@dataclass(frozen=True)
class SeparateLibraryTopIntoPiles:
    """Phyrexian Portal's whole three-sentence procedure.

    "Target opponent looks at the top ten cards of your library and separates
    them into two face-down piles. Exile one of those piles. Search the other
    pile for a card, put it into your hand, then shuffle the rest of that pile
    into your library."

    One node over all three sentences, the shape :class:`LookTopCycleForLife`
    beside it takes: "those piles" and "the other pile" name what the first
    sentence made, and a production that read only its own sentence would leave
    two referents nothing binds.

    Three decisions by two seats, and *which* seat makes each is the whole
    design of the card - the opponent divides, knowing what is in the piles,
    and you choose and search, not knowing. So the splitter is a field, and it
    is the only reference here that could be anybody else: the library, the
    hand the found card reaches and the exile are all the ability's controller's.

    The piles are face down (CR 406.3), which is what makes the second decision
    a real one rather than a formality.
    """
    count: Amount
    splitter: PlayerRef


@dataclass(frozen=True)
class LookTopCycleForLife:
    """Lim-Dul's Vault's whole three-sentence effect.

    "Look at the top five cards of your library. As many times as you choose,
    you may pay 1 life, put those cards on the bottom of your library in any
    order, then look at the top five cards of your library. Then shuffle and
    put the last cards you looked at this way on top in any order."

    One node for all three sentences, the shape :class:`ExileUntilLeavesOrUntaps`
    already takes for Tawnos's Coffin: they describe one procedure and each of
    them dangles a referent the others bind. "Those cards" is what the sentence
    in front looked at, "the last cards you looked at this way" is whichever
    iteration was the last, and neither can be read by a production that only
    saw its own sentence.

    Both numbers are fields because both are printed, and a card cycling three
    cards for 2 life is this sentence rather than a second production. What is
    *not* a field is where the unwanted cards go or where the kept ones end up:
    the bottom and the top are the whole shape of the effect, and a wording that
    sorted them elsewhere would be a different card wearing this one's head.

    The shuffle is part of it and not a rider. The kept cards go on top **after**
    the library is shuffled (CR 701.24), which is the entire reason the card is
    a tutor rather than a look: shuffling first and then stacking is what makes
    the five known cards the next five draws.
    """
    count: Amount
    life_cost: Amount

@dataclass(frozen=True)
class BinRevealedCard:
    """``Put it into <player>'s graveyard.`` (Wand of Denial.)

    "It" is the card an earlier step of this same effect turned up — the look
    at that player's library, whose whole point is that the looker now knows
    what the card is. Its own node rather than a reading of
    :class:`PutSourceIntoZone` beside it, which moves the *ability's source*: a
    node that meant either would be resolved from whichever half of the
    resolution context happened to hold something.

    The player is carried because the card goes to **its owner's** graveyard
    (CR 400.3) and the owner is the player whose library it came out of, which
    is not the seat that looked.
    """
    player: PlayerRef


@dataclass(frozen=True)
class GraveyardTopToLibrary:
    """``If the top card of <player>'s graveyard is a <filter>, put that card on
    top of that player's library.`` (Guiding Spirit.)

    **The printed "if" is part of the effect, not a condition over it**, and
    that is why this is one node rather than a condition plus an arm. Both
    halves name the same object — the top card of one graveyard — and neither
    can name it on its own: a condition node would ask about a card the arm
    would then have to find again, and "put that card on top" as a free-standing
    statement is a back-reference to whatever sentence happened to precede it.
    One node reads the whole sentence, so the two halves cannot disagree about
    which card they mean.

    Nothing is moved when the top card does not match, which is the card doing
    exactly what it says rather than a failure — and it is why the filter rides
    the node: a card naming a different type is this sentence with a different
    word in it.
    """
    player: PlayerRef
    filter: ObjectFilter


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
    #: "Up to" — finding fewer, none included, is a legal answer (CR 701.23b's
    #: fail-to-find is always legal, but this says so on the card).
    up_to: bool = False
    #: "…for **any number of** Goblin cards" (Goblin Recruiter). An "up to"
    #: with no printed ceiling, so ``extra_destinations`` and ``tapped`` cannot
    #: be sized here at all — the ceiling is the zone, and only the resolution
    #: knows how many cards the library holds. Its own flag rather than a
    #: sentinel in ``extra_destinations``: how many finds there are and where
    #: each goes are the same fact everywhere else on this node, and this is
    #: the one shape where the first half is not known until the effect runs.
    unbounded: bool = False
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
    #: "Search your library and graveyard for five cards **and exile the
    #: rest**." (Doomsday.) What happens to the cards the search did *not*
    #: find, which is nothing at all for every other printing \u2014 CR 701.23a
    #: looks through the zone and leaves it as it was. Its own field rather
    #: than a destination, because it is about the pile and not about a find:
    #: the searched zones are emptied, and both of them, which is why the
    #: search that prints it also prints no shuffle.
    exile_rest: bool = False

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
    #: "…, **then put them back in any order**" (Natural Selection, Portent).
    #: The looker rearranges what they saw, which is a different effect from
    #: merely learning it — and a *different handler*, so it is a field rather
    #: than an assumption: Visions looks and never reorders, and reading the two
    #: as one would hand Visions' controller a rearrangement the card does not
    #: give them.
    may_reorder: bool = False
    #: "**You may put that card on the bottom of that player's library.**"
    #: (Coral Fighters.) The third offer the template prints, and a third
    #: handler for the two above's reason: looking, rearranging and bottoming
    #: are three different things to be allowed to do with what you saw, and a
    #: card that only looks must never be handed one of the others.
    may_bottom: bool = False

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
    #: See the Truth's third sentence, which is a rider on this template rather
    #: than part of it: Diabolic Vision prints the pick and stops. Optional in
    #: the production for that reason, and carried here so a card that *does*
    #: print it cannot collapse into one that does not.
    all_to_hand_if_cast_elsewhere: bool = False
    #: Where the *taken* card goes. "Puts one of them **back on top of their
    #: library**" (Ashnod's Cylix) is this template with one word changed and a
    #: wholly different card behind it: nothing is drawn, and what the looker
    #: keeps is the card they draw next. A field for ``rest_destination``'s
    #: reason — the sentence states it, and a default would be a guess about
    #: the one thing the card is for.
    pick_destination: str = "hand"
    #: How many of the looked-at cards are taken. "Put **two** of them into
    #: your hand and the rest into your graveyard" (Ancestral Memories) is the
    #: only printed number other than one so far, and it is a field for
    #: ``rest_destination``'s reason: the sentence states it, and a card taking
    #: one where it prints two is a strictly smaller card with nothing to
    #: notice the difference.
    pick_count: Amount = field(default_factory=lambda: Fixed(1))
    #: **Whose library**, when that is not the looker's own. "Look at the top X
    #: cards of **target opponent's** library. Exile one of those cards…"
    #: (Sealed Fate): the pile is the opponent's and every decision about it is
    #: the spell's controller's. Its own field beside ``looker`` rather than a
    #: widening of it, because that one answers two questions at once — Ashnod's
    #: Cylix says "target player looks at the top three cards of **their**
    #: library", one seat by construction — and a card that separates them is
    #: separating exactly what that field fuses.
    pile_owner: "PlayerRef | None" = None
    #: Who looks. None is the effect's own controller, which every card in this
    #: family printed until Ashnod's Cylix — "**Target player** looks at the
    #: top three cards of **their** library". The looker and the library are
    #: one seat by construction here (the possessive says "their"), so one
    #: field answers both; a card that split them would be a different node.
    looker: "PlayerRef | None" = None

@dataclass(frozen=True)
class RevealTopOpponentChooses:
    """``Reveal the top three cards of your library. Target opponent chooses one
    of those cards. Put that card into your graveyard, then draw two cards.``
    (Thran Tome.)

    One node for the whole three-sentence template, for
    :class:`LookTopPickToHand`'s reason: the sentences describe **one** revealed
    pile, and parsed apart the second and third dangle a referent nothing binds.

    The chooser is not the ability's controller, which is what separates this
    from every look-and-pick in the family: CR 701.20 shows the cards to
    everybody, and the sentence then hands the decision to a player it targets.
    So the reveal, the choice and what becomes of the chosen card are one step —
    the arrangement ``RevealHandAndChoose`` already records one zone over ("the
    reveal is what makes the choice legal, and the discard is what the choice
    was for, so splitting them would put a chosen card between two instructions
    with nothing carrying it").

    ``then_draw`` is the sentence *behind* that step and lowers to its own
    instruction: a draw is an ordinary effect, and the only thing tying it to
    the pick is that it happens after (CR 608.2). Carried on the node because
    the production has to consume the words, not because the step is fused.
    """
    count: Amount
    #: Who chooses. Only a targeted opponent has a printing; the lowering
    #: refuses anything else rather than defaulting to a seat, because a choice
    #: made by the wrong player is the whole card.
    chooser: "PlayerRef"
    #: Where the chosen card goes. Payload for ``rest_destination``'s reason:
    #: the sentence states it, and a default would be a guess about the one
    #: thing the card is for.
    fate: str = "graveyard"
    #: "…, then draw two cards." None for a printing that draws nothing.
    then_draw: "Amount | None" = None


@dataclass(frozen=True)
class StripCardsWithChosenName:
    """``Search that player's graveyard, hand, and library for all cards with
    the same name as the chosen card and exile them. Then that player
    shuffles.`` (Lobotomy.)

    A search whose description is a **record** rather than a printed word: the
    name comes from the sentence in front of it, which is why this is a node of
    its own and not a filter on the ordinary search. ``ObjectFilter.named``
    holds a literal, and a literal is exactly what a card that names nothing
    cannot supply.

    Both sentences, because CR 701.24 ends a library search with the shuffle
    and the shuffle names the same seat this one opened — split off, the second
    is a statement no production implements and the whole line refuses.

    Necromentia prints the same two sentences behind a *named* card
    (``NameAndStrip``), fused there with a Zombie clause that counts what one of
    these zones gave up. This is the decomposed half of the same idea, and the
    two stay apart deliberately: that card's last sentence reads a pile only its
    own handler holds.
    """
    #: Whose zones are opened. Read as a reference and checked by the lowering:
    #: a search of the wrong player's library is a strictly different card and
    #: silently so.
    player: "PlayerRef"
    #: Which zones, in the printed order. Data, not part of the kind — a card
    #: printing two of the three is the same effect over a smaller reach.
    zones: tuple[str, ...]


@dataclass(frozen=True)
class SearchRevealOpponentChooses:
    """``Search your library for three cards and reveal them. Target opponent
    chooses one. Put that card into your hand and the rest into your graveyard.
    Then shuffle.`` (Intuition.)

    All four sentences, for :class:`RevealTopOpponentChooses`' reason: they
    describe **one** pile, and "one", "that card" and "the rest" have nothing to
    name without it. What differs from that node is only where the pile comes
    from — a search of a hidden zone rather than the top of one — which is why
    it is a node of its own rather than a field on that one: a search finds a
    number of cards a *player* picks (CR 701.23a), and a reveal off the top
    finds whatever is there.

    Its lowering is deliberately **two** instructions and not one. The pile is
    handed from the search to the pick through the resolution's scratchpad, and
    both halves already exist: the search is the standing library search with
    its finds *held* rather than placed (Transmute Artifact's word for the same
    thing), and the pick is the standing ``opponent_picks_revealed`` prompt,
    which has taken a chosen card's fate and the rest's since Phyrexian
    Grimoire. Fusing them would be a third handler that re-implemented both.

    ``count`` is a **floor** and not a ceiling: CR 701.23d makes a search for
    a bare quantity find that many, or as many as possible. Every counted
    search in the pool before this one printed "up to" or "any number of", so
    the distinction had never had a card to be wrong about.
    """
    count: Amount
    #: Who chooses. Only a targeted opponent has a printing; the lowering
    #: refuses anything else rather than defaulting to a seat, for
    #: :class:`RevealTopOpponentChooses`' reason — a choice made by the wrong
    #: player is the whole card.
    chooser: "PlayerRef"
    #: Where the chosen card goes, and where the rest go. Both read from the
    #: print and checked against closed lists, because they are opposite fates
    #: and a card that swapped them would be a different spell entirely.
    fate: str = "hand"
    other_fate: str = "graveyard"


@dataclass(frozen=True)
class LookTopExileRandom:
    """``Look at the top eight cards of your library. Exile four of them at
    random, then put the rest on top of your library in any order.`` (Orcish
    Librarian.)

    Its own node rather than a mode of :class:`LookTopPickToHand`, because
    nothing is *picked*: no card reaches a hand and no player chooses which
    cards go. What the two share is their tail — the rest going back on top in
    an order the player chooses — and that is shared where it is carried out,
    not by fusing the two statements that reach it.

    The exile is at random, so it is the effect rather than a decision, and it
    draws on the module RNG ``run_ai_simulation`` seeds: a given seed replays a
    given game exactly, which is the property the AI regression tests rest on.
    """
    count: Amount
    #: How many of the looked-at cards are exiled.
    exile_count: Amount
    #: Where the rest go. Only the top today — a card that bottomed them would
    #: be giving up the sorting this card is played for.
    rest_destination: str = "library_top"

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

    ``player`` is **whose** library is looked at. "Reveal the top card of
    **target opponent's** library" (Prophecy) is this same effect over another
    seat's deck, and which deck is opened is the one thing about it that cannot
    be inferred: an unstated seat reads as the caster's, so a card that named
    somebody else would reveal the wrong library and record the wrong card for
    every sentence behind it. Defaulted to "you", so every reveal written
    before this keeps a byte-identical node.
    """

    player: PlayerRef = PlayerRef("you")

@dataclass(frozen=True)
class GraveyardTopOpponentChooses:
    """``Target opponent chooses one of the top two cards of your graveyard.
    Exile that card and put the other one into your hand.`` (Phyrexian
    Grimoire.)

    Both sentences, for :class:`RevealTopOpponentChooses`' reason: they
    describe one pile, and "that card" and "the other one" have nothing to name
    without it.

    Beside that node rather than a ``zone`` field on it, and the difference is
    CR 400.2. A library is hidden, so its version has to *reveal* the pile
    before anybody can choose from it and the reveal is half of what it
    performs; a graveyard is public, so this one shows nobody anything and
    simply names cards by position (CR 404.2). Folding them would make one
    node's docstring untrue of half its cases.

    ``chosen_fate`` and ``other_fate`` are both stated because the card states
    both and they go different ways — a printing that binned the other card
    instead is the same procedure and a very different card.
    """

    count: Amount
    chooser: PlayerRef
    chosen_fate: str = "exile"
    other_fate: str = "hand"


@dataclass(frozen=True)
class PutLibraryTopIntoHand:
    """``Put that many cards from the top of your library into your hand.``
    (Scroll Rack.)

    **Not a draw**, and that is the whole reason it is a node. CR 121.1 defines
    drawing as putting the top card of a library into a hand, but an effect
    that *says* those words rather than the word "draw" is not a draw: no draw
    trigger sees it and no draw replacement applies to it (CR 121.3). Lowered
    onto ``Draw`` this card would ring every "whenever you draw a card" on the
    board and be stopped by every draw replacement, which is a different card.

    ``count`` carries the printed quantity, which on the one card that prints
    this sentence is a back-reference to the exile in front of it — "that
    many" — rather than a number.
    """

    count: Amount


@dataclass(frozen=True)
class RevealTopSortingByChosenName:
    """``Reveal the top four cards of your library and put all of them with
    that name into your hand. Put the rest into your graveyard.`` (Wood Sage.)

    Both sentences, for :class:`RevealTopOpponentChooses`' reason: they
    describe one revealed pile, and "the rest" names exactly what the first
    sentence did *not* take. Parsed apart the second would be a move out of a
    pile nothing had recorded.

    "That name" is the one a **previous step of the same effect** chose
    (``ChooseCardName``), not a name this sentence carries — which is why the
    node has no name field and the lowering demands the producer instead. A
    reader that defaulted the name to the empty string would sort the whole
    pile into the graveyard while the card compiled supported.

    Both destinations are stated. A printing that put the rest on the bottom of
    the library is the same procedure and a very different card, and nothing
    before that word shows the difference.
    """

    count: Amount
    match_zone: str = "hand"
    rest_zone: str = "graveyard"


@dataclass(frozen=True)
class RevealTopSortingByFilter:
    """``Reveal the top four cards of your library. Put all land cards revealed
    this way into your hand and the rest into your graveyard.`` (Mulch.)

    :class:`RevealTopSortingByChosenName` with the predicate printed on the
    card. Both sentences for that node's reason — one pile, and "the rest"
    names exactly what the first half did not take — and its two destinations
    for the same one.

    The difference from its sibling is what "matches" means, and it is the
    whole difference: this sentence carries its own test, so there is no
    earlier step to demand and no record whose absence could silently sort the
    pile the wrong way. ``filter`` is that test, in the ordinary object-filter
    vocabulary, so a card printing "all creature cards" is this production
    unchanged.
    """

    count: Amount
    filter: ObjectFilter
    match_zone: str = "hand"
    rest_zone: str = "graveyard"


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
    #: "Look at **a card at random** in target player's hand." (Urza's Bauble.)
    #: How much of the hand is seen, which is the other half of the clause's
    #: content: one card chosen by nobody, rather than all of them. A flag and
    #: not a count because "at random" is what makes it uncountable — a card
    #: printing "two cards at random" would need the number, and would refuse
    #: here until it had it.
    random_card: bool = False

# Two nodes that arrived from ``cards`` when Tempest's second wave took that
# module past the size guard, and both belong here by this module's own printed
# criterion: each names **a pile being looked through**.
#
# ``RevealUntil`` had been in ``cards`` since Transmogrify landed, one file away
# from every other reveal-off-the-top node — a misfiling nothing could see until
# somebody had to move something.

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
class PutExiledPileOnLibrary:
    """``Then look at the exiled cards and put them on top of your library in
    any order.`` (Scroll Rack.)

    The linked pile (CR 610.3) going back to the top of the library, in an
    order its controller chooses. One node for both printed clauses because the
    look is *why* the order is a choice: CR 406.3 makes the pile face down and
    hidden from every player, so the seat arranging it has to be shown it
    first, and a card that put the pile back without the look would be
    arranging cards nobody may see.

    ``position`` is payload for the reason it is everywhere else: a card
    printing "on the bottom" is the same production.
    """

    position: str = "top"
