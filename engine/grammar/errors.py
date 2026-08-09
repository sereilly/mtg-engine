"""Grammar failure types.

A ``GrammarError`` is a *loud* failure and that is the point: the legacy
substring rules classified a card "supported" while quietly dropping the half
of its text they did not match. The grammar's contract is the opposite — it
either accounts for every token of a line or refuses it, and the refusal
carries an offset so ``support_report`` names the exact clause that needs work.
"""

from __future__ import annotations


class GrammarError(Exception):
    """Raised when a line cannot be fully parsed.

    ``position`` is a token index into the line's token stream, ``text`` the
    source line. The message renders as ``expected X at 'rest of line'`` so the
    coverage report can group failures by what the grammar was looking for.
    """

    def __init__(
        self,
        message: str,
        *,
        line: str = "",
        position: int = 0,
        remainder: str = "",
    ) -> None:
        self.message = message
        self.line = line
        self.position = position
        self.remainder = remainder
        detail = f" at {remainder!r}" if remainder else ""
        super().__init__(f"{message}{detail}")

    @property
    def reason(self) -> str:
        """Short machine-groupable label for the coverage report."""
        return self.message


class LoweringError(Exception):
    """Raised when a well-formed AST has no instruction lowering yet.

    Distinct from :class:`GrammarError` so the ratchet can separate "the
    grammar could not read this" from "the grammar read this but the effect
    layer has no handler for it" — they have different backlogs.
    """

    def __init__(self, message: str, *, node: object | None = None) -> None:
        self.message = message
        self.node = node
        super().__init__(message)

    @property
    def reason(self) -> str:
        return self.message


__all__ = ["GrammarError", "LoweringError"]
