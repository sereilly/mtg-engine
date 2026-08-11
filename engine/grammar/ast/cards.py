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
    any_color: int = 0
    # The clause verbatim. The current mana handler re-reads the text rather
    # than taking structured pips, so lowering passes it through unchanged;
    # this field goes away when the handler takes ``pips`` directly.
    source_text: str = ""


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


@dataclass(frozen=True)
class Shuffle:
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
    free: bool = False
    # "If that spell would be put into your graveyard, exile it instead." —
    # attached by the rider parser, so a wording carrying it cannot shed it.
    exile_instead: bool = False


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
