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

Split by those two shapes at the 2,000-line cap: a permanent's modifier, read
off its line, is ``engine/cost_modifier_lines.py`` (with ``CostModifier`` and
``CostReduction``), and a spell's own is ``engine/self_cost_modifiers.py``.
This module keeps what a modifier comes to on a board (the scan, the matching,
the taxes, :func:`reduce_cost`) and :func:`cost_modifier_claims_line`, which
claims a line for both.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .cost_modifier_lines import (
    MULTICOLORED,
    CostModifier,
    CostReduction,
    _SPELL_TAX,
    _TARGETING_LIFE_TAX,
    _TARGETING_MANA_TAX,
    _SACRIFICE_SYMBOL_TAX,
    _SACRIFICE_SOURCE_TAX,
    _ABILITY_TAX,
    _ABILITY_REDUCTION,
    _BUYBACK_REDUCTION,
    _KEYWORD_ABILITY_REDUCTION,
    _KEYWORD_COST_MODIFIER,
    cost_modifiers_for,
    _keyword_cost_modifier,
    _keyword_ability_reduction,
    _spell_tax_modifier,
    _sacrifice_symbol_modifier,
    _sacrifice_source_modifier,
)
from .self_cost_modifiers import (
    ability_self_reduction,
    self_reduction_claims_line,
    self_per_target_tax_claims_line,
    self_cost_reduction_for_cast,
)

# Re-exported: names that moved to ``engine/self_cost_modifiers.py`` at the
# 2,000-line split and are still pulled from here by ``mixins/stack/casting``
# and ``mixins/stack/activation``, which another group was splitting in the
# same round. New code imports a name from the module that defines it.
from .self_cost_modifiers import (ability_self_reduction_amount,
                                  self_per_target_tax)


def cost_modifier_claims_line(line: str) -> bool:
    """Whether *line* is, in its entirety, one of the templates
    ``engine/cost_modifier_lines.py`` and ``engine/self_cost_modifiers.py``
    read.

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
    # Claimed only when the keyword is one the cast path pays a cost *by*, for
    # the same reason: "Madness costs you pay cost {2} less" matches the
    # pattern and nothing would charge it.
    keyword_cost = _KEYWORD_COST_MODIFIER.match(text)
    if (
        keyword_cost is not None
        and keyword_cost.end() == len(text)
        and _keyword_cost_modifier(keyword_cost) is not None
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
    # …and Brutal Suppression's, on the same condition: claimed only when both
    # noun phrases read, because otherwise no modifier is produced.
    scoped = _SACRIFICE_SOURCE_TAX.match(text)
    if (
        scoped is not None
        and scoped.end() == len(text)
        and _sacrifice_source_modifier(scoped) is not None
    ):
        return True
    if self_per_target_tax_claims_line(line):
        return True
    return self_reduction_claims_line(line)


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
    if colour == MULTICOLORED:
        # "**Multicolored** spells…" (Urza's Filter). CR 105.2b through the one
        # reader of the relation, over the same effective colours the colour
        # test below reads — so a gold card a Celestial Dawn has made white is
        # not multicoloured while it is being cast, and a hybrid card is.
        from .object_colors import is_multicolored

        if not is_multicolored(colors):
            return False
    elif colour and colour not in colors:
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
    for ``aura_grants.attached_ability_cost_reduction``'s reason: two
    reductions must not cancel each other's protection against a free ability.

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
    # "You may cast this spell as though it had flash **if you pay {2} more to
    # cast it**." (Rout and Invasion's four others.) An additional cost the
    # card prints on itself rather than one a permanent imposes, and here for
    # this function's own stated reason: a caster asking "what does this cost?"
    # must get one answer, and this price is part of it exactly when the spell
    # is being cast outside sorcery timing. ``cast_timing`` decides when.
    from .cast_timing import flash_surcharge_owed

    flash_price = flash_surcharge_owed(game, caster_index, card)
    if flash_price:
        return (
            total + stack_total + flash_price,
            names + stack_names + [f"{card.name}'s own flash price"],
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
    game, payer_index: int, cost, applies_to: str, *, source=None,
) -> tuple[SacrificeDemand, ...]:
    """Every "cost an additional \"Sacrifice a …\"" demand on an object whose
    cost is *cost*.

    One entry per taxing permanent, because each is its own ability — two
    Droughts charge twice — and the scan covers every battlefield, for the
    reason ``_tax`` gives: a cost modifier is not scoped to its controller's
    side unless the card says so.

    *source* is the permanent whose ability is being activated, for a tax whose
    subject is what that permanent *is* (Brutal Suppression's "nontoken
    Rebels"). None — a caller with no permanent in hand — is never taxed by
    such a modifier, because its subject names a permanent (CR 109.2).

    Returned as demands rather than performed here, because the two payers ask
    at different moments in their own announcement (CR 601.2h against
    CR 602.2b) and both need the *gate* before anything is spent.
    """
    from .subject_filters import subject_matches

    demands: list[SacrificeDemand] = []
    for seat, permanent in game.permanents_with_controller():
        for modifier in cost_modifiers_for(permanent.effective_card.oracle_text):
            if modifier.sacrifice_filter is None:
                continue
            if modifier.per_symbol is None and modifier.source_filter is None:
                continue
            if modifier.applies_to != applies_to:
                continue
            if not _timing_holds(game, modifier, payer_index):
                continue
            if modifier.source_filter is not None:
                # Asked through the one matcher, observed from the taxing
                # permanent's seat (CR 109.5) — "nontoken" and the creature
                # type are both layer-computed, so a token Rebel or a Rebel
                # that stopped being one is not taxed.
                count = int(
                    source is not None
                    and subject_matches(
                        game, source, dict(modifier.source_filter),
                        observer=seat, source=permanent,
                    )
                )
            else:
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


def keyword_cost_modifiers(
    game, payer_index: int, keyword: str | None,
) -> tuple[int, int, list[str]]:
    """``(generic added, generic taken off, by whom)`` for the *keyword*
    alternative cost *payer_index* is paying — "Flashback costs you pay cost
    {2} less." / "Flashback costs your opponents pay cost {2} more."
    (Catalyst Stone.)

    CR 601.2f over CR 702.34a's cost. Its own reader rather than a call into
    :func:`_tax`, for :func:`buyback_cost_reduction`'s reason: that function
    asks ``_matches`` about the *card being cast*, and these modifiers have no
    opinion about the card — only about which cost is being paid and by whom.
    The two numbers are returned apart because the cast path adds an increase
    before it applies a reduction (CR 601.2f), and a reduction touches only
    the generic component and stops at zero (CR 118.7a, :func:`reduce_cost`);
    netting them here would let a {2} increase be eaten by a {2} reduction
    that the cost's generic part was too small to take.

    One application per permanent printing it, over every battlefield — two
    Catalyst Stones take {4} off their controller's flashback costs. Read off
    ``effective_card`` for :func:`_tax`'s reason. ``(0, 0, [])`` for a cost
    that is the price of no keyword, which is every cast but a flashback.

    "**You** pay" is the permanent's controller (CR 109.5) and "your
    opponents pay" every seat that controller is not, asked of the control
    seam so a Stone that changes hands taxes its old controller.
    """
    if not keyword:
        return 0, 0, []
    more = less = 0
    names: list[str] = []
    for seat, permanent in game.permanents_with_controller():
        for modifier in cost_modifiers_for(permanent.effective_card.oracle_text):
            if modifier.applies_to != keyword:
                continue
            if (modifier.controller == "you") != (seat == payer_index):
                continue
            if modifier.reduces:
                less += modifier.amount
            else:
                more += modifier.amount
            names.append(permanent.card.name)
    return more, less, names


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
