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
the artifact animation are all derived in this family now, from the Aura's own
text on every recompute. What is left in that chain is the enumeration the rest
of the migration needs: near enough one branch per card, which is the signature
of a mechanism that grows with the pool rather than with the rules.

Entries are ordered most-specific first, and each names the code that carries
it out — a line recognized here but implemented nowhere is worse than one that
fails to parse.

**The family, split by subject at the 2,000-line cap.** What an attached Aura
gives its host is ``engine/aura_grants.py``, what it forbids is
``engine/aura_restrictions.py``, the attachment record and what an Aura may be
attached to is ``engine/aura_attachment.py``, and the words all of them read a
line with are ``engine/aura_vocabulary.py``. This module keeps the gate: the
template table, the claims, :func:`aura_continuous_claim` over the derivations,
and the registration of the two CR 116.2c/d offers with
``engine/special_actions.py``, which imports this module to make sure it has
run.
"""

from __future__ import annotations

import re

from .aura_attachment import _became_aura_offer, _take_became_aura_offer
from .aura_grants import (
    _STATIC_PT_GRANT,
    _PT_GRANT_PER_COUNTER,
    _build_board_counted_penalty,
    aura_conditional_keyword_grants,
    _QUOTED_ABILITY_GRANT,
    quoted_grant_readable,
    aura_conditional_ability_grants,
    aura_keyword_grants,
    aura_keyword_removals,
    _PROTECTION_GRANT,
    _CARD_TYPE_ADDITION_GRANT,
    aura_animates_artifact,
    aura_land_animation,
    _ATTACHED_CONTROL_CHANGE,
    aura_ability_cost_reduction,
    aura_redirects_all_damage,
    aura_grants_chosen_landwalk,
    aura_redirects_host_damage_to_controller,
)
from .aura_restrictions import (
    _ignore_static_offer,
    _take_ignore_static_offer,
    aura_attacked_untap_condition,
    aura_counter_untap_condition,
    aura_color_conditioned_combat_ban,
    aura_restrictions,
    aura_combat_restriction,
    aura_block_permission,
    aura_controller_cast_ban,
)
from .aura_vocabulary import (
    _NOUN,
    _ATTACHED,
    _COLORS,
    _KEYWORDS,
    _LazyPattern,
    _TYPE_ADDITION_GRANT,
    _CREATURE_TYPE_SET,
    _line_text,
)

# Re-exported: names that moved out at the 2,000-line split and are still
# pulled from ``engine.auras`` by modules other groups were splitting in the
# same round (``mixins/helpers``, ``mixins/permanent_state``,
# ``mixins/effects``, ``mixins/stack/activation``, ``prevention``,
# ``handlers/board_misc``, ``ai_policy`` and the two declare steps), whose
# import lines were left alone. New code imports a name from the module that
# defines it.
from .aura_attachment import (BECAME_AURA_ENCHANT, BECAME_AURA_RECORD,
                              attach_aura, attached_subject_triggers,
                              auras_attached_to, detach_aura)
from .aura_grants import (AMONG_CONTROLLED_PROTECTION_COLORS,
                          CHOSEN_PROTECTION_COLOR,
                          attached_ability_cost_reduction,
                          aura_board_counted_penalty, aura_protection_colors,
                          conditional_ability_lines_for)
from .aura_restrictions import (attached_block_ceiling,
                                attached_combat_restrictions,
                                aura_restriction_active,
                                cant_be_enchanted_by_own_text)

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
    ``enchant_targets.enchant_clause_nouns``, the same three splitters the
    picker and the cast gate use, because this reader was the one Mirage's
    widening broke:
    "Enchant **red or green** creature" answered no to every branch and
    "Enchant **artifact or creature**" answered yes to the artifact one whatever
    the Aura had actually enchanted.
    """
    from .enchant_targets import enchant_clause_nouns

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
    from .line_normalization import normalize_creature_line

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
    from .ability_lines import _parse_triggered_ability

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
    from .ability_lines import _parse_activated_ability

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
    ``ability_lines._modal_trigger_ability`` performs when it builds the
    ability. Asking this gate line by line reads the head as an ordinary
    attached trigger (claimed, correctly) and then each bullet as an unclaimed
    effect, so Relic Bind reported "unimplemented aura effect: • this aura
    deals 1 damage to …" for a line the trigger already owns.

    The claim is the *builder's own answer*, not a shape test: it asks
    ``_modal_trigger_ability``, which refuses a dead mode and a condition it
    cannot read. So an Aura whose modes the engine cannot perform stays
    unclaimed and visibly unsupported, which is the whole reason this file
    stopped claiming attached triggers with a wildcard.
    """
    from .ability_lines import _modal_trigger_ability

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
    from .ability_lines import _bullets_after

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
    a hole: ``enchant_targets.enchant_line_subject`` is what the *picker* is
    built from, and the graveyard form beside it
    (``enchant_targets.enchant_graveyard_line``) is the other zone's picker,
    raised by ``_cast_target_spec`` and spent by ``_apply_aura_effect``.
    Anything else starting with the word is a subject nobody reads, and a line
    nobody reads is what leaves this gate.
    """
    from .enchant_targets import enchant_graveyard_line, enchant_line_subject

    return (
        enchant_line_subject(line) is not None or enchant_graveyard_line(line)
    )


def _aura_line_claimed(line: str, card_name: str) -> bool:
    """Whether one Aura/Equipment effect line has an implementation behind it."""
    from .keyword_lines import _is_supported_keyword_line
    from .alternative_costs import alternative_cost_claims_line
    from .cast_costs import cast_cost_claims_line
    from .cast_timing import cast_permission_line
    from .enter_effects import enter_effect_line
    from .target_requirements import must_choose_claims_line
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
        # "While an opponent is choosing targets …, that player must choose at
        # least one Flagbearer on the battlefield if able." (Coalition Flag.)
        # Not an effect the Aura has *on what it enchants* — it is the Aura's
        # own static ability about its controller's opponents, read off the
        # board at every cast and activation — so it is claimed by the table
        # that enforces it, like the restriction above, rather than by a
        # continuous-effect template with nothing continuous behind it.
        or must_choose_claims_line(line)
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
    if _CREATURE_TYPE_SET.match(normalized):
        return "creature type set (layer 4) — auras.aura_creature_type_sets"
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
