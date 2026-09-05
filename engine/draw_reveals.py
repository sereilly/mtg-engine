"""Reveals a *draw* causes (CR 701.16), and the printed line that asks for one.

One sentence today: **"Reveal the first card you draw each turn."** (Rowen.) It
is a static ability of a permanent — nothing goes on the stack, nothing is
targeted, and while the permanent is on the battlefield its controller's first
draw of every turn is public.

The line lives here rather than in ``draw_step_modifiers.py`` because it is not
about the draw *step*: CR 504.1's turn-based draw is one of the draws it
reveals, and a cantrip, a Howling Mine bonus and an upkeep trigger's draw are
the others. The one place all of them meet is the draw seam
(``Game._draw_with_replacements``), which is where this is enforced.

**The reveal is announced, not just logged.** "Whenever you reveal a basic land
card this way, draw a card" is the sentence behind it on the same card, and it
is an ordinary triggered ability over an ordinary event
(``revealed_drawn_card``) rather than a second half of this table — so the noun
phrase it narrows on and the effect it produces are both payload, and a card
printing "whenever you reveal a creature card this way, gain 2 life" needs no
code here.

Three readers, for the reason every text-keyed table in this engine has three:
the draw seam that carries it out, the support gate that decides whether the
card is implemented, and the parse-coverage report that decides whether the
sentence was read. Three copies of one sentence drift; one function does not.
"""

from __future__ import annotations

import re

#: "Reveal the first card you draw each turn." Anchored on the whole sentence:
#: a line saying more than this is a rule this module does not carry out, and a
#: prefix match would claim it and then enforce only the part it recognised.
_FIRST_DRAW_REVEAL = re.compile(r"^reveal the first card you draw each turn$")


def reveals_first_draw_line(line: str) -> bool:
    """Whether one printed line asks for the first draw of each turn to be revealed.

    Normalized the way every other text-keyed reader here normalizes — lowercased,
    whitespace collapsed, the trailing stop dropped — so the printed line and the
    compiler's already-normalized one give the same answer.
    """
    text = " ".join((line or "").strip().lower().rstrip(".").split())
    return _FIRST_DRAW_REVEAL.match(text) is not None


def reveals_first_draw(game, player_index: int) -> bool:
    """Whether *player_index* must reveal their first draw of each turn.

    Derived from the board on every draw rather than stamped when a permanent
    enters, for the reason CR 611.3a gives: the ability lasts exactly as long as
    its source is on the battlefield, and a stamped flag has to be remembered
    off again.

    Read through ``effective_card`` so a text change (CR 612.1) or a copy
    (CR 707.2) is read as the card it has become, and through
    ``expand_card_lines`` rather than ``oracle_text.splitlines()`` — Rowen prints
    this sentence and the trigger behind it in **one paragraph**, so a reader
    that split the raw text saw one line that is neither, matched nothing and
    revealed nothing. That is the "a reader of a card's lines that does not start
    from ``expand_ability_lines`` is reading a different card" rule, collected
    the first time this module asked the question.
    """
    from .oracle import expand_card_lines

    for permanent in game.controlled_by(player_index):
        card = permanent.effective_card
        if any(reveals_first_draw_line(line) for line in expand_card_lines(card)):
            return True
    return False


__all__ = ["reveals_first_draw", "reveals_first_draw_line"]
