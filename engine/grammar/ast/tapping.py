"""Tapping and untapping: CR 701.26's keyword actions, and the restrictions on them.

`Tap`, `Untap` and the choice between them; "doesn't untap during its
controller's next untap step" (CR 502.3's exception, printed as a rider); the
toll that buys an untap back; and the two standing untap restrictions a
permanent carries about itself.

Split off `ast/board.py` at Weatherlight's Phase 0, when that module sat three
lines from the thousand-line guard with a wave about to open on it. The layering
guard's own prose had said `tapping` was deliberately *not* an AST family
because the guard "never fired on the inventory" — and now it has. The line is
the one `effects/tapping.py` and `lowering/tapping.py` have drawn since Homelands
and Fallen Empires: tapping is a keyword action on one permanent (CR 701.26a),
where everything left in `board` destroys, sacrifices, bounces or changes
control. The mirror re-forms on all three sides rather than forking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import (
    ObjectFilter,
    PlayerRef,
    Recipient,
)


@dataclass(frozen=True)
class Tap:
    subject: Recipient
    #: "…that could produce **any type of mana that land could produce**."
    #: (Mana Web.) A comparison between two lands' produced-mana sets, where
    #: the other land is the one the ability's *trigger* watched being tapped.
    #:
    #: A field on the tap rather than a narrowing on ``subject``, and that is
    #: the honest place for it: ``ObjectFilter`` describes one object, and
    #: nothing a filter can say names an object the **event** chose.
    #: ``subject_filters.subject_matches`` takes a source, an observer, a
    #: defending seat and a "that player" — it takes no tapped land, so a
    #: filter key here would be a narrowing the matcher silently drops, which
    #: on a sweep is every land on that player's board rather than the ones
    #: the card names.
    matching_tapped_land_mana: bool = False


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

    ``whose`` is the other printed word, and it names a *player* rather than a
    permanent: "during **its controller's** next untap step" (Frost Breath) is
    per-creature, and "during **your** next untap step" (Deep Spawn, Homarid
    Warrior — CR 701.43a's exert wording) is the next untap step of the player
    who created the effect. They coincide on every board where nobody has
    changed hands, and diverge exactly where a control change puts the creature
    on somebody else's battlefield first — so the word travels rather than being
    read as a spelling of the other, and the marker carries the seat.
    """

    subject: Recipient
    count: int = 1
    #: ``"controller"`` for "its controller's", ``"you"`` for "your".
    whose: str = "controller"


@dataclass(frozen=True)
class SimultaneousUntapAndTap:
    """``<player> simultaneously untaps each <phrase> and taps each <phrase>.``
    (Sands of Time.)

    One node rather than a :class:`Conjunction` of :class:`Untap` and
    :class:`Tap`, and the printed word "simultaneously" is why: run in sequence
    the untap goes first and the tap sweep then finds everything untapped, so
    the board ends wholly tapped instead of inverted. CR 611.2c fixes the set an
    effect acts on when the effect begins, and "simultaneously" says both sets
    are fixed at that one moment.

    Both noun phrases are carried, rather than one phrase and a flag, because
    nothing makes them agree: a card printing "untaps each tapped creature they
    control and taps each untapped land they control" is the same sentence, and
    a single filter would quietly apply one card's noun to the other's sweep.

    ``who`` is the printed subject — "that player" under a per-player trigger,
    whose seat the fire site froze (CR 603.10).
    """

    who: PlayerRef
    untap: "ObjectFilter"
    tap: "ObjectFilter"


@dataclass(frozen=True)
class UntapChosenByPaying:
    """"…that player may choose any number of tapped creatures without flying
    they control and **pay {2} for each creature chosen this way**. If the
    player does, untap those creatures." (Mudslide.)

    A toll whose *number of payments* the payer chooses. Its own node rather
    than a :class:`May` around an untap, because a ``May``'s cost is fixed when
    the offer is made and this one is not known until the picking is done — the
    player is choosing the set and the price in one decision, and the effect
    lands on exactly what they paid for.

    ``subject`` is the printed noun phrase the choice is made from, carried as
    a filter rather than as chosen objects: nothing is chosen when the ability
    resolves either, so the set is described here and picked at the prompt.
    """

    payer: PlayerRef
    subject: ObjectFilter
    cost_each: "ManaCost"


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
class DoesntUntapWhileCounter:
    """``<subject> doesn't untap during its controller's untap step **for as
    long as it has a <name> counter on it**.`` (Dread Wight.)

    The third member of the family :class:`DoesntUntapNextStep` and
    :class:`DoesntUntapWhileSourceTapped` make, and a sibling rather than
    either of them with a field, because what ends the restriction is the whole
    difference: Frost Breath's expires by being spent at the *next* untap step,
    Phyrexian Gremlins' when the source untaps, and this one when the marked
    permanent no longer carries the counter — a condition about the restricted
    permanent itself, which is what makes it removable by the very ability the
    same card grants.

    ``counter`` is the counter's printed name (CR 122.1), payload for the
    reason every printed word in this family is one: a card saying "paralysis"
    is the same restriction and must need no second node.
    """
    subject: Recipient
    counter: str


@dataclass(frozen=True)
class ReturnSelfInsteadOfUntapping:
    """``During your next untap step, as you untap your permanents, return this
    land to its owner's hand.`` (Undiscovered Paradise.)

    A **replacement of the untap**, not a delayed trigger, and the difference is
    the whole card. A delayed ability fires at the beginning of a step and waits
    for priority; the untap step gives nobody priority (CR 502.4), so a delayed
    reading would untap the land, hold the return until the upkeep, and give its
    controller a free untapped land for the turn — the one thing the card is
    printed to deny. What the sentence says is "instead of untapping": the
    engine's ``would_untap`` replacement, armed for one step.

    No fields. The window is the sentence's own ("your next untap step"), the
    object is the ability's own source, and the destination is CR 400.3's
    owner's hand — none of the three can vary without being a different
    sentence, so there is nothing here for a payload to carry.
    """
    pass
