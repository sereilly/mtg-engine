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

    *subject* is what the counter goes on when the card names something other
    than the source: "Put a **-1/-1** counter on **a creature you control**"
    (Wandering Mage). ``None`` is the source, which is what every printing
    before it meant and what the field's absence has to keep meaning.

    That spelling breaks the "never unpayable" reading above and deliberately
    keeps the node: CR 601.2h makes an activation whose cost cannot be paid no
    activation at all, and a payer controlling no creature can put the counter
    nowhere. So the *shape* is one cost and the payability is the subject's
    business — a second node would be a second place for the counter's kind to
    be read, and the kind is the only thing the two spellings share.
    """
    kind: str
    subject: "ObjectFilter | None" = None


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
class PayAttachedManaCost:
    """"Pay enchanted creature's mana cost" (Merseine).

    :class:`TapAttachedCost`'s sibling one payment over, and its own node for
    that node's reason: what is spent is read off the *host*, and no symbol can
    say it. A mana cost printed in symbols is fixed at compile time; this one is
    whatever the enchanted permanent's printed cost happens to be right now
    (CR 202.1), so the number does not exist until the ability is activated.

    Nothing is picked and no filter is carried — the attachment record is the
    whole answer, exactly as it is for the tap. CR 301.5f puts "equipped" and
    "enchanted" on the same footing, so the word is not carried either.
    """


@dataclass(frozen=True)
class PayLifeCost:
    """``Pay 4 life`` in front of a colon — an activation cost (CR 119.4).

    Named for its siblings ``SacrificeCost``, ``DiscardCost`` and
    ``RemoveCounterCost`` rather than for the words it reads. It used to be
    the bare ``PayLife``, which is also what the *effect* "pay 4 life" reads
    to (``ast/game.py``) — one name for a cost and for a statement, in an AST
    whose two unions are told apart by type.

    ``per_counter`` is "Pay 3 life **for each velocity counter on this
    enchantment**" (Tornado): the printed amount is a *rate*, and how much is
    actually owed is read off the source when the ability is activated. A field
    rather than an ``Amount`` because the multiplier is not a quantity the
    grammar can evaluate — CR 601.2f's cost is computed at activation, and the
    counter is on the permanent whose ability this is.
    """

    amount: Amount = field(default_factory=lambda: Fixed(1))
    per_counter: str | None = None
    #: "Pay 2 life **or {2}**" (Tidal Control). CR 601.2h lets the payer choose
    #: between the printed alternatives as the ability is activated, so this is
    #: one cost with a choice rather than two abilities.
    #:
    #: Carried on the life payment rather than in a ``mana`` cost of its own,
    #: and that is the safety argument: a reader that has not learned the word
    #: charges the **life** — the payment the card definitely allows — where a
    #: flat pair of costs charges *both*, which is what the compiler's prose
    #: reader did before this field existed.
    alternative_mana: tuple[tuple[str, int], ...] = ()


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
    #: "Exile **two** creature cards …" (Night Soil). How many the phrase names,
    #: beside the filter for the reason :class:`SacrificeCost`'s count is beside
    #: its own: only a count can make the cost unpayable, and one card is no
    #: more a payment of a two-card cost than none is (CR 601.2h).
    count: Amount = field(default_factory=lambda: Fixed(1))
    #: "…from **a single** graveyard" (Night Soil). Every object must come out
    #: of the *same* pile — a fact about the set the payer names, not about any
    #: one card, which is why it is on the cost and not on the filter: the
    #: filter is asked of one object at a time and could not express it.
    #: Dropped, the cost would be payable with one card from each of two
    #: graveyards, which is a strictly cheaper cost than the card prints.
    same_zone: bool = False


@dataclass(frozen=True)
class ExileTopOfLibraryCost:
    """"Exile the top card of your library" in front of a colon (Royal
    Herbalist, Phyrexian Devourer, Whirling Catapult, Storm Elemental,
    Seasoned Tactician, Thought Lash).

    CR 118.3 admits it like any other cost, and CR 118.1 makes the payment the
    printed action — so an ability whose library holds fewer than *count* cards
    cannot be activated at all rather than exiling what is there.

    Its own node rather than an :class:`ExileCost` whose filter names the top of
    a library, for the reason :class:`ExileSelf` is not one either: **nothing is
    chosen**. The payer picks no object, no filter is tested, and the cards are
    named by position rather than by characteristic — so an :class:`ObjectFilter`
    would have to carry a fact ("the top *count* of them") it is asked one card
    at a time and cannot express, and the charger would enumerate a zone that
    holds no permanents.

    What it ate is still recorded (``exiled_for_cost`` / ``exiled_set_for_cost``),
    because "the exiled card's mana value" (Phyrexian Devourer) and "if the
    exiled card is a snow land" (Storm Elemental) are asked at resolution, when
    the cards are already in exile (CR 608.2h).
    """
    count: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class RemoveCounterCost:
    counter: str = "+1/+1"
    count: Amount = field(default_factory=lambda: Fixed(1))


Cost = Union[
    ManaCost, TapSelf, SacrificeCost, DiscardCost, PayLifeCost, ExileSelf,
    ExileCost, ExileTopOfLibraryCost, RemoveCounterCost, PayAttachedManaCost
]
