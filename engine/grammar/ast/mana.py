"""Mana: what a permanent produces, and what changes it.

Split out of `ast/cards.py` when a new template pushed the parsing half past
the thousand-line guard, and named for the family `lowering/mana.py` already
carried — so the mirror re-forms rather than forking.

Three nodes, and the split between them is which referents they can see.
`AddMana` writes out a quantity for the ability's own controller;
`AddManaForTappedLand` names referents only the enclosing trigger can bind; and
`ProducesManaInstead` does not add mana at all — it is a standing change to
what a land will produce the next time it is tapped (CR 611.2, CR 305.7).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import Amount, Duration, PlayerRef, TargetSpec

#: ``ProducesManaInstead.replaced`` for "instead of any **other** type" — the
#: whole of what the land would otherwise have produced, rather than one named
#: symbol. Named once because the parse side writes it and the lowering reads
#: it, and a second spelling of the string is how those two come apart.
ANY_OTHER_TYPE = "any_other"


@dataclass(frozen=True)
class AddMana:
    pips: tuple[tuple[str, int], ...] = ()
    # The printed "or" (``Add {B} or {R}``): *one* of the pips, chosen as the
    # mana is made, never all of them. Recorded rather than folded away —
    # without it "Add {B} or {R}" and "Add {B}{R}" are the same node, and the
    # add-everything reading is exactly the mana a dual land does not make.
    choice: bool = False
    # "Add **X** mana of any one color" (Sanctum of Fruitful Harvest) — how many,
    # as an :class:`Amount`, because the number can be a board count and not just
    # a printed digit. Zero is "this clause names no any-colour mana".
    any_color: "Amount | int" = 0
    # The clause verbatim. The current mana handler re-reads the text rather
    # than taking structured pips, so lowering passes it through unchanged;
    # this field goes away when the handler takes ``pips`` directly.
    source_text: str = ""
    # "Spend this mana only to cast an instant or sorcery spell." (Vodalian
    # Arcanist.) The restriction *key* from `engine/restricted_mana.py`, not the
    # phrase: which spells it admits is that module's question, asked again by
    # the payer, so one rule answers "what may this pay for?" in both places.
    spend_only: str | None = None
    # "an amount of {B} equal to the sacrificed artifact's mana value" (Priest
    # of Yawgmoth). The mana symbol, with the *amount* named as a
    # back-reference rather than a number: it is the mana value of whatever the
    # ability's sacrifice cost ate, which is last-known information by the time
    # this resolves.
    from_sacrificed_cost: str | None = None
    # "an amount of {C} equal to **that spell's** mana value" (Mana Drain). The
    # same printed shape as `from_sacrificed_cost` above, back-referring to a
    # different object: the spell an earlier sentence countered, whose mana
    # value only that sentence could read (CR 608.2h) — by the time this clause
    # runs, in a later phase, the card is in a graveyard and the stack item is
    # gone. The symbol, again, so a card printing another colour needs no code.
    from_countered_spell: str | None = None
    # "an amount of {C} equal to **that creature's** mana value" (Energy Tap).
    # A third back-reference of the same printed shape, naming the permanent an
    # earlier step of this same effect recorded — and, unlike the two above,
    # one that is still on the battlefield when this clause runs, so the number
    # is read off it rather than remembered as a number. Named for the printed
    # words rather than for a producer: which step recorded the creature is the
    # lowering's question, and the producer gate there is what makes the words
    # legal at all.
    from_bound_creature: str | None = None
    # "…then add an additional {B} **for each charge counter removed this way**"
    # (the five Mana Batteries). A multiplier like `per_each` below, over a
    # number that is not on the board at all: the counters were removed to pay
    # this ability's own cost (CR 601.2h), so what is counted is the payment and
    # the count is last-known information. The counter's printed kind, or None.
    #
    # Its own field rather than a `per_each` filter, because an `ObjectFilter`
    # describes permanents to scan for and there is nothing to scan: read as one
    # the clause would count the counters *still* on the artifact, which is
    # every one the player chose not to spend — the exact complement of what the
    # card says.
    per_each_counter_removed: str | None = None
    #: "Add {C} **for each storage counter on this land**." (City of Shadows.)
    #: The counter's printed kind. A sibling of the field above rather than the
    #: same one, because the two name different numbers: that one counts what
    #: this ability's *cost* removed and is gone by resolution, this one counts
    #: what is sitting on the source right now — and a card whose cost adds a
    #: counter would have the two disagree by exactly one.
    per_each_counter_on_source: str | None = None
    #: "Add one mana of any color **that a land an opponent controls could
    #: produce**." (Fellwar Stone.) Which board decides the colours available -
    #: ``"opponent_lands"`` today, and a value rather than a flag because the
    #: same sentence about *your* lands or about a chosen player's is the same
    #: production with a different word.
    any_color_from: str | None = None
    # "**an additional** {B}" (the Mana Batteries). Recorded rather than
    # consumed and dropped: the word says this clause adds on top of the one
    # before it, which is what makes the printed sentence two statements rather
    # than a restatement of one.
    additional: bool = False
    # "Add {G} **for each creature with power 4 or greater you control**"
    # (Leafkin Avenger). A board count multiplying the whole clause, the same
    # shape a life gain and a counter placement already carry — so it is a
    # filter here rather than a number, and the count is taken at resolution.
    per_each: object | None = None
    # "Add {U} **or** {C}{U}." (Adarkar Unicorn.) The printed alternatives when
    # at least one of them is a *run* of more than one symbol, which ``pips`` +
    # ``choice`` cannot say: that pair is ``(symbol, count)`` pairs, one per
    # alternative, so it expresses "one of these colours" and not "{U}, or {C}
    # and {U} together". Each alternative is its own pip list here, and ``pips``
    # stays empty — the two spellings are read by different branches, so a
    # reader that has learned only the older key adds nothing rather than
    # everything.
    runs_choice: tuple[tuple[tuple[str, int], ...], ...] = ()
    # "Add three mana **in any combination of** {R} and/or {G}." (Orcish
    # Lumberjack, Burnt Offering.) The symbols the player may choose among, with
    # ``combination_count`` mana produced and each unit chosen independently —
    # which is what separates it from ``any_color`` ("of any **one** color", one
    # choice for the whole clause) and from ``runs_choice`` (a choice between
    # two written-out quantities).
    combination: tuple[str, ...] = ()
    combination_count: "Amount | int" = 0


@dataclass(frozen=True)
class AddManaForTappedLand:
    """"…**that player** adds one mana of any type that land produced" (Mana
    Flare) / "…**its controller** adds an additional {R}" (Gauntlet of Might).

    Separate from :class:`AddMana`, which always adds a written-out quantity to
    the ability's own controller. Every part of this clause is a referent the
    *trigger* binds and the statement grammar cannot see on its own: who "that
    player" / "its controller" is, and which mana "that land produced". Lowering
    therefore refuses unless the enclosing trigger is ``land_tapped_for_mana``,
    the one event that binds them.

    ``additional`` records the word "additional". It is redundant on the board —
    the trigger fires after the land's own mana is already in the pool — but a
    word a production consumes without recording is a word the deletion probe
    can delete without changing the parse, which is the dropped-rider bug class.
    """

    recipient: PlayerRef
    # Written-out symbols: (("R", 1),).
    pips: tuple[tuple[str, int], ...] = ()
    # "one mana of any type that land produced" — a count of mana whose type is
    # whatever the tapped land just made, so it cannot be written as pips.
    of_type_produced: int = 0
    additional: bool = False


@dataclass(frozen=True)
class ProducesManaInstead:
    """"If target Plains is tapped for mana, it produces colorless mana instead
    of white mana." (Quarum Trench Gnomes.) "Until end of turn, if you tap a
    land you control for mana, it produces {U} instead of any other type."
    (Deep Water.)

    Not an addition: nothing is produced when this resolves. It is a continuous
    effect on one land that swaps one symbol for another the next time — and
    every time after that, "indefinitely" — the land is tapped for mana.

    Both symbols are payload, in both directions: the colour replaced and the
    colour replacing it are facts about one printed card, so a Swamp printing
    the same sentence about black needs no code.
    """

    target: TargetSpec
    #: The symbol the land would have produced, or :data:`ANY_OTHER_TYPE` for
    #: "instead of any **other** type" — every symbol the land could have made
    #: (Deep Water). A sentinel rather than a list of the six, because the
    #: phrase is about whatever the land produces and the engine must not have
    #: to enumerate that at parse time.
    replaced: str
    #: The symbol it produces instead.
    produced: str
    #: "**Until end of turn**, if you tap a land you control for mana …" — Deep
    #: Water's window. Quarum Trench Gnomes prints none and means CR 611.2's
    #: "indefinitely", which is the empty duration this defaults to.
    duration: "Duration" = field(default_factory=lambda: Duration())
    #: True when the sentence is written about the *tapper* ("if **you tap** a
    #: land you control") rather than about the land ("if target Plains **is
    #: tapped**"). The two spellings are the same event and a different scope: a
    #: seat's whole class of lands against one named object, which is why the
    #: record they arm hangs off different things.
    by_controller: bool = False


@dataclass(frozen=True)
class SpendManaAsThough:
    """"For one spell this turn, you may spend mana as though it were mana of
    any type to pay that spell's mana cost." (North Star.)

    CR 609.4's "as though": nothing about the mana in the pool changes, and no
    mana is produced. What the effect grants is a permission the *payment*
    reads, for a bounded number of the player's spells this turn.

    Two things are payload rather than two nodes. ``count`` is how many spells
    the permission covers, because "one" is a printed number like any other.
    ``any_type`` is which permission it is: CR 106.1b's five colours **plus**
    colorless for "any type", the five colours alone for "any color" — and the
    difference is exactly whether a {C} in the cost may be paid by a coloured
    mana, which is a card the engine would otherwise get wrong in the direction
    that makes a spell castable when it is not.
    """

    count: int
    any_type: bool
