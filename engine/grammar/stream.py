"""Token cursor shared by the sub-parsers.

Recursive descent needs one mutable position that ``amounts``, ``nouns``, and
``parser`` all advance. Keeping it here (rather than in ``parser``) lets the
noun and quantity sub-parsers stay importable on their own, which is what makes
them unit-testable without standing up the whole statement grammar.
"""

from __future__ import annotations

from .errors import GrammarError
from .lexer import GToken, PUNCT, WORD, render


class TokenStream:
    """A cursor over a line's tokens with backtracking support.

    Backtracking is explicit (``mark``/``reset``) rather than implicit: a PEG
    alternative that half-consumes tokens and then fails must rewind, and a
    silent rewind is exactly the bug the full-consumption invariant exists to
    catch.
    """

    __slots__ = ("tokens", "pos", "line")

    def __init__(self, tokens: tuple[GToken, ...], line: str = "") -> None:
        self.tokens = tokens
        self.pos = 0
        self.line = line

    # -- inspection ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self.tokens)

    @property
    def exhausted(self) -> bool:
        return self.pos >= len(self.tokens)

    def peek(self, offset: int = 0) -> GToken | None:
        index = self.pos + offset
        return self.tokens[index] if 0 <= index < len(self.tokens) else None

    def peek_word(self, offset: int = 0) -> str | None:
        token = self.peek(offset)
        return token.text if token is not None and token.kind == WORD else None

    def words_from(self, offset: int = 0) -> tuple[str, ...]:
        """Remaining tokens as bare word strings, for vocabulary matching.
        Non-word tokens render as their text so positions stay aligned."""
        return tuple(token.text for token in self.tokens[self.pos + offset:])

    # -- movement -----------------------------------------------------------

    def advance(self, count: int = 1) -> None:
        self.pos = min(self.pos + count, len(self.tokens))

    def next(self) -> GToken:
        token = self.peek()
        if token is None:
            raise self.error("unexpected end of line")
        self.pos += 1
        return token

    def mark(self) -> int:
        return self.pos

    def reset(self, mark: int) -> None:
        self.pos = mark

    # -- matching -----------------------------------------------------------

    def at_word(self, *values: str) -> bool:
        token = self.peek()
        return token is not None and token.kind == WORD and token.text in values

    def at_punct(self, *values: str) -> bool:
        token = self.peek()
        return token is not None and token.kind == PUNCT and token.text in values

    def at_kind(self, kind: str) -> bool:
        token = self.peek()
        return token is not None and token.kind == kind

    def accept_word(self, *values: str) -> bool:
        """Consume the next token if it is one of *values*."""
        if self.at_word(*values):
            self.pos += 1
            return True
        return False

    def accept_phrase(self, *phrase: str) -> bool:
        """Consume a run of consecutive words, all-or-nothing."""
        if len(self.tokens) - self.pos < len(phrase):
            return False
        for offset, word in enumerate(phrase):
            token = self.tokens[self.pos + offset]
            if token.kind != WORD or token.text != word:
                return False
        self.pos += len(phrase)
        return True

    def accept_punct(self, *values: str) -> bool:
        if self.at_punct(*values):
            self.pos += 1
            return True
        return False

    def accept_kind(self, kind: str) -> GToken | None:
        token = self.peek()
        if token is not None and token.kind == kind:
            self.pos += 1
            return token
        return None

    def expect_word(self, *values: str) -> GToken:
        token = self.peek()
        if token is None or token.kind != WORD or token.text not in values:
            raise self.error(f"expected {' or '.join(values)!r}")
        self.pos += 1
        return token

    # -- errors -------------------------------------------------------------

    def error(self, message: str) -> GrammarError:
        return GrammarError(
            message,
            line=self.line,
            position=self.pos,
            remainder=render(self.tokens, self.pos),
        )


__all__ = ["TokenStream"]
