"""Conditions that ask what already **happened**, not what the board looks like.

The parse-side mirror of ``lowering/_records.py`` and the sibling of
``grammar/records.py``, and it carries their name for their reason: a handler
writes a value into the resolution scratchpad (or the turn writes one into the
game) and a later sentence reads it back. ``records.py`` one package up reads
such a record as a **quantity** ("as many cards as they discarded this way");
this module reads one as a **question** ("if you do", "if a white creature died
this way", "if you've gained 3 or more life this turn").

Split out of ``conditions`` when that module crossed the thousand-line guard.
The boundary is not the size: what stays there is a condition answered by
looking at the game *now* — a board count, a zone's height, a life total, a
permanent's characteristics, whose turn it is — and what moved is a condition
answered by looking at a record of something that has already been done. The
distinction is the one ``lowering/conditions.py`` had already been writing in
prose card by card ("that one asks the board and this one reads the
scratchpad"), which is the sign that the seam was there before the guard found
it.

Re-exported flat from ``ast/__init__``, like every other module here, so no
caller learns which side of the cut a node landed on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import Comparison, ObjectFilter, PlayerRef, TargetSpec
from .costs import Cost

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
class ChosenNameMilledThisWay:
    """``if a card with the chosen name was milled this way`` (Foreshadow).

    Two records in one question: the name a "choose a card name" step recorded,
    and the cards a mill step of the same resolution put into a graveyard. Its
    own node rather than a filter on :class:`MilledThisWay` beside it, which
    asks what *kind* of card was milled — a filter cannot carry "the name
    somebody chose a moment ago", and ``ObjectFilter.named`` is a printed
    literal.
    """


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
class SacrificedThisWay:
    """"**If you sacrifice a snow Forest this way,** …" (Gargantuan Gorilla),
    "**If you sacrifice an Island this way,** …" (Serendib Djinn).

    The yes/no reading of "this way", asked of a *narrower* noun phrase than
    the sacrifice in front of it printed: the effect said "a Forest" and this
    asks whether the one that went was a **snow** Forest. That narrowing is the
    whole reason it is not :class:`ItHappened` — the offer can be taken and the
    branch still not run.

    Its own node rather than a filter field on ``ItHappened`` for
    :class:`ExiledThisWay`'s reason one direction over: what tells these apart
    is which earlier step recorded the set, and ``ItHappened`` deliberately
    carries no field because "which step" is always the one immediately before.
    This one has to describe what it is looking for, which means it has to know
    it is looking at a sacrifice.

    The comparison is against the **cards**, not the permanents: by the time
    this is asked the sacrifice has put them in a graveyard and they are
    different objects (CR 400.7, CR 608.2h), so the record is written as it
    happens and read back here.

    Refused without a producer like every other back-reference in this file.
    """
    filter: ObjectFilter = field(default_factory=ObjectFilter)
@dataclass(frozen=True)
class DiscardedThisWay:
    """"Target player discards a card unless they put a card from their hand on
    top of their library. **If that player discards a card this way,** …"
    (Tainted Specter.)

    The yes/no reading of "this way" over a *discard*, and a sibling of
    :class:`SacrificedThisWay` one zone over. It is not :class:`ItHappened`: the
    step in front of it is an **offer**, so what happened is not "the previous
    instruction ran" but "the offer was declined **and** the discard the decline
    branch performs actually took a card". A hand that was empty when the offer
    was made can neither put a card back nor discard one, and the sentence
    behind it must not fire for that player.

    Carries no field. Which discard it means is always the one the sentence in
    front of it printed, and the lowering refuses the words without a step of
    this effect that records a discard — the standing rule for every
    back-reference here, because an unwritten record reads as zero and the
    branch would silently never run.
    """
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
class HadNamedCounter:
    """"exile it **if it had a death counter on it**" (Bogardan Phoenix,
    CR 603.4).

    :class:`HadPlus1Counter`'s twin for a counter with no rules meaning of its
    own (CR 122.3) — and a separate node rather than a word on that one,
    because they read **two different records**. A P/T counter lives in
    ``engine/pt.py``'s persistent channel and the death event freezes it as one
    bool; a named counter lives in ``engine/named_counters.py``'s per-word
    store, and freezing that is a map. "A second producer means a second key,
    never this one widened" is the rule the pronoun conditions already state,
    and it applies a level up: two records, two nodes, two payload kinds.

    Last-known information either way (CR 603.10): the creature is in a
    graveyard by the time the trigger resolves, and a graveyard card has no
    counters at all.
    """
    counter: str


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
    a counter not being there to remove (CR 609.3: removing a counter that
    is not on the object is impossible, so the removal does as much as it
    can, which is nothing).

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
