"""A permanent's cost modifier, read off its printed line (CR 601.2f, 118.9).

The first of ``engine/cost_modifiers.py``'s two shapes: a static ability that
changes the cost of *other* objects. "<colour> <type> spells cost {N} more (or
less) to cast", "activated abilities of … cost {N} more to activate", the
targeting and sacrifice taxes, the keyword-cost modifiers. Each is a filter
plus an amount (``CostModifier``), read by ``cost_modifiers_for`` and kept per
line. ``CostReduction``, the value every reduction is expressed in (CR 118.7),
is here too, because both shapes read into it.

Split out of ``engine/cost_modifiers.py`` at the 2,000-line cap. What a
modifier comes to on a board (the battlefield scan, the matching, the taxes)
stays there, with ``cost_modifier_claims_line``, which claims a line for both
shapes.
"""

from __future__ import annotations

import re
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
#: "**Multicolored** spells cost {2} less to cast." (Urza's Filter.) Printed in
#: the slot a colour word takes and answered by the same reading of the taxed
#: object's colours, but it is not a colour (CR 105.4) — it is a count of them
#: (CR 105.2b: two or more). So it rides ``CostModifier.colour`` as this word
#: rather than as a mana symbol, and :func:`_subject_matches` is the one place
#: that tells the two apart. A reader that took the field for a symbol would
#: look for a colour called "multicolored" and tax nothing, which is the
#: direction that fails closed.
MULTICOLORED = "multicolored"
#: The words the colour slot of a *spell* subject may print. The activated-
#: ability templates below keep ``_COLOURS`` alone: nothing prints "activated
#: abilities of multicolored creatures", and admitting it there would be a
#: narrowing those readers charge without ever having been shown a card.
_SPELL_COLOURS = f"{_COLOURS}|{MULTICOLORED}"


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
    colour     -- mana symbol the affected object must have, or None for any;
                  ``MULTICOLORED`` where the sentence prints that word in the
                  colour's place (Urza's Filter) — two or more colours
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
    #: "Activated abilities of **nontoken Rebels** cost an additional
    #: \"Sacrifice a land\" to activate." (Brutal Suppression.) What the taxed
    #: ability's *source* must be, as the payload ``subject_matches`` tests —
    #: the noun phrase read by the grammar's noun parser, so "nontoken" is a
    #: key and not a word dropped. Set only on a sacrifice tax charged once per
    #: activation (``per_symbol`` None); Drought's taxes every ability and
    #: leaves it None.
    source_filter: dict | None = None


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
    rf"(?:(?:{_SPELL_COLOURS}) )?(?:(?:{_TYPE_LIST}) )?spells?{_CHOSEN_TYPE_TAIL}?"
)
_SPELL_SUBJECT = re.compile(
    rf"^(?:(?P<colour>{_SPELL_COLOURS}) )?(?:(?P<type>{_TYPE_LIST}) )?"
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
    # Never from the middle of a word. This pattern is *searched* over a whole
    # text (``cost_modifiers_for``), and a colour word is a suffix of other
    # words: "multicolo**red spells cost {2} less to cast**" (Urza's Filter)
    # was read, from there, as a discount on red spells — by a card reporting
    # unsupported, which is the only reason nothing was ever charged by it.
    rf"(?<![a-z])(?P<each>each )?"
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

# "Activated abilities of nontoken Rebels cost an additional "Sacrifice a land"
# to activate." (Brutal Suppression.) Drought's imposed sacrifice with the
# subject narrowed by what the ability's **source** is, and sized once per
# activation rather than per symbol. CR 605.1a makes a mana ability an
# activated ability, and the sentence names no exception, so none is made.
_SACRIFICE_SOURCE_TAX = re.compile(
    r"activated abilities of (?P<subject>[a-z][a-z ]*?) cost an additional "
    r'"sacrifice (?P<noun>(?:a|an) [a-z ]+)" to activate'
)


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
#: sentences are required** for ``aura_grants._ABILITY_COST_REDUCTION``'s
#: reason one module over: the floor is not decoration, it is what stops a {1}
#: ability becoming free, and a pattern claiming only the first sentence would
#: leave the second unclaimed while quietly implementing a cheaper card. The
#: two are printed as one line, which is why this reads across the full stop.
_ABILITY_REDUCTION = re.compile(
    rf"activated abilities of (?:(?P<colour>{_COLOURS}) )?(?P<type>{_TYPE_LIST})s? cost "
    r"\{(?P<amount>\d+)\} less to activate\. this effect can't reduce the mana "
    r"in that cost to less than (?P<floor>one|two|three) mana"
)

#: The floor's printed number words, the same three ``engine/aura_grants.py``
#: reads for the identical rider.
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

#: "**Flashback costs you pay cost {2} less.**" / "**Flashback costs your
#: opponents pay cost {2} more.**" (Catalyst Stone.) CR 601.2f applied to one
#: keyword's **alternative cost** (CR 702.34a, CR 118.9d: "any additional
#: costs, cost increases, and cost reductions that affect that spell are
#: applied to that alternative cost").
#:
#: ``_BUYBACK_REDUCTION``'s shape two fields wider, and both are printed: this
#: one names *who is paying* ("you" is the permanent's controller, CR 109.5;
#: "your opponents" is everybody that controller is not) and runs in both
#: directions. Like that row it carries no colour and no card type — it has no
#: opinion about the spell at all, only about which cost is being paid for
#: it — so it gets its own ``applies_to`` rather than riding "cast", where an
#: unnarrowed modifier would change every spell's **mana cost**.
#:
#: The keyword is captured rather than spelled into the pattern for
#: ``_KEYWORD_ABILITY_REDUCTION``'s reason: the refusal needs something to
#: name. Only a keyword the cast path can recognise a cost *by*
#: (``AlternativeCost.keyword``) is admitted.
_KEYWORD_COST_MODIFIER = re.compile(
    r"(?P<keyword>[a-z]+) costs (?P<payer>you|your opponents) pay cost "
    r"\{(?P<amount>\d+)\} (?P<direction>less|more)"
)

#: The keywords :data:`_KEYWORD_COST_MODIFIER` may name: the ones whose cost
#: the cast path pays as a keyworded alternative cost and can therefore tell
#: apart from the mana cost it replaces. One entry, and the set is what makes
#: the refusal loud — a card naming any other keyword matches the pattern,
#: produces no modifier, is claimed by no line and reports unsupported.
_MODIFIABLE_COST_KEYWORDS = frozenset({"flashback"})

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
        # "Flashback costs your opponents pay cost {2} more." (Catalyst
        # Stone.) The same early exit asked of a single line: its sentence
        # ends at "more" with no "to <verb>" behind it either.
        and "pay cost" not in text
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
    for match in _KEYWORD_COST_MODIFIER.finditer(text):
        modifier = _keyword_cost_modifier(match)
        if modifier is not None:
            modifiers.append(modifier)
    for match in _SACRIFICE_SYMBOL_TAX.finditer(text):
        modifier = _sacrifice_symbol_modifier(match)
        if modifier is not None:
            modifiers.append(modifier)
    for match in _SACRIFICE_SOURCE_TAX.finditer(text):
        modifier = _sacrifice_source_modifier(match)
        if modifier is not None:
            modifiers.append(modifier)
    return tuple(modifiers)


def _keyword_cost_modifier(match: "re.Match[str]") -> CostModifier | None:
    """The modifier :data:`_KEYWORD_COST_MODIFIER` matched, or None when the
    keyword it names is one the cast path cannot recognise a cost by.

    Split out for ``_keyword_ability_reduction``'s reason: a pattern that
    matches and then produces no modifier must also not *claim* the line, and
    both questions are asked by calling this.

    ``applies_to`` is the keyword itself, which is what keeps this out of the
    two readers that would misapply it: ``_tax`` filters on "cast" and
    "activate" by equality, so a spell's mana cost never sees a flashback
    modifier, and :func:`cost_modifiers.keyword_cost_modifiers` is the only
    reader that asks for one.
    """
    keyword = match.group("keyword")
    if keyword not in _MODIFIABLE_COST_KEYWORDS:
        return None
    return CostModifier(
        amount=int(match.group("amount")),
        applies_to=keyword,
        reduces=match.group("direction") == "less",
        controller="you" if match.group("payer") == "you" else "opponents",
    )


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
        printed_colour = read.group("colour") or ""
        subjects.append(
            (
                # "Multicolored" stays the word (see ``MULTICOLORED``): mapped
                # through the symbol table it would come back None, which is
                # "any colour" — every spell in the game {2} cheaper.
                MULTICOLORED if printed_colour == MULTICOLORED
                else _COLOR_WORD_TO_SYMBOL.get(printed_colour),
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


def _sacrifice_source_modifier(match: "re.Match[str]") -> CostModifier | None:
    """Brutal Suppression's clause as a modifier, or None when either noun
    phrase is one ``subject_matches`` cannot test — the subject (whose
    abilities are taxed) or the payment (what may be sacrificed). Both go
    through the grammar's noun parser, so a word it does not read refuses the
    line rather than widening the tax or the payment.
    """
    from .grammar import subject_filter_payload

    subject = subject_filter_payload(match.group("subject"), plural=True)
    payment = subject_filter_payload(match.group("noun"))
    if not subject or not payment:
        return None
    return CostModifier(
        amount=0,
        applies_to="activate",
        sacrifice_filter=payment,
        source_filter=subject,
    )


def _types_named(clause: str | None) -> tuple[str, ...]:
    """The card types a printed type clause names, in order.

    "instant and enchantment" is two; "white" alone is none, because the colour
    is its own group. Splitting here rather than in the pattern keeps the count
    of types payload — a card printing three would need no change.
    """
    if not clause:
        return ()
    return tuple(re.findall(_TYPES, clause))


def cost_modifier_reduction_sentences(oracle_text: str) -> tuple[str, ...]:
    """The sentences :data:`_ABILITY_REDUCTION` reads, or empty.

    The reduction is **two sentences on one printed line** -- the amount and the
    floor -- and neither means anything alone, so the reader matches them
    joined. This names the pair for a caller that walks a card sentence by
    sentence (``scripts/parse_coverage.py``), which would otherwise report the
    floor as text nothing read. The same arrangement
    ``aura_grants.aura_cost_reduction_sentences`` makes for the identical rider
    on an Aura.
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
