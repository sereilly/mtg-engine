from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


GameMode = Literal["human_vs_ai", "ai_vs_ai", "human_vs_human"]
ActionKind = Literal[
    "cast",
    "activate",
    "activate_emblem",
    "channel_mana",
    "pass_priority",
    "tap",
    "end_turn",
    "next_phase",
    "declare_attackers",
    "declare_blockers",
    "assign_combat_damage",
    "assign_banding_damage",
    "ai_step",
    "cleanup_select",
    "untap_select",
    "untap_confirm",
    "pay_upkeep",
    "sacrifice_upkeep",
    "resolve_optional_trigger",
    "pay_upkeep_prevention",
    "debug_add_to_hand",
    "debug_cast_free",
    "debug_cast_free_opponent",
    "debug_add_mana",
    "debug_force_ai_attack_all",
    "search_library_confirm",
    "reorder_library_confirm",
    "discard_confirm",
    "balance_confirm",
    "resolve_optional_pay",
    "assign_defender_piles",
    "assign_attacker_piles",
    "dismiss_hand_reveal",
    "coin_flip_choose",
    "mulligan_take",
    "mulligan_keep",
    "mulligan_bottom_select",
    "mulligan_bottom_confirm",
]


class DeckCardEntry(BaseModel):
    name: str = Field(min_length=1)
    count: int = Field(ge=1, le=99)


class CreateSessionRequest(BaseModel):
    mode: GameMode
    host_name: str = Field(default="Player 1")
    guest_name: str = Field(default="Player 2")
    host_colors: int = Field(default=2, ge=1, le=5)
    guest_colors: int = Field(default=2, ge=1, le=5)
    # When set, use a saved deck (by id) instead of a random deck for that seat.
    host_deck_id: str | None = Field(default=None)
    guest_deck_id: str | None = Field(default=None)
    # Personal decks live only in the client's browser (localStorage), so they have
    # no server-side id. The client sends the deck's cards inline instead; when
    # present these take precedence over the *_deck_id for that seat.
    host_deck_cards: list[DeckCardEntry] | None = Field(default=None)
    guest_deck_cards: list[DeckCardEntry] | None = Field(default=None)
    use_custom_seed: bool = Field(default=False)
    custom_seed: int | None = Field(default=None)
    # Backward-compatible field for older clients that still post `seed`.
    seed: int | None = Field(default=None)
    # When True, show interactive coin-flip and mulligan prompts before the game starts.
    enable_pregame: bool = Field(default=False)


class JoinSessionRequest(BaseModel):
    guest_name: str = Field(default="Player 2")
    # The joining player picks their own deck; sent to the host with their name.
    # When unset, a random deck is built for them.
    guest_deck_id: str | None = Field(default=None)
    # Personal (browser-only) deck sent inline; takes precedence over guest_deck_id.
    guest_deck_cards: list[DeckCardEntry] | None = Field(default=None)
    guest_colors: int = Field(default=2, ge=1, le=5)


class GameActionRequest(BaseModel):
    seat: int = Field(ge=0, le=1)
    action: ActionKind
    card_name: str | None = None
    permanent_name: str | None = None
    permanent_index: int | None = Field(default=None, ge=0)
    target_permanent_index: int | None = Field(default=None, ge=0)
    # Fireball and other "divided among any number of targets" spells: the list
    # of battlefield indices (on target_seat) the damage is split among. Takes
    # precedence over the single permanent_index when present.
    target_permanent_indices: list[int] | None = Field(default=None)
    target_seat: int | None = Field(default=None, ge=0, le=1)
    # Which of the acting player's emblems to activate (activate_emblem action).
    emblem_index: int | None = Field(default=None, ge=0)
    x_value: int | None = Field(default=None, ge=0)
    hand_index: int | None = Field(default=None, ge=0)
    mana_color: Literal["W", "U", "B", "R", "G", "C"] | None = None
    attacker_indices: list[int] | None = None
    # Banding (CR 702.22c): attacking bands, each a list of attacker battlefield
    # indices, declared alongside attacker_indices in a declare_attackers action.
    bands: list[list[int]] | None = None
    blocker_pairs: dict[int, int] | None = None
    attacker_damage: dict[int, dict[int, int]] | None = None
    # Banding (CR 702.22k): how a shared blocker's damage is routed among the band
    # members it blocks — maps blocker battlefield index to the chosen attacker index.
    blocker_damage: dict[int, int] | None = None
    # Banding (CR 702.22j): the defending player's damage assignment for attackers
    # blocked by a creature with banding, submitted via an assign_banding_damage action.
    banding_damage: dict[int, dict[int, int]] | None = None
    card_order: list[int] | None = None
    # Disrupting Scepter discard choice: which hand-card indices to discard, and
    # (Library of Leng) whether to put them on top of the library instead.
    discard_indices: list[int] | None = None
    to_library: bool | None = None
    # Balance: the indices the player chooses to sacrifice/discard — land and
    # creature indices into their battlefield, plus hand-card indices to discard.
    land_indices: list[int] | None = None
    creature_indices: list[int] | None = None
    # Raging River: map of battlefield/attacker index → "left"/"right" pile label,
    # sent with assign_defender_piles / assign_attacker_piles.
    piles: dict[int, str] | None = None
    # Counterspell / Fork: which spell on the stack to target, as a top-first index
    # into the serialized stack (0 = topmost). Converted server-side to an engine
    # stack index.
    target_stack_index: int | None = Field(default=None, ge=0)
    # Natural Selection: "you may have that player shuffle" — true to shuffle the
    # target's library after reordering its top cards.
    shuffle: bool | None = None
    # "Choose one —" modal spells (Healing Salve, the Elemental Blasts): which
    # mode the caster picked, as an index into the card's serialized `modes`.
    mode_index: int | None = Field(default=None, ge=0)
    # Yes/No answer for an optional ("you may") trigger prompt, sent with the
    # `resolve_optional_trigger` action (true = let the trigger happen).
    accept: bool | None = None
    # Generic numeric amount for prompts that ask for one — e.g. how much mana to
    # pay with `pay_upkeep_prevention` (Power Leak: prevent that much damage).
    amount: int | None = Field(default=None, ge=0)
    # Debug toggle (`debug_force_ai_attack_all`): when true, the AI declares every
    # legal attacker each combat instead of its normal risk-weighted selection.
    force_attack_all: bool | None = None
    # Which activated ability to use, for permanents with more than one (Rock Hydra:
    # 0 = {R} prevention, 1 = {R}{R}{R} +1/+1 counter). Index into the permanent's
    # supported activated abilities. Omitted (None) uses the first one.
    ability_index: int | None = Field(default=None, ge=0)
    # Steps (engine step names) the human wants to stop at on the opponent's turn.
    # Sent with `ai_step` so the AI hands priority to the human at those steps
    # instead of advancing past them. Set via the phase-rail hold-priority toggles.
    stop_steps: list[str] | None = None
    # Steps the human wants a priority window at on their OWN turn. Sent so the
    # server opens a window at steps it would otherwise resolve itself (upkeep,
    # draw). Set via the phase-rail hold-priority toggles (left/own-turn halves).
    self_stop_steps: list[str] | None = None


class RawStateRequest(BaseModel):
    # The full serialized game-state object (as produced by GET .../state and
    # shown in the board's Raw State tab), pasted back to overwrite the live game.
    state: dict
    seat: int | None = Field(default=None, ge=0, le=1)


class RematchRequest(BaseModel):
    seat: int = Field(ge=0, le=1)


class RandomDeckRequest(BaseModel):
    colors: int = Field(ge=1, le=5)
    seed: int = 1337


class DeckSaveRequest(BaseModel):
    name: str = Field(default="Untitled Deck", max_length=100)
    description: str = Field(default="", max_length=2000)
    cards: list[DeckCardEntry] = Field(default_factory=list)


class DeckImportRequest(BaseModel):
    text: str | None = None
    url: str | None = None


class VerificationRequest(BaseModel):
    card_name: str = Field(min_length=1)
    status: Literal["pass", "fail"]
    reason: str | None = None
