"""Cards moving, and mana: draw, discard, mill, search, shuffle, add.

Draw, discard and mill share a shape — a player and a count — and are separate
nodes anyway, because the zones a card moves between are what each of them
means.

The two mana nodes are separate for a sharper version of the same reason:
`AddMana` writes out a quantity for the ability's own controller, while
`AddManaForTappedLand` names referents only the enclosing trigger can bind.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import (
    Amount,
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
class AddMana:
    pips: tuple[tuple[str, int], ...] = ()
    # "Add **X** mana of any one color" (Sanctum of Fruitful Harvest) — how many,
    # as an :class:`Amount`, because the number can be a board count and not just
    # a printed digit. Zero is "this clause names no any-colour mana".
    any_color: "Amount | int" = 0
    # The clause verbatim. The current mana handler re-reads the text rather
    # than taking structured pips, so lowering passes it through unchanged;
    # this field goes away when the handler takes ``pips`` directly.
    source_text: str = ""
    # "Spend this mana only to cast an instant or sorcery spell." (Vodalian
    # Arcanist.) The restriction *key* from `engine/restricted_mana.py`, not the
    # phrase: which spells it admits is that module's question, asked again by
    # the payer, so one rule answers "what may this pay for?" in both places.
    spend_only: str | None = None
    # "Add {G} **for each creature with power 4 or greater you control**"
    # (Leafkin Avenger). A board count multiplying the whole clause, the same
    # shape a life gain and a counter placement already carry — so it is a
    # filter here rather than a number, and the count is taken at resolution.
    per_each: object | None = None


@dataclass(frozen=True)
class AddManaForTappedLand:
    """"…**that player** adds one mana of any type that land produced" (Mana
    Flare) / "…**its controller** adds an additional {R}" (Gauntlet of Might).

    Separate from :class:`AddMana`, which always adds a written-out quantity to
    the ability's own controller. Every part of this clause is a referent the
    *trigger* binds and the statement grammar cannot see on its own: who "that
    player" / "its controller" is, and which mana "that land produced". Lowering
    therefore refuses unless the enclosing trigger is ``land_tapped_for_mana``,
    the one event that binds them.

    ``additional`` records the word "additional". It is redundant on the board —
    the trigger fires after the land's own mana is already in the pool — but a
    word a production consumes without recording is a word the deletion probe
    can delete without changing the parse, which is the dropped-rider bug class.
    """

    recipient: PlayerRef
    # Written-out symbols: (("R", 1),).
    pips: tuple[tuple[str, int], ...] = ()
    # "one mana of any type that land produced" — a count of mana whose type is
    # whatever the tapped land just made, so it cannot be written as pips.
    of_type_produced: int = 0
    additional: bool = False


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


@dataclass(frozen=True)
class Shuffle:
    player: PlayerRef


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
    different destination."""
    count: Amount


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

    The reveal alone. CR 701.15 makes revealing a card show it to all players
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
    """"Look at target player's hand." (Glasses of Urza, CR 701.16.)

    An information effect: nothing about the game state changes, so it is a
    leaf of its own rather than a flavour of ``ReturnToZone``. The player is
    modeled rather than assumed, because *whose* hand is looked at is the whole
    content of the clause.
    """
    player: PlayerRef
