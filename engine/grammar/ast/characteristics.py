"""What a permanent *is*: P/T, keywords, colour, printed text, counters.

CR 613 layers 5, 6 and 7 — pump and base-P/T setting, keyword grants and
losses, colour replacement, the printed-text swaps, and counters.

Counters are here rather than with the board for the reason the parsing side
puts them here: what a counter does is change a characteristic, and where it
sits is incidental.

Each of these carries a `Duration`, and it is a field rather than an assumption:
an effect with no duration is a continuous one, which lowering routes somewhere
else entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import (
    Amount,
    Duration,
    Fixed,
    Recipient,
)


@dataclass(frozen=True)
class Pump:
    subject: Recipient
    power: Amount
    toughness: Amount
    duration: Duration = field(default_factory=Duration)
    # "gets -2/-2": the sign is carried here rather than in the Amount so
    # "+X/+0" and "-X/-0" share one quantity vocabulary.
    power_negative: bool = False
    toughness_negative: bool = False
    # "gets -X/-X …, where X is the number of cards in your graveyard"
    # (Liliana, Waker of the Dead) — what the Var in power/toughness counts.
    # None when X is announced (a cast cost) rather than defined by the text.
    x_definition: Amount | None = None
    # "gets +1/+1 until end of turn **for each creature tapped this way**"
    # (Siege Striker). A back-reference to what an earlier sentence of the same
    # effect did, not a count of the board — the creatures it counts are the ones
    # that sentence tapped, and a board count would include every creature that
    # was already tapped. A flag rather than an `ObjectFilter`, because the set
    # is not describable: only the sentence in front of it knows which ones.
    per_each_tapped_this_way: bool = False


@dataclass(frozen=True)
class SetBasePT:
    subject: Recipient
    power: Amount | None
    toughness: Amount | None
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class GainKeyword:
    subject: Recipient
    keywords: tuple[str, ...]
    duration: Duration = field(default_factory=Duration)
    # "gains **your choice of** deathtouch or lifelink" (Alchemist's Gift) — the
    # keywords are *alternatives*, not a list. Same words as "gains deathtouch
    # and lifelink" once the conjunction is read, so the difference has to be
    # recorded here or the card grants both.
    choose_one: bool = False


@dataclass(frozen=True)
class LoseKeyword:
    subject: Recipient
    keywords: tuple[str, ...]
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class PutCounter:
    subject: Recipient
    counter: str = "+1/+1"
    count: Amount = field(default_factory=lambda: Fixed(1))
    up_to: bool = False
    # "…, then double the number of +1/+1 counters on that creature."
    # (Invigorating Surge.) A rider rather than a second statement: "that
    # creature" is the one this placement just chose, and reading it as its own
    # sentence would leave the doubling looking for a target nobody picked.
    then_double: bool = False


@dataclass(frozen=True)
class DoublePower:
    """``Double the power of <subject> until end of turn.`` (Unleash Fury.)

    Its own node rather than a :class:`Pump` whose amount is "the subject's
    power": a pump's amount is fixed when the effect is created, and this one
    reads the power *at resolution*. Writing it as a Pump would need an Amount
    that means "ask the board later", which is a bigger idea than one card
    needs — and the two would then be indistinguishable in the IR.
    """
    subject: Recipient
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class RemoveCounter:
    subject: Recipient
    counter: str = "+1/+1"
    count: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class ChangeText:
    """``Change the text of <subject> by replacing all instances of one <mode>
    with another.`` (CR 612 — Magical Hack, Sleight of Mind.)

    *mode* names which vocabulary is swapped, because that is the whole
    difference between the two printings and the only thing the handler reads.
    It is a closed set: a wording naming some other vocabulary is a text change
    the engine's substitution does not implement, and must fail to parse rather
    than arrive here as a mode nothing knows.
    """

    subject: Recipient
    mode: str


@dataclass(frozen=True)
class BecomeCreature:
    """"…becomes a 3/3 Sphinx creature with flying **in addition to its other
    types** until end of turn." (Riddleform, CR 205.1b / CR 613 layer 4.)

    An *addition*, not a replacement, which is the difference between this and
    :class:`BecomeColor` below and the difference the printed words state: the
    enchantment is still an enchantment while it is a creature, so anything that
    destroys enchantments still reaches it. The phrase is required rather than
    defaulted, because a card that replaced its types would be a different card
    and the words are the only thing that says which.

    ``until_end_of_turn`` is likewise required by the production: without a
    duration this is a permanent animation, and the two differ by everything
    that happens after the turn ends.
    """
    subject: Recipient
    power: int
    toughness: int
    subtypes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class BecomeColor:
    """"Target spell or permanent becomes red." (the Lace cycle, CR 105.)

    A colour *replacement*, not an addition — the object becomes that colour
    instead of its own. Mana symbols are unaffected, which is reminder text the
    lexer already strips.
    """
    subject: Recipient
    color: str
