"""Ninjutsu (CR 702.49), the keyword the rules define as a rewrite.

CR 702.49a: *"Ninjutsu is an activated ability that functions only while the
card with ninjutsu is in a player's hand. 'Ninjutsu [cost]' means '[Cost],
Reveal this card from your hand, Return an unblocked attacking creature you
control to its owner's hand: Put this card onto the battlefield from your hand
tapped and attacking.'"*

So this module is ``engine/cycling.py`` one keyword over, and for its reason:
a keyword whose definition **is** a sentence gets one reader — the rewrite —
rather than a second path beside every seam an activated ability already
passes through. :func:`expand_ninjutsu_lines` turns the printed line into that
sentence before the compiler classifies anything, and from there:

* the grammar reads the cost clause (``grammar/costs.py``: the reveal and the
  chosen return) and the effect (``grammar/effects/counters.py``'s put onto
  the battlefield, with "tapped and attacking" behind the trailing zone);
* ``engine/activation_costs.py`` charges the same clause —
  ``reveal_self_from_hand`` and the ``return_to_hand_filter`` every chosen
  return cost already has, narrowed to an unblocked attacking creature;
* ``engine/activation_zones.py`` reads CR 113.6j off the reveal (a card on the
  battlefield is in no hand to be revealed from), so the ability is a hand
  ability and never a permanent's;
* ``Game.activate_from_hand`` pays it — the card stays in the hand, revealed
  (CR 702.49b), and the defender the returned creature was attacking is written
  onto the stack object before the creature leaves combat (CR 702.49c, 506.4);
* ``handlers/hand.put_source_card_from_hand_onto_battlefield`` resolves it: the
  card only if it is still in that hand (CR 400.7, the 2021-03-19 ruling), and
  attacking through ``engine/attacking_entry.py``, the write a Basri Ket token
  shares.

Nothing downstream knows the word. **Unblocked** is CR 509.1h's status, which
no creature has before blockers are declared — the 2021-03-19 ruling's "Before
then, attacking creatures are neither blocked nor unblocked" — and that is
``subject_filters.subject_matches``' game half of the ``unblocked_only`` key
(``Game.blockers_have_been_declared``), so the cost is unpayable in the
declare attackers step without a timing row of its own.

Commander ninjutsu (CR 702.49d) is not read here: no card in the pool prints
it, and :func:`is_ninjutsu_line` is the wide shape, so a printing the
expansion cannot read reaches the support gate in ``engine/oracle.py``
(:func:`unread_ninjutsu_line`) and is refused naming the line.
"""

from __future__ import annotations

import re

#: "Ninjutsu {1}{U}". Matched on the printed line with its reminder text
#: removed, case-insensitively; the cost is taken from the printed line so a
#: coloured pip keeps its letter.
_NINJUTSU_LINE = re.compile(
    r"^ninjutsu\s+(?P<cost>(?:\{[^{}]+\})+)$", re.IGNORECASE
)
_REMINDER = re.compile(r"\([^)]*\)")
#: Any line that *is* a ninjutsu keyword line, readable or not — "Commander
#: ninjutsu {4}{U}{U}" included. The wide shape the support gate asks.
_NINJUTSU_SHAPE = re.compile(r"^(?:commander\s+)?ninjutsu\b", re.IGNORECASE)

#: The rules text CR 702.49a gives the keyword, word for word.
NINJUTSU_RULES_TEXT = (
    "{cost}, Reveal this card from your hand, Return an unblocked attacking "
    "creature you control to its owner's hand: Put this card onto the "
    "battlefield from your hand tapped and attacking."
)


def _printed_keyword_line(line: str) -> str:
    """*line* with its reminder text and trailing full stop removed."""
    return " ".join(_REMINDER.sub("", line or "").split()).strip().rstrip(".")


def ninjutsu_cost(line: str) -> str | None:
    """The cost of a printed ninjutsu keyword line, or None."""
    match = _NINJUTSU_LINE.match(_printed_keyword_line(line))
    return match.group("cost") if match is not None else None


def is_ninjutsu_line(line: str) -> bool:
    """Whether *line* is a printed ninjutsu keyword line, whether or not
    :func:`expand_ninjutsu_line` can read it."""
    stripped = _printed_keyword_line(line)
    return bool(stripped) and bool(_NINJUTSU_SHAPE.match(stripped))


def expand_ninjutsu_line(line: str) -> str | None:
    """CR 702.49a's rules text for one printed ninjutsu line, or None."""
    cost = ninjutsu_cost(line)
    if cost is None:
        return None
    return NINJUTSU_RULES_TEXT.format(cost=cost)


def expand_ninjutsu_lines(oracle_text: str) -> str:
    """*oracle_text* with every ninjutsu keyword line rewritten to its rules
    text. Text without one is returned unchanged, so applying this to every
    card costs a scan."""
    if not oracle_text or "injutsu" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_ninjutsu_line(line) or line for line in oracle_text.split("\n")
    )


def unread_ninjutsu_line(oracle_text: str) -> str | None:
    """A printed ninjutsu-shaped line this module cannot rewrite, or None.

    The support gate's question, asked of the text **after** the expansion has
    run, for ``unread_cycling_line``'s reason: a line still reading as ninjutsu
    by then is one the expansion declined (commander ninjutsu), and the card
    is unsupported naming it rather than reporting supported off its other
    lines with the keyword dropped.
    """
    for line in (oracle_text or "").split("\n"):
        if is_ninjutsu_line(line):
            return " ".join(_REMINDER.sub("", line).split()).strip()
    return None


__all__ = [
    "NINJUTSU_RULES_TEXT",
    "expand_ninjutsu_line",
    "expand_ninjutsu_lines",
    "is_ninjutsu_line",
    "ninjutsu_cost",
    "unread_ninjutsu_line",
]
