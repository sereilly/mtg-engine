"""Name-keyed registries for card-specific behavior.

Most cards should be handled generically by parse rules (engine/parsing) and
effect handlers (engine/handlers). When a card needs truly bespoke logic that
no generic instruction covers, register it here instead of hardcoding the card
name inside engine internals. This keeps per-card behavior in one place and
lets the card pool grow without touching the core rules code.

Hook registries:
- ON_SPELL_CAST       — fired when a player casts a spell, once per permanent
                        that player controls whose name is registered.
- ON_SPELL_RESOLVED   — fired after a spell resolves, once per permanent on any
                        battlefield whose name is registered.
- ON_SELF_RESOLVED    — fired when the named instant/sorcery itself resolves
                        (keyed by the resolving card's own name), for bespoke
                        effects the single compiled instruction can't express.
- ON_SPELL_COUNTERED  — fired after the named card counters a spell (keyed by
                        the counterspell's own name).
- ON_LEAVE_BATTLEFIELD — fired when the named permanent is put into a graveyard
                        from the battlefield (keyed by the permanent's name).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game
    from .game_types import StackItem
    from .models import CardDefinition, Permanent, PlayerState

SpellCastHook = Callable[["Game", "PlayerState", "Permanent", "CardDefinition"], None]
SpellResolvedHook = Callable[["Game", "PlayerState", "Permanent", "CardDefinition"], None]
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


def _make_color_rod_hook(trigger_color: str, life_amount: int) -> SpellResolvedHook:
    def hook(game: Game, controller: PlayerState, permanent: Permanent, resolved_card: CardDefinition) -> None:
        # "Whenever a player casts a [color] spell, you may pay {1}. If you do, you
        # gain 1 life." (Throne of Bone, Crystal Rod, Iron Star, Ivory Cup, Wooden
        # Sphere). The trigger goes on the stack (CR 603.3); when it resolves, the
        # optional "pay {1}: gain life" is offered — but only if the controller can
        # actually pay (checked at resolution, in _resolve_optional_pay_trigger).
        if trigger_color not in resolved_card.colors:
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


ON_SPELL_RESOLVED: dict[str, SpellResolvedHook] = {
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
