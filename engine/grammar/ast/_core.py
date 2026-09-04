"""The vocabulary every family's nodes are built from.

Quantities (what `grammar/amounts.py` produces), object and player references
(`grammar/nouns.py`), and the durations, zones, costs and conditions that hang
off an effect without being one. Plus `RawEffect`, the untyped escape hatch,
which sits beside `RawCondition` because it is the same idea: a clause the
grammar recognized structurally and has no node for, recorded so lowering can
refuse it by name rather than drop it.

The bottom of the package. Nothing here imports from a family, and a node two
families both need belongs here rather than in whichever of them was written
first — that is what keeps "which family does this new node go in?" a question
with one answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


# Re-exported, not merely imported: this module is the address every family
# uses for the shared vocabulary, and the 1,000-line split that moved these
# nodes out must not become 60 edited import lines elsewhere.
from ._primitives import AnyNumber, Fixed
from ._references import (Comparison, ObjectFilter, PlayerRef,
                          SourceRelativeComparison, TargetSpec)




@dataclass(frozen=True)
class Var:
    """A variable: X (or, rarely, Y) — resolved from the cast's x_value."""
    name: str = "x"


@dataclass(frozen=True)
class CountOf:
    """"equal to the number of Swamps you control" — a count of matching objects."""
    filter: "ObjectFilter"


@dataclass(frozen=True)
class CountOfDeaths:
    """"the number of creatures that died under your control this turn" — a
    count of a *history*, not of the board.

    Separate from :class:`CountOf` because the two move in opposite directions:
    the creatures counted here are exactly the ones no longer on the
    battlefield, so reading this as the plain filter "creature" would count the
    survivors. The same distinction :class:`DiedThisTurn` draws for a "for
    each" iterator, at the other end of the sentence.
    """
    filter: "ObjectFilter"


@dataclass(frozen=True)
class CountOfDeathsThisWay:
    """"the number of creatures that died **this way**" (Hellfire) — how many
    objects the *preceding step of this same effect* destroyed.

    A third reading of "the number of creatures" and its own node beside
    :class:`CountOf` and :class:`CountOfDeaths` for the reason those two are
    each other's: this one counts neither the board nor the turn's history but
    one earlier step's result. Read as the plain filter it would count the
    survivors — on Hellfire, exactly the creatures that did *not* die — and read
    as the turn history it would fold in every unrelated death since untap.

    The set is therefore a back-reference, and lowering refuses it unless a step
    of the same effect actually recorded one: with no producer "this way" names
    nothing, and a zero is a number the card never printed.
    """
    filter: "ObjectFilter"


@dataclass(frozen=True)
class CountOfTapsThisWay:
    """"the number of Islands **tapped this way**" (Monsoon) — how many
    permanents the *preceding step of this same effect* turned.

    :class:`CountOfDeathsThisWay` one verb over, and its own node for the same
    reason: read as the plain filter it would count every Island on the board,
    including the ones that were already tapped and the ones on a battlefield
    the sweep never touched.

    The set is therefore a back-reference, and lowering refuses it unless a step
    of the same effect actually recorded one.
    """
    filter: "ObjectFilter"


@dataclass(frozen=True)
class ColorsAmong:
    """"for each color among permanents you control" — how many *colours* the
    named objects have between them (Chromatic Orrery).

    A third aggregate beside :class:`CountOf` and :class:`GreatestPowerAmong`,
    and its own node for the same reason they are each other's: five permanents
    can be one colour and one permanent can be five (CR 105.2b), so counting
    the objects answers a different question from counting the colours among
    them. A colourless permanent contributes nothing — colourless is not a
    colour (CR 105.1).
    """
    filter: "ObjectFilter"


@dataclass(frozen=True)
class GreatestPowerAmong:
    """"the greatest power among creature cards in your graveyard" — a
    *maximum*, not a count.

    Its own node beside :class:`CountOf` for the reason the death count has
    one: the two read the same objects and answer different questions, so a
    lowering that saw only a filter would have to guess which. Zero when the set
    is empty, which is what a maximum over nothing means for a P/T.
    """
    filter: "ObjectFilter"


@dataclass(frozen=True)
class ThatMuch:
    """A back-reference to a quantity the surrounding context produced
    ("you gain that much life", "equal to the damage dealt").

    *source* names the key that quantity was recorded under when the **words
    say which** — "equal to the damage dealt" is `damage_dealt`, "equal to its
    power" is `its_power`. A bare "that much" / "that many" names nothing: it
    points at whatever the enclosing effect or the firing event produced, which
    the parser cannot know from the sentence alone, and it carries `None` to say
    so. Lowering is the layer that resolves it — against the steps of this same
    effect or against the trigger's own event, both in
    `lowering/_common.py::_back_reference_payload` — and refuses when neither
    offers a number.

    It used to default to `"damage_dealt"`, which read as evidence and was only
    a guess: under "Whenever you gain life, target opponent loses that much
    life" there is no damage anywhere, and a lowering that trusted the name
    would have taken the wrong number from the wrong place.
    """
    source: str | None = None
    #: "…equal to its power **plus 2**" (Farrel's Mantle). CR 107.3's arithmetic
    #: on a read value: the number the words name is the characteristic plus a
    #: printed constant, so it rides the back-reference rather than becoming a
    #: second node — every lowering that reads one of these reads a number, and
    #: a bonus in a node of its own would be a second number nobody added.
    #:
    #: Zero is "no bonus printed", which is every card written before this one,
    #: so no payload changes shape. A lowering that cannot carry the bonus must
    #: refuse rather than drop it: two less damage than the card says is the
    #: quiet failure this field exists to make loud.
    bonus: int = 0


@dataclass(frozen=True)
class SacrificedForCost:
    """A characteristic of what the ability's **own cost** sacrificed — "you
    gain life equal to **the sacrificed creature's toughness**" (Life Chisel,
    Diamond Valley).

    Not a :class:`ThatMuch`, and the difference is which channel holds the
    answer. A back-reference reads the resolution scratchpad, filled by an
    earlier *step of the effect*; this names the permanent the **cost** ate
    (CR 601.2h), which is off the battlefield before the ability was ever put
    on the stack. The engine already carries that permanent forward as
    last-known information (CR 608.2h) on ``sacrificed_for_cost``, the same
    channel "the sacrificed artifact's mana value" (Priest of Yawgmoth) reads —
    so this node names the characteristic and the reader names the channel.

    The characteristic is a field rather than part of the node's name for the
    reason the counter kind is payload: "the sacrificed creature's **power**" is
    the same sentence about a different number, and a card printing it needs no
    new node.
    """
    characteristic: str   # "power" | "toughness" | "mana_value"


@dataclass(frozen=True)
class ExiledForCost:
    """A characteristic of what the ability's **own cost** exiled - "where X is
    **the exiled card's mana value**" (Necropolis).

    :class:`SacrificedForCost` one zone over, and the same channel argument: the
    card left the graveyard while the cost was being paid (CR 601.2h), so
    nothing on any board or in any zone answers for it at resolution and the
    number is last-known information (CR 608.2h) the activation path recorded
    under ``exiled_for_cost``.

    Its own node rather than a flag on the sacrifice, because the two read
    different records written by different payments - and a card printing both
    would have them disagree.
    """
    characteristic: str   # "power" | "toughness" | "mana_value"


@dataclass(frozen=True)
class TappedForCost:
    """A characteristic of what the ability's **own cost** tapped — "This
    artifact deals damage equal to **the tapped creature's power** to target
    attacking or blocking creature with flying" (Unerring Sling).

    :class:`SacrificedForCost`'s third sibling, and the odd one of the three:
    the creature is still on the battlefield when the effect reads it, so this
    is not last-known information but a plain *back-reference* — "the tapped
    creature" names the one the cost tapped, and a board scan at resolution
    would name whichever untapped creature its controller happens to have
    tapped since. That is exactly the argument ``untapped_for_cost`` already
    makes on the same channel for Benthic Explorers' land.

    Its own node for :class:`ExiledForCost`'s reason: the three read different
    records written by different payments, and a card printing two of them would
    have them disagree.
    """
    characteristic: str   # "power" | "toughness" | "mana_value"


@dataclass(frozen=True)
class TotalPowerSacrificedThisWay:
    """"…where X is **the total power of the creatures sacrificed this way**"
    (Sword of the Ages).

    An aggregate over the permanents the ability's own *cost* ate, not over
    anything on a board — CR 601.2h pays the cost before the ability is on the
    stack, so by the time X is read those creatures are cards in a graveyard.
    The number is last-known information (CR 608.2h), recorded as the cost was
    charged.

    The noun phrase is carried rather than assumed: "the creatures" is what
    this card sacrifices, and a card printing "the artifacts" is the same
    sentence about a different set. What a reader can actually aggregate is the
    lowering's question.
    """
    filter: ObjectFilter


@dataclass(frozen=True)
class Half:
    """"half X, rounded up/down" — and, with *divisor*, "a third of X" (Pox).

    Named for the word the pool prints most, not for the arithmetic: dividing a
    counted quantity and rounding it is one operation, and Magic has no rule
    that treats a half differently from a third. So a fraction is this node with
    a different denominator rather than a second node beside it — which is what
    keeps `_round_every_half`, `halved_count_spec` and the `half` payload key
    covering Pox's four clauses without knowing they exist.
    """
    of: "Amount"
    rounding: str = "down"  # "down" | "up"
    #: The denominator. 2 for every "half" in the pool, so an untouched node is
    #: byte-identical to the ones written before fractions existed.
    divisor: int = 2


@dataclass(frozen=True)
class AllOf:
    """An unbounded quantity: "all damage", "any amount of mana"."""




@dataclass(frozen=True)
class BoardCount:
    """A board-state count identified by *name* rather than built compositionally:
    "the number of untapped lands they controlled at the beginning of this turn".

    :class:`CountOf` covers the counts whose whole meaning *is* a noun phrase
    ("the number of Swamps they control"), because there the filter is the
    arithmetic. These are the ones where it is not: they reach back to an
    earlier point in the turn, or subtract a constant, or read a hidden zone —
    arithmetic no ``ObjectFilter`` expresses and which the *handler* implements
    end to end. Lowering therefore maps a name onto the single handler that
    computes exactly it, and refuses every name it has no handler for.

    Naming the count instead of approximating it is the point. Reading Black
    Vise's "the number of cards in their hand minus 4" as an ordinary filtered
    count would drop the "minus 4" — the dropped-rider bug class — and the card
    would deal four damage too much while still reporting as supported.

    *base* is the constant such a count subtracts against, and it is **payload
    rather than part of the name** for the reason the land type in
    ``combat_restrictions.py`` is: "3 minus the number of cards in their hand"
    (The Rack) and "the number of cards in their hand minus 4" (Black Vise) are
    one arithmetic with one number changed. Spelling the 4 into the phrase made
    every other threshold a non-match — the false-negative failure — and The
    Rack was a name-keyed card hook purely because its number was 3. A count
    whose meaning needs no constant leaves it None.
    """
    name: str
    base: int | None = None


@dataclass(frozen=True)
class AdditionalCostPaidCount:
    """``the number of additional {1}{G} you paid`` — how many times a CR 601.2b
    optional additional cost was taken.

    A quantity that is neither a board count nor a history: the caster
    announced it as the spell was cast, and the mana pool that paid it emptied
    at the end of that step (CR 500.4), so the announcement carried on the stack
    item is the only thing that can answer. That is why it is its own leaf
    rather than a :class:`BoardCount` name — nothing about the board or the
    turn's record moves this number.

    ``symbols`` is the printed cost exactly as the card spells it. Lowering
    turns it into the canonical key the payment recorded under, through the one
    function that answers that for both halves of the read-back.

    Every lowering written before it exists refuses it by default, which is the
    union's standing guarantee for a new quantity.
    """
    symbols: str = ""


@dataclass(frozen=True)
class Plus:
    """``1 plus the number of creature cards in your graveyard`` (Wall of
    Tombstones), ``1 plus the power of target creature …`` (Sentinel) — a sum
    of two printed quantities.

    A node rather than arithmetic folded at parse time because the right-hand
    side is usually not a number yet: a count or a characteristic read at
    resolution. Every lowering written before it exists refuses it by default,
    which is the union's standing guarantee for a new quantity.
    """
    left: "Amount"
    right: "Amount"


@dataclass(frozen=True)
class Times:
    """``twice the number of white creatures that player controls`` (Jovial
    Evil) — a printed quantity multiplied by a printed factor.

    The mirror of :class:`Half`, and a node for the same reason :class:`Plus`
    is one: the thing being scaled is usually not a number yet, so the
    arithmetic cannot be folded at parse time. *factor* is payload — "twice"
    and "three times" are one shape with one number changed, and spelling the 2
    into the phrase would make every other multiple a non-match, which is the
    false-negative the ``BoardCount`` docstring above records.

    Every lowering written before it exists refuses it by default, which is the
    union's standing guarantee for a new quantity: a scaled count read as a
    plain one would deal half the damage the card prints.
    """
    factor: int
    of: "Amount"


@dataclass(frozen=True)
class CharacteristicOfTarget:
    """``the power of target creature blocking or blocked by this creature``
    (Sentinel), ``the toughness of target creature blocking or being blocked by
    this creature **minus 1**`` (Sworn Defender) — one named object's
    characteristic, read at resolution.

    Beside :class:`GreatestPowerAmong` and not inside it: that node aggregates
    over a described *set*, this one reads a single referent — typically a
    chosen target, which means the quantity itself is what carries the
    sentence's target. A lowering that accepts it must therefore describe the
    target it names, or refuse; dropping it would leave a picker with nothing
    to enumerate.

    *characteristic* is a field and not half the class name, for exactly the
    reason :class:`CharacteristicOfSubject` gives one field down: a
    ``ToughnessOfTarget`` beside a ``PowerOfTarget`` would be two copies of one
    production reaching two accessors through one resolution, and the next card
    printing a third word would need a third copy. This node **was**
    ``PowerOfSubject``, single-characteristic, and Sworn Defender is the card
    that printed the second word.

    *offset* is the printed constant the phrase adds or subtracts ("…minus 1"),
    and it is payload for :class:`BoardCount`'s stated reason: "its toughness
    minus 1" and "its power plus 2" are one arithmetic with one number changed.
    Dropping it would set a base P/T one point off and report the card
    supported — the dropped-rider class.

    It is **not** the same node as :class:`Plus`. "1 plus the power of that
    creature" is a printed number *in front of* the phrase and stays a ``Plus``
    over this one; "the toughness of … minus 1" is a modifier *inside* it, and
    the two are different because only the second one binds to the read.
    """
    subject: "TargetSpec"
    characteristic: str = "power"    # power | toughness
    offset: int = 0


@dataclass(frozen=True)
class CountersOnSource:
    """"the number of doom counters on it" (Armageddon Clock) — how many CR
    122.1 named counters the ability's own source is carrying.

    Its own node rather than a :class:`CountOf` over a noun phrase because a
    counter is not an object: it has no controller, no type line and no zone, so
    every narrowing an ``ObjectFilter`` could carry would be a question about a
    permanent instead of about what is sitting on one. The kind is data — the
    word the card invented — so the next set's counter needs no production.
    """
    kind: str


@dataclass(frozen=True)
class DamageDealtThisTurn:
    """"the amount of damage dealt to this creature this turn by other sources
    named ~" (Blazing Effigy) — a *history*, not anything on a board.

    Its own node beside :class:`CountOf` for the reason :class:`CountOfDeaths`
    is one: what it names is over. The damage marked on a creature is wiped when
    it leaves the battlefield, and this clause is printed on a dies-trigger — so
    reading it as a board quantity would answer zero on every card that could
    ever print it. ``engine/damage_ledger.py`` is the record it reads.

    Every field is payload, because every one of them is a word the card
    printed. *source_name* is ``"self"`` — the SELF token, the card naming
    itself — and never a spelled-out name, which is what keeps a card name out
    of the engine (``tests/engine/test_card_name_reads.py``). *others_only* is
    CR 109.5's "**other** sources": an identity comparison against the ability's
    own source, the same narrowing "another creature" already carries.
    """
    recipient: str = "source"
    source_name: str = "self"
    others_only: bool = False


@dataclass(frozen=True)
class DamageDealtByChosenCast:
    """"the damage dealt by **one of those** sorcery spells this turn"
    (Backdraft) — a history, narrowed by a choice the resolution makes.

    "Those" is a back-reference to the set an earlier sentence described ("a
    player who cast one or more sorcery spells this turn"), so lowering refuses
    it without that producer: with no earlier choice the phrase names nothing,
    and the zero it would otherwise read is a number the card never printed.

    Beside :class:`DamageDealtThisTurn` and not inside it, because the two are
    narrowed on opposite axes: that one fixes the *recipient* and asks which
    sources hit it, this one fixes a single **cast** and asks what it dealt.
    One node reading either would need a key for every field of both.
    """
    card_type: str


Amount = Union[Fixed, Var, CountOf, CountersOnSource, ThatMuch, SacrificedForCost, ExiledForCost, TappedForCost, TotalPowerSacrificedThisWay, Half, Times, AllOf, AnyNumber, BoardCount, Plus, CharacteristicOfTarget, DamageDealtThisTurn, DamageDealtByChosenCast, AdditionalCostPaidCount]


# ---------------------------------------------------------------------------
# Object and player references (engine/grammar/nouns.py)
# ---------------------------------------------------------------------------










# A recipient of damage/effects can be objects, players, or the "any target"
# shorthand (CR 115.4).
Recipient = Union[TargetSpec, PlayerRef]


# ---------------------------------------------------------------------------
# Durations, zones, costs, conditions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Duration:
    """How long a continuous effect lasts. ``None`` kind means permanent."""
    kind: str | None = None
    # until_end_of_turn | until_end_of_combat | this_turn | until_your_next_turn
    # | until_your_next_upkeep | until_end_of_your_next_upkeep | until_end_of_that_turn | while_source_tapped


@dataclass(frozen=True)
class CharacteristicOfSubject:
    """"…, where X is **its** mana value" (Great Defender, Subdue, Kry Shield,
    In the Eye of Chaos), "…, where X is **its toughness minus 1**" (Blood
    Lust).

    The other kind of where-clause: `CountOf` counts a set of objects, this one
    reads a characteristic off the single object the sentence already named —
    the creature it pumps, the spell it counters. It carries no subject; "its"
    is the sentence's own subject and the lowering is what knows which object
    that is.

    *characteristic* is a field rather than half the class name because the
    three words reach three accessors through one resolution: a
    ``ToughnessOfSubject`` beside a ``ManaValueOfSubject`` would be two copies
    of one production, and every card printing the third word would need a
    third.

    *offset* is the printed constant the clause adds or subtracts, and it is
    payload for exactly the reason :class:`BoardCount`'s ``base`` is: "its
    toughness minus 1" and "its mana value plus 2" are one arithmetic with one
    number changed. Dropping it would leave Blood Lust giving -X where X is the
    whole toughness — a creature killed outright by the arm that is printed
    specifically not to kill it.
    """
    characteristic: str          # mana_value | power | toughness
    offset: int = 0
    #: The noun phrase a *named* back-reference spells out — "the power of
    #: **that blocked creature**" (Glyph of Delusion) rather than a bare "its".
    #:
    #: A sentence that names one object needs no referent: "its" can only mean
    #: that one. A sentence that names **two** targets of different kinds does,
    #: because "its" would be ambiguous and English says which by repeating the
    #: noun. So the phrase is parsed and carried, and the lowering matches it
    #: against the sentence's own target roles — an unmatched or ambiguous
    #: referent refuses the line rather than picking a role and being right half
    #: the time.
    referent: "ObjectFilter | None" = None


@dataclass(frozen=True)
class Zone:
    name: str                       # battlefield | graveyard | hand | library | exile | stack
    owner: PlayerRef | None = None




@dataclass(frozen=True)
class RawEffect:
    """An imperative clause the grammar structurally recognizes as an effect
    but has no typed node for yet. Never lowered — its presence marks the line
    as "parsed but not lowerable", which the ratchet tracks separately from a
    parse failure."""
    text: str
