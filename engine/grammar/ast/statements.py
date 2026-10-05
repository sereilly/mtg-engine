"""Composition, and the unions that close over the families.

The roof of the package, and the only module that sees every family at once.
It holds:

* `Effect`, the union of every leaf node — which is exactly why it cannot live
  beside any one of them;
* the composable statement nodes (`Sequence`, `Conjunction`, `Conditional`,
  `May`, `ForEach`, the six `Repeat…` wrappers, `WhereX`,
  `CreateDelayedTrigger`, …) and `Statement`. These are what kills the
  conjunction-kind explosion: "deal damage and gain life" is two effects under
  a `Conjunction`, never a fused node.

Nothing in a family imports this module, and this module imports every family:
that one-way edge is the layer. It is the type of `grammar/statements.py`, which
sits above `grammar/effects/` on the parsing side for the same reason.

**The ability-line nodes are not here.** They were, under a second banner,
until Invasion's Phase 0 found this module 25 lines under the size guard; they
are `ast/lines.py` now, one storey up, which imports `Statement` from here and
is never imported back. The cut is the one the parse side already has
(`statements` under `parser`): a line *holds* a statement, and no statement
holds a line. `AbilityNode` went with them — it is a union over the line nodes,
not over the families, so it never needed this module's view.

What is left is the half that grows, and it has to stay: a new leaf costs an
import line and a union entry here whichever family it lands in. The next seam,
measured and not taken, is the six `Repeat…` nodes — one contiguous run whose
mirror both other packages already name (`grammar/repeats.py`,
`lowering/repeats.py`). They name `Statement` only in annotations, so they could
sit *below* this module the way `records` sits below `conditions`; that is the
cut to make when this file reaches the guard again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .conditions import Condition
from .conditions import (ChosenThisWay, DiedThisTurn, DiedThisWay,
                         CountersPlacedThisWay, EachAdditionalCostPaid,
                         EachLifeLost, ExiledThisWay)
from .costs import Cost
from ._core import (
    ObjectFilter,
    PlayerRef,
    RawEffect,
    TargetSpec,
)
from .damage import (
    DamageCantBePreventedOrRedirected,
    DamageReducedByPaidMana,
    DamageRidersUntilEndOfTurn,
    DamageUnlessPay,
    Fight,
    CoinFlipDamageLoop,
    DamageThoseDamagedThisGame,
    DealDamage,
    PreventDamage,
    DamageBecomesCounterRemoval,
    ChooseDamageSource,
    ChosenSourceNextDamage,
    DoubleCombatDamage,
    RedirectDamage,
    UpkeepCounterToll,
    UpkeepDamageUnlessCost,
)
from .characteristics import (
    BecomeColor,
    BecomeCopy,
    ChangeLandType,
    LandTypeSwap,
    ChangeSupertype,
    BecomeAura,
    GainType,
    BecomeCreature,
    ChangeBasePT,
    ChangeText,
    GainAbilityText,
    GainKeyword,
    LoseAbilityText,
    LoseKeyword,
    Pump,
    DoublePower,
    SwitchPT,
    MoveCounter,
    PlayerGetsCounters,
    PutCounter,
    RemoveCounter,
    SetBasePT,
)
from .separations import SeparateIntoPiles
from .tapping import (
    Tap,
    Untap,
    TapOrUntap,
    DoesntUntapNextStep,
    SimultaneousUntapAndTap,
    UntapChosenByPaying,
    DoesntUntapWhileSourceTapped,
    DoesntUntapWhileCounter,
    ReturnSelfInsteadOfUntapping,
)
from .board import (
    DelayedSelfAction,
    RebalanceLands,
    SacrificeExpansionPermanents,
    ShuffleGraveyardIntoLibrary,
    ShuffleHandIntoLibrary,
    ShuffleSourceIntoLibrary,
    ShuffleTargetIntoLibrary,
    ShuffleLibrary,
    Destroy,
    Exile,
    ExileUntilLeavesOrUntaps,
    PutSourceIntoZone,
    Attach,
    PayOrSacrificeGreatestManaValue,
    CantPhaseOut,
    PhaseOut,
    SimultaneousPhasing,
    PutOnLibraryBottom,
    PutGraveyardTopOnLibraryBottom,
    PutOnLibraryTop,
    PutGraveyardPositionOntoBattlefield,
    PutOntoBattlefield,
    ReanimateEnchantedCard,
    Regenerate,
    ReturnToZone,
    ChoosePermanent,
    Sacrifice,
    SacrificeAndReturnTargets,
    DestroyUnlessPay,
    DestroyEachUnlessPaid,
    SacrificeUnlessPay,
    KeepChosenSacrificeRest,
)
from .control_changes import (
    GainControl,
    BidLifeForControl,
    ExchangeControl,
    ExchangeGreatestManaValue,
    MutualControlOfSets,
)
from .mana import (
    ActivateEachLandsManaAbility,
    AddMana,
    AddManaForTappedLand,
    LoseUnspentMana,
    NoteManaSpent,
    ProducesManaInstead,
    SpendManaAsThough,
)
from .library import (
    PutExiledPileOnLibrary,
    RevealUntil,
    LookAtHand,
    LookAtLibraryTop,
    LookTopCycleForLife,
    LookTopExileRandom,
    RevealTopOpponentChooses,
    SearchRevealOpponentChooses,
    StripCardsWithChosenName,
    GraveyardTopOpponentChooses,
    PutLibraryTopIntoHand,
    RevealTopSortingByChosenName,
    RevealTopSortingByFilter,
    LookTopPickToHand,
    PlayWithTopRevealed,
    RevealTop,
    RevealTopToHandOrBottom,
    SearchLibrary,
    SearchPlayerLibrary,
    SeparateLibraryTopIntoPiles,
)
from .cards import (
    CastPermission,
    Discard,
    Draw,
    EachPlayerClaimsExiledCard,
    RandomGraveyardCardFate,
    PlayWithHandRevealed,
    RevealCardsFromHand,
    RevealHand,
    RevealHandAndChoose,
    RevealRandomFromHand,
    DiscardRevealedMatchingUnlessPayLife,
    DiscardRevealedUnlessPayLife,
    ChooseCardsInHand,
    RevealChosenHandCards,
    PutIteratedCardOnLibrary,
    Mill,
    MillUntil,
    PutMilledCardOntoBattlefield,
    PutHandCardsOnLibrary,
    NameAndRandomReveal,
    NameAndStrip,
    NameThenRevealTop,
    Scry,
    AnteOfferOwnershipExchange,
    OwnershipExchangeUnlessPaid,
    RandomRevealOwnershipExchange,
    TransmuteBySacrifice,
    RepeatedGraveyardPick,
    NameThenConsult,
    Shuffle,
)
from .exile import (
    ExileCostSacrifices,
    ExileGraveyard,
    ExileRandomFromHand,
    ExileCardsFromHand,
    ExileTopOfLibrary,
    ExileGraveyardPosition,
    ExileEntireLibrary,
    PutExiledWithSource,
    ExileGraveyardUntilLeaves,
    CastFromExiledWith,
    SearchAndExile,
    ExileBoundCard,
    ExileGraveyardArrivalsThisTurn,
    PutExiledCardIntoZone,
    PutExiledThisWay,
    PutExiledPileTopIntoHand,
)
from .stack import (
    BidLifeContest,
    ChangeTarget,
    ChooseTarget,
    CopySpell,
    CopyThatSpell,
    CounterAbility,
    CounterSpell,
    DestroyCounteredAbilitySource,
    ModalNode,
    PutExiledCardOnStackAsCopy,
    WaiveShroud,
)
from .combat import (
    AssignsCombatDamageAsUnblocked,
    AssignsNoCombatDamage,
    AttacksThisTurnIfAble,
    DestroyChosenThatDidntAttack,
    AttackingDoesntTap,
    BlockCountGrant,
    BlocksThisTurnIfAble,
    CantBe,
    AttackAsThough,
    CombatRestriction,
    ChooseBlocksForDefenders,
    ForceChosenCreatureToAttack,
    ReassignBlockersBetweenAttackers,
    RemoveFromCombat,
    BecomeBlocked,
)
from .game import (
    Ante,
    CantActivateNonManaAbilities,
    CantCastSpellTypes,
    CantPlayLands,
    CoinFlipStakesLoop,
    CountObjects,
    CreateEmblem,
    CreateCopyToken,
    CreateToken,
    PayAnyAmountOfMana,
    DrawGame,
    EndTheTurn,
    ExtraLandPlays,
    ExtraTurn,
    ChooseCardType,
    ChooseCardName,
    ChooseColor,
    ChooseCreatureType,
    ChooseNumber,
    ChooseOpponent,
    ChoosePlayerWhoCast,
    FlipCoin,
    GainLife,
    LoseGame,
    LoseLife,
    PayLife,
    SetLifeTotal,
    ExchangeLifeTotals,
    WinGame,
    SkipPhase,
    SkipStep,
    SkipTurn,
    ExtraPhases,
    BoundPermanentActivationBan,
    TargetingBan,
)


Effect = Union[
    CoinFlipDamageLoop,
    CoinFlipStakesLoop,
    DamageThoseDamagedThisGame,
    DamageRidersUntilEndOfTurn,
    DealDamage, Pump, SetBasePT, ChangeBasePT, GainAbilityText, GainKeyword, GainType, BecomeAura, ChangeSupertype, ChangeLandType, LandTypeSwap, LoseAbilityText, LoseKeyword, MoveCounter, PlayerGetsCounters, PutCounter, RemoveCounter,
    DoublePower, SwitchPT,
    GainLife, LoseLife, PayLife, SetLifeTotal, ExchangeLifeTotals, Ante, Draw, Discard, LookTopCycleForLife, SeparateLibraryTopIntoPiles, SeparateIntoPiles, Mill, MillUntil, PutMilledCardOntoBattlefield, PutHandCardsOnLibrary, Scry, Destroy, Sacrifice, SacrificeAndReturnTargets,
    SacrificeExpansionPermanents, ShuffleGraveyardIntoLibrary, ShuffleHandIntoLibrary,
    ShuffleSourceIntoLibrary,
    ShuffleTargetIntoLibrary,
    ShuffleLibrary, Exile,
    ExileUntilLeavesOrUntaps, PutSourceIntoZone, ReturnSelfInsteadOfUntapping,
    Tap, Untap,
    TapOrUntap, DoesntUntapNextStep, DoesntUntapWhileSourceTapped,
    SimultaneousUntapAndTap,
    DoesntUntapWhileCounter, UntapChosenByPaying,
    DelayedSelfAction, RebalanceLands, KeepChosenSacrificeRest, Attach, ExchangeControl,
    ExchangeGreatestManaValue,
    MutualControlOfSets,
    PayOrSacrificeGreatestManaValue,
    PayAnyAmountOfMana,
    Regenerate, ReanimateEnchantedCard, ChangeTarget, ChooseTarget, WaiveShroud, CopySpell, CopyThatSpell, CounterAbility, CounterSpell, BidLifeContest, DestroyCounteredAbilitySource, ModalNode, PutExiledCardOnStackAsCopy, ReturnToZone, ChoosePermanent, CreateToken, CreateCopyToken, AddMana,
    PutOnLibraryTop, PutOnLibraryBottom, PutGraveyardTopOnLibraryBottom,
    PutOntoBattlefield, PutGraveyardPositionOntoBattlefield,
    RevealTopToHandOrBottom, CreateEmblem, SkipPhase, SkipStep,
    SkipTurn,
    ExtraPhases,
    BoundPermanentActivationBan,
    TargetingBan,
    PlayWithTopRevealed,
    RevealTop, RevealUntil, NameAndStrip, NameAndRandomReveal, NameThenRevealTop,
    ChooseCardsInHand, RevealChosenHandCards, PutIteratedCardOnLibrary,
    ExileGraveyardUntilLeaves, CastFromExiledWith, ForceChosenCreatureToAttack,
    CantPhaseOut,
    PhaseOut,
    SimultaneousPhasing,
    ActivateEachLandsManaAbility, LoseUnspentMana,
    AddManaForTappedLand, NoteManaSpent, ProducesManaInstead, SpendManaAsThough, PreventDamage,
    RedirectDamage, DamageBecomesCounterRemoval,
    RedirectDamage, DoubleCombatDamage, ChooseDamageSource, ChosenSourceNextDamage,
    DamageCantBePreventedOrRedirected, DamageReducedByPaidMana,
    UpkeepCounterToll,
    UpkeepDamageUnlessCost,
    ExileBoundCard, ExileGraveyardArrivalsThisTurn,
    PutExiledCardIntoZone, PutExiledThisWay, PutExiledPileTopIntoHand,
    PutExiledPileOnLibrary,
    RepeatedGraveyardPick, NameThenConsult,
    SearchLibrary, SearchPlayerLibrary, SearchAndExile, TransmuteBySacrifice,
    AnteOfferOwnershipExchange,
    OwnershipExchangeUnlessPaid,
    RandomRevealOwnershipExchange,
    ExileTopOfLibrary, ExileGraveyardPosition, ExileEntireLibrary, PutExiledWithSource, ExileGraveyard, ExileCostSacrifices,
    CastPermission, LookTopExileRandom, LookTopPickToHand,
    RevealTopOpponentChooses,
    SearchRevealOpponentChooses,
    StripCardsWithChosenName,
    GraveyardTopOpponentChooses,
    PutLibraryTopIntoHand,
    RevealTopSortingByChosenName,
    RevealTopSortingByFilter,
    PlayWithHandRevealed,
    RevealCardsFromHand,
    RevealHand,
    RevealHandAndChoose,
    RevealRandomFromHand,
    ExileRandomFromHand,
    ExileCardsFromHand,
    EachPlayerClaimsExiledCard, RandomGraveyardCardFate,
    DiscardRevealedMatchingUnlessPayLife,
    DiscardRevealedUnlessPayLife,
    Shuffle, ExtraTurn, ExtraLandPlays, CantPlayLands,
    CantCastSpellTypes, CantActivateNonManaAbilities, EndTheTurn, ChooseNumber, ChooseColor, ChooseCreatureType, ChooseCardType, ChooseCardName, ChooseOpponent, ChoosePlayerWhoCast, CountObjects, FlipCoin, WinGame, LoseGame, DrawGame, BecomeColor, BecomeCopy, BecomeCreature,
    SacrificeUnlessPay, DestroyUnlessPay, DestroyEachUnlessPaid, DamageUnlessPay, Fight, LookAtHand, LookAtLibraryTop,
    CantBe, AttackAsThough, CombatRestriction, BlockCountGrant,
    AttackingDoesntTap,
    AssignsCombatDamageAsUnblocked,
    AssignsNoCombatDamage,
    AttacksThisTurnIfAble,
    DestroyChosenThatDidntAttack,
    BlocksThisTurnIfAble,
    RemoveFromCombat, BecomeBlocked, ChooseBlocksForDefenders,
    ReassignBlockersBetweenAttackers,
    ChangeText, GainControl, BidLifeForControl, RawEffect,
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
    # "…deals 2 damage to that player **unless** one of their opponents was
    # dealt damage this turn." (Antagonism.) The printed word that inverts which
    # branch the effect is on, and a flag rather than a negation wrapped round
    # the condition because negation is not something every condition node
    # carries — the lowering swaps the branches instead, which is one place and
    # works for the whole vocabulary.
    #
    # ``otherwise`` is never set beside it: an "unless" puts the body on the
    # false branch, and that branch is exactly what ``otherwise`` means.
    negated: bool = False


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
    otherwise: "Statement | None"
    #: What paying *buys* — "Then **if any player pays {2}**, discard three
    #: cards" (Rhystic Scrying) — the same chain with the polarity reversed.
    paid: "Statement | None" = None


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
    #: "…unless they pay {B} **or {3}**." (Lim-Dûl's Hex.) CR 118.8's
    #: alternative again, in the spelling where the second currency is also
    #: mana — so whole costs rather than ``life_alternative``'s single number.
    #: A tuple because the rule puts no limit on how many a card may print, and
    #: the payer covers the offer with whichever of them they can.
    cost_alternatives: tuple["ManaCost", ...] = ()
    #: What each way of covering the offer *buys*, index-aligned with
    #: ``(cost, *cost_alternatives)``. Empty — every card but one — means the
    #: alternatives are readings of one offer with one consequence, which is
    #: what CR 118.8 is normally used for.
    #:
    #: "…may pay {1} or {2}. **If that player doesn't**, destroy that creature
    #: at end of combat. **If that player pays only {1}**, prevent all combat
    #: damage …" (Winter's Chill.) Three outcomes, so the payer is choosing
    #: between the options and not merely finding one they can afford — and the
    #: engine has to report *which* was taken. A second ``May`` per option would
    #: be a second prompt and a second decline branch, and declining the first
    #: would destroy the creature before the second was ever offered.
    #:
    #: An entry may be None, which is the option that buys nothing but the
    #: absence of ``otherwise``.
    option_effects: tuple["Statement | None", ...] = ()
    #: "…unless its controller **pays life equal to its toughness**." (Essence
    #: Vortex.) A life cost with no mana alternative at all, which is a
    #: different field from ``life_alternative`` above for the reason
    #: ``_player_can_pay_optional`` states about the two payload keys: folding
    #: them would make an unaffordable mana cost read as a life one. An
    #: :class:`Amount` rather than an int, because the printed number can be a
    #: characteristic of the object the sentence already named and only the
    #: resolution knows it (CR 613 makes toughness computed).
    life_cost: "Amount | None" = None
    #: "…unless you pay {1} **for each card in your hand**." (Extravagant
    #: Spirit, Megatherium.) The set whose size multiplies the printed cost.
    #:
    #: A multiplier rather than a number, for ``DestroyUnlessPay.per_counter``'s
    #: reason one node over: the count is taken when the ability *resolves*
    #: (CR 608.2), and a hand that changed between the trigger and its
    #: resolution is the hand this charges against. None is a flat cost, which
    #: is every other offer in the pool.
    cost_per_each: "ObjectFilter | None" = None
    #: "**Starting with you**, each player may …" (Eureka). Which seat is asked
    #: first. CR 101.4 already orders a multi-seat offer from the active player,
    #: and for a sorcery those are the same seat — but they are not the same
    #: *rule*, and dropping the words would leave the printed order unstated
    #: wherever they come apart (a copy of the spell resolving under another
    #: seat's control). None means CR 101.4's default.
    starting_with: PlayerRef | None = None
    #: "**Look at the top two cards of your library.** You may sacrifice this
    #: enchantment and pay {2}{G}{G}. …" (Preferred Selection.) How many cards
    #: of their own library the offered seat has already seen when the offer is
    #: made (CR 701.20e).
    #:
    #: A field on the offer rather than a step in front of it, because the look
    #: is not something that *happens* — it is information the decision is made
    #: with, and this engine has no other channel for showing one seat a hidden
    #: zone without also asking them something. Dropped, the card would ask its
    #: controller to pay four mana and sacrifice an enchantment **blind**, which
    #: is the whole of what the first sentence is printed to prevent.
    #:
    #: Only ever the offered seat's own library: the two are one player by
    #: construction here (the sentence says "your library" and offers to "you"),
    #: and the lowering refuses any other actor rather than showing one seat
    #: another's cards.
    looked_at_top: "Amount | None" = None


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
class RepeatProcessWhile:
    """"Target player mills two cards. **If two cards that share a color were
    milled this way, repeat this process.**" (Grindstone.)

    The **fourth** printed "repeat this process" and a fourth mechanism, which
    is why it is a node of its own and not a flag on the three around it.
    Eureka's loop ends on a round nobody took, Forbidden Ritual's on its
    controller's answer, Equipoise's is not a loop at all — and this one ends
    on a *condition asked of what the round just did*, which none of the others
    has anywhere to put.

    ``round`` is the sentence before the clause, and ``condition`` is the one
    printed in front of "repeat". The condition reads a record the round writes
    ("milled **this way**"), so the loop clears that record before each round —
    otherwise "this way" would accumulate and the second round would be asked
    about the first one's cards as well.
    """
    round: "Statement"
    condition: "Condition"


@dataclass(frozen=True)
class RepeatUntilPileChosen:
    """"**Repeat this process until all cards exiled this way have been
    chosen.**" (Thieves' Auction.)

    The **fifth** printed "repeat this process" and a fifth mechanism, for the
    reason :class:`RepeatProcessWhile` is a fourth: what ends this loop is a
    *pile emptying*, and none of the four around it has anywhere to put that.
    Eureka's ends on a round nobody took, Forbidden Ritual's on its controller's
    answer, Grindstone's on a condition asked of the round, and Equipoise's is
    not a loop at all.

    The bound is also the one that ends a round **part-way**: four cards among
    three players is two passes, and the second stops after the first seat. So
    the clause and the round it wraps are one loop rather than a loop around a
    loop, which is why the lowering collapses this into the round's own
    instruction exactly as Eureka's does.

    ``round`` is the sentence before the clause. The lowering refuses anything
    but a pick out of that same pile: a repeat clause naming a record the
    sentence in front of it does not write would be a loop with no bound at all.
    """
    round: "Statement"


@dataclass(frozen=True)
class RepeatOptionalProcess:
    """"**You may repeat this process any number of times.**" (Forbidden
    Ritual.)

    :class:`RepeatProcess`'s neighbour and deliberately not its twin. That one
    wraps a *round of offers* and ends on a fact about the round — a round
    nobody took — which is something the thing running the round can see. This
    one wraps whatever the line said before it, however many sentences that was,
    and ends only when its controller declines: there is no bound, no record to
    read, and nothing to check the answer against.

    So *round* is the whole preceding statement rather than one offer, and there
    is no ``restatement`` to check it against — the words name no act, only a
    number of times, so there is nothing a mismatched restatement could say.
    """
    round: "Statement"


@dataclass(frozen=True)
class RepeatForEachType:
    """"**Repeat this process for artifacts and creatures.**" (Equipoise.)

    The third printed "repeat" and the one that is not a loop. Eureka's ends on
    a fact about a round and Forbidden Ritual's on an answer; this one ends
    because the card names how many more times there are and which card type
    each of them is about. It is a *list of parameters*, known when the line is
    parsed, so what it says is "the sentence again with one word changed".

    *round* is the process as printed — with its own type still in it — and
    *types* are the ones it happens for after that. The round's own type is not
    repeated here: it is already in the round, and naming it twice would be one
    fact in two places, free to disagree.
    """
    round: "Statement"
    types: tuple[str, ...]


@dataclass(frozen=True)
class RepeatProcessRequest:
    """"…unless you pay {3} **and repeat this process**." (Crooked Scales.)

    The **sixth** printed "repeat this process" and the first one printed
    *inside* a sentence rather than as a clause about the sentences before it.
    The five in ``engine/grammar/repeats.py`` are all attachers — each is read
    where a sentence has just ended and folds into what it names — and this one
    is the consequence a toll buys: "pay {3}" and "repeat this process" are one
    offer, joined by the printed "and", so the words are read by the price
    reader and never reach the sentence loop at all.

    So the node is a *marker* rather than a wrapper. What it names is the whole
    printed effect, which the place holding this statement does not have — the
    toll is two branches down inside the last of three sentences. The wrap
    happens where the line's instructions are all in hand
    (``grammar/lower._lower_line_statement``, the same function CR 601.2c's
    roles walk runs in), and this node is how that function is told the words
    were printed.
    """


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
                | ExiledThisWay | ChosenThisWay | EachLifeLost
                | EachAdditionalCostPaid | CountersPlacedThisWay)
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
    #: "…, where X is the number of black permanents target opponent
    #: controls **as you cast this spell**." (Reap.) CR 601.2b: the
    #: quantity is fixed as the spell is announced rather than counted when
    #: it resolves, which is what CR 601.2c then means by "once the number
    #: of targets is determined, that number doesn't change, even if the
    #: information used to determine it does".
    #:
    #: A flag on the clause rather than a different node, because it is the
    #: same definition read at a different moment — every alternative above
    #: means what it means either way, and only *when* it is asked moves.
    #: Defaulted False so every WhereX written before the words existed is
    #: untouched, and so the two other construction sites
    #: (``control_flow``'s folded sequences) keep the resolution-time
    #: reading the CR 608.2 default is.
    as_cast: bool = False


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
      long an ability that never triggers survives. **None means the opener
      printed none**, which happens when the card prints one duration in front
      of a whole sentence and shares it with the effect beside the delay (Chaos
      Moon's "until end of turn, red creatures get +1/+1 **and** whenever a
      player taps a Mountain for mana, …"). The leading-duration reader fills it
      in; a node that reaches the lowering still None refuses, because a
      repeating ability with no window is one nothing ever lifts;
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
    duration: str | None = "end_of_turn"
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
    #: The target the **opener itself** names — "this turn, when **target
    #: creature you control** attacks and isn't blocked, …" (Delif's Cone,
    #: Delif's Cube). CR 601.2c/602.2b pick it as the spell or ability is
    #: announced, so it is chosen now and the delayed ability is about it
    #: (CR 603.7c) however many steps later it fires.
    #:
    #: Distinct from ``subject``, which re-states a target an *earlier
    #: sentence* chose ("Choose target creature. When **that creature** dies
    #: this turn, …"): there the choosing is its own statement and carries its
    #: own ``targets`` description, and here the opener is the only place the
    #: target is named — so this is what the picker has to learn it from.
    target: TargetSpec | None = None
    #: "Whenever that creature deals combat damage this turn, **if this spell
    #: was kicked,** you gain life equal to that damage." (Vigorous Charge.) A
    #: condition printed where an intervening "if" goes (CR 603.4) and asked
    #: when the ability is **created** instead — legal only for a condition
    #: whose answer cannot change between the two, which is why the parser
    #: admits one kind (:class:`WasKicked`: a fact about the creating spell's
    #: own casting) and refuses the rest. Created-or-not is then the whole of
    #: it: no entry waits, so nothing has to carry a spell's history to a fire
    #: site that runs after the spell has left the stack.
    #:
    #: A field rather than a ``Conditional`` around the node, because the
    #: callers that ask a delay what it binds (``choices``, the trailing-delay
    #: wrapper) read this node's own fields and a wrapper would hide them.
    created_if: "Condition | None" = None


# ``UnlessPlayerPays`` is a *statement*, not an effect, for the reason ``May``
# is one: it wraps a whole sentence and its body is an ordinary statement.
@dataclass(frozen=True)
class NextDrawReplacement:
    """"The next time you would draw a card this turn, instead <effect>."
    (Mangara's Tome; Aladdin's Lamp and Ring of Ma'rûf print the same opener.)

    CR 614.1's one-shot replacement, armed by the ability that resolves it and
    spent by the next draw that seat makes this turn. Here beside :class:`May`
    and :class:`CreateDelayedTrigger` rather than in a family, and for their
    reason: it wraps a whole :data:`Statement`, so it cannot live below the roof
    that closes over one.

    Three cards in the pool print the opener with three different effects
    behind it, which is why the effect is a nested statement rather than part
    of the node's name. Two of the three still reach ``card_hooks`` — their
    inner sentences are not ones the grammar reads, so this production refuses
    the whole line and leaves them theirs, which is the ordering
    ``tests/engine/test_card_lines.py`` enforces.
    """
    effect: "Statement"


Statement = Union[Sequence, Conjunction, Conditional, May, UnlessPlayerPays, ForEach, RepeatProcess, RepeatProcessWhile, RepeatUntilPileChosen, RepeatOptionalProcess, RepeatForEachType, RepeatProcessRequest, WhereX, CreateDelayedTrigger, NextDrawReplacement, Effect]
