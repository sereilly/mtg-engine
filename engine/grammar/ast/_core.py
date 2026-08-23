"""The vocabulary every family's nodes are built from.

Quantities (what `grammar/amounts.py` produces), object and player references
(`grammar/nouns.py`), and the durations, zones, costs and conditions that hang
off an effect without being one. Plus `RawEffect`, the untyped escape hatch,
which sits beside `RawCondition` because it is the same idea: a clause the
grammar recognized structurally and has no node for, recorded so lowering can
refuse it by name rather than drop it.

The bottom of the package. Nothing here imports from a family, and a node two
families both need belongs here rather than in whichever of them was written
first — that is what keeps "which family does this new node go in?" a question
with one answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from ..vocabulary import TYPE_LINE_SUPERTYPES


@dataclass(frozen=True)
class Fixed:
    """A literal count: "3 damage", "two cards"."""
    value: int


@dataclass(frozen=True)
class Var:
    """A variable: X (or, rarely, Y) — resolved from the cast's x_value."""
    name: str = "x"


@dataclass(frozen=True)
class CountOf:
    """"equal to the number of Swamps you control" — a count of matching objects."""
    filter: "ObjectFilter"


@dataclass(frozen=True)
class CountOfDeaths:
    """"the number of creatures that died under your control this turn" — a
    count of a *history*, not of the board.

    Separate from :class:`CountOf` because the two move in opposite directions:
    the creatures counted here are exactly the ones no longer on the
    battlefield, so reading this as the plain filter "creature" would count the
    survivors. The same distinction :class:`DiedThisTurn` draws for a "for
    each" iterator, at the other end of the sentence.
    """
    filter: "ObjectFilter"


@dataclass(frozen=True)
class ColorsAmong:
    """"for each color among permanents you control" — how many *colours* the
    named objects have between them (Chromatic Orrery).

    A third aggregate beside :class:`CountOf` and :class:`GreatestPowerAmong`,
    and its own node for the same reason they are each other's: five permanents
    can be one colour and one permanent can be five (CR 105.2b), so counting
    the objects answers a different question from counting the colours among
    them. A colourless permanent contributes nothing — colourless is not a
    colour (CR 105.1).
    """
    filter: "ObjectFilter"


@dataclass(frozen=True)
class GreatestPowerAmong:
    """"the greatest power among creature cards in your graveyard" — a
    *maximum*, not a count.

    Its own node beside :class:`CountOf` for the reason the death count has
    one: the two read the same objects and answer different questions, so a
    lowering that saw only a filter would have to guess which. Zero when the set
    is empty, which is what a maximum over nothing means for a P/T.
    """
    filter: "ObjectFilter"


@dataclass(frozen=True)
class ThatMuch:
    """A back-reference to a quantity the surrounding context produced
    ("you gain that much life", "equal to the damage dealt").

    *source* names the key that quantity was recorded under when the **words
    say which** — "equal to the damage dealt" is `damage_dealt`, "equal to its
    power" is `its_power`. A bare "that much" / "that many" names nothing: it
    points at whatever the enclosing effect or the firing event produced, which
    the parser cannot know from the sentence alone, and it carries `None` to say
    so. Lowering is the layer that resolves it — against the steps of this same
    effect or against the trigger's own event, both in
    `lowering/_common.py::_back_reference_payload` — and refuses when neither
    offers a number.

    It used to default to `"damage_dealt"`, which read as evidence and was only
    a guess: under "Whenever you gain life, target opponent loses that much
    life" there is no damage anywhere, and a lowering that trusted the name
    would have taken the wrong number from the wrong place.
    """
    source: str | None = None


@dataclass(frozen=True)
class Half:
    """"half X, rounded up/down"."""
    of: "Amount"
    rounding: str = "down"  # "down" | "up"


@dataclass(frozen=True)
class AllOf:
    """An unbounded quantity: "all damage", "any amount of mana"."""


@dataclass(frozen=True)
class AnyNumber:
    """"remove **any number of** +1/+1 counters" (Tetravus) — a count its
    controller chooses on resolution, bounded by what is there to take.

    Distinct from :class:`AllOf`, which is "all of them" and is not a choice,
    and from :class:`Fixed`, which is a number the card printed. Keeping the
    three apart is what stops "any number" being lowered as "one" or as "all",
    either of which is a different card.
    """


@dataclass(frozen=True)
class BoardCount:
    """A board-state count identified by *name* rather than built compositionally:
    "the number of untapped lands they controlled at the beginning of this turn".

    :class:`CountOf` covers the counts whose whole meaning *is* a noun phrase
    ("the number of Swamps they control"), because there the filter is the
    arithmetic. These are the ones where it is not: they reach back to an
    earlier point in the turn, or subtract a constant, or read a hidden zone —
    arithmetic no ``ObjectFilter`` expresses and which the *handler* implements
    end to end. Lowering therefore maps a name onto the single handler that
    computes exactly it, and refuses every name it has no handler for.

    Naming the count instead of approximating it is the point. Reading Black
    Vise's "the number of cards in their hand minus 4" as an ordinary filtered
    count would drop the "minus 4" — the dropped-rider bug class — and the card
    would deal four damage too much while still reporting as supported.
    """
    name: str


@dataclass(frozen=True)
class CountersOnSource:
    """"the number of doom counters on it" (Armageddon Clock) — how many CR
    122.1 named counters the ability's own source is carrying.

    Its own node rather than a :class:`CountOf` over a noun phrase because a
    counter is not an object: it has no controller, no type line and no zone, so
    every narrowing an ``ObjectFilter`` could carry would be a question about a
    permanent instead of about what is sitting on one. The kind is data — the
    word the card invented — so the next set's counter needs no production.
    """
    kind: str


Amount = Union[Fixed, Var, CountOf, CountersOnSource, ThatMuch, Half, AllOf, AnyNumber, BoardCount]


# ---------------------------------------------------------------------------
# Object and player references (engine/grammar/nouns.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """A numeric restriction: "with power 2 or less"."""
    op: str    # "eq" | "le" | "ge" | "lt" | "gt"
    value: Amount


@dataclass(frozen=True)
class ObjectFilter:
    """A noun phrase describing a set of objects.

    ``to_payload`` emits the exact key set the deleted
    ``engine.parsing.common.TargetFilter`` produced, so instructions lowered
    from the grammar stayed byte-compatible with the 121 existing effect
    handlers across the migration; the newer restriction keys are additive and
    read with ``payload.get`` defaults on the handler side.
    """

    card_types: tuple[str, ...] = ()          # "creature", "artifact", ...
    # How multiple card types combine. "artifact or enchantment" is a union
    # ("any"); "artifact creature" is a single permanent that is both ("all").
    # Collapsing the two would make "destroy target artifact creature" hit every
    # artifact and every creature.
    type_match: str = "any"
    supertypes: tuple[str, ...] = ()          # "legendary", "basic", ...
    subtypes: tuple[str, ...] = ()            # "wall", "djinn", ... (from data)
    # How multiple subtypes combine, exactly as `type_match` does for card
    # types. "Djinn or Efreet" is a union ("any"); "Urza's Power-Plant" is a
    # single permanent carrying both land types ("all", CR 205.3i). Collapsing
    # them would let one Urza's Mine satisfy "an Urza's Mine and an Urza's
    # Tower" on its own.
    subtype_match: str = "any"
    colors: tuple[str, ...] = ()              # mana symbols: "W", "U", ...
    excluded_colors: tuple[str, ...] = ()     # "nonblack"
    excluded_types: tuple[str, ...] = ()      # "nonartifact"
    excluded_subtypes: tuple[str, ...] = ()   # "non-Wall"
    with_keywords: tuple[str, ...] = ()       # "with flying"
    without_keywords: tuple[str, ...] = ()    # "without flying"
    controller: str | None = None             # "you" | "opponent" | "that_player"
    # "target permanent you both **own** and control" (Obelisk of Undoing).
    # Ownership (CR 108.3) is a different question from control (CR 613 layer
    # 2) and the two come apart the moment anything is stolen — which is
    # precisely the case this card is printed to exclude. Its own field, so a
    # phrase naming only one of them cannot be read as naming both.
    owner: str | None = None                  # "you"
    tapped: bool | None = None
    attacking: bool | None = None
    blocking: bool | None = None
    blocked: bool | None = None
    # "target **attacking or blocking** creature" (the Legends pinger cycle).
    # Its own field rather than both booleans set at once: every matcher ANDs
    # the payload keys, so `attacking=True, blocking=True` would describe a
    # creature that is somehow doing both — a set that is always empty.
    attacking_or_blocking: bool = False
    power: Comparison | None = None
    toughness: Comparison | None = None
    mana_value: Comparison | None = None
    named: str | None = None
    zone: str = "battlefield"
    # "target **activated or triggered ability**" (Sublime Epiphany). An ability
    # on the stack is an object (CR 113.7a/608.2) but not a spell, so it is not
    # ``zone == "stack"`` with a type line — it has no card at all. The printed
    # kinds are carried rather than collapsed to "an ability", because "counter
    # target activated ability" and "counter target triggered ability" are
    # different cards and the difference is exactly this tuple.
    ability_kinds: tuple[str, ...] = ()
    # Whose zone, when *zone* names one ("from **your** graveyard"). "Return
    # target creature card from your graveyard" and "…from a graveyard" are
    # different cards, and the handlers only ever look in the caster's own
    # graveyard — so the owner is recorded and checked rather than assumed.
    zone_owner: PlayerRef | None = None
    # The head noun was "card" ("target creature **card** from your graveyard").
    # CR 400.1: an object outside the battlefield is a card, not a permanent.
    # Without this the word is droppable, and "target creature card from your
    # graveyard" would lower identically to the untemplatable "target creature
    # from your graveyard" — the dropped-rider bug class.
    is_card: bool = False
    # "with a +1/+1 counter on it" (Tempered Veteran) — the object carries at
    # least one +1/+1 counter, read off the ``plus_counters`` record the
    # placing handlers keep (CR 122).
    with_plus1_counter: bool = False
    # "nontoken" (Lich's sacrifice). CR 111.1: a token is not a card, so this is
    # neither an excluded card type nor an excluded subtype.
    nontoken: bool = False
    # "exile any number of **tokens** created with this creature" (Tetravus) —
    # the positive of ``nontoken``. Its own field rather than a tri-state,
    # because every lowering written before it exists refuses an unknown field
    # by default and would silently ignore a third value of an old one.
    token_only: bool = False
    # "…**created with this creature**" (Tetravus). Which permanent made the
    # token, and therefore *relative*: no read of the token alone can answer it,
    # exactly like ``other_than_source`` and ``attached_to``. The handler that
    # has the ability's source tests it; ``permanent_matches_filter`` is
    # deliberately not told about it.
    created_with_source: bool = False
    # "a creature **of their choice**" (Run Afoul) — the player performing the
    # action picks. Recorded rather than dropped, because "of *your* choice" is a
    # different sentence; a lowering accepts it only where the rule it lowers to
    # already puts the choice there (CR 701.21a for a sacrifice).
    their_choice: bool = False
    # "other than this creature" / "other Zombies" — excludes the source.
    other_than_source: bool = False
    # "this creature" / "this artifact" — the ability's own source.
    is_source: bool = False
    # "enchanted creature" — the permanent this Aura is attached to.
    is_enchanted: bool = False
    # "all Equipment **attached to that creature**" (Turn to Slag). Which object
    # it is attached to, as a referent rather than a filter: "that creature" is
    # the spell's own target, and no read of the Equipment alone can say so.
    # ``permanent_matches_filter`` is therefore not told about it — the handler
    # that has the context resolves it, the split the ``controls`` condition
    # already makes for "another".
    attached_to: str | None = None
    # "that's one or more colors" (Ugin, the Spirit Dragon's −X): the object
    # has at least one color, read off its effective colors.
    colored: bool = False
    # "…that isn't the target of an ability from another creature named ~"
    # (Goblin Artisans). A restriction on the object's *situation* rather than
    # on the object: it asks what else on the stack is pointing at it. The
    # source class is not carried because the printed clause names the ability's
    # source by the asking card's own name, which the lexer has already
    # collapsed to a SELF token — so the question is "another copy of me",
    # whatever the copy is called.
    not_ability_targeted_by_same_name: bool = False

    def to_payload(self) -> dict[str, object]:
        """Instruction-payload dict, emitting only keys that are set.

        The first six keys reproduce ``TargetFilter.to_payload`` exactly.
        """
        payload: dict[str, object] = {}
        if self.card_types:
            if len(self.card_types) == 1:
                payload["type_filter"] = self.card_types[0]
            elif self.type_match == "all":
                # No handler matches "is all of these types at once" yet;
                # lowering refuses rather than emitting a union that would
                # quietly widen the effect.
                payload["type_filter_all"] = list(self.card_types)
            elif set(self.card_types) == {"artifact", "enchantment"}:
                # The one union spelling the handlers already understand;
                # emitting it keeps Disenchant byte-compatible with the rule it
                # replaces.
                payload["type_filter"] = "artifact_or_enchantment"
            else:
                payload["type_filter"] = list(self.card_types)
        if self.subtypes:
            if len(self.subtypes) > 1 and self.subtype_match == "all":
                payload["subtype_filter_all"] = list(self.subtypes)
            else:
                payload["subtype_filter"] = (
                    self.subtypes[0] if len(self.subtypes) == 1 else list(self.subtypes)
                )
        if self.tapped:
            payload["tapped_only"] = True
        # "an **untapped** creature" (Enthralling Hold). ``tapped`` is tri-state
        # and only the True half had a key, so the False half was falsy all the
        # way down and "untapped creature" emitted exactly the payload of
        # "creature" — the round-108 dropped-narrowing shape, wearing a boolean
        # instead of a missing key. Its own key rather than ``tapped_only:
        # False``, because absent already means "no restriction" and a matcher
        # reading a three-valued key with ``.get()`` would answer the wrong one
        # of the two.
        elif self.tapped is False:
            payload["untapped_only"] = True
        if self.colors:
            payload["color_filter"] = self.colors[0]
        if self.excluded_colors:
            payload["exclude_colors"] = list(self.excluded_colors)
        if self.excluded_types:
            payload["exclude_types"] = list(self.excluded_types)
        # Additive keys — handlers read these with .get() defaults.
        if self.with_keywords:
            payload["with_keywords"] = list(self.with_keywords)
        if self.without_keywords:
            payload["without_keywords"] = list(self.without_keywords)
        if self.controller:
            payload["controller"] = self.controller
            if self.owner is not None:
                payload["owner"] = self.owner
        if self.attacking:
            payload["attacking_only"] = True
        if self.blocking:
            payload["blocking_only"] = True
        if self.attacking_or_blocking:
            payload["attacking_or_blocking"] = True
        if self.other_than_source:
            payload["exclude_self"] = True
        if self.not_ability_targeted_by_same_name:
            payload["not_ability_targeted_by_same_name"] = True
        if self.nontoken:
            payload["nontoken"] = True
        if self.token_only:
            payload["token_only"] = True
        if self.created_with_source:
            payload["created_with_source"] = True
        # "a card **named** Frantic Inventory". Emitted like every other
        # restriction, and tested like one — a key a matcher dropped would be a
        # count over every card in the graveyard.
        if self.named:
            payload["named"] = self.named
        # "of their choice" says *who picks*, which is not a property of the
        # objects picked from — no matcher can test it, and it is deliberately
        # absent from ``TESTABLE_SUBJECT_FILTER_KEYS`` for that reason. Emitting
        # it anyway is what makes the absence load-bearing: every gate that asks
        # "are all this payload's keys testable?" refuses the phrase, so the only
        # way through is a lowering that reads the word and says why its rule
        # already puts the choice there (``_lower_sacrifice``, CR 701.21a).
        if self.their_choice:
            payload["their_choice"] = True
        # "non-Spirit creature" (Roaming Ghostlight). Emitted only when set, so
        # every payload written before this key existed is byte-identical.
        if self.excluded_subtypes:
            payload["exclude_subtypes"] = list(self.excluded_subtypes)
        # "with mana value 3 or less" (Eliminate). Only a literal bound has a
        # payload form; a variable one ("mana value X") is left unemitted so
        # _filter_payload refuses the line rather than dropping the bound.
        if self.mana_value is not None and isinstance(self.mana_value.value, Fixed):
            payload["mana_value"] = {
                "op": self.mana_value.op,
                "value": self.mana_value.value.value,
            }
        # "with power 4 or greater" (Turret Ogre's intervening-if). Same rule
        # as mana_value: a literal bound rides the payload and the matcher
        # tests it against the layer-computed stat; a variable bound stays
        # unemitted. Both stats, because emitting one and dropping the other
        # would let a toughness restriction vanish silently.
        if self.power is not None and isinstance(self.power.value, Fixed):
            payload["power"] = {"op": self.power.op, "value": self.power.value.value}
        if self.toughness is not None and isinstance(self.toughness.value, Fixed):
            payload["toughness"] = {
                "op": self.toughness.op,
                "value": self.toughness.value.value,
            }
        if self.colored:
            payload["colored_only"] = True
        # "with a +1/+1 counter on it" (Tempered Veteran). Emitted only when
        # set, so every payload written before this key existed is
        # byte-identical.
        if self.with_plus1_counter:
            payload["with_plus1_counter"] = True
        # "a **legendary** card" (Niambi), "target **legendary** creature". A
        # supertype is a restriction like any other and rides the payload like
        # any other; until this key existed it rode nothing at all, and
        # "Destroy target legendary creature." lowered byte-identically to
        # "Destroy target creature." — the printed word consumed, recorded on
        # the AST, and then dropped on the way to the dispatcher.
        #
        # All or nothing. A phrase naming a supertype no matcher can test emits
        # no key rather than a narrowed one, so the field stays visibly set with
        # nothing behind it and the three gates below refuse the line. Emitting
        # the testable half would drop the other half silently, which is the
        # thing being fixed.
        if self.supertypes and set(self.supertypes) <= TYPE_LINE_SUPERTYPES:
            payload["supertypes"] = list(self.supertypes)
        return payload


@dataclass(frozen=True)
class PlayerRef:
    """A player or set of players."""
    kind: str  # you | each_player | each_opponent | target_player | target_opponent
               # | that_player | controller | owner | defending_player | chosen_player
    # "target player or planeswalker" (Chandra's Magmutt) — one chosen target
    # that may be a player face or a planeswalker permanent (CR 115.4 without
    # the creature half). Set only by the production that read the union, so a
    # lowering that never sees the phrase never sees the flag.
    or_planeswalker: bool = False


@dataclass(frozen=True)
class TargetSpec:
    """A quantified object reference: "target creature", "each creature with
    flying", "up to two creatures", "any target"."""
    quantifier: str            # target | each | all | up_to | any_target | this | a
    filter: ObjectFilter = field(default_factory=ObjectFilter)
    count: int = 1
    # "**X** target lands" (Candelabra of Tawnos). The count is the announced X
    # (CR 601.2b), so it is not a number until the ability is activated —
    # recorded as a fact rather than baked into `count`, because a count of 0
    # and a count that is *not yet known* are different things and a picker
    # shown 0 would offer nothing.
    count_from_x: bool = False
    # "another target creature" (Garruk, Savage Herald's −2): a second chosen
    # object that must differ from the sentence's earlier choice — not from the
    # ability's source, which is what the filter's other_than_source says.
    distinct_from_prior: bool = False
    # Whether the word "target" was printed. The quantifier alone cannot say:
    # "up to two target creatures" (Read the Tides — chosen at cast, CR 601.2c)
    # and "up to four lands" (Rewind — chosen on resolution, no targets at all)
    # both read as ``up_to``, and the two reach entirely different machinery.
    # The parser used to consume the word and discard the fact, which is the
    # round-15 finding this field closes.
    targeted: bool = False


# A recipient of damage/effects can be objects, players, or the "any target"
# shorthand (CR 115.4).
Recipient = Union[TargetSpec, PlayerRef]


# ---------------------------------------------------------------------------
# Durations, zones, costs, conditions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Duration:
    """How long a continuous effect lasts. ``None`` kind means permanent."""
    kind: str | None = None
    # until_end_of_turn | until_end_of_combat | this_turn | until_your_next_turn


@dataclass(frozen=True)
class Zone:
    name: str                       # battlefield | graveyard | hand | library | exile | stack
    owner: PlayerRef | None = None


@dataclass(frozen=True)
class ManaCost:
    """Mana pips, in the same shape ``ActivatedAbilityCost.mana`` uses."""
    pips: tuple[tuple[str, int], ...] = ()   # (("generic", 2), ("R", 1))


@dataclass(frozen=True)
class TapSelf:
    pass


@dataclass(frozen=True)
class SacrificeCost:
    filter: ObjectFilter = field(default_factory=ObjectFilter)


@dataclass(frozen=True)
class DiscardCost:
    count: Amount = field(default_factory=lambda: Fixed(1))
    # "Discard **the last card you drew this turn**" (Jandor's Ring). Not a
    # count: the card is named by history, so its payer has no choice at all,
    # and the engine tracks it on a dedicated flag
    # (``ActivatedAbilityCost.discard_last_drawn``). Folding it into ``count=1``
    # would say "discard any one card" — a strictly cheaper cost.
    last_drawn: bool = False
    # "Discard **a land card or Shrine card**" (Sanctum of Shattered Heights) —
    # the alternatives the payer may choose between, as printed. A tuple rather
    # than one filter because the "or" is a union across two *different*
    # characteristics (a card type and a subtype), which no single ObjectFilter
    # can say: its fields are AND'd, so "land" and "shrine" together would name
    # a card that is both. Empty is the unrestricted "Discard a card".
    filters: tuple[ObjectFilter, ...] = ()
    # "Discard a card **at random**" (Coral Helm). Not a narrowing of which
    # cards may pay — every card in hand may — but a removal of the *choice*:
    # the payer names nothing, and a cost the payer picks is a strictly better
    # cost than one chance picks. Its own flag rather than an empty filter list
    # for exactly that reason; the two shapes look identical and are not.
    at_random: bool = False
    #: "Discard **your hand**" (Subira, Tulzidi Caravanner). Every card, so
    #: there is nothing for the payer to choose and nothing for a filter to
    #: narrow — a different cost from "discard a card", not a count of it, which
    #: is why it is a flag rather than a very large ``count``. CR 601.2h still
    #: makes it payable with an empty hand: discarding nothing is discarding
    #: your hand.
    whole_hand: bool = False
    #: "Discard **this card**" (Waker of Waves) — the card the ability is
    #: printed on, discarded from the hand to pay. Distinct from a narrowed
    #: "discard a card" because nothing is chosen, and from ``whole_hand``
    #: because it is exactly one card and a specific one.
    self_card: bool = False


@dataclass(frozen=True)
class PutCounterCost:
    """"Put a **page** counter on this artifact" as part of an activation cost
    (Mazemind Tome).

    A cost that *adds* something rather than spending it, which is why it is its
    own node and not a negative counter removal: it can never be unpayable, and
    the thing it adds has no rules meaning of its own (CR 122.1) — only the
    card's own state trigger reads it.
    """
    kind: str


@dataclass(frozen=True)
class TapPermanentsCost:
    """"Tap two untapped Spirits you control" (Shacklegeist).

    N *other* permanents, named by a printed noun phrase — not the {T} symbol,
    which taps the source and is :attr:`ActivatedAbilityCost.requires_tap`. The
    count is printed, so it is data rather than part of the cost's identity.
    """
    count: int
    filter: ObjectFilter


@dataclass(frozen=True)
class PayLife:
    amount: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class ExileSelf:
    pass


@dataclass(frozen=True)
class RemoveCounterCost:
    counter: str = "+1/+1"
    count: Amount = field(default_factory=lambda: Fixed(1))


Cost = Union[
    ManaCost, TapSelf, SacrificeCost, DiscardCost, PayLife, ExileSelf, RemoveCounterCost
]


@dataclass(frozen=True)
class Controls:
    """"you control an Island", "the chosen player controls no nontoken permanents"."""
    who: PlayerRef
    filter: ObjectFilter
    comparison: Comparison | None = None
    #: "…two or more nonland, nontoken permanents **with the same name as one
    #: another**" (Chrome Replicator). A relation *between* the counted objects,
    #: which is why it sits here and not on `filter`: an ObjectFilter is tested
    #: against one permanent at a time, and no single permanent can answer
    #: whether it shares a name with something else. Set, `comparison` stops
    #: bounding the whole matching set and bounds the largest same-name group
    #: within it.
    shared_name: bool = False


@dataclass(frozen=True)
class EveryOf:
    """"if you control an Urza's Mine **and** an Urza's Tower" — every part must
    hold (CR 104 has no conjunction rule; this is plain English "and").

    Its own node rather than a repeated field on each condition, because the
    conjunction is about the clause list and not about any one clause: the
    Urza's cycle conjoins two `Controls`, and nothing stops a card conjoining a
    `Controls` with a `DiedThisTurn`.

    Named `EveryOf` rather than the obvious `AllOf` because that name is taken,
    by the *quantity* node meaning "all damage" / "any amount of mana". Two
    unrelated senses of "all" under one name in a flat re-export is how a
    conjunction of conditions ends up standing in for an unbounded amount.
    """
    conditions: tuple["Condition", ...]


@dataclass(frozen=True)
class IsState:
    """"it is untapped", "this creature is attacking"."""
    subject: TargetSpec
    state: str          # tapped | untapped | attacking | blocking
    negated: bool = False


@dataclass(frozen=True)
class DiedThisTurn:
    filter: ObjectFilter = field(default_factory=ObjectFilter)


@dataclass(frozen=True)
class LifeGainedThisTurn:
    """"if you gained 3 or more life this turn" (CR 603.4 intervening-if).

    A *history*, like :class:`DiedThisTurn` — no read of the board can answer
    it, which is why it is a condition node of its own rather than a comparison
    over some countable. The threshold travels on the node because a card
    printed with another number is the same production.
    """
    who: "PlayerRef"
    amount: int


@dataclass(frozen=True)
class PaidCost:
    cost: Cost | None = None


@dataclass(frozen=True)
class RawCondition:
    """A condition the grammar recognizes structurally but does not yet model
    semantically. Carries the source text so lowering can refuse it loudly
    rather than dropping it silently."""
    text: str


@dataclass(frozen=True)
class ReturnedToHandThisTurn:
    """"if a permanent was put into your hand from the battlefield this turn"
    (Barrin, Tolarian Archmage's end-step trigger, CR 603.4 intervening-if).

    A history, like :class:`DiedThisTurn`: no read of the board can answer it,
    so the game keeps a per-seat counter the bounce paths feed."""


@dataclass(frozen=True)
class CoinFlipResult:
    """"you win the flip" / "you lose the flip" (CR 705.2).

    A back-reference to a flip made earlier in the same resolution, never a
    board state — which is why lowering refuses one with no ``FlipCoin`` in
    front of it (the rule round 33 wrote down for "that much").
    """
    won: bool = True


@dataclass(frozen=True)
class RevealedCardIs:
    """``if it's a <filter>`` — a *present-tense* test on a card a previous
    sentence of the same effect revealed. (Track Down.)

    Its own node beside :class:`ItWas`, which is the past-tense one, and the
    distinction is not grammatical fussiness: "it **was** a creature card" asks
    what an object was before it left a zone (CR 608.2h, last-known
    information), while "it**'s** a creature card" asks what a card sitting in a
    library *is*. They read different producers and one of them can be answered
    by looking, so a single node would have to carry a tense flag and every
    reader would have to branch on it.
    """
    filter: "ObjectFilter"


@dataclass(frozen=True)
class ItWas:
    """"If **it** was a creature card" (Scavenging Ooze).

    A back-reference to the object an earlier step of this same effect moved,
    read as last-known information (CR 608.2h): the card is already in exile
    when this is asked, so the answer is what it was in the graveyard, not what
    the exile zone holds.

    The pronoun carries no referent, exactly as ``ThatMuch(None)`` carries no
    producer: the parser cannot see the sentence in front of it, so lowering is
    what resolves "it" against the values earlier steps recorded, and refuses
    when nothing recorded one (round 33's rule).
    """

    filter: "ObjectFilter"


@dataclass(frozen=True)
class HadPlus1Counter:
    """"if it had a +1/+1 counter on it" (Basri's Lieutenant, CR 603.4).

    About the creature that just died, so it is answerable only from
    last-known information (CR 603.10): the fire site records the answer as
    the trigger goes on the stack, and the resolution-side gate reads that
    record rather than a board the creature has already left."""


@dataclass(frozen=True)
class AttackersAimedAtYou:
    """"if **two or more of those creatures** are attacking you and/or
    planeswalkers you control" (Mangara, the Diplomat).

    CR 603.4's intervening-if over the batch the trigger fired on. Not a board
    count: "those creatures" is exactly the set declared in this attack, and a
    count of attacking creatures at large would include another opponent's.

    Both halves of the aim are one question — the player and their walkers — so
    there is one field and not two: a creature attacking a planeswalker its
    controller owns is attacking *them* for this purpose, and the card says so.
    """
    count: int


@dataclass(frozen=True)
class EnteredFrom:
    """"if it entered from your graveyard **or you cast it from your
    graveyard**" (Archfiend's Vessel) — CR 603.4's intervening-if asking where
    the permanent came from.

    Both halves, because they are genuinely two events: a permanent put onto the
    battlefield from a graveyard by a reanimation, and a permanent spell cast
    from a graveyard that then resolved. The card names both and the Demon
    arrives either way; implementing one would be a card that works under
    Unearth and not under its own flashback, which is a difference no player
    would attribute to the engine.

    ``zone`` is where it came from; ``or_cast`` says the cast half is printed
    too. A phrase naming only one is a different, narrower condition, so the
    field is not defaulted to True.
    """
    zone: str
    or_cast: bool = False


@dataclass(frozen=True)
class ItHappened:
    """"…**If you do**, …" after an action that was not optional.

    "Exile it. If you do, create a 5/5 black Demon creature token with flying."
    (Archfiend's Vessel.) The exile is not a choice — the branch is conditional
    on whether it actually *took place*, which for a source that has already
    left the battlefield it did not (CR 608.2b's "as much as possible").

    Distinct from the :class:`May` fold of the same words, which is a branch of a
    decision the player made. Reading this one as that would need a prompt
    nobody is owed; reading it as an unconditional next step would create the
    Demon whether or not the Vessel was there to exile.

    Carries no field: *which* step it refers to is always the one immediately
    before, and the lowering pairs them where that is known rather than naming a
    producer here, where it would be a second copy of ``_PRODUCES``.
    """


Condition = Union[
    EveryOf, CoinFlipResult, Controls, IsState, DiedThisTurn, HadPlus1Counter, ItWas,
    AttackersAimedAtYou, EnteredFrom, ItHappened, RevealedCardIs,
    LifeGainedThisTurn, PaidCost, RawCondition, ReturnedToHandThisTurn,
]


@dataclass(frozen=True)
class RawEffect:
    """An imperative clause the grammar structurally recognizes as an effect
    but has no typed node for yet. Never lowered — its presence marks the line
    as "parsed but not lowerable", which the ratchet tracks separately from a
    parse failure."""
    text: str
