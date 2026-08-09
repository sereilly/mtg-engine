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


def _printed_basic_types(type_line: str) -> frozenset[str]:
    """Basic land types printed on a type line, used to tell whether a
    layer-4 effect has actually replaced them."""
    lowered = type_line.lower()
    return frozenset(land_type for land_type in _LAND_TYPE_MANA if land_type in lowered)


@dataclass(frozen=True)
class CardFace:
    """One face of a multi-face card (split, flip, transform, adventure, …).

    For every non-``normal`` layout the top-level ``mana_cost``/``oracle_text``
    are empty and the real characteristics live per face, so a loader that only
    reads the top level would silently produce a blank vanilla.
    """
    name: str
    mana_cost: str = ""
    type_line: str = ""
    oracle_text: str = ""
    power: str | None = None
    toughness: str | None = None


# Layouts whose characteristics live entirely at the top level. Anything else
# needs face-aware handling before it can be compiled — see LAYOUT_SUPPORTED.
SINGLE_FACE_LAYOUTS = frozenset({"normal", "leveler", "class", "saga", "case", "planar", "scheme", "vanguard"})


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
    # Printed characteristics, kept as strings so "*", "1+*" and "-1" survive
    # intact — coercing them to int is how a Nightmare becomes a 0/0 and dies to
    # state-based actions. Use base_power/base_toughness for a numeric view.
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None
    layout: str = "normal"
    faces: tuple[CardFace, ...] = ()
    # Scryfall's stable per-card (not per-printing) identity. The right key for
    # reprint dedupe: names collide across languages and templating revisions.
    oracle_id: str = ""
    set_code: str = ""
    collector_number: str = ""
    # Set codes this card appears in, in load (printing) order. ``printings[0]``
    # is its original printing — what "cards originally printed in X" effects
    # such as City in a Bottle need. Reading the loaded-first set code instead
    # breaks as soon as a reprint set is added.
    printings: tuple[str, ...] = ()

    @property
    def primary_type(self) -> str:
        lowered = self.type_line.lower()
        for known in ("land", "creature", "artifact", "enchantment", "instant", "sorcery"):
            if known in lowered:
                return known
        return self.type_line.split(" ")[0].strip().lower()

    def _printed_stat(self, typed: str | None, raw_key: str) -> str | None:
        """Printed P/T, preferring the typed field.

        The ``raw`` fallback is a migration bridge: test fixtures build
        ``CardDefinition`` directly with a raw dict and no typed fields. It goes
        away when those move to the typed constructor.
        """
        if typed is not None:
            return typed
        if isinstance(self.raw, dict) and raw_key in self.raw:
            return str(self.raw[raw_key])
        return None

    @property
    def printed_power(self) -> str | None:
        return self._printed_stat(self.power, "power")

    @property
    def printed_toughness(self) -> str | None:
        return self._printed_stat(self.toughness, "toughness")

    @staticmethod
    def _as_int(value: str | None) -> int | None:
        """Numeric view of a printed stat, or None when it is variable ("*",
        "1+*") or absent. None means "ask the characteristic-defining-ability
        registry", never "zero"."""
        if value is None:
            return None
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
        return None

    @property
    def base_power(self) -> int | None:
        return self._as_int(self.printed_power)

    @property
    def base_toughness(self) -> int | None:
        return self._as_int(self.printed_toughness)

    @property
    def has_variable_pt(self) -> bool:
        """True when P/T is defined by a characteristic-defining ability rather
        than printed digits (Nightmare, Keldon Warlord, Rock Hydra)."""
        return (
            self.primary_type == "creature"
            and self.printed_power is not None
            and self.base_power is None
        )

    @property
    def original_printing(self) -> str:
        """Set code of this card's earliest loaded printing."""
        return self.printings[0] if self.printings else self.set_code


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
        """Printed power/toughness as a number, or 0 when it is variable.

        A variable stat ("*", "1+*") is supplied by the characteristic-defining
        registry (``mixins.permanent_state.DYNAMIC_PT``) writing an
        ``absolute_power``/``absolute_toughness`` override, which the callers of
        this method consult first — so returning 0 here is the base case for a
        CDA, not a claim that the creature is 0/0.
        """
        value = self.card.base_power if key == "power" else self.card.base_toughness
        return value if value is not None else 0

    @property
    def effective_produced_mana(self) -> tuple[str, ...]:
        """Mana this permanent produces, honoring a land-type override.

        "Enchanted land is a Swamp" (Evil Presence) / Phantasmal Terrain replace
        the land's types, so it produces only the override type's mana and loses
        its printed mana ability (CR 305.7).
        """
        # Only when layer 4 has actually changed the land's types: a land whose
        # types were replaced produces that type's mana instead of its printed
        # ability. An unchanged land keeps its printed production, which matters
        # for duals — deriving mana from their types would reorder the symbols
        # that callers read positionally.
        current = self.basic_land_types
        printed = _printed_basic_types(self.card.type_line)
        if current and set(current) != printed:
            return tuple(_LAND_TYPE_MANA[land_type] for land_type in current)
        # A copy (Copy Artifact of a Mox / Sol Ring) produces the copied
        # card's mana, so read the effective card rather than the copier's own.
        return self.effective_card.produced_mana

    @property
    def effective_card(self) -> "CardDefinition":
        """The card whose printed characteristics this permanent currently has.

        A copy (Clone / Vesuvan Doppelganger) keeps its own ``card`` (so the
        copier's identity, upkeep re-copy prompt, and name-keyed flows still
        work) but takes the copied creature's copiable values — including its
        activated and triggered abilities (CR 707.2). Ability compilation and
        serialization must read this, not ``card``."""
        return self.metadata.get("copied_card") or self.card

    def has_type(self, card_type: str) -> bool:
        """Whether this permanent currently has the given card type or subtype.

        Computed through CR 613 layer 4, so animation and basic-land-type
        changes are included alongside the printed line. A Copy Artifact copying
        a Mox is an "Artifact Enchantment" and counts as both;
        ``primary_type`` collapses multi-type lines to one type, so type checks
        on permanents should use this instead.
        """
        from .layer_bridge import computed_types

        wanted = card_type.lower()
        card_types, subtypes = computed_types(self)
        return wanted in card_types or wanted in subtypes

    @property
    def is_creature(self) -> bool:
        """Whether this permanent is currently a creature.

        Printed as one, or animated into one (Kormus Bell's Swamps, Living
        Lands' Forests, Jade Statue) — a layer-4 type-changing effect, not a
        special case. Targeting, combat, and creature-only effects must use
        this rather than the printed ``card.primary_type``.
        """
        from .layer_bridge import computed_types

        return "creature" in computed_types(self)[0]

    @property
    def basic_land_types(self) -> tuple[str, ...]:
        """The basic land types this permanent currently has, after layer 4.

        One place to ask "is this a Swamp now?" — printed, or made one by Evil
        Presence / Phantasmal Terrain / Blood Moon. Several call sites used to
        re-derive this by checking the printed type line and the override
        separately, which meant each had to remember both.
        """
        from .layer_bridge import computed_types

        subtypes = computed_types(self)[1]
        return tuple(land_type for land_type in _LAND_TYPE_MANA if land_type in subtypes)

    @property
    def basic_land_mana(self) -> tuple[str, ...]:
        """Mana symbols implied by the basic land types it currently has."""
        return tuple(_LAND_TYPE_MANA[land_type] for land_type in self.basic_land_types)

    @property
    def effective_colors(self) -> set[str]:
        """The colours this permanent currently is, after layer 5 — printed,
        or replaced by a lace or a copy effect."""
        from .layer_bridge import computed_colors

        return computed_colors(self)

    def has_keyword(self, keyword: str) -> bool:
        """Whether this permanent currently has a keyword ability.

        Printed keywords plus every grant and removal, resolved through CR 613
        layer 6 — so a grant after a removal restores the ability, per 613.9.
        Reading a ``gains_<keyword>`` metadata flag instead misses anything
        granted by another route and gets the ordering wrong.

        ``Game._has_keyword`` adds a fallback for keywords that only appear in a
        card's oracle text; prefer that from inside the engine.
        """
        from .layer_bridge import computed_abilities

        return keyword.lower() in computed_abilities(self)

    @property
    def effective_power(self) -> int:
        """Power after every continuous effect, computed through CR 613's
        layers (``engine/continuous.py`` via ``engine/layer_bridge.py``).

        The sublayer order — 7a characteristic-defining, 7b set, 7c modify,
        7d switch — is enforced by the layer system rather than by the shape of
        this method. That matters because the order is a rule, not a coding
        convention: written by hand it was correct only as long as nobody added
        a channel in the wrong place.
        """
        from .layer_bridge import computed_pt

        return computed_pt(self)[0]

    @property
    def effective_toughness(self) -> int:
        """Toughness after every continuous effect. See effective_power."""
        from .layer_bridge import computed_pt

        return computed_pt(self)[1]


@dataclass
class PlayerState:
    name: str
    life: int = 20
    hand: list[CardDefinition] = field(default_factory=list)
    library: list[CardDefinition] = field(default_factory=list)
    battlefield: list[Permanent] = field(default_factory=list)
    graveyard: list[CardDefinition] = field(default_factory=list)
    exile: list[CardDefinition] = field(default_factory=list)
    # Cards owned from outside the game (CR 100.4 / 400.11): the player's
    # sideboard. Not a game zone — nothing moves here during play; effects such
    # as Ring of Ma'rûf move a card *from* here into hand.
    sideboard: list[CardDefinition] = field(default_factory=list)
    # The ante zone (CR 407). One shared zone in paper, modeled per-player here
    # because every ante effect in the pool acts on "cards you own in the ante"
    # — Jeweled Bird antes itself and clears the rest, Darkpact swaps one out.
    # Cards land here from Contract from Below / Demonic Attorney / Jeweled Bird.
    ante: list[CardDefinition] = field(default_factory=list)
    mana_pool: dict[str, int] = field(
        default_factory=lambda: {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    )
    # Metamorphosis: "Spend this mana only to cast creature spells." Mana held
    # here joins the pool only when paying for a creature spell (spent before
    # unrestricted mana) and empties whenever the regular pool does.
    creature_only_mana: dict[str, int] = field(default_factory=dict)
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
    # This is the generic fallback used when no specific source was chosen (AI /
    # headless casts); a human pick is recorded in reverse_damage_sources instead.
    reverse_damage_charges: int = 0
    # Eye for an Eye: one-shot "the next damage dealt to you this turn is also
    # dealt to its source's controller" charges. Consumed in
    # _deal_damage_to_player; expire at cleanup. This is the generic fallback
    # used when no specific source was chosen (AI / headless casts); a human pick
    # is recorded in mirror_damage_sources instead.
    mirror_damage_charges: int = 0
    # Eye for an Eye with a chosen "source of your choice": the specific Permanent
    # or spell (a CardDefinition) the caster picked. Only damage from a matching
    # source is mirrored back to that source's controller, then the entry is
    # consumed. Cleared at cleanup.
    mirror_damage_sources: list = field(default_factory=list)
    # Reverse Damage with a chosen "source of your choice": the specific Permanent
    # or spell (a CardDefinition) the caster picked. Only damage from a matching
    # source is prevented and converted to life, then the entry is consumed.
    # Cleared at cleanup.
    reverse_damage_sources: list = field(default_factory=list)
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
    # Cards drawn this turn, in draw order — the last entry is "the last card you
    # drew this turn" (Jandor's Ring's discard cost). Every path that draws must
    # record here, so effects that replace a draw but still put a card in hand
    # (Aladdin's Lamp) append too. Cleared in begin_turn_bookkeeping.
    cards_drawn_this_turn: list = field(default_factory=list)

    def draw(self, count: int = 1) -> int:
        actual = 0
        for _ in range(count):
            if not self.library:
                # 704.5b: track attempt to draw from empty library
                if count > actual:
                    self.drew_from_empty = True
                break
            card = self.library.pop(0)
            self.hand.append(card)
            self.cards_drawn_this_turn.append(card)
            actual += 1
        return actual

    def last_card_drawn_this_turn(self):
        """The most recently drawn card that is still in hand, or None. A card
        drawn and then played/discarded is no longer available to pay a "discard
        the last card you drew this turn" cost (CR 118.3: you can only pay a cost
        you're able to pay)."""
        for card in reversed(self.cards_drawn_this_turn):
            if any(c is card for c in self.hand):
                return card
        return None
