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
    Amount,
    Duration,
    ObjectFilter,
    PlayerRef,
    Recipient,
    TargetSpec,
    Zone,
)
from .costs import ManaCost


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
    # "Destroy target creature **and target land**." (Fumarole.) The *other*
    # targeted phrases the same verb names, beyond ``subject``.
    #
    # One statement rather than a ``Conjunction`` of two ``Destroy``s, which is
    # the shape every other union of noun phrases takes: a conjunction lowers to
    # a sequence of two instructions, and a spell's cast-time target spec is
    # derived from the **first** instruction that describes one, so the second
    # target would be picked by nobody. Two targets of one spell are one
    # announcement (CR 601.2c), so they are one description — the ordered
    # ``roles`` shape ``engine/targeting.py`` already carries for Glyph of
    # Delusion, here with no relation between the roles.
    #
    # Empty for every union whose phrases are swept sets ("all enchantments you
    # control, and all Auras …"), which stay a conjunction: those name no
    # targets at all, so there is nothing for a picker to ask.
    also_targets: tuple[TargetSpec, ...] = ()


@dataclass(frozen=True)
class Sacrifice:
    player: PlayerRef
    subject: Recipient
    #: "…sacrifices **a third of** the creatures they control of their choice."
    #: (Pox.) How many, when the number is *computed* rather than printed.
    #: ``TargetSpec.count`` is an ``int`` and can only carry a printed one, and
    #: a fraction of a board has a different answer for every seat asked — so
    #: it rides here as an :class:`Amount` and the lowering turns it into the
    #: per-seat count spec the prompt is sized from. None is every sentence
    #: written before fractions existed: the subject's own count decides.
    count: "Amount | None" = None


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
    #: ``…with two scream counters on it`` (All Hallow's Eve). Counters the
    #: object carries *into* exile, as ``((counter word, how many), …)``.
    #: A tuple of pairs rather than a dict because the node is frozen and
    #: hashable, and the counter word and the number are payload for the same
    #: reason every other parameter in this grammar is — a card printing three
    #: verse counters is this sentence, not a second one.
    counters: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class PutSourceIntoZone:
    """``Put it into your graveyard.`` (All Hallow's Eve, from exile.)

    The ability moving its **own source** to a zone, with nothing chosen and
    nothing targeted — the same shape :class:`Exile` takes over the source, and
    a different one from ``ReturnToZone``, which resolves a noun phrase.

    The zone is the node's one field for the reason every parameter in this
    grammar is payload: "put it into your hand" is this sentence with a
    different destination, not a second production. Which destinations have a
    handler is the lowering's question, and it refuses the rest by name.
    """

    zone: Zone


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

    *tap_when_lost* is the trailing sentence "When you lose control of the
    creature, tap it." (Ray of Command, Magus of the Unseen) — CR 603.7's
    delayed trigger, folded onto the change it watches rather than parsed as a
    step of its own, because on its own the sentence names no object at all.

    *gained_by* is who ends up controlling it, when that is **not** the effect's
    own controller: "an opponent may gain control of a creature you control of
    their choice" (Infernal Denizen). The field is what gives "their choice" an
    antecedent — "their" is the sentence's printed subject, and a node that did
    not carry the subject would have to guess which seat picks. Absent means the
    ordinary reading, the resolving object's controller (CR 109.5).

    *offered* is the "may" in front of that verb, folded onto this node rather
    than left as an enclosing :class:`May`. The offer and the pick are one
    decision made by one seat — the seat named by *gained_by*, which is also the
    seat *their_choice* names — so they are one prompt, declinable. Wrapped in a
    ``May`` instead they would be two prompts to the same player whose two
    answers could disagree, and whose two non-interactive defaults would have to
    be kept in step.
    """

    subject: Recipient
    duration: str
    tap_when_lost: bool = False
    #: Who gains control, when the sentence names them ("**target opponent**
    #: gains control of this creature", Chaos Lord; "**an opponent** may gain
    #: control of a creature you control of their choice", Infernal Denizen).
    #: ``None`` is the ability's own controller, which is what every other
    #: "gain control of …" spelling means and what every reader written before
    #: this field assumed — so the default keeps them exactly as they were.
    #:
    #: A field rather than a second node because the two sentences differ in one
    #: word: everything else about a control change — the timestamp, the
    #: contribution, what ends it — is the same rule whoever the seat is.
    #:
    #: Two parallel branches added this field in the same wave under two names
    #: (``gained_by`` and ``gainer``) for two cards. One fact, one field.
    gained_by: "PlayerRef | None" = None
    #: Whether the seat above may decline it ("**may** gain control").
    offered: bool = False


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
class ExchangeControl:
    """``Exchange control of <first> and <second>.`` (CR 701.12b — Gauntlets of
    Chaos.)

    One node for both halves rather than two control changes in a
    :class:`Sequence`, for the reason CR 701.12a states: an exchange is atomic,
    so if either half cannot be completed *no part of it happens*. Written as
    two steps the first would apply and the second would not, which hands one
    player a permanent for nothing.

    ``shares_a_type`` is the printed "…that shares one of those types with it".
    It is a relation *between the two slots*, not a property of either
    permanent, so it rides here beside them exactly as the two-target pump's
    ``distinct`` does — an :class:`ObjectFilter` has nothing to compare against
    and would have to drop it.

    ``destroy_attached_auras`` is the trailing "If those permanents are
    exchanged this way, destroy all Auras attached to them." A rider on this
    node rather than a following statement, because "exchanged **this way**" is
    a question only the exchange can answer: on its own the sentence names no
    permanents at all.
    """

    first: Recipient
    second: Recipient
    shares_a_type: bool = False
    destroy_attached_auras: bool = False


@dataclass(frozen=True)
class ExchangeGreatestManaValue:
    """``You and target player exchange control of the <type> you each control
    with the greatest mana value. Then exchange control of <type>s the same
    way. If two or more permanents a player controls are tied for greatest,
    their controller chooses one of them.`` (Juxtapose.)

    A whole paragraph as one node, for the reason `paragraphs.py` states: "the
    same way" names an exchange the sentence before it described, and the
    tie-break sentence names permanents no sentence of its own has chosen. Read
    apart, the second sentence exchanges nothing and the third is about nobody.

    ``card_types`` is the printed list in printed order, so a card exchanging
    lands or enchantments the same way is this node with different words. Each
    exchange is separate and atomic (CR 701.12a): a player controlling no
    permanent of one type simply exchanges nothing *of that type*, and the
    other types still happen.
    """

    card_types: tuple[str, ...]

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
class ReanimateEnchantedCard:
    """The reanimation Aura's entry line, whole (Animate Dead, Dance of the Dead).

    ``When this Aura enters, if it's on the battlefield, it loses "enchant
    creature card in a graveyard" and gains "enchant creature put onto the
    battlefield with this Aura." Return|Put enchanted creature card
    to|onto the battlefield [tapped] under your control and attach this Aura to
    it. When this Aura leaves the battlefield, that creature's controller
    sacrifices it.``

    One node for the whole line because the sentences are not separable: the
    quoted rewrite exists only so the Aura may legally stay attached once its
    enchanted *card* has become a permanent (CR 400.7 makes it a new object),
    the attach is what performs that rewrite's whole consequence, and the
    trailing trigger is the price of the deal. Read as three statements they
    would be three effects on three different objects, two of which nothing
    could name.

    ``tapped`` is the one word that separates the two printings, and the word
    the rest of Dance of the Dead is built around — the +1/+1 and the "doesn't
    untap" line only matter because the creature arrives tapped.

    What carries it out is ``mixins/oracle_instructions._apply_aura_effect``,
    which reads the Aura's own text for the details (see
    ``engine/auras.AURA_REANIMATION_PHRASES``). This node exists so the line has
    an *instruction* — a trigger the compiler produces with none behind it is a
    card that reports supported with a silent ability part, which is exactly
    what the hollow-line probe counts.
    """

    tapped: bool = False


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
    # "Return target … creature card from your graveyard to the battlefield.
    # … **If the creature would leave the battlefield, exile it instead of
    # putting it anywhere else.**" (Dreams of the Dead.) A CR 614 replacement
    # armed on the permanent this move creates.
    #
    # A field on the move rather than a statement of its own, for the reason
    # ``gains`` beside it is one: the permanent does not exist until this step
    # runs, so an independent instruction would have nothing to arm — and what
    # it arms is not a target anything chose, since this ability's target is a
    # *card* in a graveyard. The parse folds the sentence in
    # (``pronouns._parse_exile_instead_of_leaving_rider``), which is where the
    # keyword grant after a reanimation is already folded.
    exile_on_leave: bool = False
    # "…to the battlefield **under the control of that creature's owner**."
    # (Reincarnation.) CR 110.2: a permanent enters under the control of the
    # spell's controller unless the effect says otherwise, and this is an
    # effect saying otherwise. Its own field rather than the destination
    # zone's owner: "which battlefield" and "who controls what lands there"
    # are different questions, and the pool prints cards that answer only the
    # second.
    under_control_of: PlayerRef | None = None
    # "Return a card from your graveyard to your hand **for each card discarded
    # this way**." (Recall.) How many times the printed subject is returned —
    # a repetition of the whole clause, not a narrowing of it, which is why it
    # is an `Amount` here rather than a bigger `count` on the subject: the
    # subject stays "a card", and the number the sentence multiplies it by is
    # not known until an earlier step of the same resolution has run.
    #
    # Recorded rather than folded away, because a card printing it and a card
    # not printing it are different cards; lowering refuses any shape it cannot
    # repeat, so the clause is never parsed and then dropped.
    repetitions: Amount | None = None
    # "**Each player** returns all creature cards from their graveyard to the
    # battlefield." (All Hallow's Eve.) Who does the returning — which is who
    # the cards come back *under the control of*, and whose graveyard "their"
    # means. Recorded rather than dropped: reading the sentence without it
    # would hand every player's creatures to the ability's controller, which is
    # a different card and one that wins the game on the spot.
    #
    # Not folded into ``under_control_of``: that field is an effect naming a
    # controller for objects somebody else moved ("under the control of that
    # creature's owner"), and this is the sentence's grammatical subject. A
    # card could print both.
    actor: PlayerRef | None = None
    # "…to the battlefield under your control **attached to that creature**."
    # (Takklemaggot.) CR 303.4f: an effect that puts an Aura onto the
    # battlefield says what it attaches to, because an Aura that entered
    # attached to nothing would be swept away by CR 704.5m before anyone could
    # attach it. The value names *which earlier step of this sentence* chose
    # the host — the scratchpad key, not a board read — so the same field
    # serves any card that picks a host and then puts something on it.
    attached_to: str | None = None
    # "…as a **non-Aura** enchantment." (Takklemaggot.) A CR 613 layer 4
    # type change applied to the permanent this move creates, carried on the
    # move because there is no other way to name an object a sentence has just
    # made: it is a new object (CR 400.7), so no earlier reference reaches it.
    losing_subtypes: tuple[str, ...] = ()
    # "**It loses "enchant creature" and gains "…"**." (Takklemaggot.) Layer 6,
    # and on this node for the reason above — the trailing sentence's "it" is
    # the permanent the return created. Each entry is a printed ability line.
    losing_abilities: tuple[str, ...] = ()
    gaining_abilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChoosePermanent:
    """"That creature's controller **chooses a creature that this card could
    enchant**." (Takklemaggot.)

    A permanent picked as the effect resolves, by a seat the sentence names
    (CR 601.2c does not make that the controller). Nothing is targeted — no
    target was declared when the ability went on the stack — so the pick is a
    *value* the sentences behind it read, which is exactly what
    ``engine/handlers/permanent_choices.py`` already provides.

    ``optional`` is what makes "If the player does … If they don't …" a real
    pair of branches: without it the sentence would always have an answer and
    the second branch would be unreachable text.
    """
    chooser: PlayerRef
    spec: "TargetSpec"
    optional: bool = False
    #: "…a creature **that this card could enchant**." CR 303.4j's legality,
    #: read as a relative clause rather than as an ``ObjectFilter`` key: the
    #: shared noun parser would then hand the phrase to every line printing it,
    #: and what makes a host legal is a question about a *pair* of permanents,
    #: which the filter matcher answers about one.
    host_for_source: bool = False


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
    # "…onto the battlefield **under its owner's control**." (Glyph of
    # Reincarnation.) CR 400.3's exception spelled the other way: the arrival
    # is not the resolving player's. A separate field from
    # ``under_your_control`` rather than a tri-state, because the two are
    # printed independently and a card printing neither means the default —
    # collapsing them would make "absent" and "the owner's" the same value, and
    # they name different seats the moment a creature has been stolen.
    under_owners_control: bool = False
    gains: tuple[str, ...] = ()
    #: "Put that card onto the battlefield under your control. **Sacrifice the
    #: creature when you lose control of this creature.**" (Seraph, Krovikan
    #: Vampire.) CR 603.7's delayed trigger, folded onto the entry it watches
    #: rather than parsed as a step of its own, because on its own the sentence
    #: names an object that does not exist yet — the permanent this entry is
    #: about to make. The same fold, for the same reason, that
    #: :class:`GainControl`.tap_when_lost is.
    sacrifice_when_control_lost: bool = False
    #: Which event recorded the card "**that card**" names, when that is not the
    #: trigger the effect is lowered under: the death that *created* a delay
    #: (CR 608.2h, Seraph), or an intervening-if that names the record instead
    #: of the fire site (Krovikan Vampire). Stamped by the parser, which is the
    #: only reader that has the whole printed line in view —
    #: ``rebinding.bind_recorded_card``.
    bound_card_from: str | None = None


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
    #: "…unless you pay {1} **for each music counter on it**" (the ability
    #: Musician grants). The counter word the printed cost is multiplied by, or
    #: None for a flat cost. Named rather than counted here for the reason
    #: cumulative upkeep names it: the multiplier is the permanent's counter
    #: total *when the trigger resolves*, which is not knowable while the
    #: sentence is being read.
    per_counter: str | None = None


@dataclass(frozen=True)
class DestroyEachUnlessPaid:
    """``For each <objects>, destroy that <object> unless any player pays N life.``
    (Cleansing.)

    A sweep whose every member can be bought off one at a time, which is what
    keeps it apart from :class:`Destroy` over a quantified noun phrase: the
    offer is made per permanent, and a seat that pays for one land has said
    nothing about the next.

    ``payer`` is the printed noun phrase's kind rather than a seat, because
    "**any** player" means the offer goes round every one of them in turn — the
    lowering refuses any other spelling instead of narrowing it to the
    controller, since a buyout nobody but the caster is offered is a different
    card.
    """

    filter: ObjectFilter
    life: int
    payer: str = "any_player"


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
    # Which object the delayed ability was created *for*: the ability's own
    # source ("this artifact", Rocket Launcher) or the object the sentence in
    # front of it named ("it", Glyph of Destruction). A field rather than a
    # second node, because the delay — the whole content of this sentence — is
    # identical either way and only the referent differs.
    subject: str = "source"   # source | bound
