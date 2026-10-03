"""Text-keyed cost modification (CR 601.2f, 118.9).

"White spells cost {3} more to cast." / "Activated abilities of white
enchantments cost {3} more to activate." — Gloom's wording, and a template
Magic reprints constantly with different colours, types and amounts. The tax is
derived from oracle text here rather than registered per card name, so a card
printed with one of these templates needs no registration.

Each modifier is a filter plus an amount. The filter says which spells (or which
permanents' abilities) are taxed; the amount is added to the generic part of the
cost, once per taxing permanent on any battlefield — two Glooms tax {6}.

**Reductions** ("costs {1} less to cast") arrived with the cards that needed
them, which is what this file's scope note used to promise: Watcher of the
Spheres taxes downward from a permanent, and Stormwing Entity reduces *its own*
cost. They are not increases with a minus sign — CR 118.7a–d says a generic
reduction touches only the generic component, a coloured one falls back to
generic where the cost has no mana of that colour, and an excess coloured
reduction spills the difference onto generic. That arithmetic is
:func:`reduce_cost`, in one place, because getting it wrong makes a spell
castable that is not.

Two shapes, and they are genuinely different mechanisms rather than one with a
scope flag. A **permanent's** modifier is a board effect: it is found by
scanning battlefields and it applies to other objects. A **spell's own**
reduction is a property of the card being cast, read off its own text and gated
on a condition about the caster's turn — no permanent is involved, so no scan
would find it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

from .oracle_types import _COLOR_WORD_TO_SYMBOL

# Card types a cost modifier can name. "spell" is the unfiltered form; the "non"
# forms are the printed negation (Vryn Wingmare), not a separate mechanism.
_TYPES = "noncreature|artifact|creature|enchantment|instant|sorcery|land"
# A printed type *list* — "Instant and enchantment spells" (Mana Matrix). Any
# number of alternatives, because the count is a fact about one card and not
# about the template.
_TYPE_LIST = rf"(?:{_TYPES})(?:(?:,| and| or)+ (?:{_TYPES}))*"
_COLOURS = "|".join(_COLOR_WORD_TO_SYMBOL)
_MANA_SYMBOLS = frozenset({"W", "U", "B", "R", "G", "C"})


@dataclass(frozen=True)
class CostModifier:
    """A cost change this permanent applies to other objects.

    amount     -- generic mana added to (or, when *reduces*, taken off) each
                  affected cost
    applies_to -- "cast" for spells, "activate" for activated abilities,
                  "buyback" for CR 702.27a's optional additional cost. The
                  third is not a narrower "cast": it reduces one *printed
                  offer* and never the spell's own mana cost, so a reader of
                  either of the first two must not see it and vice versa
    reduces    -- whether this takes mana off rather than adding it
    colour     -- mana symbol the affected object must have, or None for any
    card_types -- card types the affected object must have *one of*, or empty
                  for any; a "non"-prefixed name excludes instead of requiring.
                  A list ("Instant and enchantment spells", Mana Matrix) is
                  read as the alternation it is printed as, so the number of
                  types is payload rather than part of the template
    keyword    -- keyword the affected object must have, or None for any
    controller -- "you" when the modifier says "you cast", "opponents" when it
                  says "your opponents cast", or None for anyone's
    life       -- the tax is paid in life rather than mana (CR 118.3b)
    targets_source -- the affected spell must target the permanent printing
                  this, which is a fact about the spell's *chosen targets* and
                  so can only be answered once they are chosen (CR 601.2c,
                  before costs are paid at 601.2h)
    """

    amount: int
    applies_to: str
    reduces: bool = False
    colour: str | None = None
    card_types: tuple[str, ...] = ()
    keyword: str | None = None
    controller: str | None = None
    life: bool = False
    targets_source: bool = False
    #: "Spells cost an additional \"Sacrifice a Swamp\" to cast for each black
    #: mana symbol in their mana costs." (Drought.) The payment is a
    #: **sacrifice** rather than mana or life — a third resource on the same
    #: table, for the reason the life tax is on it: what changes is what the
    #: additional cost is paid *with*, not that there is one (CR 601.2f).
    #: The noun phrase is in the same filter vocabulary
    #: ``AdditionalCost.sacrifice_filter`` uses, so what may pay is described
    #: once for a card's own cost and for a cost imposed on it.
    sacrifice_filter: dict | None = None
    #: The mana symbol counted in the affected object's cost, once per
    #: occurrence. Drought is the first tax in the pool whose *size* is read off
    #: the thing being taxed rather than printed, and it is payload for the
    #: reason every other parameter here is: a card printing the same sentence
    #: about a red symbol needs no code.
    per_symbol: str | None = None
    #: The **further** printed subjects one sentence names -- "green enchantment
    #: spells **and** white enchantment spells" (Irini Sengir). Each entry is
    #: the ``(colour, card_types)`` pair a second noun phrase read to, and an
    #: object matching *any* of them is taxed.
    #:
    #: Its own field rather than a list-valued ``colour``: what the sentence
    #: names is a disjunction of whole noun phrases, and the two conjuncts are
    #: free to differ on both axes at once. Folding it into either field would
    #: make "green enchantment spells and white artifact spells" describe a
    #: green artifact, which is a set the card never names.
    alternative_subjects: tuple[tuple[str | None, tuple[str, ...]], ...] = ()
    #: "Black spells you cast cost **{B}** more to cast." (Derelor.) The
    #: *coloured* pips the tax adds, beside ``amount``'s generic mana.
    #:
    #: Its own field rather than more of ``amount`` because a coloured pip is a
    #: different resource: generic mana may be paid with anything (CR 202.1),
    #: {B} may not, so a Forest pays a {1} tax and does not pay a {B} one.
    #: Folding it into the generic total would make Derelor's tax payable with
    #: any mana at all, which is the direction a cost must never drift in --
    #: the same reason ``life`` and ``sacrifice_filter`` are their own fields
    #: and their own readers.
    symbols: tuple[tuple[str, int], ...] = ()
    #: "...**This effect can't reduce the mana in that cost to less than one
    #: mana**." (Heartstone.) How much mana a cost this modifier *reduces* must
    #: still hold afterwards, over the whole cost rather than its generic part --
    #: "the mana in that cost" is every symbol of it.
    #:
    #: 0 on every increase and on a reduction printed without the rider, which
    #: is the honest floor: nothing below zero. Its own field rather than a
    #: clamp folded into ``amount``, because the clamp is a property of the
    #: *result* and cannot be expressed as a smaller subtraction -- a {2}
    #: reduction meets the floor on a {2} ability and not on a {3} one.
    floor: int = 0
    #: "**Cycling** abilities you activate cost {2} less to activate."
    #: (Fluctuator.) Which *ability* is affected, where every field above says
    #: which **object** is. The first modifier in the pool whose subject is not
    #: a class of cards at all: a Fluctuator discounts one ability of a card
    #: whose other abilities it leaves alone, so a reader that answered off the
    #: card would discount them all.
    #:
    #: The keyword rather than a bare flag, because that is what the sentence
    #: prints -- but only ``"cycling"`` is ever set, because
    #: ``cycling.is_cycling_ability`` is the one keyword this engine can
    #: recognise an ability *by* after CR 702.29a's rewrite has erased the
    #: word. A second keyword needs its own derivation, not a second string.
    ability_keyword: str | None = None
    #: "Each spell costs {3} more to cast **except during its controller's
    #: turn**." (Defense Grid.) The first modifier in this table whose subject
    #: is every spell there is and whose narrowing is not about the object at
    #: all: what decides is *when* the spell is cast, which no read of the card
    #: can answer.
    #:
    #: A condition the charging sites evaluate rather than a second table, for
    #: the reason every other field here is payload: the sentence is Sphere of
    #: Resistance's with a clause on the end, and it is charged by the same
    #: arithmetic through the same loop. Evaluated where ``controller`` and
    #: ``targets_source`` are -- see :func:`_timing_holds`, which is the one
    #: reader, because a condition read at one charging site and not another is
    #: a tax collected in mana and not in coloured pips.
    #:
    #: "Its controller" is the **spell's** controller (CR 109.5), which at
    #: CR 601.2f is the player casting it -- not this permanent's controller.
    #: Read the other way round, a Defense Grid would tax its own player's
    #: spells on everybody's turn and nobody else's.
    off_controllers_turn: bool = False
    #: "Creature spells **of the chosen type** cost {2} less to cast."
    #: (Urza's Incubator.) The subject is narrowed by a word this permanent's
    #: *controller* chose as it entered (CR 614.1c, CR 205.3m), so no reading of
    #: the sentence can answer it — only a reader holding the taxing permanent
    #: can, which is why this is a flag here and the word is looked up in
    #: :func:`_tax_floored` beside the two seat comparisons.
    #:
    #: The same shape ``subject_filters``' ``chosen_creature_type`` key has one
    #: layer over, and it fails the same way round: a permanent with no word
    #: recorded discounts nothing. A dropped narrowing would make every creature
    #: spell in the game cost {2} less, which is the direction a cost must never
    #: drift in.
    chosen_creature_type: bool = False


@dataclass(frozen=True)
class CostReduction:
    """How much comes off a cost, split the way CR 118.7 splits it."""

    generic: int = 0
    colored: tuple[tuple[str, int], ...] = ()

    def __bool__(self) -> bool:
        return bool(self.generic or self.colored)


# "<colour>? <type>? spells [with <keyword>] [you cast] cost {N} more/less to cast"
#
# The amount is a **run of mana symbols**, not one number: "cost {B} more to
# cast" (Derelor) is the same sentence with a coloured pip where Gloom prints a
# generic one, and reading only the digit form left the card refusing at
# "unrecognized effect verb" with nothing else wrong with it.
# ``_tax_symbols`` splits the run; a mixed "{1}{B}" would be read as both.
#
# **The subject is a list.** "Green enchantment spells **and** white enchantment
# spells cost {2} more to cast." (Irini Sengir) is one sentence naming two
# printed noun phrases that share one predicate, which is idiom 38's shape: each
# conjunct needs its own reading, and a conjunct nothing reads leaves the whole
# clause unclaimed. So the pattern captures the subjects as one run and
# ``_spell_tax_modifier`` splits them, rather than a second template being
# written for the pairing -- the pairings are quadratic in the phrases that
# exist.
#
# It stays **one** modifier, not one per conjunct. CR 601.2f applies each cost
# increase once, and this is one static ability describing a set of spells by
# two phrases; two modifiers from one permanent would tax a spell that is both
# green and white {4}.
#
# **The quantifier is payload too.** "**Each spell costs** {3} more to cast."
# (Defense Grid.) CR 109.2 draws no distinction between the set "each spell"
# names and the one "spells" names, which is the reading
# ``global_statics._TEMPLATES`` already makes of "each creature has …" against
# "all creatures have …" -- so the printed word and the singular noun and verb
# that come with it are an alternation here rather than a template of their own.
#
# Number **agreement** is checked in ``_spell_tax_modifier`` rather than spelled
# into the pattern, because the alternation is three-way (quantifier, noun,
# verb) and a regex that enumerated the legal combinations would be the
# quadratic template list the subject list above exists to avoid. What it buys
# is a refusal: "this spell costs {1} more to cast for each target beyond the
# first" (Fireball's surcharge, charged in ``mixins/stack/``) now *matches* this
# pattern part-way through, and only the agreement check keeps it from being
# read as a tax on every spell in the game.
# "…spells **of the chosen type**" (Urza's Incubator). A narrowing printed
# *after* the noun rather than before it, which is why it is a tail on the
# subject and not another slot beside the colour and the type list: the word it
# names is not in the sentence at all, it is on the permanent (CR 614.1c).
_CHOSEN_TYPE_TAIL = r"(?: of the chosen type)"
_SPELL_SUBJECT_TEXT = (
    rf"(?:(?:{_COLOURS}) )?(?:(?:{_TYPE_LIST}) )?spells?{_CHOSEN_TYPE_TAIL}?"
)
_SPELL_SUBJECT = re.compile(
    rf"^(?:(?P<colour>{_COLOURS}) )?(?:(?P<type>{_TYPE_LIST}) )?"
    rf"spell(?P<plural>s)?(?P<chosen>{_CHOSEN_TYPE_TAIL})?$"
)
# Split only where the "and" separates two *whole* subjects. `_TYPE_LIST`
# spells its own alternation with the same word -- "Instant and enchantment
# spells" (Mana Matrix) is one phrase -- so a bare split on " and " would tear
# that card's subject in half and leave "instant" reading as nothing.
_SUBJECT_SPLIT = re.compile(r"(?<=spells) and ")
# The caster clause is **which** seat, not merely whether one is printed.
# "…spells **your opponents cast**" (Aura of Silence) is the mirror of
# Watcher of the Spheres' "…you cast", and ``CostModifier.controller`` has
# carried both words since Terror of the Peaks — only this pattern could not
# say the second, so Aura of Silence's whole sentence went unread and the tax
# was charged to nobody. Read as one alternation for ``_TARGETING_MANA_TAX``'s
# reason directly above: who casts it and what it is called are independent
# axes, and pairing them as templates is quadratic in the phrases that exist.
_SPELL_TAX = re.compile(
    rf"(?P<each>each )?"
    rf"(?P<subjects>{_SPELL_SUBJECT_TEXT}(?: and {_SPELL_SUBJECT_TEXT})*)"
    r"(?: with (?P<keyword>[a-z]+))?"
    r"(?:(?P<controller> you| your opponents) cast)? cost(?P<verb_s>s)? "
    r"(?P<amount>(?:\{(?:\d+|[wubrgc])\})+) (?P<direction>more|less) to cast"
    # "…**except during its controller's turn**." (Defense Grid.) A timing
    # condition on the tax, optional because every other card printing this
    # sentence prints it without one -- and read here rather than left to a
    # trailing-sentence claim, because a clause this pattern did not consume
    # would leave the line unclaimed and the card unsupported while the tax it
    # narrows was charged on every turn.
    r"(?P<off_turn> except during its controller's turn)?"
)

#: Which seat a printed caster clause names. A table rather than a truth test on
#: the group, because the two words scope the tax in opposite directions and a
#: bare "was something printed?" would read Aura of Silence's opponents-only
#: sentence as taxing its own controller.
_TAX_CASTERS = {" you": "you", " your opponents": "opponents"}


def _tax_symbols(printed: str) -> tuple[int, tuple[tuple[str, int], ...]]:
    """A printed run of mana symbols as ``(generic, coloured pips)``.

    One reader for both halves of what a tax charges, because they come out of
    one printed clause -- and two because they are two resources: the generic
    part joins ``amount`` and is payable with anything, the coloured part is a
    pip that is not (CR 202.1).

    An unreadable symbol contributes nothing rather than being skipped
    silently: the caller refuses a clause this could not read in full, for the
    reason every cost reader in this repo refuses -- a symbol dropped here is a
    spell cast for less than it prints.
    """
    generic = 0
    pips: dict[str, int] = {}
    for token in re.findall(r"\{([^}]*)\}", printed):
        if token.isdigit():
            generic += int(token)
        elif token.upper() in _MANA_SYMBOLS:
            symbol = token.upper()
            pips[symbol] = pips.get(symbol, 0) + 1
        else:
            return -1, ()
    return generic, tuple(sorted(pips.items()))

# "Spells your opponents cast that target this creature cost an additional N
# life to cast." (Terror of the Peaks.) A tax in **life**, not mana, and scoped
# to spells that target the permanent printing it — which is why it is its own
# template rather than an amount on the one above: the payment is a different
# resource and the scope is a fact about the *spell's targets*, not about the
# spell.
_TARGETING_LIFE_TAX = re.compile(
    r"spells your opponents cast that target this creature cost an additional "
    r"(?P<amount>\d+) life to cast"
)

# "spells your opponents cast that target this creature cost {N} more to cast"
# (Pursued Whale). The *mana* twin of the life tax above, sharing its scope: the
# same "that target this creature" fact about the spell's chosen targets, paid
# in mana rather than in life. Its own pattern because the two are charged at
# different moments — mana at CR 601.2f's cost calculation, life at 601.2h's
# payment — and reading one as the other would put the wrong number in the
# wrong place.
#
# **Both halves of the scope are payload.** "Spells that target it cost {2} more
# to cast." (Kaervek's Torch, inside the "as long as this is on the stack"
# clause ``engine/stack_statics.py`` strips) is the same sentence with the
# caster restriction unprinted and the source named by a pronoun rather than by
# its type — and the whole difference between the two cards is which seats are
# taxed, which ``controller`` already carries. Written as one row rather than a
# second template, for the reason the subject list above is one row: the
# pairings of "who casts it" with "what it is called" are quadratic in the
# phrases that exist, and a card printing a third combination needs no code.
_TARGETING_MANA_TAX = re.compile(
    r"spells(?P<controller> your opponents cast)? that target "
    r"(?:this (?:creature|permanent|artifact|enchantment|land|spell)|it) cost "
    r"\{(?P<amount>\d+)\} more to cast"
)

# "Spells cost an additional "Sacrifice a Swamp" to cast for each black mana
# symbol in their mana costs." / the same sentence about activated abilities and
# their activation costs (Drought). One pattern for both halves, because they
# are one printed template with the object and the two matching nouns changed —
# and the pairing is checked rather than assumed, so "spells … to activate" is
# not read as either.
#
# The quoted clause is a *cost*, not a granted ability: CR 601.2b's additional
# cost is printed in quotes here the way CR 702's keyword abilities are, and the
# grammar refuses the shape ("granted ability in quotes") precisely so a table
# that implements it can claim it instead.
_SACRIFICE_SYMBOL_TAX = re.compile(
    r"(?P<what>spells|activated abilities) cost an additional "
    r'"sacrifice (?:a|an) (?P<noun>[a-z]+)" to (?P<verb>cast|activate) '
    rf"for each (?P<colour>{_COLOURS}) mana symbol in their "
    r"(?P<costs>mana|activation) costs"
)

#: Which nouns the halves must pair with. A sentence naming a spell and then an
#: activation cost describes nothing this engine can charge, and reading it as
#: either half would charge the wrong objects.
_SACRIFICE_TAX_HALVES = {
    ("spells", "cast", "mana"): "cast",
    ("activated abilities", "activate", "activation"): "activate",
}


# "activated abilities of <colour>? <type>s cost {N} more to activate"
_ABILITY_TAX = re.compile(
    rf"activated abilities of (?:(?P<colour>{_COLOURS}) )?(?P<type>{_TYPE_LIST})s? cost "
    r"\{(?P<amount>\d+)\} more to activate"
)

#: "Activated abilities of creatures cost {1} less to activate. **This
#: effect can't reduce the mana in that cost to less than one mana.**"
#: (Heartstone.)
#:
#: The same subject as ``_ABILITY_TAX`` in the other direction, and **both
#: sentences are required** for ``auras._ABILITY_COST_REDUCTION``'s reason one
#: module over: the floor is not decoration, it is what stops a {1} ability
#: becoming free, and a pattern claiming only the first sentence would leave
#: the second unclaimed while quietly implementing a cheaper card. The two are
#: printed as one line, which is why this reads across the full stop.
_ABILITY_REDUCTION = re.compile(
    rf"activated abilities of (?:(?P<colour>{_COLOURS}) )?(?P<type>{_TYPE_LIST})s? cost "
    r"\{(?P<amount>\d+)\} less to activate\. this effect can't reduce the mana "
    r"in that cost to less than (?P<floor>one|two|three) mana"
)

#: The floor's printed number words, the same three ``engine/auras.py`` reads
#: for the identical rider.
_ABILITY_FLOOR_WORDS = {"one": 1, "two": 2, "three": 3}

#: "**Buyback costs cost {2} less.**" (Memory Crystal.) The reduction this
#: module's own scope note said would "arrive with the card that needs it", and
#: the card has arrived.
#:
#: What it reduces is not a class of spells but **one keyword's optional
#: additional cost** (CR 702.27a, CR 601.2b), so it carries no colour and no
#: card type: every buyback cost in the game is affected, on any card, cast by
#: anybody. That is why ``applies_to`` gets a third value rather than this
#: riding "cast" with an empty filter — a "cast" modifier with no narrowing
#: would reduce every spell's **mana cost**, which is the one thing Memory
#: Crystal must not do.
#:
#: No floor sentence, unlike ``_ABILITY_REDUCTION`` above, because the card
#: prints none: a buyback of {2} really does become free, and CR 118.7a's clamp
#: at zero is the whole of the arithmetic. The absence is read off the card
#: rather than assumed — a printing that *did* carry a floor would not match
#: this pattern end to end and would be reported unsupported.
_BUYBACK_REDUCTION = re.compile(
    r"buyback costs cost \{(?P<amount>\d+)\} less"
)

#: "**Cycling abilities you activate cost {2} less to activate.**"
#: (Fluctuator.) The same predicate as ``_ABILITY_REDUCTION`` above with a
#: subject that names an **ability** rather than a class of cards, which is why
#: it is its own row: "activated abilities of <colour> <type>s" narrows by what
#: the source *is*, and this narrows by what the ability *is*.
#:
#: No floor sentence, unlike ``_ABILITY_REDUCTION``, and for
#: ``_BUYBACK_REDUCTION``'s reason: the card prints none, so a Cycling {2}
#: really does become free and CR 118.7a's clamp at zero is the whole of the
#: arithmetic. A printing that *did* carry a floor would not match this pattern
#: end to end and would be reported unsupported.
#:
#: The keyword is captured rather than spelled into the predicate so the
#: refusal below has something to name: only "cycling" has a derivation
#: (``engine/cycling.is_cycling_ability``), because CR 702.29a's rewrite is
#: what erased the word in the first place, and a keyword with no derivation
#: would discount every activated ability in the game.
_KEYWORD_ABILITY_REDUCTION = re.compile(
    r"(?P<keyword>[a-z]+) abilities you activate cost \{(?P<amount>\d+)\} "
    r"less to activate"
)

#: The ability keywords :data:`_KEYWORD_ABILITY_REDUCTION` may name. One entry,
#: and the set is what makes the refusal loud: a card naming any other keyword
#: matches the pattern, produces no modifier, is claimed by no line and is
#: reported unsupported -- rather than being read as a discount on abilities
#: nothing can tell apart.
_DERIVABLE_ABILITY_KEYWORDS = frozenset({"cycling"})


@lru_cache(maxsize=None)
def cost_modifiers_for(oracle_text: str) -> tuple[CostModifier, ...]:
    """Every cost modifier *oracle_text* grants. Cached on the text, which is
    immutable on a CardDefinition, so the per-permanent scan on each cast stays
    as cheap as the name-keyed lookup it replaced."""
    text = oracle_text.lower()
    if (
        "more to" not in text
        and "less to" not in text
        and "life to cast" not in text
        and "an additional" not in text
        # "Buyback costs cost {2} less." (Memory Crystal.) The only template
        # here whose sentence ends at "less" with no "to <verb>" behind it, so
        # it needs its own word in this early exit — without one the card falls
        # out before any pattern is tried and reports unsupported, which is a
        # gate failing silently in the direction of doing nothing.
        and "less" not in text
    ):
        return ()
    modifiers: list[CostModifier] = []
    for match in _SPELL_TAX.finditer(text):
        modifier = _spell_tax_modifier(match)
        if modifier is not None:
            modifiers.append(modifier)
    for match in _TARGETING_LIFE_TAX.finditer(text):
        modifiers.append(
            CostModifier(
                amount=int(match.group("amount")),
                applies_to="cast",
                life=True,
                targets_source=True,
                controller="opponents",
            )
        )
    for match in _TARGETING_MANA_TAX.finditer(text):
        modifiers.append(
            CostModifier(
                amount=int(match.group("amount")),
                applies_to="cast",
                targets_source=True,
                # Only when the sentence prints it. Kaervek's Torch taxes
                # *every* spell that targets it, its controller's included, and
                # a default of "opponents" would have let its own controller
                # counter it for free.
                controller="opponents" if match.group("controller") else None,
            )
        )
    for match in _ABILITY_TAX.finditer(text):
        modifiers.append(
            CostModifier(
                amount=int(match.group("amount")),
                applies_to="activate",
                colour=_COLOR_WORD_TO_SYMBOL.get(match.group("colour") or ""),
                card_types=_types_named(match.group("type")),
            )
        )
    for match in _ABILITY_REDUCTION.finditer(text):
        modifiers.append(
            CostModifier(
                amount=int(match.group("amount")),
                applies_to="activate",
                reduces=True,
                colour=_COLOR_WORD_TO_SYMBOL.get(match.group("colour") or ""),
                card_types=_types_named(match.group("type")),
                floor=_ABILITY_FLOOR_WORDS[match.group("floor")],
            )
        )
    for match in _KEYWORD_ABILITY_REDUCTION.finditer(text):
        modifier = _keyword_ability_reduction(match)
        if modifier is not None:
            modifiers.append(modifier)
    for match in _BUYBACK_REDUCTION.finditer(text):
        modifiers.append(
            CostModifier(
                amount=int(match.group("amount")),
                applies_to="buyback",
                reduces=True,
            )
        )
    for match in _SACRIFICE_SYMBOL_TAX.finditer(text):
        modifier = _sacrifice_symbol_modifier(match)
        if modifier is not None:
            modifiers.append(modifier)
    return tuple(modifiers)


def _keyword_ability_reduction(match: "re.Match[str]") -> CostModifier | None:
    """The reduction :data:`_KEYWORD_ABILITY_REDUCTION` matched, or None when
    the keyword it names is one no derivation can recognise.

    Split out for ``_spell_tax_modifier``'s reason below: a pattern that
    matches and then produces no modifier must also not *claim* the line, and
    both questions are asked by calling this.
    """
    keyword = match.group("keyword")
    if keyword not in _DERIVABLE_ABILITY_KEYWORDS:
        return None
    return CostModifier(
        amount=int(match.group("amount")),
        applies_to="activate",
        reduces=True,
        # "…**you** activate" (CR 109.5): the modifier's own controller, the
        # same word ``_spell_tax_modifier`` reads for "you cast".
        controller="you",
        ability_keyword=keyword,
    )


def _spell_tax_modifier(match: "re.Match[str]") -> CostModifier | None:
    """The spell tax *match* charges, or None when this reader cannot read it in
    full.

    One builder, asked by :func:`cost_modifiers_for` so the tax is *charged* and
    by :func:`cost_modifier_claims_line` so the line is *claimed* -- the same
    pairing ``_sacrifice_symbol_modifier`` below has, and for the same reason: a
    clause claimed by a pattern that then produces no modifier is a card
    reporting supported with its whole sentence dropped.

    Three readings are refused rather than approximated:

    * a symbol :func:`_tax_symbols` could not name -- charging the part it did
      read is a spell cast for less than it prints;
    * a coloured *reduction* ("cost {B} less"), whose arithmetic is CR 118.7's
      and lives in :func:`reduce_cost`. No card in the pool prints one from a
      permanent, and admitting it here would discount a cost by a rule nothing
      in this path applies;
    * a conjunct the subject reader cannot read, which takes the **whole**
      clause with it (idiom 38) -- half a sentence enforced is the failure that
      refusal exists to prevent;
    * a subject, quantifier and verb that do not **agree** in number. "Each
      spell costs" and "spells cost" are the two printed spellings of one set
      (CR 109.2); "this spell costs" is a sentence about one object and is a
      different rule, and reading it here would tax every spell in the game on
      the strength of a fragment.
    """
    generic, pips = _tax_symbols(match.group("amount"))
    if generic < 0:
        return None
    if pips and match.group("direction") == "less":
        return None
    subjects: list[tuple[str | None, tuple[str, ...]]] = []
    singular = False
    chosen_type = False
    for printed in _SUBJECT_SPLIT.split(match.group("subjects")):
        read = _SPELL_SUBJECT.match(printed.strip())
        if read is None:
            return None
        singular = singular or not read.group("plural")
        chosen_type = chosen_type or bool(read.group("chosen"))
        subjects.append(
            (
                _COLOR_WORD_TO_SYMBOL.get(read.group("colour") or ""),
                _types_named(read.group("type")),
            )
        )
    # The quantifier, the noun and the verb are one agreement, checked in one
    # place: "each" comes with a singular noun and "costs", and its absence
    # comes with a plural noun and "cost". A sentence mixing them is not this
    # template -- most often because the match began part-way through a longer
    # one, which is exactly how "this spell costs {1} more to cast for each
    # target beyond the first" reaches here.
    quantified = bool(match.group("each"))
    singular_verb = bool(match.group("verb_s"))
    if quantified:
        # "Each <one thing> costs …". One subject, because the quantifier is
        # printed once and distributes over what follows it; a list would need
        # a second one to be a list of subjects rather than of nouns.
        if not (singular and singular_verb and len(subjects) == 1):
            return None
    elif singular or singular_verb:
        return None
    colour, card_types = subjects[0]
    # "of the chosen type" names a catalog through the **head noun** it hangs
    # off, the same way ``_CHOSEN_SUBTYPE_KEYS`` reads it one layer over: a
    # creature spell's chosen type is CR 205.3m's, and a subject naming any
    # other noun would be a land type or a card type and land in a different
    # record. Nothing prints one, so the reading refuses rather than guesses --
    # and refusing takes the whole line with it, which is loud.
    #
    # One subject only, for the reason ``quantified`` admits one: the narrowing
    # is printed once, and a list would leave it ambiguous which conjunct it
    # narrows.
    if chosen_type and (card_types != ("creature",) or len(subjects) > 1):
        return None
    return CostModifier(
        amount=generic,
        applies_to="cast",
        reduces=match.group("direction") == "less",
        colour=colour,
        card_types=card_types,
        keyword=match.group("keyword"),
        controller=_TAX_CASTERS.get(match.group("controller") or ""),
        symbols=pips,
        alternative_subjects=tuple(subjects[1:]),
        off_controllers_turn=bool(match.group("off_turn")),
        chosen_creature_type=chosen_type,
    )


def _sacrifice_symbol_modifier(match: "re.Match[str]") -> CostModifier | None:
    """Drought's clause as a modifier, or None when the sentence's halves do not
    pair — see ``_SACRIFICE_TAX_HALVES``.

    ``amount`` is 0: the *number* of sacrifices is read off the taxed object's
    cost rather than printed, and a non-zero amount here would also add generic
    mana through ``_tax``, which the card does not say.
    """
    applies_to = _SACRIFICE_TAX_HALVES.get(
        (match.group("what"), match.group("verb"), match.group("costs"))
    )
    if applies_to is None:
        return None
    symbol = _COLOR_WORD_TO_SYMBOL.get(match.group("colour") or "")
    if symbol is None:
        return None
    return CostModifier(
        amount=0,
        applies_to=applies_to,
        sacrifice_filter={"subtype_filter": match.group("noun")},
        per_symbol=symbol,
    )


def cost_modifier_claims_line(line: str) -> bool:
    """Whether *line* is, in its entirety, one of the templates above.

    ``cost_modifiers_for`` scans for the templates anywhere in a card's text,
    which is what a tax needs — the clause can sit in any sentence. This asks
    the stricter question the grammar needs: does the template account for the
    *whole* line, leaving nothing over? "White spells cost {3} more to cast."
    does; "This spell costs {1} more to cast for each target beyond the first."
    matches no template at all (Fireball's surcharge is applied in
    mixins/stack/ instead).

    A spell's own reduction is claimed here too, from the same reading: what
    makes a line supported is that a table implements it end to end, and both
    tables live in this module.
    """
    text = line.strip().lower().rstrip(".")
    if ability_self_reduction(line) is not None:
        return True
    # Claimed only when the whole subject list reads, for
    # `_sacrifice_symbol_modifier`'s reason one branch down: a pattern that
    # matches and then produces no modifier is a claim over a line nothing
    # charges.
    spell = _SPELL_TAX.match(text)
    if (
        spell is not None
        and spell.end() == len(text)
        and _spell_tax_modifier(spell) is not None
    ):
        return True
    if any(
        (match := pattern.match(text)) is not None and match.end() == len(text)
        for pattern in (
            _ABILITY_TAX, _ABILITY_REDUCTION, _TARGETING_LIFE_TAX,
            _TARGETING_MANA_TAX, _BUYBACK_REDUCTION,
        )
    ):
        return True
    # Claimed only when the keyword has a derivation, for
    # `_sacrifice_symbol_modifier`'s reason: the pattern matches a sentence
    # about any keyword and only one of them produces a modifier, so a claim
    # taken off the match alone would report a card supported whose printed
    # discount nothing applies.
    keyword_ability = _KEYWORD_ABILITY_REDUCTION.match(text)
    if (
        keyword_ability is not None
        and keyword_ability.end() == len(text)
        and _keyword_ability_reduction(keyword_ability) is not None
    ):
        return True
    # Claimed only when the halves pair, for `_sacrifice_symbol_modifier`'s
    # reason: an unpaired sentence produces no modifier, and a claim over a line
    # nothing charges is the drift this seam exists to prevent.
    sacrifice = _SACRIFICE_SYMBOL_TAX.match(text)
    if (
        sacrifice is not None
        and sacrifice.end() == len(text)
        and _sacrifice_symbol_modifier(sacrifice) is not None
    ):
        return True
    if self_per_target_tax_claims_line(line):
        return True
    return self_reduction_claims_line(line)


def _types_named(clause: str | None) -> tuple[str, ...]:
    """The card types a printed type clause names, in order.

    "instant and enchantment" is two; "white" alone is none, because the colour
    is its own group. Splitting here rather than in the pattern keeps the count
    of types payload — a card printing three would need no change.
    """
    if not clause:
        return ()
    return tuple(re.findall(_TYPES, clause))


def _has_printed_type(card, wanted: str) -> bool:
    """Whether *card*'s type line satisfies one named type.

    "Noncreature" is the printed negation of the same word, so it is read as
    one rather than as a type of its own — the type line is asked the same
    question and the answer is inverted.
    """
    negated = wanted.startswith("non")
    if negated:
        wanted = wanted[3:]
    return (wanted in card.type_line.lower()) != negated


def _subject_matches(
    colour: str | None, card_types: tuple[str, ...], card, colors
) -> bool:
    """Whether *card* is one of the objects a single printed noun phrase names.

    *colors* is the taxed object's **effective** colours, worked out once by the
    caller — see :func:`taxed_object_colors`. Passed in rather than read off
    ``card.colors`` here, because the printed field answers a narrower question
    than "**white** spells cost {3} more" asks: CR 601.2f is about the spell,
    and a spell's colour is a layer-5 characteristic like any other.
    """
    if colour and colour not in colors:
        return False
    if card_types and not any(
        _has_printed_type(card, wanted) for wanted in card_types
    ):
        return False
    return True


def taxed_object_colors(game, obj, seat: int | None) -> tuple[str, ...]:
    """The colours the taxed object has *now* (CR 105, CR 613.1e).

    Every loop below asks this once and hands the answer to :func:`_matches`,
    which is the difference between a tax on a colour and a tax on a printed
    mana cost. Both kinds of object reach here — a card being cast or cycled
    from a hand, and a permanent whose activated ability is being taxed — and
    ``object_colors`` is the one reader that answers for either.

    *seat* is the object's own seat and not the taxing permanent's: CR 601.2f
    charges the player casting the spell, and Celestial Dawn's second sentence
    recolours "spells **you** control and nonland cards **you own**", so a
    Gloom on one battlefield taxes a Dark Ritual only when the Dawn is on the
    caster's. A caller with no seat gets the printed answer, which is what every
    caller here did before this function existed.
    """
    from .object_colors import object_colors

    return object_colors(game, obj, seat)


def _matches(modifier: CostModifier, card, colors) -> bool:
    """Whether *card* is taxed by *modifier*.

    The keyword narrows every subject -- it is printed after the list, so it is
    a restriction on all of them -- while the noun phrases are a
    **disjunction**: "green enchantment spells and white enchantment spells" is
    one set described twice, and a spell in either half is taxed once
    (CR 601.2f).
    """
    if modifier.keyword and modifier.keyword not in {
        word.lower() for word in (card.keywords or ())
    }:
        return False
    return any(
        _subject_matches(colour, card_types, card, colors)
        for colour, card_types in (
            (modifier.colour, modifier.card_types),
            *modifier.alternative_subjects,
        )
    )


def _chosen_type_holds(permanent, card) -> bool:
    """Whether *card* has the creature type *permanent* chose as it entered.

    The one narrowing in this file that is answered off the **taxing**
    permanent rather than off the taxed object, because that is where CR 614.1c
    records the answer — ``engine/mixins/permanent_state.py`` stamps it under
    the same key ``subject_filters`` reads for "creatures of the chosen type",
    so one recorded word answers both questions.

    False when nothing is recorded: a permanent whose choice has not been made
    narrows to nothing rather than to everything.
    """
    word = getattr(permanent, "metadata", {}).get("chosen_creature_type")
    if not word:
        return False
    return str(word).lower() in (getattr(card, "type_line", "") or "").lower()


def _timing_holds(game, modifier: CostModifier, caster_index: int | None) -> bool:
    """Whether *modifier*'s printed timing clause lets it charge right now.

    True for every modifier that prints none, which is all but Defense Grid's.
    "**Except during its controller's turn**" is a fact about the *spell* being
    cast -- CR 109.5's controller, who at CR 601.2f is the player casting it --
    so the comparison is that seat against the active player and never against
    the taxing permanent's controller.

    A caller that cannot say who is casting answers **False**, which for an
    increase is the direction a cost must never move on its own: unable to tell
    whose turn it is, this declines to charge rather than charging a tax the
    card may not impose. Unreachable today -- every "cast" caller carries the
    caster -- and asserted here rather than assumed, because the field is
    payload and the next card printing it may arrive on a path that does not.
    """
    if not modifier.off_controllers_turn:
        return True
    if caster_index is None:
        return False
    return getattr(game, "active_player_index", None) != caster_index


def _names_a_permanent(modifier: CostModifier) -> bool:
    """Whether *modifier*'s subject describes an object **on the battlefield**.

    CR 109.2: a description that includes a card type or subtype and does not
    name a zone or say "card"/"spell"/"source" means a *permanent* of that type.
    So "activated abilities of creatures cost {1} less" (Heartstone) and
    "activated abilities of white enchantments cost {3} more" (Gloom) say
    nothing about a creature card or an enchantment card sitting in a hand —
    and an ability activated from a hand (CR 113.6j: cycling, Waker of Waves)
    is an ability of a card, not of a permanent.

    Asked of the *modifier* rather than of the zone, because it is a fact about
    the printed sentence. Fluctuator's subject is the **ability**
    ("cycling abilities you activate"), which names no object at all and so
    reaches a hand exactly as it reaches the battlefield.
    """
    return bool(
        modifier.colour
        or modifier.card_types
        or modifier.keyword
        or modifier.alternative_subjects
    )


def _tax(
    game, card, applies_to: str, *, wanted: str,
    controller_index: int | None = None, targeted=(), ability=None,
    on_battlefield: bool = True, subject=None,
) -> tuple[int, list[str]]:
    """The total *wanted* ("more" or "less") change to *card*'s cost from every
    permanent on any battlefield, and those permanents' names for the log.

    One application per permanent — two Glooms tax {6} — and the scan covers
    every battlefield, because a cost modifier is not scoped to its own
    controller's side unless the card says so.
    """
    total, names, _floor = _tax_floored(
        game, card, applies_to, wanted=wanted,
        controller_index=controller_index, targeted=targeted, ability=ability,
        on_battlefield=on_battlefield, subject=subject,
    )
    return total, names


def _ability_subject_holds(modifier: CostModifier, card, ability) -> bool:
    """Whether *ability* is the kind of ability *modifier* names.

    True for every modifier that names none, which is all but Fluctuator's:
    the printed subject is a class of *cards* and the ability it belongs to is
    not part of the question.

    An ability-narrowed modifier with **no ability in hand** answers False
    rather than applying: the caller that has none is asking about a cast
    (CR 601.2f), where a discount on activated abilities has nothing to
    discount — and applying it there is the direction a cost must never drift
    in.
    """
    if modifier.ability_keyword is None:
        return True
    if ability is None:
        return False
    from .cycling import is_cycling_ability

    # One keyword, one derivation, and the table above admits no other -- so
    # this is a lookup with a single row rather than a dispatch waiting to be
    # written. A keyword reaching here without one would discount every
    # activated ability on the card, which is why the pattern refuses it first.
    return (
        modifier.ability_keyword == "cycling"
        and is_cycling_ability(card, ability)
    )


def _tax_floored(
    game, card, applies_to: str, *, wanted: str,
    controller_index: int | None = None, targeted=(), ability=None,
    on_battlefield: bool = True, subject=None,
) -> tuple[int, list[str], int]:
    """:func:`_tax` plus the highest floor any contributing modifier names.

    One loop rather than two, because a second walk would be a second answer to
    "which modifiers apply to this object?" -- and the two disagreeing is a
    reduction charged under somebody else's floor. The floor is the **maximum**
    for ``auras.attached_ability_cost_reduction``'s reason: two reductions must
    not cancel each other's protection against a free ability.

    *subject* is the **object** being taxed, where that is not the card itself:
    an activation tax is charged to a permanent, whose colour is a layer-5
    reading and not the printed field on ``effective_card`` (CR 613.1e -- layers
    1 and 3 are folded into that card, layer 5 is not, because a permanent's
    colour lives on the permanent). ``None`` means the object *is* the card,
    which is a spell being cast and every other caller.
    """
    colors = taxed_object_colors(
        game, card if subject is None else subject, controller_index
    )
    total = 0
    floor = 0
    names: list[str] = []
    for seat, permanent in game.permanents_with_controller():
        # effective_card: a colour word rewritten by Sleight of Mind (CR 613
        # layer 3) changes which spells this taxes, and the tax table should
        # not have to know that text can change.
        for modifier in cost_modifiers_for(permanent.effective_card.oracle_text):
            # A life tax is not mana and is charged by its own reader: counted
            # here it would be added to the generic cost, which is a different
            # resource and a different rule (CR 118.3b).
            if modifier.life:
                continue
            # A sacrifice tax is not mana either, and is charged by
            # ``sacrifice_taxes``. Skipped rather than left to add its zero,
            # because this function also collects the taxing permanents' *names*
            # for the log — a Drought listed beside a Gloom would report a mana
            # tax it does not impose.
            if modifier.sacrifice_filter is not None:
                continue
            # A tax printed entirely as coloured pips (Derelor's "{B}") adds no
            # generic mana, and is charged by ``spell_symbol_tax``. Skipped
            # rather than left to contribute its zero, for the reason a
            # sacrifice tax is: this function also collects the taxing
            # permanents' *names*, and a Derelor listed here would report a
            # generic tax it does not impose.
            if modifier.symbols and not modifier.amount:
                continue
            # CR 109.2: a subject naming a card type means a *permanent*, so a
            # modifier that names one says nothing about an ability activated
            # from a hand. Asked before `_matches`, which answers about the
            # card's type line either way and cannot tell the two zones apart —
            # left out, a Heartstone made Waker of Waves' hand ability cheaper
            # and a Gloom taxed a white enchantment nobody had cast.
            if not on_battlefield and _names_a_permanent(modifier):
                continue
            if modifier.applies_to != applies_to or not _matches(
                modifier, card, colors
            ):
                continue
            # "…**of the chosen type**" (Urza's Incubator). The word was chosen
            # as this permanent entered (CR 614.1c) and recorded on it, so it is
            # asked here rather than in ``_matches``: that function answers
            # about the taxed card alone and has no permanent to read.
            #
            # Containment in the printed type line for ``_has_printed_type``'s
            # reason — a card being cast is not a permanent, so CR 613.1 leaves
            # the line as the whole of what there is to ask. No word recorded
            # yet discounts nothing, which is the safe direction: a dropped
            # narrowing would take {2} off every creature spell in the game.
            if modifier.chosen_creature_type and not _chosen_type_holds(
                permanent, card
            ):
                continue
            # "**Cycling** abilities you activate…" (Fluctuator) narrows by
            # which ability is being activated rather than by what its source
            # is, so it is asked here beside `_matches` rather than inside it:
            # that function answers about a card, and one card's abilities are
            # not all the same ability.
            if not _ability_subject_holds(modifier, card, ability):
                continue
            if modifier.reduces != (wanted == "less"):
                continue
            # "…**you cast**" (Watcher of the Spheres) is the modifier's own
            # controller (CR 109.5), so it needs the seat casting the spell.
            if modifier.controller == "you" and (
                controller_index is None or seat != controller_index
            ):
                continue
            # "…**your opponents** cast" — the modifier's controller is not the
            # caster (CR 109.5 again, the other way round).
            if modifier.controller == "opponents" and seat == controller_index:
                continue
            # "…**that target this creature**": a fact about the spell's chosen
            # targets, so the tax applies only when one of them is this
            # permanent. Charged once per taxing permanent the spell points at,
            # because each is its own ability.
            if modifier.targets_source and not any(
                aimed is permanent for aimed in targeted
            ):
                continue
            # "…**except during its controller's turn**" (Defense Grid), asked
            # beside the two seat comparisons above because it is the third
            # narrowing that is not about the taxed object -- see
            # :func:`_timing_holds`.
            if not _timing_holds(game, modifier, controller_index):
                continue
            total += modifier.amount
            floor = max(floor, modifier.floor)
            names.append(permanent.card.name)
    return total, names, floor


def _stack_tax(
    game, caster_index: int, card, targeted_stack,
) -> tuple[int, list[str]]:
    """The same tax charged by an object **on the stack** (CR 113.6b).

    "As long as Kaervek's Torch is on the stack, spells that target it cost {2}
    more to cast." A static ability whose source is a spell, so no scan of any
    battlefield can find it — ``engine/stack_statics.py`` is what reads the
    clause, and this is the same per-source loop ``_tax`` runs one zone over.

    Its own loop rather than another branch inside ``_tax`` because the objects
    are different kinds: ``_tax`` yields ``(seat, Permanent)`` from the control
    seam and reads each one's *effective* card through the layers, and a stack
    object has neither. What the two share is the arithmetic and the scoping
    rules, which are the four checks below in the same order.
    """
    from .stack_statics import stack_static_cost_sources

    colors = taxed_object_colors(game, card, caster_index)
    total = 0
    names: list[str] = []
    for item, modifiers in stack_static_cost_sources(getattr(game, "stack", ())):
        seat = getattr(item, "caster_index", None)
        for modifier in modifiers:
            # "…of the chosen type": the word is recorded on a *permanent* as it
            # enters (CR 614.1c), and a stack object never entered anything. No
            # card in the pool prints both clauses on one line; refused rather
            # than ignored, because ignoring would widen the subject to every
            # creature spell — the direction ``_chosen_type_holds`` refuses in
            # one loop over.
            if modifier.chosen_creature_type:
                continue
            if not _matches(modifier, card, colors):
                continue
            if modifier.controller == "you" and seat != caster_index:
                continue
            if modifier.controller == "opponents" and seat == caster_index:
                continue
            # "…that target **it**": which *object* the spell chose, so the
            # comparison is by identity against the stack objects it named.
            # Two copies of one card on the stack are two objects (CR 109.1),
            # and a spell aimed at one of them is not taxed by the other.
            if modifier.targets_source and not any(
                aimed is item for aimed in targeted_stack
            ):
                continue
            if not _timing_holds(game, modifier, caster_index):
                continue
            total += modifier.amount
            names.append(item.card.name)
    return total, names


def spell_cost_tax(
    game, caster_index: int, card, targeted=(), targeted_stack=(),
) -> tuple[int, list[str]]:
    """Extra generic mana for casting *card*, plus the taxing objects' names.

    *targeted* is what the spell points at, for the modifiers whose scope is a
    fact about the chosen targets ("spells your opponents cast **that target
    this creature**", Pursued Whale). It defaults to empty, which is what makes
    every other caller's answer unchanged: a targets-scoped modifier simply does
    not apply when nothing is aimed at its source.

    *targeted_stack* is the same fact about the other zone — the objects **on
    the stack** this spell chose (Counterspell naming a Kaervek's Torch). One
    function rather than two callers, because a caster asking "what does this
    cost?" must get one answer: a tax only the cast path could see would be a
    spell the AI declines to cast, or tries to cast and cannot pay for.
    """
    total, names = _tax(
        game, card, "cast", wanted="more", controller_index=caster_index,
        targeted=targeted,
    )
    stack_total, stack_names = _stack_tax(
        game, caster_index, card, targeted_stack
    )
    return total + stack_total, names + stack_names


def spell_symbol_tax(
    game, caster_index: int, card, targeted=(),
) -> tuple[dict[str, int], list[str]]:
    """The **coloured** mana a tax adds to *card*'s cost, and who is charging it.

    "Black spells you cast cost {B} more to cast." (Derelor.) Its own reader
    beside :func:`spell_cost_tax` for the reason :func:`spell_life_tax` is one:
    what changes is the resource. Generic mana may be paid with anything
    (CR 202.1), so folding a {B} into the generic total would let a Forest pay
    it -- a tax charged more cheaply than the card prints, which is the one
    direction a cost may never move.

    One application per taxing permanent, over every battlefield, and scoped by
    the same ``controller`` / ``targets_source`` reading ``_tax`` makes -- so
    "**you** cast" charges only its own controller's spells and an opponent's
    black spell is untaxed.
    """
    colors = taxed_object_colors(game, card, caster_index)
    total: dict[str, int] = {}
    names: list[str] = []
    for seat, permanent in game.permanents_with_controller():
        for modifier in cost_modifiers_for(permanent.effective_card.oracle_text):
            if not modifier.symbols or modifier.reduces:
                continue
            if modifier.applies_to != "cast" or not _matches(
                modifier, card, colors
            ):
                continue
            if modifier.controller == "you" and seat != caster_index:
                continue
            if modifier.controller == "opponents" and seat == caster_index:
                continue
            if modifier.targets_source and not any(
                aimed is permanent for aimed in targeted
            ):
                continue
            if not _timing_holds(game, modifier, caster_index):
                continue
            for symbol, count in modifier.symbols:
                total[symbol] = total.get(symbol, 0) + count
            names.append(permanent.card.name)
    return total, names


def spell_life_tax(game, caster_index: int, targeted) -> tuple[int, list[str]]:
    """Life the caster must pay on top of *card*'s cost, and who is charging it.

    "Spells your opponents cast **that target this creature** cost an additional
    3 life to cast." (Terror of the Peaks.) The scope is a fact about the
    spell's *chosen targets*, which is why this takes the permanents the spell
    points at rather than the card: CR 601.2c chooses targets before 601.2h pays
    costs, so the answer exists — but only at the cast, and only to a caller that
    has it.

    Charged per taxing permanent the spell targets, because each one is its own
    ability. A spell targeting two Terrors pays six.
    """
    total = 0
    names: list[str] = []
    for seat, permanent in game.permanents_with_controller():
        for modifier in cost_modifiers_for(permanent.effective_card.oracle_text):
            if not modifier.life or modifier.applies_to != "cast":
                continue
            if modifier.controller == "opponents" and seat == caster_index:
                continue
            if modifier.targets_source and not any(
                aimed is permanent for aimed in targeted
            ):
                continue
            total += modifier.amount
            names.append(permanent.card.name)
    return total, names


def spell_cost_reduction(game, caster_index: int, card) -> tuple[CostReduction, list[str]]:
    """What comes off *card*'s cost from permanents on the battlefield.

    Generic only: a permanent's modifier is printed as ``{N}``, so the regex
    reads a number. A coloured reduction from a permanent would be a new
    spelling, and :func:`reduce_cost` already knows what to do with one.
    """
    generic, names = _tax(
        game, card, "cast", wanted="less", controller_index=caster_index
    )
    return CostReduction(generic), names


def _symbols_in(cost, symbol: str) -> int:
    """How many mana symbols in *cost* are *symbol* (CR 107.4).

    Two spellings of a cost reach this, because the engine really has two: a
    **symbol dict** is what every cost inside the engine is (an activation cost,
    a payment plan), and a card's *printed* mana cost is still the string
    Scryfall gave it. One reader for both, so what Drought counts on a spell and
    what it counts on an ability cannot come to be two questions.

    The string is read per printed symbol rather than by counting "{B}"
    literally, because a hybrid or Phyrexian symbol containing B **is** a black
    mana symbol (CR 107.4e/107.4f) and a literal count would miss it. Nothing in
    the pool prints one yet; the rule is what the card says.
    """
    if isinstance(cost, Mapping):
        return max(0, int(cost.get(symbol.upper(), 0) or 0))
    return sum(
        1
        for printed in re.findall(r"\{([^}]*)\}", str(cost).upper())
        if symbol.upper() in printed.split("/")
    )


@dataclass(frozen=True)
class SacrificeDemand:
    """One imposed "Sacrifice a <noun>" cost, sized for one object.

    ``described`` is the payload ``subject_matches`` tests; ``noun`` is the word
    the card printed, kept beside it because a filter's *head noun* is
    "permanent" for anything narrowed by a subtype — true, and useless in the
    refusal a player reads.
    """

    described: dict
    count: int
    noun: str
    source_name: str


def sacrifice_taxes(
    game, payer_index: int, cost, applies_to: str
) -> tuple[SacrificeDemand, ...]:
    """Every "cost an additional \"Sacrifice a …\"" demand on an object whose
    cost is *cost*.

    One entry per taxing permanent, because each is its own ability — two
    Droughts charge twice — and the scan covers every battlefield, for the
    reason ``_tax`` gives: a cost modifier is not scoped to its controller's
    side unless the card says so.

    Returned as demands rather than performed here, because the two payers ask
    at different moments in their own announcement (CR 601.2h against
    CR 602.2b) and both need the *gate* before anything is spent.
    """
    demands: list[SacrificeDemand] = []
    for _seat, permanent in game.permanents_with_controller():
        for modifier in cost_modifiers_for(permanent.effective_card.oracle_text):
            if modifier.sacrifice_filter is None or modifier.per_symbol is None:
                continue
            if modifier.applies_to != applies_to:
                continue
            if not _timing_holds(game, modifier, payer_index):
                continue
            count = _symbols_in(cost, modifier.per_symbol)
            if count:
                demands.append(
                    SacrificeDemand(
                        described=dict(modifier.sacrifice_filter),
                        count=count,
                        noun=str(
                            modifier.sacrifice_filter.get("subtype_filter")
                            or modifier.sacrifice_filter.get("type_filter")
                            or "permanent"
                        ),
                        source_name=permanent.effective_card.name,
                    )
                )
    return tuple(demands)


def modified_ability_source_card(source):
    """The card a cost modifier tests *source* against.

    A permanent is asked for its **effective** card, so a copied or animated
    one is taxed and discounted on what it currently is (CR 613 layers 1 and
    3). A card in a hand has no such reading and *is* the card: CR 113.6j puts
    a cycling ability in a hand, where there is no permanent for a layer to
    modify — and `getattr(source, "effective_card")` on a `CardDefinition`
    raises, which is how the two ability-cost readers below came to be callable
    only from the battlefield.

    Its **colour** does not come from here, and that is the point of the
    ``subject`` argument the two readers pass alongside this: ``effective_card``
    folds in layers 1 and 3 and stops, so a permanent Celestial Dawn has made
    white still reads its printed colours off this card. The object itself is
    what layer 5 was applied to.
    """
    return getattr(source, "effective_card", source)


def ability_cost_tax(
    game, controller_index: int, source, ability=None,
    *, on_battlefield: bool = True,
) -> tuple[int, list[str]]:
    """Extra generic mana for activating *source*'s ability, plus the taxing
    permanents' names. Matched against the source's *effective* card so a
    copied or animated permanent is taxed on what it currently is.

    *ability* is the one being activated, for a modifier that narrows by which
    ability rather than by what its source is. None is the honest answer for a
    caller that has no ability in hand, and such a modifier then does not
    apply.

    *on_battlefield* is False for an ability activated from a hand (CR 113.6j),
    where CR 109.2 puts every object-scoped modifier out of reach — see
    :func:`_names_a_permanent`.
    """
    return _tax(
        game, modified_ability_source_card(source), "activate", wanted="more",
        controller_index=controller_index, ability=ability,
        on_battlefield=on_battlefield, subject=source,
    )


def ability_cost_reduction(
    game, controller_index: int, source, ability=None,
    *, on_battlefield: bool = True,
) -> tuple[int, list[str], int]:
    """Generic mana **off** *source*'s activation cost, the reducing permanents'
    names, and the floor those permanents impose.

    :func:`ability_cost_tax`'s twin, and deliberately its mirror down to the
    ``effective_card``: a copied or animated permanent is discounted on what it
    currently is, exactly as it is taxed on what it currently is.

    The floor rides back with the amount rather than being asked for separately,
    because the two come from the same modifiers -- a caller reading them apart
    could apply one permanent's reduction under another's floor.
    """
    return _tax_floored(
        game, modified_ability_source_card(source), "activate", wanted="less",
        controller_index=controller_index, ability=ability,
        on_battlefield=on_battlefield, subject=source,
    )


def cost_modifier_reduction_sentences(oracle_text: str) -> tuple[str, ...]:
    """The sentences :data:`_ABILITY_REDUCTION` reads, or empty.

    The reduction is **two sentences on one printed line** -- the amount and the
    floor -- and neither means anything alone, so the reader matches them
    joined. This names the pair for a caller that walks a card sentence by
    sentence (``scripts/parse_coverage.py``), which would otherwise report the
    floor as text nothing read. The same arrangement
    ``auras.aura_cost_reduction_sentences`` makes for the identical rider on an
    Aura.
    """
    found: list[str] = []
    for line in (oracle_text or "").split("\n"):
        text = " ".join(line.strip().lower().split()).rstrip(".")
        match = _ABILITY_REDUCTION.match(text)
        if match is None or match.end() != len(text):
            continue
        found.extend(
            sentence.strip() for sentence in text.split(". ") if sentence.strip()
        )
    return tuple(found)


# ---------------------------------------------------------------------------
# A spell's own reduction (CR 601.2f), and the arithmetic every reduction uses
# ---------------------------------------------------------------------------


# "[If <condition>, ][During your turn, ]this spell costs {…} less to cast[ if
# <condition>]."
#
# The condition is printed in **either** position: trailing on Stormwing Entity,
# fronted on Prophecy's five Avatars ("If you have 3 or less life, this spell
# costs {6} less to cast"). One sentence in two English word orders, so one
# pattern with two delimiting groups rather than two tables — and a line
# printing both is refused below, because two conditions is a conjunction
# nothing here was asked to read.
_SELF_REDUCTION = re.compile(
    r"(?:if (?P<fronted>.+?), )?"
    r"(?:(?P<during>during your turn), )?this spell costs (?P<pips>(?:\{[^}]+\})+) "
    r"less to cast(?: if (?P<condition>[^.]+))?"
    r"(?:, where x is (?P<counted>[^.]+))?\.?$"
)

# The "where X is …" clauses a self-reduction may be sized by, mapped to the
# question asked of the caster at CR 601.2f. A wording outside this table
# refuses the line — an unrecognized count read as zero would merely fail to
# discount, but read as anything else would under-charge, and refusing keeps the
# card visibly unsupported instead of quietly mispriced.
_SELF_REDUCTION_COUNTS: dict[str, str] = {
    "the total power of creatures you control": "total_power_you_control",
    "the total amount of noncombat damage dealt to your opponents this turn":
        "noncombat_damage_to_opponents_this_turn",
}


# The conditions a self-reduction may be gated on, mapped to the question the
# caster's own state answers. A wording outside this table refuses the line —
# reading an unrecognized condition as "true" would make the spell cheaper than
# it is, which is the one direction a cost error must never go.
#
# **Closed at these two.** Every other condition is read by the grammar's own
# condition reader (``grammar.condition_payload_for``) and answered by
# ``handlers/control_flow.evaluate_condition`` — the pair every printed
# intervening-if already goes through — and is gated below on the kinds a
# cast-time question can answer. These two stay because the grammar does not
# read the "you've" contraction or a spell-type narrowing on the cast record;
# retiring them means teaching it both, not adding a row here.
_SELF_CONDITIONS: dict[str, str] = {
    "you've cast an instant or sorcery spell this turn": "cast_instant_or_sorcery",
    "you've gained 3 or more life this turn": "gained_three_life",
}

#: The lowered condition kinds a spell's own reduction may stand behind (CR
#: 601.2f), and so the ones :func:`_cast_time_gate` admits. Every one is a
#: question about the board, the zones or the life totals **as they are now**:
#: a reduction is calculated while the spell is being cast, when nothing has
#: fired, nothing has resolved and nothing was recorded "this way", so a kind
#: reading a trigger's frozen context or a resolution's scratchpad would be
#: answered off an empty record — False forever, or worse, true by default.
_CAST_TIME_CONDITION_KINDS = frozenset({
    "controls", "on_battlefield", "zone_card_count", "player_life",
    "cards_in_zones",
})

#: The seat words those kinds may carry. "You" is the caster; "opponent" is the
#: existential the evaluator answers over every living opponent. Any other word
#: names a target, an event's player or a superlative, none of which a spell in
#: the middle of being cast has.
_CAST_TIME_SEATS = frozenset({"you", "opponent"})


def _cast_time_gate(payload: dict) -> bool:
    """Whether a lowered condition is one a cast-time reduction can answer.

    Refusing is the safe direction here and only here: a reduction whose gate
    could not be asked would be read as unconditional, which is a spell cheaper
    than it prints.
    """
    kind = payload.get("kind")
    if kind in ("all_of", "any_of"):
        parts = payload.get("conditions") or ()
        return bool(parts) and all(_cast_time_gate(part) for part in parts)
    if kind not in _CAST_TIME_CONDITION_KINDS:
        return False
    if any(
        key in payload and payload[key] not in _CAST_TIME_SEATS
        for key in ("who", "player")
    ):
        return False
    # "another"/"other": the asking object is a card in a hand, not a permanent,
    # and an exclusion of it is a sentence no spell prints about itself.
    described = payload.get("filter") or {}
    return not (described.get("exclude_self") or described.get("exclude_event_subject"))


def _gate_holds(game, caster_index: int, card, gate: dict) -> bool:
    """Ask *gate* of the caster's game now, through the one evaluator."""
    from .game_types import OracleExecutionContext
    from .handlers.control_flow import evaluate_condition

    caster = game.players[caster_index]
    # ``target`` is the caster only because the context needs one: no kind
    # :func:`_cast_time_gate` admits reads it.
    return evaluate_condition(
        game, OracleExecutionContext(caster=caster, target=caster, card=card), gate,
    )


# "This ability costs {N} less to activate for each <noun phrase>."
# (Sanctum of Tranquil Light.) A *self* reduction on an activated ability, sized
# by a board count rather than printed flat — which is the whole reason it is a
# separate template from the flat taxes above: the number is not in the text.
_ABILITY_SELF_REDUCTION = re.compile(
    r"this ability costs \{(?P<generic>\d+)\} less to activate for each "
    r"(?P<subject>.+?)\.?$"
)


@dataclass(frozen=True)
class AbilitySelfReduction:
    """"This ability costs {1} less to activate for each Shrine you control."

    *per_each* is the ``permanent_matches_filter`` payload of the printed noun
    phrase, so the count asks the same question of a permanent that every other
    reader of those words asks. A phrase the matcher cannot test is not recorded
    at all — the reduction refuses rather than counting a set it cannot describe,
    because reading a narrowing as satisfied makes the ability cheaper than it
    is, and cheaper is the one direction a cost error must never go.
    """

    generic: int
    per_each: dict


@lru_cache(maxsize=None)
def ability_self_reduction(line: str) -> "AbilitySelfReduction | None":
    """The per-object activation reduction *line* states, if it is one."""
    from .grammar import subject_filter_payload
    from .subject_filters import untestable_filter_keys

    match = _ABILITY_SELF_REDUCTION.match(line.strip().lower())
    if match is None:
        return None
    described = subject_filter_payload(match.group("subject"), plural=True)
    if described is None:
        return None
    if untestable_filter_keys(described):
        # A key the matcher cannot answer would be dropped, and the count would
        # then be taken over a wider set than the card names — a bigger discount
        # than the card gives.
        return None
    return AbilitySelfReduction(int(match.group("generic")), described)


def ability_self_reduction_amount(game, controller_index: int, source) -> int:
    """How much generic mana comes off *source*'s activation cost right now.

    Counted through the control seam and the shared matcher, and read off the
    permanent's *effective* card so an animated or copied permanent is discounted
    on what it currently is — the same rule ``ability_cost_tax`` follows one
    function above.
    """
    from .handlers._common import permanent_matches_filter

    total = 0
    # Split into *sentences*, not lines: the reduction is printed inside an
    # activated ability's own line ("{5}{W}: Tap target creature. This ability
    # costs …"), so a line-wise scan only ever sees text beginning with the cost
    # symbols and matches nothing. The claim predicate stays anchored and
    # whole-sentence — the two questions differ exactly as ``cost_modifiers_for``
    # and ``cost_modifier_claims_line`` already differ above.
    text = (source.effective_card.oracle_text or "").replace("\n", ". ")
    for sentence in text.split("."):
        reduction = ability_self_reduction(sentence)
        if reduction is None:
            continue
        matched = sum(
            1
            for perm in game.controlled_by(controller_index)
            if permanent_matches_filter(perm, reduction.per_each)
        )
        total += reduction.generic * matched
    return total


@dataclass(frozen=True)
class SelfCostReduction:
    """"This spell costs {2}{U} less to cast if …" (Stormwing Entity)."""

    reduction: CostReduction
    condition: str | None = None
    during_your_turn: bool = False
    #: "This spell costs **{X}** less to cast, where X is …" (Volcanic Salvo,
    #: Chandra's Incinerator). The reduction is generic and its size is not in
    #: the text — which is why {X} was refused outright above: a symbol this
    #: table could not compute would have under-charged the spell, and a cost
    #: error in that direction is the one that must never happen. Named here as
    #: the *question* to ask rather than as a number, and answered against the
    #: caster's board or history at CR 601.2f, when the cost is calculated.
    counted: str | None = None
    #: "**If an opponent controls seven or more lands**, this spell costs {6}
    #: less to cast." (Avatar of Fury.) Any condition outside
    #: ``_SELF_CONDITIONS``, as the grammar's own condition reader lowers it —
    #: the payload ``handlers/control_flow.evaluate_condition`` answers for
    #: every intervening-if in the pool, asked here of the caster at CR 601.2f.
    #: None when the reduction is unconditional or gated by a row of the table.
    gate: dict | None = None


@lru_cache(maxsize=None)
def self_cost_reduction(oracle_text: str) -> SelfCostReduction | None:
    """The reduction *oracle_text*'s own first line applies to itself, if any."""
    for line in oracle_text.lower().split("\n"):
        match = _SELF_REDUCTION.match(line.strip())
        if match is None:
            continue
        condition = match.group("condition")
        fronted = match.group("fronted")
        if condition is not None and fronted is not None:
            # Two printed conditions, one in each position: a conjunction
            # nothing here reads, and either half alone is a cheaper spell.
            return None
        condition = fronted if fronted is not None else condition
        gate = None
        if condition is not None:
            key = _SELF_CONDITIONS.get(condition.strip())
            if key is None:
                from .grammar import condition_payload_for

                gate = condition_payload_for(condition)
                if gate is None or not _cast_time_gate(gate):
                    return None
            condition = key
        # "{X} … where X is <count>" (Volcanic Salvo). A generic reduction whose
        # size is a question rather than a number; the pips must be exactly
        # "{X}" and the clause must name a count this table knows, or the line
        # refuses as it always did.
        counted_clause = match.group("counted")
        if counted_clause is not None:
            if match.group("pips").upper() != "{X}":
                return None
            counted = _SELF_REDUCTION_COUNTS.get(counted_clause.strip())
            if counted is None:
                return None
            return SelfCostReduction(
                CostReduction(0), condition=condition,
                during_your_turn=bool(match.group("during")), counted=counted,
                gate=gate,
            )
        generic = 0
        colored: dict[str, int] = {}
        for symbol in re.findall(r"\{([^}]+)\}", match.group("pips").upper()):
            if symbol.isdigit():
                generic += int(symbol)
            elif symbol in _MANA_SYMBOLS:
                colored[symbol] = colored.get(symbol, 0) + 1
            else:
                # {X} and the hybrid symbols reduce by an amount this cannot
                # compute; refuse rather than under-charging. A "{X} … where X
                # is <count>" clause is handled above and never reaches here.
                return None
        return SelfCostReduction(
            reduction=CostReduction(generic, tuple(sorted(colored.items()))),
            condition=condition,
            during_your_turn=match.group("during") is not None,
            gate=gate,
        )
    return None


def self_reduction_claims_line(line: str) -> bool:
    """Whether *line* is, in its entirety, a self-reduction this can apply."""
    return self_cost_reduction(line.strip()) is not None


# ---------------------------------------------------------------------------
# A spell's own increase, sized by how many targets it chose (CR 601.2f)
# ---------------------------------------------------------------------------

# "This spell costs {1} more to cast for each target beyond the first."
# (Fireball.) / "This spell costs 3 life more to cast for each target."
# (Phyrexian Purge.) The *increase* twin of the self-reduction above, and one
# template rather than two: what differs between the pool's two printings is
# the resource and whether the first target is free, and both of those are
# payload.
#
# It is a **self** tax, so no scan of any battlefield could find it -- exactly
# the split this module's header draws between a permanent's modifier and a
# spell's own. And its size is not in the sentence: CR 601.2c chooses targets
# before 601.2f calculates the cost, which is the ordering that makes "for each
# target" answerable at all.
#
# Fireball's half of it used to be a substring test inside
# `mixins/stack/casting.queue_from_hand`, and a literal in parse_coverage's
# `_MIXIN_TEXT_SCANS` claiming it -- one card's sentence written out twice.
# Phyrexian Purge is the second card that shares the shape, which is the bar
# `card_hooks.py` states for staying out of it.
_SELF_PER_TARGET_TAX = re.compile(
    r"^this spell costs (?:\{(?P<generic>\d+)\}|(?P<life>\d+) life) more to "
    r"cast for each target(?P<beyond> beyond the first)?$"
)


@dataclass(frozen=True)
class SelfPerTargetTax:
    """How much more a spell costs itself, per target it chose.

    ``life`` is the resource, not a flag on an amount: CR 118.3b pays a life
    cost with life, and folding it into the generic mana total would let a
    Mountain pay it -- the same reason ``CostModifier.life`` is its own field.

    ``beyond_first`` is Fireball's exemption. Charging its absence would tax the
    first target too, which is a spell costing more than it prints; charging its
    presence where it is not printed is the other direction, and worse.
    """

    amount: int
    life: bool = False
    beyond_first: bool = False

    def owed(self, targets: int) -> int:
        """What *targets* chosen targets cost, in this tax's resource."""
        charged = targets - 1 if self.beyond_first else targets
        return self.amount * max(0, charged)


@lru_cache(maxsize=None)
def self_per_target_tax(oracle_text: str) -> "SelfPerTargetTax | None":
    """The per-target increase *oracle_text* applies to itself, if any.

    Read per line and anchored at both ends, exactly as
    :func:`self_cost_reduction` reads its own: a template found in the middle of
    a longer sentence would be a cost the card does not print.
    """
    for line in oracle_text.lower().split("\n"):
        match = _SELF_PER_TARGET_TAX.match(line.strip().rstrip("."))
        if match is None:
            continue
        generic = match.group("generic")
        return SelfPerTargetTax(
            amount=int(generic if generic is not None else match.group("life")),
            life=generic is None,
            beyond_first=match.group("beyond") is not None,
        )
    return None


def self_per_target_tax_claims_line(line: str) -> bool:
    """Whether *line* is, in its entirety, a per-target increase this charges."""
    return self_per_target_tax(line.strip()) is not None


def _counted_reduction(game, caster_index: int, counted: str) -> int:
    """How large a "where X is …" self-reduction currently is.

    One function per named count, and each is a *different* kind of question:
    one reads the board, the other a turn history. Neither is an
    ``ObjectFilter`` — "total power" is an aggregate rather than a tally, and
    damage dealt this turn is not on any battlefield — which is why they are
    named clauses here rather than routed through ``count_spec``.
    """
    caster = game.players[caster_index]
    if counted == "total_power_you_control":
        # The *computed* power (CR 613), so a pumped or animated permanent
        # counts for what it currently is. Negative power contributes nothing:
        # CR 107.1b has no negative amounts, and a -3/-3 creature must not make
        # the spell cost more.
        return sum(
            max(0, perm.effective_power)
            for perm in game.controlled_by(caster_index)
            if perm.is_creature
        )
    if counted == "noncombat_damage_to_opponents_this_turn":
        # A turn history rather than a board read: the damage is gone the
        # instant it is dealt, so nothing on any battlefield could answer this.
        return int(caster.noncombat_damage_dealt_to_opponents_this_turn)
    return 0


def self_cost_reduction_for_cast(game, caster_index: int, card) -> CostReduction:
    """*card*'s own reduction, if its condition holds as it is being cast."""
    described = self_cost_reduction(card.oracle_text or "")
    if described is None:
        return CostReduction()
    if described.during_your_turn and game.active_player_index != caster_index:
        return CostReduction()
    caster = game.players[caster_index]
    if described.condition == "cast_instant_or_sorcery":
        if not any(
            "instant" in spell.type_line.lower() or "sorcery" in spell.type_line.lower()
            for spell in caster.spells_cast_this_turn
        ):
            return CostReduction()
    elif described.condition == "gained_three_life":
        if caster.life_gained_this_turn < 3:
            return CostReduction()
    # "If you have 3 or less life, …" (Avatar of Hope). Asked now, at CR
    # 601.2f, which is when a cost is calculated — so the AI's affordability
    # read, the client's playable highlight and the cast itself all see the
    # same answer, because all three come through ``cost_reduction_for_cast``.
    if described.gate is not None and not _gate_holds(
        game, caster_index, card, described.gate
    ):
        return CostReduction()
    # "…where X is <count>": the size is asked of the caster now, at CR 601.2f,
    # which is when a cost is calculated — not at announcement and not at
    # resolution, so a creature entering in response does not change what was
    # already paid.
    if described.counted is not None:
        return CostReduction(_counted_reduction(game, caster_index, described.counted))
    return described.reduction


def cost_reduction_for_cast(
    game, caster_index: int, card
) -> tuple[CostReduction, list[str]]:
    """Everything that comes off *card*'s cost as *caster_index* casts it.

    The two mechanisms meet here and nowhere else: a permanent's modifier, found
    by scanning battlefields, and the spell's own, read off its text. One
    function because two callers need the answer — the cast path and the AI's
    affordability read — and a discount only one of them can see is a spell the
    AI declines to cast or tries to cast and cannot.
    """
    board, names = spell_cost_reduction(game, caster_index, card)
    own = self_cost_reduction_for_cast(game, caster_index, card)
    combined = CostReduction(
        board.generic + own.generic,
        tuple(sorted((dict(board.colored) | dict(own.colored)).items())),
    )
    if own and not names:
        names = [card.name]
    return combined, names


def reduce_cost(required: dict[str, int], reduction: CostReduction) -> dict[str, int]:
    """Apply *reduction* to a parsed cost, per CR 118.7a–d.

    - 118.7a a generic reduction touches only the generic component;
    - 118.7b a coloured reduction against a cost with no mana of that colour
      comes off generic instead;
    - 118.7c a coloured reduction larger than that colour's component takes it
      to nothing and the difference comes off generic.

    Nothing goes below zero (CR 601.2f). Written as one function because these
    four sentences are the whole of what a reduction *is*, and a caller doing
    the subtraction itself is a caller that will get 118.7b wrong.
    """
    cost = dict(required)
    for symbol, amount in reduction.colored:
        paid = min(cost.get(symbol, 0), amount)
        cost[symbol] = cost.get(symbol, 0) - paid
        spill = amount - paid
        if spill:
            cost["generic"] = max(0, cost.get("generic", 0) - spill)
    cost["generic"] = max(0, cost.get("generic", 0) - reduction.generic)
    return cost


def buyback_cost_reduction(game) -> tuple[int, list[str]]:
    """Generic mana taken off every buyback cost by the board, and by whom.

    "Buyback costs cost {2} less." (Memory Crystal.) CR 601.2f applied to
    CR 702.27a's optional additional cost rather than to a spell's mana cost —
    which is why this is its own reader rather than a call into :func:`_tax`:
    that one asks ``_matches`` about the *card being cast*, and this modifier
    has no opinion about the card at all. Every buyback cost is reduced, on
    anybody's spell.

    One application per permanent printing it, over every battlefield, the same
    arithmetic every other modifier in this file uses — two Memory Crystals take
    {4} off. Read off ``effective_card`` for :func:`_tax`'s reason: a permanent
    whose text an effect has changed grants what it currently says.

    The reduction touches the **charge** and never the announcement's key. The
    key is the printed cost (``cast_costs.buyback_cost``), and it is what
    ``buyback_paid`` reads back at resolution to decide whether the spell
    returns to its owner's hand — so a caster who paid a reduced {0} for a
    printed {2} still bought the card back. Reducing the key instead would make
    a Memory Crystal on the battlefield the difference between a spell that
    comes back and one that does not.
    """
    total = 0
    names: list[str] = []
    for _seat, permanent in game.permanents_with_controller():
        for modifier in cost_modifiers_for(permanent.effective_card.oracle_text):
            if modifier.applies_to != "buyback" or not modifier.reduces:
                continue
            total += modifier.amount
            names.append(permanent.card.name)
    return total, names
