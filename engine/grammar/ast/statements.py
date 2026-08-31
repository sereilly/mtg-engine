"""Composition, ability lines, and the unions that close over the families.

The roof of the package, and the only module that sees all seven families at
once. It holds:

* `Effect`, the union of every leaf node — which is exactly why it cannot live
  beside any one of them;
* the composable statement nodes (`Sequence`, `Conjunction`, `Conditional`,
  `May`, `ForEach`) and `Statement`. These are what kills the conjunction-kind
  explosion: "deal damage and gain life" is two effects under a `Conjunction`,
  never a fused node;
* the ability-line nodes — one printed line compiles to exactly one of them —
  and `AbilityNode`.

Nothing in a family imports this module, and this module imports every family:
that one-way edge is the layer. It is the type of `grammar/statements.py`, which
sits above `grammar/effects/` on the parsing side for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from .conditions import Condition
from .conditions import ChosenThisWay, DiedThisTurn, DiedThisWay, ExiledThisWay
from .costs import Cost
from ._core import (
    Duration,
    ObjectFilter,
    PlayerRef,
    RawEffect,
)
from .damage import (
    DamageCantBePreventedOrRedirected,
    DamageRidersUntilEndOfTurn,
    DamageUnlessPay,
    Fight,
    CoinFlipDamageLoop,
    DamageThoseDamagedThisGame,
    DealDamage,
    PreventDamage,
    RedirectDamage,
    UpkeepDamageUnlessCost,
)
from .characteristics import (
    BecomeColor,
    ChangeSupertype,
    GainType,
    BecomeCreature,
    ChangeBasePT,
    ChangeText,
    GainAbilityText,
    GainKeyword,
    LoseKeyword,
    Pump,
    DoublePower,
    SwitchPT,
    PlayerGetsCounters,
    PutCounter,
    RemoveCounter,
    SetBasePT,
)
from .board import (
    DelayedSelfAction,
    DoesntUntapWhileSourceTapped,
    SacrificeExpansionPermanents,
    ShuffleGraveyardIntoLibrary,
    ShuffleHandIntoLibrary,
    Destroy,
    Exile,
    ExileUntilLeavesOrUntaps,
    PutSourceIntoZone,
    Attach,
    ExchangeControl,
    ExchangeGreatestManaValue,
    GainControl,
    PhaseOut,
    PutOnLibraryBottom,
    PutOnLibraryTop,
    PutOntoBattlefield,
    Regenerate,
    ReturnToZone,
    ChoosePermanent,
    Sacrifice,
    DestroyUnlessPay,
    DestroyEachUnlessPaid,
    SacrificeUnlessPay,
    Tap,
    TapOrUntap,
    DoesntUntapNextStep,
    Untap,
)
from .mana import (
    AddMana,
    AddManaForTappedLand,
    ProducesManaInstead,
    SpendManaAsThough,
)
from .cards import (
    CastPermission,
    Discard,
    Draw,
    ExileCostSacrifices,
    ExileGraveyard,
    RevealHand,
    RevealHandAndChoose,
    RevealRandomFromHand,
    DiscardRevealedUnlessPayLife,
    ExileTopOfLibrary,
    PutExiledWithSource,
    ChooseCardsInHand,
    LookAtHand,
    PutIteratedCardOnLibrary,
    LookAtLibraryTop,
    LookTopExileRandom,
    LookTopPickToHand,
    Mill,
    PutHandCardsOnLibrary,
    RevealTop,
    ExileGraveyardUntilLeaves,
    CastFromExiledWith,
    NameAndRandomReveal,
    NameAndStrip,
    NameThenRevealTop,
    RevealUntil,
    RevealTopToHandOrBottom,
    Scry,
    OwnershipExchangeUnlessPaid,
    RandomRevealOwnershipExchange,
    SearchAndExile,
    TransmuteBySacrifice,
    NameThenConsult,
    SearchLibrary,
    SearchPlayerLibrary,
    Shuffle,
)
from .stack import (
    ChangeTarget,
    ChooseTarget,
    CopySpell,
    CopyThatSpell,
    CounterAbility,
    CounterSpell,
    ModalNode,
)
from .combat import (
    AssignsNoCombatDamage,
    AttackingDoesntTap,
    CantBe,
    AttackAsThough,
    CombatRestriction,
    ForceChosenCreatureToAttack,
    RemoveFromCombat,
)
from .game import (
    Ante,
    CreateEmblem,
    CreateCopyToken,
    CreateToken,
    DrawGame,
    EndTheTurn,
    ExtraTurn,
    ChooseNumber,
    ChoosePlayerWhoCast,
    FlipCoin,
    GainLife,
    LoseGame,
    LoseLife,
    PayLife,
    SetLifeTotal,
    ExchangeLifeTotals,
    WinGame,
)


Effect = Union[
    CoinFlipDamageLoop,
    DamageThoseDamagedThisGame,
    DamageRidersUntilEndOfTurn,
    DealDamage, Pump, SetBasePT, ChangeBasePT, GainAbilityText, GainKeyword, GainType, ChangeSupertype, LoseKeyword, PlayerGetsCounters, PutCounter, RemoveCounter,
    DoublePower, SwitchPT,
    GainLife, LoseLife, PayLife, SetLifeTotal, ExchangeLifeTotals, Ante, Draw, Discard, Mill, PutHandCardsOnLibrary, Scry, Destroy, Sacrifice,
    SacrificeExpansionPermanents, ShuffleGraveyardIntoLibrary, ShuffleHandIntoLibrary, Exile,
    ExileUntilLeavesOrUntaps, PutSourceIntoZone, Tap, Untap,
    TapOrUntap, DoesntUntapNextStep, DoesntUntapWhileSourceTapped,
    DelayedSelfAction, Attach, ExchangeControl, ExchangeGreatestManaValue,
    Regenerate, ChangeTarget, ChooseTarget, CopySpell, CopyThatSpell, CounterAbility, CounterSpell, ModalNode, ReturnToZone, ChoosePermanent, CreateToken, CreateCopyToken, AddMana,
    PutOnLibraryTop, PutOnLibraryBottom, PutOntoBattlefield, RevealTopToHandOrBottom, CreateEmblem,
    RevealTop, RevealUntil, NameAndStrip, NameAndRandomReveal, NameThenRevealTop,
    ChooseCardsInHand, PutIteratedCardOnLibrary,
    ExileGraveyardUntilLeaves, CastFromExiledWith, ForceChosenCreatureToAttack,
    PhaseOut,
    AddManaForTappedLand, ProducesManaInstead, SpendManaAsThough, PreventDamage,
    RedirectDamage, DamageCantBePreventedOrRedirected, UpkeepDamageUnlessCost,
    NameThenConsult,
    SearchLibrary, SearchPlayerLibrary, SearchAndExile, TransmuteBySacrifice,
    OwnershipExchangeUnlessPaid,
    RandomRevealOwnershipExchange,
    ExileTopOfLibrary, PutExiledWithSource, ExileGraveyard, ExileCostSacrifices,
    CastPermission, LookTopExileRandom, LookTopPickToHand,
    RevealHand,
    RevealHandAndChoose,
    RevealRandomFromHand,
    DiscardRevealedUnlessPayLife,
    Shuffle, ExtraTurn, EndTheTurn, ChooseNumber, ChoosePlayerWhoCast, FlipCoin, WinGame, LoseGame, DrawGame, BecomeColor, BecomeCreature,
    SacrificeUnlessPay, DestroyUnlessPay, DestroyEachUnlessPaid, DamageUnlessPay, Fight, LookAtHand, LookAtLibraryTop,
    CantBe, AttackAsThough, CombatRestriction, AttackingDoesntTap,
    AssignsNoCombatDamage,
    RemoveFromCombat,
    ChangeText, GainControl, RawEffect,
]
# `CombatRestriction` was absent from this union for as long as it existed: it
# was defined *after* `__all__` at the bottom of the pre-split `ast.py`, so the
# module never exported it either, and `lower_statement` dispatched on it like
# any other leaf anyway. Nothing broke, because the union is an annotation and
# annotations are lazy — which is exactly why nobody noticed, and why
# `tests/engine/test_ast_effect_union.py` now checks the membership by
# construction rather than by whoever last read this list.
#
# `DamageRiders` is deliberately NOT here. It is a field of `DealDamage` — "it
# can't be regenerated", "if it would die this turn, exile it instead" — never a
# statement in its own right, and nothing dispatches on it.


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
class UnlessPlayerPays:
    """"**Unless an opponent pays {2},** gain control of target artifact …"
    (Scarwood Bandits.)

    An offer made to *another* seat, with the effect as its declined branch. Its
    own node rather than a ``May`` whose actor is an opponent, and the printed
    sentence is why: a ``May`` is an offer whose *action* is what the payer
    does, and its ``then``/``otherwise`` branches belong to the ability's own
    controller. Here the payment is the whole of what the other seat may do and
    the effect happens only when nobody takes it — reading one as the other
    would put the steal on the accepting branch.

    ``payer`` is the printed player reference, which is a *class* of seat
    ("an opponent") rather than one chosen player: CR 601.2b's cost announcement
    picks nobody, so every seat the phrase names is asked in turn until one pays.
    """
    payer: PlayerRef
    cost: "ManaCost"
    otherwise: "Statement"


@dataclass(frozen=True)
class May:
    """"You may pay {2}. If you do, …" — an optional cost or action with
    branches for taking it and declining it."""
    actor: PlayerRef
    cost: Cost | None = None
    action: "Statement | None" = None
    then: "Statement | None" = None
    otherwise: "Statement | None" = None
    #: "You may pay {1}. **When you do**, you may tap or untap target creature."
    #: (Tolarian Kraken.) CR 603.12's reflexive triggered ability, and a separate
    #: field from ``then`` because it is a separate *ability*: it is created by
    #: the payment and chooses its own targets when it is created, where a
    #: "if you do" branch is the rest of this same resolution and has only the
    #: targets this one already chose. Reading one as the other is how a trigger
    #: with a target of its own ends up pointed at whatever the producing action
    #: happened to name.
    reflexive: "Statement | None" = None
    #: "…unless that player pays {1} **or 1 life**." (Erosion.) CR 118.8's
    #: alternative payment: one offer the payer may cover either way, so it is a
    #: second reading of ``cost`` rather than a second offer. Two ``May`` nodes
    #: would be two prompts and two penalties -- declining the first would
    #: destroy the land before the second was ever made.
    #:
    #: An amount rather than a whole ``Cost``, because the only alternative any
    #: printing pairs with a mana cost this way is life; a card offering some
    #: other second cost should grow the field into a cost union rather than
    #: reuse this one for something it cannot say.
    life_alternative: int | None = None
    #: "**Starting with you**, each player may …" (Eureka). Which seat is asked
    #: first. CR 101.4 already orders a multi-seat offer from the active player,
    #: and for a sorcery those are the same seat — but they are not the same
    #: *rule*, and dropping the words would leave the printed order unstated
    #: wherever they come apart (a copy of the spell resolving under another
    #: seat's control). None means CR 101.4's default.
    starting_with: PlayerRef | None = None


@dataclass(frozen=True)
class RepeatProcess:
    """"**Repeat this process until no one** puts a card onto the battlefield."
    (Eureka.)

    The sentence before it is one *round* of an offer made to every seat; this
    one says the round happens again whenever anybody took it. So it wraps that
    statement rather than being a step beside it — the round is the process, and
    "this process" has no other referent.

    *restatement* is the offered act as the clause names it ("puts a card onto
    the battlefield"), parsed as a statement of its own. It is carried, not
    dropped: lowering checks it describes the same kind of act as the offer, so
    a card whose repeat clause names something *else* refuses instead of
    repeating the wrong thing.
    """
    round: "Statement"
    restatement: "Statement"


@dataclass(frozen=True)
class OneOf:
    """"sacrifice a creature **or** discard a creature card" (Crypt Lurker).

    Two ways to take one action, the player choosing which. Not a
    :class:`Sequence` (that does both) and not a :class:`ModalNode` (that is a
    spell's printed "Choose one —" with bulleted lines, chosen as the spell is
    cast under CR 601.2b); this is a choice made where the effect is performed.

    *labels* is each option as printed, sliced back out of the line, so the
    prompt shows the player the words on the card rather than a rendering of the
    instruction behind them.
    """
    options: tuple["Statement", ...]
    labels: tuple[str, ...] = ()


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
    iterator: (ObjectFilter | PlayerRef | DiedThisTurn | DiedThisWay
                | ExiledThisWay | ChosenThisWay)
    effect: "Statement"


@dataclass(frozen=True)
class WhereX:
    """"<sentence>, where X is the number of <filter>" — the clause that says
    what the X in the sentence means.

    A *wrapper* rather than a field on each effect, because the clause is
    printed once at the end of a whole sentence and binds every X in it: Sanctum
    of Stone Fangs' "each opponent loses X life and you gain X life, where X is
    the number of Shrines you control" is two effects and one definition. It
    lived inside the pump production for as long as it existed, which is why
    exactly one sentence shape in the pool could carry one.

    An undefined X is not the same thing and must not become one: without this
    the trailing clause is unconsumed text and the line fails loudly, which is
    the right outcome — a dropped definition would silently read the *cast's* X
    instead, and for a permanent's triggered ability there is no cast.
    """
    statement: "Statement"
    definition: Amount


@dataclass(frozen=True)
class CreateDelayedTrigger:
    """A delayed triggered ability the sentence **creates** (CR 603.7).

    ``When that creature dies this turn, …`` (Reincarnation), ``At the
    beginning of your next main phase, …`` (Mana Drain), ``Whenever that
    creature is dealt damage by an attacking creature this turn, …`` (Glyph of
    Life). The effect does not happen now; an ability that will do it waits for
    ``event``.

    Here beside `May` and `ForEach` rather than in a family, and for their
    reason: it wraps a whole `Statement`, so it cannot live below the roof that
    closes over one.

    Every field is payload, and each one is a printed word:

    * ``once`` is CR 603.7b — "when" is one-shot, "whenever … this turn"
      has a stated duration and is not;
    * ``duration`` is "this turn" against a named future step, which is how
      long an ability that never triggers survives;
    * ``binds_target`` is "**that** creature" — the delayed ability is about
      the object the creating spell targeted (CR 603.7c);
    * ``agent`` is the second noun phrase some events print ("dealt damage
      **by an attacking creature**"), narrowing what did the thing rather than
      what it was done to.

    ``event`` is a key of ``engine/delayed_triggers.DELAYED_EVENTS``, checked
    when the sentence is lowered: an event no site announces is an ability that
    would wait forever, which is worse than a refused line.
    """
    event: str
    effect: "Statement"
    once: bool = True
    duration: str = "end_of_turn"
    binds_target: bool = False
    #: The noun phrase "that <noun>" printed for the bound object. The id binds
    #: it exactly, so this re-states rather than narrows — carried and tested
    #: anyway, because a word consumed and never read could be deleted with no
    #: change to what the card does.
    subject: ObjectFilter | None = None
    agent: ObjectFilter | None = None
    #: Which object the ability **watches**, when the opener names one that is
    #: not a chosen target: ``"source"`` for the card naming itself ("when
    #: Stangg leaves the battlefield") and ``"created_token"`` for the token an
    #: earlier sentence of the same effect made ("when that token leaves the
    #: battlefield").
    #:
    #: A separate field from ``binds_target`` because it is a separate
    #: question. ``binds_target`` says the object was *chosen*, and is resolved
    #: from the spell's targets; these two are objects the effect already has
    #: in hand and never targeted, so a shared field would send the resolver to
    #: a target that was never picked.
    watches: str | None = None


# ``UnlessPlayerPays`` is a *statement*, not an effect, for the reason ``May``
# is one: it wraps a whole sentence and its body is an ordinary statement.
Statement = Union[Sequence, Conjunction, Conditional, May, UnlessPlayerPays, ForEach, RepeatProcess, WhereX, CreateDelayedTrigger, Effect]


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
    #: Noun phrases the condition carries **beyond** its subject, each under the
    #: stem ``engine/oracle.py``'s pattern table gives its ``<stem>_subject``
    #: group — "…that doesn't share a color with **a creature you control**"
    #: (Invoke Prejudice) is ``("unshared_color", <that phrase>)``.
    #:
    #: A trigger condition is read twice, once by each front end (the table
    #: supplies the *condition*, the grammar the *effect*), and a phrase only
    #: one of them sees is a card whose two halves watch different sets. The
    #: subject alone could not express these: the set on the far side of a
    #: comparison is a different object from the one the trigger fires on.
    #: Paired by stem in ``test_a_narrowed_trigger_reads_the_same_subject_on_both_sides``.
    narrowings: tuple[tuple[str, ObjectFilter], ...] = ()


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


# `ModalNode` is deliberately absent: a modal head is printed bare, behind an
# activation cost and behind a trigger condition, so it is a *statement* those
# three line nodes carry (see `ast/stack.py`) rather than a fourth kind of line
# that would need its own copy of the cost and event fields.
AbilityNode = Union[
    SpellEffectLine, TriggeredAbilityNode, ActivatedAbilityNode,
    StaticAbilityNode, KeywordLine, RegistryLine, DerivedLine,
]
