"""What a spell or an ability *costs* — CR 601.2b for a spell, CR 602.2b for an
ability.

Split out of `_core` at the thousand-line guard, the round an exile cost that
names a chosen object landed (City of Shadows, Necropolis). A family along a
line the CR already draws rather than an arbitrary cut: everything here is read
by `grammar/costs.py` on the way *to* the stack and is gone by the time
anything is lowered, where the rest of `_core` is the vocabulary an *effect* is
built from. Nothing in `_core` refers to a cost, which is what made the cut
free.

Beside `_core` rather than under it: `statements.py` names the `Cost` union in
`ActivatedAbilityNode`, and a cost is not one of the effect families — it has
no `effects/` or `lowering/` twin at all, because a cost is charged rather than
lowered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from ._core import Amount, Fixed, ObjectFilter


@dataclass(frozen=True)
class ManaCost:
    """Mana pips, in the same shape ``ActivatedAbilityCost.mana`` uses."""
    pips: tuple[tuple[str, int], ...] = ()   # (("generic", 2), ("R", 1))


@dataclass(frozen=True)
class TapSelf:
    pass


@dataclass(frozen=True)
class SacrificeCost:
    filter: ObjectFilter = field(default_factory=ObjectFilter)
    # "Sacrifice this artifact **and any number of creatures you control**"
    # (Sword of the Ages). How many the phrase names: one by default, and
    # :class:`AnyNumber` when the payer chooses the size of the set. Carried
    # rather than assumed, because the two are charged differently — a fixed
    # count can make the ability unpayable and "any number" never can, since
    # zero is a number (CR 601.2h).
    count: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class DiscardCost:
    count: Amount = field(default_factory=lambda: Fixed(1))
    # "Discard **the last card you drew this turn**" (Jandor's Ring). Not a
    # count: the card is named by history, so its payer has no choice at all,
    # and the engine tracks it on a dedicated flag
    # (``ActivatedAbilityCost.discard_last_drawn``). Folding it into ``count=1``
    # would say "discard any one card" — a strictly cheaper cost.
    last_drawn: bool = False
    # "Discard **a land card or Shrine card**" (Sanctum of Shattered Heights) —
    # the alternatives the payer may choose between, as printed. A tuple rather
    # than one filter because the "or" is a union across two *different*
    # characteristics (a card type and a subtype), which no single ObjectFilter
    # can say: its fields are AND'd, so "land" and "shrine" together would name
    # a card that is both. Empty is the unrestricted "Discard a card".
    filters: tuple[ObjectFilter, ...] = ()
    # "Discard a card **at random**" (Coral Helm). Not a narrowing of which
    # cards may pay — every card in hand may — but a removal of the *choice*:
    # the payer names nothing, and a cost the payer picks is a strictly better
    # cost than one chance picks. Its own flag rather than an empty filter list
    # for exactly that reason; the two shapes look identical and are not.
    at_random: bool = False
    #: "Discard **your hand**" (Subira, Tulzidi Caravanner). Every card, so
    #: there is nothing for the payer to choose and nothing for a filter to
    #: narrow — a different cost from "discard a card", not a count of it, which
    #: is why it is a flag rather than a very large ``count``. CR 601.2h still
    #: makes it payable with an empty hand: discarding nothing is discarding
    #: your hand.
    whole_hand: bool = False
    #: "Discard **this card**" (Waker of Waves) — the card the ability is
    #: printed on, discarded from the hand to pay. Distinct from a narrowed
    #: "discard a card" because nothing is chosen, and from ``whole_hand``
    #: because it is exactly one card and a specific one.
    self_card: bool = False


@dataclass(frozen=True)
class PutCounterCost:
    """"Put a **page** counter on this artifact" as part of an activation cost
    (Mazemind Tome).

    A cost that *adds* something rather than spending it, which is why it is its
    own node and not a negative counter removal: it can never be unpayable, and
    the thing it adds has no rules meaning of its own (CR 122.1) — only the
    card's own state trigger reads it.
    """
    kind: str


@dataclass(frozen=True)
class TapPermanentsCost:
    """"Tap two untapped Spirits you control" (Shacklegeist).

    N *other* permanents, named by a printed noun phrase — not the {T} symbol,
    which taps the source and is :attr:`ActivatedAbilityCost.requires_tap`. The
    count is printed, so it is data rather than part of the cost's identity.
    """
    count: int
    filter: ObjectFilter


@dataclass(frozen=True)
class TapAttachedCost:
    """"Tap enchanted land" (Earthlore).

    The permanent this Aura or Equipment is *attached to*, which neither of its
    two neighbours can say: `TapSelf` is the `{T}` symbol and taps the
    permanent the ability is printed on, and `TapPermanentsCost` names a class
    the payer picks from. Here nothing is picked — the attachment record is the
    whole answer — so the node carries no filter and no count.

    CR 301.5f puts "equipped" and "enchanted" on the same footing, so the word
    is not carried either: what is tapped is the host, whichever noun the card
    printed.
    """


@dataclass(frozen=True)
class PayLifeCost:
    """``Pay 4 life`` in front of a colon — an activation cost (CR 119.4).

    Named for its siblings ``SacrificeCost``, ``DiscardCost`` and
    ``RemoveCounterCost`` rather than for the words it reads. It used to be
    the bare ``PayLife``, which is also what the *effect* "pay 4 life" reads
    to (``ast/game.py``) — one name for a cost and for a statement, in an AST
    whose two unions are told apart by type.
    """

    amount: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class ExileSelf:
    pass


@dataclass(frozen=True)
class ExileCost:
    """"Exile **a creature you control**" (City of Shadows) / "Exile **a
    creature card from your graveyard**" (Necropolis) — a cost that exiles
    something the payer chooses, rather than the ability's own source.

    Beside :class:`ExileSelf` rather than a filter on it, for the reason
    :class:`SacrificeCost` is not a flag on ``sacrifice_self``: the source
    needs no picker, no payability check and no record of what it ate, and a
    chosen object needs all three.

    The zone the object comes from rides the *filter* (``zone`` /
    ``zone_owner``), the way every other noun phrase in this grammar carries it
    — a card in a graveyard and a permanent on the battlefield are the same
    printed phrase with a different tail, and two nodes would be two readers of
    one sentence.

    **A cost is not a target** (CR 601.2b vs 601.2c, idiom 10): nothing here is
    announced as a target, so shroud, protection and hexproof have nothing to
    say about what may pay.
    """
    filter: ObjectFilter


@dataclass(frozen=True)
class RemoveCounterCost:
    counter: str = "+1/+1"
    count: Amount = field(default_factory=lambda: Fixed(1))


Cost = Union[
    ManaCost, TapSelf, SacrificeCost, DiscardCost, PayLifeCost, ExileSelf,
    ExileCost, RemoveCounterCost
]
