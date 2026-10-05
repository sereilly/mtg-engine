"""One printed line: the ability-line nodes, and the union that closes them.

``parse_line`` reads one oracle line and returns exactly one of these, so this
is the type of ``grammar/parser.py`` the way ``statements`` is the type of
``grammar/statements.py`` — the *line* layer over the *sentence* layer. It
holds:

* the seven line nodes (`SpellEffectLine`, `TriggeredAbilityNode`,
  `ActivatedAbilityNode`, `StaticAbilityNode`, `KeywordLine`, `RegistryLine`,
  `DerivedLine`) and `AbilityNode`, the union over them;
* the three parts only a line is built from: `TriggerEvent` (the event half of
  a triggered ability), `ActivationRestriction` (the clause after an activated
  one) and `KeywordInstance` (one keyword of a keyword line).

Pre-split out of ``statements`` at Invasion's Phase 0, when that module sat 25
lines under the thousand-line guard with a wave about to open on it. The seam
is the one both other packages had already cut: the parse side keeps
``statements`` (one whole sentence) below ``parser`` (one printed line), and
the lowering side keeps ``statement_dispatch`` below ``lower``. The AST roof was
the one place the two layers still shared a file, under two banners.

**The edge between the halves is one name wide.** Four line nodes carry a
`Statement` and nothing else here reads that module; nothing in ``statements``
names a line node at all. That is also what the written reason for the old
arrangement got wrong: the layering guard said `AbilityNode` was, like
`Effect`, a union "over every family". It never was — it is a union over the
seven classes in this file, and it sees the families only through the
`Statement` those classes hold. So only ``statements`` has to import the
families, and this module imports ``statements``: a second storey on the roof
rather than a second roof.

It is the half that does **not** grow with the pool, and that is the point of
moving it rather than a reason against. These nodes are 22 lines longer than
they were the day the AST became a package, where the statement nodes below
them are 397 longer, the family imports 189 and the `Effect` union 75 — a new
template adds a leaf to `Effect` or a field to `May`, almost never a kind of
line. What cannot leave the roof is exactly what grows (the union has to be
written where every family is visible), so the room is made by lifting out the
part that never needed to be there.

Nothing may import this module from inside the package but ``__init__``, which
re-exports it flat like every other: callers write ``ast.TriggeredAbilityNode``
and never learn which storey a node is on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from ._core import Duration, ObjectFilter, PlayerRef
from .conditions import Condition
from .costs import Cost
from .statements import Statement


@dataclass(frozen=True)
class TriggerEvent:
    """The event half of a triggered ability. ``kind`` intentionally reuses the
    legacy trigger-kind strings ("creature_dies", "upkeep_self", …) so the 23
    existing ``condition_kinds=`` dispatch sites keep working unchanged while
    the grammar migration is in flight."""
    kind: str
    word: str = "whenever"        # whenever | when | at
    subject: ObjectFilter | PlayerRef | None = None
    #: Noun phrases the condition carries **beyond** its subject, each under the
    #: stem ``engine/oracle.py``'s pattern table gives its ``<stem>_subject``
    #: group — "…that doesn't share a color with **a creature you control**"
    #: (Invoke Prejudice) is ``("unshared_color", <that phrase>)``.
    #:
    #: A trigger condition is read twice, once by each front end (the table
    #: supplies the *condition*, the grammar the *effect*), and a phrase only
    #: one of them sees is a card whose two halves watch different sets. The
    #: subject alone could not express these: the set on the far side of a
    #: comparison is a different object from the one the trigger fires on.
    #: Paired by stem in ``test_a_narrowed_trigger_reads_the_same_subject_on_both_sides``.
    narrowings: tuple[tuple[str, ObjectFilter], ...] = ()


@dataclass(frozen=True)
class KeywordInstance:
    name: str
    argument: str | None = None   # "protection from red", "landwalk: island"


@dataclass(frozen=True)
class ActivationRestriction:
    """"Activate only during your upkeep." / "Any player may activate this ability.\""""
    text: str
    timing: str | None = None
    any_player: bool = False


@dataclass(frozen=True)
class SpellEffectLine:
    """A one-shot effect line: an instant/sorcery's text, or the effect half of
    a triggered or activated ability."""
    statement: Statement


@dataclass(frozen=True)
class TriggeredAbilityNode:
    event: TriggerEvent
    statement: Statement
    # CR 603.4 intervening-if: checked both when the trigger would fire and
    # again on resolution. Modeled as a field rather than dropped — the legacy
    # compiler silently discarded these, so conditional triggers always fired.
    intervening_if: Condition | None = None


@dataclass(frozen=True)
class ActivatedAbilityNode:
    costs: tuple[Cost, ...]
    statement: Statement
    restriction: ActivationRestriction | None = None


@dataclass(frozen=True)
class StaticAbilityNode:
    """A continuous effect. Lowering for most static shapes waits on the CR 613
    layers engine, so these are commonly "parsed but not lowered"."""
    effect: Statement
    condition: Condition | None = None
    duration: Duration = field(default_factory=Duration)
    #: "Enchanted creature gets +2/+1 as long as it's black. **Otherwise, it
    #: gets -1/-2.**" (Phyrexian Boon.) The other arm of ``condition``, and a
    #: *continuous* one: both arms apply exactly while their half of the
    #: condition holds, so neither is the one-shot ``Conditional.otherwise``
    #: that ``control_flow._attach_otherwise`` builds — reading it as that would
    #: test the colour once and keep whichever delta it found.
    #:
    #: Meaningless without ``condition``, which is what it is the complement of;
    #: the production that fills it only reaches this line after one parsed.
    otherwise: Statement | None = None
    #: "Enchanted creature gets +3/+3 **unless** it shares a color with the
    #: most common color among all permanents …" (Heroic Defiance.) The printed
    #: word that puts the effect on the condition's *false* side, and a flag
    #: for ``Conditional.negated``'s reason one module over: negation is not
    #: something every condition node carries, so the lowering moves the effect
    #: to the complement arm instead — which is the arm ``otherwise`` already
    #: is, and why the two are never set together.
    #:
    #: Continuous, like everything on this node: the bonus is there exactly
    #: while the condition is false, re-asked on every recompute (CR 611.3b).
    unless: bool = False


@dataclass(frozen=True)
class KeywordLine:
    keywords: tuple[KeywordInstance, ...]


@dataclass(frozen=True)
class RegistryLine:
    """A line whose behaviour is implemented by a text-keyed sidecar registry
    rather than by any ``OracleInstruction``.

    "Players skip their untap steps.", "Cast this spell only during the declare
    blockers step.", "If you would gain life, draw that many cards instead." —
    none of these describe a one-shot effect the stack could resolve. They are
    read straight off the card's oracle text by the untap step, the cast-timing
    gate and the CR 614 replacement interceptors respectively. There is nothing
    for the compiler to store and nothing for a handler to run.

    Like :class:`KeywordLine`, this node lowers to zero instructions, which is
    the whole point: it says "accounted for, elsewhere" instead of leaving the
    line in the backlog under a misleading "unrecognized effect verb".

    ``registry`` names the implementing module (``engine/grammar/registries.py``
    maps each one to its matcher). ``text`` is the line **verbatim** — the
    replacement interceptors self-select by looking for exactly this string in
    ``permanent.card.oracle_text``, so normalizing it here would be a way to
    quietly unhook Lich, Library of Leng and Ali from Cairo.
    """

    registry: str
    text: str


@dataclass(frozen=True)
class DerivedLine:
    """A line whose instruction a derivation table computes in full.

    "All Swamps are 1/1 black creatures that are still lands." (Kormus Bell),
    "All Mountains are Plains." (Conversion), Jihad's conditional anthem. Each
    is a template with parameters, and for each of them one engine module
    already derives those parameters from the printed sentence and hands the
    consumer a payload — so a production here would be a second reading of the
    same text, free to disagree with the first.

    Unlike :class:`RegistryLine` this *does* lower, to exactly the instruction
    the table produces (``engine/grammar/derived.py`` names the table for each
    shape). ``table`` labels the node; nothing dispatches on it. ``text`` is the
    line verbatim, and the lowering re-asks the same pure matcher rather than
    carrying an instruction through the AST — one function, two callers, nothing
    to drift.
    """

    table: str
    text: str


# `ModalNode` is deliberately absent: a modal head is printed bare, behind an
# activation cost and behind a trigger condition, so it is a *statement* those
# three line nodes carry (see `ast/stack.py`) rather than a fourth kind of line
# that would need its own copy of the cost and event fields.
AbilityNode = Union[
    SpellEffectLine, TriggeredAbilityNode, ActivatedAbilityNode,
    StaticAbilityNode, KeywordLine, RegistryLine, DerivedLine,
]
