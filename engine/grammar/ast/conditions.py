"""What a trigger or an ``if`` clause **tests** (CR 603.4, CR 605).

Split out of ``_core`` when that module reached the thousand-line guard, and
this is the cut because it is the one question `_core` asks that nothing else
in `_core` needs the answer to. The rest of that module is the vocabulary every
node is *built from* — how much (`Amount`), which objects (`ObjectFilter`,
`TargetSpec`), whose (`PlayerRef`), what it costs (`Cost`) — and a condition is
built from all of them while none of them is built from a condition. The
dependency runs one way, so the split does too.

Beside `_core` rather than among the effect families, and named in the layering
guard's `shared` tuple with it: every family that lowers a conditional reads
these, so a condition living in one family would couple the rest to it — which
is the coupling that makes the grouping stop being information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from ._core import Amount, Comparison, ObjectFilter, PlayerRef, TargetSpec
from .costs import Cost
# The other half of the split (see ``records``'s own docstring). Imported
# rather than re-declared because the ``Condition`` union at the foot of
# this module is the roof over both halves, and a roof that could only see
# one of them is the drift the union's own note is about.
from .records import (AdditionalCostWasPaid, AttackedOrBlockedThisCombat,
                      ChosenThisWay, CoinFlipResult, CostObjectWas,
                      CouldNot, CountedNumber, CountersPlacedThisWay,
                      DamagedBySourceDiedThisTurn, DealtDamageThisTurn,
                      DestroyedTargetWas, DestroyedThisWay, DiedThisTurn,
                      DiedThisWay, DiscardedCardWas, DiscardedThisWay,
                      EachAdditionalCostPaid,
                      EachLifeLost, EachShortOfThisWay, EnteredFrom,
                      ExiledThisWay, HadPlus1Counter,
                      InABlockSinceLastUpkeep, ItHappened, ItWas,
                      LifeGainedThisTurn, MilledThisWay, PaidCost,
                      ReturnedToHandThisTurn, RevealedCardIs,
                      SacrificedThisWay, SourceAbilityActivations,
                      StartedTheTurnState, TappedThisWay)

@dataclass(frozen=True)
class Controls:
    """"you control an Island", "the chosen player controls no nontoken permanents"."""
    who: PlayerRef
    filter: ObjectFilter
    comparison: Comparison | None = None
    #: "…two or more nonland, nontoken permanents **with the same name as one
    #: another**" (Chrome Replicator). A relation *between* the counted objects,
    #: which is why it sits here and not on `filter`: an ObjectFilter is tested
    #: against one permanent at a time, and no single permanent can answer
    #: whether it shares a name with something else. Set, `comparison` stops
    #: bounding the whole matching set and bounds the largest same-name group
    #: within it.
    shared_name: bool = False


@dataclass(frozen=True)
class OnBattlefield:
    """"no creatures are on the battlefield" (Pestilence, Withering Wisps).

    A count over the battlefield itself, with no player in it. That is what
    separates it from :class:`Controls`, whose every reading is relative to a
    seat: "you control no creatures" is a different sentence and a different
    card, and reading this one as a `Controls` over every player would give the
    same answer for "no" and a different one for every other quantifier — a
    per-seat count compared against a threshold is not the board's count.

    The quantifier is the comparison, exactly as it is on `Controls`: "no" is
    zero and "a" is one or more. A number is left unread rather than guessed,
    because a threshold silently taken as presence is a condition that holds on
    a board the card does not name.
    """
    filter: ObjectFilter
    comparison: Comparison


@dataclass(frozen=True)
class ZoneHasCards:
    """"If **your library has ten or more cards in it**" (Phyrexian Portal).

    A count of a *zone*, not of a board, which is why it is not an
    :class:`OnBattlefield` with a zone field: that node asks what permanents
    exist and answers through the layer system, where this one asks how tall a
    pile is and nothing about the cards in it matters at all.

    Both the seat and the zone are read rather than assumed. Every printing of
    this clause in the pool names its own library, and a wording naming
    somebody else's is a question about a pile this player cannot see - so
    admitting it without recording whose would answer about the wrong deck.
    """
    player: PlayerRef
    zone: str
    comparison: Comparison


@dataclass(frozen=True)
class PlayerLifeIs:
    """"If **that player has 5 or less life**" (Razor Pendulum).

    Its own node rather than a :class:`ZoneHasCards` with ``zone="life"``: a
    life total is not a pile, and giving that node a zone name no player state
    has would make every reader of it guess which kind of thing it was counting.
    The two are otherwise the same shape on purpose — a seat and a comparison —
    because the printed sentence is the same shape ("<player> has <N or less>
    <quantity>") and the difference is only what is counted.
    """
    player: PlayerRef
    comparison: Comparison


@dataclass(frozen=True)
class LifeTotalDifference:
    """"If **the difference between your life total and target player's life
    total is 5 or less**" (Psychic Transfer).

    Two seats and one comparison, where :class:`PlayerLifeIs` above has one
    seat: the number this compares is not any player's life total but the
    *distance* between two of them, which no seat owns. Folding it into that
    node with a second player field would have made every reader ask whether
    the second seat was set before knowing what it was comparing.

    Unsigned, because "the difference between" is: CR 107.1 has no negative
    quantities, and the card reads the same whichever player is ahead.
    """
    first: PlayerRef
    second: PlayerRef
    comparison: Comparison


@dataclass(frozen=True)
class SomeOf:
    """"if a card with the same name is in a graveyard **or** a nontoken
    permanent with the same name is on the battlefield" (Bazaar of Wonders) —
    any part is enough.

    :class:`EveryOf`'s twin, and a separate node for that one's reason: the
    disjunction is about the clause list rather than about any one clause, and
    nothing stops a card joining two different condition kinds with "or".
    Folding the two into one node with an operator field would make every
    reader ask which it was before it could ask anything else.
    """

    conditions: tuple["Condition", ...]


@dataclass(frozen=True)
class SameNamedObject:
    """"a card **with the same name** is in a graveyard" / "a nontoken permanent
    with the same name is on the battlefield" (Bazaar of Wonders).

    "The same name" as *what the firing event named* — CR 201.2's name compared
    against the spell the trigger fired on, which is why this is not an
    ``ObjectFilter`` with ``named`` set: that field holds a printed literal, and
    this one holds a comparison against an object nothing knows until the
    trigger fires.

    ``zone`` is which pile is searched and ``nontoken`` is CR 111's exclusion,
    both printed. They are separate fields rather than two node kinds because
    the question — does an object of this name exist over there — is one
    question asked of two zones.
    """

    zone: str
    nontoken: bool = False


@dataclass(frozen=True)
class EveryOf:
    """"if you control an Urza's Mine **and** an Urza's Tower" — every part must
    hold (CR 104 has no conjunction rule; this is plain English "and").

    Its own node rather than a repeated field on each condition, because the
    conjunction is about the clause list and not about any one clause: the
    Urza's cycle conjoins two `Controls`, and nothing stops a card conjoining a
    `Controls` with a `DiedThisTurn`.

    Named `EveryOf` rather than the obvious `AllOf` because that name is taken,
    by the *quantity* node meaning "all damage" / "any amount of mana". Two
    unrelated senses of "all" under one name in a flat re-export is how a
    conjunction of conditions ends up standing in for an unbounded amount.
    """
    conditions: tuple["Condition", ...]


@dataclass(frozen=True)
class IsState:
    """"it is untapped", "this creature is attacking", "it didn't attack this
    turn".

    Every state is a field the permanent already carries, which is what makes
    the word a parameter rather than a production apiece — the evaluator reads
    ``getattr(permanent, state)`` and nothing here has to know what blocking
    means.

    ``attacked_this_turn`` is a *record* of the turn rather than a present
    state, and it is on this node anyway because it is asked the same way, of
    the same object, off the same permanent; the cleanup step sweeps it. What
    keeps it honest is that nothing about the reading differs — a past-tense
    axis the board could not answer would want its own node, which is what
    :class:`StartedTheTurnState` beside it is.

    The **subject** is on the node because it is not always the source: an
    Aura's "…if it didn't attack this turn" (Aggression) asks about the
    creature it enchants, and ``rebinding`` is what points the pronoun there.
    """
    subject: TargetSpec
    state: str          # tapped | attacking | blocking | attacked_this_turn
    negated: bool = False
@dataclass(frozen=True)
class SourceOnBattlefield:
    """"if this enchantment is on the battlefield" (Tombstone Stairwell).

    CR 603.4's intervening-if asking whether the ability's own source is still
    where it was when the trigger fired. It reads as a redundancy and is not
    one: the condition is checked again as the ability resolves, so a source
    destroyed in response makes the whole ability do nothing — which for
    Tombstone Stairwell is the difference between an upkeep that fills two
    boards with Zombies and one that does not.

    Its own node rather than an :class:`IsState` with a state word, because the
    two read different things: every state on that node is a field of the
    permanent, and this is a question about which *zone* the object is in
    (CR 400.1), which only the game can answer. A state word the permanent
    cannot answer reads False forever, which here would silently turn the
    clause into "never".

    The subject travels on the node for :class:`IsState`'s reason — a printed
    "it" can have been rebound to an attached host — and lowering refuses a
    rebound one rather than answering about the wrong object.
    """
    subject: "TargetSpec"
    negated: bool = False


@dataclass(frozen=True)
class SubjectCharacteristicIs:
    """"if this creature's power is 1 or more" (Lesser Werewolf), "if target
    creature has toughness 5 or greater" (Blood Lust).

    A comparison against a *computed* characteristic (CR 613 layer 7), which is
    why it is a condition node rather than a narrowing on the subject: there is
    one object in hand and a question about it, not a set to filter.

    All three of *which* object, *which* characteristic and *what bound* travel
    on the node. The characteristic is a field rather than half the class name
    because "power" and "toughness" ask the identical question of the identical
    accessor pair — a `SubjectToughnessIs` beside a `SubjectPowerIs` would be
    two copies of one production, and the day a card prints "mana value 3 or
    less" it would be three.

    The subject is a full :class:`TargetSpec` so the clause can name the
    *spell's own target*. Lesser Werewolf asks about the ability's source and
    Blood Lust asks about the creature it targets; the difference is entirely
    which object the spec resolves to, and the comparison underneath does not
    change.
    """
    subject: "TargetSpec"
    characteristic: str      # power | toughness
    comparison: "Comparison"
@dataclass(frozen=True)
class RawCondition:
    """A condition the grammar recognizes structurally but does not yet model
    semantically. Carries the source text so lowering can refuse it loudly
    rather than dropping it silently."""
    text: str
@dataclass(frozen=True)
class ObjectHasKeyword:
    """"If **it doesn't have rampage**, …" (Rapid Fire).

    A question about the object the sentence's *other* clause named — for a
    spell, the creature it targeted, which is the same referent "that creature"
    binds to in the clause behind it. Carries no subject field for the reason
    :class:`ItHappened` carries none: the parser cannot see the sentence in
    front of it, so which object "it" is belongs to lowering, and lowering
    refuses where the referent is not the target.

    ``keywords`` is a tuple because the keyword list production reads one; a
    card printing "doesn't have flying or trample" would be answered by the
    same node rather than by a second one.
    """

    keywords: tuple[str, ...]
    negated: bool = False
@dataclass(frozen=True)
class AttackersAimedAtYou:
    """"if **two or more of those creatures** are attacking you and/or
    planeswalkers you control" (Mangara, the Diplomat).

    CR 603.4's intervening-if over the batch the trigger fired on. Not a board
    count: "those creatures" is exactly the set declared in this attack, and a
    count of attacking creatures at large would include another opponent's.

    Both halves of the aim are one question — the player and their walkers — so
    there is one field and not two: a creature attacking a planeswalker its
    controller owns is attacking *them* for this purpose, and the card says so.
    """
    count: int
@dataclass(frozen=True)
class BlockersOfBoundCreature:
    """"if at least one other Wall creature is blocking that creature and no
    non-Wall creatures are blocking that creature" (Wall of Caltrops).

    CR 603.4's intervening-if over a *relation*, and the relation's far end is
    not this ability's source: "that creature" is the creature the firing block
    event named, and the clause counts what else is blocking **it** (CR 509.1a).
    So no read of any one permanent can answer it and no read of the source can
    either — which is why it is a condition node of its own rather than more
    adjectives on an `ObjectFilter`, the same discipline `_core.blocking_target`
    keeps on the effect side.

    Both halves the card prints are this one production with different payload:
    "at least one other Wall creature" is ``ge 1`` over a Wall filter carrying
    ``other_than_source``, and "no non-Wall creatures" is ``eq 0`` over a filter
    carrying ``excluded_subtypes``. The printed number and the printed noun
    phrase travel on the node, never in the kind — a card printed "at least two
    Soldiers" is this production and needs no code.
    """
    filter: ObjectFilter
    comparison: Comparison
@dataclass(frozen=True)
class SourceExiledWithCounter:
    """"if **this card is exiled with a scream counter on it**" (All Hallow's
    Eve) — CR 603.4's intervening-if asked of an object that is in *exile*.

    Two claims, and both are read: the source is in exile (CR 406.2 — a public
    zone, so this is answerable at any time) and it carries at least one
    counter of the named kind. Dropping either half would make the trigger fire
    off a card that had left exile or off one whose last counter has already
    come off, which is the difference between a card that reanimates once and a
    card that reanimates every upkeep forever.

    The counter word is payload for the reason every counter word in this
    engine is: CR 122.1 lets a card invent one, so "scream" is data.
    """

    counter: str


@dataclass(frozen=True)
class AttachedCounterCount:
    """``if that creature has three or more +1/+0 counters on it`` (Consuming
    Ferocity).

    :class:`SourceCounterCount`'s twin over a different object: the permanent
    the Aura is attached to rather than the Aura. Two nodes and not one with a
    subject flag, because the two are answered by reading two different
    permanents and a card printing one never means the other — an enchantment
    counting *its own* +1/+0 counters is always counting zero.

    ``bound`` is which printed subject the card used. False is "enchanted
    &lt;noun&gt;", which names the host outright; True is "that &lt;noun&gt;",
    which names it only because an earlier step of the same effect did — a fact
    about the effect rather than about this clause, so the lowering is what
    checks it.
    """
    counter: str
    count: int
    bound: bool = False
    #: The comparison, as :class:`SourceCounterCount` carries it. Only
    #: ``"at_least"`` is printed on this side today ("three **or more**"); the
    #: field exists so the two nodes stay readable against each other.
    comparison: str = "at_least"


@dataclass(frozen=True)
class SourceCounterCount:
    """"if **there are no more scream counters on it**" (All Hallow's Eve).

    A count of the named counters on the ability's own source, compared against
    a number. Only the zero comparison is printed here, and that is what the
    parser reads; the field is a number rather than a flag so the card that
    prints "if there are two or more" extends the production instead of needing
    a second node.

    Asked of the *source*, whichever zone it is in — a permanent's metadata or
    an exile record's — through the one reader in
    ``engine/exiled_records.py``. A second reader for the exile answer is how a
    card ends up counting counters nothing put there.
    """

    counter: str
    count: int
    #: How *count* is compared. "exactly" is All Hallow's Eve's zero test;
    #: "at_least" is Fasting's "five **or more** hunger counters". A field
    #: rather than a second node for the reason ``count`` is a number rather
    #: than a flag — the question is one question, and the comparison is the
    #: printed words that vary.
    comparison: str = "exactly"
@dataclass(frozen=True)
class ItIsColor:
    """"Counter target spell **if it's red**." (Hydroblast, Pyroblast.)

    A present-tense colour test on the pronoun, and the pronoun names *the
    object this effect targets* — which is the referent :class:`ObjectHasKeyword`
    beside it reads, one characteristic over.

    Its own node rather than a colour on :class:`RevealedCardIs`, which is the
    other clause opening "if it's": that one asks what a card an earlier
    sentence **revealed** is, and this one asks about a target nothing revealed.
    Same words, different producer, so different nodes — the rule that already
    keeps :class:`ItWas` and :class:`DiscardedCardWas` apart.

    The colour is a symbol (``"R"``), the spelling every filter and every
    colour accessor in the engine already uses, so the two cards printing this
    differ by payload alone.

    **Which object the pronoun names is not settled here.** A spell targets and
    a permanent targets, and the two are resolved from different halves of the
    resolution context; lowering reads it off the effect this condition guards,
    because that is the only place both are in view (CR 608.2c: the instruction
    and its "if" are one sentence).
    """

    color: str
    negated: bool = False


@dataclass(frozen=True)
class TurnIsYours:
    """"**During your turn**, creatures you control get +2/+0." / "**During
    turns other than yours**, creatures you control get -0/-2." (Vibrating
    Sphere.)

    Whose turn it is, as a *condition* on a static ability rather than as a
    duration. The distinction is the same one :func:`parser._parse_static_condition_line`
    draws for "as long as": a duration is granted by something that resolves and
    then persists, while this bonus exists exactly while the turn does — it
    appears at the untap step and is gone at the next one, with nothing to undo.

    ``negated`` is "turns other than yours", which is the same question asked
    the other way round; a second node would be two readers of one fact, free to
    disagree about a game with three seats (it is *not* "an opponent's turn":
    with the source's controller inactive, every other seat's turn qualifies).
    """

    negated: bool = False


@dataclass(frozen=True)
class SelfInGraveyardWithCardsAbove:
    """"if **this card is in your graveyard with a creature card directly above
    it**" (Death Spark, Krovikan Horror); "…**with three or more creature cards
    above it**" (Nether Shadow).

    Two things at once, which is why it is one node rather than a zone test and
    a count test:

    * **Where the ability functions.** CR 113.6b — "an ability that states which
      zones it functions in functions only from those zones" — and this clause
      is that statement. The effect behind it prints no source zone of its own
      ("return this card to your hand"), so this is the *only* place the card
      says a graveyard is where the ability works at all. The lowering exposes
      it as ``functions_from``, the same derived key CR 113.6m stamps from a
      printed "from your graveyard", so the graveyard scan in
      ``engine/events.py`` needs to know nothing new.
    * **Where in the graveyard.** A graveyard is an ordered zone (CR 404.3), and
      "above" means later in that order — put there more recently. "Directly"
      narrows it to the one card immediately above, which is a different
      question from a count and not expressible as one: three creature cards
      above with a land between them satisfies Nether Shadow and not Death
      Spark.

    ``card_type`` is the printed noun and ``count``/``at_least`` the printed
    number, so a card printing "two or more land cards above it" is data rather
    than a second production.
    """

    card_type: str
    count: int = 1
    #: "three **or more**" (Nether Shadow) against the bare "a" (Death Spark).
    at_least: bool = False
    #: "**directly** above it": the one card in the slot immediately above,
    #: rather than any card anywhere above.
    directly: bool = False


#: Every node a condition clause can be. **Complete**, and held so by
#: ``tests/engine/test_grammar_layering.py``: it was a hand-maintained list that
#: had drifted twelve entries behind the modules it names, which is the shape
#: this repo keeps finding on the wrong side of — a declaration nothing checks
#: is a comment. Both halves of the split are here, which is also why the roof
#: sits on this side of it: `records` is read by `conditions`, never the
#: reverse, so the dependency runs one way exactly as it does between `_core`
#: and both.
Condition = Union[
    # Asked of the board, the zones and the players as they are now
    # (this module).
    AttackersAimedAtYou,
    BlockersOfBoundCreature,
    Controls,
    EveryOf,
    IsState,
    ItIsColor,
    ObjectHasKeyword,
    OnBattlefield,
    SourceOnBattlefield,
    LifeTotalDifference,
    PlayerLifeIs,
    RawCondition,
    SameNamedObject,
    SelfInGraveyardWithCardsAbove,
    AttachedCounterCount,
    SourceCounterCount,
    SomeOf,
    SourceExiledWithCounter,
    SubjectCharacteristicIs,
    TurnIsYours,
    ZoneHasCards,
    # Asked of a record of what already happened (``ast/records.py``).
    AdditionalCostWasPaid,
    AttackedOrBlockedThisCombat,
    ChosenThisWay,
    CoinFlipResult,
    CostObjectWas,
    CouldNot,
    CountedNumber,
    CountersPlacedThisWay,
    DamagedBySourceDiedThisTurn,
    DealtDamageThisTurn,
    DestroyedTargetWas,
    DestroyedThisWay,
    DiedThisTurn,
    DiedThisWay,
    DiscardedCardWas,
    DiscardedThisWay,
    EachAdditionalCostPaid,
    EachLifeLost,
    EachShortOfThisWay,
    EnteredFrom,
    ExiledThisWay,
    HadPlus1Counter,
    InABlockSinceLastUpkeep,
    ItHappened,
    ItWas,
    LifeGainedThisTurn,
    MilledThisWay,
    PaidCost,
    ReturnedToHandThisTurn,
    RevealedCardIs,
    SacrificedThisWay,
    SourceAbilityActivations,
    StartedTheTurnState,
    TappedThisWay,
]
