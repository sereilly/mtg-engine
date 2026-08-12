"""Typed AST for Magic oracle text.

Every node is a frozen dataclass holding only hashable values (tuples, never
lists), so an AST compares by value — the property the lowering goldens and the
deletion probe rely on.

This package imports nothing from the rest of the engine, mirroring
``engine/oracle_types.py``: the lowering, tests and scripts can import it
without any risk of a cycle.

**The node inventory is append-only.** New fields must carry defaults and new
node types must be additive; repurposing an existing field breaks every golden
test and every ratchet entry at once. Schema churn is what kills incremental
parser migrations, so the full inventory is defined here up front even where
only part of it is reachable from the productions implemented so far.

**Where a node goes.** The same seven families as ``grammar/effects/`` and
``grammar/lowering/``, so one template has one home per side — prowess parses in
``effects/characteristics.py``, lowers in ``lowering/characteristics.py``, and
its node is in ``ast/characteristics.py``.

    _core            amounts, nouns, durations, zones, costs, conditions
    damage           dealing it, and preventing it
    characteristics  P/T, keywords, colour, printed text, counters
    board            destruction, bouncing, tapping, control, sacrifice
    cards            draw, discard, mill, search, mana
    stack            countering, choosing a modal spell's mode
    combat           can't-attack / can't-be-blocked
    game             tokens, life, turns, outcomes
    statements       composition, ability lines, and the closing unions

The families share no code with each other; a node two of them need is in
``_core``. ``statements`` is the only module that imports the families, because
the ``Effect``, ``Statement`` and ``AbilityNode`` unions have to name all of
them.

Re-exported flat, so every caller writes ``ast.DealDamage`` and never names a
family — which is what makes moving a node between families a non-event.
"""

from ._core import (
    Fixed,
    Var,
    CountOf,
    ThatMuch,
    Half,
    AllOf,
    BoardCount,
    Amount,
    Comparison,
    ObjectFilter,
    PlayerRef,
    TargetSpec,
    Recipient,
    Duration,
    Zone,
    ManaCost,
    TapSelf,
    SacrificeCost,
    DiscardCost,
    PayLife,
    ExileSelf,
    RemoveCounterCost,
    Cost,
    Controls,
    IsState,
    DiedThisTurn,
    LifeGainedThisTurn,
    PaidCost,
    RawCondition,
    Condition,
    RawEffect,
)
from .damage import (
    DamageRiders,
    DealDamage,
    DamageUnlessPay,
    PreventDamage,
)
from .characteristics import (
    Pump,
    SetBasePT,
    GainKeyword,
    LoseKeyword,
    PutCounter,
    RemoveCounter,
    ChangeText,
    BecomeColor,
)
from .board import (
    Destroy,
    Sacrifice,
    Exile,
    GainControl,
    Tap,
    Untap,
    TapOrUntap,
    Regenerate,
    ReturnToZone,
    PhaseOut,
    PutOnLibraryTop,
    PutOntoBattlefield,
    SacrificeUnlessPay,
)
from .cards import (
    Draw,
    Discard,
    Mill,
    Scry,
    AddMana,
    AddManaForTappedLand,
    CastPermission,
    ExileTopOfLibrary,
    LookTopPickToHand,
    SearchAndExile,
    SearchLibrary,
    Shuffle,
    LookAtHand,
    RevealTopToHandOrBottom,
)
from .stack import (
    CounterSpell,
    ModalNode,
)
from .combat import (
    CantBe,
    CombatRestriction,
)
from .game import (
    CreateEmblem,
    GainLife,
    LoseLife,
    CreateToken,
    ExtraTurn,
    WinGame,
    LoseGame,
    DrawGame,
)
from .statements import (
    Effect,
    Sequence,
    Conjunction,
    Conditional,
    May,
    ForEach,
    Statement,
    TriggerEvent,
    KeywordInstance,
    ActivationRestriction,
    SpellEffectLine,
    TriggeredAbilityNode,
    ActivatedAbilityNode,
    StaticAbilityNode,
    KeywordLine,
    RegistryLine,
    DerivedLine,
    AbilityNode,
)

__all__ = [
    # _core
    "Fixed",
    "Var",
    "CountOf",
    "ThatMuch",
    "Half",
    "AllOf",
    "BoardCount",
    "Amount",
    "Comparison",
    "ObjectFilter",
    "PlayerRef",
    "TargetSpec",
    "Recipient",
    "Duration",
    "Zone",
    "ManaCost",
    "TapSelf",
    "SacrificeCost",
    "DiscardCost",
    "PayLife",
    "ExileSelf",
    "RemoveCounterCost",
    "Cost",
    "Controls",
    "IsState",
    "DiedThisTurn",
    "LifeGainedThisTurn",
    "PaidCost",
    "RawCondition",
    "Condition",
    "RawEffect",
    # damage
    "DamageRiders",
    "DealDamage",
    "DamageUnlessPay",
    "PreventDamage",
    # characteristics
    "Pump",
    "SetBasePT",
    "GainKeyword",
    "LoseKeyword",
    "PutCounter",
    "RemoveCounter",
    "ChangeText",
    "BecomeColor",
    # board
    "Destroy",
    "Sacrifice",
    "Exile",
    "GainControl",
    "Tap",
    "Untap",
    "TapOrUntap",
    "Regenerate",
    "ReturnToZone",
    "PhaseOut",
    "PutOnLibraryTop",
    "PutOntoBattlefield",
    "SacrificeUnlessPay",
    # cards
    "Draw",
    "Discard",
    "Mill",
    "Scry",
    "AddMana",
    "AddManaForTappedLand",
    "CastPermission",
    "ExileTopOfLibrary",
    "LookTopPickToHand",
    "SearchAndExile",
    "SearchLibrary",
    "Shuffle",
    "LookAtHand",
    "RevealTopToHandOrBottom",
    # stack
    "CounterSpell",
    "ModalNode",
    # combat
    "CantBe",
    "CombatRestriction",
    # game
    "CreateEmblem",
    "GainLife",
    "LoseLife",
    "CreateToken",
    "ExtraTurn",
    "WinGame",
    "LoseGame",
    "DrawGame",
    # statements
    "Effect",
    "Sequence",
    "Conjunction",
    "Conditional",
    "May",
    "ForEach",
    "Statement",
    "TriggerEvent",
    "KeywordInstance",
    "ActivationRestriction",
    "SpellEffectLine",
    "TriggeredAbilityNode",
    "ActivatedAbilityNode",
    "StaticAbilityNode",
    "KeywordLine",
    "RegistryLine",
    "DerivedLine",
    "AbilityNode",
]
