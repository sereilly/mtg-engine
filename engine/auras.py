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

# Templates. Several of these genuinely repeat across the pool (the P/T
# modifications, the keyword grants, the protection cycle, the upkeep damage
# family), which is why they are written as patterns rather than listed.
_TEMPLATES: tuple[tuple[re.Pattern[str], str], ...] = (
    # --- static modifications to the enchanted permanent -------------------
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
        re.compile(
            r"^enchanted land has indestructible and can't be enchanted by other auras$"
        ),
        "Wall of Wonder-style land protection — _apply_aura_effect",
    ),
    # --- combat and untap modifications ------------------------------------
    (
        re.compile(r"^all creatures able to block enchanted creature do so$"),
        "Lure — declare_blockers_step",
    ),
    (
        re.compile(rf"^enchanted {_NOUN} can't be blocked except by walls$"),
        "Invisibility — declare_blockers_step only_blockable_by_walls",
    ),
    (
        re.compile(rf"^enchanted {_NOUN} can attack as though it had haste$"),
        "Instill Energy — summoning-sickness bypass",
    ),
    (
        re.compile(rf"^enchanted {_NOUN} can attack as though it didn't have defender$"),
        "Animate Wall — declare_attackers_step can_attack_as_though_no_defender",
    ),
    (
        re.compile(
            rf"^enchanted {_NOUN} doesn't untap during its controller's untap step$"
        ),
        "Paralyze — untap_step aura_prevents_untap",
    ),
    # --- control and type changes -------------------------------------------
    (
        re.compile(rf"^you control enchanted {_NOUN}$"),
        "Control Magic / Steal Artifact — control change",
    ),
    (
        re.compile(r"^enchanted land is (?:a [a-z]+|the chosen type)$"),
        "Evil Presence / Phantasmal Terrain — land_type_override (layer 4)",
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
    return None


def unclaimed_aura_lines(normalized_lines: list[str], card_name: str = "") -> list[str]:
    """The Aura effect lines among *normalized_lines* nothing here claims.

    The "Enchant <noun>" line itself is the targeting restriction, consumed by
    ``targeting.py``/``stack_casting.aura_enchant_noun``, and is not an effect.
    """
    return [
        line
        for line in normalized_lines
        if line
        and not line.startswith("enchant ")
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
        match = _KEYWORD_GRANT.match(line)
        if match is not None:
            grants.append(match.group("keyword"))
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
        # Instill Energy. NOT a haste grant: CR 702.10b lifts the attack clause
        # of CR 302.6, and this wording lifts only that same clause. Granting
        # the haste keyword instead also lifted the {T}-ability clause, so a
        # summoning-sick Llanowar Elves under Instill Energy tapped for mana.
        re.compile(rf"^enchanted {_NOUN} can attack as though it had haste$"),
        "attacks_as_though_hasty",
    ),
)

_PROTECTION_GRANT = re.compile(
    rf"^enchanted {_NOUN} has protection from (?P<color>{_COLORS})\b"
)


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
        name in aura_restrictions(aura.card.oracle_text)
        for aura in auras_attached_to(permanent)
    )
