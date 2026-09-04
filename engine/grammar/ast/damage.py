"""Damage nodes: dealing it, and preventing it.

`DealDamage` with its riders, the "unless they pay" variant, and the CR 615
prevention shield.

`DamageRiders` is a node of its own rather than four more fields on
`DealDamage` because the riders are printed as a trailing sentence and parsed as
one — and because a rider recorded nowhere is a rider the deletion probe can
delete without changing the parse.
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
)
from .costs import ManaCost


@dataclass(frozen=True)
class DamageRiders:
    """Trailing riders attached to a damage effect ("it can't be regenerated
    this turn, and if it would die this turn, exile it instead")."""
    no_regen: bool = False
    exile_if_dies: bool = False
    divided: bool = False
    divided_evenly: bool = False
    #: "…divided evenly, **rounded down**, among any number of targets."
    #: (Fireball.) The word the printed sentence spends on what an integer
    #: division does anyway — recorded rather than swallowed, because a rule
    #: that consumes a word and stores nothing is a rule that would read
    #: "rounded **up**" as the same sentence and deal one less than the card
    #: says. Empty where the card prints no rounding at all.
    rounding: str = ""
    #: "If <this source> would deal damage to a creature, that damage can't be
    #: prevented or dealt instead to another permanent or player." (Lava Burst.)
    #: Whippoorwill's lock (:class:`DamageCantBePreventedOrRedirected`) said
    #: about *this* damage event rather than about a creature for the rest of
    #: the turn — the sentence names the source, not a victim, and the two
    #: differ the moment a second source aims at the same creature. A rider
    #: rather than a node of its own for the same reason ``no_regen`` is one:
    #: the sentence deals no damage and modifies the one that does.
    unpreventable_to_creature: bool = False


@dataclass(frozen=True)
class DamageRidersUntilEndOfTurn:
    """"If the creature deals damage to a creature this turn, the creature
    dealt damage can't be regenerated this turn. If a creature dealt damage by
    the targeted creature would die this turn, exile that creature instead."
    (Runesword.)

    The same two riders :class:`DamageRiders` carries, granted to a creature
    for the turn instead of applied to one damage event now. Old templating
    prints them as "if" sentences, and they are not conditionals: nothing is
    tested when the ability resolves, and what is created is a standing
    property of the *damager* — which is the shape `Silhouette`'s prevention
    takes on the other side of the same verb.

    Its own node rather than a flag on ``DealDamage`` because this sentence
    deals no damage at all: it says what the damage somebody else deals later
    will do.
    """
    #: Whose damage carries them. ``"ability_target"`` is the creature the
    #: ability already chose — printed as "the creature" and as "the targeted
    #: creature", one referent under two spellings.
    subject: str
    riders: DamageRiders


@dataclass(frozen=True)
class DealDamage:
    source: TargetSpec | None          # the damage source ("this creature", the spell)
    amount: Amount
    recipients: tuple[Recipient, ...]
    riders: DamageRiders = field(default_factory=DamageRiders)
    # "of an opponent's choice" — the opponent, not the controller, picks.
    chooser: PlayerRef | None = None
    # "…deals 2 damage to each creature **for each Aura attached to that
    # creature**." (Baki's Curse.) A multiplier on the printed amount, as a noun
    # phrase — the same clause `ast.Pump.per_each` carries for "+2/+2 for each
    # Aura attached to it" (Rabid Wombat), read by the same production.
    #
    # Its own field rather than a computed ``amount``, because the number is not
    # one number: the phrase names a set **relative to each recipient**, so a
    # sweep over five creatures computes five multipliers. An ``amount`` has one
    # value per resolution, which is exactly the reading that would deal every
    # creature the count taken off the first one.
    per_each: "ObjectFilter | None" = None


@dataclass(frozen=True)
class CoinFlipDamageLoop:
    """``You and target opponent each flip a coin. <source> deals N damage to
    each player whose coin comes up tails. Repeat this process until both
    players' coins come up heads on the same flip.`` (Mana Clash.)

    Three printed sentences, one node, for the reason `paragraphs.py` gives:
    the second sentence reads a pair of flips nothing else records and the third
    is a loop over both of the others. Parsed apart, the first would flip once,
    the second would read nothing, and the third would have no process to
    repeat.

    Only the amount is data. The two flippers, the "tails" reading and the
    both-heads exit are what the loop *is*, and a card that varied any of them
    would be varying the process rather than a parameter of it.
    """
    source: TargetSpec | None
    amount: Amount


@dataclass(frozen=True)
class DamageThoseDamagedThisGame:
    """``<source> deals N damage to each <class>[ and <class>] it has dealt
    damage to this game.`` (The Fallen.)

    Its own node rather than a `DealDamage` with another recipient shape,
    because the recipients are not a set anything on the board describes: they
    are a *history*, kept on the source as it deals damage, and a filter written
    over the board could only guess at it. The classes stay data — a card
    printing the same clause over creatures needs no new node — and lowering is
    where they meet what a handler implements.
    """
    source: TargetSpec | None
    amount: Amount
    classes: tuple[str, ...]


@dataclass(frozen=True)
class Fight:
    """``<subject> fights <opponent>.`` (CR 701.14 — Brash Taunter, Primal Might.)

    Its own node rather than two :class:`DealDamage` steps, because CR 701.14b
    makes the exchange atomic: if either creature has left the battlefield or
    stopped being a creature, *neither* deals damage. Written as two steps the
    first would resolve and the second would not, which is a different card.
    """
    subject: Recipient
    opponent: Recipient


@dataclass(frozen=True)
class DamageUnlessPay:
    """"<source> deals N damage to you unless you pay <cost>." (Force of
    Nature, Hasran Ogress.)

    Fused for the same reason as :class:`SacrificeUnlessPay`: the cost is not a
    step of the effect but the *alternative* to it, and both engine flows that
    implement it (the upkeep pay-or-else prompt and the pending optional-pay
    queue) take the damage and the cost together. Decomposing this into
    ``May(pay) else DealDamage`` would compile cleanly onto no handler at all.
    """
    damage: DealDamage
    payer: PlayerRef
    cost: ManaCost
    #: "…unless they pay {1} **for each vortex counter on this enchantment**."
    #: (Energy Vortex.) The counter word the printed cost is multiplied by, or
    #: None for a flat one. Payload rather than a second node, exactly as the
    #: identical clause behind a destruction already is (``DestroyUnlessPay
    #: .per_counter``): the cost is read at resolution either way, and a card
    #: printing a different counter word needs no production.
    per_counter: str | None = None


@dataclass(frozen=True)
class RedirectDamage:
    """"All damage that would be dealt to you this turn by <source> is dealt to
    <recipient> instead." (Shimian Night Stalker, Nova Pentacle — CR 614.9.)

    Its own node rather than a flag on :class:`PreventDamage`, because a
    redirection is not a prevention: the damage is still dealt, in full, by the
    same source, and only its recipient changes. Sharing the node would put the
    two one boolean apart in the AST and one mistake apart in every reader —
    and a redirect read as a shield loses lifelink, the damage triggers and the
    dealt-damage records all at once.

    to             -- the recipient whose damage moves; None when the sentence
                      names only the source ("all damage that would be dealt
                      this turn **by** target sorcery spell", Reverberation)
    new_recipient  -- who takes it instead
    dealt_by       -- the source whose damage moves, when the sentence chooses
                      one; None means every source, as the printed class form
                      ("by unblocked creatures") has
    from_chosen_source -- "a source of your choice" (CR 615.8's phrase, printed
                      here on a redirect): the source is picked as the ability is
                      activated rather than being a target of it
    one_shot       -- "**The next time** a source …", one instance rather than
                      every one for the duration
    chooser        -- "…of an opponent's choice", the same rider
                      :class:`DealDamage` carries and for the same reason
    optional       -- "you **may** have that damage dealt to you instead"
                      (Blood of the Martyr). CR 614 lets a replacement be
                      optional, and the word is a flag here rather than a node
                      of its own because everything else about the sentence is
                      the redirection above: the same recipient, the same new
                      recipient, the same duration vocabulary. Dropping it would
                      make the redirect compulsory, which on this card moves
                      every point of damage every creature would take onto its
                      controller's face whether they wanted it or not.
    """

    to: Recipient | None = None
    new_recipient: Recipient | None = None
    dealt_by: Recipient | None = None
    from_chosen_source: bool = False
    duration: Duration = field(default_factory=Duration)
    one_shot: bool = False
    chooser: PlayerRef | None = None
    optional: bool = False
    #: "All **combat** damage that would be dealt to you by unblocked creatures
    #: this turn is dealt to this creature instead." (Kjeldoran Royal Guard.)
    #: The printed word is the whole difference between a redirect that catches
    #: an unblocked attacker's ping ability and one that does not, so it is read
    #: rather than skipped — exactly as :class:`PreventDamage` reads its own.
    combat_only: bool = False
    #: "**The next 1 damage** that would be dealt to target white creature this
    #: turn is dealt to this creature instead." (Daughter of Autumn; Hazduhr the
    #: Abbot prints ``X``.) A **point pool**, the redirection twin of
    #: :class:`PreventDamage`'s quantity: CR 615.7 spells out how a numeric
    #: shield spends — each 1 damage reduces it by 1, and what is left of a
    #: larger event is dealt normally — and a numeric redirect moves those same
    #: points instead of removing them.
    #:
    #: ``None`` is "**all** damage", which every other printing in the pool is,
    #: and the distinction is not cosmetic: a record with no pool moves the whole
    #: event, so a 1-point redirect read as one would move a Fireball's twelve.
    #: Its own field rather than ``one_shot``'s neighbour for the same reason
    #: ``Shield.amount`` and ``Shield.uses`` are two fields — CR 615.8's "the
    #: next **time**" is one whole instance whatever its size, and this is a
    #: number of points however many instances it takes.
    amount: Amount | None = None


@dataclass(frozen=True)
class DamageReducedByPaidMana:
    """"That player may pay any amount of mana. <source> deals N damage to that
    player. Prevent X of that damage, where X is the amount of mana that player
    paid this way." (Power Leak, Errant Minion.)

    Three printed sentences and one effect, which is why it is a node rather
    than a sequence: the offer has no bound, the damage is what it is measured
    against, and the prevention reads the payment back — none of the three says
    anything on its own, and a decomposed reading would deal the damage before
    the offer had a number to subtract.

    Only the *amount* is carried. Who is offered and who is damaged are the same
    seat by construction — the sentence names "that player" three times, and the
    trigger condition in front of it is what says which seat that is — so
    recording either would be recording the condition twice.
    """

    amount: int


@dataclass(frozen=True)
class DamageCantBePreventedOrRedirected:
    """"Damage that would be dealt to that creature this turn can't be prevented
    or dealt instead to another permanent or player." (Whippoorwill.)

    The negation of the two families beside it: CR 615's shields and CR 614.9's
    redirections both stop applying to the named creature. Its own node rather
    than a flag on :class:`PreventDamage`, because it prevents nothing — it is a
    statement *about* what may modify a damage event, and a reader that took it
    for a shield would have the creature taking no damage at all, which is the
    opposite of what the card does.
    """
    subject: Recipient
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class PreventedRider:
    """CR 615.5's additional effect — the sentence printed *after* a prevention.

    "You gain life equal to the damage prevented this way" (Reverse Damage) is
    ``effect="gain_life"``; "Exile cards from the top of your library equal to
    the damage prevented this way" (Bone Mask) is
    ``effect="exile_from_library"``.

    ``source_colors`` is the condition Shadowbane prints in front of its own:
    "**If damage from a black source is prevented this way,** you gain that much
    life." A property of the *source*, rechecked when the damage would be dealt
    exactly as a shield's own recorded property is (CR 615.9) — which is why it
    rides here rather than being folded into the shield's ``colors``: that field
    decides whether the shield **applies at all**, and Shadowbane prevents every
    colour's damage and pays for only one.

    Empty means unconditional, which is what the two cards above print.
    """

    effect: str
    source_colors: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreventDamage:
    amount: Amount
    #: CR 615.5's "additional effect, which may refer to the amount of damage
    #: that was prevented" — the sentence printed *after* the prevention, as the
    #: name of what it does: "You gain life equal to the damage prevented this
    #: way" (Reverse Damage) is ``"gain_life"``, "Exile cards from the top of
    #: your library equal to the damage prevented this way" (Bone Mask) is
    #: ``"exile_from_library"``.
    #:
    #: A node rather than a nested statement, and the reason is the amount: the
    #: rider's quantity does not exist until the shield has absorbed something,
    #: so it cannot be an ordinary lowered step reading the scratchpad — it runs
    #: *inside* the prevention, from the interceptor, with the shields that did
    #: the work in hand. Which is exactly why ``shields.Shield.kind`` names the
    #: interceptor: the rider and the absorption are one effect.
    prevented_rider: "PreventedRider | None" = None
    #: "…would deal damage to **you and/or creatures you control** this turn"
    #: (Shadowbane). The recipients beyond ``to``, as printed. The union is a
    #: *tuple* for ``dealt_by_others``' reason one field over: one shield
    #: covering several recipients is not several shields, and a reader that
    #: kept only the first would shield the player and leave every creature the
    #: card names uncovered.
    to_others: tuple[Recipient, ...] = ()
    to: Recipient | None = None
    from_filter: ObjectFilter | None = None
    duration: Duration = field(default_factory=Duration)
    # "Prevent all **combat** damage …" (Fog). A narrowing of which damage
    # events the shield sees, not of where it applies, so it is a flag rather
    # than another `from_filter` — the filter describes the *source object*,
    # while this describes the event. Conflating them would make a Fog read as
    # a shield against every source, which is a strictly larger effect.
    combat_only: bool = False
    # "Prevent all combat damage that would be dealt **by** target creature
    # this turn." (Horn of Deafening, Lady Evangela.) The other end of the
    # event: `to` names who is protected, this names whose damage is stopped.
    # A Recipient rather than `from_filter`'s ObjectFilter, because the source
    # is *chosen* (CR 115.1c) rather than described — a filter cannot say
    # "the creature the player targeted".
    dealt_by: Recipient | None = None
    # "…by **that creature and each creature blocking it**." (Feint.) The
    # printed "and" makes the source end a *list*, and the conjuncts are not
    # interchangeable: the first is the chosen object, the rest describe sets
    # relative to it. Kept as a tail beside `dealt_by` rather than folding the
    # first into a tuple, so every lowering and every reader written before this
    # existed keeps meaning exactly what it did — and a lowering that has not
    # been taught the conjunction refuses it by name instead of shielding only
    # the first source, which is the silent half of the card.
    dealt_by_others: tuple[Recipient, ...] = ()
    # "If **a spell or ability that targets that creature** would cause a source
    # to deal damage to that creature this turn, prevent that damage."
    # (Silhouette.) Not a `from_filter`, and the difference is the card: the
    # source may be anything the spell causes to deal the damage, and what is
    # narrowed is the *resolving object* that caused it. A filter written over
    # the source would shield the creature from every spell of that description
    # instead of from the ones aimed at it.
    from_targeting_source: bool = False
    # "…that would be dealt **to and dealt by** that creature this turn."
    # (Ebony Horse, Maze of Ith.) One printed object standing at *both* ends of
    # the event, named once. A flag rather than leaving ``to`` and ``dealt_by``
    # holding the same node, because those two keys are read independently and
    # every lowering written before this existed reads one of them: seeing only
    # ``to`` would arm the shield on the recipient end alone. A creature that
    # cannot be hurt is not the card that also cannot hurt anything, and the
    # half that goes missing is silent either way.
    to_and_by: bool = False
    # "…dealt to any target this turn. **If it's a green creature, prevent the
    # next 2 damage instead.**" (Elvish Healer.) A second size the shield takes
    # when the recipient answers a printed noun phrase, which is a property of
    # *this* shield rather than a second effect: the two sentences arm one
    # shield of one size, chosen when the target is known. Two fields rather
    # than a nested node, because either alone is meaningless — the lowering
    # refuses unless both are present.
    # "…**If this spell's additional cost was paid, this effect doesn't affect
    # combat damage that would be dealt by red creatures.**" (Undergrowth.) The
    # printed noun phrase whose damage this prevention leaves alone — but only
    # when CR 601.2b's optional additional cost was taken, which is what makes
    # it a field on the prevention rather than a second effect: the card prints
    # one prevention with two widths, and reading it as two would let both
    # apply.
    #
    # None is the ordinary prevention, which is every other card that prints
    # one.
    unaffected_if_cost_paid: "ObjectFilter | None" = None
    alternate_amount: "Amount | None" = None
    alternate_subject: "ObjectFilter | None" = None


@dataclass(frozen=True)
class UpkeepDamageUnlessCost:
    """``<source> deals N damage to you unless you <cost>. If it deals damage to
    you this way, tap it.`` (Mishra's War Machine, Minion of Leshrac.)

    Two sentences and one effect, because the tap happens only on the *damage*
    branch — the second sentence has no subject of its own to compose over.

    **The cost is payload, not a kind.** Mishra's War Machine discards a card
    and Minion of Leshrac sacrifices a creature other than itself; the sentence
    is otherwise identical and so is what the upkeep step does with it. It used
    to be one card hook keyed on Mishra's whole printed line, which is why the
    second card printing the template reached nothing.
    """

    amount: Amount
    #: How many cards the alternative discards. Zero when the cost is a
    #: sacrifice — the two are alternatives, never both, and a card printing
    #: both would be refused rather than charged half.
    discard: int = 0
    #: What the alternative sacrifices, as the printed noun phrase.
    sacrifice: "ObjectFilter | None" = None
    #: "If it deals damage to you this way, **tap it**."
    taps_source: bool = False


@dataclass(frozen=True)
class UpkeepCounterToll:
    """CR 702.24a's ability written out, with its counter and its consequence
    as parameters.

    ``Put a +1/+1 counter on this creature, then sacrifice this creature unless
    you pay {1} for each +1/+1 counter on it.`` (Phantasmal Sphere.)
    ``Put a wage counter on this creature. You may pay {2} for each wage counter
    on it. If you don't, remove all wage counters from this creature and an
    opponent gains control of it.`` (Rogue Skycaptain.)

    **One node for two printed spellings**, because CR 118.12a says they are one
    sentence: "[do something] unless [a player does something else]" means "[a
    player may do something else]. If they don't, [do something]." A node per
    spelling would be two readings of one rule, free to disagree about the
    escalation — which is the whole content of the paragraph.

    And one node for two *consequences*, for the reason every other parameter in
    this grammar is payload: the counter word, the cost and what happens when
    the cost is declined are what the printings vary, and the frame around them
    is the keyword's own definition. The keyword form itself is not read here —
    ``engine/cumulative_upkeep.py`` rewrites "Cumulative upkeep [cost]" before a
    line is classified, and this is the longhand a card prints instead.

    Sitting in the damage family's module beside :class:`UpkeepDamageUnlessCost`
    for the reason that one gives: the upkeep paragraph productions are one
    family and their nodes live where the first of them did.
    """

    #: The counter word CR 702.24a calls "age": "+1/+1", "wage", "wind".
    counter: str
    #: What the payment costs *per counter*, as printed mana symbols.
    cost: dict
    #: What happens when it is declined — "sacrifice" (CR 702.24a's own) or
    #: "cede_control" (Rogue Skycaptain's, which also clears the counters).
    consequence: str = "sacrifice"
