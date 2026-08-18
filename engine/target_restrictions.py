"""Printed restrictions on what a spell may *choose* as its target (CR 601.2c).

A different question from CR 702.16's protection, from hexproof and from
shroud: those are properties of the object being aimed at and are asked of every
spell alike. This is a restriction the **spell itself** prints about its own
targeting — "You can't choose an untapped creature as this spell's target as you
cast it" (Enthralling Hold) — and it applies to nothing else on the board.

Text-keyed and derived, in the model ``cast_restrictions.py`` uses for timing
gates: the printed noun phrase is read by the grammar's noun parser into the
same filter payload every other narrowing travels as, so a card printed with a
different phrase ("a tapped artifact", "a creature you control") needs no code
here. What the phrase *is* stays one reading — the one ``subject_matches``
answers — rather than a second regex that could disagree with the first.

Two callers, and they must be the same rule: the cast path, which refuses an
illegal choice (CR 601.2c makes the spell uncastable, not merely ineffective),
and the legality enumerator, which decides what a player is offered. A
restriction only the first knew about would show a target the game then refuses.
"""

from __future__ import annotations

import re

_RESTRICTION = re.compile(
    r"^you can't choose (?P<subject>.+?) as this spell's target as you cast it$"
)

#: The claim string the Aura support gate and the parse-coverage report use.
CLAIM = "target_restrictions"


def target_restriction_filter(oracle_text: str) -> dict | None:
    """The filter payload naming what *oracle_text* forbids as a target.

    None when the card prints no such line **or** when it prints one whose noun
    phrase the matcher cannot answer — the second is a refusal, not an absence,
    and it reaches the caller as an unclaimed line so the card reports
    unsupported. A phrase admitted but untestable would be a restriction the
    cast path silently ignores, which is the one direction a targeting rule must
    never fail in: it would let the spell take exactly the target the card
    forbids.
    """
    from .grammar import subject_filter_payload

    for line in (oracle_text or "").split("\n"):
        match = _RESTRICTION.match(line.strip().lower().rstrip("."))
        if match is None:
            continue
        return subject_filter_payload(match.group("subject"))
    return None


def target_restriction_line(normalized_line: str) -> bool:
    """Whether one printed line is a targeting restriction this module carries
    out **in full**.

    Asked by the Aura support gate. It re-reads the phrase rather than taking a
    parsed payload, so the gate and the dispatch cannot come to describe
    different cards — the same arrangement `enter_effect_line` makes.
    """
    from .grammar import subject_filter_payload

    match = _RESTRICTION.match(normalized_line.strip().lower().rstrip("."))
    if match is None:
        return False
    return subject_filter_payload(match.group("subject")) is not None


def forbidden_target(game, card, permanent, caster_index: int) -> bool:
    """Whether *card*'s printed restriction forbids choosing *permanent*.

    Through ``subject_matches``, which is what makes "an untapped creature" and
    "a creature you control" one rule with the seat and the board it needs
    (CR 109.5). *caster_index* is the observer: the spell's controller is who
    "you control" is relative to as the spell is cast.
    """
    from .subject_filters import subject_matches

    described = target_restriction_filter(card.oracle_text)
    if not described:
        return False
    return subject_matches(game, permanent, described, observer=caster_index)


__all__ = [
    "CLAIM",
    "forbidden_target",
    "target_restriction_filter",
    "target_restriction_line",
]
