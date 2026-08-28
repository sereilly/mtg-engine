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
    ManaCost,
    ObjectFilter,
    PlayerRef,
    Recipient,
    TargetSpec,
)


@dataclass(frozen=True)
class DamageRiders:
    """Trailing riders attached to a damage effect ("it can't be regenerated
    this turn, and if it would die this turn, exile it instead")."""
    no_regen: bool = False
    exile_if_dies: bool = False
    divided: bool = False
    divided_evenly: bool = False


@dataclass(frozen=True)
class DealDamage:
    source: TargetSpec | None          # the damage source ("this creature", the spell)
    amount: Amount
    recipients: tuple[Recipient, ...]
    riders: DamageRiders = field(default_factory=DamageRiders)
    # "of an opponent's choice" — the opponent, not the controller, picks.
    chooser: PlayerRef | None = None


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
    """

    to: Recipient | None = None
    new_recipient: Recipient | None = None
    dealt_by: Recipient | None = None
    from_chosen_source: bool = False
    duration: Duration = field(default_factory=Duration)
    one_shot: bool = False
    chooser: PlayerRef | None = None


@dataclass(frozen=True)
class PreventDamage:
    amount: Amount
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
