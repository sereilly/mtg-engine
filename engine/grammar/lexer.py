"""Tokenizer for oracle text.

Distinct from the older ``OracleLexer`` in ``engine/oracle.py``, which shreds
information the grammar needs: it splits "+1/+1" into five symbol tokens and
keeps no source offsets, so a parse failure cannot say *where* it failed. This
lexer keeps P/T as one token, keeps spans, and stays vocabulary-free — whether
"wall" is a subtype or part of a card name is a question for the parser, which
knows the noun position; deciding it here would freeze the answer too early.

Reminder text in parentheses is stripped but *recorded*: the parse-coverage
guard needs to know it was seen and deliberately ignored rather than dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Token kinds
WORD = "word"
NUMBER = "number"
MANA = "mana"
PT = "pt"            # "+1/+1", "-0/-2", "+X/+0", "0/2"
PUNCT = "punct"
BULLET = "bullet"
QUOTE = "quote"
DASH = "dash"        # em/en dash — separates "Choose one —" from its bullets
SELF = "self"        # the card referring to itself by name ("Lightning Bolt deals…")


@dataclass(frozen=True)
class GToken:
    kind: str
    text: str
    start: int
    end: int

    def is_word(self, *values: str) -> bool:
        return self.kind == WORD and self.text in values


_REMINDER_RE = re.compile(r"\([^)]*\)")
_WHITESPACE_RE = re.compile(r"\s+")

# Order matters: P/T and mana must be tried before bare numbers and symbols.
_TOKEN_RE = re.compile(
    r"""
    (?P<mana>\{[^}]+\})
  | (?P<pt>[+-]?(?:\d+|[xy])\s*/\s*[+-]?(?:\d+|[xy]))
  | (?P<number>\d+)
  | (?P<word>[A-Za-z][A-Za-z'À-ɏ-]*)
  | (?P<bullet>•)
  | (?P<dash>[—–])
  | (?P<quote>["“”])
  | (?P<punct>[.,;:])
    """,
    re.VERBOSE,
)

# Words that carry an apostrophe-s possessive we normalize away ("land's
# controller" -> "land" "s"); keeping the possessive as part of the word would
# double the vocabulary for no gain.
_POSSESSIVE_RE = re.compile(r"'s$")


@dataclass(frozen=True)
class LexResult:
    tokens: tuple[GToken, ...]
    reminder_text: tuple[str, ...]
    normalized: str
    #: The same string with the card's own capitalisation kept — reminder text
    #: cut and whitespace collapsed exactly as :attr:`normalized`, so a token's
    #: offsets index both.
    #:
    #: This is what a :class:`TokenStream` must be given as its line. Every
    #: production that recovers a *printed* span through
    #: ``TokenStream.text_between`` — a granted ability's quoted text, a mana
    #: restriction, a registry-claimed sentence, a mode's label — slices that
    #: line at token offsets, and those offsets belong to the string the lexer
    #: actually walked. Handed the raw line instead, the slice is right only
    #: while nothing was cut: reminder text ahead of the span shifts every
    #: offset behind it, and the words that come back are somebody else's.
    #: Balduvian Shaman is the card that showed it — a parenthetical example
    #: between its two sentences, and the quoted ability it grants came back as
    #: a slice of the reminder text.
    source: str


def strip_reminder_text(text: str) -> tuple[str, tuple[str, ...]]:
    """Remove parenthetical reminder text, returning the text and what was cut."""
    reminders = tuple(match.group(0) for match in _REMINDER_RE.finditer(text))
    return _REMINDER_RE.sub("", text), reminders


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace. Curly quotes and dashes survive — the
    lexer classifies them, so normalizing them here would lose the distinction
    between a granted-ability quote and an apostrophe."""
    return _WHITESPACE_RE.sub(" ", text.strip().lower())


def _self_reference_spans(normalized: str, card_name: str | None) -> list[tuple[int, int]]:
    """Character spans where the card names itself.

    Pre-Sixth-Edition templating says "Lightning Bolt deals 3 damage" where
    modern templating says "This creature deals…". Both mean the source, so the
    lexer collapses them to one SELF token and the grammar never needs a card
    name. A legendary name with a comma is also referred to by its short name
    (CR 201.4c: "Ugin, the Spirit Dragon" says "Ugin"), so that form is
    matched too — full name first, so the short form never splits a longer
    self-reference in half.

    **A name that is also a creature type is left alone in a type position.**
    Aurochs prints "for each other attacking Aurochs", where the word is the
    creature type and not the card: collapsed to SELF the phrase counts other
    attacking copies of *this permanent excluding itself*, which is always
    none, so the pump resolves for +0/+0 on a card reporting itself supported.
    ``oracle._collapse_self_references`` applies the same rule on the
    static-line path, in the one spelling that path cannot share.

    **And a name that is also an effect verb is left alone in verb position.**
    Exile prints "Exile target nonwhite attacking creature": collapsed to SELF
    the sentence has a subject and no verb, and the card refuses on
    "unrecognized effect verb" — a refusal naming a word it does not print.
    See :func:`_in_verb_position`.
    """
    if not card_name:
        return []
    full = normalize(card_name)
    if not full:
        return []
    needles = [full]
    if "," in full:
        short = full.split(",", 1)[0].strip()
        if short:
            needles.append(short)

    def _is_word_char(index: int) -> bool:
        return 0 <= index < len(normalized) and (
            normalized[index].isalnum() or normalized[index] == "'"
        )

    def _ends_a_word(index: int) -> bool:
        """Whether a span ending at *index* sits on a word boundary.

        A possessive tail is a boundary too: "Halfdane's base power" is the
        card naming itself in possessive position, and reading the apostrophe
        as part of the word left the name an unknown WORD token no production
        could read. The tail must be exactly "'s" at a real boundary, so a
        name that merely *contains* one ("Urza's Mine" naming itself) still
        matches whole rather than splitting at its own apostrophe.
        """
        if not _is_word_char(index):
            return True
        return normalized[index:index + 2] == "'s" and not _is_word_char(index + 2)

    spans: list[tuple[int, int]] = []
    for needle in needles:
        start = normalized.find(needle)
        while start != -1:
            end = start + len(needle)
            # Only whole-word matches. A card named "Fire" must not swallow the
            # first four letters of "Firebreathing" — that would emit a SELF
            # token and drop the rest of the word, defeating full-token
            # consumption. A span inside one already claimed (the short name
            # inside the full name) is skipped for the same reason.
            if (
                not _is_word_char(start - 1)
                and _ends_a_word(end)
                and not any(s <= start < e for s, e in spans)
                and not _in_type_position(normalized, start, needle)
                and not _in_verb_position(normalized, start, end, needle)
            ):
                spans.append((start, end))
            start = normalized.find(needle, start + 1)
    return spans


#: Words after which a name that is *also* a creature type reads as the type.
#: The same set ``oracle._TYPE_POSITION_WORDS`` holds; kept here rather than
#: imported because this reader works on raw character offsets and that one on
#: a normalized line, and `engine.oracle` imports this package.
_TYPE_POSITION_WORDS = frozenset({
    "a", "an", "another", "any", "attacking", "blocking", "each", "every",
    "other", "target", "untapped", "tapped", "all", "no",
})


#: Card names that are also the imperative verb an effect sentence opens with.
#: Held to what the pool prints rather than to every verb the grammar reads:
#: the whole *name* has to be the verb, so the collision needs a one-word card
#: name that is exactly an effect verb **and** a sentence in that card's own
#: text that opens with it. A pool scan over both manifest roles finds exactly
#: one — Alliances' Exile — and the three other cards whose name is followed by
#: a noun-phrase opener (Sacrifice, Axelrod Gunnarson, Baron Sengir) are all
#: genuine self-references, which is why the word set is a condition here and
#: not merely the position.
_VERB_NAMES = frozenset({"exile"})

#: Words that open the noun phrase an imperative verb takes. A self-reference is
#: always a *subject*, so it is always followed by a verb ("Lightning Bolt
#: **deals**", "Halfdane**'s** base power") and never by one of these.
_OBJECT_POSITION_WORDS = frozenset({
    "target", "all", "a", "an", "each", "any", "up", "x", "the", "that",
    "this", "those", "these", "another", "other", "two", "three", "it",
    "them",
})


def _in_verb_position(normalized: str, start: int, end: int, needle: str) -> bool:
    """Whether the match at *start* is the card's name used as an effect verb.

    Two conditions, both required, because either alone is wrong. The word must
    be one a sentence can open with (:data:`_VERB_NAMES`) — Axelrod Gunnarson
    and Baron Sengir both print their names before a noun-phrase opener
    ("dealt damage by Baron Sengir **this** turn") and both are self-references.
    And the match must sit where a verb goes: at the start of a sentence, with a
    noun phrase after it. "Exile deals 3 damage" would be the card naming
    itself, and this leaves that reading alone.

    Only ever true for a card whose own name is an effect verb — one in the
    pool — so it costs two set lookups on every other card and nothing else.

    ``oracle._collapse_self_references`` deliberately grows no twin of this. Its
    collapse is a *retry* run only when the plain reading found no trigger
    condition, so a verb-named card with no trigger never reaches it; a
    verb-named card that printed one would need the rule there too.
    """
    if needle not in _VERB_NAMES:
        return False
    before = normalized[:start].rstrip()
    if before and before[-1] not in ".;—":
        return False
    after = normalized[end:].lstrip()
    return after.split(" ", 1)[0].strip(".,;:") in _OBJECT_POSITION_WORDS


def _in_type_position(normalized: str, start: int, needle: str) -> bool:
    """Whether the match at *start* is the card's name used as a creature type.

    Only ever true for a card whose own name is one — four in the pool — so it
    costs a set lookup on every other card and nothing else.
    """
    from .vocabulary import CREATURE_TYPES

    if needle not in CREATURE_TYPES:
        return False
    before = normalized[:start].rstrip()
    return bool(before) and before.rsplit(" ", 1)[-1] in _TYPE_POSITION_WORDS


def tokenize(line: str, *, card_name: str | None = None) -> LexResult:
    """Tokenize one oracle line.

    *card_name* lets the card's self-references collapse into a single SELF
    token, so a production can say "the source deals damage" without the
    grammar knowing anything about card names.
    """
    stripped, reminders = strip_reminder_text(line)
    # One reduction, read twice: `normalized` is what the token patterns match
    # and `source` is what a printed span is sliced out of. Lower-casing does
    # not move a character, so the two agree offset for offset — which is the
    # whole of the contract `source` documents.
    source = _WHITESPACE_RE.sub(" ", stripped.strip())
    normalized = source.lower()
    self_spans = _self_reference_spans(normalized, card_name)

    tokens: list[GToken] = []
    skip_until = -1
    for match in _TOKEN_RE.finditer(normalized):
        if match.start() < skip_until:
            continue
        for span_start, span_end in self_spans:
            if match.start() == span_start:
                tokens.append(GToken(SELF, normalized[span_start:span_end], span_start, span_end))
                skip_until = span_end
                # A possessive self-reference ("Halfdane's") keeps its marker,
                # exactly as the WORD branch below keeps "player's" as the noun
                # plus "'s" — dropping it would break full-token accounting.
                if normalized[span_end:span_end + 2] == "'s":
                    tokens.append(GToken(WORD, "'s", span_end, span_end + 2))
                    skip_until = span_end + 2
                break
        if match.start() < skip_until:
            continue
        kind = match.lastgroup or WORD
        raw = match.group()
        start, end = match.start(), match.end()
        if kind == MANA:
            tokens.append(GToken(MANA, raw.upper(), start, end))
        elif kind == PT:
            tokens.append(GToken(PT, raw.replace(" ", ""), start, end))
        elif kind == WORD:
            word = _POSSESSIVE_RE.sub("", raw)
            # A bare possessive ("player's") becomes the noun plus a marker the
            # parser can skip; dropping it entirely would break full-token
            # consumption accounting.
            if word != raw:
                tokens.append(GToken(WORD, word, start, end - 2))
                tokens.append(GToken(WORD, "'s", end - 2, end))
            else:
                tokens.append(GToken(WORD, raw, start, end))
        else:
            tokens.append(GToken(kind, raw, start, end))

    return LexResult(tuple(tokens), reminders, normalized, source)


def render(tokens: tuple[GToken, ...], start: int = 0) -> str:
    """Human-readable rendering of a token slice, for error messages."""
    return " ".join(token.text for token in tokens[start:])


__all__ = [
    "BULLET", "DASH", "GToken", "LexResult", "MANA", "NUMBER", "PT", "PUNCT",
    "QUOTE", "SELF", "WORD", "normalize", "render", "strip_reminder_text", "tokenize",
]
