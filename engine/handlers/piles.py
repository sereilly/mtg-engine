"""The handler for CR 700.3: separating objects into two piles.

One instruction kind, ``separate_into_piles``, for every printing — the
procedure, both prompts' resolvers and the table of what a pile may be sent to
do are ``engine/piles.py``. A module of its own rather than a handler in
``zones`` because four of the six printings move nothing between zones at the
split and two of them never move anything at all (Fight or Flight and Stand or
Fall leave a restriction behind).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..piles import begin_separation
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..oracle_types import OracleExecutionContext, OracleInstruction


@effect_handler("separate_into_piles")
def separate_into_piles(
    game: "Game", instruction: "OracleInstruction", context: "OracleExecutionContext"
) -> tuple[bool, str]:
    """"Separate <objects> into two piles. <What becomes of each.>"

    Two decisions by (usually) two seats, so the handler does nothing but start
    the procedure: each decision is a prompt, an interactive seat's answer
    resumes the steps behind it, and every other seat answers where it stands
    (``default_at_arm``). Starting it is the **last** thing this does — the
    procedure is a resumable loop (``engine/resumption.py``), and anything
    written after it would be skipped whenever a step stopped to ask.
    """
    begin_separation(game, instruction, context)
    return True, "resolved"
