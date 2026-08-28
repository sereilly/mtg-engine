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

from ._core import Amount, Comparison, Cost, ObjectFilter, PlayerRef, TargetSpec, Zone

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
    """"it is untapped", "this creature is attacking"."""
    subject: TargetSpec
    state: str          # tapped | untapped | attacking | blocking
    negated: bool = False


@dataclass(frozen=True)
class StartedTheTurnState:
    """"if Rasputin started the turn untapped" (Rasputin Dreamweaver).

    The same axis :class:`IsState` reads, asked of a *past* moment — so it is
    its own node rather than a flag on that one. A reader of ``IsState`` that
    had not learned the flag would answer the present-tense question, which is
    a different card: Rasputin tapped for mana on your own turn would still
    grow a counter. A node nothing recognizes refuses the line instead, which is
    the loud direction.

    The board cannot answer it — the untap step has already run by the time an
    upkeep trigger asks — so the untap step records the answer before untapping
    anything, beside the untapped-land count Power Surge already needed.
    """
    subject: TargetSpec
    state: str          # tapped
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
class DiedThisTurn:
    filter: ObjectFilter = field(default_factory=ObjectFilter)


@dataclass(frozen=True)
class DiedThisWay:
    """"for each creature that **died this way**" (Glyph of Reincarnation).

    A sibling of :class:`DiedThisTurn` and emphatically not the same set. "This
    turn" is a window of the turn's history that anything may have contributed
    to; "this way" is exactly what an earlier step of *this same effect* just
    destroyed. Reading one as the other would iterate every creature that died
    all turn — including the ones this spell had nothing to do with.

    The lowering refuses it without a producer, as every back-reference in this
    grammar is refused: with no earlier step the words name nothing, and an
    empty loop is a sentence that reports supported and does not run.
    """
    filter: ObjectFilter = field(default_factory=ObjectFilter)


@dataclass(frozen=True)
class DestroyedThisWay:
    """"if **that creature was destroyed this way**" (Infinite Authority).

    The third reading of "this way", and the one that asks a yes/no question
    rather than naming a set: did the destruction an earlier step of this same
    effect *set up* actually take place? Its own node rather than a flag on
    :class:`DiedThisWay` because that one iterates objects a sweep already
    destroyed while this one is checked later — the delayed ability that asks it
    fires at the end step, and what it is asking about happened at end of combat
    in between.

    Refused without a producer like every other back-reference here: with no
    earlier step that armed a destruction, the words name nothing and the
    condition would answer False forever on a card reporting itself supported.
    """
    subject: "ObjectFilter" = field(default_factory=ObjectFilter)


@dataclass(frozen=True)
class ChosenThisWay:
    """"for each of **those cards**" (Sylvan Library).

    The third sibling of :class:`DiedThisTurn` and :class:`DiedThisWay`, and
    the same distinction one more time: this names exactly what an earlier
    sentence of *this same effect* chose, and nothing on the board or in the
    turn's history answers it. Like ``DiedThisWay`` the lowering refuses it
    without a producer — with no earlier "choose" step the words name nothing,
    and an empty loop is a sentence that reports supported and does not run.
    """


@dataclass(frozen=True)
class LifeGainedThisTurn:
    """"if you gained 3 or more life this turn" (CR 603.4 intervening-if).

    A *history*, like :class:`DiedThisTurn` — no read of the board can answer
    it, which is why it is a condition node of its own rather than a comparison
    over some countable. The threshold travels on the node because a card
    printed with another number is the same production.
    """
    who: "PlayerRef"
    amount: int


@dataclass(frozen=True)
class DealtDamageThisTurn:
    """"if this creature dealt damage to an opponent this turn" (Whirling
    Dervish). A history like :class:`LifeGainedThisTurn`, asked of the ability's
    own source: no board read answers it, so the damage seam records it as it
    happens. The recipient is payload — "a player" and "you" are this production.
    """
    subject: "TargetSpec"
    recipient: str


@dataclass(frozen=True)
class PaidCost:
    cost: Cost | None = None


@dataclass(frozen=True)
class RawCondition:
    """A condition the grammar recognizes structurally but does not yet model
    semantically. Carries the source text so lowering can refuse it loudly
    rather than dropping it silently."""
    text: str


@dataclass(frozen=True)
class ReturnedToHandThisTurn:
    """"if a permanent was put into your hand from the battlefield this turn"
    (Barrin, Tolarian Archmage's end-step trigger, CR 603.4 intervening-if).

    A history, like :class:`DiedThisTurn`: no read of the board can answer it,
    so the game keeps a per-seat counter the bounce paths feed."""


@dataclass(frozen=True)
class CoinFlipResult:
    """"you win the flip" / "you lose the flip" (CR 705.2).

    A back-reference to a flip made earlier in the same resolution, never a
    board state — which is why lowering refuses one with no ``FlipCoin`` in
    front of it (the rule round 33 wrote down for "that much").
    """
    won: bool = True


@dataclass(frozen=True)
class RevealedCardIs:
    """``if it's a <filter>`` — a *present-tense* test on a card a previous
    sentence of the same effect revealed. (Track Down.)

    Its own node beside :class:`ItWas`, which is the past-tense one, and the
    distinction is not grammatical fussiness: "it **was** a creature card" asks
    what an object was before it left a zone (CR 608.2h, last-known
    information), while "it**'s** a creature card" asks what a card sitting in a
    library *is*. They read different producers and one of them can be answered
    by looking, so a single node would have to carry a tense flag and every
    reader would have to branch on it.
    """
    filter: "ObjectFilter"


@dataclass(frozen=True)
class ItWas:
    """"If **it** was a creature card" (Scavenging Ooze).

    A back-reference to the object an earlier step of this same effect moved,
    read as last-known information (CR 608.2h): the card is already in exile
    when this is asked, so the answer is what it was in the graveyard, not what
    the exile zone holds.

    The pronoun carries no referent, exactly as ``ThatMuch(None)`` carries no
    producer: the parser cannot see the sentence in front of it, so lowering is
    what resolves "it" against the values earlier steps recorded, and refuses
    when nothing recorded one (round 33's rule).
    """

    filter: "ObjectFilter"


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
class DiscardedCardWas:
    """"If **the discarded card** was a land card" (Land's Edge).

    The same last-known-information question :class:`ItWas` asks, about a
    different producer: the card is in a graveyard by the time this is read, so
    what it *was* in the hand is the only answer there is (CR 608.2h).

    Its own node rather than a widening of ``ItWas`` for the reason the lowering
    keys ``amount_from`` and ``amount_from_trigger`` separately: the phrase names
    which producer it means — the discard — and one node per named producer is
    what keeps a back-reference from reading whatever record happens to be
    lying around.

    Carries no producer field for the same reason ``ItWas`` carries none. Which
    discard wrote the record is lowering's question, and it refuses when nothing
    in the ability discarded anything.
    """

    filter: "ObjectFilter"


@dataclass(frozen=True)
class HadPlus1Counter:
    """"if it had a +1/+1 counter on it" (Basri's Lieutenant, CR 603.4).

    About the creature that just died, so it is answerable only from
    last-known information (CR 603.10): the fire site records the answer as
    the trigger goes on the stack, and the resolution-side gate reads that
    record rather than a board the creature has already left."""


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
class EnteredFrom:
    """"if it entered from your graveyard **or you cast it from your
    graveyard**" (Archfiend's Vessel) — CR 603.4's intervening-if asking where
    the permanent came from.

    Both halves, because they are genuinely two events: a permanent put onto the
    battlefield from a graveyard by a reanimation, and a permanent spell cast
    from a graveyard that then resolved. The card names both and the Demon
    arrives either way; implementing one would be a card that works under
    Unearth and not under its own flashback, which is a difference no player
    would attribute to the engine.

    ``zone`` is where it came from; ``or_cast`` says the cast half is printed
    too. A phrase naming only one is a different, narrower condition, so the
    field is not defaulted to True.
    """
    zone: str
    or_cast: bool = False


@dataclass(frozen=True)
class CouldNot:
    """"…**If you can't**, …" after a mandatory action.

    "Remove a pupa counter from this Aura. If you can't, sacrifice it, put a
    +1/+1 counter on enchanted creature, and that creature gains flying."
    (Cocoon.) The mirror of :class:`ItHappened`: the action before it was not
    optional, so there is no decision to branch on — the branch runs exactly
    when that action *could not be performed*, which for a counter removal is
    a counter not being there to remove (CR 701.44a: removing a counter that
    is not on the object is impossible).

    Carries no field for the reason ItHappened carries none: which step it
    refers to is always the one immediately before, and the lowering pairs
    them where that is known rather than naming a producer here that could
    drift from ``_PRODUCES``.
    """


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
class ItHappened:
    """"…**If you do**, …" after an action that was not optional.

    "Exile it. If you do, create a 5/5 black Demon creature token with flying."
    (Archfiend's Vessel.) The exile is not a choice — the branch is conditional
    on whether it actually *took place*, which for a source that has already
    left the battlefield it did not (CR 608.2b's "as much as possible").

    Distinct from the :class:`May` fold of the same words, which is a branch of a
    decision the player made. Reading this one as that would need a prompt
    nobody is owed; reading it as an unconditional next step would create the
    Demon whether or not the Vessel was there to exile.

    Carries no field: *which* step it refers to is always the one immediately
    before, and the lowering pairs them where that is known rather than naming a
    producer here, where it would be a second copy of ``_PRODUCES``.
    """


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


Condition = Union[
    EveryOf, CoinFlipResult, Controls, DestroyedThisWay, DiscardedCardWas,
    IsState, StartedTheTurnState, DiedThisTurn,
    ObjectHasKeyword,
    HadPlus1Counter, ItWas,
    AttackersAimedAtYou, EnteredFrom, ItHappened, RevealedCardIs,
    LifeGainedThisTurn, PaidCost, RawCondition, ReturnedToHandThisTurn,
    DealtDamageThisTurn, SubjectCharacteristicIs, BlockersOfBoundCreature,
    SourceExiledWithCounter, SourceCounterCount,
]
