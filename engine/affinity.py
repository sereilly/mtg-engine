"""Affinity (CR 702.41): a keyword the rules define as a cost reduction.

CR 702.41a: "Affinity is a static ability that functions while the spell with
affinity is on the stack. 'Affinity for [text]' means 'This spell costs {1}
less to cast for each [text] you control.'" So the keyword line is rewritten
into that sentence before any line is classified (``line_rewrites.
expand_ability_lines``, kicker's and flashback's arrangement), and from there it
is the self-reduction ``engine/self_cost_modifiers.py`` already reads, charges
and claims — Stratadon's "for each basic land type among lands you control" with
a different noun phrase. Nothing downstream knows the word: the cast path, the
castable highlight, the client's price (``cost_modifiers.cast_mana_charge``),
the AI's affordability read and the parse-coverage census all reach the same
sentence through ``cost_modifiers.cost_reduction_for_cast``.

The printed [text] is a plural noun phrase ("artifacts") and the rules sentence
counts one of them at a time ("for each artifact"), so the head noun is
singularized through the vocabulary's own reader (``vocabulary.singular``),
which trims only when the trimmed word is itself a known type. A noun it cannot
singularize, or a sentence the self-reduction reader then refuses, leaves the
keyword line exactly as printed — and :func:`unread_affinity_line` makes the
card unsupported naming it. That gate is what keeps an instant or sorcery
(whose *other* line compiles happily) from reporting supported with the keyword
dropped, which is precisely what Thoughtcast and Assert Authority did on the
day Mirrodin was ingested.

CR 702.41b ("If a spell has multiple instances of affinity, each of them
applies") is the self-reduction reader summing every line it reads
(``self_cost_modifiers.self_cost_reductions``), not anything here: two keyword
lines are two sentences.

The reminder text is not the rule (CR 207.2) and is never read: the rewritten
sentence is built from the keyword's own [text], so a printing whose reminder
disagreed with its keyword would still cost what CR 702.41a says.
"""

from __future__ import annotations

import re

#: "Affinity for artifacts (This spell costs {1} less to cast for each artifact
#: you control.)" — the keyword, its [text], and an optional parenthesised
#: reminder, alone on a line. Anchored at both ends: a keyword line is the
#: whole line (CR 702.1), and a sentence that merely *mentions* affinity
#: ("Creatures you control have affinity for …") is a grant this rewrite must
#: not read as the card's own keyword.
_AFFINITY_LINE = re.compile(
    r"^affinity for (?P<text>[^().,;:]+?)\s*(?:\([^()]*\))?\s*\.?$",
    re.IGNORECASE,
)


def _counted_phrase(text: str) -> str | None:
    """The singular noun phrase CR 702.41a's "for each [text]" counts, or None.

    Only the **head noun** (the last word) is singularized — "artifact
    creatures" counts one artifact creature at a time — and only through
    ``vocabulary.singular``, which trims a word only when what is left is a
    card type, a subtype or a generic noun. A head it leaves unchanged that is
    not itself such a word is a plural nothing here can read, and the rewrite
    declines rather than writing "for each artifacts".
    """
    from .grammar.vocabulary import (ALL_SUBTYPES, CARD_TYPES, GENERIC_NOUNS,
                                     singular)

    words = text.split()
    if not words:
        return None
    head = words[-1].lower()
    single = singular(head)
    if single == head and not (
        head in CARD_TYPES or head in ALL_SUBTYPES or head in GENERIC_NOUNS
    ):
        return None
    return " ".join([*words[:-1], single])


def affinity_sentence(line: str) -> str | None:
    """The rules sentence CR 702.41a says the affinity keyword *line* means,
    or None when *line* is not one or this cannot write it.

    "Affinity for artifacts (…)" -> "This spell costs {1} less to cast for each
    artifact you control." The sentence is returned only when the self-reduction
    reader applies it in full (``self_cost_modifiers.self_cost_reduction``), so
    a rewrite never produces text that would be claimed by nothing — the line
    stays as printed instead, and :func:`unread_affinity_line` names it.

    Uncached: the answer depends on the grammar's per-each reader, and the
    cache that holds that answer is the self-reduction reader's own
    (registered with ``clear_compilation_caches``) — a second cache here would
    keep a stubbed grammar's answer after the stub was gone.
    """
    match = _AFFINITY_LINE.match((line or "").strip())
    if match is None:
        return None
    counted = _counted_phrase(match.group("text").strip())
    if counted is None:
        return None
    sentence = f"This spell costs {{1}} less to cast for each {counted} you control."
    from .self_cost_modifiers import self_cost_reduction

    if self_cost_reduction(sentence) is None:
        return None
    return sentence


def is_affinity_line(line: str) -> bool:
    """Whether *line* is an affinity keyword line, readable or not."""
    return _AFFINITY_LINE.match((line or "").strip()) is not None


def expand_affinity_lines(oracle_text: str) -> str:
    """*oracle_text* with every affinity keyword line rewritten to its rules
    text.

    Text without one is returned unchanged, so applying this to every card
    costs a substring test. Applied by the compiler before any line is
    classified (``line_rewrites.expand_ability_lines``) and by the
    self-reduction reader before it reads a card's printed text — one function,
    so what the compiler claims and what the cast charges are one sentence.
    """
    if not oracle_text or "ffinity for" not in oracle_text:
        return oracle_text
    return "\n".join(
        affinity_sentence(line) or line for line in oracle_text.split("\n")
    )


def unread_affinity_line(oracle_text: str) -> str | None:
    """An affinity keyword line the rewrite could not read, or None.

    The support gate's question, asked of the text **after** the expansion has
    run (``flashback.unread_flashback_line``'s arrangement): a line still
    reading as affinity by then is one :func:`affinity_sentence` declined, and
    the card is unsupported naming it rather than cast at full price.
    """
    for line in (oracle_text or "").split("\n"):
        if is_affinity_line(line):
            return re.sub(r"\s*\([^()]*\)", "", line).strip()
    return None
