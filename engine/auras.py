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

**This is classification, not dispatch.** Much of the behaviour still lives in
``mixins/oracle_instructions.py:_apply_aura_effect``, a text-reading if-chain,
though the continuous halves have been migrating out of it a family at a time —
the P/T grant, the keyword grants, the restrictions, the protection cycle and
the artifact animation are all derived here now, from the Aura's own text on
every recompute. What is left in that chain is the enumeration the rest of the
migration needs: near enough one branch per card, which is the signature of a
mechanism that grows with the pool rather than with the rules.

Entries are ordered most-specific first, and each names the code that carries
it out — a line recognized here but implemented nowhere is worse than one that
fails to parse.
"""

from __future__ import annotations

import re

# The nouns an Aura's effect clause can address, from its "Enchant <noun>" line.
_NOUN = r"(?:creature|artifact|enchantment|land|wall|permanent)"

# "Enchanted creature" / "equipped creature" — the attached permanent, named by
# whichever word the card's own type uses. CR 301.5f: an ability referring to
# the "equipped creature" refers to whatever creature the permanent is attached
# to, and an Aura's "enchanted creature" is the same reference (CR 303.4). Both
# attach through the one record `attach_aura` writes, and the layer bridge
# derives the grant off the attached permanent's text either way — so every
# template below that describes a *continuous effect on the host* reads both
# words. The Aura-only shapes (control of the enchanted permanent, a land-type
# override, artifact animation) keep "enchanted": no Equipment prints them, and
# an Equipment that did would want its own reading, not a borrowed one.
_ATTACHED = r"(?:enchanted|equipped)"

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
        rf"^{_ATTACHED} {_NOUN} gets [+-]\d+/[+-]\d+, has (?P<keyword>{_KEYWORDS}), "
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
            rf"^{_ATTACHED} {_NOUN} gets [+-]\d+/[+-]\d+"
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
            rf"^{_ATTACHED} {_NOUN} has protection from (?:{_COLORS})\."
            r" this effect doesn't remove this aura$"
        ),
        "protection grant — _apply_aura_effect",
    ),
    (
        re.compile(rf"^{_ATTACHED} {_NOUN} has (?:{_KEYWORDS})$"),
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
    # An attached trigger ("when(ever) enchanted/equipped …") used to be claimed
    # here by a `.+` wildcard. `attached_trigger_claim` below claims it instead,
    # by *asking* the code that would carry the line out — see the docstring
    # there for why a wildcard was the wrong shape.
    (
        # The **two** enters-the-battlefield texts `_apply_aura_effect` performs
        # by bespoke text matching, and each pattern is keyed to the substrings
        # *that method* tests — Animate Dead's reanimation pair and Earthbind's
        # flying condition. Anything else is an ordinary compiled trigger and is
        # claimed below by `aura_compiled_trigger_claim`, which asks the
        # compiler whether the effect lowers.
        #
        # This row used to end `.+$`. The comment beside it said "never a
        # wildcard", and meant the *subject* — the effect half was open, so
        # "when this Aura enters, frobnicate the widget" was claimed by a method
        # implementing nothing of the sort, and any Aura printing an entry
        # effect the engine cannot perform reported supported and did nothing.
        # Keying to the method's own substrings is what keeps the gate and the
        # dispatch reading one rule rather than two copies.
        # `_apply_aura_effect` asks for two substrings across the *whole* card:
        # "creature card in a graveyard" (which is the **enchant** line, and is
        # already required by the `aura_enchants` gate in front of that branch)
        # and this one, which is the entry line's own half. A claim is asked per
        # line, so this pattern carries the half a line can answer for.
        re.compile(
            r"^when this (?:aura|enchantment) enters.*"
            r"return enchanted creature card to the battlefield"
        ),
        "enters-the-battlefield Aura trigger — _apply_aura_effect",
    ),
    (
        re.compile(
            r"^when this (?:aura|enchantment) enters.*"
            r"if (?:enchanted|this) creature has flying"
        ),
        "enters-the-battlefield Aura trigger — _apply_aura_effect",
    ),
    (
        re.compile(r"^whenever you're dealt damage, put that many vitality counters on this aura$"),
        "Vitality counter accumulation — damage hooks",
    ),
    # --- activated abilities granted by the Aura itself ----------------------
    (
        # "{R}{R}{R}: Regenerate enchanted creature." (The Brute.) **Every**
        # symbol of the cost, not one: the pattern used to be `\{[^}]*\}: `,
        # which reads a one-symbol cost and refuses the moment a card prints
        # two — so an Aura whose activated ability the compiler parses and the
        # activation path charges perfectly well was reported unsupported for
        # the width of its mana cost. The cost is not what decides whether the
        # ability is implemented; the claim asks for the *shape* of an
        # activation line and lets `_parse_noncreature_abilities` and the
        # grammar answer for the effect.
        re.compile(r"^\{[^}]*\}(?:\s*\{[^}]*\})*(?:, [^:]+)?: .+$"),
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


#: "Whenever enchanted land is tapped for mana, its controller adds an
#: additional {G}." (Wild Growth.) The phrase compiles to no trigger — "tapped
#: for mana" is not a condition the trigger table produces for an *attached*
#: subject — so the mana is added by `mixins/turn_management.tap_land_for_mana`
#: reading the Aura's text at the moment the land is tapped.
#:
#: The pattern lives here, once, because two readers need the same answer: that
#: dispatcher, and the support gate deciding whether the line is implemented.
#: It used to be written out only in the dispatcher, which is why the gate had
#: to claim the line with a wildcard instead.
_ADDITIONAL_MANA_ON_TAP = re.compile(
    r"^whenever enchanted land is tapped for mana, "
    r"its controller adds an additional \{([wubrgc])\}$"
)


def aura_additional_mana_on_tap_line(normalized_line: str) -> str | None:
    """The extra mana symbol *normalized_line* adds when its land is tapped."""
    match = _ADDITIONAL_MANA_ON_TAP.match(normalized_line.strip().rstrip("."))
    return match.group(1).upper() if match is not None else None


def aura_additional_mana_on_tap(oracle_text: str) -> str | None:
    """The same answer for a whole card, for the dispatcher that holds the Aura
    rather than one of its lines."""
    from .oracle import normalize_creature_line

    for raw_line in (oracle_text or "").splitlines():
        symbol = aura_additional_mana_on_tap_line(normalize_creature_line(raw_line))
        if symbol is not None:
            return symbol
    return None


_ATTACHED_TRIGGER = re.compile(rf"^when(?:ever)? {_ATTACHED} .+$")


def attached_trigger_claim(normalized_line: str, card_name: str = "") -> str | None:
    """Name what carries out an attached trigger line, or None if nothing does.

    ``when(ever) enchanted|equipped …`` was claimed by a `.+` wildcard in
    ``_TEMPLATES``, whose claim string named "trigger_utils / upkeep_effects"
    without asking either of them. That is a gate satisfied by its own
    declaration: the sentence matched the shape of a trigger, and matching the
    shape of a trigger is not evidence that one fires.

    Antiquities' Artifact Possession is the card it cost. Its whole effect is
    one trigger — "whenever enchanted artifact becomes tapped **or** a player
    activates an ability of enchanted artifact without {T} in its activation
    cost" — that nothing in the engine reads. The wildcard claimed it, the gate
    found no unclaimed effect line, and the Aura entered play and did nothing.

    So the claim asks, in the order the three mechanisms actually run:

    1. **A compiled trigger.** ``_parse_triggered_ability`` recognising the
       condition is the claim, and deliberately not "…and produced an
       instruction": Creature Bond compiles ``attached_creature_dies`` with no
       instruction at all, because its dispatcher (``mixins/effects.py``)
       builds the effect from the dead creature's toughness at trigger time.
       Requiring an instruction here would withdraw a card that works.
    2. **A name-keyed hook**, for an attached trigger whose behaviour is
       genuinely bespoke (Kudzu's destroy-and-reattach). Asked of the registry,
       never written out — a card name in a comparison here would be the
       dispatch `card_hooks.py` exists to keep in one place.
    3. **The additional-mana clause** above, which has a dispatcher and no
       trigger.

    Anything else is unclaimed, and its Aura is unsupported naming the line.
    """
    from .card_hooks import ENCHANTED_LAND_TAPPED_FOR_MANA
    from .oracle import _parse_triggered_ability

    if not _ATTACHED_TRIGGER.match(normalized_line):
        return None
    if _parse_triggered_ability(normalized_line, card_name) is not None:
        return "attached trigger — compiled condition"
    if card_name in ENCHANTED_LAND_TAPPED_FOR_MANA:
        return "attached trigger — card_hooks.ENCHANTED_LAND_TAPPED_FOR_MANA"
    if aura_additional_mana_on_tap_line(normalized_line) is not None:
        return "attached trigger — additional mana on tap"
    return None


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
    attached = attached_trigger_claim(normalized_line, card_name)
    if attached is not None:
        return attached
    compiled_trigger = aura_compiled_trigger_claim(normalized_line, card_name)
    if compiled_trigger is not None:
        return compiled_trigger
    return aura_continuous_claim(normalized_line)


def aura_compiled_trigger_claim(normalized_line: str, card_name: str = "") -> str | None:
    """Name the dispatcher behind a grammar-compiled attached trigger, or None.

    The grammar can read a triggered ability off an Aura or Equipment and lower
    it in full, and the support gate must then ask the question round 140's
    lesson demands: not "does it compile?" but "what *fires* it?". A trigger a
    declaration table produces and nothing announces is a card that reports
    supported and does nothing. So the claim is asked of the dispatch
    registries themselves rather than of a copied list of their keys:

    * the permanent's own enters trigger, fired inline after the attach by
      ``stack/resolution._apply_self_enters_battlefield_triggers``;
    * a registered pay-or-consequence pair, ``phases/upkeep_effects.py``'s
      ``UPKEEP_EFFECTS`` keyed by (condition, instruction kind);
    * an ordinary upkeep trigger (CR 603.3) — a seat-unambiguous condition
      whose instruction is a real handler, enqueued by the upkeep step.

    Anything else — however cleanly it lowers — stays unclaimed, and the card
    stays visibly unsupported instead of entering play with a silent line.

    The single-vs-``sequence`` wrapping mirrors ``oracle._grammar_line_result``,
    which is the code that builds the trigger this claim speaks for.
    """
    from .grammar import ast as grammar_ast
    from .grammar import compile_line

    compiled = compile_line(normalized_line, card_name=card_name or None)
    if compiled.parse_error is not None or compiled.lowering_error is not None:
        return None
    if not isinstance(compiled.node, grammar_ast.TriggeredAbilityNode):
        return None
    if not compiled.instructions:
        return None
    kind = (
        compiled.instructions[0].kind
        if len(compiled.instructions) == 1
        else "sequence"
    )
    cond = compiled.node.event.kind
    if cond == "enters_battlefield":
        return (
            "the Aura's own enters trigger — "
            "stack/resolution._apply_self_enters_battlefield_triggers"
        )
    from .phases.upkeep_effects import UPKEEP_EFFECTS

    if (cond, kind) in UPKEEP_EFFECTS:
        return f"registered upkeep pair ({cond}, {kind}) — phases/upkeep_effects.py"
    from .handlers import EFFECT_HANDLERS

    if cond in ("upkeep_self", "upkeep_each") and kind in EFFECT_HANDLERS:
        return "ordinary upkeep trigger (CR 603.3) — phases/upkeep_step.py"
    return None


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
    from .cast_costs import cast_cost_claims_line
    from .enter_effects import enter_effect_line
    from .target_restrictions import target_restriction_line

    return [
        line
        for line in normalized_lines
        if line
        and not line.startswith("enchant ")
        and not _is_supported_keyword_line(line)
        # "This Equipment enters with a soul counter on it." (Malefic Scythe.)
        # Entry state `_initialize_permanent_state` carries out from the
        # permanent's own text as it arrives — not an effect it has while
        # attached, so it is claimed by the table that performs it rather than
        # by an effect template here. Equipment reach this gate since the
        # compiler started holding them to it; an Aura printing an entry line
        # the table reads is claimed the same way.
        and enter_effect_line(line) is None
        # "You can't choose an untapped creature as this spell's target as you
        # cast it." (Enthralling Hold.) Not an effect the Aura has while it is
        # attached — it is spent as the spell is cast (CR 601.2c) — so it is
        # claimed by the table that enforces it rather than added to the effect
        # templates, which would put a line with no continuous behaviour behind
        # them. Asked as the same reader the cast path calls, so a phrase the
        # matcher cannot answer leaves the line unclaimed and the card
        # unsupported rather than admitted with the restriction absent.
        and not target_restriction_line(line)
        # "You may cast this card from your graveyard by paying 3 life and
        # discarding a card in addition to paying its other costs." (Demonic
        # Embrace.) Not an effect the Aura has while attached and not a
        # restriction on its targeting — it is a cost and a permission, both
        # read off this same line by the two tables that charge and open them.
        # Asked as those tables rather than listed here, so a clause they cannot
        # charge leaves the line unclaimed and the card unsupported.
        and not cast_cost_claims_line(line)
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

#: "…gets +1/+1 **for each soul counter on this Equipment**." (Malefic Scythe.)
#: The multiplier is the whole card: read as a flat grant the Scythe is a
#: permanent +1/+1 whose counters do nothing, which is what it was. Its own
#: pattern rather than a tail on the one above, because the two produce
#: different *kinds* of answer — a number, and a number per counter.
_PT_GRANT_PER_COUNTER = re.compile(
    r"gets ([+-]\d+)/([+-]\d+) for each (?P<counter>[a-z]+) counter on "
    r"(?:this|~)\b"
)


def aura_pt_grant_per_counter(oracle_text: str) -> tuple[int, int, str] | None:
    """``(power, toughness, counter name)`` for a per-counter grant, or None.

    Read before the flat grant everywhere both are asked, because the flat
    pattern matches this line's prefix: "gets +1/+1" is true of "gets +1/+1 for
    each soul counter", and answering the prefix is a card whose counters are
    decoration.
    """
    for raw_line in oracle_text.splitlines():
        match = _PT_GRANT_PER_COUNTER.search(_line_text(raw_line))
        if match is not None:
            return int(match.group(1)), int(match.group(2)), match.group("counter")
    return None


def aura_static_pt_grant(oracle_text: str) -> tuple[int, int] | None:
    """The permanent +P/+T an Aura grants while attached, or None.

    Derived from the Aura's own text on every recompute, so detaching it is
    simply ceasing to contribute — there is nothing to subtract, and nothing
    that can drift out of step with what was added.
    """
    # A per-counter grant is a different answer to a question this function only
    # knows how to answer with a constant, and its line starts the same way — so
    # it is declined here rather than reported as the flat grant it is not.
    if aura_pt_grant_per_counter(oracle_text) is not None:
        return None
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


def aura_attach_refusal(game, aura, host) -> str | None:
    """Why *aura* may not become attached to *host*, or None when it may.

    CR 303.4j: an effect that would attach an Aura to something it can't legally
    enchant simply doesn't move it — so this is asked *before* the move, and the
    Aura stays where it is when it answers. One predicate rather than a check at
    each mover, for the reason ``equip_refusal`` is one: the cast gate, the
    CR 704.5m sweep, a picker and a resolution all ask the same question, and a
    fifth copy is a fifth chance to disagree.

    Every clause is one the engine already reads somewhere else:
    ``aura_enchant_noun`` is what the cast gate matches a target against,
    ``enchant_noun_own_only`` is the seat half of the same clause (CR 702.5),
    and ``cannot_be_enchanted`` is CR 303.4's protection half.
    """
    from .mixins.stack import (aura_enchant_noun, enchant_noun_own_only,
                               permanent_matches_enchant_noun)
    from .target_immunity import cannot_be_enchanted

    if host is None or not game.is_on_battlefield(host):
        return "it is no longer on the battlefield"
    if host is aura:
        return "an Aura can't enchant itself"
    noun = aura_enchant_noun(aura.effective_card)
    if noun is None:
        return f"{aura.card.name} has no enchant ability"
    if not permanent_matches_enchant_noun(host, noun):
        return f"it isn't a legal {noun}"
    if enchant_noun_own_only(noun):
        seat = game.controller_index_of(aura)
        if seat is None or game.controller_index_of(host) != seat:
            return f"{noun} names a permanent its controller doesn't control"
    if cannot_be_enchanted(host, by_aura=aura):
        return "it can't be enchanted"
    return None


def attach_aura(aura, target) -> None:
    """Attach *aura* to *target*, recording it as an owned continuous effect.

    Stamps the Aura with a CR 613.7e timestamp at the moment it becomes
    attached, so its contribution sorts against other effects by when it
    started applying rather than sharing one derived timestamp with every other
    Aura on the board. An Equipment attaches through here too — the record is
    the same, and so is the rule (CR 301.5f) — via
    ``engine/equipment.py.attach_equipment``, which owns the legality and the
    move-from-a-previous-host half (CR 701.3).

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
    # CR 613.7e / 701.3c: a new timestamp *each time* it becomes attached. This
    # was `setdefault`, which is the same thing for an Aura (it attaches once
    # and then only leaves) and wrong for an Equipment, which moves: re-equipped
    # onto a second creature it kept the stamp of its first attachment, and so
    # ordered its +1/+1 before an effect that had in fact applied earlier.
    aura.metadata["aura_timestamp"] = next_timestamp()


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
    # The attachment's own half of the record, kept in step the way
    # `attach_aura` keeps it: an Aura that detaches is leaving anyway, but an
    # Equipment stays on the battlefield (CR 704.5n), and a stale `attached_to`
    # on it is an attachment the state-based sweep finds illegal again on every
    # pass — which is a sweep that never reaches its fixpoint.
    if aura.metadata.get("attached_to") is target:
        aura.metadata.pop("attached_to", None)
        # CR 603.10 last-known information. A triggered ability of the Aura
        # that resolves after the Aura has left — or a later step of the same
        # resolution that removed it, Cocoon's "sacrifice it, put a +1/+1
        # counter on **enchanted creature**" — still knows which creature that
        # was. `handlers/_common.attached_host` reads this back, and only
        # while the host itself is still on the battlefield.
        aura.metadata["last_attached_to"] = target


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
    "haste", "reach", "banding", "defender", "shadow", "shroud",
    "swampwalk", "forestwalk", "islandwalk", "mountainwalk", "plainswalk",
    "desertwalk",
)

_KEYWORD_GRANT = re.compile(
    rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? has "
    rf"(?P<keyword>{'|'.join(_GRANTABLE_KEYWORDS)})$"
)


_COMPOUND_INDESTRUCTIBLE = re.compile(
    rf"^enchanted {_NOUN} has indestructible and can't be enchanted by other auras$"
)

# "Enchanted creature has shroud as long as it's untapped." (Spectral Cloak.)
# The same layer-6 grant one line up with a condition on the attached
# permanent's own state — so the keyword is data, as it already was, and the
# state is data too: a card printing "…as long as it's tapped" is this rule read
# the other way and needs no code.
#
# "It" is the enchanted permanent, not the Aura. That is what the sentence
# means, and it is also the only reading with a consumer: the grant is derived
# on the *host* every recompute (`layer_bridge.collect_ability_effects`), which
# is where the state is known.
_CONDITIONAL_KEYWORD_GRANT = re.compile(
    rf"^{_ATTACHED} {_NOUN} has "
    rf"(?P<keyword>{'|'.join(_GRANTABLE_KEYWORDS)}) "
    r"as long as it's (?P<state>untapped|tapped)$"
)


def aura_conditional_keyword_grants(oracle_text: str) -> tuple[tuple[str, str], ...]:
    """``(keyword, state)`` pairs an Aura grants *while its host is in state*.

    Kept apart from :func:`aura_keyword_grants` rather than folded in with an
    optional condition, because the callers are different: the unconditional
    grant is a contribution the layer bridge always makes, and this one has to
    be asked of the host before it is made. A single list returning both would
    have the bridge granting a conditional keyword unconditionally the moment a
    caller forgot the second element.
    """
    grants: list[tuple[str, str]] = []
    for raw_line in (oracle_text or "").splitlines():
        match = _CONDITIONAL_KEYWORD_GRANT.match(_line_text(raw_line))
        if match is not None:
            grants.append((match.group("keyword"), match.group("state")))
    return tuple(grants)


def aura_conditional_grant_holds(permanent, state: str) -> bool:
    """Whether *permanent* is in *state* right now (CR 611.3a — asked on every
    recompute, never locked in when the Aura attached)."""
    return permanent.tapped if state == "tapped" else not permanent.tapped


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
        re.compile(rf"^all creatures able to block {_ATTACHED} creature do so$"),
        "must_be_blocked_by_all_able",
    ),
    (
        re.compile(
            rf"^{_ATTACHED} {_NOUN} doesn't untap during its controller's untap step$"
        ),
        "doesnt_untap",
    ),
    (
        re.compile(rf"^{_ATTACHED} {_NOUN} can attack as though it didn't have defender$"),
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
        # Demonic Torment / Pacifism's half. The compound rows above say in so
        # many words that a card printing only "can't attack" is a different
        # card; this is that card, and without the row its line was unclaimed
        # and the Aura reported unsupported.
        re.compile(rf"^enchanted {_NOUN} can't attack$"),
        "cant_attack",
    ),
    (
        # Faith's Fetters, second half. CR 605.1a's exception is part of the
        # name, because the clause without it is a strictly harsher restriction
        # — an Aura that stopped a land tapping for mana would lock its
        # controller out of the game rather than shut off one ability.
        re.compile(
            rf"^{_ATTACHED} {_NOUN} can't attack or block, and its activated "
            r"abilities can't be activated unless they're mana abilities$"
        ),
        "activated_abilities_shut_off",
    ),
)

# A "doesn't untap" restriction that holds only while a counter is present —
# the Legends sleep/pupa pair. The counter's kind and which object holds it are
# the parameters (payload, exactly as every text-keyed table treats them):
# Venarian Gold reads the counter off the **enchanted creature**, Cocoon off
# the **Aura itself**. Both rows are read by `aura_restriction_active`, so the
# untap step needs no new question — a conditional row whose condition holds is
# simply "doesnt_untap" being active this step.
#
# Cocoon prints "during **your** untap step" where Venarian Gold prints
# "during **its controller's**". The rows deliberately answer both with the
# creature's controller's step — the one the untap step is asking about —
# because Cocoon's "Enchant creature you control" makes the two the same seat
# whenever the attachment is legal: an opponent gaining control of the creature
# makes the attachment illegal, and the state-based sweep puts the Aura into
# the graveyard before any untap step arrives (CR 704.5m/n).
_COUNTER_UNTAP_CONDITIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            rf"^{_ATTACHED} {_NOUN} doesn't untap during its controller's "
            r"untap step if it has an? (?P<kind>[a-z]+) counter on it$"
        ),
        "attached",
    ),
    (
        re.compile(
            rf"^{_ATTACHED} {_NOUN} doesn't untap during your untap step "
            r"if this aura has an? (?P<kind>[a-z]+) counter on it$"
        ),
        "aura",
    ),
)


def aura_counter_untap_condition(line: str) -> tuple[str, str] | None:
    """``(counter kind, holder)`` for a counter-conditioned untap line, or None.

    *holder* names which object the condition reads: ``"attached"`` (Venarian
    Gold's sleep counter on the creature) or ``"aura"`` (Cocoon's pupa counter
    on the Aura itself).
    """
    normalized = _line_text(line)
    for pattern, holder in _COUNTER_UNTAP_CONDITIONS:
        match = pattern.match(normalized)
        if match is not None:
            return match.group("kind"), holder
    return None


_PROTECTION_GRANT = re.compile(
    rf"^{_ATTACHED} {_NOUN} has protection from (?P<color>{_COLORS})\b"
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


#: The combat-restriction kinds a reader asks of the *attached* channel below.
#:
#: ``engine/combat_restrictions.py``'s table reads a printed line, and an Aura
#: printing one of its sentences about the permanent it is attached to is the
#: same restriction — so the table is asked rather than copied, exactly as
#: ``aura_continuous_claim`` asks the derivation tables rather than listing
#: their sentences again. But every one of those kinds is enforced by reading
#: the *creature's own* compiled program, and a kind claimed here with nothing
#: consulting :func:`attached_combat_restrictions` would be a restriction the
#: card prints, the support gate admits, and no combat step ever asks about —
#: an ability that works more often than the card allows. So the set names
#: exactly the kinds a reader consults, and adding one means adding that
#: reader.
ENFORCED_ATTACHED_COMBAT_RESTRICTIONS = frozenset({
    "cant_be_blocked_by",
    # "Enchanted creature can't be blocked except by artifact creatures and/or
    # white creatures." (Seeker.) The whitelist form, read through the same
    # subject rewrite as the blacklist beside it — the difference between
    # Seeker and Elven Riders is whose text the sentence is printed on.
    "cant_be_blocked_except_by",
})

#: "Enchanted creature" / "equipped creature" in the subject position, with the
#: noun kept: the table below is written about "this creature", and a line about
#: an enchanted *artifact* is a sentence about something else that must fail to
#: match rather than be rewritten into one that does.
_ATTACHED_SUBJECT = re.compile(rf"^{_ATTACHED} (?P<noun>{_NOUN})(?= )")


def aura_combat_restriction(line: str):
    """The combat restriction an Aura's *line* imposes on what it is attached to.

    "Enchanted creature can't be blocked by artifact creatures." (Artifact
    Ward.) Argothian Pixies prints the same restriction about itself, so the
    difference between the two cards is the subject of the sentence and nothing
    else — which is why this rewrites the subject and asks
    ``combat_restrictions.combat_restriction_for`` instead of holding a second
    copy of its table.

    Returns None for a kind nothing consults through the attached channel; see
    :data:`ENFORCED_ATTACHED_COMBAT_RESTRICTIONS`.
    """
    from .combat_restrictions import combat_restriction_for

    normalized = _line_text(line)
    match = _ATTACHED_SUBJECT.match(normalized)
    if match is None:
        return None
    restriction = combat_restriction_for(
        f"this {match.group('noun')}{normalized[match.end():]}"
    )
    if restriction is None:
        return None
    if restriction.kind not in ENFORCED_ATTACHED_COMBAT_RESTRICTIONS:
        return None
    return restriction


def attached_combat_restrictions(permanent) -> tuple:
    """Every combat restriction the Auras on *permanent* impose on it.

    Asked at the moment combat reads it, so the restriction ends when the Aura
    does with nothing having to clear a flag — the same shape
    :func:`aura_restriction_active` has, carrying a payload.
    """
    found = []
    for aura in auras_attached_to(permanent):
        for raw_line in (aura.effective_card.oracle_text or "").splitlines():
            restriction = aura_combat_restriction(raw_line)
            if restriction is not None:
                found.append(restriction)
    return tuple(found)


#: "This token can't be enchanted." (Tetravus's Tetravites.) A restriction the
#: permanent prints about **itself**, which is the opposite direction from
#: everything else in this file — those describe what an Aura does to what it is
#: attached to. It lives here anyway because attachment is what it is about, and
#: because the two predicates that already answer "can an Aura go on this?" have
#: to ask one question rather than growing a third source each.
#:
#: Anchored on the whole sentence. Consecrate Land's "can't be enchanted by
#: other auras" is a *narrower* restriction with its own name in the table
#: above, and a prefix match here would claim it and then enforce the wider one.
_SELF_CANT_BE_ENCHANTED = re.compile(
    rf"^this (?:token|{_NOUN}) can't be enchanted$"
)


def self_cant_be_enchanted_line(line: str) -> bool:
    """Whether one printed line is "this <noun> can't be enchanted", in full.

    Read by the support gate and by both attachment predicates, so what is
    claimed and what is enforced cannot drift.
    """
    return _SELF_CANT_BE_ENCHANTED.match(_line_text(line)) is not None


def cant_be_enchanted_by_own_text(permanent) -> bool:
    """Whether *permanent*'s own text forbids Auras attaching to it.

    Off ``effective_card``, so a copy of a Tetravite carries the restriction
    (CR 707.2) and a text change can take it away.
    """
    card = getattr(permanent, "effective_card", None) or getattr(permanent, "card", None)
    text = getattr(card, "oracle_text", "") or ""
    return any(self_cant_be_enchanted_line(line) for line in text.splitlines())


def aura_restriction_active(permanent, name: str) -> bool:
    """Whether any Aura attached to *permanent* imposes restriction *name*.

    This is the whole of "does the restriction apply": when the Aura leaves it
    stops being attached, so it stops being asked. Nothing is stamped and
    nothing has to be cleaned up.
    """
    from .named_counters import counters_on

    for aura in auras_attached_to(permanent):
        text = aura.effective_card.oracle_text
        if name in aura_restrictions(text):
            return True
        if name != "doesnt_untap":
            continue
        # The counter-conditioned rows: the restriction is active exactly while
        # the counter is present, read at ask time — so when the last counter
        # leaves, nothing has to be cleared for the creature to untap again.
        for raw_line in (text or "").splitlines():
            found = aura_counter_untap_condition(raw_line)
            if found is None:
                continue
            kind, holder = found
            holder_obj = permanent if holder == "attached" else aura
            if counters_on(holder_obj, kind) > 0:
                return True
    return False


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
_STATIC_PT_LINE = re.compile(rf"^{_ATTACHED} {_NOUN} {_STATIC_PT_GRANT.pattern}$")
# The per-counter grant's whole line: "Equipped creature gets +1/+1 for each
# soul counter on this Equipment." The derivation's own pattern plus the noun
# that closes the sentence, so a sentence saying anything more stays unclaimed.
_PT_PER_COUNTER_LINE = re.compile(
    rf"^{_ATTACHED} {_NOUN} {_PT_GRANT_PER_COUNTER.pattern} [a-z]+$"
)
# The Ward cycle's trailing sentence, spelled out rather than left open-ended:
# it is part of the same effect (an Aura granting protection is not removed by
# it), and an "and whatever follows" claim is the one way this could swallow
# text nothing implements.
_PROTECTION_TAIL = r"(?:\. this effect doesn't remove this aura)?"
_PROTECTION_LINE = re.compile(_PROTECTION_GRANT.pattern + _PROTECTION_TAIL + "$")


#: "Enchanted artifact's activated abilities cost {2} less to activate. This
#: effect can't reduce the mana in that cost to less than one mana." (Power
#: Artifact.) Both sentences are matched together and both are required: the
#: floor is not a decoration, it is what stops a {2} ability becoming free, and
#: a pattern claiming only the first sentence would leave the second unclaimed
#: while quietly implementing a cheaper card.
_ABILITY_COST_REDUCTION = re.compile(
    rf"^{_ATTACHED} {_NOUN}'s activated abilities cost \{{(?P<generic>\d+)\}} "
    r"less to activate\. this effect can't reduce the mana in that cost to "
    r"less than (?P<floor>one|two|three) mana$"
)

_FLOOR_WORDS = {"one": 1, "two": 2, "three": 3}


def aura_ability_cost_reduction(oracle_text: str) -> tuple[int, int] | None:
    """``(generic reduction, minimum mana)`` an attached Aura grants, or None.

    Read off the Aura's whole text rather than one line, because the two
    sentences are printed as one paragraph and the floor belongs to the
    reduction in front of it.
    """
    # The "Enchant <noun>" line is the targeting restriction, not an effect —
    # flattening it in with the rest would put four words in front of an
    # anchored pattern and match nothing. Dropped here for the same reason
    # `unclaimed_aura_lines` drops it there.
    effect_lines = [
        line for line in (_line_text(raw) for raw in oracle_text.splitlines())
        if line and not line.startswith("enchant ")
    ]
    text = " ".join(" ".join(effect_lines).split())
    match = _ABILITY_COST_REDUCTION.match(text)
    if match is None:
        return None
    return int(match.group("generic")), _FLOOR_WORDS[match.group("floor")]


def aura_cost_reduction_sentences(oracle_text: str) -> tuple[str, ...]:
    """The sentences :func:`aura_ability_cost_reduction` reads, or empty.

    The reduction is **two sentences on one printed line** — the amount and the
    floor — and neither means anything alone: the first without the second is a
    strictly better card, and the second without the first modifies nothing. So
    the reader matches them joined, and this names the pair for a caller that
    walks a card sentence by sentence (``scripts/parse_coverage.py``) and would
    otherwise report both as text nothing read.
    """
    if aura_ability_cost_reduction(oracle_text) is None:
        return ()
    effect_lines = [
        line for line in (_line_text(raw) for raw in (oracle_text or "").splitlines())
        if line and not line.startswith("enchant ")
    ]
    joined = " ".join(" ".join(effect_lines).split())
    return tuple(
        sentence.strip() for sentence in joined.split(". ") if sentence.strip()
    )


def attached_ability_cost_reduction(permanent) -> tuple[int, int]:
    """``(reduction, floor)`` every Aura on *permanent* contributes, combined.

    Reductions add; the floor is the *highest* any of them names, which is the
    reading that keeps two Auras from cancelling each other's protection
    against a free ability.
    """
    total = 0
    floor = 0
    for aura in auras_attached_to(permanent):
        found = aura_ability_cost_reduction(aura.effective_card.oracle_text)
        if found is None:
            continue
        total += found[0]
        floor = max(floor, found[1])
    return total, floor


#: "Enchanted creature can't be the target of abilities from artifact sources."
#: (Artifact Ward.) Narrower than protection (CR 702.16), which also stops
#: damage, enchanting and blocking, and narrower than shroud, which stops spells
#: too — so it is neither of those with a filter bolted on, it is its own rule
#: about one kind of source choosing one kind of object.
#:
#: The source class is payload, like every other text-keyed table's parameter.
_ATTACHED_ABILITY_TARGET_IMMUNITY = re.compile(
    rf"^{_ATTACHED} {_NOUN} can't be the target of abilities from "
    r"(?P<source_type>artifact|creature|enchantment|land) sources$"
)


def aura_ability_target_immunity(line: str) -> str | None:
    """The class of source whose *abilities* may not target what this Aura is
    attached to, or None if *line* is not that sentence."""
    match = _ATTACHED_ABILITY_TARGET_IMMUNITY.match(_line_text(line))
    return match.group("source_type") if match is not None else None


def ability_target_immunity_classes(permanent) -> frozenset[str]:
    """Every source class the Auras on *permanent* make its abilities-untargetable.

    Asked at the moment a target is chosen, so the immunity ends when the Aura
    does — the same shape :func:`aura_restriction_active` has.
    """
    classes = {
        source_type
        for aura in auras_attached_to(permanent)
        for line in (aura.effective_card.oracle_text or "").splitlines()
        for source_type in (aura_ability_target_immunity(line),)
        if source_type is not None
    }
    return frozenset(classes)


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
    # Imported here rather than at module scope: `prevention` reads this
    # module's attachment record, so the two are mutually recursive at import.
    from .prevention import (
        attached_combat_shield_direction as _attached_combat_shield_direction,
        attached_prevent_all_from_source_type as _attached_prevent_all_from_source_type,
    )
    from .target_immunity import immunity_claims_line

    normalized = _line_text(line)
    if _STATIC_PT_LINE.match(normalized):
        return "static P/T grant (layer 7c) — auras.aura_static_pt_grant"
    if _PT_PER_COUNTER_LINE.match(normalized):
        return "per-counter P/T grant (layer 7c) — auras.aura_pt_grant_per_counter"
    if aura_keyword_grants(normalized):
        return "keyword grant (layer 6) — auras.aura_keyword_grants"
    if aura_conditional_keyword_grants(normalized):
        return (
            "state-conditioned keyword grant (layer 6) — "
            "auras.aura_conditional_keyword_grants"
        )
    if aura_restrictions(normalized):
        return "combat/untap restriction — auras.aura_restriction_active"
    if aura_counter_untap_condition(normalized) is not None:
        return "counter-conditioned untap restriction — auras.aura_restriction_active"
    if aura_combat_restriction(normalized) is not None:
        return "attached combat restriction — auras.attached_combat_restrictions"
    if aura_ability_target_immunity(normalized) is not None:
        return "ability-target immunity — auras.ability_target_immunity_classes"
    # "Enchanted creature can't be the target of spells and can't be enchanted
    # by other Auras." (Anti-Magic Aura.) Both clauses, or neither: the reader
    # claims a line only when it implements every restriction the line conjoins,
    # so a card pairing one of these with a sentence nothing reads stays
    # unsupported instead of losing half its text.
    if immunity_claims_line(normalized):
        return "target/enchant immunity — target_immunity"
    if _attached_prevent_all_from_source_type(normalized) is not None:
        return "prevention from a source class — prevention._source_type_shielded_by"
    if _attached_combat_shield_direction(normalized) is not None:
        return "combat-damage shield — prevention._attached_combat_shield"
    if _PROTECTION_LINE.match(normalized):
        return "protection grant — auras.aura_protection_colors"
    if aura_animates_artifact(normalized):
        return "artifact animation (layers 4 and 7b) — auras.animating_auras"
    if aura_ability_cost_reduction(normalized):
        return "activation cost reduction — auras.attached_ability_cost_reduction"
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
