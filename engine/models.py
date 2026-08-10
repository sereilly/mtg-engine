from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import Any

from . import shields as _shields

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


# CR 613 layer 3 — text-changing effects.
#
# ``color_word_remap`` stores symbol -> symbol ({"B": "R"}); rewriting the rules
# text needs the words. The result is cached per (card, remap) because
# ``effective_card`` is read on nearly every rules query and building a
# CardDefinition each time would be a per-call allocation on a hot path — and
# because ``compile_card_oracle``'s cache is keyed on the text, so a stable
# object keeps a remapped card compiling exactly once.
_SYMBOL_TO_COLOR_WORD: dict[str, str] = {
    "W": "white", "U": "blue", "B": "black", "R": "red", "G": "green",
}
_REMAPPED_CARDS: dict[tuple, "CardDefinition"] = {}


def _with_granted_abilities(
    card: "CardDefinition", granted: tuple[str, ...]
) -> "CardDefinition":
    """*card* with abilities a static grants appended to its rules text."""
    key = (id(card), granted)
    cached = _GRANTED_CARDS.get(key)
    if cached is None:
        text = chr(10).join(filter(None, (card.oracle_text, *granted)))
        cached = dataclasses.replace(card, oracle_text=text)
        _GRANTED_CARDS[key] = cached
    return cached


_GRANTED_CARDS: dict[tuple, "CardDefinition"] = {}


def _with_color_words_remapped(card: "CardDefinition", remap: dict) -> "CardDefinition":
    """*card* with its colour words replaced per *remap* (CR 612.1)."""
    key = (id(card), tuple(sorted(remap.items())))
    cached = _REMAPPED_CARDS.get(key)
    if cached is not None:
        return cached

    pairs = [
        (_SYMBOL_TO_COLOR_WORD[old], _SYMBOL_TO_COLOR_WORD[new])
        for old, new in remap.items()
        if old in _SYMBOL_TO_COLOR_WORD and new in _SYMBOL_TO_COLOR_WORD
    ]
    text = card.oracle_text
    if pairs:
        # One pass over the text with a single alternation, so a remap of
        # black -> red alongside red -> black swaps rather than collapsing.
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(old) for old, _ in pairs) + r")\b",
            re.IGNORECASE,
        )
        replacements = {old: new for old, new in pairs}

        def _sub(match: "re.Match") -> str:
            word = match.group(0)
            replacement = replacements[word.lower()]
            return replacement.capitalize() if word[:1].isupper() else replacement

        text = pattern.sub(_sub, text)

    remapped = dataclasses.replace(card, oracle_text=text)
    _REMAPPED_CARDS[key] = remapped
    return remapped


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
    # CR 615 prevention shields. These two are *views* over
    # ``engine/shields.py``'s collection (installed below the class), kept under
    # their old names because the web payload and the UI read them; the state
    # they report is one generic list, not a field per card.
    damage_prevention_pool: int = 0
    damage_prevention_source: str | None = None

    @property
    def prevention_shields(self) -> list["_shields.Shield"]:
        """The CR 615 shields protecting this permanent (``engine/shields.py``)."""
        return _shields.shields_on(self)

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
        serialization must read this, not ``card``.

        CR 613 layer 3 is applied here: a text-changing effect (Sleight of Mind
        replacing a colour word) rewrites the rules text *before* anything reads
        it. Applying it at each reader instead is how Magnetic Mountain went on
        blocking blue creatures and Gloom went on taxing white spells after
        their text said red — the remap reached only the readers that had been
        taught about it.
        """
        base = self.metadata.get("copied_card") or self.card
        remap = self.metadata.get("color_word_remap")
        if remap:
            base = _with_color_words_remapped(base, remap)

        # An ability granted by a board-wide static (Energy Flux) is appended to
        # the effective text, so the compiler produces it like any printed
        # ability and the upkeep step, the UI and the coverage scripts all see
        # it without knowing a static granted it.
        from .global_statics import global_statics_applying_to

        granted = [
            static.grants_ability
            for static in global_statics_applying_to(self)
            if static.grants_ability
        ]
        if granted:
            base = _with_granted_abilities(base, tuple(granted))
        return base

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


# CR 615's shields protect "a player or a permanent" alike, so a permanent gets
# the same two views a player does. Installed after the dataclass so the
# generated ``__init__`` keeps accepting them by name (the AI simulator's clone
# and several tests construct a recipient with a pool already on it) while the
# value itself lives only in the shield collection.
Permanent.damage_prevention_pool = _shields.pool_view(
    """Points held by this permanent's "prevent the next N damage" shields
    (CR 615.7). A view over ``engine/shields.py``; assigning replaces them."""
)
Permanent.damage_prevention_source = _shields.badge_view(
    """Name of the card that granted this permanent's newest live shield, for
    the UI's shield badge. Derived, so a spent shield takes its badge with it."""
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
    # CR 615 prevention shields. These four, plus ``reverse_damage_sources``
    # below and the read-only ``damage_prevention_color``, are *views* over
    # ``engine/shields.py``'s one generic collection (installed below the
    # class), not stored state: the names survive because the web payload, the
    # AI simulator and the existing tests read them, but a new shield needs no
    # new field here.
    damage_prevention_pool: int = 0
    damage_prevention_source: str | None = None
    color_prevention_shields: list[str] = field(default_factory=list)
    combat_damage_cap_one_charges: int = 0
    forcefield_capped_sources: list = field(default_factory=list)
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
    # The chosen-source half of the Reverse Damage shields above; a view over the
    # same collection (see the prevention block near the top of this class).
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
    # The artifact-sourced share of it (Reverse Polarity). Counted as the
    # damage happens, because the source may be gone by the time a spell
    # asks — the same reason combat triggers capture their victims.
    artifact_damage_taken_this_turn: int = 0
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

    @property
    def prevention_shields(self) -> list["_shields.Shield"]:
        """The CR 615 shields protecting this player (``engine/shields.py``).
        The state behind every prevention view above."""
        return _shields.shields_on(self)


# CR 615's shields, under the names the rest of the codebase already reads.
# Each is derived from ``engine/shields.py``'s one collection on every access, so
# the view and the state cannot disagree; assigning rebuilds the shields the name
# stood for, which is how the cleanup sweep and the tests that arm a shield
# directly keep working. Adding a *new* kind of shield adds nothing here.
PlayerState.damage_prevention_pool = _shields.pool_view(
    """Points held by this player's "prevent the next N damage" shields
    (CR 615.7). Several such effects are several shields; this is their total."""
)
PlayerState.damage_prevention_source = _shields.badge_view(
    """Name of the card that granted this player's newest live shield, shown as a
    hover preview on the life pill's shield badge."""
)
PlayerState.damage_prevention_color = _shields.color_badge_view(
    """Colour of the newest live Circle of Protection shield, for UI display.
    Read-only: the colour is what the shield matches its source against
    (CR 615.9), so there is nothing to set that isn't a shield."""
)
PlayerState.color_prevention_shields = _shields.list_view(
    _shields.PREVENT_FROM_COLOR,
    "color",
    _shields.make_color_shield,
    """Circle of Protection shields: one colour symbol per live shield. Each
    prevents the entire next damage event from a source of that colour this turn,
    then is consumed (CR 615.9)."""
)
PlayerState.combat_damage_cap_one_charges = _shields.charge_view(
    _shields.PREVENT_ALL_BUT,
    _shields.make_capped_charge,
    """Forcefield shields armed without a chosen attacker (AI / headless
    activations): the next damage event from any source is capped to 1."""
)
PlayerState.forcefield_capped_sources = _shields.list_view(
    _shields.PREVENT_ALL_BUT,
    "source",
    _shields.make_capped_source,
    """Forcefield: "The next time an unblocked creature of your choice would deal
    combat damage to you this turn, prevent all but 1 of that damage." One entry
    per chosen attacker; expires at end of combat."""
)
PlayerState.reverse_damage_charges = _shields.charge_view(
    _shields.PREVENT_AND_GAIN_LIFE,
    _shields.make_life_gain_charge,
    """Reverse Damage shields armed without a chosen source (AI / headless
    casts): the next damage event from any source is prevented and gained as
    life."""
)
PlayerState.reverse_damage_sources = _shields.list_view(
    _shields.PREVENT_AND_GAIN_LIFE,
    "source",
    _shields.make_life_gain_source,
    """Reverse Damage: "The next time a source of your choice would deal damage
    to you this turn, prevent that damage. You gain life equal to the damage
    prevented this way." One entry per chosen source (CR 615.5, 615.8)."""
)
