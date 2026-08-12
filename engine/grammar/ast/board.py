"""The battlefield: destruction, bouncing, tapping, control, sacrifice.

Destroy, sacrifice (both the plain effect and the fused pay-or-sacrifice),
exile, control changes, tap/untap, regeneration and return-to-zone.

Two of these keep a rider that looks droppable and is not: `Destroy.delay` (a
delayed triggered ability, CR 603.7 — not this effect with a flag) and
`Exile.duration` (a temporary exile has to give the card back, CR 406.1). Both
are recorded here so lowering picks a different handler rather than the same one
with a field it might ignore.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import (
    Duration,
    ManaCost,
    PlayerRef,
    Recipient,
    Zone,
)


@dataclass(frozen=True)
class Destroy:
    subject: Recipient
    no_regen: bool = False
    # When the destruction happens, if not on resolution: "…at end of combat"
    # is a delayed triggered ability (CR 603.7), not this effect with a rider.
    # Carried here rather than as its own node because the subject, the
    # regeneration clause and the timing are one sentence — but lowering treats
    # a delayed destroy as a *different* handler, never the immediate one with a
    # flag it might ignore.
    delay: str = ""


@dataclass(frozen=True)
class Sacrifice:
    player: PlayerRef
    subject: Recipient


@dataclass(frozen=True)
class Exile:
    """``Exile <subject> [duration]``.

    The duration is what separates two different handlers rather than a
    decoration: a bare exile is permanent, and "until end of turn" is a
    temporary exile that has to return the card (CR 406.1, 400.7). Recording it
    is what stops the rider being dropped onto the permanent reading.
    """
    subject: Recipient
    duration: Duration = field(default_factory=lambda: Duration())


@dataclass(frozen=True)
class GainControl:
    """``Gain control of <subject> for as long as <duration>.`` (CR 613 layer 2.)

    *duration* is what ends the control change, and it is required rather than
    defaulting to "permanently": an untimed steal (Control Magic) and a linked
    one (Aladdin) revert under completely different circumstances, and a
    production that let the clause be absent would also let it be *deleted*
    with no change to what was lowered.
    """

    subject: Recipient
    duration: str


@dataclass(frozen=True)
class Tap:
    subject: Recipient


@dataclass(frozen=True)
class Untap:
    subject: Recipient


@dataclass(frozen=True)
class TapOrUntap:
    """"Tap or untap target artifact, creature, or land." (Twiddle.)

    One effect whose direction its controller picks on resolution, not two
    effects joined by "or": both halves act on the *same* chosen target, so
    modelling it as a ``Conjunction`` of ``Tap`` and ``Untap`` would say the
    permanent is tapped and then untapped.
    """
    subject: Recipient


@dataclass(frozen=True)
class Regenerate:
    subject: Recipient


@dataclass(frozen=True)
class ReturnToZone:
    subject: Recipient
    to: Zone
    from_zone: Zone | None = None
    # "Return target spell or creature to its owner's hand." (Unsubstantiate):
    # the chosen object may be on the stack instead of the battlefield, a
    # union no object filter expresses — so it is a flag on the node.
    also_stack: bool = False


@dataclass(frozen=True)
class PhaseOut:
    """"<subject> phases out." (CR 702.26 — Teferi, Master of Time's −3;
    Teferi, Timeless Voyager's −8 with the can't-phase-in rider.) The subject
    may be one chosen creature or a swept set; the rider is recorded so the
    parse cannot shed it."""
    subject: Recipient
    cant_phase_in_until_your_next_turn: bool = False


@dataclass(frozen=True)
class PutOnLibraryTop:
    """"Put target creature on top of its owner's library." (Teferi, Timeless
    Voyager.) Its own node rather than a ReturnToZone: the destination is a
    *position* in a zone, which Zone cannot say, and collapsing it to
    "library" would lose where in the library the card lands."""
    target: Recipient


@dataclass(frozen=True)
class PutOnLibraryBottom:
    """``Put target card from your graveyard on the bottom of your library.``
    (Epitaph Golem.) The zone the card leaves rides the target's filter, as
    every return does; the bottom is what tells it from :class:`PutOnLibraryTop`."""
    target: Recipient


@dataclass(frozen=True)
class PutOntoBattlefield:
    """"Put up to seven permanent cards from your hand onto the battlefield."
    (Ugin, the Spirit Dragon) / "Put target creature card from a graveyard
    onto the battlefield under your control." (Liliana, Waker of the Dead's
    emblem.) Which zone the cards leave is on the target's filter; the two
    riders are recorded so a wording carrying them cannot shed them."""
    target: Recipient
    under_your_control: bool = False
    gains: tuple[str, ...] = ()


@dataclass(frozen=True)
class SacrificeUnlessPay:
    """"Sacrifice this enchantment unless you pay {W}{W}." (CR 603.)

    Kept fused rather than decomposed into `May(pay) else Sacrifice`, because
    the upkeep dispatcher in engine/phases/upkeep_effects.py is keyed on
    (trigger condition, instruction kind) pairs whose handlers implement the
    whole pay-or-else prompt. A decomposed form has no handler and would
    compile cleanly while doing nothing.
    """
    subject: Recipient
    cost: ManaCost
