"""What an Aura's effect lines say, and whether the engine implements them.

The compiler classified every Aura as supported on the strength of a single
whitelist substring — ``"enchant creature"``. An Aura reading "Enchanted
creature glimmers uncontrollably", or one with no effect line at all, compiled
as `supported`, because nothing ever looked past the enchant clause. At 44
Auras that is 44 cards whose support status was never actually checked; at the
full card pool it is thousands.

This table names the effect lines the engine carries out. The support gate
requires every non-enchant line of an Aura to match something here, so an Aura
whose effect is not implemented is reported unsupported (loud) instead of
entering play and doing nothing.

**This is classification, not dispatch.** The behaviour still lives in
``mixins/oracle_instructions.py:_apply_aura_effect`` — a 270-line text-reading
if-chain. Giving each of these entries a real ``ContinuousEffect`` owned by the
Aura is the phase-6 job, and this table is the enumeration that work needs: 52
distinct lines across 44 cards, every one appearing exactly once, which is the
signature of a mechanism that grows one branch per card.

Entries are ordered most-specific first, and each names the code that carries
it out — a line recognized here but implemented nowhere is worse than one that
fails to parse.
"""

from __future__ import annotations

import re

# The nouns an Aura's effect clause can address, from its "Enchant <noun>" line.
_NOUN = r"(?:creature|artifact|enchantment|land|wall|permanent)"

_COLORS = "white|blue|black|red|green"
# Protection is restricted to the five colours on purpose. The engine's
# protection checks are colour-based, so "protection from everything" or
# "protection from Dragons" is not implemented — and a permissive
# `protection from [a-z]+` here would claim them, which is precisely the kind
# of over-broad entry that made "enchant creature" sufficient in the first
# place. Widen it when the check behind it widens, not before.
_KEYWORDS = (
    r"flying|fear|first strike|double strike|trample|vigilance|haste|reach|"
    r"banding|defender|indestructible|swampwalk|forestwalk|islandwalk|"
    rf"mountainwalk|plainswalk|desertwalk|protection from (?:{_COLORS})"
)

# "Enchanted creature gets +2/+2, has first strike, and is a Knight in addition
# to its other types." (Dub; Demonic Embrace prints the same shape.) Defined
# above the template table because three readers share it — the P/T, the
# keyword and the subtype each belong to a different CR 613 layer, and reading
# the line three times with three regexes is how one of the three gets dropped.
#
# The subtype alternation is the ingested vocabulary rather than `[a-z]+`, so
# the *gate* and the *grant* refuse the same words: a made-up type would
# otherwise be claimed here and then granted nothing, which is the shape this
# whole module exists to prevent.
class _LazyPattern:
    """A pattern compiled on first use rather than at import.

    ``engine.grammar.vocabulary`` is where the creature types live, and the
    grammar package reaches back into this module (``registries`` imports
    ``aura_continuous_claim``) — so reading the vocabulary at import time is a
    cycle. Deferring it is the whole fix; nothing else about the pattern is
    unusual.
    """

    def __init__(self, build):
        self._build, self._compiled = build, None

    def match(self, text: str):
        if self._compiled is None:
            self._compiled = self._build()
        return self._compiled.match(text)


def _build_type_addition_grant() -> re.Pattern[str]:
    from .grammar.vocabulary import CREATURE_TYPES

    subtypes = "|".join(sorted(map(re.escape, CREATURE_TYPES), key=len, reverse=True))
    return re.compile(
        rf"^enchanted {_NOUN} gets [+-]\d+/[+-]\d+, has (?P<keyword>{_KEYWORDS}), "
        rf"and is an? (?P<subtype>{subtypes}) in addition to its other types$"
    )


_TYPE_ADDITION_GRANT = _LazyPattern(_build_type_addition_grant)

# Templates. Several of these genuinely repeat across the pool (the P/T
# modifications, the keyword grants, the protection cycle, the upkeep damage
# family), which is why they are written as patterns rather than listed.
_TEMPLATES: tuple[tuple[re.Pattern[str], str], ...] = (
    # --- static modifications to the enchanted permanent -------------------
    # Everything from here down to the `_TRIGGER_TEMPLATES` boundary is a
    # *continuous* effect: while the Aura is attached, the engine derives it
    # from the Aura's own text on every recompute. None of it produces an
    # OracleInstruction, so `aura_continuous_claim` reports these lines as
    # already implemented rather than as a lowering the grammar owes.
    (
        # "Enchanted creature gets +2/+2." / "gets -1/-0" / "gets +0/+2 and has
        # reach" / "gets +0/+2 and has '{W}: ... until end of turn.'"
        re.compile(
            rf"^enchanted {_NOUN} gets [+-]\d+/[+-]\d+"
            rf"""(?: and has (?:{_KEYWORDS}|['"][^'"]+['"]))?$"""
        ),
        "static P/T (and optional granted keyword or ability) — _apply_aura_effect",
    ),
    (
        # Aspect of Wolf: a P/T that recomputes from the board.
        re.compile(
            r"^enchanted creature gets \+x/\+y, where x is half the number of "
            r"forests you control, rounded down, and y is half "
            r"(?:that number|the number of forests you control), rounded up$"
        ),
        "board-derived P/T — permanent_state._refresh_aspect_of_wolf",
    ),
    (
        # The Ward cycle. The trailing sentence is part of the same effect.
        re.compile(
            rf"^enchanted {_NOUN} has protection from (?:{_COLORS})\."
            r" this effect doesn't remove this aura$"
        ),
        "protection grant — _apply_aura_effect",
    ),
    (
        re.compile(rf"^enchanted {_NOUN} has (?:{_KEYWORDS})$"),
        "keyword grant — _apply_aura_effect",
    ),
    (
        re.compile(rf'^enchanted {_NOUN} has "[^"]+"$'),
        "granted activated/triggered ability — _apply_aura_effect",
    ),
    (
        # "…gets +2/+2, has first strike, and is a Knight in addition to its
        # other types." (Dub, Demonic Embrace.) One printed line carrying three
        # effects in three layers — 7c, 6 and 4 — which is why each half is read
        # by the reader that owns that layer rather than by a flag here.
        _TYPE_ADDITION_GRANT,
        "P/T + keyword + layer-4 subtype — aura_type_grants / layer_bridge",
    ),
    (
        re.compile(
            r"^enchanted land has indestructible and can't be enchanted by other auras$"
        ),
        "Wall of Wonder-style land protection — _apply_aura_effect",
    ),
    # --- combat and untap modifications ------------------------------------
    #
    # **Nothing here.** Six entries stood in this block, one per pattern already
    # written in `_RESTRICTIONS` — the same sentence in two lists, one deciding
    # what the Aura does and one deciding whether the card is supported. Furor
    # of the Bitten's compound line was here too, and its comment described the
    # split as a feature.
    #
    # It is the failure this file's other comments keep naming, and it fired the
    # moment round 113 added one: Faith's Fetters' restriction derived
    # perfectly, applied perfectly, and the card reported unsupported, because
    # the second list had never heard of it. `aura_effect_claim` now falls
    # through to `aura_continuous_claim`, which asks the derivation tables — so
    # a restriction added to `_RESTRICTIONS` is claimed by construction, and
    # `tests/rules/test_aura_support.py` fails if a copy comes back.
    # --- control and type changes -------------------------------------------
    (
        re.compile(rf"^you control enchanted {_NOUN}$"),
        "Control Magic / Steal Artifact — control change",
    ),
    (
        re.compile(r"^enchanted land is (?:a [a-z]+|the chosen type)$"),
        "Evil Presence / Phantasmal Terrain — land-type change (layer 4)",
    ),
    (
        re.compile(r"^as this aura enters, choose a basic land type$"),
        "Phantasmal Terrain — enter-time choice",
    ),
    (
        re.compile(
            r"^as long as enchanted artifact isn't a creature, it's an artifact "
            r"creature with power and toughness each equal to its mana value$"
        ),
        "Animate Artifact — layer 4 animation",
    ),
    # --- upkeep triggers -----------------------------------------------------
    # From here down the line *does* compile to something — a triggered ability
    # or an activated one — so these are not continuous claims and the grammar
    # must be free to lower them itself. `_CONTINUOUS_TEMPLATE_COUNT` below is
    # the boundary.
    (
        re.compile(
            rf"^at the beginning of the upkeep of enchanted {_NOUN}'s controller, "
            r"this aura deals \d+ damage to that (?:player|creature)$"
        ),
        "the upkeep-damage Aura family — phases/upkeep_effects.py",
    ),
    (
        re.compile(
            r"^at the beginning of the upkeep of enchanted creature's controller, "
            r"put a -1/-1 counter on that creature$"
        ),
        "Weakness-style decay — phases/upkeep_effects.py",
    ),
    (
        re.compile(
            rf"^at the beginning of the upkeep of enchanted {_NOUN}'s controller, "
            r"that player may pay .+$"
        ),
        "pay-or-consequence upkeep — phases/upkeep_effects.py",
    ),
    (
        re.compile(
            r"^at the beginning of your upkeep, you may remove a vitality counter "
            r"from this aura\. if you do, .+$"
        ),
        "Vitality counters — phases/upkeep_effects.py",
    ),
    # --- other triggers ------------------------------------------------------
    (
        re.compile(r"^when(?:ever)? enchanted .+$"),
        "Aura-attached trigger — trigger_utils / upkeep_effects",
    ),
    (
        # The Aura's own enters-the-battlefield trigger. Modern Oracle says
        # "this aura"; older printings and test fixtures name the card, so
        # `aura_effect_claim` also accepts the card's own name as the subject
        # (checked by the caller, never a wildcard — a wildcard here would
        # re-open exactly the hole this table closes).
        re.compile(r"^when this (?:aura|enchantment) enters(?:,| ).+$"),
        "enters-the-battlefield Aura trigger — _apply_aura_effect",
    ),
    (
        re.compile(r"^whenever you're dealt damage, put that many vitality counters on this aura$"),
        "Vitality counter accumulation — damage hooks",
    ),
    # --- activated abilities granted by the Aura itself ----------------------
    (
        re.compile(r"^\{[^}]*\}: .+$"),
        "the Aura's own activated ability — _parse_noncreature_abilities",
    ),
)


def aura_enchant_clause(oracle_text: str) -> str | None:
    """The noun an Aura's "Enchant <noun>" line names, or None if it has none.

    The one reader of that clause. Every Aura in the shipped pool prints it
    first, so its askers all spelled the question as "does the text start with
    'enchant creature'" — and Capture Sphere, which prints "Flash" above it,
    resolved into play attached to nothing while every one of those readers
    quietly answered no. There is no rule that the enchant ability is printed
    first; there is only a convention among an Aura's *own* abilities, and a
    keyword line is not one of them.

    Returns the noun as printed, graveyard forms included ("creature card in a
    graveyard"), because the reanimation branch needs to tell them apart. The
    battlefield-only question is :func:`stack.casting.aura_enchant_noun`.
    """
    for raw_line in (oracle_text or "").lower().split("\n"):
        line = re.sub(r"\([^)]*\)", "", raw_line).strip()
        if line.startswith("enchant "):
            return line[len("enchant "):].strip()
    return None


def aura_enchants(oracle_text: str, noun: str) -> bool:
    """Whether this Aura's enchant clause names *noun* (a prefix match, so
    "creature" answers "enchant creature card in a graveyard" too — exactly
    what ``text.startswith("enchant creature")`` used to mean)."""
    clause = aura_enchant_clause(oracle_text)
    return clause is not None and clause.startswith(noun)


def aura_effect_claim(normalized_line: str, card_name: str = "") -> str | None:
    """Name the code implementing *normalized_line*, or None if nothing does.

    Takes an already-normalized line (``oracle.normalize_creature_line``).
    Returns the claim string rather than a bool so a caller can report *what*
    it believes handles the line.

    *card_name* lets a self-referential trigger ("When Animate Dead enters, …")
    be recognized as the Aura's own ETB trigger. It is matched against the
    card's actual name rather than a wildcard subject, so an unrelated
    "When <something else> enters" stays unclaimed.
    """
    if card_name:
        own_name = re.escape(card_name.strip().lower())
        normalized_line = re.sub(
            rf"^when {own_name} enters", "when this aura enters", normalized_line
        )
    for pattern, claim in _TEMPLATES:
        if pattern.match(normalized_line):
            return claim
    # **The derivation tables, asked rather than copied.** Every pattern in
    # `_RESTRICTIONS` was also written out in `_TEMPLATES` — the same sentence
    # in two lists, one deciding what the Aura *does* and one deciding whether
    # the card is supported. Adding Faith's Fetters to the first made the
    # restriction work perfectly and left the card reporting unsupported, which
    # is the exact shape this file's other comments keep describing: a gate and
    # a dispatch reading two copies of one rule. `aura_continuous_claim` already
    # asks the tables, so asking it here retires the copies.
    return aura_continuous_claim(normalized_line)


def unclaimed_aura_lines(normalized_lines: list[str], card_name: str = "") -> list[str]:
    """The Aura effect lines among *normalized_lines* nothing here claims.

    The "Enchant <noun>" line itself is the targeting restriction, consumed by
    ``targeting.py``/``stack/casting.aura_enchant_noun``, and is not an effect.

    A line that is *entirely a printed keyword* is not an effect line either —
    it is the Aura's own ability, carried out wherever that keyword is. Capture
    Sphere is why: its first line is "Flash", the flash gate reads it correctly
    off the CardDefinition, and this table then reported the card unsupported
    with the reason "unimplemented aura effect: flash". Asked of the keyword
    gate rather than of a list here, so what an Aura may print and what the
    engine implements stay one table (`IMPLEMENTED_KEYWORDS`).
    """
    from .oracle import _is_supported_keyword_line
    from .target_restrictions import target_restriction_line

    return [
        line
        for line in normalized_lines
        if line
        and not line.startswith("enchant ")
        and not _is_supported_keyword_line(line)
        # "You can't choose an untapped creature as this spell's target as you
        # cast it." (Enthralling Hold.) Not an effect the Aura has while it is
        # attached — it is spent as the spell is cast (CR 601.2c) — so it is
        # claimed by the table that enforces it rather than added to the effect
        # templates, which would put a line with no continuous behaviour behind
        # them. Asked as the same reader the cast path calls, so a phrase the
        # matcher cannot answer leaves the line unclaimed and the card
        # unsupported rather than admitted with the restriction absent.
        and not target_restriction_line(line)
        and aura_effect_claim(line, card_name) is None
    ]


# ---------------------------------------------------------------------------
# The static P/T an Aura grants, derived rather than remembered
# ---------------------------------------------------------------------------

# "Enchanted creature gets +2/+2." The grant is a property of the Aura's text,
# so it can be recomputed from the Aura at any time. It used to be applied once
# into the enchanted permanent's `power_bonus` with the delta recorded on the
# Aura and subtracted again on removal (CR 611.3) — the shape that shipped the
# Aspect of Wolf compounding bug.
#
# "+N/+N until end of turn" is deliberately excluded: that comes from an
# *activated* ability the Aura grants (Firebreathing, Blessing) and applies when
# the ability is activated, not while the Aura is attached.
_STATIC_PT_GRANT = re.compile(r"gets ([+-]\d+)/([+-]\d+)(?! until end of turn)")


def aura_static_pt_grant(oracle_text: str) -> tuple[int, int] | None:
    """The permanent +P/+T an Aura grants while attached, or None.

    Derived from the Aura's own text on every recompute, so detaching it is
    simply ceasing to contribute — there is nothing to subtract, and nothing
    that can drift out of step with what was added.
    """
    for raw_line in oracle_text.splitlines():
        line = _line_text(raw_line)
        match = _STATIC_PT_GRANT.search(line)
        if match is None:
            continue
        if line[match.end():].lstrip().startswith("until end of turn"):
            continue
        return int(match.group(1)), int(match.group(2))
    return None


def auras_attached_to(permanent) -> list:
    """Every Aura currently attached to *permanent*, in attachment order.

    ``attached_aura`` is a single slot that a second Aura overwrites, so it
    cannot answer this: a creature can carry any number of Auras (CR 303.4).
    The list is the authority; the slot is kept in step for the callers that
    only ever want "an" Aura.
    """
    return list(permanent.metadata.get("attached_auras") or [])


def attach_aura(aura, target) -> None:
    """Attach *aura* to *target*, recording it as an owned continuous effect.

    Stamps the Aura with a CR 613.7b timestamp at the moment it becomes
    attached, so its contribution sorts against other effects by when it
    started applying rather than sharing one derived timestamp with every other
    Aura on the board.

    Both directions are recorded here so no caller has to remember to keep them
    in step: ``attached_to`` on the Aura, and both ``attached_auras`` (the list,
    which is the authority) and ``attached_aura`` (the single slot kept for the
    callers that only want "an" Aura) on the target.
    """
    from .continuous import next_timestamp

    aura.metadata["attached_to"] = target
    attached = list(target.metadata.get("attached_auras") or [])
    if not any(existing is aura for existing in attached):
        attached.append(aura)
    target.metadata["attached_auras"] = attached
    target.metadata["attached_aura"] = aura
    aura.metadata.setdefault("aura_timestamp", next_timestamp())


def detach_aura(aura, target) -> None:
    """Stop *aura* applying to *target* (CR 611.3).

    Dropping the Aura from the list is the whole removal: its P/T contribution
    is recomputed from the Auras still attached, so there is no remembered
    delta to subtract and nothing that can fall out of step with what was
    added.
    """
    remaining = [
        existing
        for existing in (target.metadata.get("attached_auras") or [])
        if existing is not aura
    ]
    if remaining:
        target.metadata["attached_auras"] = remaining
        target.metadata["attached_aura"] = remaining[-1]
    else:
        target.metadata.pop("attached_auras", None)
        if target.metadata.get("attached_aura") is aura:
            target.metadata.pop("attached_aura", None)


# Reminder text. `oracle.normalize_creature_line` strips it, but importing the
# compiler here would be a cycle (it imports this module), so the one-line
# equivalent lives here. Without it an anchored pattern silently stops matching
# every card whose printing carries a reminder — which is most of them.
_REMINDER = re.compile(r"\([^)]*\)")


def _line_text(raw_line: str) -> str:
    return " ".join(_REMINDER.sub("", raw_line).strip().lower().split()).rstrip(".")

# The keyword abilities an Aura grants while attached. Same treatment as the
# P/T grant: derived from the Aura's text on every recompute and stamped with
# its attach time, so removal is dropping a contribution rather than finding
# and undoing a recorded grant.
#
# Landwalk is included. It reaches the same layer-6 channel as every other
# keyword, so the combat check that consumes it must read *computed* abilities
# rather than the raw `has_<walk>` flag the imperative path used to stamp.
_GRANTABLE_KEYWORDS = (
    "flying", "fear", "first strike", "double strike", "trample", "vigilance",
    "haste", "reach", "banding", "defender", "shadow",
    "swampwalk", "forestwalk", "islandwalk", "mountainwalk", "plainswalk",
    "desertwalk",
)

_KEYWORD_GRANT = re.compile(
    rf"^enchanted {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? has "
    rf"(?P<keyword>{'|'.join(_GRANTABLE_KEYWORDS)})$"
)


_COMPOUND_INDESTRUCTIBLE = re.compile(
    rf"^enchanted {_NOUN} has indestructible and can't be enchanted by other auras$"
)


def aura_keyword_grants(oracle_text: str) -> tuple[str, ...]:
    """Keyword abilities an Aura grants to the permanent it enchants.

    Only whole-line grants of a known keyword count. "Enchanted creature has
    protection from black. This effect doesn't remove this Aura." and
    'Enchanted land has "…"' are deliberately not matched: protection is a
    metadata channel with its own checks, and a granted *quoted* ability is not
    a keyword — claiming either here would say the layer-6 grant carries them
    when it does not.
    """
    grants: list[str] = []
    for raw_line in oracle_text.split("\n"):
        line = _line_text(raw_line)
        match = _KEYWORD_GRANT.match(line) or _TYPE_ADDITION_GRANT.match(line)
        if match is not None:
            grants.append(match.group("keyword"))
        elif _COMPOUND_INDESTRUCTIBLE.match(line):
            # Consecrate Land prints one line carrying two effects. Its trailing
            # clause is claimed separately as a restriction, so matching only
            # the keyword half here drops nothing — which is the whole reason
            # the compound is spelled out rather than matched loosely.
            grants.append("indestructible")
    return tuple(grants)


# ---------------------------------------------------------------------------
# Restrictions an Aura imposes
# ---------------------------------------------------------------------------
#
# These are not characteristics, so CR 613's layers do not apply to them — they
# change how the game is played (what may block, what untaps, what may attack).
# The ownership principle is the same one the layers gave P/T and keywords: the
# reader asks whether any attached Aura imposes the restriction, instead of the
# Aura stamping a flag on the permanent and something having to remember to
# take it off again.
#
# Each name is the vocabulary the readers use; the pattern is the printed line.
_RESTRICTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(rf"^enchanted {_NOUN} can't be blocked except by walls$"),
        "only_blockable_by_walls",
    ),
    (
        re.compile(r"^all creatures able to block enchanted creature do so$"),
        "must_be_blocked_by_all_able",
    ),
    (
        re.compile(
            rf"^enchanted {_NOUN} doesn't untap during its controller's untap step$"
        ),
        "doesnt_untap",
    ),
    (
        re.compile(rf"^enchanted {_NOUN} can attack as though it didn't have defender$"),
        "ignores_defender",
    ),
    (
        # Furor of the Bitten. The P/T half is read by `aura_static_pt_grant`,
        # which searches rather than anchors — so this pattern claims the whole
        # line and neither half is dropped.
        re.compile(
            rf"^enchanted {_NOUN} gets [+-]\d+/[+-]\d+ and attacks each combat if able$"
        ),
        "must_attack_each_combat",
    ),
    (
        # The other half of Consecrate Land's compound line; the indestructible
        # half is a layer-6 keyword grant (aura_keyword_grants).
        re.compile(
            rf"^enchanted {_NOUN} has indestructible and "
            r"can't be enchanted by other auras$"
        ),
        "cant_be_enchanted_by_auras",
    ),
    (
        # Instill Energy. NOT a haste grant: CR 702.10b lifts the attack clause
        # of CR 302.6, and this wording lifts only that same clause. Granting
        # the haste keyword instead also lifted the {T}-ability clause, so a
        # summoning-sick Llanowar Elves under Instill Energy tapped for mana.
        re.compile(rf"^enchanted {_NOUN} can attack as though it had haste$"),
        "attacks_as_though_hasty",
    ),
    (
        # Faith's Fetters, first half. Two restrictions in one printed clause,
        # and both are named here rather than one standing for the pair: a card
        # printing only "can't attack" (Pacifism) or only "can't block" is a
        # different card, and the enforcement sites are two different steps.
        re.compile(rf"^enchanted {_NOUN} can't attack or block\b"),
        "cant_attack",
    ),
    (
        re.compile(rf"^enchanted {_NOUN} can't attack or block\b"),
        "cant_block",
    ),
    (
        # Faith's Fetters, second half. CR 605.1a's exception is part of the
        # name, because the clause without it is a strictly harsher restriction
        # — an Aura that stopped a land tapping for mana would lock its
        # controller out of the game rather than shut off one ability.
        re.compile(
            rf"^enchanted {_NOUN} can't attack or block, and its activated "
            r"abilities can't be activated unless they're mana abilities$"
        ),
        "activated_abilities_shut_off",
    ),
)

_PROTECTION_GRANT = re.compile(
    rf"^enchanted {_NOUN} has protection from (?P<color>{_COLORS})\b"
)


def aura_type_grants(oracle_text: str) -> tuple[str, ...]:
    """Creature subtypes an Aura *adds* to what it enchants (CR 613 layer 4).

    "…and is a Knight in addition to its other types" — added, never replacing,
    which is the difference between this and a land-type change (CR 305.7) and
    why it goes through ``add_types`` with ``replace_subtypes`` off.
    """
    granted: list[str] = []
    for raw_line in oracle_text.split("\n"):
        match = _TYPE_ADDITION_GRANT.match(_line_text(raw_line))
        if match is not None:
            granted.append(match.group("subtype"))
    return tuple(granted)


def aura_restrictions(oracle_text: str) -> frozenset[str]:
    """The named restrictions an Aura imposes while attached."""
    found = {
        name
        for raw_line in oracle_text.splitlines()
        for pattern, name in _RESTRICTIONS
        if pattern.match(_line_text(raw_line))
    }
    return frozenset(found)


def aura_protection_colors(oracle_text: str) -> frozenset[str]:
    """Colour words an Aura grants protection from (the Ward cycle).

    Colour *words*, not mana symbols: the caller maps them, and it is the one
    that knows about text-changing remaps (Sleight of Mind).
    """
    found = set()
    for raw_line in oracle_text.splitlines():
        match = _PROTECTION_GRANT.match(_line_text(raw_line))
        if match is not None:
            found.add(match.group("color"))
    return frozenset(found)


def aura_restriction_active(permanent, name: str) -> bool:
    """Whether any Aura attached to *permanent* imposes restriction *name*.

    This is the whole of "does the restriction apply": when the Aura leaves it
    stops being attached, so it stops being asked. Nothing is stamped and
    nothing has to be cleaned up.
    """
    return any(
        name in aura_restrictions(aura.effective_card.oracle_text)
        for aura in auras_attached_to(permanent)
    )


# Animate Artifact: "As long as enchanted artifact isn't a creature, it's an
# artifact creature with power and toughness each equal to its mana value."
#
# Two layers from one line — layer 4 adds the creature type, layer 7b sets P/T —
# which is why it cannot be expressed as a flag. The engine used to *rebuild the
# CardDefinition* with "Creature" spliced into the type line and P/T baked in,
# swap it onto the permanent, and stash the original to restore on removal: the
# remember-and-undo shape, applied to the object's identity.
_ANIMATE_ARTIFACT = re.compile(
    r"^as long as enchanted artifact isn't a creature, it's an artifact creature "
    r"with power and toughness each equal to its mana value$"
)


def aura_animates_artifact(oracle_text: str) -> bool:
    """Whether this Aura animates the artifact it enchants."""
    return any(
        _ANIMATE_ARTIFACT.match(_line_text(raw_line))
        for raw_line in oracle_text.splitlines()
    )


# ---------------------------------------------------------------------------
# Which lines the derivations above already account for
# ---------------------------------------------------------------------------

# The whole-line forms of the grants above. Each is built from the *same*
# pattern source the derivation matches with, so a claim here cannot outlive
# the code that carries it out — the rule engine/grammar/registries.py works
# under. Where a derivation is already `^…$` anchored per line it is asked
# directly and needs no companion here.
_STATIC_PT_LINE = re.compile(rf"^enchanted {_NOUN} {_STATIC_PT_GRANT.pattern}$")
# The Ward cycle's trailing sentence, spelled out rather than left open-ended:
# it is part of the same effect (an Aura granting protection is not removed by
# it), and an "and whatever follows" claim is the one way this could swallow
# text nothing implements.
_PROTECTION_TAIL = r"(?:\. this effect doesn't remove this aura)?"
_PROTECTION_LINE = re.compile(_PROTECTION_GRANT.pattern + _PROTECTION_TAIL + "$")


def aura_continuous_claim(line: str) -> str | None:
    """Name the code implementing *line* as a continuous Aura effect, or None.

    Continuous here means "applied while the Aura is attached, derived from the
    Aura's own text, with no ``OracleInstruction`` anywhere": the P/T grant
    (layer 7c), the keyword grants (layer 6), the protection cycle, the combat
    and untap restrictions, the artifact animation. The grammar must not lower
    these — the engine is already applying them, and an instruction would apply
    them twice.

    Deliberately narrower than :func:`aura_effect_claim` at both ends. It stops
    short of the Aura's triggered and activated abilities, which *do* compile to
    instructions and which a claim here would silently shadow; and it claims
    only what one of the derivation functions above actually matches, so the
    shapes those do not implement (Aspect of Wolf's board-derived P/T, the
    control change, the land-type override) stay visible in the backlog rather
    than being called done by a table that merely recognizes them.

    Takes a raw printed line: reminder text is stripped here, because most
    printings of these Auras carry it and an anchored pattern would otherwise
    stop matching almost all of them.
    """
    normalized = _line_text(line)
    if _STATIC_PT_LINE.match(normalized):
        return "static P/T grant (layer 7c) — auras.aura_static_pt_grant"
    if aura_keyword_grants(normalized):
        return "keyword grant (layer 6) — auras.aura_keyword_grants"
    if aura_restrictions(normalized):
        return "combat/untap restriction — auras.aura_restriction_active"
    if _PROTECTION_LINE.match(normalized):
        return "protection grant — auras.aura_protection_colors"
    if aura_animates_artifact(normalized):
        return "artifact animation (layers 4 and 7b) — auras.animating_auras"
    return None


def animating_auras(permanent) -> list:
    """Attached Auras that animate *permanent*, honouring "isn't a creature".

    The condition is read from the permanent's **printed** type line rather than
    its computed one: asking whether it is currently a creature would include
    the creature type this very effect adds, and the answer would depend on
    whether it had already been asked.
    """
    if "creature" in permanent.card.type_line.lower():
        return []
    return [
        aura
        for aura in auras_attached_to(permanent)
        if aura_animates_artifact(aura.effective_card.oracle_text)
    ]
