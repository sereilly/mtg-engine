"""Modular (CR 702.43), the keyword and the two abilities it *is*.

CR 702.43a does not describe modular, it **defines** it: "Modular N" means
"This permanent enters with N +1/+1 counters on it" and "When this permanent is
put into a graveyard from the battlefield, you may put a +1/+1 counter on
target artifact creature for each +1/+1 counter on this permanent." So this is
the rewrite ``engine/fading.py`` made for fading — the printed keyword line
becomes the two sentences the rules say it already is, one line each (CR 113.3:
a static ability and a triggered ability are two abilities), applied by
``line_rewrites.expand_ability_lines`` before any line is classified. From
there nothing downstream knows the word:

* the entry sentence is ``enter_effects``' "enters with N +1/+1 counters" —
  the reader Triskelion and Karstoderm already go through, read by the support
  gate and by the entry state, so what is claimed and what is placed cannot
  drift;
* the death sentence is an ordinary ``dies`` trigger whose effect is the
  targeted +1/+1 placement with its number read off the source's own pile
  (``ast.CountersOnSource`` on the ``x_from_count`` channel). The source has
  left the battlefield by the time it resolves, and the count is the one it
  left with: the departed ``Permanent`` keeps its state, which is CR 603.10a's
  look-back and CR 608.2h's last-known information — Revered Unicorn's leave
  trigger reads its age counters the same way. The Darksteel rulings
  (2006-09-25) are that answer: a modular creature killed by -1/-1 counters
  "will put a number of +1/+1 counters on the target artifact creature equal to
  the number of +1/+1 counters on this creature before it left the
  battlefield". "Target" is chosen as the trigger goes on the stack and, with
  no artifact creature to name, the trigger is removed (CR 603.3d); "you may"
  is the resolution's offer.

**The rule's wording, not the reminder's**, as fading carries its rule's. The
reminder says "put its +1/+1 counters on target artifact creature", which CR
122.8 reads as the same number again; CR 702.43a says it directly, and that is
the sentence the grammar is given.

**"Modular—Sunburst"** (CR 702.44c) is modular with sunburst setting N: the
CR's own example says it means "This permanent enters with a +1/+1 counter on
it for each color of mana spent to cast it" and the same graveyard trigger,
so that is the pair it is rewritten into (:data:`MODULAR_SUNBURST_RULES_TEXT`).
The entry sentence is ``enter_effects``' colours-spent reader — the one
sunburst's own rewrite reaches (``engine/sunburst.py``) — and it is a +1/+1
counter whatever the object is, because CR 702.44c says the kind does not
depend on whether the spell is a creature. The death trigger counts the
counters the creature left with, whatever paid for them (the Arcbound Wanderer
rulings of 2004-12-01: "the number of colors of mana used to pay its cost
doesn't matter anymore").

**N is spelled as a word**, as the reminder text prints it, because that is
the form the entry-state reader reads; a count the number table cannot spell
keeps the keyword line *unread*, and :func:`unread_modular_line` keeps the card
unsupported naming it — fading's shape test, wider than the reader. Without
that gate a creature whose *other* line compiles would report supported with
its modular dropped: a 0/0 that dies on arrival.

**The word itself is still an ability the permanent has** (CR 702.43a:
modular "represents" both abilities), and a card can ask about it: Arcbound
Overseer puts a counter on "each creature you control **with modular**". That
question is layer 6's like any other keyword's (``Game._has_keyword``), and the
seed it starts from — the printed abilities, ``printed_characteristics`` —
reads the word off the printed line through :func:`is_modular_line`, beside the
ingested keywords field, so a copy, a fixture and a granted line all answer it
the same way. CR 702.43b (several instances each work separately) needs
nothing here: two printed lines are two pairs of sentences.
"""

from __future__ import annotations

import re

#: The rules text CR 702.43a gives the keyword, one line per ability, quoted
#: word for word except that N is spelled as the reminder text spells it.
MODULAR_RULES_TEXT = (
    "This permanent enters with {count} +1/+1 {noun} on it.\n"
    "When this permanent is put into a graveyard from the battlefield, you may "
    "put a +1/+1 counter on target artifact creature for each +1/+1 counter on "
    "this permanent."
)

#: CR 702.44c's example, word for word: "Modular—Sunburst" means these two
#: abilities, one line each.
MODULAR_SUNBURST_RULES_TEXT = (
    "This permanent enters with a +1/+1 counter on it for each color of mana "
    "spent to cast it.\n"
    "When this permanent is put into a graveyard from the battlefield, you may "
    "put a +1/+1 counter on target artifact creature for each +1/+1 counter on "
    "this permanent."
)

#: "Modular—Sunburst" as the printed line survives reminder-text removal.
_MODULAR_SUNBURST_LINE = re.compile(
    r"^modular\s*[—-]\s*sunburst$", re.IGNORECASE
)

#: "modular 3" as the printed line survives reminder-text removal.
_MODULAR_LINE = re.compile(r"^modular\s+(?P<count>\d+)$", re.IGNORECASE)

#: Any line that *is* a modular keyword line, readable or not — "Modular X",
#: a count with no word, "Modular—Sunburst" (Fifth Dawn's spelling, CR
#: 702.44's count), a bare "Modular". The wider shape is what the support gate
#: asks, so a variant the expansion refuses stays refused *as modular* rather
#: than reaching a classifier that has never heard of the word. The keyword and
#: at most one argument, and nothing after.
_MODULAR_SHAPE = re.compile(
    r"^modular(?:\s*[—-]\s*\S+|\s+\S+)?\s*\.?$", re.IGNORECASE
)

_REMINDER = re.compile(r"\([^)]*\)")


def _stripped(line: str) -> str:
    return " ".join(_REMINDER.sub("", line or "").split()).strip()


def _count_word(count: int) -> str | None:
    """*count* spelled the way the entry-state reader reads it, or None.

    Inverted from the grammar's own number table rather than a second list
    (``fading._count_word``'s arrangement), so a number the reader cannot read
    is a number this cannot write.
    """
    from .grammar.vocabulary import NUMBER_WORDS

    for word, value in NUMBER_WORDS.items():
        if value == count and word not in ("a", "an"):
            return word
    return None


def modular_count(line: str) -> int | None:
    """The printed N of one modular line, or None when *line* is not a modular
    line this module can rewrite."""
    match = _MODULAR_LINE.match(_stripped(line).rstrip("."))
    if match is None:
        return None
    count = int(match.group("count"))
    if count < 1 or _count_word(count) is None:
        return None
    return count


def is_modular_line(line: str) -> bool:
    """Whether *line* is a printed modular keyword line, whether or not
    :func:`expand_modular_line` can read it."""
    return _MODULAR_SHAPE.match(_stripped(line)) is not None


def expand_modular_line(line: str) -> str | None:
    """The CR 702.43a rules text for one printed modular line — CR
    702.44c's for "Modular—Sunburst" — or None."""
    if _MODULAR_SUNBURST_LINE.match(_stripped(line).rstrip(".")) is not None:
        return MODULAR_SUNBURST_RULES_TEXT
    count = modular_count(line)
    if count is None:
        return None
    return MODULAR_RULES_TEXT.format(
        count=_count_word(count), noun="counter" if count == 1 else "counters"
    )


def expand_modular_lines(oracle_text: str) -> str:
    """*oracle_text* with every modular keyword line rewritten to its rules
    text. Text without one is returned unchanged."""
    if not oracle_text or "odular" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_modular_line(line) or line for line in oracle_text.split("\n")
    )


def unread_modular_line(oracle_text: str) -> str | None:
    """A printed modular-shaped line this module cannot rewrite, or None.

    The support gate's question, asked of the text **after** the expansion has
    run, as ``fading.unread_fading_line`` is.
    """
    for line in (oracle_text or "").split("\n"):
        if is_modular_line(line):
            return _stripped(line)
    return None


def has_printed_modular(oracle_text: str) -> bool:
    """Whether *oracle_text* prints a modular keyword line — the word CR
    702.43a names as an ability, for the layer-6 seed (Arcbound Overseer's
    "each creature you control with modular")."""
    if not oracle_text or "odular" not in oracle_text:
        return False
    return any(is_modular_line(line) for line in oracle_text.split("\n"))


__all__ = [
    "MODULAR_RULES_TEXT",
    "MODULAR_SUNBURST_RULES_TEXT",
    "expand_modular_line",
    "expand_modular_lines",
    "has_printed_modular",
    "is_modular_line",
    "modular_count",
    "unread_modular_line",
]
