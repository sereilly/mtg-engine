"""How a printed line is normalized before a text-keyed table reads it.

:func:`normalize_creature_line` is the one spelling every text-keyed reader
in the engine matches against: the ability word dropped (CR 207.2c), reminder
text stripped, a semicolon read as a comma, whitespace collapsed and the
closing full stop gone. A program stores its static lines in this spelling and
the tables that dispatch on them read it back, so a second spelling anywhere
would be a gate and a runtime reading two different sentences.

Its own module, beneath the compiler and every reader split out of it, because
all of them read a line through it and ``engine/oracle.py`` imports all of
them: left in the compiler it would make each of those imports a cycle.
Split out of ``engine/oracle.py`` at the 2,000-line cap; ``engine.oracle``
still exports :func:`normalize_creature_line`, which is in its ``__all__``.
"""

from __future__ import annotations

import re

from .oracle_types import strip_ability_word


_WHITESPACE_RE = re.compile(r"\s+")
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")


def _normalize_text(oracle_text: str) -> str:
    return _WHITESPACE_RE.sub(" ", oracle_text.strip().lower())


def normalize_creature_line(line: str) -> str:
    lowered = strip_ability_word(line).lower()
    lowered = _PARENTHETICAL_RE.sub("", lowered)
    lowered = lowered.replace(";", ",")
    lowered = _WHITESPACE_RE.sub(" ", lowered).strip(" .,")
    return lowered
