"""Static abilities that function while the card is a **spell on the stack**
(CR 113.6b).

    As long as Kaervek's Torch is on the stack, spells that target it cost {2}
    more to cast.

    As long as Torrent of Lava is on the stack, each creature has "{T}: Prevent
    the next 1 damage that would be dealt to this creature by Torrent of Lava
    this turn."

Two printed sentences, one mechanism, and the mechanism is *where the ability's
source is*. Everything else in the engine that applies a static ability reads it
off a permanent — ``engine/global_statics.py`` scans battlefields,
``engine/cost_modifiers.py``'s taxes are charged "once per taxing permanent",
``engine/auras.py`` derives from an attachment. The source here is on the stack,
it is never a permanent while the ability functions, and the moment it resolves
the ability is gone.

**The prefix is the whole of what this module reads.** What follows it is an
ordinary printed static, handed to the table that already implements that
sentence: a cost tax to ``cost_modifiers``, a board-wide granted ability to
``global_statics``. So the two cards are one mechanism rather than two — and a
card printing a *third* kind of stack static needs one reader beside
:func:`_cost_modifiers` and :func:`_global_static` and nothing new anywhere
else.

**Why the prefix cannot live in those tables.** A permanent card is a spell on
the stack before it resolves, so a creature could print this sentence too. If
``global_static_for`` read the "as long as … is on the stack" wording itself, it
would then apply that creature's ability from the *battlefield*, which is
exactly the window the card excludes. The prefix has to be a separate reading
because it names a different zone.

**The subject must be the card itself.** "As long as *some other thing* is on
the stack" is a different ability with a different source, and this module has
no way to find that object — so it refuses, and the card stays visibly
unsupported rather than working from the wrong zone.
"""

from __future__ import annotations

import re
from functools import lru_cache

# "As long as <this card> is on the stack, <effect>." — the printed wording, and
# the pre-Sixth-Edition templating that goes with it: the card names itself
# rather than saying "this spell". Both spellings are read, because the
# distinction is a templating era and not a rule.
_ON_THE_STACK = re.compile(
    r"^as long as (?P<subject>.+?) is on the stack, (?P<effect>.+)$"
)

#: The printed self-references a stack static's subject may be, beside the
#: card's own name. "This spell" is CR 113.6's own wording and the form a
#: modern printing of either card would use.
_SELF_SUBJECTS = frozenset({"this spell", "this card"})

_REMINDER = re.compile(r"\([^)]*\)")


def _line(raw: str) -> str:
    """One printed line as this module compares it: no reminder text, one space
    between words, lowercased, no full stop. The same reduction
    ``global_statics`` applies, because the clause is handed straight to it."""
    return " ".join(_REMINDER.sub("", raw).strip().lower().split()).rstrip(".")


def _self_forms(card_name: str | None) -> tuple[str, ...]:
    """The names *card_name* may refer to itself by (CR 201.4c: a legendary
    name is also spoken as its first word)."""
    if not card_name:
        return ()
    full = card_name.strip().lower()
    if not full:
        return ()
    forms = [full]
    if "," in full:
        short = full.split(",", 1)[0].strip()
        if short:
            forms.append(short)
    return tuple(forms)


def stack_static_clause(line: str, card_name: str | None) -> str | None:
    """The effect clause of *line*, if *line* is a stack static of *card_name*.

    ``None`` for anything else, including a line whose subject is some object
    other than this card: see the module docstring.
    """
    match = _ON_THE_STACK.match(_line(line))
    if match is None:
        return None
    subject = match.group("subject").strip()
    if subject not in _SELF_SUBJECTS and subject not in _self_forms(card_name):
        return None
    return match.group("effect").strip()


def stack_static_clauses(oracle_text: str, card_name: str | None) -> tuple[str, ...]:
    """Every stack static clause *oracle_text* prints, in printed order."""
    return tuple(
        clause
        for raw in (oracle_text or "").splitlines()
        if (clause := stack_static_clause(raw, card_name)) is not None
    )


# ---------------------------------------------------------------------------
# What the clause after the prefix may say
# ---------------------------------------------------------------------------
#
# Each reader is the module that already implements the sentence, asked its own
# question — never a copy of its phrases. A clause no reader claims refuses, so
# a card printing a stack static this engine cannot carry out stays unsupported
# instead of reporting a sentence read and doing nothing with it.


def _cost_modifiers(clause: str) -> tuple:
    """The cost modifiers *clause* imposes while its card is on the stack.

    Empty for a clause whose modifiers this path could not charge. The
    narrowing is deliberate rather than defensive: ``spell_cost_tax`` below
    charges *generic mana at CR 601.2f*, and the other three resources a
    modifier can name are charged by their own readers over the **battlefield**
    (``spell_life_tax`` at 601.2h, ``spell_symbol_tax`` into the coloured part,
    ``sacrifice_taxes`` at announcement). A clause naming one of those would be
    claimed here and charged by nobody, which is the silent half-implementation
    this seam exists to prevent.
    """
    from .cost_modifiers import cost_modifiers_for

    modifiers = cost_modifiers_for(clause)
    if not modifiers:
        return ()
    if any(
        modifier.applies_to != "cast"
        or modifier.reduces
        or modifier.life
        or modifier.symbols
        or modifier.sacrifice_filter is not None
        or modifier.per_symbol is not None
        for modifier in modifiers
    ):
        return ()
    return modifiers


def _global_static(clause: str):
    """The board-wide static *clause* applies while its card is on the stack.

    ``None`` for a clause whose scope is **relative** to its source's
    controller. ``global_statics`` answers "creatures you control" by comparing
    the affected permanent's controller with the *source permanent*'s
    (CR 109.5), and a spell on the stack is not one — so the scope would be
    answered False for every permanent and the sentence would silently apply to
    nothing. Refusing keeps the card unsupported and the backlog honest; the
    pool prints no such card today.
    """
    from .global_statics import global_static_for

    static = global_static_for(clause)
    if static is None:
        return None
    if static.applies_to.endswith("_you_control"):
        return None
    return static


@lru_cache(maxsize=None)
def stack_static_claims_line(line: str, card_name: str | None) -> bool:
    """Whether *line* is, in full, a stack static this engine carries out.

    The support gate (``oracle._derived_static_claims``) and the parse-coverage
    census both ask this, so what the engine implements and what it claims to
    have read cannot drift.
    """
    clause = stack_static_clause(line, card_name)
    if clause is None:
        return False
    return bool(_cost_modifiers(clause)) or _global_static(clause) is not None


@lru_cache(maxsize=None)
def stack_static_cost_modifiers(
    oracle_text: str, card_name: str | None
) -> tuple:
    """Every cost modifier this card imposes while it is on the stack."""
    return tuple(
        modifier
        for clause in stack_static_clauses(oracle_text, card_name)
        for modifier in _cost_modifiers(clause)
    )


@lru_cache(maxsize=None)
def stack_static_grants(oracle_text: str, card_name: str | None) -> tuple:
    """Every board-wide static this card applies while it is on the stack."""
    return tuple(
        static
        for clause in stack_static_clauses(oracle_text, card_name)
        if (static := _global_static(clause)) is not None
    )


def grants_stack_static(card) -> bool:
    """Whether *card* prints a stack static at all.

    Asked at the one place an object goes on the stack, so it has to be cheap:
    the readers above are cached on the card's text, and a card printing none
    of this wording answers on a substring.
    """
    text = getattr(card, "oracle_text", "") or ""
    if "on the stack" not in text.lower():
        return False
    name = getattr(card, "name", None)
    return bool(
        stack_static_cost_modifiers(text, name) or stack_static_grants(text, name)
    )


# ---------------------------------------------------------------------------
# The live sources
# ---------------------------------------------------------------------------


def stack_static_cost_sources(stack) -> list[tuple]:
    """Each object on *stack* that taxes casts, paired with its modifiers.

    The stack object itself is the pair's first half, not its card: "spells
    that target **it**" is a fact about which *object* a spell chose, and two
    copies of one card on the stack are two objects (CR 111.4 / CR 601.2c).
    """
    found = []
    for item in stack or ():
        card = getattr(item, "card", None)
        if card is None:
            continue
        modifiers = stack_static_cost_modifiers(
            getattr(card, "oracle_text", "") or "", getattr(card, "name", None)
        )
        if modifiers:
            found.append((item, modifiers))
    return found


def stack_static_grant_sources(stack) -> list[tuple]:
    """Each object on *stack* granting a board-wide static, paired with it."""
    found = []
    for item in stack or ():
        card = getattr(item, "card", None)
        if card is None:
            continue
        for static in stack_static_grants(
            getattr(card, "oracle_text", "") or "", getattr(card, "name", None)
        ):
            found.append((item, static))
    return found


__all__ = [
    "grants_stack_static",
    "stack_static_claims_line",
    "stack_static_clause",
    "stack_static_clauses",
    "stack_static_cost_modifiers",
    "stack_static_cost_sources",
    "stack_static_grant_sources",
    "stack_static_grants",
]
