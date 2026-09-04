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
    applies_to -- "cast" for spells, "activate" for activated abilities
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
_SPELL_SUBJECT_TEXT = rf"(?:(?:{_COLOURS}) )?(?:(?:{_TYPE_LIST}) )?spells"
_SPELL_SUBJECT = re.compile(
    rf"^(?:(?P<colour>{_COLOURS}) )?(?:(?P<type>{_TYPE_LIST}) )?spells$"
)
# Split only where the "and" separates two *whole* subjects. `_TYPE_LIST`
# spells its own alternation with the same word -- "Instant and enchantment
# spells" (Mana Matrix) is one phrase -- so a bare split on " and " would tear
# that card's subject in half and leave "instant" reading as nothing.
_SUBJECT_SPLIT = re.compile(r"(?<=spells) and ")
_SPELL_TAX = re.compile(
    rf"(?P<subjects>{_SPELL_SUBJECT_TEXT}(?: and {_SPELL_SUBJECT_TEXT})*)"
    r"(?: with (?P<keyword>[a-z]+))?(?P<controller> you cast)? cost "
    r"(?P<amount>(?:\{(?:\d+|[wubrgc])\})+) (?P<direction>more|less) to cast"
)


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
_TARGETING_MANA_TAX = re.compile(
    r"spells your opponents cast that target this creature cost "
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
                controller="opponents",
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
    for match in _SACRIFICE_SYMBOL_TAX.finditer(text):
        modifier = _sacrifice_symbol_modifier(match)
        if modifier is not None:
            modifiers.append(modifier)
    return tuple(modifiers)


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
      refusal exists to prevent.
    """
    generic, pips = _tax_symbols(match.group("amount"))
    if generic < 0:
        return None
    if pips and match.group("direction") == "less":
        return None
    subjects: list[tuple[str | None, tuple[str, ...]]] = []
    for printed in _SUBJECT_SPLIT.split(match.group("subjects")):
        read = _SPELL_SUBJECT.match(printed.strip())
        if read is None:
            return None
        subjects.append(
            (
                _COLOR_WORD_TO_SYMBOL.get(read.group("colour") or ""),
                _types_named(read.group("type")),
            )
        )
    colour, card_types = subjects[0]
    return CostModifier(
        amount=generic,
        applies_to="cast",
        reduces=match.group("direction") == "less",
        colour=colour,
        card_types=card_types,
        keyword=match.group("keyword"),
        controller="you" if match.group("controller") else None,
        symbols=pips,
        alternative_subjects=tuple(subjects[1:]),
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
            _ABILITY_TAX, _TARGETING_LIFE_TAX, _TARGETING_MANA_TAX,
        )
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
    colour: str | None, card_types: tuple[str, ...], card
) -> bool:
    """Whether *card* is one of the objects a single printed noun phrase names."""
    if colour and colour not in (card.colors or ()):
        return False
    if card_types and not any(
        _has_printed_type(card, wanted) for wanted in card_types
    ):
        return False
    return True


def _matches(modifier: CostModifier, card) -> bool:
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
        _subject_matches(colour, card_types, card)
        for colour, card_types in (
            (modifier.colour, modifier.card_types),
            *modifier.alternative_subjects,
        )
    )


def _tax(
    game, card, applies_to: str, *, wanted: str,
    controller_index: int | None = None, targeted=(),
) -> tuple[int, list[str]]:
    """The total *wanted* ("more" or "less") change to *card*'s cost from every
    permanent on any battlefield, and those permanents' names for the log.

    One application per permanent — two Glooms tax {6} — and the scan covers
    every battlefield, because a cost modifier is not scoped to its own
    controller's side unless the card says so.
    """
    total = 0
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
            if modifier.applies_to != applies_to or not _matches(modifier, card):
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
            total += modifier.amount
            names.append(permanent.card.name)
    return total, names


def spell_cost_tax(
    game, caster_index: int, card, targeted=(),
) -> tuple[int, list[str]]:
    """Extra generic mana for casting *card*, plus the taxing permanents' names.

    *targeted* is what the spell points at, for the modifiers whose scope is a
    fact about the chosen targets ("spells your opponents cast **that target
    this creature**", Pursued Whale). It defaults to empty, which is what makes
    every other caller's answer unchanged: a targets-scoped modifier simply does
    not apply when nothing is aimed at its source.
    """
    return _tax(
        game, card, "cast", wanted="more", controller_index=caster_index,
        targeted=targeted,
    )


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
    total: dict[str, int] = {}
    names: list[str] = []
    for seat, permanent in game.permanents_with_controller():
        for modifier in cost_modifiers_for(permanent.effective_card.oracle_text):
            if not modifier.symbols or modifier.reduces:
                continue
            if modifier.applies_to != "cast" or not _matches(modifier, card):
                continue
            if modifier.controller == "you" and seat != caster_index:
                continue
            if modifier.controller == "opponents" and seat == caster_index:
                continue
            if modifier.targets_source and not any(
                aimed is permanent for aimed in targeted
            ):
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


def ability_cost_tax(game, controller_index: int, source) -> tuple[int, list[str]]:
    """Extra generic mana for activating *source*'s ability, plus the taxing
    permanents' names. Matched against the source's *effective* card so a
    copied or animated permanent is taxed on what it currently is."""
    return _tax(
        game, source.effective_card, "activate", wanted="more",
        controller_index=controller_index,
    )


# ---------------------------------------------------------------------------
# A spell's own reduction (CR 601.2f), and the arithmetic every reduction uses
# ---------------------------------------------------------------------------


# "[During your turn, ]this spell costs {…} less to cast[ if <condition>]."
_SELF_REDUCTION = re.compile(
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
_SELF_CONDITIONS: dict[str, str] = {
    "you've cast an instant or sorcery spell this turn": "cast_instant_or_sorcery",
    "you've gained 3 or more life this turn": "gained_three_life",
}


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
    from .subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

    match = _ABILITY_SELF_REDUCTION.match(line.strip().lower())
    if match is None:
        return None
    described = subject_filter_payload(match.group("subject"), plural=True)
    if described is None:
        return None
    if set(described) - set(TESTABLE_SUBJECT_FILTER_KEYS):
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


@lru_cache(maxsize=None)
def self_cost_reduction(oracle_text: str) -> SelfCostReduction | None:
    """The reduction *oracle_text*'s own first line applies to itself, if any."""
    for line in oracle_text.lower().split("\n"):
        match = _SELF_REDUCTION.match(line.strip())
        if match is None:
            continue
        condition = match.group("condition")
        if condition is not None:
            key = _SELF_CONDITIONS.get(condition.strip())
            if key is None:
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
                CostReduction(0), condition=None,
                during_your_turn=bool(match.group("during")), counted=counted,
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
