from __future__ import annotations

import dataclasses
import itertools
from dataclasses import dataclass, field
from typing import Any

from . import shields as _shields
# Safe at module level: copies and text_changes import only the layer system's
# timestamp counter, nothing from here. effective_card is read on nearly every
# rules query, so this is not a function-local import.
from .copies import copiable_card, copied_name
from .text_changes import apply_text_changes, has_text_changes, text_changes

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
    def is_legendary(self) -> bool:
        """CR 205.4a — the supertype, read off the printed type line.

        Here rather than at the one caller because it is a characteristic of the
        card: the compiler asks it to know whether the card's shortened name is
        a self-reference (``engine/self_reference.py``), and a token or a test
        fixture with no supertype answers no without anyone remembering to.
        """
        return "legendary" in self.type_line.lower()

    @property
    def primary_type(self) -> str:
        lowered = self.type_line.lower()
        for known in ("land", "creature", "artifact", "enchantment", "planeswalker", "instant", "sorcery"):
            if known in lowered:
                return known
        return self.type_line.split(" ")[0].strip().lower()

    @property
    def has_flash(self) -> bool:
        """CR 702.8b: this card may be cast any time its owner could cast an
        instant. Read from the ingested ``keywords`` field — the same source
        the layer seed reads printed abilities from. A *granted* flash ("as
        though it had flash") is a permission about a card outside the
        battlefield, so it will arrive as its own seam on ``Game``, not here.
        """
        return any(keyword.lower() == "flash" for keyword in self.keywords)

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


def _without_ability_lines(
    card: "CardDefinition", removed: tuple[str, ...]
) -> "CardDefinition":
    """*card* with the printed lines an effect has taken away struck out.

    The keyword list is filtered alongside the text: "Enchant creature" is a
    keyword ability (CR 702.5), so a card that keeps ``Enchant`` in
    ``keywords`` after losing the line still answers yes to a keyword read,
    which is the two-representations-one-reader bug this engine keeps finding.
    """
    from .keywords import normalized_ability_line

    key = (id(card), removed)
    cached = _REMOVED_CARDS.get(key)
    if cached is None:
        kept = [
            line for line in (card.oracle_text or "").split(chr(10))
            if normalized_ability_line(line) not in removed
        ]
        gone = {
            normalized_ability_line(line)
            for line in (card.oracle_text or "").split(chr(10))
            if normalized_ability_line(line) in removed
        }
        keywords = tuple(
            word for word in card.keywords
            if not any(phrase.startswith(word.lower()) for phrase in gone)
        )
        cached = dataclasses.replace(
            card, oracle_text=chr(10).join(kept), keywords=keywords
        )
        _REMOVED_CARDS[key] = cached
    return cached


_REMOVED_CARDS: dict[tuple, "CardDefinition"] = {}


def _without_keyword_parts(
    card: "CardDefinition", removed: tuple[str, ...]
) -> "CardDefinition":
    """*card* with the named keywords struck out of its keyword lines.

    The counterpart of :func:`_without_ability_lines` for a **line-derived**
    keyword (``keywords.LINE_DERIVED_KEYWORDS``), which cannot be taken away by
    either of the other two channels: layer 6's word set is not where the
    compiler looks for a flanking trigger, and matching the whole printed line
    would have to match its reminder text and would take a second keyword
    printed beside it ("Shroud, flanking").

    So a keyword *line* is decomposed the way the compiler decomposes one —
    ``normalize_creature_line`` strips the reminder, commas separate the parts
    — and only the named parts go. A line with nothing left goes entirely; a
    line the removal does not touch is left byte for byte, so a card nothing
    was removed from is the card it was.

    Only a line **every** part of which is a keyword is rewritten. A rules
    sentence that happens to contain the word ("Whenever a creature without
    flanking blocks…") is not a keyword line, and rewriting it by comma would
    be rewriting prose.
    """
    from .keywords import keyword_ability_name
    from .oracle import _is_supported_keyword_line, normalize_creature_line

    key = (id(card), removed)
    cached = _REMOVED_KEYWORD_CARDS.get(key)
    if cached is not None:
        return cached
    lines: list[str] = []
    changed = False
    for line in (card.oracle_text or "").split(chr(10)):
        if not _is_supported_keyword_line(line):
            lines.append(line)
            continue
        parts = [
            part.strip()
            for part in normalize_creature_line(line).split(",")
            if part.strip()
        ]
        kept = [
            part for part in parts if keyword_ability_name(part) not in removed
        ]
        if len(kept) == len(parts):
            lines.append(line)
            continue
        changed = True
        if kept:
            lines.append(", ".join(part[:1].upper() + part[1:] for part in kept))
    if not changed:
        _REMOVED_KEYWORD_CARDS[key] = card
        return card
    keywords = tuple(
        word for word in card.keywords
        if keyword_ability_name(word.lower()) not in removed
    )
    cached = dataclasses.replace(
        card, oracle_text=chr(10).join(lines), keywords=keywords
    )
    _REMOVED_KEYWORD_CARDS[key] = cached
    return cached


_REMOVED_KEYWORD_CARDS: dict[tuple, "CardDefinition"] = {}


# CR 400.7: a permanent that leaves the battlefield and comes back is a *new
# object*. A stable identity therefore only has to be unique and monotonic —
# the same requirement CR 613.7's timestamps have — so a monotonic counter is
# enough, and this is deliberately the same idiom as
# ``engine/continuous.py``'s ``next_timestamp``.
#
# Module-level rather than per-game because a ``Permanent`` is created in
# places that have no ``Game`` to ask: the AI simulator's detached clones, the
# Debug Menu's raw-state injection, and several hundred test rigs that build a
# board by appending to ``player.battlefield``. Making the id a property of
# *construction* means every permanent in the process is addressable without a
# single one of those call sites having to opt in.
#
# Determinism is unaffected: the counter consumes no randomness and imposes no
# iteration order, it only advances when a permanent is created — and that
# sequence is already seed-reproducible.
_PERMANENT_IDS = itertools.count(1)


def next_permanent_id() -> int:
    """The next stable permanent identity (CR 400.7: a new object, a new id)."""
    return next(_PERMANENT_IDS)


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
    # Stable identity, the replacement for addressing a permanent by its *slot*
    # on a battlefield list. Unique across every seat (one counter, not one per
    # player) and stable for as long as this object is on the battlefield, where
    # an index is stable only until something earlier in the list leaves.
    #
    # Stamped at construction and **re-stamped as the permanent enters the
    # battlefield** (``Game._put_permanent_onto_battlefield``): CR 400.7 makes a
    # returning permanent a new object, and re-stamping is what makes that true
    # for the one path that puts the *same* Permanent object back (Oubliette's
    # scoped phase-out). Last field on purpose — tests construct ``Permanent``
    # positionally.
    #
    # ``compare=False``: :class:`Permanent` equality is value equality, and
    # several call sites still depend on that (the AI simulator compares
    # detached clones). Folding identity into ``__eq__`` would be a *separate*
    # behavioural change; this field is purely additive.
    permanent_id: int = field(default_factory=next_permanent_id, compare=False)

    @property
    def prevention_shields(self) -> list["_shields.Shield"]:
        """The CR 615 shields protecting this permanent (``engine/shields.py``)."""
        return _shields.shields_on(self)

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
            return self._swapped_mana(
                tuple(_LAND_TYPE_MANA[land_type] for land_type in current)
            )
        # A copy (Copy Artifact of a Mox / Sol Ring) produces the copied
        # card's mana, so read the effective card rather than the copier's own.
        return self._swapped_mana(self.effective_card.produced_mana)

    def _swapped_mana(self, symbols: tuple[str, ...]) -> tuple[str, ...]:
        """*symbols* after every "produces X instead of Y" effect on this land.

        "If target Plains is tapped for mana, it produces colorless mana instead
        of white mana." (Quarum Trench Gnomes.) A CR 611.2 continuous effect with
        no duration, recorded on the permanent by the handler and applied here
        because this property is the one place the engine asks what a land makes.

        Applied in the order the effects were created (CR 613.7), so a second
        swap reads the first one's answer — and a symbol the land never produced
        is left alone, which is what makes the same sentence about a Swamp
        harmless on a Plains.
        """
        swaps = self.metadata.get("produced_mana_swaps")
        if not swaps:
            return symbols
        current = list(symbols)
        for replaced, produced in swaps:
            current = [produced if sym == replaced else sym for sym in current]
        return tuple(current)

    def produced_symbol_for(self, requested: str | None) -> str | None:
        """The symbol this land actually makes when a seat asks for *requested*.

        A colour can be asked for and no longer produced. A seat names the
        symbol the land **prints** — that is what its picker offers and what a
        payment plan was built against — and the swaps decide what comes out,
        so the request is mapped through the same swaps ``_swapped_mana``
        applied rather than discarded.

        The alternative, falling back to the first entry of
        ``effective_produced_mana``, is right only on a land that makes one
        symbol. Quarum Trench Gnomes on a Tundra swaps {W} for {C} and leaves
        ``("U", "C")``; asking for white then paid **{U}** — the other colour,
        not the colourless the Gnomes grant — because the printed order happens
        to put the island first. Returns None when the request maps to nothing
        this land makes, which is the caller's cue to pick a default.
        """
        if not requested:
            return None
        produced = self.effective_produced_mana
        if requested in produced:
            return requested
        swapped = self._swapped_mana((requested,))[0]
        return swapped if swapped in produced else None

    @property
    def copied_from(self) -> str | None:
        """The name of the object this permanent is currently a copy of.

        Derived from the layer-1 contribution (``engine/copies.py``), not
        stamped beside it: a permanent that is not a copy has nothing to report,
        and one that re-copies reports the newest copy without anything having
        to overwrite an old answer.
        """
        return copied_name(self)

    @property
    def effective_card(self) -> "CardDefinition":
        """The card whose printed characteristics this permanent currently has.

        **Layers 1 and 3 of CR 613, in that order**, over the printed card.

        Layer 1 (``engine/copies.py``): a copy (Clone / Vesuvan Doppelganger /
        Copy Artifact) keeps its own ``card`` — so the copier's identity and its
        zone-change reversion still work — while its *copiable values* are the
        copied object's (CR 707.2), including its activated and triggered
        abilities. Ability compilation and serialization must read this, not
        ``card``.

        Layer 3 (``engine/text_changes.py``): a text-changing effect (Sleight of
        Mind replacing a colour word, Magical Hack replacing a basic land type)
        rewrites the rules text, the type line and the keywords parsed off them
        *before* anything reads any of it. Applying it at each reader instead is
        how Magnetic Mountain went on blocking blue creatures and Gloom went on
        taxing white spells after their text said red — the remap reached only
        the readers that had been taught about it.

        The order is the rule and not a convenience: layer 1 runs first, so a
        text change on the *copy* rewrites the copied text, while a text change
        on the *source* is not copied at all (CR 707.2's last sentence). Two
        text changes do not commute, so that fold is oldest-first rather than a
        merged substitution table.
        """
        base = copiable_card(self)
        if has_text_changes(self):
            base = apply_text_changes(base, text_changes(self))

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
        # …and an ability granted to *this permanent alone* (Rapid Fire's
        # rampage), on the same channel and for the same reason: CR 702.23a
        # defines rampage as a triggered ability, so what a grant of it grants
        # is the line, and the compiler is what turns a line into an ability.
        # Appended after the board-wide ones so the fold order matches the order
        # the two were recorded in — a static applies from the board, a grant
        # from the moment it resolved.
        from .keywords import granted_ability_lines, removed_ability_lines

        granted.extend(granted_ability_lines(self))
        # …and an ability an **Aura attached to this permanent** grants
        # ('Enchanted land has "{T}: Counter target spell …"', Equinox). Derived
        # from the attachments on every read rather than recorded when the Aura
        # arrived, so detaching it takes the ability away with nothing to undo
        # (CR 611.3b). Read off the Aura's *effective* card, because a text
        # change rewrites what the Aura says before anything reads it.
        from .auras import (aura_granted_ability_lines,
                            aura_granted_line_derived_lines, auras_attached_to)

        for aura in auras_attached_to(self):
            granted.extend(aura_granted_ability_lines(aura.effective_card.oracle_text))
            # …and the keyword grants layer 6's *word* set cannot carry —
            # rampage and flanking, whose ability the CR defines rather than
            # describes, so what a grant of one grants is the printed line.
            # Same channel, same fold, and the same reason the quoted ones are
            # derived here rather than recorded at attach time.
            granted.extend(
                aura_granted_line_derived_lines(aura.effective_card.oracle_text)
            )
        # …and layer 6's other half (CR 613.1f): an ability an effect has taken
        # away. Dropped *before* the grants are appended, so a card that loses a
        # line and is then granted one keeps the granted one — and so a grant of
        # the same words is not silently removed with the printed line.
        removed = removed_ability_lines(self)
        if removed:
            base = _without_ability_lines(base, removed)
        if granted:
            base = _with_granted_abilities(base, tuple(granted))
        # …and layer 6's third removal channel, a **line-derived** keyword
        # (Barbed Foliage's "it loses flanking until end of turn"). Applied
        # after the grants rather than with the removal above, and that order is
        # the card: Agility grants flanking as a printed line, so a removal
        # folded in first would strike a line that is not there yet and leave
        # the granted one standing.
        from .keywords import removed_ability_keywords

        stripped = removed_ability_keywords(self)
        if stripped:
            base = _without_keyword_parts(base, tuple(sorted(set(stripped))))
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

    def has_supertype(self, supertype: str) -> bool:
        """Whether this permanent currently has a supertype (CR 205.4a).

        Computed through CR 613 layer 4, so a supertype an effect added or took
        away counts — "Target nonsnow basic land becomes snow" / "Target snow
        land is no longer snow" (Arcum's Weathervane), "All lands are no longer
        snow" (Melting).

        Every reader of "is this snow / legendary / basic?" that holds a
        ``Permanent`` must come here rather than to
        ``layer_bridge.printed_supertypes``, for the reason ``has_type`` exists
        one layer down: the printed line is the seed, not the answer.
        ``printed_supertypes`` stays for the callers that hold a *card* — a
        thing in a hand or a graveyard, where CR 613 does not apply at all.
        """
        from .layer_bridge import computed_supertypes

        return supertype.lower() in computed_supertypes(self)

    @property
    def effective_supertypes(self) -> frozenset[str]:
        """Every supertype this permanent currently has, after layer 4."""
        from .layer_bridge import computed_supertypes

        return frozenset(computed_supertypes(self))

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
    def changed_land_types(self) -> tuple[str, ...]:
        """The basic land types this land has *instead of* its printed ones.

        Empty when nothing has changed them. Derived by comparing layer 4's
        answer with the physical card, so it covers a layer-4 subtype
        replacement (Evil Presence, a mire counter) and a layer-3 text change
        rewriting the type line (Magical Hack) without either having to
        announce itself. The UI's "this is a Swamp now" badge reads it.
        """
        current = self.basic_land_types
        if not current or set(current) == _printed_basic_types(self.card.type_line):
            return ()
        return current

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
    # The command zone (CR 408), per-player for the reason the ante zone above
    # is: every rule about it is about the cards a player *owns* there — "a
    # player may cast a commander they own from the command zone" (CR 903.8),
    # "its owner may put it into the command zone" (CR 903.9a). Empty outside a
    # Commander game; see engine/commander.py.
    command_zone: list[CardDefinition] = field(default_factory=list)
    # CR 903.3: the cards designated as this player's commander. *Not* a zone —
    # the designation is an attribute of the card that survives every zone
    # change, so this list is written once before the game and never emptied,
    # while ``command_zone`` above holds only what is there right now.
    commanders: list[CardDefinition] = field(default_factory=list)
    # CR 903.8: how many times this player has cast each commander *from the
    # command zone*, keyed by name. The commander tax reads "each previous
    # time", so this is the count before the cast being paid for.
    commander_casts: dict[str, int] = field(default_factory=dict)
    # CR 903.10a: combat damage dealt to this player by each commander over the
    # course of the game, keyed by ``(owner seat, commander name)``. Keyed by
    # the commander and not by the opponent because "the same commander" is what
    # the rule adds up, and by owner as well as name because two players may
    # lead the same legend.
    commander_damage_taken: dict[tuple[int, str], int] = field(default_factory=dict)
    # CR 903.9a's "since the last time state-based actions were checked", as the
    # commander names already offered for their current stay in a graveyard or
    # in exile. Discarded when the card leaves those zones, so a commander that
    # returns and dies again is asked about again — and a declined offer is not
    # re-asked on every subsequent check.
    commander_zone_offered: set[str] = field(default_factory=set)
    # CR 903.11a: the names this player's deck started the game with. Nothing
    # else can answer that question once cards have moved, and 903.11a bars a
    # card from outside the game by exactly it.
    starting_deck_names: frozenset[str] = frozenset()
    # Emblems this player owns (CR 114): command-zone markers with an ability
    # and nothing else. Each entry is {"name", "oracle_text", "source_name"}
    # plus a private "_permanent" — a detached Permanent whose card carries the
    # emblem's text, so the trigger machinery fires it like any other source.
    # Not a permanent and not a card: board wipes never touch this list.
    emblems: list = field(default_factory=list)
    # Phased-out permanents this player controls (CR 702.26). Not a zone:
    # phasing out is not leaving the battlefield (702.26b), so the Permanent
    # object keeps its id, counters and attachments and returns as the same
    # object at this player's next untap step. While here it is off the
    # battlefield lists, which is what "treated as though it doesn't exist"
    # means to every control-seam read.
    phased_out: list[Permanent] = field(default_factory=list)
    mana_pool: dict[str, int] = field(
        default_factory=lambda: {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    )
    # "Spend this mana only to…" (CR 106.6) — one bucket per restriction key,
    # each keyed by mana symbol. Mana held here joins the pool only when paying
    # for a spell that restriction admits (spent before unrestricted mana) and
    # empties whenever the regular pool does. ``engine/restricted_mana.py`` owns
    # which keys exist and what each admits.
    #
    # It was a single field named ``creature_only_mana``, which is why that name
    # survives below as a *view*: the web payload, the AI simulator and the
    # existing tests read it, and the second wording ("an instant or sorcery
    # spell") would otherwise have needed a second field beside it — the shape
    # ``engine/shields.py`` was built to stop repeating.
    restricted_mana: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def creature_only_mana(self) -> dict[str, int]:
        """The creature-spells-only bucket. A view, so in-place mutation and
        ``.clear()`` reach the collection they used to *be*."""
        return self.restricted_mana.setdefault("creature", {})
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
    #: "You may spend mana as though it were mana of any color." (Chromatic
    #: Orrery.) Every unit in the pool, colourless included, pays a coloured
    #: pip. Its own flag rather than a widening of the one above, because the
    #: two are different permissions and a card may grant either.
    spends_mana_as_any_color: bool = False
    #: Every CR 106.6 spending permission the seat's board currently grants
    #: (``engine/mana_spending.py``). **Derived on every continuous refresh**,
    #: never stamped: the two booleans above are views over this list, and they
    #: used to be written as the source entered and never cleared -- so a
    #: destroyed Sunglasses of Urza left its owner spending white as red for the
    #: rest of the game. Nothing failed, because a stamp nobody clears reads
    #: exactly like a permission that is still true.
    mana_spending_permissions: tuple = ()
    #: "You may spend other mana only as though it were colorless mana."
    #: (Celestial Dawn.) The narrowing half of the permission above, derived
    #: with it: mana outside the permission's colours pays generic and ``{C}``
    #: and no coloured pip. Its own flag because every payment site asks the
    #: booleans rather than the list, and this is the one question none of them
    #: could ask before.
    mana_restricted_to_colorless_others: bool = False
    #: Whether this seat's permissions need the **general** payment arithmetic
    #: (``mana_payment.spend_under_permissions``) rather than one of the two
    #: special cases the booleans above name. False for every board the engine
    #: handled before Celestial Dawn -- an unrestricted permission still takes
    #: the Orrery path and a plain white-as-red one still takes the cascade --
    #: so a third payment route arrives without moving any shipped card onto it.
    mana_spending_is_general: bool = False
    #: "For one spell this turn, you may spend mana as though it were mana of
    #: any type to pay that spell's mana cost." (North Star.) A *count* rather
    #: than a flag, because the permission is bounded: it covers a stated
    #: number of this turn's spells and is used up. One entry per grant, each
    #: ``{"spells": n, "any_type": bool}`` — two grants of different breadth
    #: are two permissions and merging them would widen the narrower one.
    #: Cleared at cleanup ("this turn").
    spend_mana_as_though_grants: list = field(default_factory=list)
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
    # Life actually gained this turn (CR 119.3), counted after replacements: a
    # gain that a replacement consumed gained no life, so it must not answer
    # "if you gained 3 or more life this turn". Cleared in
    # begin_turn_bookkeeping — a "this turn" counter that never resets is a bug
    # that only shows up on turn two.
    life_gained_this_turn: int = 0
    # "…where X is the total amount of **noncombat damage dealt to your
    # opponents** this turn." (Chandra's Incinerator.) A per-seat tally of what
    # this player's sources dealt, kept because no zone holds it: the damage is
    # gone the instant it is dealt, and CR 601.2f asks for the total at the
    # moment a cost is calculated. Reset with the rest of the turn histories.
    noncombat_damage_dealt_to_opponents_this_turn: int = 0
    # Creatures that died *under this player's control* this turn. The
    # game-wide Game.creatures_died_this_turn cannot answer "under your
    # control": it is one number for the table, so reading it per player would
    # count the opponent's deaths too.
    creatures_died_under_your_control_this_turn: int = 0
    # Creatures put into *this player's graveyard* from the battlefield this
    # turn — CR 700.4's "dies", counted by the **owner** of what died rather
    # than by whoever controlled it. "…for each creature put into your graveyard
    # from the battlefield this turn" (Asmira, Holy Avenger).
    #
    # Its own tally beside the controller-scoped one above, and the two really
    # do differ: a creature stolen with Control Magic dies under the thief's
    # control (CR 109.5) and goes to its *owner's* graveyard (CR 400.3), so it
    # counts for one seat on one field and for the other seat on the other.
    # Neither is a reading of the graveyard itself, which forgets a token
    # (CR 111.7) and everything anything has since removed.
    creatures_put_into_your_graveyard_this_turn: int = 0
    # Whether this seat declared an attacker this turn (CR 508.1). On the seat
    # rather than derived from the board, because a player who attacked and
    # then lost the attacker still attacked this turn — reading
    # `attacked_this_turn` off the creatures would forget exactly the case
    # Fire and Brimstone is printed for. Reset with the rest of the turn
    # histories.
    attacked_this_turn: bool = False
    # Whether this seat tapped a land for mana this turn (CR 106.11 /
    # CR 701.26a's event, announced by the one tap seam in
    # `mixins/turn_management.py`). Beside `attacked_this_turn` above and for
    # exactly its reason: Desolation's "each player who tapped a land for mana
    # this turn" is a fact about the *seat*, and reading it off the board would
    # forget a land that has since untapped, left, or been tapped again for
    # something that is not mana. Reset with the rest of the turn histories.
    tapped_land_for_mana_this_turn: bool = False
    # Cards drawn this turn, in draw order — the last entry is "the last card you
    # drew this turn" (Jandor's Ring's discard cost). Every path that draws must
    # record here, so effects that replace a draw but still put a card in hand
    # (Aladdin's Lamp) append too. Cleared in begin_turn_bookkeeping.
    cards_drawn_this_turn: list = field(default_factory=list)
    # Spells this player has cast this turn, in cast order — recorded where the
    # cast is *announced* (`_apply_cast_triggers`), so a spell that was countered
    # still counts: "you've cast an instant or sorcery spell this turn"
    # (Stormwing Entity) asks about the casting, not about the resolution.
    # Cleared in begin_turn_bookkeeping.
    spells_cast_this_turn: list = field(default_factory=list)

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
