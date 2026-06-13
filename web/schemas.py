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
    "debug_cast_free_opponent",
    "debug_add_mana",
    "search_library_confirm",
    "reorder_library_confirm",
    "coin_flip_choose",
    "mulligan_take",
    "mulligan_keep",
    "mulligan_bottom_select",
    "mulligan_bottom_confirm",
]


class CreateSessionRequest(BaseModel):
    mode: GameMode
    host_name: str = Field(default="Player 1")
    guest_name: str = Field(default="Player 2")
    host_colors: int = Field(default=2, ge=1, le=5)
    guest_colors: int = Field(default=2, ge=1, le=5)
    # When set, use a saved deck (by id) instead of a random deck for that seat.
    host_deck_id: str | None = Field(default=None)
    guest_deck_id: str | None = Field(default=None)
    use_custom_seed: bool = Field(default=False)
    custom_seed: int | None = Field(default=None)
    # Backward-compatible field for older clients that still post `seed`.
    seed: int | None = Field(default=None)
    # When True, show interactive coin-flip and mulligan prompts before the game starts.
    enable_pregame: bool = Field(default=False)


class JoinSessionRequest(BaseModel):
    guest_name: str = Field(default="Player 2")


class GameActionRequest(BaseModel):
    seat: int = Field(ge=0, le=1)
    action: ActionKind
    card_name: str | None = None
    permanent_name: str | None = None
    permanent_index: int | None = Field(default=None, ge=0)
    target_permanent_index: int | None = Field(default=None, ge=0)
    target_seat: int | None = Field(default=None, ge=0, le=1)
    x_value: int | None = Field(default=None, ge=0)
    hand_index: int | None = Field(default=None, ge=0)
    mana_color: Literal["W", "U", "B", "R", "G", "C"] | None = None
    attacker_indices: list[int] | None = None
    blocker_pairs: dict[int, int] | None = None
    attacker_damage: dict[int, dict[int, int]] | None = None
    card_order: list[int] | None = None
    # Steps (engine step names) the human wants to stop at on the opponent's turn.
    # Sent with `ai_step` so the AI hands priority to the human at those steps
    # instead of advancing past them. Set via the phase-rail hold-priority toggles.
    stop_steps: list[str] | None = None


class RandomDeckRequest(BaseModel):
    colors: int = Field(ge=1, le=5)
    seed: int = 1337


class DeckCardEntry(BaseModel):
    name: str = Field(min_length=1)
    count: int = Field(ge=1, le=99)


class DeckSaveRequest(BaseModel):
    name: str = Field(default="Untitled Deck", max_length=100)
    cards: list[DeckCardEntry] = Field(default_factory=list)


class DeckImportRequest(BaseModel):
    text: str | None = None
    url: str | None = None


class VerificationRequest(BaseModel):
    card_name: str = Field(min_length=1)
    status: Literal["pass", "fail"]
    reason: str | None = None
