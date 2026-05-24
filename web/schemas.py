from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


GameMode = Literal["human_vs_ai", "ai_vs_ai", "human_vs_human"]
ActionKind = Literal["cast", "activate", "tap", "end_turn", "ai_step"]


class CreateSessionRequest(BaseModel):
    mode: GameMode
    host_name: str = Field(default="Player 1")
    guest_name: str = Field(default="Player 2")
    host_colors: int = Field(default=2, ge=1, le=5)
    guest_colors: int = Field(default=2, ge=1, le=5)
    seed: int = Field(default=1337)


class JoinSessionRequest(BaseModel):
    guest_name: str = Field(default="Player 2")


class GameActionRequest(BaseModel):
    seat: int = Field(ge=0, le=1)
    action: ActionKind
    card_name: str | None = None
    permanent_name: str | None = None
    target_seat: int | None = Field(default=None, ge=0, le=1)
    x_value: int | None = Field(default=None, ge=0)


class RandomDeckRequest(BaseModel):
    colors: int = Field(ge=1, le=5)
    seed: int = 1337
