"""Name-keyed registries for card-specific behavior.

Most cards should be handled generically by parse rules (engine/parsing) and
effect handlers (engine/handlers). When a card needs truly bespoke logic that
no generic instruction covers, register it here instead of hardcoding the card
name inside engine internals. This keeps per-card behavior in one place and
lets the card pool grow without touching the core rules code.

Hook registries:
- ON_SPELL_CAST       — fired when a player casts a spell, once per permanent
                        that player controls whose name is registered.
- ON_SPELL_CAST_ANY   — fired when *any* player casts a spell (as the spell is put
                        on the stack, CR 603.3), once per permanent on any
                        battlefield whose name is registered. Used by "whenever a
                        player casts a [color] spell" triggers (the Rod/Cup/Sphere
                        cycle) so their trigger goes on the stack above the spell
                        and resolves while the spell is still on the stack.
- ON_SELF_RESOLVED    — fired when the named instant/sorcery itself resolves
                        (keyed by the resolving card's own name), for bespoke
                        effects the single compiled instruction can't express.
- ON_SPELL_COUNTERED  — fired after the named card counters a spell (keyed by
                        the counterspell's own name).
- ON_LEAVE_BATTLEFIELD — fired when the named permanent is put into a graveyard
                        from the battlefield (keyed by the permanent's name).
- UNTAP_RESTRICTIONS  — declarative untap-step constraints (Stasis, Winter Orb,
                        Smoke, Meekstone), consumed by engine/phases/untap_step.
- DRAW_STEP_MODIFIERS — draw-step skips and bonus draws (Island Sanctuary,
                        Howling Mine), consumed by engine/phases/draw_step.
- MANA_PRODUCTION_MODIFIERS — fired once per registered permanent whenever a
                        land is tapped for mana (Mana Flare, Gauntlet of Might,
                        Lifetap), consumed by engine/mixins/turn_management.
- SPELL_COST_MODIFIERS / ABILITY_COST_MODIFIERS — extra generic mana taxed onto
                        a cast / activation, once per registered permanent on
                        any battlefield (Gloom).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game
    from .game_types import StackItem
    from .models import CardDefinition, Permanent, PlayerState

SpellCastHook = Callable[["Game", "PlayerState", "Permanent", "CardDefinition"], None]
SpellCastAnyHook = Callable[["Game", "PlayerState", "Permanent", "CardDefinition"], None]
SelfResolvedHook = Callable[["Game", "PlayerState", "CardDefinition", int, "int | None"], None]
SpellCounteredHook = Callable[["Game", "CardDefinition", "StackItem"], None]
LeaveBattlefieldHook = Callable[["Game", "PlayerState", "Permanent"], None]


def _verduran_enchantress(game: Game, controller: PlayerState, permanent: Permanent, cast_card: CardDefinition) -> None:
    # "Whenever you cast an enchantment spell, you may draw a card." The trigger goes
    # on the stack (CR 603.3); when it resolves, the optional draw is offered (a yes/no
    # prompt — human is asked; AI/headless auto-draws). Only fires for enchantments.
    if cast_card.primary_type != "enchantment":
        return
    controller_index = game.players.index(controller)
    game._enqueue_triggered_ability(
        controller_index=controller_index,
        source_permanent=permanent,
        effect_kind="triggered_draw",
        ability_text="Whenever you cast an enchantment spell, you may draw a card.",
        hook_key="optional_pay",
        hook_event={
            "card_name": permanent.card.name,
            "player_index": controller_index,
            "cost": 0,
            "life": 0,
            "draw": 1,
            "prompt": "Draw a card?",
        },
    )


ON_SPELL_CAST: dict[str, SpellCastHook] = {
    "Verduran Enchantress": _verduran_enchantress,
}


# Map: artifact name → (color that triggers it, life gained)
COLOR_ROD_TRIGGERS: dict[str, tuple[str, int]] = {
    "Crystal Rod": ("U", 1),
    "Iron Star": ("R", 1),
    "Ivory Cup": ("W", 1),
    "Throne of Bone": ("B", 1),
    "Wooden Sphere": ("G", 1),
}


def _make_color_rod_hook(trigger_color: str, life_amount: int) -> SpellCastAnyHook:
    def hook(game: Game, controller: PlayerState, permanent: Permanent, cast_card: CardDefinition) -> None:
        # "Whenever a player casts a [color] spell, you may pay {1}. If you do, you
        # gain 1 life." (Throne of Bone, Crystal Rod, Iron Star, Ivory Cup, Wooden
        # Sphere). The trigger fires as the spell is put on the stack and goes on the
        # stack above it (CR 603.3), so it resolves while the triggering spell is
        # still on the stack. When it resolves, the optional "pay {1}: gain life" is
        # offered — but only if the controller can actually pay (checked at
        # resolution, in _resolve_optional_pay_trigger).
        if trigger_color not in cast_card.colors:
            return
        controller_index = game.players.index(controller)
        game._enqueue_triggered_ability(
            controller_index=controller_index,
            source_permanent=permanent,
            effect_kind="triggered_gain_life",
            ability_text="Whenever a player casts a spell of the chosen color, you may pay {1}. If you do, gain 1 life.",
            hook_key="optional_pay",
            hook_event={
                "card_name": permanent.card.name,
                "player_index": controller_index,
                "cost": 1,
                "life": life_amount,
            },
        )

    return hook


ON_SPELL_CAST_ANY: dict[str, SpellCastAnyHook] = {
    name: _make_color_rod_hook(color, amount) for name, (color, amount) in COLOR_ROD_TRIGGERS.items()
}


def _guardian_angel(
    game: Game,
    caster: PlayerState,
    resolved_card: CardDefinition,
    target_player_index: int,
    target_permanent_index: int | None,
) -> None:
    # The first sentence (prevent the next X damage) resolves through the compiled
    # instruction. This hook adds the second sentence's granted ability: an emblem
    # the caster may activate ("pay {1}: prevent next 1 damage") until end of turn.
    # "That permanent or player" is the spell's original target, so the emblem
    # remembers it and never re-prompts on activation.
    caster.prevent_one_damage_emblems.append({
        "target_player_index": target_player_index,
        "target_permanent_index": target_permanent_index,
    })
    game.log.append(f"{caster.name} gains a Guardian Angel prevention emblem until end of turn")


ON_SELF_RESOLVED: dict[str, SelfResolvedHook] = {
    "Guardian Angel": _guardian_angel,
}


def _power_sink(game: Game, counter_card: CardDefinition, countered: StackItem) -> None:
    ctrl = game.players[countered.caster_index]
    for perm in ctrl.battlefield:
        if perm.card.primary_type == "land":
            perm.tapped = True
    ctrl.mana_pool = {k: 0 for k in ctrl.mana_pool}
    game.log.append(f"{counter_card.name} tapped all lands and drained mana from {ctrl.name}")


ON_SPELL_COUNTERED: dict[str, SpellCounteredHook] = {
    "Power Sink": _power_sink,
}


def _cyclopean_tomb_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "When this artifact is put into a graveyard from the battlefield, at the
    # beginning of each of your upkeeps for the rest of the game, remove all mire
    # counters from a land that a mire counter was put onto with this artifact but
    # that a mire counter has not been removed from with this artifact."
    #
    # Set up a rest-of-game obligation that removes the mire counter from one such
    # land per upkeep (drained in Game.resolve_upkeep). Only lands that are still
    # mired qualify — any whose counter was already removed are excluded.
    mired = permanent.metadata.get("mired_lands") or []
    remaining = [land for land in mired if land.metadata.get("mire_counter")]
    if not remaining:
        return
    controller_index = game.players.index(owner)
    game.mire_cleanup_obligations.append(
        {"controller_index": controller_index, "lands": remaining}
    )
    game.log.append(
        f"{permanent.card.name} left the battlefield; "
        f"{len(remaining)} mired land(s) will be freed over future upkeeps"
    )


def _consecrate_land_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "Enchanted land has indestructible and can't be enchanted by other Auras."
    # Both are continuous effects from this Aura — when it leaves the battlefield
    # the enchanted land loses indestructibility and may again be enchanted.
    land = permanent.metadata.get("attached_to")
    if land is None:
        return
    land.metadata.pop("is_indestructible", None)
    land.metadata.pop("cant_be_enchanted_by_auras", None)
    if land.metadata.get("attached_aura") is permanent:
        land.metadata.pop("attached_aura", None)


def _gaeas_liege_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "{T}: Target land becomes a Forest until this creature leaves the
    # battlefield." When Gaea's Liege leaves, the lands it forested revert to
    # their printed type (CR 611.3 — the duration ends).
    reverted = 0
    for land in permanent.metadata.get("forested_lands", []) or []:
        if land.metadata.get("land_type_override") == "forest":
            land.metadata.pop("land_type_override", None)
            reverted += 1
    if reverted:
        game.log.append(
            f"{permanent.card.name} left the battlefield; {reverted} land(s) reverted from Forest"
        )
    game._refresh_dynamic_creatures()


ON_LEAVE_BATTLEFIELD: dict[str, LeaveBattlefieldHook] = {
    "Cyclopean Tomb": _cyclopean_tomb_leaves,
    "Consecrate Land": _consecrate_land_leaves,
    "Gaea's Liege": _gaeas_liege_leaves,
}


# --------------------------------------------------------------------------
# Resolve-time trigger hooks
# --------------------------------------------------------------------------
# A triggered ability whose effect is a name-keyed hook is put on the stack like
# any other trigger. When it resolves, resolve_top_of_stack dispatches to
# TRIGGER_HOOKS[stack_item.hook_key], passing the StackItem; the handler reads
# stack_item.hook_event (captured when the trigger fired) and runs the effect.
# This is how the Rod/Cup/Sphere cycle and Verduran Enchantress raise their
# "you may pay {1} / draw a card" prompts at resolution rather than at fire time.

TriggerStackHook = Callable[["Game", "StackItem"], None]


def _resolve_optional_pay_trigger(game: Game, item: StackItem) -> None:
    """Resolve a deferred "you may pay {N}: gain life" / "you may draw a card"
    trigger (the color Rods, Verduran Enchantress). The pay/draw prompt is registered
    here — at resolution — so it appears only after the trigger leaves the stack,
    matching the Soul Net death-trigger behavior. A paid rider (Rods) is offered only
    when the controller can actually pay the {N}; a free rider (Verduran's draw) is
    always offered."""
    ev = item.hook_event or {}
    player_index = ev.get("player_index")
    if player_index is None or not (0 <= player_index < len(game.players)):
        return
    cost = int(ev.get("cost", 0))
    if cost > 0 and not game._player_can_pay_generic(game.players[player_index], cost):
        return
    entry: dict = {
        "card_name": ev["card_name"],
        "player_index": player_index,
        "cost": cost,
        "life": int(ev.get("life", 0)),
    }
    if "draw" in ev:
        entry["draw"] = ev["draw"]
    if "prompt" in ev:
        entry["prompt"] = ev["prompt"]
    game.pending_optional_pays.append(entry)


# hook_key → resolver.
TRIGGER_HOOKS: dict[str, TriggerStackHook] = {
    "optional_pay": _resolve_optional_pay_trigger,
}


# --------------------------------------------------------------------------
# Untap-step restrictions (CR 502)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class UntapRestriction:
    """Declarative "don't untap as normal" constraint from a permanent.

    scope      -- what the restriction applies to: "all" | "land" | "creature"
    limit      -- max permanents of that scope the active player may untap
                  (0 with scope="all" skips the untap step entirely; None
                  means no count limit)
    min_power  -- per-permanent block: creatures with effective power >= N
                  don't untap (Meekstone)
    only_while_source_untapped -- the restriction is active only while the
                  source permanent itself is untapped (Winter Orb)
    """

    scope: str
    limit: int | None = None
    min_power: int | None = None
    only_while_source_untapped: bool = False


UNTAP_RESTRICTIONS: dict[str, UntapRestriction] = {
    "Stasis": UntapRestriction(scope="all", limit=0),
    "Winter Orb": UntapRestriction(scope="land", limit=1, only_while_source_untapped=True),
    "Smoke": UntapRestriction(scope="creature", limit=1),
    "Meekstone": UntapRestriction(scope="creature", min_power=3),
}


# --------------------------------------------------------------------------
# Draw-step modifiers (CR 504)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DrawStepModifier:
    """Draw-step behavior granted by a permanent.

    optional_skip_grants_protection -- its controller may skip their draw to
                  gain "attack only me with flyers" protection (Island Sanctuary)
    extra_draws -- bonus cards drawn in EVERY player's draw step (Howling Mine)
    requires_untapped -- the modifier applies only while the source is untapped
    """

    optional_skip_grants_protection: bool = False
    extra_draws: int = 0
    requires_untapped: bool = False


DRAW_STEP_MODIFIERS: dict[str, DrawStepModifier] = {
    "Island Sanctuary": DrawStepModifier(optional_skip_grants_protection=True),
    "Howling Mine": DrawStepModifier(extra_draws=1, requires_untapped=True),
}


# --------------------------------------------------------------------------
# Mana-production modifiers ("whenever a land is tapped for mana")
# --------------------------------------------------------------------------
# Fired once per registered permanent on any battlefield, after the land's own
# mana is added: (game, tapping_player_index, land, produced_symbol,
# source_permanent, source_controller_index).

ManaProductionHook = Callable[["Game", int, "Permanent", str, "Permanent", int], None]


def _land_has_type(land: Permanent, land_type: str) -> bool:
    override = str(land.metadata.get("land_type_override", "")).lower()
    return land_type in land.card.type_line.lower() or land_type in override


def _mana_flare(game: Game, tapping_index: int, land: Permanent, symbol: str,
                source: Permanent, source_index: int) -> None:
    # "Whenever a player taps a land for mana, that player adds one mana of any
    # type that land produced." — modeled as one extra of the produced symbol.
    player = game.players[tapping_index]
    player.mana_pool[symbol] = player.mana_pool.get(symbol, 0) + 1


def _gauntlet_of_might(game: Game, tapping_index: int, land: Permanent, symbol: str,
                       source: Permanent, source_index: int) -> None:
    # "Whenever a Mountain is tapped for mana, its controller adds {R}."
    if _land_has_type(land, "mountain"):
        player = game.players[tapping_index]
        player.mana_pool["R"] = player.mana_pool.get("R", 0) + 1


def _lifetap(game: Game, tapping_index: int, land: Permanent, symbol: str,
             source: Permanent, source_index: int) -> None:
    # "Whenever an opponent taps a Forest for mana, you gain 1 life."
    if source_index != tapping_index and _land_has_type(land, "forest"):
        game._gain_life(game.players[source_index], 1, "Lifetap")


MANA_PRODUCTION_MODIFIERS: dict[str, ManaProductionHook] = {
    "Mana Flare": _mana_flare,
    "Gauntlet of Might": _gauntlet_of_might,
    "Lifetap": _lifetap,
}


# --------------------------------------------------------------------------
# Cost modifiers (extra generic mana taxed onto casts / activations)
# --------------------------------------------------------------------------
# Applied once per registered permanent on any battlefield. Return the extra
# generic mana (0 = no tax for this cast/activation).

SpellCostModifier = Callable[["Game", int, "CardDefinition"], int]
AbilityCostModifier = Callable[["Game", int, "Permanent"], int]


def _gloom_spell_tax(game: Game, caster_index: int, card: CardDefinition) -> int:
    # Gloom: "White spells cost {3} more to cast."
    return 3 if "W" in card.colors else 0


def _gloom_ability_tax(game: Game, controller_index: int, source: Permanent) -> int:
    # Gloom: "Activated abilities of white enchantments cost {3} more to activate."
    card = source.effective_card
    return 3 if ("enchantment" in card.type_line.lower() and "W" in card.colors) else 0


SPELL_COST_MODIFIERS: dict[str, SpellCostModifier] = {
    "Gloom": _gloom_spell_tax,
}

ABILITY_COST_MODIFIERS: dict[str, AbilityCostModifier] = {
    "Gloom": _gloom_ability_tax,
}


def spell_cost_tax(game: Game, caster_index: int, card: CardDefinition) -> tuple[int, list[str]]:
    """Total extra generic mana for casting *card*, plus the taxing permanents'
    names (for logging). One application per registered permanent (two Glooms
    tax {6})."""
    total = 0
    names: list[str] = []
    for player in game.players:
        for perm in player.battlefield:
            modifier = SPELL_COST_MODIFIERS.get(perm.card.name)
            if modifier is None:
                continue
            extra = modifier(game, caster_index, card)
            if extra:
                total += extra
                names.append(perm.card.name)
    return total, names


def ability_cost_tax(game: Game, controller_index: int, source: Permanent) -> tuple[int, list[str]]:
    """Total extra generic mana for activating *source*'s ability, plus the
    taxing permanents' names (for logging)."""
    total = 0
    names: list[str] = []
    for player in game.players:
        for perm in player.battlefield:
            modifier = ABILITY_COST_MODIFIERS.get(perm.card.name)
            if modifier is None:
                continue
            extra = modifier(game, controller_index, source)
            if extra:
                total += extra
                names.append(perm.card.name)
    return total, names
