from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


GameMode = Literal["human_vs_ai", "ai_vs_ai", "human_vs_human"]
ActionKind = Literal[
    "cast",
    "activate",
    "pass_priority",
    "tap",
    "end_turn",
    "next_phase",
    "declare_attackers",
    "declare_blockers",
    "assign_combat_damage",
    "ai_step",
    "cleanup_select",
    "untap_select",
    "untap_confirm",
    "pay_upkeep",
    "sacrifice_upkeep",
    "debug_add_to_hand",
    "debug_cast_free",
    "search_library_confirm",
]


class CreateSessionRequest(BaseModel):
    mode: GameMode
    host_name: str = Field(default="Player 1")
    guest_name: str = Field(default="Player 2")
    host_colors: int = Field(default=2, ge=1, le=5)
    guest_colors: int = Field(default=2, ge=1, le=5)
    use_custom_seed: bool = Field(default=False)
    custom_seed: int | None = Field(default=None)
    # Backward-compatible field for older clients that still post `seed`.
    seed: int | None = Field(default=None)


class JoinSessionRequest(BaseModel):
    guest_name: str = Field(default="Player 2")


class GameActionRequest(BaseModel):
    seat: int = Field(ge=0, le=1)
    action: ActionKind
    card_name: str | None = None
    permanent_name: str | None = None
    permanent_index: int | None = Field(default=None, ge=0)
    target_seat: int | None = Field(default=None, ge=0, le=1)
    x_value: int | None = Field(default=None, ge=0)
    hand_index: int | None = Field(default=None, ge=0)
    mana_color: Literal["W", "U", "B", "R", "G"] | None = None
    attacker_indices: list[int] | None = None
    blocker_pairs: dict[int, int] | None = None
    attacker_damage: dict[int, dict[int, int]] | None = None


class RandomDeckRequest(BaseModel):
    colors: int = Field(ge=1, le=5)
    seed: int = 1337
