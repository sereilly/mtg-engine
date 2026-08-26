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
class ExileUntilLeavesOrUntaps:
    """Tawnos's Coffin's whole four-sentence effect.

    "Exile target creature and all Auras attached to it. Note the number and
    kind of counters that were on that creature. When this artifact leaves the
    battlefield **or becomes untapped**, return that exiled card to the
    battlefield under its owner's control tapped with the noted number and kind
    of counters on it. If you do, return the other exiled cards to the
    battlefield under their owner's control attached to that permanent."

    One node for the four sentences, in the shape Necromentia's and Idol of
    Endurance's productions already use: none of the four is an effect on its
    own. The note is meaningless without the return that reads it, the return is
    meaningless without the exile that filled the pile, and the reattachment
    names "that permanent" — the creature the *previous* sentence put back. A
    parse that produced four statements would produce three that do nothing.

    Only the subject rides the node. Every other word is required by the
    production, so a card printing the sentence without the counters, without
    the Auras, or with only one of the two return events is a different card and
    keeps failing to parse.
    """

    subject: Recipient


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
class Attach:
    """``Attach <subject> to <host>`` — the keyword action of CR 701.3.

    *subject* is what moves (the Equipment; for every card in the pool it is
    the source itself, "this permanent", because CR 702.6a's expansion of
    equip is the only printing) and *host* is what it is attached to. Two
    recipients rather than one, because "Attach target Equipment you control
    to target creature you control" is a real sentence (Brass Squire) and a
    node with one slot would have to be replaced rather than extended.
    """

    subject: Recipient
    host: Recipient


@dataclass(frozen=True)
class Tap:
    subject: Recipient


@dataclass(frozen=True)
class Untap:
    subject: Recipient


@dataclass(frozen=True)
class DoesntUntapNextStep:
    """``<subject> don't untap during their controller's next untap step.``
    (Frost Breath.)

    Its own node rather than ``Untap`` with a negation flag, because it is not an
    untap that fails to happen: it is a continuous effect with a stated duration
    (CR 611.2a) whose one observable moment is the turn-based action of CR 502.3.
    Nor is it :class:`Tap` with a rider — the two sentences may name creatures on
    two battlefields, and each waits for *its own* controller's step.

    The "next" is part of what the node means, not a decoration. Without it the
    printed sentence is the permanent restriction ``engine/auras.py`` already
    derives for Paralyze, so a production that would still match with the word
    deleted implements a strictly larger effect than the card prints.

    ``count`` is the printed number of steps — "next **two** untap steps"
    (Telekinesis). A number, not a second node: how many of the same turn-based
    action the restriction survives is the one thing that differs, and a card
    printing three would need no code.
    """

    subject: Recipient
    count: int = 1


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
    # "Return this card from your graveyard to the battlefield **tapped**."
    # (Silversmote Ghoul.) CR 110.5b: a permanent enters untapped *unless a spell
    # or ability says otherwise*, and this is the ability saying so. The rider is
    # on the *move*, not a static line on the card, so engine/enter_effects.py
    # cannot claim it — that module answers for a permanent's own printed entry
    # text, which CR 603.6d makes a static ability, and this permanent is not
    # printed with one.
    entering_tapped: bool = False


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
    "library" would lose where in the library the card lands.

    *in_any_order* is Drafna's Restoration's printed rider, which only means
    anything when several cards move at once. Recorded rather than consumed,
    because a card printing it and one not printing it are different cards.
    """
    target: Recipient
    in_any_order: bool = False


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


@dataclass(frozen=True)
class DestroyUnlessPay:
    """"Destroy this creature unless you pay {3}{B}{B}{B}. If this creature is
    destroyed this way, it deals 7 damage to you." (Cosmic Horror.)

    The destroy twin of :class:`SacrificeUnlessPay`, and a separate node rather
    than a flag on it because the two are different events: a sacrifice is not
    a destruction (CR 701.16b), so regeneration and indestructible answer the
    one and not the other — which is exactly what the printed rider is asking
    about.

    ``damage_if_destroyed`` is that rider, folded in by ``riders.py`` from the
    sentence after it. None means the card printed none; the number is data on
    the same node because the consequence is *conditional on the destroy having
    happened*, and only whatever performs the destroy knows whether it did.
    """
    subject: Recipient
    cost: ManaCost
    damage_if_destroyed: int | None = None


@dataclass(frozen=True)
class SacrificeExpansionPermanents:
    """``Each nontoken permanent with a name originally printed in the <Set>
    expansion is sacrificed by its controller.`` (Golgothian Sylex.)

    The set is carried as the code the manifest gives for the printed name, so
    the node says which set rather than which words. City in a Bottle prints the
    same phrase for a continuous ban, and Homelands' Apocalypse Chime is this
    exact card for another set — which is why the phrase is a production and not
    a name-keyed entry.
    """
    set_code: str


@dataclass(frozen=True)
class ShuffleGraveyardIntoLibrary:
    """``Shuffle your graveyard into your library.`` (Feldon's Cane.)

    Its own node rather than a `ReturnToZone` with a zone pair: this moves a
    *whole zone* rather than any object a filter could name, and shuffling is
    part of the move rather than a rider on it (CR 701.19).
    """
    whose: PlayerRef


@dataclass(frozen=True)
class ShuffleHandIntoLibrary:
    """``Each player shuffles the cards from their hand into their library,
    then draws that many cards.`` (Winds of Change.)

    Beside the graveyard shuffle above and for the same reason: a whole zone
    moves, and the shuffle is part of the move rather than a rider on it
    (CR 701.19). ``then_draw`` is on the node instead of being a second
    statement because "that many" is the number the shuffle just moved — a
    count nothing else in the sentence knows, so a draw parsed apart from it
    would have no producer to read.
    """
    whose: PlayerRef
    then_draw: bool = False


@dataclass(frozen=True)
class DoesntUntapWhileSourceTapped:
    """``<subject> doesn't untap during its controller's untap step **for as
    long as this creature remains tapped**.`` (Phyrexian Gremlins.)

    A sibling of :class:`DoesntUntapNextStep` rather than that node with a
    duration, because the two are different effects and the difference is the
    whole card. Frost Breath's is a one-shot restriction that expires by being
    used up at the *next* untap step; this one is continuous and ends on a
    condition — the source untapping — which may never coincide with an untap
    step at all.
    """
    subject: Recipient


@dataclass(frozen=True)
class DelayedSelfAction:
    """``Destroy this artifact at the beginning of the next end step.`` (Rocket
    Launcher.) ``Return this artifact to its owner's hand at the beginning of
    the next end step.`` (Rakalite.)

    A delayed triggered ability (CR 603.7): the effect creates it now and it
    fires once, at a moment fixed when it was created. One node for both
    actions because the *delay* is the whole content — what happens when it
    fires is a word — and one node for the whole sentence because the action
    alone would be performed immediately, which is the opposite of what the
    card says.
    """
    action: str   # destroy | bounce
