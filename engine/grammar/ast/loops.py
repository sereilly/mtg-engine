"""What a loop repeats over when the set is a **record** of something already done.

"For each creature **exiled this way**" (Martyr's Cry), "for each of **those
cards**" (Sylvan Library), "for each **1 life you lost**" (Oath of Lim-Dûl),
"for each **additional {1}{R} you paid**" (Primitive Justice). Every node here
is the ``iterator`` of a ``ForEach`` and is never anything else: the one
production that builds them is ``sentence_clauses._parse_leading_for_each``
(with ``_parse_leading_controller_of_each``, the same loop in Seeds of
Innocence's word order), ``leading_iteration`` wraps whatever those return in a
``ForEach``, and ``statement_dispatch`` lowers each through its ``ForEach`` arm
— six into ``lowering/loops.py``, and the exiled and tapped sets into
``lowering/exile.py`` and ``lowering/tapping.py``, beside the steps that wrote
them.

The node-side mirror of ``lowering/loops.py``, and it carries that module's name
for that module's reason: its question is "what is the set?", and these are the
answers read off a record rather than off the board or the seats. The other
answers are vocabulary — an ``ObjectFilter`` and a ``PlayerRef`` from ``_core``
— and the two record sets that are also *asked* stay in ``records`` (below).

Pre-split out of ``records`` at the Phase 0 before Torment, when that module sat
eleven lines under the thousand-line guard. ``records`` is "conditions that ask
what already **happened**" — a record read as a *question* — and
``grammar/records.py`` reads one as a *quantity*. A record read as a **set to
repeat over** is a third reading, and it had ridden along in ``records`` since
Mirage split that module out of ``conditions`` with every node that read a
record. The code had drawn the line already: no ``Conditional`` holds any of
these eight, ``lowering/_record_conditions`` lowers none of them, and each sat in
``ast.Condition`` only because the union guard asks that union to name every
node ``records`` defines. ``ForEach.iterator`` names them now. It had drifted two
behind — ``TappedThisWay`` and ``EachShortOfThisWay`` were lowered as iterators
and named by no union but ``Condition`` — and
``test_the_for_each_iterator_names_every_loop_node`` holds it to this module the
way the condition guard holds ``Condition`` to ``conditions`` and ``records``.

Two loop sets stayed, and the reason is the line: ``DiedThisTurn`` and
``DiedThisWay`` are iterators too, but each is also asked. "If a creature died
this turn" (Osai Vultures) is a condition ``_record_conditions`` lowers, and "if
a white creature dies this way" (Cinder Cloud) is a ``Conditional`` that
``record_conditions`` builds and ``lowering/sequences`` rewrites into this loop.
A node a ``Conditional`` holds is a condition, so it is in ``records``, where the
union guard asks for it.

A floor beside ``records`` and ``costs``, not a family: there is no
``effects/loops.py`` for it to be a family of, ``statements`` — the roof that
defines ``ForEach`` — is its one reader, and it reads ``_core`` alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import ObjectFilter


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
    "this way" sets (:class:`DiedThisWay` in ``records``, :class:`ExiledThisWay`
    and :class:`TappedThisWay` above) for the reason they are three nodes: what
    a loop repeats over decides where the number comes from, and reading a
    count as a set would walk an empty board.

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
class CountersRemovedThisWay:
    """"**For each delay counter removed this way,** you lose 1 life unless you
    pay {1}{W}." (Delaying Shield.)

    :class:`EachLifeLost`'s shape — an iterator that is a *number*, not a set —
    with the number read off this resolution's scratchpad: how many counters
    the sentence in front of it took off ("remove all delay counters from this
    enchantment"). One repetition per counter, so each is its own offer and
    its own payment.

    Not :class:`CountersPlacedThisWay`, which walks the *objects* a placement
    put counters on and binds each one; nothing is bound here — the body means
    what it would mean written once, run again.

    ``counter`` is the printed kind. The lowering refuses the loop without a
    producer, as every back-reference in this grammar is refused.
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
    spell resolves (CR 500.5). Neither the board nor the firing event can
    answer it.

    *symbols* is which offer, because a single sentence may print two of them
    independently ("{1}{R} and/or {1}{G}") and the two counts are read back
    separately. Carried **as printed** and turned into the recorded key by one
    function (``lowering/_cost_records.optional_cost_key``), so the sentence
    that spends the count and the payment that made it name the same offer.
    """
    symbols: str
