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


Amount = Union[Fixed, Var, CountOf, ThatMuch, Half, AllOf, BoardCount]


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
    colors: tuple[str, ...] = ()              # mana symbols: "W", "U", ...
    excluded_colors: tuple[str, ...] = ()     # "nonblack"
    excluded_types: tuple[str, ...] = ()      # "nonartifact"
    excluded_subtypes: tuple[str, ...] = ()   # "non-Wall"
    with_keywords: tuple[str, ...] = ()       # "with flying"
    without_keywords: tuple[str, ...] = ()    # "without flying"
    controller: str | None = None             # "you" | "opponent" | "that_player"
    tapped: bool | None = None
    attacking: bool | None = None
    blocking: bool | None = None
    blocked: bool | None = None
    power: Comparison | None = None
    toughness: Comparison | None = None
    mana_value: Comparison | None = None
    named: str | None = None
    zone: str = "battlefield"
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
    # "that's one or more colors" (Ugin, the Spirit Dragon's −X): the object
    # has at least one color, read off its effective colors.
    colored: bool = False

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
            payload["subtype_filter"] = (
                self.subtypes[0] if len(self.subtypes) == 1 else list(self.subtypes)
            )
        if self.tapped:
            payload["tapped_only"] = True
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
        if self.attacking:
            payload["attacking_only"] = True
        if self.blocking:
            payload["blocking_only"] = True
        if self.other_than_source:
            payload["exclude_self"] = True
        if self.nontoken:
            payload["nontoken"] = True
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
class HadPlus1Counter:
    """"if it had a +1/+1 counter on it" (Basri's Lieutenant, CR 603.4).

    About the creature that just died, so it is answerable only from
    last-known information (CR 603.10): the fire site records the answer as
    the trigger goes on the stack, and the resolution-side gate reads that
    record rather than a board the creature has already left."""


Condition = Union[
    Controls, IsState, DiedThisTurn, HadPlus1Counter, LifeGainedThisTurn,
    PaidCost, RawCondition, ReturnedToHandThisTurn,
]


@dataclass(frozen=True)
class RawEffect:
    """An imperative clause the grammar structurally recognizes as an effect
    but has no typed node for yet. Never lowered — its presence marks the line
    as "parsed but not lowerable", which the ratchet tracks separately from a
    parse failure."""
    text: str
