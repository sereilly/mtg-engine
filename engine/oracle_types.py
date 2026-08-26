"""Shared oracle-text data types and small text helpers.

These live in their own module (rather than engine.oracle) so anything that
needs the compiler's *types* — the grammar's lowering, the card hooks, the
handlers — can import them without an import cycle with the compiler itself.
This module imports nothing from the engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# The payload key a "…, where X is the number of <filter>" clause travels on.
# Here rather than beside either of its two users, because the grammar writes it
# and the dispatcher reads it and this module is the one both may import: a
# string agreed in two places is exactly the second copy that drifts.
X_FROM_COUNT = "x_from_count"

# The same clause, but counted **once per recipient**: "…deals damage to each
# opponent equal to the number of Islands **that player** controls" (Typhoon).
# A separate key rather than an `owner` value on the spec above, because the
# substitution in `_execute_oracle_instruction` resolves `X_FROM_COUNT` into a
# single `context.x_value` before any handler runs — there is exactly one X, and
# this phrase has one number per seat. A handler that loops seats reads this
# instead; a handler that does not never sees the key, so a lowering may only
# emit it for a recipient whose handler loops (engine/grammar/lowering/damage.py
# checks that, and refuses otherwise).
X_FROM_COUNT_PER_RECIPIENT = "x_from_count_per_recipient"

# The payload key an effect carries when the object it acts on was **bound by
# the firing trigger** rather than chosen as a target — "…that creature becomes
# green" under a block trigger (Aisling Leprechaun). Here for the same reason as
# the key above: the grammar writes it and a handler reads it.
#
# A key rather than a second instruction kind, because which object an effect
# acts on is not a different effect — fusing the binding into the kind is what
# gave `creature_blocks_or_blocked_by_nonwall` its name and its bespoke fire
# site.
SUBJECT_FROM_TRIGGER = "subject_from_trigger"

# Its one value so far: the other half of the blocking pair the trigger fired on.
BLOCK_PAIR_SUBJECT = "block_pair"

_COLOR_WORD_TO_SYMBOL: dict[str, str] = {
    "white": "W",
    "blue": "U",
    "black": "B",
    "red": "R",
    "green": "G",
}

_X_SPEND_COLOR_RE = re.compile(r"spend only (white|blue|black|red|green) mana on x")


def x_spend_color_from_text(text: str) -> str | None:
    """The single color that may be spent on X ("Spend only black mana on X."
    — Drain Life), as a mana symbol, or None when X is unrestricted."""
    match = _X_SPEND_COLOR_RE.search(text.lower())
    return _COLOR_WORD_TO_SYMBOL[match.group(1)] if match else None


@dataclass(frozen=True)
class OracleToken:
    kind: str
    value: str


@dataclass(frozen=True)
class ActivatedAbilityCost:
    mana: dict[str, int]
    requires_tap: bool = False
    # Jandor's Ring: "{2}, {T}, Discard the last card you drew this turn: Draw a
    # card." A non-mana additional cost — the ability can't be activated unless
    # that card is still in hand, and activating discards it.
    discard_last_drawn: bool = False
    # Ring of Ma'rûf: "{5}, {T}, Exile this artifact: ..." — activating exiles
    # the source permanent as part of the cost.
    exile_self: bool = False
    # Black Lotus / Bottle of Suleiman: "…, Sacrifice this artifact: …" —
    # activating sacrifices the source permanent as part of the cost, so the
    # ability still resolves after it has left the battlefield (CR 603.6).
    sacrifice_self: bool = False
    # Hobblefiend: "{1}, Sacrifice another creature: …" — a *chosen* permanent
    # rather than the source. The whole printed noun phrase is payload, so one
    # field covers every card printed this way, "a creature **with defender**"
    # (Portcullis Vine) included. None means "no such cost", never "any
    # permanent": an empty filter would let the charger eat a land, and it is
    # also the answer for a phrase the charger cannot test — the grammar refuses
    # such a line, and this reader must not disagree by charging the wider cost.
    sacrifice_filter: dict | None = None
    # Seasoned Hallowblade: "Discard a card: …" — N cards the payer chooses,
    # where `discard_last_drawn` above names its card by history and leaves the
    # payer no choice at all. Two fields because they are two costs: a card
    # could print both.
    discard_cards: int = 0
    # Sanctum of Shattered Heights: "Discard a land card or Shrine card: …" —
    # what the discarded card must be, one payload per printed alternative, OR'd.
    # A tuple because the "or" unions two *different* characteristics and a
    # single filter AND's its keys; empty is the unrestricted "Discard a card",
    # which `discard_cards` above already says exists. A phrase the card matcher
    # cannot test never reaches here — the grammar refuses the line and
    # `_chargeable_discard_filters` refuses to read one, the same pairing
    # `sacrifice_filter` describes.
    discard_filters: tuple[dict, ...] = ()
    #: "Discard a card at random" (Coral Helm). The payer picks nothing; the
    #: activation path draws the card from the hand with the module RNG, so a
    #: seeded run reproduces it.
    discard_at_random: bool = False
    # Subira: "Discard your hand: …" — every card, chosen by nobody. Its own
    # field rather than a large ``discard_cards``, because the payability check
    # is the opposite: a count can be unpayable for want of cards, and this one
    # never is.
    discard_whole_hand: bool = False
    # Waker of Waves: "{1}{U}, **Discard this card**: …". The card discards
    # *itself* to pay, which is also what says the ability functions from the
    # hand at all (CR 113.6 — an ability works only from the battlefield unless
    # something says otherwise, and a cost the card can only pay from hand says
    # exactly that). Its own field rather than a `discard_cards=1` with a
    # self-filter: the payer chooses nothing, and the ability is unactivatable
    # from anywhere else.
    discard_self: bool = False
    # Mazemind Tome: "Put a **page** counter on this artifact". A cost that adds
    # an inert marker (CR 122.1) — never unpayable, and read by nothing but the
    # card's own state trigger. The counter's printed word, or None.
    put_counter: str | None = None
    # Scavenging Ghoul: "**Remove a corpse counter from this creature**:
    # Regenerate this creature." The mirror of ``put_counter`` and the half that
    # *can* be unpayable — CR 602.1a makes a counter removal an activation cost
    # like any other, so an ability whose source has none may not be activated.
    #
    # The counter's printed word, exactly as ``put_counter`` carries it, because
    # the kinds are open (CR 122.1): "corpse", "matrix", "dream". This was a
    # substring test for one of those words inside the activation path, so an
    # ability granted with any other counter's name — Life Matrix grants one —
    # was activated for free and could be activated forever.
    remove_counter: str | None = None
    # Shacklegeist: "Tap two untapped Spirits you control: …" — N permanents the
    # payer taps, named by the printed noun phrase. Distinct from
    # ``requires_tap``, which taps the *source* and is the {T} symbol: this taps
    # other permanents and the source is not among them unless the phrase names
    # it. None means "no such cost", never "any permanent", for the reason
    # ``sacrifice_filter`` gives.
    tap_filter: dict | None = None
    tap_count: int = 0
    # Tavern Swindler: "{T}, Pay 3 life: …" — a life payment as an activation
    # cost (CR 118.3b, 119.4). A count rather than a flag, because the amount is
    # printed; 0 is the honest "no such cost", since CR 119.4b makes paying 0
    # life always legal and therefore never a restriction on activating.
    pay_life: int = 0
    # CR 606.4: a loyalty ability's cost is putting on or removing loyalty
    # counters. ``loyalty`` is the signed delta ("+1" → 1, "−2" → -2, "0" → 0);
    # ``loyalty_x_sign`` is set instead for a variable cost ("−X" → -1), whose
    # magnitude is the X the player announces on activation. ``None``/``None``
    # means the ability is not a loyalty ability at all — 0 is a real cost
    # (CR 606.5), so it cannot double as the "absent" value.
    loyalty: int | None = None
    loyalty_x_sign: int | None = None

    @property
    def is_loyalty(self) -> bool:
        """Whether this is a loyalty-ability cost (CR 606.2)."""
        return self.loyalty is not None or self.loyalty_x_sign is not None


@dataclass(frozen=True)
class OracleInstruction:
    kind: str
    value: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TriggerCondition:
    """Represents the condition half of a triggered ability.

    kind     -- semantic label, e.g. "creature_dies", "upkeep_self"
    trigger  -- the raw trigger word: "when", "whenever", or "at"
    raw_text -- the normalized condition clause as it appeared in oracle text
    payload  -- optional structured data extracted from the condition
    """
    kind: str
    trigger: str          # "when" | "whenever" | "at"
    raw_text: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedActivatedAbility:
    source_line: str
    normalized_effect: str
    supported: bool
    cost: ActivatedAbilityCost
    effect_kind: str = "unsupported"
    instruction: OracleInstruction | None = None


@dataclass(frozen=True)
class ParsedTriggeredAbility:
    """A fully parsed triggered ability: condition + effect instruction.

    source_line  -- original oracle text line
    condition    -- the parsed trigger condition
    instruction  -- the parsed effect, or None if unsupported
    supported    -- True only if both condition and effect are recognized
    effect_kind  -- mirrors the effect_kind convention used elsewhere
    """
    source_line: str
    condition: TriggerCondition
    instruction: OracleInstruction | None
    supported: bool
    effect_kind: str = "unsupported"


@dataclass(frozen=True)
class ModalOption:
    """One mode of a "Choose one —" modal spell.

    label        -- human-readable bullet text (original case), for the UI prompt
    instruction  -- the parsed effect for this mode, or None if unsupported
    effect_kind  -- mirrors the effect_kind convention used elsewhere
    supported    -- True only if the mode's effect was recognized
    """
    label: str
    instruction: OracleInstruction | None
    effect_kind: str = "unsupported"
    supported: bool = False


@dataclass(frozen=True)
class OracleProgram:
    supported: bool
    effect_kind: str
    reason: str
    normalized_text: str
    instructions: tuple[OracleInstruction, ...] = ()
    activated_abilities: tuple[ParsedActivatedAbility, ...] = ()
    triggered_abilities: tuple[ParsedTriggeredAbility, ...] = ()
    static_lines: tuple[str, ...] = ()
    # Modes of a "Choose one —" modal spell, in bullet order. Empty for
    # non-modal cards. The player chooses one mode when the spell is cast.
    modes: tuple[ModalOption, ...] = ()
    # "Choose one **or more** —" (Sublime Epiphany, CR 700.2d). How many of the
    # modes above may be taken, not merely how many the UI should offer: the
    # cast path refuses a second mode without it, because a spell that let its
    # controller pick two modes it does not have is a spell doing something the
    # card never said. Default False keeps every "Choose one —" exactly as it
    # was.
    modes_at_least: bool = False


# Number words, shared with the text-keyed derivation tables that read a count
# out of a printed line: draw_step_modifiers, land_play_allowance,
# untap_restrictions. `engine/grammar/` reads its own numbers in the lexer.
_NUMBER_WORDS = {
    "a": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


# CR 207.2c: an ability word is italic flavour in front of an ability and has
# **no rules meaning at all**. Stripping one is therefore not a guess about what
# the card does — it is the rule — which is why this is a plain list of the
# printed words rather than a per-card exception. Only "battalion" (Makeshift
# Battalion) is in the pool today; the rest are here because a word left out is
# a card whose whole line fails to parse for a reason the parser is allowed to
# ignore, and because the list is data about Magic rather than about this pool.
ABILITY_WORDS = frozenset({
    "adamant", "addendum", "alliance", "battalion", "bloodrush", "boast",
    "celebration", "channel", "chroma", "cohort", "constellation", "converge",
    "corrupted", "council's dilemma", "coven", "delirium", "descend",
    "domain", "eminence", "enrage", "fateful hour", "ferocious", "formidable",
    "grandeur", "hellbent", "heroic", "imprint", "inspired", "join forces",
    "kinship", "landfall", "lieutenant", "magecraft", "metalcraft", "morbid",
    "pack tactics", "parley", "radiance", "raid", "rally", "revolt",
    "spell mastery", "strive", "sweep", "tempting offer", "threshold",
    "undergrowth", "will of the council",
})

#: The dashes Scryfall prints between an ability word and its ability.
_ABILITY_WORD_DASHES = ("—", "–", "-")


def strip_ability_word(line: str) -> str:
    """*line* without a leading ability word (CR 207.2c), if it has one.

    Read by both front ends — ``engine/oracle.py``'s line normalizer and
    ``engine/grammar``'s line parser — because a word stripped on one side only
    is a line the two halves of the pipeline disagree about.
    """
    for dash in _ABILITY_WORD_DASHES:
        head, sep, tail = line.partition(f" {dash} ")
        if sep and head.strip().lower() in ABILITY_WORDS:
            return tail.lstrip()
    return line

# `_instruction`, `parse_number_token`, its lenient `_parse_number_token` twin
# and `_extract_mana_cost_from_text` stood beside it. All four were
# `engine/parsing/`'s toolkit — the shorthand every rule built its instruction
# with, the two readers a rule ran over a clause it had already decided to claim
# — and all four went with the registry rather than being left as a second way
# to do what the grammar's lexer and lowering already do.


_MANA_TOKEN_RE = re.compile(r"\{([^}]+)\}")
