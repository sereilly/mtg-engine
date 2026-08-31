from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


GameMode = Literal["human_vs_ai", "ai_vs_ai", "human_vs_human", "free_for_all"]
ActionKind = Literal[
    "cast",
    "activate",
    "activate_emblem",
    "channel_mana",
    "pass_priority",
    "concede",
    "tap",
    "end_turn",
    "next_phase",
    "declare_attackers",
    "declare_blockers",
    "assign_combat_damage",
    "assign_banding_damage",
    "assign_multiblock_damage",
    "ai_step",
    "cleanup_select",
    "untap_select",
    "untap_confirm",
    "optional_untap_confirm",
    "pay_upkeep",
    "sacrifice_upkeep",
    "resolve_optional_trigger",
    "pay_upkeep_prevention",
    "debug_add_to_hand",
    "debug_add_to_sideboard",
    "debug_cast_free",
    "debug_cast_free_opponent",
    "debug_add_mana",
    "debug_force_ai_attack_all",
    "debug_clear_summoning_sickness",
    "debug_tap_permanent",
    "debug_untap_permanent",
    "debug_return_to_hand",
    "debug_destroy_permanent",
    "debug_exile_permanent",
    "debug_create_copy",
    "debug_send_to_opponent",
    "search_library_confirm",
    "search_library_decline",
    "search_exile_confirm",
    "search_destination_confirm",
    "tap_any_number_confirm",
    "trigger_target_confirm",
    "reflexive_target_confirm",
    "copy_spell_target_confirm",
    "permanent_choice_confirm",
    "untap_up_to_confirm",
    "look_top_pick_confirm",
    "name_and_strip_confirm",
    "name_and_random_reveal_confirm",
    "name_then_reveal_top_confirm",
    "name_then_consult_confirm",
    "graveyard_pick_for_price_confirm",
    "reorder_library_confirm",
    "scry_confirm",
    "discard_confirm",
    "hand_to_library_confirm",
    "revealed_hand_pick_confirm",
    "leng_discard_confirm",
    "optional_damage_redirect_confirm",
    "commander_zone_change_confirm",
    "balance_confirm",
    "sacrifice_confirm",
    "effect_order_confirm",
    "resolve_optional_pay",
    "pay_life_to_save_confirm",
    "land_type_confirm",
    "number_choice_confirm",
    "confirm_mana_payment",
    "kudzu_reattach_confirm",
    "face_down_cast_confirm",
    "exile_from_hand_confirm",
    "put_from_hand_confirm",
    "choose_cards_in_hand_confirm",
    "time_vault_skip",
    "time_vault_decline",
    "island_sanctuary_skip",
    "island_sanctuary_draw",
    "word_of_command_confirm",
    "opponent_damage_choose",
    "enter_choice_confirm",
    "body_choice_confirm",
    "entry_exile_confirm",
    "least_power_choice_confirm",
    "player_choice_confirm",
    "cast_choice_confirm",
    "loyalty_recipient_confirm",
    "mode_choice_confirm",
    "lamp_draw_confirm",
    "outside_game_draw_confirm",
    "assign_defender_piles",
    "assign_attacker_piles",
    "assign_camouflage_piles",
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


class SeatConfig(BaseModel):
    """One seat's configuration for a Free-For-All session (mode="free_for_all").
    Mirrors the host/guest fields ``CreateSessionRequest`` already carries for the
    2-player modes, one per seat instead of a fixed host/guest pair."""
    name: str = Field(default="Player")
    is_ai: bool = Field(default=False)
    colors: int = Field(default=2, ge=1, le=5)
    deck_id: str | None = Field(default=None)
    # Personal (browser-only) deck sent inline; takes precedence over deck_id.
    deck_cards: list[DeckCardEntry] | None = Field(default=None)
    # That deck's sideboard ("outside the game", CR 100.4), sent alongside
    # deck_cards for the same reason.
    deck_sideboard: list[DeckCardEntry] | None = Field(default=None)
    # That deck's command zone (CR 903.5a), sent for the same reason. Used only
    # when the session's `variant` names a Commander variant.
    deck_commander: list[DeckCardEntry] | None = Field(default=None)
    # Display name for the lobby roster (saved deck name or personal deck
    # name); the server has no other way to resolve a personal deck's name.
    deck_name: str | None = Field(default=None)


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
    # Those decks' sideboards ("outside the game", CR 100.4).
    host_deck_sideboard: list[DeckCardEntry] | None = Field(default=None)
    guest_deck_sideboard: list[DeckCardEntry] | None = Field(default=None)
    # Those decks' command zones (CR 903.5a).
    host_deck_commander: list[DeckCardEntry] | None = Field(default=None)
    guest_deck_commander: list[DeckCardEntry] | None = Field(default=None)
    # Display names for the lobby roster (see SeatConfig.deck_name).
    host_deck_name: str | None = Field(default=None)
    guest_deck_name: str | None = Field(default=None)
    use_custom_seed: bool = Field(default=False)
    custom_seed: int | None = Field(default=None)
    # Backward-compatible field for older clients that still post `seed`.
    seed: int | None = Field(default=None)
    # When True, show interactive coin-flip and mulligan prompts before the game starts.
    enable_pregame: bool = Field(default=False)
    # When True (and pregame is enabled), every player decides keep/mulligan at
    # the same time instead of in turn order — each seat gets its own prompt
    # immediately and the game starts once everyone has kept (and bottomed).
    simultaneous_mulligan: bool = Field(default=False)
    # CR 407.1: play this game for ante — every player antes one random card from
    # their deck before the game starts and the winner keeps the ante zone. Off by
    # default; while off, no seat's deck may contain a card that says "Remove this
    # card from your deck before playing if you're not playing for ante" (CR 407.3),
    # and random decks are built without them.
    playing_for_ante: bool = Field(default=False)
    # The constructed format this game is played under: a key of
    # web/deck_legality.py's FORMATS table (a bare str here because schemas is
    # the bottom layer and cannot import it; session_store normalizes it). It is
    # what the session id is minted with, so a player joining by that id can read
    # the format off it before they have asked the server anything.
    format: str = Field(default="casual", max_length=40)
    # CR 903.1 / 903.12a: play this game as a Commander variant. None (the
    # default) is an ordinary game; "commander" and "brawl" turn on CR 903 —
    # a command zone, the 40/25/30 starting life, the commander tax, and the
    # two ways a commander returns to the command zone. Each seat's commander
    # comes from its deck's command zone (see *_deck_commander above).
    variant: Literal["commander", "brawl"] | None = Field(default=None)
    # Free-For-All only (mode="free_for_all"): one entry per seat (3 or 4 total).
    # host_*/guest_* fields above are unused in this mode.
    seats: list[SeatConfig] | None = Field(default=None)


class JoinSessionRequest(BaseModel):
    guest_name: str = Field(default="Player 2")
    # The joining player picks their own deck; sent to the host with their name.
    # When unset, a random deck is built for them.
    guest_deck_id: str | None = Field(default=None)
    # Personal (browser-only) deck sent inline; takes precedence over guest_deck_id.
    guest_deck_cards: list[DeckCardEntry] | None = Field(default=None)
    # That deck's sideboard ("outside the game", CR 100.4).
    guest_deck_sideboard: list[DeckCardEntry] | None = Field(default=None)
    # That deck's command zone (CR 903.5a), for a Commander-variant session.
    guest_deck_commander: list[DeckCardEntry] | None = Field(default=None)
    guest_colors: int = Field(default=2, ge=1, le=5)
    # Display name for the lobby roster (see SeatConfig.deck_name).
    guest_deck_name: str | None = Field(default=None)


class DividedTargetRef(BaseModel):
    # One target of a divided spell: a permanent (seat + battlefield index) or a
    # player's face (index omitted). Upper bound is the session's actual player
    # count (up to 4 in Free-For-All), checked in the app.py handler — Pydantic
    # alone can't know which session a request belongs to.
    seat: int = Field(ge=0)
    index: int | None = Field(default=None, ge=0)
    # The same permanent by stable id (see GameActionRequest.target_permanent_id).
    # When set it replaces ``index``; ``seat`` is then advisory, since an id
    # already knows which battlefield it is on.
    id: int | None = Field(default=None, ge=1)


class SearchPickRef(BaseModel):
    # One pick of a two-zone exile search: which zone, and the card's index in
    # that zone's list as the prompt serialized it.
    zone: Literal["library", "graveyard"]
    index: int = Field(ge=0)


class EntryExilePick(BaseModel):
    # One card paying an entry cost ("As this creature enters, exile X creature
    # cards from your graveyard"): its index in the chooser's graveyard as the
    # prompt serialized it, and which of the offered counters that card buys.
    # ``counter`` is absent for a line that offers none - the two travel
    # together because the card and the counter it buys are one decision, made
    # as the permanent enters (CR 614.1c).
    index: int = Field(ge=0)
    counter: str | None = Field(default=None, max_length=16)


class ModeChoice(BaseModel):
    """One chosen mode of a multi-mode spell, with its own targets.

    Every target field is optional because the modes differ: "Target player
    draws a card" names a seat, "Return target nonland permanent" names a
    permanent on one, and "Counter target spell" names an object on the stack.
    """

    index: int = Field(ge=0)
    target_seat: int | None = Field(default=None, ge=0)
    # The permanent that mode chose, on `target_seat`'s battlefield. Named
    # `permanent_index` because that is what the client already sends for a
    # single-permanent cast target, so a mode's target and the spell's are
    # spelled the same on the wire.
    permanent_index: int | None = Field(default=None, ge=0)
    # And by stable id, preferred when the client resolved one (CR 400.7): an
    # index is a slot and a slot is not an identity.
    permanent_id: int | None = Field(default=None, ge=1)
    # Top-first into the serialized stack, exactly as `target_stack_index` is;
    # converted to an engine index by the same helper.
    target_stack_index: int | None = Field(default=None, ge=0)


class GameActionRequest(BaseModel):
    seat: int = Field(ge=0)
    action: ActionKind
    card_name: str | None = None
    permanent_name: str | None = None
    permanent_index: int | None = Field(default=None, ge=0)
    target_permanent_index: int | None = Field(default=None, ge=0)
    # --- stable permanent identity (CR 400.7) -------------------------------
    # The same addresses by ``Permanent.permanent_id`` — the ``id`` the
    # state payload puts on every battlefield card. An index is a *slot*, and a
    # request is written against a board the client last saw one poll ago: if
    # anything left the battlefield in between, every later slot shifted and the
    # index now names a different permanent. These are resolved to indices once,
    # at the top of ``web.actions.do_action``, so nothing downstream has to know
    # which spelling the client used.
    #
    # An id wins over the index beside it, and an id that no longer resolves is
    # an error rather than a silent fallback — falling back to the index would
    # reintroduce exactly the mistake the id exists to prevent.
    permanent_id: int | None = Field(default=None, ge=1)
    target_permanent_id: int | None = Field(default=None, ge=1)
    target_permanent_ids: list[int] | None = Field(default=None)
    source_permanent_id: int | None = Field(default=None, ge=1)
    # Fireball and other "divided among any number of targets" spells: the list
    # of battlefield indices (on target_seat) the damage is split among. Takes
    # precedence over the single permanent_index when present.
    target_permanent_indices: list[int] | None = Field(default=None)
    # Cross-seat divided targets (Fireball / Volcanic Eruption): any mix of
    # permanents and player faces on both sides. Each entry names a seat and,
    # for a permanent, its battlefield index; index None targets that player's
    # face. Takes precedence over target_permanent_indices/target_seat.
    divided_targets: list[DividedTargetRef] | None = Field(default=None)
    target_seat: int | None = Field(default=None, ge=0)
    # Debug "cast for free as opponent" (`debug_cast_free_opponent`): which seat
    # casts the spell. Distinct from target_seat (the spell's target). Optional —
    # the server defaults to the first living opponent of the acting seat.
    caster_seat: int | None = Field(default=None, ge=0)
    # "A source of your choice" (Jade Monolith): the chosen damage source — a
    # battlefield permanent (source_seat + source_permanent_index) or a spell on
    # the stack (source_stack_index, top-first like target_stack_index).
    source_seat: int | None = Field(default=None, ge=0)
    source_permanent_index: int | None = Field(default=None, ge=0)
    source_stack_index: int | None = Field(default=None, ge=0)
    # Which of the acting player's emblems to activate (activate_emblem action).
    emblem_index: int | None = Field(default=None, ge=0)
    x_value: int | None = Field(default=None, ge=0)
    hand_index: int | None = Field(default=None, ge=0)
    # Forgotten Lore: which card in the *caster's* graveyard the chooser
    # picked. Its own field rather than `hand_index`, because the zone is
    # not the answering seat's and not a hand.
    graveyard_index: int | None = Field(default=None, ge=0)
    # "Choose two cards in your hand drawn this turn" (Sylvan Library): the
    # whole answer at once, because the prompt owes a *set* and a card at a
    # time would leave a half-made choice the engine has no state for.
    hand_indices: list[int] | None = None
    mana_color: Literal["W", "U", "B", "R", "G", "C"] | None = None
    # Text-change spells (Magical Hack / Sleight of Mind): the "from" word to
    # replace. `mana_color` carries the "to" word. Both are color symbols (a basic
    # land type is addressed by its color: W=plains, U=island, B=swamp, R=mountain,
    # G=forest).
    old_color: Literal["W", "U", "B", "R", "G"] | None = None
    attacker_indices: list[int] | None = None
    # CR 508.1b: attackers sent at a planeswalker — maps attacker battlefield
    # index to the attacked planeswalker's permanent_id. The attacker's
    # defending player is derived from the walker's controller by the engine.
    attacker_planeswalker_ids: dict[int, int] | None = None
    # Banding (CR 702.22c): attacking bands, each a list of attacker battlefield
    # indices, declared alongside attacker_indices in a declare_attackers action.
    bands: list[list[int]] | None = None
    # Maps a blocker's battlefield index to the attacker it blocks. A value may be
    # a list when one creature blocks several attackers (Two-Headed Giant of Foriys).
    blocker_pairs: dict[int, int | list[int]] | None = None
    attacker_damage: dict[int, dict[int, int]] | None = None
    # Banding (CR 702.22k): how a shared blocker's damage is routed among the band
    # members it blocks — maps blocker battlefield index to the chosen attacker index.
    blocker_damage: dict[int, int] | None = None
    # Banding (CR 702.22j/k): the attacking player's full DIVISION of each band
    # blocker's damage — maps blocker battlefield index to {band member: damage}.
    blocker_damage_split: dict[int, dict[int, int]] | None = None
    # Banding (CR 702.22j): the defending player's damage assignment for attackers
    # blocked by a creature with banding, submitted via an assign_banding_damage action.
    banding_damage: dict[int, dict[int, int]] | None = None
    card_order: list[int] | None = None
    # Which permanent pays a non-mana activation cost ("Sacrifice another
    # creature"). Separate from `target_permanent_id`, which is what the
    # *ability* targets: one activation can have both, and overloading the
    # target field would make a cost eat the creature it was aimed at.
    cost_permanent_id: int | None = None
    cost_permanent_index: int | None = None
    # "Tap two untapped Spirits you control" — several permanents pay one cost,
    # which the singular field above cannot say. By id only: the list is chosen
    # before anything taps and a slot renumbers as soon as one does.
    cost_permanent_ids: list[int] | None = None
    # Which card in hand pays a "Discard a card" activation cost.
    cost_hand_index: int | None = None
    # Which zone `hand_index` addresses when a search may look in more than one
    # ("search your library and/or graveyard"). Absent means the library, so
    # every existing client is unchanged.
    search_zone: str | None = None
    # The two-zone exile search (Chandra, Heart of Fire's −9): any number of
    # picks, each naming its zone and the card's index there. Sent with
    # `search_exile_confirm`; an empty list is the fail-to-find. A counted
    # library search ("up to two basic land cards", Cultivate) sends its whole
    # answer through the same field with `search_library_confirm`.
    search_picks: list["SearchPickRef"] | None = None
    # A counted search's "which found card goes where": one printed-slot index
    # per found card, in the order the prompt listed the cards. Sent with
    # `search_destination_confirm`.
    search_assignments: list[int] | None = None
    # The entry exile (Frankenstein's Monster): every card paying the cost and
    # the counter each one buys, sent with `entry_exile_confirm`. The whole
    # answer at once, because the prompt owes a *set* of exactly X cards and a
    # card at a time would leave a half-paid cost the engine has no state for.
    entry_exile_picks: list["EntryExilePick"] | None = None
    # Casting from outside the hand (engine/cast_permissions.py): which zone
    # the named card is cast or played from. Absent means the hand, so every
    # existing client is unchanged.
    from_zone: Literal["hand", "graveyard", "exile", "command"] | None = None
    # A cost waiver ("cast spells from your hand without paying their mana
    # costs"): true to use it. Absent lets the engine apply it automatically
    # to spells without {X} in their cost (a waived X is 0, CR 107.3b).
    use_free_permission: bool | None = None
    # How many of `card_order`'s trailing entries a scry sends to the bottom
    # (CR 701.22a). Separate from card_order so the permutation stays a
    # permutation and can be validated as one.
    bottom_count: int | None = None
    # Disrupting Scepter discard choice: which hand-card indices to discard, and
    # (Library of Leng) whether to put them on top of the library instead.
    discard_indices: list[int] | None = None
    to_library: bool | None = None
    take_the_damage: bool | None = None
    # CR 903.9: whether the commander goes to the command zone instead of the
    # zone it was headed for. Its own field rather than reusing `accept`,
    # because the answer is a destination and not a yes to an offer of one.
    to_command_zone: bool | None = None
    # Balance: the indices the player chooses to sacrifice/discard — land and
    # creature indices into their battlefield, plus hand-card indices to discard.
    land_indices: list[int] | None = None
    creature_indices: list[int] | None = None
    # Forced sacrifice (Lich): the battlefield indices the player chooses to
    # sacrifice, sent with `sacrifice_confirm`.
    sacrifice_indices: list[int] | None = None
    # CR 616.1e: which of the effects contending over one event applies first,
    # as an index into the prompt's `options`. Sent with `effect_order_confirm`.
    option_index: int | None = None
    # Raging River: map of battlefield/attacker index → "left"/"right" pile label,
    # sent with assign_defender_piles / assign_attacker_piles.
    piles: dict[int, str] | None = None
    # Camouflage: map of the defender's battlefield index → 0-based pile number(s)
    # (a list only for a creature that can block additional creatures), sent with
    # assign_camouflage_piles. Creatures left out go into no pile.
    camouflage_piles: dict[int, int | list[int]] | None = None
    # Backdraft: the seat chosen by "Choose a player who cast one or more
    # sorcery spells this turn", sent with `player_choice_confirm`. Its own
    # field rather than `target_seat`: a chosen player is not a target
    # (CR 601.2c declares none), and reusing the target field would let a
    # picker built for targets answer a prompt that has none.
    chosen_seat: int | None = Field(default=None, ge=0)
    # Backdraft: which of the offered spells "one of those sorcery spells" names,
    # as a position in the turn's cast ledger, sent with `cast_choice_confirm`.
    cast_index: int | None = Field(default=None, ge=0)
    # Shapeshifter: the number its controller chose, sent with
    # `number_choice_confirm`. Bounded by the card's printed range, which the
    # engine re-checks -- an out-of-range answer is refused rather than clamped.
    number: int | None = Field(default=None, ge=0)
    # Phantasmal Terrain: the basic land type the controller chose for the
    # enchanted land, sent with `land_type_confirm`.
    land_type: Literal["plains", "island", "swamp", "mountain", "forest"] | None = None
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
    # "Choose one **or more** —" (Sublime Epiphany): every mode the caster
    # picked, each with the targets *that mode* chose (CR 601.2c). Its own field
    # rather than a list-valued `mode_index`, for the reason the cost fields are
    # their own: a mode's target and the spell's target are different questions,
    # and one field answering both would let a mode eat the other's choice.
    # The engine sorts them into printed order (CR 608.2c), so the order they
    # arrive in is the order the player clicked and means nothing.
    mode_choices: list[ModeChoice] | None = None
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
    seat: int | None = Field(default=None, ge=0)


class RematchRequest(BaseModel):
    seat: int = Field(ge=0)


class StartGameRequest(BaseModel):
    seat: int = Field(ge=0)


class RejoinSessionRequest(BaseModel):
    # The seat to take back in a game already in progress. Nothing else: the
    # seat keeps its name, deck, and board — rejoining rebuilds nothing.
    seat: int = Field(ge=0)


class RandomDeckRequest(BaseModel):
    colors: int = Field(ge=1, le=5)
    seed: int = 1337


class DeckSaveRequest(BaseModel):
    name: str = Field(default="Untitled Deck", max_length=100)
    description: str = Field(default="", max_length=2000)
    format: str = Field(default="casual", max_length=40)
    cards: list[DeckCardEntry] = Field(default_factory=list)
    # The deck's sideboard ("outside the game", CR 100.4) — the pool Ring of
    # Ma'rûf draws from.
    sideboard: list[DeckCardEntry] = Field(default_factory=list)
    # The deck's command zone (CR 903.5a) — only meaningful for Commander.
    commander: list[DeckCardEntry] = Field(default_factory=list)


class DeckImportRequest(BaseModel):
    text: str | None = None
    url: str | None = None


class VerificationRequest(BaseModel):
    card_name: str = Field(min_length=1)
    status: Literal["pass", "fail"]
    reason: str | None = None
