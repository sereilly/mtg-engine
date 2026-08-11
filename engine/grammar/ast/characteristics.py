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
class BecomeColor:
    """"Target spell or permanent becomes red." (the Lace cycle, CR 105.)

    A colour *replacement*, not an addition — the object becomes that colour
    instead of its own. Mana symbols are unaffected, which is reminder text the
    lexer already strips.
    """
    subject: Recipient
    color: str
