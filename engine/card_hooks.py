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
- ON_SPELL_COUNTERED  — fired after the named card counters a spell (keyed by
                        the counterspell's own name).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game
    from .game_types import StackItem
    from .models import CardDefinition, Permanent, PlayerState

SpellCastHook = Callable[["Game", "PlayerState", "Permanent", "CardDefinition"], None]
SpellResolvedHook = Callable[["Game", "PlayerState", "Permanent", "CardDefinition"], None]
SpellCounteredHook = Callable[["Game", "CardDefinition", "StackItem"], None]


def _verduran_enchantress(game: Game, controller: PlayerState, permanent: Permanent, cast_card: CardDefinition) -> None:
    if cast_card.primary_type != "enchantment":
        return
    drawn = controller.draw(1)
    game.log.append(f"Verduran Enchantress trigger: {controller.name} drew {drawn} card")


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
        if trigger_color in resolved_card.colors:
            game._gain_life(controller, life_amount, permanent.card.name)

    return hook


ON_SPELL_RESOLVED: dict[str, SpellResolvedHook] = {
    name: _make_color_rod_hook(color, amount) for name, (color, amount) in COLOR_ROD_TRIGGERS.items()
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
