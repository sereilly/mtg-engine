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
class CountedNumber:
    """"If **the number** is odd" / "…is even" (Chaos Moon).

    A back-reference, not a count: the number is whatever the "Count the number
    of permanents." in front of it recorded, read out of the resolution
    scratchpad. Its own node rather than an :class:`OnBattlefield` with a
    missing filter, and that is the whole distinction — one asks the board and
    the other asks what an earlier sentence of the same effect already asked.
    Folded together, the two branches would each count a board that the first
    branch may have changed, and a card printing both parities could answer yes
    to neither.

    The comparison is always a parity, because that is what "the number is …"
    prints; the lowering refuses when no count precedes it, the way every other
    back-reference in this grammar refuses without a producer.
    """
    comparison: Comparison


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
class DamagedBySourceDiedThisTurn:
    """"if a creature dealt damage by **this creature** this turn died"
    (Krovikan Vampire) — CR 603.4's intervening-if over a *relation*.

    Its own node beside :class:`DiedThisTurn` rather than a filter on it,
    because the relation has no payload form: ``ObjectFilter``'s
    ``dealt_damage_to_source_this_turn`` is never emitted, and
    ``died_this_turn`` is answered off a bare game-wide counter that could not
    read one if it were. Folded in, the condition would be satisfied by any
    death at all — every end step of every game with a creature trade in it.

    Carries no fields: the relation is to the ability's own source, and the
    ledger the evaluator reads lives on that permanent.
    """


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
class ExiledThisWay:
    """"for each creature **exiled this way**" (Martyr's Cry).

    A sibling of :class:`DiedThisWay`, and a different set for the same reason
    that one is different from :class:`DiedThisTurn`: a sweep that *exiles* kills
    nothing, so nothing died and the destroy family's record is empty. Reading
    one as the other would make the loop run zero times while the card still
    reported supported.

    Its own node rather than a verb field on ``DiedThisWay`` because what
    separates them is which earlier step recorded the set — two records, written
    by two handlers — and a node that carried the record's name as data would be
    a back-reference free to name one nothing writes.
    """
    filter: ObjectFilter = field(default_factory=ObjectFilter)


@dataclass(frozen=True)
class MilledThisWay:
    """"If one or more creature cards **were put into that graveyard this
    way**" (Helm of Obedience).

    The fourth set-naming sibling of :class:`DiedThisWay`,
    :class:`ExiledThisWay` and :class:`TappedThisWay`, and a *condition* rather
    than an amount: the sentence asks whether the loop found one, not how many.
    Its own node for those three's reason - what tells them apart is which
    earlier step recorded the set, and a node carrying the record's name as
    data would be a back-reference free to name one nothing writes.

    The graveyard is not a field. "That graveyard" is the one the loop in front
    of this sentence milled into and there is nothing else it could be; a
    wording naming another pile would be asking about cards this effect never
    put there, which the record cannot answer.
    """
    filter: ObjectFilter = field(default_factory=ObjectFilter)


@dataclass(frozen=True)
class TappedThisWay:
    """"for each creature **tapped this way**" (Raiding Party).

    The third set-naming sibling of :class:`DiedThisWay` and
    :class:`ExiledThisWay`, and its own node for the reason those two are
    separate from each other: what tells them apart is which earlier step
    recorded the set, and a node carrying the record's name as data would be a
    back-reference free to name one nothing writes.

    Its objects are still on the battlefield, which is what makes it the
    interesting one: the board *can* be asked which permanents are tapped, and
    the answer is a strictly larger set than this names — every permanent that
    was already tapped when the effect began. So the record is not a workaround
    for objects that have left, it is the only thing that knows which taps were
    this effect's.

    Refused without a producer like every other back-reference here.
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
    """"for each of **those cards**" (Sylvan Library) / "for each of **those
    creatures**" (Winter's Chill).

    The third sibling of :class:`DiedThisTurn` and :class:`DiedThisWay`, and
    the same distinction one more time: this names exactly what an earlier
    sentence of *this same effect* chose, and nothing on the board or in the
    turn's history answers it. Like ``DiedThisWay`` the lowering refuses it
    without a producer — with no earlier "choose" step the words name nothing,
    and an empty loop is a sentence that reports supported and does not run.

    *subject* is the printed noun where it names **permanents** ("those
    creatures"), and None where it names cards in a hand ("those cards"). Two
    readings of one clause and one node, because the question is identical —
    what did an earlier sentence of this effect choose — and the difference is
    only which record answers it. Carried rather than dropped: the noun
    restates what the earlier sentence named, and a restatement checked is a
    restatement, where one taken on trust is a loop over whatever that sentence
    happened to record.
    """
    subject: "ObjectFilter | None" = None


@dataclass(frozen=True)
class EachLifeLost:
    """"**for each 1 life you lost**, sacrifice a permanent …" (Oath of
    Lim-Dûl.)

    An iterator that is a *count* rather than a set: the loop has no objects,
    only a number, and the number is the firing event's — the life the
    state-based sweep measured leaving that seat. Its own node beside the three
    "this way" sets above for the reason they are three nodes: what a loop
    repeats over decides where the number comes from, and reading a count as a
    set would walk an empty board.

    The printed unit is required to be 1 and carried anyway: "for each **2**
    life you lost" would be half as many repetitions, and a production that
    dropped the number would run the wrong count while reporting supported.
    """
    per: int = 1


@dataclass(frozen=True)
class EachShortOfThisWay:
    """"**For each card less than two a player draws this way**, that player
    gains 2 life." (Truce.)

    :class:`EachLifeLost`'s twin, and a count for its reason — the loop has no
    objects, only a number. Two things make it a separate node rather than a
    field on that one. The number is a **shortfall**, the printed base minus
    what an earlier step of this same effect recorded, so a reader that took it
    for a tally would repeat the effect for every card *drawn* instead of for
    every card not drawn; and it is **one number per seat**, which is why the
    sentence names "a player" and then "that player" — the loop it lowers to is
    a loop over seats with this inside it.

    ``record`` is the resolution-scratchpad key the count is read from, resolved
    by the parse from the printed noun and verb *together* — exactly as
    ``amounts._THIS_WAY_COUNTS`` resolves the pair it reads, and for its reason:
    "for each card less than two a player *discards* this way" is a sentence
    about a different record, and reading one for the other is a number nobody
    printed. Carried resolved rather than as the two words, because that is what
    :class:`ThatMuch` does with the same question and what keeps the lowering
    from needing a second copy of the table.
    """
    record: str
    base: int


@dataclass(frozen=True)
class CountersPlacedThisWay:
    """"**For each +1/+1 counter you put on a creature this way,** remove a
    +1/+1 counter from that creature at the beginning of the next cleanup step."
    (Bounty of the Hunt.)

    The fourth "this way" window, beside :class:`DiedThisWay`,
    :class:`ExiledThisWay` and :class:`TappedThisWay`, and the same distinction
    they draw: this names exactly the counters an earlier sentence of *this same
    effect* placed, and no read of the board can answer it — a creature's +1/+1
    counters may have come from anywhere.

    It differs from those three in what it iterates. They walk a **set** of
    objects; this walks the *counters*, so a creature given two is named twice
    and the sentence runs twice about it. That is the printed reading — the
    delayed ability is created once per counter (CR 603.7) — and it is what
    makes the removal come out even with the placement.

    ``counter`` is the printed kind, checked against the placement rather than
    assumed: a card placing one kind and removing another is a sentence this
    would otherwise run over the wrong record.

    The lowering refuses it without a producer, as every back-reference in this
    grammar is refused.
    """
    counter: str


@dataclass(frozen=True)
class EachAdditionalCostPaid:
    """"**For each additional {1}{R} you paid**, destroy another target
    artifact." (Primitive Justice, Taste of Paradise.)

    :class:`EachLifeLost`'s third sibling and a *count* for its reason — the
    loop has no objects, only a number. What makes it its own node rather than
    a field on that one is where the number comes from: this is an announcement
    the **caster** made as the spell was cast (CR 601.2b), carried on the stack
    item because the mana pool it was paid out of is empty by the time the
    spell resolves (CR 500.4). Neither the board nor the firing event can
    answer it.

    *symbols* is which offer, because a single sentence may print two of them
    independently ("{1}{R} and/or {1}{G}") and the two counts are read back
    separately. Carried **as printed** and turned into the recorded key by one
    function (``lowering/loops.optional_cost_key``), so the sentence that spends
    the count and the payment that made it name the same offer.
    """
    symbols: str


@dataclass(frozen=True)
class AdditionalCostWasPaid:
    """"**If this spell's additional cost was paid**, …" (Undergrowth.)

    The boolean half of :class:`EachAdditionalCostPaid`: CR 601.2b's optional
    additional cost asked about at all rather than counted. A condition of its
    own rather than a comparison against that count, because the sentence is
    about *the* additional cost — the card prints one and does not name it — and
    a node carrying no symbols is what says so.

    Lowering resolves "the" to the one offer the card prints and refuses when
    there is more than one, which is the only reading a bare "this spell's
    additional cost" has.
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
class InABlockSinceLastUpkeep:
    """"if **it has blocked or been blocked since your last upkeep**" (Wiitigo).

    A history like :class:`DealtDamageThisTurn`, asked of the ability's own
    source and over a window no board read can answer: the combat it asks about
    may have been an opponent's, two turns of blockers ago, and every
    battlefield record of it is swept at cleanup. So the declare-blockers step
    stamps a seat-turn ordinal (``turn_state.record_block_involvement``) and
    this reads it.

    Both halves of CR 509.1a's relation are one condition, not two: the sentence
    joins them with "or" and the stamp is written for both sides of every
    declared block, so a node with a "which side" field would have a value no
    printed sentence distinguishes.
    """
    subject: "TargetSpec"


@dataclass(frozen=True)
class AttackedOrBlockedThisCombat:
    """"if this creature **attacked or blocked this combat**" (Clockwork Beast,
    Avian, Steed and Swarm; Kjeldoran Home Guard).

    :class:`InABlockSinceLastUpkeep`'s sibling over the narrowest window there
    is, and a history for the same reason: by the time an end-of-combat trigger
    resolves, this combat's record has been swept, so the answer is frozen when
    the trigger is announced (CR 603.10) and read back from the trigger's
    context. Both halves of the "or" are one condition, as they are there —
    every printed sentence joins them, and the two records the fire site reads
    are the attack map and the block mark.
    """
    subject: "TargetSpec"


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
    #: "If it **isn't** a land card" (Wand of Ith) — the same test read the
    #: other way. A flag rather than a second node, because what changes is the
    #: answer and not the question: both spellings read the same record through
    #: the same filter, and two nodes would be two places to keep that reading
    #: in step.
    negated: bool = False


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
class DestroyedTargetWas:
    """"Destroy target land. **If that land was a snow land**, …" (Icequake,
    Thermokarst.)

    A back-reference to the permanent an earlier step of this same effect
    destroyed, read as last-known information (CR 608.2h): by the time the
    condition is asked the land is a card in a graveyard, so the answer is what
    it was on the battlefield and no read of the board can give it.

    Its own node beside :class:`ItWas`, which asks the same tense of a *card* by
    its printed type line. This one asks a **permanent** a whole noun phrase —
    "a snow land" is a supertype and a card type together, and the object it is
    asked of had computed characteristics right up until it left (CR 613.1). One
    node carrying a tense flag would have to branch on it at every reader.

    The noun the sentence repeats ("that **land**") is not carried: it is the
    self-same object the destroy chose, and lowering refuses the condition
    outright when no step in front of it destroyed anything.
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
class CostObjectWas:
    """"…**if the exiled creature was a Thrull**" (Soul Exchange); "…**if the
    sacrificed creature was a Thrull**" (Ebon Praetor).

    A question about what the spell's or ability's own **cost** ate, not about
    anything a step of the effect touched: CR 601.2h pays the cost before the
    object is on the stack, so by resolution the permanent is a memory the
    payment path recorded (``sacrificed_for_cost`` / ``exiled_for_cost``) and
    CR 608.2h's last-known information is the only answer there is.

    The *fact* this carries is **which payment channel the phrase names**, and
    it has one spelling here — ``channel`` — because "the sacrificed creature"
    and "the exiled creature" are one printed template with the verb changed.
    Two nodes, or two fields meaning the same thing under two names, would be
    two readings of one sentence.

    Beside :class:`DiscardedCardWas` rather than a widening of it: that one
    names the *discard* channel, and one node per named producer is what keeps
    a back-reference from reading whatever record happens to be lying around.
    The whole noun phrase is carried rather than a printed type line, because
    what is asked here is a creature's **subtype** and lowering is what checks
    the matcher can test it.
    """

    channel: str
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


@dataclass(frozen=True)
class SourceAbilityActivations:
    """"**If this ability has been activated four or more times this turn**,
    sacrifice this creature at the beginning of the next end step." (Farrelite
    Priest, Initiates of the Ebon Hand.)

    How often the ability *reading this clause* has been activated in the
    current turn, compared against a printed number. Its own condition rather
    than a spelling of :class:`CountedNumber`, because what it counts is not on
    any board: it is a per-turn ledger the activation path keeps on the
    permanent, which is the same ledger CR 602.5's "Activate no more than twice
    each turn" is refused against (``engine/activation_restrictions.py``).

    ``count`` and ``comparison`` are the printed words and nothing else, so the
    card that prints "twice or more" or "exactly three times" extends this
    production rather than needing a second node.

    One honest limitation, recorded here because the two cards printing the
    clause cannot show it: the ledger is kept **per permanent**, not per
    printed line, so a permanent carrying a second capped ability would have
    both counted together. Neither of these creatures has one — each prints a
    single activated ability — and the fix, if a card ever prints two, is the
    per-line ledger ``ONCE_ONLY_TALLY_MARK`` already keeps beside it rather
    than a second counter here.
    """

    count: int
    #: "four **or more**" is ``"at_least"``; a printed exact count would be
    #: ``"exactly"``. The field exists for :class:`SourceCounterCount`'s reason
    #: — the question is one question and the comparison is what varies.
    comparison: str = "at_least"


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


Condition = Union[
    EveryOf, CoinFlipResult, Controls, CountedNumber, DestroyedThisWay,
    DestroyedTargetWas,
    DiscardedCardWas,
    CostObjectWas,
    IsState, StartedTheTurnState, DiedThisTurn, DamagedBySourceDiedThisTurn,
    ItIsColor, ObjectHasKeyword,
    HadPlus1Counter, ItWas,
    AttackersAimedAtYou, EnteredFrom, ItHappened, RevealedCardIs,
    LifeGainedThisTurn, PaidCost, AdditionalCostWasPaid,
    RawCondition, ReturnedToHandThisTurn,
    DealtDamageThisTurn, SubjectCharacteristicIs, BlockersOfBoundCreature,
    SourceExiledWithCounter, SourceCounterCount, SourceAbilityActivations,
    OnBattlefield,
    AttackedOrBlockedThisCombat,
    SelfInGraveyardWithCardsAbove,
    TurnIsYours,
]
