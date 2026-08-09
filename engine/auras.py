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
