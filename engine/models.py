from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Basic land subtype → the mana symbol it taps for. Used when a land's type has
# been overridden (e.g. Evil Presence makes a land a Swamp).
_LAND_TYPE_MANA = {
    "plains": "W",
    "island": "U",
    "swamp": "B",
    "mountain": "R",
    "forest": "G",
}


@dataclass(frozen=True)
class CardDefinition:
    name: str
    mana_cost: str
    cmc: float
    type_line: str
    oracle_text: str
    colors: tuple[str, ...]
    color_identity: tuple[str, ...]
    keywords: tuple[str, ...]
    produced_mana: tuple[str, ...]
    raw: dict[str, Any]

    @property
    def primary_type(self) -> str:
        lowered = self.type_line.lower()
        for known in ("land", "creature", "artifact", "enchantment", "instant", "sorcery"):
            if known in lowered:
                return known
        return self.type_line.split(" ")[0].strip().lower()


@dataclass
class Permanent:
    card: CardDefinition
    tapped: bool = False
    power_bonus: int = 0
    toughness_bonus: int = 0
    regeneration_shield: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    attacking: bool = False
    defending_player_index: int | None = None
    blocked: bool = False
    blocking_attacker_controller: int | None = None
    blocking_attacker_index: int | None = None
    damage_marked: int = 0
    # "Prevent the next N damage that would be dealt to this creature this turn"
    # (Healing Salve's prevention mode, Samite Healer, …). Consumed as damage —
    # combat or spell — would be marked, and cleared during cleanup.
    damage_prevention_pool: int = 0
    # Name of the card/effect that granted the current prevention pool, so the UI
    # can show its art when the shield badge is hovered. Cleared with the pool
    # (when fully consumed or during cleanup).
    damage_prevention_source: str | None = None

    def _base_stat(self, key: str) -> int:
        raw_value = str(self.card.raw.get(key, "0"))
        return int(raw_value) if raw_value.isdigit() else 0

    @property
    def effective_produced_mana(self) -> tuple[str, ...]:
        """Mana this permanent produces, honoring a land-type override.

        "Enchanted land is a Swamp" (Evil Presence) / Phantasmal Terrain replace
        the land's types, so it produces only the override type's mana and loses
        its printed mana ability (CR 305.7).
        """
        override = str(self.metadata.get("land_type_override", "")).lower()
        if override:
            for land_type, symbol in _LAND_TYPE_MANA.items():
                if land_type in override:
                    return (symbol,)
        return self.card.produced_mana

    @property
    def effective_power(self) -> int:
        # Layer 7d: power/toughness switch — return pre-switch toughness as power
        if self.metadata.get("pt_switched"):
            if "absolute_toughness_until_eot" in self.metadata:
                t_base = int(self.metadata["absolute_toughness_until_eot"])
            elif "absolute_toughness" in self.metadata:
                t_base = int(self.metadata["absolute_toughness"])
            else:
                t_base = self._base_stat("toughness")
            return t_base + self.toughness_bonus + int(self.metadata.get("static_buff_toughness", 0))
        # Layer 7b: temporary set effect takes priority over permanent set
        if "absolute_power_until_eot" in self.metadata:
            base = int(self.metadata["absolute_power_until_eot"])
        elif "absolute_power" in self.metadata:
            base = int(self.metadata["absolute_power"])
        else:
            base = self._base_stat("power")
        # Layer 7c: modifications on top of 7b base
        return (
            base
            + self.power_bonus
            + int(self.metadata.get("static_buff_power", 0))
            + (int(self.metadata.get("attacking_buff_power", 0)) if self.attacking else 0)
        )

    @property
    def effective_toughness(self) -> int:
        # Layer 7d: power/toughness switch — return pre-switch power as toughness
        if self.metadata.get("pt_switched"):
            if "absolute_power_until_eot" in self.metadata:
                p_base = int(self.metadata["absolute_power_until_eot"])
            elif "absolute_power" in self.metadata:
                p_base = int(self.metadata["absolute_power"])
            else:
                p_base = self._base_stat("power")
            return p_base + self.power_bonus + int(self.metadata.get("static_buff_power", 0))
        # Layer 7b: temporary set effect takes priority over permanent set
        if "absolute_toughness_until_eot" in self.metadata:
            base = int(self.metadata["absolute_toughness_until_eot"])
        elif "absolute_toughness" in self.metadata:
            base = int(self.metadata["absolute_toughness"])
        else:
            base = self._base_stat("toughness")
        # Layer 7c: modifications on top of 7b base
        return (
            base
            + self.toughness_bonus
            + int(self.metadata.get("static_buff_toughness", 0))
            + (int(self.metadata.get("attacking_buff_toughness", 0)) if self.attacking else 0)
        )


@dataclass
class PlayerState:
    name: str
    life: int = 20
    hand: list[CardDefinition] = field(default_factory=list)
    library: list[CardDefinition] = field(default_factory=list)
    battlefield: list[Permanent] = field(default_factory=list)
    graveyard: list[CardDefinition] = field(default_factory=list)
    exile: list[CardDefinition] = field(default_factory=list)
    mana_pool: dict[str, int] = field(
        default_factory=lambda: {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    )
    damage_prevention_pool: int = 0
    # Name of the card/effect that granted the player's current prevention pool,
    # surfaced as a hover preview on the life pill's shield badge.
    damage_prevention_source: str | None = None
    # Color symbol of the source a Circle of Protection shield is set against
    # (e.g. "R" for Circle of Protection: Red), for UI display.
    damage_prevention_color: str | None = None
    # Circle of Protection shields: one color symbol per active shield. Each
    # prevents the entire next damage event from a source of that color this turn
    # ("prevent that damage"), then is consumed. Cleared during cleanup.
    color_prevention_shields: list[str] = field(default_factory=list)
    combat_damage_cap_one_charges: int = 0
    # Forcefield: "The next time an unblocked creature of your choice would deal
    # combat damage to you this turn, prevent all but 1 of that damage." Each entry
    # is a chosen attacking Permanent; the next damage from it to this player is
    # capped to 1, then the entry is consumed. Cleared at end of combat / cleanup.
    forcefield_capped_sources: list = field(default_factory=list)
    # Reverse Damage: "The next time a source of your choice would deal damage to
    # you this turn, prevent that damage. You gain life equal to the damage
    # prevented this way." Each charge prevents the entire next damage event to
    # the player and gains that much life, then is consumed. Cleared at cleanup.
    reverse_damage_charges: int = 0
    has_no_max_hand_size: bool = False
    can_spend_white_as_red: bool = False
    channel_active_until_eot: bool = False
    # "Pay {1} any time you could cast an instant: prevent the next 1 damage to
    # that permanent or player" emblems the player controls until end of turn
    # (granted by Guardian Angel). One entry per granting spell; each is
    # repeatable. "That permanent or player" is the original spell's target, so
    # each entry records it as {"target_player_index", "target_permanent_index"}.
    prevent_one_damage_emblems: list = field(default_factory=list)
    island_sanctuary_protected: bool = False
    lost: bool = False
    drew_from_empty: bool = False
    mulligans_taken: int = 0
    poison_counters: int = 0
    damage_taken_this_turn: int = 0

    def draw(self, count: int = 1) -> int:
        actual = 0
        for _ in range(count):
            if not self.library:
                # 704.5b: track attempt to draw from empty library
                if count > actual:
                    self.drew_from_empty = True
                break
            self.hand.append(self.library.pop(0))
            actual += 1
        return actual
