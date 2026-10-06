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
from functools import lru_cache

# The nouns an Aura's effect clause can address, from its "Enchant <noun>" line.
_NOUN = r"(?:creature|artifact|enchantment|land|wall|permanent)"

#: "Enchanted land is a Swamp." (Evil Presence.) "Enchanted land is **an**
#: Island." (Lingering Mirage.) CR 305.7's replacement, layer 4 — and one
#: pattern for the claim and for the change, so a line this table admits is a
#: line the application can carry out.
#:
#: The article is an alternation because English puts "an" in front of Island,
#: and it is the *whole* of what refused Lingering Mirage: the claim read "a
#: [a-z]+" and the application compared against the literal "enchanted land is
#: a swamp", so a second basic type had nowhere to land twice over.
#:
#: The five types are spelled out rather than taken from the creature-type
#: catalogue, because CR 305.6 closes this set: those are the basic land types
#: there are. A word outside it is not a land type at all, and admitting one
#: would claim a line whose change nothing could make.
_AURA_LAND_TYPE_RE = re.compile(
    r"^enchanted land is an? (?P<type>plains|island|swamp|mountain|forest)$"
)


def aura_land_type_change(oracle_text: str) -> str | None:
    """The basic land type an Aura's text sets its host to, or None.

    The application half of the claim above, reading the same pattern — so the
    line reported implemented and the line acted on are one line. It was a
    substring test for ``"enchanted land is a swamp"`` inside
    ``mixins/oracle_instructions.py``, which is a card name written as a
    sentence: Evil Presence worked and every other printing of the template
    attached and did nothing.

    Takes the whole text and walks its lines, like every other reader here, so
    the caller does not have to know which line carries the clause.
    """
    for raw_line in (oracle_text or "").splitlines():
        line = " ".join(raw_line.strip().lower().split()).rstrip(".")
        match = _AURA_LAND_TYPE_RE.match(line)
        if match is not None:
            return match.group("type")
    return None

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
#: "protection from black **and from red**" (Mask of Law and Grace). CR 702.16g:
#: that clause is shorthand for **two** protection abilities, not one ability
#: with a compound quality -- which is why the conjunction is spelled once here
#: and split by :func:`aura_protection_colors` rather than being matched as an
#: opaque phrase.
#:
#: One alternation shared by the gate (``_TEMPLATES``) and the grant
#: (``_PROTECTION_GRANT``) below, for this file's standing reason: the sentence
#: that decides whether the card is supported and the sentence that decides what
#: it does have to be the same sentence. Written as a name because it is read
#: from two patterns, which is exactly when a literal starts drifting.
#:
#: "…protection from **each color among permanents you control**" (Pledge of
#: Loyalty). CR 702.16i: shorthand for one protection ability per colour in a
#: *set*, and here the set is read off a board — so it is a third alternative
#: beside a printed colour and a chosen one, resolved by the reader that holds
#: the Aura (:data:`AMONG_CONTROLLED_PROTECTION_COLORS`).
_PROTECTION_QUALITY = (
    rf"(?:{_COLORS}|the chosen color|each color among permanents you control)"
)
_PROTECTION_QUALITIES = rf"{_PROTECTION_QUALITY}(?: and from {_PROTECTION_QUALITY})*"

_KEYWORDS = (
    r"flying|fear|first strike|double strike|trample|vigilance|haste|reach|"
    r"banding|defender|indestructible|swampwalk|forestwalk|islandwalk|"
    rf"mountainwalk|plainswalk|desertwalk|protection from (?:{_PROTECTION_QUALITIES})"
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
#: The two printings of the reanimation Aura's entry line — the sentence
#: ``mixins/oracle_instructions._apply_aura_effect`` performs by reading the
#: card's own words. Named here, beside the gate, because the gate and that
#: method have to be looking at the same sentence: the pattern in ``_TEMPLATES``
#: is built out of this tuple, so a printing one of them reads and the other
#: does not is not expressible.
#:
#: Animate Dead prints the first and Dance of the Dead the second, which is what
#: makes this a template rather than a card: the difference between the two
#: sentences is one verb and one word of timing.
AURA_REANIMATION_PHRASES: tuple[str, ...] = (
    "return enchanted creature card to the battlefield",
    "put enchanted creature card onto the battlefield",
)

#: The word that separates them. "…onto the battlefield **tapped** under your
#: control" (Dance of the Dead) — read by the same method, off the same text.
AURA_REANIMATION_TAPPED = "onto the battlefield tapped"


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
            rf"""(?: and (?:has (?:{_KEYWORDS}|['"][^'"]+['"])|is (?:{_COLORS})))?$"""
        ),
        "static P/T (and optional granted keyword, ability or colour) — _apply_aura_effect",
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
        # Snowblind. A board-counted penalty whose *board* depends on the
        # combat, clamped so it can never kill the creature — see
        # :func:`aura_board_counted_penalty` for what each piece is and why the
        # noun is payload.
        _LazyPattern(lambda: _build_board_counted_penalty()),
        "board-counted clamped penalty — permanent_state._refresh_board_counted_penalties",
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
        # "Enchanted creature **is black**." The colour half of the P/T row
        # above, printed on its own. Its own row rather than a fourth optional
        # suffix there, because a card printing the colour and nothing else
        # would have to make the P/T half optional too — and a pattern whose
        # every half is optional matches "enchanted creature" alone.
        re.compile(rf"^{_ATTACHED} {_NOUN} is (?:{_COLORS})$"),
        "colour override (layer 5) — aura_color_grants / layer_bridge",
    ),
    (
        re.compile(rf'^{_ATTACHED} {_NOUN} has "[^"]+"$'),
        "granted ability line — aura_granted_ability_lines / Permanent.effective_card",
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
        _AURA_LAND_TYPE_RE,
        "Evil Presence / Lingering Mirage — land-type change (layer 4)",
    ),
    (
        re.compile(r"^enchanted land is the chosen type$"),
        "Phantasmal Terrain — land-type change to the chosen type (layer 4)",
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
        # The CR 122.1a pair is a *parameter* of the decay, not part of what the
        # engine implements: Unstable Mutation prints -1/-1 and Takklemaggot
        # -0/-1, and `add_pt_counters_to_attached` reads the pair off the
        # payload. Spelling one pair here is what kept the second card out —
        # the row claimed a card rather than a template.
        re.compile(
            r"^at the beginning of the upkeep of enchanted creature's controller, "
            r"put a [+-]\d+/[+-]\d+ counter on that creature$"
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
    (
        # Living Artifact's accumulating half. The row survives its *reason*:
        # what carried this line out used to be a substring branch inside
        # ``mixins/effects._on_player_dealt_damage``, and the line now compiles
        # to an ordinary triggered ability through CR 120.4b's passive condition
        # row. The Aura gate still has to be told the line is implemented — that
        # is what this table is — so the entry stays and only the attribution
        # moves.
        re.compile(
            r"^whenever you're dealt damage, put that many vitality counters "
            r"on this aura$"
        ),
        "Vitality counter accumulation — the damage_dealt trigger",
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
            r"^when this (?:aura|enchantment) enters.*(?:"
            + "|".join(re.escape(phrase) for phrase in AURA_REANIMATION_PHRASES)
            + r")"
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
    """Whether this Aura's enchant clause names *noun*.

    A prefix match against each noun the clause names, so "creature" answers
    "enchant creature card in a graveyard" too — exactly what
    ``text.startswith("enchant creature")`` used to mean — while a printed
    *quality* no longer hides the noun behind it. The clause is reduced by
    ``targeting.enchant_clause_nouns``, the same three splitters the picker and
    the cast gate use, because this reader was the one Mirage's widening broke:
    "Enchant **red or green** creature" answered no to every branch and
    "Enchant **artifact or creature**" answered yes to the artifact one whatever
    the Aura had actually enchanted.
    """
    from .targeting import enchant_clause_nouns

    clause = aura_enchant_clause(oracle_text)
    if clause is None:
        return False
    return any(part.startswith(noun) for part in enchant_clause_nouns(clause))


#: "Whenever enchanted land is tapped for mana, its controller adds an
#: additional {G}." (Wild Growth.) "…adds an additional {G}{G}." (Overgrowth.)
#: The phrase compiles to no trigger — "tapped for mana" is not a condition the
#: trigger table produces for an *attached* subject — so the mana is added by
#: `mixins/turn_management.tap_land_for_mana` reading the Aura's text at the
#: moment the land is tapped.
#:
#: **A run of symbols, not one.** The single-symbol group was a pattern written
#: to the one card that printed it, and the second card printing the template
#: doubles the symbol rather than changing the sentence — so the count is data
#: the same way every other printed number in this engine is. Written as one
#: group it would have refused Overgrowth outright, which is the loud direction;
#: written as an unanchored single symbol it would have added **half** the mana
#: the card prints, which is not.
#:
#: The pattern lives here, once, because two readers need the same answer: that
#: dispatcher, and the support gate deciding whether the line is implemented.
#: It used to be written out only in the dispatcher, which is why the gate had
#: to claim the line with a wildcard instead.
_ADDITIONAL_MANA_ON_TAP = re.compile(
    r"^whenever enchanted land is tapped for mana, "
    r"its controller adds an additional "
    r"(?:(?P<symbols>(?:\{[wubrgc]\})+)|(?P<any>one mana of any color))$"
)

#: The member :func:`aura_additional_mana_on_tap_line` returns for "one mana of
#: **any color**" (Fertile Ground) rather than a printed symbol. Carried in the
#: same tuple as the printed pips because it is the same clause with the colour
#: left open (CR 106.6: the controller chooses as the ability resolves), and one
#: reader answering one question is what keeps the support gate and the
#: dispatcher from drifting - which is the whole reason this pattern is here and
#: not written out at the tap site.
#:
#: Never a mana symbol, so no caller can mistake it for one: the symbols this
#: pattern produces are the five colours and {C}, upper-cased.
AURA_ANY_COLOR_MANA = "any"


def aura_additional_mana_on_tap_line(normalized_line: str) -> tuple[str, ...]:
    """The extra mana symbols *normalized_line* adds when its land is tapped.

    Empty for a line this does not implement, so a caller may ask it as a
    predicate — one answer for the dispatcher and for the support gate, which
    is why the pattern is not written out at either.
    """
    match = _ADDITIONAL_MANA_ON_TAP.match(normalized_line.strip().rstrip("."))
    if match is None:
        return ()
    if match.group("any"):
        return (AURA_ANY_COLOR_MANA,)
    return tuple(
        sym.upper() for sym in re.findall(r"[wubrgc]", match.group("symbols"))
    )


def aura_additional_mana_on_tap(oracle_text: str) -> tuple[str, ...]:
    """The same answer for a whole card, for the dispatcher that holds the Aura
    rather than one of its lines."""
    from .oracle import normalize_creature_line

    for raw_line in (oracle_text or "").splitlines():
        symbols = aura_additional_mana_on_tap_line(normalize_creature_line(raw_line))
        if symbols:
            return symbols
    return ()


# A trigger whose *condition* is about the permanent this Aura or Equipment is
# attached to. The attached word need not open the sentence: Imprison's
# condition is "whenever a player activates an ability of **enchanted
# creature** …", where the opening noun is a player and the attached permanent
# is three words in. Bounded to before the first comma, which is where a
# trigger condition ends everywhere in this engine — so the word has to be part
# of what the trigger fires *on*, never part of what it then does.
#
# Widening the shape widens nothing about the claim: what follows still has to
# compile a real instruction, or be one of the three named dispatchers below.
_ATTACHED_TRIGGER = re.compile(rf"^when(?:ever)? [^,]*\b{_ATTACHED} .+$")

# "When enchanted creature dies, this Aura deals damage equal to that
# creature's toughness to the creature's controller." (Creature Bond.)
#
# **The template and its dispatcher are gone.** They existed because the
# toughness had to be read while the creature was still on the battlefield
# (CR 603.10) and no instruction payload could hold a number nobody had
# measured yet — which was true of the *fire site*, not of the rule.
# ``_fire_creature_dies_triggers`` freezes ``dead_toughness`` into every death
# it announces now, so "damage equal to that creature's toughness" lowers to an
# ordinary ``deal_damage`` reading that key and claim 1 below covers the line.
#
# Keeping both would have been strictly worse than either: the compiled trigger
# is announced by the graveyard seam and the bespoke one by four ``on_destroy``
# callbacks beside it, so Creature Bond dealt its damage **twice** on the two
# state-based-action paths and once everywhere else.


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

    1. **A compiled trigger that produced an instruction.** Recognising the
       *condition* is not enough, and used to be: ``attached_creature_dies``
       parses for every Aura printing "when enchanted creature dies", so the
       claim was satisfied by three cards whose effect clause compiled to
       nothing — and one dispatcher keyed on that condition kind then gave all
       three Creature Bond's damage.
    2. **The additional-mana clause** above, which has a dispatcher and no
       trigger.

    There used to be a 1b: a death-damage template claimed by its printed line,
    for the one attached trigger the engine performed without an instruction.
    The death fire site freezes the dead creature's toughness now, so the
    sentence compiles like any other and claim 1 covers it.

    There used to be a third: a name-keyed registry of Aura behaviour dispatched
    from inside ``tap_land_for_mana``, whose only entry was Kudzu. It is a
    ``card_hooks.CARD_LINE_INSTRUCTIONS`` line now, so claim 1 above covers it —
    which is the point of that registry over a bespoke dispatcher. The
    instruction is announced by the tap seam, so the trigger fires however the
    land became tapped rather than on the one path its dispatcher lived in.

    Anything else is unclaimed, and its Aura is unsupported naming the line.
    """
    from .oracle import _parse_triggered_ability

    if not _ATTACHED_TRIGGER.match(normalized_line):
        return None
    parsed = _parse_triggered_ability(normalized_line, card_name)
    if parsed is not None and parsed.instruction is not None:
        return "attached trigger — compiled instruction"
    if aura_additional_mana_on_tap_line(normalized_line):
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
    # **A quoted grant is claimed only if the host can read the quote.** The
    # two rows below that admit `has "<anything>"` ask nothing of what is
    # between the quotes — the words are compiled on a *different permanent*,
    # by `Permanent.effective_card` — so an Aura whose quote the grammar
    # refuses reported supported, attached, and granted a sentence no step ever
    # acted on. Pendrell Flux did nothing for nine sets and Archery Training
    # for four. Asked before every claim rather than inside those two rows: a
    # line carrying an unreadable quote is unimplemented whichever reader
    # further down would also have liked the rest of it.
    quoted = _QUOTED_ABILITY_GRANT.match(normalized_line)
    if quoted is not None and not quoted_grant_readable(
        quoted.group("ability"), card_name
    ):
        return None
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
    anthem = aura_anthem_claim(normalized_line)
    if anthem is not None:
        return anthem
    conditional = aura_conditional_static_claim(normalized_line)
    if conditional is not None:
        return conditional
    activated = aura_activated_ability_claim(normalized_line, card_name)
    if activated is not None:
        return activated
    return aura_continuous_claim(normalized_line)


def aura_activated_ability_claim(normalized_line: str, card_name: str = "") -> str | None:
    """Name the code behind an activated ability the Aura or Equipment prints,
    or None.

    **The compiler's own reader, asked rather than described.** This was a
    regex for the *shape* of an activation line — a run of mana symbols, an
    optional comma-separated tail, a colon — standing in for
    ``_parse_activated_ability``, and a stand-in disagrees with what it stands
    for in both directions. It did:

    * CR 602.1 admits **any** cost, and this one had to start with a mana
      symbol. Fylgja's "Remove a healing counter from this Aura: Prevent the
      next 1 damage that would be dealt to enchanted creature this turn" parses
      in full — the cost charges the counter, the effect lowers to a shield —
      and the card was reported unsupported for the shape of its cost.
    * The other way round, a line matching the shape whose effect the compiler
      *cannot* read was claimed anyway. Chromatic Armor's "{X}: Put a sleight
      counter on this Aura and choose a color…" is one, and a claim there is
      how an Aura reports supported carrying an ability that does nothing.

    So the question is asked of the reader that answers it, and both cards move
    the way they should. The ability must be supported **and** carry an
    instruction, which is the same pair every other gate in the engine treats as
    "there is something behind this line".
    """
    from .oracle import _parse_activated_ability

    ability = _parse_activated_ability(normalized_line, card_name)
    if ability is None or not ability.supported or ability.instruction is None:
        return None
    return "the Aura's own activated ability — _parse_activated_ability"


def aura_anthem_claim(normalized_line: str) -> str | None:
    """Name the code behind a board-wide anthem printed on an Aura, or None.

    "As long as enchanted land is a basic Mountain, Goblin creatures get +0/+2."
    (Goblin Caves.) An Aura is a permanent, so a lord buff on one is applied by
    ``_recalculate_lord_buffs`` exactly as a lord buff on a creature is — the
    condition is what makes it about the enchanted permanent, and
    ``engine/lord_buffs.py`` refuses a condition
    ``conditional_static_holds`` cannot answer rather than dropping it.

    Deliberately **not** in :func:`aura_continuous_claim`. That function tells
    the grammar's parse claim "the engine already applies this line, do not
    lower it"; here the opposite is true — the line has to lower, because the
    ``lord_buff`` instruction is what the recompute reads. A claim in the wrong
    one of the two would leave the Aura supported with no instruction behind it.
    """
    from .lord_buffs import lord_buff_for

    if lord_buff_for(normalized_line) is None:
        return None
    return "board-wide anthem — lord_buffs, applied by _recalculate_lord_buffs"


#: The instruction kinds a *static* line printed about the attached permanent
#: may lower to, and the pass that applies each one. Keyed by the kind, because
#: what makes the sentence the host's is one shared payload key —
#: ``subject: "attached"`` — and a claim that read the key without checking the
#: kind would approve any future instruction carrying it, applied by nobody.
#:
#: Two rows, one per printed shape: a delta gated on criteria (Ice Age's five
#: Scarabs) and a delta whose *size* is a count (Vampirism). They are one claim
#: rather than two functions because the question is identical — does the P/T
#: refresh read this instruction on this permanent's behalf — and two copies of
#: it would drift the way every other pair this module has retired did.
_ATTACHED_STATIC_KINDS: dict[str, str] = {
    "conditional_static": (
        "conditional static on the enchanted permanent — lowered by the "
        "grammar, applied by _refresh_dynamic_creatures (P/T) and "
        "_recalculate_lord_buffs (keywords)"
    ),
    "dynamic_pt_bonus": (
        "counted layer-7c bonus on the enchanted permanent — lowered by the "
        "grammar, applied by _refresh_dynamic_creatures"
    ),
}


def aura_conditional_static_claim(normalized_line: str) -> str | None:
    """Name the code behind a static line about the *enchanted* permanent, or None.

    "Enchanted creature gets +N/+N as long as …" (Ice Age's five Scarabs) and
    "Enchanted creature gets +1/+1 for each other creature you control"
    (Vampirism). Like :func:`aura_anthem_claim` and unlike
    :func:`aura_continuous_claim`, this claim says **the line must lower**: the
    instruction carrying ``subject: "attached"`` is what the P/T refresh reads,
    so a claim on the other side would leave the Aura supported with nothing
    behind the sentence.

    Asked of the grammar rather than of a pattern here, which is the point of
    lowering it there: "an opponent controls a black permanent" has one reader
    (``subject_matches``, through the condition lowering), and a regex in this
    file would be a second one free to disagree about what a black permanent is.
    The same argument covers the count: "other creature you control" is the
    noun parser's phrase, evaluated by ``evaluate_count``, and a second reading
    of it here could disagree about which creatures "other" excludes.
    """
    from .grammar import ast as grammar_ast
    from .grammar import compile_line

    compiled = compile_line(normalized_line)
    if compiled.parse_error is not None or compiled.lowering_error is not None:
        return None
    if not isinstance(compiled.node, grammar_ast.StaticAbilityNode):
        return None
    for instruction in compiled.instructions:
        if instruction.payload.get("subject") != "attached":
            continue
        claim = _ATTACHED_STATIC_KINDS.get(instruction.kind)
        if claim is not None:
            return claim
    return None


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
    from .handlers import EFFECT_HANDLERS

    if cond == "leaves_battlefield" and kind in EFFECT_HANDLERS:
        # "When this Aura leaves the battlefield, it deals 1 damage to each
        # Goblin creature." (Goblin Shrine.) CR 603.6c's ability, announced from
        # the one transition off the battlefield
        # (``mixins/helpers.remove_all_from_battlefield``) rather than from the
        # forty callers that move a permanent — which is why the claim can be
        # made for any Aura, not just one whose host was destroyed.
        return (
            "the Aura's own leaves-the-battlefield trigger (CR 603.6c) — "
            "mixins/helpers.remove_all_from_battlefield"
        )
    if cond == "last_counter_removed" and kind in EFFECT_HANDLERS:
        # "When the last ore counter is removed from this Aura, destroy
        # enchanted land and this Aura deals 2 damage to that land's
        # controller." (Orcish Mine.) CR 122.1's event, announced from the
        # state-based sweep in ``mixins/game_ending.py`` rather than from the
        # four call sites that take a counter off — which is what makes the
        # claim true for *any* permanent printing the condition, not only one
        # whose counters a particular path removes. Divine Intervention already
        # rode it; this is the same dispatcher asked by an Aura.
        return (
            "the last-counter-removed trigger (CR 122.1) — "
            "mixins/game_ending.py's counter sweep"
        )
    if cond == "attackers_declared" and kind in EFFECT_HANDLERS:
        # "Whenever all non-Wall creatures you control attack, enchanted
        # creature gets +X/+0 until end of turn." (Mob Mentality.) CR 508.1's
        # declaration, announced through the event bus by
        # ``phases/declare_attackers_step.py`` — which scans **every**
        # permanent whose compiled trigger matches, not only the creatures in
        # the declaration, so an Aura watching its controller's attack is
        # announced like any other observer.
        #
        # Its own row rather than a widening of the ones above for their
        # reason: each names one condition and the site that fires it, and a
        # claim that could not name a site is the wildcard this function
        # replaced.
        return (
            "the attack-declaration trigger (CR 508.1) — "
            "phases/declare_attackers_step.py"
        )
    if cond == "self_becomes_target" and kind in EFFECT_HANDLERS:
        # "When enchanted creature becomes the target of a spell or ability,
        # destroy that creature." (Spinal Graft.) CR 603.2's announcement, made
        # from `mixins/helpers._announce_targeting` — the boundary where an
        # object is put on the stack with its targets settled (CR 601.2c /
        # 602.2b), which is one site for a spell and an ability alike.
        #
        # Reached only when `attached_trigger_claim` above did not already
        # claim the line, which for an Aura it does; the row is here so the
        # dispatcher is *named* for the shape rather than left to that
        # broader claim, which asks only whether an instruction came out.
        return (
            "the targeting trigger (CR 603.2) — "
            "mixins/helpers._announce_targeting"
        )
    if cond == "creature_dies" and kind in EFFECT_HANDLERS:
        # "Whenever a creature dies, put a +1/+1 counter on enchanted creature."
        # (Sadistic Glee.) CR 603.2's announcement of a death, made from the one
        # site every death passes through — and that site scans
        # ``permanents_with_controller()``, so an Aura watching the whole board
        # is enqueued exactly like a creature watching it. This is the row the
        # card needed and the only thing it needed: the line parses, lowers and
        # reaches a real handler, and the gate refused it for want of a claim.
        #
        # Its own row rather than a widening of the ones above, for their
        # stated reason: each names one condition and the site that fires it.
        return (
            "the creature-death trigger (CR 603.2) — "
            "mixins/helpers._fire_creature_dies_triggers"
        )
    if cond == "dies" and kind in EFFECT_HANDLERS:
        # "When this Aura is put into a graveyard from the battlefield, return
        # it to its owner's hand." (Brilliant Halo, Despondency, Fiery Mantle,
        # Fortitude, Launch, Spreading Algae.) CR 700.4's "dies", spelled long
        # -- the permanent's *own* death, announced from
        # ``_permanent_to_graveyard`` while the dying permanent is still in
        # hand, which is what makes the claim true for an Aura and not only for
        # a creature.
        #
        # It is the sibling of the ``creature_dies`` row above and separate for
        # that row's stated reason -- each names one condition and the site that
        # fires it. The pairing matters here: ``creature_dies`` is the
        # board-wide scan and this is the source's own death, and an Aura is
        # reached by exactly one of them.
        return (
            "the permanent's own death (CR 700.4) - "
            "mixins/helpers._permanent_to_graveyard"
        )
    if cond in ("spell_cast", "opponent_casts_spell") and kind in EFFECT_HANDLERS:
        # "Whenever an opponent casts a creature spell, put a +1/+1 counter on
        # enchanted creature." (Predatory Hunger.) CR 601.2i's announcement,
        # made from the one site every cast passes through
        # (``mixins/oracle_instructions._apply_spell_cast_any_triggers``, called
        # as the object goes on the stack) — and that site emits through the
        # event bus, which scans every permanent whose compiled trigger matches
        # rather than only the caster's, so an Aura watching the table is
        # enqueued exactly like the Rod/Cup/Sphere cycle's artifacts are.
        #
        # Both spellings of the announcement in one row, because one fire site
        # makes both and the printed word is the trigger's own narrowing
        # (``engine/events._opponent_casts_spell_filter``) rather than a second
        # dispatcher. Its own row rather than a widening of the ones above, for
        # their stated reason: each names one condition and the site that fires
        # it.
        return (
            "the spell-cast trigger (CR 601.2i) — "
            "mixins/oracle_instructions._apply_spell_cast_any_triggers"
        )
    from .phases.upkeep_effects import UPKEEP_EFFECTS

    if (cond, kind) in UPKEEP_EFFECTS:
        return f"registered upkeep pair ({cond}, {kind}) — phases/upkeep_effects.py"
    from .phases.upkeep_step import _ORDINARY_UPKEEP_SEATS

    # Asked of the upkeep step's own table rather than a copied list of its
    # members. The copy here read ``("upkeep_self", "upkeep_each")`` while the
    # step had grown a third condition, which is the drift this file's other
    # comments keep describing — a gate and a dispatch reading two spellings of
    # one rule, where the gate's is the smaller and so refuses cards the engine
    # can actually play.
    if cond in _ORDINARY_UPKEEP_SEATS and kind in EFFECT_HANDLERS:
        return "ordinary upkeep trigger (CR 603.3) — phases/upkeep_step.py"
    from .phases.end_step import END_STEP_CONDITIONS

    # The end step's own table, asked the way the upkeep step's is one line up.
    # "At the beginning of the end step of enchanted creature's controller,
    # destroy that creature if it didn't attack this turn" (Aggression) is a
    # CR 603.3 trigger with an ordinary handler behind it, and the end step
    # enqueues every condition in that set whatever the effect turned out to be.
    if cond in END_STEP_CONDITIONS and kind in EFFECT_HANDLERS:
        return "end-step trigger (CR 603.3) — phases/end_step.py"
    return None


def modal_trigger_run_claim(
    normalized_lines: list[str], index: int, card_name: str = "",
) -> str | None:
    """Name what carries out the modal trigger whose head sits at *index*.

    A modal triggered ability is printed as a head and a run of bullets, and
    the bullets are *not* effect lines of their own — the same grouping
    ``oracle._modal_trigger_ability`` performs when it builds the ability.
    Asking this gate line by line reads the head as an ordinary attached
    trigger (claimed, correctly) and then each bullet as an unclaimed effect,
    so Relic Bind reported "unimplemented aura effect: • this aura deals 1
    damage to …" for a line the trigger already owns.

    The claim is the *builder's own answer*, not a shape test: it asks
    ``_modal_trigger_ability``, which refuses a dead mode and a condition it
    cannot read. So an Aura whose modes the engine cannot perform stays
    unclaimed and visibly unsupported, which is the whole reason this file
    stopped claiming attached triggers with a wildcard.
    """
    from .oracle import _modal_trigger_ability

    built = _modal_trigger_ability(normalized_lines, index, card_name or None)
    if isinstance(built, tuple):
        return "modal attached trigger — oracle._modal_trigger_ability"
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

    A **bulleted run under a modal head is one line**, for the same reason: the
    bullets are modes of the trigger above them, not effects the Aura has
    beside it. They are skipped only when
    :func:`modal_trigger_run_claim` says the whole run is carried out.
    """
    from .oracle import _bullets_after

    unclaimed: list[str] = []
    index = 0
    while index < len(normalized_lines):
        line = normalized_lines[index]
        bullets = _bullets_after(normalized_lines, index)
        if bullets and not line.startswith("•"):
            if modal_trigger_run_claim(normalized_lines, index, card_name) is None:
                unclaimed.append(line)
            index += 1 + len(bullets)
            continue
        if line and not _aura_line_claimed(line, card_name):
            unclaimed.append(line)
        index += 1
    return unclaimed


def aura_claim(normalized_lines: list[str], card_name: str = "") -> str | None:
    """``"auras"`` when this card is an Aura this module implements in full.

    The **positive** half of :func:`unclaimed_aura_lines`, and the reason it had
    to exist: this module was a refusal and never an approval. It could say an
    Aura's effect line was unimplemented, but nothing here said that a fully
    implemented Aura *was* implemented — so the support gate got that from a
    substring, ``"enchant creature"`` in ``SUPPORTED_SPELL_PATTERNS``, and an
    Aura was supported because its text contained two words.

    Armor of Thorns is what that cost. Its clause is "Enchant **nonblack**
    creature", which the literal never matched, so the card was carried by
    ``"gets +"`` instead — a different substring, matching a different line, for
    a card this module claims in full. The support of an Aura had nothing to do
    with whether the Aura worked.

    Three conditions, and the third is the one a substring can never ask:

    * the card prints an ``Enchant <subject>`` line at all;
    * **every** line is claimed — the same question ``unclaimed_aura_lines``
      answers, so the approval and the refusal cannot disagree;
    * at least one *effect* line exists. An Aura whose only line is the enchant
      clause does nothing when it attaches, and would otherwise be approved for
      having no effects to fail on. No card in the pool is shaped that way,
      which is what makes requiring it free.
    """
    if not any(line.startswith("enchant ") for line in normalized_lines):
        return None
    if unclaimed_aura_lines(normalized_lines, card_name):
        return None
    effects = [
        line for line in normalized_lines
        if line and not line.startswith("enchant ")
    ]
    return "auras" if effects else None


def _enchant_line_claimed(line: str) -> bool:
    """Whether an ``Enchant <subject>`` line has both its readers behind it.

    Two, because the clause is answered in two places and either one missing is
    a hole: ``targeting.enchant_line_subject`` is what the *picker* is built
    from, and the graveyard form beside it
    (``targeting.enchant_graveyard_line``) is the other zone's picker, raised by
    ``_cast_target_spec`` and spent by ``_apply_aura_effect``. Anything else
    starting with the word is a subject nobody reads, and a line nobody reads is
    what leaves this gate.
    """
    from .targeting import enchant_graveyard_line, enchant_line_subject

    return (
        enchant_line_subject(line) is not None or enchant_graveyard_line(line)
    )


def _aura_line_claimed(line: str, card_name: str) -> bool:
    """Whether one Aura/Equipment effect line has an implementation behind it."""
    from .oracle import _is_supported_keyword_line
    from .alternative_costs import alternative_cost_claims_line
    from .cast_costs import cast_cost_claims_line
    from .cast_timing import cast_permission_line
    from .enter_effects import enter_effect_line
    from .target_restrictions import target_restriction_line

    return bool(
        # The "Enchant <subject>" line, asked of the readers that **implement**
        # it rather than of the word it starts with. `startswith("enchant ")`
        # was this file's own widened gate (ICE 36's rule, one module over): it
        # claimed any subject at all, so Roots' "Enchant creature without
        # flying" compiled supported while `targeting.enchant_subject_spec`
        # derived no picker — the card was uncastable — and
        # `permanent_matches_enchant_noun` fell through to its permissive
        # fallback, so the exclusion was unenforced. One line, two contradictory
        # failures, and a green suite.
        _enchant_line_claimed(line)
        or _is_supported_keyword_line(line)
        # "This Equipment enters with a soul counter on it." (Malefic Scythe.)
        # Entry state `_initialize_permanent_state` carries out from the
        # permanent's own text as it arrives — not an effect it has while
        # attached, so it is claimed by the table that performs it rather than
        # by an effect template here. Equipment reach this gate since the
        # compiler started holding them to it; an Aura printing an entry line
        # the table reads is claimed the same way.
        or enter_effect_line(line) is not None
        # "You can't choose an untapped creature as this spell's target as you
        # cast it." (Enthralling Hold.) Not an effect the Aura has while it is
        # attached — it is spent as the spell is cast (CR 601.2c) — so it is
        # claimed by the table that enforces it rather than added to the effect
        # templates, which would put a line with no continuous behaviour behind
        # them. Asked as the same reader the cast path calls, so a phrase the
        # matcher cannot answer leaves the line unclaimed and the card
        # unsupported rather than admitted with the restriction absent.
        or target_restriction_line(line)
        # "You may cast this card from your graveyard by paying 3 life and
        # discarding a card in addition to paying its other costs." (Demonic
        # Embrace.) Not an effect the Aura has while attached and not a
        # restriction on its targeting — it is a cost and a permission, both
        # read off this same line by the two tables that charge and open them.
        # Asked as those tables rather than listed here, so a clause they cannot
        # charge leaves the line unclaimed and the card unsupported.
        or cast_cost_claims_line(line)
        # "If you control a Plains, you may tap an untapped creature you control
        # rather than pay this spell's mana cost." (Lashknife.) CR 118.9's
        # alternative cost, the other half of the price the line above reads —
        # paid *rather than* the mana cost where that one is paid beside it, and
        # spent as the spell is cast (CR 601.2b/601.2h), so it is no effect the
        # Aura has while attached. Asked as the table that offers, gates and
        # charges it, so a clause that table refuses leaves the line unclaimed
        # and the Aura unsupported rather than castable at a price nobody reads.
        or alternative_cost_claims_line(line)
        # "You may cast this spell as though it had flash. If you cast it any
        # time a sorcery couldn't have been cast, …" (Mirage's five-Aura cycle.)
        # A *timing permission* plus the penalty printed with it — neither an
        # effect the Aura has while attached nor a restriction on its targeting,
        # so it is claimed by the table that opens and enforces it. All or
        # nothing there: the permission alone would ship an Aura that can be
        # flashed in and never sacrificed, which is a strictly better card than
        # the one printed.
        or cast_permission_line(line)
        or aura_effect_claim(line, card_name) is not None
    )


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


#: A line that is **not** a static ability, however much of one its middle
#: looks like. A continuous grant is derived from an Aura's text on every
#: recompute, so it may only be read off a line that is continuously true: a
#: triggered ability's effect is a one-shot (CR 603.1) and an activated
#: ability's is spent when it resolves (CR 602.1), and reading either as a
#: static grant applies it *before the ability has done anything* and never
#: stops.
#:
#: Bestial Fury is the card. "Whenever enchanted creature becomes blocked, it
#: gets +4/+0 and gains trample until end of turn" was read here as a permanent
#: +4/+0: the enchanted creature got it the moment the Aura attached, kept it
#: through the opponent's turns, and got a *second* +4/+0 on top whenever it was
#: actually blocked. The trample half was correct — the keyword reader below
#: takes only whole "…has <keyword>" lines — so one printed sentence had one
#: half continuous and one half not, which is the shape that makes this kind of
#: bug invisible in a game.
_NON_STATIC_LINE = re.compile(r"^(?:when|whenever|at the beginning|at end of)\b")


def _static_ability_line(line: str) -> bool:
    """Whether *line* is a static ability, and so may be read as a continuous
    grant at all.

    An activated ability is caught by the colon its cost ends at (CR 602.1),
    which is the same delimiter ``_parse_activated_ability`` splits on — asked
    here as the shape rather than by calling that parser, because the question
    is only "is there a cost in front of this", and a line whose *effect* the
    compiler cannot read is still not a static ability.
    """
    if _NON_STATIC_LINE.match(line):
        return False
    return ":" not in line.split(" gets ")[0]


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
        # Only a static ability grants continuously — see `_NON_STATIC_LINE`.
        if not _static_ability_line(line):
            continue
        tail = line[match.end():].lstrip()
        # The duration, wherever in the tail it is printed. `_STATIC_PT_GRANT`'s
        # own lookahead and this check both used to require it immediately after
        # the numbers, so "gets +4/+0 **and gains trample** until end of turn"
        # slipped between them and was read as permanent. Two readers of one
        # clause, and the sentence only has to put a word between them to defeat
        # both.
        if "until end of turn" in tail:
            continue
        # "…gets +2/+2 **as long as an opponent controls a black permanent**"
        # (Ice Age's five Scarabs), and "for as long as this artifact remains
        # tapped". A conditional grant is not a flat one, and this pattern
        # matches the prefix of both — so answering here would attach the bonus
        # unconditionally, which is the condition-dropping bug the per-counter
        # decline above exists for. The conditional grant lowers to a
        # ``conditional_static`` instruction instead (grammar/statics.py) and
        # the P/T refresh asks the condition on every recompute.
        if re.match(r"(?:for )?as long as\b", tail):
            continue
        # "…gets +3/+3 **unless it shares a color with the most common color**
        # …" (Heroic Defiance). "As long as" with the polarity printed the
        # other way round, and the same decline for the same reason: the line
        # lowers to a ``conditional_static`` whose complement arm carries the
        # delta, so answering the prefix here grants a flat +3/+3 on top of it
        # — the bonus the card says it does *not* give is given, and the one it
        # does give is doubled.
        if re.match(r"unless\b", tail):
            continue
        # "...gets +1/+1 **for each other creature you control**" (Vampirism).
        # A *counted* grant, which is a different kind of answer from the
        # constant this function knows how to give - and this pattern matches
        # its prefix, so answering here would grant a flat +1/+1 **on top of**
        # the count the layer-7c refresh already contributes from the
        # ``dynamic_pt_bonus`` the line lowers to: the enchanted creature came
        # out one point too big in each half.
        #
        # The same decline ``aura_pt_grant_per_counter`` gets at the top of this
        # function, widened from the one multiplier that had a card to the
        # printed clause itself. "For each" says the size is a count, whatever
        # is counted, and a multiplier this reader cannot see is one it must not
        # answer past.
        if re.match(r"for each\b", tail):
            continue
        return int(match.group(1)), int(match.group(2))
    return None


#: Snowblind: "Enchanted creature gets -X/-Y. If that creature is attacking, X
#: is the number of snow lands defending player controls. Otherwise, X is the
#: number of snow lands its controller controls. Y is equal to X or to enchanted
#: creature's toughness minus 1, whichever is smaller."
#:
#: Four sentences, one effect, and every one of them is load-bearing: the count,
#: the two boards it can be counted on, and the clamp. Matched together for the
#: reason ``_ABILITY_COST_REDUCTION`` above matches its pair together — the
#: clamp without the count modifies nothing, and the count without the clamp is
#: a card that kills what it enchants.
#:
#: The counted noun is payload, read by the grammar's own noun parser rather
#: than spelled here, so "snow lands" means on this card what it means on every
#: other line in the engine. The repeated phrase must be the *same* phrase: a
#: card counting two different things is not this sentence, and reading only
#: the first would give the second board the wrong count.
def _build_board_counted_penalty() -> re.Pattern[str]:
    return re.compile(
        r"^enchanted creature gets -x/-y\. "
        r"if that creature is attacking, x is the number of (?P<attacking>.+?) "
        r"defending player controls\. "
        r"otherwise, x is the number of (?P<otherwise>.+?) its controller "
        r"controls\. y is equal to x or to enchanted creature's toughness "
        r"minus 1, whichever is smaller$"
    )


_BOARD_COUNTED_PENALTY = _LazyPattern(_build_board_counted_penalty)


def aura_board_counted_penalty(oracle_text: str) -> dict | None:
    """The payload of Snowblind's clamped, board-counted penalty, or None.

    ``{"filter": <noun-phrase payload>}`` — what to count. Whose board it is
    counted on is not payload: the sentence says, and the answer changes with
    the combat, so it is asked at every recompute by
    ``permanent_state._refresh_board_counted_penalties``.

    The noun phrase is refused unless ``subject_matches`` can test it, the same
    gate every other text-keyed table applies: a narrowing the matcher cannot
    answer would be dropped, and a dropped narrowing here counts *every land*
    rather than the snow ones.
    """
    from .grammar import subject_filter_payload
    from .subject_filters import untestable_filter_keys

    for raw_line in (oracle_text or "").splitlines():
        match = _BOARD_COUNTED_PENALTY.match(_line_text(raw_line))
        if match is None:
            continue
        phrase = match.group("attacking").strip()
        if phrase != match.group("otherwise").strip():
            return None
        described = subject_filter_payload(phrase, plural=True)
        if not described or untestable_filter_keys(described):
            return None
        return {"filter": described}
    return None


def aura_board_counted_penalty_sentences(oracle_text: str) -> tuple[str, ...]:
    """The sentences :func:`aura_board_counted_penalty` reads, or empty.

    Snowblind's effect is **four sentences on one printed line** and none of
    them means anything alone: the penalty, the two boards it can be counted on,
    and the clamp. So the reader matches them joined, and this names the run for
    a caller that walks a card sentence by sentence
    (``scripts/parse_coverage.py``) and would otherwise report all four as text
    nothing read. The same pairing :func:`aura_cost_reduction_sentences` keeps
    for Power Artifact, which is the other reader shaped this way.
    """
    if aura_board_counted_penalty(oracle_text) is None:
        return ()
    for raw_line in (oracle_text or "").splitlines():
        line = _line_text(raw_line)
        if _BOARD_COUNTED_PENALTY.match(line) is None:
            continue
        return tuple(
            sentence.strip() for sentence in line.split(". ") if sentence.strip()
        )
    return ()


def auras_attached_to(permanent) -> list:
    """Every Aura currently attached to *permanent*, in attachment order.

    ``attached_aura`` is a single slot that a second Aura overwrites, so it
    cannot answer this: a creature can carry any number of Auras (CR 303.4).
    The list is the authority; the slot is kept in step for the callers that
    only ever want "an" Aura.
    """
    return list(permanent.metadata.get("attached_auras") or [])


def attached_subject_triggers(game, host, condition_kinds, payload_key):
    """``(seat, attachment, trig)`` for every trigger of something attached to
    *host* whose condition is about the permanent it is attached to.

    The combat fire sites scan a creature's **own** ``effective_card``, and an
    attached Aura's abilities are not on it — an Aura's ability is the Aura's,
    controlled by the Aura's controller (CR 113.7a), not a granted ability of
    its host. So an Aura printing "whenever enchanted creature attacks or
    blocks" (Imprison) is invisible to those scans, exactly as "when enchanted
    creature dies" was until ``mixins/helpers.py`` grew the branch this
    function generalises.

    *payload_key* is the narrowing the condition's own table wrote when it read
    the word "enchanted" — so a trigger printed about "this creature" is not
    picked up here and one printed about the attachment's host is not picked up
    by the host's own scan. One condition kind, two dispatch scopes, and the
    payload is what tells them apart.
    """
    from .trigger_utils import matching_triggers

    found = []
    for attachment in auras_attached_to(host):
        seat = game.controller_index_of(attachment)
        if seat is None:
            continue
        for trig in matching_triggers(
            attachment.effective_card, condition_kinds=condition_kinds
        ):
            noun = trig.condition.payload.get(payload_key)
            if not noun:
                continue
            # The printed noun is tested rather than assumed: "enchanted
            # **creature** attacks" is not satisfied by an Equipment on an
            # artifact that an animation has not made a creature (CR 613
            # layer 4), and a word consumed and never read is a word that
            # could be deleted.
            if not host.has_type(str(noun)):
                continue
            found.append((seat, attachment, trig))
    return found


#: What a permanent that *became* an Aura was given (Necromancy). The record the
#: sentence "it becomes an Aura with "enchant <quality>."" leaves behind: the
#: subtype is CR 613 layer 4 and goes on ``layer_bridge.GAINED_TYPES`` like any
#: other gained type, and this is the other half — the enchant ability (CR 702.5)
#: that says what the permanent may legally be attached to.
#:
#: A record rather than a granted text line, because the readers of an enchant
#: clause ask two different things of it: ``aura_enchant_noun`` reads a *card*
#: and gates on the printed word "Aura" in its type line, which a permanent that
#: became one does not have, and the quality this sentence grants is a relation
#: between two permanents rather than a noun a card's text could state.
#: :func:`enchant_card_refusal` — the one predicate every caller asks — reads it.
BECAME_AURA_ENCHANT = "became_aura_enchant"

#: The permanent whose ability put this one onto the battlefield, by id. What
#: "enchant creature **put onto the battlefield with Necromancy**" is about, and
#: the only thing that can say so: the creature was a card in a graveyard when
#: the ability was activated, and CR 400.7 makes what arrived a new object, so
#: nothing on the board or on the stack records where it came from.
#:
#: Stamped by ``handlers/zones.reanimate_creature``, read by
#: :func:`enchant_card_refusal`. Beside the record above rather than in the
#: handler that writes it, for ``tokens.CREATED_WITH_PERMANENT_ID``'s reason:
#: the writer and the reader sit at opposite ends of the pipeline.
PUT_ONTO_BATTLEFIELD_BY = "put_onto_battlefield_by"

#: The mark a layer-4 record carries when :func:`end_became_aura_effect` is the
#: thing that will take it away again. Necromancy's Aura is permanent and
#: carries none; a Licid's is a continuous effect its controller may pay to end
#: (CR 116.2c), so the records that effect wrote have to be findable again —
#: and findable *exactly*, because a permanent may have gained a type from
#: something else in between.
BECAME_AURA_RECORD = "from_became_aura"


def end_became_aura_effect(game, permanent) -> bool:
    """Undo what ``become_aura_with_enchant`` did to *permanent*. CR 116.2c.

    "You may pay {C} to end this effect" (Tempest's five Licids). The effect is
    everything that one instruction recorded — the gained enchantment type and
    Aura subtype (CR 613 layer 4), the creature type and creature subtypes it
    replaced (CR 205.1a), the ability it took away (layer 6) and the enchant
    clause it granted (CR 702.5) — so ending it is dropping exactly those
    records and nothing else. Nothing is *restored*: every one of them is a
    contribution, so the permanent goes back to being what its printed card says
    by the contribution ceasing to exist, which is the same shape
    ``detach_aura`` has one screen up.

    The attachment goes with it. An Aura that stopped being an Aura is not
    attached to anything (CR 301.5f's word only means something while the
    permanent is an Attachment), and leaving the record would make the host go
    on counting a creature among its Auras.

    Returns whether there was an effect to end.
    """
    from .keywords import restore_ability_line
    from .layer_bridge import GAINED_TYPES, LOST_TYPES

    record = permanent.metadata.pop(BECAME_AURA_ENCHANT, None)
    if record is None:
        return False
    host = permanent.metadata.get("attached_to")
    if host is not None:
        detach_aura(permanent, host)
    for key in (GAINED_TYPES, LOST_TYPES):
        entries = permanent.metadata.get(key)
        if not entries:
            continue
        kept = [entry for entry in entries if not entry.get(BECAME_AURA_RECORD)]
        if kept:
            permanent.metadata[key] = kept
        else:
            permanent.metadata.pop(key, None)
    line = record.get("ability_line")
    if line:
        restore_ability_line(permanent, str(line))
    game._refresh_dynamic_creatures()
    return True


def _became_aura_offer(game, permanent):
    """What *permanent* is offering to end its became-an-Aura effect for, or None.

    The record is the effect: `become_aura_with_enchant` writes it and
    :func:`end_became_aura_effect` removes it, so "is the offer open?" and "is
    there anything to undo?" are one question with one answer.

    The **cost** comes out of that record rather than off the card, and it has
    to: the printed sentence sits inside the ability the same resolution took
    away (CR 613 layer 6), so by the time anyone can accept, the permanent no
    longer says it. CR 611.2a's effect outlives the ability that made it, and
    CR 116.2c's offer is part of the effect.
    """
    from .special_actions import SpecialActionOffer

    record = permanent.metadata.get(BECAME_AURA_ENCHANT)
    if not record:
        return None
    cost = record.get("end_cost")
    if not cost:
        return None
    seat = game.controller_index_of(permanent)
    if seat is None:
        return None
    # "**You** may pay" — the ability's controller (CR 109.5), which for a
    # permanent that turned itself into an Aura is whoever controls it now.
    return SpecialActionOffer(seat=seat, mana=dict(cost))


def _take_became_aura_offer(game, seat: int, permanent) -> None:
    if end_became_aura_effect(game, permanent):
        game.log.append(
            f"{game.players[seat].name} paid to end {permanent.card.name}'s "
            "effect (CR 116.2c): it is a creature again"
        )


#: The restriction names an Aura is currently *not* imposing, because the
#: permanent it is attached to bought a turn off them (CR 116.2d). Recorded on
#: the Aura and cleared by the cleanup step, like every other "until end of
#: turn" record in this engine — nothing is undone, the record simply stops
#: being there.
#:
#: The **names** rather than a flag on the Aura, because the printed offer says
#: "ignore **this effect**" and names one sentence: an Aura whose second
#: restriction line sat behind the offer would otherwise be suspended whole.
IGNORED_RESTRICTIONS = "ignored_restrictions_until_eot"

#: "That creature's controller may sacrifice a permanent of their choice for
#: that player to ignore this effect until end of turn." (Volrath's Curse.)
#: CR 116.2d, and the sentence in front of it is what "this effect" names —
#: which is why the pattern reads the noun: the offer is about the restriction
#: line above it, on the permanent that line is about.
_IGNORE_STATIC_OFFER = re.compile(
    r"^that (?P<noun>[a-z]+)'s controller may sacrifice a permanent of their "
    r"choice for that player to ignore this effect until end of turn$"
)


def aura_ignore_offer(oracle_text: str) -> frozenset[str] | None:
    """The restrictions an Aura's CR 116.2d offer suspends, or None.

    "This effect" is the sentence printed in front of the offer, so the two are
    read together: the restriction set comes from :func:`aura_restrictions` over
    the same line, which is the reader that will be asked to skip them. An offer
    printed against a sentence this file does not implement claims nothing —
    a suspension of a restriction nobody imposes is not an effect.
    """
    for raw_line in (oracle_text or "").splitlines():
        line = _line_text(raw_line)
        for index, sentence in enumerate(part.strip() for part in line.split(".")):
            if not sentence or _IGNORE_STATIC_OFFER.match(sentence) is None:
                continue
            preceding = ". ".join(
                part.strip() for part in line.split(".")[:index] if part.strip()
            )
            restrictions = aura_restrictions(preceding)
            return restrictions or None
    return None


def _ignore_static_offer(game, aura):
    """What *aura* is offering its host's controller (CR 116.2d), or None."""
    from .special_actions import SpecialActionOffer

    restrictions = aura_ignore_offer(aura.effective_card.oracle_text)
    if not restrictions:
        return None
    host = aura.metadata.get("attached_to")
    if host is None or not game.is_on_battlefield(host):
        return None
    if restrictions <= set(aura.metadata.get(IGNORED_RESTRICTIONS) or ()):
        # Already bought this turn. Offering it again would let a seat pay twice
        # for one turn's relief, which the printed duration does not do.
        return None
    seat = game.controller_index_of(host)
    if seat is None:
        return None
    # "…**a permanent** of their choice", which is CR 110.1's whole noun: an
    # empty filter is every permanent, and a narrower phrase on a later card is
    # the same field with data in it.
    return SpecialActionOffer(seat=seat, sacrifice={})


def _take_ignore_static_offer(game, seat: int, aura) -> None:
    restrictions = aura_ignore_offer(aura.effective_card.oracle_text) or frozenset()
    kept = set(aura.metadata.get(IGNORED_RESTRICTIONS) or ())
    aura.metadata[IGNORED_RESTRICTIONS] = sorted(kept | set(restrictions))
    game._refresh_dynamic_creatures()
    game.log.append(
        f"{game.players[seat].name} ignores {aura.card.name}'s effect until "
        "end of turn (CR 116.2d)"
    )


def clear_ignored_restrictions(permanent) -> bool:
    """CR 514.2's cleanup: an "until end of turn" suspension ends.

    Beside the other cleanup sweeps and swept the same way, because that is what
    the printed duration is. Returns whether anything was cleared.
    """
    return permanent.metadata.pop(IGNORED_RESTRICTIONS, None) is not None


def _register_became_aura_special_action() -> None:
    """Register CR 116.2c's offer, once.

    Guarded rather than bare, because `engine/special_actions.py` imports this
    module from inside its own seam to make sure the registration has happened —
    and a duplicate kind raises there by design.
    """
    from .special_actions import (PERMANENT_SPECIAL_ACTIONS,
                                  PermanentSpecialAction,
                                  register_permanent_special_action)

    if "end_own_continuous_effect" in PERMANENT_SPECIAL_ACTIONS:
        return
    register_permanent_special_action(PermanentSpecialAction(
        kind="end_own_continuous_effect",
        offer=_became_aura_offer,
        take=_take_became_aura_offer,
    ))
    register_permanent_special_action(PermanentSpecialAction(
        kind="ignore_attached_static_until_eot",
        offer=_ignore_static_offer,
        take=_take_ignore_static_offer,
    ))


_register_became_aura_special_action()


def _became_aura_refusal(game, aura, granted, host) -> str | None:
    """Why a permanent that *became* an Aura may not enchant *host*.

    (Necromancy: ``it becomes an Aura with "enchant creature put onto the
    battlefield with Necromancy."``) The clause was granted rather than printed,
    so it is read off the record :data:`BECAME_AURA_ENCHANT` holds instead of
    off the card's text — but it is asked here, inside the one predicate the
    cast gate, the pickers, the attach and the CR 704.5m sweep all share, so
    what is offered and what is allowed cannot drift.

    The origin rider is the whole of what the sentence adds, and it is tested
    rather than dropped: the Aura may enchant the creature *its own ability* put
    onto the battlefield and no other, so an effect that would move it
    (Enchantment Alteration) finds no legal host and CR 303.4j leaves it where
    it is. Left permissive — which is what an unread noun gets in
    ``permanent_matches_enchant_noun`` — the printed restriction would be
    enforced by nothing.
    """
    from .mixins.stack import permanent_matches_enchant_noun
    from .target_immunity import cannot_be_enchanted

    if host is None or not game.is_on_battlefield(host):
        return "it is no longer on the battlefield"
    noun = str(granted.get("noun") or "")
    if not permanent_matches_enchant_noun(host, noun):
        return f"it isn't a legal {noun}"
    if granted.get("origin") == "source" and (
        host.metadata.get(PUT_ONTO_BATTLEFIELD_BY) != aura.permanent_id
    ):
        return "it wasn't put onto the battlefield with this enchantment"
    if cannot_be_enchanted(host, by_aura=aura):
        return "it can't be enchanted"
    return None


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
    ``enchant_seat_satisfied`` is the seat half of the same clause (CR 702.5),
    and ``cannot_be_enchanted`` is CR 303.4's protection half.
    """
    if host is aura:
        return "an Aura can't enchant itself"
    return enchant_card_refusal(
        game, aura.effective_card, game.controller_index_of(aura), host, aura=aura
    )


def enchant_card_refusal(game, card, controller_seat, host, *, aura=None) -> str | None:
    """The same question asked of an Aura **card** rather than a permanent.

    "…chooses a creature that this card could enchant" (Takklemaggot) is asked
    while the Aura is in a graveyard: CR 704.5m put it there the moment the
    creature it enchanted left, and the trigger that asks resolves afterwards.
    There is no permanent to read a controller or an effective card off, so both
    are passed in — the ability's controller (CR 108.4a: a card in a graveyard
    has none of its own) and the card as printed.

    One body rather than two, because :func:`aura_attach_refusal` delegates
    here: the cast gate, the CR 704.5m sweep, two pickers and two resolutions
    all ask this, and a second copy is a second chance to disagree about what a
    legal host is.
    """
    from .mixins.stack import (aura_enchant_noun, enchant_seat_satisfied,
                               permanent_matches_enchant_noun)
    from .target_immunity import cannot_be_enchanted

    # An enchant ability the permanent was **given** rather than printed
    # (Necromancy). Asked first, because the printed reading below would find no
    # enchant line at all and refuse every host — the card has none, which is
    # exactly why its own sentence grants one.
    granted = aura.metadata.get(BECAME_AURA_ENCHANT) if aura is not None else None
    if granted is not None:
        return _became_aura_refusal(game, aura, granted, host)
    if host is None or not game.is_on_battlefield(host):
        return "it is no longer on the battlefield"
    noun = aura_enchant_noun(card)
    if noun is None:
        return f"{card.name} has no enchant ability"
    if not permanent_matches_enchant_noun(host, noun):
        return f"it isn't a legal {noun}"
    if not enchant_seat_satisfied(
        game, controller_seat, game.controller_index_of(host), noun
    ):
        return f"{host.card.name} is not {noun}"
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
    #
    # The **object's** timestamp, which is what the rule says is replaced
    # ("receives a new timestamp each time it becomes attached") — so every
    # static ability on the Aura or Equipment is ordered by the attachment
    # (CR 613.7a), not only the ones a collector remembered to read off the
    # metadata key beside it. That key keeps the same number for the layers
    # that still read it.
    aura.timestamp = next_timestamp()
    aura.metadata["aura_timestamp"] = aura.timestamp


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
# **Derived from the engine's one keyword registry, not spelled beside it.**
# This was a hand-written tuple and it had drifted in both directions, which is
# the standing failure mode of a second copy: it listed "shadow", which nothing
# in this engine implements, so an Aura granting it would have been admitted
# with the evasion silently absent; and it omitted menace, lifelink,
# deathtouch, indestructible, flash, hexproof, prowess and rampage, so an Aura
# granting any of those was refused for a mechanic the engine has.
#
# The exclusions are the same three `lord_buffs.grantable_keywords` makes, and
# for the same reason: protection, landwalk and "bands with other" are family
# words whose printed form carries a quality ("protection from red"), which the
# comma/"and" splitting below would cut in half. Landwalk's *members*
# ("swampwalk", …) are ordinary entries and stay.
# Lazily, for the reason `_LazyPattern` above exists: the registry lives in
# `engine.grammar.vocabulary` and the grammar package imports this module back,
# so reading it at import time is a cycle.
def _grantable_keywords() -> tuple[str, ...]:
    from .lord_buffs import grantable_keywords

    # Longest first: the alternation is matched against a printed run, and
    # "first strike" must be tried before "first" could ever be.
    return tuple(sorted(grantable_keywords(), key=len, reverse=True))


def _keyword_alternation() -> str:
    return "|".join(_grantable_keywords())

# "Enchanted creature gets +1/+0 and has flying **and first strike**" (Wings of
# Aesthir). The grant is a *list*: CR 702 keywords are independent abilities and
# a card printing two grants two, so reading only the first would ship an Aura
# giving half of what it prints — silently, since the line still matches. The
# splitting is `_keyword_list` below, which refuses a run it cannot read whole
# rather than keeping the part it understood.
_KEYWORD_GRANT = _LazyPattern(lambda: re.compile(
    rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? has "
    rf"(?P<keyword>(?:{_keyword_alternation()})"
    rf"(?:(?:, and |, | and )(?:{_keyword_alternation()}))*)$"
))


#: "Enchanted creature **loses** flying." (Mammoth Harness.) The exact mirror of
#: ``_KEYWORD_GRANT``, in the same layer and built out of the same alternation —
#: which is the point: a word the Aura may grant is a word it may take away, and
#: two vocabularies would let one of them drift. The optional P/T prefix is the
#: same split every other pattern in this file makes, so "gets +2/+2 and loses
#: flying" is one line read into two channels rather than a line matching
#: nothing.
#:
#: Its own pattern rather than an optional verb inside the grant's, because the
#: two are **opposite contributions to one layer** (CR 613.4/613.9) and the
#: consumer has to be able to tell them apart: folded together, "loses flying"
#: would come back through ``aura_keyword_grants`` and hand the host the very
#: ability the Aura removes. The same reason ``lord_buffs.LordBuff`` keeps
#: ``lost_keywords`` beside ``keywords`` instead of signing one list.
_KEYWORD_REMOVAL = _LazyPattern(lambda: re.compile(
    rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? loses "
    rf"(?P<keyword>(?:{_keyword_alternation()})"
    rf"(?:(?:, and |, | and )(?:{_keyword_alternation()}))*)$"
))


_COMPOUND_INDESTRUCTIBLE = re.compile(
    rf"^enchanted {_NOUN} has indestructible and can't be enchanted by other auras$"
)


#: "Enchanted creature has phasing **and can't be blocked except by Walls**."
#: (Cloak of Invisibility.) One printed line carrying two effects in two
#: channels — a layer-6 keyword grant and a CR 506 combat restriction — which is
#: the shape ``_COMPOUND_INDESTRUCTIBLE`` above and ``_TYPE_ADDITION_GRANT``
#: already have, and for their reason: each half already has a reader, and the
#: line matching neither pattern whole is what left the card unsupported with
#: both of its halves individually working.
#:
#: Neither half is spelled out. The keyword run goes to the same
#: ``_keyword_list`` every other grant uses and the restriction tail goes to
#: ``combat_restrictions.combat_restriction_for`` — the table that already reads
#: that sentence when a creature prints it about itself — so a card printing
#: "has flying and can't be blocked by Walls" is this rule with nothing added.
#: A tail that table cannot read leaves the whole line unmatched and the card
#: unsupported, rather than granting the keyword and dropping the restriction:
#: a restriction the card prints and no combat step asks about is an ability
#: that works more often than the card allows, which is the quiet direction.
_KEYWORD_GRANT_AND_RESTRICTION = _LazyPattern(lambda: re.compile(
    rf"^{_ATTACHED} (?P<noun>{_NOUN}) has "
    rf"(?P<keyword>(?:{_keyword_alternation()})"
    rf"(?:(?:, and |, | and )(?:{_keyword_alternation()}))*) "
    rf"and (?P<restriction>can't .+)$"
))


#: "Enchanted creature gets +1/+1 **and can't be blocked except by creatures
#: with flying**." (Treetop Bracers.) The P/T twin of the keyword compound
#: above: a layer-7c grant and a CR 509.1b restriction on one printed line. The
#: grant half is already read by :func:`aura_static_pt_grant`, which searches
#: the line for its numbers and declines only a tail that makes the grant
#: something other than flat (a duration, a condition, a count) — a restriction
#: is none of those. So what was missing was only the restriction half's
#: reader, and this hands it to :func:`aura_combat_restriction` through the one
#: splitter both compounds share.
_PT_GRANT_AND_RESTRICTION = re.compile(
    rf"^{_ATTACHED} (?P<noun>{_NOUN}) gets [+-]\d+/[+-]\d+ "
    rf"and (?P<restriction>can't .+)$"
)


def _compound_restriction_clause(normalized: str):
    """The ``(noun, restriction clause)`` a compound line carries, or None.

    Split out because both halves of the compound are read by different
    functions — the keyword by :func:`aura_keyword_grants` (or the P/T by
    :func:`aura_static_pt_grant`), the tail by :func:`aura_combat_restriction`
    — and a second copy of the pattern in each is exactly the two-lists-one-rule
    shape this file's other comments record removing.
    """
    match = (
        _KEYWORD_GRANT_AND_RESTRICTION.match(normalized)
        or _PT_GRANT_AND_RESTRICTION.match(normalized)
    )
    if match is None:
        return None
    return match.group("noun"), match.group("restriction")

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
_CONDITIONAL_KEYWORD_GRANT = _LazyPattern(lambda: re.compile(
    rf"^{_ATTACHED} {_NOUN} has "
    rf"(?P<keyword>{_keyword_alternation()}) "
    r"as long as it's (?P<state>untapped|tapped)$"
))


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


# 'Enchanted land has "{T}: Counter target spell if it would destroy a land you
# control."' (Equinox.) A whole printed *ability*, not a keyword — so what the
# host gains is the line, and the compiler is what turns a line into an ability.
# The same channel a board-wide static's granted ability already travels on
# (`engine/global_statics.py`), for the same reason: nothing downstream of the
# compiler knows a word for "counter target spell if …".
#: The optional P/T prefix is the same split ``_KEYWORD_GRANT`` and the untap
#: restriction make, and it was missing here. Infernal Scarring prints
#: "Enchanted creature gets +2/+0 and has "When this creature dies, draw a
#: card."" — one line, two channels — and the anchored pattern matched neither
#: the whole line nor its tail, so the card reported supported, applied the
#: +2/+0, and granted **nothing**: the claim came from the P/T row of
#: ``_TEMPLATES``, which is checked first and says "and optional granted
#: keyword or ability" without asking whether anything grants one.
_QUOTED_ABILITY_GRANT = re.compile(
    rf'^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? has "(?P<ability>[^"]+)"$'
)


@lru_cache(maxsize=None)
def aura_quoted_grants(oracle_text: str) -> tuple[str, ...]:
    """Every ability *oracle_text* grants its host in quotes, **as printed** —
    whether or not the engine can read it.

    The half of :func:`aura_granted_ability_lines` that is a pure function of
    the text, for the reason ``_conditional_ability_grant_shapes`` is split
    from its own compile check: what the card *says* is cacheable here, and
    whether it compiles is ``granted_ability_supported``'s answer, held in a
    cache ``clear_compilation_caches`` knows about. It is also the reader a
    census wants — one that asked the filtered list below how many grants were
    unreadable would always be told none.
    """
    quotes: list[str] = []
    for raw_line in (oracle_text or "").splitlines():
        match = _QUOTED_ABILITY_GRANT.match(_line_text(raw_line))
        if match is not None:
            quotes.append(match.group("ability"))
    return tuple(quotes)


def quoted_grant_readable(quote: str, granter_name: str | None = None) -> bool:
    """Whether the host will be able to read *quote* once it is folded on.

    The one question both ends ask: the support gate
    (:func:`aura_effect_claim`), so an Aura whose quote the compiler refuses is
    not reported supported, and the fold (:func:`aura_granted_ability_lines`),
    so such a quote is never handed to a host. Bound first, because the quote
    is compiled on the *host* and the granter's own name means nothing there
    until ``bind_granter`` has said which object it is (CR 201.5a).
    """
    from .granted_abilities import bind_granter, granted_ability_supported

    return granted_ability_supported(bind_granter(quote, granter_name))


def aura_granted_ability_lines(
    oracle_text: str, *, granter_name: str | None = None,
    granter_id: int | None = None,
) -> tuple[str, ...]:
    """The printed ability lines an Aura grants the permanent it is attached to.

    **Derived, not recorded.** ``Permanent.effective_card`` asks this of every
    attachment on every read, so detaching the Aura takes the ability away with
    nothing to undo — CR 611.3b's "removal is the absence of a contribution",
    the arrangement every other continuous half of this file already uses.

    The claim table at the top of this module named this behaviour and the code
    it named had been deleted, so Equinox's whole printed effect was a claim
    with nothing behind it: the card reported supported and the land it
    enchanted gained nothing at all.

    **Bound to the granter, and only what compiles.** *granter_name* and
    *granter_id* are the attached permanent's: a quote naming its own Aura
    ("…the number of arrow counters on Archery Training") is handed to the host
    naming that one object (``granted_abilities.bind_granter``). And a quote
    the compiler cannot read is not handed over at all — the host's rules text
    is compiled as a whole, so one unreadable line appended to a creature made
    the *creature* unsupported and took every ability it printed with it. A
    Prodigal Sorcerer wearing the unread Archery Training could not ping.
    """
    quotes = aura_quoted_grants(oracle_text or "")
    if not quotes:
        return ()
    from .granted_abilities import GRANTER_PROBE_ID, bind_granter

    bound_id = GRANTER_PROBE_ID if granter_id is None else granter_id
    return tuple(
        bind_granter(quote, granter_name, bound_id)
        for quote in quotes
        if quoted_grant_readable(quote, granter_name)
    )


# 'As long as enchanted permanent is red or green, it has "At the beginning of
# your upkeep, sacrifice this permanent unless you pay its mana cost."' (Essence
# Leak.) The quoted grant one pattern up with a **criterion on the host** in
# front of it — CR 613.1's "as long as", so the ability is there exactly while
# the host answers the description and is gone, with nothing to undo, the
# moment a Lace or a Sway of Illusion changes the answer (CR 611.3a).
#
# The criterion is captured as words and read by the grammar's **noun parser**
# (:func:`_host_criterion_filter`), not by a colour alternation here: "is red or
# green" is "is a red or green permanent", which is a phrase that parser already
# reads and ``subject_matches`` already tests through the layers. A regex of
# colour words would be a second reader of what a colour is, and would make
# "is tapped" or "is an artifact" on the next card a new pattern instead of the
# same one.
_CONDITIONAL_QUOTED_ABILITY_GRANT = re.compile(
    rf'^as long as {_ATTACHED} (?P<noun>{_NOUN}) is (?P<criterion>[a-z][a-z, \-]*), '
    r'it has "(?P<ability>[^"]+)"$'
)


def _host_criterion_filter(noun: str, criterion: str) -> dict | None:
    """The filter payload "<attached> *noun* is *criterion*" tests, or None.

    Built by handing the noun parser the phrase the clause abbreviates — "red or
    green" + "permanent" — so the criterion means what the same words mean in
    front of any noun in the engine. None when the parser cannot read it, when
    it reads past the phrase, when the result carries a key ``subject_matches``
    cannot test, or when the criterion added nothing to the bare noun: each of
    those is a condition that would be admitted and then not enforced, which
    for a granted *drawback* is the card doing more than it prints.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    def _described(phrase: str) -> dict | None:
        stream = TokenStream(tokenize(phrase).tokens)
        try:
            described = parse_object_filter(stream)
        except GrammarError:
            return None
        if not stream.exhausted:
            return None
        return described.to_payload()

    bare = _described(noun)
    narrowed = _described(f"{criterion} {noun}")
    if bare is None or narrowed is None or narrowed == bare:
        return None
    if untestable_filter_keys(narrowed):
        return None
    return narrowed


@lru_cache(maxsize=None)
def _conditional_ability_grant_shapes(oracle_text: str) -> tuple[tuple[tuple, str], ...]:
    """Every ``(criterion, quoted ability)`` *oracle_text* prints in the
    conditional-grant shape, whether or not the engine can read the quote.

    The half of :func:`aura_conditional_ability_grants` that is a pure function
    of the text, and the only half cached here: whether the quote **compiles**
    is ``granted_ability_supported``'s answer, held in a cache
    ``clear_compilation_caches`` knows about. Caching that answer a second time
    under this function would be a compiled answer in a cache nothing clears —
    the two-poisoned-keys failure ``oracle_types.compilation_cache`` exists for.

    The recompute asks this of every Aura on every pass, so the quick refusal
    is first and is what nearly every card takes.
    """
    text = oracle_text or ""
    if '"' not in text or "as long as" not in text.lower():
        return ()
    shapes: list[tuple[tuple, str]] = []
    for raw_line in text.splitlines():
        match = _CONDITIONAL_QUOTED_ABILITY_GRANT.match(_line_text(raw_line))
        if match is None:
            continue
        described = _host_criterion_filter(
            match.group("noun"), match.group("criterion").strip()
        )
        if described is not None:
            shapes.append((_freeze_filter(described), match.group("ability")))
    return tuple(shapes)


def aura_conditional_ability_grants(oracle_text: str) -> tuple[tuple[tuple, str], ...]:
    """``(criterion, ability line)`` pairs an Aura grants its host **while the
    host answers the criterion**.

    The criterion is a filter payload frozen as sorted items (the shapes are
    cached, and a shared dict would be one caller's mutation away from changing
    the card); :func:`conditional_ability_lines_for` thaws it.

    Kept apart from :func:`aura_granted_ability_lines` for the reason
    :func:`aura_conditional_keyword_grants` is kept apart from the keyword
    grants: that list is folded into ``Permanent.effective_card`` unconditionally
    and with no game in hand, so a conditional grant returned from it would be
    an unconditional one the moment a caller forgot the second element.

    A pair is returned only when **both** halves are implemented — the
    criterion is testable and the quote compiles
    (``granted_abilities.granted_ability_supported``) — so the support gate,
    which asks this function, cannot admit a line whose ability does nothing.
    """
    shapes = _conditional_ability_grant_shapes(oracle_text or "")
    if not shapes:
        return ()
    from .granted_abilities import granted_ability_supported

    return tuple(
        (criterion, ability)
        for criterion, ability in shapes
        if granted_ability_supported(ability)
    )


def _freeze_filter(described: dict) -> tuple:
    """*described* as hashable, order-stable items (lists become tuples)."""
    return tuple(
        (key, tuple(value) if isinstance(value, list) else value)
        for key, value in sorted(described.items())
    )


def conditional_ability_lines_for(game, aura, seat: int, host) -> tuple[str, ...]:
    """The quoted abilities *aura* grants *host* right now.

    Asked on every recompute by ``_recalculate_lord_buffs``, which owns the
    derived-ability channel's clear and rebuild — so the answer is never
    remembered, and the ability leaves with the Aura, with the criterion, or
    with either's text being changed (CR 611.3a/b).

    The criterion is tested through ``subject_matches``: the host's colour is
    CR 613 layer 5's answer, not its printed one. *seat* is the Aura's
    controller (CR 109.5), which is who a relative key would be measured from.
    """
    from .subject_filters import subject_matches

    lines: list[str] = []
    for frozen, ability in aura_conditional_ability_grants(
        aura.effective_card.oracle_text or ""
    ):
        described = {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in frozen
        }
        if subject_matches(game, host, described, observer=seat, source=aura):
            lines.append(ability)
    return tuple(lines)


def _keyword_list(run: str) -> list[str]:
    """The keywords a printed run names — "flying and first strike", "flying,
    first strike, and trample".

    Only words the alternation admitted can be here, because the pattern that
    captured this run was built from that alternation; the split is therefore
    a split and not a second vocabulary.
    """
    return [part.strip() for part in re.split(r",| and ", run) if part.strip()]


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
            grants.extend(_keyword_list(match.group("keyword")))
        elif (compound := _KEYWORD_GRANT_AND_RESTRICTION.match(line)) is not None:
            # "…has phasing and can't be blocked except by Walls." The keyword
            # half only; the restriction half is claimed by
            # :func:`aura_combat_restriction` off the same line, exactly as
            # Consecrate Land's compound below splits between two readers.
            grants.extend(_keyword_list(compound.group("keyword")))
        elif _COMPOUND_INDESTRUCTIBLE.match(line):
            # Consecrate Land prints one line carrying two effects. Its trailing
            # clause is claimed separately as a restriction, so matching only
            # the keyword half here drops nothing — which is the whole reason
            # the compound is spelled out rather than matched loosely.
            grants.append("indestructible")
    return tuple(grants)


def aura_granted_line_derived_lines(oracle_text: str) -> tuple[str, ...]:
    """The printed **lines** an Aura's keyword grant has to be turned into.

    A keyword grant is normally one word into CR 613 layer 6's ability set, and
    every reader of "does it have flying?" looks there. That is no use for a
    keyword the CR *defines* as an ability rather than describing one: the
    compiler built rampage and flanking out of a printed line before layer 6
    existed for this permanent, so a word in the ability set grants the word and
    not the trigger. Agility is the card that shows it — "Enchanted creature
    gets +1/+1 and **has flanking**" made its host count as a flanker for the
    next flanker's filter and gave it no ability at all.

    So the grant of such a keyword is a grant of the *line*, exactly as
    ``keywords.LINE_DERIVED_KEYWORDS`` already says for the one-shot path
    (`handlers/pump._grant_one_keyword`) — this is that same rule on the
    continuous path, derived per read like every other half of this file so
    detaching the Aura takes the ability away with nothing to undo. The word
    comes back for free: ``layer_bridge._TEXT_KEYWORDS`` scans the compiled
    keyword lines, so the appended line puts "flanking" back in the ability set
    and both halves travel together.

    Capitalised because it is folded into the permanent's *printed* rules text,
    which the UI shows; the compiler lowercases it again.
    """
    from .keywords import LINE_DERIVED_KEYWORDS, keyword_ability_name

    return tuple(
        keyword.capitalize()
        for keyword in aura_keyword_grants(oracle_text)
        if keyword_ability_name(keyword) in LINE_DERIVED_KEYWORDS
    )


def aura_keyword_removals(oracle_text: str) -> tuple[str, ...]:
    """Keyword abilities an Aura **takes away** from the permanent it enchants.

    "Enchanted creature loses flying." (Mammoth Harness.) CR 613 layer 6 again,
    and derived on every recompute exactly as :func:`aura_keyword_grants` is —
    so the ability comes back the moment the Aura stops being attached, with no
    remembered grant to restore. That symmetry is the reason this is a
    derivation rather than a `remove_keyword` call at attach time: a stored
    removal would have to be found and undone by whichever of the ways an Aura
    can leave happened to run.

    Kept apart from the grant for the reason the module comment on
    ``_KEYWORD_REMOVAL`` gives: grants and removals share the layer and are
    opposite contributions, so one list would make them indistinguishable —
    and the wrong reading of "loses flying" is an Aura that grants it.
    """
    removals: list[str] = []
    for raw_line in (oracle_text or "").split("\n"):
        match = _KEYWORD_REMOVAL.match(_line_text(raw_line))
        if match is not None:
            removals.extend(_keyword_list(match.group("keyword")))
    return tuple(removals)


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
        # "Enchanted creature gets +3/+0 and **can only attack alone**."
        # (Errantry.) CR 506.5's "attacking alone", read as a restriction on the
        # *declaration*: the creature may attack only in a declaration where it
        # is the sole attacker. The P/T half is `aura_static_pt_grant`'s, which
        # is why the prefix is optional here — the same split `_KEYWORD_GRANT`
        # makes.
        re.compile(
            rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? "
            r"can only attack alone$"
        ),
        "can_only_attack_alone",
    ),
    (
        # The optional P/T prefix is the same split `_KEYWORD_GRANT` and the
        # attack-alone row make: "Enchanted creature gets +1/+1 **and** doesn't
        # untap during its controller's untap step" (Dance of the Dead) is one
        # printed line carrying two effects in two channels, and
        # `aura_static_pt_grant` searches rather than anchors, so both halves
        # are read. Without the prefix the line matched nothing and the Aura
        # lost the restriction *and* reported the line unclaimed.
        re.compile(
            rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? "
            r"doesn't untap during its controller's untap step$"
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
        # Convulsing Licid. The blocking half of the pair above, and the same
        # argument for a row of its own: the compound "can't attack or block"
        # rows say in so many words that a card printing one half is a
        # different card, and Stronghold prints the half nobody had. Without
        # the row the line was unclaimed, the Licid reported unsupported, and
        # `declare_blockers_step` — which has read this very name since
        # Pacifism's cousins arrived — had nothing to read.
        #
        # The optional P/T prefix is the same split the attack-alone and
        # "doesn't untap" rows above make, and Maniacal Rage is the card that
        # prints it: "Enchanted creature gets +2/+2 **and** can't block" is one
        # line carrying two effects in two channels, the numbers read by
        # `aura_static_pt_grant` (which searches rather than anchors) and the
        # restriction read here. Without the prefix the line matched nothing —
        # the Aura lost the restriction *and* reported the line unclaimed,
        # which is the failure Dance of the Dead's row records one screen up.
        re.compile(rf"^enchanted {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? can't block$"),
        "cant_block",
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
    (
        # Volrath's Curse prints the same sentence **without** CR 605.1a's
        # exception, and that is a different card rather than a wording of the
        # row above: a Birds of Paradise under Faith's Fetters may still tap for
        # mana and one under the Curse may not. Its own name for that reason —
        # the enforcement site reads which of the two it is, and one name for
        # both would have to pick a side.
        #
        # Anchored on the clause rather than the line, like the two "can't
        # attack or block" rows above it: this sentence is printed with a second
        # one behind it (the CR 116.2d offer), so a `$` would match nothing. The
        # lookahead is what keeps it off the longer wording above.
        re.compile(
            rf"^{_ATTACHED} {_NOUN} can't attack or block, and its activated "
            r"abilities can't be activated(?! unless)"
        ),
        "all_activated_abilities_shut_off",
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
#
# **One pattern over two axes, not a row per pairing.** The step is printed two
# ways ("its controller's", "your") and the holder two ways ("it", "this
# aura"), and Merseine prints the crossing the pairing table had no row for —
# "during **its controller's** untap step if **this Aura** has a net counter on
# it". A row per pairing is quadratic in the clauses that exist, which is the
# arrangement `engine/activation_restrictions.py` records replacing for exactly
# this reason; and the clause nobody had listed is not a dead restriction, it
# is an *unenforced* one, so the card untaps every turn while reporting fine.
_COUNTER_UNTAP_CONDITION = re.compile(
    rf"^{_ATTACHED} {_NOUN} doesn't untap during (?:its controller's|your) "
    r"untap step if (?P<holder>it|this aura) has an? (?P<kind>[a-z]+) "
    r"counter on it$"
)


#: "Enchanted creature doesn't untap during its controller's untap step **if it
#: attacked during its controller's last turn**." (Tangle Kelp.) The same
#: sentence Goblin Rock Sled prints about *itself*, which is idiom 14 exactly:
#: one question, asked with the subject rewritten. The answer is
#: ``turn_state.attacked_during_seats_last_turn`` for both, so the Aura cannot
#: drift from the creature that prints it — and neither can drift from the
#: declare-attackers step, which refuses Giant Turtle's attack on the same read.
_ATTACHED_UNTAP_ATTACKED_LAST_TURN = re.compile(
    rf"^{_ATTACHED} {_NOUN} doesn't untap during its controller's untap step "
    r"if it attacked during its controller's last turn$"
)


def aura_attacked_untap_condition(line: str) -> bool:
    """Whether *line* is the attack-conditioned "doesn't untap" Aura clause."""
    return _ATTACHED_UNTAP_ATTACKED_LAST_TURN.match(_line_text(line)) is not None


def aura_counter_untap_condition(line: str) -> tuple[str, str] | None:
    """``(counter kind, holder)`` for a counter-conditioned untap line, or None.

    *holder* names which object the condition reads: ``"attached"`` (Venarian
    Gold's sleep counter on the creature) or ``"aura"`` (Cocoon's pupa counter
    on the Aura itself).
    """
    match = _COUNTER_UNTAP_CONDITION.match(_line_text(line))
    if match is None:
        return None
    holder = "aura" if match.group("holder") == "this aura" else "attached"
    return match.group("kind"), holder


#: "Enchanted creature can't block **if it's black**." (Hobble.) A combat ban
#: that holds only while the host is a colour — the conditioned twin of the
#: plain ``cant_attack`` / ``cant_block`` rows in ``_RESTRICTIONS``, read by the
#: same predicate under the same two names, so the two steps that enforce those
#: rows need no new question: a conditioned row whose condition holds is simply
#: the restriction being active this declaration. That is the arrangement the
#: counter-conditioned "doesn't untap" rows above already have.
#:
#: **One pattern over two axes**, for the reason that pattern gives: the verb is
#: printed two ways and the colour five, and a row per pairing would leave the
#: nine nobody listed *unenforced* rather than dead. Hobble prints one crossing;
#: the other nine are the same sentence.
#:
#: The colour is the host's as the layers currently have it (CR 613 layer 5),
#: asked when combat asks — a creature turned black stops being able to block,
#: and one turned another colour can block again, with nothing to clear.
_COLOR_CONDITIONED_COMBAT_BAN = re.compile(
    rf"^{_ATTACHED} {_NOUN} can't (?P<verb>attack|block) "
    rf"if it's (?P<color>{_COLORS})$"
)

#: The restriction name each printed verb is enforced under.
_COMBAT_BAN_NAMES = {"attack": "cant_attack", "block": "cant_block"}


def aura_color_conditioned_combat_ban(line: str) -> tuple[str, str] | None:
    """``(restriction name, colour word)`` for a colour-conditioned combat ban,
    or None.

    The colour is the printed *word*, for :func:`aura_protection_colors`'
    reason: the caller maps it, and layer 3's text change (Sleight of Mind) has
    already rewritten the word by the time it is read off ``effective_card``.
    """
    match = _COLOR_CONDITIONED_COMBAT_BAN.match(_line_text(line))
    if match is None:
        return None
    return _COMBAT_BAN_NAMES[match.group("verb")], match.group("color")


#: The word a protection grant names when the colour was **chosen** rather
#: than printed: "Enchanted creature has protection from **the chosen
#: color**." (Ward of Lights.)
#:
#: A sixth value in the same channel as the five colour words rather than a
#: second function, because :func:`aura_protection_colors` already returns
#: *words* and leaves the mapping to its caller — "it is the one that knows
#: about text-changing remaps". Resolving a choice is the same kind of
#: knowledge, and that caller is also the only reader holding the Aura the
#: choice was recorded on.
CHOSEN_PROTECTION_COLOR = "chosen"

#: The word a protection grant names when the colours are **computed**:
#: "Enchanted creature has protection from **each color among permanents you
#: control**." (Pledge of Loyalty.) A seventh value in the same channel, for
#: the reason the sixth is one: :func:`aura_protection_colors` returns words
#: and its caller resolves them, and that caller is the only reader holding
#: both the Aura and the game. "You" is the Aura's controller (CR 109.5), and
#: the set is whatever that seat's board holds when the question is asked —
#: a static ability is not locked in (CR 611.3a), so the protection widens the
#: moment its controller lands a permanent of a new colour and narrows when
#: one leaves.
AMONG_CONTROLLED_PROTECTION_COLORS = "among_controlled"

#: The printed phrases that are not a colour word, as the value each travels as.
_PROTECTION_QUALITY_WORDS = {
    "the chosen color": CHOSEN_PROTECTION_COLOR,
    "each color among permanents you control": AMONG_CONTROLLED_PROTECTION_COLORS,
}

#: The P/T prefix is optional for :data:`_COLOR_GRANT`'s reason exactly: one
#: printed line can carry a layer-7c bonus and a layer-6 grant, and each half is
#: read by the reader that owns its layer. Without it a card printing "enchanted
#: creature gets +1/+1 and has protection from black" would be *claimed* by the
#: keyword row above -- ``_KEYWORDS`` is an alternative there -- and granted
#: nothing, which is this module's own defining failure with an anchor as its
#: cause.
_PROTECTION_GRANT = re.compile(
    rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? has protection from "
    rf"(?P<colors>{_PROTECTION_QUALITIES})\b"
)


#: "Enchanted creature gets +1/+1 and **is an artifact in addition to its other
#: types**." (Transmogrifying Licid.) The same rider one level up the type
#: hierarchy: `_TYPE_ADDITION_GRANT` above adds a creature *subtype* (CR 205.3),
#: this adds a *card type* (CR 205.2), and both are CR 613 layer 4 additions
#: that never replace.
#:
#: Its own pattern rather than a widened alternation in that one, because the
#: two grants go into different fields of the same contribution — a subtype
#: handed to ``card_types`` makes the permanent a "Knight" *type*, which nothing
#: on any board is — and because the shapes differ: Dub prints a keyword between
#: the P/T and the type where this prints nothing at all.
#:
#: The P/T half is deliberately not read here. ``_STATIC_PT_GRANT`` is an
#: unanchored *search* for exactly this reason (see its comment): the two halves
#: of one printed line live in two layers, and each is read by the reader that
#: owns its layer.
_CARD_TYPE_ADDITION_GRANT = re.compile(
    rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? is an? "
    r"(?P<card_type>artifact|enchantment|land|creature) "
    r"in addition to its other types$"
)


def aura_card_type_grants(oracle_text: str) -> tuple[str, ...]:
    """Card **types** an Aura adds to what it enchants (CR 613 layer 4).

    :func:`aura_type_grants`' twin one level up CR 205's hierarchy — a *card
    type* (CR 205.2) rather than a creature subtype (CR 205.3) — and separate
    because the two go into different fields of the contribution the layer
    engine takes. "In addition to its other types" is the printed rider that
    makes it an addition; nothing here ever replaces.
    """
    granted: list[str] = []
    for raw_line in oracle_text.splitlines():
        match = _CARD_TYPE_ADDITION_GRANT.match(_line_text(raw_line))
        if match is not None:
            granted.append(match.group("card_type"))
    return tuple(granted)


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


#: "Enchanted creature gets +3/-1 **and is black**." (Grave Servitude.) The
#: colour half of the compound line, and the bare "…is black" beside it.
#:
#: A **search**, not an anchored match, for `_STATIC_PT_GRANT`'s reason one
#: screen down: the two halves of one printed line live in two layers (7c and
#: 5), and each is read by the reader that owns its layer. Anchoring here would
#: make the compound line answer for the colour and not the P/T, or the other
#: way round, depending on which reader was written last.
#:
#: The trailing anchor is still required. "is black" ends the sentence on every
#: printing of it, and without the anchor "enchanted creature is black **as
#: long as …**" — a conditional this does not implement — would read as the
#: unconditional grant.
_COLOR_GRANT = re.compile(
    rf"{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? is (?P<color>{_COLORS})$"
)


def aura_color_grants(oracle_text: str) -> tuple[str, ...]:
    """Colour words an Aura gives what it enchants (CR 613 layer 5).

    CR 105.3: a new colour **replaces** every colour the object had, unless the
    effect says "in addition". No printing of this sentence says it, so the
    grant is a `set_colors` contribution and not an addition — a creature under
    Grave Servitude is black and nothing else.

    Colour *words*, exactly as :func:`aura_protection_colors` returns them: the
    caller is the one that knows whether a text change has remapped the word
    (Sleight of Mind), and mapping here would be a second answer to that.
    """
    granted: list[str] = []
    for raw_line in oracle_text.splitlines():
        match = _COLOR_GRANT.search(_line_text(raw_line))
        if match is not None:
            granted.append(match.group("color"))
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

    :data:`CHOSEN_PROTECTION_COLOR` is the sixth value, for "protection from
    **the chosen color**" (Ward of Lights). It travels through this same
    channel for that mapping reason exactly: the caller holds the Aura, and
    the choice is recorded on it by "As this Aura enters, choose a color."
    :data:`AMONG_CONTROLLED_PROTECTION_COLORS` is the seventh, for "each color
    among permanents you control" (Pledge of Loyalty), resolved the same way.
    """
    found = set()
    for raw_line in oracle_text.splitlines():
        match = _PROTECTION_GRANT.match(_line_text(raw_line))
        if match is not None:
            # CR 702.16g: "protection from black **and from red**" (Mask of Law
            # and Grace) is two protection abilities. Split here rather than
            # returned as a phrase, because every consumer of this frozenset
            # maps one word to one quality -- a joined string maps to none of
            # them and the Aura would protect from nothing at all. That is what
            # the pattern already did while its alternation was one colour wide
            # and its tail unanchored: it matched Mask's line and returned
            # ``{"black"}``, dropping red in silence.
            for word in match.group("colors").split(" and from "):
                word = word.strip()
                found.add(_PROTECTION_QUALITY_WORDS.get(word, word))
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
    # "Enchanted creature can't be blocked." (Cloak of Mists.) The unnarrowed
    # member of the family below: no blocker class, no count and no price, so
    # nothing may block the host at all (CR 509.1b). Phantom Warrior prints the
    # same sentence about itself, which is what makes it one table asked with
    # the subject rewritten rather than a second reading.
    #
    # Its readers are ``phases/declare_blockers_step._can_block_attacker``,
    # which refuses every blocker, and ``legality.is_unblockable``, which fades
    # the creature in the UI. Both already answered the kind off the
    # *attacker's own* program and had to be taught this channel as well --
    # a kind in this set with only one of its readers widened is a restriction
    # the UI shows and the step ignores, or the reverse.
    "cant_be_blocked",
    "cant_be_blocked_by",
    # "Enchanted creature can't be blocked except by artifact creatures and/or
    # white creatures." (Seeker.) The whitelist form, read through the same
    # subject rewrite as the blacklist beside it — the difference between
    # Seeker and Elven Riders is whose text the sentence is printed on.
    "cant_be_blocked_except_by",
    # "Enchanted creature can't attack unless its controller pays {3}."
    # (Brainwash.) CR 508.1h, an additional cost to declare the creature as an
    # attacker. Its reader is
    # ``phases/declare_attackers_step._attack_mana_costs_of``, which asks this
    # channel and the creature's own compiled program together — the gate in
    # ``can_attack`` and the charge in ``declare_attackers`` share it, so the
    # restriction cannot be checked and then left uncharged.
    "cant_attack_unless_pay",
    # "Enchanted creature can't block creatures with power equal to or greater
    # than the enchanted creature's toughness." (Ironclaw Curse.) The mirror of
    # ``cant_be_blocked_by`` above — that one says what may not block the
    # creature, this one what the creature may not block — and Ironclaw Orcs
    # prints the same sentence about itself, so it is the same table asked with
    # the subject rewritten (idiom 14). Its reader is
    # ``phases/declare_blockers_step``, which asks this channel and the
    # blocker's own compiled program in one loop, so the two spellings of the
    # restriction cannot come to be enforced differently.
    "cant_block_subject",
    # "Enchanted creature can block only creatures with flying." (Air Bladder.)
    # Shacklegeist prints the same sentence about itself, so it is the same
    # table asked with the subject rewritten. Its reader is
    # ``phases/declare_blockers_step._can_block_attacker``, which asks this
    # channel and the blocker's own compiled program in one loop — the shape
    # ``cant_block_subject`` above already has, for its reason.
    "can_block_only_with_keyword",
    # "Enchanted creature can't be blocked unless defending player pays {3} for
    # each creature they control that's blocking it." (Awesome Presence.)
    # CR 509.1d's cost owed by the **defender**, the mirror of
    # ``cant_attack_unless_pay`` above. Its reader is
    # ``phases/declare_blockers_step._block_mana_costs_of``, which asks this
    # channel about the *attacker* alongside the blocker's own program, so the
    # gate in ``_can_block_attacker`` and the charge in ``declare_blockers``
    # share one reading and a block cannot be accepted and left unpaid.
    "cant_be_blocked_unless_pay",
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
    # "Enchanted creature has phasing **and can't be blocked except by Walls**."
    # (Cloak of Invisibility.) The restriction half of a compound line, asked
    # first because the plain subject match below would hand the whole
    # sentence — keyword grant included — to a table anchored on "can't", which
    # answers None and drops a restriction the card prints.
    compound = _compound_restriction_clause(normalized)
    if compound is not None:
        noun, clause = compound
        restriction = combat_restriction_for(f"this {noun} {clause}")
        if restriction is None or restriction.also_kinds or restriction.kind not in (
            ENFORCED_ATTACHED_COMBAT_RESTRICTIONS
        ):
            return None
        return restriction
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
    # A row naming several kinds over one sentence
    # (``CombatRestriction.also_kinds``) has only its first honoured here: this
    # channel returns one restriction per line and every reader asks about one
    # kind. Refusing keeps the Aura unsupported and named, where returning the
    # first would enforce one clause of its sentence and drop the others.
    if restriction.also_kinds:
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


def aura_block_permission(line: str) -> int:
    """How many attackers beyond the printed one an Aura's *line* lets the
    permanent it is attached to block, or 0.

    "Enchanted creature can block any number of creatures." (Entangler.) Wall of
    Glare and Avatar of Hope print the same permission about themselves, so the
    difference between the cards is the subject of the sentence and nothing
    else — which is why this rewrites the subject and asks
    ``combat_permissions.printed_block_ceiling`` instead of holding a second
    copy of its table, exactly as :func:`aura_combat_restriction` asks the
    restriction table. An Equipment printing it is the same rule (CR 301.5f).
    """
    from .combat_permissions import printed_block_ceiling

    normalized = _line_text(line)
    match = _ATTACHED_SUBJECT.match(normalized)
    if match is None:
        return 0
    return printed_block_ceiling(
        (f"this {match.group('noun')}{normalized[match.end():]}",)
    )


def attached_block_ceiling(permanent) -> int:
    """The block permissions the Auras on *permanent* grant it, summed.

    Asked when the declare-blockers step reads the ceiling (CR 509.1b), so the
    permission ends when the Aura does with nothing to clear — the shape
    :func:`attached_combat_restrictions` has. Summed rather than maximised for
    ``printed_block_ceiling``'s reason: CR 509.1b's permissions add.
    """
    return sum(
        aura_block_permission(raw_line)
        for aura in auras_attached_to(permanent)
        for raw_line in (aura.effective_card.oracle_text or "").splitlines()
    )


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


def aura_restriction_active(
    permanent, name: str, *, game=None, seat: int | None = None
) -> bool:
    """Whether any Aura attached to *permanent* imposes restriction *name*.

    This is the whole of "does the restriction apply": when the Aura leaves it
    stops being attached, so it stops being asked. Nothing is stamped and
    nothing has to be cleaned up.

    *game* and *seat* are what the conditional ``doesnt_untap`` rows need: one
    of them reads the permanent's attack record against a seat's turn ordinal,
    which is not readable off the permanent alone. A caller that cannot supply
    them gets the unconditional rows only — the untap step, the one place the
    restriction is enforced, supplies both.
    """
    from .named_counters import counters_on
    from .turn_state import attacked_during_seats_last_turn

    for aura in auras_attached_to(permanent):
        # CR 116.2d: the host's controller bought a turn off this Aura's
        # restrictions, so it is imposing none of them for the rest of the turn
        # (Volrath's Curse). Asked here rather than at each of the eight readers
        # of this predicate, because this is the one place "does the restriction
        # apply?" is answered — a suspension wired into the combat step alone
        # would leave the creature's activated abilities still shut off.
        if name in (aura.metadata.get(IGNORED_RESTRICTIONS) or ()):
            continue
        text = aura.effective_card.oracle_text
        if name in aura_restrictions(text):
            return True
        if name in ("cant_attack", "cant_block"):
            # "Enchanted creature can't block **if it's black**." (Hobble.) The
            # colour-conditioned rows: active exactly while the host is that
            # colour, read through layer 5 at ask time.
            from .grammar.vocabulary import COLOR_WORDS

            colors_now = permanent.effective_colors
            for raw_line in (text or "").splitlines():
                ban = aura_color_conditioned_combat_ban(raw_line)
                if (
                    ban is not None
                    and ban[0] == name
                    and COLOR_WORDS[ban[1]] in colors_now
                ):
                    return True
            continue
        if name != "doesnt_untap":
            continue
        # The conditioned rows: the restriction is active exactly while the
        # condition holds, read at ask time — so when the last counter leaves,
        # or the creature sits out a turn, nothing has to be cleared for it to
        # untap again.
        for raw_line in (text or "").splitlines():
            found = aura_counter_untap_condition(raw_line)
            if found is not None:
                kind, holder = found
                holder_obj = permanent if holder == "attached" else aura
                if counters_on(holder_obj, kind) > 0:
                    return True
                continue
            if (
                aura_attacked_untap_condition(raw_line)
                and game is not None
                and seat is not None
                and attacked_during_seats_last_turn(game, permanent, seat)
            ):
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


#: "Enchanted land is a 5/6 green Treefolk creature that's still a land."
#: (Living Terrain.) Animate Artifact's shape with the body printed rather than
#: computed: layer 4 adds the creature type and the printed creature types
#: (CR 205.1b's "still a land" is the *addition* — nothing is replaced), layer 5
#: sets the printed colours (CR 105.3) and layer 7b sets the printed P/T. All
#: three are derived from the Aura's text on every recompute, so the land is a
#: land again the moment the Aura leaves.
#:
#: The colour run and the creature types are captured loosely and *checked* by
#: :func:`aura_land_animation` against the vocabulary, so a word that is neither
#: a colour nor a creature type refuses the line instead of being dropped.
_ATTACHED_LAND_ANIMATION = re.compile(
    r"^enchanted land is an? (?P<power>\d+)/(?P<toughness>\d+)"
    r"(?P<words>(?: [a-z][a-z'-]*)*?) creature that's still a land$"
)


def aura_land_animation(oracle_text: str) -> dict | None:
    """The body an Aura makes its land, or None.

    ``{"power", "toughness", "colors", "subtypes"}`` — colours as symbols, the
    creature types as the vocabulary spells them. One reader for the support
    gate (through :func:`aura_continuous_claim`) and for the three layers in
    ``layer_bridge`` that apply it, which is this file's standing rule.

    Colours come first and creature types after them, which is the order the
    templating prints a body in (the same order ``effects/types.py`` reads
    Quirion Druid's "2/2 green creature" in); a word out of place, or a word
    that is neither, answers None.
    """
    from .grammar.vocabulary import COLOR_WORDS, CREATURE_TYPES

    for raw_line in (oracle_text or "").splitlines():
        match = _ATTACHED_LAND_ANIMATION.match(_line_text(raw_line))
        if match is None:
            continue
        colors: list[str] = []
        subtypes: list[str] = []
        for word in match.group("words").split():
            if word in COLOR_WORDS and not subtypes:
                colors.append(COLOR_WORDS[word])
            elif word in CREATURE_TYPES:
                subtypes.append(word)
            else:
                return None
        return {
            "power": int(match.group("power")),
            "toughness": int(match.group("toughness")),
            "colors": tuple(colors),
            "subtypes": tuple(subtypes),
        }
    return None


#: "**You control** enchanted creature." (Control Magic, Dominating Licid;
#: Steal Artifact prints the same sentence one noun over.) CR 613 layer 2,
#: derived from the attachment on every state-based pass rather than performed
#: when an Aura *spell* resolves — which is the difference the Licids force. A
#: Licid becomes an Aura through an activated ability and attaches through
#: ``attach_source_to_target``; no Aura spell ever resolves, so the resolution-
#: time reading reached it not at all.
_ATTACHED_CONTROL_CHANGE = re.compile(rf"^you control {_ATTACHED} {_NOUN}$")


def aura_grants_control(attachment) -> bool:
    """Whether *attachment* says its controller controls what it is attached to.

    Asked of the permanent rather than of a string, because the text that
    matters is ``effective_card`` — a Licid's printed lines survive its type
    change, and a copy or a text-changing effect is read here for the reason
    every other derivation in this file reads it (CR 613 layers 1 and 3).

    Read by the state-based sweep in ``mixins/game_ending.py`` in **both**
    directions: it records the contribution while the attachment holds and ends
    it when the attachment does not. That is why the claim in
    :func:`aura_continuous_claim` is honest — the effect really is derived from
    the Aura's own text on every pass, with no remembered delta to undo, which
    is what the rest of this file means by "continuous".
    """
    text = attachment.effective_card.oracle_text or ""
    return any(
        _ATTACHED_CONTROL_CHANGE.match(_line_text(raw_line))
        for raw_line in text.splitlines()
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


# "Enchanted creature can't be the target of abilities from artifact sources."
# (Artifact Ward.) This module used to carry that sentence, its regex and the
# board reader behind it. It does not any more: Raiding Party prints the same
# clause about **itself** rather than about an attachment, and a reader keyed to
# the attachment cannot see it — so what looked like one Aura's rule was half a
# rule, and the missing half was the subject.
#
# `engine/target_immunity.py` owns the whole family now
# (`source_class_immunities`, `ability_source_immunity_classes`), which is where
# its two siblings already lived: a narrowed shroud is a narrowed shroud whether
# the narrowing names a spell's card type, what a source's target description
# admits, or what the source *is*. `aura_continuous_claim` below reaches it
# through `immunity_claims_line`, the same claim every other clause in that file
# is admitted by.


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
        attached_damage_shield as _attached_damage_shield_line,
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
    if aura_keyword_removals(normalized):
        return "keyword removal (layer 6) — auras.aura_keyword_removals"
    if aura_conditional_keyword_grants(normalized):
        return (
            "state-conditioned keyword grant (layer 6) — "
            "auras.aura_conditional_keyword_grants"
        )
    if aura_conditional_ability_grants(normalized):
        return (
            "criterion-conditioned ability grant (layer 6) — "
            "auras.conditional_ability_lines_for"
        )
    if aura_restrictions(normalized):
        return "combat/untap restriction — auras.aura_restriction_active"
    if aura_counter_untap_condition(normalized) is not None:
        return "counter-conditioned untap restriction — auras.aura_restriction_active"
    if aura_attacked_untap_condition(normalized):
        return "attack-conditioned untap restriction — auras.aura_restriction_active"
    if aura_color_conditioned_combat_ban(normalized) is not None:
        return "colour-conditioned combat ban — auras.aura_restriction_active"
    if aura_combat_restriction(normalized) is not None:
        return "attached combat restriction — auras.attached_combat_restrictions"
    if aura_block_permission(normalized):
        return "attached block permission (CR 509.1b) — auras.attached_block_ceiling"
    # "Enchanted creature can't be the target of spells and can't be enchanted
    # by other Auras." (Anti-Magic Aura.) Both clauses, or neither: the reader
    # claims a line only when it implements every restriction the line conjoins,
    # so a card pairing one of these with a sentence nothing reads stays
    # unsupported instead of losing half its text.
    if immunity_claims_line(normalized):
        return "target/enchant/source-class immunity — target_immunity"
    if _attached_prevent_all_from_source_type(normalized) is not None:
        return "prevention from a source class — prevention._source_type_shielded_by"
    if _attached_damage_shield_line(normalized) is not None:
        return "damage shield — prevention._attached_damage_shields"
    if _PROTECTION_LINE.match(normalized):
        return "protection grant — auras.aura_protection_colors"
    if _CARD_TYPE_ADDITION_GRANT.match(normalized):
        return "card-type addition (layer 4) — auras.aura_card_type_grants"
    if _ATTACHED_CONTROL_CHANGE.match(normalized):
        return "control change (layer 2) — auras.aura_grants_control"
    if aura_animates_artifact(normalized):
        return "artifact animation (layers 4 and 7b) — auras.animating_auras"
    if aura_land_animation(normalized) is not None:
        return "land animation (layers 4, 5 and 7b) — auras.aura_land_animation"
    if aura_ability_cost_reduction(normalized):
        return "activation cost reduction — auras.attached_ability_cost_reduction"
    if aura_redirects_all_damage(normalized):
        return (
            "CR 614.9 redirection onto the host — "
            "damage_redirects.attached_static_redirects"
        )
    if aura_redirects_host_damage_to_controller(normalized):
        return (
            "CR 614.9 redirection off the host — "
            "damage_redirects.attached_static_redirects"
        )
    if aura_controller_cast_ban(normalized) is not None:
        return "cast restriction on the host's controller — auras.controller_cast_ban"
    if aura_grants_chosen_landwalk(normalized):
        return "landwalk of the chosen type (layer 6) — auras.chosen_landwalk_grants"
    return None


#: "All damage that would be dealt to you is dealt to enchanted creature
#: instead." (Pariah.) CR 614.9's redirection printed as an Aura's **static**
#: ability: it lasts exactly as long as the Aura is attached, which is why it
#: is derived here on every damage event rather than armed as a record —
#: removal is the Aura ceasing to be attached, and there is no remembered
#: delta to undo. The same shape ``prevention._attached_damage_shields`` has one
#: module over, and for the same reason.
#:
#: "You" is CR 109.5's controller of the **Aura**, not of the creature: an
#: opponent may well control the host, and Pariah on their creature still moves
#: your damage onto it. The seat is read off the Aura at the event, so a control
#: change moves the protection with it.
#:
#: The noun is payload the way every printed noun in this file is, and both
#: attachment words are read (CR 301.5f) — an Equipment printing the sentence is
#: the same rule.
_ATTACHED_ALL_DAMAGE_REDIRECT = re.compile(
    rf"^all damage that would be dealt to you is dealt to {_ATTACHED} "
    rf"(?P<noun>{_NOUN}) instead$"
)


def aura_redirects_all_damage(line: str) -> bool:
    """Whether one printed line moves all of its controller's damage onto the
    attached permanent.

    One reader, two callers, which is this file's standing rule: the support
    gate asks it through :func:`aura_continuous_claim` so the line is claimed,
    and ``damage_redirects.attached_static_redirects`` asks it at the damage
    event so the line is *carried out*. A line claimed here and read nowhere
    else would be an Aura reporting supported while every point of damage still
    landed on its controller.
    """
    return _ATTACHED_ALL_DAMAGE_REDIRECT.match(_line_text(line)) is not None


#: "All damage that would be dealt to enchanted creature is dealt to its
#: controller instead." (Treacherous Link.) The row above's mirror, and the two
#: are not one pattern with the ends swapped: that one protects the Aura's
#: *controller* and moves the damage onto a permanent, this one protects the
#: *attached permanent* and moves it onto a player. Different recipients, so
#: different scans in ``damage_redirects`` — a record lives on the object it
#: watches, and those are two different objects.
#:
#: **"its" is the enchanted creature's**, not the Aura's. The possessive takes
#: the nearest noun phrase, which is the one the sentence has just named, and
#: the difference is the whole card: this is a {1}{B} Aura you put on an
#: *opponent's* creature so that damage aimed at it lands on them. Read as the
#: Aura's controller it would be a card that damages you.
#:
#: The noun is payload the way every printed noun in this file is, and both
#: attachment words are read (CR 301.5f) — an Equipment printing the sentence is
#: the same rule.
_ATTACHED_HOST_DAMAGE_TO_CONTROLLER = re.compile(
    rf"^all damage that would be dealt to {_ATTACHED} (?P<noun>{_NOUN}) is dealt "
    rf"to its controller instead$"
)


#: "Enchanted creature has landwalk of the chosen type." (Traveler's Cloak.)
#: CR 702.14a builds a landwalk's name out of a land type, and here the type is
#: not printed: it is the one this Aura recorded as it entered (CR 614.1c, "As
#: this Aura enters, choose a land type."). So the line grants a keyword whose
#: *word* is read off the Aura at each recompute — which is what keeps it out
#: of ``aura_keyword_grants``, whose answer is a function of the text alone.
#:
#: Both attachment words are read (CR 301.5f), like every pattern in this file.
_ATTACHED_CHOSEN_LANDWALK = re.compile(
    rf"^{_ATTACHED} creature has landwalk of the chosen type$"
)


def aura_grants_chosen_landwalk(line: str) -> bool:
    """Whether one printed line grants the host landwalk of the land type the
    attachment chose as it entered.

    One reader, two callers, which is this file's standing rule: the support
    gate asks it through :func:`aura_continuous_claim`, and
    :func:`chosen_landwalk_grants` asks it at each layer-6 recompute.
    """
    return _ATTACHED_CHOSEN_LANDWALK.match(_line_text(line)) is not None


def chosen_landwalk_grants(aura) -> tuple[str, ...]:
    """The landwalk ability *aura* gives its host — ``("islandwalk",)`` for an
    Aura that chose Island — or nothing when it prints no such line, has not
    chosen, or chose a word that names no land type.

    Read off ``effective_card`` (CR 707.2: a copy of the Cloak grants what the
    *copy* chose) and off the record the entry choice wrote. The word is put
    to ``landwalk.landwalk_requirement`` — the reader that enforces the ability
    at the declare-blockers step — so a grant nothing would enforce is never
    made.
    """
    from .enter_effects import CHOSEN_LAND_TYPE_KEY
    from .landwalk import landwalk_requirement

    chosen = str(aura.metadata.get(CHOSEN_LAND_TYPE_KEY) or "").strip().lower()
    if not chosen:
        return ()
    if not any(
        aura_grants_chosen_landwalk(line)
        for line in (aura.effective_card.oracle_text or "").splitlines()
    ):
        return ()
    walk = f"{chosen}walk"
    return (walk,) if landwalk_requirement(walk) is not None else ()


def aura_redirects_host_damage_to_controller(line: str) -> bool:
    """Whether one printed line moves all of the attached permanent's damage
    onto that permanent's controller.

    One reader, two callers, which is this file's standing rule: the support
    gate asks it through :func:`aura_continuous_claim` so the line is claimed,
    and ``damage_redirects.attached_static_redirects`` asks it at the damage
    event so the line is *carried out*. Claimed here and read nowhere else it
    would be an Aura reporting supported while every point of damage still
    landed on the creature.
    """
    return _ATTACHED_HOST_DAMAGE_TO_CONTROLLER.match(_line_text(line)) is not None


#: "Enchanted creature's **controller** can't cast creature spells."
#: (Brand of Ill Omen.) A restriction on a *player*, which is what keeps it out
#: of ``_RESTRICTIONS`` beside it: every row there is a fact about the attached
#: permanent, asked of that permanent by the step that enforces it, and there is
#: no permanent here to ask.
#:
#: The card **type** is payload for the reason every printed word in this file
#: is one: "…can't cast artifact spells" is the same sentence and must need no
#: second row. So is the seat word — CR 109.5 makes "enchanted creature's
#: controller" the controller of the *creature*, not of the Aura, and that is
#: read off the host at the gate rather than assumed to be the Aura's own.
_ATTACHED_CONTROLLER_CAST_BAN = re.compile(
    rf"^{_ATTACHED} {_NOUN}'s controller can't cast (?P<type>{_NOUN}) spells$"
)


def aura_controller_cast_ban(line: str) -> str | None:
    """The card type the enchanted permanent's controller can't cast, or None.

    One reader, two callers, which is this file's standing rule: the support
    gate asks it through :func:`aura_continuous_claim` so the line is claimed,
    and ``mixins/stack/casting.py`` asks it at CR 601.2 so the line is
    *enforced*. A printed restriction is only done when something enforces it —
    parsed and dropped, this one is an Aura that reports supported and lets the
    creature spells through.
    """
    match = _ATTACHED_CONTROLLER_CAST_BAN.match(_line_text(line))
    return match.group("type") if match is not None else None


def controller_cast_ban(game, seat: int, card) -> str | None:
    """The name of an Aura forbidding *seat* from casting *card*, or None.

    Read off the **host**, not off the Aura: the sentence says "enchanted
    creature's controller", and an Aura an opponent controls on your creature
    stops *you* casting. Every Aura on the battlefield is asked, because that is
    where the attachment record lives — an Aura that has left is no longer
    attached and so no longer says anything, with nothing to clean up.
    """
    for host_seat, host in game.permanents_with_controller():
        if host_seat != seat:
            continue
        for aura in auras_attached_to(host):
            for raw_line in (aura.effective_card.oracle_text or "").splitlines():
                banned = aura_controller_cast_ban(raw_line)
                if banned is not None and card.primary_type == banned:
                    return aura.card.name
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
