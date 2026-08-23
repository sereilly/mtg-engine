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
                and not _is_word_char(end)
                and not any(s <= start < e for s, e in spans)
            ):
                spans.append((start, end))
            start = normalized.find(needle, start + 1)
    return spans


def tokenize(line: str, *, card_name: str | None = None) -> LexResult:
    """Tokenize one oracle line.

    *card_name* lets the card's self-references collapse into a single SELF
    token, so a production can say "the source deals damage" without the
    grammar knowing anything about card names.
    """
    stripped, reminders = strip_reminder_text(line)
    normalized = normalize(stripped)
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

    return LexResult(tuple(tokens), reminders, normalized)


def render(tokens: tuple[GToken, ...], start: int = 0) -> str:
    """Human-readable rendering of a token slice, for error messages."""
    return " ".join(token.text for token in tokens[start:])


__all__ = [
    "BULLET", "DASH", "GToken", "LexResult", "MANA", "NUMBER", "PT", "PUNCT",
    "QUOTE", "SELF", "WORD", "normalize", "render", "strip_reminder_text", "tokenize",
]
