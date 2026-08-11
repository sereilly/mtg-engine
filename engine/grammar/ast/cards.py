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


@dataclass(frozen=True)
class Shuffle:
    player: PlayerRef


@dataclass(frozen=True)
class LookAtHand:
    """"Look at target player's hand." (Glasses of Urza, CR 701.16.)

    An information effect: nothing about the game state changes, so it is a
    leaf of its own rather than a flavour of ``ReturnToZone``. The player is
    modeled rather than assumed, because *whose* hand is looked at is the whole
    content of the clause.
    """
    player: PlayerRef
