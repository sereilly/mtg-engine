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


Condition = Union[
    EveryOf, CoinFlipResult, Controls, DiscardedCardWas, IsState, DiedThisTurn,
    ObjectHasKeyword,
    HadPlus1Counter, ItWas,
    AttackersAimedAtYou, EnteredFrom, ItHappened, RevealedCardIs,
    LifeGainedThisTurn, PaidCost, RawCondition, ReturnedToHandThisTurn,
    DealtDamageThisTurn, SubjectCharacteristicIs,
]
