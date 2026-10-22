"""May this printed keyword line be admitted? (CR 702.)

The compiler's keyword-*line* classifier. :func:`_is_supported_keyword_line`
admits a line when every keyword it names is one the engine implements, read
off ``vocabulary.IMPLEMENTED_KEYWORDS`` rather than a list of its own (the
comment below says why that is one frozenset). A parameterised keyword is
admitted by the reader that *implements* it — protection's and hexproof's
qualities, rampage's number, cumulative upkeep's and madness's costs, "bands
with other", a quality-first landwalk — so a quality or a cost the engine
cannot carry out keeps the whole line refused, naming it.

:func:`keyword_line_triggers` is the other half: the keywords whose rules text
the CR defines as a triggered ability (rampage, cumulative upkeep, flanking,
madness), read here for both of the compiler's line loops. And
:func:`_protection_clause_modelled` is asked by the static-line gate
(``engine/static_line_support.py``) too, so "protection from ..." printed on a
line of its own and inside a keyword list is admitted by one reader.

Split out of ``engine/oracle.py`` at the 2,000-line cap.
"""

from __future__ import annotations

import re

from .oracle_types import ParsedTriggeredAbility, _COLOR_WORD_TO_SYMBOL
from .cumulative_upkeep import cumulative_upkeep_triggers
from .flanking import flanking_triggers
from .madness import madness_triggers
from .rampage import rampage_amount, rampage_triggers
from .grammar.vocabulary import IMPLEMENTED_KEYWORDS
from .line_normalization import normalize_creature_line


# The keyword registry lives in `engine/grammar/vocabulary.py` and this module
# reads it. It used to be spelled out in the compiler as well — seventeen Title Case
# strings beside seventeen lowercase ones, held equal by hand, compared by
# nothing. The two gate different halves of the same question (this one admits a
# printed keyword *line*; the grammar's refuses to *lower* an unimplemented
# keyword), so a keyword added to one and not the other produces a card that is
# either admitted and inert or refused for a behaviour that exists — and a new
# set is a keyword-adding event by definition.
#
# This is the rule the comment on `_is_supported_static_creature_line` already
# states for lord buffs and combat restrictions: the gate and the dispatch must
# read the SAME table. Held by `tests/engine/test_keyword_registry.py`, which
# checks the gate's *behaviour* against the registry rather than comparing two
# lists — comparing them is something a future second copy would also pass.
# Keyword *mechanics* the engine does not model at all, named as the ingested
# `keywords` field spells them. This is not the negation of the registry above —
# "Enchant", "Regenerate" and "Landwalk" are Scryfall keyword tags whose
# behaviour lives elsewhere (`engine/auras.py`, the regeneration handler, the
# evasion table), so deriving this set from `KEYWORD_ABILITIES -
# IMPLEMENTED_KEYWORDS` would refuse every Aura in the pool.
#
# It is a *third* place a keyword's name can appear, and the one that fails
# silently in the expensive direction: an entry here outranks every line gate,
# so a keyword implemented in full still costs its cards their support until
# the word is deleted from this set. Rampage sat here through the whole of
# round 1's implementation and the seven Legends cards stayed unsupported with
# the behaviour built and tested. `tests/engine/test_keyword_registry.py`
# compiles a card carrying each implemented keyword *in its ingested field* for
# exactly that reason.
#
# **Empty since Mirage**, when phasing — its last entry — was implemented
# (CR 702.26, `Game.resolve_phasing_for`). Empty is the state to prefer: a
# keyword the engine does not model refuses at the line gate anyway, naming the
# clause, and this set is the only refusal that names nothing. Adding a word
# here again is a decision to refuse a card *before* reading it, and it needs
# the reason written down beside the word.
UNSUPPORTED_KEYWORDS: set[str] = set()


# ---------------------------------------------------------------------------
# Admitting a keyword line
# ---------------------------------------------------------------------------

def _is_supported_keyword_line(line: str) -> bool:
    """Whether a printed keyword line names only keywords the engine implements.

    Reads `IMPLEMENTED_KEYWORDS` rather than a local copy: what may be *admitted*
    here and what the grammar will *lower* are the same claim, and two lists
    agreeing by hand is the arrangement this codebase keeps finding bugs in.
    """
    normalized = normalize_creature_line(line)
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if not parts:
        return False
    # The two parameterised keywords are admitted by prefix plus quality:
    # "protection from white and from blue" and "hexproof from blue" carry the
    # quality as payload, not as part of the keyword's identity. What may be
    # admitted is exactly what the shield machinery models — colours for both,
    # and for protection also "multicolored", "planeswalkers" and creature
    # subtypes ("Demons and from Dragons", Baneslayer Angel), the qualities
    # ``_protection_qualities`` reads. A quality it does not model keeps the
    # whole line refused with the clause named, because admitting the word
    # would ship the card and silently drop the shield.
    return all(
        part in IMPLEMENTED_KEYWORDS or _qualified_keyword_part(part)
        for part in parts
    )


def _protection_quality_word(word: str) -> bool:
    """Whether one word of a protection clause names a quality the shield models.

    **Delegates**, and that is the whole of it. This was a hand-written copy of
    ``keywords.protection_quality`` — colour, "multicolored", the literal pair
    "planeswalker"/"planeswalkers", then the creature-type catalog — and the two
    drifted the way this codebase's docstrings keep predicting: the copy's card
    types were a list of the ones somebody had met, so "artifacts" was a quality
    the *runtime* could answer (``_permanent_has_quality`` asks ``has_type``) and
    the *gate* refused. Angelic Curator was the card that refused, with every one
    of its lines grammar-clean.

    One reader, so what is admitted here and what a shield answers to cannot come
    apart again.
    """
    from .keywords import protection_qualities_named

    # The shorthand reader (CR 702.16h/i), which answers every single-quality
    # word exactly as ``protection_quality`` does and additionally reads the
    # members that stand for several abilities — "each color" (Iridescent
    # Angel). It is the function ``_protection_qualities`` builds a
    # permanent's qualities with, so the delegation above is unchanged: one
    # reader, one vocabulary.
    return protection_qualities_named(word) is not None


def _protection_clause_modelled(clause: str) -> bool:
    """Whether every quality *clause* names is one the shield models.

    CR 702.16g/h: "protection from Demons **and from** Dragons" is shorthand for
    two protection abilities, so the clause is split exactly the way
    ``protection._protection_qualities`` splits it when it *builds* them.
    Two spellings of that split is how a gate and a runtime come to read
    different sentences out of one printed line.

    Empty is False, not vacuously True: "protection from" with nothing behind it
    names no quality, and admitting it would be the blanket prefix this replaced.
    """
    qualities = [
        word.strip()
        for word in re.split(r",|\band from\b|\band\b", clause)
        if word.strip()
    ]
    return bool(qualities) and all(_protection_quality_word(q) for q in qualities)


def _qualified_keyword_part(part: str) -> bool:
    # Rampage carries a number rather than a quality (CR 702.23a: "Rampage N"),
    # and the number is the whole of it — so the reader that *implements* it is
    # the one that admits it, exactly as the protection arm below admits only
    # the qualities `_protection_qualities` models.
    if rampage_amount(part) is not None:
        return True
    # Cumulative upkeep carries a cost rather than a quality (CR 702.24a), and
    # the cost is the whole of it. Same rule as rampage one line up: the reader
    # that *implements* the keyword admits it, so a cost `engine/
    # cumulative_upkeep.py` cannot charge keeps the line refused instead of
    # shipping a permanent whose upkeep is silently free.
    from .cumulative_upkeep import cumulative_upkeep_cost

    if cumulative_upkeep_cost(part) is not None:
        return True
    # Madness carries a cost too (CR 702.35a), and is admitted the same way:
    # by the reader that charges it (`engine/madness.py`), so a cost it cannot
    # express — an {X}, a hybrid pip — keeps the line refused instead of
    # shipping a card whose discard is never replaced.
    from .madness import madness_cost_text

    if madness_cost_text(part) is not None:
        return True
    # "Bands with other legendary creatures" (CR 702.22b). The quality is a
    # printed noun phrase rather than a word from a list, so what admits the
    # line is the reader that *implements* it — engine/banding.py, which turns
    # the phrase into the filter payload the combat sites test. A quality the
    # noun parser cannot read, or one carrying a restriction the matcher cannot
    # answer, keeps the line refused: a band whose quality is dropped is a band
    # any creature may join.
    from .banding import is_bands_with_other, is_implemented as _band_implemented

    if is_bands_with_other(part):
        return _band_implemented(part)
    # "Legendary landwalk" (CR 702.14a's quality-first shape). Same reasoning
    # again: the ability's name is built from the printed quality, so no word
    # list can hold it — what admits the line is `engine/landwalk.py`, the
    # reader the declare-blockers step *enforces* it with. A quality that
    # reader cannot test keeps the line refused, because admitting the word
    # would ship a creature whose evasion silently never applies.
    from .landwalk import is_landwalk

    if is_landwalk(part):
        return True
    # Both clauses split the same way (CR 702.16g's shorthand), and the split
    # lives in :func:`_protection_clause_modelled` — the one the static-line gate
    # asks too, so the comma-joined spelling and the standalone one cannot admit
    # different sentences.
    if part.startswith("protection from "):
        return _protection_clause_modelled(part[len("protection from "):])
    # Hexproof stays colour-only: _can_be_targeted's hexproof branch reads
    # colour words alone.
    if part.startswith("hexproof from "):
        qualities = [
            q.strip()
            for q in re.split(r",|\band from\b|\band\b", part[len("hexproof from "):])
            if q.strip()
        ]
        return bool(qualities) and all(
            q in _COLOR_WORD_TO_SYMBOL for q in qualities
        )
    return False


def keyword_line_triggers(normalized_line: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered abilities a *keyword line* is, for every keyword whose
    rules text the CR defines as one.

    Three today — rampage (CR 702.23a), cumulative upkeep (CR 702.24a) and
    flanking (CR 702.25a) — and all are the rewrite ``engine/equipment.py``
    established for equip, one layer earlier because the grammar has no
    production for "for each creature blocking it beyond the first", for an
    escalating upkeep, or for a sentence no card outside a reminder prints.
    From here the ordinary dispatchers fire them: the becomes-blocked step and
    the upkeep step, neither of which knows the word.

    **One reader because there are two front ends.** A creature's lines and a
    non-creature permanent's are parsed by different loops, and cumulative
    upkeep was added to the creature loop alone: the six Ice Age enchantments
    that print it alongside another ability compiled *supported* with the
    keyword silently dropped, which is strictly worse than not implementing it
    — the card reads as done and plays as a better card than the one printed.
    A keyword rewrite belongs to a line rather than to a card type, so both
    loops ask here.
    """
    return (
        *rampage_triggers(normalized_line),
        *cumulative_upkeep_triggers(normalized_line),
        *flanking_triggers(normalized_line),
        # CR 702.35a's second ability ("When this card is exiled this way, its
        # owner may cast it by paying [cost] …"). Its static half is not an
        # ability this returns: it is a CR 614 replacement, read off the
        # printed line by `engine/replacements/zone_changes.py` (`engine/madness.py`).
        *madness_triggers(normalized_line),
    )
