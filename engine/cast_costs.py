"""Text-keyed *additional* costs a spell prints in its own text (CR 601.2b).

The same model as ``cast_restrictions.py``, and for the same reason: "As an
additional cost to cast this spell, sacrifice a creature" means the same thing
on every card that prints it, so it is a table keyed by the canonical phrase
rather than four per-card hooks. A new card printed with a known phrase needs no
registration at all.

**What this replaced was not a gap, it was worse than one.** The phrase sat in
``SUPPORTED_SPELL_PATTERNS`` — a substring whitelist whose match produces a
marker instruction with no handler — so Village Rites compiled to "draw two
cards" plus a no-op, reported ``supported``, and cast **for free**: the cost was
claimed, never paid, and nothing in the engine knew the difference. Thrill of
Possibility's discard did not even get the marker. Alpha's Sacrifice and
Metamorphosis escaped only because a *card hook* folded the cost into their
effect, which is why the general form had never been needed.

A cost is not an effect, so none of this is an instruction. The compiler asks
this table whether a line is a cost (which is what stops the line being reported
"too complex"), and ``queue_from_hand`` asks it twice more: once before any
payment, because CR 601.2h says an unpayable cost can't be paid and CR 601.2h's
failure is *the spell can't be cast*, and once after, to perform it.

The cost objects and the clause table itself (what each printed clause charges,
and the readers that turn one line into one ``AdditionalCost``) are
``engine/cast_cost_clauses.py``, split out beneath this module at the
2,000-line cap. This module keeps the two keywords that are rewrites onto it
(buyback, kicker) and the per-card entry points the compiler and the cast path
ask.
"""

from __future__ import annotations

import re

from functools import lru_cache
from typing import TYPE_CHECKING

from .cast_cost_clauses import (
    OptionalManaCost,
    AdditionalCost,
    _ADDITIONAL_COST_PREAMBLE,
    _SELF_PERMISSION_COSTS,
    _read_cost_clauses,
    _printed_additional_cost,
    additional_cost_for_line,
    _COST_CLAUSE_SPLIT,
)
from .oracle_types import compilation_cache

# Re-exported: ``__all__`` names that moved to ``engine/cast_cost_clauses.py``
# at the 2,000-line split, and this module stays their import path.
from .cast_cost_clauses import (read_return_clause, read_sacrifice_all_clause,
                                read_sacrifice_clause)

if TYPE_CHECKING:
    from .models import CardDefinition


# ---------------------------------------------------------------------------
# Buyback (CR 702.27)
# ---------------------------------------------------------------------------
#
# **A rewrite, not a flag**, for exactly ``engine/equipment.py``'s reason.
# CR 702.27a says "Buyback [cost]" *means* two static abilities that function
# while the spell is on the stack:
#
#   "You may pay an additional [cost] as you cast this spell" and "If the
#   buyback cost was paid, put this spell into its owner's hand instead of
#   into that player's graveyard as it resolves."
#
# The first of those is a sentence this table already reads in full, so the
# keyword line is rewritten into it before any line is classified
# (:func:`expand_buyback_lines`, composed into ``oracle.expand_ability_lines``)
# and from there nothing downstream knows the word: ``_read_cost_clauses``
# reads the offer, ``legality.cast_cost_offers`` prices it against the pool and
# the untapped lands, ``web/static/app.js``'s cast-offer prompt asks for it, and
# ``casting._optional_cost_announcement`` records how many times it was taken.
#
# The **second** static ability is the half none of that machinery had, and it
# is implemented at the one seam a resolving spell leaves the stack through
# (``mixins/stack/resolution._bin_spell_card``), asked through
# :func:`buyback_paid` below. The claim and the implementation cannot drift
# because they are the *same reader*: a card whose keyword line was rewritten
# into an offer is exactly a card :func:`buyback_cost` names a cost for, so the
# hand-return applies to every card the cost was charged on and to no other.

#: "Buyback {3}", "Buyback {1}{U}". The cost is a run of mana symbols taken
#: from the printed line so a coloured pip keeps its letter, exactly as
#: ``equipment._EQUIP_LINE`` takes an equip cost.
_BUYBACK_LINE = re.compile(
    r"^buyback\s+(?P<cost>(?:\{[^{}]+\})+)$", re.IGNORECASE
)

#: Any line that *is* a buyback keyword line, readable or not. The wider shape
#: is what the support gate asks (:func:`unread_cost_sentence`), so a printing
#: this file cannot read — a buyback whose cost is not mana, say — is reported
#: as an unimplemented cost rather than falling through to a gate that never
#: heard of the keyword and casting the spell for its printed mana alone.
#:
#: **What follows the word has to be a cost**, and the width is kept by not
#: asking whether it is a cost this file can *charge*: CR 702.27a is
#: "Buyback [cost]", and every printing of one opens its cost with a mana
#: symbol or with the em dash a non-mana cost is printed behind. So a
#: "Buyback {X}" nobody can pay still matches here and is still reported.
#:
#: This was a bare "^buyback" word-boundary probe until Memory Crystal, whose
#: line -- "Buyback costs cost {2} less." -- is not a keyword line at all but a
#: static ability *about* buyback costs, read in full by
#: ``engine/cost_modifiers.py``. The prefix claimed it, the rewrite could not
#: read it, and the card was reported as a cost nothing charges: a gate refusing
#: a card another table implements, which is the one direction this gate is not
#: for. The plural noun after the keyword is what says so, and a cost never
#: begins with one.
_BUYBACK_SHAPE = re.compile(r"^buyback\s*(?:[—–-]|\{)", re.IGNORECASE)

#: "**Buyback—Sacrifice a land**." (Constant Mists.) CR 702.27's cost is any
#: cost, not a run of mana symbols, and the printed form for a non-mana one puts
#: it after an em dash rather than after a space. Every other buyback in the
#: pool is mana; this shape is the one the keyword's rewrite could not read, so
#: the card was refused by the support gate rather than cast for its mana alone.
_BUYBACK_COST_LINE = re.compile(
    r"^buyback\s*[—–-]\s*(?P<cost>.+)$", re.IGNORECASE
)

_BUYBACK_REMINDER = re.compile(r"\([^)]*\)")

#: CR 702.27a's first static ability, spelled as the sentence
#: ``_ADDITIONAL_COST_PREAMBLE`` above already reads.
BUYBACK_RULES_TEXT = (
    "As an additional cost to cast this spell, you may pay {cost}."
)

#: The same static ability when the cost is not mana. "Pay" is the mana verb, so
#: the printed clause carries its own ("sacrifice a land") and the rewrite only
#: supplies the preamble and CR 601.2b's "may".
BUYBACK_COST_RULES_TEXT = (
    "As an additional cost to cast this spell, you may {cost}."
)


def _lowered_clauses(printed: str) -> str:
    """*printed* with the first letter of each clause lowercased.

    Only the first letter of each, never the whole word and never the whole
    clause: a printed subtype ("sacrifice a **Goblin**") is read by the noun
    parser with its case intact, and a wholesale lowercasing would eat it.
    """
    pieces = _COST_CLAUSE_SPLIT.split(printed)
    return "".join(
        piece if index % 2 else piece[:1].lower() + piece[1:]
        for index, piece in enumerate(pieces)
    )


def _buyback_line_offer(line: str) -> tuple[str, str] | None:
    """``(announcement key, rules sentence)`` for one buyback line, or None.

    The key is what ``optional_cost_payments`` is keyed by and what
    :func:`buyback_paid` reads back, so it must be *one* string on both sides.
    For a mana cost it is ``mana_cost_label``'s canonical spelling, the same one
    ``_optional_mana_offers`` gives the rewritten sentence. For a non-mana cost
    it is read straight back off the :class:`AdditionalCost` the rewritten
    sentence produces — not normalized a second time here, because a second
    normalization is a second answer, and the two disagreeing is a card that
    charged its buyback and went to the graveyard anyway.

    A non-mana cost the table cannot charge returns None, which leaves
    :func:`unread_cost_sentence` reporting the card rather than casting it for
    its printed mana with a price nobody was offered.
    """
    from .mana_payment import mana_cost_from_symbols, mana_cost_label

    stripped = " ".join(_BUYBACK_REMINDER.sub("", line or "").split())
    stripped = stripped.strip().rstrip(".")
    match = _BUYBACK_LINE.match(stripped)
    if match is not None:
        symbols = mana_cost_from_symbols(match.group("cost"))
        if not symbols:
            return None
        label = mana_cost_label(symbols)
        return label, BUYBACK_RULES_TEXT.format(cost=label)
    match = _BUYBACK_COST_LINE.match(stripped)
    if match is None:
        return None
    return _optional_cost_phrase_offer(match.group("cost"))


def _optional_cost_phrase_offer(printed_cost: str) -> tuple[str, str] | None:
    """``(announcement key, rules sentence)`` for a keyword's printed
    **non-mana** cost — the words behind the em dash of "Buyback—Sacrifice a
    land." and "Kicker—Sacrifice a land." — or None when the table cannot
    charge it.

    One reader for both keywords, which is the point: CR 702.27a and CR 702.33a
    define their keyword as the *same* sentence ("You may pay an additional
    [cost] as you cast this spell"), so the rewrite of a cost phrase cannot
    depend on which word stood in front of it. This was the tail of
    ``_buyback_line_offer`` until Planeshift printed the phrase behind
    "Kicker", and a second copy there would have been two answers to "what is
    this cost's key" — the one question :func:`kicked` and :func:`buyback_paid`
    cannot afford two answers to.

    The printed clause opens a line, so it is capitalized ("Sacrifice a land");
    mid-sentence it is not. Only the first letter is touched — a wholesale
    lowercasing would eat a printed subtype ("sacrifice a Goblin"), which the
    noun reader needs the case of.

    **Every clause, not only the first.** Such a cost is a *list* — "Pay 3 life,
    Discard a card at random" (Flowstone Flood) — and Magic capitalizes each
    item of it, because each opens where a sentence would. Lowering only the
    leading letter of the whole line left "Discard" capitalized in the middle
    of the rewritten sentence, where ``_COST_CLAUSES``' rows are lowercase and
    match nothing: the clause went unread and, by ``_read_cost_clauses``'
    all-or-nothing rule, took the whole cost with it. The split is the same one
    that reader splits on, so a clause boundary cannot mean two things.

    The key is read **back off** the :class:`AdditionalCost` the sentence
    produces rather than normalized a second time here: a second normalization
    is a second answer, and the two disagreeing is a spell that paid its kicker
    and resolved unkicked.
    """
    clause = printed_cost.strip().rstrip(".")
    if clause.startswith("{"):
        # "Kicker—**{2}{B}**, Discard a creature card." (Dralnu's Pet.) A list
        # that opens on mana prints no verb for it — the reminder text supplies
        # one, "You may pay {2}{B} and discard a creature card" — so the
        # rewrite does too, and the sentence it builds is one a card could
        # print.
        clause = "pay " + clause
    sentence = BUYBACK_COST_RULES_TEXT.format(cost=_lowered_clauses(clause))
    read = _printed_additional_cost(sentence)
    if read is None or read.optional_key is None:
        return None
    return read.optional_key, sentence


def _buyback_line_cost(line: str) -> str | None:
    """The canonical key one printed buyback line's offer is announced by, or
    None.

    Canonical for :func:`_buyback_line_offer`'s reason: this string is the key
    the announcement is recorded under and the key :func:`buyback_paid` reads it
    back by, and two spellings of one cost would make the read-back miss a
    payment that was really made.
    """
    offer = _buyback_line_offer(line)
    return None if offer is None else offer[0]


def is_buyback_line(line: str) -> bool:
    """Whether *line* is a printed buyback keyword line, readable or not."""
    stripped = _BUYBACK_REMINDER.sub("", line or "").strip()
    return _BUYBACK_SHAPE.match(stripped) is not None


def expand_buyback_line(line: str) -> str | None:
    """The CR 702.27a rules text for one printed buyback line, or None."""
    offer = _buyback_line_offer(line)
    return None if offer is None else offer[1]


def expand_buyback_lines(oracle_text: str) -> str:
    """*oracle_text* with every buyback keyword line rewritten to its rules text.

    Text without one is returned unchanged, so applying this to every card costs
    a substring test. Applied by the compiler before any line is classified —
    beside ``expand_equip_lines`` and for its reason: what the compiler reads
    and what every other reader of a card's lines reads must be one text.
    """
    if not oracle_text or "uyback" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_buyback_line(line) or line for line in oracle_text.split("\n")
    )


def buyback_cost(oracle_text: str) -> str | None:
    """The canonical symbols *oracle_text*'s buyback keyword offers, or None.

    Read off the **printed** text, which is what a resolving spell's
    ``CardDefinition`` still carries: the rewrite happens inside the compiler
    and nothing writes it back onto the card.
    """
    for line in (oracle_text or "").split("\n"):
        cost = _buyback_line_cost(line)
        if cost is not None:
            return cost
    return None


def buyback_paid(card: CardDefinition, choices: dict | None) -> bool:
    """Whether this cast of *card* paid its buyback cost (CR 702.27a).

    *choices* is the resolving stack item's own record — the pool is empty by
    resolution (CR 500.5) and the announcement is long over, so
    ``additional_costs_paid`` is the only place the answer survives, exactly as
    it is for "for each additional {1}{R} you paid".

    False for a card printing no buyback, which is every card but twelve: this
    is asked at every spell's resolution.
    """
    cost = buyback_cost(getattr(card, "oracle_text", "") or "")
    if cost is None:
        return False
    paid = (choices or {}).get("additional_costs_paid") or {}
    try:
        return int(paid.get(cost, 0) or 0) > 0
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Kicker (CR 702.33)
# ---------------------------------------------------------------------------
#
# **Buyback's shape exactly, and built on buyback's machinery rather than beside
# it.** CR 702.33a: "'Kicker [cost]' means 'You may pay an additional [cost] as
# you cast this spell.'" That is CR 601.2b's optional additional cost, the
# sentence this table already reads in full -- so the keyword line is rewritten
# into it before any line is classified (:func:`expand_kicker_lines`, composed
# into ``oracle.expand_ability_lines``) and nothing downstream knows the word:
# ``_read_cost_clauses`` reads the offer, ``legality.cast_cost_offers`` prices it
# against the pool and the untapped lands, the browser's cast-offer prompt asks
# for it, ``casting._optional_cost_announcement`` checks it and the stack item
# records it under ``additional_costs_paid``.
#
# What kicker has that buyback does not is that **other sentences of the card
# ask about it** -- "if this spell was kicked", "if it was kicked", "if this
# creature wasn't kicked" -- and CR 702.33d says when the answer is settled: "a
# spell has been kicked if its controller declared the intention to pay any or
# all of its kicker costs". So :func:`kicked` is the one reader, asked
#
# * by the condition evaluator, of a resolving spell's own stack record;
# * by ``resolution._resolve_card`` as a permanent spell becomes a permanent,
#   which stamps :data:`KICKED` on it -- because the permanent is what an entry
#   replacement, an entry trigger and Skizzik's end-step trigger turns later
#   read, and the stack item is gone by then (CR 400.7 gives a permanent that
#   leaves and returns a fresh object with no stamp, which is the rule: it was
#   not cast, so it was not kicked);
# * by the cast announcement, for "whenever a player kicks a spell".
#
# and it reads the same key the rewrite produced, so the offer that is charged
# is exactly the offer that makes the spell kicked.

#: The permanent-metadata key a kicked permanent spell leaves on the permanent
#: it becomes. Present and true, or absent.
KICKED = "kicked"

#: ...and **which** kicker costs paid for it: a tuple of canonical keys
#: (:func:`kickers_paid`), stamped beside :data:`KICKED` and present exactly
#: when that is. "When this creature enters, if it was kicked **with its {1}{G}
#: kicker**, ..." (the Battlemages, CR 702.33f) is asked of the permanent after
#: the stack item is gone, so the answer has to have travelled with it.
#:
#: A second key rather than a richer value under the first, so every reader
#: that asks only "was it kicked?" -- the entry replacement, Skizzik's end
#: step -- keeps the truth test it has. And CR 400.7 for both alike: a
#: permanent that leaves and returns is a new object with neither, and one
#: nothing cast (a reanimation, a token copy, a Clone that *entered as* a
#: Battlemage -- cast as a Clone, which prints no kicker) was never stamped.
KICKED_WITH = "kicked_with"

#: The permanent-metadata key holding the mana value of the card a permanent
#: spell's **cost** discarded, for the entry replacement that is sized by it:
#: "…it enters with flying and with X +1/+1 counters on it, where X is the
#: discarded card's mana value." (Dralnu's Pet, whose kicker is "{2}{B},
#: Discard a creature card".)
#:
#: Beside :data:`KICKED` and stamped at the same place for the same reason
#: (``resolution._resolve_card``): the cost was paid at CR 601.2h, the card it
#: took is in a graveyard and a different object by resolution (CR 400.7), and
#: the permanent that asks is a new object too — so the number rides the stack
#: item's ``discarded_for_cost`` record onto the permanent before it enters,
#: where CR 614.1c's entry replacement reads it. A **number** rather than the
#: card: a mana value is read off the card as printed (CR 202.3), nothing can
#: change it afterwards, and permanent metadata is plain data everywhere else.
#:
#: Stamped only when the cost took exactly one card, which is the only number
#: "the discarded card" can mean; absent otherwise, and absent on a permanent
#: nothing cast.
CAST_COST_DISCARD_MANA_VALUE = "cast_cost_discard_mana_value"

#: "Kicker {2}", "Kicker {1}{G}", "Kicker {X}{2}". One run of mana symbols.
#:
#: "Kicker {1}{G} and/or {2}{U}" (Planeshift's two-kicker cards) is
#: :data:`_KICKER_PAIR_LINE` below, its own pattern and its own reader
#: (:func:`_kicker_line_offers`): this one stays the single cost it has always
#: been, so a reader that asks for *the* kicker of a one-kicker card is
#: unchanged.
_KICKER_LINE = re.compile(
    r"^kicker\s+(?P<cost>(?:\{[^{}]+\})+)$", re.IGNORECASE
)

#: "Kicker **{1}{G} and/or {2}{U}**" (the five Battlemages). CR 702.33b: "The
#: phrase 'Kicker [cost 1] and/or [cost 2]' means the same thing as 'Kicker
#: [cost 1], kicker [cost 2].'" -- two kicker abilities on one card, each an
#: optional additional cost of its own, either or both of which the caster may
#: announce (CR 601.2b).
#:
#: It was refused on purpose until the *question* existed. The cost half was
#: never the difficulty -- "and/or" is already two independent offers to
#: ``_optional_mana_offers`` -- but every card printing the pair also prints
#: "if it was kicked **with its {1}{G} kicker**" (CR 702.33f: a linked ability
#: that refers to one specific kicker cost), and a cost admitted without that
#: answer is a wording claimed and never exercised. :func:`kicked_with` is the
#: answer and :data:`KICKED_WITH` is where a permanent keeps it.
#:
#: Exactly two runs. CR 702.33b names two, every printing has two, and a third
#: would be a sentence nobody has read.
_KICKER_PAIR_LINE = re.compile(
    r"^kicker\s+(?P<first>(?:\{[^{}]+\})+)\s+and/or\s+"
    r"(?P<second>(?:\{[^{}]+\})+)$",
    re.IGNORECASE,
)

#: Any line that *is* a kicker keyword line, readable or not -- the wider shape
#: the support gate asks, for ``_BUYBACK_SHAPE``'s reason: a kicker whose cost
#: this file cannot read must be reported as a cost nothing charges, never fall
#: through to a gate that has not heard of the keyword and cast the spell
#: unkickable. What follows the word has to open a cost (a mana symbol, or the
#: em dash a non-mana cost is printed behind), which is what keeps "Kicker costs
#: cost {1} less" -- a static ability *about* kicker -- out of it.
_KICKER_SHAPE = re.compile(r"^(?:multi)?kicker\s*(?:[—–-]|\{)", re.IGNORECASE)

#: "**Kicker—Sacrifice a land.**" (Falling Timber, and eight more Planeshift
#: cards.) CR 702.33a's cost is any cost, not a run of mana symbols, and the
#: printed form for a non-mana one puts it behind an em dash rather than a
#: space -- ``_BUYBACK_COST_LINE``'s shape with the other keyword in front, and
#: read by the same function (:func:`_optional_cost_phrase_offer`).
#:
#: Its own pattern beside :data:`_KICKER_LINE` rather than a widening of it:
#: that one is a run of mana symbols the cast folds into its mana payment, this
#: one is a price ``_pay_additional_costs`` collects, and the announcement key
#: of each is read back off a different field of the cost it produces.
_KICKER_COST_LINE = re.compile(
    r"^kicker\s*[—–-]\s*(?P<cost>.+)$", re.IGNORECASE
)


def _kicker_line_offer(line: str) -> tuple[str, str] | None:
    """``(announcement key, rules sentence)`` for one kicker line, or None.

    The key is the canonical spelling ``_optional_mana_offers`` gives the
    rewritten sentence -- read **back off the sentence** rather than spelled a
    second time here, for ``_buyback_line_offer``'s reason: the key is what the
    announcement is recorded under and what :func:`kicked` reads it back by,
    and two spellings of one cost is a spell that paid its kicker and resolved
    unkicked.
    """
    stripped = " ".join(_BUYBACK_REMINDER.sub("", line or "").split())
    stripped = stripped.strip().rstrip(".")
    match = _KICKER_LINE.match(stripped)
    if match is None:
        return _kicker_cost_line_offer(stripped)
    read = _printed_additional_cost(
        BUYBACK_RULES_TEXT.format(cost=match.group("cost"))
    )
    if read is None or len(read.optional_mana) != 1:
        return None
    key = read.optional_mana[0].symbols
    return key, BUYBACK_RULES_TEXT.format(cost=key)


def _kicker_line_offers(line: str) -> tuple[tuple[str, ...], str] | None:
    """``(announcement keys, rules sentence)`` for one kicker line, or None.

    The plural of :func:`_kicker_line_offer`, and the function every reader of
    "which offers are this card's kickers?" asks -- because CR 702.33b lets one
    line print two ("Kicker {1}{G} and/or {2}{U}") and a reader that knew one
    key would call a Battlemage kicked with its second cost unkicked.

    A line that function reads is answered through it, as a one-key tuple, so
    whatever cost shapes it grows are kicker costs here with no edit. What this
    adds is the pair: the two runs go to the cost table as **one** sentence --
    "you may pay {1}{G} and/or {2}{U}", which ``_optional_mana_offers`` already
    reads as two independent offers -- and both keys are read back off the
    :class:`AdditionalCost` that sentence produces, for
    ``_buyback_line_offer``'s reason: the key is what the announcement is
    recorded under and what :func:`kicked_with` reads it back by.

    Refused (None, so :func:`unread_cost_sentence` reports the card) when the
    sentence does not come back as exactly two offers -- two runs spelling one
    cost would share a key, and "which kicker" would have no answer -- or when
    either prints an {X}: the announcement carries one X and two offers would
    each want their own.
    """
    single = _kicker_line_offer(line)
    if single is not None:
        return (single[0],), single[1]
    stripped = " ".join(_BUYBACK_REMINDER.sub("", line or "").split())
    stripped = stripped.strip().rstrip(".")
    match = _KICKER_PAIR_LINE.match(stripped)
    if match is None:
        return None
    read = _printed_additional_cost(BUYBACK_RULES_TEXT.format(
        cost=f"{match.group('first')} and/or {match.group('second')}"
    ))
    if read is None or len(read.optional_mana) != 2 or read.optional_key:
        return None
    if any(offer.x_count or offer.repeatable for offer in read.optional_mana):
        return None
    keys = tuple(offer.symbols for offer in read.optional_mana)
    return keys, BUYBACK_RULES_TEXT.format(cost=" and/or ".join(keys))


def _kicker_cost_line_offer(stripped: str) -> tuple[str, str] | None:
    """``(announcement key, rules sentence)`` for a kicker line whose cost is
    **not mana** ("Kicker—Sacrifice a land."), or None.

    *stripped* is the line with its reminder text and full stop already off,
    which is how :func:`_kicker_line_offer` hands it over. The key is the
    ``optional_key`` of the :class:`AdditionalCost` the rewritten sentence
    produces -- the string ``_optional_cost_announcement`` accepts the
    announcement under, ``optional_cost_taken`` charges by and :func:`kicked`
    reads back, all three off the one object, so a kicker that was paid cannot
    resolve unkicked for want of a spelling.
    """
    match = _KICKER_COST_LINE.match(stripped)
    if match is None:
        return None
    return _optional_cost_phrase_offer(match.group("cost"))


def is_kicker_line(line: str) -> bool:
    """Whether *line* is a printed kicker keyword line, readable or not."""
    stripped = _BUYBACK_REMINDER.sub("", line or "").strip()
    return _KICKER_SHAPE.match(stripped) is not None


def expand_kicker_line(line: str) -> str | None:
    """The CR 702.33a rules text for one printed kicker line, or None.

    Through :func:`_kicker_line_offers`, so a line printing two kicker costs
    (CR 702.33b) becomes the one sentence that offers both."""
    offers = _kicker_line_offers(line)
    return None if offers is None else offers[1]


def expand_kicker_lines(oracle_text: str) -> str:
    """*oracle_text* with every kicker keyword line rewritten to its rules text.

    Text without one is returned unchanged, so applying this to every card costs
    a substring test. Applied by the compiler before any line is classified,
    beside ``expand_buyback_lines`` and for its reason: what the compiler reads
    and what every other reader of a card's lines reads must be one text.
    """
    if not oracle_text or "icker" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_kicker_line(line) or line for line in oracle_text.split("\n")
    )


@lru_cache(maxsize=None)
def kicker_costs(oracle_text: str) -> tuple[str, ...]:
    """Every canonical key *oracle_text*'s kicker keyword offers, in printed
    order -- empty for a card printing no kicker.

    **The one answer to "which of this card's offers are its kickers?"**, and a
    tuple because CR 702.33b lets a card print two ("Kicker {1}{G} and/or
    {2}{U}"). Every reader of that question -- :func:`kicked`,
    :func:`kicked_with`, the cast picker's CR 702.33g view, the offer prompt's
    label -- asks this, so a second kicker cost is a second key here rather
    than a second code path in each of them.

    A key is whatever the announcement is recorded under: ``mana_cost_label``'s
    spelling for a mana cost, and whatever :func:`_kicker_line_offer` returns
    for any other shape it reads. Nothing here assumes mana.

    Read off the **printed** text, which is what a resolving spell's
    ``CardDefinition`` still carries -- the rewrite happens inside the compiler
    and nothing writes it back onto the card. Cached because it is asked of
    every spell that is cast and every one that resolves.
    """
    if "icker" not in (oracle_text or ""):
        return ()
    keys: list[str] = []
    for line in oracle_text.split("\n"):
        offers = _kicker_line_offers(line)
        if offers is None:
            continue
        keys.extend(key for key in offers[0] if key not in keys)
    return tuple(keys)


def kicker_cost(oracle_text: str) -> str | None:
    """The canonical key of *oracle_text*'s **first** kicker cost, or None.

    The singular, for a caller that wants one key to announce (a test kicking a
    card, a label). "Was it kicked?" is never this function's question: a card
    may print two kicker costs (CR 702.33b) and paying only the second kicks
    the spell, so every reader of the *answer* goes through :func:`kicked` /
    :func:`kicked_with` / :func:`kicker_costs`.
    """
    keys = kicker_costs(oracle_text or "")
    return keys[0] if keys else None


def kickers_paid(card: CardDefinition, choices: dict | None) -> tuple[str, ...]:
    """The kicker costs of *card* this cast paid, by key, in printed order
    (CR 702.33d: "If a spell's controller declares the intention to pay
    **any** of that spell's kicker costs, that spell has been 'kicked.'").

    *choices* is the spell's own stack record, where the announcement survives
    (the pool that paid is empty by resolution, CR 500.5). Empty for a card
    printing no kicker and for an object nothing cast, which has no ``choices``
    to read.

    The one reader of the record: :func:`kicked` is "is this non-empty?",
    :func:`kicked_with` is "is this key in it?", and
    ``resolution._resolve_card`` copies it onto the permanent
    (:data:`KICKED_WITH`) for the sentences asked after the stack item is gone.
    """
    keys = kicker_costs(getattr(card, "oracle_text", "") or "")
    if not keys:
        return ()
    paid = (choices or {}).get("additional_costs_paid") or {}
    taken: list[str] = []
    for key in keys:
        try:
            if int(paid.get(key, 0) or 0) > 0:
                taken.append(key)
        except (TypeError, ValueError):
            continue
    return tuple(taken)


def kicked(card: CardDefinition, choices: dict | None) -> bool:
    """Whether this cast of *card* was kicked (CR 702.33d).

    *choices* is the spell's own stack record. CR 702.33d settles the answer at
    the announcement ("declares the intention to pay **any** of that spell's
    kicker costs"), and ``choices`` is where the announcement survives: the
    pool that paid is empty by resolution (CR 500.5).

    Any of them: a Battlemage that paid only its second kicker is a kicked
    spell to Ertai's Trickery and to "whenever a player kicks a spell".

    False for a card printing no kicker and for an object nothing cast, which
    has no ``choices`` to read.
    """
    return bool(kickers_paid(card, choices))


def kicked_with(card: CardDefinition, choices: dict | None, key: str) -> bool:
    """Whether this cast of *card* paid the kicker cost *key* (CR 702.33f:
    an ability reading "if it was kicked with its [A] kicker" corresponds to
    one specific kicker cost and "is linked to the appropriate kicker
    ability").

    *key* is the canonical spelling the offer is recorded under -- what
    ``lowering/_cost_records.optional_cost_key`` makes of the printed symbols,
    so the sentence that asks and the payment that answers name one string.

    False when *card* prints no kicker of that cost, **whatever the record
    says**: an unrelated optional cost that happens to share the symbols
    (a "you may pay {1}{G}" beside a different kicker) was not a kicker
    payment, and CR 702.33f's reference is to the kicker alone.
    """
    return key in kickers_paid(card, choices)


#: "…if it was kicked **with its {1}{G} kicker**" -- the printed cost a linked
#: ability names (CR 702.33f), wherever on the card it sits.
_NAMED_KICKER_QUESTION = re.compile(
    r"kicked with its (?P<cost>(?:\{[^{}]+\})+) kicker", re.IGNORECASE
)


def unlinked_kicker_question(oracle_text: str) -> str | None:
    """The first cost a "kicked with its [A] kicker" sentence of *oracle_text*
    names that the card's own kicker line does not offer, as printed -- or
    None, which is every card but a malformed one.

    CR 702.33f: such an ability "is linked to the appropriate kicker ability",
    where A and B are "the first and second kicker costs listed on the card".
    So the cost in the question has to be one of :func:`kicker_costs` -- the
    keys a payment is recorded under -- and a sentence naming any other is a
    condition no cast can ever make true. The sentence itself parses and
    lowers happily (its key is simply never written), so the card would report
    supported with a trigger that never fires; asked by the support gate in
    ``engine/oracle.py`` of the **printed** text, beside the uncharged-cost
    gate and for its reason, it is refused instead.

    Compared as canonical keys, through the two functions the offer was
    spelled with, so "{U}{1}" asked of a "Kicker {1}{U}" is the same cost. A
    run no payment can spend ({X}, a hybrid) has no key and is unlinked.
    """
    if "kicked with its" not in (oracle_text or "").lower():
        return None
    from .mana_payment import mana_cost_from_symbols, mana_cost_label

    offered = kicker_costs(oracle_text)
    for match in _NAMED_KICKER_QUESTION.finditer(oracle_text):
        symbols = mana_cost_from_symbols(match.group("cost"))
        if not symbols or mana_cost_label(symbols) not in offered:
            return match.group("cost")
    return None


@compilation_cache
@lru_cache(maxsize=None)
def _additional_costs_of_text(
    oracle_text: str, card_name: str, legendary: bool
) -> tuple[AdditionalCost, ...]:
    """:func:`additional_costs` keyed on what it actually reads.

    Cached because it is asked of every card in every hand on every poll
    (``legality.cast_cost_offers``) and now runs the whole rewrite pass to
    answer — and because the answer is a pure function of exactly the three
    arguments ``expand_ability_lines`` takes.

    ``@compilation_cache`` because that pass *is* part of the compiler: a caller
    that stubs the grammar out and puts it back leaves this holding whatever the
    stub said otherwise, which is the shape ``clear_compilation_caches`` exists
    for.
    """
    from .line_rewrites import expand_ability_lines

    lines = expand_ability_lines(
        oracle_text or "", card_name=card_name or None, legendary=legendary
    ).splitlines()
    costs = tuple(
        cost
        for line in lines
        if (cost := additional_cost_for_line(line)) is not None
    )
    if any(x_one_of_each_color_line(line) for line in lines):
        # "Spend only colored mana on X. No more than one mana of each color
        # may be spent this way." A line of its own that restricts an X printed
        # on another, so it is folded onto the offer here -- the one place
        # every reader of this card's costs starts from.
        costs = tuple(_with_restricted_x(cost) for cost in costs)
    return costs


#: "**Spend only colored mana on X. No more than one mana of each color may be
#: spent this way.**" (Emblazoned Golem.) The whole line, both sentences: the
#: second is not a second restriction but the half of the first that makes it
#: one -- "only colored mana" alone is Drain Life's shape with every colour
#: admitted, and it is the cap of one per colour that sizes X. So the pair is
#: read together and a line carrying either alone refuses, for the reason
#: ``mana_spending.mana_spending_for`` reads Celestial Dawn's pair together: a
#: restriction half-read is a cost paid more easily than the card allows.
_X_ONE_OF_EACH_COLOR_SENTENCES = (
    "spend only colored mana on x",
    "no more than one mana of each color may be spent this way",
)
_X_ONE_OF_EACH_COLOR_LINE = re.compile(
    "^" + r"\. ".join(re.escape(part) for part in _X_ONE_OF_EACH_COLOR_SENTENCES) + "$"
)


def x_one_of_each_color_sentence(sentence: str) -> bool:
    """Whether *sentence* is one of the two the restriction is printed as.

    For ``scripts/parse_coverage.py`` alone, whose table is asked one sentence
    at a time (the arrangement ``draw_step_modifiers.draw_step_skip_line`` has
    for Fasting's pair). Nothing *enforces* off this: the pair is read together
    by :func:`x_one_of_each_color_line` below, and a card printing only one of
    them is refused by the support gate before coverage is ever asked.
    """
    normalized = " ".join((sentence or "").strip().lower().split()).rstrip(".")
    return normalized in _X_ONE_OF_EACH_COLOR_SENTENCES


def x_one_of_each_color_line(line: str) -> bool:
    """Whether *line* is, in full, the "one mana of each color on X" restriction.

    Asked by :func:`_additional_costs_of_text`, which enforces it by marking
    the offer, by :func:`cast_cost_claims_line`, which claims it, and by
    :func:`unenforced_x_spend_restriction`, which refuses a card that prints it
    over no X this table charges -- one matcher, so what is claimed and what is
    charged cannot drift.
    """
    normalized = " ".join((line or "").strip().lower().split()).rstrip(".")
    return _X_ONE_OF_EACH_COLOR_LINE.match(normalized) is not None


def _with_restricted_x(cost: AdditionalCost) -> AdditionalCost:
    """*cost* with every offer that prints an {X} marked as payable only with
    one mana of each of X colours. An offer with no X is untouched: the
    sentence is about X and says nothing of a kicker that has none."""
    import dataclasses

    if not any(offer.x_count for offer in cost.optional_mana):
        return cost
    return dataclasses.replace(
        cost,
        optional_mana=tuple(
            dataclasses.replace(offer, x_one_of_each_color=True)
            if offer.x_count else offer
            for offer in cost.optional_mana
        ),
    )


def unenforced_x_spend_restriction(
    oracle_text: str, card_name: str | None = None, legendary: bool = False
) -> str | None:
    """The "one mana of each color on X" line of *oracle_text* when **nothing
    enforces it**, else None.

    The restriction is enforced as a property of an optional X offer
    (``OptionalManaCost.x_one_of_each_color``), which is the only place a card
    in this pool prints it over. A card printing the sentence over any other X
    -- one in its mana cost, or in "pay X life" -- would have the line claimed
    by :func:`cast_cost_claims_line` and charged by nobody: the restriction
    dropped in silence and in the caster's favour. Asked by the support gate in
    ``engine/oracle.py`` beside the uncharged-cost gate, and refused there.
    """
    printed = next(
        (line for line in (oracle_text or "").splitlines()
         if x_one_of_each_color_line(line)),
        None,
    )
    if printed is None:
        return None
    costs = _additional_costs_of_text(oracle_text or "", card_name or "", legendary)
    if any(
        offer.x_one_of_each_color
        for cost in costs
        for offer in cost.optional_mana
    ):
        return None
    return printed.strip()


#: "…, where X is **the chosen number**" — the trailer
#: ``grammar/where_x.parse_where_x_definition_body`` reads into
#: ``ast.ChosenNumberAsCast``. Matched here on the words, as
#: :func:`unlinked_kicker_question` matches its own: the question is which
#: *lines of one card* go together, and a compiled line no longer knows its
#: neighbours.
_CHOSEN_NUMBER_DEFINITION = re.compile(r"\bwhere x is the chosen number\b")


def unchosen_number_definition(
    oracle_text: str, card_name: str | None = None, legendary: bool = False,
    *, spell: bool = True,
) -> str | None:
    """The "where X is the chosen number" line of *oracle_text* when **no cast
    of this card chooses one**, else None.

    The words lower to the cast's own X (``ast.ChosenNumberAsCast``), which is
    the right number exactly when the card also prints "As an additional cost
    to cast this spell, choose a number between …" — CR 601.2b makes that
    choice the announcement of X. Printed without the cost, the sentence would
    compile and spend an X nobody announced: zero on every cast, on a card
    reporting itself supported. And on a permanent the X of an ability is not
    the X its spell was cast with (CR 107.3i's exceptions aside), so *spell*
    False refuses the line outright.

    The uncharged cost's mirror: that gate refuses a price nothing collects,
    and this one a number nothing chooses. Asked by the support gate in
    ``engine/oracle.py`` beside it.
    """
    printed = next(
        (
            line for line in (oracle_text or "").splitlines()
            if _CHOSEN_NUMBER_DEFINITION.search(" ".join(line.lower().split()))
        ),
        None,
    )
    if printed is None:
        return None
    costs = _additional_costs_of_text(oracle_text or "", card_name or "", legendary)
    if spell and any(
        cost.choose_number is not None and cost.from_zone is None
        for cost in costs
    ):
        return None
    return printed.strip()


def additional_costs(card: CardDefinition) -> tuple[AdditionalCost, ...]:
    """Every additional cost *card* prints, in printed order.

    Read off ``expand_ability_lines``'s text rather than off ``oracle_text``,
    which is CLAUDE.md's rule that every reader of a card's lines starts from
    that function — and this file is one of the readers it names. Buyback
    (CR 702.27a) is *defined* as one of these costs and reaches this table only
    as the rewrite's sentence, so a reader that split the printed text would see
    a buyback card with no additional cost at all and charge nothing: this
    module's own failure, one rewrite later.
    """
    return _additional_costs_of_text(
        card.oracle_text or "",
        getattr(card, "name", "") or "",
        bool(getattr(card, "is_legendary", False)),
    )


def costs_charged_from(
    card: CardDefinition, from_zone: str
) -> tuple[AdditionalCost, ...]:
    """The additional costs *card* is charged for a cast leaving *from_zone*.

    The zone test ``queue_from_hand`` and ``targeting._cast_cost_picker`` both
    make, written once: a cost naming a zone is a price for casting from *that*
    zone (Demonic Embrace's graveyard price), so a reader that took the card
    alone would describe a cast nobody is being charged for.
    """
    return tuple(
        cost
        for cost in additional_costs(card)
        if cost.from_zone is None or cost.from_zone == from_zone
    )


def cast_announces_x(
    card: CardDefinition, *, from_zone: str = "hand",
    taken: dict[str, int] | None = None,
) -> bool:
    """Whether casting *card* from *from_zone* makes its controller announce a
    value for X (CR 107.3a).

    **The whole of CR 107.3a's list, which is the point.** The rule reads "a
    mana cost, alternative cost, additional cost, and/or activation cost with an
    {X}, [-X], or X in it" -- four places, of which ``web/static/app.js`` asked
    only the first, as a substring probe of the printed mana-cost string. Fire
    Covenant's is ``{1}{B}{R}`` and Infernal Harvest's is ``{1}{B}``: neither
    prints an {X} anywhere, because both spell their X in an *additional* cost
    ("pay X life", "return X Swamps you control to their owner's hand"). So the
    browser offered no X box, the cast took the 0 an unmade CR 107.3a
    announcement reads as here, and two spells that are entirely about X
    resolved doing nothing at all -- legal,
    since 0 is a choice, and useless.

    Here rather than beside either reader for the reason
    ``oracle_types.cost_target_count`` gives one module over: the picker is a
    *third* reader of a question the gate and the payment already ask
    (``AdditionalCost.life_charged`` / ``returned_count`` are the other two), and
    the direction a third copy drifts in is a price the player is never asked
    for. A cost field that later spells X is added to this one function and every
    reader gains it.

    The alternative-cost arm of the rule (CR 118.9) has one card behind it since
    Torment -- Flaming Gambit's "Flashback {X}{R}{R}" -- and the first line
    below already answers it, because that card's mana cost prints {X} too. A
    flashback {X} over a mana cost with none is refused by the support gate
    (``flashback.flashback_x_unannounced``), so the arm that would answer it is
    still named here and not written: a dead arm is a claim nothing tests.
    """
    if "{X}" in (card.mana_cost or "").upper():
        return True
    charged = costs_charged_from(card, from_zone)
    if any(
        cost.pay_life_x or cost.return_count_x or cost.exile_graveyard_count_x
        or cost.discard_count_x
        # "…, choose a number between 0 and 5" (Liquid Fire): CR 601.2b's
        # variable "defined in the text of the spell by a choice" — the chosen
        # number is the X the card's other line spends.
        or cost.choose_number is not None
        for cost in charged
    ):
        return True
    # "Kicker {X}" (Verdeloth the Ancient). An X that lives in an *offer*, so
    # whether it is announced at all turns on CR 601.2b's other answer: a caster
    # who declined the kicker names no number, and a box asking for one would be
    # asking about a cost nobody is paying. *taken* is that answer so far --
    # ``optional_cost_payments``, the map the offer prompt re-asks the spec
    # with -- and with none of it given the answer is no.
    return any(
        offer.x_count and int((taken or {}).get(offer.symbols, 0) or 0) > 0
        for cost in charged
        for offer in cost.optional_mana
    )


def optional_x_offers(
    card: CardDefinition, *, from_zone: str = "hand"
) -> tuple[OptionalManaCost, ...]:
    """Every CR 601.2b offer of *card* that prints an {X} ("Kicker {X}").

    Empty for every card but two in the pool, which is what lets the cast path
    ask it of every spell and change nothing for the rest.
    """
    return tuple(
        offer
        for cost in costs_charged_from(card, from_zone)
        for offer in cost.optional_mana
        if offer.x_count
    )


def unread_cost_sentence(line: str) -> str | None:
    """*line* if it announces a cost of this table's kind that it cannot
    charge, else None.

    The **table's own** answer to "is this my sentence?", asked by the support
    gate in ``engine/oracle.py``. Not a second reader: the preambles are the
    ones :func:`additional_cost_for_line` matches with, and the refusal is that
    function's own — this only distinguishes "no cost here" from "a cost here I
    refused", which the boolean seam above collapses.

    That distinction is the whole of the gate. A card whose cost line nothing
    reads is not a card missing a feature: it is a card *cheaper than it
    prints*, and because a card is supported when **any** of its lines is, it
    reports supported and casts at its printed mana cost with the extra price
    skipped. Kaervek's Spite sacrificed nothing and Infernal Harvest returned
    no Swamp, both green in every instrument except this one. The gate makes it
    loud, which is the standing invariant: a card may fail as unsupported; it
    may never resolve as something other than what it says.
    """
    normalized = line.strip().lower().rstrip(".")
    for preamble in (_ADDITIONAL_COST_PREAMBLE, _SELF_PERMISSION_COSTS):
        match = preamble.match(normalized)
        if match is not None and _read_cost_clauses(match.group("costs")) is None:
            return match.group(0)
    # A buyback line the rewrite could not read (CR 702.27a). This is asked of
    # the compiler's *expanded* text, where a readable one has already become
    # the sentence above — so what survives here is a printing
    # :func:`expand_buyback_line` refused, and refusing the card is the only
    # honest answer: the alternative is a spell cast at its printed mana cost
    # with an optional price nobody was offered and a hand-return nobody gets.
    if is_buyback_line(line) and expand_buyback_line(line) is None:
        # Spelled the way every other return here is — lowercased, reminder
        # text and the full stop off — because the caller quotes it back to the
        # reader as "printed cost nothing charges: …".
        stripped = " ".join(_BUYBACK_REMINDER.sub("", line or "").split())
        return stripped.strip().lower().rstrip(".")
    # A kicker line the rewrite could not read (CR 702.33a), for the buyback
    # line's reason one block up: what survives to here is a printing
    # :func:`expand_kicker_line` refused, and a card cast with its kicker never
    # offered is a card that can never be what half its text describes.
    if is_kicker_line(line) and expand_kicker_line(line) is None:
        stripped = " ".join(_BUYBACK_REMINDER.sub("", line or "").split())
        return stripped.strip().lower().rstrip(".")
    return None


def cast_cost_claims_line(line: str) -> bool:
    """Whether this table reads *line*.

    The support gate and the parse-coverage report both ask this, so what the
    engine implements and what it claims to have read cannot drift — the same
    seam ``enter_effects.enter_effect_line`` is.
    """
    return additional_cost_for_line(line) is not None or x_one_of_each_color_line(line)


__all__ = [
    "AdditionalCost",
    "OptionalManaCost",
    "BUYBACK_RULES_TEXT",
    "buyback_cost",
    "buyback_paid",
    "expand_buyback_line",
    "expand_buyback_lines",
    "is_buyback_line",
    "KICKED",
    "KICKED_WITH",
    "CAST_COST_DISCARD_MANA_VALUE",
    "expand_kicker_line",
    "expand_kicker_lines",
    "is_kicker_line",
    "kicked",
    "kicked_with",
    "kicker_cost",
    "kicker_costs",
    "kickers_paid",
    "optional_x_offers",
    "x_one_of_each_color_line",
    "x_one_of_each_color_sentence",
    "unenforced_x_spend_restriction",
    "unchosen_number_definition",
    "read_return_clause",
    "read_sacrifice_all_clause",
    "read_sacrifice_clause",
    "additional_cost_for_line",
    "additional_costs",
    "cast_announces_x",
    "cast_cost_claims_line",
    "costs_charged_from",
    "unlinked_kicker_question",
    "unread_cost_sentence",
]
