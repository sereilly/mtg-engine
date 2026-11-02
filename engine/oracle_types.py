"""Shared oracle-text data types and small text helpers.

These live in their own module (rather than engine.oracle) so anything that
needs the compiler's *types* — the grammar's lowering, the card hooks, the
handlers — can import them without an import cycle with the compiler itself.
This module imports nothing from the engine at run time: the one engine name
its annotations borrow (``ActivatedAbilityCost``, its own module since round
kg3) is imported for type checking only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .activated_ability_cost import ActivatedAbilityCost

# The payload key a "…, where X is the number of <filter>" clause travels on.
# Here rather than beside either of its two users, because the grammar writes it
# and the dispatcher reads it and this module is the one both may import: a
# string agreed in two places is exactly the second copy that drifts.
X_FROM_COUNT = "x_from_count"

# The value a filter's numeric bound carries when the card printed **X** rather
# than a number: "each artifact with mana value **X** or less" (Meltdown),
# "a creature card with mana value X or less" (Citanul Flute). The same string
# every *amount* in the engine uses for a value the announcement supplies, so a
# reader that already resolves "x" needs no new vocabulary — and here for
# ``X_FROM_COUNT``'s reason exactly: the grammar writes it, the dispatcher
# substitutes it, and a string agreed in two places is the copy that drifts.
X_BOUND = "x"


def substitute_x_bounds(payload: dict, x_value: int | None) -> dict:
    """*payload* with every ``X_BOUND`` filter bound resolved to *x_value*.

    CR 601.2b announces X as the spell is cast and CR 608.2 applies the effect
    with that number, so the substitution belongs at the single dispatch point
    — the same argument ``X_FROM_COUNT``'s does one key up, and the same
    payoff: every effect family gets the clause at once instead of the one
    handler that happened to need it.

    Recurses because a bound reaches the matcher twice, on the instruction's
    own filter keys and inside the ``targets`` description the picker reads,
    and a substitution honoured in one of them is a sweep that destroys a
    different set from the one it offered.

    Returns *payload* itself when nothing carries the bound, which is every
    instruction in the pool but three — the cost of the scan is one dict walk
    and the cost of getting it wrong is ``int("x")``.

    An unannounced X resolves to 0, which is what ``resolve_amount`` reads it
    as everywhere else. That is this engine's fallback for an announcement
    CR 107.3a leaves with the caster and the caster did not make -- **not**
    CR 107.3b, which locks X at 0 only for a spell cast while paying neither
    its mana cost nor an alternative cost that includes X.
    """
    if not _carries_x_bound(payload):
        return payload
    resolved = max(0, int(x_value or 0))
    return _substituted(payload, resolved)


def carries_x_bound(payload: object) -> bool:
    """Whether *payload* holds a filter bound the announcement supplies (X)."""
    return _carries_x_bound(payload)


def without_x_bounds(payload: dict) -> dict:
    """*payload* with every ``X_BOUND`` filter bound **removed**.

    For the one reader that asks before X exists: a target picker enumerating
    "target creature with mana value **X** or less" (Dominate) ahead of the X
    prompt (CR 601.2b) cannot answer the bound, and reading it as 0 would offer
    nothing. The bound is not dropped from the card — the announcement gate and
    the resolution each re-ask it through :func:`substitute_x_bounds` with the
    number the caster announced — so the picker's list is a hint (idiom 9), never
    the last word.
    """
    if not _carries_x_bound(payload):
        return payload
    return _stripped(payload)


def _stripped(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _stripped(inner)
            for key, inner in value.items()
            if not (
                key in _BOUND_KEYS
                and isinstance(inner, dict)
                and inner.get("value") == X_BOUND
            )
        }
    if isinstance(value, list):
        return [_stripped(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_stripped(item) for item in value)
    return value


#: The filter keys whose value is a ``{op, value}`` bound. All three, because
#: emitting one and resolving another is how a restriction vanishes silently —
#: the argument ``object_filter_payload`` already makes about emitting them.
_BOUND_KEYS = ("mana_value", "power", "toughness")


def _carries_x_bound(value: object) -> bool:
    if isinstance(value, dict):
        for key, inner in value.items():
            if (
                key in _BOUND_KEYS
                and isinstance(inner, dict)
                and inner.get("value") == X_BOUND
            ):
                return True
            if _carries_x_bound(inner):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_carries_x_bound(item) for item in value)
    return False


def _substituted(value: object, resolved: int) -> object:
    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            if (
                key in _BOUND_KEYS
                and isinstance(inner, dict)
                and inner.get("value") == X_BOUND
            ):
                out[key] = {**inner, "value": resolved}
            else:
                out[key] = _substituted(inner, resolved)
        return out
    if isinstance(value, list):
        return [_substituted(item, resolved) for item in value]
    if isinstance(value, tuple):
        return tuple(_substituted(item, resolved) for item in value)
    return value

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

# The ``sequence`` payload key saying its steps are **one printed damage
# sentence** the lowering split into an instruction per clause or per recipient
# — "…deals 2 damage to any target **and** 3 damage to you" (Orcish
# Artillery), "…to target player **and** each creature that player controls"
# (Heart of Bogardan) — and so one simultaneous damage event (CR 608.2f): the
# handler runs the steps inside one dealing (``engine/simultaneous_damage.py``),
# so "whenever <source> deals damage" sees the sentence's total once. Written
# by ``grammar/lowering/_conjuncts.py``, read by ``handlers/control_flow``'s
# ``sequence``; a sequence of two *sentences* (Tracker's bite and bite back)
# never carries it, because two sentences are two events.
ONE_DEALING = "one_dealing"

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

# "Each player may pay any amount of mana. Then each player creates … tokens
# equal to **the amount of mana they paid this way**." (Liege of the Hollows.)
# ``{seat: mana paid}``, per seat for ``DISCARDED_BY_SEAT``'s reason and one
# step further: there is no scalar twin at all, because no sentence in the pool
# asks about the total. The number exists nowhere until each seat has answered
# its own prompt, so the handler seeds a zero per seat and each answer fills
# one in — a seat the map never mentioned would otherwise read as the last
# answer given.
MANA_PAID_BY_SEAT = "mana_paid_by_seat"

# Its twin one zone over: ``{seat: cards drawn}`` for "Each player may draw up
# to two cards", read by the sentence that is sized from the *shortfall* ("For
# each card less than two a player draws this way, that player gains 2 life",
# Truce). Per seat rather than a single number for the reason above — each
# player's answer is their own, and one key would let the last seat to answer
# decide everybody's life gain.
DREW_BY_SEAT = "drew_by_seat"

# The hand pick's twin of the two above: ``{seat: [cards chosen]}`` for "Each
# player chooses a card in their hand. Then each player reveals their chosen
# card. …" (Stronghold Gambit). Per seat for the same reason — every player's
# answer is their own, and the single ``chosen_hand_cards`` list one seat's
# pick writes would be overwritten by the next seat to answer, leaving the
# sentences behind it reading one player's card as everybody's.
CHOSEN_HAND_CARDS_BY_SEAT = "chosen_hand_cards_by_seat"

# "…then this enchantment deals damage to the player equal to **the number of
# cards they drew this way**." (Malignant Growth.) The scalar twin of the
# per-seat tally above: one draw, one seat, one number - the same shape
# ``discarded_count`` has for the single-seat discard beside the per-seat one,
# and separate for that pair's reason. A trigger drawing for one player and a
# spell drawing for everybody are two sentences, and a shared key would let one
# seat's answer be read as another's.
#
# Here rather than beside either end because both ends spell it: the handler
# writes it, ``lowering/_records`` declares it and ``grammar/records`` reads it
# back, and a second spelling is what makes a producer gate vacuous while the
# amount reads an empty record.
DREW_COUNT = "drew_count"

# "Target player reveals their hand. **For each blue instant card revealed this
# way**, …" (Sirocco.) The cards a hand reveal showed, as cards: the sentence
# behind it narrows by colour and card type, which the *names* the client is
# sent cannot be asked. Here rather than beside either end for the reason above
# — the handler writes it and a lowering gates on it, and this module imports
# nothing from the engine so both can reach it.
#
# Separate from ``revealed_card``, which holds the single card a top-of-library
# or random-from-hand reveal named: one is a set and the other is an object, and
# a reader handed the wrong one would ask a list what its mana value is.
REVEALED_HAND_CARDS = "revealed_hand_cards"

# "Reveal any number of blue cards in your hand. **Counter target spell unless
# its controller pays {1} for each card revealed this way.**" (Brine Seer and
# the eleven cards printed with it.) How many cards the reveal in front of the
# sentence showed — a *number*, where the key above is the cards themselves.
#
# Two records for one step, exactly as ``TAPPED_THIS_WAY`` and
# ``TAPPED_THIS_WAY_OBJECTS`` are two: a "for each card revealed this way"
# spends a count and nothing re-asks what the cards were, while a sentence that
# narrows ("for each **blue instant** card revealed this way", Sirocco) can only
# be answered off the cards. A reader handed the wrong one would ask a list how
# large it is or a number what colour it is.
#
# Here rather than beside either end for ``DREW_COUNT``'s reason: the handler
# writes it, ``lowering/_records`` declares it and ``grammar/records`` reads it
# back, and a second spelling is what makes a producer gate vacuous while the
# amount reads an empty record.
REVEALED_THIS_WAY = "revealed_this_way"

#: "**Each player** may reveal any number of creature cards from their hand.
#: Then each player creates a 2/2 green Bear creature token **for each card
#: they revealed this way**." (Kamahl's Summons.) The per-seat twins of
#: ``REVEALED_THIS_WAY`` and ``REVEALED_HAND_CARDS`` — ``{seat: count}`` and
#: ``{seat: [cards]}`` — for ``DISCARDED_BY_SEAT``'s reason: a single number is
#: whichever seat answered last, and the sentence behind asks every seat its
#: own. Written as each seat's reveal is answered
#: (``choices/hand._record_chosen_cards_in_hand``), read by the token maker's
#: ``seat_record`` count.
REVEALED_BY_SEAT = "revealed_by_seat"
REVEALED_HAND_CARDS_BY_SEAT = "revealed_hand_cards_by_seat"

# "**Each player reveals the top card of their library.** If all cards revealed
# this way are creature cards, put those cards onto the battlefield under their
# owners' control." (Game Preserve.) One card per seat, kept as ``{seat: card}``
# rather than as a flat list — which is the whole of what the second sentence
# needs and nothing else can supply: the cards are still on top of their own
# libraries (CR 701.20a moves nothing), and "under **their owners'** control"
# names a different battlefield for each of them.
#
# A third record beside the two above for their stated reason: ``REVEALED_THIS_
# WAY`` is a count and ``REVEALED_HAND_CARDS`` a flat set out of one hand, and a
# reader handed either would lose which seat each card belongs to.
REVEALED_TOP_CARDS_BY_SEAT = "revealed_top_cards_by_seat"

#: What the event "a player chooses one or more targets" leaves for the effect
#: behind it: the stack object those targets were chosen for (CR 603.10). Not a
#: scratchpad key a *step* writes — the firing event froze it, into the
#: trigger's context under ``stack_targets.TARGETS_CHOSEN_ITEM`` — but named
#: here beside the per-seat reveal record because the lowering asks for both
#: the same way: "the target or targets" is a back-reference, and a sentence
#: printing it under any other event would compile clean and change nothing.
EVENT_CHOSEN_TARGETS = "event_chosen_targets"

#: The ``StackItem.choices`` key that says **this object's announcement named
#: no target, and that was a legal announcement** (CR 601.2c: "up to one target
#: creature" at zero; CR 115.6: such an object is not targeted at all).
#:
#: A record rather than something read off the empty target fields, because
#: the fields cannot say it. They are empty for three different reasons — the
#: announcement was complete and named nobody, a headless caller announced
#: bare and left the pick to the handler (the standing convention), and a
#: trigger whose target its handler finds for itself — and every resolver
#: under them answers the empty case with a **scan** of the battlefield
#: (``handlers/_targets.pick_target_permanent``). The scan knows what the
#: sentence names and nothing about what may be targeted, so an "up to one
#: target creature" that could legally name only nobody went on to act on a
#: creature with shroud: Barrin, Tolarian Archmage and Roaming Ghostlight
#: bounced one, Feline Sovereign destroyed a shrouded artifact, and the +1 of
#: three planeswalkers landed on one (Basri Ket's and Basri, Devoted
#: Paladin's counter, Garruk, Unleashed's +3/+3).
#:
#: Written by ``Game.record_no_target_named`` and read by
#: :func:`named_no_target`; nothing else spells the key. Here rather than in
#: ``engine/stack_targets.py``, whose subject it is, because the reader is a
#: handler floor (``handlers/_targets``) and that module sits above it in the
#: import order — this file imports nothing from the engine.
NAMED_NO_TARGET = "named_no_target"


def named_no_target(choices) -> bool:
    """Whether the object these *choices* ride announced **zero targets**
    (CR 601.2c) — see :data:`NAMED_NO_TARGET`.

    Takes the dict rather than the stack item because both ends hold it: the
    item at the push and the ``OracleExecutionContext`` at resolution carry
    the same object.
    """
    return bool(choices) and bool(choices.get(NAMED_NO_TARGET))


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

# The trigger-context key under which the entry seam freezes the entering
# **object itself**, beside its id — CR 608.2h's last-known information. "…its
# controller creates a token that's a copy of that creature" (Dual Nature) still
# makes the token when the creature has left by resolution, copying it as it
# last existed on the battlefield; the id alone resolves to nothing then
# (CR 400.7). The ``dead_card`` precedent one fire site over: a key the
# announcement writes and one handler reads, so it is a constant here rather
# than a string spelled twice.
EVENT_SUBJECT_LAST_KNOWN = "event_subject_last_known"

# ``targets["count"]`` for an announcement whose **size** a CR 601.2b optional
# additional cost fixes: ``{"base": 1, "per_cost": {"{1}{R}": 1, "{1}{G}": 1}}``
# is Primitive Justice's "Destroy target artifact. For each additional {1}{R}
# you paid, destroy another target artifact. For each additional {1}{G} you
# paid, destroy another target artifact…".
#
# A dict beside the ``int`` and the string ``"x"`` the same field already
# carries, because it is the same question with a third source for the number:
# a printed literal, the X announced under CR 601.2b, and now the *count of
# payments* announced in that same step. CR 601.2c fixes the number of targets
# as the spell is announced, one step after the payment, so it is knowable at
# the announcement and nowhere earlier — the pool that paid it is empty by
# resolution (CR 500.5).
#
# Here rather than beside any one of its readers: the grammar's lowering writes
# it, ``engine/targeting.py`` turns it into a picker spec and
# ``engine/legality_cast_gates.py`` gates the announcement against it. Three copies of two
# dict keys is exactly the drift this module exists to prevent, and the quiet
# direction of that drift is a spell whose targets nobody counted.
COST_TARGET_BASE = "base"
COST_TARGET_PER = "per_cost"


def cost_target_count(count: object, paid: dict | None) -> int | None:
    """How many targets *count* names, given the CR 601.2b payments *paid*.

    None when *count* is not a cost-derived description at all, which is every
    other spell in the pool — a caller may therefore ask unconditionally and
    treat None as "this announcement is not sized by a payment".

    *paid* is the ``{offer: times}`` map the casting path records under
    ``additional_costs_paid``, keyed by ``mana_payment.mana_cost_label``'s
    canonical spelling — the same key the lowering wrote, because both sides go
    through that one function (see ``lowering/_cost_records.optional_cost_key``).
    An offer the caster declined is simply absent, which is zero repetitions and
    the base count alone.
    """
    if not isinstance(count, dict) or COST_TARGET_BASE not in count:
        return None
    total = int(count.get(COST_TARGET_BASE) or 0)
    for offer, per in (count.get(COST_TARGET_PER) or {}).items():
        total += int(per) * int((paid or {}).get(str(offer), 0) or 0)
    return max(0, total)

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
    no channel to ask; ``pool_payment._x_color_allocations`` spends the printed order
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
    # "**An opponent** chooses one —" (Fatal Lore, Library of Lat-Nam,
    # Misfortune). Who picks the mode, when the head names somebody other than
    # the spell's controller (CR 700.2e). None is every other modal card, where
    # the controller picks (CR 700.2a) and the cast carries the choice.
    #
    # It has to be on the program because the *cast path* is what reads it: a
    # caster who could name the mode of one of these three spells would take
    # the half that suits them, which is the opposite of what all three cards
    # are printed to do.
    mode_chooser: str | None = None


# Number words, shared with the text-keyed derivation tables that read a count
# out of a printed line: draw_step_modifiers, land_play_allowance,
# untap_restrictions. `engine/grammar/` reads its own numbers in the lexer.
_NUMBER_WORDS = {
    "a": 1,
    # "Tap **an** untapped Merfolk you control" (Vodalian War Machine),
    # "Tap **an** untapped Swamp you control" (Hecatomb), "Tap **an** untapped
    # snow land you control" (Karplusan Giant). The same article as "a" before
    # a vowel, and its absence was not a missing spelling but three **free
    # abilities**: `chargeable_costs._chargeable_tap_cost` reads the count through this
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

    Read by both front ends — ``engine/line_normalization.py``'s line normalizer and
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
#: What a **search** put onto the battlefield — "…put that card onto the
#: battlefield, then shuffle. **That Dragon** gains haste until end of turn.
#: Exile **it** at the beginning of the next end step." (Zirilan of the
#: Claw.)
#:
#: Permanent ids, and one record shape with the reanimation's
#: (``handlers/reanimation.REANIMATED_PERMANENTS``) on purpose: a sentence reading
#: "that creature" should not have to care which step put the permanent
#: there, so both are members of ``lowering/_record_keys._RECORDED_PERMANENTS``
#: and every reader asks that set rather than a key.
#:
#: Here rather than beside a reader, for ``EXILED_THIS_WAY``'s reason
#: exactly: the writer is the *pending-choice* resolution (a search suspends
#: on a prompt, so nothing else can say which permanent it placed) and the
#: readers are lowerings. This module imports nothing from the engine, so
#: both ends can reach it.
SEARCHED_PERMANENTS = "searched_permanents"

EXILED_THIS_WAY = "exiled_this_way"

#: "…until **you put a card into your hand**" (Tainted Pact). The cards a step
#: of this effect put into a hand out of exile — a record because a hand does
#: not say which of its cards an effect added. Here for ``EXILED_THIS_WAY``'s
#: reason: ``handlers/linked_exile.put_exiled_cards_into_zone`` writes it and a
#: lowering gates on it.
PUT_INTO_HAND_THIS_WAY = "put_into_hand_this_way"

#: What the **earlier rounds** of a repeated process recorded, as
#: ``{record key: [values…]}`` (Tainted Pact). A round's own records are
#: cleared as the next begins — "that card" is this round's — and "another
#: card exiled **this way**" is the whole process's, so the loop files each
#: round's lists here before clearing them and the name relation reads both.
#: Written by ``handlers/repeats.repeat_process_until`` alone; absent
#: outside a loop, where "this way" is simply the one record.
PROCESS_ROUNDS_SO_FAR = "process_rounds_so_far"
#: What the exile step took, as objects. Written by every exile that a later
#: sentence asks a question *about* rather than a number of.
#:
#: **Its element type depends on the zone the exile emptied**, and that is a
#: fact about this key rather than an accident: a battlefield sweep records the
#: ``Permanent``s (``exile_all_matching``), because the sentences that read it
#: back ask whose each one was and CR 400.7 makes the exiled card a new object
#: with no controller at all; an exile out of a graveyard records the
#: ``CardDefinition``s, because there never was a permanent. A reader that
#: cares which it was holding has to say so — ``_claimable_exile_pile`` is the
#: one that does, and it names both shapes rather than guessing from a type
#: test, which is how Equipoise came to phase out nothing.
EXILED_THIS_WAY_OBJECTS = "exiled_this_way_objects"

#: "Starting with you, each player chooses **one of the exiled cards** and puts
#: it onto the battlefield tapped under their control. Repeat this process
#: until all cards exiled this way have been chosen." (Thieves' Auction.)
#:
#: The pile as it *stands*: what the exile above took, minus everything a seat
#: has already claimed. Its own record rather than a reading of
#: ``EXILED_THIS_WAY_OBJECTS``, because that one is the finished history of one
#: step and this one shrinks all the way through the next — a loop that read
#: the history would hand the same card to every seat.
#:
#: **A sequence of ``(owner_seat, card)`` pairs**, and both halves of that are
#: settled here because a scratchpad channel whose arity or element type is
#: left to its readers is how Equipoise chose the right permanents and phased
#: out none. The seat is carried rather than re-derived: the card is sitting in
#: its owner's exile, several players' decks share one ``CardDefinition``
#: object (``web/deck_builder`` repeats one per copy), and an identity scan
#: across the exile zones would answer with whichever seat was asked first.
CLAIMABLE_EXILED_CARDS = "claimable_exiled_cards"

#: Who **owned** each permanent an exile sweep took — ``{permanent_id: seat}``,
#: written while they are still on a battlefield and the question still has an
#: answer (CR 400.7 makes the exiled card a new object with no controller).
#: "…each player chooses one of the exiled cards and puts it onto the
#: battlefield **under their control**" (Thieves' Auction) hands a card to
#: somebody who does not own it, and CR 108.3 says the owner does not move.
#:
#: Its own constant and deliberately **not** a row in ``PER_OBJECT_SEAT_RECORDS``
#: beside ``swept_controller_seats``, which is the natural-looking home and the
#: wrong one: that table is keyed by the *printed possessive* a noun phrase
#: carries, and ``lowering/library`` looks a ``PlayerRef.kind`` up in it. "Owner"
#: is one of those kinds — "a creature card from **their** graveyard" (Exhume)
#: reaches it — so a row under that key does not add a record, it reroutes every
#: sentence that names an owner's zone into the per-object-record branch.
SWEPT_OWNER_SEATS = "swept_owner_seats"

#: The same step's record **per seat** — ``{seat: [card, …]}`` — for a sentence
#: whose exile and whose read-back are both distributed over the table: "Each
#: player exiles all creature cards from their graveyard, then … then puts all
#: cards **they** exiled this way onto the battlefield." (Living Death.)
#:
#: The per-seat twin of ``EXILED_THIS_WAY_OBJECTS``, and the same relation
#: ``DISCARDED_BY_SEAT`` has to ``discarded_count`` for that key's stated
#: reason: one flat list answers the wrong question the moment more than one
#: seat exiles, because the sentence behind it says "they" and a flat list
#: would hand every player the table's graveyards. Which is not a subtle
#: mis-play on this card — it is the difference between a mass reanimation and
#: one player taking everybody's creatures.
#:
#: Beside the flat keys rather than replacing them: the single-seat sentences
#: ("for each creature exiled this way", Martyr's Cry) ask about the whole set
#: and are right to.
#:
#: The cards are ``CardDefinition`` objects and are *not* identities — two
#: copies of one card in a graveyard are the same object — so a reader must
#: consume the list positionally rather than matching by value, exactly as the
#: graveyard sweeps that write it drain by slot.
EXILED_BY_SEAT = "exiled_by_seat"

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
#: What "**put into your graveyard this way**" names after a mill (Song of
#: Blood, Foreshadow, Helm of Obedience). The *cards* the mill put there — not
#: how many, because the sentences that read it ask which of them were creature
#: cards or carried a chosen name, and a count cannot answer either.
#:
#: Declared here for ``EXILED_THIS_WAY``'s reason: the count spec
#: ``lowering/characteristics`` writes and the producer gate
#: ``ability_lines._records_the_delay_reads`` asks sit at opposite ends of the
#: pipeline, and a second spelling between them is how a producer gate goes
#: vacuous while the amount reads an empty record.
#:
#: **Swept at VIS wave 4.** Five modules still spelled the string out — the
#: mill handlers in ``handlers/zones.py`` (``handlers/cards.py`` since the
#: 2,000-line split), the two condition readers in
#: ``handlers/control_flow.py`` and ``lowering/conditions.py``, the reanimation
#: in ``lowering/cards.py``, and ``lowering/_records._PRODUCES`` — twelve
#: occurrences, deferred once because three of those modules were open on other
#: branches. They all read this name now.
#:
#: One string that looks like a thirteenth is deliberately **not** this
#: constant: ``lowering/conditions.py`` emits ``{"kind": "milled_this_way"}``
#: and ``handlers/_record_conditions.py`` compares against it. That is a
#: *trigger-condition kind* which happens to be spelled the same way, not the
#: scratchpad key — one fact wearing another's spelling is what this entry is
#: against, so folding it would have made the confusion permanent rather than
#: removing it.
MILLED_THIS_WAY = "milled_this_way"

TAPPED_THIS_WAY = "tapped_this_way"

#: "Discard a card at random. **If you discard a creature card this way,**
#: return **it** from your graveyard to the battlefield …" (Aether Rift.) The
#: cards a discard *nobody chose* took, in the order they went — the discard's
#: twin of ``MILLED_THIS_WAY``, and a record for the same reason: by the next
#: sentence the card is one of many in a graveyard, and nothing about the pile
#: says which of them this effect put there.
#:
#: Beside ``discarded_count`` rather than replacing it: that key answers "did a
#: discard happen, and how many", which is all "if you do" asks; this answers
#: *what* went.
DISCARDED_THIS_WAY = "discarded_this_way"

#:
#: CR 701.9c: a card a replacement put into a *hidden* zone unrevealed (Library
#: of Leng, onto its owner's library) has undefined characteristics, so it is
#: counted and not listed — "a creature card" is not something it was.
#:
#: The subset of ``DISCARDED_THIS_WAY`` that actually reached a graveyard —
#: what "return it **from your graveyard**" may name. Its own key because the
#: return looks the card up by identity, and two copies of a card are one
#: ``CardDefinition``: read off the wider record, a card a replacement sent
#: somewhere else would be answered by an *older* copy already in the pile.
DISCARDED_INTO_GRAVEYARD = "discarded_into_graveyard"
TAPPED_THIS_WAY_OBJECTS = "tapped_this_way_objects"

#: The symbol a land-mana swap produces when the sentence prints no symbol at
#: all: "…it produces one mana of **a color of your choice** instead of any
#: other type and amount." (Harvest Mage.) Not a symbol a pool can hold — the
#: colour is named by the tapper *each time a land is tapped* (CR 106.12b's
#: replacement applies to that one production event), so the record carries
#: this and the tap seam resolves it against the colour the tapper asked for.
#:
#: Here rather than beside either end for ``X_FROM_COUNT``'s reason: the
#: grammar writes it into a payload and ``engine/land_mana_swaps.py`` reads it
#: back, and this module is the one both may import.
MANA_COLOR_OF_CHOICE = "color_of_choice"

#: "You and that opponent each gain control of all creatures the other controls
#: until end of turn. **Those creatures** gain haste until end of turn."
#: (Reins of Power.) Every permanent the mutual control change moved, both
#: directions in one record.
#:
#: Here rather than in ``grammar/lowering/_record_keys.py`` for that module's
#: own stated reason: the handler writes it and the lowering gates on it, so the
#: string belongs to the module neither of them imports from. A second spelling
#: is a gate that always refuses reading a record nothing ever wrote.
CONTROL_EXCHANGED_PERMANENTS = "control_exchanged_permanents"

#: What "**the mana lost this way**" (Drain Power) and "the amount of mana that
#: player **lost this way**" (Pygmy Hippo) name: the pool one step of this
#: effect emptied. CR 106.4 is where "lose this mana" is defined; CR 500.5 is
#: the *turn-based* emptying these two cards perform out of turn.
#:
#: ``{restriction key or "": {symbol: count}}``. Nested rather than flat
#: because **CR 106.13 is written about this exact pair of cards** and says the
#: restrictions survive: "Which permanents, spells, and/or abilities produced
#: that mana are unchanged, as are any restrictions or additional effects
#: associated with any of that mana." A flat ``{symbol: count}`` would hand a
#: Mishra's Workshop's artifacts-only {C}{C}{C} back as mana that pays for
#: anything, which is a strictly larger effect than the card's.
#:
#: Recorded rather than re-read, for the reason every record in this file is:
#: by the time either sentence runs the pool is empty, and Pygmy Hippo's runs a
#: whole phase later.
MANA_LOST_THIS_WAY = "mana_lost_this_way"
#: How much of it there was, restricted and unrestricted together — written
#: beside the record so a reader that wants a number is not summing a nested
#: dict it also has to know the shape of. Pygmy Hippo is that reader: it adds
#: {C} for the *amount*, which is new mana and carries no restriction. The
#: delayed trigger that reads it freezes the whole scratchpad (CR 608.2h), so
#: both travel together.
MANA_LOST_COUNT = "mana_lost_count"

#: What "**+1/+1 counters you put on a creature this way**" names (Bounty of the
#: Hunt). One entry **per counter**, not per creature, because that is what the
#: sentence counts: a creature given two of them is named twice and the loop
#: behind this runs twice about it, creating one delayed ability per counter
#: (CR 603.7) — which is what makes the removal come out even with the placement.
#:
#: Here rather than beside either reader, for ``EXILED_THIS_WAY``'s stated
#: reason: the lowering gates the printed phrase on the marker and the handler
#: writes the permanents, and the two are on opposite ends of the pipeline.
#:
#: Its own key rather than ``permanents_given_counters`` beside it: that one is
#: the *set* a placement marked, read as a set by three of Dread Wight's
#: sentences, and folding a per-counter list into it would make a creature with
#: two counters two members of a set those sentences mean once.
COUNTERS_PLACED_THIS_WAY = "counters_placed_this_way"

#: "Target creature you cast this turn has base power and toughness 0/1 until
#: your next upkeep. At the beginning of your next upkeep, put a +1/+1 counter
#: on **that creature**." (Cycle of Life.) The permanent the rewrite chose.
#:
#: Here rather than beside either reader, for ``COUNTERS_PLACED_THIS_WAY``'s
#: stated reason: the lowering gates the pronoun on the marker and the handler
#: writes the permanent, and the two sit at opposite ends of the pipeline. The
#: reader is a *delayed* ability a whole turn later (CR 603.7c), so nothing on
#: the board at that moment could tell the chosen creature from any other 0/1.
BASE_PT_SET_PERMANENTS = "base_pt_set_permanents"

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

#: "Remove target attacking creature you control from combat **and untap it**."
#: (Reconnaissance.) The permanent the removal took out of combat, recorded
#: because the step behind it names it with a bare pronoun and nothing else in
#: the sentence holds the object: a removal is neither a tap nor an untap, so
#: none of the neighbouring records has it, and the board cannot tell the
#: creature the ability targeted from any other creature that has stopped
#: attacking.
#:
#: Here rather than beside either reader, for ``COUNTERS_PLACED_THIS_WAY``'s
#: stated reason: ``handlers/combat.py`` writes it and
#: ``grammar/lowering/tapping.py`` gates on it, and the two are opposite ends of
#: the pipeline — a handler importing the grammar package closes an import
#: cycle, which is how this key found its way here.
REMOVED_FROM_COMBAT_PERMANENTS = "removed_from_combat_permanents"

#: What "**the creature type of your choice**" names (Extinction). One word,
#: chosen by the controller of the resolving spell (CR 608.2d) and read back by
#: the sweep in the same sentence through a ``subtype_filter_from`` key.
#:
#: A *scratchpad* record and not the ``chosen_creature_type`` metadata key one
#: characteristic over: that one is a choice a permanent made as it entered
#: (CR 614.1c) and lives for as long as the permanent does, where this one is
#: made and spent inside a single resolution and has no permanent at all — the
#: card that prints it is a sorcery.
CHOSEN_CREATURE_TYPE_THIS_WAY = "chosen_creature_type_this_way"

#: What "**a type chosen this way**" names after "**Each player** chooses a
#: creature type." (Harsh Mercy, Patriarch's Bidding.) A *list* of words, one
#: per seat in APNAP order (CR 101.4: the active player chooses first, then
#: each other player in turn order, each knowing the earlier choices — 101.4b),
#: written by ``each_player_chooses_creature_type`` and read by the sweep behind
#: it as a union. Its own key rather than the singular above widened, because
#: "of that type" behind one chooser and "of a type chosen this way" behind
#: every seat are different questions, and a reader of the singular handed a
#: list would test one word of several.
#:
#: A seat whose default found no creature type to name records ``None``; the
#: readers skip it. An absent record — the step never ran — is not an empty
#: list: a sweep reading it must do nothing rather than read "no type was
#: chosen" as "every creature is of no chosen type".
CHOSEN_CREATURE_TYPES_THIS_WAY = "chosen_creature_types_this_way"

#: The ``cost_from`` word for "**that spell's** mana cost" (Ice Cave): the price
#: is the mana cost of the spell the trigger fired on, read off the stack as
#: the offer is made. Named here because the lowering writes it and the offer
#: handler reads it, and a cost keyed by a word only one of them knew would be
#: a cost of nothing — which every board can pay.
EVENT_SPELL_MANA_COST = "event_spell_mana_cost"

#: The ``payer`` word of an offer chain made to "**any other player**" under an
#: event that froze a seat (Ice Cave: every player but the one who cast the
#: spell). Beside the cost word above for the same reason.
OTHER_THAN_EVENT_SUBJECT_PLAYER = "other_than_event_subject_player"

#: The ``actor`` word of an offer made to the controller of the **spell this
#: object targeted** ("Counter target instant or sorcery spell unless *its
#: controller* has Molten Influence deal 4 damage to them"). A stack object
#: has a controller and no battlefield, so neither of the two seats an offer
#: otherwise reads - the control seam for a permanent, the resolution's own
#: target seat for a player - names it. Beside the two words above for their
#: reason: the lowering writes it, the offer handler reads it, and an actor
#: only one of them knew would be an offer made to nobody.
STACK_TARGET_CONTROLLER = "stack_target_controller"

#: What "**that color**" names (Persecute). One colour symbol, chosen by the
#: controller of the resolving spell (CR 608.2d) in the sentence in front, and
#: read back by the sentence that spends it through a ``color_filter_from`` key.
#:
#: The scratchpad twin of the ``chosen_color`` metadata key, one characteristic
#: over from :data:`CHOSEN_CREATURE_TYPE_THIS_WAY` and its exact analogue: that
#: key is a permanent's choice made as it entered (CR 614.1c) and lives as long
#: as the permanent, where this one is made and spent inside a single
#: resolution and has no permanent at all.
CHOSEN_COLOR_THIS_WAY = "chosen_color_this_way"

#: What "**the chosen number**" names (Scrying Glass). One number, chosen by
#: the controller of the resolving ability (CR 608.2d) in the sentence in
#: front, and read back by the sentence that spends it.
#:
#: The scratchpad twin of the ``chosen_number`` metadata key, and the fourth of
#: the pairs above. That key is a permanent's own standing answer -- the number
#: Shapeshifter's characteristic-defining P/T keeps reading for as long as the
#: permanent lives -- where this one is made and spent inside a single
#: resolution, and a resolution is the only window in which "the chosen number"
#: can mean the number *this* activation asked for. Both are written by one
#: step, because a permanent that prints both readings would otherwise hold two
#: numbers and each reader would take whichever its author remembered.
CHOSEN_NUMBER_THIS_WAY = "chosen_number_this_way"

#: How many coins a **run** of flips actually flipped: "Flip a coin that many
#: times or until you lose a flip, whichever comes first. If you win all the
#: flips, draw two cards **for each flip**." (Squee's Revenge.) Written by
#: ``flip_coins_until_loss`` beside the ``coin_flip`` record every flip writes,
#: and separate from it because they answer different questions: that one says
#: whether the run was clean, this one how long it was — and a run the first
#: loss cut short is shorter than the number that was chosen.
COIN_FLIPS_MADE = "coin_flips_made"

#: How many flips of that run were **won**: "Flip a coin until you lose a
#: flip. Put a +1/+1 counter on this creature **for each flip you won**."
#: (Crazed Firecat.) Beside ``COIN_FLIPS_MADE`` rather than derived from it by
#: each reader, because the two differ by the losing flip only when there was
#: one — a run a ceiling stopped (Squee's Revenge) lost nothing — and a reader
#: subtracting one would be right for one card and wrong for the other.
COIN_FLIPS_WON = "coin_flips_won"

#: ``{seat: number}`` for a number **every player names at once, in secret**:
#: "Each player hides at least one item, then all players reveal them
#: simultaneously. Each player loses life equal to **the number of items they
#: revealed**. The player who revealed **the fewest** items then loses half
#: their life, rounded up." (Goblin Game.)
#:
#: Per seat for ``MANA_PAID_BY_SEAT``'s reason — every player's answer is their
#: own — and separate from ``CHOSEN_NUMBER_THIS_WAY`` beside it for a second
#: one: that key is one seat's public number, logged as it is named, and this
#: map is filled in with nothing said until its last entry exists. A seat the
#: map does not mention has **not answered yet**, which is the opposite of what
#: an absent entry means in the paid and drawn maps (zero); the prompt writes
#: every seat it asked, so by the time any sentence reads the map there is no
#: absent entry to interpret.
#:
#: Here because four ends spell it: the handler arms the prompt with it, the
#: prompt's answer writes it, ``lowering/_records`` declares it and
#: ``grammar/amounts`` reads it back.
SECRET_NUMBERS_BY_SEAT = "secret_numbers_by_seat"

#: What "**the chosen type**" / "**that type**" names when the ability that
#: chose it is a *spell* (Turnabout). One card type, chosen by the controller of
#: the resolving spell (CR 608.2d) in the sentence in front, and read back by
#: the sentence that spends it.
#:
#: The scratchpad twin of the ``chosen_card_type`` metadata key, and the third
#: of the same pair after the creature type and the colour above: that key is a
#: choice a *permanent* recorded and lives as long as the permanent
#: (Teferi's Realm), where this one is made and spent inside a single
#: resolution and has no permanent at all. One relation, two places to keep it,
#: and which one it is depends on whether there is a source permanent — a fact
#: only the handler holds, which is why both readings meet there rather than in
#: two payload keys.
CHOSEN_CARD_TYPE_THIS_WAY = "chosen_card_type_this_way"

#: What "…**each player who sacrificed a Plains this way**" names (Desolation).
#: The cards a forced sacrifice took, split by the **seat** that gave each one
#: up — ``{seat: [card, …]}``.
#:
#: Beside ``sacrificed_cards``, the flat list the same two write sites have
#: filled since Gargantuan Gorilla, rather than replacing it: that list answers
#: "did *this* effect's payer give up a snow Forest", one seat's question asked
#: by the seat that owed it, and this answers "which seats gave up a Plains",
#: which no flat list can — a sentence reading the flat one would damage every
#: player the moment any one of them sacrificed the named card.
#:
#: Here rather than beside either writer for ``CHOSEN_THIS_WAY_OBJECTS``'
#: reason: ``mixins/stack/choices/sacrifice.py`` writes it at both of its
#: sacrifice sites, ``handlers/damage.py`` reads it, and
#: ``grammar/lowering/_records._PRODUCES`` declares it.
SACRIFICED_CARDS_BY_SEAT = "sacrificed_cards_by_seat"

#: "Each player discards a card. Then **each player who didn't discard a
#: creature card this way** loses 4 life." (Strongarm Tactics.) Which cards
#: each seat discarded in this resolution, ``{seat: [cards]}`` — the discard's
#: twin of ``SACRIFICED_CARDS_BY_SEAT``, for that key's reason: the flat
#: ``DISCARDED_THIS_WAY`` answers "what went", and only a list per seat answers
#: "which seats gave up a creature card". A card that went somewhere hidden
#: (Library of Leng's library top, CR 701.9c) is counted in
#: ``DISCARDED_BY_SEAT`` and listed nowhere, so it is no creature card.
#: Written where every chosen discard is answered
#: (``choices/hand._after_discard_answered``) and by the each-player discard's
#: inline default; read by ``handlers/_filters._seat_discarded_this_way``.
DISCARDED_CARDS_BY_SEAT = "discarded_cards_by_seat"

#: **How many** permanents a sacrifice step actually ate, beside the list of
#: what they were.
#:
#: "Sacrifice any number of creatures. Last-Ditch Effort deals **that much**
#: damage to any target." A *bare* back-reference resolves against the effect's
#: one produced **quantity** (``_record_keys._PRODUCED_QUANTITIES``), and a list
#: is not one — admitting ``sacrificed_cards`` there would let "that much" name
#: a pile, which is the same argument ``exiled_count`` already carries beside
#: ``exiled_cards`` one zone over.
#:
#: A second key rather than a length taken at the reader, for that pair's reason
#: exactly: the two questions have different answers the moment a card asks
#: *which* were sacrificed with a narrowing on it. Written at the one place both
#: sacrifice paths record a card
#: (``mixins/stack/choices/sacrifice._record_sacrificed_card``),
#: so an interactive seat's answer and a non-interactive seat's inline
#: resolution cannot record different numbers.
SACRIFICED_COUNT = "sacrificed_count"

#: How much life a life-loss step actually took, in total across every seat it
#: took it from.
#:
#: "At the beginning of your upkeep, each opponent loses 1 life. You gain life
#: equal to **the life lost this way**." (Subversion.) The printed 1 is what
#: each opponent loses; what the gain reads is the *sum*, which in a two-player
#: game is 1 and at a four-player table is 3 — so nothing about the printed
#: sentence can supply it and no board read can either, life totals having moved
#: by the time the second sentence runs.
#:
#: Written by ``handlers/life_and_game.target_loses_life`` at the one place it
#: subtracts, declared by ``grammar/lowering/_records._PRODUCES`` and named as a
#: quantity by ``_record_keys._PRODUCED_QUANTITIES``, which is the three-way
#: agreement every other record on this channel has.
LIFE_LOST_THIS_WAY = "life_lost_this_way"


#: The life a permanent's **own entry trigger** made its controller lose, noted
#: on the ``Permanent`` (CR 607.1: "…gain life equal to **the life you lost when
#: it entered**", Soulgorger Orgg — the reader refers only to what that ability
#: did). The lowering marks the loss ``noted_on_source``; ``target_gains_life``'s
#: ``amount_from_source`` reads it, off a departed permanent too. A returning
#: permanent is a new object with no note (CR 400.7).
LIFE_LOST_WHEN_ENTERED = "life_lost_when_entered"


#: How many cards a "puts the cards from their hand on top of their library"
#: step moved (Jester's Mask). The ``results`` key the handler writes and the
#: ``produced`` marker the "search that player's library for **that many**
#: cards" behind it is gated on — here for ``EXILED_THIS_WAY``'s reason, that
#: the two readers sit at opposite ends of the pipeline.
HAND_CARDS_TO_LIBRARY = "hand_cards_to_library"


#: How many counters a "loses all <kind> counters" step actually took off
#: (Leeches). The ``results`` key the handler writes and the ``produced`` marker
#: the sentence behind it — "deals **that much** damage to that player" — is
#: gated on. Here for ``HAND_CARDS_TO_LIBRARY``'s reason, that the two readers
#: sit at opposite ends of the pipeline: the handler writes it and the lowering
#: gates on it, so a literal in each is how they come to disagree.
#:
#: The number is what was **removed**, not what the card asked for. A player
#: with two poison counters loses two and takes two, and reading the board
#: afterwards would read the zero the removal just wrote.
COUNTERS_REMOVED = "counters_removed"


#: "**Choose X target attacking creatures.** For each of those creatures, …"
#: (Winter's Chill.) The permanents a targeting sentence named, recorded so the
#: loop behind it has a set to walk: the spell chose them at announcement
#: (CR 601.2c) and nothing about the board says which attacking creatures those
#: were. Here for ``EXILED_THIS_WAY``'s reason — the lowering gates the printed
#: "those creatures" on the marker and the handler writes the objects, and the
#: two sit at opposite ends of the pipeline.
CHOSEN_TARGET_PERMANENTS = "chosen_target_permanents"

#: The ``targets`` description kind of "target **spell or permanent**" (Illusion,
#: Blind Seer): one chosen object in one of two zones. Beside ``"spell"`` (the
#: stack) and ``"object"`` (the battlefield), which are the description's words
#: for the two halves. Here because three ends of the pipeline spell it — the
#: lowering that writes it, ``target_descriptions._from_targets_payload`` that turns it
#: into the ``spell_or_permanent`` picker, and the handler that asks which half
#: the announcement named.
SPELL_OR_OBJECT_TARGET = "spell_or_object"


#: "**Choose two target creature cards in your graveyard.** … return **the
#: chosen cards** to the battlefield tapped." (Victimize.) The same shape one
#: zone over, and its own key rather than the permanents' for the reason those
#: two are separate: a card in a graveyard has no ``permanent_id`` and two
#: copies of one card there are the same ``CardDefinition``, so what the record
#: holds is graveyard *slots* — and a reader written for permanents would take
#: them for ids.
CHOSEN_TARGET_GRAVEYARD_SLOTS = "chosen_target_graveyard_slots"


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


#: The seat a step that **chose a permanent** records: the controller of the
#: object the previous sentence named, read before that object leaves
#: (CR 608.2h, last-known information). "Destroy target creature. **Its
#: controller** loses 2 life" (Liliana, Death Mage), "Exile target creature.
#: **Its controller** creates a 4/4 white Angel creature token" (Angelic
#: Ascension), "Destroy target creature. … **Its controller** reveals cards
#: from the top of their library" (Polymorph) are one referent with three
#: riders behind it, so they read one record.
#:
#: One key rather than two, and that is a correction rather than a convention:
#: the destroy handler wrote ``last_target_controller_index`` for the life
#: loss while the exile handler wrote ``exiled_permanent_controller`` for the
#: token, so "Destroy target creature. Its controller creates a token"
#: (Afterlife) refused for want of a producer that was sitting one file over
#: under another name — and "Exile target creature. Its controller loses 2
#: life" compiled and read a record nobody had written.
#:
#: A *spell's* controller is deliberately not this record. See
#: ``COUNTERED_SPELL_CONTROLLER`` below: a spell on the stack is not a
#: permanent, it is gone by a different rule (CR 701.6a) and it is recorded by
#: a different handler.
#:
#: Here rather than beside the lowering that gates on it, for
#: ``ATTACHED_PERMANENT_CONTROLLER``'s reason: three handlers write or read it
#: and ``grammar/lowering/_records._PRODUCES`` declares it, so a second
#: spelling makes the producer gate vacuous while a handler reads an empty
#: record — which is exactly what had happened.
LAST_TARGET_CONTROLLER = "last_target_controller"

#: The **owner** of the object a step that chose a permanent acted on.
#: "Destroy target creature. **Its owner** gains 4 life." (Path of Peace.)
#:
#: A second record beside ``LAST_TARGET_CONTROLLER`` rather than a reading of
#: it, because CR 108.3 and CR 109.5 are two different questions and the pool
#: prints both possessives: the controller is who has the permanent *now* and
#: the owner is whose deck it started in, and they differ for every permanent
#: anyone has ever stolen. Answering "its owner" out of the controller record
#: would heal the thief, which is the silent-and-in-somebody's-favour direction
#: this engine refuses everywhere else.
#:
#: Read before the permanent leaves, for its sibling's reason: by the time the
#: next step runs the object is a card in a graveyard (CR 608.2h, last-known
#: information). Ownership does not in fact change when a permanent does, but
#: the *record* is written at one moment for both keys so the two cannot come
#: to disagree about which object the sentence was about.
LAST_TARGET_OWNER = "last_target_owner"

#: The **name** of that same object, frozen at the same moment and for the same
#: reason the two seats above it are. "Exile target nonblack creature. Search
#: its controller's graveyard, hand, and library for all cards with the same
#: name as **that creature** and exile them." (Eradicate, and Scour, Splinter
#: and Sowing Salt over the other three card types.) By the time the search
#: runs, that creature is a card in exile — CR 400.7 makes it a new object and
#: CR 613.1 leaves it no computed characteristics at all — so the name the
#: sentence compares against exists nowhere but here.
#:
#: The **effective** name (CR 707.2): a Clone copying Grizzly Bears is a
#: creature named Grizzly Bears, and a search launched off its printed face
#: would strip a card nobody named.
#:
#: Its own key beside the two seats rather than a field on either, because a
#: sentence reads one or the other: Afterlife names the seat and never the
#: name, and these five name the name and reach the seat through the
#: controller key already beside it.
LAST_TARGET_NAME = "last_target_name"

#: The ``deal_damage`` recipient meaning "the controller of the last <noun
#: phrase> that dealt damage to you this turn" (Suffocation). A seat nobody
#: chose and no event froze: it is read at resolution out of
#: ``engine/damage_ledger.py``, and the phrase that says which entry rides
#: beside it on the payload's ``last_damager_filter`` key.
LAST_DAMAGER_CONTROLLER = "last_damager_controller"


#: The seat "counter target spell" records: the player who controlled the spell
#: it countered. "**Its controller** may draw up to two cards at the beginning
#: of the next turn's upkeep" (Arcane Denial) is the sentence that needs it, and
#: nothing else can answer: by the time the sentence runs, the spell is a card
#: in a graveyard (CR 701.6a) and a graveyard card has no controller at all
#: (CR 108.4) — a turn later, when the delayed ability finally fires, not even
#: the stack remembers there was one.
#:
#: Its own record rather than ``PER_OBJECT_SEAT_RECORDS["controller"]`` beside
#: it, because that one is a ``{permanent_id: seat}`` map read one entry per
#: iteration of a loop over swept *permanents*. A spell on the stack is not a
#: permanent and has no id in that space, so a seat written there would be
#: keyed by nothing and read by nobody.
#:
#: Here rather than beside the lowering that gates on it, for
#: ``ATTACHED_PERMANENT_CONTROLLER``'s reason: the ``stack`` handler writes it,
#: the ``zones`` handler reads it and ``grammar/lowering/_records._PRODUCES``
#: declares it, so the three sit at opposite ends of the pipeline.
COUNTERED_SPELL_CONTROLLER = "countered_spell_controller_seat"

#: The countered spell's **name**, the stack-side twin of ``LAST_TARGET_NAME``
#: above. "Counter target instant or sorcery spell. Search its controller's
#: graveyard, hand, and library for all cards with the same name as **that
#: spell** and exile them." (Quash.)
#:
#: A separate key from the permanent one rather than a second writer of it, for
#: ``COUNTERED_SPELL_CONTROLLER``'s own reason one line up: a spell on the stack
#: is not a permanent, the two are written by handlers in different modules, and
#: a lowering that could not tell them apart would admit "that spell" behind a
#: destroy and "that creature" behind a counterspell.
#:
#: Written when the counter step **chooses** its spell rather than when it
#: succeeds. CR 608.2's "as much as possible": a spell that can't be countered
#: (CR 701.6a has nothing to do to it) still leaves Quash a name to search for,
#: and a record written only on success would silently drop the whole second
#: sentence.
COUNTERED_SPELL_NAME = "countered_spell_name"


#: The seat that won an auction of life (``bid_life``): the high bidder when
#: the high bid stood. "**If you win the bidding**, counter that spell" (Mages'
#: Contest) is the sentence that reads it, and it has to be a record — the
#: bidding is a chain of prompts, so by the time anybody has won, the step that
#: opened it has long returned.
BIDDING_WINNER = "bidding_winner"


#: Which half of a ``keep_permanents`` choice **moves** when it is not the
#: default one. That prompt was built for "…chooses <slots>, then sacrifices
#: the rest" (Cataclysm, Global Ruin): the chosen stay, the complement is
#: sacrificed, and that fate is spelled by *absence* so every payload and
#: prompt written before a second one existed is byte-identical.
#:
#: "Each player chooses a land they control of each basic land type. **Return
#: those lands to their owners' hands.**" (Planar Overlay) is the same choice
#: over the same slots with the chosen half moving instead. One word, written
#: by the parse onto ``ast.KeepChosenSacrificeRest.fate``, carried by the
#: lowering under the payload key ``fate`` and performed by the prompt's own
#: resolver (``mixins/stack/choices/sacrifice._return_the_chosen``).
#:
#: ``KEEP_FATES`` is the closed vocabulary, read by the lowering's gate and by
#: the prompt's: a fate admitted with no performer would be a card that asks
#: every seat a question and then moves nothing.
RETURN_CHOSEN_TO_HAND = "return_chosen_to_hand"
KEEP_FATES = frozenset({RETURN_CHOSEN_TO_HAND})


#: The permanent "counter target activated ability" records: the source the
#: countered ability came from. "**That permanent's** activated abilities can't
#: be activated this turn" (Interdict) is the sentence that needs it, and
#: nothing else can answer — the spell targeted the *ability*, which is off the
#: stack by the time this clause runs (CR 113.7a gives it no card and no
#: controller of its own), and the words name the permanent behind it rather
#: than anything the caster chose.
#:
#: Its own record rather than ``LAST_TARGET_CONTROLLER`` beside it, for
#: ``COUNTERED_SPELL_CONTROLLER``'s reason one line up: that one is a *seat* and
#: this is an *object*, and the sentence that reads this one bans a permanent's
#: abilities rather than a player's.
COUNTERED_ABILITY_SOURCE = "countered_ability_source_permanent"


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
# `tests/engine/test_front_end_safety.py` swaps `front_ends._grammar_instruction`
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
