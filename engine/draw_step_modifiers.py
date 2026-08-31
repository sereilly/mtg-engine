"""Text-keyed draw-step bonus draws (CR 504).

"At the beginning of each player's draw step, [if this artifact is untapped,]
that player draws an additional card." — Howling Mine's wording, and the
template a long line of cards reprints. The bonus is derived from oracle text
here rather than registered per card name, so a card printed with the template
needs no registration.

Only the symmetric bonus-draw template lives here. Island Sanctuary's
"instead you may skip that draw" remains a name-keyed hook: what it grants is
a specific protection quality ("except by creatures with flying and/or
islandwalk"), and until a second card grants a *different* quality there is
nothing to generalize over — deriving the trigger from text while the effect
stays hardcoded would only move the card-specificity out of sight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .oracle_types import _NUMBER_WORDS


@dataclass(frozen=True)
class DrawStepBonus:
    """Extra cards drawn in EVERY player's draw step.

    count             -- how many additional cards each player draws
    requires_untapped -- the bonus applies only while the source is untapped
    """

    count: int
    requires_untapped: bool = False


# "draws an additional card" is the printed wording; the shared number-word map
# carries "a" but not "an", so extend it here rather than mutating a table the
# rest of the parser reads.
_COUNT_WORDS: dict[str, int] = {**_NUMBER_WORDS, "an": 1}
_COUNT_WORD = "|".join(sorted(_COUNT_WORDS, key=len, reverse=True))

_EXTRA_DRAW = re.compile(
    r"^at the beginning of each player's draw step, "
    r"(?P<untapped>if this [a-z ]*?is untapped, )?"
    rf"that player draws (?P<count>{_COUNT_WORD}) additional cards?$"
)


@lru_cache(maxsize=None)
def draw_step_bonus_for(oracle_text: str) -> DrawStepBonus | None:
    """The per-draw-step bonus *oracle_text* grants every player, or None.

    Cached on the text itself, which is immutable on a ``CardDefinition``, so
    the draw step's per-permanent scan stays as cheap as the name-keyed lookup
    it replaced.
    """
    if "draw step" not in oracle_text.lower():
        return None
    for raw_line in oracle_text.lower().split("\n"):
        match = _EXTRA_DRAW.match(raw_line.strip().rstrip("."))
        if match is not None:
            return DrawStepBonus(
                count=_COUNT_WORDS[match.group("count")],
                requires_untapped=match.group("untapped") is not None,
            )
    return None


@dataclass(frozen=True)
class DrawStepSkip:
    """An optional skip of the whole draw step, and what taking it buys.

    CR 504 with CR 614: "If you would begin your draw step, you may skip that
    step instead. If you do, <rider>." The skip is the template — a card can
    print it with any rider — so the *trigger* is derived from text here while
    the rider is read into a field this module knows how to honour.

    ``life_gain`` is the only rider implemented, and a rider this cannot read
    makes the whole template refuse (``draw_step_skip_for`` returns None), which
    costs the card its support rather than skipping the step and quietly
    dropping what the skip was *for*. That is the same rule every narrowing in
    the engine follows: a clause the dispatcher cannot carry out refuses at
    compile time instead of being ignored.

    Deliberately **not** merged with Island Sanctuary's `DrawStepModifier` hook.
    The two are close but not the same rule — Island Sanctuary replaces the
    *draw* ("if you would draw a card during your draw step"), this replaces the
    *step* — and its rider grants a protection quality no table yet reads. When
    a third card lands on either side, that is the moment to see whether one
    reader covers both; a merge now would be a guess about which of the two
    shapes the next card prints.
    """

    life_gain: int = 0


_SKIP_STEP = re.compile(
    r"^if you would begin your draw step, you may skip that step instead$"
)
#: "Skip your draw step." (Necropotence.) The **mandatory** twin of the offer
#: above, and its own line rather than a flag on that one: nothing is offered
#: and nothing is bought, so there is no rider to read and no choice to answer.
#: A static ability of the permanent (CR 614.10 — a skip is a replacement
#: effect), so like every other derivation table here the step reads the
#: permanent's own text and there is nothing to arm or clear.
_SKIP_DRAW_STEP = re.compile(r"^skip your draw step$")
#: The rider sentences this module can carry out. A rider outside it refuses.
_SKIP_RIDER_LIFE = re.compile(rf"^if you do, you gain (?P<count>\d+|{_COUNT_WORD}) life$")


@lru_cache(maxsize=None)
def draw_step_skip_for(oracle_text: str) -> DrawStepSkip | None:
    """The optional draw-step skip *oracle_text* offers its controller, or None.

    None both for "this card does not print the template" and for "it prints a
    rider nothing here implements" — the caller cannot tell them apart and does
    not need to, because both mean *this module does not carry this card out*.
    The support gate reads the same function, so the second case is a card
    reported unsupported naming its clause rather than one that skips a step and
    forgets its rider.
    """
    lowered = oracle_text.lower()
    if "draw step" not in lowered:
        return None
    sentences = [
        sentence.strip().rstrip(".")
        for line in lowered.split("\n")
        for sentence in line.split(". ")
    ]
    for index, sentence in enumerate(sentences):
        if not _SKIP_STEP.match(sentence):
            continue
        rider = sentences[index + 1] if index + 1 < len(sentences) else ""
        match = _SKIP_RIDER_LIFE.match(rider)
        if match is None:
            return None
        count = match.group("count")
        return DrawStepSkip(
            life_gain=int(count) if count.isdigit() else _COUNT_WORDS[count]
        )
    return None


def skips_own_draw_step(oracle_text: str) -> bool:
    """Whether *oracle_text* makes its controller skip their draw step.

    Read by ``phases/draw_step.py`` and by the support gate, so what is
    enforced and what is claimed cannot drift — the same pairing every other
    table here uses.
    """
    lowered = oracle_text.lower()
    if "draw step" not in lowered:
        return False
    return any(
        _SKIP_DRAW_STEP.match(line.strip().rstrip("."))
        for line in lowered.split("\n")
    )


def draw_step_skip_line(normalized_line: str) -> bool:
    """Whether *normalized_line* is one of the two sentences the template owns.

    Read by the support gate and by `scripts/parse_coverage.py`, so what is
    implemented and what is claimed cannot drift — the same pairing
    `enter_effect_line` uses.
    """
    line = normalized_line.strip().lower().rstrip(".")
    return bool(
        _SKIP_STEP.match(line)
        or _SKIP_RIDER_LIFE.match(line)
        or _SKIP_DRAW_STEP.match(line)
    )
