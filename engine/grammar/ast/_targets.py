"""What a sentence **points at**: the quantified reference a clause targets.

Split from ``_references`` when that module crossed the 1,000-line guard, along
the cut its own docstring already drew — "what a noun phrase *describes* against
what it points at", the same boundary Antiquities used when ``nouns.py`` split
into ``references.py``. ``_references`` keeps the describing half
(:class:`ObjectFilter` and the comparisons it is bounded by); this is the
pointing half, and it is the half whose fields grow with the *announcement*
rules (CR 601.2b–c) rather than with the vocabulary of noun phrases.

One class, because there is one thing a sentence can point at. ``_core``
re-exports it, so ``from ._core import TargetSpec`` and ``ast.TargetSpec`` both
still resolve and no importer outside this package changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._references import ObjectFilter

if TYPE_CHECKING:  # ``count_amount``'s annotation only.
    from ._core import Amount


@dataclass(frozen=True)
class TargetSpec:
    """A quantified object reference: "target creature", "each creature with
    flying", "up to two creatures", "any target"."""
    quantifier: str            # target | each | all | up_to | any_target | this | it | a
    filter: ObjectFilter = field(default_factory=ObjectFilter)
    count: int = 1
    # "**X** target lands" (Candelabra of Tawnos). The count is the announced X
    # (CR 601.2b), so it is not a number until the ability is activated —
    # recorded as a fact rather than baked into `count`, because a count of 0
    # and a count that is *not yet known* are different things and a picker
    # shown 0 would offer nothing.
    count_from_x: bool = False
    # "**For each land target player controls in excess of the number you
    # control**, choose a land that player controls." (Equipoise.) How many,
    # said by a clause in front of the noun phrase rather than by a printed
    # number — so it is an :class:`Amount` the resolution computes, beside
    # ``count_from_x`` above and for that field's reason: a count of 0 and a
    # count that is *not yet known* are different things, and folding this into
    # ``count`` would need a number nobody can write down at parse time.
    #
    # It is the whole count, never a bound on one: the clause says how many are
    # chosen, and a reading that treated it as a ceiling would let a seat choose
    # fewer than the card makes them.
    count_amount: "Amount | None" = None
    # "another target creature" (Garruk, Savage Herald's −2): a second chosen
    # object that must differ from the sentence's earlier choice — not from the
    # ability's source, which is what the filter's other_than_source says.
    distinct_from_prior: bool = False
    # "Choose two target creatures **controlled by the same opponent**."
    # (Retribution.) A relation *between* the targets rather than a property of
    # any one of them, which is why it is here and not on the filter: no matcher
    # asked about a single permanent can answer "is this the same seat as the
    # other target's", and a filter key that could not be tested would be
    # dropped by the gate that reads them. The filter still carries
    # ``controller="opponent"`` — that half *is* per-object — so what this adds
    # is only the "same" (CR 601.2c: an announcement naming two opponents'
    # creatures is illegal).
    same_controller: bool = False
    # Whether the word "target" was printed. The quantifier alone cannot say:
    # "up to two target creatures" (Read the Tides — chosen at cast, CR 601.2c)
    # and "up to four lands" (Rewind — chosen on resolution, no targets at all)
    # both read as ``up_to``, and the two reach entirely different machinery.
    # The parser used to consume the word and discard the fact, which is the
    # round-15 finding this field closes.
    targeted: bool = False
    # "among **one or two** target creatures" (Contagion; Bounty of the Hunt
    # prints "one, two, or three"). CR 601.2c: a spell with a variable number
    # of targets has that number announced with the targets, and the printed
    # enumeration is its *ceiling* — so this is the bound the announcement is
    # checked against, not a count the game picks. ``None`` is the unbounded
    # spelling ("among any number of"), which is a different sentence and not
    # a bound of infinity: only a production that read an enumeration sets
    # this, and only the lowering written for that production reads it.
    max_count: int | None = None
