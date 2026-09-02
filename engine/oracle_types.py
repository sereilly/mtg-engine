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

# The resolution-scratchpad key a discard offered to several seats records its
# per-seat tally under — ``{seat: cards discarded}`` — read by the damage that
# is sized from it ("3 minus the number of cards **they** discarded this way",
# Mind Bomb). Beside ``discarded_count`` rather than replacing it: that one is a
# single number for the whole resolution, which answers the wrong question the
# moment more than one seat discards — the last seat to answer would decide
# everybody's number. Here for the reason the keys above are: the grammar's
# lowering writes it into a payload, a handler seeds it and the prompt's answer
# fills it in, and a second spelling is how those three come apart.
DISCARDED_BY_SEAT = "discarded_by_seat"

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

_COLOR_WORD = "white|blue|black|red|green"
_X_SPEND_COLOR_RE = re.compile(
    rf"spend only ({_COLOR_WORD})(?: and/or ({_COLOR_WORD}))? mana on x"
)


def x_spend_colors_from_text(text: str) -> tuple[str, ...]:
    """The colours that may be spent on X, **in the order the card prints
    them**, or an empty tuple when X is unrestricted.

    A tuple rather than the single symbol this used to return: "Spend only
    black **and/or red** mana on X." (Soul Burn) names two, and a reader that
    can hold only one answered ``None`` — which is the answer for a card with
    no restriction at all, so the restriction was silently unenforced rather
    than refused.

    The order is load-bearing, not cosmetic. With more than one colour allowed
    the split of X between them is the caster's (CR 601.2h), and the engine has
    no channel to ask; ``casting._x_color_allocations`` spends the printed order
    as its preference, taking as much of the first-named colour as the pool
    allows. That is the caster-favourable reading for the one card in the pool
    that can tell the difference — Soul Burn gains life capped by the {B} spent
    on X, and black is the colour it names first.
    """
    match = _X_SPEND_COLOR_RE.search(text.lower())
    if match is None:
        return ()
    return tuple(
        _COLOR_WORD_TO_SYMBOL[word] for word in match.groups() if word is not None
    )


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
    #: How many of them. "Sacrifice **a** creature" (Hobblefiend) is one;
    #: "Sacrifice this artifact **and any number of** creatures you control"
    #: (Sword of the Ages) is a set whose size the payer chooses, announced on
    #: activation. Beside the filter for the reason ``remove_counter_count`` is
    #: beside its kind: only a fixed count can make an ability unpayable, and
    #: "any number" never can, since zero is a number (CR 601.2h).
    sacrifice_count: "int | str" = 1
    #: City of Shadows: "{T}, Exile **a creature you control**: ..." /
    #: Necropolis: "Exile **a creature card from your graveyard**: ..." - a
    #: *chosen* object rather than the source, which is what ``exile_self``
    #: above names. Its own field for the reason ``sacrifice_filter`` is one
    #: beside ``sacrifice_self``: a chosen payment needs a picker, a
    #: payability check and a record of what it ate, and the source needs
    #: none of the three. None means "no such cost", never "anything": an
    #: empty filter would let the charger eat a land.
    exile_filter: dict | None = None
    #: Which zone that payment comes out of - ``"battlefield"`` (a permanent
    #: the payer controls) or ``"graveyard"`` (a card in the payer's own).
    #: Beside the filter rather than inside it because the two enumerate
    #: different kinds of object, and a matcher for one cannot answer about
    #: the other (CR 613.1: a card in a zone has no computed characteristics
    #: at all).
    exile_zone: str = "battlefield"
    #: Whose zone that payment comes out of: ``"you"`` (the payer's own pile,
    #: Necropolis) or ``None`` for **any one player's** ("from a graveyard" /
    #: "from a single graveyard", Night Soil). Beside ``exile_zone`` rather
    #: than folded into it because they answer different questions — which zone
    #: and whose — and a charger that read one as the other would enumerate the
    #: wrong pile and pay nothing while the ability still resolved.
    exile_zone_owner: str | None = "you"
    #: How many objects that payment eats. "Exile **two** creature cards"
    #: (Night Soil); one everywhere else. Beside the filter for the reason
    #: ``sacrifice_count`` is: only a count can make the cost unpayable, and
    #: one card is no more a payment of a two-card cost than none is
    #: (CR 601.2h).
    exile_count: int = 1
    #: "…from **a single** graveyard" (Night Soil). Every card must come out of
    #: the *same* pile. Its own flag rather than a narrowing of the filter,
    #: because the filter is asked of one card at a time and cannot say it —
    #: and dropped, the cost would be payable with one card from each of two
    #: graveyards, which is strictly cheaper than the card prints.
    exile_same_zone: bool = False
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
    #: How many of them. The Mana Batteries print "Remove **any number of**
    #: charge counters from this artifact", where Scavenging Ghoul prints "a".
    #: An int is a fixed count; ``"any"`` is the payer's choice, announced on
    #: activation the way an X is (CR 601.2b), and what the effect then reads
    #: back is how many actually came off.
    #:
    #: Beside ``remove_counter`` rather than folded into it, because the two
    #: answer different questions and only one of them can be unpayable: a fixed
    #: count needs at least that many on the permanent, while "any number" is
    #: payable with none at all (CR 601.2h — zero is a number).
    remove_counter_count: "int | str" = 1
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
    #: Earthlore: "**Tap enchanted land**: Target blocking creature gets +1/+2
    #: until end of turn." An Aura whose cost taps the permanent it is attached
    #: to — the host, never the Aura itself, which is what ``requires_tap``'s
    #: ``{T}`` means and why this is a separate field rather than that flag.
    #: A pre-symbol templating of the same payment: nothing else can pay it, so
    #: there is no picker and no filter, only the attachment record.
    #:
    #: Last in the field order deliberately: ``parse_activated_ability_cost``
    #: builds this with six positional arguments, so a field inserted among
    #: them silently rebinds one of the six.
    tap_attached: bool = False
    #: Merseine: "**Pay enchanted creature's mana cost**: Remove a net counter
    #: from this Aura." A mana cost read off the *host*, which the ``mana``
    #: dict above cannot carry: that dict is fixed when the card compiles, and
    #: this number is whatever the enchanted permanent's printed cost happens
    #: to be at the moment of activation (CR 202.1, CR 601.2f-h). So the flag
    #: says *where the cost comes from* and the activation path builds the
    #: symbols; an ability with this set and no host is unpayable rather than
    #: free.
    #:
    #: After ``tap_attached`` for that field's stated reason: the six
    #: positional arguments ``parse_activated_ability_cost`` passes are at the
    #: front, so a field inserted among them silently rebinds one of them.
    mana_from_attached: bool = False

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
    # "Tap **an** untapped Merfolk you control" (Vodalian War Machine),
    # "Tap **an** untapped Swamp you control" (Hecatomb), "Tap **an** untapped
    # snow land you control" (Karplusan Giant). The same article as "a" before
    # a vowel, and its absence was not a missing spelling but three **free
    # abilities**: `oracle._chargeable_tap_cost` reads the count through this
    # table, got 0, and charged no tap at all — while the grammar's own amount
    # reader had always read "an" as one and admitted the line.
    "an": 1,
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


#: Seats a resolution records **per object**, keyed by the printed referent that
#: names one — and by the ``OracleExecutionContext.results`` key the step that
#: knows the answer writes it under.
#:
#: One table with two readers, in the shape this repo keeps arriving at: the
#: grammar's lowering turns "the player who controlled that creature the last
#: time it became blocked by that Wall" into a key, and the handler that swept
#: the board writes the map that key names. Spelling the string out on both
#: sides would be a rule with two readers free to disagree, and the way it would
#: fail is silent — a lowering emitting a key nothing writes compiles the card
#: supported and reanimates out of nobody's graveyard.
#:
#: The value under each key is ``{permanent_id: seat}``. A loop over those same
#: objects (``for_each``) resolves it to the one seat per iteration, which is
#: what makes the record readable from inside a per-object effect.
#: What "**exiled this way**" names (Martyr's Cry). The `produced` marker an
#: exiling sweep stamps, and the ``OracleExecutionContext.results`` key it
#: records the swept objects under — the destroy family's ``destroyed_this_way``
#: pair one zone over, and separate from it because a sweep that exiles kills
#: nothing, so a loop reading the destroy record would run zero times.
#:
#: Here rather than beside either reader, because the readers are on opposite
#: ends of the pipeline: the lowering gates the printed phrase on the marker and
#: the handler writes the objects. This module imports nothing from the engine,
#: so both can reach it.
EXILED_THIS_WAY = "exiled_this_way"
EXILED_THIS_WAY_OBJECTS = "exiled_this_way_objects"

#: What "**tapped this way**" names (Raiding Party, Siege Striker's sibling
#: sentence). The count is ``tapped_this_way`` — the key ``tap_all_matching``
#: has recorded since Monsoon — and this is the *objects* beside it, for the
#: sentence that asks a question about each one individually rather than about
#: how many there were.
#:
#: Two keys for the same step, exactly as the destroy family carries two: a
#: count answers "where X is the number of Islands tapped this way" and a set
#: answers "for each creature tapped this way, that player chooses…". Unlike a
#: destruction the objects are still on the battlefield, so a *narrower*
#: sentence could ask the board — but which of them this effect tapped is not
#: something the board records, and "all tapped creatures" is a different and
#: larger set.
TAPPED_THIS_WAY = "tapped_this_way"
TAPPED_THIS_WAY_OBJECTS = "tapped_this_way_objects"

#: What "**chosen this way**" names (Raiding Party). The permanents a
#: resolution-time pick named, accumulated across every iteration and every
#: seat that was asked — "then destroy all Plains that weren't chosen this way
#: **by any player**" is one question about all of the answers, and no single
#: prompt holds it.
#:
#: Its own key rather than ``CHOSEN_TARGET_PERMANENTS`` beside it, for that
#: constant's own reason one line up: those are permanents a spell *targeted*
#: at announcement (CR 601.2c), and these were never targeted at all — a
#: sentence reading one as the other would find an empty set on every card that
#: prints the other.
CHOSEN_THIS_WAY_OBJECTS = "chosen_this_way_objects"


#: How many cards a "puts the cards from their hand on top of their library"
#: step moved (Jester's Mask). The ``results`` key the handler writes and the
#: ``produced`` marker the "search that player's library for **that many**
#: cards" behind it is gated on — here for ``EXILED_THIS_WAY``'s reason, that
#: the two readers sit at opposite ends of the pipeline.
HAND_CARDS_TO_LIBRARY = "hand_cards_to_library"


#: "**Choose X target attacking creatures.** For each of those creatures, …"
#: (Winter's Chill.) The permanents a targeting sentence named, recorded so the
#: loop behind it has a set to walk: the spell chose them at announcement
#: (CR 601.2c) and nothing about the board says which attacking creatures those
#: were. Here for ``EXILED_THIS_WAY``'s reason — the lowering gates the printed
#: "those creatures" on the marker and the handler writes the objects, and the
#: two sit at opposite ends of the pipeline.
CHOSEN_TARGET_PERMANENTS = "chosen_target_permanents"


#: The seat "destroy enchanted land" records: the controller of the permanent
#: the Aura was attached to, read *before* the destroy (CR 608.2h, idiom 6) so
#: the sentence behind it — "and this Aura deals 2 damage to **that land's
#: controller**" (Orcish Mine) — has a seat to name. By resolution the land is a
#: card in a graveyard, which CR 400.7 makes a different object no board read
#: can find a controller for; under a control-change effect that seat was never
#: its owner either.
#:
#: Here rather than beside the lowering that gates on it, for ``EXILED_THIS_WAY``'s
#: reason: the ``destruction`` handler writes it, the ``damage`` handler reads
#: it and ``grammar/lowering/_records._PRODUCES`` declares it, so the three sit
#: at opposite ends of the pipeline and a second spelling would make the
#: producer gate vacuous while the handler read an empty record.
ATTACHED_PERMANENT_CONTROLLER = "attached_permanent_controller"


PER_OBJECT_SEAT_RECORDS: dict[str, str] = {
    "controller_when_blocked": "blocked_controller_seats",
    # "For each creature exiled this way, **its controller** draws a card."
    # (Martyr's Cry.) The bare possessive, which inside a loop over objects an
    # earlier step swept off the battlefield names that object's controller —
    # and has to be read off a record, because CR 400.7 makes the exiled card a
    # new object that no battlefield read can find a seat for (idiom 6).
    "controller": "swept_controller_seats",
}


# ---------------------------------------------------------------------------
# Caches whose values are the compiler's answers
# ---------------------------------------------------------------------------
#
# Turning the grammar off and back on is a thing the engine genuinely does —
# `tests/engine/test_front_end_safety.py` swaps `oracle._grammar_instruction`
# for a stub to measure what the card hooks would read on their own. That swap
# is only reversible if every cache holding a *compiled* answer is emptied on
# the way in and on the way out, and clearing `_compile_card_oracle` alone is
# not enough: three more caches sit downstream of it.
#
# `engine/granted_abilities.granted_ability_supported` is the one that
# collected, and how it collected is the reason this is a registry rather than
# a longer `cache_clear()` line. It compiles the quoted text of a granted
# ability on a probe card to decide whether the engine can read it. The live
# pass had already cached the pool's grants under their own keys, so the
# stubbed pass mostly *hit* — but it asked two questions the live pass never
# had, the lowercased period-stripped forms of Dread Wight's and Musician's
# granted lines, and cached **False** for both. Those two keys are the ones
# `scripts/parse_coverage.py` asks.
#
# So every compiled program still came back identical and nothing looked
# wrong; the failure surfaced hundreds of tests later, in a different file, as
# two unclaimed sentences. A stale cache does not fail where it is written,
# and two poisoned keys out of seventy-four are not visible from the outside.
#
# Registered by the caches themselves rather than listed here, because a list
# of cache names is the same second copy as a list of fire sites: the fourth
# one is added by whoever writes it, not by whoever remembers this comment.
# This module is where the registry lives because it imports nothing from the
# engine, so `oracle` and the modules that import `oracle` can both reach it.
_COMPILATION_CACHES: list[Any] = []


def compilation_cache(func):
    """Register an ``lru_cache``d function whose values came from the compiler.

    Apply *outside* ``functools.lru_cache`` (nearest the ``def``), so what is
    registered is the wrapper carrying ``cache_clear``::

        @compilation_cache
        @lru_cache(maxsize=None)
        def granted_ability_supported(...): ...
    """
    _COMPILATION_CACHES.append(func)
    return func


def clear_compilation_caches() -> None:
    """Empty every cache holding a compiled answer.

    One call, so a caller that swaps a piece of the compiler out does not have
    to know how many caches there are — which is the whole of what went wrong
    before it existed.
    """
    for cached in _COMPILATION_CACHES:
        cached.cache_clear()
