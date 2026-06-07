from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

    def _base_stat(self, key: str) -> int:
        raw_value = str(self.card.raw.get(key, "0"))
        return int(raw_value) if raw_value.isdigit() else 0

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
        return base + self.power_bonus + int(self.metadata.get("static_buff_power", 0))

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
        return base + self.toughness_bonus + int(self.metadata.get("static_buff_toughness", 0))


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
    combat_damage_cap_one_charges: int = 0
    has_no_max_hand_size: bool = False
    can_spend_white_as_red: bool = False
    channel_active_until_eot: bool = False
    island_sanctuary_protected: bool = False
    lost: bool = False
    drew_from_empty: bool = False

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
