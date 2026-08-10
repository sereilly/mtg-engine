"""Typed AST for Magic oracle text.

Every node is a frozen dataclass holding only hashable values (tuples, never
lists), so an AST compares by value — the property the lowering goldens and the
deletion probe rely on.

This module imports nothing from the rest of the engine, mirroring
``engine/oracle_types.py``: the lowering, tests and scripts can import it
without any risk of a cycle.

**The node inventory is append-only.** New fields must carry defaults and new
node types must be additive; repurposing an existing field breaks every golden
test and every ratchet entry at once. Schema churn is what kills incremental
parser migrations, so the full inventory is defined here up front even where
only part of it is reachable from the productions implemented so far.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

# ---------------------------------------------------------------------------
# Quantities (engine/grammar/amounts.py)
# ---------------------------------------------------------------------------


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
class ThatMuch:
    """A back-reference to a value produced earlier in the same resolution
    ("you gain that much life", "equal to the damage dealt"). *source* names the
    key the earlier effect recorded, e.g. "damage_dealt"."""
    source: str


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
    # "other than this creature" / "other Zombies" — excludes the source.
    other_than_source: bool = False
    # "this creature" / "this artifact" — the ability's own source.
    is_source: bool = False
    # "enchanted creature" — the permanent this Aura is attached to.
    is_enchanted: bool = False

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
        return payload


@dataclass(frozen=True)
class PlayerRef:
    """A player or set of players."""
    kind: str  # you | each_player | each_opponent | target_player | target_opponent
               # | that_player | controller | owner | defending_player | chosen_player


@dataclass(frozen=True)
class TargetSpec:
    """A quantified object reference: "target creature", "each creature with
    flying", "up to two creatures", "any target"."""
    quantifier: str            # target | each | all | up_to | any_target | this | a
    filter: ObjectFilter = field(default_factory=ObjectFilter)
    count: int = 1


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
class PaidCost:
    cost: Cost | None = None


@dataclass(frozen=True)
class RawCondition:
    """A condition the grammar recognizes structurally but does not yet model
    semantically. Carries the source text so lowering can refuse it loudly
    rather than dropping it silently."""
    text: str


Condition = Union[Controls, IsState, DiedThisTurn, PaidCost, RawCondition]


# ---------------------------------------------------------------------------
# Effects (leaf statements)
# ---------------------------------------------------------------------------


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
class Pump:
    subject: Recipient
    power: Amount
    toughness: Amount
    duration: Duration = field(default_factory=Duration)
    # "gets -2/-2": the sign is carried here rather than in the Amount so
    # "+X/+0" and "-X/-0" share one quantity vocabulary.
    power_negative: bool = False
    toughness_negative: bool = False


@dataclass(frozen=True)
class SetBasePT:
    subject: Recipient
    power: Amount | None
    toughness: Amount | None
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class GainKeyword:
    subject: Recipient
    keywords: tuple[str, ...]
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class LoseKeyword:
    subject: Recipient
    keywords: tuple[str, ...]
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class PutCounter:
    subject: Recipient
    counter: str = "+1/+1"
    count: Amount = field(default_factory=lambda: Fixed(1))
    up_to: bool = False


@dataclass(frozen=True)
class RemoveCounter:
    subject: Recipient
    counter: str = "+1/+1"
    count: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class GainLife:
    player: PlayerRef
    amount: Amount


@dataclass(frozen=True)
class LoseLife:
    player: PlayerRef
    amount: Amount


@dataclass(frozen=True)
class Draw:
    player: PlayerRef
    count: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class Discard:
    player: PlayerRef
    count: Amount = field(default_factory=lambda: Fixed(1))
    at_random: bool = False


@dataclass(frozen=True)
class Mill:
    """"Target player mills N cards." (CR 701.13a, Millstone.)

    A zone change like :class:`Draw`, and kept separate from it for the same
    reason draw and discard are separate: the cards move library-to-graveyard
    without ever being in a hand, so nothing about drawing describes it.
    """
    player: PlayerRef
    count: Amount = field(default_factory=lambda: Fixed(1))


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
class ChangeText:
    """``Change the text of <subject> by replacing all instances of one <mode>
    with another.`` (CR 612 — Magical Hack, Sleight of Mind.)

    *mode* names which vocabulary is swapped, because that is the whole
    difference between the two printings and the only thing the handler reads.
    It is a closed set: a wording naming some other vocabulary is a text change
    the engine's substitution does not implement, and must fail to parse rather
    than arrive here as a mode nothing knows.
    """

    subject: Recipient
    mode: str


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
class CounterSpell:
    subject: TargetSpec
    # "unless its controller pays {X}" (Power Sink) — CR 118.3c: the spell is
    # countered only if the cost goes unpaid. Modelled as a field rather than a
    # ``Conditional`` because the payment is offered to a *different* player as
    # part of countering, which is the counter flow's job, not a second step.
    unless_pays: ManaCost | None = None
    # The named penalty a card imposes when that cost goes unpaid ("…they tap
    # all lands with mana abilities they control and lose all unspent mana").
    # A name, not a statement: the counter flow performs it while countering,
    # so it never becomes an instruction of its own — but recording *which*
    # penalty was written means lowering can refuse one nothing performs
    # instead of consuming the sentence and dropping it.
    unpaid_penalty: str | None = None


@dataclass(frozen=True)
class ReturnToZone:
    subject: Recipient
    to: Zone
    from_zone: Zone | None = None


@dataclass(frozen=True)
class CreateToken:
    count: Amount
    power: int
    toughness: int
    name: str
    colors: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class AddMana:
    pips: tuple[tuple[str, int], ...] = ()
    any_color: int = 0
    # The clause verbatim. The current mana handler re-reads the text rather
    # than taking structured pips, so lowering passes it through unchanged;
    # this field goes away when the handler takes ``pips`` directly.
    source_text: str = ""


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
class BecomeColor:
    """"Target spell or permanent becomes red." (the Lace cycle, CR 105.)

    A colour *replacement*, not an addition — the object becomes that colour
    instead of its own. Mana symbols are unaffected, which is reminder text the
    lexer already strips.
    """
    subject: Recipient
    color: str


@dataclass(frozen=True)
class SearchLibrary:
    player: PlayerRef
    filter: ObjectFilter
    to: Zone


@dataclass(frozen=True)
class Shuffle:
    player: PlayerRef


@dataclass(frozen=True)
class ExtraTurn:
    player: PlayerRef


@dataclass(frozen=True)
class WinGame:
    """"You win the game." (CR 104.2b.)"""
    player: PlayerRef


@dataclass(frozen=True)
class LoseGame:
    """"Target player loses the game." / "You lose the game." (CR 104.3e.)"""
    player: PlayerRef


@dataclass(frozen=True)
class DrawGame:
    """"The game is a draw." (CR 104.4c.)

    No player field: the sentence has no subject, and the effect ends the game
    for everyone. Its own node rather than a ``WinGame`` with a flag, because
    104.4 is a third outcome and not a win with an asterisk.
    """


@dataclass(frozen=True)
class LookAtHand:
    """"Look at target player's hand." (Glasses of Urza, CR 701.16.)

    An information effect: nothing about the game state changes, so it is a
    leaf of its own rather than a flavour of ``ReturnToZone``. The player is
    modeled rather than assumed, because *whose* hand is looked at is the whole
    content of the clause.
    """
    player: PlayerRef


@dataclass(frozen=True)
class CantBe:
    """"<subject> can't be <participle> <duration>." (CR 701.15 regenerate,
    CR 509.1b blocking restrictions.)

    One node for the whole family, with the participle carried as data. Minting
    a node per restriction would put the parser back in the business of knowing
    which effects exist; here an unmodelled participle still reaches lowering,
    which refuses it *by name* — a visibly unsupported card instead of a clause
    nothing implements.

    ``duration`` is not optional in practice: with no duration the sentence is a
    continuous restriction (an Aura's "Enchanted creature can't be blocked"),
    which is a static ability rather than a one-shot effect, and lowering
    separates the two.
    """
    subject: Recipient
    action: str                                    # "regenerated" | "blocked"
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class RawEffect:
    """An imperative clause the grammar structurally recognizes as an effect
    but has no typed node for yet. Never lowered — its presence marks the line
    as "parsed but not lowerable", which the ratchet tracks separately from a
    parse failure."""
    text: str


Effect = Union[
    DealDamage, Pump, SetBasePT, GainKeyword, LoseKeyword, PutCounter, RemoveCounter,
    GainLife, LoseLife, Draw, Discard, Mill, Destroy, Sacrifice, Exile, Tap, Untap,
    TapOrUntap,
    Regenerate, CounterSpell, ReturnToZone, CreateToken, AddMana,
    AddManaForTappedLand, PreventDamage,
    SearchLibrary, Shuffle, ExtraTurn, WinGame, LoseGame, DrawGame, BecomeColor,
    SacrificeUnlessPay, DamageUnlessPay, LookAtHand, CantBe, ChangeText,
    GainControl, RawEffect,
]


# ---------------------------------------------------------------------------
# Statements (composable) — this is what kills the conjunction-kind explosion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sequence:
    """Steps performed in order: sentence chains and "…, then …"."""
    steps: tuple["Statement", ...]


@dataclass(frozen=True)
class Conjunction:
    """Effects joined by "and" within one sentence."""
    effects: tuple["Statement", ...]


@dataclass(frozen=True)
class Conditional:
    """"if <condition>, <then>" / "<then> unless <condition>"."""
    condition: Condition
    then: "Statement"
    otherwise: "Statement | None" = None


@dataclass(frozen=True)
class May:
    """"You may pay {2}. If you do, …" — an optional cost or action with
    branches for taking it and declining it."""
    actor: PlayerRef
    cost: Cost | None = None
    action: "Statement | None" = None
    then: "Statement | None" = None
    otherwise: "Statement | None" = None


@dataclass(frozen=True)
class ForEach:
    """"for each creature you control, …" — one repetition per member of a set.

    The set is normally something the board holds right now (an
    ``ObjectFilter``) or the players (a ``PlayerRef``). It can also be a set the
    board no longer holds: "for each creature that **died** this turn" iterates
    a history, which is what :class:`DiedThisTurn` names. Reading that as the
    plain filter "creature" would count the creatures still on the battlefield
    — a different number, and one that moves in the opposite direction.
    """
    iterator: ObjectFilter | PlayerRef | DiedThisTurn
    effect: "Statement"


Statement = Union[Sequence, Conjunction, Conditional, May, ForEach, Effect]


# ---------------------------------------------------------------------------
# Ability lines (one oracle line compiles to exactly one of these)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TriggerEvent:
    """The event half of a triggered ability. ``kind`` intentionally reuses the
    legacy trigger-kind strings ("creature_dies", "upkeep_self", …) so the 23
    existing ``condition_kinds=`` dispatch sites keep working unchanged while
    the grammar migration is in flight."""
    kind: str
    word: str = "whenever"        # whenever | when | at
    subject: ObjectFilter | PlayerRef | None = None


@dataclass(frozen=True)
class KeywordInstance:
    name: str
    argument: str | None = None   # "protection from red", "landwalk: island"


@dataclass(frozen=True)
class ActivationRestriction:
    """"Activate only during your upkeep." / "Any player may activate this ability.\""""
    text: str
    timing: str | None = None
    any_player: bool = False


@dataclass(frozen=True)
class SpellEffectLine:
    """A one-shot effect line: an instant/sorcery's text, or the effect half of
    a triggered or activated ability."""
    statement: Statement


@dataclass(frozen=True)
class TriggeredAbilityNode:
    event: TriggerEvent
    statement: Statement
    # CR 603.4 intervening-if: checked both when the trigger would fire and
    # again on resolution. Modeled as a field rather than dropped — the legacy
    # compiler silently discarded these, so conditional triggers always fired.
    intervening_if: Condition | None = None


@dataclass(frozen=True)
class ActivatedAbilityNode:
    costs: tuple[Cost, ...]
    statement: Statement
    restriction: ActivationRestriction | None = None


@dataclass(frozen=True)
class StaticAbilityNode:
    """A continuous effect. Lowering for most static shapes waits on the CR 613
    layers engine, so these are commonly "parsed but not lowered"."""
    effect: Statement
    condition: Condition | None = None
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class KeywordLine:
    keywords: tuple[KeywordInstance, ...]


@dataclass(frozen=True)
class RegistryLine:
    """A line whose behaviour is implemented by a text-keyed sidecar registry
    rather than by any ``OracleInstruction``.

    "Players skip their untap steps.", "Cast this spell only during the declare
    blockers step.", "If you would gain life, draw that many cards instead." —
    none of these describe a one-shot effect the stack could resolve. They are
    read straight off the card's oracle text by the untap step, the cast-timing
    gate and the CR 614 replacement interceptors respectively. There is nothing
    for the compiler to store and nothing for a handler to run.

    Like :class:`KeywordLine`, this node lowers to zero instructions, which is
    the whole point: it says "accounted for, elsewhere" instead of leaving the
    line in the backlog under a misleading "unrecognized effect verb".

    ``registry`` names the implementing module (``engine/grammar/registries.py``
    maps each one to its matcher). ``text`` is the line **verbatim** — the
    replacement interceptors self-select by looking for exactly this string in
    ``permanent.card.oracle_text``, so normalizing it here would be a way to
    quietly unhook Lich, Library of Leng and Ali from Cairo.
    """

    registry: str
    text: str


@dataclass(frozen=True)
class DerivedLine:
    """A line whose instruction a derivation table computes in full.

    "All Swamps are 1/1 black creatures that are still lands." (Kormus Bell),
    "All Mountains are Plains." (Conversion), Jihad's conditional anthem. Each
    is a template with parameters, and for each of them one engine module
    already derives those parameters from the printed sentence and hands the
    consumer a payload — so a production here would be a second reading of the
    same text, free to disagree with the first.

    Unlike :class:`RegistryLine` this *does* lower, to exactly the instruction
    the table produces (``engine/grammar/derived.py`` names the table for each
    shape). ``table`` labels the node; nothing dispatches on it. ``text`` is the
    line verbatim, and the lowering re-asks the same pure matcher rather than
    carrying an instruction through the AST — one function, two callers, nothing
    to drift.
    """

    table: str
    text: str


@dataclass(frozen=True)
class ModalNode:
    choose_count: int
    options: tuple[SpellEffectLine, ...]


AbilityNode = Union[
    SpellEffectLine, TriggeredAbilityNode, ActivatedAbilityNode,
    StaticAbilityNode, KeywordLine, RegistryLine, DerivedLine, ModalNode,
]


__all__ = [
    # amounts
    "Amount", "Fixed", "Var", "CountOf", "ThatMuch", "Half", "AllOf",
    # nouns
    "Comparison", "ObjectFilter", "PlayerRef", "TargetSpec", "Recipient",
    # support
    "Duration", "Zone", "Cost", "ManaCost", "TapSelf", "SacrificeCost",
    "DiscardCost", "PayLife", "ExileSelf", "RemoveCounterCost",
    "Condition", "Controls", "IsState", "DiedThisTurn", "PaidCost", "RawCondition",
    # effects
    "Effect", "DamageRiders", "DealDamage", "Pump", "SetBasePT", "GainKeyword",
    "LoseKeyword", "PutCounter", "RemoveCounter", "GainLife", "LoseLife", "Draw",
    "Discard", "Mill", "Destroy", "Sacrifice", "Exile", "Tap", "Untap", "TapOrUntap",
    "Regenerate",
    "BecomeColor", "SacrificeUnlessPay", "LookAtHand", "CantBe", "ChangeText",
    "GainControl",
    "CounterSpell", "ReturnToZone", "CreateToken", "AddMana",
    "AddManaForTappedLand", "PreventDamage",
    "SearchLibrary", "Shuffle", "ExtraTurn", "WinGame", "LoseGame", "DrawGame",
    "RawEffect",
    # statements
    "Statement", "Sequence", "Conjunction", "Conditional", "May", "ForEach",
    # abilities
    "AbilityNode", "TriggerEvent", "KeywordInstance", "ActivationRestriction",
    "SpellEffectLine", "TriggeredAbilityNode", "ActivatedAbilityNode",
    "StaticAbilityNode", "KeywordLine", "RegistryLine", "DerivedLine", "ModalNode",
]


@dataclass(frozen=True)
class CombatRestriction:
    """``<subject> can't attack unless …`` / ``can't block creatures with …``.

    A restriction on when the permanent may attack or block (CR 506, 509). It
    is a *static* ability, but unlike most static shapes it does not wait on the
    layers engine: it changes what a player may declare, not what the object's
    characteristics are, and the combat steps already dispatch on the
    instruction it lowers to.

    ``kind`` is the instruction kind, and ``payload`` its data — the land type
    or the power threshold — so the number and the noun stay parameters rather
    than becoming part of the kind's name.
    """

    subject: Recipient
    kind: str
    payload: tuple[tuple[str, object], ...] = ()
