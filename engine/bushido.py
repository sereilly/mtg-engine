"""Bushido (CR 702.45), the keyword and the triggered ability it *is*.

CR 702.45a does not describe bushido, it **defines** it: "Bushido N" means
"Whenever this creature blocks or becomes blocked, it gets +N/+N until end of
turn." So this module is the rewrite ``engine/rampage.py`` and
``engine/flanking.py`` established — the printed keyword line becomes the
ability the rules say it already is, and from there the existing block and
becomes-blocked dispatchers in ``engine/phases/block_triggers.py`` fire it,
the stack carries it, and one handler resolves it. Nothing downstream of the
compiler knows the word.

**The ability is Chub Toad's, word for word.** "Whenever this creature blocks
or becomes blocked, it gets +2/+2 until end of turn" (Ice Age) is CR 702.45a's
sentence printed without the keyword, and the grammar already reads it: the
bare joined condition ``creature_blocks_or_blocked_by`` (once per block,
CR 509.3c/509.3d — no noun phrase, so no per-creature firing) and the
``pump_self`` the sentence lowers to. A bushido trigger is built as exactly
that pair, so the dispatchers, the handler, the AI's combat reading of a
blocked pump (``ai_combat_triggers.BLOCKED_CONDITIONS``) and the support
report all meet an ability they already know.

**Bushido is line-derived, and needs the word too** — flanking's arrangement,
for three Champions of Kamigawa readers. Sensei Golden-Tail *grants* it ("That
creature gains bushido 1"), so a grant of the keyword grants the printed line
(``keywords.LINE_DERIVED_KEYWORDS``) and the compiler builds the trigger out
of the folded text; Takeno, Samurai General *counts* it ("for each point of
bushido it has"), which is :func:`bushido_points` over the same lines; and
Kenzo the Hardhearted prints it on a flip card's bottom half, which is a face
a flip makes current — the compiler reads that face's text like any other.

CR 702.45b — several instances of bushido each trigger separately — is why
:func:`bushido_amounts` returns every instance rather than their sum: two
abilities go on the stack, and each may be responded to on its own.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .oracle_types import (OracleInstruction, ParsedTriggeredAbility,
                           TriggerCondition, compilation_cache)

#: The instruction one instance of bushido lowers to: the one CR 702.45a's own
#: sentence lowers to through the grammar (Chub Toad), with its N as payload.
BUSHIDO_KIND = "pump_self"

#: The bucket the support report puts it in — ``rampage.RAMPAGE_LABEL``'s word
#: and its reason for being carried here rather than in
#: ``triggered_labels.TRIGGERED_LABELS``: that table describes the abilities the
#: grammar reads, and this one is derived from a keyword line the grammar never
#: sees. It is also the label Chub Toad's printed sentence gets.
BUSHIDO_LABEL = "triggered_pump"

#: CR 702.45a's condition, spelled as the bare joined row of the "whenever"
#: table (``engine/whenever_triggers.py``) spells it — no ``blocked_filter`` and
#: no ``blocker_filter``, which is what makes both dispatchers fire it once for
#: the block rather than once per creature on the other side of it.
_CONDITION_TEXT = "whenever this creature blocks or becomes blocked"

#: "bushido 2" as it survives ``normalize_creature_line`` — lowercased, with
#: the reminder text already stripped. The number is the whole parameter.
_BUSHIDO_PART = re.compile(r"^bushido (\d+)$")


def bushido_amount(part: str) -> int | None:
    """The N of one normalized keyword-line part, or None if it isn't bushido.

    Also the keyword-line gate's admission test
    (``keyword_lines._argument_keyword_ability``): a "bushido" with no number
    is not a line this module implements.
    """
    match = _BUSHIDO_PART.match(part.strip())
    return int(match.group(1)) if match else None


def bushido_amounts(keyword_line: str) -> tuple[int, ...]:
    """Every instance of bushido on one comma-joined keyword line (CR 702.45b).

    "Double strike, bushido 2" (Kenzo the Hardhearted, whose printed semicolon
    ``normalize_creature_line`` turns into a comma) is one instance; a line
    naming bushido twice is two, and each gets its own ability.
    """
    amounts = []
    for part in keyword_line.split(","):
        amount = bushido_amount(part)
        if amount is not None:
            amounts.append(amount)
    return tuple(amounts)


def bushido_triggers(keyword_line: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered abilities CR 702.45a says *are* the bushido on this line,
    one per instance (CR 702.45b)."""
    return tuple(
        ParsedTriggeredAbility(
            source_line=f"bushido {amount}",
            condition=TriggerCondition(
                kind="creature_blocks_or_blocked_by",
                trigger="whenever",
                raw_text=_CONDITION_TEXT,
            ),
            instruction=OracleInstruction(
                BUSHIDO_KIND, f"bushido {amount}",
                {"power": amount, "toughness": amount},
            ),
            supported=True,
            effect_kind=BUSHIDO_LABEL,
        )
        for amount in bushido_amounts(keyword_line)
    )


#: "Fumiko the Lowblood has bushido X, where X is the number of attacking
#: creatures." — a card granting itself bushido with a counted N, once the
#: short self-reference is written out (``engine/self_reference.py``) and the
#: reminder text is stripped. The subject is the card's own name or "this
#: creature"; the count clause is the grammar's to read.
_BUSHIDO_X_LINE = re.compile(
    r"^(?P<subject>.+?) has bushido x, where x is (?P<count>.+?)\.?$",
    re.IGNORECASE,
)

_REMINDER = re.compile(r"\([^)]*\)")


def expand_bushido_x_line(line: str, card_name: str | None) -> str | None:
    """CR 702.45a's sentence for a card that has "bushido X, where X is …",
    or None for any other line.

    CR 702.45a defines "Bushido N" as "Whenever this creature blocks or
    becomes blocked, it gets +N/+N until end of turn", so bushido X is that
    sentence with X — and X is counted as the ability resolves (Fumiko's
    2005-02-01 ruling: "The bushido bonus is calculated each time Fumiko's
    bushido trigger resolves, based on the number of attackers at that
    time"), which is how the grammar reads a pump's "where X is" clause.
    The sentence is Chub Toad's with a counted X, so the block dispatchers,
    the pump handler and the AI's blocked-pump reading meet a known ability;
    a count the grammar cannot read refuses the rewritten line, naming it.
    """
    stripped = " ".join(_REMINDER.sub("", line or "").split()).strip()
    match = _BUSHIDO_X_LINE.match(stripped)
    if match is None:
        return None
    subject = match.group("subject").strip().lower()
    if subject != "this creature" and (
        card_name is None or subject != card_name.strip().lower()
    ):
        return None
    return (
        f"{_CONDITION_TEXT[0].upper()}{_CONDITION_TEXT[1:]}, it gets +X/+X "
        f"until end of turn, where X is {match.group('count')}."
    )


def expand_bushido_x_lines(oracle_text: str, card_name: str | None) -> str:
    """*oracle_text* with every "has bushido X, where X is …" self-grant
    rewritten to its rules text; text without one is returned unchanged."""
    if not oracle_text or "bushido x" not in oracle_text.lower():
        return oracle_text
    return "\n".join(
        expand_bushido_x_line(line, card_name) or line
        for line in oracle_text.split("\n")
    )


def bushido_points(card) -> int:
    """How many points of bushido *card* has: the N of every instance its
    keyword lines state, summed (Takeno, Samurai General's "for each point of
    bushido it has").

    *card* is what a permanent **says** — ``Permanent.effective_card`` — so a
    granted "Bushido 1" (Sensei Golden-Tail, folded into the rules text by
    ``keywords.GRANTED_ABILITY_LINES``) counts, and one an effect struck out
    (``REMOVED_ABILITY_KEYWORDS``, "loses all abilities") does not. The keyword
    lines are the ones the compiler's keyword-line gate admits, read off the
    rewritten lines every reader of a card's lines starts from (CLAUDE.md), so
    what is counted is exactly what triggers.
    """
    return _bushido_points(card.name, card.oracle_text or "", card.is_legendary)


@compilation_cache
@lru_cache(maxsize=None)
def _bushido_points(name: str, oracle_text: str, legendary: bool) -> int:
    # Cached on the text, which is all the answer reads, and registered with
    # the compilation caches because the keyword-line gate it asks reads the
    # keyword registry (``printed_characteristics._printed_abilities_cached``'s
    # arrangement). The lord pass asks it for every Samurai on every recompute.
    if "bushido" not in oracle_text.lower():
        return 0
    from .keyword_lines import _is_supported_keyword_line
    from .line_normalization import normalize_creature_line
    from .line_rewrites import expand_ability_lines

    return sum(
        sum(bushido_amounts(normalize_creature_line(line)))
        for line in expand_ability_lines(
            oracle_text, card_name=name, legendary=legendary
        ).splitlines()
        if line.strip() and _is_supported_keyword_line(line)
    )


__all__ = [
    "BUSHIDO_KIND",
    "BUSHIDO_LABEL",
    "bushido_amount",
    "bushido_amounts",
    "bushido_points",
    "bushido_triggers",
    "expand_bushido_x_line",
    "expand_bushido_x_lines",
]
