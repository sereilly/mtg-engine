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
class CountOfDeathsThisWay:
    """"the number of creatures that died **this way**" (Hellfire) — how many
    objects the *preceding step of this same effect* destroyed.

    A third reading of "the number of creatures" and its own node beside
    :class:`CountOf` and :class:`CountOfDeaths` for the reason those two are
    each other's: this one counts neither the board nor the turn's history but
    one earlier step's result. Read as the plain filter it would count the
    survivors — on Hellfire, exactly the creatures that did *not* die — and read
    as the turn history it would fold in every unrelated death since untap.

    The set is therefore a back-reference, and lowering refuses it unless a step
    of the same effect actually recorded one: with no producer "this way" names
    nothing, and a zero is a number the card never printed.
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

    *base* is the constant such a count subtracts against, and it is **payload
    rather than part of the name** for the reason the land type in
    ``combat_restrictions.py`` is: "3 minus the number of cards in their hand"
    (The Rack) and "the number of cards in their hand minus 4" (Black Vise) are
    one arithmetic with one number changed. Spelling the 4 into the phrase made
    every other threshold a non-match — the false-negative failure — and The
    Rack was a name-keyed card hook purely because its number was 3. A count
    whose meaning needs no constant leaves it None.
    """
    name: str
    base: int | None = None


@dataclass(frozen=True)
class Plus:
    """``1 plus the number of creature cards in your graveyard`` (Wall of
    Tombstones), ``1 plus the power of target creature …`` (Sentinel) — a sum
    of two printed quantities.

    A node rather than arithmetic folded at parse time because the right-hand
    side is usually not a number yet: a count or a characteristic read at
    resolution. Every lowering written before it exists refuses it by default,
    which is the union's standing guarantee for a new quantity.
    """
    left: "Amount"
    right: "Amount"


@dataclass(frozen=True)
class Times:
    """``twice the number of white creatures that player controls`` (Jovial
    Evil) — a printed quantity multiplied by a printed factor.

    The mirror of :class:`Half`, and a node for the same reason :class:`Plus`
    is one: the thing being scaled is usually not a number yet, so the
    arithmetic cannot be folded at parse time. *factor* is payload — "twice"
    and "three times" are one shape with one number changed, and spelling the 2
    into the phrase would make every other multiple a non-match, which is the
    false-negative the ``BoardCount`` docstring above records.

    Every lowering written before it exists refuses it by default, which is the
    union's standing guarantee for a new quantity: a scaled count read as a
    plain one would deal half the damage the card prints.
    """
    factor: int
    of: "Amount"


@dataclass(frozen=True)
class PowerOfSubject:
    """``the power of target creature blocking or blocked by this creature``
    (Sentinel) — one named object's power, read at resolution.

    Beside :class:`GreatestPowerAmong` and not inside it: that node aggregates
    over a described *set*, this one reads a single referent — typically a
    chosen target, which means the quantity itself is what carries the
    sentence's target. A lowering that accepts it must therefore describe the
    target it names, or refuse; dropping it would leave a picker with nothing
    to enumerate.
    """
    subject: "TargetSpec"


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


Amount = Union[Fixed, Var, CountOf, CountersOnSource, ThatMuch, Half, Times, AllOf, AnyNumber, BoardCount, Plus, PowerOfSubject]


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
    # "target **instant or Aura** spell" (Avoid Fate, Ring of Immortals). A
    # union whose alternatives do not all live on one axis: "instant" is a card
    # type (CR 205.2) and "Aura" a subtype (CR 205.3), and every matcher in this
    # engine ANDs `card_types` against `subtypes` — so recording the phrase in
    # those two fields would describe an instant that is also an Aura, a set no
    # card can ever be in. Its own field for the reason `any_states` is one: a
    # union spelled into the fields it happens to straddle is a union the next
    # printed pair cannot use.
    #
    # Each alternative carries the axis it was read on ("card_type" / "subtype")
    # rather than the bare word, because the two vocabularies are not disjoint
    # in principle and a matcher guessing which one it was handed is a matcher
    # that can guess wrong.
    any_classes: tuple[tuple[str, str], ...] = ()
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
    #: A union of printed state adjectives — "attacking or blocking",
    #: "tapped or blocking". The words as printed, because what each one
    #: *means* is one answer the matcher owns; a pair spelled into a
    #: boolean here made every other pair a non-match.
    any_states: tuple[str, ...] = ()
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
    # "…activated ability **from an artifact source**" (Rust, Ayesha Tanaka).
    # A narrowing on the *permanent the ability came from*, which is the only
    # thing about an ability on the stack there is to narrow by — it has no card
    # and no type line of its own (CR 113.7a). Beside `ability_kinds` because it
    # is the same object's other adjective, and a tuple because "an artifact or
    # enchantment source" is the same sentence with one more word.
    ability_source_types: tuple[str, ...] = ()
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
    # "attached to a creature or land" (Enchantment Alteration) — the host by
    # card type, which a read of the attachment alone *can* answer.
    attached_to_types: tuple[str, ...] = ()
    # "another permanent **of that type**" — shares a card type with what the
    # sentence's other clause named. Only a lowering knowing that object can
    # resolve it; one that does not must refuse.
    of_bound_type: bool = False
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
    # "…**that targets a permanent you control**" (Avoid Fate, Ring of
    # Immortals). A restriction on what the *spell* chose, not on what the spell
    # is — so it is a nested noun phrase rather than more adjectives, and it is
    # relative twice over: it needs the stack object's recorded targets and the
    # seat "you control" is measured against. Never emitted by ``to_payload``
    # and never reaches ``permanent_matches_filter``; the one lowering written
    # for it carries the inner phrase as its own payload key and the handler
    # that has the stack item asks ``subject_matches`` of each target.
    targets_object: "ObjectFilter | None" = None
    # "blocking or blocked by this creature" (Sentinel) — the object is in
    # combat with the ability's own source (CR 509). Relative, like
    # ``other_than_source``: no read of the object alone can answer it, so
    # ``to_payload`` never emits it and ``permanent_matches_filter`` is never
    # told about it — the one lowering that accepts it carries the relation as
    # its own payload key and the handler that has the source tests it.
    in_combat_with_source: bool = False
    # "creatures that dealt damage to it this turn" (Brine Hag) — a *history*
    # relative to the source, read off the damage record the victim carries
    # (``damaged_by_sources_this_turn``). Same discipline as the field above:
    # never emitted, so every lowering not written for it refuses the phrase
    # instead of quietly widening to every creature.
    dealt_damage_to_source_this_turn: bool = False
    # "all creatures **blocking this creature**" (The Wretched). The set of
    # creatures currently declared as blockers of the ability's own source
    # (CR 509.1a). *Relative* like ``created_with_source``: no read of the
    # blocker alone can answer it, so it emits no payload key and never
    # reaches ``permanent_matches_filter`` — the one lowering that admits it
    # resolves the set from the fire-time combat record instead, and any
    # other lowering that meets it refuses by name.
    blocking_source: bool = False
    # "…all creatures that were **blocked by that creature this turn**"
    # (Glyph of Doom). A history relative to the object a delayed triggered
    # ability was bound to, answered from the block record that creature
    # carries rather than from any characteristic of the creatures swept — so,
    # like `dealt_damage_to_source_this_turn` above it, it is a flag the one
    # lowering written for it reads and every other lowering refuses by name.
    # "This turn" is required and "that creature" is required: a turn holds
    # several combats, and without a bound object the phrase names a blocker
    # nobody recorded.
    blocked_by_bound_object: bool = False

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
        if len(self.colors) == 1:
            payload["color_filter"] = self.colors[0]
        elif self.colors:
            # "a green **or** white creature" — an object answering *any* of
            # them, which is what the printed "or" says. Its own key rather than
            # a list-valued `color_filter`, because that key means "has this
            # colour" to every matcher already reading it and a second type
            # under one name is how two readers come to disagree.
            #
            # This branch used to be `colors[0]`, silently dropping the rest:
            # no noun phrase could produce two colours, so nothing exercised it
            # — a dropped rider waiting for the parser to grow the union above.
            payload["any_colors"] = list(self.colors)
        if self.excluded_colors:
            payload["exclude_colors"] = list(self.excluded_colors)
        if self.excluded_types:
            payload["exclude_types"] = list(self.excluded_types)
        if self.attached_to_types:
            payload["attached_to_types"] = list(self.attached_to_types)
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
        if self.any_states:
            payload["any_states"] = list(self.any_states)
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
    quantifier: str            # target | each | all | up_to | any_target | this | it | a
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
    # | until_your_next_upkeep | until_end_of_your_next_upkeep | while_source_tapped


@dataclass(frozen=True)
class ManaValueOfSubject:
    """"…, where X is **its** mana value." (Great Defender, Subdue, Kry Shield,
    In the Eye of Chaos.)

    The other kind of where-clause: `CountOf` counts a set of objects, this one
    reads a characteristic off the single object the sentence already named —
    the creature it pumps, the spell it counters. So it carries nothing at all;
    "its" is the sentence's own subject and the lowering is what knows which
    object that is.
    """


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
class RawEffect:
    """An imperative clause the grammar structurally recognizes as an effect
    but has no typed node for yet. Never lowered — its presence marks the line
    as "parsed but not lowerable", which the ratchet tracks separately from a
    parse failure."""
    text: str
