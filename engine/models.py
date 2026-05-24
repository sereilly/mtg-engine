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

    def _base_stat(self, key: str) -> int:
        raw_value = str(self.card.raw.get(key, "0"))
        return int(raw_value) if raw_value.isdigit() else 0

    @property
    def effective_power(self) -> int:
        if "absolute_power" in self.metadata:
            return int(self.metadata["absolute_power"])
        return self._base_stat("power") + self.power_bonus

    @property
    def effective_toughness(self) -> int:
        if "absolute_toughness" in self.metadata:
            return int(self.metadata["absolute_toughness"])
        return self._base_stat("toughness") + self.toughness_bonus


@dataclass
class PlayerState:
    name: str
    life: int = 20
    hand: list[CardDefinition] = field(default_factory=list)
    library: list[CardDefinition] = field(default_factory=list)
    battlefield: list[Permanent] = field(default_factory=list)
    graveyard: list[CardDefinition] = field(default_factory=list)
    mana_pool: dict[str, int] = field(
        default_factory=lambda: {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    )
    damage_prevention_pool: int = 0
    combat_damage_cap_one_charges: int = 0
    has_no_max_hand_size: bool = False
    can_spend_white_as_red: bool = False

    def draw(self, count: int = 1) -> int:
        actual = 0
        for _ in range(count):
            if not self.library:
                break
            self.hand.append(self.library.pop(0))
            actual += 1
        return actual
